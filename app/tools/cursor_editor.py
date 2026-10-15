from __future__ import annotations

import io
import struct
import tkinter as tk
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox, ttk

from PIL import Image, ImageColor, ImageDraw, ImageEnhance, ImageOps, ImageTk

from app.palette import palette
from app.tool_registry import ToolSpec
from app.ui import RoundedButton, RoundedFrame


def _chunk(chunk_id: bytes, payload: bytes) -> bytes:
    padding = b"\0" if len(payload) % 2 else b""
    return chunk_id + struct.pack("<I", len(payload)) + payload + padding


def _read_image(blob: bytes) -> Image.Image:
    try:
        with Image.open(io.BytesIO(blob)) as image:
            return image.convert("RGBA")
    except Exception as first_error:
        try:
            with Image.open(io.BytesIO(_dib_as_bmp(blob))) as image:
                return image.convert("RGBA")
        except Exception as dib_error:
            # ANI의 일부 icon 청크는 ICO 내부 이미지 한 장만 담을 수 있습니다.
            try:
                with Image.open(io.BytesIO(b"\0\0\1\0\1\0" + blob)) as image:
                    return image.convert("RGBA")
            except Exception:
                raise ValueError("커서 프레임 이미지 형식을 읽지 못했습니다.") from dib_error


def _dib_as_bmp(blob: bytes) -> bytes:
    """CUR 내부의 DIB를 Pillow가 읽을 수 있는 BMP 컨테이너로 감싼다."""
    if len(blob) < 40:
        raise ValueError("DIB 헤더가 짧습니다.")
    header_size, width, height, planes, bits = struct.unpack_from("<IiiHH", blob, 0)
    if header_size < 40 or width <= 0 or height == 0 or planes != 1:
        raise ValueError("지원하지 않는 DIB입니다.")
    actual_height = abs(height) // 2
    dib = bytearray(blob)
    struct.pack_into("<i", dib, 8, actual_height if height > 0 else -actual_height)
    palette_size = ((1 << bits) * 4) if bits <= 8 else 0
    pixel_offset = 14 + header_size + palette_size
    return b"BM" + struct.pack("<IHHI", 14 + len(dib), 0, 0, pixel_offset) + bytes(dib)


def _load_cur(path: Path) -> tuple[list[Image.Image], list[tuple[int, int]]]:
    data = path.read_bytes()
    if data[:4] == b"RIFF":
        return _load_ani(data)
    if len(data) < 6:
        raise ValueError("CUR 파일 헤더가 올바르지 않습니다.")
    reserved, kind, count = struct.unpack_from("<HHH", data, 0)
    if reserved != 0 or kind != 2 or count <= 0:
        raise ValueError("CUR 파일 형식이 아닙니다.")
    frames, hotspots = [], []
    for index in range(count):
        offset = 6 + index * 16
        width, height, _colors, _reserved, hot_x, hot_y, size, image_offset = struct.unpack_from("<BBBBHHII", data, offset)
        blob = data[image_offset:image_offset + size]
        frames.append(_read_image(blob))
        hotspots.append((hot_x, hot_y))
    return frames, hotspots


def _load_ani(data: bytes) -> tuple[list[Image.Image], list[tuple[int, int]]]:
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"ACON":
        raise ValueError("ANI 파일 형식이 아닙니다.")
    frames: list[Image.Image] = []
    cursor = 12
    while cursor + 8 <= len(data):
        chunk_id = data[cursor:cursor + 4]
        size = struct.unpack_from("<I", data, cursor + 4)[0]
        payload = data[cursor + 8:cursor + 8 + size]
        cursor += 8 + size + (size % 2)
        if chunk_id == b"LIST" and payload[:4] == b"fram":
            inner = 4
            while inner + 8 <= len(payload):
                inner_id = payload[inner:inner + 4]
                inner_size = struct.unpack_from("<I", payload, inner + 4)[0]
                inner_payload = payload[inner + 8:inner + 8 + inner_size]
                inner += 8 + inner_size + (inner_size % 2)
                if inner_id == b"icon":
                    frames.append(_read_image(inner_payload))
    if not frames:
        raise ValueError("ANI에서 이미지 프레임을 찾지 못했습니다.")
    return frames, [(0, 0) for _ in frames]


def _png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def _ico_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="ICO")
    return buffer.getvalue()


def _save_cur(path: Path, frames: list[Image.Image], hotspots: list[tuple[int, int]]) -> None:
    blobs = [_png_bytes(frame) for frame in frames]
    directory = bytearray(struct.pack("<HHH", 0, 2, len(blobs)))
    offset = 6 + len(blobs) * 16
    for image, blob, hotspot in zip(frames, blobs, hotspots):
        width = 0 if image.width >= 256 else image.width
        height = 0 if image.height >= 256 else image.height
        hot_x, hot_y = hotspot
        directory.extend(struct.pack("<BBBBHHII", width, height, 0, 0, max(0, hot_x), max(0, hot_y), len(blob), offset))
        offset += len(blob)
    path.write_bytes(bytes(directory) + b"".join(blobs))


def _save_ani(path: Path, frames: list[Image.Image], delay_ms: int) -> None:
    icons = b"".join(_chunk(b"icon", _ico_bytes(frame)) for frame in frames)
    frame_list = b"LIST" + struct.pack("<I", len(b"fram" + icons)) + b"fram" + icons
    rate = max(1, round(delay_ms / 1000 * 60))
    anih = struct.pack("<9I", 36, len(frames), len(frames), 0, 0, 32, 1, rate, 1)
    body = _chunk(b"anih", anih) + _chunk(b"rate", struct.pack(f"<{len(frames)}I", *([rate] * len(frames)))) + frame_list
    path.write_bytes(b"RIFF" + struct.pack("<I", len(b"ACON" + body)) + b"ACON" + body)


class CursorEditor(tk.Frame):
    def __init__(self, parent: tk.Widget, app: object) -> None:
        super().__init__(parent, bg=palette(app.dark_mode)["panel"])
        self.app = app
        self.colors = palette(app.dark_mode)
        self.frames: list[Image.Image] = []
        self.hotspots: list[tuple[int, int]] = []
        self.source_path: Path | None = None
        self.current_index = 0
        self.preview: ImageTk.PhotoImage | None = None
        self.onion_preview: ImageTk.PhotoImage | None = None
        self.delay_ms = tk.IntVar(value=100)
        self.paint_color = tk.StringVar(value="#ff3b30")
        self.brush_size = tk.IntVar(value=2)
        self.fill_tolerance = tk.IntVar(value=10)
        self.paint_mode = tk.StringVar(value="붓")
        self.auto_cur_sizes = tk.BooleanVar(value=True)
        self.show_previous_frame = tk.BooleanVar(value=True)
        self._painting = False
        self._stroke_recorded = False
        self._undo_stack: list[tuple[int, Image.Image]] = []
        self._redo_stack: list[tuple[int, Image.Image]] = []
        self._preview_scale = 1.0
        self._preview_origin = (0, 0)
        self.status = tk.StringVar(value="CUR 또는 ANI 파일을 선택하세요.")
        self._destroyed = False
        self.bind_all("<Control-z>", self.undo, add="+")
        self.bind_all("<Control-y>", self.redo, add="+")
        self._build()

    def _build(self) -> None:
        colors = self.colors
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        header = tk.Frame(self, bg=colors["panel"])
        header.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 10))
        tk.Label(header, text="커서 편집기", font=("Segoe UI", 22, "bold"), fg=colors["text"], bg=colors["panel"]).pack(anchor="w")
        tk.Label(header, text="Python으로 CUR·ANI 프레임을 열고 수정한 뒤 다시 커서 파일로 저장합니다.", font=("Segoe UI", 10), fg=colors["muted"], bg=colors["panel"]).pack(anchor="w", pady=(3, 0))

        body = tk.Frame(self, bg=colors["panel"])
        body.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 18))
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)
        side = RoundedFrame(body, colors, colors["surface"], colors["border"], radius=16, padding=12)
        side.grid(row=0, column=0, sticky="ns", padx=(0, 10))
        preview_panel = RoundedFrame(body, colors, colors["surface"], colors["border"], radius=16, padding=14)
        preview_panel.grid(row=0, column=1, sticky="nsew")
        preview_panel.body.rowconfigure(0, weight=1)
        preview_panel.body.columnconfigure(0, weight=1)

        RoundedButton(side.body, "CUR / ANI 열기", self.open_file, colors, accent=True, compact=True, radius=9).pack(fill="x")
        self.frame_list = tk.Listbox(side.body, height=12, width=18, bg=colors["field"], fg=colors["text"], selectbackground=colors["accent_soft"], relief="flat", bd=0, activestyle="none")
        self.frame_list.pack(fill="both", expand=True, pady=(12, 8))
        self.frame_list.bind("<<ListboxSelect>>", self.select_frame)
        self.frame_info = tk.Label(side.body, text="프레임 없음", fg=colors["muted"], bg=colors["surface"], justify="left", anchor="w")
        self.frame_info.pack(fill="x")
        tk.Label(side.body, text="ANI 재생 간격(ms)", fg=colors["muted"], bg=colors["surface"]).pack(anchor="w", pady=(12, 3))
        tk.Spinbox(side.body, from_=10, to=5000, increment=10, textvariable=self.delay_ms, width=10, bg=colors["field"], fg=colors["text"], buttonbackground=colors["surface_hover"], relief="flat").pack(anchor="w")
        RoundedButton(side.body, "현재 프레임 적용", self.apply_adjustments, colors, compact=True, radius=9).pack(fill="x", pady=(14, 5))
        RoundedButton(side.body, "배경 자동 투명", self.remove_background, colors, compact=True, radius=9).pack(fill="x", pady=3)
        tk.Checkbutton(side.body, text="CUR 5개 해상도 자동 생성", variable=self.auto_cur_sizes, fg=colors["muted"], bg=colors["surface"], activebackground=colors["surface"], selectcolor=colors["field"], anchor="w").pack(fill="x", pady=(8, 0))
        tk.Checkbutton(side.body, text="이전 프레임 반투명 표시", variable=self.show_previous_frame, command=self.show_frame, fg=colors["muted"], bg=colors["surface"], activebackground=colors["surface"], selectcolor=colors["field"], anchor="w").pack(fill="x")
        RoundedButton(side.body, "CUR로 저장", lambda: self.save_file("cur"), colors, compact=True, radius=9).pack(fill="x", pady=3)
        RoundedButton(side.body, "ANI로 저장", lambda: self.save_file("ani"), colors, compact=True, radius=9).pack(fill="x", pady=3)

        self.preview_canvas = tk.Canvas(preview_panel.body, bg="#20252b", highlightthickness=0)
        self.preview_canvas.grid(row=0, column=0, sticky="nsew")
        self.preview_canvas.bind("<Configure>", lambda _event: self.show_frame())
        self.preview_canvas.bind("<ButtonPress-1>", self.paint_start)
        self.preview_canvas.bind("<B1-Motion>", self.paint_motion)
        self.preview_canvas.bind("<ButtonRelease-1>", lambda _event: setattr(self, "_painting", False))
        toolbar = tk.Frame(preview_panel.body, bg=colors["surface"])
        toolbar.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        for label, command in (("밝게", lambda: self.adjust("brightness", 1.15)), ("어둡게", lambda: self.adjust("brightness", 0.85)), ("대비+", lambda: self.adjust("contrast", 1.2)), ("회색", self.grayscale), ("좌우 반전", self.flip)):
            RoundedButton(toolbar, label, command, colors, compact=True, radius=8).pack(side="left", padx=(0, 5))
        paint_controls = tk.Frame(preview_panel.body, bg=colors["surface"])
        paint_controls.grid(row=2, column=0, sticky="ew", pady=(9, 0))
        tk.Label(paint_controls, text="그리기", fg=colors["muted"], bg=colors["surface"]).pack(side="left", padx=(0, 5))
        for mode in ("붓", "채우기"):
            tk.Radiobutton(paint_controls, text=mode, value=mode, variable=self.paint_mode, fg=colors["muted"], bg=colors["surface"], activebackground=colors["surface"], selectcolor=colors["field"], font=("Segoe UI", 8)).pack(side="left")
        RoundedButton(paint_controls, "색상", self.choose_color, colors, compact=True, radius=8).pack(side="left", padx=(8, 4))
        self.color_swatch = tk.Label(paint_controls, text="  ", bg=self.paint_color.get(), width=2)
        self.color_swatch.pack(side="left", padx=(0, 8))
        tk.Label(paint_controls, text="붓 크기", fg=colors["muted"], bg=colors["surface"]).pack(side="left")
        tk.Spinbox(paint_controls, from_=1, to=64, textvariable=self.brush_size, width=4, bg=colors["field"], fg=colors["text"], buttonbackground=colors["surface_hover"], relief="flat").pack(side="left", padx=(3, 8))
        tk.Label(paint_controls, text="채우기 허용 %", fg=colors["muted"], bg=colors["surface"]).pack(side="left")
        tk.Spinbox(paint_controls, from_=0, to=100, textvariable=self.fill_tolerance, width=4, bg=colors["field"], fg=colors["text"], buttonbackground=colors["surface_hover"], relief="flat").pack(side="left", padx=3)
        tk.Label(preview_panel.body, textvariable=self.status, fg=colors["muted"], bg=colors["surface"], anchor="w").grid(row=3, column=0, sticky="ew", pady=(10, 0))

    def open_file(self) -> None:
        filename = filedialog.askopenfilename(title="커서 파일 선택", filetypes=[("커서 파일", "*.cur *.ani"), ("모든 파일", "*.*")])
        if not filename:
            return
        try:
            self.frames, self.hotspots = _load_cur(Path(filename))
            self.source_path = Path(filename)
            self.current_index = 0
            self._undo_stack.clear()
            self._redo_stack.clear()
            self.frame_list.delete(0, "end")
            for index, frame in enumerate(self.frames, 1):
                self.frame_list.insert("end", f"프레임 {index}  {frame.width}x{frame.height}")
            self.frame_list.selection_set(0)
            self.show_frame()
            self.status.set(f"{len(self.frames)}개 프레임을 불러왔습니다.")
        except Exception as exc:
            messagebox.showerror("커서 편집기", f"파일을 열 수 없습니다.\n{exc}", parent=self)

    def select_frame(self, _event=None) -> None:
        selection = self.frame_list.curselection()
        if selection:
            self.current_index = selection[0]
            self.show_frame()

    def show_frame(self) -> None:
        if self._destroyed or not self.frames:
            return
        image = self.frames[self.current_index]
        width = max(80, self.preview_canvas.winfo_width() - 30)
        height = max(80, self.preview_canvas.winfo_height() - 30)
        self._preview_scale = min(width / image.width, height / image.height, 8.0)
        preview_size = (max(1, round(image.width * self._preview_scale)), max(1, round(image.height * self._preview_scale)))
        preview = image.resize(preview_size, Image.Resampling.NEAREST)
        self.preview = ImageTk.PhotoImage(preview)
        self.preview_canvas.delete("all")
        self._preview_origin = (
            (self.preview_canvas.winfo_width() - preview.width) // 2,
            (self.preview_canvas.winfo_height() - preview.height) // 2,
        )
        self.onion_preview = None
        if self.show_previous_frame.get() and self.current_index > 0:
            previous = self.frames[self.current_index - 1]
            previous_size = (max(1, round(previous.width * self._preview_scale)), max(1, round(previous.height * self._preview_scale)))
            ghost = previous.resize(previous_size, Image.Resampling.NEAREST).convert("RGBA")
            alpha = ghost.getchannel("A").point(lambda value: round(value * 0.32))
            ghost.putalpha(alpha)
            self.onion_preview = ImageTk.PhotoImage(ghost)
            ghost_origin = (
                (self.preview_canvas.winfo_width() - ghost.width) // 2,
                (self.preview_canvas.winfo_height() - ghost.height) // 2,
            )
            self.preview_canvas.create_image(*ghost_origin, image=self.onion_preview, anchor="nw")
        self.preview_canvas.create_image(*self._preview_origin, image=self.preview, anchor="nw")
        self.frame_info.configure(text=f"프레임 {self.current_index + 1}/{len(self.frames)}\n{image.width} x {image.height}px\n핫스팟: {self.hotspots[self.current_index]}")

    def choose_color(self) -> None:
        chosen = colorchooser.askcolor(color=self.paint_color.get(), title="칠할 색상 선택", parent=self)
        if chosen and chosen[1]:
            self.paint_color.set(chosen[1])
            self.color_swatch.configure(bg=chosen[1])

    def _canvas_to_image(self, event: tk.Event) -> tuple[int, int] | None:
        if not self.frames or self._preview_scale <= 0:
            return None
        image = self.frames[self.current_index]
        x = round((event.x - self._preview_origin[0]) / self._preview_scale)
        y = round((event.y - self._preview_origin[1]) / self._preview_scale)
        if 0 <= x < image.width and 0 <= y < image.height:
            return x, y
        return None

    def paint_start(self, event: tk.Event) -> None:
        if self.paint_mode.get() == "채우기":
            point = self._canvas_to_image(event)
            if point is not None:
                self._record_history()
                self._fill(point)
            return
        self._painting = True
        self._stroke_recorded = False
        self._paint(event)

    def paint_motion(self, event: tk.Event) -> None:
        if self._painting and self.paint_mode.get() == "붓":
            self._paint(event)

    def _paint(self, event: tk.Event) -> None:
        point = self._canvas_to_image(event)
        if point is None:
            return
        try:
            size = max(1, min(64, int(self.brush_size.get())))
            color = ImageColor.getcolor(self.paint_color.get(), "RGBA")
        except (tk.TclError, ValueError):
            return
        if not self._stroke_recorded:
            self._record_history()
            self._stroke_recorded = True
        draw = ImageDraw.Draw(self.frames[self.current_index], "RGBA")
        if size == 1:
            # ellipse의 0픽셀 반경은 Pillow 버전에 따라 표시되지 않을 수 있어 point를 사용한다.
            draw.point(point, fill=color)
        else:
            radius = max(1, size // 2)
            draw.ellipse((point[0] - radius, point[1] - radius, point[0] + radius, point[1] + radius), fill=color)
        self.show_frame()

    def _fill(self, point: tuple[int, int]) -> None:
        try:
            tolerance = max(0, min(100, int(self.fill_tolerance.get())))
        except (tk.TclError, ValueError):
            tolerance = 10
        try:
            color = ImageColor.getcolor(self.paint_color.get(), "RGBA")
        except ValueError:
            self.status.set("색상 값이 올바르지 않습니다.")
            return
        # Pillow는 RGB 채널 차이의 합을 사용하므로 0~100%를 0~1020 범위로 변환한다.
        ImageDraw.floodfill(
            self.frames[self.current_index],
            point,
            color,
            thresh=round(tolerance * 10.2),
        )
        self.show_frame()
        self.status.set(f"허용 오차 {tolerance}%로 비슷한 색 영역을 채웠습니다.")

    def adjust(self, kind: str, factor: float) -> None:
        if not self.frames:
            return
        self._record_history()
        image = self.frames[self.current_index]
        self.frames[self.current_index] = (ImageEnhance.Brightness(image).enhance(factor) if kind == "brightness" else ImageEnhance.Contrast(image).enhance(factor)).convert("RGBA")
        self.show_frame()
        self.status.set("현재 프레임에 수정 내용을 반영했습니다. 저장하면 파일에 기록됩니다.")

    def grayscale(self) -> None:
        if self.frames:
            self._record_history()
            self.frames[self.current_index] = ImageOps.grayscale(self.frames[self.current_index]).convert("RGBA")
            self.show_frame()

    def flip(self) -> None:
        if self.frames:
            self._record_history()
            self.frames[self.current_index] = ImageOps.mirror(self.frames[self.current_index])
            self.show_frame()

    def _record_history(self) -> None:
        if not self.frames:
            return
        self._undo_stack.append((self.current_index, self.frames[self.current_index].copy()))
        del self._undo_stack[:-100]
        self._redo_stack.clear()

    def undo(self, _event=None) -> str:
        if not self._undo_stack:
            return "break"
        index, previous = self._undo_stack.pop()
        self._redo_stack.append((index, self.frames[index].copy()))
        self.current_index = index
        self.frames[index] = previous
        self.frame_list.selection_clear(0, "end")
        self.frame_list.selection_set(index)
        self.show_frame()
        self.status.set("실행 취소")
        return "break"

    def redo(self, _event=None) -> str:
        if not self._redo_stack:
            return "break"
        index, next_image = self._redo_stack.pop()
        self._undo_stack.append((index, self.frames[index].copy()))
        self.current_index = index
        self.frames[index] = next_image
        self.frame_list.selection_clear(0, "end")
        self.frame_list.selection_set(index)
        self.show_frame()
        self.status.set("다시 실행")
        return "break"

    def apply_adjustments(self) -> None:
        self.status.set("현재 프레임은 이미 편집 내용이 적용된 상태입니다.")

    def remove_background(self) -> None:
        if not self.frames:
            return
        self._record_history()
        image = self.frames[self.current_index]
        try:
            tolerance = max(0, min(100, int(self.fill_tolerance.get())))
        except (tk.TclError, ValueError):
            tolerance = 10
        threshold = round(tolerance * 10.2)
        transparent = (0, 0, 0, 0)
        # 모서리 네 곳에서 시작해 캐릭터와 연결되지 않은 배경만 투명하게 만든다.
        for point in ((0, 0), (image.width - 1, 0), (0, image.height - 1), (image.width - 1, image.height - 1)):
            ImageDraw.floodfill(image, point, transparent, thresh=threshold)
        self.show_frame()
        self.status.set(f"모서리 배경을 자동 투명 처리했습니다. 허용 오차 {tolerance}%")

    def save_file(self, kind: str) -> None:
        if not self.frames:
            messagebox.showwarning("커서 편집기", "먼저 CUR 또는 ANI 파일을 여세요.", parent=self)
            return
        source = self.source_path or Path("cursor")
        filename = filedialog.asksaveasfilename(
            title="커서 파일 저장",
            defaultextension=f".{kind}",
            initialfile=f"{source.stem}_edited.{kind}",
            filetypes=[("CUR 파일", "*.cur"), ("ANI 파일", "*.ani")],
        )
        if not filename:
            return
        try:
            path = Path(filename)
            if kind == "cur":
                frames, hotspots = self._cur_output_frames()
                _save_cur(path, frames, hotspots)
            else:
                _save_ani(path, self.frames, max(10, int(self.delay_ms.get())))
            self.status.set(f"저장 완료: {path}")
        except Exception as exc:
            messagebox.showerror("커서 편집기", f"저장할 수 없습니다.\n{exc}", parent=self)

    def _cur_output_frames(self) -> tuple[list[Image.Image], list[tuple[int, int]]]:
        if not self.auto_cur_sizes.get():
            return self.frames, self.hotspots
        source = self.frames[self.current_index]
        source_hotspot = self.hotspots[self.current_index] if self.hotspots else (0, 0)
        sizes = (16, 24, 32, 48, 64)
        frames, hotspots = [], []
        for size in sizes:
            scale = min(size / source.width, size / source.height)
            width = max(1, round(source.width * scale))
            height = max(1, round(source.height * scale))
            resized = source.resize((width, height), Image.Resampling.LANCZOS)
            frame = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            offset = ((size - width) // 2, (size - height) // 2)
            frame.alpha_composite(resized, offset)
            frames.append(frame)
            hotspots.append((offset[0] + round(source_hotspot[0] * width / source.width), offset[1] + round(source_hotspot[1] * height / source.height)))
        return frames, hotspots

    def destroy(self) -> None:
        self._destroyed = True
        self.unbind_all("<Control-z>")
        self.unbind_all("<Control-y>")
        super().destroy()


def build(parent: tk.Widget, app: object) -> tk.Widget:
    return CursorEditor(parent, app)


def register(registry) -> None:
    registry.register(ToolSpec("files.cursor_editor", "CUR / ANI 커서 편집기", "파일", build, 12))
