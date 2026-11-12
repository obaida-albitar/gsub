"""Persistent proofreading alongside the subtitle editor."""

import gettext

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GObject, Gtk

from gsub.quality import QualitySettings, visible_text
from gsub.quality_review import QualityReview, REBALANCE_CODES


_ = gettext.translation("gsub", fallback=True).gettext

_FILTERS = (
    (None, _("All issue types")),
    ("text.reading_speed", _("Reading speed")),
    ("text.line_length", _("Line length")),
    ("text.line_count", _("Line count")),
    ("text.empty", _("Empty subtitles")),
    ("timing.invalid_duration", _("Invalid duration")),
    ("timing.too_short", _("Short duration")),
    ("timing.too_long", _("Long duration")),
    ("timing.overlap", _("Overlaps")),
    ("timing.small_gap", _("Small gaps")),
)


class QualityPanel(Gtk.Box):
    """Nonmodal review widget; all document edits go through ``on_apply``.

    ``on_before_action`` flushes pending editor changes before a navigation,
    ignore or fix action, so a preview can never overwrite uncommitted typing.
    Ignored warnings last for this document's review session only.
    """

    __gsignals__ = {"closed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self, parent_window, document, on_select, settings=None,
                 on_settings_changed=None, on_apply=None, on_close=None,
                 on_before_action=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.parent_window = parent_window
        self.document = document
        self.on_select = on_select
        self.on_settings_changed = on_settings_changed
        self.on_apply = on_apply
        self.on_close = on_close
        self.on_before_action = on_before_action
        self.settings = (settings if isinstance(settings, QualitySettings)
                         else QualitySettings.from_dict(settings))
        self.review = QualityReview(document, self.settings)
        self.preview = None
        self._rows = []
        self._rendered_keys = None
        self.add_css_class("background")

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6,
                         margin_start=12, margin_end=6, margin_top=6, margin_bottom=6)
        title = Gtk.Label(label=_("Subtitle Quality"), xalign=0, hexpand=True)
        title.add_css_class("heading")
        header.append(title)
        close = Gtk.Button(icon_name="window-close-symbolic",
                           tooltip_text=_("Close proofreading panel"))
        close.add_css_class("flat")
        close.connect("clicked", lambda _button: self.close())
        header.append(close)
        self.append(header)

        scrolled = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER,
                                     vexpand=True, min_content_height=180)
        self.append(scrolled)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                          margin_top=6, margin_bottom=12,
                          margin_start=12, margin_end=12)
        scrolled.set_child(content)
        self._build_settings(content)

        self.type_filter = Gtk.DropDown(model=Gtk.StringList.new(
            [label for _code, label in _FILTERS]), tooltip_text=_("Filter by issue type"))
        self.type_filter.connect("notify::selected", self._on_filter_changed)
        content.append(self.type_filter)

        navigation = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.status_label = Gtk.Label(xalign=0, wrap=True, hexpand=True)
        self.status_label.add_css_class("dim-label")
        navigation.append(self.status_label)
        self.previous_button = Gtk.Button(icon_name="go-up-symbolic",
                                          tooltip_text=_("Previous quality issue"))
        self.next_button = Gtk.Button(icon_name="go-down-symbolic",
                                      tooltip_text=_("Next quality issue"))
        self.previous_button.connect("clicked", lambda _b: self._navigate(-1))
        self.next_button.connect("clicked", lambda _b: self._navigate(1))
        navigation.append(self.previous_button)
        navigation.append(self.next_button)
        content.append(navigation)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.ignore_button = Gtk.Button(label=_("Ignore Issue"),
            tooltip_text=_("Ignore this exact warning while the document is open. Editing the cue shows it again."))
        self.reset_ignored_button = Gtk.Button(label=_("Reset Ignored"))
        self.ignore_button.connect("clicked", self._ignore_current)
        self.reset_ignored_button.connect("clicked", self._reset_ignored)
        actions.append(self.ignore_button)
        actions.append(self.reset_ignored_button)
        content.append(actions)

        self.issues_box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.issues_box.add_css_class("boxed-list")

        self.preview_button = Gtk.Button(label=_("Preview Rebalance Fix"),
            tooltip_text=_("Preview the existing text rebalance operation for this issue"))
        self.preview_button.connect("clicked", self._preview_rebalance)
        content.append(self.preview_button)

        self.message_label = Gtk.Label(xalign=0, wrap=True, visible=False)
        self.message_label.add_css_class("dim-label")
        content.append(self.message_label)
        self.preview_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                                   spacing=6, visible=False)
        preview_title = Gtk.Label(label=_("Rebalance Preview"), xalign=0)
        preview_title.add_css_class("heading")
        self.preview_box.append(preview_title)
        self.preview_box.append(Gtk.Label(label=_("Before"), xalign=0))
        self.before_label = Gtk.Label(xalign=0, wrap=True, selectable=True)
        self.preview_box.append(self.before_label)
        self.preview_box.append(Gtk.Label(label=_("After"), xalign=0))
        self.after_label = Gtk.Label(xalign=0, wrap=True, selectable=True)
        self.preview_box.append(self.after_label)
        self.preview_box.append(Gtk.Label(
            label=_("Only line breaks and spacing change. Formatting is preserved; the fix can be undone."),
            xalign=0, wrap=True))
        preview_actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                                  spacing=6, halign=Gtk.Align.END)
        cancel = Gtk.Button(label=_("Cancel"))
        cancel.connect("clicked", lambda _b: self._clear_preview())
        self.apply_preview_button = Gtk.Button(label=_("Apply Rebalance"))
        self.apply_preview_button.add_css_class("suggested-action")
        self.apply_preview_button.connect("clicked", self._apply_preview)
        preview_actions.append(cancel)
        preview_actions.append(self.apply_preview_button)
        self.preview_box.append(preview_actions)
        content.append(self.preview_box)
        content.append(self.issues_box)
        self.refresh()

    def _build_settings(self, content):
        group = Adw.PreferencesGroup()
        expander = Adw.ExpanderRow(title=_("Quality Limits"),
                                  subtitle=_("Adjust suggestions for this project"))
        group.add(expander)
        content.append(group)
        fields = (
            ("max_cps_row", _("Maximum characters per second"), self.settings.max_cps, 1, 100, 1),
            ("max_chars_row", _("Maximum characters per line"), self.settings.max_chars_per_line, 1, 500, 0),
            ("max_lines_row", _("Maximum lines per subtitle"), self.settings.max_lines, 1, 20, 0),
            ("min_duration_row", _("Minimum duration (ms)"), self.settings.min_duration_ms, 0, 86_400_000, 0),
            ("max_duration_row", _("Maximum duration (ms)"), self.settings.max_duration_ms, 0, 86_400_000, 0),
            ("min_gap_row", _("Minimum gap (ms)"), self.settings.min_gap_ms, 0, 10_000, 0),
        )
        for attr, title, value, lower, upper, digits in fields:
            row = Adw.SpinRow(title=title, digits=digits,
                adjustment=Gtk.Adjustment(value=value, lower=min(lower, value),
                    upper=max(upper, value), step_increment=0.5 if digits else 1,
                    page_increment=10))
            setattr(self, attr, row)
            expander.add_row(row)
        self.overlap_row = Adw.SwitchRow(title=_("Check overlapping subtitles"),
            subtitle=_("Separate ASS styles and layers are checked independently"),
            active=self.settings.check_overlaps)
        expander.add_row(self.overlap_row)
        for attr, *_rest in fields:
            getattr(self, attr).connect("notify::value", self._on_settings_changed)
        self.overlap_row.connect("notify::active", self._on_settings_changed)

    @property
    def issues(self):
        return self.review.issues

    def _before_action(self):
        if callable(self.on_before_action):
            self.on_before_action()
        self.review.refresh()

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
            self._show_message(_("Maximum duration must be at least the minimum duration."))
            return
        self.settings = settings
        self.review.settings = settings
        self._clear_preview()
        if callable(self.on_settings_changed):
            self.on_settings_changed(settings)
        self.refresh()

    def _on_filter_changed(self, *_args):
        selected = self.type_filter.get_selected()
        self.review.set_filter(_FILTERS[selected][0] if selected < len(_FILTERS) else None)
        self._clear_preview()
        self._render()

    def refresh(self):
        self.review.refresh()
        if self.preview is not None:
            try:
                self.review.command_for_preview(self.preview)
            except ValueError:
                self._clear_preview()
                self._show_message(_("The subtitle or quality limits changed. Preview the fix again."))
        self._render()

    def _render(self):
        keys = tuple(self.review.issue_key(issue) for issue in self.issues)
        if keys != self._rendered_keys:
            self._rows.clear()
            while child := self.issues_box.get_first_child():
                self.issues_box.remove(child)
            for issue, key in zip(self.issues, keys):
                row = Adw.ActionRow(title=_("Subtitle %d") % (issue.position + 1),
                                    subtitle=issue.message, activatable=True)
                row.set_use_markup(False)
                row.set_subtitle_lines(0)
                row.add_prefix(Gtk.Image(icon_name="dialog-error-symbolic"
                    if issue.severity == "error" else "dialog-warning-symbolic"))
                row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
                row.connect("activated", self._on_issue_activated, key)
                self.issues_box.append(row)
                self._rows.append(row)
            self._rendered_keys = keys
        else:
            # Structural edits can change cue numbers without changing keys.
            for row, issue in zip(self._rows, self.issues):
                row.set_title(_("Subtitle %d") % (issue.position + 1))
                row.set_subtitle(issue.message)
        self.issues_box.set_visible(bool(self.issues))
        count, ignored = len(self.issues), self.review.ignored_count
        if count:
            status = _("{current} of {count} issues").format(
                current=self.review.current_index + 1, count=count)
        elif self.review.all_issues:
            status = _("No matching issues") if self.review.filter_code else _("All issues are ignored")
        else:
            status = _("No quality issues found")
        if ignored:
            status += _(" · %d ignored") % ignored
        self.status_label.set_text(status)
        for button in (self.previous_button, self.next_button, self.ignore_button):
            button.set_sensitive(bool(count))
        self.reset_ignored_button.set_sensitive(bool(self.review._dismissed))
        issue = self.review.current_issue
        self.preview_button.set_sensitive(bool(callable(self.on_apply) and issue is not None
                                               and issue.code in REBALANCE_CODES))
        self.apply_preview_button.set_sensitive(callable(self.on_apply))
        for index, row in enumerate(self._rows):
            if index == self.review.current_index:
                row.add_css_class("accent")
            else:
                row.remove_css_class("accent")

    def _on_issue_activated(self, _row, key):
        self._before_action()
        issue = self.review.select_key(key)
        self._clear_preview()
        self._render()
        if issue is not None:
            self.on_select(issue.position)

    def _navigate(self, offset):
        self._before_action()
        issue = self.review.move(offset)
        self._clear_preview()
        self._render()
        if issue is not None:
            self.on_select(issue.position)

    def _ignore_current(self, _button=None):
        issue = self.review.current_issue
        key = self.review.issue_key(issue) if issue is not None else None
        self._before_action()
        if key is None or self.review.select_key(key) is None:
            self._clear_preview()
            self._show_message(_("The issue changed. Select a current issue before ignoring it."))
            self._render()
            return
        self.review.dismiss_current()
        self._clear_preview()
        self._render()

    def _reset_ignored(self, _button=None):
        self.review.reset_ignored()
        self._clear_preview()
        self._render()

    def _preview_rebalance(self, _button=None):
        issue = self.review.current_issue
        key = self.review.issue_key(issue) if issue is not None else None
        self._before_action()
        self._clear_preview()
        if key is None or self.review.select_key(key) is None:
            self._show_message(_("The issue changed. Select a current issue before previewing a fix."))
            self._render()
            return
        try:
            self.preview = self.review.preview_rebalance()
        except ValueError as error:
            self._show_message(str(error))
            self._render()
            return
        self.before_label.set_text(visible_text(self.preview.before, self.document.format))
        self.after_label.set_text(visible_text(self.preview.after, self.document.format))
        self.preview_box.set_visible(True)
        self.on_select(self.review.current_issue.position)

    def _apply_preview(self, _button=None):
        preview = self.preview
        if preview is None or not callable(self.on_apply):
            return
        self._before_action()
        try:
            command = self.review.command_for_preview(preview)
            if self.on_apply(command) is False:
                self._show_message(_("The fix was not applied. Preview it again."))
                return
        except ValueError as error:
            self._clear_preview()
            self._show_message(str(error))
            self._render()
            return
        self._clear_preview()
        self.refresh()

    def _clear_preview(self):
        self.preview = None
        self.preview_box.set_visible(False)
        self.message_label.set_visible(False)

    def _show_message(self, message):
        self.message_label.set_text(message)
        self.message_label.set_visible(True)

    def present(self, _parent=None):
        self.set_visible(True)
        self.refresh()

    def close(self):
        self.set_visible(False)
        self._clear_preview()
        if callable(self.on_close):
            self.on_close()
        self.emit("closed")
