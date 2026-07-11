"""Subtitle format parsers."""

from typing import List, Optional, Tuple

from subtitle_editor.models import SubtitleDocument
from .srt_parser import SRTParser
from .ass_parser import ASSParser

__all__ = ['SRTParser', 'ASSParser', 'parse_subtitle_document']


def parse_subtitle_document(
    content: str, ext: str
) -> Tuple[Optional[SubtitleDocument], List[str]]:
    """Parse subtitle text into a document based on the file extension.

    Returns a ``(document, warnings)`` tuple. ``warnings`` is always a list:
    it is populated with sanitization notes for ASS/SSA input and is empty for
    SRT or unsupported extensions. For an unsupported extension the document is
    ``None`` so callers can surface an "unsupported format" message.

    This is kept free of any GTK/GIO dependencies so it can be unit-tested
    headlessly and reused by the file-opening flow.
    """
    warnings: List[str] = []
    ext = (ext or "").lower().lstrip('.')
    if ext == 'srt':
        return SRTParser.parse(content), warnings
    if ext in ('ass', 'ssa'):
        return ASSParser.parse(content, warnings), warnings
    return None, warnings
