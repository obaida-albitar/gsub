"""Undoable commands for per-entry style operations (ASS/SSA)."""

from __future__ import annotations

from subtitle_editor.commands.command import Command
from subtitle_editor.models import SubtitleDocument


class EditStyleCommand(Command):
    """Change the style name of a subtitle entry (undoable)."""

    def __init__(self, document: SubtitleDocument, position: int, new_style: str | None):
        self.document = document
        self.position = position
        self.new_style = new_style
        self.old_style = None

    def execute(self):
        if 0 <= self.position < len(self.document.entries):
            entry = self.document.entries[self.position]
            self.old_style = entry.style
            entry.style = self.new_style
            self.document.modified = True

    def undo(self):
        if self.old_style is not None and 0 <= self.position < len(self.document.entries):
            self.document.entries[self.position].style = self.old_style
            self.document.modified = True

    def description(self) -> str:
        return f"Change style of subtitle #{self.position + 1}"
