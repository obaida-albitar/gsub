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


# --- BatchFileList removal (context menu / Delete shortcuts) ----------------

def _make_file_list(count=2):
    from gsub.widgets.batch_file_list import BatchFileList

    file_list = BatchFileList()
    for i in range(count):
        file_list.add_file(_ass_doc(), f"/tmp/file_{i}.ass")
    return file_list


def test_remove_file_emits_files_changed_and_updates_ui():
    file_list = _make_file_list(2)
    emitted = []
    file_list.connect('files-changed', lambda *a: emitted.append(True))

    file_list.remove_file(file_list._files[0])

    assert emitted
    assert file_list.file_count == 1
    assert file_list._files[0].file_path == '/tmp/file_1.ass'


def test_remove_selected_removes_selection_item():
    file_list = _make_file_list(3)
    file_list._selection.select_item(1, True)

    file_list.remove_selected()

    assert file_list.file_count == 2
    assert [f.file_path for f in file_list._files] == [
        '/tmp/file_0.ass', '/tmp/file_2.ass']


def test_clear_empties_list_and_switches_to_empty_page():
    file_list = _make_file_list(2)
    file_list.clear()
    assert file_list.file_count == 0
    assert file_list.stack.get_visible_child_name() == 'empty'


def test_clear_all_without_modified_files_clears_immediately():
    file_list = _make_file_list(2)
    file_list._request_clear_all()
    assert file_list.file_count == 0


def test_clear_all_with_unsaved_changes_waits_for_confirmation():
    file_list = _make_file_list(2)
    file_list._files[0].modified = True
    # The confirmation dialog is async; without a running main loop (and a
    # user clicking "Remove All") nothing may be cleared yet.
    file_list._request_clear_all()
    assert file_list.file_count == 2


def test_delete_key_removes_selected_file():
    file_list = _make_file_list(2)
    file_list._selection.select_item(1, True)

    assert file_list._on_key_pressed(None, Gdk.KEY_Delete, 0, 0) is True
    assert file_list.file_count == 1
    assert [f.file_path for f in file_list._files] == ['/tmp/file_0.ass']


def test_ctrl_shift_delete_requests_clear_all():
    file_list = _make_file_list(2)
    requested = []
    file_list._request_clear_all = lambda: requested.append(True)

    file_list._on_key_pressed(
        None, Gdk.KEY_Delete, 0,
        Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK)

    assert requested


def test_delete_key_on_empty_list_is_ignored():
    file_list = _make_file_list(0)
    assert file_list._on_key_pressed(None, Gdk.KEY_Delete, 0, 0) is False


def test_row_get_item_tracks_binding():
    from gsub.widgets.batch_file_list import BatchFileRow

    row = BatchFileRow()
    assert row.get_item() is None

    item = _make_file_list(1)._files[0]
    row.bind(item, lambda *a: None)
    assert row.get_item() is item

    row.unbind()
    assert row.get_item() is None


def test_mapped_batch_row_focuses_checkbox_and_keeps_it_interactive(capfd):
    from gi.repository import GLib
    from gsub.widgets.batch_file_list import BatchFileRow

    file_list = _make_file_list(1)
    window = Gtk.Window()
    window.set_child(file_list)
    context = GLib.MainContext.default()

    def pump():
        for _ in range(20):
            context.iteration(False)

    def descendants(widget):
        child = widget.get_first_child()
        while child is not None:
            yield child
            yield from descendants(child)
            child = child.get_next_sibling()

    capfd.readouterr()
    try:
        window.present()
        pump()
        assert window.get_mapped()
        row = next(widget for widget in descendants(file_list.list_view)
                   if isinstance(widget, BatchFileRow))
        assert row.grab_focus()
        pump()
        assert window.get_focus() is row.check
        assert row.check.get_can_focus()
        assert file_list.get_selected_files() == file_list.get_all_files()

        # CheckButton's activation is the same action used by Space when it
        # has keyboard focus; row focus must not disable this interaction.
        assert row.check.activate()
        pump()
        assert file_list.get_selected_files() == []
    finally:
        window.destroy()
        pump()
    assert "gtk_list_box_row_grab_focus" not in capfd.readouterr().err
