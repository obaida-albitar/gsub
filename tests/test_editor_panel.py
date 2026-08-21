"""GTK widget tests for the editor panel's non-tag behaviour.

Covers the document format context (style dropdown vs SRT hiding), timing
spin population and the debounced timing-changed / style-changed /
position-changed signals, and clear(). The Formatting/tag-row behaviour is
covered separately in test_tag_editor.py.

Requires a display; skipped automatically when none is available.
"""

import pytest
from subtitle_editor.models import SubtitleEntry, SubtitleFormat, TimeCode
from subtitle_editor.resources import register_resources

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


def _entry(text="Hello", start_ms=61_500, end_ms=63_000, **kwargs):
    return SubtitleEntry(
        index=1,
        start_time=TimeCode.from_milliseconds(start_ms),
        end_time=TimeCode.from_milliseconds(end_ms),
        text=text,
        **kwargs,
    )


def _panel(fmt=SubtitleFormat.SRT, styles=None):
    from subtitle_editor.widgets.editor_panel import EditorPanel

    window = Gtk.Window()
    panel = EditorPanel()
    window.set_child(panel)
    panel.set_document_context(fmt, styles or ["Default"])
    return panel


def _pump_until(source_id_attr, panel, timeout_s=3.0):
    """Iterate the main loop until the debounce timeout fires.

    Uses a wall-clock deadline (not an iteration budget) so leftover
    sources from earlier test suites cannot starve the wait.
    """
    import time

    ctx = GLib.MainContext.default()
    deadline = time.monotonic() + timeout_s
    while getattr(panel, source_id_attr) is not None \
            and time.monotonic() < deadline:
        ctx.iteration(True)


@pytest.mark.integration
class TestDocumentContext:
    def test_srt_hides_ass_rows(self):
        panel = _panel(SubtitleFormat.SRT)
        assert panel.style_row.get_visible() is False
        assert panel.position_group.get_visible() is False

    def test_ass_shows_style_row_and_position_group(self):
        panel = _panel(SubtitleFormat.ASS, ["Default", "Title", "Signs"])
        assert panel.style_row.get_visible() is True
        assert panel.position_group.get_visible() is True
        model_names = [panel.style_model.get_string(i)
                       for i in range(panel.style_model.get_n_items())]
        assert model_names == ["Default", "Title", "Signs"]

    def test_style_list_is_replaced_between_documents(self):
        panel = _panel(SubtitleFormat.ASS, ["Default", "Title"])
        panel.set_document_context(SubtitleFormat.ASS, ["Only"])
        model_names = [panel.style_model.get_string(i)
                       for i in range(panel.style_model.get_n_items())]
        assert model_names == ["Only"]

    def test_null_style_list_falls_back_to_default(self):
        panel = _panel(SubtitleFormat.ASS, None)
        model_names = [panel.style_model.get_string(i)
                       for i in range(panel.style_model.get_n_items())]
        assert model_names == ["Default"]


@pytest.mark.integration
class TestSetEntry:
    def test_timing_spins_populated(self):
        panel = _panel()
        panel.set_entry(_entry(), 0)

        assert panel.start_minute.get_value_as_int() == 1
        assert panel.start_second.get_value_as_int() == 1
        assert panel.start_milli.get_value_as_int() == 500
        assert panel.end_second.get_value_as_int() == 3
        assert panel.end_milli.get_value_as_int() == 0

    def test_duration_and_expander_subtitles(self):
        panel = _panel()
        panel.set_entry(_entry(start_ms=61_000, end_ms=62_500), 0)

        assert panel.duration_row.get_subtitle() == "1.500 seconds"
        assert panel.start_expander.get_subtitle() == "00:01:01.000"
        assert panel.end_expander.get_subtitle() == "00:01:02.500"

    def test_becomes_sensitive(self):
        panel = _panel()
        assert panel.get_sensitive() is False
        panel.set_entry(_entry(), 0)
        assert panel.get_sensitive() is True

    def test_ass_entry_selects_style_and_margins(self):
        panel = _panel(SubtitleFormat.ASS, ["Default", "Title"])
        entry = _entry(style="Title", margin_l=12, margin_r=34, margin_v=56)

        panel.set_entry(entry, 0)

        assert panel.style_row.get_selected() == 1
        assert panel.margin_l_spin.get_value_as_int() == 12
        assert panel.margin_r_spin.get_value_as_int() == 34
        assert panel.margin_v_spin.get_value_as_int() == 56

    def test_ass_entry_with_unknown_style_falls_back_to_first(self):
        panel = _panel(SubtitleFormat.ASS, ["Default", "Title"])
        panel.set_entry(_entry(style="Missing"), 0)
        assert panel.style_row.get_selected() == 0

    def test_srt_entry_keeps_formatting_hidden(self):
        panel = _panel(SubtitleFormat.SRT)
        panel.set_entry(_entry(text="{\\i1}styled{\\i0}"), 0)
        assert panel.formatting_expander.get_visible() is False


@pytest.mark.integration
class TestTimingChangedSignal:
    def test_spin_edit_emits_debounced_timing(self):
        panel = _panel()
        panel.set_entry(_entry(start_ms=61_500, end_ms=63_000), 0)

        emitted = []
        panel.connect("timing-changed",
                      lambda w, pos, start, end: emitted.append((pos, start, end)))

        panel.start_second.set_value(9)
        panel.end_milli.set_value(250)
        _pump_until("_timing_changed_id", panel)

        assert len(emitted) == 1
        pos, start, end = emitted[0]
        assert pos == 0
        # 61.5s -> minute 1, second 9 => 69_000 ms; end 63_000 -> 63_250 ms.
        assert start.total_milliseconds == 69_500
        assert end.total_milliseconds == 63_250

    def test_loading_entry_does_not_emit(self):
        panel = _panel()
        emitted = []
        panel.connect("timing-changed",
                      lambda w, pos, start, end: emitted.append((pos, start, end)))

        panel.set_entry(_entry(), 0)
        _pump_until("_timing_changed_id", panel, timeout_s=0.4)

        assert emitted == []

    def test_no_entry_no_emission(self):
        panel = _panel()
        emitted = []
        panel.connect("timing-changed",
                      lambda w, pos, start, end: emitted.append(pos))
        panel.clear()

        panel.start_hour.set_value(2)
        _pump_until("_timing_changed_id", panel, timeout_s=0.4)

        assert emitted == []

    def test_rapid_edits_coalesce_into_one_emission(self):
        panel = _panel()
        panel.set_entry(_entry(), 0)
        emitted = []
        panel.connect("timing-changed",
                      lambda w, pos, start, end: emitted.append(start))

        panel.start_second.set_value(5)
        panel.start_second.set_value(6)
        panel.start_second.set_value(7)
        _pump_until("_timing_changed_id", panel)

        # One signal carrying the final value.
        assert len(emitted) == 1
        assert emitted[0].seconds == 7


@pytest.mark.integration
class TestStyleChangedSignal:
    def test_user_selection_emits_style(self):
        panel = _panel(SubtitleFormat.ASS, ["Default", "Title"])
        panel.set_entry(_entry(style="Default"), 0)

        emitted = []
        panel.connect("style-changed",
                      lambda w, pos, style: emitted.append((pos, style)))

        panel.style_row.set_selected(1)
        assert emitted == [(0, "Title")]

    def test_programmatic_load_does_not_emit(self):
        panel = _panel(SubtitleFormat.ASS, ["Default", "Title"])
        emitted = []
        panel.connect("style-changed",
                      lambda w, pos, style: emitted.append((pos, style)))

        panel.set_entry(_entry(style="Title"), 0)

        assert emitted == []

    def test_srt_never_emits_style(self):
        panel = _panel(SubtitleFormat.SRT)
        panel.set_entry(_entry(), 0)
        emitted = []
        panel.connect("style-changed",
                      lambda w, pos, style: emitted.append((pos, style)))

        panel.style_row.set_selected(0)

        assert emitted == []


@pytest.mark.integration
class TestPositionChangedSignal:
    def test_margin_edit_emits_debounced_position(self):
        panel = _panel(SubtitleFormat.ASS, ["Default"])
        panel.set_entry(_entry(style="Default"), 0)

        emitted = []
        panel.connect("position-changed",
                      lambda w, pos, ml, mr, mv: emitted.append((pos, ml, mr, mv)))

        panel.margin_l_spin.set_value(20)
        panel.margin_v_spin.set_value(40)
        _pump_until("_position_changed_id", panel)

        assert emitted == [(0, 20, 0, 40)]

    def test_srt_margins_do_not_emit(self):
        panel = _panel(SubtitleFormat.SRT)
        panel.set_entry(_entry(), 0)
        emitted = []
        panel.connect("position-changed",
                      lambda w, pos, ml, mr, mv: emitted.append(pos))

        panel.margin_l_spin.set_value(20)
        _pump_until("_position_changed_id", panel, timeout_s=0.4)

        assert emitted == []


@pytest.mark.integration
class TestClear:
    def test_clear_resets_everything(self):
        panel = _panel()
        panel.set_entry(_entry(), 3)

        panel.clear()

        assert panel.current_entry is None
        assert panel.current_position == -1
        assert panel.get_sensitive() is False
        start, end = panel.text_buffer.get_bounds()
        assert panel.text_buffer.get_text(start, end, False) == ""
        for spin in (panel.start_minute, panel.start_second,
                     panel.end_second, panel.end_milli):
            assert spin.get_value_as_int() == 0

    def test_pending_text_flushed_when_switching_entries(self):
        panel = _panel()
        first = _entry(text="original")
        second = _entry(text="second", start_ms=70_000, end_ms=71_000)
        panel.set_entry(first, 0)

        emitted = []
        panel.connect("text-changed",
                      lambda w, pos, text: emitted.append((pos, text)))

        # Type (schedules the debounced emission), then switch entries.
        panel.text_buffer.set_text("typed")
        assert panel._text_change_timeout_id is not None
        panel.set_entry(second, 1)

        # The pending edit was flushed for the OLD position before switching.
        assert emitted == [(0, "typed")]
        assert panel.current_position == 1
