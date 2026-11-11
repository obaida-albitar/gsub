"""Readable-text metrics and quality checks, independent of GTK."""

from copy import deepcopy

import pytest

from gsub.models import SubtitleDocument, SubtitleEntry, SubtitleFormat, TimeCode
from gsub.quality import QualitySettings, check_quality, text_metrics, visible_text


def cue(text="Hello", start=0, end=2000, **kwargs):
    return SubtitleEntry(1, TimeCode.from_milliseconds(start),
                         TimeCode.from_milliseconds(end), text, **kwargs)


def document(*entries, fmt=SubtitleFormat.SRT):
    return SubtitleDocument(fmt, entries=list(entries))


def codes(doc, settings=None):
    return [issue.code for issue in check_quality(doc, settings)]


@pytest.mark.parametrize("fmt", list(SubtitleFormat))
def test_ordinary_readable_subtitle_has_no_issues(fmt):
    assert check_quality(document(cue(), fmt=fmt)) == []


def test_srt_metrics_ignore_supported_html_and_decode_entities():
    metrics = text_metrics('<font color="red"><b>A&amp;B</b></font><br/>Hi', 1000)
    assert metrics.visible_text == "A&B\nHi"
    assert metrics.character_count == 5
    assert metrics.line_lengths == (3, 2)
    assert metrics.cps == 5


def test_srt_plain_braces_and_ass_escapes_are_literal():
    text = r"{note} text\Nmore"
    assert visible_text(text) == text


def test_srt_escaped_markup_remains_displayed_text():
    assert visible_text("&lt;b&gt;Hi&lt;/b&gt;") == "<b>Hi</b>"


@pytest.mark.parametrize("fmt", [SubtitleFormat.ASS, SubtitleFormat.SSA])
def test_ass_metrics_ignore_tags_and_count_hard_and_soft_breaks(fmt):
    metrics = text_metrics(r"{\i1}Hello{\i0}\Nworld\nX\hY", 2000, fmt)
    assert metrics.visible_text == "Hello\nworld\nX\N{NO-BREAK SPACE}Y"
    assert metrics.line_lengths == (5, 5, 3)
    assert metrics.character_count == 13
    assert metrics.cps == 6.5


def test_drawing_run_does_not_inflate_dialogue_metrics():
    text = r"{\p1}m 0 0 l 50 10{\p0}Hello"
    assert text_metrics(text, 1000, SubtitleFormat.ASS).character_count == 5


def test_drawing_mode_reset_and_transform_tags():
    assert visible_text(r"{\p1}m 0 0{\r}Hi", SubtitleFormat.ASS) == "Hi"
    assert visible_text(r"{\t(0,100,\p1)}Hi", SubtitleFormat.ASS) == "Hi"
    assert visible_text(r"{\pbo10}Hi", SubtitleFormat.ASS) == "Hi"


def test_unbalanced_ass_braces_remain_visible():
    assert visible_text("hello {broken", SubtitleFormat.ASS) == "hello {broken"


def test_combining_accents_and_bidi_markers_do_not_inflate_counts():
    assert text_metrics("e\u0301\u200f", 1000).character_count == 1


def test_metrics_normalize_newlines_and_ignore_line_edge_whitespace():
    metrics = text_metrics(" Hello \r\n there \r!", 1000)
    assert metrics.line_lengths == (5, 5, 1)
    assert metrics.line_count == 3
    assert metrics.longest_line == 5


@pytest.mark.parametrize("duration", [0, -1000])
def test_invalid_duration_has_no_cps_division(duration):
    assert text_metrics("Hello", duration).cps is None
    doc = document(cue(end=duration))
    issues = check_quality(doc)
    assert "timing.invalid_duration" in [i.code for i in issues]
    assert next(i for i in issues if i.code == "timing.invalid_duration").severity == "error"


@pytest.mark.parametrize("text", ["", "   ", "\n", "\u200f"])
def test_empty_visible_text(text):
    assert "text.empty" in codes(document(cue(text)))


def test_empty_override_event_is_flagged_but_drawing_only_event_is_ignored():
    assert "text.empty" in codes(document(cue(r"{\i1}"), fmt=SubtitleFormat.ASS))
    assert check_quality(document(cue(r"{\p1}m 0 0 l 50 0 50 50", end=100),
                                  fmt=SubtitleFormat.ASS)) == []


def test_limit_checks_are_configurable_and_report_all_problems():
    doc = document(cue("Long line\nand another\nthird", end=500))
    settings = QualitySettings(max_cps=10, max_chars_per_line=5,
                               max_lines=2, min_duration_ms=1000)
    assert set(codes(doc, settings)) == {"timing.too_short", "text.reading_speed",
                                       "text.line_length", "text.line_count"}


def test_duration_limits_and_exact_boundary_values():
    assert codes(document(cue(end=999))) == ["timing.too_short"]
    assert codes(document(cue(end=1000))) == []
    assert codes(document(cue(end=7000))) == []
    assert codes(document(cue(end=7001))) == ["timing.too_long"]
    settings = QualitySettings(max_cps=5, max_chars_per_line=5, max_lines=1)
    assert codes(document(cue(end=1000)), settings) == []


def test_small_gap_detected_in_time_order_without_changing_file_order():
    first, second = cue(start=2050, end=4050), cue(start=0, end=2000)
    doc = document(first, second)
    issues = check_quality(doc)
    assert [(i.position, i.code, i.related_position) for i in issues] == [
        (0, "timing.small_gap", 1)]
    assert doc.entries == [first, second]


@pytest.mark.parametrize("gap", [0, 80, 1000])
def test_adjacent_or_sufficient_gap_is_not_flagged(gap):
    assert check_quality(document(cue(), cue(start=2000 + gap, end=4000 + gap))) == []


def test_contained_subtitles_all_detected_against_furthest_end():
    doc = document(cue(end=6000), cue(start=1000, end=2000), cue(start=3000, end=4000))
    issues = check_quality(doc)
    overlaps = [i for i in issues if i.code == "timing.overlap"]
    assert [(i.position, i.related_position) for i in overlaps] == [(1, 0), (2, 0)]
    assert "1.000 s" in overlaps[0].message


def test_overlap_checks_can_be_disabled():
    doc = document(cue(), cue(start=1000, end=3000))
    assert "timing.overlap" in codes(doc)
    assert "timing.overlap" not in codes(doc, QualitySettings(check_overlaps=False))


def test_ass_styles_and_layers_have_independent_timing_checks():
    doc = document(cue(style="Dialogue"), cue(style="Signs"),
                   cue(style="Dialogue", layer=1), fmt=SubtitleFormat.ASS)
    assert check_quality(doc) == []
    doc.entries.append(cue(style="Dialogue", start=1000, end=3000))
    assert "timing.overlap" in codes(doc)


def test_validation_never_modifies_document():
    doc = document(cue("<b>Long text</b>", end=100), cue("", start=50, end=10))
    before = deepcopy(doc)
    check_quality(doc)
    assert doc == before


def test_settings_round_trip_and_unknown_keys():
    settings = QualitySettings(max_cps=15.5, check_overlaps=False)
    assert QualitySettings.from_dict({**settings.to_dict(), "obsolete": 4}) == settings


@pytest.mark.parametrize("bad", [None, [], {"max_cps": "20"}, {"max_cps": float("inf")},
    {"max_cps": -1}, {"max_lines": 1.5}, {"min_gap_ms": True},
    {"min_duration_ms": 8000}, {"max_chars_per_line": 0}, {"check_overlaps": "no"}])
def test_bad_saved_settings_fall_back_to_defaults(bad):
    assert QualitySettings.from_dict(bad) == QualitySettings()


def test_invalid_settings_are_rejected_explicitly():
    with pytest.raises(ValueError):
        QualitySettings(max_duration_ms=100)
