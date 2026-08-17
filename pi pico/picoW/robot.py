"""Mini robot -- looks around, greets what it finds, and follows it.

Board:  Raspberry Pi Pico W (RP2040, 2022).
Run:    uv run mpremote run "pi pico/picoW/robot.py"
Or via the Pi the Pico is plugged into (see README section 5):
        scp "pi pico/picoW/robot.py" my-pi:/tmp/ && ssh -t my-pi '~/.local/bin/mpremote run /tmp/robot.py'
Install so it runs on its own from a USB power bank, no laptop:
        uv run mpremote cp "pi pico/picoW/robot.py" :main.py
        uv run mpremote reset

WIRING -- full map. Per-part detail and debugging ladders live in the
individual test scripts; run those first if a part misbehaves.

    servo signal    ->  GP15                 physical pin 20   servo_test.py
    HC-SR04 TRIG    ->  GP2                  physical pin 4    ultrasonic_test.py
    HC-SR04 ECHO    ->  1k/2k divider -> GP3 physical pin 5    ultrasonic_test.py
    buzzer signal   ->  330R -> GP16         physical pin 21   buzzer_test.py
    LED strip DIN   ->  330R -> GP18         physical pin 24   led_test.py

    HC-SR04 V+      ->  VBUS                 physical pin 40   (5V)
    servo V+        ->  VBUS  -- read the power section below
    LED strip +5    ->  VBUS
    all GND         ->  GND rail -> GND      physical pin 38

    (a 3-pin buzzer module's middle pin goes to 3V3, physical pin 36)
    (the strip is one-way -- use the end marked DIN, never DO)

Everything must share a ground with the Pico or none of the signals have a
reference. The buzzer is happy on 3V3 or straight off the GPIO; the servo and
the HC-SR04 both genuinely need 5V.

POWER -- EVERYTHING SHARES VBUS, AND IT MEASURABLY FITS

On a Raspberry Pi 5 the USB port allows 600mA TOTAL for the whole board.
Measured draw:

    Pico W                      ~40mA
    HC-SR04                     ~15mA
    buzzer                       ~9mA   while sounding
    SG90 servo                 ~200mA   eased in 1 degree steps
                              700mA-1A  commanded to move flat out
    8 x WS2812B                  50mA   held there by the software limiter
                                488mA   if that limiter were removed

power_test.py escalates all four peripherals together -- including this file's
genuine worst case, the be_startled flinch -- and the kernel log comes back
empty. So this combination is verified rather than assumed.

WHAT MAKES IT FIT IS THE EASING, AND THAT IS NOT A COINCIDENCE

servo_test.py FAILS on this same rail. It commands whole-travel steps, so the
motor goes flat out, the port's limiter trips, and you get `over-current
change` then `USB disconnect` in the kernel log and a bare `OSError: [Errno 5]
Input/output error` on the host -- which looks nothing like a power fault.

This file never does that. Every move is eased in ~1 degree increments, so the
motor never reaches full speed and therefore never reaches full current. The
easing was added to stop a light base tipping over; it turns out to be
load-bearing for power as well. Do NOT replace glide() with _write().

If you add anything else to this rail, re-run power_test.py rather than
trusting the arithmetic above -- a 600mA limiter reacts to peaks, not averages.

If you ever do get a second 5V source (any USB phone charger plus a USB-A
breakout will do), give it to the servo and the strip, tie its ground to a Pico
GND, and leave VBUS out of it. Then STRIP_MA can go up and the servo stops
being the constraint. Grounds MUST stay common or no signal has a reference.

A two-pin passive buzzer has no polarity that matters -- a square wave
reversed is the same square wave. The 330R does matter though: this buzzer
measured ~42 ohms (buzzer_id.py), so it is a magnetic coil, and the resistor
is the only thing holding the pin to ~9mA against its 12mA rating.

That also caps the volume at roughly 3mW. For anything louder the coil has to
come off the GPIO and onto an NPN transistor -- circuit in buzzer_test.py.

SELF-CONTAINED ON PURPOSE. `mpremote run` does not upload imports, so a
script that imported a shared servo/sonar/buzzer module would only work after
copying those modules to the board first. Keeping one file means this runs the
moment you save it. The duplication is the price and it is worth it here.

BEHAVIOUR

    SEARCH  sweep the whole arc looking for anything within DETECT_CM.
            Nothing for a couple of passes -> a bored sigh, then PATROL.
    PATROL  a slow continuous glide across the room, pinging as it goes,
            breaking off the instant it hears something worth checking.
    GREET   fired once when a visitor first appears: turn to face them,
            waggle the head, and chirp a rising hello.
    TRACK   HOLD STILL and re-ping the current bearing. Only when the reading
            actually changes does it glance either side, and only if that
            fails does it look wider. Lose them for LOST_LIMIT tries -> sad
            note, back to SEARCH.

The greeting only fires on a NEW visitor. Standing still in front of it will
not set it off repeatedly -- it has to lose you first.

MOODS, roughly in order of how much you are bothering it:

    holding     watching something that is staying put -- silent, still  green
    curious     it moved; a short rising blip                            green
    wary        it is closing in; two hesitant rising notes              amber
    shy         inside CLOSE_CM; squeaks and leans away                  amber
    startled    something is in its FACE; bolts sideways and squeals     red
    annoyed     still there after being told twice; grumbles, shakes     red
    sulky       still there after six; turns away, light drains, ignores blue
    sad         lost them                                                blue
    bored       nothing around at all                                    white

Backing off resets the escalation -- one clean reading clears `blocked`.

LIGHTS

The 8-pixel strip is a second channel of expression, and also a readout. While
scanning or patrolling, strip.head() lights the pixel matching the servo's
bearing with its neighbours dimmer, so you can see where the robot is looking
without watching the head. Amber while searching, green once it has something.

Colour is chosen by mood, not by state machine: each mood function sets the
strip on entry and leaves it in the correct resting colour on exit, exactly as
each one already leaves the head on target. Nothing in the main loop paints.

Every frame goes through a CURRENT LIMITER (see Strip). It estimates a frame's
draw before sending it and scales the whole frame down if it would exceed
STRIP_MA, which is what lets the strip share VBUS with the servo. Scaling the
whole frame rather than each pixel preserves relative brightness, so hues and
gradients survive -- they just get dimmer.

Animations are only used where a pause already existed to spend. be_sulky's
drain consumes the sulk instead of adding to it, and be_bored's breathe
replaces its trailing pause. Inside tight sequences -- the startle, the
grumble, the greeting waggle -- the strip is only ever set instantly, because
a frame costs ~0.3ms and must not disturb the servo's 20ms frame or the
sensor's echo timing.

MOVEMENT. Every move is eased, not commanded as a step. A servo has no speed
input, so a single big write makes it slam across and ring on arrival; glide()
walks the angle over in ~1 degree increments on a smoothstep curve instead.
Arriving gently also means it settles faster, which is why SETTLE_MS is 80
rather than the 150 a stepped move needed.

WHAT THIS CANNOT DO -- worth knowing before blaming the code:

  * The HC-SR04 reports distance only, never direction. Everything in its
    ~15 degree cone reads the same. The bearing comes from the servo's own
    position, so the head has to sweep to find anything. That makes tracking
    inherently laggy -- about 1.5s per update -- and no amount of code fixes
    it with one fixed sensor.
  * It follows the NEAREST thing, not a particular thing. Put a closer object
    in front of it and it switches allegiance. There is no object identity.
  * Below ~15cm the sensor is deaf -- it is still ringing from its own ping
    when the echo gets back, so it reports whatever is BEHIND your hand
    instead. A hand at 5cm reading 200cm is physics, not a bug.
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

SERVO_PIN = 15
TRIG_PIN = 2
ECHO_PIN = 3
BUZZER_PIN = 16
LED_PIN = 18

# --- servo -----------------------------------------------------------------
SERVO_FREQ = 50
PERIOD_US = 1_000_000 // SERVO_FREQ
SERVO_MIN_US = 500
SERVO_MAX_US = 2500

# --- scanning --------------------------------------------------------------
# Stay off the mechanical stops. An SG90 straining against its own end stop
# will cook its gears.
SCAN_MIN_DEG = 15
SCAN_MAX_DEG = 165
CENTRE_DEG = 90

COARSE_STEP = 15   # matched to the beam width; finer buys time, not accuracy
FINE_STEP = 10

# Tracking sweeps ADAPTIVELY, widening only when it has a reason to.
#
# The first version swept a fixed +/-20 degrees every cycle whether or not
# anything had changed, so standing still in front of it still produced a
# head swinging 40 degrees back and forth forever. Re-measuring was the only
# way it knew you were still there.
#
# Now the normal case moves nothing at all -- it just re-pings down the
# current bearing -- and only escalates through these spans when the reading
# actually shifts. A stationary visitor gets a stationary head.
NUDGE_SPAN = 10      # reading changed: glance either side
WIDE_SPAN = 25       # still nothing: look properly before admitting defeat

# How much the distance may drift while still counting as "same thing, still
# there". Too tight and it twitches at sensor noise; too loose and it keeps
# staring at where you used to be.
HOLD_TOLERANCE_CM = 5

# Ignore bearing corrections smaller than this. Without a deadband the head
# chases +/-1 degree of measurement noise forever, which reads as nervous.
HEADING_DEADBAND = 10

SETTLE_MS = 80     # vibration die-down AFTER the move; the glide handles travel
PING_GAP_MS = 70   # sensor needs >=60ms of quiet between pings

# Servo travel speed for gliding, degrees per second. An SG90 free-runs at
# roughly 600; well under that keeps it smooth and quiet. Raise for a
# friskier robot, lower for a stately one.
GLIDE_DEG_PER_S = 110
WIGGLE_DEG_PER_S = 180   # the hello waggle wants to be perky, not stately
FLINCH_DEG_PER_S = 210   # a startle: the quickest move it makes, but not a jolt
SHAKE_DEG_PER_S = 170    # the annoyed head-shake
SULK_DEG_PER_S = 30      # turning away in a huff is slow and pointed

# WHY THESE ARE ALL FAIRLY LOW
#
# What tips a light base is not speed, it is ANGULAR ACCELERATION -- the head
# accelerating one way pushes the base the other, and a servo has plenty of
# torque to shove its own stand around. With the smoothstep easing in glide(),
# peak acceleration over a swing goes as (deg_per_s ** 2) / degrees.
#
# So the two knobs pull in opposite directions: halving a speed quarters the
# kick, but shrinking a swing while keeping the speed makes it WORSE, because
# the same speed has to be reached and shed in less travel. Tune speed first,
# and only shorten a movement once its speed is already gentle.
#
# These are roughly a third of the earlier values in acceleration terms. If it
# still walks across the desk, drop the speeds again before the amplitudes --
# and weigh the base down, which fixes it properly rather than hiding it.

# 60cm, not the 100cm the bare tracker used. Anything further away is mostly
# walls and furniture, and a robot that solemnly tracks a bookshelf is less
# charming than one that waits for a person.
DETECT_CM = 60
CLOSE_CM = 25      # inside this it acts shy
LOST_LIMIT = 3     # empty fine sweeps before giving up and searching again
BORED_SWEEPS = 2   # empty full sweeps before it sighs and goes on patrol

# Getting crowded. VERY_CLOSE_CM sits just above the sensor's blind zone,
# because anything nearer than that cannot be measured at all -- see
# too_close() for how the blind zone is detected rather than measured.
VERY_CLOSE_CM = 5
# Closing by more than this between reads counts as approaching. MUST stay
# below HOLD_TOLERANCE_CM: "wary" is checked inside the settled branch, so a
# value at or above the tolerance makes it unreachable -- any gap big enough
# to be an approach would already have failed the settled test and gone off
# to re-sweep instead.
APPROACH_CM = 3

ANNOY_LIMIT = 3    # crowded this many cycles running -> stops being startled
SULK_LIMIT = 6     # and this many -> gives up on you entirely

# --- patrol ----------------------------------------------------------------
# The slow idle sweep. Deliberately far below scanning speed: this one is for
# looking alive, not for measuring.
PATROL_DEG_PER_S = 25
PATROL_PING_MS = 80   # >=60ms of quiet between pings still applies while moving

# --- sensor ----------------------------------------------------------------
CM_PER_US = 0.0343
TIMEOUT_US = 30_000

# --- lights ----------------------------------------------------------------
PIXELS = 8

# The strip's share of the 600mA USB budget. Lower than the 80mA that
# led_test.py proved safe, because that figure was measured with the strip
# ALONE and the servo needs its glide current back. 50mA is what power_test.py
# verified with everything running at once.
#
# This is the single knob for strip brightness. Raise it in ~20mA steps and
# re-run power_test.py with the kernel log each time -- do not just turn it up
# and hope, because the failure mode is the Pico dropping off USB mid-move.
STRIP_MA = 50

# A WS2812B is three ~20mA LEDs plus a controller that draws ~1mA even dark.
# Datasheets say 20mA/channel and real parts come in slightly under, so this
# errs high, which is the safe direction for a budget.
MA_PER_CHANNEL = 20
QUIESCENT_MA = 1

OFF = (0, 0, 0)
AMBER = (255, 120, 0)     # looking, wary, shy -- attention without alarm
GREEN = (0, 255, 60)      # found you, holding, curious
RED = (255, 0, 0)         # startled, annoyed
BLUE = (0, 60, 255)       # sulking, sad
WHITE = (255, 255, 255)   # waking, bored


def dim(colour, f):
    """Scale a colour by f.

    Used to pick resting levels comfortably under the current ceiling. That
    matters: a colour that would trip the limiter comes out scaled by the
    limiter instead, and while that preserves hue it makes the brightness of a
    resting state depend on STRIP_MA rather than on intent.
    """
    return (int(colour[0] * f), int(colour[1] * f), int(colour[2] * f))


# What the strip settles to between events. Deliberately dim: these are on
# almost all the time, so they set the robot's idle draw and its idle mood.
RESTING_SEARCH = dim(AMBER, 0.35)
RESTING_HOLD = dim(GREEN, 0.3)

# --- personality -----------------------------------------------------------
# duty_u16. 32768 is a 50% square wave, which is as loud as a passive buzzer
# goes -- going higher narrows the pulse again and gets QUIETER. Drop this if
# you want it gentler; there is no way to make it louder from here.
VOLUME = 32768

# Measured with buzzer_tune.py: this buzzer's resonant peak. A buzzer is a
# mechanical resonator, not a speaker -- off the peak it is dramatically
# quieter whatever the duty cycle. The first version of these tunes sat
# around 500-1300Hz, an octave and a half below, and no amount of volume
# fiddling helped. Re-measure if you swap the buzzer; 2048, 2700 and 4000 are
# all common.
PEAK_HZ = 4000


def pitch(ratio):
    """A frequency expressed as a ratio of the resonant peak.

    Keeping the tunes relative means changing PEAK_HZ retunes everything at
    once and preserves the intervals, instead of scattering magic numbers
    that only suit one buzzer. Handy ratios: 0.667 = a fifth below,
    0.833 = a third below, 1.5 = a fifth above, 2.0 = an octave above.
    """
    return int(PEAK_HZ * ratio)


WIGGLE_DEG = 14    # how far the head swings either side when saying hello
WIGGLE_MS = 160    # longer pause between swings, so it reads as a nod not a jitter
SHY_DEG = 18       # how far it leans away when you crowd it
FLINCH_DEG = 26    # how far it bolts when something appears in its face
SHAKE_DEG = 9      # amplitude of the annoyed head-shake
SULK_MS = 4000     # how long it refuses to look at you


class Servo:
    """A servo that moves smoothly instead of teleporting.

    A hobby servo has no speed input -- you give it a target and it slams
    there at whatever rate it can manage, then rings on arrival. Writing one
    big step change is what makes cheap servos look twitchy and mechanical.

    glide() fixes that in software by walking the target across in ~1 degree
    increments, shaped by an ease-in-out curve so it accelerates away and
    decelerates into the destination rather than starting and stopping dead.
    That also means it arrives gently, so it rings far less -- which is why
    SETTLE_MS could come down from 150 to 80.
    """

    def __init__(self, pin):
        self.pwm = machine.PWM(machine.Pin(pin))
        self.pwm.freq(SERVO_FREQ)
        # Where we believe the head is. At power-up this is a guess: a servo
        # gives no position feedback, so nothing can know its real angle
        # until it has been commanded once. The first move is therefore
        # always a jump, no matter what. wake() gets it over with.
        self.current = CENTRE_DEG

    def _write(self, deg):
        deg = max(SCAN_MIN_DEG, min(SCAN_MAX_DEG, deg))
        us = SERVO_MIN_US + (SERVO_MAX_US - SERVO_MIN_US) * deg / 180
        self.pwm.duty_u16(int(us * 65535 / PERIOD_US))
        self.current = deg

    def snap(self, deg):
        """Move immediately. Only for the first command, when the real
        position is unknown and interpolating from a guess is meaningless."""
        self._write(deg)

    def glide(self, deg, deg_per_s=GLIDE_DEG_PER_S, watch=None):
        """Ease from the current angle to deg. Blocks for the duration.

        watch, if given, is called after every step. Return anything other
        than None from it and the glide stops dead where it is and hands that
        value back -- which is how the patrol sweep can break off mid-stride
        the moment it hears something, instead of dutifully finishing the
        sweep first.
        """
        start = self.current
        delta = deg - start
        if abs(delta) < 0.5:
            return None   # already there -- crucially, this means NO movement

        steps = max(2, int(abs(delta)))          # about one step per degree
        step_ms = max(1, int(abs(delta) * 1000 / deg_per_s) // steps)
        for i in range(1, steps + 1):
            t = i / steps
            # Smoothstep, 3t^2 - 2t^3: zero slope at both ends, so it eases
            # out of the start and into the finish. A plain linear ramp is
            # smoother than a step but still starts and stops abruptly.
            self._write(start + delta * t * t * (3 - 2 * t))
            time.sleep_ms(step_ms)
            if watch is not None:
                found = watch()
                if found is not None:
                    return found
        return None

    def release(self):
        self.pwm.deinit()


class Buzzer:
    def __init__(self, pin):
        self.pwm = machine.PWM(machine.Pin(pin))
        self.pwm.duty_u16(0)

    def start(self, hz):
        """Start a tone and return immediately -- PWM keeps sounding it in
        hardware, which is how the head can waggle mid-chirp with no
        threading anywhere."""
        self.pwm.freq(hz)
        self.pwm.duty_u16(VOLUME)

    def stop(self):
        self.pwm.duty_u16(0)

    def tone(self, hz, ms):
        self.start(hz)
        time.sleep_ms(ms)
        self.stop()

    def play(self, notes):
        for hz, ms in notes:
            self.tone(hz, ms)
            time.sleep_ms(25)

    def slide(self, start_hz, end_hz, ms, steps=20):
        """Glide between pitches. Discrete notes sound like a doorbell; a
        slide sounds like a droid. This is most of the cuteness."""
        step_ms = max(1, ms // steps)
        for i in range(steps + 1):
            self.start(start_hz + (end_hz - start_hz) * i // steps)
            time.sleep_ms(step_ms)
        self.stop()

    def release(self):
        self.pwm.deinit()


class Strip:
    """8 addressable pixels with a hard current ceiling.

    The limiter is the only reason this can share VBUS with a servo. Every
    frame's draw is estimated BEFORE it is sent -- three ~20mA channels plus
    ~1mA of controller per pixel -- and the whole frame is scaled down if it
    would exceed STRIP_MA. Verified against hand arithmetic in led_test.py:
    eight pixels of full white asks for 488mA and arrives as 15% of requested.

    Scaling the frame as a whole rather than pixel by pixel is deliberate. It
    preserves the ratios between pixels and between channels, so a gradient
    stays a gradient and a hue stays that hue -- it simply gets dimmer. A
    per-pixel clamp would distort both.

    Note there is NO WAY TO DETECT the strip. WS2812B is write-only with no
    return path, so NeoPixel() succeeds whether or not anything is plugged in
    and a missing strip is indistinguishable from a working one in software.
    Nothing here can warn you; use led_test.py.
    """

    def __init__(self, pin, n):
        self.np = neopixel.NeoPixel(machine.Pin(pin), n)
        self.n = n

    def estimate_ma(self, frame):
        channels = sum(sum(px) for px in frame)
        return self.n * QUIESCENT_MA + channels * MA_PER_CHANNEL / 255

    def show(self, frame):
        # Only the controllable part is scaled -- quiescent draw cannot be
        # reduced by dimming, so including it in the ratio would over-scale.
        budget = STRIP_MA - self.n * QUIESCENT_MA
        wanted = self.estimate_ma(frame) - self.n * QUIESCENT_MA
        scale = budget / wanted if wanted > budget and wanted > 0 else 1.0
        for i, px in enumerate(frame):
            self.np[i] = (int(px[0] * scale),
                          int(px[1] * scale),
                          int(px[2] * scale))
        self.np.write()

    def fill(self, colour):
        self.show([colour] * self.n)

    def clear(self):
        self.fill(OFF)

    def bar(self, colour, lit):
        """The first `lit` pixels on. A level readout."""
        self.show([colour if i < lit else OFF for i in range(self.n)])

    def head(self, deg, colour):
        """Light the pixel matching a head bearing, with neighbours dimmer.

        Turns the strip into a position indicator -- you can see where the
        robot is looking without watching the servo. One frame costs ~0.3ms,
        far too short to disturb the servo's 20ms frame or time_pulse_us, so
        this drops into scanning and patrol without a timing cost.
        """
        span = SCAN_MAX_DEG - SCAN_MIN_DEG
        pos = int((deg - SCAN_MIN_DEG) * (self.n - 1) / span)
        pos = max(0, min(self.n - 1, pos))
        frame = []
        for i in range(self.n):
            gap = abs(i - pos)
            frame.append(colour if gap == 0 else
                         dim(colour, 0.25) if gap == 1 else OFF)
        self.show(frame)

    def wipe(self, colour, ms):
        """Fill one pixel at a time. BLOCKING -- only for moments that already
        have a pause to spend, never inside a timed sequence."""
        step = max(1, ms // self.n)
        for lit in range(1, self.n + 1):
            self.bar(colour, lit)
            time.sleep_ms(step)

    def drain(self, colour, ms):
        """Lose one pixel at a time until dark, over ms.

        The sulk. The light going out slowly IS the sulk, so this consumes the
        sulk duration rather than adding to it -- it replaces the pause that
        used to sit there doing nothing.
        """
        step = max(1, ms // (self.n + 1))
        for lit in range(self.n, -1, -1):
            self.bar(colour, lit)
            time.sleep_ms(step)

    def breathe(self, colour, ms, cycles=1):
        """Slow fade up and down -- the bored sigh, made visible."""
        steps = 12
        step = max(1, ms // (cycles * steps * 2))
        for _ in range(cycles):
            for i in list(range(steps + 1)) + list(range(steps - 1, -1, -1)):
                self.fill(dim(colour, i / steps))
                time.sleep_ms(step)


led = machine.Pin("LED", machine.Pin.OUT)
led.value(1)          # lit means powered and running -- the liveness check

servo = Servo(SERVO_PIN)
buzzer = Buzzer(BUZZER_PIN)
strip = Strip(LED_PIN, PIXELS)
trig = machine.Pin(TRIG_PIN, machine.Pin.OUT)
echo = machine.Pin(ECHO_PIN, machine.Pin.IN)

# What colour the head-position indicator uses. Amber while hunting, green once
# it has something. In a list so measure() and the patrol watch can both read
# the current value without a global statement -- same idiom as _last_ping_ms.
look_colour = [AMBER]


# --- sensing ---------------------------------------------------------------

def read_cm():
    """One measurement. Returns cm, or None if the ping never came back."""
    trig.value(0)
    time.sleep_us(2)
    trig.value(1)
    time.sleep_us(10)   # HC-SR04 wants a 10us trigger pulse
    trig.value(0)
    us = machine.time_pulse_us(echo, 1, TIMEOUT_US)
    if us < 0:
        return None
    return (us * CM_PER_US) / 2


def measure(deg, samples):
    """Point at deg, wait for the head to stop moving, then take a median.

    Sampling has to wait for the servo. A moving servo both drags VBUS down
    and physically shakes the sensor, and roughly one reading in ten times
    out anyway -- the median of several throws out dropouts and the odd wild
    reflection without chasing them in code.
    """
    servo.glide(deg)
    strip.head(deg, look_colour[0])   # ~0.3ms; shows where it is pointing
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


# --- personality -----------------------------------------------------------

def greet(deg):
    """Turn to face a new visitor, waggle hello, and chirp on the way.

    The tone is started before each move and left running across it. Both the
    servo and the buzzer are hardware PWM, so they run genuinely at the same
    time -- the head is not pausing to sing.

    A rising major triad landing on the resonant peak. Rising into resonance
    means it also gets louder as it goes, which is most of why this reads as
    cheerful rather than as four beeps.
    """
    servo.glide(deg)
    strip.wipe(GREEN, 200)    # spends the pause that used to be sleep_ms(300)
    time.sleep_ms(100)

    notes = ((WIGGLE_DEG, 0.667),       # root
             (-WIGGLE_DEG, 0.833),      # third
             (WIGGLE_DEG // 2, 1.0),    # fifth, on the peak
             (0, 1.125))                # a step above
    for i, (offset, ratio) in enumerate(notes):
        buzzer.start(pitch(ratio))
        # A bar rising under the rising triad. Set instantly, so the note, the
        # movement and the light all begin together.
        strip.bar(GREEN, (i + 1) * PIXELS // len(notes))
        servo.glide(deg + offset, WIGGLE_DEG_PER_S)
        led.toggle()
        time.sleep_ms(WIGGLE_MS)

    buzzer.stop()
    led.value(1)
    buzzer.slide(pitch(1.125), pitch(1.33), 140)   # a little flourish on the end
    strip.fill(RESTING_HOLD)


def be_shy(deg):
    """Crowded. Lean away, squeak, then peek back.

    The light shrinks back as the head does and returns as it peeks, so the
    lean reads as flinching rather than as merely turning.
    """
    strip.fill(AMBER)
    buzzer.slide(pitch(1.0), pitch(1.3), 100)
    away = deg + SHY_DEG if deg < CENTRE_DEG else deg - SHY_DEG
    strip.fill(dim(AMBER, 0.25))
    servo.glide(away, WIGGLE_DEG_PER_S)
    time.sleep_ms(250)
    buzzer.slide(pitch(1.3), pitch(1.0), 100)
    strip.fill(AMBER)
    servo.glide(deg)
    time.sleep_ms(200)
    strip.fill(RESTING_HOLD)


def be_curious():
    """Small interested blip when the target has shifted. Rises through the
    peak, so it is short but cuts through."""
    strip.fill(GREEN)
    buzzer.slide(pitch(0.8), pitch(1.1), 90)
    strip.fill(RESTING_HOLD)


def be_wary():
    """You are closing in. Two hesitant rising notes -- not alarmed yet.

    The strip brightens with each note and falls back between them, which is
    what makes two notes read as hesitation rather than as a two-note tune.
    """
    strip.fill(AMBER)
    buzzer.tone(pitch(0.7), 70)
    strip.fill(dim(AMBER, 0.2))
    time.sleep_ms(60)
    strip.fill(AMBER)
    buzzer.tone(pitch(0.85), 70)
    strip.fill(RESTING_HOLD)


def be_startled(deg):
    """Something appeared right in its face. Duck away and squeal.

    This is the quickest move the robot makes, but it is nowhere near the
    servo's limit -- flat out, the reaction torque shoves a light base around
    and the whole robot hops. The startle is carried by the SOUND instead:
    the squeal starts before the head moves and chirps through it, which
    reads as alarm without needing a violent movement to sell it.
    """
    away = deg + FLINCH_DEG if deg < CENTRE_DEG else deg - FLINCH_DEG
    # Red lands before the movement, same as the squeal. Set instantly -- this
    # is the tightest sequence in the file and must not gain any latency.
    strip.fill(RED)
    buzzer.start(pitch(1.45))
    servo.glide(away, FLINCH_DEG_PER_S)
    for i in range(3):
        buzzer.start(pitch(1.5 if i % 2 == 0 else 1.15))
        strip.fill(RED if i % 2 == 0 else OFF)   # hard blink, on the chirps
        time.sleep_ms(55)
    buzzer.stop()
    strip.fill(RED)
    time.sleep_ms(250)
    servo.glide(deg)
    strip.fill(RESTING_HOLD)


def be_annoyed(deg):
    """Still there after being told twice. Grumble and shake its head.

    The grumble alternates two pitches either SIDE of resonance rather than
    dropping to a genuinely low note. A low growl would be the obvious
    choice, but low notes on this buzzer are close to inaudible -- so a fast
    wobble across the peak is what a growl has to be here. Physics picking
    the sound design.
    """
    for i in range(6):
        buzzer.start(pitch(1.05 if i % 2 else 0.95))
        strip.fill(RED if i % 2 else dim(RED, 0.15))   # grumbles in light too
        servo.glide(deg + (SHAKE_DEG if i % 2 else -SHAKE_DEG), SHAKE_DEG_PER_S)
        time.sleep_ms(45)
    buzzer.stop()
    servo.glide(deg)
    strip.fill(RESTING_HOLD)


def be_sulky(deg):
    """Given up on you. Turn pointedly away, go dark, and ignore the room.

    drain() replaces the bare SULK_MS pause rather than adding to it, so the
    sulk lasts exactly as long as it always did -- the light now goes out over
    the course of it, one pixel at a time, which is the whole mood in one
    gesture.
    """
    buzzer.slide(pitch(1.0), pitch(0.5), 500)
    away = SCAN_MIN_DEG if deg > CENTRE_DEG else SCAN_MAX_DEG
    strip.fill(dim(BLUE, 0.5))
    servo.glide(away, SULK_DEG_PER_S)
    led.value(0)
    strip.drain(BLUE, SULK_MS)
    led.value(1)
    strip.fill(RESTING_SEARCH)


def be_sad():
    """Lost them. Falling away from resonance fades it out on its own, which
    is exactly the shape a disappointed noise wants."""
    strip.fill(dim(BLUE, 0.6))
    buzzer.play(((pitch(1.0), 130), (pitch(0.667), 260)))
    strip.fill(RESTING_SEARCH)


def be_bored():
    """Nothing around for a while. Sigh, and have a look at the ceiling.

    breathe() spends the trailing 500ms that was already a plain pause, so the
    sigh costs no extra time -- it just stops being invisible.
    """
    strip.fill(dim(WHITE, 0.3))
    buzzer.slide(pitch(1.0), pitch(0.55), 350)
    servo.glide(CENTRE_DEG)
    strip.breathe(WHITE, 500)
    strip.fill(RESTING_SEARCH)


def wake():
    """Startup: centre the head and announce itself. Starts well below
    resonance and climbs onto it, so it swells as it rises -- a power-up."""
    servo.snap(CENTRE_DEG)
    strip.wipe(dim(WHITE, 0.6), 240)   # fills from one end, like booting up
    time.sleep_ms(200)
    buzzer.slide(pitch(0.4), pitch(1.0), 260)
    buzzer.tone(pitch(1.125), 90)
    strip.fill(RESTING_SEARCH)


# --- patrol ----------------------------------------------------------------

# Timestamp of the last patrol ping, in a list so the watch closure can write
# to it. The sensor's >=60ms quiet rule does not stop applying just because
# the head is moving.
_last_ping_ms = [0]


def _patrol_watch():
    """Called between glide steps. Returns (deg, cm) on a hint, else None."""
    # Track the head on the strip every step, not just on ping cycles -- the
    # point of the patrol is looking alive, and a smoothly travelling light is
    # most of that. ~150 steps across an arc at ~0.3ms each is ~45ms total.
    strip.head(servo.current, look_colour[0])

    now = time.ticks_ms()
    if time.ticks_diff(now, _last_ping_ms[0]) < PATROL_PING_MS:
        return None
    _last_ping_ms[0] = now
    cm = read_cm()
    if cm is not None and cm < DETECT_CM:
        return (servo.current, cm)
    return None


def patrol():
    """A slow, smooth sweep of the room. Returns (deg, cm) or (None, None).

    This is the one behaviour where the head moves for its own sake, so it
    glides continuously instead of stepping and pausing. Smoothstep easing
    over the full arc means it drifts out of the end stops, builds speed
    across the middle and settles at the far side, which is most of what
    makes it read as looking around rather than executing a scan.

    Pings taken while moving are NOT trustworthy -- the servo shakes the
    sensor and drags on VBUS, which is the whole reason normal scanning stops
    before sampling. So a hit here is only a hint. It breaks off, stands
    still, and measures properly before believing it.
    """
    print("patrol")
    for target in (SCAN_MIN_DEG, SCAN_MAX_DEG, CENTRE_DEG):
        hint = servo.glide(target, PATROL_DEG_PER_S, watch=_patrol_watch)
        if hint is None:
            continue
        deg = hint[0]
        cm = measure(deg, 3)     # stopped now, so this one counts
        if cm is not None and cm < DETECT_CM:
            return deg, cm
        # False alarm from a moving reading. Carry on from where it stopped.
    return None, None


def too_close(cm, last_cm, blocked):
    """Is something right in the sensor's face?

    This cannot be measured, only inferred, and that is worth understanding
    before trying to "fix" it. Below about 15cm the HC-SR04 is deaf: it is
    still ringing from its own 40kHz burst when the echo gets back. A hand at
    3cm therefore does NOT read as 3cm. Usually it reads as whatever is
    BEHIND the hand -- the far wall -- and sometimes as nothing at all.

    So the signature of being crowded is not a small number. It is a small
    number that suddenly becomes a large one:

      1. cm under VERY_CLOSE_CM -- the last band it can still genuinely see.
      2. something was inside CLOSE_CM and the very next read jumped to the
         background or vanished. It did not cross the room in 300ms; it
         moved into the blind zone.
      3. already blocked and still reading nothing useful -- stay blocked,
         so the escalation can actually build.

    Rule 3 exists because clearing the history after a blind-zone hit made it
    impossible to ever reach the second one: every push registered as a fresh
    surprise, then as a lost target.

    HONEST LIMITATION: rule 2 cannot distinguish "hand pressed against the
    sensor" from "person walked out of range". To this sensor those are the
    same event. That is why the escalation is bounded -- six cycles ends in a
    sulk and a return to SEARCH, which recovers on its own either way.
    """
    if cm is not None and cm < VERY_CLOSE_CM:
        return True

    # "Background" means beyond the detection range entirely -- the far wall,
    # or silence. Deliberately absolute rather than relative to the last
    # reading: a relative test like "more than double" flags someone at 20cm
    # stepping back to 45cm, which is an ordinary retreat and still perfectly
    # visible. Only a jump clean out of range means the near object stopped
    # being seen at all.
    background = cm is None or cm > DETECT_CM

    if last_cm is not None and last_cm < CLOSE_CM and background:
        return True
    return blocked > 0 and background


# --- main loop -------------------------------------------------------------

heading = CENTRE_DEG
searching = True
lost = 0
empty_sweeps = 0
last_cm = None
blocked = 0        # consecutive cycles with something in its face

try:
    # wake() MUST be inside the try. It drives the servo and takes the best
    # part of a second, and anything that moves hardware before the try has
    # no finally to undo it -- a Ctrl-C landing in that window leaves the PWM
    # slice enabled and the head stiffly holding, which looks exactly like
    # Ctrl-C being ignored. That is precisely the moment you press it if you
    # start the robot and immediately change your mind.
    wake()
    print("awake -- Ctrl-C to stop")

    while True:
        if searching:
            # Amber while hunting. Set here rather than once on entry because
            # the searching branch is also re-entered after a sulk or a lost
            # target, and this is the one place all those paths pass through.
            look_colour[0] = AMBER

            # One sample per point: a full arc is 11 points and 3 pings each
            # makes the search sluggish. Fliers get corrected by the fine
            # sweep that follows a hit.
            deg, cm = sweep(SCAN_MIN_DEG, SCAN_MAX_DEG, COARSE_STEP, 1)

            if deg is None:
                empty_sweeps += 1
                print("search: nothing inside %dcm" % DETECT_CM)
                if empty_sweeps >= BORED_SWEEPS:
                    # Sigh, then go for a slow look around. The patrol both
                    # keeps it alive to watch and covers the arc again, so a
                    # quiet room does not mean a motionless robot.
                    empty_sweeps = 0
                    print("bored")
                    be_bored()
                    deg, cm = patrol()
                if deg is None:
                    continue

            heading, last_cm = deg, cm
            searching, lost, empty_sweeps = False, 0, 0
            blocked = 0
            look_colour[0] = GREEN   # it has something now
            print("hello!  %3d deg  %5.0f cm" % (heading, cm))
            greet(heading)
            continue   # greet already left the head on target

        # TRACKING. Cheapest check first: re-ping straight down the current
        # bearing without moving at all. If you are still standing where you
        # were, this is the whole cycle -- the head does not twitch.
        cm = measure(heading, 3)

        # Crowded? Escalate the further you push it: flinch, then grumble,
        # then give up on you altogether. Resetting `blocked` only on a clean
        # reading means backing off calms it down.
        if too_close(cm, last_cm, blocked):
            blocked += 1
            lost = 0
            print("too close! (%d)" % blocked)
            if blocked >= SULK_LIMIT:
                print("sulking")
                be_sulky(heading)
                searching, blocked, last_cm = True, 0, None
            elif blocked >= ANNOY_LIMIT:
                be_annoyed(heading)
            else:
                be_startled(heading)
            # last_cm is deliberately NOT cleared. It is the evidence that
            # something was close, and too_close() needs it next time round
            # to tell a blind-zone reading from a genuine long one.
            continue

        blocked = 0
        settled = (cm is not None and cm < DETECT_CM and
                   (last_cm is None or abs(cm - last_cm) <= HOLD_TOLERANCE_CM))

        if settled:
            lost = 0
            if last_cm is not None and cm < last_cm - APPROACH_CM:
                print("wary   %3d deg  %5.0f cm" % (heading, cm))
                be_wary()
            elif cm < CLOSE_CM:
                print("shy    %3d deg  %5.0f cm" % (heading, cm))
                be_shy(heading)
            else:
                # Silent. Sitting in front of it is the most common state by
                # far, and anything that chirps on a timer while nothing is
                # happening stops reading as personality and starts reading
                # as a smoke alarm. It reacts to CHANGE, not to duration.
                print("hold   %3d deg  %5.0f cm" % (heading, cm))
            last_cm = cm
            continue

        # Something changed -- either you moved or the echo dropped out.
        # Escalate: a glance either side, and only then a proper look. Trying
        # the narrow span first means small movements cost one short sweep
        # instead of a full wide one.
        deg = None
        for span in (NUDGE_SPAN, WIDE_SPAN):
            lo = max(SCAN_MIN_DEG, heading - span)
            hi = min(SCAN_MAX_DEG, heading + span)
            deg, cm = sweep(lo, hi, FINE_STEP, 2)
            if deg is not None:
                break

        if deg is None:
            lost += 1
            print("lost   (%d/%d)" % (lost, LOST_LIMIT))
            if lost >= LOST_LIMIT:
                searching, last_cm = True, None
                print("-> full sweep")
                be_sad()
            continue

        lost = 0
        moved = abs(deg - heading)

        # Deadband. Without it the head chases a degree of measurement noise
        # back and forth forever and never looks settled.
        if moved >= HEADING_DEADBAND:
            heading = deg
            print("track  %3d deg  %5.0f cm" % (heading, cm))
            be_curious()
            servo.glide(heading)
            time.sleep_ms(SETTLE_MS)
        else:
            print("steady %3d deg  %5.0f cm" % (heading, cm))

        if cm < CLOSE_CM:
            be_shy(heading)

        last_cm = cm
except KeyboardInterrupt:
    print("\nCtrl-C -- stopping")
finally:
    # Both PWMs are hardware peripherals and keep running on their own if this
    # is skipped -- a droning buzzer and a twitching head that Ctrl-C appears
    # not to touch. This block is the only thing that stops them.
    #
    # Park centred before going limp. A servo has no holding torque without a
    # signal and does not self-centre, so releasing it mid-sweep abandons the
    # head at whatever odd angle it had reached.
    #
    # The retry matters: a SECOND Ctrl-C -- very tempting when the first looks
    # like it did nothing -- lands inside this block and can kill the cleanup
    # before release() runs, which is the very failure it is here to prevent.
    for _ in range(3):
        try:
            servo.glide(CENTRE_DEG)
            time.sleep_ms(300)
            buzzer.release()
            servo.release()
            # The strip is not a peripheral that keeps running -- each pixel
            # latches its last frame and holds it indefinitely with no further
            # input. So an uncleared strip stays lit forever after exit, which
            # looks even more like Ctrl-C was ignored than a droning buzzer.
            strip.clear()
            led.value(0)
            break
        except KeyboardInterrupt:
            pass
    print("released -- head centred and limp, buzzer quiet, pixels off")
