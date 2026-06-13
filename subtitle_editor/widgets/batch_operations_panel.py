"""
Batch operations panel for applying changes to multiple subtitle files.
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, GObject


class BatchOperationsPanel(Adw.Bin):
    """
    Panel with controls for batch operations:
    - Time shift (offset in ms)
    - Font size (for ASS styles)
    - Resolution (PlayResX/PlayResY for ASS)
    """

    __gsignals__ = {
        'operations-changed': (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self):
        clamp = Adw.Clamp()
        clamp.set_maximum_size(600)

        prefs_page = Adw.PreferencesPage()
        prefs_page.set_vexpand(True)

        self._build_time_shift_group(prefs_page)
        self._build_font_size_group(prefs_page)
        self._build_resolution_group(prefs_page)

        clamp.set_child(prefs_page)
        self.set_child(clamp)

    def _build_time_shift_group(self, prefs_page):
        group = Adw.PreferencesGroup()
        group.set_title("Time Shift")
        group.set_description("Shift subtitle timing forward or backward")
        prefs_page.add(group)

        self.offset_row = Adw.SpinRow.new_with_range(-3600000, 3600000, 100)
        self.offset_row.set_title("Offset")
        self.offset_row.set_subtitle("Milliseconds (negative for backward)")
        self.offset_row.set_value(0)
        self.offset_row.set_digits(0)
        self.offset_row.set_numeric(True)
        self.offset_row.connect('notify::value', lambda *a: self.emit('operations-changed'))
        group.add(self.offset_row)

        presets_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        presets_box.set_margin_start(12)
        presets_box.set_margin_end(12)
        presets_box.set_margin_top(12)
        presets_box.set_margin_bottom(12)
        presets_box.set_halign(Gtk.Align.CENTER)

        for label, value in [("-5s", -5000), ("-1s", -1000), ("-100ms", -100),
                              ("+100ms", 100), ("+1s", 1000), ("+5s", 5000)]:
            button = Gtk.Button(label=label)
            if value > 0:
                button.add_css_class("suggested-action")
            button.connect('clicked', lambda b, v=value: self.offset_row.set_value(
                self.offset_row.get_value() + v
            ))
            presets_box.append(button)

        group.add(presets_box)

    def _build_font_size_group(self, prefs_page):
        group = Adw.PreferencesGroup()
        group.set_title("Font Size")
        group.set_description("Change font size in ASS styles")
        prefs_page.add(group)

        self.font_size_row = Adw.SpinRow.new_with_range(1, 1000, 1)
        self.font_size_row.set_title("Font Size (points)")
        self.font_size_row.set_subtitle("Applied to all ASS styles; SRT files are skipped")
        self.font_size_row.set_value(0)
        self.font_size_row.set_digits(0)
        self.font_size_row.set_numeric(True)
        self.font_size_row.connect('notify::value', lambda *a: self.emit('operations-changed'))

        enable_row = Adw.ActionRow()
        enable_row.set_title("Change Font Size")
        enable_row.set_activatable(True)

        self.font_enable_switch = Gtk.CheckButton()
        self.font_enable_switch.set_valign(Gtk.Align.CENTER)
        self.font_enable_switch.connect('toggled', self._on_font_enable_toggled)
        enable_row.add_suffix(self.font_enable_switch)

        group.add(enable_row)
        group.add(self.font_size_row)
        self.font_size_row.set_sensitive(False)

    def _on_font_enable_toggled(self, switch):
        self.font_size_row.set_sensitive(switch.get_active())
        self.emit('operations-changed')

    def _build_resolution_group(self, prefs_page):
        group = Adw.PreferencesGroup()
        group.set_title("Resolution")
        group.set_description("Change ASS PlayResX/PlayResY resolution")
        prefs_page.add(group)

        self.res_width_row = Adw.SpinRow.new_with_range(1, 7680, 1)
        self.res_width_row.set_title("Width (PlayResX)")
        self.res_width_row.set_subtitle("ASS reference resolution width")
        self.res_width_row.set_value(0)
        self.res_width_row.set_digits(0)
        self.res_width_row.set_numeric(True)
        self.res_width_row.connect('notify::value', lambda *a: self.emit('operations-changed'))

        self.res_height_row = Adw.SpinRow.new_with_range(1, 4320, 1)
        self.res_height_row.set_title("Height (PlayResY)")
        self.res_height_row.set_subtitle("ASS reference resolution height")
        self.res_height_row.set_value(0)
        self.res_height_row.set_digits(0)
        self.res_height_row.set_numeric(True)
        self.res_height_row.connect('notify::value', lambda *a: self.emit('operations-changed'))

        enable_row = Adw.ActionRow()
        enable_row.set_title("Change Resolution")
        enable_row.set_activatable(True)

        self.res_enable_switch = Gtk.CheckButton()
        self.res_enable_switch.set_valign(Gtk.Align.CENTER)
        self.res_enable_switch.connect('toggled', self._on_res_enable_toggled)
        enable_row.add_suffix(self.res_enable_switch)

        group.add(enable_row)
        group.add(self.res_width_row)
        group.add(self.res_height_row)
        self.res_width_row.set_sensitive(False)
        self.res_height_row.set_sensitive(False)

    def _on_res_enable_toggled(self, switch):
        enabled = switch.get_active()
        self.res_width_row.set_sensitive(enabled)
        self.res_height_row.set_sensitive(enabled)
        self.emit('operations-changed')

    def has_time_shift(self) -> bool:
        """Check if a non-zero time shift offset is set."""
        return int(self.offset_row.get_value()) != 0

    def has_font_size_change(self) -> bool:
        """Check if font size change is enabled and set."""
        return bool(self.font_enable_switch.get_active() and int(self.font_size_row.get_value()) > 0)

    def has_resolution_change(self) -> bool:
        """Check if resolution change is enabled and set."""
        return bool(self.res_enable_switch.get_active()
                    and int(self.res_width_row.get_value()) > 0
                    and int(self.res_height_row.get_value()) > 0)

    def has_any_operation(self) -> bool:
        """Check if any operation is configured."""
        return self.has_time_shift() or self.has_font_size_change() or self.has_resolution_change()

    def get_summary(self) -> list[str]:
        """Get a human-readable summary of configured operations."""
        lines = []
        if self.has_time_shift():
            offset = int(self.offset_row.get_value())
            sign = "+" if offset >= 0 else ""
            lines.append(f"Time shift: {sign}{offset}ms")
        if self.has_font_size_change():
            lines.append(f"Font size: {int(self.font_size_row.get_value())}pt")
        if self.has_resolution_change():
            w = int(self.res_width_row.get_value())
            h = int(self.res_height_row.get_value())
            lines.append(f"Resolution: {w}x{h}")
        return lines

    def reset(self):
        """Reset all operations to defaults."""
        self.offset_row.set_value(0)
        self.font_size_row.set_value(0)
        self.font_enable_switch.set_active(False)
        self.res_width_row.set_value(0)
        self.res_height_row.set_value(0)
        self.res_enable_switch.set_active(False)
