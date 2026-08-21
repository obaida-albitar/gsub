"""
Custom video timeline with zooming, panning and an optional waveform.

The logic lives in :class:`TimelineModel`, a pure-Python class with no GTK
dependency, so the zoom/pan/tick math is headless-testable. The GTK side
(:class:`TimelineWidget`) is a ``Gtk.DrawingArea`` that renders the model and
translates pointer gestures into seeks:

* left click            -> exact seek to the clicked time
* click-drag            -> scrub (throttled live seeks + one final exact seek)
* middle/right drag     -> pan the view 1:1 with the pointer (click = no-op)
* Ctrl+scroll           -> zoom around the cursor (x1.25 per notch)
* Shift+scroll          -> pan the view
* plain vertical scroll -> seek +-1 s
* Ctrl+click on region  -> select that subtitle entry
* Ctrl+drag on region   -> move it, or resize when grabbed by an edge

The widget never talks to the player directly: it emits ``seek-requested``
(live/intermediate) and ``position-picked`` (click / final release) and the
player decides what to do with them. Region interactions emit
``region-selected`` (Ctrl+click) and ``region-adjusted`` (Ctrl+drag release,
with the committed whole-millisecond bounds).

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

# Region interaction tuning: pointer distance from a region edge that grabs
# the edge for resizing, pointer travel before a Ctrl+press counts as a drag
# (below it the press is a select), and the shortest region a resize allows.
REGION_EDGE_THRESHOLD_PX = 6.0
REGION_DRAG_THRESHOLD_PX = 3.0
MIN_REGION_LENGTH_S = 0.05  # 50 ms


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
        # Subtitle regions as (start_s, end_s, position) triples.
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
        """Set subtitle regions as ``(start_s, end_s, position)`` triples.

        ``position`` is the entry's index in the document (used to route
        region drags back to the right entry); plain ``(start_s, end_s)``
        pairs are tolerated and stored with position -1.
        """
        out = []
        for region in regions or []:
            start, end = float(region[0]), float(region[1])
            position = int(region[2]) if len(region) > 2 else -1
            out.append((start, end, position))
        self.subtitle_regions = out

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
        degenerate (inverted or empty) regions are dropped. The entry
        position is carried along so drags and highlights stay attached.
        """
        duration = self.duration
        out = []
        for start, end, position in self.subtitle_regions:
            s = max(0.0, start)
            if duration <= 0:
                # No media yet: keep regions unclamped (nothing to clip to).
                if end > s:
                    out.append((s, end, position))
                continue
            e = min(end, duration)
            s = max(s, self.view_start)
            e = min(e, self.view_end)
            if e > s:
                out.append((s, e, position))
        return out

    def region_hit(self, seconds: float, width_px: float):
        """Find the region under *seconds*: ``(position, mode)`` or ``None``.

        ``mode`` is ``"resize-start"``/``"resize-end"`` when the time is
        within REGION_EDGE_THRESHOLD_PX (converted to seconds at the current
        zoom) of an edge, ``"move"`` for the region body. With overlapping
        regions the later region wins: it is drawn on top.
        """
        t = float(seconds)
        pps = self.px_per_second(width_px)
        threshold = REGION_EDGE_THRESHOLD_PX / pps if pps > 0 else 0.0
        hit = None
        for start, end, position in self.subtitle_regions:
            if not (start <= t <= end):
                continue
            if t - start <= threshold:
                mode = "resize-start"
            elif end - t <= threshold:
                mode = "resize-end"
            else:
                mode = "move"
            hit = (position, mode)
        return hit


def move_region_times(start_s, end_s, delta_s, duration_s):
    """Shift a region by *delta_s*, keeping its length, clamped to the media."""
    length = end_s - start_s
    limit = max(float(duration_s), length)
    new_start = min(max(start_s + delta_s, 0.0), limit - length)
    return new_start, new_start + length


def resize_region_times(start_s, end_s, edge, time_s, duration_s):
    """Move one region edge (``"start"``/``"end"``) to *time_s*.

    The other edge stays put; MIN_REGION_LENGTH_S is always enforced and the
    region is clamped to [0, duration].
    """
    duration_s = float(duration_s)
    if edge == "start":
        new_start = min(max(float(time_s), 0.0), end_s - MIN_REGION_LENGTH_S)
        return new_start, end_s
    min_end = start_s + MIN_REGION_LENGTH_S
    new_end = max(float(time_s), min_end)
    return start_s, min(new_end, max(duration_s, min_end))


def round_region_ms(start_s, end_s, duration_s, preserve_length=False):
    """Round tentative region bounds to committed whole milliseconds.

    Returns ``(start_ms, end_ms)`` clamped to start >= 0, end <= duration and
    end > start. With ``preserve_length`` (region moves) the original length
    survives the rounding; otherwise a minimum of MIN_REGION_LENGTH_S is
    enforced (resizes).
    """
    duration_ms = max(0, int(round(float(duration_s) * 1000)))
    length_ms = max(1, int(round((float(end_s) - float(start_s)) * 1000)))
    start_ms = max(0, int(round(float(start_s) * 1000)))
    if preserve_length:
        start_ms = min(start_ms, max(0, duration_ms - length_ms))
        return start_ms, start_ms + length_ms
    end_ms = max(int(round(float(end_s) * 1000)), start_ms + int(round(MIN_REGION_LENGTH_S * 1000)))
    if duration_ms > 0:
        end_ms = min(end_ms, max(duration_ms, start_ms + 1))
    return start_ms, end_ms


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
COLOR_REGION_SELECTED = (0.45, 0.65, 0.95, 0.55)
COLOR_REGION_EDGE_SELECTED = (0.45, 0.65, 0.95, 0.95)
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
        # A region was Ctrl+dragged: committed whole-ms bounds.
        "region-adjusted": (GObject.SignalFlags.RUN_FIRST, None, (int, int, int)),
        # A region was Ctrl+clicked (no drag): entry to select.
        "region-selected": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
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
        # Middle/right-button view panning (1:1 with pointer movement).
        self._panning = False
        self._pan_last_offset_x = 0.0
        # Region interaction state: entry whose region is selected (-1 = none)
        # and the active Ctrl-drag (a dict, see _begin_region_drag).
        self._selected_position = -1
        self._region_drag = None

        self.set_hexpand(True)
        self._apply_height()

        self.set_draw_func(self._draw)

        drag = Gtk.GestureDrag()
        drag.set_button(1)
        drag.connect("drag-begin", self._on_drag_begin)
        drag.connect("drag-update", self._on_drag_update)
        drag.connect("drag-end", self._on_drag_end)
        self.add_controller(drag)

        # Middle and right buttons both pan (a click without movement, i.e.
        # begin+end with no update, does nothing: no seek, no context menu).
        for button in (2, 3):
            pan = Gtk.GestureDrag()
            pan.set_button(button)
            pan.connect("drag-begin", self._on_pan_begin)
            pan.connect("drag-update", self._on_pan_update)
            pan.connect("drag-end", self._on_pan_end)
            self.add_controller(pan)

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

    def set_selected_position(self, position: int):
        """Highlight the region of the selected entry (-1 clears)."""
        position = int(position)
        if position == self._selected_position:
            return
        self._selected_position = position
        self.queue_draw()

    def clear_peaks(self):
        self.set_peaks(None, 0.0)

    def _apply_height(self):
        height = HEIGHT_WAVEFORM if self._waveform_enabled else HEIGHT_PLAIN
        self.set_size_request(-1, height)

    # -- gestures ------------------------------------------------------------ #

    def _time_at_x(self, x: float) -> float:
        return self.model.time_at_px(x, self.get_width())

    def _absolute_x(self, gesture, offset_x) -> float:
        """Drag gestures report offsets; convert to widget coordinates."""
        ok, start_x, _start_y = gesture.get_start_point()
        base = start_x if ok else 0.0
        width = self.get_width()
        if width <= 0:
            return 0.0
        return min(max(base + offset_x, 0.0), float(width))

    def _set_cursor(self, name):
        if name is None:
            self.set_cursor(None)
        else:
            self.set_cursor_from_name(name)

    # Scrub (plain left button) ------------------------------------------- #

    def _on_drag_begin(self, gesture, start_x, _start_y):
        # Ctrl+press inside a subtitle region starts a region drag instead of
        # a scrub (see _begin_region_drag).
        state = gesture.get_current_event_state()
        if state & Gdk.ModifierType.CONTROL_MASK and self._begin_region_drag(start_x):
            return
        self._scrubbing = True
        self._scrub_position = None
        self._last_scrub_seek = 0
        self.emit("scrub-started")
        self.queue_draw()

    def _on_drag_update(self, gesture, offset_x, offset_y):
        if self._region_drag is not None:
            self._update_region_drag(gesture, offset_x, offset_y)
            return
        if not self._scrubbing:
            return
        self._scrub_position = self._time_at_x(self._absolute_x(gesture, offset_x))
        now = GLib.get_monotonic_time() // 1000
        if now - self._last_scrub_seek >= SCRUB_SEEK_INTERVAL_MS:
            self._last_scrub_seek = now
            self.emit("seek-requested", self._scrub_position)
        self.queue_draw()

    def _on_drag_end(self, gesture, offset_x, _offset_y):
        if self._region_drag is not None:
            self._end_region_drag()
            return
        if not self._scrubbing:
            return
        final = self._time_at_x(self._absolute_x(gesture, offset_x))
        self._scrubbing = False
        self._scrub_position = None
        self.emit("position-picked", final)
        self.emit("scrub-ended")
        self.queue_draw()

    # View panning (middle/right button) ---------------------------------- #

    def _on_pan_begin(self, _gesture, _start_x, _start_y):
        if self._region_drag is not None:
            return
        self._panning = True
        self._pan_last_offset_x = 0.0
        self._set_cursor("grabbing")

    def _on_pan_update(self, _gesture, offset_x, _offset_y):
        if not self._panning:
            return
        # Incremental deltas (not the accumulated offset) so view clamping
        # during the drag does not desynchronise the pointer.
        self._pan_by_px(offset_x - self._pan_last_offset_x)
        self._pan_last_offset_x = offset_x

    def _on_pan_end(self, _gesture, _offset_x, _offset_y):
        if not self._panning:
            return
        self._panning = False
        self._set_cursor(None)

    def _pan_by_px(self, dx_px: float):
        """Pan 1:1 with pointer movement (pixels -> seconds at current zoom)."""
        pps = self.model.px_per_second(self.get_width())
        if pps > 0 and dx_px:
            self.model.pan(-dx_px / pps)
            self.queue_draw()

    # Region dragging (Ctrl + left button) --------------------------------- #

    def _begin_region_drag(self, start_x: float) -> bool:
        """Try to grab a subtitle region at *start_x*; True when grabbed."""
        hit = self.model.region_hit(self._time_at_x(start_x), self.get_width())
        if hit is None:
            return False
        position, mode = hit
        for start, end, pos in self.model.subtitle_regions:
            if pos == position:
                self._region_drag = {
                    "position": position,
                    "mode": mode,
                    "orig_start": start,
                    "orig_end": end,
                    "anchor_time": self._time_at_x(start_x),
                    "moved": False,
                    "preview_start": start,
                    "preview_end": end,
                }
                self._set_cursor("ew-resize" if mode != "move" else "move")
                self.queue_draw()
                return True
        return False

    def _update_region_drag(self, gesture, offset_x, offset_y):
        drag = self._region_drag
        if not drag["moved"]:
            if math.hypot(offset_x, offset_y) < REGION_DRAG_THRESHOLD_PX:
                return  # still within click tolerance: keep preview put
            drag["moved"] = True
        pointer_time = self._time_at_x(self._absolute_x(gesture, offset_x))
        if drag["mode"] == "move":
            delta = pointer_time - drag["anchor_time"]
            drag["preview_start"], drag["preview_end"] = move_region_times(
                drag["orig_start"], drag["orig_end"], delta, self.model.duration
            )
        else:
            edge = "start" if drag["mode"] == "resize-start" else "end"
            drag["preview_start"], drag["preview_end"] = resize_region_times(
                drag["orig_start"], drag["orig_end"], edge,
                pointer_time, self.model.duration,
            )
        self.queue_draw()

    def _end_region_drag(self):
        drag = self._region_drag
        self._region_drag = None
        if not drag["moved"]:
            # Ctrl+click without a drag selects the entry (no document change).
            self.emit("region-selected", drag["position"])
        else:
            start_ms, end_ms = round_region_ms(
                drag["preview_start"], drag["preview_end"],
                self.model.duration,
                preserve_length=(drag["mode"] == "move"),
            )
            self.emit("region-adjusted", drag["position"], start_ms, end_ms)
        self._set_cursor(None)
        self.queue_draw()

    # Pointer tracking ------------------------------------------------------ #

    def _on_motion_enter(self, motion, x, _y):
        self._hover_x = x
        self._update_hover_cursor(motion)
        self.queue_draw()

    def _on_motion(self, motion, x, _y):
        self._hover_x = x
        self._update_hover_cursor(motion)
        self.queue_draw()

    def _on_motion_leave(self, _motion):
        self._hover_x = None
        self._set_cursor(None)
        self.queue_draw()

    def _update_hover_cursor(self, controller):
        """Cursor hint: resize/move over a region while Ctrl is held."""
        if self._panning or self._region_drag is not None:
            return
        name = "pointer"
        state = controller.get_current_event_state()
        if state & Gdk.ModifierType.CONTROL_MASK and self._hover_x is not None:
            hit = self.model.region_hit(
                self._time_at_x(self._hover_x), self.get_width()
            )
            if hit is not None:
                name = "move" if hit[1] == "move" else "ew-resize"
        self._set_cursor(name)

    def _on_scroll(self, controller, dx, dy):
        if self._region_drag is not None:
            return True  # gestures stay suppressed while region-dragging
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

        if self._hover_x is not None and not self._scrubbing and self._region_drag is None:
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
        self._draw_region_drag_overlay(cr, width)

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
        drag = self._region_drag
        if drag is not None:
            # The dragged region renders at its tentative position; the
            # others stay at their committed one.
            regions = [
                (drag["preview_start"], drag["preview_end"], drag["position"])
                if position == drag["position"]
                else (start, end, position)
                for start, end, position in regions
            ]
        selected = [r for r in regions if r[2] == self._selected_position]
        normal = [r for r in regions if r[2] != self._selected_position]
        radius = min(5.0, content_h / 2.0)
        self._paint_regions(cr, normal, COLOR_REGION, COLOR_REGION_EDGE, 1.0,
                            content_h, x_at, radius)
        # The selected entry's region reads brighter, with a crisper border.
        self._paint_regions(cr, selected, COLOR_REGION_SELECTED,
                            COLOR_REGION_EDGE_SELECTED, 2.0, content_h, x_at,
                            radius)

    @staticmethod
    def _paint_regions(cr, regions, fill_color, edge_color, line_width,
                       content_h, x_at, radius):
        if not regions:
            return
        # Translucent fill for all regions in one pass.
        cr.set_source_rgba(*fill_color)
        for start, end, _position in regions:
            _rounded_rect_path(
                cr, x_at(start), 0.0, max(x_at(end) - x_at(start), 1.0),
                content_h, radius,
            )
        cr.fill()
        # Crisper outline.
        cr.set_source_rgba(*edge_color)
        cr.set_line_width(line_width)
        for start, end, _position in regions:
            w = max(x_at(end) - x_at(start), 1.0)
            _rounded_rect_path(
                cr, x_at(start), 0.5, w, max(content_h - 1.0, 1.0), radius
            )
        cr.stroke()

    def _draw_region_drag_overlay(self, cr, width):
        """Time bubble with the tentative bounds while a region drag is live."""
        drag = self._region_drag
        if drag is None or not drag["moved"]:
            return
        label = "{} \u2192 {}".format(
            format_ruler_time(drag["preview_start"], True),
            format_ruler_time(drag["preview_end"], True),
        )
        layout = self._pango_layout()
        layout.set_text(label, -1)
        lw, lh = layout.get_pixel_size()
        center_x = self.model.fraction_at(
            (drag["preview_start"] + drag["preview_end"]) / 2.0
        ) * width
        bubble_w = min(lw + 8.0, width)
        bubble_x = min(max(center_x - bubble_w / 2.0, 0.0), width - bubble_w)
        self._fill_rect(cr, bubble_x, 0, bubble_w, lh + 4.0, COLOR_BACKGROUND)
        cr.set_source_rgba(*COLOR_RULER_TEXT)
        cr.move_to(bubble_x + 4, 1)
        PangoCairo.show_layout(cr, layout)

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
