"""
Subtitle format converter.

Converts between different subtitle formats (SRT, ASS, SSA).
"""

from gsub.models import SubtitleDocument, SubtitleFormat, ASSStyle, SubtitleEntry, TimeCode
from gsub.parsers import SRTParser, ASSParser
from gsub.logger import get_logger

logger = get_logger(__name__)


class FormatConverter:
    """Converts subtitle documents between different formats."""
    
    @staticmethod
    def convert(document: SubtitleDocument, target_format: SubtitleFormat) -> SubtitleDocument:
        """
        Convert a subtitle document to a different format.
        
        Args:
            document: Source document
            target_format: Target format (SRT, ASS, or SSA)
            
        Returns:
            New SubtitleDocument in the target format
        """
        if document.format == target_format:
            logger.info(f"Document already in {target_format.value} format")
            return document
        
        logger.info(f"Converting from {document.format.value} to {target_format.value}")
        
        # Create new document with target format
        new_doc = SubtitleDocument(format=target_format)
        new_doc.file_path = document.file_path
        new_doc.modified = True  # Mark as modified since format changed
        
        # Convert based on target format
        if target_format == SubtitleFormat.SRT:
            FormatConverter._convert_to_srt(document, new_doc)
        elif target_format in (SubtitleFormat.ASS, SubtitleFormat.SSA):
            FormatConverter._convert_to_ass(document, new_doc, target_format)
        
        return new_doc
    
    @staticmethod
    def _convert_to_srt(source: SubtitleDocument, target: SubtitleDocument):
        """Convert any format to SRT (strip styling)."""
        # Copy entries, stripping any styling information
        for entry in source.entries:
            new_entry = SubtitleEntry(
                index=entry.index,
                start_time=entry.start_time,
                end_time=entry.end_time,
                text=FormatConverter._strip_ass_tags(entry.text)
            )
            target.entries.append(new_entry)
        
        logger.info(f"Converted {len(target.entries)} entries to SRT")
    
    @staticmethod
    def _convert_to_ass(source: SubtitleDocument, target: SubtitleDocument, target_format: SubtitleFormat):
        """Convert any format to ASS/SSA."""
        # Set up default ASS metadata
        target.metadata = {
            'Title': 'Converted Subtitle',
            'ScriptType': 'v4.00+' if target_format == SubtitleFormat.ASS else 'v4.00',
            'WrapStyle': '0',
            'ScaledBorderAndShadow': 'yes',
            'YCbCr Matrix': 'None',
            'PlayResX': '1920',
            'PlayResY': '1080'
        }
        
        # If source is already ASS/SSA, preserve metadata and styles
        if source.format in (SubtitleFormat.ASS, SubtitleFormat.SSA):
            if source.metadata:
                target.metadata.update(source.metadata)
            if source.styles:
                target.styles = [FormatConverter._copy_style(s) for s in source.styles]
        else:
            # Create default style for SRT conversion
            default_style = ASSStyle(
                name='Default',
                fontname='Arial',
                fontsize=52,
                primary_color='&H00FFFFFF',  # White
                secondary_color='&H000000FF',  # Red
                outline_color='&H00000000',  # Black
                back_color='&H80000000',  # Semi-transparent black
                bold=True,
                italic=False,
                underline=False,
                strikeout=False,
                scale_x=100,
                scale_y=100,
                spacing=0,
                angle=0,
                border_style=1,
                outline=2,
                shadow=1,
                alignment=2,  # Bottom center
                margin_l=10,
                margin_r=10,
                margin_v=10,
                encoding=1
            )
            target.styles = [default_style]
        
        # Copy entries with style information
        for entry in source.entries:
            new_entry = SubtitleEntry(
                index=entry.index,
                start_time=entry.start_time,
                end_time=entry.end_time,
                text=entry.text,
                style=entry.style if hasattr(entry, 'style') else 'Default',
                margin_l=getattr(entry, 'margin_l', 0),
                margin_r=getattr(entry, 'margin_r', 0),
                margin_v=getattr(entry, 'margin_v', 0)
            )
            target.entries.append(new_entry)
        
        logger.info(f"Converted {len(target.entries)} entries to {target_format.value}")
    
    @staticmethod
    def _copy_style(style: ASSStyle) -> ASSStyle:
        """Create a deep copy of an ASS style."""
        return ASSStyle(
            name=style.name,
            fontname=style.fontname,
            fontsize=style.fontsize,
            primary_color=style.primary_color,
            secondary_color=style.secondary_color,
            outline_color=style.outline_color,
            back_color=style.back_color,
            bold=style.bold,
            italic=style.italic,
            underline=style.underline,
            strikeout=style.strikeout,
            scale_x=style.scale_x,
            scale_y=style.scale_y,
            spacing=style.spacing,
            angle=style.angle,
            border_style=style.border_style,
            outline=style.outline,
            shadow=style.shadow,
            alignment=style.alignment,
            margin_l=style.margin_l,
            margin_r=style.margin_r,
            margin_v=style.margin_v,
            encoding=style.encoding
        )
    
    @staticmethod
    def _strip_ass_tags(text: str) -> str:
        """Remove ASS override tags from text."""
        import re
        # Remove override blocks like {\i1}, {\b1}, etc.
        text = re.sub(r'\{[^}]*\}', '', text)
        return text
