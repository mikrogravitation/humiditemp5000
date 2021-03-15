import bme280_float

class BME280Sensor:

    provides = ["temperature", "humidity", "pressure"]

    def __init__(self, port):

        self._sensor = bme280_float.BME280(
            i2c=port,
            filter_value=bme280_float.BME280_FILTER_OFF,
            pressure_oversampling=bme280_float.BME280_OSAMPLE_8,
            temperature_oversampling=bme280_float.BME280_OSAMPLE_1,
            humidity_oversampling=bme280_float.BME280_OSAMPLE_1
        )

    def readout(self):
        temperature, pressure, humidity = self._sensor.read_compensated_data()
        return {"temperature": temperature, "humidity": humidity, "pressure": pressure/100.}
