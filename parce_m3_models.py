import bpy
import os
import time
import gc
import logging
from pathlib import Path

# ================= НАСТРОЙКИ =================
SOURCE_DIR = r"C:\Users\0\Documents\StarCraft II\Exported_Buildings\mods\liberty.sc2mod\base.sc2assets\assets\buildings\resources"
DEST_DIR = r"C:\Users\0\Documents\StarCraft II\Imported_Buildings\resourses"
LOG_FILE = os.path.join(DEST_DIR, "m3_batch_export.log")
# =============================================

# Логирование
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
console = logging.StreamHandler()
console.setLevel(logging.INFO)
logging.getLogger().addHandler(console)


def clean_scene():
    """Полная очистка сцены и данных между файлами"""
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)

    for act in list(bpy.data.actions):
        act.use_fake_user = False
        try:
            bpy.data.actions.remove(act)
        except:
            pass

    bpy.data.orphans_purge(do_recursive=True)
    gc.collect()
    bpy.context.view_layer.update()


def process_m3_file(m3_path: str, blend_path: str) -> bool:
    logging.info(f"📂 {Path(m3_path).name}")

    # 1. Импорт
    try:
        getattr(bpy.ops.m3, 'import')(
            filepath=m3_path, get_mesh=True, get_rig=True,
            get_anims=True, get_effects=False
        )
    except Exception as e:
        logging.error(f"❌ Импорт: {e}")
        return False

    obj = next((o for o in bpy.context.scene.objects if o.type == 'ARMATURE'), None)
    if not obj or not hasattr(obj, "m3_animation_groups"):
        logging.warning("⚠️ Нет Armature или m3_animation_groups")
        return False

    native_actions = []
    found_count = 0

    #  ГЛАВНОЕ ОТКРЫТИЕ: данные лежат в anim_group.animations[i].action
    for group in obj.m3_animation_groups:
        for sub_anim in group.animations:
            if not hasattr(sub_anim, 'action') or not sub_anim.action:
                continue

            act = sub_anim.action

            # Пропускаем пустые заглушки
            if len(act.fcurves) == 0:
                continue

            # Уникальное имя (на всякий случай)
            if not act.name.startswith("M3_"):
                act.name = f"M3_{group.name}_{sub_anim.name}"

            act.use_fake_user = True
            native_actions.append(act)
            found_count += 1

    if found_count == 0:
        logging.info("⏭ Нет валидных анимаций")
        return False

    logging.info(f"  ✅ Найдено Actions: {found_count}")

    # 🔪 Удаляем всё, кроме извлечённых Actions
    for act in list(bpy.data.actions):
        if act not in native_actions:
            act.use_fake_user = False
            try:
                bpy.data.actions.remove(act)
            except:
                pass

    bpy.data.orphans_purge(do_recursive=True)

    # 💾 Сохранение
    try:
        bpy.ops.wm.save_as_mainfile(filepath=blend_path, compress=True)
        logging.info(f"💾 Сохранено: {Path(blend_path).name}")
        return True
    except Exception as e:
        logging.error(f"❌ Сохранение: {e}")
        return False


# ================= ГЛАВНЫЙ ЦИКЛ =================
logging.info("🚀 Старт пакетной обработки...")
src, dest = Path(SOURCE_DIR), Path(DEST_DIR)
dest.mkdir(parents=True, exist_ok=True)

files = []
for dirpath, _, fnames in os.walk(SOURCE_DIR):
    m3s = sorted([f for f in fnames if f.lower().endswith('.m3')])
    if not m3s: continue

    m3_path = os.path.join(dirpath, m3s[0])
    blend_path = os.path.join(dest, os.path.splitext(m3s[0])[0] + ".blend")

    if os.path.exists(blend_path):
        logging.info(f"⏭ Пропуск: {os.path.basename(blend_path)}")
        continue

    files.append((m3_path, blend_path))

logging.info(f"📊 Всего новых файлов: {len(files)}")
t0 = time.time()
ok, err = 0, 0

for i, (m3_p, b_p) in enumerate(files, 1):
    logging.info(f"[{i}/{len(files)}] ---")
    if process_m3_file(m3_p, b_p):
        ok += 1
    else:
        err += 1

    clean_scene()
    time.sleep(0.05)  # Минимальная задержка для стабильности

logging.info("=" * 40)
logging.info(f"🏁 ГОТОВО! ✅{ok} ❌{err} ⏱{time.time() - t0:.1f}s")
logging.info("=" * 40)