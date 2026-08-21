"""Unit tests for bulk style property command operations."""

import copy
import dataclasses

import pytest
from gsub.commands import BulkUpdateStylePropsCommand, CommandManager
from gsub.models import ASSStyle


def _snapshot(styles):
    """Deep-copy snapshot of a style list for exact field comparisons."""
    return [copy.deepcopy(style) for style in styles]


def _assert_unchanged(before, after):
    """Assert every dataclass field of every style is identical."""
    assert len(after) == len(before)
    for old, new in zip(before, after):
        for f in dataclasses.fields(ASSStyle):
            assert getattr(new, f.name) == getattr(old, f.name)


class TestBulkUpdateStylePropsCommand:
    """Tests for BulkUpdateStylePropsCommand."""

    @pytest.mark.unit
    @pytest.mark.command
    def test_applies_multiple_props_to_both_styles(self, sample_ass_document):
        """Test applying several props of mixed types to multiple styles."""
        props = {
            'fontname': 'Noto Sans',
            'fontsize': 42,
            'primary_color': '&H0000FF00',
            'bold': True,
            'scale_x': 120.5,
            'margin_l': 33,
        }
        cmd = BulkUpdateStylePropsCommand(sample_ass_document, ['Default', 'Title'], props)

        cmd.execute()

        for name in ('Default', 'Title'):
            style = sample_ass_document.get_style_by_name(name)
            assert style.fontname == 'Noto Sans'
            assert style.fontsize == 42
            assert style.primary_color == '&H0000FF00'
            assert style.bold is True
            assert style.scale_x == 120.5
            assert style.margin_l == 33

    @pytest.mark.unit
    @pytest.mark.command
    def test_undo_restores_every_field(self, sample_ass_document):
        """Test that undo restores every original field exactly."""
        before = _snapshot(sample_ass_document.styles)
        props = {
            'fontname': 'Comic Sans',
            'fontsize': 42,
            'primary_color': '&H0000FF00',
            'bold': True,
            'italic': True,
            'scale_x': 120.5,
            'alignment': 7,
            'margin_l': 33,
        }
        cmd = BulkUpdateStylePropsCommand(sample_ass_document, ['Default', 'Title'], props)

        cmd.execute()
        cmd.undo()

        _assert_unchanged(before, sample_ass_document.styles)

    @pytest.mark.unit
    @pytest.mark.command
    def test_unknown_style_names_noop(self, sample_ass_document):
        """Test that unknown style names change nothing and leave modified alone."""
        sample_ass_document.modified = False
        before = _snapshot(sample_ass_document.styles)
        cmd = BulkUpdateStylePropsCommand(
            sample_ass_document, ['Nope', 'Missing'], {'fontsize': 99, 'bold': True})

        cmd.execute()

        assert sample_ass_document.modified is False
        _assert_unchanged(before, sample_ass_document.styles)

    @pytest.mark.unit
    @pytest.mark.command
    def test_unknown_prop_keys_ignored(self, sample_ass_document):
        """Test that unknown keys are ignored while valid sibling keys apply."""
        cmd = BulkUpdateStylePropsCommand(
            sample_ass_document, ['Default'], {'bogus': 1, 'fontsize': 55})

        cmd.execute()

        style = sample_ass_document.get_style_by_name('Default')
        assert style.fontsize == 55
        assert not hasattr(style, 'bogus')

    @pytest.mark.unit
    @pytest.mark.command
    def test_only_unknown_prop_keys_changes_nothing(self, sample_ass_document):
        """Test that a props dict of only unknown keys is a full no-op."""
        sample_ass_document.modified = False
        before = _snapshot(sample_ass_document.styles)
        cmd = BulkUpdateStylePropsCommand(sample_ass_document, ['Default'], {'bogus': 1})

        cmd.execute()

        assert sample_ass_document.modified is False
        _assert_unchanged(before, sample_ass_document.styles)

    @pytest.mark.unit
    @pytest.mark.command
    def test_name_is_not_editable(self, sample_ass_document):
        """Test that the style name (identity field) cannot be batch-edited."""
        cmd = BulkUpdateStylePropsCommand(
            sample_ass_document, ['Default'], {'name': 'Hijacked', 'fontsize': 25})

        cmd.execute()

        assert sample_ass_document.get_style_by_name('Default') is not None
        assert sample_ass_document.get_style_by_name('Hijacked') is None
        assert sample_ass_document.get_style_by_name('Default').fontsize == 25

    @pytest.mark.unit
    @pytest.mark.command
    def test_empty_style_names_noop(self, sample_ass_document):
        """Test that an empty style name list changes nothing."""
        sample_ass_document.modified = False
        before = _snapshot(sample_ass_document.styles)
        cmd = BulkUpdateStylePropsCommand(sample_ass_document, [], {'fontsize': 99})

        cmd.execute()

        assert sample_ass_document.modified is False
        _assert_unchanged(before, sample_ass_document.styles)

    @pytest.mark.unit
    @pytest.mark.command
    def test_empty_props_noop(self, sample_ass_document):
        """Test that an empty props dict changes nothing."""
        sample_ass_document.modified = False
        before = _snapshot(sample_ass_document.styles)
        cmd = BulkUpdateStylePropsCommand(sample_ass_document, ['Default', 'Title'], {})

        cmd.execute()
        cmd.undo()

        assert sample_ass_document.modified is False
        _assert_unchanged(before, sample_ass_document.styles)

    @pytest.mark.unit
    @pytest.mark.command
    def test_deduplicates_style_names(self, sample_ass_document):
        """Test that duplicate style names are harmless."""
        cmd = BulkUpdateStylePropsCommand(
            sample_ass_document, ['Default', 'Default', 'Title'], {'fontsize': 36})

        assert cmd.style_names == ['Default', 'Title']
        cmd.execute()

        assert sample_ass_document.get_style_by_name('Default').fontsize == 36
        assert sample_ass_document.get_style_by_name('Title').fontsize == 36

    @pytest.mark.unit
    @pytest.mark.command
    def test_marks_modified(self, sample_ass_document):
        """Test that applying props marks the document as modified."""
        sample_ass_document.modified = False
        cmd = BulkUpdateStylePropsCommand(sample_ass_document, ['Default'], {'fontsize': 30})

        cmd.execute()

        assert sample_ass_document.modified is True

    @pytest.mark.unit
    @pytest.mark.command
    def test_description_plural(self, sample_ass_document):
        """Test description text for multiple styles."""
        cmd = BulkUpdateStylePropsCommand(
            sample_ass_document, ['Default', 'Title'], {'fontsize': 40})

        cmd.execute()

        assert cmd.description() == "Batch update style properties on 2 styles"

    @pytest.mark.unit
    @pytest.mark.command
    def test_description_singular(self, sample_ass_document):
        """Test description text for a single style."""
        cmd = BulkUpdateStylePropsCommand(sample_ass_document, ['Title'], {'fontsize': 40})

        cmd.execute()

        assert cmd.description() == "Batch update style properties on 1 style"

    @pytest.mark.unit
    @pytest.mark.command
    def test_command_manager_undo_redo(self, sample_ass_document):
        """Test execute -> undo -> redo through the CommandManager."""
        manager = CommandManager()
        props = {'fontsize': 48, 'bold': False, 'primary_color': '&H000000FF'}
        manager.execute(
            BulkUpdateStylePropsCommand(sample_ass_document, ['Default', 'Title'], props))

        for name in ('Default', 'Title'):
            style = sample_ass_document.get_style_by_name(name)
            assert style.fontsize == 48
            assert style.bold is False
            assert style.primary_color == '&H000000FF'

        assert manager.undo() is True
        assert sample_ass_document.get_style_by_name('Default').fontsize == 20
        assert sample_ass_document.get_style_by_name('Default').bold is False
        assert sample_ass_document.get_style_by_name('Title').fontsize == 28
        assert sample_ass_document.get_style_by_name('Title').bold is True

        assert manager.redo() is True
        for name in ('Default', 'Title'):
            style = sample_ass_document.get_style_by_name(name)
            assert style.fontsize == 48
            assert style.bold is False
            assert style.primary_color == '&H000000FF'
