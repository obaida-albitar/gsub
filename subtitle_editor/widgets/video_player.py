"""
Video player widget with subtitle overlay.

Uses GStreamer for video playback and renders subtitles with ASS styling support.
Follows GNOME HIG and libadwaita design principles.
"""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gst", "1.0")
gi.require_version("GstVideo", "1.0")

import re
from typing import List, Optional

import cairo
from gi.repository import Adw, Gdk, GLib, GObject, Gst, GstVideo, Gtk, Pango, PangoCairo

from subtitle_editor.models import (
    ASSStyle,
    SubtitleDocument,
    SubtitleEntry,
    SubtitleFormat,
)

# Initialize GStreamer
Gst.init(None)


class SubtitleRenderer:
    """Renders subtitles with ASS styling support."""

    def __init__(self):
        self.current_style: Optional[ASSStyle] = None
        self.document: Optional[SubtitleDocument] = None
        # Global subtitle scale factor (similar to mpv's --sub-scale)
        # Default 0.75 to match common video players' comfortable reading size
        self.subtitle_scale = 0.75

    def set_document(self, document: Optional[SubtitleDocument]):
        """Set the subtitle document for style lookup."""
        self.document = document

    def render(
        self,
        cr: cairo.Context,
        text: str,
        style_name: Optional[str],
        width: int,
        height: int,
        video_width: int = None,
        video_height: int = None,
        entry: 'SubtitleEntry' = None,
    ):
        """Render subtitle text with styling on a Cairo context.

        Args:
            cr: Cairo context
            text: Subtitle text to render
            style_name: Name of style to apply
            width: Display width for positioning
            height: Display height for positioning
            video_width: Actual video resolution width (for reference)
            video_height: Actual video resolution height (for scaling calculation)
        """
        if not text:
            return

        # Get style from document
        style = None
        if self.document and style_name:
            style = self.document.get_style_by_name(style_name)
        if not style and self.document and self.document.styles:
            style = self.document.styles[0]  # Default to first style

        # Get PlayResY from document metadata (ASS reference resolution)
        play_res_y = None
        play_res_y_source = "default"
        if self.document and self.document.metadata:
            play_res_y_str = self.document.metadata.get("PlayResY")
            if play_res_y_str:
                try:
                    play_res_y = int(play_res_y_str)
                    play_res_y_source = "metadata"
                except ValueError:
                    pass

        # If PlayResY is not set, try to infer it from font sizes
        # Large fonts (>50) usually indicate HD resolution (720 or 1080)
        # Small fonts (<30) usually indicate SD resolution (384)
        if play_res_y is None and style and self.document:
            max_fontsize = max((s.fontsize for s in self.document.styles), default=20)
            if max_fontsize >= 70:
                play_res_y = 1080  # Assume 1080p for very large fonts
                play_res_y_source = f"inferred from fontsize={max_fontsize}"
            elif max_fontsize >= 50:
                play_res_y = 720  # Assume 720p for large fonts
                play_res_y_source = f"inferred from fontsize={max_fontsize}"
            else:
                play_res_y = 384  # Default SD resolution
                play_res_y_source = f"inferred from fontsize={max_fontsize}"

        # Create Pango layout
        layout = PangoCairo.create_layout(cr)

        # Set text
        clean_text = self._strip_ass_override_codes(text)
        layout.set_text(clean_text, -1)

        # Apply styling scaled to current display size using PlayResY
        if style:
            font_desc = self._create_font_description(style, height, play_res_y)
            layout.set_font_description(font_desc)
        else:
            # Default styling with reasonable size based on display height
            font_desc = Pango.FontDescription()
            font_desc.set_family("Sans")
            # Use 4% of display height for default size
            default_size = int(height * 0.04 * Pango.SCALE)
            font_desc.set_size(default_size)
            font_desc.set_weight(Pango.Weight.BOLD)
            layout.set_font_description(font_desc)

        # Set alignment and wrapping
        # For ASS subtitles, don't constrain the layout width - let text flow naturally
        # and calculate position based on actual text dimensions
        if style:
            # Set width to unlimited for accurate text measurement
            layout.set_width(-1)  # -1 = no wrapping based on width
            
            # Set Pango alignment based on ASS alignment (for proper RTL/LTR handling)
            if style.alignment in (1, 4, 7):  # Left-aligned
                layout.set_alignment(Pango.Alignment.LEFT)
            elif style.alignment in (3, 6, 9):  # Right-aligned
                layout.set_alignment(Pango.Alignment.RIGHT)
            else:  # Center (2, 5, 8)
                layout.set_alignment(Pango.Alignment.CENTER)
        else:
            # For non-ASS (e.g., SRT), use 90% width constraint
            layout.set_width(int(width * 0.9 * Pango.SCALE))
            layout.set_alignment(Pango.Alignment.CENTER)
        
        layout.set_wrap(Pango.WrapMode.WORD_CHAR)

        # Get layout size
        ink_rect, logical_rect = layout.get_pixel_extents()
        text_width = logical_rect.width
        text_height = logical_rect.height

        # Calculate position based on alignment
        if style:
            x, y = self._calculate_position(
                style, width, height, text_width, text_height, entry
            )
        else:
            # Default: bottom center
            x = (width - text_width) / 2
            y = height - text_height - (height * 0.05)  # 5% margin from bottom

        # Draw background/shadow if needed
        if style and style.shadow > 0:
            cr.save()
            cr.move_to(x + style.shadow, y + style.shadow)
            cr.set_source_rgba(0, 0, 0, 0.8)
            PangoCairo.show_layout(cr, layout)
            cr.restore()

        # Draw outline if needed
        if style and style.outline > 0:
            outline_color = self._parse_ass_color(style.outline_color)
            cr.save()
            cr.set_line_width(style.outline * 2)
            cr.set_source_rgba(*outline_color)
            cr.move_to(x, y)
            PangoCairo.layout_path(cr, layout)
            cr.stroke()
            cr.restore()

        # Draw main text
        if style:
            text_color = self._parse_ass_color(style.primary_color)
        else:
            text_color = (1.0, 1.0, 1.0, 1.0)  # White

        cr.save()
        cr.move_to(x, y)
        cr.set_source_rgba(*text_color)
        PangoCairo.show_layout(cr, layout)
        cr.restore()

    def _create_font_description(
        self, style: ASSStyle, display_height: int, play_res_y: int = None
    ) -> Pango.FontDescription:
        """Create a Pango font description from ASS style.

        Args:
            style: ASS style object
            display_height: Current display height for scaling
            play_res_y: ASS PlayResY value (reference resolution)
        """
        font_desc = Pango.FontDescription()
        font_desc.set_family(style.fontname or "Sans")

        # ASS fonts are designed for a specific reference resolution (PlayResY)
        # Default PlayResY is typically 384 for SD or 720/1080 for HD
        # If not specified, assume 384 (the ASS default)
        if play_res_y is None or play_res_y <= 0:
            play_res_y = 384

        # Scale font: (display_height / PlayResY) * fontsize * subtitle_scale
        # The subtitle_scale factor makes subtitles more comfortable to read
        # (similar to mpv's --sub-scale option)
        scale_factor = display_height / play_res_y * self.subtitle_scale
        size = int(style.fontsize * scale_factor * Pango.SCALE)

        font_desc.set_size(size)

        if style.bold:
            font_desc.set_weight(Pango.Weight.BOLD)
        if style.italic:
            font_desc.set_style(Pango.Style.ITALIC)

        return font_desc

    def _calculate_position(
        self,
        style: ASSStyle,
        width: int,
        height: int,
        text_width: int,
        text_height: int,
        entry: 'SubtitleEntry' = None,
    ) -> tuple:
        """Calculate text position based on ASS alignment.
        
        Args:
            style: The ASS style to use
            width: Display width
            height: Display height
            text_width: Rendered text width
            text_height: Rendered text height
            entry: Optional subtitle entry for per-entry margin overrides
        """
        # ASS alignment: numpad layout (1=bottom-left, 2=bottom-center, 3=bottom-right, etc.)
        alignment = style.alignment

        # Get margins: use entry overrides if non-zero, otherwise use style defaults
        margin_l = style.margin_l
        margin_r = style.margin_r
        margin_v = style.margin_v
        
        if entry:
            entry_ml = getattr(entry, 'margin_l', 0)
            entry_mr = getattr(entry, 'margin_r', 0)
            entry_mv = getattr(entry, 'margin_v', 0)
            
            if entry_ml != 0:
                margin_l = entry_ml
            if entry_mr != 0:
                margin_r = entry_mr
            if entry_mv != 0:
                margin_v = entry_mv

        # Horizontal position
        if alignment in (1, 4, 7):  # Left
            x = margin_l
        elif alignment in (3, 6, 9):  # Right
            x = width - text_width - margin_r
        else:  # Center (2, 5, 8)
            x = (width - text_width) / 2

        # Vertical position
        if alignment in (1, 2, 3):  # Bottom
            y = height - text_height - margin_v
        elif alignment in (7, 8, 9):  # Top
            y = margin_v
        else:  # Middle (4, 5, 6)
            y = (height - text_height) / 2

        return (x, y)

    def _parse_ass_color(self, color_str: str) -> tuple:
        """Parse ASS color format (&HAABBGGRR) to RGBA tuple."""
        if not color_str or not color_str.startswith("&H"):
            return (1.0, 1.0, 1.0, 1.0)

        try:
            # Remove &H prefix
            hex_color = color_str[2:]
            # ASS colors are AABBGGRR
            if len(hex_color) >= 6:
                bb = int(hex_color[-2:], 16) / 255.0
                gg = int(hex_color[-4:-2], 16) / 255.0
                rr = int(hex_color[-6:-4], 16) / 255.0
                # Alpha is optional
                aa = 1.0
                if len(hex_color) >= 8:
                    aa = 1.0 - (int(hex_color[-8:-6], 16) / 255.0)
                return (rr, gg, bb, aa)
        except ValueError:
            pass

        return (1.0, 1.0, 1.0, 1.0)

    def _strip_ass_override_codes(self, text: str) -> str:
        """Remove ASS override codes from text."""
        # Remove override blocks like {\i1}, {\b1}, etc.
        text = re.sub(r"\{[^}]*\}", "", text)
        return text


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
        
        # Track management
        self._audio_tracks = []
        self._subtitle_tracks = []
        self._current_audio_track = -1
        self._current_subtitle_track = -1
        self._embedded_subtitle_active = False

        # Create GStreamer pipeline
        self.player = Gst.ElementFactory.make("playbin", "player")
        if not self.player:
            print("Warning: Could not create GStreamer playbin")
            self._show_error_state()
            return

        # Disable built-in subtitles
        self.player.set_property(
            "flags", self.player.get_property("flags") & ~0x00000004
        )

        # Setup video sink for GTK4 with hardware acceleration
        self.gtksink = Gst.ElementFactory.make("gtk4paintablesink", "sink")
        if not self.gtksink:
            print("Warning: gtk4paintablesink not available, falling back")
            self.gtksink = Gst.ElementFactory.make("gtksink", "sink")

        if self.gtksink:
            # Try to use hardware-accelerated video conversion
            try:
                # Create a bin with glupload for hardware acceleration
                video_bin = Gst.Bin.new("video_bin")

                # Use glupload if available for GPU acceleration
                glupload = Gst.ElementFactory.make("glupload", "glupload")
                glcolorconvert = Gst.ElementFactory.make(
                    "glcolorconvert", "glcolorconvert"
                )

                if glupload and glcolorconvert:
                    video_bin.add(glupload)
                    video_bin.add(glcolorconvert)
                    video_bin.add(self.gtksink)
                    glupload.link(glcolorconvert)
                    glcolorconvert.link(self.gtksink)

                    # Add ghost pad
                    pad = glupload.get_static_pad("sink")
                    ghost_pad = Gst.GhostPad.new("sink", pad)
                    video_bin.add_pad(ghost_pad)

                    self.player.set_property("video-sink", video_bin)
                    print("Using hardware-accelerated video pipeline")
                else:
                    # Fallback to software rendering
                    self.player.set_property("video-sink", self.gtksink)
                    print("Using software video rendering")
            except Exception as e:
                print(f"Could not setup hardware acceleration: {e}")
                self.player.set_property("video-sink", self.gtksink)

            paintable = self.gtksink.get_property("paintable")
        else:
            print("Warning: No GTK sink available")
            paintable = None

        # Create subtitle renderer
        self.subtitle_renderer = SubtitleRenderer()

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
        if paintable:
            self.video_picture.set_paintable(paintable)
        self.video_picture.set_vexpand(True)
        self.video_picture.set_can_shrink(True)
        self.overlay.set_child(self.video_picture)

        # Subtitle overlay (drawing area)
        # Only redraw when subtitle actually changes for better performance
        self.subtitle_drawing_area = Gtk.DrawingArea()
        self.subtitle_drawing_area.set_draw_func(self._draw_subtitle)
        self.subtitle_drawing_area.set_vexpand(True)
        self.subtitle_drawing_area.set_hexpand(True)
        # Make drawing area transparent and only visible when needed
        self.subtitle_drawing_area.set_opacity(1.0)
        self.overlay.add_overlay(self.subtitle_drawing_area)

        # Control bar
        self._build_controls()

        # Setup GStreamer bus
        bus = self.player.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_gst_message)

        # Update timer - use 250ms for better performance
        GLib.timeout_add(250, self._update_position)

    def _build_controls(self):
        """Build compact video control bar with timeline and controls on same level."""
        controls_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        controls_box.add_css_class("toolbar")
        controls_box.add_css_class("osd")
        controls_box.set_margin_start(6)
        controls_box.set_margin_end(6)
        controls_box.set_margin_top(6)
        controls_box.set_margin_bottom(6)
        self.append(controls_box)

        # Playback controls on the left
        playback_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        playback_box.add_css_class("linked")
        controls_box.append(playback_box)

        # Skip backward button
        skip_back_button = Gtk.Button()
        skip_back_button.set_icon_name("media-seek-backward-symbolic")
        skip_back_button.set_tooltip_text("Skip backward 5 seconds")
        skip_back_button.connect("clicked", lambda b: self.skip(-5000))
        playback_box.append(skip_back_button)

        # Play/Pause button
        self.play_button = Gtk.Button()
        self.play_button.set_icon_name("media-playback-start-symbolic")
        self.play_button.set_tooltip_text("Play/Pause (Space)")
        self.play_button.connect("clicked", self._on_play_pause_clicked)
        playback_box.append(self.play_button)

        # Skip forward button
        skip_forward_button = Gtk.Button()
        skip_forward_button.set_icon_name("media-seek-forward-symbolic")
        skip_forward_button.set_tooltip_text("Skip forward 5 seconds")
        skip_forward_button.connect("clicked", lambda b: self.skip(5000))
        playback_box.append(skip_forward_button)

        # Current time label
        self.time_label = Gtk.Label(label="0:00")
        self.time_label.add_css_class("numeric")
        self.time_label.set_width_chars(5)
        self.time_label.set_margin_start(6)
        controls_box.append(self.time_label)

        # Timeline scale - takes up remaining space
        self.timeline_scale = Gtk.Scale()
        self.timeline_scale.set_range(0, 100)
        self.timeline_scale.set_value(0)
        self.timeline_scale.set_draw_value(False)
        self.timeline_scale.set_hexpand(True)
        self.timeline_scale.connect("change-value", self._on_timeline_seek)
        controls_box.append(self.timeline_scale)

        # Duration label
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
        subtitle_size_button = Gtk.MenuButton()
        subtitle_size_button.set_icon_name("format-text-bold-symbolic")
        subtitle_size_button.set_tooltip_text("Subtitle Size")
        
        # Create popover content
        popover = Gtk.Popover()
        popover_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        popover_box.set_margin_start(12)
        popover_box.set_margin_end(12)
        popover_box.set_margin_top(12)
        popover_box.set_margin_bottom(12)
        
        # Label
        scale_label = Gtk.Label(label="Subtitle Size")
        scale_label.add_css_class("heading")
        popover_box.append(scale_label)
        
        # Scale slider (0.1 to 1.5, default 0.75)
        scale_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.subtitle_scale_slider = Gtk.Scale()
        self.subtitle_scale_slider.set_range(0.1, 1.5)
        self.subtitle_scale_slider.set_value(0.75)
        self.subtitle_scale_slider.set_draw_value(True)
        self.subtitle_scale_slider.set_value_pos(Gtk.PositionType.RIGHT)
        self.subtitle_scale_slider.set_digits(2)
        self.subtitle_scale_slider.set_size_request(200, -1)
        self.subtitle_scale_slider.connect("value-changed", self._on_subtitle_scale_changed)
        
        # Add marks for reference points
        self.subtitle_scale_slider.add_mark(0.1, Gtk.PositionType.BOTTOM, None)
        self.subtitle_scale_slider.add_mark(0.75, Gtk.PositionType.BOTTOM, "Default")
        self.subtitle_scale_slider.add_mark(1.5, Gtk.PositionType.BOTTOM, None)
        
        scale_box.append(self.subtitle_scale_slider)
        popover_box.append(scale_box)
        
        # Reset button
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
            "GStreamer is required for video playback. Please install the required GStreamer packages."
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
        flags |= 0x00000004  # Enable TEXT flag
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
            return False  # Stop timeout
        return True  # Try again

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

        # Use ACCURATE flag for precise seeking, but allow KEY_UNIT for performance
        self.player.seek_simple(
            Gst.Format.TIME,
            Gst.SeekFlags.FLUSH | Gst.SeekFlags.ACCURATE,
            int(position_sec * Gst.SECOND),
        )

        # Update subtitle immediately after seek
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

            # Update subtitle
            self._update_current_subtitle(pos_sec)

        return True

    def _update_current_subtitle(self, position_sec: float):
        """Update the currently displayed subtitle based on position."""
        # Don't show external subtitles if embedded subtitles are active
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

        # Optimize: Check current subtitle first before searching
        if self.current_subtitle:
            start_ms = self.current_subtitle.start_time.total_milliseconds
            end_ms = self.current_subtitle.end_time.total_milliseconds
            if start_ms <= position_ms <= end_ms:
                # Still showing the same subtitle
                return

        # Find subtitle at current position using binary search for better performance
        new_subtitle = self._find_subtitle_at_position(position_ms)

        # Update only if changed
        if new_subtitle != self.current_subtitle:
            self.current_subtitle = new_subtitle
            self.subtitle_drawing_area.queue_draw()

    def _find_subtitle_at_position(self, position_ms: float):
        """Find subtitle at given position using binary search."""
        if not self.document or not self.document.entries:
            return None

        entries = self.document.entries
        left, right = 0, len(entries) - 1

        # Binary search to find the approximate position
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

        # Check nearby entries (in case of overlapping subtitles)
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
        """Draw subtitle overlay - optimized to reduce GPU usage."""
        if not self.current_subtitle:
            # Clear the drawing area when no subtitle
            cr.set_operator(cairo.Operator.CLEAR)
            cr.paint()
            cr.set_operator(cairo.Operator.OVER)
            return

        # Clear background - make it transparent
        cr.set_operator(cairo.Operator.CLEAR)
        cr.paint()
        cr.set_operator(cairo.Operator.OVER)

        # Get actual video dimensions for proper scaling
        video_width = self._video_width if self._video_width > 0 else width
        video_height = self._video_height if self._video_height > 0 else height

        # Debug: Log dimensions once per subtitle change
        if not hasattr(
            self, "_last_logged_subtitle"
        ) or self._last_logged_subtitle != id(self.current_subtitle):
            print(
                f"[Video Display] Widget size: {width}x{height}, "
                f"Video resolution: {self._video_width}x{self._video_height}"
            )
            self._last_logged_subtitle = id(self.current_subtitle)

        # Calculate the actual video display area (respecting aspect ratio)
        if self._video_width > 0 and self._video_height > 0:
            video_aspect = self._video_width / self._video_height
            widget_aspect = width / height if height > 0 else 1.0

            if video_aspect > widget_aspect:
                # Video is wider - fit to width
                display_width = width
                display_height = width / video_aspect
                x_offset = 0
                y_offset = (height - display_height) / 2
            else:
                # Video is taller - fit to height
                display_width = height * video_aspect
                display_height = height
                x_offset = (width - display_width) / 2
                y_offset = 0

            # Translate context to video display area
            cr.translate(x_offset, y_offset)

            # IMPORTANT: Use display_height (actual video display area) for font scaling
            # This ensures fonts scale based on how large the video is actually shown,
            # not the entire widget area
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
            # Fallback when video dimensions not available
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

    def _format_time(self, seconds: float) -> str:
        """Format time in seconds to H:MM:SS or M:SS."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)

        if hours > 0:
            return f"{hours}:{minutes:02d}:{secs:02d}"
        return f"{minutes}:{secs:02d}"

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
        self.subtitle_renderer.subtitle_scale = value
        # Force redraw of current subtitle
        self.subtitle_drawing_area.queue_draw()

    def _on_gst_message(self, bus, message):
        """Handle GStreamer bus messages."""
        t = message.type

        if t == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            print(f"GStreamer Error: {err}, {debug}")
            self.pause()

        elif t == Gst.MessageType.EOS:
            # End of stream
            self.pause()
            self.seek(0)

        elif t == Gst.MessageType.STATE_CHANGED:
            # Query video dimensions when state changes to PAUSED or PLAYING
            if message.src == self.player:
                old_state, new_state, pending = message.parse_state_changed()
                if new_state in (Gst.State.PAUSED, Gst.State.PLAYING):
                    self._query_video_dimensions()

        return True

    def _query_video_dimensions(self):
        """Query actual video dimensions from the stream."""
        if not self.player:
            return

        # Try to get video dimensions from the video sink pad
        try:
            # Get the video sink pad
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
                            print(
                                f"[Video Dimensions] Detected from stream: {width}x{height}"
                            )
                            return
        except Exception as e:
            print(f"Error querying video dimensions: {e}")

        # Fallback: try to query from paintable
        if self.gtksink:
            try:
                paintable = self.gtksink.get_property("paintable")
                if paintable:
                    width = paintable.get_intrinsic_width()
                    height = paintable.get_intrinsic_height()
                    if width > 0 and height > 0:
                        self._video_width = width
                        self._video_height = height
                        print(
                            f"[Video Dimensions] Detected from paintable: {width}x{height}"
                        )
            except Exception as e:
                print(f"Error getting dimensions from paintable: {e}")
    
    def _detect_tracks(self):
        """Detect available audio and subtitle tracks."""
        if not self.player:
            return False
        
        # Get number of tracks
        n_audio = self.player.get_property("n-audio")
        n_text = self.player.get_property("n-text")
        
        print(f"[Track Detection] Found {n_audio} audio tracks, {n_text} subtitle tracks")
        
        if n_audio == 0 and n_text == 0:
            return True  # Try again
        
        # Get audio tracks
        self._audio_tracks = []
        for i in range(n_audio):
            track_info = self._get_audio_track_info(i)
            self._audio_tracks.append(track_info)
            print(f"[Audio Track {i}] {track_info}")
        
        # Get subtitle tracks
        self._subtitle_tracks = []
        for i in range(n_text):
            track_info = self._get_subtitle_track_info(i)
            self._subtitle_tracks.append(track_info)
            print(f"[Subtitle Track {i}] {track_info}")
        
        # Get current tracks
        self._current_audio_track = self.player.get_property("current-audio")
        self._current_subtitle_track = self.player.get_property("current-text")
        
        print(f"[Track Detection] Current audio: {self._current_audio_track}, subtitle: {self._current_subtitle_track}")
        
        return False  # Stop timeout
    
    def _get_audio_track_info(self, index):
        """Get information about an audio track."""
        track_info = {'index': index, 'title': None, 'language': None, 'codec': None}
        
        try:
            # Get tags using emit signal
            tags = self.player.emit("get-audio-tags", index)
            if tags:
                # Get language
                success, language = tags.get_string(Gst.TAG_LANGUAGE_CODE)
                if success:
                    track_info['language'] = language
                
                # Get title
                success, title = tags.get_string(Gst.TAG_TITLE)
                if success:
                    track_info['title'] = title
                
                # Get codec
                success, codec = tags.get_string(Gst.TAG_AUDIO_CODEC)
                if success:
                    track_info['codec'] = codec
        except Exception as e:
            print(f"Error getting audio track {index} info: {e}")
        
        return track_info
    
    def _get_subtitle_track_info(self, index):
        """Get information about a subtitle track."""
        track_info = {'index': index, 'title': None, 'language': None, 'codec': None}
        
        try:
            # Get tags using emit signal
            tags = self.player.emit("get-text-tags", index)
            if tags:
                # Get language
                success, language = tags.get_string(Gst.TAG_LANGUAGE_CODE)
                if success:
                    track_info['language'] = language
                
                # Get title
                success, title = tags.get_string(Gst.TAG_TITLE)
                if success:
                    track_info['title'] = title
                
                # Get codec
                success, codec = tags.get_string(Gst.TAG_SUBTITLE_CODEC)
                if not success:
                    success, codec = tags.get_string(Gst.TAG_CODEC)
                if success:
                    track_info['codec'] = codec
        except Exception as e:
            print(f"Error getting subtitle track {index} info: {e}")
        
        return track_info
    
    def get_available_tracks(self):
        """Get list of available audio and subtitle tracks.
        
        Returns:
            tuple: (audio_tracks, subtitle_tracks) - lists of track info dicts
        """
        return (self._audio_tracks.copy(), self._subtitle_tracks.copy())
    
    def set_audio_track(self, track_index):
        """Set the current audio track.
        
        Args:
            track_index: Index of audio track to select (-1 to disable)
        """
        if not self.player:
            return
        
        print(f"[Track Switch] Setting audio track to {track_index}")
        self.player.set_property("current-audio", track_index)
        self._current_audio_track = track_index
    
    def set_subtitle_track(self, track_index):
        """Set the current subtitle track.
        
        Args:
            track_index: Index of subtitle track to select (-1 to disable)
        """
        if not self.player:
            return
        
        print(f"[Track Switch] Setting subtitle track to {track_index}")
        
        if track_index >= 0:
            # Enable embedded subtitles
            self.player.set_property("current-text", track_index)
            self._current_subtitle_track = track_index
            self._embedded_subtitle_active = True
            
            # Disable our custom subtitle rendering when using embedded
            self.current_subtitle = None
            self.subtitle_drawing_area.queue_draw()
        else:
            # Disable embedded subtitles
            self.player.set_property("current-text", -1)
            self._current_subtitle_track = -1
            self._embedded_subtitle_active = False
    
    def has_embedded_tracks(self):
        """Check if video has embedded audio or subtitle tracks.
        
        Returns:
            tuple: (has_audio_tracks, has_subtitle_tracks)
        """
        return (len(self._audio_tracks) > 0, len(self._subtitle_tracks) > 0)
    
    def extract_subtitle_track(self, track_index, output_path, callback=None):
        """Extract a subtitle track from the video to a file.
        
        Args:
            track_index: Index of the subtitle track to extract
            output_path: Path where to save the extracted subtitle file
            callback: Optional callback function(success, error_message) when done
        """
        if not self.player or not self.video_uri:
            if callback:
                callback(False, "No video loaded")
            return
        
        if track_index < 0 or track_index >= len(self._subtitle_tracks):
            if callback:
                callback(False, "Invalid track index")
            return
        
        # Extract subtitle in a background thread to avoid blocking UI
        import threading
        
        def extract_thread():
            try:
                success = self._extract_subtitle_gstreamer(track_index, output_path)
                if callback:
                    GLib.idle_add(callback, success, None if success else "Extraction failed")
            except Exception as e:
                if callback:
                    GLib.idle_add(callback, False, str(e))
        
        thread = threading.Thread(target=extract_thread, daemon=True)
        thread.start()
    
    def _extract_subtitle_gstreamer(self, track_index, output_path):
        """Extract subtitle using GStreamer pipeline.
        
        This uses a secondary pipeline to extract the subtitle track.
        """
        try:
            # Parse the video URI to get file path
            if self.video_uri.startswith("file://"):
                video_path = self.video_uri[7:]  # Remove file:// prefix
            else:
                video_path = self.video_uri
            
            print(f"[Subtitle Extract] Extracting track {track_index} to {output_path}")
            
            # Create extraction pipeline
            # We use decodebin and connect to the text pad for the specific track
            pipeline_desc = f'filesrc location="{video_path}" ! decodebin name=d ! queue ! subparse ! filesink location="{output_path}"'
            
            extract_pipeline = Gst.parse_launch(pipeline_desc)
            
            # Set to PAUSED to preroll
            extract_pipeline.set_state(Gst.State.PAUSED)
            extract_pipeline.get_state(5 * Gst.SECOND)
            
            # Try to select the subtitle track
            # Note: This is a simplified approach. In practice, subtitle extraction
            # from containers is complex and may require using tools like ffmpeg
            
            # For now, we'll use a simpler approach: read subtitles using playbin
            return self._extract_using_playbin(track_index, output_path)
            
        except Exception as e:
            print(f"[Subtitle Extract] Error: {e}")
            return False
    
    def _extract_using_playbin(self, track_index, output_path):
        """Extract subtitle by reading from playbin text pad.
        
        This is a workaround since direct subtitle extraction from containers
        is complex in GStreamer.
        """
        import subprocess
        
        # Use ffmpeg for reliable subtitle extraction
        # This is more reliable than pure GStreamer for this use case
        if self.video_uri.startswith("file://"):
            video_path = self.video_uri[7:]
        else:
            video_path = self.video_uri
        
        try:
            # ffmpeg command to extract subtitle track
            # -map 0:s:track_index selects the subtitle track
            cmd = [
                'ffmpeg',
                '-i', video_path,
                '-map', f'0:s:{track_index}',
                '-c:s', 'srt',  # Convert to SRT format
                '-y',  # Overwrite output
                output_path
            ]
            
            print(f"[Subtitle Extract] Running: {' '.join(cmd)}")
            
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30
            )
            
            if result.returncode == 0:
                print(f"[Subtitle Extract] Success: {output_path}")
                return True
            else:
                error = result.stderr.decode('utf-8', errors='ignore')
                print(f"[Subtitle Extract] Failed: {error}")
                return False
                
        except FileNotFoundError:
            print("[Subtitle Extract] ffmpeg not found. Please install ffmpeg.")
            return False
        except subprocess.TimeoutExpired:
            print("[Subtitle Extract] Extraction timeout")
            return False
        except Exception as e:
            print(f"[Subtitle Extract] Error: {e}")
            return False
