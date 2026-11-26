"""Квадовый меш напрямую из сеток точек. Единицы — мм, оси объекта X, Y, Z.

CAD-триангуляция (build.export_cad) даёт длинные тонкие треугольники и веера без петель и развёртки:
жёсткому предмету это почти не мешает, а меш, который гнётся скелетом, на такой сетке ломается.
Здесь меш строится из тех же сеток (nu, nv, 3), что идут в kit.bspline_surface / kit.skin:

  ячейка сетки   -> квад (сетка не пересэмплируется: сколько рядов задано, столько петель и будет);
  лоскут (Patch) -> UV-остров, развёрнутый по длинам рядов (масштаб островов одинаковый, мм);
  общий ряд      -> соседние лоскуты свариваются по совпадающим точкам;
  толщина        -> второй слой по нормалям вершин («на ус» на изломах) и торцевые квады по кромкам.

B-rep для чертежа (QuadMesh.brep) строится из тех же сеток, поэтому чертёж и модель по-прежнему сняты
с одного построения; отклонение квадов от B-сплайна считает QuadMesh.deviation().

Генераторы сеток для контуров: sweep_grid (профиль вдоль кривой), loft_grid (кольца),
revolve_grid (вращение), cap_grid (заглушка кольца квадами). Плотность рядов — spacing().
"""
import math
import numpy as np

OUTER, INNER, RIM = 0, 1, 2          # метки граней: наружный слой, внутренний слой, торец кромки


# ================================================================== параметры рядов
def spacing(n, dense=(), lo=0.0, hi=1.0):
    """n значений параметра от lo до hi. dense = [(центр, полуширина, во_сколько_раз_гуще), ...] —
    зоны сгущения рядов (суставы, кромки). Переход плотности плавный: резкая смена шага даёт волну
    на B-сплайне и рваные петли."""
    t = np.linspace(lo, hi, 2001)
    rho = np.ones_like(t)
    for c, w, k in dense:
        rho += (k - 1.0) * np.exp(-((t - c) / max(w, 1e-9)) ** 2 * 1.4)
    cum = np.concatenate([[0.0], np.cumsum((rho[1:] + rho[:-1]) / 2)])
    return np.interp(np.linspace(0, cum[-1], n), cum, t)


def resample_closed(ring, n):
    """Замкнутая ломаная -> n точек равномерно по длине (первая точка сохраняется)."""
    P = np.asarray(ring, float)
    Q = np.vstack([P, P[:1]])
    d = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(Q, axis=0), axis=1))])
    t = np.linspace(0, d[-1], n, endpoint=False)
    return np.stack([np.interp(t, d, Q[:, k]) for k in range(Q.shape[1])], axis=1)


def resample_open(line, n):
    P = np.asarray(line, float)
    d = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))])
    t = np.linspace(0, d[-1], n)
    return np.stack([np.interp(t, d, P[:, k]) for k in range(P.shape[1])], axis=1)


# ================================================================== лоскут
class Patch:
    """Сетка точек G[i, j] (nu, nv, 3) — один UV-остров. closed_u / closed_v — сетка замкнута по
    направлению (последний ряд соединяется с первым; дублирующий ряд не хранится). Нормаль лоскута —
    du × dv, она должна смотреть НАРУЖУ: толщина наращивается в обратную сторону."""

    def __init__(self, G, closed_u=False, closed_v=False, name="", uv_scale=1.0):
        self.G = np.asarray(G, float)
        if self.G.ndim != 3 or self.G.shape[2] != 3:
            raise ValueError("сетка лоскута должна иметь форму (nu, nv, 3)")
        self.closed_u, self.closed_v = bool(closed_u), bool(closed_v)
        self.name = name
        self.uv_scale = uv_scale

    def flipped(self):
        """Тот же лоскут с нормалью в другую сторону."""
        return Patch(self.G[:, ::-1], self.closed_u, self.closed_v, self.name, self.uv_scale)

    def wrapped(self):
        """Сетка с повтором первого ряда по замкнутым направлениям (для B-сплайна и длин)."""
        G = self.G
        if self.closed_u:
            G = np.concatenate([G, G[:1]], axis=0)
        if self.closed_v:
            G = np.concatenate([G, G[:, :1]], axis=1)
        return G

    def lengths(self):
        """Координаты развёртки, мм: U[i] и V[j] — средняя длина вдоль рядов. Остров — прямоугольник
        (U[-1] × V[-1]): узоры и канты на нём идут ровно вдоль рядов сетки."""
        W = self.wrapped()
        du = np.linalg.norm(np.diff(W, axis=0), axis=2).mean(axis=1)
        dv = np.linalg.norm(np.diff(W, axis=1), axis=2).mean(axis=0)
        return np.concatenate([[0.0], np.cumsum(du)]), np.concatenate([[0.0], np.cumsum(dv)])

    def normals(self):
        """Нормали в точках сетки (центральные разности, с учётом замкнутости)."""
        G = self.G

        def grad(axis, closed):
            if closed:
                return (np.roll(G, -1, axis=axis) - np.roll(G, 1, axis=axis)) / 2
            return np.gradient(G, axis=axis) if G.shape[axis] > 1 else np.zeros_like(G)
        n = np.cross(grad(0, self.closed_u), grad(1, self.closed_v))
        l = np.linalg.norm(n, axis=2, keepdims=True)
        l[l < 1e-12] = 1.0
        return n / l

    def offset(self, t):
        """Эквидистанта лоскута на t мм вдоль нормали."""
        return Patch(self.G + self.normals() * t, self.closed_u, self.closed_v, self.name, self.uv_scale)

    def brep_grid(self):
        """Сетка для kit.bspline_surface: с повтором замыкающего ряда и не меньше 4 рядов по каждому
        направлению (короткие направления досэмплируются линейно — форма полосы не меняется)."""
        W = self.wrapped()
        for ax in (0, 1):
            n = W.shape[ax]
            if n < 4:
                t = np.linspace(0, n - 1, 4)
                i0 = np.clip(np.floor(t).astype(int), 0, n - 2)
                f = (t - i0).reshape([-1 if a == ax else 1 for a in range(3)])
                W = np.take(W, i0, axis=ax) * (1 - f) + np.take(W, i0 + 1, axis=ax) * f
        return W

    def deviation(self):
        """Отклонение центров квадов от B-сплайна через ту же сетку, мм: (максимум, среднее)."""
        from scipy.interpolate import make_interp_spline
        W = self.brep_grid()
        nu, nv = W.shape[:2]
        A = make_interp_spline(np.arange(nu, dtype=float), W, k=3, axis=0)(np.arange(nu - 1) + 0.5)
        C = make_interp_spline(np.arange(nv, dtype=float), A, k=3, axis=1)(np.arange(nv - 1) + 0.5)
        M = (W[:-1, :-1] + W[1:, :-1] + W[1:, 1:] + W[:-1, 1:]) / 4
        d = np.linalg.norm(C - M, axis=2)
        return float(d.max()), float(d.mean())


# ================================================================== меш
class QuadMesh:
    """Полигональный меш детали: вершины V (N, 3), грани F (M, 4) — квады, у треугольника четвёртый
    индекс −1; UV по углам граней в мм острова (атлас собирается при экспорте: pack_islands).

    Собирать через quad_skin / quad_shell / quad_tube. Передаётся в Model.add вместо тела:
    деталь идёт в 3D квадами (mesh="quad"), а на чертёж — B-rep из тех же сеток (brep())."""

    def __init__(self):
        self.V = np.zeros((0, 3))
        self.F = np.zeros((0, 4), int)
        self.UV = np.zeros((0, 4, 2))          # мм в системе своего острова
        self.face_island = np.zeros(0, int)
        self.face_tag = np.zeros(0, int)
        self.islands = []                      # dict(name, w, h, tag, scale)
        self.vpatch = np.zeros(0, int)         # вершина -> индекс лоскута
        self.vuv = np.zeros((0, 2))            # вершина -> параметры (u, v) ∈ [0, 1] в своём лоскуте
        self.vside = np.zeros(0, int)          # 0 — наружный слой, 1 — внутренний
        self.sharp = np.zeros((0, 2), int)     # острые рёбра (пары вершин)
        self.patches = []
        self.gid = []                          # лоскут -> (nu, nv) номера вершин меша для точек его сетки
        self.patch_uv = []                     # лоскут -> (U, V): мм развёртки для индексов сетки; None — нет связи
        self.thickness = 0.0
        self.two_sided = False                 # один слой без толщины: материал двусторонний
        self._brep = None

    # ------------------------------------------------------------ сборка
    @staticmethod
    def from_patches(patches, weld=1e-3, sharp_borders=False):
        """Наружный слой из лоскутов: совпадающие точки соседних лоскутов свариваются (допуск weld, мм).
        sharp_borders — границы лоскутов становятся острыми рёбрами (гранёные тела)."""
        m = QuadMesh()
        m.patches = list(patches)
        V, F, UV, fi, vp, vuv, border = [], [], [], [], [], [], []
        base, bases = 0, []
        for k, P in enumerate(m.patches):
            nu, nv = P.G.shape[:2]
            U, Vv = P.lengths()
            s = P.uv_scale
            m.islands.append(dict(name=P.name or f"p{k}", w=float(U[-1] * s), h=float(Vv[-1] * s), tag=OUTER, scale=s,
                                  patch=k))
            m.patch_uv.append((U, Vv))
            bases.append((base, nu, nv))
            V.append(P.G.reshape(-1, 3))
            vp.append(np.full(nu * nv, k))
            uu = np.arange(nu) / (nu if P.closed_u else max(nu - 1, 1))
            vv = np.arange(nv) / (nv if P.closed_v else max(nv - 1, 1))
            vuv.append(np.stack(np.meshgrid(uu, vv, indexing="ij"), axis=2).reshape(-1, 2))
            cu = nu if P.closed_u else nu - 1
            cv = nv if P.closed_v else nv - 1
            I, J = np.meshgrid(np.arange(cu), np.arange(cv), indexing="ij")
            I, J = I.ravel(), J.ravel()
            I2, J2 = (I + 1) % nu, (J + 1) % nv
            F.append(base + np.stack([I * nv + J, I2 * nv + J, I2 * nv + J2, I * nv + J2], axis=1))
            UV.append(np.stack([np.stack([U[I], Vv[J]], 1), np.stack([U[I + 1], Vv[J]], 1),
                                np.stack([U[I + 1], Vv[J + 1]], 1), np.stack([U[I], Vv[J + 1]], 1)], axis=1) * s)
            fi.append(np.full(len(I), k))
            if sharp_borders:
                idx = base + np.arange(nu * nv).reshape(nu, nv)
                if not P.closed_v:
                    for j in (0, nv - 1):
                        r = idx[:, j]
                        border.append(np.stack([r, np.roll(r, -1)], 1)[: cu])
                if not P.closed_u:
                    for i in (0, nu - 1):
                        r = idx[i, :]
                        border.append(np.stack([r, np.roll(r, -1)], 1)[: cv])
            base += nu * nv
        m.V = np.vstack(V)
        m.F = np.vstack(F)
        m.UV = np.vstack(UV)
        m.face_island = np.concatenate(fi)
        m.face_tag = np.full(len(m.F), OUTER)
        m.vpatch = np.concatenate(vp)
        m.vuv = np.vstack(vuv)
        m.vside = np.zeros(len(m.V), int)
        if border:
            m.sharp = np.vstack(border)
        remap = m._weld(weld)
        m.gid = [remap[b + np.arange(nu * nv)].reshape(nu, nv) for b, nu, nv in bases]
        return m

    def sync_patches(self):
        """Сетки лоскутов -> по текущим вершинам меша (после смещения складками или деформеров): B-rep для
        чертежа, отклонение и запекание карт идут по той же форме, что и меш."""
        for k, P in enumerate(self.patches):
            if k < len(self.gid) and self.gid[k] is not None and self.gid[k].shape == P.G.shape[:2]:
                P.G = self.V[self.gid[k]].copy()
        self._brep = None
        return self

    def _weld(self, tol):
        from scipy.spatial import cKDTree
        from scipy.sparse import coo_matrix
        from scipy.sparse.csgraph import connected_components
        n = len(self.V)
        pairs = cKDTree(self.V).query_pairs(tol, output_type="ndarray")
        if len(pairs):
            # сваривать только вершины одного слоя: тонкая оболочка не должна схлопнуться
            pairs = pairs[self.vside[pairs[:, 0]] == self.vside[pairs[:, 1]]]
        g = coo_matrix((np.ones(len(pairs)), (pairs[:, 0], pairs[:, 1])), shape=(n, n))
        _, lab = connected_components(g, directed=False)
        first = np.full(lab.max() + 1, -1)
        for i in range(n - 1, -1, -1):
            first[lab[i]] = i
        keep = np.sort(first)
        new = np.full(n, -1)
        new[keep] = np.arange(len(keep))
        remap = new[first[lab]]
        self.V, self.vpatch, self.vuv, self.vside = self.V[keep], self.vpatch[keep], self.vuv[keep], self.vside[keep]
        F = np.where(self.F >= 0, remap[np.clip(self.F, 0, None)], -1)
        if len(self.sharp):
            s = np.sort(remap[self.sharp], axis=1)
            self.sharp = np.unique(s[s[:, 0] != s[:, 1]], axis=0)
        # грани, у которых после сварки совпали вершины: квад -> треугольник (полюс), иначе — убрать
        ok, tri = [], 0
        for k, f in enumerate(F):
            u = [v for i, v in enumerate(f) if v >= 0 and v != f[i - 1 if i else (3 if f[3] >= 0 else 2)]]
            u = list(dict.fromkeys(u)) if len(set(u)) < len(u) else u
            if len(u) == 4:
                ok.append(k)
            elif len(u) == 3:
                j = [list(f).index(v) for v in u]
                F[k] = u + [-1]
                uvk = self.UV[k][j]
                self.UV[k] = np.vstack([uvk, uvk[-1:]])
                ok.append(k)
                tri += 1
        ok = np.array(ok, int)
        self.F, self.UV = F[ok], self.UV[ok]
        self.face_island, self.face_tag = self.face_island[ok], self.face_tag[ok]
        return remap

    # ------------------------------------------------------------ геометрия
    def face_normals(self):
        """Нормали граней (не нормированы: длина — удвоенная площадь)."""
        F = self.F
        a, b, c = self.V[F[:, 0]], self.V[F[:, 1]], self.V[F[:, 2]]
        d = self.V[np.where(F[:, 3] >= 0, F[:, 3], F[:, 2])]
        return np.cross(c - a, d - b) + np.where((F[:, 3] < 0)[:, None], np.cross(b - a, c - a), 0.0)

    def vertex_normals(self):
        fn = self.face_normals()
        vn = np.zeros_like(self.V)
        for k in range(4):
            ok = self.F[:, k] >= 0
            np.add.at(vn, self.F[ok, k], fn[ok])
        l = np.linalg.norm(vn, axis=1, keepdims=True)
        l[l < 1e-12] = 1.0
        return vn / l

    def solidify(self, t, inner_uv=0.5):
        """Толщина t: внутренний слой по нормалям вершин (на изломе — по биссектрисе, «на ус»),
        кромки закрываются торцевыми квадами. Наружный слой остаётся на месте."""
        if t <= 0:
            self.two_sided = True
            return self
        n0, f0 = len(self.V), len(self.F)
        vn = self.vertex_normals()
        fn = self.face_normals()
        fl = np.linalg.norm(fn, axis=1, keepdims=True)
        fl[fl < 1e-12] = 1.0
        fn = fn / fl
        cs, cnt = np.zeros(n0), np.zeros(n0)
        for k in range(4):
            ok = self.F[:, k] >= 0
            np.add.at(cs, self.F[ok, k], np.sum(vn[self.F[ok, k]] * fn[ok], axis=1))
            np.add.at(cnt, self.F[ok, k], 1.0)
        cs = np.clip(cs / np.maximum(cnt, 1), 0.5, 1.0)
        inner = self.V - vn * (t / cs)[:, None]
        # кромки наружного слоя: ориентированные рёбра без встречного
        E = {}
        for f in self.F:
            vs = [v for v in f if v >= 0]
            for a, b in zip(vs, vs[1:] + vs[:1]):
                E[(a, b)] = E.get((a, b), 0) + 1
        rim = [(a, b) for (a, b) in E if (b, a) not in E]
        Fi = np.where(self.F >= 0, self.F + n0, -1)
        # разворот обхода внутренних граней (и порядка их UV)
        Fi_rev, UVi = Fi.copy(), self.UV.copy() * inner_uv
        # Обратный обход с той же первой вершиной: (a, b, c, d) -> (a, d, c, b). Диагональ, по которой
        # движок делит неплоский квад на треугольники, у лица и изнанки тогда общая; при обходе
        # (d, c, b, a) диагонали разные, и на изогнутой сетке треугольники изнанки выступали сквозь лицо.
        for k in range(f0):
            m = 4 if Fi[k, 3] >= 0 else 3
            order = [0, 3, 2, 1] if m == 4 else [0, 2, 1]
            Fi_rev[k, :m] = Fi[k, order]
            UVi[k, :m] = UVi[k][order]
            if m == 3:
                UVi[k, 3] = UVi[k, 2]
        ni = len(self.islands)
        isl_in = [dict(name=i["name"] + "_in", w=i["w"] * inner_uv, h=i["h"] * inner_uv, tag=INNER,
                       scale=i["scale"] * inner_uv, patch=i.get("patch")) for i in self.islands]
        Fr = np.array([[b, a, a + n0, b + n0] for a, b in rim], int).reshape(-1, 4)
        Lr = np.array([np.linalg.norm(self.V[a] - self.V[b]) for a, b in rim]) if rim else np.zeros(0)
        h = max(t, 2.0)                       # торцы делят один маленький остров (накладываются)
        UVr = np.array([[[l, 0], [0, 0], [0, h], [l, h]] for l in Lr], float).reshape(-1, 4, 2)
        self.V = np.vstack([self.V, inner])
        self.vpatch = np.concatenate([self.vpatch, self.vpatch])
        self.vuv = np.vstack([self.vuv, self.vuv])
        self.vside = np.concatenate([self.vside, np.ones(n0, int)])
        self.F = np.vstack([self.F, Fi_rev, Fr])
        self.UV = np.vstack([self.UV, UVi, UVr])
        self.face_island = np.concatenate([self.face_island, self.face_island + ni, np.full(len(Fr), 2 * ni)])
        self.face_tag = np.concatenate([self.face_tag, np.full(f0, INNER), np.full(len(Fr), RIM)])
        self.islands = self.islands + isl_in + ([dict(name="rim", w=float(Lr.max()), h=h, tag=RIM, scale=1.0)]
                                                if len(Fr) else [])
        if len(self.sharp):
            self.sharp = np.vstack([self.sharp, self.sharp + n0])
        if len(Fr):                             # кромка — острое ребро с обеих сторон торца
            r = np.array(rim, int)
            self.sharp = np.vstack([self.sharp.reshape(-1, 2), np.sort(r, 1), np.sort(r + n0, 1)])
        self.thickness = float(t)
        return self

    def merged(self, other):
        """Объединить два меша в один (без сварки между ними): отдельные тела одной детали."""
        m = QuadMesh()
        n, ni, npch = len(self.V), len(self.islands), len(self.patches)
        m.V = np.vstack([self.V, other.V])
        m.F = np.vstack([self.F, np.where(other.F >= 0, other.F + n, -1)])
        m.UV = np.vstack([self.UV, other.UV])
        m.face_island = np.concatenate([self.face_island, other.face_island + ni])
        m.face_tag = np.concatenate([self.face_tag, other.face_tag])
        m.islands = self.islands + [dict(i, patch=None if i.get("patch") is None else i["patch"] + npch)
                                    for i in other.islands]
        m.gid = list(self.gid) + [None if g is None else g + n for g in other.gid]
        m.patch_uv = list(self.patch_uv) + list(other.patch_uv)
        m.vpatch = np.concatenate([self.vpatch, other.vpatch + npch])
        m.vuv = np.vstack([self.vuv, other.vuv])
        m.vside = np.concatenate([self.vside, other.vside])
        m.sharp = np.vstack([self.sharp.reshape(-1, 2), other.sharp.reshape(-1, 2) + n])
        m.patches = self.patches + other.patches
        m.thickness = max(self.thickness, other.thickness)
        m.two_sided = self.two_sided or other.two_sided
        return m

    def transformed(self, fn):
        """Копия с вершинами fn(V) -> V' (зеркало, перенос). Сетки лоскутов преобразуются тоже."""
        import copy
        m = copy.copy(self)
        m.V = np.asarray(fn(self.V), float)
        m.patches = [Patch(fn(P.G.reshape(-1, 3)).reshape(P.G.shape), P.closed_u, P.closed_v, P.name, P.uv_scale)
                     for P in self.patches]
        m._brep = None
        return m

    def mirrored_y(self):
        """Зеркало относительно плоскости XZ (обход граней разворачивается, нормали остаются наружу)."""
        m = self.transformed(lambda P: P * np.array([1.0, -1.0, 1.0]))
        F, UV = m.F.copy(), m.UV.copy()
        for k in range(len(F)):
            n = 4 if F[k, 3] >= 0 else 3
            F[k, :n] = F[k, :n][::-1]
            UV[k, :n] = UV[k, :n][::-1]
        m.F, m.UV = F, UV
        m.patches = [Patch(P.G[::-1], P.closed_u, P.closed_v, P.name, P.uv_scale) for P in m.patches]
        m.gid = [None if g is None else g[::-1] for g in self.gid]
        m.patch_uv = [None] * len(self.patch_uv)          # развёртка зеркальной детали идёт против индексов сетки
        return m

    # ------------------------------------------------------------ B-rep, отклонение, габариты
    def brep(self):
        """B-rep для чертежа: B-сплайновые грани через сетки наружного слоя (kit.surface_face)."""
        if self._brep is None:
            from build123d import Compound
            from .kit import surface_face
            self._brep = Compound([surface_face(P.brep_grid()) for P in self.patches])
        return self._brep

    def deviation(self):
        d = [P.deviation() for P in self.patches]
        return (max(x[0] for x in d), float(np.mean([x[1] for x in d]))) if d else (0.0, 0.0)

    def bbox(self):
        return self.V.min(axis=0), self.V.max(axis=0)

    def counts(self):
        q = int(np.sum(self.F[:, 3] >= 0))
        t = len(self.F) - q
        return dict(quads=q, tris=t, triangles=2 * q + t, verts=len(self.V))

    def triangles(self):
        """Треугольники (K, 3) для сечений и расстояний: квад делится по диагонали 0–2."""
        q = self.F[:, 3] >= 0
        return np.vstack([self.F[:, :3], self.F[q][:, [0, 2, 3]]])

    # ------------------------------------------------------------ проверки
    def check(self, aspect_max=8.0):
        """Топология и качество: замкнутость, манифолдность, согласованность обхода, вырожденные
        и вытянутые квады. Соотношение сторон считается по наружному и внутреннему слою: торцевые
        квады кромки вытянуты по построению (толщина × шаг сетки) и в оценку не входят."""
        E = {}
        for f in self.F:
            vs = [v for v in f if v >= 0]
            for a, b in zip(vs, vs[1:] + vs[:1]):
                E[(a, b)] = E.get((a, b), 0) + 1
        und = {}
        for (a, b), c in E.items():
            k = (min(a, b), max(a, b))
            und[k] = und.get(k, 0) + c
        boundary = sum(1 for c in und.values() if c == 1)
        nonman = sum(1 for c in und.values() if c > 2)
        flipped = sum(1 for (a, b), c in E.items() if c > 1 and und[(min(a, b), max(a, b))] == 2)
        P = self.V[np.where(self.F >= 0, self.F, self.F[:, :1])]
        e = np.linalg.norm(P - np.roll(P, -1, axis=1), axis=2)
        quad = self.F[:, 3] >= 0
        area = np.linalg.norm(self.face_normals(), axis=1) / 2
        degenerate = int(np.sum(area < 1e-6) + np.sum((e[quad] < 1e-4).any(axis=1)))
        body = quad & (self.face_tag != RIM)
        a = (e[body][:, 0] + e[body][:, 2]) / 2
        b = (e[body][:, 1] + e[body][:, 3]) / 2
        asp = np.maximum(a, b) / np.maximum(np.minimum(a, b), 1e-9) if body.any() else np.zeros(1)
        return dict(boundary_edges=boundary, nonmanifold_edges=nonman, flipped_edges=flipped // 2,
                    closed=boundary == 0 and nonman == 0, degenerate=degenerate,
                    aspect_max=float(asp.max()), aspect_bad=int(np.sum(asp > aspect_max)),
                    edge_mean=float(e[body].mean()) if body.any() else 0.0, **self.counts())

    def uv_stretch(self):
        """Равномерность развёртки по островам: отношение длины ребра в 3D к длине в UV (мм/мм).
        1.0 — без искажений; возвращает {остров: (мин, макс)} по наружным островам."""
        out = {}
        P = self.V[np.where(self.F >= 0, self.F, self.F[:, :1])]
        e3 = np.linalg.norm(P - np.roll(P, -1, axis=1), axis=2)
        e2 = np.linalg.norm(self.UV - np.roll(self.UV, -1, axis=1), axis=2)
        for k, isl in enumerate(self.islands):
            if isl["tag"] != OUTER:
                continue
            m = (self.face_island == k)
            ok = (e2[m] > 1e-6) & (e3[m] > 1e-6)
            if ok.any():
                r = e3[m][ok] / e2[m][ok] * isl["scale"]
                out[isl["name"]] = (float(r.min()), float(r.max()))
        return out


def refine_patch(P, u_at=None, v_at=None):
    """Тот же лоскут с добавленными рядами: u_at / v_at — дробные индексы новых точек сетки (между
    существующими). Старые точки остаются на месте, новые лежат на кубическом сплайне через сетку,
    поэтому форма не меняется, а квады у складки мельче. Добавление рядов по v меняет кромки u=0 и u=−1,
    по u — кромки v=0 и v=−1: сгущать можно только по направлению, кромки которого ни с чем не сварены."""
    from scipy.interpolate import make_interp_spline

    def along(G, axis, extra, closed):
        if extra is None or not len(extra):
            return G
        n = G.shape[axis]
        idx = np.sort(np.unique(np.concatenate([np.arange(n, dtype=float), np.asarray(extra, float)])))
        if closed:
            W = np.concatenate([G, np.take(G, [0], axis=axis)], axis=axis)
            sp = make_interp_spline(np.arange(n + 1, dtype=float), W, k=3, axis=axis, bc_type="periodic")
            idx = idx[idx < n]
        else:
            k = 3 if n >= 4 else 1
            sp = make_interp_spline(np.arange(n, dtype=float), G, k=k, axis=axis)
            idx = idx[idx <= n - 1]
        out = sp(idx)
        base = np.isclose(idx, np.round(idx))                  # исходные точки — без погрешности сплайна
        sl = [slice(None)] * 3
        sl[axis] = np.nonzero(base)[0]
        src = [slice(None)] * 3
        src[axis] = np.round(idx[base]).astype(int)
        out[tuple(sl)] = G[tuple(src)]
        return out
    G = along(np.asarray(P.G, float), 1, v_at, P.closed_v)
    G = along(G, 0, u_at, P.closed_u)
    return Patch(G, P.closed_u, P.closed_v, P.name, P.uv_scale)


# ================================================================== сборка деталей из сеток
def _patches(grids, closed_u=False, closed_v=False, names=None):
    out = []
    for k, g in enumerate(grids):
        if isinstance(g, Patch):
            out.append(g)
        else:
            out.append(Patch(g, closed_u, closed_v, names[k] if names else f"p{k}"))
    return out


def quad_skin(bands, t, flip=False, closed_u=False, closed_v=False, names=None, weld=1e-3, sharp_borders=False):
    """Квадовый аналог kit.skin: панель с толщиной t из одного или нескольких лоскутов.

    bands — сетки (nu, nv, 3) или готовые Patch; совпадающие ряды свариваются (общий ряд — характерное
    ребро). Толщина наращивается в сторону «минус нормаль» сетки, как в skin(); flip меняет сторону
    (сетки разворачиваются). t=0 — один слой без толщины (материал двусторонний)."""
    if isinstance(bands, np.ndarray) and bands.ndim == 3:
        bands = [bands]
    ps = _patches(bands, closed_u, closed_v, names)
    if flip:
        ps = [p.flipped() for p in ps]
    return QuadMesh.from_patches(ps, weld, sharp_borders).solidify(t)


def quad_shell(patches, t=0.0, weld=1e-3, sharp_borders=False):
    """Замкнутая или открытая оболочка из готовых Patch (трубы, заглушки, полосы)."""
    return QuadMesh.from_patches(_patches(patches), weld, sharp_borders).solidify(t)


def cap_grid(ring, flip=False):
    """Заглушка замкнутого кольца одними квадами («лесенка»): точка i соединяется с точкой n−1−i.
    Кольцо — (n, 3), n чётное. Возвращает сетку (n/2, 2, 3); flip разворачивает нормаль."""
    R = np.asarray(ring, float)
    n = len(R)
    if n % 2:
        raise ValueError("заглушка квадами: в кольце должно быть чётное число точек")
    G = np.stack([R[: n // 2], R[::-1][: n // 2]], axis=1)
    return G[:, ::-1] if flip else G


def quad_tube(G, caps=True, closed_v=False, name="tube", sharp_caps=True):
    """Сплошное тело-труба из сетки колец G (nu по кольцу, nv вдоль): боковая поверхность и заглушки
    (или кольцо-тор при closed_v). Нормаль боковой сетки должна смотреть наружу."""
    G = np.asarray(G, float)
    ps = [Patch(G, closed_u=True, closed_v=closed_v, name=name)]
    if caps and not closed_v:
        ps.append(Patch(cap_grid(G[:, 0], flip=False), name=name + "_cap0"))
        ps.append(Patch(cap_grid(G[:, -1], flip=True), name=name + "_cap1"))
    m = QuadMesh.from_patches(ps, sharp_borders=False)
    if caps and not closed_v and sharp_caps:
        nu = G.shape[0]
        ring = lambda j: _find(m, G[:, j])
        e = []
        for j in (0, -1):
            r = ring(j)
            e.append(np.stack([r, np.roll(r, -1)], 1))
        m.sharp = np.unique(np.sort(np.vstack(e), axis=1), axis=0)
    # заглушки могли получить обратный обход — выровнять по боковой поверхности, затем наружу
    _orient_like_first(m)
    return _fix_outward(m)


def quad_sweep(profile, path, corners=None, up=None, closed_path=False, caps=True, scale=None, twist=None,
               name="sweep"):
    """Сплошное тело: замкнутый профиль (k, 2) вдоль кривой path (n, 3) — пояса, ремни, канты, ручки.
    corners — индексы точек профиля с острым углом: профиль делится по ним на лоскуты (каждая грань —
    свой остров, ребро между ними острое). Без corners профиль гладкий (один лоскут по кольцу).
    closed_path — кривая замкнута (кольцо); иначе концы закрываются заглушками (caps)."""
    G = sweep_grid(profile, path, up, closed_path, scale, twist)
    k = G.shape[0]
    if corners:
        cs = sorted(set(int(c) % k for c in corners))
        ps = [Patch(G[[i % k for i in range(a, b + 1)]], False, closed_path, f"{name}_{a}")
              for a, b in zip(cs, cs[1:] + [cs[0] + k])]
    else:
        ps = [Patch(G, True, closed_path, name)]
    if caps and not closed_path:
        ps += [Patch(cap_grid(G[:, 0]), name=name + "_cap0"), Patch(cap_grid(G[:, -1], flip=True), name=name + "_cap1")]
    m = QuadMesh.from_patches(ps, sharp_borders=bool(corners))
    if caps and not closed_path and not corners:
        e = []
        for j in (0, -1):
            r = _find(m, G[:, j])
            e.append(np.stack([r, np.roll(r, -1)], 1))
        m.sharp = np.unique(np.sort(np.vstack(e), axis=1), axis=0)
    _orient_like_first(m)
    return _fix_outward(m)


def _find(m, pts):
    from scipy.spatial import cKDTree
    return cKDTree(m.V).query(np.asarray(pts, float))[1]


def _orient_like_first(m):
    """Согласовать обход граней с первым островом (обход по смежности через общие рёбра)."""
    F = m.F
    edge_faces = {}
    for k, f in enumerate(F):
        vs = [v for v in f if v >= 0]
        for a, b in zip(vs, vs[1:] + vs[:1]):
            edge_faces.setdefault((min(a, b), max(a, b)), []).append((k, a, b))
    seen = np.zeros(len(F), bool)
    flip = np.zeros(len(F), bool)
    adj = {}
    for lst in edge_faces.values():
        if len(lst) == 2:
            (k1, a1, b1), (k2, a2, b2) = lst
            same = (a1, b1) == (a2, b2)             # одинаковое направление — обходы не согласованы
            adj.setdefault(k1, []).append((k2, same))
            adj.setdefault(k2, []).append((k1, same))
    for s in range(len(F)):
        if seen[s]:
            continue
        seen[s] = True
        stack = [s]
        while stack:
            k = stack.pop()
            for k2, same in adj.get(k, []):
                if not seen[k2]:
                    seen[k2] = True
                    flip[k2] = flip[k] ^ same
                    stack.append(k2)
    for k in np.nonzero(flip)[0]:
        n = 4 if F[k, 3] >= 0 else 3
        F[k, :n] = F[k, :n][::-1]
        m.UV[k, :n] = m.UV[k, :n][::-1]


# ================================================================== генераторы сеток
def frames(path, up=None, closed=False):
    """Касательная T, нормаль N и бинормаль B вдоль ломаной path (n, 3).
    up задан — B держится ближе к up (пояса, воротники: профиль не закручивается);
    иначе — кадры с минимальным кручением (ленты, шнуры)."""
    P = np.asarray(path, float)
    n = len(P)
    if closed:
        T = np.roll(P, -1, axis=0) - np.roll(P, 1, axis=0)
    else:
        T = np.gradient(P, axis=0)
    T /= np.maximum(np.linalg.norm(T, axis=1, keepdims=True), 1e-12)
    if up is not None:
        up = np.broadcast_to(np.asarray(up, float), (n, 3))
        N = np.cross(up, T)
        N /= np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-12)
        return T, N, np.cross(T, N)
    a = np.array([0.0, 0.0, 1.0]) if abs(T[0][2]) < 0.9 else np.array([1.0, 0.0, 0.0])
    N0 = np.cross(a, T[0])
    N0 /= np.linalg.norm(N0)
    Ns = [N0]
    for i in range(1, n):                       # параллельный перенос (double reflection)
        v1 = P[i] - P[i - 1]
        c1 = max(v1 @ v1, 1e-18)
        rl = Ns[-1] - (2 / c1) * (v1 @ Ns[-1]) * v1
        tl = T[i - 1] - (2 / c1) * (v1 @ T[i - 1]) * v1
        v2 = T[i] - tl
        c2 = max(v2 @ v2, 1e-18)
        Ns.append(rl - (2 / c2) * (v2 @ rl) * v2)
    N = np.array(Ns)
    return T, N, np.cross(T, N)


def sweep_grid(profile, path, up=None, closed_path=False, scale=None, twist=None):
    """Профиль вдоль кривой: profile — точки (k, 2) в осях (N, B) сечения, path — (n, 3).
    scale[j] — масштаб профиля в точке пути, twist[j] — поворот, град. Возвращает (k, n, 3).
    Замкнутый профиль -> quad_tube(сетка); открытый -> полоса для quad_skin."""
    pr = np.asarray(profile, float)
    P = np.asarray(path, float)
    T, N, B = frames(P, up, closed_path)
    n = len(P)
    sc = np.ones(n) if scale is None else np.broadcast_to(np.asarray(scale, float), (n,))
    tw = np.zeros(n) if twist is None else np.radians(np.broadcast_to(np.asarray(twist, float), (n,)))
    c, s = np.cos(tw), np.sin(tw)
    a = pr[:, 0][:, None] * c[None, :] - pr[:, 1][:, None] * s[None, :]
    b = pr[:, 0][:, None] * s[None, :] + pr[:, 1][:, None] * c[None, :]
    return P[None, :, :] + (a * sc)[:, :, None] * N[None, :, :] + (b * sc)[:, :, None] * B[None, :, :]


def loft_grid(rings):
    """Кольца или линии с одинаковым числом точек [(k, 3), ...] -> сетка (k, n, 3)."""
    return np.stack([np.asarray(r, float) for r in rings], axis=1)


def revolve_grid(profile_ru, center, axis=(0, 1, 0), n=24):
    """Вращение профиля [(радиус, смещение вдоль оси), ...] вокруг оси через center: сетка (n, k, 3),
    замкнутая по u. Точки профиля с радиусом 0 дают полюс (веер треугольников)."""
    ax = np.asarray(axis, float)
    ax = ax / np.linalg.norm(ax)
    p = np.array([1.0, 0, 0]) if abs(ax[0]) < 0.9 else np.array([0, 0, 1.0])
    e1 = p - ax * (p @ ax)
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(ax, e1)
    pr = np.asarray(profile_ru, float)
    th = np.arange(n) * 2 * math.pi / n
    d = np.cos(th)[:, None] * e1[None] + np.sin(th)[:, None] * e2[None]
    return np.asarray(center, float) + pr[None, :, :1] * d[:, None, :] + pr[None, :, 1:] * ax[None, None, :]


def revolve_quad(profile_ru, center, axis=(0, 1, 0), n=24, name="rev"):
    """Тело вращения квадами: профиль от оси до оси (первый и последний радиус 0) или кольцо."""
    G = revolve_grid(profile_ru, center, axis, n)
    m = QuadMesh.from_patches([Patch(G, closed_u=True, name=name)])
    _fix_outward(m)
    return m


def _fix_outward(m):
    """Развернуть меш целиком, если его объём отрицательный (нормали внутрь)."""
    T = m.triangles()
    a, b, c = m.V[T[:, 0]], m.V[T[:, 1]], m.V[T[:, 2]]
    if np.sum(np.einsum("ij,ij->i", a, np.cross(b, c))) < 0:
        for k in range(len(m.F)):
            n = 4 if m.F[k, 3] >= 0 else 3
            m.F[k, :n] = m.F[k, :n][::-1]
            m.UV[k, :n] = m.UV[k, :n][::-1]
        m.patches = [p.flipped() for p in m.patches]
    return m


def box_quad(x0, y0, z0, x1, y1, z1, n=(1, 1, 1), name="box"):
    """Параллелепипед квадами с острыми рёбрами: по n[i] ячеек вдоль осей."""
    xs, ys, zs = (np.linspace(a, b, k + 1) for a, b, k in ((x0, x1, n[0]), (y0, y1, n[1]), (z0, z1, n[2])))

    def face(f, us, vs):
        return np.array([[f(u, v) for v in vs] for u in us], float)
    ps = [Patch(face(lambda y, z: (x1, y, z), ys, zs), name=name + "_x1"),
          Patch(face(lambda z, y: (x0, y, z), zs, ys), name=name + "_x0"),
          Patch(face(lambda z, x: (x, y1, z), zs, xs), name=name + "_y1"),
          Patch(face(lambda x, z: (x, y0, z), xs, zs), name=name + "_y0"),
          Patch(face(lambda x, y: (x, y, z1), xs, ys), name=name + "_z1"),
          Patch(face(lambda y, x: (x, y, z0), ys, xs), name=name + "_z0")]
    return QuadMesh.from_patches(ps, sharp_borders=True)


# ================================================================== сечение меша плоскостью
def slice_mesh(V, T, origin, normal):
    """Сечение треугольного меша плоскостью -> список ломаных (k, 3); замкнутые повторяют первую точку.
    V (N, 3), T (K, 3). Цепочки собираются по общим рёбрам меша, без допусков."""
    V = np.asarray(V, float)
    T = np.asarray(T, int)
    nrm = np.asarray(normal, float)
    d = (V - np.asarray(origin, float)) @ (nrm / np.linalg.norm(nrm))
    d = np.where(d == 0.0, 1e-9, d)
    s = d[T] > 0
    hit = np.nonzero(s.any(axis=1) & ~s.all(axis=1))[0]
    if not len(hit):
        return []
    pts, key_id, segs = [], {}, []
    for k in hit:
        ends = []
        for a, b in ((0, 1), (1, 2), (2, 0)):
            i, j = T[k, a], T[k, b]
            if (d[i] > 0) != (d[j] > 0):
                key = (i, j) if i < j else (j, i)
                if key not in key_id:
                    key_id[key] = len(pts)
                    t = d[i] / (d[i] - d[j])
                    pts.append(V[i] + (V[j] - V[i]) * t)
                ends.append(key_id[key])
        if len(ends) == 2:
            segs.append(ends)
    pts = np.array(pts)
    nb = {}
    for a, b in segs:
        nb.setdefault(a, []).append(b)
        nb.setdefault(b, []).append(a)
    used, out = set(), []
    starts = [p for p, l in nb.items() if len(l) == 1] + list(nb)       # сначала концы открытых цепочек
    for s0 in starts:
        if s0 in used:
            continue
        line, cur, prev = [s0], s0, None
        used.add(s0)
        while True:
            nxt = [q for q in nb[cur] if q != prev and (q not in used or (q == s0 and len(line) > 2))]
            if not nxt:
                break
            q = nxt[0]
            line.append(q)
            if q == s0:
                break
            used.add(q)
            prev, cur = cur, q
        if len(line) > 1:
            out.append(pts[line])
    return out


# ================================================================== атлас
def pack_islands(sizes, pad=0.012):
    """Раскладка прямоугольных островов [(w, h), ...] (мм) в квадрат «полками».
    Возвращает (сторона квадрата S, мм; [(x, y), ...] — левый нижний угол острова, мм). pad — поле
    между островами в долях стороны (при 2048 px — 24 px: при уменьшении текстуры, на mip-уровнях, цвет
    соседнего острова не затекает в мелкие острова). Масштаб у всех островов один: плотность текселей одинаковая."""
    if not sizes:
        return 1.0, []
    order = sorted(range(len(sizes)), key=lambda i: -sizes[i][1])
    S = max(math.sqrt(sum(w * h for w, h in sizes)) * 1.05, max(max(w, h) for w, h in sizes) * 1.02)
    while True:
        p = S * pad
        x, y, row_h, pos, ok = p, p, 0.0, [None] * len(sizes), True
        for i in order:
            w, h = sizes[i]
            if w + 2 * p > S:
                ok = False
                break
            if x + w + p > S:
                x, y, row_h = p, y + row_h + p, 0.0
            pos[i] = (x, y)
            x += w + p
            row_h = max(row_h, h)
        if ok and y + row_h + p <= S:
            return S, pos
        S *= 1.04


# ================================================================== тело-меш для чертежа
class _Pt:
    def __init__(self, p):
        self.X, self.Y, self.Z = (float(c) for c in p)


class _Box:
    def __init__(self, lo, hi):
        self.min, self.max = _Pt(lo), _Pt(hi)


class MeshShape:
    """Готовый треугольный меш вместо тела build123d — обстановка на чертеже (group="phantom"):
    тело персонажа под одеждой. На видах рисуется видимый контур (drawing.mesh_outline), в разрезах —
    кольцо сечения. V (N, 3) мм, T (K, 3)."""

    def __init__(self, V, T):
        self.V = np.asarray(V, float)
        self.T = np.asarray(T, int)
        self.label = ""

    def bounding_box(self):
        return _Box(self.V.min(axis=0), self.V.max(axis=0))
