"""Decode an NFS MW car GEOMETRY.BIN (+ its TEXTURES.BIN) back to OBJ/PNG, to check built files.

Usage: python -I bin2obj.py <car dir> <out dir> [solid name filter] [wheel x y z ...]
Only uncompressed (0x20 / A8R8G8B8) JDLZ textures are decoded; others render untextured.
"""
import os
import struct
import sys

from PIL import Image

sys.path.insert(0, os.path.dirname(__file__))
import eagl  # noqa: E402
import dxt  # noqa: E402
import jdlz  # noqa: E402


def read_textures(path):
    b = open(path, "rb").read()
    top = eagl.parse(b)[0]
    desc = top.find(0xB3310000).find(0x33310003).data
    out = {}
    for i in range(len(desc) // 24):
        h, off, size, usize, _, _ = struct.unpack_from("<6I", desc, i * 24)
        blob = b[off:off + size]
        if blob[:4] != b"JDLZ":
            continue
        raw = jdlz.decompress(blob)
        e = raw[-156:-32]
        w, hh = struct.unpack_from("<HH", e, 68)
        four = raw[-32 + 20:-32 + 24]
        if e[74] == 0x20:
            px = raw[:w * hh * 4]
            rgba = bytearray(len(px))
            rgba[0::4], rgba[1::4], rgba[2::4], rgba[3::4] = px[2::4], px[1::4], px[0::4], px[3::4]
            out[h] = Image.frombytes("RGBA", (w, hh), bytes(rgba))
        elif four in (b"DXT1", b"DXT3"):
            out[h] = Image.fromarray(dxt.decode(raw, w, hh, four.decode()), "RGBA")
    return out


def solids(path):
    b = open(path, "rb").read()
    root = eagl.parse(b)[0]
    for obj in root.find_all(0x80134010):
        hc = obj.find(0x134011)
        pad = (-hc.offset) % 16
        hd = hc.data[pad:]
        name = hd[160:].split(b"\0")[0].decode()
        texs = [struct.unpack_from("<I", obj.find(0x134012).data, i * 8)[0]
                for i in range(len(obj.find(0x134012).data) // 8)]
        mesh = obj.find(0x80134100)
        sgc = mesh.find(0x134B02)
        sg = sgc.data[(-sgc.offset) % 16:]
        vc = mesh.find(0x134B01)
        vb = vc.data[(-vc.offset) % 128:]
        ic = mesh.find(0x134B03)
        ib = ic.data[(-ic.offset) % 16:]
        idx = struct.unpack_from("<%dH" % (len(ib) // 2), ib)
        groups = []
        vbase = 0
        for i in range(len(sg) // 104):
            g = sg[i * 104:(i + 1) * 104]
            nv, nt, first = struct.unpack_from("<III", g, 60)
            ni = struct.unpack_from("<I", g, 92)[0]
            stride = 36
            verts = [struct.unpack_from("<3f3fI2f", vb, (vbase + k) * stride) for k in range(nv)]
            tris = [idx[first + 3 * t:first + 3 * t + 3] for t in range(ni // 3)]
            groups.append((texs[g[24]], vbase, verts, tris))
            vbase += nv
        yield name, groups


def main(car_dir, out_dir, name_filter="_A", *wheels):
    os.makedirs(out_dir, exist_ok=True)
    tex = read_textures(os.path.join(car_dir, "TEXTURES.BIN"))
    for h, img in tex.items():
        img.save(os.path.join(out_dir, "%08x.png" % h))
    wheel_pos = [tuple(float(x) for x in wheels[i:i + 3]) for i in range(0, len(wheels), 3)]
    with open(os.path.join(out_dir, "car.mtl"), "w") as m:
        for h in tex:
            m.write("newmtl t%08x\nmap_Kd %08x.png\n" % (h, h))
    with open(os.path.join(out_dir, "car.obj"), "w") as f:
        f.write("mtllib car.mtl\n")
        vcount = 1
        for name, groups in solids(os.path.join(car_dir, "GEOMETRY.BIN")):
            if name_filter not in name or "_DRIVER_" in name:
                continue
            placements = [(0, 0, 0, 1)]
            if "TIRE" in name and wheel_pos:
                placements = [(x, y, z, -1 if y < 0 else 1) for x, y, z in wheel_pos]
            for ox, oy, oz, mirror in placements:
                f.write("o %s\n" % name)
                for th, vbase, verts, tris in groups:
                    f.write("usemtl t%08x\n" % th)
                    for v in verts:
                        # written y-up (x left, y up, z forward) like the CT3 export, for preview.py
                        f.write("v %f %f %f\nvt %f %f\n" % (v[1] * mirror + oy, v[2] + oz, v[0] + ox, v[7], 1 - v[8]))
                    for t in tris:
                        a, b, c = (vcount + i - vbase for i in t)
                        if mirror < 0:
                            b, c = c, b
                        f.write("f %d/%d %d/%d %d/%d\n" % (a, a, b, b, c, c))
                    vcount += len(verts)
    print("wrote", os.path.join(out_dir, "car.obj"), len(tex), "textures")


if __name__ == "__main__":
    main(*sys.argv[1:])
