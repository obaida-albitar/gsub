"""Pure-logic tests for the libmpv video player widget.

These tests deliberately avoid instantiating :class:`VideoPlayerWidget` (which
needs GTK4, libmpv and a display). They cover the framework-independent helpers
that were refactored out of the class: codec-family mapping, track-list
parsing, mpv-id -> list-position resolution, the PyAV stream mapping, time
formatting, the subtitle-scale and waveform preference persistence, frame
stepping and the timeline peaks handoff.
"""

import types

import pytest

pytest.importorskip("gi")
pytest.importorskip("mpv")

try:
    from subtitle_editor import resources

    resources.register_resources()
    from subtitle_editor.widgets.video_player import (
        VideoPlayerWidget,
        _family_matches,
        _mpv_codec_family,
    )
except Exception as exc:  # pragma: no cover - depends on GTK/libmpv stack
    pytest.skip(
        f"video_player module not importable in this environment: {exc}",
        allow_module_level=True,
    )


class _FakeTrack:
    """Minimal stand-in for ``extractors.SubtitleTrack``."""

    def __init__(self, index, codec_family, language=None):
        self.index = index
        self.codec_family = codec_family
        self.language = language


class _FakeAudioStream:
    """Minimal stand-in for ``extractors.AudioTrack``."""

    def __init__(self, index, codec=None, language=None):
        self.index = index
        self.codec = codec
        self.language = language


@pytest.mark.unit
class TestCodecFamilyHelpers:
    def test_mpv_codec_family_known(self):
        assert _mpv_codec_family("ass") == "ass"
        assert _mpv_codec_family("ssa") == "ssa"
        assert _mpv_codec_family("subrip") == "srt"
        assert _mpv_codec_family("srt") == "srt"
        assert _mpv_codec_family("text") == "srt"
        assert _mpv_codec_family("mov_text") == "srt"

    def test_mpv_codec_family_case_insensitive(self):
        assert _mpv_codec_family("SubRip") == "srt"
        assert _mpv_codec_family("ASS") == "ass"

    def test_mpv_codec_family_unknown(self):
        assert _mpv_codec_family("hdmv_pgs_subtitle") is None
        assert _mpv_codec_family(None) is None
        assert _mpv_codec_family("") is None

    def test_family_matches(self):
        assert _family_matches("ass", "ass")
        assert _family_matches("ass", "ssa")
        assert _family_matches("ssa", "ass")
        assert _family_matches("srt", "srt")
        assert not _family_matches("srt", "ass")
        assert not _family_matches("ass", None)
        assert not _family_matches(None, "srt")


@pytest.mark.unit
class TestFormatTime:
    def test_less_than_hour(self):
        assert VideoPlayerWidget._format_time(0) == "0:00.000"
        assert VideoPlayerWidget._format_time(65) == "1:05.000"
        assert VideoPlayerWidget._format_time(5.5) == "0:05.500"

    def test_at_least_one_hour(self):
        assert VideoPlayerWidget._format_time(3661) == "1:01:01.000"
        assert VideoPlayerWidget._format_time(7325) == "2:02:05.000"

    def test_fractional_truncated(self):
        assert VideoPlayerWidget._format_time(59.9) == "0:59.900"
        assert VideoPlayerWidget._format_time(59.9994) == "0:59.999"

    def test_rounding_cascades_to_next_second(self):
        assert VideoPlayerWidget._format_time(59.9999) == "1:00.000"
        assert VideoPlayerWidget._format_time(3599.99999) == "1:00:00.000"


@pytest.mark.unit
class TestParseTracks:
    @staticmethod
    def _track(tid, ttype, **kw):
        d = {"id": tid, "type": ttype}
        d.update(kw)
        return d

    def test_separates_audio_and_sub(self):
        tracks = [
            self._track(1, "video"),
            self._track(2, "audio", title="Eng", lang="eng", codec="aac"),
            self._track(3, "sub", title="Sub", lang="eng", codec="ass"),
            self._track(4, "sub", external=True, codec="ass"),  # editor doc
        ]
        audio, sub = VideoPlayerWidget._parse_tracks(tracks)
        assert len(audio) == 1
        assert audio[0]["id"] == 2
        assert audio[0]["index"] == 2
        assert audio[0]["language"] == "eng"
        # external subtitle excluded
        assert len(sub) == 1
        assert sub[0]["id"] == 3
        assert "external" not in sub[0]

    def test_empty_list(self):
        assert VideoPlayerWidget._parse_tracks([]) == ([], [])


@pytest.mark.unit
class TestSubtitleTrackPos:
    def test_resolve_by_id(self):
        tracks = [{"id": 11, "index": 11}, {"id": 12, "index": 12}]
        assert VideoPlayerWidget._subtitle_track_pos(tracks, 12) == 1

    def test_resolve_by_index(self):
        # index fallback when id does not match
        tracks = [{"id": 11, "index": 5}, {"id": 12, "index": 6}]
        assert VideoPlayerWidget._subtitle_track_pos(tracks, 6) == 1

    def test_no_match(self):
        tracks = [{"id": 11, "index": 11}]
        assert VideoPlayerWidget._subtitle_track_pos(tracks, 99) is None


@pytest.mark.unit
class TestBuildPyavMapping:
    @staticmethod
    def _mpv_sub(tid, codec, lang=None):
        return {"id": tid, "type": "sub", "codec": codec, "lang": lang}

    def test_positional_match(self, monkeypatch):
        mpv_subs = [self._mpv_sub(1, "ass"), self._mpv_sub(2, "subrip")]
        pyav = [_FakeTrack(0, "ass", "eng"), _FakeTrack(1, "srt", "eng")]
        monkeypatch.setattr(
            "subtitle_editor.widgets.video_player.list_subtitle_tracks",
            lambda path: pyav,
        )
        mapping = VideoPlayerWidget._build_pyav_mapping(mpv_subs, "/x.mkv")
        assert mapping == {0: pyav[0], 1: pyav[1]}

    def test_language_fallback_when_positions_disagree(self, monkeypatch):
        # mpv reports tracks in a different order than the container.
        mpv_subs = [
            self._mpv_sub(1, "ass", "jpn"),
            self._mpv_sub(2, "subrip", "eng"),
        ]
        pyav = [_FakeTrack(0, "srt", "eng"), _FakeTrack(1, "ass", "jpn")]
        monkeypatch.setattr(
            "subtitle_editor.widgets.video_player.list_subtitle_tracks",
            lambda path: pyav,
        )
        mapping = VideoPlayerWidget._build_pyav_mapping(mpv_subs, "/x.mkv")
        # position 0 (jpn/ass) maps to pyav[1]; position 1 (eng/srt) -> pyav[0]
        assert mapping[0] is pyav[1]
        assert mapping[1] is pyav[0]

    def test_codec_family_fallback_without_language(self, monkeypatch):
        mpv_subs = [self._mpv_sub(1, "ass")]
        pyav = [_FakeTrack(0, "ass")]
        monkeypatch.setattr(
            "subtitle_editor.widgets.video_player.list_subtitle_tracks",
            lambda path: pyav,
        )
        mapping = VideoPlayerWidget._build_pyav_mapping(mpv_subs, "/x.mkv")
        assert mapping == {0: pyav[0]}

    def test_empty_mpv_tracks(self, monkeypatch):
        monkeypatch.setattr(
            "subtitle_editor.widgets.video_player.list_subtitle_tracks",
            lambda path: [_FakeTrack(0, "ass")],
        )
        assert VideoPlayerWidget._build_pyav_mapping([], "/x.mkv") == {}

    def test_missing_stream_position_falls_back(self, monkeypatch):
        # mpv has two subs, container has only one (a stream is missing).
        mpv_subs = [self._mpv_sub(1, "ass"), self._mpv_sub(2, "subrip")]
        pyav = [_FakeTrack(0, "ass", "eng")]
        monkeypatch.setattr(
            "subtitle_editor.widgets.video_player.list_subtitle_tracks",
            lambda path: pyav,
        )
        mapping = VideoPlayerWidget._build_pyav_mapping(mpv_subs, "/x.mkv")
        # positional match for pos 0; pos 1 has no container stream -> no match.
        assert mapping == {0: pyav[0]}
        assert 1 not in mapping

    def test_listing_error_returns_empty(self, monkeypatch):
        def boom(path):
            raise RuntimeError("ffmpeg missing")

        monkeypatch.setattr(
            "subtitle_editor.widgets.video_player.list_subtitle_tracks", boom
        )
        assert VideoPlayerWidget._build_pyav_mapping(
            [self._mpv_sub(1, "ass")], "/x.mkv"
        ) == {}


@pytest.mark.unit
class TestBuildPyavAudioMap:
    """Mirrors TestBuildPyavMapping for the audio stream mapping."""

    @staticmethod
    def _mpv_audio(tid, codec=None, lang=None):
        return {"id": tid, "type": "audio", "codec": codec, "lang": lang}

    def test_positional_match(self, monkeypatch):
        mpv_audio = [
            self._mpv_audio(1, "aac", "eng"),
            self._mpv_audio(2, "ac3", "jpn"),
        ]
        pyav = [_FakeAudioStream(1, "aac", "eng"), _FakeAudioStream(3, "ac3", "jpn")]
        monkeypatch.setattr(
            "subtitle_editor.widgets.video_player.list_audio_streams",
            lambda path: pyav,
        )
        mapping = VideoPlayerWidget._build_pyav_audio_map(mpv_audio, "/x.mkv")
        # mpv track ids map to container stream indices, not positions.
        assert mapping == {1: 1, 2: 3}

    def test_language_fallback_when_positions_disagree(self, monkeypatch):
        # mpv reports the dubs in a different order than the container.
        mpv_audio = [
            self._mpv_audio(1, "aac", "jpn"),
            self._mpv_audio(2, "ac3", "eng"),
        ]
        pyav = [_FakeAudioStream(1, "ac3", "eng"), _FakeAudioStream(3, "aac", "jpn")]
        monkeypatch.setattr(
            "subtitle_editor.widgets.video_player.list_audio_streams",
            lambda path: pyav,
        )
        mapping = VideoPlayerWidget._build_pyav_audio_map(mpv_audio, "/x.mkv")
        assert mapping == {1: 3, 2: 1}

    def test_unmatched_track_left_out(self, monkeypatch):
        # Two mpv tracks, one container stream: only the match is mapped.
        mpv_audio = [self._mpv_audio(1, "aac"), self._mpv_audio(2, "ac3")]
        pyav = [_FakeAudioStream(1, "aac")]
        monkeypatch.setattr(
            "subtitle_editor.widgets.video_player.list_audio_streams",
            lambda path: pyav,
        )
        mapping = VideoPlayerWidget._build_pyav_audio_map(mpv_audio, "/x.mkv")
        assert mapping == {1: 1}
        assert 2 not in mapping

    def test_empty_audio_tracks(self, monkeypatch):
        monkeypatch.setattr(
            "subtitle_editor.widgets.video_player.list_audio_streams",
            lambda path: [_FakeAudioStream(0, "aac")],
        )
        assert VideoPlayerWidget._build_pyav_audio_map([], "/x.mkv") == {}

    def test_no_path_returns_empty(self):
        assert VideoPlayerWidget._build_pyav_audio_map(
            [self._mpv_audio(1, "aac")], ""
        ) == {}

    def test_listing_error_returns_empty(self, monkeypatch):
        def boom(path):
            raise RuntimeError("ffmpeg missing")

        monkeypatch.setattr(
            "subtitle_editor.widgets.video_player.list_audio_streams", boom
        )
        assert VideoPlayerWidget._build_pyav_audio_map(
            [self._mpv_audio(1, "aac")], "/x.mkv"
        ) == {}


@pytest.mark.unit
class TestSubtitleScalePreference:
    """The preference loader appends ``preferences.conf`` to the expanduser
    result, so the monkeypatch must return the *directory*."""

    @pytest.fixture
    def fake_home(self, tmp_path, monkeypatch):
        cfg_dir = tmp_path / "prefs"
        monkeypatch.setattr(
            "subtitle_editor.widgets.video_player.os.path.expanduser",
            lambda p: str(cfg_dir),
        )
        return cfg_dir

    def test_roundtrip(self, fake_home):
        VideoPlayerWidget._save_subtitle_scale_preference(0.8)
        assert VideoPlayerWidget._load_subtitle_scale_preference() == 0.8

    def test_clamped_on_load(self, fake_home):
        path = fake_home / "preferences.conf"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("subtitle_scale=5.0\n")
        assert VideoPlayerWidget._load_subtitle_scale_preference() == 1.5
        path.write_text("subtitle_scale=0.1\n")
        assert VideoPlayerWidget._load_subtitle_scale_preference() == 0.5

    def test_default_when_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "subtitle_editor.widgets.video_player.os.path.expanduser",
            lambda p: str(tmp_path / "nope"),
        )
        assert VideoPlayerWidget._load_subtitle_scale_preference() == 1.0

    def test_malformed_line_ignored(self, fake_home):
        path = fake_home / "preferences.conf"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("subtitle_scale=not-a-number\n")
        assert VideoPlayerWidget._load_subtitle_scale_preference() == 1.0

    def test_old_default_migrated(self, fake_home):
        path = fake_home / "preferences.conf"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("subtitle_scale=0.75\n")
        assert VideoPlayerWidget._load_subtitle_scale_preference() == 1.0

    def test_non_default_preserved(self, fake_home):
        path = fake_home / "preferences.conf"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("subtitle_scale=1.25\n")
        assert VideoPlayerWidget._load_subtitle_scale_preference() == 1.25


class _FakeMpv:
    """Records commands issued through the player's mpv handle."""

    def __init__(self):
        self.commands = []

    def command(self, name, *args):
        self.commands.append((name,) + args)


def _bare_player(mpv=None):
    """A lightweight stand-in ``self`` for the player's pure helpers.

    GObject widgets cannot be created without full initialisation, so method
    tests call the unbound function with this namespace providing exactly the
    attributes the method touches.
    """
    return types.SimpleNamespace(
        _mpv=mpv,
        _disposed=False,
        video_area=types.SimpleNamespace(queue_render=lambda: None),
    )


@pytest.mark.unit
class TestFrameStep:
    def test_forward_calls_frame_step(self):
        mpv = _FakeMpv()
        VideoPlayerWidget.frame_step(_bare_player(mpv))
        assert mpv.commands == [("frame-step",)]

    def test_back_calls_frame_back_step(self):
        mpv = _FakeMpv()
        VideoPlayerWidget.frame_step(_bare_player(mpv), back=True)
        assert mpv.commands == [("frame-back-step",)]

    def test_no_mpv_is_noop(self):
        VideoPlayerWidget.frame_step(_bare_player(None))  # must not raise


@pytest.mark.unit
class TestRegionsFromDocument:
    def test_none_document(self):
        assert VideoPlayerWidget._regions_from_document(None) == []

    def test_entries_converted_to_seconds_with_position(self):
        from subtitle_editor.models import SubtitleEntry, TimeCode

        doc = type("D", (), {})()
        doc.entries = [
            SubtitleEntry(
                1,
                TimeCode.from_milliseconds(500),
                TimeCode.from_milliseconds(2000),
                "a",
            ),
            SubtitleEntry(
                2,
                TimeCode.from_milliseconds(2500),
                TimeCode.from_milliseconds(5000),
                "b",
            ),
        ]
        regions = VideoPlayerWidget._regions_from_document(doc)
        assert regions == [(0.5, 2.0, 0), (2.5, 5.0, 1)]

    def test_inverted_entries_dropped(self):
        from subtitle_editor.models import SubtitleEntry, TimeCode

        doc = type("D", (), {})()
        doc.entries = [
            SubtitleEntry(1, TimeCode.from_milliseconds(2000),
                          TimeCode.from_milliseconds(2000), "zero"),
            SubtitleEntry(2, TimeCode.from_milliseconds(3000),
                          TimeCode.from_milliseconds(1000), "inverted"),
        ]
        assert VideoPlayerWidget._regions_from_document(doc) == []


@pytest.mark.unit
class TestRegionSignalsDeclared:
    def test_player_declares_region_signals(self):
        from gi.repository import GObject

        assert GObject.signal_lookup("region-adjusted", VideoPlayerWidget) != 0
        assert GObject.signal_lookup("region-selected", VideoPlayerWidget) != 0


@pytest.mark.unit
class TestApplyWaveformResult:
    class _FakeTimeline:
        def __init__(self):
            self.set_peaks_calls = []
            self.draws = 0

        def set_peaks(self, peaks, pps):
            self.set_peaks_calls.append((peaks, pps))

        def queue_draw(self):
            self.draws += 1

    def test_result_handed_to_widget(self):
        timeline = self._FakeTimeline()
        VideoPlayerWidget._apply_waveform_result(timeline, ([(-1, 1)], 100.0))
        assert timeline.set_peaks_calls == [([(-1, 1)], 100.0)]
        assert timeline.draws == 1

    def test_none_leaves_waveform_empty(self):
        timeline = self._FakeTimeline()
        VideoPlayerWidget._apply_waveform_result(timeline, None)
        assert timeline.set_peaks_calls == []
        assert timeline.draws == 0


class _FakeWaveformToggle:
    def __init__(self, active):
        self._active = active

    def get_active(self):
        return self._active


class _FakeWaveformTimeline:
    def __init__(self):
        self.clear_peaks_calls = 0

    def clear_peaks(self):
        self.clear_peaks_calls += 1


class _RecordingLoader:
    """Stands in for WaveformLoader; records starts and cancels."""

    instances = []

    def __init__(self, cache_dir=None):
        self.starts = []
        self.cancelled = False
        _RecordingLoader.instances.append(self)

    def start(self, path, duration_hint=None, stream_index=None):
        self.starts.append((path, duration_hint, stream_index))

    def cancel(self):
        self.cancelled = True


class _WaveformPlayerSelf:
    """Minimal stand-in ``self`` for the player's waveform helpers.

    The real methods are attached as plain functions so they bind to this
    object, letting the selection/restart logic run without a GTK widget.
    """

    _live_track_list = VideoPlayerWidget._live_track_list
    _selected_audio_track_id = VideoPlayerWidget._selected_audio_track_id
    _resolve_waveform_stream_index = VideoPlayerWidget._resolve_waveform_stream_index
    _audio_mapping_ready = VideoPlayerWidget._audio_mapping_ready
    _cancel_waveform_loader = VideoPlayerWidget._cancel_waveform_loader
    _poll_waveform_loader = VideoPlayerWidget._poll_waveform_loader
    _restart_waveform_load = VideoPlayerWidget._restart_waveform_load
    _start_waveform_load = VideoPlayerWidget._start_waveform_load
    _on_audio_track_changed = VideoPlayerWidget._on_audio_track_changed

    def __init__(self, mpv=None, toggle_active=True, current_audio=-1,
                 track_list=None, audio_map=None, pyav_video_path="/x.mkv",
                 probe_done=True, audio_tracks=None):
        self._mpv = mpv
        self._mpv_track_list = track_list or []
        self._video_path = "/x.mkv"
        self._duration = 10.0
        self._disposed = False
        self._pending_load_path = None
        self._current_audio_track = current_audio
        self._audio_tracks = (
            audio_tracks
            if audio_tracks is not None
            else [{"id": 1, "codec": "aac"}, {"id": 2, "codec": "ac3"}]
        )
        self._pyav_audio_map = {1: 1, 2: 3} if audio_map is None else audio_map
        self._pyav_video_path = pyav_video_path
        self._pyav_probe_done = probe_done
        self.waveform_toggle = _FakeWaveformToggle(toggle_active)
        self._timeline = _FakeWaveformTimeline()
        self._waveform_loader = None
        self._waveform_poll_id = None
        self.video_area = types.SimpleNamespace(queue_render=lambda: None)


@pytest.mark.unit
class TestWaveformStreamResolution:
    def test_explicit_selection_wins(self):
        player = _WaveformPlayerSelf(
            current_audio=2,
            track_list=[{"type": "audio", "id": 1, "selected": True}],
        )
        assert VideoPlayerWidget._resolve_waveform_stream_index(player) == 3

    def test_mpv_default_selection_from_track_list(self):
        # No explicit pick: mpv's own selection (language heuristics) is
        # read from the live track list.
        player = _WaveformPlayerSelf(
            track_list=[{"type": "audio", "id": 2, "selected": True}],
        )
        assert VideoPlayerWidget._resolve_waveform_stream_index(player) == 3

    def test_no_selection_falls_back_to_default_stream(self):
        player = _WaveformPlayerSelf(track_list=[])
        assert VideoPlayerWidget._resolve_waveform_stream_index(player) is None

    def test_unmapped_track_falls_back_to_default_stream(self):
        player = _WaveformPlayerSelf(current_audio=7)
        assert VideoPlayerWidget._resolve_waveform_stream_index(player) is None

    def test_stale_mapping_ignored(self):
        player = _WaveformPlayerSelf(current_audio=2, pyav_video_path="/old.mkv")
        assert VideoPlayerWidget._resolve_waveform_stream_index(player) is None

    def test_no_audio_tracks(self):
        player = _WaveformPlayerSelf(audio_tracks=[])
        assert VideoPlayerWidget._resolve_waveform_stream_index(player) is None


@pytest.mark.unit
class TestWaveformStartGating:
    """The decode starts only once the mpv<->PyAV audio mapping is ready."""

    @pytest.fixture
    def fake_loader(self, monkeypatch):
        _RecordingLoader.instances = []
        monkeypatch.setattr(
            "subtitle_editor.widgets.video_player.WaveformLoader",
            _RecordingLoader,
        )
        return _RecordingLoader

    def test_starts_with_resolved_stream_when_ready(self, fake_loader):
        player = _WaveformPlayerSelf(current_audio=2)
        VideoPlayerWidget._start_waveform_load(player)
        assert len(fake_loader.instances) == 1
        assert fake_loader.instances[0].starts == [("/x.mkv", 10.0, 3)]
        assert player._timeline.clear_peaks_calls == 1

    def test_waits_while_probe_pending(self, fake_loader):
        player = _WaveformPlayerSelf(probe_done=False)
        VideoPlayerWidget._start_waveform_load(player)
        assert fake_loader.instances == []

    def test_no_start_without_audio_tracks(self, fake_loader):
        player = _WaveformPlayerSelf(audio_tracks=[])
        VideoPlayerWidget._start_waveform_load(player)
        assert fake_loader.instances == []

    def test_no_start_while_load_pending(self, fake_loader):
        player = _WaveformPlayerSelf()
        player._pending_load_path = "/x.mkv"
        VideoPlayerWidget._start_waveform_load(player)
        assert fake_loader.instances == []

    def test_no_start_when_toggle_off(self, fake_loader):
        player = _WaveformPlayerSelf(toggle_active=False)
        VideoPlayerWidget._start_waveform_load(player)
        assert fake_loader.instances == []


@pytest.mark.unit
class TestWaveformRegeneration:
    """Changing the audio track regenerates the peaks for the new stream."""

    @pytest.fixture
    def fake_loader(self, monkeypatch):
        _RecordingLoader.instances = []
        monkeypatch.setattr(
            "subtitle_editor.widgets.video_player.WaveformLoader",
            _RecordingLoader,
        )
        return _RecordingLoader

    def test_track_change_starts_loader_for_new_stream(self, fake_loader):
        mpv = types.SimpleNamespace()
        player = _WaveformPlayerSelf(mpv=mpv)
        VideoPlayerWidget.set_audio_track(player, 2)
        assert player._current_audio_track == 2
        assert mpv.aid == 2
        assert len(fake_loader.instances) == 1
        assert fake_loader.instances[0].starts == [("/x.mkv", 10.0, 3)]
        assert player._timeline.clear_peaks_calls == 1
        assert player._waveform_loader is fake_loader.instances[0]

    def test_second_change_cancels_previous_loader(self, fake_loader):
        player = _WaveformPlayerSelf()
        VideoPlayerWidget.set_audio_track(player, 1)
        first = fake_loader.instances[0]
        VideoPlayerWidget.set_audio_track(player, 2)
        assert first.cancelled is True
        assert len(fake_loader.instances) == 2
        assert fake_loader.instances[1].starts == [("/x.mkv", 10.0, 3)]

    def test_no_restart_when_waveform_disabled(self, fake_loader):
        player = _WaveformPlayerSelf(toggle_active=False)
        VideoPlayerWidget.set_audio_track(player, 2)
        assert fake_loader.instances == []
        assert player._waveform_loader is None

    def test_no_restart_while_load_pending(self, fake_loader):
        player = _WaveformPlayerSelf()
        player._pending_load_path = "/x.mkv"
        VideoPlayerWidget.set_audio_track(player, 2)
        assert fake_loader.instances == []

    def test_disable_audio_track_still_records_selection(self, fake_loader):
        mpv = types.SimpleNamespace()
        player = _WaveformPlayerSelf(mpv=mpv)
        VideoPlayerWidget.set_audio_track(player, -1)
        assert player._current_audio_track == -1
        assert mpv.aid == -1
        # Restarted with the default stream (mpv selection is gone).
        assert len(fake_loader.instances) == 1
        assert fake_loader.instances[0].starts == [("/x.mkv", 10.0, None)]


@pytest.mark.unit
class TestWaveformPreference:
    """Same expanduser-directory monkeypatch pattern as the scale tests."""

    @pytest.fixture
    def fake_home(self, tmp_path, monkeypatch):
        cfg_dir = tmp_path / "prefs"
        monkeypatch.setattr(
            "subtitle_editor.widgets.video_player.os.path.expanduser",
            lambda p: str(cfg_dir),
        )
        return cfg_dir

    def test_default_off(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "subtitle_editor.widgets.video_player.os.path.expanduser",
            lambda p: str(tmp_path / "nope"),
        )
        assert VideoPlayerWidget._load_waveform_preference() is False

    def test_roundtrip(self, fake_home):
        VideoPlayerWidget._save_waveform_preference(True)
        assert VideoPlayerWidget._load_waveform_preference() is True
        VideoPlayerWidget._save_waveform_preference(False)
        assert VideoPlayerWidget._load_waveform_preference() is False

    def test_only_true_enables(self, fake_home):
        path = fake_home / "preferences.conf"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("waveform_enabled=true\n")
        assert VideoPlayerWidget._load_waveform_preference() is True
        path.write_text("waveform_enabled=false\n")
        assert VideoPlayerWidget._load_waveform_preference() is False
        path.write_text("waveform_enabled=banana\n")
        assert VideoPlayerWidget._load_waveform_preference() is False

    def test_keeps_other_preferences(self, fake_home):
        path = fake_home / "preferences.conf"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("subtitle_scale=1.25\n")
        VideoPlayerWidget._save_waveform_preference(True)
        assert "subtitle_scale=1.25" in path.read_text()
        assert "waveform_enabled=true" in path.read_text()
