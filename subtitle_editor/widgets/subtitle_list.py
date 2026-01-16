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
        
        # Set up scrolled window with modern styling
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.set_has_frame(True)
        
        # Create list box with modern styling using boxed-list style
        self.list_box = Gtk.ListBox()
        self.list_box.set_selection_mode(Gtk.SelectionMode.MULTIPLE)
        self.list_box.add_css_class("boxed-list")
        self.list_box.set_margin_start(12)
        self.list_box.set_margin_end(12)
        self.list_box.set_margin_top(12)
        self.list_box.set_margin_bottom(12)
        self.list_box.connect('row-selected', self._on_row_selected)
        self.list_box.connect('row-activated', self._on_row_activated)
        
        # Create context menu (rebuilt based on document format)
        self.context_menu = Gio.Menu()
        self._rebuild_context_menu()
        
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
        
        # Placeholder with better styling and action button
        placeholder_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        placeholder_box.set_vexpand(True)
        placeholder_box.set_valign(Gtk.Align.CENTER)
        
        placeholder = Adw.StatusPage()
        placeholder.set_icon_name("text-x-generic-symbolic")
        placeholder.set_title("No Subtitles")
        placeholder.set_description("Open a subtitle file or create your first subtitle entry")
        placeholder.set_vexpand(True)
        
        # Add action button to placeholder
        add_button = Gtk.Button(label="Add Subtitle")
        add_button.add_css_class("pill")
        add_button.add_css_class("suggested-action")
        add_button.set_action_name("win.add-entry")
        add_button.set_halign(Gtk.Align.CENTER)
        placeholder.set_child(add_button)
        
        placeholder_box.append(placeholder)
        self.list_box.set_placeholder(placeholder_box)
    
    def set_document(self, document: SubtitleDocument):
        """Set the subtitle document to display."""
        self.document = document
        self._rebuild_context_menu()
        self.refresh()
    
    def _rebuild_context_menu(self):
        """Rebuild right-click context menu based on current document."""
        self.context_menu.remove_all()

        menu_section = Gio.Menu()
        menu_section.append("Duplicate", "win.duplicate-entry")
        menu_section.append("Remove", "win.remove-entry")

        # Only show ASS-only items when applicable
        try:
            fmt = self.document.format if self.document else None
        except Exception:
            fmt = None

        if fmt is not None and getattr(fmt, 'value', None) in ('ass', 'ssa'):
            menu_section.append("Bulk Apply Style…", "win.bulk-apply-style")

        self.context_menu.append_section(None, menu_section)

        move_section = Gio.Menu()
        move_section.append("Move Up", "win.move-up")
        move_section.append("Move Down", "win.move-down")
        self.context_menu.append_section(None, move_section)

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
        """Create a list box row for a subtitle entry using Adw components."""
        row = Gtk.ListBoxRow()
        
        # Use Adw.ActionRow for better styling
        action_row = Adw.ActionRow()
        action_row.set_activatable(False)  # We handle activation at ListBoxRow level
        row.set_child(action_row)
        
        # Index badge as prefix
        index_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        index_box.set_valign(Gtk.Align.CENTER)
        index_label = Gtk.Label()
        index_label.set_text(str(entry.index))
        index_label.set_width_chars(4)
        index_label.set_xalign(0.5)
        index_label.add_css_class("title-3")
        index_label.add_css_class("numeric")
        index_label.add_css_class("dim-label")
        index_box.append(index_label)
        action_row.add_prefix(index_box)
        
        # Main content - use title and subtitle
        timing_text = f"{entry.start_time} → {entry.end_time}"
        action_row.set_title(entry.text[:80] if len(entry.text) > 80 else entry.text)
        
        # Build subtitle with timing and style
        style_name = entry.style or 'Default'
        subtitle_parts = [f"<span font_features='tnum=1'>{timing_text}</span>"]
        if entry.style:
            subtitle_parts.append(f"<b>Style:</b> {style_name}")
        action_row.set_subtitle(" • ".join(subtitle_parts))
        action_row.set_subtitle_lines(2)
        
        # Store references for updates
        row._action_row = action_row
        row._index_label = index_label
        row._entry = entry
        
        return row
    
    def _update_row(self, row: Gtk.ListBoxRow, entry: SubtitleEntry, position: int):
        """Update an existing row with new entry data."""
        if hasattr(row, '_action_row'):
            action_row = row._action_row
            action_row.set_title(entry.text[:80] if len(entry.text) > 80 else entry.text)
            
            timing_text = f"{entry.start_time} → {entry.end_time}"
            style_name = entry.style or 'Default'
            subtitle_parts = [f"<span font_features='tnum=1'>{timing_text}</span>"]
            if entry.style:
                subtitle_parts.append(f"<b>Style:</b> {style_name}")
            action_row.set_subtitle(" • ".join(subtitle_parts))
        
        if hasattr(row, '_index_label'):
            row._index_label.set_text(str(entry.index))
        
        if hasattr(row, '_entry'):
            row._entry = entry
    
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
