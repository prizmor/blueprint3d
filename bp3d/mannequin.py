"""Манекен кодом: женская фигура без лица в T-позе со скелетом — тело для примерки одежды.

Собственная работа проекта (не сторонний ассет): форма задана таблицами сечений ниже, меш получается
объединением перекрывающихся замкнутых тел (воксельный ремеш в Blender) и сглаживанием, скелет и веса —
в bl_mannequin.py. Имена костей — как у Unity Humanoid, поза покоя — T-поза (как у SOMA/Kimodo).

Пропорции — ПРЕДЛОЖЕНИЕ, не утверждённые мерки: взрослая фигура ~7,8 головы с длинными ногами
(стилистика аниме-игр). Система координат персонажа: Z вверх от пола, перёд смотрит в −X,
левая сторона персонажа — −Y (после сборки в Blender: перёд −Y, левая рука +X). Миллиметры.

    python -m bp3d mannequin            # пересобрать bodies/mannequin_f/
"""
import math
import numpy as np

from .mesh import QuadMesh, Patch, quad_tube, revolve_quad

H = 1680.0                              # рост

# Туловище: (z, полуширина по Y, глубина вперёд, глубина назад, смещение центра по X)
TORSO = [
    (792, 92, 60, 68, 8), (815, 144, 84, 96, 8), (845, 162, 96, 106, 8), (880, 169, 100, 108, 8),
    (930, 164, 96, 102, 5), (990, 146, 86, 90, 0), (1040, 128, 78, 82, -6), (1078, 120, 74, 78, -9),
    (1120, 123, 78, 80, -8), (1165, 130, 84, 85, -5), (1210, 138, 90, 90, 0), (1260, 146, 94, 96, 4),
    (1310, 153, 94, 100, 8), (1350, 160, 88, 100, 10), (1385, 158, 78, 94, 11), (1410, 128, 62, 80, 8),
    (1428, 76, 50, 58, 3),
]
# Нога (левая, −Y): (z, центр X, центр Y, радиус по X, радиус по Y)
LEG = [
    (905, 6, -82, 84, 76), (860, 6, -84, 90, 81), (790, 3, -84, 84, 77), (700, 0, -81, 74, 69),
    (600, 0, -77, 63, 60), (520, 2, -74, 53, 50), (470, 2, -72, 49, 48), (430, 5, -71, 46, 45),
    (350, 14, -69, 57, 51), (270, 13, -67, 47, 43), (180, 10, -65, 37, 35), (100, 9, -63, 31, 30),
    (62, 8, -62, 33, 31), (30, 6, -62, 36, 33),
]
# Стопа (левая): (x, центр Y, центр Z, полуширина, полувысота)
FOOT = [
    (52, -62, 30, 20, 26), (40, -62, 34, 29, 33), (5, -62, 38, 35, 38), (-50, -63, 30, 40, 30),
    (-105, -64, 22, 45, 22), (-150, -65, 17, 44, 17), (-180, -65, 14, 36, 14), (-196, -65, 12, 22, 11),
]
ZA = 1365.0                             # высота оси рук в T-позе
# Рука (левая, вдоль −Y, T-поза): (расстояние от плечевого сустава, центр X, центр Z, радиус по X, радиус по Z)
ARM = [
    (-45, 8, ZA - 10, 50, 46), (0, 8, ZA - 6, 50, 47), (45, 8, ZA - 2, 46, 45), (110, 8, ZA, 41, 41),
    (190, 8, ZA, 37, 38), (245, 9, ZA, 34, 34), (272, 10, ZA, 33, 32), (310, 9, ZA, 35, 34),
    (370, 8, ZA, 33, 31), (440, 8, ZA, 28, 25), (490, 8, ZA, 26, 20), (515, 8, ZA, 27, 18),
]
# Шея: (z, центр X, радиус по X, радиус по Y)
NECK = [(1395, 4, 56, 60), (1425, 0, 50, 52), (1465, -6, 47, 48), (1500, -10, 48, 49), (1530, -12, 50, 52)]
# Эллипсоиды: (центр, полуоси) — грудь (объём и верхний скат), ягодицы, голова, челюсть, кисть, большой палец
ELLIPSOIDS_L = [
    ("bust", (-74, -66, 1226), (58, 64, 66)),
    ("bust_slope", (-58, -62, 1272), (46, 72, 84)),
    ("glute", (64, -76, 880), (70, 82, 96)),
    ("hand", (4, -165 - 592, ZA), (44, 86, 15)),
    ("thumb", (-42, -165 - 560, ZA - 3), (20, 36, 12)),
]
ELLIPSOIDS_C = [
    ("head", (-14, 0, 1574), (93, 77, 107)),
    ("jaw", (-36, 0, 1524), (66, 58, 56)),
]
SHOULDER = (8.0, -165.0, ZA)            # центр левого плечевого сустава

# Скелет: имя -> (родитель, начало кости, конец кости). Левая сторона; правая — зеркалом по Y.
BONES_C = [
    ("Hips", None, (2, 0, 900), (0, 0, 1000)),
    ("Spine", "Hips", (0, 0, 1000), (-2, 0, 1120)),
    ("Chest", "Spine", (-2, 0, 1120), (2, 0, 1250)),
    ("UpperChest", "Chest", (2, 0, 1250), (4, 0, 1400)),
    ("Neck", "UpperChest", (4, 0, 1400), (-8, 0, 1500)),
    ("Head", "Neck", (-8, 0, 1500), (-8, 0, 1680)),
]
BONES_L = [
    ("Shoulder", "UpperChest", (4, -28, 1382), (8, -165, ZA)),
    ("UpperArm", "Shoulder", (8, -165, ZA), (10, -437, ZA)),
    ("LowerArm", "UpperArm", (10, -437, ZA), (8, -672, ZA)),
    ("Hand", "LowerArm", (8, -672, ZA), (6, -770, ZA)),
    ("UpperLeg", "Hips", (6, -84, 862), (2, -72, 470)),
    ("LowerLeg", "UpperLeg", (2, -72, 470), (9, -63, 78)),
    ("Foot", "LowerLeg", (9, -63, 78), (-118, -65, 14)),
    ("Toes", "Foot", (-118, -65, 14), (-195, -65, 12)),
]


def skeleton():
    """[(имя, родитель, начало, конец)] в координатах персонажа, мм. Родители идут раньше детей."""
    out = [(n, p, a, b) for n, p, a, b in BONES_C]
    for side, sy in (("Left", 1.0), ("Right", -1.0)):
        for n, p, a, b in BONES_L:
            par = p if p in ("UpperChest", "Hips") else side + p
            out.append((side + n, par, (a[0], a[1] * sy, a[2]), (b[0], b[1] * sy, b[2])))
    return out


def _ring(c, ea, eb, a, b, n, e=2.0):
    th = np.arange(n) * 2 * math.pi / n
    cs, sn = np.cos(th), np.sin(th)
    k = 2.0 / e
    return (np.asarray(c, float) + (a * np.sign(cs) * np.abs(cs) ** k)[:, None] * np.asarray(ea, float)
            + (b * np.sign(sn) * np.abs(sn) ** k)[:, None] * np.asarray(eb, float))


def _ellipsoid(c, r, n=20, name="e"):
    prof = [(math.sin(math.pi * i / 12), -math.cos(math.pi * i / 12)) for i in range(13)]
    prof[0], prof[-1] = (0.0, -1.0), (0.0, 1.0)
    m = revolve_quad(prof, (0, 0, 0), axis=(0, 0, 1), n=n, name=name)
    return m.transformed(lambda P: P * np.asarray(r, float) + np.asarray(c, float))


def parts(n=40):
    """Замкнутые тела манекена: {имя: QuadMesh}. Они перекрываются; единый меш делает Blender."""
    X, Y, Z = (1, 0, 0), (0, 1, 0), (0, 0, 1)
    out = {}
    rings = []
    for z, w, df, db, cx in TORSO:                    # туловище: сечение с разной глубиной вперёд и назад
        th = np.arange(n) * 2 * math.pi / n
        cs, sn = np.cos(th), np.sin(th)
        rx = np.where(cs >= 0, db, df)
        k = 2.0 / 2.35
        rings.append(np.stack([cx + rx * np.sign(cs) * np.abs(cs) ** k, w * np.sign(sn) * np.abs(sn) ** k,
                               np.full(n, float(z))], axis=1))
    out["torso"] = quad_tube(np.stack(rings, axis=1), name="torso")
    out["neck"] = quad_tube(np.stack([_ring((cx, 0, z), X, Y, a, b, n) for z, cx, a, b in NECK], axis=1), name="neck")
    left = {
        "leg": quad_tube(np.stack([_ring((cx, cy, z), X, Y, a, b, n) for z, cx, cy, a, b in LEG], axis=1), name="leg"),
        "foot": quad_tube(np.stack([_ring((x, cy, cz), Y, Z, a, b, n, 2.4) for x, cy, cz, a, b in FOOT], axis=1),
                          name="foot"),
        "arm": quad_tube(np.stack([_ring((cx, SHOULDER[1] - s, cz), X, Z, a, b, n) for s, cx, cz, a, b in ARM], axis=1),
                         name="arm"),
    }
    for name, c, r in ELLIPSOIDS_L:
        left[name] = _ellipsoid(c, r, name=name)
    for name, m in left.items():
        out[name + "_L"] = m
        out[name + "_R"] = m.mirrored_y()
    for name, c, r in ELLIPSOIDS_C:
        out[name] = _ellipsoid(c, r, name=name)
    return out
