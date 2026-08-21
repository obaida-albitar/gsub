"""
GTK widget test for the ASS Styles dialog font handling.

Verifies the regression where a style whose font is not installed on the
system was silently replaced by the first installed font (and lost on save).
Requires a display; skipped automatically when none is available.
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


def _make_dialog(fontname):
    return _make_dialog_for_style(ASSStyle(name="Default", fontname=fontname))


def _make_dialog_for_style(style):
    from gsub.widgets.dialogs import ASSStylesDialog

    doc = SubtitleDocument(format=SubtitleFormat.ASS)
    doc.styles = [style]

    class _FakeParent:
        def __init__(self, document):
            self.document = document

    return ASSStylesDialog(_FakeParent(doc))


def test_uninstalled_font_is_preserved_and_warned():
    dlg = _make_dialog("Sansation-Not-Installed-XYZ")
    # The real (uninstalled) font name stays in the dropdown model.
    assert "Sansation-Not-Installed-XYZ" in dlg._font_families
    # The selected entry reflects the real font, not a fallback.
    assert dlg.style_font.get_selected_item().get_string() == "Sansation-Not-Installed-XYZ"
    # The in-memory style is unchanged (no silent overwrite).
    assert dlg._styles[0].fontname == "Sansation-Not-Installed-XYZ"
    # A warning is shown because the font is missing locally.
    assert dlg.font_warning.get_visible() is True
    assert "Sansation-Not-Installed-XYZ" in dlg.font_warning.get_text()


def test_installed_font_has_no_warning():
    installed = dlg_installed = None
    dlg = _make_dialog("Temp")
    if not dlg._installed_fonts:
        pytest.skip("no installed fonts to assert against")
    real = dlg._installed_fonts[0]
    dlg2 = _make_dialog(real)
    assert dlg2._styles[0].fontname == real
    assert dlg2.font_warning.get_visible() is False


# --- Semantic inputs: Alignment / BorderStyle / Encoding ---------------------

def test_alignment_grid_reflects_loaded_style():
    dlg = _make_dialog_for_style(ASSStyle(name="Default", alignment=3))
    assert dlg.alignment_grid.get_value() == 3
    assert dlg.alignment_grid._buttons[3].get_active() is True  # bottom right


def test_border_style_combo_reflects_loaded_style():
    dlg = _make_dialog_for_style(ASSStyle(name="Default", border_style=3))
    assert dlg._border_style_choice.get_value() == 3
    assert dlg.style_border_style.get_selected_item().get_string() == "Opaque Box"


def test_encoding_combo_reflects_loaded_style():
    dlg = _make_dialog_for_style(ASSStyle(name="Default", encoding=178))
    assert dlg._encoding_choice.get_value() == 178
    assert dlg.style_encoding.get_selected_item().get_string() == "Arabic (Windows)"


def test_unknown_encoding_displays_as_custom_and_is_kept():
    dlg = _make_dialog_for_style(ASSStyle(name="Default", encoding=74))
    assert dlg.style_encoding.get_selected_item().get_string() == "74 (custom)"
    # The stored value survives loading (no silent overwrite), and reading the
    # widgets back still yields it.
    dlg._on_style_field_changed()
    assert dlg._styles[0].encoding == 74


def test_semantic_widget_changes_update_style_copy():
    dlg = _make_dialog_for_style(ASSStyle(name="Default"))
    dlg.alignment_grid.set_value(9)
    dlg._border_style_choice.set_value(3)
    dlg._encoding_choice.set_value(0)

    style = dlg._styles[0]
    assert style.alignment == 9
    assert style.border_style == 3
    assert style.encoding == 0
