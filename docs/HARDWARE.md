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
 │  ESP32-S3-Zero        │                 │  ESP32-S3-Zero  (same board)│
 │   ├ I2C ─ LIS3DH      │                 │   ├ SPI ─┬ E220-900M22S    │
 │   ├ GPIO ─ SW-420     │  ~865.1 MHz     │   │      └ microSD         │
 │   ├ UART ─ NEO-6M     │ ◄────mesh────►  │   ├ UART ─ SIM800L ─ SMS   │
 │   ├ SPI ─ E220-900M22S│   multi-hop     │   ├ WiFi ─ backend         │
 │   └ ADC ─ 18650 + sun │                 │   └ WiFi AP ─ on-site UI   │
 └───────────────────────┘                 └────────────────────────────┘
```

**One board, two roles.** The gateway is the same ESP32-S3-Zero as a node, with
different modules on the same headers and a different value in NVS. One board to
source, one board to keep as a spare, and the radio half of the wiring is
verified twenty-one times before the gateway is ever built.

---

## 1. Bill of materials

### 1.1 The board — Waveshare ESP32-S3-Zero

Both roles run the same board: a **Waveshare ESP32-S3-Zero** (ESP32-S3FH4R2,
4 MB flash, 2 MB octal PSRAM, native USB, no USB-to-UART chip). Three of its
properties decide the pin map, and none of them are obvious from a generic
ESP32-S3 pinout:

| | |
|---|---|
| **Only 24 GPIOs are broken out** | **IO1–IO18, IO38–IO42, IO45.** Everything the firmware drives lives in IO1–IO18 |
| **GPIO21 is the onboard WS2812** | It is *not* brought out to a pad. It is the status indicator (§3.5) and nothing else can use it |
| **GPIO33–37 are octal PSRAM** | Not brought out. GPIO26–32 are the SPI flash, and 19/20 are the native USB the console runs on |

The consequence worth stating plainly: **GPIO21 cannot carry the GNSS load
switch or the SIM800L PWRKEY**, which a textbook S3 pin map would put there.
Both sit on **GPIO2** instead — broken out, not a strapping pin, and inside the
RTC-capable range GPIO0–21 so the node can hold the GNSS gate low through deep
sleep.

Two more consequences for bring-up, both of which look like a dead board:

- **To flash, hold BOOT (GPIO0) down while plugging the Type-C cable in.**
  There is no USB-to-UART chip to pull the board into download mode for you.
- The console is the ESP32-S3's own USB peripheral
  (`CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG=y`), so the serial port disappears and
  reappears across a reset. That is normal.

A different S3 board can be substituted — the firmware needs only 18 GPIOs and
`set led-pin` moves the indicator — but every pin number below assumes this one.

### 1.2 Per node (×21)

| # | Part | Spec that matters | Approx ₹ |
|---|---|---|---|
| 1 | Waveshare ESP32-S3-Zero | See §1.1 — the pin map assumes this board | 350 |
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

### 1.3 Gateway (×1)

| # | Part | Spec that matters | Approx ₹ |
|---|---|---|---|
| 1 | Waveshare ESP32-S3-Zero | **The same board as a node** (§1.1). WiFi station + access point, native USB | 350 |
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
post is tapped, with the module bolted down the way it will actually sit —
sensitivity depends on the mass it is attached to. Too sensitive and the node
wakes on wind, spending its battery on nothing; too dull and it sleeps through
a blast.

**This module is a wake source and nothing else.** `PIN_VIB_INT` appears in
exactly two places in the firmware — the EXT1 wake mask and an
`rtc_gpio_pulldown_en()` before sleep — and is never sampled while awake. The
`vib_rms_mg` in telemetry comes from the **LIS3DH**, so a node with no
accelerometer reports zero vibration however this module is wired. The two
split the job: the switch catches the event in milliseconds and costs no
standing current, and the accelerometer measures it once the node is up.

> **Both wake pins must stay inside GPIO0–21.** EXT1 wake works only on
> RTC-capable pins, and of the ones this board exposes (1–18, and 21 taken by
> the pixel) every one is already assigned except GPIO3, a strapping pin.
> GPIO38–42 and 45 are free but cannot wake the chip, so moving a wake source
> there does not relocate it — it silently removes the node's ability to
> respond to a blast before its next slot.

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

Power switching: **GPIO2** drives a P-MOSFET high-side switch (or a load-switch
IC) feeding the module's VCC. The receiver is off for 99% of the node's life.

> **This pin moved.** Earlier revisions of this document put the GNSS load
> switch on GPIO21, which does not exist as a pad on the ESP32-S3-Zero (§1.1).
> A board wired to the old map leaves the receiver permanently unpowered. If
> you wired VCC straight to 3V3 instead of through a switch, the module runs
> continuously — costing ~45 mA against a node budgeted for microamps, but it
> will at least report.

**Diagnosing "no fix".** `gnsstest` on the node console dumps raw bytes from
the receiver for ten seconds and says which of the two failures you have:

```
gnsstest
```

Zero bytes means nothing is reaching the ESP32 and the sky is irrelevant —
check that the module's TX goes to the ESP32's **RX** (the names here are from
the ESP32's side and they cross). Sentences scrolling past with no fix means
the link is fine and it really is the antenna, the sky, or a cold start; watch
the satellite count in `$GPGSV` climb.

```
                 ┌─────────────┐
   3V3 ──────────┤S  AO3401  D ├────────── NEO-6M VCC
                 └──────G──────┘
                        │
              100k to 3V3 (keeps it off)
                        │
                     drain of 2N7000
                        │
   GPIO2  ── 10k ── gate of 2N7000 ;  source to GND
```

GPIO2 high turns the small NPN/FET on, which pulls the P-MOSFET gate down,
which powers the receiver. High = GNSS on, and the firmware leaves it low.

**Not GPIO21**, which an S3 pinout would suggest and which earlier revisions of
this document specified: on the ESP32-S3-Zero that pin is the onboard WS2812's
data line and is not brought out to a pad at all (§1.1). GPIO2 is broken out,
is not a strapping pin, and is inside the RTC-capable range GPIO0–21 — which
matters here, because the gate level has to be held through deep sleep or the
receiver powers itself back up the moment the ESP32 stops driving it.

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
| Onboard RGB pixel | **GPIO21** | On the board already, and not brought out to a pad. **On by default**, reporting the radio — see §2.8 |
| Console | USB (native) | Provisioning; see `firmware/README.md` |
| BOOT | GPIO0 | On-board button |

### 2.7 Node pin map, at a glance

```
        ESP32-S3-Zero  (node role)
   GPIO1  ── battery divider gate      GPIO11 ── E220 MOSI
   GPIO2  ── NEO-6M power switch       GPIO12 ── E220 SCK
   GPIO4  ── LIS3DH INT1   (wake)      GPIO13 ── E220 MISO
   GPIO5  ── SW-420 DO     (wake)      GPIO14 ── E220 BUSY
   GPIO6  ── NEO-6M PPS   (optional)   GPIO15 ── E220 DIO1
   GPIO7  ── battery sense (ADC1)      GPIO16 ── E220 NRST
   GPIO8  ── LIS3DH SDA                GPIO17 ── NEO-6M RX
   GPIO9  ── LIS3DH SCL                GPIO18 ── NEO-6M TX
   GPIO10 ── E220 NSS                  GPIO21 ── onboard RGB pixel  ★
```

★ on the board already, not on a pad — see §1.1, and §2.8 for what it says.

Free and deliberately so: GPIO3 (strapping pin), 38–42, 45. Not available at
all on this board: 19/20 (native USB), 26–32 (SPI flash), 33–37 (octal PSRAM),
43/44 and 46–48 (not broken out).

### 2.8 Node status indicator

The node carries the same WS2812 as the gateway, on the same GPIO21, and
**lights it by default** — flags bit 5, set in the shipped defaults.

The power question is worth settling, because the obvious version of the
answer is wrong. A WS2812's controller draws ~1 mA even showing black, which
next to a sleeping node's ~10 µA looks disqualifying. But it draws that
whenever the pixel has power, and on a board with the pixel wired straight to
3V3 that is *always* — awake or deep asleep, flag set or flag clear. Clearing
bit 5 does not recover that milliamp. Only cutting the pixel's supply would,
and this board does not expose a way to.

What the flag actually costs is the light: one channel at brightness 24/255
for 60 ms every 3 s — a couple of milliamps at 2% duty, so under 0.1 mA
averaged, against a standing draw the board imposes either way. That is a
rounding error, and a rounding error is a bad reason to ship nodes that cannot
tell you why they are silent.

> **Measure it on your own board before trusting the arithmetic.** If a
> variant gates the pixel's supply, the standing milliamp *is* recoverable and
> the trade changes completely. Sleep current with `set flags 0x0F` versus
> `0x2F` will tell you in a minute.

To turn it off — a gated board, or an installation that must stay dark:

```
set flags 0x0F        the defaults without bit 5
save
reboot
```

A node whose config was saved **before** this flag existed keeps its old
flags, because NVS is restoring exactly what was written. Those boards come up
dark and say so in the boot log, with the command to fix it. `factory` also
does it, at the cost of the node's identity.

It answers one question — **can this node reach the field?** — because that is
the failure the dashboard cannot report. A node that cannot transmit looks
exactly like a node nobody installed. Tilt and battery are deliberately absent:
they arrive over the mesh and get a number next to them on a screen.

| Colour | Pattern | Meaning | First thing to check |
|---|---|---|---|
| 🔴 red | **Continuous fast flash** | The LLCC68 never answered on SPI | NSS, BUSY, NRST, then the module's supply |
| 🔴 red | **2 blinks** | It initialised, but transmits are not completing | The antenna, then the supply sagging under a 22 dBm transmit |
| 🟠 amber | **3 blinks** | Transmitting, but nothing has ever been heard back | Out of range of the gateway and every relay, or the far antenna |
| 🟠 amber | **4 blinks** | It was in the mesh and no longer is | The gateway, or a relay between here and it |
| 🟢 green | **1 blink**, long pause | Radio up, transmitting, hearing the mesh | — |
| 🔵 blue | **Brief flick** | A frame was just sent or heard | Nothing |

Two things worth knowing before you rely on it:

- **A quiet node is not a broken node.** A non-relay node may hear only the
  gateway's `TIME_SYNC`, which is every 600 s, so "lost the mesh" needs one
  missed sync plus margin (660 s) — not the three minutes a gateway is held to.
  The same applies to a node that has just booted and heard *nothing yet*: its
  first frame can legitimately be 600 s away, so it is given a full sync
  period before it is allowed to complain. Any tighter and every healthy node
  blinks a fault for the first several minutes of every boot, which teaches
  whoever installed them to ignore the light.
- **The gateway announces itself even with no clock**, once a minute, so a
  node reports the mesh as present as soon as it is actually in range —
  whether or not the gateway has reached NTP or a backend. Data flows the
  same way: a node's telemetry does not wait for a clock either.
- **3 blinks in the first ten minutes is not evidence of a bad link.** Use
  `rftest` (§2.9) to settle it — that works without a clock, without WiFi, and
  without the gateway having anything to say.
- **With deep sleep on, the light only lives during the wake window** — about
  two seconds a minute — because the LED task dies with the rest of the chip.
  A node that is dark for fifty-eight seconds out of sixty is working as
  designed, not broken, and the boot log says so. An always-on relay node
  shows it continuously.

The decision logic is pure and host-tested in `components/statusled`, the same
as the gateway's.

### 2.9 `rftest` — proving the link before you drive back down

Every other diagnostic in this system sits downstream of a working radio link,
so none of them can tell you the link is the problem. A node that boots,
initialises its LLCC68 and then reports nothing looks *identical* to a node
with a disconnected antenna, a node out of range, and a node whose gateway is
switched off. Four jobs, one symptom, twenty-one posts before dark.

`rftest` sends numbered frames and has the far end echo each one back with the
signal strength **it** measured. It runs from either end:

```
rftest                    node -> gateway, 20 round trips, smallest frame
rftest 0x0011             gateway -> that node
rftest 0x0011 50 40       50 round trips carrying 40 B of filler
```

```
  1   412 ms  us->them  -71 dBm  them->us  -74 dBm
  2   408 ms  us->them  -72 dBm  them->us  -73 dBm
  3   lost
  ...
sent 20, echoed 19, loss 5%
  rtt      404 / 415 / 448 ms  (min/avg/max)
  us->them -71 dBm avg, -78 dBm worst, SNR 7.5 dB
  them->us -74 dBm avg, -80 dBm worst, SNR 6.2 dB
  MARGINAL -- this link works today and will not survive rain or a
  full-length frame. Move the antenna or add a relay.
```

Four things worth knowing:

- **The echo carries the far end's RSSI**, which is the half of a link budget
  a one-way test cannot see. A link that is loud outbound and deaf inbound is
  real and common — a detuned antenna, or a receiver desensitised by its own
  switching supply — and from the transmitting side it looks perfect. The
  verdict is decided by the **worse** direction, never the average.
- **`pad` grows the frame.** A link that passes a 10 B ping does not
  necessarily pass a full-length telemetry frame: fading and marginal SNR hit
  long frames first. Test at the size you will actually send.
- **The bar is set for this system, not for radios in general.** A node
  reports once a minute and an alert has to arrive first time, so anything
  over 2% loss is reported as marginal. A link at 10% loss will drop an alert
  within the hour.
- **Test frames never reach the backend.** The gateway answers a ping and
  drops it — it carries no measurement, and the system of record has no reason
  to ever see one.

Any board answers a ping whether or not a test is running on it, so
node-to-node links can be walked as well as node-to-gateway ones — which is
how you check a relay hop actually exists.

---

## 3. Gateway — complete pin connections (ESP32-S3)

The same board as a node. Where a node has an accelerometer, a vibration switch
and a GNSS receiver, the gateway has a microSD card and a 2G modem — on the very
same pins:

| Node header | On a node | On a gateway |
|---|---|---|
| GPIO2 | GNSS power switch | SIM800L PWRKEY |
| GPIO9 | LIS3DH SCL | microSD CS |
| GPIO8 | LIS3DH SDA | SIM800L RXD (ESP TX, via divider) |
| GPIO7 | 18650 sense (2.00× divider) | SIM800L TXD (ESP RX) |
| GPIO6 | GNSS PPS (unused) | SIM800L STATUS (input) |
| GPIO4 | LIS3DH INT1 (wake) | 12 V rail sense (5.55× divider) |
| GPIO5 | SW-420 DO (wake) | unused |
| GPIO17, 18 | GNSS UART | free |

The modem's UART sits on **GPIO8/7**, not the 17/18 a node uses for its GNSS,
because 17 and 18 carry something else on the gateway hardware. Any UART routes
to any GPIO through the S3's matrix, so the move itself is free — but it
displaced the rail sense and the STATUS input, and the rail sense had to land
back inside **ADC1 (GPIO1–10)** or it would stop reading whenever WiFi is up.
GPIO4 satisfies that; `adc_oneshot_io_to_channel()` resolves the channel from
the pin, so no driver change was needed.

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
| RXD | **GPIO8** through a divider | ESP TX. 3.3 V → 2.8 V: 1 kΩ series, 2 kΩ to GND |
| TXD | **GPIO7** direct | ESP RX. 2.8 V clears the ESP32's input threshold |
| PWRKEY | **not wired** | The common blue breakout ties it on the module, so it starts with power. `PIN_SIM_PWRKEY` is `-1` |
| STATUS | **not wired** | Not brought out on that breakout. `PIN_SIM_STATUS` is `-1` |
| VDD | leave open, or use as the divider's reference | The module's own ~2.8 V logic rail, output not input. **Do not feed 3V3 into it** |
| RESET | leave open | Active low. The driver does not use it yet — it is the only way to restart this variant in software, so wire it if you want that |
| NET | its own antenna | Helical or wire; keep it away from the 865 MHz whip |

### 3.3 Supply sense and indicators

| Function | ESP32-S3 | Notes |
|---|---|---|
| 12 V rail sense | **GPIO4** (ADC1_CH3) | 100 kΩ / 22 kΩ divider: 14 V → 2.52 V |
| Status indicator | **GPIO21** | The RGB pixel already on the board, not brought out to a pad. Nothing to wire — see §3.5 |
| Console | USB (native) | Provisioning, same as a node |

### 3.4 Gateway pin map, at a glance

```
        ESP32-S3-Zero  (gateway role)
   GPIO4  ── 12 V rail sense (ADC1)    GPIO11 ── SPI MOSI  (E220 + SD)
   GPIO7  ── SIM800L TXD  (ESP RX)     GPIO12 ── SPI SCK   (E220 + SD)
   GPIO8  ── SIM800L RXD  (via divider) GPIO13 ── SPI MISO  (E220 + SD)
   GPIO9  ── microSD CS                GPIO14 ── E220 BUSY
   GPIO10 ── E220 NSS                  GPIO15 ── E220 DIO1
                                       GPIO16 ── E220 NRST
                                       GPIO21 ── onboard RGB pixel  ★

   Only four wires to the modem: TXD, RXD, and its own supply and ground.
   PWRKEY and STATUS are not on this breakout, so GPIO2 and GPIO6 are free.

   ★ the status indicator. On the board already, and not on a pad -- see 1.1.
```

Free on the gateway: GPIO1, 2, 3, 5, 6, 17, 18, 38–42, 45. Not available at all on this board:
19/20 (native USB — the provisioning console), 26–32 (SPI flash), 33–37 (octal
PSRAM), 43/44 and 46–48 (not broken out). GPIO3 and 45 are strapping pins and
are left alone even though they are exposed.

### 3.5 Status indicator — what the colours and blinks mean

The gateway uses the **RGB pixel already fitted to the ESP32-S3-Zero** — the
WS2812 on **GPIO21**. No LED, no resistor, no pad, nothing to wire, and one
part fewer to fail in a damp box.

GPIO21 is not brought out to a pad on this board; it exists only as the pixel's
data line. That is why the SIM800L's PWRKEY and the node's GNSS load switch sit
on GPIO2 instead — see §1.1.

The nodes carry the same pixel on the same pin and leave it dark — see §2.6.

The indicator answers the question somebody actually walks over to ask: *is
this working, and if not, which part is broken?* It reports the **worst** thing
that is true, never an average — a gateway with a dead radio and a fine
backhaul is a dead gateway.

The pixel says it in two channels at once, and both matter:

- **Colour — how bad it is.** Red: not doing its job. Amber: degraded, but
  nothing is being lost. Green: working. Blue: a frame just arrived.
- **Blink count — which fault it is**, read the way a car's diagnostic flash
  is read: N short blinks, a pause, repeat.

Colour alone would not do. Six hues do not survive a dirty enclosure, a dim
setting, or the roughly one man in twelve who cannot separate red from green —
so the colour is the summary and the count is the fact. Either alone is still
useful; together they are unambiguous.

| Colour | Pattern | Meaning | First thing to check |
|---|---|---|---|
| 🔴 red | **Continuous fast flash** | The radio never started | E220 wiring, antenna, supply — nothing can be received |
| 🔴 red | **2 blinks** | Radio fine, but no node heard for three minutes | The gateway's own antenna first, then the field |
| 🟠 amber | **3 blinks** | No modem, or it has no network | The SIM800L's supply (§5), then the SIM and its antenna |
| 🟠 amber | **4 blinks** | Not joined to any WiFi network | Join one from the web UI; frames are being spooled meanwhile |
| 🟠 amber | **5 blinks** | WiFi up, backend not answering | The backend. Nothing is lost — frames are held |
| 🟠 amber | **6 blinks** | The spool backlog is deep enough to start shedding | How long the outage has run |
| 🟢 green | **1 blink**, then a long pause | Healthy: receiving from the field, delivering to the backend | — |
| 🔵 blue | **Brief flick, any time** | A frame just arrived from a node | Nothing — this is the mesh breathing |

The blue flick is the useful one day to day: standing next to the box you can
watch the field report, one flick per frame, with no equipment at all.

**Colour looks wrong?** Two different faults, and the boot sweep tells them
apart in a second:

| Sweep comes out | Meaning | Fix |
|---|---|---|
| red, green, blue | Byte order is right | If amber still looks green, the mix is too green for the part — see below |
| **green, red, blue** | This pixel is RGB, not GRB. Red and green are swapped, so amber shows as yellow-green and the healthy green heartbeat shows as red | `set led-order rgb`, `save`, `reboot` |

Amber is mixed for the eye rather than for the arithmetic, and it has to be.
A WS2812's green die puts out roughly twice the luminous intensity of its red
at the same drive, and the eye sits near peak sensitivity at green's 525 nm
and well down the curve at red's 625 nm. "Red plus half as much green" —
which reads as amber written down — comes out perceptually even, which is a
yellow-green, and at this brightness people simply call that green. The
firmware uses a **fifth** as much green, and a host test holds it under a
third. If your part still skews green, lower `AMBER_G` in
`components/statusled/statusled_pattern.c`.

**At boot the pixel sweeps red, green, blue** and then goes dark. That is not
decoration. A healthy gateway's indicator is off 98% of the time, so without
the sweep "everything is fine" and "the pixel is on a different pin" look
identical to somebody in front of a new install. The sweep also proves the
byte order: the driver sends GRB, so a sweep that comes out **green, red,
blue** means this board's pixel wants RGB instead.

A healthy gateway flashes for 60 ms every 3 seconds — about 2% duty — so the
indicator is neither a drain on a solar gateway nor a nuisance at night. The
same state is shown on the web UI as a chip carrying the pixel's own colour, the
blink count and a sentence explaining it, so a count read in the dark can be
looked up on a phone instead of in a manual.

**If nothing lights up at all**, the board is not an ESP32-S3-Zero and its
pixel is on a different GPIO. A DevKitC-1 uses 48; other variants use 47, 38
or 8. It is not something the firmware can probe for, so it is a runtime
setting rather than a rebuild:

```
set led-pin 48
save
reboot
```

`set led-pin -` returns to the board default. The GPIO the indicator actually
came up on is reported as `led.gpio` in `/api/status`.

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

**Before reading any of this, run `modemtest` on the gateway console.** It
takes ten seconds and tells you which of three different faults you have,
rather than assuming the supply — which is the most common cause but not the
only one, and the other two are free to rule out.

**Most "the SIM800L keeps rebooting" reports are power, not firmware.** During a
2G transmit burst it pulls up to **2 A for ~600 µs**, repeating at the GSM frame
rate. Consequences, all of them non-negotiable:

- It needs **3.4–4.4 V**. Not the 5 V rail, and not 3.3 V. A 4.0 V buck is the
  standard answer; an AMS1117 dropping 5 V to 4 V is not, because it cannot
  source 2 A and it turns the difference into heat.
  > Many listings for the blue breakout silk-screen or label its supply pin
  > **"VCC 5V"**. That board has no regulator on it — the pin goes straight to
  > the module, whose absolute maximum is 4.4 V. Feeding it 5 V is how these
  > die. Measure the pin before trusting the label; if the board genuinely has
  > a buck on it you will see the inductor.
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

0. **Flash it.** Hold **BOOT** down while plugging the Type-C cable in — the
   ESP32-S3-Zero has no USB-to-UART chip to do that for you, and a board that
   simply does not appear to `idf.py flash` is almost always this and not a
   dead board (§1.1).
1. **Power only.** No modules connected. Board enumerates over USB, console
   prints the banner from `nodecfg_cli_start`, and **the onboard pixel sweeps
   red, green, blue** on a gateway build. That sweep is the whole indicator
   proving itself before anything else is connected — if it does not happen,
   fix that first (§3.5), because every later step reports through it.
2. **I²C.** Connect the LIS3DH. Boot log must contain `lis3dh: found at 0x18`
   (or 0x19). If it does not: CS not tied high, or the pull-ups are missing.
3. **Tilt sanity.** `show`, then tip the board 90°. Pitch and roll must swing by
   ~90000 mdeg and come back. If one axis does not move, the part is not
   soldered on that axis.
4. **Radio.** Connect the E220 **with its antenna**. Boot log:
   `llcc68: up: 866.100 MHz SF9 BW125 CR4/5 22 dBm sync 0x1424`. A `BUSY stuck
   high` message means wiring, reset, or supply — in that order of likelihood.
5. **Two boards.** Flash a second board, `set addr 0x0011`, and watch the first
   log received frames. This is the first moment the mesh exists. Then run
   `rftest` from one of them (§2.9): on a bench at a metre it should report 0%
   loss and a strong SNR both ways, and anything less means a problem you want
   to find now rather than on a hillside.
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
| GNSS never fixes, `0 sats seen` | Run `gnsstest` on the node. **0 bytes = wiring, not sky** — TX/RX not crossed, a broken lead, or the module unpowered. Sentences arriving but no fix = antenna, sky, or a cold start. §2.4 |
| GNSS LED blinks but the node reports no fix | The LED is on the PPS pin and only pulses **after** a fix, so the receiver is working and the ESP32 is not hearing it. That is the wiring case above |
| Modem resets during `AT+CMGS` | Supply. See §5. It is essentially always the supply |
| Dashboard says "no modem" | Run `modemtest` on the gateway console. It shouts AT across every plausible baud rate and prints the raw reply: **nothing at any rate** is wiring or supply, **an answer at the wrong rate** is a baud mismatch (`AT+IPR`), **garbage everywhere** is framing — a sagging supply or both ends disagreeing |
| `mineguard-gw-01` AP not visible | The AP password is under 8 characters, so the firmware refused to start an open network — `set ap-pass <8+ chars>` |
| Frames arrive with `hops` climbing every cycle | Relays are asleep at the wrong moment — the field's clocks have drifted apart. Shorten `TIME_SYNC_INTERVAL_S` |
| SD card not found | 3.3 V logic only · CS pull-up missing · card formatted exFAT (use FAT32) |
| A node's RGB pixel stays dark | Between wake windows this is normal on a deep-sleeping node (§2.8). If it never lights: a config saved before bit 5 existed is being restored from NVS — the boot log prints the exact `set flags` command to fix it |
| Node stuck on `[NO CLOCK]` for minutes with the gateway clearly up | Fixed: the gateway now sends `TIME_SYNC` the instant a node reports epoch 0, instead of waiting for the 600 s broadcast. A clockless node runs its GNSS every cycle and listens only half the time, so it could lose that coin flip for many minutes |
| `uplink failed` / `ESP_ERR_HTTP_CONNECT` while WiFi is up | `set api` points somewhere the gateway's own network cannot reach — compare the URL against the `sta ip` in the boot log. Radio and SMS are unaffected; frames spool until it returns |
| Node reports nothing and you cannot tell why | `rftest` from the node, then `rftest <addr>` from the gateway. Loss and both-direction RSSI separate "dead radio" from "dead antenna" from "out of range" (§2.9) |
| Amber shows as green, or the green heartbeat shows as red | Byte order. If the boot sweep comes out green/red/blue this part is RGB: `set led-order rgb`, `save`, `reboot`. If the sweep is correct, it is the colour mix — §3.5 |
| The gateway's RGB pixel never lights, not even the boot sweep | On an ESP32-S3-Zero the pixel is GPIO21 and that is the default. On any other board: `set led-pin 48` (or 47, 38, 8), `save`, `reboot`. §3.5 |
| The board does not appear when flashing | Hold **BOOT** while plugging the cable in. There is no USB-to-UART chip to enter download mode for you (§1.1) |
| The serial port vanishes on every reset | Normal. The console is the S3's own USB peripheral, so the port goes with the chip |
| The boot sweep comes out green, red, blue | This pixel wants RGB, not the GRB the driver sends. Swap `c.g` and `c.r` in `pixel()`, `components/statusled/statusled.c` |
