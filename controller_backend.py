from __future__ import annotations

import json
import re
import os, sys, shutil
import contextlib
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from find_main_battle import analyze_replay_file
from parce_replay import parse_replay_unified

STAGE_ORDER = ("parse_replay", "find_main_battle", "import_scene", "final_render")
ProgressCallback = Callable[[str, int, str], None]
_RENDER_FRAME_RE = re.compile(r"Video append frame\s+(\d+)")


class _RenderProgressTracker:
    """Честный прогресс рендера по номерам кадров из собственного лога Blender."""

    MESSAGE_POOL = (
        "Совет: чем длиннее ролик, тем дольше рендерится анимация — начните с 30 секунд, чтобы быстрее увидеть результат.",
        "Blender честно просчитывает каждый кадр отдельно, поэтому финальное видео «весит» по времени куда больше, чем препроцессинг.",
        "Пока идёт рендер — самое время заварить чай. Мы обязательно покажем превью, как только всё будет готово.",
        "После завершения рендера ролик можно будет сразу посмотреть прямо в приложении, без сторонних плееров.",
        "Чем масштабнее было сражение в реплее, тем больше юнитов и зданий нужно анимировать — отсюда и разница во времени.",
        "Готовое видео сохраняется в указанную вами папку — точный путь появится на следующем экране.",
    )
    MESSAGE_EVERY_N_FRAMES = 15

    def __init__(self, total_frames: Optional[int], progress_cb: Optional[ProgressCallback]):
        self._total_frames = total_frames if total_frames and total_frames > 0 else None
        self._progress_cb = progress_cb
        self._first_frame: Optional[int] = None
        self._last_message_at: Optional[int] = None
        self._message_idx = 0
        self._warned_no_total = False

    def feed_line(self, line: str) -> bool:
        """Пробует распознать в строке 'Video append frame N'.
        Возвращает True, если строка была отрендер-кадровой."""
        match = _RENDER_FRAME_RE.search(line)
        if not match:
            return False

        frame = int(match.group(1))
        if self._first_frame is None:
            self._first_frame = frame

        rendered = frame - self._first_frame

        if self._total_frames:
            progress = int(min(100, max(0, (rendered / self._total_frames) * 100)))
        else:
            if not self._warned_no_total:
                print("[WARN] Нет analysis.duration_frames в render_payload — честный % рендера недоступен")
                self._warned_no_total = True
            progress = 0

        message = ""
        if self._last_message_at is None or rendered - self._last_message_at >= self.MESSAGE_EVERY_N_FRAMES:
            message = self.MESSAGE_POOL[self._message_idx % len(self.MESSAGE_POOL)]
            self._message_idx += 1
            self._last_message_at = rendered

        if self._progress_cb:
            self._progress_cb("final_render", progress, message)

        return True


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


class _StdoutUiTap:
    """Перехватывает print()-вызовы, которые происходят ВНУТРИ текущего процесса
    и разбирает из них __UI__-строки в реальном времени"""

    def __init__(self, real_stdout, progress_cb: Optional[ProgressCallback]):
        self._real_stdout = real_stdout
        self._progress_cb = progress_cb
        self._buffer = ""

    def write(self, chunk: str) -> int:
        self._buffer += chunk
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._consume_line(line)
        return len(chunk)

    def flush(self) -> None:
        # добираем "хвост" без \n на конце (на случай print(..., end=""))
        if self._buffer:
            self._consume_line(self._buffer)
            self._buffer = ""
        self._real_stdout.flush()

    def _consume_line(self, line: str) -> None:
        line = line.rstrip("\r")
        if not line:
            return
        if line.startswith("__UI__"):
            _handle_ui_line(line, self._progress_cb)
        else:
            self._real_stdout.write(line + "\n")

    def isatty(self) -> bool:
        return False


class BackendController:
    def __init__(self, base_dir: Optional[str] = None) -> None:
        self.base_dir = Path(base_dir or Path(__file__).resolve().parent)
        self.temp_dir = self.base_dir / "temp"
        self.temp_dir.mkdir(parents=True, exist_ok=True)

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

    def run_job(self, job_config: JobConfig, progress_cb: Optional[ProgressCallback] = None) -> JobResult:
        if not job_config.replay_path:
            return JobResult(success=False, message="Путь к реплею не указан")

        replay_path = Path(job_config.replay_path)
        if not replay_path.exists():
            return JobResult(success=False, message=f"Файл реплея не найден: {replay_path}")

        output_file = self.resolve_output_video_path(job_config)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        stdout_tap = _StdoutUiTap(sys.stdout, progress_cb)
        with contextlib.redirect_stdout(stdout_tap):
            temp_unified_path = self.temp_dir / f"unified_{replay_path.stem}.json"
            parse_replay_unified(str(replay_path), str(temp_unified_path))

            analysis = analyze_replay_file(
                str(temp_unified_path),
                window_seconds=min(job_config.animation_duration, 30),
            )
        stdout_tap.flush()

        if not analysis.get("success", False):
            return JobResult(success=False, message=analysis.get("error") or "Не удалось определить основной бой")

        # ---- Стадии 3-4 (prepare_scene, render) репортит сам Blender через stdout (__UI__ строки) ----
        render_payload = self.prepare_render_payload(job_config, analysis, temp_unified_path)
        render_payload_path = self.write_render_payload(render_payload)
        video_path = self._run_blender_render(job_config, render_payload_path, output_file, render_payload, progress_cb)
        if not video_path:
            return JobResult(success=False, message="Blender не создал итоговый видеофайл")
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

    def _run_blender_render(self, job_config: JobConfig, payload_path: Path, output_file: Path,
                            render_payload: Dict[str, Any], progress_cb: Optional[ProgressCallback] = None) -> Optional[Path]:
        blender_script = self.base_dir / "import_to_blender.py"
        if not blender_script.exists():
            return None

        output_file.parent.mkdir(parents=True, exist_ok=True)
        blender_executable = find_blender_executable()
        if not blender_executable:
            return None

        cmd = [
            blender_executable,
            "--background",
            "--python",
            str(blender_script),
            "--",
            str(payload_path),
            str(output_file),
        ]

        total_frames = (render_payload.get("analysis") or {}).get("duration_frames")
        return run_blender_render(cmd, output_file, progress_cb, total_frames=total_frames)


def find_blender_executable() -> Optional[str]:
    candidates = []

    for env_key in ("BLENDER_EXE", "BLENDER"):
        value = os.getenv(env_key)
        if value:
            candidates.append(value)

    candidates.extend([
        r"C:\Program Files\Blender Foundation\Blender 5.0\blender.exe",
        r"C:\Program Files\Blender Foundation\Blender 4.4\blender.exe",
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


def run_blender_render(command: list[str], expected_output_path: Optional[Path] = None,
                       progress_cb: Optional[ProgressCallback] = None, total_frames: Optional[int] = None) -> Optional[Path]:
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError:
        print("✗ Blender не найден в системе")
        return None

    frame_tracker = _RenderProgressTracker(total_frames, progress_cb)

    assert process.stdout is not None
    for raw_line in process.stdout:
        line = raw_line.rstrip("\n")
        if not line:
            continue

        if line.startswith("__UI__"):
            _handle_ui_line(line, progress_cb)
            continue

        frame_tracker.feed_line(line)
        print(line)

    try:
        returncode = process.wait(timeout=900)
    except subprocess.TimeoutExpired:
        process.kill()
        print("✗ Timeout при рендере (900 секунд)")
        return None

    if returncode != 0:
        print(f"✗ Blender завершился с кодом {returncode}")
        return None

    output_file = expected_output_path
    if output_file and output_file.exists():
        return output_file

    print(f"✗ Output файл не найден: {output_file}")
    return None


def _handle_ui_line(line: str, progress_cb: Optional[ProgressCallback]) -> None:
    """Парсит одну строку вида __UI__{...} и вызывает progress_cb, если она валидна."""
    payload = line[len("__UI__"):]
    try:
        event = json.loads(payload)
    except json.JSONDecodeError:
        print(f"[WARN] Не удалось разобрать __UI__ сообщение: {line}")
        return

    stage = event.get("stage")
    progress = event.get("progress")
    message = event.get("message", "")

    if stage is None or progress is None:
        print(f"[WARN] Неполное __UI__ сообщение: {event}")
        return

    try:
        progress = int(progress)
    except (TypeError, ValueError):
        progress = 0
    progress = max(0, min(100, progress))

    if progress_cb:
        progress_cb(stage, progress, message)
    else:
        print(f"[UI] {stage}: {progress}% — {message}")