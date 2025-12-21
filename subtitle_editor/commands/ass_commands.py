"""Undoable commands for ASS/SSA document metadata and styles."""

from __future__ import annotations

import copy
from dataclasses import replace as dc_replace
from typing import Optional, Dict, Any, List

from subtitle_editor.commands.command import Command
from subtitle_editor.models import SubtitleDocument, ASSStyle


class SetMetadataCommand(Command):
    """Set a Script Info metadata key/value (undoable)."""

    def __init__(self, document: SubtitleDocument, key: str, value: str):
        self.document = document
        self.key = key
        self.value = value
        self._old_present: bool = False
        self._old_value: Optional[str] = None

    def execute(self):
        self._old_present = self.key in self.document.metadata
        self._old_value = self.document.metadata.get(self.key)
        self.document.set_metadata(self.key, self.value)

    def undo(self):
        if self._old_present:
            # restore previous value
            self.document.metadata[self.key] = self._old_value if self._old_value is not None else ""
            self.document.modified = True
        else:
            self.document.remove_metadata(self.key)

    def description(self) -> str:
        return f"Set metadata '{self.key}'"


class RemoveMetadataCommand(Command):
    """Remove a Script Info metadata key (undoable)."""

    def __init__(self, document: SubtitleDocument, key: str):
        self.document = document
        self.key = key
        self._old_present: bool = False
        self._old_value: Optional[str] = None

    def execute(self):
        self._old_present = self.key in self.document.metadata
        self._old_value = self.document.metadata.get(self.key)
        self.document.remove_metadata(self.key)

    def undo(self):
        if self._old_present:
            self.document.set_metadata(self.key, self._old_value)

    def description(self) -> str:
        return f"Remove metadata '{self.key}'"


class UpsertStyleCommand(Command):
    """Insert or update an ASS style by name (undoable)."""

    def __init__(self, document: SubtitleDocument, style: ASSStyle):
        self.document = document
        self.style = copy.deepcopy(style)
        self._old_style: Optional[ASSStyle] = None
        self._was_insert: bool = False

    def execute(self):
        self._old_style = self.document.upsert_style(self.style)
        self._was_insert = self._old_style is None

    def undo(self):
        if self._was_insert:
            # remove newly added style
            self.document.remove_style(self.style.name)
            return

        # restore replaced style
        if self._old_style is not None:
            self.document.upsert_style(self._old_style)

    def description(self) -> str:
        return f"Update style '{self.style.name}'"


class RemoveStyleCommand(Command):
    """Remove an ASS style by name (undoable)."""

    def __init__(self, document: SubtitleDocument, name: str, fallback: str = "Default"):
        self.document = document
        self.name = name
        self.fallback = fallback
        self._removed_style: Optional[ASSStyle] = None
        self._old_entry_styles: Optional[List[Optional[str]]] = None

    def execute(self):
        # capture current styles per entry for perfect undo
        self._old_entry_styles = [e.style for e in self.document.entries]
        self._removed_style = self.document.remove_style(self.name, fallback=self.fallback)

    def undo(self):
        if self._removed_style is None:
            return

        # restore style
        self.document.upsert_style(self._removed_style)

        # restore entry style references
        if self._old_entry_styles is not None:
            for entry, old_style in zip(self.document.entries, self._old_entry_styles):
                entry.style = old_style
        self.document.modified = True

    def description(self) -> str:
        return f"Remove style '{self.name}'"


class RenameStyleCommand(Command):
    """Rename an ASS style by name and update all dialogue entries (undoable)."""

    def __init__(self, document: SubtitleDocument, old_name: str, new_name: str):
        self.document = document
        self.old_name = old_name
        self.new_name = new_name

    def execute(self):
        self.document.rename_style(self.old_name, self.new_name)

    def undo(self):
        self.document.rename_style(self.new_name, self.old_name)

    def description(self) -> str:
        return f"Rename style '{self.old_name}' -> '{self.new_name}'"


class ReplaceASSHeaderCommand(Command):
    """Replace Script Info metadata and the complete style list as one undo step.

    This is intended for UI use where the user edits the full state.
    """

    def __init__(
        self,
        document: SubtitleDocument,
        *,
        metadata: Optional[Dict[str, str]] = None,
        styles: Optional[List[ASSStyle]] = None,
        fallback_style: str = "Default",
    ):
        self.document = document
        self.metadata = copy.deepcopy(metadata or {})
        self.styles = [copy.deepcopy(s) for s in (styles or [])]
        self.fallback_style = fallback_style

        self._old_metadata: Optional[Dict[str, str]] = None
        self._old_styles: Optional[List[ASSStyle]] = None
        self._old_entry_styles: Optional[List[Optional[str]]] = None

    def execute(self):
        self._old_metadata = copy.deepcopy(self.document.metadata)
        self._old_styles = copy.deepcopy(self.document.styles)
        self._old_entry_styles = [e.style for e in self.document.entries]

        self.document.metadata = copy.deepcopy(self.metadata)
        self.document.styles = copy.deepcopy(self.styles)

        # Always keep at least one style.
        if not self.document.styles:
            self.document.styles.append(ASSStyle(name=self.fallback_style or "Default"))

        style_names = {s.name for s in self.document.styles}

        # Ensure fallback exists if it's needed.
        if self.fallback_style and self.fallback_style not in style_names:
            self.document.styles.append(ASSStyle(name=self.fallback_style))
            style_names.add(self.fallback_style)

        # Normalize entry styles to fallback if style was removed.
        for entry in self.document.entries:
            if entry.style and entry.style not in style_names:
                entry.style = self.fallback_style or "Default"

        self.document.modified = True

    def undo(self):
        if self._old_metadata is None or self._old_styles is None:
            return

        self.document.metadata = copy.deepcopy(self._old_metadata)
        self.document.styles = copy.deepcopy(self._old_styles)
        if self._old_entry_styles is not None:
            for entry, old_style in zip(self.document.entries, self._old_entry_styles):
                entry.style = old_style
        self.document.modified = True

    def description(self) -> str:
        return "Replace ASS metadata/styles"


class UpdateASSHeaderCommand(Command):
    """Apply multiple metadata updates and style upserts as one undo step."""

    def __init__(
        self,
        document: SubtitleDocument,
        metadata_updates: Optional[Dict[str, Optional[str]]] = None,
        style_upserts: Optional[List[ASSStyle]] = None,
    ):
        self.document = document
        self.metadata_updates = metadata_updates or {}
        self.style_upserts = [copy.deepcopy(s) for s in (style_upserts or [])]

        self._old_metadata: Optional[Dict[str, str]] = None
        self._old_styles: Optional[List[ASSStyle]] = None
        self._old_entry_styles: Optional[List[Optional[str]]] = None

    def execute(self):
        self._old_metadata = copy.deepcopy(self.document.metadata)
        self._old_styles = copy.deepcopy(self.document.styles)
        self._old_entry_styles = [e.style for e in self.document.entries]

        for k, v in self.metadata_updates.items():
            if v is None:
                self.document.remove_metadata(k)
            else:
                self.document.set_metadata(k, v)

        for style in self.style_upserts:
            self.document.upsert_style(style)

        self.document.modified = True

    def undo(self):
        if self._old_metadata is None or self._old_styles is None:
            return

        self.document.metadata = copy.deepcopy(self._old_metadata)
        self.document.styles = copy.deepcopy(self._old_styles)
        if self._old_entry_styles is not None:
            for entry, old_style in zip(self.document.entries, self._old_entry_styles):
                entry.style = old_style
        self.document.modified = True

    def description(self) -> str:
        return "Update ASS metadata/styles"
