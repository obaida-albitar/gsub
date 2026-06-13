"""
Confirmation dialog for batch operations.
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, GObject


class BatchConfirmDialog(Adw.Dialog):
    """Confirmation dialog showing summary of batch operations before applying."""

    def __init__(self, parent_window, file_count: int, operation_summary: list[str],
                 selected_count: int, format_name: str):
        super().__init__()

        self.parent_window = parent_window
        self._confirmed = False

        self.set_title("Confirm Batch Operations")
        self.set_content_width(500)
        self.set_content_height(400)

        toolbar_view = Adw.ToolbarView()
        self.set_child(toolbar_view)

        header = Adw.HeaderBar()
        header.set_show_title(False)
        toolbar_view.add_top_bar(header)

        cancel_button = Gtk.Button(label="Cancel")
        cancel_button.connect('clicked', lambda b: self.close())
        header.pack_start(cancel_button)

        apply_button = Gtk.Button(label="Apply")
        apply_button.add_css_class("suggested-action")
        apply_button.connect('clicked', self._on_apply)
        header.pack_end(apply_button)

        prefs_page = Adw.PreferencesPage()
        prefs_page.set_vexpand(True)
        toolbar_view.set_content(prefs_page)

        # Summary group
        summary_group = Adw.PreferencesGroup()
        summary_group.set_title("Changes to Apply")
        summary_group.set_description(
            f"Applying to {selected_count} of {file_count} {format_name} file{'s' if file_count != 1 else ''}"
        )
        prefs_page.add(summary_group)

        if operation_summary:
            for line in operation_summary:
                row = Adw.ActionRow()
                row.set_title(line)
                icon = Gtk.Image.new_from_icon_name("emblem-ok-symbolic")
                icon.add_css_class("success-color")
                row.add_prefix(icon)
                row.set_activatable(False)
                summary_group.add(row)
        else:
            row = Adw.ActionRow()
            row.set_title("No operations configured")
            row.set_activatable(False)
            summary_group.add(row)

        # Files group
        files_group = Adw.PreferencesGroup()
        files_group.set_title("Files Affected")
        prefs_page.add(files_group)

        files_label = Gtk.Label(label=f"{selected_count} file{'s' if selected_count != 1 else ''} will be modified")
        files_label.set_margin_start(12)
        files_label.set_margin_end(12)
        files_label.set_margin_bottom(12)
        files_label.add_css_class("dim-label")
        files_group.add(files_label)

    def _on_apply(self, button):
        self._confirmed = True
        self.close()

    def is_confirmed(self) -> bool:
        return self._confirmed
