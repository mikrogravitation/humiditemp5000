from machine import Pin
import utime

class IRQCounter:

    provides = ["count"]

    def __init__(self, port, trigger, cooldown):
        self.counter = 0
        self.last_trigger = utime.ticks_ms()

        def irq_handler(pin):
            if self.last_trigger + cooldown < utime.ticks_ms():
                self.counter += 1
                self.last_trigger = utime.ticks_ms()
                print("test")

        port.init(Pin.IN, None)
        port.irq(irq_handler, trigger)

    def readout(self):
        return {"count": self.counter}
