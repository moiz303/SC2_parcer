import sc2reader
import json
from collections import defaultdict


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
            stats['born'] += 1

            # Определяем владельца
            owner_name = 'Neutral'
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
            stats['positions'] += 1

            # event.units содержит словарь типа {unit_name [unit_id]: (x, y, z)}
            units_dict = dict(event.units)
            for unit_data, cords in units_dict.items():
                unit_id = unit_data.id
                x = cords[0]
                y = cords[1]
                z = cords[2] if len(cords) > 2 else 0.0

                if unit_id in unit_info:
                    unit_positions[unit_id].append({
                        'frame': event.frame,
                        'time': event.frame / replay.game_fps,
                        'x': float(x),
                        'y': float(y),
                        'z': float(z)
                    })

        # СОБЫТИЕ: смерть юнита
        elif event.name == 'UnitDiedEvent':
            stats['died'] += 1
            unit_deaths[event.unit_id] = event.frame

    print(f"\nСтатистика обработки:")
    print(f"  Рождений юнитов: {stats['born']}")
    print(f"  Событий позиций: {stats['positions']}")
    print(f"  Смертей: {stats['died']}")
    print(f"  Смен типа: {stats['type_change']}")
    print(f"  Уникальных юнитов с треками: {len(unit_positions)}")

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
                    'team': str(p.team),
                    'result': p.result,
                    'is_human': p.is_human
                }
                for p in replay.players if not p.is_observer
            ]
        },
        'units': []
    }

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
    replay_path = input("Введите путь до репея:\n")
    output_path = "replay_output.json"

    parse_replay_to_json(replay_path, output_path)