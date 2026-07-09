"""
Video player widget with subtitle overlay powered by libmpv.

Video is decoded and rendered by mpv (libmpv). Subtitles are rendered by
libass *inside* mpv itself, which gives frame-accurate timing and faithful
ASS/SSA styling that matches real-world players.

The editor document is serialized to a temporary subtitle file and fed to mpv
(added as an external track, reloaded on edit). This removes the custom cue
binary-search and the 250ms polling timer that previously caused some lines to
be missed, while keeping the preview in sync with editor changes via a short
debounce.
"""

import gi
import locale
import os
import tempfile
import threading
from typing import Optional

from subtitle_editor.logger import get_logger

logger = get_logger(__name__)

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

import ctypes

from gi.repository import Adw, Gdk, GLib, GObject, Gtk

# PyOpenGL provides a portable way to bridge mpv's render context with the
# Gtk.GLArea's GL context: it resolves GL functions through GLX on X11 and
# EGL on Wayland.
from mpv import MPV, MpvRenderContext, MpvGlGetProcAddressFn

# libmpv stomps on the numeric locale, which breaks number parsing elsewhere.
locale.setlocale(locale.LC_NUMERIC, "C")

from subtitle_editor.extractors import (
    extract_track,
    list_subtitle_tracks,
)
from subtitle_editor.models import SubtitleDocument, SubtitleFormat
from subtitle_editor.parsers.ass_parser import ASSParser
from subtitle_editor.parsers.srt_parser import SRTParser
from subtitle_editor.resources import template_resource_path

_DEBOUNCE_MS = 120


# Map mpv-reported subtitle codec names to our internal family. mpv uses the
# same codec vocabulary as FFmpeg/PyAV for the common text subtitle codecs.
_MPV_CODEC_FAMILIES = {
    "ass": "ass",
    "ssa": "ssa",
    "subrip": "srt",
    "srt": "srt",
    "text": "srt",
    "mov_text": "srt",
}


def _mpv_codec_family(codec: Optional[str]) -> Optional[str]:
    return _MPV_CODEC_FAMILIES.get((codec or "").lower())


def _family_matches(a: Optional[str], b: Optional[str]) -> bool:
    """True when two codec families are compatible for matching.

    ``ass`` and ``ssa`` are interchangeable (same container representation).
    """
    if a is None or b is None:
        return False
    if a == b:
        return True
    return a in ("ass", "ssa") and b in ("ass", "ssa")


def _detect_egl():
    """Return True when running on a Wayland display (EGL backend)."""
    try:
        display = Gdk.Display.get_default()
        return display is not None and "wayland" in (display.get_name() or "").lower()
    except Exception:
        return False


def _make_get_proc_address():
    """Build an mpv-compatible OpenGL get-proc-address callback.

    Resolves GL functions through GLX on X11 and EGL on Wayland. Also returns
    a helper that reads the currently bound draw framebuffer (used by mpv's
    render call), via the matching native GL library.
    """
    use_egl = _detect_egl()
    provider = None
    gl_lib = None

    if not use_egl:
        try:
            from OpenGL import GLX

            def _glx_get(name):
                return GLX.glXGetProcAddress(name.decode("utf-8"))

            provider = _glx_get
            try:
                gl_lib = ctypes.CDLL("libGL.so.1")
            except OSError:
                gl_lib = None
        except (AttributeError, ImportError):
            provider = None

    if provider is None:
        try:
            from OpenGL import EGL

            def _egl_get(name):
                return EGL.eglGetProcAddress(name.decode("utf-8"))

            provider = _egl_get
        except (AttributeError, ImportError):
            provider = None
        # glGetIntegerv for GLES lives in libGLESv2.
        for soname in ("libGLESv2.so.2", "libGLESv2.so.1", "libGLESv2.so"):
            try:
                gl_lib = ctypes.CDLL(soname)
                break
            except OSError:
                continue

    if provider is None:
        raise RuntimeError("Cannot initialize OpenGL: no GLX or EGL available")

    def wrapper(_ctx, name):
        address = provider(name)
        return ctypes.cast(address, ctypes.c_void_p).value

    def get_draw_fbo():
        if gl_lib is None:
            return 0
        try:
            gl_lib.glGetIntegerv.restype = None
            gl_lib.glGetIntegerv.argtypes = [ctypes.c_uint, ctypes.POINTER(ctypes.c_int)]
            out = ctypes.c_int(0)
            gl_lib.glGetIntegerv(0x8CA6, ctypes.byref(out))  # GL_DRAW_FRAMEBUFFER_BINDING
            return out.value
        except Exception:
            return 0

    return MpvGlGetProcAddressFn(wrapper), get_draw_fbo


@Gtk.Template(resource_path=template_resource_path("video-player"))
class VideoPlayerWidget(Gtk.Box):
    """Video player widget that renders subtitles through libmpv."""

    __gtype_name__ = "GsubVideoPlayer"

    __gsignals__ = {
        "position-changed": (GObject.SignalFlags.RUN_FIRST, None, (float,)),
        "duration-changed": (GObject.SignalFlags.RUN_FIRST, None, (float,)),
        "state-changed": (GObject.SignalFlags.RUN_FIRST, None, (bool,)),  # True=playing
    }

    # Template children.
    video_frame = Gtk.Template.Child()
    video_area = Gtk.Template.Child()
    controls_box = Gtk.Template.Child()
    play_button = Gtk.Template.Child()
    time_label = Gtk.Template.Child()
    timeline_scale = Gtk.Template.Child()
    duration_label = Gtk.Template.Child()
    volume_button = Gtk.Template.Child()
    volume_scale = Gtk.Template.Child()
    subtitle_size_button = Gtk.Template.Child()

    def __init__(self):
        super().__init__()

        self.document: Optional[SubtitleDocument] = None
        self._video_path: Optional[str] = None
        self._is_seeking = False
        self._duration = 0.0

        # Track management
        self._audio_tracks = []
        self._subtitle_tracks = []
        self._current_audio_track = -1
        self._current_subtitle_track = -1
        self._tracks_detected = False
        self._mpv_track_list = []
        # Maps the position in ``_subtitle_tracks`` (mpv's subtitle list) to the
        # matching PyAV ``SubtitleTrack`` so extraction uses the correct
        # container stream index (mpv's own track id is NOT the stream index).
        self._pyav_track_map = {}
        # Path the mapping was built for, so we only probe the file once.
        self._pyav_video_path = None
        # Generation token: bumped on every (re)schedule so a stale background
        # build (e.g. one kicked off with an empty track list) cannot overwrite
        # a newer, correct mapping.
        self._pyav_mapping_gen = 0

        # Editor subtitle feeding
        self._temp_sub_path: Optional[str] = None
        self._editor_sub_id = None
        self._redraw_source = None

        # mpv state
        self._mpv = None
        self._render_ctx = None
        self._get_draw_fbo = None
        self._disposed = False

        try:
            self._mpv = MPV(
                vo="libmpv",
                log_handler=self._mpv_log,
                loglevel="warn",
                keep_open="yes",
                osd_level="0",
                hr_seek="yes",
                video_timing_offset="0",
                sub_visibility="yes",
            )
        except Exception as exc:  # pragma: no cover - depends on libmpv presence
            logger.error(f"Failed to initialise mpv: {exc}")
            self._show_error_state()
            return

        self._mpv.observe_property("time-pos", self._on_mpv_time_pos)
        self._mpv.observe_property("duration", self._on_mpv_duration)
        self._mpv.observe_property("pause", self._on_mpv_pause)
        self._mpv.observe_property("eof-reached", self._on_mpv_eof)
        self._mpv.observe_property("track-list", self._on_mpv_track_list)
        self._mpv.observe_property("sid", self._on_mpv_sid)

        self.video_area.set_auto_render(False)
        self.video_area.connect("realize", self._on_glarea_realize)
        self.video_area.connect("unrealize", self._on_glarea_unrealize)
        self.video_area.connect("render", self._on_glarea_render)
        self.connect("unrealize", self._on_widget_unrealize)

        self._wire_controls()
        self._setup_key_controller()

    # ------------------------------------------------------------------ #
    # mpv logging
    # ------------------------------------------------------------------ #
    def _mpv_log(self, level, prefix, text):
        logger.debug(f"[mpv:{level}] {prefix}: {text}")

    # ------------------------------------------------------------------ #
    # Gtk.GLArea <-> mpv render context embedding
    # ------------------------------------------------------------------ #
    def _on_glarea_realize(self, area):
        area.make_current()
        if self._mpv is None:
            return
        try:
            callback, self._get_draw_fbo = _make_get_proc_address()
            self._render_ctx = MpvRenderContext(
                self._mpv,
                "opengl",
                opengl_init_params={"get_proc_address": callback},
            )
            self._render_ctx.update_cb = self._on_mpv_update
        except Exception as exc:  # pragma: no cover - depends on GL stack
            logger.error(f"Failed to create mpv render context: {exc}")
            self._render_ctx = None
        area.queue_render()

    def _on_mpv_update(self):
        if self._render_ctx is not None and not self._disposed:
            GLib.idle_add(self._schedule_render)

    def _schedule_render(self):
        if self._disposed or self._render_ctx is None:
            return
        self.video_area.queue_render()

    def _on_glarea_render(self, area, context):
        if self._render_ctx is None:
            return False
        factor = area.get_scale_factor()
        width = int(area.get_width() * factor)
        height = int(area.get_height() * factor)
        fbo = self._get_draw_fbo()
        try:
            self._render_ctx.render(
                flip_y=True,
                opengl_fbo={"w": width, "h": height, "fbo": fbo},
                block_for_target_time=False,
            )
        except Exception as exc:  # pragma: no cover
            logger.debug(f"mpv render error: {exc}")
        return True

    def _on_glarea_unrealize(self, area):
        if self._render_ctx is not None:
            try:
                self._render_ctx.free()
            except Exception:  # pragma: no cover
                pass
            self._render_ctx = None

    # ------------------------------------------------------------------ #
    # Public API (kept compatible with window.py)
    # ------------------------------------------------------------------ #
    def set_document(self, document: Optional[SubtitleDocument]):
        """Set the subtitle document to preview."""
        self.document = document
        # Drop any previously-added editor track (and its temp file) so a fresh
        # one is created on the next sync. This also clears the preview when an
        # empty document is set (e.g. "New File").
        self._remove_editor_sub(remove_temp=True)
        self._sync_editor_sub()
        if self._mpv is not None:
            GLib.idle_add(self.video_area.queue_render)

    def load_video(self, file_path: str):
        """Load a video file into mpv."""
        if self._mpv is None:
            return

        self._video_path = file_path
        self._editor_sub_id = None
        self._audio_tracks = []
        self._subtitle_tracks = []
        self._mpv_track_list = []
        self._tracks_detected = False
        # Reset the user's track selection so a fresh video starts clean
        # (editor document selected by default, no stale embedded track).
        self._current_audio_track = -1
        self._current_subtitle_track = -1

        try:
            self._mpv.loadfile(file_path)
            self._mpv.pause = True
        except Exception as exc:
            logger.error(f"mpv loadfile failed: {exc}")

        try:
            # The preview is editor-centric: do not auto-show an embedded
            # subtitle track (mpv defaults to "auto"). With no editor document
            # loaded this keeps the preview subtitle-free; once a document is
            # set, its external track is selected instead.
            if not (self.document and self.document.entries):
                self._mpv.sid = False
        except Exception:
            pass

        # Feed the editor document (if any) as an external subtitle track.
        self._sync_editor_sub()
        GLib.idle_add(self.video_area.queue_render)

    def play(self):
        """Start playback."""
        if self._mpv is not None:
            self._mpv.pause = False

    def pause(self):
        """Pause playback."""
        if self._mpv is not None:
            self._mpv.pause = True

    def toggle_play_pause(self):
        """Toggle between play and pause."""
        if self._mpv is not None:
            self._mpv.pause = not self._mpv.pause

    def seek(self, position_sec: float):
        """Seek to a specific position in seconds (accurate)."""
        if self._mpv is None:
            return
        try:
            self._mpv.seek(position_sec, reference="absolute", precision="exact")
        except Exception as exc:
            logger.error(f"mpv seek failed: {exc}")
        GLib.idle_add(self.video_area.queue_render)

    def skip(self, offset_ms: int):
        """Skip forward or backward by offset in milliseconds."""
        if self._mpv is None:
            return
        self.seek(max(0.0, self.get_position() + offset_ms / 1000.0))

    def get_position(self) -> float:
        """Get current playback position in seconds."""
        if self._mpv is None:
            return 0.0
        try:
            value = self._mpv.time_pos
            return float(value) if value is not None else 0.0
        except Exception:
            return 0.0

    # ------------------------------------------------------------------ #
    # mpv property observers
    # ------------------------------------------------------------------ #
    def _on_mpv_time_pos(self, _name, value):
        if value is None or self._disposed:
            return
        GLib.idle_add(self._update_position_ui, float(value))

    def _on_mpv_duration(self, _name, value):
        if value is None or self._disposed:
            return
        GLib.idle_add(self._set_duration, float(value))

    def _on_mpv_pause(self, _name, value):
        if self._disposed:
            return
        GLib.idle_add(self._set_pause_ui, bool(value))

    def _on_mpv_eof(self, _name, value):
        if value and not self._disposed:
            GLib.idle_add(self._on_eof_ui)

    def _on_mpv_track_list(self, _name, value):
        if self._disposed:
            return
        GLib.idle_add(self._update_tracks, value or [])

    def _on_mpv_sid(self, _name, value):
        if self._disposed:
            return
        # mpv applies its ``sid=auto`` default *after* the file finishes
        # loading, which would otherwise auto-show an embedded subtitle. When
        # no editor document is loaded and the user has not explicitly picked
        # an embedded track, force the selection back to "none". mpv reports a
        # concrete selected track as a positive integer (and the disabled
        # state as ``False`` / ``"no"``), so only re-disable on a positive
        # selection; setting ``sid=False`` re-fires this observer with
        # ``False`` (which is skipped), so there is no loop.
        if (
            not (self.document and self.document.entries)
            and self._current_subtitle_track < 0
            and isinstance(value, int)
            and value > 0
        ):
            try:
                self._mpv.sid = False
            except Exception:
                pass

    def _update_position_ui(self, pos):
        if self._disposed:
            return
        self.time_label.set_text(self._format_time(pos))
        if not self._is_seeking:
            self.timeline_scale.set_value(pos)
        self.emit("position-changed", pos)

    def _set_duration(self, duration):
        if self._disposed:
            return
        self._duration = duration
        self.timeline_scale.set_range(0, duration)
        self.duration_label.set_text(self._format_time(duration))
        self.emit("duration-changed", duration)

    def _set_pause_ui(self, paused):
        if self._disposed:
            return
        icon = "media-playback-start-symbolic" if paused else "media-playback-pause-symbolic"
        self.play_button.set_icon_name(icon)
        self.emit("state-changed", not paused)

    def _on_eof_ui(self):
        if self._disposed:
            return
        try:
            self.seek(0)
            self.pause()
        except Exception:
            pass

    @staticmethod
    def _parse_tracks(track_list):
        """Split an mpv ``track-list`` into (audio, subtitle) info dicts.

        External subtitle tracks are excluded (they are the editor document,
        added separately). Each dict mirrors the keys returned by
        :meth:`get_available_tracks`.
        """
        audio = []
        sub = []
        for t in track_list:
            ttype = t.get("type")
            if ttype == "audio":
                audio.append({
                    "id": t.get("id"),
                    "index": t.get("id"),
                    "title": t.get("title"),
                    "language": t.get("lang"),
                    "codec": t.get("codec"),
                })
            elif ttype == "sub" and not t.get("external"):
                sub.append({
                    "id": t.get("id"),
                    "index": t.get("id"),
                    "title": t.get("title"),
                    "language": t.get("lang"),
                    "codec": t.get("codec"),
                })
        return audio, sub

    def _update_tracks(self, track_list):
        if self._disposed:
            return
        self._mpv_track_list = track_list
        self._audio_tracks, self._subtitle_tracks = self._parse_tracks(track_list)
        self._tracks_detected = True
        # Build the PyAV stream mapping in the background (it opens & probes the
        # file, which must not block the GTK main thread / contend with mpv).
        self._schedule_pyav_mapping()
        # The preview is editor-centric: do not let mpv's "auto" default show an
        # embedded subtitle. This is re-asserted here (not only at load time)
        # because mpv applies its default *after* the file finishes loading,
        # which would override an earlier sid disable set right after loadfile().
        # It is skipped once the user explicitly picks an embedded track or an
        # editor document is loaded (whose external track is selected instead).
        if not (self.document and self.document.entries) and self._current_subtitle_track < 0:
            try:
                self._mpv.sid = False
            except Exception:
                pass
        # Resolve/repair the editor subtitle track id whenever it is still
        # unknown but a document is loaded (e.g. after a (re)load or a swap).
        # Skip when the user explicitly chose an embedded track.
        if (
            self._editor_sub_id is None
            and self._current_subtitle_track < 0
            and self._temp_sub_path
            and self.document
            and self.document.entries
        ):
            self._resolve_editor_sub_id()

    def _schedule_pyav_mapping(self):
        """Build the PyAV stream mapping once per loaded video, off the UI thread."""
        if self._disposed or not self._video_path or not self._subtitle_tracks:
            return
        if self._pyav_video_path == self._video_path and self._pyav_track_map:
            return  # already built for this video
        self._pyav_video_path = self._video_path
        snapshot = list(self._subtitle_tracks)
        path = self._video_path
        # Capture the current generation so an older build (started before the
        # tracks were fully populated) cannot clobber this one.
        gen = self._pyav_mapping_gen + 1
        self._pyav_mapping_gen = gen

        def build():
            if self._disposed or self._pyav_mapping_gen != gen:
                return
            mapping = self._build_pyav_mapping(snapshot, path)
            if (
                mapping
                and not self._disposed
                and self._video_path == path
                and self._pyav_mapping_gen == gen
            ):
                self._pyav_track_map = mapping

        threading.Thread(target=build, daemon=True).start()

    @staticmethod
    def _build_pyav_mapping(sub_tracks, path):
        """Associate each mpv subtitle track with its PyAV container stream.

        Both mpv and PyAV enumerate subtitle streams in container order, so the
        position in each list is the primary key. Language/codec matching is
        only a fallback for when the lists disagree (e.g. a missing stream),
        because matching by language first would collapse several tracks that
        share a language onto the same PyAV stream.
        """
        if not path or not sub_tracks:
            return {}
        try:
            pyav_tracks = list_subtitle_tracks(path)
        except Exception as exc:  # pragma: no cover - depends on file/ffmpeg
            logger.debug(f"Could not list PyAV subtitle tracks: {exc}")
            return {}

        mapping = {}
        for pos, ms in enumerate(sub_tracks):
            lang = (ms.get("language") or "").lower()
            fam = _mpv_codec_family(ms.get("codec"))
            match = None
            # Primary: same position in both subtitle-only, ordered lists.
            if pos < len(pyav_tracks):
                cand = pyav_tracks[pos]
                if fam is None or _family_matches(cand.codec_family, fam):
                    match = cand
            # Fallback: language + codec family match (used when positions
            # disagree, e.g. a stream is missing from one backend).
            if match is None:
                for t in pyav_tracks:
                    if (not lang or (t.language or "").lower() == lang) and (
                        fam is None or _family_matches(t.codec_family, fam)
                    ):
                        match = t
                        break
            if match is not None:
                mapping[pos] = match
        return mapping

    # ------------------------------------------------------------------ #
    # Editor subtitle feeding
    # ------------------------------------------------------------------ #
    def _subtitle_suffix(self):
        if self.document and self.document.format in (SubtitleFormat.ASS, SubtitleFormat.SSA):
            return ".ass"
        return ".srt"

    def _rewrite_temp_sub(self):
        if not self._temp_sub_path or not self.document:
            return
        try:
            if self.document.format in (SubtitleFormat.ASS, SubtitleFormat.SSA):
                text = ASSParser.serialize(self.document)
            else:
                text = SRTParser.serialize(self.document)
            with open(self._temp_sub_path, "w", encoding="utf-8") as fh:
                fh.write(text)
        except Exception as exc:
            logger.error(f"Failed to write subtitle temp file: {exc}")

    def _live_track_list(self):
        """Return the current mpv track-list, preferring the live property.

        The cached ``_mpv_track_list`` is only updated by the observer, which
        lags behind command calls such as ``sub_add``; reading the live
        property avoids acting on a stale list right after an add/remove.
        """
        if self._mpv is None:
            return self._mpv_track_list
        try:
            tl = self._mpv.track_list
            if tl:
                return tl
        except Exception:
            pass
        return self._mpv_track_list

    def _find_editor_sub_id(self):
        """Return the mpv track id of the managed external subtitle, or None.

        Matches on ``external-filename`` exactly, or by basename as a fallback
        in case mpv canonicalises the path (e.g. resolving symlinks).
        """
        if self._temp_sub_path is None:
            return None
        base = os.path.basename(self._temp_sub_path)
        for t in self._live_track_list():
            if t.get("type") == "sub" and t.get("external"):
                fn = t.get("external-filename") or ""
                if fn == self._temp_sub_path or fn.endswith(base):
                    return t.get("id")
        return None

    def _remove_editor_sub(self, remove_temp=False):
        """Remove the editor subtitle track from mpv.

        When *remove_temp* is True the temporary subtitle file is also deleted
        so the next sync recreates it with the correct suffix (used when the
        document format changes, e.g. ASS -> SRT).
        """
        if self._mpv is not None and not self._disposed:
            sid = self._find_editor_sub_id()
            if sid is not None:
                try:
                    self._mpv.sub_remove(sid)
                except Exception as exc:
                    logger.debug(f"mpv sub_remove failed: {exc}")
        self._editor_sub_id = None
        if remove_temp and self._temp_sub_path and os.path.exists(self._temp_sub_path):
            try:
                os.remove(self._temp_sub_path)
            except OSError:
                pass
            self._temp_sub_path = None

    def _select_editor_sub(self):
        """Select the editor subtitle track when no embedded one is chosen."""
        if self._current_subtitle_track < 0 and self._editor_sub_id is not None:
            try:
                self._mpv.sid = self._editor_sub_id
            except Exception:
                pass

    def _sync_editor_sub(self):
        """Create or replace the editor document as an external sub track."""
        if self._mpv is None or self._disposed:
            return

        if self.document is None or not self.document.entries:
            self._remove_editor_sub(remove_temp=False)
            return

        if self._temp_sub_path is None:
            fd, path = tempfile.mkstemp(suffix=self._subtitle_suffix())
            os.close(fd)
            self._temp_sub_path = path
        self._rewrite_temp_sub()

        # Replace the editor subtitle track with a freshly-added copy of the
        # current document. Re-adding (after removing the previous track) is
        # more reliable than ``sub-reload``, which can silently fail to re-read
        # the file on some mpv builds and leave the preview blank.
        self._remove_editor_sub(remove_temp=False)
        try:
            self._mpv.sub_add(self._temp_sub_path, "select")
        except Exception as exc:
            logger.error(f"mpv sub_add failed: {exc}")
            return
        self._resolve_editor_sub_id()

        # Keep the editor sub selected and preserve the user's size preference.
        self._select_editor_sub()
        try:
            self._mpv.sub_scale = self._load_subtitle_scale_preference()
        except Exception:
            pass

        # Force a repaint so paused previews reflect the change immediately,
        # independent of mpv's update callback firing.
        self.video_area.queue_render()

    def _resolve_editor_sub_id(self):
        if self._temp_sub_path is None:
            return
        self._editor_sub_id = self._find_editor_sub_id()
        if self._editor_sub_id is not None:
            self._select_editor_sub()

    def queue_subtitle_redraw(self):
        """Reload the editor subtitle into mpv, debounced for fast editing."""
        if self._disposed:
            return
        if self._redraw_source is not None:
            GLib.source_remove(self._redraw_source)
        self._redraw_source = GLib.timeout_add(_DEBOUNCE_MS, self._do_subtitle_redraw)

    def _do_subtitle_redraw(self):
        self._redraw_source = None
        if self._disposed:
            return False
        self._sync_editor_sub()
        return False

    # ------------------------------------------------------------------ #
    # Track selection
    # ------------------------------------------------------------------ #
    def get_available_tracks(self):
        """Return (audio_tracks, subtitle_tracks) lists of info dicts."""
        return (list(self._audio_tracks), list(self._subtitle_tracks))

    def set_audio_track(self, track_index):
        """Select an audio track by mpv track id (-1 disables)."""
        if self._mpv is not None:
            try:
                self._mpv.aid = -1 if (track_index is None or track_index < 0) else track_index
            except Exception as exc:
                logger.error(f"set_audio_track failed: {exc}")
            GLib.idle_add(self.video_area.queue_render)
        self._current_audio_track = track_index

    def set_subtitle_track(self, track_index):
        """Select a subtitle track by mpv track id (-1 shows the editor doc)."""
        self._current_subtitle_track = -1 if track_index is None else track_index
        if self._mpv is None:
            return
        if track_index is None or track_index < 0:
            if self._editor_sub_id is not None:
                try:
                    self._mpv.sid = self._editor_sub_id
                except Exception:
                    pass
            else:
                # "None" with no editor document: explicitly disable subtitles
                # (mpv defaults to auto-selecting an embedded track).
                try:
                    self._mpv.sid = False
                except Exception:
                    pass
        else:
            try:
                self._mpv.sid = track_index
            except Exception as exc:
                logger.error(f"set_subtitle_track failed: {exc}")
        GLib.idle_add(self.video_area.queue_render)

    def has_embedded_tracks(self):
        """Return (has_audio, has_subtitles) once tracks are detected."""
        if self._mpv is None or not self._tracks_detected:
            return (False, False)
        return (len(self._audio_tracks) > 0, len(self._subtitle_tracks) > 0)

    @property
    def current_audio_track(self):
        return self._current_audio_track

    @property
    def current_subtitle_track(self):
        return self._current_subtitle_track

    def _local_path(self):
        """Return the local filesystem path for the loaded video, or ``None``."""
        return self._video_path

    @staticmethod
    def _subtitle_track_pos(tracks, track_id):
        """Map an mpv subtitle track ``id`` to its position in *tracks*.

        Track-selection dialogs hand back the mpv track id (``track-list``
        ``id``), which is not the same as the list position, so callers must
        resolve it before indexing ``_subtitle_tracks`` / ``_pyav_track_map``.
        """
        for pos, t in enumerate(tracks):
            if t.get("id") == track_id or t.get("index") == track_id:
                return pos
        return None

    def subtitle_track_format(self, track_id):
        """Return the output format of a subtitle track ('ass'/'ssa'/'srt').

        *track_id* is the mpv subtitle track id (as returned by the selection
        dialog), not a list position.
        """
        pos = self._subtitle_track_pos(self._subtitle_tracks, track_id)
        if pos is None:
            return None
        mapped = self._pyav_track_map.get(pos)
        if mapped is not None:
            return mapped.codec_family
        return _mpv_codec_family(self._subtitle_tracks[pos].get("codec"))

    def extract_subtitle_track(self, track_id, output_path, callback=None):
        """Extract a subtitle track from the video to a file (background).

        *track_id* is the mpv subtitle track id (as returned by the selection
        dialog), not a list position.
        """
        if self._mpv is None or not self._video_path:
            if callback:
                callback(False, "No video loaded", None)
            return

        pos = self._subtitle_track_pos(self._subtitle_tracks, track_id)
        if pos is None or pos >= len(self._subtitle_tracks):
            if callback:
                callback(False, "Invalid track index", None)
            return

        video_path = self._local_path()
        # Snapshot the track list so the worker thread reads a stable copy.
        sub_tracks_snapshot = list(self._subtitle_tracks)

        def extract_thread():
            # Use the background-built mapping if available, otherwise build it
            # here (still off the UI thread) so extraction works even if the
            # scheduled mapping for this video has not finished yet.
            mapping = self._pyav_track_map
            if not mapping or self._pyav_video_path != video_path:
                mapping = self._build_pyav_mapping(sub_tracks_snapshot, video_path) or {}
            mapped = mapping.get(pos)
            try:
                if mapped is not None:
                    fmt = extract_track(video_path, mapped.index, output_path)
                else:
                    # Fallback: resolve the container stream from the track's
                    # language/codec when no mapping was built.
                    from subtitle_editor.extractors import extract_track_by_gst

                    fmt = extract_track_by_gst(
                        video_path, sub_tracks_snapshot[pos], output_path
                    )
                if callback:
                    GLib.idle_add(callback, True, None, fmt)
            except Exception as e:
                logger.error(f"Extraction failed: {e}")
                if callback:
                    GLib.idle_add(callback, False, str(e), None)

        thread = threading.Thread(target=extract_thread, daemon=True)
        thread.start()

    # ------------------------------------------------------------------ #
    # Controls
    # ------------------------------------------------------------------ #
    def _wire_controls(self):
        self.timeline_scale.set_range(0, 100)
        self.timeline_scale.set_value(0)
        self.timeline_scale.connect("change-value", self._on_timeline_seek)

        self.volume_scale.set_range(0, 1)
        self.volume_scale.set_value(1.0)
        self.volume_scale.connect("value-changed", self._on_volume_changed)

        popover = Gtk.Popover()
        popover_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        popover_box.set_margin_start(12)
        popover_box.set_margin_end(12)
        popover_box.set_margin_top(12)
        popover_box.set_margin_bottom(12)

        scale_label = Gtk.Label(label="Subtitle Size")
        scale_label.add_css_class("heading")
        popover_box.append(scale_label)

        scale_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.subtitle_scale_slider = Gtk.Scale()
        self.subtitle_scale_slider.set_range(0.5, 1.5)
        saved_scale = self._load_subtitle_scale_preference()
        self.subtitle_scale_slider.set_value(saved_scale)
        self.subtitle_scale_slider.set_draw_value(True)
        self.subtitle_scale_slider.set_value_pos(Gtk.PositionType.RIGHT)
        self.subtitle_scale_slider.set_digits(2)
        self.subtitle_scale_slider.set_size_request(200, -1)
        self.subtitle_scale_slider.connect("value-changed", self._on_subtitle_scale_changed)

        self.subtitle_scale_slider.add_mark(0.5, Gtk.PositionType.BOTTOM, None)
        self.subtitle_scale_slider.add_mark(0.75, Gtk.PositionType.BOTTOM, "Default")
        self.subtitle_scale_slider.add_mark(1.5, Gtk.PositionType.BOTTOM, None)

        scale_box.append(self.subtitle_scale_slider)
        popover_box.append(scale_box)

        reset_button = Gtk.Button(label="Reset to Default")
        reset_button.connect("clicked", lambda b: self.subtitle_scale_slider.set_value(0.75))
        popover_box.append(reset_button)

        popover.set_child(popover_box)
        self.subtitle_size_button.set_popover(popover)

        # Apply the initial scale to mpv once available.
        if self._mpv is not None:
            try:
                self._mpv.sub_scale = saved_scale
            except Exception:
                pass

    def _show_error_state(self):
        status_page = Adw.StatusPage()
        status_page.set_icon_name("dialog-error-symbolic")
        status_page.set_title("Video Player Unavailable")
        status_page.set_description(
            "libmpv is required for video playback. Please install the mpv library (libmpv)."
        )
        status_page.set_vexpand(True)
        if self.video_frame is not None:
            self.video_frame.set_visible(False)
        if self.controls_box is not None:
            self.controls_box.set_visible(False)
        self.append(status_page)

    @staticmethod
    def _format_time(seconds: float) -> str:
        seconds = float(seconds)
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        if hours > 0:
            return f"{hours}:{minutes:02d}:{secs:02d}"
        return f"{minutes}:{secs:02d}"

    @Gtk.Template.Callback()
    def on_skip_back(self, _button):
        self.skip(-5000)

    @Gtk.Template.Callback()
    def on_skip_forward(self, _button):
        self.skip(5000)

    @Gtk.Template.Callback()
    def on_play_pause(self, _button):
        self.toggle_play_pause()

    def _on_timeline_seek(self, scale, scroll_type, value):
        if not self._is_seeking:
            self._is_seeking = True
            GLib.timeout_add(50, lambda: setattr(self, "_is_seeking", False))
        self.seek(value)
        return False

    def _on_volume_changed(self, scale):
        value = scale.get_value()
        if self._mpv is not None:
            try:
                self._mpv.volume = value * 100
            except Exception:
                pass

    def _on_subtitle_scale_changed(self, scale):
        value = scale.get_value()
        if self._mpv is not None:
            try:
                self._mpv.sub_scale = value
            except Exception:
                pass
        self._save_subtitle_scale_preference(value)

    def _setup_key_controller(self):
        key_controller = Gtk.EventControllerKey()
        key_controller.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_controller)

    def _on_key_pressed(self, controller, keyval, keycode, state):
        if keyval in (Gdk.KEY_plus, Gdk.KEY_equal, Gdk.KEY_KP_Add):
            current = self.subtitle_scale_slider.get_value()
            self.subtitle_scale_slider.set_value(min(current + 0.05, 1.5))
            return True
        elif keyval in (Gdk.KEY_minus, Gdk.KEY_KP_Subtract):
            current = self.subtitle_scale_slider.get_value()
            self.subtitle_scale_slider.set_value(max(current - 0.05, 0.5))
            return True
        elif keyval in (Gdk.KEY_0, Gdk.KEY_KP_0):
            self.subtitle_scale_slider.set_value(0.75)
            return True
        return False

    @staticmethod
    def _load_subtitle_scale_preference():
        try:
            config_dir = os.path.expanduser("~/.config/subtitle-editor")
            config_file = os.path.join(config_dir, "preferences.conf")
            if os.path.exists(config_file):
                with open(config_file, "r") as f:
                    for line in f:
                        if line.startswith("subtitle_scale="):
                            try:
                                value = float(line.split("=")[1].strip())
                            except (ValueError, IndexError):
                                continue
                            return max(0.5, min(1.5, value))
        except Exception as e:
            logger.warning(f"Could not load subtitle scale: {e}")
        return 0.75

    @staticmethod
    def _save_subtitle_scale_preference(value: float):
        try:
            config_dir = os.path.expanduser("~/.config/subtitle-editor")
            config_file = os.path.join(config_dir, "preferences.conf")
            os.makedirs(config_dir, exist_ok=True)
            prefs = {}
            if os.path.exists(config_file):
                with open(config_file, "r") as f:
                    for line in f:
                        if "=" in line:
                            key, val = line.strip().split("=", 1)
                            prefs[key] = val
            prefs["subtitle_scale"] = f"{value:.2f}"
            with open(config_file, "w") as f:
                for key, val in prefs.items():
                    f.write(f"{key}={val}\n")
        except Exception as e:
            logger.error(f"Error saving subtitle scale: {e}")

    def _on_widget_unrealize(self, widget):
        # Tear down mpv and clean up the temporary subtitle file. The mpv
        # render context MUST be freed before the core is terminated, otherwise
        # libmpv aborts (a live render context still references the core). The
        # GLArea child's "unrealize" handler frees it later, so we free it here
        # first to guarantee correct ordering regardless of signal order.
        self._disposed = True
        if self._redraw_source is not None:
            GLib.source_remove(self._redraw_source)
            self._redraw_source = None
        if self._render_ctx is not None:
            try:
                self._render_ctx.free()
            except Exception:  # pragma: no cover
                pass
            self._render_ctx = None
        if self._mpv is not None:
            try:
                self._mpv.terminate()
            except Exception:  # pragma: no cover
                pass
            self._mpv = None
        if self._temp_sub_path and os.path.exists(self._temp_sub_path):
            try:
                os.remove(self._temp_sub_path)
            except OSError:  # pragma: no cover
                pass
            self._temp_sub_path = None
