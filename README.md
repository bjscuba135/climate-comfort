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

---

## How it works

Climate Comfort creates a **virtual thermostat** for each room. You tell it which temperature sensor to read and which devices (switches, fans, climate units) are responsible for heating and cooling. It then:

1. Reads the room temperature continuously.
2. Compares it against the current setpoint and comfort zone to decide whether heating or cooling is needed.
3. Activates or deactivates controlled devices accordingly, using configurable thresholds and hysteresis to prevent rapid cycling.
4. Responds to preset changes (Eco, Comfort, Boost, Away) from the thermostat card, automations, or a shared House Mode selector.

---

## Features

- **Comfort-zone deadband** — no devices run while the room is within ±X °C of the setpoint, avoiding constant micro-cycling
- **Multi-stage escalation** — add multiple devices to a room; each stage fires at a different distance from the boundary (e.g. a fan at the boundary, an air conditioner 3°C beyond it)
- **Four preset modes** — Eco, Comfort, Boost, Away — with individual temperature setpoints
- **Away protection band** — Away mode uses independent low/high limits rather than a single setpoint; nothing runs while the room is inside the band
- **Dehumidifier support** — humidity-based control independent of temperature, with optional suppression when heating/cooling is active
- **Manual hold detection** — automatically detects when a device has been changed outside of automation and suspends control for a configurable period
- **Global defaults** — share preset temperatures and comfort-zone width across all rooms; override per-room at any time
- **House and floor mode selectors** — a single entity change cascades the active preset to every room, or just the rooms on one floor
- **Live number entities** — edit preset temperatures and comfort zone directly from the device page without opening the options flow
- **Smart HVAC mode** — supported modes are inferred automatically from the device roles configured; no manual selection needed

---

## Installation

### Manual

1. Copy the `custom_components/climate_comfort` folder into the `custom_components` directory of your Home Assistant configuration.
2. Restart Home Assistant.
3. Go to **Settings → Devices & Services → Add Integration** and search for **Climate Comfort**.

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

If you previously copied the integration over the local network, and it was installed as:

```text
custom_components/climate_comfort
```

then the HACS install uses the same Home Assistant domain (`climate_comfort`) and should load your existing config entries and entity registry records.

Recommended safe migration:

1. Back up Home Assistant.
2. Rename the manually copied folder before installing through HACS:
   ```text
   custom_components/climate_comfort.old
   ```
3. Install **Climate Comfort** through HACS using the custom repository steps above.
4. Restart Home Assistant.
5. Confirm the existing Climate Comfort entries and entities load normally.
6. Delete `custom_components/climate_comfort.old` after the HACS-managed install is working.

Do not keep both the old manual copy and the HACS-managed copy in place at the same time.

---

## Setup

### Global Defaults (optional)

It is recommended to create a **Global Defaults** entry first if you have more than one room. This gives you a single place to manage shared preset temperatures and creates House Mode / Floor Mode selectors that all rooms can follow.

1. **Settings → Devices & Services → Add Integration → Climate Comfort**
2. Choose **Global defaults (shared preset temperatures)**
3. Set your default Comfort Zone width and preset temperatures
4. Optionally add floor names (e.g. *Ground Floor*, *First Floor*) — each creates a dedicated mode selector

A **Global Settings** device is created containing the House Mode selector and any floor selectors.

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
| **Use global preset temperatures** | Inherit Eco / Comfort / Boost / Away values from Global Defaults |

If you choose not to use global presets, a second step lets you configure preset temperatures for this room.

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

| Preset | Behaviour |
|---|---|
| **None** | Uses whatever temperature was last set manually on the thermostat card |
| **Eco** | Energy-saving setpoint — typically cooler in winter, warmer in summer |
| **Comfort** | Normal occupied setpoint |
| **Boost** | Maximum heating or cooling target |
| **Away** | Protection band — heating only fires below the Away Low limit; cooling only fires above the Away High limit |

Preset temperatures can be edited live from the number entities on the device page. Editing a preset number automatically stops inheriting from Global Defaults for that room.

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

The **Global Defaults** entry creates a **House Mode** select entity with four options: `comfort`, `eco`, `boost`, `away`. Rooms configured to follow this entity automatically switch preset when the house mode changes.

If you added floor names to Global Defaults, each floor also gets its own **Floor Mode** selector. When House Mode changes it cascades to every floor, but you can override individual floors independently.

**Wiring a room to a mode selector:**

In the room's settings, set *House / floor mode entity* to either the House Mode entity or one of the floor selectors. That's it — the room's preset follows the selector automatically.

---

## Entities Reference

### Per Room

| Entity | Type | Description |
|---|---|---|
| *(Room name)* | `climate` | The main thermostat — shows current temperature, HVAC action, setpoint, and preset |
| *(Device label) (<trigger temp>)* | `binary_sensor` | One per configured device — Running when active, Idle otherwise. Attributes include trigger temperatures and manual override status |
| **Comfort Zone** | `number` | Live-editable deadband half-width |
| **Eco / Comfort / Boost Temperature** | `number` | Live-editable preset setpoints (greyed out when inheriting from Global Defaults) |
| **Away Lower / Upper Limit** | `number` | Live-editable Away protection band limits |
| **Using Global Presets** | `switch` | Toggle whether this room inherits presets from Global Defaults |
| **Dehumidification** | `switch` | Suspend / resume dehumidifier control (only created when a dehumidifier device is configured) |
| **Reset to Automated Control** | `button` | Clears all manual holds and immediately resumes automated control |

### Global Settings Device

| Entity | Type | Description |
|---|---|---|
| **House Mode** | `select` | Whole-home mode selector — cascades to all floor selectors and directly-subscribed rooms |
| *(Floor name)* **Mode** | `select` | One per configured floor name — follows House Mode but can be overridden independently |

---

## Tips and Examples

**Start with a single heating device, activate offset 0:**
The simplest setup — one radiator or electric heater turns on when the room drops below the lower threshold and off when it recovers past the hysteresis point. Increase the comfort zone width if you find it cycling too often.

**Add a second heating stage for a backup device:**
Set the second device's activate offset higher (e.g. 2 °C). The backup only fires if the primary hasn't managed to bring the room up within 2 °C of the boundary — useful for slow systems.

**Use Away mode for frost protection:**
Set Away Low to 8 °C and Away High to 35 °C. Nothing runs in normal conditions; heating only fires if the room goes dangerously cold.

**Global Defaults + per-room override:**
Create Global Defaults with your typical temperatures. Turn on *Use global preset temperatures* for every room. For a room that runs warmer (e.g. a home office), open its options, go to *Edit preset temperatures*, and set custom values — the *Using Global Presets* switch turns off automatically.

**Suppress the dehumidifier during heating:**
Enable *Only run when not heating or cooling* on the dehumidifier device. Running both a heater and a dehumidifier simultaneously often works against each other, especially in small rooms.
