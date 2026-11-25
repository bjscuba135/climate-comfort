"""Services for schedules: replace one, resume one, read one."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from . import schedule as sched
from .const import DOMAIN
from .scheduler import ScheduleController, get_manager

SERVICE_SET_SCHEDULE = "set_schedule"
SERVICE_RESUME_SCHEDULE = "resume_schedule"
SERVICE_GET_SCHEDULE = "get_schedule"

_TARGET = {vol.Required("entity_id"): cv.entity_ids}

SET_SCHEMA = vol.Schema(
    {
        **_TARGET,
        vol.Exclusive("schedule", "schedule"): cv.string,
        vol.Exclusive("profiles", "schedule"): list,
        vol.Optional("enable"): cv.boolean,
    }
)
TARGET_SCHEMA = vol.Schema(_TARGET)


def _controllers(hass: HomeAssistant, call: ServiceCall) -> list[ScheduleController]:
    """The schedules named by the call: by a room thermostat, a mode selector
    or any of a schedule's own entities."""
    manager = get_manager(hass)
    found: list[ScheduleController] = []
    for entity_id in call.data["entity_id"]:
        controller = manager.controller_for_entity(entity_id)
        if controller is None:
            raise ServiceValidationError(
                f"{entity_id} is not a Climate Comfort room, mode selector or schedule entity"
            )
        if controller not in found:
            found.append(controller)
    return found


async def _set_schedule(hass: HomeAssistant, call: ServiceCall) -> None:
    if "schedule" not in call.data and "profiles" not in call.data:
        raise ServiceValidationError("Give the schedule as text (schedule) or as a list (profiles)")
    try:
        profiles = (
            sched.parse_text(call.data["schedule"])
            if "schedule" in call.data
            else sched.from_dicts(call.data["profiles"])
        )
    except sched.ScheduleError as err:
        raise ServiceValidationError(str(err)) from err
    for controller in _controllers(hass, call):
        try:
            await controller.async_set_profiles(profiles)
        except sched.ScheduleError as err:
            raise ServiceValidationError(f"{controller.name}: {err}") from err
        if "enable" in call.data and call.data["enable"] != controller.enabled:
            await controller.async_set_enabled(call.data["enable"])


async def _resume_schedule(hass: HomeAssistant, call: ServiceCall) -> None:
    for controller in _controllers(hass, call):
        await controller.async_resume()


async def _get_schedule(hass: HomeAssistant, call: ServiceCall) -> ServiceResponse:
    result: dict[str, Any] = {}
    for controller in _controllers(hass, call):
        attrs = controller.attributes()
        result[controller.name] = {
            "enabled": controller.enabled,
            "schedule": attrs["schedule_text"],
            "profiles": attrs["profiles"],
            "next_change": controller.next_change.isoformat() if controller.next_change else None,
            "next_preset": controller.next_preset,
            "override": attrs["override"],
        }
    return result


def async_register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_SET_SCHEDULE):
        return

    async def set_schedule(call: ServiceCall) -> None:
        await _set_schedule(hass, call)

    async def resume_schedule(call: ServiceCall) -> None:
        await _resume_schedule(hass, call)

    async def get_schedule(call: ServiceCall) -> ServiceResponse:
        return await _get_schedule(hass, call)

    hass.services.async_register(DOMAIN, SERVICE_SET_SCHEDULE, set_schedule, schema=SET_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_RESUME_SCHEDULE, resume_schedule, schema=TARGET_SCHEMA)
    hass.services.async_register(
        DOMAIN, SERVICE_GET_SCHEDULE, get_schedule,
        schema=TARGET_SCHEMA, supports_response=SupportsResponse.ONLY,
    )
