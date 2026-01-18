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
        
        # Preset buttons using ActionRows with buttons
        preset_row_back = Adw.ActionRow()
        preset_row_back.set_title("Shift Backward")
        preset_row_back.set_activatable(False)
        back_icon = Gtk.Image.new_from_icon_name("media-seek-backward-symbolic")
        preset_row_back.add_prefix(back_icon)
        
        back_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        for label, value in [("-5s", -5000), ("-1s", -1000), ("-100ms", -100)]:
            button = Gtk.Button(label=label)
            button.connect('clicked', lambda b, v=value: self.offset_row.set_value(self.offset_row.get_value() + v))
            back_box.append(button)
        preset_row_back.add_suffix(back_box)
        presets_group.add(preset_row_back)
        
        preset_row_forward = Adw.ActionRow()
        preset_row_forward.set_title("Shift Forward")
        preset_row_forward.set_activatable(False)
        forward_icon = Gtk.Image.new_from_icon_name("media-seek-forward-symbolic")
        preset_row_forward.add_prefix(forward_icon)
        
        forward_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        for label, value in [("+100ms", 100), ("+1s", 1000), ("+5s", 5000)]:
            button = Gtk.Button(label=label)
            button.add_css_class("suggested-action")
            button.connect('clicked', lambda b, v=value: self.offset_row.set_value(self.offset_row.get_value() + v))
            forward_box.append(button)
        preset_row_forward.add_suffix(forward_box)
        presets_group.add(preset_row_forward)
        
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
        scope_group.set_description("Choose which subtitles to modify")
        prefs_page.add(scope_group)

        self.scope_selected = Adw.ActionRow()
        self.scope_selected.set_title("Selected subtitles")
        self.scope_selected.set_subtitle("Apply to currently selected entries only")
        self.scope_selected_check = Gtk.CheckButton()
        self.scope_selected_check.set_active(True)
        self.scope_selected.add_prefix(self.scope_selected_check)
        self.scope_selected.set_activatable_widget(self.scope_selected_check)
        selected_icon = Gtk.Image.new_from_icon_name("edit-select-symbolic")
        self.scope_selected.add_prefix(selected_icon)
        scope_group.add(self.scope_selected)

        self.scope_all = Adw.ActionRow()
        self.scope_all.set_title("All subtitles")
        self.scope_all.set_subtitle("Apply to every subtitle in the document")
        self.scope_all_check = Gtk.CheckButton(group=self.scope_selected_check)
        self.scope_all.add_prefix(self.scope_all_check)
        self.scope_all.set_activatable_widget(self.scope_all_check)
        all_icon = Gtk.Image.new_from_icon_name("view-list-symbolic")
        self.scope_all.add_prefix(all_icon)
        scope_group.add(self.scope_all)

        self.scope_from = Adw.ActionRow()
        self.scope_from.set_title("From first selected to end")
        self.scope_from.set_subtitle("Apply to selected and all following entries")
        self.scope_from_check = Gtk.CheckButton(group=self.scope_selected_check)
        self.scope_from.add_prefix(self.scope_from_check)
        self.scope_from.set_activatable_widget(self.scope_from_check)
        from_icon = Gtk.Image.new_from_icon_name("go-next-symbolic")
        self.scope_from.add_prefix(from_icon)
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

        # Full Script Info editor (dynamic fields)
        full_info_row = Adw.ExpanderRow()
        full_info_row.set_title("All Script Info")
        full_info_row.set_subtitle("Edit all keys including PlayResX/PlayResY")
        full_info_row.set_expanded(True)
        info_group.add(full_info_row)

        self._script_info_rows = []  # list of (key_entry, value_entry)

        add_info_row = Adw.ActionRow()
        add_info_row.set_title("Add Script Info key")
        add_btn = Gtk.Button()
        add_btn.set_icon_name("list-add-symbolic")
        add_btn.add_css_class("flat")
        add_btn.add_css_class("circular")
        add_btn.connect('clicked', lambda b: self._add_kv_row(full_info_row, self._script_info_rows, "", ""))
        add_info_row.add_suffix(add_btn)
        add_info_row.set_activatable(False)
        full_info_row.add_row(add_info_row)

        for k in sorted(self._metadata.keys()):
            self._add_kv_row(full_info_row, self._script_info_rows, k, self._metadata[k])

        # Aegisub Project Garbage editor (dynamic fields)
        aeg_row = Adw.ExpanderRow()
        aeg_row.set_title("Aegisub Project Garbage")
        aeg_row.set_subtitle("Optional section used by Aegisub")
        aeg_row.set_expanded(False)
        info_group.add(aeg_row)

        self._aegisub_rows = []
        self._aegisub_garbage = copy.deepcopy(getattr(self.document, 'aegisub_project_garbage', {}) or {})

        add_aeg_row = Adw.ActionRow()
        add_aeg_row.set_title("Add Aegisub key")
        add_aeg_btn = Gtk.Button()
        add_aeg_btn.set_icon_name("list-add-symbolic")
        add_aeg_btn.add_css_class("flat")
        add_aeg_btn.add_css_class("circular")
        add_aeg_btn.connect('clicked', lambda b: self._add_kv_row(aeg_row, self._aegisub_rows, "", ""))
        add_aeg_row.add_suffix(add_aeg_btn)
        add_aeg_row.set_activatable(False)
        aeg_row.add_row(add_aeg_row)

        for k in sorted(self._aegisub_garbage.keys()):
            self._add_kv_row(aeg_row, self._aegisub_rows, k, self._aegisub_garbage[k])

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

        # Color pickers (GTK color wheel) -> stored as ASS &H... strings
        primary_dialog = Gtk.ColorDialog()
        outline_dialog = Gtk.ColorDialog()
        back_dialog = Gtk.ColorDialog()
        # Enable alpha transparency
        primary_dialog.set_with_alpha(True)
        outline_dialog.set_with_alpha(True)
        back_dialog.set_with_alpha(True)

        self._primary_color_btn = Gtk.ColorDialogButton.new(primary_dialog)
        self._outline_color_btn = Gtk.ColorDialogButton.new(outline_dialog)
        self._back_color_btn = Gtk.ColorDialogButton.new(back_dialog)

        primary_row = Adw.ActionRow()
        primary_row.set_title("Primary Colour")
        primary_row.add_suffix(self._primary_color_btn)
        primary_row.set_activatable(False)
        styles_group.add(primary_row)

        outline_row = Adw.ActionRow()
        outline_row.set_title("Outline Colour")
        outline_row.add_suffix(self._outline_color_btn)
        outline_row.set_activatable(False)
        styles_group.add(outline_row)

        back_row = Adw.ActionRow()
        back_row.set_title("Back Colour")
        back_row.add_suffix(self._back_color_btn)
        back_row.set_activatable(False)
        styles_group.add(back_row)

        self._primary_color_btn.connect('notify::rgba', lambda *a: self._on_color_changed('primary'))
        self._outline_color_btn.connect('notify::rgba', lambda *a: self._on_color_changed('outline'))
        self._back_color_btn.connect('notify::rgba', lambda *a: self._on_color_changed('back'))

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

        # Live preview (own line, larger area)
        preview_expander = Adw.ExpanderRow()
        preview_expander.set_title("Preview")
        preview_expander.set_subtitle("Live sample for the selected style")
        preview_expander.set_expanded(True)
        styles_group.add(preview_expander)

        # Larger preview area: scrolls instead of squishing other controls.
        self.preview_label = Gtk.Label(label="The quick brown fox jumps over the lazy dog 0123456789")
        self.preview_label.set_xalign(0.0)
        self.preview_label.set_wrap(True)
        self.preview_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.preview_label.set_max_width_chars(60)

        # Preview container with explicit CSS class so we can style it reliably
        self.preview_frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.preview_frame.add_css_class("ass-preview-frame")
        self.preview_frame.set_margin_top(6)
        self.preview_frame.set_margin_bottom(6)
        self.preview_frame.set_margin_start(6)
        self.preview_frame.set_margin_end(6)

        self.preview_label.add_css_class("ass-preview-label")
        self.preview_frame.append(self.preview_label)

        self.preview_scroller = Gtk.ScrolledWindow()
        self.preview_scroller.set_hexpand(True)
        self.preview_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.preview_scroller.set_min_content_height(220)
        # Let preview take remaining space in the dialog
        self.preview_scroller.set_vexpand(True)
        self.preview_scroller.set_child(self.preview_frame)

        preview_content_row = Adw.ActionRow()
        preview_content_row.set_activatable(False)
        preview_content_row.set_vexpand(True)
        preview_content_row.add_suffix(self.preview_scroller)
        preview_expander.add_row(preview_content_row)

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
            # Colors
            self._primary_color_btn.set_rgba(self._ass_color_to_rgba(style.primary_color) or Gdk.RGBA(1, 1, 1, 1))
            self._outline_color_btn.set_rgba(self._ass_color_to_rgba(style.outline_color) or Gdk.RGBA(0, 0, 0, 1))
            self._back_color_btn.set_rgba(self._ass_color_to_rgba(style.back_color) or Gdk.RGBA(0.95, 0.95, 0.95, 1))
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

    def _on_color_changed(self, which: str) -> None:
        if self._updating_style_ui:
            return
        style = self._styles[self._selected_style_index]
        if which == 'primary':
            rgba = self._primary_color_btn.get_rgba()
            style.primary_color = self._rgba_to_ass_color(rgba)
        elif which == 'outline':
            rgba = self._outline_color_btn.get_rgba()
            style.outline_color = self._rgba_to_ass_color(rgba)
        elif which == 'back':
            rgba = self._back_color_btn.get_rgba()
            style.back_color = self._rgba_to_ass_color(rgba)
        self._update_preview()

    def _ass_color_to_rgba(self, ass_color: str) -> Gdk.RGBA | None:
        """Parse ASS color string (&HAABBGGRR or &HBBGGRR) to Gdk.RGBA.

        ASS uses BBGGRR order, and AA is inverted alpha (00=opaque, FF=transparent).
        """
        if not ass_color:
            return None
        s = str(ass_color).strip().upper()
        if not s.startswith('&H'):
            return None
        hexpart = s[2:]
        # strip any trailing &
        if hexpart.endswith('&'):
            hexpart = hexpart[:-1]
        # pad
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

    def _update_preview(self) -> None:
        if not hasattr(self, 'preview_label'):
            return
        try:
            style = self._styles[self._selected_style_index]

            # Font attributes
            attrs = Pango.AttrList()
            attrs.insert(Pango.attr_family_new(style.fontname))
            attrs.insert(Pango.attr_size_new(int(style.fontsize * Pango.SCALE)))
            if style.bold:
                attrs.insert(Pango.attr_weight_new(Pango.Weight.BOLD))
            if style.italic:
                attrs.insert(Pango.attr_style_new(Pango.Style.ITALIC))
            self.preview_label.set_attributes(attrs)

            # Colors (best-effort)
            fg = self._ass_color_to_rgba(getattr(style, 'primary_color', None) or '')
            # If no bg is set, use a light gray default so shadow/outline are visible.
            bg = self._ass_color_to_rgba(getattr(style, 'back_color', None) or '') or Gdk.RGBA(0.95, 0.95, 0.95, 1)
            outline_col = self._ass_color_to_rgba(getattr(style, 'outline_color', None) or '') or Gdk.RGBA(0, 0, 0, 1)

            css = ""

            label_props = []
            if fg is not None:
                label_props.append(f"color: {self._rgba_to_css(fg)}")

            # Approximate ASS outline + shadow using layered CSS text-shadow
            try:
                outline_px = float(getattr(style, 'outline', 0.0) or 0.0)
            except Exception:
                outline_px = 0.0
            try:
                shadow_px = float(getattr(style, 'shadow', 0.0) or 0.0)
            except Exception:
                shadow_px = 0.0

            # Background behind the preview text
            if bg is not None:
                css += f".ass-preview-frame {{ background-color: {self._rgba_to_css(bg)}; padding: 12px; border-radius: 8px; }}\n"

            shadows = []
            ocss = self._rgba_to_css(outline_col) if outline_col is not None else None

            if outline_px > 0 and ocss is not None:
                o = outline_px
                # 8-direction outline
                for dx, dy in [(-o, 0), (o, 0), (0, -o), (0, o), (-o, -o), (-o, o), (o, -o), (o, o)]:
                    shadows.append(f"{dx:.1f}px {dy:.1f}px 0 {ocss}")

            if shadow_px > 0 and ocss is not None:
                # Use outline color as shadow color (common ASS usage)
                shadows.append(f"{shadow_px:.1f}px {shadow_px:.1f}px 0 {ocss}")

            if shadows:
                label_props.append(f"text-shadow: {', '.join(shadows)}")

            if label_props:
                # GTK4: label text styling often needs to target the 'text' node
                props = '; '.join(label_props)
                css += f".ass-preview-label {{ {props}; }}\n"
                css += f".ass-preview-label > text {{ {props}; }}\n"

            # Apply CSS (register provider for display so it affects our custom classes)
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

    def _add_kv_row(self, container_row: Adw.ExpanderRow, store_list: list, key: str, value: str) -> None:
        row = Adw.ActionRow()
        row.set_activatable(False)

        key_entry = Gtk.Entry()
        key_entry.set_hexpand(True)
        key_entry.set_text(str(key or ""))
        key_entry.set_placeholder_text("Key")
        key_entry.set_width_chars(18)

        value_entry = Gtk.Entry()
        value_entry.set_hexpand(True)
        value_entry.set_text(str(value or ""))
        value_entry.set_placeholder_text("Value")
        value_entry.set_width_chars(26)

        del_btn = Gtk.Button()
        del_btn.set_icon_name("user-trash-symbolic")
        del_btn.add_css_class("flat")
        del_btn.add_css_class("circular")

        def _remove(_btn):
            try:
                container_row.remove(row)
            except Exception:
                # Fallback if remove() isn't available
                row.set_visible(False)
            # keep store_list consistent
            store_list[:] = [pair for pair in store_list if pair[0] is not key_entry]

        del_btn.connect('clicked', _remove)

        # Put Key first, then Value
        row.add_prefix(value_entry)
        row.add_prefix(key_entry)
        row.add_suffix(del_btn)

        container_row.add_row(row)
        store_list.append((key_entry, value_entry))

    def _collect_kv_rows(self, rows: list) -> dict:
        out = {}
        for key_entry, value_entry in rows:
            k = key_entry.get_text().strip()
            if not k:
                continue
            out[k] = value_entry.get_text().strip()
        return out

    def _on_apply(self, _button):
        # Collect Script Info from dynamic rows
        metadata = self._collect_kv_rows(self._script_info_rows)

        # Also include the common convenience fields (they override if filled)
        for key, _label in self.COMMON_KEYS:
            val = self._info_rows[key].get_text().strip()
            if val:
                metadata[key] = val

        # Aegisub Project Garbage
        aegisub_garbage = self._collect_kv_rows(self._aegisub_rows)

        names = [s.name.strip() for s in self._styles if s.name and s.name.strip()]
        if len(set(names)) != len(names):
            self.parent_window._show_toast("Style names must be unique")
            return

        cmd = ReplaceASSHeaderCommand(
            self.document,
            metadata=metadata,
            aegisub_project_garbage=aegisub_garbage,
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


class TrackSelectionDialog(Adw.Window):
    """Dialog for selecting audio and subtitle tracks from a video file."""

    __gsignals__ = {
        "tracks-selected": (GObject.SignalFlags.RUN_FIRST, None, (int, int)),
        # (audio_track_index, subtitle_track_index) - both can be -1 for "none"
    }

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
        
        self.set_transient_for(parent)
        self.set_modal(True)
        self.set_title("Select Audio and Subtitle Tracks")
        self.set_default_size(500, 450)
        
        self.audio_tracks = audio_tracks
        self.subtitle_tracks = subtitle_tracks
        self.selected_audio = current_audio
        self.selected_subtitle = current_subtitle
        
        # Main content - AdwWindow uses AdwToolbarView for header
        toolbar_view = Adw.ToolbarView()
        self.set_content(toolbar_view)
        
        header = Adw.HeaderBar()
        toolbar_view.add_top_bar(header)
        
        # Cancel button
        cancel_button = Gtk.Button(label="Cancel")
        cancel_button.connect("clicked", lambda b: self.close())
        header.pack_start(cancel_button)
        
        # Select button
        select_button = Gtk.Button(label="Select")
        select_button.add_css_class("suggested-action")
        select_button.connect("clicked", self._on_select_clicked)
        header.pack_end(select_button)
        
        # Content box
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        toolbar_view.set_content(content_box)
        
        # Scrolled window
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        content_box.append(scrolled)
        
        # Preferences page
        prefs_page = Adw.PreferencesPage()
        scrolled.set_child(prefs_page)
        
        # Audio tracks group
        audio_group = Adw.PreferencesGroup()
        audio_group.set_title("Audio Tracks")
        audio_group.set_description(f"Select an audio track ({len(audio_tracks)} available)")
        prefs_page.add(audio_group)
        
        # Create radio buttons for audio tracks
        self.audio_check_group = []
        for i, track in enumerate(audio_tracks):
            row = Adw.ActionRow()
            row.set_title(track.get('title', f"Track {track['index'] + 1}"))
            
            # Build subtitle with language and codec info
            subtitle_parts = []
            if track.get('language'):
                subtitle_parts.append(track['language'])
            if track.get('codec'):
                subtitle_parts.append(track['codec'])
            if subtitle_parts:
                row.set_subtitle(", ".join(subtitle_parts))
            
            # Radio button
            check = Gtk.CheckButton()
            check.set_active(track['index'] == current_audio)
            check.connect("toggled", self._on_audio_track_selected, track['index'])
            
            # Group radio buttons
            if self.audio_check_group:
                check.set_group(self.audio_check_group[0])
            self.audio_check_group.append(check)
            
            row.add_prefix(check)
            row.set_activatable_widget(check)
            audio_group.add(row)
        
        # Subtitle tracks group
        subtitle_group = Adw.PreferencesGroup()
        subtitle_group.set_title("Subtitle Tracks")
        subtitle_group.set_description(f"Select a subtitle track ({len(subtitle_tracks)} available)")
        prefs_page.add(subtitle_group)
        
        # "None" option for subtitles
        none_row = Adw.ActionRow()
        none_row.set_title("None")
        none_row.set_subtitle("No embedded subtitles")
        none_check = Gtk.CheckButton()
        none_check.set_active(current_subtitle == -1)
        none_check.connect("toggled", self._on_subtitle_track_selected, -1)
        none_row.add_prefix(none_check)
        none_row.set_activatable_widget(none_check)
        subtitle_group.add(none_row)
        
        self.subtitle_check_group = [none_check]
        
        # Create radio buttons for subtitle tracks
        for i, track in enumerate(subtitle_tracks):
            row = Adw.ActionRow()
            row.set_title(track.get('title', f"Track {track['index'] + 1}"))
            
            # Build subtitle with language and codec info
            subtitle_parts = []
            if track.get('language'):
                subtitle_parts.append(track['language'])
            if track.get('codec'):
                subtitle_parts.append(track['codec'])
            if subtitle_parts:
                row.set_subtitle(", ".join(subtitle_parts))
            
            # Radio button
            check = Gtk.CheckButton()
            check.set_active(track['index'] == current_subtitle)
            check.connect("toggled", self._on_subtitle_track_selected, track['index'])
            check.set_group(none_check)
            self.subtitle_check_group.append(check)
            
            row.add_prefix(check)
            row.set_activatable_widget(check)
            subtitle_group.add(row)
    
    def _on_audio_track_selected(self, check_button, track_index):
        """Handle audio track selection."""
        if check_button.get_active():
            self.selected_audio = track_index
    
    def _on_subtitle_track_selected(self, check_button, track_index):
        """Handle subtitle track selection."""
        if check_button.get_active():
            self.selected_subtitle = track_index
    
    def _on_select_clicked(self, button):
        """Handle select button click."""
        self.emit("tracks-selected", self.selected_audio, self.selected_subtitle)
        self.close()
