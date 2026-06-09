"""
ASS/SSA (Advanced SubStation Alpha) subtitle format parser.

ASS format is more complex than SRT, with sections for metadata, styles, and events.
"""

import logging
import re
from typing import List, Dict
from subtitle_editor.models import (
    SubtitleEntry, SubtitleDocument, SubtitleFormat,
    TimeCode, ASSStyle
)

logger = logging.getLogger(__name__)


class ASSParser:
    """Parser for ASS/SSA subtitle format."""
    
    # Regex for ASS timecode: H:MM:SS.cc (centiseconds)
    TIMECODE_PATTERN = re.compile(r'(\d+):(\d{2}):(\d{2})\.(\d{2})')
    
    @classmethod
    def parse(cls, content: str) -> SubtitleDocument:
        """Parse ASS/SSA content into a SubtitleDocument."""
        lines = content.split('\n')
        
        # Detect format (ASS or SSA)
        format_type = SubtitleFormat.ASS
        for line in lines[:10]:
            if '[Script Info]' in line:
                # Check if it mentions SSA
                pass
            if 'ScriptType: v4.00' in line:
                format_type = SubtitleFormat.SSA
        
        document = SubtitleDocument(format=format_type)
        
        current_section = None
        style_format = []
        event_format = []
        
        for line in lines:
            line = line.strip()
            
            # Section headers
            if line.startswith('['):
                current_section = line.lower()
                continue
            
            if not line or line.startswith(';'):
                # Empty line or comment
                continue
            
            # Parse based on current section
            if current_section == '[script info]':
                cls._parse_script_info(line, document)

            elif current_section == '[aegisub project garbage]':
                cls._parse_aegisub_garbage(line, document)
            
            elif current_section == '[v4+ styles]' or current_section == '[v4 styles]':
                if line.startswith('Format:'):
                    style_format = [f.strip() for f in line[7:].split(',')]
                elif line.startswith('Style:'):
                    style = cls._parse_style(line, style_format)
                    if style:
                        document.styles.append(style)
            
            elif current_section == '[events]':
                if line.startswith('Format:'):
                    event_format = [f.strip() for f in line[7:].split(',')]
                elif line.startswith('Dialogue:'):
                    entry = cls._parse_dialogue(line, event_format, len(document.entries) + 1)
                    if entry:
                        document.entries.append(entry)
        
        # Ensure at least one default style exists
        if not document.styles:
            document.styles.append(ASSStyle())
        
        document.reindex()
        document.modified = False
        return document
    
    @classmethod
    def _parse_script_info(cls, line: str, document: SubtitleDocument):
        """Parse a line from the Script Info section."""
        if ':' in line:
            key, value = line.split(':', 1)
            document.metadata[key.strip()] = value.strip()

    @classmethod
    def _parse_aegisub_garbage(cls, line: str, document: SubtitleDocument):
        """Parse a line from the [Aegisub Project Garbage] section."""
        if ':' in line:
            key, value = line.split(':', 1)
            document.aegisub_project_garbage[key.strip()] = value.strip()
    
    @classmethod
    def _parse_style(cls, line: str, format_list: List[str]) -> ASSStyle:
        """Parse a Style line."""
        # Remove 'Style: ' prefix
        content = line[6:].strip()
        values = [v.strip() for v in content.split(',')]
        
        if len(values) < len(format_list):
            logger.warning("Skipping ASS style with insufficient fields: %s", line)
            return None
        
        style = ASSStyle()
        
        # Map values according to format
        for i, field in enumerate(format_list):
            if i >= len(values):
                break
            
            value = values[i]
            field_lower = field.lower()
            
            if field_lower == 'name':
                style.name = value
            elif field_lower == 'fontname':
                style.fontname = value
            elif field_lower == 'fontsize':
                style.fontsize = int(value)
            elif field_lower == 'primarycolour':
                style.primary_color = value
            elif field_lower == 'secondarycolour':
                style.secondary_color = value
            elif field_lower == 'outlinecolour':
                style.outline_color = value
            elif field_lower == 'backcolour':
                style.back_color = value
            elif field_lower == 'bold':
                style.bold = int(value) != 0
            elif field_lower == 'italic':
                style.italic = int(value) != 0
            elif field_lower == 'underline':
                style.underline = int(value) != 0
            elif field_lower == 'strikeout':
                style.strikeout = int(value) != 0
            elif field_lower == 'scalex':
                style.scale_x = float(value)
            elif field_lower == 'scaley':
                style.scale_y = float(value)
            elif field_lower == 'spacing':
                style.spacing = float(value)
            elif field_lower == 'angle':
                style.angle = float(value)
            elif field_lower == 'borderstyle':
                style.border_style = int(value)
            elif field_lower == 'outline':
                style.outline = float(value)
            elif field_lower == 'shadow':
                style.shadow = float(value)
            elif field_lower == 'alignment':
                style.alignment = int(value)
            elif field_lower == 'marginl':
                style.margin_l = int(value)
            elif field_lower == 'marginr':
                style.margin_r = int(value)
            elif field_lower == 'marginv':
                style.margin_v = int(value)
            elif field_lower == 'encoding':
                style.encoding = int(value)
        
        return style
    
    @classmethod
    def _parse_dialogue(cls, line: str, format_list: List[str], index: int) -> SubtitleEntry:
        """Parse a Dialogue line."""
        # Remove 'Dialogue: ' prefix
        content = line[9:].strip()
        
        # Split carefully - text may contain commas
        # Format typically: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
        parts = content.split(',', len(format_list) - 1)

        if len(parts) < len(format_list):
            logger.warning("Skipping ASS dialogue with insufficient fields: %s", line)
            return None
        
        start_time = None
        end_time = None
        text = ""
        style = None
        margin_l = 0
        margin_r = 0
        margin_v = 0
        layer = 0
        actor = ""
        effect = ""
        
        for i, field in enumerate(format_list):
            if i >= len(parts):
                break
            
            value = parts[i].strip()
            field_lower = field.lower()
            
            if field_lower == 'start':
                start_time = cls._parse_timecode(value)
            elif field_lower == 'end':
                end_time = cls._parse_timecode(value)
            elif field_lower == 'text':
                text = value
                # Handle ASS formatting tags in text
                text = text.replace('\\N', '\n').replace('\\n', '\n')
            elif field_lower == 'style':
                style = value
            elif field_lower == 'marginl':
                try:
                    margin_l = int(value)
                except ValueError:
                    margin_l = 0
            elif field_lower == 'marginr':
                try:
                    margin_r = int(value)
                except ValueError:
                    margin_r = 0
            elif field_lower == 'marginv':
                try:
                    margin_v = int(value)
                except ValueError:
                    margin_v = 0
            elif field_lower == 'layer':
                try:
                    layer = int(value)
                except ValueError:
                    layer = 0
            elif field_lower == 'name':
                actor = value
            elif field_lower == 'effect':
                effect = value
        
        if start_time and end_time:
            return SubtitleEntry(
                index=index,
                start_time=start_time,
                end_time=end_time,
                text=text,
                style=style,
                margin_l=margin_l,
                margin_r=margin_r,
                margin_v=margin_v,
                layer=layer,
                actor=actor,
                effect=effect
            )

        logger.warning("Skipping ASS dialogue with missing start or end time: %s", line)
        return None
    
    @classmethod
    def _parse_timecode(cls, timecode_str: str) -> TimeCode:
        """Parse an ASS timecode string."""
        match = cls.TIMECODE_PATTERN.match(timecode_str)
        if match:
            hours = int(match.group(1))
            minutes = int(match.group(2))
            seconds = int(match.group(3))
            centiseconds = int(match.group(4))
            milliseconds = centiseconds * 10
            
            return TimeCode(hours, minutes, seconds, milliseconds)
        return TimeCode()
    
    @classmethod
    def serialize(cls, document: SubtitleDocument) -> str:
        """Serialize a SubtitleDocument to ASS format."""
        lines = []
        
        # [Script Info] section
        lines.append('[Script Info]')
        lines.append('; Script generated by GNOME Subtitle Editor')

        # Common Script Info keys with reasonable defaults.
        # We only emit each key once (no duplicates), preferring values from document.metadata.
        defaults = {
            'Title': 'Untitled',
            'ScriptType': 'v4.00+',
            'WrapStyle': '0',
            'ScaledBorderAndShadow': 'yes',
            'YCbCr Matrix': 'None',
        }

        merged = dict(defaults)
        merged.update(document.metadata or {})

        preferred_order = ['Title', 'ScriptType', 'WrapStyle', 'ScaledBorderAndShadow', 'YCbCr Matrix']

        for key in preferred_order:
            if key in merged:
                lines.append(f"{key}: {merged[key]}")

        # Emit the remaining keys deterministically.
        for key in sorted(k for k in merged.keys() if k not in set(preferred_order)):
            lines.append(f"{key}: {merged[key]}")
        
        lines.append('')

        # [Aegisub Project Garbage] section (optional)
        if getattr(document, 'aegisub_project_garbage', None):
            if document.aegisub_project_garbage:
                lines.append('[Aegisub Project Garbage]')
                for key in sorted(document.aegisub_project_garbage.keys()):
                    lines.append(f"{key}: {document.aegisub_project_garbage[key]}")
                lines.append('')
        
        # [V4+ Styles] section
        lines.append('[V4+ Styles]')
        lines.append('Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, '
                    'OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, '
                    'ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, '
                    'Alignment, MarginL, MarginR, MarginV, Encoding')
        
        for style in document.styles:
            lines.append(style.to_ass_string())
        
        lines.append('')
        
        # [Events] section
        lines.append('[Events]')
        lines.append('Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text')
        
        for entry in document.entries:
            layer = getattr(entry, 'layer', 0)
            style = entry.style or 'Default'
            name = getattr(entry, 'actor', '')
            # Use per-entry margins if set, otherwise default to 0
            margin_l = getattr(entry, 'margin_l', 0)
            margin_r = getattr(entry, 'margin_r', 0)
            margin_v = getattr(entry, 'margin_v', 0)
            effect = getattr(entry, 'effect', '')
            
            # Convert newlines in text to ASS format
            text = entry.text.replace('\n', '\\N')
            
            dialogue_line = (f'Dialogue: {layer},{entry.start_time.to_ass_format()},'
                           f'{entry.end_time.to_ass_format()},{style},{name},'
                           f'{margin_l},{margin_r},{margin_v},{effect},{text}')
            lines.append(dialogue_line)
        
        return '\n'.join(lines)
