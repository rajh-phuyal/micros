"""Continuity tester -- identify an unmarked pin when there is no multimeter.

Board:  Raspberry Pi Pico W (RP2040, 2022).
Run:    uv run mpremote run "pi pico/picoW/continuity_test.py"
Or through the Pi the Pico is plugged into (README section 5):
        scp "pi pico/picoW/continuity_test.py" my-pi:/tmp/ && ssh -t my-pi '~/.local/bin/mpremote run /tmp/continuity_test.py'

Written because the PIR module in this project has no silkscreen at all, so its
three pins cannot be read -- and getting VCC and GND the wrong way round
destroys the module. Guessing is not an option and there is no meter, so the
Pico becomes the meter.

HOW IT WORKS

A GPIO configured as an input with the internal pull-up sits at 3.3V through
roughly 55k. Touch that pin to something connected to the Pico's own GND and
the pull-up loses -- the pin reads 0. Touch it to anything else and it stays 1.
That is a continuity test, and 55k is weak enough that ~60uA flows, which
harms nothing.

THE THING BEING TESTED MUST HAVE NO POWER GOING TO IT

The Pico is powered -- it is running this. The module being probed must not be.
Nothing plugged into it at all: no 5V, no ground, no signal wire. It lies loose
on the bench and the only two wires touching it are these two probes.

Two reasons, and the second one is the expensive one. A powered module pushes
its own voltage back down the probe, which makes the reading meaningless. And
the probe wire runs to GP14, so touching it against a live 5V pin puts 5V
straight onto a 3.3V input.

WIRING

Two jumper wires into the Pico and nothing else:

    wire A  ->  Pico GND  (pin 38)
    wire B  ->  Pico GP14 (pin 19)

Their free ends are the two probe tips. Touch both tips to two points, and the
script says whether those two points are joined. It does not matter which tip
goes where -- a connection is a connection in either direction.

USE THE SELF-TEST FIRST

Touch the two free ends TOGETHER. That is a connection by definition, so it
must report CONNECTED. If it does not, a jumper is not seated and every reading
after it would have been a lie. Prove the instrument before trusting the
measurement.

TWO THINGS THIS HAS TO GET RIGHT, AND THE FIRST VERSION GOT BOTH WRONG

1. BOUNCE. A hand-held dupont pin is not a sprung meter probe. It makes and
   breaks contact many times a second, so the pin reading is not a steady low
   while touching -- it is mostly low, peppered with highs. The first version
   demanded an unbroken low and so ended the measurement on the first bounce,
   reporting a 10ms contact every time and never once confirming a connection
   that was really there. Hence DUTY_MIN: judge the PROPORTION of low samples
   across the hold, not an unbroken run of them.

2. CAPACITORS, which is the direction that costs money. An uncharged capacitor
   looks exactly like a short until it fills. Through 55k a 100uF electrolytic
   holds the pin below the logic threshold for more than a second, so a fixed
   "low for 800ms means connected" would have declared the module's VCC pin to
   be ground -- and wiring it that way round destroys the module.

   The fix is not a longer timer; a bigger capacitor beats any timer. It is the
   SECOND TOUCH. Lift the probe and touch the same point again straight away: a
   capacitor is still charged from the first touch and will not go low again,
   while ground goes low instantly every single time. That is a difference in
   kind rather than degree, so it settles the question no matter what value the
   capacitor is. This script asks for that second touch and will not call
   anything ground without it.
"""

import machine
import time

PROBE_PIN = 14

POLL_MS = 5

# How long the probe has to be held before a verdict. Long enough that a small
# decoupling capacitor is fully charged and has let go again; the second touch,
# not this number, is what defends against a large one.
HOLD_MS = 2500

# Fraction of samples that must read low across the hold. Well under 1.0 so
# that contact bounce does not disqualify a real connection, and well over 0.5
# so that a probe barely grazing the target is still rejected.
DUTY_MIN = 0.80

# No low at all for this long means the probe has been lifted and the touch is
# over. Longer than any plausible bounce gap.
GAP_END_MS = 400

# A touch is acknowledged when at least half of the last CONTACT_WINDOW_MS read
# low. Deliberately a proportion over a window rather than an unbroken run of
# lows: a run would reject mains hum nicely and then also reject a badly
# bouncing contact, which can break every few samples and never string enough
# lows together. Hum sits at a few percent in any window; even a poor contact
# sits far above half. The two do not overlap.
CONTACT_WINDOW_MS = 100
CONTACT_WINDOW = CONTACT_WINDOW_MS // POLL_MS
CONTACT_OPEN_LOWS = CONTACT_WINDOW // 2

IDLE_REPORT_MS = 6000

probe = machine.Pin(PROBE_PIN, machine.Pin.IN, machine.Pin.PULL_UP)


def banner():
    print("continuity tester -- two wires: Pico GND (pin 38) and GP%d (pin 19)"
          % PROBE_PIN)
    print("Touch both free ends to two points; this says if they are joined.\n")
    print("THE MODULE BEING PROBED MUST HAVE NOTHING PLUGGED INTO IT.\n")
    print("1. Touch the two free ends TOGETHER. It must say CONNECTED.")
    print("   If it does not, reseat the jumpers before going any further.")
    print("2. Hold one end on a bare metal point that is definitely the")
    print("   module's ground -- a SOLDER BLOB on the back, never a painted")
    print("   surface -- and connect the other to each outer pin in turn.")
    print("3. Hold each one for %.1fs -- there is a countdown. Wobble is fine,"
          % (HOLD_MS / 1000))
    print("   it is measuring how much of the time you are in contact.")
    print("4. Whenever it says CONNECTED, touch the SAME point again to")
    print("   confirm. Ground goes low twice; a capacitor only goes low once.\n")
    print("Ctrl-C to stop.\n")


def noise_floor():
    """Measure what the pin reads with nothing touching, and say so out loud.

    Worth a second of everyone's time because the failure it catches is one
    that reads as a hardware fault: a probe wire long enough to pick up mains
    hum makes the pin flicker low, and without this the first thing the script
    ever says is "contact" while the probe is lying on the bench. Knowing the
    floor is 5% turns that from a mystery into a number.
    """
    print("noise floor -- touch NOTHING for one second ...")
    lows = 0
    for _ in range(1000 // POLL_MS):
        if probe.value() == 0:
            lows += 1
        time.sleep_ms(POLL_MS)
    pct = lows * 100 // (1000 // POLL_MS)
    print("   %d%% of samples read low with the probe touching nothing." % pct)

    if pct > 40:
        print("   TOO HIGH. Something really is holding GP%d down -- a jumper"
              % PROBE_PIN)
        print("   still in the wrong row, or the probe resting on metal.")
        print("   Nothing below will mean anything until that is fixed.\n")
    elif pct:
        print("   That is mains hum on a dangling wire, not a fault. Hum")
        print("   flickers a few percent of samples; a touch fills most of a")
        print("   %dms window, and only the second registers.\n"
              % CONTACT_WINDOW_MS)
    else:
        print("   Clean.\n")


class Touch:
    """One probe contact, from first low until the probe is lifted."""

    def __init__(self, now):
        self.began = now
        self.last_low = now
        self.total = 0
        self.low = 0
        self.verdict = None

    def sample(self, is_low, now):
        self.total += 1
        if is_low:
            self.low += 1
            self.last_low = now

    def span(self):
        """Time from first low to last low -- the contact itself, excluding
        the GAP_END_MS of silence that proves the probe was lifted."""
        return time.ticks_diff(self.last_low, self.began)

    def duty(self):
        return self.low / self.total if self.total else 0.0


def watch():
    touch = None
    last_low = 0
    next_tick = 0
    last_idle = time.ticks_ms()
    # Whether the previous touch was judged a connection -- the second touch is
    # only meaningful as a follow-up to a first one.
    previous_connected = False

    # Ring buffer of the most recent samples, 1 = high, plus a running count of
    # the lows in it so the window costs one add and one subtract per poll
    # rather than a sum over the whole buffer.
    window = [1] * CONTACT_WINDOW
    wi = 0
    lows_in_window = 0

    while True:
        now = time.ticks_ms()
        is_low = probe.value() == 0

        if is_low:
            last_low = now

        lows_in_window -= 1 - window[wi]
        window[wi] = 0 if is_low else 1
        lows_in_window += 1 - window[wi]
        wi = (wi + 1) % CONTACT_WINDOW

        # A dangling probe wire is an aerial and the internal pull-up is only
        # ~55k -- a high enough impedance that mains hum alone drags the pin
        # under the logic threshold for a few percent of samples. Those dips
        # are sparse; any real contact, however badly it bounces, fills most of
        # the window. The first version opened a touch on ONE low sample, so it
        # announced "contact" with the probe lying on the bench.
        if touch is None and lows_in_window >= CONTACT_OPEN_LOWS:
            # Backdated to the OLDEST low still in the window and seeded with
            # the samples from there, because the contact began when the
            # window started filling, not when it finished. Without this a
            # brief capacitor pulse is judged on the samples AFTER the pulse
            # -- all high -- and reported as "low for 0ms" grazing instead of
            # as a capacitor. The ring is oldest-first from wi, so the first
            # low found scanning forward is the contact's true start.
            age = 0
            for k in range(CONTACT_WINDOW):
                if window[(wi + k) % CONTACT_WINDOW] == 0:
                    age = (CONTACT_WINDOW - k) * POLL_MS
                    break
            touch = Touch(time.ticks_add(now, -age))
            touch.total = max(1, age // POLL_MS)
            touch.low = lows_in_window
            touch.last_low = last_low
            next_tick = 500
            if previous_connected:
                print("  second touch -- it went low again.")
            else:
                print("  contact ... hold it there")

        if touch is not None:
            touch.sample(is_low, now)
            held = time.ticks_diff(now, touch.began)

            if touch.verdict is None and held >= next_tick and held < HOLD_MS:
                print("     %.1fs  (in contact %d%% of the time)"
                      % (held / 1000, touch.duty() * 100))
                next_tick += 500

            if touch.verdict is None and held >= HOLD_MS:
                touch.verdict = judge(touch, previous_connected)

            if time.ticks_diff(now, last_low) >= GAP_END_MS:
                if touch.verdict is None:
                    touch.verdict = judge_short(touch, previous_connected)
                if touch.verdict != "retry":
                    # "retry" deliberately leaves the flag alone: a fumbled
                    # confirmation is missing evidence, not contrary evidence,
                    # so the first CONNECTED survives and can still be
                    # confirmed by the next attempt.
                    previous_connected = touch.verdict == "connected"
                touch = None
                last_idle = now
        elif time.ticks_diff(now, last_idle) >= IDLE_REPORT_MS:
            print("  (open -- the two tips are not touching anything joined)")
            last_idle = now

        time.sleep_ms(POLL_MS)


def judge(touch, previous_connected):
    """Verdict for a touch that lasted the full hold."""
    duty = touch.duty()
    if duty < DUTY_MIN:
        if previous_connected:
            return fumbled_confirmation(
                "in contact only %d%% of the time" % (duty * 100))
        print("  UNCLEAR -- low only %d%% of the time. That is more than a"
              % (duty * 100))
        print("  capacitor and less than a connection: the tip is grazing the")
        print("  target rather than sitting on it. Press harder and redo.\n")
        return "unclear"

    if previous_connected:
        print("  CONFIRMED -- low twice in a row, %.1fs the second time."
              % (HOLD_MS / 1000))
        print("  A capacitor cannot do that; it is still charged from the")
        print("  first touch. THIS POINT IS JOINED TO THE OTHER ONE.\n")
    else:
        print("  CONNECTED -- low %d%% of %.1fs."
              % (duty * 100, HOLD_MS / 1000))
        print("  Now lift the probe and touch the SAME point again. If it goes")
        print("  low a second time it is really a connection; if it stays high")
        print("  it was a large capacitor charging and this is NOT ground.\n")
    return "connected"


def fumbled_confirmation(detail):
    """A second touch that did not hold. Says nothing about the point itself.

    Worth its own path because the obvious handling is wrong: treating a
    fumbled confirmation as evidence would throw away a good first reading and
    print a conclusion the data does not support. A confirmation can only
    confirm or stay silent -- it can never refute.
    """
    print("  confirming touch did not hold -- %s." % detail)
    print("  That says nothing either way. The first CONNECTED still stands;")
    print("  touch the same point again and hold it to settle it.\n")
    return "retry"


def judge_short(touch, previous_connected):
    """Verdict for a touch that ended before the hold completed.

    Judged over the contact SPAN, not the whole touch: the touch only ends
    after GAP_END_MS of silence, and counting that silence as "not in contact"
    would bury a genuine 50ms capacitor pulse under 400ms of highs.
    """
    span = touch.span()
    span_duty = touch.low / max(1, span // POLL_MS)

    if previous_connected:
        return fumbled_confirmation("broke off after %dms" % span)

    if span_duty <= 0.6:
        print("  UNCLEAR -- in contact only %d%% of %dms. The tip is grazing"
              % (span_duty * 100, span))
        print("  the target rather than sitting on it. Press harder, redo.\n")
        return "unclear"

    # A charging capacitor and a slipped probe produce the IDENTICAL waveform.
    # The pin cannot separate them and neither can this script, so it must not
    # pretend to -- an earlier version asserted "that is a capacitor", which
    # was nonsense during the self-test where the only things in the circuit
    # are two bare wires. Report the shape, name both causes, let the person
    # holding the wire decide, since only they know whether they moved.
    print("  INCONCLUSIVE -- low for %dms, then high, and the hold never"
          % span)
    print("  completed. Two different things look exactly like this:")
    print("    * the tip slipped off, or")
    print("    * this point goes to a capacitor, which fills up and lets go.")
    if span < 300:
        print("  Under %dms it is usually a slip. Try again; if it keeps"
              % 300)
        print("  doing this while you hold steady, it is the capacitor.\n")
    else:
        print("  If you were holding steady throughout, it is the capacitor,")
        print("  which means this point is NOT ground.\n")
    return "inconclusive"


try:
    banner()
    noise_floor()
    watch()
except KeyboardInterrupt:
    print("\nCtrl-C -- stopping")
finally:
    # Leave the pad the way a reset would. mpremote's soft reset does NOT
    # restore pad configuration, so a pull-up left set here would still be
    # driving the next script that touches GP14 -- which is pir_test.py, on
    # this very pin. That would quietly hold the PIR's output line up.
    probe.init(machine.Pin.IN, None)
    print("GP%d released, pull-up off." % PROBE_PIN)
