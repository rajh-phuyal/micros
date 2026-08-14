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
