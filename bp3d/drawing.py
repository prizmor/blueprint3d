"""Чертёж из модели: ортогональные проекции со скрытыми линиями (HLR OpenCascade),
сечения плоскостями, выносные виды, размеры, позиции, спецификация, основная надпись.

Всё геометрическое на листе вычислено из тел модели — нарисовать «не то» нельзя.
Аннотации (размеры, выноски) задаются в спецификации 3D-точками.
"""
import math
from build123d import Compound, Edge, GeomType, Plane, Vector

# ------------------------------------------------------------------ SVG
class Sheet:
    def __init__(self, w, h):
        self.w, self.h = w, h
        self.out = []
        self.clip_n = 0

    def E(self, s):
        self.out.append(s)

    def line(self, x1, y1, x2, y2, cls="d", extra=""):
        self.E(f'<line class="{cls}" x1="{F(x1)}" y1="{F(y1)}" x2="{F(x2)}" y2="{F(y2)}" {extra}/>')

    def pl(self, pts, cls, closed=False, extra=""):
        if len(pts) < 2:
            return
        tag = "polygon" if closed else "polyline"
        self.E(f'<{tag} class="{cls}" points="{" ".join(F(x) + "," + F(y) for x, y in pts)}" {extra}/>')

    def path(self, rings, cls, extra=""):
        d = " ".join("M" + " L".join(F(x) + "," + F(y) for x, y in r) + "Z" for r in rings if len(r) > 2)
        self.E(f'<path class="{cls}" fill-rule="evenodd" d="{d}" {extra}/>')

    def text(self, x, y, s, size=2.5, anchor="middle", rot=0, weight=None, style=None):
        tr = f' transform="rotate({F(rot)} {F(x)} {F(y)})"' if rot else ""
        w = f' font-weight="{weight}"' if weight else ""
        st = f' font-style="{style}"' if style else ""
        s = str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        self.E(f'<text x="{F(x)}" y="{F(y)}" font-size="{F(size)}" text-anchor="{anchor}"{tr}{w}{st}>{s}</text>')

    def begin_clip(self, kind, *a):
        self.clip_n += 1
        cid = f"clp{self.clip_n}"
        if kind == "circle":
            shape = f'<circle cx="{F(a[0])}" cy="{F(a[1])}" r="{F(a[2])}"/>'
        else:
            shape = f'<rect x="{F(a[0])}" y="{F(a[1])}" width="{F(a[2])}" height="{F(a[3])}"/>'
        self.E(f'<clipPath id="{cid}">{shape}</clipPath><g clip-path="url(#{cid})">')

    def end_clip(self):
        self.E("</g>")


def F(v):
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


# ------------------------------------------------------------------ проекции
CAMERAS = {
    # направление взгляда (от камеры к объекту) и «верх» листа
    "side":  ((0, 1, 0), (0, 0, 1)),     # вид слева (камера со стороны -Y)
    "front": ((1, 0, 0), (0, 0, 1)),     # вид спереди (камера перед объектом, -X)
    "top":   ((0, 0, -1), (-1, 0, 0)),   # вид сверху
    "rear":  ((-1, 0, 0), (0, 0, 1)),
    "right": ((0, -1, 0), (0, 0, 1)),
    "iso":   ((0.62, 0.62, -0.48), (0, 0, 1)),   # аксонометрия: спереди-сбоку-сверху (со стороны вида сбоку)
}


class ViewProj:
    """Проекция модели на плоскость вида + отображение 3D -> 2D вида -> лист."""

    # Режим скрытых линий по умолчанию для новых проекций (лист может задать S["hlr"] = "poly"):
    #   "exact" — точный HLR OpenCascade (кривые как есть; на сборках из сотен тел с B-сплайнами
    #             считает минутами и иногда теряет грани);
    #   "poly"  — полигональный HLR по густой сетке (секунды, устойчив; контуры — мелкие ломаные).
    MODE = "exact"
    DEFLECTION = (0.25, 0.1)       # сетка для "poly": линейное отклонение, мм; угловое, рад
    CHORD_TOL = 0.06               # точный режим: допустимая стрела хорды при замене кривой ломаной, мм модели

    def __init__(self, kind, look_at, top_up=None):
        d, up = CAMERAS[kind]
        if kind == "top" and top_up:
            up = top_up
        self.kind = kind
        self.L = Vector(*look_at)
        self.origin = self.L - Vector(*d) * 1.0e5
        self.up = up
        self._calibrate()

    def _project(self, shape):
        sh = shape if hasattr(shape, "project_to_viewport") else Compound([shape])
        if self.MODE == "poly" and sh.faces():
            return self._project_poly(sh)
        vis, hid = sh.project_to_viewport(tuple(self.origin), viewport_up=self.up, look_at=tuple(self.L))
        if not vis and not hid and sh.faces():
            # Точный HLR OpenCascade иногда молча отдаёт пустоту на сложных телах —
            # тогда считаем полигональным HLR по сетке (тот же проектор, те же координаты).
            vis, hid = self._project_poly(sh)
        return vis, hid

    def _project_poly(self, sh):
        from OCP.BRepMesh import BRepMesh_IncrementalMesh
        from OCP.HLRBRep import HLRBRep_PolyAlgo, HLRBRep_PolyHLRToShape
        from OCP.HLRAlgo import HLRAlgo_Projector
        from OCP.gp import gp_Ax1, gp_Ax2
        from OCP.TopExp import TopExp_Explorer
        from OCP.TopAbs import TopAbs_EDGE
        from build123d import Edge as BEdge
        BRepMesh_IncrementalMesh(sh.wrapped, self.DEFLECTION[0], False, self.DEFLECTION[1], True)
        algo = HLRBRep_PolyAlgo()
        algo.Load(sh.wrapped)
        d = (self.origin - self.L).normalized()
        ax = gp_Ax2()
        ax.SetAxis(gp_Ax1(self.origin.to_pnt(), d.to_dir()))
        ax.SetYDirection(Vector(*self.up).normalized().to_dir())
        algo.Projector(HLRAlgo_Projector(ax))
        algo.Update()
        to = HLRBRep_PolyHLRToShape()
        to.Update(algo)

        def edges(c):
            out = []
            if c.IsNull():
                return out
            ex = TopExp_Explorer(c, TopAbs_EDGE)
            while ex.More():
                out.append(BEdge(ex.Current()))
                ex.Next()
            return out
        vis = edges(to.VCompound()) + edges(to.OutLineVCompound()) + edges(to.Rg1LineVCompound())
        hid = edges(to.HCompound()) + edges(to.OutLineHCompound())
        return vis, hid

    def _calibrate(self):
        o2 = None
        cols = []
        for v in ((100, 0, 0), (0, 100, 0), (0, 0, 100)):
            e = Edge.make_line(tuple(self.L), tuple(self.L + Vector(*v)))
            vis, hid = self._project(Compound([e]))
            es = list(vis) + list(hid)
            if not es:
                cols.append((0.0, 0.0))
                continue
            a, b = es[0].position_at(0), es[0].position_at(1)
            # ребро может прийти развёрнутым: начало — ближайшее к уже найденному началу
            if o2 is not None and math.dist((b.X, b.Y), o2) < math.dist((a.X, a.Y), o2):
                a, b = b, a
            if o2 is None:
                o2 = (a.X, a.Y)
            cols.append(((b.X - a.X) / 100, (b.Y - a.Y) / 100))
        self.o2 = o2 or (0.0, 0.0)
        self.M = cols   # столбцы: образы ортов X, Y, Z

    def uv(self, p):
        """3D-точка -> координаты вида (мм мира, ось v вверх), относительно look_at."""
        d = Vector(*p) - self.L
        return (self.M[0][0] * d.X + self.M[1][0] * d.Y + self.M[2][0] * d.Z,
                self.M[0][1] * d.X + self.M[1][1] * d.Y + self.M[2][1] * d.Z)

    def project(self, shapes):
        vis, hid = self._project(Compound(list(shapes)))
        out = ([self._poly(e) for e in vis], [self._poly(e) for e in hid])
        out = [p for p in out[0] if p], [p for p in out[1] if p]
        if self.MODE == "poly":      # полигональный HLR отдаёт тысячи отрезков: сшиваем их в ломаные
            out = _chain(out[0]), _chain(out[1])
        return out

    def _poly(self, e):
        if e.length < 1e-6:          # вырожденные рёбра HLR пропускаем
            return None
        try:
            return self._poly_raw(e)
        except Exception:
            a, b = e.start_point(), e.end_point()
            return [(a.X - self.o2[0], a.Y - self.o2[1]), (b.X - self.o2[0], b.Y - self.o2[1])]

    def _poly_raw(self, e):
        def at(t):
            p = e.position_at(t)
            return (p.X - self.o2[0], p.Y - self.o2[1])
        if e.geom_type == GeomType.LINE:
            return [at(0), at(1)]
        # Шаг только по длине (12 мм) превращал мелкие окружности в шестиугольники (ножка Ø24, отверстие,
        # скругление): число отрезков удваивается, пока стрела хорды не станет меньше CHORD_TOL.
        n = max(6, min(160, int(e.length / 12)))
        out = [at(i / n) for i in range(n + 1)]
        while n < 160:
            mid = [at((i + 0.5) / n) for i in range(n)]
            dev = max(_off_chord(m, out[i], out[i + 1]) for i, m in enumerate(mid))
            if dev <= self.CHORD_TOL:
                break
            out = [q for pair in zip(out, mid) for q in pair] + [out[-1]]
            n *= 2
        return out


def _off_chord(p, a, b):
    """Расстояние от точки p до хорды a–b (2D)."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    l = math.hypot(dx, dy)
    if l < 1e-9:
        return math.dist(p, a)
    return abs((p[0] - a[0]) * dy - (p[1] - a[1]) * dx) / l


def _chain(polys, tol=0.02):
    """Сшить отрезки с общими концами в длинные ломаные (меньше SVG, ровнее стыки линий).
    В узлах, где сходится больше двух линий, цепочка обрывается."""
    key = lambda p: (round(p[0] / tol), round(p[1] / tol))
    ends = {}
    for i, p in enumerate(polys):
        for k in (key(p[0]), key(p[-1])):
            ends.setdefault(k, []).append(i)
    used = [False] * len(polys)
    out = []
    for i, p in enumerate(polys):
        if used[i]:
            continue
        used[i] = True
        line = list(p)
        for _ in range(2):                       # наращиваем с конца, затем разворачиваем и с другого
            while True:
                k = key(line[-1])
                nxt = [j for j in ends.get(k, []) if not used[j]]
                if len(ends.get(k, [])) != 2 or not nxt:
                    break
                j = nxt[0]
                used[j] = True
                q = polys[j]
                line += (q[1:] if key(q[0]) == k else q[-2::-1])
            line.reverse()
        out.append(line)
    return out


def mesh_outline(shape, proj, px=1.5, bias=6.0):
    """Видимый контур тела-меша (MeshShape) на виде: силуэтные рёбра, не закрытые самим телом.
    Видимость — по буферу глубины с шагом px мм. Возвращает ломаные в координатах вида, как ViewProj.project."""
    import numpy as np
    V, T = np.asarray(shape.V, float), np.asarray(shape.T, int)
    d = np.asarray(CAMERAS[proj.kind][0], float)
    d = d / np.linalg.norm(d)
    L = np.array([proj.L.X, proj.L.Y, proj.L.Z])
    UV = (V - L) @ np.array(proj.M)
    D = (V - L) @ d
    fn = np.cross(V[T[:, 1]] - V[T[:, 0]], V[T[:, 2]] - V[T[:, 0]])
    front = fn @ d < 0
    lo = UV.min(axis=0) - 2 * px
    W, H = (np.ceil((UV.max(axis=0) - lo) / px) + 3).astype(int)
    zb = np.full((H, W), np.inf)
    P = (UV - lo) / px
    for t in T[front]:                                  # буфер глубины по лицевым треугольникам
        a, b, c = P[t]
        x0, x1 = int(min(a[0], b[0], c[0])), int(max(a[0], b[0], c[0])) + 1
        y0, y1 = int(min(a[1], b[1], c[1])), int(max(a[1], b[1], c[1])) + 1
        den = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        if abs(den) < 1e-12:
            continue
        xs, ys = np.meshgrid(np.arange(x0, x1 + 1) + 0.0, np.arange(y0, y1 + 1) + 0.0)
        w0 = ((b[1] - c[1]) * (xs - c[0]) + (c[0] - b[0]) * (ys - c[1])) / den
        w1 = ((c[1] - a[1]) * (xs - c[0]) + (a[0] - c[0]) * (ys - c[1])) / den
        w2 = 1 - w0 - w1
        m = (w0 >= -0.02) & (w1 >= -0.02) & (w2 >= -0.02)
        if not m.any():
            continue
        z = w0 * D[t[0]] + w1 * D[t[1]] + w2 * D[t[2]]
        blk = zb[y0:y1 + 1, x0:x1 + 1]
        np.minimum(blk, np.where(m, z, np.inf), out=blk)
    E = np.sort(np.concatenate([T[:, [0, 1]], T[:, [1, 2]], T[:, [2, 0]]]), axis=1)
    fid = np.tile(np.arange(len(T)), 3)
    order = np.lexsort((E[:, 1], E[:, 0]))
    E, fid = E[order], fid[order]
    same = (E[1:] == E[:-1]).all(axis=1)
    pair = np.nonzero(same)[0]
    sil = pair[front[fid[pair]] != front[fid[pair + 1]]]
    out = []
    for a, b in E[sil]:
        vis = 0
        for f in (0.25, 0.5, 0.75):
            q = P[a] * (1 - f) + P[b] * f
            x, y = int(round(q[0])), int(round(q[1]))
            dz = D[a] * (1 - f) + D[b] * f
            if 0 <= x < W and 0 <= y < H and dz <= zb[y, x] + bias:
                vis += 1
        if vis >= 2:
            out.append([tuple(UV[a]), tuple(UV[b])])
    return _chain(out, tol=0.05)


class FreeProj:
    """Проекция на произвольную секущую плоскость: начало origin, нормаль normal, «верх» листа — up."""

    def __init__(self, origin, normal, up=(0, 0, 1)):
        import numpy as np
        self.o = np.asarray(origin, float)
        n = np.asarray(normal, float)
        self.n = n / np.linalg.norm(n)
        u = np.asarray(up, float)
        u = u - self.n * (u @ self.n)
        self.ey = u / np.linalg.norm(u)
        self.ex = np.cross(self.ey, self.n)
        self.kind = "free"

    def uv(self, p):
        import numpy as np
        d = np.asarray(p, float) - self.o
        return (float(d @ self.ex), float(d @ self.ey))


class Placed:
    """Вид на листе: масштаб k и точка листа, куда попадает look_at."""

    def __init__(self, proj, k, at):
        self.proj, self.k, self.at = proj, k, at

    def s(self, p3):
        u, v = self.proj.uv(p3)
        return self.s2(u, v)

    def s2(self, u, v):
        return (self.at[0] + u * self.k, self.at[1] - v * self.k)


# ------------------------------------------------------------------ аннотации
def dim(sh, pv, kind, a, b, level, text=None):
    """Линейный размер. kind 'h' — по горизонтали листа, 'v' — по вертикали. level — координата листа."""
    ax, ay = pv.s(a)
    bx, by = pv.s(b)
    ua, va = pv.proj.uv(a)
    ub, vb = pv.proj.uv(b)
    if kind == "h":
        for x, y in ((ax, ay), (bx, by)):
            d = 1 if level > y else -1
            sh.line(x, y + d * 0.8, x, level + d * 1.5)
        sh.line(ax, level, bx, level, "d", 'marker-start="url(#arr)" marker-end="url(#arr)"')
        t = text if text is not None else F(round(abs(ua - ub)))
        sh.text((ax + bx) / 2, level - 0.8, t, 2.5)
    else:
        for x, y in ((ax, ay), (bx, by)):
            d = 1 if level > x else -1
            sh.line(x + d * 0.8, y, level + d * 1.5, y)
        sh.line(level, ay, level, by, "d", 'marker-start="url(#arr)" marker-end="url(#arr)"')
        t = text if text is not None else F(round(abs(va - vb)))
        sh.text(level - 0.8, (ay + by) / 2, t, 2.5, rot=-90)


def dim_dia(sh, pv, c3, r, ang, text):
    cu, cv = pv.proj.uv(c3)
    a = math.radians(ang)
    p1 = pv.s2(cu + r * math.cos(a), cv + r * math.sin(a))
    p2 = pv.s2(cu - r * math.cos(a), cv - r * math.sin(a))
    sh.line(*p1, *p2, "d", 'marker-start="url(#arr)" marker-end="url(#arr)"')
    m = pv.s2(cu + 0.62 * r * math.cos(a), cv + 0.62 * r * math.sin(a))
    sh.text(m[0] - math.sin(a) * 0.9, m[1] - math.cos(a) * 0.9, text, 2.5, rot=-ang)


def dim_rad(sh, pv, c3, r, ang, text):
    cu, cv = pv.proj.uv(c3)
    a = math.radians(ang)
    p1 = pv.s2(cu + 0.45 * r * math.cos(a), cv + 0.45 * r * math.sin(a))
    p2 = pv.s2(cu + r * math.cos(a), cv + r * math.sin(a))
    sh.line(*p1, *p2, "d", 'marker-end="url(#arr)"')
    m = pv.s2(cu + 0.72 * r * math.cos(a), cv + 0.72 * r * math.sin(a))
    rot = -ang if -90 <= ang <= 90 else 180 - ang
    sh.text(m[0] - math.sin(a) * 0.9, m[1] - math.cos(a) * 0.9, text, 2.5, rot=rot)


def dim_angle(sh, pv, v3, a3, b3, r, text, tr=None):
    """Угловой размер: вершина v3, стороны к a3 и b3; r — радиус дуги на листе, мм."""
    vx, vy = pv.s(v3)
    ang = [math.atan2(q[1] - vy, q[0] - vx) for q in (pv.s(a3), pv.s(b3))]
    d = (ang[1] - ang[0] + math.pi) % (2 * math.pi) - math.pi
    for a in ang:
        sh.line(vx, vy, vx + (r + 2.5) * math.cos(a), vy + (r + 2.5) * math.sin(a))
    p0 = (vx + r * math.cos(ang[0]), vy + r * math.sin(ang[0]))
    p1 = (vx + r * math.cos(ang[0] + d), vy + r * math.sin(ang[0] + d))
    sh.E(f'<path class="d" d="M{F(p0[0])},{F(p0[1])} A{F(r)},{F(r)} 0 0 {1 if d > 0 else 0} {F(p1[0])},{F(p1[1])}" '
         f'marker-start="url(#arr)" marker-end="url(#arr)"/>')
    am = ang[0] + d / 2
    tr = tr if tr is not None else r + 3.2
    sh.text(vx + tr * math.cos(am), vy + tr * math.sin(am) + 0.9, text, 2.5)


def balloon(sh, pv, p3, dx, dy, n):
    x, y = pv.s(p3)
    x2, y2 = x + dx, y + dy
    sh.E(f'<circle class="dot" cx="{F(x)}" cy="{F(y)}" r="0.45"/>')
    sh.line(x, y, x2, y2)
    w = 3.2 + 1.6 * len(str(n))
    xa, xb = (x2, x2 + w) if dx >= 0 else (x2 - w, x2)
    sh.line(xa, y2, xb, y2)
    sh.text((xa + xb) / 2, y2 - 0.7, str(n), 3.2)


def note(sh, pv, p3, dx, dy, s, size=2.3):
    x, y = pv.s(p3)
    x2, y2 = x + dx, y + dy
    sh.E(f'<circle class="dot" cx="{F(x)}" cy="{F(y)}" r="0.4"/>')
    sh.line(x, y, x2, y2)
    w = len(s) * size * 0.47 + 1
    if dx >= 0:
        sh.line(x2, y2, x2 + w, y2)
        sh.text(x2 + 0.5, y2 - 0.6, s, size, anchor="start")
    else:
        sh.line(x2 - w, y2, x2, y2)
        sh.text(x2 - 0.5, y2 - 0.6, s, size, anchor="end")


def cut_mark(sh, pv, a3, b3, letter, look):
    x1, y1 = pv.s(a3)
    x2, y2 = pv.s(b3)
    L = math.hypot(x2 - x1, y2 - y1)
    ux, uy = (x2 - x1) / L, (y2 - y1) / L
    for sx, sy, sg in ((x1, y1, 1), (x2, y2, -1)):
        sh.line(sx, sy, sx + ux * 6 * sg, sy + uy * 6 * sg, "cut")
        sh.line(sx, sy, sx + look[0] * 6, sy + look[1] * 6, "d", 'marker-end="url(#arrc)"')
        sh.text(sx + look[0] * 8.5 - ux * sg * 1.5, sy + look[1] * 8.5 + 1.2 - uy * sg * 1.5, letter, 4, weight="bold")
    sh.line(x1, y1, x2, y2, "c")


def view_title(sh, x, y, s, sub):
    sh.text(x, y, s, 4.2, weight="bold")
    if sub:
        sh.text(x, y + 4.2, sub, 2.8)
    w = len(s) * 4.2 * 0.5
    sh.line(x - w / 2, y + 1, x + w / 2, y + 1, "t")


# ------------------------------------------------------------------ сборка листа
def ground(sh, pv, x0, x1, z=0, axis="x"):
    if axis == "x":
        a, b = pv.s((x0, 0, z)), pv.s((x1, 0, z))
    else:
        a, b = pv.s((0, x0, z)), pv.s((0, x1, z))
    sh.line(*a, *b, "m")
    n = int(abs(b[0] - a[0]) / 4)
    for i in range(n + 1):
        x = min(a[0], b[0]) + i * 4
        sh.line(x, a[1], x - 1.6, a[1] + 1.6, "t")


def draw_view(sh, pv, vis, hid, internal_lines):
    for pts in hid:
        sh.pl([pv.s2(*p) for p in pts], "h")
    for pts in internal_lines:
        sh.pl([pv.s2(*p) for p in pts], "h")
    for pts in vis:
        sh.pl([pv.s2(*p) for p in pts], "m")


def _area(r):
    return 0.5 * sum(r[i][0] * r[(i + 1) % len(r)][1] - r[(i + 1) % len(r)][0] * r[i][1] for i in range(len(r)))


def _perim(r):
    return sum(math.dist(r[i], r[(i + 1) % len(r)]) for i in range(len(r)))


def section_rings(shapes, plane):
    """Сечение тел плоскостью -> список (кольца) 3D-точек по граням."""
    out = []
    for s in shapes:
        try:
            faces = s.intersect(plane)
        except Exception:
            continue
        if not faces:
            continue
        for f in faces:
            if not hasattr(f, "outer_wire"):
                continue
            rings = []
            for w in [f.outer_wire()] + list(f.inner_wires()):
                # рёбра контура приходят в произвольном порядке и направлении: сшиваем цепочку
                # по ближайшим концам, иначе узкие сечения оболочек превращаются в «клинья»
                segs = []
                for e in w.edges():
                    if e.length < 1e-6:
                        continue
                    n = max(2, min(80, int(e.length / 4)))
                    try:
                        segs.append([e.position_at(i / n) for i in range(n + 1)])
                    except Exception:
                        segs.append([e.start_point(), e.end_point()])
                ring = segs.pop(0) if segs else []
                while segs:
                    end = ring[-1]
                    j, rev, best = 0, False, None
                    for i, sg in enumerate(segs):
                        for r, q in ((False, sg[0]), (True, sg[-1])):
                            dd = (q - end).length
                            if best is None or dd < best:
                                j, rev, best = i, r, dd
                    sg = segs.pop(j)
                    ring += (sg[::-1] if rev else sg)[1:]
                if len(ring) > 2:
                    rings.append(ring)
            out.append(rings)
    return out


def _inside(pt, ring):
    x, y = pt
    c = False
    for i in range(len(ring)):
        (x1, y1), (x2, y2) = ring[i], ring[(i + 1) % len(ring)]
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            c = not c
    return c


def _area_evenodd(rings):
    """Площадь заливки evenodd: кольцо на чётной глубине вложенности прибавляется, на нечётной вычитается."""
    a = 0.0
    for i, r in enumerate(rings):
        depth = sum(1 for j, o in enumerate(rings) if j != i and _inside(r[0], o))
        a += abs(_area(r)) * (1 if depth % 2 == 0 else -1)
    return a


def mesh_section(m, origin, normal):
    """Сечение меша (QuadMesh или MeshShape) плоскостью: [[кольцо 3D-точек, ...]] — замкнутые контуры
    одной детали одной группой (вложенные кольца закрашиваются по правилу evenodd)."""
    from .mesh import slice_mesh
    T = m.triangles() if hasattr(m, "triangles") else m.T
    loops = [[tuple(map(float, q)) for q in l[:-1]] for l in slice_mesh(m.V, T, origin, normal)
             if len(l) > 3 and abs(l[0] - l[-1]).max() < 1e-9]
    return [loops] if loops else []


def _match(p, keys, default=True):
    """Деталь подходит под список ключей (точное имя или префикс)."""
    if not keys:
        return default
    return any(p.key == k or p.key.startswith(k) for k in keys)


def build_sheet(model, S, theme):
    """S — словарь листа из спецификации. Возвращает текст SVG."""
    return wrap_svg(build_body(model, S), theme, model.title)


def build_body(model, S):
    """Вся геометрия и аннотации листа (не зависит от темы) -> Sheet."""
    from . import kit
    W, H = S.get("size", (841, 594))
    sh = Sheet(W, H)
    ViewProj.MODE = S.get("hlr", "exact")
    ViewProj.DEFLECTION = S.get("hlr_deflection", (0.25, 0.1))
    placed = {}
    cache = {}
    for v in S["views"]:
        proj = ViewProj(v["kind"], v["look_at"], v.get("up"))
        pv = Placed(proj, v["k"], v["at"])
        placed[v["id"]] = pv
        keys, groups = v.get("parts"), v.get("groups", ("ext",))
        sel = [p for p in model.parts if _match(p, keys) and not _match(p, v.get("exclude"), False)]
        ext = [p.shape for p in sel if p.group in groups]
        internal = [p.shape for p in sel if p.group == "int" and "int" not in groups]
        phantom = [p.shape for p in sel if p.group == "phantom" and not hasattr(p.shape, "T")]
        phantom_mesh = [p.shape for p in sel if p.group == "phantom" and hasattr(p.shape, "T")]
        vis, hid = proj.project(ext)
        ivis, ihid = proj.project(internal) if internal and v.get("internal", True) else ([], [])
        if not v.get("hidden", True):
            hid = []
        cache[v["id"]] = (vis, hid, ivis + ihid)
        if v.get("clip"):
            sh.begin_clip("rect", *v["clip"])
        if v.get("ground"):
            g = v["ground"]
            ground(sh, pv, g[0], g[1], 0, g[2] if len(g) > 2 else "x")
        # сетка теоретических сечений (тонкими): объём поверхностей читается по ним
        for g in v.get("grid", []):
            shapes = [p.shape for p in model.parts if _match(p, g.get("parts"))]
            for val in g["values"]:
                for pts in kit.section_curves(shapes, g["axis"], val):
                    sh.pl([pv.s(p) for p in pts], "g")
        if phantom and v.get("phantom", True):
            pvis, _ = proj.project(phantom)
            for pts in pvis:
                sh.pl([pv.s2(*p) for p in pts], "ph")
        if v.get("phantom", True):                      # тело персонажа: видимый контур меша
            for ms in phantom_mesh:
                for pts in mesh_outline(ms, proj):
                    sh.pl([pv.s2(*p) for p in pts], "ph")
        draw_view(sh, pv, vis, hid, ivis + ihid)
        if v.get("dynamics") and getattr(model, "body", None) is not None:
            draw_dynamics(sh, pv, model, sel)
        if v.get("folds"):
            draw_folds(sh, pv, proj, sel)
        if v.get("clip"):
            sh.end_clip()
        if v.get("title"):
            view_title(sh, *v["title_at"], v["title"], v.get("sub", ""))

    # теоретические обводы: наложенные сечения плоскостями (без проекции тел)
    for pl in S.get("plans", []):
        proj = ViewProj(pl["kind"], pl["look_at"], pl.get("up"))
        pv = Placed(proj, pl["k"], pl["at"])
        placed[pl["id"]] = pv
        if pl.get("clip"):
            sh.begin_clip("rect", *pl["clip"])
        labels = []
        for st in pl["sets"]:
            shapes = [p.shape for p in model.parts if _match(p, st.get("parts"))]
            for val in st["values"]:
                best = None
                for pts in kit.section_curves(shapes, st["axis"], val):
                    if st.get("half") and all(p[1] < -1 for p in pts):
                        continue
                    q = [pv.s(p) for p in pts]
                    sh.pl(q, st.get("cls", "m2"))
                    for a in (q[0], q[-1]):
                        key = st.get("label_at", "top")
                        score = {"top": -a[1], "bottom": a[1], "left": -a[0], "right": a[0]}[key]
                        if best is None or score > best[0]:
                            best = (score, a)
                if best and st.get("labels", True):
                    dx, dy = st.get("label_d", (0, -1.2))
                    labels.append((best[1][0] + dx, best[1][1] + dy, st.get("fmt", "{:g}").format(val),
                                   st.get("label_anchor", "middle")))
        if pl.get("clip"):
            sh.end_clip()
        for x, y, t, anc in labels:
            sh.text(x, y, t, 1.9, anchor=anc)
        if pl.get("title"):
            view_title(sh, *pl["title_at"], pl["title"], pl.get("sub", ""))

    # сечения
    for sec in S.get("sections", []):
        if sec["plane"][0] == "free":                    # произвольная плоскость: ("free", точка, нормаль[, верх])
            ax, val = "free", 0.0
            org = tuple(float(c) for c in sec["plane"][1])
            nrm = tuple(float(c) for c in sec["plane"][2])
            plane = Plane(origin=org, z_dir=nrm)
            proj = FreeProj(org, nrm, sec["plane"][3] if len(sec["plane"]) > 3 else (0, 0, 1))
        else:
            ax, val = sec["plane"]
            nrm = {"x": (1, 0, 0), "y": (0, 1, 0), "z": (0, 0, 1)}[ax]
            org = tuple(val * c for c in nrm)
            plane = Plane(origin=org, z_dir=nrm)
            kind = {"x": "front", "y": "side", "z": "top"}[ax]
            proj = ViewProj(kind, sec["look_at"])
        pv = Placed(proj, sec["k"], sec["at"])
        placed["sec:" + sec["id"]] = pv
        sel = [p for p in model.parts if _match(p, sec.get("parts")) and not _match(p, sec.get("exclude"), False)
               and p.group not in ("phantom", "theory")]
        c = sec.get("clip")
        if c:
            a = pv.s(c[0])
            b = pv.s(c[1])
            sh.begin_clip("rect", min(a[0], b[0]), min(a[1], b[1]), abs(b[0] - a[0]), abs(b[1] - a[1]))
        if sec.get("phantom", True):                    # кольцо тела в плоскости разреза — обстановкой
            for p in model.parts:
                if p.group == "phantom" and hasattr(p.shape, "T"):
                    for rings in mesh_section(p.shape, org, nrm):
                        for r in rings:
                            if sec.get("near") is None or min(math.dist(q, org) for q in r) < sec["near"]:
                                sh.pl([pv.s2(*proj.uv(q)) for q in r + r[:1]], "ph")
        if sec.get("behind") and ax != "free":
            # то, что видно за секущей плоскостью: тела обрезаются слоем [плоскость, плоскость + глубина]
            d = sec["behind"]
            lo = [-1e4, -1e4, -1e4]
            hi = [1e4, 1e4, 1e4]
            i = "xyz".index(ax)
            lo[i], hi[i] = val + 0.05, val + d
            if c:
                for j in range(3):
                    if j != i:
                        lo[j] = min(c[0][j], c[1][j]) - 30
                        hi[j] = max(c[0][j], c[1][j]) + 30
            layer = kit.box(lo[0], lo[1], lo[2], hi[0], hi[1], hi[2])
            back = []
            for p in sel:
                if p.group == "glass" or _match(p, sec.get("behind_exclude"), False):
                    continue
                bb = p.shape.bounding_box()
                if any((bb.max.X, bb.max.Y, bb.max.Z)[j] < lo[j] or (bb.min.X, bb.min.Y, bb.min.Z)[j] > hi[j] for j in range(3)):
                    continue
                try:
                    r = p.shape & layer
                    if r is not None and r.faces():
                        back.append(r)
                except Exception:
                    pass
            if back:
                bvis, _ = proj.project(back)
                for pts in bvis:
                    sh.pl([pv.s2(*q) for q in pts], "m2")
        n = 0
        for p in sel:
            if getattr(p, "mesh", "cad") == "quad" or hasattr(p.shape, "T"):
                # квадовая деталь и тело-меш: сечение снимается с самого меша (то, что уйдёт в 3D)
                groups = mesh_section(p.quad if p.quad is not None else p.shape, org, nrm)
                if sec.get("near") is not None:          # только контуры рядом с точкой разреза (один рукав)
                    groups = [[r for r in g if min(math.dist(q, org) for q in r) < sec["near"]] for g in groups]
                    groups = [g for g in groups if g]
            else:
                groups = [[[(pt.X, pt.Y, pt.Z) for pt in r] for r in rings] for rings in section_rings([p.shape], plane)]
                if sec.get("near") is not None:
                    groups = [g for g in groups if min(math.dist(q, org) for r in g for q in r) < sec["near"]]
            for rings in groups:
                q = [[pv.s2(*proj.uv(pt)) for pt in r] for r in rings]
                # узкие сечения (тонкий лист, меньше ~1,4 мм на листе) зачерняются — ГОСТ 2.306
                area = _area_evenodd(q)
                per = sum(_perim(r) for r in q)
                thin = per > 0 and 2 * area / per < 1.4
                sh.path(q, "sec " + ("blk" if thin else ("hat" if n % 2 == 0 else "hat2")))
            n += 1
        if c:
            sh.end_clip()
        view_title(sh, *sec["title_at"], sec["title"], sec.get("sub", ""))

    # выносные виды
    for dv in S.get("details", []):
        src = placed[dv["view"]]
        vis, hid, ilines = cache[dv["view"]]
        cu, cv = src.proj.uv(dv["center"])
        k = dv["k"]
        at = dv["at"]
        pv = Placed(src.proj, k, (at[0] - cu * k, at[1] + cv * k))
        placed["det:" + dv["letter"]] = pv
        sh.begin_clip("circle", at[0], at[1], dv["r"] * k)
        draw_view(sh, pv, vis, hid if dv.get("hidden", False) else [], [])
        sh.end_clip()
        sh.E(f'<circle class="t" cx="{F(at[0])}" cy="{F(at[1])}" r="{F(dv["r"] * k)}"/>')
        # кружок на исходном виде
        c = src.s(dv["center"])
        sh.E(f'<circle class="t" cx="{F(c[0])}" cy="{F(c[1])}" r="{F(dv["r"] * src.k)}"/>')
        a = math.radians(135)
        px, py = c[0] + dv["r"] * src.k * math.cos(a), c[1] - dv["r"] * src.k * math.sin(a)
        sh.line(px, py, px - 4, py - 4)
        sh.line(px - 4, py - 4, px - 10, py - 4)
        sh.text(px - 7, py - 4.8, dv["letter"], 4, weight="bold")
        view_title(sh, *dv["title_at"], dv["letter"], dv.get("sub", ""))

    # аннотации
    for d in S.get("dims", []):
        kind, vid, a, b, level = d[:5]
        dim(sh, placed[vid], kind, a, b, level, d[5] if len(d) > 5 else None)
    for d in S.get("dias", []):
        dim_dia(sh, placed[d[0]], *d[1:])
    for d in S.get("radii", []):
        dim_rad(sh, placed[d[0]], *d[1:])
    for d in S.get("angles", []):
        dim_angle(sh, placed[d[0]], *d[1:])
    for ln in S.get("lines", []):
        sh.line(*placed[ln[0]].s(ln[1]), *placed[ln[0]].s(ln[2]), ln[3] if len(ln) > 3 else "c")
    for b in S.get("balloons", []):
        balloon(sh, placed[b[0]], *b[1:])
    for n in S.get("notes", []):
        note(sh, placed[n[0]], *n[1:])
    for c in S.get("cuts", []):
        cut_mark(sh, placed[c[0]], *c[1:])
    for t in S.get("texts", []):
        vid, p3, s = t[:3]
        x, y = placed[vid].s(p3)
        sh.text(x + (t[3] if len(t) > 3 else 0), y + (t[4] if len(t) > 4 else 0), s, t[5] if len(t) > 5 else 2.4)

    if "gaps" in S:
        table_gaps(sh, S["gaps"], S["gaps_at"])
    if getattr(model, "body", None) is not None:
        if "measures_at" in S:
            table_measures(sh, model.body, S["measures_at"])
        if "layers_at" in S:
            table_layers(sh, model, S["layers_at"])
        if "dyn_at" in S:
            table_dynamics(sh, model, S["dyn_at"])
    table_parts(sh, model, S)
    if "tech" in S:
        tech_req(sh, S["tech"], S["tech_at"])
    legend(sh, S.get("legend_at", (30, 534)), garment=getattr(model, "body", None) is not None)
    frame_and_title(sh, model, S)
    return sh


def table_parts(sh, model, S):
    bom = model.bom()
    x0, w = sh.w - 5 - 185, 185
    cols = [(0, 9, "Поз."), (9, 68, "Наименование"), (77, 70, "Материал"), (147, 14, "Кол."), (161, 24, "Прим.")]
    hh = 8
    rh = S.get("bom_row", 5.25)
    y1 = sh.h - 5 - 55
    y0 = y1 - hh - rh * len(bom)
    sh.E(f'<rect class="m" x="{F(x0)}" y="{F(y0)}" width="{w}" height="{F(y1 - y0)}"/>')
    sh.line(x0, y0 + hh, x0 + w, y0 + hh, "m")
    for cx, cw, name in cols:
        if cx:
            sh.line(x0 + cx, y0, x0 + cx, y1, "m")
        sh.text(x0 + cx + cw / 2, y0 + 5.4, name, 2.8)
    for i, (n, (name, mat, q, nt)) in enumerate(bom.items()):
        y = y0 + hh + rh * (i + 1)
        sh.line(x0, y, x0 + w, y, "t")
        sh.text(x0 + 4.5, y - 1.5, n, 2.4)
        sh.text(x0 + 10.5, y - 1.5, name, 2.4, anchor="start")
        sh.text(x0 + 78.5, y - 1.5, mat, 2.4, anchor="start")
        sh.text(x0 + 154, y - 1.5, q, 2.4)
        if nt:
            sh.text(x0 + 173, y - 1.5, nt, 2.0)
    sh.text(x0 + w / 2, y0 - 2, "СПЕЦИФИКАЦИЯ (позиции на видах)", 3.2, weight="bold")


def _table(sh, at, title, cols, rows, rh=4.6, size=2.3):
    """Простая таблица: cols = [(ширина, заголовок), ...], rows = [[ячейка, ...], ...]."""
    x0, y0 = at
    w = sum(c[0] for c in cols)
    y1 = y0 + 6.5 + rh * len(rows)
    sh.text(x0 + w / 2, y0 - 2, title, 3.0, weight="bold")
    sh.E(f'<rect class="m" x="{F(x0)}" y="{F(y0)}" width="{F(w)}" height="{F(y1 - y0)}"/>')
    sh.line(x0, y0 + 6.5, x0 + w, y0 + 6.5, "m")
    x = x0
    for cw, name in cols:
        if x > x0:
            sh.line(x, y0, x, y1, "t")
        sh.text(x + cw / 2, y0 + 4.5, name, 2.4)
        x += cw
    for i, r in enumerate(rows):
        y = y0 + 6.5 + rh * (i + 1)
        if i < len(rows) - 1:
            sh.line(x0, y, x0 + w, y, "t")
        x = x0
        for j, ((cw, _), cell) in enumerate(zip(cols, r)):
            if j == 0:
                sh.text(x + 1.5, y - 1.3, cell, size, anchor="start")
            else:
                sh.text(x + cw / 2, y - 1.3, cell, size)
            x += cw


def table_measures(sh, body, at):
    rows = [[n, F(round(v))] for n, v in body.measures_table()]
    _table(sh, at, "МЕРКИ ТЕЛА, мм", [(58, "Мерка"), (16, "Значение")], rows, rh=4.0, size=2.1)


def _dyn_rows(model):
    from .rig import _dyn_list, chains as rig_chains
    rows = []
    for p in model.parts:
        if p.group in ("phantom", "theory"):
            continue
        b = p.bind if p.bind is not None else "auto"
        bind = "веса тела" if (b == "auto" or isinstance(b, dict)) else f"кость {b}"
        zones = _dyn_list(p) if p.mesh == "quad" else []
        if not zones:
            rows.append((p, bind, None, 0, 0))
            continue
        ch = rig_chains(p, model.body)
        for zi, z in enumerate(zones):
            mine = [c for c in ch if c["zone"] == zi]
            rows.append((p, bind, z, len(mine), len(mine[0]["names"]) if mine else 0))
    return rows


def table_layers(sh, model, at):
    seen, rows = set(), []
    for p in model.parts:
        if p.group in ("phantom", "theory") or p.pos in seen:
            continue
        seen.add(p.pos)
        gap = f"{p.info.get('gap', 0):g}" if p.layer else "—"
        th = f"{p.info.get('thickness', 0):g}" if p.mesh == "quad" else "—"
        b = p.bind if p.bind is not None else "auto"
        bind = "веса тела" if (b == "auto" or isinstance(b, dict)) else f"кость {b}"
        rows.append([f"{p.pos}  {p.name}", str(p.layer) if p.layer else "—", gap, th, bind, "да" if p.hides else "—"])
    _table(sh, at, "СЛОИ И ПРИВЯЗКА", [(46, "Поз. Деталь"), (10, "Слой"), (15, "Отступ"), (13, "Толщ."), (24, "Привязка"), (14, "Тело")],
           rows)


def table_dynamics(sh, model, at):
    names = {"stiff": "пружинит", "soft": "обвисает"}
    rows = []
    for p, bind, z, nch, nb in _dyn_rows(model):
        if z is None:
            continue
        rows.append([f"{p.pos}  {p.name}", names.get(z["preset"], z["preset"]), f"{nch} × {nb}",
                     f"{z['stiffness']:g}", f"{z['damping']:g}", f"{z['gravity']:g}", f"{z['radius']:g}",
                     f"{float(z.get('v0', 0.25)):.2f}"])
    if not rows:
        rows = [["нет зон динамики", "", "", "", "", "", "", ""]]
    _table(sh, at, "ДИНАМИКА (кости с пружиной)", [(42, "Поз. Деталь"), (18, "Режим"), (16, "Цеп.×кост."), (13, "Жёстк."),
                                                 (13, "Затух."), (13, "Тяжесть"), (13, "Радиус"), (12, "Старт v")], rows)


def draw_folds(sh, pv, proj, sel):
    """Складки на виде: линии кривых складок режима "geo" — только на стороне, обращённой к зрителю
    (по нормали поверхности детали). Гребень — штрих с точкой, впадина и залом — короткий штрих."""
    import numpy as np
    from scipy.spatial import cKDTree
    d = np.asarray(CAMERAS[proj.kind][0], float) if proj.kind in CAMERAS else None
    for p in sel:
        fl = [f for f in (p.info.get("folds") or []) if "geo" in f.mode and f.P is not None]
        if not fl or p.quad is None:
            continue
        q = p.quad
        outer = np.nonzero(q.vside == 0)[0]
        tree = cKDTree(q.V[outer])
        N = q.vertex_normals()[outer]
        for f in fl:
            vis = np.ones(len(f.P), bool)
            if d is not None:
                vis = (N[tree.query(f.P)[1]] @ d) < -0.05
            cls = "fold" if f.profile in ("ridge", "pipe", "crease") else "fold2"
            run = []
            for k, q3 in enumerate(f.P):
                if vis[k]:
                    run.append(pv.s(tuple(q3)))
                elif len(run) > 1:
                    sh.pl(run, cls)
                    run = []
                else:
                    run = []
            if len(run) > 1:
                sh.pl(run, cls)


def draw_dynamics(sh, pv, model, sel):
    """Зоны динамики на виде: линии цепочек костей (суставы — точки) и линия начала зоны на детали.
    Пружинящие зоны — сплошной утолщённой линией, обвисающие — пунктиром с точкой."""
    from .rig import _dyn_list, chains as rig_chains, _grid_point
    for p in sel:
        if p.mesh != "quad" or not _dyn_list(p):
            continue
        zones = _dyn_list(p)
        for c in rig_chains(p, model.body):
            cls = "dyn" if zones[c["zone"]]["preset"] == "stiff" else "dyn2"
            pts = [pv.s(tuple(q)) for q in c["joints"]]
            sh.pl(pts, cls)
            for x, y in pts:
                sh.E(f'<circle class="dot" cx="{F(x)}" cy="{F(y)}" r="0.5"/>')
            P = p.quad.patches[c["patch"]]
            if c["index"] == 0 and P.closed_u:           # линия начала зоны: ряд сетки при v0
                n = P.G.shape[0] * 2
                row = [pv.s(tuple(_grid_point(P.G, True, i / n, c["v0"]))) for i in range(n + 1)]
                sh.pl(row, "dynz")


def table_gaps(sh, rows, at):
    x0, y0 = at
    w, rh = 258, 6
    cols = [(0, 110, "Сопряжение"), (110, 74, "Зазор"), (184, 74, "Перепад (flush)")]
    y1 = y0 + 8 + rh * len(rows)
    sh.text(x0 + w / 2, y0 - 2, "ЗАЗОРЫ И ПЕРЕПАДЫ, мм", 3.2, weight="bold")
    sh.E(f'<rect class="m" x="{F(x0)}" y="{F(y0)}" width="{w}" height="{F(y1 - y0)}"/>')
    sh.line(x0, y0 + 8, x0 + w, y0 + 8, "m")
    for cx, cw, name in cols:
        if cx:
            sh.line(x0 + cx, y0, x0 + cx, y1, "m")
        sh.text(x0 + cx + cw / 2, y0 + 5.4, name, 2.8)
    for i, r in enumerate(rows):
        y = y0 + 8 + rh * (i + 1)
        sh.line(x0, y, x0 + w, y, "t")
        sh.text(x0 + 3, y - 1.8, r[0], 2.6, anchor="start")
        sh.text(x0 + 147, y - 1.8, r[1], 2.6)
        sh.text(x0 + 221, y - 1.8, r[2], 2.6)


def tech_req(sh, lines, at):
    x, y = at
    sh.text(x + 132, y, "ТЕХНИЧЕСКИЕ ТРЕБОВАНИЯ", 3.4, weight="bold")
    for i, s in enumerate(lines):
        sh.text(x, y + 7 + i * 4.6, s, 2.55, anchor="start")


def legend(sh, at, garment=False):
    x, y = at
    sh.text(x, y, "ТИПЫ ЛИНИЙ И ОБОЗНАЧЕНИЯ", 3.0, anchor="start", weight="bold")
    items = [("m", "видимый контур (проекция модели)"), ("h", "невидимый контур"),
             ("c", "осевая, линия сечения"), ("t", "тонкая, выноски")]
    for i, (c, s) in enumerate(items):
        yy = y + 6 + i * 5
        sh.line(x, yy, x + 22, yy, c)
        sh.text(x + 26, yy + 0.9, s, 2.5, anchor="start")
    sh.E(f'<rect class="t hat" x="{x + 135}" y="{F(y + 2)}" width="12" height="4"/>')
    sh.text(x + 151, y + 4.9, "сечение детали", 2.5, anchor="start")
    sh.text(x, y + 33, "Размеры в мм. Все линии видов вычислены из 3D-модели (Blueprint3D).", 2.5, anchor="start")
    if garment:
        items = [("ph", "тело (обстановка)"), ("dyn", "цепочка костей: пружинит"), ("dyn2", "цепочка костей: обвисает"),
                 ("dynz", "начало зоны динамики"), ("fold", "складка: гребень"), ("fold2", "складка: впадина, залом")]
        for i, (c, s) in enumerate(items):
            yy = y + 6 + i * 5
            sh.line(x + 190, yy, x + 212, yy, c)
            sh.text(x + 216, yy + 0.9, s, 2.5, anchor="start")


def frame_and_title(sh, model, S):
    W, H = sh.w, sh.h
    sh.E(f'<rect class="m" x="20" y="5" width="{W - 25}" height="{H - 10}" style="stroke-width:.7"/>')
    x0, y0 = W - 5 - 185, H - 5 - 55
    sh.E(f'<rect class="m" x="{x0}" y="{y0}" width="185" height="55" style="stroke-width:.7"/>')
    for yy in (5, 10, 15, 20, 25, 30, 35, 40, 45, 50):
        sh.line(x0, y0 + yy, x0 + 65, y0 + yy, "t" if yy not in (25, 30) else "m")
    for xx in (7, 17, 40, 55, 65):
        sh.line(x0 + xx, y0, x0 + xx, y0 + 55, "m")
    sh.line(x0 + 65, y0 + 15, x0 + 185, y0 + 15, "m")
    sh.line(x0 + 65, y0 + 40, x0 + 185, y0 + 40, "m")
    sh.line(x0 + 135, y0 + 15, x0 + 135, y0 + 55, "m")
    sh.line(x0 + 135, y0 + 20, x0 + 185, y0 + 20, "m")
    sh.line(x0 + 135, y0 + 35, x0 + 185, y0 + 35, "m")
    for xx in (155, 167):
        sh.line(x0 + xx, y0 + 20, x0 + xx, y0 + 35, "m")
    sh.text(x0 + 125, y0 + 10, model.code, 5.2, weight="bold")
    tl = S.get("title_lines", [model.title])
    for i, s in enumerate(tl):
        sh.text(x0 + 100, y0 + 23 + i * 5.5, s, 3.6 if i < 2 else 2.8, weight="bold" if i < 2 else None)
    sh.text(x0 + 100, y0 + 49, S.get("doc_type", "Чертёж"), 3.0)
    sh.text(x0 + 145, y0 + 18.6, "Лит.", 2.4)
    sh.text(x0 + 161, y0 + 18.6, "Масса", 2.4)
    sh.text(x0 + 176, y0 + 18.6, "Масштаб", 2.4)
    sh.text(x0 + 145, y0 + 29, S.get("lit", "Э"), 3.4)
    sh.text(x0 + 161, y0 + 29, "—", 3.4)
    sh.text(x0 + 176, y0 + 29, S.get("scale", "1:10"), 3.4)
    sh.text(x0 + 150, y0 + 38.6, "Лист 1", 2.6)
    sh.text(x0 + 172, y0 + 38.6, "Листов 1", 2.6)
    sh.text(x0 + 160, y0 + 49, S.get("org", ""), 5, weight="bold")
    for i, h in enumerate(["Изм.", "Лист", "№ докум.", "Подп.", "Дата"]):
        sh.text(x0 + [3.5, 12, 28.5, 47.5, 60][i], y0 + 28.6, h, 2.0)
    for i, (r, nm) in enumerate([("Разраб.", S.get("author", "Claude")), ("Пров.", ""), ("Т.контр.", ""),
                                 ("Н.контр.", ""), ("Утв.", S.get("approved_by", ""))]):
        yy = y0 + 30 + 5 * (i + 1) - 1.4
        sh.text(x0 + 1, yy, r, 2.3, anchor="start")
        sh.text(x0 + 18, yy, nm, 2.3, anchor="start")
    sh.text(x0 + 59.5, y0 + 33.6, S.get("date", ""), 2.2)
    sh.E(f'<rect class="m" x="20" y="5" width="70" height="14" style="stroke-width:.5"/>')
    sh.text(55, 11, model.code, 3.6)
    sh.text(55, 16.5, "spec " + S.get("spec_hash", "")[:12], 2.2)


THEMES = {
    "blueprint": dict(bg="#0e3763", ink="#e9f2ff", dk="#082848"),
    "print": dict(bg="#ffffff", ink="#141414", dk="#4a4a4a"),
}


def wrap_svg(sh, theme, title):
    th = THEMES[theme]
    css = f"""
svg{{--bg:{th['bg']};--ink:{th['ink']};--dk:{th['dk']};background:var(--bg)}}
text{{fill:var(--ink);font-family:'ISOCPEUR','GOST type A','Arial Narrow',Arial,sans-serif;font-style:italic}}
.m{{stroke:var(--ink);stroke-width:.45;fill:none;stroke-linejoin:round;stroke-linecap:round}}
.t{{stroke:var(--ink);stroke-width:.2;fill:none}}
.h{{stroke:var(--ink);stroke-width:.22;stroke-dasharray:1.8 .9;fill:none;opacity:.7}}
.c{{stroke:var(--ink);stroke-width:.17;stroke-dasharray:9 1.2 1.5 1.2;fill:none}}
.d{{stroke:var(--ink);stroke-width:.17;fill:none}}
.sec{{stroke:var(--ink);stroke-width:.35}}
.cut{{stroke:var(--ink);stroke-width:1.1}}
.dot{{fill:var(--ink)}}
.m2{{stroke:var(--ink);stroke-width:.25;fill:none;stroke-linejoin:round;stroke-linecap:round}}
.g{{stroke:var(--ink);stroke-width:.11;fill:none;opacity:.6}}
.ph{{stroke:var(--ink);stroke-width:.2;stroke-dasharray:7 1.1 .7 1.1 .7 1.1;fill:none}}
.dyn{{stroke:var(--ink);stroke-width:.6;fill:none;stroke-dasharray:3.2 1;stroke-linecap:round}}
.dyn2{{stroke:var(--ink);stroke-width:.5;fill:none;stroke-dasharray:.2 1.3;stroke-linecap:round}}
.dynz{{stroke:var(--ink);stroke-width:.2;fill:none;stroke-dasharray:1 1}}
.fold{{stroke:var(--ink);stroke-width:.18;fill:none;stroke-dasharray:3 .8 .4 .8;opacity:.85}}
.fold2{{stroke:var(--ink);stroke-width:.18;fill:none;stroke-dasharray:1.2 .8;opacity:.85}}
.blk{{fill:var(--ink)}}
.hat{{fill:url(#hatch)}}
.hat2{{fill:url(#hatch2)}}
"""
    defs = """
<marker id="arr" viewBox="0 0 10 4" refX="10" refY="2" markerWidth="2.6" markerHeight="1.05" markerUnits="userSpaceOnUse" orient="auto-start-reverse"><path d="M0,0 L10,2 L0,4 z" style="fill:var(--ink)"/></marker>
<marker id="arrc" viewBox="0 0 10 6" refX="10" refY="3" markerWidth="3.5" markerHeight="2.1" markerUnits="userSpaceOnUse" orient="auto"><path d="M0,0 L10,3 L0,6 z" style="fill:var(--ink)"/></marker>
<pattern id="hatch" width="1.6" height="1.6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="1.6" height="1.6" style="fill:var(--bg)"/><line x1="0" y1="0" x2="0" y2="1.6" style="stroke:var(--ink);stroke-width:.18"/></pattern>
<pattern id="hatch2" width="1.6" height="1.6" patternUnits="userSpaceOnUse" patternTransform="rotate(-45)"><rect width="1.6" height="1.6" style="fill:var(--bg)"/><line x1="0" y1="0" x2="0" y2="1.6" style="stroke:var(--ink);stroke-width:.18"/></pattern>
"""
    body = "\n".join(sh.out)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{sh.w}mm" height="{sh.h}mm" viewBox="0 0 {sh.w} {sh.h}">'
            f'<title>{title}</title><style>{css}</style><defs>{defs}</defs>'
            f'<rect width="{sh.w}" height="{sh.h}" style="fill:var(--bg)"/>\n{body}\n</svg>')
