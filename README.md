# Climate Comfort

A custom Home Assistant integration that turns any collection of switches, fans, and climate entities into a fully-featured, multi-stage room thermostat with a comfort-zone deadband, preset modes, dehumidifier support, and manual-override detection.

---

## Contents

- [How it works](#how-it-works)
- [Features](#features)
- [Upgrading to 2.0.0](#upgrading-to-200)
- [Upgrading to 1.3.0](#upgrading-to-130)
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
  - [Fan Speed and Swing Direction](#fan-speed-and-swing-direction)
  - [Minimum On and Off Times](#minimum-on-and-off-times)
  - [Manual Hold Detection](#manual-hold-detection)
  - [Startup and Restarts](#startup-and-restarts)
  - [House and Floor Mode](#house-and-floor-mode)
  - [Schedules](#schedules)
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
- **Schedules** — weekly profiles for the House, each floor or a single room, with workdays and holidays, calendar events, and a drag-to-edit timeline in the card
- **House and floor mode selectors** — a single entity change cascades the active preset to every room, or just the rooms on one floor
- **Live number entities** — edit preset temperatures and comfort zone directly from the device page without opening the options flow
- **Built-in dashboard card** — a comfort-band card that configures itself from the room's thermostat, with a visual editor
- **Short-cycle protection** — optional minimum on and off times per device, so compressors are never started and stopped too quickly
- **Fan speed and swing direction** — optionally set a climate device's fan speed and its vertical and horizontal swing directions when it activates, alongside the HVAC mode
- **Smart HVAC mode** — supported modes are inferred automatically from the device roles configured; no manual selection needed

---

## Upgrading to 2.0.0

**Take a backup first.** 2.0.0 changes how each room's devices are stored, and
the change cannot be undone by installing an older version: 1.x will refuse to
load a room that 2.0.0 has migrated. Restoring the backup is the way back.

What changes when you update:

- **Devices are managed on the integration page.** Each device a room controls
  is now listed under that room in *Settings → Devices & services → Climate
  Comfort*, with **Add device** on the room and *Reconfigure* / *Delete* on each
  device. The device pages in the room's *Configure* dialog are gone. Existing
  devices are moved across automatically, with their sensors and history.
- **Adding a device is two pages, not four.** Name, entity and role first; then
  one page with every setting that applies to that device.
- **Deleting a device removes its sensor** instead of leaving an unavailable
  entity behind.
- **The dashboard card is built in.** It is served by the integration and loaded
  automatically, so there is no resource to add. If you added the card as a
  dashboard resource before, you can remove that resource; it is harmless if left.
- **The card configures itself.** It only needs the room's thermostat. Stages and
  the aggressiveness control are read from the thermostat, and the card has a
  visual editor. A hand-written `triggers:` list still works and takes priority.
- **A dehumidifier needs a humidity sensor.** Adding one to a room without a
  humidity sensor is now refused with an explanation.

For automations, the *Manual Control* sensor gains an
`automated_control_resumes_at` timestamp, and the thermostat a `stages` attribute
describing every stage.

---

## Upgrading to 1.3.0

**Requires Home Assistant 2026.11 or newer.** 1.3.0 uses the climate temperature
properties and entity hooks introduced in that release; the names they replace
are removed from Home Assistant in 2027.11.

What changes when you update:

- **Stage sensors keep a fixed name.** A sensor is now called *Radiator*, not
  *Radiator (<19.5 °C)* or *Radiator (Manual)*. The trigger temperature is the
  `trigger_temperature` attribute, and a manual hold shows as a hand icon and the
  `manual_override` attribute. Entity IDs and history are kept.
- **Removing a device no longer scrambles the others.** Each stage has its own
  permanent ID instead of being identified by its position in the list.
- **The Comfort Zone is always the room's own value.** Previously a room using
  global presets silently used the Global Defaults zone and ignored its own.
  Check each room's *Comfort Zone* number after updating if you had changed it.
- **Editing a number or the *Using Global Presets* switch no longer reloads the
  room.** The change is applied live.
- **Changes to Global Defaults reach every room straight away** rather than at
  the next restart.
- **A restart no longer moves the temperature.** In Heat-only or Cool-only mode
  a manually set temperature shifted by one comfort zone on every restart.
- **Manual holds and the Dehumidification switch survive a restart.**
- **A setpoint change reaches a device that is already running.** Its target is
  updated instead of waiting for the next time it switches on.
- **Manual changes are noticed when they happen**, not at the next temperature
  reading, and a failed command is retried within 30 seconds.
- ***Edit room settings* no longer switches *Using Global Presets* back on.**

---

## Installation

On Home Assistant 2026.11 and newer, HACS is built in as **Settings →
Marketplace**; custom repositories are added there with *Add from link*. The
HACS steps below describe the same process on the older, separate HACS.

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

Each device a room controls is added from the integration page: open *Settings →
Devices & services → Climate Comfort*, find the room, and choose **Add device**.
To change or remove one later, use *Reconfigure* or *Delete* in the menu beside
that device.

#### Page 1 — Identity

| Field | Description |
|---|---|
| **Name** | Short label shown on the device page (e.g. *Radiator*, *AirCon*, *Fan*) |
| **Entity** | The `switch`, `climate`, `fan`, or `input_boolean` entity to control |
| **Role** | `Heating`, `Cooling`, or `Dehumidifier` |

A dehumidifier can only be added to a room that has a humidity sensor.

#### Page 2 — Settings

Only the settings that apply to the entity and role you chose are shown.

**Heating and cooling devices**

| Field | Description |
|---|---|
| **Activation point** | Where this device joins in after the room leaves the comfort zone. `0` is at the edge of the zone; each further point is one step of the active aggressiveness profile's spacing. |
| **Hysteresis** | How far the temperature must recover past the activation point before the device turns off. Prevents rapid cycling. |
| **Use for emergency safety limits** | Lets this device run if the room crosses the global minimum or maximum temperature. |

**Dehumidifiers**

| Field | Description |
|---|---|
| **Activate above** | Relative humidity (%) at which the device switches on |
| **Deactivate hysteresis** | Humidity must drop this many percent below the threshold before switching off |
| **Only run when not heating/cooling** | Suppress dehumidification while temperature control is active |

**Climate entities, in any role**

| Field | Description |
|---|---|
| **HVAC mode when active** | The mode set on the climate entity when this stage activates (list populated from the entity's own supported modes) |
| **Target overshoot** | Optional offset applied to the device's temperature setpoint to ensure it actually runs — see [Target Temp Offset](#target-temp-offset) |
| **Fan speed / swing direction** | Optional — see [Fan Speed and Swing Direction](#fan-speed-and-swing-direction) |

**Every device**

| Field | Description |
|---|---|
| **Minimum on time** | Minutes the device keeps running once switched on. `0` (default) = no limit. See [Minimum On and Off Times](#minimum-on-and-off-times) |
| **Minimum off time** | Minutes the device stays off once switched off before it may start again. `0` (default) = no limit |

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

### Fan Speed and Swing Direction

Setting an HVAC mode is often not the whole story. An air conditioner set to `cool`
still has a fan speed and, on many units, a louvre direction — and the useful setting
is frequently "cool, on high, pointed at the ceiling" rather than just "cool".

For any climate device you can therefore set three optional secondary attributes,
applied when the controller switches the device on, immediately after the HVAC mode:

| Setting | Service called | Read from |
|---------|----------------|-----------|
| **Fan speed when active** | `climate.set_fan_mode` | `fan_modes` |
| **Vertical swing direction when active** | `climate.set_swing_mode` | `swing_modes` |
| **Horizontal swing direction when active** | `climate.set_swing_horizontal_mode` | `swing_horizontal_modes` |

Home Assistant treats the two swing axes as genuinely separate settings, each with its
own attribute, feature flag and service. A device may advertise one, both or neither.
Where a unit cannot control the axes independently, its integration is expected to put
every combination into `swing_modes` alone, in which case only the vertical field
appears and it carries all the options.

Three things worth knowing about how these behave:

**They are only offered when your device actually supports them.** Each dropdown is
populated from the entity's own attributes. A thermostatic radiator valve advertises
none of them, so no extra fields appear on its config step — there is no free-text box
to type a value the device will only reject.

**The values shown are the raw ones.** Dropdowns list exactly what the entity reports
— `up_down_auto`, `left_right_auto`, `3d_auto`, `quiet` — rather than the prettified
labels Home Assistant shows on the device page. These are the values you would use in
an automation or see in Developer Tools, so what you pick here is unambiguous.

**"Leave unchanged" is the default.** A device that *can* take a fan speed is still not
managed unless you pick one. Existing rooms are unaffected by this feature until you
opt in, and a device left on *Leave unchanged* keeps whatever speed it was last set to —
whether that was you, another automation, or its own remote.

**A failure here will not stop your heating or cooling.** By the time these are applied
the HVAC mode is already set and the device is running. If the fan-direction call then
fails — an unsupported value, a device that dropped offline mid-sequence — it is logged
as a warning and the device stays marked active. The alternative would be worse: rolling
the device back to inactive while the hardware is running, so the controller tries to
switch it on again on every evaluation, indefinitely. Comfort control does not hinge on
a louvre.

> **If the fields do not appear:** the entity was probably unavailable when you opened
> the form, so it had no attributes to read. Reload the integration and edit the device
> again.

---

### Minimum On and Off Times

Air conditioners, heat pumps and dehumidifiers have compressors, and a compressor
that is started and stopped every few minutes wears out quickly. Hysteresis
limits how far the temperature must move before a device switches, but not how
often. The minimum times limit how often.

- **Minimum on time** — once a device has switched on, it keeps running at least
  this long, even if the room is already back inside the comfort zone.
- **Minimum off time** — once a device has switched off, it stays off at least
  this long before it may start again. Many manufacturers ask for 3 to 5 minutes,
  so the refrigerant pressures can settle.

Typical values for an air conditioner or heat pump are a 5-minute minimum on
time and a 3 to 5-minute minimum off time. Leave both at `0` for radiators,
fans and other devices that do not mind being switched often.

How they behave:

- **Switches made by hand count too.** If you turn the air conditioner off
  yourself, its minimum off time starts then.
- **Only switching on and off is limited.** A climate entity used as several
  stages (fan only, then cool) counts as one device and uses the longest time
  set on any of its stages. Moving between its own stages is never delayed.
- **Your own choices are never delayed.** Turning the thermostat off, switching
  it to Heat only or Cool only, and turning the *Dehumidification* switch off
  all take effect at once. So does the fail-safe shutdown when the temperature
  sensor goes unavailable.
- **The safety limits wait too.** A device that should start because the room
  crossed the global minimum or maximum temperature still waits out its minimum
  off time. The wait is only a few minutes, and it protects the hardware.
- **A held device is not a manual change.** While a device waits, the controller
  expects it to stay as it is, so no manual hold is triggered.
- **The device switches within 30 seconds** of its minimum time ending, at the
  next scheduled check.
- **Times are not kept across a restart.** After Home Assistant starts, the
  limits apply from each device's first switch.

While a device waits, the thermostat shows it in a `min_time_waits` attribute,
for example `{"climate.aircon": {"action": "off", "until": "2026-11-25T14:05:00+00:00"}}`,
and the same value appears as `min_time_wait` on that device's entry in
`stages`.

---

### Manual Hold Detection

Climate Comfort watches the actual state of every controlled device and compares it to the expected state. If a device is changed by anything other than the integration itself — a manual toggle, a voice command, another automation — it detects the divergence and enters a **manual hold**:

- Automated control of that device is suspended for the configured hold period
- A `manual_holds` attribute on the thermostat entity shows which devices are held and how many minutes remain
- The binary sensor for the held device shows a hand icon and `manual_override: true`
- A hold survives a restart and ends when it originally would have
- The **Reset to Automated Control** button clears all holds immediately and resumes normal operation

Set the hold period to `0` to disable this feature entirely.

A device that is **unavailable** is never treated as a manual override. Offline is
not the same as switched off, so a unit that drops off the network — a WiFi air
conditioner is a good candidate — will not trigger a hold while it is away, and its
real state is re-read when it comes back rather than being blamed on you.

---

### Startup and Restarts

**Your settings survive a restart.** The room's HVAC mode, preset and target
temperature are restored exactly as they were. A room left in Eco, or Away, or
switched off, comes back that way.

A restored preset takes priority over the House / Floor Mode selector, so a
deliberate per-room override is not undone by a restart. The selector is consulted
only when there is nothing to restore, which in practice means the first time a room
runs after you create it.

> Before v1.2.1 there was no restoration at all: every restart silently reset the
> room to Home / `heat_cool` / 21 °C. On a mild day that is enough to start the
> heating or the air conditioning within seconds of Home Assistant booting.

A room on a named preset comes back at that preset's current temperature. A
temperature you set by hand (preset *None*) comes back exactly as you left it,
along with any comfort band you dragged on the card.

**Devices already running at boot are adopted, not fought.** Climate Comfort is
routinely loaded before the integrations it controls, so it waits: a controlled
entity that has not appeared yet is skipped rather than recorded as "off", and
automated control only begins once Home Assistant has finished starting. A device
that was left running is matched to whichever configured stage corresponds to its
actual HVAC mode, so it carries on rather than being switched off and immediately
flagged as a manual change.

The same applies to any device that shows up late or returns from an outage — its
real state is adopted the first time it can be read.

---

### House and Floor Mode

The **Global Defaults** entry creates a **House Mode** select entity whose options are built from the currently enabled presets. `away` and `home` are always present, while optional presets such as `sleep`, `comfort`, `eco`, `activity`, and `boost` appear only when enabled in Global Defaults.

If you added floor names to Global Defaults, each floor also gets its own **Floor Mode** selector. When House Mode changes it cascades to every floor, but you can override individual floors independently.

**Wiring a room to a mode selector:**

In the room's settings, set *House / floor mode entity* to either the House Mode entity or one of the floor selectors. That's it — the room's preset follows the selector automatically.

---

### Schedules

A schedule changes presets by time of day. There are three kinds, and you can
use any mix of them:

| Schedule | Changes | Use it for |
|---|---|---|
| **House schedule** | House Mode, and so every floor and room following it | One routine for the whole home |
| **Floor schedule** | One Floor Mode selector | A floor that keeps different hours (e.g. bedrooms upstairs) |
| **Room schedule** | That room's own preset | A room that is its own case (an office, a nursery) |

Every schedule is **off** until you switch it on, so updating changes nothing.

#### Profiles

A schedule is a set of **profiles**. A profile is a list of times and presets,
plus the days it covers. Each time lasts until the next one. If a day's first
time is not 00:00, the last preset of the day before carries on until it.

```
workday [workdays]: 00:00 sleep, 06:30 comfort, 08:30 eco, 17:00 comfort, 22:30 sleep
weekend [weekend]: 00:00 sleep, 08:30 comfort, 23:00 sleep
home_office [wed]: 07:30 comfort, 22:30 sleep
holiday (off): 00:00 eco
```

- **Days** are `all` (the default when left out), `workdays`, `weekend`, or a
  list of days such as `mon, wed`.
- **`(off)`** keeps a profile without using it. A profile that is off can still
  be called up by the calendar or the profile selector.
- **Which profile a day uses:**
  1. a calendar event that day titled with a profile's name;
  2. an enabled profile for chosen days that include that day;
  3. the enabled `workdays` or `weekend` profile;
  4. the enabled `all` profile.

  With none of these, the schedule leaves the preset alone that day.
- **Two enabled profiles may not cover the same days.** `all` overlaps
  `workdays` and `weekend`, and chosen-day profiles overlap when they share a
  day. A chosen-day profile does not overlap the groups: on its days it wins.

#### Editing

- **In the card** (easiest): *Edit schedule* opens a timeline for each profile.
  - Drag the boundaries to move a time, in 5-minute steps.
  - Tap a block to change its preset, split it in two or remove it.
  - Pick the days with the chips.
  - Save checks the whole schedule first.
- **In the settings**:
  - A room's own schedule: *Configure → Schedule*.
  - The House and floor schedules: Global Defaults *Configure → Schedules*.
  - Both are the text format above.
- **From an automation** — `comfort_climate.set_schedule`, with the text or a
  `profiles` list. Target a room thermostat, a House / Floor Mode selector, or
  any of the schedule's entities:

  ```yaml
  action: comfort_climate.set_schedule
  data:
    entity_id: climate.lounge
    schedule: |
      workday [workdays]: 00:00 sleep, 06:30 comfort, 22:30 sleep
      weekend [weekend]: 00:00 sleep, 08:30 comfort, 23:00 sleep
    enable: true
  ```

  `comfort_climate.get_schedule` returns a schedule as text and as profiles.

Schedules are kept in Home Assistant's own storage, not in the integration's
settings, so saving one never reloads a room.

#### Changes made by hand, and Away

- **A preset changed by hand lasts until the next scheduled change.** This
  covers the card, a voice assistant, an automation, or House Mode for its own
  schedule. Then the schedule takes over again. *Resume schedule* (in the card,
  or `comfort_climate.resume_schedule`) ends it straight away.
- **Away pauses a schedule.** While House Mode, a Floor Mode or a room is in
  Away, the schedule changes nothing. When Away ends, it goes straight back to
  what the schedule says now.
- **A room or floor with its own schedule ignores House Mode, except Away.**
  If House Mode goes to Away, they go too. When House Mode leaves Away, they go
  back to their own schedule.
- **At every scheduled change, rooms are brought back.** A room following
  House Mode that someone set by hand returns to House Mode, even if the
  scheduled preset is the one House Mode already had.

#### Workdays, holidays and the calendar

All three are set once, in Global Defaults *Configure → Schedules → Workdays,
calendar and start of day*:

- **Workday sensor** (optional): a sensor from the Workday integration. Public
  holidays then use the `weekend` profile. Without one, Monday to Friday are
  workdays.
- **Calendar** (optional): any Home Assistant calendar. It is read every hour,
  whenever an event starts or ends, and when Climate Comfort reloads. An event
  you add can take up to an hour to be noticed.
  - An event titled with a **profile name** (e.g. `weekend` on a day off)
    switches the whole day to that profile.
  - An event titled with a **preset** (e.g. `away` from 09:00 to 17:00) sets
    that preset while the event lasts.
- **Schedule day starts at**: leave at 00:00 unless you work nights. With 05:00,
  the small hours of Saturday still follow Friday's profile.

#### Entities

Each schedule (room, House, each floor) has:

| Entity | Type | Description |
|---|---|---|
| **Schedule** | `switch` | Switches the schedule on and off |
| **Schedule profile** | `select` | Chooses a profile: it is switched on and any profile covering the same days is switched off. Its `today` attribute is the profile in use today |
| **Next scheduled change** | `sensor` | When the preset next changes. Attributes: `scheduled_preset`, `next_preset`, `profile_today`, `override`, `paused`, and the profiles themselves for the card |

On the House device they are called *House schedule*, *House schedule
profile* and *House next scheduled change*; a floor's carry the floor name. A
room's thermostat has a `schedule_entity` attribute naming the schedule that
decides its preset: its own, or the one of the selector it follows.

---

## Entities Reference

### Per Room

| Entity | Type | Description |
|---|---|---|
| *(Room name)* | `climate` | The main thermostat — shows current temperature, HVAC action, setpoint, preset, and rich diagnostic attributes such as thresholds, effective comfort zone, active profile, point spacing, any manual holds, and any devices waiting out a minimum on / off time (`min_time_waits`) |
| *(Device label)* | `binary_sensor` | One per configured device — Running when active, Idle otherwise. Attributes include `trigger_temperature`, the on/off thresholds and manual override status |
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

### Dashboard card

Climate Comfort includes its own card. It is installed and loaded with the
integration — there is nothing to download and no dashboard resource to add.

Add it from the card picker (search for *Climate Comfort*), or from a room
thermostat's entity, where Home Assistant suggests it. The visual editor asks
only for the room:

```yaml
- type: custom:climate-comfort-card
  entity: climate.conservatory
```

The card reads the room's stages and its aggressiveness control from the
thermostat, so they follow any device you add, change or remove.

Optional settings:

| Option | Description |
|---|---|
| `name` | Shown in place of the room name |
| `show_details` | Set to `false` to hide the list of stages |
| `aggressiveness_entity` | Use a different select entity for the aggressiveness buttons |
| `triggers` | A hand-written list of stage sensors (`entity`, `kind`, `label`). When present it replaces the automatic stages; cards configured before 2.0 keep working this way. |

If the card does not appear after updating, refresh the browser once so it
picks up the new file.

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
