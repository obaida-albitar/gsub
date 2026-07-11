"""Tests for defensive ASS style sanitization and robust parsing."""

import pytest
from subtitle_editor.models import ASSStyle
from subtitle_editor.parsers import ASSParser


class TestAssStyleSanitization:
    """ASSStyle.from_fields should coerce and clamp without raising."""

    @pytest.mark.unit
    @pytest.mark.models
    def test_valid_fields_pass_through(self):
        fields = {
            'name': 'Default', 'fontname': 'Arial', 'fontsize': '20',
            'primarycolour': '&H00FFFFFF', 'bold': '-1', 'italic': '0',
            'strikeout': '0', 'scalex': '100', 'scaley': '100',
            'alignment': '2', 'outline': '2', 'shadow': '0',
            'borderstyle': '1', 'marginl': '10',
        }
        warnings = []
        style = ASSStyle.from_fields(fields, warnings=warnings)
        assert style.name == 'Default'
        assert style.fontsize == 20
        assert style.bold is True
        assert style.scale_x == 100.0
        assert style.alignment == 2
        assert warnings == []

    @pytest.mark.unit
    @pytest.mark.models
    def test_non_numeric_fontsize_clamped_and_warned(self):
        warnings = []
        style = ASSStyle.from_fields({'fontsize': 'abc'}, warnings=warnings)
        assert style.fontsize == 20
        assert any('Font Size' in w for w in warnings)

    @pytest.mark.unit
    @pytest.mark.models
    def test_negative_scale_reset_to_100(self):
        warnings = []
        style = ASSStyle.from_fields({'scalex': '-50', 'scaley': '0'}, warnings=warnings)
        assert style.scale_x == 100.0
        assert style.scale_y == 100.0
        assert any('ScaleX' in w for w in warnings)
        assert any('ScaleY' in w for w in warnings)

    @pytest.mark.unit
    @pytest.mark.models
    def test_alignment_clamped_to_1_9(self):
        warnings = []
        too_low = ASSStyle.from_fields({'alignment': '0'}, warnings=warnings)
        too_high = ASSStyle.from_fields({'alignment': '12'}, warnings=warnings)
        assert too_low.alignment == 1
        assert too_high.alignment == 9

    @pytest.mark.unit
    @pytest.mark.models
    def test_border_style_must_be_1_or_3(self):
        warnings = []
        style = ASSStyle.from_fields({'borderstyle': '2'}, warnings=warnings)
        assert style.border_style == 1
        assert any('BorderStyle' in w for w in warnings)

    @pytest.mark.unit
    @pytest.mark.models
    def test_nonzero_is_truthy_for_flags(self):
        # Some editors use 1/0 instead of -1/0.
        style = ASSStyle.from_fields({'bold': '1', 'strikeout': '1'})
        assert style.bold is True
        assert style.strikeout is True

    @pytest.mark.unit
    @pytest.mark.models
    def test_fontsize_clamped_to_range(self):
        warnings = []
        big = ASSStyle.from_fields({'fontsize': '9999'}, warnings=warnings)
        assert big.fontsize == 200
        small = ASSStyle.from_fields({'fontsize': '0'}, warnings=warnings)
        assert small.fontsize == 1


class TestAssParserRobustness:
    """ASSParser should never crash on malformed style values."""

    @pytest.mark.parser
    @pytest.mark.unit
    def test_bad_style_values_do_not_raise(self):
        content = """[Script Info]
Title: Bad
ScriptType: v4.00+

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Broken,Arial,notanumber,&H00FFFFFF,&H00000000,&H00000000,&H00000000,-1,0,0,0,-50,0,0,0,2,2,2,99,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:02.00,Broken,,,0,0,0,,Hi
"""
        warnings = []
        doc = ASSParser.parse(content, warnings)
        assert len(doc.styles) == 1
        style = doc.styles[0]
        # Invalid fontsize -> default; negative scale -> 100; alignment 99 -> 9.
        assert style.fontsize == 20
        assert style.scale_x == 100.0
        assert style.alignment == 9
        assert style.border_style == 1
        assert len(warnings) >= 3

    @pytest.mark.parser
    @pytest.mark.unit
    def test_missing_fields_defaulted(self):
        content = """[Script Info]
ScriptType: v4.00+

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Minimal,Arial,24,&H00FFFFFF,&H00000000,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,2,2,10,10,10,1
"""
        doc = ASSParser.parse(content)
        assert doc.styles[0].name == 'Minimal'
        assert doc.styles[0].fontsize == 24
