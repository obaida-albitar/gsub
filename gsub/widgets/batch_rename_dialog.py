"""
Naming-pattern dialog for batch "Save All As…".
"""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Adw

from gsub.batch_logic import expand_output_names
from gsub.resources import template_resource_path


@Gtk.Template(resource_path=template_resource_path("batch-rename-dialog"))
class BatchRenameDialog(Adw.Dialog):
    """Lets the user choose an output naming pattern before batch saving.

    The pattern is expanded per file (:func:`expand_output_names`) with a
    live preview of the resulting names. Saving is blocked while the
    expanded names collide (they must stay unique within the batch).
    """

    __gtype_name__ = "GsubBatchRenameDialog"

    pattern_row = Gtk.Template.Child()
    preview_group = Gtk.Template.Child()
    save_button = Gtk.Template.Child()

    # Rows beyond this many are summarized as "and N more" instead of listed.
    PREVIEW_LIMIT = 8

    def __init__(self, parent_window, filenames: list[str]):
        super().__init__()

        self.parent_window = parent_window
        self._filenames = list(filenames)
        self._confirmed = False
        self._preview_rows = []

        self.pattern_row.set_text("{name}")
        self.pattern_row.connect("changed", lambda row: self._refresh_preview())
        self._refresh_preview()

    def get_output_names(self) -> list[str]:
        """Expanded output name for each file, in the order given."""
        return expand_output_names(self.pattern_row.get_text(), self._filenames)

    def is_confirmed(self) -> bool:
        return self._confirmed

    def _refresh_preview(self):
        for row in self._preview_rows:
            self.preview_group.remove(row)
        self._preview_rows = []

        names = self.get_output_names()
        shown = min(len(names), self.PREVIEW_LIMIT)
        for original, new in zip(self._filenames[:shown], names[:shown]):
            row = Adw.ActionRow()
            row.set_title(new)
            if new != original:
                row.set_subtitle(original)
            row.set_activatable(False)
            self.preview_group.add(row)
            self._preview_rows.append(row)

        if len(names) > shown:
            more = Adw.ActionRow()
            more.set_title(f"…and {len(names) - shown} more")
            more.set_activatable(False)
            self.preview_group.add(more)
            self._preview_rows.append(more)

        unique = len(set(names)) == len(names)
        if not unique:
            clash = Adw.ActionRow()
            clash.set_title("Duplicate output names — try a base name instead of {name}")
            clash.set_activatable(False)
            icon = Gtk.Image.new_from_icon_name("dialog-warning-symbolic")
            icon.add_css_class("warning-color")
            clash.add_prefix(icon)
            self.preview_group.add(clash)
            self._preview_rows.append(clash)

        self.save_button.set_sensitive(unique)

    @Gtk.Template.Callback()
    def on_cancel_clicked(self, _button):
        self.close()

    @Gtk.Template.Callback()
    def on_save(self, _button):
        self._confirmed = True
        self.close()
