from machine import Pin
import utime
#import pyb

class IRQCounter:

    provides = ["count", "time_since_last_trigger"]

    def __init__(self, port, trigger, cooldown):
        self.counter = 0
        self.last_trigger = utime.ticks_ms()

        def irq_handler(pin):
            now = utime.ticks_ms()
            if self.last_trigger + cooldown < now:
                self.counter += 1
                self.last_trigger = now

        port.init(Pin.IN, None)
        port.irq(irq_handler, trigger)

    def readout(self):

        irq_state = pyb.disable_irq()
        count = self.counter
        time_since_last_trigger = utime.ticks_ms() - self.last_trigger
        pyb.enable_irq(irq_state)

        return {"count": count, "time_since_last_trigger": time_since_last_trigger}
