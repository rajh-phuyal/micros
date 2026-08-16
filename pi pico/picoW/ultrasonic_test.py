"""Ultrasonic test -- continuous distance readings from an HC-SR04.

Board:  Raspberry Pi Pico W (RP2040, 2022).
Run:    uv run mpremote run "pi pico/picoW/ultrasonic_test.py"
        See ../../README.md for the full flash/connect/push flow.

WIRING:

    TRIG  ->  GP2    physical pin 4
    ECHO  ->  voltage divider  ->  GP3    physical pin 5
    VCC   ->  VBUS   physical pin 40   (5V -- the HC-SR04 needs it)
    GND   ->  GND    physical pin 38

ECHO pulses to 5V and the Pico's GPIOs are 3.3V-only, so it must go through a
divider -- 1k from ECHO to the junction, 2k from the junction to GND, and GP3
reads the junction. That gives 5 * 2/(1+2) = 3.3V. Wiring ECHO straight to a
GPIO will eventually kill the pin.

VCC genuinely needs 5V. A real HC-SR04 will not fire on 3.3V, which looks
identical to a dead sensor: every reading just times out.

TIMING: the sensor needs ~60ms of quiet between pings, otherwise the tail of
the previous burst is still bouncing around and gets read as a bogus short
distance. INTERVAL_MS below must stay at or above 60.

RANGE: roughly 2cm to 4m, but the useful near limit is more like 15cm.

The near limit is the one that trips people up. After firing its 40kHz burst
the transducer keeps ringing for a moment, and it is deaf while it does. An
object close enough that the echo returns during that ring-down is missed
entirely -- so the sensor reports the NEXT thing it hears instead, which is
whatever is behind your hand. A hand held 5cm away reading 220cm is not a
fault; it is the wall on the far side of the room.

Soft or angled surfaces scatter the ping and read as out-of-range. A flat
palm held square to the sensor at 20-30cm is the reliable test target.

IF THE READINGS LOOK PLAUSIBLE BUT NEVER CHANGE -- check the pin numbers
before anything else. An unconnected GPIO floats and picks up 50Hz mains hum,
which reads as a ~10ms pulse, which converts to a steady ~150cm that ignores
whatever you put in front of the sensor. It looks exactly like a working
sensor aimed somewhere unhelpful, and it cost an hour of debugging here.

Two checks that tell real data from a floating pin:

    Hold TRIG low and count ECHO edges. A connected sensor gives 0. A
    floating pin gives ~50 per second (~150 in 3s at 50Hz mains).

        uv run mpremote exec "import machine,time; t=machine.Pin(2,machine.Pin.OUT); e=machine.Pin(3,machine.Pin.IN); t.value(0); time.sleep_ms(300); n=0; last=e.value(); s=time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(),s)<3000:
            v=e.value()
            if v and not last: n+=1
            last=v
        print('unsolicited edges:', n)"

    Measure the delay from trigger to ECHO rising. Real: constant, ~2ms on
    this module. Floating: ~10ms and drifting a few tens of us per reading,
    because you are sampling a free-running 50Hz waveform at a random phase.
"""

import machine
import time

TRIG_PIN = 2
ECHO_PIN = 3

# Sound travels 0.0343 cm/us at room temperature. The ping goes out and comes
# back, so the measured time covers twice the distance.
CM_PER_US = 0.0343

# 4m out and back is ~23ms. 30ms gives headroom and still fails fast.
TIMEOUT_US = 30_000

# Quiet time between pings. 60ms is the sensor's floor; 70 leaves margin.
# A read itself costs ~19ms, so this gives roughly 11 readings a second --
# fast enough that moving your hand tracks smoothly.
INTERVAL_MS = 70

trig = machine.Pin(TRIG_PIN, machine.Pin.OUT)
echo = machine.Pin(ECHO_PIN, machine.Pin.IN)


def read_cm():
    """One measurement. Returns cm, or None if the ping never came back."""
    trig.value(0)
    time.sleep_us(2)
    trig.value(1)
    time.sleep_us(10)  # HC-SR04 wants a 10us trigger pulse
    trig.value(0)

    # Blocks until ECHO goes high, then times how long it stays high.
    # Negative means timeout: -1 = echo never fell, -2 = echo never rose.
    us = machine.time_pulse_us(echo, 1, TIMEOUT_US)
    if us < 0:
        return None
    return (us * CM_PER_US) / 2


print("reading -- Ctrl-C to stop")

while True:
    cm = read_cm()
    if cm is None:
        print("   --   no echo (out of range, or too close)")
    else:
        # One block per 5cm, capped, so movement is obvious at a glance.
        bar = "#" * min(40, int(cm / 5))
        print("{:6.1f} cm |{}".format(cm, bar))
    time.sleep_ms(INTERVAL_MS)
