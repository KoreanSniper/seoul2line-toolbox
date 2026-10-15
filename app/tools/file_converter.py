from __future__ import annotations

import json
import shutil
import subprocess
import tarfile
import threading
import tkinter as tk
import zipfile
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from xml.etree import ElementTree

from app.palette import palette
from app.tool_registry import ToolSpec
from app.ui import RoundedButton, RoundedFrame


FORMAT_GROUPS = {
    "이미지": ("png", "jpg", "jpeg", "webp", "gif", "bmp", "tiff", "tif", "ico", "svg", "avif", "heic", "heif"),
    "동영상": ("mp4", "mkv", "avi", "mov", "webm", "wmv", "flv", "m4v", "mpeg", "mpg", "3gp", "ts", "mts"),
    "음성": ("mp3", "wav", "flac", "ogg", "opus", "aac", "m4a", "wma", "aiff", "alac"),
    "문서": ("txt", "pdf", "doc", "docx", "odt", "rtf", "html", "htm", "md", "epub"),
    "데이터": ("csv", "tsv", "json", "xml", "yaml", "yml", "toml", "ini", "sql"),
    "스프레드시트": ("xls", "xlsx", "ods"),
    "압축": ("zip", "7z", "tar", "gz", "bz2", "xz", "tar.gz", "tar.bz2", "tar.xz", "rar"),
    "코드": ("py", "js", "ts", "html", "css", "json", "xml", "yaml", "yml", "c", "cpp", "h", "java", "cs", "go", "rs", "php", "sh", "bat", "ps1"),
    "설치·디스크": ("exe", "msi", "appx", "deb", "rpm", "apk", "iso", "img", "bin", "vhd", "vhdx", "vdi", "vmdk", "ova", "ovf"),
}
FORMATS = tuple(dict.fromkeys(ext for values in FORMAT_GROUPS.values() for ext in values))
IMAGE_FORMATS = set(FORMAT_GROUPS["이미지"])
VIDEO_FORMATS = set(FORMAT_GROUPS["동영상"])
AUDIO_FORMATS = set(FORMAT_GROUPS["음성"])
ARCHIVE_FORMATS = set(FORMAT_GROUPS["압축"])
TEXT_FORMATS = set(FORMAT_GROUPS["데이터"] + FORMAT_GROUPS["코드"] + ("txt", "md", "html", "htm", "sql", "ini", "rtf"))


def _extension(path: Path) -> str:
    name = path.name.lower()
    for suffix in (".tar.gz", ".tar.bz2", ".tar.xz"):
        if name.endswith(suffix):
            return suffix[1:]
    return path.suffix.lower().lstrip(".")


class FileConverter(tk.Frame):
    def __init__(self, parent: tk.Widget, app: object) -> None:
        super().__init__(parent, bg=palette(app.dark_mode)["panel"])
        self.app = app
        self.colors = palette(app.dark_mode)
        self.source = tk.StringVar()
        self.target_format = tk.StringVar(value="png")
        self.output = tk.StringVar()
        self.status = tk.StringVar(value="변환할 파일을 선택하세요.")
        self.running = False
        self._destroyed = False
        self._build()

    def _build(self) -> None:
        colors = self.colors
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        header = tk.Frame(self, bg=colors["panel"])
        header.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 10))
        tk.Label(header, text="파일 형식 변환", font=("Segoe UI", 22, "bold"), fg=colors["text"], bg=colors["panel"]).pack(anchor="w")
        tk.Label(header, text="이미지·미디어·문서·데이터·압축 파일을 환경에 맞는 변환 엔진으로 처리합니다.", font=("Segoe UI", 10), fg=colors["muted"], bg=colors["panel"]).pack(anchor="w", pady=(3, 0))

        controls = RoundedFrame(self, colors, colors["surface"], colors["border"], radius=16, padding=14)
        controls.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 10))
        controls.body.columnconfigure(1, weight=1)
        tk.Label(controls.body, text="원본 파일", fg=colors["muted"], bg=colors["surface"]).grid(row=0, column=0, sticky="w", padx=(0, 10), pady=5)
        tk.Entry(controls.body, textvariable=self.source, bg=colors["field"], fg=colors["text"], insertbackground=colors["accent"], relief="flat", bd=0).grid(row=0, column=1, sticky="ew", ipady=7, pady=5)
        RoundedButton(controls.body, "찾기", self.choose_source, colors, compact=True, radius=9).grid(row=0, column=2, padx=(8, 0), pady=5)
        tk.Label(controls.body, text="변환 형식", fg=colors["muted"], bg=colors["surface"]).grid(row=1, column=0, sticky="w", padx=(0, 10), pady=5)
        self.format_box = ttk.Combobox(controls.body, textvariable=self.target_format, values=FORMATS, state="readonly", width=16)
        self.format_box.grid(row=1, column=1, sticky="w", pady=5)
        self.format_box.bind("<<ComboboxSelected>>", lambda _event: self._update_output())
        RoundedButton(controls.body, "변환", self.convert, colors, accent=True, compact=True, radius=9).grid(row=1, column=2, padx=(8, 0), pady=5)
        tk.Label(controls.body, text="저장 경로", fg=colors["muted"], bg=colors["surface"]).grid(row=2, column=0, sticky="w", padx=(0, 10), pady=5)
        tk.Entry(controls.body, textvariable=self.output, bg=colors["field"], fg=colors["text"], insertbackground=colors["accent"], relief="flat", bd=0).grid(row=2, column=1, sticky="ew", ipady=7, pady=5)
        RoundedButton(controls.body, "경로 선택", self.choose_output, colors, compact=True, radius=9).grid(row=2, column=2, padx=(8, 0), pady=5)

        body = RoundedFrame(self, colors, colors["surface"], colors["border"], radius=16, padding=14)
        body.grid(row=2, column=0, sticky="nsew", padx=18, pady=(0, 18))
        tk.Label(body.body, textvariable=self.status, fg=colors["muted"], bg=colors["surface"], justify="left", anchor="w", wraplength=850).pack(fill="x")
        tk.Label(body.body, text=self._backend_summary(), fg=colors["subtle"], bg=colors["surface"], justify="left", anchor="nw", wraplength=850).pack(fill="both", expand=True, pady=(14, 0))

    def _backend_summary(self) -> str:
        ffmpeg = "사용 가능" if shutil.which("ffmpeg") else "없음"
        seven_zip = "사용 가능" if shutil.which("7z") or shutil.which("7zz") else "없음"
        libreoffice = "사용 가능" if shutil.which("soffice") or shutil.which("libreoffice") else "없음"
        return (
            f"내장: 텍스트·JSON·XML·ZIP·TAR 계열 / Pillow: 일반 이미지\n"
            f"FFmpeg: {ffmpeg} (동영상·음성) | 7-Zip: {seven_zip} (7Z·RAR) | LibreOffice: {libreoffice} (문서·스프레드시트)\n"
            "지원되지 않는 코덱이나 실행 파일·디스크 이미지 변환은 원본을 훼손하지 않고 오류로 안내합니다."
        )

    def choose_source(self) -> None:
        path = filedialog.askopenfilename(title="변환할 파일 선택", filetypes=[("지원 형식", "*.*")])
        if path:
            self.source.set(path)
            source_ext = _extension(Path(path))
            if source_ext in FORMATS:
                for candidate in FORMATS:
                    if candidate != source_ext and (candidate in IMAGE_FORMATS) == (source_ext in IMAGE_FORMATS):
                        self.target_format.set(candidate)
                        break
            self._update_output()

    def choose_output(self) -> None:
        path = filedialog.asksaveasfilename(title="변환 결과 저장", defaultextension=f".{self.target_format.get()}")
        if path:
            self.output.set(path)

    def _update_output(self) -> None:
        source = Path(self.source.get())
        if source.name:
            self.output.set(str(source.with_name(f"{source.stem}.{self.target_format.get()}")))

    def convert(self) -> None:
        if self.running or self._destroyed:
            return
        source = Path(self.source.get()).expanduser()
        target = Path(self.output.get()).expanduser()
        if not source.is_file():
            messagebox.showwarning("파일 형식 변환", "원본 파일을 선택하세요.", parent=self)
            return
        if not target.name:
            self._update_output()
            target = Path(self.output.get()).expanduser()
        if source.resolve() == target.resolve():
            messagebox.showwarning("파일 형식 변환", "원본과 다른 저장 경로를 선택하세요.", parent=self)
            return
        self.running = True
        self.status.set("변환 중...")
        threading.Thread(target=self._worker, args=(source, target), daemon=True).start()

    def _worker(self, source: Path, target: Path) -> None:
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            self._convert_file(source, target)
            message = f"변환 완료\n{target}"
            ok = True
        except Exception as exc:
            message = f"변환 실패\n{type(exc).__name__}: {exc}"
            ok = False
        if self._destroyed:
            return
        try:
            self.after(0, lambda: self._finish(message, ok))
        except tk.TclError:
            return

    def _finish(self, message: str, ok: bool) -> None:
        if self._destroyed:
            return
        self.running = False
        self.status.set(message)
        if ok:
            messagebox.showinfo("파일 형식 변환", message, parent=self)
        else:
            messagebox.showerror("파일 형식 변환", message, parent=self)

    def _convert_file(self, source: Path, target: Path) -> None:
        source_ext, target_ext = _extension(source), _extension(target)
        if source_ext == target_ext:
            shutil.copy2(source, target)
            return
        if source_ext in IMAGE_FORMATS and target_ext in IMAGE_FORMATS:
            self._convert_image(source, target, target_ext)
        elif (source_ext in VIDEO_FORMATS and target_ext in VIDEO_FORMATS) or (source_ext in AUDIO_FORMATS and target_ext in AUDIO_FORMATS):
            self._run_external_media(source, target)
        elif source_ext in ARCHIVE_FORMATS and target_ext in ARCHIVE_FORMATS:
            self._convert_archive(source, target, target_ext)
        elif source_ext in TEXT_FORMATS and target_ext in TEXT_FORMATS:
            self._convert_text(source, target, source_ext, target_ext)
        elif source_ext in FORMAT_GROUPS["문서"] + FORMAT_GROUPS["스프레드시트"] and target_ext in FORMAT_GROUPS["문서"] + FORMAT_GROUPS["스프레드시트"]:
            self._run_office(source, target)
        else:
            raise RuntimeError(f"{source_ext.upper()} → {target_ext.upper()} 변환은 지원되지 않습니다.")

    @staticmethod
    def _convert_image(source: Path, target: Path, target_ext: str) -> None:
        from app.services.images import convert_image
        convert_image(source, target, target_ext)

    @staticmethod
    def _run_external_media(source: Path, target: Path) -> None:
        executable = shutil.which("ffmpeg")
        if not executable:
            raise RuntimeError("동영상·음성 변환에는 FFmpeg가 필요합니다.")
        subprocess.run([executable, "-y", "-i", str(source), str(target)], check=True, capture_output=True, text=True, encoding="utf-8", errors="replace")

    @staticmethod
    def _convert_archive(source: Path, target: Path, target_ext: str) -> None:
        if source.suffix.lower() == ".zip" and target_ext == "zip":
            shutil.copy2(source, target)
            return
        if target_ext == "zip":
            with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.write(source, source.name)
            return
        if target_ext in {"tar", "tar.gz", "tar.bz2", "tar.xz"}:
            mode = {"tar": "w", "tar.gz": "w:gz", "tar.bz2": "w:bz2", "tar.xz": "w:xz"}[target_ext]
            with tarfile.open(target, mode) as archive:
                archive.add(source, arcname=source.name)
            return
        executable = shutil.which("7z") or shutil.which("7zz")
        if not executable:
            raise RuntimeError("7Z/RAR 변환에는 7-Zip이 필요합니다.")
        subprocess.run([executable, "a", "-y", str(target), str(source)], check=True, capture_output=True, text=True, encoding="utf-8", errors="replace")

    @staticmethod
    def _convert_text(source: Path, target: Path, source_ext: str, target_ext: str) -> None:
        text = source.read_text(encoding="utf-8-sig")
        if target_ext == "json":
            value = json.loads(text)
            text = json.dumps(value, ensure_ascii=False, indent=2)
        elif target_ext == "xml":
            root = ElementTree.fromstring(text)
            text = ElementTree.tostring(root, encoding="unicode")
        target.write_text(text, encoding="utf-8")

    @staticmethod
    def _run_office(source: Path, target: Path) -> None:
        executable = shutil.which("soffice") or shutil.which("libreoffice")
        if not executable:
            raise RuntimeError("DOC/DOCX/PDF/XLS/XLSX 변환에는 LibreOffice가 필요합니다.")
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([executable, "--headless", "--convert-to", _extension(target), "--outdir", str(target.parent), str(source)], check=True, capture_output=True, text=True, encoding="utf-8", errors="replace")

    def destroy(self) -> None:
        self._destroyed = True
        super().destroy()


def build(parent: tk.Widget, app: object) -> tk.Widget:
    return FileConverter(parent, app)


def register(registry) -> None:
    registry.register(ToolSpec("files.converter", "파일 형식 변환", "파일", build, 10))
