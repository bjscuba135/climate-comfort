from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_DEVICE_ROLE,
    CONF_DEVICES,
    CONF_ENTRY_TYPE,
    CONF_MODE_ACTIVITY,
    CONF_MODE_AWAY,
    CONF_MODE_BOOST,
    CONF_MODE_COOLDOWN,
    CONF_MODE_HOME,
    CONF_MODE_SLEEP,
    CONF_MODE_WARMUP,
    CONF_USE_GLOBAL_PRESETS,
    DOMAIN,
    ENTRY_TYPE_GLOBAL,
    MODE_ACTIVITY,
    MODE_AWAY,
    MODE_BOOST,
    MODE_COOLDOWN,
    MODE_HOME,
    MODE_SLEEP,
    MODE_WARMUP,
    ROLE_DEHUMIDIFY,
)

_DATA_DEHUMIDIFY = "dehumidify_enabled"
_DATA_GLOBAL_PRESETS = "global_presets_switch"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    entities = []

    # "Using Global Presets" toggle — only useful when a Global Defaults entry exists.
    if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_GLOBAL and any(
        e.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_GLOBAL
        for e in hass.config_entries.async_entries(DOMAIN)
    ):
        gp_switch = GlobalPresetsSwitch(entry)
        hass.data[DOMAIN][entry.entry_id][_DATA_GLOBAL_PRESETS] = gp_switch
        entities.append(gp_switch)

    # Dehumidification toggle — only when at least one dehumidifier is configured
    devices = entry.options.get(CONF_DEVICES, [])
    if any(d.get(CONF_DEVICE_ROLE) == ROLE_DEHUMIDIFY for d in devices):
        dh_switch = DehumidifySwitch(entry)
        hass.data[DOMAIN][entry.entry_id]["dehumidify_switch"] = dh_switch
        entities.append(dh_switch)

    async_add_entities(entities)


# ── Using Global Presets ──────────────────────────────────────────────────────

class GlobalPresetsSwitch(SwitchEntity):
    """
    Toggle whether this room inherits preset temperatures from Global Defaults.

    On  → Eco / Comfort / Boost / Away temperatures come from the Global
           Defaults entry; preset number entities are shown as unavailable.
    Off → room uses its own locally configured preset temperatures.
    """

    _attr_should_poll = False
    _attr_entity_category = EntityCategory.CONFIG
    _attr_has_entity_name = True
    _attr_name = "Using Global Presets"

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        # Same unique_id as the old GlobalPresetsSensor so HA maps the entity
        # registry record correctly when upgrading.
        self._attr_unique_id = f"{entry.entry_id}_using_global_presets"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})
        self._attr_is_on: bool = bool(entry.data.get(CONF_USE_GLOBAL_PRESETS, False))

    async def async_added_to_hass(self) -> None:
        self._attr_is_on = bool(self._entry.data.get(CONF_USE_GLOBAL_PRESETS, False))
        self.async_write_ha_state()

    @property
    def icon(self) -> str:
        return "mdi:earth" if self._attr_is_on else "mdi:earth-off"

    def _global_config(self) -> dict:
        for e in self.hass.config_entries.async_entries(DOMAIN):
            if e.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_GLOBAL:
                return e.data
        return {}

    async def async_turn_on(self, **kwargs) -> None:
        """Enable global presets: copy global values, set flag, grey out numbers."""
        global_cfg = self._global_config()
        if not global_cfg:
            self._attr_is_on = False
            self.async_write_ha_state()
            return
        new_data = {**self._entry.data, CONF_USE_GLOBAL_PRESETS: True}
        for key in (
            CONF_MODE_AWAY,
            CONF_MODE_SLEEP,
            CONF_MODE_HOME,
            CONF_MODE_WARMUP,
            CONF_MODE_COOLDOWN,
            CONF_MODE_ACTIVITY,
            CONF_MODE_BOOST,
        ):
            if key in global_cfg:
                new_data[key] = global_cfg[key]
        self.hass.config_entries.async_update_entry(self._entry, data=new_data)

        # Push new values into the climate entity's in-memory preset cache
        entry_data = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {})
        climate = entry_data.get("climate_entity")
        if climate:
            for mode, key in {
                MODE_AWAY: CONF_MODE_AWAY,
                MODE_SLEEP: CONF_MODE_SLEEP,
                MODE_HOME: CONF_MODE_HOME,
                MODE_WARMUP: CONF_MODE_WARMUP,
                MODE_COOLDOWN: CONF_MODE_COOLDOWN,
                MODE_ACTIVITY: CONF_MODE_ACTIVITY,
                MODE_BOOST: CONF_MODE_BOOST,
            }.items():
                if key in global_cfg:
                    climate._mode_temps[mode] = float(global_cfg[key])
            self.hass.async_create_task(climate._evaluate_devices())
            climate.async_write_ha_state()

        self._attr_is_on = True
        self._refresh_numbers(entry_data)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Disable global presets: clear flag, make number entities available."""
        new_data = {**self._entry.data, CONF_USE_GLOBAL_PRESETS: False}
        self.hass.config_entries.async_update_entry(self._entry, data=new_data)
        self._attr_is_on = False
        entry_data = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {})
        self._refresh_numbers(entry_data)
        self.async_write_ha_state()

    def _refresh_numbers(self, entry_data: dict) -> None:
        for num in entry_data.get("room_sensors", []):
            num._refresh_value()
            num.async_write_ha_state()


# ── Dehumidification ──────────────────────────────────────────────────────────

class DehumidifySwitch(SwitchEntity):
    """
    Allows the user to suspend dehumidification without removing the device.

    When Off: the comfort climate controller ignores humidity readings and
    turns off any active dehumidifier devices.
    When On (default): normal humidity-based control applies.
    """

    _attr_should_poll = False
    _attr_entity_category = EntityCategory.CONFIG
    _attr_has_entity_name = True
    _attr_name = "Dehumidification"
    _attr_icon = "mdi:water-percent"

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_dehumidify_enabled"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})
        self._attr_is_on: bool = True

    async def async_added_to_hass(self) -> None:
        entry_data = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {})
        self._attr_is_on = entry_data.get(_DATA_DEHUMIDIFY, True)
        entry_data[_DATA_DEHUMIDIFY] = self._attr_is_on
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs) -> None:
        self._attr_is_on = True
        self._update_shared_state()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        self._attr_is_on = False
        self._update_shared_state()
        entry_data = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {})
        climate = entry_data.get("climate_entity")
        if climate:
            await climate._turn_off_dehumidifiers()
        self.async_write_ha_state()

    def _update_shared_state(self) -> None:
        entry_data = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {})
        entry_data[_DATA_DEHUMIDIFY] = self._attr_is_on
