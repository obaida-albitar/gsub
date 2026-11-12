"""Save/discard continuations and crash recovery for the main window."""

import os
import time

from gi.repository import Adw, GLib

from gsub.logger import get_logger
from gsub.recovery import RecoveredBatch, RecoveryStore, atomic_write_text

logger = get_logger(__name__)


class SaveWorkflowMixin:
    """Keep asynchronous save decisions in one place for every entry point."""

    def _init_save_workflow(self):
        self._save_guard_active = False
        self._close_confirmed = False
        self._recovery_store = RecoveryStore(os.path.join(self._get_config_dir(), "recovery"))
        # Previous sessions live separately from the current session, so
        # choosing Later never disables protection for newly edited work.
        self._recovery_unresolved = False
        if self._recovery_store.path.exists():
            pending = self._recovery_store.path.with_name(f"pending-{time.time_ns()}.json")
            try:
                os.replace(self._recovery_store.path, pending)
            except OSError as error:
                logger.warning("Could not preserve previous recovery snapshot: %s", error)
                self._recovery_unresolved = True
        self._pending_recovery_stores = [
            RecoveryStore(self._recovery_store.path.parent, path.name)
            for path in sorted(self._recovery_store.path.parent.glob("pending-*.json"))]
        self._recovery_restoring = False
        self._recovery_error_reported = False
        self._recovery_debounce_id = None
        self._save_dialog_pending = False
        self.batch_file_list.confirm_removal = self._request_batch_removal
        self._recovery_timer = GLib.timeout_add_seconds(10, self._autosave_recovery)
        GLib.idle_add(self._offer_recovery)

    def _dirty_batch_items(self):
        return [item for item in self.batch_file_list.get_all_files()
                if item.modified or item.document.modified]

    def _request_document_replacement(self, continuation, include_batch=False, include_editor=True):
        """Run only after all relevant changes have been saved or discarded."""
        self.editor_panel.flush_pending_changes()
        if self._save_guard_active or self._save_dialog_pending:
            return False
        dirty_editor = include_editor and self.document is not None and self.document.modified
        dirty_batch = self._dirty_batch_items() if include_batch else []
        if not dirty_editor and not dirty_batch:
            continuation()
            return True
        self._snapshot_recovery()
        self._save_guard_active = True
        names = ([os.path.basename(self.current_file) if self.current_file else "Untitled"]
                 if dirty_editor else []) + [item.filename for item in dirty_batch]
        body = "Save changes before continuing?\n" + "\n".join(names[:8])
        if len(names) > 8:
            body += f"\n…and {len(names) - 8} more files"
        dialog = Adw.MessageDialog.new(self, "Unsaved Changes", body)
        dialog.add_response("save", "Save All" if len(names) > 1 else "Save")
        dialog.add_response("discard", "Discard")
        dialog.add_response("cancel", "Cancel")
        dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_response_appearance("discard", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("save")
        dialog.set_close_response("cancel")
        dialog.connect("response", lambda _dialog, response:
                       self._resolve_unsaved_response(response, continuation, include_batch,
                                                      include_editor))
        self._save_guard_dialog = dialog
        dialog.present()
        return False

    def _resolve_unsaved_response(self, response, continuation, include_batch=False,
                                  include_editor=True):
        if response == "discard":
            document = self.document if include_editor else None
            was_modified = bool(document and document.modified)
            batch = [(item, item.modified, item.document.modified)
                     for item in self._dirty_batch_items()] if include_batch else []
            if document is not None:
                document.modified = False
            for item, _, _ in batch:
                item.modified = item.document.modified = False
            self._save_guard_active = False
            result = continuation()
            # An unsupported/missing file must not erase the old dirty state.
            if result is False:
                if self.document is document and document is not None:
                    document.modified = was_modified
                for item, modified, doc_modified in batch:
                    item.modified, item.document.modified = modified, doc_modified
            self._snapshot_recovery()
            self._update_title()
            return
        if response != "save":
            self._save_guard_active = False
            return

        save_editor = include_editor and self.document is not None and self.document.modified
        if save_editor and include_batch:
            try:
                # Check before writing either version of a shared file.
                self._batch_save_plan(self._dirty_batch_items(), self.document)
            except (OSError, ValueError, TypeError) as error:
                self._save_guard_active = False
                self._show_error(f"Cannot save all changes: {error}")
                return

        def after_editor(saved):
            if saved and include_batch:
                saved = self._save_batch_items(self._dirty_batch_items(),
                    protected_document=self.document if save_editor else None)
            self._save_guard_active = False
            if saved:
                continuation()

        if save_editor:
            if self.current_file:
                after_editor(self._save_document(self.current_file))
            else:
                self._on_save_as(None, None, on_complete=after_editor)
        else:
            after_editor(True)

    def _request_batch_removal(self, items, continuation):
        """Give dirty batch removals the same three-way decision as closing."""
        dirty = [item for item in items if item.modified or item.document.modified]
        if not dirty:
            continuation()
            return
        if self._save_guard_active:
            return
        self._snapshot_recovery()
        self._save_guard_active = True
        dialog = Adw.MessageDialog.new(self, "Unsaved Changes",
            f"Save changes to {len(dirty)} file(s) before removing them?")
        dialog.add_response("save", "Save")
        dialog.add_response("discard", "Discard")
        dialog.add_response("cancel", "Cancel")
        dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_response_appearance("discard", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("save")
        dialog.set_close_response("cancel")

        def respond(_dialog, response):
            self._save_guard_active = False
            if response == "discard" or (response == "save" and self._save_batch_items(dirty)):
                continuation()
                self._snapshot_recovery()

        dialog.connect("response", respond)
        self._save_guard_dialog = dialog
        dialog.present()

    def _batch_save_plan(self, items, protected_document=None):
        """Reject different unsaved versions targeting the same physical file."""
        targets = {}
        if protected_document is None and self.document is not None and self.document.modified:
            protected_document = self.document
        if protected_document is not None:
            path = (self.current_file if protected_document is self.document
                    else protected_document.file_path)
            if path:
                targets[os.path.realpath(path)] = self._batch_content(protected_document)
        plan = []
        for item in items:
            path, content = os.path.realpath(item.file_path), self._batch_content(item.document)
            if path in targets and targets[path] != content:
                raise ValueError(
                    f"Different unsaved versions target {os.path.basename(item.file_path)}. "
                    "Use Save As to give one version a different destination, then try again.")
            targets[path] = content
            plan.append((item, content))
        return plan

    def _save_batch_items(self, items, protected_document=None):
        try:
            plan = self._batch_save_plan(items, protected_document)
        except (OSError, ValueError, TypeError) as error:
            self._show_error(f"Cannot save batch changes: {error}")
            return False
        success = True
        saved = 0
        for item, content in plan:
            try:
                atomic_write_text(item.file_path, content)
                item.modified = item.document.modified = False
                self._batch_saved_content[id(item)] = content
                saved += 1
            except Exception as error:
                self._show_error(f"Error saving {item.filename}: {error}")
                success = False
        if saved:
            self._show_toast(f"Saved {saved} file{'s' if saved != 1 else ''}")
        self._update_batch_status()
        self._snapshot_recovery()
        return success

    def _on_close_request(self, window):
        if self._close_confirmed:
            self._save_window_state()
            self._snapshot_recovery()
            self._stop_recovery_timer()
            return False
        if self._save_dialog_pending or self._save_guard_active:
            return True
        self.editor_panel.flush_pending_changes()
        if not (self.document and self.document.modified) and not self._dirty_batch_items():
            self._save_window_state()
            self._snapshot_recovery()
            self._stop_recovery_timer()
            return False
        self._request_document_replacement(self._finish_guarded_close, include_batch=True)
        return True

    def _finish_guarded_close(self):
        self._close_confirmed = True
        self.close()

    def _stop_recovery_timer(self):
        for name in ("_recovery_timer", "_recovery_debounce_id"):
            source = getattr(self, name, None)
            if source is not None:
                GLib.source_remove(source)
                setattr(self, name, None)

    def _queue_recovery(self):
        if (hasattr(self, "_recovery_store")
                and self._recovery_debounce_id is None):
            self._recovery_debounce_id = GLib.timeout_add(1000, self._flush_queued_recovery)

    def _flush_queued_recovery(self):
        self._recovery_debounce_id = None
        self._snapshot_recovery()
        return GLib.SOURCE_REMOVE

    def _autosave_recovery(self):
        self.editor_panel.flush_pending_changes()
        self._snapshot_recovery()
        return GLib.SOURCE_CONTINUE

    def _snapshot_recovery(self):
        if (not hasattr(self, "_recovery_store") or self._recovery_unresolved
                or self._recovery_restoring):
            return False
        editor = self.document if self.document and self.document.modified else None
        batch = [RecoveredBatch(item.document, item.file_path, item.selected,
                                self._batch_saved_content.get(id(item)))
                 for item in self._dirty_batch_items()]
        try:
            self._recovery_store.save(editor, batch)
            self._recovery_error_reported = False
            return True
        except (OSError, ValueError, TypeError) as error:
            logger.warning("Could not save recovery snapshot: %s", error)
            if not self._recovery_error_reported:
                self._show_toast("Recovery copy could not be updated. Save your work manually.")
                self._recovery_error_reported = True
            return False

    def _offer_recovery(self):
        if not self._pending_recovery_stores:
            return GLib.SOURCE_REMOVE
        store = self._pending_recovery_stores.pop(0)
        try:
            session = store.load()
        except (OSError, ValueError) as error:
            logger.warning("Could not load recovery snapshot: %s", error)
            # Keep the unreadable data for inspection instead of destroying it.
            try:
                os.replace(store.path, store.path.with_suffix(".invalid"))
            except OSError:
                pass
            self._show_toast("A recovery copy could not be read; it was kept for inspection.")
            GLib.idle_add(self._offer_recovery)
            return GLib.SOURCE_REMOVE
        if session is None:
            GLib.idle_add(self._offer_recovery)
            return GLib.SOURCE_REMOVE
        count = int(session.editor is not None) + len(session.batch)
        dialog = Adw.MessageDialog.new(self, "Restore Unsaved Work?",
            f"Recovery copies of {count} unsaved document(s) are available. "
            "Restoring them will not change the original files.")
        dialog.add_response("restore", "Restore")
        dialog.add_response("discard", "Discard Recovery Copies")
        dialog.add_response("later", "Later")
        dialog.set_response_appearance("restore", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_response_appearance("discard", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("restore")
        dialog.set_close_response("later")

        def respond(_dialog, response):
            if response == "restore":
                def restore():
                    restored = self._restore_recovery(session)
                    if restored:
                        try:
                            store.clear()
                        except OSError as error:
                            logger.warning("Could not remove restored recovery snapshot: %s", error)
                    return restored
                self._request_document_replacement(
                    restore, include_batch=bool(session.batch),
                    include_editor=session.editor is not None)
            elif response == "discard":
                try:
                    store.clear()
                    self._snapshot_recovery()
                except OSError as error:
                    self._show_error(f"Could not discard recovery copies: {error}")
            GLib.idle_add(self._offer_recovery)

        dialog.connect("response", respond)
        self._recovery_dialog = dialog
        dialog.present()
        return GLib.SOURCE_REMOVE

    def _restore_recovery(self, session):
        self.editor_panel.flush_pending_changes()
        previous_document, previous_file = self.document, self.current_file
        previous_batch = self.batch_file_list.get_all_files()
        previous_baselines = dict(self._batch_saved_content)
        previous_batch_format = self.batch_format
        previous_selection = self.subtitle_list.get_selected_positions()
        histories = [(manager, list(manager._undo_stack), list(manager._redo_stack))
                     for manager in (self.command_manager, self.batch_command_manager)]
        self._recovery_restoring = True
        restored = False
        try:
            if session.editor is not None:
                self.editor_panel.flush_pending_changes()
                self._close_document_dialogs()
                self.document = session.editor
                self.document.modified = True
                self.current_file = self.document.file_path
                self.command_manager.clear()
                self.subtitle_list.set_document(self.document)
                self._reset_playback_highlight()
                self.list_stack.set_visible_child_name("list")
                self.editor_panel.set_document_context(self.document.format,
                                                       [s.name for s in self.document.styles])
                self.editor_panel.clear()
                self.video_player.set_document(self.document)
                self._update_title()
                self._update_status()
                self._update_format_actions()
                self._update_document_actions()
                self._update_undo_redo_buttons()
                self._refresh_compat()
                self._navigate_to_editor()
            if session.batch:
                self.batch_file_list.clear()
                for recovered in session.batch:
                    self.batch_file_list.add_file(recovered.document, recovered.file_path)
                    item = self.batch_file_list.get_all_files()[-1]
                    item.selected = recovered.selected
                    item.document.modified = item.modified = True
                    self._batch_saved_content[id(item)] = (
                        recovered.saved_content if recovered.saved_content is not None else "")
                self.batch_format = session.batch[0].document.format
                self.batch_command_manager.clear()
                self.batch_file_list.update_ui()
                self._refresh_batch_context()
                self._update_batch_action_buttons()
                self._update_undo_redo_buttons()
                if session.editor is None:
                    self._navigate_to_batch()
            self._recovery_unresolved = False
            self._show_toast("Unsaved work restored. Save to keep your changes.")
            restored = True
        except Exception as error:
            # UI/media failures must never leave half of a recovered session
            # installed. Restore model references before attempting UI repair,
            # so even a second widget failure cannot discard current work.
            self.document, self.current_file = previous_document, previous_file
            self.batch_file_list._files = previous_batch
            self.batch_file_list._list_store.splice(
                0, self.batch_file_list._list_store.get_n_items(), previous_batch)
            self._batch_saved_content = previous_baselines
            self.batch_format = previous_batch_format
            for manager, undo, redo in histories:
                manager._undo_stack, manager._redo_stack = undo, redo
            try:
                self.subtitle_list.set_document(previous_document)
                self.editor_panel.clear()
                if previous_document is not None:
                    self.editor_panel.set_document_context(previous_document.format,
                        [style.name for style in previous_document.styles])
                    for index, position in enumerate(previous_selection):
                        self.subtitle_list.select_entry(position, clear_others=index == 0)
                self.list_stack.set_visible_child_name(
                    "list" if previous_document is not None else "empty")
                self.batch_file_list.update_ui()
                self._refresh_batch_context()
                self._update_batch_action_buttons()
                self._update_title()
                self._update_status()
                self._update_format_actions()
                self._update_document_actions()
                self._update_undo_redo_buttons()
                self._refresh_compat()
            except Exception:
                logger.exception("Could not fully redraw the original session after failed recovery")
            try:
                self.video_player.set_document(previous_document)
            except Exception:
                logger.exception("Could not restore video preview after failed recovery")
            self._show_error(f"Could not restore recovery copies: {error}")
        finally:
            self._recovery_restoring = False
        return restored and self._snapshot_recovery()
