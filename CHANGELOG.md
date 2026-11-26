# Changelog

All notable changes to Blueprint3D. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow [Semantic Versioning](https://semver.org/) as described in [docs/development.en.md](docs/development.en.md#versioning-and-releases).

Every pull request that changes the tool adds a line under **Unreleased** (CI checks this). Mark changes that alter approval hashes of user objects with **[hash]** and changes that break existing specifications with **[breaking]**.

## [Unreleased]

### Added
- Folds (`bp3d.folds`): fold curves with profiles (`ridge`, `valley`, `pipe`, `crease`, `groove`, `step`, `stitch`) and modes `geo` (geometry, automatic densification across the fold), `normal` (tangent-space normal map baked by the UV layout) and `mask` (fold mask for the artist); `Model.atlas_px`.
- Garment fold helpers: `auto_folds`, `folds_accordion`, `folds_tension`, `folds_hanging`, `folds_spiral`, `folds_gather`, `fold_crease`, `folds_pressed`, `folds_quilt`, `seam`, `limb_arc`, `limb_line`; `Outfit.add(folds=...)`, `Piece.folds`.
- Garment blocks: `binding`, `waistband`, `sneaker_details`; `pants` loose cut (`ease` by landmarks, `leg_ease` by zones, `leg_around`, `leg_tent`, `leg_smooth`, `crease`, `elastic`).
- Weights through a proxy body for loose garments (`bind="loose"`, `Body.proxy`), blended by the gap to the body; weight smoothing by distance (`smooth_mm`).
- Pose test: stretch and compression of the outer layer against the skin under it, zone thresholds; skin self-collision detection (`skin` rows, not counted).
- Rigid binding by segments (`bind=dict(mode="segments", bone=…, cuts=[…])`): a part rotates with several bones without deforming inside a segment; blocks may carry a default binding (`Piece.bind`); `Outfit.shoe_bind`.
- Garment blocks: `panel` (overlay on a region of a garment grid, bevelled edge, stitch line), `shoe_overlays` (toe cap, heel counter), `shoe_tread` (tread and sidewall groove in the normal map); `sneaker_details(eyestay, pull_tab, over)`; `ribbon(across, conform)`; helpers `drop_on`, `surface_of`.
- Sheet: `views[].folds` — fold lines on views.
- Sample `examples/garment_folds`.
- `mesh.refine_patch`, `QuadMesh.sync_patches`, `QuadMesh.gid`, `QuadMesh.patch_uv`.
- Developer documentation: documentation map, architecture, module reference, CLI reference, file formats, development guide (English and Russian).
- Documentation policy: code changes must come with docs and a changelog entry; enforced by the `docs` CI job.
- Code of Conduct (Contributor Covenant 2.1).

### Changed
- **[hash]** Garment weights are smoothed over the fabric by distance by default (`SMOOTH_MM_TIGHT` = 20 mm): existing garments get different weights.
- **[hash]** `garment.py`, `mesh.py`, `rig.py`, `body.py` changed: approval hashes of garment objects change.
- **[hash]** Garments: the stand collar is built from rings around the neck axis (even top edge, constant clearance, lower at the front; `front_drop`) instead of pushing each point out of the body.
- **[hash]** Garments: `shoe()` is built on a last with a separate sole patch (`sole`, `welt`, `toe`, `toe_height`) instead of wrapping the foot; default `ease` 3.0, `sole` 10.0, `cols` 24.
- **[hash]** Garments: `shoe()` is a rigid model by default (`fit="rigid"`): foot bone, toe hinge past the ball line (`flex`), shaft of a high boot on the shin (`shaft_bend`), collar looser towards the top (`ankle_room`). `fit="skin"` keeps the former leg-weight binding. `Outfit.add(bind=None)` now takes the block's binding, else `"auto"`.
- **[hash]** Garments: `shoe()` is smoother — `bend_rings` = 6 (was 4), `stations` = 13 (was 9), `sole_stations` = 27 (was 15); last sections smoothed by distance (`LAST_SMOOTH` = 14 mm); the sole outline is the convex hull of the upper's footprint offset by the welt; the tongue of `sneaker_details` settles onto the shoe.
- **[hash]** Garments: `buckle()` takes `normal` and `up` and lies on the belt; `belt()` returns `front_normal` and `front_up`. The buckle is now positioned by `center` on the belt surface.
- **[hash]** Garments: skirt dynamics defaults use only leg and pelvis colliders.
- Pose test: chains of one dynamics zone are linked laterally (`posetest.LATERAL`), so a hem no longer sags as a wedge between the thighs; `<name>_dynamics.json` chains carry `ring`.
- Atlas: pattern kind `fill` (whole island in one colour).

### Fixed
- Sheet: the binding column of the layers table showed `bind="tight"` as a bone ("кость tight"); it now names skin weights, proxy body, rigid segments or a bone.
- **[hash]** Garments: the shoe sole is a cup with a `rand` wall that rises along the upper; the stand collar starts exactly at the neckline edge; `bodice()` evens out the neckline edge and smooths the fabric near the neck.
- Docs: the garment pipeline is marked as early-stage in the README, the manual and `AGENTS.md`, with a request to report problems or send fixes.
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
