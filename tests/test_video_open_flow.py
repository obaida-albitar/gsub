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
    from subtitle_editor.widgets import video_player as video_player_module
    from subtitle_editor.widgets.video_player import VideoPlayerWidget
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

    def __init__(self, order=None):
        self.loaded = None
        self.order = order if order is not None else []

    def load_video(self, path):
        self.loaded = path
        self.order.append(("load_video", path))


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
        # Shared call-order log across the fakes (see order-based tests).
        self.order = []
        self.video_player = _FakePlayer(order=self.order)
        self.video_container = _FakeWidget()
        self.video_button = _FakeWidget()
        self.right_paned = _FakeWidget()
        self.toasts = []
        self.errors = []

    def _navigate_to_editor(self):
        self.order.append(("navigate_to_editor",))

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


@pytest.mark.unit
class TestNavigateBeforeLoad:
    """The editor view must be visible before the video is loaded."""

    def test_load_video_path_navigates_before_loading(self):
        win = _FakeWindow()
        win.load_video_path = GsubWindow.load_video_path.__get__(win)
        win.load_video_path("/movies/example.mkv")

        assert win.order == [
            ("navigate_to_editor",),
            ("load_video", "/movies/example.mkv"),
        ]

    def test_open_video_navigates_before_loading(self):
        # The "Open With" cold-start entry point goes through open_video.
        win = _FakeWindow()
        win.load_video_path = GsubWindow.load_video_path.__get__(win)
        GsubWindow.open_video(win, _FakeGFile("/movies/example.mkv"))

        assert win.order == [
            ("navigate_to_editor",),
            ("load_video", "/movies/example.mkv"),
        ]


class _FakeMpv:
    """Records loadfile calls; attributes are set like on the real handle."""

    def __init__(self, order=None):
        self.loaded = None
        self.pause = None
        self.sid = True
        self.order = order if order is not None else []

    def loadfile(self, path):
        self.loaded = path
        self.order.append(("loadfile", path))


class _FakeVideoArea:
    """GLArea stand-in with a controllable realize state."""

    def __init__(self, realized=False, order=None):
        self._realized = realized
        self.order = order if order is not None else []

    def get_realized(self):
        return self._realized

    def set_realized(self, value):
        self._realized = value

    def make_current(self):
        self.order.append("make_current")

    def queue_render(self):
        self.order.append("queue_render")


class _BarePlayer:
    """Just the state VideoPlayerWidget.load_video/_on_glarea_realize touch.

    Lets the real methods run headlessly (no GTK widget, no real mpv).
    """

    def __init__(self, realized=False, order=None):
        self.order = order if order is not None else []
        self._mpv = _FakeMpv(order=self.order)
        self.video_area = _FakeVideoArea(realized=realized, order=self.order)
        self.document = None
        self._disposed = False
        self._video_path = None
        self._pending_load_path = None
        self._render_ctx = None
        self._get_draw_fbo = None
        self._editor_sub_id = "stale"
        self._audio_tracks = ["stale"]
        self._subtitle_tracks = ["stale"]
        self._mpv_track_list = ["stale"]
        self._tracks_detected = True
        self._tracks_ready_emitted = True
        self._current_audio_track = 3
        self._current_subtitle_track = 4
        self.sync_calls = 0

    def _sync_editor_sub(self):
        self.sync_calls += 1

    def _on_mpv_update(self):
        pass


@pytest.mark.unit
class TestDeferredVideoLoad:
    """load_video defers the mpv loadfile until the GLArea is realized."""

    def test_defers_loadfile_when_not_realized(self):
        player = _BarePlayer(realized=False)
        VideoPlayerWidget.load_video(player, "/movies/example.mkv")

        assert player._mpv.loaded is None
        assert player._pending_load_path == "/movies/example.mkv"
        # Track state was still reset so stale state cannot leak.
        assert player._video_path == "/movies/example.mkv"
        assert player._editor_sub_id is None
        assert player._audio_tracks == []
        assert player._subtitle_tracks == []
        assert player._mpv_track_list == []
        assert player._tracks_detected is False
        assert player._tracks_ready_emitted is False
        assert player._current_audio_track == -1
        assert player._current_subtitle_track == -1

    def test_loads_immediately_when_realized(self):
        player = _BarePlayer(realized=True)
        VideoPlayerWidget.load_video(player, "/movies/example.mkv")

        assert player._mpv.loaded == "/movies/example.mkv"
        assert player._pending_load_path is None

    def test_pending_load_replayed_after_render_context_exists(self, monkeypatch):
        order = []

        class _FakeRenderContext:
            def __init__(self, mpv, api, opengl_init_params=None):
                order.append("render-context")

        monkeypatch.setattr(
            video_player_module, "_make_get_proc_address", lambda: (None, None)
        )
        monkeypatch.setattr(video_player_module, "MpvRenderContext", _FakeRenderContext)

        player = _BarePlayer(realized=False, order=order)
        player.load_video = VideoPlayerWidget.load_video.__get__(player)
        VideoPlayerWidget.load_video(player, "/movies/example.mkv")
        assert player._mpv.loaded is None

        # GTK has marked the area realized by the time the handler runs.
        player.video_area.set_realized(True)
        VideoPlayerWidget._on_glarea_realize(player, player.video_area)

        assert player._mpv.loaded == "/movies/example.mkv"
        assert player._pending_load_path is None
        assert player._render_ctx is not None
        # The deferred loadfile only runs after the render context exists.
        loadfile_at = order.index(("loadfile", "/movies/example.mkv"))
        assert order.index("render-context") < loadfile_at
