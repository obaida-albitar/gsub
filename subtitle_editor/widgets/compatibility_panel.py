"""
Compatibility panel widget.

Displays a list of :class:`CompatIssue` entries produced by the headless
ASS/SSA compatibility validator, with an optional per-issue "Fix" action.
"""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk  # noqa: E402

from subtitle_editor.resources import template_resource_path  # noqa: E402
from subtitle_editor.parsers.ass_validator import CompatIssue, CompatSeverity  # noqa: E402


_SEVERITY_ICONS = {
    CompatSeverity.ERROR: "dialog-error-symbolic",
    CompatSeverity.WARNING: "dialog-warning-symbolic",
    CompatSeverity.INFO: "dialog-information-symbolic",
}


@Gtk.Template(resource_path=template_resource_path('compatibility-panel'))
class CompatibilityPanel(Gtk.Box):
    """Widget listing compatibility issues for the current document."""

    __gtype_name__ = 'CompatibilityPanel'

    issues_box = Gtk.Template.Child()
    empty_label = Gtk.Template.Child()
    scrolled = Gtk.Template.Child()
    count_label = Gtk.Template.Child()

    def __init__(self):
        super().__init__()

        self.on_fix = None

    def set_issues(self, issues: list):
        """Replace the displayed issues.

        Shows the empty placeholder when there are no issues.
        """
        for child in list(self.issues_box):
            self.issues_box.remove(child)

        if not issues:
            self.count_label.set_text("No compatibility issues found")
            self.empty_label.set_visible(True)
            self.scrolled.set_visible(False)
            return

        counts = {CompatSeverity.ERROR: 0, CompatSeverity.WARNING: 0,
                  CompatSeverity.INFO: 0}
        for issue in issues:
            counts[issue.severity] += 1
        parts = []
        if counts[CompatSeverity.ERROR]:
            parts.append(f"{counts[CompatSeverity.ERROR]} error")
        if counts[CompatSeverity.WARNING]:
            parts.append(f"{counts[CompatSeverity.WARNING]} warning")
        if counts[CompatSeverity.INFO]:
            parts.append(f"{counts[CompatSeverity.INFO]} info")
        self.count_label.set_text(f"{len(issues)} issue(s): " + ", ".join(parts))

        self.empty_label.set_visible(False)
        self.scrolled.set_visible(True)
        for issue in issues:
            self.issues_box.append(self._build_row(issue))

    def clear(self):
        """Clear all displayed issues."""
        self.set_issues([])

    def _build_row(self, issue: CompatIssue) -> Gtk.Box:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.set_margin_top(8)
        row.set_margin_bottom(8)
        row.set_margin_start(8)
        row.set_margin_end(8)

        image = Gtk.Image()
        image.set_from_icon_name(_SEVERITY_ICONS.get(issue.severity, "dialog-information-symbolic"))
        image.set_pixel_size(16)
        image.set_valign(Gtk.Align.START)
        row.append(image)

        label = Gtk.Label()
        label.set_xalign(0)
        label.set_hexpand(True)
        label.set_wrap(True)
        label.set_use_markup(True)
        label.set_valign(Gtk.Align.START)
        label.set_label(f"<b>{issue.location}</b>\n{issue.message}")
        row.append(label)

        fix_button = Gtk.Button(label="Fix")
        fix_button.set_valign(Gtk.Align.CENTER)
        fixable = issue.fix is not None
        fix_button.set_visible(fixable)
        fix_button.set_sensitive(fixable)
        if issue.suggestion:
            fix_button.set_tooltip_text(issue.suggestion)
        if fixable:
            fix_button.connect("clicked", self._on_fix_clicked, issue)
        row.append(fix_button)

        return row

    def _on_fix_clicked(self, button, issue: CompatIssue):
        if callable(self.on_fix):
            self.on_fix(issue)
