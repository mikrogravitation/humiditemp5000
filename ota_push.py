import socket
import sys
import json
import binascii
import hmac

with open("device_ota_keys.json") as f:
    ota_keys = json.load(f)

device = sys.argv[1]
filename = sys.argv[2]

key = binascii.unhexlify(ota_keys[device])

with open(filename, "rb") as f:
    file_contents = f.read()

hmac = binascii.hexlify(
        hmac.digest(key, filename.encode("ascii") + b" " + file_contents, "sha256")
       ).decode("ascii")

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.connect((device, 5000))

s.send("PUT /ota/{}?hmac={} HTTP/1.1\r\ncontent-length: {}\r\nhost: bla\r\n\r\n".format(
    filename,
    hmac,
    len(file_contents)).encode("ascii") + file_contents)

print(s.recv(1000).decode("ascii"))
s.close()
