# Changelog

All notable changes to Blueprint3D. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow [Semantic Versioning](https://semver.org/) as described in [docs/development.en.md](docs/development.en.md#versioning-and-releases).

Every pull request that changes the tool adds a line under **Unreleased** (CI checks this). Mark changes that alter approval hashes of user objects with **[hash]** and changes that break existing specifications with **[breaking]**.

## [Unreleased]

### Added
- Developer documentation: documentation map, architecture, module reference, CLI reference, file formats, development guide (English and Russian).
- Documentation policy: code changes must come with docs and a changelog entry; enforced by the `docs` CI job.

### Changed
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
