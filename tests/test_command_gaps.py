"""Tests for untested commands and additional coverage."""

import pytest
from subtitle_editor.commands import (
    CommandManager, AddEntryCommand, DuplicateEntryCommand,
    BatchTimingCommand, EditMarginsCommand, SortByTimeCommand,
    BulkEditStyleCommand,
)
from subtitle_editor.models import TimeCode, SubtitleEntry, SubtitleDocument, SubtitleFormat


class TestEditMarginsCommand:
    """Tests for EditMarginsCommand."""

    @pytest.mark.unit
    @pytest.mark.command
    def test_edit_margins_execute(self, sample_ass_document):
        cmd = EditMarginsCommand(sample_ass_document, 0, new_margin_l=10, new_margin_r=20, new_margin_v=30)
        cmd.execute()
        assert sample_ass_document.entries[0].margin_l == 10
        assert sample_ass_document.entries[0].margin_r == 20
        assert sample_ass_document.entries[0].margin_v == 30
        assert sample_ass_document.modified is True

    @pytest.mark.unit
    @pytest.mark.command
    def test_edit_margins_undo(self, sample_ass_document):
        cmd = EditMarginsCommand(sample_ass_document, 0, new_margin_l=10, new_margin_r=20, new_margin_v=30)
        cmd.execute()
        cmd.undo()
        assert sample_ass_document.entries[0].margin_l == 0
        assert sample_ass_document.entries[0].margin_r == 0
        assert sample_ass_document.entries[0].margin_v == 0

    @pytest.mark.unit
    @pytest.mark.command
    def test_edit_margins_invalid_position(self, sample_ass_document):
        cmd = EditMarginsCommand(sample_ass_document, 999, new_margin_l=10, new_margin_r=20, new_margin_v=30)
        cmd.execute()

    @pytest.mark.unit
    @pytest.mark.command
    def test_edit_margins_marks_modified(self, sample_ass_document):
        sample_ass_document.modified = False
        cmd = EditMarginsCommand(sample_ass_document, 0, new_margin_l=10, new_margin_r=20, new_margin_v=30)
        cmd.execute()
        assert sample_ass_document.modified is True


class TestSortByTimeCommand:
    """Tests for SortByTimeCommand."""

    @pytest.mark.unit
    @pytest.mark.command
    def test_sort_by_time_execute(self):
        doc = SubtitleDocument(format=SubtitleFormat.SRT)
        doc.entries = [
            SubtitleEntry(3, TimeCode(0, 0, 5, 0), TimeCode(0, 0, 8, 0), "Third"),
            SubtitleEntry(2, TimeCode(0, 0, 2, 0), TimeCode(0, 0, 4, 0), "Second"),
            SubtitleEntry(1, TimeCode(0, 0, 0, 500), TimeCode(0, 0, 2, 0), "First"),
        ]
        cmd = SortByTimeCommand(doc)
        cmd.execute()
        assert doc.entries[0].text == "First"
        assert doc.entries[1].text == "Second"
        assert doc.entries[2].text == "Third"
        assert doc.modified is True

    @pytest.mark.unit
    @pytest.mark.command
    def test_sort_by_time_undo(self):
        doc = SubtitleDocument(format=SubtitleFormat.SRT)
        doc.entries = [
            SubtitleEntry(3, TimeCode(0, 0, 5, 0), TimeCode(0, 0, 8, 0), "Third"),
            SubtitleEntry(2, TimeCode(0, 0, 2, 0), TimeCode(0, 0, 4, 0), "Second"),
            SubtitleEntry(1, TimeCode(0, 0, 0, 500), TimeCode(0, 0, 2, 0), "First"),
        ]
        cmd = SortByTimeCommand(doc)
        cmd.execute()
        cmd.undo()
        assert doc.entries[0].text == "Third"
        assert doc.entries[1].text == "Second"
        assert doc.entries[2].text == "First"

    @pytest.mark.unit
    @pytest.mark.command
    def test_sort_by_time_single_entry(self):
        doc = SubtitleDocument(format=SubtitleFormat.SRT)
        doc.entries = [
            SubtitleEntry(1, TimeCode(0, 0, 5, 0), TimeCode(0, 0, 8, 0), "Only"),
        ]
        cmd = SortByTimeCommand(doc)
        cmd.execute()
        assert len(doc.entries) == 1
        assert doc.entries[0].text == "Only"

    @pytest.mark.unit
    @pytest.mark.command
    def test_sort_by_time_empty_doc(self):
        doc = SubtitleDocument(format=SubtitleFormat.SRT)
        cmd = SortByTimeCommand(doc)
        cmd.execute()
        assert len(doc.entries) == 0

    @pytest.mark.unit
    @pytest.mark.command
    def test_sort_by_time_already_sorted(self):
        doc = SubtitleDocument(format=SubtitleFormat.SRT)
        doc.entries = [
            SubtitleEntry(1, TimeCode(0, 0, 0, 500), TimeCode(0, 0, 2, 0), "First"),
            SubtitleEntry(2, TimeCode(0, 0, 2, 0), TimeCode(0, 0, 4, 0), "Second"),
            SubtitleEntry(3, TimeCode(0, 0, 5, 0), TimeCode(0, 0, 8, 0), "Third"),
        ]
        cmd = SortByTimeCommand(doc)
        cmd.execute()
        assert doc.entries[0].text == "First"
        assert doc.entries[1].text == "Second"
        assert doc.entries[2].text == "Third"


class TestDuplicateEntryCommand:
    """Additional tests for DuplicateEntryCommand."""

    @pytest.mark.unit
    @pytest.mark.command
    def test_duplicate_entry_with_style_none(self, sample_ass_document):
        sample_ass_document.entries[0].style = None
        cmd = DuplicateEntryCommand(sample_ass_document, 0)
        cmd.execute()
        assert len(sample_ass_document.entries) == 3
        assert sample_ass_document.entries[1].style is None

    @pytest.mark.unit
    @pytest.mark.command
    def test_duplicate_entry_with_full_fields(self):
        doc = SubtitleDocument(format=SubtitleFormat.ASS)
        original = SubtitleEntry(
            index=1,
            start_time=TimeCode(0, 0, 0, 500),
            end_time=TimeCode(0, 0, 2, 0),
            text="Original",
            style="Default",
            layer=3,
            actor="Narrator",
            effect="fade",
            margin_l=5,
            margin_r=10,
            margin_v=15,
        )
        doc.entries.append(original)
        cmd = DuplicateEntryCommand(doc, 0)
        cmd.execute()
        assert len(doc.entries) == 2
        dup = doc.entries[1]
        assert dup.text == original.text
        assert dup.style == original.style


class TestAddEntryCommand:
    """Additional tests for AddEntryCommand."""

    @pytest.mark.unit
    @pytest.mark.command
    def test_add_entry_at_specific_position(self, sample_srt_document):
        entry = SubtitleEntry(99, TimeCode(0, 0, 10, 0), TimeCode(0, 0, 11, 0), "Inserted at 0")
        cmd = AddEntryCommand(sample_srt_document, entry, position=0)
        cmd.execute()
        assert sample_srt_document.entries[0].text == "Inserted at 0"
        assert sample_srt_document.entries[1].text == "First subtitle"

    @pytest.mark.unit
    @pytest.mark.command
    def test_add_entry_at_end_default(self, sample_srt_document):
        entry = SubtitleEntry(99, TimeCode(0, 0, 10, 0), TimeCode(0, 0, 11, 0), "Appended")
        cmd = AddEntryCommand(sample_srt_document, entry)
        cmd.execute()
        assert sample_srt_document.entries[-1].text == "Appended"


class TestBatchTimingCommand:
    """Additional tests for BatchTimingCommand."""

    @pytest.mark.unit
    @pytest.mark.command
    def test_batch_timing_invalid_positions(self, sample_srt_document):
        adjustments = [
            (999, TimeCode(0, 0, 1, 0), TimeCode(0, 0, 2, 0)),
            (0, TimeCode(0, 0, 3, 0), TimeCode(0, 0, 4, 0)),
        ]
        cmd = BatchTimingCommand(sample_srt_document, adjustments)
        cmd.execute()
        assert sample_srt_document.entries[0].start_time.total_milliseconds == 3000

    @pytest.mark.unit
    @pytest.mark.command
    def test_batch_timing_all_entries(self, sample_srt_document):
        adjustments = [
            (0, TimeCode(0, 0, 1, 0), TimeCode(0, 0, 2, 0)),
            (1, TimeCode(0, 0, 3, 0), TimeCode(0, 0, 4, 0)),
            (2, TimeCode(0, 0, 5, 0), TimeCode(0, 0, 6, 0)),
        ]
        cmd = BatchTimingCommand(sample_srt_document, adjustments)
        cmd.execute()
        assert sample_srt_document.entries[0].start_time.total_milliseconds == 1000


class TestCommandManager:
    """Additional tests for CommandManager."""

    @pytest.mark.unit
    @pytest.mark.command
    def test_command_manager_clear(self, sample_srt_document):
        cm = CommandManager()
        entry1 = SubtitleEntry(99, TimeCode(0, 0, 10, 0), TimeCode(0, 0, 11, 0), "Test1")
        entry2 = SubtitleEntry(100, TimeCode(0, 0, 12, 0), TimeCode(0, 0, 13, 0), "Test2")
        cm.execute(AddEntryCommand(sample_srt_document, entry1))
        cm.execute(AddEntryCommand(sample_srt_document, entry2))
        cm.clear()
        assert cm.can_undo() is False
        assert cm.can_redo() is False

    @pytest.mark.unit
    @pytest.mark.command
    def test_command_manager_get_descriptions(self, sample_srt_document):
        cm = CommandManager()
        entry = SubtitleEntry(99, TimeCode(0, 0, 10, 0), TimeCode(0, 0, 11, 0), "Test")
        cmd = AddEntryCommand(sample_srt_document, entry)
        cm.execute(cmd)
        undo_desc = cm.get_undo_description()
        assert undo_desc is not None and len(undo_desc) > 0
        cm.undo()
        redo_desc = cm.get_redo_description()
        assert redo_desc is not None and len(redo_desc) > 0


class TestBulkEditStyleCommand:
    """Additional tests for BulkEditStyleCommand."""

    @pytest.mark.unit
    @pytest.mark.command
    def test_bulk_edit_style_undo_marks_modified(self, sample_ass_document):
        sample_ass_document.modified = False
        cmd = BulkEditStyleCommand(sample_ass_document, [0, 1], "Title")
        cmd.execute()
        cmd.undo()
        assert sample_ass_document.modified is True
