"""Запускается Blender'ом: blender -b --factory-startup --python bl_garment.py -- manifest glb|- out_dir name
Сборка одежды на теле с ригом: тело из файла, квадовые меши как есть (UV, острые рёбра), веса из
bp3d.rig, кости динамики, тело со срезанными скрытыми полигонами, материалы и атлас, рендеры-проверки,
.blend / .fbx (с арматурой) / .glb и отчёт."""
import bpy, bmesh, json, math, os, sys
import numpy as np
from mathutils import Vector, Matrix

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bl_common as C
from bl_body import load_body

argv = sys.argv[sys.argv.index("--") + 1:]
MAN, GLB, OUT, NAME = argv[:4]
man = json.load(open(MAN, encoding="utf-8"))
parts = {p["key"]: p for p in man["parts"]}
rig = man["rig"]
report = {"parts": {}, "warnings": []}

arm, body_meshes = load_body(rig["body_file"])
sc = bpy.context.scene
sc.unit_settings.system = "METRIC"
sc.unit_settings.scale_length = 1.0
for o in list(sc.objects):                              # в сцене остаются только тело и его арматура
    if o is not arm and o not in body_meshes:
        bpy.data.objects.remove(o)
body = body_meshes[0]
if len(body_meshes) > 1:
    bpy.ops.object.select_all(action="DESELECT")
    for o in body_meshes:
        o.select_set(True)
    bpy.context.view_layer.objects.active = body
    bpy.ops.object.join()

# --- кости динамики
bpy.context.view_layer.objects.active = arm
bpy.ops.object.mode_set(mode="EDIT")
inv = arm.matrix_world.inverted()
for b in rig["bones"]:
    eb = arm.data.edit_bones.new(b["name"])
    eb.head = inv @ Vector(C.cad_to_bl(b["head"]))
    eb.tail = inv @ Vector(C.cad_to_bl(b["tail"]))
    eb.parent = arm.data.edit_bones[b["parent"]]
    eb.use_connect = False
    eb.use_deform = True
bpy.ops.object.mode_set(mode="OBJECT")
bone_names = rig["bone_names"]


def bind(o, WI=None, WW=None, bone=None):
    """Веса и модификатор арматуры: по массивам (до 4 влияний) или целиком на одну кость."""
    n = len(o.data.vertices)
    if bone is not None:
        g = o.vertex_groups.new(name=bone)
        g.add(list(range(n)), 1.0, "REPLACE")
    else:
        groups = {}
        for k in range(WI.shape[1]):
            for b in np.unique(WI[:, k]):
                sel = np.nonzero((WI[:, k] == b) & (WW[:, k] > 1e-4))[0]
                if not len(sel):
                    continue
                g = groups.get(int(b)) or o.vertex_groups.new(name=bone_names[int(b)])
                groups[int(b)] = g
                for v, w in zip(sel.tolist(), WW[sel, k].tolist()):
                    g.add([v], w, "REPLACE")
    o.parent = arm
    o.matrix_parent_inverse = arm.matrix_world.inverted()
    md = o.modifiers.new("Armature", "ARMATURE")
    md.object = arm


# --- детали
garment = bpy.data.collections.new("garment")
sc.collection.children.link(garment)
final = []
atlas_img = normal_img = None
qd = np.load(man["quads"]) if man.get("quads") else None
if qd is not None:
    atlas_img = C.bake_atlas(man["atlas"], os.path.join(OUT, NAME + "_atlas.png"))
    normal_img = C.load_detail(man["atlas"], OUT, NAME)
    for key, p in parts.items():
        if p.get("mesh") != "quad":
            continue
        o = C.quad_object(key, qd, collection=garment)
        o.data.materials.append(C.finish_material(p, atlas_img, p.get("two_sided", False), normal_img))
        if key in rig["rigid"]:
            bind(o, bone=rig["rigid"][key])
        else:
            bind(o, qd[key + "|WI"], qd[key + "|WW"])
        st = p["stats"]
        report["parts"][key] = dict(pos=p["pos"], mesh="quad", tris=st["triangles"], quads=st["quads"],
                                    tris_only=st["tris"], verts=st["verts"],
                                    non_manifold_edges=0 if p.get("two_sided") else C.non_manifold(o),
                                    group=p["group"], layer=p.get("layer", 0), brep_dev_max_mm=st["brep_dev_max_mm"],
                                    aspect_max=round(st["aspect_max"], 2),
                                    uv_stretch=[st["uv_stretch_min"], st["uv_stretch_max"]],
                                    bind=rig["rigid"].get(key, "auto"), dynamics=p.get("dynamics"))
        final.append(o)

if GLB != "-":
    before = set(sc.objects)
    bpy.ops.import_scene.gltf(filepath=GLB)
    new = [o for o in sc.objects if o not in before]
    found = {}
    for o in new:
        if o.type != "MESH":
            continue
        for cand in (o.name, o.parent.name if o.parent else "", o.data.name):
            base = cand.split(".")[0]
            if base in parts:
                found.setdefault(base, []).append(o)
                break
    for key, objs in found.items():
        p = parts[key]
        bpy.ops.object.select_all(action="DESELECT")
        for o in objs:
            o.select_set(True)
        bpy.context.view_layer.objects.active = objs[0]
        if len(objs) > 1:
            bpy.ops.object.join()
        o = bpy.context.view_layer.objects.active
        mw = o.matrix_world.copy()
        o.parent = None
        o.matrix_world = C.CAD_TO_BL @ mw
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
        o.name = o.data.name = key
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        try:
            bpy.ops.mesh.remove_doubles(threshold=0.0001, use_sharp_edge_from_normals=True)
        except TypeError:
            bpy.ops.mesh.remove_doubles(threshold=0.0001)
        bpy.ops.object.mode_set(mode="OBJECT")
        for c in o.users_collection:
            c.objects.unlink(o)
        garment.objects.link(o)
        o.data.materials.clear()
        o.data.materials.append(C.finish_material(p))
        bind(o, bone=rig["rigid"][key])
        tris = sum(len(f.vertices) - 2 for f in o.data.polygons)
        report["parts"][key] = dict(pos=p["pos"], mesh="cad", tris=tris, quads=0, verts=len(o.data.vertices),
                                    non_manifold_edges=C.non_manifold(o), group=p["group"], layer=p.get("layer", 0),
                                    bind=rig["rigid"][key])
        final.append(o)
    for o in list(sc.objects):
        if o in new and o.type == "EMPTY":
            bpy.data.objects.remove(o)
for k in parts:
    if k not in report["parts"]:
        report["warnings"].append(f"{k}: деталь не попала в сборку")

# --- тело со срезанными полигонами под одеждой (исходный меш тела остаётся в сцене скрытым)
masked = body.copy()
masked.data = body.data.copy()
masked.name = masked.data.name = "Body_masked"
sc.collection.objects.link(masked)
hid = set(rig["hidden_polys"])
if hid:
    bm = bmesh.new()
    bm.from_mesh(masked.data)
    bm.faces.ensure_lookup_table()
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if f.index in hid], context="FACES")
    bm.to_mesh(masked.data)
    bm.free()
if not masked.data.materials:
    m = bpy.data.materials.new("M_body")
    m.diffuse_color = (0.80, 0.72, 0.68, 1)
    masked.data.materials.append(m)
body.hide_render = True
body.hide_viewport = True
body["bp3d_source_body"] = True
report["body"] = dict(file=os.path.basename(rig["body_file"]), polys=len(body.data.polygons), hidden_polys=len(hid),
                      bones=len(arm.data.bones), dynamic_bones=len(rig["bones"]))

# ---------------------------------------------------------------- рендеры
C.set_engine(sc, "BLENDER_WORKBENCH")
sh = sc.display.shading
sh.light = "STUDIO"
sh.color_type = "TEXTURE"
sh.show_cavity = True
sh.cavity_type = "BOTH"
sh.show_object_outline = True
sh.show_specular_highlight = False
sh.show_backface_culling = False
sc.render.film_transparent = False
sh.background_type = "VIEWPORT"
sh.background_color = (0.93, 0.93, 0.93)
bpy.context.view_layer.update()
show = final + [masked]
mn, mx = C.bounds(show)
gmn, gmx = C.bounds(final)
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
sc.collection.objects.link(cam)
sc.camera = cam
renders = {}


def shot(name, d, lo, hi, res=(1100, 1500), pad=1.06):
    d = Vector(d).normalized()
    ctr = (Vector(lo) + Vector(hi)) / 2
    ext = Vector(hi) - Vector(lo)
    cam.data.type = "ORTHO"
    aspect = res[0] / res[1]
    width = max(abs(ext.x), abs(ext.y))
    width = width * (1.0 if abs(d.x) < 0.05 or abs(d.y) < 0.05 else 1.15)
    # ortho_scale — размер кадра по длинной стороне
    cam.data.ortho_scale = (max(ext.z, width / aspect) if aspect < 1 else max(width, ext.z * aspect)) * pad
    cam.location = ctr + d * 10
    cam.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
    cam.data.clip_start, cam.data.clip_end = 0.1, 30
    sc.render.resolution_x, sc.render.resolution_y = res
    path = os.path.join(OUT, "render_" + name + ".png")
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)
    renders[name] = path


shot("front", (0, -1, 0), mn, mx)
shot("back", (0, 1, 0), mn, mx)
shot("side", (1, 0, 0), mn, mx)
shot("q", (0.7, -1, 0.25), mn, mx)
h = gmx.z - gmn.z
shot("bodice", (0.35, -1, 0.1), (gmn.x, gmn.y, gmn.z + h * 0.55), gmx, res=(1300, 1100))
shot("hem", (-0.5, -1, -0.05), gmn, (gmx.x, gmx.y, gmn.z + h * 0.5), res=(1300, 1100))
shot("sleeve", (1, -0.6, 0.15), (0, gmn.y, gmn.z + h * 0.45), gmx, res=(1300, 1100))
sh.color_type = "SINGLE"
sh.single_color = (0.80, 0.80, 0.80)
wires = C.wire_overlay(final, thickness=0.0007)
shot("wire_front", (0.15, -1, 0.05), gmn, gmx)
shot("wire_back", (-0.25, 1, 0.1), gmn, gmx)
shot("wire_side", (1, -0.2, 0.05), gmn, gmx)
for w in wires:
    bpy.data.objects.remove(w)
sh.color_type = "TEXTURE"
bpy.data.objects.remove(cam)

report["renders"] = renders
report["total_tris"] = sum(v["tris"] for v in report["parts"].values())
report["total_tris_ext"] = report["total_tris"]
report["total_quads"] = sum(v.get("quads", 0) for v in report["parts"].values())
report["bbox_m"] = [list(gmn), list(gmx)]
report["atlas"] = dict(px=man["atlas"]["px"], px_per_cm=man["atlas"]["px_per_cm"], islands=len(man["atlas"]["islands"]),
                       normal=os.path.basename(man["atlas"]["normal"]) if man["atlas"].get("normal") else None,
                       foldmask=os.path.basename(man["atlas"]["foldmask"]) if man["atlas"].get("foldmask") else None,
                       texture=os.path.basename(atlas_img.filepath_raw)) if atlas_img else None

blend = os.path.join(OUT, NAME + ".blend")
bpy.ops.wm.save_as_mainfile(filepath=blend)
# Экспорт: арматура, одежда и тело со срезанными полигонами. Исходное тело в FBX не идёт — это отдельный ассет.
bpy.ops.object.select_all(action="DESELECT")
arm.hide_viewport = False
for o in final + [masked, arm]:
    o.hide_set(False)
    o.select_set(True)
bpy.context.view_layer.objects.active = arm
bpy.ops.export_scene.fbx(filepath=os.path.join(OUT, NAME + ".fbx"), use_selection=True,
                         apply_scale_options="FBX_SCALE_UNITS", axis_forward="-Z", axis_up="Y",
                         object_types={"ARMATURE", "MESH"}, mesh_smooth_type="FACE", add_leaf_bones=False,
                         bake_anim=False, use_armature_deform_only=False)
bpy.ops.export_scene.gltf(filepath=os.path.join(OUT, NAME + ".glb"), export_format="GLB", use_selection=True)
report["files"] = dict(blend=blend, fbx=os.path.join(OUT, NAME + ".fbx"), glb=os.path.join(OUT, NAME + ".glb"))
json.dump(report, open(os.path.join(OUT, "report.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("BP3D_DONE", report["total_tris"])
