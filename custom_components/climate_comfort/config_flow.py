from __future__ import annotations

from uuid import uuid4

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.util import slugify

from . import schedule as sched
from .const import (
    CONF_SCHEDULE_CALENDAR_ENTITY,
    CONF_SCHEDULE_DAY_START,
    CONF_SCHEDULE_WORKDAY_ENTITY,
    DATA_FLOOR_SCHEDULES,
    DATA_HOUSE_SCHEDULE,
    DATA_SCHEDULE,
    DEFAULT_SCHEDULE_DAY_START,
    CONF_COMFORT_ZONE,
    CONF_DEFAULT_PROFILE,
    CONF_DEVICE_ACTIVATE_OFFSET,
    CONF_DEVICE_ACTIVATION_POINT,
    CONF_DEVICE_DEACTIVATE_OFFSET,
    CONF_DEVICE_DEHUMIDIFY_ONLY_WHEN_IDLE,
    CONF_DEVICE_EMERGENCY_ENABLED,
    CONF_DEVICE_ENTITY,
    CONF_DEVICE_HUMIDITY_HYSTERESIS,
    CONF_DEVICE_MIN_OFF_MINUTES,
    CONF_DEVICE_MIN_ON_MINUTES,
    CONF_DEVICE_HUMIDITY_THRESHOLD,
    CONF_DEVICE_FAN_MODE,
    CONF_DEVICE_HVAC_MODE_ON,
    CONF_DEVICE_ID,
    CONF_DEVICE_SWING_HORIZONTAL_MODE,
    CONF_DEVICE_SWING_MODE,
    CONF_DEVICE_LABEL,
    CONF_DEVICE_ROLE,
    CONF_DEVICE_TARGET_TEMP_OFFSET,
    CONF_DEVICES,
    CONF_ENTRY_TYPE,
    CONF_FLOOR_NAMES,
    CONF_HOUSE_MODE_ENTITY,
    CONF_HUMIDITY_SENSOR,
    CONF_MANUAL_HOLD_HOURS,
    CONF_MANUAL_HOLD_CONFIRM_SECONDS,
    CONF_MAXIMUM_TEMPERATURE,
    CONF_MINIMUM_TEMPERATURE,
    CONF_MODE_AWAY,
    CONF_MODE_AWAY_PROFILE,
    CONF_MODE_ACTIVITY,
    CONF_MODE_ACTIVITY_PROFILE,
    CONF_MODE_ACTIVITY_ENABLED,
    CONF_MODE_BOOST,
    CONF_MODE_BOOST_PROFILE,
    CONF_MODE_BOOST_ENABLED,
    CONF_MODE_COOLDOWN,
    CONF_MODE_COOLDOWN_PROFILE,
    CONF_MODE_COOLDOWN_ENABLED,
    CONF_MODE_HOME,
    CONF_MODE_HOME_PROFILE,
    CONF_MODE_SLEEP,
    CONF_MODE_SLEEP_PROFILE,
    CONF_MODE_SLEEP_ENABLED,
    CONF_MODE_WARMUP,
    CONF_MODE_WARMUP_PROFILE,
    CONF_MODE_WARMUP_ENABLED,
    CONF_PROFILE_AGGRESSIVE_COMFORT_MULTIPLIER,
    CONF_PROFILE_AGGRESSIVE_POINT_SPACING,
    CONF_PROFILE_BALANCED_COMFORT_MULTIPLIER,
    CONF_PROFILE_BALANCED_POINT_SPACING,
    CONF_PROFILE_RELAXED_COMFORT_MULTIPLIER,
    CONF_PROFILE_RELAXED_POINT_SPACING,
    CONF_PROFILE_RESPONSIVE_COMFORT_MULTIPLIER,
    CONF_PROFILE_RESPONSIVE_POINT_SPACING,
    CONF_TEMPERATURE_SENSOR,
    CONF_USE_GLOBAL_PRESETS,
    DEFAULT_ACTIVATE_OFFSET,
    DEFAULT_COMFORT_ZONE,
    DEFAULT_DEACTIVATE_OFFSET,
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
    DEFAULT_MODE_ACTIVITY_ENABLED,
    DEFAULT_MODE_BOOST_ENABLED,
    DEFAULT_MODE_COOLDOWN_ENABLED,
    DEFAULT_MODE_SLEEP,
    DEFAULT_MODE_SLEEP_ENABLED,
    DEFAULT_MODE_WARMUP,
    DEFAULT_MODE_WARMUP_ENABLED,
    DEFAULT_PROFILE,
    DEFAULT_PROFILE_AGGRESSIVE_COMFORT_MULTIPLIER,
    DEFAULT_PROFILE_AGGRESSIVE_POINT_SPACING,
    DEFAULT_PROFILE_BALANCED_COMFORT_MULTIPLIER,
    DEFAULT_PROFILE_BALANCED_POINT_SPACING,
    DEFAULT_PROFILE_RELAXED_COMFORT_MULTIPLIER,
    DEFAULT_PROFILE_RELAXED_POINT_SPACING,
    DEFAULT_PROFILE_RESPONSIVE_COMFORT_MULTIPLIER,
    DEFAULT_PROFILE_RESPONSIVE_POINT_SPACING,
    DEFAULT_MANUAL_HOLD_HOURS,
    DEFAULT_MANUAL_HOLD_CONFIRM_SECONDS,
    DEFAULT_HUMIDITY_HYSTERESIS,
    DEFAULT_MIN_OFF_MINUTES,
    DEFAULT_MIN_ON_MINUTES,
    DEFAULT_HUMIDITY_THRESHOLD,
    DOMAIN,
    ENTRY_TYPE_GLOBAL,
    ENTRY_TYPE_ROOM,
    ROLE_COOLING,
    ROLE_DEHUMIDIFY,
    ROLE_HEATING,
    PROFILE_OPTIONS,
    SECONDARY_UNSET,
    SUBENTRY_TYPE_DEVICE,
)

# ── Selector helpers ────────────────────────────────────────────────────────


# Labels come from the "selector" section of the translation files.
_ROLE_SELECTOR = selector.SelectSelector(
    selector.SelectSelectorConfig(
        options=[ROLE_HEATING, ROLE_COOLING, ROLE_DEHUMIDIFY],
        translation_key="role",
    )
)

# Fallback list if the selected entity has no hvac_modes attribute yet
_FALLBACK_CLIMATE_MODES = ["heat", "cool", "heat_cool", "auto", "fan_only", "dry"]


def _num(min_v, max_v, step=0.5, unit="°C", mode=selector.NumberSelectorMode.SLIDER):
    return selector.NumberSelector(
        selector.NumberSelectorConfig(min=min_v, max=max_v, step=step, unit_of_measurement=unit, mode=mode)
    )


def _ha_floor_options(hass) -> list[selector.SelectOptionDict]:
    """
    Read HA's floor registry to pre-populate the floor names selector.
    Returns an empty list (gracefully) on older HA versions without floor support.
    """
    try:
        from homeassistant.helpers import floor_registry as fr
        registry = fr.async_get(hass)
        return [
            selector.SelectOptionDict(value=floor.name, label=floor.name)
            for floor in registry.async_list_floors()
        ]
    except Exception:
        return []


def _house_mode_entity_field(hass) -> selector.SelectSelector | selector.EntitySelector:
    """
    Return the right selector for the 'house / floor mode entity' field.

    When a Global Defaults entry exists, show only the House Mode and Floor Mode
    entities created by this integration (filtered by entity registry).
    Falls back to a generic select-entity picker if none are configured yet.
    """
    options = _mode_entity_options(hass)
    if options:
        return selector.SelectSelector(
            selector.SelectSelectorConfig(options=options, custom_value=False)
        )
    # No global entry or no select entities yet — generic fallback
    return selector.EntitySelector(
        selector.EntitySelectorConfig(domain=["input_select", "select"])
    )


def _mode_entity_options(hass) -> list[selector.SelectOptionDict]:
    """
    Return only the House Mode and Floor Mode select entities created by the
    Global Defaults entry of this integration.

    This restricts the 'house / floor mode entity' picker to entities that
    actually support the cascade behaviour, rather than showing every select
    entity in the system.
    """
    try:
        from homeassistant.helpers import entity_registry as er
        registry = er.async_get(hass)
        options: list[selector.SelectOptionDict] = []
        for entry in hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_GLOBAL:
                for entity_entry in er.async_entries_for_config_entry(
                    registry, entry.entry_id
                ):
                    if entity_entry.domain == "select" and not entity_entry.disabled_by:
                        label = (
                            entity_entry.name
                            or entity_entry.original_name
                            or entity_entry.entity_id
                        )
                        options.append(
                            selector.SelectOptionDict(
                                value=entity_entry.entity_id,
                                label=label,
                            )
                        )
        return options
    except Exception:
        return []


def _profile_selector(default: str = DEFAULT_PROFILE) -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=list(PROFILE_OPTIONS),
            translation_key="profile",
            custom_value=False,
        )
    )


def _profile_fields(cfg: dict | None = None) -> dict:
    cfg = cfg or {}
    return {
        vol.Required(CONF_DEFAULT_PROFILE, default=cfg.get(CONF_DEFAULT_PROFILE, DEFAULT_PROFILE)): _profile_selector(),
        vol.Required(CONF_PROFILE_RELAXED_COMFORT_MULTIPLIER, default=float(cfg.get(CONF_PROFILE_RELAXED_COMFORT_MULTIPLIER, DEFAULT_PROFILE_RELAXED_COMFORT_MULTIPLIER))): _num(0.1, 3.0, step=0.1, unit="×", mode=selector.NumberSelectorMode.BOX),
        vol.Required(CONF_PROFILE_RELAXED_POINT_SPACING, default=float(cfg.get(CONF_PROFILE_RELAXED_POINT_SPACING, DEFAULT_PROFILE_RELAXED_POINT_SPACING))): _num(0.1, 2.0, step=0.1, unit="°C", mode=selector.NumberSelectorMode.BOX),
        vol.Required(CONF_PROFILE_BALANCED_COMFORT_MULTIPLIER, default=float(cfg.get(CONF_PROFILE_BALANCED_COMFORT_MULTIPLIER, DEFAULT_PROFILE_BALANCED_COMFORT_MULTIPLIER))): _num(0.1, 3.0, step=0.1, unit="×", mode=selector.NumberSelectorMode.BOX),
        vol.Required(CONF_PROFILE_BALANCED_POINT_SPACING, default=float(cfg.get(CONF_PROFILE_BALANCED_POINT_SPACING, DEFAULT_PROFILE_BALANCED_POINT_SPACING))): _num(0.1, 2.0, step=0.1, unit="°C", mode=selector.NumberSelectorMode.BOX),
        vol.Required(CONF_PROFILE_RESPONSIVE_COMFORT_MULTIPLIER, default=float(cfg.get(CONF_PROFILE_RESPONSIVE_COMFORT_MULTIPLIER, DEFAULT_PROFILE_RESPONSIVE_COMFORT_MULTIPLIER))): _num(0.1, 3.0, step=0.1, unit="×", mode=selector.NumberSelectorMode.BOX),
        vol.Required(CONF_PROFILE_RESPONSIVE_POINT_SPACING, default=float(cfg.get(CONF_PROFILE_RESPONSIVE_POINT_SPACING, DEFAULT_PROFILE_RESPONSIVE_POINT_SPACING))): _num(0.1, 2.0, step=0.1, unit="°C", mode=selector.NumberSelectorMode.BOX),
        vol.Required(CONF_PROFILE_AGGRESSIVE_COMFORT_MULTIPLIER, default=float(cfg.get(CONF_PROFILE_AGGRESSIVE_COMFORT_MULTIPLIER, DEFAULT_PROFILE_AGGRESSIVE_COMFORT_MULTIPLIER))): _num(0.1, 3.0, step=0.1, unit="×", mode=selector.NumberSelectorMode.BOX),
        vol.Required(CONF_PROFILE_AGGRESSIVE_POINT_SPACING, default=float(cfg.get(CONF_PROFILE_AGGRESSIVE_POINT_SPACING, DEFAULT_PROFILE_AGGRESSIVE_POINT_SPACING))): _num(0.1, 2.0, step=0.1, unit="°C", mode=selector.NumberSelectorMode.BOX),
    }


_PROFILE_CONFIG_FIELDS = {
    "relaxed": (
        CONF_PROFILE_RELAXED_COMFORT_MULTIPLIER,
        CONF_PROFILE_RELAXED_POINT_SPACING,
        DEFAULT_PROFILE_RELAXED_COMFORT_MULTIPLIER,
        DEFAULT_PROFILE_RELAXED_POINT_SPACING,
    ),
    "balanced": (
        CONF_PROFILE_BALANCED_COMFORT_MULTIPLIER,
        CONF_PROFILE_BALANCED_POINT_SPACING,
        DEFAULT_PROFILE_BALANCED_COMFORT_MULTIPLIER,
        DEFAULT_PROFILE_BALANCED_POINT_SPACING,
    ),
    "responsive": (
        CONF_PROFILE_RESPONSIVE_COMFORT_MULTIPLIER,
        CONF_PROFILE_RESPONSIVE_POINT_SPACING,
        DEFAULT_PROFILE_RESPONSIVE_COMFORT_MULTIPLIER,
        DEFAULT_PROFILE_RESPONSIVE_POINT_SPACING,
    ),
    "aggressive": (
        CONF_PROFILE_AGGRESSIVE_COMFORT_MULTIPLIER,
        CONF_PROFILE_AGGRESSIVE_POINT_SPACING,
        DEFAULT_PROFILE_AGGRESSIVE_COMFORT_MULTIPLIER,
        DEFAULT_PROFILE_AGGRESSIVE_POINT_SPACING,
    ),
}


def _profile_default_field(cfg: dict | None = None) -> dict:
    cfg = cfg or {}
    return {
        vol.Required(CONF_DEFAULT_PROFILE, default=cfg.get(CONF_DEFAULT_PROFILE, DEFAULT_PROFILE)): _profile_selector(),
    }


def _single_profile_fields(profile: str, cfg: dict | None = None) -> dict:
    cfg = cfg or {}
    comfort_key, spacing_key, comfort_default, spacing_default = _PROFILE_CONFIG_FIELDS[profile]
    return {
        vol.Required(comfort_key, default=float(cfg.get(comfort_key, comfort_default))): _num(0.1, 3.0, step=0.1, unit="×", mode=selector.NumberSelectorMode.BOX),
        vol.Required(spacing_key, default=float(cfg.get(spacing_key, spacing_default))): _num(0.1, 2.0, step=0.1, unit="°C", mode=selector.NumberSelectorMode.BOX),
    }


def _mode_schema(cfg: dict | None = None) -> vol.Schema:
    cfg = cfg or {}
    return vol.Schema({
        vol.Required(CONF_MODE_AWAY_PROFILE, default=cfg.get(CONF_MODE_AWAY_PROFILE, DEFAULT_MODE_PROFILE_AWAY)): _profile_selector(),
        vol.Required(CONF_MODE_SLEEP, default=float(cfg.get(CONF_MODE_SLEEP, DEFAULT_MODE_SLEEP))): _num(5, 30, step=0.1),
        vol.Required(CONF_MODE_SLEEP_PROFILE, default=cfg.get(CONF_MODE_SLEEP_PROFILE, DEFAULT_MODE_PROFILE_SLEEP)): _profile_selector(),
        vol.Required(CONF_MODE_SLEEP_ENABLED, default=bool(cfg.get(CONF_MODE_SLEEP_ENABLED, DEFAULT_MODE_SLEEP_ENABLED))): selector.BooleanSelector(),
        vol.Required(CONF_MODE_HOME, default=float(cfg.get(CONF_MODE_HOME, DEFAULT_MODE_HOME))): _num(5, 30, step=0.1),
        vol.Required(CONF_MODE_HOME_PROFILE, default=cfg.get(CONF_MODE_HOME_PROFILE, DEFAULT_MODE_PROFILE_HOME)): _profile_selector(),
        vol.Required(CONF_MODE_WARMUP, default=float(cfg.get(CONF_MODE_WARMUP, DEFAULT_MODE_WARMUP))): _num(5, 30, step=0.1),
        vol.Required(CONF_MODE_WARMUP_PROFILE, default=cfg.get(CONF_MODE_WARMUP_PROFILE, DEFAULT_MODE_PROFILE_WARMUP)): _profile_selector(),
        vol.Required(CONF_MODE_WARMUP_ENABLED, default=bool(cfg.get(CONF_MODE_WARMUP_ENABLED, DEFAULT_MODE_WARMUP_ENABLED))): selector.BooleanSelector(),
        vol.Required(CONF_MODE_COOLDOWN, default=float(cfg.get(CONF_MODE_COOLDOWN, DEFAULT_MODE_COOLDOWN))): _num(5, 30, step=0.1),
        vol.Required(CONF_MODE_COOLDOWN_PROFILE, default=cfg.get(CONF_MODE_COOLDOWN_PROFILE, DEFAULT_MODE_PROFILE_COOLDOWN)): _profile_selector(),
        vol.Required(CONF_MODE_COOLDOWN_ENABLED, default=bool(cfg.get(CONF_MODE_COOLDOWN_ENABLED, DEFAULT_MODE_COOLDOWN_ENABLED))): selector.BooleanSelector(),
        vol.Required(CONF_MODE_ACTIVITY, default=float(cfg.get(CONF_MODE_ACTIVITY, DEFAULT_MODE_ACTIVITY))): _num(5, 30, step=0.1),
        vol.Required(CONF_MODE_ACTIVITY_PROFILE, default=cfg.get(CONF_MODE_ACTIVITY_PROFILE, DEFAULT_MODE_PROFILE_ACTIVITY)): _profile_selector(),
        vol.Required(CONF_MODE_ACTIVITY_ENABLED, default=bool(cfg.get(CONF_MODE_ACTIVITY_ENABLED, DEFAULT_MODE_ACTIVITY_ENABLED))): selector.BooleanSelector(),
        vol.Required(CONF_MODE_BOOST, default=float(cfg.get(CONF_MODE_BOOST, DEFAULT_MODE_BOOST))): _num(5, 30, step=0.1),
        vol.Required(CONF_MODE_BOOST_PROFILE, default=cfg.get(CONF_MODE_BOOST_PROFILE, DEFAULT_MODE_PROFILE_BOOST)): _profile_selector(),
        vol.Required(CONF_MODE_BOOST_ENABLED, default=bool(cfg.get(CONF_MODE_BOOST_ENABLED, DEFAULT_MODE_BOOST_ENABLED))): selector.BooleanSelector(),
    })


def _activation_point_selector(role: str, default: int = 0) -> selector.SelectSelector:
    choices = range(-20, 1) if role == ROLE_HEATING else range(0, 21)
    if default not in choices:
        default = 0
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[selector.SelectOptionDict(value=str(p), label=f"{p:+d}" if p else "0") for p in choices],
            custom_value=False,
        )
    )


def _climate_modes_for_entity(hass, entity_id: str) -> list[selector.SelectOptionDict]:
    """
    Return the actual hvac_modes from the climate entity's state attributes.
    Falls back to a sensible hard-coded list if the entity isn't loaded yet.
    """
    if entity_id:
        state = hass.states.get(entity_id)
        if state:
            modes = [
                m for m in state.attributes.get("hvac_modes", [])
                if m != "off"
            ]
            if modes:
                return [selector.SelectOptionDict(value=m, label=m) for m in modes]
    return [selector.SelectOptionDict(value=m, label=m) for m in _FALLBACK_CLIMATE_MODES]


def _secondary_options_for_entity(
    hass, entity_id: str, attribute: str
) -> list[selector.SelectOptionDict] | None:
    """
    Options for an optional secondary climate attribute (fan_modes / swing_modes),
    read from the target entity's own state attributes.

    Returns None when the entity does not advertise the attribute at all — the
    caller then omits the field entirely. There is no point offering a fan speed
    on a device that has no fan, and no fallback list either: unlike hvac_modes,
    guessing here would offer values the device is certain to reject.

    The first option is a "leave unchanged" sentinel so a device that CAN take a
    fan speed can still be left unmanaged. Without it, adding this feature would
    silently start forcing a fan speed on every activation.
    """
    if not entity_id:
        return None
    state = hass.states.get(entity_id)
    if not state:
        return None
    values = [v for v in (state.attributes.get(attribute) or []) if v]
    if not values:
        return None
    return [
        # Listed alongside the device's own raw values, so this one label
        # cannot come from a translation key.
        selector.SelectOptionDict(value=SECONDARY_UNSET, label="Leave unchanged"),
        *[selector.SelectOptionDict(value=v, label=v) for v in values],
    ]


# ── Config flow ─────────────────────────────────────────────────────────────

class ClimateComfortConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    # Version 2 stores each controlled device as a config subentry of its room
    # instead of a list inside the room's options. See async_migrate_entry.
    VERSION = 2

    def __init__(self) -> None:
        self._data: dict = {}

    @classmethod
    @callback
    def async_get_supported_subentry_types(cls, config_entry):
        """Rooms hold their controlled devices as subentries; Global Defaults has none."""
        if config_entry.data.get(CONF_ENTRY_TYPE, ENTRY_TYPE_ROOM) != ENTRY_TYPE_ROOM:
            return {}
        return {SUBENTRY_TYPE_DEVICE: DeviceSubentryFlow}

    async def async_step_user(self, user_input=None):
        return self.async_show_menu(
            step_id="user",
            menu_options=["room", "global_defaults"],
        )

    # ── Room setup path ──────────────────────────────────────────────────────

    async def async_step_room(self, user_input=None):
        g = self._global_config()
        if not g:
            return self.async_abort(reason="global_defaults_required")

        if user_input is not None:
            # Prevent two rooms with the same name being created accidentally
            room_slug = slugify(user_input[CONF_NAME])
            await self.async_set_unique_id(f"{DOMAIN}_room_{room_slug}")
            self._abort_if_unique_id_configured()
            if self._room_name_exists(user_input[CONF_NAME]):
                return self.async_abort(reason="already_configured")

            self._data.update(user_input)
            self._data[CONF_ENTRY_TYPE] = ENTRY_TYPE_ROOM
            self._data[CONF_USE_GLOBAL_PRESETS] = True
            for key in (
                CONF_MODE_AWAY, CONF_MODE_AWAY_PROFILE,
                CONF_MODE_SLEEP, CONF_MODE_SLEEP_PROFILE, CONF_MODE_SLEEP_ENABLED,
                CONF_MODE_HOME, CONF_MODE_HOME_PROFILE,
                CONF_MODE_WARMUP, CONF_MODE_WARMUP_PROFILE, CONF_MODE_WARMUP_ENABLED,
                CONF_MODE_COOLDOWN, CONF_MODE_COOLDOWN_PROFILE, CONF_MODE_COOLDOWN_ENABLED,
                CONF_MODE_ACTIVITY, CONF_MODE_ACTIVITY_PROFILE, CONF_MODE_ACTIVITY_ENABLED,
                CONF_MODE_BOOST, CONF_MODE_BOOST_PROFILE, CONF_MODE_BOOST_ENABLED,
                CONF_MINIMUM_TEMPERATURE, CONF_MAXIMUM_TEMPERATURE,
                CONF_DEFAULT_PROFILE,
                CONF_PROFILE_RELAXED_COMFORT_MULTIPLIER,
                CONF_PROFILE_RELAXED_POINT_SPACING,
                CONF_PROFILE_BALANCED_COMFORT_MULTIPLIER,
                CONF_PROFILE_BALANCED_POINT_SPACING,
                CONF_PROFILE_RESPONSIVE_COMFORT_MULTIPLIER,
                CONF_PROFILE_RESPONSIVE_POINT_SPACING,
                CONF_PROFILE_AGGRESSIVE_COMFORT_MULTIPLIER,
                CONF_PROFILE_AGGRESSIVE_POINT_SPACING,
            ):
                if key in g:
                    self._data[key] = g[key]
            return self.async_create_entry(title=self._data[CONF_NAME], data=self._data)

        schema_fields: dict = {
            vol.Required(CONF_NAME): str,
            vol.Required(CONF_TEMPERATURE_SENSOR): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
            ),
            vol.Optional(CONF_HUMIDITY_SENSOR): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="humidity")
            ),
            vol.Required(CONF_COMFORT_ZONE, default=float(g.get(CONF_COMFORT_ZONE, DEFAULT_COMFORT_ZONE))): _num(0.1, 5.0, step=0.1),
            vol.Optional(CONF_HOUSE_MODE_ENTITY): _house_mode_entity_field(self.hass),
            vol.Required(
                CONF_MANUAL_HOLD_HOURS,
                default=float(g.get(CONF_MANUAL_HOLD_HOURS, DEFAULT_MANUAL_HOLD_HOURS)),
            ): _num(0, 24, step=0.5, unit="h", mode=selector.NumberSelectorMode.SLIDER),
        }

        return self.async_show_form(
            step_id="room",
            data_schema=vol.Schema(schema_fields),
        )

    # ── Global defaults path ─────────────────────────────────────────────────

    async def async_step_global_defaults(self, user_input=None):
        # Belt-and-braces: unique_id check AND manual entry scan
        await self.async_set_unique_id(f"{DOMAIN}_global_defaults")
        self._abort_if_unique_id_configured()

        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_GLOBAL:
                return self.async_abort(reason="global_already_configured")

        if user_input is not None:
            data = dict(user_input)
            data[CONF_ENTRY_TYPE] = ENTRY_TYPE_GLOBAL
            return self.async_create_entry(title="Global Defaults", data=data)

        return self.async_show_form(
            step_id="global_defaults",
            data_schema=vol.Schema({
                vol.Required(CONF_COMFORT_ZONE, default=DEFAULT_COMFORT_ZONE): _num(0.1, 5.0, step=0.1),
                vol.Required(CONF_MINIMUM_TEMPERATURE, default=DEFAULT_MIN_TEMP): _num(0.0, 20.0, step=0.1, mode=selector.NumberSelectorMode.BOX),
                vol.Required(CONF_MAXIMUM_TEMPERATURE, default=DEFAULT_MAX_TEMP): _num(20.0, 45.0, step=0.1, mode=selector.NumberSelectorMode.BOX),
                **_profile_fields(),
                **_mode_schema().schema,
                vol.Optional(CONF_FLOOR_NAMES, default=[]): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=_ha_floor_options(self.hass),
                        custom_value=True,
                        multiple=True,
                    )
                ),
            }),
        )

    def _global_config(self) -> dict:
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_GLOBAL:
                return entry.data
        return {}

    def _room_name_exists(self, name: str) -> bool:
        """Return True if an existing room entry already uses this name."""
        normalized = slugify(name)
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ROOM:
                continue
            existing_name = entry.data.get(CONF_NAME, entry.title)
            if slugify(existing_name) == normalized:
                return True
        return False

    @staticmethod
    def async_get_options_flow(config_entry):
        return ClimateComfortOptionsFlow(config_entry)


# ── Options flow ─────────────────────────────────────────────────────────────

class ClimateComfortOptionsFlow(config_entries.OptionsFlow):
    """
    Room settings and Global Defaults editing.

    Controlled devices are no longer managed here: each is a subentry of its
    room, added, reconfigured and deleted from the integration page.
    """

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    def _global_config(self) -> dict:
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_GLOBAL:
                return entry.data
        return {}

    # ── Main menu ────────────────────────────────────────────────────────────

    async def async_step_init(self, user_input=None):
        # Global Defaults entries have no devices — show a smaller settings menu.
        if self._config_entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_GLOBAL:
            return await self.async_step_edit_global_defaults()

        # ── Room menu ───────────────────────────────────────────────────────
        return self.async_show_menu(
            step_id="init",
            menu_options=["edit_settings", "edit_room_aggressiveness", "edit_room_schedule", "finish"],
        )

    # ── Global defaults edit (shown instead of the room menu) ────────────────
    # ── Global defaults edit (split into smaller pages) ─────────────────────
    async def async_step_edit_global_defaults(self, user_input=None):
        """Menu for editing the Global Defaults entry in smaller chunks."""
        return self.async_show_menu(
            step_id="edit_global_defaults",
            menu_options=[
                "edit_global_general",
                "edit_global_modes",
                "edit_global_profiles",
                "edit_global_floors",
                "edit_global_schedules",
                "finish",
            ],
        )

    # ── Schedules ────────────────────────────────────────────────────────────

    def _entry_data(self) -> dict:
        return self.hass.data.get(DOMAIN, {}).get(self._config_entry.entry_id, {})

    async def _schedule_form(self, step_id, controller, user_input, done):
        """Edit one schedule as text, and switch it on or off.

        Schedules are kept in storage, not in the entry, so saving one here
        does not reload anything.
        """
        if controller is None:
            return self.async_abort(reason="schedule_not_loaded")
        errors: dict[str, str] = {}
        placeholders = {
            "name": controller.name,
            "presets": ", ".join(controller.valid_presets()),
            "error": "",
        }
        text = sched.to_text(controller.profiles)
        enabled = controller.enabled
        if user_input is not None:
            text = user_input.get("schedule", "")
            enabled = bool(user_input.get("enabled"))
            try:
                profiles = sched.parse_text(text)
                sched.validate(profiles, controller.valid_presets())
            except sched.ScheduleError as err:
                errors["schedule"] = "invalid_schedule"
                placeholders["error"] = str(err)
            else:
                await controller.async_set_profiles(profiles)
                if enabled != controller.enabled:
                    await controller.async_set_enabled(enabled)
                return await done()
        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema({
                vol.Required("enabled", default=enabled): selector.BooleanSelector(),
                vol.Required("schedule", default=text): selector.TextSelector(
                    selector.TextSelectorConfig(multiline=True)
                ),
            }),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_edit_room_schedule(self, user_input=None):
        return await self._schedule_form(
            "edit_room_schedule", self._entry_data().get(DATA_SCHEDULE),
            user_input, self.async_step_init,
        )

    async def async_step_edit_global_schedules(self, user_input=None):
        options = ["edit_schedule_sources", "edit_house_schedule"]
        if self._entry_data().get(DATA_FLOOR_SCHEDULES):
            options.append("edit_floor_schedule")
        options.append("edit_global_defaults")
        return self.async_show_menu(step_id="edit_global_schedules", menu_options=options)

    async def async_step_edit_schedule_sources(self, user_input=None):
        """Workday sensor, calendar and the start of the schedule day."""
        cfg = self._config_entry.data
        if user_input is not None:
            data = {**cfg, **user_input}
            for key in (CONF_SCHEDULE_WORKDAY_ENTITY, CONF_SCHEDULE_CALENDAR_ENTITY):
                if not user_input.get(key):
                    data.pop(key, None)
            self.hass.config_entries.async_update_entry(self._config_entry, data=data)
            return await self.async_step_edit_global_schedules()

        def _entity(key, **config):
            current = cfg.get(key)
            marker = vol.Optional(key, description={"suggested_value": current}) if current else vol.Optional(key)
            return marker, selector.EntitySelector(selector.EntitySelectorConfig(**config))

        workday_key, workday_sel = _entity(
            CONF_SCHEDULE_WORKDAY_ENTITY, domain="binary_sensor", integration="workday"
        )
        calendar_key, calendar_sel = _entity(CONF_SCHEDULE_CALENDAR_ENTITY, domain="calendar")
        return self.async_show_form(
            step_id="edit_schedule_sources",
            data_schema=vol.Schema({
                workday_key: workday_sel,
                calendar_key: calendar_sel,
                vol.Required(
                    CONF_SCHEDULE_DAY_START,
                    default=cfg.get(CONF_SCHEDULE_DAY_START, DEFAULT_SCHEDULE_DAY_START),
                ): selector.TimeSelector(),
            }),
        )

    async def async_step_edit_house_schedule(self, user_input=None):
        return await self._schedule_form(
            "edit_house_schedule", self._entry_data().get(DATA_HOUSE_SCHEDULE),
            user_input, self.async_step_edit_global_schedules,
        )

    async def async_step_edit_floor_schedule(self, user_input=None):
        """Pick the floor, then edit its schedule."""
        floors = self._entry_data().get(DATA_FLOOR_SCHEDULES, {})
        if user_input is not None and "floor" in user_input:
            self._floor_name = user_input["floor"]
            return await self.async_step_edit_floor_schedule_text()
        return self.async_show_form(
            step_id="edit_floor_schedule",
            data_schema=vol.Schema({
                vol.Required("floor"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=list(floors))
                ),
            }),
        )

    async def async_step_edit_floor_schedule_text(self, user_input=None):
        floors = self._entry_data().get(DATA_FLOOR_SCHEDULES, {})
        return await self._schedule_form(
            "edit_floor_schedule_text", floors.get(getattr(self, "_floor_name", None)),
            user_input, self.async_step_edit_global_schedules,
        )

    async def async_step_edit_global_general(self, user_input=None):
        """Edit shared comfort zone and safety temperature limits."""
        cfg = self._config_entry.data
        if user_input is not None:
            self.hass.config_entries.async_update_entry(self._config_entry, data={**cfg, **user_input})
            return await self.async_step_edit_global_defaults()

        return self.async_show_form(
            step_id="edit_global_general",
            data_schema=vol.Schema({
                vol.Required(CONF_COMFORT_ZONE, default=float(cfg.get(CONF_COMFORT_ZONE, DEFAULT_COMFORT_ZONE))): _num(0.1, 5.0, step=0.1),
                vol.Required(CONF_MINIMUM_TEMPERATURE, default=float(cfg.get(CONF_MINIMUM_TEMPERATURE, DEFAULT_MIN_TEMP))): _num(0.0, 20.0, step=0.1, mode=selector.NumberSelectorMode.BOX),
                vol.Required(CONF_MAXIMUM_TEMPERATURE, default=float(cfg.get(CONF_MAXIMUM_TEMPERATURE, DEFAULT_MAX_TEMP))): _num(20.0, 45.0, step=0.1, mode=selector.NumberSelectorMode.BOX),
            }),
        )

    async def async_step_edit_global_modes(self, user_input=None):
        """Edit global mode temperatures and each mode's aggressiveness profile."""
        cfg = self._config_entry.data
        if user_input is not None:
            self.hass.config_entries.async_update_entry(self._config_entry, data={**cfg, **user_input})
            return await self.async_step_edit_global_defaults()

        return self.async_show_form(
            step_id="edit_global_modes",
            data_schema=_mode_schema(cfg),
        )

    async def async_step_edit_global_profiles(self, user_input=None):
        """Menu for editing global aggressiveness profiles in grouped pages."""
        return self.async_show_menu(
            step_id="edit_global_profiles",
            menu_options=[
                "edit_global_profiles_default",
                "edit_global_profiles_relaxed",
                "edit_global_profiles_balanced",
                "edit_global_profiles_responsive",
                "edit_global_profiles_aggressive",
                "edit_global_defaults",
            ],
        )

    async def async_step_edit_global_profiles_default(self, user_input=None):
        return await self._edit_profile_group(
            "edit_global_profiles_default",
            _profile_default_field,
            self.async_step_edit_global_profiles,
            user_input,
        )

    async def async_step_edit_global_profiles_relaxed(self, user_input=None):
        return await self._edit_profile_group(
            "edit_global_profiles_relaxed",
            lambda cfg: _single_profile_fields("relaxed", cfg),
            self.async_step_edit_global_profiles,
            user_input,
        )

    async def async_step_edit_global_profiles_balanced(self, user_input=None):
        return await self._edit_profile_group(
            "edit_global_profiles_balanced",
            lambda cfg: _single_profile_fields("balanced", cfg),
            self.async_step_edit_global_profiles,
            user_input,
        )

    async def async_step_edit_global_profiles_responsive(self, user_input=None):
        return await self._edit_profile_group(
            "edit_global_profiles_responsive",
            lambda cfg: _single_profile_fields("responsive", cfg),
            self.async_step_edit_global_profiles,
            user_input,
        )

    async def async_step_edit_global_profiles_aggressive(self, user_input=None):
        return await self._edit_profile_group(
            "edit_global_profiles_aggressive",
            lambda cfg: _single_profile_fields("aggressive", cfg),
            self.async_step_edit_global_profiles,
            user_input,
        )

    async def async_step_edit_global_floors(self, user_input=None):
        """Edit the list of floor mode selectors created by Global Defaults."""
        cfg = self._config_entry.data
        if user_input is not None:
            self.hass.config_entries.async_update_entry(self._config_entry, data={**cfg, **user_input})
            return await self.async_step_edit_global_defaults()

        return self.async_show_form(
            step_id="edit_global_floors",
            data_schema=vol.Schema({
                vol.Optional(
                    CONF_FLOOR_NAMES,
                    default=list(cfg.get(CONF_FLOOR_NAMES, [])),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=_ha_floor_options(self.hass),
                        custom_value=True,
                        multiple=True,
                    )
                ),
            }),
        )

    # ── Room aggressiveness ─────────────────────────────────────────────────
    async def async_step_edit_room_aggressiveness(self, user_input=None):
        """Menu for editing per-room aggressiveness profile settings."""
        return self.async_show_menu(
            step_id="edit_room_aggressiveness",
            menu_options=[
                "edit_room_aggressiveness_default",
                "edit_room_aggressiveness_relaxed",
                "edit_room_aggressiveness_balanced",
                "edit_room_aggressiveness_responsive",
                "edit_room_aggressiveness_aggressive",
                "init",
            ],
        )

    async def async_step_edit_room_aggressiveness_default(self, user_input=None):
        return await self._edit_profile_group(
            "edit_room_aggressiveness_default",
            _profile_default_field,
            self.async_step_edit_room_aggressiveness,
            user_input,
            update_climate=True,
        )

    async def async_step_edit_room_aggressiveness_relaxed(self, user_input=None):
        return await self._edit_profile_group(
            "edit_room_aggressiveness_relaxed",
            lambda cfg: _single_profile_fields("relaxed", cfg),
            self.async_step_edit_room_aggressiveness,
            user_input,
            update_climate=True,
        )

    async def async_step_edit_room_aggressiveness_balanced(self, user_input=None):
        return await self._edit_profile_group(
            "edit_room_aggressiveness_balanced",
            lambda cfg: _single_profile_fields("balanced", cfg),
            self.async_step_edit_room_aggressiveness,
            user_input,
            update_climate=True,
        )

    async def async_step_edit_room_aggressiveness_responsive(self, user_input=None):
        return await self._edit_profile_group(
            "edit_room_aggressiveness_responsive",
            lambda cfg: _single_profile_fields("responsive", cfg),
            self.async_step_edit_room_aggressiveness,
            user_input,
            update_climate=True,
        )

    async def async_step_edit_room_aggressiveness_aggressive(self, user_input=None):
        return await self._edit_profile_group(
            "edit_room_aggressiveness_aggressive",
            lambda cfg: _single_profile_fields("aggressive", cfg),
            self.async_step_edit_room_aggressiveness,
            user_input,
            update_climate=True,
        )

    async def _edit_profile_group(self, step_id, field_factory, return_step, user_input=None, update_climate=False):
        cfg = self._config_entry.data
        if user_input is not None:
            new_data = {**cfg, **user_input}
            self.hass.config_entries.async_update_entry(self._config_entry, data=new_data)
            if update_climate:
                entry_data = self.hass.data.get(DOMAIN, {}).get(self._config_entry.entry_id, {})
                climate = entry_data.get("climate_entity")
                if climate:
                    for profile, (comfort_key, spacing_key, comfort_default, spacing_default) in _PROFILE_CONFIG_FIELDS.items():
                        climate._profile_settings[profile] = (
                            float(new_data.get(comfort_key, comfort_default)),
                            float(new_data.get(spacing_key, spacing_default)),
                        )
                    climate._profile_override = entry_data.get("profile_override")
                    self.hass.async_create_task(climate._evaluate_devices())
                    climate.async_write_ha_state()
            return await return_step()

        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema(field_factory(cfg)),
        )

    # ── Edit room settings (step 1: sensor + global toggle) ──────────────────

    async def async_step_edit_settings(self, user_input=None):
        """Edit room sensors and base comfort zone. Modes/profiles stay global."""
        cfg = self._config_entry.data
        global_cfg = self._global_config()

        if user_input is not None:
            clean = {k: v for k, v in user_input.items() if v not in (None, "")}
            # Leave "use global presets" as it is: forcing it back on here
            # discarded a room's own preset temperatures on every save.
            new_data = {**cfg, **clean}
            for key in (CONF_HUMIDITY_SENSOR, CONF_HOUSE_MODE_ENTITY):
                if key not in clean:
                    new_data.pop(key, None)
            self.hass.config_entries.async_update_entry(self._config_entry, data=new_data)
            return await self.async_step_init()

        humidity_sensor = cfg.get(CONF_HUMIDITY_SENSOR)
        house_mode_entity = cfg.get(CONF_HOUSE_MODE_ENTITY)

        schema_fields: dict = {
            vol.Required(
                CONF_TEMPERATURE_SENSOR,
                default=cfg[CONF_TEMPERATURE_SENSOR],
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
            ),
            (vol.Optional(CONF_HUMIDITY_SENSOR, default=humidity_sensor)
             if humidity_sensor else vol.Optional(CONF_HUMIDITY_SENSOR)
             ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="humidity")
            ),
            vol.Required(
                CONF_COMFORT_ZONE,
                default=float(cfg.get(CONF_COMFORT_ZONE, DEFAULT_COMFORT_ZONE)),
            ): _num(0.1, 5.0, step=0.1),
            (vol.Optional(CONF_HOUSE_MODE_ENTITY, default=house_mode_entity)
             if house_mode_entity else vol.Optional(CONF_HOUSE_MODE_ENTITY)
             ): _house_mode_entity_field(self.hass),
            vol.Required(
                CONF_MANUAL_HOLD_HOURS,
                default=float(cfg.get(CONF_MANUAL_HOLD_HOURS, DEFAULT_MANUAL_HOLD_HOURS)),
            ): _num(0, 24, step=0.5, unit="h", mode=selector.NumberSelectorMode.SLIDER),
            vol.Required(
                CONF_MANUAL_HOLD_CONFIRM_SECONDS,
                default=float(cfg.get(CONF_MANUAL_HOLD_CONFIRM_SECONDS, DEFAULT_MANUAL_HOLD_CONFIRM_SECONDS)),
            ): _num(0, 300, step=5, unit="s", mode=selector.NumberSelectorMode.SLIDER),
        }

        # Numbers only: the surrounding sentence lives in the translation file.
        placeholders = {
            "home": str(global_cfg.get(CONF_MODE_HOME, DEFAULT_MODE_HOME)),
            "comfort": str(global_cfg.get(CONF_MODE_WARMUP, DEFAULT_MODE_WARMUP)),
            "eco": str(global_cfg.get(CONF_MODE_COOLDOWN, DEFAULT_MODE_COOLDOWN)),
        }

        return self.async_show_form(
            step_id="edit_settings",
            data_schema=vol.Schema(schema_fields),
            description_placeholders=placeholders,
        )

    # ── Save ─────────────────────────────────────────────────────────────────

    async def async_step_finish(self, user_input=None):
        # Every page saves as it goes; this only closes the dialog.
        return self.async_create_entry(title="", data=dict(self._config_entry.options))


# ── Device subentry flow ─────────────────────────────────────────────────────

class DeviceSubentryFlow(config_entries.ConfigSubentryFlow):
    """
    Add or reconfigure one controlled device (a "stage") of a room.

    Two pages instead of the old three- or four-page wizard:
      1. user / reconfigure — name, entity and role
      2. settings — every remaining setting that applies to that entity and
         role, on one form: thresholds, plus mode, target overshoot and fan /
         swing settings when the entity is a climate device.
    """

    def __init__(self) -> None:
        self._pending: dict = {}
        self._existing: dict = {}

    async def async_step_user(self, user_input=None):
        return await self._step_identity("user", user_input)

    async def async_step_reconfigure(self, user_input=None):
        if not self._existing:
            self._existing = dict(self._get_reconfigure_subentry().data)
        return await self._step_identity("reconfigure", user_input)

    async def _step_identity(self, step_id: str, user_input):
        errors: dict[str, str] = {}
        if user_input is not None:
            needs_humidity = user_input[CONF_DEVICE_ROLE] == ROLE_DEHUMIDIFY
            if needs_humidity and not self._get_entry().data.get(CONF_HUMIDITY_SENSOR):
                # Without a humidity reading a dehumidifier stage can never run.
                errors["base"] = "humidity_sensor_required"
            else:
                self._pending = dict(user_input)
                return await self.async_step_settings()

        defaults = user_input or self._existing
        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema({
                vol.Required(CONF_DEVICE_LABEL, default=defaults.get(CONF_DEVICE_LABEL, "")): str,
                vol.Required(CONF_DEVICE_ENTITY, default=defaults.get(CONF_DEVICE_ENTITY, vol.UNDEFINED)): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["switch", "climate", "input_boolean", "fan"])
                ),
                vol.Required(CONF_DEVICE_ROLE, default=defaults.get(CONF_DEVICE_ROLE, ROLE_HEATING)): _ROLE_SELECTOR,
            }),
            errors=errors,
        )

    async def async_step_settings(self, user_input=None):
        role = self._pending.get(CONF_DEVICE_ROLE, ROLE_HEATING)
        entity_id = self._pending.get(CONF_DEVICE_ENTITY, "")
        is_climate = entity_id.startswith("climate.")
        # Settings saved for a different role or entity are not carried over.
        same_kind = (
            self._existing.get(CONF_DEVICE_ROLE) == role
            and self._existing.get(CONF_DEVICE_ENTITY) == entity_id
        )
        existing = self._existing if same_kind else {}

        if user_input is not None:
            data = {**self._pending, **user_input}
            if CONF_DEVICE_ACTIVATION_POINT in data:
                data[CONF_DEVICE_ACTIVATION_POINT] = int(data[CONF_DEVICE_ACTIVATION_POINT])
            # The id never changes, so the stage's sensor stays the same entity.
            data[CONF_DEVICE_ID] = self._existing.get(CONF_DEVICE_ID) or uuid4().hex
            title = data[CONF_DEVICE_LABEL]
            if self.source == config_entries.SOURCE_USER:
                return self.async_create_entry(title=title, data=data)
            return self.async_update_and_abort(
                self._get_entry(),
                self._get_reconfigure_subentry(),
                title=title,
                data=data,
            )

        fields: dict = {}
        if role == ROLE_DEHUMIDIFY:
            fields[vol.Required(
                CONF_DEVICE_HUMIDITY_THRESHOLD,
                default=float(existing.get(CONF_DEVICE_HUMIDITY_THRESHOLD, DEFAULT_HUMIDITY_THRESHOLD)),
            )] = _num(10, 100, step=1, unit="%", mode=selector.NumberSelectorMode.BOX)
            fields[vol.Required(
                CONF_DEVICE_HUMIDITY_HYSTERESIS,
                default=float(existing.get(CONF_DEVICE_HUMIDITY_HYSTERESIS, DEFAULT_HUMIDITY_HYSTERESIS)),
            )] = _num(1, 20, step=1, unit="%", mode=selector.NumberSelectorMode.BOX)
            fields[vol.Required(
                CONF_DEVICE_DEHUMIDIFY_ONLY_WHEN_IDLE,
                default=bool(existing.get(CONF_DEVICE_DEHUMIDIFY_ONLY_WHEN_IDLE, True)),
            )] = selector.BooleanSelector()
        else:
            point = int(existing.get(CONF_DEVICE_ACTIVATION_POINT, 0))
            fields[vol.Required(
                CONF_DEVICE_ACTIVATION_POINT, default=str(point)
            )] = _activation_point_selector(role, point)
            fields[vol.Required(
                CONF_DEVICE_DEACTIVATE_OFFSET,
                default=float(existing.get(CONF_DEVICE_DEACTIVATE_OFFSET, DEFAULT_DEACTIVATE_OFFSET)),
            )] = _num(0.1, 5.0, step=0.1, mode=selector.NumberSelectorMode.BOX)
            fields[vol.Required(
                CONF_DEVICE_EMERGENCY_ENABLED,
                default=bool(existing.get(CONF_DEVICE_EMERGENCY_ENABLED, False)),
            )] = selector.BooleanSelector()

        # Every kind of device can be protected from short cycling.
        for conf_key, default in (
            (CONF_DEVICE_MIN_ON_MINUTES, DEFAULT_MIN_ON_MINUTES),
            (CONF_DEVICE_MIN_OFF_MINUTES, DEFAULT_MIN_OFF_MINUTES),
        ):
            fields[vol.Required(
                conf_key, default=float(existing.get(conf_key, default)),
            )] = _num(0, 60, step=1, unit="min", mode=selector.NumberSelectorMode.BOX)

        if is_climate:
            default_mode = existing.get(
                CONF_DEVICE_HVAC_MODE_ON,
                "dry" if role == ROLE_DEHUMIDIFY else ("heat" if role == ROLE_HEATING else "cool"),
            )
            fields[vol.Required(CONF_DEVICE_HVAC_MODE_ON, default=default_mode)] = selector.SelectSelector(
                selector.SelectSelectorConfig(options=_climate_modes_for_entity(self.hass, entity_id))
            )
            # Target overshoot is always positive; the direction follows the
            # role. Not applicable to dehumidifying.
            if role != ROLE_DEHUMIDIFY:
                stored_offset = existing.get(CONF_DEVICE_TARGET_TEMP_OFFSET)
                default_offset = abs(float(stored_offset)) if stored_offset is not None else 3.0
                fields[vol.Required(CONF_DEVICE_TARGET_TEMP_OFFSET, default=default_offset)] = (
                    _num(0.0, 15.0, step=0.5, mode=selector.NumberSelectorMode.BOX)
                )
            # Optional secondary attributes, offered only for what this entity
            # actually advertises, and for every role.
            for conf_key, attribute in (
                (CONF_DEVICE_FAN_MODE, "fan_modes"),
                (CONF_DEVICE_SWING_MODE, "swing_modes"),
                (CONF_DEVICE_SWING_HORIZONTAL_MODE, "swing_horizontal_modes"),
            ):
                options = _secondary_options_for_entity(self.hass, entity_id, attribute)
                if options is None:
                    continue
                fields[
                    vol.Optional(conf_key, default=existing.get(conf_key, SECONDARY_UNSET))
                ] = selector.SelectSelector(selector.SelectSelectorConfig(options=options))

        return self.async_show_form(
            step_id="settings",
            data_schema=vol.Schema(fields),
            description_placeholders={
                "label": self._pending.get(CONF_DEVICE_LABEL, ""),
                "entity_id": entity_id,
            },
        )
