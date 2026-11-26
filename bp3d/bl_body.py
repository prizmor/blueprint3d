"""Запускается Blender'ом: blender -b --factory-startup --python bl_body.py -- <тело .blend|.glb|.fbx> <out.npz>
Выгружает тело с ригом в numpy-массивы для bp3d.body (на стороне build123d — только numpy):
вершины, треугольники, нормали, веса скиннинга, кости. Координаты — персонажа (мм; перёд −X, Z вверх),
то есть Blender (м; перёд −Y, левая рука +X) переводится как x = Y, y = −X, z = Z."""
import bpy, os, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

argv = sys.argv[sys.argv.index("--") + 1:]
SRC, OUT = argv[:2]


def load_body(path):
    """Открыть файл тела. Возвращает (арматура, [меши с модификатором этой арматуры])."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".blend":
        bpy.ops.wm.open_mainfile(filepath=path)
    else:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        if ext in (".glb", ".gltf"):
            bpy.ops.import_scene.gltf(filepath=path)
        elif ext == ".fbx":
            bpy.ops.import_scene.fbx(filepath=path)
        else:
            raise SystemExit(f"формат тела {ext}: нужен .blend, .glb или .fbx")
    arms = [o for o in bpy.context.scene.objects if o.type == "ARMATURE"]
    best = None
    for a in arms:
        ms = [o for o in bpy.context.scene.objects if o.type == "MESH"
              and any(m.type == "ARMATURE" and m.object == a for m in o.modifiers)]
        n = sum(len(o.data.vertices) for o in ms)
        if ms and (best is None or n > best[2]):
            best = (a, sorted(ms, key=lambda o: -len(o.data.vertices)), n)
    if best is None:
        raise SystemExit("в файле нет меша с арматурой: телу нужен риг и веса")
    return best[0], best[1]


def to_cad(P):
    P = np.asarray(P, float).reshape(-1, 3)
    return np.stack([P[:, 1], -P[:, 0], P[:, 2]], axis=1) * 1000.0


if __name__ == "__main__":
    arm, meshes = load_body(SRC)
    bones = list(arm.data.bones)
    names = [b.name for b in bones]
    idx = {n: i for i, n in enumerate(names)}
    mw = arm.matrix_world
    head = to_cad([mw @ b.head_local for b in bones])
    tail = to_cad([mw @ b.tail_local for b in bones])
    parent = np.array([idx[b.parent.name] if b.parent else -1 for b in bones])
    deform = np.array([b.use_deform for b in bones])
    V, N, T, W, tri_poly, vert_mesh = [], [], [], [], [], []
    v0 = p0 = 0
    for k, o in enumerate(meshes):
        me = o.data
        nv = len(me.vertices)
        co = np.zeros(nv * 3)
        me.vertices.foreach_get("co", co)
        m = np.array(o.matrix_world)
        P = co.reshape(-1, 3) @ m[:3, :3].T + m[:3, 3]
        no = np.zeros(nv * 3)
        me.vertices.foreach_get("normal", no)
        Nn = no.reshape(-1, 3) @ np.linalg.inv(m[:3, :3])
        me.calc_loop_triangles()
        nt = len(me.loop_triangles)
        tv = np.zeros(nt * 3, np.int32)
        me.loop_triangles.foreach_get("vertices", tv)
        tp = np.zeros(nt, np.int32)
        me.loop_triangles.foreach_get("polygon_index", tp)
        w = np.zeros((nv, len(bones)), np.float32)
        gmap = {g.index: idx[g.name] for g in o.vertex_groups if g.name in idx}
        for v in me.vertices:
            for g in v.groups:
                b = gmap.get(g.group)
                if b is not None:
                    w[v.index, b] = g.weight
        s = w.sum(axis=1, keepdims=True)
        s[s < 1e-9] = 1.0
        V.append(to_cad(P))
        nn = to_cad(Nn) / 1000.0
        N.append(nn / np.maximum(np.linalg.norm(nn, axis=1, keepdims=True), 1e-12))
        T.append(tv.reshape(-1, 3) + v0)
        W.append(w / s)
        tri_poly.append(tp + p0)
        vert_mesh.append(np.full(nv, k))
        v0 += nv
        p0 += len(me.polygons)
    T = np.vstack(T)
    np.savez_compressed(OUT, V=np.vstack(V), N=np.vstack(N), T=T,
                        W=np.vstack(W), tri_poly=np.concatenate(tri_poly), vert_mesh=np.concatenate(vert_mesh),
                        bone_names=np.array(names), bone_parent=parent, bone_head=head, bone_tail=tail,
                        bone_deform=deform, mesh_names=np.array([o.name for o in meshes]),
                        armature=np.array(arm.name))
    print("BP3D_DONE", len(names), sum(len(v) for v in V))
