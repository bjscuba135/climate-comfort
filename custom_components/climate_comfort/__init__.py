from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_DEVICE_ACTIVATE_OFFSET,
    CONF_DEVICE_ACTIVATION_POINT,
    CONF_DEVICE_ID,
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


def _assign_device_ids(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Give every device stage a stable id and move its sensor onto it.

    Stage sensors used to be identified by their position in the device list
    (<entry>_device_0, _device_1, ...). Removing a stage shifted every later
    one down a slot, so each sensor silently took over its neighbour's entity
    id, name and history. Each stage now carries its own id; the existing
    sensors are re-pointed at it here so entity ids and history are kept.
    """
    devices = entry.options.get(CONF_DEVICES, [])
    if all(device.get(CONF_DEVICE_ID) for device in devices):
        return False

    migrated = deepcopy(devices)
    renames: list[tuple[str, str]] = []
    for index, device in enumerate(migrated):
        if device.get(CONF_DEVICE_ID):
            continue
        device[CONF_DEVICE_ID] = uuid4().hex
        renames.append(
            (
                f"{entry.entry_id}_device_{index}",
                f"{entry.entry_id}_device_{device[CONF_DEVICE_ID]}",
            )
        )

    hass.config_entries.async_update_entry(
        entry,
        options={**entry.options, CONF_DEVICES: migrated},
    )

    registry = er.async_get(hass)
    for old_unique_id, new_unique_id in renames:
        entity_id = registry.async_get_entity_id("binary_sensor", DOMAIN, old_unique_id)
        if entity_id:
            registry.async_update_entity(entity_id, new_unique_id=new_unique_id)
    return True


_DATA_SKIP_RELOAD = "skip_reload"


def async_update_entry_live(hass: HomeAssistant, entry: ConfigEntry, **kwargs) -> bool:
    """Save a setting that has already been applied live, without a reload.

    Every change to a config entry normally reloads the room, which is right
    for structural changes made in the options flow. A number or switch entity
    pushes its new value into the running thermostat itself, though, and
    reloading for it made every entity blink unavailable and threw away
    in-memory state on each tweak.

    The marker is set before the update because the update listener may start
    running inside the call.
    """
    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if entry_data is None:
        return hass.config_entries.async_update_entry(entry, **kwargs)
    entry_data[_DATA_SKIP_RELOAD] = entry_data.get(_DATA_SKIP_RELOAD, 0) + 1
    changed = hass.config_entries.async_update_entry(entry, **kwargs)
    if not changed:
        # Nothing changed, so no listener will run to consume the marker.
        entry_data[_DATA_SKIP_RELOAD] -= 1
    return changed


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})

    if entry.data.get(CONF_ENTRY_TYPE, ENTRY_TYPE_ROOM) == ENTRY_TYPE_ROOM:
        _migrate_legacy_device_offsets(hass, entry)
        _assign_device_ids(hass, entry)

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
    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    if entry_data.get(_DATA_SKIP_RELOAD, 0) > 0:
        entry_data[_DATA_SKIP_RELOAD] -= 1
        return

    await hass.config_entries.async_reload(entry.entry_id)

    if entry.data.get(CONF_ENTRY_TYPE, ENTRY_TYPE_ROOM) != ENTRY_TYPE_GLOBAL:
        return
    # Rooms read Global Defaults when they start. Without this, a change to a
    # shared temperature, profile or safety limit reached no room until the
    # next restart of Home Assistant.
    for room in hass.config_entries.async_entries(DOMAIN):
        if room.data.get(CONF_ENTRY_TYPE, ENTRY_TYPE_ROOM) == ENTRY_TYPE_ROOM:
            hass.config_entries.async_schedule_reload(room.entry_id)
