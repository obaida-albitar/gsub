"""
Subtitle data models.

This module defines the core data structures for representing subtitles.
"""

from dataclasses import dataclass, field
from typing import Optional, List
from enum import Enum


class SubtitleFormat(Enum):
    """Supported subtitle formats."""
    SRT = "srt"
    ASS = "ass"
    SSA = "ssa"


@dataclass
class TimeCode:
    """Represents a timecode with millisecond precision."""
    hours: int = 0
    minutes: int = 0
    seconds: int = 0
    milliseconds: int = 0
    
    @property
    def total_milliseconds(self) -> int:
        """Convert timecode to total milliseconds."""
        return (self.hours * 3600000 + 
                self.minutes * 60000 + 
                self.seconds * 1000 + 
                self.milliseconds)
    
    @classmethod
    def from_milliseconds(cls, ms: int) -> 'TimeCode':
        """Create a TimeCode from total milliseconds."""
        hours = ms // 3600000
        ms %= 3600000
        minutes = ms // 60000
        ms %= 60000
        seconds = ms // 1000
        milliseconds = ms % 1000
        return cls(hours, minutes, seconds, milliseconds)
    
    def __str__(self) -> str:
        """Format as HH:MM:SS,mmm (SRT format)."""
        return f"{self.hours:02d}:{self.minutes:02d}:{self.seconds:02d},{self.milliseconds:03d}"
    
    def to_ass_format(self) -> str:
        """Format as H:MM:SS.cc (ASS format, centiseconds)."""
        centiseconds = self.milliseconds // 10
        return f"{self.hours}:{self.minutes:02d}:{self.seconds:02d}.{centiseconds:02d}"


@dataclass
class ASSStyle:
    """ASS subtitle style definition."""
    name: str = "Default"
    fontname: str = "Arial"
    fontsize: int = 20
    primary_color: str = "&H00FFFFFF"  # White
    secondary_color: str = "&H00000000"  # Black
    outline_color: str = "&H00000000"   # Black
    back_color: str = "&H00000000"      # Black
    bold: bool = False
    italic: bool = False
    underline: bool = False
    strikeout: bool = False
    scale_x: float = 100.0
    scale_y: float = 100.0
    spacing: float = 0.0
    angle: float = 0.0
    border_style: int = 1
    outline: float = 2.0
    shadow: float = 0.0
    alignment: int = 2  # Bottom center
    margin_l: int = 10
    margin_r: int = 10
    margin_v: int = 10
    encoding: int = 1
    
    def to_ass_string(self) -> str:
        """Convert style to ASS format string."""
        bold_val = -1 if self.bold else 0
        italic_val = -1 if self.italic else 0
        underline_val = -1 if self.underline else 0
        strikeout_val = -1 if self.strikeout else 0
        
        return (f"Style: {self.name},{self.fontname},{self.fontsize},"
                f"{self.primary_color},{self.secondary_color},"
                f"{self.outline_color},{self.back_color},"
                f"{bold_val},{italic_val},{underline_val},{strikeout_val},"
                f"{self.scale_x},{self.scale_y},{self.spacing},{self.angle},"
                f"{self.border_style},{self.outline},{self.shadow},"
                f"{self.alignment},{self.margin_l},{self.margin_r},{self.margin_v},"
                f"{self.encoding}")


@dataclass
class SubtitleEntry:
    """Represents a single subtitle entry."""
    index: int
    start_time: TimeCode
    end_time: TimeCode
    text: str
    style: Optional[str] = None  # For ASS format
    
    def __post_init__(self):
        """Ensure text doesn't have leading/trailing whitespace lines."""
        self.text = self.text.strip()
    
    @property
    def duration_ms(self) -> int:
        """Get the duration of this subtitle in milliseconds."""
        return self.end_time.total_milliseconds - self.start_time.total_milliseconds
    
    def shift_time(self, offset_ms: int):
        """Shift both start and end times by the given offset in milliseconds."""
        new_start_ms = max(0, self.start_time.total_milliseconds + offset_ms)
        new_end_ms = max(0, self.end_time.total_milliseconds + offset_ms)
        
        self.start_time = TimeCode.from_milliseconds(new_start_ms)
        self.end_time = TimeCode.from_milliseconds(new_end_ms)


@dataclass
class SubtitleDocument:
    """Represents a complete subtitle document."""
    format: SubtitleFormat
    entries: List[SubtitleEntry] = field(default_factory=list)
    styles: List[ASSStyle] = field(default_factory=list)  # For ASS format
    metadata: dict = field(default_factory=dict)  # For ASS header info
    modified: bool = False
    file_path: Optional[str] = None
    
    def add_entry(self, entry: SubtitleEntry):
        """Add a subtitle entry to the document."""
        self.entries.append(entry)
        self.reindex()
        self.modified = True
    
    def remove_entry(self, index: int):
        """Remove a subtitle entry by index."""
        if 0 <= index < len(self.entries):
            self.entries.pop(index)
            self.reindex()
            self.modified = True
    
    def reindex(self):
        """Reindex all subtitle entries sequentially."""
        for i, entry in enumerate(self.entries, start=1):
            entry.index = i
    
    def sort_by_time(self):
        """Sort entries by start time."""
        self.entries.sort(key=lambda e: e.start_time.total_milliseconds)
        self.reindex()
        self.modified = True
    
    def get_style_by_name(self, name: str) -> Optional[ASSStyle]:
        """Get an ASS style by name."""
        for style in self.styles:
            if style.name == name:
                return style
        return None
