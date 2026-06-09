"""
Editor panel widget.

Provides text and timing editing for the selected subtitle entry.
"""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, GObject, Gtk

from subtitle_editor.models import SubtitleEntry, SubtitleFormat, TimeCode


class EditorPanel(Gtk.Box):
    """Widget for editing subtitle text and timing."""

    __gsignals__ = {
        "text-changed": (GObject.SignalFlags.RUN_FIRST, None, (int, str)),
        "timing-changed": (GObject.SignalFlags.RUN_FIRST, None, (int, object, object)),
        "style-changed": (GObject.SignalFlags.RUN_FIRST, None, (int, object)),
        "position-changed": (GObject.SignalFlags.RUN_FIRST, None, (int, int, int, int)),
    }

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        self.current_entry: SubtitleEntry = None
        self.current_position = -1
        self._updating = False  # Flag to prevent signal loops
        self._text_change_timeout_id = None  # For debouncing text changes
        self._pending_text = None

        self._timing_changed_id = None  # For debouncing timing changes
        self._pending_timing_values = None
        self._position_changed_id = None  # For debouncing position changes
        self._pending_position_values = None

        # Add background styling
        self.add_css_class("view")

        # Scrolled window for content
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.append(scrolled)

        # Use Adw.Clamp for better readability on wide screens
        clamp = Adw.Clamp()
        clamp.set_maximum_size(600)
        clamp.set_tightening_threshold(400)
        scrolled.set_child(clamp)

        # Content box with margins
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        content.set_margin_start(18)
        content.set_margin_end(18)
        content.set_margin_top(18)
        content.set_margin_bottom(18)
        clamp.set_child(content)

        # Text section with modern card style
        text_group = Adw.PreferencesGroup()
        text_group.set_title("Subtitle Text")
        text_group.set_description("Edit the text content of the selected subtitle")
        content.append(text_group)

        # Style selection (ASS/SSA only; hidden by default)
        self.style_row = Adw.ComboRow()
        self.style_row.set_title("Style")
        self.style_row.set_subtitle("Apply a predefined style to this subtitle")
        self.style_row.set_visible(False)
        style_icon = Gtk.Image.new_from_icon_name("applications-graphics-symbolic")
        self.style_row.add_prefix(style_icon)
        self.style_model = Gtk.StringList.new([])
        self.style_row.set_model(self.style_model)
        self.style_row.connect("notify::selected", self._on_style_selected)
        text_group.add(self.style_row)

        # Text editor with better styling using Adw.Clamp
        text_expander = Adw.ExpanderRow()
        text_expander.set_title("Text Content")
        text_expander.set_subtitle("Edit the subtitle text")
        text_expander.set_expanded(True)
        text_expander.set_enable_expansion(True)
        text_icon = Gtk.Image.new_from_icon_name("text-editor-symbolic")
        text_expander.add_prefix(text_icon)
        text_group.add(text_expander)

        self.text_buffer = Gtk.TextBuffer()
        self.text_buffer.connect("changed", self._on_text_buffer_changed)

        self.text_view = Gtk.TextView()
        self.text_view.set_buffer(self.text_buffer)
        self.text_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.text_view.set_pixels_above_lines(8)
        self.text_view.set_pixels_below_lines(8)
        self.text_view.set_left_margin(16)
        self.text_view.set_right_margin(16)
        self.text_view.set_top_margin(16)
        self.text_view.set_bottom_margin(16)

        # Frame for text view with rounded corners
        text_scroll = Gtk.ScrolledWindow()
        text_scroll.set_min_content_height(150)
        text_scroll.set_max_content_height(300)
        text_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        text_scroll.set_child(self.text_view)
        text_scroll.add_css_class("card")
        text_scroll.set_margin_start(12)
        text_scroll.set_margin_end(12)
        text_scroll.set_margin_top(6)
        text_scroll.set_margin_bottom(12)

        text_expander.add_row(text_scroll)

        # Timing section with improved layout using expander rows
        timing_group = Adw.PreferencesGroup()
        timing_group.set_title("Timing")
        timing_group.set_description("Adjust when the subtitle appears and disappears")
        content.append(timing_group)

        # Start time - using expander row for better organization
        start_expander = Adw.ExpanderRow()
        start_expander.set_title("Start Time")
        start_expander.set_subtitle("00:00:00.000")
        start_expander.set_expanded(True)
        start_icon = Gtk.Image.new_from_icon_name("media-playback-start-symbolic")
        start_expander.add_prefix(start_icon)
        timing_group.add(start_expander)

        # Start time inputs as action row
        start_input_row = Adw.ActionRow()
        start_input_row.set_activatable(False)

        start_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        start_box.set_valign(Gtk.Align.CENTER)

        self.start_hour = self._create_spin_button(0, 23)
        self.start_minute = self._create_spin_button(0, 59)
        self.start_second = self._create_spin_button(0, 59)
        self.start_milli = self._create_spin_button(0, 999, 1)

        start_box.append(Gtk.Label(label="H:"))
        start_box.append(self.start_hour)
        start_box.append(Gtk.Label(label="M:"))
        start_box.append(self.start_minute)
        start_box.append(Gtk.Label(label="S:"))
        start_box.append(self.start_second)
        start_box.append(Gtk.Label(label="ms:"))
        start_box.append(self.start_milli)

        start_input_row.add_suffix(start_box)
        start_expander.add_row(start_input_row)

        # End time - using expander row
        end_expander = Adw.ExpanderRow()
        end_expander.set_title("End Time")
        end_expander.set_subtitle("00:00:00.000")
        end_expander.set_expanded(True)
        end_icon = Gtk.Image.new_from_icon_name("media-playback-stop-symbolic")
        end_expander.add_prefix(end_icon)
        timing_group.add(end_expander)

        # End time inputs as action row
        end_input_row = Adw.ActionRow()
        end_input_row.set_activatable(False)

        end_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        end_box.set_valign(Gtk.Align.CENTER)

        self.end_hour = self._create_spin_button(0, 23)
        self.end_minute = self._create_spin_button(0, 59)
        self.end_second = self._create_spin_button(0, 59)
        self.end_milli = self._create_spin_button(0, 999, 1)

        end_box.append(Gtk.Label(label="H:"))
        end_box.append(self.end_hour)
        end_box.append(Gtk.Label(label="M:"))
        end_box.append(self.end_minute)
        end_box.append(Gtk.Label(label="S:"))
        end_box.append(self.end_second)
        end_box.append(Gtk.Label(label="ms:"))
        end_box.append(self.end_milli)

        end_input_row.add_suffix(end_box)
        end_expander.add_row(end_input_row)

        # Duration display - using ActionRow with better styling
        self.duration_row = Adw.ActionRow()
        self.duration_row.set_title("Duration")
        self.duration_row.set_subtitle("0.000 seconds")
        duration_icon = Gtk.Image.new_from_icon_name("alarm-symbolic")
        self.duration_row.add_prefix(duration_icon)
        timing_group.add(self.duration_row)

        # Store expander rows for subtitle updates
        self.start_expander = start_expander
        self.end_expander = end_expander

        # Connect timing change signals
        for spin in [
            self.start_hour,
            self.start_minute,
            self.start_second,
            self.start_milli,
            self.end_hour,
            self.end_minute,
            self.end_second,
            self.end_milli,
        ]:
            spin.connect("value-changed", self._on_timing_changed)

        # Position section (ASS/SSA only - hidden by default)
        self.position_group = Adw.PreferencesGroup()
        self.position_group.set_title("Position (ASS)")
        self.position_group.set_description("Override subtitle position margins (0 = use style default)")
        self.position_group.set_visible(False)
        content.append(self.position_group)

        # Left margin
        margin_l_row = Adw.ActionRow()
        margin_l_row.set_title("Left Margin")
        margin_l_row.set_subtitle("Pixels from left edge (0 = use style default)")
        margin_l_icon = Gtk.Image.new_from_icon_name("go-previous-symbolic")
        margin_l_row.add_prefix(margin_l_icon)
        self.position_group.add(margin_l_row)
        
        self.margin_l_spin = Gtk.SpinButton()
        self.margin_l_spin.set_adjustment(Gtk.Adjustment(
            value=0, lower=0, upper=9999, step_increment=1, page_increment=10, page_size=0
        ))
        self.margin_l_spin.set_numeric(True)
        self.margin_l_spin.set_width_chars(5)
        self.margin_l_spin.set_valign(Gtk.Align.CENTER)
        self.margin_l_spin.connect("value-changed", self._on_position_changed)
        margin_l_row.add_suffix(self.margin_l_spin)

        # Right margin
        margin_r_row = Adw.ActionRow()
        margin_r_row.set_title("Right Margin")
        margin_r_row.set_subtitle("Pixels from right edge (0 = use style default)")
        margin_r_icon = Gtk.Image.new_from_icon_name("go-next-symbolic")
        margin_r_row.add_prefix(margin_r_icon)
        self.position_group.add(margin_r_row)
        
        self.margin_r_spin = Gtk.SpinButton()
        self.margin_r_spin.set_adjustment(Gtk.Adjustment(
            value=0, lower=0, upper=9999, step_increment=1, page_increment=10, page_size=0
        ))
        self.margin_r_spin.set_numeric(True)
        self.margin_r_spin.set_width_chars(5)
        self.margin_r_spin.set_valign(Gtk.Align.CENTER)
        self.margin_r_spin.connect("value-changed", self._on_position_changed)
        margin_r_row.add_suffix(self.margin_r_spin)

        # Vertical margin
        margin_v_row = Adw.ActionRow()
        margin_v_row.set_title("Vertical Margin")
        margin_v_row.set_subtitle("Pixels from top/bottom (0 = use style default)")
        margin_v_icon = Gtk.Image.new_from_icon_name("go-up-symbolic")
        margin_v_row.add_prefix(margin_v_icon)
        self.position_group.add(margin_v_row)
        
        self.margin_v_spin = Gtk.SpinButton()
        self.margin_v_spin.set_adjustment(Gtk.Adjustment(
            value=0, lower=0, upper=9999, step_increment=1, page_increment=10, page_size=0
        ))
        self.margin_v_spin.set_numeric(True)
        self.margin_v_spin.set_width_chars(5)
        self.margin_v_spin.set_valign(Gtk.Align.CENTER)
        self.margin_v_spin.connect("value-changed", self._on_position_changed)
        margin_v_row.add_suffix(self.margin_v_spin)

        # Initially disabled
        self.set_sensitive(False)

        # ASS/SSA support
        self._format = None
        self._styles = []

    def _create_spin_button(
        self, min_val: int, max_val: int, step: int = 1
    ) -> Gtk.SpinButton:
        """Create a spin button for time input."""
        adjustment = Gtk.Adjustment(
            value=0,
            lower=min_val,
            upper=max_val,
            step_increment=step,
            page_increment=step * 10,
            page_size=0,
        )

        spin = Gtk.SpinButton()
        spin.set_adjustment(adjustment)
        spin.set_numeric(True)
        # Give more width for better spacing
        spin.set_width_chars(5 if max_val >= 100 else 4)

        # Disable scroll wheel to prevent accidental value changes
        scroll_controller = Gtk.EventControllerScroll.new(
            Gtk.EventControllerScrollFlags.BOTH_AXES
        )
        scroll_controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        scroll_controller.connect("scroll", lambda *_: True)
        spin.add_controller(scroll_controller)

        return spin

    def set_document_context(self, fmt: SubtitleFormat, style_names: list[str]):
        """Provide document format and styles for style dropdown."""
        self._format = fmt
        self._styles = style_names or ["Default"]

        # Update style dropdown
        self.style_model.splice(0, self.style_model.get_n_items(), self._styles)
        is_ass = fmt in (SubtitleFormat.ASS, SubtitleFormat.SSA)
        self.style_row.set_visible(is_ass)
        self.position_group.set_visible(is_ass)

    def set_entry(self, entry: SubtitleEntry, position: int):
        """Set the current entry to edit."""
        # Flush any pending text changes before switching entries
        if self._text_change_timeout_id is not None:
            GLib.source_remove(self._text_change_timeout_id)
            if self._pending_text is not None and self.current_position >= 0:
                self.emit("text-changed", self.current_position, self._pending_text)
            self._text_change_timeout_id = None
            self._pending_text = None

        self.current_entry = entry
        self.current_position = position
        self._updating = True

        # Update style (ASS/SSA)
        if self._format in (SubtitleFormat.ASS, SubtitleFormat.SSA):
            try:
                idx = self._styles.index(entry.style or "Default")
            except ValueError:
                idx = 0
            self.style_row.set_selected(idx)
            
            # Update position margins
            self.margin_l_spin.set_value(getattr(entry, 'margin_l', 0))
            self.margin_r_spin.set_value(getattr(entry, 'margin_r', 0))
            self.margin_v_spin.set_value(getattr(entry, 'margin_v', 0))

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
        # Cancel any pending text change
        if self._text_change_timeout_id is not None:
            GLib.source_remove(self._text_change_timeout_id)
            self._text_change_timeout_id = None
        self._pending_text = None

        self.current_entry = None
        self.current_position = -1
        self._updating = True

        self.text_buffer.set_text("")

        for spin in [
            self.start_hour,
            self.start_minute,
            self.start_second,
            self.start_milli,
            self.end_hour,
            self.end_minute,
            self.end_second,
            self.end_milli,
        ]:
            spin.set_value(0)

        self._updating = False
        self.set_sensitive(False)

    def focus_text(self):
        """Focus the text editor."""
        self.text_view.grab_focus()

    def _on_style_selected(self, *args):
        if self._updating or self.current_position < 0:
            return
        if self._format not in (SubtitleFormat.ASS, SubtitleFormat.SSA):
            return

        idx = int(self.style_row.get_selected())
        if 0 <= idx < len(self._styles):
            self.emit("style-changed", self.current_position, self._styles[idx])

    def _update_duration(self):
        """Update the duration display and time subtitles."""
        start_ms = (
            self.start_hour.get_value_as_int() * 3600000
            + self.start_minute.get_value_as_int() * 60000
            + self.start_second.get_value_as_int() * 1000
            + self.start_milli.get_value_as_int()
        )

        end_ms = (
            self.end_hour.get_value_as_int() * 3600000
            + self.end_minute.get_value_as_int() * 60000
            + self.end_second.get_value_as_int() * 1000
            + self.end_milli.get_value_as_int()
        )

        duration_ms = max(0, end_ms - start_ms)
        duration_sec = duration_ms / 1000.0

        # Format time codes
        start_time_str = f"{self.start_hour.get_value_as_int():02d}:{self.start_minute.get_value_as_int():02d}:{self.start_second.get_value_as_int():02d}.{self.start_milli.get_value_as_int():03d}"
        end_time_str = f"{self.end_hour.get_value_as_int():02d}:{self.end_minute.get_value_as_int():02d}:{self.end_second.get_value_as_int():02d}.{self.end_milli.get_value_as_int():03d}"

        # Update subtitles
        if hasattr(self, "start_expander"):
            self.start_expander.set_subtitle(start_time_str)
        if hasattr(self, "end_expander"):
            self.end_expander.set_subtitle(end_time_str)

        self.duration_row.set_subtitle(f"{duration_sec:.3f} seconds")

    def _on_text_buffer_changed(self, text_buffer):
        """Handle text buffer changes with debouncing."""
        if self._updating or self.current_position < 0:
            return

        start = text_buffer.get_start_iter()
        end = text_buffer.get_end_iter()
        text = text_buffer.get_text(start, end, False)

        if self.current_entry and text != self.current_entry.text:
            # Cancel any pending timeout
            if self._text_change_timeout_id is not None:
                GLib.source_remove(self._text_change_timeout_id)

            # Store the pending text
            self._pending_text = text

            # Set a new timeout (500ms delay)
            self._text_change_timeout_id = GLib.timeout_add(
                500, self._emit_text_changed
            )

    def _emit_text_changed(self):
        """Emit the text-changed signal after debounce delay."""
        if self._pending_text is not None and self.current_position >= 0:
            self.emit("text-changed", self.current_position, self._pending_text)
            self._pending_text = None

        self._text_change_timeout_id = None
        return False  # Don't repeat the timeout

    def _on_timing_changed(self, spin_button):
        """Handle timing spin button changes with debouncing."""
        if self._updating or self.current_position < 0:
            return

        # Update duration display immediately
        self._update_duration()

        # Cancel any pending timeout
        if self._timing_changed_id is not None:
            GLib.source_remove(self._timing_changed_id)

        # Create TimeCode objects
        start_time = TimeCode(
            hours=self.start_hour.get_value_as_int(),
            minutes=self.start_minute.get_value_as_int(),
            seconds=self.start_second.get_value_as_int(),
            milliseconds=self.start_milli.get_value_as_int(),
        )

        end_time = TimeCode(
            hours=self.end_hour.get_value_as_int(),
            minutes=self.end_minute.get_value_as_int(),
            seconds=self.end_second.get_value_as_int(),
            milliseconds=self.end_milli.get_value_as_int(),
        )

        # Store the pending values
        self._pending_timing_values = (start_time, end_time)

        # Set a new timeout (300ms delay)
        self._timing_changed_id = GLib.timeout_add(
            300, self._emit_timing_changed
        )

    def _emit_timing_changed(self):
        """Emit timing-changed signal after debounce delay."""
        if self._pending_timing_values is not None and self.current_position >= 0:
            start_time, end_time = self._pending_timing_values
            self.emit("timing-changed", self.current_position, start_time, end_time)
            self._pending_timing_values = None

        self._timing_changed_id = None
        return False  # Don't repeat the timeout

    def _on_position_changed(self, spin_button):
        """Handle position margin changes with debouncing."""
        if self._updating or self.current_position < 0:
            return
        if self._format not in (SubtitleFormat.ASS, SubtitleFormat.SSA):
            return

        # Cancel any pending timeout
        if self._position_changed_id is not None:
            GLib.source_remove(self._position_changed_id)

        margin_l = self.margin_l_spin.get_value_as_int()
        margin_r = self.margin_r_spin.get_value_as_int()
        margin_v = self.margin_v_spin.get_value_as_int()

        # Store the pending values
        self._pending_position_values = (margin_l, margin_r, margin_v)

        # Set a new timeout (300ms delay)
        self._position_changed_id = GLib.timeout_add(
            300, self._emit_position_changed
        )

    def _emit_position_changed(self):
        """Emit position-changed signal after debounce delay."""
        if self._pending_position_values is not None and self.current_position >= 0:
            margin_l, margin_r, margin_v = self._pending_position_values
            self.emit(
                "position-changed",
                self.current_position,
                margin_l,
                margin_r,
                margin_v,
            )
            self._pending_position_values = None

        self._position_changed_id = None
        return False  # Don't repeat the timeout
