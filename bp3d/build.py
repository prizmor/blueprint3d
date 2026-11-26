"""3D-представление: экспорт тел в glTF и квадовых мешей в npz, сборка модели в Blender (фоновый режим)."""
import json, os, subprocess, shutil
import numpy as np
from build123d import Compound, export_gltf

from .model import FINISHES, rgb
from .mesh import pack_islands, OUTER, INNER, RIM

HERE = os.path.dirname(os.path.abspath(__file__))
SKIP = ("phantom", "theory")          # обстановка и теоретические поверхности — только для чертежа


def find_blender():
    """Blender 5.3: переменная BP3D_BLENDER, типовые места установки (Steam, установщик blender.org, macOS),
    затем blender в PATH."""
    env = os.environ.get("BP3D_BLENDER")
    cands = [env] if env else []
    cands += [r"C:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe",
              r"C:\Program Files\Blender Foundation\Blender 5.3\blender.exe",
              "/Applications/Blender.app/Contents/MacOS/Blender"]
    for c in cands:
        if c and os.path.exists(c):
            return c
    w = shutil.which("blender")
    if w:
        return w
    raise FileNotFoundError("Blender не найден: задайте BP3D_BLENDER (полный путь к blender.exe)")


def quad_stats(p, aspect_max=8.0):
    """Сводка квадового меша детали для check и отчёта сборки."""
    q = p.quad
    c = q.check(aspect_max)
    dmax, dmean = q.deviation()
    st = q.uv_stretch()
    c.update(brep_dev_max_mm=round(dmax, 3), brep_dev_mean_mm=round(dmean, 3),
             uv_stretch_min=round(min((v[0] for v in st.values()), default=1.0), 3),
             uv_stretch_max=round(max((v[1] for v in st.values()), default=1.0), 3),
             thickness=q.thickness, two_sided=q.two_sided)
    return c


def _patterns(p):
    pt = p.pattern
    if not pt:
        return []
    out = []
    for d in (pt if isinstance(pt, (list, tuple)) else [pt]):
        d = dict(d)
        d["color"] = list(rgb(d.get("color", "white")))
        out.append(d)
    return out


def export_quads(model, out_dir, atlas_px=2048):
    """Квадовые детали -> quads.npz (вершины, грани, UV в общем атласе, острые рёбра) + описание атласа:
    остров -> место в атласе, цвет детали и узоры (текстуру запекает Blender по этому описанию).
    Масштаб у всех островов один: плотность текселей одинакова по построению."""
    parts = [p for p in model.parts if p.mesh == "quad" and p.group not in SKIP]
    if not parts:
        return None, None, {}
    sizes = [(i["w"], i["h"]) for p in parts for i in p.quad.islands]
    S, pos = pack_islands(sizes)
    arrays, entries, n = {}, {}, 0
    atlas = dict(size_mm=round(S, 3), px=atlas_px, px_per_cm=round(atlas_px / S * 10, 2), islands=[])
    for p in parts:
        q = p.quad
        o = np.array(pos[n:n + len(q.islands)], float).reshape(-1, 2)
        n += len(q.islands)
        arrays[p.key + "|V"] = q.V
        arrays[p.key + "|F"] = q.F
        arrays[p.key + "|UV"] = (q.UV + o[q.face_island][:, None, :]) / S
        arrays[p.key + "|sharp"] = q.sharp.reshape(-1, 2)
        arrays[p.key + "|tag"] = q.face_tag
        base = rgb(p.color)
        g = FINISHES[p.finish]["gray"]
        pats = _patterns(p)
        for k, isl in enumerate(q.islands):
            col = base or (g, g, g)
            if isl["tag"] != OUTER and p.info.get("lining") is not None:
                col = rgb(p.info["lining"])
            use = [d for d in pats if isl["tag"] == OUTER and (not d.get("patch") or isl["name"].startswith(d["patch"]))]
            atlas["islands"].append(dict(part=p.key, name=isl["name"], tag=int(isl["tag"]), x=o[k][0] / S, y=o[k][1] / S,
                                         w=isl["w"] / S, h=isl["h"] / S, scale=isl["scale"], color=list(col),
                                         patterns=use))
        lo, hi = q.bbox()
        st = quad_stats(p)
        dyn = p.dynamics if isinstance(p.dynamics, (str, type(None))) else "custom"
        entries[p.key] = dict(key=p.key, pos=p.pos, name=p.name, finish=p.finish, group=p.group, mesh="quad",
                              bbox_mm=[*map(float, lo), *map(float, hi)], stats=st, colored=base is not None,
                              two_sided=q.two_sided, layer=p.layer, dynamics=dyn, **FINISHES[p.finish])
    npz = os.path.join(out_dir, "quads.npz")
    np.savez_compressed(npz, **arrays)
    return npz, atlas, entries


def export_cad(model, out_dir, lin_defl=0.8, ang_defl=0.15):
    """Детали mesh="cad" — в один glTF (имена узлов = ключи деталей), детали mesh="quad" — в quads.npz,
    плюс манифест для Blender. Возвращает (glb или None, манифест)."""
    os.makedirs(out_dir, exist_ok=True)
    children = []
    manifest = {"code": model.code, "title": model.title, "parts": []}
    npz, atlas, quad_entries = export_quads(model, out_dir)
    for p in model.parts:
        if p.group in SKIP:
            continue
        if p.mesh == "quad":
            manifest["parts"].append(quad_entries[p.key])
            continue
        s = p.shape
        s.label = p.key
        children.append(s)
        bb = s.bounding_box()
        c = rgb(p.color)
        manifest["parts"].append(dict(key=p.key, pos=p.pos, name=p.name, finish=p.finish, group=p.group, mesh="cad",
                                      bbox_mm=[bb.min.X, bb.min.Y, bb.min.Z, bb.max.X, bb.max.Y, bb.max.Z],
                                      color=list(c) if c else None, layer=p.layer, **FINISHES[p.finish]))
    glb = None
    if children:
        glb = os.path.join(out_dir, "cad.glb")
        # build123d тесселирует в метрах: переводим допуск из мм
        export_gltf(Compound(children=children), glb, binary=True, linear_deflection=lin_defl / 1000.0,
                    angular_deflection=ang_defl)
    manifest["quads"] = npz
    manifest["atlas"] = atlas
    man = os.path.join(out_dir, "manifest.json")
    with open(man, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    return glb, man


def export_garment(model, out_dir, name, lin_defl=0.3, ang_defl=0.15):
    """Одежда на теле: к экспорту деталей добавляются веса, кости динамики, скрытые полигоны тела
    (bp3d.rig) и файл <name>_dynamics.json с параметрами костей с пружиной для движка."""
    from .rig import Rig
    glb, man = export_cad(model, out_dir, lin_defl, ang_defl)
    rig = Rig(model)
    with open(man, encoding="utf-8") as f:
        m = json.load(f)
    arrays = {}
    if m.get("quads"):
        with np.load(m["quads"]) as d:
            arrays = {k: d[k] for k in d.files}
    m["rig"] = rig.export(arrays)
    if arrays:
        m["quads"] = os.path.join(out_dir, "quads.npz")
        np.savez_compressed(m["quads"], **arrays)
    with open(man, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=1)
    dyn = os.path.join(out_dir, name + "_dynamics.json")
    with open(dyn, "w", encoding="utf-8") as f:
        json.dump(rig.dynamics_manifest(name), f, ensure_ascii=False, indent=1)
    return glb, man, rig


def run_blender(manifest_path, glb_path, out_dir, name, script="bl_build.py", extra=()):
    blender = find_blender()
    cmd = [blender, "-b", "--factory-startup", "--python", os.path.join(HERE, script), "--",
           manifest_path, glb_path or "-", out_dir, name, *extra]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    log = os.path.join(out_dir, "blender.log")
    with open(log, "w", encoding="utf-8") as f:
        f.write(r.stdout + "\n" + r.stderr)
    rep = os.path.join(out_dir, "report.json")
    if r.returncode != 0 or "BP3D_DONE" not in r.stdout or not os.path.exists(rep):
        raise RuntimeError(f"Blender упал, см. {log}\n" + (r.stdout + r.stderr)[-1500:])
    with open(rep, encoding="utf-8") as f:
        return json.load(f)
