# -*- coding: utf-8 -*-
"""ОБРАЗЕЦ Blueprint3D: квадовый меш для жёсткого предмета (mesh="quad").

Термос: корпус и крышка — тела вращения, ручка — профиль вдоль кривой, ремень — замкнутая полоса,
накладка — панель двоякой кривизны из двух лоскутов с общим рядом. Все детали идут в 3D квадами
с развёрткой (bp3d.mesh), а на чертёж — B-сплайновыми гранями через те же сетки.
Одна деталь оставлена CAD-телом (донная опора): оба пути работают в одной модели.
Пробный объект: размеры — оценки. Мм; X — назад от передней точки, Y — влево, Z — вверх от земли.
"""
import math
import numpy as np
from bp3d.kit import Path, cyl, grid_of
from bp3d.mesh import quad_skin, quad_sweep, revolve_quad, spacing
from bp3d.model import Model

CODE = "EX-SMP-QUAD-100"
TITLE = "Термос (образец квадового меша)"

R, H = 46.0, 260.0          # радиус и высота корпуса
Z0 = 6.0                    # низ корпуса над землёй (опора)
XC = R                      # ось термоса: X = R, чтобы передняя точка была в X = 0
R_NECK, H_LID = 34.0, 46.0
N_U = 32                    # петель по окружности


def build_model():
    M = Model(code=CODE, title=TITLE)

    # Корпус: профиль (радиус, высота) от оси до оси — контур Path с дугами, разбитый с шагом 12 мм.
    # Точки на оси дают полюса: два веера треугольников (дно и верх) — в отчёте они видны отдельно.
    prof = Path((0, Z0)).L((R - 6, Z0, 6), (R, Z0 + 12), (R, Z0 + H - 30, 14), (R_NECK, Z0 + H), (0, Z0 + H))
    pts, _ = prof.sample(step=12.0)
    body = revolve_quad(pts, (XC, 0, 0), axis=(0, 0, 1), n=N_U, name="body")
    M.add("body", 1, "Корпус", "Сталь нерж., окраска", body, finish="paint", color="teal",
          pattern=dict(kind="stripe", dir="v", pitch=60, width=6, offset=30, color="white"))

    # Крышка: то же вращение, перекрывает горловину на 4 мм
    zl = Z0 + H - 4
    lid = Path((0, zl)).L((R_NECK + 3, zl), (R_NECK + 3, zl + H_LID - 10, 8), (R_NECK - 8, zl + H_LID), (0, zl + H_LID))
    pts, _ = lid.sample(step=8.0)
    M.add("lid", 2, "Крышка", "Пластик ПП", revolve_quad(pts, (XC, 0, 0), axis=(0, 0, 1), n=N_U, name="lid"),
          finish="plastic", color="ink")

    # Ручка: скруглённый прямоугольный профиль вдоль дуги сбоку (плоскость XZ, за корпусом).
    # Ряды сгущены у концов, где ручка входит в корпус.
    ts = spacing(18, dense=[(0.0, 0.12, 2.0), (1.0, 0.12, 2.0)])
    zc, rz = Z0 + 150.0, 70.0
    path = np.array([(XC + R - 6 + 34 * math.sin(math.pi * t), 0.0, zc - rz * math.cos(math.pi * t)) for t in ts])
    a = np.arange(12) * 2 * math.pi / 12
    profile = np.stack([5.0 * np.cos(a), 9.0 * np.sin(a)], axis=1)           # сечение 10 × 18 мм
    handle = quad_sweep(profile, path, up=(0, 1, 0), name="handle")
    M.add("handle", 3, "Ручка", "Пластик ПП", handle, finish="plastic", color="ink")

    # Ремень: прямоугольный профиль по замкнутому кольцу. corners — острые углы профиля: каждая грань
    # ремня — свой лоскут, рёбра между ними острые (гладкий B-сплайн через углы скруглил бы сечение).
    th = np.arange(N_U) * 2 * math.pi / N_U
    ring = np.stack([XC + (R + 1.5) * np.cos(th), (R + 1.5) * np.sin(th), np.full(N_U, Z0 + 150.0)], axis=1)
    strap = np.array([[-1.5, -11], [1.5, -11], [1.5, 0], [1.5, 11], [-1.5, 11], [-1.5, 0]], float)
    belt = quad_sweep(strap, ring, corners=(0, 1, 3, 4), up=(0, 0, 1), closed_path=True, name="strap")
    M.add("strap", 4, "Ремень", "Кожа", belt, finish="leather", color="brown")

    # Накладка: панель двоякой кривизны толщиной 2 мм из двух лоскутов с общим рядом (ребро по середине)
    def pad(u, v):
        ang = math.radians(-34 + 68 * u)
        z = Z0 + 40 + 60 * v
        r = R + 3.0 + 2.5 * math.sin(math.pi * v)           # выпуклость по высоте
        return (XC - r * math.cos(ang), r * math.sin(ang), z)
    A = grid_of(lambda u, v: pad(u, v * 0.5), 12, 6)
    B = grid_of(lambda u, v: pad(u, 0.5 + v * 0.5), 12, 6)
    M.add("pad", 5, "Накладка", "Резина", quad_skin([A, B], 2.0, names=["pad_lo", "pad_hi"]), finish="rubber",
          color="coral", pattern=dict(kind="trim", edges=("u0", "u1", "v0", "v1"), width=4, color="white"))

    # Опора: обычное CAD-тело (mesh="cad" по умолчанию) — оба пути в одной модели
    M.add("foot", 6, "Опора", "Резина", cyl((XC, 0, 0), R - 8, 0, Z0 + 1, "z"), finish="rubber")
    return M


def sheet(model):
    K = 0.8
    return dict(
        size=(594, 420), scale="1:1,25", date="", legend_at=(30, 362), hlr="poly",
        title_lines=[TITLE + ".", "Сборочный чертёж"], doc_type="Сборочный чертёж",
        views=[
            dict(id="side", kind="side", look_at=(XC, 0, 0), k=K, at=(120, 300), ground=(-80, 120),
                 title="ВИД СБОКУ", sub="(слева)  М 1:1,25", title_at=(120, 40)),
            dict(id="front", kind="front", look_at=(XC, 0, 0), k=K, at=(300, 300), ground=(-80, 80, "y"),
                 title="ВИД СПЕРЕДИ", sub="М 1:1,25", title_at=(300, 40)),
        ],
        sections=[
            dict(id="А", title="А–А", sub="(М 1:1,25)", plane=("z", Z0 + 150.0), look_at=(XC, 0, 0), k=K,
                 at=(470, 150), title_at=(470, 60)),
        ],
        cuts=[("side", (XC - 75, 0, Z0 + 150), (XC + 105, 0, Z0 + 150), "А", (0, 1))],
        dims=[
            ("v", "side", (XC + R, 0, 0), (XC + R, 0, Z0 + H + H_LID - 4), 215),
            ("h", "front", (XC, -R, Z0 + 12), (XC, R, Z0 + 12), 312),
        ],
        balloons=[
            ("front", (0, 20, 110), 34, 6, 1), ("front", (XC, 14, Z0 + H + 30), 30, -8, 2),
            ("side", (XC + R + 28, 0, Z0 + 150), 22, -20, 3), ("front", (0, -30, Z0 + 150), -34, 10, 4),
            ("front", (0, 0, Z0 + 70), -40, 14, 5), ("side", (XC - 20, 0, 2), -26, 8, 6),
        ],
        tech_at=(410, 250),
        tech=[
            "1. Размеры для справок. Линии видов вычислены из 3D-модели.",
            "2. Поз. 1–5 идут в 3D квадовым мешем с развёрткой (mesh=quad),",
            "   поз. 6 — CAD-триангуляцией.",
            "3. Разрез квадовых деталей снят с самого меша.",
        ],
    )
