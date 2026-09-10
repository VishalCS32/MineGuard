# Hardware — build sheet and complete pin connections

Everything needed to build one node and one gateway: parts, every wire, the
power design, and the bring-up order that finds a mistake in five minutes
instead of after the field trip.

The pin numbers here are generated from `firmware/common/board_pins.h`, which is
what the firmware compiles against. **That header is the authority.** If this
document and the header ever disagree, the header is right and this document is
stale — fix it.

```
     NODE  ×21                                   GATEWAY  ×1
 ┌───────────────────────┐                 ┌────────────────────────────┐
 │  ESP32-S3 mini        │                 │  ESP32-S3 mini  (same board)│
 │   ├ I2C ─ LIS3DH      │                 │   ├ SPI ─┬ E220-900M22S    │
 │   ├ GPIO ─ SW-420     │  ~865.1 MHz     │   │      └ microSD         │
 │   ├ UART ─ NEO-6M     │ ◄────mesh────►  │   ├ UART ─ SIM800L ─ SMS   │
 │   ├ SPI ─ E220-900M22S│   multi-hop     │   ├ WiFi ─ backend         │
 │   └ ADC ─ 18650 + sun │                 │   └ WiFi AP ─ on-site UI   │
 └───────────────────────┘                 └────────────────────────────┘
```

**One board, two roles.** The gateway is the same ESP32-S3 mini as a node, with
different modules on the same headers and a different value in NVS. One board to
source, one board to keep as a spare, and the radio half of the wiring is
verified twenty-one times before the gateway is ever built.

---

## 1. Bill of materials

### Per node (×21)

| # | Part | Spec that matters | Approx ₹ |
|---|---|---|---|
| 1 | ESP32-S3 mini dev board | Native USB, ≥4 MB flash, RTC GPIOs 0–21 broken out | 350 |
| 2 | LIS3DH breakout | ±2 g, I²C, **INT1 broken out** — the wake pin | 180 |
| 3 | E220-900M22S + breakout | The **M** variant: LLCC68 over SPI. Not the T (UART) variant | 650 |
| 4 | 865–867 MHz antenna + SMA pigtail | ~3 dBi whip; must be tuned for 865, not 915 or 433 | 200 |
| 5 | NEO-6M GNSS module | With ceramic patch antenna and its own backup cell | 300 |
| 6 | SW-420 or 801S vibration module | Digital output, potentiometer threshold | 60 |
| 7 | 18650 cell, 3400 mAh + holder | Protected cell | 350 |
| 8 | TP4056 charger w/ protection, or CN3791 MPPT | MPPT is worth it if the panel is 6 V | 60 |
| 9 | Solar panel 6 V 2 W | ~30× the average draw in four winter hours | 250 |
| 10 | Resistors 100 kΩ ×2, 4.7 kΩ ×2, 2N7000 | Battery divider and its gate; I²C pull-ups | 20 |
| 11 | Capacitors 100 µF + 100 nF | At the radio's supply pins, not at the far end of a wire | 15 |
| 12 | IP65 enclosure + gland + galvanised post | The post is a measurement component — see §6 | 500 |

### Gateway (×1)

| # | Part | Spec that matters | Approx ₹ |
|---|---|---|---|
| 1 | ESP32-S3 mini dev board | **The same board as a node.** WiFi station + access point, native USB | 350 |
| 2 | E220-900M22S + breakout + antenna | Same radio as the nodes, better sited | 850 |
| 3 | SIM800L module | 2G, and **its own 4 V supply** — see §5 | 350 |
| 4 | microSD module + 8 GB card | SPI, 3.3 V logic | 200 |
| 5 | Buck converter 4.0 V 3 A | For the modem alone. Not shared, not linear | 200 |
| 6 | Buck converter 5 V 2 A | For the ESP32 board's own regulator | 150 |
| 7 | 12 V 7 Ah SLA or LiFePO₄ + 20 W panel + solar charge controller | Runs the modem's bursts through a cloudy week | 3500 |
| 8 | Capacitor 2200 µF low-ESR + 100 nF | At the SIM800L's pins | 40 |
| 9 | Resistors 100 kΩ, 22 kΩ, 1 kΩ, 2 kΩ | Supply divider; modem TX level divider | 20 |
| 10 | SIM card with SMS pack | 2G still carried by the major Indian operators | — |

---

## 2. Node — complete pin connections (ESP32-S3)

### 2.1 LIS3DH accelerometer — I²C

| LIS3DH pin | ESP32-S3 | Notes |
|---|---|---|
| VIN / VCC | 3V3 | 3.3 V only |
| GND | GND | |
| SDA | **GPIO8** | 4.7 kΩ pull-up to 3V3 (the breakout usually has one) |
| SCL | **GPIO9** | 4.7 kΩ pull-up to 3V3 |
| INT1 | **GPIO4** | Deep-sleep wake. Must be an RTC GPIO (0–21) |
| SDO / SA0 | GND *or* 3V3 | GND → address 0x18, 3V3 → 0x19. The driver probes both |
| CS | 3V3 | **Tie high or the part comes up in SPI mode** and I²C is silent |

### 2.2 SW-420 / 801S vibration sensor

| Module pin | ESP32-S3 | Notes |
|---|---|---|
| VCC | 3V3 | |
| GND | GND | |
| DO | **GPIO5** | Second deep-sleep wake source. RTC GPIO |

Set the module's potentiometer so its LED is off at rest and flickers when the
post is tapped. Too sensitive and the node wakes on wind, spending its battery
on nothing; too dull and it sleeps through a blast.

### 2.3 E220-900M22S radio — SPI2

| E220 signal | ESP32-S3 | Notes |
|---|---|---|
| VCC | 3V3 | ≥150 mA capability; 100 µF + 100 nF **at the module** |
| GND | GND | Both/all ground pins |
| MOSI | **GPIO11** | |
| SCK | **GPIO12** | |
| MISO | **GPIO13** | |
| NSS / CS | **GPIO10** | |
| BUSY | **GPIO14** | Read before every transaction; not optional |
| DIO1 | **GPIO15** | IRQ line |
| NRST | **GPIO16** | Driven low for 5 ms at boot |
| ANT | 865 MHz antenna | **Never power the module without one** |

DIO2 drives the module's internal RF switch and is not brought out; the firmware
enables that (`dio2_as_rf_switch = true`). The module runs from a crystal, not a
TCXO, so `use_tcxo` stays false. Both are set in `llcc68_default_cfg()`.

### 2.4 NEO-6M GNSS — UART1

| NEO-6M pin | ESP32-S3 | Notes |
|---|---|---|
| VCC | Switched 3V3 (see below) | ~45 mA when acquiring |
| GND | GND | |
| RX | **GPIO17** (ESP TX) | Named from the ESP32's side — cross them |
| TX | **GPIO18** (ESP RX) | |
| PPS | **GPIO6** | Optional; unused by the current firmware |

Power switching: **GPIO21** drives a P-MOSFET high-side switch (or a load-switch
IC) feeding the module's VCC. The receiver is off for 99% of the node's life.

```
                 ┌─────────────┐
   3V3 ──────────┤S  AO3401  D ├────────── NEO-6M VCC
                 └──────G──────┘
                        │
              100k to 3V3 (keeps it off)
                        │
                     drain of 2N7000
                        │
   GPIO21 ── 10k ── gate of 2N7000 ;  source to GND
```

GPIO21 high turns the small NPN/FET on, which pulls the P-MOSFET gate down,
which powers the receiver. High = GNSS on, and the firmware leaves it low.

### 2.5 Battery sense

| Node | Connection |
|---|---|
| BAT+ | 100 kΩ → sense node |
| sense node | 100 kΩ → drain of a 2N7000, and **GPIO7** (ADC1_CH6) |
| 2N7000 gate | **GPIO1** — the divider only conducts while a reading is taken |
| 2N7000 source | GND |

A permanently connected 200 kΩ divider across the cell draws 21 µA, which is
comparable to the node's entire sleep current. Gating it costs one transistor.

### 2.6 Everything else

| Function | ESP32-S3 | Notes |
|---|---|---|
| Status LED | **GPIO2** | Through 330 Ω to GND |
| Console | USB (native) | Provisioning; see `firmware/README.md` |
| BOOT | GPIO0 | On-board button |

### 2.7 Node pin map, at a glance

```
        ESP32-S3 mini
   GPIO1  ── battery divider gate      GPIO11 ── E220 MOSI
   GPIO2  ── status LED                GPIO12 ── E220 SCK
   GPIO4  ── LIS3DH INT1   (wake)      GPIO13 ── E220 MISO
   GPIO5  ── SW-420 DO     (wake)      GPIO14 ── E220 BUSY
   GPIO6  ── NEO-6M PPS   (optional)   GPIO15 ── E220 DIO1
   GPIO7  ── battery sense (ADC1)      GPIO16 ── E220 NRST
   GPIO8  ── LIS3DH SDA                GPIO17 ── NEO-6M RX
   GPIO9  ── LIS3DH SCL                GPIO18 ── NEO-6M TX
   GPIO10 ── E220 NSS                  GPIO21 ── NEO-6M power switch
```

Free and deliberately so: GPIO3, 45, 46 (strapping pins), 19/20 (native USB),
26–32 (SPI flash and PSRAM — not available on any S3 module).

---

## 3. Gateway — complete pin connections (ESP32-S3)

The same board as a node. Where a node has an accelerometer, a vibration switch
and a GNSS receiver, the gateway has a microSD card and a 2G modem — on the very
same pins:

| Node header | On a node | On a gateway |
|---|---|---|
| GPIO8 | LIS3DH SDA | SIM800L STATUS (input) |
| GPIO9 | LIS3DH SCL | microSD CS |
| GPIO17 | GNSS RX | SIM800L RXD (via divider) |
| GPIO18 | GNSS TX | SIM800L TXD |
| GPIO21 | GNSS power switch | SIM800L PWRKEY |
| GPIO7 | 18650 sense (2.00× divider) | 12 V rail sense (5.55× divider) |
| GPIO4, 5 | wake inputs | unused |

### 3.1 E220-900M22S radio and microSD — one shared SPI bus (SPI2)

| Signal | ESP32-S3 | Goes to |
|---|---|---|
| MOSI | **GPIO11** | E220 MOSI **and** SD DI |
| SCK | **GPIO12** | E220 SCK **and** SD CLK |
| MISO | **GPIO13** | E220 MISO **and** SD DO |
| E220 NSS | **GPIO10** | radio chip select |
| SD CS | **GPIO9** | card chip select |
| E220 BUSY | **GPIO14** | |
| E220 DIO1 | **GPIO15** | |
| E220 NRST | **GPIO16** | |

The radio's seven wires are identical to a node's, which is the point: it is the
half of the wiring that has already been built and tested twenty-one times.

Two devices, one bus, two chip selects: they are never accessed at the same
moment and ESP-IDF serialises the bus anyway. Add a 10 kΩ pull-up to 3V3 on each
CS so neither device sees a floating select while the board boots.

### 3.2 SIM800L modem — UART1

| SIM800L pin | ESP32-S3 | Notes |
|---|---|---|
| VCC | **4.0 V buck**, not 5 V, not 3.3 V | See §5. This is the part that goes wrong |
| GND | Common ground, thick wire | Star from the buck, joined to the board's ground |
| RXD | **GPIO17** through a divider | 3.3 V → 2.8 V: 1 kΩ series, 2 kΩ to GND |
| TXD | **GPIO18** direct | 2.8 V clears the ESP32's input threshold |
| PWRKEY | **GPIO21** via NPN or open-drain | Pulled low ≥1 s to toggle power |
| STATUS | **GPIO8** | High once the modem is running |
| NET | its own antenna | Helical or wire; keep it away from the 865 MHz whip |

### 3.3 Supply sense and indicators

| Function | ESP32-S3 | Notes |
|---|---|---|
| 12 V rail sense | **GPIO7** (ADC1_CH6) | 100 kΩ / 22 kΩ divider: 14 V → 2.52 V |
| Status LED | **GPIO2** | Through 330 Ω to GND. Anode to the pin, cathode to ground — see §3.6 |
| Console | USB (native) | Provisioning, same as a node |

### 3.4 Gateway pin map, at a glance

```
        ESP32-S3 mini  (gateway role)
   GPIO2  ── status LED                GPIO13 ── SPI MISO  (E220 + SD)
   GPIO7  ── 12 V rail sense (ADC1)    GPIO14 ── E220 BUSY
   GPIO8  ── SIM800L STATUS            GPIO15 ── E220 DIO1
   GPIO9  ── microSD CS                GPIO16 ── E220 NRST
   GPIO10 ── E220 NSS                  GPIO17 ── SIM800L RXD (via divider)
   GPIO11 ── SPI MOSI  (E220 + SD)     GPIO18 ── SIM800L TXD
   GPIO12 ── SPI SCK   (E220 + SD)     GPIO21 ── SIM800L PWRKEY
```

Free and deliberately so, on both roles: GPIO3, 45, 46 (strapping pins), 19/20
(native USB — the provisioning console), 26–32 (SPI flash and PSRAM, not
available on any S3 module).

### 3.5 Status LED — what the blinking means

One LED on a box in the rain is a constrained display, so it answers the
question somebody actually walks over to ask: *is this working, and if not,
which part is broken?* It reports the **worst** thing that is true, read the way
a car's diagnostic flash is read — N short blinks, a pause, repeat.

| Pattern | Meaning | First thing to check |
|---|---|---|
| **Continuous fast flash** | The radio never started | E220 wiring, antenna, supply — nothing can be received |
| **1 blink**, then a long pause | Healthy: receiving from the field, delivering to the backend | — |
| **2 blinks** | Radio fine, but no node heard for three minutes | The gateway's own antenna first, then the field |
| **3 blinks** | No modem, or it has no network | The SIM800L's supply (§5), then the SIM and its antenna |
| **4 blinks** | Not joined to any WiFi network | Join one from the web UI; frames are being spooled meanwhile |
| **5 blinks** | WiFi up, backend not answering | The backend. Nothing is lost — frames are held |
| **6 blinks** | The spool backlog is deep enough to start shedding | How long the outage has run |
| **Brief flick, any time** | A frame just arrived from a node | Nothing — this is the mesh breathing |

The flick is the useful one day to day: standing next to the box you can watch
the field report, one flick per frame, with no equipment at all.

A healthy gateway flashes for 60 ms every 3 seconds — about 2% duty — so the
indicator is neither a drain on a solar gateway nor a nuisance at night. The
same state is shown on the web UI as a chip with the blink count and a sentence
explaining it, so a blink count read in the dark can be looked up on a phone
instead of in a manual.

If your board's LED is wired to 3V3 through the pin rather than to ground, pass
`true` for `active_low` in `statusled_start()` — otherwise the indicator is lit
except when it is trying to tell you something.

### 3.6 The gateway's own web UI

The gateway runs a WiFi **access point as well as a station**, and serves a
single page from its own flash at `http://192.168.4.1`:

| | |
|---|---|
| SSID | `mineguard-<gateway id>`, e.g. `mineguard-gw-01` |
| Password | WPA2, `set ap-pass <something>` — the default is `mineguard` and the firmware complains at every boot until it is changed |
| URL | `http://192.168.4.1`, or the gateway's address on the site network |

It shows whether the radio, the backhaul, the modem and the clock are alive,
every node the gateway has heard with its last reading and link quality, and how
deep the spool has grown. From the same page you can **scan for WiFi networks in
range and join one** — the gateway connects immediately, without a reboot, and
the page stays reachable on the AP throughout, so a mistyped password costs a
retype rather than a trip back up the pole. It also sends a test SMS, edits the
backend URL and the realtime push endpoint, and reboots the gateway.

No laptop, no USB cable, and no internet — which matters because on a mine site
the network the gateway is supposed to use is frequently the thing that is
broken, and a diagnostic interface that needs the broken component is not a
diagnostic interface.

Two outbound URLs are configured there, and they are different things: the
**backend URL** takes raw protocol frames (`POST /api/ingest`, the system of
record, retried until accepted), and the optional **realtime push URL** takes a
decoded JSON document of the gateway and every node, every ten seconds, for
anything else that wants the data and has no copy of the protocol codec. The
push is allowed to fail; the frame path is not.

Anyone who can join that AP can reconfigure the gateway and send SMS from its
SIM. Change the password.

---

## 4. Node power

| State | Draw | Fraction of a minute |
|---|---|---|
| Deep sleep (ESP32-S3 + LIS3DH watching + E220 asleep + regulator) | ~20 µA | ~58 s |
| Wake, sample burst, feature extraction | ~30 mA | ~1.5 s |
| Transmit, 22 dBm, 34-byte frame at SF9 | ~120 mA | ~0.25 s |
| Receive window (relaying, listening for a downlink) | ~12 mA | ~1.5 s |
| GNSS fix, hot start, once every ten cycles | ~45 mA | ~5 s / 10 min |

That averages **≈1.9 mA**, so a 3400 mAh cell runs roughly **70 days with no sun
at all**, and the 2 W panel covers the average draw about thirty times over in
four hours of winter light. The headroom is deliberate: it is what pays for a
cold GNSS start that takes 45 s instead of 5, and for a week of monsoon cloud.

Two things quietly destroy this budget, and both are configuration rather than
hardware: `CFG_FLAG_GNSS_ENABLED` left on with a short interval, and
`CFG_FLAG_DEEP_SLEEP` cleared. The second is legitimate — relay-backbone nodes
stay awake on purpose (see `firmware/README.md`) — but such a node needs mains
or a much larger panel, and it draws ~12 mA continuously rather than 1.9.

---

## 5. Gateway power — and the SIM800L problem

**Most "the SIM800L keeps rebooting" reports are power, not firmware.** During a
2G transmit burst it pulls up to **2 A for ~600 µs**, repeating at the GSM frame
rate. Consequences, all of them non-negotiable:

- It needs **3.4–4.4 V**. Not the 5 V rail, and not 3.3 V. A 4.0 V buck is the
  standard answer; an AMS1117 dropping 5 V to 4 V is not, because it cannot
  source 2 A and it turns the difference into heat.
- It needs **2200 µF low-ESR right at its own pins**, plus 100 nF. Bulk
  capacitance three centimetres away, past a breadboard rail, is not at its pins.
- It needs **thick, short supply wire**. 100 mΩ of wire resistance at 2 A is a
  200 mV sag, which lands the rail under the brownout threshold mid-command.

The symptom of getting this wrong is a modem that answers `AT` fine and resets
halfway through `AT+CMGS` — which looks exactly like a firmware bug and is not.

Rest of the gateway: 12 V battery → solar charge controller → two bucks (5 V for
the ESP32 board, 4 V for the modem), grounds joined in a star at the battery
negative. Average draw is ~150 mA at 5 V with WiFi up, so a 7 Ah battery carries
about a day and a half unlit, and a 20 W panel refills it in a morning.

---

## 6. Mounting — the post is part of the instrument

The node measures the attitude of whatever it is bolted to, so the mount is a
measurement component, not packaging.

- **Galvanised pipe, 1.5 m, at least 0.6 m into the ground**, concreted. A post
  in soft fill records the fill settling, not the seam.
- **Enclosure bolted rigidly to the post**, and the LIS3DH bolted rigidly to the
  enclosure. Any compliance in that chain shows up as tilt that is not ground.
- **Antenna vertical, as high as the post allows**, clear of the metalwork.
  Antenna height buys more range than any radio setting available on this chip —
  the LLCC68 is already at SF9, its ceiling at 125 kHz.
- **Solar panel facing south**, tilted at roughly the site's latitude, and not
  shading the GNSS patch.
- **Record the install**: node address, label, GPS position, and photographs.
  The first frame becomes the commissioning baseline and every later reading is
  measured against it.

Spacing along the survey line is set by the *sensing* constraint, not the radio
one: ≤ radius of influence ÷ 3, about 71 m at 150 m depth, against the radio's
~241 m. See `docs/WORKFLOW.md` §6a.

---

## 7. Bring-up order

Do this on a bench, one step at a time. Each step fails in a way you can see.

1. **Power only.** No modules connected. Board enumerates over USB, console
   prints the banner from `nodecfg_cli_start`.
2. **I²C.** Connect the LIS3DH. Boot log must contain `lis3dh: found at 0x18`
   (or 0x19). If it does not: CS not tied high, or the pull-ups are missing.
3. **Tilt sanity.** `show`, then tip the board 90°. Pitch and roll must swing by
   ~90000 mdeg and come back. If one axis does not move, the part is not
   soldered on that axis.
4. **Radio.** Connect the E220 **with its antenna**. Boot log:
   `llcc68: up: 866.100 MHz SF9 BW125 CR4/5 22 dBm sync 0x1424`. A `BUSY stuck
   high` message means wiring, reset, or supply — in that order of likelihood.
5. **Two boards.** Flash a second board, `set addr 0x0011`, and watch the first
   log received frames. This is the first moment the mesh exists.
6. **GNSS.** Outdoors, sky view. First fix from cold takes 30–60 s; the log
   prints position, satellite count and an accuracy estimate.
7. **Gateway.** Swap the node's modules for the microSD card and the modem (§3),
   then `set role gateway`, `set addr 0x0001`, `set ap-pass <something>`, `save`,
   `reboot`. Everything else can be typed on a phone: join `mineguard-gw-01`,
   open `http://192.168.4.1`, and fill in the settings form. Watch `posted`
   rise on that page, and rows appear at `/api/snapshot`.
8. **SMS.** Press *Send test SMS* on the gateway's page and confirm a message
   arrives, then trigger a real event on a node (tap it hard enough to breach
   `vib_alert_mg`) and confirm the alerting path fires on its own. Do both
   before deployment: it is the one channel nobody notices is broken until it
   is needed.

---

## 8. Failures you will actually meet

| Symptom | Cause, in order of likelihood |
|---|---|
| `BUSY stuck high` at boot | NRST not wired · module unpowered · MISO/MOSI swapped |
| Radio initialises, nothing is ever received | Antenna missing on one end · sync word mismatch · one board on 915 MHz hardware |
| `lis3dh: not responding at 0x18 or 0x19` | CS not tied high · SDA/SCL swapped · no pull-ups |
| Tilt drifts several hundred mdeg over a day | Normal — thermal expansion of the post. The backend subtracts it using the die temperature in every frame |
| Node reports, then vanishes for hours | Deep sleep with no clock: it never got a TIME_SYNC. Check the gateway is broadcasting |
| GNSS never fixes | Antenna indoors · TX/RX not crossed · module browning out on a shared 3V3 |
| Modem resets during `AT+CMGS` | Supply. See §5. It is essentially always the supply |
| `mineguard-gw-01` AP not visible | The AP password is under 8 characters, so the firmware refused to start an open network — `set ap-pass <8+ chars>` |
| Frames arrive with `hops` climbing every cycle | Relays are asleep at the wrong moment — the field's clocks have drifted apart. Shorten `TIME_SYNC_INTERVAL_S` |
| SD card not found | 3.3 V logic only · CS pull-up missing · card formatted exFAT (use FAT32) |
