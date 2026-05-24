from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_ENTRY_TYPE, DOMAIN, ENTRY_TYPE_GLOBAL, ENTRY_TYPE_ROOM

# Platforms created for room thermostat entries
PLATFORMS = ["climate", "binary_sensor", "number", "switch", "button"]

# Platforms created for the Global Defaults entry (mode selector lives here)
GLOBAL_PLATFORMS = ["select"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})
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
