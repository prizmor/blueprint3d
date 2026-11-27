# -*- coding: utf-8 -*-
"""ОБРАЗЕЦ Blueprint3D: складки, свободный крой и веса через прокси.

Майка в обтяжку с окантовками, свободные шорты-карго до середины бедра на поясе-резинке, кроссовки
с язычком и шнуровкой. Показывает:
  - складки тремя способами: геометрией (mode="geo"), в карту нормалей ("normal") и в маску для художника
    ("mask"); готовую расстановку по типу блока (auto_folds) и свои складки помощниками folds_* / seam;
  - свободный крой: свобода по зонам ноги и по сторонам (leg_ease, leg_around), натяжение через впадины
    (leg_tent) и ограничение свободы у паха (crease);
  - привязку свободной вещи через прокси-тело (bind="loose") и облегающей — по коже (bind="tight");
  - окантовку (binding), пояс-резинку с рубчиком (waistband), детали кроссовка (sneaker_details);
  - вырез в квадовой оболочке (cutout) с окантовкой по его краю.
Пробный объект: состав, длины и цвета — предложение. Мм; Z вверх от пола, перёд персонажа — −X.
"""
import numpy as np
from bp3d import body
from bp3d.model import Model
from bp3d.garment import Outfit

CODE = "EX-SMP-FOLD-100"
TITLE = "Комплект со складками (образец)"
BODY = body.load(body.MANNEQUIN_F)
LM = BODY.lm


def build_model():
    M = Model(code=CODE, title=TITLE)
    M.atlas_px = 4096                                  # мелкий рельеф в карте нормалей требует плотности текстуры
    O = Outfit(M, BODY, cols=48)

    # майка: облегает тело, узкие лямки (shoulder_out внутрь), глубокая круглая пройма (armhole_round — низ дугой,
    # глубина дуги вычтена из armhole_drop); кромки — окантовкой
    top = O.bodice(layer=1, bottom=("waist", 10), neck="round", neck_depth=75, neck_width=150, shoulder_out=-40,
                   armhole_drop=18, armhole_round=0.6, ease=0.5, tent=0.6, name="tank")
    # вырез-капля на спине (cutout): ячейки внутри убраны, край — по эллипсу, вокруг квады; кромка — окантовкой
    zk = (LM["armpit"] + LM["waist"]) / 2 - 40
    O.cutout(top, BODY.closest(np.array([[BODY.center_x(zk) + 200.0, 0.0, zk]]))["point"][0], (64, 80), name="keyhole")
    O.add("tank", 1, "Майка", "Трикотаж", top, finish="cloth", color="white", layer=1, hides=True, bind="tight")
    for edge in ("neck", "armhole_L", "armhole_R", "keyhole"):
        O.add(f"tank_bind_{edge}", 2, "Окантовка", "Трикотаж", O.binding(top, edge, width=8), finish="cloth",
              color="slate", layer=1, count=False)

    # шорты: свободные по зонам и по сторонам, пояс на резинке; складки — auto_folds + своя складка-залом
    shorts = O.pants(waist=("waist", -30), length=0.30, layer=2, ease={"waist": 0.5, ("waist", -60): 4, "hips": 4},
                     leg_ease={"top": 4, "thigh": 14}, leg_around={"front": 5, "back": 7, "out": 6}, leg_tent=0.6,
                     leg_smooth=1.5, t=1.4, cols=64, elastic=True, crease=8.0, name="shorts")
    O.hang(shorts, side="back")             # сзади ткань идёт отвесно от ягодиц, а не заходит под них
    folds = O.auto_folds(shorts, amount=1.0, seams=True)          # присборка, натяжение от паха, «трубы», швы
    hem_L = shorts.edges["end_L"]
    folds += O.fold_crease(hem_L + np.array([0, 0, 18.0]), amp=1.6, width=5, mode=("normal", "mask"), name="hem_turn_L")
    # bind="loose": веса через прокси-тело там, где ткань отходит от тела (у резинки — с кожи); smooth_mm —
    # сглаживание весов по ткани
    O.add("shorts", 3, "Шорты", "Хлопок", shorts, finish="cloth", color="sand", layer=2, hides=True,
          bind=dict(mode="loose", smooth_mm=30), folds=folds)
    O.add("shorts_band", 4, "Пояс на резинке", "Резинка", O.waistband(shorts, width=34), finish="cloth", color="sand",
          layer=3)

    # кроссовки — жёсткая модель (fit="rigid"): колодка, подошва-чаша, накладки носка и задника со строчкой
    # (shoe_overlays), кант, язычок и накладки под люверсы, прижатые к верху, петля на пятке, протектор и
    # полоса по боковине подошвы в карте нормалей (shoe_tread)
    for s in "LR":
        shoe = O.shoe(s, shaft=0.94, sole=18.0, rand=11.0, ease=3.5, toe_height=40.0, cols=32, name=f"shoe_{s}")
        caps = O.shoe_overlays(shoe, toe_cap=58.0, heel_counter=56.0)
        blocks, laces = O.sneaker_details(shoe, tongue_w=42, eyelets=4, eyestay=14.0, pull_tab=22.0, over=caps)
        O.add(f"shoe_{s}", 5, "Кроссовок", "Текстиль, ЭВА", [shoe] + caps + blocks, finish="leather", color="white",
              layer=2, hides=True, count=(s == "L"), folds=O.shoe_tread(shoe, pattern="bars"),
              pattern=[dict(kind="fill", color="slate", patch=f"shoe_{s}_sole")])
        O.add(f"laces_{s}", 6, "Шнурки", "Полиэстер", laces, finish="plastic", color="ink", layer=3, count=(s == "L"))
    return M


def sheet(model):
    K = 0.2
    zw = LM["waist"]
    thigh, _ = BODY.limb_point("leg_L", 0.2)
    xw = BODY.center_x(zw)
    return dict(
        size=(841, 594), scale="1:5", date="", hlr="poly",
        title_lines=[TITLE + ".", "Сборочный чертёж"], doc_type="Сборочный чертёж",
        views=[
            # folds=True — линии складок режима "geo" на виде (гребень — штрих с точкой, впадина — штрих)
            dict(id="front", kind="front", look_at=(0, 0, 0), k=K, at=(150, 440), ground=(-560, 560, "y"),
                 folds=True, hidden=False, title="ВИД СПЕРЕДИ", sub="М 1:5", title_at=(150, 62)),
            dict(id="rear", kind="rear", look_at=(0, 0, 0), k=K, at=(385, 440), ground=(-560, 560, "y"),
                 folds=True, hidden=False, title="ВИД СЗАДИ", sub="М 1:5", title_at=(385, 62)),
            dict(id="side", kind="side", look_at=(0, 0, 0), k=K, at=(580, 440), ground=(-330, 250),
                 folds=True, hidden=False, title="ВИД СБОКУ", sub="(слева)  М 1:5", title_at=(570, 62)),
        ],
        sections=[
            dict(id="А", title="А–А", sub="бедро  (М 1:2,5)", plane=("z", thigh[2]), look_at=(xw, 0, 0), k=0.4,
                 at=(745, 160), title_at=(745, 90)),
        ],
        cuts=[("front", (0, -300, thigh[2]), (0, 300, thigh[2]), "А", (0, 1))],
        dims=[("v", "side", (-230, 0, 0), (-230, 0, LM["height"]), 478)],
        balloons=[("front", (0, 40, LM["bust"] - 30), -44, 20, 1), ("front", (0, 0, LM["neck_base"] - 70), 40, -26, 2),
                  ("front", (0, 120, LM["hips"] - 60), -52, 10, 3), ("front", (0, -60, zw - 45), 60, -8, 4),
                  ("front", (0, -80, 60), 34, 10, 5), ("front", (0, 75, 95), -40, -20, 6)],
        measures_at=(345, 468), layers_at=(430, 470),
        tech_at=(655, 428),
        tech=[
            "1. Размеры для справок. Тело (манекен) показано обстановкой.",
            "2. Складки поз. 3: крупные — геометрией (на видах), присборка, швы, строчка",
            "   и залом подгиба — в карте нормалей и маске складок.",
            "3. Поз. 3 привязана через прокси-тело (свободная посадка), поз. 1 — по коже.",
        ],
    )
