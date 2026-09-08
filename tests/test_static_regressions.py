import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = ROOT / "custom_components/climate_comfort"
INIT = (REPOSITORY_ROOT / "__init__.py").read_text(encoding="utf-8")
CLIMATE = (REPOSITORY_ROOT / "climate.py").read_text(encoding="utf-8")
SWITCH = (REPOSITORY_ROOT / "switch.py").read_text(encoding="utf-8")
BINARY_SENSOR = (REPOSITORY_ROOT / "binary_sensor.py").read_text(encoding="utf-8")
CONFIG_FLOW = (REPOSITORY_ROOT / "config_flow.py").read_text(encoding="utf-8")
CONST = (REPOSITORY_ROOT / "const.py").read_text(encoding="utf-8")
SELECT = (REPOSITORY_ROOT / "select.py").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")
STRINGS = json.loads((REPOSITORY_ROOT / "strings.json").read_text(encoding="utf-8"))
TRANSLATIONS = json.loads((REPOSITORY_ROOT / "translations/en.json").read_text(encoding="utf-8"))
MANIFEST = json.loads((REPOSITORY_ROOT / "manifest.json").read_text(encoding="utf-8"))


def _method_body(source: str, marker: str, next_marker: str) -> str:
    return source.split(marker, 1)[1].split(next_marker, 1)[0]


def test_turn_off_all_is_not_gated_by_is_active():
    body = _method_body(CLIMATE, "async def _turn_off_all", "async def _turn_off_dehumidifiers")
    assert "if device.is_active" not in body


def test_bad_temperature_fails_safe():
    body = _method_body(CLIMATE, "def _apply_temp_state", "def _apply_humidity_state")
    assert "bad temperature" in body
    assert "_turn_off_all" in body
    assert "_attr_available = False" in body


def test_manual_hold_expected_state_is_aggregated_per_entity():
    body = _method_body(CLIMATE, "def _check_manual_changes", "def _trigger_manual_hold")
    assert "expected_on_by_entity" in body
    assert "any(" in body and "d.is_active" in body
    assert "actual_on != expected_on_by_entity" in body


def test_dehumidification_switch_turns_off_dehumidifiers_immediately():
    dehumidify_class = SWITCH.split("class DehumidifySwitch", 1)[1]
    body = _method_body(dehumidify_class, "async def async_turn_off", "def _update_shared_state")
    assert "_turn_off_dehumidifiers" in body


def test_global_preset_switch_requires_global_defaults():
    setup_body = _method_body(SWITCH, "async def async_setup_entry", "# ── Using Global Presets")
    turn_on_body = _method_body(SWITCH, "async def async_turn_on", "async def async_turn_off")
    assert "ENTRY_TYPE_GLOBAL" in setup_body
    assert "GlobalPresetsSwitch" in setup_body
    assert "if not global_cfg" in turn_on_body
    assert "return" in turn_on_body


def test_temperature_sensor_selector_is_constrained_to_temperature_device_class():
    assert 'selector.EntitySelectorConfig(domain="sensor", device_class="temperature")' in CONFIG_FLOW


def test_fixed_mode_names_use_home_assistant_icon_backed_presets():
    assert 'MODE_AWAY = "away"' in CONST
    assert 'MODE_SLEEP = "sleep"' in CONST
    assert 'MODE_HOME = "home"' in CONST
    assert 'MODE_WARMUP = "comfort"' in CONST
    assert 'MODE_COOLDOWN = "eco"' in CONST
    assert 'MODE_ACTIVITY = "activity"' in CONST
    assert 'MODE_BOOST = "boost"' in CONST
    assert 'MODE_OPTIONS = [MODE_AWAY, MODE_SLEEP, MODE_HOME, MODE_WARMUP, MODE_COOLDOWN, MODE_ACTIVITY, MODE_BOOST]' in CONST
    assert 'OPTIONAL_MODE_OPTIONS = [MODE_SLEEP, MODE_WARMUP, MODE_COOLDOWN, MODE_ACTIVITY, MODE_BOOST]' in CONST
    assert 'MODE_ENABLE_KEYS = {' in CONST
    assert 'MODE_AWAY: CONF_MODE_AWAY_ENABLED' not in CONST
    assert 'MODE_ENABLE_DEFAULTS = {' in CONST
    assert 'CONF_MODE_AWAY_ENABLED: DEFAULT_MODE_AWAY_ENABLED' not in CONST
    assert 'DEFAULT_MODE_AWAY_ENABLED = True' not in CONST
    assert 'DEFAULT_MODE_ACTIVITY_ENABLED = False' in CONST
    assert 'DEFAULT_MODE_BOOST_ENABLED = False' in CONST
    assert '_enabled_house_mode_options' in SELECT
    assert 'HOUSE_MODE_OPTIONS = MODE_OPTIONS' not in SELECT
    assert '"warmup"' not in SELECT.split('_LEGACY_MODE_ALIASES', 1)[0]
    assert '"cooldown"' not in SELECT.split('_LEGACY_MODE_ALIASES', 1)[0]
    assert '_LEGACY_MODE_ALIASES' in SELECT
    assert '"warmup": MODE_WARMUP' in SELECT
    assert '"cooldown": MODE_COOLDOWN' in SELECT
    assert '_LEGACY_MODE_ALIASES' in CLIMATE


def test_global_profile_settings_are_required_and_one_decimal_place():
    assert "CONF_PROFILE_BALANCED_COMFORT_MULTIPLIER" in CONST
    assert "CONF_PROFILE_BALANCED_POINT_SPACING" in CONST
    assert "step=0.1" in CONFIG_FLOW
    assert 'CONF_DEFAULT_PROFILE = "default_profile"' in CONST
    assert 'CONF_MINIMUM_TEMPERATURE = "minimum_temperature"' in CONST
    assert 'CONF_MAXIMUM_TEMPERATURE = "maximum_temperature"' in CONST
    assert "DEFAULT_TEMP_STEP = 0.1" in CONST


def test_preset_switching_and_number_refresh_use_cached_global_config_when_hass_is_unavailable():
    preset_body = _method_body(CLIMATE, "async def async_set_preset_mode", "async def async_set_temperature")
    state_change_body = _method_body(CLIMATE, "def _handle_state_change", "# How long after our last service call")
    number_setup_body = _method_body((REPOSITORY_ROOT / "number.py").read_text(encoding="utf-8"), "async def async_setup_entry", "class RoomSettingNumber")
    number_global_body = _method_body((REPOSITORY_ROOT / "number.py").read_text(encoding="utf-8"), "def _global_config", "def _refresh_value")
    switch_refresh_body = _method_body(SWITCH, "def _refresh_numbers", "# ── Dehumidification")
    assert "def _restore_configured_comfort_zone" in CLIMATE
    assert "self._global_comfort_zone" in CLIMATE
    assert "self._local_comfort_zone" in CLIMATE
    assert "_get_global_config(self.hass)" not in preset_body
    assert preset_body.count("self._restore_configured_comfort_zone()") >= 2
    assert "self._restore_configured_comfort_zone()" in state_change_body
    assert "global_cfg = next(" in number_setup_body
    assert "RoomSettingNumber(entry, global_cfg" in number_setup_body
    assert "if self.hass is not None:" in number_global_body
    assert "return self._global_cfg" in number_global_body
    assert "if sensor.hass is None:" in CLIMATE
    assert "if num.hass is None:" in switch_refresh_body


def test_new_room_setup_requires_global_defaults_and_uses_modes_not_legacy_presets():
    room_body = _method_body(CONFIG_FLOW, "async def async_step_room", "# ── Global defaults path")
    assert 'global_defaults_required' in room_body
    assert "CONF_MODE_HOME" in room_body
    assert "CONF_MODE_COOLDOWN" in room_body
    assert "CONF_PRESET_ECO" not in room_body
    assert "async_step_presets" not in CONFIG_FLOW


def test_room_options_offer_local_aggressiveness_without_local_mode_temperature_overrides():
    menu_body = _method_body(CONFIG_FLOW, "async def async_step_init", "# ── Global defaults edit")
    assert "edit_room_presets" not in menu_body
    assert "edit_room_aggressiveness" in menu_body
    assert "CONF_USE_GLOBAL_PRESETS" not in menu_body
    assert "_preset_schema" not in CONFIG_FLOW


def test_global_defaults_options_are_split_into_sub_pages_with_mode_temperature_editor():
    global_menu_body = _method_body(CONFIG_FLOW, "async def async_step_edit_global_defaults", "async def async_step_edit_global_general")
    assert "async_show_menu" in global_menu_body
    assert "edit_global_general" in global_menu_body
    assert "edit_global_modes" in global_menu_body
    assert "edit_global_profiles" in global_menu_body
    assert "edit_global_floors" in global_menu_body
    global_strings = STRINGS["options"]["step"]
    assert "edit_global_modes" in global_strings
    assert "mode_home" in global_strings["edit_global_modes"]["data"]
    assert "mode_activity" in global_strings["edit_global_modes"]["data"]
    assert "mode_boost" in global_strings["edit_global_modes"]["data"]
    assert "mode_away" not in global_strings["edit_global_modes"]["data"]
    assert "mode_away_enabled" not in global_strings["edit_global_modes"]["data"]
    assert "mode_activity_enabled" in global_strings["edit_global_modes"]["data"]
    assert "mode_boost_enabled" in global_strings["edit_global_modes"]["data"]
    assert "edit_global_modes" in TRANSLATIONS["options"]["step"]
    assert "mode_home" in TRANSLATIONS["options"]["step"]["edit_global_modes"]["data"]
    assert "mode_activity" in TRANSLATIONS["options"]["step"]["edit_global_modes"]["data"]
    assert "mode_boost" in TRANSLATIONS["options"]["step"]["edit_global_modes"]["data"]
    assert "mode_away" not in TRANSLATIONS["options"]["step"]["edit_global_modes"]["data"]
    assert "mode_away_enabled" not in TRANSLATIONS["options"]["step"]["edit_global_modes"]["data"]
    assert "mode_activity_enabled" in TRANSLATIONS["options"]["step"]["edit_global_modes"]["data"]
    assert "mode_boost_enabled" in TRANSLATIONS["options"]["step"]["edit_global_modes"]["data"]

    modes_body = _method_body(CONFIG_FLOW, "async def async_step_edit_global_modes", "async def async_step_edit_global_profiles")
    assert "_mode_schema(cfg)" in modes_body
    assert "async_update_entry" in modes_body
    assert "CONF_MODE_AWAY_PROFILE" in CONFIG_FLOW
    assert "CONF_MODE_AWAY_ENABLED" not in modes_body
    assert "CONF_MODE_ACTIVITY_ENABLED" in CONFIG_FLOW
    assert "CONF_MODE_BOOST_ENABLED" in CONFIG_FLOW
    assert "Away always uses the configured minimum and maximum safety temperatures" in STRINGS["options"]["step"]["edit_global_modes"]["description"]
    assert "Away safety band" in TRANSLATIONS["config"]["step"]["global_defaults"]["data"]["mode_away"]


def test_room_aggressiveness_page_persists_room_profile_settings_and_climate_uses_them():
    aggressiveness_menu_body = _method_body(CONFIG_FLOW, "async def async_step_edit_room_aggressiveness", "async def async_step_edit_room_aggressiveness_default")
    assert "async_show_menu" in aggressiveness_menu_body
    assert "edit_room_aggressiveness_relaxed" in aggressiveness_menu_body
    assert "edit_room_aggressiveness_aggressive" in aggressiveness_menu_body

    relaxed_body = _method_body(CONFIG_FLOW, "async def async_step_edit_room_aggressiveness_relaxed", "async def async_step_edit_room_aggressiveness_balanced")
    single_profile_helper = _method_body(CONFIG_FLOW, "def _single_profile_fields", "def _mode_schema")
    assert '"relaxed"' in relaxed_body
    assert "CONF_PROFILE_RELAXED_COMFORT_MULTIPLIER" in CONFIG_FLOW
    assert "comfort_key" in single_profile_helper
    assert "async_update_entry" in CONFIG_FLOW
    assert "edit_room_aggressiveness" in STRINGS["options"]["step"]["init"]["menu_options"]
    assert "edit_room_aggressiveness_relaxed" in STRINGS["options"]["step"]
    assert "edit_room_aggressiveness" in TRANSLATIONS["options"]["step"]["init"]["menu_options"]
    assert "edit_room_aggressiveness_relaxed" in TRANSLATIONS["options"]["step"]

    settings_body = _method_body(CONFIG_FLOW, "async def async_step_edit_settings", "# ── Save")
    assert "CONF_PROFILE_AGGRESSIVE_POINT_SPACING" not in settings_body
    assert "CONF_PROFILE_BALANCED_COMFORT_MULTIPLIER" not in settings_body

    profile_loop = _method_body(CLIMATE, "for profile, (comfort_key, spacing_key, comfort_default, spacing_default) in _PROFILE_CONFIG.items():", "self._mode_temps")
    assert "cfg.get(comfort_key" in profile_loop
    assert "cfg.get(spacing_key" in profile_loop


def test_room_profile_select_allows_runtime_aggressiveness_override_independent_of_mode():
    init_text = (REPOSITORY_ROOT / "__init__.py").read_text(encoding="utf-8")
    assert '"select"' in init_text.split("PLATFORMS =", 1)[1].split("]", 1)[0]
    assert "class RoomAggressivenessSelect" in SELECT
    assert "PROFILE_OVERRIDE_MODE_DEFAULT" in SELECT
    assert "profile_override" in SELECT
    assert "_profile_override" in CLIMATE
    active_profile_body = _method_body(CLIMATE, "def _active_profile", "def _profile_comfort_multiplier")
    assert "self._profile_override" in active_profile_body
    assert "self._attr_preset_mode in self._mode_profiles" in active_profile_body


def test_manual_override_requires_confirmed_persistent_mismatch_before_hold():
    assert 'CONF_MANUAL_HOLD_CONFIRM_SECONDS = "manual_hold_confirm_seconds"' in CONST
    assert "DEFAULT_MANUAL_HOLD_CONFIRM_SECONDS" in CONST
    init_body = _method_body(CLIMATE, "# Manual hold tracking", "# True once the first evaluation")
    assert "_manual_mismatch_seen" in init_body
    check_body = _method_body(CLIMATE, "def _check_manual_changes", "def _trigger_manual_hold")
    assert "_manual_hold_confirm_seconds" in check_body
    assert "mismatch_for" in check_body
    assert "continue" in check_body.split("mismatch_for", 1)[1]
    settings_body = _method_body(CONFIG_FLOW, "async def async_step_edit_settings", "# ── Save")
    assert "CONF_MANUAL_HOLD_CONFIRM_SECONDS" in settings_body


def test_climate_stage_startup_sync_matches_actual_hvac_mode_not_any_on_state():
    startup_sync_body = _method_body(CLIMATE, "if not self._initial_sync_done:", "if self._hold_hours <= 0")
    assert "_device_matches_actual(device)" in startup_sync_body
    assert "device.is_active = self._device_is_on(device.entity_id)" not in startup_sync_body
    assert "def _device_target_hvac_mode" in CLIMATE
    assert "def _device_matches_actual" in CLIMATE
    matches_body = _method_body(CLIMATE, "def _device_matches_actual", "def _check_manual_changes")
    assert "state.state == self._device_target_hvac_mode(device)" in matches_body


def test_dehumidifier_on_same_climate_entity_does_not_turn_off_active_cooling_stage():
    dehumidifier_body = _method_body(CLIMATE, "# ── Evaluate dehumidifier devices", "# ── Update HVAC action")
    assert "_deactivate_or_release_device(device)" in dehumidifier_body
    assert "await self._deactivate_device(device)" not in dehumidifier_body
    assert "def _same_climate_has_active_temperature_stage" in CLIMATE
    assert "async def _deactivate_or_release_device" in CLIMATE
    release_body = _method_body(CLIMATE, "async def _deactivate_or_release_device", "async def _deactivate_device")
    assert "_same_climate_has_active_temperature_stage(device)" in release_body
    assert "device.is_active = False" in release_body
    assert "await self._deactivate_device(device)" in release_body


def test_climate_entity_uses_home_assistant_hvac_modes_and_set_temperature_mode_arg():
    assert "from homeassistant.exceptions import HomeAssistantError" in CLIMATE
    assert "HVACMode.OFF" in CLIMATE
    assert "HVACMode.HEAT" in CLIMATE
    assert "HVACMode.COOL" in CLIMATE
    assert "HVACMode.HEAT_COOL" in CLIMATE

    hvac_mode_body = _method_body(CLIMATE, "async def async_set_hvac_mode", "async def async_set_preset_mode")
    assert "if hvac_mode not in self._attr_hvac_modes" in hvac_mode_body
    assert "raise HomeAssistantError" in hvac_mode_body

    set_temperature_body = _method_body(
        CLIMATE,
        "async def async_set_temperature",
        "# ------------------------------------------------------------------\n    # Core control logic",
    )
    assert 'requested_hvac_mode = kwargs.get("hvac_mode")' in set_temperature_body
    assert "HVACMode(requested_hvac_mode)" in set_temperature_body
    assert "if hvac_mode not in self._attr_hvac_modes" in set_temperature_body
    assert "self._attr_hvac_mode = hvac_mode" in set_temperature_body


def test_device_activation_points_are_role_limited_selects():
    body = _method_body(CONFIG_FLOW, "async def async_step_device_temp_config", "# ── Step 2b")
    assert "_activation_point_selector" in body
    assert "ROLE_HEATING" in body
    assert "range(-20, 1)" in CONFIG_FLOW and "range(0, 21)" in CONFIG_FLOW
    activation_field = body.split("CONF_DEVICE_ACTIVATION_POINT", 1)[1].split("CONF_DEVICE_DEACTIVATE_OFFSET", 1)[0]
    assert "_activation_point_selector" in activation_field
    assert "NumberSelector" not in activation_field


def test_legacy_absolute_activation_offsets_are_not_scaled_by_aggressiveness_spacing():
    assert "def _migrate_legacy_device_offsets" in INIT
    assert "CONF_DEVICE_ACTIVATE_OFFSET" in INIT
    assert "device.pop(CONF_DEVICE_ACTIVATE_OFFSET" in INIT
    assert "CONF_DEVICE_ACTIVATION_POINT" in INIT
    assert "CONF_PROFILE_BALANCED_POINT_SPACING" in INIT
    assert "hass.config_entries.async_update_entry" in INIT
    assert "_migrate_legacy_device_offsets(hass, entry)" in INIT

    device_init = _method_body(CLIMATE, "def __init__(self, data: dict) -> None:", "    @property\n    def is_climate")
    assert "self.activation_point = None" in device_init
    assert "old activate_offset was degrees beyond the boundary" in device_init
    assert "def _activation_offset_for_device" in CLIMATE
    offset_helper = _method_body(CLIMATE, "def _activation_offset_for_device", "def _thresholds")
    assert "if device.activation_point is None" in offset_helper
    assert "return device.activate_offset" in offset_helper
    assert "abs(device.activation_point) * spacing" in offset_helper
    evaluation_body = _method_body(CLIMATE, "async def _evaluate_devices", "# ── Evaluate dehumidifier devices")
    assert "ut + self._activation_offset_for_device(device, point_spacing)" in evaluation_body
    assert "lt - self._activation_offset_for_device(device, point_spacing)" in evaluation_body


def test_binary_sensor_thresholds_use_same_activation_offset_logic_as_control():
    assert "def _device_activation_offset" in BINARY_SENSOR
    assert "device.activation_point is None" in BINARY_SENSOR
    assert "return device.activate_offset" in BINARY_SENSOR
    assert "abs(device.activation_point) * point_spacing" in BINARY_SENSOR
    assert '"point_spacing": self._profile_point_spacing()' in CLIMATE
    assert "sensor.update_trigger_name(lt, ut, self._profile_point_spacing())" in CLIMATE


def test_emergency_enabled_device_flag_is_collected_and_used_for_safety_limits():
    assert 'CONF_DEVICE_EMERGENCY_ENABLED = "emergency_enabled"' in CONST
    assert "CONF_DEVICE_EMERGENCY_ENABLED" in CONFIG_FLOW
    assert "emergency_enabled" in CLIMATE
    assert "minimum_temperature" in CLIMATE
    assert "maximum_temperature" in CLIMATE


def test_hacs_metadata_declares_single_installable_comfort_climate_integration():
    hacs_path = ROOT / "hacs.json"
    assert hacs_path.exists()
    hacs = json.loads(hacs_path.read_text(encoding="utf-8"))
    assert hacs["name"] == "Climate Comfort"
    assert "domains" not in hacs
    assert MANIFEST["domain"] == "comfort_climate"
    assert hacs["homeassistant"] == MANIFEST["min_homeassistant_version"]
    assert hacs.get("render_readme") is True

    component_dirs = [p.name for p in (ROOT / "custom_components").iterdir() if p.is_dir()]
    assert component_dirs == ["climate_comfort"]
    # HACS may cache the repository path from earlier releases as climate_comfort,
    # but it installs locally using the manifest domain, which must remain
    # comfort_climate for existing Home Assistant config entries.


def test_manifest_has_hacs_friendly_repository_metadata():
    assert MANIFEST["domain"] == "comfort_climate"
    assert MANIFEST["name"] == "Climate Comfort"
    assert MANIFEST["codeowners"] == ["@bjscuba135"]
    assert MANIFEST["documentation"] == "https://github.com/bjscuba135/climate-comfort"
    assert MANIFEST["issue_tracker"] == "https://github.com/bjscuba135/climate-comfort/issues"


def test_readme_documents_hacs_custom_repository_install_and_manual_migration():
    assert "HACS support coming soon" not in README
    assert "https://github.com/bjscuba135/climate-comfort" in README
    assert "Custom repositories" in README
    assert "custom_components/comfort_climate" in README
    assert "Home Assistant integration domain remains `comfort_climate`" in README
    assert "HACS installs it locally as `custom_components/comfort_climate`" in README
    assert "Sleep / Home / Comfort / Eco Temperature" in README
    assert "Away always uses the configured global minimum and maximum temperatures" in README


def test_repository_package_installs_as_comfort_climate_for_existing_config_entries():
    assert REPOSITORY_ROOT.exists()
    assert (REPOSITORY_ROOT / "__init__.py").exists()
    assert CONST.startswith('DOMAIN = "comfort_climate"')
    assert "legacy_domain" not in CONFIG_FLOW

    for platform in ["binary_sensor", "button", "climate", "number", "select", "switch"]:
        assert (REPOSITORY_ROOT / f"{platform}.py").exists()


def test_secondary_climate_attributes_default_to_unmanaged():
    assert 'SECONDARY_UNSET = "__unset__"' in CONST
    assert 'CONF_DEVICE_FAN_MODE = "fan_mode"' in CONST
    assert 'CONF_DEVICE_SWING_MODE = "swing_mode"' in CONST
    assert 'CONF_DEVICE_SWING_HORIZONTAL_MODE = "swing_horizontal_mode"' in CONST

    # The sentinel, an empty string and an absent key must all mean "not managed",
    # so enabling this feature never starts forcing a fan speed on existing rooms.
    normaliser = _method_body(CLIMATE, "def _secondary(raw)", "class _Device")
    assert "if raw is None" in normaliser
    assert "return None" in normaliser
    assert "if not value or value == SECONDARY_UNSET" in normaliser

    device_init = _method_body(CLIMATE, "def __init__(self, data: dict) -> None:", "    @property\n    def is_climate")
    assert "self.fan_mode: str | None = _secondary(data.get(CONF_DEVICE_FAN_MODE))" in device_init
    assert "self.swing_mode: str | None = _secondary(data.get(CONF_DEVICE_SWING_MODE))" in device_init
    assert "CONF_DEVICE_SWING_HORIZONTAL_MODE" in device_init


def test_secondary_climate_attributes_are_non_fatal_and_outside_activation_rollback():
    body = _method_body(CLIMATE, "async def _apply_secondary_settings", "async def _activate_device")
    assert '"set_fan_mode"' in body
    assert '"set_swing_mode"' in body
    # Horizontal swing is a separate HA service, not a value of set_swing_mode.
    assert '"set_swing_horizontal_mode"' in body
    # Unset attributes are skipped rather than sent as a literal sentinel.
    assert "if not value" in body and "continue" in body
    # Must swallow its own errors: by this point set_hvac_mode has already
    # succeeded and the hardware is running. Marking the device inactive here
    # would make the controller retry activation on every evaluation, forever.
    assert "except Exception" in body
    assert "_LOGGER.warning" in body
    # Never assigns is_active (the docstring discusses it; the code must not touch it).
    assert "is_active =" not in body

    activate = _method_body(CLIMATE, "async def _activate_device", "def _same_climate_has_active_temperature_stage")
    assert "await self._apply_secondary_settings(device)" in activate
    # Ordering: secondary attributes are applied only after the primary mode.
    assert activate.index('"set_hvac_mode"') < activate.index("_apply_secondary_settings")
    # And still before the activation is committed, so a genuine mode failure
    # continues to roll back.
    assert activate.index("_apply_secondary_settings") < activate.index("device.is_active = True")


def test_secondary_climate_attribute_fields_are_offered_only_when_entity_supports_them():
    helper = _method_body(CONFIG_FLOW, "def _secondary_options_for_entity", "# ── Config flow")
    # No fallback list here, unlike hvac_modes: guessing would offer values the
    # device is certain to reject. Absent attribute means omit the field entirely.
    assert "_FALLBACK_CLIMATE_MODES" not in helper
    assert "if not state" in helper
    assert "if not values" in helper
    assert helper.count("return None") >= 3
    # "Leave unchanged" must be the first option, so a capable device can still
    # be left unmanaged.
    assert "SECONDARY_UNSET, label=\"Leave unchanged\"" in helper

    step = _method_body(CONFIG_FLOW, "async def async_step_device_climate_mode", "# ── Remove device")
    assert '(CONF_DEVICE_FAN_MODE, "fan_modes", "fan speed")' in step
    assert '(CONF_DEVICE_SWING_MODE, "swing_modes", "vertical swing")' in step
    assert 'CONF_DEVICE_SWING_HORIZONTAL_MODE,' in step
    assert '"swing_horizontal_modes",' in step
    assert "if options is None" in step and "continue" in step
    assert "vol.Optional(conf_key, default=existing.get(conf_key, SECONDARY_UNSET))" in step

    for source in (STRINGS, TRANSLATIONS):
        fields = source["options"]["step"]["device_climate_mode"]
        assert "fan_mode" in fields["data"]
        assert "swing_mode" in fields["data"]
        assert "swing_horizontal_mode" in fields["data"]
        # Labels must distinguish the two axes: "Fan direction" is ambiguous.
        assert fields["data"]["swing_mode"].startswith("Vertical swing direction")
        assert fields["data"]["swing_horizontal_mode"].startswith("Horizontal swing direction")
        assert "fan_mode" in fields["data_description"]
        assert "swing_mode" in fields["data_description"]
        assert "swing_horizontal_mode" in fields["data_description"]


def test_mode_preset_and_setpoint_survive_a_restart():
    # Without RestoreEntity every restart reverted the room to Home/HEAT_COOL/21C,
    # which is enough on its own to start heating or cooling seconds after boot.
    assert "from homeassistant.helpers.restore_state import RestoreEntity" in CLIMATE
    assert "class ClimateComfortEntity(ClimateEntity, RestoreEntity):" in CLIMATE
    assert "await self._restore_previous_state()" in CLIMATE

    body = _method_body(CLIMATE, "async def _restore_previous_state", "def _adopt_house_mode")
    assert "await self.async_get_last_state()" in body
    assert "if last.state in self._attr_hvac_modes" in body
    assert 'last.attributes.get("preset_mode")' in body
    assert "last.attributes.get(ATTR_TEMPERATURE)" in body
    # A restored setpoint must be sanity-checked, not trusted blindly.
    assert "self._minimum_temperature <= restored <= self._maximum_temperature" in body
    # A restored preset wins over the house/floor selector; the selector is only
    # consulted when there is nothing to restore.
    assert "if last is None" in body
    assert body.index("if last is None") < body.index("_adopt_house_mode()")

    house = _method_body(CLIMATE, "def _adopt_house_mode", "async def async_added_to_hass")
    assert "self._house_mode_entity" in house
    assert "state.state not in self._attr_preset_modes" in house


def test_startup_sync_skips_entities_that_have_not_loaded_yet():
    body = _method_body(CLIMATE, "if not self._initial_sync_done:", "if self._hold_hours <= 0")
    # A device that has not loaded reads as "off". Syncing it would record every
    # running device as inactive, and turn its arrival into a manual override.
    assert "if self._entity_unavailable(device.entity_id)" in body
    assert "continue" in body
    assert "self._synced_entities.add(device.entity_id)" in body
    # The latch must not close while Home Assistant is still starting up.
    assert "if not self.hass.is_running" in body
    assert body.index("if not self.hass.is_running") < body.index("self._initial_sync_done = True")


def test_unavailable_devices_are_never_treated_as_manual_overrides():
    assert "def _entity_unavailable" in CLIMATE
    helper = _method_body(CLIMATE, "def _entity_unavailable", "def _device_is_on")
    assert "STATE_UNAVAILABLE" in helper and "STATE_UNKNOWN" in helper
    assert "state is None" in helper

    body = _method_body(CLIMATE, "def _check_manual_changes", "def _trigger_manual_hold")
    guard = body.split("checked.add(eid)", 1)[1]
    # Offline is not off: clear any mismatch in progress and stop judging.
    assert "if self._entity_unavailable(eid)" in guard
    assert "self._synced_entities.discard(eid)" in guard
    assert "self._manual_mismatch_seen.pop(eid, None)" in guard
    # An entity seen for the first time (late load, or back from an outage) is
    # adopted from actual state rather than blamed on the user.
    assert "if eid not in self._synced_entities" in guard
    assert "stage.is_active = self._device_matches_actual(stage)" in guard
    # Both guards must run before any hold can be triggered.
    assert guard.index("if self._entity_unavailable(eid)") < guard.index("_trigger_manual_hold")
    assert guard.index("if eid not in self._synced_entities") < guard.index("_trigger_manual_hold")
