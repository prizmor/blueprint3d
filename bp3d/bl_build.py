"""Запускается Blender'ом: blender -b --factory-startup --python bl_build.py -- manifest glb out_dir name
Собирает серую модель: детали по именам, сварка вершин, сглаживание по углу, ориентация под Unity,
рендеры видов, .blend/.fbx/.glb, отчёт с проверками."""
import bpy, bmesh, json, math, os, sys
import numpy as np
from mathutils import Vector, Matrix

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bl_common as C

argv = sys.argv[sys.argv.index("--") + 1:]
MAN, GLB, OUT, NAME = argv[:4]
man = json.load(open(MAN, encoding="utf-8"))
parts = {p["key"]: p for p in man["parts"]}

bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
sc.unit_settings.system = "METRIC"
sc.unit_settings.scale_length = 1.0
if GLB != "-":                      # "-" — в модели нет CAD-деталей, только квадовые
    bpy.ops.import_scene.gltf(filepath=GLB)

# glTF кладёт меш на узел; ищем объекты-меши по ключам (имя меша/родителя)
meshes = [o for o in sc.objects if o.type == "MESH"]
found = {}
for o in meshes:
    key = None
    for cand in (o.name, o.parent.name if o.parent else "", o.data.name):
        base = cand.split(".")[0]
        if base in parts:
            key = base
            break
    if key is None:
        continue
    found.setdefault(key, []).append(o)

# корень
root = bpy.data.objects.new(NAME, None)
sc.collection.objects.link(root)
col_int = bpy.data.collections.new("internal")
sc.collection.children.link(col_int)

material = C.finish_material        # материал по отделке (и цвету, если он задан)


report = {"parts": {}, "warnings": []}
final = []
for key, objs in found.items():
    p = parts[key]
    # объединить, если узел разбит на несколько мешей
    for o in objs:
        o.matrix_world = o.matrix_world.copy()
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    if len(objs) > 1:
        bpy.ops.object.join()
    o = bpy.context.view_layer.objects.active
    mw = o.matrix_world.copy()
    o.parent = None
    o.matrix_world = mw
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    o.name = key
    o.data.name = key
    # Нормали берём точные из CAD (нормаль поверхности в каждой вершине грани, импорт glTF кладёт их
    # в custom normals). Сварка швов между гранями — с сохранением этих нормалей: где нормали
    # по разные стороны шва различаются, ребро помечается острым. Пересчёт сглаживания по углу
    # не делаем — он и давал «звёзды» и пятна на плоских гранях с длинными треугольниками.
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    try:
        bpy.ops.mesh.remove_doubles(threshold=0.0001, use_sharp_edge_from_normals=True)
    except TypeError:
        bpy.ops.mesh.remove_doubles(threshold=0.0001)
        report["warnings"].append(f"{key}: сварка без сохранения нормалей")
    # Триангуляцию CAD не переделываем: растворение «почти плоских» участков спрямляет слегка
    # изогнутые поверхности (изломы на бампере), а веера на плоских гранях с вырезами всё равно остаются.
    bpy.ops.object.mode_set(mode="OBJECT")
    bm = bmesh.new()
    bm.from_mesh(o.data)
    nm = sum(1 for e in bm.edges if not e.is_manifold)
    bm.free()
    o.data.materials.clear()
    o.data.materials.append(material(p))
    if p["group"] == "int":
        for c in o.users_collection:
            c.objects.unlink(o)
        col_int.objects.link(o)
    tris = sum(len(f.vertices) - 2 for f in o.data.polygons)
    bb = [o.matrix_world @ Vector(c) for c in o.bound_box]
    mn = [min(v[i] for v in bb) * 1000 for i in range(3)]
    mx = [max(v[i] for v in bb) * 1000 for i in range(3)]
    cad = p["bbox_mm"]
    dev = max(abs(a - b) for a, b in zip(mn + mx, cad))
    report["parts"][key] = dict(pos=p["pos"], mesh="cad", tris=tris, quads=0, non_manifold_edges=nm,
                                bbox_dev_mm=round(dev, 2), group=p["group"])
    if dev > 3:
        report["warnings"].append(f"{key}: отклонение габарита {dev:.1f} мм")
    final.append(o)

# Квадовые детали: меш уже готов (петли, UV, острые рёбра) — создаётся как есть, без сварки и пересчёта.
# Координаты пока CAD (метры): общий поворот под Unity ниже применяется ко всем деталям одинаково.
atlas_img = normal_img = None
if man.get("quads"):
    qd = np.load(man["quads"])
    if any(p.get("colored") or i["patterns"] for i in man["atlas"]["islands"] for p in [parts[i["part"]]]):
        atlas_img = C.bake_atlas(man["atlas"], os.path.join(OUT, NAME + "_atlas.png"))
    normal_img = C.load_detail(man["atlas"], OUT, NAME) if man.get("atlas") else None
    for key, p in parts.items():
        if p.get("mesh") != "quad":
            continue
        o = C.quad_object(key, qd, orient=False)
        o.data.materials.append(material(p, atlas_img, p.get("two_sided", False), normal_img))
        if p["group"] == "int":
            for c in o.users_collection:
                c.objects.unlink(o)
            col_int.objects.link(o)
        st = p["stats"]
        nm = C.non_manifold(o)
        report["parts"][key] = dict(pos=p["pos"], mesh="quad", tris=st["triangles"], quads=st["quads"],
                                    tris_only=st["tris"], non_manifold_edges=0 if p.get("two_sided") else nm,
                                    bbox_dev_mm=0.0, group=p["group"], brep_dev_max_mm=st["brep_dev_max_mm"],
                                    brep_dev_mean_mm=st["brep_dev_mean_mm"], aspect_max=round(st["aspect_max"], 2),
                                    uv_stretch=[st["uv_stretch_min"], st["uv_stretch_max"]])
        found[key] = [o]
        final.append(o)
    report["atlas"] = dict(px=man["atlas"]["px"], px_per_cm=man["atlas"]["px_per_cm"],
                           normal=os.path.basename(man["atlas"]["normal"]) if man["atlas"].get("normal") else None,
                           islands=len(man["atlas"]["islands"]),
                           texture=os.path.basename(atlas_img.filepath_raw) if atlas_img else None)

missing = [k for k in parts if k not in found]
for k in missing:
    report["warnings"].append(f"{k}: деталь не найдена в glTF")

# удалить пустые узлы импорта
for o in list(sc.objects):
    if o.type == "EMPTY" and o is not root:
        bpy.data.objects.remove(o)

# ориентация: CAD X (назад) -> Blender +Y, т.е. перед объекта смотрит в -Y
rot = Matrix.Rotation(math.radians(90), 4, "Z")
for o in final:
    o.matrix_world = rot @ o.matrix_world
    o.parent = root
bpy.ops.object.select_all(action="DESELECT")
for o in final:
    o.select_set(True)
bpy.context.view_layer.objects.active = final[0]
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

# ---------------------------------------------------------------- рендеры
try:
    sc.render.engine = "BLENDER_WORKBENCH"
except TypeError as e:
    print("engine:", e)
sh = sc.display.shading
sh.light = "STUDIO"
sh.color_type = "MATERIAL"
sh.show_cavity = True
sh.cavity_type = "BOTH"
sh.show_object_outline = True
sh.show_specular_highlight = False
sc.render.film_transparent = False
world = bpy.data.worlds.new("w")
world.color = (0.93, 0.93, 0.93)
sc.world = world
sh.background_type = "VIEWPORT"
sh.background_color = (0.93, 0.93, 0.93)
sc.render.resolution_x, sc.render.resolution_y = 1600, 1100

pts = [o.matrix_world @ Vector(c) for o in final for c in o.bound_box]
mn = Vector([min(p[i] for p in pts) for i in range(3)])
mx = Vector([max(p[i] for p in pts) for i in range(3)])
ctr = (mn + mx) / 2
size = max(mx - mn)

cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
sc.collection.objects.link(cam)
sc.camera = cam
renders = {}


def shot(name, loc_dir, ortho=True, up_z=True, scale=1.08):
    d = Vector(loc_dir).normalized()
    cam.location = ctr + d * size * (4 if ortho else 1.9)
    cam.rotation_euler = (-d).to_track_quat("-Z", "Y" if up_z else "Z").to_euler()
    if not up_z:
        cam.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
    cam.data.type = "ORTHO" if ortho else "PERSP"
    cam.data.ortho_scale = size * scale
    cam.data.lens = 50
    cam.data.clip_end = size * 20
    path = os.path.join(OUT, "render_" + name + ".png")
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)
    renders[name] = path


col_int.hide_render = True
if atlas_img:                          # цвет и узоры из атласа; детали без текстуры остаются серыми
    sh.color_type = "TEXTURE"
shot("front", (0, -1, 0))
shot("side", (1, 0, 0))
shot("top", (0, -0.0001, 1))
shot("persp_front_left", (-0.75, -1.0, 0.45), ortho=False)
shot("persp_front_right", (0.85, -1.0, 0.65), ortho=False)
shot("persp_low", (-0.3, -1.0, 0.08), ortho=False)
shot("persp_wheel", (-1.0, -0.35, 0.15), ortho=False)
quad_objs = [o for o in final if parts[o.name].get("mesh") == "quad" and parts[o.name]["group"] != "int"]
if quad_objs:                          # каркас сетки поверх заливки: топологию квадов видно глазами
    sh.color_type = "SINGLE"
    sh.single_color = (0.78, 0.78, 0.78)
    wires = C.wire_overlay(quad_objs, thickness=size * 0.0012)
    shot("wire", (-0.75, -1.0, 0.45), ortho=False)
    shot("wire_back", (0.8, 1.0, 0.5), ortho=False)
    for w in wires:
        bpy.data.objects.remove(w)
    sh.color_type = "MATERIAL"
col_int.hide_render = False

report["renders"] = renders
report["total_tris"] = sum(v["tris"] for v in report["parts"].values())
report["total_quads"] = sum(v.get("quads", 0) for v in report["parts"].values())
report["total_tris_ext"] = sum(v["tris"] for v in report["parts"].values() if v["group"] == "ext")
report["bbox_m"] = [list(mn), list(mx)]

blend = os.path.join(OUT, NAME + ".blend")
bpy.ops.wm.save_as_mainfile(filepath=blend)
bpy.ops.object.select_all(action="DESELECT")
root.select_set(True)
for o in final:
    o.select_set(True)
bpy.ops.export_scene.fbx(filepath=os.path.join(OUT, NAME + ".fbx"), use_selection=True,
                         apply_scale_options="FBX_SCALE_UNITS", axis_forward="-Z", axis_up="Y",
                         object_types={"EMPTY", "MESH"}, mesh_smooth_type="FACE", add_leaf_bones=False)
bpy.ops.export_scene.gltf(filepath=os.path.join(OUT, NAME + ".glb"), export_format="GLB", use_selection=True)
report["files"] = dict(blend=blend, fbx=os.path.join(OUT, NAME + ".fbx"), glb=os.path.join(OUT, NAME + ".glb"))
json.dump(report, open(os.path.join(OUT, "report.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("BP3D_DONE", report["total_tris"])
