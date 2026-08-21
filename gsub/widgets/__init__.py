"""UI widgets for the subtitle editor."""

from .subtitle_list import SubtitleListView
from .editor_panel import EditorPanel
from .dialogs import (
    TimeShiftDialog,
    ASSInfoDialog,
    ASSStylesDialog,
    BulkApplyStyleDialog,
    BatchStylePropsDialog,
    TrackSelectionDialog,
)
from .video_player import VideoPlayerWidget
from .home_screen import HomeScreenView
from .batch_file_list import BatchFileList
from .batch_operations_panel import BatchOperationsPanel
from .batch_confirm_dialog import BatchConfirmDialog
from .style_props_editor import GsubStylePropsEditor

__all__ = [
    'SubtitleListView', 'EditorPanel', 'TimeShiftDialog', 'ASSInfoDialog',
    'ASSStylesDialog', 'BulkApplyStyleDialog', 'BatchStylePropsDialog',
    'TrackSelectionDialog', 'VideoPlayerWidget', 'HomeScreenView',
    'BatchFileList', 'BatchOperationsPanel', 'BatchConfirmDialog',
    'GsubStylePropsEditor',
]
