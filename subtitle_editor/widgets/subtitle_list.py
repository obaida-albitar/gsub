"""
Subtitle list view widget.

Displays all subtitle entries in a scrollable list with selection support.
Uses Gtk.ListView for efficient virtualization with large datasets.

Structural operations (insert/remove/move) update the Gio.ListStore
incrementally instead of rebuilding it, and field changes are pushed to rows
through GObject property notifications, so editing stays responsive on very
long subtitle files. A search bar above the list (Ctrl+F) highlights matches
and jumps between them.
"""

import gi
import logging
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, GObject, Gio, Gdk, GLib
from subtitle_editor.models import SubtitleDocument
from subtitle_editor.parsers.ass_tags import strip_override_blocks  # noqa: E402
from subtitle_editor.resources import template_resource_path

logger = logging.getLogger(__name__)

# Subtitle text is truncated to this many characters for the row title.
DISPLAY_TEXT_LIMIT = 120


def highlight_markup(text: str, term: str) -> str:
    """Return ``text`` escaped for Pango markup, with case-insensitive
    matches of ``term`` wrapped in <b> tags (search-result highlighting)."""
    if not term:
        return GLib.markup_escape_text(text)

    lower = text.lower()
    needle = term.lower()
    parts = []
    idx = 0
    while True:
        found = lower.find(needle, idx)
        if found < 0:
            parts.append(GLib.markup_escape_text(text[idx:]))
            break
        parts.append(GLib.markup_escape_text(text[idx:found]))
        parts.append("<b>%s</b>" % GLib.markup_escape_text(text[found:found + len(term)]))
        idx = found + len(term)
    return "".join(parts)


class SubtitleListItem(GObject.Object):
    """Wrapper object for list store items holding subtitle entry data.

    Rows re-render through ``notify`` handlers bound in the factory, so
    updating a property updates the visible row without splicing the store.
    """

    __gtype_name__ = 'SubtitleListItem'

    position = GObject.Property(type=int, default=0)
    entry_index = GObject.Property(type=int, default=0)
    entry_text = GObject.Property(type=str, default='')
    entry_start = GObject.Property(type=str, default='')
    entry_end = GObject.Property(type=str, default='')
    entry_style = GObject.Property(type=str, default='')
    search_term = GObject.Property(type=str, default='')

    def __init__(self, position=0, entry=None, search_term=''):
        super().__init__()
        self.position = position
        self.search_term = search_term
        # Raw references used by the rebuild diff to detect unchanged items.
        self._entry = None
        self._text = None
        self._start = None
        self._end = None
        # Cleaned text (override blocks stripped) for display and search.
        self._clean_text = ''
        # Lowercased clean text, computed lazily for the search scan.
        self._lower_text = None
        if entry:
            self.update_from(entry)

    def update_from(self, entry, position=None):
        """Refresh all displayed fields from the document entry."""
        if position is not None:
            self.position = position
        self._entry = entry
        self._text = entry.text
        self._start = entry.start_time
        self._end = entry.end_time
        self._lower_text = None
        self.entry_index = entry.index
        # Rows show (and search matches) the human-readable text: ASS
        # override blocks are stripped for display. The raw text stays on
        # the entry model and in self._text untouched.
        clean = strip_override_blocks(entry.text)
        self._clean_text = clean
        self.entry_text = clean[:DISPLAY_TEXT_LIMIT] if len(clean) > DISPLAY_TEXT_LIMIT else clean
        self.entry_start = str(entry.start_time)
        self.entry_end = str(entry.end_time)
        self.entry_style = entry.style or ''

    def matches_entry(self, entry) -> bool:
        """Whether this item already displays ``entry``.

        Commands replace (rather than mutate) the ``str``/``TimeCode`` objects
        they change, so comparing displayed-field identity is a cheap and
        reliable staleness check for the rebuild diff.
        """
        return (self._entry is entry
                and self._text is entry.text
                and self._start is entry.start_time
                and self._end is entry.end_time
                and self.entry_style == (entry.style or ''))


@Gtk.Template(resource_path=template_resource_path('subtitle-list-row'))
class SubtitleListRow(Adw.ActionRow):
    """A single row in the subtitle list, created by the list factory."""

    __gtype_name__ = 'GsubSubtitleListRow'

    index_label = Gtk.Template.Child()


@Gtk.Template(resource_path=template_resource_path('subtitle-list'))
class SubtitleListView(Gtk.Box):
    """Widget displaying a list of subtitle entries with virtualized rendering."""

    __gtype_name__ = 'GsubSubtitleListView'

    __gsignals__ = {
        'entry-selected': (GObject.SignalFlags.RUN_FIRST, None, (int,)),
        'entry-activated': (GObject.SignalFlags.RUN_FIRST, None, (int,)),
        'selection-changed': (GObject.SignalFlags.RUN_FIRST, None, ())
    }

    search_bar = Gtk.Template.Child()
    search_entry = Gtk.Template.Child()
    search_prev_button = Gtk.Template.Child()
    search_next_button = Gtk.Template.Child()
    match_label = Gtk.Template.Child()
    empty_revealer = Gtk.Template.Child()
    list_scroll = Gtk.Template.Child()
    list_view = Gtk.Template.Child()

    def __init__(self):
        super().__init__()

        self.document: SubtitleDocument = None
        self._selected_positions = []

        # Debounce for single-entry refreshes driven by editor-panel edits.
        self._refresh_timeout_id = None
        self._pending_refresh_positions = set()
        self._refresh_debounce_delay = 50  # 50ms debounce

        # Search state.
        self._search_term = ''
        self._search_matches = []
        self._current_match = -1
        # Positions whose items currently carry the search term (only rows
        # that match need it for highlighting; updating just these keeps each
        # keystroke cheap on long documents).
        self._highlighted_positions = set()

        # Create GListStore to hold subtitle entries
        self.list_store = Gio.ListStore.new(SubtitleListItem)

        # Create selection model supporting multiple selection
        self.selection_model = Gtk.MultiSelection.new(self.list_store)
        self._selection_changed_id = self.selection_model.connect(
            'selection-changed', self._on_selection_changed)

        # Create factory for list items
        self.factory = Gtk.SignalListItemFactory()
        self.factory.connect('setup', self._on_factory_setup)
        self.factory.connect('bind', self._on_factory_bind)
        self.factory.connect('unbind', self._on_factory_unbind)

        self.list_view.set_model(self.selection_model)
        self.list_view.set_factory(self.factory)
        self.list_view.set_single_click_activate(False)

        # Context menu: one persistent popover reused for every right-click.
        # Let GTK position it (it flips near window edges), so the menu never
        # gets squeezed into a scrolling region.
        self.context_menu = Gio.Menu()
        self._rebuild_context_menu()
        self.context_popover = Gtk.PopoverMenu.new_from_model(self.context_menu)
        self.context_popover.set_has_arrow(False)
        self.context_popover.set_parent(self.list_view)

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

        # Search bar wiring. Key capture is scoped to this widget so typing in
        # the editor panel is never hijacked while search is open.
        self.search_bar.set_key_capture_widget(self)
        self.search_entry.connect('changed', self._on_search_changed)
        self.search_entry.connect('next-match', lambda *a: self._search_move(1))
        self.search_entry.connect('previous-match', lambda *a: self._search_move(-1))
        self.search_entry.connect('stop-search', lambda *a: self.set_search_visible(False))
        self.search_prev_button.connect('clicked', lambda *a: self._search_move(-1))
        self.search_next_button.connect('clicked', lambda *a: self._search_move(1))

        search_keys = Gtk.EventControllerKey.new()
        search_keys.connect('key-pressed', self._on_search_key_pressed)
        self.search_entry.add_controller(search_keys)

        self._update_match_label()
        self._update_empty_state()

    # --- Document handling -------------------------------------------------

    def set_document(self, document: SubtitleDocument):
        """Set the subtitle document to display."""
        self.document = document
        self._rebuild_context_menu()
        self.set_search_visible(False)
        self.refresh()

    def _rebuild_context_menu(self):
        """Rebuild right-click context menu based on current document."""
        self.context_menu.remove_all()

        insert_section = Gio.Menu()
        insert_section.append("Insert Above", "win.insert-above")
        insert_section.append("Insert Below", "win.insert-below")
        self.context_menu.append_section(None, insert_section)

        edit_section = Gio.Menu()
        edit_section.append("Duplicate", "win.duplicate-entry")
        edit_section.append("Remove", "win.remove-entry")
        self.context_menu.append_section(None, edit_section)

        move_section = Gio.Menu()
        move_section.append("Move Up", "win.move-up")
        move_section.append("Move Down", "win.move-down")
        self.context_menu.append_section(None, move_section)

        # Only show ASS-only items when applicable
        try:
            fmt = self.document.format if self.document else None
        except Exception:
            fmt = None

        if fmt is not None and getattr(fmt, 'value', None) in ('ass', 'ssa'):
            style_section = Gio.Menu()
            style_section.append("Bulk Apply Style…", "win.bulk-apply-style")
            self.context_menu.append_section(None, style_section)

    # --- Store updates -----------------------------------------------------
    #
    # Structural operations notify the view incrementally: the document has
    # already been mutated by a command, and these methods splice the store to
    # match, renumbering only the shifted items (rows are updated through
    # property notifications, so cost is bounded by the visible rows).

    def entries_inserted(self, position: int, count: int = 1):
        """Notify the view that ``count`` entries were inserted at ``position``."""
        if not self.document or count <= 0:
            return
        n = len(self.document.entries)
        position = max(0, min(position, n - count))
        items = [
            SubtitleListItem(position=position + i,
                             entry=self.document.entries[position + i],
                             search_term=self._search_term)
            for i in range(count)
        ]
        self.list_store.splice(position, 0, items)
        self._renumber_from(position + count)
        self._after_structure_change()

    def entries_removed(self, positions):
        """Notify the view that entries at ``positions`` were removed."""
        if not self.document:
            return
        first = None
        for pos in sorted(set(positions), reverse=True):
            if 0 <= pos < self.list_store.get_n_items():
                self.list_store.splice(pos, 1, [])
                first = pos
        if first is not None:
            self._renumber_from(first)
            self._after_structure_change()

    def entry_moved(self, from_position: int, to_position: int):
        """Notify the view that an entry moved positions in the document."""
        n = self.list_store.get_n_items()
        if (not (0 <= from_position < n) or not (0 <= to_position < n)
                or from_position == to_position):
            return
        item = self.list_store.get_item(from_position)
        self.list_store.splice(from_position, 1, [])
        self.list_store.splice(to_position, 0, [item])
        self._renumber_from(min(from_position, to_position))
        self._after_structure_change()

    def _renumber_from(self, start: int):
        """Update position/index properties of items at or after ``start``."""
        if not self.document:
            return
        entries = self.document.entries
        for i in range(max(0, start), self.list_store.get_n_items()):
            item = self.list_store.get_item(i)
            if item.position != i:
                item.position = i
            index = entries[i].index
            if item.entry_index != index:
                item.entry_index = index

    def _after_structure_change(self):
        self._update_empty_state()
        self._sync_search_after_change()

    def _rebuild_store(self):
        """Rebuild the list store, splicing only the changed range.

        The store and the document usually agree on a large common prefix and
        suffix (undoing an insert touches one row; editing one entry touches
        one row). Unchanged items are detected by identity and kept, so a
        full refresh stays cheap even for very long documents.
        """
        n_old = self.list_store.get_n_items()
        if not self.document:
            if n_old:
                self.list_store.splice(0, n_old, [])
            return

        entries = self.document.entries
        n_new = len(entries)

        # Longest identical prefix.
        p = 0
        while (p < n_old and p < n_new
               and self.list_store.get_item(p).matches_entry(entries[p])):
            p += 1

        # Longest identical suffix (not overlapping the prefix).
        s = 0
        while (s < n_old - p and s < n_new - p
               and self.list_store.get_item(n_old - 1 - s).matches_entry(
                   entries[n_new - 1 - s])):
            s += 1

        new_items = [
            SubtitleListItem(position=i, entry=entries[i],
                             search_term=self._search_term)
            for i in range(p, n_new - s)
        ]
        self.list_store.splice(p, n_old - s - p, new_items)
        self._renumber_from(p)

    def refresh(self, preserve_selection=False):
        """Refresh the entire list by rebuilding the model in one splice."""
        if self._refresh_timeout_id is not None:
            GLib.source_remove(self._refresh_timeout_id)
            self._refresh_timeout_id = None
        self._pending_refresh_positions.clear()

        old_selection = self._selected_positions.copy() if preserve_selection else []

        # Rebuild and restore selection while selection notifications are
        # blocked, then emit once. This avoids clearing and re-filling the
        # editor panel for every intermediate model change.
        self.selection_model.handler_block(self._selection_changed_id)
        try:
            self._rebuild_store()
            self._selected_positions = []
            if preserve_selection and old_selection:
                n = self.list_store.get_n_items()
                self._selected_positions = [p for p in old_selection if 0 <= p < n]
                for pos in self._selected_positions:
                    self.selection_model.select_item(pos, False)
        finally:
            self.selection_model.handler_unblock(self._selection_changed_id)

        self._after_structure_change()
        self._emit_selection_signals()

    def refresh_entry(self, position: int):
        """Refresh a single entry in the list with debouncing."""
        if not self.document or not (0 <= position < len(self.document.entries)):
            return

        self._pending_refresh_positions.add(position)

        if self._refresh_timeout_id is not None:
            GLib.source_remove(self._refresh_timeout_id)

        self._refresh_timeout_id = GLib.timeout_add(
            self._refresh_debounce_delay, self._process_pending_refreshes
        )

    def _process_pending_refreshes(self):
        """Process all pending entry refreshes in batch."""
        if self.document:
            n = self.list_store.get_n_items()
            for position in self._pending_refresh_positions:
                if 0 <= position < n and position < len(self.document.entries):
                    item = self.list_store.get_item(position)
                    if item:
                        item.update_from(self.document.entries[position], position)

        self._pending_refresh_positions.clear()
        self._refresh_timeout_id = None
        # An edited row may now match (or stop matching) the search term.
        if self._search_term:
            self._recompute_search(jump=False, update_items=True)
        return False  # Don't repeat timeout

    # --- Selection ----------------------------------------------------------

    def _emit_selection_signals(self):
        """Emit selection signals once, reflecting the current state."""
        if self._selected_positions:
            self.emit('entry-selected', self._selected_positions[0])
        else:
            self.emit('entry-selected', -1)
        self.emit('selection-changed')

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
            self.selection_model.select_item(position, False)

        self._scroll_to(position)

    def get_selected_positions(self) -> list:
        """Get all currently selected positions."""
        return self._selected_positions.copy()

    def get_selected_position(self) -> int:
        """Get the first selected position (for backward compatibility)."""
        return self._selected_positions[0] if self._selected_positions else -1

    # --- List factory -------------------------------------------------------

    def _on_factory_setup(self, factory, list_item):
        """Setup phase: Create the widget structure for list items."""
        list_item.set_child(SubtitleListRow())

    def _on_factory_bind(self, factory, list_item):
        """Bind phase: Update widget with actual data."""
        item = list_item.get_item()
        if not item:
            return
        row = list_item.get_child()
        self._apply_item(item, row)
        # Field updates arrive as property notifications (no store splices).
        handler_id = item.connect('notify', self._on_item_notify, row)
        row._bound_item_handler = (item, handler_id)

    def _on_factory_unbind(self, factory, list_item):
        """Unbind phase: Disconnect the item notification handler."""
        row = list_item.get_child()
        if row is None:
            return
        bound = getattr(row, '_bound_item_handler', None)
        if bound:
            item, handler_id = bound
            item.disconnect(handler_id)
            row._bound_item_handler = None

    def _on_item_notify(self, item, pspec, row):
        self._apply_item(item, row)

    def _apply_item(self, item, row):
        """Push all displayed fields of ``item`` onto ``row``."""
        row.index_label.set_text(str(item.entry_index))
        row.set_title(highlight_markup(item.entry_text, item.search_term))
        timing_text = f"{item.entry_start} → {item.entry_end}"
        subtitle_parts = [GLib.markup_escape_text(timing_text)]
        if item.entry_style:
            subtitle_parts.append(GLib.markup_escape_text(f"Style: {item.entry_style}"))
        row.set_subtitle(" • ".join(subtitle_parts))

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

    # --- Empty state ---------------------------------------------------------

    def _update_empty_state(self):
        """Show the empty-state page when there is nothing to display.

        The revealer overlays the whole list, so it must only be an input
        target while actually revealed; otherwise it would swallow every
        click and scroll meant for the list beneath it.
        """
        empty = self.list_store.get_n_items() == 0
        self.empty_revealer.set_reveal_child(empty)
        self.empty_revealer.set_can_target(empty)

    # --- Search ---------------------------------------------------------------

    def set_search_visible(self, visible: bool):
        """Reveal/hide the search bar (clearing highlights when hidden)."""
        self.search_bar.set_search_mode(visible)
        if visible:
            self.search_entry.grab_focus()
        elif self.search_entry.get_text():
            # Triggers 'changed' -> clears highlights and matches.
            self.search_entry.set_text('')

    def _on_search_changed(self, entry):
        term = entry.get_text().strip()
        if term == self._search_term:
            return
        self._search_term = term
        self._recompute_search()

    def _recompute_search(self, jump=True, update_items=True):
        """Recompute match positions for the current search term.

        With ``jump`` the first match is selected and scrolled to; otherwise
        the match closest to the current selection is kept.
        """
        term = self._search_term
        store = self.list_store
        n = store.get_n_items()
        if self.document and term:
            # Scan through the store items (kept in sync with the document by
            # the incremental update methods) using the cached lowercased
            # clean text (tags stripped), so keystrokes stay cheap on long
            # documents and matches reflect what the rows actually show.
            needle = term.lower()
            matches = []
            for i in range(n):
                item = store.get_item(i)
                low = item._lower_text
                if low is None:
                    low = item._clean_text.lower()
                    item._lower_text = low
                if needle in low:
                    matches.append(i)
            self._search_matches = matches
        else:
            self._search_matches = []

        if update_items:
            # Only matching rows render differently, so only items entering or
            # leaving the match set need the term; rows bound to the view
            # re-render via notify, everything else picks it up on bind.
            n = self.list_store.get_n_items()
            for pos in self._highlighted_positions | set(self._search_matches):
                if 0 <= pos < n:
                    self.list_store.get_item(pos).search_term = term
        self._highlighted_positions = set(self._search_matches)

        if self._search_matches:
            if not jump:
                selected = self.get_selected_position()
                if selected in self._search_matches:
                    self._current_match = self._search_matches.index(selected)
            else:
                self._current_match = 0
            if not (0 <= self._current_match < len(self._search_matches)):
                self._current_match = 0
            if jump:
                self.select_entry(self._search_matches[self._current_match])
        else:
            self._current_match = -1

        self._update_match_label()

    def _sync_search_after_change(self):
        """Re-sync match positions after the document structure changed."""
        if not self._search_term:
            return
        self._recompute_search(jump=False, update_items=False)

    def _search_move(self, delta: int):
        """Move to the next (1) or previous (-1) match, wrapping around."""
        if not self._search_matches:
            return
        self._current_match = (self._current_match + delta) % len(self._search_matches)
        self.select_entry(self._search_matches[self._current_match])
        self._update_match_label()
        self.search_entry.grab_focus()

    def _on_search_key_pressed(self, controller, keyval, keycode, state):
        """Enter/Shift+Enter jump to the next/previous match."""
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_ISO_Enter):
            self._search_move(-1 if state & Gdk.ModifierType.SHIFT_MASK else 1)
            return True
        return False

    def _update_match_label(self):
        """Update the "n of m" counter and navigation button sensitivity."""
        has_matches = bool(self._search_matches)
        self.search_prev_button.set_sensitive(has_matches)
        self.search_next_button.set_sensitive(has_matches)
        if not self._search_term:
            self.match_label.set_text("")
        elif has_matches:
            self.match_label.set_text(
                f"{self._current_match + 1} of {len(self._search_matches)}")
        else:
            self.match_label.set_text("No results")

    # --- Input ----------------------------------------------------------------

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
        """Show the persistent context menu at the click location."""
        if self.list_store.get_n_items() == 0:
            return
        rect = Gdk.Rectangle()
        rect.x = x
        rect.y = y
        rect.width = 1
        rect.height = 1
        self.context_popover.set_pointing_to(rect)
        self.context_popover.popup()
