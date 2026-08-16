"""
Home screen widget with action cards for single-file or batch workflows.
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, GObject

from subtitle_editor.resources import template_resource_path


@Gtk.Template(resource_path=template_resource_path('home-screen'))
class HomeScreenView(Adw.Bin):
    """Landing page with two action cards: Start Editing and Batch Operations."""

    __gtype_name__ = 'GsubHomeScreen'

    __gsignals__ = {
        'open-file': (GObject.SignalFlags.RUN_FIRST, None, ()),
        'open-batch': (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    # Template children (exposed for tests and programmatic activation).
    open_button = Gtk.Template.Child()
    batch_button = Gtk.Template.Child()

    def __init__(self):
        super().__init__()

    @Gtk.Template.Callback()
    def on_open_clicked(self, _button):
        self.emit('open-file')

    @Gtk.Template.Callback()
    def on_batch_clicked(self, _button):
        self.emit('open-batch')
