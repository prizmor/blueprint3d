# CLI reference

[Русская версия](cli.ru.md) · [Documentation map](README.md)

```
python -m bp3d <command> [<object folder>] [options]
```

`PYTHONPATH` must point at the repository root; run with the interpreter from `venv/`. Every command except `selftest` and `mannequin` takes the object folder (a folder with `spec.py`) as its first argument; the path is made absolute. Messages are printed in Russian, always in UTF-8. `sys.exit("…")` prints the message to stderr and returns exit code 1.

Implementation: `bp3d/__main__.py` — one `cmd_<name>()` function per command, argparse in `main()`.

| Command | Purpose | Exit code 1 when |
|---|---|---|
| [`new`](#new) | Create an object folder with `spec.py` from the starter template | `spec.py` already exists |
| [`check`](#check) | Build the solids and validate them | any error |
| [`draw`](#draw) | Drawing sheet: SVG, PNG, PDF | spec raises |
| [`crop`](#crop) | Enlarged fragment of the sheet | no browser, no SVG |
| [`approve`](#approve) | Record the user's approval | — |
| [`build`](#build) | 3D model | no approval / stale approval, Blender failure |
| [`render`](#render) | Presentation renders | no model, Blender failure |
| [`status`](#status) | Approval state | never |
| [`posetest`](#posetest) | Garments in a pose set, penetration table | penetrations above threshold, no body |
| [`body`](#body) | Measurements, landmarks and bone roles of a body | no body |
| [`mannequin`](#mannequin) | Rebuild the bundled bodies | MPFB missing, Blender failure |
| [`selftest`](#selftest) | Check the tool on the samples | any sample fails |

---

## new

```
new <folder> [--code CODE] [--title "Title"]
```

| Option | Default | Meaning |
|---|---|---|
| `--code` | folder name | Object code; becomes `CODE = "…"` in the spec |
| `--title` | starter title | Becomes `TITLE = "…"` in the spec |

Copies `examples/starter/spec.py` to `<folder>/spec.py` (LF line endings), replacing the literal lines `CODE = "XXX-000"` and `TITLE = "Ящик инструментальный"`. Creates the folder. Refuses to overwrite an existing `spec.py`.

## check

```
check <folder> [-v]
```

Calls `build_model()` and validates every part. `-v` also lists parts made of more than one solid.

| Part kind | Errors | Warnings |
|---|---|---|
| CAD (B-rep) | no faces; `is_valid` false; faces but no solid (except groups `phantom`, `theory`); exception while building | — |
| Quad mesh | non-manifold edges; flipped edges; degenerate faces; boundary edges (unless two-sided); quads with aspect ratio above `ASPECT_MAX = 8` | deviation from the B-spline above `BREP_DEV_MAX = 1.5` mm ("add rows"); triangles present |
| Garment (model has a body) | a vertex inside the body (signed distance < −0.05 mm); fewer than `garment.MIN_JOINT_LOOPS` loops across a joint zone | gap to the body below half the layer offset |

Prints errors as `ОШИБКА <key> (поз. N, group): …`, part counts per group, the overall size of `ext` parts, quad totals and the result line. Writes nothing itself; for a garment spec the first load of a body runs Blender once and fills `.cache/`.

## draw

```
draw <folder> [--quick]
```

Builds the model, merges sheet settings (`bp3d.json` found upward from the folder, then `sheet(model)` on top, then `spec_hash`), lays the sheet out once (`drawing.build_body`) and writes each theme (`drawing.wrap_svg`).

| Mode | Files in `<folder>/out/drawing/` |
|---|---|
| `--quick` | `<CODE>_print.svg`, `<CODE>_print.png` |
| full | the above + `<CODE>.pdf` (print theme), `<CODE>_blueprint.svg`, `<CODE>_blueprint.png` |

`<CODE>` is `model.code` up to the first space. The sheet size is `size` from the sheet dict, default A1 `(841, 594)` mm. PNG and PDF are printed by a headless browser; without a browser only SVG is written and the command still succeeds.

## crop

```
crop <folder> x y w h [--theme print|blueprint] [--scale PX_PER_MM] [--out FILE]
```

A fragment of an already drawn sheet, coordinates in sheet millimetres from the top-left corner. `--scale 0` (default) fits the fragment into about 1500×1100 px. Default output: `<folder>/out/drawing/crop_<x>_<y>_<w>x<h>.png`. Needs a browser. Uses the first `*_<theme>.svg` in `out/drawing/`.

## approve

```
approve <folder> --by "<who>" [--note "<their words>"]
```

Writes `<folder>/approved.json` with the current specification hash (see [file formats](file-formats.en.md#approvedjson)). Always overwrites. Approval is given by a person; an agent records it only after the user approved in their own words.

## build

```
build <folder> [--force] [--out DIR] [--lin MM] [--ang RAD]
```

| Option | Default | Meaning |
|---|---|---|
| `--force` | off | Skip the approval check; the result is a **draft** (`draft: true` in the report) |
| `--out` | `<folder>/out/model` | Output folder. Put drafts elsewhere: `render` and `posetest` pick the model from `out/model/` |
| `--lin` | `0.8` | Linear tessellation deflection of CAD parts, mm (garments: at most `0.3`) |
| `--ang` | `0.15` | Angular deflection, radians |

Without `--force`: no `approved.json` → refuse; stored hash ≠ current hash → refuse ("re-draw and approve again").

Hard-surface: `build.export_cad` + `build.export_quads` → `bl_build.py` in Blender. Garments: `build.export_garment` (adds the rig) → `bl_garment.py`. Output name: `model.code` up to the first space with `-` replaced by `_`. Produced files — [file formats](file-formats.en.md#model-output-outmodel). Intermediate `cad.glb` and `quads.npz` are deleted afterwards; `manifest.json` and `blender.log` stay.

Exit code is 0 even with open meshes or warnings — read the printed summary and `report.json`.

## render

```
render <folder> [--color NAME] [--hero-only] [--model FILE.blend] [--out DIR] [--pose NAME]
```

| Option | Default | Meaning |
|---|---|---|
| `--color` | `graphite` | Paint colour for hard-surface renders: `graphite`, `teal`, `coral`, `sand`, `white`, `black` (not enforced) |
| `--hero-only` | off | Only the main shot(s) |
| `--model` | first `out/model/*.blend` not containing `lookdev` | Model to render |
| `--out` | `<folder>/out/render` | Output folder |
| `--pose` | `hero` | Garments: pose for the shots |

Hard-surface: `bl_render.py` in Blender (user profile, not factory settings), Cycles, six shots; writes `render_<color>.json`. Garments: `bl_pose.py` — toon front/back (+ side, rest, matte, wireframe without `--hero-only`); writes `render.json`. Both copy `spec_hash` and `draft` from the model's `report.json`.

## status

```
status <folder>
```

Prints the approval date and author and whether it is current (`актуален`) or stale (`УСТАРЕЛ`), or that there is no approval; then the current hash. Always exits 0. For a spec that imports `bp3d.body`/`from bp3d import …`, computing the hash runs the spec (and may export the body through Blender once).

## posetest

```
posetest <folder> [--poses NAME ...] [--show MM] [--no-render] [--model FILE.blend] [--out DIR]
```

| Option | Default | Meaning |
|---|---|---|
| `--poses` | all except `hero` | Poses to test (see [manual → Clothing](manual.en.md#clothing)) |
| `--show` | `1.0` | Hide rows shallower than this many mm (collider rows always shown) |
| `--no-render` | off | Table only, no Blender |
| `--model` | first `out/model/*.blend` | Model for the renders |
| `--out` | `<folder>/out/posetest` | Output folder |

Poses the garment with the same linear skinning and weights that go into the FBX, settles spring chains, measures penetrations (`posetest.run`). Prints the table "pose → part → kind → mm → vertices → place"; rows above the threshold are marked `!`. With a built model and without `--no-render`, renders each pose (`pose_<name>.png`) and up to four worst places (`worst<n>_<pose>_<part>.png`) through `bl_pose.py`. Writes `report.json`. Exit code 1 if any row is above its threshold.

## body

```
body <body file | object folder>
```

Loads a body (`.blend`/`.glb`/`.fbx` with one armature) or the first body used by the spec in the folder, and prints vertex/triangle/bone counts, bone roles, measurements and limb parameters `elbow_t`, `knee_t`. A sanity check for custom bodies.

## mannequin

```
mannequin [--kind mpfb|dummy]
```

Rebuilds a bundled body **inside the repository** (`bodies/`):
- `mpfb` (default) — `mannequin_f` from `bodies/mannequin_f/macro.json` through MPFB (`bl_mpfb.py`). Needs MPFB in `.mpfb/blender_user` or in the profile given by `BP3D_MPFB` (`scripts/install_mpfb.ps1`).
- `dummy` — `dummy_t` from `bp3d/mannequin.py` (`bl_mannequin.py`).

Every approval of a garment built on the rebuilt body becomes stale.

## selftest

```
selftest [--draw] [--only NAME ...]
```

For each `examples/<name>/` with a `spec.py` (sorted), in a separate process: `check`; with `--draw` also `draw --quick` (passes only if a fresh `*_print.png` appeared); for specs that use `bp3d.garment` also `posetest --no-render`. A failed step stops that sample and prints the tail of its output. Final line `образцы в порядке` or the list of failures. Writes into `examples/*/out/`.

## Environment variables

| Variable | Used by | Meaning |
|---|---|---|
| `BP3D_BLENDER` | everything that runs Blender | Full path to the Blender executable (checked first) |
| `BP3D_BROWSER` | `draw`, `crop` | Full path to Edge/Chrome/Chromium |
| `BP3D_MPFB` | `mannequin --kind mpfb` | Blender user-resources folder with MPFB installed |
| `BP3D_UV` | `scripts/install.*` | Path to `uv` if it is not in `PATH` |
| `PYTHONPATH` | all | Repository root (the tool is not pip-installed) |
