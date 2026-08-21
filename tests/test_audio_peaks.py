"""Tests for the waveform peak extraction module (subtitle_editor.audio_peaks).

The pure functions (bucketing, cache keys, disk cache) run headless; the
WaveformLoader tests inject a fake ``av`` module (following the fake-object
patterns of test_extractors.py) so no real media files are required.
"""

import array
import os
import struct
import sys
import time
import types

import pytest

from subtitle_editor.audio_peaks import (
    MAX_BUCKETS,
    RESAMPLE_RATE,
    WaveformLoader,
    cache_key,
    clear_memory_cache,
    compute_peaks_from_samples,
    default_cache_dir,
    disk_cache_load,
    disk_cache_save,
)


@pytest.fixture(autouse=True)
def _clean_memory_cache():
    clear_memory_cache()
    yield
    clear_memory_cache()


# --- pure bucketing ------------------------------------------------------- #


class TestComputePeaks:
    def test_alternating_extremes(self):
        samples = array.array("h", [0, 100, -100, 50, -50])
        peaks = compute_peaks_from_samples(samples, 5)
        assert peaks == [(-100, 100)]

    def test_multiple_buckets(self):
        samples = array.array("h", [1, -2, 3, -4, 5, -6, 7])
        peaks = compute_peaks_from_samples(samples, 2)
        assert peaks == [(-2, 1), (-4, 3), (-6, 5), (7, 7)]

    def test_negatives_tracked(self):
        samples = array.array("h", [-3000, -12000, -500])
        assert compute_peaks_from_samples(samples, 3) == [(-12000, -500)]

    def test_constant_signal(self):
        samples = array.array("h", [1000] * 10)
        assert compute_peaks_from_samples(samples, 10) == [(1000, 1000)]
        assert compute_peaks_from_samples(samples, 4) == [
            (1000, 1000), (1000, 1000), (1000, 1000),
        ]

    def test_empty(self):
        assert compute_peaks_from_samples(array.array("h"), 10) == []

    def test_invalid_bucket_size(self):
        samples = array.array("h", [1, 2, 3])
        assert compute_peaks_from_samples(samples, 0) == []
        assert compute_peaks_from_samples(samples, -5) == []

    def test_float_samples(self):
        assert compute_peaks_from_samples([0.5, -1.5, 2.0], 3) == [(-1.5, 2.0)]

    def test_bucket_larger_than_input(self):
        assert compute_peaks_from_samples([3, 1, 2], 100) == [(1, 3)]


# --- cache keys ------------------------------------------------------------- #


class TestCacheKey:
    def test_same_identity_same_key(self):
        assert cache_key("/a.mkv", 10, 1.0) == cache_key("/a.mkv", 10, 1.0)

    def test_different_size_or_mtime_differs(self):
        base = cache_key("/a.mkv", 10, 1.0)
        assert cache_key("/a.mkv", 11, 1.0) != base
        assert cache_key("/a.mkv", 10, 2.0) != base

    def test_different_path_differs(self):
        assert cache_key("/a.mkv", 10, 1.0) != cache_key("/b.mkv", 10, 1.0)

    def test_relative_paths_normalised(self):
        assert cache_key("rel/x.mkv", 1, 1.0) == cache_key(
            os.path.abspath("rel/x.mkv"), 1, 1.0
        )


# --- disk cache -------------------------------------------------------------- #


class TestDiskCache:
    def test_round_trip(self, tmp_path):
        peaks = [(-12000, 12000), (0, 500), (-32768, 32767)]
        assert disk_cache_save(str(tmp_path), "k1", peaks, 100.0)
        loaded = disk_cache_load(str(tmp_path), "k1")
        assert loaded is not None
        assert loaded[0] == peaks
        assert loaded[1] == pytest.approx(100.0)

    def test_fractional_pps_round_trip(self, tmp_path):
        assert disk_cache_save(str(tmp_path), "k2", [(1, 2)], 83.333)
        _peaks, pps = disk_cache_load(str(tmp_path), "k2")
        assert abs(pps - 83.333) < 0.002

    def test_missing_file_is_miss(self, tmp_path):
        assert disk_cache_load(str(tmp_path), "nope") is None

    def test_corrupt_file_is_miss(self, tmp_path):
        path = tmp_path / "bad.gwf"
        path.write_bytes(b"garbage-not-a-waveform-file")
        assert disk_cache_load(str(tmp_path), "bad") is None

    def test_truncated_body_is_miss(self, tmp_path):
        peaks = [(i, i + 1) for i in range(100)]
        assert disk_cache_save(str(tmp_path), "short", peaks, 100.0)
        disk_file = tmp_path / "short.gwf"
        data = disk_file.read_bytes()
        disk_file.write_bytes(data[: len(data) - 8])
        assert disk_cache_load(str(tmp_path), "short") is None

    def test_wrong_magic_is_miss(self, tmp_path):
        (tmp_path / "magic.gwf").write_bytes(b"XXXXXXXX" + b"\x00" * 16)
        assert disk_cache_load(str(tmp_path), "magic") is None

    def test_float_peaks_clamped_to_int16(self, tmp_path):
        assert disk_cache_save(str(tmp_path), "f", [(1e9, -1e9)], 100.0)
        peaks, _pps = disk_cache_load(str(tmp_path), "f")
        assert peaks == [(32767, -32768)]

    def test_save_never_raises_on_bad_dir(self):
        # A file where a directory would go: saving must fail softly.
        assert not disk_cache_save("/dev/null/x", "k", [(0, 0)], 100.0)

    def test_default_cache_dir_expanded(self):
        assert "$" not in default_cache_dir()
        assert default_cache_dir().endswith(os.path.join("gsub", "waveforms"))


# --- fake av module ----------------------------------------------------------- #


class _FakePlane:
    def __init__(self, data):
        self._data = data

    def __bytes__(self):
        return self._data


class _FakeFrame:
    def __init__(self, samples_data):
        self.planes = [_FakePlane(samples_data)]
        self.samples = len(samples_data) // 2


class _FakeResampler:
    def resample(self, frame):
        return [frame]


class _FakeStream:
    type = "audio"


class _FakeContainer:
    def __init__(self, frames, duration_us=0, streams=None):
        self.streams = streams if streams is not None else [_FakeStream()]
        self._frames = frames
        self.duration = duration_us
        self.closed = False

    def decode(self, _stream):
        yield from self._frames

    def close(self):
        self.closed = True


def _sine_frame(values):
    return _FakeFrame(array.array("h", values).tobytes())


def _make_fake_av(container_factory):
    fake = types.ModuleType("av")
    fake.open = container_factory
    fake.AudioResampler = lambda **kwargs: _FakeResampler()
    return fake


@pytest.fixture
def fake_av(monkeypatch):
    holders = {}

    def install(container_factory):
        fake = _make_fake_av(container_factory)
        monkeypatch.setitem(sys.modules, "av", fake)
        return fake

    holders["install"] = install
    return install


def _wait_until(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class TestWaveformLoaderFakeAv:
    def test_success_produces_peaks(self, fake_av, tmp_path):
        media = tmp_path / "a.mkv"
        media.write_bytes(b"x" * 10)
        # One second of a square-ish wave in four frames.
        frames = [
            _sine_frame([12000, -12000] * (RESAMPLE_RATE // 8)),
        ] * 4
        fake_av(lambda path: _FakeContainer(frames, duration_us=1_000_000))

        loader = WaveformLoader(cache_dir=str(tmp_path / "cache"))
        loader.start(str(media))
        assert _wait_until(loader.is_done)
        assert not loader.has_failed()
        peaks, pps = loader.get_result()
        assert peaks
        assert min(p[0] for p in peaks) == -12000
        assert max(p[1] for p in peaks) == 12000
        assert pps == pytest.approx(100.0, rel=0.01)
        assert len(peaks) == pytest.approx(100, abs=15)

    def test_duration_bucket_cap(self, fake_av, tmp_path):
        media = tmp_path / "long.mkv"
        media.write_bytes(b"x" * 10)
        fake_av(lambda path: _FakeContainer([], duration_us=0))
        # duration_hint alone drives the cap: 600k buckets / 10h of audio.
        loader = WaveformLoader(cache_dir=str(tmp_path / "cache"))
        loader.start(str(media), duration_hint=3600 * 10)
        assert _wait_until(loader.is_done)
        _peaks, pps = loader.get_result()
        assert pps <= MAX_BUCKETS / (3600 * 10) + 1e-6

    def test_exception_marks_failed(self, fake_av, tmp_path):
        media = tmp_path / "bad.mkv"
        media.write_bytes(b"x" * 10)

        def boom(_path):
            raise RuntimeError("weird codec")

        fake_av(boom)
        loader = WaveformLoader(cache_dir=str(tmp_path / "cache"))
        loader.start(str(media))
        assert _wait_until(loader.is_done)
        assert loader.has_failed()
        assert loader.get_result() is None

    def test_no_audio_stream_marks_failed(self, fake_av, tmp_path):
        media = tmp_path / "novideo.mkv"
        media.write_bytes(b"x" * 10)
        fake_av(lambda path: _FakeContainer([], streams=[]))
        loader = WaveformLoader(cache_dir=str(tmp_path / "cache"))
        loader.start(str(media))
        assert _wait_until(loader.is_done)
        assert loader.has_failed()
        assert loader.get_result() is None

    def test_cancel_stops_early(self, fake_av, tmp_path):
        media = tmp_path / "c.mkv"
        media.write_bytes(b"x" * 10)

        def many_frames(_stream):
            # Long enough that the decode cannot finish before the cancel.
            for i in range(4000):
                time.sleep(0.002)
                yield _sine_frame([i % 1000, -(i % 1000)] * 8)

        def factory(path):
            container = _FakeContainer([], duration_us=1_000_000)
            container.decode = lambda s: many_frames(s)
            return container

        fake_av(factory)
        loader = WaveformLoader(cache_dir=str(tmp_path / "cache"))
        loader.start(str(media))
        # Wait until at least one frame has been processed, then cancel.
        assert _wait_until(lambda: loader.get_progress() > 0)
        loader.cancel()
        assert _wait_until(loader.is_done)
        assert loader.was_cancelled()
        assert loader.get_result() is None
        assert not loader.has_failed()

    def test_disk_cache_written_and_reused(self, fake_av, tmp_path):
        media = tmp_path / "cached.mkv"
        media.write_bytes(b"x" * 10)
        load_count = {"n": 0}

        def factory(_path):
            load_count["n"] += 1
            return _FakeContainer(
                [_sine_frame([500, -500] * (RESAMPLE_RATE // 4))] * 4,
                duration_us=1_000_000,
            )

        fake_av(factory)
        cache_dir = str(tmp_path / "cache")
        loader = WaveformLoader(cache_dir=cache_dir)
        loader.start(str(media))
        assert _wait_until(loader.is_done)
        first = loader.get_result()

        # A fresh loader (empty memory cache) must hit the disk cache instead
        # of decoding again.
        loader2 = WaveformLoader(cache_dir=cache_dir)
        loader2.start(str(media))
        assert loader2.is_done()
        assert loader2.get_result()[0] == first[0]
        assert load_count["n"] == 1

    def test_memory_cache_hit_after_stat(self, fake_av, tmp_path):
        media = tmp_path / "mem.mkv"
        media.write_bytes(b"x" * 10)
        calls = {"n": 0}

        def factory(_path):
            calls["n"] += 1
            return _FakeContainer([], duration_us=0)

        fake_av(factory)
        loader = WaveformLoader(cache_dir=str(tmp_path / "cache"))
        loader.start(str(media))
        assert _wait_until(loader.is_done)

        loader2 = WaveformLoader(cache_dir=str(tmp_path / "cache"))
        loader2.start(str(media))
        assert loader2.is_done()
        assert calls["n"] == 1

    def test_missing_file_marks_failed(self, tmp_path):
        loader = WaveformLoader(cache_dir=str(tmp_path / "cache"))
        loader.start(str(tmp_path / "does-not-exist.mkv"))
        assert _wait_until(loader.is_done)
        assert loader.has_failed()
        assert loader.get_result() is None

    def test_progress_reaches_one(self, fake_av, tmp_path):
        media = tmp_path / "p.mkv"
        media.write_bytes(b"x" * 10)
        fake_av(lambda path: _FakeContainer(
            [_sine_frame([100, -100] * (RESAMPLE_RATE // 4))] * 4,
            duration_us=1_000_000,
        ))
        loader = WaveformLoader(cache_dir=str(tmp_path / "cache"))
        loader.start(str(media))
        assert _wait_until(loader.is_done)
        assert loader.get_progress() == 1.0


class TestHeaderFormat:
    def test_header_layout(self):
        # Locks the on-disk header: magic + pps_milli + count, little endian.
        from subtitle_editor.audio_peaks import _HEADER, _CACHE_MAGIC

        assert _HEADER.format == "<8sII"
        assert _CACHE_MAGIC == b"GSUBWAV1"
        assert _HEADER.size == 16
        assert struct.calcsize("<8sII") == 16
