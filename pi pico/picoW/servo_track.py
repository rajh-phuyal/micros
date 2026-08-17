"""Scan and track -- point the head at the nearest object.

Board:  Raspberry Pi Pico W (RP2040, 2022).
Run:    uv run mpremote run "pi pico/picoW/servo_track.py"
        See ../../README.md for the full flash/connect/push flow.

Hardware (wiring detail lives in servo_test.py and ultrasonic_test.py):

    servo signal   ->  GP15
    HC-SR04 TRIG   ->  GP2
    HC-SR04 ECHO   ->  divider  ->  GP3
    both powered from VBUS, grounds common with the Pico

HOW IT WORKS, AND WHAT IT CANNOT DO

An HC-SR04 reports distance and nothing else. It has no idea which direction
an echo came from -- everything inside its ~15 degree cone reads the same. So
the head cannot see something and turn towards it. It sweeps, samples distance
at each angle, and points at whichever angle came back closest. The bearing
comes from the servo's own position, not from the sensor.

Consequences worth knowing before you build on this:

  * Bearing resolution is the beam width, ~15 degrees. Finer steps do not buy
    accuracy, only time.
  * Every update costs a whole sweep, so this is inherently laggy -- roughly
    1.7s per tracking update. That is physics with one fixed sensor, not
    something to optimise away in code.
  * It tracks the NEAREST thing, not a particular thing. Bring a second object
    closer and the head switches to it. There is no object identity here.

Two modes. SEARCH sweeps the full arc looking for anything within DETECT_CM.
TRACK sweeps a narrow window around the last known angle, which is quicker,
and falls back to SEARCH after LOST_LIMIT empty sweeps.

TIMING: readings are only taken once the servo has stopped moving. The servo
and the sensor share VBUS -- a moving servo both drags that rail down and
physically shakes the sensor, so sampling mid-move returns garbage. SETTLE_MS
is what keeps those two apart, and it is the main reason this is slow.
"""

import machine
import time

SERVO_PIN = 15
TRIG_PIN = 2
ECHO_PIN = 3

# --- servo -----------------------------------------------------------------
SERVO_FREQ = 50
PERIOD_US = 1_000_000 // SERVO_FREQ
SERVO_MIN_US = 500
SERVO_MAX_US = 2500

# --- scanning --------------------------------------------------------------
# Stay off the mechanical stops; an SG90 grinding against its own end stop
# will cook its gears.
SCAN_MIN_DEG = 15
SCAN_MAX_DEG = 165

COARSE_STEP = 15   # matched to the beam width
FINE_STEP = 10
FINE_SPAN = 20     # +/- this many degrees around the last known angle

SETTLE_MS = 150    # servo travel plus vibration die-down before sampling
PING_GAP_MS = 70   # sensor needs >=60ms of quiet between pings

DETECT_CM = 100    # ignore anything further away than this
LOST_LIMIT = 3     # empty fine sweeps before going back to a full search

# --- sensor ----------------------------------------------------------------
CM_PER_US = 0.0343
TIMEOUT_US = 30_000


class Servo:
    def __init__(self, pin):
        self.pwm = machine.PWM(machine.Pin(pin))
        self.pwm.freq(SERVO_FREQ)

    def angle(self, deg):
        deg = max(0, min(180, deg))
        us = SERVO_MIN_US + (SERVO_MAX_US - SERVO_MIN_US) * deg // 180
        self.pwm.duty_u16(us * 65535 // PERIOD_US)

    def release(self):
        self.pwm.deinit()


# Onboard LED on as a liveness indicator -- if it is lit, the board has power
# and got as far as running this. It stays on after the script exits; clear it
# with:  uv run mpremote exec "import machine; machine.Pin('LED', machine.Pin.OUT).value(0)"
machine.Pin("LED", machine.Pin.OUT).value(1)

servo = Servo(SERVO_PIN)
trig = machine.Pin(TRIG_PIN, machine.Pin.OUT)
echo = machine.Pin(ECHO_PIN, machine.Pin.IN)


def read_cm():
    """One measurement. Returns cm, or None if the ping never came back."""
    trig.value(0)
    time.sleep_us(2)
    trig.value(1)
    time.sleep_us(10)
    trig.value(0)
    us = machine.time_pulse_us(echo, 1, TIMEOUT_US)
    if us < 0:
        return None
    return (us * CM_PER_US) / 2


def measure(deg, samples):
    """Point at deg, wait for the head to stop, then take a median reading.

    Roughly one reading in ten times out on these modules, so a single sample
    is not trustworthy -- the median of three throws out both dropouts and the
    occasional wild reflection.
    """
    servo.angle(deg)
    time.sleep_ms(SETTLE_MS)

    reads = []
    for i in range(samples):
        cm = read_cm()
        if cm is not None:
            reads.append(cm)
        if i < samples - 1:
            time.sleep_ms(PING_GAP_MS)

    if not reads:
        return None
    reads.sort()
    return reads[len(reads) // 2]


def sweep(lo, hi, step, samples):
    """Scan lo..hi and return (angle, cm) of the closest hit, or (None, None)."""
    best_deg = None
    best_cm = None
    deg = lo
    while deg <= hi:
        cm = measure(deg, samples)
        if cm is not None and cm < DETECT_CM:
            if best_cm is None or cm < best_cm:
                best_deg = deg
                best_cm = cm
        deg += step
    return best_deg, best_cm


heading = 90
searching = True
lost = 0

try:
    # Inside the try, not before it. Anything that drives the servo ahead of
    # the try has no finally to undo it, so a Ctrl-C in that window leaves the
    # PWM slice enabled and the head holding -- indistinguishable from Ctrl-C
    # not working at all.
    servo.angle(heading)
    time.sleep_ms(400)
    print("scanning -- Ctrl-C to stop")

    while True:
        if searching:
            # Single sample per point: a full arc is 11 points, and spending
            # 3 pings on each makes the search sluggish. Fliers get corrected
            # by the fine sweep that follows.
            deg, cm = sweep(SCAN_MIN_DEG, SCAN_MAX_DEG, COARSE_STEP, 1)
            if deg is None:
                print("search: nothing inside %dcm" % DETECT_CM)
                continue
            heading, searching, lost = deg, False, 0
            print("found  %3d deg  %5.0f cm" % (heading, cm))
        else:
            lo = max(SCAN_MIN_DEG, heading - FINE_SPAN)
            hi = min(SCAN_MAX_DEG, heading + FINE_SPAN)
            deg, cm = sweep(lo, hi, FINE_STEP, 3)
            if deg is None:
                lost += 1
                print("lost   (%d/%d)" % (lost, LOST_LIMIT))
                if lost >= LOST_LIMIT:
                    searching = True
                    print("-> full sweep")
                continue
            heading, lost = deg, 0
            print("track  %3d deg  %5.0f cm" % (heading, cm))

        # Settle on the chosen heading so the movement reads as deliberate.
        servo.angle(heading)
        time.sleep_ms(SETTLE_MS)
except KeyboardInterrupt:
    print("\nCtrl-C -- stopping")
finally:
    # Runs on Ctrl-C too, so the head is never left straining. PWM is a
    # hardware peripheral and keeps pulsing on its own if this is skipped,
    # which looks exactly like the script refusing to stop. The retry guards
    # against a second Ctrl-C landing inside this block and killing the
    # cleanup before release() runs.
    for _ in range(3):
        try:
            servo.angle(90)
            time.sleep_ms(300)
            servo.release()
            break
        except KeyboardInterrupt:
            pass
    print("servo released -- head centred and limp")
