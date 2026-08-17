"""Parser for ASS/SSA override tags found inside Dialogue text.

Handles override blocks like ``{\\pos(12,34)\\b1\\an5}`` and extracts
individual tags, positioning directives, and brace-balance information.
Also provides the inverse operation (:func:`serialize_override_tags`) so a
parsed block can be rebuilt byte-for-byte, plus display helpers that strip
or split off override blocks.
This module is pure Python (no GTK/GLib) so it can be unit-tested headlessly.
"""

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

RENDERER_DEPENDENT_TAGS: frozenset = frozenset({
    'iclip', 'org', 'p', 'pbo', 't', 'frx', 'fry', 'frz',
    'fr', 'fax', 'fay', 'fscx', 'fscy',
})

BLOCK_PATTERN = re.compile(r'\{([^{}]*)\}')

# Standard ASS override tag names. A segment's name is matched against these
# first because the generic pattern below cannot split a name from alphabetic
# arguments: "\\fnGeorgia" would greedy-match the whole name "fngeorgia"
# instead of tag "fn" with argument "Georgia" (same for style resets like
# "\\rDefault"). Longest-first alternation so "\\fscx100" prefers "fscx"
# over "fs".
_KNOWN_TAG_NAMES = frozenset({
    '1a', '1c', '2a', '2c', '3a', '3c', '4a', '4c', 'a', 'alpha', 'an', 'b',
    'be', 'blur', 'bord', 'c', 'clip', 'fax', 'fay', 'fe', 'fn', 'fr', 'frx',
    'fry', 'frz', 'fs', 'fscx', 'fscy', 'fsp', 'i', 'iclip', 'k', 'kf', 'ko',
    'move', 'org', 'p', 'pbo', 'pos', 'q', 'r', 's', 'shad', 't', 'u',
    'wrapstyle', 'xbord', 'xshad', 'ybord', 'yshad', 'K',
})
_KNOWN_TAG_RE = re.compile(
    r'^(' + '|'.join(sorted(_KNOWN_TAG_NAMES, key=len, reverse=True)) + r')'
    r'(?:\((.*)\))?(.*)$'
)
# Generic fallback: an optional digit prefix 1-4 (colour/alpha tags like \3c)
# followed by letters only, so "\fs12" splits as name "fs" + args "12" rather
# than the single name "fs12".
_TAG_PATTERN = re.compile(r'^([1-4]?[a-zA-Z]+)(?:\((.*)\))?(.*)$')


@dataclass
class OverrideTag:
    name: str
    args: List[str]
    raw: str
    block_index: int


def parse_tag_segment(segment: str, block_index: int = 0) -> Optional[OverrideTag]:
    """Parse a single tag segment (the text after a ``\\``, e.g. ``fs12``).

    Known tag names are tried first so alphabetic arguments split correctly;
    the ``raw`` field preserves the original spelling byte-for-byte so parsed
    tags can be re-serialized without loss.
    """
    if not segment:
        return None
    match = _KNOWN_TAG_RE.match(segment) or _TAG_PATTERN.match(segment)
    if not match:
        return None
    name = match.group(1).lower()
    if not name:
        return None
    arg_str = match.group(2)
    if arg_str is not None:
        args = [a.strip() for a in arg_str.split(',')] if arg_str.strip() else []
        raw = '\\' + match.group(1) + '(' + arg_str + ')'
    else:
        trailing = match.group(3) or ''
        args = [trailing] if trailing else []
        raw = '\\' + match.group(1) + trailing
    return OverrideTag(name=name, args=args, raw=raw, block_index=block_index)


def _split_segments(body: str) -> List[str]:
    """Split a block body on backslashes that are NOT inside parentheses.

    ``\\t(\\fs20,\\fs30,1)`` is one tag whose arguments contain backslashes;
    a plain ``split('\\\\')`` would tear it apart. Joining the result with
    ``'\\\\'`` always reproduces ``body`` exactly.
    """
    segments: List[str] = []
    current: List[str] = []
    depth = 0
    for ch in body:
        if ch == '\\' and depth == 0:
            segments.append(''.join(current))
            current = []
            continue
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth = max(0, depth - 1)
        current.append(ch)
    segments.append(''.join(current))
    return segments


def _opaque_piece(raw: str, block_index: int) -> OverrideTag:
    """A block segment that is not a tag (comment text, doubled backslash...).

    Such pieces carry an empty name (so tag consumers skip them) and keep
    their original bytes for round-trip serialization.
    """
    return OverrideTag(name='', args=[], raw=raw, block_index=block_index)


def _parse_block(body: str, block_index: int) -> List[OverrideTag]:
    """Parse a single override block body (without braces) into tags.

    Every backslash-separated segment yields a piece: real tags carry their
    lower-cased ``name``; anything else (text before the first backslash,
    doubled backslashes, unparseable segments) becomes an opaque piece with
    an empty name. Keeping all pieces makes
    ``serialize_override_tags(parse_override_block(body)) == body`` hold
    byte-for-byte for arbitrary content.
    """
    pieces: List[OverrideTag] = []
    segments = _split_segments(body)
    if segments[0]:
        # Content before the first backslash, e.g. a comment in "{note \fs12}".
        pieces.append(_opaque_piece(segments[0], block_index))
    for segment in segments[1:]:
        if not segment:
            # Doubled backslash; keep it so serialization round-trips.
            pieces.append(_opaque_piece('\\', block_index))
            continue
        tag = parse_tag_segment(segment, block_index)
        if tag is not None:
            pieces.append(tag)
        else:
            pieces.append(_opaque_piece('\\' + segment, block_index))
    return pieces


def parse_override_block(body: str) -> List[OverrideTag]:
    """Parse a block body keeping every piece (round-trip safe).

    Unlike :func:`extract_override_tags` this also returns opaque pieces
    (empty ``name``) so the body can be rebuilt exactly; used by the visual
    tag editor.
    """
    return _parse_block(body, 0)


def serialize_override_tags(tags: List[OverrideTag]) -> str:
    """Rebuild override-block content (without braces) from parsed tags.

    Each piece re-emits its ``raw`` form verbatim, so a parse -> serialize
    round-trip reproduces the original block content byte-for-byte —
    including digit-prefixed colour tags, ``\\t(...)``/``\\clip(...)``
    bodies, drawing commands and plain comment blocks.
    """
    return ''.join(tag.raw for tag in tags)


def extract_override_tags(text: str) -> List[OverrideTag]:
    """Return all override tags found in ``{...}`` blocks within ``text``."""
    tags: List[OverrideTag] = []
    block_index = 0
    for match in BLOCK_PATTERN.finditer(text):
        tags.extend(p for p in _parse_block(match.group(1), block_index) if p.name)
        block_index += 1

    if not tags and '{' in text:
        remainder = text[text.index('{') + 1:]
        if '}' in remainder:
            remainder = remainder[:remainder.index('}')]
        tags.extend(p for p in _parse_block(remainder, 0) if p.name)
    return tags


def strip_override_blocks(text: str) -> str:
    """Remove ``{...}`` override blocks from ``text`` for display.

    Only complete blocks are removed; stray/unbalanced braces are ordinary
    text and are left alone.
    """
    return BLOCK_PATTERN.sub('', text)


def split_leading_block(text: str) -> Tuple[Optional[str], str]:
    """Split ``text`` into a leading ``{...}`` block and the rest.

    Only a block starting at position 0 counts; ``(None, text)`` is returned
    otherwise (including when the braces are unbalanced).
    """
    match = BLOCK_PATTERN.match(text)
    if not match:
        return None, text
    return match.group(0), text[match.end():]


def has_unbalanced_braces(text: str) -> bool:
    """Return True if braces are unbalanced or a ``}`` precedes its ``{``."""
    depth = 0
    for ch in text:
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth < 0:
                return True
    return depth != 0


def get_positioning(text: str) -> Optional[dict]:
    """Return the first parseable positioning directive as a dict, or None.

    Malformed tags are skipped so a later valid directive is still found.
    """
    for tag in extract_override_tags(text):
        try:
            if tag.name == 'pos' and len(tag.args) >= 2:
                return {'kind': 'pos',
                        'x': float(tag.args[0]),
                        'y': float(tag.args[1])}
            if tag.name == 'move' and len(tag.args) >= 4:
                t1 = float(tag.args[4]) if len(tag.args) >= 5 else 0.0
                t2 = float(tag.args[5]) if len(tag.args) >= 6 else 0.0
                return {'kind': 'move',
                        'x1': float(tag.args[0]),
                        'y1': float(tag.args[1]),
                        'x2': float(tag.args[2]),
                        'y2': float(tag.args[3]),
                        't1': t1,
                        't2': t2}
            if tag.name == 'an' and tag.args:
                return {'kind': 'an', 'n': int(tag.args[0])}
            if tag.name == 'a' and tag.args:
                return {'kind': 'a', 'n': int(tag.args[0])}
        except (ValueError, IndexError):
            continue
    return None


def has_tag(text: str, name: str) -> bool:
    """Return True if any override tag matches ``name`` (case-insensitive)."""
    target = name.lower()
    return any(tag.name == target for tag in extract_override_tags(text))


def get_tag_arg(text: str, name: str) -> Optional[str]:
    """Return the first arg of the first matching tag, or None."""
    target = name.lower()
    for tag in extract_override_tags(text):
        if tag.name == target and tag.args:
            return tag.args[0]
    return None
