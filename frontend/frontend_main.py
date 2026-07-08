from __future__ import annotations

import os
import sys
import json
import threading
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

                if not result["textures"] and any(token in path_lower for token in ("texture", "textures", "tex", "material", "materials")):
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
        self.backend = BackendController()
        self.title("Replay Master")
        self.geometry("1100x720")
        self.minsize(960, 640)
        self.configure(bg="#07111f")

        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.project_root = os.path.dirname(self.base_dir)
        self.logo_path = os.path.join(self.base_dir, "public", "logo.svg")
        self.preview_path = os.path.join(self.base_dir, "public", "preview.gif")
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

        self.logo_image = self._load_image(self.icon_path or self.logo_path, 42, 42)
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
        if (screen == Screen.MODELS) and not os.path.exists(self._get_config_path()):
            self.auto_scan_resources(self.project_root)
        if screen == Screen.WELCOME:
            self._update_welcome_layout()

    def _update_welcome_layout(self) -> None:
        if hasattr(self, "welcome_desc"):
            width = max(320, self.winfo_width() - 260)
            self.welcome_desc.configure(wraplength=width)
    
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

    def _show_fallback_preview(self) -> None:
        self.preview_canvas.delete("all")
        w = self.preview_canvas.winfo_width()
        h = self.preview_canvas.winfo_height()
        cx = w // 2 if w > 1 else 280
        cy = h // 2 if h > 1 else 140
        self.preview_canvas.create_text(cx, cy, text="Preview animation", fill="#9ca3af", font=("Segoe UI", 14))

    def _resize_welcome_gif(self, event) -> None:
        """Динамически изменяет размер кадров под текущий размер Canvas"""
        if not self._gif_source_frames:
            return

        from PIL import ImageTk

        # Берем текущие размеры, выделенные менеджвером геометрии
        canvas_width = event.width
        canvas_height = event.height

        if canvas_width < 10 or canvas_height < 10:
            return

        self._gif_frames = []
        for img in self._gif_source_frames:
            # Масштабируем с сохранением пропорций (aspect ratio) или вписываем жестко:
            resized_img = img.resize((canvas_width, canvas_height), Image.Resampling.LANCZOS)
            self._gif_frames.append(ImageTk.PhotoImage(resized_img))

        self._update_gif_canvas_frame()

    def _update_gif_canvas_frame(self) -> None:
        if not self._gif_frames:
            return
        w = self.preview_canvas.winfo_width()
        h = self.preview_canvas.winfo_height()

        if self._canvas_gif_image_id is not None:
            self.preview_canvas.delete(self._canvas_gif_image_id)

        # Отрисовываем строго по центру Canvas
        self._canvas_gif_image_id = self.preview_canvas.create_image(
            w // 2, h // 2, image=self._gif_frames[self._gif_frame_index], anchor="center"
        )

    def _animate_gif(self) -> None:
        if not hasattr(self, "_gif_frames") or not self._gif_frames:
            return
        if self.preview_canvas is None or self._canvas_gif_image_id is None:
            return

        self._gif_frame_index = (self._gif_frame_index + 1) % len(self._gif_frames)

        # Изменяем изображение существующего объекта в Canvas вместо пересоздания виджетов
        self.preview_canvas.itemconfig(self._canvas_gif_image_id, image=self._gif_frames[self._gif_frame_index])
        self.after(80, self._animate_gif)

    def make_welcome_screen(self) -> ttk.Frame:
        screen_frame = ttk.Frame(self.content, style="Card.TFrame", padding=30)
        screen_frame.columnconfigure(0, weight=1)
        screen_frame.rowconfigure(0, weight=1)

        inner = ttk.Frame(screen_frame)
        inner.grid(row=0, column=0, sticky="nsew")  # Добавили sticky
        inner.columnconfigure(0, weight=1)
        inner.rowconfigure(2, weight=1)  # Даем строке с превью приоритет на расширение

        welcome_title = tk.Label(inner, textvariable=self.welcome_title_var, bg="#0f172a", fg="#f8fafc",
                                 font=("Segoe UI", 27, "bold"), justify="center")
        welcome_title.grid(row=0, column=0, pady=(0, 10))

        self.welcome_desc = tk.Label(
            inner,
            textvariable=self.welcome_desc_var,
            bg="#0f172a",
            fg="#cbd5e1",
            font=("Segoe UI", 13),
            justify="center",
            wraplength=680,
        )
        self.welcome_desc.grid(row=1, column=0, pady=(0, 20))

        # Контейнер для превью
        preview_frame = tk.Frame(inner, bg="#0f172a", bd=0)
        preview_frame.grid(row=2, column=0, pady=(8, 20), sticky="nsew")
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.rowconfigure(0, weight=1)

        # Жестко говорим фрейму: не раздувайся больше, чем тебе положено!
        preview_frame.grid_propagate(False)

        # Базовые безопасные размеры для превью
        MAX_W, MAX_H = 560, 280

        self.preview_canvas = tk.Canvas(preview_frame, width=MAX_W, height=MAX_H, bg="#0f172a", highlightthickness=0)
        self.preview_canvas.grid(row=0, column=0, sticky="")

        self._gif_frames = []
        self._gif_frame_index = 0
        self._canvas_gif_image_id = None

        if os.path.exists(self.preview_path):
            from PIL import Image, ImageTk

            try:
                gif = Image.open(self.preview_path)

                # Умный расчет пропорций (Aspect Ratio), чтобы не искажать гифку
                orig_w, orig_h = gif.size
                ratio = min(MAX_W / orig_w, MAX_H / orig_h)
                new_w = int(orig_w * ratio)
                new_h = int(orig_h * ratio)

                # Подгоняем Canvas под идеально рассчитанный размер
                self.preview_canvas.configure(width=new_w, height=new_h)

                for frame_index in range(gif.n_frames):
                    gif.seek(frame_index)
                    gif_frame_img = gif.convert("RGBA")
                    # Пропорциональный ресайз без хардкода
                    gif_frame_img = gif_frame_img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                    self._gif_frames.append(ImageTk.PhotoImage(gif_frame_img))

                if self._gif_frames:
                    # Отрисовываем первый кадр прямо внутри Canvas
                    self._canvas_gif_image_id = self.preview_canvas.create_image(
                        new_w // 2, new_h // 2, image=self._gif_frames[0], anchor="center"
                    )
                    self._animate_gif()
                else:
                    raise RuntimeError("No GIF frames loaded")
            except Exception:
                self.preview_canvas.create_rectangle(0, 0, MAX_W, MAX_H, fill="#111827", outline="#1f2937")
                self.preview_canvas.create_text(MAX_W // 2, MAX_H // 2, text="Preview animation", fill="#9ca3af",
                                                font=("Segoe UI", 14))
        else:
            self.preview_canvas.create_rectangle(0, 0, MAX_W, MAX_H, fill="#111827", outline="#1f2937")
            self.preview_canvas.create_text(MAX_W // 2, MAX_H // 2, text="Preview animation", fill="#9ca3af",
                                            font=("Segoe UI", 14))

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
                                                                                                               pady=(
                                                                                                               0, 18))

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
        frame.rowconfigure(2, weight=1)
        ttk.Label(frame, text="Генерация…", style="Title.TLabel").grid(row=0, column=0, sticky="n")
        self.loading_label = ttk.Label(frame, text="Подготавливаем ассеты…", style="Body.TLabel")
        self.loading_label.grid(row=1, column=0, pady=(8, 16))
        self.progress = ttk.Progressbar(frame, mode="determinate", length=320)
        self.progress.grid(row=2, column=0, sticky="n")
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

        self.done_canvas = tk.Canvas(main, width=560, height=260, bg="#111827", highlightthickness=0)
        self.done_canvas.grid(row=2, column=0, sticky="ew", pady=(0, 16))

        self._draw_preview_canvas()
        self._animate_preview_canvas()

        self.done_path_var = tk.StringVar(
            value=self.controller.state.output_path or "C:/Users/User/Videos/SC2Renders/output.mp4")
        ttk.Label(main, textvariable=self.done_path_var, style="Muted.TLabel", justify="center").grid(row=3, column=0,
                                                                                                      sticky="ew")
        buttons = ttk.Frame(main)
        buttons.grid(row=4, column=0, sticky="ew", pady=(20, 0))
        RoundedButton(buttons, text="Новая обработка", command=self.on_reset,
                      bg="#1f2937", active_bg="#374151", fg="#f3f4f6").grid(row=0, column=0, sticky="w")
        RoundedButton(buttons, text="Готово", command=self.destroy,
                      bg="#2563eb", active_bg="#1d4ed8").grid(row=0, column=1, sticky="w", padx=(8, 0))
        return frame

    def _draw_preview_canvas(self) -> None:
        if self.done_canvas is None:
            return
        self.done_canvas.delete("all")
        self.done_canvas.create_rectangle(0, 0, 560, 260, fill="#111827", outline="#1f2937")
        for i in range(6):
            x = 60 + i * 70
            h = 40 + ((i + self._preview_frame) % 6) * 20
            self.done_canvas.create_rectangle(x, 220 - h, x + 36, 220, fill="#2563eb", outline="")
        self.done_canvas.create_text(280, 90, text="Render preview loop", fill="#f8fafc", font=("Segoe UI", 16, "bold"))
        self.done_canvas.create_text(280, 125, text="~45s loop • frames update continuously", fill="#94a3b8",
                                     font=("Segoe UI", 11))
        self.done_canvas.create_rectangle(70, 160, 490, 178, fill="#1f2937")
        self.done_canvas.create_rectangle(70, 160, 70 + 420 * 0.3, 178, fill="#38bdf8")
        self.done_canvas.create_oval(70 + 420 * 0.3 - 8, 152, 70 + 420 * 0.3 + 8, 168, fill="#f8fafc")

    def _animate_preview_canvas(self) -> None:
        self._preview_frame = (self._preview_frame + 1) % 8
        self._draw_preview_canvas()
        self.after(120, self._animate_preview_canvas)

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
        self.show_screen(Screen.LOADING)
        self.run_loading_sequence()

    def run_loading_sequence(self) -> None:
        self.progress["value"] = 0
        self.loading_label["text"] = "Подготавливаем ассеты…"
        self.after(150, self._start_backend_job)

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
        self._update_loading_status(10, "Подготавливаем ассеты…")
        threading.Thread(target=self._run_backend_job, args=(job_config,), daemon=True).start()

    def _run_backend_job(self, job_config: JobConfig) -> None:
        result = self.backend.run_job(job_config, progress_cb=self._update_loading_status)
        self.after(0, self._finish_backend_job, result)

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

    def _update_loading_status(self, progress_value: int, message: str) -> None:
        self.progress["value"] = progress_value
        self.loading_label["text"] = message

    def on_reset(self) -> None:
        self.controller.reset()
        self.replay_var.set(self.controller.state.replay_path)
        self.output_var.set(self.controller.state.output_path)
        self.save_full_var.set(self.controller.state.save_full_render)
        self.units_var.set(self.controller.state.units_path)
        self.buildings_var.set(self.controller.state.buildings_path)
        self.textures_var.set(self.controller.state.textures_path)
        self.version_var.set(self.controller.state.selected_version)
        self.duration_var.set(self.controller.state.animation_duration)

        self.show_screen(Screen.WELCOME)


def build_frontend_controller() -> FrontendController:
    return FrontendController()


def main() -> None:
    app = FrontendApp()
    app.mainloop()


if __name__ == "__main__":
    main()