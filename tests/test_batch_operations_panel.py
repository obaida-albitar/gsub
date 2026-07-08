"""
GTK widget tests for the batch operations panel and the batch file list.

These require a display (GTK cannot construct template widgets headless). They
are skipped automatically when no ``Gdk.Display`` is available, so they don't
break headless CI. The gresource bundle must be built (``meson compile``).
"""

import pytest

from subtitle_editor.models import ASSStyle, SubtitleDocument, SubtitleFormat
from subtitle_editor.resources import register_resources

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


def _ass_doc(name="Default", fontsize=20):
    doc = SubtitleDocument(format=SubtitleFormat.ASS)
    doc.styles = [ASSStyle(name=name, fontsize=fontsize)]
    return doc


def _make_panel():
    from subtitle_editor.widgets.batch_operations_panel import BatchOperationsPanel

    return BatchOperationsPanel()


# --- BatchOperationsPanel ---------------------------------------------------

def test_panel_instantiates():
    panel = _make_panel()
    assert panel is not None


def test_set_shared_styles_populates_combo():
    panel = _make_panel()
    panel.set_shared_styles(["Default", "Sign", "ED1-Romaji-L0"])
    model = panel.style_combo_row.get_model()
    assert model is not None
    assert model.get_n_items() == 3
    # First style is selected by default.
    assert panel.get_selected_style_name() == "Default"


def test_set_shared_styles_empty():
    panel = _make_panel()
    panel.set_shared_styles([])
    assert panel.style_combo_row.get_model().get_n_items() == 0
    assert panel.get_selected_style_name() is None
    assert panel.style_combo_row.get_sensitive() is False


def test_set_shared_styles_preserves_selection():
    panel = _make_panel()
    panel.set_shared_styles(["Default", "Sign"])
    panel.style_combo_row.set_selected(1)
    assert panel.get_selected_style_name() == "Sign"

    # Rebuild with an overlapping set that still includes the selection.
    panel.set_shared_styles(["Default", "Sign", "ED1-Romaji-L0"])
    assert panel.get_selected_style_name() == "Sign"


def test_set_shared_styles_drops_missing_selection():
    panel = _make_panel()
    panel.set_shared_styles(["Default", "Sign"])
    panel.style_combo_row.set_selected(1)
    assert panel.get_selected_style_name() == "Sign"

    # New set no longer contains "Sign" -> falls back to first item.
    panel.set_shared_styles(["Default", "ED1-Romaji-L0"])
    assert panel.get_selected_style_name() == "Default"


def test_font_size_enable_toggles_sensitivity_and_visibility():
    panel = _make_panel()
    assert panel.font_size_row.get_sensitive() is False
    assert panel.style_combo_row.get_visible() is False

    panel.font_enable_switch.set_active(True)
    assert panel.font_size_row.get_sensitive() is True
    assert panel.style_combo_row.get_visible() is True

    panel.font_enable_switch.set_active(False)
    assert panel.font_size_row.get_sensitive() is False
    assert panel.style_combo_row.get_visible() is False


def test_has_font_size_change():
    panel = _make_panel()
    panel.font_enable_switch.set_active(True)
    panel.font_size_row.set_value(0)
    assert panel.has_font_size_change() is False
    panel.font_size_row.set_value(42)
    assert panel.has_font_size_change() is True


def test_has_resolution_change():
    panel = _make_panel()
    panel.res_enable_switch.set_active(True)
    panel.res_width_row.set_value(0)
    panel.res_height_row.set_value(1080)
    assert panel.has_resolution_change() is False
    panel.res_width_row.set_value(1920)
    assert panel.has_resolution_change() is True


def test_get_summary():
    panel = _make_panel()
    panel.offset_row.set_value(1000)
    panel.font_enable_switch.set_active(True)
    panel.font_size_row.set_value(30)
    panel.res_enable_switch.set_active(True)
    panel.res_width_row.set_value(1920)
    panel.res_height_row.set_value(1080)

    summary = panel.get_summary()
    assert "Time shift: +1000ms" in summary
    assert "Font size: 30pt" in summary
    assert "Resolution: 1920x1080" in summary


def test_reset_clears_state():
    panel = _make_panel()
    panel.offset_row.set_value(1000)
    panel.font_enable_switch.set_active(True)
    panel.font_size_row.set_value(30)
    panel.res_enable_switch.set_active(True)
    panel.res_width_row.set_value(1920)
    panel.res_height_row.set_value(1080)

    panel.reset()

    assert int(panel.offset_row.get_value()) == 0
    assert panel.font_enable_switch.get_active() is False
    assert panel.res_enable_switch.get_active() is False
    # With the enable switches off, no operation is configured. (Font/res spin
    # rows have a minimum of 1, so their raw values clamp rather than going to 0.)
    assert panel.has_any_operation() is False


def test_operations_changed_emitted_on_toggle():
    panel = _make_panel()
    emitted = []

    def _on_changed(*args):
        emitted.append(True)

    panel.connect("operations-changed", _on_changed)
    panel.font_enable_switch.set_active(True)
    assert emitted  # at least one emission


# --- BatchFileList.update_ui (regression for the original `fmt` NameError) --

def test_batch_file_list_update_ui_no_name_error():
    from subtitle_editor.widgets.batch_file_list import BatchFileList

    file_list = BatchFileList()
    docs = [
        _ass_doc("Default", 20),
        _ass_doc("Sign", 30),
    ]
    for i, doc in enumerate(docs):
        file_list.add_file(doc, f"/tmp/file_{i}.ass")

    # Must not raise NameError: name 'fmt' is not defined.
    file_list.update_ui()

    badge = file_list.format_badge.get_label()
    assert "Default" in badge or "All" in badge
