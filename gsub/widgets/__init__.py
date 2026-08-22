"""UI widgets for Gsub."""

import gi

gi.require_version('Adw', '1')

# Subclassing libadwaita types (e.g. AdwDialog) requires the libadwaita type
# system to be initialised before the class definitions execute. Doing it here
# makes importing gsub.widgets work in any order, independent of gsub.main.
# Adw.init() is idempotent, so the call in gsub.main is not a conflict.
from gi.repository import Adw

Adw.init()

from .subtitle_list import SubtitleListView  # noqa: E402
from .editor_panel import EditorPanel  # noqa: E402
from .dialogs import (  # noqa: E402
    TimeShiftDialog,
    ASSInfoDialog,
    ASSStylesDialog,
    BulkApplyStyleDialog,
    BatchStylePropsDialog,
    TrackSelectionDialog,
)
from .video_player import VideoPlayerWidget  # noqa: E402
from .home_screen import HomeScreenView  # noqa: E402
from .batch_file_list import BatchFileList  # noqa: E402
from .batch_operations_panel import BatchOperationsPanel  # noqa: E402
from .batch_confirm_dialog import BatchConfirmDialog  # noqa: E402
from .style_props_editor import GsubStylePropsEditor  # noqa: E402

__all__ = [
    'SubtitleListView', 'EditorPanel', 'TimeShiftDialog', 'ASSInfoDialog',
    'ASSStylesDialog', 'BulkApplyStyleDialog', 'BatchStylePropsDialog',
    'TrackSelectionDialog', 'VideoPlayerWidget', 'HomeScreenView',
    'BatchFileList', 'BatchOperationsPanel', 'BatchConfirmDialog',
    'GsubStylePropsEditor',
]
