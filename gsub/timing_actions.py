"""Window actions for timing a subtitle directly from the video playhead."""

from gsub.commands import EditTimingCommand
from gsub.models import TimeCode
from gsub.timing import timing_at_playhead


class TimingActionsMixin:
    """Action handlers shared by the editor's buttons, menu and shortcuts."""

    def _timing_selection(self):
        if not self.current_video_file or not self.document:
            self._show_toast("Open a video and select a subtitle first")
            return None
        player = self.video_player
        if ((hasattr(player, "_mpv") and player._mpv is None)
                or getattr(player, "_pending_load_path", None) is not None):
            self._show_toast("Wait for the video player to finish loading")
            return None
        self.editor_panel.flush_pending_changes()
        positions = self.subtitle_list.get_selected_positions()
        if len(positions) != 1 or not 0 <= positions[0] < len(self.document.entries):
            self._show_toast("Select exactly one subtitle")
            return None
        return positions[0]

    def _set_timing_from_playhead(self, endpoint):
        position = self._timing_selection()
        if position is None:
            return
        entry = self.document.entries[position]
        try:
            start, end = timing_at_playhead(
                entry, self.video_player.get_position(), endpoint, self.document.format,
                getattr(self.video_player, "_duration", None))
        except ValueError as error:
            self._show_toast(str(error))
            return
        if (start, end) == (entry.start_time.total_milliseconds,
                            entry.end_time.total_milliseconds):
            return
        command = EditTimingCommand(self.document, position,
                                    TimeCode.from_milliseconds(start),
                                    TimeCode.from_milliseconds(end))
        self.command_manager.execute(command)
        self.subtitle_list.refresh_entry(position)
        self.editor_panel.set_entry(entry, position)
        self._update_title()
        self._document_mutated()
        self.video_player.queue_subtitle_redraw()
        self.video_player.refresh_timeline_regions()

    def _on_set_start_here(self, _action=None, _param=None):
        self._set_timing_from_playhead("start")

    def _on_set_end_here(self, _action=None, _param=None):
        self._set_timing_from_playhead("end")

    def _on_play_cue(self, _action=None, _param=None):
        position = self._timing_selection()
        if position is None:
            return
        self.video_player.set_selected_position(position)
        if not self.video_player.play_selected_cue(loop=False):
            self._show_toast("Could not play this subtitle; check its timing and loaded video")

    def _on_loop_cue(self, _action=None, _param=None):
        if getattr(self.video_player, "cue_looping", False):
            self.video_player.clear_cue_playback(pause=True)
            return
        position = self._timing_selection()
        if position is None:
            return
        self.video_player.set_selected_position(position)
        if not self.video_player.play_selected_cue(loop=True):
            self._show_toast("Could not loop this subtitle; check its timing and loaded video")
