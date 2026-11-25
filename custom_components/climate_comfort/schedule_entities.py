"""The entities every schedule has: an on/off switch, a profile select and a
sensor with the next scheduled change.

They exist for the House, each floor and each room. All three read and change
the schedule through its ScheduleController.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DATA_FLOOR_SCHEDULES, DATA_HOUSE_SCHEDULE, DATA_SCHEDULE, DOMAIN, floor_slug
from .schedule import ScheduleError
from .scheduler import ScheduleController


class _ScheduleEntity:
    """Follows one schedule and redraws when it changes."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, controller: ScheduleController, entry_id: str, prefix: str, key: str, name: str) -> None:
        self._controller = controller
        self._attr_unique_id = f"{entry_id}_{prefix}{key}"
        self._attr_name = name
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry_id)})

    async def async_added_to_hass(self) -> None:
        self._register_entity_id()
        self.async_on_remove(self._controller.add_listener(self._schedule_changed))
        self._schedule_changed()

    def _register_entity_id(self) -> None:
        raise NotImplementedError

    def _schedule_changed(self) -> None:
        if self.hass is not None and self.entity_id:
            self.async_write_ha_state()


def _names(owner_label: str | None) -> tuple[str, str, str]:
    """Entity names for a room (no label) or for the House / a floor."""
    if owner_label is None:
        return "Schedule", "Schedule profile", "Next scheduled change"
    return (
        f"{owner_label} schedule",
        f"{owner_label} schedule profile",
        f"{owner_label} next scheduled change",
    )


def entities_for_entry(hass, entry, platform: str) -> list[Any]:
    """This platform's schedule entities for a room, or for the House and floors.

    The controllers are created in ``async_setup_entry`` of the entry before
    its platforms load, because the platforms load at the same time.
    """
    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    found = []
    room = entry_data.get(DATA_SCHEDULE)
    if room is not None:
        found.append(schedule_entities(room, entry.entry_id)[platform])
    house = entry_data.get(DATA_HOUSE_SCHEDULE)
    if house is not None:
        found.append(schedule_entities(house, entry.entry_id, "house_", "House")[platform])
    for floor_name, controller in entry_data.get(DATA_FLOOR_SCHEDULES, {}).items():
        found.append(
            schedule_entities(
                controller, entry.entry_id, f"floor_{floor_slug(floor_name)}_", floor_name
            )[platform]
        )
    return found


def schedule_entities(
    controller: ScheduleController, entry_id: str, prefix: str = "", owner_label: str | None = None
) -> dict[str, Any]:
    """The three entities of one schedule, by platform."""
    switch_name, select_name, sensor_name = _names(owner_label)
    return {
        "switch": ScheduleSwitch(controller, entry_id, prefix, "schedule", switch_name),
        "select": ScheduleProfileSelect(controller, entry_id, prefix, "schedule_profile", select_name),
        "sensor": NextScheduledChangeSensor(controller, entry_id, prefix, "next_scheduled_change", sensor_name),
    }


class ScheduleSwitch(_ScheduleEntity, SwitchEntity):
    """Turns the schedule on and off. Off by default: nothing changes on upgrade."""

    _attr_icon = "mdi:calendar-clock"
    _attr_entity_category = EntityCategory.CONFIG

    def _register_entity_id(self) -> None:
        self._controller.switch_entity_id = self.entity_id

    @property
    def is_on(self) -> bool:
        return self._controller.enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._controller.async_set_enabled(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._controller.async_set_enabled(False)


class ScheduleProfileSelect(_ScheduleEntity, SelectEntity):
    """Chooses a profile: it goes on, and the profiles of the same days go off."""

    _attr_icon = "mdi:calendar-week"

    def _register_entity_id(self) -> None:
        self._controller.select_entity_id = self.entity_id

    @property
    def options(self) -> list[str]:
        return [p.name for p in self._controller.profiles]

    @property
    def current_option(self) -> str | None:
        return self._controller.chosen_profile()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        today = self._controller.attributes().get("profile_today")
        return {"today": today}

    async def async_select_option(self, option: str) -> None:
        try:
            await self._controller.async_choose_profile(option)
        except ScheduleError as err:
            raise HomeAssistantError(str(err)) from err


class NextScheduledChangeSensor(_ScheduleEntity, SensorEntity):
    """When the schedule next changes the preset; its attributes feed the card."""

    _attr_icon = "mdi:calendar-arrow-right"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    # The profiles and today's slots are for the card, not for the history.
    _unrecorded_attributes = frozenset({"profiles", "today_slots", "schedule_text", "valid_presets"})

    def _register_entity_id(self) -> None:
        self._controller.sensor_entity_id = self.entity_id

    @property
    def native_value(self):
        return self._controller.next_change if self._controller.enabled else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self._controller.attributes()
