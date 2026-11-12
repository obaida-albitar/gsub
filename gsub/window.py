"""
Main application window for the subtitle editor.

Following GNOME HIG, uses libadwaita widgets for a modern, native look.
"""

import gi
from gsub import __version__
from gsub.logger import get_logger

logger = get_logger(__name__)
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
gi.require_version('PangoCairo', '1.0')

from gi.repository import Gtk, Adw, Gio, GLib, Gdk, PangoCairo
import copy
import json
import os
import re

from gsub.batch_logic import (
    common_resolution,
    compute_shared_styles,
)
from gsub.extractors import EXTENSION_FOR_FORMAT
from gsub.models import SubtitleDocument, SubtitleFormat, TimeCode
from gsub.parsers import SRTParser, ASSParser, parse_subtitle_document
from gsub.parsers.encoding import decode_subtitle_text
from gsub.commands import (
    CommandManager,
    CompositeCommand,
    AddEntryCommand,
    RemoveEntryCommand,
    DuplicateEntryCommand,
    MoveEntryCommand,
)
from gsub.commands.ass_commands import ReplaceASSHeaderCommand
from gsub.commands.batch_commands import BatchOperationsCommand
from gsub.commands.subtitle_commands import EditTextCommand, build_new_entry
from gsub.resources import template_resource_path
from gsub.shortcuts import accels_for_action, window_key_entries
from gsub.utils import is_video_content_type
from gsub.widgets.subtitle_list import SubtitleListView
from gsub.widgets.timeline import active_entry_at
from gsub.widgets.editor_panel import EditorPanel
from gsub.widgets.dialogs import TimeShiftDialog, BulkApplyStyleDialog, BatchStylePropsDialog, ASSInfoDialog, ASSStylesDialog, TrackSelectionDialog, build_shortcuts_dialog
from gsub.widgets.video_player import VideoPlayerWidget
from gsub.widgets.home_screen import HomeScreenView
from gsub.widgets.batch_file_list import BatchFileList
from gsub.widgets.batch_operations_panel import BatchOperationsPanel
from gsub.widgets.batch_confirm_dialog import BatchConfirmDialog
from gsub.widgets.batch_rename_dialog import BatchRenameDialog
from gsub.parsers.ass_validator import (
    validate_document,
    COLOR_FIELD_ATTR,
    CompatIssue,
    clamp_blur,
    strip_fsp,
    fix_color,
)
from gsub.font_coverage import collect_glyph_coverage_issues
from gsub.widgets.compatibility_panel import CompatibilityPanel
from gsub.recovery import atomic_write_text
from gsub.save_workflow import SaveWorkflowMixin
from gsub.timing_actions import TimingActionsMixin


def should_show_track_dialog(n_audio: int, n_subs: int) -> bool:
    """Return True when a video's track layout warrants the selection dialog.

    The dialog is useful to pick among multiple audio tracks or to choose an
    embedded subtitle track (to view or extract for editing). A single audio
    track with no embedded subtitles needs no user decision, so no dialog is
    shown for that (common) case.
    """
    return n_subs >= 1 or n_audio > 1


def _window_key_table(shortcuts_entries):
    """Build the (keyval, mods) -> action lookup for window-handled keys.

    Each entry accel is parsed with GTK's accelerator parser so the table
    speaks the same keyval/modifier language as the key events the window
    controller reports. Returns {} when there are no window keys.
    """
    table = {}
    for shortcut in shortcuts_entries:
        for accel in shortcut.accels:
            valid, keyval, mods = Gtk.accelerator_parse(accel)
            if valid:
                table[(int(keyval), int(mods))] = shortcut.action
    return table


def _window_key_lookup(table, keyval, state):
    """Return the action name a key event dispatches to, or None.

    *state* is the raw modifier state of the key press. Only
    accelerator-relevant bits take part in the comparison — GTK's default
    accelerator mod mask (which includes Shift) — so modifier combos like
    Ctrl+Space or Shift+Space never trigger a plain "space" entry, and
    numlock/button masks are ignored.
    """
    mask = int(Gtk.accelerator_get_default_mod_mask()
               | Gdk.ModifierType.SHIFT_MASK)
    return table.get((int(keyval), int(state) & mask))


# Playback -> list highlight sync: minimum interval between active-entry
# lookups (microseconds).
_HIGHLIGHT_INTERVAL_US = 300_000


@Gtk.Template(resource_path=template_resource_path('window'))
class GsubWindow(SaveWorkflowMixin, TimingActionsMixin, Adw.ApplicationWindow):
    """Main application window."""

    __gtype_name__ = 'GsubWindow'

    # Template children (the static scaffold; child widgets are packed in code).
    toolbar_view = Gtk.Template.Child()
    banner = Gtk.Template.Child()
    header_bar = Gtk.Template.Child()
    menu_button = Gtk.Template.Child()
    title_stack = Gtk.Template.Child()
    title_widget = Gtk.Template.Child()
    view_switcher = Gtk.Template.Child()
    header_start_stack = Gtk.Template.Child()
    toast_overlay = Gtk.Template.Child()
    content_stack = Gtk.Template.Child()
    bottom_bar = Gtk.Template.Child()
    file_label = Gtk.Template.Child()
    status_bar = Gtk.Template.Child()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        # Application state
        self.document: SubtitleDocument = None
        self.command_manager = CommandManager()
        self.batch_command_manager = CommandManager()
        self._batch_saved_content = {}
        self._quality_dialog = None
        self._replace_dialog = None
        self.current_file = None
        self.current_video_file = None
        self.video_visible = False
        self.current_view = "home"  # "home", "editor", or "batch"
        self.batch_format = None  # SubtitleFormat of batch files (all same format)
        self.compat_issues = []

        # Load saved config
        config = self._load_config()
        self.last_directory = config.get("last_directory")
        self._list_pane_position = config.get("list_pane_position", 440)

        # Playback <-> subtitle list sync state (position highlight).
        self._last_highlight_time = 0
        self._active_highlight = -1

        # Set up window properties
        width = config.get("window_width", 1200)
        height = config.get("window_height", 800)
        self.set_default_size(width, height)
        if config.get("window_maximized", False):
            self.maximize()
        self.set_title("Gsub")
        self.connect("close-request", self._on_close_request)

        # Wire the dynamic child widgets into the templated scaffold.
        self._build_ui()
        self._update_header_bar()
        self._setup_actions()
        self._setup_window_key_controller()
        self._update_title()
        self._update_format_actions()
        self._update_document_actions()
        self._update_undo_redo_buttons()
        self._init_save_workflow()

    @staticmethod
    def _build_history_group(undo_tooltip, redo_tooltip):
        """Use the same compact linked controls in both editing modes."""
        group = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        group.add_css_class("linked")
        group.set_margin_start(6)
        buttons = []
        for icon, tooltip, action in (
            ("edit-undo-symbolic", undo_tooltip, "win.undo"),
            ("edit-redo-symbolic", redo_tooltip, "win.redo"),
        ):
            button = Gtk.Button(icon_name=icon)
            button.set_tooltip_text(tooltip)
            button.set_action_name(action)
            button.set_sensitive(False)
            group.append(button)
            buttons.append(button)
        return group, *buttons

    def _build_header_start_stack(self):
        """Build the three per-view header layouts and add them to the
        header_start_stack via add_named() (Gtk.Stack page names only resolve
        when set this way, not from the template)."""
        # Home page: empty (no start buttons)
        home_header = Gtk.Box()
        self.header_start_stack.add_named(home_header, "home")

        # Editor page: Open/Save + Undo/Redo + Video toggle
        editor_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)

        file_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        file_box.add_css_class("linked")

        open_button = Gtk.Button()
        open_button.set_icon_name("document-open-symbolic")
        open_button.set_tooltip_text("Open File (Ctrl+O)")
        open_button.set_action_name("win.open")
        file_box.append(open_button)

        self.save_button = Gtk.Button()
        self.save_button.set_icon_name("media-floppy-symbolic")
        self.save_button.set_tooltip_text("Save (Ctrl+S)")
        self.save_button.set_action_name("win.save")
        file_box.append(self.save_button)

        editor_header.append(file_box)

        undo_redo_box, self.undo_button, self.redo_button = self._build_history_group(
            "Undo (Ctrl+Z)", "Redo (Ctrl+Shift+Z)")
        editor_header.append(undo_redo_box)

        self.video_button = Gtk.ToggleButton()
        self.video_button.set_icon_name("video-display-symbolic")
        self.video_button.set_tooltip_text("Toggle Video Player (Ctrl+Shift+V)")
        self.video_button.connect('toggled', self._on_video_toggle)
        self.video_button.set_margin_start(6)
        editor_header.append(self.video_button)

        self.compat_btn = Gtk.Button()
        self.compat_btn.add_css_class("compat-button")
        self.compat_btn.set_margin_start(6)
        self.compat_btn.connect('clicked', self._on_compat_toggle)

        # Mirror libadwaita's AdwIndicatorBin layout: a 24x24 box keeps the
        # icon centred while the badge sits at its top-end, overlapping the
        # icon's top-right corner. The box reserves the badge's space, which
        # avoids the clipping that negative margins cause (GTK shrinks the
        # label below its font height).
        compat_overlay = Gtk.Overlay()
        compat_box = Gtk.CenterBox()
        compat_box.set_size_request(24, 24)
        self.compat_icon = Gtk.Image.new_from_icon_name("dialog-warning-symbolic")
        compat_box.set_center_widget(self.compat_icon)
        compat_overlay.set_child(compat_box)

        self.compat_badge = Gtk.Label()
        self.compat_badge.add_css_class("compat-badge")
        self.compat_badge.set_halign(Gtk.Align.END)
        self.compat_badge.set_valign(Gtk.Align.START)
        self.compat_badge.set_visible(False)
        compat_overlay.add_overlay(self.compat_badge)

        self.compat_btn.set_child(compat_overlay)
        editor_header.append(self.compat_btn)
        self._update_compat_button()

        quality_button = Gtk.Button(icon_name="document-properties-symbolic")
        quality_button.set_tooltip_text("Subtitle Quality Check (Ctrl+Shift+Q)")
        quality_button.set_action_name("win.quality-check")
        quality_button.set_margin_start(6)
        editor_header.append(quality_button)

        self.header_start_stack.add_named(editor_header, "editor")

        # Batch page: the same icon-only file/history groups as the editor.
        batch_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        batch_file_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        batch_file_box.add_css_class("linked")
        self.batch_add_button = Gtk.Button(icon_name="list-add-symbolic")
        self.batch_add_button.set_tooltip_text("Add subtitle files to the batch")
        self.batch_add_button.update_property(
            [Gtk.AccessibleProperty.LABEL], ["Add Files"])
        self.batch_add_button.connect('clicked', lambda b: self._on_batch_add_files())
        batch_file_box.append(self.batch_add_button)
        batch_header.append(batch_file_box)
        batch_history, self.batch_undo_button, self.batch_redo_button = self._build_history_group(
            "Undo Batch Operations (Ctrl+Z)", "Redo Batch Operations (Ctrl+Shift+Z)")
        batch_header.append(batch_history)
        self.header_start_stack.add_named(batch_header, "batch")

    def _build_ui(self):
        """Instantiate the dynamic child widgets and pack them into the
        templated scaffold. The static layout (toolbar view, header bar,
        view stack, bottom bar) is defined in window.blp; the per-view
        header layouts are built here via add_named() so their stack page
        names resolve correctly."""

        # Header start buttons - use a stack to switch between views.
        self._build_header_start_stack()

        # --- Content pages: Home, switcher views, Compatibility ---
        self.view_stack = Adw.ViewStack()
        self.content_stack.add_named(self.view_stack, "main")

        # --- Home page ---
        self.home_screen = HomeScreenView()
        self.home_screen.connect('open-file', lambda w: self._navigate_to_editor())
        self.home_screen.connect('open-batch', lambda w: self._navigate_to_batch())
        self.content_stack.add_named(self.home_screen, "home")

        # --- Editor page (single-file editing) ---
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        # Editing area - horizontal split (list + editor with video)
        self.paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self.paned.set_vexpand(True)
        self.paned.set_position(self._list_pane_position)
        self.paned.set_shrink_start_child(False)
        self.paned.set_shrink_end_child(False)
        self.paned.set_resize_start_child(False)
        self.paned.set_resize_end_child(True)
        main_box.append(self.paned)
        self._attach_file_drop_target(main_box, self._on_editor_files_drop)

        # Left side: Subtitle list with card container. Until a document is
        # opened or created, an empty state offers the New/Open entry points
        # instead of a blank, dead list.
        list_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        list_container.add_css_class("background")

        # Header above the list: title/count plus the entry actions. Keeping
        # them inside the list pane ties the buttons to the rows they act on;
        # the window footer is left for document-level status.
        self.list_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.list_header.set_margin_start(12)
        self.list_header.set_margin_end(6)
        self.list_header.set_margin_top(6)
        self.list_header.set_margin_bottom(6)
        self.list_header.set_visible(False)

        list_title = Gtk.Label(label="Subtitles")
        list_title.add_css_class("heading")
        self.list_header.append(list_title)

        self.list_count_label = Gtk.Label()
        self.list_count_label.add_css_class("dim-label")
        self.list_header.append(self.list_count_label)

        list_spacer = Gtk.Box()
        list_spacer.set_hexpand(True)
        self.list_header.append(list_spacer)

        list_actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        list_actions.add_css_class("linked")

        add_button = Gtk.Button()
        add_button.set_icon_name("list-add-symbolic")
        add_button.set_tooltip_text("Add Subtitle (Ctrl+Shift+N)")
        add_button.set_action_name("win.add-entry")
        list_actions.append(add_button)

        duplicate_button = Gtk.Button()
        duplicate_button.set_icon_name("edit-copy-symbolic")
        duplicate_button.set_tooltip_text("Duplicate Subtitle (Ctrl+D)")
        duplicate_button.set_action_name("win.duplicate-entry")
        list_actions.append(duplicate_button)

        remove_button = Gtk.Button()
        remove_button.set_icon_name("list-remove-symbolic")
        remove_button.set_tooltip_text("Remove Subtitle (Delete)")
        remove_button.set_action_name("win.remove-entry")
        list_actions.append(remove_button)

        self.list_header.append(list_actions)
        list_container.append(self.list_header)

        self.list_stack = Gtk.Stack()
        self.subtitle_list = SubtitleListView()
        self.subtitle_list.connect('entry-selected', self._on_entry_selected)
        self.subtitle_list.connect('entry-activated', self._on_entry_activated)
        self.subtitle_list.connect('selection-changed', self._on_subtitle_selection_changed)
        self.list_stack.add_named(self.subtitle_list, "list")
        self.list_stack.add_named(self._build_list_empty_page(), "empty")
        self.list_stack.set_visible_child_name("empty")
        list_container.append(self.list_stack)
        # Proofreading shares the list pane so the text editor and video stay
        # available while reviewing, without squeezing a third column in.
        self.review_stack = Gtk.Stack(hhomogeneous=False, vhomogeneous=False)
        self.review_stack.set_vexpand(True)
        self.review_stack.add_named(list_container, "subtitles")
        self.quality_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.review_stack.add_named(self.quality_container, "quality")
        self.review_stack.set_visible_child_name("subtitles")
        self.paned.set_start_child(self.review_stack)

        # Right side: Video player at top, editor panel below - use vertical paned for resizing
        self.right_paned = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL)
        self.right_paned.set_vexpand(True)
        self.right_paned.set_shrink_start_child(True)  # Allow collapsing
        self.right_paned.set_shrink_end_child(False)
        self.right_paned.set_resize_start_child(True)
        self.right_paned.set_resize_end_child(True)
        self.right_paned.set_position(0)  # Start collapsed

        # Video player at the top (initially hidden) in a container
        video_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        video_container.add_css_class("background")
        video_container.set_visible(False)  # Hide container by default
        self.video_container = video_container  # Store reference
        self.video_player = VideoPlayerWidget()
        # Show the unified track-selection dialog once mpv has parsed the
        # loaded video's track list (replaces the old timeout-based checks).
        self.video_player.connect('tracks-ready', self._on_tracks_ready)
        # Highlight the subtitle under the playhead while playing.
        self.video_player.connect('position-changed', self._on_player_position_changed)
        # Timeline region interactions: Ctrl+drag adjusts timing (undoable),
        # Ctrl+click selects the entry.
        self.video_player.connect('region-adjusted', self._on_region_adjusted)
        self.video_player.connect('region-selected', self._on_region_selected)
        video_container.append(self.video_player)
        self.right_paned.set_start_child(video_container)

        # Editor panel below video player in a scrolled window
        editor_scroll = Gtk.ScrolledWindow()
        editor_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        editor_scroll.set_vexpand(True)
        editor_scroll.add_css_class("background")

        self.editor_panel = EditorPanel()
        self.editor_panel.connect('text-changed', self._on_text_changed)
        self.editor_panel.connect('timing-changed', self._on_timing_changed)
        self.editor_panel.connect('style-changed', self._on_style_changed)
        self.editor_panel.connect('position-changed', self._on_position_changed)
        editor_scroll.set_child(self.editor_panel)
        self.right_paned.set_end_child(editor_scroll)

        self.paned.set_end_child(self.right_paned)

        # --- Compatibility page ---
        self.compat_panel = CompatibilityPanel()
        self.compat_panel.on_fix = self._apply_compat_fix
        self.content_stack.add_named(self.compat_panel, "compatibility")

        # --- Batch page ---
        batch_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        self.batch_paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self.batch_paned.set_vexpand(True)
        self.batch_paned.set_position(480)  # roomy default for long file names
        batch_box.append(self.batch_paned)
        self._attach_file_drop_target(batch_box, self._on_batch_files_drop)

        # Left side: batch file list
        batch_list_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        batch_list_container.add_css_class("background")
        self.batch_file_list = BatchFileList()
        self.batch_file_list.connect('selection-changed', self._on_batch_selection_changed)
        self.batch_file_list.connect('files-changed', self._on_batch_files_changed)
        batch_list_container.append(self.batch_file_list)
        self.batch_paned.set_start_child(batch_list_container)

        # Right side: batch operations
        batch_ops_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        batch_ops_container.add_css_class("background")
        self.batch_operations = BatchOperationsPanel()
        self.batch_operations.connect('operations-changed', self._on_batch_ops_changed)
        batch_ops_container.append(self.batch_operations)

        # Batch action buttons live inside the operations panel, under the
        # Resolution section (see batch-operations-panel.blp action_box).
        batch_button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        batch_button_box.set_hexpand(True)
        batch_button_box.set_homogeneous(True)

        batch_apply_btn = Gtk.Button(label="Apply Operations")
        batch_apply_btn.add_css_class("suggested-action")
        batch_apply_btn.connect('clicked', lambda b: self._on_batch_apply())
        self.batch_apply_btn = batch_apply_btn
        self.batch_apply_btn.set_sensitive(False)
        batch_button_box.append(batch_apply_btn)

        batch_save_btn = Gtk.Button(label="Save All")
        batch_save_btn.connect('clicked', lambda b: self._on_batch_save_all())
        self.batch_save_btn = batch_save_btn
        self.batch_save_btn.set_sensitive(False)
        batch_button_box.append(batch_save_btn)

        batch_save_as_btn = Gtk.Button(label="Save All As…")
        batch_save_as_btn.connect('clicked', lambda b: self._on_batch_save_all_as())
        self.batch_save_as_btn = batch_save_as_btn
        self.batch_save_as_btn.set_sensitive(False)
        batch_button_box.append(batch_save_as_btn)

        self.batch_operations.action_box.append(batch_button_box)
        self.batch_paned.set_end_child(batch_ops_container)

        # Start disabled: no files are loaded yet.
        self._update_batch_action_buttons()

        # --- Switcher views (Editor + Batch Operations) ---
        editor_page = self.view_stack.add_titled(main_box, "editor", "Editor")
        editor_page.set_icon_name("document-edit-symbolic")
        batch_page = self.view_stack.add_titled(
            batch_box, "batch", "Batch Operations")
        batch_page.set_icon_name("gsub-documents-symbolic")
        self.view_stack.set_visible_child_name("editor")
        self.view_switcher.set_stack(self.view_stack)
        self.view_stack.connect("notify::visible-child", self._on_view_switched)

        # Set default view to home
        self.content_stack.set_visible_child_name("home")

        self._update_bottom_bar()

    def _build_list_empty_page(self):
        """Build the placeholder shown in the editor view before any document
        is opened, with New/Open buttons as entry points."""
        page = Adw.StatusPage()
        page.set_icon_name("document-edit-symbolic")
        page.set_title("No File Open")
        page.set_description("Create a new subtitle file or open an existing one.")

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.set_halign(Gtk.Align.CENTER)

        new_button = Gtk.Button(label="New")
        new_button.set_action_name("win.new")
        box.append(new_button)

        open_button = Gtk.Button(label="Open")
        open_button.add_css_class("suggested-action")
        open_button.set_action_name("win.open")
        box.append(open_button)

        page.set_child(box)
        return page

    def _create_home_menu(self):
        """Create the primary menu for the home view."""
        menu = Gio.Menu()
        app_section = Gio.Menu()
        app_section.append("Keyboard Shortcuts", "win.show-help-overlay")
        app_section.append("About Gsub", "win.about")
        menu.append_section(None, app_section)
        return menu

    def _create_batch_menu(self):
        """Create the primary menu for the batch view."""
        menu = Gio.Menu()
        history = Gio.Menu()
        history.append("Undo Batch Operations", "win.undo")
        history.append("Redo Batch Operations", "win.redo")
        menu.append_section(None, history)
        app_section = Gio.Menu()
        app_section.append("Keyboard Shortcuts", "win.show-help-overlay")
        app_section.append("About Gsub", "win.about")
        menu.append_section(None, app_section)
        return menu

    def _create_editor_menu(self):
        """Create the primary menu for the editor view."""
        menu = Gio.Menu()

        # Undo/redo section (accel labels come from the registered accels)
        undo_redo_section = Gio.Menu()
        undo_redo_section.append("Undo", "win.undo")
        undo_redo_section.append("Redo", "win.redo")
        menu.append_section(None, undo_redo_section)

        # File section
        file_section = Gio.Menu()
        file_section.append("New", "win.new")
        file_section.append("Open…", "win.open")
        file_section.append("Save As…", "win.save-as")
        
        # Conversion submenu
        convert_menu = Gio.Menu()
        convert_menu.append("Convert to SRT", "win.convert-to-srt")
        convert_menu.append("Convert to ASS", "win.convert-to-ass")
        file_section.append_submenu("Convert Format", convert_menu)
        
        menu.append_section(None, file_section)

        # Batch section
        batch_section = Gio.Menu()
        batch_section.append("Batch Operations…", "win.batch")
        menu.append_section(None, batch_section)
        
        # Video section
        video_section = Gio.Menu()
        video_section.append("Open Video…", "win.open-video")
        video_section.append("Go to Timestamp…", "win.go-to-time")
        video_section.append("Toggle Video Player", "win.toggle-video")
        video_section.append("Select Audio/Subtitle Tracks…", "win.select-tracks")
        video_section.append("Set Subtitle Start Here", "win.set-start-here")
        video_section.append("Set Subtitle End Here", "win.set-end-here")
        video_section.append("Play Selected Cue", "win.play-cue")
        video_section.append("Loop Selected Cue / Stop Loop", "win.loop-cue")
        menu.append_section(None, video_section)
        
        # Edit section
        edit_section = Gio.Menu()
        edit_section.append("Find…", "win.find")
        edit_section.append("Find and Replace…", "win.replace")
        edit_section.append("Split Subtitle at Cursor", "win.split-entry")
        edit_section.append("Merge Selected Subtitles", "win.merge-entries")
        edit_section.append("Rebalance Text", "win.rebalance-text")
        edit_section.append("Subtitle Quality Check…", "win.quality-check")
        edit_section.append("Time Shift…", "win.time-shift")
        edit_section.append("ASS/SSA Info…", "win.ass-info")
        edit_section.append("ASS/SSA Styles…", "win.ass-styles")
        edit_section.append("Batch Edit Styles…", "win.batch-style-props")
        edit_section.append("Sort by Time", "win.sort-by-time")
        menu.append_section(None, edit_section)
        
        # App section
        app_section = Gio.Menu()
        app_section.append("Keyboard Shortcuts", "win.show-help-overlay")
        app_section.append("About Gsub", "win.about")
        menu.append_section(None, app_section)
        
        return menu
    
    def _setup_actions(self):
        """Set up window actions. Accels come from gsub.shortcuts."""
        # File actions
        self._create_action("new", self._on_new)
        self._create_action("open", self._on_open)
        self._create_action("save", self._on_save)
        self._create_action("save-as", self._on_save_as)
        self._create_action("convert-to-srt", self._on_convert_to_srt)
        self._create_action("convert-to-ass", self._on_convert_to_ass)

        # Video actions
        self._create_action("open-video", self._on_open_video)
        self._create_action("go-to-time", self._on_go_to_time)
        self._create_action("play-pause", self._on_play_pause)
        self._create_action("toggle-video", self._on_toggle_video)
        self._create_action("select-tracks", self._on_select_tracks)
        self._create_action("set-start-here", self._on_set_start_here)
        self._create_action("set-end-here", self._on_set_end_here)
        self._create_action("play-cue", self._on_play_cue)
        self._create_action("loop-cue", self._on_loop_cue)

        # Precise video navigation (see the shortcuts table for accels).
        self._create_action("seek-nudge-back", self._on_seek_nudge_back)
        self._create_action("seek-nudge-forward", self._on_seek_nudge_forward)
        self._create_action("seek-nudge-back-large", self._on_seek_nudge_back_large)
        self._create_action("seek-nudge-forward-large", self._on_seek_nudge_forward_large)
        self._create_action("frame-step", self._on_frame_step)
        self._create_action("frame-back-step", self._on_frame_back_step)
        self._create_action("seek-to-selection", self._on_seek_to_selection)

        # Navigation actions
        self._create_action("batch", self._on_batch)
        self._create_action("find", self._on_find)
        self._create_action("replace", self._on_replace)
        self._create_action("quality-check", self._on_quality_check)

        # Edit actions
        self._create_action("undo", self._on_undo)
        self._create_action("redo", self._on_redo)
        self._create_action("add-entry", self._on_add_entry)
        self._create_action("remove-entry", self._on_remove_entry)
        self._create_action("duplicate-entry", self._on_duplicate_entry)
        self._create_action("split-entry", self._on_split_entry)
        self._create_action("merge-entries", self._on_merge_entries)
        self._create_action("rebalance-text", self._on_rebalance_text)
        self._create_action("move-up", self._on_move_up)
        self._create_action("move-down", self._on_move_down)
        self._create_action("insert-above", self._on_insert_above)
        self._create_action("insert-below", self._on_insert_below)
        self._create_action("time-shift", self._on_time_shift)
        self._create_action("ass-info", self._on_ass_info_styles)
        self._create_action("ass-styles", self._on_ass_styles)
        self._create_action("bulk-apply-style", self._on_bulk_apply_style)
        self._create_action("batch-style-props", self._on_batch_style_props)
        self._create_action("sort-by-time", self._on_sort_by_time)

        # Help actions
        self._create_action("about", self._on_about)
        self._create_action("show-help-overlay", self._on_show_shortcuts)

    def _create_action(self, name: str, callback, shortcuts=None):
        """Create and register an action."""
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", callback)
        self.add_action(action)

        # Keep references so we can enable/disable format-specific actions.
        if not hasattr(self, '_actions'):
            self._actions = {}
        self._actions[name] = action

        # Look up accels in the shortcuts table unless overridden explicitly;
        # actions absent from the table get no accel.
        if shortcuts is None:
            shortcuts = accels_for_action(f"win.{name}")
        if shortcuts:
            self.get_application().set_accels_for_action(f"win.{name}", shortcuts)

    def _setup_window_key_controller(self):
        """Dispatch window-handled keys (space, period, comma, Delete).

        Registering these as application accels would let the accel win
        over text input and widget keybindings, so a plain "space" accel
        swallowed Space in the subtitle text editor and entries, and a
        "Delete" accel deleted the whole subtitle entry instead of a
        character. A bubble-phase key controller on
        the window only runs after the focused widget had its chance, so
        text widgets consume these keys for typing while the rest of the
        window (subtitle list, timeline, ...) still gets the shortcut.
        Focusable buttons keep consuming Space to activate themselves, as
        is standard. The keys and their dialog display accels live in the
        shortcuts table (window_key entries).
        """
        self._window_keys = _window_key_table(window_key_entries())
        key_controller = Gtk.EventControllerKey()
        key_controller.set_propagation_phase(Gtk.PropagationPhase.BUBBLE)
        key_controller.connect("key-pressed", self._on_window_key_pressed)
        self.add_controller(key_controller)

    def _on_window_key_pressed(self, controller, keyval, keycode, state):
        """Activate the action matching a window-handled key, if any.

        Returns True (stopping propagation) only when a window key matched
        and its action is enabled; otherwise the event continues to other
        handlers.
        """
        action_name = _window_key_lookup(self._window_keys, keyval, state)
        if action_name is None:
            return False
        action = self.lookup_action(action_name.split(".", 1)[1])
        if action is None or not action.get_enabled():
            return False
        action.activate(None)
        return True

    def _update_title(self):
        """Update window title based on current file."""
        if self.current_file:
            filename = os.path.basename(self.current_file)
            self.title_widget.set_title(filename)
            if self.document and self.document.modified:
                self.title_widget.set_subtitle("Modified")
            else:
                self.title_widget.set_subtitle("")
        else:
            self.title_widget.set_title("Gsub")
            self.title_widget.set_subtitle("")

        self._update_file_label()
    
    def _update_status(self):
        """Update status bar."""
        if self.document:
            count = len(self.document.entries)
            format_name = self.document.format.value.upper()
            self.status_bar.set_text(f"{count} subtitles • {format_name} format")
        else:
            self.status_bar.set_text("No file loaded")
        self._update_list_header()

    def _update_list_header(self):
        """Show the list header and entry count only while a document is open."""
        has_doc = self.document is not None
        self.list_header.set_visible(has_doc)
        if has_doc:
            self.list_count_label.set_text(f"({len(self.document.entries)})")

    def _update_file_label(self):
        """Show the document name (and modified state) in the bottom bar."""
        if self.current_view != "editor" or self.document is None:
            self.file_label.set_visible(False)
            return
        if self.current_file:
            name = os.path.basename(self.current_file)
            self.file_label.set_tooltip_text(self.current_file)
        else:
            name = "Untitled"
            self.file_label.set_tooltip_text("")
        if self.document.modified:
            name += " • Modified"
        self.file_label.set_text(name)
        self.file_label.set_visible(True)
    
    def _update_undo_redo_buttons(self):
        """Update undo/redo button sensitivity."""
        self.undo_button.set_sensitive(self.command_manager.can_undo())
        self.redo_button.set_sensitive(self.command_manager.can_redo())
        self.batch_undo_button.set_sensitive(self.batch_command_manager.can_undo())
        self.batch_redo_button.set_sensitive(self.batch_command_manager.can_redo())
        manager = (self.batch_command_manager if self.current_view == "batch"
                   else self.command_manager)
        can_undo, can_redo = manager.can_undo(), manager.can_redo()
        # The buttons are action-mapped, so their sensitivity follows the
        # action enabled state (which also greys out the menu items and
        # blocks the accels); keep the actions in sync too.
        for name, enabled in (("undo", can_undo), ("redo", can_redo)):
            action = getattr(self, "_actions", {}).get(name)
            if action is not None:
                action.set_enabled(enabled)

    def _document_mutated(self):
        """Refresh everything that depends on document content after a
        mutation (command executed, undone or redone): undo/redo buttons and
        the compatibility issues, so the panel never shows stale results."""
        self._update_undo_redo_buttons()
        self._refresh_compat()
        if self._quality_dialog is not None:
            self._quality_dialog.refresh()
        if self._replace_dialog is not None:
            self._replace_dialog.refresh(navigate=False)
        self._queue_recovery()

    def _update_format_actions(self):
        """Enable/disable ASS-only actions based on current document format."""
        fmt = self.document.format if self.document else None
        is_ass = fmt in (SubtitleFormat.ASS, SubtitleFormat.SSA)

        for name in ("ass-info", "ass-styles", "bulk-apply-style", "batch-style-props"):
            action = getattr(self, '_actions', {}).get(name)
            if action is not None:
                action.set_enabled(bool(is_ass))
    
    def _update_document_actions(self):
        """Enable/disable document-dependent actions.

        undo/redo are deliberately absent: their enabled state is owned by
        ``_update_undo_redo_buttons`` (empty history → disabled even with a
        document open). ``select-tracks`` is absent too: it needs a loaded
        video, not a document, and its handler (_on_select_tracks) already
        toasts when there is no video or no embedded tracks. The other
        video actions (open-video, toggle-video, play-pause) were never
        gated here either.
        """
        has_doc = self.document is not None
        for name in ("save", "save-as", "convert-to-srt", "convert-to-ass",
                     "time-shift", "sort-by-time",
                     "add-entry",
                     "move-up", "move-down", "insert-above", "insert-below",
                     "find", "replace", "quality-check"):
            action = self._actions.get(name)
            if action is not None:
                action.set_enabled(has_doc)
        # Selection-dependent actions are owned by the selection state; this
        # also disables them when the document goes away.
        self._update_selection_actions()

    def _update_selection_actions(self):
        """Enable entry actions that operate on a selected subtitle."""
        has_selection = (
            self.document is not None
            and bool(self.subtitle_list.get_selected_positions())
        )
        for name in ("remove-entry", "duplicate-entry"):
            action = self._actions.get(name)
            if action is not None:
                action.set_enabled(has_selection)
        positions = self.subtitle_list.get_selected_positions() if has_selection else []
        contiguous = (len(positions) >= 2
                      and max(positions) - min(positions) + 1 == len(positions))
        for name, enabled in (("split-entry", len(positions) == 1),
                              ("merge-entries", contiguous),
                              ("rebalance-text", has_selection)):
            action = self._actions.get(name)
            if action is not None:
                action.set_enabled(enabled)

        can_time_cue = bool(self.current_video_file) and len(positions) == 1
        for name in ("set-start-here", "set-end-here", "play-cue", "loop-cue"):
            action = self._actions.get(name)
            if action is not None:
                action.set_enabled(can_time_cue)
        action = self._actions.get("go-to-time")
        if action is not None:
            action.set_enabled(bool(self.current_video_file))

    # Window state lives in ~/.config/gsub/config.json. Releases before the
    # package rename stored it under ~/.config/subtitle-editor/; that legacy
    # directory remains as a read-only fallback so existing state migrates
    # silently the first time the config is saved.
    _LEGACY_CONFIG_DIR_NAME = "subtitle-editor"

    def _get_config_dir(self):
        """Get the config directory path."""
        config_dir = os.path.join(GLib.get_user_config_dir(), "gsub")
        os.makedirs(config_dir, exist_ok=True)
        return config_dir

    def _load_config(self) -> dict:
        """Load the full config from the config file.

        Falls back to the legacy config directory (pre-rename) when no config
        file exists in the current one; the next _save_config() then writes
        the merged state to the current directory.
        """
        config_dir = self._get_config_dir()
        config_file = os.path.join(config_dir, "config.json")
        if not os.path.exists(config_file):
            legacy_file = os.path.join(
                os.path.dirname(config_dir),
                self._LEGACY_CONFIG_DIR_NAME,
                "config.json",
            )
            if os.path.exists(legacy_file):
                config_file = legacy_file
        try:
            with open(config_file) as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save_config(self, config: dict):
        """Save the full config to the config file."""
        config_file = os.path.join(self._get_config_dir(), "config.json")
        try:
            with open(config_file, 'w') as f:
                json.dump(config, f)
        except Exception as e:
            logger.warning(f"Failed to save config: {e}")

    def _save_last_directory(self, directory: str):
        """Save the last opened directory to config file."""
        self.last_directory = directory
        config = self._load_config()
        config["last_directory"] = directory
        self._save_config(config)

    def _save_window_state(self):
        """Save window state before closing."""
        config = self._load_config()
        config["last_directory"] = self.last_directory
        config["window_maximized"] = self.is_maximized()
        if not self.is_maximized():
            config["window_width"] = self.get_width()
            config["window_height"] = self.get_height()
        if getattr(self, "paned", None) is not None:
            config["list_pane_position"] = self.paned.get_position()
        self._save_config(config)

    def _show_toast(self, message: str):
        """Show a toast notification."""
        # Escape any special characters for Pango markup (especially & which appears in filenames)
        import html
        safe_message = html.escape(message)
        toast = Adw.Toast.new(safe_message)
        toast.set_timeout(2)
        self.toast_overlay.add_toast(toast)
    
    def _show_banner(self, message: str, button_label: str = None, button_action: callable = None):
        """Show a banner notification for important messages."""
        self.banner.set_title(message)
        if button_label and button_action:
            self.banner.set_button_label(button_label)
            # Store the action to call when clicked
            if hasattr(self, '_banner_action_handler'):
                self.banner.disconnect(self._banner_action_handler)
            self._banner_action_handler = self.banner.connect('button-clicked', lambda b: button_action())
        else:
            self.banner.set_button_label("")
        self.banner.set_revealed(True)
    
    def _hide_banner(self):
        """Hide the banner notification."""
        self.banner.set_revealed(False)

    def _navigate_to_editor(self):
        """Switch to the editor view.

        No file dialog is opened automatically: the home screen's "Start"
        button just reveals the editor, whose header already offers New/Open
        (and the empty state provides buttons when no document is loaded).
        """
        self.current_view = "editor"
        self.view_stack.set_visible_child_name("editor")
        self.content_stack.set_visible_child_name("main")
        self._update_compat_button()
        self._update_header_bar()
        self._update_bottom_bar()
        self._update_title()
        self._update_status()

    def _navigate_to_batch(self):
        """Switch to the batch operations view."""
        self.current_view = "batch"
        self.view_stack.set_visible_child_name("batch")
        self.content_stack.set_visible_child_name("main")
        self.title_widget.set_title("Batch Operations")
        self.title_widget.set_subtitle("")
        self._update_header_bar()
        self._update_bottom_bar()

    def _on_view_switched(self, view_stack, _pspec):
        """Follow the view selected with the header switcher."""
        view = view_stack.get_visible_child_name()
        if view not in ("editor", "batch") or view == self.current_view:
            return
        if view == "editor":
            self._navigate_to_editor()
        else:
            self._navigate_to_batch()

    def _on_compat_toggle(self, _btn):
        """Toggle between the editor and the Compatibility page."""
        self.editor_panel.flush_pending_changes()
        if self.content_stack.get_visible_child_name() == "compatibility":
            self.content_stack.set_visible_child_name("main")
        else:
            self.content_stack.set_visible_child_name("compatibility")
            # Recompute on entering the page so it can never show stale
            # results, whatever path changed the document.
            self._refresh_compat()
        self._update_compat_button()
        self._update_title_area()

    def _update_compat_button(self):
        """Sync the header's compatibility button with the current state.

        Outside the Compatibility page it is an exclamation-mark icon with a
        numeric badge for the issue count; on the page it turns into a back
        button that returns to the editor.
        """
        if self.content_stack.get_visible_child_name() == "compatibility":
            self.compat_icon.set_from_icon_name("go-previous-symbolic")
            self.compat_badge.set_visible(False)
            self.compat_btn.set_tooltip_text("Back to Editor")
            self.compat_btn.set_sensitive(True)
            return

        n = len(getattr(self, "compat_issues", []))
        self.compat_icon.set_from_icon_name("dialog-warning-symbolic")
        self.compat_badge.set_label("9+" if n > 9 else str(n))
        self.compat_badge.set_visible(n > 0)
        self.compat_btn.set_sensitive(self.document is not None and n > 0)
        self.compat_btn.set_tooltip_text(
            f"Compatibility Checker ({n} issue{'s' if n != 1 else ''})")

    def _update_header_bar(self):
        """Update the header bar buttons and menu based on current view."""
        self.header_start_stack.set_visible_child_name(self.current_view)
        self._update_title_area()
        if self.current_view == "home":
            self.menu_button.set_menu_model(self._create_home_menu())
        elif self.current_view == "batch":
            self.menu_button.set_menu_model(self._create_batch_menu())
        else:
            self.menu_button.set_menu_model(self._create_editor_menu())
        self._update_undo_redo_buttons()

    def _update_title_area(self):
        """Show the view switcher while browsing views, the title otherwise."""
        show_switcher = (
            self.current_view in ("editor", "batch")
            and self.content_stack.get_visible_child_name() == "main"
        )
        self.title_stack.set_visible_child(
            self.view_switcher if show_switcher else self.title_widget
        )

    def _update_bottom_bar(self):
        """Update the bottom bar status based on current view."""
        if self.current_view == "editor":
            self._update_status()
        elif self.current_view == "batch":
            self._update_batch_status()
        else:
            # Home view - just status
            self.status_bar.set_text("")

        self._update_file_label()

    def open_file(self, gfile: Gio.File):
        """Open a subtitle after protecting the current document's edits."""
        return self._request_document_replacement(lambda: self._open_file_now(gfile))

    def _open_file_now(self, gfile: Gio.File):
        """Load a file after its unsaved-changes decision has completed."""
        self.editor_panel.flush_pending_changes()
        try:
            success, contents, _ = gfile.load_contents(None)
            if not success:
                self._show_error("Failed to load file")
                return False
            
            content = decode_subtitle_text(contents)
            file_path = gfile.get_path()
            
            # Detect format by extension
            ext = os.path.splitext(file_path)[1].lower()
            
            document, parse_warnings = parse_subtitle_document(content, ext)
            if document is None:
                self._show_error("Unsupported file format")
                return False

            self._close_document_dialogs()
            self.document = document
            
            self.document.file_path = file_path
            self.current_file = file_path
            self.command_manager.clear()
            self._update_undo_redo_buttons()
            
            # Update UI
            self.subtitle_list.set_document(self.document)
            self._reset_playback_highlight()
            self.list_stack.set_visible_child_name("list")
            # Provide ASS/SSA style context for per-entry style selection
            style_names = [s.name for s in (self.document.styles or [])] if self.document else []
            self.editor_panel.set_document_context(self.document.format, style_names)
            self.editor_panel.clear()
            self._update_title()
            self._update_status()
            self._update_format_actions()
            self._update_document_actions()
            
            # Update video player with subtitle document
            if self.video_player:
                self.video_player.set_document(self.document)
            
            self._save_last_directory(os.path.dirname(file_path))
            if parse_warnings:
                self._show_toast(
                    f"Fixed {len(parse_warnings)} issue(s) while parsing — review your file")
            self._show_toast(f"Opened {os.path.basename(file_path)}")
            self._navigate_to_editor()

            self._refresh_compat()
            if self.compat_issues:
                self._show_toast(
                    f"{len(self.compat_issues)} compatibility issue(s) found — see Compatibility view")
            self._snapshot_recovery()
            return True

        except Exception as e:
            self._show_error(f"Error opening file: {str(e)}")
            return False
    
    def _save_document(self, file_path: str, document=None):
        """Atomically save, updating the active document only after success."""
        self.editor_panel.flush_pending_changes()
        try:
            document = document if document is not None else self.document
            if document is None:
                return False
            
            # Serialize based on format
            if document.format == SubtitleFormat.SRT:
                content = SRTParser.serialize(document)
            else:  # ASS or SSA
                content = ASSParser.serialize(document)
            
            # Write to file
            atomic_write_text(file_path, content)

            if document is not self.document:
                self._close_document_dialogs()
                self.document = document
                self.command_manager.clear()
                self.editor_panel.clear()
                self.subtitle_list.set_document(document)
                self._reset_playback_highlight()
                self.editor_panel.set_document_context(document.format,
                                                       [s.name for s in document.styles])
                self._update_format_actions()
                self._update_status()
                if self.video_player:
                    self.video_player.set_document(document)
                self._document_mutated()
            
            self.document.modified = False
            self.document.file_path = file_path
            self.current_file = file_path
            self._hide_banner()
            self._update_title()
            self._save_last_directory(os.path.dirname(file_path))
            self._show_toast(f"Saved {os.path.basename(file_path)}")
            self._snapshot_recovery()
            return True
            
        except Exception as e:
            self._show_error(f"Error saving file: {str(e)}")
            return False
    
    def _show_error(self, message: str):
        """Show an error dialog."""
        dialog = Adw.MessageDialog.new(self, message, "")
        dialog.add_response("ok", "OK")
        dialog.set_default_response("ok")
        dialog.present()
    
    # Action callbacks
    
    def _on_new(self, action, param):
        """Create a new subtitle document."""
        self._request_document_replacement(self._create_new_document)
    
    def _on_new_response(self, dialog, response):
        """Handle response to new document save prompt."""
        self._resolve_unsaved_response(response, self._create_new_document)
    
    def _create_new_document(self):
        """Actually create a new document (called after save prompt check)."""
        self.editor_panel.flush_pending_changes()
        self._close_document_dialogs()
        self.document = SubtitleDocument(format=SubtitleFormat.SRT)
        self.current_file = None
        self.command_manager.clear()
        self._update_undo_redo_buttons()
        self.subtitle_list.set_document(self.document)
        self._reset_playback_highlight()
        self.list_stack.set_visible_child_name("list")
        style_names = [s.name for s in (self.document.styles or [])] if self.document else []
        self.editor_panel.set_document_context(self.document.format, style_names)
        self.editor_panel.clear()
        if self.video_player:
            self.video_player.set_document(self.document)
        self._update_title()
        self._update_status()
        self._update_format_actions()
        self._update_document_actions()
        self._hide_banner()
        self._navigate_to_editor()
        self._refresh_compat()
        self._snapshot_recovery()

    def _on_open(self, action, param):
        """Show file open dialog."""
        dialog = Gtk.FileDialog()
        dialog.set_title("Open Subtitle File")
        
        # Set up file filters
        filters = Gio.ListStore.new(Gtk.FileFilter)
        
        filter_all_subs = Gtk.FileFilter()
        filter_all_subs.set_name("All Subtitle Files")
        filter_all_subs.add_pattern("*.srt")
        filter_all_subs.add_pattern("*.ass")
        filter_all_subs.add_pattern("*.ssa")
        filters.append(filter_all_subs)
        
        filter_srt = Gtk.FileFilter()
        filter_srt.set_name("SRT Files")
        filter_srt.add_pattern("*.srt")
        filters.append(filter_srt)
        
        filter_ass = Gtk.FileFilter()
        filter_ass.set_name("ASS/SSA Files")
        filter_ass.add_pattern("*.ass")
        filter_ass.add_pattern("*.ssa")
        filters.append(filter_ass)
        
        dialog.set_filters(filters)
        dialog.set_default_filter(filter_all_subs)
        
        if self.last_directory:
            dialog.set_initial_folder(Gio.File.new_for_path(self.last_directory))
        dialog.open(self, None, self._on_open_response)
    
    def _on_open_response(self, dialog, result):
        """Handle file open dialog response."""
        try:
            file = dialog.open_finish(result)
            if file:
                self.open_file(file)
                self._hide_banner()
        except Exception:
            pass  # User cancelled
    
    def _on_save(self, action, param):
        """Save the current document."""
        if not self.document:
            return
        
        if self.current_file:
            self._save_document(self.current_file)
        else:
            self._on_save_as(action, param)
    
    def _on_save_as(self, action, param, on_complete=None):
        """Show save as dialog with format selection."""
        if not self.document or self._save_dialog_pending:
            if on_complete is not None:
                on_complete(False)
            return

        self.editor_panel.flush_pending_changes()
        source_document = self.document
        self._save_dialog_pending = True
        
        dialog = Gtk.FileDialog()
        dialog.set_title("Save Subtitle File")
        
        # Set up file filters for different formats
        filters = Gio.ListStore.new(Gtk.FileFilter)
        
        filter_srt = Gtk.FileFilter()
        filter_srt.set_name("SRT Files (*.srt)")
        filter_srt.add_pattern("*.srt")
        filters.append(filter_srt)
        
        filter_ass = Gtk.FileFilter()
        filter_ass.set_name("ASS Files (*.ass)")
        filter_ass.add_pattern("*.ass")
        filters.append(filter_ass)
        
        filter_ssa = Gtk.FileFilter()
        filter_ssa.set_name("SSA Files (*.ssa)")
        filter_ssa.add_pattern("*.ssa")
        filters.append(filter_ssa)
        
        dialog.set_filters(filters)
        
        # Set default filter based on current format
        if self.document.format == SubtitleFormat.SRT:
            dialog.set_default_filter(filter_srt)
        elif self.document.format == SubtitleFormat.SSA:
            dialog.set_default_filter(filter_ssa)
        else:
            dialog.set_default_filter(filter_ass)
        
        # Set initial name
        if self.current_file:
            dialog.set_initial_name(os.path.basename(self.current_file))
        else:
            ext = ".srt" if self.document.format == SubtitleFormat.SRT else ".ass"
            dialog.set_initial_name(f"untitled{ext}")
        
        if self.last_directory:
            dialog.set_initial_folder(Gio.File.new_for_path(self.last_directory))
        dialog.save(self, None, lambda chooser, result:
                    self._on_save_as_response(chooser, result, on_complete, source_document))
    
    def _on_save_as_response(self, dialog, result, on_complete=None, source_document=None):
        """Handle save as dialog response."""
        saved = False
        try:
            file = dialog.save_finish(result)
            if file:
                file_path = file.get_path()
                if not file_path:
                    self._show_error("Cannot save subtitles: no local file path")
                    return
                if source_document is not None and source_document is not self.document:
                    self._show_error("The document changed while the save dialog was open. Try Save As again.")
                    return
                
                # Check if format conversion is needed based on extension
                ext = os.path.splitext(file_path)[1].lower()
                target_format = None
                
                if ext == '.srt':
                    target_format = SubtitleFormat.SRT
                elif ext == '.ass':
                    target_format = SubtitleFormat.ASS
                elif ext == '.ssa':
                    target_format = SubtitleFormat.SSA
                
                # Convert format if needed
                document = self.document
                if target_format and target_format != document.format:
                    from gsub.converters import FormatConverter
                    self.editor_panel.flush_pending_changes()
                    document = FormatConverter.convert(document, target_format)
                saved = self._save_document(file_path, document)
        except GLib.Error as error:
            # Gtk.DialogError.DISMISSED is the ordinary Cancel path.
            if not error.matches(Gtk.DialogError.quark(), Gtk.DialogError.DISMISSED):
                self._show_error(f"Error saving file: {error.message}")
        except Exception as error:
            self._show_error(f"Error saving file: {error}")
        finally:
            self._save_dialog_pending = False
            if on_complete is not None:
                on_complete(saved)
    
    def _on_undo(self, action, param):
        """Undo the last action."""
        if self.current_view == "batch":
            desc = self.batch_command_manager.get_undo_description()
            if self.batch_command_manager.undo():
                self._refresh_batch_after_change()
                self._show_toast(f"Undo: {desc}")
            return
        self.editor_panel.flush_pending_changes()
        # Capture the description before undoing; afterwards it names the next one.
        desc = self.command_manager.get_undo_description()
        if self.command_manager.undo():
            self.subtitle_list.refresh(preserve_selection=True)
            self._update_editor_after_change()
            self._update_title()
            self._update_status()
            self._document_mutated()
            self._refresh_video_preview()
            self._show_toast(f"Undo: {desc}" if desc else "Undo")

    def _on_redo(self, action, param):
        """Redo the last undone action."""
        if self.current_view == "batch":
            desc = self.batch_command_manager.get_redo_description()
            if self.batch_command_manager.redo():
                self._refresh_batch_after_change()
                self._show_toast(f"Redo: {desc}")
            return
        self.editor_panel.flush_pending_changes()
        desc = self.command_manager.get_redo_description()
        if self.command_manager.redo():
            self.subtitle_list.refresh(preserve_selection=True)
            self._update_editor_after_change()
            self._update_title()
            self._update_status()
            self._document_mutated()
            self._refresh_video_preview()
            self._show_toast(f"Redo: {desc}" if desc else "Redo")
    
    def _update_editor_after_change(self):
        """Update the editor panel after undo/redo or other changes."""
        if len(self.subtitle_list.get_selected_positions()) > 1:
            self.editor_panel.clear()
            return
        selected_pos = self.subtitle_list.get_selected_position()
        if self.document and 0 <= selected_pos < len(self.document.entries):
            entry = self.document.entries[selected_pos]
            self.editor_panel.set_entry(entry, selected_pos)
        else:
            self.editor_panel.clear()
    
    def _on_add_entry(self, action, param):
        """Add a new subtitle entry below the selection (or at the end)."""
        if not self.document:
            self._on_new(action, param)
            return

        position = self.subtitle_list.get_selected_position()
        insert_at = position + 1 if position >= 0 else len(self.document.entries)
        self._insert_entry_at(insert_at, "Subtitle added")

    def _on_insert_above(self, action, param):
        """Insert a new subtitle entry directly above the selection."""
        if not self.document:
            return
        position = self.subtitle_list.get_selected_position()
        if position < 0:
            return
        self._insert_entry_at(position, "Subtitle inserted above")

    def _on_insert_below(self, action, param):
        """Insert a new subtitle entry directly below the selection."""
        if not self.document:
            return
        position = self.subtitle_list.get_selected_position()
        if position < 0:
            return
        self._insert_entry_at(position + 1, "Subtitle inserted below")

    def _insert_entry_at(self, position: int, toast: str):
        """Insert a new entry (timing derived from its neighbors) at
        ``position`` and update the list incrementally."""
        self.editor_panel.flush_pending_changes()
        entry = build_new_entry(self.document, position)
        cmd = AddEntryCommand(self.document, entry, position)
        self.command_manager.execute(cmd)

        self.subtitle_list.entries_inserted(position, 1)
        self.subtitle_list.select_entry(position)
        self._update_title()
        self._update_status()
        self._document_mutated()
        self._refresh_video_preview()
        self._show_toast(toast)

    def _on_find(self, action, param):
        """Reveal the subtitle search bar."""
        self._show_subtitle_list()
        self.subtitle_list.set_search_visible(True)

    def _show_subtitle_list(self):
        self.review_stack.set_visible_child_name("subtitles")

    def _close_document_dialogs(self):
        for attr in ("_quality_dialog", "_replace_dialog"):
            dialog = getattr(self, attr, None)
            if dialog is not None:
                dialog.close()
                if attr == "_quality_dialog" and dialog.get_parent() is self.quality_container:
                    self.quality_container.remove(dialog)
                setattr(self, attr, None)
        self._show_subtitle_list()

    def _select_issue_entry(self, position):
        """Navigate to a quality issue or find result without starting playback."""
        if self.document is None or not 0 <= position < len(self.document.entries):
            return
        self.subtitle_list.select_entry(position)
        if self.video_player and self.current_video_file:
            self.video_player.seek(
                self.document.entries[position].start_time.total_milliseconds / 1000.0)

    def _on_quality_check(self, action, param):
        if self.document is None:
            return
        from gsub.quality import QualitySettings
        from gsub.widgets.quality_panel import QualityPanel

        self.editor_panel.flush_pending_changes()
        if self._quality_dialog is None:
            settings = QualitySettings.from_dict(self._load_config().get("quality_settings", {}))

            def save_settings(updated):
                config = self._load_config()
                config["quality_settings"] = updated.to_dict()
                self._save_config(config)

            self._quality_dialog = QualityPanel(
                self, self.document, self._select_issue_entry,
                settings=settings, on_settings_changed=save_settings,
                on_apply=self._execute_edit_command,
                on_close=self._show_subtitle_list,
                on_before_action=self.editor_panel.flush_pending_changes)
            self.quality_container.append(self._quality_dialog)
        self.review_stack.set_visible_child_name("quality")
        self._quality_dialog.present()

    def _on_replace(self, action, param):
        if self.document is None:
            return
        from gsub.widgets.find_replace_dialog import FindReplaceDialog

        self.editor_panel.flush_pending_changes()
        if self._replace_dialog is None:
            self._replace_dialog = FindReplaceDialog(
                self, self.document, self.subtitle_list.get_selected_positions(),
                on_apply=self._execute_edit_command, on_select=self._select_issue_entry)
            self._replace_dialog.connect(
                "closed", lambda dialog: setattr(self, "_replace_dialog", None)
                if self._replace_dialog is dialog else None)
        self._replace_dialog.present()

    def _execute_edit_command(self, command, selected_position=None):
        """Refresh the editor after one undoable text operation."""
        if command is None or not getattr(command, "changed", True):
            return False
        self.command_manager.execute(command)
        self.subtitle_list.refresh(preserve_selection=True)
        if selected_position is not None:
            self.subtitle_list.select_entry(selected_position)
        self._update_editor_after_change()
        self._update_selection_actions()
        self._update_title()
        self._update_status()
        self._document_mutated()
        self._refresh_video_preview()
        self._show_toast(command.description())
        return True

    def _on_split_entry(self, action, param):
        from gsub.commands.text_commands import SplitEntryCommand

        positions = self.subtitle_list.get_selected_positions()
        if self.document is None or len(positions) != 1:
            return
        self.editor_panel.flush_pending_changes()
        position = positions[0]
        entry = self.document.entries[position]
        split_ms = None
        if self.video_player and self.current_video_file:
            playhead = round(self.video_player.get_position() * 1000)
            if entry.start_time.total_milliseconds < playhead < entry.end_time.total_milliseconds:
                split_ms = playhead
        try:
            command = SplitEntryCommand(
                self.document, position, self.editor_panel.get_split_offset(), split_ms)
            self._execute_edit_command(command, position + 1)
        except ValueError as exc:
            self._show_toast(str(exc))

    def _on_merge_entries(self, action, param):
        from gsub.commands.text_commands import MergeEntriesCommand

        if self.document is None:
            return
        self.editor_panel.flush_pending_changes()
        positions = self.subtitle_list.get_selected_positions()
        if len(positions) < 2:
            return
        try:
            self._execute_edit_command(
                MergeEntriesCommand(self.document, positions), min(positions))
        except ValueError as exc:
            self._show_toast(str(exc))

    def _on_rebalance_text(self, action, param):
        from gsub.commands.text_commands import RebalanceTextCommand
        from gsub.quality import QualitySettings

        if self.document is None:
            return
        self.editor_panel.flush_pending_changes()
        positions = self.subtitle_list.get_selected_positions()
        if not positions:
            return
        try:
            limit = QualitySettings.from_dict(
                self._load_config().get("quality_settings", {})).max_chars_per_line
            command = RebalanceTextCommand(self.document, positions, max_line_length=limit)
            if not self._execute_edit_command(command):
                self._show_toast("Selected text is already balanced")
        except ValueError as exc:
            self._show_toast(str(exc))

    def _on_remove_entry(self, action, param):
        """Remove the selected subtitle entries."""
        if not self.document:
            return
        self.editor_panel.flush_pending_changes()
        positions = self.subtitle_list.get_selected_positions()
        if not positions:
            return

        # Remove in reverse order to maintain indices; a composite keeps the
        # whole removal a single undo step.
        positions_sorted = sorted(set(positions), reverse=True)
        commands = [RemoveEntryCommand(self.document, p) for p in positions_sorted]
        if len(commands) == 1:
            self.command_manager.execute(commands[0])
        else:
            self.command_manager.execute(
                CompositeCommand(commands, "Remove subtitles"))

        self.subtitle_list.entries_removed(positions)

        # Keep the row that moved into the first removed slot selected (or
        # the previous one when the tail was removed) so the list highlight,
        # editor and selection-dependent actions stay in sync.
        remaining = len(self.document.entries)
        if remaining:
            self.subtitle_list.select_entry(min(min(positions), remaining - 1))
        else:
            self.subtitle_list.select_entry(-1)
            self.editor_panel.clear()
            self._update_selection_actions()

        self._update_title()
        self._update_status()
        self._document_mutated()
        self._refresh_video_preview()

        count = len(positions)
        self._show_toast(f"{count} subtitle{'s' if count > 1 else ''} removed")

    def _on_duplicate_entry(self, action, param):
        """Duplicate the selected subtitle entries."""
        if not self.document:
            return
        self.editor_panel.flush_pending_changes()
        positions = self.subtitle_list.get_selected_positions()
        if not positions:
            return

        # Duplicate in order, adjusting positions as we go; a composite keeps
        # the whole duplication a single undo step.
        positions_sorted = sorted(set(positions))
        commands = []
        offset = 0
        for position in positions_sorted:
            commands.append(DuplicateEntryCommand(self.document, position + offset))
            offset += 1
        if len(commands) == 1:
            self.command_manager.execute(commands[0])
        else:
            self.command_manager.execute(
                CompositeCommand(commands, "Duplicate subtitles"))

        # Splice the duplicates into the store in ascending order.
        for i, position in enumerate(positions_sorted):
            self.subtitle_list.entries_inserted(position + i + 1, 1)
        if positions_sorted:
            self.subtitle_list.select_entry(positions_sorted[-1] + offset)
        self._update_title()
        self._update_status()
        self._document_mutated()
        self._refresh_video_preview()

        count = len(positions)
        self._show_toast(f"{count} subtitle{'s' if count > 1 else ''} duplicated")

    def _on_move_up(self, action, param):
        """Move the selected entry up."""
        if not self.document:
            return
        self.editor_panel.flush_pending_changes()
        position = self.subtitle_list.get_selected_position()
        if position > 0:
            cmd = MoveEntryCommand(self.document, position, position - 1)
            self.command_manager.execute(cmd)

            self.subtitle_list.entry_moved(position, position - 1)
            self.subtitle_list.select_entry(position - 1)
            self._update_title()
            self._document_mutated()
            self._refresh_video_preview()

    def _on_move_down(self, action, param):
        """Move the selected entry down."""
        if not self.document:
            return
        self.editor_panel.flush_pending_changes()
        position = self.subtitle_list.get_selected_position()
        if position >= 0 and position < len(self.document.entries) - 1:
            cmd = MoveEntryCommand(self.document, position, position + 1)
            self.command_manager.execute(cmd)

            self.subtitle_list.entry_moved(position, position + 1)
            self.subtitle_list.select_entry(position + 1)
            self._update_title()
            self._document_mutated()
            self._refresh_video_preview()
    
    def _on_time_shift(self, action, param):
        """Show time shift dialog."""
        if not self.document or not self.document.entries:
            return
        self.editor_panel.flush_pending_changes()
        dialog = TimeShiftDialog(self)
        dialog.present()

    def _on_ass_info_styles(self, action, param):
        """Show ASS/SSA Script Info dialog."""
        if not self.document:
            return
        if self.document.format not in (SubtitleFormat.ASS, SubtitleFormat.SSA):
            self._show_toast("This is only available for ASS/SSA files")
            return

        dialog = ASSInfoDialog(self)
        dialog.present()

    def _on_ass_styles(self, action, param):
        """Show ASS/SSA styles dialog."""
        if not self.document:
            return
        if self.document.format not in (SubtitleFormat.ASS, SubtitleFormat.SSA):
            self._show_toast("This is only available for ASS/SSA files")
            return

        dialog = ASSStylesDialog(self)
        dialog.present()

    def _on_bulk_apply_style(self, action, param):
        """Bulk apply a style to multiple subtitles (ASS/SSA)."""
        if not self.document:
            return
        if self.document.format not in (SubtitleFormat.ASS, SubtitleFormat.SSA):
            self._show_toast("This is only available for ASS/SSA files")
            return
        if not self.document.entries:
            return

        dialog = BulkApplyStyleDialog(self)
        dialog.present()

    def _on_batch_style_props(self, action, param):
        """Batch-edit style definitions: font, colours, layout (ASS/SSA)."""
        if not self.document:
            return
        if self.document.format not in (SubtitleFormat.ASS, SubtitleFormat.SSA):
            self._show_toast("This is only available for ASS/SSA files")
            return
        if not self.document.styles:
            return

        dialog = BatchStylePropsDialog(self)
        dialog.present()
    
    def _on_sort_by_time(self, action, param):
        """Sort subtitles by start time."""
        if self.document:
            self.editor_panel.flush_pending_changes()
            from gsub.commands import SortByTimeCommand
            cmd = SortByTimeCommand(self.document)
            self.command_manager.execute(cmd)
            self.subtitle_list.refresh(preserve_selection=True)
            self._update_title()
            self._document_mutated()
            self._refresh_video_preview()
            self._show_toast("Subtitles sorted by time")
    
    # --- Batch operation handlers ---

    def _on_batch_selection_changed(self, widget):
        """Handle batch file selection changes."""
        self._update_batch_action_buttons()

    def _on_batch_files_changed(self, widget):
        """Handle batch file list changes."""
        files = self.batch_file_list.get_all_files()
        current = {id(item) for item in files}
        # Commands may reference several files. Removing any file establishes
        # a new history boundary so undo cannot mutate an invisible document.
        if self._batch_saved_content.keys() - current:
            self.batch_command_manager.clear()
        self._batch_saved_content = {
            id(item): self._batch_saved_content.get(id(item), self._batch_content(item.document))
            for item in files
        }
        if self.batch_file_list.file_count == 0:
            # An emptied batch is a fresh batch: drop the established format
            # so the next added file can be of any format again.
            self.batch_format = None
        self._refresh_batch_context()
        self._update_batch_action_buttons()
        self._update_batch_status()
        self._update_undo_redo_buttons()
        self._snapshot_recovery()

    @staticmethod
    def _batch_content(document):
        parser = SRTParser if document.format == SubtitleFormat.SRT else ASSParser
        return parser.serialize(document)

    def _refresh_batch_after_change(self):
        """Update file badges and dirty states relative to their last save."""
        for item in self.batch_file_list.get_all_files():
            item.modified = (self._batch_content(item.document)
                             != self._batch_saved_content[id(item)])
            item.document.modified = item.modified
        self.batch_file_list.update_ui()
        self._refresh_batch_context()
        self._update_batch_action_buttons()
        if self.current_view == "batch":
            self._update_batch_status()
        self._update_undo_redo_buttons()
        self._queue_recovery()

    def _refresh_batch_context(self):
        """Update batch panel context from the currently loaded files.

        - Style properties: the editor targets the shared styles (intersection
          of style names across all loaded ASS/SSA files), with the first
          ASS/SSA file's definitions as row defaults / preview base.
        - Resolution: prefill PlayResX/PlayResY if every loaded ASS/SSA file
          shares the same values, so the user can see the previous resolution.
        """
        ass_docs = [
            item.document for item in self.batch_file_list.get_all_files()
            if item.document.format in (SubtitleFormat.ASS, SubtitleFormat.SSA)
        ]

        shared_names = set(compute_shared_styles(ass_docs))
        base_styles = (
            [s for s in ass_docs[0].styles if s.name in shared_names]
            if ass_docs else []
        )
        self.batch_operations.set_style_props_styles(base_styles)

        # Resolution prefill when all ASS/SSA docs agree
        width, height = common_resolution(ass_docs)
        if width is not None and height is not None:
            self.batch_operations.res_width_row.set_value(width)
            self.batch_operations.res_height_row.set_value(height)
        else:
            self.batch_operations.res_width_row.set_value(0)
            self.batch_operations.res_height_row.set_value(0)

    def _on_batch_ops_changed(self, widget):
        """Handle batch operations changes."""
        self._update_batch_action_buttons()

    def _update_batch_action_buttons(self):
        """Enable/disable batch action buttons based on state."""
        has_files = self.batch_file_list.file_count > 0
        has_selected = len(self.batch_file_list.get_selected_files()) > 0
        has_ops = self.batch_operations.has_any_operation()

        # With no files loaded the whole operations panel stays inert (the
        # file list itself remains active so files can still be added).
        self.batch_operations.set_sensitive(has_files)

        self.batch_apply_btn.set_sensitive(has_selected and has_ops)
        self.batch_save_btn.set_sensitive(has_selected)
        self.batch_save_as_btn.set_sensitive(has_selected)

    def _update_batch_status(self):
        """Update the status bar for batch view."""
        total = self.batch_file_list.file_count
        selected = len(self.batch_file_list.get_selected_files())
        if total == 0:
            self.status_bar.set_text("No files loaded.")
        else:
            fmt = self.batch_format.value.upper() if self.batch_format else ""
            self.status_bar.set_text(f"{total} files ({selected} selected) • {fmt} format")

    def _on_batch_add_files(self):
        """Open a file dialog to add multiple subtitle files to the batch list."""
        dialog = Gtk.FileDialog()
        dialog.set_title("Add Subtitle Files")

        # Set up file filters
        filters = Gio.ListStore.new(Gtk.FileFilter)

        filter_all_subs = Gtk.FileFilter()
        filter_all_subs.set_name("All Subtitle Files")
        filter_all_subs.add_pattern("*.srt")
        filter_all_subs.add_pattern("*.ass")
        filter_all_subs.add_pattern("*.ssa")
        filters.append(filter_all_subs)

        filter_srt = Gtk.FileFilter()
        filter_srt.set_name("SRT Files")
        filter_srt.add_pattern("*.srt")
        filters.append(filter_srt)

        filter_ass = Gtk.FileFilter()
        filter_ass.set_name("ASS/SSA Files")
        filter_ass.add_pattern("*.ass")
        filter_ass.add_pattern("*.ssa")
        filters.append(filter_ass)

        dialog.set_filters(filters)
        dialog.set_default_filter(filter_all_subs)

        # Set default filter to match existing batch format if any
        if self.batch_format == SubtitleFormat.SRT:
            dialog.set_default_filter(filter_srt)
        elif self.batch_format in (SubtitleFormat.ASS, SubtitleFormat.SSA):
            dialog.set_default_filter(filter_ass)

        if self.last_directory:
            dialog.set_initial_folder(Gio.File.new_for_path(self.last_directory))
        dialog.open_multiple(self, None, self._on_batch_add_files_response)

    def _on_batch_add_files_response(self, dialog, result):
        """Handle batch file selection dialog response."""
        try:
            files = dialog.open_multiple_finish(result)
            if not files:
                return

            self._add_batch_files(files)

        except Exception:
            pass  # User cancelled

    def _add_batch_files(self, files) -> int:
        """Load subtitle files into the batch list; returns how many were added.

        Shared by the file chooser and drag-and-drop. Files whose format
        differs from the batch's established format are skipped with a toast.
        """
        added = 0
        for gfile in files:
            file_path = gfile.get_path() if gfile is not None else None
            if not file_path:
                continue
            try:
                success, contents, _ = gfile.load_contents(None)
                if not success:
                    continue

                content = decode_subtitle_text(contents)
                ext = os.path.splitext(file_path)[1].lower()

                doc, _warnings = parse_subtitle_document(content, ext)
                if doc is None:
                    continue

                doc.file_path = file_path

                # Enforce same format for all files
                if self.batch_format is None:
                    self.batch_format = doc.format
                elif doc.format != self.batch_format:
                    self._show_toast(
                        f"Skipped {os.path.basename(file_path)}: "
                        f"expected {self.batch_format.value.upper()} format"
                    )
                    continue

                self.batch_file_list.add_file(doc, file_path)
                self._save_last_directory(os.path.dirname(file_path))
                self._show_toast(f"Added {os.path.basename(file_path)}")
                added += 1

            except Exception as e:
                self._show_toast(f"Error loading {os.path.basename(file_path)}: {str(e)}")

        self._update_batch_status()
        self._update_batch_action_buttons()
        return added

    def _on_batch_apply(self):
        """Apply configured operations to all selected batch files."""
        selected = self.batch_file_list.get_selected_files()
        if not selected:
            return

        if not self.batch_operations.has_any_operation():
            self._show_toast("No operations configured")
            return

        # Show confirmation dialog
        summary = self.batch_operations.get_summary()
        confirm = BatchConfirmDialog(
            self,
            file_count=self.batch_file_list.file_count,
            operation_summary=summary,
            selected_count=len(selected),
            format_name=self.batch_format.value.upper() if self.batch_format else ""
        )
        confirm.connect('closed', lambda d: self._on_batch_confirm_closed(d, selected))
        confirm.present()

    def _on_batch_confirm_closed(self, dialog, selected_files):
        """Handle batch confirmation dialog close."""
        if not dialog.is_confirmed():
            return

        current_ids = {id(item) for item in self.batch_file_list.get_all_files()}
        items = [item for item in selected_files if id(item) in current_ids]
        operations = self.batch_operations
        offset = int(operations.offset_row.get_value()) if operations.has_time_shift() else None
        resolution = ((int(operations.res_width_row.get_value()),
                       int(operations.res_height_row.get_value()))
                      if operations.has_resolution_change() else None)
        style_editor = operations.style_props
        has_styles = operations.has_style_props_change()
        command = BatchOperationsCommand(
            items, offset_ms=offset, resolution=resolution,
            target_styles=style_editor.get_target_styles() if has_styles else (),
            style_properties=style_editor.get_checked_props() if has_styles else None)
        if not command.changed:
            self._show_toast("No batch files changed")
            return
        self.batch_command_manager.execute(command)
        self._refresh_batch_after_change()
        count = command.changed_count
        self._show_toast(f"Applied changes to {count} file{'s' if count != 1 else ''}")

    def _on_batch_save_all(self):
        """Save all selected batch files in-place."""
        selected = self.batch_file_list.get_selected_files()
        if selected:
            self._save_batch_items(selected)

    def _on_batch_save_all_as(self):
        """Save all selected batch files to a chosen directory."""
        selected = self.batch_file_list.get_selected_files()
        if not selected:
            return

        # Use folder selection dialog
        folder_dialog = Gtk.FileDialog()
        folder_dialog.set_title("Select Output Directory")

        if self.last_directory:
            folder_dialog.set_initial_folder(Gio.File.new_for_path(self.last_directory))

        folder_dialog.select_folder(self, None, lambda d, r: self._on_batch_save_dir_selected(d, r, selected))

    def _on_batch_save_dir_selected(self, dialog, result, selected_files):
        """Handle output directory selection for batch save."""
        try:
            folder = dialog.select_folder_finish(result)
            if not folder:
                return

            output_dir = folder.get_path()

            # Let the user pick a naming pattern before anything is written.
            rename = BatchRenameDialog(
                self,
                filenames=[item.filename for item in selected_files],
            )

            def on_rename_closed(rename_dialog):
                if not rename_dialog.is_confirmed():
                    return

                names = rename_dialog.get_output_names()
                saved = 0
                for item, filename in zip(selected_files, names):
                    try:
                        dest_path = os.path.join(output_dir, filename)

                        if item.document.format == SubtitleFormat.SRT:
                            content = SRTParser.serialize(item.document)
                        else:
                            content = ASSParser.serialize(item.document)

                        atomic_write_text(dest_path, content)

                        item.document.modified = False
                        item.modified = False
                        item.file_path = dest_path
                        item.document.file_path = dest_path
                        self._batch_saved_content[id(item)] = content
                        saved += 1
                    except Exception as e:
                        self._show_toast(f"Error saving {item.filename}: {str(e)}")

                if saved > 0:
                    self._show_toast(f"Saved {saved} file{'s' if saved != 1 else ''} to {output_dir}")
                self._update_batch_status()
                self._snapshot_recovery()

            rename.connect('closed', on_rename_closed)
            rename.present(self)

        except Exception:
            pass  # User cancelled

    def _on_about(self, action, param):
        """Show about dialog."""
        about = Adw.AboutWindow(
            transient_for=self,
            application_name="Gsub",
            application_icon="io.github.obaidaalbitar.gsub",
            developer_name="Gsub Contributors",
            version=__version__,
            license_type=Gtk.License.GPL_3_0,
            developers=["Gsub Contributors"],
            comments="A modern subtitle editor"
        )
        about.present()
    
    def _on_show_shortcuts(self, action, param):
        """Show keyboard shortcuts dialog."""
        shortcuts = build_shortcuts_dialog()
        shortcuts.present(self)
    
    def _on_batch(self, action, param):
        """Navigate to batch operations view."""
        self._navigate_to_batch()

    def _on_convert_to_srt(self, action, param):
        """Convert current document to SRT format."""
        if not self.document:
            self._show_toast("No document loaded")
            return
        
        if self.document.format == SubtitleFormat.SRT:
            self._show_toast("Document is already in SRT format")
            return
        
        # Confirm conversion (Adw.AlertDialog — the modern libadwaita API).
        dialog = Adw.AlertDialog.new(
            "Convert to SRT?",
            "Converting to SRT will remove all styling information. This cannot be undone."
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("convert", "Convert")
        dialog.set_response_appearance("convert", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")

        def _on_srt_choose(_dialog, task, _user_data):
            response = dialog.choose_finish(task)
            self._on_convert_response(response, SubtitleFormat.SRT)

        dialog.choose(self, None, _on_srt_choose, None)

    def _on_convert_to_ass(self, action, param):
        """Convert current document to ASS format."""
        if not self.document:
            self._show_toast("No document loaded")
            return

        if self.document.format == SubtitleFormat.ASS:
            self._show_toast("Document is already in ASS format")
            return

        # Confirm conversion
        heading = "Convert to ASS?"
        if self.document.format == SubtitleFormat.SRT:
            body = "Converting to ASS will add default styling to all subtitles."
        else:
            body = "Convert to ASS format?"

        dialog = Adw.AlertDialog.new(heading, body)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("convert", "Convert")
        dialog.set_response_appearance("convert", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("convert")
        dialog.set_close_response("cancel")

        def _on_ass_choose(_dialog, task, _user_data):
            response = dialog.choose_finish(task)
            self._on_convert_response(response, SubtitleFormat.ASS)

        dialog.choose(self, None, _on_ass_choose, None)

    def _on_convert_response(self, response, target_format):
        """Handle format conversion confirmation."""
        if response == "convert":
            from gsub.converters import FormatConverter

            self.editor_panel.flush_pending_changes()
            self._close_document_dialogs()
            old_format = self.document.format.value.upper()
            self.document = FormatConverter.convert(self.document, target_format)
            self.command_manager.clear()
            self.editor_panel.clear()

            # Update UI
            self.subtitle_list.set_document(self.document)
            self._reset_playback_highlight()
            style_names = [s.name for s in (self.document.styles or [])] if self.document else []
            self.editor_panel.set_document_context(self.document.format, style_names)
            self._update_format_actions()
            self._update_title()
            self._update_status()
            
            # Update video player document if available
            if self.video_player:
                self.video_player.set_document(self.document)

            self._document_mutated()

            self._show_toast(f"Converted from {old_format} to {target_format.value.upper()}")
            
            # Suggest saving
            if self.current_file:
                self._show_banner(
                    "Format converted. Save to preserve changes.",
                    "Save As",
                    lambda: self._on_save_as(None, None)
                )
    
    # Widget signal handlers

    def _on_subtitle_selection_changed(self, widget):
        """Keep selection-dependent entry actions in sync with the list."""
        self._update_selection_actions()

    def _on_entry_selected(self, widget, position):
        """Handle subtitle entry selection."""
        if not self.document:
            return
        self.editor_panel.flush_pending_changes()
        if len(self.subtitle_list.get_selected_positions()) > 1:
            self.editor_panel.clear()
            self.editor_panel.set_sensitive(False)
            if self.video_player:
                self.video_player.set_selected_position(-1)
            return
        if 0 <= position < len(self.document.entries):
            entry = self.document.entries[position]
            self.editor_panel.set_entry(entry, position)
            if self.video_player:
                self.video_player.set_selected_position(position)
        elif self.video_player:
            # Selection lost (e.g. everything unselected): clear the region
            # highlight too.
            self.video_player.set_selected_position(-1)
    
    def _on_entry_activated(self, widget, position):
        """Handle subtitle entry activation (double-click)."""
        # Focus the text editor
        self.editor_panel.focus_text()
    
    def _on_text_changed(self, widget, position, new_text):
        """Handle text change in editor panel."""
        if not self.document or position < 0:
            return
        
        from gsub.commands import EditTextCommand
        
        cmd = EditTextCommand(self.document, position, new_text)
        self.command_manager.execute(cmd)

        self.subtitle_list.refresh_entry(position)
        self._update_title()
        self._document_mutated()
        if self.video_player:
            self.video_player.queue_subtitle_redraw()

    def _on_timing_changed(self, widget, position, start_time, end_time):
        """Handle timing change in editor panel."""
        if not self.document or position < 0:
            return
        
        from gsub.commands import EditTimingCommand
        
        cmd = EditTimingCommand(self.document, position, start_time, end_time)
        self.command_manager.execute(cmd)

        self.subtitle_list.refresh_entry(position)
        self._update_title()
        self._document_mutated()
        if self.video_player:
            self.video_player.queue_subtitle_redraw()

    def _on_style_changed(self, widget, position, new_style):
        """Handle style change in editor panel (ASS/SSA only)."""
        if not self.document or position < 0:
            return
        if self.document.format not in (SubtitleFormat.ASS, SubtitleFormat.SSA):
            return

        from gsub.commands import EditStyleCommand

        cmd = EditStyleCommand(self.document, position, new_style)
        self.command_manager.execute(cmd)

        self.subtitle_list.refresh_entry(position)
        self._update_title()
        self._document_mutated()
        if self.video_player:
            self.video_player.queue_subtitle_redraw()

    def _on_position_changed(self, widget, position, margin_l, margin_r, margin_v):
        """Handle position (margin) change in editor panel (ASS/SSA only)."""
        if not self.document or position < 0:
            return
        if self.document.format not in (SubtitleFormat.ASS, SubtitleFormat.SSA):
            return
        
        from gsub.commands import EditMarginsCommand
        
        cmd = EditMarginsCommand(self.document, position, margin_l, margin_r, margin_v)
        self.command_manager.execute(cmd)
        
        # Update video player to reflect position changes
        if self.video_player:
            self.video_player.queue_subtitle_redraw()

        self._update_title()
        self._document_mutated()

    # --- Compatibility checking ---

    def _installed_font_names(self) -> list:
        """Sorted installed font family names (cached; rarely changes)."""
        if getattr(self, "_cached_installed_fonts", None) is None:
            self._cached_installed_fonts = sorted(
                f.get_name() for f in PangoCairo.FontMap.get_default().list_families())
        return self._cached_installed_fonts

    def _collect_compat_issues(self) -> list:
        """Collect compatibility issues from the validator plus Pango
        glyph-coverage checks for each style's font."""
        if not self.document:
            return []
        if self.document.format not in (SubtitleFormat.ASS, SubtitleFormat.SSA):
            return []

        installed = self._installed_font_names()
        issues = validate_document(self.document, installed_fonts=installed)
        issues.extend(collect_glyph_coverage_issues(self.document, installed))
        return issues

    def _refresh_compat(self):
        """Recompute compatibility issues and push them to the panel."""
        self.compat_issues = self._collect_compat_issues()
        self.compat_panel.set_issues(self.compat_issues)
        self._update_compat_button()

    def _apply_compat_fix(self, issue: CompatIssue):
        """Apply an automatic fix for a compatibility issue (undoable).

        Only issues carrying a ``fix`` dict are actionable; others simply show
        no Fix button in the panel. After applying, the panel is refreshed so
        the resolved issue disappears.
        """
        if not self.document or not issue.fix:
            return
        if self.document.format not in (SubtitleFormat.ASS, SubtitleFormat.SSA):
            self._show_toast("Automatic fixes are only available for ASS/SSA files")
            return

        fix = issue.fix
        kind = fix.get("kind")
        cmds = []

        if kind == "color":
            style_name = fix.get("style") or ""
            style = (self.document.get_style_by_name(style_name)
                     if style_name else None)
            if style is None:
                self._show_toast("Could not determine the style for this fix.")
                return
            field = fix.get("field")
            if field not in COLOR_FIELD_ATTR.values():
                self._show_toast("Could not determine the field for this fix.")
                return
            new_styles = [copy.deepcopy(s) for s in self.document.styles]
            for s in new_styles:
                if s.name == style_name:
                    setattr(s, field, fix_color(fix, style))
            cmds.append(ReplaceASSHeaderCommand(
                self.document,
                metadata=self.document.metadata,
                aegisub_project_garbage=getattr(
                    self.document, 'aegisub_project_garbage', {}),
                styles=new_styles,
            ))
            self._show_toast("Fixed: color corrected")

        elif kind == "spacing":
            style_name = fix.get("style")
            if not style_name:
                self._show_toast("Could not determine the style for this fix.")
                return
            new_styles = [copy.deepcopy(s) for s in self.document.styles]
            for s in new_styles:
                if s.name == style_name:
                    s.spacing = 0.0
            cmds.append(ReplaceASSHeaderCommand(
                self.document,
                metadata=self.document.metadata,
                aegisub_project_garbage=getattr(
                    self.document, 'aegisub_project_garbage', {}),
                styles=new_styles,
            ))
            # Also strip any per-entry \fsp overrides that break joining.
            for entry in self.document.entries:
                if entry.style == style_name and "\\fsp" in entry.text:
                    new_text = strip_fsp(entry.text)
                    if new_text != entry.text:
                        pos = entry.index - 1
                        cmds.append(EditTextCommand(
                            self.document, pos, new_text))
            self._show_toast("Fixed: spacing set to 0")

        elif kind == "blur":
            entry = next((e for e in self.document.entries
                          if e.index == fix.get("entry_index")), None)
            if entry is None:
                self._show_toast("Could not find the subtitle for this fix.")
                return
            new_text = clamp_blur(entry.text)
            if new_text == entry.text:
                self._show_toast("Nothing to fix")
                return
            cmds.append(EditTextCommand(self.document, entry.index - 1, new_text))
            self._show_toast("Fixed: \\blur clamped")

        else:
            self._show_toast("No automatic fix available for this issue.")
            return

        if not cmds:
            return
        command = cmds[0] if len(cmds) == 1 else CompositeCommand(
            cmds, "Fix compatibility issue")
        self.command_manager.execute(command)
        self.document.modified = True
        self._update_title()
        self._document_mutated()
        self._refresh_video_preview()

    # Video player handlers

    def _refresh_video_preview(self):
        """Ask the video player to reload the editor subtitle (debounced)."""
        if self.video_player:
            self.video_player.queue_subtitle_redraw()

    def _on_open_video(self, action, param):
        """Open a video file."""
        dialog = Gtk.FileDialog()
        dialog.set_title("Open Video File")
        
        # Set up file filters for video files
        filters = Gio.ListStore.new(Gtk.FileFilter)
        
        filter_video = Gtk.FileFilter()
        filter_video.set_name("Video Files")
        filter_video.add_mime_type("video/*")
        filter_video.add_pattern("*.mp4")
        filter_video.add_pattern("*.mkv")
        filter_video.add_pattern("*.avi")
        filter_video.add_pattern("*.webm")
        filter_video.add_pattern("*.mov")
        filter_video.add_pattern("*.wmv")
        filter_video.add_pattern("*.flv")
        filters.append(filter_video)
        
        filter_all = Gtk.FileFilter()
        filter_all.set_name("All Files")
        filter_all.add_pattern("*")
        filters.append(filter_all)
        
        dialog.set_filters(filters)
        dialog.set_default_filter(filter_video)
        
        if self.last_directory:
            dialog.set_initial_folder(Gio.File.new_for_path(self.last_directory))
        dialog.open(self, None, self._on_open_video_response)
    
    def _on_open_video_response(self, dialog, result):
        """Handle video file open dialog response."""
        try:
            file = dialog.open_finish(result)
            if file:
                file_path = file.get_path()
                if file_path:
                    self.load_video_path(file_path)
                    self._save_last_directory(os.path.dirname(file_path))
        except Exception:
            pass  # User cancelled

    def open_video(self, gfile: Gio.File):
        """Open a video file, e.g. passed on the command line or via "Open With".

        Falls back to an error when the file has no local path (e.g. a URI).
        """
        file_path = gfile.get_path() if gfile is not None else None
        if not file_path:
            self._show_error("Cannot open video: no local file path")
            return
        self.load_video_path(file_path)

    # --- Drag and drop --------------------------------------------------------

    @staticmethod
    def _is_video_file(gfile) -> bool:
        """Return True when the file's content type is a video type.

        Any failure to query the content type falls back to "not a video" so
        the file is still opened through the regular subtitle path. Mirrors
        ``GsubApplication._is_video_file`` in main.py.
        """
        try:
            info = gfile.query_info(
                Gio.FILE_ATTRIBUTE_STANDARD_CONTENT_TYPE,
                Gio.FileQueryInfoFlags.NONE,
                None,
            )
            return is_video_content_type(
                info.get_attribute_string(Gio.FILE_ATTRIBUTE_STANDARD_CONTENT_TYPE))
        except Exception:
            return False

    def _attach_file_drop_target(self, widget, callback):
        """Let ``widget`` accept files dragged in from a file manager."""
        target = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        target.connect('drop', callback)
        widget.add_controller(target)

    def _on_editor_files_drop(self, target, value, x, y):
        """Open dragged files in the editor: the first subtitle becomes the
        document, the first video loads into the player."""
        files = value.get_files() if value is not None else []
        videos = [f for f in files if self._is_video_file(f)]
        others = [f for f in files if not self._is_video_file(f)]

        if others:
            self.open_file(others[0])
            if len(others) > 1:
                self._show_toast("Only the first subtitle was opened")
        if videos:
            self.open_video(videos[0])
            if len(videos) > 1:
                self._show_toast("Only the first video was opened")
        return True

    def _on_batch_files_drop(self, target, value, x, y):
        """Add dragged subtitle files to the batch list."""
        files = value.get_files() if value is not None else []
        videos = [f for f in files if self._is_video_file(f)]
        subtitles = [f for f in files if not self._is_video_file(f)]

        if videos:
            self._show_toast("Videos cannot be added in batch mode")
        if subtitles:
            self._add_batch_files(subtitles)
        return True

    def load_video_path(self, file_path: str):
        """Load a video into the player and reveal the video pane.

        Shared by the file chooser response and :meth:`open_video`. The
        player's ``tracks-ready`` signal (emitted once mpv has parsed the
        track list) opens the track-selection dialog when the layout needs a
        user decision, replacing the old timeout-based checks.

        Navigates to the editor view first so a video opened via "Open With"
        (cold start on the home view) actually shows the player.
        """
        self._navigate_to_editor()
        self.current_video_file = file_path
        self.video_player.load_video(file_path)
        self._update_selection_actions()

        # Show video player if hidden
        if not self.video_visible:
            self.video_visible = True
            self.video_container.set_visible(True)
            self.video_button.set_active(True)
            # Expand the paned to show video player
            self.right_paned.set_position(300)

        self._show_toast(f"Loaded video: {os.path.basename(file_path)}")

    def _on_tracks_ready(self, player):
        """Show the unified track dialog once the player parsed the tracks.

        No dialog is shown for the common layout of a single audio track and
        no embedded subtitles (see :func:`should_show_track_dialog`).
        """
        audio_tracks, subtitle_tracks = self.video_player.get_available_tracks()
        if not should_show_track_dialog(len(audio_tracks), len(subtitle_tracks)):
            return
        self._show_track_selection_dialog()

    def _show_track_selection_dialog(self):
        """Show the track selection dialog (single constructor site).

        Used both automatically (via ``tracks-ready`` after loading a video)
        and manually (the ``win.select-tracks`` action).
        """
        audio_tracks, subtitle_tracks = self.video_player.get_available_tracks()

        track_dialog = TrackSelectionDialog(
            self,
            audio_tracks,
            subtitle_tracks,
            self.video_player.current_audio_track,
            self.video_player.current_subtitle_track
        )
        track_dialog.connect("tracks-selected", self._on_tracks_selected)
        track_dialog.present()
    
    def _on_toggle_video(self, action, param):
        """Toggle video player visibility."""
        self.video_button.set_active(not self.video_button.get_active())

    def _on_play_pause(self, action, param):
        """Toggle video playback (Space)."""
        if self.current_video_file:
            self.video_player.toggle_play_pause()

    def _on_go_to_time(self, action, param):
        """Edit the playback position without changing subtitle timing."""
        if not self.current_video_file:
            self._show_toast("Open a video first")
            return
        self._navigate_to_editor()
        if not self.video_visible:
            self.video_button.set_active(True)
        if not self.video_player.show_timestamp_navigation():
            self._show_toast("Wait for the video player to finish loading")

    # Precise navigation on the timeline (all guarded on a loaded video).

    def _nudge_video(self, seconds: float):
        """Exact-seek relative to the current position (clamped at 0)."""
        if not self.current_video_file:
            return
        target = self.video_player.get_position() + seconds
        self.video_player.seek(max(0.0, target))

    def _on_seek_nudge_back(self, action, param):
        """Nudge 0.1 s back (Left)."""
        self._nudge_video(-0.1)

    def _on_seek_nudge_forward(self, action, param):
        """Nudge 0.1 s forward (Right)."""
        self._nudge_video(0.1)

    def _on_seek_nudge_back_large(self, action, param):
        """Jump 5 s back (Shift+Left)."""
        self._nudge_video(-5.0)

    def _on_seek_nudge_forward_large(self, action, param):
        """Jump 5 s forward (Shift+Right)."""
        self._nudge_video(5.0)

    def _on_frame_step(self, action, param):
        """Advance one frame (period)."""
        if self.current_video_file:
            self.video_player.frame_step(back=False)

    def _on_frame_back_step(self, action, param):
        """Go back one frame (comma)."""
        if self.current_video_file:
            self.video_player.frame_step(back=True)

    def _on_seek_to_selection(self, action, param):
        """Play from the selected subtitle's start (Ctrl+J)."""
        if not self.current_video_file:
            return
        position = self.subtitle_list.get_selected_position()
        if (position < 0 or not self.document
                or position >= len(self.document.entries)):
            self._show_toast("No subtitle selected")
            return
        start_ms = self.document.entries[position].start_time.total_milliseconds
        self.video_player.seek(start_ms / 1000.0)

    # --- Playback <-> subtitle list sync ---------------------------------

    def _reset_playback_highlight(self):
        """Forget the highlight cache after the document was replaced."""
        self._active_highlight = -1
        self._last_highlight_time = 0

    def _on_player_position_changed(self, player, position):
        """Highlight the entry under the playhead (throttled).

        A pure lookup (binary search) runs at most every ~300 ms; the list is
        only touched when the active position actually changed.
        """
        now = GLib.get_monotonic_time()
        if now - self._last_highlight_time < _HIGHLIGHT_INTERVAL_US:
            return
        self._last_highlight_time = now
        entries = self.document.entries if self.document else []
        position_index = active_entry_at(entries, position)
        if position_index != self._active_highlight:
            self._active_highlight = position_index
            self.subtitle_list.highlight_active(position_index)

    # --- Timeline region interactions --------------------------------------

    def _on_region_adjusted(self, player, position, start_ms, end_ms):
        """Commit a region drag on the timeline as an undoable timing edit.

        Mirrors :meth:`_on_timing_changed` (same command and refresh
        sequence) and additionally refreshes the timeline's regions
        immediately instead of waiting for the debounced subtitle redraw.
        """
        if not self.document or not (0 <= position < len(self.document.entries)):
            return
        self.editor_panel.flush_pending_changes()
        entry = self.document.entries[position]
        if (entry.start_time.total_milliseconds == start_ms
                and entry.end_time.total_milliseconds == end_ms):
            return  # no-op: nothing moved

        from gsub.commands import EditTimingCommand

        cmd = EditTimingCommand(
            self.document, position,
            TimeCode.from_milliseconds(start_ms),
            TimeCode.from_milliseconds(end_ms),
        )
        self.command_manager.execute(cmd)

        self.subtitle_list.refresh_entry(position)
        if self.editor_panel.current_position == position:
            self.editor_panel.set_entry(entry, position)
        self._update_title()
        self._document_mutated()
        if self.video_player:
            self.video_player.queue_subtitle_redraw()
            self.video_player.refresh_timeline_regions()

    def _on_region_selected(self, player, position):
        """A region was Ctrl+clicked on the timeline: select that entry.

        Routes through the subtitle list so the existing selection path runs
        (editor panel update and the region highlight feedback loop).
        """
        if not self.document or not (0 <= position < len(self.document.entries)):
            return
        self.subtitle_list.select_entry(position)
    
    def _on_video_toggle(self, button):
        """Handle video player toggle button."""
        self.video_visible = button.get_active()
        self.video_container.set_visible(self.video_visible)
        
        if self.video_visible:
            # Expand the paned to show video player (300px default)
            if self.right_paned.get_position() == 0:
                self.right_paned.set_position(300)
            
            if not self.current_video_file:
                # Prompt to open video if none loaded
                GLib.idle_add(lambda: self._on_open_video(None, None))
        else:
            # Collapse the paned when hiding video
            self.right_paned.set_position(0)
    
    def _on_select_tracks(self, action, param):
        """Manually open track selection dialog."""
        if not self.current_video_file:
            self._show_toast("No video loaded")
            return

        has_audio, has_subtitles = self.video_player.has_embedded_tracks()

        if not has_audio and not has_subtitles:
            self._show_toast("No embedded tracks found in video")
            return

        self._show_track_selection_dialog()

    def _on_tracks_selected(self, dialog, audio_track, subtitle_track):
        """Handle track selection from the unified track dialog.

        Applies the audio/subtitle selection to the player and, when the
        dialog's extract switch was enabled, extracts the chosen subtitle
        track into the editor instead of just showing it in the video.
        """
        # Read the extract switch before closing (the dialog may be torn down).
        wants_extract = dialog.get_extract_selected()
        dialog.close()

        # Set audio track (can be changed independently)
        if audio_track >= 0:
            self.video_player.set_audio_track(audio_track)
            self._show_toast(f"Audio track {audio_track + 1} selected")

        if subtitle_track >= 0:
            if wants_extract:
                # Extract the chosen track for editing; its completion handler
                # disables the embedded track before loading the external file.
                self._extract_and_load_subtitle(subtitle_track)
            else:
                # View only - the embedded track stays enabled in the player
                self.video_player.set_subtitle_track(subtitle_track)
        elif subtitle_track == -1:
            # Disable embedded subtitles
            self.video_player.set_subtitle_track(-1)
            self._show_toast("Using external subtitles")
    
    def _extract_and_load_subtitle(self, track_index):
        """Protect edits before replacing them with an extracted track."""
        self._request_document_replacement(
            lambda: self._extract_and_load_subtitle_now(track_index))

    def _extract_and_load_subtitle_now(self, track_index):
        """Extract a subtitle track and load it for editing.

        *track_index* is the mpv subtitle track id returned by the selection
        dialog, not a list position.
        """
        # Get track info
        audio_tracks, subtitle_tracks = self.video_player.get_available_tracks()

        # Resolve the mpv track id to its position in the track list.
        pos = next(
            (i for i, t in enumerate(subtitle_tracks) if t.get("id") == track_index),
            None,
        )
        if pos is None:
            self._show_toast("Invalid track index")
            return

        track_info = subtitle_tracks[pos]
        track_name = track_info.get('title') or f"Track {pos + 1}"
        language = track_info.get('language', 'unknown')

        # Detect the source format so the temp file keeps the correct extension
        # (e.g. .ass for ASS/SSA tracks) and styles are preserved.
        fmt = self.video_player.subtitle_track_format(track_index) or 'srt'
        suffix = EXTENSION_FOR_FORMAT.get(fmt, '.srt')

        # Create temp file for extraction
        import tempfile
        temp_fd, temp_path = tempfile.mkstemp(suffix=suffix, prefix=f'subtitle_{language}_')
        os.close(temp_fd)

        # Show progress toast
        self._show_toast(f"Extracting '{track_name}'...")

        # Extract subtitle
        def on_extract_complete(success, error_msg, format_=None):
            if success:
                # HTML stripping is only meaningful for SRT. For ASS/SSA the
                # override codes ({...}) and \N line breaks are part of the
                # styling and must be preserved.
                if format_ == 'srt':
                    try:
                        self._clean_subtitle_html(temp_path)
                    except Exception as e:
                        logger.info(f"Warning: Failed to clean HTML: {e}")

                def load_extracted():
                    if not self._open_file_now(Gio.File.new_for_path(temp_path)):
                        return False
                    self.video_player.set_subtitle_track(-1)
                    # Extraction is a new unsaved document, not a saved file
                    # in /tmp. Save must ask for a durable destination.
                    self.current_file = self.document.file_path = None
                    self.document.modified = True
                    self._update_title()
                    self._snapshot_recovery()
                    self._show_toast(f"Loaded extracted subtitles: {track_name}")
                    try:
                        os.remove(temp_path)
                    except OSError:
                        pass
                    return True

                # Extraction is asynchronous; protect edits made while it ran.
                self._request_document_replacement(load_extracted)
            else:
                self._show_toast(f"Extraction failed: {error_msg}")
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

        # Start extraction
        self.video_player.extract_subtitle_track(track_index, temp_path, on_extract_complete)

    def _clean_subtitle_html(self, subtitle_path):
        r"""Remove HTML/font tags and fix ASS format issues from subtitle file.
        
        Many subtitle tracks contain HTML formatting tags like <font>, <b>, <i>
        which cause issues when displayed in Gtk labels expecting Pango markup.
        This function strips those tags while preserving the text content.
        
        Also handles ASS format conversion issues where newlines are represented
        as literal \N strings instead of actual newlines.
        """
        try:
            with open(subtitle_path, 'rb') as f:
                content = decode_subtitle_text(f.read())
            
            # Remove common HTML tags while preserving text
            # Pattern matches: <tag attr="value">text</tag> -> text
            content = re.sub(r'<font[^>]*>', '', content)
            content = re.sub(r'</font>', '', content)
            content = re.sub(r'<b>', '', content)
            content = re.sub(r'</b>', '', content)
            content = re.sub(r'<i>', '', content)
            content = re.sub(r'</i>', '', content)
            content = re.sub(r'<u>', '', content)
            content = re.sub(r'</u>', '', content)
            
            # Fix ASS format newlines: backslash-N should be actual newlines in SRT
            content = content.replace(r'\N', '\n')
            
            # Remove ASS drawing commands and other special codes
            # Curly braces with any content - ASS/SSA override codes
            content = re.sub(r'\{[^}]*\}', '', content)
            
            # Fix lines that have only one word (likely formatting issue)
            # This can happen with ASS subtitles that use special positioning
            # We'll try to merge lines that seem too short
            lines = content.split('\n')
            fixed_lines = []
            i = 0
            while i < len(lines):
                line = lines[i]
                # If line is a subtitle text line (not number, not timestamp, not empty)
                if line.strip() and not line.strip().isdigit() and '-->' not in line:
                    # Check if it's suspiciously short (single word)
                    if len(line.strip().split()) == 1 and i + 1 < len(lines):
                        # Look ahead to see if next line is also short text
                        next_line = lines[i + 1]
                        if next_line.strip() and not next_line.strip().isdigit() and '-->' not in next_line:
                            # Merge with next line
                            fixed_lines.append(line.rstrip() + ' ' + next_line.lstrip())
                            i += 2
                            continue
                fixed_lines.append(line)
                i += 1
            
            content = '\n'.join(fixed_lines)
            
            # Write cleaned content back
            with open(subtitle_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            logger.info(f"Cleaned and fixed formatting in {subtitle_path}")
        except Exception as e:
            logger.info(f"Error: {e}")
            raise
