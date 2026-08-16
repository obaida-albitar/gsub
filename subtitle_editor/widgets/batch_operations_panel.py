"""
Batch operations panel for applying changes to multiple subtitle files.
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, GObject

from subtitle_editor.resources import template_resource_path
from subtitle_editor.widgets.style_props_editor import GsubStylePropsEditor


@Gtk.Template(resource_path=template_resource_path('batch-operations-panel'))
class BatchOperationsPanel(Adw.Bin):
    """
    Panel with controls for batch operations:
    - Time shift (offset in ms)
    - Resolution (PlayResX/PlayResY for ASS)
    - Style properties (font size, font, colours, layout for ASS styles)
    """

    __gtype_name__ = 'GsubBatchOperationsPanel'

    __gsignals__ = {
        'operations-changed': (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    groups_box = Gtk.Template.Child()
    actions_group = Gtk.Template.Child()
    offset_row = Gtk.Template.Child()
    presets_box = Gtk.Template.Child()
    res_enable_row = Gtk.Template.Child()
    res_enable_switch = Gtk.Template.Child()
    res_width_row = Gtk.Template.Child()
    res_height_row = Gtk.Template.Child()
    action_box = Gtk.Template.Child()

    def __init__(self):
        super().__init__()

        # Style property batch editor (target styles + tickable property
        # rows), placed between the Resolution and Actions groups: appending
        # moves a widget to the end, so re-add the Actions group to keep it
        # last.
        self.style_props = GsubStylePropsEditor()
        self.style_props.connect('changed', lambda *a: self.emit('operations-changed'))
        self.groups_box.append(self.style_props)
        self.groups_box.remove(self.actions_group)
        self.groups_box.append(self.actions_group)

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
        self.res_width_row.connect('notify::value', lambda *a: self.emit('operations-changed'))
        self.res_height_row.connect('notify::value', lambda *a: self.emit('operations-changed'))
        self.res_enable_switch.connect('toggled', self._on_res_enable_toggled)

    def set_style_props_styles(self, styles: list):
        """Feed the style properties editor the shared ASS style definitions.

        The editor's targets are limited to the shared style names (styles
        present in every loaded ASS/SSA file); the style objects provide row
        defaults and the preview base.
        """
        self.style_props.set_styles(styles or [])

    def _on_res_enable_toggled(self, switch):
        enabled = switch.get_active()
        self.res_width_row.set_sensitive(enabled)
        self.res_height_row.set_sensitive(enabled)
        self.emit('operations-changed')

    def has_time_shift(self) -> bool:
        """Check if a non-zero time shift offset is set."""
        return int(self.offset_row.get_value()) != 0

    def has_resolution_change(self) -> bool:
        """Check if a resolution change is enabled and set."""
        return bool(self.res_enable_switch.get_active()
                    and int(self.res_width_row.get_value()) > 0
                    and int(self.res_height_row.get_value()) > 0)

    def has_style_props_change(self) -> bool:
        """Check if style property editing is configured (target + properties)."""
        return self.style_props.has_changes()

    def has_any_operation(self) -> bool:
        """Check if any operation is configured."""
        return (self.has_time_shift() or self.has_resolution_change()
                or self.has_style_props_change())

    def get_summary(self) -> list[str]:
        """Get a human-readable summary of configured operations."""
        lines = []
        if self.has_time_shift():
            offset = int(self.offset_row.get_value())
            sign = "+" if offset >= 0 else ""
            lines.append(f"Time shift: {sign}{offset}ms")
        if self.has_resolution_change():
            w = int(self.res_width_row.get_value())
            h = int(self.res_height_row.get_value())
            lines.append(f"Resolution: {w}x{h}")
        if self.has_style_props_change():
            labels = self.style_props.property_labels()
            shown = ', '.join(labels[:4]) + ('…' if len(labels) > 4 else '')
            n = len(self.style_props.get_target_styles())
            lines.append(f"Style properties: {shown} on {n} style{'s' if n != 1 else ''}")
        return lines

    def reset(self):
        """Reset all operations to defaults."""
        self.offset_row.set_value(0)
        self.res_width_row.set_value(0)
        self.res_height_row.set_value(0)
        self.res_enable_switch.set_active(False)
        self.style_props.reset()
