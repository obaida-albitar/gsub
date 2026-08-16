"""
Dialog widgets for the subtitle editor.
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
gi.require_version('PangoCairo', '1.0')

from gi.repository import Gtk, Adw, PangoCairo, Gdk, GObject
from subtitle_editor.commands import (
    TimeShiftCommand,
    ReplaceASSHeaderCommand,
    BulkEditStyleCommand,
    BulkUpdateStylePropsCommand,
)
from subtitle_editor.models import ASSStyle
from subtitle_editor.resources import template_resource_path
from subtitle_editor.shortcuts import SECTION_ORDER, entries_for_section
from subtitle_editor.utils import merge_font_families, is_font_installed
from subtitle_editor.widgets.style_props_editor import (
    GsubStylePropsEditor,
    ass_color_to_rgba,
    rgba_to_ass_color,
    rgba_to_css,
    update_ass_preview,
)
from subtitle_editor.widgets.style_widgets import (  # noqa: E402
    BORDER_STYLE_CHOICES,
    ENCODING_CHOICES,
    AlignmentGrid,
    ChoiceRow,
)
import copy


@Gtk.Template(resource_path=template_resource_path('time-shift'))
class TimeShiftDialog(Adw.Dialog):
    """Dialog for shifting subtitle timing."""

    __gtype_name__ = 'GsubTimeShiftDialog'

    offset_row = Gtk.Template.Child()
    back_box = Gtk.Template.Child()
    forward_box = Gtk.Template.Child()
    scope_all = Gtk.Template.Child()
    scope_selected = Gtk.Template.Child()
    scope_from = Gtk.Template.Child()
    scope_all_row = Gtk.Template.Child()
    scope_selected_row = Gtk.Template.Child()
    scope_from_row = Gtk.Template.Child()

    def __init__(self, parent_window):
        super().__init__()

        self.parent_window = parent_window
        self.document = parent_window.document

        # Build the preset buttons (loop-generated with closures).
        for label, value in [("-5s", -5000), ("-1s", -1000), ("-100ms", -100)]:
            button = Gtk.Button(label=label)
            button.connect('clicked', lambda b, v=value: self.offset_row.set_value(self.offset_row.get_value() + v))
            self.back_box.append(button)

        for label, value in [("+100ms", 100), ("+1s", 1000), ("+5s", 5000)]:
            button = Gtk.Button(label=label)
            button.add_css_class("suggested-action")
            button.connect('clicked', lambda b, v=value: self.offset_row.set_value(self.offset_row.get_value() + v))
            self.forward_box.append(button)

        # Group the scope radio buttons (must be wired in code).
        self.scope_selected.set_group(self.scope_all)
        self.scope_from.set_group(self.scope_all)
        self.scope_all_row.set_activatable_widget(self.scope_all)
        self.scope_selected_row.set_activatable_widget(self.scope_selected)
        self.scope_from_row.set_activatable_widget(self.scope_from)

    @Gtk.Template.Callback()
    def on_cancel_clicked(self, _button):
        self.close()

    @Gtk.Template.Callback()
    def on_apply(self, _button):
        """Apply the time shift."""
        offset_ms = int(self.offset_row.get_value())

        if offset_ms == 0:
            self.close()
            return

        # Determine which subtitles to shift
        positions = None

        if self.scope_selected.get_active():
            # Only selected subtitles
            positions = self.parent_window.subtitle_list.get_selected_positions()
            if not positions:
                self.close()
                return

        elif self.scope_from.get_active():
            # From first selected to end
            selected_positions = self.parent_window.subtitle_list.get_selected_positions()
            if selected_positions:
                first_pos = min(selected_positions)
                positions = list(range(first_pos, len(self.document.entries)))
            else:
                self.close()
                return

        # Create and execute command
        cmd = TimeShiftCommand(self.document, offset_ms, positions)
        self.parent_window.command_manager.execute(cmd)

        # Update UI - preserve selection
        self.parent_window.subtitle_list.refresh(preserve_selection=True)
        self.parent_window._update_title()
        self.parent_window._update_undo_redo_buttons()
        self.parent_window._refresh_video_preview()
        self.parent_window._show_toast(f"Time shifted by {offset_ms}ms")

        self.close()


@Gtk.Template(resource_path=template_resource_path('bulk-apply-style'))
class BulkApplyStyleDialog(Adw.Dialog):
    """Dialog to apply a style to multiple subtitle entries (ASS/SSA)."""

    __gtype_name__ = 'GsubBulkApplyStyleDialog'

    style_row = Gtk.Template.Child()
    scope_selected = Gtk.Template.Child()
    scope_selected_check = Gtk.Template.Child()
    scope_all = Gtk.Template.Child()
    scope_all_check = Gtk.Template.Child()
    scope_from = Gtk.Template.Child()
    scope_from_check = Gtk.Template.Child()

    def __init__(self, parent_window):
        super().__init__()
        self.parent_window = parent_window
        self.document = parent_window.document

        style_names = [s.name for s in (self.document.styles or [])] or ['Default']
        self._style_names = style_names
        self._style_model = Gtk.StringList.new(style_names)
        self.style_row.set_model(self._style_model)

        # Group the scope radio buttons (must be wired in code).
        self.scope_all_check.set_group(self.scope_selected_check)
        self.scope_from_check.set_group(self.scope_selected_check)
        self.scope_selected.set_activatable_widget(self.scope_selected_check)
        self.scope_all.set_activatable_widget(self.scope_all_check)
        self.scope_from.set_activatable_widget(self.scope_from_check)

    @Gtk.Template.Callback()
    def on_cancel_clicked(self, _button):
        self.close()

    def _resolve_positions(self):
        if self.scope_all_check.get_active():
            return list(range(len(self.document.entries)))
        if self.scope_from_check.get_active():
            selected_positions = self.parent_window.subtitle_list.get_selected_positions()
            if not selected_positions:
                return []
            first_pos = min(selected_positions)
            return list(range(first_pos, len(self.document.entries)))

        # default: selected
        return self.parent_window.subtitle_list.get_selected_positions()

    @Gtk.Template.Callback()
    def on_apply(self, _button):
        if not self.document or not self.document.entries:
            self.close()
            return

        positions = self._resolve_positions()
        if not positions:
            self.parent_window._show_toast("No subtitles selected")
            self.close()
            return

        idx = int(self.style_row.get_selected())
        style_name = self._style_names[idx] if 0 <= idx < len(self._style_names) else 'Default'

        cmd = BulkEditStyleCommand(self.document, positions, style_name)
        self.parent_window.command_manager.execute(cmd)

        self.parent_window.subtitle_list.refresh(preserve_selection=True)
        self.parent_window._update_title()
        self.parent_window._update_undo_redo_buttons()
        self.parent_window._refresh_video_preview()
        self.parent_window._show_toast(f"Applied style '{style_name}'")

        self.close()


@Gtk.Template(resource_path=template_resource_path('batch-style-props'))
class BatchStylePropsDialog(Adw.Dialog):
    """Dialog to batch-edit style definitions (font, colours, layout) (ASS/SSA).

    Complements :class:`BulkApplyStyleDialog` (right-click), which only
    assigns a style name to lines: this one modifies the style definitions
    themselves on the chosen targets, as a single undo step.
    """

    __gtype_name__ = 'GsubBatchStylePropsDialog'

    prefs_page = Gtk.Template.Child()
    apply_button = Gtk.Template.Child()
    style_row = Gtk.Template.Child()

    def __init__(self, parent_window):
        super().__init__()
        self.parent_window = parent_window
        self.document = parent_window.document

        style_names = [s.name for s in (self.document.styles or [])] or ['Default']
        self._style_names = style_names
        self._style_model = Gtk.StringList.new(style_names)
        self.style_row.set_model(self._style_model)

        # Style property batch editor; its "Selected style" target follows the
        # dropdown above.
        self.style_props = GsubStylePropsEditor()
        self.style_props.set_single_style_source(self._selected_style)
        self.style_props.set_styles(self.document.styles or [])
        self.style_props.connect('changed', lambda *a: self._update_apply_sensitivity())
        self.prefs_page.add(self.style_props)
        self.style_row.connect('notify::selected', lambda *a: self.style_props.sync_single_style())
        self._update_apply_sensitivity()

    @Gtk.Template.Callback()
    def on_cancel_clicked(self, _button):
        self.close()

    def _selected_style(self):
        idx = int(self.style_row.get_selected())
        return self._style_names[idx] if 0 <= idx < len(self._style_names) else None

    def _update_apply_sensitivity(self):
        self.apply_button.set_sensitive(self.style_props.has_changes())

    @Gtk.Template.Callback()
    def on_apply(self, _button):
        target_styles = self.style_props.get_target_styles()
        props = self.style_props.get_checked_props()
        if not target_styles or not props:
            self.parent_window._show_toast("Nothing to apply")
            return

        cmd = BulkUpdateStylePropsCommand(self.document, target_styles, props)
        self.parent_window.command_manager.execute(cmd)

        self.parent_window.subtitle_list.refresh(preserve_selection=True)
        self.parent_window._update_title()
        self.parent_window._update_undo_redo_buttons()
        self.parent_window._refresh_video_preview()
        self.parent_window._show_toast(
            f"Updated {len(target_styles)} style{'s' if len(target_styles) != 1 else ''}"
        )

        self.close()


@Gtk.Template(resource_path=template_resource_path('ass-info'))
class ASSInfoDialog(Adw.Dialog):
    """Dialog to edit ASS/SSA Script Info metadata (no styles)."""

    __gtype_name__ = 'GsubASSInfoDialog'

    COMMON_KEYS = [
        ('Title', 'Title'),
        ('ScriptType', 'Script Type'),
        ('WrapStyle', 'Wrap Style'),
        ('ScaledBorderAndShadow', 'Scaled Border And Shadow'),
        ('YCbCr Matrix', 'YCbCr Matrix'),
    ]

    # Template children (static editor rows).
    info_group = Gtk.Template.Child()
    info_extra_group = Gtk.Template.Child()
    aegisub_group = Gtk.Template.Child()

    def __init__(self, parent_window):
        super().__init__()
        self.parent_window = parent_window
        self.document = parent_window.document

        # Local editable copies
        self._metadata = copy.deepcopy(self.document.metadata or {})

        # --- Script Info: common keys (built in a loop) ---
        self._info_rows = {}
        for key, label in self.COMMON_KEYS:
            row = Adw.EntryRow()
            row.set_title(label)
            row.set_text(str(self._metadata.get(key, "")))
            self.info_group.add(row)
            self._info_rows[key] = row

        # Additional Script Info editor (key/value list, excluding common keys)
        self._script_info_rows = []  # list of (key_entry, value_entry, row)
        common_keys = {k for k, _ in self.COMMON_KEYS}
        self._build_kv_section(
            self.info_extra_group,
            self._script_info_rows,
            {k: v for k, v in self._metadata.items() if k not in common_keys},
        )

        # Aegisub Project Garbage editor (key/value list)
        self._aegisub_rows = []
        self._aegisub_garbage = copy.deepcopy(getattr(self.document, 'aegisub_project_garbage', {}) or {})
        self._build_kv_section(
            self.aegisub_group,
            self._aegisub_rows,
            self._aegisub_garbage,
        )

    @Gtk.Template.Callback()
    def on_cancel_clicked(self, _button):
        self.close()

    def _make_kv_listbox(self) -> Gtk.ListBox:
        listbox = Gtk.ListBox()
        listbox.add_css_class("boxed-list")
        listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        return listbox

    def _build_kv_section(self, group: Adw.PreferencesGroup, store_list: list, initial: dict) -> Gtk.ListBox:
        """Create a key/value ListBox, add it to the group, and populate it."""
        listbox = self._make_kv_listbox()
        group.add(listbox)
        add_row = self._make_add_row(listbox, store_list)
        for k in sorted(initial.keys()):
            self._add_kv_row(listbox, store_list, k, initial[k], add_row)
        listbox.append(add_row)
        return listbox

    def _make_add_row(self, listbox: Gtk.ListBox, store_list: list) -> Gtk.ListBoxRow:
        """Create the persistent 'Add key' row for a key/value ListBox."""
        add_row = Gtk.ListBoxRow()
        add_row.set_activatable(False)
        add_row.set_selectable(False)

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(8)
        box.set_margin_end(8)

        label = Gtk.Label(label=_("Add key"))
        label.set_hexpand(True)
        label.set_xalign(0.0)

        add_btn = Gtk.Button()
        add_btn.set_icon_name("list-add-symbolic")
        add_btn.add_css_class("flat")
        add_btn.add_css_class("circular")
        add_btn.set_valign(Gtk.Align.CENTER)
        add_btn.connect('clicked', lambda _b: self._add_kv_row(listbox, store_list, "", "", add_row))

        box.append(label)
        box.append(add_btn)
        add_row.set_child(box)
        return add_row

    def _add_kv_row(self, listbox: Gtk.ListBox, store_list: list, key: str, value: str, add_row: Gtk.ListBoxRow) -> None:
        """Append a key/value row to a ListBox, inserting it before the Add row."""
        row = Gtk.ListBoxRow()
        row.set_activatable(False)
        row.set_selectable(False)

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(8)
        box.set_margin_end(8)

        key_entry = Gtk.Entry()
        key_entry.set_hexpand(False)
        key_entry.set_width_chars(18)
        key_entry.set_placeholder_text(_("Key"))
        key_entry.set_text(str(key or ""))

        value_entry = Gtk.Entry()
        value_entry.set_hexpand(True)
        value_entry.set_placeholder_text(_("Value"))
        value_entry.set_text(str(value or ""))

        del_btn = Gtk.Button()
        del_btn.set_icon_name("user-trash-symbolic")
        del_btn.add_css_class("flat")
        del_btn.add_css_class("circular")
        del_btn.set_valign(Gtk.Align.CENTER)
        del_btn.connect('clicked', lambda _b: self._remove_kv_row(listbox, store_list, row))

        box.append(key_entry)
        box.append(value_entry)
        box.append(del_btn)
        row.set_child(box)

        add_index = add_row.get_index()
        listbox.insert(row, add_index if add_index >= 0 else -1)
        store_list.append((key_entry, value_entry, row))

    def _remove_kv_row(self, listbox: Gtk.ListBox, store_list: list, row: Gtk.ListBoxRow) -> None:
        listbox.remove(row)
        for i, entry in enumerate(store_list):
            if entry[2] is row:
                store_list.pop(i)
                break

    def _collect_kv_rows(self, rows: list) -> dict:
        out = {}
        for key_entry, value_entry, _row in rows:
            k = key_entry.get_text().strip()
            if not k:
                continue
            out[k] = value_entry.get_text().strip()
        return out

    @Gtk.Template.Callback()
    def on_apply(self, _button):
        # Collect Script Info from dynamic rows
        metadata = self._collect_kv_rows(self._script_info_rows)

        # Also include the common convenience fields (they override if filled)
        for key, _label in self.COMMON_KEYS:
            val = self._info_rows[key].get_text().strip()
            if val:
                metadata[key] = val

        # Aegisub Project Garbage
        aegisub_garbage = self._collect_kv_rows(self._aegisub_rows)

        # Preserve the existing styles (edited via the separate Styles dialog).
        cmd = ReplaceASSHeaderCommand(
            self.document,
            metadata=metadata,
            aegisub_project_garbage=aegisub_garbage,
            styles=self.document.styles,
            fallback_style='Default',
        )
        self.parent_window.command_manager.execute(cmd)

        self.parent_window.subtitle_list.refresh(preserve_selection=True)
        self.parent_window._update_title()
        self.parent_window._update_undo_redo_buttons()
        self.parent_window._refresh_video_preview()
        self.parent_window._show_toast("Updated ASS metadata")

        self.close()


@Gtk.Template(resource_path=template_resource_path('ass-styles'))
class ASSStylesDialog(Adw.Dialog):
    """Dialog to edit ASS/SSA style definitions ([V4+ Styles])."""

    __gtype_name__ = 'GsubASSStylesDialog'

    # Template children (static editor rows).
    style_editor_group = Gtk.Template.Child()
    style_combo = Gtk.Template.Child()
    style_name = Gtk.Template.Child()
    style_font = Gtk.Template.Child()
    style_fontsize = Gtk.Template.Child()
    font_warning = Gtk.Template.Child()
    primary_color_btn = Gtk.Template.Child()
    outline_color_btn = Gtk.Template.Child()
    back_color_btn = Gtk.Template.Child()
    style_bold = Gtk.Template.Child()
    style_italic = Gtk.Template.Child()
    style_underline = Gtk.Template.Child()
    style_strikeout = Gtk.Template.Child()
    style_spacing = Gtk.Template.Child()
    style_angle = Gtk.Template.Child()
    secondary_color_btn = Gtk.Template.Child()
    layout_group = Gtk.Template.Child()
    style_border_style = Gtk.Template.Child()
    style_margin_l = Gtk.Template.Child()
    style_margin_r = Gtk.Template.Child()
    style_margin_v = Gtk.Template.Child()
    style_encoding = Gtk.Template.Child()
    style_scale_x = Gtk.Template.Child()
    style_scale_y = Gtk.Template.Child()
    style_outline_width = Gtk.Template.Child()
    style_shadow = Gtk.Template.Child()
    style_alignment = Gtk.Template.Child()
    preview_expander = Gtk.Template.Child()
    preview_label = Gtk.Template.Child()
    preview_frame = Gtk.Template.Child()
    preview_scroller = Gtk.Template.Child()

    def __init__(self, parent_window):
        super().__init__()
        self.parent_window = parent_window
        self.document = parent_window.document

        # Local editable copies of the styles.
        self._styles = [copy.deepcopy(s) for s in (self.document.styles or [])]
        if not self._styles:
            self._styles = [ASSStyle()]

        self._selected_style_index = 0
        self._updating_style_ui = False
        # old name -> new name for styles renamed during this edit; applied
        # on Apply so dialogue entries keep referencing the renamed style.
        self._renames: dict = {}

        # --- Style selector (dropdown) ---
        self._style_model = Gtk.StringList.new([s.name for s in self._styles])
        self.style_combo.set_model(self._style_model)
        self.style_combo.set_selected(self._selected_style_index)
        self.style_combo.connect('notify::selected', self._on_style_selected)

        # Font family dropdown. Always include a style's real font name even if
        # it isn't installed locally, so we never silently overwrite it on save.
        self._installed_fonts = sorted(
            f.get_name() for f in PangoCairo.FontMap.get_default().list_families()
        )
        self._font_families = merge_font_families(
            self._installed_fonts,
            (s.fontname for s in self._styles),
        )
        self._font_model = Gtk.StringList.new(self._font_families)
        self.style_font.set_model(self._font_model)
        self.style_font.connect('notify::selected', self._on_style_field_changed)

        self.style_name.connect('notify::text', self._on_style_field_changed)
        self.style_fontsize.connect('notify::value', self._on_style_field_changed)

        # Color pickers — wired here; the ColorDialog(with-alpha) is in the template.
        self._primary_color_btn = self.primary_color_btn
        self._outline_color_btn = self.outline_color_btn
        self._back_color_btn = self.back_color_btn
        self._secondary_color_btn = self.secondary_color_btn
        self._primary_color_btn.connect('notify::rgba', lambda *a: self._on_color_changed('primary'))
        self._outline_color_btn.connect('notify::rgba', lambda *a: self._on_color_changed('outline'))
        self._back_color_btn.connect('notify::rgba', lambda *a: self._on_color_changed('back'))
        self._secondary_color_btn.connect('notify::rgba', lambda *a: self._on_color_changed('secondary'))

        self.style_bold.connect('notify::active', self._on_style_field_changed)
        self.style_italic.connect('notify::active', self._on_style_field_changed)
        self.style_underline.connect('notify::active', self._on_style_field_changed)
        self.style_strikeout.connect('notify::active', self._on_style_field_changed)
        self.style_spacing.connect('notify::value', self._on_style_field_changed)
        self.style_angle.connect('notify::value', self._on_style_field_changed)
        self.style_scale_x.connect('notify::value', self._on_style_field_changed)
        self.style_scale_y.connect('notify::value', self._on_style_field_changed)
        self.style_outline_width.connect('notify::value', self._on_style_field_changed)
        self.style_shadow.connect('notify::value', self._on_style_field_changed)
        self.style_margin_l.connect('notify::value', self._on_style_field_changed)
        self.style_margin_r.connect('notify::value', self._on_style_field_changed)
        self.style_margin_v.connect('notify::value', self._on_style_field_changed)

        # Semantic inputs for the enumerative fields: the alignment grid is
        # attached here (built in code); the combos are driven by the choice
        # tables, which also represent unknown stored encodings as "(custom)".
        self.alignment_grid = AlignmentGrid()
        self.alignment_grid.set_valign(Gtk.Align.CENTER)
        self.style_alignment.add_suffix(self.alignment_grid)
        self.alignment_grid.connect('value-changed', self._on_style_field_changed)

        self._border_style_choice = ChoiceRow(self.style_border_style, BORDER_STYLE_CHOICES)
        self._encoding_choice = ChoiceRow(self.style_encoding, ENCODING_CHOICES)
        self._border_style_choice.connect_changed(self._on_style_field_changed)
        self._encoding_choice.connect_changed(self._on_style_field_changed)

        self._load_style_into_editor()
        self._update_preview()

    @Gtk.Template.Callback()
    def on_cancel_clicked(self, _button):
        self.close()

    # --- Style selection (dropdown) --------------------------------------

    def _set_selected_style_index(self, idx: int) -> None:
        if not (0 <= idx < len(self._styles)):
            return
        self._selected_style_index = idx
        self._updating_style_ui = True
        try:
            self.style_combo.set_selected(idx)
        finally:
            self._updating_style_ui = False

    def _on_style_selected(self, _row, _pspec) -> None:
        if self._updating_style_ui:
            return
        idx = int(self.style_combo.get_selected())
        if 0 <= idx < len(self._styles):
            self._selected_style_index = idx
            self._load_style_into_editor()

    # --- Editor loading / field changes -----------------------------------

    def _load_style_into_editor(self):
        style = self._styles[self._selected_style_index]
        self._updating_style_ui = True
        try:
            self.style_name.set_text(style.name)
            try:
                font_idx = self._font_families.index(style.fontname)
            except ValueError:
                font_idx = 0
            self.style_font.set_selected(font_idx)
            self.style_fontsize.set_value(style.fontsize)
            self._update_font_warning(style.fontname)
            # Colors
            self._primary_color_btn.set_rgba(self._ass_color_to_rgba(style.primary_color) or Gdk.RGBA(1, 1, 1, 1))
            self._outline_color_btn.set_rgba(self._ass_color_to_rgba(style.outline_color) or Gdk.RGBA(0, 0, 0, 1))
            self._back_color_btn.set_rgba(self._ass_color_to_rgba(style.back_color) or Gdk.RGBA(0.95, 0.95, 0.95, 1))
            self.style_bold.set_active(bool(style.bold))
            self.style_italic.set_active(bool(style.italic))
            self.style_underline.set_active(bool(style.underline))
            self.style_strikeout.set_active(bool(style.strikeout))
            self.style_spacing.set_value(float(style.spacing))
            self.style_angle.set_value(float(style.angle))
            self._secondary_color_btn.set_rgba(self._ass_color_to_rgba(style.secondary_color) or Gdk.RGBA(0, 0, 0, 1))
            self.alignment_grid.set_value(int(style.alignment))
            self._border_style_choice.set_value(int(style.border_style))
            self.style_margin_l.set_value(int(style.margin_l))
            self.style_margin_r.set_value(int(style.margin_r))
            self.style_margin_v.set_value(int(style.margin_v))
            self._encoding_choice.set_value(int(style.encoding))
            self.style_scale_x.set_value(float(style.scale_x))
            self.style_scale_y.set_value(float(style.scale_y))
            self.style_outline_width.set_value(float(style.outline))
            self.style_shadow.set_value(float(style.shadow))
        finally:
            self._updating_style_ui = False

        self._update_preview()

    def _update_font_warning(self, fontname: str) -> None:
        """Show a note when the selected style's font is not installed locally."""
        if self.font_warning is None:
            return
        if is_font_installed(fontname, self._installed_fonts):
            self.font_warning.set_visible(False)
            self.font_warning.set_text("")
        else:
            self.font_warning.set_visible(True)
            self.font_warning.set_text(
                f"Font “{fontname}” is not installed on this system — the "
                f"preview may differ and it will be kept as-is in the file."
            )

    def _on_style_field_changed(self, *args):
        if self._updating_style_ui:
            return

        style = self._styles[self._selected_style_index]
        prev_name = style.name

        name = self.style_name.get_text().strip()
        new_name = name or prev_name or "Default"
        style.name = new_name

        font_idx = int(self.style_font.get_selected())
        selected = self.style_font.get_selected_item()
        if selected is not None:
            style.fontname = selected.get_string()
        elif 0 <= font_idx < len(self._font_families):
            style.fontname = self._font_families[font_idx]
        style.fontsize = int(self.style_fontsize.get_value())
        style.bold = bool(self.style_bold.get_active())
        style.italic = bool(self.style_italic.get_active())
        style.underline = bool(self.style_underline.get_active())
        style.strikeout = bool(self.style_strikeout.get_active())
        style.spacing = float(self.style_spacing.get_value())
        style.angle = float(self.style_angle.get_value())
        style.alignment = int(self.alignment_grid.get_value())
        style.border_style = int(self._border_style_choice.get_value())
        style.margin_l = int(self.style_margin_l.get_value())
        style.margin_r = int(self.style_margin_r.get_value())
        style.margin_v = int(self.style_margin_v.get_value())
        style.encoding = int(self._encoding_choice.get_value())
        style.scale_x = float(self.style_scale_x.get_value())
        style.scale_y = float(self.style_scale_y.get_value())
        style.outline = float(self.style_outline_width.get_value())
        style.shadow = float(self.style_shadow.get_value())

        # Keep the dropdown label in sync when the name changes.
        if new_name != prev_name:
            self._style_model.splice(self._selected_style_index, 1, [new_name])
            self._record_rename(prev_name, new_name)

        self._update_font_warning(style.fontname)
        self._update_preview()

    def _record_rename(self, old_name: str, new_name: str) -> None:
        """Track a style rename, resolving chains (a→b then b→c to a→c)."""
        for prev_old, prev_new in list(self._renames.items()):
            if prev_new == old_name:
                self._renames[prev_old] = new_name
        self._renames[old_name] = new_name

    # --- Add / remove ------------------------------------------------------

    @Gtk.Template.Callback()
    def on_add_style(self, _button):
        existing = {s.name for s in self._styles}
        n = len(self._styles) + 1
        name = f"Style{n}"
        while name in existing:
            n += 1
            name = f"Style{n}"
        new_style = ASSStyle(name=name)
        self._styles.append(new_style)
        self._style_model.splice(self._style_model.get_n_items(), 0, [new_style.name])
        self._set_selected_style_index(len(self._styles) - 1)
        self._load_style_into_editor()

    @Gtk.Template.Callback()
    def on_remove_style(self, _button):
        if len(self._styles) <= 1:
            self.parent_window._show_toast("At least one style is required")
            return
        self._confirm_remove_style()

    def _fallback_style_name(self) -> str:
        """Name shown as the removal fallback: prefer a style literally named
        'Default', then any other surviving style — never the removed one."""
        removed = self._styles[self._selected_style_index]
        others = [s for s in self._styles if s is not removed]
        return next((s.name for s in others if s.name == 'Default'),
                    others[0].name if others else 'Default')

    def _confirm_remove_style(self) -> None:
        style = self._styles[self._selected_style_index]
        fallback = self._fallback_style_name()
        dialog = Adw.AlertDialog(
            heading=_("Remove style “%s”?") % style.name,
            body=_("Subtitles that use this style will switch to “%s”. "
                   "You can undo this after applying.") % fallback,
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("remove", _("Remove"))
        dialog.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", self._on_remove_response)
        dialog.present(self)

    def _on_remove_response(self, _dialog, response: str) -> None:
        if response != "remove":
            return
        if len(self._styles) <= 1:
            return
        idx = self._selected_style_index
        self._styles.pop(idx)
        self._style_model.splice(idx, 1, [])
        self._set_selected_style_index(max(0, idx - 1))
        self._load_style_into_editor()

    def _on_color_changed(self, which: str) -> None:
        if self._updating_style_ui:
            return
        style = self._styles[self._selected_style_index]
        if which == 'primary':
            style.primary_color = self._rgba_to_ass_color(self._primary_color_btn.get_rgba())
        elif which == 'outline':
            style.outline_color = self._rgba_to_ass_color(self._outline_color_btn.get_rgba())
        elif which == 'back':
            style.back_color = self._rgba_to_ass_color(self._back_color_btn.get_rgba())
        elif which == 'secondary':
            style.secondary_color = self._rgba_to_ass_color(self._secondary_color_btn.get_rgba())
        self._update_preview()

    # --- Colour helpers ----------------------------------------------------

    def _ass_color_to_rgba(self, ass_color: str) -> Gdk.RGBA | None:
        """Parse ASS color string (&HAABBGGRR or &HBBGGRR) to Gdk.RGBA."""
        return ass_color_to_rgba(ass_color)

    def _rgba_to_css(self, rgba: Gdk.RGBA) -> str:
        return rgba_to_css(rgba)

    def _rgba_to_ass_color(self, rgba: Gdk.RGBA) -> str:
        """Convert RGBA to ASS &HAABBGGRR (AA inverted alpha)."""
        return rgba_to_ass_color(rgba)

    # --- Preview -----------------------------------------------------------

    def _update_preview(self) -> None:
        if not hasattr(self, 'preview_label'):
            return
        if not hasattr(self, '_preview_css_provider'):
            self._preview_css_provider = Gtk.CssProvider()
            Gtk.StyleContext.add_provider_for_display(
                Gdk.Display.get_default(),
                self._preview_css_provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )
        try:
            style = self._styles[self._selected_style_index]
        except IndexError:
            return
        update_ass_preview(self.preview_label, self._preview_css_provider, style)

    # --- Apply -------------------------------------------------------------

    @Gtk.Template.Callback()
    def on_apply(self, _button):
        # Validate names over ALL styles: non-empty, no commas (the Style line
        # is comma-separated, so a comma would corrupt the file), no duplicates.
        names = []
        for s in self._styles:
            name = (s.name or "").strip()
            if not name:
                self.parent_window._show_toast("Style names must not be empty")
                return
            if "," in name:
                self.parent_window._show_toast(
                    f"Style name “{name}” must not contain commas")
                return
            names.append(name)
        if len(set(names)) != len(names):
            self.parent_window._show_toast("Style names must be unique")
            return

        # Sanitize every edited style defensively before applying.
        sanitized = [ASSStyle.from_fields(s.to_fields()) for s in self._styles]

        cmd = ReplaceASSHeaderCommand(
            self.document,
            metadata=self.document.metadata,
            aegisub_project_garbage=getattr(self.document, 'aegisub_project_garbage', {}),
            styles=sanitized,
            fallback_style='Default',
            style_renames=self._renames,
        )
        self.parent_window.command_manager.execute(cmd)

        # Update per-entry style dropdown options in editor panel
        style_names = [s.name for s in (self.document.styles or [])]
        self.parent_window.editor_panel.set_document_context(self.document.format, style_names)

        self.parent_window.subtitle_list.refresh(preserve_selection=True)
        self.parent_window._update_title()
        self.parent_window._update_undo_redo_buttons()
        self.parent_window._refresh_video_preview()
        self.parent_window._show_toast("Updated ASS styles")

        self.close()


@Gtk.Template(resource_path=template_resource_path('track-selection'))
class TrackSelectionDialog(Adw.Dialog):
    """Dialog for selecting audio and subtitle tracks from a video file."""

    __gtype_name__ = 'GsubTrackSelectionDialog'

    __gsignals__ = {
        "tracks-selected": (GObject.SignalFlags.RUN_FIRST, None, (int, int)),
        # (audio_track_index, subtitle_track_index) - both can be -1 for "none"
    }

    audio_group = Gtk.Template.Child()
    subtitle_group = Gtk.Template.Child()
    extract_group = Gtk.Template.Child()
    extract_row = Gtk.Template.Child()

    def __init__(self, parent, audio_tracks, subtitle_tracks, current_audio=-1, current_subtitle=-1):
        """
        Initialize track selection dialog.

        Args:
            parent: Parent window
            audio_tracks: List of dicts with 'index', 'title', 'language', 'codec'
            subtitle_tracks: List of dicts with 'index', 'title', 'language', 'codec'
            current_audio: Currently selected audio track index
            current_subtitle: Currently selected subtitle track index
        """
        super().__init__()

        self.parent_window = parent

        self.audio_tracks = audio_tracks
        self.subtitle_tracks = subtitle_tracks
        self.selected_audio = current_audio
        self.selected_subtitle = current_subtitle

        self.audio_group.set_description(
            f"Select an audio track ({len(audio_tracks)} available)"
        )
        self.subtitle_group.set_description(
            f"Select a subtitle track ({len(subtitle_tracks)} available)"
        )

        # Create radio buttons for audio tracks
        self.audio_check_group = []
        for i, track in enumerate(audio_tracks):
            row = Adw.ActionRow()

            # Track dictionaries are produced by libmpv track discovery
            # (see VideoPlayerWidget.get_available_tracks).
            track_index = track.get('index', 0)
            track_title = track.get('title') or f"Track {track_index + 1}"
            track_language = track.get('language')
            track_codec = track.get('codec')

            # Escape ampersands in title to prevent markup parsing errors
            title = track_title.replace('&', '&amp;')
            row.set_title(title)

            # Build subtitle with language and codec info
            subtitle_parts = []
            if track_language:
                subtitle_parts.append(track_language)
            if track_codec:
                subtitle_parts.append(track_codec)
            if subtitle_parts:
                row.set_subtitle(", ".join(subtitle_parts))

            # Radio button
            check = Gtk.CheckButton()
            check.set_active(track_index == current_audio)
            check.connect("toggled", self._on_audio_track_selected, track_index)

            # Group radio buttons
            if self.audio_check_group:
                check.set_group(self.audio_check_group[0])
            self.audio_check_group.append(check)

            row.add_prefix(check)
            row.set_activatable_widget(check)
            self.audio_group.add(row)

        # "None" option for subtitles
        none_row = Adw.ActionRow()
        none_row.set_title("None")
        none_row.set_subtitle("No embedded subtitles")
        none_check = Gtk.CheckButton()
        none_check.set_active(current_subtitle == -1)
        none_check.connect("toggled", self._on_subtitle_track_selected, -1)
        none_row.add_prefix(none_check)
        none_row.set_activatable_widget(none_check)
        self.subtitle_group.add(none_row)

        self.subtitle_check_group = [none_check]

        # Create radio buttons for subtitle tracks
        for i, track in enumerate(subtitle_tracks):
            row = Adw.ActionRow()

            # Track dictionaries are produced by libmpv track discovery
            # (see VideoPlayerWidget.get_available_tracks).
            track_index = track.get('index', 0)
            track_title = track.get('title') or f"Track {track_index + 1}"
            track_language = track.get('language')
            track_codec = track.get('codec')

            # Escape ampersands in title to prevent markup parsing errors
            title = track_title.replace('&', '&amp;')
            row.set_title(title)

            # Build subtitle with language and codec info
            subtitle_parts = []
            if track_language:
                subtitle_parts.append(track_language)
            if track_codec:
                subtitle_parts.append(track_codec)
            if subtitle_parts:
                row.set_subtitle(", ".join(subtitle_parts))

            # Radio button
            check = Gtk.CheckButton()
            check.set_active(track_index == current_subtitle)
            check.connect("toggled", self._on_subtitle_track_selected, track_index)
            check.set_group(none_check)
            self.subtitle_check_group.append(check)

            row.add_prefix(check)
            row.set_activatable_widget(check)
            self.subtitle_group.add(row)

        # The extract switch only makes sense when an embedded subtitle track
        # can be chosen; sync its visibility/sensitivity to the selection.
        self._update_extract_row()

    def _update_extract_row(self):
        """Show the extract switch only when embedded subtitle tracks exist,
        and enable it only while a concrete track (not "None") is selected."""
        has_subs = bool(self.subtitle_tracks)
        self.extract_group.set_visible(has_subs)
        self.extract_row.set_visible(has_subs)
        self.extract_row.set_sensitive(self.selected_subtitle >= 0)
        if self.selected_subtitle < 0:
            # Extraction is meaningless without a concrete track; keep the
            # switch OFF so the reported state stays consistent.
            self.extract_row.set_active(False)

    def get_extract_selected(self) -> bool:
        """Whether the user asked to load the selected subtitle track for
        editing (extraction) in addition to applying the track selection."""
        return self.extract_row.get_active()

    def _on_audio_track_selected(self, check_button, track_index):
        """Handle audio track selection."""
        if check_button.get_active():
            self.selected_audio = track_index

    def _on_subtitle_track_selected(self, check_button, track_index):
        """Handle subtitle track selection."""
        if check_button.get_active():
            self.selected_subtitle = track_index
            self._update_extract_row()

    @Gtk.Template.Callback()
    def on_cancel_clicked(self, _button):
        self.close()

    @Gtk.Template.Callback()
    def on_select_clicked(self, _button):
        """Handle select button click."""
        self.emit("tracks-selected", self.selected_audio, self.selected_subtitle)
        self.close()


# The shortcut list itself lives in subtitle_editor.shortcuts (the single
# source of truth shared with the accel registration in the main window).
# Accelerators use GTK accelerator syntax (see gtk_accelerator_parse), which
# AdwShortcutsItem renders with proper Adwaita keycaps.
def build_shortcuts_dialog() -> Adw.ShortcutsDialog:
    """Build a keyboard shortcuts dialog using libadwaita's AdwShortcutsDialog.

    Sections and items come from the shared shortcut table in
    subtitle_editor.shortcuts, so the dialog always matches the accels
    registered by the main window.

    AdwShortcutsDialog is a final type and cannot be subclassed, so the dialog
    is constructed directly and populated with sections and items. This follows
    the Adwaita design (GNOME 49 / libadwaita 1.8+): proper keycap rendering
    via AdwShortcutLabel and an integrated search field.
    """
    dialog = Adw.ShortcutsDialog(title=_("Keyboard Shortcuts"))

    for section_title in SECTION_ORDER:
        shortcuts = entries_for_section(section_title)
        if not shortcuts:
            continue
        section = Adw.ShortcutsSection(title=_(section_title))
        for shortcut in shortcuts:
            # AdwShortcutsItem renders multiple accels separated by spaces.
            section.add(Adw.ShortcutsItem(
                title=_(shortcut.title),
                accelerator=" ".join(shortcut.accels),
            ))
        dialog.add(section)

    return dialog
