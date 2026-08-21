"""Subtitle extraction from media containers.

This package extracts subtitle tracks from video files while preserving the
source format. ASS/SSA tracks keep all styling (fonts, colours, positions and
override codes) instead of being flattened to SRT, matching the fidelity of
tools such as ``mkvextract``.

The primary backend is :mod:`av` (PyAV), which bundles FFmpeg's shared
libraries inside its wheel, so no system FFmpeg installation is required. A
minimal FFmpeg-subprocess fallback is used only when PyAV is unavailable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

__all__ = [
    "SubtitleTrack",
    "AudioTrack",
    "ExtractionError",
    "UnsupportedSubtitleCodec",
    "list_subtitle_tracks",
    "list_audio_streams",
    "detect_format",
    "extract_track",
    "EXTENSION_FOR_FORMAT",
]


class ExtractionError(Exception):
    """Raised when a subtitle track cannot be extracted."""


class UnsupportedSubtitleCodec(ExtractionError):
    """Raised when a subtitle track uses an unsupported codec."""


@dataclass
class SubtitleTrack:
    """Metadata describing a single subtitle track in a container."""

    index: int
    codec: str
    codec_family: str  # 'ass', 'ssa' or 'srt'
    language: Optional[str] = None
    title: Optional[str] = None


@dataclass
class AudioTrack:
    """Metadata describing a single audio stream in a container."""

    index: int  # container stream index (what decoding addresses)
    codec: str
    language: Optional[str] = None
    title: Optional[str] = None


# Output file extension for each supported family.
EXTENSION_FOR_FORMAT = {
    "ass": ".ass",
    "ssa": ".ssa",
    "srt": ".srt",
}


# Mapping from PyAV / container codec names to our internal family.
_AV_CODEC_FAMILIES = {
    "ass": "ass",
    "ssa": "ssa",
    "subrip": "srt",
    "srt": "srt",
    "text": "srt",
    "mov_text": "srt",
}


def _av_family(codec_name: str) -> Optional[str]:
    return _AV_CODEC_FAMILIES.get((codec_name or "").lower())


def _gst_family(gst_codec: Optional[str]) -> Optional[str]:
    if not gst_codec:
        return None
    g = gst_codec.lower()
    # ASS / SSA: track discovery (mpv/GStreamer) may report "SubStation Alpha", "application/x-ass",
    # "application/x-ssa", etc.
    if "ssa" in g or "substation" in g or "ass" in g:
        return "ass"
    if "subrip" in g or "srt" in g or "sub" in g or "text" in g:
        return "srt"
    return None


def _resolve_backend():
    """Return the backend module, preferring PyAV."""
    try:
        from . import pyav_extractor as backend
        return backend, "pyav"
    except ImportError:
        from . import ffmpeg_fallback as backend
        return backend, "ffmpeg"


def list_subtitle_tracks(path: str) -> List[SubtitleTrack]:
    """List the subtitle tracks found in *path*.

    Returns an empty list when no subtitle tracks are present or the file
    cannot be opened.
    """
    backend, _ = _resolve_backend()
    try:
        return backend.list_subtitle_tracks(path)
    except Exception as exc:  # pragma: no cover - depends on environment
        raise ExtractionError(f"Failed to list subtitle tracks: {exc}") from exc


def list_audio_streams(path: str) -> List[AudioTrack]:
    """List the audio streams found in *path* (container order).

    Used to translate a player track selection into the container stream
    index the waveform decoder must target. Raises :class:`ExtractionError`
    when the file cannot be opened.
    """
    backend, _ = _resolve_backend()
    try:
        return backend.list_audio_streams(path)
    except Exception as exc:  # pragma: no cover - depends on environment
        raise ExtractionError(f"Failed to list audio streams: {exc}") from exc


def detect_format(path: str, gst_track_info: dict) -> Optional[str]:
    """Determine the output format for a track identified by generic track info

    *gst_track_info* is the dict produced by the video player
    (``{'index': ..., 'language': ..., 'codec': ...}``). The matching
    container track is located by language and/or codec family.

    Returns one of ``'ass'``, ``'ssa'``, ``'srt'`` or ``None`` when the track
    cannot be matched.
    """
    try:
        tracks = list_subtitle_tracks(path)
    except ExtractionError:
        return _gst_family(gst_track_info.get("codec"))
    match = _match_track(tracks, gst_track_info)
    return match.codec_family if match else _gst_family(gst_track_info.get("codec"))


def _family_matches(a: Optional[str], b: Optional[str]) -> bool:
    """True when two codec families are compatible for matching.

    ``ass`` and ``ssa`` are treated as interchangeable because they share the
    same container representation and both map to the app's ASS document type.
    """
    if a is None or b is None:
        return False
    if a == b:
        return True
    return a in ("ass", "ssa") and b in ("ass", "ssa")


def _match_track(tracks: List[SubtitleTrack], gst_track_info: dict) -> Optional[SubtitleTrack]:
    if not tracks:
        return None
    lang = (gst_track_info.get("language") or "").lower()
    fam = _gst_family(gst_track_info.get("codec"))

    if lang:
        for track in tracks:
            if (track.language or "").lower() == lang and (
                fam is None or _family_matches(track.codec_family, fam)
            ):
                return track
    if fam:
        for track in tracks:
            if _family_matches(track.codec_family, fam):
                return track

    # Fallbacks when language/codec metadata is missing or unrecognised.
    # The text-track index maps to the Nth subtitle stream in the
    # container, so use it positionally when available.
    idx = gst_track_info.get("index")
    if isinstance(idx, int) and 0 <= idx < len(tracks):
        return tracks[idx]
    if len(tracks) == 1:
        return tracks[0]
    return None


def extract_track(path: str, track_index: int, out_path: str) -> str:
    """Extract subtitle track *track_index* to *out_path*.

    *track_index* is the index reported by :func:`list_subtitle_tracks`
    (i.e. the container's own subtitle stream order).

    Returns the output format (``'ass'``, ``'ssa'`` or ``'srt'``).
    """
    backend, _ = _resolve_backend()
    try:
        return backend.extract_track(path, track_index, out_path)
    except UnsupportedSubtitleCodec:
        raise
    except Exception as exc:  # pragma: no cover - depends on environment
        raise ExtractionError(f"Failed to extract subtitle track: {exc}") from exc


def extract_track_by_gst(path: str, gst_track_info: dict, out_path: str) -> str:
    """Extract a subtitle track identified by generic track info.

    The matching container track is located by language and/or codec family
    (see :func:`_match_track`) and then extracted.

    Returns the output format (``'ass'``, ``'ssa'`` or ``'srt'``).
    """
    backend, _ = _resolve_backend()
    try:
        tracks = backend.list_subtitle_tracks(path)
    except Exception as exc:
        raise ExtractionError(f"Failed to inspect subtitle tracks: {exc}") from exc

    match = _match_track(tracks, gst_track_info)
    if match is None:
        family = _gst_family(gst_track_info.get("codec"))
        if family is None:
            raise UnsupportedSubtitleCodec(
                "Could not match the selected track to a container stream"
            )
        raise ExtractionError("Selected subtitle track was not found in the file")

    return backend.extract_track(path, match.index, out_path)
