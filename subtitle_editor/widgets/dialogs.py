"""
Dialog widgets for the subtitle editor.
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw
from subtitle_editor.commands import TimeShiftCommand


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
