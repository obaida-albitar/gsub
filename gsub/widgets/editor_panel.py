"""
Editor panel widget.

Provides text and timing editing for the selected subtitle entry.
"""

import gettext
from dataclasses import dataclass

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Pango", "1.0")

from gi.repository import Adw, GLib, GObject, Gtk, Pango

from gsub.models import SubtitleEntry, SubtitleFormat, TimeCode
from gsub.parsers.ass_tags import (  # noqa: E402
    BLOCK_PATTERN,
    split_line_start_blocks,
)
from gsub.resources import template_resource_path
from gsub.widgets.tag_editor import TagEditorRows  # noqa: E402

# Same translation domain as the package-level gettext.install(); bound
# explicitly so the `_` alias is visible to static analysis.
_ = gettext.translation("gsub", fallback=True).gettext


@dataclass
class _TagGroup:
    """A non-leading line-start block anchored to its offset in the buffer.

    The offset is shifted by buffer edits (see the insert-text/delete-range
    handlers) so recomposition keeps splicing the block back in at its
    position within the (possibly edited) clean text.
    """
    offset: int
    header: Adw.ActionRow
    editor: TagEditorRows


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
        self.text_buffer = Gtk.TextBuffer()
        self.text_buffer.connect("changed", self._on_text_buffer_changed)
        # Shift the tracked line-start block offsets as the user edits the
        # text; they never emit text-changed themselves (the debounced
        # changed path recomposes after edits, as for any buffer change).
        self.text_buffer.connect("insert-text", self._on_buffer_insert_text)
        self.text_buffer.connect("delete-range", self._on_buffer_delete_range)
        self.text_view.set_buffer(self.text_buffer)

        # Text tag used to visually dim mid-line {...} override blocks that
        # stay inline in the text view (only line-start blocks get widgets).
        self._inline_tag = self.text_buffer.create_tag(
            None, foreground="#888a85", style=Pango.Style.ITALIC)

        # Visual editor for the leading override block (ASS/SSA only), plus
        # one _TagGroup per additional line-start block.
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

    def set_entry(self, entry: SubtitleEntry, position: int):
        """Set the current entry to edit."""
        # Flush any pending text changes before switching entries
        if self._text_change_timeout_id is not None:
            GLib.source_remove(self._text_change_timeout_id)
            if self._pending_text is not None and self.current_position >= 0:
                self.emit("text-changed", self.current_position, self._pending_text)
            self._text_change_timeout_id = None
            self._pending_text = None

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

        # Update text. For ASS/SSA every {...} block at a LINE START (offset 0
        # or right after a newline) is edited through the Formatting rows, so
        # the buffer holds clean text on every line; blocks NOT at a line
        # start (mid-word/mid-sentence) stay inline (highlighted, raw-editable).
        is_ass = self._format in (SubtitleFormat.ASS, SubtitleFormat.SSA)
        if is_ass:
            self._load_tagged_text(entry.text)
        else:
            self._clear_tag_groups()
            self.text_buffer.set_text(entry.text)
            self.tag_editor.load_body(None)
        self.formatting_expander.set_visible(is_ass)
        self._apply_inline_tag_highlight()
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
        # Cancel any pending text change
        if self._text_change_timeout_id is not None:
            GLib.source_remove(self._text_change_timeout_id)
            self._text_change_timeout_id = None
        self._pending_text = None

        self.current_entry = None
        self.current_position = -1
        self._updating = True

        self.text_buffer.set_text("")
        self.tag_editor.load_body(None)
        self._clear_tag_groups()
        self._apply_inline_tag_highlight()

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
        self.set_sensitive(False)

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

    def _on_text_buffer_changed(self, text_buffer):
        """Handle text buffer changes with debouncing."""
        if self._updating or self.current_position < 0:
            return

        # Refresh the inline-block highlighting; applying tags does not mark
        # the buffer dirty, so no extra changed signals are emitted.
        self._apply_inline_tag_highlight()
        self._queue_text_change()

    def _load_tagged_text(self, text: str):
        """Split every line-start {...} block out of ``text`` into rows.

        The buffer receives the clean text; the first block at offset 0 (if
        any) keeps its current presentation through ``self.tag_editor``,
        while every other extracted block gets its own group in the
        Formatting expander: a small header naming its line plus a
        TagEditorRows instance. Mid-word blocks stay inline in the buffer
        with the dim/italic highlight.
        """
        clean, anchors = split_line_start_blocks(text)
        leading_body = None
        group_anchors = anchors
        if anchors and anchors[0][0] == 0:
            leading_body = anchors[0][1]
            group_anchors = anchors[1:]

        self._clear_tag_groups()
        self.text_buffer.set_text(clean)
        self.tag_editor.load_body(leading_body)

        for offset, body in group_anchors:
            line = clean.count('\n', 0, offset) + 1
            header = Adw.ActionRow(title=f"Line {line} tags")
            header.set_sensitive(False)
            self.formatting_expander.add_row(header)
            editor = TagEditorRows(self.formatting_expander)
            editor.load_body(body)
            editor.connect("changed", self._on_tag_group_changed)
            self._tag_groups.append(
                _TagGroup(offset=offset, header=header, editor=editor))

    def _clear_tag_groups(self):
        """Drop every per-line tag group's header and rows from the panel."""
        for group in self._tag_groups:
            group.editor.load_body(None)
            if group.header.get_parent() is not None:
                self.formatting_expander.remove(group.header)
        self._tag_groups = []

    def _on_buffer_insert_text(self, buffer, location, text, length):
        """Shift tracked block offsets past an insertion.

        Never emits text-changed; the debounced changed path recomposes.
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

        Offsets inside the deleted range clamp to the deletion start, so
        text edits never silently drop a block (tags are removed through
        their rows instead). Never emits text-changed.
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
        if self.current_entry is not None and text == self.current_entry.text:
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
        self._update_formatting_subtitle()
        self._queue_text_change()

    def _on_tag_group_changed(self, *args):
        """A per-line group's row changed: recompose and debounce."""
        # A group whose last tag was removed drops its {} from recomposition;
        # drop its header too so the expander stays readable.
        for group in self._tag_groups:
            if (group.editor.get_block() is None
                    and group.header.get_parent() is not None):
                self.formatting_expander.remove(group.header)
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

    def _apply_inline_tag_highlight(self):
        """Dim every {...} override block left inline in the text buffer.

        Complete blocks only (stray braces are ordinary text). Uses
        apply_tag/remove_tag, which never move the cursor or emit
        buffer-changed signals.
        """
        buffer = self.text_buffer
        start, end = buffer.get_bounds()
        text = buffer.get_text(start, end, False)
        buffer.remove_tag(self._inline_tag, start, end)
        for match in BLOCK_PATTERN.finditer(text):
            tag_start = buffer.get_iter_at_offset(match.start())
            tag_end = buffer.get_iter_at_offset(match.end())
            buffer.apply_tag(self._inline_tag, tag_start, tag_end)

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
