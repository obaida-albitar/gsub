"""Parser for ASS/SSA override tags found inside Dialogue text.

Handles override blocks like ``{\\pos(12,34)\\b1\\an5}`` and extracts
individual tags, positioning directives, and brace-balance information.
This module is pure Python (no GTK/GLib) so it can be unit-tested headlessly.
"""

import re
from dataclasses import dataclass
from typing import List, Optional

RENDERER_DEPENDENT_TAGS: frozenset = frozenset({
    'iclip', 'org', 'p', 'pbo', 't', 'frx', 'fry', 'frz',
    'fr', 'fax', 'fay', 'fscx', 'fscy',
})

_BLOCK_PATTERN = re.compile(r'\{([^{}]*)\}')
_TAG_PATTERN = re.compile(r'^([a-zA-Z]+)(?:\((.*)\))?(.*)$')


@dataclass
class OverrideTag:
    name: str
    args: List[str]
    raw: str
    block_index: int


def _parse_block(body: str, block_index: int) -> List[OverrideTag]:
    """Parse a single override block body (without braces) into tags."""
    tags: List[OverrideTag] = []
    segments = body.split('\\')
    for segment in segments[1:]:
        if not segment:
            continue
        match = _TAG_PATTERN.match(segment)
        if not match:
            continue
        name = match.group(1).lower()
        if not name:
            continue
        arg_str = match.group(2)
        trailing = match.group(3) or ''
        if arg_str is not None:
            args = [a.strip() for a in arg_str.split(',')] if arg_str.strip() else []
            raw = '\\' + name + '(' + arg_str + ')'
        else:
            args = [trailing] if trailing else []
            raw = '\\' + name + trailing
        tags.append(OverrideTag(name=name, args=args, raw=raw, block_index=block_index))
    return tags


def extract_override_tags(text: str) -> List[OverrideTag]:
    """Return all override tags found in ``{...}`` blocks within ``text``."""
    tags: List[OverrideTag] = []
    block_index = 0
    for match in _BLOCK_PATTERN.finditer(text):
        tags.extend(_parse_block(match.group(1), block_index))
        block_index += 1

    if not tags and '{' in text:
        remainder = text[text.index('{') + 1:]
        if '}' in remainder:
            remainder = remainder[:remainder.index('}')]
        tags.extend(_parse_block(remainder, 0))
    return tags


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
