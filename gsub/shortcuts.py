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

Entries flagged ``window_key`` (space, period, comma) are plain typable
keys that must not become application accels at all: accels win over text
input, so registering "space" would steal Space from the text editor and
entries (and period/comma likewise). The window dispatches them itself
from a bubble-phase key controller, which only runs after the focused
widget declined the key — so text widgets consume them for typing while
the rest of the window still gets the shortcut (see
window._setup_window_key_controller). Their accels stay in the table for
display in the dialog; accels_for_action returns [] for them so no accel
is ever registered.

Mouse gestures (timeline scrolling/dragging) have no GTK accelerator
syntax. Their entries carry the closest parseable approximation in
``accels`` — wheel events parse natively ("ScrollUp", "<Ctrl>ScrollUp"),
pointer-button ones via the "Pointer_Button1" keysym — plus a free-form
``gesture`` text ("Ctrl + Drag") the dialog shows as the row subtitle.
An entry may have accels only, a gesture only, or both.

The module deliberately imports no GTK so tests can use it headlessly.
"""

from dataclasses import dataclass

# Dialog sections, in display order.
SECTION_FILE = "File"
SECTION_EDITING = "Editing"
SECTION_VIDEO = "Video"
SECTION_TIMELINE = "Timeline"
SECTION_NAVIGATION = "Navigation"

SECTION_ORDER = (SECTION_FILE, SECTION_EDITING, SECTION_VIDEO,
                 SECTION_TIMELINE, SECTION_NAVIGATION)


@dataclass(frozen=True)
class Shortcut:
    """A single shortcut: one row in the shortcuts dialog.

    Attributes:
        action: Qualified action name (e.g. "win.undo"), or None for
            widget-level keys that are only displayed in the dialog.
        accels: Accel strings in GTK syntax; the first one is the primary.
        title: Human-readable label shown in the shortcuts dialog.
        section: Dialog section (one of the SECTION_* constants).
        gesture: Free display text for mouse gestures ("Ctrl + Drag"),
            rendered as the row subtitle; None for pure key shortcuts.
        window_key: True for keys the window dispatches itself from a
            bubble-phase key controller instead of an application accel
            (plain typable keys like space that would otherwise steal text
            input). Never registered as an accel; the accels stay for the
            dialog display.
    """

    action: str | None
    accels: tuple
    title: str
    section: str
    gesture: str | None = None
    window_key: bool = False


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
    # Window key: as a plain accel, space would win over text input and
    # steal typing in the subtitle text editor; see the module docstring.
    Shortcut("win.play-pause", ("space",), "Play/Pause", SECTION_VIDEO,
             window_key=True),
    Shortcut("win.toggle-video", ("<Ctrl><Shift>V",), "Toggle Video Player", SECTION_VIDEO),
    Shortcut("win.select-tracks", ("<Ctrl><Shift>T",), "Select Audio/Subtitle Tracks…", SECTION_VIDEO),
    # Handled by the video player's key controller, not an action accel.
    Shortcut(None, ("plus", "equal", "minus", "0"),
             "Subtitle Size: Increase / Decrease / Reset", SECTION_VIDEO),
    # Timeline: precise navigation on the custom timeline. The arrow-key
    # accels are keybinding-class and coexist fine with text editing, but
    # the plain typable frame-step keys (period/comma) are window keys —
    # otherwise typing "." or "," in the text editor would step the video.
    Shortcut("win.seek-nudge-back", ("Left",), "Nudge Back 0.1 s", SECTION_TIMELINE),
    Shortcut("win.seek-nudge-forward", ("Right",), "Nudge Forward 0.1 s", SECTION_TIMELINE),
    Shortcut("win.seek-nudge-back-large", ("<Shift>Left",), "Jump Back 5 s", SECTION_TIMELINE),
    Shortcut("win.seek-nudge-forward-large", ("<Shift>Right",), "Jump Forward 5 s", SECTION_TIMELINE),
    Shortcut("win.frame-step", ("period",), "Step One Frame Forward", SECTION_TIMELINE,
             window_key=True),
    Shortcut("win.frame-back-step", ("comma",), "Step One Frame Back", SECTION_TIMELINE,
             window_key=True),
    Shortcut("win.seek-to-selection", ("<Ctrl>J",), "Play from Selected Subtitle", SECTION_TIMELINE),
    # Mouse gestures on the timeline widget, documented in the dialog only
    # (see the module docstring about their accel approximations).
    Shortcut(None, ("ScrollUp", "ScrollDown"), "Seek 1 s", SECTION_TIMELINE,
             "Scroll Wheel"),
    Shortcut(None, ("<Ctrl>ScrollUp", "<Ctrl>ScrollDown"), "Zoom Timeline",
             SECTION_TIMELINE, "Ctrl + Scroll"),
    Shortcut(None, ("<Shift>ScrollUp", "<Shift>ScrollDown"), "Pan Timeline",
             SECTION_TIMELINE, "Shift + Scroll; Middle or Right Drag"),
    Shortcut(None, ("Pointer_Button1",), "Scrub (Drag)", SECTION_TIMELINE,
             "Left Drag"),
    Shortcut(None, ("<Ctrl>Pointer_Button1",), "Move Subtitle", SECTION_TIMELINE,
             "Ctrl + Drag on a subtitle region"),
    Shortcut(None, ("Pointer_Button1",), "Resize Subtitle (Start/End)",
             SECTION_TIMELINE, "Drag the selected subtitle's edge handles"),
    Shortcut(None, ("<Ctrl>Pointer_Button1",), "Select Subtitle on Timeline",
             SECTION_TIMELINE, "Ctrl + Click"),
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
            entries (action=None) and window-key entries (handled by the
            window's key controller, not accels) are never registrable.
    """
    if action is None:
        return []
    for shortcut in SHORTCUTS:
        if shortcut.action == action:
            if shortcut.window_key:
                return []
            return list(shortcut.accels)
    return []


def window_key_entries():
    """Return the entries the window dispatches from its key controller.

    These are the keys that must not be application accels because accels
    win over text input for plain typable keys (see the module docstring).
    The window parses their accels with gtk_accelerator_parse to build its
    (keyval, modifiers) dispatch table.
    """
    return [shortcut for shortcut in SHORTCUTS if shortcut.window_key]


def entries_for_section(section):
    """Return the shortcuts shown in one dialog section, in table order.

    Args:
        section: One of the SECTION_* constants.
    """
    return [shortcut for shortcut in SHORTCUTS if shortcut.section == section]
