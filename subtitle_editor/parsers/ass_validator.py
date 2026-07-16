"""Headless compatibility validator for ASS/SSA subtitle documents.

Pure Python (no GTK/GLib) so it can be unit-tested without a display.
Checks colours, fonts, scales, Arabic spacing, emoji, override tags and
position bounds, returning a list of :class:`CompatIssue`.
"""

import re
from enum import Enum
from dataclasses import dataclass
from typing import Optional, List, Iterable

from subtitle_editor.parsers.ass_tags import (
    extract_override_tags,
    has_unbalanced_braces,
    get_positioning,
    RENDERER_DEPENDENT_TAGS,
)
from subtitle_editor.utils import parse_ass_color, is_valid_ass_color, format_ass_color
from subtitle_editor.models import SubtitleDocument, ASSStyle


SCALE_MIN_WARN = 10.0
BLUR_MAX_WARN = 10.0

# Map an ASS color field name (as it appears in a Style line) to the
# ASSStyle attribute used by the editor.
COLOR_FIELD_ATTR = {
    "PrimaryColour": "primary_color",
    "SecondaryColour": "secondary_color",
    "OutlineColour": "outline_color",
    "BackColour": "back_color",
}

# Safe replacement colors used by the automatic fix for unknown/invalid colors.
DEFAULT_COLORS = {
    "primary_color": "&H00FFFFFF",
    "secondary_color": "&H00000000",
    "outline_color": "&H00000000",
    "back_color": "&H00000000",
}

_ARABIC_RANGES = (
    (0x0590, 0x05FF),  # Hebrew
    (0x0600, 0x06FF),  # Arabic
    (0x0750, 0x077F),  # Arabic Supplement
    (0x08A0, 0x08FF),  # Arabic Extended-A
    (0x0700, 0x074F),  # Syriac
    (0x0780, 0x07BF),  # Thaana
    (0x07C0, 0x07FF),  # N'Ko
)
_EMOJI_RANGES = (
    (0x1F300, 0x1FAFF),  # symbols & pictographs
    (0x2600, 0x26FF),    # misc symbols
    (0x2700, 0x27BF),    # dingbats
    (0x1F000, 0x1F0FF),  # mahjong / playing cards
    (0x1F1E6, 0x1F1FF),  # regional indicators
    (0xFE0F, 0xFE0F),    # variation selector-16
)

ARABIC_RE = re.compile(
    "[" + "".join(f"{chr(a)}-{chr(b)}" for a, b in _ARABIC_RANGES) + "]"
)
EMOJI_RE = re.compile(
    "[" + "".join(f"{chr(a)}-{chr(b)}" for a, b in _EMOJI_RANGES) + "]"
)

_BLUR_RE = re.compile(r"\\blur\(\s*([0-9]+(?:\.[0-9]+)?)\s*\)")
_FSP_RE = re.compile(r"\\fsp\(\s*[^)]*\)")


def fix_color(fix: dict, style: ASSStyle) -> str:
    """Compute the replacement color string for a ``color.*`` fix.

    For ``unknown_format`` this returns a safe default for the field; for
    ``invisible_text`` (alpha given) it keeps the RGB but sets alpha to the
    requested value (0 = opaque).
    """
    field = fix["field"]
    if fix.get("alpha") is not None:
        parsed = parse_ass_color(getattr(style, field))
        if parsed is None:
            return DEFAULT_COLORS.get(field, "&H00FFFFFF")
        r, g, b, _ = parsed
        return format_ass_color(r, g, b, fix["alpha"])
    return DEFAULT_COLORS.get(field, "&H00FFFFFF")


def clamp_blur(text: str, max_blur: float = BLUR_MAX_WARN) -> str:
    """Clamp every ``\\blur(N)`` value in ``text`` down to ``max_blur``."""
    def _repl(m: "re.Match") -> str:
        try:
            val = float(m.group(1))
        except ValueError:
            return m.group(0)
        if val > max_blur:
            return f"\\blur({max_blur:g})"
        return m.group(0)

    return _BLUR_RE.sub(_repl, text)


def strip_fsp(text: str) -> str:
    """Remove ``\\fsp(...)`` overrides from ``text``."""
    return _FSP_RE.sub("", text)


class CompatSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class CompatIssue:
    severity: CompatSeverity
    code: str
    message: str
    location: str
    suggestion: Optional[str] = None
    # When set, the issue has a deterministic automatic fix; `fix` is a small
    # dict describing it (see the helpers below) and the UI shows a Fix button.
    fix: Optional[dict] = None


def validate_document(
    doc: SubtitleDocument,
    installed_fonts: Optional[Iterable[str]] = None,
) -> List[CompatIssue]:
    """Run all compatibility checks on an ASS/SSA document and return issues."""
    issues: List[CompatIssue] = []
    for style in doc.styles:
        issues.extend(_check_colors(style))
        issues.extend(_check_scales(style))
    if installed_fonts is not None:
        issues.extend(_check_fonts(doc, installed_fonts))
    issues.extend(_check_spacing_arabic(doc))
    issues.extend(_check_emoji(doc))
    issues.extend(_check_override_tags(doc))
    issues.extend(_check_position_bounds(doc))
    return issues


def _check_colors(style: ASSStyle) -> List[CompatIssue]:
    issues: List[CompatIssue] = []
    fields = (
        (style.primary_color, "PrimaryColour"),
        (style.secondary_color, "SecondaryColour"),
        (style.outline_color, "OutlineColour"),
        (style.back_color, "BackColour"),
    )
    for value, field_name in fields:
        if not is_valid_ass_color(value):
            issues.append(CompatIssue(
                severity=CompatSeverity.WARNING,
                code="color.unknown_format",
                message=(
                    f"Style '{style.name}': {field_name} '{value}' is not a "
                    f"valid ASS color (&H[A]BBGGRR)"
                ),
                location=f"Style '{style.name}'",
                suggestion="Replace with a valid &H[A]BBGGRR color",
                fix={"kind": "color", "field": COLOR_FIELD_ATTR[field_name]},
            ))
        elif (
            field_name == "PrimaryColour"
            and parse_ass_color(value)[3] == 255
        ):
            issues.append(CompatIssue(
                severity=CompatSeverity.WARNING,
                code="color.invisible_text",
                message=(
                    f"Style '{style.name}': PrimaryColour is fully transparent "
                    f"(invisible text)"
                ),
                location=f"Style '{style.name}'",
                suggestion="Set alpha to &H00 for opaque text",
                fix={"kind": "color", "field": "primary_color", "alpha": 0},
            ))
    return issues


def _check_fonts(
    doc: SubtitleDocument,
    installed_fonts: Iterable[str],
) -> List[CompatIssue]:
    installed = set(installed_fonts)
    issues: List[CompatIssue] = []
    for style in doc.styles:
        if style.fontname not in installed:
            issues.append(CompatIssue(
                severity=CompatSeverity.INFO,
                code="font.missing",
                message=(
                    f"Style '{style.name}': font '{style.fontname}' is not "
                    f"installed on this system"
                ),
                location=f"Style '{style.name}'",
            ))
    return issues


def _check_scales(style: ASSStyle) -> List[CompatIssue]:
    issues: List[CompatIssue] = []
    for which, value in (("ScaleX", style.scale_x), ("ScaleY", style.scale_y)):
        if 0 < value < SCALE_MIN_WARN:
            issues.append(CompatIssue(
                severity=CompatSeverity.WARNING,
                code="style.small_scale",
                message=(
                    f"Style '{style.name}': {which} is extremely small "
                    f"({value}%) and may be invisible"
                ),
                location=f"Style '{style.name}'",
            ))
    return issues


def _check_spacing_arabic(doc: SubtitleDocument) -> List[CompatIssue]:
    issues: List[CompatIssue] = []
    for entry in doc.entries:
        if not ARABIC_RE.search(entry.text):
            continue
        style = doc.get_style_by_name(entry.style)
        if style is not None and style.spacing != 0:
            issues.append(CompatIssue(
                severity=CompatSeverity.WARNING,
                code="text.arabic_spacing",
                message=(
                    f"Dialogue entry {entry.index}: Arabic/cursive text uses "
                    f"non-zero letter spacing ({style.spacing}), which breaks "
                    f"joining"
                ),
                location=f"Dialogue entry {entry.index}",
                suggestion="Set Spacing to 0 for this style",
                fix={"kind": "spacing", "style": entry.style},
            ))
        for tag in extract_override_tags(entry.text):
            if tag.name == "fsp" and tag.args and tag.args[0] != "0":
                issues.append(CompatIssue(
                    severity=CompatSeverity.WARNING,
                    code="text.arabic_spacing",
                    message=(
                        f"Dialogue entry {entry.index}: Arabic/cursive text "
                        f"uses non-zero letter spacing (\\fsp {tag.args[0]}), "
                        f"which breaks joining"
                    ),
                    location=f"Dialogue entry {entry.index}",
                    suggestion="Set Spacing to 0 for this style",
                    fix={"kind": "spacing", "style": entry.style},
                ))
                break
    return issues


def _check_emoji(doc: SubtitleDocument) -> List[CompatIssue]:
    issues: List[CompatIssue] = []
    for entry in doc.entries:
        if EMOJI_RE.search(entry.text):
            issues.append(CompatIssue(
                severity=CompatSeverity.INFO,
                code="text.emoji",
                message=(
                    f"Dialogue entry {entry.index}: contains emoji, which may "
                    f"render inconsistently without an emoji-capable font"
                ),
                location=f"Dialogue entry {entry.index}",
            ))
    return issues


def _check_override_tags(doc: SubtitleDocument) -> List[CompatIssue]:
    issues: List[CompatIssue] = []
    for entry in doc.entries:
        text = entry.text
        tags = extract_override_tags(text)

        if has_unbalanced_braces(text):
            issues.append(CompatIssue(
                severity=CompatSeverity.ERROR,
                code="tags.unbalanced_braces",
                message=(
                    f"Dialogue entry {entry.index}: unbalanced {{ }} in "
                    f"override tags"
                ),
                location=f"Dialogue entry {entry.index}",
            ))

        names = [t.name for t in tags]
        has_pos = "pos" in names
        has_move = "move" in names
        if has_pos and has_move:
            issues.append(CompatIssue(
                severity=CompatSeverity.WARNING,
                code="tags.pos_move_conflict",
                message=(
                    f"Dialogue entry {entry.index}: mixes \\pos and \\move "
                    f"(use one)"
                ),
                location=f"Dialogue entry {entry.index}",
            ))

        if names.count("an") > 1 or names.count("a") > 1:
            issues.append(CompatIssue(
                severity=CompatSeverity.WARNING,
                code="tags.duplicate_position",
                message=(
                    f"Dialogue entry {entry.index}: duplicate alignment tag"
                ),
                location=f"Dialogue entry {entry.index}",
            ))

        b_args = [t.args[0] for t in tags if t.name == "b" and t.args]
        if "1" in b_args and "0" in b_args:
            issues.append(CompatIssue(
                severity=CompatSeverity.WARNING,
                code="tags.contradictory_bold",
                message=(
                    f"Dialogue entry {entry.index}: contradictory \\b1 and \\b0"
                ),
                location=f"Dialogue entry {entry.index}",
            ))

        for tag in tags:
            if tag.name == "blur" and tag.args:
                try:
                    arg = float(tag.args[0])
                except ValueError:
                    continue
                if arg > BLUR_MAX_WARN:
                    issues.append(CompatIssue(
                        severity=CompatSeverity.WARNING,
                        code="tags.excessive_blur",
                        message=(
                            f"Dialogue entry {entry.index}: \\blur value {arg} "
                            f"is extremely large"
                        ),
                        location=f"Dialogue entry {entry.index}",
                        fix={"kind": "blur", "entry_index": entry.index},
                    ))

        renderer_names = sorted(
            {t.name for t in tags if t.name in RENDERER_DEPENDENT_TAGS}
        )
        if renderer_names:
            issues.append(CompatIssue(
                severity=CompatSeverity.INFO,
                code="tags.renderer_dependent",
                message=(
                    f"Dialogue entry {entry.index}: uses renderer-dependent "
                    f"tag(s): {renderer_names} (may render differently across "
                    f"players)"
                ),
                location=f"Dialogue entry {entry.index}",
            ))
    return issues


def _check_position_bounds(doc: SubtitleDocument) -> List[CompatIssue]:
    issues: List[CompatIssue] = []
    try:
        w = int(doc.metadata.get("PlayResX", ""))
        h = int(doc.metadata.get("PlayResY", ""))
    except (ValueError, TypeError):
        return issues

    for entry in doc.entries:
        pos = get_positioning(entry.text)
        if pos is None:
            continue
        if pos["kind"] == "pos":
            x, y = pos["x"], pos["y"]
        elif pos["kind"] == "move":
            x, y = pos["x2"], pos["y2"]
        else:
            continue
        if x < 0 or y < 0 or x > w or y > h:
            issues.append(CompatIssue(
                severity=CompatSeverity.WARNING,
                code="position.out_of_bounds",
                message=(
                    f"Dialogue entry {entry.index}: \\pos ({x},{y}) is outside "
                    f"the script resolution ({w}x{h})"
                ),
                location=f"Dialogue entry {entry.index}",
            ))
    return issues
