"""Крупные планы деталей с сеткой треугольников (диагностика геометрии).
blender -b <model.blend> --python bl_inspect.py -- <out_dir> <key1,key2,...> [<tag>]
Для каждой детали: заливка + рёбра треугольников, два ракурса."""
import bpy, math, os, sys
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
OUT, KEYS = argv[0], argv[1].split(",")
TAG = argv[2] if len(argv) > 2 else ""
sc = bpy.context.scene
sc.render.engine = "BLENDER_WORKBENCH"
sh = sc.display.shading
sh.light = "STUDIO"
sh.color_type = "SINGLE"
sh.single_color = (0.75, 0.75, 0.75)
sh.show_cavity = False
sc.render.resolution_x, sc.render.resolution_y = 1400, 1000
sc.world.color = (1, 1, 1)
for c in bpy.data.collections:
    c.hide_render = False

wire_mat = bpy.data.materials.new("wire")
wire_mat.diffuse_color = (0.05, 0.05, 0.05, 1)
cam = sc.camera
os.makedirs(OUT, exist_ok=True)
for key in KEYS:
    o = bpy.data.objects.get(key)
    if o is None:
        print("нет", key)
        continue
    # каркас поверх
    w = o.copy()
    w.data = o.data.copy()
    sc.collection.objects.link(w)
    m = w.modifiers.new("w", "WIREFRAME")
    m.thickness = 0.0012
    m.use_replace = True
    w.data.materials.clear()
    w.data.materials.append(wire_mat)
    sh.color_type = "MATERIAL"
    for mat in bpy.data.materials:
        if mat is not wire_mat:
            mat.diffuse_color = (0.78, 0.78, 0.78, 1)
    pts = [o.matrix_world @ Vector(c) for c in o.bound_box]
    mn = Vector([min(p[i] for p in pts) for i in range(3)])
    mx = Vector([max(p[i] for p in pts) for i in range(3)])
    ctr, size = (mn + mx) / 2, max(mx - mn)
    for name, d in (("a", (-0.6, -1.0, 0.7)), ("b", (0.5, -0.7, 1.4))):
        d = Vector(d).normalized()
        cam.location = ctr + d * size * 2.2
        cam.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
        cam.data.type = "PERSP"
        cam.data.lens = 50
        cam.data.clip_start = 0.01
        sc.render.filepath = os.path.join(OUT, f"inspect_{TAG}{key}_{name}.png")
        bpy.ops.render.render(write_still=True)
    bpy.data.objects.remove(w)
print("INSPECT_DONE")
