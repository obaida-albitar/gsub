"""Formatting-aware text transformations used by subtitle editing commands.

The model stores line breaks as newlines for every format; the ASS serializer
converts them to ``\\N`` on disk. None of these helpers changes document state.
"""

from dataclasses import dataclass
import html
import re

from gsub.models import SubtitleFormat
from gsub.parsers.ass_tags import (
    BLOCK_PATTERN,
    extract_override_tags,
    has_unbalanced_braces,
)


_HTML_TAG = re.compile(r"</?([A-Za-z][\w:-]*)(?:\s[^<>]*)?/?>")
_ENTITY = re.compile(r"&(?:#[0-9]+|#x[0-9A-Fa-f]+|[A-Za-z][A-Za-z0-9]+);")
_TIMED_TAGS = {"t", "move", "fad", "fade", "k", "kf", "ko", "kt", "p", "pbo"}
_GLOBAL_TAGS = {"pos", "org", "clip", "iclip", "an", "a", "q", "wrapstyle"}
_SRT_CONTAINER_TAGS = {"b", "i", "u", "s", "strike", "font", "span"}


def is_ass(format_: SubtitleFormat) -> bool:
    return format_ in (SubtitleFormat.ASS, SubtitleFormat.SSA)


@dataclass(frozen=True)
class _Piece:
    raw: str
    visible: str


def _pieces(text: str, format_: SubtitleFormat) -> list[_Piece]:
    """Tokenize markup and escape sequences without rewriting their spelling."""
    result = []
    offset = 0
    ass = is_ass(format_)
    while offset < len(text):
        token = (BLOCK_PATTERN.match(text, offset) if ass
                 else _HTML_TAG.match(text, offset))
        if token:
            result.append(_Piece(token.group(), ""))
            offset = token.end()
            continue
        if ass and text[offset:offset + 2] in (r"\N", r"\n", r"\h"):
            raw = text[offset:offset + 2]
            result.append(_Piece(raw, "\u00a0" if raw == r"\h" else "\n"))
            offset += 2
            continue
        entity = _ENTITY.match(text, offset) if not ass else None
        if entity:
            result.append(_Piece(entity.group(), html.unescape(entity.group())))
            offset = entity.end()
            continue
        result.append(_Piece(text[offset], text[offset]))
        offset += 1
    return result


def visible_text(text: str, format_: SubtitleFormat) -> str:
    """Return text used to decide whether a split has two nonempty sides."""
    return "".join(piece.visible for piece in _pieces(text, format_))


def _check_ass(text: str, *, retiming: bool) -> None:
    if has_unbalanced_braces(text):
        raise ValueError("Fix the unbalanced ASS formatting braces before editing this subtitle.")
    names = {tag.name.lower() for tag in extract_override_tags(text)}
    unsupported = _TIMED_TAGS if retiming else {"p", "pbo", "k", "kf", "ko", "kt"}
    if names & unsupported:
        raise ValueError(
            "This subtitle contains drawing, karaoke, or timed ASS effects; "
            "edit those effects manually before using this operation."
        )


def _srt_stack(text: str, end: int | None = None) -> list[tuple[str, str]]:
    """Validate nested SRT tags, returning tags still open at ``end``."""
    stack = []
    at_end = None
    for match in _HTML_TAG.finditer(text):
        if end is not None and at_end is None and match.start() >= end:
            at_end = list(stack)
        raw, name = match.group(), match.group(1).lower()
        if name not in _SRT_CONTAINER_TAGS:
            raise ValueError(f"The <{name}> tag cannot be split safely.")
        if raw.endswith("/>"):
            raise ValueError("Self-closing formatting tags cannot be split safely.")
        if raw.startswith("</"):
            if not stack or stack[-1][0] != name:
                raise ValueError("Fix the unbalanced subtitle formatting tags before splitting.")
            stack.pop()
        else:
            stack.append((name, raw))
    if end is not None and at_end is None:
        at_end = list(stack)
    if stack:
        raise ValueError("Fix the unbalanced subtitle formatting tags before splitting.")
    return at_end or []


def split_text(text: str, format_: SubtitleFormat, offset: int) -> tuple[str, str]:
    """Split at an editor offset, preserving static formatting on both sides.

    ASS editor offsets omit override blocks. SRT editor offsets include the
    original markup because its text editor displays that markup directly.
    """
    if not isinstance(offset, int):
        raise ValueError("Choose a text position inside the subtitle.")
    if is_ass(format_):
        _check_ass(text, retiming=True)
        clean_offset = 0
        raw_offset = 0
        cut = None
        history = []
        for piece in _pieces(text, format_):
            if clean_offset == offset:
                cut = raw_offset
                break
            if piece.visible:
                # ASS escape sequences occupy two editor characters, although
                # their rendered representation is a single character.
                clean_offset += len(piece.raw)
            else:
                history.append(piece.raw)
            raw_offset += len(piece.raw)
            if clean_offset > offset:
                raise ValueError("Place the cursor outside the ASS escape sequence.")
        if cut is None:
            if clean_offset == offset:
                cut = len(text)
            else:
                raise ValueError("Choose a text position inside the subtitle.")
        left = text[:cut].rstrip()
        right = text[cut:].lstrip()

        # Positioning and alignment apply to the entire ASS event, even when
        # their block appears after the cursor. Keep that effect on the first
        # half as well. Conflicting duplicate global tags are ambiguous across
        # renderers, so require the user to resolve them first.
        globals_seen = {}
        left_globals = []
        for block in BLOCK_PATTERN.finditer(text):
            for tag in extract_override_tags(block.group()):
                if tag.name not in _GLOBAL_TAGS:
                    continue
                previous = globals_seen.setdefault(tag.name, tag.raw)
                if previous != tag.raw:
                    raise ValueError("Resolve conflicting ASS position/alignment tags before splitting.")
                if block.start() >= cut:
                    left_globals.append(tag.raw)
        if left_globals:
            left = "{" + "".join(left_globals) + "}" + left
        right = "".join(history) + right
    else:
        if not 0 <= offset <= len(text):
            raise ValueError("Choose a text position inside the subtitle.")
        for pattern in (_HTML_TAG, _ENTITY):
            if any(match.start() < offset < match.end() for match in pattern.finditer(text)):
                raise ValueError("Place the cursor outside the formatting tag or character entity.")
        opened = _srt_stack(text, offset)
        left = text[:offset].rstrip()
        right = text[offset:].lstrip()
        left += "".join(f"</{name}>" for name, _raw in reversed(opened))
        right = "".join(raw for _name, raw in opened) + right
    if not visible_text(left, format_).strip() or not visible_text(right, format_).strip():
        raise ValueError("Place the cursor between two nonempty parts of the subtitle.")
    return left, right


def ass_global_tags(text: str) -> tuple[str, ...]:
    """Conservative signature for formatting that applies to an entire event."""
    return tuple(tag.raw for tag in extract_override_tags(text) if tag.name in _GLOBAL_TAGS)


def merge_texts(texts: list[str], format_: SubtitleFormat) -> str:
    """Join cues on separate lines without leaking their local ASS overrides."""
    if not texts:
        return ""
    if not is_ass(format_):
        # Cues must each be independently valid before being combined.
        for text in texts:
            _srt_stack(text)
        return "\n".join(texts)
    for text in texts:
        _check_ass(text, retiming=True)
    signatures = [ass_global_tags(text) for text in texts]
    if any(signature != signatures[0] for signature in signatures[1:]):
        raise ValueError("Subtitles with different ASS positioning/alignment tags cannot be merged.")
    result = [texts[0]]
    for previous, current in zip(texts, texts[1:]):
        local_tags = any(tag.name not in _GLOBAL_TAGS for tag in extract_override_tags(previous))
        result.append((r"{\r}" if local_tags else "") + current)
    return "\n".join(result)


def rebalance_text(text: str, format_: SubtitleFormat, max_line_length: int = 42) -> str:
    """Reflow at word boundaries, selecting two lines of similar visible length.

    Short text becomes one line. A long unbroken word is left intact. Original
    markup tokens and character entities retain their spelling and order.
    """
    if max_line_length < 1:
        raise ValueError("The maximum line length must be positive.")
    if is_ass(format_):
        _check_ass(text, retiming=False)
    elif any(match.group(1).lower() == "br" for match in _HTML_TAG.finditer(text)):
        raise ValueError("Replace <br> tags with line breaks before rebalancing this subtitle.")
    pieces = _pieces(text, format_)
    normalized = []
    visible_before = 0
    previous_space = True
    gaps = []
    for piece in pieces:
        if not piece.visible:
            normalized.append(piece)
        elif piece.visible.isspace() and piece.visible != "\u00a0":
            if not previous_space:
                gaps.append((len(normalized), visible_before))
                normalized.append(_Piece(" ", " "))
                previous_space = True
                visible_before += 1
        else:
            normalized.append(piece)
            visible_before += len(piece.visible)
            previous_space = False
    # Remove trailing whitespace without moving any closing formatting tags.
    if previous_space and gaps:
        index, _ = gaps.pop()
        normalized.pop(index)
        visible_before -= 1
    total = visible_before
    if total > max_line_length and gaps:
        # Penalize overflowing either line first, then choose the most balanced
        # pair. Do not split a word merely to satisfy the preferred length.
        def score(gap):
            _index, left = gap
            right = total - left - 1
            overflow = max(0, left - max_line_length) + max(0, right - max_line_length)
            return overflow, abs(left - right)

        index, _ = min(gaps, key=score)
        normalized[index] = _Piece("\n", "\n")
    return "".join(piece.raw for piece in normalized)
