import sc2reader
import json
from collections import defaultdict

from parce_buildings import parse_replay_buildings_to_json as pb


def parse_replay_to_json(replay_path, output_path):
    replay = sc2reader.load_replay(
        replay_path,
        load_level=4,
        use_english_names=True
    )

    print(f"Версия: {replay.release_string}")
    print(f"Карта: {replay.map_name}")
    print(f"Игроков: {len(replay.players)}")
    print(f"Всего событий: {len(replay.events)}")
    print(f"Трекер-событий: {len(replay.tracker_events)}")
    print(f"FPS клиента: {replay.game_fps}")

    # Создаём словарь для быстрого доступа к игрокам по ID
    players_by_id = {player.pid: player for player in replay.players}

    # Хранилища данных
    unit_info = {}  # unit_id -> {type, owner_name, owner_race, born_frame}
    unit_positions = defaultdict(list)  # unit_id -> list of positions
    unit_deaths = {}  # unit_id -> death_frame
    unit_type_changes = defaultdict(list)  # unit_id -> list of transformations

    # Счётчики
    stats = {'born': 0, 'positions': 0, 'died': 0, 'type_change': 0}

    # Обрабатываем трекер-события (основной источник данных)
    for event in replay.tracker_events:
        # СОБЫТИЕ: рождение юнита
        if event.name == 'UnitBornEvent':
            if event.unit.is_army or event.unit.is_worker:
                stats['born'] += 1

                # Определяем владельца
                owner_name = ''
                owner_race = 'Neutral'

                if hasattr(event, 'unit_controller') and event.unit_controller:
                    # unit_controller — это ID игрока
                    if event.unit_controller.pid in players_by_id:
                        owner_name = players_by_id[event.unit_controller.pid].name
                        owner_race = players_by_id[event.unit_controller.pid].play_race

                unit_info[event.unit_id] = {
                    'type': event.unit_type_name,
                    'owner_name': owner_name,
                    'owner_race': owner_race,
                    'born_frame': event.frame
                }

        # СОБЫТИЕ: позиции юнитов (самое важное!)
        elif event.name == 'UnitPositionsEvent':
            # event.units содержит словарь типа {unit_name [unit_id]: (x, y, z)}
            units_dict = dict(event.units)
            for unit_data, cords in units_dict.items():
                unit_id = unit_data.id
                x = cords[0]
                y = cords[1]
                z = cords[2] if len(cords) > 2 else 0.0

                if unit_id in unit_info.keys():
                    stats['positions'] += len(units_dict)

                    unit_positions[unit_id].append({
                        'frame': event.frame,
                        'time': event.frame / replay.game_fps,
                        'x': float(x),
                        'y': float(y),
                        'z': float(z)
                    })

        # СОБЫТИЕ: смерть юнита
        elif event.name == 'UnitDiedEvent':
            unit = event.unit
            unit_id = unit.id

            if unit.is_army or unit.is_worker:
                unit_deaths[unit_id] = event.frame
                stats['died'] += 1

    print(f"\nСтатистика обработки:")
    print(f"  Рождений юнитов: {stats['born']}")
    print(f"  Событий позиций: {stats['positions']}")
    print(f"  Смертей: {stats['died']}")
    print(f"  Смен типа: {stats['type_change']}")
    print(f"  Уникальных юнитов с треками: {len(unit_positions)}")

    # ========== НОРМАЛИЗАЦИЯ ВРЕМЕНИ И КАДРОВ ==========
    min_time = float('inf')
    min_frame = float('inf')

    # 1. Ищем минимум среди позиций
    for positions in unit_positions.values():
        for pos in positions:
            if pos['time'] < min_time: min_time = pos['time']
            if pos['frame'] < min_frame: min_frame = pos['frame']

    # 2. Ищем минимум среди рождений
    for info in unit_info.values():
        if info['born_frame'] is not None and info['born_frame'] < min_frame:
            min_frame = info['born_frame']
            # Пересчитываем min_time из найденного минимального кадра
            min_time = min_frame / replay.game_fps

    # 3. Ищем минимум среди смертей (на случай, если юнит умер до первой позиции)
    for frame in unit_deaths.values():
        if frame is not None and frame < min_frame:
            min_frame = frame
            min_time = min_frame / replay.game_fps

    print(f"\nАбсолютный минимум: кадр {min_frame} | время {min_time:.2f} сек")

    # 4. Применяем сдвиг ТОЛЬКО если данные начинаются не с нуля
    if min_frame > 0 and min_frame != float('inf'):
        # Сдвигаем позиции
        for positions in unit_positions.values():
            for pos in positions:
                pos['time'] -= min_time
                pos['frame'] -= min_frame

        # Сдвигаем рождения
        for info in unit_info.values():
            if info['born_frame'] is not None:
                info['born_frame'] -= min_frame

        # Сдвигаем смерти
        for uid in unit_deaths:
            if unit_deaths[uid] is not None:
                unit_deaths[uid] -= min_frame

        print(f"  Нормализация завершена (сдвиг: -{min_frame} кадров)")
    else:
        print(f"  Нормализация не требуется (данные уже начинаются с ~0)")

    # ========== НОРМАЛИЗАЦИЯ ПОЗИЦИЙ ==========
    # Находим минимальные и максимальные координаты
    min_x = float('inf')
    max_x = float('-inf')
    min_y = float('inf')
    max_y = float('-inf')

    for positions in unit_positions.values():
        for pos in positions:
            x = pos['x']
            y = pos['y']
            min_x = min(min_x, x)
            max_x = max(max_x, x)
            min_y = min(min_y, y)
            max_y = max(max_y, y)

    # Вычисляем центр карты
    center_x = (min_x + max_x) / 2
    center_y = (min_y + max_y) / 2

    print(f"\nНормализация позиций:")
    print(f"  X диапазон: {min_x:.1f} - {max_x:.1f}, центр: {center_x:.1f}")
    print(f"  Y диапазон: {min_y:.1f} - {max_y:.1f}, центр: {center_y:.1f}")

    # Вычитаем центр из всех координат
    if center_x != 0 or center_y != 0:
        for positions in unit_positions.values():
            for pos in positions:
                pos['x'] -= center_x
                pos['y'] -= center_y

    # Формируем финальный JSON
    result = {
        'metadata': {
            'replay_file': replay_path,
            'version': replay.release_string,
            'duration': f"{replay.length.seconds // 60} minutes {replay.length.seconds % 60} seconds",
            'fps': float(replay.game_fps),
            'map': replay.map_name,
            'players': [
                {
                    'name': p.name,
                    'race': p.play_race,
                    'team': str(p.team.number),
                    'result': p.result,
                    'is_human': p.is_human
                }
                for p in replay.players if not p.is_observer
            ]
        },
        'units': []
    }

    # Убираем юнитов без позиций
    for uid in unit_info:
        if uid not in unit_positions:
            unit_positions[uid] = []  # Явно создаём пустой список

    total_units = len(unit_info)
    units_with_tracks = sum(1 for pos in unit_positions.values() if len(pos) > 0)
    print(f"\nВсего юнитов в памяти: {total_units}")
    print(f"Из них с позициями: {units_with_tracks}")
    print(f"Без позиций (прошли только по рали-поинту): {total_units - units_with_tracks}")

    # Собираем данные по юнитам
    for unit_id, positions in unit_positions.items():
        if unit_id not in unit_info:
            continue

        info = unit_info[unit_id]

        unit_data = {
            'unit_id': unit_id,
            'type': info['type'],
            'owner_name': info['owner_name'],
            'owner_race': info['owner_race'],
            'born_frame': info['born_frame'],
            'died_frame': unit_deaths.get(unit_id),
            'frames': positions
        }

        # Добавляем информацию о смене типа, если есть
        if unit_id in unit_type_changes:
            unit_data['type_changes'] = unit_type_changes[unit_id]

        result['units'].append(unit_data)

    # Сохраняем JSON
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    # Подсчитываем размер
    json_str = json.dumps(result)
    size_kb = len(json_str) / 1024

    print(f"\nСохранено в: {output_path}")
    print(f"Размер JSON: ~{size_kb:.2f} КB")
    print(f"Всего юнитов в JSON: {len(result['units'])}")

    # Считаем общее количество позиций
    total_positions = sum(len(u['frames']) for u in result['units'])
    print(f"Всего позиций: {total_positions}")

    return result


# Использование
if __name__ == "__main__":
    replay_path = input("Введите путь до реплея:\n")
    output_units_path = "replay_units_output.json"
    output_buildings_path = "replay_buildings_output.json"

    parse_replay_to_json(replay_path, output_units_path)
    print("-"*50)
    pb(replay_path, output_buildings_path)