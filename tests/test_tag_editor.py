"""GTK widget tests for the visual ASS override-tag editor and clean list.

Covers the editor panel's Formatting expander (tag rows, recomposition, the
no-op-load silence invariant, SRT hiding) and the subtitle list's clean-text
display/search. Requires a display; skipped automatically when none is
available.
"""

import pytest
from gsub.models import SubtitleDocument, SubtitleEntry, SubtitleFormat, TimeCode
from gsub.resources import register_resources

try:
    from gi.repository import Adw, Gdk, GLib, Gtk
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

EXAMPLE_TEXT = (
    '{\\fnGeorgia\\fs12\\shad1\\blur1\\bord.1\\3c&HC85695&\\c&H25292D&'
    '\\4c&H5AF786&\\pos(338,103)}الحلقة 13'
)

# A real dialogue line from a user's file: a leading block plus a {\fs22}
# block starting the SECOND line (the \N is already a real newline in the
# entry model). The RTL text is intentional — mind the byte order.
USER_LINE = (
    '{\\fad(860,920)\\pos(450,265)\\fnTimes New Roman\\b1\\fs14\\shad0\\blur4'
    '\\bord1\\3c&H383E3F&}أستاذة في أكاديميّة ريغاردين السّحريّة'
    '\n{\\fs22}إيليزا نوسفيرات'
)
USER_LEAD = (
    '{\\fad(860,920)\\pos(450,265)\\fnTimes New Roman\\b1\\fs14\\shad0\\blur4'
    '\\bord1\\3c&H383E3F&}'
)
USER_LINE_1 = 'أستاذة في أكاديميّة ريغاردين السّحريّة'
USER_LINE_2 = 'إيليزا نوسفيرات'


def _make_entry(text, index=1):
    return SubtitleEntry(
        index=index,
        start_time=TimeCode(0, 0, 1, 0),
        end_time=TimeCode(0, 0, 3, 0),
        text=text,
        style='Default',
    )


def _make_panel(fmt=SubtitleFormat.ASS):
    from gsub.widgets.editor_panel import EditorPanel

    window = Gtk.Window()
    panel = EditorPanel()
    window.set_child(panel)
    panel.set_document_context(fmt, ['Default'])
    return panel


def _wait_debounce(panel):
    """Iterate the main loop until the pending text change is emitted."""
    ctx = GLib.MainContext.default()
    deadline = 20
    while panel._text_change_timeout_id is not None and deadline > 0:
        ctx.iteration(True)
        deadline -= 1


def _find_row(panel, title):
    for row in panel.tag_editor.get_rows():
        if row.get_title() == title:
            return row
    return None


def _find_trash_button(widget):
    """Locate the row's user-trash-symbolic remove button in the widget tree."""
    if isinstance(widget, Gtk.Button) and widget.get_icon_name() == 'user-trash-symbolic':
        return widget
    child = widget.get_first_child()
    while child is not None:
        found = _find_trash_button(child)
        if found is not None:
            return found
        child = child.get_next_sibling()
    return None


def _buffer_text(panel):
    start = panel.text_buffer.get_start_iter()
    end = panel.text_buffer.get_end_iter()
    return panel.text_buffer.get_text(start, end, False)


class TestEditorPanelTagEditing:
    def test_set_entry_shows_clean_text_and_tag_rows(self):
        panel = _make_panel()
        panel.set_entry(_make_entry(EXAMPLE_TEXT), 0)

        assert _buffer_text(panel) == 'الحلقة 13'
        assert panel.formatting_expander.get_visible()
        # One row per tag: fn, fs, shad, blur, bord, 3c, c, 4c, pos.
        assert len(panel.tag_editor.get_rows()) == 9
        assert panel.formatting_expander.get_subtitle() == '9 tags'

    def test_no_op_load_emits_nothing_and_roundtrips(self):
        panel = _make_panel()
        emitted = []
        panel.connect('text-changed', lambda w, p, t: emitted.append(t))
        panel.set_entry(_make_entry(EXAMPLE_TEXT), 0)

        assert panel._compose_text() == EXAMPLE_TEXT
        ctx = GLib.MainContext.default()
        for _ in range(10):
            ctx.iteration(False)
        assert emitted == []

    def test_plain_ass_line_keeps_formatting_visible(self):
        panel = _make_panel()
        entry = _make_entry('plain line')
        panel.set_entry(entry, 0)

        assert panel.formatting_expander.get_visible()
        assert panel.tag_editor.get_rows() == []
        assert panel.formatting_expander.get_subtitle() == 'No tags'
        assert _buffer_text(panel) == 'plain line'
        assert panel._compose_text() == 'plain line'

    def test_srt_document_hides_formatting(self):
        panel = _make_panel(fmt=SubtitleFormat.SRT)
        emitted = []
        panel.connect('text-changed', lambda w, p, t: emitted.append(t))
        panel.set_entry(_make_entry(EXAMPLE_TEXT), 0)

        assert not panel.formatting_expander.get_visible()
        # SRT keeps the raw text (blocks included) in the buffer.
        assert _buffer_text(panel) == EXAMPLE_TEXT
        ctx = GLib.MainContext.default()
        for _ in range(10):
            ctx.iteration(False)
        assert emitted == []

    def test_fs_edit_emits_recomposed_text(self):
        panel = _make_panel()
        emitted = []
        panel.connect('text-changed', lambda w, p, t: emitted.append((p, t)))
        panel.set_entry(_make_entry(EXAMPLE_TEXT), 0)

        row = _find_row(panel, 'Size')
        assert isinstance(row, Adw.SpinRow)
        row.set_value(48)
        _wait_debounce(panel)

        assert len(emitted) == 1
        position, text = emitted[0]
        assert position == 0
        assert '\\fs48' in text
        assert '\\pos(338,103)' in text
        assert '\\3c&HC85695&' in text
        assert text.endswith('الحلقة 13')

        # Full round-trip: the recomposed text parses to the same tags with
        # the edit applied.
        from gsub.parsers.ass_tags import extract_override_tags

        tags = {t.name: t for t in extract_override_tags(text)}
        assert tags['fs'].args == ['48']
        assert tags['pos'].args == ['338', '103']
        assert tags['3c'].args == ['&HC85695&']

    def test_removing_a_tag_drops_exactly_that_tag(self):
        panel = _make_panel()
        emitted = []
        panel.connect('text-changed', lambda w, p, t: emitted.append(t))
        panel.set_entry(_make_entry(EXAMPLE_TEXT), 0)

        row = _find_row(panel, 'Blur')
        button = _find_trash_button(row)
        button.emit('clicked')
        _wait_debounce(panel)

        assert len(emitted) == 1
        text = emitted[0]
        assert '\\blur1' not in text
        assert '\\shad1' in text
        assert '\\bord.1' in text
        assert panel.formatting_expander.get_subtitle() == '8 tags'

    def test_adding_bold_inserts_tag(self):
        panel = _make_panel()
        emitted = []
        panel.connect('text-changed', lambda w, p, t: emitted.append(t))
        panel.set_entry(_make_entry(EXAMPLE_TEXT), 0)

        panel.tag_editor.add_tag('\\b1')
        _wait_debounce(panel)

        assert emitted and '\\b1' in emitted[-1]
        assert '\\pos(338,103)' in emitted[-1]
        assert panel.formatting_expander.get_subtitle() == '10 tags'

    def test_switch_row_toggles_bold(self):
        panel = _make_panel()
        panel.set_entry(_make_entry('{\\b1}bold text'), 0)

        row = _find_row(panel, 'Bold')
        assert isinstance(row, Adw.SwitchRow)
        assert row.get_active()
        emitted = []
        panel.connect('text-changed', lambda w, p, t: emitted.append(t))
        row.set_active(False)
        _wait_debounce(panel)

        assert emitted and emitted[-1] == '{\\b0}bold text'

    def test_color_row_roundtrip(self):
        panel = _make_panel()
        panel.set_entry(_make_entry('{\\3c&HC85695&}text'), 0)

        row = _find_row(panel, 'Outline (3c)')
        assert row is not None
        # Untouched: byte-exact round-trip including the original spelling.
        assert panel._compose_text() == '{\\3c&HC85695&}text'

    def test_unknown_tag_edited_raw(self):
        panel = _make_panel()
        emitted = []
        panel.connect('text-changed', lambda w, p, t: emitted.append(t))
        panel.set_entry(_make_entry('{\\t(\\fs20,\\fs30,1)}text'), 0)

        rows = panel.tag_editor.get_rows()
        assert len(rows) == 1
        assert isinstance(rows[0], Adw.EntryRow)
        assert rows[0].get_text() == '\\t(\\fs20,\\fs30,1)'

        rows[0].set_text('\\t(\\fs30,\\fs40,1)')
        _wait_debounce(panel)
        assert emitted[-1] == '{\\t(\\fs30,\\fs40,1)}text'

        # Invalid input (unbalanced parenthesis) keeps the last good value.
        rows[0].set_text('\\t(\\fs30,\\fs40,1')
        _wait_debounce(panel)
        assert emitted[-1] == '{\\t(\\fs30,\\fs40,1)}text'

    def test_midline_block_stays_in_buffer(self):
        panel = _make_panel()
        panel.set_entry(_make_entry('{\\b1}before{\\i1}after'), 0)

        assert _buffer_text(panel) == 'before{\\i1}after'
        assert panel._compose_text() == '{\\b1}before{\\i1}after'
        # The mid-line block is highlighted with the inline tag.
        from gsub.parsers.ass_tags import BLOCK_PATTERN

        text = _buffer_text(panel)
        match = BLOCK_PATTERN.search(text)
        assert match is not None
        tag_start = panel.text_buffer.get_iter_at_offset(match.start())
        assert tag_start.has_tag(panel._inline_tag)

    def test_user_line_two_clean_lines_two_groups(self):
        """The reported line: {\fs22} starts line 2, so it gets its own group."""
        panel = _make_panel()
        emitted = []
        panel.connect('text-changed', lambda w, p, t: emitted.append(t))
        panel.set_entry(_make_entry(USER_LINE), 0)

        # The buffer shows clean text on every line — no braces at all.
        assert _buffer_text(panel) == USER_LINE_1 + '\n' + USER_LINE_2
        assert '{' not in _buffer_text(panel)

        # Group 1: the leading block's 9 rows (fad, pos, fn, b, fs, shad,
        # blur, bord, 3c). Group 2: one row for {\fs22}, labeled "Line 2".
        assert len(panel.tag_editor.get_rows()) == 9
        assert len(panel._tag_groups) == 1
        group = panel._tag_groups[0]
        assert group.header.get_title() == 'Line 2 tags'
        assert group.offset == len(USER_LINE_1) + 1
        rows = group.editor.get_rows()
        assert len(rows) == 1
        assert isinstance(rows[0], Adw.SpinRow)
        assert rows[0].get_title() == 'Size'
        assert panel.formatting_expander.get_subtitle() == '10 tags'

        # No-op load: byte-identical recomposition, nothing emitted.
        assert panel._compose_text() == USER_LINE
        ctx = GLib.MainContext.default()
        for _ in range(10):
            ctx.iteration(False)
        assert emitted == []

    def test_second_group_edit_keeps_block_on_its_line(self):
        panel = _make_panel()
        emitted = []
        panel.connect('text-changed', lambda w, p, t: emitted.append(t))
        panel.set_entry(_make_entry(USER_LINE), 0)

        row = panel._tag_groups[0].editor.get_rows()[0]
        row.set_value(48)
        _wait_debounce(panel)

        assert len(emitted) == 1
        # Full expected string: the leading block is untouched and the
        # edited {\fs48} stays at the start of the second line.
        assert emitted[0] == USER_LINE.replace('\\fs22}', '\\fs48}')
        assert panel._compose_text() == USER_LINE.replace('\\fs22}', '\\fs48}')

    def test_insert_before_block_offset_shifts_anchor(self):
        panel = _make_panel()
        panel.set_entry(_make_entry(USER_LINE), 0)

        buffer = panel.text_buffer
        buffer.insert(buffer.get_iter_at_offset(0), 'X')
        # The anchor moved past the insertion: the block still starts the
        # (now longer) second line, right after the newline.
        assert panel._tag_groups[0].offset == len(USER_LINE_1) + 2
        expected = USER_LEAD + 'X' + USER_LINE_1 + '\n{\\fs22}' + USER_LINE_2
        assert panel._compose_text() == expected
        _wait_debounce(panel)

    def test_deleting_newline_clamps_block_anchor(self):
        panel = _make_panel()
        panel.set_entry(_make_entry(USER_LINE), 0)

        buffer = panel.text_buffer
        newline = len(USER_LINE_1)
        buffer.delete(buffer.get_iter_at_offset(newline),
                      buffer.get_iter_at_offset(newline + 1))
        # The block survives (clamped to the deletion start) and the
        # recomposition stays well-formed with the lines merged.
        assert panel._tag_groups[0].offset == newline
        assert panel._compose_text() == USER_LINE.replace('\n', '')
        _wait_debounce(panel)

    def test_deleting_range_spanning_anchor_clamps_block(self):
        panel = _make_panel()
        panel.set_entry(_make_entry(USER_LINE), 0)

        buffer = panel.text_buffer
        start = len(USER_LINE_1) - 2
        buffer.delete(buffer.get_iter_at_offset(start),
                      buffer.get_iter_at_offset(start + 5))
        # The anchor clamps to the deletion start and the block survives.
        assert panel._tag_groups[0].offset == start
        expected = (USER_LEAD + USER_LINE_1[:-2]
                    + '{\\fs22}' + USER_LINE_2[2:])
        assert panel._compose_text() == expected
        _wait_debounce(panel)

    def test_mixed_extracted_and_inline_blocks_roundtrip(self):
        """Line-start blocks are extracted while mid-word blocks stay inline."""
        panel = _make_panel()
        emitted = []
        panel.connect('text-changed', lambda w, p, t: emitted.append(t))
        text = '{\\b1}before{\\i1}mid\n{\\u1}after'
        panel.set_entry(_make_entry(text), 0)

        assert _buffer_text(panel) == 'before{\\i1}mid\nafter'
        assert len(panel._tag_groups) == 1
        assert panel._tag_groups[0].header.get_title() == 'Line 2 tags'
        # The leftover mid-word block keeps its inline highlight.
        from gsub.parsers.ass_tags import BLOCK_PATTERN

        match = BLOCK_PATTERN.search(_buffer_text(panel))
        tag_start = panel.text_buffer.get_iter_at_offset(match.start())
        assert tag_start.has_tag(panel._inline_tag)

        assert panel._compose_text() == text
        ctx = GLib.MainContext.default()
        for _ in range(10):
            ctx.iteration(False)
        assert emitted == []

    def test_adjacent_line_start_blocks_get_separate_groups(self):
        panel = _make_panel()
        emitted = []
        panel.connect('text-changed', lambda w, p, t: emitted.append(t))
        panel.set_entry(_make_entry('a\n{\\b1}{\\i1}c'), 0)

        assert _buffer_text(panel) == 'a\nc'
        assert len(panel._tag_groups) == 2
        assert [g.header.get_title() for g in panel._tag_groups] == [
            'Line 2 tags', 'Line 2 tags']
        assert [g.editor.get_tag_count() for g in panel._tag_groups] == [1, 1]
        assert panel._compose_text() == 'a\n{\\b1}{\\i1}c'
        ctx = GLib.MainContext.default()
        for _ in range(10):
            ctx.iteration(False)
        assert emitted == []

    def test_removing_last_tag_of_second_group_drops_block(self):
        panel = _make_panel()
        emitted = []
        panel.connect('text-changed', lambda w, p, t: emitted.append(t))
        panel.set_entry(_make_entry(USER_LINE), 0)

        row = panel._tag_groups[0].editor.get_rows()[0]
        _find_trash_button(row).emit('clicked')
        _wait_debounce(panel)

        # The {} is gone entirely: the second line is clean.
        assert emitted and emitted[-1] == USER_LEAD + USER_LINE_1 + '\n' + USER_LINE_2
        assert panel._tag_groups[0].header.get_parent() is None
        assert panel.formatting_expander.get_subtitle() == '9 tags'

    def test_switching_entries_does_not_emit(self):
        panel = _make_panel()
        emitted = []
        panel.connect('text-changed', lambda w, p, t: emitted.append(t))
        panel.set_entry(_make_entry(EXAMPLE_TEXT), 0)
        panel.set_entry(_make_entry('other'), 1)
        panel.set_entry(_make_entry(EXAMPLE_TEXT), 0)

        ctx = GLib.MainContext.default()
        for _ in range(10):
            ctx.iteration(False)
        assert emitted == []
        assert panel._compose_text() == EXAMPLE_TEXT


class TestSubtitleListCleanDisplay:
    def _make_view(self, texts):
        from gsub.widgets.subtitle_list import SubtitleListView

        doc = SubtitleDocument(format=SubtitleFormat.ASS)
        doc.entries = [_make_entry(t, i + 1) for i, t in enumerate(texts)]
        doc.reindex()

        window = Gtk.Window()
        view = SubtitleListView()
        window.set_child(view)
        view.set_document(doc)
        return view

    def test_row_title_is_clean_text(self):
        view = self._make_view([EXAMPLE_TEXT])
        item = view.list_store.get_item(0)

        assert item.entry_text == 'الحلقة 13'
        # The raw text stays on the entry model untouched.
        assert item._text == EXAMPLE_TEXT
        assert view.document.entries[0].text == EXAMPLE_TEXT

    def test_search_matches_clean_text_only(self):
        view = self._make_view([EXAMPLE_TEXT, 'Georgia peaches'])

        view.search_entry.set_text('الحلقة')
        assert view._search_matches == [0]

        view.search_entry.set_text('Georgia')
        assert view._search_matches == [1]

    def test_search_matches_midline_text(self):
        view = self._make_view(['{\b1}hello world{\b0}'])
        view.search_entry.set_text('hello')
        assert view._search_matches == [0]

    def test_long_clean_text_truncated(self):
        view = self._make_view(['{\\b1}' + 'x' * 200])
        item = view.list_store.get_item(0)
        assert item.entry_text == 'x' * 120
