"""
ASS/SSA (Advanced SubStation Alpha) subtitle format parser.

ASS format is more complex than SRT, with sections for metadata, styles, and events.
"""

import logging
import re
from typing import List, Dict, Optional
from gsub.models import (
    SubtitleEntry, SubtitleDocument, SubtitleFormat,
    TimeCode, ASSStyle
)
from gsub.parsers.ass_tags import has_unbalanced_braces

logger = logging.getLogger(__name__)


class ASSParser:
    """Parser for ASS/SSA subtitle format."""
    
    # Regex for ASS timecode: H:MM:SS.cc (centiseconds)
    TIMECODE_PATTERN = re.compile(r'(\d+):(\d{2}):(\d{2})\.(\d{2})')
    
    @classmethod
    def parse(cls, content: str, warnings: Optional[List[str]] = None) -> SubtitleDocument:
        """Parse ASS/SSA content into a SubtitleDocument.

        If ``warnings`` (a list) is provided, sanitization notes (e.g. invalid
        or clamped style values) are appended to it so callers can surface them
        to the user.
        """
        # Drop a leading UTF-8 BOM if a caller passed raw text, so the first
        # '[Script Info]' section header is detected correctly.
        if content and content[0] == '\ufeff':
            content = content[1:]
        content = content.replace('\r\n', '\n').replace('\r', '\n')
        lines = content.split('\n')
        
        # Detect format (ASS or SSA)
        format_type = SubtitleFormat.ASS
        for line in lines[:10]:
            if 'ScriptType:' in line:
                stype = line.split(':', 1)[1].strip()
                if stype == 'v4.00':
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
            
            if not line:
                # Empty line
                continue

            if line.startswith(';'):
                # Comment line; preserve [Script Info] comments on re-save.
                if current_section == '[script info]':
                    document.script_info_comments.append(line)
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
                    style = cls._parse_style(line, style_format, warnings)
                    if style:
                        document.styles.append(style)
            
            elif current_section == '[events]':
                if line.startswith('Format:'):
                    event_format = [f.strip() for f in line[7:].split(',')]
                elif line.startswith('Dialogue:'):
                    entry = cls._parse_dialogue(line, event_format, len(document.entries) + 1, warnings)
                    if entry:
                        document.entries.append(entry)
        
        # Ensure at least one default style exists
        if not document.styles:
            document.styles.append(ASSStyle())

        # High-level diagnostics: file looks like ASS/SSA but has no subtitles.
        if not document.entries:
            looks_like_ass = any(
                line.strip().lower() in ('[script info]', '[v4+ styles]', '[v4 styles]')
                for line in lines
            )
            if looks_like_ass and warnings is not None:
                warnings.append("No [Events] section found — file has no subtitles")

        document.reindex()
        document.modified = False
        return document
    
    @classmethod
    def _parse_script_info(cls, line: str, document: SubtitleDocument):
        """Parse a line from the Script Info section."""
        if ':' in line:
            key, value = line.split(':', 1)
            key = key.strip()
            document.metadata[key] = value.strip()
            if key not in document.script_info_order:
                document.script_info_order.append(key)

    @classmethod
    def _parse_aegisub_garbage(cls, line: str, document: SubtitleDocument):
        """Parse a line from the [Aegisub Project Garbage] section."""
        if ':' in line:
            key, value = line.split(':', 1)
            document.aegisub_project_garbage[key.strip()] = value.strip()
    
    @classmethod
    def _parse_style(cls, line: str, format_list: List[str],
                     warnings: Optional[List[str]] = None) -> Optional[ASSStyle]:
        """Parse a Style line into a sanitized ASSStyle."""
        # Remove 'Style: ' prefix
        content = line[6:].strip()
        values = [v.strip() for v in content.split(',')]

        name = values[0] if values else 'Style'
        if len(values) < len(format_list):
            n = len(format_list) - len(values)
            if warnings is not None:
                warnings.append(
                    f"Style '{name}': missing {n} field(s) (commas?), padded with defaults"
                )
            # Pad trailing missing fields with empty strings so from_fields
            # falls back to its defaults instead of dropping the whole style.
            values = values + [''] * n

        # Collect raw values keyed by their format-field name (lower-cased),
        # then let ASSStyle.from_fields coerce + clamp them defensively.
        fields: Dict[str, str] = {}
        for i, field in enumerate(format_list):
            if i >= len(values):
                break
            fields[field.lower()] = values[i]

        try:
            return ASSStyle.from_fields(fields, warnings=warnings)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Failed to parse style line, skipping: %s (%s)", line, exc)
            return None
    
    @classmethod
    def _parse_dialogue(cls, line: str, format_list: List[str], index: int,
                        warnings: Optional[List[str]] = None) -> Optional[SubtitleEntry]:
        """Parse a Dialogue line."""
        # Remove 'Dialogue: ' prefix
        content = line[9:].strip()
        
        # Split carefully - text may contain commas
        # Format typically: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
        parts = content.split(',', len(format_list) - 1)

        if len(parts) < len(format_list):
            if warnings is not None:
                warnings.append(
                    f"Dialogue line has missing/truncated fields (missing commas?): {line[:60]!r}..."
                )
            # Pad trailing missing fields with empty strings so processing
            # continues; missing fields become defaults/empty.
            parts = parts + [''] * (len(format_list) - len(parts))
        
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

        # Detect malformed override blocks in the dialogue text.
        if has_unbalanced_braces(text):
            if warnings is not None:
                warnings.append(
                    f"Dialogue entry {index}: unbalanced {{ }} in override tags"
                )

        if start_time is None or end_time is None:
            if warnings is not None:
                warnings.append(
                    f"Dialogue line skipped (unparseable start or end time): {line[:60]!r}..."
                )
            logger.warning("Skipping ASS dialogue with missing start or end time: %s", line)
            return None

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

    @classmethod
    def _parse_timecode(cls, timecode_str: str) -> Optional[TimeCode]:
        """Parse an ASS timecode string; return None if it doesn't match."""
        match = cls.TIMECODE_PATTERN.match(timecode_str)
        if match:
            hours = int(match.group(1))
            minutes = int(match.group(2))
            seconds = int(match.group(3))
            centiseconds = int(match.group(4))
            milliseconds = centiseconds * 10

            return TimeCode(hours, minutes, seconds, milliseconds)
        return None
    
    @classmethod
    def serialize(cls, document: SubtitleDocument) -> str:
        """Serialize a SubtitleDocument to ASS format."""
        lines = []
        
        # [Script Info] section
        lines.append('[Script Info]')
        lines.append('; Script generated by Gsub')

        # Re-emit any original ';' comments (e.g. the Aegisub generator line)
        # so they aren't silently dropped on a re-save.
        for comment in document.script_info_comments:
            lines.append(comment)

        # Common Script Info keys with reasonable defaults. Values already
        # present in document.metadata take precedence.
        defaults = {
            'Title': 'Untitled',
            'ScriptType': 'v4.00+',
            'WrapStyle': '0',
            'ScaledBorderAndShadow': 'yes',
            'YCbCr Matrix': 'None',
        }

        merged = dict(defaults)
        merged.update(document.metadata or {})

        # Preserve the original [Script Info] key order; only then emit any
        # keys not seen in the source (defaults / newly added) deterministically.
        emitted = set()
        for key in document.script_info_order:
            if key in merged and key not in emitted:
                lines.append(f"{key}: {merged[key]}")
                emitted.add(key)

        for key in sorted(k for k in merged.keys() if k not in emitted):
            lines.append(f"{key}: {merged[key]}")

        lines.append('')

        # [Aegisub Project Garbage] section (optional)
        if getattr(document, 'aegisub_project_garbage', None):
            if document.aegisub_project_garbage:
                lines.append('[Aegisub Project Garbage]')
                # Preserve the original key order (dict keeps insertion order).
                for key in document.aegisub_project_garbage.keys():
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
        
        return '\n'.join(lines) + '\n'
