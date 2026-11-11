"""GTK behavior for search previews, scopes, replacement, and navigation."""

import pytest

gi = pytest.importorskip("gi")
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gtk

Gtk.init()
Adw.init()
if Gdk.Display.get_default() is None:
    pytest.skip("no display available for GTK widget tests", allow_module_level=True)

from gsub.commands import CommandManager
from gsub.models import SubtitleDocument, SubtitleEntry, SubtitleFormat, TimeCode
from gsub.resources import register_resources

register_resources()

from gsub.widgets.find_replace_dialog import FindReplaceDialog


def make_document(*texts, fmt=SubtitleFormat.SRT):
    return SubtitleDocument(format=fmt, entries=[
        SubtitleEntry(i + 1, TimeCode.from_milliseconds(i * 2000),
                      TimeCode.from_milliseconds(i * 2000 + 1500), text)
        for i, text in enumerate(texts)
    ])


@pytest.fixture
def editor():
    parent = Adw.Window()
    doc = make_document("Hello hello", "hello world")
    manager = CommandManager()
    navigated = []
    dialog = FindReplaceDialog(parent, doc, [1], manager.execute, navigated.append)
    yield dialog, doc, manager, navigated
    parent.destroy()


def test_search_options_and_captured_selection_scope(editor):
    dialog, _doc, _manager, navigated = editor
    dialog.search_entry.set_text("hello")
    assert len(dialog.matches) == 3
    assert navigated[-1] == 0
    dialog.case_sensitive.set_active(True)
    assert len(dialog.matches) == 2
    dialog.selection_only.set_active(True)
    assert len(dialog.matches) == 1
    assert dialog.matches[0].position == 1
    dialog.whole_words.set_active(True)
    dialog.search_entry.set_text("hell")
    assert not dialog.matches
    assert not dialog.replace_all_button.get_sensitive()


def test_replace_one_advances_and_undo_restores_one_occurrence(editor):
    dialog, doc, manager, _navigated = editor
    dialog.search_entry.set_text("hello")
    dialog.replace_entry.set_text("Hi")
    dialog._replace_one()
    assert doc.entries[0].text == "Hi hello"
    assert dialog.matches[dialog.current_match].position == 0
    assert dialog.matches[dialog.current_match].start == 3
    manager.undo()
    dialog.refresh(navigate=False)
    assert doc.entries[0].text == "Hello hello"
    assert len(dialog.matches) == 3


def test_replace_all_preview_and_single_undo_step(editor):
    dialog, doc, manager, _navigated = editor
    dialog.search_entry.set_text("hello")
    dialog.replace_entry.set_text("caption")
    row = dialog.preview_list.get_row_at_index(0)
    assert "Before:" in row.get_subtitle()
    assert "After: caption" in row.get_subtitle()
    dialog._replace_all()
    assert [entry.text for entry in doc.entries] == ["caption caption", "caption world"]
    assert not dialog.matches
    assert not dialog.replace_button.get_sensitive()
    manager.undo()
    assert [entry.text for entry in doc.entries] == ["Hello hello", "hello world"]
    assert not manager.can_undo()


def test_previous_next_and_preview_click_navigate(editor):
    dialog, _doc, _manager, navigated = editor
    dialog.search_entry.set_text("hello")
    dialog._move(-1)
    assert dialog.current_match == 2
    assert navigated[-1] == 1
    dialog._move(1)
    assert dialog.current_match == 0
    dialog.preview_list.select_row(dialog.preview_list.get_row_at_index(2))
    assert dialog.current_match == 2
    assert navigated[-1] == 1


def test_preview_limit_does_not_limit_replace_all(editor):
    dialog, doc, manager, _navigated = editor
    doc.entries[0].text = " ".join(["word"] * 105)
    dialog.search_entry.set_text("word")
    dialog.replace_entry.set_text("x")
    assert len(dialog.matches) == 105
    assert dialog.preview_list.get_row_at_index(100) is None
    assert "first 100" in dialog.note_label.get_text()
    dialog._move(-1)
    assert dialog.current_match == 104
    dialog._replace_all()
    assert doc.entries[0].text == " ".join(["x"] * 105)
    manager.undo()
    assert doc.entries[0].text.count("word") == 105


def test_ass_escapes_preview_and_replace_one_navigation():
    parent = Adw.Window()
    doc = make_document("hellohello", "next", fmt=SubtitleFormat.ASS)
    manager = CommandManager()
    dialog = FindReplaceDialog(parent, doc, (), manager.execute)
    dialog.search_entry.set_text("hello")
    dialog.replace_entry.set_text(r"a\Nb")
    assert "a ↵ b" in dialog.preview_list.get_row_at_index(0).get_subtitle()
    dialog._replace_one()
    assert doc.entries[0].text == "a\nbhello"
    assert dialog.matches[dialog.current_match].start == 3
    assert not dialog.selection_only.get_sensitive()
    dialog.replace_entry.set_text(r"{\b1}text")
    assert dialog.error_label.get_visible()
    assert not dialog.replace_button.get_sensitive()
    parent.destroy()


def test_noop_and_stale_preview_are_reported_without_mutation(editor):
    dialog, doc, manager, _navigated = editor
    dialog.search_entry.set_text("hello")
    dialog.replace_entry.set_text("hello")
    dialog.case_sensitive.set_active(True)
    dialog._replace_all()
    assert dialog.error_label.get_visible()
    assert not manager.can_undo()
    dialog.replace_entry.set_text("new")
    doc.entries[0].text = "External change"
    dialog._replace_all()
    assert doc.entries[0].text == "External change"
    assert doc.entries[1].text == "hello world"
    assert dialog.error_label.get_visible()
    assert not manager.can_undo()
