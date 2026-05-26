from __future__ import annotations

import re

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    CONF_ENTRY_TYPE,
    CONF_FLOOR_NAMES,
    DOMAIN,
    ENTRY_TYPE_GLOBAL,
    ENTRY_TYPE_ROOM,
    MODE_AWAY,
    MODE_COOLDOWN,
    MODE_ENABLE_DEFAULTS,
    MODE_ENABLE_KEYS,
    MODE_HOME,
    MODE_WARMUP,
    OPTIONAL_MODE_OPTIONS,
    PROFILE_OPTIONS,
)

_DEFAULT_MODE = MODE_HOME
_LEGACY_MODE_ALIASES = {
    "warmup": MODE_WARMUP,
    "cooldown": MODE_COOLDOWN,
}

PROFILE_OVERRIDE_MODE_DEFAULT = "mode_default"
PROFILE_OVERRIDE_OPTIONS = [PROFILE_OVERRIDE_MODE_DEFAULT, *PROFILE_OPTIONS]

_DATA_FLOOR_SELECTS = "floor_selects"
_DATA_PROFILE_OVERRIDE = "profile_override"


def _enabled_house_mode_options(cfg: dict) -> list[str]:
    enabled = [MODE_HOME, MODE_AWAY]
    for mode in OPTIONAL_MODE_OPTIONS:
        key = MODE_ENABLE_KEYS[mode]
        default = MODE_ENABLE_DEFAULTS[key]
        if bool(cfg.get(key, default)):
            enabled.append(mode)
    return enabled


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    entry_type = entry.data.get(CONF_ENTRY_TYPE, ENTRY_TYPE_ROOM)

    if entry_type == ENTRY_TYPE_ROOM:
        async_add_entities([RoomAggressivenessSelect(entry)], update_before_add=False)
        return

    if entry_type != ENTRY_TYPE_GLOBAL:
        return

    floor_selects: list[FloorModeSelect] = [
        FloorModeSelect(entry, floor_name)
        for floor_name in entry.data.get(CONF_FLOOR_NAMES, [])
    ]

    # Store floor selects so HouseModeSelect can cascade to them
    hass.data[DOMAIN][entry.entry_id][_DATA_FLOOR_SELECTS] = floor_selects

    house_select = HouseModeSelect(entry)
    async_add_entities([house_select, *floor_selects], update_before_add=False)


class HouseModeSelect(SelectEntity, RestoreEntity):
    """
    Whole-home mode selector.

    When changed it cascades the new mode to every FloorModeSelect.
    Each floor then fires its own state-change event, which room climate
    entities (subscribed via house_mode_entity) pick up automatically.

    Rooms tagged directly with this entity also update via the same mechanism.
    """

    _attr_has_entity_name = True
    _attr_name = "House Mode"
    _attr_icon = "mdi:home-thermometer"

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_house_mode"
        self._attr_current_option = _DEFAULT_MODE
        self._attr_options = _enabled_house_mode_options(entry.data)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Global Settings",
            manufacturer="Climate Comfort",
            model="Mode Controller",
        )

    async def async_added_to_hass(self) -> None:
        if last := await self.async_get_last_state():
            restored = _LEGACY_MODE_ALIASES.get(last.state, last.state)
            if restored in self._attr_options:
                self._attr_current_option = restored
        self.async_write_ha_state()

    async def async_select_option(self, option: str) -> None:
        """
        Update House Mode and cascade the change to all Floor Mode selects.

        Cascade path:
          House Mode → (state change → rooms tagged with House Mode)
                     → each FloorModeSelect.async_select_option()
                        → (state change → rooms tagged with that floor)
        """
        if option not in self._attr_options:
            return
        self._attr_current_option = option
        self.async_write_ha_state()  # triggers rooms subscribed directly to House Mode

        # Push to every floor select — each will fire its own state change
        entry_data = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {})
        for floor_select in entry_data.get(_DATA_FLOOR_SELECTS, []):
            await floor_select.async_select_option(option)


class FloorModeSelect(SelectEntity, RestoreEntity):
    """
    Floor-level mode selector.

    When changed it fires a state-change event; room climate entities whose
    house_mode_entity points to this entity update their preset automatically
    via the existing subscription mechanism in climate.py.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:floor-plan"

    def __init__(self, entry: ConfigEntry, floor_name: str) -> None:
        self._entry = entry
        self._floor_name = floor_name
        slug = re.sub(r"[^a-z0-9]+", "_", floor_name.lower()).strip("_")
        self._attr_unique_id = f"{entry.entry_id}_floor_mode_{slug}"
        self._attr_name = f"{floor_name} Mode"
        self._attr_current_option = _DEFAULT_MODE
        self._attr_options = _enabled_house_mode_options(entry.data)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
        )

    async def async_added_to_hass(self) -> None:
        if last := await self.async_get_last_state():
            restored = _LEGACY_MODE_ALIASES.get(last.state, last.state)
            if restored in self._attr_options:
                self._attr_current_option = restored
        self.async_write_ha_state()

    async def async_select_option(self, option: str) -> None:
        if option not in self._attr_options:
            return
        self._attr_current_option = option
        self.async_write_ha_state()  # triggers rooms subscribed to this floor


class RoomAggressivenessSelect(SelectEntity, RestoreEntity):
    """Per-room runtime aggressiveness override.

    The default option follows the aggressiveness profile assigned to the
    active mode. Selecting a profile here overrides the mode-derived profile
    for this room only until changed back.
    """

    _attr_has_entity_name = True
    _attr_name = "Aggressiveness"
    _attr_icon = "mdi:speedometer"
    _attr_options = PROFILE_OVERRIDE_OPTIONS

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_aggressiveness"
        self._attr_current_option = PROFILE_OVERRIDE_MODE_DEFAULT
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.data.get("name"),
            manufacturer="Climate Comfort",
            model="Multi-Stage Thermostat",
        )

    async def async_added_to_hass(self) -> None:
        if (last := await self.async_get_last_state()) and last.state in PROFILE_OVERRIDE_OPTIONS:
            self._attr_current_option = last.state
        self._apply_profile_override()
        self.async_write_ha_state()

    async def async_select_option(self, option: str) -> None:
        if option not in PROFILE_OVERRIDE_OPTIONS:
            return
        self._attr_current_option = option
        self._apply_profile_override()
        self.async_write_ha_state()

    def _apply_profile_override(self) -> None:
        entry_data = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {})
        override = None if self._attr_current_option == PROFILE_OVERRIDE_MODE_DEFAULT else self._attr_current_option
        entry_data[_DATA_PROFILE_OVERRIDE] = override
        climate = entry_data.get("climate_entity")
        if climate:
            climate._profile_override = override
            self.hass.async_create_task(climate._evaluate_devices())
            climate.async_write_ha_state()
