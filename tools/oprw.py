"""Read a binarized DayZ world (OPRW .wrp).

Follows the field order of BIS.WRP's OPRW reader (as ported in
habitualdev/IntelPackage armaformats/wrp/oprw.go), with LZO1X for the
compressed arrays (versions 23 and up). DayZ writes version 28.
"""

import struct

LZO_M2_MAX_OFFSET = 0x0800


def lzo1x_decompress(src, ip, out_len):
    """Decode an LZO1X block starting at src[ip]; returns (bytes, end offset)."""
    out = bytearray()
    t = 0
    state = "start"
    if src[ip] > 17:
        t = src[ip] - 17
        ip += 1
        if t < 4:
            state = "match_next"
        else:
            out += src[ip:ip + t]
            ip += t
            state = "first_literal_run"

    while True:
        if state == "start":
            t = src[ip]
            ip += 1
            if t >= 16:
                state = "match"
                continue
            if t == 0:
                while src[ip] == 0:
                    t += 255
                    ip += 1
                t += 15 + src[ip]
                ip += 1
            out += src[ip:ip + t + 3]
            ip += t + 3
            state = "first_literal_run"
            continue

        if state == "first_literal_run":
            t = src[ip]
            ip += 1
            if t >= 16:
                state = "match"
                continue
            m_pos = len(out) - (1 + LZO_M2_MAX_OFFSET) - (t >> 2) - (src[ip] << 2)
            ip += 1
            for k in range(3):
                out.append(out[m_pos + k])
            state = "match_done"
            continue

        if state == "match":
            if t >= 64:
                m_pos = len(out) - 1 - ((t >> 2) & 7) - (src[ip] << 3)
                ip += 1
                n = (t >> 5) - 1 + 2
            elif t >= 32:
                t &= 31
                if t == 0:
                    while src[ip] == 0:
                        t += 255
                        ip += 1
                    t += 31 + src[ip]
                    ip += 1
                m_pos = len(out) - 1 - ((src[ip] | (src[ip + 1] << 8)) >> 2)
                ip += 2
                n = t + 2
            elif t >= 16:
                m_pos = len(out) - ((t & 8) << 11)
                t &= 7
                if t == 0:
                    while src[ip] == 0:
                        t += 255
                        ip += 1
                    t += 7 + src[ip]
                    ip += 1
                m_pos -= (src[ip] | (src[ip + 1] << 8)) >> 2
                ip += 2
                if m_pos == len(out):
                    break                                   # end of stream
                m_pos -= 0x4000
                n = t + 2
            else:
                m_pos = len(out) - 1 - (t >> 2) - (src[ip] << 2)
                ip += 1
                n = 2
            dist = len(out) - m_pos
            if dist >= n:
                out += out[m_pos:m_pos + n]
            else:
                chunk = out[m_pos:]
                while n > 0:
                    take = chunk[:n]
                    out += take
                    n -= len(take)
            state = "match_done"
            continue

        if state == "match_done":
            t = src[ip - 2] & 3
            if t == 0:
                state = "start"
                continue
            state = "match_next"
            continue

        if state == "match_next":
            out += src[ip:ip + t]
            ip += t
            t = src[ip]
            ip += 1
            state = "match"
            continue

    if len(out) != out_len:
        raise ValueError("LZO: got %d bytes, expected %d" % (len(out), out_len))
    return bytes(out), ip


class Reader:
    def __init__(self, data, version=0):
        self.d = data
        self.p = 0
        self.version = version
        self.lzo = False

    def i32(self):
        v = struct.unpack_from("<i", self.d, self.p)[0]
        self.p += 4
        return v

    def u16(self):
        v = struct.unpack_from("<H", self.d, self.p)[0]
        self.p += 2
        return v

    def i16(self):
        v = struct.unpack_from("<h", self.d, self.p)[0]
        self.p += 2
        return v

    def f32(self):
        v = struct.unpack_from("<f", self.d, self.p)[0]
        self.p += 4
        return v

    def u8(self):
        v = self.d[self.p]
        self.p += 1
        return v

    def raw(self, n):
        v = self.d[self.p:self.p + n]
        self.p += n
        return v

    def asciiz(self):
        end = self.d.index(b"\0", self.p)
        s = self.d[self.p:end].decode("latin-1")
        self.p = end + 1
        return s

    def vec3(self):
        v = struct.unpack_from("<3f", self.d, self.p)
        self.p += 12
        return v

    def compressed(self, size):
        if size == 0:
            return b""
        if self.lzo:
            if size < 1024:
                return self.raw(size)
            data, self.p = lzo1x_decompress(self.d, self.p, size)
            return data
        raise NotImplementedError("LZSS arrays (version < 23)")


class QuadTree:
    """BIS QuadTree of 1/2/4-byte elements packed into 4-byte leaves."""

    def __init__(self, sx, sy, r, elem_size):
        self.sx, self.sy, self.es = sx, sy, elem_size
        self.leaf_lx, self.leaf_ly = {1: (1, 1), 2: (1, 0), 4: (0, 0)}[elem_size]
        lx = (sx - 1).bit_length()
        ly = (sy - 1).bit_length()
        nlx = (lx - self.leaf_lx + 1) // 2
        nly = (ly - self.leaf_ly + 1) // 2
        nl = max(nlx, nly)
        self.lx = nl * 2 + self.leaf_lx
        self.ly = nl * 2 + self.leaf_ly
        self.is_node = r.u8() != 0
        self.root = self._node(r) if self.is_node else r.raw(4)

    def _node(self, r):
        flag = r.u16()
        subs = []
        for i in range(16):
            subs.append(self._node(r) if (flag >> i) & 1 else r.raw(4))
        return (flag, subs)

    def _leaf(self, leaf, x, y):
        if self.es == 1:
            return leaf[(y << 1) + x]       # see note in grid()
        if self.es == 2:
            return struct.unpack_from("<H", leaf, x * 2)[0]
        return struct.unpack_from("<i", leaf, 0)[0]

    def get(self, x, y):
        if not self.is_node:
            return self._leaf(self.root, x & ((1 << self.leaf_lx) - 1), y & ((1 << self.leaf_ly) - 1))
        sx = (x << (32 - self.lx)) & 0xFFFFFFFF
        sy = (y << (32 - self.ly)) & 0xFFFFFFFF
        node = self.root
        while True:
            flag, subs = node
            idx = ((sy >> 30) << 2) + (sx >> 30)
            if (flag >> idx) & 1:
                node = subs[idx]
                sx = (sx << 2) & 0xFFFFFFFF
                sy = (sy << 2) & 0xFFFFFFFF
                continue
            return self._leaf(subs[idx], x & ((1 << self.leaf_lx) - 1), y & ((1 << self.leaf_ly) - 1))

    def grid(self):
        return [[self.get(x, y) for x in range(self.sx)] for y in range(self.sy)]


class OPRW:
    """The parts of a DayZ world (OPRW v28, and v32 from current DayZ Tools) needed
    to rebuild its Terrain Builder sources and check a build. Elevation rows run
    south to north (row z covers world Z = z * cell)."""

    def __init__(self, path):
        with open(path, "rb") as fh:
            d = fh.read()
        if d[:4] != b"OPRW":
            raise ValueError("%s is not a binarized world (OPRW)" % path)
        r = Reader(d)
        r.p = 4
        self.version = r.i32()
        if self.version < 25:
            raise ValueError("OPRW v%d: this reader handles v25+ (DayZ writes v28)" % self.version)
        r.version, r.lzo = self.version, True
        self.app_id = r.i32()
        if self.version >= 28:
            self.unknown_v28 = r.i32()          # DayZ-only header field, 0 in this map
        if self.version >= 32:
            self.unknown_v32 = r.u8()           # one more byte in current DayZ Tools' output
        self.land_x, self.land_y = r.i32(), r.i32()
        self.terrain_x, self.terrain_y = r.i32(), r.i32()
        self.land_cell = r.f32()
        self.terrain_cell = self.land_cell * self.land_x / self.terrain_x
        self.geography = QuadTree(self.land_x, self.land_y, r, 2)
        self.sound_map = QuadTree(self.land_x, self.land_x, r, 1)
        self.mountains = [r.vec3() for _ in range(r.i32())]
        self.materials = QuadTree(self.land_x, self.land_y, r, 2)
        self.grass_approx = r.compressed(self.terrain_x * self.terrain_y)
        self.prim_tex_index = r.compressed(self.terrain_x * self.terrain_y)
        self.elevation = r.compressed(self.terrain_x * self.terrain_y * 4)   # raw <f4
        self.mat_names = []
        for _ in range(r.i32()):
            self.mat_names.append(r.asciiz())
            r.u8()
        self.models = [r.asciiz() for _ in range(r.i32())]
        self.entities = []
        for _ in range(r.i32()):
            self.entities.append((r.asciiz(), r.asciiz(), r.vec3(), r.i32()))
        QuadTree(self.land_x, self.land_y, r, 4)                 # object offsets
        size_objects = r.i32()
        QuadTree(self.land_x, self.land_y, r, 4)                 # map object offsets
        r.i32()                                                  # size of map info
        r.compressed(self.land_x * self.land_y)                  # persistent
        r.compressed(self.terrain_x * self.terrain_y)            # subdivision hints
        self.max_object_id = r.i32()
        r.i32()                                                  # roadnet size
        self.roads = []
        for _ in range(self.land_x * self.land_y):
            for _ in range(r.i32()):
                n = r.i16()
                pts = [r.vec3() for _ in range(n)]
                r.raw(n)                                         # connection types
                oid = r.i32()
                p3d = r.asciiz()
                r.raw(48)                                        # to-world matrix
                self.roads.append((oid, p3d, pts))
        self.objects = []
        for _ in range(size_objects // 60):
            oid, model = r.i32(), r.i32()
            m = struct.unpack_from("<12f", d, r.p)
            r.p += 48
            shape = r.i32()
            self.objects.append((oid, self.models[model], m, shape))
        self.trailing = len(d) - r.p
