import json
import logging
import math
import statistics
from pathlib import Path
from collections import defaultdict
from typing import List, Tuple, Optional, Dict, Any, Union

logger = logging.getLogger(__name__)


def load_replay(filepath: Path) -> dict:
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)


def extract_combat_deaths(data: dict) -> List[Dict[str, Any]]:
    deaths = []
    for building in data.get('buildings', []):
        died_frame = building.get('died_frame')
        if died_frame is None or building.get('owner_race') == 'Neutral':
            continue
        frames = building.get('frames')
        if not frames:
            continue
        last_pos = frames[-1]
        deaths.append({
            'frame': died_frame,
            'x': last_pos['x'],
            'y': last_pos['y'],
            'init_frame': building.get('init_frame')
        })

    for unit in data.get('units', []):
        died_frame = unit.get('died_frame')
        if died_frame is None or unit.get('owner_race') == 'Neutral' or not unit.get('is_army', False):
            continue
        positions = unit.get('positions')
        if not positions:
            continue
        last_pos = positions[-1]
        deaths.append({
            'frame': died_frame,
            'x': last_pos['x'],
            'y': last_pos['y'],
            'init_frame': unit.get('born_frame') or unit.get('init_frame')
        })
    return deaths


def clean_spatial_noise(deaths: List[Dict[str, Any]], radius: float = 15.0) -> List[Dict[str, Any]]:
    if len(deaths) < 5:
        return deaths

    grid = defaultdict(list)
    for d in deaths:
        grid[(int(d['x'] // radius), int(d['y'] // radius))].append(d)

    filtered_deaths = []
    for (cx, cy), points in grid.items():
        neighbor_points = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                neighbor_points.extend(grid.get((cx + dx, cy + dy), []))

        for p1 in points:
            neighbors_count = sum(
                1 for p2 in neighbor_points
                if math.hypot(p1['x'] - p2['x'], p1['y'] - p2['y']) <= radius
            )
            if neighbors_count >= 3:
                filtered_deaths.append(p1)

    return filtered_deaths if filtered_deaths else deaths


def calculate_battle_center(battle_segment: List[Dict[str, Any]]) -> Tuple[float, float]:
    """Вычисляет геометрический центр сражения"""
    if not battle_segment:
        return 0.0, 0.0

    xs = [d['x'] for d in battle_segment]
    ys = [d['y'] for d in battle_segment]

    return statistics.median(xs), statistics.median(ys)


def get_battle_interval(data: dict, window_seconds: float = 30.0) -> Tuple[
    Optional[int], Optional[int], Optional[Tuple[float, float]], str]:
    fps = 30
    deaths = extract_combat_deaths(data)
    if not deaths:
        return None, None, None, "В реплее нет смертей боевых юнитов."

    deaths = clean_spatial_noise(deaths, radius=20.0)
    deaths.sort(key=lambda x: x['frame'])

    window_frames = int(window_seconds * fps)
    max_deaths_in_window = 0
    best_left_idx = 0
    best_right_idx = 0
    left = 0

    for right in range(len(deaths)):
        while deaths[right]['frame'] - deaths[left]['frame'] > window_frames:
            left += 1
        current_deaths = right - left + 1
        if current_deaths > max_deaths_in_window:
            max_deaths_in_window = current_deaths
            best_left_idx = left
            best_right_idx = right

    battle_segment = deaths[best_left_idx:best_right_idx + 1]
    if not battle_segment:
        return None, None, None, "Не удалось локализовать интервал."

    start_frame = battle_segment[0]['frame'] - 100
    end_frame = battle_segment[-1]['frame'] + 100

    center_x, center_y = calculate_battle_center(battle_segment)

    birth_frames = [d['init_frame'] for d in battle_segment if d['init_frame'] is not None]
    if birth_frames:
        earliest_birth = min(birth_frames)
        max_lookback = int(30 * fps)
        if start_frame - earliest_birth <= max_lookback:
            start_frame = max(earliest_birth, start_frame - max_lookback)

    description = f"Уничтожено {max_deaths_in_window} единиц за {window_seconds} сек."
    return start_frame, end_frame, (center_x, center_y), description


def analyze_replay_file(filepath: Union[str, Path], window_seconds: float = 30.0) -> Dict[str, Any]:
    """Интерфейсная функция для бэкенда. Возвращает структурированный Python-словарь."""
    try:
        path = Path(filepath)
        data = load_replay(path)

        start, end, center, desc = get_battle_interval(data, window_seconds=window_seconds)

        if start is not None and end is not None:
            duration_frames = end - start
            success = True
            center_x, center_y = center
        else:
            duration_frames = None
            success = False
            center_x, center_y = None, None

        return {
            "success": success,
            "start_frame": start,
            "end_frame": end,
            "duration_frames": duration_frames,
            "center_x": center_x,
            "center_y": center_y,
            "error": None
        }
    except Exception as e:
        logger.error(f"Ошибка при обработке реплея {filepath}: {e}", exc_info=True)
        return {
            "success": False,
            "start_frame": None,
            "end_frame": None,
            "duration_frames": None,
            "center_x": None,
            "center_y": None,
            "error": str(e)
        }