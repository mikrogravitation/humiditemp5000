import socket
import network
import wifi_secrets
import machine
import dht
import uos
import gc

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

sensor = dht.DHT22(machine.Pin(15))

while True:
    try:
        connection, peer = listener.accept()
        request = connection.recv(100)

        print(request)
        method, url, protocol = request.split(b"\r\n", 1)[0].split(b" ")
        path = url.split(b"/", 1)[1]
        print("incoming request: method {}, url {}, path {}, protocol {}".format(method, url, path, protocol))
        respond_404 = False

        if path == b"metrics":
            sensor.measure()
            response_body = """# HELP temperature The temperature at this sensor, in degrees Celsius
# TYPE temperature gauge
temperature {:.1f}

# HELP humidity The relative humidity at this sensor, in percent
# TYPE humidity gauge
humidity {:.1f}

# HELP wifi_rssi WiFi signal strength (RSSI)
# TYPE wifi_rssi gauge
wifi_rssi {}
""".format(sensor.temperature(), sensor.humidity(), wlan.status("rssi"))

            connection.send("HTTP/1.1 200 OK\r\nContent-Length: {}\r\nContent-Type: text/plain; version=0.0.4\r\n\r\n".format(len(response_body)) + response_body)

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

        connection.close()

    except:
        # I'd print an error, except that we don't have logging anyways.
        pass
