"""Real GTK input, validation and opening lifecycle for timestamp navigation."""

import pytest

from gsub.resources import register_resources

try:
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, GLib, Gtk
    register_resources()
    Gtk.init()
    Adw.init()
    HAS_DISPLAY = Gdk.Display.get_default() is not None
except Exception:
    HAS_DISPLAY = False

pytestmark = pytest.mark.skipif(not HAS_DISPLAY, reason="no display available for GTK tests")


def pump():
    context = GLib.MainContext.default()
    for _ in range(12):
        context.iteration(False)


@pytest.fixture
def navigation():
    from gsub.widgets.timestamp_popover import TimestampPopover

    settings = Gtk.Settings.get_default()
    animations = settings.get_property("gtk-enable-animations")
    settings.set_property("gtk-enable-animations", False)
    state = {"position": 83.456, "duration": 120.0, "paused": True}
    seeks, opens = [], []

    def seek(seconds):
        seeks.append(seconds)
        return True

    popover = TimestampPopover(seek, lambda: state["position"], lambda: state["duration"],
                               on_before_open=lambda: opens.append(True))
    window = Gtk.Window(default_width=400, default_height=180)
    button = Gtk.MenuButton(label="Current time")
    button.set_popover(popover)
    window.set_child(button)
    window.present()
    pump()
    yield popover, state, seeks, opens, button
    popover.popdown()
    window.destroy()
    pump()
    settings.set_property("gtk-enable-animations", animations)


def test_open_initializes_target_and_duration_once(navigation):
    popover, _state, seeks, opens, _button = navigation
    assert popover.open()
    pump()
    assert popover.get_visible()
    assert popover.entry.get_text() == "00:01:23.456"
    assert "00:02:00.000" in popover.duration_label.get_text()
    assert not popover.error_label.get_visible()
    assert opens == [True]
    assert seeks == []


def test_menu_button_popup_also_initializes_current_position(navigation):
    popover, state, _seeks, opens, button = navigation
    state["position"] = 12.5
    button.popup()
    pump()
    assert popover.entry.get_text() == "00:00:12.500"
    assert opens == [True]


def test_updates_and_repeated_open_do_not_replace_target_being_typed(navigation):
    popover, state, seeks, opens, _button = navigation
    popover.open()
    pump()
    popover.entry.set_text("1:45.2")
    state["position"] = 84.0
    pump()
    assert popover.open()
    assert popover.entry.get_text() == "1:45.2"
    assert seeks == []
    assert opens == [True]


def test_reopening_uses_new_actual_position_and_clears_old_errors(navigation):
    popover, state, _seeks, opens, _button = navigation
    popover.open()
    popover.entry.set_text("bad")
    assert not popover.submit()
    popover.popdown()
    pump()
    state["position"] = 91.234
    assert popover.open()
    pump()
    assert popover.entry.get_text() == "00:01:31.234"
    assert not popover.error_label.get_visible()
    assert opens == [True, True]


@pytest.mark.parametrize("text,expected", [("01:45.125", 105.125), ("100,5", 100.5),
                                         ("00:00:00", 0), ("2:00", 120)])
def test_valid_target_seeks_once_and_closes_popover(navigation, text, expected):
    popover, state, seeks, _opens, _button = navigation
    popover.open()
    pump()
    popover.entry.set_text(text)
    assert popover.submit()
    pump()
    assert seeks == [expected]
    assert not popover.get_visible()
    assert state["paused"] is True


def test_enter_submits_and_go_button_uses_same_validation(navigation):
    popover, _state, seeks, _opens, _button = navigation
    popover.open()
    popover.entry.set_text("10.25")
    popover.entry.emit("activate")
    pump()
    assert seeks == [10.25]
    popover.open()
    popover.entry.set_text("11.5")
    popover.go_button.emit("clicked")
    pump()
    assert seeks == [10.25, 11.5]


@pytest.mark.parametrize("text", ["bad", "-1", "00:60:00", "2:00.001", "", "NaN"])
def test_invalid_target_stays_editable_without_seeking(navigation, text):
    popover, _state, seeks, _opens, _button = navigation
    popover.open()
    pump()
    popover.entry.set_text(text)
    assert not popover.submit()
    assert seeks == []
    assert popover.get_visible()
    assert popover.entry.get_text() == text
    assert popover.error_label.get_visible()
    assert popover.error_label.get_text()
    popover.entry.set_text("12")
    assert not popover.error_label.get_visible()


def test_duration_is_rechecked_at_submission(navigation):
    popover, state, seeks, _opens, _button = navigation
    popover.open()
    popover.entry.set_text("90")
    state["duration"] = 60
    assert not popover.submit()
    assert seeks == []
    assert "beyond the end" in popover.error_label.get_text()
    assert "00:01:00.000" in popover.duration_label.get_text()


@pytest.mark.parametrize("failure", [False, RuntimeError("Player closed")])
def test_failed_seek_keeps_target_and_explains_failure(navigation, failure):
    popover, _state, seeks, _opens, _button = navigation

    def fail(_seconds):
        if isinstance(failure, Exception):
            raise failure
        return failure

    popover.on_seek = fail
    popover.open()
    popover.entry.set_text("20")
    assert not popover.submit()
    assert popover.get_visible()
    assert popover.entry.get_text() == "20"
    assert "Could not seek" in popover.error_label.get_text()
    assert seeks == []


def test_unknown_duration_allows_valid_target_without_fake_duration_label(navigation):
    popover, state, seeks, _opens, _button = navigation
    state["duration"] = None
    popover.open()
    assert not popover.duration_label.get_visible()
    popover.entry.set_text("999")
    assert popover.submit()
    assert seeks == [999]


def test_unavailable_duration_does_not_seek_without_validation(navigation):
    popover, _state, seeks, _opens, _button = navigation

    def unavailable():
        raise RuntimeError("Duration probe unavailable")

    popover.get_duration = unavailable
    popover.open()
    popover.entry.set_text("10")
    assert not popover.submit()
    assert seeks == []
    assert "duration is unavailable" in popover.error_label.get_text()


def test_unavailable_current_position_can_be_replaced_by_explicit_target(navigation):
    popover, _state, seeks, _opens, _button = navigation
    popover.get_position = lambda: None
    popover.open()
    assert popover.entry.get_text() == "00:00:00.000"
    assert "Current position is unavailable" in popover.error_label.get_text()
    popover.entry.set_text("12")
    assert popover.submit()
    assert seeks == [12]


def test_escape_closes_without_seeking_or_changing_target(navigation):
    popover, _state, seeks, _opens, _button = navigation
    popover.open()
    pump()
    popover.entry.set_text("45")
    assert popover._on_key_pressed(None, Gdk.KEY_Escape, 0, 0)
    pump()
    assert not popover.get_visible()
    assert popover.entry.get_text() == "45"
    assert seeks == []
    assert not popover._on_key_pressed(None, Gdk.KEY_a, 0, 0)


def test_before_open_can_reject_navigation_without_a_popup(navigation):
    popover, _state, seeks, _opens, _button = navigation
    popover.on_before_open = lambda: False
    assert not popover.open()
    assert not popover.get_visible()
    assert seeks == []


def test_native_menu_popup_also_honors_readiness_guard(navigation):
    popover, _state, seeks, _opens, button = navigation
    popover.on_before_open = lambda: False
    button.popup()
    pump()
    assert not popover.get_visible()
    assert seeks == []


@pytest.mark.parametrize("current,duration", [(1.1666667, 1.1666667),
                                           (1.1666, 1.16665), (1.1667, 1.1666)])
def test_generated_eof_target_does_not_round_past_known_duration(navigation, current, duration):
    popover, state, seeks, _opens, _button = navigation
    state["position"], state["duration"] = current, duration
    popover.open()
    assert popover.entry.get_text() == "00:00:01.166"
    assert not popover.error_label.get_visible()
    assert popover.submit()
    assert seeks == [1.166]


def test_user_entered_eof_target_is_still_rejected_without_clamping(navigation):
    popover, state, seeks, _opens, _button = navigation
    state["position"] = state["duration"] = 1.1666667
    popover.open()
    popover.entry.set_text("00:00:01.167")
    assert not popover.submit()
    assert popover.entry.get_text() == "00:00:01.167"
    assert "beyond the end" in popover.error_label.get_text()
    assert seeks == []
