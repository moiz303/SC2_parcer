import sc2reader
from collections import defaultdict
import math
import json


def parse_replay_to_json(replay_path, output_units_path):
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
    print(f"Game-событий: {len(replay.game_events)}")
    print(f"FPS клиента: {replay.game_fps}")

    players_by_id = {player.pid: player for player in replay.players}

    unit_info = {}
    unit_positions = defaultdict(list)
    unit_deaths = {}
    stats = {'born': 0, 'positions': 0, 'died': 0}

    # Состояние для симуляции движения
    unit_state = {}  # unit_id -> {'pos': (x,y), 'dest': (x,y), 'speed': float, 'is_rally': bool, 'last_frame': int, 'owner_pid': int}
    player_rally = {}  # player_pid -> {'x': float, 'y': float, 'frame': int}

    # Базовые скорости (game units/sec). Можно расширить или подгружать из game_data
    UNIT_SPEEDS = {
        'Overlord': 0.9, 'Lifted Buildings': 1.31, 'Queen': 1.31, 'Spine Crawler': 1.4,
        'Spore Crawler': 1.4, 'Brood Lord': 1.97, 'Battlecruiser': 2.62, 'Carrier': 2.62,
        'High Templar': 2.62, 'Locust': 2.62, 'Mothership': 2.62, 'Observer': 2.62,
        'Overseer': 2.62, 'Thor': 2.62, 'Changeling (Undisguised)': 3.15, 'Colossus': 3.15,
        'Disruptor': 3.15, 'Hellbat': 3.15, 'Hydralisk': 3.15, 'Immortal': 3.15,
        'Infestor': 3.15, 'Marauder': 3.15, 'Marine': 3.15, 'Roach': 3.15,
        'Sentry': 3.15, 'Siege Tank': 3.15, 'Swarm Host': 3.15, 'Tempest': 3.15,
        'Viking (Assualt Mode)': 3.15, 'Zealot': 3.15, 'Adept': 3.5, 'Baneling': 3.5,
        'Medivac': 3.5, 'Banshee': 3.85, 'Ravager': 3.85, 'Viking (Fighter Mode)': 3.85,
        'Void Ray': 3.85, 'Archon': 3.94, 'Dark Templar': 3.94, 'Drone': 3.94,
        'Ghost': 3.94, 'MULE': 3.94, 'Probe': 3.94, 'SCV': 3.94,
        'Widow Mine': 3.94, 'Lurker': 4.13, 'Raven': 4.13, 'Stalker': 4.13,
        'Ultralisk': 4.13, 'Viper': 4.13, 'Warp Prism': 4.13, 'Zergling': 4.13,
        'Corruptor': 4.72, 'Cyclone': 4.72, 'Liberator': 4.72, 'Reaper': 5.25,
        'Broodling': 5.37, 'Mutalisk': 5.6, 'Oracle': 5.6, 'Shade (Adept)': 5.6,
        'Hellion': 5.95, 'Phoenix': 5.95, 'Purification Nova (Disruptor)': 5.95, 'Interceptor': 10.5
    }

    def get_speed(unit_type_name):
        return UNIT_SPEEDS.get(unit_type_name, 3.15)

    def interpolate_positions(uid, state, final_frame=None):
        """Добавляет промежуточные точки между рождением, командами и смертью."""
        if final_frame is None:
            final_frame = state['last_frame']

        dt_frames = final_frame - state['last_frame']
        if dt_frames <= 0:
            return

        time_sec = dt_frames / replay.game_fps
        dx = state['dest'][0] - state['pos'][0]
        dy = state['dest'][1] - state['pos'][1]
        dist = math.hypot(dx, dy)
        travel = state['speed'] * time_sec

        new_pos = state['dest'] if travel >= dist else (
            state['pos'][0] + dx * (travel / dist),
            state['pos'][1] + dy * (travel / dist)
        )

        state['pos'] = new_pos
        state['last_frame'] = final_frame
        unit_positions[uid].append({
            'frame': final_frame,
            'time': final_frame / replay.game_fps,
            'x': round(new_pos[0], 2),
            'y': round(new_pos[1], 2),
            'z': 0.0
        })

    # Объединяем трекер и game события в хронологическом порядке
    all_events = sorted(list(replay.tracker_events) + list(replay.game_events), key=lambda e: e.frame)

    for event in all_events:
        if event.name == 'UnitBornEvent':
            if event.unit.is_army or event.unit.is_worker:
                stats['born'] += 1
                uid = event.unit_id
                pid = event.unit_controller.pid
                owner = players_by_id.get(pid)
                owner_name = owner.name if owner else f"PID_{pid}"
                owner_race = owner.play_race if owner else "Unknown"

                # 1. Пробуем взять последний ралли игрока
                if pid in player_rally:
                    rally_dest = {'x': float(player_rally[pid]['x']), 'y': float(player_rally[pid]['y'])}
                # 2. Фоллбэк: точка рождения (расстояние = 0, юнит будет стоять на месте)
                else:
                    rally_dest = {'x': float(event.x), 'y': float(event.y), 'z': 0.0}

                unit_info[uid] = {
                    'type': event.unit_type_name,
                    'owner_name': owner_name,
                    'owner_race': owner_race,
                    'born_frame': event.frame,
                    'rally_dest': rally_dest  # <-- ВСЕГДА присутствует
                }

                pos = (event.x, event.y)
                dest = pos
                is_rally = False

                # Наследуем последний известный rally-point игрока
                if pid in player_rally:
                    dest = (player_rally[pid]['x'], player_rally[pid]['y'])
                    is_rally = True

                unit_state[uid] = {
                    'pos': pos, 'dest': dest, 'speed': get_speed(event.unit_type_name),
                    'is_rally': is_rally, 'last_frame': event.frame, 'owner_pid': pid
                }
                unit_positions[uid].append(
                    {'frame': event.frame, 'time': event.frame / replay.game_fps, 'x': round(pos[0], 2),
                     'y': round(pos[1], 2), 'z': 0.0})

        elif event.name == 'UnitPositionsEvent':
            for unit_data, cords in event.units.items():
                uid = unit_data.id
                if uid in unit_info:
                    stats['positions'] += 1
                    x, y = cords[0], cords[1]
                    z = cords[2] if len(cords) > 2 else 0.0
                    unit_positions[uid].append({
                        'frame': event.frame, 'time': event.frame / replay.game_fps,
                        'x': float(x), 'y': float(y), 'z': float(z)
                    })

        elif event.name == 'UnitDiedEvent':
            unit = event.unit
            if unit.is_army or unit.is_worker:
                uid = unit.id
                unit_deaths[uid] = event.frame
                stats['died'] += 1

                if uid in unit_state:
                    # Фиксируем позицию смерти (если трекер отдал координаты)
                    death_pos = (event.x, event.y) if hasattr(event, 'x') and event.x is not None else unit_state[uid][
                        'pos']
                    unit_state[uid]['pos'] = death_pos
                    unit_positions[uid].append({
                        'frame': event.frame, 'time': event.frame / replay.game_fps,
                        'x': round(death_pos[0], 2), 'y': round(death_pos[1], 2), 'z': 0.0
                    })
                    del unit_state[uid]

        # Обработка команд и Rally из game_events
        elif event.name in ('TargetPointEvent', 'TargetUnitEvent', 'AbilityEvent'):
            # 1. Установка Rally-Point
            is_rally = False
            if hasattr(event, 'ability') and event.ability and 'Rally' in event.ability.name:
                is_rally = True

            if is_rally and event.name == 'TargetPointEvent':
                pid = getattr(event.unit_controller, 'pid', None) or getattr(event, 'player', None) and event.player.pid
                if pid:
                    player_rally[pid] = {'x': event.target_x, 'y': event.target_y, 'frame': event.frame}
                    # Мгновенно меняем цель всем юнитам этого игрока, которые ещё не получили прямых команд
                    for uid, state in unit_state.items():
                        if state['owner_pid'] == pid and state['is_rally']:
                            state['dest'] = (event.target_x, event.target_y)
                continue

            # 2. Прямая команда юнитам (move, attack, patrol и т.д.)
            selected_units = getattr(event, 'units', [])
            if not selected_units and hasattr(event, 'unit'):
                selected_units = [event.unit]

            for u in selected_units:
                uid = getattr(u, 'id', None)
                if uid and uid in unit_state:
                    state = unit_state[uid]
                    # Интерполируем позицию до момента команды
                    interpolate_positions(uid, state, event.frame)

                    state['is_rally'] = False  # Юнит получил прямой приказ
                    state['last_frame'] = event.frame

                    if event.name == 'TargetPointEvent':
                        state['dest'] = (event.target_x, event.target_y)
                    elif event.name == 'TargetUnitEvent' and hasattr(event, 'target'):
                        state['dest'] = (event.target.x, event.target.y)

                    # Собираем финальную информацию по юниту
                    unit_positions[uid].append({
                        'frame': event.frame, 'time': event.frame / replay.game_fps,
                        'x': round(state['pos'][0], 2), 'y': round(state['pos'][1], 2), 'z': 0.0
                    })

    # Финализация: достраиваем пути для живых юнитов до конца реплея
    if all_events:
        final_frame = all_events[-1].frame
        for uid, state in list(unit_state.items()):
            interpolate_positions(uid, state, final_frame)
            del unit_state[uid]

    # ========== НОРМАЛИЗАЦИЯ ПОЗИЦИЙ (ЕДИНЫЙ ЦЕНТР ДЛЯ ВСЕХ ОБЪЕКТОВ) ==========
    def normalize_all_positions(unit_positions, unit_info=None, other_positions=None,
                                flip_x=False, flip_y=False):
        """Центрирует координаты и опционально отражает оси для синхронизации с картой."""
        min_x, max_x = float('inf'), float('-inf')
        min_y, max_y = float('inf'), float('-inf')

        # Собираем глобальный диапазон
        all_pos = [unit_positions]
        if other_positions:
            all_pos.append(other_positions)

        for pos_dict in all_pos:
            for positions in pos_dict.values():
                for pos in positions:
                    min_x = min(min_x, pos['x'])
                    max_x = max(max_x, pos['x'])
                    min_y = min(min_y, pos['y'])
                    max_y = max(max_y, pos['y'])

        if min_x == float('inf'):
            print("⚠️ Позиции не найдены. Пропускаю нормализацию.")
            return 0.0, 0.0

        center_x = (min_x + max_x) / 2
        center_y = (min_y + max_y) / 2

        print(f"\n🌍 Нормализация + отражение осей:")
        print(f"  Центр: X={center_x:.1f}, Y={center_y:.1f}")
        print(f"  Отражение: X={'Да' if flip_x else 'Нет'}, Y={'Да' if flip_y else 'Нет'}")

        # Применяем центрирование + отражение
        def transform_coord(x, y):
            x = x - center_x
            y = y - center_y
            if flip_x: x = -x
            if flip_y: y = -y
            return x, y

        for pos_dict in all_pos:
            for positions in pos_dict.values():
                for pos in positions:
                    pos['x'], pos['y'] = transform_coord(pos['x'], pos['y'])

        # Трансформируем rally_dest тем же оффсетом и отражением
        if unit_info:
            for info in unit_info.values():
                rd = info.get('rally_dest')
                if rd and isinstance(rd, list) and len(rd) >= 2:
                    rd[0] -= center_x
                    rd[1] -= center_y
                    if flip_x: rd[0] = -rd[0]
                    if flip_y: rd[1] = -rd[1]

        return center_x, center_y

    cx, cy = normalize_all_positions(
        unit_positions,
        unit_info=unit_info,
        flip_x=False,  # ← Включите, если юниты зеркальны по X
        flip_y=False  # ← Включите, если юниты зеркальны по Y
    )

    # Собираем итоговую структуру
    output_data = {
        'units': [
            {
                'unit_id': uid,
                'type': unit_info.get(uid)['type'],
                'owner_name': unit_info.get(uid)['owner_name'],
                'owner_race': unit_info.get(uid)['owner_race'],
                'positions': unit_positions.get(uid, []),
                'rally_dest': unit_info.get(uid)['rally_dest'],
                'born_frame': unit_info.get(uid)['born_frame'],
                'died_frame': unit_deaths.get(uid)
             }
            for uid in set(list(unit_info.keys()) + list(unit_deaths.keys()))
        ]
    }

    with open(output_units_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    print(f"✅ Парсинг завершен. Записано {len(output_data['units'])} юнитов в {output_units_path}")


if __name__ == "__main__":
    replay_path = input("Введите путь до реплея:\n")
    output_rally_path = "replay_rally_output.json"

    parse_replay_to_json(replay_path, output_rally_path)