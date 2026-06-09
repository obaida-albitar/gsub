"""Pytest configuration and shared fixtures."""

import pytest
from subtitle_editor.models import (
    TimeCode, SubtitleEntry, SubtitleDocument, SubtitleFormat, ASSStyle
)


@pytest.fixture
def sample_timecode():
    """Create a sample timecode."""
    return TimeCode(hours=0, minutes=1, seconds=30, milliseconds=500)


@pytest.fixture
def sample_entry():
    """Create a sample subtitle entry."""
    return SubtitleEntry(
        index=1,
        start_time=TimeCode(0, 0, 0, 500),
        end_time=TimeCode(0, 0, 2, 0),
        text="Sample subtitle text"
    )


@pytest.fixture
def sample_srt_document():
    """Create a sample SRT document with multiple entries."""
    doc = SubtitleDocument(format=SubtitleFormat.SRT)
    doc.entries = [
        SubtitleEntry(1, TimeCode(0, 0, 0, 500), TimeCode(0, 0, 2, 0), "First subtitle"),
        SubtitleEntry(2, TimeCode(0, 0, 2, 500), TimeCode(0, 0, 5, 0), "Second subtitle"),
        SubtitleEntry(3, TimeCode(0, 0, 5, 500), TimeCode(0, 0, 8, 0), "Third subtitle"),
    ]
    return doc


@pytest.fixture
def sample_ass_document():
    """Create a sample ASS document with styles and entries."""
    doc = SubtitleDocument(format=SubtitleFormat.ASS)
    doc.metadata = {
        'Title': 'Test Subtitle',
        'ScriptType': 'v4.00+',
    }
    doc.styles = [
        ASSStyle(name="Default", fontsize=20, bold=False),
        ASSStyle(name="Title", fontsize=28, bold=True),
    ]
    doc.entries = [
        SubtitleEntry(1, TimeCode(0, 0, 0, 500), TimeCode(0, 0, 2, 0), "First subtitle", style="Default", layer=2, actor="Narrator", effect="fade"),
        SubtitleEntry(2, TimeCode(0, 0, 2, 500), TimeCode(0, 0, 5, 0), "Second subtitle", style="Title"),
    ]
    return doc


@pytest.fixture
def sample_ass_style():
    """Create a sample ASS style."""
    return ASSStyle(
        name="CustomStyle",
        fontname="Arial",
        fontsize=24,
        primary_color="&H00FFFFFF",
        bold=True,
        italic=False
    )


@pytest.fixture
def sample_srt_content():
    """Sample SRT file content."""
    return """1
00:00:00,500 --> 00:00:02,000
First subtitle

2
00:00:02,500 --> 00:00:05,000
Second subtitle
with multiple lines

3
00:00:05,500 --> 00:00:08,000
Third subtitle
"""


@pytest.fixture
def sample_ass_content():
    """Sample ASS file content."""
    return """[Script Info]
Title: Test Subtitle
ScriptType: v4.00+

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,20,&H00FFFFFF,&H00000000,&H00000000,&H00000000,0,0,0,0,100.0,100.0,0.0,0.0,1,2.0,0.0,2,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 2,0:00:00.50,0:00:02.00,Default,Narrator,0,0,0,fade,First subtitle
Dialogue: 0,0:00:02.50,0:00:05.00,Default,,,0,0,0,,Second subtitle
"""
