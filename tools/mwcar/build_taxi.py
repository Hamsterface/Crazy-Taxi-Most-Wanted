r"""Build NFS Most Wanted CARS\TAXI\GEOMETRY.BIN + TEXTURES.BIN from a Crazy Taxi 3 car export.

Usage: python -I build_taxi.py <export.json> <stock TAXI dir> <out dir>

The stock TAXI files are used as templates: every solid keeps its name, so the game's part
lookups still resolve, and shading groups are cloned from stock groups so the flag words we
do not understand stay valid. What goes where:

  TAXI_KIT00_BODY_A..E          opaque CT3 body (<= 14 texture slots, the stock maximum)
  TAXI_BASE_A..D                CT3 alpha-blended parts (lamps, chrome trim, roof sign), plus the
                                stock light markers moved onto CT3's lamps (see relocate_markers)
  TAXI_KIT00_FRONT_WINDOW_A..D  CT3 windshield
  TAXI_KIT00_FRONT_TIRE_A..E    CT3 wheel (the game mirrors it for the right side)
  TAXI_KIT00_DRIVER_A..C        collapsed to nothing (CT3 drivers are not in the car bank)

Formats (speed.exe v1.3), all reverse-engineered from the retail files:
  solid header 0x134011: +12 0x00400016, +16 bin(name), +20 tris, +24 (shaders<<16)|(textures<<8),
                         +32 bbox min f32x4, +48 bbox max f32x4, +64 matrix, +152 area, +156 tris/area, +160 name
  0x134012 / 0x134013: (u32 hash, u32 0) lists of texture / shader hashes (bin hash)
  0x134900 mesh header, 0x134B02 shading groups (104 B), 0x134B01 vertices (36 B), 0x134B03 u16 triangle list
  0x134C02 one material name per shading group
  0x13401A light markers (80 B: u32 hash, 12 zero bytes, 4x4 matrix with the position in the last row)
  BODY solids also carry 0x134017/18/19 vertex-damage tables; we write them empty.
"""
import json
import math
import os
import struct
import sys

from PIL import Image

sys.path.insert(0, os.path.dirname(__file__))
import eagl  # noqa: E402
import dxt  # noqa: E402
import jdlz  # noqa: E402

UNIT = 0.1  # CT3 decimetres -> metres


def binhash(s):
    h = 0xFFFFFFFF
    for ch in s.encode():
        h = (h * 33 + ch) & 0xFFFFFFFF
    return h


# Shader (light material) hashes from the stock TAXI body.
SHADER_BADGING = 0x02A05578  # diffuse texture with alpha, used for the taxi's badges (no depth write)
SHADER_OPAQUE = 0x0FEDEE40   # BODY_DULL_PLASTIC: plain opaque textured body part
SHADER_WINDOW = 0x1FF8C329   # WINDOW_TRAFFIC
SHADER_TIRE = 0x78743CA1     # TIRE_KIT00_SIDEWALL
SHADER_SIGN = 0xB51B3ACF     # HEADLIGHTREFLECTOR (stock headlight bulbs): 2x diffuse, almost no specular

# CT3 mesh flags: low nibble 0xF = alpha blended, 0x7 = opaque.
def is_alpha(flags):
    return (flags & 0x0F) == 0x0F




# ---------------------------------------------------------------- geometry helpers

# The NFS wheels stay where the player car's physics puts them, so the body is lowered instead until
# CT3's hub height lines up with them; that is how low Axel's car sits in Crazy Taxi. NFS_HUB_Z is
# where the hubs render in the body's frame, from the game (player car COBALTSS): real hub z -0.03,
# plus the mod's WheelHeight -0.22, minus the real car's body offset -3 in (-0.076, applied to the
# body only). RIDE_RAISE lifts the body above that if wanted. body_drop is set in main() from the
# CT3 wheel record.
NFS_HUB_Z = -0.03 - 0.22 + 0.076
RIDE_RAISE = 0.22
body_drop = 0.0
header_bbox_z_shift = 0.0  # diagnostic mode "bboxfix": solid header bboxes as if the body were not lowered


def ct_to_nfs(p):
    """CT3 body-space point -> NFS car space (body lowered by body_drop)."""
    x, y, z = p
    return (z * UNIT, x * UNIT, y * UNIT - body_drop)


def ct_nrm_to_nfs(n):
    x, y, z = n
    l = math.sqrt(x * x + y * y + z * z) or 1.0
    return (z / l, x / l, y / l)


def baked_shade(n):
    """Stock car vertex colours are baked shading by normal: ~230 facing up, ~145 sideways, ~45 down."""
    up = max(-1.0, min(1.0, n[2]))
    v = int(45 + (up + 1.0) * 0.5 * 185)
    return 0xFF000000 | (v << 16) | (v << 8) | v


class Group:
    """One shading group's worth of triangles with a single texture."""

    def __init__(self, texture_name, shader, material, template, colour=0xFF808080):
        self.colour = colour  # BADGING-style shaders treat 0x80 as neutral (stock badges sit at ~0x7C-0x83)
        self.texture = texture_name
        self.shader = shader
        self.material = material
        self.template = template  # 104-byte stock shading group to clone
        self.pos, self.nrm, self.uv, self.col, self.tris = [], [], [], [], []

    def add(self, pos, nrm, uv, tris):
        base = len(self.pos)
        self.pos += pos
        self.nrm += nrm
        self.uv += uv
        if self.colour is None:
            self.col += [baked_shade(n) for n in nrm]
        else:
            self.col += [self.colour] * len(pos)
        self.tris += [[base + i for i in t] for t in tris]


def tri_area(a, b, c):
    ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    cx, cy, cz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
    return 0.5 * math.sqrt(cx * cx + cy * cy + cz * cz)


def align_pad(abs_offset, align=16):
    return (-abs_offset) % align


# ---------------------------------------------------------------- solid builder

def build_solid(stock_obj, groups, keep_damage_chunks, markers=None):
    """Return a new 0x80134010 container replacing stock_obj's mesh with `groups`.
    `markers`, if given, replaces the stock 0x13401A marker list (the game's light flare positions)."""
    hdr = bytearray(stock_obj.find(0x134011).data)  # padding already stripped at load
    name = hdr[160:].split(b"\0")[0].decode()

    groups = [g for g in groups if g.tris]
    # 0x134012 (textures) and 0x134013 (shaders) are parallel lists in every stock solid: slot i is
    # texture i drawn with shader i, and a shading group uses the same index for both. A shorter
    # shader list makes the game skip the whole car.
    slots = []
    for g in groups:
        if (g.texture, g.shader) not in slots:
            slots.append((g.texture, g.shader))
    textures = [t for t, _ in slots]
    shaders = [s for _, s in slots]
    assert len(slots) <= 14, "%s: %d texture slots (max 14)" % (name, len(slots))

    verts = bytearray()
    idx = []
    sgs = bytearray()
    flags_or = 0
    allpos = []
    area = 0.0
    ntris = 0
    vbase = 0
    for g in groups:
        tpl = bytearray(g.template)
        mn = [min(p[k] for p in g.pos) for k in range(3)]
        mx = [max(p[k] for p in g.pos) for k in range(3)]
        struct.pack_into("<3f", tpl, 0, *mn)
        struct.pack_into("<3f", tpl, 12, *mx)
        ti = slots.index((g.texture, g.shader))
        tpl[24:29] = bytes([ti] * 5)
        tpl[29] = ti
        first = len(idx)
        for t in g.tris:
            idx += [vbase + i for i in t]
            area += tri_area(*(g.pos[i] for i in t))
        struct.pack_into("<III", tpl, 60, len(g.pos), len(g.tris), first)
        struct.pack_into("<I", tpl, 92, len(g.tris) * 3)
        flags_or |= struct.unpack_from("<I", tpl, 56)[0]
        sgs += tpl
        for p, n, c, uv in zip(g.pos, g.nrm, g.col, g.uv):
            verts += struct.pack("<3f3fI2f", *p, *n, c, *uv)
        allpos += g.pos
        ntris += len(g.tris)
        vbase += len(g.pos)
    if vbase > 0xFFFF:
        raise ValueError("%s: too many vertices for u16 indices" % name)

    # header
    mn = [min(p[k] for p in allpos) for k in range(3)]
    mx = [max(p[k] for p in allpos) for k in range(3)]
    struct.pack_into("<I", hdr, 20, ntris)
    old_flags = struct.unpack_from("<I", hdr, 24)[0]
    struct.pack_into("<I", hdr, 24, (old_flags & 0xFF0000FF) | (len(shaders) << 16) | (len(textures) << 8))
    struct.pack_into("<4f", hdr, 32, mn[0], mn[1], mn[2] + header_bbox_z_shift, 0.0)
    struct.pack_into("<4f", hdr, 48, mx[0], mx[1], mx[2] + header_bbox_z_shift, 0.0)
    area = max(area, 1e-4)
    struct.pack_into("<2f", hdr, 152, area, ntris / area)

    mesh_hdr_stock = stock_obj.find(0x80134100).find(0x134900).data
    mesh_hdr = bytearray(mesh_hdr_stock)
    struct.pack_into("<I", mesh_hdr, 12, flags_or)
    struct.pack_into("<I", mesh_hdr, 16, len(groups))
    struct.pack_into("<I", mesh_hdr, 44, len(idx))

    mesh = eagl.Chunk(0x80134100, children=[
        eagl.Chunk(0x134900, bytes(mesh_hdr)),
        eagl.Chunk(0x134B02, bytes(sgs)),
        eagl.Chunk(0x134B03, struct.pack("<%dH" % len(idx), *idx)),
        eagl.Chunk(0x134B01, bytes(verts)),
    ] + [eagl.Chunk(0x134C02, _material_name(g.material)) for g in groups])

    children = [
        eagl.Chunk(0x134011, bytes(hdr)),
        eagl.Chunk(0x134012, b"".join(struct.pack("<II", binhash(t), 0) for t in textures)),
        eagl.Chunk(0x134013, b"".join(struct.pack("<II", s, 0) for s in shaders)),
    ]
    if markers is not None:
        children.append(eagl.Chunk(0x13401A, markers))
    children.append(mesh)
    if keep_damage_chunks:
        children += [eagl.Chunk(0x134017, bytes(12)), eagl.Chunk(0x134018, b""), eagl.Chunk(0x134019, b"")]
    return eagl.Chunk(0x80134010, children=children), name


# ---------------------------------------------------------------- light markers

# 0x13401A: 80-byte records (u32 bin hash, 12 zero bytes, 4x4 f32 matrix whose last row is the
# position). speed.exe 0x74DF10 turns them into the car's light flares (brake, head, reverse);
# without them the car has no lights at all. The stock TAXI keeps them on TAXI_BASE_A..D.
MARKER_SIZE = 80
LIGHT_PUSH = 0.02  # m: sit the flare just outside the lens, not inside it


def find_lamps(parts):
    """Lamp centres (NFS metres) from CT3's lamp-lens meshes: {"head"|"brake": {+1|-1: [pos, ...]}}.
    CT3 keeps the lenses in the "brakelight" object: the rear lens mesh has three round lamps per side,
    all used as brake lights, and the front one two round headlights per side. Each lamp is its own
    connected piece of mesh (the two headlights nearly touch, so position gaps can't split them)."""
    lamps = {}
    for g in parts["brakelight"]:
        if not is_alpha(g["flags"]):
            continue  # the chrome housings
        rear = sum(p[2] for p in g["pos"]) < 0
        parent = list(range(len(g["pos"])))

        def root(a):
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a

        for t in g["tris"]:
            for b in t[1:]:
                parent[root(b)] = root(t[0])
        pieces = {}
        for i, p in enumerate(g["pos"]):
            pieces.setdefault(root(i), []).append(p)
        for side in (1, -1):  # CT3 +x = NFS +y = the car's left
            clusters = sorted((c for c in pieces.values() if c[0][0] * side > 0),
                              key=lambda c: abs(sum(p[0] for p in c)))
            if not clusters:
                continue

            def centre(c):  # middle of the lens across the car, just outside its outermost point
                _, y, z = ct_to_nfs([sum(p[k] for p in c) / len(c) for k in range(3)])
                tip = min(p[2] for p in c) if rear else max(p[2] for p in c)
                return (tip * UNIT - LIGHT_PUSH if rear else tip * UNIT + LIGHT_PUSH, y, z)

            lamps.setdefault("brake" if rear else "head", {})[side] = [centre(c) for c in clusters]
    return lamps


# Markers we place ourselves; the stock reverse markers are dropped for now (the taxi's inner tail
# lamp is a brake light), and anything else in the stock list is kept as it is.
MARKER_KINDS = {"head": "HEADLIGHT", "brake": "BRAKELIGHT"}
DROPPED_MARKERS = {binhash("LEFT_REVERSE"), binhash("RIGHT_REVERSE")}


def relocate_markers(stock_data, lamps):
    """Rebuild the stock marker list with one light marker per CT3 lamp. A name may repeat (the
    Corvette has two LEFT_BRAKELIGHTs), so each stock marker is cloned once per lamp it covers."""
    wanted = {binhash(("LEFT_" if side > 0 else "RIGHT_") + MARKER_KINDS[kind]): positions
              for kind, by_side in lamps.items() for side, positions in by_side.items()}
    assert len(stock_data) % MARKER_SIZE == 0, "unexpected marker list size %d" % len(stock_data)
    out = bytearray()
    for i in range(0, len(stock_data), MARKER_SIZE):
        rec = stock_data[i:i + MARKER_SIZE]
        h = struct.unpack_from("<I", rec, 0)[0]
        if h in DROPPED_MARKERS:
            continue
        if h not in wanted:
            out += rec
            continue
        for pos in wanted.pop(h):
            clone = bytearray(rec)  # keeps the stock orientation
            struct.pack_into("<3f", clone, 16 + 48, *pos)
            out += clone
    assert not wanted, "stock TAXI lacks markers %s" % sorted("%08x" % h for h in wanted)
    return bytes(out)


def collapse_solid(stock_obj):
    """Keep a stock solid but squash every vertex to one point so it draws nothing."""
    obj = eagl.Chunk(stock_obj.id, children=[_clone(c) for c in stock_obj.children])
    vb = obj.find(0x80134100).find(0x134B01)
    raw = bytearray(vb.data)
    # Every stock DRIVER vertex has a 12-byte position first; stride from the group vertex counts.
    sg = obj.find(0x80134100).find(0x134B02).data
    nverts = sum(struct.unpack_from("<I", sg, i * 104 + 60)[0] for i in range(len(sg) // 104))
    stride = len(raw) // nverts
    for i in range(nverts):
        struct.pack_into("<3f", raw, i * stride, 0.0, 0.0, -50.0)
    vb.data = bytes(raw)
    return obj


def _clone(c):
    return eagl.Chunk(c.id, c.data, [_clone(x) for x in c.children])


def _material_name(s):
    b = s.encode() + b"\0"
    return b + bytes((-len(b)) % 4)


# ---------------------------------------------------------------- serializer with alignment

# Leaf payloads that start on an aligned address, filled with 0x11 bytes (vertices: 128, rest: 16).
PADDED_LEAVES = {0x134011: 16, 0x13401A: 16, 0x134900: 16, 0x134B01: 128, 0x134B02: 16, 0x134B03: 16}


def serialize_geometry(root_children):
    """Serialize the top-level 0x80134000 container, re-inserting alignment padding."""
    out = bytearray()

    def emit(chunks, at_top=False):
        for k, c in enumerate(chunks):
            nxt = chunks[k + 1] if k + 1 < len(chunks) else None
            if c.id == 0 and (nxt is None or nxt.id == 0x80134010):
                continue  # alignment padding before a solid (or trailing): regenerated below
            if c.id == 0x80134010:
                # containers start 128-aligned: insert an id-0 padding chunk if needed
                gap = (-len(out)) % 128
                if gap:
                    if gap < 8:
                        gap += 128
                    out.extend(struct.pack("<II", 0, gap - 8))
                    out.extend(bytes(gap - 8))
            start = len(out)
            out.extend(struct.pack("<II", c.id, 0))
            if c.is_container:
                emit(c.children)
            else:
                if c.id in PADDED_LEAVES:  # payload is unpadded here; add the 0x11 fill
                    out.extend(b"\x11" * align_pad(len(out), PADDED_LEAVES[c.id]))
                out.extend(c.data)
            struct.pack_into("<I", out, start + 4, len(out) - start - 8)

    emit(root_children, True)
    # Stock files end with ~root/64 + 281 bytes of zero slack (fit over every stock car, max error
    # 13 bytes), then align to 64. The loader allocates the whole file; we leave a little more.
    root_end = len(out)
    total = root_end + root_end // 64 + 512
    total += (-total) % 64
    out.extend(struct.pack("<II", 0, total - root_end - 8) + bytes(total - root_end - 8))
    return out


def strip_stock_padding(chunks):
    """Remove the 0x11 alignment fill from stock padded leaves (it is regenerated on write)."""
    for c in chunks:
        if c.is_container:
            strip_stock_padding(c.children)
        elif c.id in PADDED_LEAVES:
            n = align_pad(c.offset, PADDED_LEAVES[c.id])
            if c.data[:n] != b"" * n:
                raise ValueError("unexpected padding in chunk %#x at %#x" % (c.id, c.offset))
            c.data = c.data[n:]


def fix_index_tables(buf):
    """Rewrite 0x134003/0x134004 (solid hash -> offset/size) and the total size in 0x134002."""
    solids = {}
    o = 8
    end = 8 + struct.unpack_from("<I", buf, 4)[0]
    while o < end:
        cid, size = struct.unpack_from("<II", buf, o)
        if cid == 0x80134010:
            p = o + 8
            hid, hsize = struct.unpack_from("<II", buf, p)
            hd = buf[p + 8:p + 8 + hsize].lstrip(b"\x11")
            solids[struct.unpack_from("<I", hd, 16)[0]] = (o, size + 8)
        o += 8 + size
    keys = sorted(solids)
    for cid, payload in ((0x134003, b"".join(struct.pack("<II", k, 0) for k in keys)),
                         (0x134004, b"".join(struct.pack("<6I", k, solids[k][0], solids[k][1], solids[k][1], 0, 0)
                                             for k in keys))):
        p = _find_leaf(buf, cid)
        n = struct.unpack_from("<I", buf, p + 4)[0]
        if n != len(payload):
            raise ValueError("solid table size changed (%#x)" % cid)
        buf[p + 8:p + 8 + n] = payload
    p = _find_leaf(buf, 0x134002)
    struct.pack_into("<I", buf, p + 8 + 12, len(keys))
    struct.pack_into("<I", buf, p + 8 + 0x68, len(buf))  # total file size


def _find_leaf(buf, cid):
    o = 8
    hdr = buf.find(struct.pack("<I", 0x80134001))
    size = struct.unpack_from("<I", buf, hdr + 4)[0]
    o = hdr + 8
    while o < hdr + 8 + size:
        c, n = struct.unpack_from("<II", buf, o)
        if c == cid:
            return o
        o += 8 + n
    raise KeyError(hex(cid))


# ---------------------------------------------------------------- texture pack builder

# Entry + trailer templates copied byte for byte from stock textures (speed.exe v1.3 data):
#   DXT1: CARS\TAXI TAXI_SKIN1 (opaque).  DXT3: CARS\911GT2 911GT2_BADGING (alpha-blended badge).
# Only name, hashes, buffer offsets, size and dimensions are changed.
_TPL_DXT1 = bytes.fromhex(
    "000000000000000000000000" "544158495f534b494e310000000000000000000000000000" "fa81526f" "b0e7811b"
    "00000000" "00600000" "00a00000" "00400000" "00000000" "00400000" "00018000" "08072200" "00000100" "00000000"
    "00000001" "00010000" "00000000" "00000001" "00010000" + "00000000" * 5)
_TRL_DXT1 = bytes.fromhex("00000000" "00000000" "00000000" "05000000" "06000000" "44585431" "00000000" "00000000")
_TPL_DXT3 = bytes.fromhex(
    "000000000000000000000000" "3931314754325f42414447494e4700000000000000000000" "92bace4f" "cf931a00"
    "00000000" "00900000" "00900100" "00000100" "00000000" "00000100" "00010001" "08082400" "00000100" "00050000"
    "01020100" "00010000" "00000000" "00000001" "00010000" + "00000000" * 5)
_TRL_DXT3 = bytes.fromhex("00000000" "00000000" "01000000" "05000000" "06000000" "44585433" "00000000" "00000000")
assert len(_TPL_DXT1) == 124 and len(_TPL_DXT3) == 124


MIN_TEXTURE_SIDE = 32


def texture_raw(name, img):
    """One TPK texture payload: DXT pixels + 124-byte entry + 32-byte trailer (slice offsets set later)."""
    w, h = img.size
    assert w & (w - 1) == 0 and h & (h - 1) == 0, "power-of-two only"
    # No stock car texture has a side under 32 px; smaller ones make the car fail to draw.
    # Nearest-neighbour upscaling keeps the look, and UVs are proportional so nothing else changes.
    if min(w, h) < MIN_TEXTURE_SIDE:
        k = MIN_TEXTURE_SIDE // min(w, h)
        img = img.resize((w * k, h * k), Image.NEAREST)
        w, h = img.size
    alpha = img.convert("RGBA").getextrema()[3][0] < 250
    fmt = "DXT3" if alpha else "DXT1"
    pix = dxt.encode(img, fmt)
    size = len(pix)
    e = bytearray(_TPL_DXT3 if alpha else _TPL_DXT1)
    trailer = _TRL_DXT3 if alpha else _TRL_DXT1
    e[12:36] = bytes(24)
    nm = name.encode()[:23]
    e[12:12 + len(nm)] = nm
    struct.pack_into("<I", e, 36, binhash(name))
    struct.pack_into("<III", e, 48, 0, size, size)
    struct.pack_into("<I", e, 64, size)
    struct.pack_into("<HHBB", e, 68, w, h, int(math.log2(w)), int(math.log2(h)))
    return binhash(name), bytes(pix) + bytes(e) + trailer


def build_tpk(stock_path, new_textures, keep_stock=False):
    """Return a TEXTURES.BIN with `new_textures` [(name, PIL image)], optionally keeping the stock ones."""
    stock = open(stock_path, "rb").read()
    top = eagl.parse(stock)[0]
    info = top.find(0xB3310000)
    data = top.find(0xB3320000)
    desc = info.find(0x33310003).data
    # Every texture owns a slice of one shared pixel buffer. In all stock packs those slices are
    # contiguous in hash order with no gaps (checked on GTI, CLIO, COPMIDSIZE, TAXI), so lay them
    # out exactly like that. HUFF blobs can't be re-encoded: their slice is baked in, so they must
    # keep their stock position (new texture names are picked to hash after them, see pick_name).
    items = []  # (hash, kind, payload, usize)
    for i in range(len(desc) // 24 if keep_stock else 0):
        h, off, size, usize, _, _ = struct.unpack_from("<6I", desc, i * 24)
        blob = stock[off:off + size]
        if blob[:4] == b"JDLZ":
            items.append((h, "raw", jdlz.decompress(blob), usize))
        else:
            items.append((h, "fixed", blob, usize))
    for name, img in new_textures:
        h, raw = texture_raw(name, img)
        items.append((h, "raw", raw, len(raw)))
    items.sort(key=lambda x: x[0])
    blobs = []
    pool = 0
    for h, kind, payload, usize in items:
        if kind == "fixed":
            blobs.append((h, payload, usize, 0x100, 0))
        else:
            raw = bytearray(payload)
            e = len(raw) - 156
            size = struct.unpack_from("<I", raw, e + 56)[0]
            struct.pack_into("<II", raw, e + 48, pool, pool + size)
            blob = jdlz.compress(bytes(raw))
            assert jdlz.decompress(blob) == bytes(raw)
            assert jdlz.decompress_game(blob) == bytes(raw), "blob would crash the game decoder"
            blobs.append((h, blob, usize, 0x100, 0))
        pool += usize - 156
    hashes = [b[0] for b in blobs]
    assert len(set(hashes)) == len(hashes), "texture hash collision"

    def assemble(offsets):
        info_new = eagl.Chunk(0xB3310000, children=[
            info.find(0x33310001),
            eagl.Chunk(0x33310002, b"".join(struct.pack("<II", h, 0) for h in hashes)),
            eagl.Chunk(0x33310003, b"".join(struct.pack("<6I", h, offsets[i], len(bl), us, a, b_)
                                            for i, (h, bl, us, a, b_) in enumerate(blobs))),
        ])
        out = bytearray()
        # container header + padding chunk + info
        out += struct.pack("<II", 0xB3300000, 0)
        out += struct.pack("<II", 0, 0x30) + bytes(0x30)
        out += eagl.serialize([info_new])
        gap = (-(len(out) + 8)) % 0x80  # data container starts 128-aligned
        out += struct.pack("<II", 0, gap) + bytes(gap)
        d_start = len(out)
        out += struct.pack("<II", 0xB3320000, 0)
        out += eagl.serialize([data.find(0x33320001)])
        gap = (-(len(out) + 8)) % 0x80  # raw data chunk header 128-aligned
        out += struct.pack("<II", 0, gap) + bytes(gap)
        raw_start = len(out)
        out += struct.pack("<II", 0x33320002, 0)
        placed = []
        for _, bl, _, _, _ in blobs:
            out += b"\x11" * ((-len(out)) % 0x40)
            placed.append(len(out))
            out += bl
        out += b"\x11" * ((-len(out)) % 0x80)  # stock packs end 128-aligned
        struct.pack_into("<I", out, raw_start + 4, len(out) - raw_start - 8)
        struct.pack_into("<I", out, d_start + 4, len(out) - d_start - 8)
        struct.pack_into("<I", out, 4, len(out) - 8)
        return out, placed

    out, placed = assemble([0] * len(blobs))
    out, placed2 = assemble(placed)
    assert placed == placed2
    return bytes(out)


# ---------------------------------------------------------------- CT3 -> groups

def env_uv(n_ct):
    """Bake CT3's sphere-mapped body shading: up-facing = top of the env texture."""
    x, y, z = n_ct
    l = math.sqrt(x * x + y * y + z * z) or 1.0
    return (0.5 + 0.45 * (x / l), 0.5 - 0.45 * (y / l))


# The car loader only streams a car's textures whose names it builds itself from patterns in
# speed.exe ("%s_SKIN1", "%s_BADGING", ... with %s = the car type, table at 0x8B4D9C..0x8B5048).
# Anything else in CARS\TAXI\TEXTURES.BIN is never loaded and the car is not drawn. So every
# CT3 texture must travel under one of these names. The function at 0x751870 hashes each name and
# appends it to the car's load list (up to 87); SKIN1 and SKIN1B go to dedicated skin fields instead,
# and only SKIN1 is proven to load, so SKIN1B is not used. Left out: the _N / _EU variants, SHADOW, NEON,
# RIM_BLUR and LICENSE_PLATE, which the game may treat specially.
# Names used, safest first. SKIN1 is the one proven in game (it must look like a stock skin: 256x128
# DXT1, opaque). SKIN2-4, TIRE/TREAD/RIM and SIDELIGHT are avoided: loading CT3 textures under them
# crashed the game in the loading screen (likely the paint / wheel compositing), so only generic names
# from the load list are used for everything else.
SKIN_SLOT = "SKIN1"
SKIN_SIZE = (256, 128)
TEXTURE_SLOTS = ["MISC", "INTERIOR", "BADGING", "ENGINE", "LOGO", "DOOR_HANDLE", "DRIVER"]
ATLAS_WIDTH = 256
ATLAS_MAX_HEIGHT = 512
ATLAS_PAD = 4


def _uv_range(groups):
    us = [u for g in groups for u, _ in g.uv]
    vs = [v for g in groups for _, v in g.uv]
    return min(us), max(us), min(vs), max(vs)


def _outside(lo, hi):
    return lo < -0.02 or hi > 1.02


def _pad_edge(img, pad, axes="xy"):
    import numpy as np
    a = np.asarray(img.convert("RGBA"))
    px = pad if "x" in axes else 0
    py = pad if "y" in axes else 0
    return Image.fromarray(np.pad(a, ((py, py), (px, px), (0, 0)), mode="edge"), "RGBA")


def has_alpha(img):
    return img.convert("RGBA").getextrema()[3][0] < 250


def assign_texture_slots(groups, images, skin_key, car="TAXI"):
    """Opaque and see-through textures never share an atlas: a DXT3 (alpha) texture makes NFS draw
    every surface using it in the translucent pass without depth writes."""
    names = iter("%s_%s" % (car, s) for s in TEXTURE_SLOTS)
    opaque = [g for g in groups if g.texture == skin_key or not has_alpha(images[g.texture])]
    clear = [g for g in groups if g not in opaque]
    out = _assign(opaque, images, skin_key, car, names)
    if clear:
        out += _assign(clear, images, None, car, names)
    return out


def _assign(groups, images, skin_key, car, names):
    """groups: every Group; their .texture is a placeholder key into `images` (key -> PIL image).
    Renames textures to the car's slot names (UVs remapped) and returns [(name, image)].
      skin_key            -> <car>_SKIN1 on its own, as a stock-shaped opaque 256x128 skin
      tiles in u only     -> stacked as full-width bands of one atlas (u still wraps)
      tiles in both       -> its own slot
      no tiling           -> shelf-packed atlases"""
    users = {}
    for g in groups:
        users.setdefault(g.texture, []).append(g)
    keys = sorted(users, key=lambda k: -images[k].size[0] * images[k].size[1])
    both, u_only, packed = [], [], []
    for k in keys:
        if k == skin_key:
            continue
        u0, u1, v0, v1 = _uv_range(users[k])
        if _outside(v0, v1):
            both.append(k)
        elif _outside(u0, u1):
            u_only.append(k)
        else:
            packed.append(k)

    out = []

    def take():
        try:
            return next(names)
        except StopIteration:
            raise ValueError("ran out of texture slot names") from None

    # SKIN1
    if skin_key is None:
        skin_key = "#none"
        users[skin_key] = []
        images = dict(images, **{skin_key: Image.new("RGBA", (1, 1))})
    skin = images[skin_key].convert("RGB").resize(SKIN_SIZE, Image.BILINEAR).convert("RGBA")
    for g in users[skin_key]:
        g.texture = "%s_%s" % (car, SKIN_SLOT)
    if users[skin_key]:
        out.append(("%s_%s" % (car, SKIN_SLOT), skin))

    for k in both:
        name = take()
        for g in users[k]:
            g.texture = name
        out.append((name, images[k]))

    if u_only:  # full-width bands, padded vertically only
        bands = []
        y = 0
        for k in u_only:
            w, h = images[k].size
            img = images[k].resize((ATLAS_WIDTH, h), Image.NEAREST if w < ATLAS_WIDTH else Image.BILINEAR)
            bands.append((k, y, img))
            y += h + 2 * ATLAS_PAD
        H = 1 << max(5, (y - 1).bit_length())
        name = take()
        atlas = Image.new("RGBA", (ATLAS_WIDTH, H), (0, 0, 0, 255))
        for k, by, img in bands:
            atlas.paste(_pad_edge(img, ATLAS_PAD, "y"), (0, by))
            h = img.size[1]
            for g in users[k]:
                g.texture = name
                g.uv = [(u, (by + ATLAS_PAD + min(max(v, 0.0), 1.0) * h) / H) for u, v in g.uv]
        out.append((name, atlas))

    # Shelf-pack the non-tiling textures into ATLAS_WIDTH-wide atlases.
    atlases = []  # [(placements {key: (x, y)}, height)]
    cur, x, y, shelf = {}, 0, 0, 0
    for k in sorted(packed, key=lambda k: -images[k].size[1]):
        w, h = (d + 2 * ATLAS_PAD for d in images[k].size)
        if x + w > ATLAS_WIDTH:
            x, y, shelf = 0, y + shelf, 0
        if y + h > ATLAS_MAX_HEIGHT:
            atlases.append((cur, y))
            cur, x, y, shelf = {}, 0, 0, 0
        cur[k] = (x, y)
        x += w
        shelf = max(shelf, h)
    if cur:
        atlases.append((cur, y + shelf))
    for placements, height in atlases:
        name = take()
        H = 1 << max(5, (height - 1).bit_length())
        atlas = Image.new("RGBA", (ATLAS_WIDTH, H), (0, 0, 0, 255))
        for k, (ax, ay) in placements.items():
            atlas.paste(_pad_edge(images[k], ATLAS_PAD), (ax, ay))
            w, h = images[k].size
            for g in users[k]:
                g.texture = name
                g.uv = [((ax + ATLAS_PAD + min(max(u, 0.0), 1.0) * w) / ATLAS_WIDTH,
                         (ay + ATLAS_PAD + min(max(v, 0.0), 1.0) * h) / H) for u, v in g.uv]
        out.append((name, atlas))
    return out


SWATCH = "#SWATCH"
SWATCH_ALPHA = "#SWATCHA"


def main(export_json, stock_dir, out_dir, mode=""):
    """mode "stocktex": diagnostic build that points every part at the stock TAXI_SKIN1 texture.
    mode "nodrop": diagnostic build with the body at CT3's own height (not lowered onto the wheels).
    mode "bboxfix": body lowered, but solid header bounding boxes left where they would be without it."""
    meta = json.load(open(export_json))
    tex_dir = os.path.dirname(export_json)
    stock_geo = eagl.parse(open(os.path.join(stock_dir, "GEOMETRY.BIN"), "rb").read())
    strip_stock_padding(stock_geo)
    root = stock_geo[0]
    solids = {}
    for obj in root.find_all(0x80134010):
        h = obj.find(0x134011).data.lstrip(b"\x11")
        solids[h[160:].split(b"\0")[0].decode()] = obj

    def stock_group(solid, i):
        sg = solids[solid].find(0x80134100).find(0x134B02).data
        return sg[i * 104:(i + 1) * 104]

    tpl_badging = stock_group("TAXI_KIT00_BODY_A", 4)   # BADGING
    tpl_opaque = stock_group("TAXI_KIT00_BODY_A", 0)    # BODY_DULL_PLASTIC
    tpl_window = stock_group("TAXI_KIT00_FRONT_WINDOW_A", 0)
    tpl_tire = stock_group("TAXI_KIT00_FRONT_TIRE_A", 0)

    new_textures = []

    images = {}

    def texname(i):
        key = "#CT%02d" % i
        if key not in images:
            images[key] = Image.open(os.path.join(tex_dir, meta["textures"][i]["file"])).convert("RGBA")
        return key

    def resolve(t, tex_flags, uv, tris):
        """Texture key + UVs for one CT3 mesh. CT3 texture flags 0x80 / 0x100 mean mirrored repeat in
        U / V (NFS only wraps), so the mirror is baked into a doubled texture and the UVs halved.
        A mesh counts as see-through only if texels it actually samples are transparent; otherwise it
        gets an alpha-free copy (a DXT3 texture would put it in NFS's translucent pass)."""
        import numpy as np
        mu, mv = bool(tex_flags & 0x80), bool(tex_flags & 0x100)
        base = images.get("#CT%02d" % t) or Image.open(os.path.join(tex_dir, meta["textures"][t]["file"])).convert("RGBA")
        img = base
        if mu:
            img = Image.fromarray(np.hstack([np.asarray(img), np.asarray(img)[:, ::-1]]), "RGBA")
            uv = [(u / 2, v) for u, v in uv]
        if mv:
            img = Image.fromarray(np.vstack([np.asarray(img), np.asarray(img)[::-1]]), "RGBA")
            uv = [(u, v / 2) for u, v in uv]
        a = np.asarray(img)[..., 3]
        h, w = a.shape

        def alpha_at(u, v):
            return a[int((v % 1.0) * h) % h, int((u % 1.0) * w) % w]

        samples = []
        for t0, t1, t2 in tris:
            p = [uv[t0], uv[t1], uv[t2]]
            samples.append(((p[0][0] + p[1][0] + p[2][0]) / 3, (p[0][1] + p[1][1] + p[2][1]) / 3))
            for i, j in ((0, 1), (1, 2), (2, 0)):
                samples.append(((p[i][0] + p[j][0]) / 2, (p[i][1] + p[j][1]) / 2))
        clear = any(alpha_at(u, v) < 250 for u, v in samples)
        key = "#CT%02d%s%s%s" % (t, "mu" if mu else "", "mv" if mv else "", "a" if clear else "o")
        if key not in images:
            if not clear:
                arr = np.asarray(img).copy()
                arr[..., 3] = 255
                img = Image.fromarray(arr, "RGBA")
            images[key] = img
        return key, uv, clear

    # Untextured CT3 materials get a texel each in a small swatch texture.
    swatches = {SWATCH: [], SWATCH_ALPHA: []}  # opaque and translucent colours never share a texture

    def swatch_uv(key, argb):
        lst = swatches[key]
        if argb not in lst:
            lst.append(argb)
        k = lst.index(argb)
        return ((k % 4 + 0.5) / 4, (k // 4 + 0.5) / 4)

    body, base, window, tire = {}, {}, {}, {}

    def group_for(bucket, key, tex, shader, mat, tpl, colour=None):
        if key not in bucket:
            if shader == SHADER_TIRE:
                colour = 0xFFFFFFFF
            bucket[key] = Group(tex, shader, mat, tpl, colour)  # colour None: baked shading
        return bucket[key]

    global body_drop, header_bbox_z_shift
    body_drop = 0.0 if mode == "nodrop" else meta["car"]["wheels"]["FL"][1] * UNIT - NFS_HUB_Z - RIDE_RAISE
    if mode == "bboxfix":
        header_bbox_z_shift = body_drop
    print("  body lowered %.3f m (CT3 hub height on the NFS wheels, raised %.2f m)" % (body_drop, RIDE_RAISE))

    # Roof sign: CT3 draws the lit one unshaded. NFS has no unlit car material, so the closest is
    # flat full-white vertex colours (no baked shading) with the headlight-bulb material.
    for g in meta["parts"].get("sign", []):
        name, uv, _ = resolve(g["texture"], g.get("tex_flags", 0), [tuple(x) for x in g["uv"]], g["tris"])
        grp = group_for(body, "sign:" + name, name, SHADER_SIGN, "BODY_MISC", tpl_opaque, 0xFFFFFFFF)
        grp.add([ct_to_nfs(p) for p in g["pos"]], [ct_nrm_to_nfs(n) for n in g["nrm"]], uv, g["tris"])

    for part in ("body", "brakelight"):
        for g in meta["parts"][part]:
            pos = [ct_to_nfs(p) for p in g["pos"]]
            nrm = [ct_nrm_to_nfs(n) for n in g["nrm"]]
            t = g["texture"]
            if t < 0:  # untextured: CT3 material colour from a swatch texel
                colour = g.get("diffuse", 0xFF333333)
                name = SWATCH if colour >> 24 >= 250 else SWATCH_ALPHA
                uv = [swatch_uv(name, colour)] * len(pos)
            elif all(u == 0 and v == 0 for u, v in g["uv"]):
                name, uv, _ = resolve(t, 0, [env_uv(n) for n in g["nrm"]], g["tris"])
            else:
                name, uv, _ = resolve(t, g.get("tex_flags", 0), [tuple(x) for x in g["uv"]], g["tris"])
            if t < 0 and g["flags"] & 0x40:  # the windshield: untextured, double-sided glass
                grp = group_for(window, name, name, SHADER_WINDOW, "WINDOW_TRAFFIC", tpl_window)
            elif name == SWATCH_ALPHA or (name != SWATCH and has_alpha(images[name])):  # see-through: decal
                grp = group_for(base, name, name, SHADER_BADGING, "BADGING", tpl_badging)
            else:
                grp = group_for(body, name, name, SHADER_OPAQUE, "BODY_DULL_PLASTIC", tpl_opaque)
            grp.add(pos, nrm, uv, g["tris"])
            if g["flags"] & 0x40:  # CT3 double-sided mesh (windshield, its frame, gauges); NFS culls back faces
                grp.add(pos, [(-a, -b, -c) for a, b, c in nrm], uv, [[t0, t2, t1] for t0, t1, t2 in g["tris"]])

    # Wheel: CT3 object 0 (front-left), x 0..1.97 across the tyre, outside face at +x.
    for g in meta["parts"]["wheel_FL"]:
        pos = [(p[2] * UNIT, p[0] * UNIT - 0.08, p[1] * UNIT) for p in g["pos"]]
        nrm = [ct_nrm_to_nfs(n) for n in g["nrm"]]
        name, uv, _ = resolve(g["texture"], g.get("tex_flags", 0), [tuple(x) for x in g["uv"]], g["tris"])
        grp = group_for(tire, name, name, SHADER_TIRE, "TIRE_KIT00_SIDEWALL", tpl_tire)
        grp.add(pos, nrm, uv, g["tris"])

    for key, lst in swatches.items():
        if not lst:
            continue
        fill = (0, 0, 0, 255) if key == SWATCH else (0, 0, 0, 0)
        img = Image.new("RGBA", (4, 4), fill)
        for k, c in enumerate(lst):
            img.putpixel((k % 4, k // 4), ((c >> 16) & 255, (c >> 8) & 255, c & 255, (c >> 24) & 255))
        images[key] = img.resize((16, 16), Image.NEAREST)

    all_groups = [g for bucket in (body, base, window, tire) for g in bucket.values()]
    keep_stock = mode == "stocktex"
    if keep_stock:  # diagnostic: every part on the stock TAXI_SKIN1 texture
        for g in all_groups:
            g.texture = "TAXI_SKIN1"
        new_textures = []
    else:
        new_textures = assign_texture_slots(all_groups, images, "#CT05o")  # CT3 body env texture, opaque
        for name, img in new_textures:
            print("  %-18s %dx%d" % (name, *img.size))

    lamps = find_lamps(meta["parts"])
    for kind in sorted(lamps):
        print("  %-8s lights at" % kind, " ".join("(%.2f %.2f %.2f)" % p for s in sorted(lamps[kind])
                                                 for p in lamps[kind][s]))

    plan = {}
    for lod in "ABCDE":
        plan["TAXI_KIT00_BODY_" + lod] = (list(body.values()), True)
        plan["TAXI_KIT00_FRONT_TIRE_" + lod] = (list(tire.values()), False)
    for lod in "ABCD":
        plan["TAXI_BASE_" + lod] = (list(base.values()), False)
        plan["TAXI_KIT00_FRONT_WINDOW_" + lod] = (list(window.values()), False)

    new_children = []
    for c in root.children:
        if c.id != 0x80134010:
            new_children.append(c)
            continue
        name = c.find(0x134011).data.lstrip(b"\x11")[160:].split(b"\0")[0].decode()
        if name in plan:
            groups, damage = plan[name]
            stock_markers = c.find(0x13401A)
            markers = relocate_markers(stock_markers.data, lamps) if stock_markers else None
            new, _ = build_solid(c, groups, damage, markers)
            new_children.append(new)
        elif "_DRIVER_" in name:
            new_children.append(collapse_solid(c))
        else:
            new_children.append(c)
    new_root = eagl.Chunk(root.id, children=new_children)
    geo = serialize_geometry([new_root])
    fix_index_tables(geo)
    # sanity: parses back
    eagl.parse(bytes(geo))

    os.makedirs(out_dir, exist_ok=True)
    open(os.path.join(out_dir, "GEOMETRY.BIN"), "wb").write(geo)
    tpk = build_tpk(os.path.join(stock_dir, "TEXTURES.BIN"), new_textures, keep_stock)
    eagl.parse(tpk)
    open(os.path.join(out_dir, "TEXTURES.BIN"), "wb").write(tpk)
    for n in ("VINYLS.BIN", "PREVINYL.BIN"):
        src = os.path.join(stock_dir, n)
        if os.path.exists(src):
            open(os.path.join(out_dir, n), "wb").write(open(src, "rb").read())

    def summary(bucket):
        return "%d groups, %d tris" % (len(bucket), sum(len(g.tris) for g in bucket.values()))
    print("body:", summary(body), "| base:", summary(base), "| window:", summary(window), "| tire:", summary(tire))
    print("textures:", len(new_textures), "GEOMETRY.BIN", len(geo), "TEXTURES.BIN", len(tpk))


if __name__ == "__main__":
    main(*sys.argv[1:])
