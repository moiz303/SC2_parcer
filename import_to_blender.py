import bpy
import bpy_extras.anim_utils as anim_utils
import json
import os


# ========== ОБЩИЕ ФУНКЦИИ ==========

def clear_scene():
    """Очищает сцену"""
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)


def set_smooth_interpolation(obj):
    """Устанавливает плавную интерполяцию для объекта"""
    if not obj.animation_data:
        return False

    action = obj.animation_data.action
    if not action:
        return False

    action_slot = obj.animation_data.action_slot
    if not action_slot:
        return False

    channelbag = anim_utils.action_get_channelbag_for_slot(action, action_slot)
    if not channelbag:
        return False

    modified = False

    for fcurve in channelbag.fcurves:
        if fcurve.data_path == 'location':
            for keyframe in fcurve.keyframe_points:
                if keyframe.interpolation != 'BEZIER':
                    keyframe.interpolation = 'BEZIER'
                    modified = True
                if keyframe.handle_left_type != 'AUTO_CLAMPED':
                    keyframe.handle_left_type = 'AUTO_CLAMPED'
                    modified = True
                if keyframe.handle_right_type != 'AUTO_CLAMPED':
                    keyframe.handle_right_type = 'AUTO_CLAMPED'
                    modified = True

    return modified


# ========== ИМПОРТ ЮНИТОВ ==========

def load_unit_model(unit_type, race, model_folder):
    """Загружает модель юнита (GLTF/GLB)"""
    model_variants = [
        f"{race}_{unit_type}.gltf",
        f"{unit_type}.gltf",
        f"{race}_{unit_type}.glb",
        f"{unit_type}.glb",
        f"{unit_type.lower()}.gltf",
    ]

    for variant in model_variants:
        model_path = os.path.join(model_folder, variant)
        if os.path.exists(model_path):
            try:
                # Импорт GLTF
                bpy.ops.import_scene.gltf(filepath=model_path)
                obj = bpy.context.selected_objects[0]
                obj.name = f"Unit_{unit_type}_{race}"
                return obj
            except Exception as e:
                print(f"Ошибка импорта {variant}: {e}")
                continue

    # Fallback: куб
    bpy.ops.mesh.primitive_cube_add(size=1.0)
    obj = bpy.context.active_object
    obj.name = f"Unit_placeholder_{unit_type}"

    colors = {
        'Terran': (0.2, 0.5, 0.8, 1.0),
        'Zerg': (0.6, 0.2, 0.2, 1.0),
        'Protoss': (0.8, 0.7, 0.2, 1.0),
        'Neutral': (0.5, 0.5, 0.5, 1.0)
    }
    mat = bpy.data.materials.new(name=f"mat_unit_{race}")
    mat.diffuse_color = colors.get(race, (0.5, 0.5, 0.5, 1.0))
    obj.data.materials.append(mat)

    return obj


def import_units_from_json(json_path, model_folder, fps=16.0, animation_start_time=0, animation_end_time=None):
    """
    Импорт юнитов с фильтрацией по времени существования

    Args:
        animation_start_time: начало анимации в секундах (юниты, родившиеся после этого)
        animation_end_time: конец анимации в секундах (юниты, умершие до этого)
    """
    print(f"Загрузка JSON юнитов: {json_path}")

    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    model_cache = {}
    units_created = 0
    total_frames = 0

    if 'fps' in data.get('metadata', {}):
        fps = data['metadata']['fps']

    # Если не указано, используем весь диапазон
    if animation_end_time is None:
        # Находим максимальное время из всех юнитов
        animation_end_time = 0
        for unit_data in data['units']:
            for frame in unit_data.get('frames', []):
                if frame['time'] > animation_end_time:
                    animation_end_time = frame['time']

    print(f"Фильтр по времени: {animation_start_time:.1f} - {animation_end_time:.1f} сек")

    for unit_data in data['units']:
        unit_type = unit_data['type']
        race = unit_data['owner_race']
        frames = unit_data.get('frames', [])

        if not frames:
            continue

        # Пропускаем мусор
        skip_types = ['Creep', 'Effect', 'Missile', 'Unknown', 'Creeper', 'Destructible']
        if unit_type in skip_types:
            continue

        # ========== ФИЛЬТРАЦИЯ ПО ВРЕМЕНИ СУЩЕСТВОВАНИЯ ==========
        born_time = unit_data.get('born_frame', 0) / fps if unit_data.get('born_frame') else 0
        died_time = unit_data.get('died_frame', animation_end_time) / fps if unit_data.get(
            'died_frame') else animation_end_time

        # Пропускаем юнитов, которые родились после конца анимации
        if born_time > animation_end_time:
            continue

        # Пропускаем юнитов, которые умерли до начала анимации
        if died_time < animation_start_time:
            continue

        # Фильтруем кадры по времени
        filtered_frames = [
            f for f in frames
            if animation_start_time <= f['time'] <= animation_end_time
        ]

        if not filtered_frames:
            continue

        # Сдвигаем время для анимации (чтобы первый кадр был на 0)
        min_frame_time = filtered_frames[0]['time']
        for f in filtered_frames:
            f['time'] -= min_frame_time

        # Загружаем модель
        cache_key = f"{race}_{unit_type}"
        if cache_key not in model_cache:
            model_cache[cache_key] = load_unit_model(unit_type, race, model_folder)

        base_model = model_cache[cache_key]

        # Создаём копию
        obj = base_model.copy()
        obj.data = base_model.data.copy()
        obj.name = f"Unit_{unit_type}_{unit_data['unit_id']}"
        bpy.context.collection.objects.link(obj)

        # Сортируем кадры
        sorted_frames = sorted(filtered_frames, key=lambda f: f['time'])

        # Добавляем ключевые кадры
        for frame_data in sorted_frames:
            blender_frame = int(frame_data['time'] * fps)

            if blender_frame > total_frames:
                total_frames = blender_frame

            obj.location = (frame_data['x'], frame_data['y'], frame_data['z'])
            obj.keyframe_insert(data_path="location", frame=blender_frame)

        set_smooth_interpolation(obj)

        units_created += 1
        if units_created % 50 == 0:
            print(f"Создано юнитов: {units_created}")

    print(f"  Юнитов импортировано: {units_created}")
    return units_created, total_frames


# ========== ИМПОРТ СТРОЕНИЙ ==========

def load_building_model(building_type, race, model_folder):
    """Загружает модель здания"""
    model_variants = [
        f"{race}_{building_type}.fbx",
        f"{building_type}.fbx",
        f"{building_type.lower()}.fbx",
        f"building_placeholder.fbx",
    ]

    for variant in model_variants:
        model_path = os.path.join(model_folder, variant)
        if os.path.exists(model_path):
            bpy.ops.import_scene.fbx(filepath=model_path)
            obj = bpy.context.selected_objects[0]
            obj.name = f"Building_{building_type}_{race}"
            return obj

    # Fallback: куб
    bpy.ops.mesh.primitive_cube_add(size=1.0)
    obj = bpy.context.active_object
    obj.name = f"Building_placeholder_{building_type}"

    colors = {
        'Terran': (0.2, 0.5, 0.8, 1.0),
        'Zerg': (0.6, 0.2, 0.2, 1.0),
        'Protoss': (0.8, 0.7, 0.2, 1.0),
        'Neutral': (0.5, 0.5, 0.5, 1.0)
    }
    mat = bpy.data.materials.new(name=f"mat_building_{race}")
    mat.diffuse_color = colors.get(race, (0.5, 0.5, 0.5, 1.0))
    obj.data.materials.append(mat)

    return obj


def import_buildings_from_json(json_path, model_folder, animation_start_time=0, animation_end_time=None, fps=16.0):
    """Импорт строений из JSON"""
    print(f"Загрузка JSON строений: {json_path}")

    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    model_cache = {}
    buildings_created = 0
    total_frames = 0

    if 'fps' in data.get('metadata', {}):
        fps = data['metadata']['fps']

    for building_data in data['buildings']:
        building_type = building_data['type']
        race = building_data['owner_race']
        frames = building_data.get('frames', [])

        if not frames:
            continue

        # Пропускаем нейтральные объекты (минералы, газ)
        skip_neutral = ['MineralField', 'VespeneGeyser', 'XelNagaTower', 'Destructible']
        if building_type in skip_neutral:
            continue

        # ========== ФИЛЬТРАЦИЯ ПО ВРЕМЕНИ СУЩЕСТВОВАНИЯ ==========
        born_time = building_data.get('born_frame', 0) / fps if building_data.get('born_frame') else 0
        died_time = building_data.get('died_frame', animation_end_time) / fps if building_data.get(
            'died_frame') else animation_end_time

        # Пропускаем строения, которые построены после конца анимации
        if born_time > animation_end_time:
            continue

        # Пропускаем строения, которые разрушены до начала анимации
        if died_time < animation_start_time:
            continue

        # Фильтруем кадры по времени
        filtered_frames = [
            f for f in frames
            if animation_start_time <= f['time'] <= animation_end_time
        ]

        if not filtered_frames:
            continue

        # Сдвигаем время для анимации (чтобы первый кадр был на 0)
        min_frame_time = filtered_frames[0]['time']
        for f in filtered_frames:
            f['time'] -= min_frame_time

        cache_key = f"{race}_{building_type}"
        if cache_key not in model_cache:
            model_cache[cache_key] = load_building_model(building_type, race, model_folder)

        base_model = model_cache[cache_key]

        obj = base_model.copy()
        obj.data = base_model.data.copy()
        obj.name = f"Building_{building_type}_{building_data['building_id']}"
        bpy.context.collection.objects.link(obj)

        sorted_frames = sorted(frames, key=lambda f: f['time'])

        for frame_data in sorted_frames:
            blender_frame = int(frame_data['time'] * fps)

            if blender_frame > total_frames:
                total_frames = blender_frame

            obj.location = (frame_data['x'], frame_data['y'], frame_data['z'])
            obj.keyframe_insert(data_path="location", frame=blender_frame)

        set_smooth_interpolation(obj)

        buildings_created += 1
        if buildings_created % 20 == 0:
            print(f"Создано строений: {buildings_created}")

    print(f"  Строений импортировано: {buildings_created}")
    return buildings_created, total_frames


# ========== ОСНОВНАЯ ФУНКЦИЯ ==========

def import_all(units_json_path, buildings_json_path, model_folder, start_seconds=0, end_seconds=None):
    """
    Импортирует юнитов и строения с фильтрацией по времени

    Args:
        start_seconds: начало анимации в секундах
        end_seconds: конец анимации в секундах (None = до конца)
    """
    clear_scene()

    # Импорт юнитов с фильтрацией
    units_count, units_frames = import_units_from_json(
        units_json_path, model_folder,
        animation_start_time=start_seconds,
        animation_end_time=end_seconds
    )

    # Импорт строений с фильтрацией
    buildings_count, buildings_frames = import_buildings_from_json(
        buildings_json_path, model_folder,
        animation_start_time=start_seconds,
        animation_end_time=end_seconds
    )

    # Настраиваем временную шкалу
    max_frames = max(units_frames, buildings_frames)
    fps = 16.0

    try:
        with open(units_json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if 'fps' in data.get('metadata', {}):
                fps = data['metadata']['fps']
    except:
        pass

    bpy.context.scene.render.fps = int(fps)
    bpy.context.scene.frame_end = max_frames + 10

    print(f"\n=== ИМПОРТ ЗАВЕРШЁН ===")
    print(f"  Юнитов: {units_count}")
    print(f"  Строений: {buildings_count}")
    print(f"  Всего объектов: {units_count + buildings_count}")
    print(f"  Длительность анимации: {max_frames / fps:.2f} сек")

    return units_count + buildings_count


# Запуск
if __name__ == "__main__":
    UNITS_JSON_PATH = "C:\\Users\\0\\PycharmProjects\\SC2_parcer\\replay_units_output.json"
    BUILDINGS_JSON_PATH = "C:\\Users\\0\\PycharmProjects\\SC2_parcer\\replay_buildings_output.json"
    MODEL_FOLDER = "C:\\Users\\0\\Documents\\StarCraft II\\Exported_Models\\fbx_models"

    import_all(UNITS_JSON_PATH, BUILDINGS_JSON_PATH, MODEL_FOLDER, 0, 900)