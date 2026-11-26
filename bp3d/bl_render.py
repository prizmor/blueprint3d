"""Запускается Blender'ом: blender -b <модель.blend> --python bl_render.py -- <out_dir> <имя> [цвет] [--hero-only]

Презентационный рендер серой модели Blueprint3D: процедурные PBR-материалы по отделке деталей
(матовая окраска кузова, чёрный пластик, сатиновый хром, резина, стекло, светящиеся элементы),
студийный свет из софтбоксов, тёмный фон, Cycles. Меш и исходный .blend не меняются:
результат — PNG и отдельная сцена <имя>_lookdev.blend.

Материалы процедурные, без UV: это показ формы и отделки, а не игровые текстуры
(для них нужны ретопология, развёртка и карты — отдельным шагом в пайплайне проекта)."""
import bpy, json, math, os, sys
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
OUT, NAME = os.path.abspath(argv[0]), argv[1]
COLOR = argv[2] if len(argv) > 2 and not argv[2].startswith("--") else "graphite"
HERO_ONLY = "--hero-only" in argv
os.makedirs(OUT, exist_ok=True)

# Матовые цвета окраски (линейный sRGB). Палитра — предложение, цвет выбирает пользователь.
PAINTS = {
    "graphite": (0.085, 0.090, 0.097),
    "teal":     (0.012, 0.125, 0.135),
    "coral":    (0.420, 0.085, 0.055),
    "sand":     (0.380, 0.300, 0.200),
    "white":    (0.620, 0.620, 0.600),
    "black":    (0.012, 0.012, 0.013),
}
PAINT = PAINTS.get(COLOR, PAINTS["graphite"])

sc = bpy.context.scene


def put(node, names, value):
    """Задать вход шейдера по первому существующему имени (имена входов менялись между версиями)."""
    for n in names if isinstance(names, (list, tuple)) else [names]:
        if n in node.inputs:
            node.inputs[n].default_value = value
            return True
    return False


def principled(mat):
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf is None:
        nt.nodes.clear()
        bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
        out = nt.nodes.new("ShaderNodeOutputMaterial")
        nt.links.new(bsdf.outputs[0], out.inputs[0])
    return nt, bsdf


def micro_bump(nt, bsdf, scale, strength):
    """Мелкая шагрень матовой поверхности: шум в объектных координатах (UV не нужны)."""
    tc = nt.nodes.new("ShaderNodeTexCoord")
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = scale
    if "Detail" in noise.inputs:
        noise.inputs["Detail"].default_value = 4.0
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = strength
    if "Distance" in bump.inputs:
        bump.inputs["Distance"].default_value = 0.0002
    nt.links.new(tc.outputs["Object"], noise.inputs["Vector"])
    nt.links.new(noise.outputs[0], bump.inputs["Height"])
    nt.links.new(bump.outputs[0], bsdf.inputs["Normal"])


def setup(mat, base, metal, rough, coat=0.0, emit=None, emit_k=0.0, trans=0.0, ior=1.5, bump=None):
    nt, b = principled(mat)
    put(b, "Base Color", (*base, 1.0))
    put(b, "Metallic", metal)
    put(b, "Roughness", rough)
    put(b, "IOR", ior)
    put(b, "Alpha", 1.0)
    put(b, ["Coat Weight", "Clearcoat"], coat)
    put(b, ["Transmission Weight", "Transmission"], trans)
    if emit:
        put(b, ["Emission Color", "Emission"], (*emit, 1.0))
        put(b, "Emission Strength", emit_k)
    if bump:
        micro_bump(nt, b, *bump)
    try:
        mat.surface_render_method = "DITHERED" if trans else "DITHERED"
    except Exception:
        pass


FINISH = {
    # отделка: параметры материала
    "paint":   dict(base=PAINT, metal=0.0, rough=0.62, coat=0.0, bump=(2600.0, 0.035)),      # матовая окраска
    "chrome":  dict(base=(0.60, 0.60, 0.61), metal=1.0, rough=0.26),                          # сатиновый хром
    "metal":   dict(base=(0.34, 0.34, 0.35), metal=1.0, rough=0.36),                          # литьё, тёмный металл
    "plastic": dict(base=(0.013, 0.013, 0.014), metal=0.0, rough=0.48, bump=(1800.0, 0.05)),  # чёрный пластик
    "rubber":  dict(base=(0.010, 0.010, 0.010), metal=0.0, rough=0.86, bump=(900.0, 0.08)),
    "glass":   dict(base=(0.95, 0.96, 0.97), metal=0.0, rough=0.03, trans=1.0, ior=1.49),
    "lamp":    dict(base=(0.85, 0.87, 0.90), metal=0.0, rough=0.20, emit=(0.90, 0.95, 1.0), emit_k=2.2),
    "amber":   dict(base=(0.80, 0.33, 0.04), metal=0.0, rough=0.22, emit=(1.0, 0.42, 0.05), emit_k=0.6),
}
used = set()
for m in bpy.data.materials:
    key = m.name[2:] if m.name.startswith("M_") else m.name
    key = key.replace("_clear", "").split(".")[0]
    if key in FINISH:
        setup(m, **FINISH[key])
        used.add(key)

col_int = bpy.data.collections.get("internal")
if col_int:
    col_int.hide_render = True
    col_int.hide_viewport = True
ext = [o for o in sc.objects if o.type == "MESH" and not (col_int and o.name in col_int.objects)]
pts = [o.matrix_world @ Vector(c) for o in ext for c in o.bound_box]
mn = Vector([min(p[i] for p in pts) for i in range(3)])
mx = Vector([max(p[i] for p in pts) for i in range(3)])
ctr = (mn + mx) / 2
rad = (mx - mn).length / 2

# ---------------------------------------------------------------- пол и фон
ld = bpy.data.collections.new("LD_Lookdev")
sc.collection.children.link(ld)
bpy.ops.mesh.primitive_plane_add(size=120, location=(ctr.x, ctr.y, mn.z - 0.0005))
floor = bpy.context.active_object
floor.name = "LD_floor"
for c in floor.users_collection:
    c.objects.unlink(floor)
ld.objects.link(floor)
fm = bpy.data.materials.new("LD_floor")
setup(fm, (0.060, 0.062, 0.066), 0.0, 0.42)
floor.data.materials.append(fm)

# Фон — ровный тёмный: пол освещён только возле объекта и уходит в темноту без линии горизонта.
world = bpy.data.worlds.new("LD_world")
world.use_nodes = True
wn = world.node_tree
wn.nodes.clear()
bg = wn.nodes.new("ShaderNodeBackground")
wo = wn.nodes.new("ShaderNodeOutputWorld")
bg.inputs["Color"].default_value = (0.010, 0.011, 0.013, 1)
bg.inputs["Strength"].default_value = 1.0
wn.links.new(bg.outputs[0], wo.inputs[0])
sc.world = world


# ---------------------------------------------------------------- свет: софтбоксы
def softbox(name, loc, size, size_y, watts, color=(1, 1, 1)):
    """Софтбокс — светящаяся плоскость, невидимая для камеры (у источников-ламп в Cycles видимость
    для камеры не отключается, а у мешей — отключается). Мощность пересчитана из ватт лампы."""
    bpy.ops.mesh.primitive_plane_add(size=1.0, location=loc)
    o = bpy.context.active_object
    o.name = name
    o.scale = (size, size_y, 1.0)
    for c in o.users_collection:
        c.objects.unlink(o)
    ld.objects.link(o)
    o.rotation_euler = (ctr - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    em = nt.nodes.new("ShaderNodeEmission")
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    em.inputs["Color"].default_value = (*color, 1.0)
    em.inputs["Strength"].default_value = watts / (size * size_y * math.pi)
    nt.links.new(em.outputs[0], out.inputs["Surface"])
    o.data.materials.append(m)
    o.visible_camera = False
    return o


R = rad
softbox("LD_top", (ctr.x + 0.3 * R, ctr.y + 0.9 * R, mx.z + 2.0 * R), 3.2 * R, 1.6 * R, 120 * R * R)                 # большой верхний
softbox("LD_key", (ctr.x - 2.6 * R, ctr.y - 2.4 * R, ctr.z + 1.3 * R), 2.2 * R, 1.2 * R, 150 * R * R, (1.0, 0.97, 0.93))
softbox("LD_fill", (ctr.x + 2.8 * R, ctr.y - 1.6 * R, ctr.z + 0.5 * R), 2.6 * R, 1.6 * R, 36 * R * R, (0.90, 0.95, 1.0))
softbox("LD_rim", (ctr.x + 1.4 * R, ctr.y + 3.0 * R, ctr.z + 1.6 * R), 2.6 * R, 0.7 * R, 130 * R * R)
softbox("LD_front", (ctr.x, ctr.y - 3.4 * R, ctr.z + 0.15 * R), 3.4 * R, 0.5 * R, 45 * R * R)                # полоса по бамперу

# ---------------------------------------------------------------- рендер
sc.render.engine = "CYCLES"
sc.cycles.samples = 192
sc.cycles.use_denoising = True
try:
    prefs = bpy.context.preferences.addons["cycles"].preferences
    for kind in ("OPTIX", "CUDA", "HIP", "ONEAPI", "METAL"):
        try:
            prefs.compute_device_type = kind
            prefs.get_devices()
            devs = [d for d in prefs.devices if d.type == kind]
            if devs:
                for d in prefs.devices:
                    d.use = d.type == kind
                sc.cycles.device = "GPU"
                print("BP3D_RENDER device", kind, [d.name for d in devs])
                break
        except Exception:
            continue
except Exception as e:
    print("BP3D_RENDER cpu:", e)
sc.render.resolution_x, sc.render.resolution_y = 1920, 1080
sc.render.resolution_percentage = 100
sc.render.film_transparent = False
sc.render.image_settings.file_format = "PNG"
for vt in ("AgX", "Filmic", "Standard"):
    try:
        sc.view_settings.view_transform = vt
        break
    except TypeError:
        continue
for look in ("AgX - Medium High Contrast", "Medium High Contrast", "None"):
    try:
        sc.view_settings.look = look
        break
    except TypeError:
        continue
sc.view_settings.exposure = 0.0

cam = bpy.data.objects.new("LD_cam", bpy.data.cameras.new("LD_cam"))
ld.objects.link(cam)
sc.camera = cam
renders = {}


def shot(name, direction, lens=70, target=None, radius=None, fill=1.08):
    t = Vector(target) if target is not None else ctr
    r = radius if radius is not None else rad
    d = Vector(direction).normalized()
    cam.data.lens = lens
    cam.data.sensor_width = 36
    aspect = sc.render.resolution_y / sc.render.resolution_x
    half = math.atan(18.0 * aspect / lens)                      # вертикальный полуугол — узкая ось кадра
    dist = r * fill / math.sin(half)
    cam.location = t + d * dist
    cam.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
    cam.data.clip_start = max(0.01, dist - 3 * r)
    cam.data.clip_end = dist + 80
    path = os.path.join(OUT, f"{NAME}_{COLOR}_{name}.png")
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)
    renders[name] = path
    print("BP3D_RENDER", name)


# Ориентация после сборки: перёд машины смотрит в −Y, ширина по X, высота по Z.
shot("hero", (-0.78, -1.0, 0.24), lens=70, fill=0.66)
if not HERO_ONLY:
    shot("front", (0.0, -1.0, 0.10), lens=100, fill=0.62)
    shot("side", (-1.0, -0.05, 0.08), lens=100, fill=0.60)
    shot("high", (0.85, -1.0, 0.70), lens=70, fill=0.74)
    lamp = (ctr.x - 0.36 * (mx.x - mn.x), mn.y + 0.24, mn.z + 0.69)
    shot("lamp", (-0.62, -1.0, 0.20), lens=85, target=lamp, radius=0.36, fill=1.0)
    wheel = (mn.x + 0.02, mn.y + 0.955, mn.z + 0.34)
    shot("wheel", (-1.0, -0.42, 0.12), lens=85, target=wheel, radius=0.52, fill=1.0)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, NAME + "_lookdev.blend"), copy=True)

json.dump(dict(color=COLOR, paint_linear=PAINT, finishes=sorted(used), engine="CYCLES", samples=sc.cycles.samples,
               renders=renders), open(os.path.join(OUT, f"render_{COLOR}.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print("BP3D_RENDER_DONE", len(renders))
