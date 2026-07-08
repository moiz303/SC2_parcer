from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from find_main_battle import analyze_replay_file
from parce_replay import parse_replay_unified


@dataclass
class JobConfig:
    replay_path: str
    output_dir: str
    units_path: str = ""
    buildings_path: str = ""
    textures_path: str = ""
    animation_duration: int = 45
    save_full_render: bool = False
    selected_version: str = "StarCraft II"


@dataclass
class JobResult:
    success: bool
    video_path: Optional[str] = None
    message: str = ""
    metadata: Optional[Dict[str, Any]] = None


class BackendController:
    def __init__(self, base_dir: Optional[str] = None) -> None:
        self.base_dir = Path(base_dir or Path(__file__).resolve().parent)
        self.temp_dir = self.base_dir / "temp"
        self.temp_dir.mkdir(exist_ok=True)

    def build_job_config(self, frontend_state: Dict[str, Any]) -> JobConfig:
        return JobConfig(
            replay_path=frontend_state.get("replay_path", ""),
            output_dir=frontend_state.get("output_path", ""),
            units_path=frontend_state.get("units_path", ""),
            buildings_path=frontend_state.get("buildings_path", ""),
            textures_path=frontend_state.get("textures_path", ""),
            animation_duration=int(frontend_state.get("animation_duration", 45)),
            save_full_render=bool(frontend_state.get("save_full_render", False)),
            selected_version=frontend_state.get("selected_version", "StarCraft II"),
        )

    def run_job(self, job_config: JobConfig, progress_cb: Optional[Callable[[int, str], None]] = None) -> JobResult:
        if not job_config.replay_path:
            return JobResult(success=False, message="Путь к реплею не указан")

        replay_path = Path(job_config.replay_path)
        if not replay_path.exists():
            return JobResult(success=False, message=f"Файл реплея не найден: {replay_path}")

        output_file = self.resolve_output_video_path(job_config)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        self._emit(progress_cb, 10, "Парсим реплей…")
        temp_unified_path = self.temp_dir / f"unified_{replay_path.stem}.json"
        parse_replay_unified(str(replay_path), str(temp_unified_path))

        self._emit(progress_cb, 25, "Ищем основной бой…")
        analysis = analyze_replay_file(str(temp_unified_path), window_seconds=min(job_config.animation_duration, 45))
        if not analysis.get("success", False):
            return JobResult(success=False, message=analysis.get("error") or "Не удалось определить основной бой")

        self._emit(progress_cb, 40, "Готовим параметры для Blender…")
        render_payload = self.prepare_render_payload(job_config, analysis, temp_unified_path)
        render_payload_path = self.write_render_payload(render_payload)
        video_path = self._run_blender_render(job_config, render_payload_path, output_file, render_payload, progress_cb)
        if not video_path:
            return JobResult(success=False, message="Blender не создал итоговый видеофайл")

        self._emit(progress_cb, 100, "Готово")
        return JobResult(
            success=True,
            video_path=str(video_path),
            message="Анимация сохранена",
            metadata={
                "replay_path": str(replay_path),
                "analysis": analysis,
                "unified_json": str(temp_unified_path),
                "render_payload_path": str(render_payload_path),
                "render_payload": render_payload,
            },
        )

    def resolve_output_video_path(self, job_config: JobConfig) -> Path:
        raw_path = (job_config.output_dir or str(self.temp_dir / "output")).strip()
        if not raw_path:
            raw_path = str(self.temp_dir / "output")

        candidate = Path(raw_path)
        if candidate.suffix.lower() in {".mp4", ".mov", ".avi", ".mkv", ".webm"}:
            return candidate

        if candidate.exists() and candidate.is_file():
            return candidate

        if candidate.exists() and candidate.is_dir():
            return candidate / "result.mp4"

        if candidate.suffix:
            return candidate.with_suffix(".mp4")

        return candidate / "result.mp4"

    def prepare_render_payload(self, job_config: JobConfig, analysis: Dict[str, Any], unified_json_path: Optional[Path] = None) -> Dict[str, Any]:
        return {
            "replay_path": job_config.replay_path,
            "output_path": job_config.output_dir,
            "units_path": job_config.units_path,
            "buildings_path": job_config.buildings_path,
            "textures_path": job_config.textures_path,
            "animation_duration": job_config.animation_duration,
            "save_full_render": job_config.save_full_render,
            "selected_version": job_config.selected_version,
            "analysis": analysis,
            "unified_json_path": str(unified_json_path) if unified_json_path else None,
            "speeds_json_path": str(self.base_dir / "speeds.json"),
            "input_json_schema": "UnifiedReplayOutput",
        }

    def write_render_payload(self, render_payload: Dict[str, Any]) -> Path:
        payload_path = self.temp_dir / f"render_payload_{len(list(self.temp_dir.glob('render_payload_*')))}.json"
        with payload_path.open("w", encoding="utf-8") as handle:
            json.dump(render_payload, handle, ensure_ascii=False, indent=2)
        return payload_path

    def _run_blender_render(self, job_config: JobConfig, payload_path: Path, output_file: Path, render_payload: Dict[str, Any], progress_cb: Optional[Callable[[int, str], None]] = None) -> Optional[Path]:
        blender_script = self.base_dir / "import_to_blender.py"
        if not blender_script.exists():
            return None

        output_file.parent.mkdir(parents=True, exist_ok=True)

        blender_executable = find_blender_executable()
        if not blender_executable:
            return None

        self._emit(progress_cb, 70, "Запускаем рендер…")

        # Передаём путь к render_payload.json и выходной файл как аргументы
        # Синтаксис: blender --background --python script.py -- payload.json output.mp4
        cmd = [
            blender_executable,
            "--background",
            "--python",
            str(blender_script),
            "--",
            str(payload_path),
            str(output_file),
        ]
        return run_blender_render(cmd, output_file)

    def _emit(self, progress_cb: Optional[Callable[[int, str], None]], progress: int, message: str) -> None:
        if progress_cb:
            progress_cb(progress, message)


def find_blender_executable() -> Optional[str]:
    candidates = []

    for env_key in ("BLENDER_EXE", "BLENDER"):
        value = os.getenv(env_key)
        if value:
            candidates.append(value)

    candidates.extend([
        r"C:\Program Files\Blender Foundation\Blender 5.0\blender.exe",
        r"C:\Program Files\Blender Foundation\Blender 4.4\blender.exe",
        r"C:\Program Files\Blender Foundation\Blender 4.3\blender.exe",
        r"C:\Program Files\Blender Foundation\Blender 4.2\blender.exe",
        "blender",
        "blender.exe",
    ])

    for candidate in candidates:
        if not candidate:
            continue
        if shutil.which(candidate):
            return shutil.which(candidate)
        if Path(candidate).exists():
            return str(candidate)

    return None


def run_blender_render(command: list[str], expected_output_path: Optional[Path] = None) -> Optional[Path]:
    """
    Запускает Blender с указанной командой.
    
    Args:
        command: Список аргументов для subprocess.run
        expected_output_path: Ожидаемый путь к output файлу
    
    Returns:
        Path к созданному видеофайлу или None при ошибке
    """
    try:
        print(f"▶ Запуск Blender: {' '.join(command)}")
        completed = subprocess.run(command, capture_output=True, text=True, timeout=900, check=False)
    except FileNotFoundError:
        print("✗ Blender не найден в системе")
        return None
    except subprocess.TimeoutExpired:
        print("✗ Timeout при рендере (900 секунд)")
        return None

    # Логируем вывод Blender для отладки
    if completed.stdout:
        print(f"[Blender stdout]\n{completed.stdout[:500]}")  # Первые 500 символов
    if completed.stderr:
        print(f"[Blender stderr]\n{completed.stderr[:500]}")

    if completed.returncode != 0:
        print(f"✗ Blender завершился с ошибкой (код {completed.returncode})")
        if completed.stderr:
            print(f"Детали ошибки: {completed.stderr}")
        return None

    # Проверяем что output файл был создан
    output_file = expected_output_path
    if output_file and output_file.exists():
        print(f"✓ Видеофайл создан: {output_file}")
        return output_file
    else:
        print(f"✗ Output файл не найден: {output_file}")
        return None
