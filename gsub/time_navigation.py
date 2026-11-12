"""Parsing and display for user-entered video timestamps, without GTK."""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
import math
import re


_SECONDS = re.compile(r"(?:[0-9]+(?:[.,][0-9]+)?|[.,][0-9]+)")
_COMPONENT = re.compile(r"[0-9]{1,2}")
_SECOND_COMPONENT = re.compile(r"[0-9]{1,2}(?:[.,][0-9]+)?")
_HOURS = re.compile(r"[0-9]+")
_FORMAT_ERROR = "Use HH:MM:SS.mmm, MM:SS.mmm, or a number of seconds."


def _finite_decimal(value, message):
    if isinstance(value, bool):
        raise ValueError(message)
    try:
        number = Decimal(str(value))
        as_float = float(number)
    except (InvalidOperation, TypeError, ValueError, OverflowError):
        raise ValueError(message) from None
    if not number.is_finite() or not math.isfinite(as_float) or number < 0:
        raise ValueError(message)
    return number


def parse_timestamp(text: str, duration_seconds=None) -> float:
    """Parse elapsed time, rejecting invalid components and out-of-media seeks.

    Fractional seconds may use a dot or comma. In colon notation minutes and
    seconds must be below 60; use the hours field for longer times. ``None``
    means unknown duration, while an explicit zero is a known zero-length clip.
    Parsing never clamps the user's target to a different timestamp.
    """
    if not isinstance(text, str):
        raise ValueError(_FORMAT_ERROR)
    text = text.strip()
    if not text:
        raise ValueError("Enter a timestamp.")
    parts = text.split(":")
    with localcontext() as context:
        context.prec = max(28, len(text) + 8)
        if len(parts) == 1:
            if not _SECONDS.fullmatch(text):
                raise ValueError(_FORMAT_ERROR)
            value = Decimal(text.replace(",", "."))
        elif len(parts) in (2, 3):
            if (not _COMPONENT.fullmatch(parts[-2])
                    or not _SECOND_COMPONENT.fullmatch(parts[-1])
                    or (len(parts) == 3 and not _HOURS.fullmatch(parts[0]))):
                raise ValueError(_FORMAT_ERROR)
            minutes = int(parts[-2])
            seconds = Decimal(parts[-1].replace(",", "."))
            if minutes >= 60 or seconds >= 60:
                raise ValueError("Minutes and seconds must be below 60. Use hours for longer times.")
            hours = Decimal(parts[0]) if len(parts) == 3 else Decimal(0)
            value = hours * 3600 + minutes * 60 + seconds
        else:
            raise ValueError(_FORMAT_ERROR)
    value = _finite_decimal(value, "The timestamp is too large.")
    if duration_seconds is not None:
        duration = _finite_decimal(duration_seconds,
            "Video duration is unavailable. Try again when the video has loaded.")
        if value > duration:
            raise ValueError("The timestamp is beyond the end of the video.")
    return float(value)


def format_timestamp(seconds) -> str:
    """Display elapsed time to the nearest millisecond without a 24-hour wrap."""
    value = _finite_decimal(seconds, "The position must be a finite, nonnegative number.")
    with localcontext() as context:
        context.prec = max(28, len(value.as_tuple().digits) + abs(value.adjusted()) + 8)
        milliseconds = int((value * 1000).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    hours, rest = divmod(milliseconds, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    whole_seconds, fraction = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}.{fraction:03d}"
