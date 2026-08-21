"""
Custom video timeline with zooming, panning and an optional waveform.

The logic lives in :class:`TimelineModel`, a pure-Python class with no GTK
dependency, so the zoom/pan/tick math is headless-testable. The GTK side
(:class:`TimelineWidget`) is a ``Gtk.DrawingArea`` that renders the model and
translates pointer gestures into seeks:

* left click            -> exact seek to the clicked time
* click-drag            -> scrub (throttled live seeks + one final exact seek)
* Ctrl+scroll           -> zoom around the cursor (x1.25 per notch)
* Shift+scroll          -> pan the view
* plain vertical scroll -> seek +-1 s

The widget never talks to the player directly: it emits ``seek-requested``
(live/intermediate) and ``position-picked`` (click / final release) and the
player decides what to do with them.

Drawing goes through cairo exclusively: recent GTK hands the draw function a
``cairo.Context`` directly, older versions a ``Gtk.Snapshot`` from which a
cairo context is obtained via ``append_cairo`` — one code path covers both.
"""

import bisect
import math

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("PangoCairo", "1.0")

from gi.repository import Gdk, GLib, GObject, Graphene, Gtk, PangoCairo  # noqa: E402

# ---------------------------------------------------------------------- #
# Pure model (no GTK usage until the widget section below)
# ---------------------------------------------------------------------- #

# Smallest visible time window (seconds); zooming in further is a no-op.
MIN_WINDOW = 0.5

# Ruler tick candidates (seconds). The first step whose pixel spacing reaches
# MIN_TICK_PX at the current zoom is used, keeping ticks ~60-120 px apart.
TICK_LADDER = (0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60, 120, 300, 600, 1200, 3600)
MIN_TICK_PX = 60.0


class TimelineModel:
    """Pure state + math for the timeline: view window, peaks, regions.

    ``view_start``/``view_end`` describe the visible time window (zooming
    shrinks it); ``position`` is the playback position used for the playhead.
    """

    def __init__(self):
        self.duration = 0.0
        self.position = 0.0
        self.view_start = 0.0
        self.view_end = 0.0
        # Optional waveform: list of (min, max) sample pairs per bucket and
        # how many buckets cover one second.
        self.peaks = None
        self.peaks_per_second = 0.0
        # Subtitle regions as (start_s, end_s) pairs.
        self.subtitle_regions = []

    # -- state setters ---------------------------------------------------- #

    def set_duration(self, duration: float):
        """Set the media duration and reset the view to the full range."""
        self.duration = max(0.0, float(duration or 0.0))
        self.view_start = 0.0
        self.view_end = self.duration
        self.position = min(self.position, self.duration)

    def set_position(self, position: float):
        """Set the playhead position (clamped to the media range)."""
        self.position = max(0.0, min(float(position or 0.0), self.duration))

    def set_peaks(self, peaks, peaks_per_second: float):
        """Attach waveform peaks (or clear them with ``peaks=None``)."""
        self.peaks = list(peaks) if peaks else None
        self.peaks_per_second = float(peaks_per_second or 0.0)

    def set_subtitle_regions(self, regions):
        """Set subtitle regions as an iterable of (start_s, end_s) pairs."""
        self.subtitle_regions = [(float(s), float(e)) for s, e in regions or []]

    # -- view window ------------------------------------------------------- #

    def window(self) -> float:
        """Visible span in seconds."""
        return self.view_end - self.view_start

    def px_per_second(self, width_px: float) -> float:
        """Pixels per second at the current zoom for a widget of this width."""
        window = self.window()
        if width_px <= 0 or window <= 0:
            return 0.0
        return width_px / window

    def _clamp_view(self):
        """Clamp the view window into [0, duration] with MIN_WINDOW..full."""
        if self.duration <= 0:
            self.view_start = 0.0
            self.view_end = 0.0
            return
        window = self.view_end - self.view_start
        window = max(MIN_WINDOW, min(window, self.duration))
        self.view_start = max(0.0, min(self.view_start, self.duration - window))
        self.view_end = self.view_start + window

    def set_zoom_window(self, start: float, end: float):
        """Set the visible window explicitly (clamped and size-limited)."""
        self.view_start = float(start)
        self.view_end = float(end)
        self._clamp_view()

    def zoom(self, factor: float, anchor_time: float):
        """Zoom by ``factor`` (>1 zooms in) keeping *anchor_time* fixed.

        The anchor stays at the same fraction across the view, so the time
        under the cursor does not move. The window is clamped to
        [MIN_WINDOW, duration] afterwards.
        """
        if factor <= 0 or self.duration <= 0:
            return
        window = self.window()
        if window <= 0:
            return
        fraction = self.fraction_at(anchor_time)
        new_window = max(MIN_WINDOW, min(window / factor, self.duration))
        self.view_start = float(anchor_time) - fraction * new_window
        self.view_end = self.view_start + new_window
        self._clamp_view()

    def pan(self, delta_s: float):
        """Shift the view by ``delta_s`` seconds (clamped to the media)."""
        self.view_start += float(delta_s)
        self.view_end += float(delta_s)
        self._clamp_view()

    # -- coordinate mapping ------------------------------------------------- #

    def time_at(self, fraction: float) -> float:
        """Map a 0-1 fraction across the view to an absolute time."""
        return self.view_start + float(fraction) * self.window()

    def fraction_at(self, time: float) -> float:
        """Map an absolute time to its 0-1 fraction across the view."""
        window = self.window()
        if window <= 0:
            return 0.0
        return (float(time) - self.view_start) / window

    def time_at_px(self, x: float, width_px: float) -> float:
        """Map a widget x coordinate to an absolute time (clamped)."""
        if width_px <= 0:
            return self.view_start
        fraction = min(max(x / width_px, 0.0), 1.0)
        return self.time_at(fraction)

    # -- ruler / waveform helpers ------------------------------------------- #

    def tick_interval(self, px_per_second: float) -> float:
        """Adaptive ruler tick spacing for the given pixel density."""
        for step in TICK_LADDER:
            if step * px_per_second >= MIN_TICK_PX:
                return step
        return TICK_LADDER[-1]

    def bucket_range(self):
        """Return the ``(first, last)`` peak buckets intersecting the view.

        ``last`` is exclusive; slicing ``peaks[first:last]`` covers the view.
        """
        if not self.peaks or self.peaks_per_second <= 0:
            return (0, 0)
        first = min(
            len(self.peaks),
            max(0, int(math.floor(self.view_start * self.peaks_per_second))),
        )
        last = min(
            len(self.peaks),
            int(math.ceil(self.view_end * self.peaks_per_second)),
        )
        return (first, max(first, last))

    def visible_regions(self):
        """Subtitle regions intersecting the view, clamped to media + view.

        Regions are clipped to [0, duration] and to the visible window;
        degenerate (inverted or empty) regions are dropped.
        """
        duration = self.duration
        out = []
        for start, end in self.subtitle_regions:
            s = max(0.0, start)
            if duration <= 0:
                # No media yet: keep regions unclamped (nothing to clip to).
                if end > s:
                    out.append((s, end))
                continue
            e = min(end, duration)
            s = max(s, self.view_start)
            e = min(e, self.view_end)
            if e > s:
                out.append((s, e))
        return out


def format_ruler_time(seconds: float, show_millis: bool) -> str:
    """Format a ruler/hover label as ``mm:ss`` or ``mm:ss.mmm``."""
    total = max(0, int(round(float(seconds) * 1000)))
    hours, rem = divmod(total, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1_000)
    if hours > 0:
        base = f"{hours}:{minutes:02d}:{secs:02d}"
    else:
        base = f"{minutes}:{secs:02d}"
    return f"{base}.{millis:03d}" if show_millis else base


def active_entry_at(entries, seconds: float) -> int:
    """Index of the subtitle entry active at *seconds*, or -1 (binary search).

    An entry is active when ``start <= seconds < end``. ``entries`` is assumed
    to be sorted by start time (the normal subtitle order); with heavily
    overlapping entries only the last entry starting before *seconds* is
    considered.
    """
    if not entries:
        return -1
    t = max(0.0, float(seconds))
    starts = [e.start_time.total_milliseconds / 1000.0 for e in entries]
    idx = bisect.bisect_right(starts, t) - 1
    if idx < 0:
        return -1
    end = entries[idx].end_time.total_milliseconds / 1000.0
    return idx if t < end else -1


# ---------------------------------------------------------------------- #
# GTK widget
# ---------------------------------------------------------------------- #

# Widget heights (px): waveform strip vs plain ruler/regions strip.
HEIGHT_WAVEFORM = 64
HEIGHT_PLAIN = 36
RULER_HEIGHT = 16

ZOOM_STEP = 1.25
SCRUB_SEEK_INTERVAL_MS = 150
SCROLL_SEEK_SECONDS = 1.0
PAN_FRACTION_PER_NOTCH = 0.1

# Theme-agnostic palette (kept deliberately dark-neutral: the timeline sits on
# the OSD toolbar and must work on both light and dark libadwaita themes).
COLOR_BACKGROUND = (0.10, 0.10, 0.12, 1.0)
COLOR_WAVE = (0.45, 0.65, 0.95, 0.90)
COLOR_WAVE_CENTER = (0.45, 0.65, 0.95, 0.35)
COLOR_REGION = (0.35, 0.55, 0.85, 0.30)
COLOR_REGION_EDGE = (0.35, 0.55, 0.85, 0.55)
COLOR_TICK = (0.62, 0.62, 0.66, 0.90)
COLOR_RULER_TEXT = (0.72, 0.72, 0.76, 0.95)
COLOR_PLAYHEAD = (0.95, 0.30, 0.30, 1.0)
COLOR_HOVER = (0.90, 0.90, 0.90, 0.55)
COLOR_NO_DATA = (0.0, 0.0, 0.0, 0.35)


class TimelineWidget(Gtk.DrawingArea):
    """Custom timeline renderer (see module docstring for interactions)."""

    __gtype_name__ = "GsubTimeline"

    __gsignals__ = {
        # Intermediate seeks (throttled scrub, scroll wheel).
        "seek-requested": (GObject.SignalFlags.RUN_FIRST, None, (float,)),
        # A definitive pick: click or drag release (exact seek).
        "position-picked": (GObject.SignalFlags.RUN_FIRST, None, (float,)),
        # Emitted around a drag so the player can suppress its own position
        # updates while the user controls the playhead.
        "scrub-started": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "scrub-ended": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self):
        super().__init__()
        self.model = TimelineModel()
        self._waveform_enabled = False
        self._hover_x = None
        self._scrubbing = False
        self._scrub_position = None
        self._last_scrub_seek = 0
        self._layout = None

        self.set_hexpand(True)
        self._apply_height()

        self.set_draw_func(self._draw)

        drag = Gtk.GestureDrag()
        drag.set_button(1)
        drag.connect("drag-begin", self._on_drag_begin)
        drag.connect("drag-update", self._on_drag_update)
        drag.connect("drag-end", self._on_drag_end)
        self.add_controller(drag)

        motion = Gtk.EventControllerMotion()
        motion.connect("enter", self._on_motion_enter)
        motion.connect("motion", self._on_motion)
        motion.connect("leave", self._on_motion_leave)
        self.add_controller(motion)

        scroll = Gtk.EventControllerScroll.new(
            Gtk.EventControllerScrollFlags.VERTICAL
            | Gtk.EventControllerScrollFlags.HORIZONTAL
        )
        scroll.connect("scroll", self._on_scroll)
        self.add_controller(scroll)

    # -- public API --------------------------------------------------------- #

    def set_waveform_enabled(self, enabled: bool):
        """Show the taller waveform strip (or the compact ruler-only strip)."""
        self._waveform_enabled = bool(enabled)
        self._apply_height()
        self.queue_draw()

    def set_duration(self, duration: float):
        self.model.set_duration(duration)
        self.queue_draw()

    def set_position(self, position: float):
        """Update the playhead (ignored while the user is scrubbing)."""
        if self._scrubbing:
            return
        self.model.set_position(position)
        self.queue_draw()

    def set_peaks(self, peaks, peaks_per_second: float):
        self.model.set_peaks(peaks, peaks_per_second)
        self.queue_draw()

    def set_subtitle_regions(self, regions):
        self.model.set_subtitle_regions(regions)
        self.queue_draw()

    def clear_peaks(self):
        self.set_peaks(None, 0.0)

    def _apply_height(self):
        height = HEIGHT_WAVEFORM if self._waveform_enabled else HEIGHT_PLAIN
        self.set_size_request(-1, height)

    # -- gestures ------------------------------------------------------------ #

    def _time_at_x(self, x: float) -> float:
        return self.model.time_at_px(x, self.get_width())

    @staticmethod
    def _absolute_x(gesture, offset_x) -> float:
        """Drag gestures report offsets; convert to widget coordinates."""
        ok, start_x, _start_y = gesture.get_start_point()
        base = start_x if ok else 0.0
        widget = gesture.get_widget()
        width = widget.get_width() if widget is not None else 0
        if width <= 0:
            return 0.0
        return min(max(base + offset_x, 0.0), float(width))

    def _on_drag_begin(self, _gesture, _start_x, _start_y):
        self._scrubbing = True
        self._scrub_position = None
        self._last_scrub_seek = 0
        self.emit("scrub-started")
        self.queue_draw()

    def _on_drag_update(self, gesture, offset_x, _offset_y):
        if not self._scrubbing:
            return
        self._scrub_position = self._time_at_x(self._absolute_x(gesture, offset_x))
        now = GLib.get_monotonic_time() // 1000
        if now - self._last_scrub_seek >= SCRUB_SEEK_INTERVAL_MS:
            self._last_scrub_seek = now
            self.emit("seek-requested", self._scrub_position)
        self.queue_draw()

    def _on_drag_end(self, gesture, offset_x, _offset_y):
        if not self._scrubbing:
            return
        final = self._time_at_x(self._absolute_x(gesture, offset_x))
        self._scrubbing = False
        self._scrub_position = None
        self.emit("position-picked", final)
        self.emit("scrub-ended")
        self.queue_draw()

    def _on_motion_enter(self, _motion, x, _y):
        self._hover_x = x
        self.set_cursor_from_name("pointer")
        self.queue_draw()

    def _on_motion(self, _motion, x, _y):
        self._hover_x = x
        self.queue_draw()

    def _on_motion_leave(self, _motion):
        self._hover_x = None
        self.set_cursor(None)
        self.queue_draw()

    def _on_scroll(self, controller, dx, dy):
        state = controller.get_current_event_state()
        ctrl = state & Gdk.ModifierType.CONTROL_MASK
        shift = state & Gdk.ModifierType.SHIFT_MASK
        if ctrl:
            # Zoom around the cursor position (playhead as the fallback).
            anchor = (
                self._time_at_x(self._hover_x)
                if self._hover_x is not None
                else self.model.position
            )
            delta = dy if abs(dy) >= abs(dx) else dx
            self.model.zoom(ZOOM_STEP ** (-delta), anchor)
            self.queue_draw()
            return True
        if shift or (dx != 0 and dy == 0):
            delta = (dy if dy else dx) * PAN_FRACTION_PER_NOTCH * self.model.window()
            self.model.pan(-delta)
            self.queue_draw()
            return True
        if dy:
            # Scroll up seeks back, scroll down forward (mpv wheel default).
            self.emit(
                "seek-requested",
                self.model.position - math.copysign(SCROLL_SEEK_SECONDS, dy),
            )
            return True
        return False

    # -- drawing -------------------------------------------------------------- #

    def _draw(self, _area, target, width, height):
        if width <= 0 or height <= 0:
            return
        # Recent GTK hands the draw function a cairo context directly; older
        # versions pass a Gtk.Snapshot, from which we take a cairo context.
        if hasattr(target, "append_cairo"):
            cr = target.append_cairo(Graphene.Rect().init(0, 0, width, height))
        else:
            cr = target

        model = self.model
        self._fill_rect(cr, 0, 0, width, height, COLOR_BACKGROUND)

        window = model.window()
        if model.duration <= 0 or window <= 0:
            return

        def x_at(t):
            return model.fraction_at(t) * width

        content_h = height - RULER_HEIGHT
        center_y = content_h / 2.0

        self._draw_waveform(cr, width, content_h, center_y)
        self._draw_regions(cr, content_h, x_at)

        # Shade the area not covered by decoded peaks (short decodes).
        if model.peaks and model.peaks_per_second > 0:
            covered = len(model.peaks) / model.peaks_per_second
            if covered < model.view_end:
                self._fill_rect(
                    cr, x_at(covered), 0, width - x_at(covered), content_h,
                    COLOR_NO_DATA,
                )

        if self._hover_x is not None and not self._scrubbing:
            self._draw_hover(cr, width, height)

        # Playhead (follows the pointer while scrubbing).
        position = (
            self._scrub_position
            if self._scrub_position is not None
            else model.position
        )
        px = x_at(position)
        if 0.0 <= px <= width:
            self._fill_rect(cr, px - 1.0, 0, 2.0, content_h, COLOR_PLAYHEAD)

        self._draw_ruler(cr, width, height, x_at)

    def _draw_waveform(self, cr, width, content_h, center_y):
        model = self.model
        if not self._waveform_enabled or not model.peaks:
            return
        if model.peaks_per_second <= 0 or content_h <= 0:
            return
        pps = model.peaks_per_second
        amp = content_h / 2.0
        # Aggregate min/max over the buckets falling into each pixel column
        # so the work is bounded by the widget width, not the peak count.
        cr.set_source_rgba(*COLOR_WAVE)
        for px in range(int(width)):
            t0 = model.time_at(px / width)
            t1 = model.time_at((px + 1) / width)
            b0 = int(math.floor(t0 * pps))
            b1 = max(b0 + 1, int(math.ceil(t1 * pps)))
            lo, hi = _peak_bounds(model.peaks, b0, b1)
            if lo is None:
                continue
            y0 = center_y - hi / 32768.0 * amp
            y1 = center_y - lo / 32768.0 * amp
            cr.rectangle(px, y0, 1.0, max(y1 - y0, 1.0))
        cr.fill()
        # Faint center line so silence reads as a line, not as nothing.
        self._fill_rect(cr, 0, center_y, width, 1.0, COLOR_WAVE_CENTER)

    def _draw_regions(self, cr, content_h, x_at):
        regions = self.model.visible_regions()
        if not regions or content_h <= 0:
            return
        radius = min(5.0, content_h / 2.0)
        # Translucent fill for all regions in one pass.
        cr.set_source_rgba(*COLOR_REGION)
        for start, end in regions:
            _rounded_rect_path(
                cr, x_at(start), 0.0, max(x_at(end) - x_at(start), 1.0),
                content_h, radius,
            )
        cr.fill()
        # Crisper outline.
        cr.set_source_rgba(*COLOR_REGION_EDGE)
        cr.set_line_width(1.0)
        for start, end in regions:
            w = max(x_at(end) - x_at(start), 1.0)
            _rounded_rect_path(
                cr, x_at(start), 0.5, w, max(content_h - 1.0, 1.0), radius
            )
        cr.stroke()

    def _draw_hover(self, cr, width, height):
        x = self._hover_x
        self._fill_rect(cr, x - 0.5, 0, 1.0, height - RULER_HEIGHT, COLOR_HOVER)
        label = format_ruler_time(self._time_at_x(x), self._show_millis())
        layout = self._pango_layout()
        layout.set_text(label, -1)
        lw, lh = layout.get_pixel_size()
        bubble_w = min(lw + 8.0, width)
        bubble_x = min(max(x - bubble_w / 2.0, 0.0), width - bubble_w)
        self._fill_rect(cr, bubble_x, 0, bubble_w, lh + 4.0, COLOR_BACKGROUND)
        cr.set_source_rgba(*COLOR_RULER_TEXT)
        cr.move_to(bubble_x + 4, 1)
        PangoCairo.show_layout(cr, layout)

    def _draw_ruler(self, cr, width, height, x_at):
        model = self.model
        step = model.tick_interval(model.px_per_second(width))
        first = math.floor(model.view_start / step) * step
        count = int(math.ceil((model.view_end - first) / step)) + 1
        ticks = [first + i * step for i in range(min(count, 1000))]
        show_millis = step < 1.0

        y0 = height - RULER_HEIGHT
        self._fill_rect(cr, 0, y0, width, 1.0, COLOR_TICK)
        cr.set_source_rgba(*COLOR_TICK)
        for t in ticks:
            x = x_at(t)
            if x < -1 or x > width + 1:
                continue
            cr.rectangle(x, y0, 1.0, 4.0)
        cr.fill()

        layout = self._pango_layout()
        cr.set_source_rgba(*COLOR_RULER_TEXT)
        for t in ticks:
            x = x_at(t)
            if x < -1 or x > width + 1:
                continue
            layout.set_text(format_ruler_time(t, show_millis), -1)
            cr.move_to(min(max(x + 3.0, 0.0), max(width - 40.0, 0.0)), y0 + 4)
            PangoCairo.show_layout(cr, layout)

    def _show_millis(self):
        step = self.model.tick_interval(
            self.model.px_per_second(self.get_width())
        )
        return step < 1.0

    def _pango_layout(self):
        if self._layout is None:
            self._layout = self.create_pango_layout("")
            description = self.get_pango_context().get_font_description().copy()
            description.set_size(8 * 1024)
            self._layout.set_font_description(description)
        return self._layout

    @staticmethod
    def _fill_rect(cr, x, y, w, h, rgba_tuple):
        if w <= 0 or h <= 0:
            return
        cr.save()
        cr.set_source_rgba(*rgba_tuple)
        cr.rectangle(x, y, w, h)
        cr.fill()
        cr.restore()


def _rounded_rect_path(cr, x, y, w, h, radius):
    """Append a rounded-rectangle sub-path to a cairo context."""
    r = min(radius, w / 2.0, h / 2.0)
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


def _peak_bounds(peaks, b0, b1):
    """Combined (min, max) of ``peaks[b0:b1]`` (index-safe)."""
    b0 = max(0, b0)
    b1 = min(len(peaks), b1)
    if b1 <= b0:
        return None, None
    lo = min(p[0] for p in peaks[b0:b1])
    hi = max(p[1] for p in peaks[b0:b1])
    return lo, hi
