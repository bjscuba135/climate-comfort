"""Minimal stand-ins for Home Assistant, so the control logic can be exercised.

The static tests in this folder only check that certain lines exist. These
stubs let the behavioural tests construct the real thermostat class and drive
it, without installing Home Assistant (which CI does not, and which does not
install cleanly on every platform). They model only what the integration
touches; they are not a general-purpose fake.
"""
from __future__ import annotations

import asyncio
import enum
import importlib.util
import sys
import types
from dataclasses import dataclass, field
from datetime import datetime, timezone
from itertools import count
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = ROOT / "custom_components" / "climate_comfort"
PACKAGE = "climate_comfort_under_test"


def _module(name: str, **attrs) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__dict__.update(attrs)
    sys.modules[name] = module
    return module


class _Entity:
    hass = None
    entity_id = None
    _attr_available = True

    def __init__(self) -> None:
        self.state_writes = 0

    def async_write_ha_state(self) -> None:
        self.state_writes = getattr(self, "state_writes", 0) + 1

    def async_on_remove(self, func) -> None:
        self.__dict__.setdefault("_on_remove", []).append(func)

    def async_entity_id_changed(self, old_entity_id: str) -> None:
        return None


class _ClimateEntity(_Entity):
    pass


class _BinarySensorEntity(_Entity):
    pass


class _RestoreEntity(_Entity):
    last_state = None
    last_extra_data = None

    async def async_get_last_state(self):
        return self.last_state

    async def async_get_last_extra_data(self):
        return self.last_extra_data


class _ExtraStoredData:
    def as_dict(self):
        raise NotImplementedError


class _HVACMode(str, enum.Enum):
    OFF = "off"
    HEAT = "heat"
    COOL = "cool"
    HEAT_COOL = "heat_cool"


class _HVACAction(str, enum.Enum):
    OFF = "off"
    IDLE = "idle"
    HEATING = "heating"
    COOLING = "cooling"
    DRYING = "drying"


class _ClimateEntityFeature(enum.IntFlag):
    TARGET_TEMPERATURE = 1
    TARGET_TEMPERATURE_RANGE = 2
    PRESET_MODE = 16


class _UnitOfTemperature(str, enum.Enum):
    CELSIUS = "°C"


class _BinarySensorDeviceClass(str, enum.Enum):
    RUNNING = "running"


class _EntityCategory(str, enum.Enum):
    CONFIG = "config"
    DIAGNOSTIC = "diagnostic"


_subentry_ids = count(1)


@dataclass(frozen=True, kw_only=True)
class ConfigSubentry:
    """Same shape as Home Assistant's: only subentry_id has a default."""

    data: dict
    subentry_type: str
    title: str
    unique_id: str | None
    subentry_id: str = field(default_factory=lambda: f"sub{next(_subentry_ids)}")


def _passthrough(func):
    return func


def _track(hass, *_args, **_kwargs):
    cancelled = {"done": False}

    def _cancel() -> None:
        cancelled["done"] = True

    hass.tracked.append((_args, cancelled))
    return _cancel


def _call_later(hass, delay, action):
    record = {"delay": delay, "action": action, "cancelled": False}
    hass.timers.append(record)

    def _cancel() -> None:
        record["cancelled"] = True

    return _cancel


def install_stubs() -> None:
    if "homeassistant" in sys.modules:
        return
    _module("homeassistant")
    _module("homeassistant.util")
    _module(
        "homeassistant.util.dt",
        utcnow=lambda: datetime.now(timezone.utc),
        parse_datetime=lambda value: datetime.fromisoformat(value),
    )
    _module("homeassistant.components")
    _module(
        "homeassistant.components.climate",
        ClimateEntity=_ClimateEntity,
        ClimateEntityFeature=_ClimateEntityFeature,
        HVACAction=_HVACAction,
        HVACMode=_HVACMode,
        ATTR_TARGET_TEMP_HIGH="target_temp_high",
        ATTR_TARGET_TEMP_LOW="target_temp_low",
    )
    _module("homeassistant.components.climate.const", PRESET_NONE="none")
    _module(
        "homeassistant.components.binary_sensor",
        BinarySensorDeviceClass=_BinarySensorDeviceClass,
        BinarySensorEntity=_BinarySensorEntity,
    )
    _module("homeassistant.config_entries", ConfigEntry=object, ConfigSubentry=ConfigSubentry)
    _module(
        "homeassistant.const",
        ATTR_TEMPERATURE="temperature",
        STATE_UNAVAILABLE="unavailable",
        STATE_UNKNOWN="unknown",
        UnitOfTemperature=_UnitOfTemperature,
        EntityCategory=_EntityCategory,
    )
    _module("homeassistant.core", HomeAssistant=object, callback=_passthrough)
    _module("homeassistant.exceptions", HomeAssistantError=Exception)
    _module("homeassistant.helpers")
    _module("homeassistant.helpers.device_registry", DeviceInfo=dict)
    _module("homeassistant.helpers.entity_platform", AddEntitiesCallback=object)
    _module(
        "homeassistant.helpers.entity_registry",
        async_get=lambda hass: hass.entity_registry,
        async_entries_for_config_entry=lambda registry, entry_id: registry.for_entry(entry_id),
    )
    sys.modules["homeassistant.helpers"].entity_registry = sys.modules[
        "homeassistant.helpers.entity_registry"
    ]
    _module(
        "homeassistant.helpers.event",
        async_call_later=_call_later,
        async_track_state_change_event=_track,
        async_track_time_interval=_track,
    )
    _module(
        "homeassistant.helpers.restore_state",
        ExtraStoredData=_ExtraStoredData,
        RestoreEntity=_RestoreEntity,
    )


def load_integration():
    """Import the integration package from its repository folder."""
    install_stubs()
    if PACKAGE in sys.modules:
        return sys.modules[PACKAGE]
    spec = importlib.util.spec_from_file_location(
        PACKAGE,
        PACKAGE_DIR / "__init__.py",
        submodule_search_locations=[str(PACKAGE_DIR)],
    )
    package = importlib.util.module_from_spec(spec)
    sys.modules[PACKAGE] = package
    spec.loader.exec_module(package)
    return package


# ── Fake Home Assistant ──────────────────────────────────────────────────────


class State:
    def __init__(self, state: str, attributes: dict | None = None) -> None:
        self.state = state
        self.attributes = attributes or {}


class Entry:
    def __init__(
        self,
        entry_id: str,
        data: dict,
        options: dict | None = None,
        devices: list[dict] | None = None,
        version: int = 2,
    ) -> None:
        self.entry_id = entry_id
        self.title = data.get("name", entry_id)
        self.data = data
        self.options = options or {}
        self.version = version
        self.subentries: dict[str, ConfigSubentry] = {}
        self.update_listeners: list = []
        for device in devices or []:
            self.add_device(device)

    def add_device(self, device: dict) -> ConfigSubentry:
        subentry = ConfigSubentry(
            data=dict(device),
            subentry_type="device",
            title=device.get("label", ""),
            unique_id=None,
        )
        self.subentries[subentry.subentry_id] = subentry
        return subentry


class _States:
    def __init__(self) -> None:
        self._states: dict[str, State] = {}

    def get(self, entity_id: str):
        return self._states.get(entity_id)

    def set(self, entity_id: str, state: str, attributes: dict | None = None) -> None:
        self._states[entity_id] = State(state, attributes)


class _Services:
    """Records service calls and applies their obvious effect to the states."""

    def __init__(self, hass) -> None:
        self._hass = hass
        self.calls: list[tuple[str, str, dict]] = []
        self.on_call = None  # optional async hook(domain, service, data)

    async def async_call(self, domain, service, data, blocking=False) -> None:
        self.calls.append((domain, service, dict(data)))
        entity_id = data["entity_id"]
        if service == "set_hvac_mode":
            self._hass.states.set(entity_id, data["hvac_mode"])
        elif service in ("turn_on", "turn_off"):
            self._hass.states.set(entity_id, "on" if service == "turn_on" else "off")
        if self.on_call is not None:
            await self.on_call(domain, service, data)

    def named(self, service: str) -> list[dict]:
        return [data for _domain, name, data in self.calls if name == service]


class _ConfigEntries:
    def __init__(self, hass) -> None:
        self._hass = hass
        self.entries: list[Entry] = []
        self.reloaded: list[str] = []
        self.scheduled: list[str] = []

    def async_entries(self, _domain=None) -> list[Entry]:
        return list(self.entries)

    def async_add_subentry(self, entry, subentry) -> bool:
        entry.subentries[subentry.subentry_id] = subentry
        return True

    def async_update_entry(self, entry, *, data=None, options=None, version=None) -> bool:
        changed = False
        if version is not None and version != entry.version:
            entry.version = version
            changed = True
        if data is not None and data != entry.data:
            entry.data = data
            changed = True
        if options is not None and options != entry.options:
            entry.options = options
            changed = True
        if changed:
            for listener in entry.update_listeners:
                self._hass.async_create_task(listener(self._hass, entry))
        return changed

    async def async_reload(self, entry_id: str) -> None:
        self.reloaded.append(entry_id)

    def async_schedule_reload(self, entry_id: str) -> None:
        self.scheduled.append(entry_id)


@dataclass
class RegistryEntry:
    entity_id: str
    domain: str
    unique_id: str


class _EntityRegistry:
    def __init__(self) -> None:
        # (platform domain, integration domain, unique_id) -> entity_id
        self.entities: dict[tuple[str, str, str], str] = {}

    def async_get_entity_id(self, domain, platform, unique_id):
        return self.entities.get((domain, platform, unique_id))

    def for_entry(self, _entry_id):
        return [
            RegistryEntry(entity_id=entity_id, domain=key[0], unique_id=key[2])
            for key, entity_id in self.entities.items()
        ]

    def async_remove(self, entity_id) -> None:
        for key, value in list(self.entities.items()):
            if value == entity_id:
                del self.entities[key]

    def async_update_entity(self, entity_id, *, new_unique_id) -> None:
        for key, value in list(self.entities.items()):
            if value == entity_id:
                del self.entities[key]
                self.entities[(key[0], key[1], new_unique_id)] = entity_id


class Hass:
    def __init__(self) -> None:
        self.data: dict = {}
        self.is_running = True
        self.states = _States()
        self.services = _Services(self)
        self.config_entries = _ConfigEntries(self)
        self.entity_registry = _EntityRegistry()
        self.tracked: list = []
        self.timers: list = []
        self.tasks: list = []

    def async_create_task(self, coro):
        task = asyncio.ensure_future(coro)
        self.tasks.append(task)
        return task

    async def settle(self) -> None:
        """Run until every task the integration spawned has finished."""
        while self.tasks:
            pending, self.tasks = self.tasks, []
            await asyncio.gather(*pending)
