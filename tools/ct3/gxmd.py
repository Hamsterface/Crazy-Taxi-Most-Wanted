r"""Reader for Crazy Taxi 3 (PC) GXMD model banks (Media\bankNN.mdl).

Layout, reverse-engineered from the retail files (all little-endian):

  "GXMD" u16 version(3) u16 0x10
  vertex pools, back to back:
      u32  count | 0xDD000000            low 16 bits = vertex count
      u8   stride in dwords
      u8   component mask                0x01 pos f32x3, 0x02 normal (packed 11:11:10),
                                         0x04 colour, 0x10 uv f32x2 (last 8 bytes)
      u8   extra, u8 pad
      count * stride bytes
  objects (the car banks have 16, id = header >> 12):
      u32  id << 12 | 0x001
      u32  mesh count
      f32  centre[3], radius, half_extents[3]
      mesh records:
          +0x00 u32  flags, top byte 0xCC
          +0x04 f32  centre[3], radius, half_extents[3]
          +0x20 u32  material word, blend word, f32 alpha?, u32 diffuse, ambient, specular, ?, ?
          +0x40 u32  render state
          if flags & 0x8000 (textured):
          +0x44 u16  texture index into the matching .art, u16 texture flags
          then (at +0x48, or +0x44 when untextured) a display list of u32 tokens:
                0x00000011 state end / sync
                0x40000000, 0x400FFFFF            begin
                0x2000000N                         vertex format select
                0xC6000004                         (texture stage setup)
                0x3000000P u32 count u16[count]    triangle strip from vertex pool P, padded to 4
  Object 6 in the car banks has no mesh records: it is a hull (face normals + u16 quads on pool 1).
"""
import math
import struct
import sys
from dataclasses import dataclass, field

POOL_TAG = 0xDD


@dataclass
class Pool:
    offset: int
    count: int
    stride: int
    mask: int
    extra: int
    pos: list = field(default_factory=list)
    nrm: list = field(default_factory=list)
    uv: list = field(default_factory=list)
    col: list = field(default_factory=list)


@dataclass
class Mesh:
    offset: int
    flags: int
    centre: tuple
    radius: float
    material: tuple
    texture: int
    tex_flags: int
    diffuse: int
    strips: list = field(default_factory=list)  # (pool, [u16...])


@dataclass
class Object:
    offset: int
    id: int
    centre: tuple
    radius: float
    extents: tuple
    meshes: list = field(default_factory=list)


def decode_normal(v):
    """Xbox NORMPACKED3: signed 11:11:10."""
    def s(x, bits):
        if x & (1 << (bits - 1)):
            x -= 1 << bits
        return x / ((1 << (bits - 1)) - 1)
    return s(v & 0x7FF, 11), s((v >> 11) & 0x7FF, 11), s((v >> 22) & 0x3FF, 10)


def read_pools(d):
    pools = []
    o = 8
    while o + 8 <= len(d) and d[o + 3] == POOL_TAG and d[o + 2] == 0:
        count = struct.unpack_from("<H", d, o)[0]
        stride = d[o + 4] * 4
        p = Pool(o, count, stride, d[o + 5], d[o + 6])
        base = o + 8
        for i in range(count):
            r = base + i * stride
            p.pos.append(struct.unpack_from("<fff", d, r))
            k = 12
            if p.mask & 0x02:
                p.nrm.append(decode_normal(struct.unpack_from("<I", d, r + k)[0]))
                k += 4
            else:
                p.nrm.append((0.0, 1.0, 0.0))
            if p.mask & 0x04:
                p.col.append(struct.unpack_from("<I", d, r + k)[0])
            else:
                p.col.append(0xFFFFFFFF)
            p.uv.append(struct.unpack_from("<ff", d, r + stride - 8) if p.mask & 0x10 else (0.0, 0.0))
        pools.append(p)
        o = base + count * stride
    return pools, o


def _is_object_header(d, o):
    if o + 40 > len(d):
        return False
    w, n = struct.unpack_from("<II", d, o)
    if (w & 0xFFF) != 0x001 or w >= 0x10000 or not 0 < n < 512:
        return False
    f = struct.unpack_from("<7f", d, o + 8)
    return all(math.isfinite(x) and abs(x) < 1e4 for x in f) and f[3] > 0


def _read_mesh(d, o, end):
    flags = struct.unpack_from("<I", d, o)[0]
    centre = struct.unpack_from("<fff", d, o + 4)
    radius = struct.unpack_from("<f", d, o + 16)[0]
    material = struct.unpack_from("<8I", d, o + 0x20)
    if flags & 0x8000:  # textured: one extra texture word before the display list
        tex, tflags = struct.unpack_from("<HH", d, o + 0x44)
        p = o + 0x48
    else:
        tex, tflags = -1, 0
        p = o + 0x44
    m = Mesh(o, flags, centre, radius, material, tex, tflags, material[3])
    while p + 8 <= end:
        w = struct.unpack_from("<I", d, p)[0]
        if (w >> 24) == 0xCC and ((w >> 16) & 0xFF) == 0 and p != o:
            break  # next mesh
        if _is_object_header(d, p):
            break
        if (w >> 28) == 3 and (w & 0x0FFFFF00) == 0:
            cnt = struct.unpack_from("<I", d, p + 4)[0]
            if 0 < cnt < 0x10000 and p + 8 + cnt * 2 <= end:
                m.strips.append((w & 0xFF, list(struct.unpack_from("<%dH" % cnt, d, p + 8))))
                p += 8 + ((cnt * 2 + 3) & ~3)
                continue
        p += 4
    return m, p


def read_objects(d, start):
    objs = []
    o = start
    n = len(d)
    while o < n - 40:
        if not _is_object_header(d, o):
            o += 4
            continue
        w, cnt = struct.unpack_from("<II", d, o)
        f = struct.unpack_from("<7f", d, o + 8)
        ob = Object(o, w >> 12, f[0:3], f[3], f[4:7])
        p = o + 36
        if (struct.unpack_from("<I", d, p)[0] >> 24) != 0xCC:
            objs.append(ob)  # hull / non-mesh object, skip its payload
            o = p
            continue
        for _ in range(cnt):
            if p + 0x48 > n or (struct.unpack_from("<I", d, p)[0] >> 24) != 0xCC:
                break
            m, p = _read_mesh(d, p, n)
            ob.meshes.append(m)
        objs.append(ob)
        o = p
    return objs


def strip_to_tris(idx):
    tris = []
    for i in range(len(idx) - 2):
        a, b, c = idx[i], idx[i + 1], idx[i + 2]
        if a == b or b == c or a == c:
            continue
        tris.append((a, b, c) if i % 2 == 0 else (b, a, c))
    return tris


def load(path):
    d = open(path, "rb").read()
    if d[:4] != b"GXMD":
        raise ValueError("not a GXMD file: %s" % path)
    pools, end = read_pools(d)
    objs = read_objects(d, end)
    return d, pools, objs


def iter_strips(objs, ids=None):
    for ob in objs:
        if ids is not None and ob.id not in ids:
            continue
        for m in ob.meshes:
            for pool, idx in m.strips:
                yield ob, m, pool, idx


if __name__ == "__main__":
    d, pools, objs = load(sys.argv[1])
    for p in pools:
        print("pool @%#x count=%d stride=%d mask=%#x extra=%#x" % (p.offset, p.count, p.stride, p.mask, p.extra))
    for ob in objs:
        ns = sum(len(m.strips) for m in ob.meshes)
        print("object %2d @%#x meshes=%d strips=%d c=(%.2f %.2f %.2f) r=%.2f ext=(%.2f %.2f %.2f)" % (
            ob.id, ob.offset, len(ob.meshes), ns, *ob.centre, ob.radius, *ob.extents))
        for m in ob.meshes:
            print("    mesh @%#x flags=%#010x tex=%2d tflags=%#06x diffuse=%#010x strips=%s" % (
                m.offset, m.flags, m.texture, m.tex_flags, m.diffuse,
                [(pl, len(ix)) for pl, ix in m.strips]))
