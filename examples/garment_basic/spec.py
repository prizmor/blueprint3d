# -*- coding: utf-8 -*-
"""ОБРАЗЕЦ Blueprint3D: одежда на теле с ригом — шаблон спецификации одежды.

Простой комплект на манекене: футболка с короткими рукавами, шорты, пояс с пряжкой, лента у ворота с двумя
хвостами (обвисают на костях с пружиной), носки и ботинки. Показывает всё, что нужно любой вещи:
тело и мерки, блоки Outfit, слои, привязку (веса тела / одна кость), зону динамики, скрытие тела под
одеждой, цвет и узор, лист с телом-обстановкой, разрезами, таблицами мерок, слоёв и динамики.
Пробный объект: состав, размеры и цвета — предложение, не утверждённый дизайн.
Мм; Z вверх от пола, перёд персонажа смотрит в −X, левая сторона персонажа — −Y.
"""
import numpy as np
from bp3d import body
from bp3d.model import Model
from bp3d.garment import Outfit

CODE = "EX-SMP-GARM-100"
TITLE = "Комплект базовый (образец одежды)"
BODY = body.load(body.MANNEQUIN_F)          # тело входит в хеш апрува: поменялось тело — апрув устарел
LM = BODY.lm                                # ориентиры: LM["waist"], LM["bust"], LM["knee_t"] ...


def build_model():
    M = Model(code=CODE, title=TITLE)
    O = Outfit(M, BODY, cols=48)            # 48 петель вокруг туловища

    # Слой 1 — футболка: лиф до бёдер и короткие рукава одной деталью (общий ряд по пройме сваривается).
    # ease — прибавка свободы поверх отступа слоя: на талии плотнее, на груди свободнее.
    tee = O.bodice(layer=1, bottom=("waist", -70), neck="round", neck_depth=55, ease={"waist": 3, "bust": 6}, tent=0.5)
    sleeves = [O.sleeve(tee, s, length=0.30, kind="straight", ease=5) for s in "LR"]
    O.add("tee", 1, "Футболка", "Трикотаж хлопковый", [tee] + sleeves, finish="cloth", color="cream", layer=1,
          hides=True, pattern=dict(kind="stripe", dir="v", pitch=36, width=9, color="teal", patch="bodice_body"))

    # Слой 2 — шорты: труба таза, шаговый мостик и две штанины; низ футболки заправлен под них
    shorts = O.pants(waist=("waist", -5), length=0.26, layer=2, ease=2.0, leg_ease=7.0)
    O.add("shorts", 2, "Шорты", "Хлопок плотный", shorts, finish="cloth", color="navy", layer=2, hides=True)

    # Слой 3 — пояс поверх шорт (over: пояс ложится на вещь под ним) и пряжка на одной кости
    belt = O.belt(z=("waist", -22), width=26, thick=3, layer=3, over=[shorts])
    O.add("belt", 3, "Пояс", "Кожа", belt, finish="leather", color="brown", layer=3)
    M.add("buckle", 4, "Пряжка", "Латунь", O.buckle(belt.edges["front"], normal=belt.edges["front_normal"], up=belt.edges["front_up"]), finish="metal",
          color="gold", bind="hips", layer=4)

    # Слой 4 — лента у ворота: два хвоста на груди, обвисают (preset "soft"), цепочка костей вдоль каждого.
    # Корень цепочки садится на кость, которая ведёт вещь под лентой (здесь — грудной отдел): тогда при
    # наклоне и повороте корпуса лента не уезжает относительно футболки.
    knot = O.front_point(("bust", 88), layer=2, extra=3.0)
    tails = []
    for k, dy in enumerate((-9.0, 9.0)):
        start = knot + (0.0, dy, 0.0)
        path = np.array([start, start + (-4.0, dy * 0.8, -55), start + (-6.0, dy * 1.8, -115)])
        tails.append(O.ribbon(path, width=20, t=1.0, name=f"tie{k}", over=[tee]))   # over: лента ложится на футболку
    O.add("tie", 5, "Лента", "Шёлк", tails, finish="satin", color="coral", layer=4,
          dynamics=dict(preset="soft", chains=1, bones=3, v0=0.1))

    # Носки (слой 1) и ботинки (слой 2): по одной детали на сторону, одна позиция спецификации
    for s in "LR":
        O.add(f"sock_{s}", 6, "Носок", "Трикотаж", O.stocking(s, top=LM["knee_t"] + 0.2, bottom=0.97), finish="cloth",
              color="white", layer=1, hides=True)
        O.add(f"shoe_{s}", 7, "Ботинок", "Кожа", O.shoe(s, shaft=0.9, cols=24), finish="leather", color="brown",
              layer=2, hides=True)
    return M


def sheet(model):
    K = 0.2                                  # главные виды 1:5
    zw, zb = LM["waist"], LM["bust"]
    xw = BODY.center_x(zw)
    elbow = BODY.limb_point("arm_L", 0.2)    # точка и направление оси руки: разрез рукава поперёк руки
    return dict(
        size=(841, 594), scale="1:5", date="", hlr="poly",
        title_lines=[TITLE + ".", "Сборочный чертёж"], doc_type="Сборочный чертёж",
        views=[
            # group "phantom" — тело: тонкая штрихпунктирная; dynamics=True — цепочки костей на виде
            dict(id="front", kind="front", look_at=(0, 0, 0), k=K, at=(150, 440), ground=(-560, 560, "y"),
                 dynamics=True, hidden=False, title="ВИД СПЕРЕДИ", sub="М 1:5", title_at=(150, 62)),
            dict(id="rear", kind="rear", look_at=(0, 0, 0), k=K, at=(385, 440), ground=(-560, 560, "y"),
                 hidden=False, title="ВИД СЗАДИ", sub="М 1:5", title_at=(385, 62)),
            dict(id="side", kind="side", look_at=(0, 0, 0), k=K, at=(580, 440), ground=(-330, 250),
                 dynamics=True, hidden=False, title="ВИД СБОКУ", sub="(слева)  М 1:5", title_at=(570, 62)),
        ],
        sections=[
            # разрезы квадовых деталей сняты с самого меша; кольцо тела — обстановкой: виден отступ и толщина
            dict(id="А", title="А–А", sub="талия  (М 1:2,5)", plane=("z", zw - 22), look_at=(xw, 0, 0), k=0.4,
                 at=(745, 120), title_at=(745, 48), near=200),      # near: без колец рук в той же плоскости
            dict(id="Б", title="Б–Б", sub="грудь  (М 1:2,5)", plane=("z", zb), look_at=(xw, 0, 0), k=0.4,
                 at=(745, 250), title_at=(745, 180), near=170),
            dict(id="В", title="В–В", sub="рукав  (М 1:2)", plane=("free", elbow[0], elbow[1], (-1, 0, 0)), k=0.5,
                 at=(745, 362), title_at=(745, 318), near=110),
        ],
        cuts=[("front", (0, -230, zw - 22), (0, 230, zw - 22), "А", (0, 1)),
              ("front", (0, -230, zb), (0, 230, zb), "Б", (0, 1))],
        dims=[
            ("v", "side", (-200, 0, 0), (-200, 0, LM["height"]), 475),
            ("v", "front", (0, 330, zw), (0, 330, zw - 70), 60, "70"),
        ],
        balloons=[
            ("front", (0, 60, zb + 40), -34, -18, 1), ("front", (0, 110, LM["hips"] - 20), -40, 8, 2),
            ("front", (0, -70, zw - 22), 44, -14, 3), ("front", (0, 0, zw - 22), 12, 20, 4),
            ("front", (0, 12, zb + 40), 40, -30, 5), ("front", (0, 80, 250), -30, 6, 6),
            ("front", (0, -80, 40), 30, 10, 7),
        ],
        measures_at=(345, 468), layers_at=(430, 470), dyn_at=(430, 532),
        tech_at=(655, 418),
        tech=[
            "1. Размеры для справок. Тело (манекен) показано обстановкой и в изделие не входит.",
            "2. Все детали, кроме поз. 4, — квадовый меш с развёрткой; поз. 4 — CAD-тело на кости hips.",
            "3. Отступ слоя — зазор изнанки от тела; слои не пересекаются в исходной позе.",
            "4. Поз. 5 — зона динамики: по три кости с пружиной на хвост, режим «обвисает».",
            "5. Тело под поз. 1, 2, 6, 7 скрывается (кроме полосы у кромок).",
        ],
    )
