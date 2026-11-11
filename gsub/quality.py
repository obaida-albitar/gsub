"""Readability checks shared by the editor and document quality dialog.

These are configurable editorial suggestions, not format errors. They never
change a document. Character counts include spaces and punctuation, exclude
line separators/formatting, and count combining marks with their base letter.
"""

from dataclasses import asdict, dataclass, fields
import html
import math
import re
import unicodedata

from gsub.models import SubtitleDocument, SubtitleFormat
from gsub.parsers.ass_tags import BLOCK_PATTERN, parse_override_block


@dataclass(frozen=True)
class QualitySettings:
    max_cps: float = 20.0
    max_chars_per_line: int = 42
    max_lines: int = 2
    min_duration_ms: int = 1000
    max_duration_ms: int = 7000
    min_gap_ms: int = 80
    check_overlaps: bool = True

    def __post_init__(self):
        for name in ("max_cps", "max_chars_per_line", "max_lines",
                     "min_duration_ms", "max_duration_ms", "min_gap_ms"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be a number")
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be a finite nonnegative number")
            if name != "max_cps" and not isinstance(value, int):
                raise ValueError(f"{name} must be a whole number")
        if self.max_chars_per_line < 1 or self.max_lines < 1:
            raise ValueError("Line limits must be positive")
        if self.max_duration_ms < self.min_duration_ms:
            raise ValueError("Maximum duration must be at least the minimum duration")
        if not isinstance(self.check_overlaps, bool):
            raise ValueError("check_overlaps must be a boolean")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, values: dict | None) -> "QualitySettings":
        """Load user settings; damaged or obsolete configuration uses defaults."""
        if not isinstance(values, dict):
            return cls()
        names = {field.name for field in fields(cls)}
        try:
            return cls(**{k: v for k, v in values.items() if k in names})
        except (TypeError, ValueError):
            return cls()


@dataclass(frozen=True)
class TextMetrics:
    visible_text: str
    character_count: int
    line_lengths: tuple[int, ...]
    cps: float | None

    @property
    def line_count(self) -> int:
        return len(self.line_lengths)

    @property
    def longest_line(self) -> int:
        return max(self.line_lengths, default=0)


@dataclass(frozen=True)
class QualityIssue:
    position: int
    code: str
    message: str
    severity: str = "warning"
    related_position: int | None = None


_SRT_TAG = re.compile(r"</?(?:b|i|u|s|font)(?:\s+[^>]*?)?\s*>", re.I)
_SRT_BREAK = re.compile(r"<br\s*/?>", re.I)


def _ass_visible(text: str) -> tuple[str, bool]:
    """Ignore override/comment blocks and drawing runs, tracking top-level p/r."""
    chunks = []
    drawing = False
    had_drawing = False
    offset = 0
    for block in BLOCK_PATTERN.finditer(text):
        if not drawing:
            chunks.append(text[offset:block.start()])
        for tag in parse_override_block(block.group(1)):
            if tag.name == "p" and tag.args:
                try:
                    drawing = float(tag.args[0]) > 0
                    had_drawing |= drawing
                except ValueError:
                    pass
            elif tag.name == "r":
                drawing = False
        offset = block.end()
    if not drawing:
        chunks.append(text[offset:])
    return ("".join(chunks).replace(r"\N", "\n").replace(r"\n", "\n")
            .replace(r"\h", "\N{NO-BREAK SPACE}")), had_drawing


def visible_text(text: str, fmt: SubtitleFormat = SubtitleFormat.SRT) -> str:
    """Return displayed dialogue without modifying the source text."""
    if fmt in (SubtitleFormat.ASS, SubtitleFormat.SSA):
        text, _ = _ass_visible(text)
    else:
        text = html.unescape(_SRT_TAG.sub("", _SRT_BREAK.sub("\n", text)))
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _character_count(text: str) -> int:
    return sum(not unicodedata.combining(ch)
               and unicodedata.category(ch) not in ("Cf", "Mn", "Me") for ch in text)


def text_metrics(text: str, duration_ms: int,
                 fmt: SubtitleFormat = SubtitleFormat.SRT) -> TextMetrics:
    clean = visible_text(text, fmt)
    lines = tuple(_character_count(line.strip()) for line in clean.split("\n"))
    count = sum(lines)
    return TextMetrics(clean, count, lines, count * 1000 / duration_ms
                       if duration_ms > 0 else None)


def check_quality(document: SubtitleDocument,
                  settings: QualitySettings | None = None) -> list[QualityIssue]:
    """Check readability and chronological neighbors without mutating entries.

    ASS neighbors are compared within a style and layer, so a sign in a
    different style/layer does not make ordinary dialogue an overlap. Drawing
    only events are excluded; an empty override-only event is still flagged.
    """
    settings = settings or QualitySettings()
    issues = []
    groups = {}
    is_ass = document.format in (SubtitleFormat.ASS, SubtitleFormat.SSA)
    for position, entry in enumerate(document.entries):
        metrics = text_metrics(entry.text, entry.duration_ms, document.format)
        if is_ass and not metrics.visible_text.strip() and _ass_visible(entry.text)[1]:
            continue

        def add(code, message, severity="warning"):
            issues.append(QualityIssue(position, code, message, severity))

        if not metrics.character_count:
            add("text.empty", "Subtitle has no visible text.")
        if entry.duration_ms <= 0:
            add("timing.invalid_duration", "End time must be after start time.", "error")
        elif entry.duration_ms < settings.min_duration_ms:
            add("timing.too_short", f"Duration {entry.duration_ms / 1000:.3f} s is below "
                f"{settings.min_duration_ms / 1000:.3f} s.")
        elif entry.duration_ms > settings.max_duration_ms:
            add("timing.too_long", f"Duration {entry.duration_ms / 1000:.3f} s exceeds "
                f"{settings.max_duration_ms / 1000:.3f} s.")
        if metrics.cps is not None and metrics.cps > settings.max_cps:
            add("text.reading_speed", f"Reading speed {metrics.cps:.1f} characters/s "
                f"exceeds {settings.max_cps:g}.")
        if metrics.longest_line > settings.max_chars_per_line:
            add("text.line_length", f"Longest line has {metrics.longest_line} characters "
                f"(limit {settings.max_chars_per_line}).")
        if metrics.line_count > settings.max_lines:
            add("text.line_count", f"Subtitle has {metrics.line_count} lines "
                f"(limit {settings.max_lines}).")
        if entry.duration_ms > 0:
            group = (entry.style or "Default", entry.layer) if is_ass else None
            groups.setdefault(group, []).append((entry.start_time.total_milliseconds,
                                                  entry.end_time.total_milliseconds, position))

    for entries in groups.values():
        # Furthest end catches containment (a long subtitle spanning many
        # shorter ones), while sorting keeps checks useful for unsorted files.
        furthest = None
        for start, end, position in sorted(entries):
            if furthest is not None:
                previous_end, previous_position = furthest
                gap = start - previous_end
                if gap < 0 and settings.check_overlaps:
                    issues.append(QualityIssue(position, "timing.overlap",
                        f"Overlaps subtitle {previous_position + 1} by "
                        f"{(min(end, previous_end) - start) / 1000:.3f} s.",
                        related_position=previous_position))
                elif 0 < gap < settings.min_gap_ms:
                    issues.append(QualityIssue(position, "timing.small_gap",
                        f"Gap after subtitle {previous_position + 1} is only {gap} ms "
                        f"(minimum {settings.min_gap_ms} ms).",
                        related_position=previous_position))
            if furthest is None or end > furthest[0]:
                furthest = (end, position)
    return sorted(issues, key=lambda issue: issue.position)
