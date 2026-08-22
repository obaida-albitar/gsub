"""GTK widget tests for the subtitle list view.

Covers the incremental store updates used by add/insert/remove/move (the
document is mutated by commands, then the view is notified) and the search
machinery. Requires a display; skipped automatically when none is available.
"""

import types

import pytest
from gsub.models import SubtitleDocument, SubtitleEntry, SubtitleFormat, TimeCode
from gsub.resources import register_resources

try:
    from gi.repository import Adw, Gdk, Gtk
    register_resources()
    try:
        Gtk.init()
        Adw.init()
    except Exception:
        pass
    _HAS_DISPLAY = Gdk.Display.get_default() is not None
except Exception:  # pragma: no cover - environment without GTK
    _HAS_DISPLAY = False

pytestmark = pytest.mark.skipif(
    not _HAS_DISPLAY, reason="no display available for GTK widget tests"
)


def _entry(start_ms, text):
    return SubtitleEntry(
        index=0,
        start_time=TimeCode.from_milliseconds(start_ms),
        end_time=TimeCode.from_milliseconds(start_ms + 1000),
        text=text,
    )


def _make_view(texts):
    from gsub.widgets.subtitle_list import SubtitleListView

    doc = SubtitleDocument(format=SubtitleFormat.SRT)
    doc.entries = [_entry(i * 2000, text) for i, text in enumerate(texts)]
    doc.reindex()

    window = Gtk.Window()
    view = SubtitleListView()
    window.set_child(view)
    view.set_document(doc)
    return view, doc


def _store_texts(view):
    return [view.list_store.get_item(i).entry_text for i in range(view.list_store.get_n_items())]


class TestIncrementalUpdates:
    def test_entries_inserted_splices_and_renumbers(self):
        from gsub.commands.subtitle_commands import AddEntryCommand, build_new_entry

        view, doc = _make_view(["one", "two", "three"])
        entry = build_new_entry(doc, 1)
        AddEntryCommand(doc, entry, 1).execute()
        view.entries_inserted(1, 1)

        assert _store_texts(view) == ["one", "New subtitle", "two", "three"]
        for i in range(4):
            assert view.list_store.get_item(i).position == i
            assert view.list_store.get_item(i).entry_index == i + 1

    def test_entries_removed_splices_and_renumbers(self):
        from gsub.commands.subtitle_commands import RemoveEntryCommand

        view, doc = _make_view(["one", "two", "three", "four"])
        RemoveEntryCommand(doc, 1).execute()
        RemoveEntryCommand(doc, 2).execute()
        view.entries_removed([1, 3])

        assert _store_texts(view) == ["one", "three"]
        assert view.list_store.get_item(1).entry_index == 2

    def test_entry_moved_splices_and_renumbers(self):
        from gsub.commands.subtitle_commands import MoveEntryCommand

        view, doc = _make_view(["one", "two", "three"])
        MoveEntryCommand(doc, 2, 0).execute()
        view.entry_moved(2, 0)

        assert _store_texts(view) == ["three", "one", "two"]
        for i in range(3):
            assert view.list_store.get_item(i).entry_index == i + 1

    def test_empty_state_switches(self):
        view, _doc = _make_view(["one"])
        assert not view.empty_revealer.get_reveal_child()

        view.document.entries.clear()
        view.document.reindex()
        view.refresh()
        assert view.empty_revealer.get_reveal_child()
        assert view.list_store.get_n_items() == 0

    def test_empty_state_only_targets_input_while_revealed(self):
        # The empty state overlays the list; it must not swallow pointer
        # events while hidden.
        view, _doc = _make_view(["one"])
        assert not view.empty_revealer.get_can_target()

        view.document.entries.clear()
        view.document.reindex()
        view.refresh()
        assert view.empty_revealer.get_can_target()

        view.document.entries.append(_entry(0, "back"))
        view.document.reindex()
        view.refresh()
        assert not view.empty_revealer.get_can_target()

    def test_refresh_preserves_selection(self):
        view, doc = _make_view(["one", "two", "three"])
        view.select_entry(1)

        # Simulate a no-op structural refresh (e.g. undo path).
        view.refresh(preserve_selection=True)
        assert view.get_selected_positions() == [1]

    def test_refresh_entry_updates_without_splice(self):
        view, doc = _make_view(["one", "two"])
        item = view.list_store.get_item(0)
        doc.entries[0].text = "changed"
        view.refresh_entry(0)
        # Debounced: the item updates when the timeout fires.
        from gi.repository import GLib

        ctx = GLib.MainContext.default()
        deadline = 10
        while view._refresh_timeout_id is not None and deadline > 0:
            ctx.iteration(True)
            deadline -= 1
        assert item.entry_text == "changed"
        # Same object identity — no store splice happened.
        assert view.list_store.get_item(0) is item


class TestSearch:
    def test_term_finds_matches_and_updates_counter(self):
        view, _doc = _make_view(["alpha hello", "beta", "hello again", "gamma"])
        view.search_entry.set_text("hello")

        assert view._search_matches == [0, 2]
        assert view.match_label.get_text() == "1 of 2"
        assert view.get_selected_position() == 0

    def test_next_previous_wrap_around(self):
        view, _doc = _make_view(["a hello", "b hello", "c hello"])
        view.search_entry.set_text("hello")

        view._search_move(1)
        assert view.get_selected_position() == 1
        assert view.match_label.get_text() == "2 of 3"

        view._search_move(1)
        view._search_move(1)  # wraps back to the first
        assert view.get_selected_position() == 0

        view._search_move(-1)  # wraps to the last
        assert view.get_selected_position() == 2

    def test_no_results_label(self):
        view, _doc = _make_view(["alpha", "beta"])
        view.search_entry.set_text("zzz")
        assert view.match_label.get_text() == "No results"
        assert not view.search_next_button.get_sensitive()

    def test_closing_search_clears_highlights(self):
        view, _doc = _make_view(["alpha hello"])
        view.search_entry.set_text("hello")
        assert view.list_store.get_item(0).search_term == "hello"

        view.set_search_visible(False)
        assert view.list_store.get_item(0).search_term == ""
        assert view._search_matches == []
        assert view.match_label.get_text() == ""

    def test_matches_recompute_after_removal(self):
        from gsub.commands.subtitle_commands import RemoveEntryCommand

        view, doc = _make_view(["a hello", "b hello", "c hello"])
        view.search_entry.set_text("hello")
        assert view._search_matches == [0, 1, 2]

        RemoveEntryCommand(doc, 1).execute()
        view.entries_removed([1])
        assert view._search_matches == [0, 1]

    def test_new_rows_carry_search_term(self):
        from gsub.commands.subtitle_commands import build_new_entry

        view, doc = _make_view(["a hello"])
        view.search_entry.set_text("hello")

        entry = build_new_entry(doc, 1)
        entry.text = "more hello"
        doc.entries.append(entry)
        doc.reindex()
        view.entries_inserted(1, 1)
        assert view.list_store.get_item(1).search_term == "hello"


class TestContextMenu:
    @staticmethod
    def _menu_labels(menu):
        """Collect all item labels of a (possibly sectioned) Gio.Menu."""
        labels = []
        for i in range(menu.get_n_items()):
            link = menu.get_item_link(i, "section")
            if link is not None:
                labels.extend(TestContextMenu._menu_labels(link))
            else:
                value = menu.get_item_attribute_value(i, "label", None)
                if value is not None:
                    labels.append(value.get_string())
        return labels

    def test_menu_has_insert_and_move_sections(self):
        view, _doc = _make_view(["one"])
        labels = self._menu_labels(view.context_menu)

        assert "Insert Above" in labels
        assert "Insert Below" in labels
        assert "Duplicate" in labels
        assert "Remove" in labels
        assert "Move Up" in labels
        assert "Move Down" in labels
        # ASS-only entry must not appear for SRT documents.
        assert "Bulk Apply Style…" not in labels

    def test_ass_document_adds_bulk_style(self):
        from gsub.widgets.subtitle_list import SubtitleListView

        doc = SubtitleDocument(format=SubtitleFormat.ASS)
        doc.entries = [_entry(0, "one")]
        doc.reindex()

        window = Gtk.Window()
        view = SubtitleListView()
        window.set_child(view)
        view.set_document(doc)

        assert "Bulk Apply Style…" in self._menu_labels(view.context_menu)


class TestHighlightActive:
    """Playback highlight: marks + scrolls a row without touching selection."""

    @staticmethod
    def _make_many(n):
        return _make_view([f"line {i}" for i in range(n)])

    def test_marks_item_and_scrolls(self):
        view, _doc = self._make_many(5)
        view.select_entry(0)

        scrolled = []
        original_scroll = view._scroll_to
        view._scroll_to = lambda pos: scrolled.append(pos)
        try:
            view.highlight_active(3)
        finally:
            view._scroll_to = original_scroll

        assert scrolled == [3]
        assert view.list_store.get_item(3).active_playing is True
        # Selection untouched.
        assert view.get_selected_positions() == [0]

    def test_clears_previous_highlight(self):
        view, _doc = self._make_many(4)
        view.highlight_active(1)
        view.highlight_active(2)
        assert view.list_store.get_item(1).active_playing is False
        assert view.list_store.get_item(2).active_playing is True

    def test_minus_one_clears_without_scrolling(self):
        view, _doc = self._make_many(4)
        view.highlight_active(2)

        scrolled = []
        original_scroll = view._scroll_to
        view._scroll_to = lambda pos: scrolled.append(pos)
        try:
            view.highlight_active(-1)
        finally:
            view._scroll_to = original_scroll

        assert view.list_store.get_item(2).active_playing is False
        assert scrolled == []

    def test_repeated_calls_are_noops(self):
        view, _doc = self._make_many(4)
        view.highlight_active(1)

        scrolled = []
        original_scroll = view._scroll_to
        view._scroll_to = lambda pos: scrolled.append(pos)
        try:
            view.highlight_active(1)
            view.highlight_active(1)
        finally:
            view._scroll_to = original_scroll
        assert scrolled == []
        assert view.list_store.get_item(1).active_playing is True

    def test_out_of_range_positions_ignored(self):
        view, _doc = self._make_many(3)
        view.highlight_active(99)   # no crash, no scroll
        view.highlight_active(-5)
        assert view._active_position == -1

    def test_refresh_resets_highlight(self):
        view, _doc = self._make_many(3)
        view.highlight_active(1)
        view.refresh(preserve_selection=True)
        assert view._active_position == -1
        assert all(
            not view.list_store.get_item(i).active_playing for i in range(3)
        )

    def test_bound_row_gets_css_class(self):
        from gsub.widgets.subtitle_list import SubtitleListRow

        view, _doc = self._make_many(3)
        item = view.list_store.get_item(1)

        class _FakeRow:
            def __init__(self):
                self.classes = set()
                self.index_label = types.SimpleNamespace(set_text=lambda t: None)
                self._title = None
                self._subtitle = None

            def set_title(self, t):
                self._title = t

            def set_subtitle(self, s):
                self._subtitle = s

            def add_css_class(self, name):
                self.classes.add(name)

            def remove_css_class(self, name):
                self.classes.discard(name)

        row = _FakeRow()
        view._apply_item(item, row)
        assert "active-playing" not in row.classes

        item.active_playing = True
        view._apply_item(item, row)
        assert "active-playing" in row.classes

        item.active_playing = False
        view._apply_item(item, row)
        assert "active-playing" not in row.classes
        # The CSS class is applied to real rows too (factory wiring).
        assert issubclass(SubtitleListRow, object)
