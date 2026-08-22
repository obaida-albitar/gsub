"""
Confirmation dialog for batch operations.
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw

from gsub.resources import template_resource_path


@Gtk.Template(resource_path=template_resource_path('batch-confirm-dialog'))
class BatchConfirmDialog(Adw.Dialog):
    """Confirmation dialog showing summary of batch operations before applying."""

    __gtype_name__ = 'GsubBatchConfirmDialog'

    summary_group = Gtk.Template.Child()
    files_label = Gtk.Template.Child()

    def __init__(self, parent_window, file_count: int, operation_summary: list[str],
                 selected_count: int, format_name: str):
        super().__init__()

        self.parent_window = parent_window
        self._confirmed = False

        # Summary group description (depends on counts + format).
        self.summary_group.set_description(
            f"Applying to {selected_count} of {file_count} {format_name} "
            f"file{'s' if file_count != 1 else ''}"
        )

        if operation_summary:
            for line in operation_summary:
                row = Adw.ActionRow()
                row.set_title(line)
                icon = Gtk.Image.new_from_icon_name("emblem-ok-symbolic")
                icon.add_css_class("success-color")
                row.add_prefix(icon)
                row.set_activatable(False)
                self.summary_group.add(row)
        else:
            row = Adw.ActionRow()
            row.set_title("No operations configured")
            row.set_activatable(False)
            self.summary_group.add(row)

        self.files_label.set_label(
            f"{selected_count} file{'s' if selected_count != 1 else ''} will be modified"
        )

    @Gtk.Template.Callback()
    def on_cancel_clicked(self, _button):
        self.close()

    @Gtk.Template.Callback()
    def on_apply(self, _button):
        self._confirmed = True
        self.close()

    def is_confirmed(self) -> bool:
        return self._confirmed
