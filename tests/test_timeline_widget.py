"""GTK widget tests for the timeline's gesture controllers.

Real pointer event sequences are impractical headless, so the drag handlers
are driven directly with fabricated gestures (same start-point/offset math
the real events produce). Requires a display; skipped automatically when
none is available (same gating as test_subtitle_list_view.py).
"""

import pytest

try:
    from gi.repository import Gdk, GObject, Gtk

    from gsub.resources import register_resources

    register_resources()
    try:
        Gtk.init()
    except Exception:
        pass
    from gsub.widgets.timeline import TimelineWidget  # noqa: E402
    CTRL = Gdk.ModifierType.CONTROL_MASK
    _HAS_DISPLAY = Gdk.Display.get_default() is not None
except Exception:  # pragma: no cover - environment without GTK
    _HAS_DISPLAY = False

pytestmark = pytest.mark.skipif(
    not _HAS_DISPLAY, reason="no display available for GTK widget tests"
)

WIDTH = 600  # fixed fake allocation: with duration 600 s, 1 px = 1 s


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


class TestSelectedEdgeResize:
    """Plain (no modifier) drags of the selected region's edge handles."""

    def test_plain_press_on_selected_edge_begins_resize_without_scrub(self):
        timeline = _make_timeline()
        timeline.set_selected_position(0)
        recorder = _Recorder(timeline)
        gesture = _FakeGesture(timeline, start_x=101.0)

        timeline._on_drag_begin(gesture, 101.0, 5.0)

        assert timeline._region_drag is not None
        assert timeline._region_drag["position"] == 0
        assert timeline._region_drag["mode"] == "resize-start"
        assert recorder.events == []  # no scrub-started, no seeks
        assert timeline._scrubbing is False

    def test_plain_press_on_selected_end_edge_grabs_end(self):
        timeline = _make_timeline()
        timeline.set_selected_position(0)
        timeline._on_drag_begin(_FakeGesture(timeline, start_x=199.0), 199.0, 5.0)
        assert timeline._region_drag["mode"] == "resize-end"

    def test_plain_edge_drag_release_emits_exact_ms(self):
        timeline = _make_timeline()
        timeline.set_selected_position(0)
        recorder = _Recorder(timeline)
        gesture = _FakeGesture(timeline, start_x=199.0)

        timeline._on_drag_begin(gesture, 199.0, 5.0)
        timeline._on_drag_update(gesture, -49.0, 0.0)  # pointer at 150 s
        timeline._on_drag_end(gesture, -49.0, 0.0)

        assert recorder.events == [("region-adjusted", 0, 100000, 150000)]
        assert timeline._region_drag is None

    def test_plain_press_on_selected_body_still_scrubs(self):
        # Regression: the selected region's body stays scrub/seek territory.
        timeline = _make_timeline()
        timeline.set_selected_position(0)
        recorder = _Recorder(timeline)
        gesture = _FakeGesture(timeline, start_x=150.0)

        timeline._on_drag_begin(gesture, 150.0, 5.0)
        assert recorder.names() == ["scrub-started"]
        assert timeline._region_drag is None
        assert timeline._scrubbing is True
        timeline._on_drag_update(gesture, 20.0, 0.0)
        assert ("seek-requested", 170.0) in recorder.events
        timeline._on_drag_end(gesture, 20.0, 0.0)
        assert ("position-picked", 170.0) in recorder.events
        assert recorder.names()[-1] == "scrub-ended"

    def test_plain_press_on_unselected_region_edge_still_scrubs(self):
        # Without Ctrl only the selected region reacts; the edge of another
        # region keeps seeking/scrubbing like empty timeline space.
        timeline = _make_timeline()
        timeline.set_selected_position(0)
        recorder = _Recorder(timeline)
        gesture = _FakeGesture(timeline, start_x=301.0)

        timeline._on_drag_begin(gesture, 301.0, 5.0)

        assert recorder.names() == ["scrub-started"]
        assert timeline._region_drag is None
        assert timeline._scrubbing is True

    def test_ctrl_edge_on_unselected_region_still_resizes(self):
        # Regression: Ctrl keeps working on any region, selected or not.
        timeline = _make_timeline()
        timeline.set_selected_position(0)
        recorder = _Recorder(timeline)
        gesture = _FakeGesture(timeline, start_x=301.0, state=CTRL)

        timeline._on_drag_begin(gesture, 301.0, 5.0)
        assert timeline._region_drag["position"] == 1
        assert timeline._region_drag["mode"] == "resize-start"
        timeline._on_drag_update(gesture, -10.0, 0.0)  # pointer at 291 s
        timeline._on_drag_end(gesture, -10.0, 0.0)

        assert recorder.events == [("region-adjusted", 1, 291000, 350000)]

    def test_noop_release_emits_nothing(self):
        # A plain grab released without moving: no select, no adjustment.
        timeline = _make_timeline()
        timeline.set_selected_position(0)
        recorder = _Recorder(timeline)
        gesture = _FakeGesture(timeline, start_x=101.0)

        timeline._on_drag_begin(gesture, 101.0, 5.0)
        timeline._on_drag_end(gesture, 0.0, 0.0)

        assert recorder.events == []

    def test_release_with_unchanged_values_emits_nothing(self):
        # A real drag whose clamped bounds round back to the committed ones
        # (end edge pinned at the media duration) must not emit.
        timeline = _make_timeline()
        timeline.set_subtitle_regions([(100.0, 200.0, 0), (590.0, 600.0, 1)])
        timeline.set_selected_position(1)
        recorder = _Recorder(timeline)
        gesture = _FakeGesture(timeline, start_x=599.0)

        timeline._on_drag_begin(gesture, 599.0, 5.0)
        timeline._on_drag_update(gesture, 50.0, 0.0)  # pointer clamps to 600 s
        timeline._on_drag_end(gesture, 50.0, 0.0)

        assert recorder.events == []

    def test_hover_cursor_over_selected_edge_without_ctrl(self):
        timeline = _make_timeline()
        timeline.set_selected_position(0)
        timeline._hover_x = 101.0

        timeline._update_hover_cursor(_FakeGesture(timeline, start_x=101.0))

        cursor = timeline.get_cursor()
        assert cursor is not None
        assert cursor.get_name() == "ew-resize"

    def test_hover_cursor_over_selected_body_stays_pointer(self):
        timeline = _make_timeline()
        timeline.set_selected_position(0)
        timeline._hover_x = 150.0

        timeline._update_hover_cursor(_FakeGesture(timeline, start_x=150.0))

        cursor = timeline.get_cursor()
        assert cursor is None or cursor.get_name() == "pointer"


class TestOverlappingRegions:
    """Overlapping regions: the selected region wins, hit-test and z-order.

    Setup: region 0 (100-200 s, selected) is drawn beneath region 1
    (150-250 s) in document order. Everything inside the overlap (150-200 s)
    must still grab the selected region's body/edges without Ctrl.
    """

    def _overlapping_timeline(self):
        timeline = _make_timeline()
        timeline.set_subtitle_regions([(100.0, 200.0, 0), (150.0, 250.0, 1)])
        timeline.set_selected_position(0)
        return timeline

    def test_plain_press_on_selected_edge_under_overlap_begins_resize(self):
        timeline = self._overlapping_timeline()
        recorder = _Recorder(timeline)

        timeline._on_drag_begin(_FakeGesture(timeline, start_x=196.0), 196.0, 5.0)

        assert timeline._region_drag is not None
        assert timeline._region_drag["position"] == 0
        assert timeline._region_drag["mode"] == "resize-end"
        assert recorder.events == []  # no scrub started
        assert timeline._scrubbing is False

    def test_ctrl_press_on_selected_edge_under_overlap_grabs_it_too(self):
        timeline = self._overlapping_timeline()
        gesture = _FakeGesture(timeline, start_x=196.0, state=CTRL)

        timeline._on_drag_begin(gesture, 196.0, 5.0)
        assert timeline._region_drag["position"] == 0
        assert timeline._region_drag["mode"] == "resize-end"

        timeline._on_drag_update(gesture, -46.0, 0.0)  # pointer at 150 s
        timeline._on_drag_end(gesture, -46.0, 0.0)
        assert timeline._region_drag is None

    def test_selected_region_resize_commits_from_under_overlap(self):
        timeline = self._overlapping_timeline()
        recorder = _Recorder(timeline)
        gesture = _FakeGesture(timeline, start_x=196.0)

        timeline._on_drag_begin(gesture, 196.0, 5.0)
        timeline._on_drag_update(gesture, -46.0, 0.0)
        timeline._on_drag_end(gesture, -46.0, 0.0)

        assert recorder.events == [("region-adjusted", 0, 100000, 150000)]

    def test_ctrl_click_inside_overlap_stays_on_selected_region(self):
        # Tradeoff: within the overlap the selected region wins hit-testing,
        # so Ctrl+click re-selects it; the overlapping entry is reachable via
        # the part of its region outside the overlap (next test).
        timeline = self._overlapping_timeline()
        recorder = _Recorder(timeline)
        gesture = _FakeGesture(timeline, start_x=175.0, state=CTRL)

        timeline._on_drag_begin(gesture, 175.0, 5.0)
        timeline._on_drag_end(gesture, 0.0, 0.0)

        assert recorder.events == [("region-selected", 0)]

    def test_ctrl_click_on_unoverlapped_part_selects_other_region(self):
        timeline = self._overlapping_timeline()
        recorder = _Recorder(timeline)
        gesture = _FakeGesture(timeline, start_x=220.0, state=CTRL)

        timeline._on_drag_begin(gesture, 220.0, 5.0)
        timeline._on_drag_end(gesture, 0.0, 0.0)

        assert recorder.events == [("region-selected", 1)]

    def test_hover_cursor_over_selected_edge_under_overlap(self):
        timeline = self._overlapping_timeline()
        timeline._hover_x = 196.0

        timeline._update_hover_cursor(_FakeGesture(timeline, start_x=196.0))

        cursor = timeline.get_cursor()
        assert cursor is not None
        assert cursor.get_name() == "ew-resize"

    def test_selected_region_painted_last_with_handles_on_top(self):
        # Z-order: capture the paint calls and assert the selected region is
        # painted after the unselected ones, its edge handles after that.
        timeline = self._overlapping_timeline()
        order = []
        timeline._paint_regions = lambda cr, regions, *args: order.append(
            ("paint", [r[2] for r in regions])
        )
        timeline._draw_edge_handles = lambda cr, content_h, x_at, regions: order.append(
            ("handles", [r[2] for r in regions])
        )

        timeline._draw_regions(object(), 36.0, lambda t: t)

        assert order == [("paint", [1]), ("paint", [0]), ("handles", [0])]


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

    def test_edge_handles_follow_selection(self):
        timeline = _make_timeline()
        assert timeline.has_edge_handles() is False  # nothing selected
        timeline.set_selected_position(0)
        assert timeline.has_edge_handles() is True
        timeline.set_selected_position(-1)
        assert timeline.has_edge_handles() is False

    def test_edge_handles_need_a_matching_region(self):
        timeline = _make_timeline()
        timeline.set_selected_position(7)  # no such region
        assert timeline.has_edge_handles() is False

    def test_edge_handles_hidden_when_region_scrolled_out(self):
        timeline = _make_timeline()
        timeline.set_selected_position(0)
        assert timeline.has_edge_handles() is True
        timeline.model.set_zoom_window(300.0, 350.0)  # region 0 out of view
        assert timeline.has_edge_handles() is False
