"""Robust text decoding for subtitle files.

Subtitle files arrive in many encodings: UTF-8 (with or without a BOM),
UTF-16 (LE/BE, with or without a BOM), Western ANSI/Windows-1252, Shift-JIS,
etc. Using a plain ``bytes.decode('utf-8')`` raises ``UnicodeDecodeError`` on
anything else and, for UTF-8-with-BOM files, leaves a BOM that breaks
section detection in the ASS parser.

:func:`decode_subtitle_text` tries decoders in a sensible order and always
returns a usable ``str`` (falling back to Windows-1252 with replacement
characters) so loading never crashes.
"""

from __future__ import annotations

import codecs

# UTF-16 decoders are only attempted when an explicit BOM is present: decoding
# arbitrary bytes as UTF-16-LE/BE "succeeds" on almost any input but yields
# mojibake, which would mask the correct (e.g. cp1252) decoding.
_BOM_UTF8 = codecs.BOM_UTF8
_BOM_UTF16_LE = codecs.BOM_UTF16_LE
_BOM_UTF16_BE = codecs.BOM_UTF16_BE


def _try_charset_normalizer(raw: bytes) -> str | None:
    """Best-effort decode using charset-normalizer if it is installed."""
    try:
        from charset_normalizer import from_bytes
    except ImportError:  # pragma: no cover - depends on environment
        return None
    try:
        matches = from_bytes(raw).best()
    except Exception:  # pragma: no cover - defensive
        return None
    if matches is None:
        return None
    try:
        return str(matches)
    except Exception:  # pragma: no cover - defensive
        return None


def decode_subtitle_text(raw: bytes) -> str:
    """Decode raw subtitle ``bytes`` into text, tolerating any common encoding.

    Strategy (strict UTF-8 first, then charset sniffing, never crashing):
      1. UTF-8 with/without BOM (the common case; strict, so invalid bytes fail fast).
      2. UTF-16 only when an explicit BOM is present (avoids silent mojibake).
      3. charset-normalizer for cp1252 / Shift-JIS / other legacy encodings.
      4. Windows-1252 with replacement characters as a last resort.
    """
    if not raw:
        return ""

    # UTF-8 with BOM: strip it and decode as plain UTF-8.
    if raw[:3] == _BOM_UTF8:
        raw = raw[3:]
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            pass

    # UTF-8 without BOM (strict, so it fails on non-UTF-8 input).
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass

    # UTF-16 only when a BOM is present (definitive, no false positives).
    if raw[:2] in (_BOM_UTF16_LE, _BOM_UTF16_BE):
        try:
            return raw.decode("utf-16")
        except UnicodeDecodeError:
            pass

    # Windows-1252 is the dominant legacy encoding for Western subtitles, so
    # try a strict decode first. This also avoids charset-normalizer's tendency
    # to mislabel short cp1252 text as Latin-2.
    try:
        return raw.decode("cp1252")
    except UnicodeDecodeError:
        pass

    decoded = _try_charset_normalizer(raw)
    if decoded is not None:
        return decoded

    # Last resort: never raise. cp1252 with replacement covers any byte
    # sequence (used when it contained undefined cp1252 bytes too).
    return raw.decode("cp1252", errors="replace")
