"""
Batch operations panel for applying changes to multiple subtitle files.
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, GObject

from subtitle_editor.resources import template_resource_path


@Gtk.Template(resource_path=template_resource_path('batch-operations-panel'))
class BatchOperationsPanel(Adw.Bin):
    """
    Panel with controls for batch operations:
    - Time shift (offset in ms)
    - Font size (for ASS styles)
    - Resolution (PlayResX/PlayResY for ASS)
    """

    __gtype_name__ = 'GsubBatchOperationsPanel'

    __gsignals__ = {
        'operations-changed': (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    offset_row = Gtk.Template.Child()
    presets_box = Gtk.Template.Child()
    font_enable_row = Gtk.Template.Child()
    font_enable_switch = Gtk.Template.Child()
    font_size_row = Gtk.Template.Child()
    res_enable_row = Gtk.Template.Child()
    res_enable_switch = Gtk.Template.Child()
    res_width_row = Gtk.Template.Child()
    res_height_row = Gtk.Template.Child()

    def __init__(self):
        super().__init__()
        self._build_presets()
        self._connect_signals()

    def _build_presets(self):
        """Populate the quick time-shift preset buttons (built in a loop)."""
        for label, value in [("-5s", -5000), ("-1s", -1000), ("-100ms", -100),
                              ("+100ms", 100), ("+1s", 1000), ("+5s", 5000)]:
            button = Gtk.Button(label=label)
            if value > 0:
                button.add_css_class("suggested-action")
            button.connect('clicked', lambda b, v=value: self.offset_row.set_value(
                self.offset_row.get_value() + v
            ))
            self.presets_box.append(button)

    def _connect_signals(self):
        self.offset_row.connect('notify::value', lambda *a: self.emit('operations-changed'))
        self.font_size_row.connect('notify::value', lambda *a: self.emit('operations-changed'))
        self.res_width_row.connect('notify::value', lambda *a: self.emit('operations-changed'))
        self.res_height_row.connect('notify::value', lambda *a: self.emit('operations-changed'))
        self.font_enable_switch.connect('toggled', self._on_font_enable_toggled)
        self.res_enable_switch.connect('toggled', self._on_res_enable_toggled)

    def _on_font_enable_toggled(self, switch):
        self.font_size_row.set_sensitive(switch.get_active())
        self.emit('operations-changed')

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
