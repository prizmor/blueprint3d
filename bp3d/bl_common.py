"""Общие функции скриптов Blender (bl_build, bl_garment, bl_pose, bl_toon): квадовые меши из npz,
запекание атласа цветов и узоров, материалы, камера. Импортируется из каталога bp3d: скрипты добавляют
его в sys.path."""
import bpy, math, os
import numpy as np
from mathutils import Vector, Matrix

CAD_TO_BL = Matrix.Rotation(math.radians(90), 4, "Z")     # CAD X (назад) -> Blender +Y: перёд смотрит в −Y


def cad_to_bl(P):
    """Точки CAD (мм; X назад, Z вверх) -> Blender (м; перёд в −Y, Z вверх)."""
    P = np.asarray(P, float)
    return np.stack([-P[..., 1], P[..., 0], P[..., 2]], axis=-1) * 0.001


def set_engine(sc, *names):
    for n in names:
        try:
            sc.render.engine = n
            return n
        except TypeError:
            continue
    return sc.render.engine


# ------------------------------------------------------------------ квадовые меши
def quad_object(key, data, collection=None, orient=True):
    """Объект-меш из массивов quads.npz: квады как есть (без пересчёта топологии), UV из атласа,
    острые рёбра, сглаживание. orient — сразу в ориентации Blender (иначе в координатах CAD, метры)."""
    V = data[key + "|V"]
    F = data[key + "|F"]
    UV = data[key + "|UV"]
    V = cad_to_bl(V) if orient else np.asarray(V) * 0.001
    faces = [[int(i) for i in f if i >= 0] for f in F]
    me = bpy.data.meshes.new(key)
    me.from_pydata([tuple(v) for v in V], [], faces)
    me.update()
    uvl = me.uv_layers.new(name="UVMap")
    flat = np.zeros((len(me.loops), 2), np.float32)
    k = 0
    for fi, f in enumerate(faces):
        n = len(f)
        flat[k:k + n] = UV[fi][:n]
        k += n
    uvl.data.foreach_set("uv", flat.ravel())
    for p in me.polygons:
        p.use_smooth = True
    sharp = data[key + "|sharp"]
    if len(sharp):
        want = {(min(a, b), max(a, b)) for a, b in sharp.tolist()}
        for e in me.edges:
            a, b = e.vertices
            if (min(a, b), max(a, b)) in want:
                e.use_edge_sharp = True
    tag = me.attributes.new("bp3d_tag", "INT", "FACE")
    tag.data.foreach_set("value", np.asarray(data[key + "|tag"], np.int32))
    o = bpy.data.objects.new(key, me)
    (collection or bpy.context.scene.collection).objects.link(o)
    return o


# ------------------------------------------------------------------ атлас
def _pattern(img, x0, y0, x1, y1, pxmm, isl, d):
    """Узор в прямоугольнике острова. Координаты узора — миллиметры острова (u вдоль рядов сетки,
    v поперёк), поэтому полосы и клетка идут ровно по петлям меша."""
    h, w = y1 - y0, x1 - x0
    if h <= 0 or w <= 0:
        return
    s = isl["scale"]
    U = (np.arange(w) + 0.5)[None, :] / pxmm / s          # мм детали
    V = (np.arange(h) + 0.5)[:, None] / pxmm / s
    Wm, Hm = w / pxmm / s, h / pxmm / s
    kind = d["kind"]
    col = np.array(d["color"], np.float32)
    if kind == "fill":                                   # весь остров одним цветом (подошва, вставка)
        img[y0:y1, x0:x1] = col
        return
    if kind == "stripe":
        t = U if d.get("dir", "v") == "u" else V          # dir — вдоль какой оси меняется цвет
        t = np.broadcast_to(t, (h, w))
        pitch = float(d.get("pitch", 20.0))
        m = ((t + float(d.get("offset", 0.0))) % pitch) < float(d.get("width", pitch / 2))
    elif kind == "check":
        pitch = float(d.get("pitch", 30.0))
        wd = float(d.get("width", pitch / 2))
        a = (np.broadcast_to(U, (h, w)) % pitch) < wd
        b = (np.broadcast_to(V, (h, w)) % pitch) < wd
        m = a ^ b if d.get("style", "gingham") == "checker" else (a | b)
        if d.get("style", "gingham") == "gingham":      # перекрестье плотнее: вторым проходом
            img[y0:y1, x0:x1][a & b] = col * 0.75
            m = a ^ b
            mix = 0.55
            img[y0:y1, x0:x1][m] = img[y0:y1, x0:x1][m] * (1 - mix) + col * mix
            return
    elif kind == "dots":
        pitch = float(d.get("pitch", 25.0))
        r = float(d.get("r", pitch * 0.22))
        uu = np.broadcast_to(U, (h, w))
        vv = np.broadcast_to(V, (h, w))
        row = np.floor(vv / pitch)
        du = (uu + (row % 2) * pitch / 2) % pitch - pitch / 2
        dv = vv % pitch - pitch / 2
        m = du * du + dv * dv < r * r
    elif kind == "trim":
        wd = float(d.get("width", 6.0))
        off = float(d.get("offset", 0.0))
        uu = np.broadcast_to(U, (h, w))
        vv = np.broadcast_to(V, (h, w))
        m = np.zeros((h, w), bool)
        for e in d.get("edges", ("v1",)):
            t = {"u0": uu, "u1": Wm - uu, "v0": vv, "v1": Hm - vv}[e]
            m |= (t >= off) & (t < off + wd)
    else:
        raise ValueError(f"узор {kind!r}: fill, stripe, check, dots, trim")
    img[y0:y1, x0:x1][m] = col


def bake_atlas(atlas, path, pad=10, spread=28):
    """Текстура атласа: каждый остров залит цветом детали, поверх — узоры. Поле pad пикселей вокруг
    острова заливается тем же цветом, чтобы на швах не проступал фон. Возвращает bpy-изображение."""
    px = int(atlas["px"])
    img = np.zeros((px, px, 3), np.float32)
    img[:] = (0.5, 0.5, 0.5)
    done = np.zeros((px, px), bool)
    pxmm = px / atlas["size_mm"]
    isl_px = []
    for isl in atlas["islands"]:
        x0, y0 = int(round(isl["x"] * px)), int(round(isl["y"] * px))
        x1, y1 = int(round((isl["x"] + isl["w"]) * px)), int(round((isl["y"] + isl["h"]) * px))
        x1, y1 = max(x1, x0 + 1), max(y1, y0 + 1)
        isl_px.append((x0, y0, x1, y1))
        img[max(y0 - pad, 0):min(y1 + pad, px), max(x0 - pad, 0):min(x1 + pad, px)] = isl["color"]
        done[max(y0 - pad, 0):min(y1 + pad, px), max(x0 - pad, 0):min(x1 + pad, px)] = True
    # Фон между островами заливается цветом ближайшего острова (расширение на spread пикселей): на
    # mip-уровнях в остров не подмешивается ни серый фон, ни цвет соседа.
    for _ in range(spread):
        for ax, sh in ((0, 1), (0, -1), (1, 1), (1, -1)):
            src = np.roll(done, sh, axis=ax)
            take = src & ~done
            if take.any():
                img[take] = np.roll(img, sh, axis=ax)[take]
                done |= take
    for isl, (x0, y0, x1, y1) in zip(atlas["islands"], isl_px):
        for d in isl.get("patterns", []):
            _pattern(img, x0, y0, x1, y1, pxmm, isl, d)
    im = bpy.data.images.new(os.path.splitext(os.path.basename(path))[0], px, px, alpha=False)
    rgba = np.ones((px, px, 4), np.float32)
    rgba[..., :3] = img
    im.pixels.foreach_set(rgba.ravel())
    im.filepath_raw = path
    im.file_format = "PNG"
    im.save()
    im.pack()
    return im


def load_detail(atlas, out, name):
    """Карта нормалей и маска складок, запечённые в Python (bp3d.folds.bake_maps): переименовать по имени
    модели и загрузить карту нормалей как изображение (цветовое пространство Non-Color). Нет карты — None."""
    img = None
    for key, suffix in (("normal", "_normal.png"), ("foldmask", "_foldmask.png")):
        src = atlas.get(key)
        if not src or not os.path.exists(src):
            continue
        dst = os.path.join(out, name + suffix)
        if os.path.abspath(src) != os.path.abspath(dst):
            os.replace(src, dst)
        atlas[key] = dst
        if key == "normal":
            img = bpy.data.images.load(dst)
            try:
                img.colorspace_settings.name = "Non-Color"
            except TypeError:
                pass
            img.pack()
    return img


# ------------------------------------------------------------------ материалы
_mats = {}


def finish_material(p, image=None, two_sided=False, normal=None):
    """Материал детали по отделке. Квадовые детали берут цвет из атласа (image) и рельеф из карты нормалей
    (normal, касательное пространство); CAD-детали — серый оттенок отделки или свой цвет. Один материал на
    сочетание отделки и источника цвета."""
    clear = p.get("group") == "glass"
    tex = image is not None and p.get("mesh") == "quad"
    nrm = normal is not None and p.get("mesh") == "quad"
    col = None if tex else p.get("color")
    key = p["finish"] + ("_clear" if clear else "") + ("_tex" if tex else "") + ("_nrm" if nrm else "") + \
        ("_%02x%02x%02x" % tuple(int(c * 255) for c in col) if col else "") + ("_2s" if two_sided else "")
    if key in _mats:
        return _mats[key]
    m = bpy.data.materials.new("M_" + key)
    m.use_nodes = True
    nt = m.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    g = p["gray"]
    c = col or (g, g, g)
    bsdf.inputs["Base Color"].default_value = (*c, 1)
    bsdf.inputs["Metallic"].default_value = p["metal"]
    bsdf.inputs["Roughness"].default_value = p["rough"]
    if tex:
        t = nt.nodes.new("ShaderNodeTexImage")
        t.image = image
        t.location = (-400, 300)
        nt.links.new(t.outputs["Color"], bsdf.inputs["Base Color"])
    if nrm:
        tn = nt.nodes.new("ShaderNodeTexImage")
        tn.image = normal
        try:
            tn.image.colorspace_settings.name = "Non-Color"
        except TypeError:
            pass
        tn.location = (-700, -200)
        nm = nt.nodes.new("ShaderNodeNormalMap")
        nm.location = (-400, -200)
        nm.uv_map = "UVMap"
        nt.links.new(tn.outputs["Color"], nm.inputs["Color"])
        nt.links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])
    if clear:
        bsdf.inputs["Alpha"].default_value = 0.25
    m.diffuse_color = (*c, 0.22 if clear else 1)
    m.metallic = 0.0          # Workbench: металл без окружения рендерится чёрным
    m.roughness = 0.5
    m.use_backface_culling = not two_sided
    m["bp3d_finish"] = p["finish"]
    _mats[key] = m
    return m


# ------------------------------------------------------------------ камера и габариты
def bounds(objs):
    pts = [o.matrix_world @ Vector(c) for o in objs for c in o.bound_box]
    mn = Vector([min(p[i] for p in pts) for i in range(3)])
    mx = Vector([max(p[i] for p in pts) for i in range(3)])
    return mn, mx


def non_manifold(o):
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(o.data)
    nm = sum(1 for e in bm.edges if not e.is_manifold)
    bm.free()
    return nm


def wire_overlay(objs, thickness=0.0006, color=(0.03, 0.03, 0.03, 1)):
    """Копии объектов с модификатором «каркас» поверх заливки — чтобы глазами проверить топологию.
    Возвращает список копий (удалить после рендера)."""
    mat = bpy.data.materials.get("BP3D_wire") or bpy.data.materials.new("BP3D_wire")
    mat.diffuse_color = color
    out = []
    for o in objs:
        w = o.copy()
        w.data = o.data.copy()
        bpy.context.scene.collection.objects.link(w)
        for md in list(w.modifiers):
            if md.type != "ARMATURE":
                w.modifiers.remove(md)
        md = w.modifiers.new("wire", "WIREFRAME")
        md.thickness = thickness
        md.use_replace = True
        md.use_even_offset = False
        w.data.materials.clear()
        w.data.materials.append(mat)
        out.append(w)
    return out


def save_clean(path):
    """Сохранить сцену в .blend без следов машины, на которой он собран. save_as_mainfile пишет в файл
    окно-менеджер с последней папкой файлового диалога (домашняя папка пользователя), а путь рендера
    остаётся абсолютным. Пишется только сцена со всем, на что она ссылается; путь рендера затирается
    целиком: Blender хранит его в буфере фиксированной длины, и после короткой строки старые байты остаются."""
    for sc in bpy.data.scenes:
        sc.render.filepath = "_" * 1000
        sc.render.filepath = "//"
    bpy.data.libraries.write(path, set(bpy.data.scenes), compress=True, path_remap="RELATIVE_ALL")
