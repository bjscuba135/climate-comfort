from __future__ import annotations

import logging
from copy import deepcopy
from pathlib import Path
from types import MappingProxyType
from uuid import uuid4

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_DEVICE_ACTIVATE_OFFSET,
    CONF_DEVICE_ACTIVATION_POINT,
    CONF_DEVICE_ENTITY,
    CONF_DEVICE_ID,
    CONF_DEVICE_LABEL,
    CONF_DEVICE_ROLE,
    CONF_DEVICES,
    CONF_ENTRY_TYPE,
    CONF_FLOOR_NAMES,
    CONF_PROFILE_BALANCED_POINT_SPACING,
    DATA_FLOOR_SCHEDULES,
    DATA_HOUSE_SCHEDULE,
    DATA_SCHEDULE,
    DEFAULT_PROFILE_BALANCED_POINT_SPACING,
    DOMAIN,
    ENTRY_TYPE_GLOBAL,
    ENTRY_TYPE_ROOM,
    ROLE_HEATING,
    SUBENTRY_TYPE_DEVICE,
    floor_slug,
)

_LOGGER = logging.getLogger(__name__)

CARD_FILENAME = "climate-comfort-card.js"
CARD_URL = f"/{DOMAIN}/{CARD_FILENAME}"


def get_device_configs(entry: ConfigEntry) -> list[dict]:
    """Return the room's controlled devices, one dict per device subentry."""
    return [
        {**subentry.data, CONF_DEVICE_ID: subentry.data.get(CONF_DEVICE_ID) or subentry.subentry_id}
        for subentry in entry.subentries.values()
        if subentry.subentry_type == SUBENTRY_TYPE_DEVICE
    ]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Serve the dashboard card and have the frontend load it.

    The card ships inside the integration, so there is no separate download and
    no dashboard resource to add by hand. Failing here must never stop the
    thermostats from loading, so every problem is logged and swallowed.
    """
    try:
        from homeassistant.components.frontend import add_extra_js_url
        from homeassistant.components.http import StaticPathConfig
        from homeassistant.loader import async_get_integration

        card_path = Path(__file__).parent / "frontend" / CARD_FILENAME
        integration = await async_get_integration(hass, DOMAIN)
        await hass.http.async_register_static_paths(
            [StaticPathConfig(CARD_URL, str(card_path), False)]
        )
        # The version query makes browsers fetch the new card after an update.
        add_extra_js_url(hass, f"{CARD_URL}?v={integration.version}")
    except Exception:  # noqa: BLE001 - the card is optional, the thermostat is not
        _LOGGER.exception("Could not register the Climate Comfort dashboard card")

    # Schedules: load them, offer the services, and start once Home Assistant
    # has started (workdays and calendars need their integrations loaded).
    from .scheduler import get_manager
    from .services import async_register_services

    manager = get_manager(hass)
    await manager.async_load()
    async_register_services(hass)

    async def _start(_event=None) -> None:
        await manager.async_start()

    if hass.is_running:
        await _start()
    else:
        from homeassistant.const import EVENT_HOMEASSISTANT_STARTED

        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _start)
    return True

# Platforms created for room thermostat entries
PLATFORMS = ["climate", "binary_sensor", "number", "switch", "button", "select", "sensor"]

# Platforms created for the Global Defaults entry (mode selector lives here)
GLOBAL_PLATFORMS = ["select", "switch", "sensor"]


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


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Version 1 -> 2: move the device list out of options into subentries."""
    if entry.version > 2:
        # Created by a newer release; do not guess at its layout.
        return False
    if entry.version == 2:
        return True

    if entry.data.get(CONF_ENTRY_TYPE, ENTRY_TYPE_ROOM) == ENTRY_TYPE_ROOM:
        # Bring very old device lists up to date first, so every device has an
        # activation point and a stable id before it becomes a subentry.
        _migrate_legacy_device_offsets(hass, entry)
        _assign_device_ids(hass, entry)

        already = {
            subentry.data.get(CONF_DEVICE_ID)
            for subentry in entry.subentries.values()
            if subentry.subentry_type == SUBENTRY_TYPE_DEVICE
        }
        for device in entry.options.get(CONF_DEVICES, []):
            if device.get(CONF_DEVICE_ID) in already:
                continue  # a previous attempt got this far
            hass.config_entries.async_add_subentry(
                entry,
                ConfigSubentry(
                    data=MappingProxyType(dict(device)),
                    subentry_type=SUBENTRY_TYPE_DEVICE,
                    title=str(device.get(CONF_DEVICE_LABEL) or device.get(CONF_DEVICE_ENTITY, "Device")),
                    unique_id=None,
                ),
            )

    options = {k: v for k, v in entry.options.items() if k != CONF_DEVICES}
    hass.config_entries.async_update_entry(entry, options=options, version=2)
    _LOGGER.info("Migrated Climate Comfort entry '%s' to version 2", entry.title)
    return True


def _remove_orphaned_stage_sensors(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Delete the sensor of a device stage that no longer exists.

    Without this, deleting a device left its sensor behind as a permanently
    unavailable entity that had to be removed by hand.
    """
    prefix = f"{entry.entry_id}_device_"
    wanted = {f"{prefix}{device[CONF_DEVICE_ID]}" for device in get_device_configs(entry)}
    registry = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        if (
            entity.domain == "binary_sensor"
            and entity.unique_id.startswith(prefix)
            and entity.unique_id not in wanted
        ):
            registry.async_remove(entity.entity_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})

    if entry.data.get(CONF_ENTRY_TYPE, ENTRY_TYPE_ROOM) == ENTRY_TYPE_ROOM:
        _remove_orphaned_stage_sensors(hass, entry)

    hass.data[DOMAIN][entry.entry_id] = {}

    entry_type = entry.data.get(CONF_ENTRY_TYPE, ENTRY_TYPE_ROOM)
    _create_schedule_controllers(hass, entry)

    if entry_type == ENTRY_TYPE_ROOM:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        entry.async_on_unload(entry.add_update_listener(_async_update_options))

    elif entry_type == ENTRY_TYPE_GLOBAL:
        await hass.config_entries.async_forward_entry_setups(entry, GLOBAL_PLATFORMS)
        entry.async_on_unload(entry.add_update_listener(_async_update_options))
        # The workday sensor, calendar or start of day may have changed.
        from .scheduler import get_manager

        if hass.is_running:
            hass.async_create_task(get_manager(hass).async_refresh())

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    entry_type = entry.data.get(CONF_ENTRY_TYPE, ENTRY_TYPE_ROOM)

    if entry_type == ENTRY_TYPE_ROOM:
        unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
        if not unload_ok:
            return False

    elif entry_type == ENTRY_TYPE_GLOBAL:
        await hass.config_entries.async_unload_platforms(entry, GLOBAL_PLATFORMS)

    entry_data = hass.data[DOMAIN].pop(entry.entry_id)
    for controller in _entry_controllers(entry_data):
        controller.manager.unregister(controller)
    return True


def _create_schedule_controllers(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Make the entry's schedules before its platforms load.

    The platforms load at the same time, and the schedule's switch, select and
    sensor, and its target (a thermostat or a mode selector), all need it.
    """
    from .scheduler import OWNER_HOUSE, ScheduleController, floor_owner, get_manager, room_owner

    manager = get_manager(hass)
    entry_data = hass.data[DOMAIN][entry.entry_id]
    if entry.data.get(CONF_ENTRY_TYPE, ENTRY_TYPE_ROOM) == ENTRY_TYPE_ROOM:
        entry_data[DATA_SCHEDULE] = ScheduleController(
            manager, room_owner(entry.entry_id), entry.data.get("name") or entry.title
        )
        return
    entry_data[DATA_HOUSE_SCHEDULE] = ScheduleController(manager, OWNER_HOUSE, "House")
    entry_data[DATA_FLOOR_SCHEDULES] = {
        name: ScheduleController(manager, floor_owner(floor_slug(name)), name)
        for name in entry.data.get(CONF_FLOOR_NAMES, [])
    }


def _entry_controllers(entry_data: dict) -> list:
    found = [entry_data.get(DATA_SCHEDULE), entry_data.get(DATA_HOUSE_SCHEDULE)]
    found.extend(entry_data.get(DATA_FLOOR_SCHEDULES, {}).values())
    return [c for c in found if c is not None]


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Forget a deleted room's schedule (the House's stays with Global Defaults)."""
    from .scheduler import get_manager, room_owner

    if entry.data.get(CONF_ENTRY_TYPE, ENTRY_TYPE_ROOM) == ENTRY_TYPE_ROOM:
        get_manager(hass).remove_owner(room_owner(entry.entry_id))


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
