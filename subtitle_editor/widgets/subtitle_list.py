"""
Subtitle list view widget.

Displays all subtitle entries in a scrollable list with selection support.
Uses Gtk.ListView for efficient virtualization with large datasets.
"""

import gi
import logging
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, GObject, Pango, Gio, Gdk, GLib
from subtitle_editor.models import SubtitleDocument, SubtitleEntry

logger = logging.getLogger(__name__)


class SubtitleListItem(GObject.Object):
    """Wrapper object for list store items holding subtitle entry data."""
    
    __gtype_name__ = 'SubtitleListItem'
    
    position = GObject.Property(type=int, default=0)
    entry_index = GObject.Property(type=int, default=0)
    entry_text = GObject.Property(type=str, default='')
    entry_start = GObject.Property(type=str, default='')
    entry_end = GObject.Property(type=str, default='')
    entry_style = GObject.Property(type=str, default='')
    
    def __init__(self, position=0, entry=None):
        super().__init__()
        self.position = position
        if entry:
            self.entry_index = entry.index
            self.entry_text = entry.text[:80] if len(entry.text) > 80 else entry.text
            self.entry_start = str(entry.start_time)
            self.entry_end = str(entry.end_time)
            self.entry_style = entry.style or ''


class SubtitleListView(Gtk.ScrolledWindow):
    """Widget displaying a list of subtitle entries with virtualized rendering."""
    
    __gsignals__ = {
        'entry-selected': (GObject.SignalFlags.RUN_FIRST, None, (int,)),
        'entry-activated': (GObject.SignalFlags.RUN_FIRST, None, (int,)),
        'selection-changed': (GObject.SignalFlags.RUN_FIRST, None, ())
    }
    
    def __init__(self):
        super().__init__()
        
        self.document: SubtitleDocument = None
        self._selected_positions = []
        
        # Performance optimization: debounce refresh operations
        self._refresh_timeout_id = None
        self._pending_refresh_positions = set()
        self._refresh_debounce_delay = 50  # 50ms debounce
        
        # Set up scrolled window with modern styling
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.set_has_frame(True)
        
        # Create GListStore to hold subtitle entries
        # We'll store position indices wrapped in GObject instances
        self.list_store = Gio.ListStore.new(SubtitleListItem)
        
        # Create selection model supporting multiple selection
        self.selection_model = Gtk.MultiSelection.new(self.list_store)
        self.selection_model.connect('selection-changed', self._on_selection_changed)
        
        # Create factory for list items
        self.factory = Gtk.SignalListItemFactory()
        self.factory.connect('setup', self._on_factory_setup)
        self.factory.connect('bind', self._on_factory_bind)
        self.factory.connect('unbind', self._on_factory_unbind)
        
        # Create the ListView with virtualization
        self.list_view = Gtk.ListView()
        self.list_view.set_model(self.selection_model)
        self.list_view.set_factory(self.factory)
        self.list_view.set_single_click_activate(False)
        self.list_view.add_css_class("navigation-sidebar")
        
        # Add empty-state placeholder
        placeholder = Adw.StatusPage()
        placeholder.set_icon_name("text-x-generic-symbolic")
        placeholder.set_title("No Subtitles")
        placeholder.set_description("Open a subtitle file or add your first subtitle entry")
        
        add_button = Gtk.Button(label="Add Subtitle")
        add_button.add_css_class("pill")
        add_button.add_css_class("suggested-action")
        add_button.set_action_name("win.add-entry")
        add_button.set_halign(Gtk.Align.CENTER)
        placeholder.set_child(add_button)
        
        if hasattr(self.list_view, 'set_placeholder'):
            self.list_view.set_placeholder(placeholder)
        
        # Make ListView the direct child of the ScrolledWindow so that
        # the ScrolledWindow uses the ListView's own Gtk.Scrollable
        # implementation for adjustment communication.
        self.list_view.set_margin_start(12)
        self.list_view.set_margin_end(12)
        self.list_view.set_margin_top(12)
        self.list_view.set_margin_bottom(12)
        self.set_child(self.list_view)
        
        # Create context menu (rebuilt based on document format)
        self.context_menu = Gio.Menu()
        self._rebuild_context_menu()
        
        # Add activation gesture (double-click)
        activation = Gtk.GestureClick.new()
        activation.set_button(1)
        activation.connect('pressed', self._on_click_pressed)
        self.list_view.add_controller(activation)
        
        # Add right-click gesture
        right_click = Gtk.GestureClick.new()
        right_click.set_button(3)
        right_click.connect('pressed', self._on_right_click)
        self.list_view.add_controller(right_click)
        
        # Add key controller for activation (Enter key)
        key_controller = Gtk.EventControllerKey.new()
        key_controller.connect('key-pressed', self._on_key_pressed)
        self.list_view.add_controller(key_controller)
    
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

    def _rebuild_store(self):
        """Create a new store and selection model, and set them on the list view."""
        new_store = Gio.ListStore.new(SubtitleListItem)
        if self.document:
            for i, entry in enumerate(self.document.entries):
                new_store.append(SubtitleListItem(position=i, entry=entry))
        
        new_selection = Gtk.MultiSelection.new(new_store)
        new_selection.connect('selection-changed', self._on_selection_changed)
        
        self.list_store = new_store
        self.selection_model = new_selection
        self.list_view.set_model(self.selection_model)

    def refresh(self, preserve_selection=False):
        """Refresh the entire list by rebuilding the model."""
        # Cancel any pending single-entry refreshes
        if self._refresh_timeout_id is not None:
            GLib.source_remove(self._refresh_timeout_id)
            self._refresh_timeout_id = None
        self._pending_refresh_positions.clear()
        
        # Store current selection if requested
        old_selection = self._selected_positions.copy() if preserve_selection else []
        
        self._rebuild_store()
        self.list_view.queue_resize()
        
        # Restore selection if requested
        if preserve_selection and old_selection:
            for pos in old_selection:
                if 0 <= pos < len(self.document.entries):
                    self.selection_model.select_item(pos, False)
            self._selected_positions = [p for p in old_selection if 0 <= p < len(self.document.entries)]
        else:
            self._selected_positions = []
    
    def refresh_entry(self, position: int):
        """Refresh a single entry in the list with debouncing."""
        if not self.document or position < 0 or position >= len(self.document.entries):
            return
        
        # Add to pending refresh set
        self._pending_refresh_positions.add(position)
        
        # Cancel existing timeout if any
        if self._refresh_timeout_id is not None:
            GLib.source_remove(self._refresh_timeout_id)
        
        # Set new timeout
        self._refresh_timeout_id = GLib.timeout_add(
            self._refresh_debounce_delay, self._process_pending_refreshes
        )
    
    def _process_pending_refreshes(self):
        """Process all pending entry refreshes in batch."""
        for position in self._pending_refresh_positions:
            if 0 <= position < self.list_store.get_n_items() and self.document and position < len(self.document.entries):
                entry = self.document.entries[position]
                store_item = self.list_store.get_item(position)
                if store_item:
                    store_item.entry_index = entry.index
                    store_item.entry_text = entry.text[:80] if len(entry.text) > 80 else entry.text
                    store_item.entry_start = str(entry.start_time)
                    store_item.entry_end = str(entry.end_time)
                    store_item.entry_style = entry.style or ''
                    self.list_store.splice(position, 1, [store_item])
        
        self._pending_refresh_positions.clear()
        self._refresh_timeout_id = None
        return False  # Don't repeat timeout
    
    def select_entry(self, position: int, clear_others=True):
        """Select an entry by position."""
        if position < 0:
            self.selection_model.unselect_all()
            self._selected_positions = []
            return
        
        if clear_others:
            self.selection_model.unselect_all()
            self._selected_positions = []
        
        if position < self.list_store.get_n_items():
            self.selection_model.select_item(position, False)
            if position not in self._selected_positions:
                self._selected_positions.append(position)
    
    def get_selected_positions(self) -> list:
        """Get all currently selected positions."""
        return self._selected_positions.copy()
    
    def get_selected_position(self) -> int:
        """Get the first selected position (for backward compatibility)."""
        return self._selected_positions[0] if self._selected_positions else -1
    
    def _on_factory_setup(self, factory, list_item):
        """Setup phase: Create the widget structure for list items."""
        # Use Adw.ActionRow for better styling
        action_row = Adw.ActionRow()
        action_row.set_activatable(False)
        
        # Index badge as prefix
        index_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        index_box.set_valign(Gtk.Align.CENTER)
        index_label = Gtk.Label()
        index_label.set_width_chars(4)
        index_label.set_xalign(0.5)
        index_label.add_css_class("title-3")
        index_label.add_css_class("numeric")
        index_label.add_css_class("dim-label")
        index_box.append(index_label)
        action_row.add_prefix(index_box)
        
        # Set subtitle lines
        action_row.set_subtitle_lines(2)
        
        # Store references for bind phase
        action_row._index_label = index_label
        
        list_item.set_child(action_row)
    
    def _on_factory_bind(self, factory, list_item):
        """Bind phase: Update widget with actual data."""
        try:
            item = list_item.get_item()
            if not item:
                logger.warning("bind: get_item() returned None")
                return
            
            position = item.position
            action_row = list_item.get_child()
            
            logger.debug("bind: position=%d, idx=%d, text='%s'",
                         position, item.entry_index,
                         item.entry_text[:30])
            
            # Update index
            action_row._index_label.set_text(str(item.entry_index))
            
            # Update title (subtitle text)
            action_row.set_title(item.entry_text)
            
            # Update subtitle (timing and style)
            timing_text = f"{item.entry_start} → {item.entry_end}"
            subtitle_parts = [timing_text]
            if item.entry_style:
                subtitle_parts.append(f"Style: {item.entry_style}")
            action_row.set_subtitle(" • ".join(subtitle_parts))
        except Exception:
            logger.exception("Failed to bind list item")
    
    def _on_factory_unbind(self, factory, list_item):
        """Unbind phase: Clean up if needed."""
        item = list_item.get_item()
        if item:
            logger.debug("unbind: position=%d", item.position)
    
    def _on_selection_changed(self, selection_model, position, n_items):
        """Handle selection changes in the ListView."""
        selected = []
        bitset = selection_model.get_selection()
        size = bitset.get_size()
        for i in range(size):
            selected.append(bitset.get_nth(i))
        self._selected_positions = selected
        
        # Emit signals
        if self._selected_positions:
            self.emit('entry-selected', self._selected_positions[0])
        else:
            self.emit('entry-selected', -1)
        
        self.emit('selection-changed')
    
    def _on_click_pressed(self, gesture, n_press, x, y):
        """Handle click for activation (double-click)."""
        if n_press == 2:
            if self._selected_positions:
                self.emit('entry-activated', self._selected_positions[0])
    
    def _on_key_pressed(self, controller, keyval, keycode, state):
        """Handle key press for list activation."""
        if keyval == Gdk.KEY_Return or keyval == Gdk.KEY_KP_Enter:
            if self._selected_positions:
                self.emit('entry-activated', self._selected_positions[0])
                return True
        return False
    
    def _on_right_click(self, gesture, n_press, x, y):
        """Handle right-click on list."""
        # Show context menu
        popover = Gtk.PopoverMenu()
        popover.set_menu_model(self.context_menu)
        popover.set_parent(self.list_view)
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
