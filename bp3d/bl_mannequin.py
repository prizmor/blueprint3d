"""Запускается Blender'ом: blender -b --factory-startup --python bl_mannequin.py -- parts.npz skeleton.json out_dir name
Собирает манекен: замкнутые части -> один меш (воксельный ремеш + сглаживание), скелет Unity Humanoid
в T-позе, автоматические веса, развёртка. Результат: <name>.blend, <name>.glb, превью."""
import bpy, json, math, os, sys
import numpy as np
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bl_common as C

argv = sys.argv[sys.argv.index("--") + 1:]
NPZ, SKEL, OUT, NAME = argv[:4]
VOXEL = float(argv[4]) if len(argv) > 4 else 0.006

bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
data = np.load(NPZ)
keys = sorted({k.split("|")[0] for k in data.files})
objs = [C.quad_object(k, data) for k in keys]
bpy.ops.object.select_all(action="DESELECT")
for o in objs:
    o.select_set(True)
bpy.context.view_layer.objects.active = objs[0]
bpy.ops.object.join()
body = bpy.context.view_layer.objects.active
body.name = body.data.name = "Body"

# Объединение перекрывающихся тел: воксельный ремеш даёт один замкнутый меш без внутренних стенок,
# сглаживание убирает острые впадины по линиям стыка (плечо, пах, грудь).
md = body.modifiers.new("remesh", "REMESH")
md.mode = "VOXEL"
md.voxel_size = VOXEL
md.adaptivity = 0.0
bpy.ops.object.modifier_apply(modifier=md.name)
md = body.modifiers.new("smooth", "SMOOTH")
md.factor = 0.5
md.iterations = 14
bpy.ops.object.modifier_apply(modifier=md.name)
zmin = min(v.co.z for v in body.data.vertices)
for v in body.data.vertices:
    v.co.z -= zmin
for p in body.data.polygons:
    p.use_smooth = True
body.data.materials.clear()
mat = bpy.data.materials.new("M_body")
mat.use_nodes = True
bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
bsdf.inputs["Base Color"].default_value = (0.80, 0.74, 0.70, 1)
bsdf.inputs["Roughness"].default_value = 0.6
mat.diffuse_color = (0.80, 0.74, 0.70, 1)
body.data.materials.append(mat)

# развёртка (нужна для маски скрытия тела под одеждой)
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.select_all(action="SELECT")
bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=0.003)
bpy.ops.object.mode_set(mode="OBJECT")

# скелет
skel = json.load(open(SKEL, encoding="utf-8"))
arm_data = bpy.data.armatures.new("Armature")
arm = bpy.data.objects.new("Armature", arm_data)
sc.collection.objects.link(arm)
bpy.context.view_layer.objects.active = arm
bpy.ops.object.mode_set(mode="EDIT")
for name, parent, a, b in skel:
    eb = arm_data.edit_bones.new(name)
    eb.head = Vector(C.cad_to_bl(a))
    eb.tail = Vector(C.cad_to_bl(b))
    if parent:
        eb.parent = arm_data.edit_bones[parent]
        eb.use_connect = (eb.head - eb.parent.tail).length < 1e-5
for eb in arm_data.edit_bones:              # единообразный крен: ось Z кости — вперёд персонажа (−Y Blender)
    eb.align_roll(Vector((0, -1, 0)))
bpy.ops.object.mode_set(mode="OBJECT")

bpy.ops.object.select_all(action="DESELECT")
body.select_set(True)
arm.select_set(True)
bpy.context.view_layer.objects.active = arm
bpy.ops.object.parent_set(type="ARMATURE_AUTO")
weighted = sum(1 for v in body.data.vertices if v.groups)
if weighted < len(body.data.vertices) * 0.99:       # тепловые веса не сошлись — веса по оболочкам костей
    print("BP3D_MANNEQUIN heat weights failed, envelope fallback")
    bpy.ops.object.parent_set(type="ARMATURE_ENVELOPE")
bpy.context.view_layer.objects.active = body
bpy.ops.object.vertex_group_limit_total(group_select_mode="ALL", limit=4)
bpy.ops.object.vertex_group_normalize_all(group_select_mode="ALL", lock_active=False)

# превью
C.set_engine(sc, "BLENDER_WORKBENCH")
sh = sc.display.shading
sh.light = "STUDIO"
sh.color_type = "MATERIAL"
sh.show_cavity = True
sh.show_object_outline = True
sh.background_type = "VIEWPORT"
sh.background_color = (0.93, 0.93, 0.93)
sc.render.resolution_x, sc.render.resolution_y = 900, 1300
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
sc.collection.objects.link(cam)
sc.camera = cam
mn, mx = C.bounds([body])
ctr, size = (mn + mx) / 2, max(mx - mn)
cam.data.type = "ORTHO"
for name, d in (("front", (0, -1, 0)), ("side", (-1, 0, 0)), ("back", (0, 1, 0)), ("q", (-0.7, -1, 0.25))):
    d = Vector(d).normalized()
    cam.location = ctr + d * size * 4
    cam.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
    cam.data.ortho_scale = size * 1.06
    cam.data.clip_end = size * 20
    sc.render.filepath = os.path.join(OUT, f"preview_{name}.png")
    bpy.ops.render.render(write_still=True)
bpy.data.objects.remove(cam)

C.save_clean(os.path.join(OUT, NAME + ".blend"))
bpy.ops.object.select_all(action="DESELECT")
body.select_set(True)
arm.select_set(True)
bpy.ops.export_scene.gltf(filepath=os.path.join(OUT, NAME + ".glb"), export_format="GLB", use_selection=True)
print("BP3D_DONE", len(body.data.vertices), len(body.data.polygons), weighted)
