# -*- coding: utf-8 -*-
"""ОБРАЗЕЦ Blueprint3D: цельные вещи — облегающий топ с капюшоном (два варианта) и шорты-карго.

Показывает:
  - цельную оболочку: лиф и капюшон сварены по общей горловине, проймы — окантовкой (худи с рукавами — то же
    плюс sleeve(); свободная вещь слоя 3 при поднятых руках тянется сильнее порога posetest — см. руководство);
  - капюшон (hood) надетый и лежащий на спине как ВАРИАНТЫ детали (variant="hood:up" / "hood:down"):
    в игре виден один, posetest не сравнивает их друг с другом, чертёж и рендер берут первый, вид сзади на листе —
    второй (views[].variant);
  - кулиску по всему краю капюшона (binding по открытой кромке opening) и шнур с наконечниками (drawstring);
  - карман-кенгуру (kangaroo_pocket: трапеция, входы по бокам, объём) и карманы-карго с клапаном и кнопками
    (cargo_pocket) — накладки panel_at поверх сетки вещи;
  - шорты с ластовицей в шаге (crotch="gusset", по умолчанию): два полюса на 5 рёбер вместо одного на 6;
  - источники весов отдельного лоскута (Piece.patch_regions) и сглаживание весов свободной вещи (smooth_mm).
Пробный объект: состав, длины и цвета — предложение. Мм; Z вверх от пола, перёд персонажа — −X.
"""
from bp3d import body
from bp3d.model import Model
from bp3d.garment import Outfit

CODE = "EX-SMP-HOOD-100"
TITLE = "Топ с капюшоном и шорты-карго (образец)"
BODY = body.load(body.MANNEQUIN_F)
LM = BODY.lm


def build_model():
    M = Model(code=CODE, title=TITLE)
    M.atlas_px = 4096
    O = Outfit(M, BODY, cols=48)

    # облегающий укороченный топ: густой лиф (cols 96) — у горловины хватает точек на колонки капюшона
    top = O.bodice(layer=1, bottom=("waist", 20), neck="round", neck_depth=60, cols=96, row_step=12,
                   ease={"bust": 3, "waist": 3, "hips": 3}, tent=0.5, armhole_drop=20, t=1.4, drape=0.0, name="hoodie")
    top.patch_regions = {"hoodie_body": ("torso",)}          # туловище — веса только с туловища
    pocket = O.kangaroo_pocket(top, z=("waist", 75), width=240, height=110, top_width=180, bulge=6)
    for k, mode in enumerate(("up", "down")):
        hood = O.hood(top, mode=mode, front_gap=70, chin=115, name=f"hood_{mode}")
        O.add(f"hoodie_{mode}", 1, "Топ с капюшоном", "Трикотаж", [top, hood, pocket], finish="cloth", color="slate",
              layer=1, hides=True, bind="tight", count=(k == 0), variant=f"hood:{mode}")
        casing = O.binding(hood, "opening", width=22, proud=3.0, t=1.4)
        # кулиска (окантовка обнимает край — она в слое самой вещи) и шнур, выходящий из неё, — в слое вещи;
        # привязка — как у вещи. Шнур проверяется на тело; вещь и кулиску он не проверяет (тот же слой)
        O.add(f"hood_casing_{mode}", 2, "Кулиска", "Трикотаж", casing, finish="cloth", color="slate", layer=1,
              bind="tight", count=(k == 0), variant=f"hood:{mode}")
        O.add(f"drawstring_{mode}", 3, "Шнур", "Полиэстер", O.drawstring(hood, top, over=[casing]), finish="cloth",
              color="cream", layer=1, bind="tight", count=(k == 0), variant=f"hood:{mode}")
    for s in "LR":
        O.add(f"armhole_bind_{s}", 4, "Окантовка проймы", "Кашкорсе",
              O.binding(top, f"armhole_{s}", width=12, proud=2.0, t=1.2), finish="cloth", color="ink", layer=1,
              count=(s == "L"))
    O.add("hoodie_band", 5, "Резинка низа", "Кашкорсе", O.hem_band(top, width=30, edge="bottom", out=2.0, t=1.4),
          finish="cloth", color="ink", layer=1)

    # шорты-карго: ластовица в шаге, карманы с объёмом, клапаном и кнопками
    pants = O.pants(waist=("waist", -24), length=0.34, layer=2, ease={"waist": 0.5, ("waist", -60): 9, "hips": 12},
                    leg_ease={"top": 14, "thigh": 20}, leg_around={"front": 6, "back": 9, "out": 8}, leg_tent=0.7,
                    leg_smooth=2.0, t=1.6, cols=64, elastic=True, name="cargo")
    blocks, snaps = [], []
    for s in "LR":
        b_, sn = O.cargo_pocket(pants, s, at=0.22, size=(130, 120), bulge=10, flap=44, snaps=2)
        blocks += b_
        snaps.append(sn)
    O.add("cargo", 6, "Шорты-карго", "Рип-стоп", [pants] + blocks, finish="cloth", color="sand", layer=2, hides=True,
          bind="loose")
    O.add("cargo_band", 7, "Пояс на резинке", "Резинка", O.waistband(pants, width=40, proud=2.4, t=2.0), finish="cloth",
          color="sand", layer=3)
    for s in "LR":
        O.add(f"cargo_snaps_{s}", 8, "Кнопки", "Металл", snaps["LR".index(s)], finish="metal", color="#8d9096", layer=3,
              count=(s == "L"))
    return M


def sheet(model):
    K = 0.2
    return dict(
        size=(841, 594), scale="1:5", date="", hlr="poly",
        title_lines=[TITLE + ".", "Сборочный чертёж"], doc_type="Сборочный чертёж",
        views=[
            dict(id="front", kind="front", look_at=(0, 0, 0), k=K, at=(150, 440), ground=(-560, 560, "y"),
                 hidden=False, title="ВИД СПЕРЕДИ", sub="капюшон надет  М 1:5", title_at=(150, 62)),
            dict(id="rear", kind="rear", look_at=(0, 0, 0), k=K, at=(385, 440), ground=(-560, 560, "y"),
                 hidden=False, variant=["hood:down"], title="ВИД СЗАДИ", sub="капюшон на спине  М 1:5", title_at=(385, 62)),
            dict(id="side", kind="side", look_at=(0, 0, 0), k=K, at=(580, 440), ground=(-330, 250),
                 hidden=False, title="ВИД СБОКУ", sub="(слева)  М 1:5", title_at=(570, 62)),
        ],
        dims=[("v", "side", (-230, 0, 0), (-230, 0, LM["height"]), 478)],
        balloons=[("front", (0, 60, LM["bust"] - 40), -50, 20, 1), ("front", (0, 120, LM["hips"] - 120), -52, 10, 6)],
        measures_at=(345, 468), layers_at=(430, 462),
        tech_at=(655, 428),
        tech=[
            "1. Размеры для справок. Тело (манекен) показано обстановкой.",
            "2. Топ — одна оболочка: лиф и капюшон сварены по общей горловине.",
            "3. Капюшон — два варианта детали: надет (виды спереди и сбоку) и на спине (вид сзади).",
        ],
    )
