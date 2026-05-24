from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from homeassistant.components.climate.const import (
    PRESET_AWAY,
    PRESET_BOOST,
    PRESET_COMFORT,
    PRESET_ECO,
)

from .const import (
    CONF_COMFORT_ZONE,
    CONF_ENTRY_TYPE,
    CONF_PRESET_AWAY_HIGH,
    CONF_PRESET_AWAY_LOW,
    CONF_PRESET_BOOST,
    CONF_PRESET_COMFORT,
    CONF_PRESET_ECO,
    CONF_USE_GLOBAL_PRESETS,
    DEFAULT_COMFORT_ZONE,
    DEFAULT_PRESET_AWAY_HIGH,
    DEFAULT_PRESET_AWAY_LOW,
    DEFAULT_PRESET_BOOST,
    DEFAULT_PRESET_COMFORT,
    DEFAULT_PRESET_ECO,
    DOMAIN,
    ENTRY_TYPE_GLOBAL,
)

# (key_suffix, name, config_key, default, icon, is_delta, min_v, max_v, step)
_NUMBER_DEFS: list[tuple] = [
    ("comfort_zone",   "Comfort Zone",        CONF_COMFORT_ZONE,     DEFAULT_COMFORT_ZONE,     "mdi:swap-vertical-circle", True,  0.1, 5.0,  0.1),
    ("preset_eco",     "Eco Temperature",     CONF_PRESET_ECO,       DEFAULT_PRESET_ECO,       "mdi:leaf",                 False, 5.0, 30.0, 0.5),
    ("preset_comfort", "Comfort Temperature", CONF_PRESET_COMFORT,   DEFAULT_PRESET_COMFORT,   "mdi:sofa",                 False, 5.0, 30.0, 0.5),
    ("preset_boost",   "Boost Temperature",   CONF_PRESET_BOOST,     DEFAULT_PRESET_BOOST,     "mdi:rocket-launch",        False, 5.0, 30.0, 0.5),
    ("away_lower",     "Away Lower Limit",    CONF_PRESET_AWAY_LOW,  DEFAULT_PRESET_AWAY_LOW,  "mdi:thermometer-low",      False, 5.0, 25.0, 0.5),
    ("away_upper",     "Away Upper Limit",    CONF_PRESET_AWAY_HIGH, DEFAULT_PRESET_AWAY_HIGH, "mdi:thermometer-high",     False, 20.0, 40.0, 0.5),
]

# Map config keys to climate entity attribute names for live in-memory updates
_PRESET_KEY_MAP = {
    CONF_PRESET_ECO: PRESET_ECO,
    CONF_PRESET_COMFORT: PRESET_COMFORT,
    CONF_PRESET_BOOST: PRESET_BOOST,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    numbers = [
        RoomSettingNumber(entry, *defn)
        for defn in _NUMBER_DEFS
    ]
    hass.data[DOMAIN][entry.entry_id]["room_sensors"] = numbers  # shared key used by climate sync
    async_add_entities(numbers)


class RoomSettingNumber(NumberEntity):
    """
    Editable number entity for one room setting (preset temp, comfort zone, etc.).

    Appears in the Configuration section of the device page.  The user can
    read the current effective value AND change it directly without opening
    the options flow.

    When 'use global presets' is on, the displayed value comes from Global
    Defaults.  Editing any preset number automatically turns that flag off
    so the room uses its own values instead.
    """

    _attr_should_poll = False
    _attr_entity_category = EntityCategory.CONFIG
    _attr_has_entity_name = True
    _attr_mode = NumberMode.BOX
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_entity_registry_enabled_default = True

    def __init__(
        self,
        entry: ConfigEntry,
        key_suffix: str,
        name: str,
        config_key: str,
        default: float,
        icon: str,
        is_delta: bool,
        min_v: float,
        max_v: float,
        step: float,
    ) -> None:
        self._entry = entry
        self._config_key = config_key
        self._default = default
        self._is_delta = is_delta

        self._attr_unique_id = f"{entry.entry_id}_setting_{key_suffix}"
        self._attr_name = name
        self._attr_icon = icon
        self._attr_native_min_value = min_v
        self._attr_native_max_value = max_v
        self._attr_native_step = step

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
        )

        # Safe initial value — set directly from entry.data so HA has a
        # valid state from the moment the entity is created, before self.hass
        # is available.
        raw = entry.data.get(config_key, default)
        self._attr_native_value: float = float(raw) if raw is not None else default

    async def async_added_to_hass(self) -> None:
        # Now self.hass is available — refresh to pick up global defaults.
        self._refresh_value()
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """
        Preset temperature numbers are greyed out when the room is inheriting
        values from Global Defaults — editing them is not meaningful then.
        The Comfort Zone number (is_delta=True) is always available.
        """
        if self._is_delta:
            return True
        return not bool(self._entry.data.get(CONF_USE_GLOBAL_PRESETS, False))

    def _global_config(self) -> dict:
        for e in self.hass.config_entries.async_entries(DOMAIN):
            if e.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_GLOBAL:
                return e.data
        return {}

    def _refresh_value(self) -> None:
        """Recompute native_value, honouring use_global_presets for preset keys."""
        cfg = self._entry.data
        use_global = not self._is_delta and bool(cfg.get(CONF_USE_GLOBAL_PRESETS, False))

        if use_global:
            g = self._global_config()
            v = g.get(self._config_key)
            if v is not None:
                self._attr_native_value = float(v)
                return

        v = cfg.get(self._config_key, self._default)
        self._attr_native_value = float(v) if v is not None else self._default

    async def async_set_native_value(self, value: float) -> None:
        """
        User changed the value from the device page.

        1. Update the number entity immediately (responsive UI).
        2. Push the new value into the climate entity's live state.
        3. Persist to entry.data (survives restart, no full reload needed).
        4. Automatically disable 'use global presets' so this room now uses
           its own values.
        """
        self._attr_native_value = value
        self.async_write_ha_state()

        entry_data = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {})

        # Update climate entity's in-memory cached values directly
        climate = entry_data.get("climate_entity")
        if climate:
            if self._config_key in _PRESET_KEY_MAP:
                climate._preset_temps[_PRESET_KEY_MAP[self._config_key]] = value
            elif self._config_key == CONF_PRESET_AWAY_LOW:
                climate._away_low = value
            elif self._config_key == CONF_PRESET_AWAY_HIGH:
                climate._away_high = value
            elif self._config_key == CONF_COMFORT_ZONE:
                climate._comfort_zone = value
            # Re-evaluate with the new setting
            self.hass.async_create_task(climate._evaluate_devices())
            climate.async_write_ha_state()

        # Turn off global preset inheritance when the user sets a room value
        new_data = {**self._entry.data, self._config_key: value, CONF_USE_GLOBAL_PRESETS: False}
        self.hass.config_entries.async_update_entry(self._entry, data=new_data)

        # Update the global presets switch to reflect the flag being cleared
        gp_switch = entry_data.get("global_presets_switch")
        if gp_switch:
            gp_switch._attr_is_on = False
            gp_switch.async_write_ha_state()
