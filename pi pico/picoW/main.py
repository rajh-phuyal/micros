"""Connection test -- blink the onboard LED.

Board:  Raspberry Pi Pico W (RP2040, 2022).
Run:    uv run mpremote run "pi pico/picoW/main.py"
        See ../../README.md for the full flash/connect/push flow.

On a Pico W the onboard LED is wired to the CYW43 WiFi chip, not to a GPIO,
so it is Pin("LED"). Pin(25) is the WiFi chip select on this board -- it
compiles and runs fine, it just never lights anything. That is the usual
reason a working plain-Pico blink does nothing on a Pico W.

"""

import machine
import time

led = machine.Pin("LED", machine.Pin.OUT)

print("blinking -- Ctrl-C to stop")

while True:
    led.toggle()
    print("led:", led.value())
    time.sleep(0.5)
