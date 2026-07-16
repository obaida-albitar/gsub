"""Small GTK-free helpers shared by the UI layer."""

from typing import Iterable, List, Optional, Tuple


def is_font_installed(name: str, installed: Iterable[str]) -> bool:
    """Return True if ``name`` is among the installed font family names."""
    if not name:
        return False
    return name in set(installed)


def merge_font_families(
    installed: Iterable[str], style_fonts: Iterable[str]
) -> List[str]:
    """Build the font dropdown list.

    The dropdown shows fonts that are actually installed on the system first,
    then any style font name that is *not* installed. This guarantees a style
    keeps referencing its real font (e.g. "Sansation") even when that font is
    missing from the user's machine, instead of silently falling back to the
    first installed font and corrupting the file on save.
    """
    installed_sorted = sorted(installed)
    installed_set = set(installed_sorted)
    extra = sorted(f for f in style_fonts if f and f not in installed_set)
    return installed_sorted + extra


def parse_ass_color(s: str) -> Optional[Tuple[int, int, int, int]]:
    """Parse an ASS color string to (r, g, b, a) with a = transparency 0..255.

    Accepts '&HBBGGRR' or '&HAABBGGRR' (ASS byte order: BGR, alpha is
    TRANSPARENCY, 00 = opaque, FF = invisible). Also tolerate a stray trailing
    '&'. Return None if the string is not a valid ASS color.
    """
    if not s:
        return None
    t = s.strip().upper()
    if not t.startswith("&H"):
        return None
    t = t[2:]
    if t.endswith("&"):
        t = t[:-1]
    if len(t) < 6 or len(t) > 8:
        return None
    if any(c not in "0123456789ABCDEF" for c in t):
        return None
    bbggrr = t[-6:]
    bb = int(bbggrr[0:2], 16)
    gg = int(bbggrr[2:4], 16)
    rr = int(bbggrr[4:6], 16)
    if len(t) == 6:
        aa = 0
    else:
        aa = int(t[:-6], 16)
    return (rr, gg, bb, aa)


def is_valid_ass_color(s: str) -> bool:
    """True if s parses as a valid ASS color via parse_ass_color."""
    return parse_ass_color(s) is not None


def format_ass_color(r: int, g: int, b: int, a: int) -> str:
    """Return an '&HAABBGGRR' string (clamp each channel to 0..255, a is
    transparency 0..255)."""
    r = max(0, min(255, int(r)))
    g = max(0, min(255, int(g)))
    b = max(0, min(255, int(b)))
    a = max(0, min(255, int(a)))
    return "&H{:02X}{:02X}{:02X}{:02X}".format(a, b, g, r)
