# Changelog

All notable changes to Blueprint3D. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow [Semantic Versioning](https://semver.org/) as described in [docs/development.en.md](docs/development.en.md#versioning-and-releases).

Every pull request that changes the tool adds a line under **Unreleased** (CI checks this). Mark changes that alter approval hashes of user objects with **[hash]** and changes that break existing specifications with **[breaking]**.

## [Unreleased]

### Added
- Developer documentation: documentation map, architecture, module reference, CLI reference, file formats, development guide (English and Russian).
- Documentation policy: code changes must come with docs and a changelog entry; enforced by the `docs` CI job.
- Code of Conduct (Contributor Covenant 2.1).

### Changed
- **[hash]** Garments: the stand collar is built from rings around the neck axis (even top edge, constant clearance, lower at the front; `front_drop`) instead of pushing each point out of the body.
- **[hash]** Garments: `shoe()` is built on a last with a separate sole patch (`sole`, `welt`, `toe`, `toe_height`) instead of wrapping the foot; default `ease` 3.0, `sole` 10.0, `cols` 24.
- **[hash]** Garments: `buckle()` takes `normal` and `up` and lies on the belt; `belt()` returns `front_normal` and `front_up`. The buckle is now positioned by `center` on the belt surface.
- **[hash]** Garments: skirt dynamics defaults use only leg and pelvis colliders.
- Pose test: chains of one dynamics zone are linked laterally (`posetest.LATERAL`), so a hem no longer sags as a wedge between the thighs; `<name>_dynamics.json` chains carry `ring`.
- Atlas: pattern kind `fill` (whole island in one colour).
- CI: `actions/checkout` and `actions/setup-python` v7 (Node 24).

## [0.4.0] - 2026-11-26

First public release as a standalone repository.

### Added
- Hard-surface pipeline: parametric specification → drafting sheet (SVG/PNG/PDF) and 3D model (`.blend`/`.fbx`/`.glb`) from the same solids; CAD tessellation and quad-mesh paths.
- Garment pipeline on rigged bodies: garment blocks, layers, weight transfer, spring-bone chains, body masking, FBX with armature, pose test with a penetration table.
- Bundled bodies `mannequin_f` (MakeHuman, CC0) and `dummy_t`.
- Project config `bp3d.json` for sheet defaults; `BP3D_BLENDER`, `BP3D_BROWSER`, `BP3D_MPFB` environment variables.
- Installers for Windows (`scripts/install.ps1`), Linux/macOS (`scripts/install.sh`) and MPFB (`scripts/install_mpfb.ps1`).

[Unreleased]: https://github.com/prizmor/blueprint3d/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/prizmor/blueprint3d/releases/tag/v0.4.0
