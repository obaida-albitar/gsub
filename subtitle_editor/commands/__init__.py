"""Command pattern implementation for undo/redo functionality."""

from .command import Command, CommandManager
from .subtitle_commands import (
    AddEntryCommand,
    RemoveEntryCommand,
    EditTextCommand,
    EditTimingCommand,
    DuplicateEntryCommand,
    MoveEntryCommand,
    TimeShiftCommand,
    BatchTimingCommand,
    EditMarginsCommand,
    SortByTimeCommand,
)

from .ass_commands import (
    SetMetadataCommand,
    RemoveMetadataCommand,
    UpsertStyleCommand,
    RemoveStyleCommand,
    RenameStyleCommand,
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
    'AddEntryCommand',
    'RemoveEntryCommand',
    'EditTextCommand',
    'EditTimingCommand',
    'DuplicateEntryCommand',
    'MoveEntryCommand',
    'TimeShiftCommand',
    'BatchTimingCommand',

    'SetMetadataCommand',
    'RemoveMetadataCommand',
    'UpsertStyleCommand',
    'RemoveStyleCommand',
    'RenameStyleCommand',
    'ReplaceASSHeaderCommand',

    'EditStyleCommand',
    'BulkEditStyleCommand',
    'EditMarginsCommand',
    'SortByTimeCommand',
]
