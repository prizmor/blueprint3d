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
5. **Documentation is mandatory.** In the same pull request: a line in `CHANGELOG.md` under **Unreleased**, and every document your change affects — CLI reference, file formats, module reference, architecture, manual — in both languages (`*.en.md` and `*.ru.md`). Which document covers what: [docs/development.en.md → Documentation policy](docs/development.en.md#documentation-policy). If you can write only one language, say so in the pull request and the maintainer completes the other. CI (job `docs`) rejects code changes without a changelog entry and documentation; a pull request whose docs disagree with the code is not merged.
6. Before writing code, read [docs/architecture.en.md](docs/architecture.en.md) and the [module reference](docs/modules.en.md) for the parts you touch; follow the rules in the [development guide](docs/development.en.md).
7. Open a pull request and fill in the template. Small focused pull requests are reviewed faster than large mixed ones.

Every pull request needs the maintainer's approval and passing CI before it is merged. Nobody else can push to `main`.

## Good to know

- Changing `kit.py`, `mesh.py`, `body.py`, `garment.py` or `rig.py` changes the approval hash of every object that uses them: users will have to re-approve their drawings. Mention it in the pull request.
- Do not commit generated output (`out/`), environments (`venv/`, `.python/`), caches (`.cache/`, `.mpfb/`), or anything with personal paths and names.
- `.blend` files go through Git LFS. Bodies must be saved with `bl_common.save_clean()`.
- Bug reports and ideas are welcome as issues too — include the command, the full output and, if possible, a minimal `spec.py`.

## Licence of contributions

By sending a pull request you agree that your contribution is licensed under the [Apache License 2.0](LICENSE) (section 5 of the licence), and under [CC0 1.0](examples/LICENSE) for files in `examples/` and `bodies/`.

## Conduct

Everyone taking part follows the [Code of Conduct](CODE_OF_CONDUCT.md) (Contributor Covenant 2.1). In short: be respectful and constructive, criticise code, not people. Reports go to the maintainer privately through GitHub (Security → Report a vulnerability).

---

## По-русски

Спасибо, что хотите улучшить Blueprint3D. Пригодится любой опыт: геймдизайн, программирование, 3D и техарт, черчение, конструирование одежды.

1. Форк, ветка от `main`.
2. Установка: `scripts/install.ps1` или `scripts/install.sh`.
3. Правка. Существующие спецификации должны работать как раньше: новые опции — необязательные, старые умолчания не меняются.
4. `python -m bp3d selftest --draw` — все образцы проходят; листы образцов в `examples/<имя>/out/drawing/` просмотреть глазами. Для 3D и одежды — ещё `build` / `posetest` на затронутом образце и рендеры.
5. **Документация обязательна.** В том же pull request — строка в `CHANGELOG.md` в разделе **Unreleased** и все затронутые документы: команды, форматы файлов, модули, архитектура, руководство — на обоих языках (`*.ru.md` и `*.en.md`). Что где описывается — [docs/development.ru.md → Правила документации](docs/development.ru.md#правила-документации). Пишете на одном языке — укажите, второй допишет мейнтейнер. CI (задача `docs`) не пропускает правку кода без записи в changelog и документации; PR, где документация расходится с кодом, не вливается.
6. До правки прочитать [docs/architecture.ru.md](docs/architecture.ru.md) и [справочник модулей](docs/modules.ru.md) по затрагиваемым частям; правила — [руководство разработчика](docs/development.ru.md).
7. Pull request по шаблону. Маленькие и цельные PR смотрятся быстрее.

Каждый PR вливается только после апрува мейнтейнера и зелёного CI. Пушить в `main` больше никто не может.

Правка `kit.py`, `mesh.py`, `body.py`, `garment.py` или `rig.py` меняет хеш апрува объектов пользователей — напишите об этом в PR. Не коммитить `out/`, `venv/`, `.python/`, `.cache/`, `.mpfb/`, личные пути и имена. Тела сохранять через `bl_common.save_clean()`.

Все участники соблюдают [правила поведения](CODE_OF_CONDUCT.md) (Contributor Covenant 2.1): уважительно и по делу, критикуется код, а не люди. Жалобы — мейнтейнеру приватно через GitHub (Security → Report a vulnerability).

Отправляя PR, вы соглашаетесь, что ваш вклад распространяется по [Apache License 2.0](LICENSE), а файлы в `examples/` и `bodies/` — по [CC0 1.0](examples/LICENSE).
