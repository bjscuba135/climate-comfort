from __future__ import annotations

from copy import deepcopy

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_DEVICE_ACTIVATE_OFFSET,
    CONF_DEVICE_ACTIVATION_POINT,
    CONF_DEVICE_ROLE,
    CONF_DEVICES,
    CONF_ENTRY_TYPE,
    CONF_PROFILE_BALANCED_POINT_SPACING,
    DEFAULT_PROFILE_BALANCED_POINT_SPACING,
    DOMAIN,
    ENTRY_TYPE_GLOBAL,
    ENTRY_TYPE_ROOM,
    ROLE_HEATING,
)

# Platforms created for room thermostat entries
PLATFORMS = ["climate", "binary_sensor", "number", "switch", "button", "select"]

# Platforms created for the Global Defaults entry (mode selector lives here)
GLOBAL_PLATFORMS = ["select"]


def _global_balanced_point_spacing(hass: HomeAssistant) -> float:
    for existing in hass.config_entries.async_entries(DOMAIN):
        if existing.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_GLOBAL:
            return float(
                existing.data.get(
                    CONF_PROFILE_BALANCED_POINT_SPACING,
                    DEFAULT_PROFILE_BALANCED_POINT_SPACING,
                )
            )
    return DEFAULT_PROFILE_BALANCED_POINT_SPACING


def _migrate_legacy_device_offsets(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Convert old absolute activate_offset device config to activation_point."""
    devices = entry.options.get(CONF_DEVICES, [])
    if not devices:
        return False

    spacing = _global_balanced_point_spacing(hass) or DEFAULT_PROFILE_BALANCED_POINT_SPACING
    migrated = deepcopy(devices)
    changed = False

    for device in migrated:
        if CONF_DEVICE_ACTIVATE_OFFSET not in device:
            continue

        if CONF_DEVICE_ACTIVATION_POINT not in device:
            offset = abs(float(device.get(CONF_DEVICE_ACTIVATE_OFFSET, 0.0)))
            point = int(round(offset / spacing)) if spacing else int(round(offset))
            if device.get(CONF_DEVICE_ROLE) == ROLE_HEATING:
                point = -point
            device[CONF_DEVICE_ACTIVATION_POINT] = point

        device.pop(CONF_DEVICE_ACTIVATE_OFFSET, None)
        changed = True

    if changed:
        hass.config_entries.async_update_entry(
            entry,
            options={**entry.options, CONF_DEVICES: migrated},
        )
    return changed


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})

    if entry.data.get(CONF_ENTRY_TYPE, ENTRY_TYPE_ROOM) == ENTRY_TYPE_ROOM:
        _migrate_legacy_device_offsets(hass, entry)

    hass.data[DOMAIN][entry.entry_id] = {}

    entry_type = entry.data.get(CONF_ENTRY_TYPE, ENTRY_TYPE_ROOM)

    if entry_type == ENTRY_TYPE_ROOM:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        entry.async_on_unload(entry.add_update_listener(_async_update_options))

    elif entry_type == ENTRY_TYPE_GLOBAL:
        await hass.config_entries.async_forward_entry_setups(entry, GLOBAL_PLATFORMS)
        entry.async_on_unload(entry.add_update_listener(_async_update_options))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    entry_type = entry.data.get(CONF_ENTRY_TYPE, ENTRY_TYPE_ROOM)

    if entry_type == ENTRY_TYPE_ROOM:
        unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
        if not unload_ok:
            return False

    elif entry_type == ENTRY_TYPE_GLOBAL:
        await hass.config_entries.async_unload_platforms(entry, GLOBAL_PLATFORMS)

    hass.data[DOMAIN].pop(entry.entry_id)
    return True


async def _async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
