"""
Dialog widgets for the subtitle editor.
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
gi.require_version('PangoCairo', '1.0')

from gi.repository import Gtk, Adw, Pango, PangoCairo, Gdk, GObject
from subtitle_editor.commands import TimeShiftCommand, ReplaceASSHeaderCommand, BulkEditStyleCommand
from subtitle_editor.models import ASSStyle
from subtitle_editor.resources import template_resource_path
from subtitle_editor.utils import merge_font_families, is_font_installed
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
        self.style_alignment.connect('notify::value', self._on_style_field_changed)

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
            self.style_border_style.set_value(int(style.border_style))
            self.style_margin_l.set_value(int(style.margin_l))
            self.style_margin_r.set_value(int(style.margin_r))
            self.style_margin_v.set_value(int(style.margin_v))
            self.style_encoding.set_value(int(style.encoding))
            self.style_scale_x.set_value(float(style.scale_x))
            self.style_scale_y.set_value(float(style.scale_y))
            self.style_outline_width.set_value(float(style.outline))
            self.style_shadow.set_value(float(style.shadow))
            self.style_alignment.set_value(int(style.alignment))
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
        style.border_style = int(self.style_border_style.get_value())
        style.margin_l = int(self.style_margin_l.get_value())
        style.margin_r = int(self.style_margin_r.get_value())
        style.margin_v = int(self.style_margin_v.get_value())
        style.encoding = int(self.style_encoding.get_value())
        style.scale_x = float(self.style_scale_x.get_value())
        style.scale_y = float(self.style_scale_y.get_value())
        style.outline = float(self.style_outline_width.get_value())
        style.shadow = float(self.style_shadow.get_value())
        style.alignment = int(self.style_alignment.get_value())

        # Keep the dropdown label in sync when the name changes.
        if new_name != prev_name:
            self._style_model.splice(self._selected_style_index, 1, [new_name])

        self._update_font_warning(style.fontname)
        self._update_preview()

    # --- Add / remove ------------------------------------------------------

    @Gtk.Template.Callback()
    def on_add_style(self, _button):
        new_style = ASSStyle(name=f"Style{len(self._styles) + 1}")
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
        return next((s.name for s in self._styles if s.name == 'Default'),
                    self._styles[0].name if self._styles else 'Default')

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
        if not ass_color:
            return None
        s = str(ass_color).strip().upper()
        if not s.startswith('&H'):
            return None
        hexpart = s[2:]
        if hexpart.endswith('&'):
            hexpart = hexpart[:-1]
        if len(hexpart) <= 6:
            aa = 0
            hexpart = hexpart.zfill(6)
        else:
            aa = int(hexpart[:-6].zfill(2)[-2:], 16)
            hexpart = hexpart[-6:]

        bb = int(hexpart[0:2], 16)
        gg = int(hexpart[2:4], 16)
        rr = int(hexpart[4:6], 16)
        alpha = 1.0 - (aa / 255.0)

        rgba = Gdk.RGBA()
        rgba.red = rr / 255.0
        rgba.green = gg / 255.0
        rgba.blue = bb / 255.0
        rgba.alpha = alpha
        return rgba

    def _rgba_to_css(self, rgba: Gdk.RGBA) -> str:
        r = int(rgba.red * 255)
        g = int(rgba.green * 255)
        b = int(rgba.blue * 255)
        a = rgba.alpha
        return f"rgba({r},{g},{b},{a:.3f})"

    def _rgba_to_ass_color(self, rgba: Gdk.RGBA) -> str:
        """Convert RGBA to ASS &HAABBGGRR (AA inverted alpha)."""
        rr = int(max(0, min(255, round(rgba.red * 255))))
        gg = int(max(0, min(255, round(rgba.green * 255))))
        bb = int(max(0, min(255, round(rgba.blue * 255))))
        aa = int(max(0, min(255, round((1.0 - rgba.alpha) * 255))))
        return f"&H{aa:02X}{bb:02X}{gg:02X}{rr:02X}"

    # --- Preview -----------------------------------------------------------

    def _update_preview(self) -> None:
        if not hasattr(self, 'preview_label'):
            return
        try:
            style = self._styles[self._selected_style_index]

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
            self.preview_label.set_attributes(attrs)

            fg = self._ass_color_to_rgba(getattr(style, 'primary_color', None) or '')
            bg = self._ass_color_to_rgba(getattr(style, 'back_color', None) or '') or Gdk.RGBA(0.95, 0.95, 0.95, 1)
            outline_col = self._ass_color_to_rgba(getattr(style, 'outline_color', None) or '') or Gdk.RGBA(0, 0, 0, 1)

            border_style = int(getattr(style, 'border_style', 1) or 1)
            try:
                angle = float(getattr(style, 'angle', 0.0) or 0.0)
            except Exception:
                angle = 0.0
            try:
                margin_l = int(getattr(style, 'margin_l', 0) or 0)
                margin_r = int(getattr(style, 'margin_r', 0) or 0)
                margin_v = int(getattr(style, 'margin_v', 0) or 0)
            except Exception:
                margin_l = margin_r = margin_v = 0

            css = ""

            label_props = []
            if fg is not None:
                label_props.append(f"color: {self._rgba_to_css(fg)}")

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
                frame_props.append(f"background-color: {self._rgba_to_css(bg)}")
            else:
                frame_props.append("background-color: rgba(127, 127, 127, 0.18)")
            css += f".ass-preview-frame {{ {'; '.join(frame_props)}; padding: 12px; border-radius: 8px; }}\n"

            shadows = []
            ocss = self._rgba_to_css(outline_col) if outline_col is not None else None

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

            if not hasattr(self, '_preview_css_provider'):
                self._preview_css_provider = Gtk.CssProvider()
                Gtk.StyleContext.add_provider_for_display(
                    Gdk.Display.get_default(),
                    self._preview_css_provider,
                    Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
                )

            self._preview_css_provider.load_from_data(css.encode('utf-8'))

        except Exception:
            self.preview_label.set_attributes(None)

    # --- Apply -------------------------------------------------------------

    @Gtk.Template.Callback()
    def on_apply(self, _button):
        names = [s.name.strip() for s in self._styles if s.name and s.name.strip()]
        if len(set(names)) != len(names):
            self.parent_window._show_toast("Style names must be unique")
            return

        # Sanitize every edited style defensively before applying.
        sanitized = []
        for style in self._styles:
            fields = {
                'name': style.name,
                'fontname': style.fontname,
                'fontsize': str(style.fontsize),
                'primarycolour': style.primary_color,
                'secondarycolour': style.secondary_color,
                'outlinecolour': style.outline_color,
                'backcolour': style.back_color,
                'bold': '-1' if style.bold else '0',
                'italic': '-1' if style.italic else '0',
                'underline': '-1' if style.underline else '0',
                'strikeout': '-1' if style.strikeout else '0',
                'scalex': str(style.scale_x),
                'scaley': str(style.scale_y),
                'spacing': str(style.spacing),
                'angle': str(style.angle),
                'borderstyle': str(style.border_style),
                'outline': str(style.outline),
                'shadow': str(style.shadow),
                'alignment': str(style.alignment),
                'marginl': str(style.margin_l),
                'marginr': str(style.margin_r),
                'marginv': str(style.margin_v),
                'encoding': str(style.encoding),
            }
            sanitized.append(ASSStyle.from_fields(fields))

        cmd = ReplaceASSHeaderCommand(
            self.document,
            metadata=self.document.metadata,
            aegisub_project_garbage=getattr(self.document, 'aegisub_project_garbage', {}),
            styles=sanitized,
            fallback_style='Default',
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

    def _on_audio_track_selected(self, check_button, track_index):
        """Handle audio track selection."""
        if check_button.get_active():
            self.selected_audio = track_index

    def _on_subtitle_track_selected(self, check_button, track_index):
        """Handle subtitle track selection."""
        if check_button.get_active():
            self.selected_subtitle = track_index

    @Gtk.Template.Callback()
    def on_cancel_clicked(self, _button):
        self.close()

    @Gtk.Template.Callback()
    def on_select_clicked(self, _button):
        """Handle select button click."""
        self.emit("tracks-selected", self.selected_audio, self.selected_subtitle)
        self.close()


# (section_title, [(action_title, accelerator_display), ...])
# Accelerators use GTK accelerator syntax (see gtk_accelerator_parse), which
# AdwShortcutsItem renders with proper Adwaita keycaps.
SHORTCUTS = [
    (_("File"), [
        (_("New"), "<Ctrl>N"),
        (_("Open…"), "<Ctrl>O"),
        (_("Save"), "<Ctrl>S"),
        (_("Save As…"), "<Ctrl><Shift>S"),
    ]),
    (_("Editing"), [
        (_("Undo"), "<Ctrl>Z"),
        (_("Redo"), "<Ctrl><Shift>Z"),
        (_("Add Subtitle"), "<Ctrl><Shift>N"),
        (_("Remove Subtitle"), "Delete"),
        (_("Duplicate Subtitle"), "<Ctrl>D"),
        (_("Move Up"), "<Ctrl>Up"),
        (_("Move Down"), "<Ctrl>Down"),
    ]),
    (_("Video"), [
        (_("Open Video…"), "<Ctrl><Shift>O"),
        (_("Toggle Video Player"), "<Ctrl>V"),
        (_("Select Audio/Subtitle Tracks…"), "<Ctrl><Shift>T"),
    ]),
    (_("Navigation"), [
        (_("Home"), "<Alt>Home"),
        (_("Keyboard Shortcuts"), "<Ctrl>question"),
    ]),
]


def build_shortcuts_dialog() -> Adw.ShortcutsDialog:
    """Build a keyboard shortcuts dialog using libadwaita's AdwShortcutsDialog.

    AdwShortcutsDialog is a final type and cannot be subclassed, so the dialog
    is constructed directly and populated with sections and items. This follows
    the Adwaita design (GNOME 49 / libadwaita 1.8+): proper keycap rendering
    via AdwShortcutLabel and an integrated search field.
    """
    dialog = Adw.ShortcutsDialog(title=_("Keyboard Shortcuts"))

    for section_title, items in SHORTCUTS:
        section = Adw.ShortcutsSection(title=section_title)
        for title, accel in items:
            section.add(Adw.ShortcutsItem(title=title, accelerator=accel))
        dialog.add(section)

    return dialog
