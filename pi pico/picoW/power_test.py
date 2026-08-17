"""Power budget test -- add one peripheral at a time until something breaks.

Board:  Raspberry Pi Pico W (RP2040, 2022).
Run:    uv run mpremote run "pi pico/picoW/power_test.py"
Or via the Pi the Pico is plugged into (see README section 5) -- and on the Pi
ALWAYS run it with the kernel log, because the log is the actual instrument:
        scp "pi pico/picoW/power_test.py" my-pi:/tmp/ && ssh -t my-pi 'sudo dmesg -C; ~/.local/bin/mpremote run /tmp/power_test.py; echo "--- kernel ---"; sudo dmesg | tail -20; vcgencmd get_throttled'

WHY THIS FILE EXISTS

Everything on this robot shares the Pico's VBUS rail, and on a Raspberry Pi 5
that port allows 600mA TOTAL for the whole board. There is no external supply.
Every peripheral has been proven to work ALONE; none has been proven to work
alongside the others, and current is the one resource they all compete for:

    Pico W                      ~40mA
    HC-SR04                     ~15mA
    buzzer                       ~9mA   while sounding
    SG90 servo                 ~200mA   easing in 1 degree steps
                              700mA-1A  commanded to move flat out
    8 x WS2812B                  50mA   held there by the software limiter
                                480mA   if that limiter were removed

Adding them up on paper says it fits. Paper is not evidence -- inrush is
transient, and a 600mA limiter reacts to peaks, not to averages. So escalate
for real and let the hardware answer.

WHAT IT ACTUALLY COSTS THE HOST -- measured, not estimated

Sampled on the Pi 5 while robot.py ran with everything active:

    robot total                ~314mA   ~1.6W of the 600mA port budget
    EXT5V_V under load     4.977-5.026V  no sag, drifts up as often as down
    kernel log after dmesg -C   empty   no over-current, disconnect or undervolt
    mpremote on the Pi          24MB    0.2% of 8GB, ~1% of one core
    Pi load average          unchanged  0.17 before, 0.17 during

Note `lsusb` reports 250mA for the board. Ignore it: bMaxPower is what the
Pico's USB descriptor DECLARES, not what the robot draws.

The 600mA cap is worth understanding the right way round. It protects the HOST,
not the robot: exceed it and the port trips, the Pico drops off the bus with
Errno 5, and the host's own work carries on untouched. The blast radius of a
power mistake here is this robot and nothing else.

Two honest limits on those figures. vcgencmd was sampled at 1Hz and cannot see
a millisecond inrush spike -- the instrument that can is the kernel's
over-current message, which is why an empty dmesg is the load-bearing evidence
rather than the voltage readings. And the 600mA is shared across ALL the host's
USB ports, so plugging in a second powered device changes the arithmetic.

HOW TO READ THE RESULT

Each stage prints before it starts and after it survives. If the Pico browns
out, USB re-enumerates, mpremote dies with `OSError: [Errno 5] Input/output
error`, and the LAST STAGE PRINTED is the one that broke the budget. That is
the number this file exists to produce.

Afterwards, `dmesg` gives the reason directly:

    over-current change     the port's limiter tripped -- too much current
    USB disconnect          the Pico dropped off the bus
    Undervoltage detected   the whole Pi sagged, not just the port

An empty log means every stage fitted, and the ceiling is somewhere above what
this test asked for.

THE SERVO EASING IS LOAD-BEARING, TWICE OVER

servo_test.py fails on this rail and robot.py does not, and the difference is
not luck. servo_test.py commands whole-travel steps, so the motor goes flat out
and draws its peak for the length of the slew. robot.py eases in 1 degree
smoothstep increments, so the motor never reaches full speed and never reaches
full current. The gentle motion added to stop a light base tipping over is the
same thing keeping this robot inside the USB budget.

That is why the glide here mirrors robot.py's easing rather than stepping. A
test that slammed the servo would report a budget the real robot never spends.

Each stage also includes robot.py's genuine worst case -- the be_startled
flinch, 26 degrees at 210 deg/s -- because peak demand is what trips a limiter,
and an average that fits is no use if the peak does not.

IF IT FAILS AT STAGE 1

Then the LED ceiling is the thing to lower. STRIP_MA below is the single knob;
drop it to 30 and re-run. If stage 1 fails even at 30mA, the servo has less
headroom than measured earlier and the honest fix is a second 5V source -- a
USB phone charger plus a USB-A breakout is 5V at 1-2A for very little. Tie its
ground to a Pico GND and leave VBUS out of the strip entirely.

WIRING -- exactly as the individual test files document:

    servo signal   ->  GP15   pin 20      (5V and GND from the rails)
    HC-SR04 TRIG   ->  GP2    pin 4
    HC-SR04 ECHO   ->  1k/2k divider  ->  GP3   pin 5
    buzzer         ->  330R   ->  GP16   pin 21
    strip DIN      ->  330R   ->  GP18   pin 24
    strip +5       ->  5V rail from VBUS pin 40
    all grounds    ->  GND rail -> GND pin 38
"""

import machine
import time

try:
    import neopixel
except ImportError:
    raise SystemExit(
        "no `neopixel` module in this firmware -- see README section 1."
    )

SERVO_PIN = 15
TRIG_PIN = 2
ECHO_PIN = 3
BUZZER_PIN = 16
LED_PIN = 18

PIXELS = 8

# Lower than led_test.py's 80mA: that figure was measured with the strip alone,
# and the servo now wants its glide current back. This is the one knob to turn
# if stage 1 fails. See the header.
STRIP_MA = 50
MA_PER_CHANNEL = 20
QUIESCENT_MA = 1

# Servo pulse limits and frame, same as every other file here.
FREQ = 50
PERIOD_US = 1_000_000 // FREQ
MIN_US = 500
MAX_US = 2500

CENTRE_DEG = 90
SWEEP_LOW = 40
SWEEP_HIGH = 140

# Mirrors robot.py. GLIDE is the ordinary searching speed; FLINCH is the
# fastest move the robot ever makes and therefore its peak current demand.
GLIDE_DEG_PER_S = 110
FLINCH_DEG_PER_S = 210
FLINCH_DEG = 26

VOLUME = 32768
PEAK_HZ = 4000

TIMEOUT_US = 30_000
CM_PER_US = 0.0343

STAGE_SECONDS = 8


class Servo:
    def __init__(self, pin):
        self.pwm = machine.PWM(machine.Pin(pin))
        self.pwm.freq(FREQ)
        self.deg = CENTRE_DEG

    def angle(self, deg):
        deg = max(0, min(180, deg))
        us = MIN_US + (MAX_US - MIN_US) * deg // 180
        self.pwm.duty_u16(us * 65535 // PERIOD_US)
        self.deg = deg

    def glide(self, to, deg_per_s=GLIDE_DEG_PER_S):
        """Eased move, 1 degree at a time, smoothstep 3t^2-2t^3.

        Easing is why this robot fits in the USB budget at all -- it keeps
        the motor off its current peak. Mirrors robot.py deliberately.
        """
        frm = self.deg
        span = to - frm
        if span == 0:
            return
        steps = abs(span)
        total_ms = int(steps * 1000 / deg_per_s)
        step_ms = max(1, total_ms // steps)
        for i in range(1, steps + 1):
            t = i / steps
            eased = t * t * (3 - 2 * t)
            self.angle(int(frm + span * eased))
            time.sleep_ms(step_ms)

    def release(self):
        self.pwm.deinit()


class Buzzer:
    def __init__(self, pin):
        self.pwm = machine.PWM(machine.Pin(pin))
        self.pwm.duty_u16(0)

    def start(self, hz):
        self.pwm.freq(hz)
        self.pwm.duty_u16(VOLUME)

    def stop(self):
        self.pwm.duty_u16(0)

    def release(self):
        self.pwm.deinit()


class Strip:
    """8 pixels with a hard current ceiling.

    Identical limiter to led_test.py, where it was verified against hand
    arithmetic: a frame's draw is estimated before it is sent and the whole
    frame scaled down if it would exceed STRIP_MA, so relative brightness
    between pixels survives and no colour request can exceed the ceiling.
    """

    def __init__(self, pin, n):
        self.np = neopixel.NeoPixel(machine.Pin(pin), n)
        self.n = n

    def estimate_ma(self, frame):
        channels = sum(sum(px) for px in frame)
        return self.n * QUIESCENT_MA + channels * MA_PER_CHANNEL / 255

    def show(self, frame):
        budget = STRIP_MA - self.n * QUIESCENT_MA
        wanted = self.estimate_ma(frame) - self.n * QUIESCENT_MA
        scale = 1.0
        if wanted > budget and wanted > 0:
            scale = budget / wanted
        for i, px in enumerate(frame):
            self.np[i] = (int(px[0] * scale), int(px[1] * scale), int(px[2] * scale))
        self.np.write()

    def fill(self, colour):
        self.show([colour] * self.n)

    def clear(self):
        self.fill((0, 0, 0))


servo = Servo(SERVO_PIN)
buzzer = Buzzer(BUZZER_PIN)
strip = Strip(LED_PIN, PIXELS)
trig = machine.Pin(TRIG_PIN, machine.Pin.OUT)
echo = machine.Pin(ECHO_PIN, machine.Pin.IN)

machine.Pin("LED", machine.Pin.OUT).value(1)


def read_cm():
    """One HC-SR04 ping. None if the echo never came back."""
    trig.value(0)
    time.sleep_us(5)
    trig.value(1)
    time.sleep_us(10)
    trig.value(0)
    us = machine.time_pulse_us(echo, 1, TIMEOUT_US)
    if us < 0:
        return None
    return us * CM_PER_US / 2


def worst_case(use_buzzer):
    """robot.py's peak demand: the be_startled flinch.

    Full white on the strip at the same time, which the limiter will scale
    down, plus the squeal if the buzzer is in play. If anything trips, it
    should trip here rather than during a gentle sweep.
    """
    strip.fill((255, 255, 255))
    if use_buzzer:
        buzzer.start(int(PEAK_HZ * 1.45))
    target = CENTRE_DEG - FLINCH_DEG if servo.deg >= CENTRE_DEG else CENTRE_DEG + FLINCH_DEG
    servo.glide(target, FLINCH_DEG_PER_S)
    if use_buzzer:
        buzzer.stop()
    servo.glide(CENTRE_DEG, GLIDE_DEG_PER_S)


def run_stage(name, leds, use_buzzer, use_sonar):
    """Sweep for STAGE_SECONDS with the given peripherals all active."""
    print("STAGE: %s -- starting" % name)
    started = time.ticks_ms()
    step = 0
    going_up = True

    while time.ticks_diff(time.ticks_ms(), started) < STAGE_SECONDS * 1000:
        if leds:
            # A moving band, so current is genuinely varying rather than
            # sitting at a constant the rail can settle into.
            frame = []
            for i in range(PIXELS):
                on = (i + step) % PIXELS < 3
                frame.append((255, 140, 0) if on else (0, 0, 0))
            strip.show(frame)

        target = SWEEP_HIGH if going_up else SWEEP_LOW
        servo.glide(target)
        going_up = not going_up

        if use_buzzer:
            buzzer.start(PEAK_HZ)
            time.sleep_ms(80)
            buzzer.stop()

        if use_sonar:
            cm = read_cm()
            print("   ping: %s" % ("none" if cm is None else "%.0f cm" % cm))
            time.sleep_ms(70)

        step += 1

    print("   worst case: flinch %d deg at %d deg/s" % (FLINCH_DEG, FLINCH_DEG_PER_S))
    worst_case(use_buzzer)
    print("STAGE: %s -- SURVIVED\n" % name)


try:
    strip.clear()
    servo.angle(CENTRE_DEG)
    time.sleep_ms(500)

    print("strip ceiling %dmA; unlimited full white would be %.0fmA\n"
          % (STRIP_MA, strip.estimate_ma([(255, 255, 255)] * PIXELS)))

    run_stage("0 servo alone (baseline, known good)", False, False, False)
    run_stage("1 servo + LED strip", True, False, False)
    run_stage("2 servo + LED + buzzer", True, True, False)
    run_stage("3 servo + LED + buzzer + ultrasonic", True, True, True)

    print("ALL STAGES SURVIVED -- the full robot fits in the budget.")
    print("Raise STRIP_MA in ~20mA steps and re-run to find the real ceiling.")
except KeyboardInterrupt:
    print("\nCtrl-C -- stopping")
finally:
    # Runs on Ctrl-C too. The servo and buzzer are hardware PWM and would keep
    # going without this; the strip latches its last frame and holds it.
    strip.clear()
    buzzer.release()
    servo.release()
    print("released -- servo limp, buzzer silent, pixels off")
