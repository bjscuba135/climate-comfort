"""Schedules in Home Assistant: storage, workdays, calendar, and what they drive.

There is one ScheduleController per schedule *owner*: the House Mode
selector, each Floor Mode selector, and each room. The owner's **target** is
what the schedule changes: a mode selector or a room thermostat's preset.
The rules for what a schedule wants at any time live in ``schedule.py``; this
module decides when to apply it:

- At every scheduled change the target is set to the scheduled preset, even
  if it already shows it, so rooms following a selector are brought back too.
- A change made by a person (or an automation) lasts until the next scheduled
  change: an *override*.
- While the target is in Away the schedule waits; when Away ends, the target
  goes straight back to what the schedule says now.

Schedules are kept in Home Assistant's storage rather than in the config
entries, so editing one from the card or a service never reloads anything.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any

import homeassistant.util.dt as dt_util
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import (
    async_track_point_in_utc_time,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store

from . import schedule as sched
from .const import (
    CONF_ENTRY_TYPE,
    CONF_SCHEDULE_CALENDAR_ENTITY,
    CONF_SCHEDULE_DAY_START,
    CONF_SCHEDULE_WORKDAY_ENTITY,
    DOMAIN,
    ENTRY_TYPE_GLOBAL,
    MODE_AWAY,
)

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY = f"{DOMAIN}.schedules"
STORAGE_VERSION = 1
DATA_MANAGER = "schedule_manager"

OWNER_HOUSE = "house"

# How often workdays and calendar events are read again, and every schedule
# checked, whatever else happens.
REFRESH_INTERVAL = timedelta(hours=1)
# Days of workdays and calendar events kept ahead.
LOOKAHEAD_DAYS = sched.HORIZON_DAYS + 1


def floor_owner(slug: str) -> str:
    return f"floor:{slug}"


def room_owner(entry_id: str) -> str:
    return f"room:{entry_id}"


def get_manager(hass: HomeAssistant) -> ScheduleManager:
    """The one manager, created on first use."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    manager = domain_data.get(DATA_MANAGER)
    if manager is None:
        manager = ScheduleManager(hass)
        domain_data[DATA_MANAGER] = manager
    return manager


def parse_day_start(value: Any) -> int:
    """``"05:00:00"`` (from a time selector) → 300 minutes; anything odd → 0."""
    if not value:
        return 0
    try:
        hours, minutes, *_ = str(value).split(":")
        return (int(hours) % 24) * 60 + int(minutes) % 60
    except (TypeError, ValueError):
        return 0


class ScheduleManager:
    """Shared by every schedule: storage, workdays, calendar events."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self.data: dict[str, Any] = {"owners": {}}
        self.controllers: dict[str, ScheduleController] = {}
        self.workdays: dict[date, bool] = {}
        self.events: list[sched.Event] = []
        self._loaded = False
        self._started = False
        self._unsubs: list[Callable[[], None]] = []
        self._calendar_unsub: Callable[[], None] | None = None
        self._calendar_tracked: str | None = None

    # Storage ----------------------------------------------------------------

    async def async_load(self) -> None:
        if self._loaded:
            return
        stored = await self._store.async_load()
        if isinstance(stored, dict) and isinstance(stored.get("owners"), dict):
            self.data = stored
        self._loaded = True

    def owner_data(self, owner_id: str) -> dict[str, Any]:
        return self.data["owners"].setdefault(
            owner_id, {"enabled": False, "profiles": None, "chosen": None, "override": None}
        )

    def remove_owner(self, owner_id: str) -> None:
        if self.data["owners"].pop(owner_id, None) is not None:
            self.save()

    def save(self) -> None:
        self._store.async_delay_save(lambda: self.data, 1)

    # Settings from Global Defaults ----------------------------------------------

    def _global_config(self) -> dict[str, Any]:
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_GLOBAL:
                return {**entry.data, **entry.options}
        return {}

    @property
    def day_start(self) -> int:
        return parse_day_start(self._global_config().get(CONF_SCHEDULE_DAY_START))

    def is_workday(self, day: date) -> bool:
        return self.workdays.get(day, day.weekday() < 5)

    # Controllers --------------------------------------------------------------

    def register(self, controller: ScheduleController) -> None:
        self.controllers[controller.owner_id] = controller

    def unregister(self, controller: ScheduleController) -> None:
        if self.controllers.get(controller.owner_id) is controller:
            self.controllers.pop(controller.owner_id)
        controller.cancel_timer()

    def controller_for_entity(self, entity_id: str) -> ScheduleController | None:
        """The schedule an entity belongs to: its own entities or its target."""
        for controller in self.controllers.values():
            if entity_id in controller.entity_ids():
                return controller
        return None

    # Lifecycle ----------------------------------------------------------------

    async def async_start(self) -> None:
        """Begin refreshing; called once Home Assistant has started."""
        if self._started:
            return
        self._started = True
        self._unsubs.append(
            async_track_time_interval(self.hass, self._async_interval, REFRESH_INTERVAL)
        )
        await self.async_refresh()

    async def _async_interval(self, _now=None) -> None:
        await self.async_refresh()

    async def async_refresh(self) -> None:
        """Read workdays and calendar events again, then check every schedule."""
        config = self._global_config()
        await self._async_read_workdays(config.get(CONF_SCHEDULE_WORKDAY_ENTITY))
        await self._async_read_calendar(config.get(CONF_SCHEDULE_CALENDAR_ENTITY))
        for controller in list(self.controllers.values()):
            await controller.async_evaluate()

    async def _async_read_workdays(self, entity_id: str | None) -> None:
        self.workdays = {}
        if not entity_id or self.hass.states.get(entity_id) is None:
            return
        today = dt_util.now().date()
        for offset in range(-1, LOOKAHEAD_DAYS + 1):
            day = today + timedelta(days=offset)
            try:
                response = await self.hass.services.async_call(
                    "workday", "check_date",
                    {"entity_id": entity_id, "check_date": day.isoformat()},
                    blocking=True, return_response=True,
                )
                result = (response or {}).get(entity_id, {}).get("workday")
                if isinstance(result, bool):
                    self.workdays[day] = result
            except Exception as err:  # noqa: BLE001 - fall back to Mon-Fri
                _LOGGER.warning("Climate Comfort: could not ask %s about %s: %s", entity_id, day, err)
                return

    async def _async_read_calendar(self, entity_id: str | None) -> None:
        if entity_id != self._calendar_tracked:
            if self._calendar_unsub:
                self._calendar_unsub()
                self._calendar_unsub = None
            self._calendar_tracked = entity_id
            if entity_id:
                self._calendar_unsub = async_track_state_change_event(
                    self.hass, [entity_id], self._calendar_changed
                )
        self.events = []
        if not entity_id or self.hass.states.get(entity_id) is None:
            return
        start = dt_util.start_of_local_day() - timedelta(days=1)
        end = start + timedelta(days=LOOKAHEAD_DAYS + 2)
        try:
            response = await self.hass.services.async_call(
                "calendar", "get_events",
                {
                    "entity_id": entity_id,
                    "start_date_time": start.isoformat(),
                    "end_date_time": end.isoformat(),
                },
                blocking=True, return_response=True,
            )
        except Exception as err:  # noqa: BLE001 - the schedule still works without it
            _LOGGER.warning("Climate Comfort: could not read calendar %s: %s", entity_id, err)
            return
        for item in (response or {}).get(entity_id, {}).get("events", []):
            event = _calendar_event(item)
            if event is not None:
                self.events.append(event)

    @callback
    def _calendar_changed(self, _event) -> None:
        self.hass.async_create_task(self.async_refresh())

    async def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._calendar_unsub:
            self._calendar_unsub()
        for controller in self.controllers.values():
            controller.cancel_timer()


def _calendar_event(item: dict) -> sched.Event | None:
    """An event from calendar.get_events; all-day events span local midnights."""
    title = str(item.get("summary") or "").strip()
    if not title:
        return None
    start = _event_time(item.get("start"))
    end = _event_time(item.get("end"))
    if start is None or end is None:
        return None
    return sched.Event(start, end, title)


def _event_time(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value)
    if len(text) == 10:  # all-day: a date
        try:
            day = date.fromisoformat(text)
        except ValueError:
            return None
        return dt_util.start_of_local_day(day).astimezone(dt_util.UTC)
    parsed = dt_util.parse_datetime(text)
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_util.get_default_time_zone())
    return parsed.astimezone(dt_util.UTC)


class ScheduleController:
    """One schedule and the target it drives.

    The target is any object with ``target_entity_id`` (str | None),
    ``schedule_presets()`` -> list of allowed presets, ``schedule_current()``
    -> current preset, ``async_apply_scheduled(preset)`` and
    ``schedule_disabled()`` (called when the schedule is switched off, so the
    target can go back to following whatever it followed before).
    """

    def __init__(self, manager: ScheduleManager, owner_id: str, name: str) -> None:
        self.manager = manager
        self.hass = manager.hass
        self.owner_id = owner_id
        self.name = name
        self.target: Any = None
        self.sensor_entity_id: str | None = None
        self.switch_entity_id: str | None = None
        self.select_entity_id: str | None = None
        self._listeners: list[Callable[[], None]] = []
        self._timer: Callable[[], None] | None = None
        # The next change found at the last evaluation; passing it is a
        # scheduled change even when the preset it brings is already set.
        self._next_change: datetime | None = None
        self.next_change: datetime | None = None
        self.next_preset: str | None = None
        self.scheduled_preset: str | None = None
        manager.register(self)

    # Stored state -------------------------------------------------------------

    @property
    def _data(self) -> dict[str, Any]:
        return self.manager.owner_data(self.owner_id)

    @property
    def enabled(self) -> bool:
        return bool(self._data.get("enabled"))

    @property
    def override(self) -> dict[str, Any] | None:
        return self._data.get("override")

    def valid_presets(self) -> list[str]:
        if self.target is None:
            return []
        return [p for p in self.target.schedule_presets() if p and p != "none"]

    @property
    def profiles(self) -> list[sched.Profile]:
        stored = self._data.get("profiles")
        if stored:
            try:
                return sched.from_dicts(stored)
            except sched.ScheduleError as err:
                _LOGGER.warning("Climate Comfort: stored schedule of %s is unreadable: %s", self.name, err)
        presets = self.valid_presets() or ["home"]
        return sched.default_profiles(presets)

    def entity_ids(self) -> set[str]:
        ids = {self.sensor_entity_id, self.switch_entity_id, self.select_entity_id}
        if self.target is not None:
            ids.add(getattr(self.target, "target_entity_id", None))
        return {i for i in ids if i}

    # Listeners ----------------------------------------------------------------

    def add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)

        def _remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return _remove

    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    # The schedule ---------------------------------------------------------------

    def timeline(self) -> sched.Timeline:
        return sched.Timeline(
            self.profiles,
            dt_util.get_default_time_zone(),
            is_workday=self.manager.is_workday,
            events=self.manager.events,
            day_start=self.manager.day_start,
            valid_presets=self.valid_presets(),
        )

    def _target_ready(self) -> bool:
        return self.target is not None and self.target.schedule_current() is not None

    async def async_evaluate(self, *, force: bool = False) -> None:
        """Apply the schedule if it is time to; ``force`` applies it now."""
        self.cancel_timer()
        if not self.enabled or not self._target_ready():
            self.next_change = self.next_preset = self.scheduled_preset = None
            self._next_change = None
            self._notify()
            return

        now = dt_util.utcnow()
        timeline = self.timeline()
        scheduled = timeline.preset_at(now)
        next_at, next_preset = timeline.next_change(now)

        crossed = self._next_change is not None and now >= self._next_change
        override = self.override
        if override is not None:
            until = override.get("until")
            expired = until is not None and dt_util.parse_datetime(until) <= now
            if crossed or expired or force:
                self._data["override"] = override = None
                self.manager.save()

        current = self.target.schedule_current()
        if scheduled is None:
            pass  # no profile for today: the schedule has no opinion
        elif current == MODE_AWAY and scheduled != MODE_AWAY and not force:
            pass  # paused while Away
        elif override is not None:
            pass  # a person's change, until the next scheduled change
        elif force or crossed or current != scheduled:
            _LOGGER.debug("Climate Comfort: schedule of %s sets %s", self.name, scheduled)
            await self.target.async_apply_scheduled(scheduled)

        self.scheduled_preset = scheduled
        self.next_change = next_at
        self.next_preset = next_preset
        self._next_change = next_at
        if next_at is not None:
            self._timer = async_track_point_in_utc_time(
                self.hass, self._async_timer, next_at + timedelta(seconds=1)
            )
        self._notify()

    async def _async_timer(self, _now=None) -> None:
        self._timer = None
        await self.async_evaluate()

    def cancel_timer(self) -> None:
        if self._timer is not None:
            self._timer()
            self._timer = None

    def note_change(self, preset: str | None, previous: str | None) -> None:
        """The target was changed by someone other than this schedule."""
        if not self.enabled or preset is None:
            return
        if preset == MODE_AWAY:
            # Away pauses the schedule; there is nothing to wait out.
            if self.override is not None:
                self._data["override"] = None
                self.manager.save()
            self._notify()
            return
        if previous == MODE_AWAY:
            # Back from Away: return to what the schedule says now.
            self.hass.async_create_task(self.async_evaluate(force=True))
            return
        now = dt_util.utcnow()
        timeline = self.timeline()
        if preset == timeline.preset_at(now):
            self._data["override"] = None
        else:
            next_at, _ = timeline.next_change(now)
            self._data["override"] = {
                "preset": preset,
                "until": next_at.isoformat() if next_at else None,
            }
        self.manager.save()
        self._notify()

    # Changes from the switch, select, services and card ---------------------------

    async def async_set_enabled(self, enabled: bool) -> None:
        data = self._data
        data["enabled"] = enabled
        data["override"] = None
        if enabled and not data.get("profiles"):
            data["profiles"] = sched.to_dicts(self.profiles)
        self.manager.save()
        if enabled:
            await self.async_evaluate()
        else:
            await self.async_evaluate()
            if self.target is not None:
                await self.target.schedule_disabled()
        self._notify()

    async def async_set_profiles(self, profiles: list[sched.Profile]) -> None:
        sched.validate(profiles, self.valid_presets())
        data = self._data
        data["profiles"] = sched.to_dicts(profiles)
        if data.get("chosen") and sched.find_profile(profiles, data["chosen"]) is None:
            data["chosen"] = None
        self.manager.save()
        await self.async_evaluate()

    async def async_choose_profile(self, name: str) -> None:
        profiles = sched.enable_profile(self.profiles, name)
        sched.validate(profiles, self.valid_presets())
        data = self._data
        data["profiles"] = sched.to_dicts(profiles)
        data["chosen"] = sched.find_profile(profiles, name).name
        self.manager.save()
        await self.async_evaluate()

    async def async_resume(self) -> None:
        self._data["override"] = None
        self.manager.save()
        await self.async_evaluate(force=True)

    # For the entities ---------------------------------------------------------

    def chosen_profile(self) -> str | None:
        """What the profile select shows: the last one chosen, else today's."""
        profiles = self.profiles
        chosen = sched.find_profile(profiles, self._data.get("chosen"))
        if chosen is not None and chosen.enabled:
            return chosen.name
        today = self.timeline().today_profile(dt_util.utcnow()) if self._target_ready() else None
        return today.name if today else None

    def attributes(self) -> dict[str, Any]:
        now = dt_util.utcnow()
        timeline = self.timeline()
        today = timeline.today_profile(now)
        current = self.target.schedule_current() if self.target is not None else None
        return {
            "owner_name": self.name,
            "schedule_enabled": self.enabled,
            "switch_entity": self.switch_entity_id,
            "profile_entity": self.select_entity_id,
            "target_entity": getattr(self.target, "target_entity_id", None),
            "scheduled_preset": self.scheduled_preset,
            "next_preset": self.next_preset,
            "profile_today": today.name if today else None,
            "override": self.override if self.enabled else None,
            "paused": bool(
                self.enabled
                and current == MODE_AWAY
                and self.scheduled_preset not in (None, MODE_AWAY)
            ),
            "valid_presets": self.valid_presets(),
            "profiles": sched.to_dicts(self.profiles),
            "today_slots": sched.slot_dicts(timeline.today_slots(now)),
            "schedule_text": sched.to_text(self.profiles),
        }
