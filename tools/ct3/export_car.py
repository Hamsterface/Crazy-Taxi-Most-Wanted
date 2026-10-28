r"""Export a Crazy Taxi 3 car bank to OBJ/MTL/PNG plus a JSON part list for tools/mwcar.

Usage: python -I export_car.py "<CT3 dir>" <out dir> [driver]

Car bank object ids (bank40; other banks order everything after the wheels differently,
so classify_objects() picks the rest by shape):
   0..3   wheels FL, FR, RL, RR, modelled at the origin (x 0..+w for left, -w..0 for right)
   4,5,8,9 motion-blur wheel variants
   6      collision hull (no meshes)
   7      body: the tall object with the most meshes
   10,11  roof sign, unlit / lit (both texture 23: 10 samples its dim bottom half, 11 the bright top);
          radius 2.0, lit is the later id
   12..15 light overlays (head + brake lamp lenses, one per light state): car-sized but flat;
          "lights" is the first

Wheel placement comes from CT3.exe: a pointer table at 0x68217C (indexed by driver)
points to 27-float records: FL, FR, RL, RR wheel centres, centre of mass (0,y,0),
then four body-box corners.
"""
import json
import os
import struct
import sys

from PIL import Image

sys.path.insert(0, os.path.dirname(__file__))
import gxmd  # noqa: E402
import gxtx  # noqa: E402

# Driver index (CT3.exe name table at 0x682708) -> bank number (switch at 0x478C42).
DRIVERS = ["angel", "bixbite", "venus", "zax", "slash", "iceman", "cinnamon", "hotd",
           "axel", "bdjoe", "gena", "gus"]
BANKS = [80, 81, 82, 83, 44, 45, 46, 47, 40, 41, 42, 43, 84, 85, 86]

EXE_BASE = 0x400000
CAR_TABLE_PTRS = 0x68217C

WHEEL_OBJECTS = {"FL": 0, "FR": 1, "RL": 2, "RR": 3}
MIRROR_U, MIRROR_V = 0x80, 0x100  # mesh texture flags: mirrored repeat (see tools/mwcar/build_taxi.py resolve)

# CT3 units are decimetres: Axel's car is 5.3 m long, 52.9 units.
UNIT_TO_M = 0.1


def read_car_record(exe_path, driver_index):
    d = open(exe_path, "rb").read()
    pe = struct.unpack_from("<I", d, 0x3C)[0]
    nsec = struct.unpack_from("<H", d, pe + 6)[0]
    opt = struct.unpack_from("<H", d, pe + 20)[0]
    secs = [struct.unpack_from("<8sIIII", d, pe + 24 + opt + 40 * i) for i in range(nsec)]

    def off(va):
        r = va - EXE_BASE
        for _, vs, v, rs, ra in secs:
            if v <= r < v + max(vs, rs):
                return ra + r - v
        raise ValueError(hex(va))

    rec_va = struct.unpack_from("<I", d, off(CAR_TABLE_PTRS + 4 * driver_index))[0]
    f = struct.unpack_from("<27f", d, off(rec_va))
    return {
        "wheels": {"FL": f[0:3], "FR": f[3:6], "RL": f[6:9], "RR": f[9:12]},
        "centre_of_mass": f[12:15],
        "box": [f[15:18], f[18:21], f[21:24], f[24:27]],
    }


def classify_objects(objs):
    """Return the ids of the body, lit roof sign and first light overlay (sign/lights may be None)."""
    drawn = [ob for ob in objs if ob.meshes]
    body = max((ob for ob in drawn if ob.extents[1] > 3), key=lambda ob: len(ob.meshes))
    signs = [ob.id for ob in drawn if abs(ob.radius - 2.0) < 0.1]
    lights = [ob.id for ob in drawn if ob.radius > 15 and ob.extents[1] < 2.5]
    return body.id, max(signs, default=None), min(lights, default=None)


def collect(pools, objs, ids, offset=(0.0, 0.0, 0.0)):
    """Return {texture: {"pos": [...], "nrm": [...], "uv": [...], "tris": [...]}} for the given objects."""
    groups = {}
    for ob, m, pool, idx in gxmd.iter_strips(objs, ids):
        P = pools[pool]
        # material[3] bytes are A, R, G, B (read as a little-endian u32: 0xBBGGRRAA)
        d = m.material[3]
        argb = ((d & 0xFF) << 24) | (((d >> 8) & 0xFF) << 16) | (((d >> 16) & 0xFF) << 8) | ((d >> 24) & 0xFF)
        g = groups.setdefault((m.texture, m.flags & 0xFF, argb, m.tex_flags),
                              {"pos": [], "nrm": [], "uv": [], "tris": [], "remap": {}})
        for t in gxmd.strip_to_tris(idx):
            if max(t) >= P.count:
                continue
            tri = []
            for i in t:
                key = (pool, i)
                if key not in g["remap"]:
                    g["remap"][key] = len(g["pos"])
                    x, y, z = P.pos[i]
                    g["pos"].append((x + offset[0], y + offset[1], z + offset[2]))
                    g["nrm"].append(P.nrm[i])
                    g["uv"].append(P.uv[i])
                tri.append(g["remap"][key])
            g["tris"].append(tri)
    for g in groups.values():
        del g["remap"]
    return groups


def mirror_suffix(tex_flags):
    return ("mu" if tex_flags & MIRROR_U else "") + ("mv" if tex_flags & MIRROR_V else "")


def write_mirrored(out_dir, name, tex_flags):
    """OBJ has no mirrored-repeat addressing: bake the mirror into a doubled copy of the texture
    (sampled with halved UVs). Returns the copy's file name."""
    img = Image.open(os.path.join(out_dir, name))
    w, h = img.size
    if tex_flags & MIRROR_U:
        wide = Image.new(img.mode, (w * 2, h))
        wide.paste(img, (0, 0))
        wide.paste(img.transpose(Image.FLIP_LEFT_RIGHT), (w, 0))
        img, w = wide, w * 2
    if tex_flags & MIRROR_V:
        tall = Image.new(img.mode, (w, h * 2))
        tall.paste(img, (0, 0))
        tall.paste(img.transpose(Image.FLIP_TOP_BOTTOM), (0, h))
        img = tall
    out = "%s_%s.png" % (os.path.splitext(name)[0], mirror_suffix(tex_flags))
    img.save(os.path.join(out_dir, out))
    return out


def write_obj(path, parts, tex_names):
    out_dir = os.path.dirname(path)
    mirrored = sorted({(tex, tf & (MIRROR_U | MIRROR_V)) for groups in parts.values() for (tex, _, _, tf) in groups
                       if tex >= 0 and tf & (MIRROR_U | MIRROR_V)})
    mtl = os.path.splitext(path)[0] + ".mtl"
    with open(mtl, "w") as f:
        for i, name in enumerate(tex_names):
            f.write("newmtl tex%02d\nKd 1 1 1\nmap_Kd %s\nmap_d %s\n\n" % (i, name, name))
        for tex, tf in mirrored:
            name = write_mirrored(out_dir, tex_names[tex], tf)
            f.write("newmtl tex%02d_%s\nKd 1 1 1\nmap_Kd %s\nmap_d %s\n\n" % (tex, mirror_suffix(tf), name, name))
        f.write("newmtl untextured\nKd 0.2 0.2 0.2\n")
    with open(path, "w") as f:
        f.write("mtllib %s\n" % os.path.basename(mtl))
        base = 1
        for part, groups in parts.items():
            f.write("o %s\n" % part)
            for (tex, _, _, tf), g in sorted(groups.items()):
                if tex < 0:
                    tf = 0
                su = 0.5 if tf & MIRROR_U else 1.0
                sv = 0.5 if tf & MIRROR_V else 1.0
                for x, y, z in g["pos"]:
                    f.write("v %f %f %f\n" % (x * UNIT_TO_M, y * UNIT_TO_M, z * UNIT_TO_M))
                for nx, ny, nz in g["nrm"]:
                    f.write("vn %f %f %f\n" % (nx, ny, nz))
                for u, v in g["uv"]:
                    f.write("vt %f %f\n" % (u * su, 1.0 - v * sv))
                mat = "untextured" if tex < 0 else "tex%02d" % tex
                if tf & (MIRROR_U | MIRROR_V):
                    mat += "_" + mirror_suffix(tf)
                f.write("usemtl %s\n" % mat)
                for t in g["tris"]:
                    f.write("f %s\n" % " ".join("%d/%d/%d" % (base + i, base + i, base + i) for i in t))
                base += len(g["pos"])


def main(ct3_dir, out_dir, driver="axel"):
    di = DRIVERS.index(driver)
    bank = BANKS[di]
    media = os.path.join(ct3_dir, "Media")
    _, pools, objs = gxmd.load(os.path.join(media, "bank%d.mdl" % bank))
    rec = read_car_record(os.path.join(ct3_dir, "CT3.exe"), di)

    os.makedirs(out_dir, exist_ok=True)
    tex_names = gxtx.export(os.path.join(media, "bank%d.art" % bank), out_dir)

    body, sign, lights = classify_objects(objs)
    parts = {"body": collect(pools, objs, {body}),
             "sign": collect(pools, objs, {sign}),
             "lights": collect(pools, objs, {lights})}
    for name, oid in WHEEL_OBJECTS.items():
        parts["wheel_" + name] = collect(pools, objs, {oid})
    # Placed wheels for the preview OBJ only; the JSON keeps them at the origin.
    placed = dict(parts)
    for name, oid in WHEEL_OBJECTS.items():
        placed["wheel_" + name] = collect(pools, objs, {oid}, rec["wheels"][name])
    write_obj(os.path.join(out_dir, "%s.obj" % driver), placed, tex_names)

    meta = {
        "driver": driver,
        "bank": bank,
        "unit_to_m": UNIT_TO_M,
        "axes": "x left, y up, z forward (CT3 space)",
        "car": rec,
        "textures": [{"file": n, "width": w, "height": h, "format": gxtx.FORMATS.get(c)}
                     for n, (w, h, c, _) in zip(tex_names, gxtx.read(os.path.join(media, "bank%d.art" % bank)))],
        "parts": {
            part: [{"texture": tex, "flags": fl, "diffuse": dif, "tex_flags": tf, "pos": g["pos"], "nrm": g["nrm"],
                    "uv": g["uv"], "tris": g["tris"]}
                   for (tex, fl, dif, tf), g in sorted(groups.items())]
            for part, groups in parts.items()
        },
    }
    with open(os.path.join(out_dir, "%s.json" % driver), "w") as f:
        json.dump(meta, f)
    tris = {p: sum(len(g["tris"]) for g in gs.values()) for p, gs in parts.items()}
    print("bank%d (%s): %s" % (bank, driver, tris))
    print("wheels:", rec["wheels"])


if __name__ == "__main__":
    main(*sys.argv[1:])
