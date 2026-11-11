"""Document proofreading with configurable limits and navigation to issues."""

import gettext

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk

from gsub.quality import QualitySettings, check_quality

_ = gettext.translation("gsub", fallback=True).gettext


class QualityDialog(Adw.Dialog):
    def __init__(self, parent_window, document, on_select, settings=None,
                 on_settings_changed=None):
        super().__init__()
        self.parent_window = parent_window
        self.document = document
        self.on_select = on_select
        self.on_settings_changed = on_settings_changed
        self.settings = (settings if isinstance(settings, QualitySettings)
                         else QualitySettings.from_dict(settings))
        self.set_title(_("Subtitle Quality"))
        self.set_content_width(680)
        self.set_content_height(650)

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())
        self.set_child(toolbar)
        scrolled = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER,
                                     vexpand=True)
        toolbar.set_content(scrolled)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18,
                          margin_top=18, margin_bottom=18,
                          margin_start=18, margin_end=18)
        scrolled.set_child(content)

        settings_group = Adw.PreferencesGroup()
        expander = Adw.ExpanderRow(title=_("Quality Limits"),
                                  subtitle=_("Adjust suggestions for your subtitle project"))
        settings_group.add(expander)
        content.append(settings_group)
        self.max_cps_row = self._spin(expander, _("Maximum characters per second"),
                                      self.settings.max_cps, 1, 100, 1)
        self.max_chars_row = self._spin(expander, _("Maximum characters per line"),
                                        self.settings.max_chars_per_line, 1, 500)
        self.max_lines_row = self._spin(expander, _("Maximum lines per subtitle"),
                                        self.settings.max_lines, 1, 20)
        self.min_duration_row = self._spin(expander, _("Minimum duration (ms)"),
                                           self.settings.min_duration_ms, 0, 86_400_000)
        self.max_duration_row = self._spin(expander, _("Maximum duration (ms)"),
                                           self.settings.max_duration_ms, 0, 86_400_000)
        self.min_gap_row = self._spin(expander, _("Minimum gap (ms)"),
                                      self.settings.min_gap_ms, 0, 10_000)
        self.overlap_row = Adw.SwitchRow(title=_("Check overlapping subtitles"),
            subtitle=_("Turn off for intentional simultaneous dialogue or signs"),
            active=self.settings.check_overlaps)
        expander.add_row(self.overlap_row)

        # Connect after constructing every row so initial values never trigger
        # a partial read or unexpectedly overwrite saved preferences.
        for row in (self.max_cps_row, self.max_chars_row, self.max_lines_row,
                    self.min_duration_row, self.max_duration_row, self.min_gap_row):
            row.connect("notify::value", self._on_settings_changed)
        self.overlap_row.connect("notify::active", self._on_settings_changed)

        self.status_label = Gtk.Label(xalign=0, wrap=True)
        self.status_label.add_css_class("dim-label")
        content.append(self.status_label)
        self.issues_box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.issues_box.add_css_class("boxed-list")
        content.append(self.issues_box)
        self.issues = []
        self.refresh()

    @staticmethod
    def _spin(parent, title, value, lower, upper, digits=0):
        # Preserve custom values loaded from configuration even beyond the
        # convenient UI range.
        row = Adw.SpinRow(title=title, digits=digits,
            adjustment=Gtk.Adjustment(value=value, lower=min(lower, value),
                upper=max(upper, value), step_increment=0.5 if digits else 1,
                page_increment=10))
        parent.add_row(row)
        return row

    def _on_settings_changed(self, *_args):
        try:
            settings = QualitySettings(
                max_cps=self.max_cps_row.get_value(),
                max_chars_per_line=int(self.max_chars_row.get_value()),
                max_lines=int(self.max_lines_row.get_value()),
                min_duration_ms=int(self.min_duration_row.get_value()),
                max_duration_ms=int(self.max_duration_row.get_value()),
                min_gap_ms=int(self.min_gap_row.get_value()),
                check_overlaps=self.overlap_row.get_active())
        except ValueError:
            self.status_label.set_text(_("Maximum duration must be at least the minimum duration."))
            return
        self.settings = settings
        if self.on_settings_changed is not None:
            self.on_settings_changed(settings)
        self.refresh()

    def refresh(self):
        """Rescan the current document, preserving the user's limits."""
        self.issues = check_quality(self.document, self.settings)
        while child := self.issues_box.get_first_child():
            self.issues_box.remove(child)
        self.status_label.set_text(
            _("No quality issues found") if not self.issues
            else _("%d quality issue(s) — select one to review its subtitle") % len(self.issues))
        self.issues_box.set_visible(bool(self.issues))
        for issue in self.issues:
            row = Adw.ActionRow(title=_("Subtitle %d") % (issue.position + 1),
                                subtitle=issue.message, activatable=True)
            # Issue text must remain literal (e.g. <b> in a subtitle).
            row.set_use_markup(False)
            row.set_subtitle_lines(0)
            row.add_prefix(Gtk.Image(icon_name="dialog-error-symbolic"
                if issue.severity == "error" else "dialog-warning-symbolic"))
            row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
            row.connect("activated", self._on_issue_activated, issue.position)
            self.issues_box.append(row)

    def _on_issue_activated(self, _row, position):
        if 0 <= position < len(self.document.entries):
            self.on_select(position)
        self.close()

    def present(self, parent=None):
        super().present(parent or self.parent_window)
