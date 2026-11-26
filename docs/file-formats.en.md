# File formats

[Русская версия](file-formats.ru.md) · [Documentation map](README.md)

Every file Blueprint3D reads or writes. Keys are listed as the code writes them; new keys may be added in minor versions, existing keys are not renamed without a **[breaking]** changelog entry.

## Object folder

```
<object>/
  spec.py            the specification (you write it)
  approved.json      approval record (bp3d approve)
  out/               everything generated; never commit
    drawing/         <CODE>_print.svg/.png, <CODE>.pdf, <CODE>_blueprint.svg/.png, crop_*.png
    model/           <NAME>.blend/.fbx/.glb, <NAME>_atlas.png, render_*.png, report.json, manifest.json, blender.log
                     garments: + <NAME>_dynamics.json
    render/          presentation renders + render_<color>.json (hard-surface) or render.json (garments)
    posetest/        report.json, pose_*.png, worst*_*.png, renders.json
```

`<CODE>` = `model.code` up to the first space; `<NAME>` = the same with `-` replaced by `_`.

## Inputs

### `spec.py`

A Python module with:

| Name | Required | Contract |
|---|---|---|
| `build_model()` | yes | Returns a `bp3d.model.Model` |
| `sheet(model)` | for `draw` | Returns the sheet dict (keys: manual → Sheet; reference: [modules → drawing](modules.en.md#drawingpy)) |
| a global holding a `Body` (e.g. `BODY = body.load(...)`) | garments | Turns on garment checks, render and the body hash |
| `CODE`, `TITLE` | no | Convention of the starter template; `new` replaces these two lines |

The folder is put on `sys.path`, so a spec may import helper modules next to it (they are **not** part of the approval hash).

### `bp3d.json`

Optional, found in the object folder or any parent. A JSON object whose keys become sheet defaults; `sheet(model)` overrides them. Typical keys: `org` (organisation in the title block), `author` (developer field, default `Claude`), `approved_by`, `lit`, `doc_type`. Not hashed.

```json
{"org": "STUDIO", "author": "Name"}
```

### Body files

`.blend`, `.glb`/`.gltf` or `.fbx` with one armature and a weighted mesh, standing on the floor, facing −Y in Blender. Bone roles are guessed from names; override with `body.load(path, roles={...})`, landmarks with `landmarks={...}`. Bundled bodies: `bodies/mannequin_f/mannequin_f.blend` (+ `macro.json` — MakeHuman macro parameters `gender, age, muscle, weight, proportions, height, cupsize, firmness, race`, `targets`, `rig`), `bodies/dummy_t/dummy_t.blend`.

## Records

### `approved.json`

```json
{
 "spec_hash": "<sha256 hex>",
 "approved_by": "<--by>",
 "note": "<--note: the approver's words>",
 "date": "YYYY-MM-DD",
 "bp3d": "<tool version>"
}
```

Only `spec_hash` is compared by `build`. Commit this file together with `spec.py`.

## Model output (`out/model/`)

### `report.json`

Written by `bl_build.py` / `bl_garment.py`, extended by `build`.

| Key | Content |
|---|---|
| `parts` | `{key: {pos, mesh, tris, quads, non_manifold_edges, bbox_dev_mm, group}}`; quad parts add `tris_only, brep_dev_max_mm, brep_dev_mean_mm, aspect_max, uv_stretch, tverts, poles, valence`; garments add `verts, layer, bind, dynamics` |
| `warnings` | list of strings: size deviation > 3 mm, part missing from glTF, weld problems |
| `atlas` | `{px, px_per_cm, islands, texture}` |
| `renders` | check renders produced |
| `total_tris`, `total_quads`, `total_tris_ext` | totals |
| `bbox_m` | overall size in metres |
| `files` | `{blend, fbx, glb}` |
| `body` | garments: `{file, polys, hidden_polys, bones, dynamic_bones}` |
| `dynamics` | garments: `{file: "<NAME>_dynamics.json", chains, colliders}` |
| `spec_hash`, `draft` | added by `build`; `draft: true` for `--force` builds |

### Model files

| File | Content |
|---|---|
| `<NAME>.blend` | Scene: parts as objects (internal parts in collection `internal`), materials by finish; garments: armature with spring bones, skinned garments, `Body_masked` |
| `<NAME>.fbx` | Unity axes (forward −Z, up Y), scale by units, no leaf bones; garments include the armature and `Body_masked` |
| `<NAME>.glb` | glTF binary, Blender exporter defaults |
| `<NAME>_atlas.png` | Colour atlas of quad parts (`Model.atlas_px`, 2048 px by default; island colours, patterns, 10 px padding + dilation) |
| `<NAME>_normal.png` | Tangent-space normal map of quad parts (OpenGL Y+, same layout as the atlas), baked from folds with mode `normal`; only when such folds exist |
| `<NAME>_foldmask.png` | Fold mask for the artist (grey, brightness — fold strength), from folds with mode `mask` |
| `render_*.png` | Check renders (Workbench): views, perspectives, wireframes |
| `manifest.json` | Intermediate: what was sent to Blender (see below) |
| `blender.log` | Blender stdout + stderr of the last run |

### `manifest.json` (Python → Blender)

```
{
  code, title,
  parts: [ {key, pos, name, finish, group, mesh: "cad"|"quad", bbox_mm[6], color, layer, gray, metal, rough,
            quad parts: stats, colored, two_sided, dynamics, variant} ],
  quads: "<path to quads.npz>" | null,
  atlas: {size_mm, px, px_per_cm, islands: [{part, name, tag, x, y, w, h, scale, color, patterns}]},
  rig (garments): {bones: [{name, parent, head, tail}], bone_names, rigid: {key: bone}, hidden_polys,
                   armature, body_meshes, body_file}
}
```

`quads.npz` keys per quad part: `<key>|V`, `|F`, `|UV`, `|sharp`, `|tag`; garments add `|WI` (int32, 4 bone indices) and `|WW` (float32 weights). `cad.glb` and `quads.npz` are deleted after a successful build.

### `<NAME>_dynamics.json`

Engine-neutral spring-bone description for garments. Units: metres.

```
{
  "model": "<NAME>",
  "format": "bp3d-dynamics-1",
  "units": "meters",
  "note": "...",
  "chains": [
    {"part", "bones": [names root→tip], "parent", "preset",
     "stiffness", "damping", "gravity", "hit_radius_m",
     "follow": [{"bone", "weight"}], "bone_length_m", "colliders": [names],
     "ring": {"index", "count", "closed"}}   // place of the chain among the chains of its zone (neighbours are linked)
  ],
  "colliders": [
    {"name", "bone", "shape": "capsule", "radius_m", "along_bone",
     "start", "end",            // fractions along the bone
     "a_rest_mm", "b_rest_mm"}  // capsule ends in the rest pose, CAD mm
  ]
}
```

Map it to the engine's spring-bone component (UniVRM SpringBone, Magica Cloth BoneSpring, or your own). `format` changes only with a major version.

## Render output

### `out/render/render_<color>.json` (hard-surface)

`{color, paint_linear, finishes, engine, samples, renders: {shot: file}, spec_hash, draft}`. Shots: `hero`, `front`, `side`, `high`, `lamp`, `wheel` as `<NAME>_<color>_<shot>.png`; `<NAME>_lookdev.blend` next to them.

### `out/render/render.json` (garments)

`{pose, renders: [png names], spec_hash, draft}` (with `--inspect` only the six `inspect_*.png` are written, no `render.json`). Shots: `<pose>_toon`, `<pose>_toon_back`, and without `--hero-only` `<pose>_toon_side`, `rest_toon`, `<pose>_matte`, `<pose>_wire`.

## Pose test output (`out/posetest/`)

### `report.json`

| Key | Content |
|---|---|
| `poses`, `parts` | what was tested |
| `thresholds` | `{body, layer, extreme, extreme_poses}` mm |
| `failed` | true if any row exceeds its threshold |
| `worst_body`, `worst_layer`, `worst_collider`, `worst_skin`, `worst_stretch`, `worst_compress` | deepest values, mm |
| `rows` | `[{pose, part, kind: body|layer|collider|skin|stretch|compress, other, depth, count, where, point, rest}]` — deepest per pose/part/kind; `where` is the nearest landmark |
| `renders` | `{name: file}` |
| `spec_hash` | hash of the tested specification |

Images: `pose_<pose>.png` (each pose), `worst<n>_<pose>_<part>.png` (up to four worst places).

### `_shots.json` (Python → `bl_pose.py`, temporary)

`{"shots": [{name, pose: {bone: 16 floats row-major, CAD mm}, mode: solid|wire|toon|matte|inspect, dir, target, radius, res, parts, hide}]}` (`parts` — show only these parts, `hide` — hide these: non-chosen variants).

## Caches

### `.cache/body_<sha16>.npz`

Body exported by `bl_body.py`, in CAD space (mm): `V, N, T, W` (per-bone weights, normalised), `tri_poly`, `vert_mesh`, `bone_names, bone_parent, bone_head, bone_tail, bone_deform`, `mesh_names`, `armature`. Keyed by the first 16 hex digits of the body file's SHA-256. Safe to delete.
