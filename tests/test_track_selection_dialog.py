"""GTK widget test for the unified track-selection dialog.

Focuses on the extract switch row: it must stay hidden for videos without
embedded subtitle tracks, follow the subtitle selection for sensitivity, and
report its state through ``get_extract_selected``. Requires a display;
skipped automatically when none is available.
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


def _tracks(count, kind):
    """Build fake track dicts shaped like VideoPlayerWidget's output."""
    return [
        {
            "id": i + 1,
            "index": i + 1,
            "title": f"{kind} {i + 1}",
            "language": "eng",
            "codec": "aac" if kind == "audio" else "ass",
        }
        for i in range(count)
    ]


def _make_dialog(n_audio=1, n_subs=1, current_subtitle=-1):
    from subtitle_editor.widgets.dialogs import TrackSelectionDialog

    window = Gtk.Window()
    dialog = TrackSelectionDialog(
        window,
        _tracks(n_audio, "audio"),
        _tracks(n_subs, "sub"),
        current_audio=-1,
        current_subtitle=current_subtitle,
    )
    dialog.present(window)
    return dialog


class TestExtractRowVisibility:
    def test_hidden_without_subtitle_tracks(self):
        dlg = _make_dialog(n_audio=2, n_subs=0)
        assert dlg.extract_group.get_visible() is False
        assert dlg.extract_row.get_visible() is False
        assert dlg.extract_row.get_sensitive() is False

    def test_visible_with_subtitle_tracks(self):
        dlg = _make_dialog(n_audio=1, n_subs=2)
        assert dlg.extract_group.get_visible() is True
        assert dlg.extract_row.get_visible() is True


class TestExtractRowSelection:
    def test_disabled_while_none_selected(self):
        dlg = _make_dialog(n_subs=2, current_subtitle=-1)
        assert dlg.extract_row.get_sensitive() is False
        assert dlg.get_extract_selected() is False

    def test_enabled_when_track_selected(self):
        # subtitle_check_group[0] is the "None" row; tracks follow.
        dlg = _make_dialog(n_subs=2, current_subtitle=-1)
        dlg.subtitle_check_group[1].set_active(True)
        assert dlg.selected_subtitle == 1
        assert dlg.extract_row.get_sensitive() is True

    def test_switch_flip_reflected_in_property(self):
        dlg = _make_dialog(n_subs=1)
        dlg.subtitle_check_group[1].set_active(True)
        assert dlg.get_extract_selected() is False  # default OFF
        dlg.extract_row.set_active(True)
        assert dlg.get_extract_selected() is True

    def test_selecting_none_disables_and_resets_switch(self):
        dlg = _make_dialog(n_subs=1)
        dlg.subtitle_check_group[1].set_active(True)
        dlg.extract_row.set_active(True)
        dlg.subtitle_check_group[0].set_active(True)
        assert dlg.selected_subtitle == -1
        assert dlg.extract_row.get_sensitive() is False
        assert dlg.get_extract_selected() is False


class TestSelectionSignal:
    def test_select_emits_chosen_tracks(self):
        dlg = _make_dialog(n_audio=2, n_subs=2)
        fired = []
        dlg.connect("tracks-selected", lambda d, a, s: fired.append((a, s)))

        dlg.audio_check_group[1].set_active(True)  # audio track index 2
        dlg.subtitle_check_group[2].set_active(True)  # subtitle track index 2
        dlg.on_select_clicked(None)

        assert fired == [(2, 2)]
