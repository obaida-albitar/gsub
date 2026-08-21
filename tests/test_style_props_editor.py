"""
GTK widget tests for the shared style properties editor group.

These require a display (GTK cannot construct template widgets headless). They
are skipped automatically when no ``Gdk.Display`` is available, so they don't
break headless CI. The gresource bundle must be built (``make build-resources``).
"""

import copy

import pytest

from gsub.commands import CommandManager
from gsub.models import (
    ASSStyle,
    SubtitleDocument,
    SubtitleEntry,
    SubtitleFormat,
    TimeCode,
)
from gsub.resources import register_resources
from gsub.utils import is_valid_ass_color

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


def _make_editor(styles=None, source=None):
    from gsub.widgets.style_props_editor import GsubStylePropsEditor

    editor = GsubStylePropsEditor()
    if source is not None:
        editor.set_single_style_source(source)
    editor.set_styles(styles if styles is not None else _sample_styles())
    return editor


def _sample_styles():
    return [
        ASSStyle(name="Default", fontname="Sans", fontsize=20),
        ASSStyle(name="Title", fontname="Serif", fontsize=28, bold=True),
    ]


# --- Construction & targets -------------------------------------------------

def test_editor_instantiates():
    editor = _make_editor()
    assert editor is not None


def test_default_target_is_all_without_single_style_source():
    editor = _make_editor()
    assert editor.target_one_row.get_visible() is False
    assert editor.target_all_check.get_active() is True
    assert editor.get_target_styles() == ["Default", "Title"]
    # Targets exist but nothing is ticked -> no change configured.
    assert editor.has_changes() is False


def test_single_style_source_selects_and_tracks_one():
    current = {"name": "Default"}
    editor = _make_editor(source=lambda: current["name"])
    assert editor.target_one_row.get_visible() is True
    assert editor.target_one_check.get_active() is True
    assert editor.get_target_styles() == ["Default"]

    current["name"] = "Title"
    editor.sync_single_style()
    assert editor.target_one_row.get_subtitle() == "Title"
    assert editor.get_target_styles() == ["Title"]


def test_single_style_unknown_name_yields_no_targets():
    editor = _make_editor(source=lambda: "Missing")
    assert editor.get_target_styles() == []
    assert editor.has_changes() is False


def test_choose_mode_with_checklist_and_all_none_buttons():
    editor = _make_editor()
    editor.target_choose_check.set_active(True)

    # Entering choose mode expands the expander and shows All/None.
    assert editor.target_choose_expander.get_expanded() is True
    assert editor.select_buttons_box.get_visible() is True
    assert editor.get_target_styles() == []  # nothing ticked yet

    editor.on_select_all(None)
    assert set(editor.get_target_styles()) == {"Default", "Title"}

    editor._style_checks["Default"].set_active(False)
    assert editor.get_target_styles() == ["Title"]

    editor.on_select_none(None)
    assert editor.get_target_styles() == []


def test_set_styles_preserves_choose_mode_checks():
    editor = _make_editor()
    editor.target_choose_check.set_active(True)
    editor._style_checks["Default"].set_active(True)

    editor.set_styles(_sample_styles())  # same names again
    assert editor.get_target_styles() == ["Default"]

    editor.set_styles([ASSStyle(name="Title")])  # "Default" gone
    assert editor.get_target_styles() == []


def test_set_styles_empty_hides_nothing_but_disables_changes():
    editor = _make_editor(styles=[])
    assert editor.get_target_styles() == []
    editor.fontsize_check.set_active(True)
    assert editor.has_changes() is False  # no targets


def test_one_mode_falls_back_to_all_without_source():
    editor = _make_editor()  # no source
    # Simulate a stale "one" mode (e.g. source removed): set_styles repairs it.
    editor._loading = True
    editor.target_one_check.set_active(True)
    editor._loading = False
    editor.set_styles(_sample_styles())
    assert editor.target_all_check.get_active() is True
    assert editor.get_target_styles() == ["Default", "Title"]


# --- Property reading -----------------------------------------------------------

def test_checked_props_map_onto_ass_style_fields():
    editor = _make_editor()

    # Tick one row of every kind.
    editor.font_check.set_active(True)
    editor.fontsize_check.set_active(True)
    editor.bold_check.set_active(True)
    editor.primary_check.set_active(True)
    editor.alignment_check.set_active(True)
    editor.margin_l_check.set_active(True)

    props = editor.get_checked_props()

    # Every key must be a real, non-name ASSStyle field (this would raise on
    # a typo) and values must be accepted by the model.
    style = ASSStyle(name="Probe")
    for field, value in props.items():
        assert field != "name"
        setattr(style, field, value)

    assert isinstance(props["fontsize"], int)
    assert isinstance(props["bold"], bool)
    assert isinstance(props["alignment"], int)
    assert isinstance(props["margin_l"], int)
    assert is_valid_ass_color(props["primary_color"])
    assert props["fontname"]  # some font selected


def test_unticked_rows_are_not_reported():
    editor = _make_editor()
    # Values are loaded from the base style but nothing is ticked.
    assert editor.get_checked_props() == {}
    assert editor.has_changes() is False


def test_row_values_default_to_first_target_style():
    editor = _make_editor()  # All -> first style is "Default"
    assert editor.fontsize_row.get_value() == 20.0
    assert editor.bold_row.get_active() is False

    editor.fontsize_row.set_value(42)
    assert editor.fontsize_row.get_value() == 42.0


# --- Semantic inputs: Alignment / BorderStyle / Encoding ---------------------

def test_checked_props_return_ints_for_semantic_widgets():
    editor = _make_editor()
    editor.alignment_check.set_active(True)
    editor.border_style_check.set_active(True)
    editor.encoding_check.set_active(True)
    editor.alignment_grid.set_value(7)
    editor._choice_rows['border_style'].set_value(3)
    editor._choice_rows['encoding'].set_value(0)

    props = editor.get_checked_props()
    assert props['alignment'] == 7
    assert props['border_style'] == 3
    assert props['encoding'] == 0
    for value in (props['alignment'], props['border_style'], props['encoding']):
        assert isinstance(value, int)


def test_semantic_widgets_load_values_from_style():
    styles = [ASSStyle(name="Default", alignment=9, border_style=3, encoding=178)]
    editor = _make_editor(styles=styles)
    assert editor.alignment_grid.get_value() == 9
    assert editor.alignment_grid._buttons[9].get_active() is True  # top right
    assert editor._choice_rows['border_style'].get_value() == 3
    assert editor.border_style_row.get_selected_item().get_string() == "Opaque Box"
    assert editor._choice_rows['encoding'].get_value() == 178
    assert editor.encoding_row.get_selected_item().get_string() == "Arabic (Windows)"


def test_unknown_encoding_shows_custom_entry_and_round_trips():
    editor = _make_editor(styles=[ASSStyle(name="Default", encoding=74)])
    assert editor.encoding_row.get_selected_item().get_string() == "74 (custom)"

    editor.encoding_check.set_active(True)
    assert editor.get_checked_props()['encoding'] == 74


def test_reset_unticks_semantic_rows():
    editor = _make_editor()
    editor.alignment_check.set_active(True)
    editor.border_style_check.set_active(True)
    editor.encoding_check.set_active(True)

    editor.reset()
    assert editor.get_checked_props() == {}


def test_reset_clears_ticks_and_restores_default_target():
    editor = _make_editor()
    editor.target_choose_check.set_active(True)
    editor.on_select_all(None)
    editor.font_check.set_active(True)
    editor.preview_expander.set_expanded(True)

    editor.reset()

    assert editor.target_all_check.get_active() is True
    assert editor.get_checked_props() == {}
    assert editor.preview_expander.get_expanded() is False
    assert editor.target_choose_expander.get_expanded() is False


def test_property_labels_cover_checked_props():
    from gsub.widgets.style_props_editor import PROP_LABELS

    editor = _make_editor()
    editor.font_check.set_active(True)
    editor.spacing_check.set_active(True)

    labels = editor.property_labels()
    assert labels == [PROP_LABELS["fontname"], PROP_LABELS["spacing"]]
    assert all(label for label in labels)


# --- BulkApplyStyleDialog integration -------------------------------------------

class _FakeSubtitleList:
    def __init__(self, positions):
        self._positions = positions

    def get_selected_positions(self):
        return list(self._positions)

    def refresh(self, preserve_selection=False):
        pass


class _FakeWindow:
    def __init__(self, document, positions=(0,)):
        self.document = document
        self.subtitle_list = _FakeSubtitleList(positions)
        self.command_manager = CommandManager()
        self.toasts = []

    def _show_toast(self, message):
        self.toasts.append(message)

    def _update_title(self):
        pass

    def _update_undo_redo_buttons(self):
        pass

    def _refresh_video_preview(self):
        pass


def _make_assign_dialog(document):
    from gsub.widgets.dialogs import BulkApplyStyleDialog

    return BulkApplyStyleDialog(_FakeWindow(document))


def _make_props_dialog(document):
    from gsub.widgets.dialogs import BatchStylePropsDialog

    return BatchStylePropsDialog(_FakeWindow(document))


def _ass_doc_with_entries():
    doc = SubtitleDocument(format=SubtitleFormat.ASS)
    doc.styles = _sample_styles()
    doc.entries = [
        SubtitleEntry(1, TimeCode(0, 0, 0, 500), TimeCode(0, 0, 2, 0), "hi", style="Default"),
    ]
    return doc


# --- BulkApplyStyleDialog (assignment only, right-click) ------------------------

def test_assign_dialog_applies_style_to_selected_lines():
    doc = _ass_doc_with_entries()

    dialog = _make_assign_dialog(doc)
    # Property editing moved to its own dialog (main menu).
    assert not hasattr(dialog, "style_props")

    dialog.style_row.set_selected(1)  # Title
    dialog.on_apply(None)

    assert doc.entries[0].style == "Title"
    assert doc.get_style_by_name("Title").bold is True  # definitions untouched

    dialog.parent_window.command_manager.undo()
    assert doc.entries[0].style == "Default"


# --- BatchStylePropsDialog (style definitions, main menu) ------------------------

def test_props_dialog_targets_dropdown_style_by_default():
    doc = _ass_doc_with_entries()
    dialog = _make_props_dialog(doc)

    # The editor's "Selected style" follows the dialog's own style dropdown.
    assert dialog.style_props.get_target_styles() == ["Default"]
    dialog.style_row.set_selected(1)
    assert dialog.style_props.get_target_styles() == ["Title"]


def test_props_dialog_applies_property_edit_with_undo():
    doc = _ass_doc_with_entries()
    original = copy.deepcopy(doc.styles[0])

    dialog = _make_props_dialog(doc)
    dialog.style_props.fontsize_check.set_active(True)
    dialog.style_props.fontsize_row.set_value(36)
    dialog.on_apply(None)

    assert doc.styles[0].fontsize == 36
    assert doc.get_style_by_name("Title").fontsize == 28  # untouched
    assert dialog.parent_window.toasts == ["Updated 1 style"]
    assert dialog.parent_window.command_manager.can_undo()

    dialog.parent_window.command_manager.undo()
    assert doc.styles[0].fontsize == original.fontsize
    assert doc.styles[0].to_fields() == original.to_fields()


def test_props_dialog_nothing_configured_shows_toast_and_stays_open():
    doc = _ass_doc_with_entries()

    dialog = _make_props_dialog(doc)

    assert dialog.apply_button.get_sensitive() is False
    dialog.on_apply(None)
    assert dialog.parent_window.toasts == ["Nothing to apply"]
    assert dialog.parent_window.command_manager.can_undo() is False
    assert doc.entries[0].style == "Default"
