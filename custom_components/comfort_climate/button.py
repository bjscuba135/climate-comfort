from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

import logging
_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([ResetManualControlButton(entry)])


class ResetManualControlButton(ButtonEntity):
    """
    Clears all active manual holds and immediately returns every controlled
    device to automated integration control.

    Useful when a device was manually adjusted (e.g. a fan turned on at bedtime)
    and the hold period hasn't expired yet but you want to resume automation now.
    """

    _attr_should_poll = False
    _attr_entity_category = EntityCategory.CONFIG
    _attr_has_entity_name = True
    _attr_name = "Reset to Automated Control"
    _attr_icon = "mdi:restore"

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_reset_manual_control"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
        )

    async def async_press(self) -> None:
        entry_data = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {})
        climate = entry_data.get("climate_entity")
        if not climate:
            return

        cleared = list(climate._manual_holds.keys())
        climate._manual_holds.clear()

        if cleared:
            _LOGGER.info(
                "climate_comfort [%s]: manual holds cleared for %s",
                self._entry.data.get("name"),
                cleared,
            )
            # Mark all cleared entities as recently touched so _check_manual_changes
            # doesn't immediately re-trigger holds when it sees diverged states.
            for entity_id in cleared:
                climate._mark_integration_touch(entity_id)

        await climate._evaluate_devices()
        climate.async_write_ha_state()
