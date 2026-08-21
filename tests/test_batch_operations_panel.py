"""
GTK widget tests for the batch operations panel and the batch file list.

These require a display (GTK cannot construct template widgets headless). They
are skipped automatically when no ``Gdk.Display`` is available, so they don't
break headless CI. The gresource bundle must be built (``meson compile``).
"""

import pytest

from gsub.models import ASSStyle, SubtitleDocument, SubtitleFormat
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


def _ass_doc(name="Default", fontsize=20):
    doc = SubtitleDocument(format=SubtitleFormat.ASS)
    doc.styles = [ASSStyle(name=name, fontsize=fontsize)]
    return doc


def _make_panel():
    from gsub.widgets.batch_operations_panel import BatchOperationsPanel

    return BatchOperationsPanel()


# --- BatchOperationsPanel ---------------------------------------------------

def test_panel_instantiates():
    panel = _make_panel()
    assert panel is not None


def test_panel_has_no_font_size_group_leftover():
    panel = _make_panel()
    # The old Font Size section was merged into Style Properties.
    assert not hasattr(panel, "font_size_row")
    assert not hasattr(panel, "style_combo_row")


def test_set_style_props_styles_feeds_editor():
    panel = _make_panel()
    panel.set_style_props_styles([
        ASSStyle(name="Default", fontsize=20),
        ASSStyle(name="Sign", fontsize=30),
    ])
    # No single-style source in the panel: "Selected style" hidden, All default.
    assert panel.style_props.target_one_row.get_visible() is False
    assert panel.style_props.get_target_styles() == ["Default", "Sign"]


def test_set_style_props_styles_empty():
    panel = _make_panel()
    panel.set_style_props_styles([])
    assert panel.style_props.get_target_styles() == []
    assert panel.has_style_props_change() is False


def test_has_style_props_change_needs_property_tick():
    panel = _make_panel()
    panel.set_style_props_styles([ASSStyle(name="Default", fontsize=20)])

    # Targets (All) but no property ticked yet.
    assert panel.has_style_props_change() is False

    panel.style_props.fontsize_check.set_active(True)
    panel.style_props.fontsize_row.set_value(24)
    assert panel.has_style_props_change() is True


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
    panel.res_enable_switch.set_active(True)
    panel.res_width_row.set_value(1920)
    panel.res_height_row.set_value(1080)
    panel.set_style_props_styles([ASSStyle(name="Default", fontsize=20)])
    panel.style_props.fontsize_check.set_active(True)
    panel.style_props.fontsize_row.set_value(24)

    summary = panel.get_summary()
    assert "Time shift: +1000ms" in summary
    assert "Resolution: 1920x1080" in summary
    assert any(line.startswith("Style properties: Font Size on 1 style") for line in summary)


def test_reset_clears_state():
    panel = _make_panel()
    panel.offset_row.set_value(1000)
    panel.res_enable_switch.set_active(True)
    panel.res_width_row.set_value(1920)
    panel.res_height_row.set_value(1080)
    panel.set_style_props_styles([ASSStyle(name="Default", fontsize=20)])
    panel.style_props.fontsize_check.set_active(True)

    panel.reset()

    assert int(panel.offset_row.get_value()) == 0
    assert panel.res_enable_switch.get_active() is False
    assert panel.has_style_props_change() is False
    assert panel.has_any_operation() is False


def test_operations_changed_emitted_on_toggle():
    panel = _make_panel()
    emitted = []

    def _on_changed(*args):
        emitted.append(True)

    panel.connect("operations-changed", _on_changed)
    panel.res_enable_switch.set_active(True)
    assert emitted  # at least one emission


# --- BatchFileList.update_ui (regression for the original `fmt` NameError) --

def test_batch_file_list_update_ui_no_name_error():
    from gsub.widgets.batch_file_list import BatchFileList

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
