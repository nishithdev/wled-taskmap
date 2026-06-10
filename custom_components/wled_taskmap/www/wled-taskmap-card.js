/* WLED Task Map card - visual LED rule builder.
   Add via dashboard: type "custom:wled-taskmap-card" (appears in the card picker). */

const SUGGESTED_STATES = ["unavailable", "unknown", "error", "problem", "on", "off", "open", "failed", "idle"];

class WledTaskmapCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._selected = new Set();
    this._rules = [];
    this._editing = null; // index being edited, or null
    this._formOpen = false;
    this._form = { entity: "", states: new Set(), color: "#FF0000" };
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
      if (this._entry) this._rules = JSON.parse(JSON.stringify(this._entry.rules || []));
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
      })),
    });
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
      };
    } else {
      this._form = { entity: "", states: new Set(["unavailable", "error"]), color: "#FF0000" };
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
    if (!isTodo && !this._form.states.size) return this._flash("Pick at least one state");
    const rule = {
      entity_id: entity,
      leds,
      color: this._form.color.replace("#", "").toUpperCase(),
      alert_states: [...this._form.states].join(","),
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
    const set = new Set(SUGGESTED_STATES);
    const st = this._hass.states[entity];
    if (st) set.add(st.state);
    this._form.states.forEach((s) => set.add(s));
    return [...set];
  }

  // ---------- rendering ----------

  _ledColor(i) {
    if (this._selected.has(i)) return null; // selection style wins
    for (let r = this._rules.length - 1; r >= 0; r--) {
      if (this._rules[r].leds.includes(i)) return "#" + this._rules[r].color;
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
    const editingTodo = this._form.entity.trim().startsWith("todo.");

    const leds = Array.from({ length: n }, (_, i) => {
      const ruleColor = this._ledColor(i);
      const sel = this._selected.has(i);
      const style = sel
        ? `background:${this._form.color};box-shadow:0 0 6px ${this._form.color};border-color:var(--primary-text-color)`
        : ruleColor
        ? `background:${ruleColor};opacity:.45`
        : "";
      return `<div class="led ${sel ? "sel" : ""}" data-i="${i}" style="${style}" title="LED ${i}"></div>`;
    }).join("");

    const rules = this._rules.map((r, i) => {
      const name = this._hass.states[r.entity_id]?.attributes?.friendly_name || r.entity_id;
      const when = r.entity_id.startsWith("todo.")
        ? "has pending items"
        : `is ${r.alert_states.split(",").join(" / ")}`;
      const ledsTxt = r.leds.length > 6 ? `${r.leds.length} LEDs` : `LED ${r.leds.join(", ")}`;
      return `<div class="rule">
        <span class="dot" style="background:#${r.color}"></span>
        <span class="rtext"><b>${name}</b> ${when} → ${ledsTxt}</span>
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
        ${editingTodo
          ? `<div class="hint">To-do list: lights up whenever it has pending items.</div>`
          : `<div class="step"><span class="num">3</span> …is in one of these states</div><div class="chips">${stateChips}
             <input class="newstate" placeholder="other…" size="8"></div>`}
        <div class="step"><span class="num">${editingTodo ? 3 : 4}</span> Light them in this color
          <input type="color" class="color" value="${this._form.color}"></div>
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
        .color{margin-left:8px;width:48px;height:28px;border:none;background:none;cursor:pointer;vertical-align:middle}
        .actions{margin-top:12px;display:flex;gap:8px}
        button.primary{background:var(--primary-color);color:#fff;border:none;border-radius:8px;padding:8px 16px;cursor:pointer;font-size:.95em}
        button.cancel{background:none;border:1px solid var(--divider-color);border-radius:8px;padding:8px 16px;cursor:pointer;color:var(--primary-text-color)}
        button.add{margin-top:12px}
        .hint{color:var(--secondary-text-color);font-size:.85em;margin:6px 0}
        .flash{color:var(--error-color);font-size:.85em;margin-top:6px;opacity:0;transition:opacity .3s}
      </style>
      <ha-card>
        <h2>LED Alerts</h2>
        <div class="sub">${this._entry.host} · ${n} LEDs${this._formOpen ? " · tap or drag across the strip to choose LEDs" : ""}</div>
        <div class="strip">${leds}</div>
        <div class="rules">${rules}</div>
        ${form}
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
    const entity = root.querySelector(".entity");
    entity?.addEventListener("change", () => { this._form.entity = entity.value; this._render(); });
    entity?.addEventListener("input", () => { this._form.entity = entity.value; });
    root.querySelectorAll(".chip").forEach((c) =>
      c.addEventListener("click", () => {
        const s = c.dataset.state;
        this._form.states.has(s) ? this._form.states.delete(s) : this._form.states.add(s);
        this._render();
      }));
    const ns = root.querySelector(".newstate");
    ns?.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && ns.value.trim()) { this._form.states.add(ns.value.trim()); this._render(); }
    });
    const color = root.querySelector(".color");
    color?.addEventListener("input", () => { this._form.color = color.value; this._render(); });
  }
}

customElements.define("wled-taskmap-card", WledTaskmapCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "wled-taskmap-card",
  name: "WLED Task Map",
  description: "Visually map entities and tasks to LEDs: tap pixels, pick an entity, state and color.",
});
