"""
Batch file list widget for managing multiple subtitle files.
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, Gio, GObject
from gsub.models import SubtitleDocument
from gsub.logger import get_logger
from gsub.resources import template_resource_path
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


@Gtk.Template(resource_path=template_resource_path('batch-file-list'))
class BatchFileList(Adw.Bin):
    """
    Widget displaying a list of loaded subtitle files with checkboxes.
    Shows filename, format badge, entry count, and modified status.
    """

    __gtype_name__ = 'GsubBatchFileList'

    __gsignals__ = {
        'selection-changed': (GObject.SignalFlags.RUN_FIRST, None, ()),
        'files-changed': (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    stack = Gtk.Template.Child()
    file_count_label = Gtk.Template.Child()
    format_badge = Gtk.Template.Child()
    list_view = Gtk.Template.Child()
    empty_page = Gtk.Template.Child()

    def __init__(self):
        super().__init__()
        self._files: list[BatchFileItem] = []

        self._list_store = Gio.ListStore.new(BatchFileItem)
        self.list_view.set_model(Gtk.SingleSelection.new(self._list_store))
        self.list_view.set_factory(self._create_factory())

        self.update_ui()

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
        self.file_count_label.set_text(f"{count} file{'s' if count != 1 else ''}")

        if count == 0:
            self.stack.set_visible_child_name("empty")
            self.format_badge.set_text("")
        else:
            self.stack.set_visible_child_name("list")
            formats = {f.format_name for f in self._files}
            if len(formats) == 1:
                self.format_badge.set_text(f"All {next(iter(formats))}")
            else:
                self.format_badge.set_text("Mixed")


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
