"""Buzzer identification -- measure its DC resistance to find out what it is.

Board:  Raspberry Pi Pico W (RP2040, 2022).
Run:    uv run mpremote run "pi pico/picoW/buzzer_id.py"

WHY BOTHER

Two very different parts get sold as "passive buzzer", and they need opposite
treatment:

    piezo     a ceramic disc. Electrically a capacitor -- open circuit to DC,
              draws microamps. The series resistor protects nothing; it only
              throttles volume. Drop it as low as you like.
    magnetic  a coil, like a tiny speaker. 8-16 ohms. The series resistor is
              the ONLY thing standing between a 12mA-rated GPIO and a ~200mA
              short. Do not remove it.

They look identical from the outside. Guessing wrong in one direction leaves
you needlessly quiet; guessing wrong in the other slowly kills a pin.

A multimeter across the buzzer's two legs answers this in five seconds --
open circuit means piezo, a handful of ohms means magnetic. This script is
for when you do not have one to hand.

HOW IT WORKS

Your existing wiring is already a voltage divider, it just has nothing
reading the middle of it:

    GP16 ---[ series R ]---+--- buzzer ---> GND
                           |
                           +--- GP26   <-- add this one jumper (pin 31)

Drive GP16 high and read the junction with the ADC. No current flows through
an open circuit, so nothing drops across the series resistor:

    piezo (open)     junction sits at ~3.3V   -> reads full scale
    magnetic (16R)   3.3 * 16/346 = ~0.15V    -> reads near zero

That is not a subtle difference needing careful calibration. It is one end of
the range or the other.

WIRING TO ADD -- one jumper:

    junction between the resistor and the buzzer  ->  GP26   physical pin 31

The junction is the breadboard row where the resistor's second leg meets the
buzzer wire. Leave everything else exactly as it is.

Remove the jumper afterwards; it does nothing during normal operation, but
GP26 is the pin you would want for a battery-voltage sense later on.

SAFETY: this drives GP16 high into whatever is there for a few milliseconds
at a time. Worst case (a 16 ohm coil behind 330R) is ~9.5mA, inside spec.
Do NOT run this with the series resistor already removed.
"""

import machine
import time

SIG_PIN = 16
SENSE_PIN = 26

# Must match the resistor actually fitted, or the sum is wrong.
SERIES_R = 330

VREF = 3.3
SAMPLES = 64

# Above this, essentially no current is flowing -- an open circuit.
PIEZO_V = 3.0
# Below this, the series resistor is dropping nearly everything -- a low
# resistance load.
MAGNETIC_V = 1.0


machine.Pin("LED", machine.Pin.OUT).value(1)

sig = machine.Pin(SIG_PIN, machine.Pin.OUT)
adc = machine.ADC(SENSE_PIN)


def read_v():
    total = 0
    for _ in range(SAMPLES):
        total += adc.read_u16()
    return (total / SAMPLES) * VREF / 65535


try:
    sig.value(0)
    time.sleep_ms(100)
    idle_v = read_v()

    sig.value(1)
    time.sleep_ms(100)
    driven_v = read_v()
    sig.value(0)

    print("junction idle   : %.3f V" % idle_v)
    print("junction driven : %.3f V" % driven_v)

    if idle_v > 0.3:
        # A pin pulled low should sit at 0V. Anything else means the sense
        # jumper is not where it should be, or is not connected at all.
        print("\nidle voltage should be ~0V. Check the GP26 jumper is in the")
        print("junction row -- between the resistor and the buzzer, not on")
        print("the GP16 side of the resistor.")

    if driven_v >= PIEZO_V:
        print("\nPIEZO -- open circuit, no measurable current.")
        print("The %dR is only limiting volume, not protecting anything." % SERIES_R)
        print("Safe to drop it to 100R, or short it out entirely.")
    elif driven_v <= MAGNETIC_V:
        r = SERIES_R * driven_v / (VREF - driven_v)
        ma = (VREF / (SERIES_R + r)) * 1000
        print("\nMAGNETIC -- roughly %.1f ohms." % r)
        print("At %dR that is %.1f mA, against a 12mA pin rating." % (SERIES_R, ma))
        print("Dropping to 100R would be %.1f mA. Keep the resistor;" %
              ((VREF / (100 + r)) * 1000))
        print("use an NPN transistor if you want it louder.")
    else:
        r = SERIES_R * driven_v / (VREF - driven_v)
        print("\nInconclusive -- about %.0f ohms, between the two cases." % r)
        print("Neither a clean open circuit nor a low-resistance coil.")
        print("Suspect the wiring before believing this number.")
finally:
    sig.value(0)
    print("\ndone -- remove the GP26 jumper")
