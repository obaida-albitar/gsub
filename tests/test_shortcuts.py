"""
Tests for the shortcuts table in subtitle_editor.shortcuts (the single
source of truth shared by accel registration and the shortcuts dialog)
and for the dialog built from it.

The table tests are pure data checks and run headless; the dialog tests
need GTK and are skipped when no display is available (same pattern as
test_ass_styles_dialog.py).
"""

import gettext

import pytest

from subtitle_editor.shortcuts import (
    SECTION_ORDER,
    SECTION_TIMELINE,
    SECTION_VIDEO,
    SHORTCUTS,
    accels_for_action,
    entries_for_section,
)

# Same translation setup as subtitle_editor/__init__.py installs app-wide.
_translation = gettext.translation("gsub", fallback=True)


class TestShortcutsTable:
    """Structural invariants of the shortcuts table."""

    @pytest.mark.unit
    def test_every_action_has_an_accel(self):
        """Entries bound to an action must declare at least one accel."""
        for shortcut in SHORTCUTS:
            if shortcut.action is not None:
                assert shortcut.accels, f"{shortcut.action} has no accels"

    @pytest.mark.unit
    def test_every_section_has_entries(self):
        """All dialog sections exist and are non-empty."""
        assert SECTION_ORDER
        for section in SECTION_ORDER:
            assert entries_for_section(section), f"section {section} is empty"

    @pytest.mark.unit
    def test_entries_belong_to_known_sections(self):
        """Every entry must reference a section the dialog shows."""
        for shortcut in SHORTCUTS:
            assert shortcut.section in SECTION_ORDER, shortcut.title

    @pytest.mark.unit
    def test_titles_are_unique(self):
        """The dialog search matches on titles, so titles must be unique."""
        titles = [shortcut.title for shortcut in SHORTCUTS]
        assert len(titles) == len(set(titles))

    @pytest.mark.unit
    def test_no_accel_conflicts_between_actions(self):
        """No accel string may be claimed by two different actions."""
        owners = {}
        for shortcut in SHORTCUTS:
            if shortcut.action is None:
                continue
            for accel in shortcut.accels:
                previous = owners.setdefault(accel, shortcut.action)
                assert previous == shortcut.action, (
                    f"accel {accel} claimed by both {previous} and {shortcut.action}"
                )

    @pytest.mark.unit
    def test_play_pause_bound_to_space(self):
        """Space toggles playback."""
        assert accels_for_action("win.play-pause") == ["space"]

    @pytest.mark.unit
    def test_toggle_video_moved_off_ctrl_v(self):
        """Toggle video uses Ctrl+Shift+V and no longer shadows Ctrl+V."""
        accels = accels_for_action("win.toggle-video")
        assert "<Ctrl><Shift>V" in accels
        assert "<Ctrl>V" not in accels

    @pytest.mark.unit
    def test_redo_has_ctrl_y_alias(self):
        """Redo keeps Ctrl+Shift+Z and adds Ctrl+Y."""
        accels = accels_for_action("win.redo")
        assert "<Ctrl><Shift>Z" in accels
        assert "<Ctrl>Y" in accels

    @pytest.mark.unit
    def test_widget_level_entries_are_display_only(self):
        """Subtitle zoom and search-match keys have no action and are never registered."""
        widget_shortcuts = [s for s in SHORTCUTS if s.action is None]
        titles = " ".join(s.title for s in widget_shortcuts)
        assert "Subtitle Size" in titles
        assert "Search Match" in titles
        # They still need display accels for the dialog...
        for shortcut in widget_shortcuts:
            assert shortcut.accels
        # ...but looking them up for registration yields nothing.
        assert accels_for_action(None) == []

    @pytest.mark.unit
    def test_gesture_entries_are_display_only(self):
        """Gesture rows document mouse interactions: no action, never registered."""
        gestures = [s for s in SHORTCUTS if s.gesture]
        assert gestures
        for shortcut in gestures:
            assert shortcut.action is None, shortcut.title
        assert accels_for_action(None) == []


class TestTimelineSection:
    """The Timeline section: keyboard entries moved from Video + gestures."""

    @pytest.mark.unit
    def test_timeline_sits_after_video_in_section_order(self):
        assert SECTION_ORDER.index(SECTION_TIMELINE) == SECTION_ORDER.index(SECTION_VIDEO) + 1

    @pytest.mark.unit
    def test_keyboard_entries_moved_from_video(self):
        timeline_actions = {s.action for s in entries_for_section(SECTION_TIMELINE)} - {None}
        assert {
            "win.seek-nudge-back", "win.seek-nudge-forward",
            "win.seek-nudge-back-large", "win.seek-nudge-forward-large",
            "win.frame-step", "win.frame-back-step",
            "win.seek-to-selection",
        } <= timeline_actions
        video_actions = {s.action for s in entries_for_section(SECTION_VIDEO)} - {None}
        assert not timeline_actions & video_actions

    @pytest.mark.unit
    def test_video_keeps_the_player_entries(self):
        video_actions = {s.action for s in entries_for_section(SECTION_VIDEO)}
        assert {"win.open-video", "win.play-pause", "win.toggle-video",
                "win.select-tracks"} <= video_actions

    @pytest.mark.unit
    def test_gesture_entries_present(self):
        gestures = {s.title: s for s in entries_for_section(SECTION_TIMELINE) if s.gesture}
        expected = {
            "Seek 1 s": "Scroll Wheel",
            "Zoom Timeline": "Ctrl + Scroll",
            "Pan Timeline": "Shift + Scroll; Middle or Right Drag",
            "Scrub (Drag)": "Left Drag",
            "Move Subtitle": "Ctrl + Drag on a subtitle region",
            "Resize Subtitle (Start/End)": "Drag the selected subtitle's edge handles",
            "Select Subtitle on Timeline": "Ctrl + Click",
        }
        assert gestures.keys() == expected.keys()
        for title, gesture in expected.items():
            assert gestures[title].gesture == gesture
            assert gestures[title].accels, f"{title} needs a display accel"



# --- GTK-gated dialog tests --------------------------------------------- #

try:
    from gi.repository import Adw, Gdk, Gtk
    from subtitle_editor.resources import register_resources
    register_resources()
    try:
        Gtk.init()
        Adw.init()
    except Exception:
        pass
    _HAS_DISPLAY = Gdk.Display.get_default() is not None
except Exception:  # pragma: no cover - environment without GTK
    _HAS_DISPLAY = False

pytestmark_gtk = pytest.mark.skipif(
    not _HAS_DISPLAY, reason="no display available for GTK widget tests"
)


@pytestmark_gtk
def test_all_accels_parse_as_gtk_accelerators():
    """Every accel in the table must parse (catches e.g. 'Space' vs 'space').

    Gesture-only entries (no accels) are skipped: their gesture text is
    free-form display copy, not accelerator syntax.
    """
    for shortcut in SHORTCUTS:
        if not shortcut.accels:
            continue
        for accel in shortcut.accels:
            ok, _keyval, _mods = Gtk.accelerator_parse(accel)
            assert ok, f"{accel!r} ({shortcut.title}) is not a valid GTK accelerator"


@pytestmark_gtk
def test_every_entry_constructs_as_a_shortcuts_item():
    """Both kinds of rows build into AdwShortcutsItem on an unmapped dialog.

    AdwShortcutsSection only accepts AdwShortcutsItem children, so gesture
    entries ride along as a subtitle next to their parseable accel.
    """
    from subtitle_editor.widgets.dialogs import build_shortcuts_dialog

    dialog = build_shortcuts_dialog()
    assert isinstance(dialog, Adw.ShortcutsDialog)

    for shortcut in SHORTCUTS:
        item = Adw.ShortcutsItem(title=shortcut.title)
        if shortcut.accels:
            item.set_accelerator(" ".join(shortcut.accels))
        if shortcut.gesture:
            item.set_subtitle(shortcut.gesture)
        assert item.get_title() == shortcut.title
        if shortcut.gesture:
            assert item.get_subtitle() == shortcut.gesture
        else:
            assert item.get_subtitle() == ""
    # A gesture-only entry (no accels) stays constructible without a keycap.
    item = Adw.ShortcutsItem(title="Pan", subtitle="Middle Drag")
    assert item.get_accelerator() == ""


@pytestmark_gtk
def test_shortcuts_dialog_covers_the_table():
    """The dialog builds from the table and shows every section and title.

    AdwShortcutsDialog constructs its child rows lazily on first map, so
    coverage is asserted through the same data path the dialog builder
    consumes (SECTION_ORDER + entries_for_section). Entries with and
    without a gesture are both covered by that path.
    """
    from subtitle_editor.widgets.dialogs import build_shortcuts_dialog

    dialog = build_shortcuts_dialog()
    assert isinstance(dialog, Adw.ShortcutsDialog)
    assert dialog.get_title() == _translation.gettext("Keyboard Shortcuts")

    covered = [s.title for section in SECTION_ORDER for s in entries_for_section(section)]
    assert sorted(covered) == sorted(s.title for s in SHORTCUTS)
    for section in SECTION_ORDER:
        assert entries_for_section(section), f"section {section} is empty"
    # Accel-only rows have no gesture text; gesture rows carry one and are
    # exactly the Timeline mouse-gesture entries.
    accel_only = [s for s in SHORTCUTS if s.gesture is None]
    gesture_rows = [s for s in SHORTCUTS if s.gesture is not None]
    assert accel_only and gesture_rows
    assert all(s.section == SECTION_TIMELINE for s in gesture_rows)
