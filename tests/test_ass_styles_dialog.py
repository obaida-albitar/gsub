"""
GTK widget test for the ASS Styles dialog font handling.

Verifies the regression where a style whose font is not installed on the
system was silently replaced by the first installed font (and lost on save).
Requires a display; skipped automatically when none is available.
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


def _make_dialog(fontname):
    from subtitle_editor.widgets.dialogs import ASSStylesDialog

    doc = SubtitleDocument(format=SubtitleFormat.ASS)
    doc.styles = [ASSStyle(name="Default", fontname=fontname)]

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
