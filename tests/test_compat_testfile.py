"""Integration tests against examples/compatibility_test.ass.

The test file is a deliberately broken — but syntactically valid — ASS
document in which every style and labeled ``CASE nn`` entry triggers one
specific compatibility check. These tests prove that the Compatibility
feature detects every case it is supposed to handle, that the automatic
fixes resolve all fixable issues, and that undoing them restores the
original document.
"""

import copy
from collections import Counter
from pathlib import Path

import pytest

from gsub.commands.ass_commands import ReplaceASSHeaderCommand
from gsub.commands.command import CommandManager, CompositeCommand
from gsub.commands.subtitle_commands import EditTextCommand
from gsub.models import SubtitleFormat
from gsub.parsers.ass_parser import ASSParser
from gsub.parsers.ass_validator import (
    clamp_blur,
    fix_color,
    strip_fsp,
    validate_document,
)

TESTFILE = Path(__file__).resolve().parent.parent / "examples" / "compatibility_test.ass"

# Fonts considered installed for these tests. Only styles using another
# font (the "Nonexistent Font" style) may be reported missing, which keeps
# the font check deterministic on any host.
INSTALLED_FONTS = ["Arial", "Monospace"]

EXPECTED_COUNTS = {
    "color.unknown_format": 3,   # BadColors: web / decimal / short-hex colors
    "color.invisible_text": 1,   # Invisible: PrimaryColour alpha &HFF
    "font.missing": 1,           # MissingFont style
    "style.small_scale": 2,      # TinyScale: ScaleX 5 and ScaleY 8
    "text.arabic_spacing": 4,    # \fsp(3), bare \fsp2, style spacing, stress entry
    "text.emoji": 2,             # emoji entry + stress entry
    "tags.unbalanced_braces": 2, # unclosed { and reversed }{
    "tags.pos_move_conflict": 1,
    "tags.duplicate_position": 3,  # \an x2, legacy \a x2, stress entry
    "tags.contradictory_bold": 1,
    "tags.excessive_blur": 3,    # \blur(20), bare \blur15, stress \blur(12)
    "tags.renderer_dependent": 2,  # frz/fscx/t combo + drawing \p
    "position.out_of_bounds": 3,  # beyond PlayRes, negative x, \move end point
}
FIXABLE_KINDS = {"color": 4, "spacing": 4, "blur": 3}


def load_testfile():
    warnings = []
    doc = ASSParser.parse(TESTFILE.read_text(encoding="utf-8"), warnings)
    return doc, warnings


def issues_of(doc):
    return validate_document(doc, installed_fonts=INSTALLED_FONTS)


def entry_by_index(doc, index):
    return next(e for e in doc.entries if e.index == index)


def style_by_name(doc, name):
    return doc.get_style_by_name(name)


@pytest.mark.integration
class TestTestFileParses:
    def test_parses_as_ass_with_all_cases(self):
        doc, _ = load_testfile()
        assert doc.format == SubtitleFormat.ASS
        assert len(doc.styles) == 7
        assert len(doc.entries) == 24

    def test_parser_warnings_are_only_the_brace_cases(self):
        # The file is broken at the compatibility level, not syntactically:
        # the only parse warnings are the two intentionally unbalanced-brace
        # entries (CASE 03 and CASE 04).
        _, warnings = load_testfile()
        assert len(warnings) == 2
        assert all("unbalanced" in w for w in warnings)
        assert any("entry 3" in w for w in warnings)
        assert any("entry 4" in w for w in warnings)


@pytest.mark.integration
class TestAllChecksTrigger:
    def test_every_issue_code_with_exact_counts(self):
        # Exact-count comparison catches both missed detections and false
        # positives anywhere in the file.
        counts = Counter(i.code for i in issues_of(load_testfile()[0]))
        assert counts == Counter(EXPECTED_COUNTS)

    def test_clean_baseline_triggers_nothing(self):
        # CASE 01 uses a valid style and a single \an tag: no issue may
        # reference it, proving the checks do not fire on clean input.
        assert [i for i in issues_of(load_testfile()[0])
                if i.location == "Dialogue entry 1"] == []

    def test_fixable_issue_kinds(self):
        kinds = Counter(i.fix["kind"] for i in issues_of(load_testfile()[0]) if i.fix)
        assert kinds == Counter(FIXABLE_KINDS)


@pytest.mark.integration
class TestAutoFixes:
    @staticmethod
    def apply_fix(document, manager, issue):
        """Apply one fix exactly the way GsubWindow._apply_compat_fix does."""
        fix = issue.fix
        cmds = []
        if fix["kind"] == "color":
            style = document.get_style_by_name(fix["style"])
            new_styles = [copy.deepcopy(s) for s in document.styles]
            for s in new_styles:
                if s.name == fix["style"]:
                    setattr(s, fix["field"], fix_color(fix, style))
            cmds.append(ReplaceASSHeaderCommand(
                document, metadata=document.metadata,
                aegisub_project_garbage=getattr(
                    document, "aegisub_project_garbage", {}),
                styles=new_styles))
        elif fix["kind"] == "spacing":
            new_styles = [copy.deepcopy(s) for s in document.styles]
            for s in new_styles:
                if s.name == fix["style"]:
                    s.spacing = 0.0
            cmds.append(ReplaceASSHeaderCommand(
                document, metadata=document.metadata,
                aegisub_project_garbage=getattr(
                    document, "aegisub_project_garbage", {}),
                styles=new_styles))
            for entry in document.entries:
                if entry.style == fix["style"] and "\\fsp" in entry.text:
                    new_text = strip_fsp(entry.text)
                    if new_text != entry.text:
                        cmds.append(EditTextCommand(
                            document, entry.index - 1, new_text))
        elif fix["kind"] == "blur":
            entry = next(e for e in document.entries
                         if e.index == fix["entry_index"])
            cmds.append(EditTextCommand(
                document, entry.index - 1, clamp_blur(entry.text)))
        command = cmds[0] if len(cmds) == 1 else CompositeCommand(
            cmds, "Fix compatibility issue")
        manager.execute(command)

    @classmethod
    def apply_all_fixes(cls):
        doc, _ = load_testfile()
        manager = CommandManager()
        for issue in [i for i in issues_of(doc) if i.fix]:
            cls.apply_fix(doc, manager, issue)
        return doc, manager

    def test_all_fixable_issues_resolve(self):
        doc, _ = self.apply_all_fixes()
        counts = Counter(i.code for i in issues_of(doc))
        for code in ("color.unknown_format", "color.invisible_text",
                     "text.arabic_spacing", "tags.excessive_blur"):
            assert counts.pop(code, 0) == 0, f"{code} still reported after fixes"
        # Everything that has no automatic fix must be untouched.
        assert counts == Counter(
            {k: v for k, v in EXPECTED_COUNTS.items()
             if k not in ("color.unknown_format", "color.invisible_text",
                          "text.arabic_spacing", "tags.excessive_blur")})

    def test_fix_outcomes(self):
        doc, _ = self.apply_all_fixes()
        # Invalid colors are replaced with safe defaults per field.
        bad = style_by_name(doc, "BadColors")
        assert bad.primary_color == "&H00FFFFFF"
        assert bad.secondary_color == "&H00000000"
        assert bad.outline_color == "&H00000000"
        # Invisible color keeps its RGB, only the alpha becomes opaque.
        assert style_by_name(doc, "Invisible").primary_color == "&H000000FF"
        # Style spacing is zeroed...
        assert style_by_name(doc, "ArabicSpaced").spacing == 0.0
        # ...and \fsp overrides disappear from every entry of the style.
        for index in (16, 17):
            assert "\\fsp" not in entry_by_index(doc, index).text
        # Both blur spellings are clamped to 10 in canonical form.
        assert "\\blur(10)" in entry_by_index(doc, 9).text
        assert "\\blur(20)" not in entry_by_index(doc, 9).text
        assert "\\blur(10)" in entry_by_index(doc, 10).text
        # The stress entry is fixed where fixable; its other problems stay.
        stress = entry_by_index(doc, 19).text
        assert "\\blur(10)" in stress and "\\an5\\an8" in stress

    def test_undo_restores_original_state(self):
        doc, manager = self.apply_all_fixes()
        while manager.undo():
            pass
        assert Counter(i.code for i in issues_of(doc)) == Counter(EXPECTED_COUNTS)
        assert style_by_name(doc, "BadColors").primary_color == "#FF0000"
        assert style_by_name(doc, "Invisible").primary_color == "&HFF0000FF"
        assert style_by_name(doc, "ArabicSpaced").spacing == 2.0
        assert "\\fsp3" in entry_by_index(doc, 16).text
        assert "\\blur(20)" in entry_by_index(doc, 9).text
