"""
Semantic input widgets and choice tables for enumerative ASS style fields.

Alignment, BorderStyle and Encoding are plain numbers in the ASS format
(a 1-9 numpad grid, 1/3, and 0-255 charset IDs). The widgets here replace
bare number spinners with inputs users can understand, while still exchanging
plain ints with the ASSStyle fields:

- :class:`AlignmentGrid` — 3x3 numpad toggle grid for Alignment,
- :class:`ChoiceRow` — value-oriented wrapper around an ``Adw.ComboRow``
  populated from a ``(value, label)`` choices table,
- the ``BORDER_STYLE_CHOICES`` / ``ENCODING_CHOICES`` tables and their label
  helpers, shared by the styles dialog and the batch style editor.
"""

import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Adw, GObject, Gtk  # noqa: E402


# --- Choice tables (pure data; no GTK calls) --------------------------------

BORDER_STYLE_CHOICES = ((1, "Outline + Shadow"), (3, "Opaque Box"))

# The standard SSA/ASS Encoding field: a Windows charset ID, not a text
# encoding. 0 and the 128+ range differ subtly (e.g. 4 vs 128 "Shift JIS"),
# so both spellings are listed.
ENCODING_CHOICES = (
    (0, "ANSI (default)"),
    (1, "Default"),
    (2, "Symbol"),
    (3, "Mac"),
    (4, "Shift JIS"),
    (5, "Hangul"),
    (6, "Johab"),
    (7, "GB2312 (Simplified Chinese)"),
    (8, "Chinese BIG5 (Traditional Chinese)"),
    (9, "Greek"),
    (10, "Turkish"),
    (11, "Vietnamese"),
    (12, "Hebrew"),
    (13, "Arabic"),
    (14, "Baltic"),
    (15, "Russian"),
    (16, "Thai"),
    (17, "East European"),
    (18, "OEM DOS"),
    (128, "Shift JIS (Windows)"),
    (129, "Hangul (Windows)"),
    (130, "Johab (Windows)"),
    (134, "GB2312 (Windows)"),
    (136, "Chinese BIG5 (Windows)"),
    (161, "Greek (Windows)"),
    (162, "Turkish (Windows)"),
    (163, "Vietnamese (Windows)"),
    (177, "Hebrew (Windows)"),
    (178, "Arabic (Windows)"),
    (186, "Baltic (Windows)"),
    (204, "Russian (Windows)"),
    (222, "Thai (Windows)"),
    (238, "East European (Windows)"),
    (255, "OEM DOS (Windows)"),
)


def _custom_label(value) -> str:
    """Label for a choice value that is not in any standard table."""
    return f"{value} (custom)"


def _choices_with(choices, value) -> tuple:
    """``choices`` plus ``value`` as a custom entry when it is missing.

    Used to populate dropdowns so any stored value stays representable
    (and round-trips unchanged) instead of being silently coerced.
    """
    choices = tuple(choices)
    if any(entry_value == value for entry_value, _label in choices):
        return choices
    return choices + ((value, _custom_label(value)),)


def border_style_label(value) -> str:
    """Human-readable BorderStyle name (custom fallback for unknown values)."""
    return next((label for entry_value, label in BORDER_STYLE_CHOICES
                 if entry_value == value), _custom_label(value))


def encoding_label(value) -> str:
    """Human-readable Encoding charset name (custom fallback otherwise)."""
    return next((label for entry_value, label in ENCODING_CHOICES
                 if entry_value == value), _custom_label(value))


def encoding_choices_with(value) -> tuple:
    """:data:`ENCODING_CHOICES` plus ``value`` as a custom entry when missing."""
    return _choices_with(ENCODING_CHOICES, value)


# --- Alignment grid -----------------------------------------------------------

# Tooltip per alignment value: ASS positions the subtitle in the video frame.
_ALIGNMENT_TOOLTIPS = {
    1: "Bottom left (1)",
    2: "Bottom center (2)",
    3: "Bottom right (3)",
    4: "Middle left (4)",
    5: "Middle center (5)",
    6: "Middle right (6)",
    7: "Top left (7)",
    8: "Top center (8)",
    9: "Top right (9)",
}


class AlignmentGrid(Gtk.Grid):
    """ASS Alignment picker: a 3x3 toggle-button grid in numpad layout.

    7 8 9 are the top row, 1 2 3 the bottom row (the ASS convention:
    1 = bottom left, 9 = top right, 5 = center). Exactly one button is
    active at any time. Built programmatically and sized compactly so it
    fits as the suffix of an ``Adw.ActionRow``.
    """

    __gtype_name__ = 'GsubAlignmentGrid'

    __gsignals__ = {
        'value-changed': (GObject.SignalFlags.RUN_FIRST, None, (int,)),
    }

    def __init__(self):
        super().__init__()

        self._value = 2  # ASSStyle default: bottom center
        self._updating = False

        # Equal-size buttons keep the grid compact and square-ish.
        size_group = Gtk.SizeGroup(mode=Gtk.SizeGroupMode.BOTH)
        self._buttons = {}
        for value in range(1, 10):
            button = Gtk.ToggleButton(label=str(value))
            button.set_tooltip_text(_ALIGNMENT_TOOLTIPS[value])
            row = 2 - (value - 1) // 3  # 1-3 bottom, 7-9 top (numpad layout)
            column = (value - 1) % 3
            self.attach(button, column, row, 1, 1)
            size_group.add_widget(button)
            button.connect('toggled', self._on_button_toggled, value)
            self._buttons[value] = button

        self._select(self._value)

    def get_value(self) -> int:
        """Currently selected alignment (1-9)."""
        return self._value

    def set_value(self, value) -> None:
        """Select ``value`` (1-9); any other value is a no-op."""
        try:
            value = int(value)
        except (TypeError, ValueError):
            return
        if value not in self._buttons:
            return
        self._select(value)

    def _select(self, value: int) -> None:
        """Make ``value`` the active button, emitting when it changed."""
        changed = value != self._value
        self._value = value
        self._updating = True
        try:
            for button_value, button in self._buttons.items():
                button.set_active(button_value == value)
        finally:
            self._updating = False
        if changed:
            self.emit('value-changed', value)

    def _on_button_toggled(self, button, value):
        if self._updating:
            return
        if button.get_active():
            self._select(value)
        elif value == self._value:
            # The active button was toggled off: turn it back on so exactly
            # one button always stays active.
            self._updating = True
            try:
                button.set_active(True)
            finally:
                self._updating = False


# --- Choice combo helper --------------------------------------------------------

class ChoiceRow:
    """Value-oriented controller for an ``Adw.ComboRow`` over a choices table.

    The row shows the labels of a ``(value, label)`` table in a
    ``Gtk.StringList``; this helper keeps the parallel value list so callers
    read and write the semantic value instead of model indices. ``set_value``
    appends a "(custom)" entry for values missing from the table, so any
    stored number stays representable (mirrors how the font combo keeps
    uninstalled fonts).
    """

    def __init__(self, row: Adw.ComboRow, choices):
        self.row = row
        self._base_choices = tuple(choices)
        self._choices = ()
        self._values = []
        self.set_choices(self._base_choices)

    def set_choices(self, choices) -> None:
        """Populate the row from a ``(value, label)`` table (resets selection)."""
        choices = tuple(choices)
        self._choices = choices
        self._values = [value for value, _label in choices]
        self.row.set_model(Gtk.StringList.new([label for _value, label in choices]))

    def get_value(self):
        """Semantic value of the selected entry, or None when unset."""
        index = int(self.row.get_selected())
        if 0 <= index < len(self._values):
            return self._values[index]
        return None

    def set_value(self, value) -> None:
        """Select ``value``; unknown values appear as a custom entry."""
        choices = _choices_with(self._base_choices, value)
        if choices != self._choices:
            self.set_choices(choices)
        try:
            self.row.set_selected(self._values.index(value))
        except ValueError:
            pass  # unreachable: _choices_with always includes value

    def connect_changed(self, callback) -> None:
        """Invoke ``callback(row, pspec)`` whenever the selection changes."""
        self.row.connect('notify::selected', callback)
