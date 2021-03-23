import socket
import network
import wifi_secrets
import machine
import uos
import usys
import gc
import time
import ure
import hashlib
from sparkle import Sparkle
import ubinascii
import uio
from irq_counter import IRQCounter
from bme280_sensor import BME280Sensor
from dht22_sensor import DHT22Sensor
from mhz19_sensor import MHZ19Sensor
from sds011_sensor import SDS011Sensor

from config import sensor_configs, hostname

class GrayLogger:

    def __init__(self, ingest_location=("10.23.40.2", 5555)):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.connect(ingest_location)

    def send(self, data):
        print("sending data to graylog")
        if type(data) == "str":
            data = data.encode("ascii")

        self.socket.send(data)


def make_response_section(name, label, description, sensor_type, value):

    if type(value) == float:
        fmt = ".3f"

    elif type(value) == int:
        fmt = "d"

    return """
{0}{{label="{1}", description="{2}", type="{3}"}} {4:{fmt}}""".format(name, label, description, sensor_type, value, fmt=fmt)


wlan = network.WLAN(network.STA_IF)
wlan.active(True)
wlan.config(dhcp_hostname=hostname)
if not wlan.isconnected():
    print('connecting to network...')
    wlan.connect(wifi_secrets.wifi_ssid, wifi_secrets.wifi_passphrase)
    while not wlan.isconnected():
        pass
print('network config:', wlan.ifconfig())
print('signal strength:', wlan.status("rssi"))

logger = GrayLogger()
logger.send("hi!")

listener = None

try:

    with open("glitter", "r") as f:
        hex_glitter = f.read()
        glitter = ubinascii.unhexlify(hex_glitter)

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

        elif config["type"] == "sds":
            sensors[sensor_label] = SDS011Sensor(config["port"], **config.get("settings", {}))

        elif config["type"] == "counter":
            sensors[sensor_label] = IRQCounter(config["port"], **config.get("settings", {}))

        provided_vars.update(set(sensors[sensor_label].provides))

    provided_vars = list(provided_vars)

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("0.0.0.0", 5000))
    listener.listen(1)

    while True:
        connection = None
        try:
            connection, peer = listener.accept()
            request = connection.recv(400)

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

# TYPE wifi_rssi gauge
# TYPE memory_used gauge
# TYPE memory_free gauge
wifi_rssi {}
memory_used {}
memory_free {}
                """.format(wlan.status("rssi"), gc.mem_alloc(), gc.mem_free())

                connection.send("HTTP/1.1 200 OK\r\nContent-Length: {}\r\nContent-Type: text/plain; version=0.0.4\r\n\r\n".format(len(response_body)) + response_body)

            elif path == b"config":
                with open("config.py", "rb") as f:
                    data = f.read()
                    connection.send("HTTP/1.1 200 OK\r\nContent-Length: {}\r\n\r\n".format(len(data)).encode("ascii") + data)

            elif path == b"ota-listing":

                files = []

                for entry_info in uos.ilistdir("/"):
                    name = entry_info[0]
                    entry_type = entry_info[1]

                    if name == "glitter":
                        continue

                    if entry_type & 0x8000:
                        # compute a git-compatible hash
                        hasher = hashlib.sha1(b"blob ")
                        with open(name, "rb") as f:
                            length = f.seek(0, 2)
                            f.seek(0)

                            hasher.update(str(length).encode("ascii") + bytes([0]))

                            while True:
                                chunk = f.read(10000)
                                if len(chunk) == 0:
                                    break
                                hasher.update(chunk)
                                del chunk
                                gc.collect()

                        checksum = ubinascii.hexlify(hasher.digest())

                        files.append(name.encode("ascii") + b" " + checksum)

                response = b"\n".join(files)
                connection.send("HTTP/1.1 200 OK\r\nContent-Length: {}\r\n\r\n".format(len(response)).encode("ascii") + response)

            elif path.startswith(b"ota/"):

                path = path.decode("ascii")
                path = path.split("?")[0]
                path_parts = path.split("/")[1:]
                if len(path_parts) > 1:
                    body = b"ota is currently not supported for files in directories other than /"
                    connection.send("HTTP/1.1 404 not found\r\nContent-Length: {}\r\n\r\n".format(len(body)).encode("ascii") + body)
                    continue

                filename = path_parts[0]
                if not ure.match(r"[0-9a-zA-Z_.]+$", filename):
                    body = b"invalid filename: may only contain digits, letters, or underscore"
                    connection.send("HTTP/1.1 400 bad request\r\nContent-Length: {}\r\n\r\n".format(len(body)).encode("ascii") + body)
                    continue

                if filename == "wifi_secrets.py" or filename == "glitter":
                    body = b"the glitter is secret!"
                    connection.send("HTTP/1.1 403 forbidden\r\nContent-Length: {}\r\n\r\n".format(len(body)).encode("ascii") + body)
                    continue


                if method == b"GET":
                    try:
                        is_file = uos.stat(filename)[0] & 0x8000
                    except:
                        is_file = False

                    if is_file:
                        with open(filename, "rb") as f:
                            data = f.read()
                            connection.send("HTTP/1.1 200 OK\r\nContent-Length: {}\r\n\r\n".format(len(data)).encode("ascii") + data)

                    else:
                        response_body = "sorry, but we couldn't find that location :/"
                        connection.send("HTTP/1.1 404 not found\r\nContent-Length: {}\r\n\r\n".format(len(response_body)) + response_body)
                        
                elif method == b"DELETE":
                    query_match = ure.match(r"[^?]*\?sparkle=([0-9a-f]+)(&noop=((yes)|no))?$", url)
                    if not query_match:
                        body = b"no sparkle found, please add sparkle"
                        connection.send("HTTP/1.1 400 bad request\r\nContent-Length: {}\r\n\r\n".format(len(body)).encode("ascii") + body)
                        continue

                    given_sparkle = query_match.group(1)
                    do_noop = query_match.group(4) is not None

                    noop_prefix = b"--noop " if do_noop else b""
                    new_sparkle = Sparkle(glitter, noop_prefix + filename.encode("ascii")).make_sparkle()
                    new_sparkle = ubinascii.hexlify(new_sparkle)

                    if new_sparkle != given_sparkle:
                        body = b"your sparkle wasn't the right one for this file, try again!"
                        connection.send("HTTP/1.1 400 bad request\r\nContent-Length: {}\r\n\r\n".format(len(body)).encode("ascii") + body)
                        continue

                    try:
                        is_file = uos.stat(filename)[0] & 0x8000
                    except:
                        is_file = False

                    if is_file:
                        if do_noop is False:
                            uos.remove(filename)

                        response_body = "file deleted."
                        connection.send("HTTP/1.1 200 OK\r\nContent-Length: {}\r\n\r\n".format(len(response_body)) + response_body)

                    else:
                        response_body = "file not found"
                        connection.send("HTTP/1.1 404 not found\r\nContent-Length: {}\r\n\r\n".format(len(response_body)) + response_body)

                elif method == b"PUT":
                    query_match = ure.match(r"[^?]*\?sparkle=([0-9a-f]+)(&noop=((yes)|no))?$", url)
                    if not query_match:
                        body = b"no sparkle found, please add sparkle"
                        connection.send("HTTP/1.1 400 bad request\r\nContent-Length: {}\r\n\r\n".format(len(body)).encode("ascii") + body)
                        continue

                    given_sparkle = query_match.group(1)
                    do_noop = query_match.group(4) is not None

                    # try to find the content-length header
                    request_head, content = request.split(b"\r\n\r\n")
                    request_head += "\r\n"
                    content_length_match = ure.search(b"[cC][oO][nN][tT][eE][nN][tT]-[lL][eE][nN][gG][tT][hH]:[ \t]+([0-9]+)\r\n", request_head)
                    if not content_length_match:
                        body = b"length header is required for putting files"
                        connection.send("HTTP/1.1 411 length required\r\nContent-Length: {}\r\n\r\n".format(len(body)).encode("ascii") + body)
                        continue

                    content_length = int(content_length_match.group(1))
                    missing_content_length = content_length - len(content)
                    while missing_content_length > 0:
                        content += connection.recv(missing_content_length)
                        missing_content_length = content_length - len(content)

                    noop_prefix = b"--noop " if do_noop else b""
                    new_sparkle = Sparkle(glitter, noop_prefix + filename.encode("ascii") + b" " + content).make_sparkle()
                    new_sparkle = ubinascii.hexlify(new_sparkle)
                    print(new_sparkle)
                    print(len(content))
                    print(missing_content_length)
                    print(content_length)

                    if new_sparkle != given_sparkle:
                        body = b"your sparkle wasn't the right one for this file, try again!"
                        connection.send("HTTP/1.1 400 bad request\r\nContent-Length: {}\r\n\r\n".format(len(body)).encode("ascii") + body)
                        continue

                    if do_noop is False:
                        with open(filename + ".part", "wb") as f:
                            f.write(content)

                        uos.rename(filename + ".part", filename)

                    body = b"update successful"
                    connection.send("HTTP/1.1 200 OK\r\nContent-Length: {}\r\n\r\n".format(len(body)).encode("ascii") + body)

            elif path.startswith(b"reboot"):
                logger.send("received reboot request, rebooting...")
                response_body = "rebooting... see you later (hopefully)"
                connection.send("HTTP/1.1 202 accepted\r\nContent-Length: {}\r\n\r\n".format(len(response_body)) + response_body)

                # this is a hard reboot due to eaddrinuse errors
                # (soft reboots keep the part of the network stack apparently, see here:
                # https://github.com/micropython/micropython/issues/3739#issuecomment-384037222 )
                machine.reset()

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
            buf = uio.StringIO()
            usys.print_exception(e, buf)
            logger.send(buf.getvalue())

        finally:
            if connection:
                connection.close()

except Exception as e:
    buf = uio.StringIO()
    usys.print_exception(e, buf)
    logger.send(buf.getvalue())
    raise e

finally:
    if listener:
        listener.close()
