"""Text editing workflows: formatting, timing precision, and exact undo states."""

from copy import deepcopy
import re

import pytest

from gsub.commands.command import CommandManager
from gsub.commands.text_commands import (
    MergeEntriesCommand,
    RebalanceTextCommand,
    SplitEntryCommand,
)
from gsub.models import SubtitleDocument, SubtitleEntry, SubtitleFormat, TimeCode
from gsub.parsers.ass_parser import ASSParser
from gsub.parsers.ass_tags import BLOCK_PATTERN, strip_override_blocks
from gsub.text_operations import merge_texts, rebalance_text, split_text, visible_text


def entry(text, start=1000, end=5000, **metadata):
    return SubtitleEntry(1, TimeCode.from_milliseconds(start),
                         TimeCode.from_milliseconds(end), text, **metadata)


def document(*entries, format_=SubtitleFormat.SRT):
    doc = SubtitleDocument(format=format_, entries=list(entries),
                           metadata={"Title": "Keep me"}, script_info_comments=["; Keep me"])
    doc.reindex()
    return doc


@pytest.mark.parametrize("format_", list(SubtitleFormat))
def test_plain_split_and_repeatable_history(format_):
    doc = document(entry("Hello world", layer=4, actor="Narrator", margin_l=55),
                   entry("Following", 7000, 8000), format_=format_)
    before = deepcopy(doc.entries)
    manager = CommandManager()
    command = SplitEntryCommand(doc, 0, 6, split_ms=3000)
    manager.execute(command)
    assert command.changed
    assert [item.text for item in doc.entries] == ["Hello", "world", "Following"]
    assert doc.entries[0].end_time.total_milliseconds == 3000
    assert doc.entries[1].start_time.total_milliseconds == 3000
    assert doc.entries[1].actor == "Narrator"
    assert doc.entries[1].layer == 4
    assert doc.entries[1].margin_l == 55
    assert [item.index for item in doc.entries] == [1, 2, 3]
    after = deepcopy(doc.entries)
    for _ in range(3):
        assert manager.undo()
        assert doc.entries == before
        assert manager.redo()
        assert doc.entries == after
    assert doc.metadata == {"Title": "Keep me"}
    assert doc.script_info_comments == ["; Keep me"]


@pytest.mark.parametrize("playhead", [None, 0, 1000, 5000, 8000])
def test_split_outside_playhead_falls_back_to_text_ratio(playhead):
    doc = document(entry("abc defghij"))
    command = SplitEntryCommand(doc, 0, 4, playhead)
    command.execute()
    assert command.split_ms == 2200
    assert doc.entries[0].duration_ms > 0
    assert doc.entries[1].duration_ms > 0


def test_ass_split_honors_centisecond_serialization_precision():
    doc = document(entry("ab cd", 0, 20), format_=SubtitleFormat.ASS)
    command = SplitEntryCommand(doc, 0, 3, 1)
    command.execute()
    assert command.split_ms == 10
    serialized = ASSParser.serialize(doc)
    reparsed = ASSParser.parse(serialized)
    assert all(item.duration_ms == 10 for item in reparsed.entries)


@pytest.mark.parametrize("format_,start,end", [
    (SubtitleFormat.SRT, 100, 101),
    (SubtitleFormat.ASS, 0, 10),
    (SubtitleFormat.SSA, 0, 0),
    (SubtitleFormat.SRT, 20, 0),
])
def test_split_rejects_duration_too_short_without_mutation(format_, start, end):
    doc = document(entry("two words", start, end), format_=format_)
    before = deepcopy(doc)
    with pytest.raises(ValueError, match="too short"):
        SplitEntryCommand(doc, 0, 4)
    assert doc == before


@pytest.mark.parametrize("text,offset,left,right", [
    (r"{\i1}Hello world", 6, r"{\i1}Hello", r"{\i1}world"),
    (r"{\i1}Hello {\i0}world", 6, r"{\i1}Hello", r"{\i1}{\i0}world"),
    (r"{\b1}One {\c&H00FF00&}two three", 8,
     r"{\b1}One {\c&H00FF00&}two", r"{\b1}{\c&H00FF00&}three"),
    ("مرحبا بالعالم", 6, "مرحبا", "بالعالم"),
    ("猫と犬 🐈と🐕", 4, "猫と犬", "🐈と🐕"),
])
def test_ass_split_preserves_static_inline_formatting(text, offset, left, right):
    assert split_text(text, SubtitleFormat.ASS, offset) == (left, right)


def test_ass_split_keeps_late_event_position_on_both_halves():
    left, right = split_text(r"Hello {\pos(10,20)}world", SubtitleFormat.ASS, 6)
    assert left == r"{\pos(10,20)}Hello"
    assert right == r"{\pos(10,20)}world"


@pytest.mark.parametrize("tag", [r"\t(0,500,\fs30)", r"\move(0,0,10,20)",
                                     r"\fad(100,100)", r"\fade(0,255,0,0,1,2,3)",
                                     r"\k20", r"\K20", r"\kf20", r"\p1"])
def test_ass_split_rejects_timed_and_drawing_effects(tag):
    doc = document(entry("{" + tag + "}Hello world"), format_=SubtitleFormat.ASS)
    before = deepcopy(doc)
    with pytest.raises(ValueError, match="effects"):
        SplitEntryCommand(doc, 0, 6)
    assert doc == before


def test_ass_split_rejects_ambiguous_global_tag_duplicates():
    with pytest.raises(ValueError, match="conflicting"):
        split_text(r"{\an2}Hello {\an8}world", SubtitleFormat.ASS, 6)


@pytest.mark.parametrize("offset", [0, 11, -1, 20])
def test_split_needs_two_nonempty_parts(offset):
    with pytest.raises(ValueError):
        split_text("Hello world", SubtitleFormat.ASS, offset)


def test_ass_split_does_not_bisect_escape_sequence():
    with pytest.raises(ValueError, match="escape"):
        split_text(r"Hello\Nworld", SubtitleFormat.ASS, 6)


def test_ass_split_rejects_unbalanced_override_blocks():
    with pytest.raises(ValueError, match="braces"):
        split_text(r"{\i1Hello world", SubtitleFormat.ASS, 6)


@pytest.mark.parametrize("text,offset,left,right", [
    ("<i>Hello world</i>", 9, "<i>Hello</i>", "<i>world</i>"),
    ('<font color="red"><b>Hello world</b></font>', 26,
     '<font color="red"><b>Hello</b></font>', '<font color="red"><b>world</b></font>'),
    ("<b>Hello</b> world", 13, "<b>Hello</b>", "world"),
    ("Cats &amp; dogs", 11, "Cats &amp;", "dogs"),
])
def test_srt_split_closes_and_reopens_nested_formatting(text, offset, left, right):
    assert split_text(text, SubtitleFormat.SRT, offset) == (left, right)


@pytest.mark.parametrize("text,offset", [
    ("<i>Hello world</i>", 2),
    ("Cats &amp; dogs", 8),
    ("<i>Hello world", 9),
    ("<i>Hello</b> world", 13),
    ("<unknown>Hello world</unknown>", 15),
])
def test_srt_split_rejects_broken_or_bisected_markup(text, offset):
    with pytest.raises(ValueError):
        split_text(text, SubtitleFormat.SRT, offset)


def test_merge_uses_timing_extrema_and_exact_snapshot_undo():
    doc = document(entry("First", 4000, 6000), entry("Second", 1000, 8000),
                   entry("Third", 9000, 10000))
    before = deepcopy(doc.entries)
    command = MergeEntriesCommand(doc, [1, 0, 1])
    command.execute()
    assert [item.text for item in doc.entries] == ["First\nSecond", "Third"]
    assert doc.entries[0].start_time.total_milliseconds == 1000
    assert doc.entries[0].end_time.total_milliseconds == 8000
    assert [item.index for item in doc.entries] == [1, 2]
    command.undo()
    assert doc.entries == before
    command.redo()
    assert doc.entries[0].text == "First\nSecond"


@pytest.mark.parametrize("positions", [[], [0], [0, 2], [-1, 0], [1, 3]])
def test_merge_requires_multiple_valid_adjacent_positions(positions):
    doc = document(entry("First"), entry("Second"), entry("Third"))
    before = deepcopy(doc)
    with pytest.raises(ValueError):
        MergeEntriesCommand(doc, positions)
    assert doc == before


@pytest.mark.parametrize("field,value", [
    ("style", "Title"), ("actor", "Someone else"), ("layer", 5),
    ("margin_l", 30), ("margin_r", 30), ("margin_v", 30), ("effect", "banner"),
])
def test_ass_merge_rejects_loss_of_differing_metadata(field, value):
    doc = document(entry("First"), entry("Second", **{field: value}), format_=SubtitleFormat.ASS)
    before = deepcopy(doc)
    with pytest.raises(ValueError, match="same style"):
        MergeEntriesCommand(doc, [0, 1])
    assert doc == before


def test_ass_merge_resets_local_overrides_between_cues():
    assert merge_texts([r"{\i1}First", "Second", r"{\b1}Third", "Fourth"], SubtitleFormat.ASS) == (
        "{\\i1}First\n{\\r}Second\n{\\b1}Third\n{\\r}Fourth"
    )


def test_ass_merge_plain_text_needs_no_redundant_reset():
    assert merge_texts(["First", "Second"], SubtitleFormat.ASS) == "First\nSecond"


def test_ass_merge_rejects_differently_positioned_events():
    with pytest.raises(ValueError, match="positioning"):
        merge_texts([r"{\pos(10,20)}First", "Second"], SubtitleFormat.ASS)


def test_ass_merge_preserves_common_metadata_and_positioning():
    doc = document(entry(r"{\an8}First", actor="Narrator", layer=3),
                   entry(r"{\an8}Second", actor="Narrator", layer=3),
                   format_=SubtitleFormat.ASS)
    command = MergeEntriesCommand(doc, [0, 1])
    command.execute()
    assert doc.entries[0].actor == "Narrator"
    assert doc.entries[0].layer == 3
    assert doc.entries[0].text == "{\\an8}First\n{\\an8}Second"


@pytest.mark.parametrize("format_", list(SubtitleFormat))
def test_rebalance_short_single_line_is_noop(format_):
    doc = document(entry("A short subtitle"), format_=format_)
    command = RebalanceTextCommand(doc, [0])
    assert not command.changed
    command.execute()
    assert not doc.modified
    assert doc.entries[0].text == "A short subtitle"


@pytest.mark.parametrize("format_", list(SubtitleFormat))
def test_rebalance_long_text_uses_balanced_word_boundary(format_):
    text = "These subtitles should have two well balanced lines for comfortable reading"
    result = rebalance_text(text, format_)
    lines = result.splitlines()
    assert len(lines) == 2
    assert all(len(line) <= 42 for line in lines)
    assert abs(len(lines[0]) - len(lines[1])) <= 8
    assert result.replace("\n", " ") == text


def test_rebalance_uses_visible_lengths_and_preserves_all_ass_blocks():
    text = r"{\i1\pos(10,20)}These subtitles {\b1}should have two well balanced lines"
    result = rebalance_text(text, SubtitleFormat.ASS, 30)
    assert BLOCK_PATTERN.findall(result) == BLOCK_PATTERN.findall(text)
    assert strip_override_blocks(result).replace("\n", " ") == strip_override_blocks(text)
    assert len(strip_override_blocks(result).splitlines()) == 2


def test_rebalance_srt_tags_and_entities_keep_original_spelling():
    text = '<font color="red">These cats &amp; dogs should have <i>two well balanced</i> lines</font>'
    result = rebalance_text(text, SubtitleFormat.SRT, 30)
    assert re.findall(r"<[^>]+>|&[\w#]+;", result) == re.findall(r"<[^>]+>|&[\w#]+;", text)
    assert visible_text(result, SubtitleFormat.SRT).replace("\n", " ") == (
        "These cats & dogs should have two well balanced lines"
    )


def test_rebalance_collapses_existing_linebreaks_and_spaces():
    assert rebalance_text("  Some\n text  ", SubtitleFormat.SRT) == "Some text"
    assert rebalance_text(r"{\i1}Some\Ntext", SubtitleFormat.ASS) == r"{\i1}Some text"


def test_rebalance_handles_space_on_both_sides_of_tag():
    assert rebalance_text(r"One {\i1} two", SubtitleFormat.ASS) == r"One {\i1}two"


def test_rebalance_preserves_unbreakable_spaces_and_words():
    text = "x" * 80
    assert rebalance_text(text, SubtitleFormat.SRT) == text
    assert rebalance_text(r"Hello\hworld", SubtitleFormat.ASS, 4) == r"Hello\hworld"
    assert rebalance_text("Hello&nbsp;world", SubtitleFormat.SRT, 4) == "Hello&nbsp;world"


def test_rebalance_multiple_selection_is_one_repeatable_undo_step():
    doc = document(entry("First\nsubtitle"), entry("Keep this"), entry("Third  subtitle"))
    before = deepcopy(doc.entries)
    manager = CommandManager()
    manager.execute(RebalanceTextCommand(doc, [0, 2]))
    assert [item.text for item in doc.entries] == ["First subtitle", "Keep this", "Third subtitle"]
    assert manager.undo()
    assert doc.entries == before
    assert not manager.can_undo()
    assert manager.redo()
    assert doc.entries[2].text == "Third subtitle"


def test_rebalance_rejects_unsafe_selection_atomically():
    doc = document(entry("First\nsubtitle"), entry(r"{\p1}m 0 0 l 10 10"),
                   format_=SubtitleFormat.ASS)
    before = deepcopy(doc)
    with pytest.raises(ValueError, match="effects"):
        RebalanceTextCommand(doc, [0, 1])
    assert doc == before


@pytest.mark.parametrize("positions", [[], [-1], [2]])
def test_rebalance_requires_valid_selection(positions):
    with pytest.raises(ValueError):
        RebalanceTextCommand(document(entry("Text")), positions)


def test_invalid_rebalance_line_length_is_rejected():
    with pytest.raises(ValueError, match="positive"):
        rebalance_text("Text", SubtitleFormat.SRT, 0)


@pytest.mark.parametrize("operation", ["split", "merge"])
def test_scrolling_ass_effects_are_rejected(operation):
    doc = document(entry("First words", effect="Scroll up;0;400;20"),
                   entry("Second words", effect="Scroll up;0;400;20"),
                   format_=SubtitleFormat.ASS)
    with pytest.raises(ValueError, match="Scrolling"):
        if operation == "split":
            SplitEntryCommand(doc, 0, 6)
        else:
            MergeEntriesCommand(doc, [0, 1])
