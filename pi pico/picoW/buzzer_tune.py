"""Buzzer tuning -- find the frequency your buzzer is actually loudest at.

Board:  Raspberry Pi Pico W (RP2040, 2022).
Run:    uv run mpremote run "pi pico/picoW/buzzer_tune.py"
Wiring: see buzzer_test.py. GP16 via a series resistor.

WHY THIS EXISTS

A buzzer is not a speaker with a flat response -- it is a mechanical
resonator with a sharp peak, typically 2-4kHz for the small ones. Drive it
an octave below that peak and it is genuinely quiet, no matter how much
current you push through it. Drive it AT the peak and it is piercing.

So "the buzzer is too quiet" is usually a tuning problem, not a power
problem. This plays a ladder of frequencies at full duty so you can hear
which one jumps out, then feeds that number back into the melodies.

The datasheet number, if you have one, is printed as the resonant frequency
-- 2048Hz, 2700Hz and 4000Hz are all common. This script is what you use
when you do not.

HOW TO USE IT

Listen to the ladder. One or two steps will be obviously louder than their
neighbours -- that is the peak. Note the printed frequency, then raise the
melody notes in robot.py to sit near it. It does not have to be exact; the
peak is broad enough that landing within a few hundred Hz gets most of it.

Then the second pass sweeps duty cycle at that peak, so you can hear how
much headroom is left. 32768 is a 50% square wave and the maximum -- past
that the pulse narrows again and it gets QUIETER, which surprises people.
"""

import machine
import time

BUZZER_PIN = 16

MAX_DUTY = 32768   # 50% square wave -- loudest possible from PWM

# Ladder covering everything a small buzzer might resonate at. Roughly
# quarter-octave steps, so neighbouring tones are close enough to compare
# by ear but far enough apart to keep the list short.
SWEEP_HZ = (
    400, 500, 600, 750, 900, 1100, 1300, 1600,
    1900, 2300, 2700, 3200, 3800, 4500, 5300, 6300,
)

STEP_MS = 400      # long enough to judge loudness, short enough to stay awake
GAP_MS = 120


class Buzzer:
    def __init__(self, pin):
        self.pwm = machine.PWM(machine.Pin(pin))
        self.pwm.duty_u16(0)

    def tone(self, hz, ms, duty=MAX_DUTY):
        self.pwm.freq(hz)
        self.pwm.duty_u16(duty)
        time.sleep_ms(ms)
        self.pwm.duty_u16(0)

    def release(self):
        self.pwm.deinit()


machine.Pin("LED", machine.Pin.OUT).value(1)

buzzer = Buzzer(BUZZER_PIN)

try:
    print("PASS 1 -- frequency ladder at full duty.")
    print("Listen for the step that is obviously louder than its neighbours.\n")

    # Twice through, because the loudest step is much easier to pick out on
    # the second listen when you already know roughly where it is.
    for lap in (1, 2):
        print("  lap", lap)
        for hz in SWEEP_HZ:
            print("   %5d Hz" % hz)
            buzzer.tone(hz, STEP_MS)
            time.sleep_ms(GAP_MS)
        time.sleep_ms(800)

    print("\nPASS 2 -- duty sweep, stepping across the middle of the range.")
    print("Loudness should peak at 32768 (50%) and fall off either side.\n")

    for hz in (1600, 2700, 4000):
        print("  at %d Hz" % hz)
        for duty in (2000, 6000, 14000, 24000, 32768, 44000, 56000):
            # Past 32768 the pulse narrows again -- 44000 is the same width
            # as 21535, just inverted. It gets quieter, not louder.
            pct = duty * 100 // 65535
            print("   duty %5d  (%2d%%)" % (duty, pct))
            buzzer.tone(hz, 300, duty)
            time.sleep_ms(100)
        time.sleep_ms(600)

    print("\ndone -- tell me which frequency was loudest")
except KeyboardInterrupt:
    print("\nCtrl-C -- stopping")
finally:
    buzzer.release()
    print("buzzer released")
