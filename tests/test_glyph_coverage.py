"""Regression tests for the Pango glyph-coverage check.

The check used ``Pango.Coverage.NONE``, which only exists in older PyGObject
bindings (newer ones renamed the enum to ``Pango.CoverageLevel``), so opening
a file whose styles use an installed font crashed with:
``type object 'Coverage' has no attribute 'NONE'``.
"""

import pytest

from gsub.font_coverage import (
    COVERAGE_NONE,
    collect_glyph_coverage_issues,
)
from gsub.models import (
    ASSStyle,
    SubtitleDocument,
    SubtitleEntry,
    SubtitleFormat,
    TimeCode,
)


def _doc(styles, texts, style_name="Default"):
    doc = SubtitleDocument(format=SubtitleFormat.ASS)
    doc.styles = styles
    doc.entries = [
        SubtitleEntry(i + 1, TimeCode(0, 0, i, 0), TimeCode(0, 0, i + 2, 0), t,
                      style=style_name)
        for i, t in enumerate(texts)
    ]
    return doc


@pytest.mark.unit
def test_coverage_none_constant_resolves():
    # Must be the NONE coverage level (0) on old and new PyGObject alike.
    assert int(COVERAGE_NONE) == 0


@pytest.mark.unit
def test_installed_font_check_runs_without_raising():
    # Regression for the user-facing crash: an installed font with a non-Latin
    # sample (e.g. the Arabic Wistoria subs styled with "Adwaita Sans") must
    # not raise, whether or not glyphs are missing.
    doc = _doc(
        [ASSStyle(name="Default", fontname="Adwaita Sans", fontsize=26)],
        ["مرحبا بالعالم"],
    )
    issues = collect_glyph_coverage_issues(doc, installed_fonts=["Adwaita Sans"])
    assert isinstance(issues, list)
    for issue in issues:
        assert issue.code == "font.glyph_missing"


@pytest.mark.unit
def test_uninstalled_font_is_skipped():
    doc = _doc([ASSStyle(name="Default", fontname="No-Such-Font-XYZ")],
               ["hello"])
    assert collect_glyph_coverage_issues(
        doc, installed_fonts=["SomeOtherFont"]) == []


@pytest.mark.unit
def test_style_without_entries_is_skipped():
    doc = _doc([ASSStyle(name="Default", fontname="Adwaita Sans")], [])
    assert collect_glyph_coverage_issues(
        doc, installed_fonts=["Adwaita Sans"]) == []
