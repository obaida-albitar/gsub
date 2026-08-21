"""
Visual editor rows for an ASS override-tag block.

The editor panel splits a dialogue line into its LEADING ``{...}`` block and
the remaining text. This module owns the rows that let the user edit that
leading block through proper widgets (spin rows, switches, colour buttons,
a font dropdown), one row per tag instance in original order. Unknown or
complex tags (``\\t(...)``, ``\\clip``, karaoke, drawings...) fall back to a
raw-text entry row.

:class:`TagEditorRows` is format-agnostic about where the rows live: it is
given an :class:`Adw.ExpanderRow` to populate and exposes

- ``load_body(body)`` — rebuild the rows from a block body (no signals),
- ``get_block()`` — the re-serialized ``{...}`` block (or None when empty),
- the ``changed`` signal — emitted whenever the user edits any row.

Round-trip safety: untouched tags re-emit their original raw bytes, so
loading a line and changing nothing reproduces it exactly.
"""

import gettext
import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
gi.require_version('PangoCairo', '1.0')

from gi.repository import Adw, Gdk, Gio, GObject, Gtk, PangoCairo  # noqa: E402

from gsub.parsers.ass_tags import (  # noqa: E402
    OverrideTag,
    parse_override_block,
    parse_tag_segment,
    serialize_override_tags,
)
from gsub.utils import merge_font_families  # noqa: E402
from gsub.widgets.style_props_editor import (  # noqa: E402
    ass_color_to_rgba,
    rgba_to_ass_color,
)

# Same translation domain as the package-level gettext.install(); bound
# explicitly so the `_` alias is visible to static analysis.
_ = gettext.translation('gsub', fallback=True).gettext

# One row per tag; labels follow the ASS naming for the colour slots.
COLOR_TAG_TITLES = {
    'c': 'Colour',
    '1c': 'Primary (1c)',
    '2c': 'Secondary (2c)',
    '3c': 'Outline (3c)',
    '4c': 'Shadow (4c)',
}

SWITCH_TAG_TITLES = {
    'b': 'Bold',
    'i': 'Italic',
    'u': 'Underline',
    's': 'Strikeout',
}

# name -> (title, lower, upper, digits)
SPIN_TAG_SPECS = {
    'fs': ('Size', 1, 300, 0),
    'blur': ('Blur', 0, 20, 1),
    'bord': ('Border Width', 0, 20, 1),
    'shad': ('Shadow Depth', 0, 20, 1),
    'fsp': ('Letter Spacing', -100, 100, 1),
}

# Add-tag menu: (action name, label, default raw tag).
ADDABLE_TAGS = (
    ('bold', 'Bold', '\\b1'),
    ('italic', 'Italic', '\\i1'),
    ('underline', 'Underline', '\\u1'),
    ('strikeout', 'Strikeout', '\\s1'),
    ('font', 'Font', '\\fnArial'),
    ('size', 'Size', '\\fs48'),
    ('primary-color', 'Primary Colour', '\\c&H00FFFFFF'),
    ('outline-color', 'Outline Colour', '\\3c&H00000000'),
    ('shadow-color', 'Shadow Colour', '\\4c&H00000000'),
    ('position', 'Position', '\\pos(10,50)'),
    ('blur', 'Blur', '\\blur1'),
    ('border-width', 'Border Width', '\\bord2'),
    ('shadow-depth', 'Shadow Depth', '\\shad2'),
)

_POS_RANGE = (0, 4096)

_installed_fonts_cache = None


def _installed_fonts() -> list:
    """Sorted font family names, cached after the first query."""
    global _installed_fonts_cache
    if _installed_fonts_cache is None:
        _installed_fonts_cache = sorted(
            f.get_name() for f in PangoCairo.FontMap.get_default().list_families()
        )
    return _installed_fonts_cache


def _parse_float(value, default=0.0) -> float:
    """float() that tolerates ASS-style ".1" arguments; default on failure."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _format_number(value: float) -> str:
    """Compact numeric tag argument ("0.1", "48", "-3.5")."""
    return f'{value:g}'


def _is_paren_form(piece: OverrideTag) -> bool:
    """Whether the tag was written in the ``\\name(args)`` form."""
    return '(' in piece.raw and piece.raw.endswith(')')


def _normalize_color_arg(arg: str) -> str:
    """Tolerate bare ``BBGGRR`` colour args by adding the ``&H`` prefix."""
    arg = (arg or '').strip()
    if arg and not arg.startswith('&'):
        return '&H' + arg
    return arg


def _valid_raw_tag(text: str) -> bool:
    """Minimal validation for a raw tag edited in an entry row.

    Must start with a backslash and keep parentheses balanced; braces never
    occur inside a single tag's raw form.
    """
    if not text.startswith('\\') or len(text) < 2:
        return False
    if '{' in text or '}' in text:
        return False
    return text.count('(') == text.count(')')


class TagEditorRows(GObject.Object):
    """Builds and manages Adw rows editing one override block's tags."""

    __gtype_name__ = 'GsubTagEditorRows'

    __gsignals__ = {
        'changed': (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, expander: Adw.ExpanderRow):
        super().__init__()
        self._expander = expander
        # Ordered pieces (tags and opaque content) of the block body.
        self._pieces: list[OverrideTag] = []
        self._rows: list[Adw.PreferencesRow] = []
        self._updating = False
        # An originally empty block "{}" round-trips as "{}" until edited.
        self._empty_block = False

    # --- Public API ----------------------------------------------------------

    def load_body(self, body):
        """Rebuild the rows from a block body (without braces), or clear.

        Never emits ``changed``; callers use this while loading an entry.
        """
        self._updating = True
        try:
            for row in self._rows:
                self._expander.remove(row)
            self._rows = []
            self._pieces = parse_override_block(body) if body else []
            self._empty_block = body is not None and body == ''
            for piece in self._pieces:
                row = self._build_row(piece)
                if row is not None:
                    self._expander.add_row(row)
                    self._rows.append(row)
        finally:
            self._updating = False

    def get_block(self):
        """The serialized ``{...}`` block, or None when there is none."""
        body = serialize_override_tags(self._pieces)
        if not body and not self._empty_block:
            return None
        return '{' + body + '}'

    def get_tag_count(self) -> int:
        """Number of real tags (opaque block content is not counted)."""
        return sum(1 for piece in self._pieces if piece.name)

    def get_rows(self) -> list:
        """The currently built rows, in block order (for tests/inspection)."""
        return list(self._rows)

    def add_tag(self, raw: str):
        """Append a tag given in raw form (e.g. ``\\\\b1``) and emit changed."""
        tag = parse_tag_segment(raw[1:] if raw.startswith('\\') else raw)
        if tag is None:
            return
        self._pieces.append(tag)
        row = self._build_row(tag)
        if row is not None:
            self._expander.add_row(row)
            self._rows.append(row)
        self._emit_changed()

    def setup_add_button(self, button: Gtk.MenuButton):
        """Turn ``button`` into the add-tag menu opener."""
        actions = Gio.SimpleActionGroup()
        menu = Gio.Menu()
        for name, label, raw in ADDABLE_TAGS:
            action = Gio.SimpleAction.new(name, None)
            action.connect('activate', self._on_add_activated, raw)
            actions.add_action(action)
            menu.append(label, f'tag-add.{name}')
        button.insert_action_group('tag-add', actions)
        button.set_popover(Gtk.PopoverMenu.new_from_model(menu))

    # --- Internals ------------------------------------------------------------

    def _on_add_activated(self, action, parameter, raw):
        self.add_tag(raw)

    def _emit_changed(self):
        if self._updating:
            return
        self._empty_block = False
        self.emit('changed')

    def _set_piece_value(self, piece: OverrideTag, value: str, paren: bool):
        """Rewrite a piece's args/raw, keeping the parsed spelling form."""
        piece.args = [value]
        if paren:
            piece.raw = '\\' + piece.name + '(' + value + ')'
        else:
            piece.raw = '\\' + piece.name + value

    def _make_remove_button(self, piece, row) -> Gtk.Button:
        def on_clicked(_button):
            if self._updating:
                return
            self._expander.remove(row)
            self._rows.remove(row)
            self._pieces.remove(piece)
            self._emit_changed()

        button = Gtk.Button(icon_name='user-trash-symbolic',
                            valign=Gtk.Align.CENTER,
                            tooltip_text=_('Remove tag'))
        button.add_css_class('flat')
        button.connect('clicked', on_clicked)
        return button

    def _build_row(self, piece: OverrideTag):
        """Build the editing row for ``piece`` (None for invisible pieces)."""
        name = piece.name
        if not name:
            # Opaque block content: only tag-like pieces (starting with a
            # backslash) get an editable raw row; pure comment text stays
            # invisible but is preserved by serialization.
            if not piece.raw.startswith('\\'):
                return None
            return self._build_raw_row(piece)
        if name in COLOR_TAG_TITLES:
            return self._build_color_row(piece)
        if name in SWITCH_TAG_TITLES:
            return self._build_switch_row(piece)
        if name == 'fn':
            return self._build_font_row(piece)
        if name == 'pos':
            return self._build_pos_row(piece)
        if name in SPIN_TAG_SPECS:
            return self._build_spin_row(piece)
        return self._build_raw_row(piece)

    # --- Row builders -----------------------------------------------------------

    def _build_spin_row(self, piece: OverrideTag) -> Adw.SpinRow:
        title, lower, upper, digits = SPIN_TAG_SPECS[piece.name]
        value = _parse_float(piece.args[0] if piece.args else None, lower)
        paren = _is_paren_form(piece)
        row = Adw.SpinRow(
            title=_(title),
            subtitle='\\' + piece.name,
            adjustment=Gtk.Adjustment(
                value=min(max(value, lower), upper),
                lower=lower,
                upper=upper,
                step_increment=1 if digits == 0 else 0.1,
                page_increment=10 if digits == 0 else 1,
                page_size=0,
            ),
            digits=digits,
        )
        row.set_numeric(True)

        def on_value_changed(spin_row, _pspec):
            if self._updating:
                return
            self._set_piece_value(piece, _format_number(spin_row.get_value()), paren)
            self._emit_changed()

        row.connect('notify::value', on_value_changed)
        row.add_suffix(self._make_remove_button(piece, row))
        return row

    def _build_switch_row(self, piece: OverrideTag) -> Adw.SwitchRow:
        paren = _is_paren_form(piece)
        row = Adw.SwitchRow(title=_(SWITCH_TAG_TITLES[piece.name]),
                            subtitle='\\' + piece.name)
        row.set_active(bool(piece.args) and piece.args[0] not in ('0', '', 'false'))

        def on_active_changed(switch_row, _pspec):
            if self._updating:
                return
            self._set_piece_value(piece, '1' if switch_row.get_active() else '0', paren)
            self._emit_changed()

        row.connect('notify::active', on_active_changed)
        row.add_suffix(self._make_remove_button(piece, row))
        return row

    def _build_color_row(self, piece: OverrideTag) -> Adw.ActionRow:
        paren = _is_paren_form(piece)
        arg = _normalize_color_arg(piece.args[0] if piece.args else '')
        rgba = ass_color_to_rgba(arg)
        if rgba is None:
            rgba = Gdk.RGBA(0, 0, 0, 1)
        row = Adw.ActionRow(title=_(COLOR_TAG_TITLES[piece.name]),
                            subtitle='\\' + piece.name)

        button = Gtk.ColorDialogButton(valign=Gtk.Align.CENTER,
                                       dialog=Gtk.ColorDialog(with_alpha=True))
        button.set_rgba(rgba)
        row.add_suffix(button)

        def on_rgba_changed(color_button, _pspec):
            if self._updating:
                return
            # Always write the canonical &HAABBGGRR spelling when setting.
            self._set_piece_value(piece, rgba_to_ass_color(color_button.get_rgba()), paren)
            self._emit_changed()

        button.connect('notify::rgba', on_rgba_changed)
        row.add_suffix(self._make_remove_button(piece, row))
        return row

    def _build_font_row(self, piece: OverrideTag) -> Adw.ComboRow:
        paren = _is_paren_form(piece)
        current = piece.args[0] if piece.args else ''
        # Installed fonts plus the tag's own font (kept even when not
        # installed, mirroring the style editors' font dropdown).
        families = merge_font_families(_installed_fonts(), [current])
        row = Adw.ComboRow(title=_('Font'), subtitle='\\fn',
                           model=Gtk.StringList.new(families))
        try:
            row.set_selected(families.index(current))
        except ValueError:  # pragma: no cover - merge always includes it
            row.set_selected(0)

        def on_selected(combo_row, _pspec):
            if self._updating:
                return
            item = combo_row.get_selected_item()
            if item is None:
                return
            self._set_piece_value(piece, item.get_string(), paren)
            self._emit_changed()

        row.connect('notify::selected', on_selected)
        row.add_suffix(self._make_remove_button(piece, row))
        return row

    def _build_pos_row(self, piece: OverrideTag) -> Adw.ActionRow:
        args = [a for a in (piece.args or [])]
        if len(args) == 1 and ',' in args[0]:
            args = args[0].split(',', 1)
        x = _parse_float(args[0] if args else None)
        y = _parse_float(args[1] if len(args) > 1 else None)
        row = Adw.ActionRow(title=_('Position'), subtitle='\\pos(x,y)')

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                      spacing=4, valign=Gtk.Align.CENTER)
        spins = []
        for label, value in (('X:', x), ('Y:', y)):
            box.append(Gtk.Label(label=label))
            spin = Gtk.SpinButton(
                adjustment=Gtk.Adjustment(
                    value=min(max(value, _POS_RANGE[0]), _POS_RANGE[1]),
                    lower=_POS_RANGE[0], upper=_POS_RANGE[1],
                    step_increment=1, page_increment=100, page_size=0),
                numeric=True)
            spin.set_width_chars(5)
            spins.append(spin)
            box.append(spin)
        row.add_suffix(box)

        def on_value_changed(_spin):
            if self._updating:
                return
            piece.args = [str(spins[0].get_value_as_int()),
                          str(spins[1].get_value_as_int())]
            piece.raw = '\\pos({},{})'.format(*piece.args)
            self._emit_changed()

        for spin in spins:
            spin.connect('value-changed', on_value_changed)
        row.add_suffix(self._make_remove_button(piece, row))
        return row

    def _build_raw_row(self, piece: OverrideTag) -> Adw.EntryRow:
        row = Adw.EntryRow(title=_('Tag'))
        row.set_text(piece.raw)

        def on_text_changed(entry_row, _pspec):
            if self._updating:
                return
            text = entry_row.get_text()
            if not _valid_raw_tag(text):
                return  # keep the last good value
            piece.raw = text
            reparsed = parse_tag_segment(text[1:])
            if reparsed is not None:
                piece.name = reparsed.name
                piece.args = reparsed.args
            self._emit_changed()

        row.connect('notify::text', on_text_changed)
        row.add_suffix(self._make_remove_button(piece, row))
        return row
