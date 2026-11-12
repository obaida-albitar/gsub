"""A compact, explicit target timestamp editor for the video player."""

import gettext
from decimal import Decimal, ROUND_FLOOR

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gdk, GLib, Gtk

from gsub.time_navigation import format_timestamp, parse_timestamp


_ = gettext.translation("gsub", fallback=True).gettext


class TimestampPopover(Gtk.Popover):
    """Edit a seek target without replacing the player's actual-time readout.

    ``on_seek(seconds)`` must retain the player's playing/paused state and
    return False on failure (True or None means success). Position and duration
    providers are read when opening; later position updates never rewrite the
    entry. Duration is checked again at submission so a newly loaded or closed
    video cannot turn an old target into an unchecked seek.
    """

    def __init__(self, on_seek, get_position, get_duration=None, on_before_open=None):
        super().__init__(autohide=True, has_arrow=True)
        self.on_seek = on_seek
        self.get_position = get_position
        self.get_duration = get_duration or (lambda: None)
        self.on_before_open = on_before_open
        self._prepared_for_popup = False
        self._focus_source = None

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8,
                          margin_top=12, margin_bottom=12,
                          margin_start=12, margin_end=12, width_request=300)
        self.set_child(content)
        title = Gtk.Label(label=_("Go to Timestamp"), xalign=0)
        title.add_css_class("heading")
        content.append(title)
        target_label = Gtk.Label(label=_("Target timestamp"), xalign=0)
        content.append(target_label)

        input_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.entry = Gtk.Entry(hexpand=True, placeholder_text="00:00:00.000",
                               activates_default=False)
        self.entry.set_width_chars(16)
        self.entry.update_property([Gtk.AccessibleProperty.LABEL], [_("Target timestamp")])
        self.entry.add_css_class("numeric")
        self.entry.connect("activate", lambda _entry: self.submit())
        self.entry.connect("changed", self._on_entry_changed)
        self.go_button = Gtk.Button(label=_("Go"), tooltip_text=_("Seek to target timestamp"))
        self.go_button.add_css_class("suggested-action")
        self.go_button.connect("clicked", lambda _button: self.submit())
        input_row.append(self.entry)
        input_row.append(self.go_button)
        content.append(input_row)

        formats = Gtk.Label(label=_("Use HH:MM:SS.mmm, MM:SS.mmm, or seconds. A dot or comma separates fractional seconds."),
                            xalign=0, wrap=True, max_width_chars=36)
        formats.add_css_class("dim-label")
        content.append(formats)
        self.duration_label = Gtk.Label(xalign=0, wrap=True, visible=False)
        self.duration_label.add_css_class("dim-label")
        content.append(self.duration_label)
        frame_note = Gtk.Label(label=_("Video frames limit the exact position playback can reach."),
                               xalign=0, wrap=True, max_width_chars=36)
        frame_note.add_css_class("dim-label")
        content.append(frame_note)
        self.error_label = Gtk.Label(xalign=0, wrap=True, max_width_chars=36, visible=False)
        self.error_label.add_css_class("error")
        content.append(self.error_label)

        keys = Gtk.EventControllerKey.new()
        keys.connect("key-pressed", self._on_key_pressed)
        self.add_controller(keys)
        self.connect("notify::visible", self._on_visibility_changed)
        self.connect("closed", self._on_closed)

    def _show_error(self, message):
        self.error_label.set_text(message)
        self.error_label.set_visible(True)

    def _clear_error(self):
        self.error_label.set_text("")
        self.error_label.set_visible(False)

    def _on_entry_changed(self, _entry):
        self._clear_error()

    def _read_duration(self):
        try:
            duration = self.get_duration()
            if duration is not None:
                label = format_timestamp(duration)
                self.duration_label.set_text(_("Video duration: %s") % label)
                self.duration_label.set_visible(True)
            else:
                self.duration_label.set_visible(False)
            return duration
        except Exception:
            self.duration_label.set_visible(False)
            raise ValueError(_("Video duration is unavailable. Try again when the video has loaded.")) from None

    def prepare(self) -> bool:
        """Initialize once for the next opening, leaving active typing alone."""
        self._clear_error()
        if callable(self.on_before_open):
            try:
                if self.on_before_open() is False:
                    return False
            except Exception:
                self._show_error(_("Could not open timestamp navigation. Try again when the video is ready."))
                return False
        try:
            position = format_timestamp(self.get_position())
        except Exception:
            position = "00:00:00.000"
            position_unavailable = True
        else:
            position_unavailable = False
        self.entry.set_text(position)
        try:
            duration = self._read_duration()
            if duration is not None:
                try:
                    parse_timestamp(position, duration)
                except ValueError:
                    # The generated millisecond display can round a valid EOF
                    # position just past a fractional-ms duration. Initialize
                    # with the last whole millisecond instead. User-entered
                    # targets still go through strict, unclamped submission.
                    last_ms = (Decimal(str(duration)) * 1000).to_integral_value(
                        rounding=ROUND_FLOOR)
                    self.entry.set_text(format_timestamp(last_ms / 1000))
        except ValueError as error:
            self._show_error(str(error))
        if position_unavailable:
            self._show_error(_("Current position is unavailable. Enter a timestamp to continue."))
        self.entry.select_region(0, -1)
        self._prepared_for_popup = True
        return True

    def open(self) -> bool:
        if self.get_visible():
            self.entry.grab_focus()
            return True
        if not self.prepare():
            return False
        self.popup()
        return True

    def _on_visibility_changed(self, _popover, _pspec):
        if not self.get_visible():
            self._prepared_for_popup = False
            return
        if not self._prepared_for_popup and not self.prepare():
            self.popdown()
            return
        self._prepared_for_popup = False
        # After the popover is laid out GTK can focus its entry reliably.
        if self._focus_source is None:
            self._focus_source = GLib.idle_add(self._focus_entry)

    def _focus_entry(self):
        self._focus_source = None
        if self.get_visible():
            self.entry.grab_focus()
            self.entry.select_region(0, -1)
        return GLib.SOURCE_REMOVE

    def _on_closed(self, _popover):
        self._prepared_for_popup = False
        if self._focus_source is not None:
            GLib.source_remove(self._focus_source)
            self._focus_source = None

    def _on_key_pressed(self, _controller, keyval, _keycode, _state):
        if keyval == Gdk.KEY_Escape:
            self.popdown()
            return True
        return False

    def submit(self) -> bool:
        """Seek only after validation; errors stay next to the editable target."""
        self._clear_error()
        try:
            seconds = parse_timestamp(self.entry.get_text(), self._read_duration())
        except ValueError as error:
            self._show_error(str(error))
            return False
        try:
            result = self.on_seek(seconds)
        except Exception:
            result = False
        if result is False:
            self._show_error(_("Could not seek to that timestamp. Try again when the video is ready."))
            return False
        self.popdown()
        return True
