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
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.restore_state import ExtraStoredData, RestoreEntity

from . import get_device_configs
from .const import (
    DATA_SCHEDULE,
    SIGNAL_MODE_REASSERTED,
    ATTR_ACTIVE_DEVICES,
    CONF_DEVICE_ID,
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
    CONF_DEVICE_MIN_OFF_MINUTES,
    CONF_DEVICE_MIN_ON_MINUTES,
    CONF_DEVICE_ROLE,
    CONF_DEVICE_SWING_HORIZONTAL_MODE,
    CONF_DEVICE_SWING_MODE,
    CONF_DEVICE_TARGET_TEMP_OFFSET,
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


class _ComfortExtraData(ExtraStoredData):
    """Manual holds, stored alongside the restored state.

    Holds live only in memory otherwise, so a restart or a reload of the room
    used to end them silently and hand a device the user had just taken over
    straight back to automation.
    """

    def __init__(self, manual_holds: dict[str, str]) -> None:
        self.manual_holds = manual_holds

    def as_dict(self) -> dict[str, Any]:
        return {"manual_holds": self.manual_holds}


def _state_is_on(entity_id: str, state: str | None) -> bool:
    """Whether a state value means the device is running."""
    if entity_id.startswith("climate."):
        return state not in (None, "off", "unavailable", "unknown")
    return state == "on"


class _Device:
    """Runtime wrapper for one controlled device stage."""

    def __init__(self, data: dict, index: int = 0) -> None:
        # Stable identity for this stage. Older configs have none until the
        # setup migration assigns one; fall back to the list position, which is
        # what the unique IDs used to be built from.
        self.id: str = str(data.get(CONF_DEVICE_ID) or index)
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

        # Short-cycle protection, in minutes (0 = no limit).
        self.min_on_minutes: float = max(0.0, float(data.get(CONF_DEVICE_MIN_ON_MINUTES) or 0))
        self.min_off_minutes: float = max(0.0, float(data.get(CONF_DEVICE_MIN_OFF_MINUTES) or 0))

        self.is_active: bool = False

    @property
    def is_climate(self) -> bool:
        return self.entity_id.startswith("climate.")


class ClimateComfortEntity(ClimateEntity, RestoreEntity):
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
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_min_temp = DEFAULT_MIN_TEMP
    _attr_max_temp = DEFAULT_MAX_TEMP
    _attr_target_temperature_step = DEFAULT_TEMP_STEP
    # Shown on the dashboard card, but they change with every temperature
    # reading or count down by the minute, so keep them out of the database.
    _unrecorded_attributes = frozenset({"stages", "manual_holds", "min_time_waits"})

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

        self._temp_sensor: str = cfg[CONF_TEMPERATURE_SENSOR]
        self._humidity_sensor: str | None = cfg.get(CONF_HUMIDITY_SENSOR)
        self._house_mode_entity: str | None = cfg.get(CONF_HOUSE_MODE_ENTITY)

        # Modes are inferred from the configured device roles; no manual selection needed.
        devices_data: list[dict] = get_device_configs(entry)
        self._attr_hvac_modes = _infer_hvac_modes(devices_data)

        self._attr_preset_mode = MODE_HOME
        self._load_settings()

        self._devices: list[_Device] = [
            _Device(d, idx) for idx, d in enumerate(devices_data)
        ]
        self._device_entity_ids: set[str] = {d.entity_id for d in self._devices}

        # Tracks which temperature-control stage is currently applied to each
        # climate entity. A single climate entity may have heating and cooling
        # stages; resolve the winner per entity before issuing service calls.
        self._active_climate_stage: dict[str, _Device | None] = {}
        # Last target temperature we sent to each climate entity, so a setpoint
        # change while a stage is already running can be pushed to the device
        # without re-sending an identical value on every evaluation.
        self._last_target_sent: dict[str, float] = {}
        # When each physical device last switched between on and off, by us or
        # by hand, for the minimum on / off times. Unknown (not seen to switch
        # since this room started) means no limit applies yet.
        self._last_switched: dict[str, Any] = {}
        # Devices the last evaluation wanted to switch but left as they are
        # until their minimum time ends: entity_id -> {"action", "until"}.
        self._min_time_waits: dict[str, dict[str, Any]] = {}

        # Evaluations make blocking service calls, and those calls change device
        # states, which in turn request another evaluation. Only one runs at a
        # time; requests arriving meanwhile are folded into a single re-run.
        self._evaluating: bool = False
        self._evaluate_again: bool = False

        # Pick the best default: prefer HEAT_COOL, then first non-OFF mode, then OFF.
        non_off = [m for m in self._attr_hvac_modes if m != HVACMode.OFF]
        default_mode = (
            HVACMode.HEAT_COOL if HVACMode.HEAT_COOL in self._attr_hvac_modes
            else (non_off[0] if non_off else HVACMode.OFF)
        )
        self._attr_hvac_mode: HVACMode = default_mode
        self._attr_native_current_temperature: float | None = None
        self._attr_current_humidity: float | None = None
        self._attr_hvac_action: HVACAction = HVACAction.IDLE
        # supported_features is a dynamic property — see below

        # Manual hold tracking -------------------------------------------
        # entity_id → first monotonic timestamp when a non-own mismatch was seen.
        # A hold only starts if the same mismatch persists for the confirmation window.
        self._manual_mismatch_seen: dict[str, float] = {}
        # entity_id → {"since": datetime, "user_id": str|None}
        self._manual_holds: dict[str, dict] = {}
        # entity_id → cancel callback for the timer that ends its hold.
        self._hold_timers: dict[str, Any] = {}
        # entity_ids whose real state we have actually observed. Hold detection is
        # only meaningful for these: an entity we have never seen (still loading at
        # boot) or one that has gone unavailable must never be judged a manual
        # override, because we have nothing trustworthy to compare against.
        self._synced_entities: set[str] = set()
        # True once the first evaluation has run and is_active flags are in sync.
        # On the very first evaluation we align is_active with actual device state
        # rather than treating any divergence as a manual override.
        self._initial_sync_done: bool = False
        # Timestamp (monotonic) of the last service call we made per entity.
        # State changes arriving within _OWN_CHANGE_WINDOW seconds of a call
        # are treated as our own and don't trigger a manual hold.
        self._last_integration_touch: dict[str, float] = {}

        # The room's setpoint (midpoint of the comfort band). Kept separate from
        # the temperature the thermostat card shows, which in Heat or Cool mode
        # is the activation threshold rather than the midpoint.
        self._setpoint: float = self._mode_temps[MODE_HOME]
        # This room's own schedule. While it is on, the room ignores House /
        # Floor Mode except for Away.
        self._schedule = hass.data.get(DOMAIN, {}).get(entry.entry_id, {}).get(DATA_SCHEDULE)
        self._profile_override: str | None = (
            hass.data.get(DOMAIN, {}).get(entry.entry_id, {}).get("profile_override")
        )

    def _load_settings(self) -> None:
        """Read everything tunable from the room entry and Global Defaults.

        Called at construction and again whenever a number or switch entity
        changes a setting, so those edits apply live without reloading the room.
        """
        cfg = self._entry.data
        g = _get_global_config(self.hass)
        use_global = bool(cfg.get(CONF_USE_GLOBAL_PRESETS, False))

        # The comfort zone is always the room's own value. "Use global presets"
        # governs preset temperatures only; the room form and the Comfort Zone
        # number both edit this value, so it must be the one that is applied.
        previous_zone = getattr(self, "_local_comfort_zone", None)
        self._local_comfort_zone: float = float(
            cfg.get(CONF_COMFORT_ZONE, g.get(CONF_COMFORT_ZONE, DEFAULT_COMFORT_ZONE))
        )
        if (
            previous_zone != self._local_comfort_zone
            or self._attr_preset_mode != PRESET_NONE
        ):
            # Keep a zone the user dragged on the card (preset None) unless the
            # configured value itself just changed.
            self._comfort_zone: float = self._local_comfort_zone

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

        # How many hours to suspend automated control after a manual change.
        # 0 disables the feature.
        self._hold_hours: float = float(
            cfg.get(CONF_MANUAL_HOLD_HOURS, DEFAULT_MANUAL_HOLD_HOURS)
        )
        self._manual_hold_confirm_seconds: float = float(
            cfg.get(CONF_MANUAL_HOLD_CONFIRM_SECONDS, DEFAULT_MANUAL_HOLD_CONFIRM_SECONDS)
        )

    async def async_settings_updated(self) -> None:
        """Apply a setting changed by a number or switch entity, without a reload."""
        self._load_settings()
        preset = self._attr_preset_mode
        if preset != PRESET_NONE and preset in self._mode_temps:
            self._setpoint = self._mode_temps[preset]
        await self._evaluate_devices()
        # Refresh the numbers and switch even when no evaluation could run
        # (thermostat off, or no temperature reading yet).
        self._sync_binary_sensors()
        self.async_write_ha_state()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @property
    def extra_restore_state_data(self) -> ExtraStoredData:
        return _ComfortExtraData(
            {
                eid: hold["since"].isoformat()
                for eid, hold in self._manual_holds.items()
            }
        )

    async def _restore_manual_holds(self) -> None:
        """Bring back holds that were still running before a restart or reload."""
        if self._hold_hours <= 0:
            return
        extra = await self.async_get_last_extra_data()
        if extra is None:
            return
        stored = extra.as_dict().get("manual_holds") or {}
        now = dt_util.utcnow()
        for entity_id, since_raw in stored.items():
            if entity_id not in self._device_entity_ids:
                continue  # device no longer part of this room
            since = dt_util.parse_datetime(str(since_raw))
            if since is None:
                continue
            if since + timedelta(hours=self._hold_hours) <= now:
                continue  # ran out while Home Assistant was down
            self._trigger_manual_hold(entity_id, since)

    @callback
    def async_entity_id_changed(self, old_entity_id: str) -> None:
        """Nothing here is keyed on our own entity_id, so a rename needs no work."""
        super().async_entity_id_changed(old_entity_id)

    async def async_will_remove_from_hass(self) -> None:
        for cancel in self._hold_timers.values():
            cancel()
        self._hold_timers.clear()

    async def _restore_previous_state(self) -> None:
        """Reinstate HVAC mode, preset and setpoint from before the restart.

        Without this, every Home Assistant restart silently reverted the room to
        the hardcoded Home / HEAT_COOL / 21 °C defaults, discarding whatever the
        user or an automation had set. That is not a cosmetic reset: a room left
        in Eco or Away comes back at a far more demanding setpoint and can start
        heating or cooling on its own within seconds of boot.

        A restored preset deliberately wins over the house/floor selector — a
        per-room override survives a restart. The selector is only consulted when
        there is nothing to restore, which means the first run after the room is
        created.
        """
        last = await self.async_get_last_state()
        if last is None:
            self._adopt_house_mode()
            return

        if last.state in self._attr_hvac_modes:
            self._attr_hvac_mode = HVACMode(last.state)

        preset = last.attributes.get("preset_mode")
        if preset in self._attr_preset_modes:
            self._attr_preset_mode = preset
            if preset in self._mode_temps:
                self._setpoint = self._mode_temps[preset]

        if self._attr_preset_mode != PRESET_NONE:
            # A named preset always uses its configured temperature, so a change
            # made in Global Defaults while the room was reloading takes effect.
            return

        # Preset None means the user set the temperature by hand: restore it.
        #
        # This reads our own effective_setpoint attribute, NOT the standard
        # `temperature` attribute. In Heat or Cool mode `temperature` is the
        # activation threshold shown on the card, one comfort zone away from the
        # setpoint, so restoring from it moved the room by a comfort zone on
        # every restart and every reload.
        def _restored(attribute: str, low: float, high: float) -> float | None:
            try:
                value = float(last.attributes.get(attribute))
            except (TypeError, ValueError):
                return None
            return value if math.isfinite(value) and low <= value <= high else None

        setpoint = _restored(
            ATTR_EFFECTIVE_SETPOINT, self._minimum_temperature, self._maximum_temperature
        )
        if setpoint is not None:
            self._setpoint = setpoint
        # A range dragged on the card also sets the band width.
        zone = _restored(ATTR_COMFORT_ZONE, 0.05, 10.0)
        if zone is not None:
            self._comfort_zone = zone

    def _adopt_house_mode(self) -> None:
        """Adopt the house/floor selector's current preset, if one is wired up.

        Only used when there is no previous state to restore. Previously the
        selector was tracked for changes but never read at startup, so a room
        stayed on the hardcoded Home default until the selector next moved.
        """
        if not self._house_mode_entity:
            return
        state = self.hass.states.get(self._house_mode_entity)
        if state is None or state.state not in self._attr_preset_modes:
            return
        self._attr_preset_mode = state.state
        if state.state in self._mode_temps:
            self._setpoint = self._mode_temps[state.state]

    async def async_added_to_hass(self) -> None:
        await self._restore_previous_state()
        await self._restore_manual_holds()

        entities_to_track = [self._temp_sensor]
        if self._humidity_sensor:
            entities_to_track.append(self._humidity_sensor)
        if self._house_mode_entity:
            entities_to_track.append(self._house_mode_entity)
        # Controlled devices are watched too, so a manual change is noticed when
        # it happens rather than at the next temperature reading.
        entities_to_track.extend(sorted(self._device_entity_ids))

        self.async_on_remove(
            async_track_state_change_event(
                self.hass, entities_to_track, self._handle_state_change
            )
        )
        # Safety net: confirms manual holds, retries a service call that failed,
        # and keeps the hold countdown current even if no sensor reports.
        self.async_on_remove(
            async_track_time_interval(
                self.hass, self._handle_tick, self._TICK_INTERVAL
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
            "setpoint": self._setpoint,
            "preset": self._attr_preset_mode,
            "point_spacing": self._profile_point_spacing(),
        }

        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_MODE_REASSERTED, self._mode_reasserted)
        )
        if self._schedule is not None:
            self._schedule.target = self
            if self.hass.is_running:
                self.hass.async_create_task(self._schedule.async_evaluate())

        self.hass.async_create_task(self._evaluate_devices())

    # ── Schedules ──────────────────────────────────────────────────────────

    def _own_schedule(self) -> bool:
        return self._schedule is not None and self._schedule.enabled

    @property
    def target_entity_id(self) -> str | None:
        return self.entity_id

    def schedule_presets(self) -> list[str]:
        return [p for p in self._attr_preset_modes if p != PRESET_NONE]

    def schedule_current(self) -> str | None:
        return self._attr_preset_mode if self.hass is not None else None

    async def async_apply_scheduled(self, preset: str) -> None:
        await self._async_apply_preset(preset)

    async def schedule_disabled(self) -> None:
        """Without its own schedule the room follows House / Floor Mode again."""
        if not self._house_mode_entity:
            return
        state = self.hass.states.get(self._house_mode_entity)
        preset = _HOUSE_MODE_TO_PRESET.get(state.state.lower()) if state else None
        if preset and preset in self._enabled_modes:
            await self._async_apply_preset(preset)

    @callback
    def _mode_reasserted(self, entity_id: str) -> None:
        """A schedule set our mode selector to the value it already had."""
        if entity_id != self._house_mode_entity or self._own_schedule():
            return
        state = self.hass.states.get(entity_id)
        preset = _HOUSE_MODE_TO_PRESET.get(state.state.lower()) if state else None
        if preset and preset in self._enabled_modes and preset != self._attr_preset_mode:
            self.hass.async_create_task(self._async_apply_preset(preset))

    def _schedule_entity_id(self) -> str | None:
        """The schedule that decides this room's preset, for the card."""
        if self._own_schedule():
            return self._schedule.sensor_entity_id
        if self._house_mode_entity and self._schedule is not None:
            followed = self._schedule.manager.controller_for_entity(self._house_mode_entity)
            if followed is not None and followed.enabled:
                return followed.sensor_entity_id
        return None

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
            if preset and preset in self._enabled_modes and self._own_schedule():
                # The room's own schedule decides, but Away still applies.
                previous = self._attr_preset_mode
                if preset == MODE_AWAY:
                    self.hass.async_create_task(self._async_apply_preset(preset))
                    self._schedule.note_change(preset, previous)
                elif previous == MODE_AWAY:
                    self.hass.async_create_task(self._return_from_away(preset))
                return
            if preset and preset in self._enabled_modes:
                self._attr_preset_mode = preset
                if preset == MODE_AWAY:
                    self._setpoint = round((self._minimum_temperature + self._maximum_temperature) / 2, 1)
                else:
                    self._setpoint = self._mode_temps.get(preset, self._setpoint)
                self._restore_configured_comfort_zone()
                self.hass.async_create_task(self._evaluate_devices())
                self.async_write_ha_state()

        elif entity_id in self._device_entity_ids:
            # Only on/off or mode changes matter here; climate devices report
            # attribute updates (their own temperature) far more often.
            old_state = event.data.get("old_state")
            if old_state is not None and old_state.state == new_state.state:
                return
            # A switch made by hand counts for the minimum times too: the
            # compressor does not care who turned it on.
            if old_state is not None and _state_is_on(entity_id, old_state.state) != _state_is_on(
                entity_id, new_state.state
            ):
                self._last_switched[entity_id] = dt_util.utcnow()
            self.hass.async_create_task(self._evaluate_devices())

    async def _handle_tick(self, _now=None) -> None:
        await self._evaluate_devices()

    # How often to re-evaluate when nothing else has prompted it.
    _TICK_INTERVAL = timedelta(seconds=30)

    # How long after our last service call to a device we consider subsequent
    # state changes as "ours" and not manual overrides.
    _OWN_CHANGE_WINDOW: float = 5.0  # seconds

    def _entity_unavailable(self, entity_id: str) -> bool:
        """True when we have no trustworthy reading for this entity."""
        state = self.hass.states.get(entity_id)
        return state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN)

    def _device_is_on(self, entity_id: str) -> bool:
        """Read the actual current on/off state of a controlled entity."""
        state = self.hass.states.get(entity_id)
        if state is None:
            return False
        return _state_is_on(entity_id, state.state)

    def _min_time_wait(self, entity_id: str, turn_on: bool) -> float:
        """Seconds before this device may be switched on (or off); 0 if now.

        Only switching the physical device between on and off is limited. A
        climate entity configured as several stages is one device, so its
        strictest stage setting applies; moving it between its own stages (fan
        only to cool, say) is not a switch on or off and is never held.
        """
        minutes = max(
            (
                d.min_off_minutes if turn_on else d.min_on_minutes
                for d in self._devices
                if d.entity_id == entity_id
            ),
            default=0.0,
        )
        since = self._last_switched.get(entity_id)
        if minutes <= 0 or since is None:
            return 0.0
        return max(0.0, minutes * 60 - (dt_util.utcnow() - since).total_seconds())

    def _may_switch(self, entity_id: str, turn_on: bool) -> bool:
        """Whether an automatic switch on / off may happen now; records the wait if not."""
        wait = self._min_time_wait(entity_id, turn_on)
        if wait <= 0:
            return True
        self._min_time_waits[entity_id] = {
            "action": "on" if turn_on else "off",
            "until": dt_util.utcnow() + timedelta(seconds=wait),
        }
        return False

    def _opposite_running(self, device: _Device) -> bool:
        """Whether another device is still heating while this one would cool,
        or the other way round.

        Normally the comfort zone keeps the two apart, but a minimum on time or
        a sudden change of preset can leave one running after the room has
        crossed to needing the other. Starting this one then would only fight
        it; it waits until the other has switched off.
        """
        if device.role not in (ROLE_HEATING, ROLE_COOLING):
            return False
        opposite = ROLE_COOLING if device.role == ROLE_HEATING else ROLE_HEATING
        return any(
            other.is_active and other.role == opposite and other.entity_id != device.entity_id
            for other in self._devices
        )

    def _may_start(self, device: _Device) -> bool:
        return not self._opposite_running(device) and self._may_switch(
            device.entity_id, turn_on=True
        )

    def _note_switch(self, entity_id: str, was_on: bool, now_on: bool) -> None:
        """Remember when we switched a device on or off, for the minimum times."""
        if was_on != now_on:
            self._last_switched[entity_id] = dt_util.utcnow()

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
            #
            # Only sync entities that have actually loaded. This entity is
            # routinely added before the integrations it controls, and a missing
            # entity reads as "off" — so syncing it here would record every
            # running device as inactive, and the moment it appeared we would call
            # that a manual override and suspend control for hours.
            for device in self._devices:
                if self._entity_unavailable(device.entity_id):
                    continue
                device.is_active = self._device_matches_actual(device)
                self._synced_entities.add(device.entity_id)
            # Keep re-syncing until Home Assistant has finished starting; stragglers
            # after that are handled per entity below.
            if not self.hass.is_running:
                return
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

            if self._entity_unavailable(eid):
                # Offline is not the same as switched off. Forget any mismatch in
                # progress and drop the entity from the synced set, so that when it
                # returns we re-read it instead of blaming the user for the outage.
                self._synced_entities.discard(eid)
                self._manual_mismatch_seen.pop(eid, None)
                continue

            if eid not in self._synced_entities:
                # First trustworthy reading — it loaded late, or just came back.
                # Adopt what the hardware says rather than calling it an override.
                for stage in self._devices:
                    if stage.entity_id == eid:
                        stage.is_active = self._device_matches_actual(stage)
                self._synced_entities.add(eid)
                continue

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

    def _trigger_manual_hold(self, entity_id: str, since=None) -> None:
        """Record a manual hold and schedule automatic resume.

        `since` is given when a hold is being restored after a restart, so it
        ends when it originally would have rather than starting over.
        """
        restored = since is not None
        since = since or dt_util.utcnow()
        self._manual_holds[entity_id] = {"since": since, "user_id": None}
        remaining = max(
            1.0,
            (since + timedelta(hours=self._hold_hours) - dt_util.utcnow()).total_seconds(),
        )
        _LOGGER.info(
            "climate_comfort [%s]: manual override %s on %s — "
            "automated control suspended for %.0f more min",
            self._entry.data.get("name"),
            "restored" if restored else "detected",
            entity_id,
            remaining / 60,
        )

        @callback
        def _resume(_now=None) -> None:
            self._hold_timers.pop(entity_id, None)
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

        if previous := self._hold_timers.pop(entity_id, None):
            previous()
        self._hold_timers[entity_id] = async_call_later(self.hass, remaining, _resume)

    async def async_clear_manual_holds(self) -> list[str]:
        """End every hold now and return the entity_ids that were held."""
        cleared = list(self._manual_holds)
        self._manual_holds.clear()
        for cancel in self._hold_timers.values():
            cancel()
        self._hold_timers.clear()
        # Mark as recently touched so _check_manual_changes doesn't immediately
        # re-trigger holds when it sees states that still differ from is_active.
        for entity_id in cleared:
            self._mark_integration_touch(entity_id)
        await self._evaluate_devices()
        # Update the hold indicators even when no evaluation could run.
        self._sync_binary_sensors()
        self.async_write_ha_state()
        return cleared

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
            self._attr_native_current_temperature = None
            self._attr_available = False
            self.hass.async_create_task(self._turn_off_all())
            return

        self._attr_available = True
        try:
            temperature = float(state.state)
            if not math.isfinite(temperature):
                raise ValueError("temperature is not finite")
            self._attr_native_current_temperature = temperature
        except (ValueError, TypeError):
            _LOGGER.warning(
                "climate_comfort [%s]: bad temperature '%s' from %s — "
                "turning off all devices and marking unavailable",
                self._entry.data.get("name"), state.state, self._temp_sensor,
            )
            self._attr_native_current_temperature = None
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
            ATTR_EFFECTIVE_SETPOINT: self._setpoint,
            ATTR_ACTIVE_DEVICES: [d.entity_id for d in self._devices if d.is_active],
            # The schedule sensor that decides this room's preset, for the card.
            "schedule_entity": self._schedule_entity_id(),
        }
        if self._humidity_sensor:
            attrs[ATTR_CURRENT_HUMIDITY] = self._attr_current_humidity

        # Everything the dashboard card needs to draw this room on its own, so
        # it no longer has to be told about each stage sensor by entity id.
        attrs["stages"] = self._stage_attributes(lt, ut, point_spacing)
        if self.hass is not None:
            registry = er.async_get(self.hass)
            for key, domain, suffix in (
                ("aggressiveness_entity", "select", "aggressiveness"),
                ("reset_entity", "button", "reset_manual_control"),
            ):
                entity_id = registry.async_get_entity_id(
                    domain, DOMAIN, f"{self._entry.entry_id}_{suffix}"
                )
                if entity_id:
                    attrs[key] = entity_id

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

        waits = {
            eid: wait
            for eid in self._min_time_waits
            if (wait := self._min_time_wait_attribute(eid)) is not None
        }
        if waits:
            attrs["min_time_waits"] = waits

        return attrs

    def _stage_attributes(self, lt: float, ut: float, point_spacing: float) -> list[dict[str, Any]]:
        """One entry per configured device stage, in configuration order."""
        stages: list[dict[str, Any]] = []
        for device in self._devices:
            if device.role == ROLE_DEHUMIDIFY:
                kind = "humidity"
                threshold: float = device.humidity_threshold
            elif device.role == ROLE_HEATING:
                kind = "heating"
                threshold = round(lt - self._activation_offset_for_device(device, point_spacing), 2)
            else:
                kind = "cooling"
                threshold = round(ut + self._activation_offset_for_device(device, point_spacing), 2)
            stages.append(
                {
                    "id": device.id,
                    "label": device.label,
                    "kind": kind,
                    "threshold": threshold,
                    "active": device.is_active,
                    "manual": device.entity_id in self._manual_holds,
                    # Set while the device is kept as it is by its minimum on /
                    # off time: {"action": "on" | "off", "until": ISO time}.
                    "min_time_wait": self._min_time_wait_attribute(device.entity_id),
                    "entity_id": device.entity_id,
                    "hvac_mode": self._device_target_hvac_mode(device) if device.is_climate else None,
                }
            )
        return stages

    def _min_time_wait_attribute(self, entity_id: str) -> dict[str, str] | None:
        wait = self._min_time_waits.get(entity_id)
        if wait is None or wait["until"] <= dt_util.utcnow():
            return None
        return {"action": wait["action"], "until": wait["until"].isoformat()}

    def manual_control_attributes(self) -> dict[str, Any]:
        """Return concise metadata for the room-level manual-control UI."""
        if not self._manual_holds:
            return {}

        now = dt_util.utcnow()
        labels = {device.entity_id: device.label for device in self._devices}
        holds: list[tuple[str, int]] = []
        for entity_id, hold in self._manual_holds.items():
            remaining_seconds = (hold["since"] + timedelta(hours=self._hold_hours) - now).total_seconds()
            if remaining_seconds > 0:
                holds.append((labels.get(entity_id, entity_id), max(1, int(remaining_seconds / 60))))
        if not holds:
            return {}

        next_remaining = min(minutes for _, minutes in holds)
        return {
            "manual_hold_devices": [label for label, _ in holds],
            "automated_control_resumes_in": f"{next_remaining} min",
            # A real timestamp, for automations and relative-time displays.
            "automated_control_resumes_at": min(
                hold["since"] + timedelta(hours=self._hold_hours)
                for hold in self._manual_holds.values()
            ).isoformat(),
            "manual_control_summary": f"Manual control — resumes in {next_remaining} min",
        }

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
    def native_target_temperature(self) -> float | None:
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
    def native_target_temperature_low(self) -> float | None:
        """Lower comfort boundary — heating activates below this."""
        if self._attr_hvac_mode != HVACMode.HEAT_COOL:
            return None
        lt, _ = self._thresholds()
        return lt

    @property
    def native_target_temperature_high(self) -> float | None:
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

    async def _return_from_away(self, house_preset: str) -> None:
        """House Mode left Away: the room's schedule decides, else House Mode."""
        await self._schedule.async_evaluate(force=True)
        if self._attr_preset_mode == MODE_AWAY:
            await self._async_apply_preset(house_preset)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """A preset chosen by a person, an automation or the card."""
        if preset_mode != PRESET_NONE and preset_mode not in self._attr_preset_modes:
            raise HomeAssistantError(f"Unsupported preset mode: {preset_mode}")
        previous = self._attr_preset_mode
        await self._async_apply_preset(preset_mode)
        if self._own_schedule():
            self._schedule.note_change(preset_mode, previous)

    async def _async_apply_preset(self, preset_mode: str) -> None:
        self._attr_preset_mode = preset_mode
        if preset_mode == MODE_AWAY:
            self._setpoint = round((self._minimum_temperature + self._maximum_temperature) / 2, 1)
            self._restore_configured_comfort_zone()
        elif preset_mode not in (PRESET_NONE,):
            self._setpoint = self._mode_temps.get(preset_mode, self._setpoint)
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
            self._setpoint = round((lt + ut) / 2, 1)
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
                self._setpoint = temp + self._comfort_zone
            elif self._attr_hvac_mode == HVACMode.COOL:
                # User is setting UT directly: new setpoint = UT - comfort_zone
                self._setpoint = temp - self._comfort_zone
            else:
                self._setpoint = temp
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
        sp = self._setpoint
        effective_comfort_zone = self._comfort_zone * self._profile_comfort_multiplier()
        return sp - effective_comfort_zone, sp + effective_comfort_zone

    async def _evaluate_devices(self) -> None:
        """Run the control logic, one evaluation at a time.

        A request that arrives while an evaluation is in flight does not start
        a second one alongside it — two interleaved runs can each decide to
        switch the same device. It is folded into one re-run instead, which
        sees whatever changed in the meantime.
        """
        if self._evaluating:
            self._evaluate_again = True
            return
        self._evaluating = True
        try:
            while True:
                self._evaluate_again = False
                await self._evaluate_once()
                if not self._evaluate_again:
                    break
        finally:
            self._evaluating = False
        # Callers that were folded into this run have already returned, so the
        # result has to be published from here.
        if self.hass is not None and self.entity_id:
            self.async_write_ha_state()

    async def _evaluate_once(self) -> None:
        # Check for manual changes before doing anything else.
        # Compares expected state (is_active) against actual HA state.
        self._check_manual_changes()
        self._min_time_waits = {}

        if self._attr_hvac_mode == HVACMode.OFF:
            # Evaluations now also run on a timer and on device changes, so only
            # devices that are actually on are switched off here. Sending "off"
            # to everything each time would flood a cloud-connected unit.
            await self._turn_off_all(only_if_on=True)
            self._attr_hvac_action = HVACAction.OFF
            return

        current = self._attr_native_current_temperature
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
        any_dehumidifying = False

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
                    if self._may_start(device):
                        await self._activate_device(device)
                elif current >= deactivate_at and device.is_active:
                    if self._may_switch(device.entity_id, turn_on=False):
                        await self._deactivate_device(device)
                if device.is_active:
                    any_heating = True

            elif device.role == ROLE_COOLING and mode_allows_cooling:
                activate_at = ut + self._activation_offset_for_device(device, point_spacing)
                deactivate_at = activate_at - device.deactivate_offset
                should_activate = current >= activate_at or (emergency_cool and device.emergency_enabled)
                if should_activate and not device.is_active:
                    if self._may_start(device):
                        await self._activate_device(device)
                elif current <= deactivate_at and device.is_active:
                    if self._may_switch(device.entity_id, turn_on=False):
                        await self._deactivate_device(device)
                if device.is_active:
                    any_cooling = True

            else:
                # The thermostat's mode no longer allows this role. That was a
                # person's choice, so it takes effect at once.
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

            # Switching the unit on from off, or off altogether, waits for its
            # minimum times. The stages are left as they were meanwhile, so the
            # manual-change check finds nothing to call an override. Switching
            # off because a person changed the thermostat's mode is not held.
            mode_forbids_prev = prev is not None and (
                (prev.role == ROLE_HEATING and not mode_allows_heating)
                or (prev.role == ROLE_COOLING and not mode_allows_cooling)
            )
            if (
                (prev is None) != (winning is None)
                and not mode_forbids_prev
                and not (
                    self._may_start(winning)
                    if winning is not None
                    else self._may_switch(entity_id, turn_on=False)
                )
            ):
                for stage in stages:
                    stage.is_active = stage is prev
                winning = prev

            if winning != prev:
                if winning is None:
                    await self._set_climate_off(entity_id)
                else:
                    await self._activate_device(winning)
                self._active_climate_stage[entity_id] = winning
            elif winning is not None:
                # Same stage still running: follow a setpoint or preset change.
                await self._refresh_target_temperature(winning)

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
                if device.is_active and (
                    self._same_climate_has_active_temperature_stage(device)
                    or self._may_switch(device.entity_id, turn_on=False)
                ):
                    await self._deactivate_or_release_device(device)
                if device.is_active:
                    any_dehumidifying = True
                continue

            activate_at = device.humidity_threshold
            deactivate_at = activate_at - device.humidity_hysteresis
            if current_humidity >= activate_at and not device.is_active:
                # Joining a unit already running in another mode is not a
                # switch on, so only an idle unit waits.
                if self._device_is_on(device.entity_id) or self._may_switch(
                    device.entity_id, turn_on=True
                ):
                    await self._activate_device(device)
            elif current_humidity <= deactivate_at and device.is_active:
                if self._same_climate_has_active_temperature_stage(device) or self._may_switch(
                    device.entity_id, turn_on=False
                ):
                    await self._deactivate_or_release_device(device)

            if device.is_active:
                any_dehumidifying = True

        # ── Update HVAC action ────────────────────────────────────────────
        if any_heating:
            self._attr_hvac_action = HVACAction.HEATING
        elif any_cooling:
            self._attr_hvac_action = HVACAction.COOLING
        elif any_dehumidifying:
            self._attr_hvac_action = HVACAction.DRYING
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
        was_on = self._device_is_on(device.entity_id)
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
                target = self._device_target_temperature(device)
                if target is not None:
                    await self._send_target_temperature(device, target)
                await self._apply_secondary_settings(device)
            else:
                await self.hass.services.async_call(
                    "homeassistant", "turn_on",
                    {"entity_id": device.entity_id},
                    blocking=True,
                )
            self._note_switch(device.entity_id, was_on, True)
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
                was_on = self._device_is_on(device.entity_id)
                await self.hass.services.async_call(
                    "homeassistant", "turn_off",
                    {"entity_id": device.entity_id},
                    blocking=True,
                )
                self._note_switch(device.entity_id, was_on, False)
            device.is_active = False  # Commit only after success
        except Exception as err:
            _LOGGER.error(
                "climate_comfort: failed to deactivate '%s' (%s): %s",
                device.label, device.entity_id, err,
            )
            # is_active stays True — device may still be on, retry next cycle

    def _device_target_temperature(self, device: _Device) -> float | None:
        """Target to set on a climate device: room setpoint pushed past by its overshoot."""
        if (
            not device.is_climate
            or device.role == ROLE_DEHUMIDIFY
            or device.target_temp_offset is None
        ):
            return None
        magnitude = abs(device.target_temp_offset)
        if device.role == ROLE_HEATING:
            return round(self._setpoint + magnitude, 1)
        return round(self._setpoint - magnitude, 1)

    async def _send_target_temperature(self, device: _Device, target: float) -> None:
        self._mark_integration_touch(device.entity_id)
        await self.hass.services.async_call(
            "climate", "set_temperature",
            {"entity_id": device.entity_id, "temperature": target},
            blocking=True,
        )
        self._last_target_sent[device.entity_id] = target

    async def _refresh_target_temperature(self, device: _Device) -> None:
        """Push a changed setpoint to a stage that is already running.

        The target used to be sent only when a stage switched on, so changing
        the room temperature while the air conditioner was already cooling left
        the unit aiming at the old value until it next cycled.
        """
        target = self._device_target_temperature(device)
        if target is None or self._last_target_sent.get(device.entity_id) == target:
            return
        try:
            await self._send_target_temperature(device, target)
        except Exception as err:
            # Remember the attempt so a device that rejects the value is not
            # retried, and logged, on every evaluation until the target changes.
            self._last_target_sent[device.entity_id] = target
            _LOGGER.warning(
                "climate_comfort: '%s' (%s) is active, but updating its target "
                "to %.1f failed: %s",
                device.label, device.entity_id, target, err,
            )

    async def _set_climate_off(self, entity_id: str) -> None:
        self._last_target_sent.pop(entity_id, None)
        self._mark_integration_touch(entity_id)
        was_on = self._device_is_on(entity_id)
        await self.hass.services.async_call(
            "climate", "set_hvac_mode",
            {"entity_id": entity_id, "hvac_mode": "off"},
            blocking=True,
        )
        self._note_switch(entity_id, was_on, False)

    async def _turn_off_all(self, only_if_on: bool = False) -> None:
        turned_off: set[str] = set()
        for device in self._devices:
            if device.entity_id in turned_off:
                device.is_active = False
                continue
            if only_if_on and not self._device_is_on(device.entity_id):
                device.is_active = False
                continue
            if device.is_climate:
                await self._set_climate_off(device.entity_id)
            else:
                self._mark_integration_touch(device.entity_id)
                was_on = self._device_is_on(device.entity_id)
                await self.hass.services.async_call(
                    "homeassistant", "turn_off",
                    {"entity_id": device.entity_id},
                    blocking=True,
                )
                self._note_switch(device.entity_id, was_on, False)
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
                was_on = self._device_is_on(device.entity_id)
                await self.hass.services.async_call(
                    "homeassistant", "turn_off",
                    {"entity_id": device.entity_id},
                    blocking=True,
                )
                self._note_switch(device.entity_id, was_on, False)
            turned_off.add(device.entity_id)
            device.is_active = False
        self._sync_binary_sensors()

    def _sync_binary_sensors(self) -> None:
        """Write device states and thresholds to hass.data, then refresh all sensors."""
        lt, ut = self._thresholds()
        entry_data = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {})
        entry_data["device_states"] = {
            f"{self._entry.entry_id}_device_{device.id}": device.is_active
            for device in self._devices
        }
        entry_data["thresholds"] = {
            "lt": round(lt, 2),
            "ut": round(ut, 2),
            "setpoint": self._setpoint,
            "preset": self._attr_preset_mode,
            "point_spacing": self._profile_point_spacing(),
        }
        # Share manual holds and hold duration so binary sensors can show override status
        entry_data["manual_holds"] = dict(self._manual_holds)
        entry_data["hold_hours"] = self._hold_hours

        for sensor in entry_data.get("device_sensors", []):
            if sensor.hass is None:
                continue
            sensor.refresh()
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
        for entity_key in ("manual_control_sensor", "reset_manual_control_button"):
            entity = entry_data.get(entity_key)
            if entity and entity.hass is not None:
                entity.async_write_ha_state()
