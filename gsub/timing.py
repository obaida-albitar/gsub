"""Validated timing and cue-preview settings, independent of GTK and mpv."""

from dataclasses import dataclass
import math

from gsub.models import SubtitleFormat


def _finite(value, name):
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a finite number") from None
    if isinstance(value, bool) or not math.isfinite(result):
        raise ValueError(f"{name} must be a finite number")
    return result


def timing_at_playhead(entry, seconds, endpoint, fmt, duration_seconds=None):
    """Change one endpoint, preserving the other and ASS's 10 ms precision.

    A playhead outside the video is clamped to its bounds. Invalid cue
    durations are rejected instead of silently moving the other endpoint.
    """
    if endpoint not in ("start", "end"):
        raise ValueError("Choose the start or end time")
    seconds = max(0.0, _finite(seconds, "Playhead"))
    if duration_seconds is not None:
        duration = _finite(duration_seconds, "Video duration")
        if duration > 0:
            seconds = min(seconds, duration)
    value = int(round(seconds * 1000))
    if fmt in (SubtitleFormat.ASS, SubtitleFormat.SSA):
        value = int(math.floor(seconds * 100 + 1e-8)) * 10
    start = entry.start_time.total_milliseconds
    end = entry.end_time.total_milliseconds
    if endpoint == "start":
        start = value
    else:
        end = value
    if end <= start:
        raise ValueError("Start time must be before end time")
    return start, end


def cue_playback_bounds(start_ms, end_ms, pre_roll_ms=500, post_roll_ms=500,
                        duration_seconds=None):
    """Return a playable (start, end) in seconds including optional context."""
    start = _finite(start_ms, "Cue start") / 1000
    end = _finite(end_ms, "Cue end") / 1000
    pre = _finite(pre_roll_ms, "Lead-in")
    post = _finite(post_roll_ms, "Lead-out")
    if start < 0 or end <= start:
        raise ValueError("The selected subtitle needs a positive duration")
    if not 0 <= pre <= 10_000 or not 0 <= post <= 10_000:
        raise ValueError("Lead-in and lead-out must be between 0 and 10000 ms")
    first, last = max(0.0, start - pre / 1000), end + post / 1000
    if duration_seconds is not None:
        duration = _finite(duration_seconds, "Video duration")
        if duration > 0:
            # A cue entirely outside the media is not a useful preview.
            if start >= duration:
                raise ValueError("The selected subtitle is outside the video")
            last = min(last, duration)
    if last <= first:
        raise ValueError("The selected subtitle is outside the video")
    return first, last


@dataclass(frozen=True)
class PlaybackSettings:
    speed: float = 1.0
    pre_roll_ms: int = 500
    post_roll_ms: int = 500

    def __post_init__(self):
        if not 0.25 <= _finite(self.speed, "Playback speed") <= 2.0:
            raise ValueError("Playback speed must be between 0.25 and 2.0")
        for name in ("pre_roll_ms", "post_roll_ms"):
            value = getattr(self, name)
            if (isinstance(value, bool) or not isinstance(value, int)
                    or not 0 <= value <= 10_000):
                raise ValueError("Lead-in and lead-out must be between 0 and 10000 ms")

    @classmethod
    def from_preferences(cls, prefs):
        defaults = cls()
        if not isinstance(prefs, dict):
            return defaults
        values = {}
        for field, key, convert in (("speed", "playback_speed", float),
                                    ("pre_roll_ms", "cue_pre_roll_ms", int),
                                    ("post_roll_ms", "cue_post_roll_ms", int)):
            try:
                value = convert(prefs.get(key, getattr(defaults, field)))
                cls(**{field: value})
                values[field] = value
            except (TypeError, ValueError, OverflowError):
                values[field] = getattr(defaults, field)
        return cls(**values)

    def to_preferences(self):
        return {"playback_speed": str(self.speed),
                "cue_pre_roll_ms": str(self.pre_roll_ms),
                "cue_post_roll_ms": str(self.post_roll_ms)}
