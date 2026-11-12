"""Timing actions preserve cue content and participate in real undo history."""

from types import SimpleNamespace

import pytest

from gsub.commands import CommandManager
from gsub.models import SubtitleDocument, SubtitleEntry, SubtitleFormat, TimeCode
from gsub.timing import PlaybackSettings, cue_playback_bounds, timing_at_playhead
from gsub.timing_actions import TimingActionsMixin


def cue(start=1000, end=3000):
    return SubtitleEntry(1, TimeCode.from_milliseconds(start),
                         TimeCode.from_milliseconds(end), "{\\i1}Keep this", actor="Ana", layer=2)


@pytest.mark.parametrize("fmt,seconds,expected", [
    (SubtitleFormat.SRT, 1.2399, 1240),
    (SubtitleFormat.ASS, 1.2399, 1230),
    (SubtitleFormat.SSA, 1.2399, 1230),
    (SubtitleFormat.ASS, 1.29, 1290),
    (SubtitleFormat.SRT, -1, 0),
])
def test_start_from_playhead_preserves_end(fmt, seconds, expected):
    assert timing_at_playhead(cue(), seconds, "start", fmt) == (expected, 3000)


@pytest.mark.parametrize("fmt", list(SubtitleFormat))
def test_end_from_playhead_clamps_to_video_without_moving_start(fmt):
    assert timing_at_playhead(cue(), 20, "end", fmt, 4.0) == (1000, 4000)


@pytest.mark.parametrize("endpoint,seconds", [("start", 3), ("start", 4),
                                                ("end", 1), ("end", 0.5)])
def test_invalid_endpoint_change_is_rejected(endpoint, seconds):
    with pytest.raises(ValueError, match="Start time"):
        timing_at_playhead(cue(), seconds, endpoint, SubtitleFormat.SRT)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), None, "bad", True])
def test_invalid_playhead_cannot_mutate_document(bad):
    with pytest.raises(ValueError):
        timing_at_playhead(cue(), bad, "start", SubtitleFormat.SRT)


@pytest.mark.parametrize("arguments,expected", [
    ((100, 2000, 500, 500, 10), (0.0, 2.5)),
    ((1000, 9900, 500, 500, 10), (0.5, 10.0)),
    ((1000, 1010, 0, 0, 10), (1.0, 1.01)),
    ((1000, 3000, 0, 0, None), (1.0, 3.0)),
    ((1000, 3000, 500, 500, 0), (0.5, 3.5)),
])
def test_playback_bounds_use_context_and_clip_to_media(arguments, expected):
    assert cue_playback_bounds(*arguments) == expected


@pytest.mark.parametrize("arguments", [
    (1000, 1000), (-1, 2000), (3000, 2000),
    (1000, 2000, -1, 0), (1000, 2000, 0, 10_001),
    (1000, 2000, 0, 0, 0.9), (float("nan"), 2000),
])
def test_unplayable_cues_and_invalid_context_are_rejected(arguments):
    with pytest.raises(ValueError):
        cue_playback_bounds(*arguments)


@pytest.mark.parametrize("values", [{"speed": 0.1}, {"speed": float("nan")},
    {"speed": True}, {"pre_roll_ms": -1}, {"post_roll_ms": 10001},
    {"pre_roll_ms": 1.5}, {"post_roll_ms": True}])
def test_settings_reject_invalid_values(values):
    with pytest.raises(ValueError):
        PlaybackSettings(**values)


def test_preferences_round_trip_and_corrupt_fields_fall_back_independently():
    settings = PlaybackSettings(speed=0.75, pre_roll_ms=0, post_roll_ms=1000)
    assert PlaybackSettings.from_preferences(settings.to_preferences()) == settings
    assert PlaybackSettings.from_preferences({"playback_speed": "nan",
        "cue_pre_roll_ms": "bad", "cue_post_roll_ms": "1500"}) == PlaybackSettings(post_roll_ms=1500)


class WindowHarness(TimingActionsMixin):
    def __init__(self, fmt=SubtitleFormat.SRT):
        self.document = SubtitleDocument(fmt, entries=[cue()])
        self.current_video_file = "video.mkv"
        self.command_manager = CommandManager()
        self.messages = []
        self.positions = [0]
        self.subtitle_list = SimpleNamespace(
            get_selected_positions=lambda: self.positions,
            refresh_entry=lambda _p: None)
        self.editor_panel = SimpleNamespace(flush_pending_changes=lambda: None,
                                            set_entry=lambda _e, _p: None)
        self.video_player = SimpleNamespace(get_position=lambda: 1.2399, _duration=10,
            queue_subtitle_redraw=lambda: None, refresh_timeline_regions=lambda: None)

    def _show_toast(self, message):
        self.messages.append(message)

    def _update_title(self):
        pass

    def _document_mutated(self):
        pass


@pytest.mark.parametrize("fmt", list(SubtitleFormat))
def test_set_start_is_one_undo_step_and_preserves_content_and_ass_fields(fmt):
    window = WindowHarness(fmt)
    window._on_set_start_here()
    entry = window.document.entries[0]
    assert entry.start_time.total_milliseconds == (1240 if fmt == SubtitleFormat.SRT else 1230)
    assert entry.end_time.total_milliseconds == 3000
    assert (entry.text, entry.actor, entry.layer) == ("{\\i1}Keep this", "Ana", 2)
    assert window.command_manager.undo()
    assert entry.start_time.total_milliseconds == 1000
    assert not window.command_manager.can_undo()
    assert window.command_manager.redo()
    assert entry.start_time.total_milliseconds != 1000


def test_invalid_end_and_noop_do_not_add_undo_steps():
    window = WindowHarness()
    window.video_player.get_position = lambda: 0.5
    window._on_set_end_here()
    assert not window.command_manager.can_undo()
    assert "Start time" in window.messages[-1]
    window.video_player.get_position = lambda: 1.0
    window._on_set_start_here()
    assert not window.command_manager.can_undo()


@pytest.mark.parametrize("positions,video", [([], "v.mkv"), ([0, 1], "v.mkv"),
                                             ([2], "v.mkv"), ([0], None)])
def test_actions_require_one_valid_selection_and_a_video(positions, video):
    window = WindowHarness()
    window.positions, window.current_video_file = positions, video
    window._on_set_start_here()
    assert not window.command_manager.can_undo()
    assert window.messages


@pytest.mark.parametrize("attribute,value", [("_mpv", None), ("_pending_load_path", "video.mkv")])
def test_timing_action_waits_for_player_to_be_ready(attribute, value):
    window = WindowHarness()
    setattr(window.video_player, attribute, value)
    window._on_set_start_here()
    assert not window.command_manager.can_undo()
    assert "loading" in window.messages[-1]
