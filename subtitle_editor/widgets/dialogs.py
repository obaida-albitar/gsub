"""
Dialog widgets for the subtitle editor.
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw
from subtitle_editor.commands import TimeShiftCommand


class TimeShiftDialog(Adw.Window):
    """Dialog for shifting subtitle timing."""
    
    def __init__(self, parent_window):
        super().__init__()
        
        self.parent_window = parent_window
        self.document = parent_window.document
        
        # Set up window
        self.set_transient_for(parent_window)
        self.set_modal(True)
        self.set_default_size(400, 300)
        
        # Header bar
        header = Adw.HeaderBar()
        
        cancel_button = Gtk.Button(label="Cancel")
        cancel_button.connect('clicked', lambda b: self.close())
        header.pack_start(cancel_button)
        
        apply_button = Gtk.Button(label="Apply")
        apply_button.add_css_class("suggested-action")
        apply_button.connect('clicked', self._on_apply)
        header.pack_end(apply_button)
        
        # Content
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        
        content_box.append(header)
        
        # Preferences page
        prefs_page = Adw.PreferencesPage()
        prefs_page.set_vexpand(True)
        content_box.append(prefs_page)
        
        # Time shift group
        shift_group = Adw.PreferencesGroup()
        shift_group.set_title("Time Shift")
        shift_group.set_description("Shift all subtitles by a specified amount")
        prefs_page.add(shift_group)
        
        # Offset input
        offset_row = Adw.ActionRow()
        offset_row.set_title("Offset")
        shift_group.add(offset_row)
        
        offset_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        offset_box.set_valign(Gtk.Align.CENTER)
        
        # Milliseconds spin button
        self.offset_adjustment = Gtk.Adjustment(
            value=0,
            lower=-3600000,  # -1 hour
            upper=3600000,   # +1 hour
            step_increment=100,
            page_increment=1000,
            page_size=0
        )
        
        self.offset_spin = Gtk.SpinButton()
        self.offset_spin.set_adjustment(self.offset_adjustment)
        self.offset_spin.set_numeric(True)
        self.offset_spin.set_width_chars(8)
        
        offset_box.append(self.offset_spin)
        offset_box.append(Gtk.Label(label="milliseconds"))
        
        offset_row.add_suffix(offset_box)
        
        # Quick presets
        presets_group = Adw.PreferencesGroup()
        presets_group.set_title("Quick Presets")
        prefs_page.add(presets_group)
        
        preset_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        preset_box.set_halign(Gtk.Align.CENTER)
        preset_box.set_margin_top(12)
        preset_box.set_margin_bottom(12)
        
        for label, value in [("-5s", -5000), ("-1s", -1000), ("-100ms", -100),
                             ("+100ms", 100), ("+1s", 1000), ("+5s", 5000)]:
            button = Gtk.Button(label=label)
            button.connect('clicked', lambda b, v=value: self.offset_spin.set_value(v))
            preset_box.append(button)
        
        presets_group.add(preset_box)
        
        # Scope group
        scope_group = Adw.PreferencesGroup()
        scope_group.set_title("Apply To")
        prefs_page.add(scope_group)
        
        # Radio buttons for scope
        self.scope_all = Gtk.CheckButton(label="All subtitles")
        self.scope_all.set_active(True)
        scope_all_row = Adw.ActionRow()
        scope_all_row.set_title("All subtitles")
        scope_all_row.add_prefix(self.scope_all)
        scope_all_row.set_activatable_widget(self.scope_all)
        scope_group.add(scope_all_row)
        
        self.scope_selected = Gtk.CheckButton(label="Selected subtitle only")
        self.scope_selected.set_group(self.scope_all)
        scope_selected_row = Adw.ActionRow()
        scope_selected_row.set_title("Selected subtitle only")
        scope_selected_row.add_prefix(self.scope_selected)
        scope_selected_row.set_activatable_widget(self.scope_selected)
        scope_group.add(scope_selected_row)
        
        self.scope_from = Gtk.CheckButton(label="From selected to end")
        self.scope_from.set_group(self.scope_all)
        scope_from_row = Adw.ActionRow()
        scope_from_row.set_title("From selected to end")
        scope_from_row.add_prefix(self.scope_from)
        scope_from_row.set_activatable_widget(self.scope_from)
        scope_group.add(scope_from_row)
        
        self.set_content(content_box)
    
    def _on_apply(self, button):
        """Apply the time shift."""
        offset_ms = int(self.offset_spin.get_value())
        
        if offset_ms == 0:
            self.close()
            return
        
        # Determine which subtitles to shift
        positions = None
        
        if self.scope_selected.get_active():
            # Only selected subtitle
            selected_pos = self.parent_window.subtitle_list.get_selected_position()
            if selected_pos >= 0:
                positions = [selected_pos]
            else:
                self.close()
                return
        
        elif self.scope_from.get_active():
            # From selected to end
            selected_pos = self.parent_window.subtitle_list.get_selected_position()
            if selected_pos >= 0:
                positions = list(range(selected_pos, len(self.document.entries)))
            else:
                self.close()
                return
        
        # Create and execute command
        cmd = TimeShiftCommand(self.document, offset_ms, positions)
        self.parent_window.command_manager.execute(cmd)
        
        # Update UI
        self.parent_window.subtitle_list.refresh()
        self.parent_window._update_title()
        
        self.close()
