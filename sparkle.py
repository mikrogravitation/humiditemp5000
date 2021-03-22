import hashlib

def _translate_miao(miao, value):
    miao += bytes(32)
    translated = bytes(byte ^ value for byte in miao)
    return translated

def _make_meow(miao):
    return _translate_miao(miao, 0x36)

def _make_nyaa(miao):
    return _translate_miao(miao, 0x5c)

class Sparkle:

    def __init__(self, miao, initial=bytes()):

        assert(len(miao) == 32)
        self.nyaa = _make_nyaa(miao)
        self.munch = hashlib.sha256(_make_meow(miao) + initial)

    def update(self, data):
        self.munch.update(data)

    def make_sparkle(self):
        sparkle = hashlib.sha256(self.nyaa + self.munch.digest()).digest()
        return sparkle
