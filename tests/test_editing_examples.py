"""Exercise the user-facing example files through actual load/edit/save flows."""

from collections import Counter
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from gsub.commands import CommandManager
from gsub.commands.batch_commands import BatchOperationsCommand
from gsub.commands.text_commands import MergeEntriesCommand, RebalanceTextCommand, SplitEntryCommand
from gsub.models import SubtitleFormat
from gsub.parsers import ASSParser, SRTParser, parse_subtitle_document
from gsub.parsers.ass_tags import BLOCK_PATTERN
from gsub.quality import check_quality, text_metrics
from gsub.search import SearchOptions, build_replace_command, find_matches, visible_text


EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
EXPECTED_ISSUES = {
    2: "timing.too_short",
    3: "text.reading_speed",
    4: "text.line_length",
    5: "text.line_count",
    6: "timing.too_long",
    8: "timing.overlap",
    9: "timing.small_gap",
    10: "text.empty",
    11: "timing.invalid_duration",
    15: "text.line_length",
}

pytestmark = pytest.mark.integration


def load(name):
    path = EXAMPLES / name
    doc, warnings = parse_subtitle_document(path.read_text(encoding="utf-8"), path.suffix)
    assert doc is not None
    assert warnings == []
    return doc


def serialize(doc):
    parser = SRTParser if doc.format == SubtitleFormat.SRT else ASSParser
    return parser.serialize(doc)


@pytest.fixture(params=["srt", "ass"])
def sample(request):
    return load(f"editing_tools_test.{request.param}")


def save_and_reopen(doc, tmp_path):
    output = tmp_path / f"edited.{doc.format.value}"
    output.write_text(serialize(doc), encoding="utf-8")
    reopened, warnings = parse_subtitle_document(output.read_text(encoding="utf-8"), output.suffix)
    assert warnings == []
    assert reopened.entries == doc.entries
    assert reopened.styles == doc.styles
    return reopened


def test_main_example_has_exact_documented_quality_results(sample):
    assert len(sample.entries) == (18 if sample.format == SubtitleFormat.SRT else 25)
    before = deepcopy(sample)
    issues = check_quality(sample)
    assert Counter((issue.position + 1, issue.code) for issue in issues) == Counter(
        (number, code) for number, code in EXPECTED_ISSUES.items())
    assert sample == before


@pytest.mark.parametrize("extension", ["srt", "ass"])
def test_batch_partner_is_clean(extension):
    partner = load(f"batch_undo_partner.{extension}")
    assert len(partner.entries) == 3
    assert check_quality(partner) == []


def test_formatted_split_survives_save_reopen_and_undo(sample, tmp_path):
    manager = CommandManager()
    before = serialize(sample)
    offset = len("<i>Meet me") if sample.format == SubtitleFormat.SRT else len("Meet me")
    manager.execute(SplitEntryCommand(sample, 11, offset))
    first, second = sample.entries[11:13]
    assert visible_text(first.text, sample.format) == "Meet me"
    assert visible_text(second.text, sample.format) == "by the ticket office."
    assert first.start_time.total_milliseconds == 38000
    assert second.end_time.total_milliseconds == 43000
    assert first.end_time == second.start_time
    assert first.duration_ms > 0 and second.duration_ms > 0
    if sample.format == SubtitleFormat.SRT:
        assert first.text == "<i>Meet me</i>"
        assert second.text == "<i>by the ticket office.</i>"
    else:
        assert first.text.startswith(r"{\i1}")
        assert second.text.startswith(r"{\i1}")
        assert first.actor == second.actor == "Mira"
    after = serialize(sample)
    save_and_reopen(sample, tmp_path)
    manager.undo()
    assert serialize(sample) == before
    manager.redo()
    assert serialize(sample) == after


def test_merge_keeps_bold_from_spilling_into_second_sentence(sample, tmp_path):
    manager = CommandManager()
    before = serialize(sample)
    manager.execute(MergeEntriesCommand(sample, [12, 13]))
    merged = sample.entries[12]
    assert visible_text(merged.text, sample.format) == "Keep the ticket.\nIt is our way home."
    assert merged.start_time.total_milliseconds == 43300
    assert merged.end_time.total_milliseconds == 49000
    if sample.format == SubtitleFormat.SRT:
        assert merged.text == "<b>Keep the ticket.</b>\nIt is our way home."
    else:
        assert merged.text == "{\\b1}Keep the ticket.\n{\\r}It is our way home."
    save_and_reopen(sample, tmp_path)
    manager.undo()
    assert serialize(sample) == before


def test_rebalance_fixes_both_long_lines_in_one_undo_step(sample, tmp_path):
    manager = CommandManager()
    before = serialize(sample)
    originals = [deepcopy(sample.entries[position]) for position in (3, 14)]
    manager.execute(RebalanceTextCommand(sample, [3, 14]))
    for position, original in zip((3, 14), originals):
        current = sample.entries[position]
        metrics = text_metrics(current.text, current.duration_ms, sample.format)
        assert metrics.line_count == 2
        assert metrics.longest_line <= 42
        assert " ".join(visible_text(current.text, sample.format).split()) == original.text
        assert (current.start_time, current.end_time) == (original.start_time, original.end_time)
    assert not any(issue.code == "text.line_length" for issue in check_quality(sample))
    save_and_reopen(sample, tmp_path)
    manager.undo()
    assert serialize(sample) == before
    assert not manager.can_undo()


def test_search_counts_match_manual_exercises(sample):
    assert len(find_matches(sample, "ticket")) == 7
    assert len(find_matches(sample, "ticket", SearchOptions(whole_words=True))) == 6
    for options, expected in ((SearchOptions(), 4),
                              (SearchOptions(whole_words=True), 3),
                              (SearchOptions(case_sensitive=True), 2),
                              (SearchOptions(case_sensitive=True, whole_words=True), 1)):
        assert len(find_matches(sample, "ticket", options, positions=[15])) == expected
    assert [match.position for match in find_matches(sample, "STRASSE")] == [17]


def test_replace_all_preserves_inline_tags_save_and_one_step_undo(sample, tmp_path):
    before = serialize(sample)
    original = sample.entries[16].text
    manager = CommandManager()
    manager.execute(build_replace_command(sample, find_matches(sample, "ticket"), "pass"))
    updated = sample.entries[16].text
    assert visible_text(updated, sample.format) == "pass inspectors are on board."
    if sample.format == SubtitleFormat.ASS:
        assert BLOCK_PATTERN.findall(updated) == BLOCK_PATTERN.findall(original)
    else:
        assert updated == "<i>pass</i> inspectors are on board."
    assert not find_matches(sample, "ticket")
    assert len(find_matches(sample, "pass")) == 7
    after = serialize(sample)
    save_and_reopen(sample, tmp_path)
    manager.undo()
    assert serialize(sample) == before
    assert not manager.can_undo()
    manager.redo()
    assert serialize(sample) == after


def test_ass_special_cases_are_accepted_or_rejected_without_losing_data():
    doc = load("editing_tools_test.ass")
    assert not any(issue.position >= 18 for issue in check_quality(doc))
    before = serialize(doc)
    for position in (20, 21, 22):
        with pytest.raises(ValueError):
            SplitEntryCommand(doc, position, 5)
        assert serialize(doc) == before
    for position in (20, 21):
        with pytest.raises(ValueError):
            RebalanceTextCommand(doc, [position])
        assert serialize(doc) == before
    with pytest.raises(ValueError, match="style"):
        MergeEntriesCommand(doc, [23, 24])
    assert serialize(doc) == before


def test_batch_pair_restores_clamped_times_styles_and_resolution(sample, tmp_path):
    extension = sample.format.value
    partner = load(f"batch_undo_partner.{extension}")
    items = [SimpleNamespace(document=doc, modified=False) for doc in (sample, partner)]
    before = [serialize(item.document) for item in items]
    manager = CommandManager()
    command = BatchOperationsCommand(
        items, offset_ms=-1000,
        resolution=(1920, 1080) if sample.format == SubtitleFormat.ASS else None,
        target_styles=["Default"],
        style_properties={"fontsize": 48} if sample.format == SubtitleFormat.ASS else None)
    manager.execute(command)
    assert command.changed_count == 2
    after = [serialize(item.document) for item in items]
    assert all(item.document.entries[0].start_time.total_milliseconds == 0 for item in items)
    for number, item in enumerate(items):
        directory = tmp_path / str(number)
        directory.mkdir()
        save_and_reopen(item.document, directory)
        if sample.format == SubtitleFormat.ASS:
            assert item.document.metadata["PlayResX"] == "1920"
            assert item.document.get_style_by_name("Default").fontsize == 48
            assert item.document.get_style_by_name("Sign").fontsize == 36
    manager.undo()
    assert [serialize(item.document) for item in items] == before
    assert [item.document.entries[0].start_time.total_milliseconds for item in items] == [200, 100]
    assert not manager.can_undo()
    manager.redo()
    assert [serialize(item.document) for item in items] == after
