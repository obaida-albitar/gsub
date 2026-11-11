"""Find/replace dialog with a live preview and command-based edits."""

import gettext

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from gsub.search import (
    SearchOptions, build_replace_command, find_matches, replacement_visible_text,
)
from gsub.models import SubtitleFormat


_ = gettext.translation("gsub", fallback=True).gettext


class FindReplaceDialog(Adw.Dialog):
    """Search a document, preview replacements, and apply one undoable edit.

    ``on_apply(command)`` must execute synchronously through the window's
    CommandManager and refresh its views. ``on_select(position)`` navigates to a
    zero-based subtitle position. The selection-only scope is captured on open.
    """

    __gtype_name__ = "GsubFindReplaceDialog"
    PREVIEW_LIMIT = 100

    def __init__(self, parent_window, document, selected_positions=(),
                 on_apply=None, on_select=None):
        super().__init__()
        self.parent_window = parent_window
        self.document = document
        self.selected_positions = tuple(sorted(set(selected_positions)))
        self.on_apply = on_apply
        self.on_select = on_select
        self.matches = []
        self.current_match = -1
        self._refreshing = False
        self.set_title(_("Find and Replace"))
        self.set_content_width(620)
        self.set_content_height(620)

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                      margin_top=12, margin_bottom=18, margin_start=18, margin_end=18)
        toolbar.set_content(box)
        self.set_child(toolbar)

        self.search_entry = Gtk.SearchEntry(placeholder_text=_("Find in subtitle text…"))
        self.replace_entry = Gtk.Entry(placeholder_text=_("Replace with (empty removes matches)"))
        if document.format in (SubtitleFormat.ASS, SubtitleFormat.SSA):
            self.replace_entry.set_tooltip_text(
                _("ASS: use \\N or \\n for a line break, and \\h for a nonbreaking space"))
        box.append(self.search_entry)
        box.append(self.replace_entry)

        options = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.case_sensitive = Gtk.CheckButton(label=_("Match case"))
        self.whole_words = Gtk.CheckButton(label=_("Whole words"))
        self.selection_only = Gtk.CheckButton(label=_("Selection only"))
        self.selection_only.set_sensitive(bool(self.selected_positions))
        if not self.selected_positions:
            self.selection_only.set_tooltip_text(_("Select subtitles before opening this dialog"))
        for control in (self.case_sensitive, self.whole_words, self.selection_only):
            options.append(control)
        box.append(options)

        navigation = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.count_label = Gtk.Label(xalign=0, hexpand=True)
        navigation.append(self.count_label)
        self.previous_button = Gtk.Button(icon_name="go-up-symbolic",
                                          tooltip_text=_("Previous match"))
        self.next_button = Gtk.Button(icon_name="go-down-symbolic",
                                      tooltip_text=_("Next match"))
        navigation.append(self.previous_button)
        navigation.append(self.next_button)
        box.append(navigation)

        self.preview_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.preview_list.add_css_class("boxed-list")
        scrolled = Gtk.ScrolledWindow(vexpand=True, min_content_height=160,
                                      hscrollbar_policy=Gtk.PolicyType.NEVER)
        scrolled.set_child(self.preview_list)
        box.append(scrolled)
        self.note_label = Gtk.Label(
            label=_("Formatting tags are preserved. Replacement text uses the formatting at the match start."),
            wrap=True, xalign=0)
        self.note_label.add_css_class("dim-label")
        box.append(self.note_label)
        self.error_label = Gtk.Label(wrap=True, xalign=0, visible=False)
        self.error_label.add_css_class("error")
        box.append(self.error_label)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6,
                          halign=Gtk.Align.END)
        self.replace_button = Gtk.Button(label=_("Replace"))
        self.replace_all_button = Gtk.Button(label=_("Replace All"))
        self.replace_all_button.add_css_class("suggested-action")
        actions.append(self.replace_button)
        actions.append(self.replace_all_button)
        box.append(actions)

        self.search_entry.connect("changed", lambda _entry: self.refresh())
        self.search_entry.connect("activate", lambda _entry: self._move(1))
        self.replace_entry.connect("changed", lambda _entry: self.refresh(navigate=False))
        for control in (self.case_sensitive, self.whole_words, self.selection_only):
            control.connect("toggled", lambda _button: self.refresh())
        self.previous_button.connect("clicked", lambda _button: self._move(-1))
        self.next_button.connect("clicked", lambda _button: self._move(1))
        self.preview_list.connect("row-selected", self._on_preview_selected)
        self.replace_button.connect("clicked", self._replace_one)
        self.replace_all_button.connect("clicked", self._replace_all)
        self.refresh(navigate=False)

    def present(self, parent=None):
        super().present(parent or self.parent_window)
        self.search_entry.grab_focus()

    def _positions(self):
        return self.selected_positions if self.selection_only.get_active() else None

    def refresh(self, navigate=True):
        """Rebuild the preview from the current document and controls."""
        self._refreshing = True
        self.error_label.set_visible(False)
        options = SearchOptions(self.case_sensitive.get_active(), self.whole_words.get_active())
        self.matches = find_matches(self.document, self.search_entry.get_text(),
                                    options, self._positions())
        self.current_match = 0 if self.matches else -1
        child = self.preview_list.get_first_child()
        while child is not None:
            following = child.get_next_sibling()
            self.preview_list.remove(child)
            child = following
        replacement = self.replace_entry.get_text()
        replacement_error = None
        try:
            replacement = replacement_visible_text(replacement, self.document.format)
        except ValueError as error:
            replacement_error = str(error)
        for index, match in enumerate(self.matches[:self.PREVIEW_LIMIT]):
            row = Adw.ActionRow(title=_("Subtitle {number} · match {match}").format(
                number=match.position + 1, match=index + 1))
            row.set_use_markup(False)
            row.set_activatable(True)
            left, right = max(0, match.start - 35), min(len(match.visible_text), match.end + 35)
            before = match.visible_text[left:right]
            after = match.visible_text[left:match.start] + replacement + match.visible_text[match.end:right]
            row.set_subtitle(_("Before: {before}\nAfter: {after}").format(
                before=self._preview_text(before), after=self._preview_text(after)))
            row.set_subtitle_lines(2)
            self.preview_list.append(row)
        if len(self.matches) > self.PREVIEW_LIMIT:
            self.note_label.set_text(_("Showing the first {limit} previews. Navigation and Replace All include every match. Formatting tags are preserved.").format(limit=self.PREVIEW_LIMIT))
        else:
            self.note_label.set_text(_("Formatting tags are preserved. Replacement text uses the formatting at the match start."))
        self._refreshing = False
        self._select_current(navigate)
        if replacement_error:
            self.error_label.set_text(replacement_error)
            self.error_label.set_visible(True)
            self.replace_button.set_sensitive(False)
            self.replace_all_button.set_sensitive(False)

    @staticmethod
    def _preview_text(text):
        return text.replace("\n", " ↵ ")[:160]

    def _select_current(self, navigate=True):
        count = len(self.matches)
        self.count_label.set_text(
            _("{current} of {count} matches").format(current=self.current_match + 1, count=count)
            if count else (_("No matches") if self.search_entry.get_text() else _("Enter text to find")))
        for button in (self.previous_button, self.next_button):
            button.set_sensitive(count > 0)
        for button in (self.replace_button, self.replace_all_button):
            button.set_sensitive(count > 0 and callable(self.on_apply))
        self._refreshing = True
        self.preview_list.select_row(self.preview_list.get_row_at_index(self.current_match)
                                     if 0 <= self.current_match < self.PREVIEW_LIMIT else None)
        self._refreshing = False
        if count and navigate and callable(self.on_select):
            self.on_select(self.matches[self.current_match].position)

    def _on_preview_selected(self, _list, row):
        if self._refreshing or row is None:
            return
        self.current_match = row.get_index()
        self._select_current()

    def _move(self, direction):
        if self.matches:
            self.current_match = (self.current_match + direction) % len(self.matches)
            self._select_current()

    def _apply(self, matches):
        if not callable(self.on_apply):
            return False
        try:
            command = build_replace_command(self.document, matches, self.replace_entry.get_text())
            if command is None:
                self.error_label.set_text(_("The replacement would not change the text."))
                self.error_label.set_visible(True)
                return False
            self.on_apply(command)
            return True
        except ValueError as error:
            self.refresh(navigate=False)
            self.error_label.set_text(str(error))
            self.error_label.set_visible(True)
            return False

    def _replace_one(self, _button=None):
        if not 0 <= self.current_match < len(self.matches):
            return
        previous = self.matches[self.current_match]
        if self._apply([previous]):
            replacement = replacement_visible_text(self.replace_entry.get_text(), self.document.format)
            following = (previous.position, previous.start + len(replacement))
            self.refresh(navigate=False)
            for index, match in enumerate(self.matches):
                if (match.position, match.start) >= following:
                    self.current_match = index
                    break
            self._select_current()

    def _replace_all(self, _button=None):
        if self.matches and self._apply(self.matches):
            self.refresh()
