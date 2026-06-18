"""
Batch file list widget for managing multiple subtitle files.
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, Gio, GObject, GLib
from subtitle_editor.models import SubtitleDocument, SubtitleFormat
from subtitle_editor.logger import get_logger
from subtitle_editor.resources import template_resource_path
import os

logger = get_logger(__name__)


class BatchFileItem(GObject.GObject):
    """Data model for a single file in the batch list."""

    __gtype_name__ = 'BatchFileItem'

    def __init__(self, document: SubtitleDocument, file_path: str):
        super().__init__()
        self.document = document
        self.file_path = file_path
        self.selected = True
        self.modified = False

    @property
    def filename(self):
        return os.path.basename(self.file_path)

    @property
    def format_name(self):
        return self.document.format.value.upper()

    @property
    def entry_count(self):
        return len(self.document.entries)


class BatchFileList(Adw.Bin):
    """
    Widget displaying a list of loaded subtitle files with checkboxes.
    Shows filename, format badge, entry count, and modified status.
    """

    __gsignals__ = {
        'selection-changed': (GObject.SignalFlags.RUN_FIRST, None, ()),
        'files-changed': (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self):
        super().__init__()
        self._files: list[BatchFileItem] = []
        self._build_ui()

    def _build_ui(self):
        self._outer_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        header_box.set_margin_start(12)
        header_box.set_margin_end(12)
        header_box.set_margin_top(12)
        header_box.set_margin_bottom(6)

        header_label = Gtk.Label(label="Files")
        header_label.add_css_class("heading")
        header_box.append(header_label)

        self._file_count_label = Gtk.Label(label="0 files")
        self._file_count_label.add_css_class("dim-label")
        header_box.append(self._file_count_label)

        header_box.append(Gtk.Label(label=""))  # spacer
        header_box.set_hexpand(True)

        self._format_badge = Gtk.Label(label="")
        self._format_badge.add_css_class("dim-label")
        header_box.append(self._format_badge)

        self._outer_box.append(header_box)

        self._list_store = Gio.ListStore.new(BatchFileItem)

        self._list_view = Gtk.ListView.new(
            Gtk.SingleSelection.new(self._list_store),
            self._create_factory()
        )
        self._list_view.set_vexpand(True)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        scrolled.set_child(self._list_view)
        self._outer_box.append(scrolled)

        self._empty_page = Adw.StatusPage()
        self._empty_page.set_title("No Files Loaded")
        self._empty_page.set_description("Add subtitle files to begin batch processing")
        self._empty_page.set_icon_name("folder-multiple-symbolic")

        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self._stack.add_named(self._outer_box, "list")
        self._stack.add_named(self._empty_page, "empty")
        self._stack.set_visible_child_name("empty")

        self.set_child(self._stack)

    def _create_factory(self):
        factory = Gtk.SignalListItemFactory()
        factory.connect('setup', self._on_factory_setup)
        factory.connect('bind', self._on_factory_bind)
        factory.connect('unbind', self._on_factory_unbind)
        return factory

    def _on_factory_setup(self, factory, list_item):
        row = BatchFileRow()
        list_item.set_child(row)

    def _on_factory_bind(self, factory, list_item):
        row = list_item.get_child()
        item = list_item.get_item()
        row.bind(item, self._on_checkbox_toggled)

    def _on_factory_unbind(self, factory, list_item):
        row = list_item.get_child()
        row.unbind()

    def _on_checkbox_toggled(self, item):
        self.emit('selection-changed')

    def add_file(self, document: SubtitleDocument, file_path: str):
        """Add a file to the batch list."""
        item = BatchFileItem(document, file_path)
        self._files.append(item)
        self._list_store.append(item)
        self.update_ui()
        self.emit('files-changed')

    def remove_file(self, item: BatchFileItem):
        """Remove a file from the batch list."""
        found, pos = self._list_store.find(item)
        if found:
            self._list_store.remove(pos)
        self._files.remove(item)
        self.update_ui()
        self.emit('files-changed')

    def clear(self):
        """Remove all files from the batch list."""
        self._list_store.remove_all()
        self._files.clear()
        self.update_ui()
        self.emit('files-changed')

    @property
    def file_count(self):
        return len(self._files)

    def get_selected_files(self) -> list[BatchFileItem]:
        """Get all files that have their checkbox checked."""
        return [f for f in self._files if f.selected]

    def get_all_files(self) -> list[BatchFileItem]:
        """Get all files in the batch list."""
        return list(self._files)

    def update_ui(self):
        """Refresh the UI state (file count, format badge, visibility)."""
        count = len(self._files)
        self._file_count_label.set_text(f"{count} file{'s' if count != 1 else ''}")

        if count == 0:
            self._stack.set_visible_child_name("empty")
            self._format_badge.set_text("")
        else:
            self._stack.set_visible_child_name("list")
            fmt = self._files[0].format_name
            self._format_badge.set_text(f"All {fmt}")


@Gtk.Template(resource_path=template_resource_path('batch-file-row'))
class BatchFileRow(Adw.ActionRow):
    """A single row in the batch file list."""

    __gtype_name__ = 'GsubBatchFileRow'

    check = Gtk.Template.Child()
    format_label = Gtk.Template.Child()
    count_label = Gtk.Template.Child()
    modified_icon = Gtk.Template.Child()

    def __init__(self):
        super().__init__()
        self._item = None
        self._callback = None
        self.check.connect('toggled', self._on_toggled)

    def bind(self, item: BatchFileItem, callback):
        self._item = item
        self._callback = callback
        self.set_title(item.filename)
        self.set_subtitle(item.file_path)
        self.check.set_active(item.selected)
        self.format_label.set_text(item.format_name)
        self.count_label.set_text(f"{item.entry_count} entries")
        self.modified_icon.set_visible(item.modified)

    def unbind(self):
        self._item = None
        self._callback = None

    def _on_toggled(self, check):
        if self._item:
            self._item.selected = check.get_active()
            if self._callback:
                self._callback(self._item)
