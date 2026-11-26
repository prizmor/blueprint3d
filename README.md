# Blueprint3D

**Drawing as code → 3D model, one to one.** Describe an object once as a parametric Python specification (`spec.py`) and get both a technical drawing sheet and a game-ready 3D model from the same geometry. What is on the drawing is exactly what is in the model.

[Русская версия](README.ru.md) · [Documentation](docs/README.md) · [Manual](docs/manual.en.md) · [Architecture](docs/architecture.en.md) · [CLI](docs/cli.en.md) · [Guide for AI agents](AGENTS.md)

| Output | What you get |
|---|---|
| Drawing | A drafting-standard sheet (GOST style): SVG, PNG, PDF, white and blueprint themes. Hidden-line projections, sections, detail views, dimensions, callouts, parts list |
| 3D model | `.blend`, `.fbx`, `.glb`, renders, report. Either a CAD tessellation (grey block-out) or a clean quad mesh with UVs built straight from the construction grids |
| Garments | Clothing on a rigged body: quad topology with one-piece layouts (hoods, crotch gussets, cut-outs), folds as geometry and normal maps, overlays and pockets, rigid footwear, part variants, UVs, skin weights, spring-bone chains, body masking, FBX with armature, pose test with a penetration and stretch table |

Works for hard-surface objects (vehicles, weapons, gear, furniture, buildings) and for character clothing in an anime-game style (modelled garments, not cloth simulation).

> **Garments are at an early stage.** The clothing pipeline (body, garment blocks, weights, spring bones, `posetest`) has only just started: expect glitches — crumpled or uneven edges, parts that do not meet cleanly, poses where fabric goes through the body. This is normal for now and will be fixed step by step. If you find a problem, please [open an issue](https://github.com/prizmor/blueprint3d/issues) with the spec and a render, or fix it and send a pull request — see [CONTRIBUTING.md](CONTRIBUTING.md). The hard-surface pipeline is more mature.

## Requirements

- Git with [Git LFS](https://git-lfs.com/) — the rigged bodies in `bodies/` are LFS files
- Python 3.12 (3.10–3.13 work), or [uv](https://docs.astral.sh/uv/), which installs Python by itself
- [Blender 5.3](https://www.blender.org/) — runs headless for the 3D stage (build, render, posetest)
- Microsoft Edge, Google Chrome or Chromium — prints the SVG sheet to PNG and PDF (optional: without it you get SVG only)

Windows is the main platform; Linux and macOS are supported by `scripts/install.sh`.

## Install

```powershell
git lfs install
git clone https://github.com/prizmor/blueprint3d.git
cd blueprint3d
powershell -ExecutionPolicy Bypass -File scripts\install.ps1
```

Linux / macOS: `sh scripts/install.sh`.

The script creates `venv/`, installs build123d (OpenCascade), numpy and scipy, and reports where it found Blender and the browser. If Blender is somewhere unusual, set `BP3D_BLENDER` to the full path of the executable; for the browser, `BP3D_BROWSER`.

Check that everything works:

```powershell
$env:PYTHONPATH = (Get-Location).Path
.\venv\Scripts\python.exe -m bp3d selftest
```

## Quick start

```powershell
$env:PYTHONPATH = "C:\path\to\blueprint3d"; $py = "C:\path\to\blueprint3d\venv\Scripts\python.exe"
& $py -m bp3d new     art\blueprints\BOX-001 --title "Tool box"   # spec.py from the starter template
& $py -m bp3d check   art\blueprints\BOX-001                       # build and validate the solids
& $py -m bp3d draw    art\blueprints\BOX-001 --quick               # white PNG sheet for iterations
& $py -m bp3d build   art\blueprints\BOX-001 --force --out tmp\box # draft 3D model before approval
& $py -m bp3d approve art\blueprints\BOX-001 --by "Name" --note "Approved"
& $py -m bp3d build   art\blueprints\BOX-001                       # final model from the approved drawing
```

Object folders live in **your** project, not in this repository. Results go to `<object>/out/` (keep `out/` out of git — it is reproducible from `spec.py`). An optional `bp3d.json` in your project root sets sheet defaults such as the title-block organisation: `{"org": "MY STUDIO"}`.

Every command, the specification format, geometry, garments, sheet keys and checklists are in the full manual: [English](docs/manual.en.md) · [Русский](docs/manual.ru.md).

## Layout

```
bp3d/          the tool: CLI (__main__.py), geometry (kit.py), quad mesh (mesh.py), sheet (drawing.py),
               Blender scripts (bl_*.py), bodies, garments, rigging, pose test
bodies/        rigged bodies for garments: mannequin_f (MakeHuman, A-pose), dummy_t (code-built, T-pose)
examples/      sample specifications; selftest runs on them; examples/starter is the template for `new`
docs/          documentation in English and Russian: manual, architecture, modules, CLI, file formats, development
scripts/       installers: install.ps1, install.sh, install_mpfb.ps1 (only to rebuild the mannequin)
```

## Contributing — you are welcome here

If you are a good game designer, a good programmer, a 3D artist, or you simply understand this better than I do — please send pull requests. Better geometry, better topology, better drawings, new garment blocks, other engines and platforms, clearer docs, bug fixes: all of it is welcome. The goal is a tool that keeps getting better and produces higher-quality results for everyone.

How it works: fork, branch, change, run `python -m bp3d selftest --draw`, update the documentation and `CHANGELOG.md` (documentation is mandatory for every change), open a pull request. Every pull request is reviewed and merged by the maintainer. Details — [CONTRIBUTING.md](CONTRIBUTING.md).

## License

- **The tool** (everything except `examples/` and `bodies/`) — [Apache License 2.0](LICENSE). Use it for anything, including commercial work; fork it and change it as you like. When you distribute a fork or a modified version you must keep the [NOTICE](NOTICE) file (it names the original project and links here) and mark the files you changed. Please also say plainly in your fork's README that it is a fork of Blueprint3D, with a link to this repository.
- **What you make with it is yours.** The author claims no rights in your specifications, drawings, models, renders or any other output of the program. Copyright belongs to whoever created them.
- **Examples and bodies** — [CC0 1.0](examples/LICENSE) (public domain). Code you copy from `examples/` into your own `spec.py`, and garments built on the bundled bodies, carry no conditions at all.
- Third-party: the `mannequin_f` body is built from MakeHuman core assets (CC0) with MPFB 2 (GPL-3.0, not included). Python dependencies are installed separately and keep their own licenses.
