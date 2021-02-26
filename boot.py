import socket
import network
import wifi_secrets
import machine
import dht

def do_connect():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print('connecting to network...')
        wlan.connect(wifi_secrets.wifi_ssid, wifi_secrets.wifi_passphrase)
        while not wlan.isconnected():
            pass
    print('network config:', wlan.ifconfig())

do_connect()
listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
listener.bind(("0.0.0.0", 5000))
listener.listen(1)

sensor = dht.DHT22(machine.Pin(4))

while True:
    connection, peer = listener.accept()
    request = connection.recv(100)
    if request.startswith("GET /metrics"):
        sensor.measure()
        response_body = """# HELP temperature The temperature at this sensor, in degrees Celsius
# TYPE temperature gauge
temperature {:.1f}

# HELP humidity The relative humidity at this sensor, in percent
# TYPE humidity gauge
humidity {:.1f}
""".format(sensor.temperature(), sensor.humidity())

        connection.send("HTTP/1.1 200 OK\r\nContent-Length: {}\r\nContent-Type: text/plain; version=0.0.4\r\n\r\n".format(len(response_body)) + response_body)
    connection.close()
