from __future__ import annotations

import logging
import math
import time
from collections import defaultdict
from datetime import timedelta
from typing import Any

import homeassistant.util.dt as dt_util

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.components.climate.const import PRESET_NONE
from homeassistant.components.climate import ATTR_TARGET_TEMP_HIGH, ATTR_TARGET_TEMP_LOW
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_TEMPERATURE,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later, async_track_state_change_event

from .const import (
    ATTR_ACTIVE_DEVICES,
    ATTR_COMFORT_ZONE,
    ATTR_CURRENT_HUMIDITY,
    ATTR_EFFECTIVE_SETPOINT,
    ATTR_LOWER_THRESHOLD,
    ATTR_UPPER_THRESHOLD,
    CONF_COMFORT_ZONE,
    CONF_DEFAULT_PROFILE,
    CONF_DEVICE_ACTIVATE_OFFSET,
    CONF_DEVICE_ACTIVATION_POINT,
    CONF_DEVICE_DEACTIVATE_OFFSET,
    CONF_DEVICE_DEHUMIDIFY_ONLY_WHEN_IDLE,
    CONF_DEVICE_EMERGENCY_ENABLED,
    CONF_DEVICE_ENTITY,
    CONF_DEVICE_HUMIDITY_HYSTERESIS,
    CONF_DEVICE_HUMIDITY_THRESHOLD,
    CONF_DEVICE_HVAC_MODE_ON,
    CONF_DEVICE_FAN_MODE,
    CONF_DEVICE_LABEL,
    CONF_DEVICE_ROLE,
    CONF_DEVICE_SWING_HORIZONTAL_MODE,
    CONF_DEVICE_SWING_MODE,
    CONF_DEVICE_TARGET_TEMP_OFFSET,
    CONF_DEVICES,
    CONF_ENTRY_TYPE,
    CONF_HOUSE_MODE_ENTITY,
    CONF_HUMIDITY_SENSOR,
    CONF_HVAC_MODES,
    CONF_MAXIMUM_TEMPERATURE,
    CONF_MINIMUM_TEMPERATURE,
    CONF_MODE_AWAY,
    CONF_MODE_AWAY_PROFILE,
    CONF_MODE_ACTIVITY,
    CONF_MODE_ACTIVITY_PROFILE,
    CONF_MODE_BOOST,
    CONF_MODE_BOOST_PROFILE,
    CONF_MODE_COOLDOWN,
    CONF_MODE_COOLDOWN_PROFILE,
    CONF_MODE_HOME,
    CONF_MODE_HOME_PROFILE,
    CONF_MODE_SLEEP,
    CONF_MODE_SLEEP_PROFILE,
    CONF_MODE_WARMUP,
    CONF_MODE_WARMUP_PROFILE,
    CONF_MANUAL_HOLD_HOURS,
    CONF_MANUAL_HOLD_CONFIRM_SECONDS,
    CONF_TEMPERATURE_SENSOR,
    CONF_USE_GLOBAL_PRESETS,
    CONF_PROFILE_AGGRESSIVE_COMFORT_MULTIPLIER,
    CONF_PROFILE_AGGRESSIVE_POINT_SPACING,
    CONF_PROFILE_BALANCED_COMFORT_MULTIPLIER,
    CONF_PROFILE_BALANCED_POINT_SPACING,
    CONF_PROFILE_RELAXED_COMFORT_MULTIPLIER,
    CONF_PROFILE_RELAXED_POINT_SPACING,
    CONF_PROFILE_RESPONSIVE_COMFORT_MULTIPLIER,
    CONF_PROFILE_RESPONSIVE_POINT_SPACING,
    DEFAULT_COMFORT_ZONE,
    DEFAULT_MANUAL_HOLD_HOURS,
    DEFAULT_MANUAL_HOLD_CONFIRM_SECONDS,
    DEFAULT_MAX_TEMP,
    DEFAULT_MIN_TEMP,
    DEFAULT_MODE_AWAY,
    DEFAULT_MODE_ACTIVITY,
    DEFAULT_MODE_BOOST,
    DEFAULT_MODE_COOLDOWN,
    DEFAULT_MODE_HOME,
    DEFAULT_MODE_PROFILE_AWAY,
    DEFAULT_MODE_PROFILE_ACTIVITY,
    DEFAULT_MODE_PROFILE_BOOST,
    DEFAULT_MODE_PROFILE_COOLDOWN,
    DEFAULT_MODE_PROFILE_HOME,
    DEFAULT_MODE_PROFILE_SLEEP,
    DEFAULT_MODE_PROFILE_WARMUP,
    DEFAULT_MODE_SLEEP,
    DEFAULT_MODE_WARMUP,
    DEFAULT_PROFILE,
    DEFAULT_PROFILE_AGGRESSIVE_COMFORT_MULTIPLIER,
    DEFAULT_PROFILE_AGGRESSIVE_POINT_SPACING,
    DEFAULT_PROFILE_BALANCED_COMFORT_MULTIPLIER,
    DEFAULT_PROFILE_BALANCED_POINT_SPACING,
    DEFAULT_PROFILE_RELAXED_COMFORT_MULTIPLIER,
    DEFAULT_PROFILE_RELAXED_POINT_SPACING,
    DEFAULT_PROFILE_RESPONSIVE_COMFORT_MULTIPLIER,
    DEFAULT_PROFILE_RESPONSIVE_POINT_SPACING,
    DEFAULT_TEMP_STEP,
    DOMAIN,
    ENTRY_TYPE_GLOBAL,
    MODE_AWAY,
    MODE_ACTIVITY,
    MODE_BOOST,
    MODE_COOLDOWN,
    MODE_ENABLE_DEFAULTS,
    MODE_ENABLE_KEYS,
    MODE_HOME,
    MODE_OPTIONS,
    OPTIONAL_MODE_OPTIONS,
    MODE_SLEEP,
    MODE_WARMUP,
    PROFILE_AGGRESSIVE,
    PROFILE_BALANCED,
    PROFILE_RELAXED,
    PROFILE_RESPONSIVE,
    ROLE_COOLING,
    ROLE_DEHUMIDIFY,
    ROLE_HEATING,
    SECONDARY_UNSET,
)

_LOGGER = logging.getLogger(__name__)

_HVAC_MODE_MAP: dict[str, HVACMode] = {
    "heat_cool": HVACMode.HEAT_COOL,
    "heat": HVACMode.HEAT,
    "cool": HVACMode.COOL,
}

_LEGACY_MODE_ALIASES: dict[str, str] = {
    "warmup": MODE_WARMUP,
    "cooldown": MODE_COOLDOWN,
}


def _enabled_modes_from_config(cfg: dict) -> list[str]:
    enabled = [MODE_HOME, MODE_AWAY]
    for mode in OPTIONAL_MODE_OPTIONS:
        key = MODE_ENABLE_KEYS[mode]
        default = MODE_ENABLE_DEFAULTS[key]
        if bool(cfg.get(key, default)):
            enabled.append(mode)
    return enabled


_HOUSE_MODE_TO_PRESET: dict[str, str] = {
    **_LEGACY_MODE_ALIASES,
    **{mode: mode for mode in MODE_OPTIONS},
}

_PROFILE_CONFIG = {
    PROFILE_RELAXED: (
        CONF_PROFILE_RELAXED_COMFORT_MULTIPLIER,
        CONF_PROFILE_RELAXED_POINT_SPACING,
        DEFAULT_PROFILE_RELAXED_COMFORT_MULTIPLIER,
        DEFAULT_PROFILE_RELAXED_POINT_SPACING,
    ),
    PROFILE_BALANCED: (
        CONF_PROFILE_BALANCED_COMFORT_MULTIPLIER,
        CONF_PROFILE_BALANCED_POINT_SPACING,
        DEFAULT_PROFILE_BALANCED_COMFORT_MULTIPLIER,
        DEFAULT_PROFILE_BALANCED_POINT_SPACING,
    ),
    PROFILE_RESPONSIVE: (
        CONF_PROFILE_RESPONSIVE_COMFORT_MULTIPLIER,
        CONF_PROFILE_RESPONSIVE_POINT_SPACING,
        DEFAULT_PROFILE_RESPONSIVE_COMFORT_MULTIPLIER,
        DEFAULT_PROFILE_RESPONSIVE_POINT_SPACING,
    ),
    PROFILE_AGGRESSIVE: (
        CONF_PROFILE_AGGRESSIVE_COMFORT_MULTIPLIER,
        CONF_PROFILE_AGGRESSIVE_POINT_SPACING,
        DEFAULT_PROFILE_AGGRESSIVE_COMFORT_MULTIPLIER,
        DEFAULT_PROFILE_AGGRESSIVE_POINT_SPACING,
    ),
}

_MODE_CONFIG = {
    MODE_AWAY: (CONF_MODE_AWAY, CONF_MODE_AWAY_PROFILE, DEFAULT_MODE_AWAY, DEFAULT_MODE_PROFILE_AWAY),
    MODE_SLEEP: (CONF_MODE_SLEEP, CONF_MODE_SLEEP_PROFILE, DEFAULT_MODE_SLEEP, DEFAULT_MODE_PROFILE_SLEEP),
    MODE_HOME: (CONF_MODE_HOME, CONF_MODE_HOME_PROFILE, DEFAULT_MODE_HOME, DEFAULT_MODE_PROFILE_HOME),
    MODE_WARMUP: (CONF_MODE_WARMUP, CONF_MODE_WARMUP_PROFILE, DEFAULT_MODE_WARMUP, DEFAULT_MODE_PROFILE_WARMUP),
    MODE_COOLDOWN: (CONF_MODE_COOLDOWN, CONF_MODE_COOLDOWN_PROFILE, DEFAULT_MODE_COOLDOWN, DEFAULT_MODE_PROFILE_COOLDOWN),
    MODE_ACTIVITY: (CONF_MODE_ACTIVITY, CONF_MODE_ACTIVITY_PROFILE, DEFAULT_MODE_ACTIVITY, DEFAULT_MODE_PROFILE_ACTIVITY),
    MODE_BOOST: (CONF_MODE_BOOST, CONF_MODE_BOOST_PROFILE, DEFAULT_MODE_BOOST, DEFAULT_MODE_PROFILE_BOOST),
}


def _get_global_config(hass: HomeAssistant) -> dict:
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_GLOBAL:
            return entry.data
    return {}


def _infer_hvac_modes(devices_data: list[dict]) -> list[HVACMode]:
    """
    Derive the supported HVAC modes from the configured device roles.

      Only heating devices  →  [Off, Heat]
      Only cooling devices  →  [Off, Cool]
      Both                  →  [Off, Heat/Cool, Heat, Cool]
      Neither (or only dehumidifiers / no devices yet)
                            →  [Off, Heat/Cool, Heat, Cool]  (safe default)
    """
    has_heating = any(d.get(CONF_DEVICE_ROLE) == ROLE_HEATING for d in devices_data)
    has_cooling = any(d.get(CONF_DEVICE_ROLE) == ROLE_COOLING for d in devices_data)

    if has_heating and has_cooling:
        return [HVACMode.OFF, HVACMode.HEAT_COOL, HVACMode.HEAT, HVACMode.COOL]
    if has_heating:
        return [HVACMode.OFF, HVACMode.HEAT]
    if has_cooling:
        return [HVACMode.OFF, HVACMode.COOL]
    # No temp-controlling devices yet — offer everything so the user isn't stuck
    return [HVACMode.OFF, HVACMode.HEAT_COOL, HVACMode.HEAT, HVACMode.COOL]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    entity = ClimateComfortEntity(hass, entry)
    # Store reference so number entities can update cached preset values live
    hass.data[DOMAIN][entry.entry_id]["climate_entity"] = entity
    async_add_entities([entity])


def _secondary(raw) -> str | None:
    """Normalise an optional secondary-attribute config value.

    Absent, empty, or the SECONDARY_UNSET sentinel all mean "not managed".
    """
    if raw is None:
        return None
    value = str(raw).strip()
    if not value or value == SECONDARY_UNSET:
        return None
    return value


class _Device:
    """Runtime wrapper for one controlled device stage."""

    def __init__(self, data: dict) -> None:
        self.entity_id: str = data[CONF_DEVICE_ENTITY]
        self.label: str = data.get(CONF_DEVICE_LABEL) or self.entity_id
        self.role: str = data[CONF_DEVICE_ROLE]

        # Temperature escalation fields (heating/cooling roles)
        if CONF_DEVICE_ACTIVATION_POINT in data:
            self.activation_point: int | None = int(data.get(CONF_DEVICE_ACTIVATION_POINT, 0))
        else:
            # Backward compatibility: old activate_offset was degrees beyond the boundary.
            # Leave activation_point unset so runtime continues using the absolute
            # degree offset instead of multiplying it by the active profile spacing.
            self.activation_point = None
        self.activate_offset: float = float(data.get(
            CONF_DEVICE_ACTIVATE_OFFSET,
            abs(self.activation_point) if self.activation_point is not None else 0.0,
        ))
        self.deactivate_offset: float = float(data.get(CONF_DEVICE_DEACTIVATE_OFFSET, 0.5))
        self.emergency_enabled: bool = bool(data.get(CONF_DEVICE_EMERGENCY_ENABLED, False))
        self.hvac_mode_on: str | None = data.get(CONF_DEVICE_HVAC_MODE_ON)
        # If set, service call also sets climate target = room_setpoint + this offset.
        # Use negative values for cooling (e.g. -3), positive for heating (e.g. +3).
        raw_offset = data.get(CONF_DEVICE_TARGET_TEMP_OFFSET)
        self.target_temp_offset: float | None = float(raw_offset) if raw_offset is not None else None

        # Optional secondary climate attributes, applied on activation alongside
        # hvac_mode. None/SECONDARY_UNSET means "not managed" — leave the device on
        # whatever it was, rather than forcing a value we were never given.
        self.fan_mode: str | None = _secondary(data.get(CONF_DEVICE_FAN_MODE))
        self.swing_mode: str | None = _secondary(data.get(CONF_DEVICE_SWING_MODE))
        self.swing_horizontal_mode: str | None = _secondary(
            data.get(CONF_DEVICE_SWING_HORIZONTAL_MODE)
        )

        # Humidity / dehumidifier fields
        self.humidity_threshold: float = float(data.get(CONF_DEVICE_HUMIDITY_THRESHOLD, 65.0))
        self.humidity_hysteresis: float = float(data.get(CONF_DEVICE_HUMIDITY_HYSTERESIS, 5.0))
        self.dehumidify_only_when_idle: bool = bool(data.get(CONF_DEVICE_DEHUMIDIFY_ONLY_WHEN_IDLE, True))

        self.is_active: bool = False

    @property
    def is_climate(self) -> bool:
        return self.entity_id.startswith("climate.")


class ClimateComfortEntity(ClimateEntity):
    """
    Multi-stage room thermostat with comfort-zone deadband.

    Temperature devices escalate in/out as the room drifts beyond the comfort zone.
    The same climate entity can appear as multiple stages (e.g. fan_only at boundary,
    cool at +3°C) — only the highest active stage is ever applied, so the device
    never flip-flops between two modes.

    Dehumidifier devices are evaluated independently against a humidity sensor,
    optionally only running when temperature control is idle.

    Away mode uses the configured global minimum and maximum temperatures as a
    protection band rather than a custom editable setpoint.
    """

    _attr_has_entity_name = True
    _attr_name = None
    _attr_icon = "mdi:thermostat-auto"
    _attr_should_poll = False
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_min_temp = DEFAULT_MIN_TEMP
    _attr_max_temp = DEFAULT_MAX_TEMP
    _attr_target_temperature_step = DEFAULT_TEMP_STEP

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = entry.entry_id

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.data["name"],
            manufacturer="Climate Comfort",
            model="Multi-Stage Thermostat",
        )

        cfg = entry.data
        opts = entry.options
        g = _get_global_config(hass)

        self._temp_sensor: str = cfg[CONF_TEMPERATURE_SENSOR]
        self._humidity_sensor: str | None = cfg.get(CONF_HUMIDITY_SENSOR)
        self._house_mode_entity: str | None = cfg.get(CONF_HOUSE_MODE_ENTITY)

        # Modes are inferred from the configured device roles; no manual selection needed.
        devices_data: list[dict] = opts.get(CONF_DEVICES, [])
        self._attr_hvac_modes = _infer_hvac_modes(devices_data)

        use_global = bool(cfg.get(CONF_USE_GLOBAL_PRESETS, False))
        self._global_comfort_zone: float = float(g.get(CONF_COMFORT_ZONE, DEFAULT_COMFORT_ZONE))
        self._local_comfort_zone: float = float(cfg.get(CONF_COMFORT_ZONE, self._global_comfort_zone))
        self._comfort_zone: float = (
            self._global_comfort_zone if use_global else self._local_comfort_zone
        )

        def _resolve(key: str, default: float) -> float:
            # When "use global presets" is on, skip local values for preset keys
            if not use_global:
                v = cfg.get(key)
                if v is not None:
                    return float(v)
            v = g.get(key)
            if v is not None:
                return float(v)
            return default

        self._minimum_temperature: float = float(g.get(CONF_MINIMUM_TEMPERATURE, DEFAULT_MIN_TEMP))
        self._maximum_temperature: float = float(g.get(CONF_MAXIMUM_TEMPERATURE, DEFAULT_MAX_TEMP))

        self._profile_settings: dict[str, tuple[float, float]] = {}
        for profile, (comfort_key, spacing_key, comfort_default, spacing_default) in _PROFILE_CONFIG.items():
            self._profile_settings[profile] = (
                float(cfg.get(comfort_key, g.get(comfort_key, comfort_default))),
                float(cfg.get(spacing_key, g.get(spacing_key, spacing_default))),
            )

        self._mode_temps: dict[str, float] = {}
        self._mode_profiles: dict[str, str] = {}
        for mode, (temp_key, profile_key, temp_default, profile_default) in _MODE_CONFIG.items():
            self._mode_temps[mode] = _resolve(temp_key, temp_default)
            self._mode_profiles[mode] = str(g.get(profile_key, cfg.get(profile_key, profile_default)))
        # Away exposes a midpoint setpoint for UI/attributes, but its actual control
        # band always comes from the configured global minimum/maximum temperatures.
        self._mode_temps[MODE_AWAY] = round((self._minimum_temperature + self._maximum_temperature) / 2, 1)

        mode_source = g or cfg
        self._enabled_modes = _enabled_modes_from_config(mode_source)
        self._attr_preset_modes = [PRESET_NONE, *self._enabled_modes]
        self._attr_preset_mode = MODE_HOME

        self._devices: list[_Device] = [_Device(d) for d in devices_data]

        # Tracks which temperature-control stage is currently applied to each
        # climate entity. A single climate entity may have heating and cooling
        # stages; resolve the winner per entity before issuing service calls.
        self._active_climate_stage: dict[str, _Device | None] = {}

        # Pick the best default: prefer HEAT_COOL, then first non-OFF mode, then OFF.
        non_off = [m for m in self._attr_hvac_modes if m != HVACMode.OFF]
        default_mode = (
            HVACMode.HEAT_COOL if HVACMode.HEAT_COOL in self._attr_hvac_modes
            else (non_off[0] if non_off else HVACMode.OFF)
        )
        self._attr_hvac_mode: HVACMode = default_mode
        self._attr_current_temperature: float | None = None
        self._attr_current_humidity: float | None = None
        self._attr_hvac_action: HVACAction = HVACAction.IDLE
        # supported_features is a dynamic property — see below

        # Manual hold tracking -------------------------------------------
        # How many hours to suspend automated control after a manual change.
        # 0 disables the feature.
        self._hold_hours: float = float(
            cfg.get(CONF_MANUAL_HOLD_HOURS, DEFAULT_MANUAL_HOLD_HOURS)
        )
        self._manual_hold_confirm_seconds: float = float(
            cfg.get(CONF_MANUAL_HOLD_CONFIRM_SECONDS, DEFAULT_MANUAL_HOLD_CONFIRM_SECONDS)
        )
        # entity_id → first monotonic timestamp when a non-own mismatch was seen.
        # A hold only starts if the same mismatch persists for the confirmation window.
        self._manual_mismatch_seen: dict[str, float] = {}
        # entity_id → {"since": datetime, "user_id": str|None}
        self._manual_holds: dict[str, dict] = {}
        # True once the first evaluation has run and is_active flags are in sync.
        # On the very first evaluation we align is_active with actual device state
        # rather than treating any divergence as a manual override.
        self._initial_sync_done: bool = False
        # Timestamp (monotonic) of the last service call we made per entity.
        # State changes arriving within _OWN_CHANGE_WINDOW seconds of a call
        # are treated as our own and don't trigger a manual hold.
        self._last_integration_touch: dict[str, float] = {}

        self._attr_target_temperature: float = self._mode_temps[MODE_HOME]
        self._profile_override: str | None = (
            hass.data.get(DOMAIN, {}).get(entry.entry_id, {}).get("profile_override")
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def async_added_to_hass(self) -> None:
        entities_to_track = [self._temp_sensor]
        if self._humidity_sensor:
            entities_to_track.append(self._humidity_sensor)
        if self._house_mode_entity:
            entities_to_track.append(self._house_mode_entity)

        self.async_on_remove(
            async_track_state_change_event(
                self.hass, entities_to_track, self._handle_state_change
            )
        )



        if state := self.hass.states.get(self._temp_sensor):
            self._apply_temp_state(state)
        if self._humidity_sensor:
            if state := self.hass.states.get(self._humidity_sensor):
                self._apply_humidity_state(state)

        # Pre-populate thresholds immediately so diagnostic binary sensors
        # show trigger temperatures before the first temperature reading arrives.
        lt, ut = self._thresholds()
        entry_data = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {})
        entry_data["thresholds"] = {
            "lt": round(lt, 2),
            "ut": round(ut, 2),
            "setpoint": self._attr_target_temperature,
            "preset": self._attr_preset_mode,
            "point_spacing": self._profile_point_spacing(),
        }

        self.hass.async_create_task(self._evaluate_devices())

    @callback
    def _handle_state_change(self, event) -> None:
        new_state = event.data.get("new_state")
        if new_state is None:
            return
        entity_id: str = event.data.get("entity_id", "")

        if entity_id == self._temp_sensor:
            # Pass unavailable/unknown through to _apply_temp_state — it handles
            # fail-safe shutdown and marks the entity unavailable.
            self._apply_temp_state(new_state)
            self.hass.async_create_task(self._evaluate_devices())
            self.async_write_ha_state()

        elif entity_id == self._humidity_sensor:
            if new_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                self._attr_current_humidity = None
                self.hass.async_create_task(self._turn_off_dehumidifiers())
                self.async_write_ha_state()
                return
            self._apply_humidity_state(new_state)
            self.hass.async_create_task(self._evaluate_devices())
            self.async_write_ha_state()

        elif entity_id == self._house_mode_entity:
            preset = _HOUSE_MODE_TO_PRESET.get(new_state.state.lower())
            if preset and preset in self._enabled_modes:
                self._attr_preset_mode = preset
                if preset == MODE_AWAY:
                    self._attr_target_temperature = round((self._minimum_temperature + self._maximum_temperature) / 2, 1)
                else:
                    self._attr_target_temperature = self._mode_temps.get(preset, self._attr_target_temperature)
                self._restore_configured_comfort_zone()
                self.hass.async_create_task(self._evaluate_devices())
                self.async_write_ha_state()

    # How long after our last service call to a device we consider subsequent
    # state changes as "ours" and not manual overrides.
    _OWN_CHANGE_WINDOW: float = 5.0  # seconds

    def _device_is_on(self, entity_id: str) -> bool:
        """Read the actual current on/off state of a controlled entity."""
        state = self.hass.states.get(entity_id)
        if state is None:
            return False
        if entity_id.startswith("climate."):
            return state.state not in ("off", "unavailable", "unknown")
        return state.state in ("on",)

    def _device_target_hvac_mode(self, device: _Device) -> str:
        """Return the HA HVAC mode this configured climate stage represents."""
        if device.role == ROLE_DEHUMIDIFY:
            return device.hvac_mode_on or "dry"
        return device.hvac_mode_on or (
            "heat" if device.role == ROLE_HEATING else "cool"
        )

    def _device_matches_actual(self, device: _Device) -> bool:
        """Return True when the real entity state matches this specific stage."""
        state = self.hass.states.get(device.entity_id)
        if state is None:
            return False
        if device.is_climate:
            return state.state == self._device_target_hvac_mode(device)
        return state.state in ("on",)

    def _check_manual_changes(self) -> None:
        """
        Compare each device's expected state (is_active) against its actual
        state in the HA state machine.

        On the very first call after startup, skip hold detection and just
        align is_active with actual state — devices left on before HA started
        are not manual overrides.

        On subsequent calls, any divergence that isn't from a recent service
        call of ours is treated as a manual override and starts a hold.
        """
        if not self._initial_sync_done:
            # Startup sync: align each configured stage with its specific real
            # state, no holds triggered.  For climate entities that appear as
            # multiple stages (cool/fan_only/dry), do not mark every stage active
            # just because the entity is not off; match the actual HVAC mode.
            for device in self._devices:
                device.is_active = self._device_matches_actual(device)
            self._initial_sync_done = True
            return

        if self._hold_hours <= 0:
            return

        # For multi-stage climate groups, track per entity_id (not per stage)
        checked: set[str] = set()

        for device in self._devices:
            eid = device.entity_id
            if eid in checked or self._is_in_manual_hold(eid):
                continue
            checked.add(eid)

            expected_on_by_entity = any(
                d.is_active for d in self._devices if d.entity_id == eid
            )
            actual_on = self._device_is_on(eid)
            last_touch = self._last_integration_touch.get(eid, 0.0)
            recently_touched = time.monotonic() - last_touch < self._OWN_CHANGE_WINDOW

            if not recently_touched and actual_on != expected_on_by_entity:
                now = time.monotonic()
                first_seen = self._manual_mismatch_seen.get(eid)
                if first_seen is None:
                    self._manual_mismatch_seen[eid] = now
                    continue
                mismatch_for = now - first_seen
                if mismatch_for < self._manual_hold_confirm_seconds:
                    continue
                self._manual_mismatch_seen.pop(eid, None)
                self._trigger_manual_hold(eid)
            else:
                self._manual_mismatch_seen.pop(eid, None)

    def _trigger_manual_hold(self, entity_id: str) -> None:
        """Record a manual hold and schedule automatic resume."""
        self._manual_holds[entity_id] = {"since": dt_util.utcnow(), "user_id": None}
        _LOGGER.info(
            "climate_comfort [%s]: manual override detected on %s — "
            "automated control suspended for %.1f h",
            self._entry.data.get("name"),
            entity_id,
            self._hold_hours,
        )

        @callback
        def _resume(_now=None) -> None:
            self._manual_holds.pop(entity_id, None)
            # Mark as recently touched so _check_manual_changes doesn't
            # immediately re-trigger a hold when it sees the device may still
            # be in a state that diverges from is_active.  The evaluation that
            # follows will either bring the device in line or leave it as-is.
            self._mark_integration_touch(entity_id)
            _LOGGER.info(
                "climate_comfort [%s]: hold expired for %s — resuming control",
                self._entry.data.get("name"),
                entity_id,
            )
            self.hass.async_create_task(self._evaluate_devices())
            self.async_write_ha_state()

        self.async_on_remove(
            async_call_later(self.hass, self._hold_hours * 3600, _resume)
        )

    def _is_in_manual_hold(self, entity_id: str) -> bool:
        """Return True if this entity is currently in a manual hold period."""
        if self._hold_hours <= 0 or entity_id not in self._manual_holds:
            return False
        hold = self._manual_holds[entity_id]
        resume_at = hold["since"] + timedelta(hours=self._hold_hours)
        if dt_util.utcnow() < resume_at:
            return True
        self._manual_holds.pop(entity_id, None)  # expired — clean up
        return False

    def _apply_temp_state(self, state) -> None:
        if state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            _LOGGER.warning(
                "climate_comfort [%s]: temperature sensor %s is %s — "
                "turning off all devices and marking unavailable",
                self._entry.data.get("name"), self._temp_sensor, state.state,
            )
            self._attr_current_temperature = None
            self._attr_available = False
            self.hass.async_create_task(self._turn_off_all())
            return

        self._attr_available = True
        try:
            temperature = float(state.state)
            if not math.isfinite(temperature):
                raise ValueError("temperature is not finite")
            self._attr_current_temperature = temperature
        except (ValueError, TypeError):
            _LOGGER.warning(
                "climate_comfort [%s]: bad temperature '%s' from %s — "
                "turning off all devices and marking unavailable",
                self._entry.data.get("name"), state.state, self._temp_sensor,
            )
            self._attr_current_temperature = None
            self._attr_available = False
            self.hass.async_create_task(self._turn_off_all())

    def _apply_humidity_state(self, state) -> None:
        try:
            humidity = float(state.state)
            if not math.isfinite(humidity):
                raise ValueError("humidity is not finite")
            self._attr_current_humidity = humidity
        except (ValueError, TypeError):
            _LOGGER.warning(
                "climate_comfort [%s]: bad humidity '%s' from %s — "
                "turning off dehumidifiers",
                self._entry.data.get("name"), state.state, self._humidity_sensor,
            )
            self._attr_current_humidity = None
            self.hass.async_create_task(self._turn_off_dehumidifiers())

    # ------------------------------------------------------------------
    # Extra state attributes
    # ------------------------------------------------------------------

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        lt, ut = self._thresholds()
        active_profile = self._active_profile()
        comfort_multiplier, point_spacing = self._profile_settings.get(
            active_profile, self._profile_settings[PROFILE_BALANCED]
        )
        attrs: dict[str, Any] = {
            ATTR_COMFORT_ZONE: self._comfort_zone,
            "effective_comfort_zone": round(self._comfort_zone * comfort_multiplier, 2),
            "mode": self._attr_preset_mode,
            "profile": active_profile,
            "comfort_multiplier": comfort_multiplier,
            "point_spacing": point_spacing,
            "minimum_temperature": self._minimum_temperature,
            "maximum_temperature": self._maximum_temperature,
            ATTR_LOWER_THRESHOLD: round(lt, 2),
            ATTR_UPPER_THRESHOLD: round(ut, 2),
            ATTR_EFFECTIVE_SETPOINT: self._attr_target_temperature,
            ATTR_ACTIVE_DEVICES: [d.entity_id for d in self._devices if d.is_active],
        }
        if self._humidity_sensor:
            attrs[ATTR_CURRENT_HUMIDITY] = self._attr_current_humidity

        # Manual holds — show which devices are in hold and time remaining
        if self._manual_holds:
            now = dt_util.utcnow()
            hold_info: dict[str, str] = {}
            for eid, hold in list(self._manual_holds.items()):
                resume_at = hold["since"] + timedelta(hours=self._hold_hours)
                remaining = (resume_at - now).total_seconds()
                if remaining > 0:
                    mins = int(remaining / 60)
                    by = f" by user {hold['user_id']}" if hold.get("user_id") else ""
                    hold_info[eid] = f"manual hold — {mins} min remaining{by}"
            if hold_info:
                attrs["manual_holds"] = hold_info

        return attrs

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Dynamic feature flags and range temperature properties
    # ------------------------------------------------------------------

    @property
    def supported_features(self) -> ClimateEntityFeature:
        """
        Heat/Cool mode exposes independent low/high handles on the thermostat
        card via TARGET_TEMPERATURE_RANGE.  Heat or Cool alone uses a single
        target temperature, matching the standard thermostat card behaviour.
        """
        base = ClimateEntityFeature.PRESET_MODE
        if self._attr_hvac_mode == HVACMode.HEAT_COOL:
            return base | ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
        return base | ClimateEntityFeature.TARGET_TEMPERATURE

    @property
    def target_temperature(self) -> float | None:
        """
        Return the single target temperature for Heat or Cool mode.

        Rather than exposing the abstract midpoint setpoint, we show the user
        the actual activation temperature so "I want it warmer than X" (Heat)
        and "I want it cooler than Y" (Cool) feel natural:

          Heat mode  → lower threshold (LT): heating fires below this
          Cool mode  → upper threshold (UT): cooling fires above this
          Heat/Cool  → midpoint (card uses low/high handles instead)
          Off        → midpoint (informational)
        """
        lt, ut = self._thresholds()
        if self._attr_hvac_mode == HVACMode.HEAT:
            return lt
        if self._attr_hvac_mode == HVACMode.COOL:
            return ut
        return round((lt + ut) / 2, 1)

    @property
    def target_temperature_low(self) -> float | None:
        """Lower comfort boundary — heating activates below this."""
        if self._attr_hvac_mode != HVACMode.HEAT_COOL:
            return None
        lt, _ = self._thresholds()
        return lt

    @property
    def target_temperature_high(self) -> float | None:
        """Upper comfort boundary — cooling activates above this."""
        if self._attr_hvac_mode != HVACMode.HEAT_COOL:
            return None
        _, ut = self._thresholds()
        return ut

    # ------------------------------------------------------------------
    # HA service handlers
    # ------------------------------------------------------------------

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode not in self._attr_hvac_modes:
            raise HomeAssistantError(f"Unsupported HVAC mode: {hvac_mode}")
        self._attr_hvac_mode = hvac_mode
        if hvac_mode == HVACMode.OFF:
            await self._turn_off_all()
            self._attr_hvac_action = HVACAction.OFF
        else:
            await self._evaluate_devices()
        self.async_write_ha_state()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        if preset_mode != PRESET_NONE and preset_mode not in self._attr_preset_modes:
            raise HomeAssistantError(f"Unsupported preset mode: {preset_mode}")
        self._attr_preset_mode = preset_mode
        if preset_mode == MODE_AWAY:
            self._attr_target_temperature = round((self._minimum_temperature + self._maximum_temperature) / 2, 1)
            self._restore_configured_comfort_zone()
        elif preset_mode not in (PRESET_NONE,):
            self._attr_target_temperature = self._mode_temps.get(preset_mode, self._attr_target_temperature)
            # Restore the configured base comfort zone so slider drags don't silently
            # inherit a modified zone.
            self._restore_configured_comfort_zone()
        await self._evaluate_devices()
        self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        requested_hvac_mode = kwargs.get("hvac_mode")
        if requested_hvac_mode is not None:
            try:
                hvac_mode = HVACMode(requested_hvac_mode)
            except ValueError as err:
                raise HomeAssistantError(
                    f"Unsupported HVAC mode: {requested_hvac_mode}"
                ) from err
            if hvac_mode not in self._attr_hvac_modes:
                raise HomeAssistantError(f"Unsupported HVAC mode: {hvac_mode}")
            self._attr_hvac_mode = hvac_mode

        lt = kwargs.get(ATTR_TARGET_TEMP_LOW)
        ut = kwargs.get(ATTR_TARGET_TEMP_HIGH)
        temp = kwargs.get(ATTR_TEMPERATURE)

        if lt is not None and ut is not None:
            # Range drag in Heat/Cool mode.
            # Derive the new setpoint (midpoint) and comfort zone (half-width).
            lt, ut = float(lt), float(ut)
            if ut <= lt:
                return  # Guard against invalid ranges
            self._attr_target_temperature = round((lt + ut) / 2, 1)
            self._comfort_zone = round((ut - lt) / 2, 2)
            self._attr_preset_mode = PRESET_NONE
            # _comfort_zone is intentionally NOT persisted here — the slider is
            # live/exploratory.  Selecting a preset restores the configured zone.

        elif temp is not None:
            # Single temperature drag.
            # The displayed handle sits at LT (Heat) or UT (Cool), so we
            # back-derive the internal setpoint preserving the comfort zone.
            temp = float(temp)
            if self._attr_hvac_mode == HVACMode.HEAT:
                # User is setting LT directly: new setpoint = LT + comfort_zone
                self._attr_target_temperature = temp + self._comfort_zone
            elif self._attr_hvac_mode == HVACMode.COOL:
                # User is setting UT directly: new setpoint = UT - comfort_zone
                self._attr_target_temperature = temp - self._comfort_zone
            else:
                self._attr_target_temperature = temp
            self._attr_preset_mode = PRESET_NONE

        else:
            return

        await self._evaluate_devices()
        self.async_write_ha_state()

    # ------------------------------------------------------------------
    # Core control logic
    # ------------------------------------------------------------------

    def _restore_configured_comfort_zone(self) -> None:
        """Restore the configured comfort zone after transient slider adjustments."""
        if bool(self._entry.data.get(CONF_USE_GLOBAL_PRESETS, False)):
            self._comfort_zone = self._global_comfort_zone
        else:
            self._comfort_zone = self._local_comfort_zone

    def _active_profile(self) -> str:
        if self._profile_override:
            return self._profile_override
        if self._attr_preset_mode in self._mode_profiles:
            return self._mode_profiles[self._attr_preset_mode]
        return str(self._entry.data.get(CONF_DEFAULT_PROFILE, DEFAULT_PROFILE))

    def _profile_comfort_multiplier(self) -> float:
        return self._profile_settings.get(self._active_profile(), self._profile_settings[PROFILE_BALANCED])[0]

    def _profile_point_spacing(self) -> float:
        return self._profile_settings.get(self._active_profile(), self._profile_settings[PROFILE_BALANCED])[1]

    def _activation_offset_for_device(self, device: _Device, point_spacing: float | None = None) -> float:
        """
        Return the actual degrees beyond the comfort boundary for a device.

        New configs store a discrete activation point that scales with the active
        aggressiveness profile.  Legacy configs only have activate_offset, which
        was already an absolute °C value and must not be multiplied by spacing.
        """
        if device.activation_point is None:
            return device.activate_offset
        spacing = self._profile_point_spacing() if point_spacing is None else point_spacing
        return abs(device.activation_point) * spacing

    def _thresholds(self) -> tuple[float, float]:
        if self._attr_preset_mode == MODE_AWAY:
            return self._minimum_temperature, self._maximum_temperature
        sp = self._attr_target_temperature
        effective_comfort_zone = self._comfort_zone * self._profile_comfort_multiplier()
        return sp - effective_comfort_zone, sp + effective_comfort_zone

    async def _evaluate_devices(self) -> None:
        # Check for manual changes before doing anything else.
        # Compares expected state (is_active) against actual HA state.
        self._check_manual_changes()

        if self._attr_hvac_mode == HVACMode.OFF:
            await self._turn_off_all()
            self._attr_hvac_action = HVACAction.OFF
            return

        current = self._attr_current_temperature
        if current is None:
            return

        lt, ut = self._thresholds()
        point_spacing = self._profile_point_spacing()
        emergency_heat = current <= self._minimum_temperature
        emergency_cool = current >= self._maximum_temperature
        mode_allows_heating = self._attr_hvac_mode in (HVACMode.HEAT, HVACMode.HEAT_COOL)
        mode_allows_cooling = self._attr_hvac_mode in (HVACMode.COOL, HVACMode.HEAT_COOL)
        any_heating = False
        any_cooling = False

        # ── Separate devices by type ──────────────────────────────────────
        # Climate entities with the same entity_id form an escalation group.
        # Switch/fan entities are always independent.
        climate_groups: dict[str, list[_Device]] = defaultdict(list)
        switch_devices: list[_Device] = []
        dehumidifier_devices: list[_Device] = []

        for device in self._devices:
            if device.role == ROLE_DEHUMIDIFY:
                dehumidifier_devices.append(device)
            elif device.is_climate:
                climate_groups[device.entity_id].append(device)
            else:
                switch_devices.append(device)

        # ── Evaluate switch/fan devices ───────────────────────────────────
        for device in switch_devices:
            if self._is_in_manual_hold(device.entity_id):
                continue  # manual hold in effect — don't touch this device
            if device.role == ROLE_HEATING and mode_allows_heating:
                activate_at = lt - self._activation_offset_for_device(device, point_spacing)
                deactivate_at = activate_at + device.deactivate_offset
                should_activate = current <= activate_at or (emergency_heat and device.emergency_enabled)
                if should_activate and not device.is_active:
                    await self._activate_device(device)
                elif current >= deactivate_at and device.is_active:
                    await self._deactivate_device(device)
                if device.is_active:
                    any_heating = True

            elif device.role == ROLE_COOLING and mode_allows_cooling:
                activate_at = ut + self._activation_offset_for_device(device, point_spacing)
                deactivate_at = activate_at - device.deactivate_offset
                should_activate = current >= activate_at or (emergency_cool and device.emergency_enabled)
                if should_activate and not device.is_active:
                    await self._activate_device(device)
                elif current <= deactivate_at and device.is_active:
                    await self._deactivate_device(device)
                if device.is_active:
                    any_cooling = True

            else:
                if device.is_active:
                    await self._deactivate_device(device)

        # ── Evaluate climate escalation groups ────────────────────────────
        # For each unique climate entity, decide the single winning
        # temperature-control stage before making any service calls. This
        # avoids one role turning off a climate entity just activated by
        # another role.
        for entity_id, stages in climate_groups.items():
            if self._is_in_manual_hold(entity_id):
                continue  # manual hold in effect — don't touch this entity

            for stage in stages:
                if stage.role == ROLE_HEATING:
                    if not mode_allows_heating:
                        stage.is_active = False
                        continue
                    activate_at = lt - self._activation_offset_for_device(stage, point_spacing)
                    deactivate_at = activate_at + stage.deactivate_offset
                    if current <= activate_at or (emergency_heat and stage.emergency_enabled):
                        stage.is_active = True
                    elif current >= deactivate_at:
                        stage.is_active = False

                elif stage.role == ROLE_COOLING:
                    if not mode_allows_cooling:
                        stage.is_active = False
                        continue
                    activate_at = ut + self._activation_offset_for_device(stage, point_spacing)
                    deactivate_at = activate_at - stage.deactivate_offset
                    if current >= activate_at or (emergency_cool and stage.emergency_enabled):
                        stage.is_active = True
                    elif current <= deactivate_at:
                        stage.is_active = False

            active_stages = [s for s in stages if s.is_active]
            winning = (
                max(active_stages, key=lambda s: self._activation_offset_for_device(s, point_spacing))
                if active_stages else None
            )
            prev = self._active_climate_stage.get(entity_id)

            if winning != prev:
                if winning is None:
                    await self._set_climate_off(entity_id)
                else:
                    await self._activate_device(winning)
                self._active_climate_stage[entity_id] = winning

            if winning is not None:
                if winning.role == ROLE_HEATING:
                    any_heating = True
                elif winning.role == ROLE_COOLING:
                    any_cooling = True

        # ── Evaluate dehumidifier devices ─────────────────────────────────
        entry_data = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {})
        dehumidify_enabled = entry_data.get("dehumidify_enabled", True)

        current_humidity = self._attr_current_humidity
        for device in dehumidifier_devices:
            if current_humidity is None:
                continue
            # User can suspend dehumidification via the switch entity
            if not dehumidify_enabled:
                if device.is_active:
                    await self._deactivate_or_release_device(device)
                continue
            # Optionally suppress dehumidification when heating/cooling is active
            if device.dehumidify_only_when_idle and (any_heating or any_cooling):
                if device.is_active:
                    await self._deactivate_or_release_device(device)
                continue

            activate_at = device.humidity_threshold
            deactivate_at = activate_at - device.humidity_hysteresis
            if current_humidity >= activate_at and not device.is_active:
                await self._activate_device(device)
            elif current_humidity <= deactivate_at and device.is_active:
                await self._deactivate_or_release_device(device)

        # ── Update HVAC action ────────────────────────────────────────────
        if any_heating:
            self._attr_hvac_action = HVACAction.HEATING
        elif any_cooling:
            self._attr_hvac_action = HVACAction.COOLING
        else:
            self._attr_hvac_action = HVACAction.IDLE

        self._sync_binary_sensors()

    # ------------------------------------------------------------------
    # Device activation helpers
    # ------------------------------------------------------------------

    def _mark_integration_touch(self, entity_id: str) -> None:
        """Record that we just issued a service call for this entity."""
        self._last_integration_touch[entity_id] = time.monotonic()

    async def _apply_secondary_settings(self, device: _Device) -> None:
        """Apply optional fan speed / swing directions after the primary mode is set.

        Vertical and horizontal swing are independent in Home Assistant and are
        applied as separate service calls; a device may support either or both.

        Deliberately NON-FATAL, and deliberately not inside the caller's rollback.
        By the time this runs, set_hvac_mode (and any set_temperature) has already
        succeeded — the device IS heating or cooling. If a fan-direction call then
        fails because the device rejects that value, the right outcome is a warning,
        not marking the device inactive: that would roll `is_active` back to False
        while the hardware is running, and the next evaluation would activate it
        again, forever. Comfort control must not hinge on a swing setting.
        """
        for attr, value, service in (
            ("fan mode", device.fan_mode, "set_fan_mode"),
            ("vertical swing mode", device.swing_mode, "set_swing_mode"),
            (
                "horizontal swing mode",
                device.swing_horizontal_mode,
                "set_swing_horizontal_mode",
            ),
        ):
            if not value:
                continue  # not managed for this device
            try:
                self._mark_integration_touch(device.entity_id)
                await self.hass.services.async_call(
                    "climate", service,
                    {"entity_id": device.entity_id, service.replace("set_", ""): value},
                    blocking=True,
                )
            except Exception as err:
                _LOGGER.warning(
                    "climate_comfort: '%s' (%s) is active, but setting %s to '%s' failed: %s",
                    device.label, device.entity_id, attr, value, err,
                )

    async def _activate_device(self, device: _Device) -> None:
        _LOGGER.info("climate_comfort: activating '%s' (%s)", device.label, device.entity_id)
        self._mark_integration_touch(device.entity_id)
        try:
            if device.is_climate:
                if device.role == ROLE_DEHUMIDIFY:
                    mode = device.hvac_mode_on or "dry"
                else:
                    mode = device.hvac_mode_on or (
                        "heat" if device.role == ROLE_HEATING else "cool"
                    )
                await self.hass.services.async_call(
                    "climate", "set_hvac_mode",
                    {"entity_id": device.entity_id, "hvac_mode": mode},
                    blocking=True,
                )
                if device.target_temp_offset is not None:
                    ref = self._attr_target_temperature
                    magnitude = abs(device.target_temp_offset)
                    target = ref + magnitude if device.role == ROLE_HEATING else ref - magnitude
                    self._mark_integration_touch(device.entity_id)
                    await self.hass.services.async_call(
                        "climate", "set_temperature",
                        {"entity_id": device.entity_id, "temperature": round(target, 1)},
                        blocking=True,
                    )
                await self._apply_secondary_settings(device)
            else:
                await self.hass.services.async_call(
                    "homeassistant", "turn_on",
                    {"entity_id": device.entity_id},
                    blocking=True,
                )
            device.is_active = True  # Commit only after all calls succeed
        except Exception as err:
            _LOGGER.error(
                "climate_comfort: failed to activate '%s' (%s): %s",
                device.label, device.entity_id, err,
            )
            device.is_active = False  # Roll back — retry on next evaluation

    def _same_climate_has_active_temperature_stage(self, device: _Device) -> bool:
        """Return True if this climate entity is already being used for heat/cool."""
        if not device.is_climate:
            return False
        return any(
            other is not device
            and other.entity_id == device.entity_id
            and other.role in (ROLE_HEATING, ROLE_COOLING)
            and other.is_active
            for other in self._devices
        )

    async def _deactivate_or_release_device(self, device: _Device) -> None:
        """
        Deactivate a stage unless another temp-control stage owns the same climate.

        A physical aircon can be configured as cool/fan_only/dry stages against the
        same climate entity.  When dry is suppressed because cooling is active, do
        not call climate.set_hvac_mode(off), because that turns off the cooling
        stage that just won the temperature-control decision.  Just mark the dry
        stage inactive and let the owning heat/cool stage keep control.
        """
        if self._same_climate_has_active_temperature_stage(device):
            device.is_active = False
            self._sync_binary_sensors()
            return
        await self._deactivate_device(device)

    async def _deactivate_device(self, device: _Device) -> None:
        _LOGGER.info("climate_comfort: deactivating '%s' (%s)", device.label, device.entity_id)
        self._mark_integration_touch(device.entity_id)
        try:
            if device.is_climate:
                await self._set_climate_off(device.entity_id)
            else:
                await self.hass.services.async_call(
                    "homeassistant", "turn_off",
                    {"entity_id": device.entity_id},
                    blocking=True,
                )
            device.is_active = False  # Commit only after success
        except Exception as err:
            _LOGGER.error(
                "climate_comfort: failed to deactivate '%s' (%s): %s",
                device.label, device.entity_id, err,
            )
            # is_active stays True — device may still be on, retry next cycle

    async def _set_climate_off(self, entity_id: str) -> None:
        self._mark_integration_touch(entity_id)
        await self.hass.services.async_call(
            "climate", "set_hvac_mode",
            {"entity_id": entity_id, "hvac_mode": "off"},
            blocking=True,
        )

    async def _turn_off_all(self) -> None:
        turned_off: set[str] = set()
        for device in self._devices:
            if device.entity_id in turned_off:
                device.is_active = False
                continue
            if device.is_climate:
                await self._set_climate_off(device.entity_id)
            else:
                self._mark_integration_touch(device.entity_id)
                await self.hass.services.async_call(
                    "homeassistant", "turn_off",
                    {"entity_id": device.entity_id},
                    blocking=True,
                )
            turned_off.add(device.entity_id)
            device.is_active = False
        self._active_climate_stage.clear()
        self._sync_binary_sensors()

    async def _turn_off_dehumidifiers(self) -> None:
        """Turn off dehumidifier stages when humidity control is unavailable/disabled."""
        turned_off: set[str] = set()
        for device in self._devices:
            if device.role != ROLE_DEHUMIDIFY:
                continue
            if device.entity_id in turned_off:
                device.is_active = False
                continue
            if device.is_climate:
                await self._set_climate_off(device.entity_id)
            else:
                self._mark_integration_touch(device.entity_id)
                await self.hass.services.async_call(
                    "homeassistant", "turn_off",
                    {"entity_id": device.entity_id},
                    blocking=True,
                )
            turned_off.add(device.entity_id)
            device.is_active = False
        self._sync_binary_sensors()

    def _sync_binary_sensors(self) -> None:
        """Write device states and thresholds to hass.data, then refresh all sensors."""
        lt, ut = self._thresholds()
        entry_data = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {})
        entry_data["device_states"] = {
            f"{self._entry.entry_id}_device_{i}": device.is_active
            for i, device in enumerate(self._devices)
        }
        entry_data["thresholds"] = {
            "lt": round(lt, 2),
            "ut": round(ut, 2),
            "setpoint": self._attr_target_temperature,
            "preset": self._attr_preset_mode,
            "point_spacing": self._profile_point_spacing(),
        }
        # Share manual holds and hold duration so binary sensors can show override status
        entry_data["manual_holds"] = dict(self._manual_holds)
        entry_data["hold_hours"] = self._hold_hours

        for sensor in entry_data.get("device_sensors", []):
            if sensor.hass is None:
                continue
            # Update name so trigger temp stays current when setpoint changes
            sensor.update_trigger_name(lt, ut, self._profile_point_spacing())
            sensor.async_write_ha_state()
        for sensor in entry_data.get("room_sensors", []):
            if sensor.hass is None:
                continue
            sensor._refresh_value()
            sensor.async_write_ha_state()
        gp_switch = entry_data.get("global_presets_switch")
        if gp_switch and gp_switch.hass is not None:
            gp_switch._attr_is_on = bool(
                self._entry.data.get(CONF_USE_GLOBAL_PRESETS, False)
            )
            gp_switch.async_write_ha_state()
