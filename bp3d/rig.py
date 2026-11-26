"""Привязка одежды к скелету: веса, кости динамики, коллайдеры, скрытие тела под одеждой.

Всё считается на стороне Python (numpy), а Blender только собирает готовое: одни и те же веса идут
и в модель, и в posetest. Поэтому то, что проверено posetest, — это то, что уйдёт в FBX.

  bind="auto"                     веса переносятся с ближайшей поверхности тела (с интерполяцией внутри
                                  треугольника), сглаживаются по сетке вещи, остаются 4 влияния на вершину
  bind="hips" (роль или имя)      жёсткая деталь на одной кости
  dynamics="stiff" | "soft" | dict  цепочки костей с пружиной по сетке детали (вдоль v) — см. chains()
  hides=True | dict(reach, margin)  тело под деталью скрывается: вершина тела ближе reach мм к изнанке вещи
                                  и дальше margin мм от её кромок
"""
import math
import numpy as np

from .garment import DYNAMICS, smoothstep
from .mesh import RIM
from .body import REGIONS

MAX_INFLUENCES = 4
# Стратегии привязки (поле bind): "auto"/"tight" — облегающая, веса с ближайшей точки тела; "proxy"/"loose" —
# свободная, веса с раздутого и сглаженного прокси-тела (Body.proxy); имя кости или роль — жёсткая деталь.
BIND_ALIASES = {"tight": "auto", "loose": "proxy"}
PROXY_FROM = (10.0, 22.0)  # зазор ткани до тела, мм: ближе первого — веса с кожи, дальше второго — с прокси
WEIGHT_MIN_LOOSE = 0.03    # свободная вещь: влияния меньше этого отбрасываются мягко (до выбора MAX_INFLUENCES)
SMOOTH_MM_TIGHT = 20.0    # сглаживание весов по поверхности вещи, мм: облегающая (bind="auto")
SMOOTH_MM_LOOSE = 45.0    # свободная (bind="proxy"); своё значение — bind=dict(mode=..., smooth_mm=...)


def _dyn_list(part):
    d = part.dynamics
    if not d or d == "rigid":
        return []
    out = []
    for x in (d if isinstance(d, (list, tuple)) else [d]):
        x = dict(preset=x) if isinstance(x, str) else dict(x)
        preset = x.get("preset", "stiff")
        if DYNAMICS.get(preset) is None:
            continue
        p = dict(DYNAMICS[preset])
        p.update(x)
        p["preset"] = preset
        out.append(p)
    return out


def _depth(skel, b):
    d = 0
    while skel.parent[b] >= 0:
        b, d = skel.parent[b], d + 1
    return d


def _grid_point(G, closed_u, u, v):
    """Точка сетки при параметрах u, v ∈ [0, 1] (линейно между точками)."""
    nu, nv = G.shape[:2]
    fu = (u * nu) % nu if closed_u else u * (nu - 1)
    fv = v * (nv - 1)
    i0, j0 = int(math.floor(fu)), int(min(math.floor(fv), nv - 2))
    i1 = (i0 + 1) % nu if closed_u else min(i0 + 1, nu - 1)
    a, b = fu - i0, fv - j0
    return ((1 - a) * (1 - b) * G[i0, j0] + a * (1 - b) * G[i1, j0] + (1 - a) * b * G[i0, j0 + 1] + a * b * G[i1, j0 + 1])


def chains(part, body):
    """Цепочки костей динамики детали. Каждая зона dynamics: patch — имя лоскута (или его начало; по
    умолчанию все лоскуты детали), chains — число цепочек вокруг (для ленты 1), bones — костей в цепочке,
    v0…v1 — участок сетки вдоль v, где работает динамика (0 — верх, 1 — низ), blend — ширина плавного
    перехода от весов тела к цепочке (в долях v), parent — кость тела для корня цепочки (роль или имя;
    по умолчанию — та, чей вес у корня наибольший), colliders — имена коллайдеров или "auto".
    Вместо сетки цепочку можно задать явно: path=[(x, y, z), ...]."""
    q = part.quad
    out = []
    for zi, d in enumerate(_dyn_list(part)):
        pats = [k for k, P in enumerate(q.patches) if not d.get("patch") or P.name.startswith(d["patch"])]
        if not pats:
            raise ValueError(f"{part.key}: динамика — нет лоскута {d.get('patch')!r}; есть: "
                             + ", ".join(P.name for P in q.patches))
        K = int(d.get("bones", 3))
        v0, v1 = float(d.get("v0", 0.25)), float(d.get("v1", 1.0))
        for k in pats:
            P = q.patches[k]
            C = int(d.get("chains", 8 if P.closed_u else 1))
            for c in range(C):
                if d.get("path") is not None:
                    from .mesh import resample_open
                    J = resample_open(np.asarray(d["path"], float), K + 1)
                else:
                    u = c / C if P.closed_u else (0.5 if C == 1 else c / (C - 1))
                    J = np.array([_grid_point(P.G, P.closed_u, u, v0 + (v1 - v0) * i / K) for i in range(K + 1)])
                root_w = body.weights_at(J[:1], regions=d.get("regions"))[0]
                if d.get("parent"):
                    parent = body.bone(d["parent"])
                else:
                    # корень цепочки — на кости, которая ближе к корню скелета среди заметно влияющих:
                    # подол у талии садится на таз, а не на позвоночник (иначе юбка уезжает при наклоне)
                    cand = np.nonzero(root_w >= 0.2)[0]
                    cand = cand if len(cand) else np.array([int(root_w.argmax())])
                    parent = int(min(cand, key=lambda b: _depth(body.skel, int(b))))
                # follow: цепочка частично поворачивается вместе с бедром вокруг тазобедренного сустава
                # (подол поднимается с коленом, а не ждёт, пока его вытолкнет коллайдер). Вес убывает
                # с расстоянием от цепочки до оси бедра.
                fol = []
                if d.get("follow"):
                    for sd in "LR":
                        hj = body.joint(f"thigh_{sd}")
                        dist = float(np.linalg.norm((J[min(1, K)] - hj)[:2]))
                        w = float(d["follow"]) * math.exp(-(dist / 170.0) ** 2)
                        if w > 0.03:
                            fol.append(dict(bone=body.bone(f"thigh_{sd}"), weight=round(w, 3), pivot=hj))
                hr = body.closest(J[:1])
                od = J[0] - hr["point"][0]
                od = od / np.linalg.norm(od) if np.linalg.norm(od) > 1e-6 else hr["normal"][0]
                out.append(dict(part=part.key, zone=zi, patch=k, index=c, count=C, joints=J, parent=parent, out=od,
                                follow=fol,
                                names=[f"{part.key}_d{zi}p{k}c{c:02d}_{i}" for i in range(K)],
                                v0=v0, v1=v1, blend=float(d.get("blend", 0.12)), closed=bool(P.closed_u),
                                params={x: d[x] for x in ("preset", "stiffness", "damping", "gravity", "radius")},
                                colliders=d.get("colliders", "auto")))
    return out


def _smooth_weights(W, F, it=2):
    """Сглаживание весов по рёбрам меша (среднее с соседями)."""
    n = len(W)
    E = []
    for a, b in ((0, 1), (1, 2), (2, 3), (3, 0)):
        ok = (F[:, a] >= 0) & (F[:, b] >= 0)
        E.append(np.stack([F[ok, a], F[ok, b]], 1))
    tri = F[:, 3] < 0
    E.append(np.stack([F[tri, 2], F[tri, 0]], 1))
    E = np.vstack(E)
    E = E[E[:, 0] != E[:, 1]]
    from scipy.sparse import coo_matrix
    A = coo_matrix((np.ones(len(E) * 2), (np.concatenate([E[:, 0], E[:, 1]]), np.concatenate([E[:, 1], E[:, 0]]))),
                   shape=(n, n)).tocsr()
    A.data[:] = 1.0
    deg = np.maximum(np.asarray(A.sum(axis=1)).ravel(), 1.0)
    for _ in range(it):
        W = 0.5 * W + 0.5 * (A @ W) / deg[:, None]
    return W


def _smooth_weights_mm(W, V, F, radius):
    """Сглаживание весов по поверхности вещи на радиус radius (мм): неявная диффузия (I + t·L) W' = W
    с лапласианом по рёбрам, вес ребра 1/длина². В отличие от сглаживания «по соседям» охватывает одно и то же
    расстояние и на мелкой сетке у сустава, и на крупной: перепад весов у подмышки и паха растягивается на
    несколько сантиметров ткани, а не на одно короткое ребро."""
    from scipy.sparse import coo_matrix, identity
    from scipy.sparse.linalg import splu
    E = []
    for a, b in ((0, 1), (1, 2), (2, 3), (3, 0)):
        ok = (F[:, a] >= 0) & (F[:, b] >= 0)
        E.append(np.stack([F[ok, a], F[ok, b]], 1))
    tri = F[:, 3] < 0
    E.append(np.stack([F[tri, 2], F[tri, 0]], 1))
    E = np.unique(np.sort(np.vstack(E), axis=1), axis=0)
    E = E[E[:, 0] != E[:, 1]]
    n = len(V)
    l2 = np.maximum(np.sum((V[E[:, 0]] - V[E[:, 1]]) ** 2, axis=1), 1e-4)
    w = 1.0 / l2
    A = coo_matrix((np.concatenate([w, w]), (np.concatenate([E[:, 0], E[:, 1]]), np.concatenate([E[:, 1], E[:, 0]]))),
                   shape=(n, n)).tocsc()
    L = coo_matrix((np.asarray(A.sum(axis=1)).ravel(), (np.arange(n), np.arange(n))), shape=(n, n)).tocsc() - A
    lu = splu((identity(n, format="csc") + (radius ** 2 / 4.0) * L).tocsc())
    out = lu.solve(np.asarray(W, np.float64))
    return np.clip(out, 0.0, None).astype(np.float32)


def _limit(W, k=MAX_INFLUENCES, w_min=0.0):
    """Оставить k наибольших влияний на вершину и нормировать. Влияния меньше w_min (WEIGHT_MIN) отбрасываются:
    хвост сглаживания в 3–4 % от далёкой кости (бедро на животе) при её повороте на 90° сдвигает точку на
    сантиметр, а у соседней вершины четвёртым влиянием оказывается другая кость — ткань рвётся. Для свободных
    вещей (bind="proxy") по умолчанию WEIGHT_MIN_LOOSE, для облегающих — 0 (их веса и так как у кожи). Отсечение
    мягкое (из всех влияний, кроме главного, вычитается w_min): вес плавно уходит в ноль, без скачка."""
    if w_min > 0:                      # мягкое отсечение: w − w_min, без скачка на границе отсечения
        top = W.max(axis=1, keepdims=True)
        W = np.where(W >= top, W, np.maximum(W - w_min, 0.0))
    if W.shape[1] > k:
        idx = np.argpartition(-W, k - 1, axis=1)[:, :k]
        M = np.zeros_like(W)
        r = np.arange(len(W))[:, None]
        M[r, idx] = W[r, idx]
        W = M
    s = W.sum(axis=1, keepdims=True)
    s[s < 1e-9] = 1.0
    return W / s


def body_colliders(body):
    """Капсулы тела для костей с пружиной: бёдра, голени, плечи, предплечья, таз, туловище, голова.
    Каждая: имя, кость, концы оси a и b (мм, поза покоя), радиус."""
    lm, out = body.lm, []
    names = {"arm": ("upper_arm", "forearm"), "leg": ("thigh", "shin")}
    for kind in ("leg", "arm"):
        for side in "LR":
            limb = f"{kind}_{side}"
            J = body.limb_axis(limb)
            tm = lm["elbow_t"] if kind == "arm" else lm["knee_t"]
            for seg, (t0, t1) in enumerate(((0.0, tm), (tm, 1.0))):
                rs = []
                for t in (t0 + (t1 - t0) * 0.3, t0 + (t1 - t0) * 0.6, t0 + (t1 - t0) * 0.85):
                    p, _ = body.limb_point(limb, t)
                    rs.append(np.median(np.linalg.norm(body.limb_ring(limb, t, 16) - p, axis=1)))
                role = f"{names[kind][seg]}_{side}"
                out.append(dict(name=role, bone=body.bone(role), a=J[seg], b=J[seg + 1], r=float(np.max(rs))))

    def half_depth(z):
        r = body.torso_ring(z, 32, legs=False, smooth=0)
        return float((r[:, 0].max() - r[:, 0].min()) / 2), float((r[:, 0].max() + r[:, 0].min()) / 2)
    d, cx = half_depth(lm["hips"])
    out.append(dict(name="pelvis", bone=body.bone("hips"), a=np.array([cx, lm["hip_L"][1] * 0.75, lm["hips"]]),
                    b=np.array([cx, lm["hip_R"][1] * 0.75, lm["hips"]]), r=d * 0.95))
    dw, cw = half_depth(lm["waist"])
    db, cb = half_depth(lm["underbust"])
    out.append(dict(name="torso", bone=body.bone("spine"), a=np.array([cw, 0.0, lm["waist"]]),
                    b=np.array([cb, 0.0, lm["underbust"]]), r=(dw + db) / 2 * 0.95))
    hb = body.joint("head")
    top = lm["height"]
    out.append(dict(name="head", bone=body.bone("head"), a=np.array([hb[0], 0.0, (hb[2] + top) / 2]),
                    b=np.array([hb[0], 0.0, (hb[2] + top) / 2 + 1.0]), r=(top - hb[2]) * 0.42))
    return out


class Rig:
    """Скелет с костями динамики, веса всех деталей, коллайдеры и скрытые треугольники тела."""

    def __init__(self, model):
        body = model.body
        if body is None:
            raise ValueError("у модели нет тела: Model.body (Outfit(M, BODY) ставит его сам)")
        self.body = body
        self.parts = [p for p in model.parts if p.group not in ("phantom", "theory")]
        self.chains = [c for p in self.parts if p.mesh == "quad" for c in chains(p, body)]
        extra = []
        for c in self.chains:
            prev = body.skel.names[c["parent"]]
            for i, n in enumerate(c["names"]):
                extra.append((n, prev, c["joints"][i], c["joints"][i + 1]))
                prev = n
        self.skel = body.skel.extended(extra)
        for c in self.chains:
            c["bones"] = [self.skel.index[n] for n in c["names"]]
        self.colliders = body_colliders(body)
        self.W, self.rigid = {}, {}
        nb = len(self.skel.names)
        for p in self.parts:
            b = p.bind if p.bind is not None else "auto"
            mode = b.get("mode", "auto") if isinstance(b, dict) else b
            mode = BIND_ALIASES.get(mode, mode)
            if mode not in ("auto", "proxy"):
                self.rigid[p.key] = body.bone(mode)
                if p.mesh == "quad":
                    W = np.zeros((len(p.quad.V), nb), np.float32)
                    W[:, self.rigid[p.key]] = 1.0
                    self.W[p.key] = W
                continue
            if p.mesh != "quad":                       # CAD-деталь: одна кость — та, что сильнее у центра детали
                bb = p.shape.bounding_box()
                c = np.array([[(bb.min.X + bb.max.X) / 2, (bb.min.Y + bb.max.Y) / 2, (bb.min.Z + bb.max.Z) / 2]])
                self.rigid[p.key] = int(body.weights_at(c)[0].argmax())
                continue
            opt = dict(b) if isinstance(b, dict) else {}
            if mode == "proxy":                        # свободная вещь: веса с раздутого сглаженного тела
                opt.setdefault("proxy", dict(inflate=float(opt.pop("inflate", 25.0)), smooth=int(opt.pop("proxy_smooth", 12))))
                opt.setdefault("smooth", 4)
                opt.setdefault("smooth_mm", SMOOTH_MM_LOOSE)
                opt.setdefault("w_min", WEIGHT_MIN_LOOSE)
            opt.setdefault("smooth_mm", SMOOTH_MM_TIGHT)
            self.W[p.key] = self._auto(p, opt, nb)
        self.hidden = self._hidden()

    def _auto(self, p, opt, nb):
        body, q = self.body, p.quad
        V = q.V
        nb0 = body.W.shape[1]
        Wb = np.zeros((len(V), nb0), np.float32)
        # вершина слева не берёт веса с правой руки и ноги, и наоборот: иначе шаговый шов и подмышка
        # схватят чужую кость. Лоскут может сузить донорские области (подол платья — только туловище).
        side = np.where(V[:, 1] < -15.0, 0, np.where(V[:, 1] > 15.0, 1, 2))
        base = ([r for r in REGIONS if not r.endswith("_R")], [r for r in REGIONS if not r.endswith("_L")], list(REGIONS))
        names = np.array([q.patches[k].name for k in q.vpatch])
        want, pr = opt.get("regions"), p.info.get("regions", {})
        for i in range(3):
            for nm in set(names[side == i].tolist()):
                regs = [r for r in base[i] if (not want or r in want) and (nm not in pr or r in pr[nm])]
                m = (side == i) & (names == nm)
                rr = regs or list(pr.get(nm) or want or REGIONS)
                Wt = body.weights_at(V[m], regions=rr, roles=opt.get("roles"))
                if opt.get("proxy"):
                    # прокси — только там, где ткань висит свободно: у тела (резинка, пояс, облегающий верх)
                    # веса с кожи, дальше PROXY_FROM мм — с прокси, между — плавно
                    Wp = body.weights_at(V[m], regions=rr, roles=opt.get("roles"), proxy=opt["proxy"])
                    gap = body.closest(V[m])["dist"]
                    a0, a1 = opt.get("proxy_from", PROXY_FROM)
                    k = np.clip((gap - a0) / max(a1 - a0, 1e-6), 0.0, 1.0)[:, None]
                    k = k * k * (3 - 2 * k)
                    Wb[m] = Wt * (1 - k) + Wp * k
                else:
                    Wb[m] = Wt
        Wb = _smooth_weights(Wb, q.F, int(opt.get("smooth", 2)))
        if opt.get("smooth_mm", 0) > 0:                  # сглаживание по расстоянию (подмышка, пах)
            Wb = _smooth_weights_mm(Wb, q.V, q.F, float(opt["smooth_mm"]))
            Wb /= np.maximum(Wb.sum(axis=1, keepdims=True), 1e-9)
        W = np.zeros((len(V), nb), np.float32)
        W[:, :nb0] = Wb
        for c in [c for c in self.chains if c["part"] == p.key]:
            sel = np.nonzero(q.vpatch == c["patch"])[0]
            u, v = q.vuv[sel, 0], q.vuv[sel, 1]
            K = len(c["bones"])
            s = smoothstep((v - c["v0"]) / max(c["blend"], 1e-6)) * (v > c["v0"])
            if c["count"] > 1:                         # доля этой цепочки по окружности
                if c["closed"]:
                    du = np.abs(((u * c["count"] - c["index"]) + c["count"] / 2) % c["count"] - c["count"] / 2)
                else:
                    du = np.abs(u * (c["count"] - 1) - c["index"])
                share = np.clip(1.0 - du, 0.0, 1.0)
            else:
                share = np.ones(len(sel))
            pk = np.clip((v - c["v0"]) / max(c["v1"] - c["v0"], 1e-6), 0, 1) * K - 0.5
            a = np.clip(np.floor(pk), 0, K - 1).astype(int)
            f = np.clip(pk - a, 0.0, 1.0)
            f[pk < 0] = 0.0
            b2 = np.clip(a + 1, 0, K - 1)
            cols = np.array(c["bones"])
            amt = (s * share).astype(np.float32)
            np.add.at(W, (sel, cols[a]), amt * (1 - f))
            np.add.at(W, (sel, cols[b2]), amt * f)
        # доля тела уменьшается на долю динамики
        dyn = W[:, nb0:].sum(axis=1, keepdims=True)
        W[:, :nb0] *= np.clip(1.0 - dyn, 0.0, 1.0)
        return _limit(W, w_min=float(opt.get("w_min", 0.0)))

    def _hidden(self):
        """Скрытые треугольники тела: все три вершины закрыты вещью с hides."""
        from scipy.spatial import cKDTree
        body = self.body
        cov = np.zeros(len(body.V), bool)
        for p in self.parts:
            if not p.hides or p.mesh != "quad":
                continue
            opt = p.hides if isinstance(p.hides, dict) else {}
            # margin больше reach: вершина тела за кромкой вещи всегда остаётся видимой
            reach, margin = float(opt.get("reach", 14.0)), float(opt.get("margin", 18.0))
            q = p.quad
            inner = q.V[q.vside == 1] if (q.vside == 1).any() else q.V
            d, _ = cKDTree(inner).query(body.V, distance_upper_bound=reach)
            c = np.isfinite(d)
            rim = np.unique(q.F[q.face_tag == RIM].ravel())
            rim = rim[rim >= 0]
            if len(rim):
                dr, _ = cKDTree(q.V[rim]).query(body.V, distance_upper_bound=margin)
                c &= ~np.isfinite(dr)
            cov |= c
        return cov[body.T].all(axis=1)

    # ------------------------------------------------------------ экспорт
    def export(self, arrays):
        """Дописать в словарь массивов веса деталей (4 влияния на вершину) и вернуть описание рига для
        манифеста сборки."""
        for key, W in self.W.items():
            idx = np.argsort(-W, axis=1)[:, :MAX_INFLUENCES]
            r = np.arange(len(W))[:, None]
            arrays[key + "|WI"] = idx.astype(np.int32)
            arrays[key + "|WW"] = W[r, idx].astype(np.float32)
        nb0 = len(self.body.skel.names)
        sk = self.skel
        return dict(
            bones=[dict(name=sk.names[i], parent=sk.names[sk.parent[i]], head=sk.head[i].tolist(), tail=sk.tail[i].tolist())
                   for i in range(nb0, len(sk.names))],
            bone_names=list(sk.names), rigid={k: sk.names[b] for k, b in self.rigid.items()},
            hidden_polys=sorted(set(int(x) for x in self.body.tri_poly[self.hidden])),
            armature=self.body.armature, body_meshes=self.body.mesh_names, body_file=self.body.source)

    def dynamics_manifest(self, name):
        """Нейтральное описание динамики для движка: цепочки костей с параметрами пружины и коллайдеры.
        Координаты коллайдеров — в долях длины кости (0 — начало, 1 — конец), радиусы и длины — в метрах:
        от осей и единиц файла модели не зависят."""
        sk = self.skel

        def frac(p, b):
            h, t = sk.head[b], sk.tail[b]
            d = t - h
            return float((np.asarray(p) - h) @ d / max(d @ d, 1e-9))
        cols = []
        for c in self.colliders:
            b = c["bone"]
            ax = sk.tail[b] - sk.head[b]
            along = abs(float((c["b"] - c["a"]) @ ax)) / max(np.linalg.norm(c["b"] - c["a"]) * np.linalg.norm(ax), 1e-9) > 0.7
            cols.append(dict(name=c["name"], bone=sk.names[b], shape="capsule", radius_m=round(c["r"] / 1000, 4),
                             along_bone=bool(along), start=round(frac(c["a"], b), 3), end=round(frac(c["b"], b), 3),
                             a_rest_mm=[round(float(x), 1) for x in c["a"]], b_rest_mm=[round(float(x), 1) for x in c["b"]]))
        ch = []
        for c in self.chains:
            pr = c["params"]
            use = [x["name"] for x in self.colliders] if c["colliders"] == "auto" else list(c["colliders"])
            ch.append(dict(part=c["part"], bones=c["names"], parent=sk.names[c["parent"]], preset=pr["preset"],
                           stiffness=pr["stiffness"], damping=pr["damping"], gravity=pr["gravity"],
                           hit_radius_m=round(pr["radius"] / 1000, 4),
                           ring=dict(index=c["index"], count=c["count"], closed=bool(c["closed"])),
                           follow=[dict(bone=sk.names[f["bone"]], weight=f["weight"]) for f in c["follow"]],
                           bone_length_m=[round(float(np.linalg.norm(c["joints"][i + 1] - c["joints"][i])) / 1000, 4)
                                          for i in range(len(c["names"]))], colliders=use))
        return dict(model=name, format="bp3d-dynamics-1", units="meters",
                    note="stiffness: тяга к позе покоя 0…1; damping: затухание 0…1; gravity: доля силы тяжести 0…1 "
                         "(вниз в мировых осях); hit_radius: радиус столкновения сустава цепочки с коллайдерами; "
                         "follow: корень цепочки дополнительно поворачивается вокруг начала указанной кости на долю "
                         "weight её поворота относительно родителя цепочки (подол идёт за бедром).",
                    chains=ch, colliders=cols)
