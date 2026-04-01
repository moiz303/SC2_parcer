import bpy
import bpy_extras.anim_utils as anim_utils
import json
import os


def clear_scene():
    """Очищает сцену"""
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)


def load_model(unit_type, race, model_folder):
    """Загружает FBX модель"""
    model_variants = [
        f"{race}_{unit_type}.fbx",
        f"{unit_type}.fbx",
        f"{unit_type.lower()}.fbx",
    ]

    for variant in model_variants:
        model_path = os.path.join(model_folder, variant)
        if os.path.exists(model_path):
            bpy.ops.import_scene.fbx(filepath=model_path)
            obj = bpy.context.selected_objects[0]
            obj.name = f"{unit_type}_{race}"
            return obj

    # Fallback: куб
    bpy.ops.mesh.primitive_cube_add(size=1.0)
    obj = bpy.context.active_object
    obj.name = f"placeholder_{unit_type}"

    # Раскрашиваем по расе
    mat = bpy.data.materials.new(name=f"mat_{race}")
    mat.diffuse_color = {
        'Terran': (0.2, 0.5, 0.8, 1.0),
        'Zerg': (0.6, 0.2, 0.2, 1.0),
        'Protoss': (0.8, 0.7, 0.2, 1.0),
        'Neutral': (0.5, 0.5, 0.5, 1.0)
    }.get(race, (0.5, 0.5, 0.5, 1.0))

    obj.data.materials.append(mat)
    return obj


def set_smooth_interpolation(obj):
    """
    Устанавливает плавную интерполяцию (BEZIER) для всех ключевых кадров объекта
    Использует новую систему channelbag для Blender 5.0.1
    """
    if not obj.animation_data:
        return False

    action = obj.animation_data.action
    if not action:
        return False

    action_slot = obj.animation_data.action_slot
    if not action_slot:
        return False

    # Получаем channelbag для action и slot
    channelbag = anim_utils.action_get_channelbag_for_slot(action, action_slot)
    if not channelbag:
        return False

    modified = False

    # Проходим по всем F-curves в channelbag
    for fcurve in channelbag.fcurves:
        # Обрабатываем только кривые позиции
        if fcurve.data_path == 'location':
            for keyframe in fcurve.keyframe_points:
                # Меняем тип интерполяции
                if keyframe.interpolation != 'BEZIER':
                    keyframe.interpolation = 'BEZIER'
                    modified = True

                # Настраиваем автоматические ручки для плавности
                if keyframe.handle_left_type != 'AUTO':
                    keyframe.handle_left_type = 'AUTO'
                    modified = True

                if keyframe.handle_right_type != 'AUTO':
                    keyframe.handle_right_type = 'AUTO'
                    modified = True

    return modified


def import_units_from_json(json_path, model_folder, fps=16.0):
    """
    Импорт юнитов из JSON с плавной анимацией
    """
    print(f"Загрузка JSON: {json_path}")

    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    clear_scene()

    # Кэш моделей
    model_cache = {}
    units_created = 0
    total_frames = 0

    # Получаем FPS из метаданных
    if 'fps' in data.get('metadata', {}):
        fps = data['metadata']['fps']
        print(f"FPS из метаданных: {fps}")

    for unit_data in data['units']:
        unit_type = unit_data['type']
        race = unit_data['owner_race']
        frames = unit_data['frames']

        if not frames:
            continue

        # Пропускаем мусор
        skip_types = ['Creep', 'Effect', 'Missile', 'Unknown', 'Creeper', 'Destructible']
        if unit_type in skip_types:
            continue

        # Загружаем модель
        cache_key = f"{race}_{unit_type}"
        if cache_key not in model_cache:
            model_cache[cache_key] = load_model(unit_type, race, model_folder)

        base_model = model_cache[cache_key]

        # Создаём копию
        obj = base_model.copy()
        obj.data = base_model.data.copy()
        obj.name = f"{unit_type}_{unit_data['unit_id']}"
        bpy.context.collection.objects.link(obj)

        # Сортируем кадры по времени
        sorted_frames = sorted(frames, key=lambda f: f['frame'])

        # Добавляем ключевые кадры
        for frame_data in sorted_frames:
            blender_frame = int(frame_data['time'] * fps)

            if blender_frame > total_frames:
                total_frames = blender_frame

            obj.location = (frame_data['x'], frame_data['y'], frame_data['z'])
            obj.keyframe_insert(data_path="location", frame=blender_frame)

        # Применяем плавную интерполяцию
        set_smooth_interpolation(obj)

        units_created += 1
        if units_created % 50 == 0:
            print(f"Создано юнитов: {units_created}")

    # Настраиваем временную шкалу
    bpy.context.scene.render.fps = int(fps)
    bpy.context.scene.frame_end = total_frames + 10

    print(f"\nИмпорт завершён!")
    print(f"  Создано юнитов: {units_created}")
    print(f"  Всего кадров: {total_frames}")
    print(f"  Длительность: {total_frames / fps:.2f} сек")

    return units_created


# Запуск
if __name__ == "__main__":
    JSON_PATH = "C:\\Users\\0\\PycharmProjects\\SC2_parcer\\replay_output.json"
    MODEL_FOLDER = "C:\\Users\\0\\Documents\\StarCraft II\\Exported_Models\\fbx_models"

    import_units_from_json(JSON_PATH, MODEL_FOLDER)