"""Continuous review state, stable exceptions and stale-safe fix previews."""

from copy import deepcopy

import pytest

from gsub.commands.command import CommandManager
from gsub.models import SubtitleDocument, SubtitleEntry, SubtitleFormat, TimeCode
from gsub.quality import QualitySettings
from gsub.quality_review import QualityReview


LONG_TEXT = "This subtitle needs a balanced break between its words."
LIMITS = QualitySettings(max_chars_per_line=28, max_cps=100,
                         min_duration_ms=0, max_duration_ms=100_000, min_gap_ms=0)


def cue(text=LONG_TEXT, start=1000, end=5000):
    return SubtitleEntry(1, TimeCode.from_milliseconds(start),
                         TimeCode.from_milliseconds(end), text)


def review(*entries, fmt=SubtitleFormat.SRT, settings=LIMITS):
    doc = SubtitleDocument(fmt, entries=list(entries))
    doc.reindex()
    return QualityReview(doc, settings)


def choose(state, code, position=None):
    issue = next(issue for issue in state.issues
                 if issue.code == code and (position is None or issue.position == position))
    state.select_key(state.issue_key(issue))
    return issue


def test_review_never_changes_subtitle_content_or_modified_state():
    state = review(cue())
    before = deepcopy(state.document)
    state.dismiss_current()
    state.set_filter("text.line_length")
    state.reset_ignored()
    assert state.document == before
    assert not state.document.modified


def test_filter_and_navigation_wrap_without_selecting_nonmatching_issues():
    state = review(cue(), cue("", 6000, 9000), cue(start=10_000, end=13_000))
    state.set_filter("text.line_length")
    assert [issue.position for issue in state.issues] == [0, 2]
    assert state.move(-1).position == 2
    assert state.move(1).position == 0
    state.set_filter("timing.invalid_duration")
    assert state.current_issue is None
    assert state.move(1) is None


def test_ignored_issue_reappears_after_text_changes():
    state = review(cue())
    state.dismiss_current()
    assert not state.issues
    assert state.ignored_count == 1
    state.document.entries[0].text += " More words."
    state.refresh()
    assert [issue.code for issue in state.issues] == ["text.line_length"]
    assert state.ignored_count == 0


def test_unrelated_insert_and_reindex_keeps_warning_ignored():
    state = review(cue())
    original = state.document.entries[0]
    state.dismiss_current()
    state.document.entries.insert(0, cue("A new cue", 0, 500))
    state.document.reindex()
    state.refresh()
    assert not state.issues
    assert state.document.entries[1] is original
    assert state.ignored_count == 1


def test_deepcopy_based_commands_keep_exceptions_for_unchanged_cues():
    state = review(cue(), cue("Short", 6000, 8000))
    state.dismiss_current()
    state.document.entries[:] = deepcopy(state.document.entries)
    state.document.entries[1].text = "Changed but still short"
    state.refresh()
    assert not state.issues
    assert state.ignored_count == 1


@pytest.mark.parametrize("before", [True, False])
def test_duplicate_gets_its_own_warning_even_when_inserted_before_original(before):
    state = review(cue())
    original = state.document.entries[0]
    state.dismiss_current()
    duplicate = deepcopy(original)
    state.document.entries.insert(0 if before else 1, duplicate)
    state.document.reindex()
    state.refresh()
    length_issues = [issue for issue in state.issues if issue.code == "text.line_length"]
    assert len(length_issues) == 1
    assert state.document.entries[length_issues[0].position] is duplicate
    assert state.ignored_count == 1


def test_ignored_overlap_survives_unrelated_insert_and_message_renumbering():
    state = review(cue("First", 1000, 4000), cue("Second", 3000, 6000))
    choose(state, "timing.overlap")
    state.dismiss_current()
    state.document.entries.insert(0, cue("Earlier", 0, 500))
    state.document.reindex()
    state.refresh()
    assert not state.issues
    assert state.ignored_count == 1
    assert "subtitle 2" in state.all_issues[0].message


def test_changing_related_cue_brings_overlap_warning_back():
    state = review(cue("First", 1000, 4000), cue("Second", 3000, 6000))
    state.dismiss_current()
    state.document.entries[0].end_time = TimeCode.from_milliseconds(4500)
    state.refresh()
    assert state.current_issue.code == "timing.overlap"


def test_reset_ignored_and_limit_change_reveal_warnings():
    state = review(cue())
    state.dismiss_current()
    state.reset_ignored()
    assert len(state.issues) == 1
    state.dismiss_current()
    state.settings = QualitySettings(max_chars_per_line=25, max_cps=100,
        min_duration_ms=0, max_duration_ms=100_000, min_gap_ms=0)
    state.refresh()
    assert len(state.issues) == 1


def test_current_issue_follows_its_cue_after_moving():
    state = review(cue(), cue(LONG_TEXT + " Second.", 6000, 9000))
    state.move(1)
    original = state.document.entries.pop(1)
    state.document.entries.insert(0, original)
    state.document.reindex()
    state.refresh()
    assert state.current_issue.position == 0
    assert state.document.entries[0] is original


@pytest.mark.parametrize("fmt,text", [
    (SubtitleFormat.SRT, "<i>" + LONG_TEXT + "</i>"),
    (SubtitleFormat.ASS, r"{\b1}" + LONG_TEXT + r"{\b0}"),
    (SubtitleFormat.SSA, r"{\i1}" + LONG_TEXT),
])
def test_rebalance_preview_preserves_formatting_and_undo_redo(fmt, text):
    state = review(cue(text), fmt=fmt)
    choose(state, "text.line_length")
    preview = state.preview_rebalance()
    assert preview.before == text
    assert "\n" in preview.after
    assert state.document.entries[0].text == text
    manager = CommandManager()
    manager.execute(state.command_for_preview(preview))
    assert state.document.entries[0].text == preview.after
    manager.undo()
    assert state.document.entries[0].text == text
    manager.redo()
    assert state.document.entries[0].text == preview.after


@pytest.mark.parametrize("prefix", [r"{\k10}", r"{\p1}m 0 0 l 1 1{\p0}", r"{\pbo3}"])
def test_ass_karaoke_and_drawings_explain_why_manual_editing_is_needed(prefix):
    state = review(cue(prefix + LONG_TEXT), fmt=SubtitleFormat.ASS)
    choose(state, "text.line_length")
    with pytest.raises(ValueError, match="drawing, karaoke"):
        state.preview_rebalance()


def test_other_issue_types_have_no_rebalance_fix():
    state = review(cue("", 0, 1000))
    with pytest.raises(ValueError, match="line-length or line-count"):
        state.preview_rebalance()


def test_unbreakable_word_does_not_offer_a_noop_fix():
    state = review(cue("x" * 80))
    with pytest.raises(ValueError, match="already balanced"):
        state.preview_rebalance()


@pytest.mark.parametrize("field", ["text", "timing", "metadata"])
def test_preview_cannot_overwrite_changed_source_cue(field):
    state = review(cue())
    preview = state.preview_rebalance()
    entry = state.document.entries[0]
    if field == "text":
        entry.text += " New typing."
    elif field == "timing":
        entry.end_time = TimeCode.from_milliseconds(6000)
    else:
        entry.actor = "A different speaker"
    with pytest.raises(ValueError, match="subtitle changed"):
        state.command_for_preview(preview)


def test_preview_cannot_apply_after_quality_limits_change():
    state = review(cue())
    preview = state.preview_rebalance()
    state.settings = QualitySettings(max_chars_per_line=20)
    with pytest.raises(ValueError, match="quality limits changed"):
        state.command_for_preview(preview)


def test_preview_cannot_cross_documents():
    first, second = review(cue()), review(cue())
    with pytest.raises(ValueError, match="document changed"):
        second.command_for_preview(first.preview_rebalance())


def test_apply_builds_fresh_snapshot_preserving_newer_edits_to_other_cues():
    state = review(cue(), cue("Other cue", 6000, 8000))
    preview = state.preview_rebalance()
    state.document.entries[1].text = "Newer peer edit"
    command = state.command_for_preview(preview)
    command.execute()
    assert state.document.entries[1].text == "Newer peer edit"
    command.undo()
    assert state.document.entries[0].text == LONG_TEXT
    assert state.document.entries[1].text == "Newer peer edit"


def test_preview_applies_to_same_cue_after_an_unrelated_insertion():
    state = review(cue())
    preview = state.preview_rebalance()
    state.document.entries.insert(0, cue("New", 0, 500))
    state.document.reindex()
    state.refresh()
    state.command_for_preview(preview).execute()
    assert state.document.entries[0].text == "New"
    assert state.document.entries[1].text == preview.after


def test_line_count_issue_can_preview_rebalance():
    state = review(cue("One\ntwo\nthree"))
    choose(state, "text.line_count")
    assert state.preview_rebalance().after == "One two three"
