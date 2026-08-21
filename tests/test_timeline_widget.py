"""GTK widget tests for the timeline's gesture controllers.

Real pointer event sequences are impractical headless, so the drag handlers
are driven directly with fabricated gestures (same start-point/offset math
the real events produce). Requires a display; skipped automatically when
none is available (same gating as test_subtitle_list_view.py).
"""

import pytest

try:
    from gi.repository import Gdk, GObject, Gtk

    from subtitle_editor.resources import register_resources

    register_resources()
    try:
        Gtk.init()
    except Exception:
        pass
    _HAS_DISPLAY = Gdk.Display.get_default() is not None
except Exception:  # pragma: no cover - environment without GTK
    _HAS_DISPLAY = False

pytestmark = pytest.mark.skipif(
    not _HAS_DISPLAY, reason="no display available for GTK widget tests"
)

from subtitle_editor.widgets.timeline import TimelineWidget  # noqa: E402

WIDTH = 600  # fixed fake allocation: with duration 600 s, 1 px = 1 s

CTRL = Gdk.ModifierType.CONTROL_MASK


class _FakeGesture:
    """The GestureDrag API the timeline handlers touch."""

    def __init__(self, widget, start_x=0.0, state=0):
        self._widget = widget
        self._start_x = start_x
        self._state = state

    def get_start_point(self):
        return (True, self._start_x, 0.0)

    def get_current_event_state(self):
        return self._state

    def get_widget(self):
        return self._widget


class _Recorder:
    """Records every timeline signal emission."""

    def __init__(self, timeline):
        self.events = []
        for name in (
            "seek-requested",
            "position-picked",
            "scrub-started",
            "scrub-ended",
            "region-adjusted",
            "region-selected",
        ):
            timeline.connect(name, self._handler(name))

    def _handler(self, name):
        def handler(_widget, *args):
            self.events.append((name,) + args)

        return handler

    def names(self):
        return [event[0] for event in self.events]


def _make_timeline():
    window = Gtk.Window()
    timeline = TimelineWidget()
    window.set_child(timeline)
    timeline.model.set_duration(600.0)
    # Unmapped widgets have no allocation: fake a fixed width so the
    # px -> seconds math behaves as on screen.
    timeline.get_width = lambda: WIDTH
    timeline.set_subtitle_regions([(100.0, 200.0, 0), (300.0, 350.0, 1)])
    return timeline


class TestSignalsDeclared:
    def test_region_signals_registered(self):
        assert GObject.signal_lookup("region-adjusted", TimelineWidget) != 0
        assert GObject.signal_lookup("region-selected", TimelineWidget) != 0


class TestScrubRegression:
    """Plain left click/drag keeps seeking (no Ctrl, no region grab)."""

    def test_plain_press_drag_release(self):
        timeline = _make_timeline()
        recorder = _Recorder(timeline)
        gesture = _FakeGesture(timeline, start_x=300.0)

        timeline._on_drag_begin(gesture, 300.0, 5.0)
        assert recorder.names() == ["scrub-started"]
        timeline._on_drag_update(gesture, 50.0, 0.0)
        assert ("seek-requested", 350.0) in recorder.events
        timeline._on_drag_end(gesture, 50.0, 0.0)

        assert ("position-picked", 350.0) in recorder.events
        assert recorder.names()[-1] == "scrub-ended"
        assert timeline._region_drag is None
        assert timeline._scrubbing is False

    def test_ctrl_press_outside_regions_still_scrubs(self):
        timeline = _make_timeline()
        recorder = _Recorder(timeline)
        gesture = _FakeGesture(timeline, start_x=250.0, state=CTRL)

        timeline._on_drag_begin(gesture, 250.0, 5.0)
        assert recorder.names() == ["scrub-started"]
        assert timeline._region_drag is None
        assert timeline._scrubbing is True


class TestRegionDrag:
    def _ctrl_gesture(self, timeline, start_x):
        return _FakeGesture(timeline, start_x=start_x, state=CTRL)

    def test_ctrl_press_inside_region_begins_drag_without_scrub(self):
        timeline = _make_timeline()
        recorder = _Recorder(timeline)

        timeline._on_drag_begin(self._ctrl_gesture(timeline, 150.0), 150.0, 5.0)

        assert timeline._region_drag is not None
        assert timeline._region_drag["position"] == 0
        assert timeline._region_drag["mode"] == "move"
        assert recorder.events == []  # no scrub-started, no seeks
        assert timeline._scrubbing is False

    def test_ctrl_press_near_edges_grabs_edge(self):
        timeline = _make_timeline()
        timeline._on_drag_begin(self._ctrl_gesture(timeline, 101.0), 101.0, 5.0)
        assert timeline._region_drag["mode"] == "resize-start"

        timeline2 = _make_timeline()
        timeline2._on_drag_begin(self._ctrl_gesture(timeline2, 199.0), 199.0, 5.0)
        assert timeline2._region_drag["mode"] == "resize-end"

    def test_drag_then_release_emits_region_adjusted(self):
        timeline = _make_timeline()
        recorder = _Recorder(timeline)
        gesture = self._ctrl_gesture(timeline, 150.0)

        timeline._on_drag_begin(gesture, 150.0, 5.0)
        timeline._on_drag_update(gesture, 50.0, 0.0)
        # Preview follows the pointer without touching the stored region.
        assert timeline._region_drag["preview_start"] == pytest.approx(150.0)
        assert timeline.model.subtitle_regions[0][:2] == (100.0, 200.0)
        timeline._on_drag_end(gesture, 50.0, 0.0)

        assert recorder.events == [("region-adjusted", 0, 150000, 250000)]
        assert timeline._region_drag is None

    def test_move_clamped_at_zero(self):
        timeline = _make_timeline()
        recorder = _Recorder(timeline)
        gesture = self._ctrl_gesture(timeline, 110.0)

        timeline._on_drag_begin(gesture, 110.0, 5.0)
        timeline._on_drag_update(gesture, -200.0, 0.0)
        timeline._on_drag_end(gesture, -200.0, 0.0)

        assert recorder.events == [("region-adjusted", 0, 0, 100000)]

    def test_resize_release(self):
        timeline = _make_timeline()
        recorder = _Recorder(timeline)
        gesture = self._ctrl_gesture(timeline, 101.0)

        timeline._on_drag_begin(gesture, 101.0, 5.0)
        timeline._on_drag_update(gesture, -21.0, 0.0)
        timeline._on_drag_end(gesture, -21.0, 0.0)

        assert recorder.events == [("region-adjusted", 0, 80000, 200000)]

    def test_resize_enforces_min_length(self):
        timeline = _make_timeline()
        recorder = _Recorder(timeline)
        gesture = self._ctrl_gesture(timeline, 199.0)

        timeline._on_drag_begin(gesture, 199.0, 5.0)
        # Pointer dragged to 100.01 s: the end stops 50 ms past the start.
        timeline._on_drag_update(gesture, -98.99, 0.0)
        timeline._on_drag_end(gesture, -98.99, 0.0)

        assert recorder.events == [("region-adjusted", 0, 100000, 100050)]

    def test_tiny_ctrl_click_selects(self):
        timeline = _make_timeline()
        recorder = _Recorder(timeline)
        gesture = self._ctrl_gesture(timeline, 150.0)

        timeline._on_drag_begin(gesture, 150.0, 5.0)
        timeline._on_drag_end(gesture, 0.0, 0.0)

        assert recorder.events == [("region-selected", 0)]

    def test_movement_under_threshold_still_selects(self):
        timeline = _make_timeline()
        recorder = _Recorder(timeline)
        gesture = self._ctrl_gesture(timeline, 150.0)

        timeline._on_drag_begin(gesture, 150.0, 5.0)
        timeline._on_drag_update(gesture, 2.0, 2.0)  # ~2.8 px travel
        timeline._on_drag_end(gesture, 2.0, 2.0)

        assert recorder.events == [("region-selected", 0)]


class TestPanDrag:
    """Middle/right-button drag pans the view 1:1 with the pointer."""

    def test_drag_pans_view(self):
        timeline = _make_timeline()
        timeline.model.set_zoom_window(100.0, 160.0)  # 60 s window, 10 px/s
        gesture = _FakeGesture(timeline, start_x=300.0)

        timeline._on_pan_begin(gesture, 300.0, 5.0)
        assert timeline._panning is True
        timeline._on_pan_update(gesture, 20.0, 0.0)

        assert timeline.model.view_start == pytest.approx(98.0)  # 20 px = 2 s
        assert timeline.model.window() == pytest.approx(60.0)
        timeline._on_pan_end(gesture, 20.0, 0.0)
        assert timeline._panning is False

    def test_pan_clamps_at_start_of_media(self):
        timeline = _make_timeline()
        timeline.model.set_zoom_window(10.0, 70.0)  # 10 px/s
        gesture = _FakeGesture(timeline, start_x=300.0)

        timeline._on_pan_begin(gesture, 300.0, 5.0)
        timeline._on_pan_update(gesture, 200.0, 0.0)  # -20 s, past 0

        assert timeline.model.view_start == 0.0
        assert timeline.model.window() == pytest.approx(60.0)

    def test_click_without_movement_is_noop(self):
        timeline = _make_timeline()
        timeline.model.set_zoom_window(100.0, 160.0)
        recorder = _Recorder(timeline)
        gesture = _FakeGesture(timeline, start_x=300.0)

        timeline._on_pan_begin(gesture, 300.0, 5.0)
        timeline._on_pan_end(gesture, 0.0, 0.0)

        assert timeline.model.view_start == pytest.approx(100.0)
        assert recorder.events == []

    def test_shift_scroll_pan_unaffected(self):
        timeline = _make_timeline()
        timeline.model.set_zoom_window(100.0, 160.0)
        before = timeline.model.view_start
        timeline.model.pan(10.0)
        assert timeline.model.view_start == pytest.approx(before + 10.0)


class TestSelectedRegion:
    def test_set_selected_position(self):
        timeline = _make_timeline()
        timeline.set_selected_position(1)
        assert timeline._selected_position == 1
        timeline.set_selected_position(-1)
        assert timeline._selected_position == -1
