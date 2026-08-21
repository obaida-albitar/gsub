"""GTK widget tests for the compatibility panel.

Verifies issue rendering, severity counting, the empty state and the Fix
button -> on_fix callback wiring. Requires a display; skipped automatically
when none is available.
"""

import pytest
from subtitle_editor.parsers.ass_validator import CompatIssue, CompatSeverity
from subtitle_editor.resources import register_resources

try:
    from gi.repository import Gdk, Gtk
    register_resources()
    try:
        Gtk.init()
        import gi
        gi.require_version('Adw', '1')
        from gi.repository import Adw
        Adw.init()
    except Exception:
        pass
    _HAS_DISPLAY = Gdk.Display.get_default() is not None
except Exception:  # pragma: no cover - environment without GTK
    _HAS_DISPLAY = False

pytestmark = pytest.mark.skipif(
    not _HAS_DISPLAY, reason="no display available for GTK widget tests"
)


def _issue(severity, location="Style 'Default'", message="Something is off",
           suggestion=None, fix=None):
    return CompatIssue(
        severity=severity,
        code="test.issue",
        message=message,
        location=location,
        suggestion=suggestion,
        fix=fix,
    )


def _make_panel():
    from subtitle_editor.widgets.compatibility_panel import CompatibilityPanel

    panel = CompatibilityPanel()
    fixed = []
    panel.on_fix = fixed.append
    return panel, fixed


def _rows(panel):
    return list(panel.issues_box)


def _row_widgets(row):
    """Each row: [icon, label, fix button] in order."""
    return [row.get_first_child(),
            row.get_first_child().get_next_sibling(),
            row.get_first_child().get_next_sibling().get_next_sibling()]


@pytest.mark.integration
class TestEmptyState:
    def test_initial_state_has_no_rows(self):
        panel, _ = _make_panel()
        assert _rows(panel) == []
        assert panel.count_label.get_text() == ""

    def test_set_empty_issues_keeps_placeholder(self):
        panel, _ = _make_panel()
        panel.set_issues([_issue(CompatSeverity.ERROR)])
        assert panel.empty_label.get_visible() is False

        panel.set_issues([])
        assert panel.empty_label.get_visible() is True
        assert panel.scrolled.get_visible() is False
        assert panel.count_label.get_text() == "No compatibility issues found"

    def test_clear_returns_to_placeholder(self):
        panel, _ = _make_panel()
        panel.set_issues([_issue(CompatSeverity.WARNING)])
        panel.clear()
        assert _rows(panel) == []
        assert panel.empty_label.get_visible() is True


@pytest.mark.integration
class TestIssueRendering:
    def test_one_row_per_issue_in_order(self):
        panel, _ = _make_panel()
        issues = [
            _issue(CompatSeverity.ERROR, location="Line 3", message="m1"),
            _issue(CompatSeverity.INFO, location="Line 4", message="m2"),
        ]
        panel.set_issues(issues)

        rows = _rows(panel)
        assert len(rows) == 2
        label = _row_widgets(rows[0])[1]
        assert label.get_label() == "<b>Line 3</b>\nm1"

    def test_count_label_summarises_severities(self):
        panel, _ = _make_panel()
        panel.set_issues([
            _issue(CompatSeverity.ERROR),
            _issue(CompatSeverity.ERROR),
            _issue(CompatSeverity.WARNING),
            _issue(CompatSeverity.INFO),
        ])
        assert panel.count_label.get_text() == (
            "4 issue(s): 2 error, 1 warning, 1 info")

    def test_count_label_single_category(self):
        panel, _ = _make_panel()
        panel.set_issues([_issue(CompatSeverity.WARNING)])
        assert panel.count_label.get_text() == "1 issue(s): 1 warning"

    def test_severity_icon_matches(self):
        panel, _ = _make_panel()
        panel.set_issues([
            _issue(CompatSeverity.ERROR),
            _issue(CompatSeverity.WARNING),
            _issue(CompatSeverity.INFO),
        ])
        rows = _rows(panel)
        icons = [_row_widgets(row)[0] for row in rows]
        assert icons[0].get_icon_name() == "dialog-error-symbolic"
        assert icons[1].get_icon_name() == "dialog-warning-symbolic"
        assert icons[2].get_icon_name() == "dialog-information-symbolic"

    def test_set_issues_replaces_previous_rows(self):
        panel, _ = _make_panel()
        panel.set_issues([_issue(CompatSeverity.ERROR)])
        panel.set_issues([_issue(CompatSeverity.INFO)])

        rows = _rows(panel)
        assert len(rows) == 1
        assert _row_widgets(rows[0])[0].get_icon_name() == (
            "dialog-information-symbolic")


@pytest.mark.integration
class TestFixButton:
    def test_fixable_issue_shows_enabled_button_with_suggestion(self):
        panel, _ = _make_panel()
        fix = {"kind": "blur", "entry_index": 1}
        panel.set_issues([
            _issue(CompatSeverity.WARNING, suggestion="Clamp \\blur",
                   fix=fix),
        ])

        button = _row_widgets(_rows(panel)[0])[2]
        assert button.get_visible() is True
        assert button.get_sensitive() is True
        assert button.get_tooltip_text() == "Clamp \\blur"

    def test_unfixable_issue_has_hidden_button(self):
        panel, _ = _make_panel()
        panel.set_issues([_issue(CompatSeverity.INFO)])

        button = _row_widgets(_rows(panel)[0])[2]
        assert button.get_visible() is False

    def test_clicking_fix_invokes_callback_with_issue(self):
        panel, fixed = _make_panel()
        issue = _issue(
            CompatSeverity.WARNING,
            suggestion="Replace the colour",
            fix={"kind": "color", "field": "primary_color", "style": "Default"},
        )
        panel.set_issues([issue])

        button = _row_widgets(_rows(panel)[0])[2]
        button.emit("clicked")

        assert fixed == [issue]

    def test_no_callback_configured_is_safe(self):
        panel, _ = _make_panel()
        panel.on_fix = None
        panel.set_issues([
            _issue(CompatSeverity.WARNING, fix={"kind": "blur"}),
        ])

        button = _row_widgets(_rows(panel)[0])[2]
        button.emit("clicked")  # must not raise
