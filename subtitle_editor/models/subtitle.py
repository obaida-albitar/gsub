"""
Subtitle data models.

This module defines the core data structures for representing subtitles.
"""

from dataclasses import dataclass, field, replace as dc_replace
from typing import Optional, List, Dict, Any
from enum import Enum
import copy
import math


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

    # ------------------------------------------------------------------
    # Defensive coercion / sanitization
    #
    # ASS files in the wild (or hand-edited ones) sometimes contain invalid
    # or extreme values that make subtitles render wrong or even crash the
    # parser. These helpers coerce each field to a valid value and record a
    # human-readable note in `warnings` when a correction was made. Both the
    # ASS parser and the styles editor rely on this so behaviour is consistent.
    # ------------------------------------------------------------------

    @staticmethod
    def _coerce_int(raw, default, lo=None, hi=None, warnings=None, label=""):
        try:
            val = int(round(float(raw)))
        except (ValueError, TypeError):
            if warnings is not None and raw not in (None, ""):
                warnings.append(f"{label}: '{raw}' is not a valid integer, using {default}")
            return default
        if lo is not None and val < lo:
            if warnings is not None:
                warnings.append(f"{label}: {val} is below {lo}, clamped to {lo}")
            return lo
        if hi is not None and val > hi:
            if warnings is not None:
                warnings.append(f"{label}: {val} is above {hi}, clamped to {hi}")
            return hi
        return val

    @staticmethod
    def _coerce_float(raw, default, lo=None, hi=None, warnings=None, label=""):
        try:
            val = float(raw)
        except (ValueError, TypeError):
            if warnings is not None and raw not in (None, ""):
                warnings.append(f"{label}: '{raw}' is not a valid number, using {default}")
            return default
        if not math.isfinite(val):
            if warnings is not None:
                warnings.append(f"{label}: non-finite value, using {default}")
            return default
        if lo is not None and val < lo:
            if warnings is not None:
                warnings.append(f"{label}: {val} is below {lo}, clamped to {lo}")
            return lo
        if hi is not None and val > hi:
            if warnings is not None:
                warnings.append(f"{label}: {val} is above {hi}, clamped to {hi}")
            return hi
        return val

    @classmethod
    def from_fields(cls, fields: Dict[str, str], *, name_hint: str = "Style",
                    warnings: Optional[List[str]] = None) -> 'ASSStyle':
        """Build an ASSStyle from a mapping of lowercased field name -> raw string.

        Every value is coerced and clamped to a valid range; corrections are
        appended to ``warnings`` (a list of human-readable strings). This never
        raises on bad input and always returns a usable style.
        """
        raw = fields or {}
        label = lambda key: f"Style '{raw.get('name') or name_hint}': {key}"

        name = (raw.get("name") or "").strip() or name_hint
        fontname = (raw.get("fontname") or "").strip() or "Arial"

        style = cls()
        style.name = name
        style.fontname = fontname
        style.fontsize = cls._coerce_int(
            raw.get("fontsize"), 20, 1, 200, warnings, label("Font Size"))

        # Colours are passed through untouched; the editor degrades gracefully
        # on unparseable colour strings, so we don't risk silent data loss here.
        style.primary_color = (raw.get("primarycolour") or "&H00FFFFFF").strip()
        style.secondary_color = (raw.get("secondarycolour") or "&H00000000").strip()
        style.outline_color = (raw.get("outlinecolour") or "&H00000000").strip()
        style.back_color = (raw.get("backcolour") or "&H00000000").strip()

        # Boolean flags: ASS uses -1/0, but some editors use 1/0. Non-zero = on.
        style.bold = cls._coerce_int(raw.get("bold"), 0, warnings=warnings,
                                     label=label("Bold")) != 0
        style.italic = cls._coerce_int(raw.get("italic"), 0, warnings=warnings,
                                       label=label("Italic")) != 0
        style.underline = cls._coerce_int(raw.get("underline"), 0, warnings=warnings,
                                          label=label("Underline")) != 0
        style.strikeout = cls._coerce_int(raw.get("strikeout"), 0, warnings=warnings,
                                          label=label("StrikeOut")) != 0

        # Scales: must be strictly positive; reset to 100 if invalid/zero/negative.
        scale_x = cls._coerce_float(raw.get("scalex"), 100.0, warnings=warnings,
                                    label=label("ScaleX"))
        if not (0 < scale_x <= 1000):
            if warnings is not None:
                warnings.append(f"{label('ScaleX')}: {scale_x} out of range, reset to 100")
            scale_x = 100.0
        style.scale_x = scale_x

        scale_y = cls._coerce_float(raw.get("scaley"), 100.0, warnings=warnings,
                                    label=label("ScaleY"))
        if not (0 < scale_y <= 1000):
            if warnings is not None:
                warnings.append(f"{label('ScaleY')}: {scale_y} out of range, reset to 100")
            scale_y = 100.0
        style.scale_y = scale_y

        style.spacing = cls._coerce_float(
            raw.get("spacing"), 0.0, -100.0, 100.0, warnings, label("Spacing"))
        style.angle = cls._coerce_float(
            raw.get("angle"), 0.0, -360.0, 360.0, warnings, label("Angle"))

        # BorderStyle: only 1 (outline+shadow) and 3 (opaque box) are valid.
        border_style = cls._coerce_int(raw.get("borderstyle"), 1, warnings=warnings,
                                       label=label("BorderStyle"))
        if border_style not in (1, 3):
            if warnings is not None:
                warnings.append(f"{label('BorderStyle')}: {border_style} is invalid, reset to 1")
            border_style = 1
        style.border_style = border_style

        style.outline = cls._coerce_float(
            raw.get("outline"), 2.0, 0.0, 20.0, warnings, label("Outline"))
        style.shadow = cls._coerce_float(
            raw.get("shadow"), 0.0, 0.0, 20.0, warnings, label("Shadow"))

        # Alignment: ASS grid is 1-9.
        style.alignment = cls._coerce_int(
            raw.get("alignment"), 2, 1, 9, warnings, label("Alignment"))

        style.margin_l = cls._coerce_int(
            raw.get("marginl"), 10, 0, 9999, warnings, label("MarginL"))
        style.margin_r = cls._coerce_int(
            raw.get("marginr"), 10, 0, 9999, warnings, label("MarginR"))
        style.margin_v = cls._coerce_int(
            raw.get("marginv"), 10, 0, 9999, warnings, label("MarginV"))

        style.encoding = cls._coerce_int(
            raw.get("encoding"), 1, 0, 255, warnings, label("Encoding"))

        return style


@dataclass
class SubtitleEntry:
    """Represents a single subtitle entry."""
    index: int
    start_time: TimeCode
    end_time: TimeCode
    text: str
    style: Optional[str] = None  # For ASS format
    # Per-entry margin overrides (ASS format)
    margin_l: int = 0  # Left margin override (0 = use style default)
    margin_r: int = 0  # Right margin override (0 = use style default)
    margin_v: int = 0  # Vertical margin override (0 = use style default)
    layer: int = 0  # ASS layer number
    actor: str = ""  # ASS "Name" field (spec calls it "Actor")
    effect: str = ""  # ASS effect
    
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
    metadata: Dict[str, str] = field(default_factory=dict)  # [Script Info]
    aegisub_project_garbage: Dict[str, str] = field(default_factory=dict)  # [Aegisub Project Garbage]
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

    # --- ASS/SSA metadata helpers ---
    def set_metadata(self, key: str, value: str) -> None:
        """Set a metadata key/value (ASS/SSA Script Info).

        This marks the document modified.
        """
        if key is None:
            raise ValueError("metadata key must not be None")
        key = str(key).strip()
        if not key:
            raise ValueError("metadata key must not be empty")
        self.metadata[key] = "" if value is None else str(value)
        self.modified = True

    def remove_metadata(self, key: str) -> None:
        """Remove a metadata key if present."""
        if key in self.metadata:
            del self.metadata[key]
            self.modified = True

    # --- Aegisub Project Garbage helpers ---
    def set_aegisub_garbage(self, key: str, value: str) -> None:
        """Set a key/value in [Aegisub Project Garbage]."""
        if key is None:
            raise ValueError("aegisub key must not be None")
        key = str(key).strip()
        if not key:
            raise ValueError("aegisub key must not be empty")
        self.aegisub_project_garbage[key] = "" if value is None else str(value)
        self.modified = True

    def remove_aegisub_garbage(self, key: str) -> None:
        """Remove a key from [Aegisub Project Garbage] if present."""
        if key in self.aegisub_project_garbage:
            del self.aegisub_project_garbage[key]
            self.modified = True

    # --- ASS style helpers ---
    def upsert_style(self, style: ASSStyle) -> Optional[ASSStyle]:
        """Insert or update a style by name.

        Returns the previous style if replaced, else None.
        """
        if style is None:
            raise ValueError("style must not be None")
        if not style.name or not str(style.name).strip():
            raise ValueError("style.name must not be empty")

        for idx, existing in enumerate(self.styles):
            if existing.name == style.name:
                old = copy.deepcopy(existing)
                self.styles[idx] = copy.deepcopy(style)
                self.modified = True
                return old

        self.styles.append(copy.deepcopy(style))
        self.modified = True
        return None

    def rename_style(self, old_name: str, new_name: str) -> None:
        """Rename a style and update dialogue entries referencing it."""
        old_name = (old_name or "").strip()
        new_name = (new_name or "").strip()
        if not old_name or not new_name:
            raise ValueError("style names must not be empty")
        if old_name == new_name:
            return

        if self.get_style_by_name(new_name) is not None:
            raise ValueError(f"style '{new_name}' already exists")

        style = self.get_style_by_name(old_name)
        if style is None:
            raise KeyError(f"style '{old_name}' not found")

        style.name = new_name
        for entry in self.entries:
            if entry.style == old_name:
                entry.style = new_name
        self.modified = True

    def remove_style(self, name: str, fallback: str = "Default") -> Optional[ASSStyle]:
        """Remove a style by name.

        Any dialogue entries using the removed style are switched to `fallback`.
        Returns the removed style, or None if not found.
        """
        name = (name or "").strip()
        if not name:
            raise ValueError("style name must not be empty")

        removed = None
        for idx, style in enumerate(list(self.styles)):
            if style.name == name:
                removed = self.styles.pop(idx)
                break

        if removed is None:
            return None

        # Ensure fallback exists
        if fallback and self.get_style_by_name(fallback) is None:
            self.styles.append(ASSStyle(name=fallback))

        for entry in self.entries:
            if entry.style == name:
                entry.style = fallback

        # Always keep at least one style
        if not self.styles:
            self.styles.append(ASSStyle())

        self.modified = True
        return copy.deepcopy(removed)
