"""Buzzer test -- play tones on a passive buzzer on GP16.

Board:  Raspberry Pi Pico W (RP2040, 2022).
Run:    uv run mpremote run "pi pico/picoW/buzzer_test.py"
Or via the Pi the Pico is plugged into (see README section 5):
        scp "pi pico/picoW/buzzer_test.py" my-pi:/tmp/ && ssh -t my-pi '~/.local/bin/mpremote run /tmp/buzzer_test.py'
        See ../../README.md for the full flash/connect/push flow.

WIRING -- two-pin bare buzzer:

    buzzer +  ->  330R resistor  ->  GP16   physical pin 21
    buzzer -  ->  GND rail       ->  GND    physical pin 38

WIRING -- three-pin module (KY-006 and clones), pins marked  -  middle  S:

    S       ->  330R resistor  ->  GP16   physical pin 21
    middle  ->  3V3            ->  physical pin 36
    -       ->  GND rail

POLARITY on a two-pin buzzer: for a PASSIVE one it does not matter. It is
driven by a square wave, so swapping the leads inverts the phase and sounds
identical. If the markings are worn off, wire it either way -- and note that
"sounds the same reversed" is itself proof it is passive. (Longer leg is +,
and many have a + moulded into the top face, if you want to know anyway.)

THE SERIES RESISTOR IS NOT DECORATION. Two different parts get sold as
"passive buzzer" and they draw wildly different current:

    piezo     a ceramic disc. Effectively a capacitor -- microamps. Any
              resistor value works; it only sets volume.
    magnetic  a coil, like a tiny speaker. Typically 8-16 ohms. Straight off
              a GPIO that is 3.3V / 16R = ~200mA, and an RP2040 pin is rated
              for 12mA. The small black cylinders in starter kits are these.

330R puts a 16R magnetic coil at ~9.5mA, inside spec, and merely makes a
piezo a little quieter. So 330R is the safe default when you do not know
which you have. Drop to 100R for more volume only once you have confirmed
it is a piezo. A multimeter across the two pins settles it instantly: a few
ohms means magnetic, open circuit means piezo.

MEASURED HERE: ~42 ohms, so this one is MAGNETIC. buzzer_id.py did the
measuring. That means 330R is load-bearing, not decorative -- it is the only
thing keeping the pin inside spec, and dropping it to 100R would be 23mA
against a 12mA rating.

FOR REAL VOLUME, USE A TRANSISTOR

Driving the coil straight off a GPIO caps you at ~9mA, which is about 3mW
into the buzzer. A small NPN takes the coil off the pin's budget entirely and
lets it have the full rail:

    GP16  --[ 1k ]--  base
    3V3 (pin 36)  --  buzzer  --  collector
    emitter  --  GND rail
    1N4148 across the buzzer, BANDED END to the 3V3 side

That is ~74mA through the coil, roughly 230mW -- about 18dB louder, which is
a different device rather than a slight improvement. Fit the series resistor
back in (47R-100R) if it turns out to be painful, or just lower VOLUME: with
the transistor carrying the current, duty cycle finally works as a real
volume control instead of being pinned at maximum.

The diode is not optional. A coil that gets switched off dumps its stored
energy as a reverse spike, and without somewhere to go that spike kills the
transistor. The banded end goes to the positive side.

The middle leg of a TO-92 NPN is the base on every common part, but E and C
swap between families -- 2N3904 and S8050 are E-B-C read with the flat face
towards you, BC337 and BC547 are C-B-E. Check the part you actually have;
swapping E and C leaves it in reverse-active mode, which barely conducts and
looks like a dead transistor.

PASSIVE vs ACTIVE -- get this wrong and nothing works:

    passive = a bare speaker. Needs a square wave. YOU pick the pitch,
              which is what makes tunes possible. Silent on steady DC.
    active  = has its own oscillator inside. Beeps on steady DC at one
              fixed pitch, and ignores PWM entirely.

Tell them apart without a datasheet -- drive the pin steady high:

    uv run mpremote exec "import machine,time; p=machine.Pin(16,machine.Pin.OUT); p.value(1); time.sleep(1); p.value(0)"

A continuous beep means it is ACTIVE and this script will not work properly
on it -- an active buzzer just drones at its own pitch. A single faint click
at each edge, then silence, means it is PASSIVE. That is the one you want.

WHY GP16 AND NOT GP14

RP2040 PWM has 8 slices, each shared by a pair of GPIOs: slice = (GP / 2) % 8.
A slice has ONE frequency shared across both its channels. The servo on GP15
is slice 7 and needs 50Hz. GP14 is also slice 7 -- putting the buzzer there
would force both to the same frequency, and whichever was configured last
would win. The servo would go haywire, or the buzzer would be inaudible, and
the wiring would look perfect the whole time.

GP16 is slice 0. Any pin outside the GP14/GP15 pair is fine.
"""

import machine
import time

BUZZER_PIN = 16

# duty_u16 doubles as volume. 32768 is a 50% square wave -- the loudest a
# passive buzzer will go. Lower values narrow the pulse and quieten it, and
# so do HIGHER ones: 44000 is the same pulse width as 21535, just inverted.
# 0 is silence, and is how a note is ended.
#
# Volume comes far more from frequency than from duty. See buzzer_tune.py --
# a buzzer has a sharp resonant peak, usually 2-4kHz, and playing an octave
# below it is quiet no matter what you set here.
VOLUME = 32768

NOTE_GAP_MS = 30   # brief silence between notes so they don't slur together

# Equal-temperament frequencies, rounded to whole Hz. Good enough for a
# buzzer -- nobody is tuning an orchestra to this.
NOTES = {
    "C5": 523, "D5": 587, "E5": 659, "F5": 698, "G5": 784,
    "A5": 880, "B5": 988, "C6": 1047, "D6": 1175, "E6": 1319,
    "G6": 1568, "C7": 2093,
}


class Buzzer:
    def __init__(self, pin):
        self.pwm = machine.PWM(machine.Pin(pin))
        self.pwm.duty_u16(0)   # silent until asked

    def start(self, hz, volume=VOLUME):
        """Begin a tone and return immediately.

        PWM is a hardware peripheral, so the note keeps sounding on its own
        with no CPU involvement -- which is how the robot chirps and moves
        its head at the same time without any threading.
        """
        self.pwm.freq(hz)
        self.pwm.duty_u16(volume)

    def stop(self):
        self.pwm.duty_u16(0)

    def tone(self, hz, ms, volume=VOLUME):
        """Blocking single note. hz of 0 is a rest."""
        if hz > 0:
            self.start(hz, volume)
        time.sleep_ms(ms)
        self.stop()

    def play(self, notes):
        """notes is a sequence of (hz, ms) pairs."""
        for hz, ms in notes:
            self.tone(hz, ms)
            time.sleep_ms(NOTE_GAP_MS)

    def slide(self, start_hz, end_hz, ms, steps=24):
        """Glide between two pitches. This is what sounds robotic and cute --
        discrete notes sound like a doorbell, a slide sounds like a droid."""
        step_ms = max(1, ms // steps)
        for i in range(steps + 1):
            self.start(start_hz + (end_hz - start_hz) * i // steps)
            time.sleep_ms(step_ms)
        self.stop()

    def release(self):
        """Hand the pin back. Same lesson as the servo -- PWM runs in
        hardware, so without this the buzzer drones on after the script
        exits, and Ctrl-C looks like it did nothing."""
        self.pwm.deinit()


# Onboard LED on as a liveness indicator -- lit means the board has power and
# got as far as running this.
machine.Pin("LED", machine.Pin.OUT).value(1)

buzzer = Buzzer(BUZZER_PIN)

try:
    # This scale is deliberately below the resonant peak, and you can hear
    # it: the top notes are noticeably louder than the bottom ones even
    # though every one is at the same duty. That unevenness IS the resonance,
    # and it is why the robot's tunes live up around 4kHz instead.
    print("scale up -- note how the higher notes are louder")
    for name in ("C5", "D5", "E5", "F5", "G5", "A5", "B5", "C6"):
        print("  ", name, NOTES[name])
        buzzer.tone(NOTES[name], 180)
        time.sleep_ms(NOTE_GAP_MS)

    time.sleep_ms(400)

    print("volume steps -- should get louder")
    for vol in (2000, 6000, 14000, 32768):
        print("   duty", vol)
        buzzer.tone(NOTES["A5"], 250, vol)
        time.sleep_ms(120)

    time.sleep_ms(400)

    print("slides -- the cute robot noises")
    # Pitched around this buzzer's measured 4kHz resonance (see
    # buzzer_tune.py). Rising INTO the peak swells in volume all by itself,
    # and falling away from it fades -- which is why these read as cheerful
    # and disappointed rather than as two identical bleeps.
    buzzer.slide(1600, 4000, 300)     # rising: curious / greeting
    time.sleep_ms(150)
    buzzer.slide(4000, 1600, 300)     # falling: disappointed
    time.sleep_ms(150)
    buzzer.slide(3200, 4400, 120)     # quick warble up...
    buzzer.slide(4400, 3200, 120)     # ...and back: excited
    time.sleep_ms(400)

    print("done")
except KeyboardInterrupt:
    print("\nCtrl-C -- stopping")
finally:
    buzzer.release()
    print("buzzer released")
