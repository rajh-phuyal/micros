"""LED strip test -- 8-pixel addressable WS2812B strip on GP18.

Board:  Raspberry Pi Pico W (RP2040, 2022).
Run:    uv run mpremote run "pi pico/picoW/led_test.py"
Or via the Pi the Pico is plugged into (see README section 5):
        scp "pi pico/picoW/led_test.py" my-pi:/tmp/ && ssh -t my-pi '~/.local/bin/mpremote run /tmp/led_test.py'
        See ../../README.md for the full flash/connect/push flow.

WIRING -- three flying leads, and the END MATTERS:

    yellow  DIN   ->  330R resistor  ->  GP18   physical pin 24
    black   GND   ->  GND rail       ->  GND    physical pin 23 (right beside GP18)
    red     +5    ->  the 5V rail fed from VBUS physical pin 40

USE THE END MARKED "DIN". The strip is one-way: data shifts in at DIN and out
at DO so strips can be daisy-chained. Feeding DO does absolutely nothing, and
a backwards strip looks exactly like a dead one -- no flicker, no first pixel,
nothing. Both ends are labelled ("+5 / DIN / GND" and "+5 / DO / GND"), so
trace the yellow lead and confirm it lands on DIN before suspecting anything
in this file.

POWER -- SHARING VBUS, WHICH IS A REAL CONSTRAINT

Everything on this robot runs off the Pico's VBUS rail, and on a Raspberry Pi 5
the USB port caps at 600mA TOTAL for the whole board. Rough draw:

    Pico W                      ~40mA
    HC-SR04                     ~15mA
    buzzer                       ~9mA   (only while sounding)
    SG90 servo                 ~200mA   while gliding
                              700mA-1A  if commanded to move flat out
    8 x WS2812B                 480mA   at full white
                                  ~8mA  with all pixels off

Full white plus a moving servo is over budget on its own, and servo inrush
alone already exceeded it once: `servo_test.py` trips `over-current`, the Pico
disconnects and re-enumerates, and the host reports `OSError: [Errno 5]
Input/output error`, which looks nothing like a power fault.

WHY robot.py SURVIVES AND servo_test.py DOES NOT

servo_test.py commands whole-travel steps -- angle(0), then angle(90). The
servo goes flat out and draws its peak for the length of the slew. robot.py
eases every move in 1 degree smoothstep increments at 30-210 deg/s, so the
motor never reaches full speed and never reaches full current. The gentle
motion that was added to stop a light base tipping is also what keeps the
robot inside the USB budget. Do not "optimise" the easing away.

SO THE STRIP IS CURRENT-LIMITED IN SOFTWARE, NOT BRIGHTNESS-LIMITED

A percentage brightness cap does not bound current, because current depends on
how many channels are lit, not on how bright one looks: 25% white and 75% red
draw about the same. So estimate the draw of each frame BEFORE sending it and
scale the whole frame down if it exceeds STRIP_MA. A WS2812B is three ~20mA
LEDs plus a ~1mA controller, which makes the estimate simple arithmetic and
accurate enough to design against.

The result is a hard ceiling no colour choice can exceed. A bug that asks for
eight pixels of full white gets a dim white instead of browning out the rail
and taking the Pico's USB connection with it.

STRIP_MA IS SET LOW ON PURPOSE. Start conservative and raise it while watching
the kernel log -- the Pi tells you when you have gone too far:

    ssh my-pi 'sudo dmesg -C; ~/.local/bin/mpremote run /tmp/led_test.py; sudo dmesg | tail'

An empty log means you stayed inside the budget. `over-current change` or
`USB disconnect` means back it off. That is a measurement, not a guess, and it
beats picking a number and hoping.

NO EXTERNAL SUPPLY? THE CHEAPEST WAY OUT

If the ceiling turns out too dim to be worth having, the fix is a second 5V
source -- and any USB phone charger is one. A USB-A breakout board, or a
sacrificial cable with the red and black conductors stripped, gives 5V at 1-2A
for very little. Feed the strip from that, tie its ground to a Pico GND, and
leave VBUS out of it entirely. Grounds MUST be common or the data line has no
reference and the strip sees garbage.

THE SERIES RESISTOR, AND THE CAPACITOR YOU DO NOT NEED YET

330R in series on the data line, placed at the STRIP end rather than the Pico
end, damps the reflection on a fast edge. 220R does the same job; anywhere in
100R-470R is fine. Without it the classic symptom is pixel 0 flickering or
showing a wrong colour while 1-7 behave.

The usual advice is also a 1000uF cap across the strip's +5 and GND. That cap
exists to absorb large fast current swings, and STRIP_MA has deliberately made
those swings small -- tens of milliamps, not hundreds. So it is genuinely
optional at this ceiling. It becomes necessary if you later fit a proper
supply and raise STRIP_MA towards the strip's real 480mA.

3.3V DATA INTO A 5V STRIP IS OUT OF SPEC

A WS2812B wants a logic high near 0.7 x VDD = 3.5V. GP18 gives 3.3V. It
usually works and it is what nearly every Pico project does, but there is no
margin. If pixel 0 misbehaves while 1-7 are perfect, this is why: pixel 0 is
the only one reading a 3.3V signal, because each pixel reshapes and retransmits
at a full 5V to the next. Fixes in order of effort: keep the data wire short,
then a level shifter.

WHY THERE IS NO PIN-CONFLICT PUZZLE HERE

WS2812B bit timing is ~1.25us per bit at roughly +/-150ns, far too tight for a
Python loop, so `neopixel` drives it from the RP2040's PIO -- a programmable
state machine, separate hardware from the PWM block. None of the GP14/GP15
slice-sharing reasoning that forced the buzzer onto GP16 applies here. There
are 8 state machines (2 blocks x 4) and the robot uses none, so any free GPIO
works. GP18 is chosen only because it is unused and sits beside a GND pin (23).

COLOUR ORDER

The hardware shifts GREEN first -- these are GRB parts. MicroPython's
`neopixel` already accounts for that, so plain `(r, g, b)` tuples are correct
and part 3 below will show the colour it names. If red and green come out
swapped you have a clone with a different internal order, and the fix is to
swap channels on assignment, not to rewire anything.

IF NOTHING LIGHTS -- test the links, do not re-check the wiring by eye:

1. Wrong end?           See above. Most likely single cause.
2. Is the 5V rail live? LED + 220R from the strip's +5 row to the GND row.
                        Breadboard rails are usually SPLIT IN THE MIDDLE into
                        isolated halves that look continuous -- already the
                        actual fault once in this project.
3. Is GP18 alive?       LED + 220R from GP18 to the "-" rail, then
                            uv run mpremote exec "import machine,time; p=machine.Pin(18,machine.Pin.OUT); [(p.toggle(),time.sleep(0.4)) for _ in range(15)]; p.value(0)"
                        Blinking proves the pin, the hole and the rail at once.
4. Grounds tied?        The strip's GND and a Pico GND must be the same node.
5. Only some light?     If fewer than 8 respond, PIXELS is wrong -- part 2
                        counts them for you.
"""

import machine
import time

try:
    import neopixel
except ImportError:
    raise SystemExit(
        "no `neopixel` module in this firmware.\n"
        "Flash a current MicroPython build for the Pico W -- see README\n"
        "section 1. Every official build since 1.20 ships it."
    )

LED_PIN = 18
PIXELS = 8

# --- the current ceiling ---------------------------------------------------

# Everything shares VBUS with a 600mA total budget, so the strip gets a hard
# allowance rather than a brightness percentage. 80mA is deliberately timid:
# it leaves the servo its glide current and the Pico its own. Raise it in
# steps of ~40mA while watching `dmesg` (see the header) -- an empty kernel
# log means you are still inside the budget.
STRIP_MA = 80

# A WS2812B is three LEDs at roughly 20mA each at full scale, plus about 1mA
# for the controller even when dark. Datasheets say 20mA/channel; real parts
# land a little under, so this errs high, which is the safe direction.
MA_PER_CHANNEL = 20
QUIESCENT_MA = 1

RED = (255, 0, 0)
GREEN = (0, 255, 0)
BLUE = (0, 0, 255)
WHITE = (255, 255, 255)
OFF = (0, 0, 0)


strip = neopixel.NeoPixel(machine.Pin(LED_PIN), PIXELS)


def estimate_ma(frame):
    """Predicted draw of a frame, in mA, before it is sent.

    Channels are independent current sinks, so the total is simply the sum of
    every channel scaled by its duty. The quiescent term is per pixel and
    unavoidable -- it is drawn even by a dark strip.
    """
    channels = sum(sum(px) for px in frame)
    return PIXELS * QUIESCENT_MA + channels * MA_PER_CHANNEL / 255


def show(frame):
    """Send a frame, scaled down if it would exceed STRIP_MA.

    Scaling is applied to the whole frame at once rather than per pixel, so
    relative brightness between pixels is preserved -- a gradient stays a
    gradient, it just gets dimmer. Only the controllable part is scaled: the
    quiescent draw cannot be reduced, so it is excluded from the ratio.
    """
    budget = STRIP_MA - PIXELS * QUIESCENT_MA
    wanted = estimate_ma(frame) - PIXELS * QUIESCENT_MA

    scale = 1.0
    if wanted > budget and wanted > 0:
        scale = budget / wanted

    for i, px in enumerate(frame):
        strip[i] = (int(px[0] * scale), int(px[1] * scale), int(px[2] * scale))
    strip.write()
    return scale


def fill(colour):
    return show([colour] * PIXELS)


def clear():
    show([OFF] * PIXELS)


def wheel(pos):
    """0-255 around the colour wheel as three 0-255 channels.

    Three 85-wide ramps: red to green, green to blue, blue back to red.
    Cheaper than an HSV conversion and quite good enough for eight pixels.
    """
    pos %= 256
    if pos < 85:
        return (255 - pos * 3, pos * 3, 0)
    if pos < 170:
        pos -= 85
        return (0, 255 - pos * 3, pos * 3)
    pos -= 170
    return (pos * 3, 0, 255 - pos * 3)


# Onboard LED on as a liveness indicator -- lit means the board has power and
# got as far as running this.
machine.Pin("LED", machine.Pin.OUT).value(1)

print("ceiling: %dmA for %d pixels" % (STRIP_MA, PIXELS))
print("unlimited full white would be %.0fmA\n" % estimate_ma([WHITE] * PIXELS))

try:
    clear()
    time.sleep_ms(300)

    # 1. Proof of life before anything clever. One pixel is a few mA, so this
    #    works even if the rail has almost nothing spare.
    print("1) pixel 0 only -- proves data, power and ground all reach the strip")
    show([WHITE] + [OFF] * (PIXELS - 1))
    time.sleep(2)
    clear()
    time.sleep_ms(400)

    # 2. Walk one pixel down the strip. This is the count test: the highest
    #    number that actually lights is how many pixels you have, and it also
    #    shows which physical end is pixel 0.
    print("2) walking one pixel -- count them, and note which end starts")
    for i in range(PIXELS):
        frame = [OFF] * PIXELS
        frame[i] = WHITE
        show(frame)
        print("   pixel", i)
        time.sleep_ms(350)
    clear()
    time.sleep_ms(400)

    # 3. Colour order check. If these come out wrong it is channel ordering in
    #    the part, not a wiring fault -- see the header.
    print("3) red, green, blue -- named, so you can check the order")
    for name, colour in (("red", RED), ("green", GREEN), ("blue", BLUE)):
        scale = fill(colour)
        print("   %-6s %3d%% of requested" % (name, int(scale * 100)))
        time.sleep(1)
    clear()
    time.sleep_ms(400)

    # 4. Ramp. This is also the limiter's own test: past a certain level the
    #    reported percentage starts falling below 100, which is the ceiling
    #    doing its job. The strip should stop getting brighter and simply
    #    stay put rather than flickering or resetting the board.
    print("4) fading white up -- watch the limiter engage")
    for level in range(0, 256, 15):
        scale = fill((level, level, level))
        print("   level %3d -> %3d%% of requested" % (level, int(scale * 100)))
        time.sleep_ms(120)
    for level in range(255, -1, -15):
        fill((level, level, level))
        time.sleep_ms(60)
    clear()
    time.sleep_ms(400)

    # 5. The one that looks like a robot rather than a test rig.
    print("5) rainbow -- two turns of the wheel")
    for step in range(512):
        show([wheel(step + i * 256 // PIXELS) for i in range(PIXELS)])
        time.sleep_ms(12)

    print("done")
except KeyboardInterrupt:
    print("\nCtrl-C -- stopping")
finally:
    # Runs on Ctrl-C too. Unlike PWM the strip is not a peripheral that keeps
    # running by itself -- each pixel latches its last value and holds it
    # indefinitely, so without this the strip stays lit after the script exits
    # and Ctrl-C looks like it did nothing.
    clear()
    print("cleared -- all pixels off")
