"""GTK-free tests for the headless ASS compatibility validator and helpers."""

import pytest
from subtitle_editor.parsers.ass_validator import (
    validate_document,
    CompatIssue,
    fix_color,
    clamp_blur,
    strip_fsp,
)
from subtitle_editor.parsers.ass_tags import extract_override_tags, get_positioning, has_unbalanced_braces
from subtitle_editor.utils import parse_ass_color, is_valid_ass_color, format_ass_color
from subtitle_editor.models import SubtitleDocument, ASSStyle, SubtitleEntry, SubtitleFormat, TimeCode
from subtitle_editor.parsers.ass_parser import ASSParser


def make_doc(entries_text=None, styles=None, meta=None):
    doc = SubtitleDocument(format=SubtitleFormat.ASS)
    doc.metadata.update(meta or {})
    for s in (styles or [ASSStyle()]):
        doc.styles.append(s)
    if entries_text:
        for i, t in enumerate(entries_text, 1):
            doc.entries.append(SubtitleEntry(index=i, start_time=TimeCode(0, 0, 1, 0),
                                             end_time=TimeCode(0, 0, 2, 0), style='Default', text=t))
    return doc


@pytest.mark.unit
@pytest.mark.parser
class TestAssColors:
    def test_parse_8digit_alpha_zero(self):
        assert parse_ass_color("&H00FFFFFF") == (255, 255, 255, 0)

    def test_parse_6digit_alpha_zero(self):
        assert parse_ass_color("&HFFFFFF") == (255, 255, 255, 0)

    def test_parse_hash_is_none(self):
        assert parse_ass_color("#FF00FF") is None

    def test_is_valid_true_false(self):
        assert is_valid_ass_color("&H00FFFFFF") is True
        assert is_valid_ass_color("#FF00FF") is False

    def test_format_parse_roundtrip(self):
        s = format_ass_color(255, 255, 255, 0)
        assert s == "&H00FFFFFF"
        assert parse_ass_color(s) == (255, 255, 255, 0)


@pytest.mark.unit
@pytest.mark.parser
class TestAssTags:
    def test_extract_pos_and_bold(self):
        tags = {t.name: t for t in extract_override_tags("{\\pos(1,2)\\b1}")}
        assert tags["pos"].args == ["1", "2"]
        assert tags["b"].args == ["1"]

    def test_get_positioning(self):
        pos = get_positioning("{\\pos(10,20)}hello")
        assert pos == {"kind": "pos", "x": 10.0, "y": 20.0}

    def test_unbalanced_braces(self):
        assert has_unbalanced_braces("{ \\pos(1,2) ") is True
        assert has_unbalanced_braces("{\\pos(1,2)}") is False

    def test_renderer_dependent_tag_extracted(self):
        tags = extract_override_tags("{\\iclip(0,0,100,100)}")
        assert any(t.name == "iclip" for t in tags)


@pytest.mark.unit
@pytest.mark.parser
class TestValidatorColors:
    def test_unknown_format(self):
        doc = make_doc(styles=[ASSStyle(name="Default", primary_color="#BAD")])
        assert any(iss.code == "color.unknown_format" for iss in validate_document(doc))

    def test_invisible_text(self):
        doc = make_doc(styles=[ASSStyle(name="Default", primary_color="&HFF000000")])
        assert any(iss.code == "color.invisible_text" for iss in validate_document(doc))


@pytest.mark.unit
@pytest.mark.parser
class TestValidatorFonts:
    def test_font_missing(self):
        doc = make_doc(styles=[ASSStyle(name="Default", fontname="Comic Sans")])
        issues = validate_document(doc, installed_fonts=["Arial"])
        assert any(iss.code == "font.missing" for iss in issues)

    def test_font_ok_when_none(self):
        doc = make_doc(styles=[ASSStyle(name="Default", fontname="Comic Sans")])
        assert not any(iss.code == "font.missing" for iss in validate_document(doc))


@pytest.mark.unit
@pytest.mark.parser
class TestValidatorScales:
    def test_small_scale(self):
        doc = make_doc(styles=[ASSStyle(name="Default", scale_x=5)])
        assert any(iss.code == "style.small_scale" for iss in validate_document(doc))


@pytest.mark.unit
@pytest.mark.parser
class TestValidatorArabic:
    def test_arabic_spacing_style(self):
        doc = make_doc(entries_text=["مرحبا"],
                       styles=[ASSStyle(name="Default", spacing=2)])
        assert any(iss.code == "text.arabic_spacing" for iss in validate_document(doc))

    def test_arabic_spacing_override(self):
        doc = make_doc(entries_text=["{\\fsp2}مرحبا"],
                       styles=[ASSStyle(name="Default", spacing=0)])
        assert any(iss.code == "text.arabic_spacing" for iss in validate_document(doc))


@pytest.mark.unit
@pytest.mark.parser
class TestValidatorEmoji:
    def test_emoji(self):
        doc = make_doc(entries_text=["hello 😀 world"])
        assert any(iss.code == "text.emoji" for iss in validate_document(doc))


@pytest.mark.unit
@pytest.mark.parser
class TestValidatorTags:
    def test_pos_move_conflict(self):
        doc = make_doc(entries_text=["{\\pos(1,2)\\move(3,4,5,6)}"])
        assert any(iss.code == "tags.pos_move_conflict" for iss in validate_document(doc))

    def test_unbalanced_braces(self):
        doc = make_doc(entries_text=["{ \\pos(1,2) "])
        assert any(iss.code == "tags.unbalanced_braces" for iss in validate_document(doc))

    def test_excessive_blur(self):
        doc = make_doc(entries_text=["{\\blur20}"])
        assert any(iss.code == "tags.excessive_blur" for iss in validate_document(doc))

    def test_renderer_dependent(self):
        doc = make_doc(entries_text=["{\\iclip(0,0,100,100)}"])
        assert any(iss.code == "tags.renderer_dependent" for iss in validate_document(doc))

    def test_duplicate_position(self):
        doc = make_doc(entries_text=["{\\an5\\an7}"])
        assert any(iss.code == "tags.duplicate_position" for iss in validate_document(doc))

    def test_contradictory_bold(self):
        doc = make_doc(entries_text=["{\\b1\\b0}"])
        assert any(iss.code == "tags.contradictory_bold" for iss in validate_document(doc))


@pytest.mark.unit
@pytest.mark.parser
class TestValidatorPosition:
    def test_out_of_bounds(self):
        doc = make_doc(entries_text=["{\\pos(2000,2000)}"],
                       meta={"PlayResX": "1920", "PlayResY": "1080"})
        assert any(iss.code == "position.out_of_bounds" for iss in validate_document(doc))

    def test_in_bounds(self):
        doc = make_doc(entries_text=["{\\pos(100,100)}"],
                       meta={"PlayResX": "1920", "PlayResY": "1080"})
        assert not any(iss.code == "position.out_of_bounds" for iss in validate_document(doc))


@pytest.mark.unit
@pytest.mark.parser
class TestValidatorIntegration:
    def test_parse_and_validate(self):
        content = """[Script Info]
Title: Test
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,20,&H00FFFFFF,&H00000000,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,2,2,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:02.00,Default,,,0,0,0,,{\\pos(2000,5)}Hi
"""
        warnings = []
        doc = ASSParser.parse(content, warnings)
        issues = validate_document(doc)
        assert isinstance(issues, list)
        assert all(isinstance(i, CompatIssue) for i in issues)
        assert all(isinstance(i.code, str) for i in issues)
        assert any(i.code == "position.out_of_bounds" for i in issues)


@pytest.mark.unit
@pytest.mark.parser
class TestFixAttribution:
    """Only deterministically-fixable issues should carry a ``fix`` dict."""

    def _by_code(self, doc, installed_fonts=None):
        return {i.code: i for i in validate_document(doc, installed_fonts=installed_fonts)}

    def test_fixable_codes_have_fix(self):
        doc = make_doc(
            entries_text=["مرحبا {\\fsp2}", "{\\blur20}"],
            styles=[ASSStyle(name="Default", primary_color="#BAD", spacing=2)],
            meta={"PlayResX": "1920", "PlayResY": "1080"},
        )
        by = self._by_code(doc)
        assert by["color.unknown_format"].fix["kind"] == "color"
        assert by["color.unknown_format"].fix["field"] == "primary_color"
        assert by["text.arabic_spacing"].fix["kind"] == "spacing"
        assert by["tags.excessive_blur"].fix["kind"] == "blur"
        assert by["tags.excessive_blur"].fix["entry_index"] == 2

    def test_invisible_text_fix(self):
        doc = make_doc(styles=[ASSStyle(name="Default", primary_color="&HFF000000")])
        issue = self._by_code(doc)["color.invisible_text"]
        assert issue.fix == {"kind": "color", "field": "primary_color", "alpha": 0}

    def test_non_fixable_codes_have_no_fix(self):
        doc = make_doc(
            entries_text=["😀", "{\\pos(1,2)\\move(3,4,5,6)}", "{\\pos(2000,2000)}",
                          "{\\an5\\an7}", "{\\b1\\b0}", "{ \\pos(1,2) ",
                          "{\\iclip(0,0,100,100)}"],
            styles=[ASSStyle(name="Default", fontname="Comic Sans", scale_x=5)],
            meta={"PlayResX": "1920", "PlayResY": "1080"},
        )
        by = self._by_code(doc, installed_fonts=["Arial"])
        for code in (
            "font.missing", "text.emoji", "position.out_of_bounds",
            "tags.pos_move_conflict", "tags.duplicate_position",
            "tags.contradictory_bold", "tags.unbalanced_braces",
            "tags.renderer_dependent", "style.small_scale",
        ):
            assert by[code].fix is None, f"{code} should not be auto-fixable"


@pytest.mark.unit
@pytest.mark.parser
class TestFixHelpers:
    def test_fix_color_unknown_uses_default(self):
        style = ASSStyle(name="Default", primary_color="#BAD")
        assert fix_color({"kind": "color", "field": "primary_color"}, style) == "&H00FFFFFF"

    def test_fix_color_invisible_sets_alpha(self):
        style = ASSStyle(name="Default", primary_color="&HFFFFFFFF")
        assert fix_color({"kind": "color", "field": "primary_color", "alpha": 0}, style) == "&H00FFFFFF"

    def test_clamp_blur_clamps_large_only(self):
        assert clamp_blur("{\\blur(20)\\b1} rest {\\blur(5)}") == "{\\blur(10)\\b1} rest {\\blur(5)}"

    def test_strip_fsp_removes_overrides(self):
        assert strip_fsp("hi {\\fsp(3)} there {\\fsp(2.5)}") == "hi {} there {}"
