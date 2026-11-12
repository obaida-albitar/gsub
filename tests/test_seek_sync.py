"""Seek completion reconciles paused frames without stale callback races."""

from types import SimpleNamespace
import time

import pytest

from gsub.resources import register_resources
from gsub.models import SubtitleDocument, SubtitleEntry, SubtitleFormat, TimeCode
from gsub.timing import PlaybackSettings

pytest.importorskip("gi")
pytest.importorskip("mpv")
register_resources()

from gsub.widgets import video_player as module  # noqa: E402
from gsub.widgets.video_player import VideoPlayerWidget as Player  # noqa: E402


class Label:
    def __init__(self):
        self.text = ""
        self.width = 0

    def set_text(self, text):
        self.text = text

    def set_width_chars(self, width):
        self.width = width


class Timeline:
    def __init__(self):
        self.position = 1.0
        self.duration = 10.0

    def set_position(self, position):
        self.position = position

    def set_duration(self, duration):
        self.duration = duration
        self.position = min(self.position, duration)


class Backend:
    def __init__(self):
        self.time_pos = 1.0
        self.seeking = False
        self.pause = True
        self.seeks = []
        self.commands = []
        self.fail = False

    def seek(self, position, **options):
        if self.fail:
            raise RuntimeError("decoder unavailable")
        self.seeks.append(position)
        self.seeking = True

    def command(self, command, *args):
        self.commands.append((command, *args))
        if command in ("frame-step", "frame-back-step"):
            self.pause = True
            self.time_pos += 1 / 30 if command == "frame-step" else -1 / 30

    def terminate(self):
        pass


class Harness:
    for name in ("seek", "get_position", "skip", "frame_step", "_on_mpv_time_pos",
                 "_on_mpv_seeking", "_on_seek_state_ui", "_update_position_ui",
                 "_on_timeline_seek_requested", "_on_timeline_position_picked",
                 "_on_timeline_scrub_started", "_on_timeline_scrub_ended",
                 "_on_eof_ui", "_on_mpv_eof", "pause", "_set_duration", "_on_mpv_duration",
                 "play_selected_cue", "clear_cue_playback", "_cue_bounds",
                 "_poll_cue_playback", "_check_cue_position", "_update_cue_loop_ui"):
        locals()[name] = getattr(Player, name)
    _format_time = staticmethod(Player._format_time)
    cue_looping = Player.cue_looping

    def __init__(self):
        self._mpv = Backend()
        self._video_path = "video.mkv"
        self._pending_load_path = None
        self._duration = 10.0
        self._disposed = False
        self._is_seeking = False
        self._timeline = Timeline()
        self.time_label = Label()
        self.duration_label = Label()
        self.video_area = SimpleNamespace(queue_render=lambda: None,
                                          get_realized=lambda: False)
        self.events = []
        self._cue_playback = None
        self._cue_poll_id = None
        self._selected_position = 0
        self._playback_settings = PlaybackSettings()
        self.document = SubtitleDocument(SubtitleFormat.SRT, entries=[
            SubtitleEntry(1, TimeCode.from_milliseconds(2000),
                          TimeCode.from_milliseconds(3000), "Cue")])

    def emit(self, *args):
        self.events.append(args)


@pytest.fixture
def clock(monkeypatch):
    state = SimpleNamespace(now=1_000_000, next_id=0, sources={}, removed=[], idle=[], priorities=[])
    def add(_ms, callback, *args):
        state.next_id += 1
        state.sources[state.next_id] = (callback, args)
        return state.next_id
    def remove(source):
        state.removed.append(source)
        state.sources.pop(source, None)
    monkeypatch.setattr(module.GLib, "timeout_add", add)
    monkeypatch.setattr(module.GLib, "source_remove", remove)
    def idle(callback, *args, **options):
        state.idle.append((callback, args))
        state.priorities.append(options.get("priority"))
    monkeypatch.setattr(module.GLib, "idle_add", idle)
    monkeypatch.setattr(module.GLib, "get_monotonic_time", lambda: state.now)
    return state


@pytest.mark.parametrize("paused", [False, True])
def test_seek_shows_target_immediately_without_changing_pause_state(clock, paused):
    player = Harness()
    player._mpv.pause = paused
    assert player.seek(3.14) is True
    assert player._timeline.position == 3.14
    assert player.time_label.text == "0:03.140"
    assert player._mpv.pause is paused
    assert player.get_position() == 3.14


@pytest.mark.parametrize("value", [None, "bad", True, float("inf"), float("nan")])
def test_invalid_seek_does_not_queue_or_change_marker(clock, value):
    player = Harness()
    assert player.seek(value) is False
    assert player._timeline.position == 1.0
    assert not clock.sources
    assert not player._mpv.seeks


@pytest.mark.parametrize("value,expected", [(-10, 0), (1000, 10), ("3.125", 3.125)])
def test_finite_requests_clamp_to_media(clock, value, expected):
    player = Harness()
    assert player.seek(value)
    assert player._mpv.seeks == [expected]
    assert player._timeline.position == expected


@pytest.mark.parametrize("state", ["unloaded", "pending-load", "disposed", "no-backend"])
def test_unavailable_player_rejects_seek(clock, state):
    player = Harness()
    if state == "unloaded":
        player._video_path = None
    elif state == "pending-load":
        player._pending_load_path = "video.mkv"
    elif state == "disposed":
        player._disposed = True
    else:
        player._mpv = None
    assert player.seek(3) is False
    assert not clock.sources


def test_latest_seek_owns_the_only_poll_and_old_callbacks_cannot_finish_it(clock):
    player = Harness()
    player.seek(3)
    old_generation, old_source = player._seek_generation, player._seek_poll_id
    old_callback, old_args = clock.sources[old_source]
    player.seek(7)
    newest_source = player._seek_poll_id
    assert old_source in clock.removed
    assert list(clock.sources) == [newest_source]
    assert old_callback(*old_args) is False
    player._on_seek_state_ui(False, old_generation)
    assert player._seek_poll_id == newest_source
    assert player._pending_seek["target"] == 7
    assert player._timeline.position == 7


def test_queued_preseek_and_midseek_position_events_cannot_rewind_completion(clock):
    player = Harness()
    player._on_mpv_time_pos("time-pos", 1.0)
    before_seek = clock.idle.pop()
    player.seek(3.14)
    before_seek[0](*before_seek[1])
    assert player._timeline.position == 3.14
    player._on_mpv_time_pos("time-pos", 1.2)
    during_seek = clock.idle.pop()
    during_seek[0](*during_seek[1])
    assert player.time_label.text == "0:03.140"
    player._mpv.time_pos, player._mpv.seeking = 3.1666667, False
    player._on_seek_state_ui(False, player._seek_generation)
    assert player._pending_seek is None
    assert player._timeline.position == 3.1666667
    assert player.time_label.text == "0:03.167"
    during_seek[0](*during_seek[1])
    assert player._timeline.position == 3.1666667
    player._on_mpv_time_pos("time-pos", 3.2)
    after_seek = clock.idle.pop()
    after_seek[0](*after_seek[1])
    assert player._timeline.position == 3.2


def test_seek_completion_reads_actual_frame_while_paused(clock):
    player = Harness()
    player.seek(3.14)
    generation = player._seek_generation
    assert Player._poll_seek_completion(player, generation) is True
    player._mpv.seeking = False
    player._mpv.time_pos = 3.1666667
    assert Player._poll_seek_completion(player, generation) is False
    assert player._mpv.pause
    assert player._timeline.position == player.get_position() == 3.1666667
    assert player.time_label.text == "0:03.167"
    assert not clock.sources


def test_missing_position_is_not_a_false_zero_completion_and_times_out(clock):
    player = Harness()
    player._mpv.time_pos = None
    player._last_actual_position = 1.25
    player.seek(8)
    player._mpv.seeking = False
    assert Player._poll_seek_completion(player, player._seek_generation) is True
    assert player._pending_seek is not None
    clock.now += 2_000_001
    assert Player._poll_seek_completion(player, player._seek_generation) is False
    assert player._timeline.position == 1.25
    assert player.time_label.text == "0:01.250"


def test_stuck_decoder_falls_back_to_actual_position_within_bound(clock):
    player = Harness()
    player.seek(8)
    player._mpv.time_pos = 2.0
    clock.now += 2_000_001
    assert Player._poll_seek_completion(player, player._seek_generation) is False
    assert player._timeline.position == 2.0
    assert player.time_label.text == "0:02.000"


def test_backend_rejection_clears_pending_state_and_restores_actual_position(clock):
    player = Harness()
    player._mpv.fail = True
    assert player.seek(8) is False
    assert player._pending_seek is None
    assert not clock.sources
    assert player._timeline.position == 1.0
    assert player._mpv.pause


def test_drag_release_publishes_final_marker_before_decoder_finishes(clock):
    player = Harness()
    player._on_timeline_scrub_started(None)
    player._on_timeline_seek_requested(None, 3.0)
    player._on_timeline_position_picked(None, 4.0)
    player._on_timeline_scrub_ended(None)
    assert player._timeline.position == 4.0
    assert player.time_label.text == "0:04.000"
    assert player._pending_seek["target"] == 4.0
    assert len(clock.sources) == 1
    player._mpv.time_pos, player._mpv.seeking = 4.0333333, False
    Player._poll_seek_completion(player, player._seek_generation)
    assert player._timeline.position == 4.0333333


def test_rapid_relative_nudges_accumulate_accepted_targets(clock):
    player = Harness()
    player.skip(100)
    player.skip(100)
    player.skip(100)
    assert player._mpv.seeks == pytest.approx([1.1, 1.2, 1.3])
    assert player._timeline.position == pytest.approx(1.3)
    assert len(clock.sources) == 1


def test_explicit_end_seek_pauses_at_end_and_old_eof_cannot_rewind_new_seek(clock):
    player = Harness()
    player.seek(10)
    end_generation = player._seek_generation
    player._on_eof_ui(end_generation)
    assert player._mpv.seeks == [10]
    player._mpv.seeking, player._mpv.time_pos = False, 9.9666667
    Player._poll_seek_completion(player, end_generation)
    player._on_eof_ui(end_generation)
    assert player._mpv.seeks == [10]
    assert player._mpv.pause
    player.seek(2)
    player._on_eof_ui(end_generation)
    assert player._mpv.seeks == [10, 2]


def test_new_video_cancels_poll_and_resets_optimistic_marker(clock):
    player = Harness()
    player.seek(8)
    old_generation = player._seek_generation
    old_source = player._seek_poll_id
    Player.load_video(player, "new.mkv")
    assert old_source in clock.removed
    assert not clock.sources
    assert player._timeline.position == player._timeline.duration == 0
    assert player.time_label.text == "0:00.000"
    player._update_position_ui(8, old_generation, 10)
    assert player._timeline.position == 0


def test_frame_step_cancels_pending_seek_and_reports_its_frame(clock):
    player = Harness()
    player.seek(8)
    player.frame_step()
    assert player._pending_seek is None
    assert not clock.sources
    player._update_position_ui(player._mpv.time_pos)
    assert player._timeline.position == pytest.approx(1 + 1 / 30)
    assert player._mpv.pause


def test_cue_preview_cancels_pending_normal_seek_before_arming(clock):
    player = Harness()
    player.seek(8)
    old_source = player._seek_poll_id
    old_callback, args = clock.sources[old_source]
    assert player.play_selected_cue(loop=True)
    assert player._pending_seek is None
    assert old_source in clock.removed
    assert old_callback(*args) is False
    assert player._cue_playback["bounds"] == (1.5, 3.5)


def test_disposal_invalidates_all_pending_seek_callbacks(clock):
    player = Harness()
    player.seek(8)
    generation = player._seek_generation
    player._redraw_source = None
    player._cancel_waveform_loader = lambda: None
    player._render_ctx = None
    player._temp_sub_path = None
    Player._on_widget_unrealize(player, None)
    assert player._disposed and player._pending_seek is None
    assert not clock.sources
    assert Player._poll_seek_completion(player, generation) is False


def test_duration_reserves_timestamp_precision_before_first_seek(clock):
    player = Harness()
    player._set_duration(75.0)
    assert player.time_label.width == len("1:15.000")
    assert player.time_label.text == "0:01.000"


def test_metadata_and_position_delivery_cannot_be_starved_by_render_idles(clock):
    player = Harness()
    player._on_mpv_duration("duration", 12.0)
    assert clock.priorities[-1] == module.GLib.PRIORITY_DEFAULT
    callback, args = clock.idle.pop()
    callback(*args)
    assert player._duration == 12.0
    player._on_mpv_time_pos("time-pos", 3.14)
    assert clock.priorities[-1] == module.GLib.PRIORITY_DEFAULT


def test_duration_callback_runs_even_when_default_priority_mainloop_stays_busy():
    player = Harness()
    player._duration = 0.0
    context = module.GLib.MainContext.default()
    # Render/frame-clock work can keep ordinary main-loop work continuously
    # ready. Metadata must not depend on an otherwise-idle GTK main loop.
    busy = module.GLib.timeout_add(0, lambda: True)
    try:
        player._on_mpv_duration("duration", 12.0)
        for _ in range(20):
            context.iteration(False)
            if player._duration == 12.0:
                break
        assert player._duration == 12.0
    finally:
        module.GLib.source_remove(busy)


def test_native_paused_seek_reconciles_to_decoded_frame_and_holds_end(tmp_path):
    """Paused native decoding must update both marker and timestamp."""
    av = pytest.importorskip("av")
    video = tmp_path / "seek-sync.mp4"
    with av.open(str(video), "w") as container:
        stream = container.add_stream("mpeg4", rate=30)
        stream.width, stream.height, stream.pix_fmt = 32, 32, "yuv420p"
        for _ in range(150):
            frame = av.VideoFrame(32, 32, "rgb24")
            frame.planes[0].update(bytes(frame.planes[0].buffer_size))
            container.mux(stream.encode(frame))
        container.mux(stream.encode())
    player = Harness()
    player._mpv = module.MPV(vo="null", ao="null", keep_open="yes", pause=True)
    player._video_path = str(video)
    player._duration = 5.0
    player._mpv.observe_property("time-pos", player._on_mpv_time_pos)
    player._mpv.observe_property("seeking", player._on_mpv_seeking)
    player._mpv.observe_property("eof-reached", player._on_mpv_eof)
    context = module.GLib.MainContext.default()
    def settle():
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            while context.pending():
                context.iteration(False)
            if player._pending_seek is None:
                # Drain already queued post-completion notifications too.
                for _ in range(10):
                    while context.pending():
                        context.iteration(False)
                    time.sleep(0.005)
                return
            time.sleep(0.005)
        pytest.fail("native seek did not settle")
    try:
        player._mpv.loadfile(str(video))
        player._mpv.wait_for_property("duration", lambda value: value and value > 0, timeout=5)
        assert player.seek(3.14)
        assert player._timeline.position == 3.14
        settle()
        actual = player._mpv.time_pos
        assert player._mpv.pause
        assert abs(actual - 3.14) <= 1 / 30 + 0.001
        assert player._timeline.position == pytest.approx(actual)
        assert player.time_label.text == Player._format_time(actual)
        assert player.seek(5.0)
        settle()
        assert player._mpv.pause
        assert player._timeline.position > 4.9
    finally:
        Player._cancel_pending_seek(player)
        player._disposed = True
        player._mpv.terminate()
