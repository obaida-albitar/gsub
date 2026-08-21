"""Pure-logic tests for subtitle list helpers.

Covers the timing derivation used by "add/insert subtitle" and the Pango
highlighting used by the list search. No GTK display is required.
"""

import pytest

from gsub.models import SubtitleDocument, SubtitleEntry, SubtitleFormat, TimeCode
from gsub.commands.subtitle_commands import (
    NEW_ENTRY_DURATION_MS,
    NEW_ENTRY_END_OFFSET_MS,
    NEW_ENTRY_GAP_MS,
    NEW_ENTRY_MIN_DURATION_MS,
    build_new_entry,
)


def _entry(start_ms, end_ms, text="x"):
    return SubtitleEntry(
        index=0,
        start_time=TimeCode.from_milliseconds(start_ms),
        end_time=TimeCode.from_milliseconds(end_ms),
        text=text,
    )


def _doc_with(*entries):
    doc = SubtitleDocument(format=SubtitleFormat.SRT)
    doc.entries = list(entries)
    doc.reindex()
    return doc


class TestBuildNewEntry:
    def test_empty_document(self):
        entry = build_new_entry(SubtitleDocument(format=SubtitleFormat.SRT), 0)
        assert entry.start_time.total_milliseconds == 0
        assert entry.duration_ms == NEW_ENTRY_DURATION_MS
        assert entry.text == "New subtitle"

    def test_at_end_uses_offset_after_last_entry(self):
        doc = _doc_with(_entry(0, 2000), _entry(3000, 5000))
        entry = build_new_entry(doc, 2)
        assert entry.start_time.total_milliseconds == 5000 + NEW_ENTRY_END_OFFSET_MS
        assert entry.duration_ms == NEW_ENTRY_DURATION_MS

    def test_between_entries_prefers_default_duration_within_gap(self):
        # Gap between 2000 and 10000: starts after previous +100ms and keeps
        # the default 2s duration (it fits before the next entry).
        doc = _doc_with(_entry(0, 2000), _entry(10000, 12000))
        entry = build_new_entry(doc, 1)
        assert entry.start_time.total_milliseconds == 2000 + NEW_ENTRY_GAP_MS
        assert entry.duration_ms == NEW_ENTRY_DURATION_MS

    def test_between_entries_caps_to_next_start(self):
        # Gap of 1.5s: the default 2s duration doesn't fit, so the entry is
        # capped to end 100ms before the next one.
        doc = _doc_with(_entry(0, 1000), _entry(2600, 4000))
        entry = build_new_entry(doc, 1)
        assert entry.start_time.total_milliseconds == 1000 + NEW_ENTRY_GAP_MS
        assert entry.end_time.total_milliseconds == 2600 - NEW_ENTRY_GAP_MS

    def test_tight_gap_falls_back_to_minimum_duration(self):
        # Only ~200ms of room: the minimum 200ms duration is used even though
        # it slightly overlaps the next entry.
        doc = _doc_with(_entry(0, 1000), _entry(1300, 2000))
        entry = build_new_entry(doc, 1)
        assert entry.start_time.total_milliseconds == 1000 + NEW_ENTRY_GAP_MS
        assert entry.duration_ms == NEW_ENTRY_MIN_DURATION_MS

    def test_insert_at_front_without_previous(self):
        doc = _doc_with(_entry(5000, 8000))
        entry = build_new_entry(doc, 0)
        assert entry.start_time.total_milliseconds == 0
        assert entry.duration_ms == NEW_ENTRY_DURATION_MS

    @pytest.mark.parametrize("position", [-1, 99])
    def test_out_of_range_position_clamps_to_end(self, position):
        doc = _doc_with(_entry(0, 2000))
        entry = build_new_entry(doc, position)
        assert entry.start_time.total_milliseconds == 2000 + NEW_ENTRY_END_OFFSET_MS


class TestHighlightMarkup:
    @pytest.fixture(autouse=True)
    def _import_highlight(self):
        pytest.importorskip("gi")
        from gi.repository import GLib  # noqa: F401  (markup escaping backend)
        from gsub.widgets.subtitle_list import highlight_markup
        self.highlight = highlight_markup

    def test_no_term_escapes_only(self):
        assert self.highlight("plain text", "") == "plain text"

    def test_escapes_markup_characters(self):
        assert self.highlight("a & <b>", "") == "a &amp; &lt;b&gt;"

    def test_wraps_case_insensitive_matches(self):
        result = self.highlight("say hello, HELLO!", "hello")
        assert result == "say <b>hello</b>, <b>HELLO</b>!"

    def test_escapes_text_around_match(self):
        result = self.highlight("a & hello", "hello")
        assert result == "a &amp; <b>hello</b>"

    def test_match_inside_markup_characters(self):
        # The needle must be found in the raw text, not the escaped one.
        result = self.highlight("<hello>", "hello")
        assert result == "&lt;<b>hello</b>&gt;"

    def test_no_match_returns_escaped_text(self):
        assert self.highlight("abc", "xyz") == "abc"

    def test_overlapping_matches_advance_past_match(self):
        assert self.highlight("aaaa", "aa") == "<b>aa</b><b>aa</b>"
