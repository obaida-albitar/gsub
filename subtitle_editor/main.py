#!/usr/bin/env python3
"""
Gsub - Main Entry Point

A modern subtitle editor using GTK 4 and libadwaita.
Supports SRT and ASS/SSA subtitle formats with full editing capabilities.
"""

import sys
import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, Gio

# Initialize libadwaita before any widget module is imported. Adw.init()
# registers the libadwaita GTypes with GObject's type system so that
# Gtk.Builder (used by Gtk.Template) can resolve types like AdwToolbarView.
Adw.init()

# Register the compiled gresource bundle before importing the window, since the
# window's Gtk.Template references resource paths that must exist at import time.
from subtitle_editor.resources import register_resources, install_style_provider

register_resources()

from subtitle_editor.window import GsubWindow


class GsubApplication(Adw.Application):
    """Main application class for Gsub."""

    def __init__(self):
        super().__init__(
            application_id='app.gsub',
            flags=Gio.ApplicationFlags.HANDLES_OPEN
        )
        self.window = None

    def do_startup(self):
        """Load the application stylesheet once the display is available."""
        Adw.Application.do_startup(self)
        # Style provider needs a default display, which exists by do_startup.
        install_style_provider()

    def do_activate(self):
        """Called when the application is activated."""
        if not self.window:
            self.window = GsubWindow(application=self)
        self.window.present()

    def do_open(self, files, n_files, hint):
        """Called when the application is asked to open files."""
        self.do_activate()
        if files and len(files) > 0:
            # Open the first file
            self.window.open_file(files[0])


def main():
    """Main entry point for the application."""
    app = GsubApplication()
    return app.run(sys.argv)


if __name__ == '__main__':
    sys.exit(main())
