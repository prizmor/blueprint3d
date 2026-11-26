"""posetest: одежда на теле в наборе поз — где и насколько она протыкается.

Тело и одежда ставятся в позу тем же линейным скиннингом и теми же весами, что уйдут в FBX (bp3d.rig),
кости с пружиной занимают положение равновесия (пружина к позе покоя + тяжесть + выталкивание из
коллайдеров). Затем считаются:

  body      вершина одежды ушла под кожу своей части тела (скрытые под одеждой полигоны тела не считаются);
  layer     вершина верхнего слоя ушла под наружную поверхность нижнего слоя;
  collider  сустав цепочки динамики оказался внутри коллайдера до выталкивания (насколько коллайдер
            отодвигает ткань: большая величина — подол лежит на бедре, это нормально, но стоит посмотреть рендер).

Пороги: PEN_BODY и PEN_LAYER, мм. Строка таблицы: поза → деталь → вид → глубина → место (ближайший ориентир).
"""
import math
import numpy as np

from .body import skin_points, Surface, _rot
from .mesh import OUTER, RIM

PEN_BODY = 4.0          # мм: глубже — проникновение одежды в тело считается ошибкой
PEN_LAYER = 4.0         # мм: то же между слоями одежды
PEN_EXTREME = 12.0      # мм: порог для крайних поз (сгиб сустава больше 90°)
EXTREME = ("sit", "squat", "elbows_bent")   # в них тело само входит в себя в складке (линейный скиннинг без
                                            # корректирующих форм), и одежда в складке повторяет это
LATERAL = 0.75          # доля, на которую сустав цепочки подтягивается к смещению соседних цепочек (полотно)
NEAR = 30.0             # мм: глубже этого точка уже «с другой стороны», а не протыкание


# Растяжение и сжатие ткани считаются СВЕРХ кожи под ней: линейный скиннинг сам тянет кожу манекена у подмышки
# в позе «руки вверх» в разы, и облегающая вещь не может тянуться меньше. Ошибка — когда ткань тянется или
# сминается сильнее кожи под ней: это делают веса (резкий переход между костями), а не поза.
STRETCH_MAX = 0.60      # доля: ребро наружного слоя растянуто сильнее кожи под ним больше чем на 60 %
COMPRESS_MAX = 0.70     # доля: ребро сжато сильнее кожи под ним больше чем на 70 %
STRETCH_EXTREME = 0.90  # растяжение сверх кожи в крайних позах (EXTREME)
# В паху и подмышке ткань между двумя разведёнными костями тянется и в жизни (шаговый шов на широком шаге,
# бок под поднятой рукой); у локтя и колена — сгиб. Пороги растяжения по зонам (ближайший ориентир):
# Пах: шаговый шов свободных низов на широком шаге тянется на 97–107 % сверх кожи при любых настройках весов
# (замер на шортах и брюках образцов) — порог 110 % предложен и требует утверждения.
STRETCH_ZONES = {"пах": 1.10, "подмышка": 0.90, "локоть": 0.75, "колено": 0.75}


def limit(pose, kind, where=""):
    """Порог проникновения (мм) или растяжения / сжатия (доля) для позы, вида проверки и места."""
    if kind == "stretch":
        zone = next((v for k, v in STRETCH_ZONES.items() if where.startswith(k)), STRETCH_MAX)
        return max(zone, STRETCH_EXTREME) if pose in EXTREME else zone
    if kind == "compress":
        return COMPRESS_MAX
    if pose in EXTREME:
        return PEN_EXTREME
    return PEN_BODY if kind == "body" else PEN_LAYER


SELF_NEAR = 60.0        # мм: кожа «сама в себе» — вошла в часть тела дальше этого по телу в покое


def skin_self(body, Vb, k=48):
    """Вершины кожи, которые в позе сами ушли внутрь другой части тела (икра в бедро в приседе, живот в бедро
    сидя): линейный скиннинг сминает внутреннюю сторону сильного сгиба. Ткань, попавшая туда, проникает в кожу,
    которая сама проникла в тело, — это не ошибка вещи, а предел позы; posetest считает такие места отдельно."""
    from scipy.spatial import cKDTree
    from .body import closest_on_tris
    T = body.T
    Cp = Vb[T].mean(axis=1)
    C0 = body.V[T].mean(axis=1)
    Nt = np.cross(Vb[T[:, 1]] - Vb[T[:, 0]], Vb[T[:, 2]] - Vb[T[:, 0]])
    Nt /= np.maximum(np.linalg.norm(Nt, axis=1, keepdims=True), 1e-12)
    _, cand = cKDTree(Cp).query(Vb, k=k)
    far = np.linalg.norm(C0[cand] - body.V[:, None, :], axis=2) > SELF_NEAR      # не своя окрестность
    best = np.full(len(Vb), np.inf)
    sign = np.ones(len(Vb))
    for j in range(cand.shape[1]):
        ok = far[:, j]
        if not ok.any():
            continue
        r = np.nonzero(ok)[0]
        tt = cand[r, j]
        P = Vb[r]
        A, B_, C_ = Vb[T[tt, 0]], Vb[T[tt, 1]], Vb[T[tt, 2]]
        bc = closest_on_tris(P, A, B_, C_)
        X = bc[:, :1] * A + bc[:, 1:2] * B_ + bc[:, 2:] * C_
        d = np.linalg.norm(P - X, axis=1)
        better = d < best[r]
        idx = r[better]
        best[idx] = d[better]
        sign[idx] = np.sign(np.einsum("ij,ij->i", (P - X)[better], Nt[tt][better]))
    return (sign < 0) & (best < 40.0)


def _edges(q):
    """Рёбра наружного слоя квадовой детали: (K, 2) пары вершин."""
    F = q.F[q.face_tag == OUTER]
    E = []
    for a, b in ((0, 1), (1, 2), (2, 3), (3, 0)):
        ok = (F[:, a] >= 0) & (F[:, b] >= 0)
        E.append(np.stack([F[ok, a], F[ok, b]], 1))
    E = np.sort(np.vstack(E), axis=1)
    E = np.unique(E[E[:, 0] != E[:, 1]], axis=0)
    return E

# Позы: {роль кости: поворот}. Ключ без стороны ставит обе стороны зеркально (вектор задаётся для ЛЕВОЙ
# стороны: левая сторона персонажа — −Y, перёд — −X, верх — +Z). Формы поворота:
#   ("to", (x, y, z))            — направить кость по вектору (плечо, бедро);
#   ("bend", градусы, (x, y, z)) — согнуть в сторону вектора (локоть — вперёд, колено — назад);
#   [("x"|"y"|"z", градусы), …]  — повороты вокруг осей персонажа (корпус).
# "_root": (dx, dy, dz) — сдвиг всего тела, мм.
POSES = {
    "rest": {},
    "t_pose": {"upper_arm": ("to", (0, -1, 0))},
    "arms_down": {"upper_arm": ("to", (0.05, -0.16, -1)), "forearm": ("bend", 8, (-1, 0, 0))},
    "arms_up": {"upper_arm": ("to", (0, -0.35, 1)), "clavicle": [("x", -18)]},
    "arms_forward": {"upper_arm": ("to", (-1, -0.12, 0))},
    "elbows_bent": {"upper_arm": ("to", (0, -0.35, -0.94)), "forearm": ("bend", 100, (-1, 0, 0.2))},
    "squat": {"thigh": ("to", (-0.92, -0.2, -0.33)), "shin": ("bend", 115, (1, 0, 0)), "spine": [("y", -12)],
              "upper_arm": ("to", (-0.9, -0.2, -0.38)), "_root": (0, 0, -330)},
    "wide_step": {"thigh_L": ("to", (-0.5, -0.12, -0.86)), "thigh_R": ("to", (0.42, 0.12, -0.9)),
                  "shin_R": ("bend", 25, (1, 0, 0)), "upper_arm_L": ("to", (0.35, -0.2, -0.92)),
                  "upper_arm_R": ("to", (-0.35, 0.2, -0.92))},
    "side_step": {"thigh": ("to", (0, -0.42, -0.9))},
    "bend_forward": {"spine": [("y", -30)], "chest": [("y", -25)], "upper_chest": [("y", -10)],
                     "upper_arm": ("to", (-0.3, -0.15, -0.94))},
    "twist": {"spine": [("z", 18)], "chest": [("z", 18)], "upper_chest": [("z", 12)],
              "upper_arm": ("to", (0, -0.5, -0.86))},
    "sit": {"thigh": ("to", (-1, -0.1, 0.03)), "shin": ("bend", 88, (1, 0, 0)),
            "upper_arm": ("to", (-0.35, -0.2, -0.92)), "forearm": ("bend", 45, (-1, 0, 0)), "_root": (0, 0, -380)},
}
# Поза для показа: стоя, вес на левой ноге, руки расслаблены и чуть отведены, лёгкий поворот корпуса.
HERO = {
    "hips": [("x", 3.5)], "spine": [("x", -4), ("z", 5)], "chest": [("x", -2), ("z", 5)], "neck": [("z", -8)],
    "head": [("z", -6), ("x", 3)],
    "thigh_L": ("to", (-0.02, -0.03, -1)), "thigh_R": ("to", (-0.16, 0.2, -0.97)), "shin_R": ("bend", 14, (1, 0, 0)),
    "upper_arm_L": ("to", (0.10, -0.33, -0.94)), "forearm_L": ("bend", 12, (-1, 0, 0)),
    "upper_arm_R": ("to", (-0.06, 0.40, -0.91)), "forearm_R": ("bend", 28, (-1, 0, 0.1)),
}
POSES["hero"] = HERO


def _shortest(a, b):
    """Поворот кратчайшей дугой от направления a к b."""
    a, b = a / np.linalg.norm(a), b / np.linalg.norm(b)
    ax = np.cross(a, b)
    s = np.linalg.norm(ax)
    if s < 1e-9:
        return np.eye(3)
    return _rot(ax / s, math.degrees(math.atan2(s, float(a @ b))))


def _seg_closest(P, a, b):
    d = b - a
    t = np.clip(((P - a) @ d) / max(d @ d, 1e-9), 0.0, 1.0)
    return a + t[:, None] * d


def solve(rig, pose):
    """Матрицы всех костей (тела и динамики) для позы. Возвращает (M, давление коллайдеров по цепочкам)."""
    body, sk = rig.body, rig.skel
    M = body.pose_on(sk, pose)
    g = np.array([0.0, 0.0, -1.0])
    press, solved = [], []
    for c in rig.chains:
        pr = c["params"]
        Mp = M[c["parent"]]
        Rp = Mp[:3, :3]
        J = c["joints"]
        K = len(J) - 1
        Rf = np.eye(3)
        for f in c.get("follow", []):                     # подол идёт за бедром: доля поворота бедра вокруг сустава
            from scipy.spatial.transform import Rotation
            Rrel = Rp.T @ M[f["bone"]][:3, :3]
            R1 = Rotation.from_rotvec(Rotation.from_matrix(Rrel).as_rotvec() * f["weight"]).as_matrix()
            J = f["pivot"] + (J - f["pivot"]) @ R1.T
            Rf = R1 @ Rf
        J0 = c["joints"]
        use = rig.colliders if c["colliders"] == "auto" else [x for x in rig.colliders if x["name"] in c["colliders"]]
        caps = [((M[x["bone"]] @ np.append(x["a"], 1))[:3], (M[x["bone"]] @ np.append(x["b"], 1))[:3], x["r"]) for x in use]
        # В позе покоя цепочку ничто не двигает: радиус столкновения сустава не больше его зазора до
        # коллайдера в покое (иначе коллайдер толкал бы ткань уже в исходной позе).
        rest_gap = np.array([[max(np.linalg.norm(c["joints"][i] - _seg_closest(c["joints"][i][None], x["a"], x["b"])[0]) - x["r"], 0.0)
                              for x in use] for i in range(K + 1)]) if use else np.zeros((K + 1, 0))
        wg = pr["gravity"] / max(pr["gravity"] + pr["stiffness"], 1e-6)
        p = [(Mp @ np.append(J[0], 1))[:3]]
        worst = 0.0
        out = Rp @ c["out"]                               # «наружу от тела» у корня цепочки, в позе
        up = np.array([0.0, 0.0, 1.0])
        side = {}                                         # коллайдер -> сторона, на которую вытолкнут предыдущий сустав
        for i in range(1, K + 1):
            L = np.linalg.norm(J[i] - J[i - 1])
            d0 = Rp @ (J[i] - J[i - 1]) / L
            # тяжесть действует только на изменение ориентации: в позе покоя цепочка стоит как построена
            d = d0 + (g - Rp @ Rf @ g) * wg
            q = p[-1] + L * d / np.linalg.norm(d)
            now = {}
            for _ in range(4):
                for ci, (a, b, r) in enumerate(caps):
                    cpt = _seg_closest(q[None], a, b)[0]
                    v = q - cpt
                    dist = np.linalg.norm(v)
                    rj = min(pr["radius"], rest_gap[i, ci])
                    lack = r + rj - dist
                    if lack > 0:
                        worst = max(worst, float(lack))
                        # Ткань выталкивается только наружу от тела и вверх: полотно держат соседние
                        # цепочки, поэтому оно ложится на бедро сверху, а не соскальзывает вбок или под него.
                        nv = max(float(v @ out), 0.0) * out + max(float(v @ up), 0.0) * up
                        if np.linalg.norm(nv) < 0.35 * max(dist, 1e-6):
                            nv = out + up
                        ax = (b - a) / max(np.linalg.norm(b - a), 1e-9)
                        tcap = float((cpt - a) @ ax) / max(np.linalg.norm(b - a), 1e-9)
                        if 0.02 < tcap < 0.98:            # у цилиндра капсулы выталкивание вдоль оси не выводит наружу
                            nv = nv - (nv @ ax) * ax
                            if np.linalg.norm(nv) < 1e-6:
                                nv = up - (up @ ax) * ax
                        n = nv / np.linalg.norm(nv)
                        # сустав ниже по цепочке ложится на ту же сторону коллайдера, что и предыдущий
                        if ci in side and n @ side[ci] < 0.5:
                            n = side[ci]
                        q = cpt + n * (r + rj)
                        now[ci] = n
                v = q - p[-1]
                q = p[-1] + v / max(np.linalg.norm(v), 1e-9) * L
            side = now
            p.append(q)
        kin = np.array([(Mp @ np.append(J[i], 1))[:3] for i in range(K + 1)])     # без тяжести и коллайдеров
        solved.append(dict(c=c, p=np.array(p), kin=kin, J=J, J0=J0, Rp=Rp, Rf=Rf))
        press.append(worst)
    # Полотно между цепочками: цепочка, которую коллайдер не тронул, не может провиснуть клином между
    # двумя соседними, лёгшими на бёдра, — ткань тянет её за ними. Смещение сустава подтягивается к среднему
    # смещению соседей по кольцу, если оно больше собственного; длины костей затем восстанавливаются.
    groups = {}
    for s in solved:
        c = s["c"]
        if c["count"] > 2:
            groups.setdefault((c["part"], c["zone"], c["patch"]), []).append(s)
    for grp in groups.values():
        grp.sort(key=lambda s: s["c"]["index"])
        if len(grp) != grp[0]["c"]["count"] or len({len(s["p"]) for s in grp}) != 1:
            continue
        P = np.array([s["p"] for s in grp])
        D = P - np.array([s["kin"] for s in grp])
        closed = grp[0]["c"]["closed"]
        for _ in range(4):
            if closed:
                nb = (np.roll(D, 1, axis=0) + np.roll(D, -1, axis=0)) / 2
            else:
                Dp = np.concatenate([D[:1], D, D[-1:]], axis=0)
                nb = (Dp[:-2] + Dp[2:]) / 2
            more = np.linalg.norm(nb, axis=2, keepdims=True) > np.linalg.norm(D, axis=2, keepdims=True)
            D = np.where(more, D + LATERAL * (nb - D), D)
        P = np.array([s["kin"] for s in grp]) + D
        for s, q in zip(grp, P):
            q[0] = s["p"][0]
            for i in range(1, len(q)):                    # длины костей
                L = np.linalg.norm(s["J"][i] - s["J"][i - 1])
                v = q[i] - q[i - 1]
                q[i] = q[i - 1] + v / max(np.linalg.norm(v), 1e-9) * L
            s["p"] = q
    for s in solved:
        c, p, J, J0, Rp, Rf = s["c"], s["p"], s["J"], s["J0"], s["Rp"], s["Rf"]
        for i in range(len(p) - 1):
            d_rest = (J[i + 1] - J[i]) / np.linalg.norm(J[i + 1] - J[i])
            d_new = (p[i + 1] - p[i]) / np.linalg.norm(p[i + 1] - p[i])
            R = _shortest(Rp @ d_rest, d_new) @ Rp @ Rf
            Mi = np.eye(4)
            Mi[:3, :3] = R
            Mi[:3, 3] = p[i] - R @ J0[i]
            M[c["bones"][i]] = Mi
    return M, press


def _regions_for(rig, key, W):
    """Область тела, против которой проверяется каждая вершина детали: та, чьи кости её ведут.
    Вершины на костях динамики проверяются против туловища и ног (подол о бёдра)."""
    body = rig.body
    nb0 = body.W.shape[1]
    RW = np.zeros((len(W), 6), np.float32)
    for b in range(nb0):
        RW[:, body.bone_region[b]] += W[:, b]
    reg = RW.argmax(axis=1)
    dyn = W[:, nb0:].sum(axis=1) > 0.5
    return reg, dyn


def run(model, poses=None):
    """Прогнать модель через позы. Возвращает (rows, summary): rows — список словарей
    pose, part, kind, other, depth, count, where, point (в позе), rest (в покое)."""
    from .rig import Rig
    rig = Rig(model)
    body = rig.body
    poses = poses or [k for k in POSES if k != "hero"]
    parts = [p for p in rig.parts if p.mesh == "quad"]
    tri_reg = body.treg
    rows = []
    from scipy.spatial import cKDTree
    BE = np.unique(np.sort(np.vstack([body.T[:, [0, 1]], body.T[:, [1, 2]], body.T[:, [2, 0]]]), axis=1), axis=0)
    bl0 = np.maximum(np.linalg.norm(body.V[BE[:, 0]] - body.V[BE[:, 1]], axis=1), 1e-9)
    btree = cKDTree(body.V)
    near_body = {}
    for p in parts:
        E = _edges(p.quad)
        if len(E):
            near_body[p.key] = btree.query((p.quad.V[E[:, 0]] + p.quad.V[E[:, 1]]) / 2, k=6)[1]
    for name in poses:
        M, press = solve(rig, POSES[name] if isinstance(name, str) else name)
        Vb = skin_points(body.V, np.pad(body.W, ((0, 0), (0, 0))), M[: body.W.shape[1]])
        Sb = Surface(Vb, body.T)
        collapsed = skin_self(body, Vb)[body.T].any(axis=1)              # треугольники кожи, ушедшие в тело
        br = np.linalg.norm(Vb[BE[:, 0]] - Vb[BE[:, 1]], axis=1) / bl0          # растяжение кожи по рёбрам
        skin_hi = np.ones(len(body.V))
        skin_lo = np.ones(len(body.V))
        for c in (0, 1):
            np.maximum.at(skin_hi, BE[:, c], br)
            np.minimum.at(skin_lo, BE[:, c], br)
        posed, outer = {}, {}
        for p in parts:
            q = p.quad
            Vp = skin_points(q.V, rig.W[p.key], M)
            posed[p.key] = Vp
            reg, dyn = _regions_for(rig, p.key, rig.W[p.key])
            depth = np.zeros(len(Vp))
            skin_depth = np.zeros(len(Vp))
            groups = [(np.nonzero((reg == r) & ~dyn)[0], tri_reg == r) for r in range(6)]
            groups.append((np.nonzero(dyn)[0], np.isin(tri_reg, (0, 4, 5))))
            for sel, tmask in groups:
                if not len(sel) or not tmask.any():
                    continue
                h = Sb.closest(Vp[sel], tmask, k=8)
                d = h["dist"]
                bad = (d < 0) & (d > -NEAR) & ~rig.hidden[h["tri"]]
                selfc = bad & collapsed[h["tri"]]
                depth[sel[bad & ~selfc]] = -d[bad & ~selfc]
                skin_depth[sel[selfc]] = -d[selfc]
            # растяжение и сжатие ткани: длины рёбер наружного слоя в позе против покоя
            E = _edges(q)
            if len(E):
                l0 = np.linalg.norm(q.V[E[:, 0]] - q.V[E[:, 1]], axis=1)
                l1 = np.linalg.norm(Vp[E[:, 0]] - Vp[E[:, 1]], axis=1)
                ok = l0 > 0.3
                r = np.where(ok, l1 / np.maximum(l0, 1e-9), 1.0)
                nb = near_body[p.key]
                s_hi = skin_hi[nb].mean(axis=1)                 # кожа под ребром ткани
                s_lo = skin_lo[nb].mean(axis=1)
                for kind_, val in (("stretch", r - s_hi), ("compress", s_lo - r)):
                    j = int(np.argmax(val))
                    if val[j] > 0.15:
                        mid = (q.V[E[j, 0]] + q.V[E[j, 1]]) / 2
                        wh = body.nearest_landmark(mid)
                        rows.append(dict(pose=name, part=p.key, kind=kind_, other="", depth=float(val[j]),
                                         count=int((val > limit(name, kind_, wh)).sum()), where=wh,
                                         point=((Vp[E[j, 0]] + Vp[E[j, 1]]) / 2).tolist(), rest=mid.tolist()))
            if skin_depth.max() > 0.05:
                i = int(skin_depth.argmax())
                rows.append(dict(pose=name, part=p.key, kind="skin", other="кожа сама вошла в тело", depth=float(skin_depth[i]),
                                 count=0, where=body.nearest_landmark(q.V[i]), point=Vp[i].tolist(), rest=q.V[i].tolist()))
            if depth.max() > 0.05:
                i = int(depth.argmax())
                rows.append(dict(pose=name, part=p.key, kind="body", other="", depth=float(depth[i]),
                                 count=int((depth > limit(name, "body")).sum()), where=body.nearest_landmark(q.V[i]),
                                 point=Vp[i].tolist(), rest=q.V[i].tolist()))
        for A in parts:                                   # слои: верхний слой под наружной поверхностью нижнего
            qa = A.quad
            Fa = qa.F[qa.face_tag == OUTER]
            Ta = np.vstack([Fa[:, :3], Fa[Fa[:, 3] >= 0][:, [0, 2, 3]]])
            if not len(Ta):
                continue
            rimv = np.zeros(len(qa.V), bool)
            rr = qa.F[qa.face_tag == RIM].ravel()
            rimv[rr[rr >= 0]] = True
            Sa = None
            regA, dynA = _regions_for(rig, A.key, rig.W[A.key])
            lo, hi = posed[A.key].min(axis=0), posed[A.key].max(axis=0)
            for Bp in parts:
                if Bp is A or Bp.layer <= A.layer or not A.layer:
                    continue
                Vq = posed[Bp.key]
                near = np.nonzero(((Vq > lo - 15) & (Vq < hi + 15)).all(axis=1))[0]
                if not len(near):
                    continue
                Sa = Sa or Surface(posed[A.key], Ta)
                h = Sa.closest(Vq[near], k=8)
                d = h["dist"]
                edge = rimv[Ta[h["tri"]]].any(axis=1)
                # рукав, прижатый к боку, — не ошибка слоёв: сравниваются вещи на одной части тела
                regB, dynB = _regions_for(rig, Bp.key, rig.W[Bp.key])
                va = Ta[h["tri"]][:, 0]
                # вершины на костях динамики (подол) сравниваются с вещами на туловище и ногах, но не на руках
                body_a, body_b = np.isin(regA[va], (0, 4, 5)), np.isin(regB[near], (0, 4, 5))
                same = (regB[near] == regA[va]) | (dynB[near] & body_a) | (dynA[va] & body_b)
                bad = (d < 0) & (d > -NEAR) & ~edge & same
                if bad.any():
                    j = int((-d * bad).argmax())
                    i = int(near[j])
                    if -d[j] > 0.05:
                        rows.append(dict(pose=name, part=Bp.key, kind="layer", other=A.key, depth=float(-d[j]),
                                         count=int((bad & (-d > limit(name, "layer"))).sum()),
                                         where=body.nearest_landmark(Bp.quad.V[i]), point=Vq[i].tolist(),
                                         rest=Bp.quad.V[i].tolist()))
        for c, w in zip(rig.chains, press):
            if w > 0.5:
                rows.append(dict(pose=name, part=c["part"], kind="collider", other=f"цепочка {c['index']}", depth=float(w),
                                 count=0, where=body.nearest_landmark(c["joints"][-1]), point=None, rest=c["joints"][-1].tolist()))
    # по одной строке «коллайдер» на деталь и позу — самая нагруженная цепочка
    best = {}
    for r in rows:
        k = (r["pose"], r["part"], r["kind"], r["other"] if r["kind"] == "layer" else "")
        if k not in best or r["depth"] > best[k]["depth"]:
            best[k] = r
    rows = sorted(best.values(), key=lambda r: (-(r["kind"] != "collider"), -r["depth"]))
    fails = [r for r in rows if r["kind"] not in ("collider", "skin") and r["depth"] > limit(r["pose"], r["kind"], r["where"])]
    summary = dict(poses=list(poses), parts=[p.key for p in parts],
                   thresholds=dict(body=PEN_BODY, layer=PEN_LAYER, extreme=PEN_EXTREME, extreme_poses=list(EXTREME)),
                   failed=len(fails), worst_body=max([r["depth"] for r in rows if r["kind"] == "body"], default=0.0),
                   worst_layer=max([r["depth"] for r in rows if r["kind"] == "layer"], default=0.0),
                   worst_collider=max([r["depth"] for r in rows if r["kind"] == "collider"], default=0.0),
                   worst_stretch=max([r["depth"] for r in rows if r["kind"] == "stretch"], default=0.0),
                   worst_skin=max([r["depth"] for r in rows if r["kind"] == "skin"], default=0.0),
                   worst_compress=max([r["depth"] for r in rows if r["kind"] == "compress"], default=0.0))
    return rows, summary, rig


def bone_matrices(rig, pose):
    """Матрицы костей позы для Blender: {имя кости: 16 чисел построчно} в координатах персонажа (мм)."""
    M, _ = solve(rig, POSES[pose] if isinstance(pose, str) else pose)
    return {n: M[i].reshape(-1).tolist() for i, n in enumerate(rig.skel.names)}
