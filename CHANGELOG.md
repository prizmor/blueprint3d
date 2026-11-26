# Changelog

All notable changes to Blueprint3D. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow [Semantic Versioning](https://semver.org/) as described in [docs/development.en.md](docs/development.en.md#versioning-and-releases).

Every pull request that changes the tool adds a line under **Unreleased** (CI checks this). Mark changes that alter approval hashes of user objects with **[hash]** and changes that break existing specifications with **[breaking]**.

## [Unreleased]

## [0.6.0] - 2026-11-27

### Added
- One-piece garments: `Outfit.hood` (worn or lying on the back, welded to the bodice neckline by a shared row), `drawstring`, `kangaroo_pocket`, `cargo_pocket` (volume, flap, snaps), `panel_at`; `panel(bulge, sides, patch, trapezoid u)`; `binding` on open edges (hood `opening`).
- Cut-outs in quad shells: `Outfit.cutout` (ellipse, rect, slit; quads around the hole, contour as an edge); `Patch.mask`, `Patch.cells`.
- Topology check: `QuadMesh.topology` (poles, valence histogram, T-vertices); `check` reports T-vertices as errors and poles near bend joints (`BEND_R` = 45 mm) as warnings; build report `tverts`, `poles`, `valence`.
- Variants of parts: `Model.add(variant="group:name")` / `Outfit.add(variant=…)`, `Model.variant_groups`, `inactive`, `variants_exclusive`; `render --variant`, `views[].variant`, `sections[].variant`; manifest `variant`; `posetest` does not compare variants of one group.
- `bodice(drape, drape_taper)` — hanging form; `sleeve(smooth, crease)`; `Piece.patch_regions`; `Body.torso_ring/torso_grid(phase)`.
- Sample `examples/garment_hoodie` (hooded top with both hood variants, cargo shorts); `garment_folds` shows a back cut-out with binding.

### Changed
- **[hash]** `pants()` builds a gusset along the inseam by default (`crotch="gusset"`): two 5-edge poles instead of one 6-edge pole at the front and back of the crotch; `crotch="point"` keeps the former layout.
- **[hash]** `mesh.py` changed (cell masks, topology report): approval hashes of all quad objects change, hard-surface ones included.
- **[hash]** Fold refinement caps density by the larger of the neighbouring steps (splits no longer get 1:9 quads); `band()` resamples the edge by the smallest profile step.

## [0.5.0] - 2026-11-26

### Added
- Folds (`bp3d.folds`): fold curves with profiles (`ridge`, `valley`, `pipe`, `crease`, `groove`, `step`, `stitch`) and modes `geo` (geometry, automatic densification across the fold), `normal` (tangent-space normal map baked by the UV layout) and `mask` (fold mask for the artist); `Model.atlas_px`.
- Garment fold helpers: `auto_folds`, `folds_accordion`, `folds_tension`, `folds_hanging`, `folds_spiral`, `folds_gather`, `fold_crease`, `folds_pressed`, `folds_quilt`, `seam`, `limb_arc`, `limb_line`; `Outfit.add(folds=...)`, `Piece.folds`.
- Garment blocks: `binding`, `waistband`, `sneaker_details`; `pants` loose cut (`ease` by landmarks, `leg_ease` by zones, `leg_around`, `leg_tent`, `leg_smooth`, `crease`, `elastic`).
- Weights through a proxy body for loose garments (`bind="loose"`, `Body.proxy`), blended by the gap to the body; weight smoothing by distance (`smooth_mm`).
- Pose test: stretch and compression of the outer layer against the skin under it, zone thresholds; skin self-collision detection (`skin` rows, not counted).
- `render --inspect <keys>`: shape inspection of garment parts in a light matte material with light from all sides, six views (`bl_pose.py` mode `inspect`, shot key `parts`).
- `ribbon(arc, ends, side, conform_on)`; `shoe(nose, rand_fade)`.
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
- **[hash]** Garments: `shoe()` is smoother — `bend_rings` = 6 (was 4), `stations` = 13 (was 9), `sole_stations` = 27 (was 15); last sections smoothed by distance (`LAST_SMOOTH` = 14 mm); the sole outline is the convex hull of the upper's footprint offset by the welt; tongue and eyelet stays of `sneaker_details` are panels on the shoe grid (the tongue starts under the collar instead of rising above it), the pull tab is a loop; the toe ends in a rounded nose and the sole ends close into a vertical line instead of a point.
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

[Unreleased]: https://github.com/prizmor/blueprint3d/compare/v0.6.0...HEAD
[0.6.0]: https://github.com/prizmor/blueprint3d/releases/tag/v0.6.0
[0.5.0]: https://github.com/prizmor/blueprint3d/releases/tag/v0.5.0
[0.4.0]: https://github.com/prizmor/blueprint3d/releases/tag/v0.4.0
