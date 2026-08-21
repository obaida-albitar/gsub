"""Tests for defensive ASS style sanitization and robust parsing."""

import pytest
from gsub.models import ASSStyle
from gsub.parsers import ASSParser


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

    @pytest.mark.unit
    @pytest.mark.models
    def test_newly_exposed_fields_round_trip(self):
        """The style editor now exposes the full set of numeric/flag fields.

        Verify they are parsed from fields and survive a serialize round-trip
        via to_ass_string().
        """
        fields = {
            'name': 'Full', 'fontname': 'DejaVu Sans', 'fontsize': '42',
            'primarycolour': '&H00FFFFFF', 'secondarycolour': '&H000000FF',
            'outlinecolour': '&H00000000', 'backcolour': '&H00000000',
            'bold': '-1', 'italic': '0', 'underline': '1', 'strikeout': '-1',
            'scalex': '120', 'scaley': '80', 'spacing': '3', 'angle': '15',
            'borderstyle': '3', 'outline': '4', 'shadow': '1',
            'alignment': '7', 'marginl': '20', 'marginr': '30',
            'marginv': '40', 'encoding': '0',
        }
        style = ASSStyle.from_fields(fields)
        assert style.underline is True
        assert style.strikeout is True
        assert style.spacing == 3.0
        assert style.angle == 15.0
        assert style.border_style == 3
        assert style.scale_x == 120.0
        assert style.scale_y == 80.0
        assert style.margin_l == 20
        assert style.margin_r == 30
        assert style.margin_v == 40
        assert style.encoding == 0

        # The serialized string must carry the same values back.
        # Integer-valued floats are emitted without a trailing '.0'.
        # split[0] is "Style: <name>", so field offsets start at index 1.
        parts = style.to_ass_string().split(',')
        assert parts[1] == 'DejaVu Sans'
        assert parts[2] == '42'
        assert parts[7] == '-1'   # bold
        assert parts[8] == '0'     # italic
        assert parts[9] == '-1'    # underline
        assert parts[10] == '-1'   # strikeout
        assert parts[11] == '120'  # scalex
        assert parts[12] == '80'   # scaley
        assert parts[13] == '3'    # spacing
        assert parts[14] == '15'   # angle
        assert parts[15] == '3'    # borderstyle
        assert parts[16] == '4'    # outline
        assert parts[17] == '1'    # shadow
        assert parts[18] == '7'    # alignment
        assert parts[19] == '20'   # marginl
        assert parts[20] == '30'   # marginr
        assert parts[21] == '40'   # marginv
        assert parts[22] == '0'    # encoding

    @pytest.mark.unit
    @pytest.mark.models
    def test_negative_or_zero_scale_reset_to_100(self):
        warnings = []
        style = ASSStyle.from_fields({'scalex': '-5', 'scaley': '0'}, warnings=warnings)
        assert style.scale_x == 100.0
        assert style.scale_y == 100.0
        assert any('ScaleX' in w for w in warnings)
        assert any('ScaleY' in w for w in warnings)

    @pytest.mark.unit
    @pytest.mark.models
    def test_large_but_valid_scale_preserved(self):
        # Fansub logo/sign styling legitimately uses very large ScaleX/ScaleY
        # (e.g. a tiny font scaled thousands of percent). These must NOT be
        # clamped; only non-positive / non-finite values are invalid.
        warnings = []
        style = ASSStyle.from_fields({'scalex': '4300', 'scaley': '4300'}, warnings=warnings)
        assert style.scale_x == 4300.0
        assert style.scale_y == 4300.0
        assert warnings == []

    @pytest.mark.unit
    @pytest.mark.models
    def test_to_fields_round_trips_losslessly(self):
        style = ASSStyle(
            name='Sign', fontname='Sansation', fontsize=36,
            primary_color='&H00FFFFFF', secondary_color='&H000000FF',
            outline_color='&H00000000', back_color='&H80000000',
            bold=True, italic=False, underline=True, strikeout=True,
            scale_x=123.5, scale_y=100.0, spacing=1.5, angle=-12.25,
            border_style=3, outline=2.5, shadow=0.0, alignment=7,
            margin_l=20, margin_r=30, margin_v=40, encoding=0,
        )
        round_tripped = ASSStyle.from_fields(style.to_fields())
        assert round_tripped == style


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
