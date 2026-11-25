const SUPPORT_PRESET_MODES = 1;
const SUPPORT_TARGET_TEMPERATURE = 2;
const SUPPORT_TARGET_TEMPERATURE_RANGE = 4;

const fireEvent = (node, type, detail = {}, options = {}) => {
  const event = new Event(type, {
    bubbles: options.bubbles ?? true,
    cancelable: options.cancelable ?? false,
    composed: options.composed ?? true,
  });
  event.detail = detail;
  node.dispatchEvent(event);
  return event;
};

// Weekly schedule (integration 2.1+). Slot times are "HH:MM" in the Home
// Assistant server's time zone, on a 5-minute grid.
const SCHEDULE_DAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];
const SCHEDULE_DAY_LABELS = {
  mon: 'Mon', tue: 'Tue', wed: 'Wed', thu: 'Thu', fri: 'Fri', sat: 'Sat', sun: 'Sun',
};
const SCHEDULE_DAY_MODES = [['all', 'All'], ['workdays', 'Workdays'], ['weekend', 'Weekend']];
const SCHEDULE_DEFAULT_PRESETS = ['away', 'sleep', 'home', 'comfort', 'eco', 'activity', 'boost'];
const SCHEDULE_NAME_FORBIDDEN = /[[\]:#,]/;
const SCHEDULE_STEP = 5;
const DAY_MINUTES = 1440;

// Static styles for the schedule strip and editor. They live in their own
// <style> element so the per-update style rebuild never touches them.
const SCHEDULE_STYLES = `
  :host {
    --cc-preset-sleep: #6366f1;
    --cc-preset-home: #16a34a;
    --cc-preset-comfort: #ea7a12;
    --cc-preset-eco: #0d9488;
    --cc-preset-away: #7c8796;
    --cc-preset-activity: #db2777;
    --cc-preset-boost: #dc2626;
    --cc-preset-other: #64748b;
  }
  .cc-schedule:empty,
  .cc-editor:empty { display: none; }
  .sch-strip {
    margin-top: 16px;
    border-top: 1px solid var(--cc-border, rgba(148, 163, 184, 0.18));
    padding-top: 14px;
    display: grid;
    gap: 10px;
  }
  .sch-head {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
  }
  .sch-head-main {
    flex: 1 1 170px;
    min-width: 0;
    background: none;
    border: 0;
    padding: 0;
    text-align: left;
    cursor: pointer;
  }
  .sch-title {
    display: block;
    font-weight: 700;
    font-size: 0.95rem;
  }
  .sch-summary {
    display: block;
    font-size: 0.88rem;
    margin-top: 2px;
  }
  .sch-muted {
    color: var(--cc-text-soft, var(--secondary-text-color, #9ca3af));
    font-size: 0.8rem;
  }
  .sch-pill {
    display: inline-block;
    margin-left: 6px;
    padding: 1px 8px;
    border-radius: 999px;
    font-size: 0.72rem;
    font-weight: 600;
    background: rgba(148, 163, 184, 0.16);
    border: 1px solid var(--cc-border, rgba(148, 163, 184, 0.18));
    vertical-align: middle;
  }
  .sch-strip.off .sch-bar-wrap,
  .sch-strip.off .sch-summary,
  .sch-strip.off .sch-pill {
    opacity: 0.45;
    filter: grayscale(0.7);
  }
  .sch-bar {
    position: relative;
    height: 22px;
    border-radius: 8px;
    overflow: hidden;
    background: rgba(148, 163, 184, 0.12);
    box-shadow: inset 0 0 0 1px var(--cc-border, rgba(148, 163, 184, 0.18));
  }
  .sch-bar.empty {
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .sch-bar.edit {
    height: 40px;
    overflow: visible;
    background: none;
    box-shadow: none;
    margin-top: 4px;
  }
  .sch-segs {
    position: absolute;
    inset: 0;
    overflow: hidden;
    border-radius: 10px;
    background: rgba(148, 163, 184, 0.12);
  }
  .sch-seg {
    position: absolute;
    top: 0;
    bottom: 0;
    margin: 0;
    padding: 0;
    border: 0;
    border-right: 1px solid rgba(255, 255, 255, 0.35);
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
    white-space: nowrap;
    color: #fff;
    font-size: 0.7rem;
    font-weight: 700;
    text-shadow: 0 1px 1px rgba(0, 0, 0, 0.35);
  }
  button.sch-seg { cursor: pointer; }
  .sch-seg.carry {
    opacity: 0.55;
    background-image: repeating-linear-gradient(135deg, rgba(255, 255, 255, 0.28) 0 4px, transparent 4px 8px) !important;
  }
  .sch-seg.selected {
    box-shadow: inset 0 0 0 3px var(--primary-text-color, #fff);
  }
  .sch-now {
    position: absolute;
    top: 0;
    bottom: 0;
    width: 3px;
    margin-left: -1px;
    background: var(--primary-text-color, #fff);
    box-shadow: 0 0 0 1px var(--card-background-color, rgba(0, 0, 0, 0.5));
    pointer-events: none;
  }
  .sch-handle {
    position: absolute;
    top: -6px;
    bottom: -6px;
    width: 28px;
    margin-left: -14px;
    display: flex;
    justify-content: center;
    cursor: ew-resize;
    touch-action: none;
    z-index: 2;
    outline: none;
  }
  .sch-handle::before {
    content: '';
    width: 4px;
    border-radius: 2px;
    background: var(--card-background-color, #fff);
    box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.45);
  }
  .sch-handle:focus-visible::before,
  .sch-handle.dragging::before {
    width: 6px;
    background: var(--primary-color, #03a9f4);
  }
  .sch-tip {
    position: absolute;
    bottom: calc(100% + 4px);
    left: 50%;
    transform: translateX(-50%);
    padding: 3px 7px;
    border-radius: 6px;
    background: rgba(17, 24, 39, 0.92);
    color: #fff;
    font-size: 0.74rem;
    font-weight: 700;
    white-space: nowrap;
    pointer-events: none;
  }
  .sch-ticks {
    position: relative;
    height: 14px;
    margin-top: 3px;
    font-size: 0.66rem;
    color: var(--cc-text-soft, var(--secondary-text-color, #9ca3af));
  }
  .sch-ticks span {
    position: absolute;
    top: 0;
    transform: translateX(-50%);
  }
  .sch-ticks span:first-child { transform: none; }
  .sch-ticks span:last-child { transform: translateX(-100%); }
  .sch-switch {
    position: relative;
    flex: none;
    width: 38px;
    height: 22px;
    padding: 0;
    border-radius: 999px;
    border: 1px solid var(--cc-border, rgba(148, 163, 184, 0.18));
    background: rgba(148, 163, 184, 0.35);
    cursor: pointer;
    transition: background 0.15s;
  }
  .sch-switch span {
    position: absolute;
    top: 2px;
    left: 2px;
    width: 16px;
    height: 16px;
    border-radius: 50%;
    background: #fff;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.3);
    transition: left 0.15s;
  }
  .sch-switch.on { background: var(--primary-color, #03a9f4); }
  .sch-switch.on span { left: 18px; }
  .sch-switch:disabled { opacity: 0.5; cursor: default; }
  .sch-btn {
    min-height: 34px;
    padding: 6px 12px;
    border-radius: 999px;
    border: 1px solid var(--cc-border, rgba(148, 163, 184, 0.18));
    background: rgba(148, 163, 184, 0.1);
    font-size: 0.82rem;
    font-weight: 600;
    cursor: pointer;
  }
  .sch-btn.primary {
    background: var(--primary-color, #03a9f4);
    color: var(--text-primary-color, #fff);
    border-color: transparent;
  }
  .sch-btn.ghost { background: transparent; }
  .sch-btn.wide { width: 100%; }
  .sch-btn:disabled { opacity: 0.45; cursor: default; }
  .sch-band {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 8px 10px;
    padding: 8px 10px;
    border-radius: 12px;
    font-size: 0.84rem;
    background: rgba(234, 122, 18, 0.13);
    border: 1px solid rgba(234, 122, 18, 0.35);
  }
  .sch-band.paused {
    background: rgba(124, 135, 150, 0.14);
    border-color: rgba(124, 135, 150, 0.35);
  }
  .sch-band > span { flex: 1 1 170px; }
  .sch-error {
    display: flex;
    align-items: flex-start;
    gap: 8px;
    padding: 8px 10px;
    border-radius: 10px;
    font-size: 0.82rem;
    color: var(--error-color, #db4437);
    background: rgba(219, 68, 55, 0.1);
  }
  .sch-error > span { flex: 1; }
  .sch-error button {
    border: 0;
    background: none;
    cursor: pointer;
    color: inherit;
    padding: 0 4px;
  }
  .sch-note {
    font-size: 0.8rem;
    padding: 6px 10px;
    border-radius: 10px;
    background: rgba(59, 130, 246, 0.12);
  }
  .sch-err {
    font-size: 0.78rem;
    color: var(--error-color, #db4437);
  }
  .sch-editor {
    margin-top: 14px;
    padding: 12px;
    display: grid;
    gap: 12px;
    border-radius: 16px;
    border: 1px solid var(--cc-border, rgba(148, 163, 184, 0.18));
    background: rgba(148, 163, 184, 0.05);
  }
  .sch-prof {
    display: grid;
    gap: 8px;
    padding: 10px;
    border-radius: 14px;
    border: 1px solid var(--cc-border, rgba(148, 163, 184, 0.18));
    background: var(--card-background-color, transparent);
  }
  .sch-prof.off .sch-bar,
  .sch-prof.off .sch-ticks { opacity: 0.5; }
  .sch-prof-head {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .sch-name {
    flex: 1 1 auto;
    min-width: 0;
    font: inherit;
    color: inherit;
    padding: 7px 10px;
    border-radius: 10px;
    border: 1px solid var(--cc-border, rgba(148, 163, 184, 0.18));
    background: rgba(148, 163, 184, 0.08);
  }
  .sch-icon {
    min-width: 36px;
    min-height: 36px;
    padding: 6px;
    border: 0;
    border-radius: 8px;
    background: none;
    color: var(--cc-text-soft, var(--secondary-text-color, #9ca3af));
    cursor: pointer;
    font-size: 1rem;
  }
  .sch-days,
  .sch-menu-row {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px;
  }
  .sch-chip-break { flex-basis: 100%; height: 0; }
  .sch-chip {
    min-height: 30px;
    padding: 4px 10px;
    border-radius: 999px;
    border: 1px solid var(--cc-border, rgba(148, 163, 184, 0.18));
    background: rgba(148, 163, 184, 0.08);
    font-size: 0.78rem;
    cursor: pointer;
  }
  .sch-chip.selected {
    background: rgba(59, 130, 246, 0.22);
    border-color: rgba(96, 165, 250, 0.6);
    font-weight: 700;
  }
  .sch-chip.implied {
    border-style: dashed;
    border-color: rgba(96, 165, 250, 0.55);
  }
  .sch-chip.preset::before {
    content: '';
    display: inline-block;
    width: 8px;
    height: 8px;
    margin-right: 6px;
    border-radius: 50%;
    background: var(--chip);
  }
  .sch-chip.preset.selected {
    background: var(--chip);
    border-color: transparent;
    color: #fff;
  }
  .sch-chip.preset.selected::before { background: #fff; }
  .sch-menu {
    display: grid;
    gap: 8px;
    padding: 10px;
    border-radius: 12px;
    background: rgba(148, 163, 184, 0.1);
  }
  .sch-time,
  .sch-copy {
    font: inherit;
    font-size: 0.82rem;
    color: inherit;
    padding: 5px 8px;
    border-radius: 8px;
    border: 1px solid var(--cc-border, rgba(148, 163, 184, 0.18));
    background: rgba(148, 163, 184, 0.08);
    color-scheme: light dark;
    max-width: 100%;
  }
  .sch-foot { display: grid; gap: 8px; }
  .sch-actions {
    display: flex;
    justify-content: flex-end;
    flex-wrap: wrap;
    gap: 8px;
  }
`;

class ClimateComfortCard extends HTMLElement {
  // Picks the first Climate Comfort room when the card is added from the
  // picker. Stages and the aggressiveness control are discovered from the
  // thermostat itself, so the entity is the only thing the card needs.
  static getStubConfig(hass, entities = []) {
    const isRoom = (id) => id.startsWith('climate.')
      && hass?.states?.[id]?.attributes?.comfort_zone !== undefined;
    return {
      entity: entities.find(isRoom) || Object.keys(hass?.states || {}).find(isRoom) || '',
      show_details: true,
    };
  }

  // Visual editor, built by Home Assistant from this description.
  static getConfigForm() {
    const labels = {
      entity: 'Room thermostat',
      name: 'Name (optional)',
      show_details: 'Show stage details',
      show_schedule: 'Show schedule',
    };
    const helpers = {
      entity: 'A room created by the Climate Comfort integration.',
      name: 'Shown in place of the room name.',
      show_details: 'Lists every heating, cooling and humidity stage below the comfort band.',
      show_schedule: 'Shows today\'s schedule for this room, with a button to edit the weekly schedule.',
    };
    return {
      schema: [
        {
          name: 'entity',
          required: true,
          selector: { entity: { filter: [{ integration: 'comfort_climate', domain: 'climate' }] } },
        },
        { name: 'name', selector: { text: {} } },
        { name: 'show_details', selector: { boolean: {} } },
        { name: 'show_schedule', selector: { boolean: {} } },
      ],
      computeLabel: (schema) => labels[schema.name],
      computeHelper: (schema) => helpers[schema.name],
    };
  }

  setConfig(config) {
    if (!config || !config.entity) {
      throw new Error('Climate Comfort card requires an entity');
    }
    this._config = {
      show_details: true,
      ...config,
      triggers: Array.isArray(config.triggers) ? config.triggers : [],
    };
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  getCardSize() {
    return (this._config?.show_details ? 8 : 6) + (this._schedule() ? 2 : 0);
  }

  _state(entityId) {
    return entityId ? this._hass?.states?.[entityId] ?? null : null;
  }

  _cleanLabel(text, fallback = 'Unknown') {
    if (!text) return fallback;
    return String(text)
      .replace(/^Climate\s+/i, '')
      .replace(/^.*?\s-\s/, '')
      .replace(/\s*\([^)]*\)$/, '')
      .trim() || fallback;
  }

  _num(value) {
    if (value === null || value === undefined || value === '') return null;
    if (typeof value === 'number') return Number.isFinite(value) ? value : null;
    const match = String(value).match(/-?\d+(?:\.\d+)?/);
    return match ? Number.parseFloat(match[0]) : null;
  }

  _fmtTemp(value) {
    return value === null || value === undefined || Number.isNaN(value) ? '—' : `${Number(value).toFixed(1)}°C`;
  }

  _fmtHumidity(value) {
    return value === null || value === undefined || Number.isNaN(value) ? '—' : `${Math.round(Number(value))}% RH`;
  }

  _titleCase(value, fallback = '—') {
    if (!value) return fallback;
    return String(value)
      .replace(/_/g, ' ')
      .replace(/\b\w/g, (m) => m.toUpperCase());
  }

  _formatHvacMode(mode) {
    const map = {
      off: 'Off',
      heat_cool: 'Auto',
      heat: 'Heat',
      cool: 'Cool',
      fan_only: 'Fan',
      dry: 'Dry',
      auto: 'Auto',
    };
    return map[mode] || this._titleCase(mode);
  }

  _deriveActionBadge(action, stages) {
    if (stages.some((s) => s.active && s.kind === 'humidity')) return 'Dry';
    const map = {
      heating: 'Heating',
      cooling: 'Cooling',
      idle: 'Idle',
      off: 'Off',
      fan: 'Fan',
      fan_only: 'Fan',
      dry: 'Dry',
    };
    return map[action] || this._titleCase(action, 'Idle');
  }

  _escape(text) {
    return String(text ?? '').replace(/[&<>"']/g, (ch) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[ch]));
  }

  // Stages published by the thermostat in its `stages` attribute (integration
  // 2.0 and newer). Used unless the card config lists `triggers` by hand.
  _stagesFromAttributes(attrs) {
    if (!Array.isArray(attrs.stages)) return [];
    return attrs.stages.map((stage, index) => ({
      entity: stage.entity_id,
      label: this._escape(stage.label || stage.entity_id),
      kind: stage.kind,
      thresholdType: stage.kind === 'humidity'
        ? 'humidity'
        : stage.kind === 'heating' ? 'below' : 'above',
      thresholdValue: this._num(stage.threshold),
      active: Boolean(stage.active),
      manual: Boolean(stage.manual),
      controlledEntity: stage.entity_id || null,
      hvacModeWhenActive: stage.hvac_mode || null,
      attrs: {},
      labelSide: index % 2 === 0 ? 'top' : 'bottom',
    }));
  }

  _aggressivenessEntity() {
    return this._config?.aggressiveness_entity
      || this._state(this._config?.entity)?.attributes?.aggressiveness_entity
      || null;
  }

  _normalizeTrigger(trigger, index) {
    const stateObj = this._state(trigger.entity);
    if (!stateObj) return null;
    const attrs = stateObj.attributes || {};
    const kind = trigger.kind || 'cooling';
    const thresholdType = kind === 'humidity'
      ? 'humidity'
      : attrs.activates_below
        ? 'below'
        : 'above';
    const thresholdValue = kind === 'humidity'
      ? this._num(attrs.activates_above_humidity)
      : this._num(attrs.activates_below ?? attrs.activates_above);
    const label = trigger.label || this._cleanLabel(attrs.friendly_name, trigger.entity);
    return {
      entity: trigger.entity,
      label,
      kind,
      thresholdType,
      thresholdValue,
      active: stateObj.state === 'on',
      controlledEntity: attrs.controlled_entity || null,
      hvacModeWhenActive: attrs.hvac_mode_when_active || null,
      rawState: stateObj,
      attrs,
      labelSide: index % 2 === 0 ? 'top' : 'bottom',
    };
  }

  _nextStage(current, stages, direction) {
    if (current === null) return null;
    const eligible = stages
      .filter((stage) => stage.thresholdValue !== null)
      .filter((stage) => direction === 'below' ? current > stage.thresholdValue : current < stage.thresholdValue)
      .sort((a, b) => direction === 'below'
        ? b.thresholdValue - a.thresholdValue
        : a.thresholdValue - b.thresholdValue);
    return eligible[0] || null;
  }

  _buildModel() {
    const climate = this._state(this._config?.entity);
    if (!climate) return null;
    const aggressiveness = this._state(this._aggressivenessEntity());
    const attrs = climate.attributes || {};
    const currentTemperature = this._num(attrs.current_temperature);
    const currentHumidity = this._num(attrs.current_humidity);
    const lowerThreshold = this._num(attrs.lower_threshold);
    const upperThreshold = this._num(attrs.upper_threshold);
    const presetMode = attrs.preset_mode || attrs.mode || null;
    const activeProfile = attrs.profile || null;
    const activeDevices = Array.isArray(attrs.active_devices) ? attrs.active_devices : [];
    const supportedFeatures = Number(attrs.supported_features || 0);

    // A hand-written `triggers` list still wins, so existing dashboards keep
    // their custom labels; otherwise the thermostat describes its own stages.
    const stages = this._config.triggers.length
      ? this._config.triggers
        .map((trigger, index) => this._normalizeTrigger(trigger, index))
        .filter(Boolean)
        .map((stage) => ({
          ...stage,
          active: stage.active || (stage.controlledEntity ? activeDevices.includes(stage.controlledEntity) : false),
        }))
      : this._stagesFromAttributes(attrs);

    const tempStages = stages.filter((stage) => stage.kind !== 'humidity' && stage.thresholdValue !== null);
    const humidityStage = stages.find((stage) => stage.kind === 'humidity' && stage.thresholdValue !== null) || null;

    const numericPoints = [lowerThreshold, upperThreshold, currentTemperature, ...tempStages.map((s) => s.thresholdValue)]
      .filter((value) => value !== null && value !== undefined && Number.isFinite(value));

    const fallbackMin = Math.min(...numericPoints, 18);
    const fallbackMax = Math.max(...numericPoints, 24);
    const rawMin = numericPoints.length ? Math.min(...numericPoints) : fallbackMin;
    const rawMax = numericPoints.length ? Math.max(...numericPoints) : fallbackMax;
    const span = Math.max(rawMax - rawMin, 1);
    const padding = Math.max(span * 0.05, 0.5);
    const rangeMin = rawMin - padding;
    const rangeMax = rawMax + padding;

    const sortValue = (stage) => stage.thresholdValue ?? 0;
    const heatingStages = tempStages.filter((stage) => stage.thresholdType === 'below').sort((a, b) => sortValue(a) - sortValue(b));
    const coolingStages = tempStages.filter((stage) => stage.thresholdType === 'above').sort((a, b) => sortValue(a) - sortValue(b));

    const profileBadge = activeProfile ? this._titleCase(activeProfile) : 'Default';
    const overrideBadge = aggressiveness?.state ? this._titleCase(aggressiveness.state === 'mode_default' ? 'default' : aggressiveness.state) : null;

    const nextHeatStage = this._nextStage(currentTemperature, heatingStages, 'below');
    const nextCoolStage = this._nextStage(currentTemperature, coolingStages, 'above');
    const humidityNeeded = Boolean(humidityStage && currentHumidity !== null && currentHumidity >= humidityStage.thresholdValue);
    const supportsPreset = Boolean(supportedFeatures & SUPPORT_PRESET_MODES) && Array.isArray(attrs.preset_modes) && attrs.preset_modes.length > 0;
    const supportsRange = Boolean(supportedFeatures & SUPPORT_TARGET_TEMPERATURE_RANGE);
    const supportsTemp = Boolean((supportedFeatures & SUPPORT_TARGET_TEMPERATURE) || supportsRange);

    return {
      climate,
      aggressiveness,
      roomName: this._config.name || attrs.friendly_name || climate.entity_id,
      currentTemperature,
      currentHumidity,
      lowerThreshold,
      upperThreshold,
      presetMode,
      hvacMode: climate.state,
      hvacModes: Array.isArray(attrs.hvac_modes) ? attrs.hvac_modes : [],
      hvacAction: attrs.hvac_action || climate.state,
      actionBadge: this._deriveActionBadge(attrs.hvac_action || climate.state, stages),
      activeProfile,
      profileBadge,
      overrideBadge,
      activeDevices,
      stages,
      tempStages,
      heatingStages,
      coolingStages,
      humidityStage,
      humidityNeeded,
      rangeMin,
      rangeMax,
      showDetails: this._config.show_details !== false,
      targetTempLow: this._num(attrs.target_temp_low),
      targetTempHigh: this._num(attrs.target_temp_high),
      targetTempStep: this._num(attrs.target_temp_step) || 0.5,
      minTemp: this._num(attrs.min_temp) ?? 5,
      maxTemp: this._num(attrs.max_temp) ?? 35,
      presetModes: Array.isArray(attrs.preset_modes) ? attrs.preset_modes : [],
      aggressivenessOptions: aggressiveness?.attributes?.options || [],
      nextHeatStage,
      nextCoolStage,
      supportsPreset,
      supportsTemp,
      supportsRange,
    };
  }

  _pct(model, value) {
    if (value === null || value === undefined) return null;
    const span = model.rangeMax - model.rangeMin || 1;
    return Math.min(100, Math.max(0, ((value - model.rangeMin) / span) * 100));
  }

  _barGradient(model) {
    const hasHeat = model.heatingStages.length > 0;
    const hasCool = model.coolingStages.length > 0;
    const lowerPct = this._pct(model, model.lowerThreshold) ?? 40;
    const upperPct = this._pct(model, model.upperThreshold) ?? 60;
    const leftColor = hasHeat ? '#7f1d1d' : '#d6d8de';
    const leftMid = hasHeat ? '#f3c7cf' : '#d6d8de';
    const center = '#dde1e7';
    const rightMid = hasCool ? '#c9ecff' : '#d6d8de';
    const rightColor = hasCool ? '#0b4aa8' : '#d6d8de';
    return `linear-gradient(90deg, ${leftColor} 0%, ${leftMid} ${lowerPct}%, ${center} ${lowerPct}%, ${center} ${upperPct}%, ${rightMid} ${upperPct}%, ${rightColor} 100%)`;
  }

  _badgeClass(kind) {
    return {
      Heating: 'heating',
      Cooling: 'cooling',
      Fan: 'fan',
      Dry: 'dry',
      Idle: 'idle',
      Off: 'idle',
    }[kind] || 'idle';
  }

  _tempCard(title, stage, kindLabel, active) {
    if (!stage) return '';
    return `
      <button class="summary-card ${active ? 'active' : ''}" data-entity="${stage.entity}" type="button">
        <span class="summary-kicker">${title}</span>
        <span class="summary-value">${this._fmtTemp(stage.thresholdValue)}</span>
        <span class="summary-device">${stage.label}</span>
        <span class="summary-state">${kindLabel}</span>
      </button>
    `;
  }

  _humidityCard(model) {
    if (!model.humidityStage) return '';
    return `
      <button class="summary-card humidity ${model.humidityStage.active ? 'active' : ''}" data-entity="${model.humidityStage.entity}" type="button">
        <span class="summary-kicker">Dry above</span>
        <span class="summary-value">${this._fmtHumidity(model.humidityStage.thresholdValue)}</span>
        <span class="summary-device">${model.humidityStage.label}</span>
        <span class="summary-state">${model.humidityStage.active ? 'Active now' : 'Humidity stage'}</span>
      </button>
    `;
  }

  _renderMarkers(model) {
    const markers = [];
    for (const stage of model.tempStages) {
      const left = this._pct(model, stage.thresholdValue);
      if (left === null) continue;
      const activeClass = stage.active ? 'marker active' : 'marker';
      const kindClass = stage.kind === 'heating' ? 'heating' : 'cooling';
      const sideClass = stage.labelSide === 'bottom' ? 'bottom' : 'top';
      markers.push(`
        <div class="${activeClass} ${kindClass} ${sideClass}" style="left:${left}%" data-entity="${stage.entity}">
          <span class="marker-label">${stage.label}</span>
          <span class="dot"></span>
        </div>
      `);
    }

    const currentLeft = this._pct(model, model.currentTemperature);
    if (currentLeft !== null) {
      markers.push(`
        <div class="current-marker" style="left:${currentLeft}%">
          <span class="current-pill top">${this._fmtTemp(model.currentTemperature)}</span>
          <span class="current-line"></span>
        </div>
      `);
    }

    const lowerLeft = this._pct(model, model.lowerThreshold);
    const upperLeft = this._pct(model, model.upperThreshold);
    if (lowerLeft !== null) {
      markers.push(`<div class="boundary boundary-lower" style="left:${lowerLeft}%"></div>`);
    }
    if (upperLeft !== null) {
      markers.push(`<div class="boundary boundary-upper" style="left:${upperLeft}%"></div>`);
    }

    return markers.join('');
  }

  _renderStageList(stages, label) {
    if (!stages.length) return '';
    return `
      <div class="stage-group">
        <div class="stage-group-title">${label}</div>
        <div class="stage-list">
          ${stages.map((stage) => `
            <button class="stage-chip ${stage.active ? 'active' : ''} ${stage.kind}" data-entity="${stage.entity}" type="button">
              <span class="stage-chip-label">${stage.label}</span>
              <span class="stage-chip-value">${this._fmtTemp(stage.thresholdValue)}</span>
            </button>
          `).join('')}
        </div>
      </div>
    `;
  }

  _renderModeButtons(model) {
    if (!model.hvacModes.length) return '';
    return `
      <div class="control-group">
        <div class="control-group-title">Mode</div>
        <div class="chip-row">
          ${model.hvacModes.map((mode) => `
            <button
              class="chip-button ${model.hvacMode === mode ? 'selected' : ''}"
              data-action="set-hvac-mode"
              data-value="${mode}"
              type="button"
            >${this._formatHvacMode(mode)}</button>
          `).join('')}
        </div>
      </div>
    `;
  }

  _renderPresetButtons(model) {
    if (!model.supportsPreset || !model.presetModes.length) return '';
    return `
      <div class="control-group">
        <div class="control-group-title">Preset</div>
        <div class="chip-row">
          ${model.presetModes.map((preset) => `
            <button
              class="chip-button ${model.presetMode === preset ? 'selected' : ''}"
              data-action="set-preset"
              data-value="${preset}"
              type="button"
            >${this._titleCase(preset)}</button>
          `).join('')}
        </div>
      </div>
    `;
  }

  _renderAggressivenessButtons(model) {
    if (!model.aggressivenessOptions.length) return '';
    const current = model.aggressiveness?.state;
    return `
      <div class="control-group">
        <div class="control-group-title">Aggressiveness</div>
        <div class="chip-row">
          ${model.aggressivenessOptions.map((option) => `
            <button
              class="chip-button ${current === option ? 'selected' : ''}"
              data-action="set-aggressiveness"
              data-value="${option}"
              type="button"
            >${this._titleCase(option === 'mode_default' ? 'default' : option)}</button>
          `).join('')}
        </div>
      </div>
    `;
  }

  _renderTemperatureControls(model) {
    if (!model.supportsTemp) return '';
    const low = model.targetTempLow ?? model.lowerThreshold;
    const high = model.targetTempHigh ?? model.upperThreshold;
    return `
      <div class="control-group temp-control-group">
        <div class="control-group-title">Comfort band</div>
        <div class="range-grid">
          <div class="range-control">
            <span class="range-label">Low</span>
            <div class="range-row">
              <button class="stepper" data-action="adjust-low" data-delta="-1" type="button">−</button>
              <button class="range-value" data-action="more-info" data-entity="${model.climate.entity_id}" type="button">${this._fmtTemp(low)}</button>
              <button class="stepper" data-action="adjust-low" data-delta="1" type="button">+</button>
            </div>
          </div>
          <div class="range-control">
            <span class="range-label">High</span>
            <div class="range-row">
              <button class="stepper" data-action="adjust-high" data-delta="-1" type="button">−</button>
              <button class="range-value" data-action="more-info" data-entity="${model.climate.entity_id}" type="button">${this._fmtTemp(high)}</button>
              <button class="stepper" data-action="adjust-high" data-delta="1" type="button">+</button>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  _openMoreInfo(entityId) {
    if (!entityId) return;
    fireEvent(this, 'hass-more-info', { entityId });
  }

  async _callService(domain, service, data) {
    if (!this._hass) return;
    await this._hass.callService(domain, service, data);
  }

  _clamp(value, min, max) {
    return Math.min(max, Math.max(min, value));
  }

  async _adjustTemperature(which, delta) {
    const model = this._buildModel();
    if (!model) return;
    const step = model.targetTempStep || 0.5;
    const low = model.targetTempLow ?? model.lowerThreshold ?? model.minTemp;
    const high = model.targetTempHigh ?? model.upperThreshold ?? model.maxTemp;
    let nextLow = low;
    let nextHigh = high;
    if (which === 'low') {
      nextLow = this._clamp(low + (delta * step), model.minTemp, high);
    } else {
      nextHigh = this._clamp(high + (delta * step), low, model.maxTemp);
    }
    await this._callService('climate', 'set_temperature', {
      entity_id: model.climate.entity_id,
      target_temp_low: Number(nextLow.toFixed(1)),
      target_temp_high: Number(nextHigh.toFixed(1)),
      hvac_mode: model.hvacMode === 'off' ? 'heat_cool' : model.hvacMode,
    });
  }

  async _handleAction(action, value, entityId, delta) {
    const model = this._buildModel();
    switch (action) {
      case 'set-hvac-mode':
        await this._callService('climate', 'set_hvac_mode', {
          entity_id: this._config.entity,
          hvac_mode: value,
        });
        return;
      case 'set-preset':
        await this._callService('climate', 'set_preset_mode', {
          entity_id: this._config.entity,
          preset_mode: value,
        });
        return;
      case 'set-aggressiveness':
        if (!this._aggressivenessEntity()) return;
        await this._callService('select', 'select_option', {
          entity_id: this._aggressivenessEntity(),
          option: value,
        });
        return;
      case 'adjust-low':
        await this._adjustTemperature('low', Number(delta || 0));
        return;
      case 'adjust-high':
        await this._adjustTemperature('high', Number(delta || 0));
        return;
      case 'more-info':
        this._openMoreInfo(entityId || value || this._config.entity);
        return;
      default:
        this._openMoreInfo(entityId || this._config.entity);
    }
  }

  _bindEvents(root) {
    root.querySelectorAll('[data-action], [data-entity]').forEach((element) => {
      element.addEventListener('click', async (event) => {
        event.stopPropagation();
        const action = element.dataset.action;
        const value = element.dataset.value;
        const entityId = element.dataset.entity;
        const delta = element.dataset.delta;
        if (action) {
          await this._handleAction(action, value, entityId, delta);
        } else if (entityId) {
          this._openMoreInfo(entityId);
        }
      });
    });

    const shell = root.querySelector('.card-shell');
    if (shell) {
      shell.addEventListener('click', (event) => {
        if (event.target.closest('button, summary')) return;
        this._openMoreInfo(this._config.entity);
      });
    }
  }

  // The shadow root is built once. Home Assistant sets `hass` on every state
  // change in the house, so only the main area and the read-only schedule
  // strip are rebuilt on update; the schedule editor has its own container
  // that is rebuilt only when the editor's own state changes. That keeps a
  // half-finished edit, a focused text field and an in-progress drag alive.
  _ensureSkeleton() {
    if (!this.shadowRoot) this.attachShadow({ mode: 'open' });
    if (this._mainEl && this.shadowRoot.contains(this._mainEl)) return;
    this.shadowRoot.innerHTML = `
      <style class="cc-main-style"></style>
      <style>${SCHEDULE_STYLES}</style>
      <ha-card>
        <div class="cc-main"></div>
        <div class="cc-schedule"></div>
        <div class="cc-editor"></div>
      </ha-card>
    `;
    this._styleEl = this.shadowRoot.querySelector('.cc-main-style');
    this._mainEl = this.shadowRoot.querySelector('.cc-main');
    this._schedEl = this.shadowRoot.querySelector('.cc-schedule');
    this._editorEl = this.shadowRoot.querySelector('.cc-editor');
    this._mainHtml = null;
    this._schedHtml = null;
    this._schedEl.addEventListener('click', (ev) => this._onScheduleClick(ev));
    this._editorEl.addEventListener('click', (ev) => this._onEditorClick(ev));
    this._editorEl.addEventListener('input', (ev) => this._onEditorInput(ev));
    this._editorEl.addEventListener('change', (ev) => this._onEditorChange(ev));
    this._editorEl.addEventListener('keydown', (ev) => this._onEditorKeyDown(ev));
    this._editorEl.addEventListener('pointerdown', (ev) => this._onEditorPointerDown(ev));
    this._renderEditor();
  }

  _setMain(html) {
    if (html === this._mainHtml) return;
    this._mainHtml = html;
    this._mainEl.innerHTML = html;
    this._bindEvents(this._mainEl);
  }

  _render() {
    if (!this._config) return;
    this._ensureSkeleton();
    if (!this._hass) {
      this._setMain(`<div class="pad">Waiting for Home Assistant…</div>`);
      return;
    }

    const model = this._buildModel();
    if (!model) {
      this._setMain(`<div class="pad">Entity ${this._escape(this._config.entity)} not found.</div>`);
      this._renderSchedule();
      return;
    }

    const summaryCards = [
      this._tempCard('Next heat', model.nextHeatStage, model.nextHeatStage?.active ? 'Active now' : 'Heating stage', Boolean(model.nextHeatStage?.active)),
      this._tempCard('Next cool', model.nextCoolStage, model.nextCoolStage?.active ? 'Active now' : 'Cooling stage', Boolean(model.nextCoolStage?.active)),
      this._humidityCard(model),
    ].filter(Boolean).join('');

    const detailsHtml = model.showDetails ? `
      <details class="details-shell">
        <summary>Trigger details</summary>
        ${this._renderStageList(model.heatingStages, 'Heating stages')}
        ${this._renderStageList(model.coolingStages, 'Cooling stages')}
        <div class="meta-grid">
          <div class="meta-row"><span>Current</span><strong>${this._fmtTemp(model.currentTemperature)}</strong></div>
          <div class="meta-row"><span>Humidity</span><strong>${this._fmtHumidity(model.currentHumidity)}</strong></div>
          <div class="meta-row"><span>Dead zone</span><strong>${this._fmtTemp(model.lowerThreshold)} → ${this._fmtTemp(model.upperThreshold)}</strong></div>
          <div class="meta-row"><span>Preset</span><strong>${this._titleCase(model.presetMode)}</strong></div>
          <div class="meta-row"><span>Active aggressiveness</span><strong>${model.profileBadge}</strong></div>
          ${model.overrideBadge ? `<div class="meta-row"><span>Override</span><strong>${model.overrideBadge}</strong></div>` : ''}
          <div class="meta-row"><span>Active devices</span><strong>${model.activeDevices.length ? model.activeDevices.join(', ') : 'None'}</strong></div>
        </div>
      </details>
    ` : '';

    const styles = `
        :host {
          --cc-red-deep: #7f1d1d;
          --cc-red-soft: #f3c7cf;
          --cc-dead-zone: #dde1e7;
          --cc-blue-soft: #c9ecff;
          --cc-blue-deep: #0b4aa8;
          --cc-teal: #2dd4bf;
          --cc-text-main: var(--primary-text-color, #e5e7eb);
          --cc-text-soft: var(--secondary-text-color, #9ca3af);
          --cc-border: rgba(148, 163, 184, 0.18);
          --cc-surface: rgba(148, 163, 184, 0.08);
          display: block;
        }
        * {
          box-sizing: border-box;
        }
        button {
          font: inherit;
          color: inherit;
        }
        ha-card {
          padding: 18px;
          border-radius: 20px;
          overflow: hidden;
        }
        .card-shell {
          cursor: pointer;
        }
        .pad {
          padding: 16px;
        }
        .header {
          display: flex;
          justify-content: space-between;
          align-items: flex-start;
          gap: 12px;
          margin-bottom: 12px;
        }
        .title {
          font-size: 1.3rem;
          font-weight: 700;
          line-height: 1.2;
        }
        .subtitle {
          color: var(--cc-text-soft);
          margin-top: 4px;
          font-size: 0.92rem;
        }
        .badges {
          display: flex;
          flex-wrap: wrap;
          justify-content: flex-end;
          gap: 8px;
        }
        .badge {
          border-radius: 999px;
          padding: 6px 10px;
          font-size: 0.78rem;
          font-weight: 700;
          letter-spacing: 0.01em;
          background: rgba(148, 163, 184, 0.14);
          color: var(--cc-text-main);
          border: 1px solid var(--cc-border);
        }
        .badge.heating { background: rgba(127, 29, 29, 0.18); }
        .badge.cooling { background: rgba(11, 74, 168, 0.18); }
        .badge.fan { background: rgba(59, 130, 246, 0.16); }
        .badge.dry { background: rgba(45, 212, 191, 0.18); }
        .hero {
          display: flex;
          align-items: baseline;
          gap: 12px;
          margin-bottom: 18px;
        }
        .hero-temp {
          font-size: 2.6rem;
          font-weight: 800;
          line-height: 1;
        }
        .hero-humidity {
          color: var(--cc-text-soft);
          font-size: 0.95rem;
          font-weight: 600;
        }
        .bar-area {
          position: relative;
          margin-top: 16px;
        }
        .bar-shell {
          position: relative;
          height: 150px;
        }
        .bar {
          position: absolute;
          left: 0;
          right: 0;
          top: 66px;
          height: 18px;
          border-radius: 999px;
          overflow: visible;
          background: ${this._barGradient(model)};
          box-shadow: inset 0 0 0 1px rgba(255,255,255,0.12);
        }
        .boundary {
          position: absolute;
          top: 62px;
          width: 2px;
          height: 26px;
          background: rgba(255,255,255,0.38);
          transform: translateX(-1px);
          z-index: 2;
        }
        .marker {
          position: absolute;
          transform: translateX(-50%);
          z-index: 3;
          text-align: center;
          width: 116px;
        }
        .marker.top { top: 8px; }
        .marker.bottom { top: 88px; }
        .marker.top .dot { margin: 0 auto 8px; }
        .marker.bottom .dot { margin: 8px auto 0; }
        .marker .dot {
          width: 12px;
          height: 12px;
          border-radius: 50%;
          display: block;
          border: 2px solid rgba(255,255,255,0.9);
          background: rgba(17,24,39,0.5);
          box-shadow: 0 0 0 2px rgba(17,24,39,0.16);
        }
        .marker.heating .dot { background: var(--cc-red-deep); }
        .marker.cooling .dot { background: var(--cc-blue-deep); }
        .marker.active .dot {
          transform: scale(1.15);
          box-shadow: 0 0 0 4px rgba(255,255,255,0.12);
        }
        .marker-label {
          display: block;
          font-size: 0.68rem;
          color: var(--cc-text-soft);
          line-height: 1.15;
          white-space: normal;
        }
        .current-marker {
          position: absolute;
          top: 18px;
          transform: translateX(-50%);
          z-index: 4;
          text-align: center;
          width: 72px;
        }
        .current-line {
          display: block;
          width: 3px;
          height: 82px;
          margin: 0 auto;
          border-radius: 3px;
          background: rgba(255,255,255,0.95);
          box-shadow: 0 0 0 2px rgba(17,24,39,0.18);
        }
        .current-pill {
          display: inline-block;
          padding: 4px 8px;
          border-radius: 999px;
          font-size: 0.72rem;
          font-weight: 800;
          background: rgba(17,24,39,0.9);
          color: white;
          white-space: nowrap;
          margin-bottom: 8px;
        }
        .axis {
          display: flex;
          justify-content: space-between;
          color: var(--cc-text-soft);
          font-size: 0.72rem;
          margin-top: 6px;
        }
        .summary-grid {
          margin-top: 16px;
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
          gap: 10px;
        }
        .summary-card {
          border: 1px solid var(--cc-border);
          background: var(--cc-surface);
          border-radius: 16px;
          padding: 12px;
          display: flex;
          flex-direction: column;
          align-items: flex-start;
          gap: 4px;
          text-align: left;
          cursor: pointer;
        }
        .summary-card.active { box-shadow: inset 0 0 0 1px rgba(255,255,255,0.12); }
        .summary-card.humidity,
        .summary-card.humidity.active { background: rgba(45, 212, 191, 0.12); }
        .summary-kicker {
          font-size: 0.72rem;
          color: var(--cc-text-soft);
          text-transform: uppercase;
          letter-spacing: 0.04em;
        }
        .summary-value {
          font-size: 1.1rem;
          font-weight: 800;
        }
        .summary-device {
          font-size: 0.86rem;
          font-weight: 700;
        }
        .summary-state {
          font-size: 0.74rem;
          color: var(--cc-text-soft);
        }
        .controls-shell {
          margin-top: 16px;
          display: grid;
          gap: 12px;
        }
        .control-group {
          border-radius: 16px;
          border: 1px solid var(--cc-border);
          background: rgba(148, 163, 184, 0.05);
          padding: 12px;
        }
        .control-group-title {
          font-size: 0.82rem;
          font-weight: 700;
          color: var(--cc-text-soft);
          margin-bottom: 10px;
        }
        .chip-row {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
        }
        .chip-button {
          border: 1px solid var(--cc-border);
          background: rgba(148, 163, 184, 0.08);
          border-radius: 999px;
          padding: 8px 12px;
          cursor: pointer;
        }
        .chip-button.selected {
          background: rgba(59, 130, 246, 0.2);
          border-color: rgba(96, 165, 250, 0.45);
        }
        .range-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
          gap: 12px;
        }
        .range-control {
          display: flex;
          flex-direction: column;
          gap: 8px;
        }
        .range-label {
          font-size: 0.76rem;
          color: var(--cc-text-soft);
          font-weight: 700;
          text-transform: uppercase;
          letter-spacing: 0.04em;
        }
        .range-row {
          display: grid;
          grid-template-columns: 40px 1fr 40px;
          gap: 8px;
          align-items: center;
        }
        .stepper,
        .range-value {
          border: 1px solid var(--cc-border);
          border-radius: 12px;
          background: rgba(148, 163, 184, 0.08);
          min-height: 42px;
          cursor: pointer;
        }
        .stepper {
          font-size: 1.2rem;
          font-weight: 700;
        }
        .range-value {
          font-weight: 700;
          padding: 0 12px;
        }
        .details-shell {
          margin-top: 16px;
          border-top: 1px solid var(--cc-border);
          padding-top: 12px;
        }
        .details-shell summary {
          cursor: pointer;
          font-weight: 700;
          color: var(--cc-text-main);
          list-style: none;
        }
        .details-shell summary::-webkit-details-marker {
          display: none;
        }
        .stage-group {
          margin-top: 14px;
        }
        .stage-group-title {
          font-size: 0.82rem;
          font-weight: 700;
          color: var(--cc-text-soft);
          margin-bottom: 8px;
        }
        .stage-list {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
        }
        .stage-chip {
          border-radius: 12px;
          padding: 8px 10px;
          background: rgba(148, 163, 184, 0.08);
          border: 1px solid var(--cc-border);
          display: flex;
          gap: 8px;
          align-items: center;
          cursor: pointer;
        }
        .stage-chip.heating.active { background: rgba(127, 29, 29, 0.18); }
        .stage-chip.cooling.active { background: rgba(11, 74, 168, 0.18); }
        .stage-chip-label {
          font-size: 0.78rem;
          font-weight: 700;
        }
        .stage-chip-value {
          font-size: 0.74rem;
          color: var(--cc-text-soft);
        }
        .meta-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
          gap: 10px;
          margin-top: 14px;
        }
        .meta-row {
          border-radius: 12px;
          padding: 10px 12px;
          background: rgba(148, 163, 184, 0.06);
          border: 1px solid var(--cc-border);
          display: flex;
          flex-direction: column;
          gap: 4px;
          font-size: 0.8rem;
        }
        .meta-row span {
          color: var(--cc-text-soft);
        }
        @media (max-width: 640px) {
          .header {
            flex-direction: column;
          }
          .badges {
            justify-content: flex-start;
          }
          .hero-temp {
            font-size: 2.2rem;
          }
          .bar-shell {
            height: 136px;
          }
          .bar {
            top: 60px;
          }
          .marker {
            width: 92px;
          }
          .marker-label {
            font-size: 0.62rem;
          }
          .current-line {
            height: 74px;
          }
        }
    `;
    if (this._styleEl.textContent !== styles) this._styleEl.textContent = styles;

    this._setMain(`
        <div class="card-shell">
          <div class="header">
            <div>
              <div class="title">${model.roomName}</div>
              <div class="subtitle">Comfort response curve · tap chips to control</div>
            </div>
            <div class="badges">
              <span class="badge ${this._badgeClass(model.actionBadge)}">${model.actionBadge}</span>
              <span class="badge">${this._titleCase(model.presetMode)}</span>
              <span class="badge">${model.profileBadge}</span>
              ${model.overrideBadge ? `<span class="badge">Override: ${model.overrideBadge}</span>` : ''}
            </div>
          </div>
          <div class="hero">
            <div class="hero-temp">${this._fmtTemp(model.currentTemperature)}</div>
            ${model.currentHumidity !== null ? `<div class="hero-humidity">${this._fmtHumidity(model.currentHumidity)}</div>` : ''}
          </div>
          <div class="bar-area">
            <div class="bar-shell">
              ${this._renderMarkers(model)}
              <div class="bar"></div>
            </div>
            <div class="axis">
              <span>${this._fmtTemp(model.rangeMin)}</span>
              <span>Soft-grey dead zone</span>
              <span>${this._fmtTemp(model.rangeMax)}</span>
            </div>
            ${summaryCards ? `<div class="summary-grid">${summaryCards}</div>` : ''}
          </div>
          <div class="controls-shell">
            ${this._renderModeButtons(model)}
            ${this._renderPresetButtons(model)}
            ${this._renderAggressivenessButtons(model)}
            ${this._renderTemperatureControls(model)}
          </div>
          ${detailsHtml}
        </div>
    `);

    this._renderSchedule();
  }

  // ── Schedule: helpers ──────────────────────────────────────────────────────

  // The schedule that governs this room, published by the thermostat as the
  // `schedule_entity` attribute (a sensor). Null when there is none.
  _schedule() {
    if (!this._config || this._config.show_schedule === false) return null;
    const id = this._state(this._config.entity)?.attributes?.schedule_entity;
    if (!id) return null;
    const stateObj = this._state(id);
    return { id, stateObj, attrs: stateObj?.attributes || {} };
  }

  _scheduleEnabled(attrs) {
    if (typeof attrs.schedule_enabled === 'boolean') return attrs.schedule_enabled;
    const sw = this._state(attrs.switch_entity);
    return sw ? sw.state === 'on' : true;
  }

  _toMin(text) {
    const match = /^(\d{1,2}):(\d{2})(?::\d{2})?$/.exec(String(text ?? '').trim());
    if (!match) return null;
    const hours = Number(match[1]);
    const minutes = Number(match[2]);
    if (hours > 23 || minutes > 59) return null;
    return hours * 60 + minutes;
  }

  _toHHMM(minutes) {
    const pad = (n) => String(n).padStart(2, '0');
    return `${pad(Math.floor(minutes / 60))}:${pad(minutes % 60)}`;
  }

  _lang() {
    return this._hass?.locale?.language || this._hass?.language || undefined;
  }

  _timeOptions() {
    const options = { hour: '2-digit', minute: '2-digit' };
    const format = this._hass?.locale?.time_format;
    if (format === '12') options.hour12 = true;
    if (format === '24') options.hour12 = false;
    return options;
  }

  // A slot time ("HH:MM", minutes since midnight) in the user's 12/24h style.
  _fmtClock(minutes) {
    const hhmm = this._toHHMM(minutes);
    if (minutes >= DAY_MINUTES) return this._hass?.locale?.time_format === '12' ? '12:00 AM' : '24:00';
    try {
      const date = new Date(Date.UTC(2000, 0, 1, Math.floor(minutes / 60), minutes % 60));
      return date.toLocaleTimeString(this._lang(), { ...this._timeOptions(), timeZone: 'UTC' });
    } catch (err) {
      return hhmm;
    }
  }

  // An ISO timestamp (the sensor's state) as a time, with the weekday added
  // when it is not today. Honours the user's "server / local" time zone choice.
  _fmtWhen(iso) {
    if (!iso || iso === 'unknown' || iso === 'unavailable') return null;
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return null;
    const options = this._timeOptions();
    if (this._hass?.locale?.time_zone === 'server' && this._hass?.config?.time_zone) {
      options.timeZone = this._hass.config.time_zone;
    }
    try {
      const dayKey = (d) => d.toLocaleDateString('en-CA', { timeZone: options.timeZone });
      const time = date.toLocaleTimeString(this._lang(), options);
      if (dayKey(date) === dayKey(new Date())) return time;
      const weekday = date.toLocaleDateString(this._lang(), { weekday: 'short', timeZone: options.timeZone });
      return `${weekday} ${time}`;
    } catch (err) {
      return date.toLocaleTimeString();
    }
  }

  // Minutes since midnight in the server's time zone (slots are server time).
  _nowMinutes() {
    try {
      const parts = new Intl.DateTimeFormat('en-GB', {
        timeZone: this._hass?.config?.time_zone || undefined,
        hour: '2-digit',
        minute: '2-digit',
        hourCycle: 'h23',
      }).formatToParts(new Date());
      const get = (type) => Number(parts.find((p) => p.type === type)?.value);
      return (get('hour') % 24) * 60 + get('minute');
    } catch (err) {
      const now = new Date();
      return now.getHours() * 60 + now.getMinutes();
    }
  }

  _presetLabel(preset) {
    return this._escape(this._titleCase(preset, 'None'));
  }

  _presetColor(preset) {
    const safe = String(preset ?? '').toLowerCase().replace(/[^a-z0-9_-]/g, '');
    return safe ? `var(--cc-preset-${safe}, var(--cc-preset-other))` : 'var(--cc-preset-other)';
  }

  // [{start: "HH:MM", preset}] → [{m, preset}] sorted, unreadable times dropped.
  _parseSlots(raw) {
    if (!Array.isArray(raw)) return [];
    return raw
      .map((slot) => ({ m: this._toMin(slot?.start), preset: String(slot?.preset ?? '') }))
      .filter((slot) => slot.m !== null)
      .sort((a, b) => a.m - b.m);
  }

  _normDays(days) {
    if (Array.isArray(days)) {
      const wanted = days.map((d) => String(d).toLowerCase().slice(0, 3));
      return SCHEDULE_DAYS.filter((d) => wanted.includes(d));
    }
    return ['all', 'workdays', 'weekend'].includes(days) ? days : 'all';
  }

  _daySet(days) {
    if (days === 'all') return SCHEDULE_DAYS;
    if (days === 'workdays') return SCHEDULE_DAYS.slice(0, 5);
    if (days === 'weekend') return SCHEDULE_DAYS.slice(5);
    return Array.isArray(days) ? days : [];
  }

  // Mirrors the backend: `all` overlaps all/workdays/weekend; a mode overlaps
  // itself; chosen-day lists overlap when they share a day; chosen days never
  // overlap a mode (they take precedence on their days).
  _daysOverlap(a, b) {
    const aList = Array.isArray(a);
    const bList = Array.isArray(b);
    if (aList && bList) return a.some((d) => b.includes(d));
    if (aList || bList) return false;
    if (a === 'all' || b === 'all') return true;
    return a === b;
  }

  _describeDays(days) {
    if (days.length === 7) return 'every day';
    if (days.length === 5 && SCHEDULE_DAYS.slice(0, 5).every((d) => days.includes(d))) return 'workdays';
    if (days.length === 2 && days.includes('sat') && days.includes('sun')) return 'the weekend';
    return SCHEDULE_DAYS.filter((d) => days.includes(d)).map((d) => SCHEDULE_DAY_LABELS[d]).join(', ');
  }

  // Coloured blocks for a day. A first slot that starts after midnight is
  // preceded by a "carried over" block for the previous day's last preset.
  _segments(slots, carryPreset) {
    if (!slots.length) return [];
    const segments = [];
    if (slots[0].m > 0) {
      segments.push({
        start: 0, end: slots[0].m, preset: carryPreset ?? slots[slots.length - 1].preset, index: -1, carry: true,
      });
    }
    slots.forEach((slot, index) => {
      segments.push({
        start: slot.m,
        end: index + 1 < slots.length ? slots[index + 1].m : DAY_MINUTES,
        preset: slot.preset,
        index,
        carry: false,
      });
    });
    return segments;
  }

  _ticksHtml() {
    return `<div class="sch-ticks" aria-hidden="true">${[0, 6, 12, 18, 24]
      .map((h) => `<span style="left:${(h / 24) * 100}%">${h}</span>`).join('')}</div>`;
  }

  _errorText(err) {
    if (!err) return 'Unknown error';
    if (typeof err === 'string') return err;
    return err.message || err.body?.message || err.error || err.code || String(err);
  }

  // ── Schedule: read-only strip ─────────────────────────────────────────────

  _renderSchedule() {
    if (!this._schedEl) return;
    const sched = this._hass ? this._schedule() : null;
    if (!sched && this._edit && this._config?.show_schedule === false) this._closeEditor();
    const html = sched ? this._scheduleStripHtml(sched) : '';
    if (html === this._schedHtml) return;
    this._schedHtml = html;
    this._schedEl.innerHTML = html;
  }

  _scheduleStripHtml(sched) {
    if (!sched.stateObj) {
      return `<div class="sch-strip"><div class="sch-muted">Schedule ${this._escape(sched.id)} is not available.</div></div>`;
    }
    const a = sched.attrs;
    const enabled = this._scheduleEnabled(a);
    const busy = Boolean(this._schedBusy);
    const editing = Boolean(this._edit);
    const nextAt = this._fmtWhen(sched.stateObj.state);
    const current = a.scheduled_preset || null;
    const next = a.next_preset || null;

    let summary;
    if (!enabled) {
      summary = 'Schedule is off';
    } else if (current) {
      summary = `${this._presetLabel(current)}${nextAt ? ` until ${this._escape(nextAt)}` : ''}${next && next !== current ? ` → ${this._presetLabel(next)}` : ''}`;
    } else if (next && nextAt) {
      summary = `${this._presetLabel(next)} from ${this._escape(nextAt)}`;
    } else {
      summary = 'Nothing scheduled';
    }

    const owner = a.owner_name ? ` · ${this._escape(a.owner_name)}` : '';
    const profile = a.profile_today
      ? `<span class="sch-pill" title="Profile used today">${this._escape(a.profile_today)}</span>`
      : '';

    let band = '';
    if (enabled && a.paused) {
      band = `
        <div class="sch-band paused">
          <span>Paused while Away</span>
          <button class="sch-btn" data-sact="sched-resume" type="button" ${busy ? 'disabled' : ''}>Resume schedule</button>
        </div>`;
    } else if (enabled && a.override && typeof a.override === 'object') {
      const until = this._fmtWhen(a.override.until);
      band = `
        <div class="sch-band">
          <span>${this._presetLabel(a.override.preset)} set by hand — schedule resumes ${until ? `at ${this._escape(until)}` : 'at the next change'}</span>
          <button class="sch-btn" data-sact="sched-resume" type="button" ${busy ? 'disabled' : ''}>Resume schedule</button>
        </div>`;
    }

    const slots = this._parseSlots(a.today_slots);
    const now = this._nowMinutes();
    const carry = slots.length && now < slots[0].m && current ? current : undefined;
    const segments = this._segments(slots, carry);
    const bar = segments.length
      ? `
        <div class="sch-bar-wrap">
          <div class="sch-bar">
            ${segments.map((seg) => {
              const left = (seg.start / DAY_MINUTES) * 100;
              const width = ((seg.end - seg.start) / DAY_MINUTES) * 100;
              const title = seg.carry
                ? `Carried over from the previous day until ${this._fmtClock(seg.end)}`
                : `${this._titleCase(seg.preset)} ${this._fmtClock(seg.start)}–${this._fmtClock(seg.end)}`;
              return `<div class="sch-seg ${seg.carry ? 'carry' : ''}" style="left:${left}%;width:${width}%;background-color:${this._presetColor(seg.preset)}" title="${this._escape(title)}">${!seg.carry && width >= 12 ? this._presetLabel(seg.preset) : ''}</div>`;
            }).join('')}
            <div class="sch-now" style="left:${(now / DAY_MINUTES) * 100}%" title="Now"></div>
          </div>
          ${this._ticksHtml()}
        </div>`
      : `<div class="sch-bar-wrap"><div class="sch-bar empty"><span class="sch-muted">No profile covers today</span></div></div>`;

    const toggle = a.switch_entity
      ? `<button class="sch-switch ${enabled ? 'on' : ''}" data-sact="sched-toggle" type="button" role="switch"
           aria-checked="${enabled}" aria-label="Schedule on or off" title="${enabled ? 'Turn schedule off' : 'Turn schedule on'}" ${busy ? 'disabled' : ''}><span></span></button>`
      : '';

    const error = this._schedError
      ? `<div class="sch-error" role="alert"><span>${this._escape(this._schedError)}</span><button data-sact="sched-dismiss" type="button" aria-label="Dismiss">✕</button></div>`
      : '';

    const stale = editing && this._edit.entityId === sched.id && JSON.stringify(a.profiles ?? null) !== this._edit.baseline
      ? `<div class="sch-note">This schedule was changed elsewhere since you started editing. Saving will replace those changes.</div>`
      : '';

    return `
      <div class="sch-strip ${enabled ? '' : 'off'}">
        <div class="sch-head">
          <button class="sch-head-main" data-sact="sched-info" type="button">
            <span class="sch-title">Schedule${owner}${profile}</span>
            <span class="sch-summary">${summary}</span>
          </button>
          ${toggle}
          <button class="sch-btn" data-sact="sched-edit" type="button" ${editing ? 'disabled' : ''}>${editing ? 'Editing…' : 'Edit schedule'}</button>
        </div>
        ${band}
        ${bar}
        ${error}
        ${stale}
      </div>
    `;
  }

  async _scheduleCall(domain, service, data) {
    if (!this._hass) return;
    this._schedBusy = true;
    this._schedError = null;
    this._renderSchedule();
    try {
      await this._hass.callService(domain, service, data);
    } catch (err) {
      this._schedError = this._errorText(err);
    } finally {
      this._schedBusy = false;
      this._renderSchedule();
    }
  }

  async _onScheduleClick(ev) {
    const target = ev.target.closest('[data-sact]');
    if (!target || target.disabled) return;
    ev.stopPropagation();
    const sched = this._schedule();
    if (!sched) return;
    switch (target.dataset.sact) {
      case 'sched-edit':
        this._openEditor();
        return;
      case 'sched-toggle': {
        const sw = sched.attrs.switch_entity;
        if (!sw) return;
        const on = this._scheduleEnabled(sched.attrs);
        await this._scheduleCall('switch', on ? 'turn_off' : 'turn_on', { entity_id: sw });
        return;
      }
      case 'sched-resume':
        await this._scheduleCall('comfort_climate', 'resume_schedule', { entity_id: sched.id });
        return;
      case 'sched-info':
        this._openMoreInfo(sched.id);
        return;
      case 'sched-dismiss':
        this._schedError = null;
        this._renderSchedule();
        return;
      default:
    }
  }

  // ── Schedule: editor ──────────────────────────────────────────────────────

  _editableProfile(raw) {
    const {
      name, days, enabled, slots, ...extra
    } = raw && typeof raw === 'object' ? raw : {};
    return {
      extra,
      name: String(name ?? ''),
      days: this._normDays(days),
      enabled: enabled !== false,
      slots: this._parseSlots(slots),
    };
  }

  _serializeProfiles(profiles) {
    return profiles.map((p) => ({
      ...p.extra,
      name: p.name.trim(),
      days: Array.isArray(p.days) ? SCHEDULE_DAYS.filter((d) => p.days.includes(d)) : p.days,
      enabled: Boolean(p.enabled),
      slots: p.slots.map((slot) => ({ start: this._toHHMM(slot.m), preset: slot.preset })),
    }));
  }

  _openEditor() {
    const sched = this._schedule();
    if (!sched?.stateObj) return;
    const a = sched.attrs;
    const valid = Array.isArray(a.valid_presets) ? a.valid_presets.map(String).filter(Boolean) : [];
    this._edit = {
      entityId: sched.id,
      ownerName: a.owner_name || '',
      validPresets: valid.length ? valid : SCHEDULE_DEFAULT_PRESETS,
      strictPresets: valid.length > 0,
      profiles: (Array.isArray(a.profiles) ? a.profiles : []).map((p) => this._editableProfile(p)),
      baseline: JSON.stringify(a.profiles ?? null),
      sel: null,
      error: null,
      saving: false,
    };
    this._drag = null;
    this._renderEditor();
    this._renderSchedule();
  }

  _closeEditor() {
    this._edit = null;
    this._drag = null;
    this._renderEditor();
    this._renderSchedule();
  }

  _validateProfiles(profiles, validPresets, strictPresets) {
    const perProfile = profiles.map(() => []);
    const global = [];
    const seen = new Set();
    profiles.forEach((profile, index) => {
      const errors = perProfile[index];
      const name = profile.name.trim();
      if (!name) {
        errors.push('Give this profile a name.');
      } else if (SCHEDULE_NAME_FORBIDDEN.test(name)) {
        errors.push('Names can\'t contain [ ] : # or commas.');
      } else if (seen.has(name.toLowerCase())) {
        errors.push(`Another profile is already called “${name}”.`);
      } else {
        seen.add(name.toLowerCase());
      }
      if (Array.isArray(profile.days) && !profile.days.length) errors.push('Pick at least one day.');
      if (!profile.slots.length) errors.push('Add at least one time slot.');
      let previous = -1;
      const badTimes = profile.slots.some((slot) => {
        const bad = !Number.isInteger(slot.m) || slot.m < 0 || slot.m >= DAY_MINUTES
          || slot.m % SCHEDULE_STEP !== 0 || slot.m <= previous;
        previous = slot.m;
        return bad;
      });
      if (badTimes) errors.push('Slot times must go up in 5-minute steps within the day.');
      if (strictPresets) {
        const badPresets = [...new Set(profile.slots.map((s) => s.preset).filter((p) => !validPresets.includes(p)))];
        if (badPresets.length) {
          errors.push(`Not an allowed preset: ${badPresets.map((p) => this._titleCase(p, '(none)')).join(', ')}.`);
        }
      }
    });
    const label = (profile, index) => `“${profile.name.trim() || `Profile ${index + 1}`}”`;
    for (let i = 0; i < profiles.length; i += 1) {
      for (let j = i + 1; j < profiles.length; j += 1) {
        const a = profiles[i];
        const b = profiles[j];
        if (!a.enabled || !b.enabled || !this._daysOverlap(a.days, b.days)) continue;
        const shared = this._daySet(a.days).filter((d) => this._daySet(b.days).includes(d));
        global.push(`${label(a, i)} and ${label(b, j)} are both switched on for ${this._describeDays(shared)}. Switch one off or change its days.`);
      }
    }
    return {
      profiles: perProfile,
      global,
      ok: !global.length && perProfile.every((errors) => !errors.length),
    };
  }

  _renderEditor() {
    const el = this._editorEl;
    if (!el) return;
    const ed = this._edit;
    if (!ed) {
      el.innerHTML = '';
      return;
    }
    el.innerHTML = `
      <div class="sch-editor" role="region" aria-label="Edit schedule">
        <div>
          <div class="sch-title">Edit ${ed.ownerName ? `${this._escape(ed.ownerName)} ` : ''}schedule</div>
          <div class="sch-muted">Drag a boundary to move a change. Tap a block to change its preset, split it or remove it.</div>
        </div>
        ${ed.profiles.map((profile, index) => this._editorProfileHtml(profile, index)).join('')
          || '<div class="sch-muted">No profiles yet.</div>'}
        <button class="sch-btn wide" data-sact="add-profile" type="button">+ Add profile</button>
        <div class="sch-foot"></div>
      </div>
    `;
    this._renderEditorStatus();
  }

  // Validation messages and the Save/Cancel row. Updated on its own while
  // typing a name, so the text field keeps focus.
  _renderEditorStatus() {
    const ed = this._edit;
    if (!ed || !this._editorEl) return;
    const result = this._validateProfiles(ed.profiles, ed.validPresets, ed.strictPresets);
    ed.profiles.forEach((_, index) => {
      const box = this._editorEl.querySelector(`[data-errs="${index}"]`);
      if (box) box.innerHTML = result.profiles[index].map((m) => `<div class="sch-err">${this._escape(m)}</div>`).join('');
    });
    const foot = this._editorEl.querySelector('.sch-foot');
    if (!foot) return;
    foot.innerHTML = `
      ${result.global.map((m) => `<div class="sch-err">${this._escape(m)}</div>`).join('')}
      ${ed.error ? `<div class="sch-error" role="alert"><span>Couldn't save: ${this._escape(ed.error)}</span></div>` : ''}
      <div class="sch-actions">
        <button class="sch-btn ghost" data-sact="edit-cancel" type="button" ${ed.saving ? 'disabled' : ''}>Cancel</button>
        <button class="sch-btn primary" data-sact="edit-save" type="button" ${result.ok && !ed.saving ? '' : 'disabled'}>${ed.saving ? 'Saving…' : 'Save'}</button>
      </div>
    `;
  }

  _editorProfileHtml(profile, index) {
    const ed = this._edit;
    const isList = Array.isArray(profile.days);
    const implied = this._daySet(profile.days);
    const chip = (value, text, selected, impliedDay) => `
      <button class="sch-chip ${selected ? 'selected' : ''} ${impliedDay ? 'implied' : ''}" data-sact="days"
        data-p="${index}" data-v="${value}" type="button" aria-pressed="${selected}">${text}</button>`;
    const chips = SCHEDULE_DAY_MODES.map(([value, text]) => chip(value, text, profile.days === value, false)).join('')
      + '<span class="sch-chip-break"></span>'
      + SCHEDULE_DAYS.map((d) => chip(d, SCHEDULE_DAY_LABELS[d], isList && profile.days.includes(d), !isList && implied.includes(d))).join('');
    const others = ed.profiles
      .map((other, j) => (j === index ? '' : `<option value="${j}">${this._escape(other.name.trim() || `Profile ${j + 1}`)}</option>`))
      .join('');
    const selected = ed.sel && ed.sel.p === index && ed.sel.s < profile.slots.length ? ed.sel.s : null;
    return `
      <div class="sch-prof ${profile.enabled ? '' : 'off'}">
        <div class="sch-prof-head">
          <input class="sch-name" data-p="${index}" type="text" value="${this._escape(profile.name)}"
            placeholder="Profile name" aria-label="Profile name" autocomplete="off" maxlength="40">
          <button class="sch-switch ${profile.enabled ? 'on' : ''}" data-sact="prof-enabled" data-p="${index}" type="button"
            role="switch" aria-checked="${profile.enabled}" aria-label="Profile enabled"
            title="${profile.enabled ? 'Profile is on' : 'Profile is off'}"><span></span></button>
          <button class="sch-icon" data-sact="prof-delete" data-p="${index}" type="button" title="Delete profile" aria-label="Delete profile">✕</button>
        </div>
        <div class="sch-days" role="group" aria-label="Days">${chips}</div>
        <div>
          <div class="sch-bar edit" data-p="${index}">${this._editorBarInner(profile, index)}</div>
          ${this._ticksHtml()}
        </div>
        ${selected !== null ? this._editorMenuHtml(profile, index, selected) : ''}
        ${others ? `
          <div class="sch-menu-row">
            <select class="sch-copy" data-p="${index}" aria-label="Copy time slots from another profile">
              <option value="">Copy slots from…</option>${others}
            </select>
          </div>` : ''}
        <div data-errs="${index}"></div>
      </div>
    `;
  }

  _editorBarInner(profile, index) {
    const ed = this._edit;
    const drag = this._drag && this._drag.p === index ? this._drag : null;
    const selected = ed?.sel && ed.sel.p === index ? ed.sel.s : null;
    const segments = this._segments(profile.slots).map((seg) => {
      const left = (seg.start / DAY_MINUTES) * 100;
      const width = ((seg.end - seg.start) / DAY_MINUTES) * 100;
      const style = `left:${left}%;width:${width}%;background-color:${this._presetColor(seg.preset)}`;
      if (seg.carry) {
        return `<div class="sch-seg carry" style="${style}" title="Carried over from the previous day"></div>`;
      }
      const range = `${this._fmtClock(seg.start)}–${this._fmtClock(seg.end)}`;
      return `<button class="sch-seg ${selected === seg.index ? 'selected' : ''}" data-sact="seg" data-p="${index}"
        data-s="${seg.index}" type="button" style="${style}"
        aria-label="${this._presetLabel(seg.preset)} ${range}" title="${this._presetLabel(seg.preset)} ${range}">${width >= 12 ? this._presetLabel(seg.preset) : ''}</button>`;
    }).join('');
    const handles = profile.slots.map((slot, s) => {
      if (s === 0 && slot.m === 0) return '';
      const dragging = drag && drag.s === s;
      const time = this._fmtClock(slot.m);
      return `<div class="sch-handle ${dragging ? 'dragging' : ''}" data-p="${index}" data-s="${s}" tabindex="0"
        role="slider" aria-label="Start of ${this._presetLabel(slot.preset)}" aria-valuemin="0" aria-valuemax="${DAY_MINUTES - SCHEDULE_STEP}"
        aria-valuenow="${slot.m}" aria-valuetext="${this._escape(time)}" style="left:${(slot.m / DAY_MINUTES) * 100}%">${dragging ? `<span class="sch-tip">${this._escape(time)}</span>` : ''}</div>`;
    }).join('');
    return `<div class="sch-segs">${segments}</div>${handles}`;
  }

  _editorMenuHtml(profile, index, s) {
    const ed = this._edit;
    const slot = profile.slots[s];
    const end = s + 1 < profile.slots.length ? profile.slots[s + 1].m : DAY_MINUTES;
    const canSplit = end - slot.m >= SCHEDULE_STEP * 2;
    const presets = [...ed.validPresets];
    if (slot.preset && !presets.includes(slot.preset)) presets.push(slot.preset);
    return `
      <div class="sch-menu">
        <div class="sch-menu-row">
          <span class="sch-muted">From</span>
          <input class="sch-time" type="time" step="300" data-p="${index}" data-s="${s}" value="${this._toHHMM(slot.m)}" aria-label="Start time">
          <span class="sch-muted">until ${this._escape(this._fmtClock(end))}</span>
        </div>
        <div class="sch-menu-row" role="group" aria-label="Preset">
          ${presets.map((preset) => `
            <button class="sch-chip preset ${slot.preset === preset ? 'selected' : ''}" data-sact="slot-preset"
              data-p="${index}" data-s="${s}" data-v="${this._escape(preset)}" type="button"
              style="--chip:${this._presetColor(preset)}" aria-pressed="${slot.preset === preset}">${this._presetLabel(preset)}</button>`).join('')}
        </div>
        <div class="sch-menu-row">
          <button class="sch-btn" data-sact="slot-split" data-p="${index}" data-s="${s}" type="button" ${canSplit ? '' : 'disabled'}>Split in two</button>
          <button class="sch-btn" data-sact="slot-remove" data-p="${index}" data-s="${s}" type="button" ${profile.slots.length > 1 ? '' : 'disabled'}>Remove slot</button>
          <button class="sch-btn ghost" data-sact="slot-close" type="button">Done</button>
        </div>
      </div>
    `;
  }

  // Lowest and highest start a slot may take: 5 minutes clear of its neighbours.
  _slotBounds(profile, s) {
    return {
      min: s > 0 ? profile.slots[s - 1].m + SCHEDULE_STEP : 0,
      max: s + 1 < profile.slots.length ? profile.slots[s + 1].m - SCHEDULE_STEP : DAY_MINUTES - SCHEDULE_STEP,
    };
  }

  _snap(minutes) {
    return Math.round(minutes / SCHEDULE_STEP) * SCHEDULE_STEP;
  }

  _onEditorClick(ev) {
    const target = ev.target.closest('[data-sact]');
    const ed = this._edit;
    if (!target || target.disabled || !ed) return;
    ev.stopPropagation();
    const p = Number(target.dataset.p);
    const s = Number(target.dataset.s);
    const value = target.dataset.v;
    const profile = ed.profiles[p];
    switch (target.dataset.sact) {
      case 'prof-enabled':
        profile.enabled = !profile.enabled;
        break;
      case 'prof-delete':
        ed.profiles.splice(p, 1);
        ed.sel = null;
        break;
      case 'days':
        if (SCHEDULE_DAY_MODES.some(([mode]) => mode === value)) {
          profile.days = value;
        } else if (Array.isArray(profile.days)) {
          profile.days = profile.days.includes(value)
            ? profile.days.filter((d) => d !== value)
            : SCHEDULE_DAYS.filter((d) => d === value || profile.days.includes(d));
        } else {
          profile.days = [value];
        }
        break;
      case 'seg':
        ed.sel = ed.sel && ed.sel.p === p && ed.sel.s === s ? null : { p, s };
        break;
      case 'slot-preset':
        profile.slots[s].preset = value;
        break;
      case 'slot-split': {
        const slot = profile.slots[s];
        const end = s + 1 < profile.slots.length ? profile.slots[s + 1].m : DAY_MINUTES;
        const mid = this._snap((slot.m + end) / 2);
        if (mid > slot.m && mid < end) {
          profile.slots.splice(s + 1, 0, { m: mid, preset: slot.preset });
          ed.sel = { p, s: s + 1 };
        }
        break;
      }
      case 'slot-remove':
        if (profile.slots.length > 1) profile.slots.splice(s, 1);
        ed.sel = null;
        break;
      case 'slot-close':
        ed.sel = null;
        break;
      case 'add-profile': {
        const enabledDays = ed.profiles.filter((o) => o.enabled).map((o) => o.days);
        const free = ['all', 'workdays', 'weekend'].find((d) => !enabledDays.some((o) => this._daysOverlap(d, o)));
        const names = new Set(ed.profiles.map((o) => o.name.trim().toLowerCase()));
        let n = ed.profiles.length + 1;
        while (names.has(`profile ${n}`)) n += 1;
        const preset = ed.validPresets.includes('home') ? 'home' : (ed.validPresets[0] || 'home');
        ed.profiles.push({
          extra: {}, name: `Profile ${n}`, days: free || 'all', enabled: Boolean(free), slots: [{ m: 0, preset }],
        });
        ed.sel = null;
        break;
      }
      case 'edit-cancel':
        this._closeEditor();
        return;
      case 'edit-save':
        this._saveEditor();
        return;
      default:
        return;
    }
    ed.error = null;
    this._renderEditor();
  }

  _onEditorInput(ev) {
    const target = ev.target;
    const ed = this._edit;
    if (!ed || !target.classList?.contains('sch-name')) return;
    const profile = ed.profiles[Number(target.dataset.p)];
    if (!profile) return;
    profile.name = target.value;
    ed.error = null;
    this._renderEditorStatus();
  }

  _onEditorChange(ev) {
    const target = ev.target;
    const ed = this._edit;
    if (!ed) return;
    const profile = ed.profiles[Number(target.dataset.p)];
    if (!profile) return;
    if (target.classList.contains('sch-copy')) {
      if (target.value === '') return;
      const source = ed.profiles[Number(target.value)];
      if (source) profile.slots = source.slots.map((slot) => ({ ...slot }));
      ed.sel = null;
    } else if (target.classList.contains('sch-time')) {
      const s = Number(target.dataset.s);
      const minutes = this._toMin(target.value);
      if (minutes !== null && profile.slots[s]) {
        const { min, max } = this._slotBounds(profile, s);
        profile.slots[s].m = this._clamp(this._snap(minutes), min, max);
      }
    } else {
      return;
    }
    ed.error = null;
    this._renderEditor();
  }

  // Keyboard alternative to dragging a boundary.
  _onEditorKeyDown(ev) {
    const handle = ev.target.closest?.('.sch-handle');
    const ed = this._edit;
    if (!handle || !ed || this._drag) return;
    const p = Number(handle.dataset.p);
    const s = Number(handle.dataset.s);
    const profile = ed.profiles[p];
    const slot = profile?.slots[s];
    if (!slot) return;
    const { min, max } = this._slotBounds(profile, s);
    const steps = {
      ArrowLeft: -SCHEDULE_STEP, ArrowDown: -SCHEDULE_STEP, ArrowRight: SCHEDULE_STEP, ArrowUp: SCHEDULE_STEP,
      PageDown: -60, PageUp: 60,
    };
    let next;
    if (ev.key in steps) next = slot.m + steps[ev.key];
    else if (ev.key === 'Home') next = min;
    else if (ev.key === 'End') next = max;
    else return;
    ev.preventDefault();
    slot.m = this._clamp(next, min, max);
    ed.error = null;
    this._renderEditor();
    this._editorEl.querySelector(`.sch-bar[data-p="${p}"] .sch-handle[data-s="${s}"]`)?.focus();
  }

  // Drag a boundary: moves the later slot's start, snapped to 5 minutes and
  // clamped between its neighbours. Capture goes on the bar (which survives
  // its own redraws), so the handle can be redrawn under the finger.
  _onEditorPointerDown(ev) {
    const handle = ev.target.closest?.('.sch-handle');
    const ed = this._edit;
    if (!handle || !ed || this._drag) return;
    if (ev.pointerType === 'mouse' && ev.button !== 0) return;
    const p = Number(handle.dataset.p);
    const s = Number(handle.dataset.s);
    const profile = ed.profiles[p];
    const slot = profile?.slots[s];
    const bar = handle.closest('.sch-bar');
    if (!slot || !bar) return;
    ev.preventDefault();
    const { min, max } = this._slotBounds(profile, s);
    const drag = {
      p, s, min, max, slot, bar, profile, pointerId: ev.pointerId,
    };
    this._drag = drag;
    try {
      bar.setPointerCapture(ev.pointerId);
    } catch (err) {
      // Capture is a nicety; window-level moves still arrive while pressed.
    }
    const redraw = () => {
      bar.innerHTML = this._editorBarInner(profile, p);
    };
    const move = (e) => {
      if (e.pointerId !== drag.pointerId) return;
      e.preventDefault();
      const rect = bar.getBoundingClientRect();
      if (!rect.width) return;
      const minutes = this._clamp(this._snap(((e.clientX - rect.left) / rect.width) * DAY_MINUTES), drag.min, drag.max);
      if (minutes !== drag.slot.m) {
        drag.slot.m = minutes;
        redraw();
      }
    };
    const end = (e) => {
      if (this._drag !== drag || (e && e.pointerId !== drag.pointerId)) return;
      this._drag = null;
      bar.removeEventListener('pointermove', move);
      bar.removeEventListener('pointerup', end);
      bar.removeEventListener('pointercancel', end);
      bar.removeEventListener('lostpointercapture', end);
      try {
        bar.releasePointerCapture(drag.pointerId);
      } catch (err) {
        // Already released.
      }
      if (this._edit === ed) {
        ed.error = null;
        this._renderEditor();
      }
    };
    bar.addEventListener('pointermove', move);
    bar.addEventListener('pointerup', end);
    bar.addEventListener('pointercancel', end);
    bar.addEventListener('lostpointercapture', end);
    redraw();
  }

  async _saveEditor() {
    const ed = this._edit;
    if (!ed || ed.saving || !this._hass) return;
    if (!this._validateProfiles(ed.profiles, ed.validPresets, ed.strictPresets).ok) return;
    ed.saving = true;
    ed.error = null;
    this._renderEditorStatus();
    try {
      await this._hass.callService('comfort_climate', 'set_schedule', {
        entity_id: ed.entityId,
        profiles: this._serializeProfiles(ed.profiles),
      });
      if (this._edit === ed) this._closeEditor();
    } catch (err) {
      if (this._edit !== ed) return;
      ed.saving = false;
      ed.error = this._errorText(err);
      this._renderEditorStatus();
    }
  }
}

// The integration loads this file automatically. A dashboard resource left
// over from an older setup may load it a second time; define the card once.
if (!customElements.get('climate-comfort-card')) {
  customElements.define('climate-comfort-card', ClimateComfortCard);
}

window.customCards = window.customCards || [];
window.customCards = window.customCards.filter((card) => card.type !== 'climate-comfort-card');
window.customCards.push({
  type: 'climate-comfort-card',
  preview: true,
  documentationURL: 'https://github.com/bjscuba135/climate-comfort#dashboard-card',
  name: 'Climate Comfort Card',
  description: 'Interactive comfort-band card for Climate Comfort entities with trigger stages, aggressiveness, and humidity markers.',
  // Card picker suggestions, opt-in from Home Assistant 2026.6. Older versions
  // ignore this key, so it is safe to ship unconditionally.
  //
  // Deliberately narrow: a plain climate entity is not a Climate Comfort room and
  // this card would render nothing useful for one. Suggesting it for every
  // thermostat in the house would just make the picker noisy, so we match on the
  // attributes only our own thermostat publishes.
  getEntitySuggestion: (hass, entityId) => {
    if (entityId.split('.')[0] !== 'climate') {
      return null;
    }
    const attrs = hass?.states?.[entityId]?.attributes;
    if (!attrs || attrs.comfort_zone === undefined || attrs.effective_setpoint === undefined) {
      return null;
    }
    return {
      config: { type: 'custom:climate-comfort-card', entity: entityId },
    };
  },
});
