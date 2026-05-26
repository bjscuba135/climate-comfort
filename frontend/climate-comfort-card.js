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

class ClimateComfortCard extends HTMLElement {
  static getStubConfig() {
    return {
      entity: 'climate.conservatory',
      aggressiveness_entity: 'select.conservatory_aggressiveness',
      triggers: [],
      show_details: true,
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
    return this._config?.show_details ? 8 : 6;
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
    const aggressiveness = this._state(this._config?.aggressiveness_entity);
    const attrs = climate.attributes || {};
    const currentTemperature = this._num(attrs.current_temperature);
    const currentHumidity = this._num(attrs.current_humidity);
    const lowerThreshold = this._num(attrs.lower_threshold);
    const upperThreshold = this._num(attrs.upper_threshold);
    const presetMode = attrs.preset_mode || attrs.mode || null;
    const activeProfile = attrs.profile || null;
    const activeDevices = Array.isArray(attrs.active_devices) ? attrs.active_devices : [];
    const supportedFeatures = Number(attrs.supported_features || 0);

    const stages = this._config.triggers
      .map((trigger, index) => this._normalizeTrigger(trigger, index))
      .filter(Boolean)
      .map((stage) => ({
        ...stage,
        active: stage.active || (stage.controlledEntity ? activeDevices.includes(stage.controlledEntity) : false),
      }));

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
        if (!this._config.aggressiveness_entity) return;
        await this._callService('select', 'select_option', {
          entity_id: this._config.aggressiveness_entity,
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

  _render() {
    if (!this._config) return;
    if (!this.shadowRoot) this.attachShadow({ mode: 'open' });
    if (!this._hass) {
      this.shadowRoot.innerHTML = `<ha-card><div class="pad">Waiting for Home Assistant…</div></ha-card>`;
      return;
    }

    const model = this._buildModel();
    if (!model) {
      this.shadowRoot.innerHTML = `<ha-card><div class="pad">Entity ${this._config.entity} not found.</div></ha-card>`;
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

    this.shadowRoot.innerHTML = `
      <style>
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
      </style>
      <ha-card>
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
      </ha-card>
    `;

    this._bindEvents(this.shadowRoot);
  }
}

customElements.define('climate-comfort-card', ClimateComfortCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: 'climate-comfort-card',
  name: 'Climate Comfort Card',
  description: 'Interactive comfort-band card for Climate Comfort entities with trigger stages, aggressiveness, and humidity markers.',
});
