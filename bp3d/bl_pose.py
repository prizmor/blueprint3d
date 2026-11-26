"""Запускается Blender'ом: blender -b <модель.blend> --python bl_pose.py -- shots.json out_dir
Ставит собранную модель с ригом в позы и рендерит кадры: проверочные (матовый Workbench, каркас) и
показ в toon-стиле (EEVEE: ступени света через Shader to RGB, обводка вывернутой оболочкой).

shots.json: {"shots": [{"name", "pose": {кость: 16 чисел 4×4 в координатах персонажа, мм}, "mode":
"solid" | "wire" | "toon" | "matte" | "inspect", "dir": [x, y, z] (откуда смотрит камера, оси Blender), "target":
[x, y, z] мм в координатах персонажа или null (вся фигура), "radius": мм, "res": [w, h], "parts": [ключи деталей]
или null (все)}]}. "inspect" — осмотр формы: светлый матовый материал с картой нормалей вещи и свет со всех сторон,
включая снизу (тёмная палитра прячет вмятины, швы и щели); parts — показать только эти детали."""
import bpy, json, math, os, sys
import numpy as np
from mathutils import Vector, Matrix

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bl_common as C

argv = sys.argv[sys.argv.index("--") + 1:]
SHOTS, OUT = argv[:2]
cfg = json.load(open(SHOTS, encoding="utf-8"))
os.makedirs(OUT, exist_ok=True)
sc = bpy.context.scene
arm = next(o for o in sc.objects if o.type == "ARMATURE")
meshes = [o for o in sc.objects if o.type == "MESH" and not o.get("bp3d_source_body") and not o.hide_render]
CM = Matrix(((0, -0.001, 0, 0), (0.001, 0, 0, 0), (0, 0, 0.001, 0), (0, 0, 0, 1)))        # персонаж (мм) -> Blender (м)
CMi = CM.inverted()


def apply_pose(pose):
    """Поставить кости по матрицам «поза относительно покоя». matrix_basis считается из матриц покоя,
    поэтому результат не зависит от крена костей и порядка обновления сцены."""
    A = arm.matrix_world
    Ai = A.inverted()
    world = {}
    for b in arm.data.bones:
        m = pose.get(b.name)
        Mw = Matrix([m[0:4], m[4:8], m[8:12], m[12:16]]) if m else None
        if Mw is None:                                   # кости нет в позе — идёт за родителем
            world[b.name] = world[b.parent.name] if b.parent else Matrix.Identity(4)
        else:
            world[b.name] = Ai @ CM @ Mw @ CMi @ A
    for pb in arm.pose.bones:
        b = pb.bone
        pose_b = world[b.name] @ b.matrix_local
        if b.parent:
            pose_p = world[b.parent.name] @ b.parent.matrix_local
            pb.matrix_basis = (b.parent.matrix_local.inverted() @ b.matrix_local).inverted() @ (pose_p.inverted() @ pose_b)
        else:
            pb.matrix_basis = b.matrix_local.inverted() @ pose_b
    bpy.context.view_layer.update()


def bounds_posed():
    dg = bpy.context.evaluated_depsgraph_get()
    lo, hi = Vector((1e9,) * 3), Vector((-1e9,) * 3)
    for o in [o for o in meshes if not o.hide_render]:
        e = o.evaluated_get(dg)
        for c in e.bound_box:
            w = e.matrix_world @ Vector(c)
            lo = Vector(map(min, lo, w))
            hi = Vector(map(max, hi, w))
    return lo, hi


cam = bpy.data.objects.new("pose_cam", bpy.data.cameras.new("pose_cam"))
sc.collection.objects.link(cam)
sc.camera = cam


def frame(sh):
    d = Vector(sh.get("dir", (0.6, -1, 0.15))).normalized()
    res = sh.get("res", (1100, 1500))
    sc.render.resolution_x, sc.render.resolution_y = res
    aspect = res[0] / res[1]
    if sh.get("target") is not None:
        t = Vector(C.cad_to_bl(sh["target"]))
        r = sh.get("radius", 250.0) / 1000.0
        size = 2 * r
        ctr = t
    else:
        lo, hi = bounds_posed()
        ctr = (lo + hi) / 2
        ext = hi - lo
        width = max(ext.x, ext.y) * (1.0 if abs(d.x) < 0.05 or abs(d.y) < 0.05 else 1.12)
        size = (max(ext.z, width / aspect) if aspect < 1 else max(width, ext.z * aspect)) * 1.06
    cam.data.type = "ORTHO"
    cam.data.ortho_scale = size
    cam.location = ctr + d * 10
    cam.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
    cam.data.clip_start, cam.data.clip_end = 0.1, 30


# ---------------------------------------------------------------- режимы рендера
def setup_solid(wire=False):
    C.set_engine(sc, "BLENDER_WORKBENCH")
    s = sc.display.shading
    s.light, s.show_cavity, s.cavity_type = "STUDIO", True, "BOTH"
    s.show_object_outline, s.show_specular_highlight, s.show_backface_culling = True, False, False
    s.background_type, s.background_color = "VIEWPORT", (0.93, 0.93, 0.93)
    s.color_type = "SINGLE" if wire else "TEXTURE"
    s.single_color = (0.80, 0.80, 0.80)


_toon_done = False
SHADE = {  # отделка: (доля тени, блик) — ткань матовая, ткань с блеском, кожа, металл, пластик
    "cloth": (0.64, 0.0), "satin": (0.60, 0.22), "leather": (0.52, 0.12), "metal": (0.48, 0.55),
    "chrome": (0.48, 0.7), "plastic": (0.56, 0.15), "paint": (0.6, 0.0), "rubber": (0.55, 0.0),
}


def toon_material(m):
    """Материал → toon: базовый цвет (атлас или цвет) × ступени света. Свет считает Diffuse BSDF,
    Shader to RGB превращает его в число, ColorRamp режет на две ступени с цветной тенью."""
    if m.get("bp3d_toon"):
        return
    m["bp3d_toon"] = True
    m.use_nodes = True
    nt = m.node_tree
    bsdf = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
    out = next((n for n in nt.nodes if n.type == "OUTPUT_MATERIAL"), None) or nt.nodes.new("ShaderNodeOutputMaterial")
    base_link = bsdf.inputs["Base Color"].links[0].from_socket if bsdf and bsdf.inputs["Base Color"].links else None
    base_col = tuple(bsdf.inputs["Base Color"].default_value) if bsdf else tuple(m.diffuse_color)
    shade, spec = SHADE.get(m.get("bp3d_finish", "cloth"), (0.6, 0.0))
    dif = nt.nodes.new("ShaderNodeBsdfDiffuse")
    s2r = nt.nodes.new("ShaderNodeShaderToRGB")
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.interpolation = "CONSTANT"
    e = ramp.color_ramp.elements
    e[0].position, e[0].color = 0.0, (shade * 0.92, shade * 0.9, shade * 1.06, 1)        # тень чуть холоднее
    e[1].position, e[1].color = 0.30, (1, 1, 1, 1)
    mix = nt.nodes.new("ShaderNodeMixRGB")
    mix.blend_type = "MULTIPLY"
    mix.inputs[0].default_value = 1.0
    nt.links.new(dif.outputs[0], s2r.inputs[0])
    nt.links.new(s2r.outputs[0], ramp.inputs[0])
    if base_link:
        nt.links.new(base_link, mix.inputs[1])
    else:
        mix.inputs[1].default_value = base_col
    nt.links.new(ramp.outputs[0], mix.inputs[2])
    last = mix.outputs[0]
    if spec > 0:                                         # жёсткий блик: глянец через порог
        gl = nt.nodes.new("ShaderNodeBsdfGlossy") if hasattr(bpy.types, "ShaderNodeBsdfGlossy") else nt.nodes.new("ShaderNodeBsdfAnisotropic")
        gl.inputs["Roughness"].default_value = 0.18
        s2 = nt.nodes.new("ShaderNodeShaderToRGB")
        r2 = nt.nodes.new("ShaderNodeValToRGB")
        r2.color_ramp.interpolation = "CONSTANT"
        r2.color_ramp.elements[0].color = (0, 0, 0, 1)
        r2.color_ramp.elements[1].position, r2.color_ramp.elements[1].color = 0.92, (spec, spec, spec, 1)
        add = nt.nodes.new("ShaderNodeMixRGB")
        add.blend_type = "ADD"
        add.inputs[0].default_value = 1.0
        nt.links.new(gl.outputs[0], s2.inputs[0])
        nt.links.new(s2.outputs[0], r2.inputs[0])
        nt.links.new(last, add.inputs[1])
        nt.links.new(r2.outputs[0], add.inputs[2])
        last = add.outputs[0]
    em = nt.nodes.new("ShaderNodeEmission")
    nt.links.new(last, em.inputs[0])
    nt.links.new(em.outputs[0], out.inputs["Surface"])
    m.use_backface_culling = False


def setup_toon():
    global _toon_done
    C.set_engine(sc, "BLENDER_EEVEE_NEXT", "BLENDER_EEVEE")
    for vt in ("Standard",):
        try:
            sc.view_settings.view_transform = vt
        except TypeError:
            pass
    try:
        sc.view_settings.look = "None"
    except TypeError:
        pass
    if _toon_done:
        return
    _toon_done = True
    world = bpy.data.worlds.new("toon_world")
    world.use_nodes = True
    wt = world.node_tree
    bg = next(n for n in wt.nodes if n.type == "BACKGROUND")
    wout = next(n for n in wt.nodes if n.type == "OUTPUT_WORLD")
    bg.inputs["Color"].default_value = (0.86, 0.88, 0.91, 1)
    bg.inputs["Strength"].default_value = 1.0
    dim = wt.nodes.new("ShaderNodeBackground")                # фон виден камере, но сцену почти не освещает:
    dim.inputs["Color"].default_value = (0.5, 0.52, 0.6, 1)   # ступени света даёт одно солнце
    dim.inputs["Strength"].default_value = 0.12
    lp = wt.nodes.new("ShaderNodeLightPath")
    mx = wt.nodes.new("ShaderNodeMixShader")
    wt.links.new(lp.outputs["Is Camera Ray"], mx.inputs[0])
    wt.links.new(dim.outputs[0], mx.inputs[1])
    wt.links.new(bg.outputs[0], mx.inputs[2])
    wt.links.new(mx.outputs[0], wout.inputs["Surface"])
    sc.world = world
    sun = bpy.data.objects.new("toon_sun", bpy.data.lights.new("toon_sun", "SUN"))
    sun.data.energy = 1.0
    sun.data.angle = math.radians(2)
    sun.rotation_euler = (math.radians(52), math.radians(-8), math.radians(-38))
    sc.collection.objects.link(sun)
    line = bpy.data.materials.new("BP3D_outline")
    line.use_nodes = True
    nt = line.node_tree
    nt.nodes.clear()
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs[0].default_value = (0.05, 0.05, 0.08, 1)
    o = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(em.outputs[0], o.inputs["Surface"])
    line.use_backface_culling = True
    for ob in meshes:
        for m in ob.data.materials:
            if m:
                toon_material(m)
        ob.data.materials.append(line)                   # обводка: вывернутая оболочка, видна только с изнанки
        md = ob.modifiers.new("outline", "SOLIDIFY")
        md.thickness = 0.0032
        md.offset = 1.0
        md.use_flip_normals = True
        md.use_rim = False
        md.material_offset = len(ob.data.materials) - 1
        md.use_quality_normals = True


def setup_matte():
    C.set_engine(sc, "CYCLES")
    sc.cycles.samples = 96
    sc.cycles.use_denoising = True
    if not bpy.data.worlds.get("matte_world"):
        w = bpy.data.worlds.new("matte_world")
        w.use_nodes = True
        bg = next(n for n in w.node_tree.nodes if n.type == "BACKGROUND")
        bg.inputs["Color"].default_value = (0.75, 0.77, 0.80, 1)
        bg.inputs["Strength"].default_value = 0.9
        sun = bpy.data.objects.new("matte_sun", bpy.data.lights.new("matte_sun", "SUN"))
        sun.data.energy = 2.5
        sun.data.angle = math.radians(12)
        sun.rotation_euler = (math.radians(50), math.radians(-6), math.radians(-35))
        sc.collection.objects.link(sun)
    sc.world = bpy.data.worlds["matte_world"]


_inspect = {}


def inspect_material(src):
    """Светлый матовый материал осмотра; карта нормалей — та же, что у вещи. Пластик и металл — тёмные, чтобы
    шнурки, люверсы и фурнитура отличались от основы."""
    key = src.name if src else "-"
    if key in _inspect:
        return _inspect[key]
    m = bpy.data.materials.new("BP3D_inspect")
    m.use_nodes = True
    nt = m.node_tree
    bs = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    dark = src is not None and src.get("bp3d_finish") in ("plastic", "metal", "chrome")
    bs.inputs["Base Color"].default_value = (0.09, 0.09, 0.1, 1) if dark else (0.66, 0.64, 0.6, 1)
    bs.inputs["Roughness"].default_value = 0.65
    if src is not None and src.use_nodes:
        img = next((n.image for n in src.node_tree.nodes if n.type == "TEX_IMAGE" and n.image
                    and "normal" in n.image.name.lower()), None)
        if img is not None:
            t = nt.nodes.new("ShaderNodeTexImage")
            t.image = img
            nm = nt.nodes.new("ShaderNodeNormalMap")
            nt.links.new(t.outputs["Color"], nm.inputs["Color"])
            nt.links.new(nm.outputs["Normal"], bs.inputs["Normal"])
    _inspect[key] = m
    return m


def setup_inspect():
    C.set_engine(sc, "BLENDER_EEVEE_NEXT", "BLENDER_EEVEE")
    try:
        sc.view_settings.view_transform = "Standard"
    except TypeError:
        pass
    if not bpy.data.worlds.get("inspect_world"):
        w = bpy.data.worlds.new("inspect_world")
        w.use_nodes = True
        bg = next(n for n in w.node_tree.nodes if n.type == "BACKGROUND")
        bg.inputs["Color"].default_value = (0.3, 0.31, 0.33, 1)
        bg.inputs["Strength"].default_value = 1.0
        for i, (d, e) in enumerate((((1, -1, 1.2), 3.0), ((-1, 0.5, 0.8), 1.2), ((0, 1, 0.3), 0.8), ((0.3, -0.4, -1.0), 1.6))):
            L = bpy.data.objects.new(f"inspect_sun{i}", bpy.data.lights.new(f"inspect_sun{i}", "SUN"))
            L.data.energy = e
            L.rotation_euler = (-Vector(d)).to_track_quat("-Z", "Y").to_euler()
            sc.collection.objects.link(L)
            L["bp3d_inspect"] = True
    sc.world = bpy.data.worlds["inspect_world"]
    for o in sc.objects:                                 # свет осмотра — только в этом режиме
        if o.type == "LIGHT":
            o.hide_render = not o.get("bp3d_inspect")


def end_inspect():
    for o in sc.objects:
        if o.type == "LIGHT":
            o.hide_render = bool(o.get("bp3d_inspect"))


renders = {}
order = {"solid": 0, "wire": 1, "matte": 2, "inspect": 3, "toon": 4}  # toon меняет материалы — рендерится последним
for sh in sorted(cfg["shots"], key=lambda s: order[s.get("mode", "solid")]):
    mode = sh.get("mode", "solid")
    apply_pose(sh.get("pose") or {})
    wires, saved, shown = [], {}, {}
    if sh.get("parts"):                                  # только эти детали (и без тела, если его не просили)
        want = set(sh["parts"])
        for o in [o for o in sc.objects if o.type == "MESH"]:
            shown[o.name] = o.hide_render
            o.hide_render = o.name.split(".")[0] not in want
    if mode in ("solid", "wire"):
        setup_solid(mode == "wire")
        if mode == "wire":
            wires = C.wire_overlay([o for o in meshes if o.name != "Body_masked"], thickness=0.0007)
    elif mode == "matte":
        setup_matte()
    elif mode == "inspect":
        setup_inspect()
        for o in meshes:
            saved[o.name] = [s.material for s in o.material_slots]
            for s in o.material_slots:
                s.material = inspect_material(s.material)
    else:
        setup_toon()
    frame(sh)
    path = os.path.join(OUT, sh["name"] + ".png")
    sc.render.filepath = path
    sc.render.film_transparent = False
    bpy.ops.render.render(write_still=True)
    renders[sh["name"]] = path
    for w in wires:
        bpy.data.objects.remove(w)
    for o in meshes:                                     # вернуть материалы и видимость после осмотра
        if o.name in saved:
            for s, m in zip(o.material_slots, saved[o.name]):
                s.material = m
    if mode == "inspect":
        end_inspect()
    for o in sc.objects:
        if o.name in shown:
            o.hide_render = shown[o.name]
    print("BP3D_POSE", sh["name"])
json.dump(renders, open(os.path.join(OUT, "renders.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("BP3D_DONE", len(renders))
