"""Pure-logic tests for the libmpv video player widget.

These tests deliberately avoid instantiating :class:`VideoPlayerWidget` (which
needs GTK4, libmpv and a display). They cover the framework-independent helpers
that were refactored out of the class: codec-family mapping, track-list
parsing, mpv-id -> list-position resolution, the PyAV stream mapping, time
formatting and the subtitle-scale preference persistence.
"""

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
        assert VideoPlayerWidget._format_time(0) == "0:00"
        assert VideoPlayerWidget._format_time(65) == "1:05"
        assert VideoPlayerWidget._format_time(5.5) == "0:05"

    def test_at_least_one_hour(self):
        assert VideoPlayerWidget._format_time(3661) == "1:01:01"
        assert VideoPlayerWidget._format_time(7325) == "2:02:05"

    def test_fractional_truncated(self):
        assert VideoPlayerWidget._format_time(59.9) == "0:59"


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
