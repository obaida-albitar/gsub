"""Unit tests for command pattern and subtitle commands."""

import pytest
from subtitle_editor.commands import (
    CommandManager, AddEntryCommand, RemoveEntryCommand, EditTextCommand,
    EditTimingCommand, DuplicateEntryCommand, MoveEntryCommand,
    TimeShiftCommand, BatchTimingCommand
)
from subtitle_editor.models import TimeCode, SubtitleEntry


class TestCommandManager:
    """Tests for CommandManager."""

    @pytest.mark.unit
    @pytest.mark.command
    def test_command_manager_initialization(self):
        """Test CommandManager initialization."""
        cm = CommandManager()
        assert cm.can_undo() is False
        assert cm.can_redo() is False

    @pytest.mark.unit
    @pytest.mark.command
    def test_command_manager_max_history(self):
        """Test CommandManager respects max history."""
        cm = CommandManager(max_history=5)
        assert cm._max_history == 5

    @pytest.mark.unit
    @pytest.mark.command
    def test_execute_command(self, sample_srt_document, sample_entry):
        """Test executing a command."""
        cm = CommandManager()
        cmd = AddEntryCommand(sample_srt_document, sample_entry)
        
        initial_count = len(sample_srt_document.entries)
        cm.execute(cmd)
        
        assert len(sample_srt_document.entries) == initial_count + 1
        assert cm.can_undo() is True
        assert cm.can_redo() is False

    @pytest.mark.unit
    @pytest.mark.command
    def test_undo_command(self, sample_srt_document, sample_entry):
        """Test undoing a command."""
        cm = CommandManager()
        cmd = AddEntryCommand(sample_srt_document, sample_entry)
        
        initial_count = len(sample_srt_document.entries)
        cm.execute(cmd)
        cm.undo()
        
        assert len(sample_srt_document.entries) == initial_count
        assert cm.can_undo() is False
        assert cm.can_redo() is True

    @pytest.mark.unit
    @pytest.mark.command
    def test_redo_command(self, sample_srt_document, sample_entry):
        """Test redoing a command."""
        cm = CommandManager()
        cmd = AddEntryCommand(sample_srt_document, sample_entry)
        
        initial_count = len(sample_srt_document.entries)
        cm.execute(cmd)
        cm.undo()
        cm.redo()
        
        assert len(sample_srt_document.entries) == initial_count + 1
        assert cm.can_undo() is True
        assert cm.can_redo() is False

    @pytest.mark.unit
    @pytest.mark.command
    def test_execute_clears_redo_stack(self, sample_srt_document):
        """Test that executing a new command clears redo stack."""
        cm = CommandManager()
        entry1 = SubtitleEntry(1, TimeCode(), TimeCode(), "Entry 1")
        entry2 = SubtitleEntry(2, TimeCode(), TimeCode(), "Entry 2")
        
        cm.execute(AddEntryCommand(sample_srt_document, entry1))
        cm.undo()
        assert cm.can_redo() is True
        
        cm.execute(AddEntryCommand(sample_srt_document, entry2))
        assert cm.can_redo() is False

    @pytest.mark.unit
    @pytest.mark.command
    def test_max_history_limit(self, sample_srt_document):
        """Test that history is limited to max_history."""
        cm = CommandManager(max_history=3)
        
        for i in range(5):
            entry = SubtitleEntry(i, TimeCode(), TimeCode(), f"Entry {i}")
            cm.execute(AddEntryCommand(sample_srt_document, entry))
        
        # Should only be able to undo 3 times
        undo_count = 0
        while cm.can_undo():
            cm.undo()
            undo_count += 1
        
        assert undo_count == 3

    @pytest.mark.unit
    @pytest.mark.command
    def test_clear_history(self, sample_srt_document, sample_entry):
        """Test clearing command history."""
        cm = CommandManager()
        cm.execute(AddEntryCommand(sample_srt_document, sample_entry))
        cm.undo()
        
        cm.clear()
        
        assert cm.can_undo() is False
        assert cm.can_redo() is False

    @pytest.mark.unit
    @pytest.mark.command
    def test_get_undo_description(self, sample_srt_document, sample_entry):
        """Test getting undo command description."""
        cm = CommandManager()
        cm.execute(AddEntryCommand(sample_srt_document, sample_entry))
        
        description = cm.get_undo_description()
        assert "Add subtitle" in description

    @pytest.mark.unit
    @pytest.mark.command
    def test_get_redo_description(self, sample_srt_document, sample_entry):
        """Test getting redo command description."""
        cm = CommandManager()
        cm.execute(AddEntryCommand(sample_srt_document, sample_entry))
        cm.undo()
        
        description = cm.get_redo_description()
        assert "Add subtitle" in description


class TestAddEntryCommand:
    """Tests for AddEntryCommand."""

    @pytest.mark.unit
    @pytest.mark.command
    def test_add_entry_at_end(self, sample_srt_document):
        """Test adding entry at end of document."""
        entry = SubtitleEntry(99, TimeCode(0, 0, 10, 0), TimeCode(0, 0, 11, 0), "New entry")
        cmd = AddEntryCommand(sample_srt_document, entry)
        
        initial_count = len(sample_srt_document.entries)
        cmd.execute()
        
        assert len(sample_srt_document.entries) == initial_count + 1
        assert sample_srt_document.entries[-1].text == "New entry"

    @pytest.mark.unit
    @pytest.mark.command
    def test_add_entry_at_position(self, sample_srt_document):
        """Test adding entry at specific position."""
        entry = SubtitleEntry(99, TimeCode(), TimeCode(), "Inserted entry")
        cmd = AddEntryCommand(sample_srt_document, entry, position=1)
        
        cmd.execute()
        
        assert sample_srt_document.entries[1].text == "Inserted entry"

    @pytest.mark.unit
    @pytest.mark.command
    def test_add_entry_undo(self, sample_srt_document):
        """Test undoing add entry."""
        entry = SubtitleEntry(99, TimeCode(), TimeCode(), "New entry")
        cmd = AddEntryCommand(sample_srt_document, entry)
        
        initial_count = len(sample_srt_document.entries)
        cmd.execute()
        cmd.undo()
        
        assert len(sample_srt_document.entries) == initial_count

    @pytest.mark.unit
    @pytest.mark.command
    def test_add_entry_reindex(self, sample_srt_document):
        """Test that adding entry triggers reindexing."""
        entry = SubtitleEntry(99, TimeCode(), TimeCode(), "New entry")
        cmd = AddEntryCommand(sample_srt_document, entry)
        
        cmd.execute()
        
        # Check all entries are properly indexed
        for i, e in enumerate(sample_srt_document.entries, start=1):
            assert e.index == i


class TestRemoveEntryCommand:
    """Tests for RemoveEntryCommand."""

    @pytest.mark.unit
    @pytest.mark.command
    def test_remove_entry(self, sample_srt_document):
        """Test removing an entry."""
        cmd = RemoveEntryCommand(sample_srt_document, 1)
        
        initial_count = len(sample_srt_document.entries)
        removed_text = sample_srt_document.entries[1].text
        cmd.execute()
        
        assert len(sample_srt_document.entries) == initial_count - 1
        assert all(e.text != removed_text for e in sample_srt_document.entries)

    @pytest.mark.unit
    @pytest.mark.command
    def test_remove_entry_undo(self, sample_srt_document):
        """Test undoing remove entry."""
        cmd = RemoveEntryCommand(sample_srt_document, 1)
        
        initial_count = len(sample_srt_document.entries)
        removed_text = sample_srt_document.entries[1].text
        cmd.execute()
        cmd.undo()
        
        assert len(sample_srt_document.entries) == initial_count
        assert sample_srt_document.entries[1].text == removed_text

    @pytest.mark.unit
    @pytest.mark.command
    def test_remove_entry_invalid_position(self, sample_srt_document):
        """Test removing entry at invalid position."""
        cmd = RemoveEntryCommand(sample_srt_document, 999)
        
        initial_count = len(sample_srt_document.entries)
        cmd.execute()
        
        assert len(sample_srt_document.entries) == initial_count


class TestEditTextCommand:
    """Tests for EditTextCommand."""

    @pytest.mark.unit
    @pytest.mark.command
    def test_edit_text(self, sample_srt_document):
        """Test editing subtitle text."""
        cmd = EditTextCommand(sample_srt_document, 0, "Modified text")
        
        cmd.execute()
        
        assert sample_srt_document.entries[0].text == "Modified text"

    @pytest.mark.unit
    @pytest.mark.command
    def test_edit_text_undo(self, sample_srt_document):
        """Test undoing text edit."""
        original_text = sample_srt_document.entries[0].text
        cmd = EditTextCommand(sample_srt_document, 0, "Modified text")
        
        cmd.execute()
        cmd.undo()
        
        assert sample_srt_document.entries[0].text == original_text

    @pytest.mark.unit
    @pytest.mark.command
    def test_edit_text_marks_modified(self, sample_srt_document):
        """Test that editing text marks document as modified."""
        sample_srt_document.modified = False
        cmd = EditTextCommand(sample_srt_document, 0, "Modified text")
        
        cmd.execute()
        
        assert sample_srt_document.modified is True


class TestEditTimingCommand:
    """Tests for EditTimingCommand."""

    @pytest.mark.unit
    @pytest.mark.command
    def test_edit_start_time(self, sample_srt_document):
        """Test editing start time."""
        new_start = TimeCode(0, 0, 5, 0)
        cmd = EditTimingCommand(sample_srt_document, 0, new_start=new_start)
        
        cmd.execute()
        
        assert sample_srt_document.entries[0].start_time.total_milliseconds == 5000

    @pytest.mark.unit
    @pytest.mark.command
    def test_edit_end_time(self, sample_srt_document):
        """Test editing end time."""
        new_end = TimeCode(0, 0, 10, 0)
        cmd = EditTimingCommand(sample_srt_document, 0, new_end=new_end)
        
        cmd.execute()
        
        assert sample_srt_document.entries[0].end_time.total_milliseconds == 10000

    @pytest.mark.unit
    @pytest.mark.command
    def test_edit_both_times(self, sample_srt_document):
        """Test editing both start and end times."""
        new_start = TimeCode(0, 0, 5, 0)
        new_end = TimeCode(0, 0, 10, 0)
        cmd = EditTimingCommand(sample_srt_document, 0, new_start=new_start, new_end=new_end)
        
        cmd.execute()
        
        assert sample_srt_document.entries[0].start_time.total_milliseconds == 5000
        assert sample_srt_document.entries[0].end_time.total_milliseconds == 10000

    @pytest.mark.unit
    @pytest.mark.command
    def test_edit_timing_undo(self, sample_srt_document):
        """Test undoing timing edit."""
        original_start = sample_srt_document.entries[0].start_time.total_milliseconds
        new_start = TimeCode(0, 0, 5, 0)
        cmd = EditTimingCommand(sample_srt_document, 0, new_start=new_start)
        
        cmd.execute()
        cmd.undo()
        
        assert sample_srt_document.entries[0].start_time.total_milliseconds == original_start


class TestDuplicateEntryCommand:
    """Tests for DuplicateEntryCommand."""

    @pytest.mark.unit
    @pytest.mark.command
    def test_duplicate_entry(self, sample_srt_document):
        """Test duplicating an entry."""
        cmd = DuplicateEntryCommand(sample_srt_document, 0)
        
        initial_count = len(sample_srt_document.entries)
        original_text = sample_srt_document.entries[0].text
        cmd.execute()
        
        assert len(sample_srt_document.entries) == initial_count + 1
        assert sample_srt_document.entries[1].text == original_text

    @pytest.mark.unit
    @pytest.mark.command
    def test_duplicate_entry_timing(self, sample_srt_document):
        """Test that duplicated entry has adjusted timing."""
        original_end = sample_srt_document.entries[0].end_time.total_milliseconds
        cmd = DuplicateEntryCommand(sample_srt_document, 0)
        
        cmd.execute()
        
        # Duplicate should start after original ends
        duplicate_start = sample_srt_document.entries[1].start_time.total_milliseconds
        assert duplicate_start > original_end

    @pytest.mark.unit
    @pytest.mark.command
    def test_duplicate_entry_undo(self, sample_srt_document):
        """Test undoing duplicate entry."""
        cmd = DuplicateEntryCommand(sample_srt_document, 0)
        
        initial_count = len(sample_srt_document.entries)
        cmd.execute()
        cmd.undo()
        
        assert len(sample_srt_document.entries) == initial_count


class TestMoveEntryCommand:
    """Tests for MoveEntryCommand."""

    @pytest.mark.unit
    @pytest.mark.command
    def test_move_entry(self, sample_srt_document):
        """Test moving an entry."""
        text_at_0 = sample_srt_document.entries[0].text
        cmd = MoveEntryCommand(sample_srt_document, 0, 2)
        
        cmd.execute()
        
        assert sample_srt_document.entries[2].text == text_at_0

    @pytest.mark.unit
    @pytest.mark.command
    def test_move_entry_undo(self, sample_srt_document):
        """Test undoing move entry."""
        text_at_0 = sample_srt_document.entries[0].text
        cmd = MoveEntryCommand(sample_srt_document, 0, 2)
        
        cmd.execute()
        cmd.undo()
        
        assert sample_srt_document.entries[0].text == text_at_0


class TestTimeShiftCommand:
    """Tests for TimeShiftCommand."""

    @pytest.mark.unit
    @pytest.mark.command
    def test_time_shift_all_entries(self, sample_srt_document):
        """Test shifting time for all entries."""
        original_times = [(e.start_time.total_milliseconds, e.end_time.total_milliseconds) 
                          for e in sample_srt_document.entries]
        cmd = TimeShiftCommand(sample_srt_document, 1000)
        
        cmd.execute()
        
        for i, entry in enumerate(sample_srt_document.entries):
            assert entry.start_time.total_milliseconds == original_times[i][0] + 1000
            assert entry.end_time.total_milliseconds == original_times[i][1] + 1000

    @pytest.mark.unit
    @pytest.mark.command
    def test_time_shift_selected_entries(self, sample_srt_document):
        """Test shifting time for selected entries only."""
        original_start = sample_srt_document.entries[1].start_time.total_milliseconds
        cmd = TimeShiftCommand(sample_srt_document, 1000, positions=[1])
        
        cmd.execute()
        
        assert sample_srt_document.entries[1].start_time.total_milliseconds == original_start + 1000

    @pytest.mark.unit
    @pytest.mark.command
    def test_time_shift_negative(self, sample_srt_document):
        """Test shifting time backward."""
        original_start = sample_srt_document.entries[0].start_time.total_milliseconds
        cmd = TimeShiftCommand(sample_srt_document, -100)
        
        cmd.execute()
        
        expected = max(0, original_start - 100)
        assert sample_srt_document.entries[0].start_time.total_milliseconds == expected

    @pytest.mark.unit
    @pytest.mark.command
    def test_time_shift_undo(self, sample_srt_document):
        """Test undoing time shift."""
        original_times = [(e.start_time.total_milliseconds, e.end_time.total_milliseconds) 
                          for e in sample_srt_document.entries]
        cmd = TimeShiftCommand(sample_srt_document, 1000)
        
        cmd.execute()
        cmd.undo()
        
        for i, entry in enumerate(sample_srt_document.entries):
            assert entry.start_time.total_milliseconds == original_times[i][0]
            assert entry.end_time.total_milliseconds == original_times[i][1]


class TestBatchTimingCommand:
    """Tests for BatchTimingCommand."""

    @pytest.mark.unit
    @pytest.mark.command
    def test_batch_timing_adjustment(self, sample_srt_document):
        """Test batch timing adjustments."""
        adjustments = [
            (0, TimeCode(0, 0, 1, 0), TimeCode(0, 0, 2, 0)),
            (1, TimeCode(0, 0, 3, 0), TimeCode(0, 0, 4, 0)),
        ]
        cmd = BatchTimingCommand(sample_srt_document, adjustments)
        
        cmd.execute()
        
        assert sample_srt_document.entries[0].start_time.total_milliseconds == 1000
        assert sample_srt_document.entries[1].start_time.total_milliseconds == 3000

    @pytest.mark.unit
    @pytest.mark.command
    def test_batch_timing_undo(self, sample_srt_document):
        """Test undoing batch timing adjustments."""
        original_times = [(e.start_time.total_milliseconds, e.end_time.total_milliseconds) 
                          for e in sample_srt_document.entries[:2]]
        adjustments = [
            (0, TimeCode(0, 0, 1, 0), TimeCode(0, 0, 2, 0)),
            (1, TimeCode(0, 0, 3, 0), TimeCode(0, 0, 4, 0)),
        ]
        cmd = BatchTimingCommand(sample_srt_document, adjustments)
        
        cmd.execute()
        cmd.undo()
        
        assert sample_srt_document.entries[0].start_time.total_milliseconds == original_times[0][0]
        assert sample_srt_document.entries[1].start_time.total_milliseconds == original_times[1][0]
