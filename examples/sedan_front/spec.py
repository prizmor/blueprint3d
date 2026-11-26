# -*- coding: utf-8 -*-
"""ОБРАЗЕЦ Blueprint3D: кузов из поверхностей двоякой кривизны.
EX-VEH-SD02-100 — передняя часть кузова седана D-класса, без марки и символики.
Пробный объект, не игровой ассет: размеры — оценки, чертёж не апрувнут. Брать отсюда приёмы, а не форму.

Кузов — не пересечение призм и не один лофт, а набор поверхностей двоякой кривизны:
  ВЕРХ  z = H(x, y): капот (центральный купол, «полосы», рёбра, боковые скаты) и верх крыла;
  СТЕНКА wall(s, z): облицовка бампера, фары и борт крыла — горизонтали с большим скруглением угла;
  линия E — ребро, где верх встречается со стенкой: кромка капота → верх фары → плечевая линия крыла.
Панели — оболочки с толщиной (kit.skin) по этим поверхностям; зазоры заданы смещением границ.
Детали «по месту» (рамка решётки, ламели, вставки ПТФ, датчики) — пересечение контура вида спереди
со слоем, эквидистантным стенке (wslab), поэтому повторяют её кривизну.
Мм; X — назад от передней точки, Y — влево, Z — вверх от земли.
"""
import math
import numpy as np
from build123d import Compound
from bp3d.kit import (Path, poly, sym, rect, circle_path, hexagon, prism_xz, prism_yz, prism_xy,
                      revolve_about, cyl, box, mirror_y, union, cut, mono, lerp, hermite, coons, map_grid,
                      mirror_grid, skin, grid_of, offset_grid, heal, surface_face)
from bp3d.model import Model

GAP = 2.0                        # половина зазора между панелями (зазор 4 мм)
X_END = 1640.0                   # конец построения поверхностей (дальше линии двери)
X_F1 = 1480.0                    # конец панели крыла до обрезки по линии двери
WC = (955.0, 335.5)              # центр переднего колеса (x, z): передний свес 955
R_TIRE, R_ARCH = 335.5, 386.0    # шина 235/40 R19 (Ø671), проём арки
Y_TC = 795.0                     # полуколея (колея 1590)

# ====================================================================== СТЕНКА
Z_CHIN = 258.0                   # подштамповка над губой бампера
Z_WAIST = 478.0                  # «пояс» облицовки: ребро по самой выступающей линии носа
T_N_CHIN = [(150, 120), (190, 62), (203, 38), (216, 27), (233, 24), (246, 27), (258, 36)]
T_N_LO = [(258, 36), (282, 31), (330, 21.5), (395, 11), (445, 4), (478, 0)]
T_N_UP = [(478, 0), (540, 4.5), (600, 11.5), (645, 19.5), (680, 29), (715, 43), (740, 60), (770, 92),
          (830, 170)]                                                        # профиль носа по оси: z -> x
T_RF = [(110, 3600), (520, 3300), (650, 2300), (780, 2000)]                  # радиус передка в плане
T_WS = [(0, 868), (250, 890), (480, 910), (700, 925), (955, 931), (1300, 928), (1640, 923)]   # полуширина борта
T_RA = [(110, 280), (400, 320), (520, 345), (650, 370), (780, 385)]          # угол: вылет вдоль X
T_RB = [(110, 270), (400, 310), (520, 370), (650, 450), (780, 490)]          # угол: вылет вдоль Y
T_NE = [(110, 2.7), (520, 2.5), (700, 2.1), (780, 2.0)]                      # «квадратность» угла


def N(z):
    if z < Z_CHIN:
        return mono(T_N_CHIN, z)
    return mono(T_N_LO, z) if z < Z_WAIST else mono(T_N_UP, z)


def F(y, z):
    """Передняя поверхность: x по (y, z)."""
    r = mono(T_RF, z)
    return N(z) + r - math.sqrt(r * r - y * y)


def W(x, z):
    """Борт: полуширина y по (x, z). Наибольшая ширина на z=520, выше — завал, ниже — подбор."""
    t = z - 520.0
    return mono(T_WS, x) - (58.0 * (t / 250.0) ** 2 if t > 0 else 30.0 * (t / 340.0) ** 2)


def wall(s, z):
    """Точка стенки. s∈[0,1] — передок (y от оси до начала угла), [1,2] — скругление угла
    (катящийся суперэллипс между передом и бортом), [2,3] — борт до X_END. s<0 — правая сторона."""
    if s < 0:
        x, y, zz = wall(-s, z)
        return (x, -y, zz)
    ra, rb, n = mono(T_RA, z), mono(T_RB, z), mono(T_NE, z)
    if s <= 1.0:
        ya = 500.0
        for _ in range(8):
            ya = W(F(ya, z), z) - rb
        y = s * ya
        return (F(y, z), y, z)
    if s <= 2.0:
        ph = (s - 1.0) * math.pi / 2
        a = ra * (1 - max(0.0, math.cos(ph)) ** (2 / n))
        b = rb * (1 - max(0.0, math.sin(ph)) ** (2 / n))
        x, y = 200.0, 700.0
        for _ in range(10):
            y = W(x, z) - b
            x = F(y, z) + a
        return (x, y, z)
    xb = 500.0
    for _ in range(8):
        xb = F(W(xb, z), z) + ra
    x = lerp(xb, X_END, s - 2.0)
    return (x, W(x, z), z)


def _bisect(g, a, b, n=40):
    ga = g(a)
    for _ in range(n):
        m = 0.5 * (a + b)
        gm = g(m)
        if (gm > 0) == (ga > 0):
            a, ga = m, gm
        else:
            b = m
    return 0.5 * (a + b)


def s_of_x(x, z):
    return _bisect(lambda s: wall(s, z)[0] - x, 0.0, 3.0)


def s_of_y(y, z):
    return _bisect(lambda s: wall(s, z)[1] - y, 0.0, 2.0)


def _ds(s, z, mm):
    """Приращение s, дающее mm вдоль стенки."""
    return mm * 2e-3 / math.dist(wall(s - 1e-3, z), wall(s + 1e-3, z))


# ====================================================================== ВЕРХ (капот)
# Капот — четыре грани на сторону, каждая со своей логикой (от оси наружу):
#   купол      — выпуклая середина, сужается к носу (к эмблеме); край купола — «полоса», перелом вниз;
#   ложбина    — вогнутый скат от «полосы»: сначала круто, к ребру выполаживается (тень подчёркивает купол);
#   ребро      — острый гребень от стойки A к внутреннему углу фары;
#   боковой скат — от ребра к линии E, продолжается верхом крыла и закатывается к плечу.
# По длине гребень выпуклый: круче у носа, положе к жабо; передняя кромка завалена «водопадом».
T_ZC = [(0, 752), (100, 777), (200, 801), (300, 823), (450, 853), (600, 881), (800, 915), (955, 938), (1100, 955),
        (1215, 966), (1330, 977), (1450, 988), (1640, 1005)]                 # гребень капота по оси
T_YB = [(40, 120), (300, 175), (800, 255), (1330, 320), (1640, 340)]         # «полосы»: край купола
T_YC = [(60, 426), (200, 468), (400, 522), (700, 592), (955, 640), (1200, 680), (1450, 712), (1640, 730)]  # рёбра
T_C1 = [(40, 4), (600, 9), (1640, 11)]                                       # стрела купола до «полосы»
T_DZM = [(60, 10), (400, 30), (955, 46), (1640, 52)]                         # падение от «полосы» до ребра
T_VAL = [(60, 2.5), (400, 7), (955, 10), (1640, 11)]                         # прогиб ложбины ниже хорды
ROLL_A, ROLL_L = 38.0, 62.0                                                  # завал передней кромки капота

_s = np.linspace(0, 2, 161)
_w = np.array([wall(s, 730.0) for s in _s])
_XL_Y, _XL_X = _w[:, 1], _w[:, 0]


def roll(x, y):
    d = x - float(np.interp(abs(y), _XL_Y, _XL_X))
    return ROLL_A * math.exp(-max(0.0, d) / ROLL_L)


def h_bulge(x):
    return mono(T_ZC, x) - roll(x, mono(T_YB, x)) - mono(T_C1, x)


def h_crease(x):
    return mono(T_ZC, x) - roll(x, mono(T_YC, x)) - mono(T_C1, x) - mono(T_DZM, x)


def h_core(x, y):
    """Капот между рёбрами: купол до «полосы», за ней — ложбина до ребра.
    Ложбина: хорда от «полосы» к ребру минус прогиб по синусу — у «полосы» скат круче, чем край
    купола (выпуклый перелом), у ребра почти горизонтален (за ребром — резкий уход вниз)."""
    y = abs(y)
    yb = mono(T_YB, x)
    if y <= yb:
        return mono(T_ZC, x) - roll(x, y) - mono(T_C1, x) * (y / yb) ** 2
    yc = mono(T_YC, x)
    t = min(1.0, (y - yb) / (yc - yb))
    return (mono(T_ZC, x) - mono(T_C1, x) - mono(T_DZM, x) * t - mono(T_VAL, x) * math.sin(math.pi * t)
            - roll(x, y))


# ---------------------------------------------------------------------- линия E
def _ze_front(s):
    z = 728.0
    for _ in range(30):
        x, y, _ = wall(s, z)
        z = h_core(x, y)
    return z


def _e_front(s):
    return wall(s, _ze_front(s))


S_B = _bisect(lambda s: _e_front(s)[1] - mono(T_YB, _e_front(s)[0]), 0.05, 1.0)      # «полоса» выходит на кромку
S_TIP = _bisect(lambda s: _e_front(s)[1] - mono(T_YC, _e_front(s)[0]), S_B, 1.8)     # ребро выходит на кромку
X_TIP, Y_TIP, Z_TIP = _e_front(S_TIP)
T_ZE = [(X_TIP, Z_TIP), (165, 736), (330, 745), (600, 753), (955, 772), (1250, 788), (1640, 808)]   # высота E по x


def _ze_exact(s):
    if s <= S_TIP:
        return _ze_front(s)
    z = 745.0
    for _ in range(12):
        z = mono(T_ZE, wall(s, z)[0])
    return z


_ZE_S = np.unique(np.concatenate([np.linspace(0, 3, 500), np.linspace(S_TIP - 0.02, S_TIP + 0.02, 41)]))
_ZE_Z = np.array([_ze_exact(s) for s in _ZE_S])


def zE(s):
    return float(np.interp(abs(s), _ZE_S, _ZE_Z))


def E(s):
    return wall(s, zE(s))


_s = np.linspace(S_TIP, 3.0, 700)
_e = np.array([E(s) for s in _s])
_E_S, _E_X, _E_Y, _E_Z = _s, _e[:, 0], _e[:, 1], _e[:, 2]


def yE(x):
    return float(np.interp(x, _E_X, _E_Y))


def zEx(x):
    return float(np.interp(x, _E_X, _E_Z))


def sE(x):
    return float(np.interp(x, _E_X, _E_S))


def H(x, y):
    """Верх: высота по (x, y). За ребром капота — скат к линии E (капот, затем верх крыла)."""
    y = abs(y)
    if x <= X_TIP:
        return h_core(x, y)
    yc = mono(T_YC, x)
    if y <= yc:
        return h_core(x, y)
    zc, ye, ze = h_crease(x), yE(x), zEx(x)
    t = min(1.05, (y - yc) / max(1e-6, ye - yc))
    return hermite(zc, 0.42 * (ze - zc), ze, 2.0 * (ze - zc), t)


# ---------------------------------------------------------------------- линии разъёма на верхе
X_HC = 165.0                                             # угол капота (разъём уходит с E на верх)
T_YH = [(X_HC, yE(X_HC) + GAP), (300, 692), (500, 730), (700, 752), (955, 772), (1200, 790), (1450, 803),
        (1640, 810)]                                     # линия разъёма капот — крыло


def x_hr(y):
    """Задняя кромка капота (в плане середина впереди, углы сзади)."""
    return 1215.0 + 105.0 * (abs(y) / 800.0) ** 2


def _fixp(yfun, rear):
    x = 1300.0
    for _ in range(25):
        x = rear(yfun(x))
    return x


X_HRC = _fixp(lambda x: mono(T_YH, x), x_hr)             # задний угол капота
# внутренняя граница верха крыла: вдоль капота, за его углом — к линии E (подножие стойки A)
T_YFI = ([(x, mono(T_YH, x) + GAP) for x in (X_HC, 230, 300, 400, 500, 700, 955, 1200, X_HRC)]
         + [(X_HRC + 70, mono(T_YH, X_HRC) + 16), (X_F1, yE(X_F1) - 6)])


def _warp(t):
    return 0.35 * t + 0.65 * t * t              # сгущение сетки к передней кромке


def top_patch(y_in, y_out, x_in0, x_out0, s0, s1, nv, nu=40, rear=x_hr):
    """Лоскут верха между продольными линиями y_in(x), y_out(x); передний край — участок E
    от s0 до s1, задний — rear(y)."""
    x_in1, x_out1 = _fixp(y_in, rear), _fixp(y_out, rear)
    bottom = lambda u: (lerp(x_in0, x_in1, _warp(u)), y_in(lerp(x_in0, x_in1, _warp(u))))
    top = lambda u: (lerp(x_out0, x_out1, _warp(u)), y_out(lerp(x_out0, x_out1, _warp(u))))
    left = lambda v: E(lerp(s0, s1, v))[:2]
    right = lambda v: (rear(lerp(y_in(x_in1), y_out(x_out1), v)), lerp(y_in(x_in1), y_out(x_out1), v))
    return map_grid(coons(bottom, top, left, right, nu, nv), lambda x, y: (x, y, H(x, y)))


def hood_bands():
    yb = lambda x: mono(T_YB, x)
    yc = lambda x: mono(T_YC, x)
    yh = lambda x: mono(T_YH, x) - GAP
    xb0 = _e_front(S_B)[0]
    inner = top_patch(lambda x: -yb(x), yb, xb0, xb0, -S_B, S_B, 11)
    mid = top_patch(yb, yc, xb0, X_TIP, S_B, S_TIP, 8)
    facet = top_patch(yc, yh, X_TIP, X_HC, S_TIP, sE(X_HC), 7)
    return [mirror_grid(facet), mirror_grid(mid), inner, mid, facet]


# ====================================================================== линии на стенке
def _ctl(points):
    """Опорные точки линии на стенке: ('y'|'x', координата, z) -> таблица (s, z)."""
    return [((s_of_y(c, z) if kind == "y" else s_of_x(c, z)), z) for kind, c, z in points]


T_ZL = _ctl([("y", 0, 648), ("y", 300, 647), ("y", 462, 638), ("y", 570, 631), ("y", 700, 638), ("x", 300, 660),
             ("x", 430, 699), ("x", 520, 727), ("x", 590, 750), ("x", 660, 764)])   # низ накладки и фары
T_ZBOT = [(0, 190), (1, 193), (2, 205), (2.5, 208), (3, 208)]                       # нижняя кромка бампера
T_SEAM = [(150, 668), (200, 666), (250, 660), (380, 642), (475, 598), (545, 542), (640, 472), (705, 428),
          (780, 395)]                                                               # разъём бампер — крыло: z -> x
Z_FB = 215.0                                                                        # низ крыла (порог)
T_DOOR = [(150, 1462), (205, 1455), (260, 1445), (360, 1418), (480, 1396), (600, 1390), (690, 1398),
          (760, 1420), (830, 1455), (900, 1496), (1000, 1560)]                      # линия передней двери: z -> x


def zL(s):
    return mono(T_ZL, abs(s))


def zEg(s):
    return zE(s) - 2 * GAP


def zbot(s):
    return mono(T_ZBOT, abs(s))


def seam_s(z, dx):
    return s_of_x(mono(T_SEAM, z) + dx, z)


def wall_patch(bottom, top, left, right, nu, nv, dense=4):
    """Лоскут стенки по области в координатах (s, z)."""
    return map_grid(coons(bottom, top, left, right, (nu - 1) * dense + 1, nv), wall, nu)


def _fn(v):
    return v if callable(v) else (lambda s: v)


def band(s0, s1, zlo, zhi, nu, nv):
    """Сетка полосы стенки между линиями zlo(s) и zhi(s) (или постоянными высотами) на участке s0..s1."""
    zlo, zhi = _fn(zlo), _fn(zhi)
    return grid_of(lambda u, v: wall(lerp(s0, s1, u), lerp(zlo(lerp(s0, s1, u)), zhi(lerp(s0, s1, u)), v)), nu, nv)


def wslab(G, d0, d1):
    """Слой, эквидистантный стенке: от d0 до d1 мм внутрь от наружной поверхности (минус — наружу)."""
    return skin(offset_grid(G, d0) if d0 else G, d1 - d0, flip=True)


def tslab(G, d0, d1):
    """То же для верха: от d0 до d1 мм вниз от наружной поверхности."""
    return skin(offset_grid(G, d0, flip=True) if d0 else G, d1 - d0)


S_LI = s_of_y(462.0, 690.0)                                                # внутренний торец фары
S_TAIL = _bisect(lambda s: (zEg(s) - zL(s)) - 9.0, 1.2, 2.9)               # хвост фары (высота 9 мм)
S_L0 = S_LI + _ds(S_LI, 690, GAP)


_L_S = np.linspace(S_L0, S_TAIL, 240)
_L_ARC = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(
    np.array([wall(s, 0.5 * (zL(s) + zEg(s))) for s in _L_S]), axis=0), axis=1))])


def s_at(a):
    """Параметр s по длине a (мм) вдоль средней линии фары от внутреннего торца."""
    return float(np.interp(a, _L_ARC, _L_S))


def zm(s, f):
    """Высота в полосе фары: доля f от низа (0) до верха (1)."""
    return lerp(zL(s), zEg(s), f)


def fascia_bands():
    ztop = lambda s: zL(s) - 2 * GAP
    st = _bisect(lambda s: wall(s, ztop(s))[0] - (mono(T_SEAM, ztop(s)) - GAP), 1.2, 2.9)
    sw, sc = seam_s(Z_WAIST, -GAP), seam_s(Z_CHIN, -GAP)
    s0 = seam_s(zbot(2.3), -GAP)
    zt, zb0 = ztop(st), zbot(s0)
    edge = lambda z0, z1, sg: (lambda v: (sg * seam_s(lerp(z0, z1, v), -GAP), lerp(z0, z1, v)))
    nu = 85
    chin = wall_patch(lambda u: (lerp(-s0, s0, u), zbot(lerp(-s0, s0, u))), lambda u: (lerp(-sc, sc, u), Z_CHIN),
                      edge(zb0, Z_CHIN, -1), edge(zb0, Z_CHIN, 1), nu, 5)
    lower = wall_patch(lambda u: (lerp(-sc, sc, u), Z_CHIN), lambda u: (lerp(-sw, sw, u), Z_WAIST),
                       edge(Z_CHIN, Z_WAIST, -1), edge(Z_CHIN, Z_WAIST, 1), nu, 10)
    upper = wall_patch(lambda u: (lerp(-sw, sw, u), Z_WAIST), lambda u: (lerp(-st, st, u), ztop(lerp(-st, st, u))),
                       edge(Z_WAIST, zt, -1), edge(Z_WAIST, zt, 1), nu, 8)
    lower[:, 0] = chin[:, -1]
    upper[:, 0] = lower[:, -1]
    return [chin, lower, upper]


def fender_bands():
    yfi = lambda x: mono(T_YFI, x)
    x_ft = _bisect(lambda x: (yE(x) - yfi(x)) - 8.0, X_HC, 500.0)          # носик крыла притуплён (8 мм)
    nu = 44
    xs = [lerp(x_ft, X_F1, u) for u in np.linspace(0, 1, (nu - 1) * 4 + 1)]
    Dt = np.array([[(x, lerp(yfi(x), yE(x), v)) for v in np.linspace(0, 1, 7)] for x in xs])
    top = map_grid(Dt, lambda x, y: (x, y, H(x, y)), nu)
    # борт: от E вниз до порога; слева — разъём с бампером (выше низа фары граница условная:
    # там панель вырезается под фару)
    s_ft, s_1 = sE(x_ft), sE(X_F1)
    z0, zk = zE(s_ft), 700.0

    def left(v):
        z = lerp(z0, Z_FB, v)
        if z > zk:
            return (lerp(s_ft, seam_s(zk, GAP), (z0 - z) / (z0 - zk)), z)
        return (seam_s(z, GAP), z)
    side = wall_patch(lambda u: (lerp(s_ft, s_1, u), zE(lerp(s_ft, s_1, u))),
                      lambda u: (lerp(seam_s(Z_FB, GAP), s_of_x(X_F1, Z_FB), u), Z_FB),
                      left, lambda v: (s_of_x(X_F1, lerp(zE(s_1), Z_FB, v)), lerp(zE(s_1), Z_FB, v)), nu, 15)
    side[:, 0] = top[:, -1]
    return [top, side], x_ft


def _isect(a, b):
    r = a & b
    return r if r is not None and r.solids() else None


def _fv(pts, sg=1):
    """Контур вида спереди для левой (sg=1) или правой (sg=-1) стороны."""
    return poly([(sg * p[0],) + tuple(p[1:]) for p in (pts if sg > 0 else list(reversed(pts)))])


# контуры вида спереди (y, z[, r])
MOUTH = sym([(0, 276), (392, 276, 30), (512, Z_WAIST, 34), (456, 600, 30), (440, 668), (0, 668)])
POD = [(520, 438, 14), (800, 430, 14), (858, 404, 18), (862, 338, 18), (800, 318, 14), (535, 318, 14)]
RADAR = (-78, 312, 78, 392)
PLATE = (-265, 386, 265, 510)


# ====================================================================== МОДЕЛЬ
def build_model():
    M = Model(code="EX-VEH-SD02-100", title="Седан D-класса — передняя часть кузова")
    arch = cyl((WC[0], 0, WC[1]), R_ARCH, -1100, 1100, "y")
    both = lambda f: (f(1), f(-1))                    # (левая, правая)
    mir = lambda sg, sh: sh if sg > 0 else mirror_y(sh)

    # ------------------------------------------------------------ капот
    hb = hood_bands()
    M.add("hood", 1, "Капот, панель наружная", "Al 6xxx, s1,0", skin(hb, 1.2))
    fo = [offset_grid(b, 16, flip=True) for b in hb[1:4]]
    for k in range(2):
        row = 0.5 * (fo[k][:, -1] + fo[k + 1][:, 0])
        fo[k][:, -1] = row
        fo[k + 1][:, 0] = row
    frame = skin(fo, 1.0)
    holes = [prism_xy(rect(x0, y0, x1, y1, 40), 600, 1100) for x0, x1 in ((230, 520), (600, 880), (950, 1150))
             for y0, y1 in ((-360, -60), (60, 360))]
    M.add("hood_frame", 26, "Капот, каркас внутренний", "Al 6xxx, s0,9", cut(frame, Compound(holes)), "metal", group="int")

    # ------------------------------------------------------------ сетки стенки
    lamp_g = band(S_L0, S_TAIL, zL, zEg, 37, 6)                                        # полоса фары
    s_m = s_of_y(575.0, Z_WAIST)
    G_mouth = band(-s_m, s_m, 264.0, 676.0, 61, 15)                                    # зона решётки
    G_cheek = [band(sg * s_of_y(400.0, 380.0), sg * s_of_y(885.0, 380.0), Z_CHIN + 4, Z_WAIST - 1, 33, 9)
               for sg in (1, -1)]                                                      # щёки бампера (ПТФ)
    G_up = [band(sg * s_of_y(430.0, 540.0), sg * s_of_y(840.0, 540.0), Z_WAIST + 2, 600.0, 25, 5) for sg in (1, -1)]
    # правая щека строится с u в обратную сторону: нормаль наружу; выравниваем к «внутрь»
    G_cheek[1], G_up[1] = G_cheek[1][::-1], G_up[1][::-1]

    # ------------------------------------------------------------ крылья
    fb, x_ft = fender_bands()
    fender = skin(fb, 1.2)
    s_cut0 = sE(x_ft) - _ds(sE(x_ft), 740, 30)
    lamp_cut = wslab(band(s_cut0, S_TAIL + _ds(S_TAIL, 750, 2 * GAP), lambda s: zL(s) - 2 * GAP,
                          lambda s: zE(s) + 0.3, 41, 6), -10, 14)
    door = Path((mono(T_DOOR, 150), 150))
    door.S(*[(x, z) for z, x in T_DOOR[1:]])
    door.L((X_END + 80, 1000), (X_END + 80, 150))
    door_cut = prism_xz(door.close(), 500, 1100)
    lip_ring = cut(cyl((WC[0], 0, WC[1]), R_ARCH + 22, 500, 1100, "y"), cyl((WC[0], 0, WC[1]), R_ARCH, 490, 1110, "y"))
    ret_ring = cut(cyl((WC[0], 0, WC[1]), R_ARCH + 1.2, 500, 1100, "y"), cyl((WC[0], 0, WC[1]), R_ARCH, 490, 1110, "y"))
    side_g = fb[1][:, ::-1]                       # нормаль внутрь, как у остальных сеток стенки
    low = box(-100, 0, Z_FB + 1, 2000, 1200, 765)
    fender = heal(cut(fender, arch, lamp_cut, door_cut))
    lip = cut(_isect(_isect(lip_ring, wslab(side_g, -2.5, 0.6)), low), lamp_cut, door_cut)
    ret = cut(_isect(_isect(ret_ring, wslab(side_g, 0.0, 15.0)), low), door_cut)
    # отбортовка крыла в зазор с капотом (водосточная полка)
    edge = fb[0][:, 0]
    flange = np.stack([edge + (0, 0, -6.0 * j) for j in range(4)], axis=1)[::-1]
    fl = union(fender, lip, ret, cut(skin(flange, 1.2), door_cut))
    s_th = sE(X_F1)
    th = [surface_face(b) for b in hb] + [surface_face(fb[0]), surface_face(mirror_grid(fb[0]))]
    th += [surface_face(band(-s_th, s_th, lo, hi, 141, 9)) for lo, hi in ((zbot, Z_CHIN), (Z_CHIN, Z_WAIST), (Z_WAIST, zE))]
    M.add("theory", None, "Теоретическая поверхность", "", Compound(th), group="theory")
    M.add("fender_L", 2, "Крыло переднее с отбортовкой арки", "Сталь, s0,7", fl)
    M.add("fender_R", 2, "Крыло переднее с отбортовкой арки", "Сталь, s0,7", mirror_y(fl))

    # ------------------------------------------------------------ облицовка бампера
    fascia = skin(fascia_bands(), 3.0, flip=True)
    mouth_p = lambda g: prism_yz(poly(MOUTH), -60, 420, grow=g)
    pod_p = lambda sg, g: prism_yz(_fv(POD, sg), -60, 520, grow=g)
    sens = [(sg * y, z) for sg in (1, -1) for y, z in ((585, 548), (805, 508))]
    tow = (-466, 300)
    holes = [mouth_p(0), pod_p(1, 0), pod_p(-1, 0), prism_yz(circle_path(tow, 24), -60, 300)]
    holes += [prism_yz(circle_path(c, 10.5), -60, 500) for c in sens]
    # рельеф вокруг проёмов: подштамповка-ступенька 1,4 мм по контуру решётки и вставок ПТФ
    steps = [cut(_isect(mouth_p(14.0), wslab(G_mouth, -3.0, 1.4)), box(-100, -700, 640, 300, 700, 800)),
             _isect(pod_p(1, 11.0), wslab(G_cheek[0], -3.0, 1.4))]
    steps.append(mirror_y(steps[1]))
    fascia = heal(cut(fascia, arch, Compound(holes), *steps))
    M.add("fascia", 3, "Облицовка бампера", "PP+EPDM, s3,0, окраска", fascia)

    # ------------------------------------------------------------ накладка, эмблема
    sw = S_LI - _ds(S_LI, 690, GAP)
    wing = skin(offset_grid(band(-sw, sw, zL, zEg, 41, 6), -1.5), 4.5, flip=True)
    M.add("wing", 4, "Накладка решётки верхняя", "ABS, хром", wing, "chrome")
    G_em = band(-_ds(0, 680, 90), _ds(0, 680, 90), 622.0, 724.0, 9, 7)
    M.add("emblem", 7, "Заглушка эмблемы", "ABS, хром", _isect(prism_yz(rect(-54, 630, 54, 716, 20), -60, 200),
                                                              wslab(G_em, -7.0, 2.0)), "chrome")

    # ------------------------------------------------------------ решётка, воздухозаборник
    ring = cut(_isect(mouth_p(-1.0), wslab(G_mouth, 3.0, 46.0)), _isect(mouth_p(-17.0), wslab(G_mouth, -5.0, 60.0)))
    bar = _isect(_isect(prism_yz(rect(-540, 420, 540, Z_WAIST + 2), -60, 420), mouth_p(-18.0)), wslab(G_mouth, 5.0, 46.0))
    M.add("grille_frame", 5, "Рамка решётки с поперечиной", "ABS, чёрный глянец", ring, "plastic")
    M.add("grille_bar", 5, "Рамка решётки с поперечиной", "ABS, чёрный глянец", bar, "plastic", count=False)
    inner = mouth_p(-16.0)
    for j, z in enumerate((505, 533, 561, 589, 617)):
        sl = _isect(_isect(prism_yz(rect(-500, z - 6, 500, z + 6, 2.5), -60, 420), inner), wslab(G_mouth, 12.0, 40.0))
        M.add(f"slat_{j}", 6, "Ламель решётки", "ABS, чёрный глянец", sl, "plastic")
    struts = Compound([prism_yz(rect(y - 4, Z_WAIST, y + 4, 650), -60, 420) for y in (-330, -165, 165, 330)])
    back_u = _isect(_isect(prism_yz(rect(-500, Z_WAIST, 500, 650), -60, 420), inner), wslab(G_mouth, 54.0, 57.0))
    M.add("grille_back", 6, "Ламель решётки", "ABS", union(_isect(_isect(struts, inner), wslab(G_mouth, 30.0, 55.5)), back_u),
          "plastic", count=False)
    # нижний воздухозаборник: сотовая сетка, крышка радара
    mesh = _isect(_isect(prism_yz(rect(-520, 280, 520, 421), -60, 420), inner), wslab(G_mouth, 22.0, 28.0))
    cells = []
    for k in range(5):
        z = 295 + 28 * k
        for j in range(-9, 10):
            y = 58 * j + (29 if k % 2 else 0)
            if abs(y) < 520:
                cells.append(prism_yz(poly([(y - 25, z), (y - 13, z + 11.5), (y + 13, z + 11.5), (y + 25, z),
                                            (y + 13, z - 11.5), (y - 13, z - 11.5)]), -60, 300))
    rad_p = lambda g: prism_yz(rect(*RADAR, 10), -60, 300, grow=g)
    mesh = cut(mesh, Compound(cells), rad_p(3.0))
    M.add("mesh", 13, "Сетка нижнего воздухозаборника", "PP, чёрный", mesh, "plastic")
    M.add("mesh_back", 13, "Сетка нижнего воздухозаборника", "PP",
          _isect(_isect(prism_yz(rect(-520, 280, 520, 421), -60, 420), inner), wslab(G_mouth, 50.0, 53.0)), "plastic", count=False)
    M.add("radar", 14, "Крышка радара (ниша)", "PC, радиопрозр.", _isect(rad_p(0), wslab(G_mouth, 14.0, 30.0)), "plastic")
    plate = prism_yz(rect(*PLATE, 8), 1.0, 14.0)
    plate = cut(plate, Compound([cyl((0, y, z), 3.5, -5, 30, "x") for y in (-210, 210) for z in (410, 486)]))
    M.add("plate", 15, "Площадка номерного знака", "PP", plate, "plastic")

    # ------------------------------------------------------------ вставки ПТФ и воздуховоды, датчики
    G = G_cheek[0]
    tray = cut(_isect(pod_p(1, -1.5), wslab(G, 2.0, 36.0)), _isect(pod_p(1, -9.0), wslab(G, -8.0, 30.0)))
    duct = prism_yz(_fv([(808, 416, 8), (838, 408, 8), (842, 342, 8), (812, 334, 8)]), -60, 520)
    vanes = Compound([prism_yz(_fv([(806, z), (846, z - 4), (846, z + 1), (806, z + 5)]), -60, 520) for z in (358, 383)])
    pod = cut(tray, duct)
    vanes = _isect(vanes, wslab(G, 26.0, 36.0))
    fog = _isect(prism_yz(_fv([(548, 404, 9), (712, 400, 9), (716, 364, 9), (552, 360, 9)]), -60, 520), wslab(G, 18.0, 30.0))
    leds = _isect(Compound([prism_yz(_fv([(y0, 393), (y0 + 30, 392), (y0 + 30, 372), (y0, 371)]), -60, 520)
                            for y0 in (560, 598, 636, 674)]), wslab(G, 14.0, 18.0))
    trim = _isect(prism_yz(_fv([(540, 343), (795, 340), (795, 332), (540, 335)]), -60, 520), wslab(G, 20.0, 30.0))
    for sg, k in ((1, "L"), (-1, "R")):
        M.add(f"pod_{k}", 16, "Вставка ПТФ с воздуховодом", "PP, чёрный", mir(sg, pod), "plastic")
        M.add(f"podvane_{k}", 16, "Вставка ПТФ с воздуховодом", "PP, чёрный", mir(sg, vanes), "plastic", count=False)
        M.add(f"fog_{k}", 17, "Фара противотуманная светодиодная", "PC / LED", mir(sg, fog), "lamp")
        M.add(f"fogled_{k}", 17, "Фара противотуманная светодиодная", "LED", mir(sg, leds), "lamp", count=False)
        M.add(f"podtrim_{k}", 16, "Вставка ПТФ с воздуховодом", "ABS, хром", mir(sg, trim), "chrome", count=False)
    for j, c in enumerate(sens):
        G = (G_up if c[1] > Z_WAIST else G_cheek)[0 if c[0] > 0 else 1]
        M.add(f"pdc_{j}", 19, "Датчик парковки", "сб., окраска", _isect(prism_yz(circle_path(c, 9), -60, 500), wslab(G, -0.4, 6.0)))
    M.add("towcap", 18, "Заглушка буксирной проушины", "PP, окраска",
          _isect(prism_yz(circle_path(tow, 22.5), -60, 300), wslab(G_cheek[1], -0.3, 3.0)))

    # ------------------------------------------------------------ фары
    arc = _L_ARC
    cell = lambda a0, a1, f0, f1: band(s_at(a0), s_at(a1), lambda s: zm(s, f0), lambda s: zm(s, f1), 5, 4)
    a_in = float(np.interp(16.0, [zEg(s_at(a)) - zL(s_at(a)) for a in arc[::-1]], arc[::-1]))  # длина, где высота фары 16 мм
    lens = wslab(lamp_g, 0.0, 3.0)
    cav = band(s_at(5.0), s_at(a_in), lambda s: zL(s) + 5, lambda s: zEg(s) - 5, 33, 5)
    housing = cut(wslab(lamp_g, 3.0, 78.0), wslab(cav, -2.0, 27.0))
    mods, lenses = [], []
    for j in range(9):
        a = 34.0 + 37.0 * j
        w, f0, f1 = (16.0, 0.30, 0.72) if j < 3 else (14.5, 0.36, 0.70)
        mods.append(wslab(cell(a - w, a + w, f0, f1), 15.0, 30.0))
        lenses.append(wslab(cell(a - w + 5, a + w - 5, f0 + 0.09, f1 - 0.09), 10.0, 16.0))
    a_end = arc[-1]
    drl = union(wslab(band(s_at(9.0), s_at(a_end - 26), lambda s: zL(s) + 7, lambda s: zL(s) + 17, 33, 4), 7.0, 16.0),
                wslab(band(s_at(9.0), s_at(20.0), lambda s: zL(s) + 7, lambda s: zEg(s) - 12, 4, 6), 7.0, 16.0))
    a_t0 = 34.0 + 37.0 * 9 + 6
    turn = wslab(band(s_at(a_t0), s_at(a_in - 6), lambda s: zm(s, 0.42), lambda s: zm(s, 0.84), 9, 4), 9.0, 18.0)
    brow = wslab(band(S_L0, s_at(0.52 * a_end), lambda s: zEg(s) - 13, zEg, 21, 4), -2.0, 0.2)
    # крепёжные лапки и регулировка (за панелями): строятся от точек корпуса
    tabs = []
    for a, up in ((60.0, 1), (300.0, 1), (190.0, -1)):
        px, py, pz = wall(s_at(a), zEg(s_at(a)) if up > 0 else zL(s_at(a)))
        nx, ny = math.cos(math.radians(22 + 0.11 * a)), -math.sin(math.radians(22 + 0.11 * a))
        cx, cy = px + 54 * nx, py + 54 * ny
        z0, z1 = (pz - 6, pz + 26) if up > 0 else (pz - 26, pz + 6)
        t = cut(box(cx - 2, cy - 17, z0, cx + 2, cy + 17, z1), cyl((0, cy, pz + up * 13), 4.2, cx - 6, cx + 6, "x"))
        rib = box(cx - 30, cy - 2, min(z0, z1) + 6, cx, cy + 2, max(z0, z1) - 6)
        tabs.append(union(t, rib))
    px, py, pz = wall(S_L0, zm(S_L0, 0.5))
    side_tab = cut(box(px + 40, py - 36, pz - 12, px + 44, py - 4, pz + 12), cyl((0, py - 24, pz), 4.2, px + 34, px + 50, "x"))
    caps = []
    for a in (70.0, 215.0):
        cx, cy, cz = wall(s_at(a), zm(s_at(a), 0.5))
        ang = math.radians(22 + 0.11 * a)
        caps.append(cyl((0, cy - 82 * math.sin(ang), cz), 34, cx + 82 * math.cos(ang) - 14, cx + 82 * math.cos(ang) + 16, "x"))
    for sg, k in ((1, "L"), (-1, "R")):
        M.add(f"hl_{k}_lens", 8, "Рассеиватель фары", "PC, лак", mir(sg, lens), "glass", group="glass")
        M.add(f"hl_{k}_housing", 9, "Корпус фары с маской", "PP-T20 / PC, металлизация", mir(sg, housing), "plastic")
        M.add(f"hl_{k}_drl", 10, "Световод ДХО (J-образный)", "PMMA", mir(sg, drl), "lamp")
        for j in range(9):
            M.add(f"hl_{k}_mod{j}", 11, "Модуль светодиодный (3 дальн. + 6 ближн.)", "сб.", mir(sg, mods[j]), "metal")
            M.add(f"hl_{k}_len{j}", 11, "Модуль светодиодный (3 дальн. + 6 ближн.)", "PMMA", mir(sg, lenses[j]), "lamp", count=False)
        M.add(f"hl_{k}_turn", 12, "Указатель поворота", "PMMA, LED", mir(sg, turn), "amber")
        M.add(f"hl_{k}_brow", 4, "Накладка решётки верхняя", "ABS, хром", mir(sg, brow), "chrome", count=False)
        M.add(f"hl_{k}_tabs", 27, "Лапка крепления фары (с корпусом)", "PP-T20", mir(sg, union(*tabs, side_tab)),
              "plastic", group="int", count=False)
        M.add(f"hl_{k}_caps", 27, "Лапка крепления фары (с корпусом)", "PP", mir(sg, union(*caps)), "plastic", group="int",
              count=False)
    M.bom_extra[27] = ("Лапка крепления фары (с корпусом)", "PP-T20", 8, "М6")

    # ------------------------------------------------------------ жабо, обстановка
    y_cw = mono(T_YH, X_HRC) - 8
    cz = lambda x, y: H(x_hr(y), y) - 12 + 0.30 * (x - x_hr(y) - 2 * GAP)
    Gc = np.array([[(x_hr(y) + 2 * GAP + d, y, cz(x_hr(y) + 2 * GAP + d, y)) for y in np.linspace(-y_cw, y_cw, 45)]
                   for d in np.linspace(0, 92, 5)])
    cowl = skin(Gc, 3.0)
    slots = []
    for row, d in enumerate((26, 44, 62)):
        for j in range(-6, 7):
            y = 92 * j + (46 if row % 2 else 0)
            if abs(y) < y_cw - 90 and not (abs(y + 170) < 60 or abs(y - 440) < 60):
                x = x_hr(y) + 2 * GAP + d
                slots.append(prism_xy(rect(x - 3.5, y - 30, x + 3.5, y + 30, 3.4), 880, 1050))
    cowl = cut(cowl, Compound(slots))
    piv = [union(cyl((x_hr(y) + 52, y, 0), 17, cz(x_hr(y) + 52, y) - 4, cz(x_hr(y) + 52, y) + 9, "z"),
                 cyl((x_hr(y) + 52, y, 0), 9, cz(x_hr(y) + 52, y) + 9, cz(x_hr(y) + 52, y) + 24, "z")) for y in (-170, 440)]
    M.add("cowl", 20, "Жабо (накладка ветрового окна)", "PP, чёрный", union(cowl, *piv), "plastic")
    # лобовое стекло и стойка A — фантом
    y_g = y_cw - 40
    ca, sa = math.cos(math.radians(29)), math.sin(math.radians(29))

    def glass(u, v):
        y0 = lerp(-y_g, y_g, v)
        xb = x_hr(y0) + 2 * GAP + 92
        zb = cz(xb, y0) + 4
        t = 300 * u
        return (xb + ca * t + 0.00012 * t * t, y0 * (1 - 0.00022 * t), zb + sa * t - 0.00010 * t * t)
    M.add("ph_glass", None, "Стекло ветровое", "", skin(grid_of(glass, 9, 25), 5.0), "glass", group="phantom")

    def pillar(u, v):
        gx, gy, gz = glass(u, 1.0)
        return (gx + 26 * v, gy + 8 + 62 * v, gz - 8 - 46 * v * v)
    pl = skin(grid_of(pillar, 9, 5), 6.0)
    M.add("ph_pillar_L", None, "Стойка A", "", pl, group="phantom")
    M.add("ph_pillar_R", None, "Стойка A", "", mirror_y(pl), group="phantom")

    # ------------------------------------------------------------ колёса, тормоза, подкрылки
    C3 = (WC[0], 0, WC[1])
    tp = Path((241.3, Y_TC - 104))
    tp.S((252, Y_TC - 115), (285, Y_TC - 120.5), (316, Y_TC - 115), (330, Y_TC - 104))
    tp.S((334.5, Y_TC - 60), (335.5, Y_TC), (334.5, Y_TC + 60), (330, Y_TC + 104))
    tp.S((316, Y_TC + 115), (285, Y_TC + 120.5), (252, Y_TC + 115), (241.3, Y_TC + 104))
    tire = revolve_about(tp.close(), C3)
    grooves = [revolve_about(rect(327.5, Y_TC + u - 4.5, 340, Y_TC + u + 4.5), C3) for u in (-72, -26, 26, 72)]
    grooves += [revolve_about(rect(266, Y_TC + sg * 116, 268.5, Y_TC + sg * 128), C3) for sg in (1, -1)]
    slots = []
    for j in range(60):
        a = math.radians(6 * j + 1.5)
        c, s_ = math.cos(a), math.sin(a)
        q = [(WC[0] + r * c - w * s_, WC[1] + r * s_ + w * c) for r, w in ((322, -2.2), (340, -2.2), (340, 2.2), (322, 2.2))]
        slots += [prism_xz(poly(q), Y_TC + 86, Y_TC + 110), prism_xz(poly(q), Y_TC - 110, Y_TC - 86)]
    tire = cut(tire, Compound(grooves), Compound(slots))
    rim = revolve_about(poly([(252, Y_TC + 116), (252, Y_TC + 104), (241.3, Y_TC + 104), (241.3, Y_TC + 96), (233, Y_TC + 88),
                              (233, Y_TC - 88), (241.3, Y_TC - 96), (241.3, Y_TC - 104), (252, Y_TC - 104), (252, Y_TC - 116),
                              (238, Y_TC - 116), (226, Y_TC - 100), (226, Y_TC + 96), (232, Y_TC + 108), (238, Y_TC + 116)]), C3)
    face = revolve_about(poly([(34, Y_TC + 45), (80, Y_TC + 45), (94, Y_TC + 62), (228, Y_TC + 92), (228, Y_TC + 110),
                               (150, Y_TC + 101), (96, Y_TC + 92), (70, Y_TC + 97), (34, Y_TC + 97)]), C3)
    wins = []
    pt = lambda r, a: (WC[0] + r * math.cos(math.radians(a)), WC[1] + r * math.sin(math.radians(a)))
    for kk in range(10):
        a0 = 90 + 36 * kk
        w = Path(pt(221, a0 + 3.6))
        w.A(WC, 221, a0 + 32.4)
        w.L(pt(104, a0 + 28.5))
        w.A(WC, 104, a0 + 7.5)
        wins.append(prism_xz(w.close(), Y_TC + 30, Y_TC + 130))
        g = Path(pt(214, a0 - 0.75))
        g.A(WC, 214, a0 + 0.75)
        g.L(pt(122, a0 + 1.1), pt(122, a0 - 1.1))
        wins.append(prism_xz(g.close(), Y_TC + 30, Y_TC + 130))
    face = cut(face, Compound(wins))
    nuts = [prism_xz(hexagon(pt(57.15, 90 + 72 * kk), 10.5), Y_TC + 90, Y_TC + 108) for kk in range(5)]
    cap = union(cyl(C3, 33, Y_TC + 95, Y_TC + 103, "y"), cyl(C3, 26, Y_TC + 103, Y_TC + 106, "y"))
    wheel = union(rim, face)
    disc = union(revolve_about(rect(96, Y_TC - 2, 160, Y_TC + 26), C3),
                 revolve_about(poly([(34, Y_TC + 38), (96, Y_TC + 38), (96, Y_TC + 20), (88, Y_TC + 20), (88, Y_TC + 30),
                                     (34, Y_TC + 30)]), C3))
    disc = cut(disc, revolve_about(rect(104, Y_TC + 9.5, 161, Y_TC + 14.5), C3))
    cal = Path(pt(118, 122))
    cal.A(WC, 118, 178)
    cal.L(pt(180, 176))
    cal.A(WC, 180, 124)
    caliper = cut(prism_xz(cal.close(), Y_TC - 22, Y_TC + 43), revolve_about(rect(90, Y_TC - 5, 164, Y_TC + 29), C3))
    hub = union(cyl(C3, 46, Y_TC - 70, Y_TC + 45, "y"), cyl(C3, 20, 330, Y_TC - 70, "y"),
                box(WC[0] - 26, Y_TC - 105, WC[1] - 150, WC[0] + 26, Y_TC - 60, WC[1] + 190))
    strut = union(cyl((WC[0] + 8, Y_TC - 205, 0), 27, WC[1] + 150, 660, "z"), cyl((WC[0] + 8, Y_TC - 205, 0), 62, 520, 700, "z"),
                  box(WC[0] - 18, Y_TC - 205, WC[1] + 110, WC[0] + 34, Y_TC - 100, WC[1] + 170))
    # свод подкрылка: ширина по форме борта (до отбортовки арки), иначе за колесом щель насквозь
    def vault(u, v):
        x, z = pt(R_ARCH + 3, lerp(-24.0, 204.0, u))
        return (x, lerp(640.0, W(x, max(z, Z_FB)) - 14.0, v), z)
    lw = Path(pt(R_ARCH + 4.5, -24))
    lw.A(WC, R_ARCH + 4.5, 90).A(WC, R_ARCH + 4.5, 204)
    liner = heal(union(skin(grid_of(vault, 41, 5), 3.0, flip=True),
                       cut(prism_xz(lw.close(), 637, 641.5), cyl(C3, 150, 630, 650, "y"))))
    for sg, k in ((1, "L"), (-1, "R")):
        M.add(f"wh_{k}_tire", 22, "Шина 235/40 R19 96V", "—", mir(sg, tire), "rubber", note="покуп.")
        M.add(f"wh_{k}_rim", 23, "Диск 19×8,5J ET45, 5×114,3", "Al, литьё, алмазная проточка", mir(sg, wheel), "metal", note="покуп.")
        M.add(f"wh_{k}_hub", 23, "Диск 19×8,5J ET45, 5×114,3", "", mir(sg, union(cap, *nuts)), "chrome", count=False)
        M.add(f"wh_{k}_disc", 24, "Диск тормозной вент. Ø320×28", "Чугун GG20", mir(sg, disc), "metal")
        M.add(f"wh_{k}_caliper", 25, "Суппорт тормозной", "Al / чугун", mir(sg, caliper), "metal")
        M.add(f"wh_{k}_knuckle", 30, "Ступица, кулак, стойка (условно)", "сталь", mir(sg, union(hub, strut)), "metal", group="int")
        M.add(f"liner_{k}", 21, "Подкрылок", "PP / нетканый PET", mir(sg, liner), "plastic")

    # ------------------------------------------------------------ внутренние узлы (для разрезов)
    bp = Path((132, -640))
    bp.S((106, -330), (98, 0), (106, 330), (132, 640))
    bp.L((182, 640))
    bp.S((156, 330), (148, 0), (156, -330), (182, -640))
    beam = prism_xy(bp.close(), 392, 492)
    beam = cut(beam, prism_xy(Path((141, -600)).S((115, -330), (107, 0), (115, 330), (141, 600)).L((172, 600))
                              .S((147, 330), (139, 0), (147, -330), (172, -600)).close(), 400, 484))
    M.add("beam", 28, "Усилитель бампера", "Al 6082-T6, профиль", beam, "metal", group="int")
    absb = cut(_isect(prism_yz(rect(-560, 388, 560, 496, 12), -60, 300), wslab(G_mouth, 46.5, 150.0)), prism_xy(bp, 380, 500),
               box(120, -700, 380, 400, 700, 500))
    M.add("absorber", 29, "Абсорбер энергии", "EPP 45 г/л", absb, "plastic", group="int")
    M.add("crashbox_L", 28, "Усилитель бампера", "Al", box(158, 500, 398, 290, 590, 486, 6), "metal", group="int", count=False)
    M.add("crashbox_R", 28, "Усилитель бампера", "Al", box(158, -590, 398, 290, -500, 486, 6), "metal", group="int", count=False)
    M.add("radiator", 31, "Блок радиаторов (условно)", "Al", union(box(196, -370, 280, 212, 370, 640), box(226, -390, 262, 258, 390, 668)),
          "metal", group="int")
    M.add("tiebar", 32, "Панель рамки радиатора верхняя", "Сталь, s1,2", cut(box(170, -430, 664, 270, 430, 690),
                                                                            box(176, -420, 660, 264, 420, 686)), "metal", group="int")
    return M


def sheet(model):
    from bp3d.drawing import CAMERAS, ViewProj
    CAMERAS["lamp"] = ((0.77, -0.64, 0.0), (0, 0, 1))        # взгляд по нормали к рассеивателю левой фары
    K = 0.125
    WC3 = (WC[0], 0, WC[1])
    x0, _, z0 = E(0)                                          # передняя кромка капота на оси
    XR = x_hr(0)
    ZR = H(XR, 0)                                             # задняя кромка капота на оси
    pt = lambda r, a: (WC[0] + r * math.cos(math.radians(a)), 0, WC[1] + r * math.sin(math.radians(a)))
    n0 = lambda v: f"{v:.0f}"
    slope = math.degrees(math.atan((H(1000, 0) - H(500, 0)) / 500.0))
    appr = -math.degrees(math.atan2(WC[1] - 190.0, WC[0] - 62.0) - math.asin(R_TIRE / math.hypot(WC[0] - 62.0, WC[1] - 190.0)))
    BODY = ["theory"]
    LP = lambda a, f: wall(s_at(a), zm(s_at(a), f))                              # точка на фаре: длина a, доля высоты f
    TAB = lambda a: wall(s_at(a), zEg(s_at(a)) + 13)
    SB = s_of_y(520.0, 690.0)                                                    # разрез Б–Б по фаре
    PB = wall(SB, 690.0)
    GB = (XR + 2 * GAP + 92, 0, ZR + 20)                                         # основание ветрового стекла
    A = lambda x, z: (x, 0, z)                                                   # точка разреза А–А
    Fy = lambda y, z: (0, y, z)                                                  # точка вида спереди
    ST = [20, 60, 120, 200, 300, 450, 600, 780, 955, 1150]                       # станции теоретических обводов
    # аксонометрия: вписать в поле
    ip = ViewProj("iso", (0, 0, 0))
    uv = [ip.uv(c) for c in ((0, -931, 190), (0, 931, 190), (1500, -931, 190), (1500, 931, 800), (1215, 0, ZR),
                             (0, 0, 730), (1500, -931, 800), (400, -931, 190), (1500, 800, 1000))]
    ki = 0.08
    iso_at = (743 - ki * (min(u for u, v in uv) + max(u for u, v in uv)) / 2,
              246 + ki * (min(v for u, v in uv) + max(v for u, v in uv)) / 2)
    lp = ViewProj("lamp", (0, 0, 0))
    lu, lv = lp.uv(wall(lerp(S_L0, S_TAIL, 0.5), 690.0))
    lamp_at = (376 - 0.4 * lu, 424 + 0.4 * lv)
    return dict(
        size=(841, 594), scale="1:8", date="25.11.26", hlr="poly", hlr_deflection=(0.2, 0.08),
        title_lines=["Седан D-класса. Модуль передка:", "капот, крылья, облицовка бампера,", "решётка, фары, жабо, колёса"],
        doc_type="Сборочный чертёж", bom_row=5.25,
        views=[
            dict(id="side", kind="side", look_at=(0, 0, 0), k=K, at=(40, 160), ground=(-150, 1700), hidden=False,
                 internal=False, grid=[dict(axis="y", values=[0, 200, 400, 600, 800], parts=BODY)],
                 title="ВИД СБОКУ", sub="(слева)  М 1:8", title_at=(150, 12)),
            dict(id="front", kind="front", look_at=(0, 0, 0), k=K, at=(398, 160), ground=(-990, 990, "y"), hidden=False,
                 internal=False, title="ВИД СПЕРЕДИ", sub="М 1:8", title_at=(398, 13)),
            dict(id="top", kind="top", look_at=(0, 0, 0), k=K, at=(40, 312), up=(0, 1, 0), hidden=False, internal=False,
                 grid=[dict(axis="z", values=[300, 450, 600, 700], parts=BODY)],
                 title="ВИД СВЕРХУ", sub="М 1:8", title_at=(205, 188)),
            dict(id="iso", kind="iso", look_at=(0, 0, 0), k=ki, at=iso_at, hidden=False, internal=False, phantom=False,
                 title="АКСОНОМЕТРИЯ", sub="(справочно)  М 1:12,5", title_at=(743, 133)),
            dict(id="lamp", kind="lamp", look_at=(0, 0, 0), k=0.4, at=lamp_at, hidden=False,
                 parts=["hl_L"], groups=("ext", "int"),
                 title="Д", sub="(М 1:2,5)  фара левая в сборе, рассеиватель поз. 8 не показан", title_at=(300, 392)),
        ],
        plans=[dict(id="bp", kind="front", look_at=(0, 0, 0), k=0.2, at=(452, 404), clip=(258, 196, 194.3, 186),
                    title="ТЕОРЕТИЧЕСКИЕ ОБВОДЫ", sub="поперечные сечения X = const (левая половина)  М 1:5", title_at=(356, 192),
                    sets=[dict(axis="x", values=ST, parts=BODY, half=True, labels=False)])],
        sections=[
            dict(id="А", title="А–А", sub="(М 1:4) по оси автомобиля", plane=("y", 0.0), look_at=(0, 0, 0), k=0.25, at=(547, 217),
                 clip=((-16, 0, 170), (372, 0, 772)), title_at=(592, 12), behind=300,
                 parts=["hood", "wing", "emblem", "grille", "slat", "mesh", "radar", "plate", "fascia", "beam", "absorber",
                        "radiator", "tiebar"]),
            dict(id="Б", title="Б–Б", sub="(М 1:2,5) через фару", plane=("y", 520.0), look_at=(0, 520, 0), k=0.4, at=(634, 346),
                 clip=((66, 520, 566), (392, 520, 796)), title_at=(745, 12), behind=45,
                 parts=["hl_L", "hood", "fascia", "tiebar", "pdc"]),
            dict(id="В", title="В–В", sub="(М 1:4) поперёк капота и крыла, X = 700; половина до оси симметрии", plane=("x", 700.0),
                 look_at=(700, 0, 0), k=0.25, at=(506, 694), clip=((700, -1, 596), (700, 946, 906)), title_at=(345, 457),
                 parts=["hood", "fender_L", "liner_L"]),
            dict(id="Г", title="Г–Г", sub="(М 1:2,5) крыло над колесом, X = 955", plane=("x", 955.0), look_at=(955, 0, 0), k=0.4,
                 at=(877, 708.4), clip=((955, 606, 640), (955, 946, 896)), title_at=(566, 345), behind=60,
                 parts=["fender_L", "liner_L", "wh_L_tire", "wh_L_knuckle", "hood"]),
        ],
        details=[
            dict(letter="Е", view="front", center=(0, 690, 378), r=186, k=0.4, at=(568, 263), title_at=(508, 192), sub="(М 1:2,5)"),
            dict(letter="Ж", view="side", center=pt(R_ARCH, 132), r=70, k=0.5, at=(577, 502), title_at=(528, 468), sub="(М 1:2)"),
        ],
        cuts=[("top", (-45, 0, 0), (395, 0, 0), "А", (0, -1)),
              ("front", (0, 520, 815), (0, 520, 575), "Б", (-1, 0)),
              ("top", (700, 1010, 0), (700, -40, 0), "В", (1, 0)),
              ("side", (955, 0, 905), (955, 0, 640), "Г", (1, 0))],
        lines=[("bp", (0, 0, 180), (0, 0, 1020), "c")]
        + [("bp", (0, 0, z), (0, 935, z), "g") for z in (200, 400, 600, 800, 1000)]
        + [("bp", (0, y, 185), (0, y, 1010), "g") for y in (200, 400, 600, 800)]
        + [("sec:А", (0, 0, 172), (0, 0, 770), "c"), ("sec:В", (700, 0, 600), (700, 0, 905), "c"),
               ("top", (-60, 0, 0), (1560, 0, 0), "c"), ("front", (0, 0, 120), (0, 0, 1010), "c"),
               ("side", (WC[0] - 370, 0, WC[1]), (WC[0] + 370, 0, WC[1]), "c"),
               ("side", (WC[0], 0, WC[1] - 370), (WC[0], 0, WC[1] + 370), "c")],
        dims=[
            ("h", "side", (0, 0, Z_WAIST), WC3, 166), ("h", "side", (0, 0, Z_WAIST), (XR, 0, ZR), 172),
            ("h", "side", (0, 0, Z_WAIST), (1496, 0, 900), 178),
            ("v", "side", (62, 0, 190), (62, 0, 0), 33, "190"), ("v", "side", (x0, 0, z0), (x0, 0, 0), 26, n0(z0)),
            ("v", "side", WC3, (WC[0], 0, 0), 246, "335,5"), ("v", "side", (XR, 0, ZR), (XR, 0, 0), 254, n0(ZR)),
            ("h", "front", (0, 931, 520), (0, -931, 520), 178), ("h", "front", (0, Y_TC, 0), (0, -Y_TC, 0), 172, "1590 (колея)"),
            ("h", "front", (0, -Y_TC + 117.5, 0), (0, -Y_TC - 117.5, 0), 166, "235"),
            ("v", "front", (0, -931, z0), (0, -931, 0), 522, n0(z0)), ("v", "front", (0, -931, Z_WAIST), (0, -931, 0), 529, "478"),
            ("v", "top", (955, 931, 0), (955, -931, 0), 250, "1862"),
            ("h", "top", (x0, -950, 0), (XR, -950, 0), 435, n0(XR - x0) + " (капот)"),
            ("h", "sec:В", (700, 931, 600), (700, 0, 600), 546, "931"),
            ("h", "lamp", LP(0, 0.5), LP(_L_ARC[-1], 0.5), 449),
            ("h", "lamp", TAB(60), TAB(300), 397),
            ("h", "det:Е", (0, 862, 338), (0, 520, 318), 300, "342"),
            ("v", "sec:Г", (955, 800, WC[1] + R_TIRE), (955, 800, WC[1] + R_ARCH + 3), 641, "53"),
            ("v", "sec:Б", wall(SB, zEg(SB)), wall(SB, zL(SB)), 668),
            ("h", "sec:А", (0, 0, 190), (98, 0, 392), 180, "98"),
        ],

        angles=[("side", (885, 0, 0), (300, 0, 0), (300, 0, 585 * math.tan(math.radians(appr))), 62, f"{appr:.0f}°"),
                ("side", GB, (GB[0] + 300, 0, GB[2]), (GB[0] + 300 * math.cos(math.radians(29)), 0, GB[2] + 300 * math.sin(math.radians(29))),
                 24, "29°"),
                ("side", (1000, 0, H(1000, 0)), (500, 0, H(1000, 0)), (500, 0, H(1000, 0) - 500 * math.tan(math.radians(slope))), 44,
                 f"{slope:.1f}°".replace(".", ","), 40.5)],
        texts=[("bp", (0, 0, z), n0(z), 4.5, 0.8, 2.0) for z in (200, 400, 600, 800, 1000)]
        + [("bp", (0, y, 185), n0(y), 0, 3.2, 2.0) for y in (200, 400, 600, 800)]
        + [("bp", (0, 0, H(x, 0)), f"X{x}", -5.5, -0.5, 1.9) for x in ST[2:]]
,
        balloons=[
            # вид сбоку
            ("side", (600, 0, H(600, 0)), -8, -16, 1), ("side", (1340, 0, 560), 20, 4, 2), ("side", (200, 0, 690), -8, -24, 9),
            ("side", (330, 0, 372), -12, 30, 16), ("side", (XR + 40, 0, ZR + 4), -14, -16, 20),
            ("side", pt(371, 62), 22, -12, 21), ("side", pt(324, -76), 18, -6, 22), ("side", pt(190, -18), 20, 7, 23),
            ("side", pt(140, 22), 26, -5, 24), ("side", pt(150, 152), -40, 37, 25),
            # вид спереди
            ("front", Fy(150, 692), -5, -18, 4), ("front", Fy(-10, 690), 8, -20, 7), ("front", Fy(-200, 561), 10, -36, 6),
            ("front", Fy(-300, 280), -4, 14, 5), ("front", Fy(200, 340), -8, 24, 13), ("front", Fy(0, 350), 2, 27, 14),
            ("front", Fy(-150, 390), 8, 33, 15), ("front", Fy(700, 320), 12, 22, 16), ("front", Fy(630, 382), 20, 36, 17),
            ("front", Fy(-466, 300), -8, 27, 18), ("front", Fy(-805, 508), 4, -38, 19), ("front", Fy(-640, 240), -4, 17, 3),
            ("front", Fy(600, 644), 10, -27, 10), ("front", Fy(560, 678), 20, -23, 11), ("front", Fy(840, 704), -9, -22, 12),
            ("front", Fy(-600, 700), 2, -30, 8), ("front", Fy(-520, 660), -14, -31, 9),
            # вид сверху
            ("top", (700, 120, 0), 6, -10, 1), ("top", (900, 838, 0), -10, 13, 2), ("top", (XR + 50, -300, 0), 14, 10, 20),
            ("top", (120, -700, 0), -10, 14, 3), ("top", (30, 250, 0), -9, -6, 4),
            # А–А
            ("sec:А", A(200, H(200, 0)), 14, 8, 1), ("sec:А", A(300, H(300, 0) - 17), 6, 15, 26), ("sec:А", A(225, 690), 16, 6, 32),
            ("sec:А", A(258, 560), 9, -4, 31), ("sec:А", A(150, 488), 14, -10, 28), ("sec:А", A(76, 470), 28, 66, 29),
            ("sec:А", A(30, 695), -9, -14, 4), ("sec:А", A(30, 561), -10, 6, 6), ("sec:А", A(4, 448), -6, 12, 15),
            ("sec:А", A(48, 340), -13, 8, 13), ("sec:А", A(26, 225), -9, 7, 3),
            # Б–Б
            ("sec:Б", (PB[0] + 6, 520, 716), -16, -6, 8), ("sec:Б", (PB[0] + 62, 520, 668), 8, 38, 9),
            ("sec:Б", (PB[0] + 24, 520, zm(SB, 0.5)), -30, 38, 11), ("sec:Б", (300, 520, H(300, 520)), 6, -9, 1),
            ("sec:Б", wall(SB, 600), -12, 10, 3), ("sec:Б", (PB[0] + 12, 520, zL(SB) + 12), -14, 24, 10),
            # В–В, Г–Г
            ("sec:В", (700, 320, H(700, 320)), 0, -9, 1), ("sec:В", (700, 200, H(700, 200) - 17), 5, 13, 26),
            ("sec:В", (700, 850, H(700, 850)), -4, -12, 2), ("sec:В", (700, 760, WC[1] + 293), 8, -8, 21),
            ("sec:Г", (955, 830, H(955, 830)), 6, -10, 2), ("sec:Г", (955, 700, WC[1] + R_ARCH + 4.5), 4, -14, 21),
            ("sec:Г", (955, 740, 650), -6, 12, 22), ("sec:Г", (955, 628, 650), 4, 14, 30),
            # вид Д
            ("lamp", LP(120, 0.95), 4, -14, 4), ("lamp", LP(210, 0.5), 6, 22, 11), ("lamp", LP(420, 0.12), 8, 14, 10),
            ("lamp", LP(400, 0.62), 10, -16, 12), ("lamp", TAB(300), 12, -4, 27), ("lamp", LP(540, 0.5), -4, 16, 9),
            # выносные
            ("det:Е", Fy(700, 428), 14, -22, 16), ("det:Е", Fy(630, 382), 6, 34, 17), ("det:Е", Fy(826, 370), -20, 34, 16),
            ("det:Е", Fy(600, 480), -30, -8, 3),
            ("det:Ж", pt(R_ARCH + 12, 126), -12, -12, 2), ("det:Ж", pt(R_ARCH - 22, 124), 16, 16, 21), ("det:Ж", pt(R_TIRE - 6, 127), 12, 4, 22),
        ],
        notes=[
            ("side", (800, 0, zEx(800)), -30, -42, "ребро E (плечевая линия)"),
            ("side", (mono(T_DOOR, 480), 0, 480), 10, 22, "линия передней двери"),
            ("side", pt(R_ARCH, 100), -16, -9, "R386"), ("side", pt(R_TIRE, -25), 10, 10, "Ø671"),
            ("side", pt(57.15, 162), -46, -34, "5 отв. PCD 114,3"),
            ("top", (F(300, Z_WAIST), -300, 0), 16, 9, "нос в плане R3340"),
            ("top", (wall(1.5, Z_WAIST)[0], wall(1.5, Z_WAIST)[1], 0), -12, -10, "угол: суперэллипс 345×370"),
            ("side", (WC[0] + 150, 0, zEx(WC[0] + 150)), 22, -30, "E: 772 над осью колеса"),
            ("top", (900, -mono(T_YC, 900), 0), 8, 12, "ребро капота"), ("top", (900, mono(T_YB, 900), 0), 8, -7, "«полоса» купола"),
            ("top", (1000, -mono(T_YH, 1000), 0), 8, 14, "разъём капот — крыло 4"),
            ("sec:В", (700, mono(T_YC, 700), H(700, mono(T_YC, 700))), -8, -12, "ребро капота"),
            ("sec:В", (700, mono(T_YH, 700), H(700, mono(T_YH, 700))), 8, -14, "зазор 4, отбортовка 18"),
            ("sec:В", (700, yE(700), zEx(700)), 10, 12, "ребро E"),
            ("sec:Г", (955, yE(955), zEx(955)), -16, -8, "ребро E"),
            ("sec:Г", (955, W(955, WC[1] + R_ARCH + 6) - 8, WC[1] + R_ARCH + 0.6), 12, 14, "полка 15"),
            ("sec:А", A(0, Z_WAIST), -6, -4, "X0"),
            ("sec:Б", (PB[0] + 30, 520, zEg(SB) - 2), -6, -12, "рассеиватель s3,0"),
            ("lamp", LP(14, 0.5), -6, 24, "ДХО: J-световод"), ("lamp", LP(70, 0.62), -14, 34, "дальний ×3"),
            ("lamp", LP(260, 0.5), 2, -24, "ближний ×6"),
            ("det:Е", Fy(826, 400), 16, -42, "воздуховод"), ("det:Е", Fy(700, 336), 14, 18, "накладка, хром"),
            ("det:Е", Fy(700, 449), -8, -18, "подштамповка 1,4"),
        ],
        gaps_at=(25, 444),
        gaps=[("Капот — крыло", "4,0 ±0,5", "0 ±0,5"), ("Капот — накладка решётки / фара", "4,0 ±0,7", "−1,0 ±0,7"),
              ("Капот — жабо", "4,0 ±1,0", "−12 (перекрытие уплотнителем)"), ("Фара — крыло", "4,0 ±0,7", "0 ±0,7"),
              ("Фара — облицовка бампера", "4,0 ±1,0", "0 ±1,0"), ("Облицовка бампера — крыло", "4,0 ±1,0", "0 ±1,0"),
              ("Накладка решётки — фара", "4,0 ±0,7", "+1,5 (накладка выступает)"), ("Крыло — дверь передняя", "4,0 ±0,5", "0 ±0,5")],
        legend_at=(30, 512),
        tech_at=(292, 551),
        tech=[
            "1. Размеры для справок. Все линии видов, разрезов и обводов вычислены из 3D-модели (Blueprint3D); марочной символики нет, поз. 7 — заглушка.",
            "2. Кузов — поверхности двоякой кривизны: верх z = H(x, y), стенка (горизонтали с углом-суперэллипсом), ребро E — кромка капота, верх фары, плечо крыла.",
            f"3. Габариты модуля: ширина 1862, длина до линии двери 1496, колея 1590, свес 955; высота кромки капота {z0:.0f}, у жабо {ZR:.0f}; угол въезда {appr:.0f}°.",
            "4. Панели — оболочки: сталь и алюминий s0,7–1,0 (в разрезах зачернены), облицовка бампера PP+EPDM s3,0. Зазоры — по таблице, 4 мм.",
            "5. Фара: 9 светодиодных модулей в ряд (3 дальний + 6 ближний), J-образный световод ДХО по низу, указатель поворота в хвосте; крепление — 4 лапки М6.",
            "6. Решётка: рамка и 5 ламелей — чёрный глянец, накладка поз. 4 — хром; нижний воздухозаборник — сотовая сетка с нишей радара; проём решётки 1024×392, площадка номера 530×124.",
            "7. Колесо 235/40 R19 (Ø671), диск 19×8,5J ET45, PCD 5×114,3, 10 сдвоенных спиц; тормозной диск Ø320×28; проём арки R386, отбортовка 22 мм.",
        ],
    )
