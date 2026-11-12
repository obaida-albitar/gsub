"""
Batch file list widget for managing multiple subtitle files.
"""

import gettext

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, Gio, GLib, GObject, Gdk
from gsub.models import SubtitleDocument
from gsub.logger import get_logger
from gsub.resources import template_resource_path
import os

# Same translation domain as the package-level gettext.install(); bound
# explicitly so the `_` alias is visible to static analysis.
_ = gettext.translation('gsub', fallback=True).gettext

logger = get_logger(__name__)


class BatchFileItem(GObject.GObject):
    """Data model for a single file in the batch list."""

    __gtype_name__ = 'BatchFileItem'
    modified = GObject.Property(type=bool, default=False)

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
        # The application supplies Save/Discard/Cancel; standalone widgets
        # retain their existing clear-all confirmation.
        self.confirm_removal = None

        self._list_store = Gio.ListStore.new(BatchFileItem)
        self._selection = Gtk.SingleSelection.new(self._list_store)
        self.list_view.set_model(self._selection)
        self.list_view.set_factory(self._create_factory())

        self._setup_context_menu()

        self.update_ui()

    def _setup_context_menu(self):
        """Right-click menu + Delete keys for removing files.

        Menu items target widget-local actions; the Delete accelerators are
        shown as plain menu attributes because they are dispatched by this
        widget's key controller, never registered as application accels.
        The controller consumes Delete before the window's bubble-phase
        window-key dispatch (win.remove-entry) can see it.
        """
        actions = Gio.SimpleActionGroup()
        remove_action = Gio.SimpleAction.new('remove-file', None)
        remove_action.connect('activate', lambda *a: self.remove_selected())
        clear_action = Gio.SimpleAction.new('clear-all', None)
        clear_action.connect('activate', lambda *a: self._request_clear_all())
        actions.add_action(remove_action)
        actions.add_action(clear_action)
        self.insert_action_group('batch-list', actions)

        menu = Gio.Menu()
        remove_item = Gio.MenuItem.new(_('Remove File'), 'batch-list.remove-file')
        remove_item.set_attribute_value('accel', GLib.Variant.new_string('Delete'))
        menu.append_item(remove_item)
        clear_item = Gio.MenuItem.new(_('Clear All'), 'batch-list.clear-all')
        clear_item.set_attribute_value(
            'accel', GLib.Variant.new_string('<Ctrl><Shift>Delete'))
        menu.append_item(clear_item)

        self.context_popover = Gtk.PopoverMenu.new_from_model(menu)
        self.context_popover.set_has_arrow(False)
        self.context_popover.set_parent(self.list_view)

        right_click = Gtk.GestureClick.new()
        right_click.set_button(3)
        right_click.connect('pressed', self._on_right_click)
        self.list_view.add_controller(right_click)

        key_controller = Gtk.EventControllerKey.new()
        key_controller.connect('key-pressed', self._on_key_pressed)
        self.list_view.add_controller(key_controller)

    def _on_right_click(self, gesture, n_press, x, y):
        """Select the row under the pointer and show the context menu."""
        if self.file_count == 0:
            return
        self._select_row_at(x, y)
        rect = Gdk.Rectangle()
        rect.x = x
        rect.y = y
        rect.width = 1
        rect.height = 1
        self.context_popover.set_pointing_to(rect)
        self.context_popover.popup()

    def _select_row_at(self, x, y):
        """Move the list selection to the row widget under (x, y)."""
        widget = self.list_view.pick(x, y, Gtk.PickFlags.DEFAULT)
        while widget is not None and not isinstance(widget, BatchFileRow):
            widget = widget.get_parent()
        item = widget.get_item() if widget is not None else None
        if item is not None:
            found, pos = self._list_store.find(item)
            if found:
                self._selection.select_item(pos, True)

    def _on_key_pressed(self, controller, keyval, keycode, state):
        """Delete removes the selected file; Ctrl+Shift+Delete clears all.

        Consumed here (bubble phase, closer to the focus than the window's
        key controller) so the win.remove-entry window key never fires
        while the batch list has focus.
        """
        if self.file_count == 0:
            return False
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(state & Gdk.ModifierType.SHIFT_MASK)
        if keyval == Gdk.KEY_Delete:
            if ctrl and shift:
                self._request_clear_all()
                return True
            if not ctrl and not shift:
                self.remove_selected()
                return True
        return False

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

    def get_selected_item(self) -> BatchFileItem | None:
        """The item currently selected in the list view."""
        return self._selection.get_selected_item()

    def remove_selected(self):
        """Remove the file selected in the list view (context menu / Delete)."""
        item = self.get_selected_item()
        if item is not None:
            if self.confirm_removal is not None:
                self.confirm_removal([item], lambda: self.remove_file(item))
            else:
                self.remove_file(item)

    def _request_clear_all(self):
        """Clear the list, confirming first when unsaved changes exist."""
        if self.confirm_removal is not None:
            self.confirm_removal(self.get_all_files(), self.clear)
            return
        if any(f.modified for f in self._files):
            dialog = Adw.AlertDialog.new(
                _('Remove All Files?'),
                _('Some files have unsaved changes that will be lost.'))
            dialog.add_response('cancel', _('Cancel'))
            dialog.add_response('remove', _('Remove All'))
            dialog.set_response_appearance(
                'remove', Adw.ResponseAppearance.DESTRUCTIVE)
            dialog.choose(self.get_root() or self, None,
                          self._on_clear_all_response)
        else:
            self.clear()

    def _on_clear_all_response(self, dialog, result):
        try:
            if dialog.choose_finish(result) == 'remove':
                self.clear()
        except Exception:
            pass  # Dialog dismissed

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
        self._modified_handler = None
        self.check.connect('toggled', self._on_toggled)

    def do_grab_focus(self):
        """Focus the interactive checkbox without requiring a ListBox parent."""
        return self.check.grab_focus()

    def bind(self, item: BatchFileItem, callback):
        self.unbind()
        self._item = item
        self._callback = callback
        self.set_title(item.filename)
        self.set_subtitle(item.file_path)
        self.check.set_active(item.selected)
        self.format_label.set_text(item.format_name)
        self.count_label.set_text(f"{item.entry_count} entries")
        self.modified_icon.set_visible(item.modified)
        self._modified_handler = item.connect(
            "notify::modified", lambda obj, _pspec: self.modified_icon.set_visible(obj.modified))

    def unbind(self):
        if self._item is not None and self._modified_handler is not None:
            self._item.disconnect(self._modified_handler)
        self._modified_handler = None
        self._item = None
        self._callback = None

    def get_item(self) -> BatchFileItem | None:
        """The item currently bound to this row (None when recycled)."""
        return self._item

    def _on_toggled(self, check):
        if self._item:
            self._item.selected = check.get_active()
            if self._callback:
                self._callback(self._item)
