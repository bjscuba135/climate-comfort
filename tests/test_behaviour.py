"""Behavioural tests: build the real thermostat and drive it.

These run against the stand-ins in conftest.py rather than Home Assistant
itself, so they prove the control logic, not the integration with core.
"""
from __future__ import annotations

import asyncio
import importlib
from datetime import datetime, timedelta, timezone

from conftest import PACKAGE, Entry, Hass, State, load_integration

package = load_integration()
climate = importlib.import_module(f"{PACKAGE}.climate")
binary_sensor = importlib.import_module(f"{PACKAGE}.binary_sensor")
const = importlib.import_module(f"{PACKAGE}.const")
DOMAIN = const.DOMAIN

TRV = {
    "id": "trv",
    "entity_id": "climate.trv",
    "label": "Radiator",
    "role": "heating",
    "activation_point": 0,
    "deactivate_offset": 0.5,
    "target_temp_offset": 3.0,
}
AIRCON = {
    "id": "ac",
    "entity_id": "climate.aircon",
    "label": "Aircon",
    "role": "cooling",
    "activation_point": 0,
    "deactivate_offset": 0.5,
    "target_temp_offset": 3.0,
}


class Event:
    def __init__(self, entity_id: str, old: str | None, new: str) -> None:
        self.data = {
            "entity_id": entity_id,
            "old_state": State(old) if old is not None else None,
            "new_state": State(new),
        }


def make_room(devices, room_data=None, global_data=None, hass=None):
    hass = hass or Hass()
    global_entry = Entry("global", {"entry_type": "global", **(global_data or {})})
    room_entry = Entry(
        "room",
        {
            "entry_type": "room",
            "name": "Lounge",
            "temperature_sensor": "sensor.lounge_temperature",
            "comfort_zone": 1.0,
            "use_global_presets": True,
            **(room_data or {}),
        },
        devices=devices,
    )
    hass.config_entries.entries = [global_entry, room_entry]
    hass.data[DOMAIN] = {"global": {}, "room": {}}
    for device in devices:
        hass.states.set(device["entity_id"], "off")
    entity = climate.ClimateComfortEntity(hass, room_entry)
    entity.entity_id = "climate.lounge"
    hass.data[DOMAIN]["room"]["climate_entity"] = entity
    return hass, entity, room_entry


def run(coro):
    return asyncio.run(coro)


# ── Restoring state ──────────────────────────────────────────────────────────


def test_restart_in_heat_mode_does_not_move_the_setpoint():
    """A heating-only room shows the lower threshold as its temperature.

    Restoring the setpoint from that attribute lowered the room by one comfort
    zone on every restart and reload.
    """

    async def scenario():
        _hass, entity, _ = make_room([TRV])
        assert entity._attr_hvac_modes == [climate.HVACMode.OFF, climate.HVACMode.HEAT]
        entity._attr_preset_mode = "none"
        entity._setpoint = 22.5
        entity._attr_hvac_mode = climate.HVACMode.HEAT
        # What Home Assistant would have stored for this entity:
        shown = entity.native_target_temperature
        assert shown == 21.5  # the lower threshold, not the setpoint
        stored = State(
            "heat",
            {"preset_mode": "none", "temperature": shown, **entity.extra_state_attributes},
        )

        _hass2, restored, _ = make_room([TRV])
        restored.last_state = stored
        await restored._restore_previous_state()
        assert restored._setpoint == 22.5
        assert restored.native_target_temperature == 21.5

    run(scenario())


def test_restored_preset_uses_its_current_configured_temperature():
    async def scenario():
        _hass, entity, _ = make_room([TRV], global_data={"mode_home": 20.0})
        entity.last_state = State(
            "heat",
            {"preset_mode": "home", "temperature": 20.0, "effective_setpoint": 21.0},
        )
        await entity._restore_previous_state()
        assert entity._attr_preset_mode == "home"
        assert entity._setpoint == 20.0

    run(scenario())


def test_restore_ignores_an_out_of_range_setpoint():
    async def scenario():
        _hass, entity, _ = make_room([TRV])
        entity.last_state = State(
            "heat", {"preset_mode": "none", "effective_setpoint": 99.0}
        )
        await entity._restore_previous_state()
        assert entity._setpoint == 21.0

    run(scenario())


# ── Settings ─────────────────────────────────────────────────────────────────


def test_comfort_zone_is_always_the_rooms_own_value():
    _hass, entity, _ = make_room(
        [TRV], room_data={"comfort_zone": 0.5}, global_data={"comfort_zone": 2.0}
    )
    assert entity._comfort_zone == 0.5
    assert entity._thresholds() == (20.5, 21.5)


def test_settings_change_applies_live():
    async def scenario():
        _hass, entity, entry = make_room([TRV], global_data={"mode_home": 21.0})
        assert entity._setpoint == 21.0
        entry.data = {**entry.data, "use_global_presets": False, "mode_home": 19.5}
        await entity.async_settings_updated()
        assert entity._setpoint == 19.5

    run(scenario())


def test_live_save_does_not_reload_but_other_changes_do():
    async def scenario():
        hass, _entity, entry = make_room([TRV])
        entry.update_listeners.append(package._async_update_options)

        changed = package.async_update_entry_live(
            hass, entry, data={**entry.data, "mode_home": 20.0}
        )
        await hass.settle()
        assert changed and hass.config_entries.reloaded == []

        # An update that changes nothing must not leave a marker behind that
        # would swallow the next real reload.
        package.async_update_entry_live(hass, entry, data=dict(entry.data))
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, "temperature_sensor": "sensor.other"}
        )
        await hass.settle()
        assert hass.config_entries.reloaded == ["room"]

    run(scenario())


def test_changing_global_defaults_reloads_every_room():
    async def scenario():
        hass, _entity, _ = make_room([TRV])
        global_entry = hass.config_entries.entries[0]
        global_entry.update_listeners.append(package._async_update_options)
        hass.config_entries.async_update_entry(global_entry, data={**global_entry.data, "mode_home": 20.0})
        await hass.settle()
        assert hass.config_entries.reloaded == ["global"]
        assert hass.config_entries.scheduled == ["room"]

    run(scenario())


# ── Device stage identity ────────────────────────────────────────────────────


def test_stage_ids_are_assigned_once_and_existing_sensors_follow():
    hass = Hass()
    entry = Entry(
        "room",
        {"entry_type": "room"},
        {"devices": [{"entity_id": "switch.a", "role": "heating"}, {"entity_id": "switch.b", "role": "heating"}]},
        version=1,
    )
    registry = hass.entity_registry
    registry.entities[("binary_sensor", DOMAIN, "room_device_0")] = "binary_sensor.lounge_a"
    registry.entities[("binary_sensor", DOMAIN, "room_device_1")] = "binary_sensor.lounge_b"

    assert package._assign_device_ids(hass, entry) is True
    ids = [d["id"] for d in entry.options["devices"]]
    assert len(set(ids)) == 2 and all(ids)
    assert registry.entities == {
        ("binary_sensor", DOMAIN, f"room_device_{ids[0]}"): "binary_sensor.lounge_a",
        ("binary_sensor", DOMAIN, f"room_device_{ids[1]}"): "binary_sensor.lounge_b",
    }
    # Second run is a no-op: ids are never regenerated.
    assert package._assign_device_ids(hass, entry) is False
    assert [d["id"] for d in entry.options["devices"]] == ids


def test_stage_sensor_keeps_its_name_and_reports_the_trigger_as_an_attribute():
    async def scenario():
        hass, entity, entry = make_room([TRV])
        sensor = binary_sensor.ControlledDeviceSensor(entry, climate._Device(TRV, 0))
        sensor.hass = hass
        hass.data[DOMAIN]["room"]["device_sensors"] = [sensor]
        entity._attr_native_current_temperature = 18.0
        await entity._evaluate_devices()

        assert sensor._attr_unique_id == "room_device_trv"
        assert sensor._attr_name == "Radiator"
        assert sensor.is_on is True
        assert sensor.extra_state_attributes["trigger_temperature"] == 20.0

        entity._trigger_manual_hold("climate.trv")
        entity._sync_binary_sensors()
        assert sensor._attr_name == "Radiator"
        assert sensor._attr_icon == "mdi:hand-back-right"
        assert sensor.extra_state_attributes["manual_override"] is True

    run(scenario())


# ── Control ──────────────────────────────────────────────────────────────────


def test_setpoint_change_reaches_a_stage_that_is_already_running():
    async def scenario():
        hass, entity, _ = make_room([TRV])
        entity._attr_native_current_temperature = 18.0
        await entity._evaluate_devices()
        assert hass.services.named("set_hvac_mode") == [
            {"entity_id": "climate.trv", "hvac_mode": "heat"}
        ]
        assert [c["temperature"] for c in hass.services.named("set_temperature")] == [24.0]

        # Heat mode: the card's handle is the lower threshold, so 21 → setpoint 22.
        await entity.async_set_temperature(temperature=21.0)
        assert entity._setpoint == 22.0
        assert [c["temperature"] for c in hass.services.named("set_temperature")] == [24.0, 25.0]

        # Nothing changed: no repeat calls.
        await entity._evaluate_devices()
        await entity._evaluate_devices()
        assert len(hass.services.named("set_temperature")) == 2
        assert len(hass.services.named("set_hvac_mode")) == 1

    run(scenario())


def test_overlapping_evaluations_are_folded_into_one():
    async def scenario():
        hass, entity, _ = make_room([TRV])
        entity._attr_native_current_temperature = 18.0
        reentered = []

        async def on_call(_domain, service, _data):
            if service == "set_hvac_mode":
                # The device's state change asks for another evaluation while
                # the first is still part-way through its service calls.
                reentered.append(entity._evaluating)
                await entity._evaluate_devices()
                await asyncio.sleep(0)

        hass.services.on_call = on_call
        await entity._evaluate_devices()

        assert reentered == [True]
        assert len(hass.services.named("set_hvac_mode")) == 1
        assert entity._evaluating is False
        assert entity.state_writes >= 1

    run(scenario())


def test_device_state_change_prompts_an_evaluation():
    async def scenario():
        hass, entity, _ = make_room([AIRCON], room_data={"manual_hold_confirm_seconds": 0})
        entity._attr_native_current_temperature = 21.0
        await entity._evaluate_devices()  # startup sync; nothing to do
        assert hass.services.calls == []

        # Attribute-only update: ignored.
        entity._handle_state_change(Event("climate.aircon", "off", "off"))
        assert hass.tasks == []

        # Someone switches the air conditioner on by hand.
        hass.states.set("climate.aircon", "cool")
        entity._handle_state_change(Event("climate.aircon", "off", "cool"))
        await hass.settle()
        assert "climate.aircon" in entity._manual_mismatch_seen

        # Still on at the next check: it becomes a manual hold, left alone.
        await entity._handle_tick()
        assert entity._is_in_manual_hold("climate.aircon")
        assert hass.services.calls == []

    run(scenario())


# ── Manual holds ─────────────────────────────────────────────────────────────


def test_manual_hold_survives_a_restart_with_its_original_end_time():
    async def scenario():
        _hass, entity, _ = make_room([TRV], room_data={"manual_hold_hours": 2.0})
        started = datetime.now(timezone.utc) - timedelta(minutes=30)
        entity._trigger_manual_hold("climate.trv", started)
        stored = entity.extra_restore_state_data

        hass2, restored, _ = make_room([TRV], room_data={"manual_hold_hours": 2.0})
        restored.last_extra_data = stored
        await restored._restore_manual_holds()
        assert restored._is_in_manual_hold("climate.trv")
        # 90 minutes left of the original two hours, not a fresh two hours.
        assert 5300 < hass2.timers[-1]["delay"] <= 5400

    run(scenario())


def test_expired_or_orphaned_holds_are_not_restored():
    async def scenario():
        _hass, entity, _ = make_room([TRV], room_data={"manual_hold_hours": 2.0})
        long_ago = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
        recent = datetime.now(timezone.utc).isoformat()
        entity.last_extra_data = climate._ComfortExtraData(
            {"climate.trv": long_ago, "climate.removed": recent}
        )
        await entity._restore_manual_holds()
        assert entity._manual_holds == {}

    run(scenario())


def test_reset_button_path_ends_holds_and_cancels_their_timers():
    async def scenario():
        hass, entity, _ = make_room([TRV])
        entity._attr_native_current_temperature = 21.0
        entity._trigger_manual_hold("climate.trv")
        cleared = await entity.async_clear_manual_holds()
        assert cleared == ["climate.trv"]
        assert not entity._is_in_manual_hold("climate.trv")
        assert hass.timers[-1]["cancelled"] is True

    run(scenario())


def test_thermostat_off_does_not_resend_off_to_devices_that_are_off():
    async def scenario():
        hass, entity, _ = make_room([TRV])
        entity._attr_native_current_temperature = 18.0
        await entity._evaluate_devices()
        await entity.async_set_hvac_mode(climate.HVACMode.OFF)
        offs = [c for c in hass.services.named("set_hvac_mode") if c["hvac_mode"] == "off"]
        assert len(offs) == 1

        # Timer ticks while off: the radiator is already off, so nothing is sent.
        await entity._handle_tick()
        await entity._handle_tick()
        offs = [c for c in hass.services.named("set_hvac_mode") if c["hvac_mode"] == "off"]
        assert len(offs) == 1

        # If it is found running while the thermostat is off, it is switched off.
        hass.states.set("climate.trv", "heat")
        await entity._handle_tick()
        offs = [c for c in hass.services.named("set_hvac_mode") if c["hvac_mode"] == "off"]
        assert len(offs) == 2

    run(scenario())


# ── Version 2: devices as subentries ─────────────────────────────────────────


def test_version_1_device_list_becomes_subentries_and_sensors_are_kept():
    async def scenario():
        hass = Hass()
        entry = Entry(
            "room",
            {"entry_type": "room", "name": "Lounge"},
            {
                "devices": [
                    {"entity_id": "climate.trv", "label": "Radiator", "role": "heating", "activation_point": 0},
                    {"entity_id": "switch.fan", "label": "Fan", "role": "cooling", "activation_point": 2},
                ],
                "other": "kept",
            },
            version=1,
        )
        registry = hass.entity_registry
        registry.entities[("binary_sensor", DOMAIN, "room_device_0")] = "binary_sensor.lounge_radiator"
        registry.entities[("binary_sensor", DOMAIN, "room_device_1")] = "binary_sensor.lounge_fan"

        assert await package.async_migrate_entry(hass, entry) is True
        assert entry.version == 2
        assert entry.options == {"other": "kept"}

        devices = package.get_device_configs(entry)
        assert [d["label"] for d in devices] == ["Radiator", "Fan"]
        assert [s.title for s in entry.subentries.values()] == ["Radiator", "Fan"]
        # The sensors follow their device onto its permanent id.
        assert registry.entities == {
            ("binary_sensor", DOMAIN, f"room_device_{devices[0]['id']}"): "binary_sensor.lounge_radiator",
            ("binary_sensor", DOMAIN, f"room_device_{devices[1]['id']}"): "binary_sensor.lounge_fan",
        }

        # Running it again changes nothing.
        assert await package.async_migrate_entry(hass, entry) is True
        assert len(entry.subentries) == 2

    run(scenario())


def test_migration_refuses_an_entry_from_a_newer_release():
    async def scenario():
        entry = Entry("room", {"entry_type": "room"}, version=3)
        assert await package.async_migrate_entry(Hass(), entry) is False

    run(scenario())


def test_deleting_a_device_removes_its_sensor_but_no_others():
    hass, _entity, entry = make_room([TRV, AIRCON])
    registry = hass.entity_registry
    registry.entities = {
        ("binary_sensor", DOMAIN, "room_device_trv"): "binary_sensor.lounge_radiator",
        ("binary_sensor", DOMAIN, "room_device_ac"): "binary_sensor.lounge_aircon",
        ("binary_sensor", DOMAIN, "room_device_gone"): "binary_sensor.lounge_old_heater",
        ("binary_sensor", DOMAIN, "room_manual_control"): "binary_sensor.lounge_manual_control",
    }
    package._remove_orphaned_stage_sensors(hass, entry)
    assert sorted(registry.entities.values()) == [
        "binary_sensor.lounge_aircon",
        "binary_sensor.lounge_manual_control",
        "binary_sensor.lounge_radiator",
    ]


def test_thermostat_publishes_its_stages_for_the_card():
    async def scenario():
        hass, entity, _ = make_room([TRV, AIRCON])
        hass.entity_registry.entities[("select", DOMAIN, "room_aggressiveness")] = "select.lounge_aggressiveness"
        entity._attr_native_current_temperature = 18.0
        await entity._evaluate_devices()

        attrs = entity.extra_state_attributes
        assert attrs["aggressiveness_entity"] == "select.lounge_aggressiveness"
        assert attrs["stages"] == [
            {
                "id": "trv", "label": "Radiator", "kind": "heating", "threshold": 20.0,
                "active": True, "manual": False, "min_time_wait": None, "entity_id": "climate.trv", "hvac_mode": "heat",
            },
            {
                "id": "ac", "label": "Aircon", "kind": "cooling", "threshold": 22.0,
                "active": False, "manual": False, "min_time_wait": None, "entity_id": "climate.aircon", "hvac_mode": "cool",
            },
        ]
        assert {"stages", "manual_holds"} <= entity._unrecorded_attributes

    run(scenario())


# ── Minimum on / off times ───────────────────────────────────────────────────


def _minutes_ago(entity, entity_id, minutes):
    """Pretend the device last switched this many minutes ago."""
    entity._last_switched[entity_id] = datetime.now(timezone.utc) - timedelta(minutes=minutes)


def test_minimum_on_and_off_times_hold_a_compressor_in_its_state():
    async def scenario():
        ac = {**AIRCON, "min_on_minutes": 5, "min_off_minutes": 3}
        hass, entity, _ = make_room(
            [TRV, ac], room_data={"manual_hold_confirm_seconds": 0}
        )
        entity._attr_native_current_temperature = 23.0
        await entity._evaluate_devices()
        assert hass.states.get("climate.aircon").state == "cool"
        assert entity._last_switched["climate.aircon"] is not None

        # Cool enough to stop, but it has only just started: it keeps running,
        # still counts as cooling, and is not mistaken for a manual change.
        entity._attr_native_current_temperature = 21.0
        await entity._evaluate_devices()
        await entity._handle_tick()
        assert hass.states.get("climate.aircon").state == "cool"
        assert entity._attr_hvac_action == climate.HVACAction.COOLING
        assert not entity._is_in_manual_hold("climate.aircon")
        stage = next(s for s in entity.extra_state_attributes["stages"] if s["id"] == "ac")
        assert stage["min_time_wait"]["action"] == "off"
        assert "climate.aircon" in entity.extra_state_attributes["min_time_waits"]

        # Once the minimum on time has passed it stops.
        _minutes_ago(entity, "climate.aircon", 6)
        await entity._evaluate_devices()
        assert hass.states.get("climate.aircon").state == "off"

        # Hot again straight away: it must rest first.
        entity._attr_native_current_temperature = 23.0
        await entity._evaluate_devices()
        await entity._handle_tick()
        assert hass.states.get("climate.aircon").state == "off"
        assert not entity._is_in_manual_hold("climate.aircon")
        assert entity.extra_state_attributes["min_time_waits"]["climate.aircon"]["action"] == "on"

        _minutes_ago(entity, "climate.aircon", 4)
        await entity._evaluate_devices()
        assert hass.states.get("climate.aircon").state == "cool"
        assert "min_time_waits" not in entity.extra_state_attributes

    run(scenario())


def test_turning_the_thermostat_off_or_changing_its_mode_is_not_held():
    async def scenario():
        ac = {**AIRCON, "min_on_minutes": 30}
        hass, entity, _ = make_room([TRV, ac])
        entity._attr_native_current_temperature = 23.0
        await entity._evaluate_devices()
        assert hass.states.get("climate.aircon").state == "cool"

        # Heat only: the person no longer wants cooling, so it stops at once.
        await entity.async_set_hvac_mode(climate.HVACMode.HEAT)
        assert hass.states.get("climate.aircon").state == "off"

        await entity.async_set_hvac_mode(climate.HVACMode.HEAT_COOL)
        _minutes_ago(entity, "climate.aircon", 60)
        await entity._evaluate_devices()
        assert hass.states.get("climate.aircon").state == "cool"

        await entity.async_set_hvac_mode(climate.HVACMode.OFF)
        assert hass.states.get("climate.aircon").state == "off"

    run(scenario())


def test_a_switch_made_by_hand_starts_the_minimum_off_time():
    async def scenario():
        fan = {
            "id": "fan", "entity_id": "switch.fan", "label": "Fan", "role": "cooling",
            "activation_point": 0, "deactivate_offset": 0.5, "min_off_minutes": 3,
        }
        hass, entity, _ = make_room([fan])
        entity._attr_native_current_temperature = 21.0
        await entity._evaluate_devices()

        # Someone switches it on and off again by hand.
        entity._handle_state_change(Event("switch.fan", "off", "on"))
        entity._handle_state_change(Event("switch.fan", "on", "off"))
        hass.tasks.clear()

        entity._attr_native_current_temperature = 23.0
        await entity._evaluate_devices()
        assert hass.states.get("switch.fan").state == "off"

        _minutes_ago(entity, "switch.fan", 4)
        await entity._evaluate_devices()
        assert hass.states.get("switch.fan").state == "on"

    run(scenario())


def test_no_minimum_times_by_default():
    async def scenario():
        hass, entity, _ = make_room([TRV, AIRCON])
        entity._attr_native_current_temperature = 23.0
        await entity._evaluate_devices()
        entity._attr_native_current_temperature = 21.0
        await entity._evaluate_devices()
        entity._attr_native_current_temperature = 23.0
        await entity._evaluate_devices()
        modes = [c["hvac_mode"] for c in hass.services.named("set_hvac_mode")
                 if c["entity_id"] == "climate.aircon"]
        assert modes == ["cool", "off", "cool"]

    run(scenario())


def test_heating_does_not_start_while_a_held_cooler_is_still_running():
    async def scenario():
        ac = {**AIRCON, "min_on_minutes": 5}
        heater = {
            "id": "heater", "entity_id": "switch.heater", "label": "Heater", "role": "heating",
            "activation_point": 0, "deactivate_offset": 0.5,
        }
        hass, entity, _ = make_room([heater, ac])
        entity._attr_native_current_temperature = 23.0
        await entity._evaluate_devices()
        assert hass.states.get("climate.aircon").state == "cool"

        # The room drops to needing heat while the AC is held on: the heater waits.
        entity._attr_native_current_temperature = 19.0
        await entity._evaluate_devices()
        assert hass.states.get("climate.aircon").state == "cool"
        assert hass.states.get("switch.heater").state == "off"

        # Once the AC may stop, it stops, and the heater starts at the next check.
        _minutes_ago(entity, "climate.aircon", 6)
        await entity._evaluate_devices()
        assert hass.states.get("climate.aircon").state == "off"
        await entity._evaluate_devices()
        assert hass.states.get("switch.heater").state == "on"

    run(scenario())
