# Firmware

Two ESP-IDF applications and the shared components they are built from.

```
firmware/
  common/mesh_proto.h     the wire protocol, byte-identical to the Python codec
  common/board_pins.h     every pin in the system, in one place
  components/
    subnet_proto/         frame build, parse, CRC, config hash        (portable)
    meshnet/              flood de-duplication, TTL, relay, neighbours (portable)
    nodelogic/            tilt rate, thresholds, events, cooldowns     (portable)
    gwrules/              the gateway's offline alerting decision      (portable)
    statusled/            what the one LED on the box means            (portable)
    llcc68/               E220-900M22S radio driver (SPI)
    lis3dh/               tilt, vibration and die temperature (I2C)
    gnss/                 NEO-6M: NMEA parsing is portable, UART is not
    battery/              ADC1 battery sense, calibrated
    sim800l/              2G modem, AT commands, SMS
    nodecfg/              NVS identity + config + the provisioning console
  node/                   the field node application      (ESP32-S3)
  gateway/                the gateway application         (ESP32-S3, same board)
    main/webui.c            the on-site web UI's server
    main/fieldview.c        what the gateway has heard, for that UI
    main/web/index.html     the page itself, linked into the binary
  host_test/              everything portable, tested with cc and no hardware
```

"Portable" means exactly one thing: the module compiles on a laptop with no
ESP-IDF, and `host_test/run.sh` exercises it there. Those are the modules that
decide whether the system warns anybody, so they are tested where a failure
costs a minute rather than a field trip.

## Test the portable core

```bash
firmware/host_test/run.sh          # 325 checks, no hardware, ~1 second
```

Covers the frame codec (including every single-bit flip in a frame), mesh
routing and flood termination, the NMEA parser against real captured sentences,
the LLCC68's spreading-factor limits, the node's threshold and rate logic, and
the gateway's alerting rules.

## Build and flash

Needs **ESP-IDF v5.2 or newer** — the LIS3DH driver uses the `i2c_master` API,
which does not exist before v5.2. On a machine with Python 3.13, use v5.4 or
newer: older ESP-IDF releases do not accept that interpreter.

### First time on a new machine (Ubuntu/Debian)

```bash
mkdir -p ~/esp && cd ~/esp
git clone -b v5.5.5 --depth 1 --shallow-submodules --recursive \
    https://github.com/espressif/esp-idf.git
cd esp-idf && ./install.sh esp32s3      # ~4 GB unpacked, once

# CMake needs ninja and ESP-IDF does not ship it on Linux. Putting it in IDF's
# own virtualenv avoids needing root, and export.sh then puts it on PATH.
~/.espressif/python_env/idf5.5_py3.13_env/bin/pip install ninja
```

Both boards are ESP32-S3, so that is the only target to install. Flashing over
USB needs serial access -- `sudo usermod -aG dialout $USER`, then log out and
back in.

The `flex`, `bison` and `gperf` packages appear in Espressif's prerequisite list
but are not used by the CMake build; only `cmake` and `ninja` are, and the line
above covers ninja without a package manager.

### Or from VS Code, with no terminal at all

The **Espressif IDF** extension drives the same build system from buttons. With
ESP-IDF already installed as above, point the extension at it in your VS Code
*user* settings (`Ctrl+Shift+P` -> Preferences: Open User Settings (JSON)):

```jsonc
"idf.espIdfPath":  "/home/<you>/esp/esp-idf",
"idf.toolsPath":   "/home/<you>/.espressif",
"idf.pythonBinPath": "/home/<you>/.espressif/python_env/idf5.5_py3.13_env/bin/python",
"idf.gitPath":     "/usr/bin/git",
"idf.port":        "/dev/ttyACM0"
```

Then **File -> Open Workspace from File... -> `firmware/mineguard.code-workspace`**,
and use the status-bar buttons: 🔨 build, ⚡ flash, 🖥 monitor. Pick which project
they act on with the folder selector in that same status bar.

> **Do not open `firmware/` itself as the folder.** It is not an ESP-IDF project
> and has no `CMakeLists.txt`; it is a container for two projects that share the
> `components/` directory beside them. Pointing the extension at it fails with
> *"CMakeLists.txt not found in project directory"*. Open the workspace file, or
> open `firmware/node` / `firmware/gateway` directly -- each carries a
> `.vscode/settings.json` fixing the target to `esp32s3`.

If you would rather have the extension install ESP-IDF itself, skip the manual
install above and run `ESP-IDF: Configure ESP-IDF Extension` -> *Express*; it
does the same thing through a wizard.

Machine-specific settings (where ESP-IDF lives, which serial port) belong in
user settings. Project facts (the target, the flash method) are in the checked-in
workspace settings, so every machine builds these the same way.

### Every session, from a terminal

```bash
. $HOME/esp/esp-idf/export.sh

cd firmware/node
idf.py set-target esp32s3
idf.py build flash monitor

cd ../gateway
idf.py set-target esp32s3
idf.py build flash monitor
```

`set-target` is needed once per application; after that `idf.py build flash
monitor` is the whole loop. On an S3 mini the port is the native USB one —
usually `/dev/ttyACM0`, pass it as `-p /dev/ttyACM0` if the auto-detection picks
the wrong device. Leave the monitor with **Ctrl-]**.

If a board refuses to be found, put it in download mode by hand: hold **BOOT**,
tap **RESET**, release BOOT, then flash. Some S3 minis need this the first time
because there is no auto-reset circuit on the native USB port. `idf.py
erase-flash` clears a board completely, including the NVS that holds its
identity — after that it comes up unprovisioned with a MAC-derived address.

Both applications target the **same board**, an ESP32-S3 mini. What makes one a
gateway is the modules on its headers and `set role gateway` in NVS — one board
to source, one board to keep as a spare, and the radio half of the wiring
verified twenty-one times before the gateway is built.

`sdkconfig.defaults` is checked in for both, so every board is built the same
way. A node that behaves differently because of somebody's local menuconfig is a
node whose data cannot be compared with its neighbours'.

## Provisioning

One binary flashes to every board. What makes a board node `0x0014` is a value
in NVS, written over the console — never a compile-time constant, because
twenty-one boards each needing their own build is twenty-one chances to flash
the wrong one with no way to tell afterwards.

Open the serial console (`idf.py monitor`, or any terminal at 115200) and type:

```
show                          identity, config and radio counters
set addr 0x0014               mesh address (0x0010+ = surveyed)
set label T-05
set role node|gateway
set interval 60               sample interval, seconds
set rate-alert 150            the tilt RATE trigger -- the precursor
set tilt-alert 2000           absolute tilt, mdeg
set vib-alert 500             mg
set tx-power 22               dBm
set flags 0x0F                bit0 relay, bit1 gnss, bit2 vib, bit3 deep-sleep
set offsets <pitch> <roll>    tilt zero, mdeg
save
reboot
```

Gateway only:

```
set wifi <ssid> <password>
set api  http://10.0.0.5:8000
set mqtt 10.0.0.5             optional; '-' clears it and everything runs on HTTP
set site jharia
set gw-id gw-01
set sms  +919876543210,+911234567890
set ap-pass <8+ chars>        guards the on-site web UI -- change it
set push https://host/hook    optional realtime JSON feed; '-' clears it
save
```

Everything in that second list can also be typed on a phone, over the gateway's
own access point — see below.

An unprovisioned board still joins the network: it derives a provisional address
from its own MAC (0x8000 and up, so it cannot collide with a surveyed address)
and reports. The backend auto-provisions it unplaced, which is how a board that
was flashed and dropped in a bag still appears on the dashboard instead of
vanishing. Every reply begins `OK` or `ERR`, so a script can drive the same
console for a whole crate of boards.

## What the node does

```
wake ─► sample burst ─► extract ─► decide ─► TX events ─► TX telemetry ─► listen ─► sleep
        32 reads         tilt        rate,     immediately   22 bytes      1.5 s     to the
        at 100 Hz        vib RMS     tamper,                                         next slot
                         die temp    battery
```

Three properties worth knowing before changing any of it:

**The duty cycle is aligned to the epoch, not to boot.** A node sleeps until the
next multiple of `sample_interval_s` in absolute UTC. Every node is therefore
awake in the same window, which is the only reason a controlled flood works: a
relay that is asleep when its neighbour transmits is not a relay.

**An event does not wait for the next slot.** Threshold breaches transmit
immediately, and the accelerometer's own interrupt or the vibration switch can
wake the node out of deep sleep to find one. Both wake pins are RTC GPIOs for
that reason.

**The rate trigger is the important one.** There is no crack gauge in this
design, so a first opening is not directly observable — what is observable is
that tilt starts moving faster, and it does that while absolute tilt is still
comfortably inside its own limit.

A node with `CFG_FLAG_DEEP_SLEEP` cleared never sleeps and holds its receiver
open instead. That is not a fallback: a mains- or large-panel-powered node is
the field's relay backbone, and it costs ~12 mA continuously rather than 1.9.

## What the gateway does

In this order, and the order is the design:

1. **Receive and write down.** Every frame is spooled to microSD before anything
   else is attempted. A failed POST must never cost a measurement.
2. **Decide locally.** A critical `EVENT` becomes an SMS from the gateway's own
   modem, with no server in the path. An SMS that needs the backend to be
   reachable is an SMS that fails exactly when it is needed.
3. **Uplink when possible.** Batches of up to 64 frames, over MQTT when a broker
   is configured and HTTP otherwise, retried until they land. Nothing is removed
   from the spool until the backend has taken it.
4. **Say so, out loud.** One status LED reports the worst thing that is true —
   continuous flash for a dead radio, then 2–6 blinks for a silent field, a
   missing modem, no WiFi, an unreachable backend or a deep spool, and a single
   heartbeat when all is well. Every received frame produces a brief flick, so
   the mesh can be watched breathing without any equipment. The decision logic
   is pure and host-tested (`components/statusled`); the legend is in
   `docs/HARDWARE.md` §3.5 and on the web UI.
5. **Carry the clock and control back down.** `TIME_SYNC` to the whole field
   every ten minutes; `CONFIG_SET` to individual nodes.

Downlink timing is the subtle part. Nodes are awake about two seconds a minute,
so a config transmitted at an arbitrary moment reaches nobody. The gateway holds
each pending downlink and sends it the instant it hears from that node — a frame
just received is proof the sender is awake right now. It stays queued until the
`CONFIG_ACK` arrives, which is also what turns the row in the dashboard from
`pending` into `applied`.

## The gateway's web UI

The gateway serves one page from its own flash, and runs a WiFi access point as
well as a station so that page is reachable whether or not the site network is:

```
join  mineguard-<gw-id>        WPA2, password from `set ap-pass`
open  http://192.168.4.1       or the gateway's address on the site network
```

It answers a different question from the dashboard upstream. The dashboard
answers *what is the ground doing*; this answers *is this box working* — which
is a different question, asked by a different person, at a different moment,
usually in the rain.

| Shows | Does |
|---|---|
| Radio, backhaul, modem and clock, as coloured chips | **Scans for WiFi networks in range and joins one** — pick it from a list, type the password, and the gateway joins immediately without a reboot |
| Every node heard: last frame, raw tilt, vibration, temperature, battery, RSSI, SNR, hop count, GNSS, last event | Sends a test SMS through the real modem and the real recipient list |
| Spool depth, its backing, and anything shed | Edits the backend URL, the **realtime push endpoint**, MQTT broker, site, gateway id, SMS recipients and the AP password |
| Uplink counters, whether the backend is reachable, and the realtime feed's state | Reboots the gateway |
| Both addresses the page itself answers on | |

### Joining the site's WiFi from the page

The gateway is an access point **and** a station at the same time, which is what
makes this work: you join `mineguard-<gw-id>` from a phone, press **Scan for
networks**, pick the site's SSID from the list (strongest first, with the signal
shown), type the password, and press Save. The gateway joins straight away —
`uplink_wifi_apply()` reconfigures the station and reconnects — and the Network
card shows the result and the address the page is now also reachable at. Nothing
reboots, and the AP stays up throughout, so a wrong password costs a retype
rather than a trip up the pole.

### The realtime push endpoint

Two outbound paths, and they are not the same thing:

| | Backend URL | Realtime push URL |
|---|---|---|
| Carries | Raw protocol frames, base64, batched | A decoded JSON document: the gateway's state and the last reading from every node |
| To | `POST <api>/api/ingest` | `POST <whatever you type>` |
| Cadence | As soon as frames are spooled, retried until accepted | Every 10 s, while WiFi is up |
| On failure | Frames stay spooled — nothing is lost | Dropped; the next push carries current data anyway |
| Purpose | The system of record | Anything else that wants the data and has no copy of the protocol codec |

The push is deliberately allowed to fail. It runs after the ingest attempt in
the same task and never blocks it: trading a warning for a dashboard would be
the wrong way round. The document is the same one the web UI renders, built once
in `report.c` so the two cannot drift:

```json
{
  "gateway": "gw-01", "site": "jharia", "addr": 1, "uptime_s": 9241,
  "time_valid": true, "epoch": 1789000000,
  "wifi":   { "sta_up": true, "sta_ssid": "jharia-ops", "sta_ip": "10.0.0.42", "rssi": -63,
              "ap_ssid": "mineguard-gw-01", "ap_ip": "192.168.4.1", "ap_clients": 1 },
  "uplink": { "transport": "http", "api": "http://10.0.0.5:8000",
              "posted": 18422, "failures": 7, "downlinks": 3, "link_down": false },
  "push":   { "url": "https://ops.example.com/hook", "sent": 412, "failures": 1, "last_age_s": 4 },
  "spool":  { "backing": "microSD", "depth": 0, "shed": 0 },
  "mesh":   { "radio_up": true, "rx_total": 19003, "rx_dup": 4820, "rx_bad": 61,
              "relayed": 2211, "tx": 640, "crc_err": 61 },
  "sms":    { "modem": true, "registered": true, "csq": 17, "sent": 2, "suppressed": 11 },
  "vbat_mv": 12980,
  "nodes": [
    { "addr": 16, "age_s": 12, "frames": 1440, "rssi": -71, "snr_db": 9.5, "hops": 1,
      "have_tlm": true, "t_epoch": 1789000000, "pitch_mdeg": -1240, "roll_mdeg": 430,
      "vib_rms_mg": 12, "temp_c": 31.4, "vbat_mv": 3980, "flags": 0, "fix": 3, "sats": 9 },
    { "addr": 17, "…": "…", "event": "TILT RATE", "event_sev": 3, "event_epoch": 1789000000 }
  ]
}
```

Tilt in that document is raw, for the same reason it is raw on the page: the
baselines, the thermal correction and the reconstructed field live in the
backend, and a second opinion computed from less information would be a worse
one. HTTPS endpoints work — the certificate bundle is compiled in.

Implementation notes, because they are the constraints that shaped it: one HTML
file with inline CSS and JavaScript, no framework, no CDN and no web fonts — a
page that fetches anything from the internet is blank exactly where it is
needed. It is embedded in the binary via `EMBED_TXTFILES`, so there is no
filesystem to mount and it is served whether or not the SD card is fitted. The
HTTP task runs *below* the radio and uplink tasks: a phone refreshing a page
must never delay a frame off the air.

Tilt shown there is **raw** — no commissioning baseline, no thermal correction —
and the page says so. It is the right number for "this node is reporting" and
the wrong one for "this node is in trouble"; that judgement stays server-side,
where the baselines and the whole array are.

Anyone who can join the AP can reconfigure the gateway and send SMS from its
SIM. There is no login; the WPA2 password is the boundary, and the firmware
warns at every boot while it is still the default.

## Degraded modes

| Failure | What the firmware still does |
|---|---|
| No microSD | Buffers in RAM (~25 minutes of a 21-node field), and says so at boot |
| No WiFi / backend down | Spools indefinitely; the local rule engine still sends SMS |
| No MQTT broker | HTTP for uplink, and pulls pending configs instead of being pushed them |
| No modem | Everything except the offline alerting path, and logs that the path is down |
| No radio on a node | Still samples and logs to the console — a dead radio looks like a dead radio |
| No site network at all | The gateway's own AP still serves the web UI, so it can be diagnosed, joined to a network, and configured on site |
| Push endpoint down or wrong | Nothing else is affected: the frame path, the spool and SMS are untouched, and the UI shows the failure count |
| Node never gets a TIME_SYNC | Reports with a zero timestamp and listens instead of sleeping, rather than inventing rates from a free-running counter |
