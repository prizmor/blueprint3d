# Blueprint3D — full manual

A 3D modelling tool for games: hard-surface objects (vehicles, weapons, equipment, furniture, buildings) and character clothing on a rigged body. An object is described once, as a parametric specification in Python (`spec.py`). Two representations are produced from it:

| Representation | What it is | How it is produced |
|---|---|---|
| Drawing | GOST sheet: SVG, PNG, PDF, white and "blueprint" theme | Projections of the solids with hidden lines, plane sections, detail views, dimensions, leaders, parts list |
| 3D model | `.blend`, `.fbx`, `.glb`, renders, report | The same solids → Blender in the background. Two mesh paths: CAD triangulation (grey model) or a quad mesh with a UV unwrap taken directly from the construction grids. For clothing, also an armature, weights and spring bones |

The drawing and the model match by construction: both are taken from the same solids. It is impossible to draw on the sheet something that is not in the model.

Workflow for an AI agent — [`AGENTS.md`](../AGENTS.md). Russian version — [`manual.ru.md`](manual.ru.md).

## Where things are

```
blueprint3d/       repository root
  README.md        overview (README.ru.md — in Russian); AGENTS.md — workflow for an AI agent
  docs/            documentation: this manual, architecture, modules, cli, file-formats, development (.en.md / .ru.md); map — docs/README.md
  requirements.txt dependencies (build123d on OpenCascade)
  scripts/         installation: install.ps1 (Windows), install.sh (Linux, macOS), install_mpfb.ps1
  venv/            environment, not in git; installed by scripts/install.ps1
  bp3d/
    __main__.py    commands: new, check, draw, crop, approve, build, render, status, posetest, body, mannequin, selftest
    kit.py         geometry: contours, solids, doubly curved surfaces
    mesh.py        quad mesh from grids: patches, welding, thickness, UV islands, sweep, revolve, mesh section
    model.py       Model and Part: parts-list items, finish, colour, groups, skinning fields
    drawing.py     sheet: projections, sections, detail views, dimensions, tables, title block; context body, dynamics
    build.py       export of solids to glTF and quads to npz, texture atlas, Blender launch
    bl_common.py   shared code for Blender scripts: meshes from npz, atlas baking, materials, wireframe
    bl_build.py    building the object model in Blender, check renders, report
    bl_render.py   presentation render with matte materials (objects)
    bl_inspect.py  mesh close-up (shaded and wireframe)
    body.py        character body: landmarks, measurements, rings, offset shell, weight transfer, poses
    garment.py     clothing blocks (Outfit): bodice, sleeve, skirt, pants, stocking, collar, belt, ribbon, bow, shoes
    rig.py         binding: weights, spring bones, colliders, hiding the body under clothing
    posetest.py    poses, spring bone solver, penetration table
    bl_body.py     export of the rigged body to numpy (cache .cache/)
    bl_garment.py  building clothing on the body: armature, weights, atlas, renders, FBX with armature
    bl_pose.py     poses in Blender: posetest renders, toon and matte presentation
    mannequin.py, bl_mannequin.py, bl_mpfb.py   building the tool's bodies (bodies/)
  bodies/          rigged bodies: mannequin_f (MakeHuman, A-pose), dummy_t (mannequin built in code, T-pose)
  examples/        sample specifications; the tool itself is tested on them (selftest)
    starter/       template for a new object: a box of simple solids with a full A2 sheet
    pickup_front/  simple solids from view contours: front end of a pickup truck
    sedan_front/   body shell from doubly curved surfaces: front end of a sedan
    quad_parts/    quad mesh for a hard-surface object: revolve, sweep, panel from patches, atlas with a pattern
    garment_basic/ clothing on the mannequin — template for a clothing specification (check, draw, build, posetest)
<object folder>/   objects live in your project, not in the tool repository (for example, art/blueprints/<CODE>/); the folder is created by the new command
  spec.py          object specification: build_model() and sheet(model)
  approved.json    user approval
  out/             drawing, model, renders — not in git
```

The examples are trial objects on which the tool was debugged, not game assets: their dimensions are estimates and their drawings are not approved. Take techniques and sheet layout from them, but not shape. The `EX-…` codes are taken by them — do not give them to your own objects.

## Installation

Required: Git with Git LFS (the bodies in `bodies/` are LFS files), Python 3.12 (or [uv](https://docs.astral.sh/uv/) — it installs Python itself), Blender 5.3 for the 3D stage, Edge, Chrome or Chromium for the PNG and PDF of the drawing.

```powershell
git lfs install
git clone https://github.com/prizmor/blueprint3d.git
cd blueprint3d
powershell -ExecutionPolicy Bypass -File scripts\install.ps1     # Linux, macOS: sh scripts/install.sh
```

The script installs `venv/` (Python 3.12, build123d 0.13, numpy, scipy) and checks that Blender and a browser can be found. Blender is looked up via the `BP3D_BLENDER` variable, in Steam (`...\steamapps\common\Blender\blender.exe`), in `C:\Program Files\Blender Foundation\Blender 5.3\`, in `/Applications/Blender.app` and in `PATH`. The browser is looked up via `BP3D_BROWSER`, then Edge, Chrome, Chromium. Without a browser the drawing is still produced, but only as SVG.

MPFB (`scripts\install_mpfb.ps1`) is needed only to rebuild the mannequin; the ready body is in `bodies/`. MPFB is installed into a separate Blender profile `.mpfb/` inside the repository; your own profile can be given in `BP3D_MPFB`.

**Project settings.** A `bp3d.json` file in the object folder or higher up the tree (usually at the root of your project) sets default sheet values, for example `{"org": "STUDIO", "author": "Smith"}` — the text in the title block. The specification's `sheet()` overrides them. The file is not part of the approval hash.

## Commands

Run from any folder: `PYTHONPATH` points to the root of the tool repository, the object path can be anything.

```powershell
$env:PYTHONPATH="C:\path\to\blueprint3d"; $py="C:\path\to\blueprint3d\venv\Scripts\python.exe"
& $py -m bp3d check   art\blueprints\<CODE>
```

Linux and macOS: `PYTHONPATH=/path/to/blueprint3d /path/to/blueprint3d/venv/bin/python -m bp3d check art/blueprints/<CODE>`.

| Command | What it does |
|---|---|
| `new <folder> [--code CODE] [--title "Title"]` | Creates an object folder with a `spec.py` from the `examples/starter` template. The default code is the folder name |
| `check <folder>` | Builds the solids and checks them: invalid, empty, without a closed solid; prints overall dimensions. Quad parts: closedness, manifoldness, face winding, degenerate and elongated quads, deviation from the B-rep. Clothing: clearance to the body and loops at the joints. Exit code 1 on errors |
| `draw <folder> [--quick]` | Drawing. `--quick` — white PNG only, for iterations |
| `crop <folder> x y w h [--out file]` | Enlarged area of the sheet (sheet mm) — for self-review by zones |
| `approve <folder> --by "<who>" --note "<quote>"` | Records the approval: hash of `spec.py` and the construction modules (for clothing, also the body file) |
| `build <folder> [--force] [--out folder]` | 3D model. Without `--force` it refuses if the drawing is not approved or the specification has changed |
| `render <folder> [--color colour] [--hero-only] [--model file.blend] [--pose pose]` | Presentation render. For clothing, the showcase pose in toon style and a matte frame |
| `status <folder>` | Approval state |
| `posetest <folder> [--poses ...] [--show mm] [--no-render] [--model file.blend]` | Clothing in a set of poses: penetration table and renders of the worst cases. Exit code 1 if there are rows above the threshold |
| `body <body file or folder>` | Measurements, landmarks and bone roles of the body |
| `mannequin [--kind mpfb\|dummy]` | Rebuild the tool's bodies in `bodies/` |
| `selftest [--draw] [--only name ...]` | Check of the tool itself: `check` (with `--draw`, also a draft sheet) for each example in `examples/`, plus `posetest` for the clothing example. Exit code 1 if any of them fails |

## Workflow

1. **Passport.** Purpose, real overall dimensions, key dimensions, what is visible and what is internal. Anything the user has not specified is marked as a proposal, not silently invented.
2. **Specification.** `new <object folder>` puts a working template in place; the template's geometry and sheet are replaced with your own. `build_model()` returns a `Model` with parts, `sheet(model)` returns the sheet description.
3. **`check`.** Fix all errors before drawing.
4. **`draw --quick`** and self-review of the drawing by zones with `crop` (checklist below).
5. **Draft 3D before showing.** `build --force --out <temporary folder>`, look at the renders. The build finds errors that are invisible in lines: see-through gaps, inside-out parts, intersections.
6. **Full `draw`** and showing it to the user. Approval is given only by the user, in words in the chat; record `approve` with the quote.
7. **`build`** without `--force`: check the report (open meshes, deviations of overall dimensions) and look at the renders.
8. **`render`** — if a colour presentation is needed.

Any edit of `spec.py`, `kit.py` or `mesh.py` after approval makes it stale: the drawing is redrawn and approved again. For clothing, the hash also includes `body.py`, `garment.py`, `rig.py` and the body file. `--force` is only a draft for your own review, not a result for the user.

For clothing the workflow is the same with additions: body measurements at the start and `posetest` after the draft build — `new → check → draw --quick → crop → build --force → posetest → fixes → draw → approval → build → posetest → render`. Details are in the "Clothing" section.

## Object specification

```python
from bp3d.kit import ...
from bp3d.model import Model

def build_model():
    M = Model(code="XXX-000", title="Title")
    M.add("key", 1, "Name", "Material", shape, finish="paint", group="ext")
    return M

def sheet(model):
    return dict(size=(841, 594), scale="1:8", views=[...], sections=[...], ...)
```

Axes: X — rearward from the frontmost point, Y — to the left, Z — up from the ground, millimetres. In Blender the front faces −Y.

**Finish** (`finish`) sets the material type: the grey shade in the model and the material in the render — `paint`, `chrome`, `metal`, `plastic`, `rubber`, `glass`, `lamp`, `amber`, and for clothing `cloth` (matte fabric), `satin` (glossy fabric), `leather`. The `material` field is text for the parts list on the sheet ("Cotton") and does not affect appearance.

**Part fields** (`Model.add(...)`, all optional — old specifications work as before):

| Field | Meaning |
|---|---|
| `mesh` | `"cad"` — CAD triangulation of the solid (default); `"quad"` — quad mesh. Set automatically if a `QuadMesh` is passed instead of a solid |
| `color` | Colour: a name from `model.PALETTE`, `"#RRGGBB"` or `(r, g, b)`. Without a colour the part is grey according to its finish. The palette is a proposal; the user chooses the colour |
| `pattern` | Pattern or list of patterns for a quad part, baked into the atlas by UV: `dict(kind="stripe", dir="v", pitch, width, color)`, `"check"` (`style="gingham"\|"checker"`), `"dots"` (`pitch`, `r`), `"fill"` — the whole island in one colour (with `patch`: a sole, an insert), `"trim"` — piping along the island edge (`edges=("v1",)`, `width`). `patch="name"` — only on patches whose names start with this |
| `bind` | Binding to the skeleton: `"auto"` — weights from the body; a role or bone name (`"hips"`) — a rigid part on a single bone; `dict(mode="segments", …)` — a rigid part of several segments (clothing → Binding) |
| `dynamics` | Spring bones: `"stiff"` (springy, holds its shape), `"soft"` (sags), `"rigid"`/`None` or a dictionary — see "Clothing" |
| `layer` | Clothing layer 1…4 (0 — not clothing) |
| `hides` | `True` — the body under the part is hidden |

**Part groups** (`group`):

| Group | In views | In sections | In parts list and 3D |
|---|---|---|---|
| `ext` | visible outline | yes | yes |
| `int` | dashed | yes | yes, collection `internal`, hidden in renders |
| `glass` | not projected and hides nothing | yes | yes, transparent in the render |
| `phantom` | thin chain line with two dots | no | no |
| `theory` | no (only the section grid and lines plan) | no | no |

Parts of the same item that do not increase the quantity — `count=False`. Do not reuse object codes.

## Geometry

### Simple solids
- `Path` — a contour of lines (`L`), arcs (`A`, no more than 180° per call) and splines (`S`); a point `(u, v, r)` rounds the vertex with a true arc. Do not discretise curves into polylines: each face produces an extra line on the drawing.
- `tri(side, front, top)` — intersection of view prisms; suitable for housings and simple panels.
- `prism_xz`, `prism_yz`, `prism_xy` with `grow` — contour extrusion, contour offset for gaps.
- `loft_x(..., centripetal=True)`, `revolve_about`, `cyl`, `box`, `cut`, `union`, `mirror_y`.

### Doubly curved surfaces
An intersection of view prisms gives a "box", a single loft through sections gives a "bar of soap". Body panels are built from patches:

1. The shape is defined by functions — design lines and sections (`mono`, `hermite`).
2. Each smooth zone is a grid of points: `grid_of`, `coons`, `map_grid`.
3. A panel is a shell with thickness `skin([patches], t)`. A shared row of points of neighbouring patches is a feature edge; it becomes a drawing line by itself.
4. Gaps — by offsetting patch boundaries, not by cutting.
5. Parts "fitted in place" (frames, slats, inserts) — intersection of a view contour with a layer offset from the surface (`offset_grid` + `skin`).
6. The theoretical surface for the lines plan — faces without thickness: `surface_face`, group `theory`.

### Quad mesh from grids (`bp3d.mesh`)
CAD triangulation produces long thin triangles and fans without edge loops or a UV unwrap. For a hard-surface object this hardly matters, but a mesh that is bent by a skeleton breaks on it. The second path builds a polygonal mesh from the same `(nu, nv, 3)` grids that go into `bspline_surface` and `skin`:

- a grid cell is a quad; the grid is not resampled: as many rows as are given, that many loops there will be. Row densification — `spacing(n, dense=[(center, half_width, factor)])`;
- a patch (`Patch`) is a UV island unwrapped by row lengths; all islands share one scale, so texel density is uniform. Islands are packed into a shared model texture atlas during the build;
- the shared row of neighbouring patches is welded; thickness is a second layer along vertex normals (mitred at a crease) plus edge quads along the borders;
- the B-rep for the drawing is built from the same grids (`QuadMesh.brep()`), so the drawing and the model are still taken from one construction. Sections of quad parts are taken from the mesh itself.

| Function | What it builds |
|---|---|
| `quad_skin(bands, t)` | Counterpart of `skin`: a panel with thickness from patches with shared rows; `t=0` — a single layer (double-sided material); `closed_u=True` — a tube |
| `quad_shell(patches, t)` | Shell from ready `Patch` objects |
| `quad_tube(G)` | Solid from a grid of rings with quad caps |
| `quad_sweep(profile, path, corners=...)` | Profile along a curve (belt, handle, piping); `corners` — sharp corners of the profile, `closed_path` — a ring |
| `revolve_quad(profile, center, axis, n)` | Solid of revolution; points on the axis produce poles (triangle fans) |
| `box_quad`, `sweep_grid`, `loft_grid`, `revolve_grid`, `cap_grid` | Box with sharp edges and grids for your own constructions |
| `Path.sample(step)` | Points of a `Path` contour preserving vertices — a profile for sweep and revolve |

A part is added as usual: `M.add("body", 1, "Housing", "Steel", quad_mesh, color="teal")`. The build report shows per part the number of quads and triangles, the deviation of quads from the B-spline of the same grid, UV unwrap stretch and atlas density (px/cm); `out/model/` gets wireframe renders `render_wire*.png` and the texture `<name>_atlas.png`. Example — `examples/quad_parts`.

`check` thresholds: quad aspect ratio no more than 8:1 (border edge quads are not counted: they are elongated by construction); deviation from the B-rep over 1.5 mm — a warning "add rows". Triangles are allowed only at revolve poles and toes — their count is shown in `check` and in the report.

### Folds and fine relief (`bp3d.folds`)
General functionality for any quad mesh (clothing, soft goods). A fold is part of the model: it does not change in animation, the item only bends with the bones.

A fold (`Fold`) is a curve on the surface — `path` (points, mm; pressed onto the surface when the part is assembled) or `uv=[(u, v), ...]` on a named `patch` — plus a cross-section profile: `ridge` (rounded crest), `valley` (rounded trough), `pipe` (wide crest), `crease` (sharp crest), `groove` (sharp groove, seam), `step` (step — folded-over fabric), `stitch` (dashed groove with `pitch`). Parameters: `amp` (mm, positive outward; a number, `(start, end)` or per point of the curve), `width` (half-width of the profile, mm), `taper` (fade towards the ends, a fraction of the length), `asym` (−1…1), `offset` (mm across the curve — parallel stitch rows from one seam), `closed`.

`mode` says where the fold goes; several at once are allowed, and different folds of one item may use different modes:

| Mode | Where | Typical use |
|---|---|---|
| `geo` | Geometry of the game model; rows near the fold are densified automatically (`refine_for_folds`) | Large folds: accordion at the ankle, knee bags, tension diagonals, hanging pipes |
| `normal` | Tangent-space normal map (`<name>_normal.png`, OpenGL Y+), baked by the UV layout | Small folds, gathers, seams, stitches, rib of an elastic |
| `mask` | Fold mask for the artist (`<name>_foldmask.png`, brightness — fold strength) | Data for painting or shading folds |

Folds are passed to `Outfit.add(..., folds=[...])`; a block may carry its own (`Piece.folds`: rib of a waistband). The normal map is baked analytically from the fold field at the surface point under each pixel — equivalent to baking from a high-poly version of the same item; the high-poly mesh itself is not exported. Atlas resolution — `Model.atlas_px` (default 2048; 4096 for stitches and ribs).

- Densification adds rows only across a fold (a ring fold needs denser rows, not columns along itself), at most `REFINE_MAX` = 4 between two old rows, and does not make a quad narrower than 1:`REFINE_ASPECT` = 5. A direction whose edges are welded to another patch is not densified (a note is printed: raise `cols` / lower `row_step` of the block).
- Points moved by `geo` folds are pushed out of the body to the layer gap.
- On a ready solid (`Piece.solid`: shoe, laces) only `normal` and `mask` work.

### Rules learned in practice
- **Grid orientation.** The patch normal is `du × dv`. `skin` grows thickness towards "minus normal". An "inward" layer on a grid with an outward normal will go outward: flip the grid (`G[:, ::-1]`) and check the overall dimensions in `check` — they must not grow.
- **Mirrored parts** — `mirror_y` of the finished left part, not building a second grid with reversed winding.
- **`union` is not always reliable** on spline solids: it may lose a solid or give an invalid result. Check volume and `is_valid`; if it does not combine, leave it as a separate part of the same item (`count=False`).
- **Solids overlap, they do not touch.** Face-to-face contact gives an open mesh after welding.
- **An invalid solid** after boolean operations — `heal(...)`. It breaks the repeated polygonal projection.
- **A zone grid needs margin.** A part at the edge of the grid is clipped silently (you get a fragment instead of a disc).
- **Edge roll-offs and roundings** are computed from the actual distance to the edge, not by interpolation between neighbouring lines — otherwise the edge becomes wavy.
- **Behind every opening — a solid wall** (grille, recess, wheel arch). Drawing lines will not show a see-through gap, a render will.
- **Internal assemblies do not intersect external ones.** Check in sections and in the draft 3D.
- **The surface through a grid is built by `kit.bspline_surface`** with its own interpolation. The standard OpenCascade interpolator (`GeomAPI_PointsToBSplineSurface`) is asymmetric: on a mirrored grid it produced a wave of several millimetres at one edge — a fold at the joint on one side only. Do not go back to it.
- **Check symmetry on both sides.** A symmetric grid does not yet mean a symmetric solid: compare the left and right joints on a close-up render of the draft build, and if in doubt, with rays (`find_intersection_points`) at mirrored points. Comparing the volumes of the halves does not catch a local wave.
- **Slits along edges.** A part that must adjoin a curved panel (a wheel-arch liner to the side panel) is defined by the shape of that panel, not by a constant width.
- **A flat panel** is barely visible on the drawing but stands out in 3D. Check the crown height against the theoretical lines plan: numbers matter more than the impression the lines give.
- **A sharp profile — from patches.** A B-spline through a grid rounds the corners: a rectangular strap cross-section made from one patch turned into an oval with a 1.7 mm deviation. Define profile corners via `corners` in `quad_sweep` (each face is its own patch, the edge is sharp).
- **A closed profile of revolution** runs from axis to axis: the first and last points have radius 0, otherwise the mesh is not closed.
- **The outer and inner sides of a shell share the quad diagonal.** A doubly curved quad is not planar; the engine splits it into two triangles along the diagonal from the first vertex. An inner side wound "back to front" was split along the other diagonal and poked through the outer side as dots of lining colour. Wind the inner side from the same first vertex.
- **Atlas padding — at least 10 px, with the background in the colour of the nearest island.** Otherwise, at mip levels the neighbour's colour bleeds into small islands.
- **Parts of the same item must not start at the same point.** Two ribbons from a shared point are welded into an edge with three faces (a non-manifold mesh).

## Clothing

> **Garments are at an early stage.** The clothing pipeline (body, garment blocks, weights, spring bones, `posetest`) has only just started: expect glitches — crumpled or uneven edges, parts that do not meet cleanly, poses where fabric goes through the body. This is normal for now and will be fixed step by step. If you find a problem, please [open an issue](https://github.com/prizmor/blueprint3d/issues) with the spec and a render, or fix it and send a pull request — see [CONTRIBUTING.md](../CONTRIBUTING.md). The hard-surface pipeline is more mature.

The style is that of anime games: clothing is a modelled mesh with clean quad topology, not a cloth simulation. The model defines the shape (the skirt holds a bell, the collar stands up), motion comes from spring bones only where it is needed (hem, ribbons, tails), the clothing sits on the body, and the body underneath is hidden. There are no sewing patterns or stitching: a garment is described directly in 3D relative to the body. Example and template — `examples/garment_basic`.

### Body (`bp3d.body`)
```python
from bp3d import body
BODY = body.load(body.MANNEQUIN_F)        # .blend / .glb / .fbx with armature and weights
BODY.lm["waist"], BODY.measures["bust"]   # landmarks and measurements; python -m bp3d body <file>
```
- **Character coordinate system** — the same as for objects: Z up from the floor, X — rearward (the front faces −X), the character's left side — −Y, millimetres. After the build in Blender the front faces −Y, the left arm faces +X, and the FBX is written with Unity axes (as for objects).
- The body is exported through Blender in the background once and cached in `.cache/` (not in git); the specification side uses only numpy.
- Any rest pose (A or T): everything is computed from the bones. Bones are reduced to **roles** (`hips`, `spine`, `chest`, `upper_chest`, `neck`, `head`, `clavicle_L`, `upper_arm_L`, `forearm_L`, `hand_L`, `thigh_L`, `shin_L`, `foot_L`, `toe_L` and the same with `_R`) by name — Unity Humanoid, Mixamo, UE/MakeHuman game_engine are understood. Unusual names: `body.load(path, roles={"thigh_L": "Bip_L_Thigh", ...})`.
- **Landmarks** `BODY.lm`: heights `waist`, `bust`, `underbust`, `hips`, `crotch`, `armpit`, `neck_base`, `head_base`, `knee`, `ankle`, `height`; joint points `shoulder_L`, `elbow_L`, `wrist_L`, `hip_L`, `knee_L`, `ankle_L`, `armpit_L`, `shoulder_top_L` (and `_R`); limb parameters `elbow_t`, `knee_t`. They are computed from bones and sections; they can be overridden: `body.load(path, landmarks={"waist": 1050.0})`.
- Limb parameter `t`: 0 — shoulder or hip joint, 1 — wrist or ankle; elbow and knee — `lm["elbow_t"]`, `lm["knee_t"]`.
- Building blocks: `torso_ring(z)`, `torso_grid(zs, nu, offset, tent)` — an offset torso shell; `limb_ring`, `limb_grid(limb, ts, nu, offset)` — an arm or leg shell; `section(origin, normal)` — body section; `closest(P)` — signed distance to the body; `push_out(G, clearance)` — push a grid out of the body to the clearance; `weights_at(P)` — weights from the nearest surface.
- **The body hash is part of the approval.** The hash of the body file and of the role and landmark tables is included in the specification hash: if the body changes, the approval is stale.

The tool's bodies: `bodies/mannequin_f` — a female MakeHuman figure (MPFB2, base mesh and the 53-bone game_engine skeleton, A-pose), asset licence CC0 — see `bodies/README.md`; `bodies/dummy_t` — a mannequin built in code (T-pose, Unity Humanoid names), a second body for checking that a garment is not tied to one rig.

### Clothing blocks (`bp3d.garment.Outfit`)
`O = Outfit(M, BODY)` puts the body into the model and adds it to the drawing as context. Each block returns a `Piece` — grids of the outer surface with named edges (`edges`) to which other blocks attach. `O.add(key, pos, name, material, [blocks], finish, color, layer, bind, dynamics, hides, pattern)` welds the blocks along shared rows into one part with thickness.

| Block | What it is | Edges |
|---|---|---|
| `tube(top, bottom)` | Torso shell without shoulders: corset, bandeau, yoke | `top`, `bottom` |
| `bodice(bottom, neck, ...)` | Bodice, top, shirt, blouse, jacket, vest: a tube up to the armpits and an upper part with shoulders. `neck`: `round`, `v`, `square`, `boat`, `high`; `open_front=True` — open front | `bottom`, `neck`, `armhole_L/R` |
| `sleeve(top, side, length, kind)` | Sleeve from the armhole: `straight`, `flare`, `bell`, `puff` (puff sleeve), `cap` (cap sleeve); sleeveless — do not add the block | `end` |
| `skirt(waist, length, kind)` | Skirt: `straight`, `a`, `bell`, `circle`; `pleats=n` — pleats as geometry; `top=bodice` — a dress as one part | `waist`, `hem` |
| `pants(waist, length)` | Trousers, shorts, leggings: pelvis, crotch bridge, two legs. Loose cut: `ease` by landmarks (`{"waist": 0.5, "hips": 10}` — elastic at the waist, loose on the hips), `leg_ease` by zones `top`, `thigh`, `knee`, `calf`, `ankle`, `leg_around` by sides `front`, `back`, `out`, `in`, `leg_tent`, `leg_smooth`, `crease` (cap of the gap behind the knee and at the front of the groin, default 12 mm), `elastic=True` | `waist`, `end_L/R` |
| `stocking(side, top, bottom)`, `glove(side, ...)` | Stocking, knee sock, sock; arm sleeve | `top`, `end` |
| `collar(top, kind)` | Collar along the neckline: `stand` — a stand built as an even ring around the neck axis (`height`, `front_drop` — how much lower it is at the front, as a fraction of the height); its bottom runs exactly along the bodice neckline edge, `turndown`, `flat`, `ruffle` | |
| `cuff(piece, kind)`, `hem_band(piece, kind)` | Cuff and hem band: `band`, `turnback`, `ruffle` | |
| `band(loop, profile)` | Any strip along an edge: custom profile, wave (frill, ruche) | |
| `piping(loop)` | Piping — a cord along an edge | |
| `belt(z, width, over=[...])` | Belt; `over` — garments under it: the belt lies on them | `ring`, `front` |
| `buckle(center, normal, up)` | Buckle — a build123d solid (`mesh="cad"`) that lies on the belt with its tilt: `center=belt.edges["front"]`, `normal=belt.edges["front_normal"]`, `up=belt.edges["front_up"]`; added with `M.add(..., bind="hips")` | |
| `buttons(z_top, z_bottom, count)`, `lacing(...)` | Row of buttons and lacing on the front or back | |
| `ribbon(path, width, over=[...])` | Ribbon along a polyline; `over` — garments it lies on | `end` |
| `bow(center)` | Bow: loops with a knot and two tails as separate blocks (tails get dynamics) | |
| `shoe(side, shaft)` | Boot built on a last: the shaft and the ankle bend follow the leg, from the instep to the toe the shoe has its own smooth shape (envelope of the foot plus `ease`, toe rounded over the `toe` fraction of the length, toe box at least `toe_height` high); a cup sole `sole` thick with a `welt` and a `rand` wall rising along the side of the upper is a separate patch `<name>_sole`. `fit="rigid"` (default) — the shoe is a rigid model: binding `shoe_bind` (foot, toe hinge `flex` mm wide, shaft on the shin when `shaft_bend`), the collar is `ankle_room` mm looser towards the top edge; `fit="skin"` — the former binding by leg weights | `top`, `front_line` |
| `shoe_bind(side, flex, shaft_bend)` | Rigid footwear binding by segments: foot bone; past the plane through the toe joint — toe bone (blend `flex` = 24 mm; `None` — the sole does not bend); with `shaft_bend` the shaft from 50 mm above the ankle — shin (blend 40 mm). Also for your own footwear and parts on the foot: `bind=O.shoe_bind("L")` | |
| `binding(piece, edge, width)` | Binding that wraps an edge on both sides (neckline, armhole); the direction across the edge is taken from the garment surface | |
| `waistband(piece, width)` | Elastic waistband over the top edge of trousers or a skirt; lies over the garment, rib of the elastic in the normal map | |
| `sneaker_details(shoe, tongue_w, eyelets)` | Sneaker details on a `shoe`: padded collar, tongue along the instep, lacing with eyelets; returns (blocks of the shoe material, laces block) | |
| `auto_folds(piece, amount, seams)` | Plausible folds by block type and fit (`pants`, `sleeve`, `skirt`): accordion at knee and ankle, tension from the crotch, hanging pipes, gathers under an elastic, side seam and inseam | |
| `folds_accordion`, `folds_tension`, `folds_hanging`, `folds_spiral`, `folds_gather`, `fold_crease`, `folds_pressed`, `folds_quilt`, `seam` | Fold types as ready functions (compression accordion, tension, hanging, spiral, gathers, folded fabric, pressed pleats, quilting, seam with stitches); `limb_arc`, `limb_line` — rings and lines along a limb for your own folds | |

- **Layers.** `layer` 1 — next to the body (tight-fitting, stockings), 2 — tops and skirts, 3 — outerwear, 4 — accessories. The offset of the inner side from the body grows with the layer: 2, 6, 10, 14 mm (`garment.LAYER_GAP`), so the layers do not intersect. `ease` — extra looseness on top of the offset: a number, a function of height or `{"waist": 2, "bust": 6}`. `tent` 0…1 — fabric tension across hollows (cleavage, between the legs).
- **Grid density.** `cols` — loops around the torso (a multiple of 8), `row_step` — row spacing, mm (default 20). At the waist, elbow and knee the rows are densified automatically; `check` requires at least 3 loops across a bend.
- **Binding.** Strategies (`bind`):
  - `"auto"` / `"tight"` — fitted: weights from the nearest body surface with interpolation inside the triangle;
  - `"proxy"` / `"loose"` — loose: where the fabric stands off the body, weights come from a proxy body (`Body.proxy`: the body inflated by 25 mm and smoothed, with weights smoothed over the mesh 12 times); where it is close to the body (elastic, waistband), from the skin. The blend goes by the gap: closer than `rig.PROXY_FROM` = (10, 22) mm — skin, farther — proxy, smoothly between;
  - a bone name or role — a rigid part on one bone;
  - `dict(mode="segments", bone=…, cuts=[dict(bone, point, normal, blend), …])` — a rigid part of several segments: every vertex on `bone`; each cutting plane takes the vertices on the side its `normal` points to onto its own bone, with a smooth transition `blend` mm wide across the plane; planes apply in order. Inside a segment the part does not deform, it only rotates with the bone. For footwear, armour plates, knee pads. Blocks may carry their own default binding (`Piece.bind`): `shoe` binds rigidly by segments; `add(..., bind=…)` overrides it.

  After the transfer the weights are smoothed over the fabric by distance (`smooth_mm`, implicit diffusion with edge weight 1/length²): `rig.SMOOTH_MM_TIGHT` = 20 mm for fitted, `SMOOTH_MM_LOOSE` = 45 mm for loose; for loose items weights smaller than `WEIGHT_MIN_LOOSE` = 0.03 are dropped softly. 4 influences per vertex remain. A vertex on the left does not take weights from the right arm and leg. Your own values: `bind=dict(mode="loose", smooth_mm=30, inflate=25, proxy_smooth=12, proxy_from=(10, 22), w_min=0.03)`. A rigid part — `bind="hips"` (role or bone name).
- **Dynamics.** `dynamics="stiff" | "soft"` or a dictionary: `preset`, `patch` (patch name), `chains` (chains around; 1 for a ribbon), `bones` (bones per chain), `v0`…`v1` — the section of the grid, top to bottom, where dynamics work, `blend` — width of the transition from body weights, `parent` — the root bone, `radius` — collision radius, `follow` — the fraction of thigh rotation that the chain root follows, `colliders`. A skirt fills in defaults itself: root on the pelvis, start at the hip line, 12 chains of 4 bones, `follow=0.9`, colliders limited to the legs and the pelvis. Body capsule colliders (thighs, shins, upper arms, forearms, pelvis, torso, head) are built automatically.
- **Hiding the body.** `hides=True`: a body vertex closer than 14 mm to the inner side of the garment and farther than 18 mm from its edges counts as covered; a body polygon is hidden if all its vertices are covered. Tuning — `hides=dict(reach=…, margin=…)`.

### What you get after `build`
`out/model/`: `<name>.blend`, `<name>.fbx` (the body armature with added dynamics bones, clothing meshes with weights, `Body_masked` — the body with hidden polygons removed; `add_leaf_bones=False`, Unity axes), `<name>.glb`, `<name>_atlas.png`, `<name>_dynamics.json`, renders (`front`, `back`, `side`, `q`, `bodice`, `sleeve`, `hem`, `wire_*`) and `report.json`.

- **Body and clothing.** The FBX contains the clothing and the finished body with polygons removed — it can be placed in a scene right away. For swappable outfits, Unity takes only the clothing meshes from the FBX and hides the polygons of the shared body by the `hidden_polys` list from `manifest`/`report` (polygon indices of the source body mesh). No texture mask over the body UVs is made.
- **Spring bones.** The tool is not tied to an engine component, so the parameters are stored in a neutral `<name>_dynamics.json`: chains (bones, parent, `stiffness`, `damping`, `gravity`, `hit_radius_m`, lengths, `follow`, list of colliders) and capsule colliders (bone, radius, start and end as fractions of the bone length). Options for Unity: UniVRM SpringBone (MIT), Magica Cloth 2 (BoneSpring), your own component reading this file; in other engines — your own component reading the same file.

### Clothing checks
- `check` — the quad checks are extended with: no point inside the body in the rest pose (error), clearance at least half the layer offset (warning), loops in joint zones.
- `posetest` — the model is put into 12 poses (`rest`, `t_pose`, `arms_down`, `arms_up`, `arms_forward`, `elbows_bent`, `squat`, `wide_step`, `side_step`, `bend_forward`, `twist`, `sit`) with the same linear skinning and the same weights that go into the FBX; spring bones take their equilibrium position (spring towards the rest pose, gravity, pushing out of colliders away from the body). Counted:
  - `тело` (body) — a clothing vertex has gone under the skin of its body part (hidden polygons are not counted);
  - `слой` (layer) — a vertex of an upper layer has gone under the outer surface of a lower layer on the same body part;
  - `коллайдер` (collider) — how far a collider pushed a chain joint (for reference: a large value means the hem lies on the thigh).
  - `растяжение` / `сжатие` (stretch / compression) — how much more an edge of the outer layer is stretched or compressed than the skin under it (linear skinning itself stretches the mannequin's skin at the armpit severalfold in `arms_up`; a fitted item cannot stretch less). Thresholds: `posetest.STRETCH_MAX` = 60 %, `COMPRESS_MAX` = 70 %, in extreme poses `STRETCH_EXTREME` = 90 %; by zone (`STRETCH_ZONES`, nearest landmark): crotch 110 %, armpit 90 %, elbow and knee 75 %. All thresholds are proposals;
  - `кожа в теле` (skin in body) — the garment entered skin that itself went into another body part in the pose (calf into thigh in a squat, belly into thigh when sitting: linear skinning crushes the inner side of a strong bend). Reported separately and not counted as a failure: this is the limit of the pose, not of the item (`posetest.skin_self`).
  Chains of one dynamics zone are linked like a sheet: a joint is pulled towards the displacement of the neighbouring chains by the fraction `posetest.LATERAL` (0.75) when the neighbours are displaced more — the hem does not sag as a wedge between the thighs.
  The table "pose → part → kind → depth → location (nearest landmark)" is printed and written to `out/posetest/report.json`; next to it are a frame of each pose and close-ups of the four worst spots.
- **Thresholds** (`posetest.PEN_BODY`, `PEN_LAYER`, `PEN_EXTREME`): 4 mm for the body and layers; 12 mm in the extreme poses `sit`, `squat`, `elbows_bent` — there the joint is bent by more than 90°, with linear skinning the body enters itself in the fold, and the clothing in the fold repeats this. Anything deeper than the threshold must be fixed: offset (`ease`), layer, length, binding, dynamics.
- The showcase pose is `posetest.HERO` (standing, weight on one leg, arms relaxed); poses are defined by bone rotations in code: `("to", vector)`, `("bend", degrees, vector)`, `[("z", degrees)]`.

### Clothing rules learned in practice
- **Do not end a sleeve at the elbow or a trouser leg at the knee.** An edge right at the joint enters the neighbouring segment when bent (a cuff at the elbow gave 30 mm in `elbows_bent`). Put the edge 0.1 of the parameter above or below the joint.
- **A belt follows the body weights, not a single bone.** A belt on `hips` cut into the waist by 28 mm in a squat: the waist is driven by the spine bones. Only small rigid parts (a buckle) go on a single bone.
- **The chain root goes on the bone that drives the garment underneath.** A hem — on the pelvis, a ribbon on the chest — on the chest section. A ribbon at the belt with its root on the pelvis drifted 15 mm away from the shorts when the torso turned, and with its root on the spine — when bending.
- **Skirt dynamics start at the hip line, not at the waist.** Above it the skirt follows the body together with the belt; starting right at the waist shifts the belt when bending.
- **An overlay part lies on the clothing, not on the body.** A ribbon at the collar, computed from the body, ended up 12 mm under the T-shirt: at the cleavage the fabric is stretched (`tent`). Pass `over=[garment]`.
- **Short skirt and the "sit" pose.** The thigh rises by 90°, and the hem must lie on it: `follow`, more chains and `radius` 30 help. The chain between the thighs touches no collider; in the estimate the neighbouring chains pull it along (`posetest.LATERAL`), otherwise the front sags as a wedge through the legs. In the engine this needs a link between neighbouring chains (the `ring` field in `<name>_dynamics.json`) — look at the `pose_sit` frame.
- **Do not shrink-wrap a stand collar point by point.** Pushing every point of the stand out of the body crumpled it, made the top edge uneven and stretched it upwards under the chin. The stand is built from rings around the neck axis: constant clearance, flat top edge, lower at the front.
- **The sole meets the upper with a wall.** A flat slab under the upper looked glued on from below. The sole is a cup: the bottom of the upper sinks into it and the `rand` wall rises along the side.
- **The stand starts at the neckline edge.** A stand laid over the neckline with its own smoothed edge left a gap and an overlap with the bodice fabric; the bodice evens out the neckline edge and the fabric near the neck itself, and the stand takes the same points.
- **Footwear has its own shape, not a wrap of the foot.** A shell around the foot repeated the toes and the arch. From the instep to the toe the shoe is built on a last; the body inside may be anything.
- **Footwear is a rigid model, not fabric.** Leg weights stretched the shoe after the skin of the foot and ankle. A shoe is rigid by segments (foot, toe past the ball line, shaft of a high boot on the shin); the body under it is hidden, so the foot inside does not show through. The collar is looser at the top — the shin moves in it when the ankle bends.
- **Place a rigid overlay along the tilt of the part under it.** A buckle standing vertically looked foreign on a tilted belt: take the normal and "up" from the belt.
- **Hem colliders are the legs and the pelvis.** In a forward bend the torso capsule comes from above and pushed the hem upwards, into the vest.
- **Check clearance between vertices too.** A flat quad cuts off the convexity of the body: `push_out` also moves the corners of a cell whose middle is closer than half the offset.
- **Body hiding does not reach the edge.** A strip of the body at the edge of the garment stays visible (`margin`): otherwise a hole shows in the neckline and under the hem.
- **Smooth weights by distance, not by neighbours.** On a sleeve at the armpit the weight jump sat on a few 6 mm edges, and in `arms_up` they stretched by 280 % over the skin; smoothing over 20 mm of fabric brought it to 55 %.
- **A tail of a far bone is worse than no weight.** 3.7 % of the thigh on a belly vertex moved it by 9 mm when sitting (the thigh turns by 90°), and the neighbour had another bone as its fourth influence. Loose items drop small influences softly (`WEIGHT_MIN_LOOSE`); a hard cut makes the jump at the cut boundary.
- **The proxy body only where the fabric hangs free.** Proxy weights at the elastic waist dragged the thigh into the belly and stretched it by 289 %; they are blended in by the gap to the body.
- **Loose fabric on the inner side of a bend falls into the body.** Behind the knee in a squat and at the front of the groin when sitting, linear skinning crushes the bend; the gap there is limited (`pants(crease=...)`).
- **A narrow strip needs a dense edge.** A binding on a sparse neckline edge made 1:15 quads; the edge is resampled to the step across the strip, linearly — a cubic spline overshoots at the strap corners.
- **Across the edge — along the garment surface.** The mean plane of an armhole led a binding into the body under the arm: an armhole is a 3D curve.
- **A waistband lies over the trousers.** Below the edge the trousers widen towards the hips, and a straight band sank into them; gathers start below the band.
- **Tension (`tent`) starts below the limb root.** At the crotch the hull of the ring included the pelvis and inflated the leg to 45 mm.

## Sheet

| Key in `sheet()` | Purpose |
|---|---|
| `views` | Views: `kind` (`side`, `front`, `top`, `rear`, `right`, `iso`), `k`, `at`, `look_at` |
| `views[].parts`, `exclude`, `groups` | A view of a subset of parts, for example an assembly shown separately |
| `views[].grid` | Thin section grid over the view: buttocks, waterlines |
| `plans` | Theoretical lines plan: superimposed plane sections without projecting the solids |
| `sections` | Sections; `behind` — what is visible behind the cutting plane to a given depth |
| `details` | Detail views from an existing view |
| `dims`, `dias`, `radii`, `angles` | Dimensions: linear, diameters, radii, angular |
| `balloons`, `notes`, `texts`, `lines`, `cuts` | Item balloons, leaders with text, labels, centre lines, section markers |
| `gaps`, `tech` | Gap table, technical requirements |
| `hlr="poly"` | Polygonal hidden-line computation: seconds instead of minutes on assemblies of hundreds of spline solids. The default is exact |
| `views[].dynamics` | Clothing: spring bone chain lines and the dynamics zone boundary on the view |
| `views[].folds` | Clothing: lines of `geo` folds on the view, only on the side facing the viewer (crest — dash-dot, trough and crease — short dash) |
| `sections[].plane = ("free", point, normal[, up])` | Section by an arbitrary plane (a sleeve across the arm); `near` — only contours closer than that many mm to the point |
| `measures_at`, `layers_at`, `dyn_at` | Clothing: tables of body measurements, layers and binding, dynamics |
| `size`, `legend_at`, `tech_at`, `gaps_at` | Sheet size in mm (default A1 841×594; the template is A2 594×420) and the positions of the legend, technical requirements and gap table. On a sheet smaller than A1, `legend_at` must be set: the default position is designed for A1 |

The character body on the sheet is context (`group="phantom"`): in views its visible outline is drawn, in sections the section ring, so a section shows the garment's offset from the body and its thickness. A clothing sheet is A1, main views at 1:5 (see the example).

Narrow sections (thin sheet metal) are filled black per GOST 2.306. The projection point of a custom camera is set with `CAMERAS["name"] = (direction, up)`; for such views leave `look_at` at `(0, 0, 0)` and compute `at` with `ViewProj(...).uv(point)`.

## Self-review

**Drawing** — look at the PNG enlarged, by zones (`crop`):
- overlapping text, leaders and lines;
- dimensions and leaders point where they should, the numbers match the model;
- views are consistent, no stray lines or "holes";
- sections are readable: thin sheet metal is filled black, parts do not intersect;
- the lines plan has no flat areas where there should be convexity.

**Model** — report and renders:
- no open meshes, deviation of overall dimensions within 3 mm;
- the overall size matches the intended one;
- no see-through gaps, inside-out parts or protruding flanges;
- the object is recognisable without labels.

**Clothing** — additionally:
- `check` without errors; on the wireframe (`render_wire_*`) the loops are even, without elongated or twisted quads, denser at the joints;
- `posetest` passed; the frames of the poses and of the worst spots have been looked at;
- the figure's silhouette reads, the garment does not look like paint on the body: it has thickness, edges, offset;
- skin does not show through the fabric, there are no holes in the body in the neckline or under the hem;
- colours and pattern are in place, stripes run along the loops.

## Render

`bl_render.py` assigns procedural PBR materials according to the finish of the parts, sets up softboxes and renders six frames in Cycles: hero, front, side, top three-quarter, headlight close-up and wheel close-up. The model's source `.blend` is not changed. Paint colours: `graphite`, `teal`, `coral`, `sand`, `white`, `black`; the palette is a proposal, the user chooses the colour.

This is a presentation of shape and finish, not game textures. CAD parts need retopology, a UV unwrap and maps for the engine — a separate step of your project's pipeline; quad parts already come with edge loops, a UV unwrap and a colour atlas.

**Clothing** is rendered by `bl_pose.py`: the showcase pose in toon style (EEVEE: two light steps via Shader to RGB, hard highlight on skin and metal, outline by an inverted hull), the same frame matte (Cycles) and wireframe. Files — `out/render/hero_toon.png`, `hero_toon_back.png`, `hero_toon_side.png`, `rest_toon.png`, `hero_matte.png`, `hero_wire.png`. This is a preview, not a game shader.

Normals in the model are exact, from CAD. Do not recompute auto smooth by angle and do not "clean up" the triangulation: this produces blotches and creases.

## Extending the tool

Whatever is missing is added to `bp3d/` with comments, without breaking existing specifications. After any edit of `bp3d/`:

```powershell
& $py -m bp3d selftest --draw
```

All examples must pass; afterwards look at the example sheets (`examples/<name>/out/drawing/`). A new rule or limitation goes into this file right away (both languages), a new technique into an example or the template.

**Documentation is mandatory for every change of the tool**: a `CHANGELOG.md` entry and every affected document in both languages, in the same pull request. How the tool is built — [architecture](architecture.en.md), [modules](modules.en.md), [CLI](cli.en.md), [file formats](file-formats.en.md); rules for changes, testing and documentation — [development guide](development.en.md).

## What to keep in git

- **In the tool repository:** the `bp3d/` code, the examples, the bodies in `bodies/` (`.blend` via Git LFS and `macro.json`), documentation, installation scripts.
- **In your project:** `spec.py` and `approved.json` of the objects, optionally `bp3d.json`. Nothing from `out/` — drawings, models, renders — is needed in git: it is reproduced by commands from `spec.py`, and the specification hash is on the sheet and in `report.json`. Add the line `out/` to the project's `.gitignore`.
- The finished model gets into the engine as a separate step of the project pipeline.
## Limitations

- Faces, bodies, hair — other tools. There is no cloth simulation: folds come from a texture, a shader or parametric geometry.
- `mesh="cad"` parts are CAD triangulation without a UV unwrap: a grey model and blocking. Game topology is available only with `mesh="quad"`.
- Feature edges are sharp creases between patches; radii on edges are not built yet.
- Import into the engine is not automated; the spring bone component in the engine is on the project side.
- Clothing: `posetest` is an estimate based on linear skinning and static equilibrium of the chains, not game physics. A short skirt in the "sit" and "squat" poses gives penetrations up to the extreme-pose threshold and above.
- Clothing: the open front (`open_front`) has no lapels or overlapping fastening; a stocking ends at the ankle (the foot is covered by footwear); the boot has no heel, and its sole goes below the floor by its thickness (the character root is raised by it in the game); on the atlas the border edge quads share one small island.
- Clothing: loose bottoms in deep bends — in `squat` the fabric behind the knee and when sitting at the waist and knee stretches above the threshold, and on a wide step the crotch reaches the proposed 110 % limit. Without corrective shapes (not made: a user decision) linear skinning does not do better; see `posetest`.
- Clothing: folds — no deformers (bend, twist, inflate, brush) yet; a fold on a patch whose edges are welded densifies only the free direction.
- Clothing: a CAD part is bound to a single bone only.
