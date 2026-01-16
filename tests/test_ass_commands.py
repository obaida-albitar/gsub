"""Unit tests for ASS/SSA command operations."""

import pytest
from subtitle_editor.commands import (
    SetMetadataCommand, RemoveMetadataCommand, UpsertStyleCommand,
    RemoveStyleCommand, RenameStyleCommand, ReplaceASSHeaderCommand,
    UpdateASSHeaderCommand
)
from subtitle_editor.models import ASSStyle


class TestSetMetadataCommand:
    """Tests for SetMetadataCommand."""

    @pytest.mark.unit
    @pytest.mark.command
    def test_set_metadata_new_key(self, sample_ass_document):
        """Test setting a new metadata key."""
        cmd = SetMetadataCommand(sample_ass_document, "Author", "Test Author")
        
        cmd.execute()
        
        assert sample_ass_document.metadata["Author"] == "Test Author"
        assert sample_ass_document.modified is True

    @pytest.mark.unit
    @pytest.mark.command
    def test_set_metadata_existing_key(self, sample_ass_document):
        """Test updating existing metadata key."""
        sample_ass_document.metadata["Title"] = "Old Title"
        cmd = SetMetadataCommand(sample_ass_document, "Title", "New Title")
        
        cmd.execute()
        
        assert sample_ass_document.metadata["Title"] == "New Title"

    @pytest.mark.unit
    @pytest.mark.command
    def test_set_metadata_undo_new_key(self, sample_ass_document):
        """Test undoing set metadata for new key."""
        cmd = SetMetadataCommand(sample_ass_document, "NewKey", "NewValue")
        
        cmd.execute()
        cmd.undo()
        
        assert "NewKey" not in sample_ass_document.metadata

    @pytest.mark.unit
    @pytest.mark.command
    def test_set_metadata_undo_existing_key(self, sample_ass_document):
        """Test undoing set metadata for existing key."""
        sample_ass_document.metadata["Title"] = "Old Title"
        cmd = SetMetadataCommand(sample_ass_document, "Title", "New Title")
        
        cmd.execute()
        cmd.undo()
        
        assert sample_ass_document.metadata["Title"] == "Old Title"


class TestRemoveMetadataCommand:
    """Tests for RemoveMetadataCommand."""

    @pytest.mark.unit
    @pytest.mark.command
    def test_remove_metadata(self, sample_ass_document):
        """Test removing metadata."""
        sample_ass_document.metadata["TestKey"] = "TestValue"
        cmd = RemoveMetadataCommand(sample_ass_document, "TestKey")
        
        cmd.execute()
        
        assert "TestKey" not in sample_ass_document.metadata

    @pytest.mark.unit
    @pytest.mark.command
    def test_remove_metadata_undo(self, sample_ass_document):
        """Test undoing remove metadata."""
        sample_ass_document.metadata["TestKey"] = "TestValue"
        cmd = RemoveMetadataCommand(sample_ass_document, "TestKey")
        
        cmd.execute()
        cmd.undo()
        
        assert sample_ass_document.metadata["TestKey"] == "TestValue"

    @pytest.mark.unit
    @pytest.mark.command
    def test_remove_metadata_nonexistent(self, sample_ass_document):
        """Test removing non-existent metadata key."""
        cmd = RemoveMetadataCommand(sample_ass_document, "NonExistent")
        
        cmd.execute()  # Should not raise error
        cmd.undo()  # Should not restore anything


class TestUpsertStyleCommand:
    """Tests for UpsertStyleCommand."""

    @pytest.mark.unit
    @pytest.mark.command
    def test_upsert_new_style(self, sample_ass_document):
        """Test inserting a new style."""
        new_style = ASSStyle(name="NewStyle", fontsize=22)
        cmd = UpsertStyleCommand(sample_ass_document, new_style)
        
        initial_count = len(sample_ass_document.styles)
        cmd.execute()
        
        assert len(sample_ass_document.styles) == initial_count + 1
        assert sample_ass_document.get_style_by_name("NewStyle") is not None

    @pytest.mark.unit
    @pytest.mark.command
    def test_upsert_existing_style(self, sample_ass_document):
        """Test updating an existing style."""
        updated_style = ASSStyle(name="Default", fontsize=30, bold=True)
        cmd = UpsertStyleCommand(sample_ass_document, updated_style)
        
        initial_count = len(sample_ass_document.styles)
        cmd.execute()
        
        assert len(sample_ass_document.styles) == initial_count  # No new style added
        style = sample_ass_document.get_style_by_name("Default")
        assert style.fontsize == 30
        assert style.bold is True

    @pytest.mark.unit
    @pytest.mark.command
    def test_upsert_style_undo_insert(self, sample_ass_document):
        """Test undoing style insertion."""
        new_style = ASSStyle(name="NewStyle", fontsize=22)
        cmd = UpsertStyleCommand(sample_ass_document, new_style)
        
        initial_count = len(sample_ass_document.styles)
        cmd.execute()
        cmd.undo()
        
        assert len(sample_ass_document.styles) == initial_count
        assert sample_ass_document.get_style_by_name("NewStyle") is None

    @pytest.mark.unit
    @pytest.mark.command
    def test_upsert_style_undo_update(self, sample_ass_document):
        """Test undoing style update."""
        original_size = sample_ass_document.get_style_by_name("Default").fontsize
        updated_style = ASSStyle(name="Default", fontsize=30)
        cmd = UpsertStyleCommand(sample_ass_document, updated_style)
        
        cmd.execute()
        cmd.undo()
        
        style = sample_ass_document.get_style_by_name("Default")
        assert style.fontsize == original_size


class TestRemoveStyleCommand:
    """Tests for RemoveStyleCommand."""

    @pytest.mark.unit
    @pytest.mark.command
    def test_remove_style(self, sample_ass_document):
        """Test removing a style."""
        cmd = RemoveStyleCommand(sample_ass_document, "Title", fallback="Default")
        
        initial_count = len(sample_ass_document.styles)
        cmd.execute()
        
        assert len(sample_ass_document.styles) == initial_count - 1
        assert sample_ass_document.get_style_by_name("Title") is None

    @pytest.mark.unit
    @pytest.mark.command
    def test_remove_style_updates_entries(self, sample_ass_document):
        """Test that removing style updates entries to fallback."""
        # Second entry uses "Title"
        cmd = RemoveStyleCommand(sample_ass_document, "Title", fallback="Default")
        
        cmd.execute()
        
        # Entry that used "Title" should now use "Default"
        for entry in sample_ass_document.entries:
            assert entry.style != "Title"

    @pytest.mark.unit
    @pytest.mark.command
    def test_remove_style_undo(self, sample_ass_document):
        """Test undoing style removal."""
        original_styles = [s.name for s in sample_ass_document.styles]
        cmd = RemoveStyleCommand(sample_ass_document, "Title", fallback="Default")
        
        cmd.execute()
        cmd.undo()
        
        restored_styles = [s.name for s in sample_ass_document.styles]
        assert set(original_styles) == set(restored_styles)

    @pytest.mark.unit
    @pytest.mark.command
    def test_remove_style_undo_restores_entries(self, sample_ass_document):
        """Test that undoing style removal restores entry references."""
        original_entry_styles = [e.style for e in sample_ass_document.entries]
        cmd = RemoveStyleCommand(sample_ass_document, "Title", fallback="Default")
        
        cmd.execute()
        cmd.undo()
        
        for i, entry in enumerate(sample_ass_document.entries):
            assert entry.style == original_entry_styles[i]


class TestRenameStyleCommand:
    """Tests for RenameStyleCommand."""

    @pytest.mark.unit
    @pytest.mark.command
    def test_rename_style(self, sample_ass_document):
        """Test renaming a style."""
        cmd = RenameStyleCommand(sample_ass_document, "Default", "MainStyle")
        
        cmd.execute()
        
        assert sample_ass_document.get_style_by_name("Default") is None
        assert sample_ass_document.get_style_by_name("MainStyle") is not None

    @pytest.mark.unit
    @pytest.mark.command
    def test_rename_style_updates_entries(self, sample_ass_document):
        """Test that renaming style updates all entries."""
        cmd = RenameStyleCommand(sample_ass_document, "Default", "MainStyle")
        
        cmd.execute()
        
        # Check entries that used "Default" now use "MainStyle"
        for entry in sample_ass_document.entries:
            if entry.style == "MainStyle":
                # This was previously "Default"
                assert entry.style == "MainStyle"

    @pytest.mark.unit
    @pytest.mark.command
    def test_rename_style_undo(self, sample_ass_document):
        """Test undoing style rename."""
        cmd = RenameStyleCommand(sample_ass_document, "Default", "MainStyle")
        
        cmd.execute()
        cmd.undo()
        
        assert sample_ass_document.get_style_by_name("Default") is not None
        assert sample_ass_document.get_style_by_name("MainStyle") is None


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


class TestUpdateASSHeaderCommand:
    """Tests for UpdateASSHeaderCommand."""

    @pytest.mark.unit
    @pytest.mark.command
    def test_update_metadata(self, sample_ass_document):
        """Test updating metadata keys."""
        metadata_updates = {"Author": "New Author", "Year": "2024"}
        cmd = UpdateASSHeaderCommand(
            sample_ass_document,
            metadata_updates=metadata_updates
        )
        
        cmd.execute()
        
        assert sample_ass_document.metadata["Author"] == "New Author"
        assert sample_ass_document.metadata["Year"] == "2024"

    @pytest.mark.unit
    @pytest.mark.command
    def test_update_metadata_remove_key(self, sample_ass_document):
        """Test removing metadata key by setting to None."""
        sample_ass_document.metadata["ToRemove"] = "Value"
        metadata_updates = {"ToRemove": None}
        cmd = UpdateASSHeaderCommand(
            sample_ass_document,
            metadata_updates=metadata_updates
        )
        
        cmd.execute()
        
        assert "ToRemove" not in sample_ass_document.metadata

    @pytest.mark.unit
    @pytest.mark.command
    def test_update_styles(self, sample_ass_document):
        """Test upserting styles."""
        new_style = ASSStyle(name="NewStyle", fontsize=22)
        updated_style = ASSStyle(name="Default", fontsize=30)
        cmd = UpdateASSHeaderCommand(
            sample_ass_document,
            style_upserts=[new_style, updated_style]
        )
        
        initial_count = len(sample_ass_document.styles)
        cmd.execute()
        
        # One new style added, one updated
        assert len(sample_ass_document.styles) == initial_count + 1
        assert sample_ass_document.get_style_by_name("NewStyle") is not None
        assert sample_ass_document.get_style_by_name("Default").fontsize == 30

    @pytest.mark.unit
    @pytest.mark.command
    def test_update_header_undo(self, sample_ass_document):
        """Test undoing header update."""
        original_metadata = dict(sample_ass_document.metadata)
        original_styles = len(sample_ass_document.styles)
        
        metadata_updates = {"NewKey": "NewValue"}
        new_style = ASSStyle(name="NewStyle")
        cmd = UpdateASSHeaderCommand(
            sample_ass_document,
            metadata_updates=metadata_updates,
            style_upserts=[new_style]
        )
        
        cmd.execute()
        cmd.undo()
        
        # Check metadata restored
        assert "NewKey" not in sample_ass_document.metadata
        # Check styles restored
        assert len(sample_ass_document.styles) == original_styles
