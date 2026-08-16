"""
Single source of truth for keyboard shortcuts.

This table drives both accelerator registration (the main window calls
set_accels_for_action with these) and the shortcuts dialog (dialogs.py
builds its sections from it), so the help overlay can never drift away
from the actually registered key bindings.

Accels use GTK accelerator syntax (see gtk_accelerator_parse); key names
must match gdk_keyval_name exactly, e.g. lowercase "space" and "plus"
rather than "Space" and "+". Entries with action=None describe keys
handled by widget key controllers (video player zoom, search matches);
they are shown in the dialog but never registered as action accels.

The module deliberately imports no GTK so tests can use it headlessly.
"""

from dataclasses import dataclass

# Dialog sections, in display order.
SECTION_FILE = "File"
SECTION_EDITING = "Editing"
SECTION_VIDEO = "Video"
SECTION_NAVIGATION = "Navigation"

SECTION_ORDER = (SECTION_FILE, SECTION_EDITING, SECTION_VIDEO, SECTION_NAVIGATION)


@dataclass(frozen=True)
class Shortcut:
    """A single shortcut: one row in the shortcuts dialog.

    Attributes:
        action: Qualified action name (e.g. "win.undo"), or None for
            widget-level keys that are only displayed in the dialog.
        accels: Accel strings in GTK syntax; the first one is the primary.
        title: Human-readable label shown in the shortcuts dialog.
        section: Dialog section (one of the SECTION_* constants).
    """

    action: str | None
    accels: tuple
    title: str
    section: str


SHORTCUTS = (
    # File
    Shortcut("win.new", ("<Ctrl>N",), "New", SECTION_FILE),
    Shortcut("win.open", ("<Ctrl>O",), "Open…", SECTION_FILE),
    Shortcut("win.save", ("<Ctrl>S",), "Save", SECTION_FILE),
    Shortcut("win.save-as", ("<Ctrl><Shift>S",), "Save As…", SECTION_FILE),
    # Editing
    Shortcut("win.undo", ("<Ctrl>Z",), "Undo", SECTION_EDITING),
    Shortcut("win.redo", ("<Ctrl><Shift>Z", "<Ctrl>Y"), "Redo", SECTION_EDITING),
    Shortcut("win.add-entry", ("<Ctrl><Shift>N",), "Add Subtitle", SECTION_EDITING),
    Shortcut("win.remove-entry", ("Delete",), "Remove Subtitle", SECTION_EDITING),
    Shortcut("win.duplicate-entry", ("<Ctrl>D",), "Duplicate Subtitle", SECTION_EDITING),
    Shortcut("win.move-up", ("<Ctrl>Up",), "Move Up", SECTION_EDITING),
    Shortcut("win.move-down", ("<Ctrl>Down",), "Move Down", SECTION_EDITING),
    # Video
    Shortcut("win.open-video", ("<Ctrl><Shift>O",), "Open Video…", SECTION_VIDEO),
    Shortcut("win.play-pause", ("space",), "Play/Pause", SECTION_VIDEO),
    Shortcut("win.toggle-video", ("<Ctrl><Shift>V",), "Toggle Video Player", SECTION_VIDEO),
    Shortcut("win.select-tracks", ("<Ctrl><Shift>T",), "Select Audio/Subtitle Tracks…", SECTION_VIDEO),
    # Handled by the video player's key controller, not an action accel.
    Shortcut(None, ("plus", "equal", "minus", "0"),
             "Subtitle Size: Increase / Decrease / Reset", SECTION_VIDEO),
    # Navigation
    Shortcut("win.home", ("<Alt>Home",), "Home", SECTION_NAVIGATION),
    Shortcut("win.find", ("<Ctrl>F",), "Find in Subtitles", SECTION_NAVIGATION),
    # Handled by the search entry's key controller, not an action accel.
    Shortcut(None, ("Return", "<Shift>Return"),
             "Next / Previous Search Match", SECTION_NAVIGATION),
    Shortcut("win.show-help-overlay", ("<Ctrl>question",), "Keyboard Shortcuts", SECTION_NAVIGATION),
)


def accels_for_action(action):
    """Return the accels registered for an action, or [] if it has none.

    Args:
        action: Qualified action name, e.g. "win.undo". Widget-level
            entries (action=None) are never registrable.
    """
    if action is None:
        return []
    for shortcut in SHORTCUTS:
        if shortcut.action == action:
            return list(shortcut.accels)
    return []


def entries_for_section(section):
    """Return the shortcuts shown in one dialog section, in table order.

    Args:
        section: One of the SECTION_* constants.
    """
    return [shortcut for shortcut in SHORTCUTS if shortcut.section == section]
