"""Unit tests for style command operations."""

import pytest
from gsub.commands import EditStyleCommand, BulkEditStyleCommand


class TestEditStyleCommand:
    """Tests for EditStyleCommand."""

    @pytest.mark.unit
    @pytest.mark.command
    def test_edit_style(self, sample_ass_document):
        """Test changing entry style."""
        cmd = EditStyleCommand(sample_ass_document, 0, "Title")
        
        cmd.execute()
        
        assert sample_ass_document.entries[0].style == "Title"

    @pytest.mark.unit
    @pytest.mark.command
    def test_edit_style_to_none(self, sample_ass_document):
        """Test setting style to None."""
        cmd = EditStyleCommand(sample_ass_document, 0, None)
        
        cmd.execute()
        
        assert sample_ass_document.entries[0].style is None

    @pytest.mark.unit
    @pytest.mark.command
    def test_edit_style_undo(self, sample_ass_document):
        """Test undoing style edit."""
        original_style = sample_ass_document.entries[0].style
        cmd = EditStyleCommand(sample_ass_document, 0, "Title")
        
        cmd.execute()
        cmd.undo()
        
        assert sample_ass_document.entries[0].style == original_style

    @pytest.mark.unit
    @pytest.mark.command
    def test_edit_style_marks_modified(self, sample_ass_document):
        """Test that editing style marks document as modified."""
        sample_ass_document.modified = False
        cmd = EditStyleCommand(sample_ass_document, 0, "Title")
        
        cmd.execute()
        
        assert sample_ass_document.modified is True

    @pytest.mark.unit
    @pytest.mark.command
    def test_edit_style_invalid_position(self, sample_ass_document):
        """Test editing style at invalid position."""
        cmd = EditStyleCommand(sample_ass_document, 999, "Title")
        
        # Should not raise error
        cmd.execute()


class TestBulkEditStyleCommand:
    """Tests for BulkEditStyleCommand."""

    @pytest.mark.unit
    @pytest.mark.command
    def test_bulk_edit_style(self, sample_ass_document):
        """Test applying style to multiple entries."""
        cmd = BulkEditStyleCommand(sample_ass_document, [0, 1], "Title")
        
        cmd.execute()
        
        assert sample_ass_document.entries[0].style == "Title"
        assert sample_ass_document.entries[1].style == "Title"

    @pytest.mark.unit
    @pytest.mark.command
    def test_bulk_edit_style_single_entry(self, sample_ass_document):
        """Test bulk edit with single entry."""
        cmd = BulkEditStyleCommand(sample_ass_document, [0], "Title")
        
        cmd.execute()
        
        assert sample_ass_document.entries[0].style == "Title"

    @pytest.mark.unit
    @pytest.mark.command
    def test_bulk_edit_style_to_none(self, sample_ass_document):
        """Test bulk editing style to None."""
        cmd = BulkEditStyleCommand(sample_ass_document, [0, 1], None)
        
        cmd.execute()
        
        assert sample_ass_document.entries[0].style is None
        assert sample_ass_document.entries[1].style is None

    @pytest.mark.unit
    @pytest.mark.command
    def test_bulk_edit_style_undo(self, sample_ass_document):
        """Test undoing bulk style edit."""
        original_styles = [e.style for e in sample_ass_document.entries]
        cmd = BulkEditStyleCommand(sample_ass_document, [0, 1], "Title")
        
        cmd.execute()
        cmd.undo()
        
        for i, entry in enumerate(sample_ass_document.entries):
            assert entry.style == original_styles[i]

    @pytest.mark.unit
    @pytest.mark.command
    def test_bulk_edit_style_deduplicates_positions(self, sample_ass_document):
        """Test that duplicate positions are handled correctly."""
        cmd = BulkEditStyleCommand(sample_ass_document, [0, 0, 1, 1], "Title")
        
        cmd.execute()
        
        # Should work without errors
        assert sample_ass_document.entries[0].style == "Title"
        assert sample_ass_document.entries[1].style == "Title"

    @pytest.mark.unit
    @pytest.mark.command
    def test_bulk_edit_style_invalid_positions(self, sample_ass_document):
        """Test bulk edit with some invalid positions."""
        cmd = BulkEditStyleCommand(sample_ass_document, [0, 999], "Title")
        
        cmd.execute()
        
        # Valid position should be updated
        assert sample_ass_document.entries[0].style == "Title"

    @pytest.mark.unit
    @pytest.mark.command
    def test_bulk_edit_style_marks_modified(self, sample_ass_document):
        """Test that bulk edit marks document as modified."""
        sample_ass_document.modified = False
        cmd = BulkEditStyleCommand(sample_ass_document, [0, 1], "Title")
        
        cmd.execute()
        
        assert sample_ass_document.modified is True

    @pytest.mark.unit
    @pytest.mark.command
    def test_bulk_edit_style_empty_positions(self, sample_ass_document):
        """Test bulk edit with empty position list."""
        sample_ass_document.modified = False
        cmd = BulkEditStyleCommand(sample_ass_document, [], "Title")
        
        cmd.execute()
        
        # Should not modify anything
        assert sample_ass_document.modified is False
