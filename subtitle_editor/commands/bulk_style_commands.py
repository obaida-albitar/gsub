"""Undoable commands for bulk style operations (ASS/SSA)."""

from __future__ import annotations

import copy
import dataclasses
from typing import Dict, List, Optional

from subtitle_editor.commands.command import Command
from subtitle_editor.models import ASSStyle, SubtitleDocument

# Style fields a batch property edit may touch, derived from the model so it
# stays in sync with ASSStyle. The name is excluded: it is the style's identity
# (used to locate the style), never a batch-editable property.
_EDITABLE_STYLE_FIELDS = {f.name for f in dataclasses.fields(ASSStyle)} - {'name'}


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


class BulkUpdateStylePropsCommand(Command):
    """Batch-update style definition properties on named styles (undoable)."""

    def __init__(self, document: SubtitleDocument, style_names: List[str], props: Dict[str, object]):
        self.document = document
        self.style_names = list(dict.fromkeys(style_names))
        # Ignore unknown keys defensively: only real ASSStyle fields apply.
        self.props = {key: value for key, value in props.items() if key in _EDITABLE_STYLE_FIELDS}
        self._old: dict[int, ASSStyle] = {}

    def execute(self):
        self._old = {}
        if not self.props:
            # Nothing editable to apply: a complete no-op (not even modified).
            return
        names = set(self.style_names)
        for idx, style in enumerate(self.document.styles):
            if style.name in names:
                self._old[idx] = copy.deepcopy(style)
                for field_name, value in self.props.items():
                    setattr(style, field_name, value)
        if self._old:
            self.document.modified = True

    def undo(self):
        # Styles are restored by list index, which stays valid because this
        # command never renames, adds, or removes styles (entries are targeted
        # by name and the list is only mutated in place).
        restored = False
        for idx, old in self._old.items():
            if 0 <= idx < len(self.document.styles):
                self.document.styles[idx] = copy.deepcopy(old)
                restored = True
        if restored:
            self.document.modified = True

    def description(self) -> str:
        count = len(self._old)
        return f"Batch update style properties on {count} style{'s' if count != 1 else ''}"
