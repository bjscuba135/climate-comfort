# Climate Comfort

A custom Home Assistant integration that turns any collection of switches, fans, and climate entities into a fully-featured, multi-stage room thermostat with a comfort-zone deadband, preset modes, dehumidifier support, and manual-override detection.

---

## Contents

- [How it works](#how-it-works)
- [Features](#features)
- [Installation](#installation)
- [Setup](#setup)
  - [Global Defaults (optional)](#global-defaults-optional)
  - [Room Thermostat](#room-thermostat)
  - [Adding Devices](#adding-devices)
- [Concepts](#concepts)
  - [Comfort Zone](#comfort-zone)
  - [Preset Modes](#preset-modes)
  - [Device Roles](#device-roles)
  - [Escalation Stages](#escalation-stages)
  - [Target Temp Offset](#target-temp-offset)
  - [Manual Hold Detection](#manual-hold-detection)
  - [House and Floor Mode](#house-and-floor-mode)
- [Entities Reference](#entities-reference)
- [Tips and Examples](#tips-and-examples)
- [Dashboard Example](#dashboard-example)
  - [Recommended layout](#recommended-layout)
  - [Example Lovelace view](#example-lovelace-view)

---

## How it works

Climate Comfort creates a **virtual thermostat** for each room. You tell it which temperature sensor to read and which devices (switches, fans, climate units) are responsible for heating and cooling. It then:

1. Reads the room temperature continuously.
2. Compares it against the current setpoint and comfort zone to decide whether heating or cooling is needed.
3. Activates or deactivates controlled devices accordingly, using configurable thresholds and hysteresis to prevent rapid cycling.
4. Responds to preset changes (Away, Sleep, Home, Comfort, Eco, Activity, Boost) from the thermostat card, automations, or a shared House Mode selector.

---

## Features

- **Comfort-zone deadband** — no devices run while the room is within ±X °C of the setpoint, avoiding constant micro-cycling
- **Multi-stage escalation** — add multiple devices to a room; each stage fires at a different distance from the boundary (e.g. a fan at the boundary, an air conditioner 3°C beyond it)
- **Built-in Home Assistant presets** — supports `away`, `sleep`, `home`, `comfort`, `eco`, `activity`, and `boost`
- **Preset availability toggles** — choose which optional presets appear in the climate entity and House / Floor Mode selectors; `away`, `home`, and `none` are always available
- **Mode-specific temperatures and aggressiveness** — each built-in preset can have its own target temperature and profile, except `away`, which always uses the global minimum/maximum safety temperatures as its heating/cooling boundaries
- **Away protection band** — Away mode always uses the configured global minimum/maximum safety temperatures as its protection band; nothing runs while the room is inside the band
- **Dehumidifier support** — humidity-based control independent of temperature, with optional suppression when heating/cooling is active
- **Manual hold detection** — automatically detects when a device has been changed outside of automation and suspends control for a configurable period
- **Global defaults** — share preset temperatures and comfort-zone width across all rooms; override per-room at any time
- **House and floor mode selectors** — a single entity change cascades the active preset to every room, or just the rooms on one floor
- **Live number entities** — edit preset temperatures and comfort zone directly from the device page without opening the options flow
- **Smart HVAC mode** — supported modes are inferred automatically from the device roles configured; no manual selection needed

---

## Installation

### Manual

1. Copy the `custom_components/climate_comfort` folder into the `custom_components` directory of your Home Assistant configuration, then rename the copied folder to `comfort_climate` if you are installing manually.
2. Restart Home Assistant.
3. Go to **Settings → Devices & Services → Add Integration** and search for **Climate Comfort**.

The project/display name is **Climate Comfort**, but the Home Assistant integration domain remains `comfort_climate` for compatibility with existing installs and config entries. The repository folder remains `custom_components/climate_comfort` so HACS can update older HACS records, but HACS installs it locally as `custom_components/comfort_climate` because the manifest domain is `comfort_climate`.

### HACS

Climate Comfort can be installed with HACS as a custom repository until it is accepted into the default HACS catalogue.

1. Open **HACS → Integrations**.
2. Select the three-dot menu → **Custom repositories**.
3. Add this repository URL:
   ```text
   https://github.com/bjscuba135/climate-comfort
   ```
4. Set **Category** to **Integration**.
5. Select **Add**, then search HACS for **Climate Comfort** and install it.
6. Restart Home Assistant.
7. Go to **Settings → Devices & Services → Add Integration** and search for **Climate Comfort**.

#### Updating from a manual install

Home Assistant stores config entries by integration domain. To preserve existing entries and entity IDs, Climate Comfort keeps the historical Home Assistant domain:

```text
custom_components/comfort_climate
```

The repository/project has been renamed to **Climate Comfort**, but the integration domain remains `comfort_climate`. For HACS compatibility the repository still contains the source under `custom_components/climate_comfort`; HACS reads that folder and installs it locally as `custom_components/comfort_climate` from the manifest domain.

Recommended safe migration:

1. Back up Home Assistant.
2. If you have a manually copied folder, rename it before installing through HACS:
   ```text
   custom_components/comfort_climate.old
   ```
3. Install **Climate Comfort** through HACS using the custom repository steps above.
4. Restart Home Assistant.
5. Confirm the existing Climate Comfort entries and entities load normally.
6. Delete `custom_components/comfort_climate.old` after the HACS-managed install is working.

Do not keep both the old manual copy and the HACS-managed copy in place at the same time.

---

## Setup

### Global Defaults (optional)

It is recommended to create a **Global Defaults** entry first if you have more than one room. This gives you a single place to manage shared mode temperatures, preset availability toggles, aggressiveness profiles, and House Mode / Floor Mode selectors that all rooms can follow.

1. **Settings → Devices & Services → Add Integration → Climate Comfort**
2. Choose **Global defaults (shared preset temperatures)**
3. Configure shared mode temperatures, preset availability toggles, and aggressiveness profiles
4. Optionally add floor names (e.g. *Ground Floor*, *First Floor*) — each creates a dedicated mode selector

A **Global Settings** device is created containing the House Mode selector and any floor selectors.

Default preset availability:

- Always available: `none`, `away`, `home`
- Toggleable and enabled by default: `sleep`, `comfort`, `eco`
- Toggleable and disabled by default: `activity`, `boost`

---

### Room Thermostat

1. **Settings → Devices & Services → Add Integration → Climate Comfort**
2. Choose **Room thermostat**

| Field | Description |
|---|---|
| **Room name** | Used as the device name and unique ID — must be unique |
| **Temperature sensor** | The `sensor` entity whose value drives all control decisions |
| **Humidity sensor** | Optional — required only if you add a dehumidifier device |
| **Comfort zone width** | Half-width of the deadband either side of the setpoint (±°C) |
| **House / floor mode entity** | Optional — a `select` entity whose state sets the active preset |
| **Manual override hold period** | Hours to suspend control after a manual device change (0 = disabled) |
| **Use global preset temperatures** | Inherit shared mode temperatures from Global Defaults |

If you choose not to use global presets, a second step lets you configure this room's mode temperatures and profiles locally.

---

### Adding Devices

Devices are added after a room is created via the **Configure** button on the integration card (or from the device page).

#### Step 1 — Identity

| Field | Description |
|---|---|
| **Name** | Short label shown on the device page (e.g. *Radiator*, *AirCon*, *Fan*) |
| **Entity** | The `switch`, `climate`, `fan`, or `input_boolean` entity to control |
| **Role** | `Heating`, `Cooling`, or `Dehumidifier` |

#### Step 2a — Temperature thresholds (Heating / Cooling)

| Field | Description |
|---|---|
| **Activate offset** | How far beyond the comfort zone boundary before this device turns on. `0` = exactly at the boundary. `3` = 3 °C past it. |
| **Hysteresis** | How far the temperature must recover past the activation point before the device turns off. Prevents rapid cycling. |

#### Step 2b — Humidity thresholds (Dehumidifier)

| Field | Description |
|---|---|
| **Activate above** | Relative humidity (%) at which the device switches on |
| **Deactivate hysteresis** | Humidity must drop this many percent below the threshold before switching off |
| **Only run when not heating/cooling** | Suppress dehumidification while temperature control is active |

#### Step 3 — Climate mode (climate entities only)

| Field | Description |
|---|---|
| **HVAC mode when active** | The mode set on the climate entity when this stage activates (list populated from the entity's own supported modes) |
| **Target overshoot** | Optional offset applied to the device's temperature setpoint to ensure it actually runs — see [Target Temp Offset](#target-temp-offset) |

---

## Concepts

### Comfort Zone

The comfort zone is a dead band centred on the target temperature. No devices run while the room temperature sits within this band.

```
          Comfort Zone
         ←── ±1.0 °C ──→
              |      |
    ──────────|──────|──────────
  [Heating]  20°   21°   22°  [Cooling]
              LT         UT
```

With a 21 °C setpoint and a 1.0 °C comfort zone:

- **Lower threshold (LT)** = 20.0 °C — heating devices activate below this
- **Upper threshold (UT)** = 22.0 °C — cooling devices activate above this

The comfort zone can be adjusted live from the device page's **Comfort Zone** number entity without restarting or opening the options flow.

---

### Preset Modes

Climate Comfort uses built-in Home Assistant climate presets for the room thermostat:

| Preset | Behaviour |
|---|---|
| **None** | Uses whatever temperature was last set manually on the thermostat card |
| **Away** | Protection-oriented band that always uses the configured global minimum and maximum temperatures as the heating/cooling thresholds |
| **Sleep** | Cooler or quieter overnight target |
| **Home** | Default occupied target and the fallback mode that is always available |
| **Comfort** | Warmer / more comfortable occupied target |
| **Eco** | Reduced / setback target |
| **Activity** | Cooler occupied target intended for more active periods |
| **Boost** | Temporary high-priority target |

Preset availability is configurable in **Global Defaults → Mode temperatures**:

- `none`, `away`, and `home` are always available
- Optional presets (`sleep`, `comfort`, `eco`, `activity`, `boost`) can be turned on or off individually
- House Mode / Floor Mode selectors only show presets that are enabled
- Room thermostats reject disabled presets if a dashboard or automation tries to set one

Preset temperatures can be edited live from the number entities on the device page. `Away` is not exposed as an editable temperature because it always inherits the global minimum/maximum safety bounds. `Activity Temperature` and `Boost Temperature` are created disabled by default in the entity registry so they can be surfaced only when wanted.

---

### Device Roles

| Role | Activates when… | Deactivates when… |
|---|---|---|
| **Heating** | Room temperature ≤ LT − activate_offset | Temperature recovers above activation point + hysteresis |
| **Cooling** | Room temperature ≥ UT + activate_offset | Temperature recovers below activation point − hysteresis |
| **Dehumidifier** | Humidity ≥ threshold | Humidity falls below threshold − hysteresis |

---

### Escalation Stages

The same physical device (e.g. a climate entity) can be added multiple times with different roles and offsets to create an escalation ladder. Climate Comfort resolves a **single winning stage** per entity before issuing any service calls, so the device never flip-flops between modes.

**Example — single air conditioner, two cooling stages:**

| Stage | Role | Activate offset | Behaviour |
|---|---|---|---|
| AirCon — Fan | Cooling | 0 °C | Fan-only mode kicks in at the comfort zone boundary |
| AirCon — Cool | Cooling | 3 °C | Full cooling mode takes over 3 °C beyond the boundary |

Only the highest-offset active stage is applied at any time.

---

### Target Temp Offset

When a climate entity is the controlled device, you can set a **target overshoot** to ensure the device actually runs rather than sitting idle at a setpoint it has already reached.

- **Heating** — device is set to `setpoint + offset` °C
- **Cooling** — device is set to `setpoint − offset` °C

Set to `0` to use the room setpoint directly as the device's target temperature.

---

### Manual Hold Detection

Climate Comfort watches the actual state of every controlled device and compares it to the expected state. If a device is changed by anything other than the integration itself — a manual toggle, a voice command, another automation — it detects the divergence and enters a **manual hold**:

- Automated control of that device is suspended for the configured hold period
- A `manual_holds` attribute on the thermostat entity shows which devices are held and how many minutes remain
- The binary sensor for the held device shows `(Manual)` in its name
- The **Reset to Automated Control** button clears all holds immediately and resumes normal operation

Set the hold period to `0` to disable this feature entirely.

---

### House and Floor Mode

The **Global Defaults** entry creates a **House Mode** select entity whose options are built from the currently enabled presets. `away` and `home` are always present, while optional presets such as `sleep`, `comfort`, `eco`, `activity`, and `boost` appear only when enabled in Global Defaults.

If you added floor names to Global Defaults, each floor also gets its own **Floor Mode** selector. When House Mode changes it cascades to every floor, but you can override individual floors independently.

**Wiring a room to a mode selector:**

In the room's settings, set *House / floor mode entity* to either the House Mode entity or one of the floor selectors. That's it — the room's preset follows the selector automatically.

---

## Entities Reference

### Per Room

| Entity | Type | Description |
|---|---|---|
| *(Room name)* | `climate` | The main thermostat — shows current temperature, HVAC action, setpoint, preset, and rich diagnostic attributes such as thresholds, effective comfort zone, active profile, point spacing, and any manual holds |
| *(Device label) (<trigger temp>)* | `binary_sensor` | One per configured device — Running when active, Idle otherwise. Attributes include trigger temperatures and manual override status |
| **Comfort Zone** | `number` | Live-editable deadband half-width |
| **Sleep / Home / Comfort / Eco Temperature** | `number` | Core mode temperatures shown by default; Away always inherits the configured minimum / maximum safety bounds instead |
| **Activity Temperature** | `number` | Optional live-editable preset temperature; disabled by default in the entity registry |
| **Boost Temperature** | `number` | Optional live-editable preset temperature; disabled by default in the entity registry |
| **Using Global Presets** | `switch` | Toggle whether this room inherits shared mode temperatures from Global Defaults |
| **Aggressiveness** | `select` | Runtime per-room profile override. `mode_default` follows the active mode's configured profile |
| **Dehumidification** | `switch` | Suspend / resume dehumidifier control (only created when a dehumidifier device is configured) |
| **Reset to Automated Control** | `button` | Clears all manual holds and immediately resumes automated control |

### Global Settings Device

| Entity | Type | Description |
|---|---|---|
| **House Mode** | `select` | Whole-home mode selector — cascades to all floor selectors and directly-subscribed rooms; only enabled presets are shown |
| *(Floor name)* **Mode** | `select` | One per configured floor name — follows House Mode but can be overridden independently |

---

## Tips and Examples

**Start with a single heating device, activate offset 0:**
The simplest setup — one radiator or electric heater turns on when the room drops below the lower threshold and off when it recovers past the hysteresis point. Increase the comfort zone width if you find it cycling too often.

**Add a second heating stage for a backup device:**
Set the second device's activate offset higher (e.g. 2 °C). The backup only fires if the primary hasn't managed to bring the room up within 2 °C of the boundary — useful for slow systems.

**Use Away mode for protection:**
Away always uses the configured global minimum and maximum temperatures, so tune those safety bounds to match how far the room is allowed to drift while unoccupied.

**Global Defaults + per-room override:**
Create Global Defaults with your typical temperatures. Turn on *Use global preset temperatures* for every room. For a room that runs warmer (e.g. a home office), open its options, go to *Edit mode temperatures*, and set custom values — the *Using Global Presets* switch turns off automatically.

**Use Activity and Boost selectively:**
`Activity` and `Boost` are disabled by default so the everyday UI stays clean. Enable them only for rooms or households where they add real value.

**Use the Aggressiveness select for temporary tuning:**
Leave the room on `mode_default` most of the time, then temporarily switch to `responsive` or `aggressive` if a room needs tighter control without editing the stored mode configuration.

**Suppress the dehumidifier during heating:**
Enable *Only run when not heating or cooling* on the dehumidifier device. Running both a heater and a dehumidifier simultaneously often works against each other, especially in small rooms.

---

## Dashboard Example

A good end-user dashboard for Climate Comfort should expose three layers clearly:

1. **Quick room control** — current temp, preset, and target
2. **Tuning controls** — comfort zone, key mode temperatures, aggressiveness
3. **Diagnostics** — thresholds, active devices, manual holds

The integration already exposes useful entities and attributes for this without needing a bespoke frontend card. A ready-to-import example is also included at `examples/lovelace/climate-comfort-dashboard.yaml`.

### Prototype custom card

A first Conservatory-focused custom card prototype is included at:

- `frontend/climate-comfort-card.js`

It is a plain JavaScript Lovelace custom card with no build step. The intended deployment path is to publish the file in GitHub and add it to Home Assistant as a Lovelace resource, for example via jsDelivr:

```text
https://cdn.jsdelivr.net/gh/bjscuba135/climate-comfort@main/frontend/climate-comfort-card.js
```

Example configuration:

```yaml
- type: custom:climate-comfort-card
  entity: climate.conservatory
  aggressiveness_entity: select.conservatory_aggressiveness
  triggers:
    - entity: binary_sensor.conservatory_aircon_heat_10_degc
      kind: heating
      label: Aircon heat
    - entity: binary_sensor.conservatory_radiator_5_degc
      kind: heating
      label: Radiator
    - entity: binary_sensor.conservatory_aircon_fan_0_degc
      kind: cooling
      label: Aircon fan
    - entity: binary_sensor.conservatory_aircon_cool_3_degc
      kind: cooling
      label: Aircon cool
    - entity: binary_sensor.conservatory_fan_10_degc
      kind: cooling
      label: Extractor fan
    - entity: binary_sensor.conservatory_aircon_dry_65
      kind: humidity
      label: Dry mode
```

### Recommended layout

- **Top row:** one thermostat card per important room
- **Second row:** shared house controls (`House Mode`, floor modes)
- **Third row:** room tuning entities (`Comfort Zone`, core temperatures, `Aggressiveness`)
- **Bottom row:** diagnostics glance / entities card for manual holds and active stages

### Example Lovelace view

```yaml
title: Climate Comfort
path: climate-comfort
icon: mdi:home-thermometer
cards:
  - type: grid
    columns: 2
    square: false
    cards:
      - type: thermostat
        entity: climate.lounge
        name: Lounge
        features:
          - type: climate-preset-modes
            style: dropdown
      - type: thermostat
        entity: climate.bedroom
        name: Bedroom
        features:
          - type: climate-preset-modes
            style: dropdown

  - type: entities
    title: House Modes
    show_header_toggle: false
    entities:
      - entity: select.global_settings_house_mode
        name: House Mode
      - entity: select.global_settings_ground_floor_mode
        name: Ground Floor
      - entity: select.global_settings_first_floor_mode
        name: First Floor

  - type: grid
    columns: 2
    square: false
    cards:
      - type: entities
        title: Lounge Tuning
        show_header_toggle: false
        entities:
          - entity: select.lounge_aggressiveness
            name: Aggressiveness
          - entity: number.lounge_comfort_zone
            name: Comfort Zone
          - entity: number.lounge_mode_home
            name: Home Temperature
          - entity: number.lounge_mode_warmup
            name: Comfort Temperature
          - entity: number.lounge_mode_cooldown
            name: Eco Temperature
          - entity: switch.lounge_using_global_presets
            name: Use Global Presets
      - type: entities
        title: Bedroom Tuning
        show_header_toggle: false
        entities:
          - entity: select.bedroom_aggressiveness
            name: Aggressiveness
          - entity: number.bedroom_comfort_zone
            name: Comfort Zone
          - entity: number.bedroom_mode_sleep
            name: Sleep Temperature
          - entity: number.bedroom_mode_home
            name: Home Temperature
          - entity: number.bedroom_mode_warmup
            name: Comfort Temperature
          - entity: switch.bedroom_using_global_presets
            name: Use Global Presets

  - type: entities
    title: Lounge Diagnostics
    show_header_toggle: false
    entities:
      - entity: climate.lounge
        name: Lounge Thermostat
        secondary_info: last-changed
      - entity: binary_sensor.lounge_radiator
      - entity: binary_sensor.lounge_aircon_cool
      - entity: button.lounge_reset_to_automated_control
```

### Best UI ideas for end users

- Keep `Activity` and `Boost` hidden unless the household actually uses them.
- Use the thermostat card for preset changes, not a separate entities list, when possible.
- Put `Aggressiveness` near `Comfort Zone` so users understand both are tuning controls.
- Treat diagnostics as a collapsible or lower-priority section.
- Surface the reset button only where manual holds are likely to confuse people.

### If you want a richer custom visual

The next step would be a dedicated Lovelace card that groups:

- current room temperature
- active preset
- effective comfort zone
- lower / upper thresholds
- active devices
- manual hold warning banner
- inline chips for mode selection and aggressiveness

That would likely be best as a small custom card or a decluttering-card/button-card template package rather than adding more integration entities.
