"""Тело персонажа — опора для одежды: меш с ригом в numpy, ориентиры, мерки, сечения, поверхность
со смещением, расстояния до тела, перенос весов и позы.

Система координат персонажа (та же, что у предметов): Z вверх от пола, X — назад (перёд смотрит в −X),
левая сторона персонажа — −Y. Миллиметры. После сборки в Blender: перёд −Y, левая рука +X — как ждёт Unity.

Тело загружается из .blend / .glb / .fbx через Blender в фоне (bl_body.py) и кешируется в .cache/:
на стороне спецификации — только массивы. Поза покоя любая (A или T): всё считается от костей.

    BODY = body.load(body.MANNEQUIN_F)
    BODY.lm["waist"], BODY.measures["bust"]        # ориентиры и мерки
    G = BODY.torso_grid(zs, nu=48, offset=4.0)     # сетка (nu, nv, 3) на теле + отступ — основа лифа
    G = BODY.limb_grid("arm_L", ts, nu=20, offset=3.0)

Кости тела сводятся к ролям (hips, spine, chest, neck, head, clavicle_L, upper_arm_L, forearm_L, hand_L,
thigh_L, shin_L, foot_L, toe_L и то же с _R) по именам; если имена необычные — передать roles={роль: имя}.
"""
import hashlib, json, math, os, re, subprocess
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CACHE = os.path.join(ROOT, ".cache")
MANNEQUIN_F = os.path.join(ROOT, "bodies", "mannequin_f", "mannequin_f.blend")     # MakeHuman, A-поза
DUMMY_T = os.path.join(ROOT, "bodies", "dummy_t", "dummy_t.blend")                 # манекен кодом, T-поза

LIMB_ROLES = ("clavicle", "upper_arm", "forearm", "hand", "thigh", "shin", "foot", "toe")
ROLES = ["hips", "spine", "chest", "upper_chest", "neck", "head"] + [f"{r}_{s}" for s in "LR" for r in LIMB_ROLES]
REGION_OF = {"hips": "torso", "spine": "torso", "chest": "torso", "upper_chest": "torso", "neck": "head",
             "head": "head", "clavicle": "torso", "upper_arm": "arm", "forearm": "arm", "hand": "arm",
             "thigh": "leg", "shin": "leg", "foot": "leg", "toe": "leg"}
REGIONS = ["torso", "head", "arm_L", "arm_R", "leg_L", "leg_R"]
_NAMES = {
    "hips": ("hips", "pelvis", "hip"), "neck": ("neck",), "head": ("head",), "chest": ("chest",),
    "upper_chest": ("upperchest",),
    "clavicle": ("shoulder", "clavicle", "collar"), "upper_arm": ("upperarm", "arm", "uparm"),
    "forearm": ("lowerarm", "forearm"), "hand": ("hand",),
    "thigh": ("upperleg", "upleg", "thigh"), "shin": ("lowerleg", "leg", "calf", "shin"),
    "foot": ("foot",), "toe": ("toes", "toe", "toebase", "ball"),
}
_SKIP = ("twist", "roll", "ik", "pole", "helper", "breast", "buttock", "end", "ctrl", "target")


def _tokens(name):
    n = name.split(":")[-1]
    n = re.sub(r"([a-z])([A-Z])", r"\1_\2", n).lower()
    return [t for t in re.split(r"[^a-z0-9]+", n) if t]


def guess_roles(names, parent):
    """Роли костей по именам (Unity Humanoid, Mixamo, UE/MakeHuman game_engine, Rigify и похожие)."""
    depth = []
    for i in range(len(names)):
        d, p = 0, parent[i]
        while p >= 0:
            d, p = d + 1, parent[p]
        depth.append(d)
    cand, spine = {}, []
    for i in sorted(range(len(names)), key=lambda i: depth[i]):
        tk = _tokens(names[i])
        side = "L" if ("l" in tk or "left" in tk) else "R" if ("r" in tk or "right" in tk) else ""
        core = "".join(t for t in tk if t not in ("l", "r", "left", "right", "def", "mixamorig"))
        if any(s in core for s in _SKIP):
            continue
        stem = re.sub(r"\d+$", "", core)
        if stem == "spine" and not side:
            spine.append(i)
            continue
        for role, keys in _NAMES.items():
            if stem in keys:
                key = f"{role}_{side}" if role in LIMB_ROLES else role
                if (role in LIMB_ROLES) == bool(side):
                    cand.setdefault(key, i)
    for role, i in zip([r for r in ("spine", "chest", "upper_chest") if r not in cand], spine):
        cand[role] = i
    return cand


def _rot(axis, deg):
    a = np.asarray({"x": (1, 0, 0), "y": (0, 1, 0), "z": (0, 0, 1)}.get(axis, axis) if isinstance(axis, str) else axis, float)
    a = a / np.linalg.norm(a)
    t = math.radians(deg)
    K = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    return np.eye(3) + math.sin(t) * K + (1 - math.cos(t)) * (K @ K)


def rotation(spec, mirror=False):
    """Поворот из списка [(ось, градусы), ...] в осях персонажа (применяются по порядку) или матрицы 3×3.
    mirror — тот же поворот для другой стороны тела (зеркало относительно плоскости XZ)."""
    if isinstance(spec, np.ndarray):
        R = spec
    else:
        R = np.eye(3)
        for axis, deg in spec:
            R = _rot(axis, deg) @ R
    if mirror:
        M = np.diag([1.0, -1.0, 1.0])
        R = M @ R @ M
    return R


def closest_on_tris(P, A, B, C):
    """Ближайшая точка треугольника (Ericson): барицентрические координаты (m, 3) для точек P (m, 3)."""
    AB, AC, AP = B - A, C - A, P - A
    d1, d2 = (AB * AP).sum(1), (AC * AP).sum(1)
    BP = P - B
    d3, d4 = (AB * BP).sum(1), (AC * BP).sum(1)
    CP = P - C
    d5, d6 = (AB * CP).sum(1), (AC * CP).sum(1)
    va, vb, vc = d3 * d6 - d5 * d4, d5 * d2 - d1 * d6, d1 * d4 - d3 * d2
    den = va + vb + vc
    den = np.where(np.abs(den) < 1e-30, 1e-30, den)
    v, w = vb / den, vc / den
    z, o = np.zeros_like(v), np.ones_like(v)

    def sdiv(a, b):
        return a / np.where(np.abs(b) < 1e-30, 1e-30, b)
    t_ab, t_ac, t_bc = sdiv(d1, d1 - d3), sdiv(d2, d2 - d6), sdiv(d4 - d3, (d4 - d3) + (d5 - d6))
    conds = [(d1 <= 0) & (d2 <= 0), (d3 >= 0) & (d4 <= d3), (vc <= 0) & (d1 >= 0) & (d3 <= 0),
             (d6 >= 0) & (d5 <= d6), (vb <= 0) & (d2 >= 0) & (d6 <= 0), (va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0)]
    bu = np.select(conds, [o, z, 1 - t_ab, z, 1 - t_ac, z], 1 - v - w)
    bv = np.select(conds, [z, o, t_ab, z, z, 1 - t_bc], v)
    bw = np.select(conds, [z, z, z, o, t_ac, t_bc], w)
    return np.stack([bu, bv, bw], axis=1)


def plane_segments(V, T, origin, normal):
    """Отрезки пересечения треугольников плоскостью: (M, 2, 3). Без сборки в цепочки — для лучей."""
    n = np.asarray(normal, float)
    d = (V - np.asarray(origin, float)) @ (n / np.linalg.norm(n))
    d = np.where(d == 0.0, 1e-9, d)
    dt = d[T]
    s = dt > 0
    hit = s.any(1) & ~s.all(1)
    Th, dh, sh = T[hit], dt[hit], s[hit]
    if not len(Th):
        return np.zeros((0, 2, 3))
    lone = np.where((sh.sum(1) == 1)[:, None], sh, ~sh).argmax(1)
    r = np.arange(len(Th))
    i1, i2 = (lone + 1) % 3, (lone + 2) % 3
    v0, v1, v2 = V[Th[r, lone]], V[Th[r, i1]], V[Th[r, i2]]
    d0, d1, d2 = dh[r, lone], dh[r, i1], dh[r, i2]
    return np.stack([v0 + (v1 - v0) * (d0 / (d0 - d1))[:, None], v0 + (v2 - v0) * (d0 / (d0 - d2))[:, None]], axis=1)


def _ray_segments(dirs, A, B, mode):
    """Лучи из начала координат (K, 2) против отрезков A–B (M, 2): радиус дальнего/ближнего пересечения."""
    E = B - A
    den = dirs[:, 0:1] * E[None, :, 1] - dirs[:, 1:2] * E[None, :, 0]
    den = np.where(np.abs(den) < 1e-12, 1e-12, den)
    r = (A[:, 0] * E[:, 1] - A[:, 1] * E[:, 0])[None, :] / den
    s = (A[None, :, 0] * dirs[:, 1:2] - A[None, :, 1] * dirs[:, 0:1]) / den
    ok = (s >= -1e-9) & (s <= 1 + 1e-9) & (r > 1e-6)
    if mode == "far":
        out = np.where(ok, r, -np.inf).max(axis=1)
    else:
        out = np.where(ok, r, np.inf).min(axis=1)
    return np.where(np.isfinite(out), out, np.nan)


def _fill_circular(r):
    """Заполнить пропуски (NaN) линейной интерполяцией по кругу."""
    r = np.asarray(r, float)
    ok = np.isfinite(r)
    if ok.all():
        return r
    if not ok.any():
        raise ValueError("сечение тела пустое: луч не нашёл поверхность (проверьте высоту и область)")
    n = len(r)
    i = np.nonzero(ok)[0]
    return np.interp(np.arange(n), np.concatenate([i - n, i, i + n]), np.tile(r[ok], 3))


def _smooth_circular(r, sigma):
    if sigma <= 0:
        return r
    n = len(r)
    k = int(max(1, math.ceil(sigma * 3)))
    w = np.exp(-0.5 * (np.arange(-k, k + 1) / sigma) ** 2)
    w /= w.sum()
    return np.convolve(np.concatenate([r[-k:], r, r[:k]]), w, mode="valid")[:n]


class Skeleton:
    """Кости: имена, родитель, начало и конец в позе покоя (мм, координаты персонажа)."""

    def __init__(self, names, parent, head, tail):
        self.names = [str(n) for n in names]
        self.parent = np.asarray(parent, int)
        self.head = np.asarray(head, float)
        self.tail = np.asarray(tail, float)
        self.index = {n: i for i, n in enumerate(self.names)}

    def extended(self, bones):
        """Новый скелет с добавленными костями [(имя, имя родителя, начало, конец), ...]."""
        names, parent = list(self.names), list(self.parent)
        head, tail = list(self.head), list(self.tail)
        for n, p, a, b in bones:
            idx = {m: i for i, m in enumerate(names)}
            parent.append(idx[p])
            names.append(n)
            head.append(np.asarray(a, float))
            tail.append(np.asarray(b, float))
        return Skeleton(names, parent, np.array(head), np.array(tail))

    def matrices(self, rot, root_shift=(0, 0, 0)):
        """Матрицы костей 4×4 (поза относительно покоя) из {индекс кости: поворот 3×3 в осях персонажа}.
        Поворот кости — вокруг её начала, в системе родителя: M_b = M_parent · T(h) · R · T(−h)."""
        M = np.zeros((len(self.names), 4, 4))
        for b in range(len(self.names)):
            L = np.eye(4)
            R = rot.get(b)
            if R is not None:
                L[:3, :3] = R
                L[:3, 3] = self.head[b] - R @ self.head[b]
            if self.parent[b] >= 0:
                M[b] = M[self.parent[b]] @ L
            else:
                L[:3, 3] += np.asarray(root_shift, float)
                M[b] = L
        return M


def skin_points(P, W, M):
    """Линейный скиннинг: точки P (n, 3), веса W (n, B), матрицы M (B, 4, 4)."""
    Ph = np.concatenate([P, np.ones((len(P), 1))], axis=1)
    out = np.zeros((len(P), 3))
    for b in np.nonzero(W.any(axis=0))[0]:
        out += W[:, b:b + 1] * (Ph @ M[b].T)[:, :3]
    return out


class Surface:
    """Треугольная поверхность с быстрым поиском ближайшей точки: тело в покое и в позе, наружный слой
    одежды. V (N, 3), T (K, 3); нормали вершин считаются по граням, если не заданы."""

    def __init__(self, V, T, N=None):
        from scipy.spatial import cKDTree
        self.V = np.asarray(V, float)
        self.T = np.asarray(T, int)
        if N is None:
            fn = np.cross(self.V[self.T[:, 1]] - self.V[self.T[:, 0]], self.V[self.T[:, 2]] - self.V[self.T[:, 0]])
            N = np.zeros_like(self.V)
            for i in range(3):
                np.add.at(N, self.T[:, i], fn)
            N /= np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-12)
        self.N = N
        used = np.unique(self.T)
        self._ids = used
        self._tree = cKDTree(self.V[used])
        cnt = np.bincount(self.T.ravel(), minlength=len(self.V))
        k = int(min(max(cnt.max(), 1), 14))
        vt = np.full((len(self.V), k), -1)
        fill = np.zeros(len(self.V), int)
        for t, tri in enumerate(self.T):
            for v in tri:
                if fill[v] < k:
                    vt[v, fill[v]] = t
                    fill[v] += 1
        self._vt = vt

    def closest(self, P, tri_mask=None, k=6):
        """Ближайшие точки поверхности: dict(dist со знаком — плюс со стороны нормали, point, tri, bary, normal)."""
        P = np.asarray(P, float).reshape(-1, 3)
        n = len(P)
        out_d = np.full(n, np.inf)
        out_t = np.zeros(n, int)
        out_b = np.zeros((n, 3))
        k = min(k, len(self._ids))
        for s in range(0, n, 3000):
            Q = P[s:s + 3000]
            _, nn = self._tree.query(Q, k=k)
            cand = self._vt[self._ids[nn.reshape(len(Q), -1)]].reshape(len(Q), -1)
            ok = cand >= 0
            if tri_mask is not None:
                ok &= tri_mask[np.clip(cand, 0, None)]
            ci = np.clip(cand, 0, None)
            m = cand.shape[1]
            Qr = np.repeat(Q, m, axis=0)
            Tt = self.T[ci.ravel()]
            A, B, C = self.V[Tt[:, 0]], self.V[Tt[:, 1]], self.V[Tt[:, 2]]
            bc = closest_on_tris(Qr, A, B, C)
            X = bc[:, :1] * A + bc[:, 1:2] * B + bc[:, 2:] * C
            d = np.linalg.norm(Qr - X, axis=1).reshape(len(Q), m)
            d[~ok] = np.inf
            j = d.argmin(axis=1)
            r = np.arange(len(Q))
            out_d[s:s + len(Q)] = d[r, j]
            out_t[s:s + len(Q)] = ci[r, j]
            out_b[s:s + len(Q)] = bc.reshape(len(Q), m, 3)[r, j]
        Tt = self.T[out_t]
        X = (out_b[:, :, None] * self.V[Tt]).sum(axis=1)
        Nn = (out_b[:, :, None] * self.N[Tt]).sum(axis=1)
        Nn /= np.maximum(np.linalg.norm(Nn, axis=1, keepdims=True), 1e-12)
        sign = np.where(((P - X) * Nn).sum(axis=1) >= 0, 1.0, -1.0)
        return dict(dist=out_d * sign, point=X, tri=out_t, bary=out_b, normal=Nn)


class Body:
    def __init__(self, data, source="", source_hash="", roles=None, landmarks=None):
        self.V = np.asarray(data["V"], float)
        self.T = np.asarray(data["T"], int)
        self.N = np.asarray(data["N"], float)
        self.W = np.asarray(data["W"], np.float32)
        self.tri_poly = np.asarray(data["tri_poly"], int)
        self.skel = Skeleton(data["bone_names"], data["bone_parent"], data["bone_head"], data["bone_tail"])
        self.armature = str(data["armature"])
        self.mesh_names = [str(n) for n in data["mesh_names"]]
        self.source, self.source_hash = source, source_hash
        g = guess_roles(self.skel.names, self.skel.parent)
        for role, name in (roles or {}).items():
            if name not in self.skel.index:
                raise ValueError(f"роль {role}: кости {name!r} нет в скелете")
            g[role] = self.skel.index[name]
        need = [r for r in ROLES if r not in g and r not in ("upper_chest", "chest", "toe_L", "toe_R",
                                                             "clavicle_L", "clavicle_R")]
        if need:
            raise ValueError("не найдены кости для ролей " + ", ".join(need) + ". Передайте roles={роль: имя кости}. "
                             "Кости скелета: " + ", ".join(self.skel.names))
        self.roles = g
        self._regions()
        self._adjacency()
        self.lm = {}
        self._landmarks()
        self.lm.update(landmarks or {})
        self.measures = self._measures()

    # ------------------------------------------------------------ области тела
    def bone(self, role_or_name):
        """Индекс кости по роли («upper_arm_L») или имени."""
        if role_or_name in self.roles:
            return self.roles[role_or_name]
        if role_or_name in self.skel.index:
            return self.skel.index[role_or_name]
        raise KeyError(f"нет кости или роли {role_or_name!r}; роли: {', '.join(sorted(self.roles))}")

    def joint(self, role):
        return self.skel.head[self.bone(role)].copy()

    def _regions(self):
        nb = len(self.skel.names)
        by_bone = {i: r for r, i in self.roles.items()}
        self.bone_role = []
        for b in range(nb):
            p = b
            while p >= 0 and p not in by_bone:
                p = self.skel.parent[p]
            self.bone_role.append(by_bone.get(p, "hips"))
        reg = []
        for r in self.bone_role:
            base = r[:-2] if r[-2:] in ("_L", "_R") else r
            g = REGION_OF[base]
            reg.append(g + r[-2:] if g in ("arm", "leg") else g)
        self.bone_region = np.array([REGIONS.index(g) for g in reg])
        RW = np.zeros((len(self.V), len(REGIONS)), np.float32)
        for b in range(nb):
            RW[:, self.bone_region[b]] += self.W[:, b]
        self.region_w = RW
        self.vreg = RW.argmax(axis=1)
        self.treg = RW[self.T].sum(axis=1).argmax(axis=1)

    def tri_mask(self, regions=None):
        """Маска треугольников по областям ("torso", "head", "arm_L", "leg_R", ...); None — все."""
        if regions is None:
            return np.ones(len(self.T), bool)
        ids = [REGIONS.index(r) for r in regions]
        return np.isin(self.treg, ids)

    def role_weight(self, roles):
        """Суммарный вес вершин тела по костям ролей (с дочерними костями: пальцы идут с кистью)."""
        roles = set(roles)
        cols = [b for b in range(len(self.skel.names)) if self.bone_role[b] in roles]
        return self.W[:, cols].sum(axis=1)

    def _adjacency(self):
        self._surf = Surface(self.V, self.T, self.N)

    # ------------------------------------------------------------ расстояние до тела и перенос весов
    def closest(self, P, tri_mask=None, k=6):
        """Ближайшие точки поверхности тела. Возвращает dict: dist — расстояние со знаком (плюс снаружи,
        минус внутри тела), point, tri (индекс треугольника), bary, normal (наружу)."""
        return self._surf.closest(P, tri_mask, k)

    def weights_at(self, P, regions=None, roles=None, hit=None):
        """Веса скиннинга для точек P: перенос с ближайшей поверхности тела с интерполяцией внутри
        треугольника. regions / roles ограничивают донорскую часть тела (рукав берёт веса только с руки,
        чулок — только со своей ноги): иначе точка у подмышки или между ног схватит чужую кость."""
        mask = None
        if regions is not None:
            mask = self.tri_mask(regions)
        if roles is not None:
            rw = self.role_weight(roles)
            m2 = rw[self.T].mean(axis=1) > 0.5
            mask = m2 if mask is None else (mask & m2)
        h = hit if hit is not None else self.closest(P, mask, k=10 if mask is not None else 6)
        bad = ~np.isfinite(h["dist"])
        if bad.any():                               # рядом нет треугольников нужной области — искать по всем
            h2 = self.closest(np.asarray(P, float).reshape(-1, 3)[bad])
            for key in ("tri", "bary"):
                h[key][bad] = h2[key]
        Tt = self.T[h["tri"]]
        return (h["bary"][:, :, None] * self.W[Tt]).sum(axis=1)

    def push_out(self, G, clearance, iters=3, cells=True):
        """Вытолкнуть точки сетки из тела до отступа не меньше clearance (мм): точка ближе — сдвигается
        от поверхности по её нормали. Гарантирует отсутствие проникновения в исходной позе."""
        G = np.array(G, float)
        P = G.reshape(-1, 3)
        cl = np.broadcast_to(np.asarray(clearance, float), G.shape[:-1]).reshape(-1) if np.ndim(clearance) else clearance
        for _ in range(iters):
            h = self.closest(P)
            lack = cl - h["dist"]
            m = lack > 1e-3
            if not m.any():
                break
            P[m] = P[m] + h["normal"][m] * lack[m][:, None]
        G = P.reshape(G.shape)
        if cells and G.shape[0] > 1 and G.shape[1] > 1:
            # Плоский квад срезает выпуклость тела: между вершинами зазор меньше, чем в вершинах.
            # Середина ячейки ближе к телу, чем половина отступа, — её четыре угла отодвигаются.
            clg = np.reshape(cl, G.shape[:2]) if np.ndim(cl) else np.full(G.shape[:2], float(cl))
            for _ in range(2):
                C = (G[:-1, :-1] + G[1:, :-1] + G[1:, 1:] + G[:-1, 1:]) / 4
                need = (clg[:-1, :-1] + clg[1:, :-1] + clg[1:, 1:] + clg[:-1, 1:]) / 4 * 0.6
                h = self.closest(C.reshape(-1, 3))
                lack = np.clip(need.reshape(-1) - h["dist"], 0.0, None)
                if not (lack > 1e-3).any():
                    break
                mv = (h["normal"] * lack[:, None]).reshape(C.shape)
                add = np.zeros_like(G)
                cnt = np.zeros(G.shape[:2])
                for di, dj in ((0, 0), (1, 0), (1, 1), (0, 1)):
                    sl = (slice(di, di + C.shape[0]), slice(dj, dj + C.shape[1]))
                    add[sl] = np.where((np.linalg.norm(mv, axis=2) > np.linalg.norm(add[sl], axis=2))[..., None], mv, add[sl])
                G = G + add * (clg > -1e8)[..., None]
        return G

    # ------------------------------------------------------------ сечения и кольца
    def section(self, origin, normal, regions=None):
        """Сечение тела плоскостью: список ломаных (k, 3)."""
        from .mesh import slice_mesh
        return slice_mesh(self.V, self.T[self.tri_mask(regions)], origin, normal)

    def ring(self, origin, axis, ref, n=48, regions=None, mode="far", tent=0.0, smooth=0.0, offset=0.0,
             thetas=None, rmax=None):
        """Кольцо тела вокруг оси: n точек в плоскости через origin с нормалью axis; угол отсчитывается
        от ref и растёт против часовой стрелки, если смотреть навстречу оси (сетка колец вдоль оси даёт
        нормаль наружу).

        mode="far" — наружная огибающая (туловище: луч из оси берёт дальнюю поверхность), "near" —
        ближняя (конечность: своя поверхность, а не соседняя нога). tent 0…1 — натяжение ткани: 0 — по телу,
        1 — по выпуклой оболочке сечения (мостик через впадины, между ног). smooth — сглаживание по кругу
        (в шагах сетки). offset — отступ наружу, мм (скаляр или массив по кругу)."""
        o = np.asarray(origin, float)
        ez = np.asarray(axis, float)
        ez = ez / np.linalg.norm(ez)
        ex = np.asarray(ref, float)
        ex = ex - ez * (ex @ ez)
        ex /= np.linalg.norm(ex)
        ey = np.cross(ez, ex)
        th = np.arange(n) * 2 * math.pi / n if thetas is None else np.asarray(thetas, float)
        dirs = np.stack([np.cos(th), np.sin(th)], axis=1)
        S = plane_segments(self.V, self.T[self.tri_mask(regions)], o, ez)
        if not len(S):
            raise ValueError(f"сечение тела пустое в точке {np.round(o).tolist()} (области {regions})")
        A = np.stack([(S[:, 0] - o) @ ex, (S[:, 0] - o) @ ey], axis=1)
        B = np.stack([(S[:, 1] - o) @ ex, (S[:, 1] - o) @ ey], axis=1)
        if rmax is not None:                           # только ближайшая окрестность оси (конечность)
            keep = (np.linalg.norm(A, axis=1) < rmax) & (np.linalg.norm(B, axis=1) < rmax)
            A, B = A[keep], B[keep]
        r = _ray_segments(dirs, A, B, mode)
        if tent > 0 or not np.isfinite(r).all():
            from scipy.spatial import ConvexHull
            pts = np.vstack([A, B])
            hv = pts[ConvexHull(pts).vertices]
            rh = _ray_segments(dirs, hv, np.roll(hv, -1, axis=0), "far")
            rh = _fill_circular(rh)
            r = np.where(np.isfinite(r), r, rh)
            r = r + (rh - r) * tent
        r = _smooth_circular(_fill_circular(r), smooth)
        if np.ndim(offset) or offset:
            P2 = dirs * r[:, None]
            tg = np.roll(P2, -1, axis=0) - np.roll(P2, 1, axis=0)
            nr = np.stack([tg[:, 1], -tg[:, 0]], axis=1)
            nr /= np.maximum(np.linalg.norm(nr, axis=1, keepdims=True), 1e-12)
            cs = np.clip((nr * dirs).sum(axis=1), 0.6, 1.0)
            r = r + np.asarray(offset, float) / cs
        return o + r[:, None] * (dirs[:, :1] * ex + dirs[:, 1:] * ey), r

    def center_x(self, z):
        """Середина туловища по X на высоте z (ось колец туловища и юбки проходит через неё)."""
        zs, xs = self._axis_table
        return float(np.interp(z, zs, xs))

    def torso_ring(self, z, n=48, offset=0.0, tent=0.0, smooth=1.0, down=False, legs=True):
        """Кольцо туловища на высоте z (ниже паха — огибающая обеих ног: tent подтягивается к 1).
        Начало кольца — середина спины. down=True — обход для сетки, идущей сверху вниз (юбка, лиф от
        плеч к талии): нормаль остаётся наружу."""
        regions = ("torso", "head", "leg_L", "leg_R") if legs else ("torso", "head")
        if z < self.lm["crotch"] + 15:
            tent = max(tent, 1.0)
        elif z < self.lm["crotch"] + 60:
            tent = max(tent, 1.0 - (z - self.lm["crotch"] - 15) / 45.0)
        return self.ring((self.center_x(z), 0.0, z), (0, 0, -1) if down else (0, 0, 1), (1, 0, 0), n, regions,
                         "far", tent, smooth, offset)[0]

    def torso_grid(self, zs, nu=48, offset=0.0, tent=0.0, smooth=1.0, legs=True):
        """Сетка (nu, nv, 3) на туловище: кольца на высотах zs плюс отступ. offset, tent — число, массив
        по высотам (nv,) или функция z -> число: плотно на талии, свободнее на груди. Порядок zs задаёт
        направление сетки: по возрастанию — снизу вверх, по убыванию — сверху вниз."""
        zs = np.asarray(zs, float)
        down = zs[-1] < zs[0]
        val = lambda p, j, z: (p(z) if callable(p) else (p[j] if np.ndim(p) else p))
        return np.stack([self.torso_ring(z, nu, val(offset, j, z), val(tent, j, z), smooth, down, legs)
                         for j, z in enumerate(zs)], axis=1)

    # ------------------------------------------------------------ конечности
    LIMBS = {"arm": ("upper_arm", "forearm", "hand"), "leg": ("thigh", "shin", "foot")}

    def limb_axis(self, limb):
        """Ось конечности «arm_L» / «leg_R»: точки (корень, средний сустав, конец) — плечо–локоть–запястье
        или бедро–колено–щиколотка."""
        kind, side = limb.split("_")
        return np.array([self.joint(f"{r}_{side}") for r in self.LIMBS[kind]])

    def limb_point(self, limb, t):
        """Точка и направление оси конечности при параметре t: 0 — корень (плечо, бедро), 1 — запястье
        или щиколотка; средний сустав — при t = lm["elbow_t"] / lm["knee_t"]. t > 1 — продолжение в кисть.
        У сустава направление меняется плавно, чтобы кольца не пересекались на сгибе."""
        J = self.limb_axis(limb)
        l1, l2 = np.linalg.norm(J[1] - J[0]), np.linalg.norm(J[2] - J[1])
        tm = l1 / (l1 + l2)
        d1, d2 = (J[1] - J[0]) / l1, (J[2] - J[1]) / l2
        s = t * (l1 + l2)
        p = J[0] + d1 * s if t <= tm else J[1] + d2 * (s - l1)
        w = float(np.clip((t - tm) / 0.16 + 0.5, 0.0, 1.0))
        w = w * w * (3 - 2 * w)
        d = d1 * (1 - w) + d2 * w
        return p, d / np.linalg.norm(d)

    def limb_ref(self, limb):
        """Направление начала кольца конечности: у руки — вниз (шов под мышкой), у ноги — внутрь (шаговый шов)."""
        kind, side = limb.split("_")
        return np.array([0.0, 0.0, -1.0]) if kind == "arm" else np.array([0.0, 1.0 if side == "L" else -1.0, 0.0])

    def limb_frame(self, limb, t):
        """Оси кольца конечности при параметре t: (ex — начало отсчёта угла, ey). Вместе с направлением
        оси d образуют правую тройку: угол растёт против часовой стрелки, если смотреть навстречу оси."""
        _, d = self.limb_point(limb, t)
        ref = self.limb_ref(limb)
        if abs(ref @ d) > 0.95:                       # ось почти вдоль опорного направления (рука вниз)
            ref = np.array([0.0, 1.0 if limb.endswith("L") else -1.0, 0.0])
        ex = ref - d * (ref @ d)
        ex /= np.linalg.norm(ex)
        return ex, np.cross(d, ex)

    def limb_ring(self, limb, t, n=24, offset=0.0, tent=0.0, smooth=1.0, thetas=None):
        """Кольцо конечности поперёк оси при параметре t (см. limb_point). thetas — свои углы точек
        (по умолчанию равномерно, n точек)."""
        p, d = self.limb_point(limb, t)
        ex, ey = self.limb_frame(limb, t)
        kind = limb.split("_")[0]
        rmax = (240.0 if kind == "arm" else 330.0) * self.lm["height"] / 1700.0
        regions = ("torso", limb) if kind == "leg" else None      # вторая нога не попадает в кольцо
        th = np.arange(n) * 2 * math.pi / n if thetas is None else np.asarray(thetas, float)
        _, r = self.ring(p, d, ex, len(th), regions, "near", tent, 0.0, 0.0, thetas=th, rmax=rmax)
        med = np.median(r)
        r = np.minimum(r, med * 1.7)                  # у корня конечности луч уходит в туловище — обрезать
        r = _smooth_circular(r, smooth) + offset
        return p + r[:, None] * (np.cos(th)[:, None] * ex + np.sin(th)[:, None] * ey)

    def limb_grid(self, limb, ts, nu=24, offset=0.0, tent=0.0, smooth=1.0):
        """Сетка (nu, nv, 3) вокруг руки или ноги: кольца при параметрах ts (от корня к концу) плюс отступ.
        offset — число, массив (nv,) или функция t -> число."""
        val = lambda p, j, t: (p(t) if callable(p) else (p[j] if np.ndim(p) else p))
        return np.stack([self.limb_ring(limb, t, nu, val(offset, j, t), val(tent, j, t), smooth)
                         for j, t in enumerate(ts)], axis=1)

    # ------------------------------------------------------------ ориентиры и мерки
    def _ray_up(self, x, y, z0):
        """Первая поверхность тела над точкой (x, y, z0): высота z или None."""
        o = np.array([x, y, z0], float)
        A, B, C = (self.V[self.T[:, i]] for i in range(3))
        e1, e2 = B - A, C - A
        d = np.array([0.0, 0.0, 1.0])
        h = np.cross(d, e2)
        a = (e1 * h).sum(1)
        a = np.where(np.abs(a) < 1e-12, 1e-12, a)
        s = o - A
        u = (s * h).sum(1) / a
        q = np.cross(s, e1)
        v = (q @ d) / a
        t = (e2 * q).sum(1) / a
        ok = (u >= 0) & (v >= 0) & (u + v <= 1) & (t > 1e-6)
        return float(z0 + t[ok].min()) if ok.any() else None

    def _hull_stats(self, z, regions):
        S = plane_segments(self.V, self.T[self.tri_mask(regions)], (0, 0, z), (0, 0, 1))
        if len(S) < 3:
            return None
        from scipy.spatial import ConvexHull
        pts = S.reshape(-1, 3)[:, :2]
        h = ConvexHull(pts)
        hv = pts[h.vertices]
        per = float(np.linalg.norm(hv - np.roll(hv, -1, axis=0), axis=1).sum())
        return dict(perimeter=per, xmin=float(pts[:, 0].min()), xmax=float(pts[:, 0].max()),
                    width=float(pts[:, 1].max() - pts[:, 1].min()))

    def _landmarks(self):
        lm = self.lm
        lm["height"] = float(self.V[:, 2].max())
        for side in "LR":
            lm[f"shoulder_{side}"] = self.joint(f"upper_arm_{side}")
            lm[f"elbow_{side}"] = self.joint(f"forearm_{side}")
            lm[f"wrist_{side}"] = self.joint(f"hand_{side}")
            lm[f"hip_{side}"] = self.joint(f"thigh_{side}")
            lm[f"knee_{side}"] = self.joint(f"shin_{side}")
            lm[f"ankle_{side}"] = self.joint(f"foot_{side}")
        lm["neck_base"] = float(self.joint("neck")[2])
        lm["head_base"] = float(self.joint("head")[2])
        hip_z = float(lm["hip_L"][2])
        sh_z = float(lm["shoulder_L"][2])
        xh = float(lm["hip_L"][0])
        hits = [self._ray_up(xh + dx, 0.0, lm["knee_L"][2]) for dx in (-50, -25, 0, 25, 50)]
        lm["crotch"] = min(h for h in hits if h is not None)
        # подмышка: вершина складки между боком и рукой во фронтальном сечении через плечевой сустав
        for side, sg in (("L", -1.0), ("R", 1.0)):
            best = None
            xs, ys = lm[f"shoulder_{side}"][0], abs(lm[f"shoulder_{side}"][1])
            for dx in (-30, -15, 0, 15, 30):
                S = plane_segments(self.V, self.T, (xs + dx, 0, 0), (1, 0, 0)).reshape(-1, 3)
                if not len(S):
                    continue
                yy = S[:, 1] * sg
                m = (yy > ys - 110) & (yy < ys - 5) & (S[:, 2] < sh_z - 20) & (S[:, 2] > sh_z - 220)
                if m.any():
                    score = S[m, 2] - yy[m]
                    j = score.argmax()
                    if best is None or score[j] > best[0]:
                        best = (score[j], S[m][j])
            lm[f"armpit_{side}"] = best[1] if best else np.array([xs, -sg * (ys - 40), sh_z - 80])
        lm["armpit"] = float(min(lm["armpit_L"][2], lm["armpit_R"][2]))
        # вершина плеча: поверхность над плечевым суставом
        for side in "LR":
            s = lm[f"shoulder_{side}"]
            top = self._ray_up(s[0], s[1], s[2])
            lm[f"shoulder_top_{side}"] = np.array([s[0], s[1], top if top else s[2] + 40])
        # талия, бёдра, грудь: по сечениям туловища с шагом 5 мм
        rt = ("torso", "head", "leg_L", "leg_R")
        zs = np.arange(lm["crotch"] + 5, lm["armpit"] - 5, 5.0)
        st = [self._hull_stats(z, rt) for z in zs]
        ok = [i for i, s in enumerate(st) if s]
        zs, st = zs[ok], [st[i] for i in ok]
        per = np.array([s["perimeter"] for s in st])
        xmin = np.array([s["xmin"] for s in st])
        self._axis_table = (zs, np.convolve(np.pad(np.array([(s["xmin"] + s["xmax"]) / 2 for s in st]), 4, mode="edge"),
                                            np.ones(9) / 9, mode="valid"))
        mid = (zs > hip_z + 60) & (zs < lm["armpit"] - 90)
        lm["waist"] = float(zs[mid][per[mid].argmin()])
        low = zs < lm["waist"]
        lm["hips"] = float(zs[low][per[low].argmax()]) if low.any() else hip_z
        up = zs > lm["waist"] + 40
        lm["bust"] = float(zs[up][xmin[up].argmin()]) if up.any() else lm["waist"] + 150
        ub = (zs > lm["waist"] + 0.45 * (lm["bust"] - lm["waist"])) & (zs < lm["bust"] - 15)
        lm["underbust"] = float(zs[ub][per[ub].argmin()]) if ub.any() else (lm["waist"] + lm["bust"]) / 2
        lm["knee"] = float(lm["knee_L"][2])
        lm["ankle"] = float(lm["ankle_L"][2])
        for limb, key in (("arm_L", "elbow_t"), ("leg_L", "knee_t")):
            J = self.limb_axis(limb)
            l1, l2 = np.linalg.norm(J[1] - J[0]), np.linalg.norm(J[2] - J[1])
            lm[key] = float(l1 / (l1 + l2))

    def _loop_len(self, P):
        from scipy.spatial import ConvexHull
        return float(np.linalg.norm(P - np.roll(P, -1, axis=0), axis=1).sum())

    def _measures(self):
        """Таблица мерок, мм. Обхваты — длина кольца тела (сантиметровой лентой — по выпуклой оболочке)."""
        lm, m = self.lm, {}
        m["height"] = lm["height"]
        for k in ("bust", "underbust", "waist", "hips"):
            m[k] = self._loop_len(self.torso_ring(lm[k], 96, tent=1.0, smooth=0))
            m[k + "_z"] = lm[k]
        nz = (lm["neck_base"] + lm["head_base"]) / 2
        m["neck"] = self._loop_len(self.ring((self.joint("neck")[0], 0, nz), (0, 0, 1), (1, 0, 0), 48,
                                             ("torso", "head"), "far", 1.0)[0])
        m["shoulder_width"] = float(abs(lm["shoulder_L"][1] - lm["shoulder_R"][1]))
        J = self.limb_axis("arm_L")
        m["arm_length"] = float(np.linalg.norm(J[1] - J[0]) + np.linalg.norm(J[2] - J[1]))
        m["upper_arm"] = self._loop_len(self.limb_ring("arm_L", lm["elbow_t"] * 0.5, 32))
        m["wrist"] = self._loop_len(self.limb_ring("arm_L", 0.97, 32))
        J = self.limb_axis("leg_L")
        m["leg_length"] = float(np.linalg.norm(J[1] - J[0]) + np.linalg.norm(J[2] - J[1]))
        m["thigh"] = self._loop_len(self.limb_ring("leg_L", lm["knee_t"] * 0.35, 32))
        m["knee"] = self._loop_len(self.limb_ring("leg_L", lm["knee_t"], 32))
        m["calf"] = max(self._loop_len(self.limb_ring("leg_L", t, 32)) for t in
                        np.linspace(lm["knee_t"] + 0.08, lm["knee_t"] + 0.3, 6))
        m["ankle"] = self._loop_len(self.limb_ring("leg_L", 0.96, 32))
        m["inseam"] = lm["crotch"]
        m["back_length"] = lm["neck_base"] - lm["waist"]
        m["armpit_z"], m["neck_base_z"], m["knee_z"] = lm["armpit"], lm["neck_base"], lm["knee"]
        return {k: round(float(v), 1) for k, v in m.items()}

    def measures_table(self):
        """[(название, значение мм)] для листа и для команды body."""
        names = [("height", "Рост"), ("bust", "Обхват груди"), ("underbust", "Обхват под грудью"),
                 ("waist", "Обхват талии"), ("hips", "Обхват бёдер"), ("neck", "Обхват шеи"),
                 ("shoulder_width", "Ширина плеч (по суставам)"), ("back_length", "Длина спины до талии"),
                 ("arm_length", "Длина руки (плечо–запястье)"), ("upper_arm", "Обхват плеча"),
                 ("wrist", "Обхват запястья"), ("inseam", "Высота шага (пах от пола)"),
                 ("thigh", "Обхват бедра"), ("knee", "Обхват колена"), ("calf", "Обхват икры"),
                 ("ankle", "Обхват щиколотки"), ("bust_z", "Высота линии груди"), ("waist_z", "Высота талии"),
                 ("hips_z", "Высота линии бёдер"), ("armpit_z", "Высота подмышки"),
                 ("neck_base_z", "Высота основания шеи"), ("knee_z", "Высота колена")]
        return [(n, self.measures[k]) for k, n in names if k in self.measures]

    def nearest_landmark(self, p):
        """Название ближайшего ориентира к точке — для отчёта posetest («где проткнуло»)."""
        lm = self.lm
        names = {"bust": "грудь", "underbust": "под грудью", "waist": "талия", "hips": "бёдра", "crotch": "пах",
                 "knee": "колено", "ankle": "щиколотка", "neck_base": "основание шеи", "armpit": "подмышка"}
        best = None
        for k, z in ((k, lm[k]) for k in names):
            d = abs(p[2] - z) + (0 if k not in ("armpit",) else 30)
            if best is None or d < best[0]:
                best = (d, names[k])
        for side, sn in (("L", "лев."), ("R", "прав.")):
            for k, n in (("shoulder", "плечо"), ("elbow", "локоть"), ("wrist", "запястье"), ("knee", "колено"),
                         ("hip", "тазобедренный"), ("ankle", "щиколотка"), ("armpit", "подмышка")):
                d = float(np.linalg.norm(np.asarray(p) - lm[f"{k}_{side}"]))
                if d < best[0]:
                    best = (d, f"{n} {sn}")
        return best[1]

    # ------------------------------------------------------------ позы
    def pose(self, spec):
        """Матрицы костей для позы {роль или имя кости: [(ось, градусы), ...]}. Ключ без стороны
        («upper_arm») ставит обе стороны зеркально; «_root»: (dx, dy, dz) — сдвиг корня, мм."""
        return self.pose_on(self.skel, spec)

    _NEXT = {"upper_arm": "forearm", "forearm": "hand", "thigh": "shin", "shin": "foot", "foot": "toe"}
    _OPTIONAL = ("upper_chest", "chest", "clavicle", "toe")

    def rest_dir(self, role):
        """Направление кости роли в позе покоя: к следующему суставу (плечо → локоть), иначе вдоль кости."""
        base, side = (role[:-2], role[-2:]) if role[-2:] in ("_L", "_R") else (role, "")
        nxt = self._NEXT.get(base)
        b = self.roles[role]
        d = (self.joint(nxt + side) - self.skel.head[b]) if nxt and (nxt + side) in self.roles else (self.skel.tail[b] - self.skel.head[b])
        return d / np.linalg.norm(d)

    def _pose_rot(self, role, val, mirror):
        if isinstance(val, tuple) and val and val[0] in ("to", "bend"):
            m = np.array([1.0, -1.0, 1.0]) if mirror else np.ones(3)
            d = self.rest_dir(role)
            if val[0] == "to":
                t = np.asarray(val[1], float) * m
                t = t / np.linalg.norm(t)
                ax = np.cross(d, t)
                sn = np.linalg.norm(ax)
                return np.eye(3) if sn < 1e-9 else _rot(ax / sn, math.degrees(math.atan2(sn, float(d @ t))))
            ax = np.cross(d, np.asarray(val[2], float) * m)
            return _rot(ax / np.linalg.norm(ax), float(val[1]))
        return rotation(val, mirror)

    def pose_on(self, skel, spec):
        """Поза на скелете skel (тело или тело с костями динамики). Формы поворота — см. posetest.POSES:
        ("to", вектор), ("bend", градусы, вектор), [(ось, градусы), ...]. Вектор задаётся для левой стороны;
        ключ без стороны ставит обе стороны зеркально, ключ с _R берёт вектор как есть."""
        rot, shift = {}, (0, 0, 0)
        idx = lambda role: skel.index[self.skel.names[self.roles[role]]]
        for key, val in spec.items():
            if key == "_root":
                shift = val
            elif key in self.roles:
                rot[idx(key)] = self._pose_rot(key, val, False)
            elif key + "_L" in self.roles:
                rot[idx(key + "_L")] = self._pose_rot(key + "_L", val, False)
                rot[idx(key + "_R")] = self._pose_rot(key + "_R", val, True)
            elif key in skel.index:
                rot[skel.index[key]] = rotation(val)
            elif key.replace("_L", "").replace("_R", "") in self._OPTIONAL:
                continue                                 # у этого скелета такой кости нет — поза без неё
            else:
                raise KeyError(f"поза: нет кости или роли {key!r}")
        return skel.matrices(rot, shift)

    def posed(self, M):
        """Вершины тела в позе (матрицы от pose())."""
        return skin_points(self.V, self.W, M[: self.W.shape[1]])

    def shape(self):
        """Тело как обстановка для чертежа (group="phantom"): контур на видах и кольца в разрезах."""
        from .mesh import MeshShape
        return MeshShape(self.V, self.T)


def file_hash(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


_loaded = {}


def load(path, roles=None, landmarks=None):
    """Загрузить тело с ригом (.blend / .glb / .fbx). roles — {роль: имя кости} для нестандартных имён;
    landmarks — переопределение ориентиров ({"waist": 1050.0, ...}). Хеш файла тела и этих таблиц входит
    в хеш апрува спецификации: тело изменилось — апрув устарел."""
    from .build import find_blender
    path = os.path.abspath(path)
    if not os.path.exists(path):
        raise FileNotFoundError(f"нет файла тела {path}")
    fh = file_hash(path)
    extra = json.dumps([roles, {k: (v.tolist() if hasattr(v, "tolist") else v) for k, v in (landmarks or {}).items()}],
                       sort_keys=True, ensure_ascii=False)
    sh = hashlib.sha256((fh + extra).encode("utf-8")).hexdigest()
    if sh in _loaded:
        return _loaded[sh]
    os.makedirs(CACHE, exist_ok=True)
    npz = os.path.join(CACHE, f"body_{fh[:16]}.npz")
    if not os.path.exists(npz):
        r = subprocess.run([find_blender(), "-b", "--factory-startup", "--python", os.path.join(HERE, "bl_body.py"),
                            "--", path, npz], capture_output=True, text=True, encoding="utf-8", errors="replace")
        if "BP3D_DONE" not in r.stdout or not os.path.exists(npz):
            raise RuntimeError("не удалось выгрузить тело:\n" + (r.stdout + r.stderr)[-1500:])
    b = Body(np.load(npz, allow_pickle=False), path, sh, roles, landmarks)
    _loaded[sh] = b
    return b
