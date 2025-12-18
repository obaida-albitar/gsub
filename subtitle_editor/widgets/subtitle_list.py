"""
Subtitle list view widget.

Displays all subtitle entries in a scrollable list with selection support.
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, GObject, Pango, Gio, Gdk
from subtitle_editor.models import SubtitleDocument, SubtitleEntry


class SubtitleListView(Gtk.ScrolledWindow):
    """Widget displaying a list of subtitle entries."""
    
    __gsignals__ = {
        'entry-selected': (GObject.SignalFlags.RUN_FIRST, None, (int,)),
        'entry-activated': (GObject.SignalFlags.RUN_FIRST, None, (int,))
    }
    
    def __init__(self):
        super().__init__()
        
        self.document: SubtitleDocument = None
        self._selected_position = -1
        
        # Set up scrolled window
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        
        # Create list box
        self.list_box = Gtk.ListBox()
        self.list_box.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.list_box.add_css_class("boxed-list")
        self.list_box.connect('row-selected', self._on_row_selected)
        self.list_box.connect('row-activated', self._on_row_activated)
        
        # Create context menu
        self.context_menu = Gio.Menu()
        
        menu_section = Gio.Menu()
        menu_section.append("Duplicate", "win.duplicate-entry")
        menu_section.append("Remove", "win.remove-entry")
        self.context_menu.append_section(None, menu_section)
        
        # Add right-click gesture
        right_click = Gtk.GestureClick.new()
        right_click.set_button(3)  # Right mouse button
        right_click.connect('pressed', self._on_right_click)
        self.list_box.add_controller(right_click)
        
        self.set_child(self.list_box)
        
        # Placeholder
        placeholder = Gtk.Label()
        placeholder.set_markup("<big>No subtitles</big>\n\nPress <b>Ctrl+N</b> to add a subtitle")
        placeholder.set_margin_top(48)
        placeholder.set_margin_bottom(48)
        placeholder.add_css_class("dim-label")
        self.list_box.set_placeholder(placeholder)
    
    def set_document(self, document: SubtitleDocument):
        """Set the subtitle document to display."""
        self.document = document
        self.refresh()
    
    def refresh(self):
        """Refresh the entire list."""
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
        
        self._selected_position = -1
    
    def refresh_entry(self, position: int):
        """Refresh a single entry in the list."""
        if not self.document or position < 0 or position >= len(self.document.entries):
            return
        
        row = self.list_box.get_row_at_index(position)
        if row:
            # Update the row content
            entry = self.document.entries[position]
            self._update_row(row, entry, position)
    
    def select_entry(self, position: int):
        """Select an entry by position."""
        if position < 0:
            self.list_box.unselect_all()
            self._selected_position = -1
            return
        
        row = self.list_box.get_row_at_index(position)
        if row:
            self.list_box.select_row(row)
            self._selected_position = position
    
    def get_selected_position(self) -> int:
        """Get the currently selected position."""
        return self._selected_position
    
    def _create_row(self, entry: SubtitleEntry, position: int) -> Gtk.ListBoxRow:
        """Create a list box row for a subtitle entry."""
        row = Gtk.ListBoxRow()
        row.set_margin_top(0)
        row.set_margin_bottom(0)
        
        # Main box for the row
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        row.set_child(box)
        
        # Index label
        index_label = Gtk.Label()
        index_label.set_text(str(entry.index))
        index_label.set_width_chars(4)
        index_label.set_xalign(1.0)
        index_label.add_css_class("dim-label")
        index_label.add_css_class("monospace")
        box.append(index_label)
        
        # Content box (vertical)
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        content_box.set_hexpand(True)
        box.append(content_box)
        
        # Timing label
        timing_label = Gtk.Label()
        timing_text = f"{entry.start_time} → {entry.end_time}"
        timing_label.set_markup(f"<small>{timing_text}</small>")
        timing_label.set_xalign(0.0)
        timing_label.add_css_class("dim-label")
        timing_label.add_css_class("monospace")
        content_box.append(timing_label)
        
        # Text label
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
            row._timing_label.set_markup(f"<small>{timing_text}</small>")
        
        if hasattr(row, '_text_label'):
            row._text_label.set_text(entry.text)
    
    def _on_row_selected(self, list_box, row):
        """Handle row selection."""
        if row:
            position = row.get_index()
            self._selected_position = position
            self.emit('entry-selected', position)
        else:
            self._selected_position = -1
            self.emit('entry-selected', -1)
    
    def _on_row_activated(self, list_box, row):
        """Handle row activation (double-click or Enter)."""
        position = row.get_index()
        self.emit('entry-activated', position)
    
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
