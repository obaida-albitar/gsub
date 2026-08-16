"""
Reusable preferences group for batch-editing ASS style properties.

Embedded by the Batch Edit Styles dialog (per document, undoable) and the
Batch Operations panel (across files). The group shows:

- a checklist of styles with All / None quick toggles,
- property rows grouped into Text / Colours / Layout expanders, each with a
  prefix CheckButton — only ticked rows are applied,
- a live preview of the first ticked style with the ticked properties.

Hosts read the selection with :meth:`get_checked_styles` and
:meth:`get_checked_props` (ASSStyle field name -> value) and listen to the
``changed`` signal to update their apply-button sensitivity.
"""

import copy

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
gi.require_version('PangoCairo', '1.0')

from gi.repository import Adw, Gdk, GObject, Gtk, Pango, PangoCairo

from subtitle_editor.models import ASSStyle
from subtitle_editor.resources import template_resource_path
from subtitle_editor.utils import merge_font_families, parse_ass_color, format_ass_color


# Human-readable labels for summaries (batch confirm dialog, toasts).
PROP_LABELS = {
    'fontname': 'Font',
    'fontsize': 'Font Size',
    'bold': 'Bold',
    'italic': 'Italic',
    'underline': 'Underline',
    'strikeout': 'StrikeOut',
    'spacing': 'Spacing',
    'angle': 'Angle',
    'primary_color': 'Primary Colour',
    'secondary_color': 'Secondary Colour',
    'outline_color': 'Outline Colour',
    'back_color': 'Back Colour',
    'alignment': 'Alignment',
    'border_style': 'Border Style',
    'outline': 'Outline',
    'shadow': 'Shadow',
    'scale_x': 'Scale X',
    'scale_y': 'Scale Y',
    'margin_l': 'Margin L',
    'margin_r': 'Margin R',
    'margin_v': 'Margin V',
    'encoding': 'Encoding',
}


def ass_color_to_rgba(ass_color) -> Gdk.RGBA | None:
    """Parse ASS color string (&HAABBGGRR or &HBBGGRR) to Gdk.RGBA."""
    parsed = parse_ass_color(ass_color)
    if parsed is None:
        return None
    rr, gg, bb, aa = parsed

    rgba = Gdk.RGBA()
    rgba.red = rr / 255.0
    rgba.green = gg / 255.0
    rgba.blue = bb / 255.0
    rgba.alpha = 1.0 - aa / 255.0
    return rgba


def rgba_to_ass_color(rgba: Gdk.RGBA) -> str:
    """Convert RGBA to ASS &HAABBGGRR (AA inverted alpha)."""
    rr = int(round(rgba.red * 255))
    gg = int(round(rgba.green * 255))
    bb = int(round(rgba.blue * 255))
    aa = int(round((1.0 - rgba.alpha) * 255))
    return format_ass_color(rr, gg, bb, aa)


def rgba_to_css(rgba: Gdk.RGBA) -> str:
    r = int(rgba.red * 255)
    g = int(rgba.green * 255)
    b = int(rgba.blue * 255)
    a = rgba.alpha
    return f"rgba({r},{g},{b},{a:.3f})"


def update_ass_preview(label: Gtk.Label, css_provider: Gtk.CssProvider, style: ASSStyle) -> None:
    """Render ``style`` on ``label`` (Pango attrs) + the preview CSS classes.

    Shared by the ASS Styles dialog and the style properties editor so both
    previews look identical. Best effort: on failure the attributes are reset.
    """
    try:
        attrs = Pango.AttrList()
        attrs.insert(Pango.attr_family_new(style.fontname))
        attrs.insert(Pango.attr_size_new(int(style.fontsize * Pango.SCALE)))
        if style.bold:
            attrs.insert(Pango.attr_weight_new(Pango.Weight.BOLD))
        if style.italic:
            attrs.insert(Pango.attr_style_new(Pango.Style.ITALIC))
        if getattr(style, 'underline', False):
            attrs.insert(Pango.attr_underline_new(Pango.Underline.SINGLE))
        if getattr(style, 'strikeout', False):
            attrs.insert(Pango.attr_strikethrough_new(True))
        try:
            spacing_px = int(round(float(getattr(style, 'spacing', 0.0) or 0.0) * Pango.SCALE))
        except Exception:
            spacing_px = 0
        if spacing_px != 0:
            attrs.insert(Pango.attr_letter_spacing_new(spacing_px))
        label.set_attributes(attrs)

        fg = ass_color_to_rgba(getattr(style, 'primary_color', None) or '')
        bg = ass_color_to_rgba(getattr(style, 'back_color', None) or '') or Gdk.RGBA(0.95, 0.95, 0.95, 1)
        outline_col = ass_color_to_rgba(getattr(style, 'outline_color', None) or '') or Gdk.RGBA(0, 0, 0, 1)

        border_style = int(getattr(style, 'border_style', 1) or 1)
        try:
            angle = float(getattr(style, 'angle', 0.0) or 0.0)
        except Exception:
            angle = 0.0

        css = ""

        label_props = []
        if fg is not None:
            label_props.append(f"color: {rgba_to_css(fg)}")

        if angle:
            label_props.append(
                f"transform: rotate({angle:.1f}deg); transform-origin: center;")

        # The preview frame is meant to fill the viewport. We intentionally do
        # NOT apply the style's real MarginL/MarginR/MarginV here — that would
        # indent and shrink the sample so it looks like it doesn't take the
        # full width. A subtle card background makes the full-width surface
        # visible; BorderStyle 3 uses the style's back colour instead.
        frame_props = []
        if border_style == 3 and bg is not None:
            frame_props.append(f"background-color: {rgba_to_css(bg)}")
        else:
            frame_props.append("background-color: rgba(127, 127, 127, 0.18)")
        css += f".ass-preview-frame {{ {'; '.join(frame_props)}; padding: 12px; border-radius: 8px; }}\n"

        shadows = []
        ocss = rgba_to_css(outline_col) if outline_col is not None else None

        # Outline/shadow only make sense for BorderStyle 1.
        if border_style == 1:
            try:
                outline_px = float(getattr(style, 'outline', 0.0) or 0.0)
            except Exception:
                outline_px = 0.0
            try:
                shadow_px = float(getattr(style, 'shadow', 0.0) or 0.0)
            except Exception:
                shadow_px = 0.0

            if outline_px > 0 and ocss is not None:
                o = outline_px
                for dx, dy in [(-o, 0), (o, 0), (0, -o), (0, o), (-o, -o), (-o, o), (o, -o), (o, o)]:
                    shadows.append(f"{dx:.1f}px {dy:.1f}px 0 {ocss}")

            if shadow_px > 0 and ocss is not None:
                shadows.append(f"{shadow_px:.1f}px {shadow_px:.1f}px 0 {ocss}")

        if shadows:
            label_props.append(f"text-shadow: {', '.join(shadows)}")

        if label_props:
            props = '; '.join(label_props)
            css += f".ass-preview-label {{ {props}; }}\n"
            css += f".ass-preview-label > text {{ {props}; }}\n"

        css_provider.load_from_data(css.encode('utf-8'))

    except Exception:
        label.set_attributes(None)


@Gtk.Template(resource_path=template_resource_path('style-props-editor'))
class GsubStylePropsEditor(Adw.PreferencesGroup):
    """Checklist of styles + tickable property rows for batch style editing."""

    __gtype_name__ = 'GsubStylePropsEditor'

    __gsignals__ = {
        'changed': (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    target_all_row = Gtk.Template.Child()
    target_all_check = Gtk.Template.Child()
    target_one_row = Gtk.Template.Child()
    target_one_check = Gtk.Template.Child()
    target_choose_expander = Gtk.Template.Child()
    target_choose_check = Gtk.Template.Child()
    select_buttons_box = Gtk.Template.Child()
    no_styles_row = Gtk.Template.Child()
    font_row = Gtk.Template.Child()
    font_check = Gtk.Template.Child()
    fontsize_row = Gtk.Template.Child()
    fontsize_check = Gtk.Template.Child()
    bold_row = Gtk.Template.Child()
    bold_check = Gtk.Template.Child()
    italic_row = Gtk.Template.Child()
    italic_check = Gtk.Template.Child()
    underline_row = Gtk.Template.Child()
    underline_check = Gtk.Template.Child()
    strikeout_row = Gtk.Template.Child()
    strikeout_check = Gtk.Template.Child()
    spacing_row = Gtk.Template.Child()
    spacing_check = Gtk.Template.Child()
    angle_row = Gtk.Template.Child()
    angle_check = Gtk.Template.Child()
    primary_color_btn = Gtk.Template.Child()
    primary_check = Gtk.Template.Child()
    secondary_color_btn = Gtk.Template.Child()
    secondary_check = Gtk.Template.Child()
    outline_color_btn = Gtk.Template.Child()
    outline_check = Gtk.Template.Child()
    back_color_btn = Gtk.Template.Child()
    back_check = Gtk.Template.Child()
    alignment_row = Gtk.Template.Child()
    alignment_check = Gtk.Template.Child()
    border_style_row = Gtk.Template.Child()
    border_style_check = Gtk.Template.Child()
    outline_width_row = Gtk.Template.Child()
    outline_width_check = Gtk.Template.Child()
    shadow_row = Gtk.Template.Child()
    shadow_check = Gtk.Template.Child()
    scale_x_row = Gtk.Template.Child()
    scale_x_check = Gtk.Template.Child()
    scale_y_row = Gtk.Template.Child()
    scale_y_check = Gtk.Template.Child()
    margin_l_row = Gtk.Template.Child()
    margin_l_check = Gtk.Template.Child()
    margin_r_row = Gtk.Template.Child()
    margin_r_check = Gtk.Template.Child()
    margin_v_row = Gtk.Template.Child()
    margin_v_check = Gtk.Template.Child()
    encoding_row = Gtk.Template.Child()
    encoding_check = Gtk.Template.Child()
    preview_expander = Gtk.Template.Child()
    preview_label = Gtk.Template.Child()

    # (ASSStyle field, row attribute, check attribute, cast)
    _SPIN_SPECS = [
        ('fontsize', 'fontsize_row', 'fontsize_check', int),
        ('spacing', 'spacing_row', 'spacing_check', float),
        ('angle', 'angle_row', 'angle_check', float),
        ('scale_x', 'scale_x_row', 'scale_x_check', float),
        ('scale_y', 'scale_y_row', 'scale_y_check', float),
        ('outline', 'outline_width_row', 'outline_width_check', float),
        ('shadow', 'shadow_row', 'shadow_check', float),
        ('alignment', 'alignment_row', 'alignment_check', int),
        ('border_style', 'border_style_row', 'border_style_check', int),
        ('margin_l', 'margin_l_row', 'margin_l_check', int),
        ('margin_r', 'margin_r_row', 'margin_r_check', int),
        ('margin_v', 'margin_v_row', 'margin_v_check', int),
        ('encoding', 'encoding_row', 'encoding_check', int),
    ]

    # (ASSStyle field, row attribute, check attribute)
    _SWITCH_SPECS = [
        ('bold', 'bold_row', 'bold_check'),
        ('italic', 'italic_row', 'italic_check'),
        ('underline', 'underline_row', 'underline_check'),
        ('strikeout', 'strikeout_row', 'strikeout_check'),
    ]

    # (ASSStyle field, color button attribute, check attribute)
    _COLOR_SPECS = [
        ('primary_color', 'primary_color_btn', 'primary_check'),
        ('secondary_color', 'secondary_color_btn', 'secondary_check'),
        ('outline_color', 'outline_color_btn', 'outline_check'),
        ('back_color', 'back_color_btn', 'back_check'),
    ]

    def __init__(self):
        super().__init__()

        self._styles_by_name: dict[str, ASSStyle] = {}
        self._style_rows: list[Adw.ActionRow] = []
        self._style_checks: dict[str, Gtk.CheckButton] = {}
        self._loading = False
        self._single_style_getter = None

        self._installed_fonts = sorted(
            f.get_name() for f in PangoCairo.FontMap.get_default().list_families()
        )
        self._font_families: list[str] = list(self._installed_fonts)
        self._font_model = Gtk.StringList.new(self._font_families)
        self.font_row.set_model(self._font_model)

        self._preview_css_provider = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            self._preview_css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

        self._connect_signals()

        # Target radios (grouped in code, like the dialog's scope radios).
        self.target_one_check.set_group(self.target_all_check)
        self.target_choose_check.set_group(self.target_all_check)
        self.target_all_row.set_activatable_widget(self.target_all_check)
        self.target_one_row.set_activatable_widget(self.target_one_check)
        for check in (self.target_all_check, self.target_one_check, self.target_choose_check):
            check.connect('toggled', self._on_target_changed)
        self.select_buttons_box.set_visible(False)

    # --- Wiring -------------------------------------------------------------

    def _connect_signals(self):
        self.font_row.connect('notify::selected', self._on_anything_changed)
        self.font_check.connect('toggled', self._on_anything_changed)
        for _field, row_attr, check_attr, _cast in self._SPIN_SPECS:
            getattr(self, row_attr).connect('notify::value', self._on_anything_changed)
            getattr(self, check_attr).connect('toggled', self._on_anything_changed)
        for _field, row_attr, check_attr in self._SWITCH_SPECS:
            getattr(self, row_attr).connect('notify::active', self._on_anything_changed)
            getattr(self, check_attr).connect('toggled', self._on_anything_changed)
        for _field, btn_attr, check_attr in self._COLOR_SPECS:
            getattr(self, btn_attr).connect('notify::rgba', self._on_anything_changed)
            getattr(self, check_attr).connect('toggled', self._on_anything_changed)

    def _on_anything_changed(self, *args):
        if self._loading:
            return
        self._update_preview()
        self.emit('changed')

    # --- Target styles ---------------------------------------------------------

    @Gtk.Template.Callback()
    def on_select_all(self, _button):
        for check in self._style_checks.values():
            check.set_active(True)
        self._on_anything_changed()

    @Gtk.Template.Callback()
    def on_select_none(self, _button):
        for check in self._style_checks.values():
            check.set_active(False)
        self._on_anything_changed()

    def _on_target_changed(self, check):
        if not check.get_active() or self._loading:
            return
        choosing = check is self.target_choose_check
        self.select_buttons_box.set_visible(choosing)
        if choosing:
            self.target_choose_expander.set_expanded(True)
        self._on_anything_changed()

    def _mode(self) -> str:
        if self.target_one_check.get_active():
            return 'one'
        if self.target_choose_check.get_active():
            return 'choose'
        return 'all'

    def _mode_check(self, mode: str) -> Gtk.CheckButton:
        return {
            'all': self.target_all_check,
            'one': self.target_one_check,
            'choose': self.target_choose_check,
        }[mode]

    def _set_mode(self, mode: str):
        check = self._mode_check(mode)
        if not check.get_active():
            check.set_active(True)  # fires _on_target_changed
        else:
            self._on_target_changed(check)

    def set_single_style_source(self, getter):
        """Provide the "Selected style" target, e.g. the dialog's style dropdown.

        ``getter`` is a callable returning the current style name (or None).
        It makes the "Selected style" row visible and selects it as target;
        without a source the editor offers All / Choose styles only.
        """
        self._single_style_getter = getter
        self.target_one_row.set_visible(getter is not None)
        self._set_mode('one' if getter is not None else 'all')
        self.sync_single_style()

    def sync_single_style(self):
        """Refresh the 'Selected style' label and preview (source changed)."""
        if self._single_style_getter is None:
            return
        self.target_one_row.set_subtitle(self._single_style_getter() or "")
        if self._mode() == 'one':
            self._on_anything_changed()

    def get_target_styles(self) -> list[str]:
        """Style names the ticked properties would apply to."""
        mode = self._mode()
        if mode == 'one':
            if self._single_style_getter is None:
                return []
            name = self._single_style_getter()
            return [name] if name in self._styles_by_name else []
        if mode == 'choose':
            return self._checked_choose_styles()
        return list(self._styles_by_name)

    def _checked_choose_styles(self) -> list[str]:
        """Names ticked in the "Choose styles" checklist, in display order."""
        return [name for name, check in self._style_checks.items() if check.get_active()]

    def set_styles(self, styles):
        """Rebuild the "Choose styles" checklist and reload row values.

        Checks of styles that remain in the new list are preserved; row values
        are (re)loaded from the target style so ticking a row applies a
        sensible value.
        """
        previous_checked = set(self._checked_choose_styles())

        for row in self._style_rows:
            self.target_choose_expander.remove(row)
        self._style_rows = []
        self._style_checks = {}

        self._styles_by_name = {
            s.name: copy.deepcopy(s) for s in (styles or []) if getattr(s, 'name', None)
        }

        for name in self._styles_by_name:
            row = Adw.ActionRow(title=name)
            check = Gtk.CheckButton()
            check.set_valign(Gtk.Align.CENTER)
            check.set_active(name in previous_checked)
            check.connect('toggled', self._on_anything_changed)
            row.add_prefix(check)
            row.set_activatable_widget(check)
            self.target_choose_expander.add_row(row)
            self._style_rows.append(row)
            self._style_checks[name] = check

        self.no_styles_row.set_visible(not self._styles_by_name)

        # A "one" target is impossible without a source; fall back to "all".
        if self._mode() == 'one' and self._single_style_getter is None:
            self._set_mode('all')

        # Keep style fonts in the dropdown even when not installed so the
        # preview can use them and re-selecting never loses the real value.
        self._font_families = merge_font_families(
            self._installed_fonts,
            (s.fontname for s in self._styles_by_name.values()),
        )
        self._font_model = Gtk.StringList.new(self._font_families)
        self.font_row.set_model(self._font_model)

        base = self._base_style()
        if base is not None:
            self._load_values_from_style(base)

        self._on_anything_changed()

    # --- Property values ------------------------------------------------------

    def get_checked_props(self) -> dict:
        """Map of ASSStyle field name -> value for every ticked property row."""
        props = {}

        if self.font_check.get_active():
            item = self.font_row.get_selected_item()
            if item is not None:
                props['fontname'] = item.get_string()

        for field, row_attr, check_attr, cast in self._SPIN_SPECS:
            if getattr(self, check_attr).get_active():
                props[field] = cast(getattr(self, row_attr).get_value())

        for field, row_attr, check_attr in self._SWITCH_SPECS:
            if getattr(self, check_attr).get_active():
                props[field] = bool(getattr(self, row_attr).get_active())

        for field, btn_attr, check_attr in self._COLOR_SPECS:
            if getattr(self, check_attr).get_active():
                props[field] = rgba_to_ass_color(getattr(self, btn_attr).get_rgba())

        return props

    def has_changes(self) -> bool:
        """True when a target is selected AND at least one property is ticked."""
        return bool(self.get_target_styles()) and bool(self.get_checked_props())

    def property_labels(self) -> list[str]:
        """Human-readable labels of the ticked properties (for summaries)."""
        return [PROP_LABELS.get(field, field) for field in self.get_checked_props()]

    def reset(self):
        """Clear every tick, collapse sections, restore the default target."""
        self._loading = True
        try:
            for check in self._style_checks.values():
                check.set_active(False)
            self.font_check.set_active(False)
            for attrs in (self._SPIN_SPECS, self._SWITCH_SPECS, self._COLOR_SPECS):
                for spec in attrs:
                    getattr(self, spec[2]).set_active(False)
            self.preview_expander.set_expanded(False)
            self.target_choose_expander.set_expanded(False)
            self._mode_check('one' if self._single_style_getter is not None else 'all').set_active(True)
            self.select_buttons_box.set_visible(False)
            base = self._base_style()
            if base is not None:
                self._load_values_from_style(base)
        finally:
            self._loading = False
        self._on_anything_changed()

    # --- Internals ------------------------------------------------------------

    def _base_style(self) -> ASSStyle | None:
        """First target style, else first available, as the value template."""
        targets = self.get_target_styles()
        if targets:
            return self._styles_by_name[targets[0]]
        if self._styles_by_name:
            return next(iter(self._styles_by_name.values()))
        return None

    def _load_values_from_style(self, style: ASSStyle):
        """Set every row's value from ``style`` without ticking anything."""
        self._loading = True
        try:
            try:
                font_idx = self._font_families.index(style.fontname)
            except ValueError:
                font_idx = 0
            self.font_row.set_selected(font_idx)
            self.fontsize_row.set_value(int(style.fontsize))
            for field, row_attr, _check_attr, cast in self._SPIN_SPECS:
                getattr(self, row_attr).set_value(cast(getattr(style, field)))
            for field, row_attr, _check_attr in self._SWITCH_SPECS:
                getattr(self, row_attr).set_active(bool(getattr(style, field)))
            for field, btn_attr, _check_attr in self._COLOR_SPECS:
                rgba = ass_color_to_rgba(getattr(style, field))
                if rgba is None:
                    rgba = Gdk.RGBA(0, 0, 0, 1)
                getattr(self, btn_attr).set_rgba(rgba)
        finally:
            self._loading = False

    def _update_preview(self):
        """Preview = first ticked style with the ticked properties applied."""
        base = self._base_style()
        if base is None:
            self.preview_label.set_attributes(None)
            return
        style = copy.deepcopy(base)
        for field, value in self.get_checked_props().items():
            setattr(style, field, value)
        update_ass_preview(self.preview_label, self._preview_css_provider, style)
