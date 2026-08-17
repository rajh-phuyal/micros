"""HC-SR501 PIR motion sensor -- prove the part before wiring it into robot.py.

Board:  Raspberry Pi Pico W (RP2040, 2022).
Run:    uv run mpremote run "pi pico/picoW/pir_test.py"
Or through the Pi the Pico is plugged into (README section 5):
        scp "pi pico/picoW/pir_test.py" my-pi:/tmp/ && ssh -t my-pi '~/.local/bin/mpremote run /tmp/pir_test.py'

This file drives NOTHING except the sensor -- no servo, no strip, no buzzer.
If it misbehaves there is only one thing it can be.

WHAT THIS SENSOR ACTUALLY IS

Passive InfraRed. It does not emit anything; it watches infrared radiation
through a faceted Fresnel dome that splits the view into zones. A warm body
CROSSING between zones changes the reading and trips the output. Two
consequences that matter more than anything else in this file:

  * It detects CHANGE, not presence. Someone who stands perfectly still stops
    existing as far as this sensor is concerned. It is a motion detector in the
    literal sense, not a person detector.
  * It has NO DIRECTION. The output is one bit for a ~110 degree cone up to
    several metres. It can tell robot.py that something happened. It can never
    tell it where, so it cannot drive tracking on its own -- that stays the
    job of sweeping the HC-SR04, which gets bearing from the servo's position.

FINDING THE THREE PINS WHEN THE BOARD HAS NO MARKINGS

This module has no silkscreen at all, so the pins have to be identified rather
than read. That has to be got right first time: VCC and GND swapped destroys
the module. There is no meter here, so it is done by eye and then confirmed
with continuity_test.py, which turns the Pico itself into a continuity tester.

Only the outer two pins are ever in doubt -- the MIDDLE pin is OUT on every
HC-SR501 variant.

By eye, turn the board over and look at the three solder pads:

  * Two of them sit inside a small ring of bare board, isolated from the copper
    around them.
  * One connects straight into the large copper area -- either solid, or by
    two to four short spokes. That one is GND. Ground is the only net on a
    board like this that gets the whole pour to itself.

Cross-check it against the tall cylindrical capacitor: the side with a stripe
printed down it is the negative leg, and it lands in that same copper.

Then confirm it before any power goes anywhere near it. Run continuity_test.py,
hold its reference wire on the copper pour and touch its probe to each outer
pin: the one that reads CONNECTED is GND, the other is VCC. Unpowered, so a
wrong guess at this stage costs nothing.

WIRING

    PIR VCC  ->  5V rail from VBUS pin 40
    PIR OUT  ->  1k in series ->  GP14   physical pin 19   (see below)
    PIR GND  ->  GND rail -> GND pin 38   (pin 18 is a GND right beside GP14)

NO DIVIDER NEEDED, unlike the HC-SR04's ECHO. The BISS0001 chip on this board
runs from the module's own onboard 3.3V regulator, so OUT swings 0-3.3V even
though VCC is 5V. That is by design, not luck.

Clones exist though, and with no meter here there is no way to check what OUT
actually swings to. So put a single 1k resistor in SERIES with the OUT wire --
not a divider, just one resistor in line. It costs nothing and covers both
cases: a 3.3V output still reads as a clean high, because a GPIO input draws
about a microamp and a microamp across 1k is no drop worth having; and a 5V
output gets clamped by the RP2040's own protection diode with the current held
to a safe ~1.4mA instead of whatever the module can push.

That only works while GP14 has no pull resistor enabled -- a pull would turn
the series resistor into exactly the divider it is not supposed to be. Plain
Pin.IN, as below, is right. Note continuity_test.py leaves a pull-up ON GP14
during its run, which is why it deliberately clears it on the way out.

GP14 shares PWM slice 7 with the servo's GP15. That is fine and always will be
here, because this pin is only ever a digital input -- the slice conflict that
mattered for the buzzer only exists between two PWM outputs.

THE TWO POTS AND THE JUMPER -- most "faulty sensor" reports are these

There are two little screws and one two-position jumper, and they do:

    SENSITIVITY   range, roughly 3m to 7m. Anywhere is fine on a desk.
    TIME DELAY    Tx: how long OUT stays HIGH after a trigger, 0.3s to 300s.
                  Ships near maximum on many boards, which looks exactly like
                  a sensor stuck on. This is the one that matters.
    JUMPER  H     repeatable trigger -- OUT stays high while motion continues.
            L     single trigger -- OUT drops after Tx regardless.

H is what a robot wants: it should stay awake while you are still moving
around, and L makes it fall asleep in your face.

WITH NO MARKINGS you cannot tell which screw is which, or which jumper
position is H. Do not try to. The test below MEASURES both -- it reports the
delay it observed and infers the jumper mode from whether the high times vary.
So the procedure is empirical, not informed:

  1. Run it as the board arrived. Read the reported Tx and jumper mode.
  2. Wrong delay? Turn ONE screw a quarter turn and run again. If Tx moved,
     that screw is TIME DELAY; if not, it is the other one. Now you know.
  3. Reported L? Move the jumper to its other position and run again.

Two runs identifies the whole board, and nothing here can be damaged by
guessing wrong -- a mis-set pot is a bad reading, not a dead part.

WARM-UP IS REAL AND IT WILL FOOL YOU

The sensor needs 30-60s after power-on to settle its reference level, and it
throws false positives the whole time. Stage 0 below deliberately watches that
window and reports what it sees, because "it triggered the moment I plugged it
in" is the single most common way this part gets wrongly condemned -- and for
robot.py it matters directly: without a warm-up gate the robot would wake up
spuriously every single time it starts.

POWER

Idle draw is around 50uA and the peak is under a milliamp. Against a 600mA
budget that is free, and it is the reason this idea is worth having: an idle
robot that is genuinely idle costs far less than one patrolling, because the
servo stops moving entirely.

IF NOTHING TRIGGERS

  1. Wait out the warm-up. Really. Stage 0 exists for this.
  2. Turn each screw in turn and re-run -- see the pots section above. The
     delay pot arriving near maximum is the single commonest cause.
  3. Check the jumper is fitted at all -- with it off, behaviour is undefined.
  4. Confirm VCC is 5V, not 3.3V. Most of these will not run from 3V3, which
     is the one place this sensor differs from everything else in this project.
  5. Check the dome is actually seated. It pushes on, and a loose one destroys
     the zone pattern the whole method depends on.
  6. Wave a hand ACROSS the field of view, not towards it. Crossing zones is
     what it detects; walking straight at it is the weakest possible signal.

IF IT TRIGGERS WHEN NOBODY IS MOVING

Run this and walk out of the room for stage 1 (or put the sensor face-down
on the desk before starting). Triggers arriving every few seconds with
nobody there are phantoms -- the sensor firing on its own. The giveaway is
RHYTHM: real people are irregular, phantoms come at a steady interval.

Prime suspect if the dome is off: the dome is not just a lens. It also
shields the bare pyro element from draughts and ambient infrared, and an
uncovered element can free-run on air currents alone. Put the dome back on
and re-run before blaming the board.
"""

import machine
import time

PIR_PIN = 14

WARMUP_S = 60          # what the datasheet asks for; stage 0 measures reality
WATCH_S = 45           # how long stage 1 listens

pir = machine.Pin(PIR_PIN, machine.Pin.IN)


def stage0_warmup():
    """Watch the settling window and report the false positives in it."""
    print("STAGE 0 -- warm-up, %ds. Stay still and leave it alone." % WARMUP_S)
    print("Anything reported here is the sensor settling, NOT a fault.\n")

    started = time.ticks_ms()
    # ticks_ms counts from power-on and survives mpremote's soft reset, so it
    # says how long the SENSOR has been powered too -- it shares USB power.
    # A sensor that has been up for minutes settled long ago, and transitions
    # during this stage are then not settling at all: they are phantoms.
    if started > 90_000:
        print("NOTE: powered for ~%ds already, so the sensor is long settled."
              % (started // 1000))
        print("Transitions below are NOT settling -- they are the sensor")
        print("free-running. See IF IT TRIGGERS WHEN NOBODY IS MOVING.\n")
    last = pir.value()
    glitches = 0
    next_tick = 10

    while time.ticks_diff(time.ticks_ms(), started) < WARMUP_S * 1000:
        v = pir.value()
        if v != last:
            elapsed = time.ticks_diff(time.ticks_ms(), started) / 1000
            print("   %5.1fs  -> %d   (settling)" % (elapsed, v))
            glitches += 1
            last = v
        elapsed = time.ticks_diff(time.ticks_ms(), started) / 1000
        if elapsed >= next_tick:
            print("   %5.1fs  ... still warming, OUT=%d" % (elapsed, v))
            next_tick += 10
        time.sleep_ms(20)

    print("\n   warm-up done, %d transition(s) while settling." % glitches)
    if glitches:
        print("   That is why robot.py must gate on a warm-up before trusting")
        print("   this sensor -- it would have woken up %d time(s) for nothing."
              % glitches)
    else:
        print("   Clean warm-up. Still gate on it; it is not always this quiet.")
    print("   OUT is now %d (should be 0 -- if it is 1, turn the TIME DELAY pot"
          % pir.value())
    print("   fully anticlockwise and run again).\n")


def stage1_watch():
    """Report every edge, and time how long OUT stays high."""
    print("STAGE 1 -- watching %ds. Wave a hand ACROSS the dome." % WATCH_S)
    print("Crossing the zones is what it detects; approaching head-on is the")
    print("weakest signal it can be given.\n")

    started = time.ticks_ms()
    last = pir.value()
    rose_at = None
    triggers = 0
    highs = []

    if last:
        # A high already in progress has no observed start, so it cannot be
        # timed. One uncounted run mis-timed it from BOOT, reported a 342s
        # "high", and that single bogus number was enough to flip the jumper
        # verdict from L to H. Never time what was never seen rising.
        print("   (OUT is already high from the warm-up -- its start was")
        print("    never seen, so this first high will not be counted)\n")

    while time.ticks_diff(time.ticks_ms(), started) < WATCH_S * 1000:
        v = pir.value()
        if v != last:
            elapsed = time.ticks_diff(time.ticks_ms(), started) / 1000
            if v:
                rose_at = time.ticks_ms()
                triggers += 1
                print("   %5.1fs  MOTION      (trigger %d)" % (elapsed, triggers))
            elif rose_at is None:
                print("   %5.1fs  clear       (high since before the watch -- "
                      "not counted)" % elapsed)
            else:
                held = time.ticks_diff(time.ticks_ms(), rose_at) / 1000
                highs.append(held)
                print("   %5.1fs  clear       (was high %.1fs)" % (elapsed, held))
            last = v
        time.sleep_ms(20)

    if last and rose_at is not None:
        highs.append(time.ticks_diff(time.ticks_ms(), rose_at) / 1000)
        print("   still high when the watch ended")

    return triggers, highs


def report(triggers, highs):
    print("\n--- result ---")
    print("triggers        : %d" % triggers)
    if not triggers:
        print("\nNothing fired. Work the 'IF NOTHING TRIGGERS' list in the header")
        print("from the top -- in this project the answer has usually been the")
        print("boring first item, not the exotic last one.")
        return

    print("high durations  : %s" % ", ".join("%.1fs" % h for h in highs))
    shortest = min(highs)
    longest = max(highs)
    print("shortest / longest high : %.1fs / %.1fs" % (shortest, longest))

    print("\nTIME DELAY (Tx) reads as about %.0fs." % shortest)
    if shortest > 8:
        print("That is long. robot.py would stay awake for %.0fs after you left"
              % shortest)
        print("the room. Turn the pot anticlockwise -- 2-5s suits a robot that")
        print("should notice you leaving.")
    elif shortest < 1:
        print("That is short enough that OUT can drop between polls of a busy")
        print("loop. Fine for an IRQ, marginal for polling -- give it ~2s.")
    else:
        print("Good range for waking a robot.")

    if longest > shortest * 1.8:
        print("\nHigh times vary a lot, so the jumper is on H (retriggerable):")
        print("OUT is being held up by continued motion. That is what you want.")
    else:
        print("\nHigh times are all about equal, which looks like jumper L")
        print("(single trigger) -- OUT drops after Tx even if you keep moving.")
        print("Move it to H so the robot stays awake while you are still there.")


try:
    print("HC-SR501 on GP%d\n" % PIR_PIN)
    stage0_warmup()
    triggers, highs = stage1_watch()
    report(triggers, highs)
    print("\nNothing to release -- this sensor is read-only and drives no pin.")
except KeyboardInterrupt:
    print("\nCtrl-C -- stopping")
