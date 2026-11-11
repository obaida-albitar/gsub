"""GTK integration checks for proofreading and immediate readability metrics."""

import pytest

from gsub.models import SubtitleDocument, SubtitleEntry, SubtitleFormat, TimeCode
from gsub.quality import QualitySettings
from gsub.resources import register_resources

try:
    from gi.repository import Adw, Gdk, Gtk
    register_resources()
    Gtk.init()
    Adw.init()
    HAS_DISPLAY = Gdk.Display.get_default() is not None
except Exception:
    HAS_DISPLAY = False

pytestmark = pytest.mark.skipif(not HAS_DISPLAY, reason="no display available for GTK tests")


def cue(text="Hello", start=0, end=2000):
    return SubtitleEntry(1, TimeCode.from_milliseconds(start),
                         TimeCode.from_milliseconds(end), text)


def make_dialog(*entries, settings=None):
    from gsub.widgets.quality_dialog import QualityDialog

    window = Gtk.Window()
    doc = SubtitleDocument(SubtitleFormat.SRT, entries=list(entries))
    selected, saved = [], []
    dialog = QualityDialog(window, doc, selected.append, settings=settings,
                           on_settings_changed=saved.append)
    return dialog, selected, saved


def rows(dialog):
    result = []
    child = dialog.issues_box.get_first_child()
    while child:
        result.append(child)
        child = child.get_next_sibling()
    return result


def test_empty_quality_dialog_shows_clear_result():
    dialog, _, saved = make_dialog(cue())
    assert dialog.issues == []
    assert rows(dialog) == []
    assert dialog.status_label.get_label() == "No quality issues found"
    assert not dialog.issues_box.get_visible()
    assert saved == []


def test_issues_activate_selection_callback(monkeypatch):
    dialog, selected, _ = make_dialog(cue(end=100))
    closed = []
    monkeypatch.setattr(dialog, "close", lambda: closed.append(True))
    rows(dialog)[0].emit("activated")
    assert selected == [0]
    assert closed == [True]


def test_configuration_updates_rescan_and_persist():
    dialog, _, saved = make_dialog(cue("Hello", end=1000),
                                   settings=QualitySettings(max_cps=2))
    assert any(i.code == "text.reading_speed" for i in dialog.issues)
    dialog.max_cps_row.set_value(20)
    assert not dialog.issues
    assert saved[-1].max_cps == 20


def test_overlap_switch_and_refresh_use_current_document():
    dialog, _, saved = make_dialog(cue(), cue(start=1000, end=3000))
    assert any(i.code == "timing.overlap" for i in dialog.issues)
    dialog.overlap_row.set_active(False)
    assert not dialog.issues
    assert saved[-1].check_overlaps is False
    dialog.document.entries[0].text = ""
    dialog.refresh()
    assert any(i.code == "text.empty" for i in dialog.issues)


def test_invalid_duration_settings_do_not_replace_last_valid_settings():
    dialog, _, saved = make_dialog(cue())
    dialog.min_duration_row.set_value(8000)
    assert dialog.settings.min_duration_ms == 1000
    assert "Maximum duration" in dialog.status_label.get_label()
    assert saved == []
    dialog.max_duration_row.set_value(9000)
    assert dialog.settings.min_duration_ms == 8000
    assert saved[-1].max_duration_ms == 9000


@pytest.fixture
def panel():
    from gsub.widgets.editor_panel import EditorPanel

    window = Gtk.Window()
    editor = EditorPanel()
    window.set_child(editor)
    editor.set_document_context(SubtitleFormat.SRT, [])
    editor.set_entry(cue(), 0)
    yield editor
    editor.clear()
    window.destroy()


def test_live_readability_updates_for_text_and_timing_without_waiting(panel):
    assert "2.5 characters/s" in panel.readability_row.get_subtitle()
    panel.text_buffer.set_text("Hello world\nHi")
    assert "Characters per line: 11, 2" in panel.readability_row.get_subtitle()
    panel.end_second.set_value(1)
    assert "13.0 characters/s" in panel.readability_row.get_subtitle()
    panel.clear()
    assert panel.readability_row.get_subtitle() == "No subtitle selected"


def test_ass_live_metrics_use_visible_text(panel):
    panel.set_document_context(SubtitleFormat.ASS, ["Default"])
    panel.set_entry(cue(r"{\p1}m 0 0 l 5 5{\p0}{\b1}Hello\Nworld"), 0)
    assert "5.0 characters/s" in panel.readability_row.get_subtitle()
    assert "Characters per line: 5, 5" in panel.readability_row.get_subtitle()


def test_flush_emits_pending_text_timing_and_margins_once(panel):
    panel.set_document_context(SubtitleFormat.ASS, ["Default"])
    emitted = []
    for signal in ("text-changed", "timing-changed", "position-changed"):
        panel.connect(signal, lambda _p, *args, signal=signal: emitted.append((signal, args)))
    panel.text_buffer.set_text("Changed")
    panel.end_second.set_value(3)
    panel.margin_l_spin.set_value(10)
    panel.flush_pending_changes()
    assert [signal for signal, _ in emitted] == [
        "text-changed", "timing-changed", "position-changed"]
    assert all(args[0] == 0 for _, args in emitted)
    assert emitted[0][1][1] == "Changed"
    assert emitted[1][1][2].total_milliseconds == 3000
    assert emitted[2][1][1:] == (10, 0, 0)
    assert panel._text_change_timeout_id is None
    assert panel._timing_changed_id is None
    assert panel._position_changed_id is None
    panel.flush_pending_changes()
    assert len(emitted) == 3


def test_switching_entries_flushes_old_timing_to_old_position(panel):
    emitted = []
    panel.connect("timing-changed", lambda _p, *args: emitted.append(args))
    panel.end_second.set_value(4)
    panel.set_entry(cue(start=5000, end=7000), 1)
    assert len(emitted) == 1
    assert emitted[0][0] == 0
    assert emitted[0][2].total_milliseconds == 4000
    panel._emit_timing_changed()
    assert len(emitted) == 1


def test_clear_cancels_pending_edits_for_replaced_document(panel):
    emitted = []
    for signal in ("text-changed", "timing-changed", "position-changed"):
        panel.connect(signal, lambda _p, *args: emitted.append(args))
    panel.set_document_context(SubtitleFormat.ASS, ["Default"])
    panel.text_buffer.set_text("Changed")
    panel.end_second.set_value(4)
    panel.margin_r_spin.set_value(20)
    panel.clear()
    panel._emit_text_changed()
    panel._emit_timing_changed()
    panel._emit_position_changed()
    assert emitted == []


def test_split_offset_uses_buffer_cursor(panel):
    panel.set_document_context(SubtitleFormat.ASS, ["Default"])
    panel.set_entry(cue(r"{\b1}Hello"), 0)
    panel.text_buffer.place_cursor(panel.text_buffer.get_iter_at_offset(2))
    assert panel.get_split_offset() == 2
