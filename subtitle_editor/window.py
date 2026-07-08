"""
Main application window for the subtitle editor.

Following GNOME HIG, uses libadwaita widgets for a modern, native look.
"""

import gi
from subtitle_editor.logger import get_logger

logger = get_logger(__name__)
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, Gio, GLib
import json
import os

from subtitle_editor.extractors import EXTENSION_FOR_FORMAT
from subtitle_editor.models import SubtitleDocument, SubtitleFormat
from subtitle_editor.parsers import SRTParser, ASSParser
from subtitle_editor.commands import CommandManager
from subtitle_editor.resources import template_resource_path
from subtitle_editor.widgets.subtitle_list import SubtitleListView
from subtitle_editor.widgets.editor_panel import EditorPanel
from subtitle_editor.widgets.dialogs import TimeShiftDialog, BulkApplyStyleDialog, ASSInfoStylesDialog, build_shortcuts_dialog
from subtitle_editor.widgets.video_player import VideoPlayerWidget
from subtitle_editor.widgets.home_screen import HomeScreenView
from subtitle_editor.widgets.batch_file_list import BatchFileList
from subtitle_editor.widgets.batch_operations_panel import BatchOperationsPanel
from subtitle_editor.widgets.batch_confirm_dialog import BatchConfirmDialog


@Gtk.Template(resource_path=template_resource_path('window'))
class GsubWindow(Adw.ApplicationWindow):
    """Main application window."""

    __gtype_name__ = 'GsubWindow'

    # Template children (the static scaffold; child widgets are packed in code).
    toolbar_view = Gtk.Template.Child()
    banner = Gtk.Template.Child()
    header_bar = Gtk.Template.Child()
    menu_button = Gtk.Template.Child()
    title_widget = Gtk.Template.Child()
    header_start_stack = Gtk.Template.Child()
    toast_overlay = Gtk.Template.Child()
    view_stack = Gtk.Template.Child()
    bottom_bar = Gtk.Template.Child()
    status_bar = Gtk.Template.Child()
    action_box = Gtk.Template.Child()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        # Application state
        self.document: SubtitleDocument = None
        self.command_manager = CommandManager()
        self.current_file = None
        self.current_video_file = None
        self.video_visible = False
        self.current_view = "home"  # "home", "editor", or "batch"
        self.batch_format = None  # SubtitleFormat of batch files (all same format)

        # Load saved config
        config = self._load_config()
        self.last_directory = config.get("last_directory")

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
        self._update_title()
        self._update_format_actions()
        self._update_document_actions()

    def _build_header_start_stack(self):
        """Build the three per-view header layouts and add them to the
        header_start_stack via add_named() (Gtk.Stack page names only resolve
        when set this way, not from the template)."""
        # Home page: empty (no start buttons)
        home_header = Gtk.Box()
        self.header_start_stack.add_named(home_header, "home")

        # Editor page: nav buttons + Open/Save + Undo/Redo + Video toggle
        editor_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)

        nav_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        nav_box.add_css_class("linked")

        home_btn = Gtk.Button()
        home_btn.set_icon_name("go-home-symbolic")
        home_btn.set_tooltip_text("Home")
        home_btn.connect('clicked', lambda b: self._navigate_to_home())
        nav_box.append(home_btn)

        batch_btn = Gtk.Button()
        batch_btn.set_icon_name("folder-multiple-symbolic")
        batch_btn.set_tooltip_text("Batch Operations")
        batch_btn.connect('clicked', lambda b: self._navigate_to_batch())
        nav_box.append(batch_btn)

        editor_header.append(nav_box)

        separator = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        separator.set_margin_start(4)
        separator.set_margin_end(4)
        editor_header.append(separator)

        file_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        file_box.add_css_class("linked")

        open_button = Gtk.Button()
        open_button.set_icon_name("document-open-symbolic")
        open_button.set_tooltip_text("Open File (Ctrl+O)")
        open_button.set_action_name("win.open")
        file_box.append(open_button)

        self.save_button = Gtk.Button()
        self.save_button.set_icon_name("document-save-symbolic")
        self.save_button.set_tooltip_text("Save (Ctrl+S)")
        self.save_button.set_action_name("win.save")
        file_box.append(self.save_button)

        editor_header.append(file_box)

        undo_redo_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        undo_redo_box.add_css_class("linked")
        undo_redo_box.set_margin_start(6)

        self.undo_button = Gtk.Button()
        self.undo_button.set_icon_name("edit-undo-symbolic")
        self.undo_button.set_tooltip_text("Undo (Ctrl+Z)")
        self.undo_button.set_action_name("win.undo")
        self.undo_button.set_sensitive(False)
        undo_redo_box.append(self.undo_button)

        self.redo_button = Gtk.Button()
        self.redo_button.set_icon_name("edit-redo-symbolic")
        self.redo_button.set_tooltip_text("Redo (Ctrl+Shift+Z)")
        self.redo_button.set_sensitive(False)
        undo_redo_box.append(self.redo_button)

        editor_header.append(undo_redo_box)

        self.video_button = Gtk.ToggleButton()
        self.video_button.set_icon_name("video-display-symbolic")
        self.video_button.set_tooltip_text("Toggle Video Player (Ctrl+V)")
        self.video_button.connect('toggled', self._on_video_toggle)
        self.video_button.set_margin_start(6)
        editor_header.append(self.video_button)

        self.header_start_stack.add_named(editor_header, "editor")

        # Batch page: navigation + Add Files
        batch_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        batch_nav_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        batch_nav_box.add_css_class("linked")
        batch_home_btn = Gtk.Button()
        batch_home_btn.set_icon_name("go-home-symbolic")
        batch_home_btn.set_tooltip_text("Home")
        batch_home_btn.connect('clicked', lambda b: self._navigate_to_home())
        batch_nav_box.append(batch_home_btn)
        batch_editor_btn = Gtk.Button()
        batch_editor_btn.set_icon_name("accessories-text-editor-symbolic")
        batch_editor_btn.set_tooltip_text("Editor")
        batch_editor_btn.connect('clicked', lambda b: self._navigate_to_editor(show_open=False))
        batch_nav_box.append(batch_editor_btn)
        batch_header.append(batch_nav_box)

        separator2 = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        separator2.set_margin_start(4)
        separator2.set_margin_end(4)
        batch_header.append(separator2)

        batch_add_btn = Gtk.Button()
        add_content = Adw.ButtonContent()
        add_content.set_label("Add Files")
        add_content.set_icon_name("list-add-symbolic")
        batch_add_btn.set_child(add_content)
        batch_add_btn.set_tooltip_text("Add subtitle files to the batch")
        batch_add_btn.connect('clicked', lambda b: self._on_batch_add_files())
        batch_header.append(batch_add_btn)
        self.header_start_stack.add_named(batch_header, "batch")

    def _build_ui(self):
        """Instantiate the dynamic child widgets and pack them into the
        templated scaffold. The static layout (toolbar view, header bar,
        view stack, bottom bar) is defined in window.blp; the per-view
        header layouts are built here via add_named() so their stack page
        names resolve correctly."""

        # Header start buttons - use a stack to switch between views.
        self._build_header_start_stack()

        # --- Home page ---
        self.home_screen = HomeScreenView()
        self.home_screen.connect('open-file', lambda w: self._navigate_to_editor(show_open=True))
        self.home_screen.connect('open-batch', lambda w: self._navigate_to_batch())
        self.view_stack.add_titled(self.home_screen, "home", "Home")

        # --- Editor page (single-file editing) ---
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.view_stack.add_titled(main_box, "editor", "Editor")

        # Editing area - horizontal split (list + editor with video)
        self.paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self.paned.set_vexpand(True)
        self.paned.set_position(400)
        self.paned.set_shrink_start_child(False)
        self.paned.set_shrink_end_child(False)
        self.paned.set_resize_start_child(False)
        self.paned.set_resize_end_child(True)
        main_box.append(self.paned)

        # Left side: Subtitle list with card container
        list_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        list_container.add_css_class("background")
        self.subtitle_list = SubtitleListView()
        self.subtitle_list.connect('entry-selected', self._on_entry_selected)
        self.subtitle_list.connect('entry-activated', self._on_entry_activated)
        list_container.append(self.subtitle_list)
        self.paned.set_start_child(list_container)

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

        # --- Batch page ---
        batch_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.view_stack.add_titled(batch_box, "batch", "Batch Operations")

        self.batch_paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self.batch_paned.set_vexpand(True)
        self.batch_paned.set_position(350)
        batch_box.append(self.batch_paned)

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

        # Batch action buttons below operations
        batch_button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        batch_button_box.set_margin_start(12)
        batch_button_box.set_margin_end(12)
        batch_button_box.set_margin_top(18)
        batch_button_box.set_margin_bottom(12)

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

        batch_ops_container.append(batch_button_box)
        self.batch_paned.set_end_child(batch_ops_container)

        # Set default view to home
        self.view_stack.set_visible_child_name("home")

        self._update_bottom_bar()
    
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
        nav_section = Gio.Menu()
        nav_section.append("Home", "win.home")
        nav_section.append("Editor", "win.editor-view")
        menu.append_section(None, nav_section)
        app_section = Gio.Menu()
        app_section.append("Keyboard Shortcuts", "win.show-help-overlay")
        app_section.append("About Gsub", "win.about")
        menu.append_section(None, app_section)
        return menu

    def _create_editor_menu(self):
        """Create the primary menu for the editor view."""
        menu = Gio.Menu()
        
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
        video_section.append("Toggle Video Player", "win.toggle-video")
        video_section.append("Select Audio/Subtitle Tracks…", "win.select-tracks")
        menu.append_section(None, video_section)
        
        # Edit section
        edit_section = Gio.Menu()
        edit_section.append("Time Shift…", "win.time-shift")
        edit_section.append("ASS/SSA Info & Styles…", "win.ass-info-styles")
        edit_section.append("Bulk Apply Style…", "win.bulk-apply-style")
        edit_section.append("Sort by Time", "win.sort-by-time")
        menu.append_section(None, edit_section)
        
        # App section
        app_section = Gio.Menu()
        app_section.append("Keyboard Shortcuts", "win.show-help-overlay")
        app_section.append("About Gsub", "win.about")
        menu.append_section(None, app_section)
        
        return menu
    
    def _setup_actions(self):
        """Set up window actions."""
        # File actions
        self._create_action("new", self._on_new, ["<Ctrl>N"])
        self._create_action("open", self._on_open, ["<Ctrl>O"])
        self._create_action("save", self._on_save, ["<Ctrl>S"])
        self._create_action("save-as", self._on_save_as, ["<Ctrl><Shift>S"])
        self._create_action("convert-to-srt", self._on_convert_to_srt)
        self._create_action("convert-to-ass", self._on_convert_to_ass)
        
        # Video actions
        self._create_action("open-video", self._on_open_video, ["<Ctrl><Shift>O"])
        self._create_action("toggle-video", self._on_toggle_video, ["<Ctrl>V"])
        self._create_action("select-tracks", self._on_select_tracks, ["<Ctrl><Shift>T"])
        
        # Navigation actions
        self._create_action("home", self._on_home, ["<Alt>Home"])
        self._create_action("batch", self._on_batch)
        self._create_action("editor-view", self._on_editor_view)

        # Edit actions
        self._create_action("undo", self._on_undo, ["<Ctrl>Z"])
        self._create_action("redo", self._on_redo, ["<Ctrl><Shift>Z"])
        self._create_action("add-entry", self._on_add_entry, ["<Ctrl><Shift>N"])
        self._create_action("remove-entry", self._on_remove_entry, ["Delete"])
        self._create_action("duplicate-entry", self._on_duplicate_entry, ["<Ctrl>D"])
        self._create_action("move-up", self._on_move_up, ["<Ctrl>Up"])
        self._create_action("move-down", self._on_move_down, ["<Ctrl>Down"])
        self._create_action("time-shift", self._on_time_shift)
        self._create_action("ass-info-styles", self._on_ass_info_styles)
        self._create_action("bulk-apply-style", self._on_bulk_apply_style)
        self._create_action("sort-by-time", self._on_sort_by_time)
        
        # Help actions
        self._create_action("about", self._on_about)
        self._create_action("show-help-overlay", self._on_show_shortcuts, ["<Ctrl>question"])
    
    def _create_action(self, name: str, callback, shortcuts=None):
        """Create and register an action."""
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", callback)
        self.add_action(action)

        # Keep references so we can enable/disable format-specific actions.
        if not hasattr(self, '_actions'):
            self._actions = {}
        self._actions[name] = action
        
        if shortcuts:
            self.get_application().set_accels_for_action(f"win.{name}", shortcuts)
    
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
    
    def _update_status(self):
        """Update status bar."""
        if self.document:
            count = len(self.document.entries)
            format_name = self.document.format.value.upper()
            self.status_bar.set_text(f"{count} subtitles • {format_name} format")
        else:
            self.status_bar.set_text("No file loaded")
    
    def _update_undo_redo_buttons(self):
        """Update undo/redo button sensitivity."""
        self.undo_button.set_sensitive(self.command_manager.can_undo())
        self.redo_button.set_sensitive(self.command_manager.can_redo())

    def _update_format_actions(self):
        """Enable/disable ASS-only actions based on current document format."""
        fmt = self.document.format if self.document else None
        is_ass = fmt in (SubtitleFormat.ASS, SubtitleFormat.SSA)

        for name in ("ass-info-styles", "bulk-apply-style"):
            action = getattr(self, '_actions', {}).get(name)
            if action is not None:
                action.set_enabled(bool(is_ass))
    
    def _update_document_actions(self):
        """Enable/disable document-dependent actions."""
        has_doc = self.document is not None
        for name in ("save", "save-as", "convert-to-srt", "convert-to-ass",
                     "select-tracks", "time-shift", "sort-by-time",
                     "add-entry", "remove-entry", "duplicate-entry",
                     "move-up", "move-down", "undo", "redo"):
            action = self._actions.get(name)
            if action is not None:
                action.set_enabled(has_doc)

    def _get_config_dir(self):
        """Get the config directory path."""
        config_dir = os.path.join(GLib.get_user_config_dir(), "subtitle-editor")
        os.makedirs(config_dir, exist_ok=True)
        return config_dir

    def _load_config(self) -> dict:
        """Load the full config from the config file."""
        config_file = os.path.join(self._get_config_dir(), "config.json")
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

    def _on_close_request(self, window):
        """Save window state before closing."""
        config = self._load_config()
        config["last_directory"] = self.last_directory
        config["window_maximized"] = self.is_maximized()
        if not self.is_maximized():
            config["window_width"] = self.get_width()
            config["window_height"] = self.get_height()
        self._save_config(config)
        return False  # allow close

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

    def _navigate_to_home(self):
        """Switch to the home view."""
        self.current_view = "home"
        self.view_stack.set_visible_child_name("home")
        self.title_widget.set_title("Gsub")
        self.title_widget.set_subtitle("")
        self._update_header_bar()
        self._update_bottom_bar()

    def _navigate_to_editor(self, show_open=True):
        """Switch to the editor view.

        Args:
            show_open: If True, show the file open dialog (used when coming from home).
        """
        self.current_view = "editor"
        self.view_stack.set_visible_child_name("editor")
        self._update_header_bar()
        self._update_bottom_bar()
        self._update_title()
        self._update_status()
        # Only open file dialog when explicitly requested (from home screen or new file)
        if show_open and not self.document:
            self._on_open(None, None)

    def _navigate_to_batch(self):
        """Switch to the batch operations view."""
        self.current_view = "batch"
        self.view_stack.set_visible_child_name("batch")
        self.title_widget.set_title("Batch Operations")
        self.title_widget.set_subtitle("")
        self._update_header_bar()
        self._update_bottom_bar()

    def _update_header_bar(self):
        """Update the header bar buttons and menu based on current view."""
        self.header_start_stack.set_visible_child_name(self.current_view)
        if self.current_view == "home":
            self.menu_button.set_menu_model(self._create_home_menu())
        elif self.current_view == "batch":
            self.menu_button.set_menu_model(self._create_batch_menu())
        else:
            self.menu_button.set_menu_model(self._create_editor_menu())

    def _update_bottom_bar(self):
        """Update the bottom bar buttons based on current view."""
        # Clear existing action buttons
        while self.action_box.get_first_child():
            self.action_box.remove(self.action_box.get_first_child())

        if self.current_view == "editor":
            # Editor action buttons
            add_button = Gtk.Button()
            add_button.set_icon_name("list-add-symbolic")
            add_button.set_tooltip_text("Add Subtitle (Ctrl+Shift+N)")
            add_button.set_action_name("win.add-entry")
            self.action_box.append(add_button)

            remove_button = Gtk.Button()
            remove_button.set_icon_name("list-remove-symbolic")
            remove_button.set_tooltip_text("Remove Subtitle (Delete)")
            remove_button.set_action_name("win.remove-entry")
            self.action_box.append(remove_button)

            duplicate_button = Gtk.Button()
            duplicate_button.set_icon_name("edit-copy-symbolic")
            duplicate_button.set_tooltip_text("Duplicate Subtitle (Ctrl+D)")
            duplicate_button.set_action_name("win.duplicate-entry")
            self.action_box.append(duplicate_button)

            self._update_status()
        elif self.current_view == "batch":
            self._update_batch_status()
        else:
            # Home view - just status
            self.status_bar.set_text("")

    def open_file(self, gfile: Gio.File):
        """Open a subtitle file."""
        try:
            success, contents, _ = gfile.load_contents(None)
            if not success:
                self._show_error("Failed to load file")
                return
            
            content = contents.decode('utf-8')
            file_path = gfile.get_path()
            
            # Detect format by extension
            ext = os.path.splitext(file_path)[1].lower()
            
            if ext == '.srt':
                self.document = SRTParser.parse(content)
            elif ext in ['.ass', '.ssa']:
                self.document = ASSParser.parse(content)
            else:
                self._show_error("Unsupported file format")
                return
            
            self.document.file_path = file_path
            self.current_file = file_path
            self.command_manager.clear()
            
            # Update UI
            self.subtitle_list.set_document(self.document)
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
            self._show_toast(f"Opened {os.path.basename(file_path)}")
            self._navigate_to_editor(show_open=False)

        except Exception as e:
            self._show_error(f"Error opening file: {str(e)}")
    
    def _save_document(self, file_path: str):
        """Save the current document to a file."""
        try:
            if not self.document:
                return
            
            # Serialize based on format
            if self.document.format == SubtitleFormat.SRT:
                content = SRTParser.serialize(self.document)
            else:  # ASS or SSA
                content = ASSParser.serialize(self.document)
            
            # Write to file
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            self.document.modified = False
            self.document.file_path = file_path
            self.current_file = file_path
            self._hide_banner()
            self._update_title()
            self._save_last_directory(os.path.dirname(file_path))
            self._show_toast(f"Saved {os.path.basename(file_path)}")
            
        except Exception as e:
            self._show_error(f"Error saving file: {str(e)}")
    
    def _show_error(self, message: str):
        """Show an error dialog."""
        dialog = Adw.MessageDialog.new(self, message, "")
        dialog.add_response("ok", "OK")
        dialog.set_default_response("ok")
        dialog.present()
    
    # Action callbacks
    
    def _on_new(self, action, param):
        """Create a new subtitle document."""
        if self.document and self.document.modified:
            dialog = Adw.MessageDialog.new(
                self,
                "Unsaved Changes",
                "The current document has unsaved changes. Save before creating a new document?"
            )
            dialog.add_response("save", "Save")
            dialog.add_response("discard", "Discard")
            dialog.add_response("cancel", "Cancel")
            dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
            dialog.set_default_response("save")
            dialog.set_close_response("cancel")
            dialog.connect("response", self._on_new_response)
            dialog.present()
            return
        
        self._create_new_document()
    
    def _on_new_response(self, dialog, response):
        """Handle response to new document save prompt."""
        if response == "save":
            if self.current_file:
                self._save_document(self.current_file)
            else:
                self._on_save_as(None, None)
            self._create_new_document()
        elif response == "discard":
            self._create_new_document()
    
    def _create_new_document(self):
        """Actually create a new document (called after save prompt check)."""
        self.document = SubtitleDocument(format=SubtitleFormat.SRT)
        self.current_file = None
        self.command_manager.clear()
        self.subtitle_list.set_document(self.document)
        style_names = [s.name for s in (self.document.styles or [])] if self.document else []
        self.editor_panel.set_document_context(self.document.format, style_names)
        self.editor_panel.clear()
        self._update_title()
        self._update_status()
        self._update_format_actions()
        self._update_document_actions()
        self._hide_banner()
        self._navigate_to_editor(show_open=False)
    
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
        except Exception as e:
            pass  # User cancelled
    
    def _on_save(self, action, param):
        """Save the current document."""
        if not self.document:
            return
        
        if self.current_file:
            self._save_document(self.current_file)
        else:
            self._on_save_as(action, param)
    
    def _on_save_as(self, action, param):
        """Show save as dialog with format selection."""
        if not self.document:
            return
        
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
        dialog.save(self, None, self._on_save_as_response)
    
    def _on_save_as_response(self, dialog, result):
        """Handle save as dialog response."""
        try:
            file = dialog.save_finish(result)
            if file:
                file_path = file.get_path()
                
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
                if target_format and target_format != self.document.format:
                    from subtitle_editor.converters import FormatConverter
                    self.document = FormatConverter.convert(self.document, target_format)
                    self.subtitle_list.set_document(self.document)
                    style_names = [s.name for s in (self.document.styles or [])] if self.document else []
                    self.editor_panel.set_document_context(self.document.format, style_names)
                    self._update_format_actions()
                    self._show_toast(f"Converted to {target_format.value.upper()}")
                
                self._save_document(file_path)
        except Exception as e:
            pass  # User cancelled
    
    def _on_undo(self, action, param):
        """Undo the last action."""
        if self.command_manager.undo():
            self.subtitle_list.refresh(preserve_selection=True)
            self._update_editor_after_change()
            self._update_title()
            self._update_status()
            self._update_undo_redo_buttons()
    
    def _on_redo(self, action, param):
        """Redo the last undone action."""
        if self.command_manager.redo():
            self.subtitle_list.refresh(preserve_selection=True)
            self._update_editor_after_change()
            self._update_title()
            self._update_status()
            self._update_undo_redo_buttons()
    
    def _update_editor_after_change(self):
        """Update the editor panel after undo/redo or other changes."""
        selected_pos = self.subtitle_list.get_selected_position()
        if selected_pos >= 0 and selected_pos < len(self.document.entries):
            entry = self.document.entries[selected_pos]
            self.editor_panel.set_entry(entry, selected_pos)
        else:
            self.editor_panel.clear()
    
    def _on_add_entry(self, action, param):
        """Add a new subtitle entry."""
        if not self.document:
            self._on_new(action, param)
            return
        
        from subtitle_editor.commands import AddEntryCommand
        from subtitle_editor.models import SubtitleEntry, TimeCode
        
        # Create new entry with default values
        last_time_ms = 0
        if self.document.entries:
            last_time_ms = self.document.entries[-1].end_time.total_milliseconds + 1000
        
        entry = SubtitleEntry(
            index=len(self.document.entries) + 1,
            start_time=TimeCode.from_milliseconds(last_time_ms),
            end_time=TimeCode.from_milliseconds(last_time_ms + 2000),
            text="New subtitle"
        )
        
        cmd = AddEntryCommand(self.document, entry)
        self.command_manager.execute(cmd)
        
        self.subtitle_list.refresh()
        self.subtitle_list.select_entry(len(self.document.entries) - 1)
        self._update_title()
        self._update_status()
        self._update_undo_redo_buttons()
        self._show_toast("Subtitle added")
    
    def _on_remove_entry(self, action, param):
        """Remove the selected subtitle entries."""
        if not self.document:
            return
        
        positions = self.subtitle_list.get_selected_positions()
        if not positions:
            return
        
        from subtitle_editor.commands import RemoveEntryCommand
        
        # Remove in reverse order to maintain indices
        positions_sorted = sorted(positions, reverse=True)
        
        for position in positions_sorted:
            cmd = RemoveEntryCommand(self.document, position)
            self.command_manager.execute(cmd)
        
        self.subtitle_list.refresh()
        self.editor_panel.clear()
        self._update_title()
        self._update_status()
        self._update_undo_redo_buttons()
        
        count = len(positions)
        self._show_toast(f"{count} subtitle{'s' if count > 1 else ''} removed")
    
    def _on_duplicate_entry(self, action, param):
        """Duplicate the selected subtitle entries."""
        if not self.document:
            return
        
        positions = self.subtitle_list.get_selected_positions()
        if not positions:
            return
        
        from subtitle_editor.commands import DuplicateEntryCommand
        
        # Duplicate in order, adjusting positions as we go
        positions_sorted = sorted(positions)
        offset = 0
        
        for position in positions_sorted:
            cmd = DuplicateEntryCommand(self.document, position + offset)
            self.command_manager.execute(cmd)
            offset += 1
        
        self.subtitle_list.refresh()
        # Select the last duplicated entry
        if positions_sorted:
            self.subtitle_list.select_entry(positions_sorted[-1] + offset)
        self._update_title()
        self._update_status()
        self._update_undo_redo_buttons()
        
        count = len(positions)
        self._show_toast(f"{count} subtitle{'s' if count > 1 else ''} duplicated")
    
    def _on_move_up(self, action, param):
        """Move the selected entry up."""
        if not self.document:
            return
        
        position = self.subtitle_list.get_selected_position()
        if position > 0:
            from subtitle_editor.commands import MoveEntryCommand
            
            cmd = MoveEntryCommand(self.document, position, position - 1)
            self.command_manager.execute(cmd)
            
            self.subtitle_list.refresh()
            self.subtitle_list.select_entry(position - 1)
            self._update_title()
    
    def _on_move_down(self, action, param):
        """Move the selected entry down."""
        if not self.document:
            return
        
        position = self.subtitle_list.get_selected_position()
        if position >= 0 and position < len(self.document.entries) - 1:
            from subtitle_editor.commands import MoveEntryCommand
            
            cmd = MoveEntryCommand(self.document, position, position + 1)
            self.command_manager.execute(cmd)
            
            self.subtitle_list.refresh()
            self.subtitle_list.select_entry(position + 1)
            self._update_title()
    
    def _on_time_shift(self, action, param):
        """Show time shift dialog."""
        if not self.document or not self.document.entries:
            return
        
        dialog = TimeShiftDialog(self)
        dialog.present()

    def _on_ass_info_styles(self, action, param):
        """Show ASS/SSA info & styles dialog."""
        if not self.document:
            return
        if self.document.format not in (SubtitleFormat.ASS, SubtitleFormat.SSA):
            self._show_toast("This is only available for ASS/SSA files")
            return

        dialog = ASSInfoStylesDialog(self)
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
    
    def _on_sort_by_time(self, action, param):
        """Sort subtitles by start time."""
        if self.document:
            from subtitle_editor.commands import SortByTimeCommand
            cmd = SortByTimeCommand(self.document)
            self.command_manager.execute(cmd)
            self.subtitle_list.refresh(preserve_selection=True)
            self._update_title()
            self._update_undo_redo_buttons()
            self._show_toast("Subtitles sorted by time")
    
    # --- Batch operation handlers ---

    def _on_batch_selection_changed(self, widget):
        """Handle batch file selection changes."""
        self._update_batch_action_buttons()

    def _on_batch_files_changed(self, widget):
        """Handle batch file list changes."""
        self._update_batch_action_buttons()

    def _on_batch_ops_changed(self, widget):
        """Handle batch operations changes."""
        self._update_batch_action_buttons()

    def _update_batch_action_buttons(self):
        """Enable/disable batch action buttons based on state."""
        has_files = self.batch_file_list.file_count > 0
        has_selected = len(self.batch_file_list.get_selected_files()) > 0
        has_ops = self.batch_operations.has_any_operation()

        self.batch_apply_btn.set_sensitive(has_selected and has_ops)
        self.batch_save_btn.set_sensitive(has_selected)
        self.batch_save_as_btn.set_sensitive(has_selected)

    def _update_batch_status(self):
        """Update the status bar for batch view."""
        total = self.batch_file_list.file_count
        selected = len(self.batch_file_list.get_selected_files())
        if total == 0:
            self.status_bar.set_text("No files loaded. Click 'Add Files…' to begin.")
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

            for gfile in files:
                file_path = gfile.get_path()
                try:
                    success, contents, _ = gfile.load_contents(None)
                    if not success:
                        continue

                    content = contents.decode('utf-8')
                    ext = os.path.splitext(file_path)[1].lower()

                    # Parse based on format
                    if ext == '.srt':
                        doc = SRTParser.parse(content)
                    elif ext in ['.ass', '.ssa']:
                        doc = ASSParser.parse(content)
                    else:
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

                except Exception as e:
                    self._show_toast(f"Error loading {os.path.basename(file_path)}: {str(e)}")

            self._update_batch_status()
            self._update_batch_action_buttons()

        except Exception as e:
            pass  # User cancelled

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

        modified_count = 0
        for item in selected_files:
            doc = item.document
            changed = False

            # Apply time shift
            if self.batch_operations.has_time_shift():
                offset = int(self.batch_operations.offset_row.get_value())
                for entry in doc.entries:
                    entry.shift_time(offset)
                changed = True

            # Apply font size change (ASS/SSA only)
            if self.batch_operations.has_font_size_change() and doc.format in (SubtitleFormat.ASS, SubtitleFormat.SSA):
                new_size = int(self.batch_operations.font_size_row.get_value())
                for style in doc.styles:
                    style.fontsize = new_size
                changed = True

            # Apply resolution change (ASS/SSA only)
            if self.batch_operations.has_resolution_change() and doc.format in (SubtitleFormat.ASS, SubtitleFormat.SSA):
                new_w = str(int(self.batch_operations.res_width_row.get_value()))
                new_h = str(int(self.batch_operations.res_height_row.get_value()))
                doc.metadata["PlayResX"] = new_w
                doc.metadata["PlayResY"] = new_h
                changed = True

            if changed:
                doc.modified = True
                item.modified = True
                modified_count += 1

        self.batch_file_list.update_ui()
        self._update_batch_status()

        if modified_count > 0:
            self._show_toast(f"Applied changes to {modified_count} file{'s' if modified_count != 1 else ''}")
            self._update_batch_action_buttons()

    def _on_batch_save_all(self):
        """Save all selected batch files in-place."""
        selected = self.batch_file_list.get_selected_files()
        if not selected:
            return

        saved = 0
        skipped = 0
        for item in selected:
            try:
                if item.document.format == SubtitleFormat.SRT:
                    content = SRTParser.serialize(item.document)
                else:
                    content = ASSParser.serialize(item.document)

                with open(item.file_path, 'w', encoding='utf-8') as f:
                    f.write(content)

                item.document.modified = False
                item.modified = False
                saved += 1
            except Exception as e:
                self._show_toast(f"Error saving {item.filename}: {str(e)}")
                skipped += 1

        if saved > 0:
            self._show_toast(f"Saved {saved} file{'s' if saved != 1 else ''}")
        self._update_batch_status()

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
            saved = 0
            for item in selected_files:
                try:
                    dest_path = os.path.join(output_dir, item.filename)

                    if item.document.format == SubtitleFormat.SRT:
                        content = SRTParser.serialize(item.document)
                    else:
                        content = ASSParser.serialize(item.document)

                    with open(dest_path, 'w', encoding='utf-8') as f:
                        f.write(content)

                    item.document.modified = False
                    item.modified = False
                    saved += 1
                except Exception as e:
                    self._show_toast(f"Error saving {item.filename}: {str(e)}")

            if saved > 0:
                self._show_toast(f"Saved {saved} file{'s' if saved != 1 else ''} to {output_dir}")
            self._update_batch_status()

        except Exception as e:
            pass  # User cancelled

    def _on_about(self, action, param):
        """Show about dialog."""
        about = Adw.AboutWindow(
            transient_for=self,
            application_name="Gsub",
            application_icon="app.gsub",
            developer_name="Gsub Contributors",
            version="0.2.0",
            license_type=Gtk.License.GPL_3_0,
            developers=["Gsub Contributors"],
            comments="A modern subtitle editor"
        )
        about.present()
    
    def _on_show_shortcuts(self, action, param):
        """Show keyboard shortcuts dialog."""
        shortcuts = build_shortcuts_dialog()
        shortcuts.present(self)
    
    def _on_home(self, action, param):
        """Navigate to home view."""
        self._navigate_to_home()

    def _on_editor_view(self, action, param):
        """Navigate to editor view."""
        self._navigate_to_editor()

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
            from subtitle_editor.converters import FormatConverter

            old_format = self.document.format.value.upper()
            self.document = FormatConverter.convert(self.document, target_format)

            # Update UI
            self.subtitle_list.set_document(self.document)
            style_names = [s.name for s in (self.document.styles or [])] if self.document else []
            self.editor_panel.set_document_context(self.document.format, style_names)
            self._update_format_actions()
            self._update_title()
            self._update_status()
            
            # Update video player document if available
            if self.video_player:
                self.video_player.set_document(self.document)
            
            self._show_toast(f"Converted from {old_format} to {target_format.value.upper()}")
            
            # Suggest saving
            if self.current_file:
                self._show_banner(
                    "Format converted. Save to preserve changes.",
                    "Save As",
                    lambda: self._on_save_as(None, None)
                )
    
    # Widget signal handlers
    
    def _on_entry_selected(self, widget, position):
        """Handle subtitle entry selection."""
        if not self.document:
            return
        if len(self.subtitle_list.get_selected_positions()) > 1:
            self.editor_panel.clear()
            self.editor_panel.set_sensitive(False)
            return
        if 0 <= position < len(self.document.entries):
            entry = self.document.entries[position]
            self.editor_panel.set_entry(entry, position)
    
    def _on_entry_activated(self, widget, position):
        """Handle subtitle entry activation (double-click)."""
        # Focus the text editor
        self.editor_panel.focus_text()
    
    def _on_text_changed(self, widget, position, new_text):
        """Handle text change in editor panel."""
        if not self.document or position < 0:
            return
        
        from subtitle_editor.commands import EditTextCommand
        
        cmd = EditTextCommand(self.document, position, new_text)
        self.command_manager.execute(cmd)
        
        self.subtitle_list.refresh_entry(position)
        self._update_title()
        self._update_undo_redo_buttons()
    
    def _on_timing_changed(self, widget, position, start_time, end_time):
        """Handle timing change in editor panel."""
        if not self.document or position < 0:
            return
        
        from subtitle_editor.commands import EditTimingCommand
        
        cmd = EditTimingCommand(self.document, position, start_time, end_time)
        self.command_manager.execute(cmd)
        
        self.subtitle_list.refresh_entry(position)
        self._update_title()
        self._update_undo_redo_buttons()

    def _on_style_changed(self, widget, position, new_style):
        """Handle style change in editor panel (ASS/SSA only)."""
        if not self.document or position < 0:
            return
        if self.document.format not in (SubtitleFormat.ASS, SubtitleFormat.SSA):
            return

        from subtitle_editor.commands import EditStyleCommand

        cmd = EditStyleCommand(self.document, position, new_style)
        self.command_manager.execute(cmd)

        self.subtitle_list.refresh_entry(position)
        self._update_title()
        self._update_undo_redo_buttons()

    def _on_position_changed(self, widget, position, margin_l, margin_r, margin_v):
        """Handle position (margin) change in editor panel (ASS/SSA only)."""
        if not self.document or position < 0:
            return
        if self.document.format not in (SubtitleFormat.ASS, SubtitleFormat.SSA):
            return
        
        from subtitle_editor.commands import EditMarginsCommand
        
        cmd = EditMarginsCommand(self.document, position, margin_l, margin_r, margin_v)
        self.command_manager.execute(cmd)
        
        # Update video player to reflect position changes
        if self.video_player:
            self.video_player.queue_subtitle_redraw()
        
        self._update_title()
        self._update_undo_redo_buttons()
    
    # Video player handlers
    
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
                self.current_video_file = file_path
                
                # Reset extraction dialog flag for new video
                self._extraction_dialog_shown = False
                
                self.video_player.load_video(file_path)
                
                # Show video player if hidden
                if not self.video_visible:
                    self.video_visible = True
                    self.video_container.set_visible(True)
                    self.video_button.set_active(True)
                    # Expand the paned to show video player
                    self.right_paned.set_position(300)
                
                self._save_last_directory(os.path.dirname(file_path))
                self._show_toast(f"Loaded video: {os.path.basename(file_path)}")
                
                # Check for embedded tracks after a delay to allow detection to complete
                # Use a longer delay and check if tracks are actually detected
                GLib.timeout_add(1500, self._check_and_show_track_selection)
                GLib.timeout_add(2500, self._check_and_show_track_selection)  # Retry once more if needed
        except Exception as e:
            pass  # User cancelled
    
    def _on_video_load_extract_response(self, dialog, response):
        """Handle video load extraction dialog response."""
        dialog.close()
        if response == "extract":
            self._show_subtitle_extraction_dialog()
        elif response == "select":
            self._show_track_selection_dialog()

    def _check_and_show_track_selection(self):
        """Check for embedded tracks and show selection dialog if available."""
        has_audio, has_subtitles = self.video_player.has_embedded_tracks()
        
        logger.info(f"has_audio={has_audio}, has_subtitles={has_subtitles}")
        
        # Prevent showing dialog multiple times
        if hasattr(self, '_extraction_dialog_shown') and self._extraction_dialog_shown:
            return False
        
        # If video has audio or subtitle tracks, show unified selection dialog
        if has_audio or has_subtitles:
            self._extraction_dialog_shown = True
            audio_tracks, subtitle_tracks = self.video_player.get_available_tracks()
            
            # Create dialog asking what to do with embedded subtitles
            extract_dialog = Adw.MessageDialog.new(
                self,
                "Video Contains Subtitle Tracks",
                f"This video has {len(subtitle_tracks)} embedded subtitle track(s). What would you like to do?"
            )
            extract_dialog.add_response("play", "Just Play Video")
            extract_dialog.add_response("extract", "Extract & Edit Subtitles")
            if len(audio_tracks) > 1:
                extract_dialog.add_response("select", "Select Tracks")
            
            extract_dialog.set_response_appearance("extract", Adw.ResponseAppearance.SUGGESTED)
            extract_dialog.set_default_response("extract")
            extract_dialog.set_close_response("play")
            
            extract_dialog.connect("response", self._on_video_load_extract_response)
            extract_dialog.present()
        elif has_audio and len(self.video_player.get_available_tracks()[0]) > 1:
            # Multiple audio tracks but no subtitles - show track selection
            self._show_track_selection_dialog()
        else:
            logger.debug("No tracks to select, skipping dialog")
        
        return False  # Stop timeout
    
    def _show_track_selection_dialog(self):
        """Show the track selection dialog."""
        audio_tracks, subtitle_tracks = self.video_player.get_available_tracks()
        
        from subtitle_editor.widgets.dialogs import TrackSelectionDialog
        
        track_dialog = TrackSelectionDialog(
            self,
            audio_tracks,
            subtitle_tracks,
            self.video_player.current_audio_track,
            self.video_player.current_subtitle_track
        )
        track_dialog.connect("tracks-selected", self._on_tracks_selected)
        track_dialog.present()
    
    def _show_subtitle_extraction_dialog(self):
        """Show dialog to select which subtitle track to extract and optionally change audio."""
        audio_tracks, subtitle_tracks = self.video_player.get_available_tracks()
        
        if not subtitle_tracks:
            self._show_toast("No subtitle tracks found")
            return
        
        # Show full track selection dialog with audio tracks included
        from subtitle_editor.widgets.dialogs import TrackSelectionDialog
        
        track_dialog = TrackSelectionDialog(
            self,
            audio_tracks,  # Include audio tracks
            subtitle_tracks,
            self.video_player.current_audio_track,
            -1   # No subtitle pre-selected (user must choose which to extract)
        )
        track_dialog.connect("tracks-selected", self._on_extract_track_selected)
        track_dialog.present()
    
    def _on_toggle_video(self, action, param):
        """Toggle video player visibility."""
        self.video_button.set_active(not self.video_button.get_active())
    
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
        
        # Get track information
        audio_tracks, subtitle_tracks = self.video_player.get_available_tracks()
        
        # Show track selection dialog
        from subtitle_editor.widgets.dialogs import TrackSelectionDialog
        
        track_dialog = TrackSelectionDialog(
            self,
            audio_tracks,
            subtitle_tracks,
            self.video_player.current_audio_track,
            self.video_player.current_subtitle_track
        )
        track_dialog.connect("tracks-selected", self._on_tracks_selected)
        track_dialog.present()
    
    def _on_tracks_selected(self, dialog, audio_track, subtitle_track):
        """Handle track selection from dialog."""
        # Close the track selection dialog first
        dialog.close()
        
        # Set audio track (can be changed independently)
        if audio_track >= 0:
            self.video_player.set_audio_track(audio_track)
            self._show_toast(f"Audio track {audio_track + 1} selected")
        
        # Set subtitle track
        if subtitle_track >= 0:
            self.video_player.set_subtitle_track(subtitle_track)
            
            # Ask user if they want to extract and edit the subtitle track
            audio_tracks, subtitle_tracks = self.video_player.get_available_tracks()
            track_info = subtitle_tracks[subtitle_track] if subtitle_track < len(subtitle_tracks) else {}
            track_name = track_info.get('title', f"Track {subtitle_track + 1}")
            
            extract_dialog = Adw.MessageDialog.new(
                self,
                "Extract Subtitle Track?",
                f"Do you want to extract '{track_name}' for editing, or just view it?"
            )
            extract_dialog.add_response("view", "View Only")
            extract_dialog.add_response("extract", "Extract & Edit")
            extract_dialog.set_response_appearance("extract", Adw.ResponseAppearance.SUGGESTED)
            extract_dialog.set_default_response("extract")
            extract_dialog.set_close_response("view")
            
            extract_dialog.connect("response", self._on_extract_response, subtitle_track)
            extract_dialog.present()
        elif subtitle_track == -1:
            # Disable embedded subtitles
            self.video_player.set_subtitle_track(-1)
            self._show_toast("Using external subtitles")
    
    def _on_extract_track_selected(self, dialog, audio_track, subtitle_track):
        """Handle track selection for extraction."""
        # Apply audio track selection first (independent of subtitle extraction)
        if audio_track >= 0:
            self.video_player.set_audio_track(audio_track)
        
        # Then handle subtitle extraction if a track is selected
        if subtitle_track >= 0:
            self._extract_and_load_subtitle(subtitle_track)
        
        dialog.close()
    
    def _extract_and_load_subtitle(self, track_index):
        """Extract a subtitle track and load it for editing."""
        # Get track info
        audio_tracks, subtitle_tracks = self.video_player.get_available_tracks()
        
        if track_index >= len(subtitle_tracks):
            self._show_toast("Invalid track index")
            return
        
        track_info = subtitle_tracks[track_index]
        track_name = track_info.get('title') or f"Track {track_index + 1}"
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

                # IMPORTANT: Disable embedded subtitle track before loading external file
                # This prevents double subtitles (embedded + external)
                self.video_player.set_subtitle_track(-1)

                # Load the extracted subtitle file
                try:
                    gfile = Gio.File.new_for_path(temp_path)
                    self.open_file(gfile)
                    # Escape ampersands for markup
                    safe_track_name = track_name.replace('&', '&amp;')
                    self._show_toast(f"Loaded extracted subtitles: {safe_track_name}")

                    # Optionally clean up temp file after loading
                    # (for now, keep it as it becomes the working file)
                except Exception as e:
                    self._show_toast(f"Error loading extracted subtitles: {e}")
                    try:
                        os.remove(temp_path)
                    except OSError:
                        pass
            else:
                self._show_toast(f"Extraction failed: {error_msg}")
                try:
                    os.remove(temp_path)
                except:
                    pass

        # Start extraction
        self.video_player.extract_subtitle_track(track_index, temp_path, on_extract_complete)
    
    def _on_extract_response(self, dialog, response, subtitle_track):
        """Handle subtitle extraction response (from manual track selection)."""
        if response == "extract":
            self._extract_and_load_subtitle(subtitle_track)
        # else: view only - embedded subtitles remain enabled in video player
    
    def _clean_subtitle_html(self, subtitle_path):
        r"""Remove HTML/font tags and fix ASS format issues from subtitle file.
        
        Many subtitle tracks contain HTML formatting tags like <font>, <b>, <i>
        which cause issues when displayed in Gtk labels expecting Pango markup.
        This function strips those tags while preserving the text content.
        
        Also handles ASS format conversion issues where newlines are represented
        as literal \N strings instead of actual newlines.
        """
        import re
        
        try:
            with open(subtitle_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
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
