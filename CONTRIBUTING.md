# Contributing to Blueprint3D

[Русский — ниже](#по-русски)

Thank you for wanting to make Blueprint3D better. Game designers, programmers, 3D and technical artists, people who know drafting or garment construction — every kind of expertise helps.

## How to send a change

1. Fork the repository and create a branch from `main`.
2. Set up the tool: `scripts/install.ps1` or `scripts/install.sh` (see [README](README.md)).
3. Make your change. Keep existing specifications working: new options are optional and old defaults stay the same.
4. Run the self-test and look at the result:
   ```
   python -m bp3d selftest --draw
   ```
   All samples must pass. Open the sample sheets in `examples/<name>/out/drawing/` and check them by eye. For 3D or garment changes, also run `build` / `posetest` on the affected sample and look at the renders.
5. Update the docs in the same pull request: a new rule, option or limitation goes into both `docs/manual.en.md` and `docs/manual.ru.md` (if you write only one language, say so in the pull request — the maintainer will add the other).
6. Open a pull request and fill in the template. Small focused pull requests are reviewed faster than large mixed ones.

Every pull request needs the maintainer's approval and passing CI before it is merged. Nobody else can push to `main`.

## Good to know

- Changing `kit.py`, `mesh.py`, `body.py`, `garment.py` or `rig.py` changes the approval hash of every object that uses them: users will have to re-approve their drawings. Mention it in the pull request.
- Do not commit generated output (`out/`), environments (`venv/`, `.python/`), caches (`.cache/`, `.mpfb/`), or anything with personal paths and names.
- `.blend` files go through Git LFS. Bodies must be saved with `bl_common.save_clean()`.
- Bug reports and ideas are welcome as issues too — include the command, the full output and, if possible, a minimal `spec.py`.

## Licence of contributions

By sending a pull request you agree that your contribution is licensed under the [Apache License 2.0](LICENSE) (section 5 of the licence), and under [CC0 1.0](examples/LICENSE) for files in `examples/` and `bodies/`.

## Conduct

Be respectful and constructive. Criticise code, not people. Harassment of any kind is not tolerated; the maintainer may close discussions and block participants who ignore this.

---

## По-русски

Спасибо, что хотите улучшить Blueprint3D. Пригодится любой опыт: геймдизайн, программирование, 3D и техарт, черчение, конструирование одежды.

1. Форк, ветка от `main`.
2. Установка: `scripts/install.ps1` или `scripts/install.sh`.
3. Правка. Существующие спецификации должны работать как раньше: новые опции — необязательные, старые умолчания не меняются.
4. `python -m bp3d selftest --draw` — все образцы проходят; листы образцов в `examples/<имя>/out/drawing/` просмотреть глазами. Для 3D и одежды — ещё `build` / `posetest` на затронутом образце и рендеры.
5. Документация — в том же pull request: новое правило, опция или ограничение идёт в `docs/manual.ru.md` и `docs/manual.en.md` (если пишете на одном языке — укажите, второй допишет мейнтейнер).
6. Pull request по шаблону. Маленькие и цельные PR смотрятся быстрее.

Каждый PR вливается только после апрува мейнтейнера и зелёного CI. Пушить в `main` больше никто не может.

Правка `kit.py`, `mesh.py`, `body.py`, `garment.py` или `rig.py` меняет хеш апрува объектов пользователей — напишите об этом в PR. Не коммитить `out/`, `venv/`, `.python/`, `.cache/`, `.mpfb/`, личные пути и имена. Тела сохранять через `bl_common.save_clean()`.

Отправляя PR, вы соглашаетесь, что ваш вклад распространяется по [Apache License 2.0](LICENSE), а файлы в `examples/` и `bodies/` — по [CC0 1.0](examples/LICENSE).
