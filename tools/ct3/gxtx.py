r"""Reader for Crazy Taxi 3 (PC) texture banks (Media\bankNN.art).

  u32 count, u32 offset[count]
  per texture: "GXTX" u16 width u16 height u32 data_size u16 1 u16 pixel_format
               data_size bytes of 8- or 16-bit pixels, Xbox-swizzled, no mipmaps.
"""
import os
import struct
import sys

from PIL import Image

# pixel_format codes seen in the car banks. Verified visually (see tools/ct3/README).
FORMATS = {
    0: "ARGB1555",
    1: "ARGB4444",
    3: "I8",    # 8-bit intensity (light flares, grilles); used as both colour and alpha
    4: "A8L8",  # alpha in the high byte; seen with luminance 0 (shadow)
    5: "RGB565",
}
BYTES_PER_PIXEL = {"I8": 1}


def _expand(v, bits):
    return (v * 255 + ((1 << bits) - 1) // 2) // ((1 << bits) - 1)


def decode_pixel(p, fmt):
    if fmt == "RGB565":
        return (_expand(p >> 11 & 31, 5), _expand(p >> 5 & 63, 6), _expand(p & 31, 5), 255)
    if fmt == "ARGB1555":
        return (_expand(p >> 10 & 31, 5), _expand(p >> 5 & 31, 5), _expand(p & 31, 5), 255 if p & 0x8000 else 0)
    if fmt == "ARGB4444":
        return (_expand(p >> 8 & 15, 4), _expand(p >> 4 & 15, 4), _expand(p & 15, 4), _expand(p >> 12 & 15, 4))
    if fmt == "I8":
        return (p, p, p, p)
    if fmt == "A8L8":
        return (p & 255, p & 255, p & 255, p >> 8)
    raise ValueError(fmt)


def read(path):
    d = open(path, "rb").read()
    n = struct.unpack_from("<I", d, 0)[0]
    offs = struct.unpack_from("<%dI" % n, d, 4)
    out = []
    for o in offs:
        if d[o:o + 4] != b"GXTX":
            raise ValueError("bad texture at %#x" % o)
        w, h, size, _one, code = struct.unpack_from("<HHIHH", d, o + 4)
        out.append((w, h, code, d[o + 16:o + 16 + size]))
    return out


def swizzle_index(x, y, w, h):
    """Xbox swizzle: interleave x/y bits (x first) while both dimensions have bits left."""
    i = 0
    bit = 0
    mw, mh = w - 1, h - 1
    sx = sy = 0
    while mw or mh:
        if mw:
            i |= ((x >> sx) & 1) << bit
            bit += 1
            sx += 1
            mw >>= 1
        if mh:
            i |= ((y >> sy) & 1) << bit
            bit += 1
            sy += 1
            mh >>= 1
    return i


def to_image(w, h, code, data, fmt=None, swizzled=True):
    fmt = fmt or FORMATS.get(code, "RGB565")
    px = struct.unpack_from("<%d%s" % (w * h, "B" if BYTES_PER_PIXEL.get(fmt, 2) == 1 else "H"), data)
    if swizzled:
        px = [px[swizzle_index(x, y, w, h)] for y in range(h) for x in range(w)]
    img = Image.new("RGBA", (w, h))
    img.putdata([decode_pixel(p, fmt) for p in px])
    return img


def export(path, outdir):
    os.makedirs(outdir, exist_ok=True)
    names = []
    for i, (w, h, code, data) in enumerate(read(path)):
        name = "tex%02d.png" % i
        to_image(w, h, code, data).save(os.path.join(outdir, name))
        names.append(name)
    return names


if __name__ == "__main__":
    for i, (w, h, code, data) in enumerate(read(sys.argv[1])):
        print(i, w, h, code, FORMATS.get(code))
    if len(sys.argv) > 2:
        export(sys.argv[1], sys.argv[2])
