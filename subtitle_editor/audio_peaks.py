"""
Audio waveform peak extraction for the timeline.

Decodes the default (first) audio stream of a media file with PyAV into mono
``s16`` at a low sample rate (only the amplitude envelope is needed), and
accumulates per-bucket min/max pairs at ~100 buckets per second. The result
feeds :class:`subtitle_editor.widgets.timeline.TimelineModel` peaks.

Everything here is GLib-free and safe to call from a worker thread.
:class:`WaveformLoader` runs the decode on a daemon thread; the UI polls it
with ``GLib.timeout_add`` and consumes the result when ``is_done()``. Any
failure (unsupported codec, broken file, missing PyAV) leaves the result as
``None`` so the timeline keeps working without a waveform.

Results are cached in memory (keyed by ``(abspath, size, mtime)``) and on
disk (one small binary file per key under ``~/.cache/gsub/waveforms/``).
"""

from __future__ import annotations

import array
import hashlib
import os
import struct
import threading

# Target waveform resolution: ~100 min/max buckets per second of audio.
BUCKETS_PER_SECOND = 100
# Hard cap on total buckets so pathological inputs cannot exhaust memory.
MAX_BUCKETS = 600_000
# Peak extraction does not need audible fidelity: a low mono rate keeps the
# decode fast while preserving the envelope shape for display.
RESAMPLE_RATE = 8000

# Disk cache: magic + (pps_milli, count) header followed by packed int16
# (min, max) pairs.
_CACHE_MAGIC = b"GSUBWAV1"
_HEADER = struct.Struct("<8sII")
_DEFAULT_CACHE_DIR = os.path.join("~", ".cache", "gsub", "waveforms")

# Module-level memory cache: (abspath, size, mtime) -> (peaks, pps).
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


def cache_key(path: str, size: int, mtime: float) -> str:
    """Stable cache key for a file identity (path + size + mtime)."""
    raw = f"{os.path.abspath(path)}\0{int(size)}\0{int(mtime * 1000)}"
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
    """Incremental min/max accumulation into fixed-size buckets."""

    def __init__(self, bucket_size: int):
        self.bucket_size = max(1, int(bucket_size))
        self.peaks: list = []
        self._lo = 0
        self._hi = 0
        self._count = 0

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


def _decode_audio_peaks(path: str, duration_hint: float | None, cancel_event,
                        progress_cb=None):
    """Decode *path*'s default audio stream into (peaks, pps, samples).

    Raises on any decode problem; callers translate that into a silent
    "no waveform" state. The cancel event is polled between frames.
    """
    import av  # imported lazily so tests can inject a fake module

    container = av.open(path)
    try:
        stream = next(
            (s for s in container.streams if s.type == "audio"), None
        )
        if stream is None:
            raise ValueError(f"no audio stream in {path!r}")

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
        total_samples = 0
        expected = duration * rate if duration > 0 else 0

        for frame in container.decode(stream):
            if cancel_event is not None and cancel_event.is_set():
                return None
            resampled = resampler.resample(frame)
            if not isinstance(resampled, (list, tuple)):
                resampled = [resampled] if resampled is not None else []
            for out in resampled:
                samples = array.array("h")
                samples.frombytes(bytes(out.planes[0]))
                accumulator.add(samples)
                total_samples += len(samples)
                if progress_cb and expected > 0:
                    progress_cb(min(0.99, total_samples / expected))

        if progress_cb:
            progress_cb(1.0)
        return (accumulator.finish(), actual_pps, total_samples)
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

    # -- lifecycle ------------------------------------------------------------ #

    def start(self, path: str, duration_hint: float | None = None):
        """Begin loading peaks for *path* (cache hits resolve synchronously)."""
        self._path = path
        try:
            stat = os.stat(path)
            key = cache_key(path, stat.st_size, stat.st_mtime)
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
            target=self._run, args=(path, key, duration_hint), daemon=True
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

    def _run(self, path, key, duration_hint):
        try:
            outcome = _decode_audio_peaks(
                path, duration_hint, self._cancel_event, self._set_progress
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
