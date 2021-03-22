import hashlib

def _xor_key(key, pad):
    key += bytes(32) # extend key to 64 bytes
    padded_key = bytes(key_byte ^ pad for key_byte in key)
    return padded_key

def _inner_key(key):
    return _xor_key(key, 0x36)

def _outer_key(key):
    return _xor_key(key, 0x5c)

class HMAC:

    def __init__(self, key, initial=bytes()):
        self.key = key
        self.hasher = hashlib.sha256(_inner_key(key) + initial)

    def update(self, data):
        self.hasher.update(data)

    def digest(self):
        outer_hash = hashlib.sha256(_outer_key(self.key) + self.hasher.digest()).digest()
        return outer_hash
