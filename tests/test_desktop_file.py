"""Pure-logic tests for the desktop entry file.

Asserts the system-integration contract: gsub registers as a handler for the
common video container types (so "Open With" works from file managers) while
keeping the subtitle mime types, and accepts multiple file arguments.
"""

import configparser
from pathlib import Path

DESKTOP_FILE = Path(__file__).parent.parent / "data" / "app.gsub.desktop"

VIDEO_MIMES = [
    "video/mp4",
    "video/x-matroska",
    "video/webm",
    "video/x-msvideo",
    "video/quicktime",
    "video/x-flv",
    "video/ogg",
    "video/x-theora+ogg",
]

SUBTITLE_MIMES = [
    "application/x-subrip",
    "text/x-ass",
    "text/x-ssa",
]


def _desktop_section() -> configparser.SectionProxy:
    """Parse the desktop file; raw parser because Exec contains %F."""
    parser = configparser.RawConfigParser()
    parser.read(DESKTOP_FILE)
    return parser["Desktop Entry"]


def _mimetypes() -> set:
    return {m for m in _desktop_section()["MimeType"].split(";") if m}


def test_exec_accepts_file_arguments():
    assert "%F" in _desktop_section()["Exec"]


def test_mimetype_includes_video_types():
    mimes = _mimetypes()
    missing = [m for m in VIDEO_MIMES if m not in mimes]
    assert missing == []


def test_mimetype_keeps_subtitle_types():
    mimes = _mimetypes()
    missing = [m for m in SUBTITLE_MIMES if m not in mimes]
    assert missing == []


def test_entry_is_a_gui_application():
    section = _desktop_section()
    assert section["Type"] == "Application"
    assert section["Terminal"].lower() == "false"
