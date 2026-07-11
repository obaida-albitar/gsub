"""Small GTK-free helpers shared by the UI layer."""

from typing import Iterable, List


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
