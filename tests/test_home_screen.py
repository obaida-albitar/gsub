"""GTK widget test for the home screen cards.

Clicking the first card's button must emit ``open-file`` (the window then
navigates to the editor without popping a file chooser) and the batch card
must emit ``open-batch``. Requires a display; skipped automatically when
none is available.
"""

import pytest
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


def _make_view():
    from subtitle_editor.widgets.home_screen import HomeScreenView

    return HomeScreenView()


def test_start_button_emits_open_file():
    view = _make_view()
    fired = []
    view.connect("open-file", lambda *args: fired.append(True))

    view.open_button.emit("clicked")

    assert fired == [True]


def test_batch_button_emits_open_batch():
    view = _make_view()
    fired = []
    view.connect("open-batch", lambda *args: fired.append(True))

    view.batch_button.emit("clicked")

    assert fired == [True]


def test_start_button_does_not_emit_open_batch():
    view = _make_view()
    fired = []
    view.connect("open-batch", lambda *args: fired.append(True))

    view.open_button.emit("clicked")

    assert fired == []
