# Blueprint3D documentation

[Русская версия](README.ru.md)

Every document exists in English (`*.en.md`) and Russian (`*.ru.md`) with the same content.

## I want to…

| …do this | Read |
|---|---|
| Install the tool and make my first object | [README](../README.md) → [Manual](manual.en.md) (Installation, Commands, Workflow) |
| Write a specification: solids, surfaces, quad meshes, the sheet | [Manual](manual.en.md) (Object specification, Geometry, Sheet) |
| Make clothing on a rigged body | [Manual → Clothing](manual.en.md#clothing), [bodies](../bodies/README.md) |
| Look up a command, flag or exit code | [CLI reference](cli.en.md) |
| Know what a generated file contains, use the output in an engine | [File formats](file-formats.en.md) |
| Understand how the tool works inside | [Architecture](architecture.en.md) → [Module reference](modules.en.md) |
| Change the tool, add a feature, send a pull request | [Development guide](development.en.md), [CONTRIBUTING](../CONTRIBUTING.md) |
| Work on it as an AI agent | [AGENTS.md](../AGENTS.md) |
| See what changed between versions | [CHANGELOG](../CHANGELOG.md) |

## Documents

| Document | Audience | Content |
|---|---|---|
| [manual](manual.en.md) | users | Full user manual: installation, commands, workflow, spec format, geometry, clothing, sheet, self-review checklists, rules learned in practice, limitations |
| [cli](cli.en.md) | users, developers | Every command with options, outputs and exit codes; environment variables |
| [file-formats](file-formats.en.md) | users, integrators | Object folder layout, `approved.json`, `bp3d.json`, `report.json`, manifest, `_dynamics.json`, posetest report, caches |
| [architecture](architecture.en.md) | developers | Components, pipelines, Python ↔ Blender process model, approval hash, coordinate systems, invariants, extension points |
| [modules](modules.en.md) | developers | Each module: responsibility, public API, dependencies, global state, known issues |
| [development](development.en.md) | contributors | Setup, compatibility and code rules, **documentation policy**, how to extend each part, testing, versioning |
| [../bodies/README.md](../bodies/README.md) | users | Bundled bodies, their origin and licence, custom bodies |

## Documentation is mandatory

A change to the tool is finished only when the documentation describes it — in both languages, in the same pull request, with a `CHANGELOG.md` entry. CI checks the minimum; review checks the rest. Rules: [development guide → Documentation policy](development.en.md#documentation-policy).
