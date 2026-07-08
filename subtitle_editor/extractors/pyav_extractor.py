"""PyAV (``av``) based subtitle extraction backend.

PyAV wraps FFmpeg's libraries and ships them inside its wheel, so no system
FFmpeg binary is required. For ASS/SSA tracks we reconstruct a valid ``.ass`` /
``.ssa`` file from the stream's ``CodecPrivate`` (the ``[Script Info]``,
``[V4+ Styles]`` and ``[Events]`` header, which may already contain static
``Comment:`` lines) followed by the timed ``Dialogue:`` lines taken from each
packet. Start/End timestamps are derived from the packet's presentation
timestamp and duration because the packet payload only carries the remaining
event fields. This matches the output of ``mkvextract``.

For text based tracks (SubRip, MOV text, ...) we rebuild an SRT file from the
packet timestamps and payload.
"""

from __future__ import annotations

import av
from fractions import Fraction

from . import (
    ExtractionError,
    SubtitleTrack,
    UnsupportedSubtitleCodec,
)


def _resolve_family(stream) -> str:
    """Determine the output family for a PyAV subtitle stream.

    PyAV reports both ASS (``S_TEXT/ASS``) and SSA (``S_TEXT/SSA``) tracks as
    codec name ``"ssa"``. To pick the correct ``.ass`` vs ``.ssa`` extension we
    inspect the stream's ``CodecPrivate``: a ``[V4+ Styles]`` section means the
    track is true ASS (v4+), otherwise it is SSA v4.
    """
    name = (stream.codec_context.name or "").lower()
    if name in ("subrip", "srt", "text", "mov_text"):
        return "srt"
    if name in ("ass", "ssa"):
        extra = stream.codec_context.extradata or b""
        if b"[V4+ Styles]" in extra:
            return "ass"
        if b"[V4 Styles]" in extra:
            return "ssa"
        # Fall back to the codec name when the header is absent.
        return "ass" if name == "ass" else "ssa"
    raise UnsupportedSubtitleCodec(
        f"Unsupported subtitle codec: {stream.codec_context.name}"
    )


def list_subtitle_tracks(path: str) -> list:
    container = av.open(path)
    try:
        tracks = []
        for stream in container.streams:
            if stream.type != "subtitle":
                continue
            try:
                family = _resolve_family(stream)
            except UnsupportedSubtitleCodec:
                continue
            tracks.append(
                SubtitleTrack(
                    index=stream.index,
                    codec=stream.codec_context.name,
                    codec_family=family,
                    language=stream.language,
                    title=getattr(stream, "title", None),
                )
            )
        return tracks
    finally:
        container.close()


def _fmt_ass_time(seconds: Fraction) -> str:
    """Format a duration in seconds as ``H:MM:SS.cc`` (centiseconds)."""
    if seconds is None:
        return "0:00:00.00"
    total = float(seconds)
    if total < 0:
        total = 0.0
    hours = int(total // 3600)
    minutes = int((total % 3600) // 60)
    secs = total % 60
    return f"{hours}:{minutes:02d}:{secs:05.2f}"


def _fmt_srt_time(seconds: Fraction) -> str:
    """Format a duration in seconds as ``HH:MM:SS,mmm`` (SRT style)."""
    if seconds is None:
        return "00:00:00,000"
    total = float(seconds)
    if total < 0:
        total = 0.0
    hours = int(total // 3600)
    minutes = int((total % 3600) // 60)
    secs = total % 60
    int_part = int(secs)
    frac = int(round((secs - int_part) * 1000))
    if frac == 1000:
        int_part += 1
        frac = 0
    return f"{hours:02d}:{minutes:02d}:{int_part:02d},{frac:03d}"


def _reconstruct_ass_line(raw: str, pts: Fraction, duration: Fraction) -> str:
    """Build a ``Dialogue:`` line from a raw ASS packet payload.

    The raw payload omits the ``Dialogue:``/``Comment:`` prefix and the
    Start/End timestamps, and prepends a Matroska read-order field. The event
    fields therefore are laid out as::

        ReadOrder, Layer, Style, Name, MarginL, MarginR, MarginV, Effect, Text
    """
    line = raw.strip()
    if line.startswith("Dialogue:") or line.startswith("Comment:"):
        line = line.split(":", 1)[1].strip()

    parts = line.split(",")
    if len(parts) < 8:
        # Malformed/short payload: emit verbatim inside a Dialogue line.
        return f"Dialogue: {line}"

    rest = parts[2:]  # drop ReadOrder and Layer
    layer = parts[1]
    style, name, margin_l, margin_r, margin_v, effect = rest[0:6]
    text = ",".join(rest[6:])

    start = _fmt_ass_time(pts)
    end = _fmt_ass_time(pts + duration if pts is not None else None)
    return (
        f"Dialogue: {layer},{start},{end},{style},{name},"
        f"{margin_l},{margin_r},{margin_v},{effect},{text}"
    )


def _write_ass(container, stream, out_path: str) -> None:
    time_base = stream.time_base or Fraction(1, 1000)
    extra = stream.codec_context.extradata
    if extra:
        header = extra.decode("utf-8-sig")
    else:
        header = ""

    header = header.replace("\r\n", "\n").replace("\n", "\r\n")
    if header and not header.endswith("\r\n"):
        header += "\r\n"

    if "[Events]" not in header:
        header += "\r\n[Events]\r\n"
        header += (
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, "
            "MarginV, Effect, Text\r\n"
        )

    lines = [header]
    for packet in container.demux(stream):
        data = bytes(packet)
        if not data:
            continue
        raw = data.decode("utf-8", "replace")
        pts = packet.pts * time_base if packet.pts is not None else None
        dur = packet.duration * time_base if packet.duration is not None else None
        lines.append(_reconstruct_ass_line(raw, pts, dur) + "\r\n")

    with open(out_path, "w", encoding="utf-8-sig", newline="") as fh:
        fh.write("".join(lines))


def _write_srt(container, stream, out_path: str) -> None:
    time_base = stream.time_base or Fraction(1, 1000)
    blocks = []
    index = 1
    for packet in container.demux(stream):
        data = bytes(packet)
        if not data:
            continue
        text = data.decode("utf-8", "replace").replace("\r\n", "\n").strip("\n")
        if not text:
            continue
        start = _fmt_srt_time(
            packet.pts * time_base if packet.pts is not None else None
        )
        end = _fmt_srt_time(
            (packet.pts + packet.duration) * time_base
            if packet.pts is not None and packet.duration is not None
            else None
        )
        blocks.append(f"{index}\n{start} --> {end}\n{text}\n")
        index += 1

    with open(out_path, "w", encoding="utf-8", newline="") as fh:
        fh.write("\n".join(blocks))


def extract_track(path: str, track_index: int, out_path: str) -> str:
    container = av.open(path)
    try:
        stream = None
        for s in container.streams:
            if s.type == "subtitle" and s.index == track_index:
                stream = s
                break
        if stream is None:
            raise ExtractionError(f"No subtitle track with index {track_index}")

        family = _resolve_family(stream)
        if family in ("ass", "ssa"):
            _write_ass(container, stream, out_path)
        else:
            _write_srt(container, stream, out_path)
        return family
    finally:
        container.close()
