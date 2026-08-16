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

Not started. For now this holds [main.py](pi%20pico/picoW/main.py), a connection
test that blinks the onboard LED — no wiring, USB cable only. Use it to confirm the
host↔board link before debugging anything else.

```bash
uv run mpremote run "pi pico/picoW/main.py"
```

---

## Reference

- [mpremote docs](https://docs.micropython.org/en/latest/reference/mpremote.html) — every command above
- [MicroPython `rp2` quick reference](https://docs.micropython.org/en/latest/rp2/quickref.html) — Pin, PWM, ADC, I2C, SPI on the Pico
- [Raspberry Pi Pico series documentation](https://www.raspberrypi.com/documentation/microcontrollers/pico-series.html) — datasheets, pinout diagrams
- [Connecting to the Internet with Raspberry Pi Pico W](https://datasheets.raspberrypi.com/picow/connecting-to-the-internet-with-pico-w.pdf) — the WiFi book, needed for anything network-controlled
