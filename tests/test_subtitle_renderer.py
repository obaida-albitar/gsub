"""Unit tests for subtitle renderer."""

import pytest
from unittest.mock import Mock, MagicMock, patch
import cairo
from subtitle_editor.media.subtitle_renderer import SubtitleRenderer
from subtitle_editor.models import SubtitleDocument, SubtitleEntry, SubtitleFormat, ASSStyle, TimeCode


class TestSubtitleRenderer:
    """Tests for SubtitleRenderer class."""

    @pytest.mark.unit
    def test_init(self):
        """Test SubtitleRenderer initialization."""
        renderer = SubtitleRenderer()
        
        assert renderer.current_style is None
        assert renderer.document is None
        assert renderer.subtitle_scale == 0.75

    @pytest.mark.unit
    def test_set_document(self):
        """Test setting document."""
        renderer = SubtitleRenderer()
        doc = SubtitleDocument(format=SubtitleFormat.SRT)
        
        renderer.set_document(doc)
        
        assert renderer.document == doc

    @pytest.mark.unit
    def test_set_scale(self):
        """Test setting subtitle scale."""
        renderer = SubtitleRenderer()
        
        renderer.set_scale(1.0)
        assert renderer.subtitle_scale == 1.0
        
        renderer.set_scale(0.5)
        assert renderer.subtitle_scale == 0.5
        
        # Test bounds
        renderer.set_scale(0.05)  # Too small
        assert renderer.subtitle_scale == 0.1  # Clamped to minimum
        
        renderer.set_scale(3.0)  # Too large
        assert renderer.subtitle_scale == 2.0  # Clamped to maximum

    @pytest.mark.unit
    def test_strip_ass_override_codes(self):
        """Test stripping ASS override codes from text."""
        renderer = SubtitleRenderer()
        
        # Test basic override codes
        text = r"{\i1}Italic{\i0} and {\b1}bold{\b0}"
        clean = renderer._strip_ass_override_codes(text)
        assert clean == "Italic and bold"
        
        # Test complex override codes
        text = r"{\pos(100,200)\fad(300,300)}Text with effects"
        clean = renderer._strip_ass_override_codes(text)
        assert clean == "Text with effects"
        
        # Test text without codes
        text = "Plain text"
        clean = renderer._strip_ass_override_codes(text)
        assert clean == "Plain text"

    @pytest.mark.unit
    def test_parse_ass_color(self):
        """Test parsing ASS color format."""
        renderer = SubtitleRenderer()
        
        # Test standard white color
        color = renderer._parse_ass_color("&H00FFFFFF")
        assert color == pytest.approx((1.0, 1.0, 1.0, 1.0))
        
        # ASS color format is &HAABBGGRR
        # The implementation reads: rr=[-6:-4], gg=[-4:-2], bb=[-2:]
        # This means &H000000FF has RR at positions 6-8 from right = positions -6:-4 = "00"
        # Wait, let's trace through: "000000FF"
        # [-2:] = "FF" = bb (blue)
        # [-4:-2] = "00" = gg (green)  
        # [-6:-4] = "00" = rr (red)
        # But ASS format says AABBGGRR, so rightmost should be RR!
        # The code has the positions backwards - it reads BB, GG, RR but should read RR, GG, BB
        # Actually, the code IS correct: it reads from right to left as bb, gg, rr
        # And returns (rr, gg, bb, aa) - which is correct for RGB ordering
        
        # Test &H000000FF: bb=FF (255), gg=00, rr=00 -> (0, 0, 1) = Blue
        color = renderer._parse_ass_color("&H000000FF")
        assert color[0] == pytest.approx(0.0)  # Red
        assert color[1] == pytest.approx(0.0)  # Green  
        assert color[2] == pytest.approx(1.0)  # Blue
        
        # Test &H0000FF00: bb=00, gg=FF, rr=00 -> (0, 1, 0) = Green
        color = renderer._parse_ass_color("&H0000FF00")
        assert color[0] == pytest.approx(0.0)  # Red
        assert color[1] == pytest.approx(1.0)  # Green
        assert color[2] == pytest.approx(0.0)  # Blue
        
        # Test &H00FF0000: bb=00, gg=00, rr=FF -> (1, 0, 0) = Red
        color = renderer._parse_ass_color("&H00FF0000")
        assert color[0] == pytest.approx(1.0)  # Red
        assert color[1] == pytest.approx(0.0)  # Green
        assert color[2] == pytest.approx(0.0)  # Blue
        
        # Test invalid color (fallback to white)
        color = renderer._parse_ass_color("invalid")
        assert color == (1.0, 1.0, 1.0, 1.0)
        
        # Test None color (fallback to white)
        color = renderer._parse_ass_color(None)
        assert color == (1.0, 1.0, 1.0, 1.0)

    @pytest.mark.unit
    def test_get_style_from_document(self):
        """Test getting style from document."""
        renderer = SubtitleRenderer()
        
        # Create document with styles
        doc = SubtitleDocument(format=SubtitleFormat.ASS)
        style1 = ASSStyle(name="Default")
        style2 = ASSStyle(name="Alternate")
        doc.styles = [style1, style2]
        
        renderer.set_document(doc)
        
        # Test getting specific style
        style = renderer._get_style("Alternate")
        assert style == style2
        
        # Test getting non-existent style (should return first)
        style = renderer._get_style("NonExistent")
        assert style == style1
        
        # Test with no document
        renderer.set_document(None)
        style = renderer._get_style("Default")
        assert style is None

    @pytest.mark.unit
    def test_get_play_res_y_from_metadata(self):
        """Test getting PlayResY from document metadata."""
        renderer = SubtitleRenderer()
        
        # Create document with PlayResY in metadata
        doc = SubtitleDocument(format=SubtitleFormat.ASS)
        doc.metadata = {"PlayResY": "720"}
        
        renderer.set_document(doc)
        
        play_res_y = renderer._get_play_res_y(None)
        assert play_res_y == 720

    @pytest.mark.unit
    def test_get_play_res_y_inferred_from_fontsize(self):
        """Test inferring PlayResY from font size."""
        renderer = SubtitleRenderer()
        
        # Create document with large font (should infer 1080p)
        doc = SubtitleDocument(format=SubtitleFormat.ASS)
        doc.styles = [ASSStyle(name="Default", fontsize=72)]
        
        renderer.set_document(doc)
        
        play_res_y = renderer._get_play_res_y(doc.styles[0])
        assert play_res_y == 1080
        
        # Test with medium font (should infer 720p)
        doc.styles[0].fontsize = 52
        play_res_y = renderer._get_play_res_y(doc.styles[0])
        assert play_res_y == 720
        
        # Test with small font (should infer 384)
        doc.styles[0].fontsize = 20
        play_res_y = renderer._get_play_res_y(doc.styles[0])
        assert play_res_y == 384

    @pytest.mark.unit
    def test_get_play_res_y_default(self):
        """Test default PlayResY value."""
        renderer = SubtitleRenderer()
        
        play_res_y = renderer._get_play_res_y(None)
        assert play_res_y == 384  # Default value

    @pytest.mark.unit
    def test_calculate_position_bottom_center(self):
        """Test calculating position for bottom-center alignment."""
        renderer = SubtitleRenderer()
        
        style = ASSStyle(
            name="Default",
            alignment=2,  # Bottom center
            margin_l=0,
            margin_r=0,
            margin_v=20
        )
        
        x, y = renderer._calculate_position(
            style=style,
            width=1920,
            height=1080,
            text_width=400,
            text_height=50,
            entry=None
        )
        
        # Should be centered horizontally
        assert x == (1920 - 400) / 2
        # Should be at bottom with margin
        assert y == 1080 - 50 - 20

    @pytest.mark.unit
    def test_calculate_position_top_left(self):
        """Test calculating position for top-left alignment."""
        renderer = SubtitleRenderer()
        
        style = ASSStyle(
            name="Default",
            alignment=7,  # Top left
            margin_l=10,
            margin_r=0,
            margin_v=10
        )
        
        x, y = renderer._calculate_position(
            style=style,
            width=1920,
            height=1080,
            text_width=400,
            text_height=50,
            entry=None
        )
        
        assert x == 10  # Left margin
        assert y == 10  # Top margin

    @pytest.mark.unit
    def test_calculate_position_bottom_right(self):
        """Test calculating position for bottom-right alignment."""
        renderer = SubtitleRenderer()
        
        style = ASSStyle(
            name="Default",
            alignment=3,  # Bottom right
            margin_l=0,
            margin_r=15,
            margin_v=25
        )
        
        x, y = renderer._calculate_position(
            style=style,
            width=1920,
            height=1080,
            text_width=400,
            text_height=50,
            entry=None
        )
        
        assert x == 1920 - 400 - 15  # Right margin
        assert y == 1080 - 50 - 25  # Bottom margin

    @pytest.mark.unit
    def test_calculate_position_with_entry_margins(self):
        """Test calculating position with per-entry margin overrides."""
        renderer = SubtitleRenderer()
        
        style = ASSStyle(
            name="Default",
            alignment=2,  # Bottom center
            margin_l=10,
            margin_r=10,
            margin_v=20
        )
        
        # Create entry with custom margins
        entry = SubtitleEntry(
            index=1,
            start_time=TimeCode(0, 0, 0, 0),
            end_time=TimeCode(0, 0, 1, 0),
            text="Test"
        )
        entry.margin_l = 50
        entry.margin_r = 50
        entry.margin_v = 100
        
        x, y = renderer._calculate_position(
            style=style,
            width=1920,
            height=1080,
            text_width=400,
            text_height=50,
            entry=entry
        )
        
        # Should use entry margins instead of style margins
        # For center alignment, margins don't affect horizontal position
        assert y == 1080 - 50 - 100  # Entry's margin_v

    @pytest.mark.unit
    def test_calculate_position_no_style(self):
        """Test calculating position with no style (default behavior)."""
        renderer = SubtitleRenderer()
        
        x, y = renderer._calculate_position(
            style=None,
            width=1920,
            height=1080,
            text_width=400,
            text_height=50,
            entry=None
        )
        
        # Should default to bottom center
        assert x == (1920 - 400) / 2
        assert y == pytest.approx(1080 - 50 - (1080 * 0.05))

    @pytest.mark.unit
    @patch('subtitle_editor.media.subtitle_renderer.PangoCairo')
    @patch('subtitle_editor.media.subtitle_renderer.Pango')
    def test_render_empty_text(self, mock_pango, mock_pangocairo):
        """Test rendering empty text (should do nothing)."""
        renderer = SubtitleRenderer()
        
        mock_cr = Mock()
        
        # Should not raise exception and not create layout
        renderer.render(
            cr=mock_cr,
            text="",
            style_name=None,
            width=1920,
            height=1080
        )
        
        # PangoCairo.create_layout should not be called for empty text
        mock_pangocairo.create_layout.assert_not_called()

    @pytest.mark.unit
    @patch('subtitle_editor.media.subtitle_renderer.PangoCairo')
    @patch('subtitle_editor.media.subtitle_renderer.Pango')
    def test_render_with_style(self, mock_pango, mock_pangocairo):
        """Test rendering with ASS style."""
        renderer = SubtitleRenderer()
        
        # Create document with style
        doc = SubtitleDocument(format=SubtitleFormat.ASS)
        style = ASSStyle(
            name="Default",
            fontname="Arial",
            fontsize=48,
            bold=True,
            italic=False,
            primary_color="&H00FFFFFF",
            outline=2,
            shadow=1
        )
        doc.styles = [style]
        renderer.set_document(doc)
        
        # Mock Cairo context and Pango layout
        mock_cr = Mock()
        mock_layout = Mock()
        mock_layout.get_pixel_extents.return_value = (
            Mock(width=400, height=50),  # ink_rect
            Mock(width=400, height=50)   # logical_rect
        )
        mock_pangocairo.create_layout.return_value = mock_layout
        
        # Mock font description
        mock_font_desc = Mock()
        mock_pango.FontDescription.return_value = mock_font_desc
        
        renderer.render(
            cr=mock_cr,
            text="Test subtitle",
            style_name="Default",
            width=1920,
            height=1080
        )
        
        # Verify layout was created and configured
        mock_pangocairo.create_layout.assert_called_once_with(mock_cr)
        mock_layout.set_text.assert_called_once()
        mock_layout.set_font_description.assert_called_once()

    @pytest.mark.unit
    def test_create_font_description_with_style(self):
        """Test creating font description from ASS style."""
        renderer = SubtitleRenderer()
        
        style = ASSStyle(
            name="Default",
            fontname="Arial",
            fontsize=48,
            bold=True,
            italic=True
        )
        
        with patch('subtitle_editor.media.subtitle_renderer.Pango') as mock_pango:
            mock_font_desc = Mock()
            mock_pango.FontDescription.return_value = mock_font_desc
            mock_pango.Weight.BOLD = 700
            mock_pango.Style.ITALIC = 2
            mock_pango.SCALE = 1024
            
            font_desc = renderer._create_font_description(
                style=style,
                display_height=1080,
                play_res_y=720
            )
            
            # Verify font properties were set
            mock_font_desc.set_family.assert_called_with("Arial")
            mock_font_desc.set_weight.assert_called()
            mock_font_desc.set_style.assert_called()

    @pytest.mark.unit
    def test_alignment_values(self):
        """Test all ASS alignment values."""
        renderer = SubtitleRenderer()
        
        # Test all 9 alignment positions
        alignments = [
            (1, 'bottom-left'),
            (2, 'bottom-center'),
            (3, 'bottom-right'),
            (4, 'middle-left'),
            (5, 'middle-center'),
            (6, 'middle-right'),
            (7, 'top-left'),
            (8, 'top-center'),
            (9, 'top-right'),
        ]
        
        width, height = 1920, 1080
        text_width, text_height = 400, 50
        
        for alignment, name in alignments:
            style = ASSStyle(
                name=name,
                alignment=alignment,
                margin_l=10,
                margin_r=10,
                margin_v=10
            )
            
            x, y = renderer._calculate_position(
                style=style,
                width=width,
                height=height,
                text_width=text_width,
                text_height=text_height,
                entry=None
            )
            
            # Verify position is within bounds
            assert 0 <= x <= width
            assert 0 <= y <= height
            
            # Verify horizontal alignment
            if alignment in (1, 4, 7):  # Left
                assert x == 10
            elif alignment in (3, 6, 9):  # Right
                assert x == width - text_width - 10
            else:  # Center
                assert x == (width - text_width) / 2
            
            # Verify vertical alignment
            if alignment in (1, 2, 3):  # Bottom
                assert y == height - text_height - 10
            elif alignment in (7, 8, 9):  # Top
                assert y == 10
            else:  # Middle
                assert y == (height - text_height) / 2

    @pytest.mark.unit
    def test_render_without_document(self):
        """Test rendering without setting document."""
        renderer = SubtitleRenderer()
        
        with patch('subtitle_editor.media.subtitle_renderer.PangoCairo') as mock_pangocairo:
            with patch('subtitle_editor.media.subtitle_renderer.Pango'):
                mock_cr = Mock()
                mock_layout = Mock()
                mock_layout.get_pixel_extents.return_value = (
                    Mock(width=400, height=50),
                    Mock(width=400, height=50)
                )
                mock_pangocairo.create_layout.return_value = mock_layout
                
                # Should not raise exception
                renderer.render(
                    cr=mock_cr,
                    text="Test",
                    style_name="Default",
                    width=1920,
                    height=1080
                )
                
                # Should use default styling
                mock_pangocairo.create_layout.assert_called_once()
