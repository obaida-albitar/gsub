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
        TimelineModel,
        active_entry_at,
        format_ruler_time,
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
        model.set_subtitle_regions([(-10.0, 5.0), (10.0, 20.0), (590.0, 900.0)])
        model.set_zoom_window(0.0, 30.0)
        assert model.visible_regions() == [(0.0, 5.0), (10.0, 20.0)]

    def test_degenerate_regions_dropped(self, model):
        model.set_subtitle_regions([(5.0, 5.0), (8.0, 6.0), (1.0, 2.0)])
        assert model.visible_regions() == [(1.0, 2.0)]

    def test_regions_partial_overlap_with_view(self, model):
        model.set_subtitle_regions([(100.0, 200.0)])
        model.set_zoom_window(150.0, 300.0)
        assert model.visible_regions() == [(150.0, 200.0)]

    def test_no_duration_keeps_regions(self):
        m = TimelineModel()
        m.set_subtitle_regions([(5.0, 10.0)])
        assert m.visible_regions() == [(5.0, 10.0)]


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
