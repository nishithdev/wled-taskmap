# WLED Task Map — Full Documentation

For first-time setup, follow the step-by-step guide in the [README](../README.md). This page is the complete reference.

## Contents

1. [How it works](#how-it-works)
2. [The card](#the-card)
3. [Rule model](#rule-model)
4. [State matching details](#state-matching-details)
5. [Services](#services)
6. [Sensor](#sensor)
7. [WebSocket API](#websocket-api)
8. [Multiple WLED devices](#multiple-wled-devices)
9. [Troubleshooting](#troubleshooting)
10. [Uninstalling](#uninstalling)

## How it works

The integration keeps a set of *rules* (entity → LEDs → trigger states → color). It subscribes to state changes of every watched entity. On any change it recomputes which rules are alerting and pushes the result to your WLED device over its local JSON API (`POST /json/state`) using WLED's individual-LED addressing — alerting rules get their color, non-alerting mapped LEDs are set to black. LEDs that no rule touches are never written to, so the rest of the strip behaves normally.

There is no cloud involved; everything is local HTTP between Home Assistant and the WLED device.

## The card

The **WLED Task Map** card is bundled with the integration and registered automatically — you do not need to add a Lovelace resource. Add it from the dashboard card picker ("WLED Task Map").

Card YAML (optional):

```yaml
type: custom:wled-taskmap-card
# only needed with multiple WLED Task Map devices:
entry_id: <config entry id>
```

In the card you can:

- See the strip as one dot per LED (count is read live from the device).
- **Add alert**: tap/drag LEDs → pick entity (autocomplete) → tap trigger states (chips are entity-aware: enum/select options, climate HVAC modes, domain defaults, current state) → pick color → save.
- **Edit** ✏️ or **delete** 🗑 any rule. Edits pre-select the rule's LEDs on the strip.
- Saves apply instantly (websocket → config entry update → reload).

## Rule model

Rules are stored in the config entry options:

```json
{
  "entity_id": "sensor.printer_status",
  "leds": [2, 3, 4],
  "color": "FF3B30",
  "alert_states": "error,unavailable"
}
```

- `leds` — any set of 0-based LED indices (not necessarily contiguous).
- `color` — RRGGBB hex, no `#`.
- `alert_states` — comma-separated, case-insensitive.
- Rules from versions before 0.4.0 (`led` + `led_count`) are migrated automatically.
- If two rules light the same LED, the rule lower in the list wins.

## State matching details

- Comparison is against the entity's **state string**, lowercased (`on`, `error`, `below_horizon`…).
- **Numeric thresholds**: a condition starting with `>`, `<`, `>=`, `<=`, `=`, or `!=` is compared numerically — e.g. `>80` alerts when a temperature sensor exceeds 80. Mix freely with state strings: `unavailable,>80`.
- **To-do lists** (`todo.*`) alert whenever the list has at least one pending item. Add a numeric condition (e.g. `>3`) to change the threshold.
- Attribute-based conditions are not supported directly — create a [template binary sensor](https://www.home-assistant.io/integrations/template/) and watch that.

## Effects

Each rule has an effect: **solid** (default), **blink** (on/off every second — for critical alerts), or **pulse** (full/dim breathing). Blinking is driven by Home Assistant, so it works per-LED even though WLED effects are per-segment.

## Quiet hours

At the bottom of the card, choose what happens between two times (windows may cross midnight):

- **Dim alerts** — alert LEDs at 25% brightness
- **Hide alerts** — alert LEDs off; the rest of the strip is untouched
- **Turn strip off** — powers the whole WLED strip off for the night and back on when the window ends (only if it was on when quiet hours began)

Alerts reappear at full brightness when the window ends. Quiet hours are evaluated in Home Assistant's configured timezone.

## Strip state restore

Before painting its first alert, the integration snapshots what the mapped LEDs were showing (via WLED's live view) and restores those exact colors when all alerts clear — so alerts no longer leave black pixels behind on a strip running an effect or preset.

## Locating LEDs

Tap 🔦 on any rule to flash its LEDs three times on the physical strip. Tap a rule's text to open the watched entity's more-info dialog.

## Services

| Service | Fields | Description |
|---|---|---|
| `wled_taskmap.set_alert` | `led` (int), `color` (hex, default `FF0000`) | Light a single LED manually. Survives until cleared. |
| `wled_taskmap.clear_alert` | `led` (int) | Clear one manual alert. |
| `wled_taskmap.clear_all` | — | Clear all manual alerts. |

Manual alerts layer on top of rule-driven alerts and are kept in memory (cleared on HA restart). Use them for things that aren't entities: automation failure handlers, webhooks, CI pipelines.

```yaml
action:
  - service: wled_taskmap.set_alert
    data: {led: 5, color: "FF6600"}
```

## Sensor

Each device adds `sensor.<name>_active_alerts`:

- **State** — number of currently-lit alerts.
- `alerting_entities` — which watched entities are alerting.
- `manual_leds` — LEDs lit via `set_alert`.
- `watched` — all rules (entity + LEDs).

Useful for notifications, e.g. *"notify me when active alerts > 0 for 10 minutes"*.

## WebSocket API

Used by the card; available to other frontends:

- `wled_taskmap/get_config` → `{entries: [{entry_id, host, segment, led_count, rules, active}]}`
- `wled_taskmap/save_rules` `{entry_id, rules: [...]}` → replaces all rules for that entry.

## Multiple WLED devices

Add the integration once per WLED device (each with its own IP). Add one card per device, setting `entry_id` in the card YAML to bind it to a specific device. Services currently target the first loaded device.

## Troubleshooting

**The card isn't in the card picker.** Hard-refresh the browser (Ctrl/Cmd+Shift+R). In the companion app: close and reopen, or Settings → Companion App → Debugging → Reset frontend cache.

**"No WLED Task Map device found" in the card.** The integration isn't set up yet — Settings → Devices & Services → Add Integration → WLED Task Map.

**"Could not reach the WLED device" during setup.** Verify the IP (WLED app or router), that the strip is powered, and that HA and WLED are on the same network/VLAN.

**LEDs don't light when a rule should fire.** Check the entity's actual state string in Developer Tools → States — it must exactly match a trigger state (e.g. Bambu printers report `RUNNING`, not `printing`; matching is case-insensitive but spelling matters). Also confirm the strip is on — the integration turns it on when an alert fires, but a strip with brightness 0 stays dark.

**LEDs lit that I didn't expect.** A watched entity is probably `unavailable` (device offline) — that's usually the alert working as intended.

**Wrong LEDs light up.** If you use WLED segments, LED indices in rules are relative to the configured segment (default segment 0 = whole strip).

**Errors in logs.** Search Settings → System → Logs for `wled_taskmap` and open an issue with the traceback: https://github.com/nishithdev/wled-taskmap/issues

## Uninstalling

1. Remove the device(s): Settings → Devices & Services → WLED Task Map → delete.
2. Remove the card(s) from dashboards.
3. Uninstall via HACS, restart HA.

Mapped LEDs may stay dark until you power-cycle the strip or set a WLED preset.
