"""JDLZ (EA LZ77) codec. decompress() is ported from MWSDK's src/jdlz.cpp (MIT).

Stream: "JDLZ" 02 10 00 00, u32 decompressed size, u32 compressed size (whole stream), then items.
Two flag bytes are read lazily, each time their 8 bits run out: f1 (one bit per item: 1 = match,
0 = literal) and f2 (one bit per *match*: 1 = near form, 0 = far form).
  near: b0 b1 -> length ((b0 & 0xF0) << 4 | b1) + 3 (3..4098), distance (b0 & 0x0F) + 1 (1..16)
  far:  b0 b1 -> length (b0 & 0x1F) + 3 (3..34), distance ((b0 & 0xE0) << 3 | b1) + 17 (17..2064)

The game decompresses texture blobs in place, so compressed blobs must be smaller than their output;
compress() is a real LZ77 encoder (greedy, hash chains) and in_place_safe() checks the overlap.
"""
import struct

MAGIC = b"JDLZ"
VERSION = 0x02
HEADER_SIZE = 0x10

NEAR_MAX_DIST, NEAR_MAX_LEN = 16, 4098
FAR_MIN_DIST, FAR_MAX_DIST, FAR_MAX_LEN = 17, 2064, 34
MIN_LEN = 3


def decompress(data, trace=None):
    if data[:4] != MAGIC or data[4] != VERSION:
        raise ValueError("not a JDLZ v2 stream")
    out_len = struct.unpack_from("<I", data, 8)[0]
    out = bytearray(out_len)
    pos, op, n = HEADER_SIZE, 0, len(data)
    f1 = f2 = 1
    while pos < n and op < out_len:
        if f1 == 1:
            f1 = data[pos] | 0x100
            pos += 1
        if f2 == 1:
            f2 = data[pos] | 0x100
            pos += 1
        if f1 & 1:
            b0, b1 = data[pos], data[pos + 1]
            pos += 2
            if f2 & 1:
                length = (((b0 & 0xF0) << 4) | b1) + 3
                dist = (b0 & 0x0F) + 1
            else:
                length = (b0 & 0x1F) + 3
                dist = (((b0 & 0xE0) << 3) | b1) + 17
            if dist > op:
                raise ValueError("JDLZ back-reference underflow")
            for _ in range(length):
                if op >= out_len:
                    break
                out[op] = out[op - dist]
                op += 1
            f2 >>= 1
        else:
            out[op] = data[pos]
            op += 1
            pos += 1
        f1 >>= 1
        if trace is not None:
            trace.append((pos, op))
    if op != out_len:
        raise ValueError("JDLZ size mismatch")
    return bytes(out)


def _find_match(raw, i, chains):
    n = len(raw)
    best_len, best_dist = 0, 0
    # near form: distances 1..16, long lengths (runs, repeated blocks)
    for dist in range(1, min(NEAR_MAX_DIST, i) + 1):
        l = 0
        lim = min(NEAR_MAX_LEN, n - i)
        while l < lim and raw[i + l] == raw[i + l - dist]:
            l += 1
        if l > best_len:
            best_len, best_dist = l, dist
            if l == lim:
                return best_len, best_dist
    # far form: distances 17..2064 via the 3-byte hash chain, lengths up to 34
    if i + MIN_LEN <= n:
        key = raw[i:i + MIN_LEN]
        for j in reversed(chains.get(key, ())[-64:]):
            dist = i - j
            if dist > FAR_MAX_DIST:
                break
            if dist < FAR_MIN_DIST:
                continue
            l = 0
            lim = min(FAR_MAX_LEN, n - i)
            while l < lim and raw[i + l] == raw[j + l]:
                l += 1
            if l > best_len:
                best_len, best_dist = l, dist
                if l == lim:
                    break
    return best_len, best_dist


def compress(raw):
    raw = bytes(raw)
    out = bytearray(MAGIC + bytes([VERSION, HEADER_SIZE, 0, 0]) + bytes(8))
    f1_pos = f2_pos = 0
    f1_bits = f2_bits = 8  # 8 = exhausted: the decoder reads a new flag byte before the next item
    chains = {}
    i, n = 0, len(raw)

    def index(k):
        if k + MIN_LEN <= n:
            chains.setdefault(raw[k:k + MIN_LEN], []).append(k)

    while i < n:
        if f1_bits == 8:
            f1_pos, f1_bits = len(out), 0
            out.append(0)
        if f2_bits == 8:
            f2_pos, f2_bits = len(out), 0
            out.append(0)
        length, dist = _find_match(raw, i, chains)
        if length >= MIN_LEN:
            out[f1_pos] |= 1 << f1_bits
            if dist <= NEAR_MAX_DIST:
                length = min(length, NEAR_MAX_LEN)
                v = length - 3
                out[f2_pos] |= 1 << f2_bits
                out += bytes([((v >> 4) & 0xF0) | (dist - 1), v & 0xFF])
            else:
                length = min(length, FAR_MAX_LEN)
                d = dist - 17
                out += bytes([((d >> 3) & 0xE0) | (length - 3), d & 0xFF])
            f2_bits += 1
            for k in range(i, i + length):
                index(k)
            i += length
        else:
            out.append(raw[i])
            index(i)
            i += 1
        f1_bits += 1
    # speed.exe's decoder (0x0064DB40) runs until its input counter hits exactly 0 and, after every
    # item, refills an exhausted f1 and then f2 flag byte. So the stream must end with those refill
    # bytes, or the game reads past the end, never reaches 0 and overruns its output (crash).
    if f1_bits == 8:
        out.append(0)
        if f2_bits == 8:
            out.append(0)
    elif f2_bits == 8 and n:
        out.append(0)
    struct.pack_into("<II", out, 8, n, len(out))
    return bytes(out)


def decompress_game(data):
    """Exact port of speed.exe v1.3's JDLZ decoder (0x0064DB40), including its termination rule.
    Raises if the stream would make the game read past its end or write past the output."""
    if data[:4] != MAGIC or data[4] != VERSION:
        raise ValueError("not a JDLZ v2 stream")
    out_len, comp = struct.unpack_from("<II", data, 8)
    out = bytearray(out_len)
    f1 = data[0x10] | 0x100
    f2 = data[0x11] | 0x100
    p, op = 0x12, 0
    left = comp - 0x12
    if left == 0:
        return bytes(out)
    while True:
        if left < 0 or p > len(data):
            raise ValueError("game decoder reads past the end of the stream")
        if f1 & 1:
            b0, b1 = data[p], data[p + 1]
            if f2 & 1:
                length = (((b0 & 0xF0) << 4) | b1) + 3
                dist = (b0 & 0x0F) + 1
            else:
                length = (b0 & 0x1F) + 3
                dist = (((b0 & 0xE0) << 3) | b1) + 0x11
            if op + length > out_len or dist > op:
                raise ValueError("game decoder writes outside the output at %d" % op)
            for _ in range(length):
                out[op] = out[op - dist]
                op += 1
            f2 >>= 1
            p += 2
            left -= 2
        else:
            if op < out_len:
                out[op] = data[p]
                op += 1
            p += 1
            left -= 1
        f1 >>= 1
        if f1 == 1:
            f1 = data[p] | 0x100 if p < len(data) else 0x100
            p += 1
            left -= 1
        if f2 == 1:
            f2 = data[p] | 0x100 if p < len(data) else 0x100
            p += 1
            left -= 1
        if left == 0:
            break
    if op != out_len:
        raise ValueError("game decoder produced %d of %d bytes" % (op, out_len))
    return bytes(out)


def in_place_safe(blob, margin=0):
    """True if decoding with the stream placed at the end of the output buffer never overwrites
    input it has not read yet (how the game decompresses texture blobs)."""
    usize = struct.unpack_from("<I", blob, 8)[0]
    base = usize + margin - len(blob)
    if base < 0:
        return False
    trace = []
    decompress(blob, trace)
    return all(op <= base + pos for pos, op in trace)


# Kept for reference: literal-only streams. Bigger than their input, so NOT loadable in place.
def encode_store(raw):
    out = bytearray(MAGIC + bytes([VERSION, HEADER_SIZE, 0, 0]) + bytes(8))
    for i, b in enumerate(raw):
        if i % 8 == 0:
            out.append(0)
            if i == 0:
                out.append(0)
        out.append(b)
    struct.pack_into("<II", out, 8, len(raw), len(out))
    return bytes(out)


encode = compress


if __name__ == "__main__":
    import os
    for blob in (os.urandom(1000) + bytes(5000), b"abc" * 3000, bytes(range(256)) * 40, b"x"):
        c = compress(blob)
        assert decompress(c) == blob
        assert decompress_game(c) == blob
        print("ok", len(blob), "->", len(c), "in-place safe:", in_place_safe(c))
