"""Literal subtitle search and undoable replacement, without changing markup.

Offsets refer to visible Unicode text. Each visible character keeps its source
span, so a match may cross an ASS override block or an SRT formatting tag while
replacement leaves every tag byte-for-byte intact.
"""

from dataclasses import dataclass
import html
import re
import unicodedata

from gsub.commands.command import CompositeCommand
from gsub.commands.subtitle_commands import EditTextCommand
from gsub.models import SubtitleFormat
from gsub.parsers.ass_tags import BLOCK_PATTERN, parse_override_block


_SRT_TAG = re.compile(
    r"</?(?:b|i|u|s|strike|font|span|ruby|rt)(?=[\s/>])"
    r"(?:[^>\"']|\"[^\"]*\"|'[^']*')*>", re.IGNORECASE,
)
_ENTITY = re.compile(r"&(?:#[0-9]+|#x[0-9a-fA-F]+|[a-zA-Z][a-zA-Z0-9]+);")
_SRT_BREAK = re.compile(r"<br\s*/?>", re.IGNORECASE)


@dataclass(frozen=True)
class SearchOptions:
    case_sensitive: bool = False
    whole_words: bool = False


@dataclass(frozen=True)
class SearchMatch:
    position: int
    start: int
    end: int
    source_text: str
    visible_text: str


def _visible_source(text, subtitle_format):
    """Return visible text and one raw (start, end) span per character."""
    characters = []
    spans = []
    ass = subtitle_format in (SubtitleFormat.ASS, SubtitleFormat.SSA)
    drawing = False
    offset = 0
    while offset < len(text):
        if ass:
            block = BLOCK_PATTERN.match(text, offset)
            if block:
                for tag in parse_override_block(block.group(1)):
                    if tag.name == "r":
                        drawing = False
                    elif tag.name == "p" and tag.args:
                        try:
                            drawing = int(tag.args[0]) != 0
                        except ValueError:
                            pass
                offset = block.end()
                continue
            if drawing:
                offset += 1
                continue
            if text[offset:offset + 2] in (r"\N", r"\n", r"\h"):
                characters.append("\xa0" if text[offset + 1] == "h" else "\n")
                spans.append((offset, offset + 2))
                offset += 2
                continue
        else:
            line_break = _SRT_BREAK.match(text, offset)
            if line_break:
                characters.append("\n")
                spans.append((offset, line_break.end()))
                offset = line_break.end()
                continue
            tag = _SRT_TAG.match(text, offset)
            if tag:
                offset = tag.end()
                continue
            entity = _ENTITY.match(text, offset)
            if entity:
                decoded = html.unescape(entity.group())
                characters.extend(decoded)
                spans.extend([(offset, entity.end())] * len(decoded))
                offset = entity.end()
                continue
        characters.append(text[offset])
        spans.append((offset, offset + 1))
        offset += 1
    return "".join(characters), spans


def visible_text(text, subtitle_format):
    """Return searchable text, excluding formatting and ASS drawing paths."""
    return _visible_source(text, subtitle_format)[0]


def _is_word(character):
    return character == "_" or character.isalnum() or unicodedata.category(character).startswith("M")


def _match_offsets(text, query, options):
    if not query:
        return
    if options.case_sensitive:
        haystack, needle = text, query
        source_indices = list(range(len(text)))
    else:
        folded = [character.casefold() for character in text]
        haystack, needle = "".join(folded), query.casefold()
        source_indices = [i for i, piece in enumerate(folded) for _ in piece]
    offset = 0
    while True:
        found = haystack.find(needle, offset)
        if found < 0:
            return
        stop = found + len(needle)
        offset = stop
        # Do not replace only half of a casefold expansion such as ß -> ss.
        if ((found and source_indices[found - 1] == source_indices[found]) or
                (stop < len(haystack) and source_indices[stop - 1] == source_indices[stop])):
            continue
        start, end = source_indices[found], source_indices[stop - 1] + 1
        if options.whole_words and (
            (start and _is_word(text[start - 1])) or
            (end < len(text) and _is_word(text[end]))
        ):
            continue
        yield start, end


def find_matches(document, query, options=None, positions=None):
    """Find nonoverlapping literal matches in document order.

    ``positions=None`` searches every entry; an empty iterable searches none.
    Markup and drawing data are never matched. A partial match within an HTML
    entity expanding into several characters is excluded to protect its bytes.
    """
    options = options or SearchOptions()
    if not query:
        return []
    positions = range(len(document.entries)) if positions is None else sorted(set(positions))
    result = []
    for position in positions:
        if not 0 <= position < len(document.entries):
            continue
        source = document.entries[position].text
        text, spans = _visible_source(source, document.format)
        for start, end in _match_offsets(text, query, options):
            if ((start and spans[start - 1] == spans[start]) or
                    (end < len(spans) and spans[end - 1] == spans[end])):
                continue
            result.append(SearchMatch(position, start, end, source, text))
    return result


def _encode_replacement(replacement, subtitle_format):
    replacement = replacement.replace("\r\n", "\n").replace("\r", "\n")
    if subtitle_format in (SubtitleFormat.ASS, SubtitleFormat.SSA):
        if "{" in replacement or "}" in replacement:
            raise ValueError("ASS replacements cannot contain braces; use the formatting editor for tags.")
        # The model uses actual newlines; the ASS serializer encodes them as
        # \N on disk. Accept the familiar ASS text escapes in the single-line
        # replacement field as well as actual Unicode separators.
        return replacement.replace(r"\N", "\n").replace(r"\n", "\n").replace(r"\h", "\xa0")
    return html.escape(replacement, quote=False)


def replacement_visible_text(replacement, subtitle_format):
    """Text the replacement will display, for previews and match navigation."""
    return visible_text(_encode_replacement(replacement, subtitle_format), subtitle_format)


def build_replace_command(document, matches, replacement):
    """Build one undo step for one or many matches, or None for no changes.

    Reject stale previews rather than replacing text at outdated offsets. The
    caller executes the result through its normal CommandManager.
    """
    encoded = _encode_replacement(replacement, document.format)
    replacement_text = visible_text(encoded, document.format)
    grouped = {}
    count = 0
    for match in matches:
        if not 0 <= match.position < len(document.entries):
            raise ValueError("The subtitles changed. Refresh the search preview and try again.")
        source = document.entries[match.position].text
        if source != match.source_text:
            raise ValueError("The subtitles changed. Refresh the search preview and try again.")
        grouped.setdefault(match.position, []).append(match)
    commands = []
    for position, entry_matches in sorted(grouped.items()):
        source = document.entries[position].text
        text, spans = _visible_source(source, document.format)
        edits = []
        previous_end = -1
        for match in sorted(entry_matches, key=lambda m: m.start):
            if not 0 <= match.start < match.end <= len(text) or match.start < previous_end:
                raise ValueError("Search matches must be valid and nonoverlapping.")
            previous_end = match.end
            if text[match.start:match.end] == replacement_text:
                continue
            raw_spans = list(dict.fromkeys(spans[match.start:match.end]))
            for i, (start, end) in enumerate(raw_spans):
                edits.append((start, end, encoded if i == 0 else ""))
            count += 1
        updated = source
        for start, end, value in sorted(edits, reverse=True):
            updated = updated[:start] + value + updated[end:]
        if updated != source:
            commands.append(EditTextCommand(document, position, updated))
    if not commands:
        return None
    return CompositeCommand(commands, f"Replace {count} match{'es' if count != 1 else ''}")
