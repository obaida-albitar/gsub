"""
Tests for the semantic style input widgets (alignment grid, choice tables).

The choice-table helpers are pure and always run. The AlignmentGrid tests
need a display (GTK cannot construct widgets headless); they are skipped
automatically when no ``Gdk.Display`` is available, like the other GTK
widget tests. The gresource bundle must be built (``make build-resources``)
because importing the widgets package loads the template classes.
"""

import pytest

from gsub.resources import register_resources

try:
    register_resources()
except Exception:  # pragma: no cover - unbuilt resources
    pass

# Imported after register_resources(): the widgets package __init__ loads
# template classes, which validate their resource paths at import time.
from gsub.widgets.style_widgets import (  # noqa: E402
    BORDER_STYLE_CHOICES,
    ENCODING_CHOICES,
    AlignmentGrid,
    border_style_label,
    encoding_choices_with,
    encoding_label,
)

try:
    from gi.repository import Adw, Gdk, Gtk
    try:
        Gtk.init()
        Adw.init()
    except Exception:
        pass
    _HAS_DISPLAY = Gdk.Display.get_default() is not None
except Exception:  # pragma: no cover - environment without GTK
    _HAS_DISPLAY = False

gtkmark = pytest.mark.skipif(
    not _HAS_DISPLAY, reason="no display available for GTK widget tests"
)


# --- Choice tables (pure) ---------------------------------------------------

def test_border_style_labels_known_values():
    assert BORDER_STYLE_CHOICES == ((1, "Outline + Shadow"), (3, "Opaque Box"))
    assert border_style_label(1) == "Outline + Shadow"
    assert border_style_label(3) == "Opaque Box"


def test_border_style_label_custom_fallback():
    assert border_style_label(2) == "2 (custom)"
    assert border_style_label(0) == "0 (custom)"
    assert border_style_label(-1) == "-1 (custom)"


def test_encoding_labels_known_values():
    assert encoding_label(0) == "ANSI (default)"
    assert encoding_label(1) == "Default"
    assert encoding_label(4) == "Shift JIS"
    assert encoding_label(178) == "Arabic (Windows)"
    assert encoding_label(255) == "OEM DOS (Windows)"


def test_encoding_label_custom_fallback():
    assert encoding_label(74) == "74 (custom)"
    assert encoding_label(256) == "256 (custom)"


def test_encoding_choices_with_keeps_known_value_untouched():
    assert encoding_choices_with(1) == ENCODING_CHOICES
    assert encoding_choices_with(178) == ENCODING_CHOICES


def test_encoding_choices_with_appends_custom_only_when_missing():
    with_custom = encoding_choices_with(74)
    assert with_custom == ENCODING_CHOICES + ((74, "74 (custom)"),)
    # Standard table order is preserved; the custom entry comes last.
    assert with_custom[:len(ENCODING_CHOICES)] == ENCODING_CHOICES
    assert with_custom[-1] == (74, "74 (custom)")


# --- AlignmentGrid (GTK) ------------------------------------------------------

@gtkmark
def test_alignment_grid_defaults_to_bottom_center():
    grid = AlignmentGrid()
    assert grid.get_value() == 2  # ASSStyle default


@gtkmark
def test_alignment_grid_round_trips_all_values():
    grid = AlignmentGrid()
    for value in range(1, 10):
        grid.set_value(value)
        assert grid.get_value() == value


@gtkmark
def test_alignment_grid_uses_numpad_layout():
    grid = AlignmentGrid()

    def value_at(column, row):
        child = grid.get_child_at(column, row)
        if isinstance(child, tuple):  # some bindings return a 1-tuple
            child = child[0]
        return int(child.get_label())

    assert [value_at(c, 0) for c in range(3)] == [7, 8, 9]  # top row
    assert [value_at(c, 1) for c in range(3)] == [4, 5, 6]  # middle row
    assert [value_at(c, 2) for c in range(3)] == [1, 2, 3]  # bottom row


@gtkmark
def test_alignment_grid_emits_value_changed_on_selection():
    grid = AlignmentGrid()
    emitted = []
    grid.connect('value-changed', lambda g, v: emitted.append(v))

    grid.set_value(7)
    assert emitted == [7]

    grid.set_value(7)  # unchanged value: no further emission
    assert emitted == [7]


@gtkmark
def test_alignment_grid_button_click_selects_value():
    grid = AlignmentGrid()
    emitted = []
    grid.connect('value-changed', lambda g, v: emitted.append(v))

    grid._buttons[9].set_active(True)  # simulates clicking top-right
    assert grid.get_value() == 9
    assert emitted == [9]


@gtkmark
def test_alignment_grid_keeps_exactly_one_button_active():
    grid = AlignmentGrid()
    for value in range(1, 10):
        grid.set_value(value)
        active = [v for v, button in grid._buttons.items() if button.get_active()]
        assert active == [value]

    # Toggling the active button off is refused: one button must stay on.
    grid._buttons[grid.get_value()].set_active(False)
    active = [v for v, button in grid._buttons.items() if button.get_active()]
    assert active == [grid.get_value()]


@gtkmark
def test_alignment_grid_out_of_range_is_noop():
    grid = AlignmentGrid()
    grid.set_value(3)
    for bad in (0, 10, -4, 99):
        grid.set_value(bad)
    assert grid.get_value() == 3
    assert grid._buttons[3].get_active() is True


@gtkmark
def test_alignment_grid_buttons_have_position_tooltips():
    grid = AlignmentGrid()
    assert grid._buttons[1].get_tooltip_text() == "Bottom left (1)"
    assert grid._buttons[5].get_tooltip_text() == "Middle center (5)"
    assert grid._buttons[9].get_tooltip_text() == "Top right (9)"
