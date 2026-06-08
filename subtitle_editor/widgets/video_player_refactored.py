"""
Video player widget with subtitle overlay - Refactored version.

Uses GStreamer for video playback and renders subtitles with ASS styling support.
Follows GNOME HIG and libadwaita design principles.

This is a refactored version that uses separate modules for:
- MediaExtractor: Subtitle/audio extraction
- TrackManager: Track detection and management
- SubtitleRenderer: Subtitle rendering with styling
"""

import gi
from subtitle_editor.logger import get_logger

logger = get_logger(__name__)

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gst", "1.0")
gi.require_version("GstVideo", "1.0")

import os
import tempfile
from typing import Optional
import cairo
from gi.repository import Adw, Gdk, GLib, GObject, Gst, GstVideo, Gtk

from subtitle_editor.models import SubtitleDocument, SubtitleEntry
from subtitle_editor.media import MediaExtractor, TrackManager
from subtitle_editor.media.subtitle_renderer import SubtitleRenderer

# Initialize GStreamer
Gst.init(None)


class VideoPlayerWidget(Gtk.Box):
    """Video player widget with subtitle overlay."""

    __gsignals__ = {
        "position-changed": (GObject.SignalFlags.RUN_FIRST, None, (float,)),
        "duration-changed": (GObject.SignalFlags.RUN_FIRST, None, (float,)),
        "state-changed": (GObject.SignalFlags.RUN_FIRST, None, (bool,)),  # True=playing
    }

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        self.document: Optional[SubtitleDocument] = None
        self.current_subtitle: Optional[SubtitleEntry] = None
        self.video_uri: Optional[str] = None
        self._is_seeking = False
        self._duration = 0
        self._video_width = 0
        self._video_height = 0
        self._embedded_subtitle_active = False

        # Create GStreamer pipeline
        self.player = Gst.ElementFactory.make("playbin", "player")
        if not self.player:
            logger.warning("Could not create GStreamer playbin")
            self._show_error_state()
            return

        # Disable built-in subtitles by default
        self.player.set_property(
            "flags", self.player.get_property("flags") & ~0x00000004
        )

        # Initialize managers
        self.track_manager = TrackManager(self.player)
        self.media_extractor = None  # Initialized when needed
        
        # Setup video sink for GTK4 with hardware acceleration
        self._setup_video_sink()

        # Create subtitle renderer
        self.subtitle_renderer = SubtitleRenderer()

        # Build UI
        self._build_ui()

        # Setup GStreamer bus
        bus = self.player.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_gst_message)

        # Update timer - use 250ms for better performance
        GLib.timeout_add(250, self._update_position)

    def _setup_video_sink(self):
        """Setup video sink with hardware acceleration if available."""
        self.gtksink = Gst.ElementFactory.make("gtk4paintablesink", "sink")
        if not self.gtksink:
            logger.warning("gtk4paintablesink not available, falling back")
            self.gtksink = Gst.ElementFactory.make("gtksink", "sink")

        if self.gtksink:
            # Try to use hardware-accelerated video conversion
            try:
                video_bin = Gst.Bin.new("video_bin")
                glupload = Gst.ElementFactory.make("glupload", "glupload")
                glcolorconvert = Gst.ElementFactory.make("glcolorconvert", "glcolorconvert")

                if glupload and glcolorconvert:
                    video_bin.add(glupload)
                    video_bin.add(glcolorconvert)
                    video_bin.add(self.gtksink)
                    glupload.link(glcolorconvert)
                    glcolorconvert.link(self.gtksink)

                    pad = glupload.get_static_pad("sink")
                    ghost_pad = Gst.GhostPad.new("sink", pad)
                    video_bin.add_pad(ghost_pad)

                    self.player.set_property("video-sink", video_bin)
                    logger.info("Using hardware-accelerated video pipeline")
                else:
                    self.player.set_property("video-sink", self.gtksink)
                    logger.info("Using software video rendering")
            except Exception as e:
                logger.info(f"Could not setup hardware acceleration: {e}")
                self.player.set_property("video-sink", self.gtksink)
        else:
            logger.warning("No GTK sink available")

    def _build_ui(self):
        """Construct the user interface."""
        # Video display area
        video_frame = Gtk.Frame()
        video_frame.add_css_class("view")
        video_frame.set_vexpand(True)
        self.append(video_frame)

        # Overlay for subtitles
        self.overlay = Gtk.Overlay()
        video_frame.set_child(self.overlay)

        # Video picture widget
        self.video_picture = Gtk.Picture()
        self.video_picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        if self.gtksink:
            paintable = self.gtksink.get_property("paintable")
            if paintable:
                self.video_picture.set_paintable(paintable)
        self.video_picture.set_vexpand(True)
        self.video_picture.set_can_shrink(True)
        self.overlay.set_child(self.video_picture)

        # Subtitle overlay (drawing area)
        self.subtitle_drawing_area = Gtk.DrawingArea()
        self.subtitle_drawing_area.set_draw_func(self._draw_subtitle)
        self.subtitle_drawing_area.set_vexpand(True)
        self.subtitle_drawing_area.set_hexpand(True)
        self.subtitle_drawing_area.set_opacity(1.0)
        self.overlay.add_overlay(self.subtitle_drawing_area)

        # Control bar
        self._build_controls()

    def _build_controls(self):
        """Build compact video control bar."""
        controls_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        controls_box.add_css_class("toolbar")
        controls_box.add_css_class("osd")
        controls_box.set_margin_start(6)
        controls_box.set_margin_end(6)
        controls_box.set_margin_top(6)
        controls_box.set_margin_bottom(6)
        self.append(controls_box)

        # Playback controls
        playback_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        playback_box.add_css_class("linked")
        controls_box.append(playback_box)

        skip_back_button = Gtk.Button()
        skip_back_button.set_icon_name("media-seek-backward-symbolic")
        skip_back_button.set_tooltip_text("Skip backward 5 seconds")
        skip_back_button.connect("clicked", lambda b: self.skip(-5000))
        playback_box.append(skip_back_button)

        self.play_button = Gtk.Button()
        self.play_button.set_icon_name("media-playback-start-symbolic")
        self.play_button.set_tooltip_text("Play/Pause (Space)")
        self.play_button.connect("clicked", self._on_play_pause_clicked)
        playback_box.append(self.play_button)

        skip_forward_button = Gtk.Button()
        skip_forward_button.set_icon_name("media-seek-forward-symbolic")
        skip_forward_button.set_tooltip_text("Skip forward 5 seconds")
        skip_forward_button.connect("clicked", lambda b: self.skip(5000))
        playback_box.append(skip_forward_button)

        # Time labels
        self.time_label = Gtk.Label(label="0:00")
        self.time_label.add_css_class("numeric")
        self.time_label.set_width_chars(5)
        self.time_label.set_margin_start(6)
        controls_box.append(self.time_label)

        # Timeline scale
        self.timeline_scale = Gtk.Scale()
        self.timeline_scale.set_range(0, 100)
        self.timeline_scale.set_value(0)
        self.timeline_scale.set_draw_value(False)
        self.timeline_scale.set_hexpand(True)
        self.timeline_scale.connect("change-value", self._on_timeline_seek)
        controls_box.append(self.timeline_scale)

        self.duration_label = Gtk.Label(label="0:00")
        self.duration_label.add_css_class("numeric")
        self.duration_label.add_css_class("dim-label")
        self.duration_label.set_width_chars(5)
        self.duration_label.set_margin_end(6)
        controls_box.append(self.duration_label)

        # Volume button
        self.volume_button = Gtk.VolumeButton()
        self.volume_button.set_value(1.0)
        self.volume_button.set_tooltip_text("Volume")
        self.volume_button.connect("value-changed", self._on_volume_changed)
        controls_box.append(self.volume_button)

        # Subtitle size button with popover
        self._build_subtitle_size_button(controls_box)

    def _build_subtitle_size_button(self, controls_box):
        """Build subtitle size adjustment button."""
        subtitle_size_button = Gtk.MenuButton()
        subtitle_size_button.set_icon_name("format-text-bold-symbolic")
        subtitle_size_button.set_tooltip_text("Subtitle Size")
        
        popover = Gtk.Popover()
        popover_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        popover_box.set_margin_start(12)
        popover_box.set_margin_end(12)
        popover_box.set_margin_top(12)
        popover_box.set_margin_bottom(12)
        
        scale_label = Gtk.Label(label="Subtitle Size")
        scale_label.add_css_class("heading")
        popover_box.append(scale_label)
        
        self.subtitle_scale_slider = Gtk.Scale()
        self.subtitle_scale_slider.set_range(0.1, 1.5)
        self.subtitle_scale_slider.set_value(0.75)
        self.subtitle_scale_slider.set_draw_value(True)
        self.subtitle_scale_slider.set_value_pos(Gtk.PositionType.RIGHT)
        self.subtitle_scale_slider.set_digits(2)
        self.subtitle_scale_slider.set_size_request(200, -1)
        self.subtitle_scale_slider.connect("value-changed", self._on_subtitle_scale_changed)
        
        self.subtitle_scale_slider.add_mark(0.1, Gtk.PositionType.BOTTOM, None)
        self.subtitle_scale_slider.add_mark(0.75, Gtk.PositionType.BOTTOM, "Default")
        self.subtitle_scale_slider.add_mark(1.5, Gtk.PositionType.BOTTOM, None)
        
        popover_box.append(self.subtitle_scale_slider)
        
        reset_button = Gtk.Button(label="Reset to Default")
        reset_button.connect("clicked", lambda b: self.subtitle_scale_slider.set_value(0.75))
        popover_box.append(reset_button)
        
        popover.set_child(popover_box)
        subtitle_size_button.set_popover(popover)
        controls_box.append(subtitle_size_button)

    def _show_error_state(self):
        """Show error state when GStreamer is not available."""
        status_page = Adw.StatusPage()
        status_page.set_icon_name("dialog-error-symbolic")
        status_page.set_title("Video Player Unavailable")
        status_page.set_description(
            "GStreamer is required for video playback. "
            "Please install the required GStreamer packages."
        )
        status_page.set_vexpand(True)
        self.append(status_page)

    def set_document(self, document: Optional[SubtitleDocument]):
        """Set the subtitle document."""
        self.document = document
        self.subtitle_renderer.set_document(document)
        self._update_subtitle_display()

    def load_video(self, file_path: str):
        """Load a video file."""
        if not self.player:
            return

        self.video_uri = f"file://{file_path}"
        self.player.set_state(Gst.State.NULL)
        self.player.set_property("uri", self.video_uri)
        
        # Enable text/subtitle support in playbin
        flags = self.player.get_property("flags")
        flags &= ~0x00000004  # Disable TEXT flag (handled by SubtitleRenderer)
        self.player.set_property("flags", flags)
        
        self.player.set_state(Gst.State.PAUSED)

        # Query duration and tracks after loading
        GLib.timeout_add(500, self._query_duration)
        GLib.timeout_add(1000, self._detect_tracks)

    def _query_duration(self):
        """Query video duration."""
        if not self.player:
            return False

        success, duration = self.player.query_duration(Gst.Format.TIME)
        if success:
            self._duration = duration / Gst.SECOND
            self.timeline_scale.set_range(0, self._duration)
            self.duration_label.set_text(self._format_time(self._duration))
            self.emit("duration-changed", self._duration)
            return False
        return True

    def _detect_tracks(self):
        """Detect available audio and subtitle tracks."""
        if not self.player:
            return False
        
        return not self.track_manager.detect_tracks()

    # Playback control methods
    def play(self):
        """Start playback."""
        if self.player:
            self.player.set_state(Gst.State.PLAYING)
            self.play_button.set_icon_name("media-playback-pause-symbolic")
            self.emit("state-changed", True)

    def pause(self):
        """Pause playback."""
        if self.player:
            self.player.set_state(Gst.State.PAUSED)
            self.play_button.set_icon_name("media-playback-start-symbolic")
            self.emit("state-changed", False)

    def toggle_play_pause(self):
        """Toggle between play and pause."""
        if not self.player:
            return

        state = self.player.get_state(0)[1]
        if state == Gst.State.PLAYING:
            self.pause()
        else:
            self.play()

    def seek(self, position_sec: float):
        """Seek to a specific position in seconds."""
        if not self.player:
            return

        self.player.seek_simple(
            Gst.Format.TIME,
            Gst.SeekFlags.FLUSH | Gst.SeekFlags.ACCURATE,
            int(position_sec * Gst.SECOND),
        )

        GLib.idle_add(lambda: self._update_current_subtitle(position_sec))

    def skip(self, offset_ms: int):
        """Skip forward or backward by offset in milliseconds."""
        if not self.player:
            return

        success, position = self.player.query_position(Gst.Format.TIME)
        if success:
            new_pos = max(0, position + (offset_ms * Gst.MSECOND))
            self.player.seek_simple(
                Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT, new_pos
            )

    def get_position(self) -> float:
        """Get current playback position in seconds."""
        if not self.player:
            return 0.0

        success, position = self.player.query_position(Gst.Format.TIME)
        if success:
            return position / Gst.SECOND
        return 0.0

    # Track management methods
    def has_embedded_tracks(self):
        """Check if video has embedded audio or subtitle tracks."""
        return self.track_manager.has_tracks()

    def get_available_tracks(self):
        """Get list of available audio and subtitle tracks."""
        return self.track_manager.get_all_tracks()

    def set_audio_track(self, track_index: int):
        """Set the current audio track."""
        self.track_manager.set_audio_track(track_index)

    def set_subtitle_track(self, track_index: int):
        """Set the current subtitle track."""
        success = self.track_manager.set_subtitle_track(track_index)
        if success:
            if track_index >= 0:
                self._embedded_subtitle_active = True
                self.current_subtitle = None
                self.subtitle_drawing_area.queue_draw()
            else:
                self._embedded_subtitle_active = False

    def extract_subtitle_track(self, track_index, output_path, callback=None):
        """Extract a subtitle track from the video to a file."""
        if not self.player or not self.video_uri:
            if callback:
                callback(False, "No video loaded")
            return
        
        audio_tracks, subtitle_tracks = self.track_manager.get_all_tracks()
        if track_index < 0 or track_index >= len(subtitle_tracks):
            if callback:
                callback(False, "Invalid track index")
            return
        
        # Initialize extractor if needed
        if not self.media_extractor:
            try:
                from subtitle_editor.media import MediaExtractor
                self.media_extractor = MediaExtractor()
            except Exception as e:
                if callback:
                    callback(False, f"Failed to initialize media extractor: {e}")
                return
        
        # Extract in background thread
        import threading
        
        def extract_thread():
            try:
                # Get video file path
                if self.video_uri.startswith("file://"):
                    video_path = self.video_uri[7:]
                else:
                    video_path = self.video_uri
                
                success = self.media_extractor.extract_subtitle_track(
                    video_path,
                    track_index,
                    output_path,
                    format='srt'
                )
                
                if callback:
                    GLib.idle_add(callback, success, None if success else "Extraction failed")
            except Exception as e:
                if callback:
                    GLib.idle_add(callback, False, str(e))
        
        thread = threading.Thread(target=extract_thread, daemon=True)
        thread.start()

    # Update and rendering methods
    def _update_position(self):
        """Update position display and subtitle."""
        if not self.player or self._is_seeking:
            return True

        success, position = self.player.query_position(Gst.Format.TIME)
        if success:
            pos_sec = position / Gst.SECOND
            self.time_label.set_text(self._format_time(pos_sec))
            self.timeline_scale.set_value(pos_sec)
            self.emit("position-changed", pos_sec)
            self._update_current_subtitle(pos_sec)

        return True

    def _update_current_subtitle(self, position_sec: float):
        """Update the currently displayed subtitle based on position."""
        if self._embedded_subtitle_active:
            if self.current_subtitle is not None:
                self.current_subtitle = None
                self.subtitle_drawing_area.queue_draw()
            return
        
        if not self.document:
            if self.current_subtitle is not None:
                self.current_subtitle = None
                self.subtitle_drawing_area.queue_draw()
            return

        position_ms = position_sec * 1000

        # Check current subtitle first
        if self.current_subtitle:
            start_ms = self.current_subtitle.start_time.total_milliseconds
            end_ms = self.current_subtitle.end_time.total_milliseconds
            if start_ms <= position_ms <= end_ms:
                return

        # Find subtitle at current position
        new_subtitle = self._find_subtitle_at_position(position_ms)

        if new_subtitle != self.current_subtitle:
            self.current_subtitle = new_subtitle
            self.subtitle_drawing_area.queue_draw()

    def _find_subtitle_at_position(self, position_ms: float):
        """Find subtitle at given position using binary search."""
        if not self.document or not self.document.entries:
            return None

        entries = self.document.entries
        left, right = 0, len(entries) - 1

        while left <= right:
            mid = (left + right) // 2
            entry = entries[mid]
            start_ms = entry.start_time.total_milliseconds
            end_ms = entry.end_time.total_milliseconds

            if start_ms <= position_ms <= end_ms:
                return entry
            elif position_ms < start_ms:
                right = mid - 1
            else:
                left = mid + 1

        # Check nearby entries
        for i in range(max(0, left - 2), min(len(entries), left + 3)):
            entry = entries[i]
            start_ms = entry.start_time.total_milliseconds
            end_ms = entry.end_time.total_milliseconds
            if start_ms <= position_ms <= end_ms:
                return entry

        return None

    def _update_subtitle_display(self):
        """Force subtitle display update."""
        self.subtitle_drawing_area.queue_draw()

    def _draw_subtitle(self, area, cr, width, height):
        """Draw subtitle overlay."""
        if not self.current_subtitle:
            cr.set_operator(cairo.Operator.CLEAR)
            cr.paint()
            cr.set_operator(cairo.Operator.OVER)
            return

        cr.set_operator(cairo.Operator.CLEAR)
        cr.paint()
        cr.set_operator(cairo.Operator.OVER)

        # Get video dimensions for proper scaling
        video_width = self._video_width if self._video_width > 0 else width
        video_height = self._video_height if self._video_height > 0 else height

        # Calculate video display area (respecting aspect ratio)
        if self._video_width > 0 and self._video_height > 0:
            video_aspect = self._video_width / self._video_height
            widget_aspect = width / height if height > 0 else 1.0

            if video_aspect > widget_aspect:
                display_width = width
                display_height = width / video_aspect
                x_offset = 0
                y_offset = (height - display_height) / 2
            else:
                display_width = height * video_aspect
                display_height = height
                x_offset = (width - display_width) / 2
                y_offset = 0

            cr.translate(x_offset, y_offset)

            self.subtitle_renderer.render(
                cr,
                self.current_subtitle.text,
                self.current_subtitle.style,
                int(display_width),
                int(display_height),
                video_width,
                video_height,
                self.current_subtitle,
            )
        else:
            self.subtitle_renderer.render(
                cr,
                self.current_subtitle.text,
                self.current_subtitle.style,
                width,
                height,
                width,
                height,
                self.current_subtitle,
            )

    # Event handlers
    def _on_play_pause_clicked(self, button):
        """Handle play/pause button click."""
        self.toggle_play_pause()

    def _on_timeline_seek(self, scale, scroll_type, value):
        """Handle timeline seek."""
        if not self._is_seeking:
            self._is_seeking = True
            GLib.timeout_add(50, lambda: setattr(self, "_is_seeking", False))

        self.seek(value)
        return False

    def _on_volume_changed(self, button, value):
        """Handle volume change."""
        if self.player:
            self.player.set_property("volume", value)

    def _on_subtitle_scale_changed(self, scale):
        """Handle subtitle scale change."""
        value = scale.get_value()
        self.subtitle_renderer.set_scale(value)
        self.subtitle_drawing_area.queue_draw()

    def _on_gst_message(self, bus, message):
        """Handle GStreamer bus messages."""
        t = message.type

        if t == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            logger.info(f"GStreamer Error: {err}, {debug}")
            self.pause()

        elif t == Gst.MessageType.EOS:
            self.pause()
            self.seek(0)

        elif t == Gst.MessageType.STATE_CHANGED:
            if message.src == self.player:
                old_state, new_state, pending = message.parse_state_changed()
                if new_state in (Gst.State.PAUSED, Gst.State.PLAYING):
                    self._query_video_dimensions()

        return True

    def _query_video_dimensions(self):
        """Query actual video dimensions from the stream."""
        if not self.player:
            return

        try:
            video_sink = self.player.get_property("video-sink")
            if video_sink:
                pad = video_sink.get_static_pad("sink")
                if pad:
                    caps = pad.get_current_caps()
                    if caps and caps.get_size() > 0:
                        structure = caps.get_structure(0)
                        success, width = structure.get_int("width")
                        success2, height = structure.get_int("height")
                        if success and success2:
                            self._video_width = width
                            self._video_height = height
                            logger.info(f"Video dimensions: {width}x{height}")
                            return
        except Exception as e:
            logger.info(f"Error querying video dimensions: {e}")

        # Fallback: try paintable
        if self.gtksink:
            try:
                paintable = self.gtksink.get_property("paintable")
                if paintable:
                    width = paintable.get_intrinsic_width()
                    height = paintable.get_intrinsic_height()
                    if width > 0 and height > 0:
                        self._video_width = width
                        self._video_height = height
                        logger.info(f"Video dimensions from paintable: {width}x{height}")
            except Exception as e:
                logger.info(f"Error getting dimensions from paintable: {e}")

    def _format_time(self, seconds: float) -> str:
        """Format time in seconds to H:MM:SS or M:SS."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)

        if hours > 0:
            return f"{hours}:{minutes:02d}:{secs:02d}"
        return f"{minutes}:{secs:02d}"
