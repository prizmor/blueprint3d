# Тела с ригом для одежды

Тело — входные данные одежды: меш с арматурой и весами. Хеш файла тела входит в апрув каждой вещи, которая на него опирается: пересборка тела делает эти апрувы устаревшими.

| Тело | Что это | Поза покоя | Скелет |
|---|---|---|---|
| `mannequin_f/mannequin_f.blend` | Женская фигура MakeHuman, собранная MPFB2 по `macro.json` | A-поза | game_engine: 53 кости (`pelvis`, `spine_01…03`, `clavicle_l`, `upperarm_l`, `lowerarm_l`, `hand_l` с пальцами, `thigh_l`, `calf_l`, `foot_l`, `ball_l`, `neck_01`, `head`) |
| `dummy_t/dummy_t.blend` | Манекен кодом (`bp3d/mannequin.py`): сечения, воксельное объединение, автоматические веса | T-поза | Unity Humanoid: 22 кости |

Мерки и ориентиры: `python -m bp3d body <файл>`. Пропорции и параметры фигуры — предложение, не утверждённые мерки персонажа; меняются в `mannequin_f/macro.json` (макропараметры MakeHuman: `gender` 0 — женщина, `age`, `muscle`, `weight`, `proportions`, `height`, `cupsize`, `firmness`; `targets` — отдельные морфы; `rig` — скелет).

## Происхождение и лицензия `mannequin_f`

- Источник: MPFB 2.0.18 (MakeHuman Plugin For Blender), официальный каталог расширений Blender — `https://extensions.blender.org/add-ons/mpfb/`, архив `add-on-mpfb-v2.0.18.zip`, sha256 `c075b3e9b94b8e5556a5f03f4653602d02ea306de08126e8f55ed6dee28a2dad`.
- Код MPFB — GPL-3.0-or-later. В игру он не входит: это инструмент, которым собран меш.
- Базовый меш, морфы и кожа MakeHuman — CC0 («All core assets are shared under Creative Commons, CC0» — `https://static.makehumancommunity.org/about/license.html`). Файлы весов скелета в пакете помечены `"license": "CC0"`.
- Собранные модели можно продавать и использовать в закрытой игре, указание авторства не требуется (`https://static.makehumancommunity.org/mpfb/faq/can_i_sell_models.html`, `.../use_in_closed_source.html`; проверено 2026-11-26).
- Сторонние наборы ассетов MakeHuman (одежда, волосы, позы) имеют свои лицензии и здесь не используются.

`dummy_t` — собственная работа автора инструмента, сторонних ассетов в нём нет.

Оба тела в этой папке передаются в общественное достояние по CC0 1.0 (см. `LICENSE` в этой папке): вещи, собранные на них, ничем не ограничены.

## Пересборка

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_mpfb.ps1    # один раз: MPFB в .mpfb\, ваш профиль Blender не трогается
$env:PYTHONPATH="."; $py="venv\Scripts\python.exe"     # из корня репозитория
& $py -m bp3d mannequin                # mannequin_f из macro.json
& $py -m bp3d mannequin --kind dummy   # dummy_t из bp3d/mannequin.py
```

Сборка убирает служебную геометрию базового меша (вспомогательные сетки, кубики суставов), оставляет веса только костей скелета (до 4 влияний), ставит ступни на пол и сохраняет `.blend` и превью.

## Своё тело

Подойдёт любой `.blend`, `.glb` или `.fbx` с одной арматурой и мешем с весами, стоящий на полу лицом в −Y (Blender). Роли костей распознаются по именам (Unity Humanoid, Mixamo, UE/MakeHuman); для других имён — `body.load(путь, roles={"thigh_L": "<имя кости>", ...})`. Проверка: `python -m bp3d body <файл>` должен напечатать правдоподобные мерки.
