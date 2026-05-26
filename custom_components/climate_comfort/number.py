from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_COMFORT_ZONE,
    CONF_ENTRY_TYPE,
    CONF_MODE_ACTIVITY,
    CONF_MODE_BOOST,
    CONF_MODE_COOLDOWN,
    CONF_MODE_HOME,
    CONF_MODE_SLEEP,
    CONF_MODE_WARMUP,
    CONF_USE_GLOBAL_PRESETS,
    DEFAULT_COMFORT_ZONE,
    DEFAULT_MODE_ACTIVITY,
    DEFAULT_MODE_BOOST,
    DEFAULT_MODE_COOLDOWN,
    DEFAULT_MODE_HOME,
    DEFAULT_MODE_SLEEP,
    DEFAULT_MODE_WARMUP,
    DOMAIN,
    ENTRY_TYPE_GLOBAL,
    MODE_ACTIVITY,
    MODE_BOOST,
    MODE_COOLDOWN,
    MODE_ENABLE_DEFAULTS,
    MODE_ENABLE_KEYS,
    MODE_HOME,
    MODE_SLEEP,
    MODE_WARMUP,
)

# (key_suffix, name, config_key, default, icon, is_delta, enabled_by_default, min_v, max_v, step)
_NUMBER_DEFS: list[tuple] = [
    ("comfort_zone",   "Comfort Zone",         CONF_COMFORT_ZONE,   DEFAULT_COMFORT_ZONE,   "mdi:swap-vertical-circle", True,  True,  0.1, 5.0,  0.1),
    ("mode_sleep",     "Sleep Temperature",   CONF_MODE_SLEEP,     DEFAULT_MODE_SLEEP,     "mdi:sleep",                False, True,  5.0, 30.0, 0.1),
    ("mode_home",      "Home Temperature",    CONF_MODE_HOME,      DEFAULT_MODE_HOME,      "mdi:sofa",                 False, True,  5.0, 30.0, 0.1),
    ("mode_warmup",    "Comfort Temperature", CONF_MODE_WARMUP,    DEFAULT_MODE_WARMUP,    "mdi:sofa",                 False, True,  5.0, 30.0, 0.1),
    ("mode_cooldown",  "Eco Temperature",     CONF_MODE_COOLDOWN,  DEFAULT_MODE_COOLDOWN,  "mdi:leaf",                 False, True,  5.0, 30.0, 0.1),
    ("mode_activity",  "Activity Temperature", CONF_MODE_ACTIVITY, DEFAULT_MODE_ACTIVITY,  "mdi:run",                  False, False, 5.0, 30.0, 0.1),
    ("mode_boost",     "Boost Temperature",   CONF_MODE_BOOST,     DEFAULT_MODE_BOOST,     "mdi:rocket-launch",        False, False, 5.0, 30.0, 0.1),
]

# Map config keys to climate entity attribute names for live in-memory updates
_PRESET_KEY_MAP = {
    CONF_MODE_SLEEP: MODE_SLEEP,
    CONF_MODE_HOME: MODE_HOME,
    CONF_MODE_WARMUP: MODE_WARMUP,
    CONF_MODE_COOLDOWN: MODE_COOLDOWN,
    CONF_MODE_ACTIVITY: MODE_ACTIVITY,
    CONF_MODE_BOOST: MODE_BOOST,
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
        enabled_by_default: bool,
        min_v: float,
        max_v: float,
        step: float,
    ) -> None:
        self._entry = entry
        self._config_key = config_key
        self._default = default
        self._is_delta = is_delta
        self._enabled_by_default = enabled_by_default

        self._attr_unique_id = f"{entry.entry_id}_setting_{key_suffix}"
        self._attr_entity_registry_enabled_default = enabled_by_default
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
        Optional preset numbers are also hidden when that preset is disabled.
        """
        if self._is_delta:
            return True
        if self._config_key in MODE_ENABLE_KEYS.values():
            return True
        preset_mode = _PRESET_KEY_MAP.get(self._config_key)
        if preset_mode is not None and preset_mode != MODE_HOME:
            enable_key = MODE_ENABLE_KEYS.get(preset_mode)
            if enable_key and not bool(self._entry.data.get(enable_key, MODE_ENABLE_DEFAULTS[enable_key])):
                return False
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
                climate._mode_temps[_PRESET_KEY_MAP[self._config_key]] = value
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
