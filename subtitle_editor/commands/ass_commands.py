"""Undoable commands for ASS/SSA document metadata and styles."""

from __future__ import annotations

import copy
from dataclasses import replace as dc_replace
from typing import Optional, Dict, Any, List

from subtitle_editor.commands.command import Command
from subtitle_editor.models import SubtitleDocument, ASSStyle


class ReplaceASSHeaderCommand(Command):
    """Replace Script Info metadata, optional Aegisub garbage, and the complete style list as one undo step.

    This is intended for UI use where the user edits the full state.

    ``style_renames`` optionally maps old style names to new ones; dialogue
    entries referencing an old name are switched to the new one instead of
    falling back when the old name disappears from the style list.
    """

    def __init__(
        self,
        document: SubtitleDocument,
        *,
        metadata: Optional[Dict[str, str]] = None,
        aegisub_project_garbage: Optional[Dict[str, str]] = None,
        styles: Optional[List[ASSStyle]] = None,
        fallback_style: str = "Default",
        style_renames: Optional[Dict[str, str]] = None,
    ):
        self.document = document
        self.metadata = copy.deepcopy(metadata or {})
        self.aegisub_project_garbage = copy.deepcopy(aegisub_project_garbage or {})
        self.styles = [copy.deepcopy(s) for s in (styles or [])]
        self.fallback_style = fallback_style
        self.style_renames = dict(style_renames or {})

        self._old_metadata: Optional[Dict[str, str]] = None
        self._old_aegisub_project_garbage: Optional[Dict[str, str]] = None
        self._old_styles: Optional[List[ASSStyle]] = None
        self._old_entry_styles: Optional[List[Optional[str]]] = None

    def execute(self):
        self._old_metadata = copy.deepcopy(self.document.metadata)
        self._old_aegisub_project_garbage = copy.deepcopy(getattr(self.document, 'aegisub_project_garbage', {}) or {})
        self._old_styles = copy.deepcopy(self.document.styles)
        self._old_entry_styles = [e.style for e in self.document.entries]

        self.document.metadata = copy.deepcopy(self.metadata)
        self.document.aegisub_project_garbage = copy.deepcopy(self.aegisub_project_garbage)
        self.document.styles = copy.deepcopy(self.styles)

        # Always keep at least one style.
        if not self.document.styles:
            self.document.styles.append(ASSStyle(name=self.fallback_style or "Default"))

        style_names = {s.name for s in self.document.styles}

        # Ensure fallback exists if it's needed.
        if self.fallback_style and self.fallback_style not in style_names:
            self.document.styles.append(ASSStyle(name=self.fallback_style))
            style_names.add(self.fallback_style)

        # Apply explicit renames first so renamed styles keep their entries.
        for entry in self.document.entries:
            if entry.style in self.style_renames:
                entry.style = self.style_renames[entry.style]

        # Normalize entry styles to fallback if style was removed.
        for entry in self.document.entries:
            if entry.style and entry.style not in style_names:
                entry.style = self.fallback_style or "Default"

        self.document.modified = True

    def undo(self):
        if self._old_metadata is None or self._old_styles is None:
            return

        self.document.metadata = copy.deepcopy(self._old_metadata)
        if self._old_aegisub_project_garbage is not None:
            self.document.aegisub_project_garbage = copy.deepcopy(self._old_aegisub_project_garbage)
        self.document.styles = copy.deepcopy(self._old_styles)
        if self._old_entry_styles is not None:
            for entry, old_style in zip(self.document.entries, self._old_entry_styles):
                entry.style = old_style
        self.document.modified = True

    def description(self) -> str:
        return "Replace ASS metadata/styles"
