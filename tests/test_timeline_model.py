"""Pure-logic tests for the timeline model and helpers.

The model is deliberately GTK-free, so these run headless; the import is
wrapped the same way as test_video_player.py to skip gracefully on systems
without the GTK stack.
"""

import pytest

pytest.importorskip("gi")

try:
    from subtitle_editor import resources

    resources.register_resources()
    from subtitle_editor.widgets.timeline import (
        MIN_WINDOW,
        REGION_EDGE_THRESHOLD_PX,
        REGION_HANDLE_WIDTH_PX,
        TimelineModel,
        active_entry_at,
        format_ruler_time,
        move_region_times,
        region_edge_grab_px,
        resize_region_times,
        round_region_ms,
    )
    from subtitle_editor.models import SubtitleEntry, TimeCode
except Exception as exc:  # pragma: no cover - depends on GTK stack
    pytest.skip(f"timeline module not importable: {exc}", allow_module_level=True)


def _entry(start_ms, end_ms):
    return SubtitleEntry(
        index=0,
        start_time=TimeCode.from_milliseconds(start_ms),
        end_time=TimeCode.from_milliseconds(end_ms),
        text="x",
    )


@pytest.fixture
def model():
    m = TimelineModel()
    m.set_duration(600.0)
    return m


@pytest.mark.unit
class TestZoom:
    def test_zoom_in_shrinks_window_and_resets_on_duration(self, model):
        assert model.window() == 600.0
        model.zoom(2.0, 300.0)
        assert model.window() == pytest.approx(300.0)

    def test_anchor_stays_at_same_fraction(self, model):
        anchor = 200.0
        fraction_before = model.fraction_at(anchor)
        model.zoom(4.0, anchor)
        assert model.fraction_at(anchor) == pytest.approx(fraction_before)
        assert model.time_at(fraction_before) == pytest.approx(anchor)

    def test_anchor_preserved_at_multiple_factors(self, model):
        model.zoom(3.0, 100.0)
        model.zoom(0.5, 100.0)
        model.zoom(2.5, 100.0)
        # Window changed but the anchor is still at fraction 1/6.
        assert model.fraction_at(100.0) == pytest.approx(100.0 / 600.0)

    def test_min_window_enforced(self, model):
        model.zoom(1e9, 300.0)
        assert model.window() == pytest.approx(MIN_WINDOW)

    def test_max_window_is_full_duration(self, model):
        model.zoom(0.001, 300.0)
        assert model.window() == pytest.approx(600.0)
        assert model.view_start == 0.0
        assert model.view_end == pytest.approx(600.0)

    def test_zoom_clamps_at_left_edge(self, model):
        model.zoom(10.0, 0.0)
        assert model.view_start == 0.0
        assert model.window() == pytest.approx(60.0)

    def test_zoom_clamps_at_right_edge(self, model):
        model.zoom(10.0, 600.0)
        assert model.view_end == pytest.approx(600.0)
        assert model.view_start == pytest.approx(540.0)

    def test_set_zoom_window_clamps(self, model):
        model.set_zoom_window(-50.0, 10.0)
        assert model.view_start == 0.0
        assert model.window() >= MIN_WINDOW
        model.set_zoom_window(590.0, 2000.0)
        assert model.view_end == pytest.approx(600.0)

    def test_no_zoom_without_duration(self):
        m = TimelineModel()
        m.zoom(2.0, 0.0)
        assert m.window() == 0.0


@pytest.mark.unit
class TestPan:
    def test_pan_moves_window(self, model):
        model.zoom(10.0, 0.0)  # 60 s window at the start
        model.pan(100.0)
        assert model.view_start == pytest.approx(100.0)
        assert model.window() == pytest.approx(60.0)

    def test_pan_clamps_at_edges(self, model):
        model.zoom(10.0, 300.0)
        model.pan(-10_000.0)
        assert model.view_start == 0.0
        model.pan(10_000.0)
        assert model.view_end == pytest.approx(600.0)

    def test_negative_pan(self, model):
        model.zoom(2.0, 300.0)
        model.pan(-150.0)
        assert model.view_start == pytest.approx(0.0)


@pytest.mark.unit
class TestMapping:
    def test_time_fraction_round_trip(self, model):
        model.zoom(2.0, 300.0)
        for fraction in (0.0, 0.25, 0.5, 0.75, 1.0):
            t = model.time_at(fraction)
            assert model.fraction_at(t) == pytest.approx(fraction)

    def test_fraction_outside_view(self, model):
        model.zoom(2.0, 300.0)  # view 150..450
        assert model.fraction_at(0.0) == pytest.approx(-0.5)
        assert model.fraction_at(700.0) == pytest.approx(11 / 6)

    def test_px_per_second(self, model):
        assert model.px_per_second(1200) == pytest.approx(2.0)
        model.zoom(2.0, 300.0)
        assert model.px_per_second(1200) == pytest.approx(4.0)
        assert model.px_per_second(0) == 0.0

    def test_position_clamped(self, model):
        model.set_position(-5.0)
        assert model.position == 0.0
        model.set_position(10_000.0)
        assert model.position == pytest.approx(600.0)


@pytest.mark.unit
class TestTickLadder:
    def test_ladder_choices(self, model):
        # ~60-120 px apart: pick the first step whose spacing reaches 60 px.
        cases = {
            100.0: 1.0,    # 1 s * 100 px = 100 px
            60.0: 1.0,     # exactly 60 px
            50.0: 2.0,     # 1 s would be 50 px, so 2 s (100 px)
            10.0: 10.0,    # 10 s * 10 px = 100 px
            1.0: 60.0,     # 60 s * 1 px = 60 px
            0.5: 120.0,    # 120 s * 0.5 px = 60 px
            0.2: 300.0,    # very zoomed out
        }
        for pps, expected in cases.items():
            assert model.tick_interval(pps) == expected, f"at {pps} px/s"

    def test_extreme_zoom_out_returns_last_rung(self, model):
        assert model.tick_interval(0.001) == 3600.0

    def test_sub_second_steps_when_zoomed_in(self, model):
        assert model.tick_interval(600.0) == 0.1
        assert model.tick_interval(240.0) == 0.25
        assert model.tick_interval(120.0) == 0.5


@pytest.mark.unit
class TestBucketRange:
    def test_full_view(self, model):
        model.set_peaks([(0, 0)] * 600, 1.0)
        assert model.bucket_range() == (0, 600)

    def test_sliced_view(self, model):
        model.set_peaks([(0, 0)] * 1000, 10.0)  # 100 s of peaks
        model.set_zoom_window(20.0, 50.0)
        assert model.bucket_range() == (200, 500)

    def test_no_peaks(self, model):
        assert model.bucket_range() == (0, 0)
        model.set_peaks([], 100.0)
        assert model.bucket_range() == (0, 0)

    def test_out_of_range_view_clamped(self, model):
        model.set_peaks([(0, 0)] * 10, 1.0)
        model.set_zoom_window(50.0, 100.0)
        first, last = model.bucket_range()
        assert first == 10
        assert last <= 10


@pytest.mark.unit
class TestSubtitleRegions:
    def test_regions_clamped_to_duration_and_view(self, model):
        model.set_subtitle_regions(
            [(-10.0, 5.0, 0), (10.0, 20.0, 1), (590.0, 900.0, 2)]
        )
        model.set_zoom_window(0.0, 30.0)
        assert model.visible_regions() == [(0.0, 5.0, 0), (10.0, 20.0, 1)]

    def test_degenerate_regions_dropped(self, model):
        model.set_subtitle_regions([(5.0, 5.0, 0), (8.0, 6.0, 1), (1.0, 2.0, 2)])
        assert model.visible_regions() == [(1.0, 2.0, 2)]

    def test_regions_partial_overlap_with_view(self, model):
        model.set_subtitle_regions([(100.0, 200.0, 3)])
        model.set_zoom_window(150.0, 300.0)
        assert model.visible_regions() == [(150.0, 200.0, 3)]

    def test_no_duration_keeps_regions(self):
        m = TimelineModel()
        m.set_subtitle_regions([(5.0, 10.0, 1)])
        assert m.visible_regions() == [(5.0, 10.0, 1)]

    def test_region_tuples_carry_position(self, model):
        model.set_subtitle_regions([(1.0, 2.0, 5), (3.0, 4.0, 6)])
        assert model.subtitle_regions == [(1.0, 2.0, 5), (3.0, 4.0, 6)]
        model.set_subtitle_regions([(1.0, 2.0)])
        # Plain (start, end) pairs are tolerated with position -1.
        assert model.subtitle_regions == [(1.0, 2.0, -1)]


@pytest.mark.unit
class TestRegionHit:
    """region_hit(): body = move, edges = resize, miss = None.

    Default setup: duration 600 s over a 600 px widget (1 px = 1 s), so the
    8 px edge threshold equals 8 s. The threshold is a constant number of
    screen pixels: it converts to time at the current zoom instead of being
    a fixed time span.
    """

    WIDTH = 600

    @staticmethod
    def _model_with_region(model):
        model.set_subtitle_regions([(100.0, 200.0, 0)])
        return model

    def test_body_is_move(self, model):
        self._model_with_region(model)
        assert model.region_hit(150.0, self.WIDTH) == (0, "move")

    def test_edges_are_resize(self, model):
        self._model_with_region(model)
        assert model.region_hit(100.0, self.WIDTH) == (0, "resize-start")
        assert model.region_hit(103.0, self.WIDTH) == (0, "resize-start")
        assert model.region_hit(197.0, self.WIDTH) == (0, "resize-end")
        assert model.region_hit(200.0, self.WIDTH) == (0, "resize-end")

    def test_just_past_threshold_is_body(self, model):
        self._model_with_region(model)
        assert model.region_hit(108.5, self.WIDTH) == (0, "move")
        assert model.region_hit(191.5, self.WIDTH) == (0, "move")

    def test_miss_outside_region(self, model):
        self._model_with_region(model)
        assert model.region_hit(50.0, self.WIDTH) is None
        assert model.region_hit(250.0, self.WIDTH) is None
        assert model.region_hit(1000.0, self.WIDTH) is None
        assert model.region_hit(-5.0, self.WIDTH) is None

    def test_edge_threshold_constant_in_screen_pixels(self, model):
        # The same pixel distance from the edge hits at every zoom level:
        # 5 px into the region grabs, 12 px is already the body, whether a
        # pixel is worth 1 s (full 600 s view) or 0.1 s (60 s window).
        self._model_with_region(model)
        for window, near, far in ((600.0, 105.0, 112.0), (60.0, 100.5, 101.2)):
            model.set_zoom_window(0.0, window)
            assert model.region_hit(near, self.WIDTH) == (0, "resize-start")
            assert model.region_hit(far, self.WIDTH) == (0, "move")

    def test_grab_zone_is_larger_of_constant_and_handle_width(self, model):
        # The grab zone can never be narrower than the drawn handles (the
        # pointer must always reach what is on screen).
        grab = region_edge_grab_px()
        assert grab == max(REGION_EDGE_THRESHOLD_PX, REGION_HANDLE_WIDTH_PX)
        assert grab >= 8.0
        self._model_with_region(model)  # 1 px = 1 s, so px and s coincide
        assert model.region_hit(100.0 + grab - 0.5, self.WIDTH) == (0, "resize-start")
        assert model.region_hit(100.0 + grab + 0.5, self.WIDTH) == (0, "move")

    def test_last_region_wins_on_overlap(self, model):
        model.set_subtitle_regions([(100.0, 200.0, 0), (150.0, 250.0, 1)])
        assert model.region_hit(175.0, self.WIDTH) == (1, "move")

    def test_no_regions(self, model):
        assert model.region_hit(10.0, self.WIDTH) is None


@pytest.mark.unit
class TestRegionMoveMath:
    def test_move_preserves_length(self):
        assert move_region_times(10.0, 13.5, 5.0, 600.0) == (15.0, 18.5)

    def test_move_clamps_at_zero(self):
        assert move_region_times(10.0, 13.5, -100.0, 600.0) == (0.0, 3.5)

    def test_move_clamps_at_duration(self):
        assert move_region_times(595.0, 605.0, 50.0, 600.0) == (590.0, 600.0)

    def test_negative_move(self):
        assert move_region_times(100.0, 110.0, -30.0, 600.0) == (70.0, 80.0)


@pytest.mark.unit
class TestRegionResizeMath:
    def test_resize_start(self):
        assert resize_region_times(10.0, 20.0, "start", 5.0, 600.0) == (5.0, 20.0)

    def test_resize_start_clamped_at_zero(self):
        assert resize_region_times(10.0, 20.0, "start", -5.0, 600.0) == (0.0, 20.0)

    def test_resize_start_min_length_enforced(self):
        # 50 ms minimum: the start cannot pass end - 0.05.
        result = resize_region_times(10.0, 20.0, "start", 19.98, 600.0)
        assert result == pytest.approx((19.95, 20.0))

    def test_resize_end(self):
        assert resize_region_times(10.0, 20.0, "end", 25.0, 600.0) == (10.0, 25.0)

    def test_resize_end_clamped_at_duration(self):
        assert resize_region_times(10.0, 20.0, "end", 900.0, 600.0) == (10.0, 600.0)

    def test_resize_end_min_length_enforced(self):
        assert resize_region_times(10.0, 20.0, "end", 10.01, 600.0) == (10.0, 10.05)


@pytest.mark.unit
class TestRoundRegionMs:
    def test_rounds_to_whole_ms(self):
        assert round_region_ms(1.2345, 5.6789, 600.0) == (1234, 5679)

    def test_move_preserves_length_after_rounding(self):
        assert round_region_ms(9.9999, 13.4999, 600.0, preserve_length=True) == (10000, 13500)

    def test_start_clamped_at_zero(self):
        assert round_region_ms(-0.01, 1.0, 600.0) == (0, 1000)

    def test_end_clamped_at_duration(self):
        assert round_region_ms(599.5, 601.0, 600.0) == (599500, 600000)

    def test_move_clamped_at_duration_boundary(self):
        # A 3.5 s region dragged so its rounded start would push its end
        # past 600 s: the start backs off to keep the length and the clamp.
        assert round_region_ms(598.0, 601.5, 600.0, preserve_length=True) == (596500, 600000)

    def test_resize_enforces_min_length(self):
        assert round_region_ms(10.0, 10.01, 600.0) == (10000, 10050)


@pytest.mark.unit
class TestFormatRulerTime:
    def test_without_millis(self):
        assert format_ruler_time(0.0, False) == "0:00"
        assert format_ruler_time(75.4, False) == "1:15"
        assert format_ruler_time(3661.0, False) == "1:01:01"

    def test_with_millis(self):
        assert format_ruler_time(0.0, True) == "0:00.000"
        assert format_ruler_time(75.4, True) == "1:15.400"
        assert format_ruler_time(59.9999, True) == "1:00.000"


@pytest.mark.unit
class TestActiveEntryAt:
    @staticmethod
    def _entries():
        return [
            _entry(500, 2000),
            _entry(2500, 5000),
            _entry(6000, 8000),
        ]

    def test_before_first_entry(self):
        assert active_entry_at(self._entries(), 0.0) == -1
        assert active_entry_at(self._entries(), 0.4999) == -1

    def test_start_is_inclusive_end_exclusive(self):
        entries = self._entries()
        assert active_entry_at(entries, 0.5) == 0
        assert active_entry_at(entries, 1.9999) == 0
        assert active_entry_at(entries, 2.0) == -1  # gap
        assert active_entry_at(entries, 2.5) == 1
        assert active_entry_at(entries, 5.0) == -1  # end exclusive
        assert active_entry_at(entries, 6.0) == 2
        assert active_entry_at(entries, 7.999) == 2

    def test_after_last_entry(self):
        assert active_entry_at(self._entries(), 8.0) == -1
        assert active_entry_at(self._entries(), 100.0) == -1

    def test_empty(self):
        assert active_entry_at([], 1.0) == -1

    def test_negative_time_clamped(self):
        assert active_entry_at(self._entries(), -3.0) == -1

    def test_single_entry(self):
        assert active_entry_at([_entry(0, 1000)], 0.0) == 0
        assert active_entry_at([_entry(0, 1000)], 0.999) == 0
        assert active_entry_at([_entry(0, 1000)], 1.0) == -1
