"""Undoable commands for bulk style operations (ASS/SSA)."""

from __future__ import annotations

from typing import List, Optional

from subtitle_editor.commands.command import Command
from subtitle_editor.models import SubtitleDocument


class BulkEditStyleCommand(Command):
    """Apply a style name to multiple entries (undoable as one step)."""

    def __init__(self, document: SubtitleDocument, positions: List[int], new_style: Optional[str]):
        self.document = document
        self.positions = sorted(set(int(p) for p in positions))
        self.new_style = new_style
        self._old_styles: dict[int, Optional[str]] = {}

    def execute(self):
        self._old_styles = {}
        for pos in self.positions:
            if 0 <= pos < len(self.document.entries):
                entry = self.document.entries[pos]
                self._old_styles[pos] = entry.style
                entry.style = self.new_style
        if self._old_styles:
            self.document.modified = True

    def undo(self):
        for pos, old_style in self._old_styles.items():
            if 0 <= pos < len(self.document.entries):
                self.document.entries[pos].style = old_style
        if self._old_styles:
            self.document.modified = True

    def description(self) -> str:
        return f"Bulk apply style to {len(self._old_styles)} subtitles"
