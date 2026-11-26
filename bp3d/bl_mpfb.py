"""Запускается Blender'ом с профилем, где установлен MPFB (BLENDER_USER_RESOURCES=.mpfb/blender_user):
    blender -b --python bl_mpfb.py -- out_dir name [macro.json]
Создаёт женское тело MakeHuman (базовый меш MPFB, ассеты CC0) с игровым скелетом, убирает служебную
геометрию, сохраняет <name>.blend / <name>.glb и превью. Параметры фигуры — macro.json."""
import bpy, json, math, os, sys
import numpy as np
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bl_common as C

argv = sys.argv[sys.argv.index("--") + 1:]
OUT, NAME = argv[:2]
CFG = json.load(open(argv[2], encoding="utf-8")) if len(argv) > 2 else {}

bpy.ops.wm.read_factory_settings(use_empty=True)
mod = None
for m in ("bl_ext.user_default.mpfb", "bl_ext.blender_org.mpfb"):
    try:
        bpy.ops.preferences.addon_enable(module=m)
        __import__(m)
        mod = m
        break
    except Exception as e:
        print("BP3D_MPFB", m, e)
if mod is None:
    raise SystemExit("MPFB не установлен: scripts/install_mpfb.ps1")
import importlib
HumanService = importlib.import_module(mod + ".services.humanservice").HumanService
TargetService = importlib.import_module(mod + ".services.targetservice").TargetService

macro = TargetService.get_default_macro_info_dict()
macro.update({k: v for k, v in CFG.get("macro", {}).items() if k != "race"})
macro["race"].update(CFG.get("macro", {}).get("race", {}))
body = HumanService.create_human(mask_helpers=False, detailed_helpers=False, extra_vertex_groups=True,
                                 feet_on_ground=False, scale=0.1, macro_detail_dict=macro)
for name, w in CFG.get("targets", {}).items():        # отдельные морфы MakeHuman: «breast-volume-vert-up»: 0.3
    path = TargetService.target_full_path(name)
    if path:
        TargetService.load_target(body, path, weight=float(w), name=name)
    else:
        print("BP3D_MPFB нет морфа", name)
arm = HumanService.add_builtin_rig(body, CFG.get("rig", "game_engine"), import_weights=True)

# Служебная геометрия базового меша (вспомогательные сетки одежды, кубики суставов) в игру не идёт:
# остаются только вершины группы "body".
bpy.context.view_layer.objects.active = body
if body.data.shape_keys:                               # запечь морфы в форму
    bpy.ops.object.shape_key_add(from_mix=True)
    mix = [v.co.copy() for v in body.data.shape_keys.key_blocks[-1].data]
    body.shape_key_clear()
    for v, co in zip(body.data.vertices, mix):
        v.co = co
gi = body.vertex_groups["body"].index
keep = np.array([any(g.group == gi and g.weight > 0.5 for g in v.groups) for v in body.data.vertices])
import bmesh
bm = bmesh.new()
bm.from_mesh(body.data)
bm.verts.ensure_lookup_table()
bmesh.ops.delete(bm, geom=[v for v in bm.verts if not keep[v.index]], context="VERTS")
bm.to_mesh(body.data)
bm.free()
bones = {b.name for b in arm.data.bones}
for g in list(body.vertex_groups):                    # служебные группы вершин не нужны: только веса костей
    if g.name not in bones:
        body.vertex_groups.remove(g)
for md in list(body.modifiers):
    if md.type != "ARMATURE":
        body.modifiers.remove(md)
bpy.ops.object.vertex_group_limit_total(group_select_mode="ALL", limit=4)
bpy.ops.object.vertex_group_normalize_all(group_select_mode="ALL", lock_active=False)
body.name = body.data.name = "Body"
arm.name = arm.data.name = "Armature"
# Ступни на пол: меш и скелет сдвигаются вместе (у базового меша MakeHuman ноль — в центре таза).
from mathutils import Matrix
dz = -min(v.co.z for v in body.data.vertices)
body.data.transform(Matrix.Translation((0, 0, dz)))
arm.data.transform(Matrix.Translation((0, 0, dz)))
body.data.update()
for p in body.data.polygons:
    p.use_smooth = True
body.data.materials.clear()
mat = bpy.data.materials.new("M_body")
mat.diffuse_color = (0.80, 0.72, 0.68, 1)
body.data.materials.append(mat)

C.set_engine(sc := bpy.context.scene, "BLENDER_WORKBENCH")
sh = sc.display.shading
sh.light, sh.color_type, sh.show_cavity, sh.show_object_outline = "STUDIO", "MATERIAL", True, True
sh.background_type, sh.background_color = "VIEWPORT", (0.93, 0.93, 0.93)
sc.render.resolution_x, sc.render.resolution_y = 900, 1300
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
sc.collection.objects.link(cam)
sc.camera = cam
bpy.context.view_layer.update()
mn, mx = C.bounds([body])
ctr, size = (mn + mx) / 2, max(mx - mn)
cam.data.type = "ORTHO"
for name, d in (("front", (0, -1, 0)), ("side", (1, 0, 0)), ("back", (0, 1, 0)), ("q", (0.7, -1, 0.25))):
    d = Vector(d).normalized()
    cam.location = ctr + d * size * 4
    cam.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
    cam.data.ortho_scale = size * 1.06
    cam.data.clip_end = size * 20
    sc.render.filepath = os.path.join(OUT, f"preview_{name}.png")
    bpy.ops.render.render(write_still=True)
bpy.data.objects.remove(cam)
C.save_clean(os.path.join(OUT, NAME + ".blend"))
print("BP3D_BONES", [b.name for b in arm.data.bones])
print("BP3D_DONE", len(body.data.vertices), len(body.data.polygons), [round(c, 3) for c in (*mn, *mx)])
