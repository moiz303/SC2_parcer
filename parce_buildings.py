import sc2reader
import json
from collections import defaultdict


def parse_replay_buildings_to_json(replay_path, output_path):
    """
    Парсит строения из UnitInitEvent (основной источник для зданий)
    """
    print(f"Загрузка реплея: {replay_path}")

    replay = sc2reader.load_replay(
        replay_path,
        load_level=4,
        use_english_names=True
    )

    print(f"Версия: {replay.release_string}")
    print(f"Карта: {replay.map_name}")
    print(f"Игроков: {len(replay.players)}")
    print(f"FPS: {replay.game_fps}")

    players_by_id = {player.pid: player for player in replay.players}

    # Хранилища данных
    building_info = {}  # unit_id -> {type, owner_name, owner_race, init_frame}
    building_positions = defaultdict(list)  # unit_id -> list of positions
    building_deaths = {}  # unit_id -> death_frame
    building_upgrades = defaultdict(list)  # unit_id -> upgrades (например, Lair -> Hive)

    stats = {'init': 0, 'building': 0, 'positions': 0, 'died': 0, 'upgrade': 0}

    for event in replay.tracker_events:
        # ОСНОВНОЙ ИСТОЧНИК: инициализация объектов (здания здесь!)
        if (event.name == 'UnitInitEvent') or ((event.name == 'UnitBornEvent') and event.unit.is_building):
            stats['init'] += 1

            # Определяем владельца
            owner_name = ''
            owner_race = 'Neutral'

            if hasattr(event, 'unit_controller') and event.unit_controller:
                if hasattr(event.unit_controller, 'pid') and event.unit_controller.pid in players_by_id:
                    owner_name = players_by_id[event.unit_controller.pid].name
                    owner_race = players_by_id[event.unit_controller.pid].play_race
            elif hasattr(event, 'player') and event.player:
                owner_name = event.player.name
                owner_race = event.player.play_race if hasattr(event.player, 'play_race') else event.player.race

            building_info[event.unit_id] = {
                'type': event.unit_type_name,
                'owner_name': owner_name,
                'owner_race': owner_race,
                'init_frame': event.frame
            }

            # Сохраняем позицию, если есть
            if hasattr(event, 'x') and hasattr(event, 'y'):
                building_positions[event.unit_id].append({
                    'frame': event.frame,
                    'time': event.frame / replay.game_fps,
                    'x': float(event.x),
                    'y': float(event.y),
                    'z': float(getattr(event, 'z', 0.0))
                })

        # СМЕНА ТИПА (эволюция зданий: Lair -> Hive, Gateway -> WarpGate)
        elif event.name == 'UnitTypeChangeEvent':
            if event.unit_id in building_info:
                stats['upgrade'] += 1
                old_type = building_info[event.unit_id]['type']
                new_type = event.unit_type_name

                building_upgrades[event.unit_id].append({
                    'frame': event.frame,
                    'time': event.frame / replay.game_fps,
                    'from_type': old_type,
                    'to_type': new_type
                })

                # Обновляем текущий тип здания
                building_info[event.unit_id]['type'] = new_type

                # Сохраняем позицию при трансформации
                if hasattr(event, 'x') and hasattr(event, 'y'):
                    building_positions[event.unit_id].append({
                        'frame': event.frame,
                        'time': event.frame / replay.game_fps,
                        'x': float(event.x),
                        'y': float(event.y),
                        'z': float(getattr(event, 'z', 0.0))
                    })

        # ПОЗИЦИИ (обновление позиций зданий)
        elif event.name == 'UnitPositionsEvent':
            units_dict = dict(event.units)

            for unit_data, cords in units_dict.items():
                unit_id = unit_data.id
                x = cords[0]
                y = cords[1]
                z = cords[2] if len(cords) > 2 else 0.0

                if unit_id in building_info.keys():
                    stats['positions'] += len(units_dict)

                    building_positions[unit_id].append({
                        'frame': event.frame,
                        'time': event.frame / replay.game_fps,
                        'x': float(x),
                        'y': float(y),
                        'z': float(z)
                    })

        # СМЕРТЬ/УНИЧТОЖЕНИЕ
        elif event.name == 'UnitDiedEvent':
            unit_id = event.unit.id

            if event.unit.is_building:
                building_deaths[unit_id] = event.frame
                stats['died'] += 1

    print(f"\nСтатистика обработки:")
    print(f"  UnitInitEvent всего: {stats['init']}")
    print(f"  Смен типа (эволюций): {stats['upgrade']}")
    print(f"  Событий позиций: {stats['positions']}")
    print(f"  Уничтожений: {stats['died']}")
    print(f"  Уникальных строений с треками: {len(building_positions)}")

    # ========== НОРМАЛИЗАЦИЯ ВРЕМЕНИ И КАДРОВ ==========
    min_time = float('inf')
    min_frame = float('inf')

    # 1. Ищем минимум среди позиций
    for positions in building_positions.values():
        for pos in positions:
            if pos['time'] < min_time: min_time = pos['time']
            if pos['frame'] < min_frame: min_frame = pos['frame']

    # 2. Ищем минимум среди рождений
    for info in building_info.values():
        if info['init_frame'] is not None and info['init_frame'] < min_frame:
            min_frame = info['init_frame']
            # Пересчитываем min_time из найденного минимального кадра
            min_time = min_frame / replay.game_fps

    # 3. Ищем минимум среди смертей (на случай, если юнит умер до первой позиции)
    for frame in building_deaths.values():
        if frame is not None and frame < min_frame:
            min_frame = frame
            min_time = min_frame / replay.game_fps

    print(f"\nАбсолютный минимум: кадр {min_frame} | время {min_time:.2f} сек")

    # 4. Применяем сдвиг ТОЛЬКО если данные начинаются не с нуля
    if min_frame > 0 and min_frame != float('inf'):
        # Сдвигаем позиции
        for positions in building_positions.values():
            for pos in positions:
                pos['time'] -= min_time
                pos['frame'] -= min_frame

        # Сдвигаем рождения
        for info in building_info.values():
            if info['init_frame'] is not None:
                info['init_frame'] -= min_frame

        # Сдвигаем смерти
        for uid in building_deaths:
            if building_deaths[uid] is not None:
                building_deaths[uid] -= min_frame

        print(f"  Нормализация завершена (сдвиг: -{min_frame} кадров)")
    else:
        print(f"  Нормализация не требуется (данные уже начинаются с ~0)")

    # ========== НОРМАЛИЗАЦИЯ ПОЗИЦИЙ ==========
    min_x = float('inf')
    max_x = float('-inf')
    min_y = float('inf')
    max_y = float('-inf')

    for positions in building_positions.values():
        for pos in positions:
            x = pos['x']
            y = pos['y']
            if x < min_x: min_x = x
            if x > max_x: max_x = x
            if y < min_y: min_y = y
            if y > max_y: max_y = y

    center_x = (min_x + max_x) / 2 if min_x != float('inf') else 0
    center_y = (min_y + max_y) / 2 if min_y != float('inf') else 0

    print(f"\nНормализация позиций:")
    print(f"  X диапазон: {min_x:.1f} - {max_x:.1f}, центр: {center_x:.1f}")
    print(f"  Y диапазон: {min_y:.1f} - {max_y:.1f}, центр: {center_y:.1f}")

    if center_x != 0 or center_y != 0:
        print(f"  Сдвиг: X на {-center_x:.1f}, Y на {-center_y:.1f}")
        for positions in building_positions.values():
            for pos in positions:
                pos['x'] -= center_x
                pos['y'] -= center_y

    # Выводим найденные типы зданий
    found_building_types = set()
    for info in building_info.values():
        found_building_types.add(info['type'])

    if found_building_types:
        print(f"\nНайденные типы зданий:")
        for bt in sorted(found_building_types):
            print(f"  {bt}")
    else:
        print("\nВНИМАНИЕ: Здания не найдены! Проверьте список non_buildings.")

    # Если нет строений — выходим с пустым JSON
    if not building_info:
        result = {
            'metadata': {
                'replay_file': replay_path,
                'version': replay.release_string,
                'duration': f"{replay.length.seconds // 60} minutes {replay.length.seconds % 60} seconds",
                'fps': float(replay.game_fps),
                'map': replay.map_name,
                'players': []
            },
            'buildings': []
        }

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        print(f"\nСохранён пустой JSON в: {output_path}")
        return result

    # Формируем JSON
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
                    'team': str(p.team),
                    'result': p.result,
                    'is_human': p.is_human
                }
                for p in replay.players if not p.is_observer
            ]
        },
        'buildings': []
    }

    # Убираем строения без позиций
    for uid in building_info:
        if uid not in building_positions:
            building_positions[uid] = []  # Явно создаём пустой список

    for unit_id, positions in building_positions.items():
        if unit_id not in building_info:
            continue

        info = building_info[unit_id]

        building_data = {
            'building_id': unit_id,
            'type': info['type'],
            'owner_name': info['owner_name'],
            'owner_race': info['owner_race'],
            'init_frame': info['init_frame'],
            'died_frame': building_deaths.get(unit_id),
            'frames': positions
        }

        if unit_id in building_upgrades and building_upgrades[unit_id]:
            building_data['upgrades'] = building_upgrades[unit_id]

        result['buildings'].append(building_data)

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"\nСохранено в: {output_path}")
    print(f"Всего строений в JSON: {len(result['buildings'])}")

    total_positions = sum(len(b['frames']) for b in result['buildings'])
    print(f"Всего позиций: {total_positions}")

    return result


if __name__ == "__main__":
    replay_path = input("Введите путь до реплея:\n")
    output_path = "replay_buildings_output.json"

    parse_replay_buildings_to_json(replay_path, output_path)