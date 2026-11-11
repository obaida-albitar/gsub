"""Undoable split, merge, and reflow commands with exact entry snapshots."""

from copy import deepcopy

from gsub.commands.command import Command
from gsub.models import SubtitleDocument, TimeCode
from gsub.text_operations import is_ass, merge_texts, rebalance_text, split_text, visible_text


class _EntriesCommand(Command):
    """Store both states rather than trying to invert a lossy transformation."""

    def __init__(self, document: SubtitleDocument):
        self.document = document
        self._before = deepcopy(document.entries)
        self._after = deepcopy(document.entries)

    @property
    def changed(self) -> bool:
        return self._before != self._after

    def execute(self):
        if self.changed:
            self.document.entries[:] = deepcopy(self._after)
            self.document.modified = True

    def undo(self):
        if self.changed:
            self.document.entries[:] = deepcopy(self._before)
            self.document.modified = True

    def _reindex_after(self):
        for index, entry in enumerate(self._after, 1):
            entry.index = index


class SplitEntryCommand(_EntriesCommand):
    """Split a cue at its editor cursor and an optional video time (milliseconds)."""

    def __init__(self, document: SubtitleDocument, position: int,
                 text_offset: int, split_ms: int | None = None):
        super().__init__(document)
        if not 0 <= position < len(self._before):
            raise ValueError("Select a subtitle to split.")
        self.position = position
        original = self._before[position]
        if is_ass(document.format) and original.effect.lower().startswith(("scroll", "banner")):
            raise ValueError("Scrolling ASS effects cannot be split without changing their appearance.")
        left_text, right_text = split_text(original.text, document.format, text_offset)
        start = original.start_time.total_milliseconds
        end = original.end_time.total_milliseconds
        # ASS timestamps serialize in centiseconds. Choose a split that remains
        # strictly between both serialized endpoints as well as in memory.
        step = 10 if is_ass(document.format) else 1
        first = (start // step + 1) * step
        last = ((end - 1) // step) * step
        if first > last:
            raise ValueError("This subtitle is too short to split into two positive durations.")
        if split_ms is None or not start < split_ms < end:
            left_count = len(visible_text(left_text, document.format).strip())
            right_count = len(visible_text(right_text, document.format).strip())
            split_ms = start + (end - start) * left_count / (left_count + right_count)
        cut = min(last, max(first, round(split_ms / step) * step))
        left, right = deepcopy(original), deepcopy(original)
        left.text, right.text = left_text, right_text
        left.end_time = TimeCode.from_milliseconds(cut)
        right.start_time = TimeCode.from_milliseconds(cut)
        self.split_ms = cut
        self._after[position:position + 1] = [left, right]
        self._reindex_after()

    def description(self) -> str:
        return f"Split subtitle #{self.position + 1}"


class MergeEntriesCommand(_EntriesCommand):
    """Merge adjacent cues while retaining timing bounds and compatible metadata."""

    def __init__(self, document: SubtitleDocument, positions):
        super().__init__(document)
        self.positions = sorted(set(positions))
        if len(self.positions) < 2:
            raise ValueError("Select at least two adjacent subtitles to merge.")
        first, last = self.positions[0], self.positions[-1]
        if first < 0 or last >= len(self._before):
            raise ValueError("Select valid subtitles to merge.")
        if self.positions != list(range(first, last + 1)):
            raise ValueError("Select adjacent subtitles to merge.")
        entries = self._before[first:last + 1]
        if is_ass(document.format):
            def metadata(entry):
                return (entry.style or "Default", entry.margin_l, entry.margin_r,
                        entry.margin_v, entry.layer, entry.actor, entry.effect)

            if any(metadata(entry) != metadata(entries[0]) for entry in entries[1:]):
                raise ValueError(
                    "ASS subtitles must have the same style, speaker, layer, margins, "
                    "and effect to merge without losing their formatting."
                )
            if any(entry.effect.lower().startswith(("scroll", "banner")) for entry in entries):
                raise ValueError("Scrolling ASS effects cannot be merged safely.")
        merged = deepcopy(entries[0])
        merged.text = merge_texts([entry.text for entry in entries], document.format)
        merged.start_time = deepcopy(min(entries, key=lambda e: e.start_time.total_milliseconds).start_time)
        merged.end_time = deepcopy(max(entries, key=lambda e: e.end_time.total_milliseconds).end_time)
        if merged.duration_ms <= 0:
            raise ValueError("The merged subtitle must have a positive duration.")
        self._after[first:last + 1] = [merged]
        self._reindex_after()

    def description(self) -> str:
        return f"Merge {len(self.positions)} subtitles"


class RebalanceTextCommand(_EntriesCommand):
    """Rebalance selected cues as one undoable action."""

    def __init__(self, document: SubtitleDocument, positions, max_line_length: int = 42):
        super().__init__(document)
        self.positions = sorted(set(positions))
        if not self.positions or any(not 0 <= position < len(self._before)
                                     for position in self.positions):
            raise ValueError("Select subtitles to rebalance.")
        for position in self.positions:
            entry = self._after[position]
            entry.text = rebalance_text(entry.text, document.format, max_line_length)

    def description(self) -> str:
        return f"Rebalance text in {len(self.positions)} subtitle(s)"
