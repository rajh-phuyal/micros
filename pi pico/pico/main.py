"""Pedestrian crossing traffic light.

Board:  Raspberry Pi Pico (plain RP2040) running MicroPython.
        Nothing here needs WiFi, so it runs unchanged on a Pico W too.
Deploy: uv run mpremote cp "pi pico/pico/main.py" "pi pico/pico/traffic.py" :
        (both files are required -- main.py imports traffic.py)
        See ../../README.md for the full flash/connect/push flow.

Wiring (GP numbers, not physical pin numbers):

    normal light      red    GP14  ---[220R]--- LED --- GND
                      yellow GP13  ---[220R]--- LED --- GND
                      green  GP12  ---[220R]--- LED --- GND
    pedestrian light  red    GP11  ---[220R]--- LED --- GND
                      green  GP10  ---[220R]--- LED --- GND
    request button           GP15  --- button --- GND

The button uses the internal pull-up, so it reads 1 when open and 0 when
pressed -- hence the `== 0` tests below. No external resistor needed.

GP10-GP15 behave identically on a Pico and a Pico W. Do not move them to
GP23/24/25/29: on a Pico W those belong to the WiFi chip (see README).
"""

import machine
import uasyncio

from traffic import TrafficLight


async def button_task(button_pin, ped_request, normal_light):
    while True:
        if button_pin.value() == 0 and not ped_request.is_set():
            await uasyncio.sleep(0.05)
            if button_pin.value() == 0:
                print("BUTTON PRESSED")
                ped_request.set()
                normal_light.interrupt()
        await uasyncio.sleep(0.05)


async def main():
    normal = TrafficLight("normal", {"red": 14, "yellow": 13, "green": 12})
    pedestrian = TrafficLight("pedestrian", {"red": 11, "green": 10})
    button = machine.Pin(15, machine.Pin.IN, machine.Pin.PULL_UP)

    ped_request = uasyncio.Event()

    uasyncio.create_task(normal.run(ped_request))
    uasyncio.create_task(pedestrian.run(ped_request))
    uasyncio.create_task(button_task(button, ped_request, normal))

    while True:
        await uasyncio.sleep(1)


uasyncio.run(main())
