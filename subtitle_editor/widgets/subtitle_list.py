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
from subtitle_editor.resources import template_resource_path

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


@Gtk.Template(resource_path=template_resource_path('subtitle-list-row'))
class SubtitleListRow(Adw.ActionRow):
    """A single row in the subtitle list, created by the list factory."""

    __gtype_name__ = 'GsubSubtitleListRow'

    index_label = Gtk.Template.Child()


@Gtk.Template(resource_path=template_resource_path('subtitle-list'))
class SubtitleListView(Gtk.ScrolledWindow):
    """Widget displaying a list of subtitle entries with virtualized rendering."""

    __gtype_name__ = 'GsubSubtitleListView'

    __gsignals__ = {
        'entry-selected': (GObject.SignalFlags.RUN_FIRST, None, (int,)),
        'entry-activated': (GObject.SignalFlags.RUN_FIRST, None, (int,)),
        'selection-changed': (GObject.SignalFlags.RUN_FIRST, None, ())
    }

    list_view = Gtk.Template.Child()

    def __init__(self):
        super().__init__()

        self.document: SubtitleDocument = None
        self._selected_positions = []

        # Performance optimization: debounce refresh operations
        self._refresh_timeout_id = None
        self._pending_refresh_positions = set()
        self._refresh_debounce_delay = 50  # 50ms debounce

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

        self.list_view.set_model(self.selection_model)
        self.list_view.set_factory(self.factory)
        self.list_view.set_single_click_activate(False)

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
        """Rebuild the list store in-place to preserve scroll position."""
        # Clear selection before mutating the store to avoid
        # GTK trying to focus a row whose parent was removed.
        self.selection_model.unselect_all()
        self._selected_positions = []
        
        old_count = self.list_store.get_n_items()
        new_count = len(self.document.entries) if self.document else 0
        
        if old_count == new_count:
            # Same count — just update items in place
            for i in range(new_count):
                entry = self.document.entries[i]
                self.list_store.splice(i, 1, [SubtitleListItem(position=i, entry=entry)])
        else:
            # Different count — replace all items in one splice call
            new_items = []
            if self.document:
                for i, entry in enumerate(self.document.entries):
                    new_items.append(SubtitleListItem(position=i, entry=entry))
            self.list_store.splice(0, old_count, new_items)

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
        
        # Restore selection via idle to let GTK wire up new rows first
        if preserve_selection and old_selection:
            self._selected_positions = [p for p in old_selection if 0 <= p < len(self.document.entries)]
            GLib.idle_add(self._restore_selection_idle)
        else:
            self._selected_positions = []
    
    def _restore_selection_idle(self):
        """Restore selection after GTK finishes processing model changes."""
        for pos in self._selected_positions:
            if 0 <= pos < self.list_store.get_n_items():
                self.selection_model.select_item(pos, False)
        return False
    
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
        to_select = []
        for position in self._pending_refresh_positions:
            if 0 <= position < self.list_store.get_n_items() and self.document and position < len(self.document.entries):
                entry = self.document.entries[position]
                was_selected = position in self._selected_positions
                self.list_store.splice(position, 1, [SubtitleListItem(position=position, entry=entry)])
                if was_selected:
                    to_select.append(position)
        
        self._pending_refresh_positions.clear()
        self._refresh_timeout_id = None
        
        # Defer selection to let GTK wire up new rows
        if to_select:
            GLib.idle_add(self._select_positions_idle, to_select)
        
        return False  # Don't repeat timeout
    
    def _select_positions_idle(self, positions):
        """Select positions after GTK finishes processing model changes."""
        for pos in positions:
            if 0 <= pos < self.list_store.get_n_items():
                self.selection_model.select_item(pos, False)
        return False
    
    def _scroll_to(self, position: int):
        """Scroll the list view to make the given position visible."""
        if 0 <= position < self.list_store.get_n_items():
            self.list_view.scroll_to(position, Gtk.ListScrollFlags.NONE, None)

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
            if position not in self._selected_positions:
                self._selected_positions.append(position)
            # Defer select_item to let GTK finish wiring rows
            GLib.idle_add(self._select_single_idle, position)
        
        self._scroll_to(position)
    
    def _select_single_idle(self, position):
        """Select a single item after model changes settle."""
        if 0 <= position < self.list_store.get_n_items():
            self.selection_model.select_item(position, False)
        return False
    
    def get_selected_positions(self) -> list:
        """Get all currently selected positions."""
        return self._selected_positions.copy()
    
    def get_selected_position(self) -> int:
        """Get the first selected position (for backward compatibility)."""
        return self._selected_positions[0] if self._selected_positions else -1
    
    def _on_factory_setup(self, factory, list_item):
        """Setup phase: Create the widget structure for list items."""
        # GsubSubtitleListRow is a Blueprint-templated Adw.ActionRow with the
        # index badge already wired up as a prefix.
        list_item.set_child(SubtitleListRow())

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
            action_row.index_label.set_text(str(item.entry_index))

            # Update title (subtitle text) — escape Pango markup
            action_row.set_title(GLib.markup_escape_text(item.entry_text))

            # Update subtitle (timing and style) — escape Pango markup
            timing_text = f"{item.entry_start} → {item.entry_end}"
            subtitle_parts = [GLib.markup_escape_text(timing_text)]
            if item.entry_style:
                subtitle_parts.append(GLib.markup_escape_text(f"Style: {item.entry_style}"))
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
