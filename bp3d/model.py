"""Модель объекта: список деталей с позициями спецификации + описание листа чертежа."""
from dataclasses import dataclass, field

# Отделка влияет только на оттенок серого в 3D-представлении (без текстур).
FINISHES = {
    "paint":   dict(gray=0.55, metal=0.0, rough=0.45),
    "chrome":  dict(gray=0.80, metal=1.0, rough=0.15),
    "metal":   dict(gray=0.45, metal=1.0, rough=0.45),
    "plastic": dict(gray=0.14, metal=0.0, rough=0.70),
    "rubber":  dict(gray=0.07, metal=0.0, rough=0.90),
    "glass":   dict(gray=0.70, metal=0.0, rough=0.05),
    "lamp":    dict(gray=0.90, metal=0.0, rough=0.20),
    "amber":   dict(gray=0.62, metal=0.0, rough=0.20),
    # ткани и кожа (одежда): матовая ткань, ткань с блеском, кожа
    "cloth":   dict(gray=0.50, metal=0.0, rough=0.85),
    "satin":   dict(gray=0.55, metal=0.0, rough=0.35),
    "leather": dict(gray=0.20, metal=0.0, rough=0.50),
}

# Палитра — предложение: цвет выбирает пользователь. Имя из палитры, "#RRGGBB" или (r, g, b) в sRGB 0…1.
PALETTE = {
    "ink": "#1d2433", "navy": "#27375a", "slate": "#4a5670", "teal": "#1f6f78", "mint": "#8fd3c8",
    "white": "#f1efe9", "cream": "#e9dfc9", "sand": "#c9b089", "brown": "#5a3c2c", "black": "#141416",
    "wine": "#6e2233", "coral": "#e0654f", "rose": "#e8a3a8", "gold": "#c9a04a", "silver": "#b9bcc2",
    "violet": "#5b4a8a", "sky": "#7fb2e0",
}


def rgb(color):
    """Цвет детали -> (r, g, b) в sRGB 0…1; None остаётся None."""
    if color is None:
        return None
    if isinstance(color, str):
        h = PALETTE.get(color, color).lstrip("#")
        if len(h) != 6:
            raise ValueError(f"цвет {color!r}: имя из PALETTE или #RRGGBB")
        return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return tuple(float(c) for c in color[:3])


@dataclass
class Part:
    key: str            # уникальное имя объекта в 3D (латиница)
    pos: int            # номер позиции спецификации
    name: str
    material: str
    shape: object
    finish: str = "paint"
    # ext — внешний (видимый); int — внутренний (на видах штриховыми); glass — прозрачный (на видах не
    # проецируется и ничего не заслоняет, виден в разрезах); phantom — обстановка (тонкая штрихпунктирная
    # с двумя точками, в спецификацию не входит); theory — теоретическая поверхность без толщины
    # (только для сетки сечений и обводов: на видах, в разрезах, спецификации и 3D её нет)
    group: str = "ext"
    note: str = ""
    count: bool = True  # False — часть той же позиции (не увеличивает «Кол.» в спецификации)
    # --- 3D-меш и всё, что нужно детали, которая гнётся скелетом (по умолчанию — как раньше)
    mesh: str = "cad"       # "cad" — CAD-триангуляция тела; "quad" — квадовый меш из сеток (bp3d.mesh)
    quad: object = None     # QuadMesh детали (для mesh="quad")
    bind: object = None     # привязка к скелету: "auto" | имя/роль кости | dict(mode="auto", bones=[роли])
    dynamics: object = None  # кости с пружиной: пресет "stiff" | "soft" | "rigid" или dict (см. garment.DYNAMICS)
    layer: int = 0          # слой одежды: 1 — у тела … 4 — аксессуары; 0 — не одежда
    hides: object = None    # True — скрыть тело под деталью (маска считается по покрытию)
    color: object = None    # цвет: имя из PALETTE, "#RRGGBB" или (r, g, b); None — серый по отделке
    pattern: object = None  # узор или список узоров: dict(kind="stripe"|"check"|"dots"|"trim", ...)
    info: dict = field(default_factory=dict)   # служебное: отступ от тела, толщина, зоны суставов


@dataclass
class Model:
    code: str
    title: str
    subtitle: str = ""
    parts: list = field(default_factory=list)
    bom_extra: dict = field(default_factory=dict)   # pos -> (name, material, qty, note) для позиций без геометрии
    body: object = None     # тело персонажа (bp3d.body.Body) — для одежды; None — обычный предмет

    def add(self, key, pos, name, material, shape, finish="paint", group="ext", note="", count=True,
            mesh=None, bind=None, dynamics=None, layer=0, hides=None, color=None, pattern=None, info=None):
        """shape — тело build123d (CAD-триангуляция в 3D) или QuadMesh (квадовый меш в 3D, на чертёж —
        B-rep из тех же сеток). Остальные поля — см. Part."""
        if any(p.key == key for p in self.parts):
            raise ValueError(f"duplicate part key {key}")
        if finish not in FINISHES:
            raise ValueError(f"{key}: отделка {finish!r}; есть {', '.join(FINISHES)}")
        quad = None
        if hasattr(shape, "brep") and hasattr(shape, "F"):      # QuadMesh
            quad, shape = shape, shape.brep()
            mesh = mesh or "quad"
        mesh = mesh or "cad"
        if mesh == "quad" and quad is None:
            raise ValueError(f"{key}: mesh='quad' требует QuadMesh (bp3d.mesh.quad_skin и др.) вместо тела")
        if mesh == "cad":
            quad = None
        rgb(color)
        self.parts.append(Part(key, pos, name, material, shape, finish, group, note, count, mesh, quad, bind,
                               dynamics, layer, hides, color, pattern, dict(info or {})))
        return shape

    def ext(self):
        return [p for p in self.parts if p.group == "ext"]

    def internal(self):
        return [p for p in self.parts if p.group == "int"]

    def bom(self):
        """Спецификация: позиция -> (наименование, материал, количество, примечание)."""
        rows = {}
        for p in self.parts:
            if p.group in ("phantom", "theory") or p.pos is None:
                continue
            if p.pos in rows:
                n, m, q, note = rows[p.pos]
                rows[p.pos] = (n, m, q + (1 if p.count else 0), note)
            else:
                rows[p.pos] = (p.name, p.material, 1 if p.count else 0, p.note)
        rows.update(self.bom_extra)
        return dict(sorted(rows.items()))
