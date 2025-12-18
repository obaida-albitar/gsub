#!/usr/bin/env python3
"""
GNOME Subtitle Editor - Main Entry Point

A modern subtitle editor for GNOME desktop using GTK 4 and libadwaita.
Supports SRT and ASS/SSA subtitle formats with full editing capabilities.
"""

import sys
import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, Gio

from subtitle_editor.window import SubtitleEditorWindow


class SubtitleEditorApplication(Adw.Application):
    """Main application class for the Subtitle Editor."""
    
    def __init__(self):
        super().__init__(
            application_id='org.gnome.SubtitleEditor',
            flags=Gio.ApplicationFlags.HANDLES_OPEN
        )
        self.window = None
        
    def do_activate(self):
        """Called when the application is activated."""
        if not self.window:
            self.window = SubtitleEditorWindow(application=self)
        self.window.present()
        
    def do_open(self, files, n_files, hint):
        """Called when the application is asked to open files."""
        self.do_activate()
        if files and len(files) > 0:
            # Open the first file
            self.window.open_file(files[0])


def main():
    """Main entry point for the application."""
    app = SubtitleEditorApplication()
    return app.run(sys.argv)


if __name__ == '__main__':
    sys.exit(main())
