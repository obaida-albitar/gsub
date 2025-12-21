"""
Dialog widgets for the subtitle editor.
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
gi.require_version('PangoCairo', '1.0')

from gi.repository import Gtk, Adw, Pango, PangoCairo
from subtitle_editor.commands import TimeShiftCommand, ReplaceASSHeaderCommand, BulkEditStyleCommand
from subtitle_editor.models import ASSStyle
import copy


class TimeShiftDialog(Adw.Dialog):
    """Dialog for shifting subtitle timing."""
    
    def __init__(self, parent_window):
        super().__init__()
        
        self.parent_window = parent_window
        self.document = parent_window.document
        
        # Set up dialog - larger size to show all content
        self.set_title("Time Shift")
        self.set_content_width(520)
        self.set_content_height(650)
        
        # Use toolbar view for modern layout
        toolbar_view = Adw.ToolbarView()
        self.set_child(toolbar_view)
        
        # Header bar
        header = Adw.HeaderBar()
        header.set_show_title(False)
        toolbar_view.add_top_bar(header)
        
        cancel_button = Gtk.Button(label="Cancel")
        cancel_button.connect('clicked', lambda b: self.close())
        header.pack_start(cancel_button)
        
        apply_button = Gtk.Button(label="Apply")
        apply_button.add_css_class("suggested-action")
        apply_button.connect('clicked', self._on_apply)
        header.pack_end(apply_button)
        
        # Preferences page as content
        prefs_page = Adw.PreferencesPage()
        prefs_page.set_vexpand(True)
        toolbar_view.set_content(prefs_page)
        
        # Time shift group
        shift_group = Adw.PreferencesGroup()
        shift_group.set_title("Offset")
        shift_group.set_description("Shift subtitles forward or backward in time")
        prefs_page.add(shift_group)
        
        # Offset input using SpinRow for modern look
        self.offset_row = Adw.SpinRow.new_with_range(-3600000, 3600000, 100)
        self.offset_row.set_title("Time Offset")
        self.offset_row.set_subtitle("Milliseconds (negative for backward)")
        self.offset_row.set_value(0)
        self.offset_row.set_digits(0)
        self.offset_row.set_numeric(True)
        shift_group.add(self.offset_row)
        
        # Quick presets with better layout
        presets_group = Adw.PreferencesGroup()
        presets_group.set_title("Quick Adjustments")
        presets_group.set_description("Common time shift values")
        prefs_page.add(presets_group)
        
        # Preset buttons in a flow box for better wrapping
        preset_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        preset_box.set_margin_top(12)
        preset_box.set_margin_bottom(12)
        preset_box.set_margin_start(12)
        preset_box.set_margin_end(12)
        
        # Row 1: Backward adjustments
        back_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        back_box.set_halign(Gtk.Align.CENTER)
        back_label = Gtk.Label(label="Shift Backward:")
        back_label.add_css_class("caption")
        back_box.append(back_label)
        
        for label, value in [("-5s", -5000), ("-1s", -1000), ("-100ms", -100)]:
            button = Gtk.Button(label=label)
            button.connect('clicked', lambda b, v=value: self.offset_row.set_value(self.offset_row.get_value() + v))
            back_box.append(button)
        
        preset_box.append(back_box)
        
        # Row 2: Forward adjustments
        forward_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        forward_box.set_halign(Gtk.Align.CENTER)
        forward_label = Gtk.Label(label="Shift Forward:")
        forward_label.add_css_class("caption")
        forward_box.append(forward_label)
        
        for label, value in [("+100ms", 100), ("+1s", 1000), ("+5s", 5000)]:
            button = Gtk.Button(label=label)
            button.add_css_class("suggested-action")
            button.connect('clicked', lambda b, v=value: self.offset_row.set_value(self.offset_row.get_value() + v))
            forward_box.append(button)
        
        preset_box.append(forward_box)
        
        presets_group.add(preset_box)
        
        # Scope group with better styling
        scope_group = Adw.PreferencesGroup()
        scope_group.set_title("Apply To")
        scope_group.set_description("Choose which subtitles to shift")
        prefs_page.add(scope_group)
        
        # Radio buttons for scope with icons
        self.scope_all = Gtk.CheckButton()
        self.scope_all.set_active(True)
        scope_all_row = Adw.ActionRow()
        scope_all_row.set_title("All Subtitles")
        scope_all_row.set_subtitle("Shift the entire subtitle track")
        all_icon = Gtk.Image.new_from_icon_name("view-list-symbolic")
        scope_all_row.add_prefix(all_icon)
        scope_all_row.add_prefix(self.scope_all)
        scope_all_row.set_activatable_widget(self.scope_all)
        scope_group.add(scope_all_row)
        
        self.scope_selected = Gtk.CheckButton()
        self.scope_selected.set_group(self.scope_all)
        scope_selected_row = Adw.ActionRow()
        scope_selected_row.set_title("Selected Only")
        scope_selected_row.set_subtitle("Shift only the currently selected subtitle")
        selected_icon = Gtk.Image.new_from_icon_name("edit-select-symbolic")
        scope_selected_row.add_prefix(selected_icon)
        scope_selected_row.add_prefix(self.scope_selected)
        scope_selected_row.set_activatable_widget(self.scope_selected)
        scope_group.add(scope_selected_row)
        
        self.scope_from = Gtk.CheckButton()
        self.scope_from.set_group(self.scope_all)
        scope_from_row = Adw.ActionRow()
        scope_from_row.set_title("From Selected to End")
        scope_from_row.set_subtitle("Shift all subtitles after the selected one")
        from_icon = Gtk.Image.new_from_icon_name("go-next-symbolic")
        scope_from_row.add_prefix(from_icon)
        scope_from_row.add_prefix(self.scope_from)
        scope_from_row.set_activatable_widget(self.scope_from)
        scope_group.add(scope_from_row)
    
    def _on_apply(self, button):
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
        self.parent_window._show_toast(f"Time shifted by {offset_ms}ms")
        
        self.close()


class BulkApplyStyleDialog(Adw.Dialog):
    """Dialog to apply a style to multiple subtitle entries (ASS/SSA)."""

    def __init__(self, parent_window):
        super().__init__()
        self.parent_window = parent_window
        self.document = parent_window.document

        self.set_title("Bulk Apply Style")
        self.set_content_width(520)
        self.set_content_height(420)

        toolbar_view = Adw.ToolbarView()
        self.set_child(toolbar_view)

        header = Adw.HeaderBar()
        header.set_show_title(False)
        toolbar_view.add_top_bar(header)

        cancel_button = Gtk.Button(label="Cancel")
        cancel_button.connect('clicked', lambda b: self.close())
        header.pack_start(cancel_button)

        apply_button = Gtk.Button(label="Apply")
        apply_button.add_css_class("suggested-action")
        apply_button.connect('clicked', self._on_apply)
        header.pack_end(apply_button)

        prefs_page = Adw.PreferencesPage()
        prefs_page.set_vexpand(True)
        toolbar_view.set_content(prefs_page)

        group = Adw.PreferencesGroup()
        group.set_title("Style")
        group.set_description("Apply a style to many subtitles at once")
        prefs_page.add(group)

        style_names = [s.name for s in (self.document.styles or [])] or ['Default']
        self._style_names = style_names
        self._style_model = Gtk.StringList.new(style_names)

        self.style_row = Adw.ComboRow()
        self.style_row.set_title("Style")
        self.style_row.set_model(self._style_model)
        self.style_row.set_selected(0)
        group.add(self.style_row)

        scope_group = Adw.PreferencesGroup()
        scope_group.set_title("Scope")
        prefs_page.add(scope_group)

        self.scope_selected = Adw.ActionRow()
        self.scope_selected.set_title("Selected subtitles")
        self.scope_selected_check = Gtk.CheckButton()
        self.scope_selected_check.set_active(True)
        self.scope_selected.add_prefix(self.scope_selected_check)
        scope_group.add(self.scope_selected)

        self.scope_all = Adw.ActionRow()
        self.scope_all.set_title("All subtitles")
        self.scope_all_check = Gtk.CheckButton(group=self.scope_selected_check)
        self.scope_all.add_prefix(self.scope_all_check)
        scope_group.add(self.scope_all)

        self.scope_from = Adw.ActionRow()
        self.scope_from.set_title("From first selected to end")
        self.scope_from_check = Gtk.CheckButton(group=self.scope_selected_check)
        self.scope_from.add_prefix(self.scope_from_check)
        scope_group.add(self.scope_from)

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

    def _on_apply(self, _button):
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
        self.parent_window._show_toast(f"Applied style '{style_name}'")

        self.close()


class ASSInfoStylesDialog(Adw.Dialog):
    """Dialog to edit ASS/SSA Script Info metadata and style definitions."""

    COMMON_KEYS = [
        ('Title', 'Title'),
        ('ScriptType', 'Script Type'),
        ('WrapStyle', 'Wrap Style'),
        ('ScaledBorderAndShadow', 'Scaled Border And Shadow'),
        ('YCbCr Matrix', 'YCbCr Matrix'),
    ]

    def __init__(self, parent_window):
        super().__init__()
        self.parent_window = parent_window
        self.document = parent_window.document

        self.set_title("ASS/SSA Info & Styles")
        self.set_content_width(700)
        self.set_content_height(720)

        # Local editable copies
        self._metadata = copy.deepcopy(self.document.metadata or {})
        self._styles = [copy.deepcopy(s) for s in (self.document.styles or [])]
        if not self._styles:
            self._styles = [ASSStyle()]

        self._selected_style_index = 0
        self._updating_style_ui = False

        toolbar_view = Adw.ToolbarView()
        self.set_child(toolbar_view)

        header = Adw.HeaderBar()
        header.set_show_title(False)
        toolbar_view.add_top_bar(header)

        cancel_button = Gtk.Button(label="Cancel")
        cancel_button.connect('clicked', lambda b: self.close())
        header.pack_start(cancel_button)

        apply_button = Gtk.Button(label="Apply")
        apply_button.add_css_class("suggested-action")
        apply_button.connect('clicked', self._on_apply)
        header.pack_end(apply_button)

        prefs_page = Adw.PreferencesPage()
        prefs_page.set_vexpand(True)
        toolbar_view.set_content(prefs_page)

        # --- Script Info ---
        info_group = Adw.PreferencesGroup()
        info_group.set_title("Script Info")
        info_group.set_description("Metadata stored in the [Script Info] section")
        prefs_page.add(info_group)

        self._info_rows = {}
        for key, label in self.COMMON_KEYS:
            row = Adw.EntryRow()
            row.set_title(label)
            row.set_text(str(self._metadata.get(key, "")))
            info_group.add(row)
            self._info_rows[key] = row

        extra_row = Adw.ExpanderRow()
        extra_row.set_title("Additional metadata")
        extra_row.set_subtitle("One per line: Key: Value")
        info_group.add(extra_row)

        self.extra_buffer = Gtk.TextBuffer()
        self.extra_view = Gtk.TextView(buffer=self.extra_buffer)
        self.extra_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.extra_view.set_monospace(True)
        self.extra_view.set_size_request(-1, 120)

        common_set = {k for k, _ in self.COMMON_KEYS}
        extras = []
        for k in sorted(self._metadata.keys()):
            if k not in common_set:
                extras.append(f"{k}: {self._metadata[k]}")
        self.extra_buffer.set_text("\n".join(extras))

        extra_row.add_row(self.extra_view)

        # --- Styles ---
        styles_group = Adw.PreferencesGroup()
        styles_group.set_title("Styles")
        styles_group.set_description("Edit style definitions in [V4+ Styles]")
        prefs_page.add(styles_group)

        # Keep a persistent model to avoid signal feedback loops / freezes.
        self._style_model = Gtk.StringList.new([s.name for s in self._styles])

        self.style_combo = Adw.ComboRow()
        self.style_combo.set_title("Style")
        self.style_combo.set_model(self._style_model)
        self.style_combo.set_selected(self._selected_style_index)
        self.style_combo.connect('notify::selected', self._on_style_selected)
        styles_group.add(self.style_combo)

        buttons_row = Adw.ActionRow()
        buttons_row.set_title("Manage styles")

        add_btn = Gtk.Button()
        add_btn.set_icon_name("list-add-symbolic")
        add_btn.add_css_class("flat")
        add_btn.add_css_class("circular")
        add_btn.set_tooltip_text("Add style")
        add_btn.connect('clicked', self._on_add_style)

        remove_btn = Gtk.Button()
        remove_btn.set_icon_name("list-remove-symbolic")
        remove_btn.add_css_class("flat")
        remove_btn.add_css_class("circular")
        remove_btn.set_tooltip_text("Remove style")
        remove_btn.connect('clicked', self._on_remove_style)

        buttons_row.add_suffix(add_btn)
        buttons_row.add_suffix(remove_btn)
        buttons_row.set_activatable(False)
        styles_group.add(buttons_row)

        self.style_name = Adw.EntryRow()
        self.style_name.set_title("Name")
        self.style_name.connect('notify::text', self._on_style_field_changed)
        styles_group.add(self.style_name)

        # Font family dropdown
        self._font_families = sorted(
            [f.get_name() for f in PangoCairo.FontMap.get_default().list_families()]
        )
        self._font_model = Gtk.StringList.new(self._font_families)

        self.style_font = Adw.ComboRow()
        self.style_font.set_title("Font")
        self.style_font.set_model(self._font_model)
        self.style_font.connect('notify::selected', self._on_style_field_changed)
        styles_group.add(self.style_font)

        self.style_fontsize = Adw.SpinRow.new_with_range(1, 200, 1)
        self.style_fontsize.set_title("Font Size")
        self.style_fontsize.connect('notify::value', self._on_style_field_changed)
        styles_group.add(self.style_fontsize)

        self.style_primary = Adw.EntryRow()
        self.style_primary.set_title("Primary Colour")
        # Compatibility: some libadwaita versions lack set_subtitle()/set_placeholder_text() on EntryRow.
        self.style_primary.set_tooltip_text("ASS format e.g. &H00FFFFFF")
        self.style_primary.connect('notify::text', self._on_style_field_changed)
        styles_group.add(self.style_primary)

        self.style_outline = Adw.EntryRow()
        self.style_outline.set_title("Outline Colour")
        self.style_outline.set_tooltip_text("ASS format e.g. &H00000000")
        self.style_outline.connect('notify::text', self._on_style_field_changed)
        styles_group.add(self.style_outline)

        self.style_back = Adw.EntryRow()
        self.style_back.set_title("Back Colour")
        self.style_back.set_tooltip_text("ASS format e.g. &H00000000")
        self.style_back.connect('notify::text', self._on_style_field_changed)
        styles_group.add(self.style_back)

        self.style_bold = Adw.SwitchRow()
        self.style_bold.set_title("Bold")
        self.style_bold.connect('notify::active', self._on_style_field_changed)
        styles_group.add(self.style_bold)

        self.style_italic = Adw.SwitchRow()
        self.style_italic.set_title("Italic")
        self.style_italic.connect('notify::active', self._on_style_field_changed)
        styles_group.add(self.style_italic)

        self.style_outline_width = Adw.SpinRow.new_with_range(0, 20, 0.1)
        self.style_outline_width.set_title("Outline")
        self.style_outline_width.set_digits(1)
        self.style_outline_width.connect('notify::value', self._on_style_field_changed)
        styles_group.add(self.style_outline_width)

        self.style_shadow = Adw.SpinRow.new_with_range(0, 20, 0.1)
        self.style_shadow.set_title("Shadow")
        self.style_shadow.set_digits(1)
        self.style_shadow.connect('notify::value', self._on_style_field_changed)
        styles_group.add(self.style_shadow)

        self.style_alignment = Adw.SpinRow.new_with_range(1, 9, 1)
        self.style_alignment.set_title("Alignment")
        self.style_alignment.set_subtitle("1-9 (ASS alignment grid)")
        self.style_alignment.connect('notify::value', self._on_style_field_changed)
        styles_group.add(self.style_alignment)

        # Live preview
        preview_row = Adw.ActionRow()
        preview_row.set_title("Preview")
        preview_row.set_subtitle("Live sample for the selected style")
        preview_row.set_activatable(False)

        self.preview_label = Gtk.Label(label="The quick brown fox jumps over the lazy dog 0123456789")
        self.preview_label.set_xalign(0.0)
        self.preview_label.set_wrap(True)
        self.preview_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.preview_label.set_max_width_chars(40)
        preview_row.add_suffix(self.preview_label)
        styles_group.add(preview_row)

        self._load_style_into_editor()
        self._update_preview()

    def _set_selected_style_index(self, idx: int) -> None:
        if not (0 <= idx < len(self._styles)):
            return
        self._selected_style_index = idx
        self._updating_style_ui = True
        try:
            self.style_combo.set_selected(idx)
        finally:
            self._updating_style_ui = False

    def _sync_style_model_full(self) -> None:
        """Full resync of the style model (used after bulk changes)."""
        names = [s.name for s in self._styles]
        # Replace all contents
        self._style_model.splice(0, self._style_model.get_n_items(), names)
        self._set_selected_style_index(min(self._selected_style_index, len(self._styles) - 1))

    def _on_style_selected(self, _row, _pspec):
        if self._updating_style_ui:
            return
        idx = int(self.style_combo.get_selected())
        if 0 <= idx < len(self._styles):
            self._selected_style_index = idx
            self._load_style_into_editor()

    def _load_style_into_editor(self):
        style = self._styles[self._selected_style_index]
        self._updating_style_ui = True
        try:
            self.style_name.set_text(style.name)
            # Select font in dropdown (fallback to first item)
            try:
                font_idx = self._font_families.index(style.fontname)
            except ValueError:
                font_idx = 0
            self.style_font.set_selected(font_idx)
            self.style_fontsize.set_value(style.fontsize)
            self.style_primary.set_text(style.primary_color)
            self.style_outline.set_text(style.outline_color)
            self.style_back.set_text(style.back_color)
            self.style_bold.set_active(bool(style.bold))
            self.style_italic.set_active(bool(style.italic))
            self.style_outline_width.set_value(float(style.outline))
            self.style_shadow.set_value(float(style.shadow))
            self.style_alignment.set_value(int(style.alignment))
        finally:
            self._updating_style_ui = False

        self._update_preview()

    def _on_style_field_changed(self, *args):
        if self._updating_style_ui:
            return

        style = self._styles[self._selected_style_index]
        prev_name = style.name

        name = self.style_name.get_text().strip()
        new_name = name or prev_name or "Default"
        style.name = new_name
        # Read font from dropdown
        font_idx = int(self.style_font.get_selected())
        if 0 <= font_idx < len(self._font_families):
            style.fontname = self._font_families[font_idx]
        style.fontsize = int(self.style_fontsize.get_value())
        style.primary_color = self.style_primary.get_text().strip() or style.primary_color
        style.outline_color = self.style_outline.get_text().strip() or style.outline_color
        style.back_color = self.style_back.get_text().strip() or style.back_color
        style.bold = bool(self.style_bold.get_active())
        style.italic = bool(self.style_italic.get_active())
        style.outline = float(self.style_outline_width.get_value())
        style.shadow = float(self.style_shadow.get_value())
        style.alignment = int(self.style_alignment.get_value())

        # Only update the model label when the name changes.
        if new_name != prev_name:
            self._style_model.splice(self._selected_style_index, 1, [new_name])

        self._update_preview()

    def _on_add_style(self, _button):
        new_style = ASSStyle(name=f"Style{len(self._styles) + 1}")
        self._styles.append(new_style)
        self._style_model.splice(self._style_model.get_n_items(), 0, [new_style.name])
        self._set_selected_style_index(len(self._styles) - 1)
        self._load_style_into_editor()

    def _on_remove_style(self, _button):
        if len(self._styles) <= 1:
            return
        idx = self._selected_style_index
        self._styles.pop(idx)
        self._style_model.splice(idx, 1, [])
        self._set_selected_style_index(max(0, idx - 1))
        self._load_style_into_editor()

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
            self.preview_label.set_attributes(attrs)
        except Exception:
            self.preview_label.set_attributes(None)

    def _parse_extra_metadata(self) -> dict:
        start, end = self.extra_buffer.get_bounds()
        text = self.extra_buffer.get_text(start, end, True)
        out = {}
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith(';'):
                continue
            if ':' not in line:
                continue
            k, v = line.split(':', 1)
            k = k.strip()
            if not k:
                continue
            out[k] = v.strip()
        return out

    def _on_apply(self, _button):
        metadata = {}
        for key, _label in self.COMMON_KEYS:
            val = self._info_rows[key].get_text().strip()
            if val:
                metadata[key] = val
        metadata.update(self._parse_extra_metadata())

        names = [s.name.strip() for s in self._styles if s.name and s.name.strip()]
        if len(set(names)) != len(names):
            self.parent_window._show_toast("Style names must be unique")
            return

        cmd = ReplaceASSHeaderCommand(
            self.document,
            metadata=metadata,
            styles=self._styles,
            fallback_style='Default',
        )
        self.parent_window.command_manager.execute(cmd)

        # Update per-entry style dropdown options in editor panel
        style_names = [s.name for s in (self.document.styles or [])]
        self.parent_window.editor_panel.set_document_context(self.document.format, style_names)

        self.parent_window.subtitle_list.refresh(preserve_selection=True)
        self.parent_window._update_title()
        self.parent_window._update_undo_redo_buttons()
        self.parent_window._show_toast("Updated ASS metadata/styles")

        self.close()
