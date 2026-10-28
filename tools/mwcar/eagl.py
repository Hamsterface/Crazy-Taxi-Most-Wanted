"""EAGL / BCHUNK container helpers for NFS Most Wanted (2005) .BIN files.

Chunk = u32 id, u32 size, payload. Ids with the top bit set (0x80000000) are containers
whose payload is more chunks. Payloads are sometimes preceded by 0x11 alignment padding,
and padding chunks have id 0.
"""
import struct
from dataclasses import dataclass, field


@dataclass
class Chunk:
    id: int
    data: bytes = b""                      # payload for leaf chunks
    children: list = field(default_factory=list)
    offset: int = -1                       # absolute offset of the payload when parsed

    @property
    def is_container(self):
        return bool(self.id & 0x80000000)

    def find(self, cid):
        for c in self.children:
            if c.id == cid:
                return c
        return None

    def find_all(self, cid):
        out = []
        for c in self.children:
            if c.id == cid:
                out.append(c)
            out.extend(c.find_all(cid))
        return out


def parse(buf, start=0, end=None):
    end = len(buf) if end is None else end
    out = []
    o = start
    while o + 8 <= end:
        cid, size = struct.unpack_from("<II", buf, o)
        body = o + 8
        if body + size > end:
            raise ValueError("chunk %#x at %#x overruns (%#x > %#x)" % (cid, o, body + size, end))
        c = Chunk(cid, offset=body)
        if c.is_container:
            c.children = parse(buf, body, body + size)
        else:
            c.data = bytes(buf[body:body + size])
        out.append(c)
        o = body + size
    return out


def serialize(chunks):
    out = bytearray()
    for c in chunks:
        payload = serialize(c.children) if c.is_container else c.data
        out += struct.pack("<II", c.id, len(payload))
        out += payload
    return bytes(out)


def dump(chunks, depth=0, show=lambda c: ""):
    for c in chunks:
        size = len(serialize([c])) - 8
        print("%s%08x size=%d %s" % ("  " * depth, c.id, size, show(c)))
        if c.is_container:
            dump(c.children, depth + 1, show)
