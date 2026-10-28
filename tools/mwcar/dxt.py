"""Small DXT1 / DXT3 (BC1 / BC2) encoder: bounding-box endpoints along the block's main axis.

Good enough for CT3's low-res 2002 textures; no mipmaps (the stock car textures have none).
"""
import numpy as np


def _pack565(c):
    c = np.clip(np.rint(c), 0, 255).astype(np.uint32)
    return ((c[..., 0] >> 3) << 11) | ((c[..., 1] >> 2) << 5) | (c[..., 2] >> 3)


def _unpack565(v):
    r = ((v >> 11) & 31) * 255 // 31
    g = ((v >> 5) & 63) * 255 // 63
    b = (v & 31) * 255 // 31
    return np.stack([r, g, b], -1).astype(np.float32)


def _blocks(rgba):
    h, w, _ = rgba.shape
    bh, bw = max(1, (h + 3) // 4), max(1, (w + 3) // 4)
    pad = np.zeros((bh * 4, bw * 4, 4), np.float32)
    pad[:h, :w] = rgba
    if h < 4 or w < 4:  # tiny textures: repeat edge so blocks are filled
        pad[h:, :] = pad[h - 1:h, :]
        pad[:, w:] = pad[:, w - 1:w]
    return pad.reshape(bh, 4, bw, 4, 4).transpose(0, 2, 1, 3, 4).reshape(bh * bw, 16, 4)


def _color_block(px):
    """px: (n,16,3) float -> (n,8) bytes, always 4-colour mode (c0 > c1)."""
    mean = px.mean(1, keepdims=True)
    d = px - mean
    cov = np.einsum("nki,nkj->nij", d, d)
    axis = np.ones((px.shape[0], 3), np.float32)
    for _ in range(8):  # power iteration for the main axis
        axis = np.einsum("nij,nj->ni", cov, axis)
        axis /= np.linalg.norm(axis, axis=1, keepdims=True) + 1e-9
    t = np.einsum("nki,ni->nk", d, axis)
    lo = mean[:, 0] + axis * t.min(1, keepdims=True)
    hi = mean[:, 0] + axis * t.max(1, keepdims=True)
    c0, c1 = _pack565(hi), _pack565(lo)
    swap = c0 < c1
    c0, c1 = np.where(swap, c1, c0), np.where(swap, c0, c1)
    same = c0 == c1
    c1 = np.where(same & (c0 > 0), c0 - 1, c1)
    c0 = np.where(same & (c0 == 0), 1, c0)
    p0, p1 = _unpack565(c0), _unpack565(c1)
    pal = np.stack([p0, p1, (2 * p0 + p1) / 3, (p0 + 2 * p1) / 3], 1)  # (n,4,3)
    dist = ((px[:, :, None, :] - pal[:, None, :, :]) ** 2).sum(-1)
    idx = dist.argmin(2).astype(np.uint32)
    bits = (idx << (2 * np.arange(16, dtype=np.uint32))).sum(1).astype(np.uint32)
    out = np.zeros((px.shape[0], 8), np.uint8)
    out[:, 0:2] = c0.astype("<u2").view(np.uint8).reshape(-1, 2)
    out[:, 2:4] = c1.astype("<u2").view(np.uint8).reshape(-1, 2)
    out[:, 4:8] = bits.astype("<u4").view(np.uint8).reshape(-1, 4)
    return out


def encode(img, fmt):
    """img: PIL image. fmt 'DXT1' or 'DXT3'. Returns bytes, blocks in row order."""
    rgba = np.asarray(img.convert("RGBA"), np.float32)
    blk = _blocks(rgba)
    color = _color_block(blk[..., :3])
    if fmt == "DXT1":
        return color.tobytes()
    a = np.clip(np.rint(blk[..., 3] / 17.0), 0, 15).astype(np.uint64)
    abits = (a << (4 * np.arange(16, dtype=np.uint64))).sum(1).astype("<u8")
    alpha = abits.view(np.uint8).reshape(-1, 8)
    return np.concatenate([alpha, color], 1).tobytes()


def decode(data, w, h, fmt):
    """Reference decoder for checking the encoder (returns RGBA uint8 array)."""
    bs = 8 if fmt == "DXT1" else 16
    bw, bh = max(1, (w + 3) // 4), max(1, (h + 3) // 4)
    out = np.zeros((bh * 4, bw * 4, 4), np.uint8)
    for i in range(bw * bh):
        b = data[i * bs:(i + 1) * bs]
        cb = b[-8:]
        c0 = int.from_bytes(cb[0:2], "little")
        c1 = int.from_bytes(cb[2:4], "little")
        p0, p1 = _unpack565(np.array(c0)), _unpack565(np.array(c1))
        pal = [p0, p1, (2 * p0 + p1) / 3, (p0 + 2 * p1) / 3]
        bits = int.from_bytes(cb[4:8], "little")
        abits = int.from_bytes(b[0:8], "little") if fmt == "DXT3" else None
        by, bx = divmod(i, bw)
        for k in range(16):
            y, x = divmod(k, 4)
            c = pal[(bits >> (2 * k)) & 3]
            a = ((abits >> (4 * k)) & 15) * 17 if abits is not None else 255
            out[by * 4 + y, bx * 4 + x] = (*c.astype(np.uint8), a)
    return out[:h, :w]
