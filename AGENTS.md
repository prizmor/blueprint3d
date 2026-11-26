# Blueprint3D — guide for AI agents

This file is for coding agents (Claude Code, Codex, Cursor and others) that install Blueprint3D, use it to make drawings and models, or improve the tool itself. Humans: start with [README.md](README.md).

Answer the user in the language they write in. The CLI prints messages in Russian; the manual exists in [English](docs/manual.en.md) and [Russian](docs/manual.ru.md) with the same content.

## 1. What the tool does

One parametric Python specification (`spec.py` with `build_model()` and `sheet(model)`) produces:
- a drawing sheet (SVG/PNG/PDF) projected from the solids, and
- a 3D model (`.blend`, `.fbx`, `.glb`, renders, `report.json`) built from the same solids in headless Blender.

Two mesh paths: `mesh="cad"` (CAD tessellation — grey block-out) and `mesh="quad"` (clean quads with UVs from the construction grids — game topology). Garments are quad meshes on a rigged body with weights, spring bones and body masking.

## 2. Set up and verify (do this before anything else)

1. **Clone with LFS.** `git lfs install`, then `git clone <repo-url>`. If `bodies/*/*.blend` are ~130-byte text files, LFS was not pulled: run `git lfs pull` in the repo (the installer does this too).
2. **Install.** Windows: `powershell -ExecutionPolicy Bypass -File scripts\install.ps1`. Linux/macOS: `sh scripts/install.sh`. It creates `venv/` and prints `Blender: <path>` and `Browser: <path>`.
3. **Blender 5.3** is needed for `build`, `render`, `posetest`, `body`, `mannequin` and for `check` of garments (the body is exported once through Blender and cached in `.cache/`). Not found → set `BP3D_BLENDER` to the full path of `blender.exe` / `blender`. Do not install Blender yourself without the user's consent.
4. **Browser** (Edge/Chrome/Chromium) is needed only for PNG/PDF of the sheet and for `crop`. Not found → `BP3D_BROWSER`, or work with SVG.
5. **Verify:** from the repo root, `PYTHONPATH=<repo>` and `venv/…/python -m bp3d selftest`. Every sample must report OK. With Blender present, the garment sample also runs `posetest`.

If a step fails because the network is unavailable, stop and tell the user. Do not change system or network settings and do not bypass certificate checks.

## 3. How to run commands

The tool is not pip-installed: `PYTHONPATH` points at the repository root, and the venv Python runs the package.

```powershell
$env:PYTHONPATH = "C:\path\to\blueprint3d"; $py = "C:\path\to\blueprint3d\venv\Scripts\python.exe"
& $py -m bp3d <command> <object folder> [options]
```

```sh
PYTHONPATH=/path/to/blueprint3d /path/to/blueprint3d/venv/bin/python -m bp3d <command> <object folder>
```

Object folders belong to the user's project (for example `art/blueprints/<CODE>/`), never to this repository. Outputs go to `<object>/out/` — never commit them. A `bp3d.json` found in the object folder or any parent sets sheet defaults (`org`, `author`, …).

Commands: `new`, `check`, `draw [--quick]`, `crop`, `approve`, `build [--force] [--out]`, `render`, `status`, `posetest`, `body`, `mannequin`, `selftest [--draw] [--only …]`. Exit code 1 means errors (check) or penetrations above the threshold (posetest). Full table — manual, section «Команды» / "Commands".

## 4. Making an object

1. **Passport.** Purpose, real overall size, key dimensions, what is visible and what is internal. Anything the user did not give you is a *proposal* — say so, do not invent silently.
2. `new <folder> --code <CODE> --title "<title>"` → replace the template's geometry and sheet with your own. Study the closest sample in `examples/` for technique, not for shape.
3. `check` → fix every error before drawing.
4. `draw --quick`, then inspect the sheet zone by zone with `crop` (overlapping text, wrong dimensions, stray lines, flat panels).
5. **Draft 3D before showing anything:** `build --force --out <temp folder>` and look at the renders. They reveal gaps, inside-out parts and collisions that lines hide.
6. Full `draw`, show it to the user. **Approval comes only from the user, in their own words.** Record it: `approve <folder> --by "<who>" --note "<their words>"`.
7. `build` without `--force`; read `report.json` (open meshes, size deviations ≤ 3 mm) and look at the renders.
8. `render` if a colour presentation is needed. Colours and palette are the user's choice.

Any change to `spec.py`, `kit.py` or `mesh.py` after approval makes the approval stale (for garments also `body.py`, `garment.py`, `rig.py` and the body file). Re-draw and get a new approval. `--force` output is a draft for your own checks, never a result for the user.

**Garments are at an early stage:** expect glitches, tell the user about every defect you see in the renders instead of hiding it, and report tool problems as issues or fix them in a pull request.

**Garments:** `new → check → draw --quick → crop → build --force → posetest → fixes → draw → approval → build → posetest → render`. Read the manual's «Одежда» / "Clothing" section first: body landmarks, layers and gaps, density near joints, binding, spring-bone dynamics, the rules learned in practice (sleeve not ending at the elbow, belt on body weights, skirt dynamics from the hip line, overlays with `over=[…]`).

## 5. Improving the tool

- Work on a branch; send changes as a pull request (see [CONTRIBUTING.md](CONTRIBUTING.md)). `main` is protected: only the maintainer merges.
- Add what is missing to `bp3d/` with comments; **existing specifications must keep working** (new `Model.add` fields are optional, defaults unchanged).
- After any change in `bp3d/`: `python -m bp3d selftest --draw` — all samples pass, then look at the sample sheets in `examples/<name>/out/drawing/` with your own eyes.
- A changed `kit.py`, `mesh.py`, `body.py`, `garment.py` or `rig.py` changes the approval hash of every user object built on it. Say so in the pull request.
- **Documentation is mandatory — part of the change, not a follow-up.** Before you write code, read [docs/architecture.en.md](docs/architecture.en.md) and the section of [docs/modules.en.md](docs/modules.en.md) for the modules you touch. In the same pull request:
  - add a line to `CHANGELOG.md` under **Unreleased** (mark **[hash]** / **[breaking]** where it applies);
  - update every document the change affects — the table "You changed → Update" in [docs/development.en.md](docs/development.en.md#documentation-policy) says which (CLI, file formats, modules, architecture, manual);
  - update **both** languages (`*.en.md` and `*.ru.md`);
  - copy names, defaults and thresholds from the code; do not describe intentions as behaviour;
  - put a new technique into a sample or the starter template so `selftest` covers it.

  The CI job `docs` fails a pull request that changes `bp3d/`, `scripts/`, `examples/`, `bodies/` or `requirements.txt` without `CHANGELOG.md` and documentation. If you notice documentation that disagrees with the code, fix it in the same pull request or report it.
- Blender scripts that save `.blend` files that end up in git (bodies) must use `bl_common.save_clean()` — plain `save_as_mainfile` stores the absolute path of the machine it ran on.
- Do not commit `venv/`, `.cache/`, `.python/`, `.mpfb/`, `out/`, personal paths, user names or project/company names.

## 6. Where to look

| Question | Place |
|---|---|
| Spec format, part fields, groups, finishes | manual → «Спецификация объекта» / "Object specification" |
| Double-curvature panels, quad meshes, pitfalls | manual → «Геометрия» / "Geometry" |
| Garments, body, layers, dynamics, posetest | manual → «Одежда» / "Clothing" |
| Sheet keys (views, sections, dims, tables) | manual → «Лист» / "Sheet" |
| Self-check lists for drawing, model, garment | manual → «Самопроверка» / "Self-review" |
| Bodies, their origin and licence, custom bodies | [bodies/README.md](bodies/README.md) |
| Working examples | `examples/*/spec.py` (`starter` is the template) |
| How the tool is built: stages, Python ↔ Blender, hash, axes | [docs/architecture.en.md](docs/architecture.en.md) |
| What each module does, public API, global state, known issues | [docs/modules.en.md](docs/modules.en.md) |
| Every command, flag, exit code, environment variable | [docs/cli.en.md](docs/cli.en.md) |
| Every file the tool reads or writes | [docs/file-formats.en.md](docs/file-formats.en.md) |
| Rules for changing the tool, documentation policy, testing, versions | [docs/development.en.md](docs/development.en.md) |
| Map of all documents | [docs/README.md](docs/README.md) |
