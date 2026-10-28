"""Tiny PE helper for static analysis of CT3.exe / speed.exe (x86)."""
import re
import struct

import capstone


class PE:
    def __init__(self, path):
        self.d = open(path, "rb").read()
        d = self.d
        pe = struct.unpack_from("<I", d, 0x3C)[0]
        nsec = struct.unpack_from("<H", d, pe + 6)[0]
        opt = struct.unpack_from("<H", d, pe + 20)[0]
        self.base = struct.unpack_from("<I", d, pe + 24 + 28)[0]
        self.secs = []
        for i in range(nsec):
            name, vs, va, rs, ra = struct.unpack_from("<8sIIII", d, pe + 24 + opt + 40 * i)
            self.secs.append((name.rstrip(b"\0").decode(errors="replace"), va, vs, ra, rs))
        self.md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)

    def va(self, off):
        for _, va, _, ra, rs in self.secs:
            if ra <= off < ra + rs:
                return self.base + va + off - ra
        return None

    def off(self, va):
        r = va - self.base
        for _, sva, vs, ra, rs in self.secs:
            if sva <= r < sva + max(vs, rs):
                return ra + r - sva
        return None

    def find(self, pat):
        return [self.va(m.start()) for m in re.finditer(pat, self.d)]

    def xrefs(self, va):
        """Offsets where the absolute value `va` appears (push/mov imm32, tables)."""
        needle = struct.pack("<I", va)
        return [self.va(m.start()) for m in re.finditer(re.escape(needle), self.d)]

    def u32(self, va):
        return struct.unpack_from("<I", self.d, self.off(va))[0]

    def f32(self, va):
        return struct.unpack_from("<f", self.d, self.off(va))[0]

    def cstr(self, va):
        o = self.off(va)
        e = self.d.index(b"\0", o)
        return self.d[o:e].decode(errors="replace")

    def dis(self, va, n=40):
        o = self.off(va)
        out = []
        for ins in self.md.disasm(self.d[o:o + n * 8], va):
            out.append(ins)
            if len(out) >= n:
                break
        return out

    def show(self, va, n=40):
        for i in self.dis(va, n):
            note = ""
            for tok in i.op_str.replace(",", " ").replace("[", " ").replace("]", " ").split():
                if tok.startswith("0x") and len(tok) >= 8:
                    try:
                        v = int(tok, 16)
                        o = self.off(v)
                        if o is not None:
                            s = self.d[o:o + 40].split(b"\0")[0]
                            if len(s) >= 4 and all(32 <= c < 127 for c in s):
                                note = "  ; " + s.decode()
                            else:
                                note = "  ; [%#x]=%#x f=%g" % (v, self.u32(v), self.f32(v))
                    except Exception:  # noqa: BLE001
                        pass
            print("%08x  %-8s %s%s" % (i.address, i.mnemonic, i.op_str, note))

    def func_start(self, va, limit=0x4000):
        """Walk back to the nearest CC/90 padding run followed by a plausible prologue."""
        o = self.off(va)
        for k in range(o, max(0, o - limit), -1):
            if self.d[k - 1] in (0xCC, 0x90, 0xC3) and self.d[k - 2] in (0xCC, 0x90, 0xC3, 0x00):
                if self.d[k] in (0x55, 0x83, 0x81, 0x53, 0x56, 0x57, 0x6A, 0x8B, 0xA1, 0x51, 0xD9, 0x64):
                    return self.va(k)
        return None
