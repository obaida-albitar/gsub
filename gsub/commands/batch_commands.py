"""Atomic, snapshot-based undo for operations spanning several batch files."""

from copy import deepcopy

from gsub.batch_logic import apply_resolution, apply_style_properties
from gsub.commands.command import Command


class BatchOperationsCommand(Command):
    """Apply one set of operations as a single undo step.

    Items only need ``document`` and ``modified`` attributes; this module
    deliberately does not import GTK. All work is prepared on copies before
    touching any live document. Snapshots also restore timings clamped at zero
    exactly, which cannot be achieved by applying an inverse time shift.
    """

    def __init__(self, items, *, offset_ms=None, resolution=None,
                 target_styles=(), style_properties=None):
        self._changes = []
        seen = set()
        names = tuple(target_styles)
        for item in items:
            if id(item.document) in seen:
                continue
            seen.add(id(item.document))
            before = deepcopy(item.document.__dict__)
            prepared = deepcopy(item.document)
            if offset_ms is not None:
                for entry in prepared.entries:
                    entry.shift_time(offset_ms)
            if resolution is not None:
                apply_resolution(prepared, *resolution)
            if style_properties:
                apply_style_properties(prepared, names, style_properties)
            if prepared.__dict__ == before:
                continue
            prepared.modified = True
            self._changes.append((item, before, deepcopy(prepared.__dict__), item.modified))

    @property
    def changed(self):
        return bool(self._changes)

    @property
    def changed_count(self):
        return len(self._changes)

    @staticmethod
    def _restore(item, state, modified):
        # Keep the document object so existing UI references remain valid.
        item.document.__dict__.clear()
        item.document.__dict__.update(deepcopy(state))
        item.modified = modified

    def execute(self):
        for item, _before, after, _modified in self._changes:
            self._restore(item, after, True)

    def undo(self):
        for item, before, _after, modified in self._changes:
            self._restore(item, before, modified)

    def description(self):
        count = self.changed_count
        return f"Apply batch operations to {count} file{'s' if count != 1 else ''}"
