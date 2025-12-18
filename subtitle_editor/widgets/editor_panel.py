"""
Editor panel widget.

Provides text and timing editing for the selected subtitle entry.
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, GObject
from subtitle_editor.models import SubtitleEntry, TimeCode


class EditorPanel(Gtk.Box):
    """Widget for editing subtitle text and timing."""
    
    __gsignals__ = {
        'text-changed': (GObject.SignalFlags.RUN_FIRST, None, (int, str)),
        'timing-changed': (GObject.SignalFlags.RUN_FIRST, None, (int, object, object))
    }
    
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        
        self.current_entry: SubtitleEntry = None
        self.current_position = -1
        self._updating = False  # Flag to prevent signal loops
        
        # Scrolled window for content (removed duplicate header)
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.append(scrolled)
        
        # Content box with margins
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        content.set_margin_start(18)
        content.set_margin_end(18)
        content.set_margin_top(18)
        content.set_margin_bottom(18)
        scrolled.set_child(content)
        
        # Text section
        text_group = Adw.PreferencesGroup()
        text_group.set_title("Text")
        content.append(text_group)
        
        # Text editor
        self.text_buffer = Gtk.TextBuffer()
        self.text_buffer.connect('changed', self._on_text_buffer_changed)
        
        self.text_view = Gtk.TextView()
        self.text_view.set_buffer(self.text_buffer)
        self.text_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.text_view.set_pixels_above_lines(6)
        self.text_view.set_pixels_below_lines(6)
        self.text_view.set_left_margin(12)
        self.text_view.set_right_margin(12)
        self.text_view.set_top_margin(12)
        self.text_view.set_bottom_margin(12)
        self.text_view.add_css_class("card")
        
        text_scroll = Gtk.ScrolledWindow()
        text_scroll.set_min_content_height(120)
        text_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        text_scroll.set_child(self.text_view)
        
        text_group.add(text_scroll)
        
        # Timing section
        timing_group = Adw.PreferencesGroup()
        timing_group.set_title("Timing")
        content.append(timing_group)
        
        # Start time
        start_row = Adw.ActionRow()
        start_row.set_title("Start Time")
        timing_group.add(start_row)
        
        start_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        start_box.set_valign(Gtk.Align.CENTER)
        
        self.start_hour = self._create_spin_button(0, 23)
        self.start_minute = self._create_spin_button(0, 59)
        self.start_second = self._create_spin_button(0, 59)
        self.start_milli = self._create_spin_button(0, 999, 1)
        
        start_box.append(self.start_hour)
        start_box.append(Gtk.Label(label=":"))
        start_box.append(self.start_minute)
        start_box.append(Gtk.Label(label=":"))
        start_box.append(self.start_second)
        start_box.append(Gtk.Label(label=","))
        start_box.append(self.start_milli)
        
        start_row.add_suffix(start_box)
        
        # End time
        end_row = Adw.ActionRow()
        end_row.set_title("End Time")
        timing_group.add(end_row)
        
        end_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        end_box.set_valign(Gtk.Align.CENTER)
        
        self.end_hour = self._create_spin_button(0, 23)
        self.end_minute = self._create_spin_button(0, 59)
        self.end_second = self._create_spin_button(0, 59)
        self.end_milli = self._create_spin_button(0, 999, 1)
        
        end_box.append(self.end_hour)
        end_box.append(Gtk.Label(label=":"))
        end_box.append(self.end_minute)
        end_box.append(Gtk.Label(label=":"))
        end_box.append(self.end_second)
        end_box.append(Gtk.Label(label=","))
        end_box.append(self.end_milli)
        
        end_row.add_suffix(end_box)
        
        # Duration display
        self.duration_row = Adw.ActionRow()
        self.duration_row.set_title("Duration")
        self.duration_row.set_subtitle("0.000 seconds")
        timing_group.add(self.duration_row)
        
        # Connect timing change signals
        for spin in [self.start_hour, self.start_minute, self.start_second, self.start_milli,
                     self.end_hour, self.end_minute, self.end_second, self.end_milli]:
            spin.connect('value-changed', self._on_timing_changed)
        
        # Initially disabled
        self.set_sensitive(False)
    
    def _create_spin_button(self, min_val: int, max_val: int, step: int = 1) -> Gtk.SpinButton:
        """Create a spin button for time input."""
        adjustment = Gtk.Adjustment(
            value=0,
            lower=min_val,
            upper=max_val,
            step_increment=step,
            page_increment=step * 10,
            page_size=0
        )
        
        spin = Gtk.SpinButton()
        spin.set_adjustment(adjustment)
        spin.set_numeric(True)
        spin.set_width_chars(4 if max_val >= 100 else 3)
        
        return spin
    
    def set_entry(self, entry: SubtitleEntry, position: int):
        """Set the current entry to edit."""
        self.current_entry = entry
        self.current_position = position
        self._updating = True
        
        # Update text
        self.text_buffer.set_text(entry.text)
        
        # Update start time
        self.start_hour.set_value(entry.start_time.hours)
        self.start_minute.set_value(entry.start_time.minutes)
        self.start_second.set_value(entry.start_time.seconds)
        self.start_milli.set_value(entry.start_time.milliseconds)
        
        # Update end time
        self.end_hour.set_value(entry.end_time.hours)
        self.end_minute.set_value(entry.end_time.minutes)
        self.end_second.set_value(entry.end_time.seconds)
        self.end_milli.set_value(entry.end_time.milliseconds)
        
        # Update duration
        self._update_duration()
        
        self._updating = False
        self.set_sensitive(True)
    
    def clear(self):
        """Clear the editor."""
        self.current_entry = None
        self.current_position = -1
        self._updating = True
        
        self.text_buffer.set_text("")
        
        for spin in [self.start_hour, self.start_minute, self.start_second, self.start_milli,
                     self.end_hour, self.end_minute, self.end_second, self.end_milli]:
            spin.set_value(0)
        
        self._updating = False
        self.set_sensitive(False)
    
    def focus_text(self):
        """Focus the text editor."""
        self.text_view.grab_focus()
    
    def _update_duration(self):
        """Update the duration display."""
        start_ms = (self.start_hour.get_value_as_int() * 3600000 +
                   self.start_minute.get_value_as_int() * 60000 +
                   self.start_second.get_value_as_int() * 1000 +
                   self.start_milli.get_value_as_int())
        
        end_ms = (self.end_hour.get_value_as_int() * 3600000 +
                 self.end_minute.get_value_as_int() * 60000 +
                 self.end_second.get_value_as_int() * 1000 +
                 self.end_milli.get_value_as_int())
        
        duration_ms = max(0, end_ms - start_ms)
        duration_sec = duration_ms / 1000.0
        
        self.duration_row.set_subtitle(f"{duration_sec:.3f} seconds")
    
    def _on_text_buffer_changed(self, text_buffer):
        """Handle text buffer changes."""
        if self._updating or self.current_position < 0:
            return
        
        start = text_buffer.get_start_iter()
        end = text_buffer.get_end_iter()
        text = text_buffer.get_text(start, end, False)
        
        if self.current_entry and text != self.current_entry.text:
            self.emit('text-changed', self.current_position, text)
    
    def _on_timing_changed(self, spin_button):
        """Handle timing spin button changes."""
        if self._updating or self.current_position < 0:
            return
        
        # Update duration display
        self._update_duration()
        
        # Create TimeCode objects
        start_time = TimeCode(
            hours=self.start_hour.get_value_as_int(),
            minutes=self.start_minute.get_value_as_int(),
            seconds=self.start_second.get_value_as_int(),
            milliseconds=self.start_milli.get_value_as_int()
        )
        
        end_time = TimeCode(
            hours=self.end_hour.get_value_as_int(),
            minutes=self.end_minute.get_value_as_int(),
            seconds=self.end_second.get_value_as_int(),
            milliseconds=self.end_milli.get_value_as_int()
        )
        
        # Emit signal
        self.emit('timing-changed', self.current_position, start_time, end_time)
