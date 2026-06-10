# WLED Task Map

A Home Assistant custom integration that maps tasks, entities, and errors to **individual LEDs** on a WLED strip. Each watched item gets its own LED: red light at position 3 means *that* thing needs attention.

## Features

- **Per-LED mapping** — assign any Home Assistant entity to a specific LED index with its own alert color.
- **Entity error watching** — LEDs light when an entity enters `unavailable`, `unknown`, `error`, `problem` (customizable per mapping).
- **To-do list aware** — map a `todo.*` entity and its LED lights whenever the list has pending items (Todoist, Local To-do, etc.).
- **Service hook for anything else** — call `wled_taskmap.set_alert` from any automation (failed automations, Jira webhooks, CI pipelines…).
- **Active Alerts sensor** — shows how many items are alerting and which ones.
- UI-only setup, no YAML required.

## Installation

### HACS (recommended)

1. HACS → menu (⋮) → **Custom repositories** → add this repo URL, category **Integration**.
2. Install **WLED Task Map**, restart Home Assistant.

### Manual

Copy `custom_components/wled_taskmap` into your HA `config/custom_components/` folder and restart.

## Setup

1. **Settings → Devices & Services → Add Integration → WLED Task Map** — enter your WLED IP. That's the whole setup.
2. On any dashboard: **Edit → Add card → WLED Task Map** (the card ships with the integration, no resource setup needed).

### Creating alerts — all visual, in the card

The card shows your actual LED strip as a row of dots. To add an alert:

1. Tap **＋ Add alert**
2. Tap (or drag across) the LEDs that should light up
3. Type the entity to watch (autocomplete)
4. Tap the states that should trigger it (chips: unavailable, error, on… or type your own). To-do lists skip this — they trigger whenever items are pending.
5. Pick a color from the color picker

Saved instantly. Existing alerts are listed under the strip in plain language ("**Printer** is error / unavailable → LED 3, 4, 5") with edit ✏️ and delete 🗑 buttons.

## Catching failed automations / external tasks

Use the `set_alert` service from any automation:

```yaml
automation:
  - alias: "Flag backup failure on LED 5"
    trigger:
      - platform: state
        entity_id: binary_sensor.backup_failed
        to: "on"
    action:
      - service: wled_taskmap.set_alert
        data:
          led: 5
          color: "FF6600"

  - alias: "Clear it when fixed"
    trigger:
      - platform: state
        entity_id: binary_sensor.backup_failed
        to: "off"
    action:
      - service: wled_taskmap.clear_alert
        data:
          led: 5
```

For external apps (Todoist, Jira, GitHub…), install their HA integration and either map their `todo.*`/sensor entities directly, or trigger `set_alert` from an automation/webhook.

## Services

| Service | Description |
|---|---|
| `wled_taskmap.set_alert` | Light LED `led` with `color` |
| `wled_taskmap.clear_alert` | Turn off LED `led` |
| `wled_taskmap.clear_all` | Clear all manual alerts |

## Publishing to HACS

1. Push this repo to GitHub (keep the `custom_components/wled_taskmap` layout, `hacs.json` at root).
2. Create a GitHub **release** (tag matching `manifest.json` version, e.g. `0.1.0`).
3. Users add it as a HACS custom repository immediately; for the default HACS store, submit a PR to [hacs/default](https://github.com/hacs/default) after meeting their [requirements](https://hacs.xyz/docs/publish/integration/) (repo description, topics, valid manifest — all already in place here).

## Notes

- LEDs are driven via WLED's JSON API individual-LED control, so non-alerting mapped LEDs are held dark while the rest of the strip behaves normally.
- One config entry per WLED device.

## License

MIT
