"""
Editor panel widget.

Provides text and timing editing for the selected subtitle entry.
"""

import gettext
from dataclasses import dataclass

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, GObject, Gtk

from gsub.models import SubtitleEntry, SubtitleFormat, TimeCode
from gsub.parsers.ass_tags import split_override_blocks  # noqa: E402
from gsub.quality import text_metrics
from gsub.resources import template_resource_path
from gsub.widgets.tag_editor import TagEditorRows  # noqa: E402

# Same translation domain as the package-level gettext.install(); bound
# explicitly so the `_` alias is visible to static analysis.
_ = gettext.translation("gsub", fallback=True).gettext


@dataclass
class _TagGroup:
    """A non-leading {...} block anchored to its offset in the buffer.

    The offset is shifted by buffer edits (see the insert-text/delete-range
    handlers) so recomposition keeps splicing the block back in at its
    position within the (possibly edited) clean text — line-start and
    mid-line blocks alike. The block is edited through its own nested
    expander row (header), whose title/subtitle track the anchor's line
    while the text is edited (see _refresh_tag_group_headers).
    """
    offset: int
    header: Adw.ExpanderRow
    editor: TagEditorRows
    add_button: Gtk.MenuButton


@Gtk.Template(resource_path=template_resource_path('editor-panel'))
class EditorPanel(Gtk.Box):
    """Widget for editing subtitle text and timing."""

    __gtype_name__ = 'GsubEditorPanel'

    __gsignals__ = {
        "text-changed": (GObject.SignalFlags.RUN_FIRST, None, (int, str)),
        "timing-changed": (GObject.SignalFlags.RUN_FIRST, None, (int, object, object)),
        "style-changed": (GObject.SignalFlags.RUN_FIRST, None, (int, object)),
        "position-changed": (GObject.SignalFlags.RUN_FIRST, None, (int, int, int, int)),
    }

    # Template children.
    style_row = Gtk.Template.Child()
    text_expander = Gtk.Template.Child()
    text_view = Gtk.Template.Child()
    readability_row = Gtk.Template.Child()
    formatting_expander = Gtk.Template.Child()
    add_tag_button = Gtk.Template.Child()
    start_expander = Gtk.Template.Child()
    start_hour = Gtk.Template.Child()
    start_minute = Gtk.Template.Child()
    start_second = Gtk.Template.Child()
    start_milli = Gtk.Template.Child()
    end_expander = Gtk.Template.Child()
    end_hour = Gtk.Template.Child()
    end_minute = Gtk.Template.Child()
    end_second = Gtk.Template.Child()
    end_milli = Gtk.Template.Child()
    duration_row = Gtk.Template.Child()
    position_group = Gtk.Template.Child()
    margin_l_spin = Gtk.Template.Child()
    margin_r_spin = Gtk.Template.Child()
    margin_v_spin = Gtk.Template.Child()

    def __init__(self):
        super().__init__()

        self.current_entry: SubtitleEntry = None
        self.current_position = -1
        self._updating = False  # Flag to prevent signal loops
        self._text_change_timeout_id = None  # For debouncing text changes
        self._pending_text = None

        self._timing_changed_id = None  # For debouncing timing changes
        self._pending_timing_values = None
        self._position_changed_id = None  # For debouncing position changes
        self._pending_position_values = None

        # Style dropdown model (ASS/SSA only; the row is hidden by default in
        # the template).
        self.style_model = Gtk.StringList.new([])
        self.style_row.set_model(self.style_model)
        self.style_row.connect("notify::selected", self._on_style_selected)

        # Text buffer is created in code and bound to the templated text view.
        # It always holds the clean text (every {...} override block is edited
        # through the Formatting rows, including mid-line ones).
        self.text_buffer = Gtk.TextBuffer()
        self.text_buffer.connect("changed", self._on_text_buffer_changed)
        # Shift the tracked block offsets as the user edits the text; they
        # never emit text-changed themselves (the debounced changed path
        # recomposes after edits, as for any buffer change).
        self.text_buffer.connect("insert-text", self._on_buffer_insert_text)
        self.text_buffer.connect("delete-range", self._on_buffer_delete_range)
        self.text_view.set_buffer(self.text_buffer)

        # Right-click context menu: the text view's own menu (Copy, Paste,
        # Select All, …) with our items appended via extra-menu. A custom
        # popover here popped a second grabbing popup alongside the text
        # view's built-in one, and the contention broke dismissal, item
        # activation and sizing; GTK's menu does all three right.
        self._inline_click_offset = None
        inline_actions = Gio.SimpleActionGroup()
        action = Gio.SimpleAction.new('add', None)
        action.connect('activate', self._on_inline_add_tags)
        inline_actions.add_action(action)
        self.text_view.insert_action_group('text-tags', inline_actions)

        # "Add Formatting Here" is appended for ASS/SSA in
        # set_document_context, once the format is known.
        self._inline_menu = Gio.Menu()
        self.text_view.set_extra_menu(self._inline_menu)

        # The built-in menu pops on right-click by itself; this gesture only
        # records where, so Add Formatting can target the click position
        # (popping anything here would contend with the built-in menu again).
        text_right_click = Gtk.GestureClick.new()
        text_right_click.set_button(3)
        text_right_click.connect('pressed', self._on_text_right_click)
        self.text_view.add_controller(text_right_click)

        # Row count of the leading block's editor; a grown count means a
        # row was added and the group headers must be moved after it.
        self._leading_row_count = 0

        # Visual editor for the leading override block (ASS/SSA only), plus
        # one _TagGroup per additional block, wherever it sits.
        self.tag_editor = TagEditorRows(self.formatting_expander)
        self.tag_editor.connect("changed", self._on_tag_editor_changed)
        self.tag_editor.setup_add_button(self.add_tag_button)
        self._tag_groups: list[_TagGroup] = []

        # Configure the time spin buttons (adjustments + scroll-wheel disabling).
        self._setup_spin_button(self.start_hour, 0, 23)
        self._setup_spin_button(self.start_minute, 0, 59)
        self._setup_spin_button(self.start_second, 0, 59)
        self._setup_spin_button(self.start_milli, 0, 999, 1)
        self._setup_spin_button(self.end_hour, 0, 23)
        self._setup_spin_button(self.end_minute, 0, 59)
        self._setup_spin_button(self.end_second, 0, 59)
        self._setup_spin_button(self.end_milli, 0, 999, 1)

        # Connect timing change signals
        for spin in [
            self.start_hour,
            self.start_minute,
            self.start_second,
            self.start_milli,
            self.end_hour,
            self.end_minute,
            self.end_second,
            self.end_milli,
        ]:
            spin.connect("value-changed", self._on_timing_changed)

        # Position margin spin buttons (ASS/SSA only; group is hidden by default).
        self._setup_margin_spin(self.margin_l_spin)
        self._setup_margin_spin(self.margin_r_spin)
        self._setup_margin_spin(self.margin_v_spin)
        self.margin_l_spin.connect("value-changed", self._on_position_changed)
        self.margin_r_spin.connect("value-changed", self._on_position_changed)
        self.margin_v_spin.connect("value-changed", self._on_position_changed)

        # Initially disabled
        self.set_sensitive(False)

        # ASS/SSA support
        self._format = None
        self._styles = []

    def _setup_spin_button(
        self, spin: Gtk.SpinButton, min_val: int, max_val: int, step: int = 1
    ) -> None:
        """Apply adjustment, numeric mode, width, and scroll-wheel disabling to a
        templated time spin button."""
        adjustment = Gtk.Adjustment(
            value=0,
            lower=min_val,
            upper=max_val,
            step_increment=step,
            page_increment=step * 10,
            page_size=0,
        )
        spin.set_adjustment(adjustment)
        spin.set_numeric(True)
        spin.set_width_chars(5 if max_val >= 100 else 4)

        # Disable scroll wheel to prevent accidental value changes
        scroll_controller = Gtk.EventControllerScroll.new(
            Gtk.EventControllerScrollFlags.BOTH_AXES
        )
        scroll_controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        scroll_controller.connect("scroll", lambda *_: True)
        spin.add_controller(scroll_controller)

    def _setup_margin_spin(self, spin: Gtk.SpinButton) -> None:
        """Configure a position-margin spin button (0-9999)."""
        spin.set_adjustment(Gtk.Adjustment(
            value=0, lower=0, upper=9999, step_increment=1, page_increment=10, page_size=0
        ))
        spin.set_numeric(True)
        spin.set_width_chars(5)

    def set_document_context(self, fmt: SubtitleFormat, style_names: list[str]):
        """Provide document format and styles for style dropdown."""
        self._format = fmt
        self._styles = style_names or ["Default"]

        # Update style dropdown
        self.style_model.splice(0, self.style_model.get_n_items(), self._styles)
        is_ass = fmt in (SubtitleFormat.ASS, SubtitleFormat.SSA)
        self.style_row.set_visible(is_ass)
        self.position_group.set_visible(is_ass)

        # Context menu: append Add Formatting Here only where tags exist.
        self._inline_menu.remove_all()
        if is_ass:
            self._inline_menu.append(_("Add Formatting Here"), 'text-tags.add')

    def set_entry(self, entry: SubtitleEntry, position: int):
        """Set the current entry to edit."""
        self.flush_pending_changes()

        self.current_entry = entry
        self.current_position = position
        self._updating = True

        # Update style (ASS/SSA)
        if self._format in (SubtitleFormat.ASS, SubtitleFormat.SSA):
            try:
                idx = self._styles.index(entry.style or "Default")
            except ValueError:
                idx = 0
            self.style_row.set_selected(idx)
            
            # Update position margins
            self.margin_l_spin.set_value(getattr(entry, 'margin_l', 0))
            self.margin_r_spin.set_value(getattr(entry, 'margin_r', 0))
            self.margin_v_spin.set_value(getattr(entry, 'margin_v', 0))

        # Update text. For ASS/SSA every {...} block is edited through the
        # Formatting rows: the block at offset 0 (if any) through the
        # leading rows, every other block — line-start or mid-line —
        # through its own "Line N tags" group, so the buffer holds clean
        # text only.
        is_ass = self._format in (SubtitleFormat.ASS, SubtitleFormat.SSA)
        if is_ass:
            self._load_tagged_text(entry.text)
        else:
            self._clear_tag_groups()
            self.text_buffer.set_text(entry.text)
            self.tag_editor.load_body(None)
            self._leading_row_count = 0
        self.formatting_expander.set_visible(is_ass)
        self._update_formatting_subtitle()

        # Update start time
        self.start_hour.set_value(entry.start_time.hours)
        self.start_minute.set_value(entry.start_time.minutes)
        self.start_second.set_value(entry.start_time.seconds)
        self.start_milli.set_value(entry.start_time.milliseconds)

        # Update end time
        self.end_hour.set_value(entry.end_time.hours)
        self.end_minute.set_value(entry.end_time.minutes)
        self.end_second.set_value(entry.end_time.seconds)
        self.end_milli.set_value(entry.end_time.milliseconds)

        # Update duration
        self._update_duration()

        self._updating = False
        self.set_sensitive(True)

    def clear(self):
        """Clear the editor."""
        # A cleared editor can belong to a document that was just replaced.
        # Cancel all old sources; callers flush before replacing a document.
        self._cancel_pending_changes()

        self.current_entry = None
        self.current_position = -1
        self._updating = True

        self.text_buffer.set_text("")
        self.tag_editor.load_body(None)
        self._leading_row_count = 0
        self._clear_tag_groups()

        for spin in [
            self.start_hour,
            self.start_minute,
            self.start_second,
            self.start_milli,
            self.end_hour,
            self.end_minute,
            self.end_second,
            self.end_milli,
        ]:
            spin.set_value(0)

        self._updating = False
        self.readability_row.set_subtitle(_("No subtitle selected"))
        self.set_sensitive(False)

    def _cancel_pending_changes(self):
        for timer_attr in ("_text_change_timeout_id", "_timing_changed_id",
                           "_position_changed_id"):
            source_id = getattr(self, timer_attr)
            if source_id is not None:
                GLib.source_remove(source_id)
                setattr(self, timer_attr, None)
        self._pending_text = None
        self._pending_timing_values = None
        self._pending_position_values = None

    def flush_pending_changes(self):
        """Commit debounced edits before a command, save, or entry switch.

        Capture the original position and cancel sources before emitting: a
        signal handler may change selection or refresh this editor.
        """
        position = self.current_position
        text = self._pending_text
        timing = self._pending_timing_values
        margins = self._pending_position_values
        self._cancel_pending_changes()
        if position < 0:
            return
        if text is not None:
            self.emit("text-changed", position, text)
        if timing is not None:
            self.emit("timing-changed", position, *timing)
        if margins is not None:
            self.emit("position-changed", position, *margins)

    def get_split_offset(self) -> int:
        """Text cursor offset (clean text for ASS/SSA, source text for SRT)."""
        return self.text_buffer.get_iter_at_mark(self.text_buffer.get_insert()).get_offset()

    def focus_text(self):
        """Focus the text editor."""
        self.text_view.grab_focus()

    def _on_style_selected(self, *args):
        if self._updating or self.current_position < 0:
            return
        if self._format not in (SubtitleFormat.ASS, SubtitleFormat.SSA):
            return

        idx = int(self.style_row.get_selected())
        if 0 <= idx < len(self._styles):
            self.emit("style-changed", self.current_position, self._styles[idx])

    def _update_duration(self):
        """Update the duration display and time subtitles."""
        start_ms = (
            self.start_hour.get_value_as_int() * 3600000
            + self.start_minute.get_value_as_int() * 60000
            + self.start_second.get_value_as_int() * 1000
            + self.start_milli.get_value_as_int()
        )

        end_ms = (
            self.end_hour.get_value_as_int() * 3600000
            + self.end_minute.get_value_as_int() * 60000
            + self.end_second.get_value_as_int() * 1000
            + self.end_milli.get_value_as_int()
        )

        duration_ms = max(0, end_ms - start_ms)
        duration_sec = duration_ms / 1000.0

        # Format time codes
        start_time_str = f"{self.start_hour.get_value_as_int():02d}:{self.start_minute.get_value_as_int():02d}:{self.start_second.get_value_as_int():02d}.{self.start_milli.get_value_as_int():03d}"
        end_time_str = f"{self.end_hour.get_value_as_int():02d}:{self.end_minute.get_value_as_int():02d}:{self.end_second.get_value_as_int():02d}.{self.end_milli.get_value_as_int():03d}"

        # Update subtitles
        if hasattr(self, "start_expander"):
            self.start_expander.set_subtitle(start_time_str)
        if hasattr(self, "end_expander"):
            self.end_expander.set_subtitle(end_time_str)

        self.duration_row.set_subtitle(f"{duration_sec:.3f} seconds")
        self._update_readability()

    def _update_readability(self):
        if self.current_entry is None:
            return
        start_ms = (self.start_hour.get_value_as_int() * 3600000
                    + self.start_minute.get_value_as_int() * 60000
                    + self.start_second.get_value_as_int() * 1000
                    + self.start_milli.get_value_as_int())
        end_ms = (self.end_hour.get_value_as_int() * 3600000
                  + self.end_minute.get_value_as_int() * 60000
                  + self.end_second.get_value_as_int() * 1000
                  + self.end_milli.get_value_as_int())
        metrics = text_metrics(self._compose_text(), end_ms - start_ms, self._format)
        speed = (_("%.1f characters/s") % metrics.cps if metrics.cps is not None
                 else _("Reading speed unavailable"))
        lengths = ", ".join(str(n) for n in metrics.line_lengths)
        self.readability_row.set_subtitle(
            _("%s · Characters per line: %s") % (speed, lengths))

    def _on_text_buffer_changed(self, text_buffer):
        """Handle text buffer changes with debouncing."""
        if self._updating or self.current_position < 0:
            return

        # The group headers (line numbers/snippets) go stale as the user
        # edits text around a block's anchor; recompute them here — this
        # runs after insert/delete complete, unlike the hook-style
        # insert-text/delete-range handlers that only shift offsets.
        self._refresh_tag_group_headers()
        self._queue_text_change()

    def _load_tagged_text(self, text: str):
        """Split every {...} block out of ``text`` into rows.

        The buffer receives the clean text; the first block at offset 0 (if
        any) keeps its current presentation through ``self.tag_editor``,
        while every other block — line-start or mid-line — gets its own
        nested expander row in the Formatting section, titled after its
        line, with its own add-tag button and a TagEditorRows instance
        inside.
        """
        clean, anchors = split_override_blocks(text)
        leading_body = None
        group_anchors = anchors
        if anchors and anchors[0][0] == 0:
            leading_body = anchors[0][1]
            group_anchors = anchors[1:]

        self._clear_tag_groups()
        self.text_buffer.set_text(clean)
        self.tag_editor.load_body(leading_body)
        self._leading_row_count = len(self.tag_editor.get_rows())

        for offset, body in group_anchors:
            self._insert_tag_group(offset, body)
        self._refresh_tag_group_headers()

    def _refresh_tag_group_headers(self):
        """Recompute each line group's header from the current buffer text.

        Line numbers and snippets go stale as the user edits text around a
        block's anchor, so this runs after every anchor-shifting edit, not
        only at load time. The snippet is the clean text from the block's
        position to the end of its line — what the block applies to — which
        for a line-start block is the whole line.
        """
        if not self._tag_groups:
            return
        start, end = self.text_buffer.get_bounds()
        text = self.text_buffer.get_text(start, end, False)
        for group in self._tag_groups:
            if group.header.get_parent() is None:
                continue
            offset = min(group.offset, len(text))
            line_no = text.count('\n', 0, offset) + 1
            line_end = text.find('\n', offset)
            if line_end == -1:
                line_end = len(text)
            snippet = text[offset:line_end].strip()
            if len(snippet) > 40:
                snippet = snippet[:40].rstrip() + '…'
            group.header.set_title(f"Line {line_no} tags")
            group.header.set_subtitle(snippet or _("(empty line)"))

    def _clear_tag_groups(self):
        """Drop every per-line tag group's header and rows from the panel."""
        for group in self._tag_groups:
            group.editor.load_body(None)
            if group.header.get_parent() is not None:
                self.formatting_expander.remove(group.header)
        self._tag_groups = []

    def _on_buffer_insert_text(self, buffer, location, text, length):
        """Shift tracked block offsets past an insertion.

        Runs before the default handler inserts the text (hook signal), so
        the offsets are shifted in pre-insertion coordinates. Never emits
        text-changed; the debounced changed path recomposes.
        """
        if self._updating or not self._tag_groups:
            return
        position = location.get_offset()
        count = len(text)
        for group in self._tag_groups:
            if group.offset >= position:
                group.offset += count

    def _on_buffer_delete_range(self, buffer, start, end):
        """Shift tracked block offsets across a deletion.

        Runs before the default handler deletes (hook signal), so the range
        iterators carry pre-deletion coordinates. Offsets inside the deleted
        range clamp to the deletion start, so text edits never silently drop
        a block (tags are removed through their rows instead). Never emits
        text-changed.
        """
        if self._updating or not self._tag_groups:
            return
        position = start.get_offset()
        count = end.get_offset() - position
        for group in self._tag_groups:
            if group.offset > position:
                group.offset = max(position, group.offset - count)

    def _compose_text(self) -> str:
        """Full dialogue text: blocks spliced back into the buffer text.

        The leading block (managed by self.tag_editor) is prepended; each
        remaining group's serialized block is inserted at its tracked
        offset, in order, so the recomposed text matches the entry byte for
        byte as long as nothing was edited.
        """
        start = self.text_buffer.get_start_iter()
        end = self.text_buffer.get_end_iter()
        text = self.text_buffer.get_text(start, end, False)

        parts = []
        prev = 0
        for group in self._tag_groups:
            block = group.editor.get_block()
            if block is None:
                continue
            parts.append(text[prev:group.offset])
            parts.append(block)
            prev = group.offset
        parts.append(text[prev:])

        leading = self.tag_editor.get_block()
        return (leading or "") + ''.join(parts)

    def _queue_text_change(self):
        """Debounce a text-changed emission for the recomposed full text.

        A no-op recomposition (identical to the current entry text) never
        schedules an emission, so loading a tagged line and changing nothing
        stays silent.
        """
        if self._updating or self.current_position < 0:
            return

        text = self._compose_text()
        self._update_readability()
        if self.current_entry is not None and text == self.current_entry.text:
            # The buffer now matches the entry, so any scheduled emission is
            # obsolete (e.g. an added {} placeholder was dropped again) and
            # must not fire with its stale snapshot.
            if self._text_change_timeout_id is not None:
                GLib.source_remove(self._text_change_timeout_id)
                self._text_change_timeout_id = None
            self._pending_text = None
            return

        # Cancel any pending timeout
        if self._text_change_timeout_id is not None:
            GLib.source_remove(self._text_change_timeout_id)

        # Store the pending text
        self._pending_text = text

        # Set a new timeout (500ms delay)
        self._text_change_timeout_id = GLib.timeout_add(
            500, self._emit_text_changed
        )

    def _on_tag_editor_changed(self, *args):
        """A formatting row changed: recompose and debounce as a text change."""
        row_count = len(self.tag_editor.get_rows())
        if row_count > self._leading_row_count:
            # A row was added to the leading block: move the group headers
            # after it so the leading block's rows stay together, ahead of
            # the per-line expanders (containers append only).
            self._reorder_tag_group_headers()
        self._leading_row_count = row_count
        self._update_formatting_subtitle()
        self._queue_text_change()

    def _on_tag_group_changed(self, *args):
        """A per-line group's row changed: recompose and debounce."""
        # A group whose last tag was removed drops its {} from recomposition;
        # drop the group entirely, header included, so the expander stays
        # readable and _reorder_tag_group_headers cannot resurrect it.
        for group in list(self._tag_groups):
            if group.editor.get_block() is None:
                self._prune_tag_group(group)
        self._update_formatting_subtitle()
        self._queue_text_change()

    def _update_formatting_subtitle(self):
        """Show the total tag count on the Formatting expander."""
        count = self.tag_editor.get_tag_count() + sum(
            group.editor.get_tag_count() for group in self._tag_groups)
        if count == 0:
            self.formatting_expander.set_subtitle(_("No tags"))
        elif count == 1:
            self.formatting_expander.set_subtitle(_("1 tag"))
        else:
            self.formatting_expander.set_subtitle(f"{count} tags")

    # --- Adding formatting blocks (right-click) --------------------------------

    def _on_text_right_click(self, gesture, n_press, x, y):
        """Record the right-click position for Add Formatting Here.

        The context menu itself is the text view's built-in one (with our
        extra-menu items); this only remembers where it was opened so a
        formatting block can be inserted at the click when nothing is
        selected.
        """
        if self._format in (SubtitleFormat.ASS, SubtitleFormat.SSA):
            buffer_x, buffer_y = self.text_view.window_to_buffer_coords(
                Gtk.TextWindowType.WIDGET, x, y)
            _over_line, iter_at = self.text_view.get_iter_at_location(
                buffer_x, buffer_y)
            self._inline_click_offset = iter_at.get_offset()

    def _on_inline_add_tags(self, action, param):
        """Open the add-formatting dialog at the click (or selection start)."""
        if self.text_buffer.get_has_selection():
            selection_start, _selection_end = self.text_buffer.get_selection_bounds()
            offset = selection_start.get_offset()
        else:
            offset = self._inline_click_offset
            if offset is None:
                return
        self._open_inline_tag_editor(offset)

    def _inline_add_target(self, offset: int):
        """The panel-side target for a block added at ``offset``: None when
        it becomes the leading rows themselves (offset 0 ahead of an empty
        leading block — its presentation at load time), otherwise the new
        group editing it."""
        if offset == 0 and self.tag_editor.get_block() is None:
            return None
        return self._insert_tag_group(offset, None)

    def _open_inline_tag_editor(self, offset: int):
        """Open the dialog adding a formatting block at ``offset``.

        The new block's rows appear in the Formatting section right away
        (the target from _inline_add_target) and every dialog change is
        mirrored into them and the composed text live, through the normal
        debounced text-changed path (so undo keeps working). Closing
        without having added a tag drops them again.
        """
        target_group = self._inline_add_target(offset)

        dialog = Adw.Dialog(title=_("Add Formatting"))
        dialog.set_content_width(420)

        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(
            title=_("Add Formatting"),
            subtitle=_("Changes apply immediately")))
        done_button = Gtk.Button(label=_("Done"))
        done_button.add_css_class('suggested-action')
        done_button.connect('clicked', lambda *_: dialog.close())
        header.pack_end(done_button)
        add_button = Gtk.MenuButton(
            icon_name='list-add-symbolic',
            valign=Gtk.Align.CENTER,
            tooltip_text=_('Add tag'))
        add_button.add_css_class('flat')
        header.pack_start(add_button)

        editor_group = Adw.PreferencesGroup()
        page = Adw.PreferencesPage()
        page.add(editor_group)
        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(header)
        toolbar.set_content(page)
        dialog.set_child(toolbar)

        editor = TagEditorRows(editor_group)
        editor.setup_add_button(add_button)
        editor.connect(
            'changed', lambda *_: self._sync_inline_add(editor, target_group))
        dialog.connect(
            'closed', lambda *_: self._finish_inline_add(editor, target_group))
        dialog.present(self.get_root() or self)

    def _sync_inline_add(self, editor: TagEditorRows, target_group):
        """Mirror the add-dialog's tags into its panel target; recompose.

        A group target is synced here directly (not via
        _on_tag_group_changed) so an emptied group survives while its
        dialog is still open.
        """
        block = editor.get_block()
        target = self.tag_editor if target_group is None else target_group.editor
        target.load_body(block[1:-1] if block else None)
        if target_group is None:
            self._on_tag_editor_changed()
        else:
            self._update_formatting_subtitle()
        self._queue_text_change()

    def _finish_inline_add(self, editor: TagEditorRows, target_group):
        """Drop the reserved rows/group when the dialog closed without tags.

        Recomposition matches the entry again, so the queue call cancels
        any pending emission instead of emitting.
        """
        if editor.get_block() is not None:
            return  # tags were added: everything is already live
        if target_group is None:
            self.tag_editor.load_body(None)
            self._leading_row_count = 0
        else:
            self._prune_tag_group(target_group)
        self._update_formatting_subtitle()
        self._queue_text_change()

    def _insert_tag_group(self, offset: int, body: str) -> "_TagGroup":
        """Add a tag group (nested expander + rows) for the block at ``offset``.

        Shared by the load-time split and the add-formatting dialog; keeps
        both ``_tag_groups`` and the visible headers in offset order
        (recomposition splices blocks in list order, and containers have
        no insert API, so ordering means remove-and-reappend). Adjacent
        blocks share one offset; list order follows document order.
        """
        header = Adw.ExpanderRow()
        header.set_expanded(True)
        add_button = Gtk.MenuButton(
            icon_name='list-add-symbolic',
            valign=Gtk.Align.CENTER,
            tooltip_text=_('Add tag'))
        add_button.add_css_class('flat')
        header.add_suffix(add_button)
        self.formatting_expander.add_row(header)
        editor = TagEditorRows(header)
        editor.load_body(body)
        editor.setup_add_button(add_button)
        editor.connect("changed", self._on_tag_group_changed)

        group = _TagGroup(offset=offset, header=header, editor=editor,
                          add_button=add_button)
        index = len(self._tag_groups)
        for i, existing in enumerate(self._tag_groups):
            if existing.offset > offset:
                index = i
                break
        self._tag_groups.insert(index, group)
        self._reorder_tag_group_headers()
        self._refresh_tag_group_headers()
        self._update_formatting_subtitle()
        # Queue so a group created by the add-formatting dialog recomposes
        # (and cancels any stale pending) as soon as it gains tags; at
        # load time _updating keeps this silent.
        self._queue_text_change()
        return group

    def _prune_tag_group(self, group: "_TagGroup"):
        """Drop a group's header and bookkeeping (it holds no tags)."""
        if group.header.get_parent() is not None:
            self.formatting_expander.remove(group.header)
        if group in self._tag_groups:
            self._tag_groups.remove(group)

    def _reorder_tag_group_headers(self):
        """Re-append every group header in offset order, after other rows.

        Containers append only, so reordering means removing the headers
        and adding them back; this also keeps newly added leading-block
        rows ahead of the per-line group expanders.
        """
        if not self._tag_groups:
            return
        ordered = sorted(self._tag_groups, key=lambda g: g.offset)
        for group in ordered:
            if group.header.get_parent() is not None:
                self.formatting_expander.remove(group.header)
        for group in ordered:
            if group.header.get_parent() is None:
                self.formatting_expander.add_row(group.header)

    def _emit_text_changed(self):
        """Emit the text-changed signal after debounce delay."""
        if self._pending_text is not None and self.current_position >= 0:
            self.emit("text-changed", self.current_position, self._pending_text)
            self._pending_text = None

        self._text_change_timeout_id = None
        return False  # Don't repeat the timeout

    def _on_timing_changed(self, spin_button):
        """Handle timing spin button changes with debouncing."""
        if self._updating or self.current_position < 0:
            return

        # Update duration display immediately
        self._update_duration()

        # Cancel any pending timeout
        if self._timing_changed_id is not None:
            GLib.source_remove(self._timing_changed_id)

        # Create TimeCode objects
        start_time = TimeCode(
            hours=self.start_hour.get_value_as_int(),
            minutes=self.start_minute.get_value_as_int(),
            seconds=self.start_second.get_value_as_int(),
            milliseconds=self.start_milli.get_value_as_int(),
        )

        end_time = TimeCode(
            hours=self.end_hour.get_value_as_int(),
            minutes=self.end_minute.get_value_as_int(),
            seconds=self.end_second.get_value_as_int(),
            milliseconds=self.end_milli.get_value_as_int(),
        )

        # Store the pending values
        self._pending_timing_values = (start_time, end_time)

        # Set a new timeout (300ms delay)
        self._timing_changed_id = GLib.timeout_add(
            300, self._emit_timing_changed
        )

    def _emit_timing_changed(self):
        """Emit timing-changed signal after debounce delay."""
        if self._pending_timing_values is not None and self.current_position >= 0:
            start_time, end_time = self._pending_timing_values
            self.emit("timing-changed", self.current_position, start_time, end_time)
            self._pending_timing_values = None

        self._timing_changed_id = None
        return False  # Don't repeat the timeout

    def _on_position_changed(self, spin_button):
        """Handle position margin changes with debouncing."""
        if self._updating or self.current_position < 0:
            return
        if self._format not in (SubtitleFormat.ASS, SubtitleFormat.SSA):
            return

        # Cancel any pending timeout
        if self._position_changed_id is not None:
            GLib.source_remove(self._position_changed_id)

        margin_l = self.margin_l_spin.get_value_as_int()
        margin_r = self.margin_r_spin.get_value_as_int()
        margin_v = self.margin_v_spin.get_value_as_int()

        # Store the pending values
        self._pending_position_values = (margin_l, margin_r, margin_v)

        # Set a new timeout (300ms delay)
        self._position_changed_id = GLib.timeout_add(
            300, self._emit_position_changed
        )

    def _emit_position_changed(self):
        """Emit position-changed signal after debounce delay."""
        if self._pending_position_values is not None and self.current_position >= 0:
            margin_l, margin_r, margin_v = self._pending_position_values
            self.emit(
                "position-changed",
                self.current_position,
                margin_l,
                margin_r,
                margin_v,
            )
            self._pending_position_values = None

        self._position_changed_id = None
        return False  # Don't repeat the timeout
