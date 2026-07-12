import sc2reader
import json
import logging
import math
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict

from ui_processing import ui_progress


"""LOG_FILE = Path(__file__).resolve().parent / "parce_replay.log"
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
"""

@dataclass
class Position:
    """Позиция в кадре"""
    frame: int
    time: float
    x: float
    y: float
    z: float = 0.0


@dataclass
class BuildingTransform:
    """Трансформация здания (эволюция)"""
    frame: int
    time: float
    from_type: str
    to_type: str


@dataclass
class BaseEntity:
    """Базовая сущность (общая для зданий и юнитов)"""
    entity_id: int
    entity_type: str
    owner_name: str
    owner_race: str
    init_frame: int
    died_frame: Optional[int] = None

    def to_dict(self) -> dict:
        """Конвертация в словарь для JSON"""
        result = {
            'entity_id': self.entity_id,
            'type': self.entity_type,
            'owner_name': self.owner_name,
            'owner_race': self.owner_race,
            'init_frame': self.init_frame,
            'died_frame': self.died_frame
        }
        return result


@dataclass
class Building(BaseEntity):
    """Специфичная для здания сущность"""
    frames: List[Position] = None
    transforms: List[BuildingTransform] = None

    def __post_init__(self):
        if self.frames is None:
            self.frames = []
        if self.transforms is None:
            self.transforms = []

    def to_dict(self) -> dict:
        result = super().to_dict()
        result['frames'] = [asdict(pos) for pos in self.frames]
        if self.transforms:
            result['transforms'] = [asdict(trans) for trans in self.transforms]
        return result


@dataclass
class Unit(BaseEntity):
    """Специфичная для юнита сущность"""
    positions: List[Position] = None
    is_army: bool = False

    def __post_init__(self):
        if self.positions is None:
            self.positions = []

    def to_dict(self) -> dict:
        result = super().to_dict()
        result['positions'] = [asdict(pos) for pos in self.positions]
        result['is_army'] = self.is_army
        return result


class UnifiedReplayParser:
    """
    Унифицированный парсер реплеев SC2, объединяющий логику для зданий и юнитов
    """

    def __init__(self):
        self.replay = None
        self.players_by_id = {}
        self.buildings: Dict[int, Building] = {}
        self.units: Dict[int, Unit] = {}

        self._building_transforms: Dict[int, List[BuildingTransform]] = defaultdict(list)
        self._building_positions: Dict[int, List[Position]] = defaultdict(list)
        self._unit_positions: Dict[int, List[Position]] = defaultdict(list)
        self._building_deaths: Dict[int, int] = {}
        self._unit_deaths: Dict[int, int] = {}
        self._unit_last_state: Dict[int, Tuple[Tuple[float, float], int]] = {}

        logging.info("Парсинг реплея...")
        ui_progress("parse_replay", 0, "Начинаю парсинг реплея...")

    def parse_replay(self, replay_path: str, output_path: str = None) -> Dict[str, Any]:
        """Основной метод парсинга реплея"""

        self.replay = sc2reader.load_replay(
            replay_path,
            load_level=4,
            use_english_names=True
        )

        logging.info(f"📊 Версия: {self.replay.release_string}")
        logging.info(f"🗺️ Карта: {self.replay.map_name}")
        logging.info(f"👥 Игроков: {len(self.replay.players)}")
        ui_progress("parse_replay", 10, "Сырые данные загружены. Приступаю к предобработке...")

        self.players_by_id = {player.pid: player for player in self.replay.players}
        self._parse_events()
        ui_progress("parse_replay", 30, "Предобработка завершена. Начинаю распределение позиций зданий...")

        self._finalize_buildings()
        ui_progress("parse_replay", 50, "Распределение зданий завершено. Обрабатываю данные армий...")
        self._finalize_units()
        ui_progress("parse_replay", 70, "Армии обработаны. Приступаю к центровке карты...")

        self._normalize_all_positions()
        ui_progress("parse_replay", 85, "Карта отцентрована. Сборка финального результата...")
        result = self._build_result(replay_path)
        ui_progress("parse_replay", 95,  "Результат собран. Сохранение в кэш...")

        if output_path:
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(result, f, indent=2, ensure_ascii=False)
            logging.info(f"\n💾 Сохранено в: {output_path}")
            ui_progress("parse_replay", 100, "ГОТОВО")
        return result

    def _parse_events(self):
        """Парсинг всех событий реплея"""
        stats = {
            'init_buildings': 0,
            'init_units': 0,
            'neutral_buildings': 0,
            'transforms': 0,
            'positions': 0,
            'deaths': 0
        }

        all_events = sorted(
            list(self.replay.tracker_events) + list(self.replay.game_events),
            key=lambda e: e.frame
        )

        for event in all_events:
            # 1. Рождение/инициализация объектов
            if event.name in ['UnitInitEvent', 'UnitBornEvent']:
                self._handle_init_event(event, stats)

            # 2. Смена типа (трансформация зданий)
            elif event.name == 'UnitTypeChangeEvent':
                self._handle_type_change(event, stats)

            # 3. Обновление позиций
            elif event.name == 'UnitPositionsEvent':
                self._handle_positions_event(event, stats)

            # 4. Смерть/уничтожение
            elif event.name == 'UnitDiedEvent':
                self._handle_death_event(event, stats)

        self._print_stats(stats)

    def _handle_init_event(self, event, stats):
        """Обработка инициализации зданий и юнитов"""
        owner_name = ''
        owner_race = 'Neutral'

        has_controller = False
        if hasattr(event, 'unit_controller') and event.unit_controller:
            has_controller = True
            if hasattr(event.unit_controller, 'pid') and event.unit_controller.pid in self.players_by_id:
                owner_name = self.players_by_id[event.unit_controller.pid].name
                owner_race = self.players_by_id[event.unit_controller.pid].play_race
        elif hasattr(event, 'player') and event.player:
            has_controller = True
            owner_name = event.player.name
            owner_race = event.player.play_race if hasattr(event.player, 'play_race') else event.player.race

        is_building = False
        is_unit = False
        is_neutral_building = False

        if hasattr(event, 'unit'):
            if hasattr(event.unit, 'is_building'):
                is_building = event.unit.is_building
            if hasattr(event.unit, 'is_army') or hasattr(event.unit, 'is_worker'):
                is_unit = (event.unit.is_army or event.unit.is_worker) if hasattr(event.unit, 'is_army') else False

        if not has_controller and event.name == 'UnitBornEvent':
            is_neutral_building = True
            is_building = True
            owner_name = 'None'
            owner_race = 'Neutral'
            stats['neutral_buildings'] += 1

        if is_building or is_neutral_building:
            stats['init_buildings'] += 1
            building = Building(
                entity_id=event.unit_id,
                entity_type=event.unit_type_name,
                owner_name=owner_name,
                owner_race=owner_race,
                init_frame=event.frame,
            )
            self.buildings[event.unit_id] = building

            if hasattr(event, 'x') and hasattr(event, 'y'):
                self._building_positions[event.unit_id].append(Position(
                    frame=event.frame,
                    time=event.frame / self.replay.game_fps,
                    x=float(event.x),
                    y=float(event.y),
                    z=float(getattr(event, 'z', 0.0))
                ))

        elif is_unit:
            stats['init_units'] += 1
            unit = Unit(
                entity_id=event.unit_id,
                entity_type=event.unit_type_name,
                owner_name=owner_name,
                owner_race=owner_race,
                init_frame=event.frame,
                is_army=event.unit.is_army if hasattr(event.unit, 'is_army') else False
            )
            self.units[event.unit_id] = unit

            if hasattr(event, 'x') and hasattr(event, 'y'):
                pos = Position(
                    frame=event.frame,
                    time=event.frame / self.replay.game_fps,
                    x=float(event.x),
                    y=float(event.y),
                    z=float(getattr(event, 'z', 0.0))
                )
                self._unit_positions[event.unit_id].append(pos)
                self._unit_last_state[event.unit_id] = ((pos.x, pos.y), event.frame)

    def _handle_type_change(self, event, stats):
        """Обработка трансформации зданий (Lair->Hive, Gateway->WarpGate)"""
        if event.unit_id in self.buildings:
            stats['transforms'] += 1
            old_type = self.buildings[event.unit_id].entity_type
            new_type = event.unit_type_name

            transform = BuildingTransform(
                frame=event.frame,
                time=event.frame / self.replay.game_fps,
                from_type=old_type,
                to_type=new_type
            )
            self._building_transforms[event.unit_id].append(transform)
            self.buildings[event.unit_id].entity_type = new_type

            if hasattr(event, 'x') and hasattr(event, 'y'):
                self._building_positions[event.unit_id].append(Position(
                    frame=event.frame,
                    time=event.frame / self.replay.game_fps,
                    x=float(event.x),
                    y=float(event.y),
                    z=float(getattr(event, 'z', 0.0))
                ))

    def _handle_positions_event(self, event, stats):
        """Обработка обновления позиций"""
        units_dict = dict(event.units)
        stats['positions'] += len(units_dict)

        for unit_data, cords in units_dict.items():
            unit_id = unit_data.id if hasattr(unit_data, 'id') else unit_data
            x = float(cords[0])
            y = float(cords[1])
            z = float(cords[2]) if len(cords) > 2 else 0.0

            if unit_id in self.buildings:
                self._building_positions[unit_id].append(Position(
                    frame=event.frame,
                    time=event.frame / self.replay.game_fps,
                    x=x, y=y, z=z
                ))

            elif unit_id in self.units:
                last_state = self._unit_last_state.get(unit_id)
                if not last_state:
                    continue

                last_pos, last_frame = last_state
                dt_frames = event.frame - last_frame

                if dt_frames <= 0:
                    continue

                dist = math.hypot(x - last_pos[0], y - last_pos[1])
                if dist < 0.05 and dt_frames / self.replay.game_fps < 0.5:
                    self._unit_last_state[unit_id] = ((x, y), event.frame)
                    continue

                pos = Position(
                    frame=event.frame,
                    time=event.frame / self.replay.game_fps,
                    x=x, y=y, z=z
                )
                self._unit_positions[unit_id].append(pos)
                self._unit_last_state[unit_id] = ((x, y), event.frame)

    def _handle_death_event(self, event, stats):
        """Обработка смерти/уничтожения"""
        unit = event.unit
        unit_id = unit.id

        if unit.is_building and unit_id in self.buildings:
            self._building_deaths[unit_id] = event.frame
            stats['deaths'] += 1

            last_state = self._unit_last_state.get(unit_id)
            death_x = float(event.x) if hasattr(event, 'x') and event.x is not None else (
                last_state[0][0] if last_state else 0)
            death_y = float(event.y) if hasattr(event, 'y') and event.y is not None else (
                last_state[0][1] if last_state else 0)

            self._building_positions[unit_id].append(Position(
                frame=event.frame,
                time=event.frame / self.replay.game_fps,
                x=death_x, y=death_y, z=0.0
            ))

        elif (unit.is_army or unit.is_worker) and unit_id in self.units:
            self._unit_deaths[unit_id] = event.frame
            stats['deaths'] += 1

            last_state = self._unit_last_state.get(unit_id)
            death_x = float(event.x) if hasattr(event, 'x') and event.x is not None else (
                last_state[0][0] if last_state else 0)
            death_y = float(event.y) if hasattr(event, 'y') and event.y is not None else (
                last_state[0][1] if last_state else 0)

            if self._unit_positions[unit_id] and event.frame <= self._unit_positions[unit_id][-1].frame:
                event.frame = self._unit_positions[unit_id][-1].frame + 1

            self._unit_positions[unit_id].append(Position(
                frame=event.frame,
                time=event.frame / self.replay.game_fps,
                x=death_x, y=death_y, z=0.0
            ))

            if unit_id in self._unit_last_state:
                del self._unit_last_state[unit_id]

    def _finalize_buildings(self):
        """Финальная обработка зданий"""
        for building_id, building in self.buildings.items():
            building.frames = self._building_positions.get(building_id, [])
            building.transforms = self._building_transforms.get(building_id, [])
            building.died_frame = self._building_deaths.get(building_id)
            building.died_time = (building.died_frame / self.replay.game_fps) if building.died_frame else None

    def _finalize_units(self):
        """Финальная обработка юнитов"""
        for unit_id, unit in self.units.items():
            unit.positions = self._unit_positions.get(unit_id, [])
            unit.died_frame = self._unit_deaths.get(unit_id)
            unit.died_time = (unit.died_frame / self.replay.game_fps) if unit.died_frame else None

    def _normalize_all_positions(self):
        """Нормализация всех координат (центрирование карты)"""
        all_positions = []

        for building in self.buildings.values():
            all_positions.extend(building.frames)
            for transform in building.transforms:
                pass

        for unit in self.units.values():
            all_positions.extend(unit.positions)

        if not all_positions:
            return

        min_x = min(p.x for p in all_positions)
        max_x = max(p.x for p in all_positions)
        min_y = min(p.y for p in all_positions)
        max_y = max(p.y for p in all_positions)

        center_x = (min_x + max_x) / 2
        center_y = (min_y + max_y) / 2

        logging.info(f"\n🎯 Нормализация позиций:")
        logging.info(f"   X диапазон: {min_x:.1f} - {max_x:.1f}, центр: {center_x:.1f}")
        logging.info(f"   Y диапазон: {min_y:.1f} - {max_y:.1f}, центр: {center_y:.1f}")

        # Сдвигаем все позиции
        for position in all_positions:
            position.x -= center_x
            position.y -= center_y

    def _build_result(self, replay_path: str) -> Dict[str, Any]:
        """Формирование итогового JSON"""
        players_info = []
        for player in self.replay.players:
            if not player.is_observer:
                players_info.append({
                    'name': player.name,
                    'race': player.play_race,
                    'team': f"{player.team}: Player {player.pid} - {player.name} ({player.play_race})",
                    'result': player.result,
                    'is_human': player.is_human
                })

        metadata = {
            'replay_file': replay_path,
            'version': self.replay.release_string,
            'duration': f"{self.replay.length.seconds // 60} minutes {self.replay.length.seconds % 60} seconds",
            'fps': float(self.replay.game_fps),
            'map': self.replay.map_name,
            'players': players_info
        }

        result = {
            'metadata': metadata,
            'buildings': [building.to_dict() for building in self.buildings.values()],
            'units': [unit.to_dict() for unit in self.units.values()]
        }

        logging.info(f"\n📊 Итоговая статистика:")
        logging.info(f"   🏠 Зданий: {len(result['buildings'])}")
        logging.info(f"   ⚔️ Юнитов: {len(result['units'])}")

        total_positions = sum(len(b.get('frames', [])) for b in result['buildings'])
        total_positions += sum(len(u.get('positions', [])) for u in result['units'])
        logging.info(f"   📍 Всего позиций: {total_positions}")

        return result

    def _print_stats(self, stats: dict):
        """Вывод статистики обработки"""
        logging.info(f"\n📈 Статистика обработки:")
        logging.info(
            f"   🏗️ Инициализаций зданий: {stats['init_buildings']} (из них нейтральных: {stats.get('neutral_buildings', 0)})")
        logging.info(f"   ⚔️ Инициализаций юнитов: {stats['init_units']}")
        logging.info(f"   🔄 Трансформаций: {stats['transforms']}")
        logging.info(f"   📍 Событий позиций: {stats['positions']}")
        logging.info(f"   💀 Уничтожений: {stats['deaths']}")
        logging.info(f"   📊 Всего сущностей: {len(self.buildings) + len(self.units)}")

def parse_replay_unified(replay_path: str, output_path: str = "unified_output.json"):
    """Унифицированная функция парсинга"""
    parser = UnifiedReplayParser()
    return parser.parse_replay(replay_path, output_path)


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        replay_path = sys.argv[1]
    else:
        replay_path = input("Введите путь до реплея:\n")

    output_path = "unified_replay_output.json"
    result = parse_replay_unified(replay_path, output_path)

    logging.info(f"\n✅ Готово! Создан единый JSON-файл с зданиями и юнитами")