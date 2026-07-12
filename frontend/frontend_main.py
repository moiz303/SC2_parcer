from __future__ import annotations

import json
import threading
import shutil, os, sys
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Dict

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from controller_backend import BackendController, JobConfig


class Screen(str, Enum):
    WELCOME = "welcome"
    REPLAY = "replay"
    MODELS = "models"
    LOADING = "loading"
    DONE = "done"


def find_resource_folders(root_dir: str, selected_version: str | None = None) -> Dict[str, str]:
    """Пытается автоматически найти папки с моделями, зданиями и текстурами."""
    result: Dict[str, str] = {"units": "", "buildings": "", "textures": ""}
    if not root_dir or not os.path.exists(root_dir):
        return result

    def _normalize(path: str) -> str:
        return os.path.abspath(path)

    search_roots: list[str] = []
    for candidate in [root_dir, os.path.dirname(root_dir), os.path.expanduser("~")]:
        if candidate and os.path.exists(candidate):
            candidate_path = _normalize(candidate)
            if candidate_path not in search_roots:
                search_roots.append(candidate_path)

    drive_root = os.path.splitdrive(_normalize(root_dir))[0] + os.sep
    if drive_root not in search_roots:
        search_roots.append(drive_root)

    if selected_version:
        version_candidates = []
        for candidate in search_roots:
            version_path = os.path.join(candidate, selected_version)
            if os.path.exists(version_path):
                version_candidates.append(_normalize(version_path))
        search_roots = version_candidates + search_roots

    for search_root in search_roots:
        if all(result.values()):
            break
        for dirpath, dirnames, _ in os.walk(search_root):
            for dirname in dirnames:
                full_path = os.path.abspath(os.path.join(dirpath, dirname))
                path_lower = full_path.lower()

                if not result["textures"] and any(
                        token in path_lower for token in ("texture", "textures", "tex", "material", "materials")):
                    result["textures"] = full_path
                elif not result["units"] and ("unit" in path_lower or "units" in path_lower) and (
                        "model" in path_lower or "models" in path_lower
                ):
                    result["units"] = full_path
                elif not result["buildings"] and ("building" in path_lower or "buildings" in path_lower) and (
                        "model" in path_lower or "models" in path_lower
                ):
                    result["buildings"] = full_path

    return result


class RoundedButton(tk.Canvas):
    def __init__(self, parent, text, command=None, width=140, height=38, radius=12,
                 bg="#2563eb", fg="#ffffff", active_bg=None, outline="",
                 font=("Segoe UI", 11, "bold"), **kwargs):
        # Цвет фона Canvas должен совпадать с фоном родительского фрейма (Card.TFrame),
        # чтобы не было видимых границ самого холста
        parent_bg = "#0f172a"
        super().__init__(parent, width=width, height=height, bg=parent_bg,
                         highlightthickness=0, **kwargs)

        self.text = text
        self.command = command
        self.width = width
        self.height = height
        self.radius = radius
        self.bg = bg
        self.fg = fg
        self.active_bg = active_bg or bg
        self.outline = outline
        self.font = font
        self.current_bg = self.bg

        self.draw_button()

        # Привязываем события для эффекта наведения и клика
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)

    def draw_button(self):
        self.delete("all")
        # Координаты для сглаженного многоугольника (имитация rounded rect)
        points = [
            self.radius, 0, self.width - self.radius, 0,
            self.width, 0, self.width, self.radius,
            self.width, self.height - self.radius, self.width, self.height,
                            self.width - self.radius, self.height, self.radius, self.height,
            0, self.height, 0, self.height - self.radius,
            0, self.radius, 0, 0
        ]
        # Рисуем саму кнопку
        self.create_polygon(points, smooth=True, fill=self.current_bg, outline=self.outline, width=2)
        # Рисуем текст по центру
        self.create_text(self.width // 2, self.height // 2, text=self.text, fill=self.fg, font=self.font)

    def _on_enter(self, event):
        self.current_bg = self.active_bg
        self.draw_button()

    def _on_leave(self, event):
        self.current_bg = self.bg
        self.draw_button()

    def _on_click(self, event):
        if self.command:
            self.command()


class SmoothProgressBar(tk.Canvas):
    """Прогресс-бар с плавной (анимированной) анимацией заполнения и подписью не хранит —
    просто красиво и без рывков доезжает до целевого значения, даже если backend
    присылает редкие/скачкообразные обновления."""

    def __init__(self, parent, width=460, height=10, radius=5,
                 track_color="#111827", fill_color="#2563eb", parent_bg="#0f172a", **kwargs):
        super().__init__(parent, width=width, height=height, bg=parent_bg,
                         highlightthickness=0, **kwargs)
        self.width = width
        self.height = height
        self.radius = radius
        self.track_color = track_color
        self.fill_color = fill_color
        self.value = 0.0
        self.target = 0.0
        self._anim_job = None
        self._draw()

    def _round_rect(self, x0, y0, x1, y1, radius, **kw):
        x1 = max(x1, x0 + 0.01)
        points = [
            x0 + radius, y0, x1 - radius, y0, x1, y0, x1, y0 + radius,
            x1, y1 - radius, x1, y1, x1 - radius, y1, x0 + radius, y1,
            x0, y1, x0, y1 - radius, x0, y0 + radius, x0, y0,
        ]
        return self.create_polygon(points, smooth=True, **kw)

    def _draw(self):
        self.delete("all")
        self._round_rect(0, 0, self.width, self.height, self.radius, fill=self.track_color, outline="")
        if self.value > 0.3:
            fill_w = max(self.height, self.width * (self.value / 100))
            self._round_rect(0, 0, fill_w, self.height, self.radius, fill=self.fill_color, outline="")

    def set_target(self, value: float) -> None:
        self.target = max(0.0, min(100.0, value))
        if self._anim_job is None:
            self._tick()

    def _tick(self) -> None:
        diff = self.target - self.value
        if abs(diff) < 0.2:
            self.value = self.target
            self._draw()
            self._anim_job = None
            return
        self.value += diff * 0.18
        self._draw()
        self._anim_job = self.after(16, self._tick)


@dataclass
class FrontendState:
    replay_path: str = ""
    output_path: str = ""
    save_full_render: bool = False
    units_path: str = ""
    buildings_path: str = ""
    textures_path: str = ""
    selected_version: str = "StarCraft II"
    animation_duration: int = 45


class FrontendController:
    def __init__(self) -> None:
        self.current_screen: Screen = Screen.WELCOME
        self._state = FrontendState()
        self._screen_key = 0

    @property
    def state(self) -> FrontendState:
        return self._state

    def snapshot(self) -> Dict[str, Any]:
        payload = asdict(self._state)
        payload["screen"] = self.current_screen.value
        payload["screen_key"] = self._screen_key
        return payload

    def start(self) -> None:
        self.current_screen = Screen.WELCOME
        self._screen_key += 1

    def set_replay_path(self, value: str) -> None:
        self._state.replay_path = value

    def set_output_path(self, value: str) -> None:
        self._state.output_path = value

    def set_save_full_render(self, value: bool) -> None:
        self._state.save_full_render = value

    def set_units_path(self, value: str) -> None:
        self._state.units_path = value

    def set_buildings_path(self, value: str) -> None:
        self._state.buildings_path = value

    def set_textures_path(self, value: str) -> None:
        self._state.textures_path = value

    def set_selected_version(self, value: str) -> None:
        self._state.selected_version = value

    def set_animation_duration(self, value: int) -> None:
        self._state.animation_duration = value

    def next_step(self) -> None:
        if self.current_screen == Screen.WELCOME:
            self.current_screen = Screen.REPLAY
        elif self.current_screen == Screen.REPLAY:
            self.current_screen = Screen.MODELS
        self._screen_key += 1

    def back_step(self) -> None:
        if self.current_screen == Screen.MODELS:
            self.current_screen = Screen.REPLAY
        elif self.current_screen == Screen.REPLAY:
            self.current_screen = Screen.WELCOME
        self._screen_key += 1

    def start_generation(self) -> None:
        self.current_screen = Screen.LOADING
        self._screen_key += 1

    def complete_generation(self) -> None:
        self.current_screen = Screen.DONE
        self._screen_key += 1

    def reset(self) -> None:
        self._state = FrontendState()
        self.current_screen = Screen.WELCOME
        self._screen_key += 1

    def status_label(self) -> str:
        return {
            Screen.WELCOME: "",
            Screen.REPLAY: "Шаг 1 — Выбор повтора",
            Screen.MODELS: "Шаг 2 — Путь к ассетам",
            Screen.LOADING: "Обработка реплея…",
            Screen.DONE: "Готово!",
        }[self.current_screen]


class FrontendApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.controller = FrontendController()
        self.clear_temp()
        self.backend = BackendController()
        self.title("Replay Master")
        self.geometry("1100x720")
        self.resizable(False, False)
        self.configure(bg="#07111f")

        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.project_root = os.path.dirname(self.base_dir)
        self.preview_path = os.path.join(self.base_dir, "public", "preview.mp4")
        self.icon_path = os.path.join(self.base_dir, "public", "icon.jpg")

        self.style = ttk.Style(self)
        self.style.theme_use("clam")
        self.style.configure("TFrame", background="#07111f")
        self.style.configure("Card.TFrame", background="#0f172a")
        self.style.configure("Title.TLabel", background="#07111f", foreground="#f8fafc", font=("Segoe UI", 22, "bold"))
        self.style.configure("Body.TLabel", background="#07111f", foreground="#cbd5e1", font=("Segoe UI", 12))
        self.style.configure("Muted.TLabel", background="#07111f", foreground="#7c879c", font=("Segoe UI", 11))
        self.style.configure("Primary.TButton", background="#2563eb", foreground="#ffffff")
        self.style.map("Primary.TButton", background=[("active", "#1d4ed8")])
        self.style.configure("Secondary.TButton", background="#1f2937", foreground="#f3f4f6")
        self.style.configure("Outline.TButton", background="#111827", foreground="#e5e7eb")

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        self.header = ttk.Frame(self, style="Card.TFrame", padding=(20, 12))
        self.header.grid(row=0, column=0, sticky="ew")
        self.header.columnconfigure(1, weight=1)
        self.header.rowconfigure(0, weight=1)

        self.logo_image = self._load_image(self.icon_path, 42, 42)
        if self.logo_image is not None:
            self.logo_label = tk.Label(self.header, image=self.logo_image, bg="#0f172a", bd=0)
            self.logo_label.grid(row=0, column=0, sticky="w", padx=(0, 10))
        else:
            self.logo_label = tk.Label(self.header, text="▶", fg="#60a5fa", bg="#0f172a", font=("Segoe UI", 22, "bold"))
            self.logo_label.grid(row=0, column=0, sticky="w", padx=(0, 10))

        ttk.Label(self.header, text="Replay Master", style="Title.TLabel").grid(row=0, column=1, sticky="w")
        ttk.Label(self.header, text="Обработчик повторов из RTS", style="Muted.TLabel").grid(row=1, column=1,
                                                                                             sticky="w")

        self.content = ttk.Frame(self, padding=20)
        self.content.grid(row=1, column=0, sticky="nsew")
        self.content.columnconfigure(0, weight=1)
        self.content.rowconfigure(0, weight=1)

        self.footer = ttk.Frame(self, style="Card.TFrame", padding=(20, 10))
        self.footer.grid(row=2, column=0, sticky="ew")
        self.footer.columnconfigure(0, weight=1)
        self.footer.columnconfigure(1, weight=1)
        self.status_var = tk.StringVar(value="")
        self.version_var = tk.StringVar(value="StarCraft II")
        ttk.Label(self.footer, textvariable=self.status_var, style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(self.footer, textvariable=self.version_var, style="Muted.TLabel").grid(row=0, column=1, sticky="e")

        self.welcome_title_var = tk.StringVar(value="Творите вместе с Replay Master")
        self.welcome_desc_var = tk.StringVar(
            value="Превращайте повторы из StarCraft II и других стратегий в кинематографичную анимацию главного сражения всего за пару кликов!")

        self._preview_frame = 0  # Инициализируем кадр для превью до сборки экранов
        self.done_canvas = None  # Избегаем пересечения имен с self.preview_canvas

        self.screens: Dict[Screen, ttk.Frame] = {}
        self.build_screens()
        self.show_screen(Screen.WELCOME)
        self.protocol("WM_DELETE_WINDOW", self._on_close_app)

    def _on_close_app(self):
        self.save_history()
        self.clear_temp()
        self.destroy()

    def build_screens(self) -> None:
        self.screens[Screen.WELCOME] = self.make_welcome_screen()
        self.screens[Screen.REPLAY] = self.make_replay_screen()
        self.screens[Screen.MODELS] = self.make_models_screen()
        self.screens[Screen.LOADING] = self.make_loading_screen()
        self.screens[Screen.DONE] = self.make_done_screen()

    def show_screen(self, screen: Screen) -> None:
        for frame in self.screens.values():
            frame.grid_remove()
        self.screens[screen].grid(row=0, column=0, sticky="nsew")
        self.status_var.set(self.controller.status_label())
        self.version_var.set(self.controller.state.selected_version)
        if screen == Screen.MODELS:
            if not os.path.exists(self._get_config_path()):
                self.auto_scan_resources(self.project_root)
            else:
                with open(self._get_config_path(), "r") as f:
                    if not json.load(f)['units_path']:
                        self.auto_scan_resources(self.project_root)
        if screen == Screen.WELCOME:
            self._update_welcome_layout()
        if screen == Screen.DONE:
            self._load_done_preview()

    def _update_welcome_layout(self) -> None:
        if hasattr(self, "welcome_desc"):
            width = max(320, self.winfo_width() - 260)
            self.welcome_desc.configure(wraplength=width)

    def _load_done_preview(self) -> None:
        """Динамически подгружает и запускает видео/GIF в момент показа экрана."""
        output_path = str(self.done_path_var.get())
        if not output_path or not os.path.exists(output_path):
            return

        self.done_label.configure(image="")

        if output_path.lower().endswith(('.mp4', '.avi', '.mkv', '.mov')):
            self._setup_mp4_player(self.done_label, output_path, self.MAX_W, self.MAX_H)

    def auto_scan_resources(self, base_dir: str) -> None:
        """Рекурсивно пытается найти папки с моделями и текстурами без ручного выбора."""
        if not base_dir or not os.path.exists(base_dir):
            return

        game_version = (self.version_var.get() or "").strip()
        found = find_resource_folders(base_dir, game_version)

        if not any(found.values()):
            fallback_roots = [self.project_root, self.base_dir, os.path.expanduser("~")]
            for fallback_root in fallback_roots:
                if fallback_root and fallback_root != base_dir and os.path.exists(fallback_root):
                    found = find_resource_folders(fallback_root, game_version)
                    if any(found.values()):
                        break

        if found["units"]:
            self.units_var.set(found["units"])
            self.controller.set_units_path(found["units"])
        if found["buildings"]:
            self.buildings_var.set(found["buildings"])
            self.controller.set_buildings_path(found["buildings"])
        if found["textures"]:
            self.textures_var.set(found["textures"])
            self.controller.set_textures_path(found["textures"])

    def _load_image(self, path: str, width: int, height: int):
        if not path or not os.path.exists(path):
            return None
        ext = os.path.splitext(path)[1].lower()
        try:
            if ext == ".svg":
                import cairosvg
                from PIL import Image, ImageTk
                import io

                png_bytes = cairosvg.svg2png(url=path, output_width=width, output_height=height)
                image = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
                return ImageTk.PhotoImage(image.resize((width, height)))
            if ext == ".gif":
                from PIL import Image, ImageTk

                image = Image.open(path)
                image = image.convert("RGBA")
                image = image.resize((width, height), Image.Resampling.LANCZOS)
                return ImageTk.PhotoImage(image)
            if ext in {".png", ".jpg", ".jpeg"}:
                from PIL import Image, ImageTk

                image = Image.open(path).convert("RGBA")
                return ImageTk.PhotoImage(image.resize((width, height), Image.Resampling.LANCZOS))
        except Exception:
            return None
        return None

    def _get_config_path(self) -> str:
        """Возвращает путь к файлу конфигурации в папке со скриптом."""
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui_config.json")

    def load_history(self, screen_name) -> None:
        """Загружает ранее сохраненные значения из JSON файла."""
        config_path = self._get_config_path()
        if not os.path.exists(config_path):
            return

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                SCREEN_FIELDS = {
                    "replay": {"replay_path", "output_path", "animation_duration", "save_full_render"},
                    "models": {"units_path", "buildings_path", "textures_path", "selected_version"}
                }
                if screen_name in SCREEN_FIELDS:
                    for key in SCREEN_FIELDS[screen_name]:
                        value = data[key]
                        if key == "animation_duration":
                            var_name = "duration_var"
                        elif key == "selected_version":
                            var_name = "version_var"
                        else:
                            var_name = f"{'_'.join(key.split('_')[:-1])}_var"
                        getattr(self, var_name).set(value)
                        getattr(self.controller, f"set_{key}")(value)
        except Exception as e:
            print(f"Не удалось загрузить историю UI: {e}")

    def save_history(self) -> None:
        """Сохраняет текущие значения полей ввода в JSON файл."""
        config_path = self._get_config_path()
        try:
            data = {
                "replay_path": self.replay_var.get(),
                "output_path": self.output_var.get(),
                "units_path": self.units_var.get(),
                "buildings_path": self.buildings_var.get(),
                "textures_path": self.textures_var.get(),
                "selected_version": self.version_var.get(),
                "animation_duration": self.duration_var.get(),
                "save_full_render": self.save_full_var.get()
            }
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"Не удалось сохранить историю UI: {e}")

    def _make_step_sidebar(self, parent: ttk.Frame, current_step: int) -> ttk.Frame:
        sidebar = ttk.Frame(parent, style="Card.TFrame", padding=(20, 24))
        sidebar.grid(row=0, column=0, sticky="ns", padx=(0, 24))
        sidebar.columnconfigure(0, weight=1)
        ttk.Label(sidebar, text="Путь обработки", style="Muted.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 12))

        steps = [
            (1, "Выбор повтора"),
            (2, "Настройка моделей"),
            (3, "Готово"),
        ]
        for idx, (step_no, label) in enumerate(steps, start=1):
            state = "done" if step_no < current_step else "active" if step_no == current_step else "todo"
            row = idx
            dot = "●" if state == "active" else "✓" if state == "done" else "○"
            color = "#60a5fa" if state == "active" else "#34d399" if state == "done" else "#64748b"
            ttk.Label(sidebar, text=f"{dot}  {label}", foreground=color, background="#0f172a",
                      font=("Segoe UI", 11, "bold")).grid(row=row, column=0, sticky="w", pady=4)
        return sidebar

    def _setup_mp4_player(self, label: tk.Label, video_path: str, target_width: int, target_height: int,
                          fps: int = 24) -> None:
        """
        Инициализирует и запускает проигрыватель MP4-видео на указанном Label.
        """
        if not os.path.exists(video_path):
            print(f"Предупреждение: Видеофайл не найден по пути: {video_path}")
            return

        try:
            import cv2
            from PIL import Image, ImageTk
        except ImportError:
            print("Ошибка: Для воспроизведения видео требуется установить opencv-python")
            print("Выполните: pip install opencv-python")
            return

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            print(f"Ошибка: Не удалось открыть видео {video_path}")
            return

        frames = []

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

            pil_image = Image.fromarray(frame_rgb)

            img_w, img_h = pil_image.size
            ratio_w = target_width / img_w
            ratio_h = target_height / img_h
            ratio = min(ratio_w, ratio_h)

            new_w = max(1, int(img_w * ratio))
            new_h = max(1, int(img_h * ratio))

            resized_frame = pil_image.resize((new_w, new_h), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(resized_frame)
            frames.append(photo)

        cap.release()

        if not frames:
            return

        label.frames = frames
        label.current_frame_idx = 0
        delay = max(40, int(1000 / fps))

        def update_frame() -> None:
            if not label.winfo_exists():
                return
            idx = label.current_frame_idx
            label.configure(image=label.frames[idx])
            label.current_frame_idx = (idx + 1) % len(label.frames)
            label.after(delay, update_frame)

        update_frame()

    def make_welcome_screen(self) -> ttk.Frame:
        screen_frame = ttk.Frame(self.content, style="Card.TFrame", padding=30)
        screen_frame.columnconfigure(0, weight=1)
        screen_frame.rowconfigure(0, weight=1)

        inner = ttk.Frame(screen_frame)
        inner.grid(row=0, column=0, sticky="nsew")
        inner.columnconfigure(0, weight=1)
        inner.rowconfigure(2, weight=1)

        welcome_title = tk.Label(inner, textvariable=self.welcome_title_var, bg="#0f172a", fg="#f8fafc",
                                 font=("Segoe UI", 27, "bold"), justify="center")
        welcome_title.grid(row=0, column=0, pady=(0, 10))

        self.welcome_desc = tk.Label(inner, textvariable=self.welcome_desc_var, bg="#0f172a", fg="#cbd5e1",
                                     font=("Segoe UI", 13), justify="center", wraplength=680)
        self.welcome_desc.grid(row=1, column=0, pady=(0, 20))

        preview_frame = tk.Frame(inner, bg="#0f172a", bd=0)
        preview_frame.grid(row=2, column=0, pady=(8, 20), sticky="nsew")
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.rowconfigure(0, weight=1)

        preview_frame.grid_propagate(False)

        self.preview_label = tk.Label(preview_frame, bg="#0f172a", bd=0, highlightthickness=0)
        self.preview_label.grid(row=0, column=0, sticky="")

        MAX_W, MAX_H = 560, 280
        self._setup_mp4_player(self.preview_label, self.preview_path, MAX_W, MAX_H)

        RoundedButton(inner, text="Начать создавать", command=self.on_start,
                      bg="#2563eb", active_bg="#1d4ed8").grid(row=3, column=0, pady=(6, 0))
        return screen_frame

    def make_replay_screen(self) -> ttk.Frame:
        frame = ttk.Frame(self.content, style="Card.TFrame", padding=30)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(0, weight=1)

        sidebar = self._make_step_sidebar(frame, 1)
        main = ttk.Frame(frame, padding=(10, 0, 0, 0))
        main.grid(row=0, column=1, sticky="nsew")
        main.columnconfigure(0, weight=1)

        ttk.Label(main, text="Выберите повтор и папку для анимации", style="Title.TLabel",
                  justify="center").grid(row=0, column=0, sticky="ew", pady=(0, 18))
        self.replay_var = tk.StringVar(value=self.controller.state.replay_path)
        self.output_var = tk.StringVar(value=self.controller.state.output_path)
        self.save_full_var = tk.BooleanVar(value=self.controller.state.save_full_render)
        self.duration_var = tk.IntVar(value=self.controller.state.animation_duration)
        self.load_history("replay")

        self.make_path_row(main, 1, "Файл повтора", self.replay_var, is_file=True)
        self.make_path_row(main, 3, "Папка для сохранения результата", self.output_var, is_file=False)

        check = ttk.Checkbutton(main, text="Сохранить полный рендер (весь повтор)", variable=self.save_full_var,
                                command=self.on_save_full_toggle)
        check.grid(row=5, column=0, sticky="w", pady=(10, 20))

        duration_label = tk.Label(main, text="Длительность анимации (сек):",
                                  bg="#0f172a", fg="#cbd5e1", font=("Segoe UI", 11))
        duration_label.grid(row=6, column=0, sticky="w", pady=(0, 4))

        self.duration_scale = tk.Scale(
            main,
            from_=30, to=75,
            resolution=15,  # Жесткий шаг: 30 -> 45 -> 60 -> 75
            orient="horizontal",
            variable=self.duration_var,
            command=self.on_duration_change,
            length=320,
            tickinterval=15,
            bg="#0f172a",
            fg="#cbd5e1",
            troughcolor="#1f2937",
            activebackground="#2563eb",
            highlightthickness=0, bd=0,
            sliderrelief="flat",
            font=("Segoe UI", 10, "bold")
        )
        self.duration_scale.grid(row=7, column=0, sticky="w", pady=(0, 20))

        RoundedButton(main, text="Далее → Модели", command=self.on_replay_next,
                      bg="#2563eb", active_bg="#1d4ed8").grid(row=6, column=0, sticky="e")
        return frame

    def make_models_screen(self) -> ttk.Frame:
        frame = ttk.Frame(self.content, style="Card.TFrame", padding=30)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(0, weight=1)

        sidebar = self._make_step_sidebar(frame, 2)
        main = ttk.Frame(frame, padding=(10, 0, 0, 0))
        main.grid(row=0, column=1, sticky="nsew")
        main.columnconfigure(0, weight=1)

        ttk.Label(main, text="Модели, текстуры и игровой движок", style="Title.TLabel", justify="center").grid(row=0,
                                                                                                               column=0,
                                                                                                               sticky="ew",
                                                                                                               pady=(0,
                                                                                                                     18))

        self.units_var = tk.StringVar(value=self.controller.state.units_path)
        self.buildings_var = tk.StringVar(value=self.controller.state.buildings_path)
        self.textures_var = tk.StringVar(value=self.controller.state.textures_path)
        self.version_var = tk.StringVar(value=self.controller.state.selected_version)
        self.load_history("models")

        self.make_path_row(main, 1, "Папка с моделями юнитов", self.units_var, is_file=False)
        self.make_path_row(main, 3, "Папка с моделями зданий", self.buildings_var, is_file=False)
        self.make_path_row(main, 5, "Папка с текстурами", self.textures_var, is_file=False)

        ttk.Label(main, text="Игра / Игровой движок", style="Muted.TLabel").grid(row=7, column=0, sticky="w",
                                                                                 pady=(10, 4))
        self.version_combo = ttk.Combobox(main, textvariable=self.version_var, values=["StarCraft II"],
                                          state="readonly")
        self.version_combo.grid(row=8, column=0, sticky="ew", pady=(0, 16))
        self.version_combo.bind("<<ComboboxSelected>>", lambda _event: self.auto_scan_resources(self.project_root))

        buttons = ttk.Frame(main)
        buttons.grid(row=9, column=0, sticky="ew")
        buttons.columnconfigure(0, weight=1)
        RoundedButton(buttons, text="Назад", command=self.on_back,
                      bg="#1f2937", active_bg="#374151", fg="#f3f4f6").grid(row=0, column=0, sticky="w")
        RoundedButton(buttons, text="Очистить", command=self.on_clear_all,
                      bg="#111827", active_bg="#1f2937", fg="#e5e7eb", outline="#374151").grid(row=0, column=1,
                                                                                               sticky="w", padx=(8, 0))
        RoundedButton(buttons, text="Сгенерировать", command=self.on_generate,
                      bg="#2563eb", active_bg="#1d4ed8").grid(row=0, column=2, sticky="e")
        return frame

    def make_loading_screen(self) -> ttk.Frame:
        frame = ttk.Frame(self.content, style="Card.TFrame", padding=30)
        frame.columnconfigure(0, weight=1)

        ttk.Label(frame, text="Генерация…", style="Title.TLabel").grid(row=0, column=0)

        stages = ttk.Frame(frame, style="Card.TFrame")
        stages.grid(row=2, column=0, sticky="ew")
        stages.columnconfigure(0, weight=1)

        self.loading_stages = {}

        def create_stage(row, key, number, title, color):
            stage_row = ttk.Frame(stages, style="Card.TFrame")
            stage_row.grid(row=row, column=0, sticky="ew", pady=(0, 5))
            stage_row.columnconfigure(1, weight=1)

            badge = tk.Label(stage_row, text=str(number), width=2, bg="#1f2937", fg="#7c879c",
                             font=("Segoe UI", 10, "bold"))
            badge.grid(row=0, column=0, padx=(0, 8))
            ttk.Label(stage_row, text=title, style="Muted.TLabel").grid(row=0, column=1, sticky="w")

            percent = ttk.Label(stage_row, text="0%", style="Muted.TLabel")
            percent.grid(row=0, column=2, sticky="e")

            message = ttk.Label(stages, text="", style="Body.TLabel")
            message.grid(row=row + 1, column=0, sticky="w", pady=(0, 2))

            bar = SmoothProgressBar(stages, width=460, height=10, fill_color=color, parent_bg="#0f172a")
            bar.grid(row=row + 2, column=0, sticky="ew", pady=(0, 18))

            self.loading_stages[key] = {
                "badge": badge,
                "percent": percent,
                "message": message,
                "bar": bar
            }

        create_stage(0, "parse_replay", 1, "Парсинг реплея", "#3b82f6")
        create_stage(3, "find_main_battle", 2, "Поиск главного сражения", "#3b82f6")
        create_stage(6, "import_scene", 3, "Подготовка сцены Blender", "#3b82f6")
        create_stage(9, "final_render", 4, "Рендер анимации", "#3b82f6")

        return frame

    def make_done_screen(self) -> ttk.Frame:
        frame = ttk.Frame(self.content, style="Card.TFrame", padding=30)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(0, weight=1)
        sidebar = self._make_step_sidebar(frame, 3)
        main = ttk.Frame(frame, padding=(10, 0, 0, 0))
        main.grid(row=0, column=1, sticky="nsew")
        main.columnconfigure(0, weight=1)

        ttk.Label(main, text="Анимация готова!", style="Title.TLabel", justify="center").grid(row=0, column=0,
                                                                                              sticky="ew")
        ttk.Label(main, text="Рендер сохранён успешно", style="Body.TLabel", justify="center").grid(row=1, column=0,
                                                                                                    sticky="ew",
                                                                                                    pady=(8, 16))

        self.MAX_W, self.MAX_H = 560, 280

        preview_frame = tk.Frame(main, bg="#111827", bd=0, width=self.MAX_W, height=self.MAX_H)
        preview_frame.grid(row=2, column=0, pady=(0, 16), sticky="n")
        preview_frame.grid_propagate(False)

        self.done_label = tk.Label(preview_frame, bg="#111827", bd=0, highlightthickness=0)
        self.done_label.grid(row=0, column=0, sticky="")

        self.done_path_var = tk.StringVar(
            value=self.controller.state.output_path or "C:/Users/User/Videos/SC2Renders/output.mp4")

        ttk.Label(main, textvariable=self.done_path_var, style="Muted.TLabel", justify="center").grid(row=3, column=0,
                                                                                                      sticky="ew")

        buttons = ttk.Frame(main)
        buttons.grid(row=4, column=0, sticky="ew", pady=(20, 0))
        buttons.columnconfigure(0, weight=1)

        RoundedButton(buttons, text="Новая обработка", command=self.on_reset,
                      bg="#1f2937", active_bg="#374151", fg="#f3f4f6").grid(row=0, column=0, sticky="w")
        RoundedButton(buttons, text="Готово", command=self._on_close_app,
                      bg="#2563eb", active_bg="#1d4ed8").grid(row=0, column=1, sticky="w", padx=(8, 0))
        return frame

    def make_path_row(self, parent: ttk.Frame, row: int, label_text: str, variable: tk.StringVar,
                      is_file: bool) -> None:
        ttk.Label(parent, text=label_text, style="Muted.TLabel").grid(row=row, column=0, sticky="w", pady=(8, 4))
        entry = ttk.Entry(parent, textvariable=variable, width=55)
        entry.grid(row=row + 1, column=0, sticky="ew")
        RoundedButton(parent, text="Обзор", command=lambda: self.browse_path(variable, is_file),
                      bg="#111827", active_bg="#1f2937", fg="#e5e7eb", outline="#374151",
                      width=90, height=32, radius=8).grid(row=row + 1, column=1, padx=(8, 0), sticky="e")

    def browse_path(self, variable: tk.StringVar, is_file: bool) -> None:
        if is_file:
            path = filedialog.askopenfilename(title="Выберите реплей",
                                              filetypes=[("Replay files", "*.SC2Replay"), ("All files", "*.*")])
        else:
            path = filedialog.askdirectory(title="Выберите папку")
        if path:
            variable.set(path)

    def on_start(self) -> None:
        self.controller.start()
        self.show_screen(Screen.REPLAY)

    def on_replay_next(self) -> None:
        self.controller.set_replay_path(self.replay_var.get())
        self.controller.set_output_path(self.output_var.get())
        self.controller.set_save_full_render(self.save_full_var.get())
        if not self.controller.state.replay_path or not self.controller.state.output_path:
            messagebox.showwarning("Пропущены поля!", "Пожалуйста, заполните все поля перед переходом далее")
            return
        self.controller.next_step()
        self.show_screen(Screen.MODELS)

    def on_save_full_toggle(self) -> None:
        self.controller.set_save_full_render(self.save_full_var.get())

    def on_back(self) -> None:
        self.controller.back_step()
        self.show_screen(Screen.REPLAY)

    def on_clear_all(self) -> None:
        self.units_var.set("")
        self.buildings_var.set("")
        self.textures_var.set("")
        self.controller.set_units_path("")
        self.controller.set_buildings_path("")
        self.controller.set_textures_path("")

    def on_duration_change(self, value: str) -> None:
        self.controller.set_animation_duration(int(float(value)))

    def on_generate(self) -> None:
        self.controller.set_units_path(self.units_var.get())
        self.controller.set_buildings_path(self.buildings_var.get())
        self.controller.set_textures_path(self.textures_var.get())
        self.controller.set_selected_version(self.version_var.get())
        if not all([self.controller.state.units_path, self.controller.state.buildings_path,
                    self.controller.state.textures_path]):
            messagebox.showwarning("Пропущены поля!", "Пожалуйста, заполните все поля перед началом генерации")
            return
        self.save_history()
        self.controller.start_generation()
        self._reset_loading_bars()
        self.show_screen(Screen.LOADING)
        self._start_backend_job()

    def _start_backend_job(self) -> None:
        job_config = JobConfig(
            replay_path=self.controller.state.replay_path,
            output_dir=self.controller.state.output_path,
            units_path=self.controller.state.units_path,
            buildings_path=self.controller.state.buildings_path,
            textures_path=self.controller.state.textures_path,
            animation_duration=self.controller.state.animation_duration,
            save_full_render=self.controller.state.save_full_render,
            selected_version=self.controller.state.selected_version,
        )
        threading.Thread(target=self._run_backend_job, args=(job_config,), daemon=True).start()

    def _reset_loading_bars(self) -> None:
        """Сбрасывает все прогресс-бары перед стартом нового job'а."""
        for entry in self.loading_stages.values():
            entry["bar"].value = 0.0
            entry["bar"].target = 0.0
            entry["bar"]._draw()
            entry["percent"].config(text="0%")
            entry["message"].config(text="")

    def _run_backend_job(self, job_config: JobConfig) -> None:
        result = self.backend.run_job(job_config, progress_cb=self._update_loading_status)
        self.after(0, self._finish_backend_job, result)

    def _update_loading_status(self, stage: str, progress: int, message: str) -> None:
        """Это callback, backend зовёт его из ФОНОВОГО потока — сюда напрямую
        трогать виджеты Tkinter нельзя, поэтому просто маршалим вызов в главный поток."""
        self.after(0, self._apply_loading_status, stage, progress, message)

    def _apply_loading_status(self, stage: str, progress: int, message: str) -> None:
        """А вот это уже безопасно выполняется в главном потоке."""
        entry = self.loading_stages.get(stage)
        if entry is None:
            return

        entry["bar"].set_target(progress)
        entry["percent"].config(text=f"{progress}%")
        if message:
            entry["message"].config(text=message)

        if progress >= 100:
            entry["badge"].config(bg="#22c55e", fg="#ffffff")

    def _finish_backend_job(self, result) -> None:
        if result.success and result.video_path:
            self.controller.set_output_path(result.video_path)
            self.controller.complete_generation()
            self.done_path_var.set(result.video_path)
            self.show_screen(Screen.DONE)
        else:
            self.controller.complete_generation()
            self.done_path_var.set(self.controller.state.output_path or "C:/Users/User/Videos/SC2Renders/output.mp4")
            self.show_screen(Screen.DONE)
            messagebox.showerror("Ошибка генерации", result.message or "Не удалось создать видео")

    def on_reset(self) -> None:
        self.replay_var.set(self.controller.state.replay_path)
        self.output_var.set(self.controller.state.output_path)
        self.save_full_var.set(self.controller.state.save_full_render)
        self.units_var.set(self.controller.state.units_path)
        self.buildings_var.set(self.controller.state.buildings_path)
        self.textures_var.set(self.controller.state.textures_path)
        self.version_var.set(self.controller.state.selected_version)
        self.duration_var.set(self.controller.state.animation_duration)
        self.controller.reset()

        self.show_screen(Screen.WELCOME)

    def clear_temp(self):
        path = Path(__file__).resolve().parent.parent
        temp_path = path / "temp"
        if temp_path.exists():
            shutil.rmtree(temp_path, ignore_errors=True)


def build_frontend_controller() -> FrontendController:
    return FrontendController()


def main() -> None:
    app = FrontendApp()
    app.mainloop()


if __name__ == "__main__":
    main()