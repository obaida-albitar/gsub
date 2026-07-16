"""Command pattern implementation for undo/redo functionality."""

from .command import Command, CommandManager, CompositeCommand
from .subtitle_commands import (
    AddEntryCommand,
    RemoveEntryCommand,
    EditTextCommand,
    EditTimingCommand,
    DuplicateEntryCommand,
    MoveEntryCommand,
    TimeShiftCommand,
    EditMarginsCommand,
    SortByTimeCommand,
)

from .ass_commands import (
    ReplaceASSHeaderCommand,
)

from .style_commands import (
    EditStyleCommand,
)

from .bulk_style_commands import (
    BulkEditStyleCommand,
)

__all__ = [
    'Command',
    'CommandManager',
    'CompositeCommand',
    'AddEntryCommand',
    'RemoveEntryCommand',
    'EditTextCommand',
    'EditTimingCommand',
    'DuplicateEntryCommand',
    'MoveEntryCommand',
    'TimeShiftCommand',

    'ReplaceASSHeaderCommand',

    'EditStyleCommand',
    'BulkEditStyleCommand',
    'EditMarginsCommand',
    'SortByTimeCommand',
]
