import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = ROOT / "custom_components/climate_comfort"
CLIMATE = (REPOSITORY_ROOT / "climate.py").read_text()
SWITCH = (REPOSITORY_ROOT / "switch.py").read_text()
CONFIG_FLOW = (REPOSITORY_ROOT / "config_flow.py").read_text()
CONST = (REPOSITORY_ROOT / "const.py").read_text()
SELECT = (REPOSITORY_ROOT / "select.py").read_text()
README = (ROOT / "README.md").read_text()
STRINGS = json.loads((REPOSITORY_ROOT / "strings.json").read_text())
TRANSLATIONS = json.loads((REPOSITORY_ROOT / "translations/en.json").read_text())
MANIFEST = json.loads((REPOSITORY_ROOT / "manifest.json").read_text())


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


def test_fixed_mode_and_profile_names_do_not_overlap():
    assert 'MODE_HOME = "home"' in CONST
    assert 'MODE_WARMUP = "warmup"' in CONST
    assert 'MODE_COOLDOWN = "cooldown"' in CONST
    assert 'PROFILE_BALANCED = "balanced"' in CONST
    assert 'PROFILE_AGGRESSIVE = "aggressive"' in CONST
    assert '"boost"' not in SELECT.split("HOUSE_MODE_OPTIONS", 1)[1].split("]", 1)[0]


def test_global_profile_settings_are_required_and_one_decimal_place():
    assert "CONF_PROFILE_BALANCED_COMFORT_MULTIPLIER" in CONST
    assert "CONF_PROFILE_BALANCED_POINT_SPACING" in CONST
    assert "step=0.1" in CONFIG_FLOW
    assert 'CONF_DEFAULT_PROFILE = "default_profile"' in CONST
    assert 'CONF_MINIMUM_TEMPERATURE = "minimum_temperature"' in CONST
    assert 'CONF_MAXIMUM_TEMPERATURE = "maximum_temperature"' in CONST
    assert "DEFAULT_TEMP_STEP = 0.1" in CONST


def test_new_room_setup_requires_global_defaults_and_uses_modes_not_legacy_presets():
    room_body = _method_body(CONFIG_FLOW, "async def async_step_room", "# ── Global defaults path")
    assert 'global_defaults_required' in room_body
    assert "CONF_MODE_HOME" in room_body
    assert "CONF_MODE_COOLDOWN" in room_body
    assert "CONF_PRESET_ECO" not in room_body
    assert "async_step_presets" not in CONFIG_FLOW


def test_room_options_offer_local_aggressiveness_without_local_mode_temperature_overrides():
    menu_body = _method_body(CONFIG_FLOW, "async def async_step_init", "# ── Global defaults edit")
    settings_body = _method_body(CONFIG_FLOW, "async def async_step_edit_settings", "# ── Save")
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
    assert "edit_global_modes" in TRANSLATIONS["options"]["step"]
    assert "mode_home" in TRANSLATIONS["options"]["step"]["edit_global_modes"]["data"]

    modes_body = _method_body(CONFIG_FLOW, "async def async_step_edit_global_modes", "async def async_step_edit_global_profiles")
    assert "_mode_schema(cfg)" in modes_body
    assert "async_update_entry" in modes_body


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
    init_text = (REPOSITORY_ROOT / "__init__.py").read_text()
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


def test_device_activation_points_are_role_limited_selects():
    body = _method_body(CONFIG_FLOW, "async def async_step_device_temp_config", "# ── Step 2b")
    assert "_activation_point_selector" in body
    assert "ROLE_HEATING" in body
    assert "-5" in body and "0" in body and "5" in body
    activation_field = body.split("CONF_DEVICE_ACTIVATION_POINT", 1)[1].split("CONF_DEVICE_DEACTIVATE_OFFSET", 1)[0]
    assert "_activation_point_selector" in activation_field
    assert "NumberSelector" not in activation_field


def test_emergency_enabled_device_flag_is_collected_and_used_for_safety_limits():
    assert 'CONF_DEVICE_EMERGENCY_ENABLED = "emergency_enabled"' in CONST
    assert "CONF_DEVICE_EMERGENCY_ENABLED" in CONFIG_FLOW
    assert "emergency_enabled" in CLIMATE
    assert "minimum_temperature" in CLIMATE
    assert "maximum_temperature" in CLIMATE


def test_hacs_metadata_declares_single_installable_comfort_climate_integration():
    hacs_path = ROOT / "hacs.json"
    assert hacs_path.exists()
    hacs = json.loads(hacs_path.read_text())
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


def test_repository_package_installs_as_comfort_climate_for_existing_config_entries():
    assert REPOSITORY_ROOT.exists()
    assert (REPOSITORY_ROOT / "__init__.py").exists()
    assert CONST.startswith('DOMAIN = "comfort_climate"')
    assert "legacy_domain" not in CONFIG_FLOW

    for platform in ["binary_sensor", "button", "climate", "number", "select", "switch"]:
        assert (REPOSITORY_ROOT / f"{platform}.py").exists()
