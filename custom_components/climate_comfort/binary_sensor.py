from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import get_device_configs
from .climate import _Device
from .const import (
    DOMAIN,
    ROLE_COOLING,
    ROLE_DEHUMIDIFY,
    ROLE_HEATING,
)

_ROLE_ICONS = {
    ROLE_HEATING: "mdi:radiator",
    ROLE_COOLING: "mdi:snowflake",
    ROLE_DEHUMIDIFY: "mdi:water-percent",
}

_ROLE_LABELS = {
    ROLE_HEATING: "Heating",
    ROLE_COOLING: "Cooling",
    ROLE_DEHUMIDIFY: "Dehumidifier",
}


def _device_activation_offset(device: "_Device", point_spacing: float | None) -> float:
    if device.activation_point is None or point_spacing is None:
        return device.activate_offset
    return abs(device.activation_point) * point_spacing


def _device_trigger_temperature(
    device: "_Device",
    lt: float | None,
    ut: float | None,
    point_spacing: float | None = None,
) -> float | None:
    """Temperature at which a heating or cooling stage switches on."""
    if device.role == ROLE_DEHUMIDIFY or lt is None or ut is None:
        return None
    offset = _device_activation_offset(device, point_spacing)
    if device.role == ROLE_COOLING:
        return round(ut + offset, 2)
    return round(lt - offset, 2)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    devices_data = get_device_configs(entry)
    device_sensors = [
        ControlledDeviceSensor(entry, _Device(d, idx))
        for idx, d in enumerate(devices_data)
    ]
    manual_control_sensor = ManualControlSensor(entry)
    entry_data = hass.data[DOMAIN][entry.entry_id]
    entry_data["device_sensors"] = device_sensors
    entry_data["manual_control_sensor"] = manual_control_sensor

    async_add_entities([*device_sensors, manual_control_sensor])


class ManualControlSensor(BinarySensorEntity):
    """Expose whether a room has an active manual-control hold."""

    _attr_should_poll = False
    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_has_entity_name = True
    _attr_name = "Manual Control"
    _attr_icon = "mdi:hand-back-right"

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_manual_control"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
        )

    @property
    def is_on(self) -> bool:
        climate = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {}).get("climate_entity")
        return bool(climate and climate._manual_holds)

    @property
    def extra_state_attributes(self) -> dict:
        climate = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {}).get("climate_entity")
        return climate.manual_control_attributes() if climate else {}


class ControlledDeviceSensor(BinarySensorEntity):
    """
    Diagnostic sensor for one device managed by a Climate Comfort room.

    Appears on the room's device page alongside the thermostat entity.
    State: Running (device is currently active) / Idle.
    Attributes include the current computed trigger temperatures so you can
    see at a glance when each device will switch on or off.

    The name is the stage's label and never changes. It used to carry the
    trigger temperature and a "(Manual)" marker, which renamed the entity every
    time the setpoint moved; those now live in the attributes and the icon.
    """

    _attr_should_poll = False
    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True

    def __init__(self, entry: ConfigEntry, device: _Device) -> None:
        self._entry = entry
        self._device = device

        # Built from the stage's stable id, not its position in the list, so
        # removing a stage leaves every other sensor on its own history.
        self._attr_unique_id = f"{entry.entry_id}_device_{device.id}"
        self._attr_name = device.label
        self._attr_icon = _ROLE_ICONS.get(device.role, "mdi:power")

        # Grouped with the climate entity on the room's device page
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
        )

    async def async_added_to_hass(self) -> None:
        self.refresh()
        self.async_write_ha_state()

    @callback
    def async_entity_id_changed(self, old_entity_id: str) -> None:
        super().async_entity_id_changed(old_entity_id)

    def refresh(self) -> None:
        """Show a hand icon while this stage's device is in a manual hold."""
        entry_data = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {})
        if self._device.entity_id in entry_data.get("manual_holds", {}):
            self._attr_icon = "mdi:hand-back-right"
        else:
            self._attr_icon = _ROLE_ICONS.get(self._device.role, "mdi:power")

    @property
    def is_on(self) -> bool:
        states: dict = (
            self.hass.data.get(DOMAIN, {})
            .get(self._entry.entry_id, {})
            .get("device_states", {})
        )
        return bool(states.get(self._attr_unique_id, False))

    @property
    def extra_state_attributes(self) -> dict:
        d = self._device
        thresholds: dict = (
            self.hass.data.get(DOMAIN, {})
            .get(self._entry.entry_id, {})
            .get("thresholds", {})
        )
        lt = thresholds.get("lt")
        ut = thresholds.get("ut")
        preset = thresholds.get("preset", "")
        point_spacing = thresholds.get("point_spacing")

        attrs: dict = {}

        if d.role in (ROLE_HEATING, ROLE_COOLING):
            if lt is not None and ut is not None:
                offset = _device_activation_offset(d, point_spacing)
                attrs["trigger_temperature"] = _device_trigger_temperature(
                    d, lt, ut, point_spacing
                )
                if d.role == ROLE_HEATING:
                    activate_at = lt - offset
                    deactivate_at = activate_at + d.deactivate_offset
                    attrs["activates_below"] = f"{activate_at:.1f} °C"
                    attrs["deactivates_above"] = f"{deactivate_at:.1f} °C"
                else:
                    activate_at = ut + offset
                    deactivate_at = activate_at - d.deactivate_offset
                    attrs["activates_above"] = f"{activate_at:.1f} °C"
                    attrs["deactivates_below"] = f"{deactivate_at:.1f} °C"
                if preset:
                    attrs["active_preset"] = preset

            # Config values — useful but secondary to trigger temps
            if d.activation_point is None:
                attrs["offset_beyond_boundary"] = f"{d.activate_offset} °C"
            else:
                attrs["activation_point"] = d.activation_point
                if point_spacing is not None:
                    attrs["offset_beyond_boundary"] = (
                        f"{_device_activation_offset(d, point_spacing):.1f} °C"
                    )
            attrs["hysteresis"] = f"{d.deactivate_offset} °C"
            if d.hvac_mode_on:
                attrs["hvac_mode_when_active"] = d.hvac_mode_on
            if d.target_temp_offset is not None:
                direction = "above setpoint" if d.role == ROLE_HEATING else "below setpoint"
                attrs["target_overshoot"] = f"{d.target_temp_offset} °C {direction}"

        elif d.role == ROLE_DEHUMIDIFY:
            attrs["activates_above_humidity"] = f"{d.humidity_threshold:.0f} %"
            attrs["deactivates_below_humidity"] = (
                f"{d.humidity_threshold - d.humidity_hysteresis:.0f} %"
            )
            attrs["only_when_temperature_idle"] = d.dehumidify_only_when_idle

        # Manual override status
        entry_data = (
            self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {})
        )
        holds = entry_data.get("manual_holds", {})
        if d.entity_id in holds:
            hold = holds[d.entity_id]
            from datetime import timedelta
            import homeassistant.util.dt as dt_util
            resume_at = hold["since"] + timedelta(
                hours=entry_data.get("hold_hours", 2.0)
            )
            remaining_min = max(0, int((resume_at - dt_util.utcnow()).total_seconds() / 60))
            attrs["manual_override"] = True
            attrs["automated_control_resumes_in"] = f"{remaining_min} min"
        else:
            attrs["manual_override"] = False

        # Always last — reference info
        attrs["controlled_entity"] = d.entity_id
        attrs["role"] = _ROLE_LABELS.get(d.role, d.role)

        return attrs
