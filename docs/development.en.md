# Development guide

[Русская версия](development.ru.md) · [Documentation map](README.md)

How to work on Blueprint3D itself: setup, rules, how to extend each part, testing, documentation, versioning. For using the tool see the [manual](manual.en.md); for how it is built see [architecture](architecture.en.md) and the [module reference](modules.en.md).

## Setup

1. `git lfs install`, clone, run `scripts/install.ps1` (Windows) or `scripts/install.sh`.
2. Blender 5.3 (for build, render, posetest, garments) and Edge/Chrome/Chromium (for PNG/PDF).
3. `PYTHONPATH=<repo>` and `venv/…/python -m bp3d selftest --draw` must pass before you change anything — otherwise you cannot tell your breakage from an existing one.

There is no packaging step: the package is run from the source tree with `PYTHONPATH`.

## Rules

### Compatibility

- **Existing specifications keep working.** New parameters are keyword arguments with defaults that reproduce the old behaviour. Renaming or removing a public function, a `Model.add` field, a sheet key or a CLI option is a breaking change: avoid it; if unavoidable, keep an alias for at least one minor version and mark the changelog entry **[breaking]**.
- **Approval hashes.** `spec_hash` includes `kit.py`, `mesh.py` and, for garments, `body.py`, `garment.py`, `rig.py` and the body file. Any edit to those files — even a comment — makes every user approval stale. Group such edits, say so in the pull request, mark the changelog entry **[hash]**. Changes that do not affect geometry belong elsewhere (`drawing.py`, `build.py`, `bl_*.py`, `__main__.py` are not hashed).
- **Bodies.** Rebuilding `bodies/*` invalidates garment approvals. Save bodies only with `bl_common.save_clean()`.

### Code

- Python 3.10–3.13; dependencies only from `requirements.txt` (build123d, numpy, scipy). A new dependency needs a reason in the pull request and a line in `requirements.txt` with a pinned or bounded version.
- Blender scripts (`bl_*.py`) run inside Blender's own Python: `bpy`, `mathutils`, numpy only — no build123d, no scipy. They talk to the Python side through files (`manifest.json`, `.npz`, `.glb`, JSON) and print a `BP3D_DONE` marker at the end (see [architecture](architecture.en.md#process-model)).
- Look up shader nodes by type, never by name (names are localised); read enum identifiers instead of hard-coding them.
- Units: millimetres in specs, sheets and reports; metres only inside Blender and exported files. Axes — see [architecture](architecture.en.md#coordinate-systems).
- Comments and CLI messages are in Russian (the existing convention); docstrings say *why*, not *what*. English comments are accepted from contributors.
- Keep functions pure where possible: geometry functions take grids/paths and return new objects; no hidden module state. Existing global state is listed in the [module reference](modules.en.md#global-state) — do not add more.
- No absolute paths, user names, studio or project names in code, docs or bundled files.

### Commits and pull requests

- One topic per pull request. Branch from `main`; `main` is protected — only the maintainer merges, after review and green CI.
- Commit messages: `Area: what changed` in the first line (`Garment: ...`, `Drawing: ...`, `CI: ...`), the reason in the body.
- Squash merge only; the PR title becomes the commit title.

## Documentation policy

**Documentation is part of the change, not a follow-up.** A pull request that changes the tool's behaviour is complete only when the documentation describes the new behaviour.

| You changed | Update |
|---|---|
| Any behaviour, option, default, output | `CHANGELOG.md` under **Unreleased** — always |
| A command, flag, exit code, environment variable | [`cli`](cli.en.md) |
| A file the tool reads or writes, a JSON key, a folder layout | [`file-formats`](file-formats.en.md) |
| A module's responsibility, public function, data structure | [`modules`](modules.en.md) |
| Data flow, a new process boundary, a new stage | [`architecture`](architecture.en.md) |
| Spec API visible to users (kit/mesh functions, `Model.add` fields, garment blocks, sheet keys), a rule learned in practice, a limitation | [`manual`](manual.en.md) |
| How to contribute, test, release | this file, [`CONTRIBUTING.md`](../CONTRIBUTING.md), [`AGENTS.md`](../AGENTS.md) |
| Installation, requirements | [`README.md`](../README.md), [`manual`](manual.en.md#installation), `scripts/` |

- **Both languages.** Every document exists as `*.en.md` and `*.ru.md` with the same content. Update both in the same pull request; if you can write only one, say so in the pull request and the maintainer completes the other before merging.
- **Facts from code.** Names, defaults, keys and thresholds are copied from the code, with the module where they live. Do not document intentions as behaviour.
- **New techniques go into samples.** A new way of building something gets a sample in `examples/` or a section in the starter template, so `selftest` keeps it working.
- **CI enforces the minimum.** The `docs` job fails a pull request that changes `bp3d/`, `scripts/`, `examples/`, `bodies/` or `requirements.txt` without changing `CHANGELOG.md`, and without changing any documentation file. The maintainer may set the label `docs-not-needed` for changes with no visible effect (pure refactoring); the changelog entry is still required.
- **Review checks the docs.** The maintainer reads the documentation diff as carefully as the code diff; a pull request whose docs disagree with the code is not merged.

## Extending the tool

### A new CLI command
1. `cmd_<name>(obj, args)` in `bp3d/__main__.py`; subparser in `main()`; dispatch entry.
2. Outputs under `<object>/out/<name>/`; record `spec_hash` in any report you write.
3. Exit code 1 for failures a script should notice.
4. Docs: [cli](cli.en.md), [file-formats](file-formats.en.md) if it writes files, the manual's command table.

### A geometry function (`kit.py`) or quad builder (`mesh.py`)
1. Pure function, millimetres, grids `(nu, nv, 3)`, outward normal `du × dv`.
2. A quad builder returns a `QuadMesh` that passes `check` (closed, manifold, consistent winding, aspect ≤ 8).
3. Use it in a sample so `selftest` covers it.
4. **[hash]** in the changelog. Docs: manual (Geometry), [modules](modules.en.md).

### A finish
`model.FINISHES` (grey value, metalness, roughness for the grey model), the matching material in `bl_render.py` (presentation) and the toon shading table in `bl_pose.py` (garments). Docs: manual (Object specification).

### A sheet key
Read it in `drawing.build_body` with a default that keeps old sheets unchanged. Docs: manual (Sheet), [modules](modules.en.md#drawingpy).

### A garment block
Method on `garment.Outfit` following the neighbours: grid from top to bottom, normal outward, `push_out` from the body, named edges in `Piece.edges` for blocks that attach to it. Check with `check` (gap, joint loops) and `posetest`. Use it in `examples/garment_basic` or a new garment sample. **[hash]**. Docs: manual (Clothing → Clothing blocks), [modules](modules.en.md#garmentpy).

### A Blender-side feature
Edit the `bl_*.py` script; pass new data through the manifest or the `.npz` (add keys, never change existing ones); add new report keys rather than renaming. Docs: [file-formats](file-formats.en.md).

### A new body
Any `.blend`/`.glb`/`.fbx` with one armature and a weighted mesh, standing on the floor, facing −Y in Blender. Bone roles are guessed from names; unusual names need `roles=`. Bundled bodies: provenance and licence in `bodies/README.md`; must be CC0-compatible; saved with `save_clean()`.

## Testing

| Level | What | When |
|---|---|---|
| `python -m bp3d selftest` | `check` of every sample; `posetest --no-render` of garment samples | after every change in `bp3d/` |
| `selftest --draw` | + `draw --quick` of every sample (needs a browser) | before a pull request; look at the sheets in `examples/*/out/drawing/` |
| `build` / `render` / `posetest` on the affected sample | Blender stage | after changes in 3D, Blender scripts, garments |
| CI `selftest` | hard-surface samples on Ubuntu without Blender | every pull request and push to `main` |
| CI `docs` | documentation policy | every pull request |

`selftest` is the regression suite: a sample that stops passing is a regression, not a sample to delete. A bug fix comes with a sample (or a sample change) that would have caught it, when practical.

## Versioning and releases

- [Semantic Versioning](https://semver.org/): **major** — breaking spec API or file-format change; **minor** — new features, changes that alter approval hashes; **patch** — fixes without hash or API changes.
- The version lives in `bp3d/__init__.py` (`__version__`) and is written into `approved.json`.
- Release: move **Unreleased** entries in `CHANGELOG.md` under a new version heading with the date, bump `__version__`, merge, tag `vX.Y.Z` on `main`, create a GitHub release with the changelog section.
