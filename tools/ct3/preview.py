"""Tiny textured software rasteriser for checking exported OBJs (no Blender needed).

Usage: python -I preview.py model.obj out.png [yaw_deg] [pitch_deg]
"""
import math
import os
import sys

import numpy as np
from PIL import Image


def load_obj(path):
    v, vt, faces, mats = [], [], [], {}
    cur = None
    d = os.path.dirname(path)
    for line in open(path):
        p = line.split()
        if not p:
            continue
        if p[0] == "mtllib":
            name = None
            for l2 in open(os.path.join(d, p[1])):
                q = l2.split()
                if q and q[0] == "newmtl":
                    name = q[1]
                elif q and q[0] == "map_Kd":
                    mats[name] = np.asarray(Image.open(os.path.join(d, q[1])).convert("RGBA"), dtype=np.float32) / 255
        elif p[0] == "v":
            v.append([float(x) for x in p[1:4]])
        elif p[0] == "vt":
            vt.append([float(x) for x in p[1:3]])
        elif p[0] == "usemtl":
            cur = p[1]
        elif p[0] == "f":
            idx = [tuple(int(k) - 1 for k in c.split("/")[:2]) for c in p[1:]]
            faces.append((cur, idx))
    return np.array(v), np.array(vt), faces, mats


def render(path, out, yaw=35.0, pitch=20.0, size=(900, 600), cull=0):
    """cull: 0 none, +1 / -1 drop triangles whose screen winding has that sign."""
    V, VT, faces, mats = load_obj(path)
    W, H = size
    cy, sy = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
    cp, sp = math.cos(math.radians(pitch)), math.sin(math.radians(pitch))
    c = (V.min(0) + V.max(0)) / 2
    P = V - c
    # yaw about y, then pitch about x
    x = P[:, 0] * cy + P[:, 2] * sy
    z = -P[:, 0] * sy + P[:, 2] * cy
    y = P[:, 1] * cp - z * sp
    z = P[:, 1] * sp + z * cp
    s = 0.9 * min(W, H) / (2 * max(np.abs(x).max(), np.abs(y).max()))
    sx = W / 2 + x * s
    sy_ = H / 2 - y * s
    zbuf = np.full((H, W), -1e9, np.float32)
    img = np.zeros((H, W, 3), np.float32) + 0.35
    for mat, idx in faces:
        tex = mats.get(mat)
        a, b, cc = idx[0], idx[1], idx[2]
        xs = np.array([sx[a[0]], sx[b[0]], sx[cc[0]]])
        ys = np.array([sy_[a[0]], sy_[b[0]], sy_[cc[0]]])
        zs = np.array([z[a[0]], z[b[0]], z[cc[0]]])
        x0, x1 = int(max(0, xs.min())), int(min(W - 1, xs.max() + 1))
        y0, y1 = int(max(0, ys.min())), int(min(H - 1, ys.max() + 1))
        if x1 < x0 or y1 < y0:
            continue
        den = (ys[1] - ys[2]) * (xs[0] - xs[2]) + (xs[2] - xs[1]) * (ys[0] - ys[2])
        if abs(den) < 1e-9:
            continue
        if cull and (den > 0) == (cull > 0):
            continue
        gx, gy = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
        w0 = ((ys[1] - ys[2]) * (gx - xs[2]) + (xs[2] - xs[1]) * (gy - ys[2])) / den
        w1 = ((ys[2] - ys[0]) * (gx - xs[2]) + (xs[0] - xs[2]) * (gy - ys[2])) / den
        w2 = 1 - w0 - w1
        m = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
        if not m.any():
            continue
        zz = w0 * zs[0] + w1 * zs[1] + w2 * zs[2]
        sub = zbuf[y0:y1 + 1, x0:x1 + 1]
        m &= zz > sub
        if tex is not None and len(VT):
            uv = VT[[a[1], b[1], cc[1]]]
            u = w0 * uv[0, 0] + w1 * uv[1, 0] + w2 * uv[2, 0]
            v = w0 * uv[0, 1] + w1 * uv[1, 1] + w2 * uv[2, 1]
            th, tw = tex.shape[:2]
            tx = (np.mod(u, 1.0) * tw).astype(int) % tw
            ty = ((1 - np.mod(v, 1.0)) * th).astype(int) % th
            col = tex[ty, tx]
            m &= col[..., 3] > 0.3
            rgb = col[..., :3]
        else:
            rgb = np.zeros(gx.shape + (3,), np.float32) + 0.15
        sub[m] = zz[m]
        region = img[y0:y1 + 1, x0:x1 + 1]
        region[m] = rgb[m]
    Image.fromarray((img * 255).clip(0, 255).astype(np.uint8)).save(out)


if __name__ == "__main__":
    a = sys.argv[1:]
    render(a[0], a[1], *(float(x) for x in a[2:4]), cull=int(a[4]) if len(a) > 4 else 0)
