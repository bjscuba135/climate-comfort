from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLIMATE = (ROOT / "custom_components/climate_comfort/climate.py").read_text()
SWITCH = (ROOT / "custom_components/climate_comfort/switch.py").read_text()
CONFIG_FLOW = (ROOT / "custom_components/climate_comfort/config_flow.py").read_text()


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
