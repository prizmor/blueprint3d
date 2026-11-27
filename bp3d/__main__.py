"""CLI: python -m bp3d <команда> <папка объекта> [опции]

  new      создать папку объекта со spec.py из шаблона examples/starter
  check    собрать тела и проверить их (валидность, пустые детали, габариты) — до отрисовки
  draw     чертёж: SVG, PNG, PDF (белый лист и «синька»); --quick — только белый PNG
  crop     вырезать участок листа крупно — для самопроверки чертежа по зонам
  approve  записать апрув пользователя (хеш spec.py + kit.py)
  build    серая 3D-модель из апрувнутого чертежа (.blend/.fbx/.glb, рендеры, отчёт)
  render   презентационный рендер модели с матовыми материалами
  status   состояние апрува
  selftest проверка самого инструмента на образцах examples/* — после правок bp3d/

Папка объекта содержит spec.py с функциями build_model() -> Model и sheet(model) -> dict.
Результаты: <папка>/out/drawing/*, out/model/*, out/render/*; апрув — <папка>/approved.json.
Правила работы — docs/manual.ru.md (docs/manual.en.md — на английском), порядок для ИИ-агента — AGENTS.md.
"""
import argparse, datetime, glob, hashlib, importlib.util, json, os, re, shutil, subprocess, sys, time

from . import __version__
from .build import export_cad, export_garment, find_blender, run_blender, quad_stats
from .drawing import build_body, wrap_svg

HERE = os.path.dirname(os.path.abspath(__file__))
EXAMPLES = os.path.join(os.path.dirname(HERE), "examples")
REPO = os.path.dirname(HERE)
# Браузер без окна печатает SVG в PNG и PDF. Свой путь — переменная BP3D_BROWSER.
EDGE = [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"]
BROWSER_NAMES = ("msedge", "chrome", "google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
                 "microsoft-edge")
CONFIG_NAME = "bp3d.json"


def project_config(obj):
    """Настройки проекта: первый bp3d.json вверх по папкам от папки объекта (например, {"org": "СТУДИЯ"} —
    надпись в штампе листа). Ключи — значения листа по умолчанию; sheet() спецификации их перекрывает.
    В хеш апрува не входит: это оформление, а не построение."""
    d = os.path.abspath(obj)
    while True:
        p = os.path.join(d, CONFIG_NAME)
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        up = os.path.dirname(d)
        if up == d:
            return {}
        d = up


def spec_hash(obj):
    """Хеш апрува: спецификация и модули построения; правка любого из них делает апрув устаревшим.
    Если спецификация опирается на тело персонажа (в модуле есть BODY = body.load(...)), в хеш входят
    модули одежды и хеш файла тела с таблицами ролей и ориентиров: тело изменилось — апрув устарел."""
    h = hashlib.sha256()
    files = [os.path.join(obj, "spec.py"), os.path.join(HERE, "kit.py"), os.path.join(HERE, "mesh.py")]
    bodies = spec_bodies(obj)
    if bodies:
        files += [os.path.join(HERE, n) for n in ("body.py", "garment.py", "rig.py")]
    for p in files:
        with open(p, "rb") as f:
            h.update(f.read().replace(b"\r\n", b"\n"))
    for b in bodies:
        h.update(b.source_hash.encode("ascii"))
    return h.hexdigest()


_specs = {}


def load_spec(obj):
    if obj in _specs:
        return _specs[obj]
    spec = importlib.util.spec_from_file_location("bp3d_spec", os.path.join(obj, "spec.py"))
    m = importlib.util.module_from_spec(spec)
    sys.path.insert(0, obj)
    spec.loader.exec_module(m)
    _specs[obj] = m
    return m


def spec_bodies(obj):
    """Тела персонажей, на которые опирается спецификация (глобальные переменные модуля типа Body)."""
    with open(os.path.join(obj, "spec.py"), encoding="utf-8") as f:
        if "bp3d.body" not in f.read() and "from bp3d import" not in open(os.path.join(obj, "spec.py"), encoding="utf-8").read():
            return []
    from .body import Body
    return [v for v in vars(load_spec(obj)).values() if isinstance(v, Body)]


def browser():
    env = os.environ.get("BP3D_BROWSER")
    if env and os.path.exists(env):
        return env
    for e in EDGE:
        if os.path.exists(e):
            return e
    for n in BROWSER_NAMES:
        w = shutil.which(n)
        if w:
            return w
    return None


def render_svg(svg_path, png_path, pdf_path, w_mm, h_mm):
    b = browser()
    if not b:
        print("Edge/Chrome/Chromium не найден — PNG/PDF не созданы (путь можно задать в BP3D_BROWSER)")
        return
    d = os.path.dirname(svg_path)
    name = os.path.basename(svg_path)
    px = 4
    tmp = os.path.join(d, "_r.html")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(f'<!doctype html><html><head><meta charset="utf-8"><style>@page{{size:{w_mm}mm {h_mm}mm;margin:0}}'
                f'html,body{{margin:0}}img{{display:block;width:{w_mm * px}px;height:{h_mm * px}px}}'
                f'@media print{{img{{width:{w_mm}mm;height:{h_mm}mm}}}}</style></head><body><img src="{name}"></body></html>')
    url = "file:///" + tmp.replace("\\", "/")
    if png_path:
        _browser_run(b, ["--hide-scrollbars", "--force-device-scale-factor=1", f"--window-size={w_mm * px},{h_mm * px}",
                         f"--screenshot={png_path}", url], png_path)
    if pdf_path:
        _browser_run(b, ["--no-pdf-header-footer", f"--print-to-pdf={pdf_path}", url], pdf_path)
    time.sleep(0.5)
    os.remove(tmp)


def _browser_run(b, args, out, tries=3):
    """Браузер без окна со своим временным профилем: параллельные запуски (два чертежа сразу, selftest рядом с
    draw) не делят профиль — общий профиль давал пустые PNG без ошибки. Пустой или не появившийся файл —
    повтор, после tries попыток — RuntimeError."""
    import tempfile
    for k in range(tries):
        if os.path.exists(out):
            os.remove(out)
        with tempfile.TemporaryDirectory(prefix="bp3d_browser_") as prof:
            subprocess.run([b, "--headless=new", "--disable-gpu", f"--user-data-dir={prof}"] + args, capture_output=True)
            time.sleep(0.3)
        if os.path.exists(out) and os.path.getsize(out) > 0:
            return
    raise RuntimeError(f"браузер не создал {out} за {tries} попытки")


def cmd_check(obj, args):
    """Собрать модель и проверить тела до отрисовки: невалидные и пустые детали ломают проекцию и 3D."""
    t = time.time()
    model = load_spec(obj).build_model()
    bad, groups = [], {}
    lo, hi = [1e9] * 3, [-1e9] * 3
    quads = []
    for p in model.parts:
        s = p.shape
        groups[p.group] = groups.get(p.group, 0) + 1
        if p.mesh == "quad":            # квадовая деталь: B-rep — только грани для чертежа, проверяется сам меш
            why = check_quad(p, quads)
            if why:
                bad.append(p.key)
                print(f"ОШИБКА  {p.key} (поз. {p.pos}, {p.group}): " + "; ".join(why))
            if p.group == "ext":
                a3, b3 = p.quad.bbox()
                for i in range(3):
                    lo[i], hi[i] = min(lo[i], a3[i]), max(hi[i], b3[i])
            continue
        if hasattr(s, "V") and hasattr(s, "T"):      # тело-меш (обстановка): проверять нечего
            continue
        try:
            faces, solids, valid = len(s.faces()), len(s.solids()), bool(s.is_valid)
        except Exception as e:
            faces, solids, valid = 0, 0, False
            print(f"  {p.key}: {type(e).__name__}: {e}")
        why = []
        if faces == 0:
            why.append("пустая деталь (пересечение ничего не дало?)")
        elif not valid:
            why.append("невалидное тело — heal() или не объединять тела")
        if p.group not in ("phantom", "theory") and faces and solids == 0:
            why.append("нет замкнутого тела")
        if why:
            bad.append(p.key)
            print(f"ОШИБКА  {p.key} (поз. {p.pos}, {p.group}): " + "; ".join(why))
        elif solids > 1 and args.verbose:
            print(f"  {p.key}: {solids} тел в одной детали")
        if p.group == "ext" and faces:
            bb = s.bounding_box()
            for i, (a, b) in enumerate(((bb.min.X, bb.max.X), (bb.min.Y, bb.max.Y), (bb.min.Z, bb.max.Z))):
                lo[i], hi[i] = min(lo[i], a), max(hi[i], b)
    print(f"деталей {len(model.parts)}: " + ", ".join(f"{g} {n}" for g, n in sorted(groups.items())))
    if hi[0] > lo[0]:
        print("габариты внешних деталей, мм: " + "  ".join(f"{ax} {a:.0f}…{b:.0f} ({b - a:.0f})"
                                                           for ax, a, b in zip("XYZ", lo, hi)))
    if model.body is not None:
        bad += check_garment(model)
    if quads:
        print(f"квадовых деталей {len(quads)}: квадов {sum(q['quads'] for q in quads)}, "
              f"треугольников {sum(q['tris'] for q in quads)}, "
              f"отклонение от B-rep до {max(q['brep_dev_max_mm'] for q in quads):.2f} мм")
    print(f"позиций спецификации {len(model.bom())}; {time.time() - t:.0f} с")
    print("ошибок нет" if not bad else f"ошибок: {len(bad)} — исправить до отрисовки")
    sys.exit(1 if bad else 0)


ASPECT_MAX = 8.0        # квад длиннее этого соотношения сторон считается вытянутым
BREP_DEV_MAX = 1.5      # мм: квадовый меш дальше от B-сплайна той же сетки — сетка слишком редкая


def check_quad(p, acc):
    """Проверки квадового меша детали. Возвращает список ошибок; предупреждения печатает."""
    st = quad_stats(p, ASPECT_MAX)
    acc.append(st)
    why = []
    if st["nonmanifold_edges"]:
        why.append(f"неманифолдных рёбер {st['nonmanifold_edges']} (три грани на ребре)")
    if st["flipped_edges"]:
        why.append(f"обход граней не согласован на {st['flipped_edges']} рёбрах (лоскут наизнанку)")
    if st["degenerate"]:
        why.append(f"вырожденных граней {st['degenerate']}")
    if st["boundary_edges"] and not st["two_sided"]:
        why.append(f"меш не замкнут: открытых рёбер {st['boundary_edges']}")
    if st["aspect_bad"]:
        why.append(f"вытянутых квадов {st['aspect_bad']} (до {st['aspect_max']:.1f}:1, порог {ASPECT_MAX:g}:1) — "
                   "выровнять число рядов по обоим направлениям")
    if st.get("tverts"):
        why.append(f"T-вершин {st['tverts']} — лоскуты сварены не по общим точкам (согласовать число рядов на кромке)")
    if st["brep_dev_max_mm"] > BREP_DEV_MAX:
        print(f"  ! {p.key}: квады отходят от B-сплайна сетки на {st['brep_dev_max_mm']:.2f} мм — добавить рядов")
    if st["tris"]:
        print(f"  {p.key}: треугольников {st['tris']} (полюса вращения, сварка рядов)")
    return why


BEND_ROLES = {"upper_arm": "плечо", "forearm": "локоть", "hand": "запястье", "thigh": "тазобедренный",
              "shin": "колено", "foot": "щиколотка"}
BEND_R = 45.0           # мм: полюс ближе этого к суставу — в зоне сгиба (деформируется с изломом)


def check_poles(model, p):
    """Полюсы раскладки вне зон сгиба: предупреждение с местом (узлы — развилка в паху, подмышке, капюшон)."""
    import numpy as np
    body = model.body
    topo = p.quad.topology()
    pts = []
    for role, nm in BEND_ROLES.items():
        for s in "LR":
            r = f"{role}_{s}"
            if r in body.roles:
                pts.append((body.joint(r), f"{nm} {s}"))
    near = []
    for P, n in topo["poles"]:
        d = [(float(np.linalg.norm(P - J)), nm) for J, nm in pts]
        if d:
            dm, nm = min(d)
            if dm < BEND_R:
                near.append(f"{nm} ({n} рёбер, {dm:.0f} мм)")
    if topo["poles"]:
        h = topo["valence"]
        print(f"  {p.key}: полюсов {len(topo['poles'])} (3 ребра: {h.get(3, 0)}, 5: {h.get(5, 0)}, 6+: "
              f"{sum(c for k, c in h.items() if k >= 6)})")
    if near:
        print(f"  ! {p.key}: полюс в зоне сгиба — " + "; ".join(near[:4]) + " — увести узел раскладки от сустава")


def check_garment(model):
    """Проверки одежды на теле в исходной позе: ни одна точка не внутри тела, зазор не меньше половины
    отступа слоя, в зонах суставов хватает петель поперёк сгиба. Возвращает ключи деталей с ошибками."""
    import numpy as np
    from .garment import MIN_JOINT_LOOPS
    body, bad = model.body, []
    for p in model.parts:
        if p.mesh != "quad" or p.group in ("phantom", "theory"):
            continue
        q = p.quad
        check_poles(model, p)
        h = body.closest(q.V)
        i = int(h["dist"].argmin())
        dmin = float(h["dist"][i])
        why = []
        if dmin < -0.05:
            why.append(f"входит в тело на {-dmin:.1f} мм ({body.nearest_landmark(q.V[i])}) — увеличить отступ (ease) или слой")
        elif p.layer and dmin < 0.5 * p.info.get("gap", 0.0):
            print(f"  ! {p.key}: зазор до тела {dmin:.1f} мм ({body.nearest_landmark(q.V[i])}) меньше половины отступа слоя")
        for name, pt, axis, half, radius in p.info.get("joints", []):
            ax = np.asarray(axis, float)
            d = q.V - np.asarray(pt, float)
            along = d @ ax
            rad = np.linalg.norm(d - along[:, None] * ax, axis=1)
            m = (np.abs(along) <= half) & (rad <= radius) & (q.vside == 0)
            loops = len({(int(k), round(float(v), 4)) for k, v in zip(q.vpatch[m], q.vuv[m, 1])})
            if loops < MIN_JOINT_LOOPS:
                why.append(f"в зоне «{name}» петель поперёк сгиба {loops}, нужно не меньше {MIN_JOINT_LOOPS} — "
                           "уменьшить row_step или сгустить ряды")
        if why:
            bad.append(p.key)
            print(f"ОШИБКА  {p.key} (поз. {p.pos}, слой {p.layer}): " + "; ".join(why))
    return bad


def _garment_blend(obj, args):
    if getattr(args, "model", ""):
        return os.path.abspath(args.model)
    found = [p for p in glob.glob(os.path.join(obj, "out", "model", "*.blend")) if "lookdev" not in p]
    return found[0] if found else None


def _run_pose(blend, shots, out):
    os.makedirs(out, exist_ok=True)
    js = os.path.join(out, "_shots.json")
    with open(js, "w", encoding="utf-8") as f:
        json.dump(dict(shots=shots), f)
    r = subprocess.run([find_blender(), "-b", blend, "--python", os.path.join(HERE, "bl_pose.py"), "--", js, out],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    os.remove(js)
    if "BP3D_DONE" not in r.stdout:
        sys.exit("рендер поз не удался:\n" + (r.stdout + r.stderr)[-1500:])


def cmd_posetest(obj, args):
    """Одежда в наборе поз: таблица проникновений (тело, слои, коллайдеры) и рендеры худших случаев."""
    from . import posetest as PT
    t = time.time()
    model = load_spec(obj).build_model()
    if model.body is None:
        sys.exit("posetest: у модели нет тела (Outfit(M, BODY))")
    poses = args.poses or [k for k in PT.POSES if k != "hero"]
    for k in poses:
        if k not in PT.POSES:
            sys.exit(f"нет позы {k}; есть: {', '.join(PT.POSES)}")
    rows, summary, rig = PT.run(model, poses)
    limit_ = PT.limit
    out = os.path.abspath(args.out) if args.out else os.path.join(obj, "out", "posetest")
    os.makedirs(out, exist_ok=True)
    kinds = {"body": "тело", "layer": "слой", "collider": "коллайдер", "stretch": "растяжение", "compress": "сжатие",
             "skin": "кожа в теле"}
    print(f"{'поза':14s} {'деталь':14s} {'вид':10s} {'мм':>6s} {'вершин':>6s}  место")
    for r in rows:
        if r["kind"] in ("stretch", "compress"):
            if r["depth"] <= limit_(r["pose"], r["kind"], r["where"]) * 0.8:
                continue
            flag = "!" if r["depth"] > limit_(r["pose"], r["kind"], r["where"]) else " "
            print(f"{flag}{r['pose']:13s} {r['part']:14s} {kinds[r['kind']]:10s} {r['depth'] * 100:5.0f}% {r['count']:6d}  {r['where']}")
            continue
        if r["depth"] < args.show and r["kind"] != "collider":
            continue
        flag = "!" if r["kind"] not in ("collider", "skin") and r["depth"] > PT.limit(r["pose"], r["kind"], r["where"]) else " "
        other = f" ({r['other']})" if r["other"] else ""
        print(f"{flag}{r['pose']:13s} {r['part']:14s} {kinds[r['kind']]:10s} {r['depth']:6.1f} {r['count']:6d}  {r['where']}{other}")
    renders = {}
    blend = _garment_blend(obj, args)
    if blend and not args.no_render:
        shots = [dict(name=f"pose_{k}", pose=PT.bone_matrices(rig, k), mode="solid", dir=(0.6, -1, 0.15), res=(900, 1300),
                      hide=sorted(model.inactive())) for k in poses]
        worst = [r for r in rows if r["kind"] not in ("collider", "skin") and r["point"]][:4]
        cx = model.body.center_x(model.body.lm["waist"])
        for n, r in enumerate(worst):
            p = r["point"]
            v = (p[0] - cx, p[1])
            l = max((v[0] ** 2 + v[1] ** 2) ** 0.5, 1e-6)
            shots.append(dict(name=f"worst{n + 1}_{r['pose']}_{r['part']}", pose=PT.bone_matrices(rig, r["pose"]), mode="solid",
                              dir=(-v[1] / l, v[0] / l, 0.2), target=p, radius=190.0, res=(1100, 1100)))
        _run_pose(blend, shots, out)
        renders = {s["name"]: s["name"] + ".png" for s in shots}
    elif not blend:
        print("рендеров нет: сначала bp3d build (нужен .blend модели)")
    summary.update(spec_hash=spec_hash(obj), rows=[{k: v for k, v in r.items()} for r in rows], renders=renders)
    with open(os.path.join(out, "report.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    print(f"поз {len(poses)}, деталей {len(summary['parts'])}; худшее: тело {summary['worst_body']:.1f} мм "
          f"(порог {PT.PEN_BODY:g}), слои {summary['worst_layer']:.1f} мм (порог {PT.PEN_LAYER:g}; в крайних позах "
          f"{', '.join(PT.EXTREME)} — {PT.PEN_EXTREME:g}), "
          f"коллайдеры отодвигают ткань до {summary['worst_collider']:.0f} мм; растяжение до {summary['worst_stretch'] * 100:.0f} % "
          f"(порог {PT.STRETCH_MAX * 100:.0f}, в крайних позах {PT.STRETCH_EXTREME * 100:.0f}), сжатие до "
          f"{summary['worst_compress'] * 100:.0f} % (порог {PT.COMPRESS_MAX * 100:.0f})  ({time.time() - t:.0f} с)")
    print("posetest пройден" if not summary["failed"] else f"posetest НЕ пройден: строк выше порога {summary['failed']}")
    print(out)
    sys.exit(1 if summary["failed"] else 0)


def cmd_body(obj, args):
    """Мерки и ориентиры тела: файл тела (.blend/.glb/.fbx) или папка объекта со spec.py."""
    from . import body as B
    if os.path.isdir(obj):
        bodies = spec_bodies(obj)
        if not bodies:
            sys.exit("в спецификации нет тела (BODY = body.load(...))")
        b = bodies[0]
    else:
        b = B.load(obj)
    print(f"тело: {b.source}")
    print(f"вершин {len(b.V)}, треугольников {len(b.T)}, костей {len(b.skel.names)}")
    print("роли костей: " + ", ".join(f"{r}={b.skel.names[i]}" for r, i in sorted(b.roles.items())))
    print("мерки, мм:")
    for n, v in b.measures_table():
        print(f"  {n:34s} {v:8.0f}")
    print("параметры конечностей: локоть t={:.2f}, колено t={:.2f}".format(b.lm["elbow_t"], b.lm["knee_t"]))


def cmd_mannequin(args):
    """Пересобрать тела инструмента: манекен MakeHuman (нужен MPFB: scripts/install_mpfb.ps1) или
    манекен кодом (dummy_t)."""
    import numpy as np
    from . import mannequin
    bodies = os.path.join(os.path.dirname(HERE), "bodies")
    if args.kind == "mpfb":
        out = os.path.join(bodies, "mannequin_f")
        prof = os.environ.get("BP3D_MPFB") or os.path.join(REPO, ".mpfb", "blender_user")
        if not os.path.isdir(prof):
            sys.exit("MPFB не установлен: powershell -File scripts\\install_mpfb.ps1 (или BP3D_MPFB — профиль Blender с MPFB)")
        r = subprocess.run([find_blender(), "-b", "--python", os.path.join(HERE, "bl_mpfb.py"), "--", out, "mannequin_f",
                            os.path.join(out, "macro.json")], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", env=dict(os.environ, BLENDER_USER_RESOURCES=prof))
    else:
        out = os.path.join(bodies, "dummy_t")
        os.makedirs(out, exist_ok=True)
        arrays = {}
        for k, m in mannequin.parts().items():
            arrays[k + "|V"], arrays[k + "|F"], arrays[k + "|UV"] = m.V, m.F, m.UV * 0.001
            arrays[k + "|sharp"], arrays[k + "|tag"] = np.zeros((0, 2), int), m.face_tag
        npz, sk = os.path.join(out, "_parts.npz"), os.path.join(out, "_skeleton.json")
        np.savez_compressed(npz, **arrays)
        with open(sk, "w", encoding="utf-8") as f:
            json.dump(mannequin.skeleton(), f)
        r = subprocess.run([find_blender(), "-b", "--factory-startup", "--python", os.path.join(HERE, "bl_mannequin.py"),
                            "--", npz, sk, out, "dummy_t"], capture_output=True, text=True, encoding="utf-8", errors="replace")
        for tmp in (npz, sk, os.path.join(out, "dummy_t.glb")):
            if os.path.exists(tmp):
                os.remove(tmp)
    if "BP3D_DONE" not in r.stdout:
        sys.exit("сборка тела не удалась:\n" + (r.stdout + r.stderr)[-1500:])
    for f in glob.glob(os.path.join(out, "preview_*.png")):
        if not f.endswith("preview_front.png"):
            os.remove(f)
    print("тело пересобрано:", out, "— апрувы вещей на этом теле устарели")


def cmd_render_garment(obj, args, blend):
    """Показ одежды: поза для показа (posetest.HERO) в toon-стиле и матовый кадр. Это превью, а не игровой шейдер."""
    from . import posetest as PT
    from .rig import Rig
    t = time.time()
    model = load_spec(obj).build_model()
    rig = Rig(model)
    out = os.path.abspath(args.out) if args.out else os.path.join(obj, "out", "render")
    pose = args.pose or "hero"
    hide = sorted(model.inactive(getattr(args, "variant", None) or ()))
    if getattr(args, "inspect", ""):
        # осмотр формы деталей: светлый материал, свет со всех сторон, шесть ракурсов, поза покоя (или --pose)
        parts = [k.strip() for k in args.inspect.split(",") if k.strip()]
        keys = {p.key for p in model.parts}
        miss = [k for k in parts if k not in keys]
        if miss:
            sys.exit("нет деталей: " + ", ".join(miss) + "; есть: " + ", ".join(sorted(keys)))
        M = PT.bone_matrices(rig, args.pose) if args.pose else {}
        views = dict(front=(0.7, -1, 0.6), back=(-0.7, 1, 0.5), left=(1, 0, 0.2), right=(-1, 0, 0.2), top=(0.3, -0.4, 1),
                     bottom=(0.3, -0.4, -1))
        shots = [dict(name=f"inspect_{v}", pose=M, mode="inspect", dir=d, res=(1100, 1000), parts=parts)
                 for v, d in views.items()]
        _run_pose(blend, shots, out)
        print(f"осмотр деталей {', '.join(parts)} (6 ракурсов): {out}  ({time.time() - t:.0f} с)")
        return
    M = PT.bone_matrices(rig, pose)
    shots = [dict(name=f"{pose}_toon", pose=M, mode="toon", dir=(0.55, -1, 0.12), res=(1400, 1900)),
             dict(name=f"{pose}_toon_back", pose=M, mode="toon", dir=(-0.6, 1, 0.15), res=(1400, 1900))]
    if not args.hero_only:
        shots += [dict(name=f"{pose}_toon_side", pose=M, mode="toon", dir=(1, -0.15, 0.1), res=(1400, 1900)),
                  dict(name="rest_toon", pose={}, mode="toon", dir=(0, -1, 0.05), res=(1400, 1900)),
                  dict(name=f"{pose}_matte", pose=M, mode="matte", dir=(0.55, -1, 0.12), res=(1400, 1900)),
                  dict(name=f"{pose}_wire", pose=M, mode="wire", dir=(0.55, -1, 0.12), res=(1400, 1900))]
    for s_ in shots:
        s_["hide"] = hide                                  # невыбранные варианты деталей
    _run_pose(blend, shots, out)
    src = os.path.join(os.path.dirname(blend), "report.json")
    rep = dict(pose=pose, renders=[s["name"] + ".png" for s in shots])
    if os.path.exists(src):
        mr = json.load(open(src, encoding="utf-8"))
        rep["spec_hash"], rep["draft"] = mr.get("spec_hash"), mr.get("draft", False)
    json.dump(rep, open(os.path.join(out, "render.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"рендер одежды (toon и матовый, поза {pose}): {out}  ({time.time() - t:.0f} с)")


def cmd_draw(obj, args):
    t = time.time()
    m = load_spec(obj)
    model = m.build_model()
    S = dict(project_config(obj))
    S.update(m.sheet(model))
    S["spec_hash"] = spec_hash(obj)
    out = os.path.join(obj, "out", "drawing")
    os.makedirs(out, exist_ok=True)
    base = os.path.join(out, model.code.split()[0])
    w, h = S.get("size", (841, 594))
    tm = time.time()
    body = build_body(model, S)            # геометрия листа считается один раз, темы отличаются только стилем
    quick = getattr(args, "quick", False)
    for theme in (("print",) if quick else ("print", "blueprint")):
        svg = f"{base}_{theme}.svg"
        with open(svg, "w", encoding="utf-8") as f:
            f.write(wrap_svg(body, theme, model.title))
        render_svg(svg, f"{base}_{theme}.png", f"{base}.pdf" if theme == "print" and not quick else None, w, h)
    print(f"модель {tm - t:.0f} с, лист {time.time() - tm:.0f} с")
    print(f"чертёж: {out}  ({time.time() - t:.0f} с, spec {S['spec_hash'][:12]})")


def cmd_crop(obj, args):
    """Участок листа x, y, w, h (мм) крупным планом из SVG — чтобы смотреть чертёж по зонам."""
    b = browser()
    if not b:
        sys.exit("Edge/Chrome/Chromium не найден: задайте BP3D_BROWSER")
    svgs = glob.glob(os.path.join(obj, "out", "drawing", f"*_{args.theme}.svg"))
    if not svgs:
        sys.exit("нет SVG — сначала bp3d draw")
    svg = svgs[0]
    with open(svg, encoding="utf-8") as f:
        mm = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', f.read(600))
    W, H = (float(mm.group(1)), float(mm.group(2))) if mm else (841.0, 594.0)
    x, y, w, h = args.x, args.y, args.w, args.h
    px = args.scale or min(1500 / w, 1100 / h)
    out = os.path.abspath(args.out) if args.out else os.path.join(
        os.path.dirname(svg), f"crop_{x:.0f}_{y:.0f}_{w:.0f}x{h:.0f}.png")
    tmp = os.path.join(os.path.dirname(svg), "_z.html")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write('<!doctype html><html><head><meta charset="utf-8"><style>html,body{margin:0;overflow:hidden;background:#fff}'
                f'img{{position:absolute;left:{-x * px}px;top:{-y * px}px;width:{W * px}px;height:{H * px}px}}</style></head>'
                f'<body><img src="{os.path.basename(svg)}"></body></html>')
    try:
        _browser_run(b, ["--hide-scrollbars", "--force-device-scale-factor=1", f"--window-size={int(w * px)},{int(h * px)}",
                         f"--screenshot={out}", "file:///" + tmp.replace("\\", "/")], out)
    finally:
        os.remove(tmp)
    print(out)


def cmd_approve(obj, args):
    rec = dict(spec_hash=spec_hash(obj), approved_by=args.by, note=args.note,
               date=datetime.date.today().isoformat(), bp3d=__version__)
    with open(os.path.join(obj, "approved.json"), "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=1)
    print("апрув записан:", rec["spec_hash"][:12])


def cmd_build(obj, args):
    ap = os.path.join(obj, "approved.json")
    cur = spec_hash(obj)
    if not args.force:
        if not os.path.exists(ap):
            sys.exit("нет approved.json — чертёж не апрувнут (bp3d approve)")
        rec = json.load(open(ap, encoding="utf-8"))
        if rec["spec_hash"] != cur:
            sys.exit(f"спецификация изменилась после апрува ({rec['spec_hash'][:12]} -> {cur[:12]}): перерисуйте и апрувните заново")
    t = time.time()
    m = load_spec(obj)
    model = m.build_model()
    out = os.path.abspath(args.out) if args.out else os.path.join(obj, "out", "model")
    os.makedirs(out, exist_ok=True)
    name = model.code.split()[0].replace("-", "_")
    if model.body is not None:          # одежда на теле: веса, кости динамики, тело со срезанными полигонами
        glb, man, rig = export_garment(model, out, name, lin_defl=min(args.lin, 0.3), ang_defl=args.ang)
        rep = run_blender(man, glb, out, name, script="bl_garment.py")
        rep["dynamics"] = dict(file=name + "_dynamics.json", chains=len(rig.chains), colliders=len(rig.colliders))
    else:
        glb, man = export_cad(model, out, lin_defl=args.lin, ang_defl=args.ang)
        rep = run_blender(man, glb, out, name)
    for tmp in (glb, os.path.join(out, "quads.npz")):
        if tmp and os.path.exists(tmp):
            os.remove(tmp)
    rep["spec_hash"] = cur
    rep["draft"] = bool(args.force)
    with open(os.path.join(out, "report.json"), "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1)
    bad = [k for k, v in rep["parts"].items() if v["non_manifold_edges"]]
    print(f"модель{' (ЧЕРНОВИК, без апрува)' if args.force else ''}: {out}  ({time.time() - t:.0f} с)")
    print(f"деталей {len(rep['parts'])}, треугольников {rep['total_tris']} (внешних {rep['total_tris_ext']})"
          + (f", из них квадами {rep['total_quads']} граней" if rep.get("total_quads") else ""))
    if rep.get("body"):
        b = rep["body"]
        print(f"тело {b['file']}: скрыто полигонов {b['hidden_polys']} из {b['polys']}; костей {b['bones']}, "
              f"из них динамики {b['dynamic_bones']}")
    if rep.get("atlas"):
        print(f"атлас {rep['atlas']['px']} px, плотность {rep['atlas']['px_per_cm']} px/см, островов {rep['atlas']['islands']}")
    print("незамкнутые меши:", ", ".join(bad) if bad else "нет")
    for w in rep["warnings"]:
        print("!", w)


def cmd_render(obj, args):
    """Презентационный рендер: матовые материалы по отделке деталей, студийный свет, Cycles."""
    if args.model:
        blend = os.path.abspath(args.model)
    else:
        found = [p for p in glob.glob(os.path.join(obj, "out", "model", "*.blend")) if "lookdev" not in p]
        if not found:
            sys.exit("нет модели — сначала bp3d build")
        blend = found[0]
    if spec_bodies(obj):
        return cmd_render_garment(obj, args, blend)
    out = os.path.abspath(args.out) if args.out else os.path.join(obj, "out", "render")
    name = os.path.splitext(os.path.basename(blend))[0]
    cmd = [find_blender(), "-b", blend, "--python", os.path.join(HERE, "bl_render.py"), "--", out, name, args.color]
    if args.hero_only:
        cmd.append("--hero-only")
    t = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if "BP3D_RENDER_DONE" not in r.stdout:
        sys.exit("рендер не удался:\n" + (r.stdout + r.stderr)[-1500:])
    rep = os.path.join(out, f"render_{args.color}.json")
    if os.path.exists(rep):
        j = json.load(open(rep, encoding="utf-8"))
        src = os.path.join(os.path.dirname(blend), "report.json")
        if os.path.exists(src):
            mr = json.load(open(src, encoding="utf-8"))
            j["spec_hash"], j["draft"] = mr.get("spec_hash"), mr.get("draft", False)
        j["renders"] = {k: os.path.basename(v) for k, v in j["renders"].items()}
        json.dump(j, open(rep, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"рендер ({args.color}): {out}  ({time.time() - t:.0f} с)")


def cmd_status(obj, args):
    cur = spec_hash(obj)
    ap = os.path.join(obj, "approved.json")
    if os.path.exists(ap):
        rec = json.load(open(ap, encoding="utf-8"))
        ok = rec["spec_hash"] == cur
        print("апрув:", rec["date"], rec["approved_by"], "— актуален" if ok else "— УСТАРЕЛ (спецификация изменена)")
    else:
        print("апрува нет")
    print("spec", cur[:12])


def cmd_new(obj, args):
    """Новый объект: копия шаблона examples/starter с подставленными кодом и названием."""
    dst = os.path.join(obj, "spec.py")
    if os.path.exists(dst):
        sys.exit(f"{dst} уже есть — шаблон не записан")
    code = args.code or os.path.basename(obj)
    with open(os.path.join(EXAMPLES, "starter", "spec.py"), encoding="utf-8") as f:
        src = f.read()
    src = src.replace('CODE = "XXX-000"', f"CODE = {json.dumps(code, ensure_ascii=False)}")
    if args.title:
        src = src.replace('TITLE = "Ящик инструментальный"', f"TITLE = {json.dumps(args.title, ensure_ascii=False)}")
    os.makedirs(obj, exist_ok=True)
    with open(dst, "w", encoding="utf-8", newline="\n") as f:
        f.write(src)
    print(f"создан {dst} (код {code}) — заменить геометрию и лист шаблона своими")


def cmd_selftest(args):
    """Проверка инструмента на образцах: после правок bp3d/ все образцы должны собираться и рисоваться.
    Каждый образец — отдельным процессом: упавший образец не мешает остальным."""
    env = dict(os.environ, PYTHONPATH=os.path.dirname(HERE), PYTHONIOENCODING="utf-8")
    names = sorted(n for n in os.listdir(EXAMPLES) if os.path.exists(os.path.join(EXAMPLES, n, "spec.py")))
    if args.only:
        names = [n for n in names if n in args.only]
    failed = []
    for n in names:
        obj = os.path.join(EXAMPLES, n)
        steps = [["check"]] + ([["draw", "--quick"]] if args.draw else [])
        with open(os.path.join(obj, "spec.py"), encoding="utf-8") as f:
            if "bp3d.garment" in f.read():          # одежда на теле: ещё и posetest (таблица, без рендеров)
                steps.append(["posetest", "--no-render"])
        for step in steps:
            t = time.time()
            r = subprocess.run([sys.executable, "-m", "bp3d", step[0], obj] + step[1:], env=env,
                               capture_output=True, text=True, encoding="utf-8", errors="replace")
            ok = r.returncode == 0
            if ok and step[0] == "draw":   # чертёж считается готовым, только если PNG действительно появился
                ok = any(os.path.getmtime(p) >= t - 1 and os.path.getsize(p) > 0
                         for p in glob.glob(os.path.join(obj, "out", "drawing", "*_print.png")))
            last = (r.stdout.strip().splitlines() or [""])[-1]
            if step[0] == "posetest":
                last = next((l for l in r.stdout.splitlines() if l.startswith("posetest")), last)
            print(f"{'ok    ' if ok else 'ОШИБКА'} {n:14s} {step[0]:8s} {time.time() - t:4.0f} с  {last}")
            if not ok:
                failed.append(f"{n} {step[0]}")
                print((r.stdout + r.stderr)[-1500:])
                break
    print("образцы в порядке" if not failed else "не прошли: " + ", ".join(failed))
    sys.exit(1 if failed else 0)


def main():
    # Консоль Windows по умолчанию в кодовой странице ANSI: «Ø», «×», «→» в выводе роняли команду
    # с UnicodeEncodeError. Вывод — всегда UTF-8.
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(prog="bp3d", description="Blueprint3D: чертёж кодом и 3D-модель из него")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("selftest", help="проверить инструмент на образцах examples/*")
    s.add_argument("--draw", action="store_true", help="кроме check, отрисовать черновой лист каждого образца")
    s.add_argument("--only", nargs="*", default=[], help="только эти образцы (имена папок)")
    s = sub.add_parser("mannequin", help="пересобрать тела инструмента (bodies/)")
    s.add_argument("--kind", default="mpfb", choices=("mpfb", "dummy"), help="mpfb — манекен MakeHuman; dummy — манекен кодом")

    def add(name, help_):
        s = sub.add_parser(name, help=help_)
        s.add_argument("obj", help="папка объекта со spec.py")
        return s
    s = add("new", "создать объект из шаблона")
    s.add_argument("--code", default="", help="обозначение объекта (по умолчанию — имя папки)")
    s.add_argument("--title", default="", help="название объекта")
    s = add("check", "проверить тела модели до отрисовки")
    s.add_argument("-v", "--verbose", action="store_true", help="показывать детали из нескольких тел")
    s = add("draw", "отрисовать чертёж")
    s.add_argument("--quick", action="store_true", help="черновик: только белый лист PNG, без PDF и «синьки»")
    s = add("crop", "участок листа крупно (мм листа)")
    for a in ("x", "y", "w", "h"):
        s.add_argument(a, type=float)
    s.add_argument("--theme", default="print", choices=("print", "blueprint"))
    s.add_argument("--scale", type=float, default=0, help="пикселей на мм листа (по умолчанию — вписать в 1500×1100)")
    s.add_argument("--out", default="", help="куда сохранить PNG")
    s = add("approve", "записать апрув пользователя")
    s.add_argument("--by", required=True)
    s.add_argument("--note", default="")
    s = add("build", "собрать 3D-модель из апрувнутого чертежа")
    s.add_argument("--force", action="store_true", help="собрать без апрува (черновик для собственной проверки)")
    s.add_argument("--out", default="", help="папка результата (для черновика — вне out/model)")
    s.add_argument("--lin", type=float, default=0.8, help="линейное отклонение тесселяции, мм")
    s.add_argument("--ang", type=float, default=0.15, help="угловое отклонение, рад")
    s = add("render", "презентационный рендер модели")
    s.add_argument("--color", default="graphite", help="матовый цвет окраски: graphite, teal, coral, sand, white, black")
    s.add_argument("--hero-only", action="store_true", help="только главный кадр (сравнение цветов)")
    s.add_argument("--model", default="", help="другой .blend (например, черновая сборка)")
    s.add_argument("--out", default="", help="папка результата")
    s.add_argument("--pose", default="", help="одежда: поза показа (по умолчанию hero), см. posetest.POSES")
    s.add_argument("--variant", nargs="*", default=[], help="одежда: варианты деталей для кадров, «группа:имя» "
                                                               "(по умолчанию — первый вариант каждой группы)")
    s.add_argument("--inspect", default="", help="одежда: осмотр формы деталей (ключи через запятую) — светлый материал, "
                                                 "свет со всех сторон, шесть ракурсов")
    add("status", "состояние апрува")
    s = add("posetest", "одежда в наборе поз: проникновения и рендеры худших случаев")
    s.add_argument("--poses", nargs="*", default=[], help="только эти позы")
    s.add_argument("--show", type=float, default=1.0, help="показывать строки глубже этого, мм")
    s.add_argument("--no-render", action="store_true", help="без рендеров (только таблица)")
    s.add_argument("--model", default="", help="другой .blend (черновая сборка)")
    s.add_argument("--out", default="", help="папка результата")
    add("body", "мерки и ориентиры тела: файл тела или папка объекта")
    a = p.parse_args()
    if a.cmd == "selftest":
        return cmd_selftest(a)
    if a.cmd == "mannequin":
        return cmd_mannequin(a)
    obj = os.path.abspath(a.obj)
    {"new": cmd_new, "check": cmd_check, "draw": cmd_draw, "crop": cmd_crop, "approve": cmd_approve, "build": cmd_build,
     "render": cmd_render, "status": cmd_status, "posetest": cmd_posetest, "body": cmd_body}[a.cmd](obj, a)


if __name__ == "__main__":
    main()
