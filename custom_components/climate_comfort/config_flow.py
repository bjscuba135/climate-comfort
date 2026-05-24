from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.helpers import selector
from homeassistant.util import slugify

from .const import (
    CONF_COMFORT_ZONE,
    CONF_DEVICE_ACTIVATE_OFFSET,
    CONF_DEVICE_DEACTIVATE_OFFSET,
    CONF_DEVICE_DEHUMIDIFY_ONLY_WHEN_IDLE,
    CONF_DEVICE_ENTITY,
    CONF_DEVICE_HUMIDITY_HYSTERESIS,
    CONF_DEVICE_HUMIDITY_THRESHOLD,
    CONF_DEVICE_HVAC_MODE_ON,
    CONF_DEVICE_LABEL,
    CONF_DEVICE_ROLE,
    CONF_DEVICE_TARGET_TEMP_OFFSET,
    CONF_DEVICES,
    CONF_ENTRY_TYPE,
    CONF_FLOOR_NAMES,
    CONF_HOUSE_MODE_ENTITY,
    CONF_HUMIDITY_SENSOR,
    CONF_MANUAL_HOLD_HOURS,
    DEFAULT_MANUAL_HOLD_HOURS,
    CONF_PRESET_AWAY_HIGH,
    CONF_PRESET_AWAY_LOW,
    CONF_PRESET_BOOST,
    CONF_PRESET_COMFORT,
    CONF_PRESET_ECO,
    CONF_TEMPERATURE_SENSOR,
    CONF_USE_GLOBAL_PRESETS,
    DEFAULT_ACTIVATE_OFFSET,
    DEFAULT_COMFORT_ZONE,
    DEFAULT_DEACTIVATE_OFFSET,
    DEFAULT_HUMIDITY_HYSTERESIS,
    DEFAULT_HUMIDITY_THRESHOLD,
    DEFAULT_PRESET_AWAY_HIGH,
    DEFAULT_PRESET_AWAY_LOW,
    DEFAULT_PRESET_BOOST,
    DEFAULT_PRESET_COMFORT,
    DEFAULT_PRESET_ECO,
    DOMAIN,
    ENTRY_TYPE_GLOBAL,
    ENTRY_TYPE_ROOM,
    ROLE_COOLING,
    ROLE_DEHUMIDIFY,
    ROLE_HEATING,
)

# ── Selector helpers ────────────────────────────────────────────────────────


_ROLE_OPTIONS = [
    selector.SelectOptionDict(value=ROLE_HEATING, label="Heating"),
    selector.SelectOptionDict(value=ROLE_COOLING, label="Cooling"),
    selector.SelectOptionDict(value=ROLE_DEHUMIDIFY, label="Dehumidifier"),
]

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


def _preset_schema(eco=DEFAULT_PRESET_ECO, comfort=DEFAULT_PRESET_COMFORT,
                   boost=DEFAULT_PRESET_BOOST, away_low=DEFAULT_PRESET_AWAY_LOW,
                   away_high=DEFAULT_PRESET_AWAY_HIGH) -> vol.Schema:
    return vol.Schema({
        vol.Required(CONF_PRESET_ECO, default=eco): _num(5, 30),
        vol.Required(CONF_PRESET_COMFORT, default=comfort): _num(5, 30),
        vol.Required(CONF_PRESET_BOOST, default=boost): _num(5, 30),
        vol.Required(CONF_PRESET_AWAY_LOW, default=away_low): _num(5, 25, mode=selector.NumberSelectorMode.BOX),
        vol.Required(CONF_PRESET_AWAY_HIGH, default=away_high): _num(20, 40, mode=selector.NumberSelectorMode.BOX),
    })


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


# ── Config flow ─────────────────────────────────────────────────────────────

class ClimateComfortConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._data: dict = {}

    async def async_step_user(self, user_input=None):
        return self.async_show_menu(
            step_id="user",
            menu_options={
                "room": "Room thermostat",
                "global_defaults": "Global defaults (shared preset temperatures)",
            },
        )

    # ── Room setup path ──────────────────────────────────────────────────────

    async def async_step_room(self, user_input=None):
        g = self._global_config()
        has_global = bool(g)

        if user_input is not None:
            # Prevent two rooms with the same name being created accidentally
            room_slug = slugify(user_input[CONF_NAME])
            await self.async_set_unique_id(f"{DOMAIN}_room_{room_slug}")
            self._abort_if_unique_id_configured()
            if self._room_name_exists(user_input[CONF_NAME]):
                return self.async_abort(reason="already_configured")

            self._data.update(user_input)
            self._data[CONF_ENTRY_TYPE] = ENTRY_TYPE_ROOM
            use_global = bool(user_input.get(CONF_USE_GLOBAL_PRESETS, False))

            if use_global and has_global:
                # Copy global preset values into the entry data and set the flag.
                # Preset step is skipped entirely.
                for key in (
                    CONF_PRESET_ECO, CONF_PRESET_COMFORT, CONF_PRESET_BOOST,
                    CONF_PRESET_AWAY_LOW, CONF_PRESET_AWAY_HIGH,
                ):
                    if key in g:
                        self._data[key] = g[key]
                self._data[CONF_USE_GLOBAL_PRESETS] = True
                return self.async_create_entry(title=self._data[CONF_NAME], data=self._data)

            self._data[CONF_USE_GLOBAL_PRESETS] = False
            return await self.async_step_presets()

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

        # Only show the toggle when a Global Defaults entry exists
        if has_global:
            schema_fields[vol.Required(CONF_USE_GLOBAL_PRESETS, default=True)] = (
                selector.BooleanSelector()
            )

        return self.async_show_form(
            step_id="room",
            data_schema=vol.Schema(schema_fields),
        )

    async def async_step_presets(self, user_input=None):
        if user_input is not None:
            self._data.update(user_input)
            return self.async_create_entry(title=self._data[CONF_NAME], data=self._data)

        g = self._global_config()
        return self.async_show_form(
            step_id="presets",
            data_schema=_preset_schema(
                eco=float(g.get(CONF_PRESET_ECO, DEFAULT_PRESET_ECO)),
                comfort=float(g.get(CONF_PRESET_COMFORT, DEFAULT_PRESET_COMFORT)),
                boost=float(g.get(CONF_PRESET_BOOST, DEFAULT_PRESET_BOOST)),
                away_low=float(g.get(CONF_PRESET_AWAY_LOW, DEFAULT_PRESET_AWAY_LOW)),
                away_high=float(g.get(CONF_PRESET_AWAY_HIGH, DEFAULT_PRESET_AWAY_HIGH)),
            ),
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
                **_preset_schema().schema,
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
    Device list management and room settings editing.

    Device add/edit flow:
      1. add_device / edit_device_select → edit_device
         Captures: label, entity, role
      2a. device_temp_config  (heating/cooling)
         Captures: activate_offset, deactivate_offset
      2b. device_humidity_config  (dehumidifier)
         Captures: humidity_threshold, humidity_hysteresis, only_when_idle
      3. device_climate_mode  (climate entities only, any role)
         Captures: hvac_mode_on (dynamic from entity), optional target_temp_offset
    """

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry
        self._devices: list[dict] = list(config_entry.options.get(CONF_DEVICES, []))
        self._pending: dict = {}
        self._pending_settings: dict = {}
        self._editing_index: int | None = None

    def _global_config(self) -> dict:
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_GLOBAL:
                return entry.data
        return {}

    # ── Main menu ────────────────────────────────────────────────────────────

    async def async_step_init(self, user_input=None):
        # Global Defaults entries have no devices — send straight to their own edit form
        if self._config_entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_GLOBAL:
            return await self.async_step_edit_global_defaults()

        using_global = bool(
            self._config_entry.data.get(CONF_USE_GLOBAL_PRESETS, False)
        )

        base_menu: dict[str, str] = {"add_device": "Add a device"}
        if self._devices:
            base_menu["edit_device_select"] = "Edit a device"
            base_menu["remove_device"] = "Remove a device"
        base_menu["edit_settings"] = "Edit room settings"
        if not using_global:
            base_menu["edit_room_presets"] = "Edit preset temperatures"
        base_menu["finish"] = "Save & close"

        return self.async_show_menu(step_id="init", menu_options=base_menu)

    # ── Global defaults edit (shown instead of the room menu) ────────────────

    async def async_step_edit_global_defaults(self, user_input=None):
        """Edit the shared preset temperatures and comfort zone."""
        cfg = self._config_entry.data

        if user_input is not None:
            new_data = {**cfg, **user_input}
            self.hass.config_entries.async_update_entry(self._config_entry, data=new_data)
            return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="edit_global_defaults",
            data_schema=vol.Schema({
                vol.Required(CONF_COMFORT_ZONE, default=float(cfg.get(CONF_COMFORT_ZONE, DEFAULT_COMFORT_ZONE))): _num(0.1, 5.0, step=0.1),
                **_preset_schema(
                    eco=float(cfg.get(CONF_PRESET_ECO, DEFAULT_PRESET_ECO)),
                    comfort=float(cfg.get(CONF_PRESET_COMFORT, DEFAULT_PRESET_COMFORT)),
                    boost=float(cfg.get(CONF_PRESET_BOOST, DEFAULT_PRESET_BOOST)),
                    away_low=float(cfg.get(CONF_PRESET_AWAY_LOW, DEFAULT_PRESET_AWAY_LOW)),
                    away_high=float(cfg.get(CONF_PRESET_AWAY_HIGH, DEFAULT_PRESET_AWAY_HIGH)),
                ).schema,
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

    # ── Step 1: label / entity / role ────────────────────────────────────────

    async def async_step_add_device(self, user_input=None):
        self._editing_index = None
        return await self._step_device_identity(user_input)

    async def async_step_edit_device_select(self, user_input=None):
        if user_input is not None:
            target = user_input["device_to_edit"]
            if target == "__back__":
                return await self.async_step_init()
            idx_str, _, _eid = target.partition("|")
            try:
                self._editing_index = int(idx_str)
            except ValueError:
                self._editing_index = next(
                    (i for i, d in enumerate(self._devices) if d[CONF_DEVICE_ENTITY] == target),
                    None,
                )
            return await self.async_step_edit_device()

        # ← Back appears first; devices follow with an index prefix so duplicate
        # entity_ids (multi-stage escalation) remain individually selectable.
        options = [
            selector.SelectOptionDict(value="__back__", label="← Back to menu"),
            *[
                selector.SelectOptionDict(
                    value=f"{i}|{d[CONF_DEVICE_ENTITY]}",
                    label=f"{d.get(CONF_DEVICE_LABEL, d[CONF_DEVICE_ENTITY])} ({d.get(CONF_DEVICE_ROLE, '')})",
                )
                for i, d in enumerate(self._devices)
            ],
        ]
        return self.async_show_form(
            step_id="edit_device_select",
            data_schema=vol.Schema({
                vol.Required("device_to_edit"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=options)
                )
            }),
        )

    async def async_step_edit_device(self, user_input=None):
        return await self._step_device_identity(user_input)

    async def _step_device_identity(self, user_input):
        """Step 1 of device add/edit: label, entity, role."""
        editing = self._editing_index is not None
        step_id = "edit_device" if editing else "add_device"
        existing = self._devices[self._editing_index] if editing and self._editing_index is not None else {}

        if user_input is not None:
            self._pending = dict(user_input)
            role = user_input[CONF_DEVICE_ROLE]
            if role == ROLE_DEHUMIDIFY:
                return await self.async_step_device_humidity_config()
            return await self.async_step_device_temp_config()

        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema({
                vol.Required(CONF_DEVICE_LABEL, default=existing.get(CONF_DEVICE_LABEL, "")): str,
                vol.Required(CONF_DEVICE_ENTITY, default=existing.get(CONF_DEVICE_ENTITY, vol.UNDEFINED)): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["switch", "climate", "input_boolean", "fan"])
                ),
                vol.Required(CONF_DEVICE_ROLE, default=existing.get(CONF_DEVICE_ROLE, ROLE_HEATING)): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=_ROLE_OPTIONS)
                ),
            }),
        )

    # ── Step 2a: temperature device config ───────────────────────────────────

    async def async_step_device_temp_config(self, user_input=None):
        editing = self._editing_index is not None
        existing = self._devices[self._editing_index] if editing and self._editing_index is not None else {}

        if user_input is not None:
            self._pending.update(user_input)
            if self._pending.get(CONF_DEVICE_ENTITY, "").startswith("climate."):
                return await self.async_step_device_climate_mode()
            self._commit_pending()
            return await self.async_step_init()

        return self.async_show_form(
            step_id="device_temp_config",
            data_schema=vol.Schema({
                vol.Required(
                    CONF_DEVICE_ACTIVATE_OFFSET,
                    default=float(existing.get(CONF_DEVICE_ACTIVATE_OFFSET, DEFAULT_ACTIVATE_OFFSET)),
                ): _num(0.0, 20.0, mode=selector.NumberSelectorMode.BOX),
                vol.Required(
                    CONF_DEVICE_DEACTIVATE_OFFSET,
                    default=float(existing.get(CONF_DEVICE_DEACTIVATE_OFFSET, DEFAULT_DEACTIVATE_OFFSET)),
                ): _num(0.1, 5.0, step=0.1, mode=selector.NumberSelectorMode.BOX),
            }),
            description_placeholders={
                "role": self._pending.get(CONF_DEVICE_ROLE, ""),
                "activate_help": (
                    "0 = triggers exactly at the comfort zone boundary. "
                    "5 = triggers 5°C beyond it."
                ),
            },
        )

    # ── Step 2b: humidity / dehumidifier config ───────────────────────────────

    async def async_step_device_humidity_config(self, user_input=None):
        editing = self._editing_index is not None
        existing = self._devices[self._editing_index] if editing and self._editing_index is not None else {}

        if user_input is not None:
            self._pending.update(user_input)
            if self._pending.get(CONF_DEVICE_ENTITY, "").startswith("climate."):
                return await self.async_step_device_climate_mode()
            self._commit_pending()
            return await self.async_step_init()

        return self.async_show_form(
            step_id="device_humidity_config",
            data_schema=vol.Schema({
                vol.Required(
                    CONF_DEVICE_HUMIDITY_THRESHOLD,
                    default=float(existing.get(CONF_DEVICE_HUMIDITY_THRESHOLD, DEFAULT_HUMIDITY_THRESHOLD)),
                ): _num(10, 100, step=1, unit="%", mode=selector.NumberSelectorMode.BOX),
                vol.Required(
                    CONF_DEVICE_HUMIDITY_HYSTERESIS,
                    default=float(existing.get(CONF_DEVICE_HUMIDITY_HYSTERESIS, DEFAULT_HUMIDITY_HYSTERESIS)),
                ): _num(1, 20, step=1, unit="%", mode=selector.NumberSelectorMode.BOX),
                vol.Required(
                    CONF_DEVICE_DEHUMIDIFY_ONLY_WHEN_IDLE,
                    default=bool(existing.get(CONF_DEVICE_DEHUMIDIFY_ONLY_WHEN_IDLE, True)),
                ): selector.BooleanSelector(),
            }),
        )

    # ── Step 3: climate mode (dynamic from entity) ────────────────────────────

    async def async_step_device_climate_mode(self, user_input=None):
        editing = self._editing_index is not None
        existing = self._devices[self._editing_index] if editing and self._editing_index is not None else {}
        entity_id = self._pending.get(CONF_DEVICE_ENTITY, "")
        role = self._pending.get(CONF_DEVICE_ROLE, ROLE_HEATING)

        if user_input is not None:
            self._pending.update(user_input)
            self._commit_pending()
            return await self.async_step_init()

        # Dynamically build the HVAC mode list from the entity's actual supported modes
        mode_options = _climate_modes_for_entity(self.hass, entity_id)

        default_mode = existing.get(
            CONF_DEVICE_HVAC_MODE_ON,
            "dry" if role == ROLE_DEHUMIDIFY else ("heat" if role == ROLE_HEATING else "cool"),
        )
        # Stored value may be signed (old format) or unsigned (new) — always show positive
        stored_offset = existing.get(CONF_DEVICE_TARGET_TEMP_OFFSET)
        default_offset = abs(float(stored_offset)) if stored_offset is not None else 3.0

        schema_fields: dict = {
            vol.Required(CONF_DEVICE_HVAC_MODE_ON, default=default_mode): selector.SelectSelector(
                selector.SelectSelectorConfig(options=mode_options)
            ),
        }
        # Target temp overshoot — always a positive value, direction inferred from role,
        # exactly like activate_offset. Not applicable to dehumidify.
        if role != ROLE_DEHUMIDIFY:
            schema_fields[vol.Required(CONF_DEVICE_TARGET_TEMP_OFFSET, default=default_offset)] = (
                _num(0.0, 15.0, step=0.5, mode=selector.NumberSelectorMode.BOX)
            )

        return self.async_show_form(
            step_id="device_climate_mode",
            data_schema=vol.Schema(schema_fields),
            description_placeholders={
                "entity_id": entity_id,
                "offset_help": (
                    "Direction is automatic: heating adds this to the setpoint, "
                    "cooling subtracts it. "
                    "E.g. 3 on a cooling device → AC targets setpoint−3°C so it actually runs. "
                    "Set to 0 to use the setpoint directly as the device target."
                ),
            },
        )

    # ── Remove device ────────────────────────────────────────────────────────

    async def async_step_remove_device(self, user_input=None):
        if not self._devices:
            return await self.async_step_init()

        if user_input is not None:
            idx_str = user_input.get("device_to_remove", "")
            if idx_str == "__back__":
                return await self.async_step_init()
            try:
                idx = int(idx_str.split("|")[0])
                self._devices.pop(idx)
            except (ValueError, IndexError):
                pass
            return await self.async_step_init()

        options = [
            selector.SelectOptionDict(value="__back__", label="← Back to menu"),
            *[
                selector.SelectOptionDict(
                    value=f"{i}|{d[CONF_DEVICE_ENTITY]}",
                    label=f"{d.get(CONF_DEVICE_LABEL, d[CONF_DEVICE_ENTITY])} ({d.get(CONF_DEVICE_ROLE, '')})",
                )
                for i, d in enumerate(self._devices)
            ],
        ]
        return self.async_show_form(
            step_id="remove_device",
            data_schema=vol.Schema({
                vol.Required("device_to_remove"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=options)
                )
            }),
        )

    # ── Edit room settings (step 1: sensor + global toggle) ──────────────────

    async def async_step_edit_settings(self, user_input=None):
        """
        Step 1: temperature sensor, comfort zone, house mode, and (if a Global
        Defaults entry exists) a toggle to sync preset temperatures from it.

        If 'use global presets' is turned ON we copy the global values into
        local data so they're visible, set the flag, and skip the presets step.
        If turned OFF (or no global exists) we proceed to edit_presets where
        the user can set their own values.
        """
        cfg = self._config_entry.data
        global_cfg = self._global_config()
        has_global = bool(global_cfg)

        if user_input is not None:
            # Strip None / empty-string values for optional entity fields so we
            # don't write invalid entity IDs into config data.
            clean = {
                k: v for k, v in user_input.items()
                if v not in (None, "")
            }
            new_data = {**cfg, **clean}
            # If an optional entity field was cleared (absent from clean), remove it
            for key in (CONF_HUMIDITY_SENSOR, CONF_HOUSE_MODE_ENTITY):
                if key not in clean:
                    new_data.pop(key, None)

            use_global = bool(clean.get(CONF_USE_GLOBAL_PRESETS, False))

            if use_global and has_global:
                for key in (
                    CONF_PRESET_ECO, CONF_PRESET_COMFORT, CONF_PRESET_BOOST,
                    CONF_PRESET_AWAY_LOW, CONF_PRESET_AWAY_HIGH,
                ):
                    if key in global_cfg:
                        new_data[key] = global_cfg[key]
                new_data[CONF_USE_GLOBAL_PRESETS] = True
                self.hass.config_entries.async_update_entry(self._config_entry, data=new_data)
                return await self.async_step_init()

            new_data[CONF_USE_GLOBAL_PRESETS] = False
            self._pending_settings = new_data
            return await self.async_step_edit_presets()

        # ── Build the form ────────────────────────────────────────────────────
        # Optional entity selectors must NOT use default="" — an empty string
        # fails HA's entity-ID validation.  Omit the default entirely when unset.
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
        }

        placeholders: dict = {}

        if has_global:
            schema_fields[vol.Required(
                CONF_USE_GLOBAL_PRESETS,
                default=bool(cfg.get(CONF_USE_GLOBAL_PRESETS, False)),
            )] = selector.BooleanSelector()

            if cfg.get(CONF_USE_GLOBAL_PRESETS):
                placeholders["global_summary"] = (
                    f"Eco {global_cfg.get(CONF_PRESET_ECO, '?')} °C  ·  "
                    f"Comfort {global_cfg.get(CONF_PRESET_COMFORT, '?')} °C  ·  "
                    f"Boost {global_cfg.get(CONF_PRESET_BOOST, '?')} °C  ·  "
                    f"Away {global_cfg.get(CONF_PRESET_AWAY_LOW, '?')}–"
                    f"{global_cfg.get(CONF_PRESET_AWAY_HIGH, '?')} °C"
                )

        return self.async_show_form(
            step_id="edit_settings",
            data_schema=vol.Schema(schema_fields),
            description_placeholders=placeholders or None,
        )

    # ── Edit room settings (step 2: preset temperatures, via edit_settings) ─────

    async def async_step_edit_presets(self, user_input=None):
        """Preset edit reached via edit_settings (after sensor/global-toggle step)."""
        pending = getattr(self, "_pending_settings", {})
        cfg = self._config_entry.data

        if user_input is not None:
            new_data = {**pending, **user_input}
            self.hass.config_entries.async_update_entry(self._config_entry, data=new_data)
            self._pending_settings = {}
            return await self.async_step_init()

        return self.async_show_form(
            step_id="edit_presets",
            data_schema=_preset_schema(
                eco=float(cfg.get(CONF_PRESET_ECO, DEFAULT_PRESET_ECO)),
                comfort=float(cfg.get(CONF_PRESET_COMFORT, DEFAULT_PRESET_COMFORT)),
                boost=float(cfg.get(CONF_PRESET_BOOST, DEFAULT_PRESET_BOOST)),
                away_low=float(cfg.get(CONF_PRESET_AWAY_LOW, DEFAULT_PRESET_AWAY_LOW)),
                away_high=float(cfg.get(CONF_PRESET_AWAY_HIGH, DEFAULT_PRESET_AWAY_HIGH)),
            ),
        )

    # ── Edit preset temperatures (direct menu option) ─────────────────────────

    async def async_step_edit_room_presets(self, user_input=None):
        """
        Direct route to editing this room's preset temperatures.

        Always accessible from the main menu regardless of whether global
        presets are currently in use.  Saving here stores room-specific values
        and automatically clears the 'use global presets' flag so those values
        take effect immediately.
        """
        cfg = self._config_entry.data
        global_cfg = self._global_config()
        use_global = bool(cfg.get(CONF_USE_GLOBAL_PRESETS, False))

        if user_input is not None:
            new_data = {**cfg, **user_input, CONF_USE_GLOBAL_PRESETS: False}
            self.hass.config_entries.async_update_entry(self._config_entry, data=new_data)
            return await self.async_step_init()

        # Pre-fill with the currently effective values so the user sees
        # what they're working with (global or local, whichever is active).
        def _eff(key: str, default: float) -> float:
            if use_global:
                v = global_cfg.get(key) or cfg.get(key, default)
            else:
                v = cfg.get(key, default)
            return float(v)

        placeholders: dict = {}
        if use_global:
            placeholders["inherit_note"] = (
                "These values are currently inherited from Global Defaults. "
                "Saving here will store room-specific temperatures and stop "
                "inheriting from global."
            )

        return self.async_show_form(
            step_id="edit_room_presets",
            data_schema=_preset_schema(
                eco=_eff(CONF_PRESET_ECO, DEFAULT_PRESET_ECO),
                comfort=_eff(CONF_PRESET_COMFORT, DEFAULT_PRESET_COMFORT),
                boost=_eff(CONF_PRESET_BOOST, DEFAULT_PRESET_BOOST),
                away_low=_eff(CONF_PRESET_AWAY_LOW, DEFAULT_PRESET_AWAY_LOW),
                away_high=_eff(CONF_PRESET_AWAY_HIGH, DEFAULT_PRESET_AWAY_HIGH),
            ),
            description_placeholders=placeholders or None,
        )

    # ── Save ─────────────────────────────────────────────────────────────────

    async def async_step_finish(self, user_input=None):
        return self.async_create_entry(title="", data={CONF_DEVICES: self._devices})

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _commit_pending(self) -> None:
        if self._editing_index is not None:
            self._devices[self._editing_index] = self._pending
            self._editing_index = None
        else:
            self._devices.append(self._pending)
        self._pending = {}
