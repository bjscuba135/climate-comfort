"""The schedule engine on its own: parsing, validation, and what applies when."""
from __future__ import annotations

import importlib
from datetime import date, datetime, timedelta, timezone

import pytest

from conftest import PACKAGE, load_integration

load_integration()
schedule = importlib.import_module(f"{PACKAGE}.schedule")

PRESETS = ["away", "sleep", "home", "comfort", "eco", "activity", "boost"]
UTC = timezone.utc

TEXT = """
# a comment line
workday [workdays]: 00:00 sleep, 06:30 comfort, 08:30 eco, 17:00 comfort, 22:30 sleep
weekend [weekend]: 00:00 sleep, 08:00 comfort, 23:00 sleep
home_office [wed]: 07:30 comfort, 22:30 sleep   # Wednesdays at home
holiday (off): 00:00 eco
"""


def timeline(text=TEXT, **kwargs):
    profiles = schedule.parse_text(text)
    schedule.validate(profiles, PRESETS)
    return schedule.Timeline(profiles, UTC, valid_presets=PRESETS, **kwargs)


def at(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=UTC)


# 2026-11-23 is a Monday.
MON, TUE, WED, SAT = (23, 24, 25, 28)


def test_text_round_trips_and_reads_days_and_off():
    profiles = schedule.parse_text(TEXT)
    assert [p.name for p in profiles] == ["workday", "weekend", "home_office", "holiday"]
    assert profiles[0].days == "workdays"
    assert profiles[2].days == (2,)
    assert profiles[3].enabled is False and profiles[3].days == "all"
    again = schedule.parse_text(schedule.to_text(profiles))
    assert schedule.to_dicts(again) == schedule.to_dicts(profiles)
    assert schedule.from_dicts(schedule.to_dicts(profiles))[2].slots[0].start == 450


@pytest.mark.parametrize(
    "text, message",
    [
        ("workday: 06:30", "time and a preset"),
        ("workday: 25:00 home", "not a time of day"),
        ("workday: 08:00 home, 06:00 sleep", "in order"),
        ("workday: 08:00 sauna", "not an available preset"),
        ("a: 00:00 home\nA: 00:00 eco", "two profiles"),
        ("a [workdays]: 00:00 home\nb: 00:00 eco", "both on"),
        ("a [mon, tue]: 00:00 home\nb [tue]: 00:00 eco", "both on"),
        ("a [mon, weekend]: 00:00 home", "not both"),
        ("a [someday]: 00:00 home", "not a day"),
        ("just words", "Line 1"),
    ],
)
def test_bad_schedules_are_refused_with_a_reason(text, message):
    with pytest.raises(schedule.ScheduleError, match=message):
        profiles = schedule.parse_text(text)
        schedule.validate(profiles, PRESETS)


def test_chosen_days_do_not_overlap_groups_and_all_is_allowed_with_them():
    profiles = schedule.parse_text(
        "a: 00:00 home\nb [wed]: 00:00 eco\nc [workdays] (off): 00:00 sleep"
    )
    schedule.validate(profiles, PRESETS)


def test_which_profile_a_day_uses():
    tl = timeline()
    assert tl.profile_for(date(2026, 11, MON)).name == "workday"
    assert tl.profile_for(date(2026, 11, WED)).name == "home_office"
    assert tl.profile_for(date(2026, 11, SAT)).name == "weekend"
    # A holiday from the Workday sensor is a weekend day.
    holiday = timeline(is_workday=lambda d: d != date(2026, 11, TUE))
    assert holiday.profile_for(date(2026, 11, TUE)).name == "weekend"


def test_preset_now_and_the_next_change():
    tl = timeline()
    assert tl.preset_at(at(2026, 11, MON, 7)) == "comfort"
    assert tl.next_change(at(2026, 11, MON, 7)) == (at(2026, 11, MON, 8, 30), "eco")
    # Late evening: next change crosses midnight? No: sleep carries on until 06:30.
    assert tl.next_change(at(2026, 11, MON, 23)) == (at(2026, 11, TUE, 6, 30), "comfort")


def test_a_day_whose_first_slot_is_late_carries_the_day_before():
    tl = timeline()
    # Wednesday's profile starts at 07:30; Tuesday ended on sleep.
    assert tl.preset_at(at(2026, 11, WED, 3)) == "sleep"
    assert tl.next_change(at(2026, 11, WED, 3)) == (at(2026, 11, WED, 7, 30), "comfort")


def test_no_profile_means_no_opinion():
    tl = timeline("workday [workdays]: 00:00 sleep, 07:00 home")
    assert tl.preset_at(at(2026, 11, SAT, 12)) is None
    assert tl.next_change(at(2026, 11, SAT, 12)) == (at(2026, 11, 30, 0, 0), "sleep")


def test_calendar_event_named_after_a_profile_switches_the_whole_day():
    events = [schedule.Event(at(2026, 11, TUE, 10), at(2026, 11, TUE, 11), "Weekend")]
    tl = timeline(events=events)
    assert tl.profile_for(date(2026, 11, TUE)).name == "weekend"
    assert tl.preset_at(at(2026, 11, TUE, 7)) == "sleep"  # weekend lie-in
    # Even a profile that is switched off can be called up by the calendar.
    tl = timeline(events=[schedule.Event(at(2026, 11, TUE, 0), at(2026, 11, WED, 0), "holiday")])
    assert tl.preset_at(at(2026, 11, TUE, 12)) == "eco"


def test_calendar_event_named_after_a_preset_applies_while_it_lasts():
    events = [schedule.Event(at(2026, 11, MON, 9), at(2026, 11, MON, 15), "away")]
    tl = timeline(events=events)
    assert tl.preset_at(at(2026, 11, MON, 8, 45)) == "eco"
    assert tl.next_change(at(2026, 11, MON, 8, 45)) == (at(2026, 11, MON, 9), "away")
    assert tl.preset_at(at(2026, 11, MON, 12)) == "away"
    assert tl.next_change(at(2026, 11, MON, 12)) == (at(2026, 11, MON, 15), "eco")


def test_day_start_moves_the_handover_for_night_shifts():
    tl = timeline(day_start=5 * 60)
    # 03:00 on Saturday still belongs to Friday (a workday) until 05:00.
    assert tl.schedule_day(at(2026, 11, SAT, 3)) == (date(2026, 11, 27), 22 * 60)
    assert tl.profile_for(tl.schedule_day(at(2026, 11, SAT, 3))[0]).name == "workday"


def test_local_time_is_used_for_slots():
    from zoneinfo import ZoneInfo

    london = ZoneInfo("Europe/London")
    tl = schedule.Timeline(schedule.parse_text("all: 00:00 sleep, 07:00 home"), london,
                           valid_presets=PRESETS)
    # 1 July is British Summer Time: 07:00 local is 06:00 UTC.
    assert tl.next_change(datetime(2026, 7, 1, 1, tzinfo=UTC))[0] == datetime(2026, 7, 1, 6, tzinfo=UTC)


def test_enabling_a_profile_switches_off_the_ones_it_overlaps():
    profiles = schedule.parse_text(
        "workday [workdays]: 00:00 home\nwfh [workdays] (off): 00:00 comfort\nwed [wed]: 00:00 eco"
    )
    changed = schedule.enable_profile(profiles, "wfh")
    assert [(p.name, p.enabled) for p in changed] == [("workday", False), ("wfh", True), ("wed", True)]
    schedule.validate(changed, PRESETS)
    with pytest.raises(schedule.ScheduleError):
        schedule.enable_profile(profiles, "nope")


def test_default_schedule_uses_only_available_presets():
    profiles = schedule.default_profiles(["home", "away"])
    schedule.validate(profiles, ["home", "away"])
    assert {s.preset for p in profiles for s in p.slots} == {"home"}
