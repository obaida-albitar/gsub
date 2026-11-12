"""Timestamp navigation, asynchronous seek feedback and proofreading in GTK.

Most cases use a recording media backend with the actual window, popover and
timeline. The native-media cases also decode a generated 25 fps test video.
"""

from copy import deepcopy
from pathlib import Path
import shutil
import subprocess
import time

import pytest

from gsub.resources import register_resources

try:
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, Gio, GLib, Gtk
    register_resources()
    Gtk.init()
    Adw.init()
    if Gdk.Display.get_default() is None:
        pytest.skip("no display available for GTK integration tests", allow_module_level=True)
    from gsub.window import GsubWindow
except ImportError as error:
    pytest.skip(str(error), allow_module_level=True)


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
# Native GTK keeps application signal closures after window teardown; retain
# the Python wrappers while later modules create their application windows.
_APPLICATIONS = []


def pump():
    context = GLib.MainContext.default()
    for _ in range(12):
        context.iteration(False)


def wait_until(condition, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pump()
        if condition():
            return True
        time.sleep(0.01)
    pump()
    return bool(condition())


def descendants(widget):
    yield widget
    child = widget.get_first_child()
    while child is not None:
        yield from descendants(child)
        child = child.get_next_sibling()


class RecordingMedia:
    """Intentionally asynchronous: a seek request does not change time_pos."""

    def __init__(self):
        self.pause = True
        self.time_pos = 1.0
        self.seeking = False
        self.speed = 1.0
        self.ab_loop_a = self.ab_loop_b = "no"
        self.sid = False
        self.track_list = []
        self.seek_calls = []
        self.commands = []

    def seek(self, position, **kwargs):
        self.seek_calls.append((position, kwargs))

    def command(self, *args):
        self.commands.append(args)
        if args[0] in ("frame-step", "frame-back-step"):
            self.pause = True

    def loadfile(self, path):
        self.time_pos = 0.0


@pytest.fixture(scope="module")
def navigation_window(tmp_path_factory):
    directory = tmp_path_factory.mktemp("navigation-config")
    directory.mkdir(exist_ok=True)
    original = GsubWindow._get_config_dir
    GsubWindow._get_config_dir = lambda _self: str(directory)
    app = Adw.Application(application_id="io.github.obaidaalbitar.gsub.navigation-tests",
                          flags=Gio.ApplicationFlags.NON_UNIQUE)
    app.register(None)
    _APPLICATIONS.append(app)
    win = GsubWindow(application=app)
    win._stop_recovery_timer()
    win.errors, win.toasts = [], []
    win._show_error = win.errors.append
    win._show_toast = win.toasts.append
    native_engine = win.video_player._mpv
    # Map the actual GLArea using its native engine before replacing only the
    # command backend. Popup tests then exercise a properly mapped GTK anchor.
    win.current_video_file = "navigation.mp4"
    win._navigate_to_editor()
    win.video_button.set_active(True)
    win.present()
    assert wait_until(win.video_player.video_area.get_realized)
    pump()
    try:
        yield win
    finally:
        win._stop_recovery_timer()
        win.video_player._cancel_pending_seek()
        win.video_player.clear_cue_playback(pause=True)
        win.video_player._mpv = native_engine
        win.destroy()
        GsubWindow._get_config_dir = original
        pump()


@pytest.fixture
def window(navigation_window):
    win = navigation_window
    win.editor_panel.flush_pending_changes()
    win._close_document_dialogs()
    player = win.video_player
    player.timestamp_popover.popdown()
    player.clear_cue_playback(pause=True)
    player._cancel_pending_seek()
    player._mpv = RecordingMedia()
    player._disposed = False
    player._pending_load_path = None
    player._video_path = "navigation.mp4"
    player.document = None
    player._timeline_scrubbing = False
    win.current_video_file = "navigation.mp4"
    win.current_file = None
    win.document = None
    win.subtitle_list.set_document(None)
    win.editor_panel.clear()
    win._navigate_to_editor()
    win.video_button.set_active(True)
    player._set_duration(10.0)
    player._publish_position(1.0)
    player._set_pause_ui(True)
    win._update_document_actions()
    win.errors.clear()
    win.toasts.clear()
    pump()
    return win


def open_example(win, tmp_path):
    path = tmp_path / "navigation.srt"
    path.write_bytes((EXAMPLES / "editing_tools_test.srt").read_bytes())
    assert win._open_file_now(Gio.File.new_for_path(str(path)))
    return path


def test_quality_check_has_one_toolbar_button_and_consistent_panel_title(window, tmp_path):
    open_example(window, tmp_path)
    buttons = [widget for widget in descendants(window) if isinstance(widget, Gtk.Button)
               and widget.get_action_name() == "win.quality-check"]
    assert len(buttons) == 1
    assert buttons[0].get_tooltip_text() == "Subtitle Quality Check (Ctrl+Shift+Q)"
    buttons[0].emit("clicked")
    assert window.review_stack.get_visible_child_name() == "quality"
    labels = [widget.get_label() for widget in descendants(window._quality_dialog)
              if isinstance(widget, Gtk.Label)]
    assert "Subtitle Quality Check" in labels


def test_quality_hide_and_reopen_preserves_review_context(window, tmp_path):
    open_example(window, tmp_path)
    window.lookup_action("quality-check").activate(None)
    panel = window._quality_dialog
    panel._ignore_current()
    ignored = panel.review.ignored_count
    assert ignored == 1
    panel.close()
    assert window.review_stack.get_visible_child_name() == "subtitles"
    window.lookup_action("quality-check").activate(None)
    assert window._quality_dialog is panel
    assert panel.review.ignored_count == ignored
    assert window.review_stack.get_visible_child_name() == "quality"


def test_go_to_time_action_works_without_document_or_selection(window):
    assert window.document is None
    assert window.subtitle_list.get_selected_positions() == []
    assert window.lookup_action("go-to-time").get_enabled()
    assert not window.lookup_action("set-start-here").get_enabled()
    window.lookup_action("go-to-time").activate(None)
    assert wait_until(window.video_player.timestamp_popover.get_visible)
    assert window.video_player.timestamp_popover.entry.get_text() == "00:00:01.000"


def test_go_to_time_shortcut_reveals_hidden_preview_from_batch(window):
    window._navigate_to_batch()
    window.video_button.set_active(False)
    assert not window.video_visible
    window.lookup_action("go-to-time").activate(None)
    assert wait_until(window.video_player.timestamp_popover.get_visible)
    assert window.current_view == "editor"
    assert window.video_visible
    assert window.video_container.get_visible()


def test_no_video_disables_go_to_time_and_time_button(window):
    window.current_video_file = None
    window.video_player._video_path = None
    window.video_player._set_duration(0.0)
    window._update_selection_actions()
    assert not window.lookup_action("go-to-time").get_enabled()
    assert not window.video_player.time_button.get_sensitive()
    assert not window.video_player.show_timestamp_navigation()


def test_pending_load_cannot_open_timestamp_popover(window):
    player = window.video_player
    player._pending_load_path = "next.mp4"
    player._set_duration(0.0)
    assert not player.show_timestamp_navigation()
    window._on_go_to_time(None, None)
    assert not player.timestamp_popover.get_visible()
    assert "loading" in window.toasts[-1]
    assert player._mpv.seek_calls == []


@pytest.mark.parametrize("text", ["", "bad", "nan", "-0:01", "1:60", "0:00:60",
                                  "1:2:3:4", "0:10.001"])
def test_invalid_timestamp_does_not_seek_or_move_marker(window, text):
    player = window.video_player
    assert player.show_timestamp_navigation()
    popover = player.timestamp_popover
    popover.entry.set_text(text)
    popover.entry.emit("activate")
    assert not popover.submit()
    assert player._mpv.seek_calls == []
    assert player._timeline.model.position == 1.0
    assert player.time_label.get_text() == "0:01.000"
    assert popover.error_label.get_visible()
    assert popover.entry.get_editable()
    assert popover.entry.get_text() == text


@pytest.mark.parametrize("text", ["2.345", "0:02.345", "00:00:02,345"])
@pytest.mark.parametrize("paused", [True, False])
def test_timestamp_enter_seeks_without_changing_pause_or_document(window, tmp_path, text, paused):
    open_example(window, tmp_path)
    entries = deepcopy(window.document.entries)
    player = window.video_player
    player._mpv.pause = paused
    player._set_pause_ui(paused)
    assert player.show_timestamp_navigation()
    player.timestamp_popover.entry.set_text(text)
    player.timestamp_popover.entry.emit("activate")
    assert player._mpv.seek_calls[-1][0] == pytest.approx(2.345)
    assert player._mpv.pause is paused
    assert player.time_label.get_text() == "0:02.345"
    assert player._timeline.model.position == pytest.approx(2.345)
    assert not player.timestamp_popover.get_visible()
    assert window.document.entries == entries
    assert not window.document.modified
    assert not window.command_manager.can_undo()


def test_timestamp_target_is_not_replaced_by_playback_updates(window):
    player = window.video_player
    assert player.show_timestamp_navigation()
    player.timestamp_popover.entry.set_text("0:07.500")
    player._mpv.time_pos = 2.0
    player._update_position_ui(2.0)
    assert player.timestamp_popover.entry.get_text() == "0:07.500"
    # Repeated Ctrl+G should preserve a target that is already being edited.
    window.lookup_action("go-to-time").activate(None)
    assert player.timestamp_popover.entry.get_text() == "0:07.500"


def test_failed_native_seek_keeps_timestamp_popover_and_actual_position(window, monkeypatch):
    player = window.video_player
    assert player.show_timestamp_navigation()
    player.timestamp_popover.entry.set_text("4.5")

    def fail_seek(*_args, **_kwargs):
        raise RuntimeError("Backend refused seek")

    monkeypatch.setattr(player._mpv, "seek", fail_seek)
    assert player.timestamp_popover.submit() is False
    assert player.timestamp_popover.get_visible()
    assert player.timestamp_popover.error_label.get_visible()
    assert player._timeline.model.position == 1.0
    assert player.time_label.get_text() == "0:01.000"
    assert player._pending_seek is None


def test_rapid_nudge_actions_accumulate_before_backend_completes(window):
    for _ in range(3):
        window.lookup_action("seek-nudge-forward").activate(None)
    assert [target for target, _ in window.video_player._mpv.seek_calls] == pytest.approx(
        [1.1, 1.2, 1.3])
    assert window.video_player._timeline.model.position == pytest.approx(1.3)
    assert window.video_player.time_label.get_text() == "0:01.300"


def test_paused_seek_publishes_marker_then_reconciles_actual_decoded_frame(window):
    player = window.video_player
    assert player.seek(3.167)
    generation = player._seek_generation
    assert player.time_label.get_text() == "0:03.167"
    assert player._timeline.model.position == pytest.approx(3.167)
    player._mpv.seeking = True
    player._poll_seek_completion(generation)
    player._mpv.time_pos = 3.16
    player._mpv.seeking = False
    assert not player._poll_seek_completion(generation)
    assert player.time_label.get_text() == "0:03.160"
    assert player._timeline.model.position == pytest.approx(3.16)
    assert player._mpv.pause is True
    assert player._seek_poll_id is None


def test_stale_queued_observer_cannot_rewind_latest_paused_seek(window):
    player = window.video_player
    assert player.seek(2.5)
    generation = player._seek_generation
    old_serial = player._position_event_serial
    assert player.seek(4.25)
    player._update_position_ui(1.0, generation=generation, serial=old_serial)
    assert player.time_label.get_text() == "0:04.250"
    assert player._timeline.model.position == pytest.approx(4.25)


def test_video_switch_cancels_pending_poll_and_discards_old_observer(window):
    player = window.video_player
    assert player.seek(8.0)
    old_generation, old_poll = player._seek_generation, player._seek_poll_id
    assert GLib.MainContext.default().find_source_by_id(old_poll) is not None
    player.load_video("next-video.mp4")
    assert player._seek_generation != old_generation
    assert player._pending_seek is None and player._seek_poll_id is None
    assert GLib.MainContext.default().find_source_by_id(old_poll) is None
    player._update_position_ui(8.0, generation=old_generation)
    assert player._timeline.model.position == 0.0
    assert player.time_label.get_text() == "0:00.000"
    assert not player.time_button.get_sensitive()


def test_video_switch_discards_queued_duration_and_pause_from_previous_media(window):
    player = window.video_player
    player._on_mpv_duration("duration", 42.0)
    player._on_mpv_pause("pause", False)
    player.load_video("new-loading-video.mp4")
    assert player._duration == 0.0
    assert not player.time_button.get_sensitive()
    pump()
    assert player._duration == 0.0
    assert not player.time_button.get_sensitive()
    assert player.play_button.get_icon_name() == "media-playback-start-symbolic"
    assert player._mpv.pause is True


def test_timestamp_navigation_clears_cue_loop_and_poll_without_pausing(window, tmp_path):
    open_example(window, tmp_path)
    window.subtitle_list.select_entry(0)
    player = window.video_player
    assert player.play_selected_cue(loop=True)
    loop_poll = player._cue_poll_id
    assert loop_poll is not None and player.cue_looping
    player._mpv.pause = False
    assert player.show_timestamp_navigation()
    player.timestamp_popover.entry.set_text("4.25")
    assert player.timestamp_popover.submit()
    assert not player.cue_looping
    assert player._cue_poll_id is None
    assert player._mpv.ab_loop_a == "no" and player._mpv.ab_loop_b == "no"
    assert player._mpv.pause is False
    assert GLib.MainContext.default().find_source_by_id(loop_poll) is None


@pytest.fixture(scope="module")
def native_media(tmp_path_factory):
    executable = shutil.which("ffmpeg")
    if executable is None:
        pytest.skip("ffmpeg is required to generate the native playback fixture")
    path = tmp_path_factory.mktemp("native-navigation") / "25fps.mp4"
    subprocess.run([executable, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=25", "-t", "8", "-an",
        "-c:v", "mpeg4", "-q:v", "4", str(path)], check=True, timeout=30)
    return path


@pytest.fixture(scope="module")
def native_window(tmp_path_factory, native_media):
    directory = tmp_path_factory.mktemp("native-navigation-config")
    original = GsubWindow._get_config_dir
    GsubWindow._get_config_dir = lambda _self: str(directory)
    app = Adw.Application(application_id="io.github.obaidaalbitar.gsub.native-navigation-tests",
                          flags=Gio.ApplicationFlags.NON_UNIQUE)
    app.register(None)
    _APPLICATIONS.append(app)
    win = GsubWindow(application=app)
    win.errors, win.toasts = [], []
    win._show_error = win.errors.append
    win._show_toast = win.toasts.append
    win._stop_recovery_timer()
    win.present()
    win.video_player._mpv.ao = "null"
    win.load_video_path(str(native_media))
    assert wait_until(lambda: win.video_player._duration > 7.9)
    assert win.video_player.video_area.get_realized()
    assert win.video_player._mpv.pause
    try:
        yield win
    finally:
        win._stop_recovery_timer()
        win.destroy()
        GsubWindow._get_config_dir = original
        pump()


def test_native_paused_timestamp_seek_updates_readout_and_timeline(native_window):
    win, player = native_window, native_window.video_player
    assert win.document is None
    win.lookup_action("go-to-time").activate(None)
    assert wait_until(player.timestamp_popover.get_visible)
    player.timestamp_popover.entry.set_text("0:03.167")
    assert player.timestamp_popover.submit()
    assert wait_until(lambda: player._pending_seek is None)
    actual = float(player._mpv.time_pos)
    assert actual == pytest.approx(3.167, abs=0.05)
    assert player._mpv.pause
    assert player._timeline.model.position == pytest.approx(actual, abs=0.001)
    assert player.time_label.get_text() == player._format_time(actual)


@pytest.mark.parametrize("back", [False, True])
def test_native_frame_step_finishes_at_same_position_as_readout_and_timeline(native_window, back):
    player = native_window.video_player
    assert player.seek(4.0)
    assert wait_until(lambda: player._pending_seek is None)
    before = float(player._mpv.time_pos)
    player.frame_step(back=back)
    assert wait_until(lambda: abs(float(player._mpv.time_pos) - before) > 0.001)
    assert wait_until(lambda: abs(player._timeline.model.position - float(player._mpv.time_pos)) < 0.001)
    actual = float(player._mpv.time_pos)
    assert actual == pytest.approx(before + (-0.04 if back else 0.04), abs=0.002)
    assert player.time_label.get_text() == player._format_time(actual)
    assert player._mpv.pause


def test_native_rapid_nudges_and_video_switch_do_not_leave_stale_seek_feedback(native_window, native_media):
    win, player = native_window, native_window.video_player
    assert player.seek(2.0)
    assert wait_until(lambda: player._pending_seek is None)
    for _ in range(4):
        win.lookup_action("seek-nudge-forward").activate(None)
    assert wait_until(lambda: player._pending_seek is None)
    assert float(player._mpv.time_pos) == pytest.approx(2.4, abs=0.05)
    old_generation = player._seek_generation
    assert player.seek(7.0)
    player.load_video(str(native_media))
    assert player._pending_seek is None
    assert player._seek_poll_id is None
    assert player._seek_generation > old_generation
    assert wait_until(lambda: player._duration > 7.9)
    assert wait_until(lambda: float(player._mpv.time_pos or 0) < 0.1)
    assert player._timeline.model.position < 0.1
