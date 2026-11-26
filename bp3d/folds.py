"""Складки и мелкий рельеф: поле смещения по нормали поверхности от набора кривых на ней. Общий модуль —
работает с любым квадовым мешем (одежда, мягкие предметы), тело ему не нужно.

Складка (Fold) — кривая на поверхности плюс профиль сечения:
  "ridge"  скруглённый гребень        "valley" скруглённая впадина      "pipe"   широкий гребень («труба»)
  "crease" острый залом (гребень)    "groove" острая канавка (шов)      "step"   ступень (залом сложенной ткани)
  "stitch" строчка: пунктир канавок с шагом pitch
Амплитуда amp (мм, плюс — наружу; число, (в начале, в конце) или по точкам кривой), ширина width (мм —
полуширина профиля), затухание к концам taper (доля длины), асимметрия asym (−1…1: ширина с одной
стороны кривой больше), смещение offset (мм поперёк кривой: параллельные строчки от одного шва).

Куда идёт складка — mode, можно несколько:
  "geo"     в геометрию игровой модели (сетка у складки сгущается сама: refine_for_folds)
  "normal"  в карту нормалей (запекается по развёртке: bake_maps) — мелкие складки, швы, строчка
  "mask"    в маску складок для художника (та же развёртка, яркость — сила складки)
Крупные складки — "geo", мелкие — "normal"; одну складку можно отдать в несколько мест сразу.

Складка не меняется при анимации: это часть формы вещи, вещь только гнётся по костям.
"""
import math
import numpy as np

from .mesh import Patch, QuadMesh, OUTER, refine_patch, resample_open, resample_closed

MODES = ("geo", "normal", "mask")
PROFILES = ("ridge", "valley", "pipe", "crease", "groove", "step", "stitch")
REFINE_PER_WIDTH = 2.5        # шаг сетки у складки — не больше width / REFINE_PER_WIDTH
REFINE_MAX = 4                # не больше стольких новых рядов между двумя старыми
REFINE_ASPECT = 5.0           # сгущение не делает квад уже 1:REFINE_ASPECT (если другую ось сгустить нельзя)


def smoothstep(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3 - 2 * x)


def profile(kind, x):
    """Профиль сечения складки; x — расстояние от кривой в долях ширины (со знаком)."""
    ax = np.abs(x)
    if kind in ("ridge", "pipe"):
        return np.where(ax < 1, (1 - x * x) ** 2, 0.0)
    if kind == "valley":
        return -np.where(ax < 1, (1 - x * x) ** 2, 0.0)
    if kind == "crease":
        return np.where(ax < 1, (1 - ax) ** 1.6, 0.0)
    if kind in ("groove", "stitch"):
        return -np.where(ax < 1, (1 - ax) ** 1.6, 0.0)
    if kind == "step":                  # подъём на ширине 2·width, затем плавный спуск ещё на 2·width
        return np.where(x < 1, smoothstep((x + 1) / 2), 1 - smoothstep((x - 1) / 2))
    raise ValueError(f"профиль складки {kind!r}: {', '.join(PROFILES)}")


def reach(kind):
    """Насколько далеко от кривой действует профиль, в долях ширины."""
    return 3.0 if kind == "step" else 1.0


class Fold:
    """Складка: path — точки кривой (n, 3), мм, на поверхности вещи или рядом (кривая прижимается к ней
    при сборке); либо uv=[(u, v), ...] ∈ [0, 1] на лоскуте patch (по имени). Остальное — см. модуль."""

    def __init__(self, path=None, *, amp=4.0, width=20.0, profile="ridge", taper=0.25, asym=0.0, offset=0.0,
                 mode="geo", closed=False, pitch=4.0, uv=None, patch=None, snap=True, name=""):
        if profile not in PROFILES:
            raise ValueError(f"профиль складки {profile!r}: {', '.join(PROFILES)}")
        self.path = None if path is None else np.asarray(path, float)
        self.uv, self.patch = uv, patch
        if self.path is None and uv is None:
            raise ValueError("складка: нужен path (точки) или uv с patch")
        self.amp, self.width, self.profile = amp, float(width), profile
        self.taper, self.asym, self.offset = float(taper), float(asym), float(offset)
        self.mode = (mode,) if isinstance(mode, str) else tuple(mode)
        bad = [m for m in self.mode if m not in MODES]
        if bad:
            raise ValueError(f"складка: режим {bad[0]!r}; есть {', '.join(MODES)}")
        self.closed, self.pitch, self.snap, self.name = bool(closed), float(pitch), snap, name
        self.P = None                   # кривая после прижатия: точки (m, 3), параметр s ∈ [0, 1], касательные

    def copy(self, **kw):
        import copy
        f = copy.copy(self)
        for k, v in kw.items():
            setattr(f, k, v)
        return f

    # ------------------------------------------------------------ кривая
    def _amp_at(self, s):
        a = self.amp
        if np.isscalar(a):
            return np.full_like(s, float(a))
        a = np.asarray(a, float)
        if a.shape == (2,):
            return a[0] + (a[1] - a[0]) * s
        return np.interp(s, np.linspace(0, 1, len(a)), a)

    def resolve(self, surface=None, patches=None):
        """Перевести кривую в 3D, сгустить и прижать к поверхности (Surface наружного слоя вещи)."""
        if self.path is not None:
            P = self.path
        else:
            pt = next((q for q in (patches or []) if q.name == self.patch), None)
            if pt is None:
                raise ValueError(f"складка {self.name!r}: нет лоскута {self.patch!r}")
            P = np.array([grid_point(pt, u, v) for u, v in self.uv])
        step = max(0.4, min(self.width / 6.0, 2.5, self.pitch / 4.0 if self.profile == "stitch" else 9.0))

        def dense(Q):
            L = np.linalg.norm(np.diff(np.vstack([Q, Q[:1]]) if self.closed else Q, axis=0), axis=1).sum()
            n = max(4, int(math.ceil(L / step)) + 1)
            return resample_closed(Q, n) if self.closed else resample_open(Q, n)
        P = dense(P)
        if surface is not None and self.snap:
            for _ in range(2):
                P = surface.closest(P)["point"]
                P = dense(P)
        seg = np.linalg.norm(np.diff(np.vstack([P, P[:1]]) if self.closed else P, axis=0), axis=1)
        cum = np.concatenate([[0.0], np.cumsum(seg)])[: len(P)]
        self.length = float(seg.sum())
        self.s = cum / max(self.length, 1e-9)
        T = (np.roll(P, -1, axis=0) - np.roll(P, 1, axis=0)) if self.closed else np.gradient(P, axis=0)
        self.T = T / np.maximum(np.linalg.norm(T, axis=1, keepdims=True), 1e-12)
        self.P = P
        self._tree = None
        return self

    def tree(self):
        if self._tree is None:
            from scipy.spatial import cKDTree
            self._tree = cKDTree(self.P)
        return self._tree

    # ------------------------------------------------------------ поле
    def field(self, X, N):
        """Смещение по нормали (мм) в точках X (n, 3) с нормалями N (n, 3)."""
        H = np.zeros(len(X))
        if self.P is None:
            self.resolve()
        R = self.width * reach(self.profile) + abs(self.offset)
        lo, hi = self.P.min(axis=0) - R, self.P.max(axis=0) + R
        box = np.nonzero(((X >= lo) & (X <= hi)).all(axis=1))[0]
        if not len(box):
            return H
        d, i = self.tree().query(X[box], distance_upper_bound=R)
        ok = np.isfinite(d)
        if not ok.any():
            return H
        box, d, i = box[ok], d[ok], i[ok]
        v = X[box] - self.P[i]
        side = np.einsum("ij,ij->i", v, np.cross(self.T[i], N[box]))
        x = d * np.where(side >= 0, 1.0, -1.0) - self.offset
        a = np.clip(self.asym, -0.9, 0.9)
        x = np.where(x > 0, x / (1 + a), x / (1 - a)) / self.width
        val = profile(self.profile, x)
        s = self.s[i]
        if self.profile == "stitch":    # пунктир: канавка на 60 % шага
            fr = (s * self.length / self.pitch) % 1.0
            val = val * np.where(fr < 0.6, np.sin(np.pi * np.minimum(fr / 0.6, 1.0)) ** 0.5, 0.0)
        tap = 1.0
        if not self.closed and self.taper > 0:
            tap = smoothstep(s / self.taper) * smoothstep((1 - s) / self.taper)
        H[box] = self._amp_at(s) * val * tap
        return H


def grid_point(P, u, v):
    """Точка сетки лоскута при u, v ∈ [0, 1] (билинейно, с учётом замкнутости)."""
    W = P.wrapped()
    fu = u * (W.shape[0] - 1)
    fv = v * (W.shape[1] - 1)
    return bilinear(W, np.array([fu]), np.array([fv]))[0]


def bilinear(W, fi, fj):
    """Значения сетки W (nu, nv, k) в дробных индексах fi, fj (массивы одинаковой длины)."""
    nu, nv = W.shape[:2]
    fi = np.clip(fi, 0, nu - 1)
    fj = np.clip(fj, 0, nv - 1)
    i0 = np.minimum(np.floor(fi).astype(int), nu - 2) if nu > 1 else np.zeros(len(fi), int)
    j0 = np.minimum(np.floor(fj).astype(int), nv - 2) if nv > 1 else np.zeros(len(fj), int)
    a = (fi - i0)[:, None]
    b = (fj - j0)[:, None]
    i1, j1 = np.minimum(i0 + 1, nu - 1), np.minimum(j0 + 1, nv - 1)
    return (W[i0, j0] * (1 - a) * (1 - b) + W[i1, j0] * a * (1 - b) + W[i0, j1] * (1 - a) * b + W[i1, j1] * a * b)


def total(folds, X, N, mode):
    """Сумма полей складок, отданных в режим mode."""
    H = np.zeros(len(X))
    for f in folds:
        if mode in f.mode:
            H += f.field(X, N)
    return H


# ================================================================== сборка: сгущение и смещение
def _shared(patches, tol=1e-3):
    """Для каждого лоскута — какие кромки сварены с другими: (кромки u=0/−1, кромки v=0/−1)."""
    from scipy.spatial import cKDTree
    out = []
    for k, P in enumerate(patches):
        others = [q.G.reshape(-1, 3) for j, q in enumerate(patches) if j != k]
        if not others:
            out.append((False, False))
            continue
        t = cKDTree(np.vstack(others))
        G = P.G
        hit = lambda pts: bool(np.any(t.query(pts, distance_upper_bound=tol)[0] < tol))
        ue = (not P.closed_u) and (hit(G[0]) or hit(G[-1]))
        ve = (not P.closed_v) and (hit(G[:, 0]) or hit(G[:, -1]))
        out.append((ue, ve))
    return out


def refine_for_folds(patches, folds, notes=None):
    """Сгустить сетки лоскутов у складок режима "geo": между рядами, где шаг больше width / REFINE_PER_WIDTH,
    добавляются ряды (до REFINE_MAX). Направление, кромки которого сварены с другим лоскутом, не сгущается —
    об этом пишется в notes (поднять cols / row_step у блока)."""
    geo = [f for f in folds if "geo" in f.mode]
    if not geo:
        return list(patches)
    shared = _shared(patches)
    out = []
    for P, (u_edges, v_edges) in zip(patches, shared):
        G = P.G
        nu, nv = G.shape[:2]

        def gaps(axis, closed):
            """Сколько рядов вставить в каждый промежуток вдоль оси: важен только шаг ПОПЕРЁК складки
            (кольцевой складке не нужны частые колонки вдоль неё самой)."""
            W = np.concatenate([G, np.take(G, [0], axis=axis)], axis=axis) if closed else G
            A = np.take(W, np.arange(W.shape[axis] - 1), axis=axis)
            Bq = np.take(W, np.arange(1, W.shape[axis]), axis=axis)
            D = (Bq - A).reshape(-1, 3)
            M = ((A + Bq) / 2).reshape(-1, 3)
            ratio = np.zeros(len(M))
            for f in geo:
                if f.P is None:
                    f.resolve()
                R = f.width * reach(f.profile) + abs(f.offset)
                d, i = f.tree().query(M, distance_upper_bound=R)
                ok = np.isfinite(d)
                if not ok.any():
                    continue
                T = f.T[i[ok]]
                Dk = D[ok]
                cross = np.linalg.norm(Dk - np.einsum("ij,ij->i", Dk, T)[:, None] * T, axis=1)
                ratio[ok] = np.maximum(ratio[ok], cross / (f.width / REFINE_PER_WIDTH))
            ratio = ratio.reshape(A.shape[:2])
            per = ratio.max(axis=0 if axis == 1 else 1)
            # не делать квад уже 1:REFINE_ASPECT: шаг по этой оси не меньше шага по другой / REFINE_ASPECT
            oth = 0 if axis == 1 else 1
            if G.shape[oth] > 1:
                So = np.linalg.norm(np.diff(G, axis=oth), axis=2)               # шаги по другой оси
                So = np.concatenate([So, So[-1:]] if oth == 0 else [So, So[:, -1:]], axis=oth)
                Sa = np.linalg.norm(Bq - A, axis=2)                             # шаги по этой оси
                Som = (np.take(So, np.arange(A.shape[axis]), axis=axis)
                       + np.take(So, np.arange(1, A.shape[axis] + 1) % G.shape[axis], axis=axis)) / 2
                cap = np.floor(Sa * REFINE_ASPECT / np.maximum(Som, 1e-6)) - 1
                cap = cap.min(axis=0 if axis == 1 else 1)
            else:
                cap = np.full(len(per), REFINE_MAX)
            extra = []
            for j, r in enumerate(per):
                k = int(min(REFINE_MAX, cap[j], max(0, math.ceil(float(r)) - 1)))
                extra += [j + q / (k + 1) for q in range(1, k + 1)]
            return extra
        v_at = gaps(1, P.closed_v)
        u_at = gaps(0, P.closed_u)
        if v_at and u_edges:
            if notes is not None:
                notes.append(f"{P.name}: ряды по v у складок не добавлены — кромка сварена с соседним лоскутом; "
                             "уменьшить row_step блока")
            v_at = []
        if u_at and v_edges:
            if notes is not None:
                notes.append(f"{P.name}: колонки по u у складок не добавлены — кромка сварена с соседним лоскутом; "
                             "поднять cols блока")
            u_at = []
        out.append(refine_patch(P, u_at, v_at) if (u_at or v_at) else P)
    return out


def apply_geo(mesh, folds):
    """Сместить вершины наружного слоя меша (до solidify) полем складок режима "geo" и обновить сетки
    лоскутов. Возвращает смещения вершин, мм."""
    geo = [f for f in folds if "geo" in f.mode]
    if not geo:
        return np.zeros(len(mesh.V))
    N = mesh.vertex_normals()
    H = total(geo, mesh.V, N, "geo")
    mesh.V = mesh.V + N * H[:, None]
    mesh.sync_patches()
    return H


def surface_of(patches):
    """Surface наружного слоя по сеткам лоскутов — к ней прижимаются кривые складок."""
    from .body import Surface
    m = QuadMesh.from_patches(patches)
    return Surface(m.V, m.triangles())


# ================================================================== запекание карт по развёртке
def bake_maps(parts, atlas, px):
    """Карта нормалей (касательное пространство, OpenGL: Y вверх) и маска складок по атласу модели.

    parts — {ключ детали: (QuadMesh, [Fold])}; atlas — описание атласа из build.export_quads (острова с
    местом в атласе и номером лоскута). Рельеф считается аналитически по полю складок режимов "normal" /
    "mask" в точках поверхности под каждым пикселем — это то же, что запекание с высокополигональной
    версии той же вещи, без самой версии. Возвращает (normal uint8 (px, px, 3), mask uint8 (px, px)) —
    строка 0 — низ (v = 0), как у атласа цвета."""
    S = atlas["size_mm"]
    pxmm = px / S
    nrm = np.zeros((px, px, 3), np.float32)
    nrm[:] = (0.0, 0.0, 1.0)
    msk = np.zeros((px, px), np.float32)
    amax = 1e-6
    for isl in atlas["islands"]:
        part = parts.get(isl["part"])
        if part is None or isl["tag"] != OUTER or isl.get("patch") is None:
            continue
        mesh, folds = part
        k = isl["patch"]
        if k >= len(mesh.patches) or mesh.patch_uv[k] is None:
            continue
        nf = [f for f in folds if "normal" in f.mode]
        mf = [f for f in folds if "mask" in f.mode]
        if not nf and not mf:
            continue
        P = mesh.patches[k]
        U, V = mesh.patch_uv[k]
        x0, y0 = int(round(isl["x"] * px)), int(round(isl["y"] * px))
        x1, y1 = int(round((isl["x"] + isl["w"]) * px)), int(round((isl["y"] + isl["h"]) * px))
        if x1 - x0 < 3 or y1 - y0 < 3:
            continue
        sc = isl["scale"]
        um = (np.arange(x0, x1) - x0 + 0.5) / pxmm / sc            # мм развёртки по пикселям
        vm = (np.arange(y0, y1) - y0 + 0.5) / pxmm / sc
        fi = np.interp(um, U, np.arange(len(U), dtype=float))
        fj = np.interp(vm, V, np.arange(len(V), dtype=float))
        FI, FJ = np.meshgrid(fi, fj, indexing="xy")                # (h, w)
        W = P.wrapped()
        Nw = P.normals()
        if P.closed_u:
            Nw = np.concatenate([Nw, Nw[:1]], axis=0)
        if P.closed_v:
            Nw = np.concatenate([Nw, Nw[:, :1]], axis=1)
        X = bilinear(W, FI.ravel(), FJ.ravel())
        N = bilinear(Nw, FI.ravel(), FJ.ravel())
        N /= np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-12)
        h, w = FI.shape
        if nf:
            H = total(nf, X, N, "normal").reshape(h, w)
            pmm = 1.0 / (pxmm * sc)                                 # мм поверхности на пиксель
            gx = np.gradient(H, pmm, axis=1)
            gy = np.gradient(H, pmm, axis=0)
            n = np.stack([-gx, -gy, np.ones_like(H)], axis=2)
            nrm[y0:y1, x0:x1] = n / np.linalg.norm(n, axis=2, keepdims=True)
        if mf:
            Hm = np.abs(total(mf, X, N, "mask")).reshape(h, w)
            msk[y0:y1, x0:x1] = np.maximum(msk[y0:y1, x0:x1], Hm)
            amax = max(amax, float(Hm.max()))
    n8 = np.clip(np.round((nrm * 0.5 + 0.5) * 255), 0, 255).astype(np.uint8)
    m8 = np.clip(np.round(msk / amax * 255), 0, 255).astype(np.uint8)
    return n8, m8


def write_png(path, img):
    """PNG без сторонних библиотек. img (h, w) или (h, w, 3|4) uint8; строка 0 — низ изображения."""
    import struct, zlib
    a = np.asarray(img, np.uint8)
    if a.ndim == 2:
        a = a[:, :, None]
    a = a[::-1]
    h, w, c = a.shape
    raw = b"".join(b"\x00" + a[y].tobytes() for y in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    ct = {1: 0, 3: 2, 4: 6}[c]
    with open(path, "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, ct, 0, 0, 0))
                 + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))
