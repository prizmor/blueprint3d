# Module reference

[Русская версия](modules.ru.md) · [Documentation map](README.md)

What each module in `bp3d/` is responsible for, its public interface, what it depends on and what to watch out for. User-facing usage of the spec API (examples, rules learned in practice) is in the [manual](manual.en.md); this page is for people changing the code.

| Module | Lines | Runtime | Hashed* | Responsibility |
|---|---|---|---|---|
| [`__main__.py`](#__main__py) | ~670 | tool | no | CLI, spec loading, approval, project config, browser, selftest |
| [`model.py`](#modelpy) | ~120 | tool | no | `Model`, `Part`, finishes, palette, BOM |
| [`kit.py`](#kitpy) | ~600 | tool | **yes** | Contours, prisms, lofts, booleans, B-spline surfaces, shells |
| [`mesh.py`](#meshpy) | ~780 | tool | **yes** | Quad meshes from grids, UV islands, thickness, atlas packing, mesh slicing |
| [`drawing.py`](#drawingpy) | ~1030 | tool | no | Projection, HLR, sections, annotations, tables, SVG |
| [`build.py`](#buildpy) | ~170 | tool | no | Blender discovery, export for Blender, running scripts |
| [`body.py`](#bodypy) | ~830 | tool | garments | Rigged body as arrays: roles, landmarks, measurements, rings and grids, poses |
| [`garment.py`](#garmentpy) | ~920 | tool | garments | `Outfit` garment blocks |
| [`rig.py`](#rigpy) | ~345 | tool | garments | Weight transfer, spring chains, colliders, body masking, dynamics export |
| [`posetest.py`](#posetestpy) | ~280 | tool | no | Pose library, spring equilibrium, penetration measurement |
| [`folds.py`](#foldspy) | ~330 | tool | no | Folds and fine relief: displacement field, densification, normal map and fold mask baking |
| [`mannequin.py`](#mannequinpy) | ~140 | tool | no | Code-built `dummy_t` body |
| [`bl_*.py`](#blender-scripts) | ~1650 | Blender | no | Scene assembly, export, atlas, renders, body export, mannequin rebuild |

\* Included in the approval hash: editing the file invalidates approvals (garments: only for specs with a body).

---

## `__main__.py`

**Owns:** the command line and everything that ties stages together.

- `main()` — argparse; reconfigures stdout/stderr to UTF-8; dispatches to `cmd_<name>(obj, args)`. Reference: [CLI](cli.en.md).
- `load_spec(obj)` — imports `<obj>/spec.py` as module `bp3d_spec`, inserts `obj` into `sys.path` (so a spec may import modules next to it), caches per path in `_specs`.
- `spec_hash(obj)` — approval hash (see [architecture](architecture.en.md#approval-and-reproducibility)). `spec_bodies(obj)` finds `Body` globals of the spec; it runs the spec only if its text mentions `bp3d.body` or `from bp3d import`.
- `project_config(obj)` — first `bp3d.json` upward from the object folder.
- `check_quad`, `check_garment` — the rules of `check`; thresholds `ASPECT_MAX = 8.0`, `BREP_DEV_MAX = 1.5` mm.
- `browser()`, `render_svg()` — headless browser lookup and SVG → PNG/PDF.
- `_run_pose()`, `_garment_blend()` — glue to `bl_pose.py`.
- `cmd_selftest` — runs each sample step in a separate process with `PYTHONPATH` = repo root.

Depends on: `build`, `drawing`, lazily `body`, `posetest`, `mannequin`.

## `model.py`

**Owns:** the in-memory description of an object.

- `FINISHES` — `{finish: dict(gray, metal, rough)}`: `paint, chrome, metal, plastic, rubber, glass, lamp, amber, cloth, satin, leather`. Drives the grey model and atlas colours; presentation materials live in `bl_render.py`/`bl_pose.py`.
- `PALETTE` — 17 named colours (a suggestion; the user chooses). `rgb(color)` accepts a palette name, `#RRGGBB` or a tuple and returns sRGB floats 0–1.
- `Part` — dataclass: `key, pos, name, material, shape, finish="paint", group="ext", note, count=True, mesh="cad", quad, bind, dynamics, layer=0, hides, color, pattern, info`.
- `Model(code, title, subtitle="", parts=[], bom_extra={}, body=None)`:
  - `add(...)` validates key uniqueness and finish; a `QuadMesh` passed as `shape` becomes `quad` and `shape` becomes `quad.brep()`, `mesh` defaults to `"quad"`; returns the B-rep.
  - `ext()`, `internal()`, `bom()` (skips `phantom`/`theory`, sums quantities by `count`, applies `bom_extra`).

Groups: `ext` visible; `int` internal (dashed, separate collection in 3D); `glass` (not projected, in sections, transparent in renders); `phantom` (surroundings: thin phantom line, not in BOM or 3D); `theory` (theoretical surfaces: only grids/lines plans).

## `kit.py`

**Owns:** B-rep construction on build123d/OpenCascade. Units mm. **Hashed.**

| Group | API |
|---|---|
| Contours | `Path(start)` with `.L(*pts)`, `.A(c, r, a1)` (≤ 180° per call), `.S(*pts)`, `.close()`, `.wire(to3)`, `.sample(step)`; a point `(u, v, r)` fillets the vertex (only between two lines; radius clamped silently). Helpers `poly`, `sym`, `arcpts`, `rect`, `circle_path`, `ellipse_path` (spline approximation), `hexagon` |
| Solids | `prism_xz/yz/xy(path, a, b, grow=0)`; `tri(side, front, top)` — intersection of view prisms; `loft_x(sections, centripetal=False, max_degree=8)`; `revolve_about`; `cyl`; `box` |
| Booleans, placement | `union`, `cut`, `mirror_y`, `heal` (fix if invalid, never raises), `surface_x` (ray to seat parts) |
| 1D design lines | `lerp`, `interp`, `mono` (monotone cubic, no overshoot), `smooth` (Catmull-Rom), `hermite` |
| Grids `(nu, nv, 3)` | `coons`, `resample`, `grid_of(fn, nu, nv)` (rows resampled by length, so shared borders match), `map_grid`, `mirror_grid`, `grid_normals`, `offset_grid` (+normal by default) |
| Surfaces | `bspline_surface(G)` — own not-a-knot cubic interpolation (scipy), ≥ 4×4 points; `surface_face`; `skin(bands, t)` — shell of thickness t towards −normal with mitred shared rows, sewn; falls back to one solid per band; `section_curves` |

Watch out: `bspline_surface` deliberately does **not** use `GeomAPI_PointsToBSplineSurface` (asymmetric on mirrored grids). `offset_grid` goes +normal, `skin` goes −normal.

## `mesh.py`

**Owns:** polygonal meshes built from the same grids, for game topology. **Hashed.**

- Tags `OUTER, INNER, RIM = 0, 1, 2`.
- `Patch(G, closed_u, closed_v, name, uv_scale)` — one grid = one UV island unrolled by mean row lengths (mm). Normal `du × dv` outward. `deviation()` compares the cell centre of the cubic spline with the quad.
- `QuadMesh` — `V (N,3)`, `F (M,4)` (triangle: last index −1), `UV (M,4,2)` per corner in island mm, `face_island`, `face_tag`, `islands`, `vpatch`, `vuv`, `vside`, `sharp`, `patches`, `thickness`, `two_sided`.
  - `from_patches(patches, weld=1e-3, sharp_borders=False)` → `_weld` (KD-tree, same side only; faces collapsing to 3 vertices become poles).
  - `solidify(t, inner_uv=0.5)` — inner layer along vertex normals with mitre (≤ 2t), rim quads on open edges; inner faces keep the first vertex so both layers share the triangulation diagonal; rim islands share one strip.
  - `brep()` — compound of B-spline faces of the **outer layer only, zero thickness** (for views); sections of quad parts slice the mesh instead.
  - `check(aspect_max=8.0)`, `uv_stretch()`, `deviation()`, `counts()`, `merged`, `transformed`, `mirrored_y`, `triangles`.
- Builders: `quad_skin(bands, t)`, `quad_shell`, `quad_tube(G, caps)`, `quad_sweep(profile, path, corners)`, `revolve_quad`, `box_quad`, `cap_grid` (even ring).
- Grid generators: `spacing(n, dense=[(c, w, k)])` (smooth Gaussian density), `resample_closed/open`, `frames`, `sweep_grid`, `loft_grid`, `revolve_grid`.
- `slice_mesh(V, T, origin, normal)` — plane section polylines.
- `pack_islands(sizes, pad=0.012)` — shelf packing into a square with one scale for all islands (uniform texel density).
- `MeshShape(V, T)` — a ready triangle mesh as surroundings (the body under clothing on the drawing).

## `folds.py`

**Owns:** folds and fine relief as a displacement field along the surface normal from curves on it. General — works on any `QuadMesh`.

- `Fold(path | uv+patch, amp, width, profile, taper, asym, offset, mode, closed, pitch)`; `resolve(surface, patches)` presses the curve onto the surface and densifies it; `field(X, N)` — displacement at points.
- `PROFILES` — `ridge, valley, pipe, crease, groove, step, stitch`; `MODES` — `geo, normal, mask`.
- `refine_for_folds(patches, folds, notes)` — inserts rows across `geo` folds (`REFINE_PER_WIDTH` = 2.5, `REFINE_MAX` = 4, `REFINE_ASPECT` = 5), only in directions whose edges are not welded.
- `apply_geo(mesh, folds)` — moves outer vertices before `solidify` and syncs patch grids (`QuadMesh.sync_patches`).
- `bake_maps(parts, atlas, px)` — normal map and fold mask by the atlas layout, analytically from the fold field; `write_png` — PNG without extra libraries.

## `drawing.py`

**Owns:** the sheet. Not hashed — changing the drawing never invalidates approvals.

Pipeline: `build_body(model, S)` → `Sheet` (SVG fragments, 1 unit = 1 sheet mm) → `wrap_svg(sheet, theme, title)`.

`build_body` order: views → plans → sections → details → annotations (`dims`, `dias`, `radii`, `angles`, `lines`, `balloons`, `notes`, `cuts`, `texts`) → gap table → garment tables (measurements, layers, dynamics) → parts list → technical requirements → legend → frame and title block.

- **Projection.** `CAMERAS` — `{kind: (direction, up)}` for `side, front, top, rear, right, iso`; specs may add entries. `ViewProj(kind, look_at, top_up)` calibrates the 2D image of the axes and projects shapes; `MODE = "exact"` (OpenCascade HLR, chord tolerance 0.06 mm) or `"poly"` (`HLRBRep_PolyAlgo` on a mesh, much faster on hundreds of spline solids); an empty exact result falls back to poly. `FreeProj` for arbitrary section planes; `Placed(proj, k, at)` maps to the sheet.
- **Groups.** `ext` with HLR; `int` projected separately and drawn as hidden lines; `glass` not projected unless requested; `phantom` thin phantom line (meshes via a software depth buffer, `mesh_outline`); `theory` only through `grid`/`plans`.
- **Sections.** Axis planes or `("free", origin, normal[, up])`; CAD parts by B-rep plane intersection, quad parts and meshes by `slice_mesh`; thin sections (2·area/perimeter < 1.4 sheet mm) are filled solid (GOST 2.306), others hatched alternately; `behind` adds what lies behind the plane.
- **Line classes** `m` (0.45 visible), `m2`, `h` (hidden), `c` (centre), `t`, `d` (dimension), `g` (grid), `ph` (phantom), `sec`, `cut`, `dyn*`; themes `print` and `blueprint`; GOST-style italic font stack.
- **Title block** fields from the sheet dict: `title_lines`, `doc_type`, `lit`, `scale` (text only — view scale is `k`), `org`, `author`, `approved_by`, `date`, `spec_hash`.

Watch out: `ViewProj.MODE`/`DEFLECTION` are class-level and set by every `build_body`; detail views reuse the parent view's polylines (no extra resolution); missing `title_at`, `gaps_at`, `tech_at` raise `KeyError`.

## `build.py`

**Owns:** handing a model to Blender.

- `find_blender()` — `BP3D_BLENDER`, Steam, `Program Files\Blender Foundation\Blender 5.3`, macOS app, `PATH`.
- `export_cad(model, out, lin, ang)` — CAD parts to `cad.glb` (metres), manifest entries for all parts except `phantom`/`theory`.
- `export_quads(model, out, atlas_px=2048)` — quad parts to `quads.npz`, atlas packing and island colours/patterns.
- `export_garment(model, out, name)` — the above plus `Rig(model).export()` into the manifest and `<name>_dynamics.json`.
- `run_blender(manifest, glb, out, name, script, extra)` — runs a `bl_*.py` with `-b --factory-startup`, writes `blender.log`, requires `BP3D_DONE` and `report.json`.
- `quad_stats(part)` — quality figures for `check` and the report.

## `body.py`

**Owns:** a rigged body as numpy data. **Hashed for garment specs.**

- `load(path, roles=None, landmarks=None)` → `Body`; exports through `bl_body.py` once per body file into `.cache/body_<sha16>.npz`; memoised by `source_hash`. Constants `MANNEQUIN_F`, `DUMMY_T`.
- **Roles.** `guess_roles(names, parent)` maps bones to `hips, spine, chest, upper_chest, neck, head, clavicle/upper_arm/forearm/hand/thigh/shin/foot/toe _L/_R` by name tokens (Unity Humanoid, Mixamo, UE/MakeHuman game_engine, Rigify); shallowest match wins; bones with `twist, roll, ik, pole, helper, end, ctrl, target…` are skipped. Unroled bones inherit the nearest ancestor's role (fingers → hand).
- **Landmarks** `lm`: heights `waist, bust, underbust, hips, crotch, armpit, neck_base, head_base, knee, ankle, height`; joint points `shoulder/elbow/wrist/hip/knee/ankle/armpit/shoulder_top _L/_R`; `elbow_t`, `knee_t`. Computed from bones, rays and horizontal sections (perimeter extrema).
- **Measurements** `measures`: tape-measure girths (convex hull) and lengths, rounded to 0.1 mm.
- **Geometry helpers:** `closest(P)` (signed distance, point, triangle, barycentrics), `weights_at(P)`, `push_out(G, clearance)`, `section`, `ring`, `torso_ring/torso_grid`, `limb_point/limb_frame/limb_ring/limb_grid`, `nearest_landmark`.
- **Poses:** `pose(spec)`, `pose_on(skel, spec)` with `("to", vec)`, `("bend", deg, vec)`, `[(axis, deg)]`, `"_root"`; unsided keys apply to both sides, mirrored.
- `Skeleton`, `Surface`, `skin_points` (linear blend skinning).

## `garment.py`

**Owns:** garment blocks. **Hashed for garment specs.**

- Constants: `LAYER_GAP = {1: 2, 2: 6, 3: 10, 4: 14}` mm, `ROW_STEP = 20`, `MIN_JOINT_LOOPS = 3`, `DYNAMICS = {stiff, soft, rigid}` presets (stiffness, damping, gravity, radius).
- `Piece(patches, t, edges, solid, joints, name)` — outer-surface grids with named edges other blocks attach to; joints for the joint-loop check.
- `Outfit(model, body, cols=48)` — sets `model.body`, adds the body as a `phantom` part; `add(key, pos, name, material, pieces, finish="cloth", layer, bind="auto", dynamics, hides, pattern, …)` welds pieces into one quad part with thickness and fills `info` (gap, joints, regions, lining).
- Blocks: `tube`, `bodice`, `sleeve`, `skirt`, `pants`, `stocking`, `glove`, `collar`, `cuff`, `hem_band`, `band`, `piping`, `belt`, `buckle`, `button(s)`, `lacing`, `ribbon`, `bow`, `shoe`; helpers `waist_ring`, `push_over`, `over_radius`, `front_point`. Parameters and edges: manual → Clothing.

## `rig.py`

**Owns:** binding a garment to the skeleton. **Hashed for garment specs.**

- `Rig(model)` — extends the body skeleton with spring bones, computes weights for every quad part, rigid binding for `bind="<bone or role>"` and CAD parts, colliders, hidden body polygons.
- Weight transfer `_auto`: per-vertex side restriction (left vertices never take right-limb weights), optional region/role restriction, barycentric weights from the closest body triangle, edge smoothing, blend with spring-chain weights, top 4 influences.
- `chains(part, body)` — spring chains from a part's `dynamics` (keys `patch, chains, bones, v0, v1, blend, parent, follow, radius, colliders, path`); bone names `<key>_d<zone>p<k>c<chain>_<i>`.
- `body_colliders(body)` — capsules for thighs, shins, upper arms, forearms, pelvis, torso, head.
- `_hidden` — body polygons fully covered by a garment with `hides` (`reach` 14 mm, `margin` 18 mm from the garment's edges).
- `export(arrays)` (weights into the npz, rig section of the manifest), `dynamics_manifest(name)` → [`<name>_dynamics.json`](file-formats.en.md#name_dynamicsjson).

## `posetest.py`

**Owns:** checking a garment in motion without a game engine.

- `POSES` — `rest, t_pose, arms_down, arms_up, arms_forward, elbows_bent, squat, wide_step, side_step, bend_forward, twist, sit`; `HERO` presentation pose (excluded from tests).
- `solve(rig, pose)` — body bones from the pose; spring chains in **static equilibrium** (spring towards rest orientation, gravity, push-out from colliders, segment lengths kept), then chains of one zone are linked laterally: a joint follows the larger displacement of its ring neighbours by `LATERAL = 0.75`. Damping is not used.
- `run(model, poses)` — skins every part with the FBX weights and measures: `body` (vertex under the skin of its own region), `layer` (upper layer under the outer surface of a lower one), `collider` (how far a collider pushed a chain). Depths beyond 30 mm are ignored as "other side".
- Thresholds `PEN_BODY = PEN_LAYER = 4.0` mm, `PEN_EXTREME = 12.0` mm in `sit, squat, elbows_bent`; `limit(pose, kind)`.
- Stretch and compression rows measure an outer-layer edge against the skin under it (`STRETCH_MAX`, `COMPRESS_MAX`, `STRETCH_EXTREME`, `STRETCH_ZONES`); `skin_self(body, Vb)` finds skin that went into another body part, penetrations there are reported as `skin` and not counted.
- `bone_matrices(rig, pose)` — 4×4 per bone for `bl_pose.py`.

## `mannequin.py`

**Owns:** the code-built `dummy_t` body — torso as superellipse rings, limb tubes, ellipsoids for head, hands, bust, glutes; `skeleton()` with 22 Unity Humanoid bones. Rebuilt with `mannequin --kind dummy` (voxel remesh, smoothing and automatic weights happen in `bl_mannequin.py`).

## Blender scripts

All run inside Blender, read `sys.argv` after `--`, and print a marker at the end. Contracts: [architecture → process model](architecture.en.md#process-model); files: [file formats](file-formats.en.md).

| Script | Called by | Does |
|---|---|---|
| `bl_common.py` | the other scripts | `cad_to_bl` axis conversion, `quad_object` (mesh from npz with UVs, sharp edges, `bp3d_tag`), `bake_atlas` (island colours + stripe/check/dots/trim patterns, 10 px pad + dilation), `finish_material`, `wire_overlay`, `save_clean` |
| `bl_build.py` | `build` | import CAD glTF, match objects to parts, weld, check size deviation (> 3 mm warns), quad objects, atlas, `internal` collection, rotate to Blender axes, Workbench check renders, `.blend`/`.fbx`/`.glb`, `report.json` |
| `bl_garment.py` | `build` (garments) | body + armature + spring bones, skinned garment meshes (vertex groups from `WI`/`WW`), rigid CAD parts, `Body_masked`, renders, FBX with armature |
| `bl_render.py` | `render` | Cycles presentation: floor, softboxes, materials by finish, paint colour, six shots, `_lookdev.blend` |
| `bl_pose.py` | `posetest`, `render` (garments) | applies bone matrices, renders solid/wire/matte/toon (EEVEE two-step shading, inverted-hull outline) |
| `bl_body.py` | `body.load` | body file → npz in CAD space (mm), weights per bone |
| `bl_inspect.py` | manual use | close-ups of parts (fill + wireframe) with the scene camera |
| `bl_mannequin.py` | `mannequin --kind dummy` | builds `dummy_t` from npz parts and skeleton |
| `bl_mpfb.py` | `mannequin --kind mpfb` | builds `mannequin_f` with MPFB from `macro.json` |

---

## Global state

Known module-level state — do not add more:

| State | Module | Effect |
|---|---|---|
| `_specs` cache, `sys.path` insertions | `__main__` | one spec module instance per process; spec folder stays importable |
| `ViewProj.MODE`, `ViewProj.DEFLECTION` | `drawing` | set by each `build_body`, never restored |
| `CAMERAS` | `drawing` | specs may add camera directions |
| `_loaded` | `body` | bodies memoised by `source_hash` |
| `QuadMesh._brep` | `mesh` | cached B-rep, reset by `transformed()` |

## Known issues

Found while writing this documentation; each is a candidate for a pull request.

- Polygon indices for body masking are computed per mesh in `bl_body.py` but applied after joining meshes in `bl_garment.py`; with a body of several meshes the hidden polygons may land on wrong faces.
- `.cache/body_*.npz` is keyed only by the body file hash: after changing `bl_body.py`, delete `.cache/`.
- `bl_build.py` and `bl_garment.py` save models with `save_as_mainfile`, which records absolute paths in the user's `.blend` (bodies use `save_clean`).
- `bl_render.py` matches materials by name and has no `cloth`/`satin`/`leather` finishes; its `lamp`/`wheel` shots assume a vehicle.
- `bl_inspect.py` needs a scene camera, which `bl_garment.py` removes before saving.
- Docstrings out of date: `__main__` (hash covers more than `spec.py + kit.py`), `bl_common` (mentions `bl_toon`), `bl_mpfb` (claims a GLB).
- Spring-chain `damping` is exported but not used by `posetest`.
- Files opened without closing in several `json.load(open(...))` calls in `__main__.py`.
- Subprocesses (Blender, browser) have no timeout.
