"""Cross-feature GTK workflows using the shipped SRT and ASS exercises.

The window, subtitle editor, proofreading UI, commands and recovery storage
are real. A player recorder isolates action wiring from multimedia decoding,
which is tested separately by the player workflow suite.
"""

from copy import deepcopy
from pathlib import Path

import pytest

from gsub.models import SubtitleFormat
from gsub.parsers import parse_subtitle_document
from gsub.parsers.encoding import decode_subtitle_text
from gsub.quality import QualitySettings
from gsub.recovery import RecoveredBatch, RecoveryStore
from gsub.resources import register_resources

try:
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, Gio, GLib, Gtk
    register_resources()
    Gtk.init()
    Adw.init()
    HAS_DISPLAY = Gdk.Display.get_default() is not None
except Exception:
    HAS_DISPLAY = False

pytestmark = pytest.mark.skipif(not HAS_DISPLAY, reason="no display available for GTK tests")

from tests.test_window import StubPlayer  # noqa: E402
from gsub.window import GsubWindow  # noqa: E402


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
TIMING_ACTIONS = ("set-start-here", "set-end-here", "play-cue", "loop-cue")


class WorkflowPlayer(StubPlayer):
    def __init__(self):
        super().__init__()
        self._duration = 180.0
        self.selected_position = -1
        self.cue_looping = False

    def set_selected_position(self, position):
        super().set_selected_position(position)
        self.selected_position = position

    def play_selected_cue(self, loop=False):
        self.calls.append(("play_selected_cue", loop))
        self.cue_looping = loop
        return self.document is not None and self.selected_position >= 0

    def clear_cue_playback(self, pause=False):
        self.calls.append(("clear_cue_playback", pause))
        self.cue_looping = False


def pump():
    context = GLib.MainContext.default()
    for _ in range(8):
        context.iteration(False)


@pytest.fixture(scope="module")
def workflow_window(tmp_path_factory):
    directory = tmp_path_factory.mktemp("workflow-config")
    original = GsubWindow._get_config_dir
    GsubWindow._get_config_dir = lambda _self: str(directory)
    app = Adw.Application(application_id="io.github.obaidaalbitar.gsub.workflow-tests")
    app.register(None)
    win = GsubWindow(application=app)
    win.errors, win.toasts = [], []
    win._show_error = win.errors.append
    win._show_toast = win.toasts.append
    try:
        yield win
    finally:
        win._stop_recovery_timer()
        win.destroy()
        GsubWindow._get_config_dir = original


@pytest.fixture
def window(workflow_window):
    win = workflow_window
    win.editor_panel.flush_pending_changes()
    win._close_document_dialogs()
    if win.document is not None:
        win.document.modified = False
    for item in win.batch_file_list.get_all_files():
        item.modified = item.document.modified = False
    win.batch_file_list.clear()
    win.command_manager.clear()
    win.current_video_file = None
    win.video_player = WorkflowPlayer()
    win._save_guard_active = False
    win._save_dialog_pending = False
    win._close_confirmed = False
    win._pending_recovery_stores = []
    win._recovery_store.clear()
    win._save_config({"quality_settings": QualitySettings().to_dict()})
    win.errors.clear()
    win.toasts.clear()
    pump()
    return win


def open_example(win, tmp_path, extension="srt", name="working"):
    source = EXAMPLES / f"editing_tools_test.{extension}"
    path = tmp_path / f"{name}.{extension}"
    path.write_bytes(source.read_bytes())
    assert win.open_file(Gio.File.new_for_path(str(path)))
    pump()
    assert not win.errors
    return path


def activate(win, name):
    action = win.lookup_action(name)
    assert action is not None and action.get_enabled(), name
    action.activate(None)
    pump()


def select(win, position):
    win.subtitle_list.select_entry(position)
    pump()


def select_review_issue(panel, code, position):
    issue = next(issue for issue in panel.issues
                 if issue.position == position and issue.code == code)
    panel._on_issue_activated(None, panel.review.issue_key(issue))


@pytest.mark.parametrize("extension", ["srt", "ass"])
def test_timing_quality_fix_recovery_and_atomic_save_roundtrip(window, tmp_path, extension):
    original_path = open_example(window, tmp_path, extension)
    original_bytes = original_path.read_bytes()
    activate(window, "quality-check")
    panel = window._quality_dialog
    assert window.review_stack.get_visible_child_name() == "quality"
    select_review_issue(panel, "text.line_length", 14)
    assert window.subtitle_list.get_selected_position() == 14
    original_entry = deepcopy(window.document.entries[14])

    window.current_video_file = "preview.mkv"
    window.video_player.position = 50.1234
    window._update_selection_actions()
    activate(window, "set-start-here")
    expected_start = 50_123 if extension == "srt" else 50_120
    assert window.document.entries[14].start_time.total_milliseconds == expected_start
    assert window.document.entries[14].end_time == original_entry.end_time
    assert panel.document is window.document
    activate(window, "undo")
    assert window.document.entries[14] == original_entry
    activate(window, "redo")

    select_review_issue(panel, "text.line_length", 14)
    panel._preview_rebalance()
    preview = panel.preview
    assert preview is not None and "\n" in preview.after
    assert window.document.entries[14].text == original_entry.text
    panel._apply_preview()
    assert window.document.entries[14].text == preview.after
    assert window.review_stack.get_visible_child_name() == "quality"
    assert not any(issue.position == 14 and issue.code == "text.line_length"
                   for issue in panel.issues)
    activate(window, "undo")
    assert window.document.entries[14].text == original_entry.text
    assert window.document.entries[14].start_time.total_milliseconds == expected_start
    activate(window, "redo")
    assert window.document.entries[14].text == preview.after

    assert window._snapshot_recovery()
    recovered = window._recovery_store.load()
    assert recovered.editor == window.document
    assert recovered.editor.entries[14].actor == original_entry.actor
    assert recovered.editor.entries[14].layer == original_entry.layer
    assert original_path.read_bytes() == original_bytes

    output = tmp_path / f"reviewed.{extension}"
    assert window._save_document(str(output))
    assert not window.document.modified
    assert not window._recovery_store.path.exists()
    document, warnings = parse_subtitle_document(
        decode_subtitle_text(output.read_bytes()), "." + extension)
    assert not warnings
    assert document.entries[14].text == preview.after
    assert document.entries[14].start_time.total_milliseconds == expected_start
    assert document.entries[14].actor == original_entry.actor
    assert document.entries[14].layer == original_entry.layer
    assert original_path.read_bytes() == original_bytes


def test_closing_and_reopening_panel_keeps_ignored_warnings(window, tmp_path):
    open_example(window, tmp_path)
    activate(window, "quality-check")
    panel = window._quality_dialog
    initial_count = len(panel.issues)
    panel._ignore_current()
    assert len(panel.issues) == initial_count - 1
    panel.close()
    assert window.review_stack.get_visible_child_name() == "subtitles"
    assert window._quality_dialog is panel
    activate(window, "quality-check")
    assert window._quality_dialog is panel
    assert panel.review.ignored_count == 1
    assert len(panel.issues) == initial_count - 1
    activate(window, "find")
    assert window.review_stack.get_visible_child_name() == "subtitles"
    assert window._quality_dialog is panel


@pytest.mark.parametrize("extension", ["srt", "ass"])
def test_replacing_document_detaches_old_panel_and_resets_review(window, tmp_path, extension):
    open_example(window, tmp_path, extension)
    activate(window, "quality-check")
    previous = window._quality_dialog
    previous._ignore_current()
    open_example(window, tmp_path, extension, name="second")
    assert previous.get_parent() is None
    assert window._quality_dialog is None
    assert window.review_stack.get_visible_child_name() == "subtitles"
    activate(window, "quality-check")
    assert window._quality_dialog is not previous
    assert window._quality_dialog.document is window.document
    assert window._quality_dialog.review.ignored_count == 0


def test_new_timing_actions_require_video_and_exactly_one_cue(window, tmp_path):
    open_example(window, tmp_path)
    select(window, 0)
    assert all(not window.lookup_action(name).get_enabled() for name in TIMING_ACTIONS)
    window.current_video_file = "preview.mkv"
    window._update_selection_actions()
    assert all(window.lookup_action(name).get_enabled() for name in TIMING_ACTIONS)
    window.subtitle_list.select_entry(1, clear_others=False)
    assert all(not window.lookup_action(name).get_enabled() for name in TIMING_ACTIONS)
    select(window, 0)
    window.current_video_file = None
    window._update_selection_actions()
    assert all(not window.lookup_action(name).get_enabled() for name in TIMING_ACTIONS)
    window.document = None
    window._update_document_actions()
    assert not window.lookup_action("quality-check").get_enabled()
    assert all(not window.lookup_action(name).get_enabled() for name in TIMING_ACTIONS)


@pytest.mark.parametrize("extension", ["srt", "ass"])
def test_timing_action_flushes_typing_and_undo_keeps_separate_edit_steps(window, tmp_path, extension):
    open_example(window, tmp_path, extension)
    select(window, 0)
    original = deepcopy(window.document.entries[0])
    window.current_video_file = "preview.mkv"
    window.video_player.position = 1.2399
    window._update_selection_actions()
    window.editor_panel.text_buffer.set_text("Pending typing from the editor")
    activate(window, "set-start-here")
    assert window.document.entries[0].text == "Pending typing from the editor"
    expected = 1240 if extension == "srt" else 1230
    assert window.document.entries[0].start_time.total_milliseconds == expected
    activate(window, "undo")
    assert window.document.entries[0].start_time == original.start_time
    assert window.document.entries[0].text == "Pending typing from the editor"
    activate(window, "undo")
    assert window.document.entries[0] == original
    assert not window.command_manager.can_undo()


def test_play_and_loop_actions_use_selected_cue_and_loop_toggle_stops_it(window, tmp_path):
    open_example(window, tmp_path)
    select(window, 2)
    window.current_video_file = "preview.mkv"
    window._update_selection_actions()
    activate(window, "play-cue")
    assert window.video_player.selected_position == 2
    assert window.video_player.named("play_selected_cue") == [False]
    activate(window, "loop-cue")
    assert window.video_player.cue_looping
    assert window.video_player.named("play_selected_cue") == [False, True]
    activate(window, "loop-cue")
    assert not window.video_player.cue_looping
    assert window.video_player.named("clear_cue_playback") == [True]


@pytest.mark.parametrize("extension", ["srt", "ass"])
def test_recovery_restores_unsaved_fixed_text_and_creates_fresh_review(window, tmp_path, extension):
    path = open_example(window, tmp_path, extension)
    disk_before = path.read_bytes()
    activate(window, "quality-check")
    old_panel = window._quality_dialog
    select_review_issue(old_panel, "text.line_length", 14)
    old_panel._preview_rebalance()
    fixed = old_panel.preview.after
    old_panel._apply_preview()
    old_panel._ignore_current()
    window._snapshot_recovery()
    session = window._recovery_store.load()
    assert window._restore_recovery(session)
    assert old_panel.get_parent() is None
    assert window._quality_dialog is None
    assert window.document.entries[14].text == fixed
    assert window.document.modified
    assert path.read_bytes() == disk_before
    activate(window, "quality-check")
    assert window._quality_dialog.review.ignored_count == 0
    assert window._quality_dialog.document is session.editor


def test_save_failure_keeps_dirty_reviewed_work_and_recovery_copy(window, tmp_path, monkeypatch):
    from gsub import window as window_module

    path = open_example(window, tmp_path)
    before = path.read_bytes()
    activate(window, "quality-check")
    panel = window._quality_dialog
    select_review_issue(panel, "text.line_length", 14)
    panel._preview_rebalance()
    panel._apply_preview()
    fixed = window.document.entries[14].text
    window._snapshot_recovery()

    def fail_write(*_args, **_kwargs):
        raise OSError("Simulated disk error")

    monkeypatch.setattr(window_module, "atomic_write_text", fail_write)
    assert not window._save_document(str(path))
    assert window.document.modified
    assert window.document.entries[14].text == fixed
    assert path.read_bytes() == before
    assert window._recovery_store.load().editor.entries[14].text == fixed
    assert window.errors and "Simulated disk error" in window.errors[-1]


def test_quality_settings_update_is_shared_with_subsequent_rebalance_commands(window, tmp_path):
    open_example(window, tmp_path)
    activate(window, "quality-check")
    panel = window._quality_dialog
    panel.max_chars_row.set_value(32)
    assert window._load_config()["quality_settings"]["max_chars_per_line"] == 32
    select_review_issue(panel, "text.line_length", 14)
    panel._preview_rebalance()
    preview = panel.preview
    assert preview is not None and preview.max_line_length == 32
    panel.max_chars_row.set_value(30)
    assert panel.preview is None
    assert panel.document.format == SubtitleFormat.SRT


def dirty_both_workspaces(win, tmp_path):
    editor_path = open_example(win, tmp_path)
    select(win, 0)
    win.editor_panel.text_buffer.set_text("Current unsaved editor work")
    win.editor_panel.flush_pending_changes()
    batch_path = tmp_path / "existing-batch.srt"
    batch_path.write_bytes((EXAMPLES / "batch_undo_partner.srt").read_bytes())
    win._add_batch_files([Gio.File.new_for_path(str(batch_path))])
    item = win.batch_file_list.get_all_files()[0]
    item.document.entries[0].text = "Current unsaved batch work"
    item.modified = item.document.modified = True
    item.selected = False
    return editor_path, batch_path, win.document, item


def offer_single_workspace_recovery(win, tmp_path, workspace):
    source = EXAMPLES / "batch_undo_partner.srt"
    recovered, _ = parse_subtitle_document(source.read_text(), ".srt")
    recovered.entries[0].text = "Recovered work from a prior session"
    recovered.file_path = str(tmp_path / f"recovered-{workspace}.srt")
    recovered.modified = True
    store = RecoveryStore(win._recovery_store.path.parent, f"pending-{workspace}.json")
    if workspace == "batch":
        store.save(None, [RecoveredBatch(recovered, recovered.file_path, False)])
    else:
        store.save(recovered)
    win._pending_recovery_stores = [store]
    win._offer_recovery()
    win._recovery_dialog.response("restore")
    return store


@pytest.mark.parametrize("workspace", ["editor", "batch"])
def test_restore_discard_targets_only_workspace_being_replaced(window, tmp_path, workspace):
    editor_path, batch_path, editor, batch_item = dirty_both_workspaces(window, tmp_path)
    editor_bytes, batch_bytes = editor_path.read_bytes(), batch_path.read_bytes()
    pending = offer_single_workspace_recovery(window, tmp_path, workspace)
    assert window._save_guard_active
    body = window._save_guard_dialog.get_body()
    if workspace == "batch":
        assert batch_path.name in body and editor_path.name not in body
    else:
        assert editor_path.name in body and batch_path.name not in body
    window._save_guard_dialog.response("discard")
    pump()
    assert not window._save_guard_active
    assert not pending.path.exists()
    if workspace == "batch":
        assert window.document is editor and editor.modified
        assert editor.entries[0].text == "Current unsaved editor work"
        assert window.batch_file_list.get_all_files()[0].document.entries[0].text.startswith("Recovered")
    else:
        assert window.document is not editor and window.document.modified
        assert window.document.entries[0].text.startswith("Recovered")
        assert window.batch_file_list.get_all_files()[0] is batch_item
        assert batch_item.modified and batch_item.document.modified
    current = window._recovery_store.load()
    assert current.editor is not None and len(current.batch) == 1
    assert editor_path.read_bytes() == editor_bytes
    assert batch_path.read_bytes() == batch_bytes


@pytest.mark.parametrize("workspace", ["editor", "batch"])
def test_cancel_restore_keeps_both_workspaces_dirty_and_pending_copy(window, tmp_path, workspace):
    _, _, editor, batch_item = dirty_both_workspaces(window, tmp_path)
    pending = offer_single_workspace_recovery(window, tmp_path, workspace)
    window._save_guard_dialog.response("cancel")
    pump()
    assert window.document is editor and editor.modified
    assert window.batch_file_list.get_all_files()[0] is batch_item
    assert batch_item.modified and batch_item.document.modified
    assert pending.path.exists()
    assert window._recovery_store.load().editor.entries[0].text == "Current unsaved editor work"


def test_failed_restore_retains_current_editor_batch_and_both_recovery_copies(window, tmp_path, monkeypatch):
    _, _, editor, batch_item = dirty_both_workspaces(window, tmp_path)
    window._snapshot_recovery()

    def fail_set_document(_document):
        raise RuntimeError("Simulated player refresh failure")

    monkeypatch.setattr(window.video_player, "set_document", fail_set_document)
    pending = offer_single_workspace_recovery(window, tmp_path, "editor")
    window._save_guard_dialog.response("discard")
    pump()
    assert window.document is editor
    assert editor.modified
    assert editor.entries[0].text == "Current unsaved editor work"
    assert window.batch_file_list.get_all_files()[0] is batch_item
    assert batch_item.modified and batch_item.document.modified
    assert pending.path.exists()
    assert window._recovery_store.load().editor.entries[0].text == "Current unsaved editor work"
    assert any("Simulated player refresh failure" in error for error in window.errors)


def test_partial_batch_restore_failure_rolls_back_both_workspaces_and_undo_history(window, tmp_path, monkeypatch):
    _, batch_path, editor, batch_item = dirty_both_workspaces(window, tmp_path)
    baseline = window._batch_saved_content[id(batch_item)]
    assert window.command_manager.can_undo()
    recovered_editor = deepcopy(editor)
    recovered_editor.entries[0].text = "Recovered editor should not remain after failure"
    recovered_batch = deepcopy(batch_item.document)
    recovered_batch.entries[0].text = "Recovered batch should not remain after failure"
    pending = RecoveryStore(window._recovery_store.path.parent, "pending-combined.json")
    recovered_batch_path = str(tmp_path / "recovered-batch.srt")
    pending.save(recovered_editor, [RecoveredBatch(recovered_batch, recovered_batch_path)])
    real_add = window.batch_file_list.add_file

    def fail_recovered_batch(document, path):
        if path == recovered_batch_path:
            raise RuntimeError("Simulated batch population failure")
        return real_add(document, path)

    monkeypatch.setattr(window.batch_file_list, "add_file", fail_recovered_batch)
    window._pending_recovery_stores = [pending]
    window._offer_recovery()
    window._recovery_dialog.response("restore")
    window._save_guard_dialog.response("discard")
    pump()
    assert window.document is editor and editor.modified
    assert editor.entries[0].text == "Current unsaved editor work"
    assert window.batch_file_list.get_all_files() == [batch_item]
    assert batch_item.modified and batch_item.document.modified
    assert batch_item.selected is False
    assert batch_item.file_path == str(batch_path)
    assert window._batch_saved_content[id(batch_item)] == baseline
    assert pending.path.exists()
    current = window._recovery_store.load()
    assert current.editor.entries[0].text == "Current unsaved editor work"
    assert current.batch[0].document.entries[0].text == "Current unsaved batch work"
    assert any("Simulated batch population failure" in error for error in window.errors)
    activate(window, "undo")
    assert window.document.entries[0].text == "The last train leaves at midnight."


def capture_save_chooser(monkeypatch, target):
    captured = []
    monkeypatch.setattr(Gtk.FileDialog, "save", lambda chooser, parent, cancellable, callback:
                        captured.append((chooser, callback)))
    monkeypatch.setattr(Gtk.FileDialog, "save_finish", lambda _chooser, _result:
                        Gio.File.new_for_path(str(target)))
    return captured


@pytest.mark.parametrize("target_format", ["srt", "ass"])
def test_save_as_writes_latest_pending_typing_while_chooser_open(window, tmp_path, monkeypatch, target_format):
    open_example(window, tmp_path)
    select(window, 0)
    target = tmp_path / f"latest.{target_format}"
    captured = capture_save_chooser(monkeypatch, target)
    activate(window, "save-as")
    assert window._save_dialog_pending and len(captured) == 1
    window.editor_panel.text_buffer.set_text("Typing added while the save chooser was open")
    chooser, callback = captured[0]
    callback(chooser, None)
    pump()
    saved, _ = parse_subtitle_document(target.read_text(), "." + target_format)
    assert saved.entries[0].text == "Typing added while the save chooser was open"
    assert window.document.entries[0].text == saved.entries[0].text
    assert not window.document.modified
    assert not window._save_dialog_pending
    assert not window._recovery_store.path.exists()


def test_new_waits_for_real_save_chooser_callback_and_saves_latest_edit(window, tmp_path, monkeypatch):
    open_example(window, tmp_path)
    select(window, 0)
    window.editor_panel.text_buffer.set_text("Initial unsaved edit")
    window.editor_panel.flush_pending_changes()
    old_document = window.document
    window.current_file = window.document.file_path = None
    target = tmp_path / "untitled-saved.srt"
    captured = capture_save_chooser(monkeypatch, target)
    activate(window, "new")
    window._save_guard_dialog.response("save")
    assert window.document is old_document
    assert window._save_guard_active and window._save_dialog_pending
    window.editor_panel.text_buffer.set_text("Latest edit before finishing Save As")
    chooser, callback = captured[0]
    callback(chooser, None)
    pump()
    saved, _ = parse_subtitle_document(target.read_text(), ".srt")
    assert saved.entries[0].text == "Latest edit before finishing Save As"
    assert window.document is not old_document
    assert not window.document.entries
    assert not window._save_guard_active
    assert not window._save_dialog_pending
