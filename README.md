# micros

Repo for all things micro controllers.

Everything here is **MicroPython**, driven from macOS with **`mpremote`**, managed by **`uv`**.

## Layout

```
pi pico/
  pico-mpy-flash/   firmware .uf2 files, shared by both boards
  pico/             plain Pico (RP2040) projects  -> traffic light
  picoW/            Pico W (RP2040, 2022) projects -> mini robot
```

One repo, one host toolchain, one flow — the folder just records which board a
project is wired for.

> The folder name `pi pico` contains a space, so every shell path below has to be
> quoted. Renaming it to `pi-pico` would drop the quotes everywhere; say the word
> and I'll do it.

---

## The flow

Three steps, in order: **flash firmware once → connect → push code**.

The steps are *identical* for a plain Pico and a Pico W. Only two things differ:

1. which `.uf2` firmware file you flash, and
2. a handful of GPIO pins that mean different things (see [Pico vs Pico W](#pico-vs-pico-w)).

### 0. Host setup — once per machine

```bash
uv sync
```

Every command below goes through `uv run`, so there is no venv to activate:

```bash
uv run mpremote devs
```

### 1. Flash MicroPython — once per board

Only needed on a brand-new board, or to upgrade the firmware. **Not** part of the
day-to-day loop.

1. Put the board into bootloader mode. Either:
   - hold **BOOTSEL**, plug in USB, release; or
   - if MicroPython is already on it, skip the button entirely:
     ```bash
     uv run mpremote bootloader
     ```
2. A USB volume called `RPI-RP2` appears.
3. Copy the `.uf2` onto it. The board reboots on its own and the volume vanishes —
   that is success, not an eject error.

```bash
cp "pi pico/pico-mpy-flash/RPI_PICO_W-20251209-v1.27.0.uf2" /Volumes/RPI-RP2/
```

**Get the right file for the board.** Flashing the wrong one is the classic
"works on Pico but not Pico W" failure — the plain `RPI_PICO` build has no
`network` module and no `Pin("LED")` alias.

| Board | Chip | Firmware | Download |
|---|---|---|---|
| Pico | RP2040 | `RPI_PICO-*.uf2` | <https://micropython.org/download/RPI_PICO/> |
| Pico W (2022) | RP2040 | `RPI_PICO_W-*.uf2` | <https://micropython.org/download/RPI_PICO_W/> |
| Pico 2 | RP2350 | `RPI_PICO2-*.uf2` | <https://micropython.org/download/RPI_PICO2/> |
| Pico 2 W | RP2350 | `RPI_PICO2_W-*.uf2` | <https://micropython.org/download/RPI_PICO2_W/> |

Only the **Pico W** `.uf2` is checked in right now. If you put the traffic light
on a genuine plain Pico, grab `RPI_PICO-*.uf2` into `pi pico/pico-mpy-flash/` too.

### 2. Check the board is there

```bash
uv run mpremote devs
```

You want a line with a `/dev/cu.usbmodem*` port. If you only see
`cu.Bluetooth-Incoming-Port` and `cu.debug-console`, the board is not enumerating —
it is either still in bootloader mode (re-flash it) or on a charge-only USB cable.

### 3. Push and run code — the daily loop

Pick one of three modes depending on what you're doing:

**Run a script once, without installing it** — best while iterating:

```bash
uv run mpremote run "pi pico/pico/main.py"
```

Output streams to your terminal; Ctrl-C stops it. Nothing is written to the board,
so a power-cycle goes back to whatever was there before. Note: `run` does *not*
upload the imports, so this only works if the modules it imports are already on the
device (or you use `mount`, below).

**Mount a project folder as the device filesystem** — no copying at all:

```bash
uv run mpremote mount "pi pico/pico" repl
```

Then at the `>>>` prompt: `import main`. The board reads your local files live, so
edit-and-rerun is instant. Files are *not* persisted to the board — unmount and
it's gone.

**Install onto the board** — what you want once it works:

```bash
uv run mpremote cp "pi pico/pico/main.py" "pi pico/pico/traffic.py" :
```

The trailing `:` means "device root". Verify with:

```bash
uv run mpremote ls
```

#### Which file gets sent where

There is no per-board magic — the device has one flat filesystem, and only one
filename is special:

- **`main.py`** — MicroPython runs this automatically on every boot/reset. This is
  what makes the board work standalone on USB power with no laptop attached.
- **everything else** (`traffic.py`, …) — ordinary modules, only run when something
  `import`s them. They must be copied too, or `main.py` fails with `ImportError`.
- `boot.py` — runs *before* `main.py`. Use it for setup that must happen first,
  like bringing up WiFi.

So "deploying" is just: copy `main.py` plus every module it imports to `:`.

The project folders here (`pico/`, `picoW/`) are a **host-side** organisation only.
They flatten onto the device — the board has no idea which folder a file came from,
which is also why two projects can't be installed at once without renaming.

### 4. Watching a running board

```bash
uv run mpremote repl
```

Ctrl-C breaks into the running program, Ctrl-D soft-reboots (re-runs `main.py`),
**Ctrl-]** exits the repl and leaves the board running.

---

## When it gets stuck

**`could not open device` / `device busy`** — something else already holds the port.
Close the other repl/serial monitor. Only one process at a time.

**The board is unreachable because `main.py` is hogging the CPU.** An infinite
`uasyncio` loop does this, so it happens often:

```bash
uv run mpremote repl
```

then hit **Ctrl-C** to break in. From there, remove the offender so it stops
auto-running: `uv run mpremote rm :main.py`.

**Totally wedged** — force the bootloader and re-flash:

```bash
uv run mpremote bootloader
```

Re-flashing the same MicroPython `.uf2` normally leaves the filesystem intact. To
wipe the flash completely (files *and* firmware), drag
[`flash_nuke.uf2`](https://datasheets.raspberrypi.com/soft/flash_nuke.uf2) onto
`RPI-RP2` first, then flash MicroPython again.

**Hard reset without unplugging:**

```bash
uv run mpremote reset
```

**The servo or buzzer won't stop, and Ctrl-C seems to do nothing.** PWM is a
*hardware* peripheral — once configured it keeps generating pulses with no CPU
involvement, so killing the Python doesn't kill the output. Only `deinit()` or a
chip reset does. Every script here releases its PWM in a `finally` block; the trap
is anything that drives hardware *before* the `try`, which has no `finally` to
unwind it. The nuclear option always works:

```bash
uv run mpremote reset
```

**After a reset the servo sits at some odd angle and feels dead.** That's correct
behaviour, not a fault. A servo has no holding torque without a signal and never
self-centres — with no PWM it simply stays limp wherever it was left. Push it with
a finger: if it moves freely, it's released, not jammed.

**Verify what the hardware is actually doing** rather than guessing — read the
RP2040 registers directly:

```bash
uv run mpremote exec "import machine; b=0x40050000+0x14*7; print('slice7 CSR=0x%08x enabled=%d' % (machine.mem32[b], machine.mem32[b]&1)); print('GP15 FUNCSEL=%d (4=PWM, 5=SIO, 31=reset default)' % (machine.mem32[0x40014000+8*15+4]&0x1f))"
```

Slice is `(GP / 2) % 8`, and its register block is at `0x40050000 + 0x14 * slice`.

---

## Pico vs Pico W

The Pico W bolts a CYW43439 WiFi chip onto the RP2040, and it steals pins. Code
that works on a Pico can silently do nothing (or something weird) on a Pico W:

| | Pico | Pico W |
|---|---|---|
| Onboard LED | `Pin(25, Pin.OUT)` | `Pin("LED", Pin.OUT)` — it hangs off the WiFi chip, **not** a GPIO |
| GPIO 23 | SMPS power-save control | `WL_ON` — WiFi chip power |
| GPIO 24 | VBUS sense | `WL_D` — WiFi SPI data |
| GPIO 25 | onboard LED | `WL_CS` — WiFi chip select |
| GPIO 29 / ADC3 | VSYS/3 voltage sense | `WL_CLK`, shared with VSYS sense |
| VBUS detect | GPIO 24 | WiFi chip's `WL_GPIO2` |
| `import network` | not available | available |

**Practical rule: on a Pico W, treat GPIO 23, 24, 25 and 29 as off-limits.**
GPIO 0–22 and 26–28 behave the same on both boards.

Blink the onboard LED portably:

```python
import machine
led = machine.Pin("LED", machine.Pin.OUT)   # works on Pico W; on plain Pico use 25
led.value(1)
```

---

## Projects

### `pi pico/pico/` — pedestrian crossing traffic light

Two light clusters plus a request button, run as cooperative `uasyncio` tasks.
See [main.py](pi%20pico/pico/main.py) for the wiring map and
[traffic.py](pi%20pico/pico/traffic.py) for the state machine.
[traffic.html](pi%20pico/pico/traffic.html) is a browser-side visualisation.

```bash
uv run mpremote cp "pi pico/pico/main.py" "pi pico/pico/traffic.py" : && uv run mpremote reset
```

### `pi pico/picoW/` — mini robot

A head that looks around, greets whatever it finds, and follows it.
[robot.py](pi%20pico/picoW/robot.py) is the whole thing in one self-contained file.

```bash
uv run mpremote run "pi pico/picoW/robot.py"
```

Install it so it runs from a USB power bank with no laptop attached — note the
`:main.py` destination, which renames it on the way over:

```bash
uv run mpremote cp "pi pico/picoW/robot.py" :main.py && uv run mpremote reset
```

#### Wiring

| Part | Signal | Physical pin | Power |
|---|---|---|---|
| SG90 servo | GP15 | 20 | VBUS (pin 40) |
| HC-SR04 TRIG | GP2 | 4 | VBUS (pin 40) |
| HC-SR04 ECHO | GP3 **via 1k/2k divider** | 5 | |
| Passive buzzer | GP16 **via 330R** | 21 | GPIO, or 3V3 (pin 36) for 3-pin modules |

All grounds common, to a Pico GND (pin 38). The servo and HC-SR04 genuinely need
5V — **never 3V3**, that rail is the RP2040's own regulator and a servo will brown
it out mid-move.

ECHO pulses to 5V and the Pico's GPIOs are 3.3V-only, so the divider is not
optional; without it the pin eventually dies.

**Pin choice is not free.** RP2040 PWM has 8 slices, each shared by a GPIO pair
(`slice = (GP / 2) % 8`), and a slice has **one** frequency. The servo needs 50 Hz
and the buzzer needs kilohertz, so they must be on different slices. GP15 is slice
7, so GP14 would collide — GP16 (slice 0) is clear.

**The buzzer's series resistor is not decoration.** Two different parts get sold as
"passive buzzer": a *piezo* disc draws microamps, but a *magnetic* one is a coil of
a few tens of ohms. `buzzer_id.py` measured this one at **~42 Ω — magnetic**, so
the 330 Ω is the only thing holding the pin to ~9 mA against its 12 mA rating.
Don't drop it. A two-pin passive buzzer has no polarity that matters; a square wave
reversed is the same square wave.

That also caps volume at ~3 mW. To go louder the coil has to come off the GPIO
entirely, onto a small NPN: `GP16 →[1k]→ base`, `3V3 → buzzer → collector`,
`emitter → GND`, and a **1N4148 across the buzzer, banded end to 3V3** to catch the
coil's turn-off spike. That's ~74 mA and roughly 18 dB louder — and duty cycle
becomes a real volume control instead of being pinned at maximum.

#### Test each part before running the robot

Every one of these has a debugging ladder in its header, written from what
actually went wrong here:

```bash
uv run mpremote run "pi pico/picoW/main.py"            # LED only, no wiring — is the link alive?
uv run mpremote run "pi pico/picoW/servo_test.py"      # sweeps GP15
uv run mpremote run "pi pico/picoW/ultrasonic_test.py" # live distance bar graph
uv run mpremote run "pi pico/picoW/buzzer_test.py"     # scale, volume steps, slides
uv run mpremote run "pi pico/picoW/buzzer_tune.py"     # find the buzzer's resonant peak
uv run mpremote run "pi pico/picoW/buzzer_id.py"       # piezo or magnetic? (needs a GP26 jumper)
uv run mpremote run "pi pico/picoW/servo_track.py"     # scan-and-point, no sound
```

**If the buzzer is quiet, it's almost certainly the frequency, not the power.** A
buzzer is a mechanical resonator with a sharp peak — this one measured **4000 Hz**
with `buzzer_tune.py`. An octave and a half below that it's inaudibly weak no
matter what duty cycle you set. `robot.py` expresses every tone as a ratio of
`PEAK_HZ`, so re-measuring and changing that one constant retunes the whole
personality and keeps the intervals intact. (Also: 50% duty is the maximum — past
`32768` the pulse narrows again and it gets *quieter*.)

Three traps that cost real time, all recorded in those headers: a breadboard's
power rails are **split in the middle** into isolated halves; an unconnected GPIO
floats on 50 Hz mains hum and reads as a convincing, unchanging ~150 cm; and a
**passive** buzzer needs a square wave while an **active** one only beeps on DC
and ignores PWM entirely.

#### Tuning knobs

All at the top of `robot.py`:

| Constant | Does what | Turn it… |
|---|---|---|
| `GLIDE_DEG_PER_S` | head travel speed | down for stately, up for frisky |
| `HOLD_TOLERANCE_CM` | distance drift still counting as "same thing" | up if it fidgets, down if it stares at where you were |
| `HEADING_DEADBAND` | bearing change too small to bother turning for | up to calm it down |
| `NUDGE_SPAN` / `WIDE_SPAN` | how far it glances when the reading shifts | up if it loses you when you move |
| `DETECT_CM` | how far away it notices things | down if it keeps finding furniture |
| `VOLUME` | duty cycle | only meaningful once a transistor is carrying the current |
| `PEAK_HZ` | buzzer resonance | re-measure with `buzzer_tune.py` if you swap the buzzer |

#### What it cannot do

The HC-SR04 measures distance and nothing else — it has no idea which direction an
echo came from. The bearing comes from the servo's own position, so the head must
sweep to find anything. That makes tracking inherently laggy (~1.5s per update) and
limits bearing resolution to the beam width, ~15°. It also follows the *nearest*
thing, not a particular thing. Below ~15 cm the sensor is deaf — still ringing from
its own ping — and reports whatever is behind your hand instead.

---

## Reference

- [mpremote docs](https://docs.micropython.org/en/latest/reference/mpremote.html) — every command above
- [MicroPython `rp2` quick reference](https://docs.micropython.org/en/latest/rp2/quickref.html) — Pin, PWM, ADC, I2C, SPI on the Pico
- [Raspberry Pi Pico series documentation](https://www.raspberrypi.com/documentation/microcontrollers/pico-series.html) — datasheets, pinout diagrams
- [Connecting to the Internet with Raspberry Pi Pico W](https://datasheets.raspberrypi.com/picow/connecting-to-the-internet-with-pico-w.pdf) — the WiFi book, needed for anything network-controlled
