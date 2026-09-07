<p align="center"><img src="https://raw.githubusercontent.com/nishithdev/wled-taskmap/main/assets/logo.png" width="360" alt="WLED Task Map"></p>

<h1 align="center">WLED Task Map</h1>

Light up LEDs on your WLED strip when something needs your attention.

Examples of what it can do:

- LED 3 **blinks red** when your 3D printer goes into an error state
- LEDs 0–4 turn **orange** when your shopping list has items on it
- Ten LEDs become a **live battery gauge**, filling red → yellow → green as your phone charges
- A block of LEDs works as an **ambient week calendar** — today's block fills as the day passes
- A tiny **LED pet** bounces happily when your chores are done and sulks grey when they pile up

You set all of this up by **tapping LEDs and picking colors in a visual card** — no YAML, no code.

<p align="center"><img src="https://raw.githubusercontent.com/nishithdev/wled-taskmap/main/assets/demo.gif" width="560" alt="30-second demo: tap LEDs, pick an entity and states, choose a color — done"></p>

## Feature highlights

- **Visual rule builder** — tap/drag LEDs on a live picture of your strip, pick an entity (autocomplete), tap trigger states (entity-aware suggestions, numeric comparisons like `<20`), choose a color. Starter templates get you going on an empty card.
- **Effects & color styles** — solid, ⚡ blink, 〰 pulse, ▮▯ **fill** (LEDs as a progress bar for any numeric sensor), with **gradient** and 🌈 rainbow color blending across the block.
- **Week board** 📅 — an ambient weekly calendar: N LEDs per day, today fills through the day with a gradient, past days dim, Monday or Sunday start, day markers on the card.
- **LED pet** 🐾 — a tamagotchi whose mood (happy → sulking) reflects your to-do lists and problem sensors; mood changes hit the Logbook.
- **Static lights** 💡 — always-lit LEDs with no entity behind them: separators, accents, plain lamps.
- **Day-to-day controls** — pause ⏸, silence 🔕 until the state changes, drag to reorder, duplicate, undo delete, custom names, 🔦 test-flash to locate LEDs, live strip view in the card.
- **Brightness** — global ☀️ intensity slider plus quiet hours 🌙 (dim to a configurable night level, hide alerts, or power the strip off on a schedule — in HA's timezone).
- **Set-and-forget reliability** — zeroconf auto-discovery, automatic repaint after WLED power-cycles/reconnects, flap protection ("only after N minutes"), entity renames auto-handled, Repairs warnings for dead rules, alert history in the Logbook, offline banner.
- **💾 Export / Import** — back up or share every rule and setting as one JSON file.
- **Automation-friendly** — `set_alert`/`clear_alert` services (survive restarts), an Active Alerts sensor, and a websocket API.

Full reference (services, websocket API, troubleshooting): **[docs/documentation.md](docs/documentation.md)**

![What you need](https://img.shields.io/badge/Home%20Assistant-2024.6%2B-blue) ![HACS](https://img.shields.io/badge/HACS-custom%20repository-orange)

---

## What you need before starting

1. **Home Assistant** up and running.
2. **A WLED device** — an LED strip running [WLED](https://kno.wled.ge/) firmware, connected to your WiFi.
3. **The IP address of your WLED device** (looks like `192.168.1.50`). To find it: open the WLED app on your phone, or open Settings → Devices & Services → WLED in Home Assistant — the IP is shown on the device page. You can also check your router's device list.
4. **HACS** installed in Home Assistant. HACS is an app store for community add-ons. If you don't have it, follow the [official HACS install guide](https://hacs.xyz/docs/use/) first (one-time, ~10 minutes).

---

## Step 1 — Install the integration (via HACS)

1. In Home Assistant, click **HACS** in the left sidebar.
2. Click the **⋮ (three dots)** menu in the top-right corner → **Custom repositories**.
3. In the *Repository* field paste:
   ```
   https://github.com/nishithdev/wled-taskmap
   ```
4. In the *Type* dropdown pick **Integration**, then click **Add** and close the dialog.
5. In HACS, search for **WLED Task Map**, open it, and click **Download**.
6. **Restart Home Assistant**: Settings → System → click the power icon (top right) → Restart. Wait for it to come back up.

> Without the restart, nothing will work — don't skip step 6.

## Step 2 — Connect it to your WLED strip

In most cases your WLED device is **discovered automatically**: go to **Settings → Devices & Services**, look for "WLED Task Map" under *Discovered*, and click **Add**. Done.

If it isn't discovered:

1. Click **+ Add Integration** (bottom right).
2. Search for **WLED Task Map** and click it.
3. Type your WLED device's **IP address** (from "What you need" above) and submit.

That's the entire configuration. If you get "Could not reach the WLED device", double-check the IP and that the strip is powered on.

## Step 3 — Add the card to your dashboard

1. Open any dashboard (e.g. **Overview** in the sidebar).
2. Click the **✏️ pencil** (top right) to enter edit mode.
3. Click **+ Add card**, scroll down or search for **WLED Task Map**, and click it. Click **Save**.
4. Click **Done** to leave edit mode.

> Card not in the list? Do a hard refresh of your browser: **Ctrl+Shift+R** (Windows) / **Cmd+Shift+R** (Mac). On the phone app: close and reopen the app.

You'll now see your LED strip drawn as a row of dots.

## Step 4 — Create your first alert

In the card:

1. Tap **＋ Add alert**.
2. **Tap the dots** (LEDs) on the strip that should light up. Drag across to select several. They glow in your chosen color so you can see exactly what you picked.
3. **Type the entity to watch** — start typing and pick from the suggestions. An *entity* is anything Home Assistant tracks: `sensor.printer_status`, `binary_sensor.front_door`, `todo.shopping_list`…
4. **Tap the states that should trigger the alert** — e.g. `error` and `unavailable`. (Skip this for to-do lists: they trigger automatically whenever they have pending items.)
5. **Pick a color** with the color picker.
6. Tap **Add alert**. Done — it's live immediately.

Your alerts are listed under the strip in plain language, e.g.:

> 🔴 **3D Printer** is error / unavailable → LED 3, 4, 5  ✏️ 🗑

Tap ✏️ to change anything, 🗑 to remove.

### How it behaves

- When a watched entity enters one of its trigger states, its LEDs light in the chosen color.
- When it recovers, those LEDs turn off.
- The rest of your strip is untouched — you can keep using WLED normally.

---

## Example: zoning one strip into a status board

A single 30-LED shelf strip can act as a whole-house dashboard by giving each topic its own block of LEDs:

<p align="center"><img src="https://raw.githubusercontent.com/nishithdev/wled-taskmap/main/assets/zones-example.svg?v=2" width="640" alt="One strip split into network, phone battery, and printer zones"></p>

| Zone | LEDs | Alert | Color / effect |
|---|---|---|---|
| Network | 0–2 | `binary_sensor.nas_online` is `off` for 5 min | red, blink |
| Network | 3–5 | `sensor.optiplex7050_cpu_temp` is `unavailable` for 10 min | red, solid |
| Network | 6–9 | `update.home_assistant_core` is `on` (update available) | purple, solid |
| Battery | 10–19 | `sensor.pixel_10_pro_xl_battery_level` — "its level, as a bar" (0–100) | red→green **gradient fill**: a live battery gauge that ramps red → orange → yellow → green as it charges |
| Battery | 10–19 | same sensor, `below 20` | red, blink — overrides the gauge when critically low (later rules win) |
| Printer | 20–28 | `sensor.p1s_print_progress` from 0 to 100 | blue, **fill** (live progress bar) |
| Printer | 29 | `sensor.p1s_print_status` is `error` / `unavailable` | red, blink |

(To-do lists work the same way: map `todo.shopping_list` to a block and it lights when items are pending, or use fill with a 0→10 range to show the count as a bar.)

Tips that make multi-LED setups work well:

- **Leave a dark LED between zones** so adjacent alerts don't read as one blob.
- **Same color per zone, different effect per severity** — solid = info, pulse = warning, blink = act now. Easier to learn than ten colors.
- **Use the 🔦 test button** after building each zone to confirm the physical layout matches what you tapped.
- **Overlap on purpose**: map a "panic" rule (e.g. `binary_sensor.water_leak` is `on`) to *all 30 LEDs* in blinking red — rules later in the list win, so it overrides every zone when it fires.

Running **two strips** (e.g. desk + hallway)? Add the integration once per WLED device and place one card per device on your dashboard — each card binds to its own strip, so the desk strip can track your printer while the hallway strip tracks the household lists.

## Common questions

**Which states should I pick?**
`unavailable` and `error` are good defaults for most devices. For sensors that signal a problem by turning "on" (door open, leak detected, low battery), pick `on`. Not sure what states an entity has? Open it in Developer Tools → States and watch what it reports.

**My strip has no segments configured — is that OK?**
Yes. A fresh WLED install works out of the box; LED numbers simply count from the start of the strip (first LED = 0).

**Can two alerts share the same LEDs?**
Yes — if both trigger, the newer rule's color wins.

**LEDs lit up that I didn't expect?**
One of your watched entities is probably `unavailable` (device offline). That's the alert doing its job — or a sign to remove that mapping.

## For advanced users: trigger from automations

Any automation can light an LED directly — useful for things that aren't entities (webhooks, script failures, CI builds):

```yaml
action:
  - service: wled_taskmap.set_alert
    data:
      led: 5
      color: "FF6600"
```

`wled_taskmap.clear_alert` (with `led`) turns it back off; `wled_taskmap.clear_all` clears all manual alerts.

## Manual installation (without HACS)

Download this repository, copy the `custom_components/wled_taskmap` folder into your Home Assistant `config/custom_components/` folder, restart HA, then continue from **Step 2**.

## License

MIT
