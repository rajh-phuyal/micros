"""Traffic light state machine. Imported by main.py -- copy both to the board.

One class covers both roles, chosen by `kind`:

    "normal"      GREEN -> YELLOW -> RED, looping on a timer.
    "pedestrian"  sits at PED_RED until asked, then PED_GREEN and back.

The two coordinate through a single shared `uasyncio.Event` (`ped_request`):

    button press  ->  ped_request.set() + normal.interrupt()
    interrupt()   ->  cuts the normal light's current _sleep() short so it
                      advances to RED immediately instead of waiting out
                      the full 10s
    pedestrian    ->  wakes on the event, runs its sequence, then clears it,
                      which releases the normal light back into its loop

_sleep() polls a flag every 100ms rather than using a real cancellable timer;
that is the whole reason interrupt() works without task cancellation.
"""

import machine
import uasyncio


class TrafficLight:
    def __init__(self, kind, pins):
        self.kind = kind
        self.leds = {}
        for name, pin_num in pins.items():
            self.leds[name] = machine.Pin(pin_num, machine.Pin.OUT)

        self.state = "GREEN" if kind == "normal" else "PED_RED"
        self._interrupted = False
        self._apply_state()

    def _all_off(self):
        for led in self.leds.values():
            led.value(0)

    def _apply_state(self):
        self._all_off()
        if self.state == "GREEN":
            self.leds["green"].value(1)
        elif self.state == "YELLOW":
            self.leds["yellow"].value(1)
        elif self.state == "RED":
            self.leds["red"].value(1)
        elif self.state == "PED_RED":
            self.leds["red"].value(1)
        elif self.state == "PED_GREEN":
            self.leds["green"].value(1)
        print(f"{self.kind}: {self.state}")

    def set_state(self, new_state):
        self.state = new_state
        self._apply_state()

    def interrupt(self):
        self._interrupted = True

    async def _sleep(self, seconds):
        ticks = int(seconds / 0.1)
        for _ in range(ticks):
            if self._interrupted:
                self._interrupted = False
                return
            await uasyncio.sleep(0.1)

    async def _run_normal(self, ped_request):
        while True:
            self.set_state("GREEN")
            await self._sleep(10)
            if ped_request.is_set():
                self.set_state("YELLOW")
                await uasyncio.sleep(3)
                self.set_state("RED")
                while ped_request.is_set():
                    await uasyncio.sleep(0.1)
                continue

            self.set_state("YELLOW")
            await self._sleep(3)
            if ped_request.is_set():
                self.set_state("RED")
                while ped_request.is_set():
                    await uasyncio.sleep(0.1)
                continue

            self.set_state("RED")
            await self._sleep(10)
            if ped_request.is_set():
                while ped_request.is_set():
                    await uasyncio.sleep(0.1)
                continue

    async def _run_pedestrian(self, ped_request):
        while True:
            self.set_state("PED_RED")
            await ped_request.wait()

            await uasyncio.sleep(4)

            self.set_state("PED_GREEN")
            await uasyncio.sleep(5)

            self.set_state("PED_RED")
            await uasyncio.sleep(1.5)

            ped_request.clear()

    async def run(self, ped_request):
        if self.kind == "normal":
            await self._run_normal(ped_request)
        else:
            await self._run_pedestrian(ped_request)
