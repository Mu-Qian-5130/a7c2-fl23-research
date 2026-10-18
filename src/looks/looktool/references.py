"""Bounded TIFF/DCP look extraction and 3D .cube interpolation.

DCP camera matrices/HueSat maps are inventoried, never copied to Sony.
This is a look-stage approximation, not an Adobe RAW renderer.
"""
import hashlib
import shlex
import struct
from pathlib import Path

import numpy as np
from scipy.interpolate import CubicSpline

from .color import rows, rgb_to_hsv, hsv_to_rgb, srgb_encode, srgb_decode, prophoto_to_srgb


def fingerprint(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Cube:
    def __init__(self, path):
        data, size = [], None
        self.minimum, self.maximum = np.zeros(3), np.ones(3)
        seen = set()
        for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
            words = shlex.split(line, comments=True)
            if not words:
                continue
            key = words[0]
            if key == "TITLE":
                continue
            if key in ("LUT_3D_SIZE", "DOMAIN_MIN", "DOMAIN_MAX"):
                if key in seen or data:
                    raise ValueError("Duplicate or late cube header")
                seen.add(key)
                if key == "LUT_3D_SIZE":
                    if len(words) != 2:
                        raise ValueError("Invalid cube size header")
                    size = int(words[1])
                    if not 2 <= size <= 129:
                        raise ValueError("3D cube size must be 2..129")
                else:
                    if len(words) != 4:
                        raise ValueError("Cube domain needs three values")
                    setattr(self, "minimum" if key == "DOMAIN_MIN" else "maximum", np.array(words[1:], dtype=float))
                continue
            if len(words) != 3 or size is None:
                raise ValueError("Only a standalone 3D cube is supported; no 1D/shaper LUT")
            data.append([float(x) for x in words])
            if len(data) > size**3:
                raise ValueError("Too many cube data rows")
        values = np.asarray(data, dtype=float)
        if size is None or values.shape != (size**3, 3) or not np.isfinite(values).all():
            raise ValueError("Incomplete or nonfinite cube")
        if not np.isfinite([self.minimum, self.maximum]).all() or np.any(self.maximum <= self.minimum):
            raise ValueError("Invalid cube domain")
        self.values = values.reshape(size, size, size, 3)  # red varies fastest in .cube
        self.sha256 = fingerprint(path)

    def sample(self, rgb):
        a = rows(rgb)
        n = len(self.values)
        at = np.clip((a-self.minimum)/(self.maximum-self.minimum), 0, 1)*(n-1)
        lo = np.minimum(at.astype(int), n-2)
        f = at-lo
        result = np.zeros_like(a)
        for r in (0, 1):
            for g in (0, 1):
                for b in (0, 1):
                    weight = (f[:,0] if r else 1-f[:,0])*(f[:,1] if g else 1-f[:,1])*(f[:,2] if b else 1-f[:,2])
                    result += weight[:,None]*self.values[lo[:,2]+b,lo[:,1]+g,lo[:,0]+r]
        return result


def tiff_tags(raw):
    if len(raw) < 8 or raw[:2] not in (b"II", b"MM"):
        raise ValueError("Not a classic TIFF DCP")
    endian = "<" if raw[:2] == b"II" else ">"
    if struct.unpack_from(endian+"H", raw, 2)[0] not in (42, 0x4352):
        raise ValueError("BigTIFF and non-TIFF profiles are unsupported")
    offset = struct.unpack_from(endian+"I", raw, 4)[0]
    if offset < 8 or offset+2 > len(raw):
        raise ValueError("DCP IFD outside file")
    count = struct.unpack_from(endian+"H", raw, offset)[0]
    if offset+2+12*count+4 > len(raw):
        raise ValueError("Truncated DCP IFD")
    sizes = {1:1,2:1,3:2,4:4,5:8,7:1,9:4,10:8,11:4,12:8}
    tags = {}
    for i in range(count):
        start = offset+2+12*i
        tag, typ, length, pointer = struct.unpack_from(endian+"HHII", raw, start)
        if tag in tags or typ not in sizes:
            raise ValueError("Duplicate DCP tag or unsupported TIFF type")
        n = length*sizes[typ]
        at = start+8 if n <= 4 else pointer
        if at+n > len(raw) or (n > 4 and at < 8):
            raise ValueError("DCP payload outside file")
        tags[tag] = (typ, length, raw[at:at+n])
    return endian, tags


class DcpLook:
    def __init__(self, path):
        raw = Path(path).read_bytes()
        endian, self.tags = tiff_tags(raw)

        def array(tag, typ, dtype):
            actual, count, payload = self.tags[tag]
            if actual != typ:
                raise ValueError("Unexpected DCP tag type: "+str(tag))
            return np.frombuffer(payload, dtype=endian+dtype).astype(float)

        self.dims, self.table, self.encoding = None, None, 0
        if (50981 in self.tags) != (50982 in self.tags):
            raise ValueError("DCP needs both LookTable dimensions and data")
        if 50981 in self.tags:
            dims = array(50981, 4, "u4")
            if dims.shape != (3,) or np.any(dims != np.rint(dims)):
                raise ValueError("Invalid DCP LookTable dimensions")
            nh, ns, nv = self.dims = tuple(int(x) for x in dims)
            if not (1 <= nh <= 360 and 2 <= ns <= 256 and 1 <= nv <= 256):
                raise ValueError("Unsupported DCP LookTable dimensions")
            a = array(50982, 11, "f4")
            if a.size != nh*ns*nv*3 or not np.isfinite(a).all():
                raise ValueError("Invalid DCP LookTable payload")
            self.table = a.reshape(nv, nh, ns, 3)
            if np.any(self.table[...,1:] < 0):
                raise ValueError("Negative saturation/value scale")
            if 51108 in self.tags:
                v = array(51108, 4, "u4")
                if v.shape != (1,) or v[0] not in (0, 1):
                    raise ValueError("Unsupported DCP LookTable encoding")
                self.encoding = int(v[0])
        curve = array(50940, 11, "f4").reshape(-1,2) if 50940 in self.tags else np.array([[0.,0.],[1.,1.]])
        if len(curve) < 2 or not np.isfinite(curve).all() or np.any(np.diff(curve[:,0]) <= 0) or np.any(np.diff(curve[:,1]) < 0):
            raise ValueError("Invalid DCP tone curve")
        if not np.allclose(curve[[0,-1]], [[0,0],[1,1]], atol=1e-6) or np.any((curve < 0)|(curve > 1)):
            raise ValueError("DCP tone curve must span 0..1")
        self.curve = curve
        self.spline = CubicSpline(curve[:,0], curve[:,1], bc_type="natural")
        dense = self.spline(np.linspace(0,1,8193))
        if np.any(np.diff(dense) < -1e-7) or dense.min() < -1e-7 or dense.max() > 1+1e-7:
            raise ValueError("DCP natural-spline curve overshoots; explicit renderer review required")
        if self.table is None and 50940 not in self.tags:
            raise ValueError("DCP contains no supported look stage")
        self.sha256 = hashlib.sha256(raw).hexdigest()

    def lookup(self, hsv):
        a = rows(hsv)
        if self.table is None:
            return np.tile([0.,1.,1.], (len(a),1))
        nh, ns, nv = self.dims
        h, s, v = a.T
        hs = (h%360)*nh/360
        ss = np.clip(s,0,1)*(ns-1)
        vs = (srgb_encode(np.clip(v,0,1)) if self.encoding else np.clip(v,0,1))*(nv-1)
        h0, s0 = np.floor(hs).astype(int), np.minimum(ss.astype(int),ns-2)
        v0 = np.minimum(vs.astype(int),nv-2) if nv > 1 else np.zeros(len(a),dtype=int)
        hf, sf, vf = hs-h0, ss-s0, vs-v0
        result = np.zeros_like(a)
        for dh in (0,1):
            for ds in (0,1):
                for dv in ((0,1) if nv > 1 else (0,)):
                    w = (hf if dh else 1-hf)*(sf if ds else 1-sf)*(vf if dv else 1-vf)
                    result += self.table[v0+dv,(h0+dh)%nh,s0+ds]*w[:,None]
        return result

    def render(self, linear_prophoto, exposure_stops=0):
        rgb = np.clip(rows(linear_prophoto)*2**exposure_stops,0,1)
        hsv = rgb_to_hsv(rgb)
        delta = self.lookup(hsv)
        h = (hsv[:,0]+delta[:,0])%360
        s = np.clip(hsv[:,1]*delta[:,1],0,1)
        v = hsv[:,2]*delta[:,2]
        if self.encoding:
            v = srgb_decode(np.clip(srgb_encode(hsv[:,2])*delta[:,2],0,1))
        corrected = hsv_to_rgb(np.column_stack([h,s,np.clip(v,0,1)]))
        lo, hi = corrected.min(1), corrected.max(1)
        weight = np.divide(corrected-lo[:,None], (hi-lo)[:,None], out=np.zeros_like(corrected), where=(hi-lo)[:,None] > 1e-12)
        linear = self.spline(lo)[:,None]+weight*(self.spline(hi)-self.spline(lo))[:,None]
        return np.clip(srgb_encode(linear@prophoto_to_srgb().T),0,1)

    def inventory(self):
        return {"sha256":self.sha256, "look_dimensions":self.dims, "look_value_encoding":"srgb" if self.encoding else "linear",
                "tone_points":len(self.curve), "ignored_calibration_tags":[x for x in (50721,50722,50778,50779,50937,50938,50939,50964,50965) if x in self.tags],
                "full_adobe_renderer":False, "working_space":"linear ProPhoto RGB D50"}
