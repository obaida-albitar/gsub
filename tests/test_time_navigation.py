"""Timestamp input is explicit, finite and never silently clamped."""

from decimal import Decimal

import pytest

from gsub.time_navigation import format_timestamp, parse_timestamp


@pytest.mark.parametrize("text,expected", [
    ("0", 0.0), ("12", 12.0), ("12.345", 12.345), ("12,345", 12.345),
    (".5", 0.5), (",5", 0.5), ("  01:23.456  ", 83.456),
    ("1:23,456", 83.456), ("00:00:00.000", 0.0),
    ("1:02:03.456", 3723.456), ("1:2:3", 3723.0),
    ("25:59:59,99", 93599.99), ("100:00:00", 360000.0),
    ("59:59.999", 3599.999), ("61.000001", 61.000001),
    ("00:01.234567", 1.234567), ("00001:00:00", 3600.0),
])
def test_accepted_formats(text, expected):
    assert parse_timestamp(text) == pytest.approx(expected)


@pytest.mark.parametrize("text", [
    "", "  ", "-1", "+1", "-0", "1e3", "NaN", "inf", "∞", "1.", "1,",
    ":", "1:", ":01", "1::02", "1:2:3:4", "1:02.3:04", "01 :02",
    "01: 02", "01:02 seconds", "1.2.3", "1,2.3", "1:002", "000:01",
    "00:001:02", "-1:00:00", "00:00:-1", "00:00:.5", "０１:０２",
    None, 42, True,
])
def test_malformed_input_is_rejected(text):
    with pytest.raises(ValueError):
        parse_timestamp(text)


@pytest.mark.parametrize("text", ["60:00", "1:60", "1:60.001", "00:60:00", "00:00:60"])
def test_minute_and_second_components_are_bounded(text):
    with pytest.raises(ValueError, match="below 60"):
        parse_timestamp(text)


@pytest.mark.parametrize("text,duration,expected", [
    ("1.2", 1.2, 1.2), ("00:01.200", Decimal("1.200"), 1.2),
    ("1:00", 60, 60.0), ("0", 0, 0.0), ("123456", None, 123456.0),
])
def test_known_end_is_accepted_and_unknown_duration_has_no_artificial_limit(text, duration, expected):
    assert parse_timestamp(text, duration) == expected


@pytest.mark.parametrize("text,duration", [("1.201", 1.2), ("0.001", 0), ("01:01", 60)])
def test_timestamp_past_known_duration_is_rejected_instead_of_clamped(text, duration):
    with pytest.raises(ValueError, match="beyond the end"):
        parse_timestamp(text, duration)


@pytest.mark.parametrize("duration", [float("nan"), float("inf"), -1, True, "bad"])
def test_invalid_duration_does_not_disable_bounds_check(duration):
    with pytest.raises(ValueError, match="duration is unavailable"):
        parse_timestamp("1", duration)


def test_unrepresentably_large_input_is_rejected():
    with pytest.raises(ValueError, match="too large"):
        parse_timestamp("9" * 400)


@pytest.mark.parametrize("seconds,expected", [
    (0, "00:00:00.000"), (1.0005, "00:00:01.001"),
    (65.4321, "00:01:05.432"), (59.9996, "00:01:00.000"),
    (3599.9996, "01:00:00.000"), (3605, "01:00:05.000"),
    (25 * 3600 + 3.2, "25:00:03.200"),
    (Decimal("123.456"), "00:02:03.456"),
])
def test_formatter_has_milliseconds_and_does_not_wrap_days(seconds, expected):
    assert format_timestamp(seconds) == expected


@pytest.mark.parametrize("seconds", [float("nan"), float("inf"), -0.001, None, True, "bad"])
def test_invalid_positions_cannot_be_displayed_as_a_timestamp(seconds):
    with pytest.raises(ValueError):
        format_timestamp(seconds)


@pytest.mark.parametrize("position", [0.0001, 1.2345, 65.9876, 12345.6789, 90000.1234])
def test_displayed_position_round_trips_to_millisecond_precision(position):
    assert abs(parse_timestamp(format_timestamp(position)) - position) <= 0.0005 + 1e-10
