"""GTK-free state for a continuous, document-local proofreading session.

Review tokens are private runtime attributes: deepcopy-based undo commands carry
them forward, while subtitle parsers/serializers never write them to the file.
An ignored warning also includes the cue's content, so editing that cue brings
the warning back instead of hiding a newly introduced problem.
"""

from dataclasses import dataclass
from uuid import uuid4

from gsub.commands.text_commands import RebalanceTextCommand
from gsub.quality import QualityIssue, QualitySettings, check_quality
from gsub.text_operations import rebalance_text


_TOKEN_ATTR = "_gsub_quality_review_token"
REBALANCE_CODES = frozenset(("text.line_length", "text.line_count"))


def _fingerprint(entry):
    return (entry.text, entry.start_time.total_milliseconds,
            entry.end_time.total_milliseconds, entry.style, entry.layer,
            entry.actor, entry.effect, entry.margin_l, entry.margin_r,
            entry.margin_v)


@dataclass(frozen=True)
class RebalancePreview:
    document_id: int
    entry_token: str
    fingerprint: tuple
    before: str
    after: str
    max_line_length: int


class QualityReview:
    """Filter, navigate and ignore issues without changing the subtitle file."""

    def __init__(self, document, settings=None):
        self.document = document
        self.settings = settings or QualitySettings()
        self.filter_code = None
        self.all_issues = []
        self.issues = []
        self.current_index = -1
        self._dismissed = set()
        self._known_entries = {}
        self._current_key = None
        self.refresh()

    def _assign_tokens(self):
        groups = {}
        for entry in self.document.entries:
            token = getattr(entry, _TOKEN_ATTR, None)
            if not isinstance(token, str):
                token = uuid4().hex
                setattr(entry, _TOKEN_ATTR, token)
            groups.setdefault(token, []).append(entry)
        known = {}
        for token, entries in groups.items():
            # Duplicating a cue deepcopies its token too. Prefer the original
            # live object when available, then give each new copy its own ID.
            old = self._known_entries.get(token)
            keeper = next((entry for entry in entries if entry is old), entries[0])
            known[token] = keeper
            for entry in entries:
                if entry is keeper:
                    continue
                new_token = uuid4().hex
                setattr(entry, _TOKEN_ATTR, new_token)
                known[new_token] = entry
        self._known_entries = known

    def issue_key(self, issue):
        entry = self.document.entries[issue.position]
        related = None
        if issue.related_position is not None:
            neighbor = self.document.entries[issue.related_position]
            related = (getattr(neighbor, _TOKEN_ATTR), _fingerprint(neighbor))
        limit_name = {
            "text.reading_speed": "max_cps", "text.line_length": "max_chars_per_line",
            "text.line_count": "max_lines", "timing.too_short": "min_duration_ms",
            "timing.too_long": "max_duration_ms", "timing.small_gap": "min_gap_ms",
        }.get(issue.code)
        limit = getattr(self.settings, limit_name) if limit_name else None
        # Messages can contain cue numbers. Those change after unrelated
        # insertions, so the stable key describes the actual state instead.
        return (getattr(entry, _TOKEN_ATTR), issue.code, _fingerprint(entry),
                related, limit, issue.severity)

    @property
    def current_issue(self) -> QualityIssue | None:
        if 0 <= self.current_index < len(self.issues):
            return self.issues[self.current_index]
        return None

    @property
    def ignored_count(self):
        return sum(self.issue_key(issue) in self._dismissed
                   for issue in self.all_issues)

    def refresh(self):
        previous_index = self.current_index
        self._assign_tokens()
        self.all_issues = check_quality(self.document, self.settings)
        self.issues = [issue for issue in self.all_issues
                       if self.issue_key(issue) not in self._dismissed
                       and (self.filter_code is None or issue.code == self.filter_code)]
        keys = [self.issue_key(issue) for issue in self.issues]
        if self._current_key in keys:
            self.current_index = keys.index(self._current_key)
        else:
            self.current_index = min(max(0, previous_index), len(self.issues) - 1)
        self._remember_current()

    def _remember_current(self):
        issue = self.current_issue
        self._current_key = self.issue_key(issue) if issue is not None else None

    def set_filter(self, code):
        self.filter_code = code
        self.refresh()

    def select_key(self, key):
        for index, issue in enumerate(self.issues):
            if self.issue_key(issue) == key:
                self.current_index = index
                self._remember_current()
                return issue
        return None

    def move(self, offset):
        if self.issues:
            self.current_index = (self.current_index + offset) % len(self.issues)
            self._remember_current()
        return self.current_issue

    def dismiss_current(self):
        if self.current_issue is not None:
            self._dismissed.add(self.issue_key(self.current_issue))
            self.refresh()

    def reset_ignored(self):
        self._dismissed.clear()
        self.refresh()

    def preview_rebalance(self):
        issue = self.current_issue
        if issue is None or issue.code not in REBALANCE_CODES:
            raise ValueError("Select a line-length or line-count issue to rebalance.")
        entry = self.document.entries[issue.position]
        after = rebalance_text(entry.text, self.document.format,
                               self.settings.max_chars_per_line)
        if after == entry.text:
            raise ValueError("This subtitle is already balanced; edit or split it manually.")
        return RebalancePreview(id(self.document), getattr(entry, _TOKEN_ATTR),
            _fingerprint(entry), entry.text, after, self.settings.max_chars_per_line)

    def command_for_preview(self, preview):
        """Validate the preview and build a fresh command, keeping newer edits.

        Commands snapshot the whole entry list. Constructing one only now,
        rather than storing a command at preview time, preserves edits made to
        other cues while the preview was open.
        """
        if preview.document_id != id(self.document):
            raise ValueError("The document changed. Preview the fix again.")
        matches = [(position, entry) for position, entry in enumerate(self.document.entries)
                   if getattr(entry, _TOKEN_ATTR, None) == preview.entry_token]
        if len(matches) != 1 or _fingerprint(matches[0][1]) != preview.fingerprint:
            raise ValueError("The subtitle changed. Preview the fix again.")
        if preview.max_line_length != self.settings.max_chars_per_line:
            raise ValueError("The quality limits changed. Preview the fix again.")
        command = RebalanceTextCommand(self.document, [matches[0][0]],
                                       preview.max_line_length)
        if command._after[matches[0][0]].text != preview.after:
            raise ValueError("The subtitle changed. Preview the fix again.")
        return command
