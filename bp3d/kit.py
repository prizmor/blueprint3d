"""Строительные блоки геометрии. Единицы — мм. Оси объекта X, Y, Z (Z вверх).

Профиль — замкнутый 2D-контур из прямых, дуг и сплайнов (класс Path). Скругления углов
делаются настоящими дугами, поэтому на чертеже нет «рёбер дискретизации».
Тела строятся вытягиванием профилей вида сбоку/спереди/сверху, их пересечением (tri),
лофтом по сечениям и вращением.
"""
import math
from build123d import (Axis, Edge, Face, Solid, Vector, Wire, extrude, revolve, mirror, offset, Plane)

BIG = 1.0e5


# ================================================================== 2D-контур
class Path:
    """Замкнутый 2D-контур. Точки: (u, v) или (u, v, r) — r = радиус скругления в этой вершине
    (действует, если по обе стороны вершины прямые)."""

    def __init__(self, start):
        self.start = tuple(start[:2])
        self.r0 = start[2] if len(start) > 2 else 0
        self.segs = []          # ('L', p0, p1) | ('A', p0, pm, p1) | ('S', [p0..pn])
        self.rad = []           # радиус в КОНЦЕ сегмента i
        self.cur = self.start

    def L(self, *pts):
        for p in pts:
            q = tuple(p[:2])
            self.segs.append(("L", self.cur, q))
            self.rad.append(p[2] if len(p) > 2 else 0)
            self.cur = q
        return self

    def A(self, c, r, a1, n_check=True):
        """Дуга окружности с центром c и радиусом r от текущей точки до угла a1 (град)."""
        a0 = math.degrees(math.atan2(self.cur[1] - c[1], self.cur[0] - c[0]))
        # выбрать ветвь угла так, чтобы дуга шла кратчайшим путём (дуги > 180° — двумя вызовами A)
        while a1 - a0 > 180.0001:
            a0 += 360
        while a0 - a1 > 180.0001:
            a0 -= 360
        am = (a0 + a1) / 2
        pm = (c[0] + r * math.cos(math.radians(am)), c[1] + r * math.sin(math.radians(am)))
        p1 = (c[0] + r * math.cos(math.radians(a1)), c[1] + r * math.sin(math.radians(a1)))
        self.segs.append(("A", self.cur, pm, p1))
        self.rad.append(0)
        self.cur = p1
        return self

    def S(self, *pts):
        """Сплайн через точки, заканчивается в последней."""
        ps = [self.cur] + [tuple(p[:2]) for p in pts]
        self.segs.append(("S", ps))
        self.rad.append(0)
        self.cur = ps[-1]
        return self

    def close(self):
        if math.dist(self.cur, self.start) > 1e-6:
            self.segs.append(("L", self.cur, self.start))
            self.rad.append(self.r0)
        else:
            self.rad[-1] = self.r0
        self.cur = self.start
        return self

    # --- скругления
    def _resolved(self):
        segs = [list(s) for s in self.segs]
        n = len(segs)
        out_arcs = {}
        for i in range(n):
            r = self.rad[i]
            j = (i + 1) % n
            if r <= 0 or segs[i][0] != "L" or segs[j][0] != "L":
                continue
            A, B = segs[i][1], segs[i][2]
            C = segs[j][2]
            d1 = _unit(_sub(A, B))
            d2 = _unit(_sub(C, B))
            cosang = max(-1.0, min(1.0, d1[0] * d2[0] + d1[1] * d2[1]))
            th = math.acos(cosang)
            if th < 1e-3 or abs(th - math.pi) < 1e-3:
                continue
            t = r / math.tan(th / 2)
            tmax = 0.49 * min(math.dist(A, B), math.dist(B, C))
            if t > tmax:
                t = tmax
                r = t * math.tan(th / 2)
            p1 = _add(B, _mul(d1, t))
            p2 = _add(B, _mul(d2, t))
            bis = _unit(_add(d1, d2))
            cen = _add(B, _mul(bis, r / math.sin(th / 2)))
            pm = _sub(cen, _mul(bis, r))
            segs[i][2] = p1
            segs[j][1] = p2
            out_arcs[i] = ("A", p1, pm, p2)
        res = []
        for i, s in enumerate(segs):
            if not (s[0] == "L" and math.dist(s[1], s[2]) < 1e-6):
                res.append(tuple(s))
            if i in out_arcs:
                res.append(out_arcs[i])
        return res

    def edges(self, to3):
        """Рёбра build123d; to3 — функция (u, v) -> (x, y, z)."""
        E = []
        for s in self._resolved():
            if s[0] == "L":
                E.append(Edge.make_line(to3(*s[1]), to3(*s[2])))
            elif s[0] == "A":
                E.append(Edge.make_three_point_arc(to3(*s[1]), to3(*s[2]), to3(*s[3])))
            else:
                E.append(Edge.make_spline([Vector(*to3(*p)) for p in s[1]]))
        return E

    def wire(self, to3):
        return Wire(self.edges(to3))

    def sample(self, step=10.0):
        """Точки контура с шагом не больше step (мм) — для квадовых сеток (mesh.sweep_grid, revolve_grid).
        Каждое ребро делится отдельно, поэтому вершины контура сохраняются. У замкнутого контура
        замыкающая точка не повторяется, у незамкнутого (профиль вращения от оси до оси) — последняя
        точка входит. Возвращает (точки (n, 2), индексы вершин контура — углы для острых рёбер)."""
        pts, corners = [], []
        for e in self.edges(lambda u, v: (u, v, 0.0)):
            n = max(1, int(math.ceil(e.length / step)))
            corners.append(len(pts))
            for i in range(n):
                q = e.position_at(i / n)
                pts.append((q.X, q.Y))
        if math.dist(self.cur, self.start) > 1e-6:
            corners.append(len(pts))
            pts.append(self.cur)
        return pts, corners

    def points(self, n_arc=8):
        """Приближённые точки контура (для аннотаций/проверок)."""
        out = []
        for s in self._resolved():
            if s[0] == "L":
                out.append(s[1])
            elif s[0] == "A":
                out += [s[1], s[2]]
            else:
                out += s[1][:-1]
        return out


def _sub(a, b): return (a[0] - b[0], a[1] - b[1])
def _add(a, b): return (a[0] + b[0], a[1] + b[1])
def _mul(a, k): return (a[0] * k, a[1] * k)


def _unit(a):
    l = math.hypot(*a)
    return (a[0] / l, a[1] / l)


def poly(pts):
    """Path из списка точек (u, v[, r])."""
    if isinstance(pts, Path):
        return pts
    p = Path(pts[0])
    p.L(*pts[1:])
    return p.close()


def sym(half, axis=0):
    """Половина контура (от оси до оси, точки могут нести радиус) -> полный симметричный список."""
    def m(p):
        q = list(p)
        q[axis] = -q[axis]
        return tuple(q)
    return list(half) + [m(p) for p in reversed(half[1:-1])]


def arcpts(c, r, a0, a1, n=48):
    return [(c[0] + r * math.cos(math.radians(a0 + (a1 - a0) * i / n)),
             c[1] + r * math.sin(math.radians(a0 + (a1 - a0) * i / n))) for i in range(n + 1)]


def rect(u0, v0, u1, v1, r=0):
    return poly([(u0, v0, r), (u1, v0, r), (u1, v1, r), (u0, v1, r)])


def circle_path(c, r):
    p = Path((c[0] + r, c[1]))
    p.A(c, r, 180).A(c, r, 360)
    return p.close()


def ellipse_path(c, rx, ry, n=16):
    pts = [(c[0] + rx * math.cos(2 * math.pi * i / n), c[1] + ry * math.sin(2 * math.pi * i / n)) for i in range(1, n)]
    p = Path((c[0] + rx, c[1]))
    p.S(*pts, (c[0] + rx, c[1]))
    return p.close()


def hexagon(c, r, a0=30):
    return poly([(c[0] + r * math.cos(math.radians(a0 + 60 * j)), c[1] + r * math.sin(math.radians(a0 + 60 * j))) for j in range(6)])


# ================================================================== тела
def _face(path, to3, grow=0):
    f = Face(poly(path).wire(to3))
    return offset(f, amount=grow) if grow else f


def prism_xz(path, y0, y1, grow=0):
    """Контур вида сбоку (x, z), вытянутый по Y. grow — смещение контура наружу (мм), для зазоров."""
    return extrude(_face(path, lambda u, v: (u, y0, v), grow), amount=y1 - y0, dir=(0, 1, 0))


def prism_yz(path, x0, x1, grow=0):
    """Контур вида спереди (y, z), вытянутый по X."""
    return extrude(_face(path, lambda u, v: (x0, u, v), grow), amount=x1 - x0, dir=(1, 0, 0))


def prism_xy(path, z0, z1, grow=0):
    """Контур вида сверху (x, y), вытянутый по Z."""
    return extrude(_face(path, lambda u, v: (u, v, z0), grow), amount=z1 - z0, dir=(0, 0, 1))


def _ext(path, i):
    pts = poly(path).points()
    return (min(p[i] for p in pts) - 20, max(p[i] for p in pts) + 20)


def tri(side=None, front=None, top=None, y=None, x=None, z=None, grow=0):
    """Тело как пересечение призм видов: его силуэты совпадают с заданными контурами.
    Диапазоны вытягивания берутся из габаритов других профилей (огромные призмы ломают булевы операции)."""
    def pick(*c):
        for v in c:
            if v is not None:
                return v
        return (-5000, 5000)
    y = pick(y, _ext(front, 0) if front is not None else None, _ext(top, 1) if top is not None else None)
    x = pick(x, _ext(side, 0) if side is not None else None, _ext(top, 0) if top is not None else None)
    z = pick(z, _ext(side, 1) if side is not None else None, _ext(front, 1) if front is not None else None)
    parts = []
    if side is not None:
        parts.append(prism_xz(side, *y, grow=grow))
    if front is not None:
        parts.append(prism_yz(front, *x, grow=grow))
    if top is not None:
        parts.append(prism_xy(top, *z, grow=grow))
    out = parts[0]
    for s in parts[1:]:
        out = out & s
    return _solid(out)


def loft_x(sections, ruled=False, centripetal=False, max_degree=8):
    """Лофт через поперечные сечения [(x, Path в координатах (y, z)), ...] с одинаковым числом рёбер.
    centripetal=True — центростремительная параметризация OCCT (с max_degree≈5): без перехлёста там,
    где сечения резко меняются (нос машины); стандартная хордовая на таких местах «выстреливает»."""
    wires = [poly(p).wire(lambda u, v, x=x: (x, u, v)) for x, p in sections]
    if ruled or not centripetal:
        return Solid.make_loft(wires, ruled=ruled)
    from OCP.BRepOffsetAPI import BRepOffsetAPI_ThruSections
    from OCP.Approx import Approx_ParametrizationType
    ts = BRepOffsetAPI_ThruSections(True, False, 1e-6)
    ts.SetMaxDegree(max_degree)
    ts.SetParType(Approx_ParametrizationType.Approx_Centripetal)
    ts.CheckCompatibility(False)
    for w in wires:
        ts.AddWire(w.wrapped)
    ts.Build()
    return Solid(ts.Shape())


def revolve_about(profile_ru, center, axis=(0, 1, 0)):
    """Тело вращения: профиль (радиус, смещение вдоль оси) относительно центра."""
    ax = Vector(*axis).normalized()
    perp = Vector(1, 0, 0) if abs(ax.X) < 0.9 else Vector(0, 0, 1)
    perp = (perp - ax * perp.dot(ax)).normalized()
    c = Vector(*center)
    f = _face(profile_ru, lambda r, u: tuple(c + perp * r + ax * u))
    return revolve(f, Axis(tuple(c), tuple(ax)), 360)


def cyl(center, r, a0, a1, axis="y"):
    """Цилиндр: center — 3D-точка на оси, a0..a1 — диапазон вдоль оси (абсолютный)."""
    if axis == "y":
        return extrude(_face(circle_path((center[0], center[2]), r), lambda u, v: (u, a0, v)), amount=a1 - a0, dir=(0, 1, 0))
    if axis == "x":
        return extrude(_face(circle_path((center[1], center[2]), r), lambda u, v: (a0, u, v)), amount=a1 - a0, dir=(1, 0, 0))
    return extrude(_face(circle_path((center[0], center[1]), r), lambda u, v: (u, v, a0)), amount=a1 - a0, dir=(0, 0, 1))


def box(x0, y0, z0, x1, y1, z1, r=0):
    return prism_xy(rect(x0, y0, x1, y1, r), z0, z1)


def mirror_y(shape):
    return _solid(mirror(shape, Plane.XZ))


def union(*shapes):
    shapes = [s for s in shapes if s is not None]
    out = shapes[0]
    for s in shapes[1:]:
        out = out + s
    return _solid(out)


def cut(shape, *tools):
    for t in tools:
        if t is not None:
            shape = shape - t
    return _solid(shape)


def _solid(s):
    return s


def surface_x(shape, y, z, x0=-2000.0):
    """Первая точка поверхности тела по лучу +X из (x0, y, z) — для посадки деталей «по месту»."""
    pts = shape.find_intersection_points(Axis((x0, y, z), (1, 0, 0)))
    xs = [p[0].X for p in pts]
    return min(xs) if xs else None


def lerp(a, b, t):
    return a + (b - a) * t


def interp(table, x):
    """Кусочно-линейная интерполяция по [(x, y), ...]."""
    if x <= table[0][0]:
        return table[0][1]
    for (x0, y0), (x1, y1) in zip(table, table[1:]):
        if x <= x1:
            return lerp(y0, y1, (x - x0) / (x1 - x0))
    return table[-1][1]


def mono(table, x):
    """Монотонная кубическая интерполяция (Fritsch–Carlson, PCHIP): гладко и без выбросов
    за пределы соседних значений — для дизайн-линий, где перехлёст даёт «плавники»."""
    xs = [p[0] for p in table]
    ys = [p[1] for p in table]
    n = len(xs)
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    h = [xs[i + 1] - xs[i] for i in range(n - 1)]
    d = [(ys[i + 1] - ys[i]) / h[i] for i in range(n - 1)]
    m = [d[0]] + [0.0] * (n - 2) + [d[-1]]
    for i in range(1, n - 1):
        if d[i - 1] * d[i] <= 0:
            m[i] = 0.0
        else:
            w1, w2 = 2 * h[i] + h[i - 1], h[i] + 2 * h[i - 1]
            m[i] = (w1 + w2) / (w1 / d[i - 1] + w2 / d[i])
    i = max(k for k in range(n - 1) if xs[k] <= x)
    t = (x - xs[i]) / h[i]
    h00, h10, h01, h11 = 2 * t ** 3 - 3 * t ** 2 + 1, t ** 3 - 2 * t ** 2 + t, -2 * t ** 3 + 3 * t ** 2, t ** 3 - t ** 2
    return h00 * ys[i] + h10 * h[i] * m[i] + h01 * ys[i + 1] + h11 * h[i] * m[i + 1]


def smooth(table, x):
    """Гладкая (Catmull-Rom) интерполяция по [(x, y), ...]."""
    xs = [p[0] for p in table]
    if x <= xs[0]:
        return table[0][1]
    if x >= xs[-1]:
        return table[-1][1]
    i = max(k for k in range(len(xs) - 1) if xs[k] <= x)
    p0 = table[max(i - 1, 0)][1]
    p1, p2 = table[i][1], table[i + 1][1]
    p3 = table[min(i + 2, len(table) - 1)][1]
    t = (x - xs[i]) / (xs[i + 1] - xs[i])
    return 0.5 * (2 * p1 + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3)


# ================================================================== поверхности двоякой кривизны
# Кузовные панели задаются не пересечением призм и не одним лофтом, а «лоскутами»:
# каждая гладкая зона — B-сплайновая поверхность через сетку точек, вычисленных функцией формы
# (дизайн-линии, сечения). Границы лоскутов — настоящие характерные рёбра (кромки, подштамповки,
# линии разъёма), поэтому на чертеже они получаются линиями сами. Панель — оболочка с толщиной
# (skin): наружная поверхность + эквидистанта внутрь + торцы.
import numpy as np


def coons(bottom, top, left, right, nu, nv):
    """Сетка (nu, nv, dim) внутри четырёхугольной области, заданной четырьмя граничными кривыми —
    функциями t∈[0,1] -> точка. bottom/top идут вдоль u (при v=0 и v=1), left/right — вдоль v
    (при u=0 и u=1). Углы должны совпадать: left(0)=bottom(0), right(1)=top(1) и т. д."""
    us, vs = np.linspace(0, 1, nu), np.linspace(0, 1, nv)
    B = np.array([bottom(u) for u in us], float)
    T = np.array([top(u) for u in us], float)
    L = np.array([left(v) for v in vs], float)
    R = np.array([right(v) for v in vs], float)
    U, V = us[:, None, None], vs[None, :, None]
    return ((1 - V) * B[:, None, :] + V * T[:, None, :] + (1 - U) * L[None, :, :] + U * R[None, :, :]
            - ((1 - U) * (1 - V) * B[0] + U * (1 - V) * B[-1] + (1 - U) * V * T[0] + U * V * T[-1]))


def resample(points, n):
    """Ломаная -> n точек, равномерно по длине (для ровной параметризации рядов сетки)."""
    P = np.asarray(points, float)
    d = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))])
    if d[-1] < 1e-9:
        return np.repeat(P[:1], n, axis=0)
    t = np.linspace(0, d[-1], n)
    return np.stack([np.interp(t, d, P[:, k]) for k in range(P.shape[1])], axis=1)


def grid_of(fn, nu, nv, dense=5):
    """Сетка (nu, nv, 3) по функции fn(u, v) -> (x, y, z), u, v ∈ [0, 1]. Каждый ряд v=const
    считается густо и пересэмплируется равномерно по длине: соседние лоскуты с общей границей
    получают на ней одинаковые точки, а значит — совпадающие кромки."""
    us = np.linspace(0, 1, (nu - 1) * dense + 1)
    return np.stack([resample([fn(u, v) for u in us], nu) for v in np.linspace(0, 1, nv)], axis=1)


def grid_normals(G):
    """Единичные нормали сетки (центральные разности)."""
    n = np.cross(np.gradient(G, axis=0), np.gradient(G, axis=1))
    l = np.linalg.norm(n, axis=2, keepdims=True)
    l[l < 1e-12] = 1.0
    return n / l


def offset_grid(G, t, flip=False):
    """Эквидистанта сетки на t мм вдоль нормали (flip меняет сторону)."""
    return np.asarray(G, float) + grid_normals(np.asarray(G, float)) * (-t if flip else t)


def bspline_surface(G):
    """Geom_BSplineSurface (степень 3, C2) через сетку точек G[i][j] с равномерной параметризацией:
    граничная кривая зависит только от граничного ряда точек, поэтому у соседних лоскутов с общим
    рядом кромки геометрически совпадают.

    Интерполяция своя (кубический сплайн «без узла» по каждому направлению), а не
    GeomAPI_PointsToBSplineSurface: тот несимметричен — на зеркально-симметричной сетке давал у одного
    края волну в несколько миллиметров (складка облицовки у стыка с крылом только с одной стороны)."""
    try:                                   # OCP 7.x
        from OCP.TColgp import TColgp_Array2OfPnt
        from OCP.TColStd import TColStd_Array1OfReal, TColStd_Array1OfInteger
    except ImportError:                    # OCP 8: коллекции переименованы
        from OCP.collections import Array2_gp_Pnt as TColgp_Array2OfPnt
        from OCP.collections import Array1_double as TColStd_Array1OfReal, Array1_int as TColStd_Array1OfInteger
    from OCP.Geom import Geom_BSplineSurface
    from OCP.gp import gp_Pnt
    from scipy.interpolate import make_interp_spline
    G = np.asarray(G, float)
    nu, nv = G.shape[:2]
    if nu < 4 or nv < 4:
        raise ValueError("сетка лоскута должна быть не меньше 4×4")
    su = make_interp_spline(np.arange(nu, dtype=float), G, k=3, axis=0)        # полюса по u для каждого ряда
    sv = make_interp_spline(np.arange(nv, dtype=float), np.swapaxes(su.c, 0, 1), k=3, axis=0)   # затем по v
    P = np.swapaxes(sv.c, 0, 1)                                                # полюса (nu, nv, 3)

    def knots(t):
        vals, mult = np.unique(np.round(t, 9), return_counts=True)
        k = TColStd_Array1OfReal(1, len(vals))
        m = TColStd_Array1OfInteger(1, len(vals))
        for i, (a, b) in enumerate(zip(vals, mult)):
            k.SetValue(i + 1, float(a))
            m.SetValue(i + 1, int(b))
        return k, m
    arr = TColgp_Array2OfPnt(1, nu, 1, nv)
    for i in range(nu):
        for j in range(nv):
            arr.SetValue(i + 1, j + 1, gp_Pnt(*map(float, P[i, j])))
    uk, um = knots(su.t)
    vk, vm = knots(sv.t)
    return Geom_BSplineSurface(arr, uk, vk, um, vm, 3, 3, False, False)


def surface_face(G):
    """Грань-лоскут через сетку точек (без толщины)."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    return Face(BRepBuilderAPI_MakeFace(bspline_surface(G), 1e-6).Face())


def skin(bands, t, flip=False, tol=0.02):
    """Панель-оболочка с толщиной t из одного или нескольких лоскутов.

    bands — список сеток (nu, nv, 3); соседние делят ряд: bands[k][:, -1] == bands[k+1][:, 0]
    (общая граница — характерное ребро: излом по ней сохраняется, эквидистанта на ней строится
    по биссектрисе). t — толщина по нормали; сторона — «минус нормаль» сетки, flip меняет её.
    Возвращает одно замкнутое тело; если сшить не удалось — Compound отдельных лоскутов-тел."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_Sewing, BRepBuilderAPI_MakeSolid
    from OCP.GeomFill import GeomFill
    from OCP.TopoDS import TopoDS
    from OCP.TopAbs import TopAbs_SHELL
    from OCP.TopExp import TopExp_Explorer
    from OCP.BRepLib import BRepLib
    from OCP.BRepCheck import BRepCheck_Analyzer
    from build123d import Compound
    if isinstance(bands, np.ndarray) and bands.ndim == 3:
        bands = [bands]
    outer = [np.asarray(b, float) for b in bands]
    sgn = 1.0 if flip else -1.0
    nrm = [grid_normals(b) * sgn for b in outer]
    inner = [b + n * t for b, n in zip(outer, nrm)]
    for k in range(len(outer) - 1):               # общий ряд: смещение по биссектрисе («на ус»)
        n1, n2 = nrm[k][:, -1], nrm[k + 1][:, 0]
        m = n1 + n2
        m /= np.linalg.norm(m, axis=1, keepdims=True)
        c = np.clip(np.sum(m * n1, axis=1, keepdims=True), 0.5, 1.0)
        row = outer[k][:, -1] + m * (t / c)
        inner[k][:, -1] = row
        inner[k + 1][:, 0] = row

    def one(grids_o, grids_i):
        so = [bspline_surface(g) for g in grids_o]
        si = [bspline_surface(g) for g in grids_i]
        faces = []
        for a, b in zip(so, si):
            u0, u1, v0, v1 = a.Bounds()
            faces += [a, b, GeomFill.Surface_s(a.UIso(u0), b.UIso(u0)), GeomFill.Surface_s(a.UIso(u1), b.UIso(u1))]
        u0, u1, v0, v1 = so[0].Bounds()
        faces.append(GeomFill.Surface_s(so[0].VIso(v0), si[0].VIso(v0)))
        u0, u1, v0, v1 = so[-1].Bounds()
        faces.append(GeomFill.Surface_s(so[-1].VIso(v1), si[-1].VIso(v1)))
        sew = BRepBuilderAPI_Sewing(tol)
        for f in faces:
            sew.Add(BRepBuilderAPI_MakeFace(f, 1e-6).Face())
        sew.Perform()
        ex = TopExp_Explorer(sew.SewedShape(), TopAbs_SHELL)
        if not ex.More():
            return None
        sh = (getattr(TopoDS, "Shell_s", None) or TopoDS.Shell)(ex.Current())
        ex.Next()
        if ex.More() or not sh.Closed():
            return None
        sol = BRepBuilderAPI_MakeSolid(sh).Solid()
        BRepLib.OrientClosedSolid_s(sol)
        if not BRepCheck_Analyzer(sol).IsValid():
            return None
        return Solid(sol)

    s = one(outer, inner)
    if s is not None:
        return s
    parts = [one([o], [i]) for o, i in zip(outer, inner)]
    if any(p is None for p in parts):
        raise RuntimeError("skin: лоскут не сшивается в тело (проверьте сетку на вырожденность)")
    return parts[0] if len(parts) == 1 else Compound(parts)


def hermite(p0, m0, p1, m1, t):
    """Кубическая кривая Эрмита: значения p0, p1 и производные m0, m1 (по t) на концах, t∈[0,1]."""
    return ((2 * t ** 3 - 3 * t ** 2 + 1) * p0 + (t ** 3 - 2 * t ** 2 + t) * m0
            + (-2 * t ** 3 + 3 * t ** 2) * p1 + (t ** 3 - t ** 2) * m1)


def section_curves(shapes, axis, value, n=None):
    """Линии пересечения тел плоскостью axis=value ('x'|'y'|'z') — ломаные 3D-точек.
    Для сетки теоретических сечений на видах (объём поверхности читается по ним)."""
    nrm = {"x": (1, 0, 0), "y": (0, 1, 0), "z": (0, 0, 1)}[axis]
    plane = Plane(origin=tuple(value * c for c in nrm), z_dir=nrm)
    out = []
    for s in shapes:
        try:
            faces = s.intersect(plane)
        except Exception:
            continue
        if not faces:
            continue
        for f in (faces if hasattr(faces, "__iter__") else [faces]):
            for e in f.edges():
                if e.length < 1e-6:
                    continue
                k = n or max(2, min(120, int(e.length / 5)))
                out.append([tuple(e.position_at(i / k)) for i in range(k + 1)])
    return out


def map_grid(D, fn, nu=None):
    """Сетка области D (nu_dense, nv, k) -> 3D-сетка: fn(*точка области) -> (x, y, z); ряды v=const
    пересэмплируются равномерно по длине до nu точек (см. grid_of)."""
    D = np.asarray(D, float)
    G = np.array([[fn(*D[i, j]) for j in range(D.shape[1])] for i in range(D.shape[0])], float)
    if nu is None:
        return G
    return np.stack([resample(G[:, j], nu) for j in range(G.shape[1])], axis=1)


def mirror_grid(G):
    """Зеркало сетки относительно плоскости XZ с сохранением направления нормали
    (порядок рядов по v разворачивается)."""
    M = np.array(G, float)[:, ::-1].copy()
    M[..., 1] *= -1
    return M


def heal(shape):
    """Починить тело после булевых операций со сплайновыми оболочками (допуски рёбер);
    исправное тело возвращается как есть."""
    try:
        if shape.is_valid:
            return shape
        fixed = shape.fix()
        return fixed if fixed is not None and fixed.is_valid else shape
    except Exception:
        return shape
