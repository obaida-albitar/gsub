"""Tests for the FFmpeg-subprocess fallback extraction backend.

All ``ffmpeg``/``ffprobe`` invocations are faked by swapping the module's
``subprocess`` reference for a stub (so the real process-wide ``subprocess``
module is untouched). The tests cover JSON parsing, codec-family mapping,
audio vs subtitle listing, error handling and the extraction command line
without needing the binaries on PATH.
"""

import json

import pytest

import gsub.extractors as extractors
from gsub.extractors import ffmpeg_fallback
from gsub.extractors.ffmpeg_fallback import (
    ExtractionError,
    _probe,
    extract_track,
    list_audio_streams,
    list_subtitle_tracks,
)


class _Completed:
    """Minimal subprocess.CompletedProcess stand-in."""

    def __init__(self, returncode=0, stdout=b"", stderr=b""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class _SubprocessStub:
    """Replaces ``ffmpeg_fallback.subprocess``; records every command."""

    PIPE = "PIPE"

    def __init__(self, responses):
        # responses: list of _Completed, or a callable(cmd) -> _Completed
        # (which may also raise, e.g. FileNotFoundError).
        self.responses = responses
        self.commands = []

    def run(self, cmd, **kwargs):
        self.commands.append((cmd, kwargs))
        result = self.responses(cmd) if callable(self.responses) else (
            self.responses.pop(0))
        if isinstance(result, Exception):
            raise result
        return result


def _ffprobe_json(streams):
    return _Completed(stdout=json.dumps({"streams": streams}).encode("utf-8"))


@pytest.fixture
def ffprobe_stub(monkeypatch):
    """Install a subprocess stub answering one ffprobe call."""
    stub = _SubprocessStub(lambda cmd: _ffprobe_json([]))
    monkeypatch.setattr(ffmpeg_fallback, "subprocess", stub)
    return stub


@pytest.mark.unit
class TestListSubtitleTracks:
    def test_parses_subtitle_streams_with_tags(self, ffprobe_stub):
        ffprobe_stub.responses = lambda cmd: _ffprobe_json([
            {"index": 0, "codec_name": "h264", "codec_type": "video"},
            {"index": 1, "codec_name": "ass", "codec_type": "subtitle",
             "tags": {"language": "eng", "title": "Signs"}},
            {"index": 2, "codec_name": "subrip", "codec_type": "subtitle",
             "tags": {"language": "ger"}},
        ])

        tracks = list_subtitle_tracks("/movie.mkv")

        assert [t.index for t in tracks] == [1, 2]
        assert [t.codec_family for t in tracks] == ["ass", "srt"]
        assert tracks[0].language == "eng"
        assert tracks[0].title == "Signs"
        assert tracks[1].title is None
        # ffprobe was asked for stream metadata in JSON form.
        probe_cmd, kwargs = ffprobe_stub.commands[0]
        assert probe_cmd[0] == "ffprobe"
        assert "json" in probe_cmd
        assert probe_cmd[-1] == "/movie.mkv"
        assert kwargs.get("timeout") == 30

    def test_known_subtitle_codec_families(self, ffprobe_stub):
        ffprobe_stub.responses = lambda cmd: _ffprobe_json([
            {"index": i, "codec_name": name, "codec_type": "subtitle"}
            for i, name in enumerate(
                ("ass", "ssa", "subrip", "srt", "mov_text", "text"))
        ])

        tracks = list_subtitle_tracks("x")
        assert [t.codec_family for t in tracks] == [
            "ass", "ssa", "srt", "srt", "srt", "srt"]

    def test_unknown_subtitle_codec_is_skipped(self, ffprobe_stub):
        # Image-based subtitle codecs cannot be copied to a text format.
        ffprobe_stub.responses = lambda cmd: _ffprobe_json([
            {"index": 3, "codec_name": "hdmv_pgs_subtitle",
             "codec_type": "subtitle"},
        ])

        assert list_subtitle_tracks("x") == []

    def test_no_streams_yields_empty_list(self, ffprobe_stub):
        assert list_subtitle_tracks("x") == []

    def test_missing_tags_key_is_tolerated(self, ffprobe_stub):
        ffprobe_stub.responses = lambda cmd: _ffprobe_json([
            {"index": 0, "codec_name": "subrip", "codec_type": "subtitle",
             "tags": None},
        ])
        tracks = list_subtitle_tracks("x")
        assert tracks[0].language is None
        assert tracks[0].title is None


@pytest.mark.unit
class TestListAudioStreams:
    def test_lists_only_audio_streams(self, ffprobe_stub):
        ffprobe_stub.responses = lambda cmd: _ffprobe_json([
            {"index": 0, "codec_name": "h264", "codec_type": "video"},
            {"index": 1, "codec_name": "aac", "codec_type": "audio",
             "tags": {"language": "jpn"}},
            {"index": 2, "codec_name": "ac3", "codec_type": "audio",
             "tags": {"language": "eng", "title": "Commentary"}},
            {"index": 3, "codec_name": "ass", "codec_type": "subtitle"},
        ])

        tracks = list_audio_streams("/movie.mkv")

        # Audio listing keeps container order and skips video/subtitles; the
        # audio path has no codec-family filter (any audio codec is valid).
        assert [t.index for t in tracks] == [1, 2]
        assert [t.codec for t in tracks] == ["aac", "ac3"]
        assert not hasattr(tracks[0], "codec_family")
        assert tracks[1].title == "Commentary"

    def test_no_audio_streams_yields_empty_list(self, ffprobe_stub):
        ffprobe_stub.responses = lambda cmd: _ffprobe_json([
            {"index": 0, "codec_name": "h264", "codec_type": "video"},
        ])
        assert list_audio_streams("x") == []


@pytest.mark.unit
class TestProbeErrors:
    def test_missing_ffprobe_binary(self, monkeypatch):
        stub = _SubprocessStub(lambda cmd: FileNotFoundError("ffprobe"))
        monkeypatch.setattr(ffmpeg_fallback, "subprocess", stub)
        with pytest.raises(ExtractionError, match="ffprobe not found"):
            _probe("x")

    def test_probe_failure_raises_with_stderr(self, monkeypatch):
        stub = _SubprocessStub(
            lambda cmd: _Completed(returncode=1, stderr=b"no such file"))
        monkeypatch.setattr(ffmpeg_fallback, "subprocess", stub)
        with pytest.raises(ExtractionError, match="no such file"):
            _probe("x")


@pytest.mark.unit
class TestExtractTrack:
    def _install(self, monkeypatch, ffmpeg_result):
        """Stub answering ffprobe with one ASS track and ffmpeg with the
        given result (or exception instance)."""
        def _respond(cmd):
            if cmd[0] == "ffprobe":
                return _ffprobe_json([
                    {"index": 2, "codec_name": "ass", "codec_type": "subtitle",
                     "tags": {"language": "eng"}}])
            return ffmpeg_result

        stub = _SubprocessStub(_respond)
        monkeypatch.setattr(ffmpeg_fallback, "subprocess", stub)
        return stub

    def test_successful_copy_extraction_returns_family(self, monkeypatch):
        stub = self._install(monkeypatch, _Completed(returncode=0))

        family = extract_track("/movie.mkv", 2, "/tmp/out.ass")

        assert family == "ass"
        ffmpeg_cmd, kwargs = stub.commands[1]
        assert ffmpeg_cmd[0] == "ffmpeg"
        # The track is mapped by container index and copied verbatim.
        assert ffmpeg_cmd[ffmpeg_cmd.index("-map") + 1] == "0:2"
        assert ffmpeg_cmd[ffmpeg_cmd.index("-c:s") + 1] == "copy"
        assert ffmpeg_cmd[-1] == "/tmp/out.ass"
        assert kwargs.get("timeout") == 60

    def test_unknown_track_index_raises(self, monkeypatch):
        stub = _SubprocessStub(lambda cmd: _ffprobe_json([
            {"index": 5, "codec_name": "subrip", "codec_type": "subtitle"}]))
        monkeypatch.setattr(ffmpeg_fallback, "subprocess", stub)
        with pytest.raises(ExtractionError, match="index 7"):
            extract_track("x", 7, "out.srt")

    def test_ffmpeg_failure_raises_with_stderr(self, monkeypatch):
        self._install(
            monkeypatch, _Completed(returncode=1, stderr=b"write error"))
        with pytest.raises(ExtractionError, match="write error"):
            extract_track("x", 2, "out.ass")

    def test_missing_ffmpeg_binary(self, monkeypatch):
        self._install(monkeypatch, FileNotFoundError("ffmpeg"))
        with pytest.raises(ExtractionError, match="ffmpeg not found"):
            extract_track("x", 2, "out.ass")


@pytest.mark.unit
class TestFacadeWithFallbackBackend:
    """The package facade must wrap fallback failures as ExtractionError."""

    @pytest.fixture(autouse=True)
    def _use_fallback(self, monkeypatch):
        monkeypatch.setattr(
            extractors, "_resolve_backend",
            lambda: (ffmpeg_fallback, "ffmpeg"),
        )

    def test_malformed_probe_json_is_wrapped(self, monkeypatch):
        # returncode 0 but garbage stdout: the raw JSONDecodeError from the
        # fallback must not leak through the public API.
        stub = _SubprocessStub(lambda cmd: _Completed(stdout=b"not json"))
        monkeypatch.setattr(ffmpeg_fallback, "subprocess", stub)

        with pytest.raises(ExtractionError):
            extractors.list_subtitle_tracks("/movie.mkv")

    def test_audio_failure_wrapped(self, monkeypatch):
        stub = _SubprocessStub(
            lambda cmd: _Completed(returncode=1, stderr=b"boom"))
        monkeypatch.setattr(ffmpeg_fallback, "subprocess", stub)

        with pytest.raises(ExtractionError, match="Failed to list audio"):
            extractors.list_audio_streams("/movie.mkv")

    def test_extract_failure_wrapped(self, monkeypatch):
        def _respond(cmd):
            if cmd[0] == "ffprobe":
                return _ffprobe_json([
                    {"index": 0, "codec_name": "ass", "codec_type": "subtitle"}])
            return _Completed(returncode=1, stderr=b"boom")

        stub = _SubprocessStub(_respond)
        monkeypatch.setattr(ffmpeg_fallback, "subprocess", stub)

        with pytest.raises(ExtractionError, match="Failed to extract"):
            extractors.extract_track("/movie.mkv", 0, "/tmp/out.ass")


class _FakeBackend:
    """Stand-in backend whose track list tests can reconfigure."""

    tracks = []
    families = {}

    @classmethod
    def list_subtitle_tracks(cls, path):
        return list(cls.tracks)

    @classmethod
    def extract_track(cls, path, index, out_path):
        return cls.families.get(index, "srt")


@pytest.mark.unit
class TestFacadeTrackMatching:
    """detect_format / extract_track_by_gst matching logic (fake backend)."""

    @pytest.fixture(autouse=True)
    def _fake_backend(self, monkeypatch):
        monkeypatch.setattr(
            extractors, "_resolve_backend", lambda: (_FakeBackend, "fake"))
        tracks = [
            extractors.SubtitleTrack(
                index=1, codec="ass", codec_family="ass", language="eng"),
            extractors.SubtitleTrack(
                index=2, codec="subrip", codec_family="srt", language="ger"),
        ]
        monkeypatch.setattr(_FakeBackend, "tracks", tracks)
        monkeypatch.setattr(_FakeBackend, "families", {1: "ass", 2: "srt"})

    def test_detect_format_by_language_and_codec(self):
        gst = {"index": 0, "language": "ger", "codec": "application/x-subrip"}
        assert extractors.detect_format("x.mkv", gst) == "srt"

    def test_detect_format_ass_ssa_interchangeable(self):
        # The container reports the ASS track as SSA-ish; families match.
        gst = {"index": 0, "language": "eng", "codec": "SubStation Alpha"}
        assert extractors.detect_format("x.mkv", gst) == "ass"

    def test_detect_format_positional_fallback(self):
        # No language/codec metadata: the text-track index addresses the Nth
        # subtitle stream in the container.
        gst = {"index": 1, "language": None, "codec": None}
        assert extractors.detect_format("x.mkv", gst) == "srt"

    def test_detect_format_single_track_fallback(self, monkeypatch):
        monkeypatch.setattr(_FakeBackend, "tracks", [
            extractors.SubtitleTrack(index=3, codec="ass", codec_family="ass"),
        ])
        gst = {"index": 9, "language": "zzz", "codec": None}
        assert extractors.detect_format("x.mkv", gst) == "ass"

    def test_detect_format_no_match_returns_none(self):
        gst = {"index": 9, "language": "zzz", "codec": None}
        assert extractors.detect_format("x.mkv", gst) is None

    def test_detect_format_probe_failure_uses_gst_codec(self, monkeypatch):
        def _boom(path):
            raise RuntimeError("cannot open")

        class _FailingBackend:
            list_subtitle_tracks = staticmethod(_boom)

        monkeypatch.setattr(
            extractors, "_resolve_backend", lambda: (_FailingBackend, "fake"))
        gst = {"index": 0, "language": "eng", "codec": "application/x-ass"}
        assert extractors.detect_format("x.mkv", gst) == "ass"

    def test_extract_track_by_gst_dispatches_to_matched_index(self, tmp_path):
        out = tmp_path / "out.ass"
        gst = {"index": 0, "language": "eng", "codec": "application/x-ass"}
        assert extractors.extract_track_by_gst(
            "x.mkv", gst, str(out)) == "ass"

    def test_extract_track_by_gst_unmatched_raises(self, tmp_path):
        # Two tracks, no positional match and no codec family: unsupported.
        gst = {"index": 5, "language": "zzz", "codec": "totally-unknown"}
        with pytest.raises(extractors.UnsupportedSubtitleCodec):
            extractors.extract_track_by_gst("x.mkv", gst, str(tmp_path / "o"))

    def test_extract_track_by_gst_known_family_missing_track(
            self, tmp_path, monkeypatch):
        # Codec family is recognised but no track matches language/index.
        gst = {"index": 5, "language": "zzz", "codec": "application/x-ass"}
        # Two SRT-only tracks: no language, family or positional match.
        monkeypatch.setattr(_FakeBackend, "tracks", [
            extractors.SubtitleTrack(
                index=9, codec="subrip", codec_family="srt"),
            extractors.SubtitleTrack(
                index=10, codec="subrip", codec_family="srt"),
        ])
        with pytest.raises(extractors.ExtractionError,
                           match="not found in the file"):
            extractors.extract_track_by_gst("x.mkv", gst, str(tmp_path / "o"))


@pytest.mark.unit
class TestPyavListing:
    """PyAV track/stream listing driven by a fake container."""

    @staticmethod
    def _stream(index, type_, name, language=None, title=None, extradata=b""):
        codec_context = type("CC", (), {"name": name, "extradata": extradata})()
        return type(
            "S", (), {
                "index": index, "type": type_, "codec_context": codec_context,
                "language": language, "title": title,
            })()

    @pytest.fixture(autouse=True)
    def _fake_av(self, monkeypatch):
        opened = []

        class _Container:
            def __init__(self, streams):
                self.streams = streams

            def close(self):
                opened.append("closed")

        holder = self

        def fake_open(path):
            opened.append("open")
            return _Container(list(holder.streams))

        import gsub.extractors.pyav_extractor as pyav

        monkeypatch.setattr(pyav.av, "open", fake_open)
        self.pyav = pyav
        self.opened = opened
        return self

    def test_list_subtitle_tracks_filters_and_resolves(self):
        self.streams = [
            self._stream(0, "video", "h264"),
            self._stream(1, "subtitle", "ass", extradata=b"[V4+ Styles]\n..."),
            self._stream(2, "subtitle", "ssa", extradata=b"[V4 Styles]"),
            self._stream(3, "subtitle", "subrip", language="ger"),
            self._stream(4, "subtitle", "hdmv_pgs_subtitle"),
        ]

        tracks = self.pyav.list_subtitle_tracks("x.mkv")

        assert [t.index for t in tracks] == [1, 2, 3]
        assert [t.codec_family for t in tracks] == ["ass", "ssa", "srt"]
        assert tracks[2].language == "ger"
        # The container is closed after listing.
        assert self.opened == ["open", "closed"]

    def test_list_audio_streams(self):
        self.streams = [
            self._stream(0, "video", "h264"),
            self._stream(1, "audio", "aac", language="jpn", title="Main"),
            self._stream(2, "subtitle", "ass"),
            self._stream(3, "audio", "flac"),
        ]

        tracks = self.pyav.list_audio_streams("x.mkv")

        assert [t.index for t in tracks] == [1, 3]
        assert [t.codec for t in tracks] == ["aac", "flac"]
        assert tracks[0].language == "jpn"
        assert tracks[0].title == "Main"
        assert self.opened == ["open", "closed"]
