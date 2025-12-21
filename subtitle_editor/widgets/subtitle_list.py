"""
Subtitle list view widget.

Displays all subtitle entries in a scrollable list with selection support.
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, GObject, Pango, Gio, Gdk
from subtitle_editor.models import SubtitleDocument, SubtitleEntry


class SubtitleListView(Gtk.ScrolledWindow):
    """Widget displaying a list of subtitle entries."""
    
    __gsignals__ = {
        'entry-selected': (GObject.SignalFlags.RUN_FIRST, None, (int,)),
        'entry-activated': (GObject.SignalFlags.RUN_FIRST, None, (int,)),
        'selection-changed': (GObject.SignalFlags.RUN_FIRST, None, ())
    }
    
    def __init__(self):
        super().__init__()
        
        self.document: SubtitleDocument = None
        self._selected_positions = []  # Changed to list for multi-selection
        
        # Set up scrolled window
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        
        # Add styling
        self.add_css_class("background")
        
        # Create list box with modern styling
        # BROWSE mode allows single click selection, Ctrl+Click for multi-select
        self.list_box = Gtk.ListBox()
        self.list_box.set_selection_mode(Gtk.SelectionMode.MULTIPLE)
        self.list_box.add_css_class("navigation-sidebar")
        self.list_box.set_margin_start(6)
        self.list_box.set_margin_end(6)
        self.list_box.set_margin_top(6)
        self.list_box.set_margin_bottom(6)
        self.list_box.connect('row-selected', self._on_row_selected)
        self.list_box.connect('row-activated', self._on_row_activated)
        
        # Create context menu
        self.context_menu = Gio.Menu()
        
        menu_section = Gio.Menu()
        menu_section.append("Duplicate", "win.duplicate-entry")
        menu_section.append("Remove", "win.remove-entry")
        self.context_menu.append_section(None, menu_section)
        
        move_section = Gio.Menu()
        move_section.append("Move Up", "win.move-up")
        move_section.append("Move Down", "win.move-down")
        self.context_menu.append_section(None, move_section)
        
        # Add click gesture for better selection control
        click = Gtk.GestureClick.new()
        click.set_button(1)  # Left mouse button
        click.connect('pressed', self._on_left_click)
        self.list_box.add_controller(click)
        
        # Add right-click gesture
        right_click = Gtk.GestureClick.new()
        right_click.set_button(3)  # Right mouse button
        right_click.connect('pressed', self._on_right_click)
        self.list_box.add_controller(right_click)
        
        self.set_child(self.list_box)
        
        # Placeholder with better styling
        placeholder = Adw.StatusPage()
        placeholder.set_icon_name("text-x-generic-symbolic")
        placeholder.set_title("No Subtitles")
        placeholder.set_description("Press Ctrl+Shift+N to add your first subtitle")
        placeholder.set_vexpand(True)
        self.list_box.set_placeholder(placeholder)
    
    def set_document(self, document: SubtitleDocument):
        """Set the subtitle document to display."""
        self.document = document
        self.refresh()
    
    def refresh(self, preserve_selection=False):
        """Refresh the entire list."""
        # Store current selection if requested
        old_selection = self._selected_positions.copy() if preserve_selection else []
        
        # Clear existing rows
        row = self.list_box.get_first_child()
        while row:
            next_row = row.get_next_sibling()
            self.list_box.remove(row)
            row = next_row
        
        # Add rows for each entry
        if self.document:
            for i, entry in enumerate(self.document.entries):
                row = self._create_row(entry, i)
                self.list_box.append(row)
        
        # Restore selection if requested
        if preserve_selection and old_selection:
            for pos in old_selection:
                if 0 <= pos < len(self.document.entries):
                    row = self.list_box.get_row_at_index(pos)
                    if row:
                        self.list_box.select_row(row)
            self._selected_positions = [p for p in old_selection if 0 <= p < len(self.document.entries)]
        else:
            self._selected_positions = []
    
    def refresh_entry(self, position: int):
        """Refresh a single entry in the list."""
        if not self.document or position < 0 or position >= len(self.document.entries):
            return
        
        row = self.list_box.get_row_at_index(position)
        if row:
            # Update the row content
            entry = self.document.entries[position]
            self._update_row(row, entry, position)
    
    def select_entry(self, position: int, clear_others=True):
        """Select an entry by position."""
        if position < 0:
            self.list_box.unselect_all()
            self._selected_positions = []
            return
        
        if clear_others:
            self.list_box.unselect_all()
            self._selected_positions = []
        
        row = self.list_box.get_row_at_index(position)
        if row:
            self.list_box.select_row(row)
            if position not in self._selected_positions:
                self._selected_positions.append(position)
    
    def get_selected_positions(self) -> list:
        """Get all currently selected positions."""
        return self._selected_positions.copy()
    
    def get_selected_position(self) -> int:
        """Get the first selected position (for backward compatibility)."""
        return self._selected_positions[0] if self._selected_positions else -1
    
    def _create_row(self, entry: SubtitleEntry, position: int) -> Gtk.ListBoxRow:
        """Create a list box row for a subtitle entry."""
        row = Gtk.ListBoxRow()
        
        # Main box for the row
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.set_margin_top(10)
        box.set_margin_bottom(10)
        row.set_child(box)
        
        # Index badge
        index_label = Gtk.Label()
        index_label.set_text(str(entry.index))
        index_label.set_width_chars(3)
        index_label.set_xalign(0.5)
        index_label.add_css_class("caption")
        index_label.add_css_class("numeric")
        index_label.set_valign(Gtk.Align.START)
        index_label.set_margin_top(2)
        box.append(index_label)
        
        # Content box (vertical)
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        content_box.set_hexpand(True)
        box.append(content_box)
        
        # Timing label with better formatting
        timing_label = Gtk.Label()
        timing_text = f"{entry.start_time} → {entry.end_time}"
        timing_label.set_markup(f"<span size='small' weight='500'>{timing_text}</span>")
        timing_label.set_xalign(0.0)
        timing_label.add_css_class("caption")
        timing_label.add_css_class("numeric")
        content_box.append(timing_label)
        
        # Text label with better styling
        text_label = Gtk.Label()
        text_label.set_text(entry.text)
        text_label.set_xalign(0.0)
        text_label.set_ellipsize(Pango.EllipsizeMode.END)
        text_label.set_lines(2)
        text_label.set_wrap(True)
        text_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        text_label.set_max_width_chars(50)
        content_box.append(text_label)
        
        # Store references for updates
        row._index_label = index_label
        row._timing_label = timing_label
        row._text_label = text_label
        
        return row
    
    def _update_row(self, row: Gtk.ListBoxRow, entry: SubtitleEntry, position: int):
        """Update an existing row with new entry data."""
        if hasattr(row, '_index_label'):
            row._index_label.set_text(str(entry.index))
        
        if hasattr(row, '_timing_label'):
            timing_text = f"{entry.start_time} → {entry.end_time}"
            row._timing_label.set_markup(f"<span size='small' weight='500'>{timing_text}</span>")
        
        if hasattr(row, '_text_label'):
            row._text_label.set_text(entry.text)
    
    def _on_row_selected(self, list_box, row):
        """Handle row selection - update selected positions list."""
        # Get all selected rows by iterating through valid ListBoxRow children
        selected_rows = []
        
        # Iterate through all rows
        row_iter = list_box.get_first_child()
        while row_iter:
            # Check if this is actually a ListBoxRow (not PopoverMenu or other widgets)
            if isinstance(row_iter, Gtk.ListBoxRow) and row_iter.is_selected():
                selected_rows.append(row_iter)
            row_iter = row_iter.get_next_sibling()
        
        # Update selected positions
        self._selected_positions = [r.get_index() for r in selected_rows]
        
        # Emit signals
        if self._selected_positions:
            # Emit entry-selected with first position for backward compatibility
            self.emit('entry-selected', self._selected_positions[0])
        else:
            self.emit('entry-selected', -1)
        
        self.emit('selection-changed')
    
    def _on_row_activated(self, list_box, row):
        """Handle row activation (double-click or Enter)."""
        position = row.get_index()
        self.emit('entry-activated', position)
    
    def _on_left_click(self, gesture, n_press, x, y):
        """Handle left click for better selection behavior."""
        # Get the state to check for Ctrl/Shift
        state = gesture.get_current_event_state()
        ctrl_pressed = state & Gdk.ModifierType.CONTROL_MASK
        shift_pressed = state & Gdk.ModifierType.SHIFT_MASK
        
        # Find which row was clicked
        row = self.list_box.get_row_at_y(y)
        if not row:
            return
        
        # If no modifiers, clear all other selections
        if not ctrl_pressed and not shift_pressed:
            # Deselect all first, then select the clicked one
            self.list_box.unselect_all()
            self.list_box.select_row(row)
            # Let the normal handler process this
    
    def _on_right_click(self, gesture, n_press, x, y):
        """Handle right-click on list."""
        # Find which row was clicked
        row = self.list_box.get_row_at_y(y)
        if row:
            # Select the row
            self.list_box.select_row(row)
            
            # Show context menu
            popover = Gtk.PopoverMenu()
            popover.set_menu_model(self.context_menu)
            popover.set_parent(self.list_box)
            popover.set_pointing_to(Gdk.Rectangle())
            popover.set_position(Gtk.PositionType.BOTTOM)
            
            # Position at click location
            rect = Gdk.Rectangle()
            rect.x = x
            rect.y = y
            rect.width = 1
            rect.height = 1
            popover.set_pointing_to(rect)
            
            popover.popup()
