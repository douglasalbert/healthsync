from datetime import datetime, timedelta, timezone

import pytest

from healthsync.models import synthesize_sleep_stages


def _utc(*a):
    return datetime(*a, tzinfo=timezone.utc)


def _ms(s):
    return s * 1000


def _seg_duration_ms(seg):
    return int((seg[2] - seg[1]).total_seconds() * 1000)


def _totals(segments):
    totals = {"light": 0, "deep": 0, "rem": 0, "awake": 0}
    for stage, start, end in segments:
        totals[stage] += _seg_duration_ms((stage, start, end))
    return totals


def test_totals_preserved_exactly():
    start = _utc(2025, 5, 17, 23, 0)
    end = _utc(2025, 5, 18, 7, 0)
    light, deep, rem, awake = _ms(14400), _ms(5400), _ms(8100), _ms(900)

    segments = synthesize_sleep_stages(start, end, light, deep, rem, awake, cycle_count=4)
    totals = _totals(segments)

    assert totals["light"] == light
    assert totals["deep"] == deep
    assert totals["rem"] == rem
    assert totals["awake"] == awake


def test_awake_block_placed_at_start():
    start = _utc(2025, 5, 17, 23, 0)
    end = _utc(2025, 5, 18, 7, 0)
    segments = synthesize_sleep_stages(start, end, _ms(14400), _ms(5400), _ms(8100), _ms(900), 4)
    assert segments[0][0] == "awake"
    assert segments[0][1] == start


def test_deep_front_loaded_rem_back_loaded():
    """First cycle's deep should be greater than last cycle's; REM the opposite."""
    start = _utc(2025, 5, 17, 23, 0)
    end = _utc(2025, 5, 18, 7, 0)
    segments = synthesize_sleep_stages(start, end, _ms(14400), _ms(5400), _ms(8100), 0, 4)

    deeps = [s for s in segments if s[0] == "deep"]
    rems = [s for s in segments if s[0] == "rem"]

    assert _seg_duration_ms(deeps[0]) > _seg_duration_ms(deeps[-1])
    assert _seg_duration_ms(rems[0]) < _seg_duration_ms(rems[-1])


def test_segments_chronologically_ordered_and_within_window():
    start = _utc(2025, 5, 17, 23, 0)
    end = _utc(2025, 5, 18, 7, 0)
    segments = synthesize_sleep_stages(start, end, _ms(14400), _ms(5400), _ms(8100), _ms(900), 4)

    prev_end = start
    for stage, s, e in segments:
        assert s == prev_end, "segments must be contiguous"
        assert s >= start and e <= end + timedelta(seconds=1)
        prev_end = e


def test_zero_totals_returns_empty():
    start = _utc(2025, 5, 17, 23, 0)
    end = _utc(2025, 5, 18, 7, 0)
    assert synthesize_sleep_stages(start, end, 0, 0, 0, 0, 4) == []


def test_missing_cycle_count_falls_back_to_90min():
    start = _utc(2025, 5, 17, 23, 0)
    end = _utc(2025, 5, 18, 7, 0)
    # 8 hours of light sleep, no explicit cycle count → 5 cycles of ~90min
    segments = synthesize_sleep_stages(start, end, _ms(28800), 0, 0, 0, cycle_count=0)
    light_segments = [s for s in segments if s[0] == "light"]
    # 5 cycles × 2 light blocks per cycle = up to 10 light segments
    assert 0 < len(light_segments) <= 10


def test_totals_exceeding_window_are_scaled():
    """If WHOOP reports more stage time than the window allows, scale to fit."""
    start = _utc(2025, 5, 18, 0, 0)
    end = _utc(2025, 5, 18, 1, 0)  # only 1 hour window
    # 4 hours of stages claimed (scale factor = 0.25)
    segments = synthesize_sleep_stages(start, end, _ms(3600), _ms(3600), _ms(3600), _ms(3600), 2)

    total = sum(_seg_duration_ms(s) for s in segments)
    assert total <= _ms(3600) + 100  # allow for integer rounding
