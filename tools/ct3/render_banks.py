"""Render a top + side wireframe thumbnail of every bank, to find the cars."""
import glob
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection

sys.path.insert(0, os.path.dirname(__file__))
import gxmd  # noqa: E402


def segs(pools, strips, a, b):
    out = []
    for s in strips:
        if s.pool >= len(pools):
            continue
        P = pools[s.pool].pos
        for t in gxmd.strip_to_tris(s.indices):
            if max(t) >= len(P):
                continue
            for i, j in ((0, 1), (1, 2), (2, 0)):
                out.append(((P[t[i]][a], P[t[i]][b]), (P[t[j]][a], P[t[j]][b])))
    return out


def main(media, outdir, pattern="bank*.mdl"):
    os.makedirs(outdir, exist_ok=True)
    for path in sorted(glob.glob(os.path.join(media, pattern))):
        name = os.path.splitext(os.path.basename(path))[0]
        try:
            _, pools, strips = gxmd.load(path)
        except Exception as e:  # noqa: BLE001
            print(name, "failed", e)
            continue
        fig, axes = plt.subplots(1, 3, figsize=(15, 5))
        for ax, (a, b, t) in zip(axes, ((0, 2, "x/z"), (2, 1, "z/y"), (0, 1, "x/y"))):
            ax.add_collection(LineCollection(segs(pools, strips, a, b), linewidths=0.2, colors="k"))
            ax.autoscale()
            ax.set_aspect("equal")
            ax.set_title("%s %s" % (name, t))
        fig.savefig(os.path.join(outdir, name + ".png"), dpi=80)
        plt.close(fig)
        print(name, "pools", [p.count for p in pools], "strips", len(strips))


if __name__ == "__main__":
    main(*sys.argv[1:])
