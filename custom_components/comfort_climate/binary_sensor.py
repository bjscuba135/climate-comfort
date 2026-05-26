from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .climate import _Device
from .const import (
    CONF_DEVICES,
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


def _device_name_with_trigger(device: "_Device", lt: float | None, ut: float | None) -> str:
    """
    Build the entity name using the actual trigger temperature / humidity so
    it reads like the dehumidifier entry already does:

      Aircon - Cool (>26.5 °C)  — cooling fires above 26.5 °C
      Aircon - Heat (<10.5 °C)  — heating fires below 10.5 °C
      Fan (>23.5 °C)            — fan fires above 23.5 °C (offset 0)
      Aircon - Dry (>65 %)      — dehumidifier fires above 65 % RH

    Falls back to the plain label when thresholds aren't available yet.
    """
    if device.role == ROLE_DEHUMIDIFY:
        return f"{device.label} (>{device.humidity_threshold:.0f} %)"
    if lt is None or ut is None:
        return device.label          # thresholds not ready yet; updated on first sync
    if device.role == ROLE_COOLING:
        activate_at = ut + device.activate_offset
        return f"{device.label} (>{activate_at:.1f} °C)"
    # ROLE_HEATING
    activate_at = lt - device.activate_offset
    return f"{device.label} (<{activate_at:.1f} °C)"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    devices_data = entry.options.get(CONF_DEVICES, [])
    device_sensors = [
        ControlledDeviceSensor(entry, idx, _Device(d))
        for idx, d in enumerate(devices_data)
    ]
    hass.data[DOMAIN][entry.entry_id]["device_sensors"] = device_sensors

    async_add_entities(device_sensors)


class ControlledDeviceSensor(BinarySensorEntity):
    """
    Diagnostic sensor for one device managed by a Climate Comfort room.

    Appears on the room's device page alongside the thermostat entity.
    State: Running (device is currently active) / Idle.
    Attributes include the current computed trigger temperatures so you can
    see at a glance when each device will switch on or off.
    """

    _attr_should_poll = False
    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True

    def __init__(self, entry: ConfigEntry, index: int, device: _Device) -> None:
        self._entry = entry
        self._index = index
        self._device = device

        self._attr_unique_id = f"{entry.entry_id}_device_{index}"
        # Name starts as plain label; updated to include trigger temp on first sync
        self._attr_name = device.label
        self._attr_icon = _ROLE_ICONS.get(device.role, "mdi:power")

        # Grouped with the climate entity on the room's device page
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
        )

    async def async_added_to_hass(self) -> None:
        """Apply trigger-temp name as soon as hass is available."""
        thresholds = (
            self.hass.data.get(DOMAIN, {})
            .get(self._entry.entry_id, {})
            .get("thresholds", {})
        )
        self.update_trigger_name(thresholds.get("lt"), thresholds.get("ut"))
        self.async_write_ha_state()

    def update_trigger_name(self, lt: float | None, ut: float | None) -> None:
        """Recompute the entity name — shows (Manual) when a hold is active."""
        entry_data = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {})
        holds = entry_data.get("manual_holds", {})
        if self._device.entity_id in holds:
            self._attr_name = f"{self._device.label} (Manual)"
            self._attr_icon = "mdi:hand-back-right"
        else:
            self._attr_name = _device_name_with_trigger(self._device, lt, ut)
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

        attrs: dict = {}

        if d.role in (ROLE_HEATING, ROLE_COOLING):
            if lt is not None and ut is not None:
                if d.role == ROLE_HEATING:
                    activate_at = lt - d.activate_offset
                    deactivate_at = activate_at + d.deactivate_offset
                    attrs["activates_below"] = f"{activate_at:.1f} °C"
                    attrs["deactivates_above"] = f"{deactivate_at:.1f} °C"
                else:
                    activate_at = ut + d.activate_offset
                    deactivate_at = activate_at - d.deactivate_offset
                    attrs["activates_above"] = f"{activate_at:.1f} °C"
                    attrs["deactivates_below"] = f"{deactivate_at:.1f} °C"
                if preset:
                    attrs["active_preset"] = preset

            # Config values — useful but secondary to trigger temps
            attrs["offset_beyond_boundary"] = f"{d.activate_offset} °C"
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


