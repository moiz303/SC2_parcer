import bpy
import math
import json
import os

# ========== ОБЩИЕ ФУНКЦИИ ==========

def clear_scene():
    # Удаляем объекты
    for obj in bpy.data.objects:
        bpy.data.objects.remove(obj, do_unlink=True)
    # Чистим мусор (меши, материалы, экшены)
    for collection in (bpy.data.meshes, bpy.data.materials, bpy.data.actions, bpy.data.images):
        for item in collection:
            collection.remove(item, do_unlink=True)
    bpy.ops.outliner.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)


def get_end_frame(units_json_path, buildings_json_path, fps=16.0):
    """Возвращает реальный последний кадр + буфер, опираясь на макс. кадр в JSON"""
    max_frame = 0

    for path in [units_json_path, buildings_json_path]:
        if not os.path.exists(path): continue
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Сканируем все позиции
        for item in data.get('units', []) + data.get('buildings', []):
            frames = item.get('positions', item.get('frames', []))
            if frames:
                last_f = max(f.get('frame', f.get('time', 0) * fps) for f in frames)
                if last_f > max_frame:
                    max_frame = last_f

            # Также учитываем death_frame, если он есть
            d_f = item.get('died_frame', item.get('death_frame'))
            if d_f and d_f > max_frame:
                max_frame = d_f

    return int(max_frame)


def set_smooth_interpolation(obj):
    """Безопасно сглаживает ключи на любой версии Blender"""
    if not obj.animation_data:
        return

    # Получаем Action (учитывая новый API 5.0+)
    action = None
    if hasattr(obj.animation_data, 'action_slots'):
        slots = obj.animation_data.action_slots
        if slots and len(slots) > 0:
            action = slots[0].action

    if not action and obj.animation_data.action:
        action = obj.animation_data.action
    if not action:
        return

    # Новый API: channels | Старый API: fcurves
    containers = getattr(action, 'channels', []) or getattr(action, 'fcurves', [])

    for cont in containers:
        kps = getattr(cont, 'keyframe_points', [])
        for kp in kps:
            kp.interpolation = 'BEZIER'
            kp.handle_left_type = 'AUTO_CLAMPED'
            kp.handle_right_type = 'AUTO_CLAMPED'


def load_building_model(building_type, race, model_folder):
    model_variants = [
        f"{race}_{building_type}.fbx", f"{building_type}.fbx",
        f"{building_type.lower()}.fbx", "building_placeholder.fbx"
    ]

    for variant in model_variants:
        model_path = os.path.join(model_folder, variant)
        if os.path.exists(model_path):
            try:
                bpy.ops.import_scene.fbx(filepath=model_path)
                # FBX часто импортирует пустышки. Берём первый MESH.
                imported = [o for o in bpy.context.selected_objects if o.type == 'MESH']
                if not imported:
                    raise RuntimeError("В FBX нет мешей")
                obj = imported[0]
                obj.name = f"Building_{building_type}_{race}"

                # 🔑 ПРИНУДИТЕЛЬНО КРАСИМ В ЦВЕТ РАСЫ
                mat = get_race_material(race)
                if obj.data.materials:
                    obj.data.materials[0] = mat  # Заменяем серый FBX-материал
                else:
                    obj.data.materials.append(mat)
                return obj
            except Exception as e:
                print(f"⚠️ Ошибка импорта {variant}: {e}")
                continue

    # Fallback: куб
    bpy.ops.mesh.primitive_cube_add(size=1.0)
    obj = bpy.context.active_object
    obj.name = f"Building_placeholder_{building_type}"

    mat = get_race_material(race)
    obj.data.materials.clear()  # Убираем дефолтный серый слот
    obj.data.materials.append(mat)  # Ставим цветной
    return obj


def load_unit_model(unit_type, race, model_folder):
    # Абсолютно аналогично зданиям, меняются только расширения/префиксы
    model_variants = [
        f"{race}_{unit_type}.gltf", f"{unit_type}.gltf",
        f"{race}_{unit_type}.glb", f"{unit_type}.glb",
        f"{unit_type.lower()}.gltf"
    ]

    for variant in model_variants:
        model_path = os.path.join(model_folder, variant)
        if os.path.exists(model_path):
            try:
                bpy.ops.import_scene.gltf(filepath=model_path)
                imported = [o for o in bpy.context.selected_objects if o.type == 'MESH']
                if not imported:
                    raise RuntimeError("В GLTF нет мешей")
                obj = imported[0]
                obj.name = f"Unit_{unit_type}_{race}"

                mat = get_race_material(race)
                if obj.data.materials:
                    obj.data.materials[0] = mat
                else:
                    obj.data.materials.append(mat)
                return obj
            except Exception as e:
                print(f"⚠️ Ошибка импорта {variant}: {e}")
                continue

    # Fallback: куб
    bpy.ops.mesh.primitive_cube_add(size=1.0)
    obj = bpy.context.active_object
    obj.name = f"Unit_placeholder_{unit_type}"

    mat = get_race_material(race)
    obj.data.materials.clear()
    obj.data.materials.append(mat)
    return obj


def get_race_material(race):
    if race in race_materials:
        return race_materials[race]

    colors = {
        'Терраны': (0.2, 0.5, 0.8, 1.0),
        'Зерги': (0.6, 0.2, 0.2, 1.0),
        'Протоссы': (0.8, 0.7, 0.2, 1.0),
        'Neutral': (0.5, 0.5, 0.5, 1.0)
    }
    color = colors.get(race, (0.5, 0.5, 0.5, 1.0))

    mat = bpy.data.materials.new(name=f"Mat_{race}")
    mat.use_nodes = True

    # Совместимо с Blender 3.x и 4.x
    bsdf = mat.node_tree.nodes.get("Principled BSDF") or mat.node_tree.nodes.get("Principled")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = color
    # Для корректного отображения в Solid-режиме:
    mat.diffuse_color = color[:3] + (1.0,)  # (R, G, B, A)

    race_materials[race] = mat
    return mat


def set_unit_visibility(obj, born_frame, died_frame, timeline_start=1, timeline_end=None):
    """Анимирует видимость юнита с гарантированным скрытием вне его времени жизни."""
    if timeline_end is None:
        timeline_end = bpy.context.scene.frame_end

    # 1. До рождения: скрыт
    obj.hide_viewport = True
    obj.hide_render = True
    obj.keyframe_insert(data_path="hide_viewport", frame=timeline_start - 1)
    obj.keyframe_insert(data_path="hide_render", frame=timeline_start - 1)

    # 2. Рождение: показан
    obj.hide_viewport = False
    obj.hide_render = False
    obj.keyframe_insert(data_path="hide_viewport", frame=born_frame)
    obj.keyframe_insert(data_path="hide_render", frame=born_frame)

    # 3. Смерть: скрыт
    if died_frame is not None:
        obj.hide_viewport = True
        obj.hide_render = True
        obj.keyframe_insert(data_path="hide_viewport", frame=died_frame)
        obj.keyframe_insert(data_path="hide_render", frame=died_frame)

        # 4. Конец таймлайна: остаётся скрытым (защита от экстраполяции)
        obj.keyframe_insert(data_path="hide_viewport", frame=timeline_end)
        obj.keyframe_insert(data_path="hide_render", frame=timeline_end)


# Маппинг координат: SC2 (X вправо, Y вверх по карте, Z высота) → Blender (X вправо, Y вперёд, Z вверх)
def sc2_to_blender(x, y, z):
    return x * COORD_SCALE, -y * COORD_SCALE, z * COORD_SCALE


def animate_worker_patrol(obj, start_pos, target_pos, born_frame, died_frame, fps=16.0, unit_speed=2.25):
    """Генерирует ключи ходьбы туда-сюда между двумя точками с учётом скорости юнита."""
    if died_frame is None:
        died_frame = bpy.context.scene.frame_end

    # Расстояние между точками
    dist = math.hypot(target_pos[0] - start_pos[0], target_pos[1] - start_pos[1])
    if dist < 0.5:  # Слишком близко, нет смысла анимировать
        obj.location = start_pos
        obj.keyframe_insert(data_path="location", frame=born_frame)
        return

    # Сколько кадров идёт один путь (расстояние / скорость * FPS)
    frames_one_way = max(1, int((dist / unit_speed) * fps))

    current_frame = born_frame
    direction = 1  # 1 = к target, -1 = к start
    obj.location = start_pos
    obj.keyframe_insert(data_path="location", frame=current_frame)

    while current_frame < died_frame:
        current_frame += frames_one_way
        if current_frame > died_frame:
            current_frame = died_frame

        current_pos = target_pos if direction == 1 else start_pos
        obj.location = current_pos
        obj.keyframe_insert(data_path="location", frame=current_frame)
        direction *= -1


# ========== ИМПОРТ РАЛИ-ПОИНТНЫХ ЮНИТОВ ==========
def import_sc2_units(JSON_PATH, MODELS_BLEND):
    # 1. Синхронизируем FPS с SC2
    bpy.context.scene.render.fps = 16
    bpy.context.scene.render.fps_base = 1.0

    with open(JSON_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # 2. Кэш моделей (чтобы не грузить один меш 350 раз)
    model_cache = {}  # Ключ: f"{race}_{unit_type}" -> Значение: исходный объект

    def get_unit_model_cached(utype, race, folder):
        cache_key = f"{race}_{utype}"
        if cache_key not in model_cache:
            model_cache[cache_key] = load_unit_model(utype, race, folder)
        return model_cache[cache_key]

    # 3. Проходим по юнитам
    for u in data['units']:
        uid = u['unit_id']
        utype = u['type']
        race = u['owner_race']
        positions = u['positions']
        born = u.get('born_frame', 0)
        died = u.get('died_frame')

        if not positions:
            continue

        # 1. Получаем исходный объект из кэша (импорт происходит только 1 раз)
        src_obj = get_unit_model_cached(utype, race, MODEL_FOLDER)

        # 2. Создаём инстанс: копируем объект, но ШАРИМ mesh-данные
        obj = src_obj.copy()
        obj.data = src_obj.data  # ⚠️ КРИТИЧНО: экономит память и ускоряет анимацию
        obj.name = f"Unit_{utype}_{uid}"
        bpy.context.collection.objects.link(obj)

        # 3. Показываем/скрываем по фрейму рождения
        obj.hide_viewport = True
        obj.hide_render = True
        obj.keyframe_insert(data_path="hide_viewport", frame=START_FRAME + born - 1)
        obj.keyframe_insert(data_path="hide_render", frame=START_FRAME + born - 1)

        obj.hide_viewport = False
        obj.hide_render = False
        obj.keyframe_insert(data_path="hide_viewport", frame=START_FRAME + born)
        obj.keyframe_insert(data_path="hide_render", frame=START_FRAME + born)

        # 4. Анимация позиции
        for pos in positions:
            frame = START_FRAME + pos['frame']
            x, y, z = sc2_to_blender(pos['x'], pos['y'], pos['z'])
            obj.location = (x, y, z)
            obj.keyframe_insert(data_path="location", frame=frame)

        # Скрываем при смерти
        if died is not None:
            death_frame = START_FRAME + died
            obj.hide_viewport = True
            obj.hide_render = True
            obj.keyframe_insert(data_path="hide_viewport", frame=death_frame)
            obj.keyframe_insert(data_path="hide_render", frame=death_frame)

    print(f"✅ Импортировано {len([o for o in bpy.data.objects if o.name.startswith('Unit_')])} юнитов.")


# =============== ИМПОРТ СТРОЕНИЙ ================

def import_buildings_from_json(json_path, model_folder, animation_start_time=0):
    """Импорт строений из JSON"""
    print(f"Загрузка JSON строений: {json_path}")

    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    buildings_created = 0
    total_frames = 0

    if 'fps' in data.get('metadata', {}):
        fps = data['metadata']['fps']

    if 'duration' in data.get('metadata', {}):
        animation_end_time = data['metadata']['duration'].split()
        animation_end_time = int(animation_end_time[0]) * 60 + int(animation_end_time[2])

    for building_data in data['buildings']:
        building_id = building_data['building_id']
        building_type = building_data['type']
        race = building_data['owner_race']
        positions = building_data['frames']

        # Время жизни в секундах
        init_frame = building_data.get('init_frame', 0)
        died_frame = building_data.get('died_frame', animation_end_time * int(fps))

        # 1. Получаем исходный объект здания из кэша
        src_obj = load_building_model(building_type, race, MODEL_FOLDER)

        # 2. Создаём инстанс (shared mesh = экономия памяти)
        obj = src_obj.copy()
        obj.data = src_obj.data
        obj.name = f"Building_{building_type}_{building_id}"
        bpy.context.collection.objects.link(obj)

        # 3. Скрыт до завершения постройки (init_frame вместо born_frame)
        obj.hide_viewport = True
        obj.hide_render = True
        obj.keyframe_insert(data_path="hide_viewport", frame=START_FRAME + init_frame - 1)
        obj.keyframe_insert(data_path="hide_render", frame=START_FRAME + init_frame - 1)

        # 4. Показан в момент завершения постройки
        obj.hide_viewport = False
        obj.hide_render = False
        obj.keyframe_insert(data_path="hide_viewport", frame=START_FRAME + init_frame)
        obj.keyframe_insert(data_path="hide_render", frame=START_FRAME + init_frame)

        # 5. Анимация позиции (полная поддержка мобильных зданий Terran/Zerg)
        for pos in positions:
            frame = START_FRAME + pos['frame']
            x, y, z = sc2_to_blender(pos['x'], pos['y'], pos['z'])
            obj.location = (x, y, z)
            obj.keyframe_insert(data_path="location", frame=frame)

        # 6. Скрываем при уничтожении
        if died_frame is not None:
            death_frame = START_FRAME + died_frame
            obj.hide_viewport = True
            obj.hide_render = True
            obj.keyframe_insert(data_path="hide_viewport", frame=death_frame)
            obj.keyframe_insert(data_path="hide_render", frame=death_frame)

        set_smooth_interpolation(obj)
        buildings_created += 1

    print(f"  Строений импортировано: {buildings_created}")
    return buildings_created, total_frames


# ========== ОСНОВНАЯ ФУНКЦИЯ ==========

def import_all(rally_json_path, buildings_json_path, model_folder, start_seconds=0):
    """
    Импортирует юнитов и строения с фильтрацией по времени

    Args:
        start_seconds: начало анимации в секундах
    """
    clear_scene()

    # Импорт тех юнитов, которые ходили только по рали-поинтам
    import_sc2_units(
        rally_json_path, model_folder
    )

    # Импорт строений с фильтрацией
    buildings_count, buildings_frames = import_buildings_from_json(
        buildings_json_path, model_folder,
        animation_start_time=start_seconds
    )

    # Настраиваем временную шкалу

    try:
        with open(buildings_json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if 'fps' in data.get('metadata', {}):
                fps = data['metadata']['fps']

            max_frames = get_end_frame(rally_json_path, buildings_json_path, fps)
    except:
        pass

    bpy.context.scene.render.fps = int(fps)
    bpy.context.scene.frame_end = max_frames + 15

    print(f"\n=== ИМПОРТ ЗАВЕРШЁН ===")
    print(f"  Длительность анимации: {max_frames / fps:.2f} сек")

    return


# Запуск
if __name__ == "__main__":
    RALLYUNITS_JSON_PATH = "C:\\Users\\0\\PycharmProjects\\SC2_parcer\\replay_rally_output.json"
    BUILDINGS_JSON_PATH = "C:\\Users\\0\\PycharmProjects\\SC2_parcer\\replay_buildings_output.json"
    MODEL_FOLDER = "C:\\Users\\0\\Documents\\StarCraft II\\Exported_Models\\fbx_models"

    # ============= ДЕФОЛТНЫЕ ЗНАЧЕНИЯ ===============
    START_FRAME = 0
    COORD_SCALE = 1.0  # Масштаб карты (1 SC2 unit = 1 Blender unit обычно ок)
    race_materials = {}  # Кэш: 'Terran' -> bpy.data.materials

    import_all(RALLYUNITS_JSON_PATH, BUILDINGS_JSON_PATH, MODEL_FOLDER, start_seconds=START_FRAME)