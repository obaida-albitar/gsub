"""GTK integration tests for the real GsubWindow.

Instantiates one GsubWindow per module (it is heavy: template, subtitle
list, editor panel and a real mpv handle) against a registered (but never
run) Adw.Application. The video player attribute is replaced with a stub
after construction so no video is ever loaded into mpv; all other widgets
(subtitle list, editor panel, compatibility panel, batch panels) are real.

Handlers and actions are invoked directly — no file dialogs are driven.
Requires a display; skipped automatically when none is available.
"""

import shutil
import tempfile

import pytest

from gsub.resources import register_resources

try:
    from gi.repository import Adw, Gdk, Gio, GLib, Gtk
    register_resources()
    try:
        Gtk.init()
        Adw.init()
    except Exception:
        pass
    _HAS_DISPLAY = Gdk.Display.get_default() is not None
except Exception:  # pragma: no cover - environment without GTK
    _HAS_DISPLAY = False

pytestmark = pytest.mark.skipif(
    not _HAS_DISPLAY, reason="no display available for GTK widget tests"
)

try:
    from gsub.window import (
        GsubWindow, _window_key_lookup, _window_key_table,
    )
except Exception as exc:  # pragma: no cover - depends on GTK/libmpv stack
    pytest.skip(
        f"window module not importable in this environment: {exc}",
        allow_module_level=True,
    )

from gsub import window as window_module  # noqa: E402
from gsub.models import SubtitleFormat, TimeCode  # noqa: E402
from gsub.commands.subtitle_commands import EditTextCommand  # noqa: E402
from gsub.shortcuts import window_key_entries  # noqa: E402

SRT_CONTENT = """1
00:00:00,500 --> 00:00:02,000
First subtitle

2
00:00:02,500 --> 00:00:05,000
Second subtitle

3
00:00:05,500 --> 00:00:08,000
Third subtitle
"""

# Out-of-order SRT: the first block starts later than the second.
SRT_UNORDERED = """1
00:00:05,000 --> 00:00:06,000
Charlie

2
00:00:01,000 --> 00:00:02,000
Alpha

3
00:00:03,000 --> 00:00:04,000
Bravo
"""

# ASS with an invalid PrimaryColour (compat issue with a color fix) and a
# \blur(99) override in the dialogue (compat issue with a blur fix).
ASS_CONTENT = """[Script Info]
ScriptType: v4.00+

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,20,notacolor,&H000000FF,&H00000000,&H00000000,0,0,0,0,100.0,100.0,0.0,0.0,1,2.0,0.0,2,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,{\\blur(99)}Hello there
Dialogue: 0,0:00:03.00,0:00:04.00,Default,,0,0,0,,Second line
"""


class StubPlayer:
    """Video player stand-in recording every call the window makes."""

    def __init__(self):
        self.calls = []
        self.document = None
        self.current_audio_track = -1
        self.current_subtitle_track = -1
        self.position = 0.0
        self.audio_tracks = []
        self.subtitle_tracks = []
        self.embedded = (False, False)

    # Names must match the real VideoPlayerWidget API the window touches.
    def set_document(self, doc):
        self.calls.append(("set_document", doc))
        self.document = doc

    def load_video(self, path):
        self.calls.append(("load_video", path))

    def toggle_play_pause(self):
        self.calls.append(("toggle_play_pause",))

    def get_position(self):
        return self.position

    def seek(self, seconds):
        self.calls.append(("seek", seconds))
        self.position = seconds

    def frame_step(self, back=False):
        self.calls.append(("frame_step", back))

    def queue_subtitle_redraw(self):
        self.calls.append(("queue_subtitle_redraw",))

    def refresh_timeline_regions(self):
        self.calls.append(("refresh_timeline_regions",))

    def set_selected_position(self, position):
        self.calls.append(("set_selected_position", position))

    def get_available_tracks(self):
        return self.audio_tracks, self.subtitle_tracks

    def has_embedded_tracks(self):
        return self.embedded

    def set_audio_track(self, index):
        self.calls.append(("set_audio_track", index))

    def set_subtitle_track(self, index):
        self.calls.append(("set_subtitle_track", index))

    def subtitle_track_format(self, track_id):
        return "ass"

    def extract_subtitle_track(self, track_index, out_path, callback):
        self.calls.append(("extract_subtitle_track", track_index))

    def named(self, name):
        """Arguments of every call to *name* (unpacked when there is one)."""
        results = []
        for method, *args in self.calls:
            if method != name:
                continue
            results.append(args[0] if len(args) == 1 else tuple(args))
        return results


class RecordingTrackDialog:
    """Stands in for TrackSelectionDialog, recording construction.

    The window builds the real dialog via the module-level name, so tests
    monkeypatch gsub.window.TrackSelectionDialog with this class
    to observe that the dialog was created, presented, and with which
    track lists — without driving a real Adw.Dialog.
    """

    created = []

    def __init__(self, parent, audio_tracks, subtitle_tracks,
                 current_audio=-1, current_subtitle=-1):
        self.parent = parent
        self.audio_tracks = list(audio_tracks)
        self.subtitle_tracks = list(subtitle_tracks)
        self.connected = []
        self.presented = False
        RecordingTrackDialog.created.append(self)

    @classmethod
    def reset(cls):
        cls.created = []

    def connect(self, signal, handler):
        self.connected.append(signal)

    def present(self):
        self.presented = True


@pytest.fixture(scope="module")
def window():
    """One real GsubWindow with an isolated config dir and a stub player."""
    config_dir = tempfile.mkdtemp(prefix="gsub-window-tests-")
    original_config_dir = GsubWindow._get_config_dir
    GsubWindow._get_config_dir = lambda self: config_dir

    app = Adw.Application(application_id="io.github.obaidaalbitar.gsub.window-tests")
    app.register(None)
    win = GsubWindow(application=app)

    # Record toasts/errors while still exercising the real code paths.
    toasts = []
    real_toast = win._show_toast

    def _toast(message):
        toasts.append(message)
        real_toast(message)

    win._show_toast = _toast
    win.toasts = toasts

    errors = []
    real_error = win._show_error

    def _error(message):
        errors.append(message)
        real_error(message)

    win._show_error = _error
    win.errors = errors

    player = StubPlayer()
    win.video_player = player

    yield win

    win.destroy()
    GsubWindow._get_config_dir = original_config_dir
    shutil.rmtree(config_dir, ignore_errors=True)


def _pump(count=5):
    """Dispatch pending main-loop events (selection signals, idles)."""
    ctx = GLib.MainContext.default()
    for _ in range(count):
        ctx.iteration(False)


def _write(tmp_path, name, content):
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return str(path)


def _open(win, tmp_path, name, content):
    path = _write(tmp_path, name, content)
    win.toasts.clear()
    win.errors.clear()
    win.open_file(Gio.File.new_for_path(path))
    _pump()
    return path


def _new_document(win):
    win.toasts.clear()
    win._create_new_document()
    _pump()


def _select(win, position):
    win.subtitle_list.select_entry(position)
    _pump()


@pytest.mark.integration
class TestWindowConstruction:
    def test_editor_and_batch_headers_share_compact_file_and_history_groups(self, window):
        editor = window.header_start_stack.get_child_by_name("editor")
        batch = window.header_start_stack.get_child_by_name("batch")
        assert editor.get_spacing() == batch.get_spacing() == 0

        editor_files = editor.get_first_child()
        batch_files = batch.get_first_child()
        assert editor_files.has_css_class("linked")
        assert batch_files.has_css_class("linked")
        assert editor_files.get_spacing() == batch_files.get_spacing() == 0
        assert window.batch_add_button.get_parent() is batch_files
        assert window.batch_add_button.get_icon_name() == "list-add-symbolic"
        assert not window.batch_add_button.get_label()
        assert window.batch_add_button.get_tooltip_text() == "Add subtitle files to the batch"

        for undo, redo, header in (
            (window.undo_button, window.redo_button, editor),
            (window.batch_undo_button, window.batch_redo_button, batch),
        ):
            group = undo.get_parent()
            assert group.get_parent() is header
            assert redo.get_parent() is group
            assert group.has_css_class("linked")
            assert group.get_spacing() == 0
            assert group.get_margin_start() == 6
            assert undo.get_icon_name() == "edit-undo-symbolic"
            assert redo.get_icon_name() == "edit-redo-symbolic"
            assert undo.get_action_name() == "win.undo"
            assert redo.get_action_name() == "win.redo"

    def test_batch_add_icon_keeps_its_add_files_behavior(self, window, monkeypatch):
        invoked = []
        monkeypatch.setattr(window, "_on_batch_add_files", lambda: invoked.append(True))
        window.batch_add_button.emit("clicked")
        assert invoked == [True]

    def test_key_actions_are_registered(self, window):
        for name in (
            "new", "open", "save", "save-as", "convert-to-srt",
            "convert-to-ass", "undo", "redo", "add-entry", "remove-entry",
            "duplicate-entry", "move-up", "move-down", "insert-above",
            "insert-below", "time-shift", "sort-by-time", "open-video",
            "play-pause", "toggle-video", "select-tracks",
            "seek-to-selection", "batch", "find",
            "replace", "quality-check", "split-entry", "merge-entries", "rebalance-text",
            "about", "show-help-overlay",
        ):
            assert window.lookup_action(name) is not None, name

    def test_starts_on_home_with_empty_editor(self, window):
        assert window.current_view == "home"
        assert window.content_stack.get_visible_child_name() == "home"
        assert window.title_stack.get_visible_child() is window.title_widget
        assert window.list_stack.get_visible_child_name() == "empty"
        assert window.document is None
        assert window.title_widget.get_title() == "Gsub"
        assert window.file_label.get_visible() is False

    def test_document_actions_disabled_without_document(self, window):
        window.document = None
        window._update_document_actions()
        window._update_format_actions()
        # undo/redo enablement is owned by the history state, not the
        # document: an empty history disables them regardless.
        window.command_manager.clear()
        window._update_undo_redo_buttons()

        for name in ("save", "undo", "redo", "add-entry", "sort-by-time"):
            assert window.lookup_action(name).get_enabled() is False, name
        # ASS-only actions are disabled for a missing document too.
        assert window.lookup_action("ass-styles").get_enabled() is False

    def test_accelerators_registered_on_application(self, window):
        app = window.get_application()
        assert "<Control>z" in app.get_accels_for_action("win.undo")
        assert "<Control>j" in app.get_accels_for_action(
            "win.seek-to-selection")
        # Delete is a window key, never an accel: as an accel it would win
        # over the text editor and delete the entry instead of a character.
        assert app.get_accels_for_action("win.remove-entry") == []
        # Actions absent from the shortcuts table get no accel.
        assert app.get_accels_for_action("win.batch") == []


@pytest.mark.integration
class TestNavigation:
    def test_editor_view_without_document_shows_empty_state(self, window):
        window.document = None
        window._navigate_to_editor()

        assert window.current_view == "editor"
        assert window.view_stack.get_visible_child_name() == "editor"
        assert window.content_stack.get_visible_child_name() == "main"
        # The view switcher replaces the window title once views are on screen.
        assert window.title_stack.get_visible_child() is window.view_switcher
        # No dialog, no crash: the list shows its empty placeholder.
        assert window.list_stack.get_visible_child_name() == "empty"
        # The compatibility button is icon-only: the badge stays hidden while
        # there are no issues and the tooltip carries the count.
        assert window.compat_badge.get_visible() is False
        assert window.compat_btn.get_tooltip_text() == "Compatibility Checker (0 issues)"
        assert window.compat_btn.get_sensitive() is False

    def test_batch_navigation(self, window):
        window._navigate_to_batch()
        assert window.current_view == "batch"
        assert window.view_stack.get_visible_child_name() == "batch"
        assert window.content_stack.get_visible_child_name() == "main"
        # The batch status bar describes the empty list.
        assert "No files loaded" in window.status_bar.get_text()

    def test_navigation_action_switches_to_batch_view(self, window):
        assert window.activate_action("win.batch") is True
        assert window.current_view == "batch"
        assert window.view_stack.get_visible_child_name() == "batch"

    def test_switcher_switches_views(self, window):
        window._navigate_to_batch()
        window.view_stack.set_visible_child_name("editor")
        _pump()
        assert window.current_view == "editor"
        assert window.content_stack.get_visible_child_name() == "main"

    def test_file_name_shown_in_footer(self, window, tmp_path):
        _open(window, tmp_path, "footer.srt", SRT_CONTENT)

        assert window.file_label.get_visible() is True
        assert window.file_label.get_text() == "footer.srt"

        window.document.modified = True
        window._update_title()
        assert window.file_label.get_text() == "footer.srt • Modified"

    def test_file_name_hidden_outside_editor(self, window, tmp_path):
        _open(window, tmp_path, "footer.srt", SRT_CONTENT)
        window._navigate_to_batch()

        assert window.file_label.get_visible() is False


@pytest.mark.integration
class TestNewDocument:
    def test_new_creates_empty_srt_document(self, window):
        _new_document(window)

        assert window.document is not None
        assert window.document.format == SubtitleFormat.SRT
        assert window.document.entries == []
        assert window.current_file is None
        assert window.list_stack.get_visible_child_name() == "list"
        assert window.current_view == "editor"
        assert window.status_bar.get_text() == "0 subtitles • SRT format"
        assert window.title_widget.get_title() == "Gsub"
        # Document-dependent actions become available; ASS-only stay off.
        assert window.lookup_action("save").get_enabled() is True
        assert window.lookup_action("ass-styles").get_enabled() is False
        # The player received the new document.
        assert window.video_player.document is window.document

    def test_new_response_discard_replaces_document(self, window, tmp_path):
        _open(window, tmp_path, "old.srt", SRT_CONTENT)
        assert len(window.document.entries) == 3

        window._on_new_response(None, "discard")

        assert window.document.entries == []
        assert window.current_file is None

    def test_new_response_save_writes_then_replaces(self, window, tmp_path):
        path = _open(window, tmp_path, "unsaved.srt", SRT_CONTENT)
        window.document.entries[0].text = "Modified"
        window.document.modified = True

        window._on_new_response(None, "save")

        # The old file was written with the modification...
        saved = open(path, encoding="utf-8").read()
        assert "Modified" in saved
        # ...and a fresh empty document took its place.
        assert window.document.entries == []
        assert window.current_file is None

    def test_new_response_cancel_keeps_document(self, window, tmp_path):
        _open(window, tmp_path, "keep.srt", SRT_CONTENT)

        window._on_new_response(None, "cancel")

        assert len(window.document.entries) == 3

    def test_add_entry_without_document_creates_one(self, window):
        window.document = None
        window._on_add_entry(None, None)

        # Falls through to the new-document flow instead of crashing.
        assert window.document is not None


@pytest.mark.integration
class TestOpenFile:
    def test_open_srt_loads_entries_and_updates_ui(self, window, tmp_path):
        path = _open(window, tmp_path, "movie.srt", SRT_CONTENT)

        assert len(window.document.entries) == 3
        assert window.document.entries[0].text == "First subtitle"
        assert window.current_file == path
        assert window.title_widget.get_title() == "movie.srt"
        assert window.list_stack.get_visible_child_name() == "list"
        assert window.current_view == "editor"
        assert window.status_bar.get_text() == "3 subtitles • SRT format"
        assert any("Opened movie.srt" in t for t in window.toasts)
        # Opening resets the undo history and forwards the document.
        assert window.command_manager.can_undo() is False
        assert window.video_player.document is window.document
        # SRT: no style dropdown, no compat issues.
        assert window.editor_panel.style_row.get_visible() is False
        assert window.compat_issues == []

    def test_open_ass_sets_style_context_and_format_actions(
            self, window, tmp_path):
        _open(window, tmp_path, "movie.ass", ASS_CONTENT)

        assert window.document.format == SubtitleFormat.ASS
        model = window.editor_panel.style_model
        names = [model.get_string(i) for i in range(model.get_n_items())]
        assert names == ["Default"]
        assert window.editor_panel.style_row.get_visible() is True
        # ASS-only actions come alive.
        for name in ("ass-info", "ass-styles", "bulk-apply-style"):
            assert window.lookup_action(name).get_enabled() is True, name

    def test_open_ass_reports_compatibility_issues(self, window, tmp_path):
        _open(window, tmp_path, "compat.ass", ASS_CONTENT)

        codes = {issue.code for issue in window.compat_issues}
        assert "color.unknown_format" in codes
        assert window.compat_panel.count_label.get_text().startswith(
            f"{len(window.compat_issues)} issue(s)")
        assert any("compatibility issue" in t for t in window.toasts)

    def test_open_unsupported_extension_shows_error(self, window, tmp_path):
        _open(window, tmp_path, "old.doc", SRT_CONTENT.replace("\n", " "))

        assert window.document is None
        assert any("Unsupported file format" in e for e in window.errors)


@pytest.mark.integration
class TestEditAndUndoRedo:
    def test_text_edit_undo_redo_roundtrip(self, window, tmp_path):
        _open(window, tmp_path, "edit.srt", SRT_CONTENT)
        _select(window, 0)
        assert window.editor_panel.current_position == 0

        # Type through the real editor panel (debounced 500 ms). Use a
        # wall-clock deadline: leftover sources from earlier suites can
        # consume iteration budgets before the debounce timeout fires.
        import time
        window.editor_panel.text_buffer.set_text("Edited text")
        ctx = GLib.MainContext.default()
        deadline = time.monotonic() + 5.0
        while window.editor_panel._text_change_timeout_id is not None \
                and time.monotonic() < deadline:
            ctx.iteration(True)

        assert window.document.entries[0].text == "Edited text"
        assert window.document.modified is True
        assert window.title_widget.get_subtitle() == "Modified"
        assert window.command_manager.can_undo() is True
        assert window.undo_button.get_sensitive() is True

        window.toasts.clear()
        window._on_undo(None, None)

        assert window.document.entries[0].text == "First subtitle"
        assert any("Undo: Edit text" in t for t in window.toasts)
        assert window.undo_button.get_sensitive() is False
        assert window.redo_button.get_sensitive() is True

        window._on_redo(None, None)

        assert window.document.entries[0].text == "Edited text"
        assert any("Redo: Edit text" in t for t in window.toasts)

    def test_undo_buttons_reset_on_document_switch(self, window, tmp_path):
        # Regression: opening/creating a document clears the command stack
        # but the header buttons used to stay sensitive afterwards.
        _open(window, tmp_path, "first.srt", SRT_CONTENT)
        _select(window, 0)
        window.command_manager.execute(
            EditTextCommand(window.document, 0, "Edited"))
        # Real handlers refresh the buttons after executing; mirror that
        # since the command manager was driven directly.
        window._update_undo_redo_buttons()
        assert window.undo_button.get_sensitive() is True

        _open(window, tmp_path, "second.srt", SRT_CONTENT)
        assert window.command_manager.can_undo() is False
        assert window.undo_button.get_sensitive() is False
        assert window.redo_button.get_sensitive() is False

        window.command_manager.execute(
            EditTextCommand(window.document, 0, "Edited"))
        _new_document(window)
        assert window.undo_button.get_sensitive() is False

    def test_undo_with_empty_history_is_silent(self, window):
        _new_document(window)
        window.command_manager.clear()
        window.toasts.clear()

        window._on_undo(None, None)
        window._on_redo(None, None)

        assert window.toasts == []

    def test_timing_change_executes_edit_timing_command(
            self, window, tmp_path):
        _open(window, tmp_path, "timing.srt", SRT_CONTENT)

        start = TimeCode.from_milliseconds(1_000)
        end = TimeCode.from_milliseconds(2_750)
        window._on_timing_changed(None, 0, start, end)

        entry = window.document.entries[0]
        assert entry.start_time.total_milliseconds == 1_000
        assert entry.end_time.total_milliseconds == 2_750
        assert window.command_manager.can_undo() is True

    def test_text_and_timing_guards(self, window):
        window.document = None
        # No document: handlers must be silent no-ops.
        window._on_text_changed(None, 0, "x")
        window._on_timing_changed(
            None, 0, TimeCode(0), TimeCode(0))
        window._on_style_changed(None, 0, "Default")
        window._on_position_changed(None, 0, 1, 2, 3)


@pytest.mark.integration
class TestEntryStructureActions:
    def test_add_entry_appends_at_end_without_selection(self, window):
        _new_document(window)

        window.activate_action("win.add-entry")

        assert len(window.document.entries) == 1
        assert window.subtitle_list.get_selected_position() == 0
        assert any("Subtitle added" in t for t in window.toasts)

    def test_add_entry_inserts_after_selection(self, window, tmp_path):
        _open(window, tmp_path, "add.srt", SRT_CONTENT)
        _select(window, 0)

        window._on_add_entry(None, None)

        assert len(window.document.entries) == 4
        assert window.subtitle_list.get_selected_position() == 1

    def test_insert_above_and_below_without_selection_are_noops(
            self, window):
        _new_document(window)
        window._on_insert_above(None, None)
        window._on_insert_below(None, None)

        assert window.document.entries == []

    def test_insert_above_selection(self, window, tmp_path):
        _open(window, tmp_path, "above.srt", SRT_CONTENT)
        _select(window, 1)

        window._on_insert_above(None, None)

        assert len(window.document.entries) == 4
        assert window.subtitle_list.get_selected_position() == 1

    def test_remove_without_selection_is_noop(self, window, tmp_path):
        _open(window, tmp_path, "rm.srt", SRT_CONTENT)
        window.subtitle_list.select_entry(-1)

        window._on_remove_entry(None, None)

        assert len(window.document.entries) == 3
        assert not any("removed" in t for t in window.toasts)

    def test_remove_selected_entry(self, window, tmp_path):
        _open(window, tmp_path, "rm2.srt", SRT_CONTENT)
        _select(window, 1)

        window._on_remove_entry(None, None)

        assert len(window.document.entries) == 2
        assert window.document.entries[0].text == "First subtitle"
        assert window.document.entries[1].text == "Third subtitle"
        assert any("1 subtitle removed" in t for t in window.toasts)
        # Removal is undoable.
        window._on_undo(None, None)
        assert len(window.document.entries) == 3

    def test_remove_selects_next_entry_with_visible_highlight(
            self, window, tmp_path):
        _open(window, tmp_path, "rm-next.srt", SRT_CONTENT)
        _select(window, 1)

        window._on_remove_entry(None, None)
        _pump()

        # The row that moved into the removed slot stays selected, and the
        # selection model agrees with the cached positions, so the highlight
        # is actually visible.
        assert window.subtitle_list.get_selected_positions() == [1]
        bitset = window.subtitle_list.selection_model.get_selection()
        assert [bitset.get_nth(i) for i in range(bitset.get_size())] == [1]
        assert window.editor_panel.current_position == 1
        assert window.lookup_action("remove-entry").get_enabled() is True

    def test_remove_last_entry_selects_previous(self, window, tmp_path):
        _open(window, tmp_path, "rm-last.srt", SRT_CONTENT)
        _select(window, 2)

        window._on_remove_entry(None, None)
        _pump()

        assert window.subtitle_list.get_selected_positions() == [1]
        assert window.editor_panel.current_position == 1

    def test_remove_only_entry_clears_selection(self, window):
        _new_document(window)
        window.activate_action("win.add-entry")
        _pump()

        window._on_remove_entry(None, None)
        _pump()

        assert window.subtitle_list.get_selected_positions() == []
        assert window.lookup_action("remove-entry").get_enabled() is False
        assert window.editor_panel.current_position == -1

    def test_duplicate_without_selection_is_noop(self, window, tmp_path):
        _open(window, tmp_path, "dup.srt", SRT_CONTENT)
        window.subtitle_list.select_entry(-1)

        window._on_duplicate_entry(None, None)

        assert len(window.document.entries) == 3

    def test_duplicate_selected_entry(self, window, tmp_path):
        _open(window, tmp_path, "dup2.srt", SRT_CONTENT)
        _select(window, 2)

        window._on_duplicate_entry(None, None)

        assert len(window.document.entries) == 4
        assert window.document.entries[3].text == "Third subtitle"
        assert any("duplicated" in t for t in window.toasts)

    def test_move_up_down_and_boundaries(self, window, tmp_path):
        _open(window, tmp_path, "move.srt", SRT_CONTENT)

        # At the top: moving up is a no-op.
        _select(window, 0)
        window._on_move_up(None, None)
        assert window.document.entries[0].text == "First subtitle"

        window._on_move_down(None, None)
        assert window.document.entries[0].text == "Second subtitle"
        assert window.subtitle_list.get_selected_position() == 1

        window._on_move_up(None, None)
        assert window.document.entries[0].text == "First subtitle"

        # At the bottom: moving down is a no-op.
        _select(window, 2)
        window._on_move_down(None, None)
        assert window.document.entries[2].text == "Third subtitle"

    def test_structure_actions_without_document_do_not_crash(self, window):
        window.document = None
        window._on_remove_entry(None, None)
        window._on_duplicate_entry(None, None)
        window._on_move_up(None, None)
        window._on_move_down(None, None)


@pytest.mark.integration
class TestListHeaderAndSelectionActions:
    """Entry actions live in the list header and follow the selection."""

    def test_header_hidden_without_document(self, window):
        window.document = None
        window._update_status()

        assert window.list_header.get_visible() is False

    def test_header_count_tracks_document(self, window):
        _new_document(window)

        assert window.list_header.get_visible() is True
        assert window.list_count_label.get_text() == "(0)"

        window.activate_action("win.add-entry")
        assert window.list_count_label.get_text() == "(1)"

    def test_remove_and_duplicate_require_a_selection(self, window, tmp_path):
        _open(window, tmp_path, "sel.srt", SRT_CONTENT)
        window.subtitle_list.select_entry(-1)
        _pump()

        assert window.lookup_action("remove-entry").get_enabled() is False
        assert window.lookup_action("duplicate-entry").get_enabled() is False

        _select(window, 0)

        assert window.lookup_action("remove-entry").get_enabled() is True
        assert window.lookup_action("duplicate-entry").get_enabled() is True

        window.subtitle_list.select_entry(-1)
        _pump()

        assert window.lookup_action("remove-entry").get_enabled() is False
        assert window.lookup_action("duplicate-entry").get_enabled() is False

    def test_selection_actions_disabled_without_document(self, window):
        window.document = None
        window._update_document_actions()

        assert window.lookup_action("remove-entry").get_enabled() is False
        assert window.lookup_action("duplicate-entry").get_enabled() is False


@pytest.mark.integration
class TestSaveDocument:
    def test_save_roundtrip(self, window, tmp_path):
        _open(window, tmp_path, "roundtrip.srt", SRT_CONTENT)
        window.document.entries[1].text = "Changed"
        window.document.modified = True

        out = tmp_path / "saved.srt"
        window.toasts.clear()
        window._save_document(str(out))

        assert out.exists()
        assert window.document.modified is False
        assert window.current_file == str(out)
        assert window.title_widget.get_subtitle() == ""
        assert any("Saved saved.srt" in t for t in window.toasts)

        # Reopening the saved file yields identical entries.
        content = out.read_text(encoding="utf-8")
        assert "Changed" in content
        window.open_file(Gio.File.new_for_path(str(out)))
        assert [e.text for e in window.document.entries] == [
            "First subtitle", "Changed", "Third subtitle"]

    def test_save_without_document_is_noop(self, window, tmp_path):
        window.document = None
        out = tmp_path / "nope.srt"
        window._save_document(str(out))
        assert not out.exists()

    def test_on_save_uses_current_file(self, window, tmp_path):
        path = _open(window, tmp_path, "inplace.srt", SRT_CONTENT)
        window.document.entries[0].text = "Rewritten"

        window._on_save(None, None)

        assert "Rewritten" in open(path, encoding="utf-8").read()


@pytest.mark.integration
class TestSortAndConvert:
    def test_sort_by_time_orders_entries_and_is_undoable(
            self, window, tmp_path):
        _open(window, tmp_path, "unordered.srt", SRT_UNORDERED)
        assert window.document.entries[0].text == "Charlie"

        window.toasts.clear()
        window._on_sort_by_time(None, None)

        assert [e.text for e in window.document.entries] == [
            "Alpha", "Bravo", "Charlie"]
        assert any("sorted by time" in t for t in window.toasts)

        window._on_undo(None, None)
        assert window.document.entries[0].text == "Charlie"

    def test_sort_by_time_without_document_is_noop(self, window):
        window.document = None
        window._on_sort_by_time(None, None)  # must not raise

    def test_time_shift_guards(self, window):
        window.document = None
        window._on_time_shift(None, None)  # no document: nothing happens

        _new_document(window)
        window._on_time_shift(None, None)  # no entries: nothing happens

    def test_convert_guards(self, window):
        window.document = None
        window.toasts.clear()
        window._on_convert_to_srt(None, None)
        assert any("No document loaded" in t for t in window.toasts)

        _new_document(window)
        window.toasts.clear()
        window._on_convert_to_srt(None, None)
        assert any("already in SRT" in t for t in window.toasts)

    def test_convert_response_to_ass_updates_everything(
            self, window, tmp_path):
        path = _open(window, tmp_path, "convert.srt", SRT_CONTENT)

        window.toasts.clear()
        window._on_convert_response("convert", SubtitleFormat.ASS)

        assert window.document.format == SubtitleFormat.ASS
        assert window.lookup_action("ass-styles").get_enabled() is True
        assert window.editor_panel.style_row.get_visible() is True
        assert any("Converted from SRT to ASS" in t for t in window.toasts)
        # A banner suggests saving because the file on disk is now stale.
        assert window.banner.get_revealed() is True
        assert "Format converted" in window.banner.get_title()
        assert window.current_file == path


@pytest.mark.integration
class TestVideoPlayerIntegration:
    def test_load_video_path_reveals_player_and_navigates(
            self, window):
        _new_document(window)
        window.toasts.clear()

        window.load_video_path("/movies/example.mkv")

        assert window.current_video_file == "/movies/example.mkv"
        assert window.video_player.named("load_video") == [
            "/movies/example.mkv"]
        assert window.current_view == "editor"
        assert window.video_visible is True
        assert window.video_container.get_visible() is True
        assert window.video_button.get_active() is True
        assert any("example.mkv" in t for t in window.toasts)

    def test_region_adjusted_commits_undoable_timing_edit(
            self, window, tmp_path):
        _open(window, tmp_path, "region.srt", SRT_CONTENT)

        window._on_region_adjusted(None, 1, 3_000, 4_500)

        entry = window.document.entries[1]
        assert entry.start_time.total_milliseconds == 3_000
        assert entry.end_time.total_milliseconds == 4_500
        assert window.command_manager.can_undo() is True
        assert window.video_player.named("refresh_timeline_regions")

        window._on_undo(None, None)
        assert entry.start_time.total_milliseconds == 2_500

    def test_region_adjusted_noop_when_unchanged(self, window, tmp_path):
        _open(window, tmp_path, "region2.srt", SRT_CONTENT)
        window.command_manager.clear()

        window._on_region_adjusted(None, 0, 500, 2_000)

        assert window.command_manager.can_undo() is False

    def test_region_selected_selects_entry(self, window, tmp_path):
        _open(window, tmp_path, "regionsel.srt", SRT_CONTENT)
        window._on_region_selected(None, 2)
        assert window.subtitle_list.get_selected_position() == 2

    def test_seek_to_selection(self, window, tmp_path):
        _open(window, tmp_path, "seek.srt", SRT_CONTENT)
        _select(window, 1)
        window.current_video_file = "/movies/example.mkv"

        window._on_seek_to_selection(None, None)

        # Entry 1 starts at 2.5 s.
        assert window.video_player.named("seek") == [2.5]

    def test_seek_to_selection_guards(self, window, tmp_path):
        _open(window, tmp_path, "seek2.srt", SRT_CONTENT)
        _select(window, 0)
        window.current_video_file = None
        window.video_player.calls.clear()
        window.toasts.clear()

        window._on_seek_to_selection(None, None)
        assert window.video_player.named("seek") == []

        # With a video but no selection: a toast, not a crash.
        window.current_video_file = "/movies/example.mkv"
        window.subtitle_list.select_entry(-1)
        window._on_seek_to_selection(None, None)
        assert window.video_player.named("seek") == []
        assert any("No subtitle selected" in t for t in window.toasts)

    def test_play_pause_requires_loaded_video(self, window):
        window.current_video_file = None
        window.video_player.calls.clear()
        window._on_play_pause(None, None)
        assert window.video_player.named("toggle_play_pause") == []

        window.current_video_file = "/movies/example.mkv"
        window._on_play_pause(None, None)
        assert len(window.video_player.named("toggle_play_pause")) == 1

    def test_nudge_and_frame_steps_require_loaded_video(self, window):
        window.current_video_file = None
        player = window.video_player
        player.calls.clear()
        player.position = 10.0

        window._on_seek_nudge_back(None, None)
        window._on_frame_step(None, None)
        assert player.calls == []

        window.current_video_file = "/movies/example.mkv"
        window._on_seek_nudge_back(None, None)
        # 10.0 - 0.1 = 9.9
        assert player.named("seek") == [9.9]
        window._on_seek_nudge_forward_large(None, None)
        assert player.named("seek") == [9.9, 14.9]
        window._on_frame_step(None, None)
        assert player.named("frame_step") == [False]
        window._on_frame_back_step(None, None)
        assert player.named("frame_step") == [False, True]

    def test_tracks_ready_dialog_decision(self, window, monkeypatch):
        shown = []
        monkeypatch.setattr(
            window, "_show_track_selection_dialog",
            lambda: shown.append(True))
        player = window.video_player

        # Single audio track, no subtitles: no dialog.
        player.audio_tracks = [{"id": 1}]
        player.subtitle_tracks = []
        window._on_tracks_ready(player)
        assert shown == []

        # Multiple audio tracks: dialog.
        player.audio_tracks = [{"id": 1}, {"id": 2}]
        window._on_tracks_ready(player)
        assert shown == [True]

        # Embedded subtitles: dialog.
        player.audio_tracks = [{"id": 1}]
        player.subtitle_tracks = [{"id": 3}]
        window._on_tracks_ready(player)
        assert len(shown) == 2

    def test_select_tracks_guards(self, window, monkeypatch):
        shown = []
        monkeypatch.setattr(
            window, "_show_track_selection_dialog", lambda: shown.append(True))
        player = window.video_player
        window.toasts.clear()

        window.current_video_file = None
        window._on_select_tracks(None, None)
        assert any("No video loaded" in t for t in window.toasts)

        window.current_video_file = "/movies/example.mkv"
        player.embedded = (False, False)
        window._on_select_tracks(None, None)
        assert any("No embedded tracks" in t for t in window.toasts)

        player.embedded = (True, False)
        window._on_select_tracks(None, None)
        assert shown == [True]


@pytest.mark.unit
class TestWindowKeyLookup:
    """The pure (keyval, state) -> action lookup behind the controller."""

    @pytest.fixture(scope="class")
    def table(self):
        return _window_key_table(window_key_entries())

    def test_plain_keys_match_with_clean_state(self, table):
        for key_name, action in (
            ("space", "win.play-pause"),
            ("period", "win.frame-step"),
            ("comma", "win.frame-back-step"),
            ("Left", "win.seek-nudge-back"),
            ("Right", "win.seek-nudge-forward"),
            ("Delete", "win.remove-entry"),
        ):
            assert _window_key_lookup(
                table, Gdk.keyval_from_name(key_name), 0) == action

    def test_shift_arrows_match_the_large_seeks(self, table):
        assert _window_key_lookup(
            table, Gdk.keyval_from_name("Left"),
            Gdk.ModifierType.SHIFT_MASK) == "win.seek-nudge-back-large"
        assert _window_key_lookup(
            table, Gdk.keyval_from_name("Right"),
            Gdk.ModifierType.SHIFT_MASK) == "win.seek-nudge-forward-large"

    def test_control_held_does_not_match(self, table):
        for key_name in ("space", "period", "comma", "Left", "Right",
                         "Delete"):
            assert _window_key_lookup(
                table, Gdk.keyval_from_name(key_name),
                Gdk.ModifierType.CONTROL_MASK) is None

    def test_shift_held_does_not_match_plain_keys(self, table):
        assert _window_key_lookup(
            table, Gdk.keyval_from_name("space"),
            Gdk.ModifierType.SHIFT_MASK) is None

    def test_unrelated_keyvals_do_not_match(self, table):
        for key_name in ("a", "Return", "Escape"):
            assert _window_key_lookup(
                table, Gdk.keyval_from_name(key_name), 0) is None

    def test_table_covers_exactly_the_window_key_actions(self, table):
        assert set(table.values()) == {
            "win.play-pause", "win.frame-step", "win.frame-back-step",
            "win.seek-nudge-back", "win.seek-nudge-forward",
            "win.seek-nudge-back-large", "win.seek-nudge-forward-large",
            "win.remove-entry"}
        assert set(table) == {
            (Gdk.keyval_from_name("space"), 0),
            (Gdk.keyval_from_name("period"), 0),
            (Gdk.keyval_from_name("comma"), 0),
            (Gdk.keyval_from_name("Left"), 0),
            (Gdk.keyval_from_name("Right"), 0),
            (Gdk.keyval_from_name("Left"), int(Gdk.ModifierType.SHIFT_MASK)),
            (Gdk.keyval_from_name("Right"), int(Gdk.ModifierType.SHIFT_MASK)),
            (Gdk.keyval_from_name("Delete"), 0),
        }


@pytest.mark.integration
class TestWindowKeyController:
    """The bubble-phase controller dispatching window-handled keys.

    Real key events are unreliable headless, so the controller's handler is
    invoked directly with the keyvals the signal would deliver. That Space
    no longer intercepts typing in editor_panel.text_view is a property of
    the bubble phase itself — a focused text widget consumes the key before
    the window ever sees it — and needs manual GUI verification.
    """

    def test_window_keys_not_registered_as_accels(self, window):
        app = window.get_application()
        for name in ("play-pause", "frame-step", "frame-back-step",
                     "seek-nudge-back", "seek-nudge-forward",
                     "seek-nudge-back-large", "seek-nudge-forward-large",
                     "remove-entry"):
            assert app.get_accels_for_action(f"win.{name}") == [], name
        # The controller dispatches them from its own lookup table instead.
        assert set(window._window_keys.values()) == {
            "win.play-pause", "win.frame-step", "win.frame-back-step",
            "win.seek-nudge-back", "win.seek-nudge-forward",
            "win.seek-nudge-back-large", "win.seek-nudge-forward-large",
            "win.remove-entry"}

    def test_space_toggles_playback_with_a_video(self, window):
        window.current_video_file = "/movies/example.mkv"
        window.video_player.calls.clear()

        handled = window._on_window_key_pressed(
            None, Gdk.keyval_from_name("space"), 0, 0)

        assert handled is True
        assert window.video_player.named("toggle_play_pause") == [()]

    def test_space_without_video_is_consumed_but_silent(self, window):
        window.current_video_file = None
        window.video_player.calls.clear()

        handled = window._on_window_key_pressed(
            None, Gdk.keyval_from_name("space"), 0, 0)

        # Same as the old accel: the key is consumed, the handler no-ops
        # because there is no video to play.
        assert handled is True
        assert window.video_player.calls == []

    def test_period_and_comma_frame_step(self, window):
        window.current_video_file = "/movies/example.mkv"
        window.video_player.calls.clear()

        assert window._on_window_key_pressed(
            None, Gdk.keyval_from_name("period"), 0, 0) is True
        assert window._on_window_key_pressed(
            None, Gdk.keyval_from_name("comma"), 0, 0) is True
        assert window.video_player.named("frame_step") == [False, True]

    def test_modifier_combos_fall_through(self, window):
        window.current_video_file = "/movies/example.mkv"
        window.video_player.calls.clear()

        combos = (
            Gdk.ModifierType.CONTROL_MASK,
            Gdk.ModifierType.SHIFT_MASK,
            Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK,
        )
        for state in combos:
            handled = window._on_window_key_pressed(
                None, Gdk.keyval_from_name("space"), 0, state)
            assert handled is False, state

        assert window.video_player.calls == []

    def test_unrelated_key_falls_through(self, window):
        assert window._on_window_key_pressed(
            None, Gdk.keyval_from_name("a"), 0, 0) is False

    def test_delete_removes_the_selected_entry(self, window, tmp_path):
        _open(window, tmp_path, "del.srt", SRT_CONTENT)
        _select(window, 0)

        handled = window._on_window_key_pressed(
            None, Gdk.keyval_from_name("Delete"), 0, 0)

        assert handled is True
        assert len(window.document.entries) == 2

    def test_delete_without_document_falls_through(self, window):
        window.document = None
        window._update_document_actions()

        assert window._on_window_key_pressed(
            None, Gdk.keyval_from_name("Delete"), 0, 0) is False


@pytest.mark.integration
class TestSelectTracksWithoutDocument:
    """win.select-tracks needs a loaded video, not a subtitle document."""

    def test_action_enabled_without_document(self, window):
        window.document = None
        window._update_document_actions()

        assert window.lookup_action("select-tracks").get_enabled() is True
        # The other video actions are not document-gated either.
        for name in ("open-video", "play-pause", "toggle-video"):
            assert window.lookup_action(name).get_enabled() is True, name

    def test_action_still_enabled_with_document(self, window):
        _new_document(window)
        window._update_document_actions()
        assert window.lookup_action("select-tracks").get_enabled() is True

    def test_video_with_audio_only_opens_dialog(self, window, monkeypatch):
        # 1 audio track, 0 embedded subtitles, and no document at all.
        window.document = None
        window._update_document_actions()
        player = window.video_player
        player.audio_tracks = [{"id": 1, "index": 1, "title": "Audio 1"}]
        player.subtitle_tracks = []
        player.embedded = (True, False)
        window.current_video_file = "/movies/example.mkv"

        RecordingTrackDialog.reset()
        monkeypatch.setattr(
            window_module, "TrackSelectionDialog", RecordingTrackDialog)

        assert window.activate_action("win.select-tracks") is True

        assert len(RecordingTrackDialog.created) == 1
        dialog = RecordingTrackDialog.created[0]
        assert len(dialog.audio_tracks) == 1
        assert dialog.subtitle_tracks == []
        assert dialog.presented is True
        assert "tracks-selected" in dialog.connected

    def test_no_video_toasts_instead_of_opening_dialog(self, window,
                                                       monkeypatch):
        window.current_video_file = None
        window.toasts.clear()
        RecordingTrackDialog.reset()
        monkeypatch.setattr(
            window_module, "TrackSelectionDialog", RecordingTrackDialog)

        assert window.activate_action("win.select-tracks") is True

        assert any("No video loaded" in t for t in window.toasts)
        assert RecordingTrackDialog.created == []


@pytest.mark.integration
class TestPlaybackHighlight:
    def test_position_changed_highlights_active_entry(self, window, tmp_path):
        _open(window, tmp_path, "highlight.srt", SRT_CONTENT)
        window._last_highlight_time = 0
        window._active_highlight = -1

        # 1.0 s falls inside the first entry (0.5-2.0 s).
        window._on_player_position_changed(None, 1.0)
        assert window._active_highlight == 0

        # An immediate second update is throttled: no new lookup, no change.
        window._on_player_position_changed(None, 6.0)
        assert window._active_highlight == 0

    def test_position_changed_without_document_is_safe(self, window):
        window.document = None
        window._last_highlight_time = 0
        window._on_player_position_changed(None, 5.0)


@pytest.mark.integration
class TestCompatibilityFixes:
    def test_color_fix_applies_and_refreshes_panel(self, window, tmp_path):
        _open(window, tmp_path, "fixcolor.ass", ASS_CONTENT)
        issue = next(i for i in window.compat_issues
                     if i.code == "color.unknown_format")

        window.toasts.clear()
        window._apply_compat_fix(issue)

        assert window.document.styles[0].primary_color == "&H00FFFFFF"
        assert any("Fixed: color corrected" in t for t in window.toasts)
        # The panel was refreshed: the colour issue is gone.
        assert all(i.code != "color.unknown_format"
                   for i in window.compat_issues)
        # And the fix is undoable.
        window._on_undo(None, None)
        assert window.document.styles[0].primary_color == "notacolor"

    def test_blur_fix_clamps_entry_text(self, window, tmp_path):
        _open(window, tmp_path, "fixblur.ass", ASS_CONTENT)
        issue = next(i for i in window.compat_issues if i.fix
                     and i.fix.get("kind") == "blur")

        window._apply_compat_fix(issue)

        assert "{\\blur(10)}Hello there" in window.document.entries[0].text

    def test_fix_without_document_is_noop(self, window, tmp_path):
        _open(window, tmp_path, "nofix.ass", ASS_CONTENT)
        issue = next(i for i in window.compat_issues
                     if i.code == "color.unknown_format")
        window.document = None
        window._apply_compat_fix(issue)  # must not raise

    def test_srt_documents_have_no_compat_issues(self, window, tmp_path):
        _open(window, tmp_path, "plain.srt", SRT_CONTENT)
        assert window.compat_issues == []
        assert window.compat_btn.get_sensitive() is False

    def test_style_edit_refreshes_compat(self, window, tmp_path):
        # Regression: fixing a style by hand (e.g. ScaleX in the styles
        # dialog) used to leave the stale issue listed until the file was
        # closed and reopened.
        import copy
        from gsub.commands.ass_commands import ReplaceASSHeaderCommand

        content = ASS_CONTENT.replace("100.0,100.0", "5.0,5.0", 1)
        _open(window, tmp_path, "smallscale.ass", content)
        assert any(i.code == "style.small_scale" for i in window.compat_issues)

        styles = [copy.deepcopy(s) for s in window.document.styles]
        styles[0].scale_x = 100.0
        styles[0].scale_y = 100.0
        window.command_manager.execute(ReplaceASSHeaderCommand(
            window.document,
            metadata=window.document.metadata,
            aegisub_project_garbage=getattr(
                window.document, "aegisub_project_garbage", {}),
            styles=styles,
        ))
        window._document_mutated()  # what the styles dialog calls after saving

        assert all(i.code != "style.small_scale" for i in window.compat_issues)

    def test_undo_refreshes_compat(self, window, tmp_path):
        # Undoing a fix must bring the issue back to the panel, not just to
        # the document.
        _open(window, tmp_path, "undo.ass", ASS_CONTENT)
        issue = next(i for i in window.compat_issues
                     if i.code == "color.unknown_format")
        window._apply_compat_fix(issue)
        assert all(i.code != "color.unknown_format"
                   for i in window.compat_issues)

        window._on_undo(None, None)

        assert any(i.code == "color.unknown_format"
                   for i in window.compat_issues)

    def test_entry_removal_refreshes_compat(self, window, tmp_path):
        # The blur issue lives on entry 1; deleting that entry must drop the
        # issue from the panel.
        _open(window, tmp_path, "rm.ass", ASS_CONTENT)
        assert any(i.fix and i.fix.get("kind") == "blur"
                   for i in window.compat_issues)

        window.subtitle_list.select_entry(0)
        window._on_remove_entry(None, None)

        assert all(not (i.fix and i.fix.get("kind") == "blur")
                   for i in window.compat_issues)

    def test_compat_toggle_recomputes_stale_issues(self, window, tmp_path):
        # Safety net: entering the Compatibility page always recomputes, so
        # not even an out-of-band change can leave stale results on screen.
        _open(window, tmp_path, "toggle.ass", ASS_CONTENT)
        window.document.styles[0].primary_color = "&H00FFFFFF"
        assert any(i.code == "color.unknown_format"
                   for i in window.compat_issues)  # stale on purpose

        # The header badge mirrors the issue count before the page opens.
        assert window.compat_btn.get_sensitive() is True
        assert window.compat_badge.get_visible() is True
        assert window.compat_badge.get_text() == str(len(window.compat_issues))

        window._on_compat_toggle(window.compat_btn)

        assert window.content_stack.get_visible_child_name() == "compatibility"
        assert all(i.code != "color.unknown_format"
                   for i in window.compat_issues)
        # On the page the button becomes a back button without a badge.
        assert window.compat_btn.get_sensitive() is True
        assert window.compat_badge.get_visible() is False
        assert window.compat_btn.get_tooltip_text() == "Back to Editor"

        # Leave the window on the editor page for the tests that follow.
        window._on_compat_toggle(window.compat_btn)
        assert window.content_stack.get_visible_child_name() == "main"

    def test_badge_caps_at_9_plus(self, window):
        original_issues = window.compat_issues
        original_document = window.document
        try:
            window.content_stack.set_visible_child_name("main")
            window.document = (original_document if original_document is not None
                               else object())
            window.compat_issues = [object()] * 10
            window._update_compat_button()
            assert window.compat_btn.get_sensitive() is True
            assert window.compat_badge.get_visible() is True
            assert window.compat_badge.get_text() == "9+"
        finally:
            window.compat_issues = original_issues
            window.document = original_document
            window._update_compat_button()


@pytest.mark.integration
class TestBatchConfirmDialog:
    """The confirmation dialog the window shows before applying batch ops."""

    @staticmethod
    def _make(window, summary=("Shift times by 500 ms",), file_count=4,
              selected=2, fmt="ASS"):
        from gsub.widgets.batch_confirm_dialog import (
            BatchConfirmDialog,
        )

        return BatchConfirmDialog(
            window,
            file_count=file_count,
            operation_summary=list(summary),
            selected_count=selected,
            format_name=fmt,
        )

    @staticmethod
    def _summary_rows(dialog):
        """ActionRows of the summary group (iteration yields internal boxes)."""
        found = []

        def _walk(widget):
            if isinstance(widget, Adw.ActionRow):
                found.append(widget)
                return
            child = widget.get_first_child()
            while child is not None:
                _walk(child)
                child = child.get_next_sibling()

        _walk(dialog.summary_group)
        return found

    def test_summary_rows_and_counts(self, window):
        dialog = self._make(window)

        rows = self._summary_rows(dialog)
        assert len(rows) == 1
        assert rows[0].get_title() == "Shift times by 500 ms"
        assert dialog.summary_group.get_description() == (
            "Applying to 2 of 4 ASS files")
        assert dialog.files_label.get_label() == "2 files will be modified"

    def test_no_operations_summary(self, window):
        dialog = self._make(window, summary=())

        rows = self._summary_rows(dialog)
        assert [row.get_title() for row in rows] == ["No operations configured"]

    def test_singular_counts(self, window):
        dialog = self._make(window, summary=("x",), file_count=1, selected=1)

        assert dialog.summary_group.get_description() == (
            "Applying to 1 of 1 ASS file")
        assert dialog.files_label.get_label() == "1 file will be modified"

    def test_apply_confirms_and_cancel_does_not(self, window):
        dialog = self._make(window)
        assert dialog.is_confirmed() is False

        dialog.on_apply(None)
        assert dialog.is_confirmed() is True

        other = self._make(window)
        other.on_cancel_clicked(None)
        assert other.is_confirmed() is False


@pytest.mark.integration
@pytest.mark.parametrize("extension", ["srt", "ass"])
def test_real_editing_example_opens_checks_replaces_and_saves(window, tmp_path, extension):
    from pathlib import Path

    from gsub.quality import QualitySettings
    from gsub.search import visible_text

    path = Path(__file__).resolve().parent.parent / "examples" / f"editing_tools_test.{extension}"
    original = path.read_text(encoding="utf-8")
    config = window._load_config()
    config["quality_settings"] = QualitySettings().to_dict()
    window._save_config(config)
    window.open_file(Gio.File.new_for_path(str(path)))
    _pump()
    window._on_quality_check(None, None)
    quality = window._quality_dialog
    try:
        assert len(quality.issues) == 10
    finally:
        window._close_document_dialogs()

    _select(window, 15)
    window._on_replace(None, None)
    dialog = window._replace_dialog
    try:
        dialog.search_entry.set_text("ticket")
        assert len(dialog.matches) == 7
        dialog.selection_only.set_active(True)
        dialog.whole_words.set_active(True)
        assert len(dialog.matches) == 3
        dialog.replace_entry.set_text("pass")
        dialog._replace_all()
        assert visible_text(window.document.entries[15].text, window.document.format) == (
            "pass, pass, pass; tickets.")
        output = tmp_path / f"edited.{extension}"
        window._save_document(str(output))
        assert output.exists()
        window._on_undo(None, None)
        assert visible_text(window.document.entries[15].text, window.document.format) == (
            "Ticket, ticket, TICKET; tickets.")
        window._on_redo(None, None)
        assert visible_text(window.document.entries[15].text, window.document.format) == (
            "pass, pass, pass; tickets.")
    finally:
        window._close_document_dialogs()
    assert path.read_text(encoding="utf-8") == original


@pytest.mark.integration
class TestEditingTools:
    @pytest.mark.parametrize("action", ["insert-above", "remove-entry", "duplicate-entry",
                                       "move-up", "move-down", "sort-by-time"])
    def test_structural_actions_flush_pending_edits_to_original_cue(
            self, window, tmp_path, action):
        _open(window, tmp_path, "pending.srt", SRT_CONTENT)
        _select(window, 1)
        window.editor_panel.text_buffer.set_text("Pending edit")
        window.editor_panel.start_milli.set_value(600)
        window.lookup_action(action).activate(None)
        if action == "remove-entry":
            assert [e.text for e in window.document.entries] == ["First subtitle", "Third subtitle"]
            window._on_undo(None, None)
        edited = [entry for entry in window.document.entries if entry.text == "Pending edit"]
        assert edited
        if action == "duplicate-entry":
            assert [entry.start_time.total_milliseconds for entry in edited] == [2600, 5100]
            assert edited[1].duration_ms == 2400
        else:
            assert all(entry.start_time.total_milliseconds == 2600 for entry in edited)
        assert window.document.entries[-1].text != "Pending edit" or action == "move-down"
        _pump()
        assert window.editor_panel._pending_timing_values is None

    def test_multiselect_commits_current_draft_before_disabling_editor(self, window, tmp_path):
        _open(window, tmp_path, "multiselect.srt", SRT_CONTENT)
        _select(window, 0)
        window.editor_panel.text_buffer.set_text("Keep this edit")
        window.editor_panel.start_milli.set_value(600)
        window.subtitle_list.select_entry(1, clear_others=False)
        _pump()
        assert window.document.entries[0].text == "Keep this edit"
        assert window.document.entries[0].start_time.total_milliseconds == 600
        assert window.document.entries[1].text == "Second subtitle"
        assert not window.editor_panel.get_sensitive()

    def test_format_conversion_flushes_draft_and_discards_old_document_history(self, window, tmp_path):
        _open(window, tmp_path, "convert.srt", SRT_CONTENT)
        _select(window, 0)
        window.editor_panel.text_buffer.set_text("Converted draft")
        window._on_convert_response("convert", SubtitleFormat.ASS)
        assert window.document.entries[0].text == "Converted draft"
        assert window.document.format == SubtitleFormat.ASS
        assert not window.command_manager.can_undo()

    def test_save_as_conversion_flushes_and_updates_preview_document(self, window, tmp_path):
        from types import SimpleNamespace

        _open(window, tmp_path, "before.srt", SRT_CONTENT)
        _select(window, 0)
        window.editor_panel.text_buffer.set_text("Saved draft")
        output = tmp_path / "after.ass"
        chooser = SimpleNamespace(save_finish=lambda _result: Gio.File.new_for_path(str(output)))
        window._on_save_as_response(chooser, None)
        assert output.exists()
        assert "Saved draft" in output.read_text()
        assert window.video_player.document is window.document
        assert not window.command_manager.can_undo()

    def test_split_flushes_pending_text_and_roundtrips(self, window, tmp_path):
        _open(window, tmp_path, "split.srt", SRT_CONTENT)
        _select(window, 0)
        window.editor_panel.text_buffer.set_text("Hello world")
        window.editor_panel.text_buffer.place_cursor(
            window.editor_panel.text_buffer.get_iter_at_offset(5))
        window._on_split_entry(None, None)
        assert [e.text for e in window.document.entries[:2]] == ["Hello", "world"]
        assert len(window.document.entries) == 4
        window._on_undo(None, None)
        assert len(window.document.entries) == 3
        assert window.document.entries[0].text == "Hello world"
        window._on_redo(None, None)
        assert [e.text for e in window.document.entries[:2]] == ["Hello", "world"]

    def test_split_uses_video_position_when_inside_cue(self, window, tmp_path):
        _open(window, tmp_path, "playhead.srt", SRT_CONTENT)
        _select(window, 0)
        window.current_video_file = "preview.mp4"
        window.video_player.position = 1.2
        try:
            window.editor_panel.text_buffer.place_cursor(
                window.editor_panel.text_buffer.get_iter_at_offset(5))
            window._on_split_entry(None, None)
            assert window.document.entries[0].end_time.total_milliseconds == 1200
            assert window.document.entries[1].start_time.total_milliseconds == 1200
        finally:
            window.current_video_file = None

    def test_merge_selection_and_undo(self, window, tmp_path):
        _open(window, tmp_path, "merge.srt", SRT_CONTENT)
        _select(window, 0)
        window.subtitle_list.select_entry(1, clear_others=False)
        _pump()
        assert window.lookup_action("merge-entries").get_enabled()
        assert not window.lookup_action("split-entry").get_enabled()
        window._on_merge_entries(None, None)
        assert len(window.document.entries) == 2
        assert window.document.entries[0].text == "First subtitle\nSecond subtitle"
        assert window.document.entries[0].end_time.total_milliseconds == 5000
        window._on_undo(None, None)
        assert [e.text for e in window.document.entries] == [
            "First subtitle", "Second subtitle", "Third subtitle"]

    def test_rebalance_and_replace_are_independent_undo_steps(self, window, tmp_path):
        from gsub.search import build_replace_command, find_matches

        text = "This is a much longer subtitle that needs a balanced line break for comfortable reading"
        _open(window, tmp_path, "rebalance.srt", SRT_CONTENT.replace("First subtitle", text))
        _select(window, 0)
        window._on_rebalance_text(None, None)
        balanced = window.document.entries[0].text
        assert len(balanced.splitlines()) == 2
        command = build_replace_command(window.document, find_matches(window.document, "subtitle"), "caption")
        window._execute_edit_command(command)
        assert "caption" in window.document.entries[0].text
        window._on_undo(None, None)
        assert window.document.entries[0].text == balanced
        window._on_undo(None, None)
        assert window.document.entries[0].text == text

    def test_quality_action_saves_limits_and_navigates(self, window, tmp_path):
        _open(window, tmp_path, "quality.srt", SRT_CONTENT)
        window._on_quality_check(None, None)
        dialog = window._quality_dialog
        assert dialog.document is window.document
        dialog.max_cps_row.set_value(1)
        assert window._load_config()["quality_settings"]["max_cps"] == 1
        assert any(issue.code == "text.reading_speed" for issue in dialog.issues)
        window.current_video_file = "preview.mp4"
        try:
            dialog._on_issue_activated(None, 1)
            assert window.subtitle_list.get_selected_position() == 1
            assert window.video_player.position == 2.5
        finally:
            window.current_video_file = None
            window._close_document_dialogs()

    def test_find_replace_action_flushes_and_preserves_selection_scope(self, window, tmp_path):
        _open(window, tmp_path, "replace.srt", SRT_CONTENT)
        _select(window, 0)
        window.editor_panel.text_buffer.set_text("First First")
        window._on_replace(None, None)
        dialog = window._replace_dialog
        try:
            assert dialog.selected_positions == (0,)
            dialog.search_entry.set_text("First")
            dialog.replace_entry.set_text("Changed")
            dialog.selection_only.set_active(True)
            dialog._replace_all()
            assert window.document.entries[0].text == "Changed Changed"
            window._on_undo(None, None)
            assert window.document.entries[0].text == "First First"
            assert len(dialog.matches) == 2
        finally:
            window._close_document_dialogs()


@pytest.mark.integration
class TestBatchUndoRedo:
    @staticmethod
    def _prepare(window, tmp_path, content=SRT_CONTENT, suffix="srt"):
        window.batch_file_list.clear()
        window.batch_operations.reset()
        paths = [_write(tmp_path, f"batch{i}.{suffix}", content) for i in range(2)]
        window._add_batch_files([Gio.File.new_for_path(path) for path in paths])
        window._navigate_to_batch()
        return window.batch_file_list.get_all_files()

    @staticmethod
    def _apply(window, offset):
        from types import SimpleNamespace

        window.batch_operations.offset_row.set_value(offset)
        window._on_batch_confirm_closed(SimpleNamespace(is_confirmed=lambda: True),
                                        window.batch_file_list.get_selected_files())

    def test_batch_roundtrip_is_separate_from_editor_history(self, window, tmp_path):
        _open(window, tmp_path, "editor.srt", SRT_CONTENT)
        _select(window, 0)
        window._on_text_changed(None, 0, "Editor change")
        items = self._prepare(window, tmp_path)
        self._apply(window, -1000)
        assert all(it.document.entries[0].start_time.total_milliseconds == 0 for it in items)
        assert window.batch_undo_button.get_sensitive()
        window._on_undo(None, None)
        assert all(it.document.entries[0].start_time.total_milliseconds == 500 for it in items)
        assert not any(it.modified or it.document.modified for it in items)
        assert window.document.entries[0].text == "Editor change"
        assert window.batch_redo_button.get_sensitive()
        window._on_redo(None, None)
        assert all(it.modified for it in items)
        window._navigate_to_editor()
        window._on_undo(None, None)
        assert window.document.entries[0].text == "First subtitle"
        assert all(it.modified for it in items)

    def test_batch_undo_after_save_marks_modified_and_redo_returns_clean(self, window, tmp_path):
        items = self._prepare(window, tmp_path)
        self._apply(window, 1000)
        window._on_batch_save_all()
        assert not any(it.modified for it in items)
        window._on_undo(None, None)
        assert all(it.modified for it in items)
        # Undo changes in-memory subtitles; explicit saves control disk writes.
        assert all("00:00:01,500" in open(it.file_path).read() for it in items)
        window._on_redo(None, None)
        assert not any(it.modified for it in items)

    def test_batch_selection_and_removal_history_boundary(self, window, tmp_path):
        items = self._prepare(window, tmp_path)
        items[1].selected = False
        self._apply(window, 1000)
        assert items[0].modified and not items[1].modified
        window._on_undo(None, None)
        self._apply(window, 2000)
        assert not window.batch_command_manager.can_redo()
        window.batch_file_list.remove_file(items[1])
        assert not window.batch_command_manager.can_undo()
        assert not window.lookup_action("undo").get_enabled()
        window._navigate_to_editor()

    def test_batch_modified_badge_tracks_undo(self, window, tmp_path):
        from gsub.widgets.batch_file_list import BatchFileRow

        items = self._prepare(window, tmp_path)
        row = BatchFileRow()
        row.bind(items[0], lambda _item: None)
        assert not row.modified_icon.get_visible()
        self._apply(window, 1000)
        assert row.modified_icon.get_visible()
        window._on_undo(None, None)
        assert not row.modified_icon.get_visible()
        row.unbind()
        window._navigate_to_editor()

    def test_ass_batch_undo_restores_style_resolution_and_timing(self, window, tmp_path):
        import copy

        items = self._prepare(window, tmp_path, ASS_CONTENT, "ass")
        original = [copy.deepcopy(it.document) for it in items]
        panel = window.batch_operations
        panel.res_enable_switch.set_active(True)
        panel.res_width_row.set_value(1920)
        panel.res_height_row.set_value(1080)
        panel.style_props.fontsize_check.set_active(True)
        panel.style_props.fontsize_row.set_value(42)
        self._apply(window, 1000)
        for it in items:
            assert it.document.metadata["PlayResX"] == "1920"
            assert it.document.styles[0].fontsize == 42
            assert it.document.entries[0].start_time.total_milliseconds == 2000
        window._on_undo(None, None)
        assert [it.document for it in items] == original
        window._on_redo(None, None)
        assert all(it.document.styles[0].fontsize == 42 for it in items)
        window._navigate_to_editor()


@pytest.mark.integration
class TestBatchRenameDialog:
    """The naming-pattern dialog shown before batch "Save All As…" writes."""

    @staticmethod
    def _make(window, filenames=("ep01.srt", "ep02.srt")):
        from gsub.widgets.batch_rename_dialog import BatchRenameDialog

        return BatchRenameDialog(window, filenames=list(filenames))

    @staticmethod
    def _row_titles(dialog):
        found = []

        def _walk(widget):
            if isinstance(widget, Adw.ActionRow):
                found.append(widget.get_title())
                return
            child = widget.get_first_child()
            while child is not None:
                _walk(child)
                child = child.get_next_sibling()

        _walk(dialog.preview_group)
        return found

    def test_default_pattern_keeps_names_and_enables_save(self, window):
        dialog = self._make(window)

        assert dialog.get_output_names() == ["ep01.srt", "ep02.srt"]
        assert dialog.save_button.get_sensitive() is True
        assert self._row_titles(dialog) == ["ep01.srt", "ep02.srt"]

    def test_pattern_edit_updates_preview(self, window):
        dialog = self._make(window)

        dialog.pattern_row.set_text("test file S01E")
        assert dialog.get_output_names() == [
            "test file S01E01.srt", "test file S01E02.srt"]

        titles = self._row_titles(dialog)
        assert titles == ["test file S01E01.srt", "test file S01E02.srt"]

    def test_pattern_with_placeholder_substitutes(self, window):
        dialog = self._make(window)

        dialog.pattern_row.set_text("{name}_fixed")
        assert dialog.get_output_names() == ["ep01_fixed.srt", "ep02_fixed.srt"]

    def test_colliding_names_block_save(self, window):
        dialog = self._make(window, filenames=("ep01.srt", "ep01.srt"))

        # Same original basename twice -> identical expanded names.
        dialog.pattern_row.set_text("{name}")
        assert dialog.save_button.get_sensitive() is False

        # Numbered base names are unique even for duplicate basenames.
        dialog.pattern_row.set_text("test file")
        assert dialog.save_button.get_sensitive() is True

    def test_long_batches_are_summarized(self, window):
        names = [f"ep{i:02d}.srt" for i in range(10)]
        dialog = self._make(window, filenames=names)

        titles = self._row_titles(dialog)
        assert len(titles) == dialog.PREVIEW_LIMIT + 1
        assert titles[-1] == "…and 2 more"

    def test_save_confirms_and_cancel_does_not(self, window):
        dialog = self._make(window)
        assert dialog.is_confirmed() is False

        dialog.on_save(None)
        assert dialog.is_confirmed() is True

        other = self._make(window)
        other.on_cancel_clicked(None)
        assert other.is_confirmed() is False
