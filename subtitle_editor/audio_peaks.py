"""
Audio waveform peak extraction for the timeline.

Decodes one audio stream of a media file with PyAV into mono ``s16`` at a low
sample rate (only the amplitude envelope is needed), and accumulates
per-bucket min/max pairs at ~200 buckets per second of audio. The result
feeds :class:`subtitle_editor.widgets.timeline.TimelineModel` peaks.

Buckets are addressed by *absolute presentation time* (each decoded frame's
``pts`` on the container clock), the same clock mpv schedules audio and video
by. Counting decoded samples instead would drift (encoder delay, dropped
packets) and shift the whole wave whenever the stream does not start at t=0
(MP4 edit lists, AAC priming, MKV track offsets). Time regions without audio
(stream start offset, gaps) become silence buckets rather than compacting the
following audio left.

Everything here is GLib-free and safe to call from a worker thread.
:class:`WaveformLoader` runs the decode on a daemon thread; the UI polls it
with ``GLib.timeout_add`` and consumes the result when ``is_done()``. Any
failure (unsupported codec, broken file, missing PyAV) leaves the result as
``None`` so the timeline keeps working without a waveform.

Results are cached in memory (keyed by ``(abspath, size, mtime,
stream_index)``) and on disk (one small binary file per key under
``~/.cache/gsub/waveforms/``).
"""

from __future__ import annotations

import array
import hashlib
import os
import struct
import threading

# Target waveform resolution: ~200 min/max buckets per second of audio (at
# deep zoom, 0.5 s across ~600 px still gets ~1.5 buckets per pixel).
BUCKETS_PER_SECOND = 200
# Hard cap on total buckets so pathological inputs cannot exhaust memory.
MAX_BUCKETS = 600_000
# Peak extraction does not need audible fidelity: a low mono rate keeps the
# decode fast while preserving the envelope shape for display.
RESAMPLE_RATE = 8000

# Disk cache: magic + (pps_milli, count) header followed by packed int16
# (min, max) pairs. The magic is a format version: PTS-addressed buckets and
# the 200/s resolution are incompatible with the old files, so stale caches
# from earlier builds (any other magic) are treated as a miss.
_CACHE_MAGIC = b"GSUBWAV2"
_HEADER = struct.Struct("<8sII")
_DEFAULT_CACHE_DIR = os.path.join("~", ".cache", "gsub", "waveforms")

# Module-level memory cache: (abspath, size, mtime, stream_index) ->
# (peaks, pps).
_MEMORY_CACHE: dict = {}
_MEMORY_LOCK = threading.Lock()


def compute_peaks_from_samples(samples, bucket_size: int) -> list:
    """Reduce an iterable of sample values to per-bucket (min, max) pairs.

    The last bucket may be shorter than ``bucket_size``. Returns ``[]`` for
    empty input or a non-positive bucket size.
    """
    n = len(samples)
    if n == 0 or bucket_size <= 0:
        return []
    peaks = []
    for start in range(0, n, bucket_size):
        chunk = samples[start:start + bucket_size]
        if chunk:
            peaks.append((min(chunk), max(chunk)))
    return peaks


def cache_key(path: str, size: int, mtime: float, stream_index=None) -> str:
    """Stable cache key for a file identity plus the decoded audio stream.

    *stream_index* is the container stream the peaks were decoded from (the
    same file holds one peak set per dub); ``None`` (the default/first audio
    stream) is keyed as ``-1`` so it never collides with a real index.
    """
    raw = "{}\0{}\0{}\0{}".format(
        os.path.abspath(path),
        int(size),
        int(mtime * 1000),
        -1 if stream_index is None else int(stream_index),
    )
    return hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()


def default_cache_dir() -> str:
    """The on-disk waveform cache directory (created on demand)."""
    return os.path.expanduser(_DEFAULT_CACHE_DIR)


def _disk_cache_path(cache_dir: str, key: str) -> str:
    return os.path.join(cache_dir, f"{key}.gwf")


def _clamp_i16(value) -> int:
    try:
        v = int(round(float(value)))
    except (TypeError, ValueError, OverflowError):
        return 0
    return max(-32768, min(32767, v))


def disk_cache_save(cache_dir: str, key: str, peaks, peaks_per_second: float):
    """Write a peak set to the disk cache (best effort, never raises)."""
    try:
        os.makedirs(cache_dir, exist_ok=True)
        data = array.array("h")
        for lo, hi in peaks:
            data.append(_clamp_i16(lo))
            data.append(_clamp_i16(hi))
        pps_milli = max(1, int(round(float(peaks_per_second) * 1000)))
        with open(_disk_cache_path(cache_dir, key), "wb") as fh:
            fh.write(_HEADER.pack(_CACHE_MAGIC, pps_milli, len(peaks)))
            fh.write(data.tobytes())
        return True
    except (OSError, ValueError, struct.error):
        return False


def disk_cache_load(cache_dir: str, key: str):
    """Load a peak set from the disk cache; ``None`` on any miss/corruption."""
    path = _disk_cache_path(cache_dir, key)
    try:
        with open(path, "rb") as fh:
            header = fh.read(_HEADER.size)
            if len(header) != _HEADER.size:
                return None
            magic, pps_milli, count = _HEADER.unpack(header)
            if magic != _CACHE_MAGIC or pps_milli <= 0:
                return None
            body = fh.read(count * 4)
            if len(body) != count * 4:
                return None
            values = array.array("h")
            values.frombytes(body)
            if len(values) != count * 2:
                return None
            peaks = [(values[i], values[i + 1]) for i in range(0, len(values), 2)]
            return (peaks, pps_milli / 1000.0)
    except (OSError, ValueError, struct.error):
        return None


class _BucketAccumulator:
    """Incremental min/max accumulation into fixed-size time buckets.

    Buckets are addressed by absolute sample position (``position()`` is the
    stream time of the next sample to be placed): ``add`` appends samples at
    the current position, ``add_silence`` pads a missing time region with
    ``(0, 0)`` buckets instead of letting later audio shift left.
    """

    def __init__(self, bucket_size: int):
        self.bucket_size = max(1, int(bucket_size))
        self.peaks: list = []
        self._lo = 0
        self._hi = 0
        self._count = 0

    def position(self) -> int:
        """Absolute position (in samples) of the next sample to be placed."""
        return len(self.peaks) * self.bucket_size + self._count

    def add(self, samples) -> None:
        """Fold an array of s16 samples into the buckets."""
        pos = 0
        n = len(samples)
        while pos < n:
            if self._count == 0:
                self._lo = self._hi = samples[pos]
            take = min(self.bucket_size - self._count, n - pos)
            chunk = samples[pos:pos + take]
            lo = min(chunk)
            hi = max(chunk)
            if lo < self._lo:
                self._lo = lo
            if hi > self._hi:
                self._hi = hi
            self._count += take
            pos += take
            if self._count >= self.bucket_size:
                self._flush()

    def add_silence(self, n_samples: int) -> None:
        """Fold ``n`` samples of digital silence into the buckets."""
        if n_samples <= 0:
            return
        if self._count > 0:
            # Silence is zero amplitude: it widens the partial bucket's
            # bounds to include 0 but keeps its earlier samples.
            self._lo = min(self._lo, 0)
            self._hi = max(self._hi, 0)
            fill = min(self.bucket_size - self._count, n_samples)
            self._count += fill
            n_samples -= fill
            if self._count >= self.bucket_size:
                self._flush()
        whole, extra = divmod(n_samples, self.bucket_size)
        self.peaks.extend([(0, 0)] * whole)
        if extra:
            self._lo = self._hi = 0
            self._count = extra

    def _flush(self):
        if self._count > 0:
            self.peaks.append((self._lo, self._hi))
        self._count = 0

    def finish(self) -> list:
        self._flush()
        return self.peaks


def _container_duration_seconds(container) -> float:
    """Best-effort media duration in seconds (0.0 when unknown)."""
    try:
        duration = getattr(container, "duration", None)
        if not duration:
            return 0.0
        # FFmpeg reports container duration in AV_TIME_BASE (microseconds).
        return max(0.0, float(duration) / 1_000_000.0)
    except (TypeError, ValueError):
        return 0.0


def _select_audio_stream(container, path: str, stream_index):
    """Pick the audio stream to decode.

    *stream_index* (a PyAV/FFmpeg container stream index) selects the exact
    stream; ``None`` falls back to the first audio stream.
    """
    audio_streams = [s for s in container.streams if s.type == "audio"]
    if not audio_streams:
        raise ValueError(f"no audio stream in {path!r}")
    if stream_index is None:
        return audio_streams[0]
    for stream in audio_streams:
        if stream.index == stream_index:
            return stream
    raise ValueError(f"no audio stream with index {stream_index} in {path!r}")


def _frame_start_seconds(frame, fallback: float | None) -> float | None:
    """Absolute presentation time of a decoded frame, in seconds.

    mpv schedules audio by presentation timestamp on the container clock, so
    the waveform must place samples the same way: a sample's bucket is its
    absolute time (``pts`` in the stream's time base), never "Nth sample
    since decoding began". Returns *fallback* when the frame carries no
    usable timestamp.
    """
    pts = getattr(frame, "pts", None)
    time_base = getattr(frame, "time_base", None)
    if pts is not None and time_base is not None:
        try:
            return float(pts * time_base)
        except (TypeError, ValueError, OverflowError):
            pass
    try:
        time = getattr(frame, "time", None)
        if time is not None:
            return float(time)
    except (TypeError, ValueError, OverflowError):
        pass
    return fallback


def _decode_audio_peaks(path: str, duration_hint: float | None, cancel_event,
                        progress_cb=None, stream_index=None):
    """Decode one audio stream of *path* into (peaks, pps, samples).

    *stream_index* selects the container stream (``None`` = first audio
    stream). Samples are placed at their absolute presentation times, so a
    stream that starts late begins with silence buckets and gaps stay gaps.
    Raises on any decode problem; callers translate that into a silent
    "no waveform" state. The cancel event is polled between frames.
    """
    import av  # imported lazily so tests can inject a fake module

    container = av.open(path)
    try:
        stream = _select_audio_stream(container, path, stream_index)

        duration = _container_duration_seconds(container) or float(
            duration_hint or 0
        )
        rate = RESAMPLE_RATE
        pps = BUCKETS_PER_SECOND
        if duration > 0:
            # Keep the total bucket count under the cap for long media.
            pps = min(pps, MAX_BUCKETS / duration)
        bucket_size = max(1, int(round(rate / pps)))
        actual_pps = rate / bucket_size

        resampler = av.AudioResampler(
            format="s16", layout="mono", rate=rate
        )
        accumulator = _BucketAccumulator(bucket_size)
        expected = duration * rate if duration > 0 else 0
        overflow = False

        for frame in container.decode(stream):
            if cancel_event is not None and cancel_event.is_set():
                return None
            frame_start = _frame_start_seconds(frame, None)
            resampled = resampler.resample(frame)
            if not isinstance(resampled, (list, tuple)):
                resampled = [resampled] if resampled is not None else []
            for out in resampled:
                samples = array.array("h")
                samples.frombytes(bytes(out.planes[0]))
                if frame_start is None:
                    # No timestamp: continue at the end of the audio placed
                    # so far (never compact earlier audio left).
                    frame_start = accumulator.position() / rate
                pos = int(round(frame_start * rate))
                cursor = accumulator.position()
                if pos > cursor:
                    # Missing time region (stream start offset, gap): render
                    # it as silence buckets instead of shifting audio left.
                    gap_buckets = (pos - cursor + bucket_size - 1) // bucket_size
                    if len(accumulator.peaks) + gap_buckets > MAX_BUCKETS:
                        # Pathological timestamp jump: stop instead of
                        # allocating the cap's worth of silence buckets.
                        overflow = True
                        break
                    accumulator.add_silence(pos - cursor)
                elif pos < cursor:
                    # Overlap (out-of-order/priming frames): keep only the
                    # part beyond the audio already placed.
                    samples = samples[cursor - pos:]
                accumulator.add(samples)
                frame_start = accumulator.position() / rate
            if overflow or len(accumulator.peaks) >= MAX_BUCKETS:
                break  # pathological timestamps: refuse to exhaust memory
            if progress_cb and expected > 0:
                progress_cb(min(0.99, accumulator.position() / expected))

        if progress_cb:
            progress_cb(1.0)
        return (accumulator.finish(), actual_pps, accumulator.position())
    finally:
        try:
            container.close()
        except Exception:  # pragma: no cover - close of half-open container
            pass


class WaveformLoader:
    """One-shot background waveform computation for a media file.

    Usage: ``start(path)`` then poll ``get_progress()``/``is_done()`` from the
    UI thread; ``get_result()`` returns ``(peaks, peaks_per_second)`` once
    done, or ``None`` when still running, cancelled or failed. The class is
    GLib-free on purpose (the player drives it with a ``GLib`` timeout).
    """

    def __init__(self, cache_dir: str | None = None):
        self._cache_dir = cache_dir if cache_dir else default_cache_dir()
        self._thread: threading.Thread | None = None
        self._cancel_event = threading.Event()
        self._lock = threading.Lock()
        self._done = False
        self._failed = False
        self._cancelled = False
        self._progress = 0.0
        self._result = None
        self._path = None
        self._stream_index = None

    # -- lifecycle ------------------------------------------------------------ #

    def start(self, path: str, duration_hint: float | None = None,
              stream_index=None):
        """Begin loading peaks for *path* (cache hits resolve synchronously).

        *stream_index* is the container stream to decode (``None`` = the
        first audio stream); it is part of the cache key so each dub of a
        file has its own peak set.
        """
        self._path = path
        self._stream_index = stream_index
        try:
            stat = os.stat(path)
            key = cache_key(path, stat.st_size, stat.st_mtime, stream_index)
        except OSError:
            key = None

        if key is not None:
            with _MEMORY_LOCK:
                cached = _MEMORY_CACHE.get(key)
            if cached is not None:
                self._result = (list(cached[0]), cached[1])
                self._progress = 1.0
                self._done = True
                return
            cached = disk_cache_load(self._cache_dir, key)
            if cached is not None:
                self._store_memory(key, cached)
                self._result = cached
                self._progress = 1.0
                self._done = True
                return

        self._thread = threading.Thread(
            target=self._run, args=(path, key, duration_hint, stream_index),
            daemon=True,
        )
        self._thread.start()

    def cancel(self):
        """Ask the worker to stop at the next frame boundary."""
        self._cancel_event.set()

    # -- polling --------------------------------------------------------------- #

    def is_done(self) -> bool:
        with self._lock:
            return self._done

    def has_failed(self) -> bool:
        with self._lock:
            return self._failed

    def was_cancelled(self) -> bool:
        with self._lock:
            return self._cancelled

    def get_progress(self) -> float:
        with self._lock:
            return self._progress

    def get_result(self):
        """``(peaks, peaks_per_second)`` when finished successfully, else ``None``."""
        with self._lock:
            return self._result

    # -- internals --------------------------------------------------------------- #

    @staticmethod
    def _store_memory(key, result):
        with _MEMORY_LOCK:
            _MEMORY_CACHE[key] = result

    def _set_progress(self, value):
        with self._lock:
            self._progress = value

    def _run(self, path, key, duration_hint, stream_index):
        try:
            outcome = _decode_audio_peaks(
                path, duration_hint, self._cancel_event, self._set_progress,
                stream_index,
            )
        except Exception:
            with self._lock:
                self._failed = True
                self._done = True
                self._progress = 1.0
            return

        if outcome is None:  # cancelled
            with self._lock:
                self._cancelled = True
                self._done = True
                self._progress = 1.0
            return

        peaks, pps, _samples = outcome
        if key is not None:
            self._store_memory(key, (peaks, pps))
            disk_cache_save(self._cache_dir, key, peaks, pps)
        with self._lock:
            self._result = (peaks, pps)
            self._progress = 1.0
            self._done = True


def clear_memory_cache():
    """Reset the module-level memory cache (used by tests)."""
    with _MEMORY_LOCK:
        _MEMORY_CACHE.clear()
