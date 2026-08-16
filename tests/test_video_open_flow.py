"""Pure-logic tests for the consolidated video-opening flow.

Covers the track-dialog decision helper, the video content-type helper used
by the "Open With" routing, and the shared ``load_video_path``/``open_video``
window methods driven through fakes (no mpv or real widget needed).
"""

import pytest

from subtitle_editor.utils import is_video_content_type

try:
    from subtitle_editor.resources import register_resources

    register_resources()
    from subtitle_editor.window import GsubWindow, should_show_track_dialog
except Exception as exc:  # pragma: no cover - depends on GTK/libmpv stack
    pytest.skip(
        f"window module not importable in this environment: {exc}",
        allow_module_level=True,
    )


@pytest.mark.unit
class TestShouldShowTrackDialog:
    def test_no_tracks_needs_no_dialog(self):
        assert should_show_track_dialog(0, 0) is False

    def test_single_audio_no_subs_needs_no_dialog(self):
        # The most common layout: no decision for the user to make.
        assert should_show_track_dialog(1, 0) is False

    def test_multiple_audio_tracks_need_dialog(self):
        assert should_show_track_dialog(2, 0) is True
        assert should_show_track_dialog(3, 0) is True

    def test_single_subtitle_track_needs_dialog(self):
        assert should_show_track_dialog(0, 1) is True
        assert should_show_track_dialog(1, 1) is True

    def test_multiple_subtitle_tracks_need_dialog(self):
        assert should_show_track_dialog(1, 2) is True
        assert should_show_track_dialog(0, 3) is True

    def test_multi_audio_and_subs_need_dialog(self):
        assert should_show_track_dialog(2, 1) is True


@pytest.mark.unit
class TestIsVideoContentType:
    def test_video_types(self):
        assert is_video_content_type("video/mp4") is True
        assert is_video_content_type("video/x-matroska") is True
        assert is_video_content_type("video/webm") is True
        assert is_video_content_type("video/quicktime") is True

    def test_non_video_types(self):
        assert is_video_content_type("application/x-subrip") is False
        assert is_video_content_type("text/x-ass") is False
        assert is_video_content_type("application/octet-stream") is False
        assert is_video_content_type("videomp4") is False

    def test_empty_and_none_are_not_video(self):
        assert is_video_content_type("") is False
        assert is_video_content_type(None) is False


class _FakePlayer:
    """Records load_video calls."""

    def __init__(self):
        self.loaded = None

    def load_video(self, path):
        self.loaded = path


class _FakeWidget:
    """Records setter calls."""

    def __init__(self):
        self.calls = []

    def set_visible(self, value):
        self.calls.append(("set_visible", value))

    def set_active(self, value):
        self.calls.append(("set_active", value))

    def set_position(self, value):
        self.calls.append(("set_position", value))

    def called(self, name):
        return [value for method, value in self.calls if method == name]


class _FakeWindow:
    """Just the attributes load_video_path/open_video touch on GsubWindow."""

    def __init__(self, video_visible=False):
        self.current_video_file = None
        self.video_visible = video_visible
        self.video_player = _FakePlayer()
        self.video_container = _FakeWidget()
        self.video_button = _FakeWidget()
        self.right_paned = _FakeWidget()
        self.toasts = []
        self.errors = []

    def _show_toast(self, message):
        self.toasts.append(message)

    def _show_error(self, message):
        self.errors.append(message)


class _FakeGFile:
    """Minimal Gio.File stand-in exposing get_path()."""

    def __init__(self, path):
        self._path = path

    def get_path(self):
        return self._path


@pytest.mark.unit
class TestLoadVideoPath:
    def test_loads_and_reveals_hidden_player(self):
        win = _FakeWindow(video_visible=False)
        win.load_video_path = GsubWindow.load_video_path.__get__(win)
        win.load_video_path("/movies/example.mkv")

        assert win.current_video_file == "/movies/example.mkv"
        assert win.video_player.loaded == "/movies/example.mkv"
        assert win.video_visible is True
        assert win.video_container.called("set_visible") == [True]
        assert win.video_button.called("set_active") == [True]
        # The pane is expanded to give the player room.
        assert win.right_paned.called("set_position") == [300]
        assert any("example.mkv" in toast for toast in win.toasts)

    def test_keeps_visible_player_untouched(self):
        win = _FakeWindow(video_visible=True)
        win.load_video_path = GsubWindow.load_video_path.__get__(win)
        win.load_video_path("/movies/example.mp4")

        assert win.video_visible is True
        assert win.video_container.calls == []
        assert win.video_button.calls == []
        assert win.right_paned.calls == []

    def test_toast_uses_basename(self):
        win = _FakeWindow()
        win.load_video_path = GsubWindow.load_video_path.__get__(win)
        win.load_video_path("/movies/a & b.mkv")

        assert win.toasts == ["Loaded video: a & b.mkv"]


@pytest.mark.unit
class TestOpenVideo:
    def test_delegates_local_path_to_load_video_path(self):
        win = _FakeWindow()
        win.load_video_path = GsubWindow.load_video_path.__get__(win)
        GsubWindow.open_video(win, _FakeGFile("/movies/example.mkv"))

        assert win.current_video_file == "/movies/example.mkv"
        assert win.video_player.loaded == "/movies/example.mkv"
        assert win.errors == []

    def test_rejects_pathless_file(self):
        win = _FakeWindow()
        win.load_video_path = GsubWindow.load_video_path.__get__(win)
        GsubWindow.open_video(win, _FakeGFile(None))

        assert win.video_player.loaded is None
        assert win.current_video_file is None
        assert len(win.errors) == 1

    def test_rejects_none_gfile(self):
        win = _FakeWindow()
        win.load_video_path = GsubWindow.load_video_path.__get__(win)
        GsubWindow.open_video(win, None)

        assert win.video_player.loaded is None
        assert len(win.errors) == 1
