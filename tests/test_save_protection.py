"""Real-window save decisions, recovery lifecycle, and failed-save regressions."""

import tempfile

import pytest

from gsub.resources import register_resources

try:
    from gi.repository import Adw, Gdk, Gio, GLib, Gtk
    register_resources()
    Adw.init()
    Gtk.init()
    if Gdk.Display.get_default() is None:
        pytest.skip("no display available for GTK integration tests", allow_module_level=True)
    from gsub.window import GsubWindow
except ImportError as error:
    pytest.skip(str(error), allow_module_level=True)

from gsub import save_workflow, window as window_module  # noqa: E402
from gsub.models import SubtitleDocument, SubtitleFormat  # noqa: E402
from gsub.parsers import SRTParser  # noqa: E402
from gsub.recovery import RecoveredBatch, RecoverySession, RecoveryStore  # noqa: E402


SRT = "1\n00:00:01,000 --> 00:00:03,000\nOriginal text\n"
# GTK keeps application signal closures alive across window teardown. Keep
# the Python application wrapper alive too when later modules create windows.
_APPLICATIONS = []


class DecisionDialog:
    created = []

    def __init__(self, parent, title, body):
        self.title, self.body = title, body
        self.responses = {}
        self.handlers = []
        self.presented = False
        self.created.append(self)

    def add_response(self, key, label):
        self.responses[key] = label

    def set_response_appearance(self, *args):
        pass

    def set_default_response(self, key):
        self.default = key

    def set_close_response(self, key):
        self.close_response = key

    def connect(self, signal, handler):
        self.handlers.append(handler)

    def present(self):
        self.presented = True

    def respond(self, response):
        for handler in self.handlers:
            handler(self, response)


@pytest.fixture(scope="module")
def real_window():
    with tempfile.TemporaryDirectory(prefix="gsub-save-tests-") as directory:
        original = GsubWindow._get_config_dir
        GsubWindow._get_config_dir = lambda self: directory
        app = Adw.Application(application_id="io.github.obaidaalbitar.gsub.save-tests")
        app.register(None)
        _APPLICATIONS.append(app)
        win = GsubWindow(application=app)
        win._stop_recovery_timer()
        yield win
        win._stop_recovery_timer()
        win.destroy()
        GsubWindow._get_config_dir = original


@pytest.fixture
def win(real_window, monkeypatch):
    win = real_window
    win._stop_recovery_timer()
    win._save_guard_active = False
    win._save_dialog_pending = False
    win._close_confirmed = False
    win._recovery_unresolved = False
    win._pending_recovery_stores = []
    win._recovery_store.clear()
    for path in win._recovery_store.path.parent.glob("pending-*"):
        path.unlink()
    win.batch_file_list.clear()
    win._create_new_document()
    win.errors = []
    win.toasts = []
    monkeypatch.setattr(win, "_show_error", win.errors.append)
    monkeypatch.setattr(win, "_show_toast", win.toasts.append)
    DecisionDialog.created = []
    monkeypatch.setattr(save_workflow.Adw.MessageDialog, "new", DecisionDialog)
    yield win
    win._stop_recovery_timer()


def dirty_editor(win, tmp_path, untitled=False):
    path = tmp_path / "editor.srt"
    path.write_text(SRT)
    win._open_file_now(Gio.File.new_for_path(str(path)))
    win.document.entries[0].text = "Unsaved editor text"
    win.document.modified = True
    if untitled:
        win.current_file = win.document.file_path = None
    return path, win.document


def dirty_batch(win, tmp_path, selected=False):
    path = tmp_path / "batch.srt"
    path.write_text(SRT)
    win._add_batch_files([Gio.File.new_for_path(str(path))])
    item = win.batch_file_list.get_all_files()[-1]
    item.document.entries[0].text = "Unsaved batch text"
    item.document.modified = item.modified = True
    item.selected = selected
    return path, item


def test_new_cancel_preserves_document_and_snapshot(win, tmp_path):
    _, document = dirty_editor(win, tmp_path)
    win._on_new(None, None)
    DecisionDialog.created[-1].respond("cancel")
    assert win.document is document
    assert document.modified
    assert win._recovery_store.load().editor.entries[0].text == "Unsaved editor text"


def test_new_discard_replaces_only_after_explicit_decision(win, tmp_path):
    path, document = dirty_editor(win, tmp_path)
    win._on_new(None, None)
    assert win.document is document
    DecisionDialog.created[-1].respond("discard")
    assert win.document is not document
    assert win.document.entries == []
    assert path.read_text() == SRT
    assert not win._recovery_store.path.exists()


def test_new_save_writes_then_replaces_document(win, tmp_path):
    path, document = dirty_editor(win, tmp_path)
    win._on_new(None, None)
    DecisionDialog.created[-1].respond("save")
    assert "Unsaved editor text" in path.read_text()
    assert win.document is not document
    assert not win._recovery_store.path.exists()


def test_failed_save_does_not_replace_document(win, tmp_path, monkeypatch):
    path, document = dirty_editor(win, tmp_path)
    monkeypatch.setattr(window_module, "atomic_write_text",
                        lambda *args: (_ for _ in ()).throw(OSError("disk full")))
    win._on_new(None, None)
    DecisionDialog.created[-1].respond("save")
    assert win.document is document
    assert document.modified
    assert path.read_text() == SRT
    assert any("disk full" in error for error in win.errors)
    assert not win._save_guard_active


@pytest.mark.parametrize("saved", [True, False])
def test_untitled_save_waits_for_async_completion(win, tmp_path, monkeypatch, saved):
    _, document = dirty_editor(win, tmp_path, untitled=True)
    callbacks = []
    monkeypatch.setattr(win, "_on_save_as", lambda _a, _p, on_complete=None:
                        callbacks.append(on_complete))
    win._on_new(None, None)
    DecisionDialog.created[-1].respond("save")
    assert win.document is document
    assert win._save_guard_active
    callbacks[0](saved)
    assert (win.document is not document) == saved
    assert not win._save_guard_active


@pytest.mark.parametrize("response", ["cancel", "discard", "save"])
def test_open_directly_obeys_unsaved_decision(win, tmp_path, response):
    original, document = dirty_editor(win, tmp_path)
    target = tmp_path / "next.srt"
    target.write_text(SRT.replace("Original text", "Next document"))
    win.open_file(Gio.File.new_for_path(str(target)))
    assert win.document is document
    DecisionDialog.created[-1].respond(response)
    assert (win.document is document) == (response == "cancel")
    assert ("Unsaved editor text" in original.read_text()) == (response == "save")
    if response != "cancel":
        assert win.document.entries[0].text == "Next document"


def test_failed_open_does_not_destroy_current_document_or_dirty_state(win, tmp_path):
    _, document = dirty_editor(win, tmp_path)
    win.open_file(Gio.File.new_for_path(str(tmp_path / "missing.srt")))
    DecisionDialog.created[-1].respond("discard")
    assert win.document is document
    assert document.modified
    assert win.errors


def test_repeated_replacement_does_not_stack_save_prompts(win, tmp_path):
    dirty_editor(win, tmp_path)
    win._on_new(None, None)
    win._on_new(None, None)
    assert len(DecisionDialog.created) == 1


def test_pending_text_is_flushed_before_dirty_decision(win, tmp_path):
    path = tmp_path / "pending.srt"
    path.write_text(SRT)
    win._open_file_now(Gio.File.new_for_path(str(path)))
    win.subtitle_list.select_entry(0)
    win.editor_panel.text_buffer.set_text("Typed immediately before closing")
    assert win._on_close_request(win)
    assert win.document.modified
    assert DecisionDialog.created


def test_close_cancel_includes_unchecked_batch_files(win, tmp_path):
    path, item = dirty_batch(win, tmp_path, selected=False)
    assert win._on_close_request(win) is True
    dialog = DecisionDialog.created[-1]
    assert path.name in dialog.body
    dialog.respond("cancel")
    assert item.modified
    assert path.read_text() == SRT


def test_close_save_saves_editor_and_all_dirty_batch_files(win, tmp_path, monkeypatch):
    editor_path, document = dirty_editor(win, tmp_path)
    batch_path, item = dirty_batch(win, tmp_path, selected=False)
    closed = []
    monkeypatch.setattr(win, "_finish_guarded_close", lambda: closed.append(True))
    assert win._on_close_request(win)
    DecisionDialog.created[-1].respond("save")
    assert closed == [True]
    assert not document.modified
    assert not item.modified
    assert "Unsaved editor text" in editor_path.read_text()
    assert "Unsaved batch text" in batch_path.read_text()


def test_close_failed_batch_save_keeps_window_open_and_recovery(win, tmp_path, monkeypatch):
    _, item = dirty_batch(win, tmp_path)
    closed = []
    monkeypatch.setattr(win, "_finish_guarded_close", lambda: closed.append(True))
    monkeypatch.setattr(save_workflow, "atomic_write_text",
                        lambda *args: (_ for _ in ()).throw(OSError("not writable")))
    win._on_close_request(win)
    DecisionDialog.created[-1].respond("save")
    assert closed == []
    assert item.modified
    assert win._recovery_store.load().batch


def test_close_save_all_rejects_conflicting_versions_of_same_file(win, tmp_path, monkeypatch):
    source, document = dirty_editor(win, tmp_path)
    _, item = dirty_batch(win, tmp_path)
    item.file_path = item.document.file_path = str(source)
    closed = []
    monkeypatch.setattr(win, "_finish_guarded_close", lambda: closed.append(True))
    win._on_close_request(win)
    DecisionDialog.created[-1].respond("save")
    assert not closed
    assert document.modified and item.modified
    assert source.read_text() == SRT
    assert "Save As" in win.errors[-1]
    snapshot = win._recovery_store.load()
    assert snapshot.editor is not None and snapshot.batch


def test_same_file_with_identical_editor_and_batch_content_can_save(win, tmp_path, monkeypatch):
    source, document = dirty_editor(win, tmp_path)
    _, item = dirty_batch(win, tmp_path)
    item.file_path = item.document.file_path = str(source)
    item.document.entries[0].text = document.entries[0].text
    closed = []
    monkeypatch.setattr(win, "_finish_guarded_close", lambda: closed.append(True))
    win._on_close_request(win)
    DecisionDialog.created[-1].respond("save")
    assert closed == [True]
    assert not document.modified and not item.modified
    assert "Unsaved editor text" in source.read_text()


def test_batch_save_detects_alias_of_dirty_editor_via_symlink(win, tmp_path):
    source, document = dirty_editor(win, tmp_path)
    _, item = dirty_batch(win, tmp_path)
    link = tmp_path / "alias.srt"
    link.symlink_to(source.name)
    item.file_path = str(link)
    assert win._save_batch_items([item]) is False
    assert document.modified and item.modified
    assert source.read_text() == SRT
    assert link.is_symlink()


def test_batch_save_preflights_all_documents_before_first_write(win, tmp_path, monkeypatch):
    source, item = dirty_batch(win, tmp_path)
    monkeypatch.setattr(win, "_batch_content",
                        lambda _doc: (_ for _ in ()).throw(ValueError("invalid document")))
    assert win._save_batch_items([item]) is False
    assert item.modified
    assert source.read_text() == SRT


def test_saving_editor_keeps_recovery_for_dirty_batch(win, tmp_path):
    editor_path, _ = dirty_editor(win, tmp_path)
    dirty_batch(win, tmp_path)
    assert win._save_document(str(editor_path))
    session = win._recovery_store.load()
    assert session.editor is None
    assert len(session.batch) == 1


@pytest.mark.parametrize("response", ["cancel", "discard", "save"])
def test_dirty_batch_removal_uses_save_discard_cancel(win, tmp_path, response):
    path, item = dirty_batch(win, tmp_path)
    win.batch_file_list._selection.set_selected(0)
    win.batch_file_list.remove_selected()
    assert item in win.batch_file_list.get_all_files()
    DecisionDialog.created[-1].respond(response)
    assert (item in win.batch_file_list.get_all_files()) == (response == "cancel")
    assert ("Unsaved batch text" in path.read_text()) == (response == "save")


class SaveChooser:
    def __init__(self, path=None, error=None):
        self.path, self.error = path, error

    def save_finish(self, result):
        if self.error is not None:
            raise self.error
        return Gio.File.new_for_path(str(self.path)) if self.path is not None else None


def test_cancelled_save_as_reports_false_without_changing_document(win, tmp_path):
    _, document = dirty_editor(win, tmp_path, untitled=True)
    result = []
    win._save_dialog_pending = True
    error = GLib.Error.new_literal(Gtk.DialogError.quark(), "Cancelled", Gtk.DialogError.DISMISSED)
    win._on_save_as_response(SaveChooser(error=error), None, result.append, document)
    assert result == [False]
    assert win.document is document
    assert document.modified
    assert not win._save_dialog_pending
    assert not win.errors


def test_failed_save_as_conversion_keeps_original_format_and_content(win, tmp_path, monkeypatch):
    _, document = dirty_editor(win, tmp_path)
    monkeypatch.setattr(window_module, "atomic_write_text",
                        lambda *args: (_ for _ in ()).throw(OSError("disk full")))
    result = []
    win._on_save_as_response(SaveChooser(tmp_path / "converted.ass"), None,
                             result.append, document)
    assert result == [False]
    assert win.document is document
    assert document.format == SubtitleFormat.SRT
    assert document.modified


def test_successful_save_as_conversion_commits_only_after_file_write(win, tmp_path):
    _, document = dirty_editor(win, tmp_path, untitled=True)
    target = tmp_path / "converted.ass"
    result = []
    win._on_save_as_response(SaveChooser(target), None, result.append, document)
    assert result == [True]
    assert win.document.format == SubtitleFormat.ASS
    assert not win.document.modified
    assert win.current_file == str(target)
    assert "Unsaved editor text" in target.read_text()


def test_stale_save_as_cannot_save_a_different_document(win, tmp_path):
    _, original = dirty_editor(win, tmp_path)
    win._create_new_document()
    target = tmp_path / "wrong.srt"
    result = []
    win._on_save_as_response(SaveChooser(target), None, result.append, original)
    assert result == [False]
    assert not target.exists()
    assert win.document is not original


def test_recovery_later_preserves_old_snapshot_and_protects_current_edits(win, tmp_path):
    _, previous = dirty_editor(win, tmp_path)
    previous.entries[0].text = "Previous session"
    win._snapshot_recovery()
    win.document = None
    win._init_save_workflow()
    pending = win._pending_recovery_stores[0].path
    win._offer_recovery()
    DecisionDialog.created[-1].respond("later")
    dirty_editor(win, tmp_path)
    assert win._snapshot_recovery()
    assert pending.exists()
    assert "Previous session" in pending.read_text()
    assert win._recovery_store.load().editor.entries[0].text == "Unsaved editor text"


def test_restore_recovery_marks_unsaved_and_leaves_original_disk_untouched(win, tmp_path):
    source, previous = dirty_editor(win, tmp_path)
    win._snapshot_recovery()
    win.document = None
    win._init_save_workflow()
    pending = win._pending_recovery_stores[0].path
    win._offer_recovery()
    DecisionDialog.created[-1].respond("restore")
    assert win.document.modified
    assert win.document.entries[0].text == previous.entries[0].text
    assert win.current_file == str(source)
    assert source.read_text() == SRT
    assert not pending.exists()
    assert win._recovery_store.path.exists()


def test_restore_batch_retains_selection_and_save_baseline(win, tmp_path):
    source, item = dirty_batch(win, tmp_path, selected=False)
    baseline = win._batch_saved_content[id(item)]
    session = RecoverySession(None, [RecoveredBatch(item.document, str(source), False, baseline)])
    win.batch_file_list.clear()
    assert win._restore_recovery(session)
    restored = win.batch_file_list.get_all_files()[0]
    assert restored.modified and restored.document.modified
    assert restored.selected is False
    assert win._batch_saved_content[id(restored)] == baseline
    assert source.read_text() == SRT


def test_batch_only_recovery_preserves_current_unsaved_editor(win, tmp_path):
    _, document = dirty_editor(win, tmp_path)
    store = RecoveryStore(win._recovery_store.path.parent, "pending-batch.json")
    batch = SRTParser.parse(SRT)
    store.save(None, [RecoveredBatch(batch, str(tmp_path / "restored-batch.srt"))])
    win._pending_recovery_stores = [store]
    win._offer_recovery()
    DecisionDialog.created[-1].respond("restore")
    assert len(DecisionDialog.created) == 1
    assert win.document is document and document.modified
    assert win._recovery_store.load().editor.entries[0].text == "Unsaved editor text"


def test_editor_only_recovery_preserves_unchecked_dirty_batch(win, tmp_path):
    _, item = dirty_batch(win, tmp_path, selected=False)
    store = RecoveryStore(win._recovery_store.path.parent, "pending-editor.json")
    editor = SRTParser.parse(SRT)
    editor.modified = True
    store.save(editor)
    win._pending_recovery_stores = [store]
    win._offer_recovery()
    DecisionDialog.created[-1].respond("restore")
    assert len(DecisionDialog.created) == 1
    assert item in win.batch_file_list.get_all_files()
    assert item.modified and item.document.modified
    assert win._recovery_store.load().batch[0].document.entries[0].text == "Unsaved batch text"


def test_discarding_recovery_does_not_write_originals(win, tmp_path):
    source, _ = dirty_editor(win, tmp_path)
    win._snapshot_recovery()
    win.document = None
    win._init_save_workflow()
    pending = win._pending_recovery_stores[0].path
    win._offer_recovery()
    DecisionDialog.created[-1].respond("discard")
    assert not pending.exists()
    assert source.read_text() == SRT
    assert win.document is None


def test_bad_recovery_is_preserved_and_current_session_still_works(win, tmp_path):
    win._recovery_store.path.parent.mkdir(parents=True, exist_ok=True)
    win._recovery_store.path.write_text("{invalid")
    win._init_save_workflow()
    win._offer_recovery()
    assert list(win._recovery_store.path.parent.glob("*.invalid"))
    dirty_editor(win, tmp_path)
    assert win._snapshot_recovery()


def test_recovery_write_failure_does_not_interrupt_editing_and_notifies_once(win, tmp_path, monkeypatch):
    dirty_editor(win, tmp_path)
    monkeypatch.setattr(win._recovery_store, "save",
                        lambda *args: (_ for _ in ()).throw(OSError("disk full")))
    assert win._snapshot_recovery() is False
    assert win._snapshot_recovery() is False
    assert sum("Recovery copy" in message for message in win.toasts) == 1
    assert win.document.modified


def test_mutations_debounce_recovery_writes(win, tmp_path, monkeypatch):
    dirty_editor(win, tmp_path)
    saves = []
    monkeypatch.setattr(win._recovery_store, "save", lambda *args: saves.append(args))
    win._document_mutated()
    source = win._recovery_debounce_id
    win._document_mutated()
    assert win._recovery_debounce_id == source
    assert saves == []
    GLib.source_remove(source)
    win._flush_queued_recovery()
    assert len(saves) == 1


def test_periodic_snapshot_flushes_pending_editor_text(win, tmp_path):
    source = tmp_path / "pending.srt"
    source.write_text(SRT)
    win._open_file_now(Gio.File.new_for_path(str(source)))
    win.subtitle_list.select_entry(0)
    win.editor_panel.text_buffer.set_text("Pending text survives a crash")
    win._autosave_recovery()
    assert win._recovery_store.load().editor.entries[0].text == "Pending text survives a crash"


def test_clean_close_does_not_prompt(win):
    assert win._on_close_request(win) is False
    assert not DecisionDialog.created


def test_close_during_pending_save_as_keeps_window_alive(win):
    win._save_dialog_pending = True
    assert win.document.modified is False
    assert win._on_close_request(win) is True
    assert not DecisionDialog.created
    win._save_dialog_pending = False
    assert win._on_close_request(win) is False


def test_saving_empty_document_is_supported(win, tmp_path):
    win.document = SubtitleDocument(SubtitleFormat.SRT, modified=True)
    assert win._save_document(str(tmp_path / "empty.srt"))
    assert (tmp_path / "empty.srt").exists()
