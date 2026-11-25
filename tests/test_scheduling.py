"""Schedules driving real targets: a room's preset and the House Mode selector."""
from __future__ import annotations

import importlib
from datetime import datetime, timezone

import pytest

from conftest import PACKAGE, Entry, State, load_integration
from test_behaviour import TRV, Event, make_room, run

load_integration()
scheduler = importlib.import_module(f"{PACKAGE}.scheduler")
select = importlib.import_module(f"{PACKAGE}.select")
const = importlib.import_module(f"{PACKAGE}.const")
dt_util = importlib.import_module("homeassistant.util.dt")

UTC = timezone.utc
# 2026-11-23 is a Monday.
SCHEDULE = "all: 00:00 sleep, 06:30 comfort, 08:30 eco, 22:00 sleep"
ALL_PRESETS = {
    "mode_sleep_enabled": True, "mode_warmup_enabled": True, "mode_cooldown_enabled": True,
}


class Clock:
    def __init__(self, monkeypatch, start: datetime) -> None:
        self.now = start
        monkeypatch.setattr(dt_util, "utcnow", lambda: self.now)

    def set(self, hh: int, mm: int = 0) -> None:
        self.now = self.now.replace(hour=hh, minute=mm)


@pytest.fixture
def clock(monkeypatch):
    return Clock(monkeypatch, datetime(2026, 11, 23, 7, 0, tzinfo=UTC))


def room_with_schedule(text=SCHEDULE, room_data=None):
    hass, entity, entry = make_room([TRV], room_data=room_data, global_data=ALL_PRESETS)
    controller = scheduler.ScheduleController(
        scheduler.get_manager(hass), scheduler.room_owner(entry.entry_id), "Lounge"
    )
    controller.target = entity
    entity._schedule = controller
    controller.sensor_entity_id = "sensor.lounge_next_scheduled_change"
    entity._attr_native_current_temperature = 21.0
    return hass, entity, controller


async def enable(controller, text=SCHEDULE):
    from conftest import load_integration as _  # noqa: F401
    sched = importlib.import_module(f"{PACKAGE}.schedule")
    await controller.async_set_profiles(sched.parse_text(text))
    await controller.async_set_enabled(True)


def test_room_schedule_applies_and_a_manual_preset_lasts_until_the_next_change(clock):
    async def scenario():
        hass, entity, controller = room_with_schedule()
        await enable(controller)
        assert entity._attr_preset_mode == "comfort"
        assert controller.next_change == datetime(2026, 11, 23, 8, 30, tzinfo=UTC)
        assert hass.timers[-1]["when"] > controller.next_change  # wakes just after it

        # Someone picks Home: it holds, even when the schedule is checked again.
        await entity.async_set_preset_mode("home")
        assert controller.override == {
            "preset": "home", "until": "2026-11-23T08:30:00+00:00",
        }
        clock.set(7, 45)
        await controller.async_evaluate()
        assert entity._attr_preset_mode == "home"

        # At the next scheduled change the schedule takes over again.
        clock.set(8, 31)
        await controller.async_evaluate()
        assert entity._attr_preset_mode == "eco"
        assert controller.override is None
        assert entity.extra_state_attributes["schedule_entity"] == "sensor.lounge_next_scheduled_change"

    run(scenario())


def test_choosing_the_scheduled_preset_by_hand_is_not_an_override(clock):
    async def scenario():
        _hass, entity, controller = room_with_schedule()
        await enable(controller)
        await entity.async_set_preset_mode("comfort")
        assert controller.override is None

    run(scenario())


def test_away_pauses_the_room_schedule_and_returning_resumes_it(clock):
    async def scenario():
        hass, entity, controller = room_with_schedule(
            room_data={"house_mode_entity": "select.house_mode"}
        )
        await enable(controller)

        # House Mode goes to Away: the room follows, and the schedule waits.
        entity._handle_state_change(Event("select.house_mode", "home", "away"))
        await hass.settle()
        assert entity._attr_preset_mode == "away"
        clock.set(8, 31)
        await controller.async_evaluate()
        assert entity._attr_preset_mode == "away"
        assert controller.attributes()["paused"] is True

        # Other House Mode changes do not reach a room with its own schedule...
        # ...but leaving Away returns it to what the schedule says now.
        entity._handle_state_change(Event("select.house_mode", "away", "home"))
        await hass.settle()
        assert entity._attr_preset_mode == "eco"
        entity._handle_state_change(Event("select.house_mode", "home", "sleep"))
        await hass.settle()
        assert entity._attr_preset_mode == "eco"

    run(scenario())


def test_switching_the_schedule_off_returns_the_room_to_house_mode(clock):
    async def scenario():
        hass, entity, controller = room_with_schedule(
            room_data={"house_mode_entity": "select.house_mode"}
        )
        hass.states.set("select.house_mode", "home")
        await enable(controller)
        assert entity._attr_preset_mode == "comfort"
        await controller.async_set_enabled(False)
        assert entity._attr_preset_mode == "home"
        assert entity.extra_state_attributes["schedule_entity"] is None

    run(scenario())


def test_invalid_schedule_is_refused_and_nothing_changes(clock):
    async def scenario():
        sched = importlib.import_module(f"{PACKAGE}.schedule")
        _hass, entity, controller = room_with_schedule()
        await enable(controller)
        before = controller.attributes()["profiles"]
        with pytest.raises(sched.ScheduleError):
            await controller.async_set_profiles(sched.parse_text("all: 00:00 sauna"))
        assert controller.attributes()["profiles"] == before

    run(scenario())


def test_choosing_a_profile_switches_off_the_one_it_overlaps(clock):
    async def scenario():
        _hass, entity, controller = room_with_schedule()
        await enable(
            controller,
            "workday [workdays]: 00:00 sleep, 06:30 comfort\nwfh [workdays] (off): 00:00 sleep, 06:00 eco",
        )
        assert entity._attr_preset_mode == "comfort"
        await controller.async_choose_profile("wfh")
        assert entity._attr_preset_mode == "eco"
        assert controller.chosen_profile() == "wfh"
        assert [p["enabled"] for p in controller.attributes()["profiles"]] == [False, True]

    run(scenario())


def test_schedules_survive_a_restart(clock):
    async def scenario():
        hass, entity, controller = room_with_schedule()
        await enable(controller)
        await entity.async_set_preset_mode("home")
        stored = controller.manager._store.saved

        # A new manager reading the same storage finds the schedule and the override.
        manager = scheduler.ScheduleManager(hass)
        manager._store.saved = stored
        await manager.async_load()
        data = manager.owner_data(controller.owner_id)
        assert data["enabled"] is True
        assert data["override"]["preset"] == "home"

    run(scenario())


# ── House Mode ───────────────────────────────────────────────────────────────


def house(hass, clock):
    entry = Entry("global", {"entry_type": "global", **ALL_PRESETS})
    hass.data.setdefault(const.DOMAIN, {})["global"] = {}
    controller = scheduler.ScheduleController(scheduler.get_manager(hass), scheduler.OWNER_HOUSE, "House")
    house_select = select.HouseModeSelect(entry, controller)
    house_select.hass = hass
    house_select.entity_id = "select.house_mode"
    controller.target = house_select
    return house_select, controller


def test_house_schedule_drives_house_mode_and_brings_rooms_back(clock):
    async def scenario():
        hass, room, _ = make_room([TRV], room_data={"house_mode_entity": "select.house_mode"},
                                  global_data=ALL_PRESETS)
        room.hass = hass
        room._attr_native_current_temperature = 21.0
        room._dispatch_off = importlib.import_module(
            "homeassistant.helpers.dispatcher"
        ).async_dispatcher_connect(hass, const.SIGNAL_MODE_REASSERTED, room._mode_reasserted)

        house_select, controller = house(hass, clock)
        await enable(controller, "all: 00:00 sleep, 06:30 comfort, 08:30 comfort, 09:00 eco")
        assert house_select.current_option == "comfort"

        # A person sets the room itself to Home (the room has no schedule).
        await room.async_set_preset_mode("home")
        hass.states.set("select.house_mode", "comfort")

        # A person changes House Mode: an override until the next change.
        await house_select.async_select_option("boost" if "boost" in house_select.options else "home")
        assert controller.override is not None
        await house_select.async_select_option("comfort")  # back to the scheduled one
        assert controller.override is None

        # At 09:00 House Mode is set to Eco by the schedule.
        clock.set(9, 1)
        await controller.async_evaluate()
        assert house_select.current_option == "eco"

        # A scheduled change to the value House Mode already has still brings
        # back a room someone changed by hand.
        hass.states.set("select.house_mode", "eco")
        await room.async_set_preset_mode("home")
        await controller.async_evaluate(force=True)
        await hass.settle()
        assert room._attr_preset_mode == "eco"
        room._dispatch_off()

    run(scenario())


def test_house_away_pauses_the_house_schedule(clock):
    async def scenario():
        hass, _room, _ = make_room([TRV], global_data=ALL_PRESETS)
        house_select, controller = house(hass, clock)
        await enable(controller)
        await house_select.async_select_option("away")
        clock.set(8, 31)
        await controller.async_evaluate()
        assert house_select.current_option == "away"
        await house_select.async_select_option("home")
        await hass.settle()
        assert house_select.current_option == "eco"

    run(scenario())


def test_calendar_events_are_read_from_the_service_response():
    event = scheduler._calendar_event(
        {"summary": "away", "start": "2026-11-23T09:00:00+00:00", "end": "2026-11-23T17:00:00+00:00"}
    )
    assert event.title == "away" and event.start.hour == 9
    all_day = scheduler._calendar_event({"summary": "weekend", "start": "2026-11-24", "end": "2026-11-25"})
    assert all_day.end - all_day.start == (all_day.end - all_day.start).__class__(days=1)
    assert scheduler._calendar_event({"summary": "", "start": "2026-11-24", "end": "2026-11-25"}) is None
    assert scheduler.parse_day_start("05:30:00") == 330
    assert scheduler.parse_day_start(None) == 0
