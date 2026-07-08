"""FFmpeg-subprocess fallback extraction backend.

Used only when PyAV (``av``) is not importable. It relies on an ``ffmpeg`` /
``ffprobe`` binary being available on the system and copies the subtitle track
verbatim (``-c:s copy``) instead of transcoding it to SRT, preserving the
source format.
"""

from __future__ import annotations

import json
import subprocess

from . import (
    ExtractionError,
    SubtitleTrack,
    UnsupportedSubtitleCodec,
)


def _probe(path: str) -> list:
    try:
        out = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "stream=index,codec_name,codec_type,language:stream_tags=language,title",
                "-of",
                "json",
                path,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )
    except FileNotFoundError as exc:
        raise ExtractionError("ffprobe not found") from exc

    if out.returncode != 0:
        raise ExtractionError(out.stderr.decode("utf-8", "ignore"))

    data = json.loads(out.stdout.decode("utf-8", "ignore"))
    tracks = []
    for stream in data.get("streams", []):
        if stream.get("codec_type") != "subtitle":
            continue
        codec = stream.get("codec_name", "")
        family = {
            "ass": "ass",
            "ssa": "ssa",
            "subrip": "srt",
            "srt": "srt",
            "mov_text": "srt",
            "text": "srt",
        }.get(codec)
        if not family:
            continue
        tags = stream.get("tags", {}) or {}
        tracks.append(
            SubtitleTrack(
                index=int(stream["index"]),
                codec=codec,
                codec_family=family,
                language=tags.get("language"),
                title=tags.get("title"),
            )
        )
    return tracks


def list_subtitle_tracks(path: str) -> list:
    return _probe(path)


def extract_track(path: str, track_index: int, out_path: str) -> str:
    tracks = _probe(path)
    match = next((t for t in tracks if t.index == track_index), None)
    if match is None:
        raise ExtractionError(f"No subtitle track with index {track_index}")
    family = match.codec_family

    cmd = [
        "ffmpeg",
        "-i",
        path,
        "-map",
        f"0:{track_index}",
        "-c:s",
        "copy",
        "-y",
        out_path,
    ]
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
        )
    except FileNotFoundError as exc:
        raise ExtractionError("ffmpeg not found") from exc

    if result.returncode != 0:
        raise ExtractionError(result.stderr.decode("utf-8", "ignore"))
    return family
