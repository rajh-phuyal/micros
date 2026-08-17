"""Servo test -- sweep a hobby servo on GP15.

Board:  Raspberry Pi Pico W (RP2040, 2022).
Run:    uv run mpremote run "pi pico/picoW/servo_test.py"
Or via the Pi the Pico is plugged into (see README section 5):
        scp "pi pico/picoW/servo_test.py" my-pi:/tmp/ && ssh -t my-pi '~/.local/bin/mpremote run /tmp/servo_test.py'
        See ../../README.md for the full flash/connect/push flow.

WIRING -- read before plugging in:

    servo signal (orange/yellow)  ->  GP15   physical pin 20
    servo V+     (red)            ->  its own 5V supply, NOT the Pico
    servo GND    (brown/black)    ->  that supply's GND *and* GND pin 38

Do NOT power the servo from 3V3 (physical pin 36). That rail is a small
regulator for the RP2040 itself -- a servo's stall current will brown it out
and reset the board mid-move.

VBUS (physical pin 40) is tempting and often *seems* to work, but it is the
USB rail, and an SG90 pulls 700mA-1A on inrush. Measured on a Raspberry Pi 5,
which caps USB at 600mA total unless its firmware trusts the supply, the very
first move triggers `over-current`, the Pico disconnects and re-enumerates, and
the host reports `OSError: [Errno 5] Input/output error` from inside mpremote --
which looks nothing like a power fault. A laptop port has more headroom and
hides this for longer, which is worse: it fails later, under load, intermittently.

So give the servo its own 5-6V supply -- power bank, 4xAA, bench supply -- with
its GND tied back to a Pico GND pin. They MUST share a ground: the pulse width
is measured against it, so without the link the servo ignores the signal
entirely. Do not connect the external 5V to VBUS as well. A 470-1000uF
capacitor across the servo supply absorbs the inrush.

GP15's logic high is 3.3V, technically under spec for a 5V servo, but the
common SG90/MG90 clones accept it. If the servo twitches or ignores you and
the wiring is right, that is the first thing to suspect.

IF NOTHING MOVES -- test each link, do not re-check the wiring by eye:

1. Is the GPIO alive?  LED + 220R from GP15 to the "-" rail, then
       uv run mpremote exec "import machine,time; p=machine.Pin(15,machine.Pin.OUT); [(p.toggle(),time.sleep(0.4)) for _ in range(15)]; p.value(0)"
   Blinking proves the pin, the hole, and the "-" rail all at once.

2. Is the "+" rail alive?  Same LED + 220R straight from "+" to "-".
   It lights on USB power alone, no command needed.

   ^ this was the actual fault the first time. Breadboard power rails are
   usually SPLIT IN THE MIDDLE into two isolated halves -- they look like one
   continuous strip. A VBUS jumper in the top half feeds nothing plugged into
   the bottom half. Same trap applies to the "-" rail.

3. Signal wire in the right row?  It must share a row with GP15 AND sit on the
   same side of the centre channel. 20B-20E are connected to 20A; 20F-20J are
   a separate strip despite the same row number.

4. Still nothing?  Fit a horn before condemning the servo -- a bare spline
   turning is quiet and easy to miss.
"""

import machine
import time

SERVO_PIN = 15

# Pulse width in microseconds at each end of travel. 500-2500us is the usual
# full-180 range for SG90-style servos, but clones vary. If it buzzes, strains,
# or clicks at the extremes it is grinding against a mechanical stop -- narrow
# these towards 1000/2000 until it goes quiet. Leaving a servo stalled against
# its own end stop will cook the gears.
MIN_US = 500
MAX_US = 2500

# Hobby servos want a 50Hz frame -- one pulse every 20000us. duty_u16 spreads
# 0-65535 across that whole frame, so a pulse width converts as
# us / 20000 * 65535.
FREQ = 50
PERIOD_US = 1_000_000 // FREQ


class Servo:
    def __init__(self, pin, min_us=MIN_US, max_us=MAX_US):
        self.pwm = machine.PWM(machine.Pin(pin))
        self.pwm.freq(FREQ)
        self.min_us = min_us
        self.max_us = max_us

    def write_us(self, us):
        us = max(self.min_us, min(self.max_us, us))
        self.pwm.duty_u16(us * 65535 // PERIOD_US)

    def angle(self, deg):
        deg = max(0, min(180, deg))
        self.write_us(self.min_us + (self.max_us - self.min_us) * deg // 180)

    def release(self):
        """Stop driving the pin. The servo goes limp instead of holding."""
        self.pwm.deinit()


# Onboard LED on as a liveness indicator -- lit means the board has power and
# got as far as running this.
machine.Pin("LED", machine.Pin.OUT).value(1)

servo = Servo(SERVO_PIN)

try:
    # Step to a few known angles first -- if these work but the sweep does not,
    # the problem is speed/power, not wiring.
    for deg in (0, 90, 180, 90, 0):
        print("angle:", deg)
        servo.angle(deg)
        time.sleep(1)

    print("sweeping")
    for deg in range(0, 181, 5):
        servo.angle(deg)
        time.sleep(0.02)
    for deg in range(180, -1, -5):
        servo.angle(deg)
        time.sleep(0.02)

    servo.angle(90)
    time.sleep(0.5)
    print("done -- centred, releasing")
finally:
    # Runs on Ctrl-C too, so an interrupted test never leaves the servo
    # straining against a stop.
    servo.release()
