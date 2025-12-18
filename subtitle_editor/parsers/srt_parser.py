"""
SRT (SubRip) subtitle format parser.

SRT format structure:
1
00:00:20,000 --> 00:00:24,400
This is the first subtitle

2
00:00:24,600 --> 00:00:27,800
This is the second subtitle
"""

import re
from typing import List
from subtitle_editor.models import SubtitleEntry, SubtitleDocument, SubtitleFormat, TimeCode


class SRTParser:
    """Parser for SRT subtitle format."""
    
    # Regex pattern for SRT timecode: HH:MM:SS,mmm --> HH:MM:SS,mmm
    TIMECODE_PATTERN = re.compile(
        r'(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2}),(\d{3})'
    )
    
    @classmethod
    def parse(cls, content: str) -> SubtitleDocument:
        """Parse SRT content into a SubtitleDocument."""
        document = SubtitleDocument(format=SubtitleFormat.SRT)
        
        # Split into subtitle blocks (separated by blank lines)
        blocks = re.split(r'\n\s*\n', content.strip())
        
        for block in blocks:
            if not block.strip():
                continue
                
            lines = block.strip().split('\n')
            if len(lines) < 3:
                continue  # Invalid block
            
            try:
                # First line: index
                index = int(lines[0].strip())
                
                # Second line: timecodes
                match = cls.TIMECODE_PATTERN.match(lines[1])
                if not match:
                    continue
                
                start_time = TimeCode(
                    hours=int(match.group(1)),
                    minutes=int(match.group(2)),
                    seconds=int(match.group(3)),
                    milliseconds=int(match.group(4))
                )
                
                end_time = TimeCode(
                    hours=int(match.group(5)),
                    minutes=int(match.group(6)),
                    seconds=int(match.group(7)),
                    milliseconds=int(match.group(8))
                )
                
                # Remaining lines: text
                text = '\n'.join(lines[2:])
                
                entry = SubtitleEntry(
                    index=index,
                    start_time=start_time,
                    end_time=end_time,
                    text=text
                )
                document.entries.append(entry)
                
            except (ValueError, IndexError):
                continue  # Skip invalid entries
        
        document.reindex()
        document.modified = False
        return document
    
    @classmethod
    def serialize(cls, document: SubtitleDocument) -> str:
        """Serialize a SubtitleDocument to SRT format."""
        lines = []
        
        for entry in document.entries:
            # Index
            lines.append(str(entry.index))
            
            # Timecodes
            timecode_line = f"{entry.start_time} --> {entry.end_time}"
            lines.append(timecode_line)
            
            # Text
            lines.append(entry.text)
            
            # Blank line separator
            lines.append('')
        
        return '\n'.join(lines)
