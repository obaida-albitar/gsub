"""
Subtitle rendering with ASS styling support.

Renders subtitles on Cairo surfaces with proper styling, positioning, and formatting.
"""

import re
import cairo
from typing import Optional

import gi
gi.require_version('Pango', '1.0')
gi.require_version('PangoCairo', '1.0')
from gi.repository import Pango, PangoCairo

from subtitle_editor.models import ASSStyle, SubtitleDocument, SubtitleEntry


class SubtitleRenderer:
    """Renders subtitles with ASS styling support on Cairo surfaces."""

    def __init__(self):
        """Initialize the subtitle renderer."""
        self.current_style: Optional[ASSStyle] = None
        self.document: Optional[SubtitleDocument] = None
        # Global subtitle scale factor (similar to mpv's --sub-scale)
        # Default 0.75 to match common video players' comfortable reading size
        self.subtitle_scale = 0.75

    def set_document(self, document: Optional[SubtitleDocument]):
        """
        Set the subtitle document for style lookup.
        
        Args:
            document: SubtitleDocument containing styles and metadata
        """
        self.document = document

    def set_scale(self, scale: float):
        """
        Set the subtitle scale factor.
        
        Args:
            scale: Scale factor (0.1 to 2.0, default 0.75)
        """
        self.subtitle_scale = max(0.1, min(2.0, scale))

    def render(
        self,
        cr: cairo.Context,
        text: str,
        style_name: Optional[str],
        width: int,
        height: int,
        video_width: int = None,
        video_height: int = None,
        entry: SubtitleEntry = None,
    ):
        """
        Render subtitle text with styling on a Cairo context.

        Args:
            cr: Cairo context
            text: Subtitle text to render
            style_name: Name of style to apply
            width: Display width for positioning
            height: Display height for positioning
            video_width: Actual video resolution width (for reference)
            video_height: Actual video resolution height (for scaling calculation)
            entry: SubtitleEntry for per-entry margin overrides
        """
        if not text:
            return

        print(f"[Render] Display: {width}x{height}, Video: {video_width}x{video_height}, Style: {style_name}")

        # Get style from document
        style = self._get_style(style_name)
        
        # Get PlayResY from document metadata (ASS reference resolution)
        play_res_y = self._get_play_res_y(style)
        
        print(f"[Render] PlayResY: {play_res_y}")

        # Create Pango layout
        layout = PangoCairo.create_layout(cr)

        # Set text
        clean_text = self._strip_ass_override_codes(text)
        layout.set_text(clean_text, -1)

        # Apply styling scaled to current display size using PlayResY
        if style:
            font_desc = self._create_font_description(style, height, play_res_y)
            layout.set_font_description(font_desc)
        else:
            font_desc = self._create_default_font_description(height)
            layout.set_font_description(font_desc)

        # Set alignment and wrapping
        self._configure_layout(layout, style, width)

        # Get layout size
        ink_rect, logical_rect = layout.get_pixel_extents()
        text_width = logical_rect.width
        text_height = logical_rect.height

        print(f"[Render] Text size: {text_width}x{text_height}")

        # Calculate position based on alignment
        x, y = self._calculate_position(
            style, width, height, text_width, text_height, entry
        )
        
        if style:
            print(f"[Render] Position: ({x:.1f}, {y:.1f}), Alignment: {style.alignment}, Margins: L={style.margin_l} R={style.margin_r} V={style.margin_v}")
        else:
            print(f"[Render] Position: ({x:.1f}, {y:.1f}), Default alignment")

        # Draw shadow if needed
        if style and style.shadow > 0:
            self._draw_shadow(cr, layout, x, y, style.shadow)

        # Draw outline if needed
        if style and style.outline > 0:
            self._draw_outline(cr, layout, x, y, style)

        # Draw main text
        self._draw_text(cr, layout, x, y, style)

    def _get_style(self, style_name: Optional[str]) -> Optional[ASSStyle]:
        """Get style from document by name."""
        if not self.document:
            return None
        
        style = None
        if style_name:
            style = self.document.get_style_by_name(style_name)
        if not style and self.document.styles:
            style = self.document.styles[0]  # Default to first style
        
        return style

    def _get_play_res_y(self, style: Optional[ASSStyle]) -> int:
        """
        Get PlayResY (reference resolution) from document or infer it.
        
        Args:
            style: Current style (used for inference if PlayResY not set)
            
        Returns:
            PlayResY value
        """
        play_res_y = None
        
        # Try to get from metadata
        if self.document and self.document.metadata:
            play_res_y_str = self.document.metadata.get("PlayResY")
            if play_res_y_str:
                try:
                    play_res_y = int(play_res_y_str)
                except ValueError:
                    pass

        # If PlayResY is not set, try to infer it from font sizes
        if play_res_y is None and style and self.document:
            max_fontsize = max(
                (s.fontsize for s in self.document.styles), default=20
            )
            if max_fontsize >= 70:
                play_res_y = 1080  # Assume 1080p for very large fonts
            elif max_fontsize >= 50:
                play_res_y = 720  # Assume 720p for large fonts
            else:
                play_res_y = 384  # Default SD resolution
        
        # Final fallback
        if play_res_y is None or play_res_y <= 0:
            play_res_y = 384
        
        return play_res_y

    def _create_font_description(
        self, style: ASSStyle, display_height: int, play_res_y: int
    ) -> Pango.FontDescription:
        """
        Create a Pango font description from ASS style.

        Args:
            style: ASS style object
            display_height: Current display height for scaling
            play_res_y: ASS PlayResY value (reference resolution)
            
        Returns:
            Configured Pango.FontDescription
        """
        font_desc = Pango.FontDescription()
        font_desc.set_family(style.fontname or "Sans")

        # Scale font: (display_height / PlayResY) * fontsize * subtitle_scale
        scale_factor = display_height / play_res_y * self.subtitle_scale
        size = int(style.fontsize * scale_factor * Pango.SCALE)
        
        # Calculate actual pixel size for logging (avoid formatting issues with mocks in tests)
        try:
            pixel_size = size / Pango.SCALE
            print(f"[Render] Font: {style.fontname}, Size: {style.fontsize} → {pixel_size:.1f}px (scale: {scale_factor:.3f}, subtitle_scale: {self.subtitle_scale})")
        except (TypeError, AttributeError):
            # Handle mocked Pango.SCALE in tests
            print(f"[Render] Font: {style.fontname}, Size: {style.fontsize}, scale: {scale_factor:.3f}, subtitle_scale: {self.subtitle_scale}")
        
        font_desc.set_size(size)

        if style.bold:
            font_desc.set_weight(Pango.Weight.BOLD)
        if style.italic:
            font_desc.set_style(Pango.Style.ITALIC)

        return font_desc

    def _create_default_font_description(self, display_height: int) -> Pango.FontDescription:
        """Create default font description for non-styled subtitles."""
        font_desc = Pango.FontDescription()
        font_desc.set_family("Sans")
        # Use 4% of display height for default size
        default_size = int(display_height * 0.04 * Pango.SCALE)
        font_desc.set_size(default_size)
        font_desc.set_weight(Pango.Weight.BOLD)
        return font_desc

    def _configure_layout(self, layout, style: Optional[ASSStyle], width: int):
        """Configure Pango layout alignment and wrapping."""
        if style:
            # Set width to unlimited for accurate text measurement
            layout.set_width(-1)  # -1 = no wrapping based on width
            
            # Set Pango alignment based on ASS alignment
            if style.alignment in (1, 4, 7):  # Left-aligned
                layout.set_alignment(Pango.Alignment.LEFT)
            elif style.alignment in (3, 6, 9):  # Right-aligned
                layout.set_alignment(Pango.Alignment.RIGHT)
            else:  # Center (2, 5, 8)
                layout.set_alignment(Pango.Alignment.CENTER)
        else:
            # For non-ASS (e.g., SRT), use 90% width constraint
            layout.set_width(int(width * 0.9 * Pango.SCALE))
            layout.set_alignment(Pango.Alignment.CENTER)
        
        layout.set_wrap(Pango.WrapMode.WORD_CHAR)

    def _calculate_position(
        self,
        style: Optional[ASSStyle],
        width: int,
        height: int,
        text_width: int,
        text_height: int,
        entry: SubtitleEntry = None,
    ) -> tuple:
        """
        Calculate text position based on ASS alignment.
        
        Args:
            style: The ASS style to use
            width: Display width
            height: Display height
            text_width: Rendered text width
            text_height: Rendered text height
            entry: Optional subtitle entry for per-entry margin overrides
            
        Returns:
            Tuple of (x, y) position
        """
        if not style:
            # Default: bottom center
            x = (width - text_width) / 2
            y = height - text_height - (height * 0.05)  # 5% margin from bottom
            return (x, y)

        # ASS alignment: numpad layout (1=bottom-left, 2=bottom-center, etc.)
        alignment = style.alignment

        # Get margins: use entry overrides if non-zero, otherwise use style defaults
        margin_l = style.margin_l
        margin_r = style.margin_r
        margin_v = style.margin_v
        
        if entry:
            entry_ml = getattr(entry, 'margin_l', 0)
            entry_mr = getattr(entry, 'margin_r', 0)
            entry_mv = getattr(entry, 'margin_v', 0)
            
            if entry_ml != 0:
                margin_l = entry_ml
            if entry_mr != 0:
                margin_r = entry_mr
            if entry_mv != 0:
                margin_v = entry_mv

        # Horizontal position
        if alignment in (1, 4, 7):  # Left
            x = margin_l
        elif alignment in (3, 6, 9):  # Right
            x = width - text_width - margin_r
        else:  # Center (2, 5, 8)
            x = (width - text_width) / 2

        # Vertical position
        if alignment in (1, 2, 3):  # Bottom
            y = height - text_height - margin_v
        elif alignment in (7, 8, 9):  # Top
            y = margin_v
        else:  # Middle (4, 5, 6)
            y = (height - text_height) / 2

        return (x, y)

    def _draw_shadow(self, cr: cairo.Context, layout, x: float, y: float, shadow: float):
        """Draw shadow effect."""
        cr.save()
        cr.move_to(x + shadow, y + shadow)
        cr.set_source_rgba(0, 0, 0, 0.8)
        PangoCairo.show_layout(cr, layout)
        cr.restore()

    def _draw_outline(self, cr: cairo.Context, layout, x: float, y: float, style: ASSStyle):
        """Draw outline effect."""
        outline_color = self._parse_ass_color(style.outline_color)
        cr.save()
        cr.set_line_width(style.outline * 2)
        cr.set_source_rgba(*outline_color)
        cr.move_to(x, y)
        PangoCairo.layout_path(cr, layout)
        cr.stroke()
        cr.restore()

    def _draw_text(self, cr: cairo.Context, layout, x: float, y: float, style: Optional[ASSStyle]):
        """Draw main text."""
        if style:
            text_color = self._parse_ass_color(style.primary_color)
        else:
            text_color = (1.0, 1.0, 1.0, 1.0)  # White

        cr.save()
        cr.move_to(x, y)
        cr.set_source_rgba(*text_color)
        PangoCairo.show_layout(cr, layout)
        cr.restore()

    def _parse_ass_color(self, color_str: str) -> tuple:
        """
        Parse ASS color format (&HAABBGGRR) to RGBA tuple.
        
        Args:
            color_str: ASS color string
            
        Returns:
            RGBA tuple (r, g, b, a) with values 0.0-1.0
        """
        if not color_str or not color_str.startswith("&H"):
            return (1.0, 1.0, 1.0, 1.0)

        try:
            # Remove &H prefix
            hex_color = color_str[2:]
            # ASS colors are AABBGGRR
            if len(hex_color) >= 6:
                bb = int(hex_color[-2:], 16) / 255.0
                gg = int(hex_color[-4:-2], 16) / 255.0
                rr = int(hex_color[-6:-4], 16) / 255.0
                # Alpha is optional
                aa = 1.0
                if len(hex_color) >= 8:
                    aa = 1.0 - (int(hex_color[-8:-6], 16) / 255.0)
                return (rr, gg, bb, aa)
        except ValueError:
            pass

        return (1.0, 1.0, 1.0, 1.0)

    def _strip_ass_override_codes(self, text: str) -> str:
        """
        Remove ASS override codes from text.
        
        Args:
            text: Text with ASS codes
            
        Returns:
            Clean text without ASS codes
        """
        # Remove override blocks like {\i1}, {\b1}, etc.
        text = re.sub(r"\{[^}]*\}", "", text)
        return text
