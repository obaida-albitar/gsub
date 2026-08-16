"""Pango glyph-coverage checks for ASS style fonts.

Kept out of the main window module so it can be imported and unit-tested
headlessly (Pango font maps work without a display).
"""

import gi

gi.require_version('Pango', '1.0')
gi.require_version('PangoCairo', '1.0')

from gi.repository import Pango, PangoCairo  # noqa: E402

from subtitle_editor.logger import get_logger  # noqa: E402
from subtitle_editor.models import SubtitleDocument  # noqa: E402
from subtitle_editor.parsers.ass_validator import (  # noqa: E402
    CompatIssue,
    CompatSeverity,
)

logger = get_logger(__name__)

# The coverage-level enum is ``Pango.CoverageLevel`` in newer PyGObject and
# was exposed as ``Pango.Coverage`` in older bindings; NONE == 0 either way.
try:
    COVERAGE_NONE = Pango.CoverageLevel.NONE
except AttributeError:  # pragma: no cover - older PyGObject
    COVERAGE_NONE = Pango.Coverage.NONE

# Lazily-created shared font map / context (they rarely change).
_FONTMAP = None
_CONTEXT = None


def _fontmap_and_context():
    global _FONTMAP, _CONTEXT
    if _FONTMAP is None:
        _FONTMAP = PangoCairo.FontMap.get_default()
        _CONTEXT = _FONTMAP.create_context()
    return _FONTMAP, _CONTEXT


def collect_glyph_coverage_issues(
    document: SubtitleDocument,
    installed_fonts,
    sample_limit: int = 300,
) -> list:
    """Report characters an installed style font cannot render (INFO issues).

    Purely informational: a Pango failure for one style is logged and skipped
    so this check can never break document loading or the refresh cycle.
    """
    installed = set(installed_fonts)
    fontmap, ctx = _fontmap_and_context()
    lang = Pango.Language.get_default()

    issues = []
    for style in document.styles:
        if style.fontname not in installed:
            continue
        sample = "".join(
            e.text for e in document.entries if e.style == style.name
        )[:sample_limit]
        if not sample:
            continue
        try:
            font = fontmap.load_font(
                ctx, Pango.FontDescription.from_string(style.fontname))
            if font is None:
                continue
            coverage = font.get_coverage(lang)
            missing = sorted({
                ch for ch in sample if coverage.get(ord(ch)) == COVERAGE_NONE
            })
        except Exception:
            logger.exception("Glyph coverage check failed for font '%s'",
                             style.fontname)
            continue
        if missing:
            issues.append(CompatIssue(
                severity=CompatSeverity.INFO,
                code="font.glyph_missing",
                message=(
                    f"Style '{style.name}': font '{style.fontname}' "
                    f"lacks glyphs for: {''.join(missing)!r}"),
                location=f"Style '{style.name}'"))
    return issues
