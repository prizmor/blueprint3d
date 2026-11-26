"""Одежда из проверенных блоков: каждая функция Outfit возвращает Piece — сетки наружной поверхности
вещи, построенные по телу (bp3d.body), с кромками, к которым пристыковываются другие блоки.

Это не симуляция ткани и не выкройки: вещь описывается сразу в 3D относительно тела —
оболочка тела со смещением (лиф, рукав, чулок), лофт колец по ориентирам (юбка), полоса вдоль кромки
(воротник, манжета, кант, оборка, пояс), жёсткие детали обычными средствами kit.

    O = Outfit(M, BODY)                                    # M — Model, BODY — body.load(...)
    top = O.bodice(layer=1, bottom="waist", neck="round")  # лиф с проймами и вырезом
    sl = O.sleeve(top, "L", length=0.55, kind="puff")      # рукав от проймы лифа
    O.add("blouse", 1, "Блуза", "Хлопок", [top, sl, O.sleeve(top, "R", length=0.55, kind="puff")],
          finish="cloth", color="white", layer=1, hides=True)

Слои: 1 — у тела (бельё, чулки, облегающее), 2 — верх и юбки, 3 — верхняя одежда, 4 — аксессуары.
Отступ внутренней поверхности от тела растёт по слоям (LAYER_GAP), поэтому слои не пересекаются.
Сетки всех блоков идут сверху вниз (v: от плеча к подолу, от плеча к запястью), нормаль — наружу.
Правила и порядок работы — docs/manual.ru.md, раздел «Одежда».
"""
import math
import numpy as np

from .mesh import Patch, QuadMesh, quad_sweep, revolve_quad, spacing, resample_closed, resample_open, _fix_outward
from .body import _smooth_circular
from . import folds as FL
from .folds import Fold

LAYER_GAP = {1: 2.0, 2: 6.0, 3: 10.0, 4: 14.0}        # отступ внутренней поверхности слоя от тела, мм
ROW_STEP = 20.0                                       # шаг рядов по умолчанию, мм
JOINT_DENSE = 1.8                                     # во сколько раз гуще ряды у сустава
MIN_JOINT_LOOPS = 3                                   # петель поперёк сгиба в зоне сустава (проверяет check)

# Пресеты динамики (кости с пружиной). stiffness — насколько кость тянется к позе покоя (0…1),
# damping — затухание (0…1), gravity — доля силы тяжести (0…1), radius — радиус столкновения кости, мм.
DYNAMICS = {
    "stiff": dict(stiffness=0.75, damping=0.45, gravity=0.10, radius=18.0),    # пружинит, держит форму
    "soft": dict(stiffness=0.25, damping=0.20, gravity=0.60, radius=14.0),     # обвисает
    "rigid": None,                                                             # без динамики
}


def smooth_line(line, closed=True, step=12.0, tension=0.0):
    """Сгладить и уплотнить кромку: кубический сплайн через точки, шаг step мм (для полос вдоль кромки,
    чтобы воротник и кант не повторяли углы редкой сетки)."""
    from scipy.interpolate import CubicSpline
    P = np.asarray(line, float)
    keep = np.concatenate([[True], np.linalg.norm(np.diff(P, axis=0), axis=1) > 1e-6])   # без совпадающих точек
    P = P[keep]
    if closed and len(P) > 2 and np.linalg.norm(P[0] - P[-1]) < 1e-6:
        P = P[:-1]
    Q = np.vstack([P, P[:1]]) if closed else P
    d = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(Q, axis=0), axis=1))])
    n = max(8, int(round(d[-1] / step)))
    cs = CubicSpline(d, Q, bc_type="periodic" if closed else "natural")
    t = np.linspace(0, d[-1], n, endpoint=not closed)
    return cs(t)


def smoothstep(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3 - 2 * x)


class Piece:
    """Блок одежды: лоскуты наружной поверхности (patches) с толщиной t либо готовое тело (solid).
    edges — именованные кромки (n, 3) для стыковки: "bottom", "neck", "armhole_L", "end", "hem"...
    joints — зоны суставов, которые блок пересекает (для проверки плотности петель)."""

    def __init__(self, patches=(), t=1.2, edges=None, solid=None, joints=(), name=""):
        self.patches = list(patches)
        self.t = t
        self.edges = dict(edges or {})
        self.solid = solid
        self.joints = list(joints)
        self.name = name
        self.folds = []         # складки и рельеф, которые блок несёт сам (рубчик резинки, строчка) — см. bp3d.folds
        self.kind = None        # тип блока ("pants", "sleeve", "skirt", ...) — для auto_folds


WORLD_DIRS = {"front": (-1.0, 0.0, 0.0), "back": (1.0, 0.0, 0.0), "up": (0.0, 0.0, 1.0), "down": (0.0, 0.0, -1.0)}


class Outfit:
    def __init__(self, model, body, cols=48, phantom=True):
        """cols — число петель вокруг туловища по умолчанию (кратно 8)."""
        self.M, self.B = model, body
        self.cols = cols
        model.body = body
        if phantom and not any(p.key == "body" for p in model.parts):
            model.add("body", None, "Тело (манекен)", "", body.shape(), group="phantom")

    # ------------------------------------------------------------ служебное
    def z(self, ref):
        """Высота: число, имя ориентира ("waist") или (ориентир, смещение мм)."""
        if isinstance(ref, (tuple, list)):
            return self.z(ref[0]) + float(ref[1])
        if isinstance(ref, str):
            v = self.B.lm[ref]
            return float(v[2]) if np.ndim(v) else float(v)
        return float(ref)

    def profile(self, spec):
        """Отступ по высоте: число, функция z -> мм или {ориентир или высота: мм} с интерполяцией."""
        if callable(spec):
            return spec
        if isinstance(spec, dict):
            pts = sorted((self.z(k), float(v)) for k, v in spec.items())
            zs, vs = [p[0] for p in pts], [p[1] for p in pts]
            return lambda z: float(np.interp(z, zs, vs))
        return lambda z: float(spec)

    def gap(self, layer, t):
        """Отступ НАРУЖНОЙ поверхности слоя от тела: зазор слоя + толщина."""
        return LAYER_GAP[layer] + t

    def _outward(self, patch):
        """Развернуть лоскут нормалью от тела (обход по u), не меняя направление v."""
        G = patch.G
        i, j = G.shape[0] // 2, G.shape[1] // 2
        pts = np.array([G[i, j], G[i // 2, j], G[min(i + i // 2, G.shape[0] - 1), j]])
        idx = [(i, j), (i // 2, j), (min(i + i // 2, G.shape[0] - 1), j)]
        nr = patch.normals()
        h = self.B.closest(pts)
        s = sum(float(nr[a, b] @ (p - q)) for (a, b), p, q in zip(idx, pts, h["point"]))
        if s < 0:
            return Patch(G[::-1], patch.closed_u, patch.closed_v, patch.name, patch.uv_scale)
        return patch

    def _rows(self, length, step, dense=()):
        n = max(4, int(round(length / (step or ROW_STEP))) + 1)
        extra = sum(2 * w * (k - 1) for _, w, k in dense)
        return spacing(int(round(n * (1 + extra))), dense)

    def add(self, key, pos, name, material, pieces, finish="cloth", color=None, layer=1, bind=None,
            dynamics=None, hides=None, pattern=None, note="", count=True, group="ext", t=None, lining=None, folds=None):
        """Собрать блоки в одну деталь: общие ряды свариваются, оболочка получает толщину, готовые тела
        добавляются как есть. Заполняет слой, привязку, динамику и сведения для проверок.
        folds — складки и рельеф (bp3d.folds.Fold, помощники fold_* / folds_* и auto_folds): режим "geo"
        меняет геометрию оболочки (сетка у складок сгущается), "normal" и "mask" запекаются в карты.
        bind — привязка (bp3d.rig); не задана — привязка блока (у обуви — жёсткая по сегментам), иначе "auto"."""
        pieces = pieces if isinstance(pieces, (list, tuple)) else [pieces]
        if bind is None:
            bind = next((p.bind for p in pieces if getattr(p, "bind", None) is not None), "auto")
        shells = [p for p in pieces if p.patches]
        fl = list(folds or []) + [f for p in pieces for f in getattr(p, "folds", [])]
        mesh, notes = None, []
        if shells:
            th = t if t is not None else shells[0].t
            patches = [Patch(q.G.copy(), q.closed_u, q.closed_v, q.name, q.uv_scale) for p in shells for q in p.patches]
            if fl:
                solids = [q for p in pieces if p.solid is not None for q in p.solid.patches]
                surf = FL.surface_of(patches + solids)
                for f in fl:
                    f.resolve(surf, patches + solids)
                patches = FL.refine_for_folds(patches, fl, notes)
            mesh = QuadMesh.from_patches(patches)
            H = FL.apply_geo(mesh, fl) if fl else None
            if H is not None and np.abs(H).max() > 1e-3:
                # ткань у складок не входит в тело: сдвинутые точки — не ближе отступа слоя
                moved = np.abs(H) > 1e-3
                mesh.V[moved] = self.B.push_out(mesh.V[moved], LAYER_GAP.get(layer, 2.0) + th - 0.3, cells=False)
                mesh.sync_patches()
            mesh.solidify(th)
        elif fl:
            solids = [q for p in pieces if p.solid is not None for q in p.solid.patches]
            surf = FL.surface_of(solids) if solids else None
            for f in fl:
                if "geo" in f.mode:
                    notes.append(f"{f.name or 'складка'}: на готовом теле режим geo не применяется — только normal/mask")
                f.resolve(surf, solids)
        for note_ in notes:
            print("  ! " + key + ": " + note_)
        for p in pieces:
            if p.solid is not None:
                mesh = p.solid if mesh is None else mesh.merged(p.solid)
        dd = next((p.dyn_defaults for p in pieces if getattr(p, "dyn_defaults", None)), None)
        if dynamics and dd:                          # умолчания динамики от блока (у юбки — таз, старт у бёдер)
            fill = lambda d: {**dd, **(d if isinstance(d, dict) else dict(preset=d))}
            dynamics = [fill(d) for d in dynamics] if isinstance(dynamics, (list, tuple)) else fill(dynamics)
        info = dict(thickness=mesh.thickness, joints=[j for p in pieces for j in p.joints], gap=LAYER_GAP.get(layer, 0.0),
                    folds=fl, fold_notes=notes,
                    regions={q.name: tuple(p.regions) for p in pieces if getattr(p, "regions", None) for q in p.patches})
        if lining is not None:
            info["lining"] = lining
        self.M.add(key, pos, name, material, mesh, finish=finish, group=group, note=note, count=count, bind=bind,
                   dynamics=dynamics, layer=layer, hides=hides, color=color, pattern=pattern, info=info)
        return mesh

    # ------------------------------------------------------------ туловище: труба
    def tube(self, top, bottom, layer=1, ease=0.0, tent=0.2, t=1.2, cols=None, row_step=None, smooth=1.0,
             name="tube", dense_at=("waist",)):
        """Оболочка туловища между высотами top и bottom (не выше подмышек): корсаж, бандо, топ без
        бретелей, кокетка юбки. ease — прибавка свободы поверх отступа слоя (число, функция или
        {ориентир: мм}); tent — натяжение через впадины (0 — по телу, 1 — по выпуклой оболочке)."""
        B = self.B
        zt, zb = self.z(top), self.z(bottom)
        if zt > B.lm["armpit"] - 8:
            raise ValueError("tube: верх выше подмышек — для вещи с плечами используйте bodice()")
        nu = cols or self.cols
        dense = [((zt - self.z(k)) / (zt - zb), 30.0 / (zt - zb), JOINT_DENSE) for k in dense_at
                 if zb + 10 < self.z(k) < zt - 10]
        zs = zt + (zb - zt) * self._rows(zt - zb, row_step, dense)
        e = self.profile(ease)
        off = lambda z: self.gap(layer, t) + e(z)
        G = B.torso_grid(zs, nu, offset=off, tent=tent, smooth=smooth)
        G = B.push_out(G, np.array([[off(z) for z in zs]] * nu) - 0.3)
        p = Patch(G, closed_u=True, name=name)
        joints = [("талия", (B.center_x(B.lm["waist"]), 0.0, B.lm["waist"]), (0, 0, 1), 30.0, 260.0)] \
            if zb < B.lm["waist"] - 30 and zt > B.lm["waist"] + 30 else []
        return Piece([p], t, dict(top=G[:, 0], bottom=G[:, -1]), joints=joints, name=name)

    # ------------------------------------------------------------ туловище: лиф с плечами
    def bodice(self, layer=1, bottom="waist", ease=0.0, tent=0.25, t=1.2, cols=None, row_step=None,
               neck="round", neck_depth=70.0, neck_width=None, back_depth=18.0, armhole_drop=14.0,
               shoulder_out=0.0, open_front=False, smooth=1.0, name="bodice"):
        """Лиф, топ, рубашка, жакет, жилет: труба от подмышек до bottom плюс верх с плечами, проймами
        и вырезом. Кромки: bottom, neck, armhole_L, armhole_R (к ним стыкуются юбка, воротник, рукава).

        neck — "round" | "v" | "square" | "boat" | "high"; neck_depth — глубина выреза спереди от линии
        плеча, мм; neck_width — ширина выреза (по умолчанию от шеи); back_depth — глубина сзади.
        armhole_drop — насколько низ проймы ниже подмышки; shoulder_out — вынос плеча за сустав, мм.
        open_front=True — распашной перёд (жакет, жилет): полочки от выреза до низа, без середины.
        ease — прибавка свободы: {"waist": 2, "bust": 8} или число; полуприлегающий силуэт — ease и tent."""
        B, lm = self.B, self.B.lm
        nu = cols or self.cols
        if nu % 8:
            raise ValueError("bodice: число петель cols должно быть кратно 8")
        zt, zb = lm["armpit"] - armhole_drop, self.z(bottom)
        e = self.profile(ease)
        off = lambda z: self.gap(layer, t) + e(z)
        dense = [((zt - lm["waist"]) / (zt - zb), 30.0 / (zt - zb), JOINT_DENSE)] if zb < lm["waist"] - 30 else []
        zs = zt + (zb - zt) * self._rows(zt - zb, row_step, dense)
        Gt = B.torso_grid(zs, nu, offset=off, tent=tent, smooth=smooth)
        Gt = B.push_out(Gt, np.array([[off(z) for z in zs]] * nu) - 0.3)
        ring = Gt[:, 0]
        nq = nu // 4
        a = max(2, int(round(nu * 22.0 / 360)))                    # половина низа проймы, в петлях
        presets = dict(round=(1.0, 1.0), v=(1.0, 1.25), square=(1.15, 1.0), boat=(1.9, 0.35), high=(0.8, 0.3))
        kw, kd = presets[neck]
        yn = (neck_width / 2 if neck_width else (B.measures["neck"] / (2 * math.pi) + 14.0) * kw)
        depth = neck_depth * kd
        sA = 1.0 if ring[nq, 1] > 0 else -1.0                      # сторона первой четверти обхода
        ytip = abs(lm["shoulder_top_L"][1]) + shoulder_out
        # число петель половины выреза: по ширине выреза на уровне груди
        yfront = np.abs(ring[nu // 2 - nq: nu // 2 + 1, 1])[::-1]  # |y| колонок от середины переда к боку
        hn = int(np.clip(np.searchsorted(yfront, yn * 0.9), 2, nq - a - 2))
        ns = nq - a - hn
        nf = nu // 2 - 2 * a
        cf = lambda j: nq + a + j
        cb = lambda j: (nq - a - j) % nu
        # --- поверхность плеч: веер лучей в плоскостях y = const (спереди через плечо на спину)
        x0, z0 = B.center_x(zt), zt
        ymax = ytip + 12.0
        ys = np.linspace(-ymax, ymax, 41)
        phis = np.linspace(-0.2, math.pi + 0.2, 61)
        R = np.zeros((len(ys), len(phis)))
        zcap = lm["neck_base"] + 30.0
        for k, y in enumerate(ys):
            _, r = B.ring((x0, y, z0), (0, 1, 0), (-1, 0, 0), thetas=phis, mode="far")
            lim = np.where(np.sin(phis) > 0.05, (zcap - z0) / np.maximum(np.sin(phis), 0.05), np.inf)
            R[k] = np.minimum(r, lim)
        if tent > 0:                                               # мостик через ложбинку: огибающая по y
            from scipy.ndimage import gaussian_filter1d, maximum_filter1d
            Rm = gaussian_filter1d(maximum_filter1d(R, size=5, axis=0), 1.5, axis=0)
            R = R + (np.maximum(R, Rm) - R) * tent
        from scipy.interpolate import RegularGridInterpolator
        itp = RegularGridInterpolator((ys, phis), R, bounds_error=False, fill_value=None)

        offv = off(zt)

        def surf(y, ph):
            # Точка наружной поверхности вещи: тело плюс отступ вдоль луча веера. Лучи расходятся из оси,
            # поэтому сетка не складывается во впадинах (подъём по нормалям тела при отступе слоя 3 давал
            # складки, и изнанка выходила наружу). Точный зазор потом добирает push_out.
            y, ph = np.broadcast_arrays(np.asarray(y, float), np.asarray(ph, float))
            r = itp(np.stack([np.clip(y, -ymax, ymax), ph], axis=-1)) + offv
            return np.stack([x0 - r * np.cos(ph), y, z0 + r * np.sin(ph)], axis=-1)
        # линия плеча: угол наибольшей высоты в плоскостях от выреза до плеча
        pd = np.linspace(0.3, math.pi - 0.3, 80)
        phi_top = lambda y: float(pd[surf(np.full(80, abs(y)), pd)[:, 2].argmax()])
        phS = float(np.mean([phi_top(y) for y in np.linspace(yn, ytip, 5)]))
        rS = float(itp([[yn, phS]])[0]) + offv
        dF, dB = 22.0 / rS, 10.0 / rS                              # угол выреза чуть впереди и позади плеча
        nrow = max(3, int(round((lm["shoulder_top_L"][2] - zt) * 1.25 / (row_step or ROW_STEP))))

        def y_shoulder(j):
            if j <= ns:
                return sA * (ytip + (yn - ytip) * j / ns)
            if j >= nf - ns:
                return -sA * (yn + (ytip - yn) * (j - (nf - ns)) / ns)
            return sA * yn * (1 - 2 * (j - ns) / (nf - 2 * ns))

        def column(j, ph_a, ph_b, n):
            """Точки колонки j от угла ph_a до ph_b, n отрезков, равномерно по длине."""
            yF, yK, yS = ring[cf(j), 1], ring[cb(j), 1], y_shoulder(j)
            ph = np.linspace(ph_a, ph_b, 40)
            w = np.where(ph <= phS, smoothstep(ph / phS), smoothstep((math.pi - ph) / (math.pi - phS)))
            y = np.where(ph <= phS, yF, yK) * (1 - w) + yS * w
            return resample_open(surf(y, ph), n + 1)

        def strap(j):
            return np.vstack([column(j, 0.0, phS - dF, nrow)[:-1], column(j, phS - dF, phS, 1)[:-1],
                              column(j, phS, phS + dB, 1)[:-1], column(j, phS + dB, math.pi, nrow)])
        Rr = 2 * nrow + 2
        cornerF = strap(ns)[nrow]
        cornerB = strap(ns)[nrow + 2]
        shape = dict(round=lambda c: math.sqrt(max(0.0, 1 - c * c)), v=lambda c: 1 - abs(c),
                     square=lambda c: min(1.0, (1 - abs(c)) / 0.3), boat=lambda c: math.sqrt(max(0.0, 1 - c * c)),
                     high=lambda c: math.sqrt(max(0.0, 1 - c * c)))[neck]

        def neck_col(j, front):
            c = 2 * (j - ns) / (nf - 2 * ns) - 1
            if front:
                zl = max(cornerF[2] - depth * shape(c), zt + 14.0)
                ph = np.linspace(0.0, phS - dF, 60)
            else:
                zl = max(cornerB[2] - back_depth * math.sqrt(max(0.0, 1 - c * c)), zt + 14.0)
                ph = np.linspace(math.pi, phS + dB, 60)
            yE, yS = (ring[cf(j), 1] if front else ring[cb(j), 1]), y_shoulder(j)
            w = smoothstep(ph / phS) if front else smoothstep((math.pi - ph) / (math.pi - phS))
            P = surf(yE * (1 - w) + yS * w, ph)
            k = int(np.argmax(P[:, 2] >= zl)) if (P[:, 2] >= zl).any() else len(P) - 1
            k = max(k, 2)
            return resample_open(P[: k + 1], nrow + 1)
        S = {j: strap(j) for j in list(range(0, ns + 1)) + list(range(nf - ns, nf + 1))}
        def lift(G):
            return np.array(G, float)                 # отступ уже учтён в surf()
        strapA = lift(np.stack([S[j] for j in range(0, ns + 1)], axis=0))
        strapB = lift(np.stack([S[j] for j in range(nf - ns, nf + 1)], axis=0))
        grids = {"strapA": strapA, "strapB": strapB}
        if not open_front:
            Fc = np.stack([S[ns][: nrow + 1]] + [neck_col(j, True) for j in range(ns + 1, nf - ns)]
                          + [S[nf - ns][: nrow + 1]], axis=0)
            grids["front"] = lift(Fc)
        Bc = np.stack([S[ns][nrow + 2:][::-1]] + [neck_col(j, False) for j in range(ns + 1, nf - ns)]
                      + [S[nf - ns][nrow + 2:][::-1]], axis=0)[:, ::-1]
        grids["back"] = lift(Bc)
        # общие колонки и стык с трубой: совпадение точек, плавный переход за 3 ряда
        if "front" in grids:
            grids["front"][0], grids["front"][-1] = strapA[-1, : nrow + 1], strapB[0, : nrow + 1]
        grids["back"][0], grids["back"][-1] = strapA[-1, nrow + 2:], strapB[0, nrow + 2:]

        def seat(G, cols, front, i0=0):
            n = G.shape[1]
            for jj, c in enumerate(cols):
                target = ring[c]
                if front:
                    d = target - G[jj, 0]
                    for i in range(min(4, n)):
                        G[jj, i] += d * (1 - smoothstep(i / 3.0))
                else:
                    d = target - G[jj, n - 1]
                    for i in range(min(4, n)):
                        G[jj, n - 1 - i] += d * (1 - smoothstep(i / 3.0))
        seat(strapA, [cf(j) for j in range(0, ns + 1)], True)
        seat(strapA, [cb(j) for j in range(0, ns + 1)], False)
        seat(strapB, [cf(j) for j in range(nf - ns, nf + 1)], True)
        seat(strapB, [cb(j) for j in range(nf - ns, nf + 1)], False)
        if "front" in grids:
            seat(grids["front"], [cf(j) for j in range(ns, nf - ns + 1)], True)
        seat(grids["back"], [cb(j) for j in range(ns, nf - ns + 1)], False)
        def relax(G, head, tail, it=3):
            """Сгладить ряды у стыка с трубой (вдоль колонок): без резкого излома, на котором нормали
            вырождаются и изнанка совпадает с лицом."""
            n = G.shape[1]
            rows = [i for i in range(1, min(6, n - 1))] if head else []
            rows += [i for i in range(max(n - 6, 1), n - 1)] if tail else []
            for _ in range(it):
                H = G.copy()
                for i in rows:
                    G[:, i] = (H[:, i - 1] + 2 * H[:, i] + H[:, i + 1]) / 4
                    if G.shape[0] > 2:                             # и поперёк, кроме крайних колонок
                        G[1:-1, i] = (G[1:-1, i] * 2 + H[:-2, i] + H[2:, i]) / 4
        relax(strapA, True, True)
        relax(strapB, True, True)
        if "front" in grids:
            relax(grids["front"], True, False)
        relax(grids["back"], False, True)
        for k in grids:
            grids[k] = B.push_out(grids[k], offv - 0.3)
        if "front" in grids:                                       # после выталкивания общие колонки снова совместить
            grids["front"][0], grids["front"][-1] = grids["strapA"][-1, : nrow + 1], grids["strapB"][0, : nrow + 1]
        grids["back"][0], grids["back"][-1] = grids["strapA"][-1, nrow + 2:], grids["strapB"][0, nrow + 2:]
        for k, cols_, fr in (("strapA", [cf(j) for j in range(0, ns + 1)], True), ("strapB", [cf(j) for j in range(nf - ns, nf + 1)], True)):
            grids[k][:, 0] = ring[cols_]
        grids["strapA"][:, -1] = ring[[cb(j) for j in range(0, ns + 1)]]
        grids["strapB"][:, -1] = ring[[cb(j) for j in range(nf - ns, nf + 1)]]
        if "front" in grids:
            grids["front"][:, 0] = ring[[cf(j) for j in range(ns, nf - ns + 1)]]
        grids["back"][:, -1] = ring[[cb(j) for j in range(ns, nf - ns + 1)]]
        # Ткань у шеи: кромка выреза выравнивается вдоль себя, внутренние точки переда и спинки
        # сглаживаются (выталкивание по ячейкам оставляло бугры, и стойка воротника садилась на неровный
        # вырез), затем зазор до тела восстанавливается без сдвига общих рядов.
        for key, row in (("front", -1), ("back", 0)):
            if key not in grids or grids[key].shape[0] < 4:
                continue
            Gy = grids[key]
            for _ in range(2):
                H = Gy.copy()
                Gy[1:-1, row] = (H[:-2, row] + 2 * H[1:-1, row] + H[2:, row]) / 4
                H = Gy.copy()
                Gy[1:-1, 1:-1] = 0.5 * H[1:-1, 1:-1] + 0.125 * (H[:-2, 1:-1] + H[2:, 1:-1] + H[1:-1, :-2] + H[1:-1, 2:])
            cl = np.full(Gy.shape[:2], offv - 0.3)
            cl[0], cl[-1] = -1e9, -1e9
            cl[:, 0 if key == "front" else -1] = -1e9
            grids[key] = B.push_out(Gy, cl, cells=False)
        # труба: при распашном переде середина переда вынимается
        if open_front:
            order = [(nu // 2 + hn + k) % nu for k in range(nu - 2 * hn + 1)]
            tube = Patch(Gt[order], closed_u=False, name=name + "_body")
        else:
            tube = Patch(Gt, closed_u=True, name=name + "_body")
        patches = [self._outward(tube)] + [self._outward(Patch(g, name=f"{name}_{k}")) for k, g in grids.items()]
        sideA, sideB = ("R", "L") if sA > 0 else ("L", "R")
        edges = dict(bottom=Gt[:, -1], top=ring)
        edges["armhole_" + sideA] = np.vstack([grids["strapA"][0], ring[[(nq - a + k) % nu for k in range(1, 2 * a)]]])
        edges["armhole_" + sideB] = np.vstack([grids["strapB"][-1][::-1], ring[[(3 * nq - a + k) % nu for k in range(1, 2 * a)]]])
        nA, nB = grids["strapA"][-1, nrow: nrow + 3], grids["strapB"][0, nrow: nrow + 3]
        if open_front:
            fr = lambda g, col: np.vstack([Gt[col, ::-1], g[1: nrow + 1]])
            lineA = np.vstack([fr(grids["strapA"][-1], (nu // 2 - hn) % nu), nA[1:]])
            lineB = np.vstack([fr(grids["strapB"][0], (nu // 2 + hn) % nu), nB[1:]])
            edges["neck"] = np.vstack([lineA, grids["back"][1:-1, 0], lineB[::-1]])      # открытая кромка: низ–шея–низ
            edges["neck_closed"] = False
        else:
            edges["neck"] = np.vstack([grids["front"][:, -1], nB[1:], grids["back"][::-1, 0][1:], nA[::-1][1:-1]])
            edges["neck_closed"] = True
        joints = [("талия", (B.center_x(lm["waist"]), 0.0, lm["waist"]), (0, 0, 1), 30.0, 260.0)] if zb < lm["waist"] - 30 else []
        pc = Piece(patches, t, edges, joints=joints, name=name)
        pc.layer = layer
        return pc

    # ------------------------------------------------------------ трубы по конечностям
    def _limb_tube(self, limb, loop, t_end, off, row_step, t0=None, n=None, name="tube", blend=4, around=None,
                   tent=0.0, smooth_v=0.0, caps=()):
        """Труба вдоль руки или ноги от кромки loop (или от параметра t0) до t_end. off(rel) — отступ
        наружной поверхности от тела, rel = 0…1 вдоль трубы (если у функции есть атрибут by_t — off(t) по
        параметру конечности). around — добавка по сторонам {"front"|"back"|"out"|"in": мм или функция rel}
        (свободный крой: спереди и сзади больше); tent — натяжение через впадины (свободная штанина не
        повторяет колено и икру); smooth_v — сглаживание радиуса вдоль трубы, в рядах. Первый ряд совпадает
        с loop (сварится). caps — [(t_от, t_до, сторона, мм)]: отступ на стороне не больше мм в диапазоне t
        (внутренняя сторона сгиба: при сгибе линейный скиннинг сминает её, лишняя свобода проваливается в тело)."""
        B = self.B
        J = B.limb_axis(limb)
        L = np.linalg.norm(J[1] - J[0]) + np.linalg.norm(J[2] - J[1])
        kind = limb.split("_")[0]
        if loop is not None:
            loop = np.asarray(loop, float)
            n = len(loop)
            c = loop.mean(axis=0)
            if t0 is None:
                t0 = float(np.clip((c - J[0]) @ (J[1] - J[0]) / np.linalg.norm(J[1] - J[0]) / L, 0.02, 0.6))
            p, d = B.limb_point(limb, t0)
            ex, ey = B.limb_frame(limb, t0)
            th = np.arctan2((loop - p) @ ey, (loop - p) @ ex)
            k0 = int(np.abs(th).argmin())
            loop, th = np.roll(loop, -k0, axis=0), np.roll(th, -k0)
            th = np.unwrap(th)
            if th[-1] < th[0]:                                    # кромка обходится в другую сторону — развернуть
                loop = np.vstack([loop[:1], loop[1:][::-1]])
                th = np.unwrap(np.arctan2((loop - p) @ ey, (loop - p) @ ex))
            # углы строго возрастают и за полный обход набирают ровно 2π: кольца трубы не перекручиваются
            dth = np.maximum(np.diff(np.concatenate([th, [th[0] + 2 * math.pi]])), 0.02)
            th = th[0] + np.concatenate([[0.0], np.cumsum(dth)[:-1]]) * (2 * math.pi / dth.sum())
        else:
            th = np.arange(n) * 2 * math.pi / n
        tm = B.lm["elbow_t"] if kind == "arm" else B.lm["knee_t"]
        dense = [((tm - t0) / (t_end - t0), 0.07 / (t_end - t0), JOINT_DENSE)] if t0 + 0.08 < tm < t_end - 0.08 else []
        sp = self._rows((t_end - t0) * L, row_step, dense)
        ts = t0 + (t_end - t0) * sp
        uni = th[0] + np.arange(n) * 2 * math.pi / n
        side = limb.split("_")[1]
        axes = dict(WORLD_DIRS, out=(0.0, -1.0 if side == "L" else 1.0, 0.0), inner=(0.0, 1.0 if side == "L" else -1.0, 0.0))
        axes["in"] = axes.pop("inner")
        offv = (lambda tt, rel: off(tt)) if getattr(off, "by_t", False) else (lambda tt, rel: off(rel))
        rings, offs = [], []
        for k, (tt, rel) in enumerate(zip(ts, sp)):
            w = smoothstep(k / float(blend)) if loop is not None else 1.0
            thk = th * (1 - w) + uni * w
            o = np.full(n, float(offv(tt, rel)))
            if around and w > 0:
                ex, ey = B.limb_frame(limb, tt)
                dirs = np.cos(thk)[:, None] * ex + np.sin(thk)[:, None] * ey
                for nm_, val in around.items():
                    v_ = val(rel) if callable(val) else float(val)
                    o += np.maximum(dirs @ np.asarray(axes[nm_]), 0.0) ** 2 * v_ * w   # от стыка — плавно
                o = _smooth_circular(o, 2.0)
            if caps:
                ex, ey = B.limb_frame(limb, tt)
                dirs = np.cos(thk)[:, None] * ex + np.sin(thk)[:, None] * ey
                for c0, c1, nm_, mm in caps:
                    span = max(c1 - c0, 1e-6)
                    inside = float(smoothstep((tt - c0) / (0.25 * span)) * smoothstep((c1 - tt) / (0.25 * span)))
                    if inside <= 0:
                        continue
                    wdir = np.maximum(dirs @ np.asarray(axes[nm_]), 0.0) ** 1.5 * inside
                    o = o - np.maximum(o - mm, 0.0) * wdir
                o = _smooth_circular(o, 1.5)
            offs.append(o)
            # натяжение через впадины — ниже корня конечности (у паха и подмышки хулл раздул бы трубу)
            tw = float(smoothstep((tt - t0 - 0.05) / 0.12)) if tent else 0.0
            rings.append(B.limb_ring(limb, tt, n, o, tent=tent * w * tw, thetas=thk))
        G = np.stack(rings, axis=1)
        if smooth_v > 0 and G.shape[1] > 4:                       # свободная штанина: радиус без бугров колена
            from scipy.ndimage import gaussian_filter1d
            k0 = blend if loop is not None else 0
            Gs = gaussian_filter1d(G, smooth_v, axis=1, mode="nearest")
            wgt = smoothstep((np.arange(G.shape[1]) - k0) / 3.0)[None, :, None]
            G = G * (1 - wgt) + Gs * wgt
        if loop is not None:
            d0 = loop - G[:, 0]
            for k in range(min(blend + 1, G.shape[1])):
                G[:, k] += d0 * (1 - smoothstep(k / float(blend)))
            cl = np.stack(offs, axis=1) - 0.3
            cl[:, 0] = -1e9                                       # общий ряд не трогаем: он задан кромкой
            G = B.push_out(G, cl)
        else:
            G = B.push_out(G, np.stack(offs, axis=1) - 0.3)
        jn = "локоть" if kind == "arm" else "колено"
        joints = []
        if t0 + 0.05 < tm < t_end - 0.05:
            pj, dj = B.limb_point(limb, tm)
            joints.append((f"{jn} {limb[-1]}", tuple(pj), tuple(dj), 0.07 * L, 120.0))
        return self._outward(Patch(G, closed_u=True, name=name)), joints, ts

    def sleeve(self, top, side, length=1.0, kind="straight", ease=3.0, amount=35.0, t=None, row_step=None,
               name=None):
        """Рукав от проймы лифа top (Piece от bodice) вдоль руки до параметра length (1.0 — запястье,
        lm["elbow_t"] — локоть, 0.25 — короткий). kind: "straight" — втачной прямой; "flare" — расширяется
        книзу на amount мм; "bell" — раструб от локтя; "puff" — фонарик (объём amount, низ собран);
        "cap" — крылышко (короткий, length ≈ 0.15, расклёшен). Кромка: end."""
        t = top.t if t is None else t
        layer = getattr(top, "layer", 1)
        base = self.gap(layer, t) + ease
        prof = dict(straight=lambda r: 0.0, flare=lambda r: amount * r ** 1.6,
                    bell=lambda r: amount * float(smoothstep((r - 0.45) / 0.55)),
                    puff=lambda r: amount * math.sin(math.pi * min(1.0, r) ** 0.85) ** 0.9,
                    cap=lambda r: amount * r)[kind]
        name = name or f"sleeve_{side}"
        p, joints, _ = self._limb_tube(f"arm_{side}", top.edges[f"armhole_{side}"], length,
                                       lambda r: base + prof(r), row_step, name=name)
        pc = Piece([p], t, dict(end=p.G[:, -1]), joints=joints, name=name)
        pc.layer = layer
        pc.limb = f"arm_{side}"
        pc.kind, pc.length = "sleeve", length
        return pc

    def stocking(self, side, top=0.3, bottom=0.97, layer=1, ease=0.0, t=0.8, cols=20, row_step=None, name=None):
        """Чулок, гольф, гетра: оболочка ноги между параметрами top и bottom (0 — тазобедренный сустав,
        lm["knee_t"] — колено, 1 — щиколотка). Кромки: top, end."""
        name = name or f"stocking_{side}"
        off = self.gap(layer, t) + ease
        p, joints, _ = self._limb_tube(f"leg_{side}", None, bottom, lambda r: off, row_step, t0=top, n=cols, name=name)
        pc = Piece([p], t, dict(top=p.G[:, 0], end=p.G[:, -1]), joints=joints, name=name)
        pc.layer, pc.limb = layer, f"leg_{side}"
        return pc

    def glove(self, side, top=0.55, bottom=0.99, layer=1, ease=0.0, t=0.8, cols=16, row_step=None, name=None):
        """Нарукавник / манжета-перчатка без кисти: оболочка руки между параметрами top и bottom."""
        name = name or f"armband_{side}"
        off = self.gap(layer, t) + ease
        p, joints, _ = self._limb_tube(f"arm_{side}", None, bottom, lambda r: off, row_step, t0=top, n=cols, name=name)
        pc = Piece([p], t, dict(top=p.G[:, 0], end=p.G[:, -1]), joints=joints, name=name)
        pc.layer, pc.limb = layer, f"arm_{side}"
        return pc

    # ------------------------------------------------------------ низ: юбка
    def skirt(self, waist="waist", length=420.0, kind="a", flare=None, layer=2, ease=2.0, t=1.2, cols=None,
              row_step=None, pleats=0, pleat_depth=14.0, top=None, name="skirt"):
        """Юбка: кольца от талии вниз. kind: "straight" — прямая, "a" — А-силуэт, "bell" — колокол,
        "circle" — солнце; flare — вынос подола наружу относительно талии, мм (по умолчанию от kind).
        pleats — число складок геометрией (cols должно делиться на 2·pleats), pleat_depth — их глубина.
        top — Piece лифа: верх юбки совпадёт с его кромкой bottom (платье одной деталью).
        Кромки: waist, hem. Юбка нигде не ближе к телу, чем отступ слоя: бёдра раздвигают её сами."""
        B, lm = self.B, self.B.lm
        nu = cols or self.cols
        if pleats and nu % (2 * pleats):
            raise ValueError(f"skirt: cols={nu} должно делиться на 2·pleats={2 * pleats}")
        zw = self.z(waist) if top is None else float(np.mean(top.edges["bottom"][:, 2]))
        fl = flare if flare is not None else dict(straight=10.0, a=0.30 * length, bell=0.42 * length,
                                                  circle=0.75 * length)[kind]
        f = dict(straight=lambda s: s, a=lambda s: s, bell=lambda s: math.sin(math.pi / 2 * s) ** 0.75,
                 circle=lambda s: s ** 0.9)[kind]
        sp = self._rows(length, row_step, [(0.0, 0.08, 1.5)])
        zs = zw - length * sp
        o = (B.center_x(zw), 0.0)
        gp = self.gap(layer, t) + ease
        th = np.arange(nu) * 2 * math.pi / nu
        dirs = np.stack([np.cos(th), -np.sin(th)], axis=1)          # обход для сетки сверху вниз
        rb = np.zeros((nu, len(zs)))
        for j, z in enumerate(zs):
            zz = max(z, lm["knee"] * 0.5)
            te = 1.0 if zz < lm["crotch"] + 40 else 0.5
            rb[:, j] = B.ring((o[0], o[1], zz), (0, 0, -1), (1, 0, 0), nu, ("torso", "leg_L", "leg_R"), "far", te, 1.0)[1]
        rw = rb[:, 0] + gp
        if top is not None:
            tr = np.asarray(top.edges["bottom"], float)
            rw = np.linalg.norm(tr[:, :2] - np.array(o), axis=1)
        r = np.zeros_like(rb)
        for j, s in enumerate(sp):
            des = rw + fl * f(s)
            need = rb[:, j] + gp
            k = 10.0
            r[:, j] = des + k * np.log1p(np.exp(np.clip((need - des) / k, -30, 30)))      # мягкий максимум
            r[:, j] = _smooth_circular(r[:, j], 1.2)
            r[:, j] = np.maximum(r[:, j], need)
            if pleats:
                saw = np.abs(((th * pleats / (2 * math.pi)) % 1.0) * 2 - 1)               # 1…0…1 на складку
                r[:, j] += pleat_depth * (0.5 - saw) * 2 * float(smoothstep((s - 0.08) / 0.5))
        G = np.stack([np.stack([o[0] + r[:, j] * dirs[:, 0], o[1] + r[:, j] * dirs[:, 1], np.full(nu, z)], axis=1)
                      for j, z in enumerate(zs)], axis=1)
        if top is not None:                                          # верх юбки = низ лифа (общий ряд)
            d0 = tr - G[:, 0]
            for k in range(min(4, G.shape[1])):
                G[:, k] += d0 * (1 - smoothstep(k / 3.0))
        G = B.push_out(G, LAYER_GAP[layer] + t - 0.3)
        if top is not None:
            G[:, 0] = tr
        p = self._outward(Patch(G, closed_u=True, name=name))
        pc = Piece([p], t, dict(waist=p.G[:, 0], hem=p.G[:, -1]), name=name)
        pc.layer = layer
        pc.regions = ("torso",)                      # юбка берёт веса только с туловища: ноги её не растягивают
        pc.kind, pc.z_top, pc.z_hem = "skirt", float(zw), float(zw - length)
        # Динамика подола по умолчанию: цепочки сидят на тазе и начинаются у линии бёдер — выше юбка идёт
        # за телом (пояс гнётся вместе с талией), ниже — за костями с пружиной. Радиус столкновения большой:
        # цепочка между бёдрами ложится на них, а не проваливается.
        # Коллайдеры подола — только ноги и таз: капсула туловища при наклоне вперёд приходит сверху и
        # толкала бы подол вверх, в жилет.
        pc.dyn_defaults = dict(parent="hips", v0=float(np.clip((zw - lm["hips"]) * 0.4 / length, 0.08, 0.5)),
                               radius=30.0, chains=12, bones=4, follow=0.9,
                               colliders=("thigh_L", "thigh_R", "shin_L", "shin_R", "pelvis"))
        return pc

    # ------------------------------------------------------------ низ: брюки, шорты, леггинсы
    def leg_profile(self, spec):
        """Отступ штанины по параметру ноги: число, функция t или {"top"|"thigh"|"knee"|"calf"|"ankle": мм}
        (зоны: тазобедренный сустав, середина бедра, колено, середина голени, щиколотка)."""
        if callable(spec) or np.isscalar(spec):
            f = spec if callable(spec) else (lambda t: float(spec))
        else:
            kt = self.B.lm["knee_t"]
            pos = dict(top=0.0, thigh=kt * 0.5, knee=kt, calf=kt + (1 - kt) * 0.5, ankle=1.0)
            pts = sorted((pos[k], float(v)) for k, v in spec.items())
            from .kit import mono
            f = (lambda t: mono(pts, t)) if len(pts) > 1 else (lambda t: pts[0][1])
        return f

    def pants(self, waist="waist", length=1.0, layer=1, ease=1.0, leg_ease=None, flare=0.0, t=1.0, cols=None,
              row_step=None, name="pants", leg_around=None, leg_tent=0.0, leg_smooth=0.0, elastic=False, crease=12.0):
        """Брюки, шорты, леггинсы: труба таза от талии до паха, шаговый мостик и две штанины вдоль ног
        до параметра length (0.2 — шорты, lm["knee_t"] — до колена, 0.97 — до щиколотки).
        ease — свобода таза: число или {ориентир: мм} ({"waist": 0.5, "hips": 6} — резинка на талии, свободно
        на бёдрах). leg_ease — свобода штанины: число, функция t или по зонам {"thigh": 14, "knee": 22,
        "ankle": 4} (свободно на колене, уже к щиколотке). leg_around — добавка по сторонам ноги
        {"front": мм, "back": мм, "out": мм, "in": мм}; leg_tent — натяжение через впадины (свободная штанина
        не повторяет колено и икру), leg_smooth — сглаживание вдоль штанины; flare — расклёш к низу, мм.
        elastic=True — пояс на резинке: auto_folds добавит присборку под поясом. crease — отступ, мм, не больше
        которого ткань отходит от тела под коленом и спереди у паховой складки (там линейный скиннинг сминает
        сгиб, и лишняя свобода проваливается в тело в приседе и сидя); None — без ограничения.
        Кромки: waist, end_L, end_R."""
        B, lm = self.B, self.B.lm
        nu = cols or self.cols
        if nu % 4:
            raise ValueError("pants: cols должно быть кратно 4")
        zw, zc = self.z(waist), lm["crotch"] + 22.0
        e = self.profile(ease)
        offz = lambda z: self.gap(layer, t) + e(z)
        dense = [((zw - lm["hips"]) / (zw - zc), 0.12, 1.4)]
        zs = zw + (zc - zw) * self._rows(zw - zc, row_step, dense)
        G = B.torso_grid(zs, nu, offset=offz, tent=0.35, smooth=1.0)
        G = B.push_out(G, np.array([[offz(z) for z in zs]] * nu) - 0.3)
        ring = G[:, -1]
        off = offz(zc)
        # шаговый мостик: от середины переда под пахом к середине спины, в плоскости y = 0
        nc = max(4, int(round(nu * 0.17)) // 2 * 2)
        x0 = B.center_x(zc)
        ph = np.linspace(0, math.pi, 41)
        Pb, rbr = B.ring((x0, 0.0, zc), (0, -1, 0), (-1, 0, 0), thetas=ph, mode="near", regions=("torso", "leg_L", "leg_R"))
        rbr = np.minimum(rbr, np.median(rbr) * 1.6) + off
        Pb = np.stack([x0 - rbr * np.cos(ph), np.zeros_like(ph), zc - rbr * np.sin(ph)], axis=1)
        Pb[0], Pb[-1] = ring[nu // 2], ring[0]
        bridge = resample_open(Pb, nc + 1)
        bridge[:, 1] = 0.0
        y_first = ring[nu // 4, 1]
        sideA, sideB = ("R", "L") if y_first > 0 else ("L", "R")
        loopA = np.vstack([ring[0: nu // 2 + 1], bridge[1:-1]])                      # спина → бок A → перёд → мостик
        loopB = np.vstack([ring[nu // 2:], ring[:1], bridge[::-1][1:-1]])
        lp = self.leg_profile(ease if leg_ease is None and np.isscalar(ease) else (leg_ease if leg_ease is not None else 1.0))
        leg_off = lambda tt: self.gap(layer, t) + lp(tt) + flare * max(0.0, (tt - lm["knee_t"]) / (1 - lm["knee_t"])) ** 1.5
        leg_off.by_t = True
        patches = [self._outward(Patch(G, closed_u=True, name=name + "_hip"))]
        edges, joints = dict(waist=G[:, 0]), []
        for side, loop in ((sideA, loopA), (sideB, loopB)):
            kt = lm["knee_t"]
            caps = [] if crease is None else [(kt - 0.12, kt + 0.14, "back", crease), (0.0, 0.16, "front", crease)]
            p, jn, _ = self._limb_tube(f"leg_{side}", loop, length, leg_off, row_step, name=f"{name}_leg_{side}", blend=5,
                                       around=leg_around, tent=leg_tent, smooth_v=leg_smooth, caps=caps)
            patches.append(p)
            joints += jn
            edges["end_" + side] = p.G[:, -1]
        if zw > lm["waist"] - 5:
            joints.append(("бёдра", (B.center_x(lm["hips"]), 0.0, lm["hips"]), (0, 0, 1), 35.0, 300.0))
        pc = Piece(patches, t, edges, joints=joints, name=name)
        pc.layer, pc.kind = layer, "pants"
        pc.legs = {"L": "leg_L", "R": "leg_R"}
        pc.length, pc.waist_z, pc.elastic, pc.cols = length, zw, elastic, nu
        return pc

    # ------------------------------------------------------------ полосы вдоль кромок
    def band(self, loop, profile, closed=True, up=(0, 0, 1), t=1.2, wave=None, name="band", taper=0, fit=None,
             fit_from=0):
        """Полоса вдоль кромки: воротник, манжета, оборка, подгиб. loop — точки кромки (n, 3) из
        Piece.edges; profile — сечение полосы [(наружу, вверх), ...] в мм от кромки; closed — кромка
        замкнута. up — куда «вверх» у сечения (для манжеты — вдоль руки). wave=(амплитуда, число волн) —
        волна по краю (оборка, рюш). taper — на скольких точках у концов открытой кромки полоса сходит на нет."""
        L = np.asarray(loop, float)
        # узкая полоса (окантовка) на редкой кромке даёт вытянутые квады: кромка сгущается под шаг поперёк
        pr_ = np.asarray(profile, float)
        across = np.linalg.norm(np.diff(pr_, axis=0), axis=1).mean() if len(pr_) > 1 else 10.0
        along = max(3.0, across * 3.5)
        seg = np.linalg.norm(np.diff(np.vstack([L, L[:1]]) if closed else L, axis=0), axis=1)
        if seg.max() > along * 1.4 or seg.min() < 1e-6:
            L = smooth_line(L, closed, step=along)
        n = len(L)
        if closed:
            T = np.roll(L, -1, axis=0) - np.roll(L, 1, axis=0)
        else:
            T = np.gradient(L, axis=0)
        T /= np.maximum(np.linalg.norm(T, axis=1, keepdims=True), 1e-12)
        if up is None:                                             # «вверх» — по нормали плоскости кромки
            c = L.mean(axis=0)
            _, _, vt = np.linalg.svd(L - c)
            up = vt[2]
        upa = np.asarray(up, float)
        if upa.ndim == 2:                                          # своё направление в каждой точке кромки
            if len(upa) != len(L):                                 # кромка пересэмплирована — ближайшие точки
                from scipy.spatial import cKDTree
                upa = upa[cKDTree(np.asarray(loop, float)).query(L)[1]]
            U = upa.copy()
        else:
            U = np.broadcast_to(upa, (n, 3)).copy()
        U -= T * (U * T).sum(axis=1, keepdims=True)
        U /= np.maximum(np.linalg.norm(U, axis=1, keepdims=True), 1e-12)
        O = np.cross(T, U)
        h = self.B.closest(L)
        sg = np.sign((O * (L - h["point"])).sum(axis=1).sum()) or 1.0      # «наружу» — от тела
        O = O * sg
        pr = np.asarray(profile, float)
        k = np.ones(n)
        if taper and not closed:
            k = np.minimum(np.minimum(np.arange(n), np.arange(n)[::-1]) / float(taper), 1.0)
            k = smoothstep(k) * 0.92 + 0.08
        G = L[None] + pr[:, :1, None] * (O * k[:, None])[None] + pr[:, 1:, None] * (U * k[:, None])[None]
        if wave:
            amp, cnt = wave
            s = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(L, axis=0), axis=1))])
            s = s / (s[-1] + (np.linalg.norm(L[0] - L[-1]) if closed else 0.0))
            w = np.sin(2 * math.pi * cnt * s)
            fr = np.linspace(0, 1, len(pr)) ** 1.3
            G = G + (amp * fr)[:, None, None] * w[None, :, None] * O[None]
        if fit is not None:                                        # полоса не входит в тело: зазор fit мм
            cl = np.full(G.shape[:2], float(fit))
            cl[: fit_from] = -1e9                                  # ряды у кромки не трогаем: они сидят на вещи
            G = self.B.push_out(G, cl, cells=False)
        p = self._outward(Patch(G, closed_v=closed, name=name))
        return Piece([p], t, dict(edge=p.G[-1] if p.G.shape[0] else None, outer=G[-1]), name=name)

    def _stand(self, loop, closed, height, t, name, front_drop=0.35, rows=4, stand_off=4.5, seat=True):
        """Воротник-стойка: ровное кольцо вокруг оси шеи. Низ лежит на вырезе, верх — гладкая плоская кромка;
        радиус идёт от выреза к шее с постоянным зазором, спереди стойка ниже (front_drop — доля высоты),
        чтобы не упираться в подбородок. Форма считается по кольцам шеи, а не выталкиванием точек из тела:
        выталкивание по точкам мяло стойку и вытягивало её вверх под подбородком."""
        B = self.B
        # seat: низ стойки — точно по кромке выреза (те же точки, что у лифа): ткань лифа входит в стойку
        # без щели и нахлёста. Без seat кромка сглаживается и стойка садится поверх выреза.
        L = np.asarray(loop, float) if seat else smooth_line(loop, closed, step=10.0)
        a0, b0 = B.joint("neck"), B.joint("head")
        ax = (b0 - a0) / np.linalg.norm(b0 - a0)
        ex = np.array([1.0, 0.0, 0.0]) - ax * ax[0]
        ex /= np.linalg.norm(ex)
        ey = np.cross(ax, ex)
        rel = L - a0
        h0 = rel @ ax
        rad = rel - h0[:, None] * ax
        th = np.arctan2(rad @ ey, rad @ ex)
        r0 = np.linalg.norm(rad, axis=1)

        def sm(v, sigma):
            if closed:
                return _smooth_circular(v, sigma)
            k = int(math.ceil(sigma * 3))
            w = np.exp(-0.5 * (np.arange(-k, k + 1) / sigma) ** 2)
            return np.convolve(np.pad(v, k, mode="edge"), w / w.sum(), mode="valid")
        fw = ((1 - np.cos(th)) / 2) ** 1.5                           # 0 — спина, 1 — середина переда
        hk = height * (1 - front_drop * fw)
        # верхняя кромка — плоская: высота как первая гармоника угла
        A = np.stack([np.ones_like(th), np.cos(th), np.sin(th)], axis=1)
        top_h = A @ np.linalg.lstsq(A, h0 + hk, rcond=None)[0]
        na = 48
        hs = np.linspace(h0.min() - 6.0, top_h.max() + 6.0, 7)
        R = np.array([B.ring(a0 + ax * h, ax, ex, na, ("torso", "head"), "far", 1.0, 2.0)[1] for h in hs])

        def r_body(theta, h):
            fa = (theta % (2 * math.pi)) / (2 * math.pi) * na
            i0 = np.floor(fa).astype(int) % na
            fr = fa - np.floor(fa)
            fh = np.clip((h - hs[0]) / (hs[1] - hs[0]), 0, len(hs) - 1.001)
            j0 = np.floor(fh).astype(int)
            fj = fh - j0
            ra = R[j0, i0] * (1 - fr) + R[j0, (i0 + 1) % na] * fr
            rb = R[j0 + 1, i0] * (1 - fr) + R[j0 + 1, (i0 + 1) % na] * fr
            return ra * (1 - fj) + rb * fj
        gapc = LAYER_GAP[1] + t + stand_off                     # стойка отстоит от шеи, а не облегает её
        rings = []
        for i in range(rows + 1):
            f = i / rows
            if seat and i == 0:
                rings.append(L.copy())
                continue
            drop, base = (0.0, r0) if seat else (4.0, r0 + 2.2)   # без seat низ стойки перекрывает кромку выреза
            h = (h0 - drop) + (top_h - h0 + drop) * f
            need = r_body(th, h) + gapc
            r = base + (need - base) * float(smoothstep(min(1.0, f / 0.6)))
            r = sm(np.maximum(r, need), 1.0 if seat else 1.5)
            rings.append(a0 + ax[None] * h[:, None] + r[:, None] * (np.cos(th)[:, None] * ex + np.sin(th)[:, None] * ey))
        G = np.stack(rings, axis=0)
        cl = np.full(G.shape[:2], -1e9)
        cl[1 if seat else 0:2] = LAYER_GAP[1] + t                   # только низ: у основания шеи плечо поднимается круто
        G = B.push_out(G, cl, cells=False)
        p = self._outward(Patch(G, closed_v=closed, name=name))
        return Piece([p], t, dict(outer=rings[-1]), name=name)

    def collar(self, top, kind="stand", height=28.0, width=None, t=1.2, name="collar", front_drop=0.35):
        """Воротник по вырезу лифа: "stand" — стойка (ровное кольцо вокруг шеи; front_drop — насколько она
        ниже спереди, в долях высоты), "turndown" — отложной (стойка + отлёт шириной width),
        "flat" — плоский (лежит на плечах), "ruffle" — оборка по вырезу."""
        loop, closed = top.edges["neck"], top.edges.get("neck_closed", True)
        if kind == "stand":
            pc = self._stand(loop, closed, height, t, name, front_drop)
            pc.layer = getattr(top, "layer", 1) + 1
            return pc
        loop = smooth_line(loop, closed, step=11.0)
        w = width or height * 1.4
        prof = dict(
            turndown=[(0.8, -2.0), (-1.5, height * 0.5), (-2.0, height * 0.85), (1.5, height * 1.0),
                      (w * 0.5, height * 0.62), (w * 0.85, height * 0.1), (w, -height * 0.3)],
            flat=[(0.0, 1.5), (w * 0.35, 3.5), (w * 0.7, 2.5), (w, 0.5)],
            ruffle=[(0.0, 1.0), (w * 0.3, 5.0), (w * 0.65, 6.0), (w, 3.0)])[kind]
        fit = float(self.B.closest(loop)["dist"].max()) + t + 0.8        # воротник лежит поверх лифа, не в нём
        pc = self.band(loop, prof, closed=closed, t=t, name=name, wave=(w * 0.16, max(6, len(loop) // 5)) if kind == "ruffle" else None,
                       taper=0 if closed else 5, fit=fit, fit_from=len(prof) // 2)
        pc.layer = getattr(top, "layer", 1) + 1
        return pc

    def cuff(self, piece, width=30.0, flare=3.0, t=1.4, edge="end", kind="band", name=None):
        """Манжета по кромке рукава или штанины: "band" — лента поверх края, "turnback" — отворот,
        "ruffle" — оборка наружу."""
        loop = piece.edges[edge]
        limb = getattr(piece, "limb", None) or {"end_L": "leg_L", "end_R": "leg_R"}.get(edge)
        if limb is not None:
            J = self.B.limb_axis(limb)
            up = (J[1] - J[2]) / np.linalg.norm(J[1] - J[2])       # к корню конечности
        else:
            up = np.array([0.0, 0.0, 1.0])
        prof = dict(band=[(1.2, 6.0), (2.2 + flare * 0.3, 0.0), (2.4 + flare * 0.6, -width * 0.5), (2.0 + flare, -width)],
                    turnback=[(1.5, -width * 0.6), (3.0, -width), (5.0 + flare, -width * 0.5), (5.5 + flare, 2.0)],
                    ruffle=[(0.5, 4.0), (4.0, -width * 0.35), (9.0, -width * 0.7), (16.0, -width)])[kind]
        pc = self.band(loop, prof, closed=True, up=up, t=t, name=name or f"cuff_{piece.name}",
                       wave=(width * 0.18, max(5, len(loop) // 4)) if kind == "ruffle" else None,
                       fit=LAYER_GAP[min(getattr(piece, "layer", 1) + 1, 4)] + t)
        pc.layer = getattr(piece, "layer", 1) + 1
        return pc

    def hem_band(self, piece, width=24.0, edge="hem", out=2.0, t=1.4, kind="band", name=None):
        """Полоса по низу юбки или лифа: "band" — подгиб/кайма, "ruffle" — оборка вниз."""
        loop = piece.edges[edge]
        prof = dict(band=[(out, 3.0), (out + 0.5, -width * 0.5), (out, -width)],
                    ruffle=[(0.5, 3.0), (3.0, -width * 0.35), (7.0, -width * 0.7), (12.0, -width)])[kind]
        pc = self.band(loop, prof, closed=True, t=t, name=name or f"hem_{piece.name}",
                       wave=(width * 0.22, max(8, len(loop) // 4)) if kind == "ruffle" else None)
        pc.layer = getattr(piece, "layer", 1)
        return pc

    def piping(self, loop, r=2.2, closed=True, name="piping", sides=6):
        """Кант: круглый шнур вдоль кромки (замкнутое тело)."""
        a = np.arange(sides) * 2 * math.pi / sides
        L = np.asarray(loop, float)
        m = quad_sweep(np.stack([r * np.cos(a), r * np.sin(a)], axis=1), L, up=(0, 0, 1) if closed else None,
                       closed_path=closed, name=name)
        return Piece(solid=m, name=name)

    # ------------------------------------------------------------ пояс, пряжка, пуговицы, шнуровка
    def waist_ring(self, z="waist", layer=3, extra=0.0, n=None, tent=0.6):
        """Кольцо вокруг туловища на высоте z с отступом слоя (ось пояса, линия для пуговиц)."""
        return self.B.torso_ring(self.z(z), n or self.cols, LAYER_GAP[layer] + extra, tent, 1.5, down=True)

    def push_over(self, G, pieces, clear=2.0, iters=3):
        """Отодвинуть точки сетки G от наружной поверхности вещей pieces до зазора clear мм: накладная
        деталь (лента, бант, карман) ложится на одежду под ней, а не на тело."""
        from .body import Surface
        Vs, Ts, n0 = [], [], 0
        for pc in pieces:
            for mm in ([QuadMesh.from_patches(pc.patches)] if pc.patches else []) + ([pc.solid] if pc.solid is not None else []):
                Vs.append(mm.V)
                Ts.append(mm.triangles() + n0)
                n0 += len(mm.V)
        S = Surface(np.vstack(Vs), np.vstack(Ts))
        G = np.array(G, float)
        P = G.reshape(-1, 3)
        for _ in range(iters):
            h = S.closest(P, k=8)
            lack = clear - h["dist"]
            mk = (lack > 1e-3) & (h["dist"] > -40.0)
            if not mk.any():
                break
            P[mk] += h["normal"][mk] * lack[mk][:, None]
        return P.reshape(G.shape)

    def over_radius(self, pieces, z, n, origin):
        """Радиус наружной поверхности вещей pieces на высоте z по n лучам из оси origin (x, y) —
        чтобы пояс и накладные детали садились на одежду под ними, а не на тело. NaN — луч не попал."""
        from .body import plane_segments, _ray_segments
        th = np.arange(n) * 2 * math.pi / n
        dirs = np.stack([np.cos(th), -np.sin(th)], axis=1)
        A, Bq = [], []
        for pc in pieces:
            for P in pc.patches:
                m = QuadMesh.from_patches([P])
                S = plane_segments(m.V, m.triangles(), (0, 0, z), (0, 0, 1))
                if len(S):
                    A.append(S[:, 0, :2] - np.array(origin))
                    Bq.append(S[:, 1, :2] - np.array(origin))
        if not A:
            return np.full(n, np.nan)
        return _ray_segments(dirs, np.vstack(A), np.vstack(Bq), "far")

    def belt(self, z="waist", width=28.0, thick=3.0, layer=3, over=(), tent=0.6, rows=3, name="belt", gap=1.2):
        """Пояс: лента шириной width и толщиной thick вокруг туловища на высоте z. over — блоки одежды под
        поясом (юбка, лиф): пояс ложится на них с зазором, а не режет их. Кромка front — точка для пряжки."""
        B = self.B
        zc = self.z(z)
        nu = self.cols
        o = (B.center_x(zc), 0.0)
        th = np.arange(nu) * 2 * math.pi / nu
        dirs = np.stack([np.cos(th), -np.sin(th)], axis=1)
        rings = []
        for zz in np.linspace(zc + width / 2, zc - width / 2, rows):
            r = B.ring((o[0], o[1], zz), (0, 0, -1), (1, 0, 0), nu, ("torso", "leg_L", "leg_R"), "far", tent, 1.5)[1]
            r = r + LAYER_GAP[layer]
            if over:
                ro = self.over_radius(over, zz, nu, o)
                r = np.where(np.isfinite(ro), np.maximum(r, ro + gap), r)      # gap — зазор над вещами под поясом
            r = _smooth_circular(r, 1.0) + thick
            rings.append(np.stack([o[0] + r * dirs[:, 0], o[1] + r * dirs[:, 1], np.full(nu, zz)], axis=1))
        G = np.stack(rings, axis=1)
        p = self._outward(Patch(G, closed_u=True, name=name))
        mid = G[:, rows // 2]
        i = int(mid[:, 0].argmin())
        up = G[i, 0] - G[i, -1]                                   # вдоль пояса снизу вверх (с его наклоном)
        up /= np.linalg.norm(up)
        tg = mid[(i + 1) % nu] - mid[i - 1]
        nrm = np.cross(tg, up)
        nrm /= np.linalg.norm(nrm)
        if nrm[0] > 0:                                             # наружу: перёд смотрит в −X
            nrm = -nrm
        pc = Piece([p], thick, dict(ring=mid, front=mid[i], front_normal=nrm, front_up=up), name=name)
        pc.layer = layer
        return pc

    def front_point(self, z, layer=2, extra=0.0, y=0.0):
        """Точка на переде туловища (на отступе слоя) на высоте z, со смещением y от середины."""
        ring = self.B.torso_ring(self.z(z), 96, LAYER_GAP[layer] + extra, 0.5, 1.0)
        front = ring[ring[:, 0] < self.B.center_x(self.z(z))]
        return front[np.abs(front[:, 1] - y).argmin()].copy()

    def buckle(self, center, w=44.0, h=36.0, d=5.0, bar=5.0, normal=(-1, 0, 0), up=(0, 0, 1)):
        """Пряжка-рамка — жёсткая деталь (тело build123d, mesh="cad"): рамка w × h толщиной d.
        center — точка на наружной поверхности пояса, normal — наружу от пояса, up — вдоль пояса вверх:
        пряжка ложится на пояс с его наклоном (belt.edges["front"], ["front_normal"], ["front_up"]),
        а не стоит вертикально. Привязывается к одной кости: O.M.add(..., bind="hips")."""
        from build123d import Location, Plane
        from .kit import box, cut
        frame = cut(box(-d, -w / 2, -h / 2, 1.0, w / 2, h / 2, r=3),
                    box(-d - 1, -w / 2 + bar, -h / 2 + bar, 2.0, w / 2 - bar, h / 2 - bar, r=1.5))
        prong = box(-d - 0.5, -1.6, -h / 2 + 1, -d + 2.0, 1.6, h / 2 - 1)
        n = np.asarray(normal, float)
        n /= np.linalg.norm(n)
        u = np.asarray(up, float)
        u = u - n * (u @ n)
        u /= np.linalg.norm(u)
        loc = Location(Plane(origin=tuple(float(c) for c in center), x_dir=tuple(-n), z_dir=tuple(u)))
        return (frame + prong).moved(loc)

    def button(self, center, normal=(-1, 0, 0), r=7.0, h=3.0, name="button", n=12):
        """Пуговица — диск (тело вращения квадами) с осью по normal."""
        prof = [(0, 0), (r * 0.7, 0), (r, h * 0.4), (r * 0.8, h), (0, h)]
        m = revolve_quad(prof, center, axis=normal, n=n, name=name)
        return Piece(solid=m, name=name)

    def buttons(self, z_top, z_bottom, count, layer=2, extra=1.0, y=0.0, r=7.0, name="button"):
        """Ряд пуговиц по переду от высоты z_top до z_bottom."""
        out = None
        for k, z in enumerate(np.linspace(self.z(z_top), self.z(z_bottom), count)):
            p = self.front_point(z, layer, extra, y)
            h = self.B.closest(p[None])
            nrm = h["normal"][0]
            b = self.button(p, nrm, r, name=f"{name}{k}").solid
            out = b if out is None else out.merged(b)
        return Piece(solid=out, name=name)

    def lacing(self, z_top, z_bottom, count, half_width=22.0, layer=2, extra=1.5, r=1.6, back=False, name="lace"):
        """Шнуровка крест-накрест между двумя рядами точек по переду (или по спине)."""
        zs = np.linspace(self.z(z_top), self.z(z_bottom), count)
        out = None
        a = np.arange(6) * 2 * math.pi / 6
        prof = np.stack([r * np.cos(a), r * np.sin(a)], axis=1)

        def pt(z, y):
            if back:
                ring = self.B.torso_ring(z, 96, LAYER_GAP[layer] + extra, 0.5, 1.0)
                bk = ring[ring[:, 0] > self.B.center_x(z)]
                return bk[np.abs(bk[:, 1] - y).argmin()].copy()
            return self.front_point(z, layer, extra, y)
        for k in range(count - 1):
            for s in (1.0, -1.0):
                p0, p1 = pt(zs[k], s * half_width), pt(zs[k + 1], -s * half_width)
                mid = (p0 + p1) / 2
                hmid = self.B.closest(mid[None])
                mid = mid + hmid["normal"][0] * (r * (2.2 if s > 0 else 0.6))         # шнуры не пересекаются
                seg = quad_sweep(prof, resample_open(np.array([p0, mid, p1]), 5), name=f"{name}{k}")
                out = seg if out is None else out.merged(seg)
        return Piece(solid=out, name=name)

    # ------------------------------------------------------------ ленты и банты
    def ribbon(self, path, width=22.0, t=0.8, normal=None, taper=0.75, rows=None, name="ribbon", clear=9.0, over=()):
        """Лента вдоль ломаной path (n, 3): полоса шириной width. normal — куда смотрит лицевая сторона
        (по умолчанию от тела); taper — ширина на конце относительно начала. Сетка идёт вдоль ленты (v),
        поэтому динамика задаётся одной цепочкой: dynamics=dict(preset="soft", chains=1, bones=3)."""
        P = resample_open(np.asarray(path, float), rows or max(4, int(np.linalg.norm(np.diff(path, axis=0), axis=1).sum() / 18) + 1))
        n = len(P)
        T = np.gradient(P, axis=0)
        T /= np.maximum(np.linalg.norm(T, axis=1, keepdims=True), 1e-12)
        if normal is None:
            h = self.B.closest(P)
            N = P - h["point"]
        else:
            N = np.broadcast_to(np.asarray(normal, float), (n, 3)).copy()
        N -= T * (N * T).sum(axis=1, keepdims=True)
        N /= np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-12)
        S = np.cross(T, N)
        wd = width / 2 * np.linspace(1.0, taper, n)
        G = np.stack([P - S * wd[:, None], P, P + S * wd[:, None]], axis=0)
        if clear is not None:                                      # лента не входит в тело: зазор clear мм
            G = self.B.push_out(G, clear + t, cells=False)
        if over:                                                   # и не входит в одежду под ней
            G = self.push_over(G, over, clear=t + 1.5)
        p = Patch(G, name=name)
        if (p.normals()[1, n // 2] @ N[n // 2]) < 0:
            p = Patch(G[::-1], name=name)
        return Piece([p], t, dict(end=G[:, -1]), name=name)

    def bow(self, center, normal=(-1, 0, 0), size=90.0, width=None, t=1.0, tails=110.0, droop=0.25, name="bow", over=()):
        """Бант: две петли и узел (жёсткая часть) и два хвоста-ленты (для динамики). normal — куда смотрит
        бант. Возвращает (Piece петель и узла, [Piece хвост, Piece хвост]): хвосты добавляются отдельной
        деталью с dynamics, петли — с bind к кости."""
        c = np.asarray(center, float)
        nrm = np.asarray(normal, float)
        nrm /= np.linalg.norm(nrm)
        upv = np.array([0.0, 0.0, 1.0])
        side = np.cross(upv, nrm)
        side /= np.linalg.norm(side)
        upv = np.cross(nrm, side)
        w = width or size * 0.42
        loops = []
        for sg in (1.0, -1.0):
            a = np.linspace(0, 2 * math.pi, 14, endpoint=False)
            # петля — «капля» в плоскости (side, normal): от узла наружу и обратно
            rx = 3.0 + size * 0.25 * (1 - np.cos(a))               # от узла наружу и обратно
            ry = size * 0.13 * (1 + np.sin(a)) + 2.0                # петля выпуклая только наружу от тела
            path = c + sg * side[None] * rx[:, None] + nrm[None] * ry[:, None] - upv[None] * (droop * rx[:, None] * 0.35)
            prof = np.stack([np.zeros(3), np.array([-w / 2, 0.0, w / 2])], axis=1)
            T = np.roll(path, -1, axis=0) - np.roll(path, 1, axis=0)
            T /= np.linalg.norm(T, axis=1, keepdims=True)
            wscale = 0.55 + 0.45 * np.sin(a / 2)                   # у узла петля уже
            G = np.stack([path + upv[None] * (v * wscale)[:, None] for v in prof[:, 1]], axis=0)
            loops.append(Patch(G, closed_v=True, name=f"{name}_loop{'L' if sg > 0 else 'R'}"))
        knot = revolve_quad([(0, -1), (0.7, -0.75), (1, 0), (0.7, 0.75), (0, 1)], (0, 0, 0), axis=(0, 0, 1), n=10,
                            name=name + "_knot")
        knot = knot.transformed(lambda P: c + nrm * 4.0 + P[:, :1] * side * w * 0.26 + P[:, 1:2] * nrm * w * 0.24
                                + P[:, 2:] * upv * w * 0.34)
        _fix_outward(knot)
        body_ = QuadMesh.from_patches(loops).solidify(t)
        pc = Piece(solid=body_.merged(knot), name=name)
        tl = []
        for sg in (1.0, -1.0):
            p0 = c + nrm * 2.0 - upv * w * 0.2 + sg * side * w * 0.22
            p1 = p0 - upv * tails * 0.55 + sg * side * tails * 0.28 + nrm * 4.0
            p2 = p0 - upv * tails + sg * side * tails * 0.36 + nrm * 2.0
            tl.append(self.ribbon(np.array([p0, p1, p2]), width=w * 0.8, t=t, normal=nrm, taper=1.15,
                                  name=f"{name}_tail{'L' if sg > 0 else 'R'}", over=over))
        return pc, tl

    # ------------------------------------------------------------ обувь
    def shoe(self, side, shaft=0.9, layer=2, ease=3.0, t=2.0, sole=10.0, welt=3.0, toe=0.30, toe_height=32.0,
             cols=24, name=None, rand=8.0, fit="rigid", flex=24.0, ankle_room=6.0, shaft_bend=None):
        """Обувь — ботинок или сапог на КОЛОДКЕ: форма стопы у обуви своя, фиксированная, а не обтяжка стопы
        (обтяжка повторяла пальцы и свод). Голенище (от параметра ноги shaft: 0.9 — чуть выше щиколотки,
        0.7 — до середины голени) и изгиб у щиколотки идут по ноге; от подъёма до носка — колодка:
        гладкие сечения с плоским низом, ширина и высота — огибающая стопы плюс ease, носок закруглён на
        последней доле длины toe, высота носка не меньше toe_height. Отдельным телом — подошва-чаша толщиной
        sole с рантом welt и бортиком высотой rand, который поднимается по стенке верха (лоскут «<имя>_sole»:
        ему можно дать свой цвет узором kind="fill").
        Подошва уходит ниже пола на sole мм: в игре корень персонажа поднимается на эту величину.
        Верх открыт, толщина верха t.
        Привязка (fit): "rigid" (по умолчанию) — обувь жёсткая модель, как в играх: стопа целиком на кости стопы,
        носок за линией пальцев — на кости пальцев с плавным сгибом шириной flex мм (flex=None — подошва не
        гнётся), голенище выше щиколотки — на голени (shaft_bend: True / False / None — само, если голенище
        выше щиколотки больше чем на 80 мм). Обувь не тянется по коже: форма неподвижна, только поворачивается
        с костями. Горловина шире на ankle_room мм к верхнему краю — место голени при сгибе щиколотки.
        "skin" — прежняя привязка весами ноги."""
        from .body import plane_segments
        from .mesh import _orient_like_first
        B = self.B
        name = name or f"shoe_{side}"
        limb = f"leg_{side}"
        reg = (limb,)
        mask = B.tri_mask(reg)
        ank = B.joint(f"foot_{side}")
        sg = -1.0 if side == "L" else 1.0
        fv = B.V[(B.vreg == ["torso", "head", "arm_L", "arm_R", "leg_L", "leg_R"].index(limb)) & (B.V[:, 2] < ank[2] * 0.9)]
        off = self.gap(layer, t) + ease
        x_tip = float(fv[:, 0].min()) - off - 2.0
        zb = -2.5                                                   # низ верха: чуть ниже стопы, утоплен в подошву
        zp = float(ank[2] + 28.0)
        front = fv[np.abs(fv[:, 2] - min(ank[2] * 0.85, fv[:, 2].max())) < 12.0]
        pivot = np.array([float(front[:, 0].min()) - 44.0, float(np.median(fv[:, 1])), zp])     # перед подъёмом стопы

        def ring_at(origin, n, extra=0.0):
            S = plane_segments(B.V, B.T[mask], origin, n).reshape(-1, 3)
            S = S[np.linalg.norm(S - ank, axis=1) < 260.0]
            c = S.mean(axis=0)
            c = c - n * ((c - origin) @ n)
            return B.ring(c, n, (0.0, sg, 0.0), cols, reg, "far", 1.0, 1.0, off + extra, rmax=130.0)[0]
        ptop, _ = B.limb_point(limb, shaft)
        rigid = fit == "rigid"
        rings = []
        for z in np.linspace(ptop[2], zp, max(3, int((ptop[2] - zp) / 16.0) + 2)):             # голенище
            # жёсткая обувь: голень при сгибе щиколотки ходит в горловине — к верху горловина свободнее
            ex = ankle_room * float(smoothstep((z - zp) / max(ptop[2] - zp, 1.0))) if rigid else 0.0
            rings.append(ring_at(np.array([ank[0], ank[1], z]), np.array([0.0, 0.0, -1.0]), ex))
        for ph in np.radians([22.5, 45, 67.5, 90]):                                            # изгиб: веер плоскостей
            rings.append(ring_at(pivot, np.array([-math.sin(ph), 0.0, -math.cos(ph)])))
        G = B.push_out(np.stack(rings, axis=1), off - 0.2)
        # низ пятки — плоский: кольца изгиба режут пятку наискось, и без этого она висит над подошвой клином
        G[..., 2] = np.where(G[..., 2] < 16.0, zb, G[..., 2])
        nleg = G.shape[1]
        # --- колодка: огибающая стопы по станциям от подъёма до носка
        ss = spacing(9, [(1.0, 0.2, 1.6)])[1:]
        xs = pivot[0] + (x_tip - pivot[0]) * ss
        wb, hb, yc = [], [], []
        for x in xs:
            sl = fv[np.abs(fv[:, 0] - x) < 12.0]
            if len(sl) < 4:
                wb.append(wb[-1]); hb.append(hb[-1]); yc.append(yc[-1])
                continue
            yc.append(float((sl[:, 1].max() + sl[:, 1].min()) / 2))
            wb.append(float((sl[:, 1].max() - sl[:, 1].min()) / 2))
            hb.append(float(sl[:, 2].max()))
        env = lambda v: np.convolve(np.pad(np.maximum.accumulate(np.array(v)[::-1])[::-1] * 0.5 + np.array(v) * 0.5, 2, mode="edge"),
                                    np.ones(5) / 5, mode="valid")
        wb, hb = np.maximum(env(wb), np.array(wb)), np.maximum(env(hb), np.array(hb))
        yc = np.convolve(np.pad(np.array(yc), 2, mode="edge"), np.ones(5) / 5, mode="valid")
        th = np.arange(cols) * 2 * math.pi / cols
        dy, dz = sg * np.cos(th), -sg * np.sin(th)                    # те же углы, что у колец ноги
        s0 = 1.0 - toe
        last = []
        for k, s in enumerate(ss):
            tp = 0.0 if s <= s0 else (s - s0) / toe
            w = (wb[k] + off) * math.sqrt(max(1.0 - tp ** 2.4, 0.0))
            h = max(hb[k] + off, toe_height) * math.sqrt(max(1.0 - max(0.0, (tp - 0.35) / 0.65) ** 2.2, 0.0))
            if w < 1.0 or h < 1.0:
                continue
            zc, hz = zb + (h - zb) / 2, (h - zb) / 2
            n_top, n_bot = 2.6, 5.0                                 # верх округлый, низ почти плоский
            ex_ = np.where(dz >= 0, n_top, n_bot)
            r = (np.abs(dy / w) ** ex_ + np.abs(dz / hz) ** ex_) ** (-1.0 / ex_)
            last.append(np.stack([np.full(cols, xs[k]), yc[k] + r * dy, zc + r * dz], axis=1))
        Gl = np.stack(last, axis=1)
        tip = np.array([x_tip, yc[-1], zb + min(hb[-1] + off, toe_height) * 0.3])
        G = np.concatenate([G, Gl, np.repeat(tip[None, None, :], cols, axis=0)], axis=1)   # полюс носка
        tube = self._outward(Patch(G, closed_u=True, name=name))
        upper = QuadMesh.from_patches([tube]).solidify(t)
        # линия переда (середина подъёма) от верха голенища до начала колодки — для язычка и шнуровки
        # у колец голенища и изгиба — самая передняя точка, у сечений колодки (все точки на одном X) — верхняя
        # точка кольца, крайняя по направлению «вперёд-вверх»: у колец голенища — передняя, у сечений колодки
        # (все точки на одном X) — верхняя, у наклонных колец изгиба — между ними
        fu = np.array([-1.0, 0.0, 1.0])
        front_line = np.array([tube.G[int(np.argmax(tube.G[:, k] @ fu)), k] for k in range(min(nleg + 3, tube.G.shape[1] - 1))])
        # --- подошва: отдельное замкнутое тело-чаша. Низ верха утоплен в неё, а бортик высотой rand
        # поднимается по стенке верха — подошва состыкована с верхом, а не приклеена снизу плоской плитой.
        from .mesh import _find
        low = tube.G.reshape(-1, 3)
        low = low[low[:, 2] < rand]                                   # контур верха на высоте бортика
        x0, x1 = float(low[:, 0].max()) + welt, float(low[:, 0].min()) - welt
        sx = (x0 + (x1 - x0) * spacing(15, [(0.0, 0.12, 1.8), (1.0, 0.12, 1.8)]))[1:-1]
        mid, half = np.full(len(sx), np.nan), np.full(len(sx), np.nan)
        for k, x in enumerate(sx):                                    # контур низа верха по станциям
            sl = low[np.abs(low[:, 0] - x) < 14.0]
            if len(sl) >= 3:
                mid[k], half[k] = (sl[:, 1].max() + sl[:, 1].min()) / 2, (sl[:, 1].max() - sl[:, 1].min()) / 2
        ok = np.isfinite(half)                                        # станции без точек — по соседним
        mid, half = np.interp(sx[::-1], sx[ok][::-1], mid[ok][::-1])[::-1], np.interp(sx[::-1], sx[ok][::-1], half[ok][::-1])[::-1]
        half = np.convolve(np.pad(half, 1, mode="edge"), [0.25, 0.5, 0.25], mode="valid")
        nb, zf = 6, zb - 0.7                                          # zf — дно чаши, чуть ниже низа верха
        srings = []
        for k, x in enumerate(sx):
            e = min(abs(x - x0), abs(x - x1))                         # скругление пятки и носка подошвы в плане
            W = half[k] + welt
            if e < 34.0:
                W = min(W, math.sqrt(max(e * (2 * 34.0 - e), 0.0)) + 6.0)
            W = max(W, 7.0)
            zt = zf + 0.8 + rand * float(smoothstep(min(1.0, e / 30.0)))    # бортик сходит на нет к концам
            Wi = W - min(welt + 1.0, W * 0.45)                        # внутренний край бортика — в толще стенки верха
            pts = ([(y, -sole) for y in np.linspace(-W, W, nb + 1)] + [(W, (zt - sole) / 2), (W, zt)]
                   + [(y, zf) for y in np.linspace(Wi, -Wi, nb + 1)] + [(-W, zt), (-W, (zt - sole) / 2)])
            srings.append(np.array([(x, mid[k] + y, z) for y, z in pts]))
        ns_ = len(srings[0])
        c0, c1 = srings[0].mean(axis=0), srings[-1].mean(axis=0)
        c0[0], c1[0] = x0, x1
        Gs = np.stack([np.repeat(c0[None], ns_, axis=0)] + srings + [np.repeat(c1[None], ns_, axis=0)], axis=1)
        sm_ = QuadMesh.from_patches([Patch(Gs, closed_u=True, name=name + "_sole")])
        _orient_like_first(sm_)
        _fix_outward(sm_)
        edges = []                                                    # острые рёбра: низ, верх бортика, его внутренний край
        for c in (0, nb, nb + 2, nb + 3, 2 * nb + 3, 2 * nb + 4):
            v = _find(sm_, Gs[c, 1:-1])
            edges.append(np.stack([v[:-1], v[1:]], axis=1))
        sm_.sharp = np.unique(np.sort(np.vstack(edges), axis=1), axis=0)
        pc = Piece(solid=upper.merged(sm_), edges=dict(top=tube.G[:, 0], front_line=front_line), name=name)
        pc.layer, pc.limb = layer, limb
        pc.ground, pc.kind, pc.side = sole, "shoe", side
        if rigid:
            pc.bind = self.shoe_bind(side, flex=flex, shaft_bend=(ptop[2] - ank[2] > 80.0) if shaft_bend is None else shaft_bend)
        return pc

    def shoe_bind(self, side, flex=24.0, shaft_bend=False, ankle=50.0, ankle_blend=40.0):
        """Жёсткая привязка обуви по сегментам (bp3d.rig, mode="segments"): стопа — кость стопы; носок за
        плоскостью через сустав пальцев поперёк стопы — кость пальцев (переход flex мм; None — без сгиба);
        при shaft_bend голенище выше щиколотки на ankle мм — голень (переход ankle_blend мм). Подходит и для
        своей обуви и деталей на стопе: O.add(..., bind=O.shoe_bind("L"))."""
        B = self.B
        ank = B.joint(f"foot_{side}")
        cuts = []
        if flex is not None and f"toe_{side}" in B.roles:
            tj = B.joint(f"toe_{side}")
            d = tj - ank
            d[2] = 0.0
            cuts.append(dict(bone=f"toe_{side}", point=tj.tolist(), normal=(d / max(np.linalg.norm(d), 1e-9)).tolist(),
                             blend=max(float(flex), 1.0)))
        if shaft_bend:
            cuts.append(dict(bone=f"shin_{side}", point=[float(ank[0]), float(ank[1]), float(ank[2] + ankle)],
                             normal=[0.0, 0.0, 1.0], blend=float(ankle_blend)))
        return dict(mode="segments", bone=f"foot_{side}", cuts=cuts)

    # ================================================================== складки (bp3d.folds)
    # Помощники возвращают списки Fold; их передают в add(..., folds=[...]). Кривые строятся по телу и
    # прижимаются к поверхности вещи при сборке. mode — "geo" (геометрия), "normal" (карта нормалей),
    # "mask" (маска для художника) или несколько сразу. Все складки неподвижны: вещь гнётся по костям.
    def _axes(self, side):
        d = dict(WORLD_DIRS)
        d["out"] = (0.0, -1.0 if side == "L" else 1.0, 0.0)
        d["in"] = (0.0, 1.0 if side == "L" else -1.0, 0.0)
        return {k: np.asarray(v, float) for k, v in d.items()}

    def limb_arc(self, limb, t, sector=None, n=72, tilt=0.0, phase=0.0, offset=0.0):
        """Кольцо вокруг руки или ноги при параметре t (или дуга: sector=("back", 80) — ±80° вокруг стороны
        "front" | "back" | "out" | "in"); tilt — наклон кольца, мм вдоль оси. Возвращает (точки, замкнута)."""
        B = self.B
        th = np.arange(n) * 2 * math.pi / n
        P = B.limb_ring(limb, t, n, offset, thetas=th)
        _, d = B.limb_point(limb, t)
        ex, ey = B.limb_frame(limb, t)
        dirs = np.cos(th)[:, None] * ex + np.sin(th)[:, None] * ey
        if tilt:
            P = P + d[None] * (tilt * np.sin(th + phase))[:, None]
        if sector is None:
            return P, True
        name, half = sector
        ax = self._axes(limb[-1])[name]
        c = int(np.argmax(dirs @ ax))
        h = int(round(n * half / 360.0))
        idx = [(c + k) % n for k in range(-h, h + 1)]
        return P[idx], False

    def limb_line(self, limb, t0, t1, side="out", n=24, offset=0.0):
        """Линия вдоль руки или ноги по стороне side ("front", "back", "out", "in") — шов, лампас, складка."""
        ax = self._axes(limb[-1])[side]
        out = []
        for t in np.linspace(t0, t1, n):
            P, _ = self.limb_arc(limb, t, n=48, offset=offset)
            p_, _ = self.B.limb_point(limb, t)
            out.append(P[int(np.argmax((P - p_) @ ax))])
        return np.array(out)

    def folds_accordion(self, limb, t, count=4, pitch=24.0, amp=5.0, width=12.0, sector=None, tilt=6.0, jitter=0.3,
                        mode="geo", seed=0, name="accordion"):
        """Гармошка от сжатия: count колец (или дуг по sector) вокруг конечности около параметра t с шагом
        pitch мм — локоть, колено, низ штанины над обувью, у резинки. Кольца чуть наклонены и неравны."""
        J = self.B.limb_axis(limb)
        L = np.linalg.norm(J[1] - J[0]) + np.linalg.norm(J[2] - J[1])
        rng = np.random.default_rng(seed)
        out = []
        for k in range(count):
            tk = t + (k - (count - 1) / 2) * pitch / L
            ph = rng.uniform(0, 2 * math.pi)
            P, closed = self.limb_arc(limb, tk, sector, tilt=tilt * rng.uniform(0.5, 1.0), phase=ph)
            n = len(P)
            wob = amp * (1 - jitter * rng.uniform(0, 1)) * (1 + 0.35 * jitter * np.sin(np.linspace(0, 2 * math.pi, n) * 2 + ph))
            out.append(Fold(P, amp=wob, width=width * rng.uniform(0.85, 1.15), closed=closed, taper=0.0 if closed else 0.3,
                            mode=mode, name=f"{name}{k}"))
        return out

    def folds_tension(self, start, ends, amp=4.0, width=16.0, mode="geo", taper=0.15, name="tension"):
        """Складки натяжения: прямые от точки напряжения start к точкам ends — от паха, подмышки, пуговицы,
        молнии, точки крепления. Сильнее у начала, сходят на нет к концу."""
        start = np.asarray(start, float)
        return [Fold(np.linspace(start, np.asarray(e, float), 12), amp=(amp, amp * 0.15), width=width, taper=taper,
                     mode=mode, name=f"{name}{k}") for k, e in enumerate(ends)]

    def folds_hanging(self, loop, z_bottom, count=8, amp=(1.0, 5.0), width=28.0, z_top=None, profile="pipe", mode="geo",
                      phase=0.5, name="hang"):
        """Висящие складки — вертикальные «трубы» свободной ткани от линии опоры loop (кромка: талия, плечи)
        вниз до высоты z_bottom (юбка, плащ, рукав-колокол). amp — (у опоры, внизу)."""
        L = np.asarray(loop, float)
        closed = np.linalg.norm(L[0] - L[-1]) < 1e-6 or len(L) > 8
        P = resample_closed(L, count * 8) if closed else resample_open(L, count * 8)
        out = []
        for k in range(count):
            q = P[int((k + phase) * 8) % len(P)]
            zt = q[2] if z_top is None else self.z(z_top)
            path = np.array([[q[0], q[1], z] for z in np.linspace(zt, self.z(z_bottom), 10)])
            out.append(Fold(path, amp=amp, width=width, profile=profile, taper=0.12, mode=mode, name=f"{name}{k}"))
        return out

    def folds_spiral(self, limb, t0, t1, turns=1.0, count=2, amp=3.0, width=18.0, mode="geo", name="spiral"):
        """Спиральные складки вокруг свободного рукава или штанины."""
        out = []
        for c in range(count):
            pts = []
            for k, tt in enumerate(np.linspace(t0, t1, 40)):
                P, _ = self.limb_arc(limb, tt, n=72)
                a = (c / count + turns * k / 39.0) % 1.0
                pts.append(P[int(a * 72) % 72])
            out.append(Fold(np.array(pts), amp=amp, width=width, taper=0.2, mode=mode, name=f"{name}{c}"))
        return out

    def folds_gather(self, edge, count=24, length=40.0, amp=2.5, width=8.0, direction="down", mode="geo",
                     jitter=0.3, seed=0, start=0.0, name="gather"):
        """Присборка: много коротких складок поперёк кромки edge (пояс на резинке, манжета, кокетка).
        direction — куда от кромки ("down", "up" или вектор); start — отступ начала складок от кромки, мм."""
        L = np.asarray(edge, float)
        P = resample_closed(L, count)
        dv = np.asarray(WORLD_DIRS.get(direction, direction) if isinstance(direction, str) else direction, float)
        rng = np.random.default_rng(seed)
        out = []
        for k, q in enumerate(P):
            ln = length * (1 - jitter * rng.uniform(0, 1))
            q0 = q + dv * start                                     # от кромки отступ: сама кромка ровная
            out.append(Fold(np.linspace(q0, q0 + dv * ln, 8), amp=(amp * rng.uniform(0.7, 1.0), 0.0), width=width,
                            taper=0.15, mode=mode, name=f"{name}{k}"))
        return out

    def fold_crease(self, path, amp=3.0, width=6.0, mode="geo", name="crease"):
        """Залом сложенной ткани: ступень вдоль кривой (двойной слой, отворот, лежащий капюшон)."""
        return [Fold(np.asarray(path, float), amp=amp, width=width, profile="step", taper=0.1, mode=mode, name=name)]

    def folds_pressed(self, edge_top, edge_bottom, count=12, amp=4.0, width=8.0, mode="geo", name="pleat"):
        """Заутюженные складки (плиссе, бантовые): ступени по линиям между двумя кромками."""
        A = resample_closed(np.asarray(edge_top, float), count)
        Bq = resample_closed(np.asarray(edge_bottom, float), count * 8)
        out = []
        for k, a in enumerate(A):
            b = Bq[np.argmin(np.linalg.norm(Bq[:, :2] - a[:2], axis=1))]
            out.append(Fold(np.linspace(a, b, 10), amp=amp, width=width, profile="step", taper=0.05, mode=mode,
                            name=f"{name}{k}"))
        return out

    def folds_quilt(self, patch, pitch_u=0.1, pitch_v=0.1, pattern="diamond", amp=-2.5, width=6.0, mode="geo", name="quilt"):
        """Простёжка на лоскуте patch (по имени): впадины по линиям сетки развёртки — "stripe" (полосы по v),
        "grid" (клетка), "diamond" (ромб). pitch — шаг в долях лоскута."""
        lines = []
        if pattern in ("stripe", "grid"):
            lines += [[(0.0, v), (1.0, v)] for v in np.arange(pitch_v, 1.0, pitch_v)]
        if pattern == "grid":
            lines += [[(u, 0.0), (u, 1.0)] for u in np.arange(pitch_u, 1.0, pitch_u)]
        if pattern == "diamond":
            for c in np.arange(-1.0, 2.0, pitch_u):
                for sg in (1.0, -1.0):
                    uv = [(c + sg * v * pitch_u / pitch_v, v) for v in np.linspace(0, 1, 30)]
                    uv = [(u, v) for u, v in uv if 0.0 <= u <= 1.0]
                    if len(uv) > 2:
                        lines.append(uv)
        prof = "valley" if amp < 0 else "ridge"
        return [Fold(uv=[tuple(q) for q in ln], patch=patch, amp=abs(amp), width=width, profile=prof, taper=0.0,
                     mode=mode, name=f"{name}{k}") for k, ln in enumerate(lines)]

    def seam(self, path, width=1.6, depth=0.5, stitch=(3.0,), stitch_pitch=3.5, mode=("normal", "mask"), name="seam"):
        """Шов: канавка вдоль кривой и строчка параллельно ей (stitch — смещения строчек, мм; знак — сторона)."""
        P = np.asarray(path, float)
        out = [Fold(P, amp=depth, width=width, profile="groove", taper=0.0, mode=mode, name=name)]
        out += [Fold(P, amp=depth * 0.7, width=0.9, profile="stitch", pitch=stitch_pitch, offset=o, taper=0.0, mode=mode,
                     name=f"{name}_st{k}") for k, o in enumerate(stitch)]
        return out

    def auto_folds(self, piece, amount=1.0, seams=True, seed=1):
        """Правдоподобная расстановка складок по типу блока и посадке: где сжатие, где натяжение. Возвращает
        список Fold — его можно отфильтровать, дополнить или передать в add как есть. Крупные складки идут в
        геометрию ("geo"), мелкая присборка и швы — в карту нормалей и маску."""
        B, lm, a = self.B, self.B.lm, float(amount)
        kind = getattr(piece, "kind", None)
        F = []
        if kind == "pants":
            kt, ln = lm["knee_t"], piece.length
            for side, limb in piece.legs.items():
                ax = self._axes(side)
                if ln > kt + 0.06:      # колено: гармошка под коленом, мягкие «мешки» спереди
                    F += self.folds_accordion(limb, kt + 0.015, count=3, pitch=20, amp=4.0 * a, width=10, sector=("back", 75),
                                              tilt=3, seed=seed, name=f"knee_back_{side}")
                    F += self.folds_accordion(limb, kt - 0.05, count=2, pitch=42, amp=2.8 * a, width=20, sector=("front", 65),
                                              tilt=6, seed=seed + 1, name=f"knee_front_{side}")
                if ln > 0.82:           # низ: стопка складок над манжетой или обувью
                    F += self.folds_accordion(limb, ln - 0.095, count=4, pitch=19, amp=4.5 * a, width=10, tilt=7, jitter=0.35,
                                              seed=seed + 2, name=f"stack_{side}")
                # натяжение от паха вниз-наружу по бедру
                p0, _ = B.limb_point(limb, 0.06)
                start = np.array([B.center_x(lm["crotch"]) - 20.0, p0[1] * 0.45, lm["crotch"] + 25.0])
                ends = [B.limb_point(limb, t_)[0] + ax["front"] * 70 + ax["out"] * k_ for t_, k_ in ((0.22, 20.0), (0.32, 45.0))]
                F += self.folds_tension(start, ends, amp=3.2 * a, width=15, name=f"crotch_{side}")
                # бедро спереди: длинная мягкая «труба»
                F.append(Fold(self.limb_line(limb, 0.08, min(ln, kt) - 0.1, "front", offset=0.0), amp=2.2 * a, width=26,
                              profile="pipe", taper=0.3, name=f"thigh_pipe_{side}"))
                if seams:               # швы: боковой и шаговый
                    F += self.seam(self.limb_line(limb, 0.02, ln - 0.01, "out"), name=f"side_seam_{side}")
                    F += self.seam(self.limb_line(limb, 0.04, ln - 0.01, "in"), stitch=(), name=f"inseam_{side}")
            if getattr(piece, "elastic", False):     # присборка под поясом на резинке: крупная — геометрией, мелкая — картой
                bw = getattr(piece, "band_width", 40.0)              # присборка видна под поясом-резинкой
                F += self.folds_gather(piece.edges["waist"], count=max(8, piece.cols // 3), length=48, amp=2.2 * a, width=11,
                                       seed=seed, start=bw - 6.0, name="waist_gather")
                F += self.folds_gather(piece.edges["waist"], count=piece.cols, length=26, amp=0.7 * a, width=3.5,
                                       mode=("normal", "mask"), seed=seed + 3, start=bw - 4.0, name="waist_gather_fine")
        elif kind == "sleeve":
            limb, ln = piece.limb, piece.length
            et = lm["elbow_t"]
            if ln > et + 0.06:
                F += self.folds_accordion(limb, et + 0.01, count=3, pitch=18, amp=3.5 * a, width=9, sector=("front", 70),
                                          tilt=3, seed=seed, name="elbow")
            if ln > 0.8:
                F += self.folds_accordion(limb, ln - 0.06, count=3, pitch=17, amp=3.0 * a, width=9, tilt=5, seed=seed + 1,
                                          name="cuff_stack")
        elif kind == "skirt":
            F += self.folds_hanging(piece.edges["waist"], piece.z_hem + 15, count=10, amp=(0.5 * a, 5.0 * a), width=30,
                                    name="skirt_hang")
        return F

    def binding(self, piece, edge, width=8.0, proud=1.8, t=1.0, name=None):
        """Окантовка кромки: узкая полоса, обнимающая край с обеих сторон (вырез, пройма, низ топа)."""
        from .body import Surface
        prof = [(0.3, -width / 2), (proud, -width * 0.2), (proud, width * 0.2), (0.3, width / 2)]
        across = np.linalg.norm(np.diff(np.asarray(prof), axis=0), axis=1).mean()
        L0 = np.asarray(piece.edges[edge], float)
        keep = np.concatenate([[True], np.linalg.norm(np.diff(L0, axis=0), axis=1) > 1e-6])
        L0 = L0[keep]
        per = np.linalg.norm(np.diff(np.vstack([L0, L0[:1]]), axis=0), axis=1).sum()
        loop = resample_closed(L0, max(12, int(per / max(3.0, across * 3.5))))   # ломаная: на углах без перехлёста
        # поперёк кромки — по поверхности самой вещи (кромка выреза и проймы — пространственная кривая:
        # средняя плоскость уводила бы полосу в тело под рукой)
        m = QuadMesh.from_patches(piece.patches)
        Ng = Surface(m.V, m.triangles()).closest(loop)["normal"]
        T = np.roll(loop, -1, axis=0) - np.roll(loop, 1, axis=0)
        T /= np.linalg.norm(T, axis=1, keepdims=True)
        up = np.cross(Ng, T)
        pc = self.band(loop, prof, closed=True, up=up, t=t, name=name or f"binding_{piece.name}_{edge}",
                       fit=LAYER_GAP[min(getattr(piece, "layer", 1), 4)] + piece.t + 0.5)
        pc.layer = getattr(piece, "layer", 1)
        return pc

    def waistband(self, piece, width=38.0, proud=2.2, t=1.8, ribs=True, edge="waist", name=None):
        """Пояс на резинке поверх верхней кромки брюк или юбки: плотная лента шириной width, чуть выпуклая;
        ribs — рубчик резинки в карте нормалей (вертикальные канавки)."""
        loop = piece.edges[edge]
        prof = [(proud * 0.4, 3.0), (proud, -width * 0.15), (proud, -width * 0.85), (proud * 0.4, -width - 1.0)]
        pc = self.band(loop, prof, closed=True, up=(0, 0, 1), t=t, name=name or f"waistband_{piece.name}",
                       fit=LAYER_GAP[min(getattr(piece, "layer", 1), 4)] + piece.t + 0.8)
        # лента ложится поверх вещи (ниже кромки брюки расширяются к бёдрам): зазор с запасом на присборку
        pc.patches = [Patch(self.push_over(pc.patches[0].G, [piece], clear=t + 3.2), pc.patches[0].closed_u,
                            pc.patches[0].closed_v, pc.patches[0].name)]
        pc.layer, pc.kind = getattr(piece, "layer", 1), "waistband"
        piece.band_width = width
        if ribs:
            L = resample_closed(np.asarray(loop, float), max(24, int(np.linalg.norm(np.diff(loop, axis=0), axis=1).sum() / 6)))
            pc.folds = [Fold(np.linspace(q + (0, 0, -3.0), q + (0, 0, -width + 2.0), 6), amp=0.45, width=1.6, profile="groove",
                             taper=0.05, mode=("normal", "mask"), name=f"rib{k}") for k, q in enumerate(L)]
        return pc

    def _lace(self, left, right, r=1.6, lift=2.5, name="lace", normals=None):
        """Шнуровка крест-накрест между рядами точек left и right (одинаковой длины)."""
        a = np.arange(6) * 2 * math.pi / 6
        prof = np.stack([r * np.cos(a), r * np.sin(a)], axis=1)
        out = None
        for k in range(len(left) - 1):
            for sg, (p0, p1) in enumerate(((left[k], right[k + 1]), (right[k], left[k + 1]))):
                mid = (p0 + p1) / 2
                n = normals[k] if normals is not None else self.B.closest(mid[None])["normal"][0]
                mid = mid + n * (lift + r * (1.8 if sg == 0 else 0.4))     # шнуры не пересекаются
                seg = quad_sweep(prof, resample_open(np.array([p0, mid, p1]), 7), name=f"{name}{k}_{sg}")
                out = seg if out is None else out.merged(seg)
        return out

    def sneaker_details(self, shoe, tongue_w=46.0, eyelets=5, collar=True, lace_r=1.7, name=None):
        """Детали кроссовка на ботинке shoe (блок shoe): мягкий кант по верху голенища, язычок по подъёму
        и шнуровка крест-накрест. Возвращает (кант и язычок — блоки того же материала, что ботинок;
        шнурки и люверсы — отдельный блок-тело для своего цвета)."""
        nm = name or shoe.name
        from .body import Surface
        Sf = Surface(shoe.solid.V, shoe.solid.triangles())
        fl = np.asarray(shoe.edges["front_line"], float)            # от верха голенища к подъёму
        fl = resample_open(fl, 14)
        h = Sf.closest(fl)
        n = h["normal"]
        T = np.gradient(fl, axis=0)
        T /= np.linalg.norm(T, axis=1, keepdims=True)
        side = np.cross(T, n)
        side /= np.linalg.norm(side, axis=1, keepdims=True)
        blocks = []
        if collar:                                                  # мягкий кант по верху голенища
            prof = [(0.5, -7.0), (3.5, -4.0), (4.5, 0.0), (3.0, 3.5), (0.5, 5.0)]
            pc = self.band(shoe.edges["top"], prof, closed=True, up=(0, 0, 1), t=1.6, name=f"{nm}_collar")
            blocks.append(pc)
        # язычок: полоса по подъёму, выше канта на 14 мм, лежит на ботинке
        top_ext = fl[0] + (fl[0] - fl[1]) / np.linalg.norm(fl[0] - fl[1]) * 14.0
        path = np.vstack([top_ext, fl[:-2]])[::-1]                  # снизу вверх
        tg = self.ribbon(path, width=tongue_w, t=2.2, normal=None, taper=1.05, name=f"{nm}_tongue", clear=None,
                         over=[shoe])
        blocks.append(tg)
        # люверсы и шнурки: ряды по обе стороны язычка
        idx = np.linspace(2, len(fl) - 3, eyelets).astype(int)[::-1]
        off = tongue_w / 2 + 5.0
        L = fl[idx] + side[idx] * off + n[idx] * 2.0
        R = fl[idx] - side[idx] * off + n[idx] * 2.0
        laces = self._lace(L, R, r=lace_r, lift=3.0, name=f"{nm}_lace", normals=n[idx])
        for k, (pl, pr) in enumerate(zip(L, R)):
            for q, tag in ((pl, "l"), (pr, "r")):
                ring = self.button(q, n[idx][k], r=3.2, h=1.6, name=f"{nm}_eyelet{k}{tag}", n=10).solid
                laces = laces.merged(ring)
        lp = Piece(solid=laces, name=f"{nm}_laces")
        lp.layer = getattr(shoe, "layer", 2) + 1
        lp.bind = getattr(shoe, "bind", None)                      # шнурки — той же жёсткой привязкой, что ботинок
        return blocks, lp
