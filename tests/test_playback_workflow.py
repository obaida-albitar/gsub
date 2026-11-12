"""Cue preview lifecycle, player failures, preferences and GTK control wiring."""

from types import SimpleNamespace
import time

import pytest

from gsub.models import SubtitleDocument, SubtitleEntry, SubtitleFormat, TimeCode
from gsub.resources import register_resources
from gsub.timing import PlaybackSettings

pytest.importorskip("gi")
pytest.importorskip("mpv")
register_resources()

from gi.repository import Adw, Gdk, Gtk  # noqa: E402
from gsub.widgets import video_player as player_module  # noqa: E402
from gsub.widgets.video_player import VideoPlayerWidget  # noqa: E402


class FakeMPV:
    def __init__(self, **kwargs):
        self.pause = True
        self.seeking = False
        self.time_pos = 9.0
        self.speed = 1.0
        self.seeks = []
        self.fail_property = None
        self.fail_seek = False

    def __setattr__(self, name, value):
        if name == getattr(self, "fail_property", None):
            raise RuntimeError("mpv property unavailable")
        object.__setattr__(self, name, value)

    def seek(self, target, **kwargs):
        if self.fail_seek:
            raise RuntimeError("seek failed")
        self.seeks.append(target)
        self.time_pos = target

    def observe_property(self, *args):
        pass


class PlayerHarness:
    """Real preview methods with controllable media and no renderer."""

    for name in ("play_selected_cue", "clear_cue_playback", "_cue_bounds",
                 "_poll_cue_playback", "_check_cue_position", "_refresh_cue_bounds",
                 "_update_cue_loop_ui", "get_position", "set_selected_position",
                 "set_playback_settings", "seek", "_on_eof_ui", "play", "toggle_play_pause"):
        locals()[name] = getattr(VideoPlayerWidget, name)
    cue_looping = VideoPlayerWidget.cue_looping

    def __init__(self):
        self._mpv = FakeMPV()
        self._disposed = False
        self._video_path = "video.mkv"
        self._pending_load_path = None
        self._duration = 10.0
        self._selected_position = 0
        self._playback_settings = PlaybackSettings()
        self._cue_playback = None
        self._cue_poll_id = None
        self._timeline = None
        self._loop_cue_button = None
        self.video_area = SimpleNamespace(queue_render=lambda: None,
                                          get_realized=lambda: False)
        self.document = SubtitleDocument(SubtitleFormat.SRT, entries=[
            SubtitleEntry(1, TimeCode.from_milliseconds(1000),
                TimeCode.from_milliseconds(2000), "Hello"),
            SubtitleEntry(2, TimeCode.from_milliseconds(4000),
                TimeCode.from_milliseconds(5000), "Next"),
        ])


@pytest.fixture
def player(monkeypatch):
    monkeypatch.setattr(player_module.GLib, "timeout_add", lambda *args: 123)
    monkeypatch.setattr(player_module.GLib, "source_remove", lambda *args: None)
    monkeypatch.setattr(player_module.GLib, "idle_add", lambda *args: None)
    monkeypatch.setattr(player_module, "read_preferences", lambda: {})
    monkeypatch.setattr(player_module, "write_preferences", lambda _prefs: None)
    return PlayerHarness()


def arm(player):
    player._check_cue_position(player._cue_playback["bounds"][0])
    assert player._cue_playback["armed"]
    assert not player._mpv.pause


def test_one_shot_ignores_old_position_then_plays_and_stops_at_cue_end(player):
    assert player.play_selected_cue()
    assert player._mpv.pause
    assert player._mpv.seeks == [0.5]
    player._check_cue_position(9.0)  # queued observer from before the seek
    assert player._cue_playback is not None and player._mpv.pause
    arm(player)
    player._check_cue_position(2.4)
    assert player._cue_playback is not None
    player._check_cue_position(2.51)
    assert player._cue_playback is None and player._mpv.pause
    assert player._mpv.seeks[-1] == 2.5
    assert player._cue_poll_id is None


def test_loop_uses_native_bounds_and_stays_active_at_boundary(player):
    assert player.play_selected_cue(loop=True)
    assert player.cue_looping
    assert (player._mpv.ab_loop_a, player._mpv.ab_loop_b) == (0.5, 2.5)
    assert player._mpv.ab_loop_count == "inf"
    arm(player)
    player._check_cue_position(2.5)
    assert player.cue_looping and not player._mpv.pause


def test_selecting_another_cue_stops_loop_and_disables_native_endpoints(player):
    player.play_selected_cue(loop=True)
    arm(player)
    player.set_selected_position(1)
    assert not player.cue_looping and player._mpv.pause
    assert (player._mpv.ab_loop_a, player._mpv.ab_loop_b) == ("no", "no")
    assert player.play_selected_cue()
    assert player._mpv.seeks[-1] == 3.5


def test_same_selection_keeps_loop_but_replaced_entry_cancels_it(player):
    player.play_selected_cue(loop=True)
    player.set_selected_position(0)
    assert player.cue_looping
    player.document.entries[0] = player.document.entries[1]
    player._refresh_cue_bounds()
    assert not player.cue_looping


def test_timing_edits_update_native_loop_and_reseek_when_outside(player):
    player.play_selected_cue(loop=True)
    arm(player)
    entry = player.document.entries[0]
    entry.start_time, entry.end_time = TimeCode.from_milliseconds(6000), TimeCode.from_milliseconds(7000)
    player._refresh_cue_bounds()
    assert (player._mpv.ab_loop_a, player._mpv.ab_loop_b) == (5.5, 7.5)
    assert player._mpv.seeks[-1] == 5.5
    assert player.cue_looping


def test_invalid_timing_after_edit_cancels_preview(player):
    player.play_selected_cue(loop=True)
    player.document.entries[0].end_time = TimeCode.from_milliseconds(500)
    player._refresh_cue_bounds()
    assert player._cue_playback is None
    assert player._mpv.pause


@pytest.mark.parametrize("change", ["no-video", "no-document", "no-selection", "pending-load", "disposed"])
def test_unavailable_media_or_selection_never_starts_preview(player, change):
    if change == "no-video":
        player._video_path = None
    elif change == "no-document":
        player.document = None
    elif change == "no-selection":
        player._selected_position = -1
    elif change == "pending-load":
        player._pending_load_path = "video.mkv"
    else:
        player._disposed = True
    assert not player.play_selected_cue()
    assert not player._mpv.seeks


@pytest.mark.parametrize("failure", ["speed", "ab_loop_count", "ab_loop_a", "ab_loop_b", "seek"])
def test_player_failure_cannot_leave_a_loop_running(player, failure):
    if failure == "seek":
        player._mpv.fail_seek = True
    else:
        player._mpv.fail_property = failure
    assert not player.play_selected_cue(loop=True)
    assert player._cue_playback is None
    assert player._mpv.pause


def test_failed_native_loop_cleanup_pauses_and_blocks_ordinary_resume(player):
    assert player.play_selected_cue(loop=True)
    arm(player)
    class BrokenLoopMPV(FakeMPV):
        def __setattr__(self, name, value):
            if name in ("ab_loop_a", "ab_loop_b"):
                raise RuntimeError("core unavailable")
            super().__setattr__(name, value)
    player._mpv = BrokenLoopMPV()
    player._mpv.pause = False
    assert not player.clear_cue_playback()
    assert player._mpv.pause
    player.play()
    assert player._mpv.pause
    player.toggle_play_pause()
    assert player._mpv.pause
    assert not player.play_selected_cue()


def test_property_reset_has_command_fallback(player):
    class CommandFallbackMPV(FakeMPV):
        def command(self, operation, name, value):
            assert operation == "set"
            object.__setattr__(self, name.replace("-", "_"), value)
    player._mpv = CommandFallbackMPV()
    player._mpv.fail_property = "ab_loop_a"
    assert player.clear_cue_playback()
    assert player._mpv.ab_loop_a == "no"


def test_seek_timeout_cancels_preview_instead_of_playing_old_audio(player, monkeypatch):
    player.play_selected_cue()
    requested = player._cue_playback["requested_at"]
    monkeypatch.setattr(player_module.GLib, "get_monotonic_time", lambda: requested + 5_000_001)
    player._check_cue_position(9.0)
    assert player._cue_playback is None
    assert player._mpv.pause


def test_manual_seek_exits_bounded_preview(player):
    player.play_selected_cue(loop=True)
    player.seek(6.0)
    assert player._cue_playback is None
    assert player._mpv.ab_loop_a == "no"
    assert player._mpv.time_pos == 6.0


def test_new_video_clears_loop_before_deferred_load(player):
    player.play_selected_cue(loop=True)
    VideoPlayerWidget.load_video(player, "another.mkv")
    assert player._cue_playback is None
    assert player._duration == 0
    assert player._pending_load_path == "another.mkv"


def test_preview_at_media_end_stays_at_end_instead_of_rewinding_to_zero(player):
    player.document.entries[0].end_time = TimeCode.from_milliseconds(10_000)
    player.play_selected_cue()
    player._on_eof_ui()
    assert player._cue_playback is None
    assert player._mpv.seeks[-1] == 10.0
    assert player._mpv.pause


def test_speed_and_context_preferences_merge_without_losing_other_preferences(player, monkeypatch):
    saved = []
    monkeypatch.setattr(player_module, "read_preferences", lambda: {"waveform_enabled": "true"})
    monkeypatch.setattr(player_module, "write_preferences", saved.append)
    settings = PlaybackSettings(speed=0.75, pre_roll_ms=0, post_roll_ms=1000)
    assert player.set_playback_settings(settings)
    assert player._mpv.speed == 0.75
    assert saved == [{"waveform_enabled": "true", **settings.to_preferences()}]
    player.play_selected_cue()
    assert player._cue_playback["bounds"] == (1.0, 3.0)


def test_failed_speed_change_preserves_previous_settings(player):
    player._mpv.fail_property = "speed"
    assert not player.set_playback_settings(PlaybackSettings(speed=0.75))
    assert player._playback_settings == PlaybackSettings()


def test_preference_write_failure_does_not_break_playback(player, monkeypatch):
    def fail(_prefs):
        raise OSError("read-only configuration")
    monkeypatch.setattr(player_module, "write_preferences", fail)
    assert player.set_playback_settings(PlaybackSettings(speed=0.75))
    assert player.play_selected_cue()


def test_compact_player_popover_exposes_timing_actions_and_restores_settings(monkeypatch):
    Gtk.init()
    Adw.init()
    if Gdk.Display.get_default() is None:
        pytest.skip("GTK display unavailable")
    monkeypatch.setattr(player_module, "MPV", FakeMPV)
    monkeypatch.setattr(player_module, "read_preferences", lambda: {
        "playback_speed": "0.75", "cue_pre_roll_ms": "100", "cue_post_roll_ms": "750"})
    saved = []
    monkeypatch.setattr(player_module, "write_preferences", saved.append)
    widget = VideoPlayerWidget()
    assert widget.cue_controls_button.get_popover() is not None
    assert widget._mpv.speed == 0.75
    assert widget.playback_speed_row.get_value() == 0.75
    assert widget.cue_pre_roll_row.get_value() == 100
    assert widget.cue_post_roll_row.get_value() == 750
    assert widget._loop_cue_button.get_action_name() == "win.loop-cue"
    widget.playback_speed_row.set_value(0.5)
    assert widget._mpv.speed == 0.5
    assert saved[-1]["playback_speed"] == "0.5"


def test_programmatic_playback_settings_update_visible_controls_once(monkeypatch):
    Gtk.init()
    Adw.init()
    if Gdk.Display.get_default() is None:
        pytest.skip("GTK display unavailable")
    prefs = {"playback_speed": "1.0", "cue_pre_roll_ms": "100",
             "cue_post_roll_ms": "750", "waveform_enabled": "true",
             "subtitle_scale": "1.1"}
    monkeypatch.setattr(player_module, "MPV", FakeMPV)
    monkeypatch.setattr(player_module, "read_preferences", lambda: dict(prefs))
    saved = []
    monkeypatch.setattr(player_module, "write_preferences", saved.append)
    widget = VideoPlayerWidget()
    settings = PlaybackSettings(speed=0.75, pre_roll_ms=200, post_roll_ms=1000)
    assert widget.set_playback_settings(settings)
    assert widget._mpv.speed == widget.playback_speed_row.get_value() == 0.75
    assert widget.cue_pre_roll_row.get_value() == 200
    assert widget.cue_post_roll_row.get_value() == 1000
    assert saved == [{**prefs, **settings.to_preferences()}]
    widget._mpv.fail_property = "speed"
    assert not widget.set_playback_settings(PlaybackSettings(speed=0.5))
    assert widget.playback_speed_row.get_value() == 0.75
    assert widget.cue_pre_roll_row.get_value() == 200
    assert widget.cue_post_roll_row.get_value() == 1000
    assert len(saved) == 1


@pytest.mark.parametrize("loop", [False, True])
def test_native_mpv_cue_preview_stops_or_loops_real_media(tmp_path, loop):
    """Exercise real libmpv seeking/speed/loop properties with a tiny video."""
    av = pytest.importorskip("av")
    video = tmp_path / "cue-preview.mp4"
    with av.open(str(video), "w") as container:
        stream = container.add_stream("mpeg4", rate=25)
        stream.width, stream.height, stream.pix_fmt = 32, 32, "yuv420p"
        for _ in range(25):
            frame = av.VideoFrame(32, 32, "rgb24")
            frame.planes[0].update(bytes(frame.planes[0].buffer_size))
            container.mux(stream.encode(frame))
        container.mux(stream.encode())
    player = PlayerHarness()
    player._mpv = player_module.MPV(vo="null", ao="null", keep_open="yes", pause=True)
    player._video_path = str(video)
    player._duration = 1.0
    player._playback_settings = PlaybackSettings(speed=0.75, pre_roll_ms=0, post_roll_ms=0)
    entry = player.document.entries[0]
    entry.start_time = TimeCode.from_milliseconds(100)
    entry.end_time = TimeCode.from_milliseconds(250)
    try:
        player._mpv.loadfile(str(video))
        player._mpv.wait_for_property("duration", lambda value: value and value > 0, timeout=5)
        assert player.play_selected_cue(loop=loop)
        context = player_module.GLib.MainContext.default()
        deadline = time.monotonic() + 2.0
        armed_at = None
        positions = []
        while time.monotonic() < deadline:
            while context.pending():
                context.iteration(False)
            preview = player._cue_playback
            if preview is None:
                break
            if preview["armed"] and armed_at is None:
                armed_at = time.monotonic()
            if preview["armed"]:
                positions.append(player.get_position())
            if loop and armed_at and time.monotonic() - armed_at > 0.65:
                break
            time.sleep(0.005)
        assert player._mpv.speed == 0.75
        if loop:
            assert player.cue_looping and not player._mpv.pause
            assert player._mpv.ab_loop_a == 0.1
            assert player._mpv.ab_loop_b == 0.25
            # Audio-only mpv may briefly report 0 while resetting the loop.
            assert any(0.09 <= position <= 0.3 for position in positions), positions
            assert max(positions) <= 0.35, positions
        else:
            assert player._cue_playback is None
            assert player._mpv.pause
            player._mpv.wait_for_property("time-pos",
                lambda value: value is not None and abs(value - 0.25) < 0.05,
                timeout=2)
            assert abs(player.get_position() - 0.25) < 0.05
    finally:
        player.clear_cue_playback(pause=True)
        player._mpv.terminate()
