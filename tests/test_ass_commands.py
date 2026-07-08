"""Unit tests for ASS/SSA command operations."""

import pytest
from subtitle_editor.commands import ReplaceASSHeaderCommand
from subtitle_editor.models import ASSStyle


class TestReplaceASSHeaderCommand:
    """Tests for ReplaceASSHeaderCommand."""

    @pytest.mark.unit
    @pytest.mark.command
    def test_replace_metadata(self, sample_ass_document):
        """Test replacing metadata."""
        new_metadata = {"Title": "New Title", "Author": "New Author"}
        cmd = ReplaceASSHeaderCommand(
            sample_ass_document,
            metadata=new_metadata
        )

        cmd.execute()

        assert sample_ass_document.metadata["Title"] == "New Title"
        assert sample_ass_document.metadata["Author"] == "New Author"

    @pytest.mark.unit
    @pytest.mark.command
    def test_replace_styles(self, sample_ass_document):
        """Test replacing styles."""
        new_styles = [
            ASSStyle(name="Style1", fontsize=18),
            ASSStyle(name="Style2", fontsize=24),
        ]
        cmd = ReplaceASSHeaderCommand(
            sample_ass_document,
            styles=new_styles
        )

        cmd.execute()

        # Command ensures at least one style exists and may add fallback
        assert len(sample_ass_document.styles) >= 2
        assert sample_ass_document.get_style_by_name("Style1") is not None

    @pytest.mark.unit
    @pytest.mark.command
    def test_replace_aegisub_garbage(self, sample_ass_document):
        """Test replacing Aegisub project garbage."""
        new_garbage = {"Audio File": "audio.wav", "Video File": "video.mp4"}
        cmd = ReplaceASSHeaderCommand(
            sample_ass_document,
            aegisub_project_garbage=new_garbage
        )

        cmd.execute()

        assert sample_ass_document.aegisub_project_garbage["Audio File"] == "audio.wav"

    @pytest.mark.unit
    @pytest.mark.command
    def test_replace_header_undo(self, sample_ass_document):
        """Test undoing header replacement."""
        original_metadata = dict(sample_ass_document.metadata)
        original_styles = [s.name for s in sample_ass_document.styles]

        new_metadata = {"Title": "New Title"}
        new_styles = [ASSStyle(name="NewStyle")]
        cmd = ReplaceASSHeaderCommand(
            sample_ass_document,
            metadata=new_metadata,
            styles=new_styles
        )

        cmd.execute()
        cmd.undo()

        assert sample_ass_document.metadata == original_metadata
        assert [s.name for s in sample_ass_document.styles] == original_styles

    @pytest.mark.unit
    @pytest.mark.command
    def test_replace_header_keeps_one_style(self, sample_ass_document):
        """Test that at least one style is always present."""
        cmd = ReplaceASSHeaderCommand(
            sample_ass_document,
            styles=[]
        )

        cmd.execute()

        assert len(sample_ass_document.styles) >= 1

    @pytest.mark.unit
    @pytest.mark.command
    def test_replace_header_normalizes_entry_styles(self, sample_ass_document):
        """Test that entry styles are normalized to fallback if removed."""
        # Remove all styles and add only one
        new_styles = [ASSStyle(name="OnlyStyle")]
        cmd = ReplaceASSHeaderCommand(
            sample_ass_document,
            styles=new_styles,
            fallback_style="OnlyStyle"
        )

        cmd.execute()

        # All entries should use the fallback
        for entry in sample_ass_document.entries:
            assert entry.style == "OnlyStyle"
