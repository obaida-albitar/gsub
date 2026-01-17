"""
Main application window for the subtitle editor.

Following GNOME HIG, uses libadwaita widgets for a modern, native look.
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, Gio, GLib
import os

from subtitle_editor.models import SubtitleDocument, SubtitleFormat
from subtitle_editor.parsers import SRTParser, ASSParser
from subtitle_editor.commands import CommandManager
from subtitle_editor.widgets.subtitle_list import SubtitleListView
from subtitle_editor.widgets.editor_panel import EditorPanel
from subtitle_editor.widgets.dialogs import TimeShiftDialog, BulkApplyStyleDialog, ASSInfoStylesDialog
from subtitle_editor.widgets.video_player import VideoPlayerWidget


class SubtitleEditorWindow(Adw.ApplicationWindow):
    """Main application window."""
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        
        # Application state
        self.document: SubtitleDocument = None
        self.command_manager = CommandManager()
        self.current_file = None
        self.current_video_file = None
        self.video_visible = False
        
        # Set up window properties
        self.set_default_size(1200, 800)
        self.set_title("Subtitle Editor")
        
        # Build UI
        self._build_ui()
        self._setup_actions()
        self._update_title()
        self._update_format_actions()
    
    def _build_ui(self):
        """Construct the user interface."""
        # Use Adw.ToolbarView for modern GNOME layout
        toolbar_view = Adw.ToolbarView()
        self.set_content(toolbar_view)
        
        # Toast overlay for user feedback
        self.toast_overlay = Adw.ToastOverlay()
        toolbar_view.set_content(self.toast_overlay)
        
        # Banner for important notifications (initially hidden)
        self.banner = Adw.Banner()
        self.banner.set_revealed(False)
        toolbar_view.add_top_bar(self.banner)
        
        # Header bar
        self.header_bar = Adw.HeaderBar()
        toolbar_view.add_top_bar(self.header_bar)
        
        # Primary menu button
        menu_button = Gtk.MenuButton()
        menu_button.set_icon_name("open-menu-symbolic")
        menu_button.set_menu_model(self._create_primary_menu())
        menu_button.set_tooltip_text("Main Menu")
        self.header_bar.pack_end(menu_button)
        
        # Document title - centered
        self.title_widget = Adw.WindowTitle()
        self.title_widget.set_title("Subtitle Editor")
        self.header_bar.set_title_widget(self.title_widget)
        
        # Open/Save button group (start side)
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
        
        self.header_bar.pack_start(file_box)
        
        # Undo/Redo buttons
        undo_redo_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        undo_redo_box.add_css_class("linked")
        
        self.undo_button = Gtk.Button()
        self.undo_button.set_icon_name("edit-undo-symbolic")
        self.undo_button.set_tooltip_text("Undo (Ctrl+Z)")
        self.undo_button.set_action_name("win.undo")
        self.undo_button.set_sensitive(False)
        undo_redo_box.append(self.undo_button)
        
        self.redo_button = Gtk.Button()
        self.redo_button.set_icon_name("edit-redo-symbolic")
        self.redo_button.set_tooltip_text("Redo (Ctrl+Shift+Z)")
        self.redo_button.set_action_name("win.redo")
        self.redo_button.set_sensitive(False)
        undo_redo_box.append(self.redo_button)
        
        self.header_bar.pack_start(undo_redo_box)
        
        # Video button (toggle video player)
        self.video_button = Gtk.ToggleButton()
        self.video_button.set_icon_name("video-display-symbolic")
        self.video_button.set_tooltip_text("Toggle Video Player (Ctrl+V)")
        self.video_button.connect('toggled', self._on_video_toggle)
        self.header_bar.pack_start(self.video_button)
        
        # Main content - use Adw.ViewStack for potential future views
        self.view_stack = Adw.ViewStack()
        self.toast_overlay.set_child(self.view_stack)
        
        # Main editing view
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        main_page = self.view_stack.add_titled(main_box, "main", "Editor")
        
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
        self.video_player.connect('position-changed', self._on_video_position_changed)
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
        
        # Bottom bar with status and actions
        bottom_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        bottom_bar.set_margin_start(12)
        bottom_bar.set_margin_end(12)
        bottom_bar.set_margin_top(6)
        bottom_bar.set_margin_bottom(6)
        toolbar_view.add_bottom_bar(bottom_bar)
        
        # Status label
        self.status_bar = Gtk.Label()
        self.status_bar.set_halign(Gtk.Align.START)
        self.status_bar.set_hexpand(True)
        self.status_bar.add_css_class("dim-label")
        bottom_bar.append(self.status_bar)
        
        # Action buttons in bottom bar
        action_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        
        add_button = Gtk.Button()
        add_button.set_icon_name("list-add-symbolic")
        add_button.set_tooltip_text("Add Subtitle (Ctrl+N)")
        add_button.set_action_name("win.add-entry")
        action_box.append(add_button)
        
        remove_button = Gtk.Button()
        remove_button.set_icon_name("list-remove-symbolic")
        remove_button.set_tooltip_text("Remove Subtitle (Delete)")
        remove_button.set_action_name("win.remove-entry")
        action_box.append(remove_button)
        
        duplicate_button = Gtk.Button()
        duplicate_button.set_icon_name("edit-copy-symbolic")
        duplicate_button.set_tooltip_text("Duplicate Subtitle (Ctrl+D)")
        duplicate_button.set_action_name("win.duplicate-entry")
        action_box.append(duplicate_button)
        
        bottom_bar.append(action_box)
        
        self._update_status()
    
    def _create_primary_menu(self):
        """Create the primary menu."""
        menu = Gio.Menu()
        
        # File section
        file_section = Gio.Menu()
        file_section.append("New", "win.new")
        file_section.append("Open…", "win.open")
        file_section.append("Save As…", "win.save-as")
        menu.append_section(None, file_section)
        
        # Video section
        video_section = Gio.Menu()
        video_section.append("Open Video…", "win.open-video")
        video_section.append("Toggle Video Player", "win.toggle-video")
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
        app_section.append("About Subtitle Editor", "win.about")
        menu.append_section(None, app_section)
        
        return menu
    
    def _setup_actions(self):
        """Set up window actions."""
        # File actions
        self._create_action("new", self._on_new, ["<Ctrl>N"])
        self._create_action("open", self._on_open, ["<Ctrl>O"])
        self._create_action("save", self._on_save, ["<Ctrl>S"])
        self._create_action("save-as", self._on_save_as, ["<Ctrl><Shift>S"])
        
        # Video actions
        self._create_action("open-video", self._on_open_video, ["<Ctrl><Shift>O"])
        self._create_action("toggle-video", self._on_toggle_video, ["<Ctrl>V"])
        
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
            self.title_widget.set_title("Subtitle Editor")
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
    
    def _show_toast(self, message: str):
        """Show a toast notification."""
        toast = Adw.Toast.new(message)
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
            
            # Update video player with subtitle document
            if self.video_player:
                self.video_player.set_document(self.document)
            
            self._show_toast(f"Opened {os.path.basename(file_path)}")
            
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
            self._update_title()
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
        # TODO: Prompt to save if modified
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
        
        dialog.open(self, None, self._on_open_response)
    
    def _on_open_response(self, dialog, result):
        """Handle file open dialog response."""
        try:
            file = dialog.open_finish(result)
            if file:
                self.open_file(file)
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
        """Show save as dialog."""
        if not self.document:
            return
        
        dialog = Gtk.FileDialog()
        dialog.set_title("Save Subtitle File")
        
        # Set initial name
        if self.current_file:
            dialog.set_initial_name(os.path.basename(self.current_file))
        else:
            ext = ".srt" if self.document.format == SubtitleFormat.SRT else ".ass"
            dialog.set_initial_name(f"untitled{ext}")
        
        dialog.save(self, None, self._on_save_as_response)
    
    def _on_save_as_response(self, dialog, result):
        """Handle save as dialog response."""
        try:
            file = dialog.save_finish(result)
            if file:
                self._save_document(file.get_path())
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
            self.document.sort_by_time()
            self.subtitle_list.refresh(preserve_selection=True)
            self._update_title()
            self._show_toast("Subtitles sorted by time")
    
    def _on_about(self, action, param):
        """Show about dialog."""
        about = Adw.AboutWindow(
            transient_for=self,
            application_name="Subtitle Editor",
            application_icon="accessories-text-editor-symbolic",
            developer_name="GNOME Community",
            version="1.0.0",
            website="https://gitlab.gnome.org/",
            issue_url="https://gitlab.gnome.org/",
            license_type=Gtk.License.GPL_3_0,
            developers=["GNOME Subtitle Editor Contributors"],
            comments="A modern subtitle editor for GNOME"
        )
        about.present()
    
    def _on_show_shortcuts(self, action, param):
        """Show keyboard shortcuts window."""
        builder = Gtk.Builder()
        builder.add_from_string(SHORTCUTS_UI)
        shortcuts = builder.get_object("shortcuts")
        shortcuts.set_transient_for(self)
        shortcuts.present()
    
    # Widget signal handlers
    
    def _on_entry_selected(self, widget, position):
        """Handle subtitle entry selection."""
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
        
        # Update the entry directly (this is a simple property change, not undoable)
        entry = self.document.entries[position]
        entry.margin_l = margin_l
        entry.margin_r = margin_r
        entry.margin_v = margin_v
        self.document.modified = True
        
        # Update video player to reflect position changes
        if self.video_player:
            self.video_player.subtitle_drawing_area.queue_draw()
        
        self._update_title()
    
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
        
        dialog.open(self, None, self._on_open_video_response)
    
    def _on_open_video_response(self, dialog, result):
        """Handle video file open dialog response."""
        try:
            file = dialog.open_finish(result)
            if file:
                file_path = file.get_path()
                self.current_video_file = file_path
                self.video_player.load_video(file_path)
                
                # Show video player if hidden
                if not self.video_visible:
                    self.video_visible = True
                    self.video_container.set_visible(True)
                    self.video_button.set_active(True)
                    # Expand the paned to show video player
                    self.right_paned.set_position(300)
                
                self._show_toast(f"Loaded video: {os.path.basename(file_path)}")
        except Exception as e:
            pass  # User cancelled
    
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
    
    def _on_video_position_changed(self, player, position_sec):
        """Handle video position changes to update UI."""
        # Could be used to highlight current subtitle in the list
        pass


# Keyboard shortcuts overlay UI
SHORTCUTS_UI = """
<?xml version="1.0" encoding="UTF-8"?>
<interface>
  <object class="GtkShortcutsWindow" id="shortcuts">
    <property name="modal">1</property>
    <child>
      <object class="GtkShortcutsSection">
        <property name="section-name">shortcuts</property>
        <child>
          <object class="GtkShortcutsGroup">
            <property name="title" translatable="yes">File</property>
            <child>
              <object class="GtkShortcutsShortcut">
                <property name="title" translatable="yes">Save</property>
                <property name="accelerator">&lt;Ctrl&gt;S</property>
              </object>
            </child>
            <child>
              <object class="GtkShortcutsShortcut">
                <property name="title" translatable="yes">Save As</property>
                <property name="accelerator">&lt;Ctrl&gt;&lt;Shift&gt;S</property>
              </object>
            </child>
          </object>
        </child>
        <child>
          <object class="GtkShortcutsGroup">
            <property name="title" translatable="yes">Edit</property>
            <child>
              <object class="GtkShortcutsShortcut">
                <property name="title" translatable="yes">Undo</property>
                <property name="accelerator">&lt;Ctrl&gt;Z</property>
              </object>
            </child>
            <child>
              <object class="GtkShortcutsShortcut">
                <property name="title" translatable="yes">Redo</property>
                <property name="accelerator">&lt;Ctrl&gt;&lt;Shift&gt;Z</property>
              </object>
            </child>
            <child>
              <object class="GtkShortcutsShortcut">
                <property name="title" translatable="yes">New File</property>
                <property name="accelerator">&lt;Ctrl&gt;N</property>
              </object>
            </child>
            <child>
              <object class="GtkShortcutsShortcut">
                <property name="title" translatable="yes">Open File</property>
                <property name="accelerator">&lt;Ctrl&gt;O</property>
              </object>
            </child>
            <child>
              <object class="GtkShortcutsShortcut">
                <property name="title" translatable="yes">Remove Subtitle</property>
                <property name="accelerator">Delete</property>
              </object>
            </child>
            <child>
              <object class="GtkShortcutsShortcut">
                <property name="title" translatable="yes">Duplicate Subtitle</property>
                <property name="accelerator">&lt;Ctrl&gt;D</property>
              </object>
            </child>
            <child>
              <object class="GtkShortcutsShortcut">
                <property name="title" translatable="yes">Move Up</property>
                <property name="accelerator">&lt;Ctrl&gt;Up</property>
              </object>
            </child>
            <child>
              <object class="GtkShortcutsShortcut">
                <property name="title" translatable="yes">Move Down</property>
                <property name="accelerator">&lt;Ctrl&gt;Down</property>
              </object>
            </child>
          </object>
        </child>
      </object>
    </child>
  </object>
</interface>
"""
