"""Generates animated glTF satellite models. Axes: X forward, Y up (zenith), Z array axis."""
import json, struct, math, sys
from pathlib import Path
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "frontend/public/models"); OUT.mkdir(parents=True, exist_ok=True)
P = math.pi
def q(ax, a): s = math.sin(a / 2); return [ax[0]*s, ax[1]*s, ax[2]*s, math.cos(a / 2)]
QZ, QX = q((1, 0, 0), P / 2), q((0, 0, 1), -P / 2)  # cylinder (built along Y) -> along Z / X

def box(w, h, d):
    x, y, z = w/2, h/2, d/2
    F = [((1,0,0), [(x,-y,-z),(x,y,-z),(x,y,z),(x,-y,z)]), ((-1,0,0), [(-x,-y,z),(-x,y,z),(-x,y,-z),(-x,-y,-z)]),
         ((0,1,0), [(-x,y,-z),(-x,y,z),(x,y,z),(x,y,-z)]), ((0,-1,0), [(-x,-y,z),(-x,-y,-z),(x,-y,-z),(x,-y,z)]),
         ((0,0,1), [(-x,-y,z),(x,-y,z),(x,y,z),(-x,y,z)]), ((0,0,-1), [(x,-y,-z),(-x,-y,-z),(-x,y,-z),(x,y,-z)])]
    V, N, I = [], [], []
    for n, vs in F:
        b = len(V); V += vs; N += [n]*4; I += [b, b+1, b+2, b, b+2, b+3]
    return V, N, I

def cyl(r, h, seg=28, r2=None):
    r2 = r if r2 is None else r2; V, N, I = [], [], []
    for i in range(seg + 1):
        a = 2*P*i/seg; c, s = math.cos(a), math.sin(a)
        V += [(r*c, -h/2, r*s), (r2*c, h/2, r2*s)]; N += [(c, 0, s)]*2
    for i in range(seg):
        b = 2*i; I += [b, b+1, b+2, b+1, b+3, b+2]
    for sg, y, rr in ((1, h/2, r2), (-1, -h/2, r)):
        c = len(V); V.append((0, y, 0)); N.append((0, sg, 0))
        for i in range(seg + 1):
            a = 2*P*i/seg; V.append((rr*math.cos(a), y, rr*math.sin(a))); N.append((0, sg, 0))
        for i in range(seg):
            I += [c, c+2+i, c+1+i] if sg > 0 else [c, c+1+i, c+2+i]
    return V, N, I

class G:
    def __init__(s):
        s.m, s.me, s.n, s.b, s.bv, s.ac, s.an = [], [], [], bytearray(), [], [], []
        s.mt = {k: s.mat(*v) for k, v in dict(gold=((.78,.58,.2), .55, .4), silver=((.78,.8,.83), .6, .35),
                white=((.9,.9,.92), .2, .5), dark=((.08,.08,.1), .5, .5), cell=((.04,.09,.28), .6, .25)).items()}
    def mat(s, rgb, metal, rough):
        s.m.append({"pbrMetallicRoughness": {"baseColorFactor": [*rgb, 1], "metallicFactor": metal, "roughnessFactor": rough}}); return len(s.m) - 1
    def acc(s, data, ct, typ, count, target=None, mm=None):
        while len(s.b) % 4: s.b.append(0)
        v = {"buffer": 0, "byteOffset": len(s.b), "byteLength": len(data)}; s.b += data
        if target: v["target"] = target
        s.bv.append(v); a = {"bufferView": len(s.bv) - 1, "componentType": ct, "count": count, "type": typ}
        if mm: a["min"], a["max"] = mm
        s.ac.append(a); return len(s.ac) - 1
    def part(s, geo, mat, t=(0, 0, 0), r=None):
        V, N, I = geo; mm = ([min(v[i] for v in V) for i in range(3)], [max(v[i] for v in V) for i in range(3)])
        p = s.acc(b"".join(struct.pack("<3f", *v) for v in V), 5126, "VEC3", len(V), 34962, mm)
        n = s.acc(b"".join(struct.pack("<3f", *v) for v in N), 5126, "VEC3", len(N), 34962)
        i = s.acc(struct.pack(f"<{len(I)}H", *I), 5123, "SCALAR", len(I), 34963)
        s.me.append({"primitives": [{"attributes": {"POSITION": p, "NORMAL": n}, "indices": i, "material": mat}]})
        return s.node(len(s.me) - 1, t, r)
    def node(s, mesh=None, t=None, r=None, kids=None):
        d = {}
        if mesh is not None: d["mesh"] = mesh
        if t and any(t): d["translation"] = list(t)
        if r: d["rotation"] = r
        if kids: d["children"] = kids
        s.n.append(d); return len(s.n) - 1
    def spin(s, kids, t, period, axis=(0, 0, 1)):
        n = s.node(None, t, None, kids)
        ti = s.acc(struct.pack("<5f", *[period*i/4 for i in range(5)]), 5126, "SCALAR", 5, mm=([0], [period]))
        ro = s.acc(b"".join(struct.pack("<4f", *q(axis, 2*P*i/4)) for i in range(5)), 5126, "VEC4", 5)
        s.an.append({"samplers": [{"input": ti, "output": ro, "interpolation": "LINEAR"}], "channels": [{"sampler": 0, "target": {"node": n, "path": "rotation"}}]})
        return n
    def panel(s, L, W, z=0):  # solar wing, long axis Z
        k = [s.part(box(W, .05, L), s.mt["silver"]), s.part(box(W - .12, .075, L - .12), s.mt["cell"])]
        k += [s.part(box(W, .09, .035), s.mt["silver"], (0, 0, L*(i/4 - .5))) for i in range(1, 4)]
        k += [s.part(box(.03, .09, L), s.mt["silver"], (W/6*i, 0, 0)) for i in (-1, 1)]
        return s.node(None, (0, 0, z), None, k)
    def save(s, name, roots):
        j = {"asset": {"version": "2.0", "generator": "overhead"}, "scene": 0, "scenes": [{"nodes": roots}], "nodes": s.n, "meshes": s.me,
             "materials": s.m, "accessors": s.ac, "bufferViews": s.bv}
        if s.an: j["animations"] = s.an
        js = json.dumps(j, separators=(",", ":")).encode(); js += b" " * (-len(js) % 4)
        bn = bytes(s.b) + b"\0" * (-len(s.b) % 4); j["buffers"] = [{"byteLength": len(bn)}]
        js = json.dumps(j, separators=(",", ":")).encode(); js += b" " * (-len(js) % 4)
        (OUT / f"{name}.glb").write_bytes(struct.pack("<III", 0x46546C67, 2, 28 + len(js) + len(bn)) + struct.pack("<II", len(js), 0x4E4F534A) + js + struct.pack("<II", len(bn), 0x004E4942) + bn)

def generic():
    g = G(); m = g.mt
    r = [g.part(box(2.2, 2.2, 2.6), m["gold"]), g.part(box(2.3, .25, 2.7), m["silver"], (0, 1.2, 0)), g.part(box(1.2, .8, 1.2), m["dark"], (0, -1.4, 0)),
         g.part(cyl(.06, 1.0), m["silver"], (.4, 1.8, 0)), g.part(cyl(.1, .9, r2=.95), m["white"], (-.3, 1.9, 0)),
         g.spin([g.panel(7, 2.6, 4.8), g.panel(7, 2.6, -4.8)], (0, 0, 0), 40)]
    g.save("generic", r)

def iss():
    g = G(); m = g.mt; r = [g.part(box(1.8, 1.8, 108), m["silver"], (0, 5, 0)), g.part(cyl(.8, 6), m["silver"], (0, 2.5, 0))]
    for x, l, rad, c in ((-18, 12, 2.1, "gold"), (-6, 11, 2.3, "white"), (5, 13.4, 2.3, "white"), (16, 9, 2.1, "silver")):
        r.append(g.part(cyl(rad, l), m[c], (x, 0, 0), QX))
    r += [g.part(cyl(1.4, 22), m["white"], (-6, 0, 0), QZ), g.part(cyl(1.5, 7, r2=.9), m["silver"], (22, 0, 0), QX)]
    for z in (-21, -13, 13, 21): r.append(g.part(box(10, .12, 3.6), m["white"], (0, 5.2, z)))
    for z in (-46, -33, 33, 46): r.append(g.spin([g.part(box(.1, 35, 11.7), m["cell"], (0, y, 0)) for y in (-19.5, 19.5)] + [g.part(cyl(.15, 4), m["silver"], (0, 0, 0))], (0, 5, z), 40))
    g.save("iss", r)

def starlink():
    g = G(); m = g.mt
    r = [g.part(box(2.8, .18, 1.4), m["white"]), g.part(box(1.6, .05, .9), m["dark"], (0, -.12, 0)), g.part(box(.7, .06, .5), m["silver"], (.5, .1, 0)),
         g.spin([g.panel(8.1, 2.8, 4.8)], (0, 0, 0), 50)]
    g.save("starlink", r)

def gps():
    g = G(); m = g.mt
    r = [g.part(box(1.9, 1.8, 2.1), m["gold"]), g.part(cyl(.04, 1.4), m["silver"], (0, 1.6, 0)), g.part(cyl(.6, .15), m["white"], (0, -1.0, 0)),
         g.spin([g.panel(3.2, 1.6, 2.6), g.panel(3.2, 1.6, -2.6)], (0, 0, 0), 30)]
    r += [g.part(cyl(.11, .4), m["silver"], (.55*math.cos(a), -1.2, .55*math.sin(a))) for a in [2*P*i/6 for i in range(6)]] + [g.part(cyl(.11, .4), m["silver"], (0, -1.2, 0))]
    g.save("gps", r)

def weather():
    g = G(); m = g.mt
    r = [g.part(box(1.9, 1.2, 2.0), m["gold"], (0, -.6, 0)), g.part(box(1.9, 1.3, 2.0), m["white"], (0, .65, 0)), g.part(cyl(.05, 1.2), m["silver"], (-.5, 1.9, .3)),
         g.spin([g.panel(6.5, 1.8, 4.2)], (0, 0, 0), 35),
         g.spin([g.part(cyl(.3, 1.0), m["silver"], (.55, 0, 0), QX), g.part(cyl(.18, .5), m["dark"], (1.1, 0, 0), QX)], (0, 1.6, 0), 6, (0, 1, 0))]
    g.save("weather", r)

def science():
    g = G(); m = g.mt
    r = [g.part(cyl(1.2, 9), m["silver"], (2, 0, 0), QX), g.part(cyl(1.55, 3.5), m["gold"], (-3.8, 0, 0), QX), g.part(cyl(1.15, .1), m["dark"], (6.55, 0, 0), QX),
         g.part(cyl(.05, 3.4), m["silver"], (-3, 1.9, 0)), g.part(cyl(.55, .08), m["white"], (-3, 3.7, 0)),
         g.spin([g.panel(7, 2.6, 4.4), g.panel(7, 2.6, -4.4)], (-2.5, 0, 0), 45)]
    g.save("science", r)

for f in (generic, iss, starlink, gps, weather, science): f()
print("models written to", OUT)
