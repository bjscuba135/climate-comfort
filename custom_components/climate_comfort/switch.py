from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import async_update_entry_live, get_device_configs
from .const import (
    CONF_DEVICE_ROLE,
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
    devices = get_device_configs(entry)
    if any(d.get(CONF_DEVICE_ROLE) == ROLE_DEHUMIDIFY for d in devices):
        dh_switch = DehumidifySwitch(entry)
        hass.data[DOMAIN][entry.entry_id]["dehumidify_switch"] = dh_switch
        entities.append(dh_switch)

    async_add_entities(entities)


# ── Using Global Presets ──────────────────────────────────────────────────────

class GlobalPresetsSwitch(SwitchEntity):
    """
    Toggle whether this room inherits preset temperatures from Global Defaults.

    On  → Sleep / Home / Comfort / Eco / Activity / Boost temperatures come from
           the Defaults entry; Away always follows the shared minimum/maximum
           safety bounds, and preset number entities are shown as unavailable.
    Off → room uses its own locally configured preset temperatures, while Away
           still follows the shared minimum/maximum safety bounds.
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

    @callback
    def async_entity_id_changed(self, old_entity_id: str) -> None:
        super().async_entity_id_changed(old_entity_id)

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
        await self._apply(new_data, True)

    async def async_turn_off(self, **kwargs) -> None:
        """Disable global presets: clear flag, make number entities available."""
        await self._apply({**self._entry.data, CONF_USE_GLOBAL_PRESETS: False}, False)

    async def _apply(self, new_data: dict, is_on: bool) -> None:
        """Save the flag without reloading the room, then apply it live."""
        async_update_entry_live(self.hass, self._entry, data=new_data)
        self._attr_is_on = is_on
        entry_data = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {})
        climate = entry_data.get("climate_entity")
        if climate:
            # Re-reads the preset temperatures and refreshes the numbers.
            await climate.async_settings_updated()
        else:
            self._refresh_numbers(entry_data)
        self.async_write_ha_state()

    def _refresh_numbers(self, entry_data: dict) -> None:
        for num in entry_data.get("room_sensors", []):
            if num.hass is None:
                continue
            num._refresh_value()
            num.async_write_ha_state()


# ── Dehumidification ──────────────────────────────────────────────────────────

class DehumidifySwitch(SwitchEntity, RestoreEntity):
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
        # Restore the last choice: this used to come back On after every
        # restart or reload, quietly re-enabling a dehumidifier the user had
        # switched off.
        last = await self.async_get_last_state()
        if last is not None and last.state in ("on", "off"):
            self._attr_is_on = last.state == "on"
        self._update_shared_state()
        if not self._attr_is_on:
            # The thermostat is set up before this switch, so its first
            # evaluation may already have run with dehumidification enabled.
            entry_data = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {})
            climate = entry_data.get("climate_entity")
            if climate:
                self.hass.async_create_task(climate._evaluate_devices())
        self.async_write_ha_state()

    @callback
    def async_entity_id_changed(self, old_entity_id: str) -> None:
        super().async_entity_id_changed(old_entity_id)

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
