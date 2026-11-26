# Форматы файлов

[English version](file-formats.en.md) · [Карта документации](README.ru.md)

Все файлы, которые Blueprint3D читает или пишет. Ключи приведены так, как их пишет код; новые ключи могут появляться в минорных версиях, существующие не переименовываются без записи в CHANGELOG с пометкой **[breaking]**.

## Папка объекта

```
<object>/
  spec.py            спецификация (её пишете вы)
  approved.json      запись апрува (bp3d approve)
  out/               всё сгенерированное; никогда не коммитить
    drawing/         <CODE>_print.svg/.png, <CODE>.pdf, <CODE>_blueprint.svg/.png, crop_*.png
    model/           <NAME>.blend/.fbx/.glb, <NAME>_atlas.png, render_*.png, report.json, manifest.json, blender.log
                     одежда: + <NAME>_dynamics.json
    render/          презентационные рендеры + render_<color>.json (жёсткие предметы) или render.json (одежда)
    posetest/        report.json, pose_*.png, worst*_*.png, renders.json
```

`<CODE>` = `model.code` до первого пробела; `<NAME>` = то же, с `-`, заменённым на `_`.

## Входные файлы

### `spec.py`

Модуль Python, в котором есть:

| Имя | Обязательно | Контракт |
|---|---|---|
| `build_model()` | да | Возвращает `bp3d.model.Model` |
| `sheet(model)` | для `draw` | Возвращает словарь листа (ключи: руководство → Лист; справочник: [модули → drawing](modules.ru.md#drawingpy)) |
| глобальная переменная с `Body` (например, `BODY = body.load(...)`) | одежда | Включает проверки одежды, рендер и хеш тела |
| `CODE`, `TITLE` | нет | Соглашение стартового шаблона; `new` заменяет эти две строки |

Папка добавляется в `sys.path`, поэтому спецификация может импортировать вспомогательные модули, лежащие рядом (они **не** входят в хеш апрува).

### `bp3d.json`

Необязательный, ищется в папке объекта или в любой родительской. JSON-объект, ключи которого становятся значениями листа по умолчанию; `sheet(model)` их переопределяет. Типичные ключи: `org` (организация в штампе), `author` (поле разработчика, по умолчанию `Claude`), `approved_by`, `lit`, `doc_type`. В хеш не входит.

```json
{"org": "STUDIO", "author": "Name"}
```

### Файлы тел

`.blend`, `.glb`/`.gltf` или `.fbx` с одной арматурой и мешем с весами; тело стоит на полу, лицом к −Y в Blender. Роли костей угадываются по именам; переопределяются через `body.load(path, roles={...})`, ориентиры — через `landmarks={...}`. Поставляемые тела: `bodies/mannequin_f/mannequin_f.blend` (+ `macro.json` — макропараметры MakeHuman `gender, age, muscle, weight, proportions, height, cupsize, firmness, race`, `targets`, `rig`), `bodies/dummy_t/dummy_t.blend`.

## Записи

### `approved.json`

```json
{
 "spec_hash": "<sha256 hex>",
 "approved_by": "<--by>",
 "note": "<--note: the approver's words>",
 "date": "YYYY-MM-DD",
 "bp3d": "<tool version>"
}
```

`build` сравнивает только `spec_hash`. Коммитьте этот файл вместе со `spec.py`.

## Результат сборки (`out/model/`)

### `report.json`

Пишет `bl_build.py` / `bl_garment.py`, дополняет `build`.

| Ключ | Содержимое |
|---|---|
| `parts` | `{key: {pos, mesh, tris, quads, non_manifold_edges, bbox_dev_mm, group}}`; квадовые детали добавляют `tris_only, brep_dev_max_mm, brep_dev_mean_mm, aspect_max, uv_stretch`; одежда добавляет `verts, layer, bind, dynamics` |
| `warnings` | список строк: отклонение размера > 3 мм, деталь отсутствует в glTF, проблемы сварки |
| `atlas` | `{px, px_per_cm, islands, texture}` |
| `renders` | сделанные проверочные рендеры |
| `total_tris`, `total_quads`, `total_tris_ext` | итоги |
| `bbox_m` | габарит в метрах |
| `files` | `{blend, fbx, glb}` |
| `body` | одежда: `{file, polys, hidden_polys, bones, dynamic_bones}` |
| `dynamics` | одежда: `{file: "<NAME>_dynamics.json", chains, colliders}` |
| `spec_hash`, `draft` | добавляет `build`; `draft: true` для сборок с `--force` |

### Файлы модели

| Файл | Содержимое |
|---|---|
| `<NAME>.blend` | Сцена: детали как объекты (внутренние детали в коллекции `internal`), материалы по отделке; одежда: арматура с костями с пружиной, одежда со скиннингом, `Body_masked` |
| `<NAME>.fbx` | Оси Unity (вперёд −Z, вверх Y), масштаб по единицам, без концевых костей (leaf bones); у одежды включены арматура и `Body_masked` |
| `<NAME>.glb` | Бинарный glTF, настройки экспортёра Blender по умолчанию |
| `<NAME>_atlas.png` | Цветной атлас квадовых деталей (`Model.atlas_px`, по умолчанию 2048 px; цвета островов, узоры, отступ 10 px + расширение краёв) |
| `<NAME>_normal.png` | Карта нормалей квадовых деталей (касательное пространство OpenGL Y+, та же раскладка, что у атласа), запечена из складок режима `normal`; только если такие складки есть |
| `<NAME>_foldmask.png` | Маска складок для художника (серая, яркость — сила складки), из складок режима `mask` |
| `render_*.png` | Проверочные рендеры (Workbench): виды, перспективы, каркасы |
| `manifest.json` | Промежуточный: что было передано в Blender (см. ниже) |
| `blender.log` | stdout + stderr Blender последнего запуска |

### `manifest.json` (Python → Blender)

```
{
  code, title,
  parts: [ {key, pos, name, finish, group, mesh: "cad"|"quad", bbox_mm[6], color, layer, gray, metal, rough,
            quad parts: stats, colored, two_sided, dynamics} ],
  quads: "<path to quads.npz>" | null,
  atlas: {size_mm, px, px_per_cm, islands: [{part, name, tag, x, y, w, h, scale, color, patterns}]},
  rig (garments): {bones: [{name, parent, head, tail}], bone_names, rigid: {key: bone}, hidden_polys,
                   armature, body_meshes, body_file}
}
```

Ключи `quads.npz` для каждой квадовой детали: `<key>|V`, `|F`, `|UV`, `|sharp`, `|tag`; одежда добавляет `|WI` (int32, 4 индекса костей) и `|WW` (веса float32). `cad.glb` и `quads.npz` удаляются после успешной сборки.

### `<NAME>_dynamics.json`

Независимое от движка описание костей с пружиной для одежды. Единицы: метры.

```
{
  "model": "<NAME>",
  "format": "bp3d-dynamics-1",
  "units": "meters",
  "note": "...",
  "chains": [
    {"part", "bones": [names root→tip], "parent", "preset",
     "stiffness", "damping", "gravity", "hit_radius_m",
     "follow": [{"bone", "weight"}], "bone_length_m", "colliders": [names],
     "ring": {"index", "count", "closed"}}   // место цепочки среди цепочек своей зоны (соседние связаны)
  ],
  "colliders": [
    {"name", "bone", "shape": "capsule", "radius_m", "along_bone",
     "start", "end",            // доли длины кости
     "a_rest_mm", "b_rest_mm"}  // концы капсулы в позе покоя, мм CAD
  ]
}
```

Сопоставьте его с компонентом костей с пружиной в движке (UniVRM SpringBone, Magica Cloth BoneSpring или свой). `format` меняется только с мажорной версией.

## Результат рендера

### `out/render/render_<color>.json` (жёсткие предметы)

`{color, paint_linear, finishes, engine, samples, renders: {shot: file}, spec_hash, draft}`. Кадры: `hero`, `front`, `side`, `high`, `lamp`, `wheel` в виде `<NAME>_<color>_<shot>.png`; рядом `<NAME>_lookdev.blend`.

### `out/render/render.json` (одежда)

`{pose, renders: [png names], spec_hash, draft}`. Кадры: `<pose>_toon`, `<pose>_toon_back` и без `--hero-only` — `<pose>_toon_side`, `rest_toon`, `<pose>_matte`, `<pose>_wire`.

## Результат проверки поз (`out/posetest/`)

### `report.json`

| Ключ | Содержимое |
|---|---|
| `poses`, `parts` | что проверялось |
| `thresholds` | `{body, layer, extreme, extreme_poses}` мм |
| `failed` | true, если хоть одна строка превышает свой порог |
| `worst_body`, `worst_layer`, `worst_collider`, `worst_skin`, `worst_stretch`, `worst_compress` | наибольшие глубины, мм |
| `rows` | `[{pose, part, kind: body|layer|collider|skin|stretch|compress, other, depth, count, where, point, rest}]` — наибольшая глубина на позу/деталь/вид; `where` — ближайший ориентир |
| `renders` | `{name: file}` |
| `spec_hash` | хеш проверенной спецификации |

Изображения: `pose_<pose>.png` (каждая поза), `worst<n>_<pose>_<part>.png` (до четырёх худших мест).

### `_shots.json` (Python → `bl_pose.py`, временный)

`{"shots": [{name, pose: {bone: 16 floats row-major, CAD mm}, mode: solid|wire|toon|matte, dir, target, radius, res}]}`.

## Кэши

### `.cache/body_<sha16>.npz`

Тело, экспортированное `bl_body.py`, в пространстве CAD (мм): `V, N, T, W` (веса по костям, нормированные), `tri_poly`, `vert_mesh`, `bone_names, bone_parent, bone_head, bone_tail, bone_deform`, `mesh_names`, `armature`. Ключ — первые 16 шестнадцатеричных цифр SHA-256 файла тела. Можно безопасно удалить.
