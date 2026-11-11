"""Snapshot and transaction guarantees for multi-file batch edits."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from gsub.commands.batch_commands import BatchOperationsCommand
from gsub.commands.command import CommandManager
from gsub.models import ASSStyle, SubtitleDocument, SubtitleEntry, SubtitleFormat, TimeCode


def item(start=500, end=2000, fmt=SubtitleFormat.SRT):
    document = SubtitleDocument(
        format=fmt,
        entries=[SubtitleEntry(1, TimeCode.from_milliseconds(start),
                               TimeCode.from_milliseconds(end), "Hello", style="Default")],
        styles=[ASSStyle(name="Default", fontsize=20)] if fmt != SubtitleFormat.SRT else [],
        metadata={"PlayResX": "640", "PlayResY": "480"} if fmt != SubtitleFormat.SRT else {},
    )
    return SimpleNamespace(document=document, modified=False)


def test_batch_shift_undo_restores_clamped_times_across_files():
    items = [item(), item(100, 700)]
    original = [deepcopy(it.document) for it in items]
    references = [it.document for it in items]
    manager = CommandManager()
    command = BatchOperationsCommand(items, offset_ms=-1000)
    assert command.changed_count == 2
    # Preparing a command must not change any live document.
    assert [it.document for it in items] == original
    manager.execute(command)
    shifted = [deepcopy(it.document) for it in items]
    assert items[1].document.entries[0].end_time.total_milliseconds == 0
    assert all(it.modified for it in items)
    manager.undo()
    assert [it.document for it in items] == original
    assert all(it.document is ref for it, ref in zip(items, references))
    assert not any(it.modified for it in items)
    manager.redo()
    assert [it.document for it in items] == shifted


def test_batch_combines_style_resolution_and_timing_in_one_step():
    items = [item(fmt=SubtitleFormat.ASS), item(fmt=SubtitleFormat.ASS)]
    original = [deepcopy(it.document) for it in items]
    command = BatchOperationsCommand(
        items, offset_ms=1000, resolution=(1920, 1080),
        target_styles=["Default"], style_properties={"fontsize": 42, "bold": True})
    manager = CommandManager()
    manager.execute(command)
    for it in items:
        assert it.document.entries[0].start_time.total_milliseconds == 1500
        assert it.document.styles[0].fontsize == 42
        assert it.document.styles[0].bold is True
        assert it.document.metadata["PlayResX"] == "1920"
    manager.undo()
    assert [it.document for it in items] == original
    assert not manager.can_undo()


def test_invalid_batch_preparation_leaves_all_files_untouched():
    items = [item(), item()]
    original = deepcopy(items)
    with pytest.raises(TypeError):
        BatchOperationsCommand(items, offset_ms="invalid")
    assert items == original


@pytest.mark.parametrize("kwargs", [{}, {"offset_ms": 0},
                                  {"resolution": (1920, 1080)},
                                  {"target_styles": ["missing"],
                                   "style_properties": {"fontsize": 30}}])
def test_no_op_batch_does_not_claim_changes(kwargs):
    command = BatchOperationsCommand([item()], **kwargs)
    assert not command.changed
    assert command.changed_count == 0


def test_batch_deduplicates_document_references_and_restores_dirty_state():
    it = item()
    it.document.modified = it.modified = True
    command = BatchOperationsCommand([it, it], offset_ms=100)
    assert command.changed_count == 1
    command.execute()
    assert it.document.entries[0].start_time.total_milliseconds == 600
    command.undo()
    assert it.document.entries[0].start_time.total_milliseconds == 500
    assert it.modified and it.document.modified


def test_redo_uses_prepared_values_after_operation_inputs_change():
    it = item(fmt=SubtitleFormat.ASS)
    props = {"fontsize": 35}
    command = BatchOperationsCommand([it], target_styles=["Default"], style_properties=props)
    command.execute()
    command.undo()
    props["fontsize"] = 99
    command.redo()
    assert it.document.styles[0].fontsize == 35


def test_single_document_time_shift_also_restores_clamped_times():
    from gsub.commands.subtitle_commands import TimeShiftCommand

    it = item(100, 700)
    manager = CommandManager()
    manager.execute(TimeShiftCommand(it.document, -1000))
    assert it.document.entries[0].end_time.total_milliseconds == 0
    manager.undo()
    assert it.document.entries[0].start_time.total_milliseconds == 100
    assert it.document.entries[0].end_time.total_milliseconds == 700
    manager.redo()
    assert it.document.entries[0].end_time.total_milliseconds == 0
