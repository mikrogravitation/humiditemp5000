import socket
import network
import wifi_secrets
import machine
import uos
import usys
import gc
import time
from irq_counter import IRQCounter
from bme280_sensor import BME280Sensor
from dht22_sensor import DHT22Sensor
from mhz19_sensor import MHZ19Sensor

from config import sensor_configs

def make_response_section(name, label, description, sensor_type, value):

    if type(value) == float:
        fmt = ".3f"

    elif type(value) == int:
        fmt = "d"

    return """
{0}{{label="{1}", description="{2}", type="{3}"}} {4:{fmt}}""".format(name, label, description, sensor_type, value, fmt=fmt)

# extra 3.3v pin (for connecting two sensors at once)
machine.Pin(13, machine.Pin.OUT).on()

print("before sleep")

# wait for dht sensor to stabilize
time.sleep(2)

# initialize sensor objects
sensors = {}
provided_vars = set()
for sensor_label, config in sensor_configs.items():
    if config["type"] == "dht":
        sensors[sensor_label] = DHT22Sensor(config["port"], **config.get("settings", {}))
    
    elif config["type"] == "bme":
        sensors[sensor_label] = BME280Sensor(config["port"], **config.get("settings", {}))

    elif config["type"] == "mhz":
        sensors[sensor_label] = MHZ19Sensor(config["port"], **config.get("settings", {}))

    elif config["type"] == "counter":
        sensors[sensor_label] = IRQCounter(config["port"], **config.get("settings", {}))

    provided_vars.update(set(sensors[sensor_label].provides))

provided_vars = list(provided_vars)

wlan = network.WLAN(network.STA_IF)
wlan.active(True)
if not wlan.isconnected():
    print('connecting to network...')
    wlan.connect(wifi_secrets.wifi_ssid, wifi_secrets.wifi_passphrase)
    while not wlan.isconnected():
        pass
print('network config:', wlan.ifconfig())
print('signal strength:', wlan.status("rssi"))

listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
listener.bind(("0.0.0.0", 5000))
listener.listen(1)

while True:
    connection = None
    try:
        connection, peer = listener.accept()
        request = connection.recv(100)

        print(request)
        method, url, protocol = request.split(b"\r\n", 1)[0].split(b" ")
        path = url.split(b"/", 1)[1]
        print("incoming request: method {}, url {}, path {}, protocol {}".format(method, url, path, protocol))
        respond_404 = False

        if path == b"metrics":

            response_body = "".join("# TYPE {} gauge\n".format(var)
                    for var in provided_vars)

            for sensor_label in sensors.keys():
                sensor = sensors[sensor_label]
                sensor_config = sensor_configs[sensor_label]

                data = sensor.readout()

                for name, value in data.items():
                    response_body += make_response_section(
                            name,
                            sensor_label,
                            sensor_config["description"],
                            sensor_config["type"],
                            value)

            response_body += """
wifi_rssi {}
            """.format(wlan.status("rssi"))

            connection.send("HTTP/1.1 200 OK\r\nContent-Length: {}\r\nContent-Type: text/plain; version=0.0.4\r\n\r\n".format(len(response_body)) + response_body)

        elif path == b"config":
            with open("config.py", "rb") as f:
                data = f.read()
                connection.send("HTTP/1.1 200 OK\r\nContent-Length: {}\r\n\r\n".format(len(data)).encode("ascii") + data)

        else:
            
            file_found = False

            if path == b"":
                path = b"index.html"

            for entry_info in uos.ilistdir("webroot"):
                name = entry_info[0]
                print("iterating over files in the webroot: {}".format(name))
                if name.encode("ascii") == path:
                    with open("webroot/" + name, "rb") as f:
                        length = f.seek(0, 2)
                        f.seek(0)
                        connection.send("HTTP/1.1 200 OK\r\nContent-Length: {}\r\n\r\n".format(length).encode("ascii"))

                        # read the response in chunks, we don't have that much ram
                        while True:
                            chunk = f.read(10000)
                            if len(chunk) == 0:
                                break
                            connection.send(chunk)
                            del chunk
                            gc.collect()

                    file_found = True

            if not file_found:
                response_body = "sorry, but we couldn't find that location :/"
                connection.send("HTTP/1.1 404 not found\r\nContent-Length: {}\r\n\r\n".format(len(response_body)) + response_body)

    except KeyboardInterrupt as e:
        raise e

    except Exception as e:
        # I'd print an error, except that we don't have logging anyways.
        usys.print_exception(e)
        #raise e

    finally:
        if connection:
            connection.close()
