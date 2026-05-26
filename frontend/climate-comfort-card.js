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
    return this._config?.show_details ? 6 : 4;
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

  _normalizeTrigger(trigger) {
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
    };
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

    const stages = this._config.triggers
      .map((trigger) => this._normalizeTrigger(trigger))
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

    return {
      climate,
      aggressiveness,
      roomName: this._config.name || attrs.friendly_name || climate.entity_id,
      currentTemperature,
      currentHumidity,
      lowerThreshold,
      upperThreshold,
      presetMode,
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
      rangeMin,
      rangeMax,
      showDetails: this._config.show_details !== false,
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

  _summary(model) {
    const activeTempStage = model.tempStages.find((stage) => stage.active);
    const activeHumidityStage = model.humidityStage?.active ? model.humidityStage : null;
    if (activeTempStage) {
      return `${this._titleCase(model.actionBadge)} active — ${activeTempStage.label} engaged`;
    }
    if (activeHumidityStage) {
      return `${activeHumidityStage.label} active above ${this._fmtHumidity(activeHumidityStage.thresholdValue)}`;
    }

    const current = model.currentTemperature;
    const candidates = [];
    for (const stage of model.heatingStages) {
      if (current !== null && current > stage.thresholdValue) {
        candidates.push({
          distance: current - stage.thresholdValue,
          text: `Next heat stage: ${stage.label} at ${this._fmtTemp(stage.thresholdValue)}`,
        });
      }
    }
    for (const stage of model.coolingStages) {
      if (current !== null && current < stage.thresholdValue) {
        candidates.push({
          distance: stage.thresholdValue - current,
          text: `Next cool stage: ${stage.label} at ${this._fmtTemp(stage.thresholdValue)}`,
        });
      }
    }
    candidates.sort((a, b) => a.distance - b.distance);

    if (
      current !== null &&
      model.lowerThreshold !== null &&
      model.upperThreshold !== null &&
      current >= model.lowerThreshold &&
      current <= model.upperThreshold
    ) {
      if (candidates[0]) return `Stable — ${candidates[0].text}`;
      return 'Stable — inside the dead zone';
    }

    if (model.humidityStage && model.currentHumidity !== null && model.currentHumidity < model.humidityStage.thresholdValue) {
      return `${candidates[0]?.text || 'Temperature stable'} · Dry mode above ${this._fmtHumidity(model.humidityStage.thresholdValue)}`;
    }

    return candidates[0]?.text || 'Monitoring thresholds';
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

  _renderMarkers(model) {
    const markers = [];
    for (const stage of model.tempStages) {
      const left = this._pct(model, stage.thresholdValue);
      if (left === null) continue;
      const activeClass = stage.active ? 'marker active' : 'marker';
      const kindClass = stage.kind === 'heating' ? 'heating' : 'cooling';
      markers.push(`
        <div class="${activeClass} ${kindClass}" style="left:${left}%">
          <span class="dot"></span>
          <span class="marker-label">${stage.label}</span>
        </div>
      `);
    }

    const currentLeft = this._pct(model, model.currentTemperature);
    if (currentLeft !== null) {
      markers.push(`
        <div class="current-marker" style="left:${currentLeft}%">
          <span class="current-line"></span>
          <span class="current-pill">${this._fmtTemp(model.currentTemperature)}</span>
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
            <div class="stage-chip ${stage.active ? 'active' : ''} ${stage.kind}">
              <span class="stage-chip-label">${stage.label}</span>
              <span class="stage-chip-value">${this._fmtTemp(stage.thresholdValue)}</span>
            </div>
          `).join('')}
        </div>
      </div>
    `;
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

    const humidityHtml = model.humidityStage ? `
      <div class="humidity-row ${model.humidityStage.active ? 'active' : ''}">
        <span class="humidity-icon">💧</span>
        <span class="humidity-text">${model.humidityStage.label} above ${this._fmtHumidity(model.humidityStage.thresholdValue)}</span>
      </div>
    ` : '';

    const detailsHtml = model.showDetails ? `
      <details class="details-shell">
        <summary>Trigger details</summary>
        ${this._renderStageList(model.heatingStages, 'Heating stages')}
        ${this._renderStageList(model.coolingStages, 'Cooling stages')}
        <div class="meta-grid">
          <div class="meta-row"><span>Current</span><strong>${this._fmtTemp(model.currentTemperature)}</strong></div>
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
          display: block;
        }
        ha-card {
          padding: 18px;
          border-radius: 20px;
          overflow: hidden;
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
          height: 74px;
          padding-top: 24px;
        }
        .bar {
          position: relative;
          height: 18px;
          border-radius: 999px;
          overflow: visible;
          background: ${this._barGradient(model)};
          box-shadow: inset 0 0 0 1px rgba(255,255,255,0.12);
        }
        .boundary {
          position: absolute;
          top: 16px;
          width: 2px;
          height: 22px;
          background: rgba(255,255,255,0.32);
          transform: translateX(-1px);
          z-index: 2;
        }
        .marker {
          position: absolute;
          top: 8px;
          transform: translateX(-50%);
          z-index: 3;
          text-align: center;
          max-width: 108px;
        }
        .marker .dot {
          width: 12px;
          height: 12px;
          border-radius: 50%;
          display: block;
          margin: 0 auto 8px;
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
        }
        .current-marker {
          position: absolute;
          top: -8px;
          transform: translateX(-50%);
          z-index: 4;
          text-align: center;
        }
        .current-line {
          display: block;
          width: 3px;
          height: 34px;
          margin: 0 auto 8px;
          border-radius: 3px;
          background: rgba(255,255,255,0.92);
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
        }
        .axis {
          display: flex;
          justify-content: space-between;
          color: var(--cc-text-soft);
          font-size: 0.72rem;
          margin-top: 6px;
        }
        .summary {
          margin-top: 14px;
          padding: 10px 12px;
          border-radius: 14px;
          background: rgba(148, 163, 184, 0.08);
          border: 1px solid var(--cc-border);
          font-size: 0.92rem;
          font-weight: 600;
        }
        .humidity-row {
          margin-top: 12px;
          display: inline-flex;
          align-items: center;
          gap: 8px;
          border-radius: 999px;
          padding: 6px 10px;
          background: rgba(45, 212, 191, 0.1);
          border: 1px solid rgba(45, 212, 191, 0.24);
          color: var(--cc-text-main);
          font-size: 0.8rem;
          font-weight: 600;
        }
        .humidity-row.active {
          background: rgba(45, 212, 191, 0.18);
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
          .marker-label {
            display: none;
          }
          .bar-shell {
            height: 62px;
          }
        }
      </style>
      <ha-card>
        <div class="header">
          <div>
            <div class="title">${model.roomName}</div>
            <div class="subtitle">Comfort response curve · auto-fit scale</div>
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
          ${humidityHtml}
          <div class="summary">${this._summary(model)}</div>
        </div>
        ${detailsHtml}
      </ha-card>
    `;
  }
}

customElements.define('climate-comfort-card', ClimateComfortCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: 'climate-comfort-card',
  name: 'Climate Comfort Card',
  description: 'Visual comfort-band card for Climate Comfort entities with trigger stages, aggressiveness, and humidity markers.',
});
