"""Real GTK checks for the persistent, editable proofreading workflow."""

import pytest

from gsub.commands.command import CommandManager
from gsub.models import SubtitleDocument, SubtitleEntry, SubtitleFormat, TimeCode
from gsub.quality import QualitySettings
from gsub.resources import register_resources

try:
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, Gtk
    register_resources()
    Gtk.init()
    Adw.init()
    HAS_DISPLAY = Gdk.Display.get_default() is not None
except Exception:
    HAS_DISPLAY = False

pytestmark = pytest.mark.skipif(not HAS_DISPLAY, reason="no display available for GTK tests")

LONG_TEXT = "This subtitle needs a balanced break between its words."
LIMITS = QualitySettings(max_chars_per_line=28, max_cps=100,
                         min_duration_ms=0, max_duration_ms=100_000, min_gap_ms=0)


def cue(text=LONG_TEXT, start=1000, end=5000):
    return SubtitleEntry(1, TimeCode.from_milliseconds(start),
                         TimeCode.from_milliseconds(end), text)


@pytest.fixture
def panel_factory():
    from gsub.widgets.quality_panel import QualityPanel

    windows = []

    def make(*entries, fmt=SubtitleFormat.SRT, on_before_action=None):
        doc = SubtitleDocument(fmt, entries=list(entries))
        doc.reindex()
        window = Gtk.Window()
        windows.append(window)
        selected, saved = [], []
        manager = CommandManager()
        panel = QualityPanel(window, doc, selected.append, settings=LIMITS,
            on_settings_changed=saved.append, on_apply=manager.execute,
            on_before_action=on_before_action)
        window.set_child(panel)
        return panel, selected, saved, manager

    yield make
    for window in windows:
        window.destroy()


def rows(panel):
    result = []
    child = panel.issues_box.get_first_child()
    while child:
        result.append(child)
        child = child.get_next_sibling()
    return result


def test_panel_is_embeddable_and_issue_activation_keeps_it_open(panel_factory):
    panel, selected, _, _ = panel_factory(cue())
    closed = []
    panel.connect("closed", lambda _p: closed.append(True))
    rows(panel)[0].emit("activated")
    assert selected == [0]
    assert panel.get_visible()
    assert not closed


def test_navigation_and_filter_restrict_the_review_queue(panel_factory):
    panel, selected, _, _ = panel_factory(cue(), cue("", 6000, 8000),
                                         cue(start=9000, end=13_000))
    panel.type_filter.set_selected(2)  # Line length
    assert [issue.position for issue in panel.issues] == [0, 2]
    panel.next_button.emit("clicked")
    assert selected[-1] == 2
    panel.next_button.emit("clicked")
    assert selected[-1] == 0
    panel.previous_button.emit("clicked")
    assert selected[-1] == 2
    panel.type_filter.set_selected(5)  # Invalid duration
    assert not panel.issues
    assert not panel.next_button.get_sensitive()
    assert not panel.ignore_button.get_sensitive()


def test_ignore_reset_and_changed_cue_visibility(panel_factory):
    panel, _, _, _ = panel_factory(cue())
    panel.ignore_button.emit("clicked")
    assert not rows(panel)
    assert "1 ignored" in panel.status_label.get_text()
    panel.document.entries[0].text += " More typing."
    panel.refresh()
    assert len(rows(panel)) == 1
    panel.ignore_button.emit("clicked")
    panel.reset_ignored_button.emit("clicked")
    assert len(rows(panel)) == 1
    assert "ignored" not in panel.status_label.get_text()


def test_settings_changes_persist_and_refresh_results(panel_factory):
    panel, _, saved, _ = panel_factory(cue())
    panel.max_chars_row.set_value(100)
    assert not panel.issues
    assert saved[-1].max_chars_per_line == 100
    panel.max_chars_row.set_value(20)
    assert len(panel.issues) == 1


def test_invalid_settings_do_not_replace_last_valid_limits(panel_factory):
    panel, _, saved, _ = panel_factory(cue())
    panel.min_duration_row.set_value(200_000)
    assert panel.settings == LIMITS
    assert not saved
    assert "Maximum duration" in panel.message_label.get_text()


def test_preview_is_nonmutating_then_one_undoable_fix(panel_factory):
    panel, selected, _, manager = panel_factory(cue("<i>" + LONG_TEXT + "</i>"))
    before = panel.document.entries[0].text
    panel.preview_button.emit("clicked")
    assert panel.preview_box.get_visible()
    assert panel.document.entries[0].text == before
    assert panel.before_label.get_text() == LONG_TEXT
    assert "\n" in panel.after_label.get_text()
    assert selected[-1] == 0
    after = panel.preview.after
    panel.apply_preview_button.emit("clicked")
    assert panel.document.entries[0].text == after
    assert not panel.preview_box.get_visible()
    assert manager.can_undo()
    manager.undo()
    panel.refresh()
    assert panel.document.entries[0].text == before
    assert not manager.can_undo()
    manager.redo()
    assert panel.document.entries[0].text == after


def test_cancel_preview_keeps_document_and_history_unchanged(panel_factory):
    panel, _, _, manager = panel_factory(cue())
    panel._preview_rebalance()
    panel._clear_preview()
    panel._apply_preview()
    assert panel.document.entries[0].text == LONG_TEXT
    assert not manager.can_undo()


def test_changed_source_invalidates_preview_before_apply(panel_factory):
    panel, _, _, manager = panel_factory(cue())
    panel._preview_rebalance()
    panel.document.entries[0].text += " New typing."
    panel._apply_preview()
    assert panel.document.entries[0].text.endswith(" New typing.")
    assert not manager.can_undo()
    assert "subtitle changed" in panel.message_label.get_text()
    assert not panel.preview_box.get_visible()


def test_refresh_hides_stale_preview_and_explains_why(panel_factory):
    panel, _, _, _ = panel_factory(cue())
    panel._preview_rebalance()
    panel.document.entries[0].text += " New typing."
    panel.refresh()
    assert panel.preview is None
    assert not panel.preview_box.get_visible()
    assert "changed" in panel.message_label.get_text()


def test_apply_flushes_pending_changes_before_validating_preview(panel_factory):
    calls = []
    panel, _, _, manager = panel_factory(cue(), on_before_action=lambda: calls.append(True))
    panel._preview_rebalance()
    panel.on_before_action = lambda: setattr(panel.document.entries[0], "text", "Pending edit")
    panel._apply_preview()
    assert calls == [True]
    assert panel.document.entries[0].text == "Pending edit"
    assert not manager.can_undo()


@pytest.mark.parametrize("operation", ["_ignore_current", "_preview_rebalance"])
def test_pending_edit_cannot_redirect_action_to_a_different_issue(panel_factory, operation):
    panel, _, _, manager = panel_factory(cue(), cue(start=6000, end=10_000))
    panel.on_before_action = lambda: setattr(panel.document.entries[0], "text", "Fixed")
    getattr(panel, operation)()
    assert len(panel.issues) == 1
    assert panel.issues[0].position == 1
    assert not panel.review.ignored_count
    assert panel.preview is None
    assert not manager.can_undo()
    assert "issue changed" in panel.message_label.get_text()


def test_unsupported_ass_fix_is_explained_without_changes(panel_factory):
    text = r"{\k20}" + LONG_TEXT
    panel, _, _, manager = panel_factory(cue(text), fmt=SubtitleFormat.ASS)
    panel._preview_rebalance()
    assert "karaoke" in panel.message_label.get_text()
    assert panel.preview is None
    assert panel.document.entries[0].text == text
    assert not manager.can_undo()


def test_empty_panel_has_clear_status_and_disabled_controls(panel_factory):
    panel, _, _, _ = panel_factory(cue("Readable"))
    assert panel.status_label.get_text() == "No quality issues found"
    assert not rows(panel)
    assert not panel.issues_box.get_visible()
    assert not panel.previous_button.get_sensitive()
    assert not panel.preview_button.get_sensitive()


def test_repeated_refresh_keeps_existing_rows_when_results_do_not_change(panel_factory):
    panel, _, _, _ = panel_factory(cue())
    initial = rows(panel)
    panel.refresh()
    assert rows(panel) == initial
    panel.document.entries.insert(0, cue("Earlier", 0, 500))
    panel.document.reindex()
    panel.refresh()
    assert rows(panel) == initial
    assert rows(panel)[0].get_title() == "Subtitle 2"


def test_close_hides_panel_and_emits_signal_without_destroying_document(panel_factory):
    panel, _, _, _ = panel_factory(cue())
    closed = []
    panel.connect("closed", lambda _p: closed.append(True))
    panel.close()
    assert not panel.get_visible()
    assert closed == [True]
    panel.present()
    assert panel.get_visible()
    assert len(panel.issues) == 1


def test_readonly_panel_does_not_offer_mutating_fix_controls(panel_factory):
    panel, _, _, _ = panel_factory(cue())
    panel.on_apply = None
    panel.refresh()
    assert not panel.preview_button.get_sensitive()
    assert not panel.apply_preview_button.get_sensitive()
