/* WLED Task Map card - visual LED rule builder.
   Add via dashboard: type "custom:wled-taskmap-card" (appears in the card picker). */

const SUGGESTED_STATES = ["unavailable", "unknown", "error", "problem", "on", "off", "open", "failed", "idle"];

// Known possible states per domain (besides unavailable/unknown, which always apply)
const DOMAIN_STATES = {
  light: ["on", "off"],
  switch: ["on", "off"],
  binary_sensor: ["on", "off"],
  input_boolean: ["on", "off"],
  automation: ["on", "off"],
  script: ["on", "off"],
  fan: ["on", "off"],
  cover: ["open", "closed", "opening", "closing"],
  lock: ["locked", "unlocked", "locking", "unlocking", "jammed"],
  person: ["home", "not_home"],
  device_tracker: ["home", "not_home"],
  sun: ["above_horizon", "below_horizon"],
  media_player: ["playing", "paused", "idle", "off", "on", "standby", "buffering"],
  vacuum: ["cleaning", "docked", "paused", "idle", "returning", "error"],
  climate: ["off", "heat", "cool", "heat_cool", "auto", "dry", "fan_only"],
  timer: ["idle", "active", "paused"],
  update: ["on", "off"],
  alarm_control_panel: ["disarmed", "armed_home", "armed_away", "armed_night", "pending", "triggered"],
  water_heater: ["off", "eco", "electric", "performance", "high_demand", "heat_pump", "gas"],
  calendar: ["on", "off"],
  weather: ["clear-night", "cloudy", "fog", "hail", "lightning", "partlycloudy", "pouring", "rainy", "snowy", "sunny", "windy"],
  printer: ["idle", "printing", "error"],
};

class WledTaskmapCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._selected = new Set();
    this._rules = [];
    this._editing = null; // index being edited, or null
    this._formOpen = false;
    this._form = { entity: "", states: new Set(), color: "#FF0000", effect: "solid" };
    this._quiet = { start: "", end: "", mode: "off" };
    this._dragging = false;
    this._dragMode = true;
    this._loaded = false;
  }

  setConfig(config) { this._config = config || {}; }
  static getStubConfig() { return {}; }
  getCardSize() { return 5; }

  set hass(hass) {
    this._hass = hass;
    if (!this._loaded) { this._loaded = true; this._load(); }
  }

  async _load() {
    try {
      const data = await this._hass.callWS({ type: "wled_taskmap/get_config" });
      const entries = data.entries || [];
      this._entry = this._config.entry_id
        ? entries.find((e) => e.entry_id === this._config.entry_id)
        : entries[0];
      if (this._entry) {
        this._rules = JSON.parse(JSON.stringify(this._entry.rules || []));
        this._quiet = Object.assign({ start: "", end: "", mode: "off" }, this._entry.quiet || {});
        this._segment = this._entry.segment ?? 0;
        this._pet = Object.assign({ enabled: false, start: 0, size: 3, sources: [] }, this._entry.pet || {});
      }
      this._render();
    } catch (e) {
      this.shadowRoot.innerHTML = `<ha-card><div style="padding:16px">WLED Task Map: ${e.message || e}</div></ha-card>`;
    }
  }

  async _save() {
    await this._hass.callWS({
      type: "wled_taskmap/save_rules",
      entry_id: this._entry.entry_id,
      rules: this._rules.map((r) => ({
        entity_id: r.entity_id,
        leds: r.leds,
        color: r.color.replace("#", "").toUpperCase(),
        alert_states: r.alert_states,
        effect: r.effect || "solid",
        for_minutes: r.for_minutes || 0,
        fill_min: r.fill_min ?? 0,
        fill_max: r.fill_max ?? 100,
        color2: r.color2 || "",
      })),
    });
  }

  async _saveQuiet() {
    await this._hass.callWS({
      type: "wled_taskmap/save_settings",
      entry_id: this._entry.entry_id,
      quiet_start: this._quiet.start || "",
      quiet_end: this._quiet.end || "",
      quiet_mode: this._quiet.mode || "off",
      segment: parseInt(this._segment, 10) || 0,
    });
  }

  async _testRule(i) {
    const r = this._rules[i];
    await this._hass.callWS({
      type: "wled_taskmap/test_rule",
      entry_id: this._entry.entry_id,
      leds: r.leds,
      color: r.color,
    });
  }

  async _savePet() {
    await this._hass.callWS({
      type: "wled_taskmap/save_pet",
      entry_id: this._entry.entry_id,
      enabled: !!this._pet.enabled,
      start: parseInt(this._pet.start, 10) || 0,
      size: Math.max(2, parseInt(this._pet.size, 10) || 3),
      sources: this._pet.sources || [],
    });
  }

  _moreInfo(entityId) {
    const ev = new CustomEvent("hass-more-info", {
      bubbles: true, composed: true, detail: { entityId },
    });
    this.dispatchEvent(ev);
  }

  // ---------- interactions ----------

  _toggleLed(i) {
    if (this._selected.has(i)) this._selected.delete(i); else this._selected.add(i);
    this._render();
  }

  _openForm(editIndex = null) {
    this._formOpen = true;
    this._editing = editIndex;
    if (editIndex !== null) {
      const r = this._rules[editIndex];
      this._selected = new Set(r.leds);
      this._form = {
        entity: r.entity_id,
        states: new Set(r.alert_states.split(",").map((s) => s.trim()).filter(Boolean)),
        color: "#" + r.color.replace("#", ""),
        effect: r.effect || "solid",
        forMin: r.for_minutes || 0,
        fillMin: r.fill_min ?? 0,
        fillMax: r.fill_max ?? 100,
        colorStyle: r.color2 === "RAINBOW" ? "rainbow" : r.color2 ? "gradient" : "single",
        color2: r.color2 && r.color2 !== "RAINBOW" ? "#" + r.color2 : "#00C853",
      };
    } else {
      this._form = { entity: "", states: new Set(["unavailable", "error"]), color: "#FF0000", effect: "solid", forMin: 0, fillMin: 0, fillMax: 100, colorStyle: "single", color2: "#00C853" };
    }
    this._render();
  }

  _closeForm() {
    this._formOpen = false;
    this._editing = null;
    this._selected.clear();
    this._render();
  }

  async _submitForm() {
    const leds = [...this._selected].sort((a, b) => a - b);
    const entity = this._form.entity.trim();
    if (!entity || !this._hass.states[entity]) return this._flash("Pick a valid entity");
    if (!leds.length) return this._flash("Tap some LEDs on the strip first");
    const isTodo = entity.startsWith("todo.");
    const isFill = this._form.effect === "fill";
    if (!isTodo && !isFill && !this._form.states.size) return this._flash("Pick at least one state");
    const rule = {
      entity_id: entity,
      leds,
      color: this._form.color.replace("#", "").toUpperCase(),
      alert_states: [...this._form.states].join(","),
      effect: this._form.effect || "solid",
      for_minutes: Math.max(0, parseFloat(this._form.forMin) || 0),
      fill_min: parseFloat(this._form.fillMin) || 0,
      fill_max: parseFloat(this._form.fillMax) || 100,
      color2: this._form.colorStyle === "rainbow" ? "RAINBOW"
        : this._form.colorStyle === "gradient" ? this._form.color2.replace("#", "").toUpperCase() : "",
    };
    if (this._editing !== null) this._rules[this._editing] = rule;
    else this._rules.push(rule);
    await this._save();
    this._closeForm();
  }

  async _deleteRule(i) {
    this._rules.splice(i, 1);
    await this._save();
    this._render();
  }

  _flash(msg) {
    const el = this.shadowRoot.querySelector(".flash");
    if (el) { el.textContent = msg; el.style.opacity = 1; setTimeout(() => (el.style.opacity = 0), 2500); }
  }

  _entityStateSuggestions() {
    const entity = this._form.entity.trim();
    const st = this._hass.states[entity];
    const set = new Set();
    if (st) {
      // Entity-specific possible states, most relevant first
      const domain = entity.split(".")[0];
      const attrs = st.attributes || {};
      // Enum sensors / select / input_select expose their full option list
      (attrs.options || []).forEach((o) => set.add(String(o)));
      if (domain === "climate") (attrs.hvac_modes || []).forEach((m) => set.add(String(m)));
      (DOMAIN_STATES[domain] || []).forEach((s) => set.add(s));
      set.add(st.state); // whatever it reports right now
      set.add("unavailable");
      set.add("unknown");
    } else {
      SUGGESTED_STATES.forEach((s) => set.add(s));
    }
    this._form.states.forEach((s) => set.add(s));
    return [...set];
  }

  // ---------- rendering ----------

  static _hsv2hex(h, s, v) {
    const f = (n) => { const k = (n + h * 6) % 6; return v - v * s * Math.max(0, Math.min(k, 4 - k, 1)); };
    return "#" + [f(5), f(3), f(1)].map((x) => Math.round(x * 255).toString(16).padStart(2, "0")).join("");
  }

  static _hex2hsv(hex) {
    const r = parseInt(hex.slice(1, 3), 16) / 255, g = parseInt(hex.slice(3, 5), 16) / 255, b = parseInt(hex.slice(5, 7), 16) / 255;
    const mx = Math.max(r, g, b), mn = Math.min(r, g, b), d = mx - mn;
    let h = 0;
    if (d) h = mx === r ? ((g - b) / d % 6) / 6 : mx === g ? ((b - r) / d + 2) / 6 : ((r - g) / d + 4) / 6;
    if (h < 0) h += 1;
    return [h, mx ? d / mx : 0, mx];
  }

  _previewColor(i) {
    // Gradient/rainbow-aware color for selected LED i (matches backend hue blending)
    const sel = [...this._selected].sort((a, b) => a - b);
    const pos = sel.indexOf(i), n = sel.length;
    const t = n > 1 ? pos / (n - 1) : 0;
    if (this._form.colorStyle === "rainbow") return WledTaskmapCard._hsv2hex(0.75 * t, 1, 1);
    if (this._form.colorStyle === "gradient") {
      const [h1, s1, v1] = WledTaskmapCard._hex2hsv(this._form.color);
      const [h2, s2, v2] = WledTaskmapCard._hex2hsv(this._form.color2);
      let dh = h2 - h1;
      if (dh > 0.5) dh -= 1; else if (dh < -0.5) dh += 1;
      return WledTaskmapCard._hsv2hex(((h1 + dh * t) % 1 + 1) % 1, s1 + (s2 - s1) * t, v1 + (v2 - v1) * t);
    }
    return this._form.color;
  }

  static _ruleColorAt(rule, i) {
    const block = [...rule.leds].sort((a, b) => a - b);
    const pos = block.indexOf(i), n = block.length;
    const t = n > 1 ? pos / (n - 1) : 0;
    if (rule.color2 === "RAINBOW") return WledTaskmapCard._hsv2hex(0.75 * t, 1, 1);
    if (rule.color2) {
      const [h1, s1, v1] = WledTaskmapCard._hex2hsv("#" + rule.color);
      const [h2, s2, v2] = WledTaskmapCard._hex2hsv("#" + rule.color2);
      let dh = h2 - h1;
      if (dh > 0.5) dh -= 1; else if (dh < -0.5) dh += 1;
      return WledTaskmapCard._hsv2hex(((h1 + dh * t) % 1 + 1) % 1, s1 + (s2 - s1) * t, v1 + (v2 - v1) * t);
    }
    return "#" + rule.color;
  }

  _ledColor(i) {
    if (this._selected.has(i)) return null; // selection style wins
    for (let r = this._rules.length - 1; r >= 0; r--) {
      if (this._rules[r].leds.includes(i)) return WledTaskmapCard._ruleColorAt(this._rules[r], i);
    }
    return null;
  }

  _render() {
    if (!this._entry) {
      this.shadowRoot.innerHTML =
        `<ha-card><div style="padding:16px">No WLED Task Map device found. Add the integration first (Settings → Devices &amp; Services).</div></ha-card>`;
      return;
    }
    const n = this._entry.led_count || 30;
    const isFill = this._form.effect === "fill";
    const entId = this._form.entity.trim();
    const editingTodo = !isFill && entId.startsWith("todo.");
    const entState = this._hass.states[entId];
    // Numeric sensor (battery %, temperature...) without a fixed option list
    const isNumeric = !isFill && !editingTodo && !!entState
      && !(entState.attributes || {}).options
      && entState.state !== "" && !isNaN(parseFloat(entState.state)) && isFinite(entState.state);

    const leds = Array.from({ length: n }, (_, i) => {
      const ruleColor = this._ledColor(i);
      const sel = this._selected.has(i);
      const pc = sel ? this._previewColor(i) : null;
      const style = sel
        ? `background:${pc};box-shadow:0 0 6px ${pc};border-color:var(--primary-text-color)`
        : ruleColor
        ? `background:${ruleColor};opacity:.45`
        : "";
      return `<div class="led ${sel ? "sel" : ""}" data-i="${i}" style="${style}" title="LED ${i}"></div>`;
    }).join("");

    const rules = this._rules.map((r, i) => {
      const name = this._hass.states[r.entity_id]?.attributes?.friendly_name || r.entity_id;
      const when = r.effect === "fill"
        ? `fills ${r.fill_min ?? 0}–${r.fill_max ?? 100}`
        : r.entity_id.startsWith("todo.")
        ? "has pending items"
        : `is ${r.alert_states.split(",").join(" / ")}`;
      const ledsTxt = r.leds.length > 6 ? `${r.leds.length} LEDs` : `LED ${r.leds.join(", ")}`;
      const fx = (r.effect === "blink" ? " · ⚡ blink" : r.effect === "pulse" ? " · 〰 pulse" : r.effect === "fill" ? " · ▮▯ fill bar" : "")
        + (r.color2 === "RAINBOW" ? " · 🌈" : r.color2 ? " · gradient" : "")
        + (r.for_minutes > 0 ? ` · ⏱ after ${r.for_minutes}m` : "");
      return `<div class="rule">
        <span class="dot" style="background:#${r.color}"></span>
        <span class="rtext" data-info="${r.entity_id}" title="Show entity details"><b>${name}</b> ${when} → ${ledsTxt}${fx}</span>
        <button class="icon" data-test="${i}" title="Flash these LEDs on the strip">🔦</button>
        <button class="icon" data-edit="${i}" title="Edit">✏️</button>
        <button class="icon" data-del="${i}" title="Delete">🗑</button>
      </div>`;
    }).join("") || `<div class="empty">No alerts yet. Tap “Add alert”.</div>`;

    const stateChips = this._formOpen && !editingTodo
      ? this._entityStateSuggestions().map((s) =>
          `<button class="chip ${this._form.states.has(s) ? "on" : ""}" data-state="${s}">${s}</button>`
        ).join("")
      : "";

    const entityOptions = this._formOpen
      ? Object.keys(this._hass.states).sort().map((e) => `<option value="${e}">`).join("")
      : "";

    const form = this._formOpen ? `
      <div class="form">
        <div class="step"><span class="num">1</span> Tap the LEDs on the strip above that should light up <span class="count">(${this._selected.size} selected)</span></div>
        <div class="step"><span class="num">2</span> When this entity…</div>
        <input class="entity" list="entities" placeholder="Start typing… e.g. sensor.printer" value="${this._form.entity}">
        <datalist id="entities">${entityOptions}</datalist>
        ${isFill
          ? `<div class="step"><span class="num">3</span> Fill the LEDs as its value goes from
             <input type="number" class="fillmin" value="${this._form.fillMin}" style="width:64px"> to
             <input type="number" class="fillmax" value="${this._form.fillMax}" style="width:64px"></div>
             <div class="hint">Progress bar: at the first value no LEDs are lit, at the second all selected LEDs are. E.g. 0 to 100 for a print-progress sensor.</div>`
          : editingTodo
          ? `<div class="hint">To-do list: lights up whenever it has pending items.</div>`
          : isNumeric
          ? `<div class="step"><span class="num">3</span> What should the LEDs show?</div>
             <div class="chips"><button class="chip tobar">▮▯ Its level, as a ${this._form.colorStyle !== "single" ? this._form.colorStyle + " " : ""}bar (no conditions needed)</button></div>
             <div class="hint" style="margin:8px 0 4px">…or alert only when its value is:</div>
             <div class="chips">
               <select class="cmpop">
                 <option value="<">below</option><option value=">">above</option>
                 <option value="<=">at most</option><option value=">=">at least</option>
                 <option value="=">exactly</option><option value="!=">not</option>
               </select>
               <input type="number" class="cmpval" placeholder="${entState.state}" style="width:80px">
               <button class="chip addcmp">add</button>
               ${["unavailable","unknown"].map((s) =>
                 `<button class="chip ${this._form.states.has(s) ? "on" : ""}" data-state="${s}">${s}</button>`).join("")}
             </div>
             <div class="chips" style="margin-top:6px">${[...this._form.states].filter((s)=>!["unavailable","unknown"].includes(s)).map((s) =>
               `<button class="chip on" data-state="${s}">${s} ✕</button>`).join("")}</div>
             <div class="hint">Current value: <b>${entState.state}</b>${entState.attributes.unit_of_measurement ? " " + entState.attributes.unit_of_measurement : ""}. E.g. battery: “below 20” to alert when low.</div>`
          : `<div class="step"><span class="num">3</span> …is in one of these states</div><div class="chips">${stateChips}
             <input class="newstate" placeholder="other…" size="8"></div>
             <div class="hint">Number sensor? Type a comparison instead, e.g. <b>&gt;80</b> or <b>&lt;20</b></div>`}
        <div class="step"><span class="num">${editingTodo ? 3 : 4}</span> Light them in this color
          <select class="colorstyle">
            <option value="single" ${this._form.colorStyle === "single" ? "selected" : ""}>single</option>
            <option value="gradient" ${this._form.colorStyle === "gradient" ? "selected" : ""}>gradient</option>
            <option value="rainbow" ${this._form.colorStyle === "rainbow" ? "selected" : ""}>rainbow</option>
          </select>
          ${this._form.colorStyle !== "rainbow" ? `<input type="color" class="color" value="${this._form.color}">` : ""}
          ${this._form.colorStyle === "gradient" ? `→ <input type="color" class="color2" value="${this._form.color2}">` : ""}
          <span class="chips" style="display:inline-flex;margin-left:10px">
            ${["solid","blink","pulse","fill"].map((e) =>
              `<button class="chip ${this._form.effect === e ? "on" : ""}" data-effect="${e}">${e === "blink" ? "⚡ " : e === "pulse" ? "〰 " : ""}${e}</button>`).join("")}
          </span></div>
        <div class="step">⏱ Only alert after
          <input type="number" class="formin" min="0" step="0.5" value="${this._form.forMin}" style="width:60px"> minutes in that state
          <span class="hint" style="display:inline">(0 = immediately; avoids flickering from devices that briefly drop off)</span></div>
        <div class="actions">
          <button class="primary save">${this._editing !== null ? "Save changes" : "Add alert"}</button>
          <button class="cancel">Cancel</button>
        </div>
      </div>` : `<button class="primary add">＋ Add alert</button>`;

    this.shadowRoot.innerHTML = `
      <style>
        ha-card{padding:16px}
        h2{margin:0 0 4px;font-size:1.1em}
        .sub{color:var(--secondary-text-color);font-size:.85em;margin-bottom:12px}
        .strip{display:flex;flex-wrap:wrap;gap:4px;padding:10px;border-radius:10px;background:var(--secondary-background-color);user-select:none}
        .led{width:18px;height:18px;border-radius:50%;background:var(--divider-color);border:2px solid transparent;cursor:pointer;box-sizing:border-box}
        .led:hover{border-color:var(--primary-color)}
        .rule{display:flex;align-items:center;gap:8px;padding:8px 4px;border-bottom:1px solid var(--divider-color)}
        .dot{width:14px;height:14px;border-radius:50%;flex-shrink:0}
        .rtext{flex:1;font-size:.92em}
        .icon{background:none;border:none;cursor:pointer;font-size:1em}
        .empty{color:var(--secondary-text-color);padding:12px 4px;font-size:.9em}
        .form{margin-top:12px;padding:12px;border-radius:10px;background:var(--secondary-background-color)}
        .step{margin:10px 0 6px;font-size:.92em}
        .num{display:inline-flex;width:18px;height:18px;border-radius:50%;background:var(--primary-color);color:#fff;font-size:.75em;align-items:center;justify-content:center;margin-right:6px}
        .count{color:var(--secondary-text-color)}
        .entity{width:100%;box-sizing:border-box;padding:8px;border-radius:6px;border:1px solid var(--divider-color);background:var(--card-background-color);color:var(--primary-text-color)}
        .chips{display:flex;flex-wrap:wrap;gap:6px;align-items:center}
        .chip{border:1px solid var(--divider-color);background:var(--card-background-color);color:var(--primary-text-color);border-radius:14px;padding:4px 10px;cursor:pointer;font-size:.85em}
        .chip.on{background:var(--primary-color);color:#fff;border-color:var(--primary-color)}
        .newstate{border:1px dashed var(--divider-color);background:none;border-radius:14px;padding:4px 10px;color:var(--primary-text-color);font-size:.85em}
        .cmpop,.cmpval,.colorstyle{background:var(--card-background-color);color:var(--primary-text-color);border:1px solid var(--divider-color);border-radius:6px;padding:5px 6px;font-size:.9em}
        .addcmp{border-style:dashed}
        .color{margin-left:8px;width:48px;height:28px;border:none;background:none;cursor:pointer;vertical-align:middle}
        .actions{margin-top:12px;display:flex;gap:8px}
        button.primary{background:var(--primary-color);color:#fff;border:none;border-radius:8px;padding:8px 16px;cursor:pointer;font-size:.95em}
        button.cancel{background:none;border:1px solid var(--divider-color);border-radius:8px;padding:8px 16px;cursor:pointer;color:var(--primary-text-color)}
        button.add{margin-top:12px}
        .hint{color:var(--secondary-text-color);font-size:.85em;margin:6px 0}
        .flash{color:var(--error-color);font-size:.85em;margin-top:6px;opacity:0;transition:opacity .3s}
        .rtext{cursor:pointer}
        .rtext:hover{text-decoration:underline}
        .quiet{margin-top:14px;padding-top:10px;border-top:1px solid var(--divider-color);font-size:.88em;color:var(--secondary-text-color);display:flex;align-items:center;gap:8px;flex-wrap:wrap}
        .quiet select,.quiet input{background:var(--card-background-color);color:var(--primary-text-color);border:1px solid var(--divider-color);border-radius:6px;padding:4px 6px}
      </style>
      <ha-card>
        <h2>LED Alerts</h2>
        <div class="sub">${this._entry.host} · ${n} LEDs${this._formOpen ? " · tap or drag across the strip to choose LEDs" : ""}</div>
        <div class="strip">${leds}</div>
        <div class="rules">${rules}</div>
        ${form}
        <div class="quiet">
          🌙 Quiet hours
          <select class="qmode">
            <option value="off" ${this._quiet.mode === "off" ? "selected" : ""}>Off</option>
            <option value="dim" ${this._quiet.mode === "dim" ? "selected" : ""}>Dim alerts</option>
            <option value="hide" ${this._quiet.mode === "hide" ? "selected" : ""}>Hide alerts</option>
            <option value="strip_off" ${this._quiet.mode === "strip_off" ? "selected" : ""}>Turn strip off</option>
          </select>
          <span class="qtimes" style="${this._quiet.mode === "off" ? "display:none" : ""}">
            from <input type="time" class="qstart" value="${this._quiet.start}">
            to <input type="time" class="qend" value="${this._quiet.end}">
          </span>
          <span style="margin-left:auto" title="WLED segment ID (leave 0 unless you use segments)">segment
            <input type="number" class="segment" min="0" max="31" value="${this._segment ?? 0}" style="width:48px"></span>
        </div>
        <div class="quiet">
          🐾 LED pet
          <label style="display:inline-flex;align-items:center;gap:4px"><input type="checkbox" class="peton" ${this._pet?.enabled ? "checked" : ""}> enabled</label>
          <span class="petcfg" style="${this._pet?.enabled ? "" : "display:none"}">
            home: LED <input type="number" class="petstart" min="0" max="1024" value="${this._pet?.start ?? 0}" style="width:54px">
            size <input type="number" class="petsize" min="2" max="20" value="${this._pet?.size ?? 3}" style="width:44px">
            ${this._pet?.mood ? `· mood: <b>${{happy:"happy 🌱",content:"content 😌",grumpy:"grumpy 😾",sad:"sulking 😞"}[this._pet.mood] || this._pet.mood}</b>` : ""}
          </span>
        </div>
        ${this._pet?.enabled ? `<div class="quiet" style="border-top:none;margin-top:2px;padding-top:0">
          it watches:
          ${(this._pet.sources || []).map((s) => `<button class="chip on" data-petsrc="${s}">${s} ✕</button>`).join("")}
          <input class="petsrcadd" list="petentities" placeholder="add a to-do list or sensor…" style="min-width:180px">
          <datalist id="petentities">${Object.keys(this._hass.states).sort().map((e) => `<option value="${e}">`).join("")}</datalist>
        </div>` : ""}
        <div class="flash"></div>
      </ha-card>`;

    this._bind();
  }

  _bind() {
    const root = this.shadowRoot;
    const strip = root.querySelector(".strip");
    if (strip && this._formOpen) {
      strip.addEventListener("pointerdown", (e) => {
        const t = e.target.closest(".led"); if (!t) return;
        const i = +t.dataset.i;
        this._dragging = true;
        this._dragMode = !this._selected.has(i);
        this._dragMode ? this._selected.add(i) : this._selected.delete(i);
        this._render();
      });
      strip.addEventListener("pointerover", (e) => {
        if (!this._dragging) return;
        const t = e.target.closest(".led"); if (!t) return;
        const i = +t.dataset.i;
        this._dragMode ? this._selected.add(i) : this._selected.delete(i);
        t.style.background = this._dragMode ? this._form.color : "";
        t.classList.toggle("sel", this._dragMode);
      });
      const end = () => { if (this._dragging) { this._dragging = false; this._render(); } };
      strip.addEventListener("pointerup", end);
      strip.addEventListener("pointerleave", end);
    }
    root.querySelector(".add")?.addEventListener("click", () => this._openForm());
    root.querySelector(".cancel")?.addEventListener("click", () => this._closeForm());
    root.querySelector(".save")?.addEventListener("click", () => this._submitForm());
    root.querySelectorAll("[data-edit]").forEach((b) =>
      b.addEventListener("click", () => this._openForm(+b.dataset.edit)));
    root.querySelectorAll("[data-del]").forEach((b) =>
      b.addEventListener("click", () => this._deleteRule(+b.dataset.del)));
    root.querySelectorAll("[data-test]").forEach((b) =>
      b.addEventListener("click", () => this._testRule(+b.dataset.test)));
    root.querySelectorAll("[data-info]").forEach((el) =>
      el.addEventListener("click", () => this._moreInfo(el.dataset.info)));
    root.querySelectorAll("[data-effect]").forEach((b) =>
      b.addEventListener("click", () => { this._form.effect = b.dataset.effect; this._render(); }));
    const qmode = root.querySelector(".qmode");
    qmode?.addEventListener("change", async () => {
      this._quiet.mode = qmode.value;
      await this._saveQuiet(); this._render();
    });
    const seg = root.querySelector(".segment");
    seg?.addEventListener("change", async () => {
      this._segment = seg.value;
      await this._saveQuiet();
    });
    const peton = root.querySelector(".peton");
    peton?.addEventListener("change", async () => { this._pet.enabled = peton.checked; await this._savePet(); this._render(); });
    ["petstart", "petsize"].forEach((cls) => {
      const inp = root.querySelector("." + cls);
      inp?.addEventListener("change", async () => {
        this._pet[cls === "petstart" ? "start" : "size"] = inp.value;
        await this._savePet();
      });
    });
    root.querySelectorAll("[data-petsrc]").forEach((b) =>
      b.addEventListener("click", async () => {
        this._pet.sources = (this._pet.sources || []).filter((s) => s !== b.dataset.petsrc);
        await this._savePet(); this._render();
      }));
    const psrc = root.querySelector(".petsrcadd");
    psrc?.addEventListener("change", async () => {
      const v = psrc.value.trim();
      if (v && this._hass.states[v] && !(this._pet.sources || []).includes(v)) {
        this._pet.sources = [...(this._pet.sources || []), v];
        await this._savePet(); this._render();
      }
    });
    ["qstart", "qend"].forEach((cls) => {
      const inp = root.querySelector("." + cls);
      inp?.addEventListener("change", async () => {
        this._quiet[cls === "qstart" ? "start" : "end"] = inp.value;
        await this._saveQuiet();
      });
    });
    const entity = root.querySelector(".entity");
    entity?.addEventListener("change", () => { this._form.entity = entity.value; this._render(); });
    entity?.addEventListener("input", () => { this._form.entity = entity.value; });
    root.querySelectorAll(".chip").forEach((c) =>
      c.addEventListener("click", () => {
        const s = c.dataset.state;
        this._form.states.has(s) ? this._form.states.delete(s) : this._form.states.add(s);
        this._render();
      }));
    const tobar = root.querySelector(".tobar");
    tobar?.addEventListener("click", () => {
      this._form.effect = "fill";
      const st = this._hass.states[this._form.entity.trim()];
      const unit = st?.attributes?.unit_of_measurement;
      const val = parseFloat(st?.state);
      if (unit === "%" || (!isNaN(val) && val >= 0 && val <= 100)) {
        this._form.fillMin = 0; this._form.fillMax = 100;
      }
      this._render();
    });
    const addcmp = root.querySelector(".addcmp");
    addcmp?.addEventListener("click", () => {
      const op = root.querySelector(".cmpop").value;
      const val = root.querySelector(".cmpval").value.trim();
      if (val === "" || isNaN(parseFloat(val))) return this._flash("Enter a number first");
      this._form.states.add(op + val);
      this._render();
    });
    const ns = root.querySelector(".newstate");
    ns?.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && ns.value.trim()) { this._form.states.add(ns.value.trim()); this._render(); }
    });
    const color = root.querySelector(".color");
    color?.addEventListener("input", () => { this._form.color = color.value; this._render(); });
    const color2 = root.querySelector(".color2");
    color2?.addEventListener("input", () => { this._form.color2 = color2.value; this._render(); });
    const cstyle = root.querySelector(".colorstyle");
    cstyle?.addEventListener("change", () => { this._form.colorStyle = cstyle.value; this._render(); });
    const formin = root.querySelector(".formin");
    formin?.addEventListener("change", () => { this._form.forMin = formin.value; });
    const fmin = root.querySelector(".fillmin");
    fmin?.addEventListener("change", () => { this._form.fillMin = fmin.value; });
    const fmax = root.querySelector(".fillmax");
    fmax?.addEventListener("change", () => { this._form.fillMax = fmax.value; });
  }
}

customElements.define("wled-taskmap-card", WledTaskmapCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "wled-taskmap-card",
  name: "WLED Task Map",
  description: "Visually map entities and tasks to LEDs: tap pixels, pick an entity, state and color.",
});
