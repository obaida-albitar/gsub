#!/usr/bin/env python3
"""
Gsub - Main Entry Point

A modern subtitle editor using GTK 4 and libadwaita.
Supports SRT and ASS/SSA subtitle formats with full editing capabilities.
"""

import sys
import gi

from gsub.utils import is_video_content_type

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Adw, Gio

# Initialize libadwaita before any widget module is imported. Adw.init()
# registers the libadwaita GTypes with GObject's type system so that
# Gtk.Builder (used by Gtk.Template) can resolve types like AdwToolbarView.
Adw.init()

# Register the compiled gresource bundle before importing the window, since the
# window's Gtk.Template references resource paths that must exist at import time.
from gsub.resources import register_resources, install_style_provider

register_resources()

from gsub.window import GsubWindow


class GsubApplication(Adw.Application):
    """Main application class for Gsub."""

    def __init__(self):
        super().__init__(
            application_id='io.github.obaidaalbitar.gsub',
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
        """Called when the application is asked to open files.

        Videos (e.g. via "Open With" from the file manager) go to the video
        player, everything else is treated as a subtitle file.
        """
        self.do_activate()
        if files and len(files) > 0:
            # Open the first file
            file = files[0]
            if self._is_video_file(file):
                self.window.open_video(file)
            else:
                self.window.open_file(file)

    @staticmethod
    def _is_video_file(gfile) -> bool:
        """Return True when the file's content type is a video type.

        Any failure to query the content type falls back to "not a video" so
        the file is still opened through the regular subtitle path.
        """
        try:
            info = gfile.query_info(
                Gio.FILE_ATTRIBUTE_STANDARD_CONTENT_TYPE,
                Gio.FileQueryInfoFlags.NONE,
                None,
            )
            return is_video_content_type(
                info.get_attribute_string(Gio.FILE_ATTRIBUTE_STANDARD_CONTENT_TYPE))
        except Exception:
            return False


def main():
    """Main entry point for the application."""
    app = GsubApplication()
    return app.run(sys.argv)


if __name__ == '__main__':
    sys.exit(main())
