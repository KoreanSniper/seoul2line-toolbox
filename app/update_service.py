from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from urllib.parse import urlparse

from app.version import INSTALLER_NAME, REPOSITORY, VERSION


API_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
MAX_INSTALLER_SIZE = 512 * 1024 * 1024
ALLOWED_HOSTS = {"api.github.com", "github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com", "github-releases.githubusercontent.com"}


def version_tuple(value: str) -> tuple[int, int, int]:
    if not isinstance(value, str) or not re.fullmatch(r"v?\d{1,5}\.\d{1,5}\.\d{1,5}", value):
        raise ValueError("올바르지 않은 배포 버전입니다.")
    return tuple(int(part) for part in value.removeprefix("v").split("."))


def open_response(url: str):
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS or parsed.username or parsed.password:
        raise ValueError("허용되지 않은 업데이트 주소입니다.")
    request = urllib.request.Request(url, headers={"User-Agent": f"seoul2line-Toolbox/{VERSION}", "Accept": "application/json" if url == API_URL else "application/octet-stream"})
    response = urllib.request.urlopen(request, timeout=30)
    final = urlparse(response.geturl())
    if final.scheme != "https" or final.hostname not in ALLOWED_HOSTS:
        response.close()
        raise ValueError("허용되지 않은 다운로드 리디렉션입니다.")
    return response


def read_json(url: str) -> dict:
    with open_response(url) as response:
        raw = response.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ValueError("업데이트 정보가 너무 큽니다.")
    result = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(result, dict):
        raise ValueError("업데이트 정보 형식이 잘못되었습니다.")
    return result


@dataclass(frozen=True)
class Release:
    version: str
    url: str
    sha256: str
    size: int
    page_url: str


def check_latest(current: str = VERSION) -> Release | None:
    try:
        release = read_json(API_URL)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    tag = release.get("tag_name", "")
    if release.get("draft") or release.get("prerelease") or version_tuple(tag) <= version_tuple(current):
        return None
    base = f"https://github.com/{REPOSITORY}/releases/download/{tag}/"
    assets = {item["name"]: item for item in release.get("assets", [])}
    for name in (INSTALLER_NAME, "update.json"):
        if name not in assets or assets[name].get("browser_download_url") != base + name:
            raise ValueError("릴리스에 검증 가능한 설치 파일과 update.json이 없습니다.")
    manifest = read_json(base + "update.json")
    if manifest.get("version") != tag.removeprefix("v") or manifest.get("installer") != INSTALLER_NAME:
        raise ValueError("설치 파일 버전이 릴리스와 일치하지 않습니다.")
    checksum, size = manifest.get("sha256", ""), manifest.get("size")
    if not isinstance(checksum, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", checksum):
        raise ValueError("설치 파일 체크섬이 잘못되었습니다.")
    if type(size) is not int or not 0 < size <= MAX_INSTALLER_SIZE or assets[INSTALLER_NAME].get("size") != size:
        raise ValueError("설치 파일 크기가 잘못되었습니다.")
    return Release(tag.removeprefix("v"), base + INSTALLER_NAME, checksum.lower(), size,
                   f"https://github.com/{REPOSITORY}/releases/tag/{tag}")


def download_release(release: Release, directory: Path) -> Path:
    version_tuple(release.version)
    if type(release.size) is not int or not 0 < release.size <= MAX_INSTALLER_SIZE or not re.fullmatch(r"[0-9a-f]{64}", release.sha256):
        raise ValueError("설치 파일 검증 정보가 잘못되었습니다.")
    expected = f"https://github.com/{REPOSITORY}/releases/download/v{release.version}/{INSTALLER_NAME}"
    if release.url != expected:
        raise ValueError("설치 파일은 지정 저장소의 버전 릴리스에서만 받을 수 있습니다.")
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"setup-{release.version}.exe"
    temporary = destination.with_suffix(".part")
    try:
        digest, total = hashlib.sha256(), 0
        with open_response(release.url) as response, temporary.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > release.size or total > MAX_INSTALLER_SIZE:
                    raise ValueError("설치 파일이 예상 크기를 초과했습니다.")
                output.write(chunk)
                digest.update(chunk)
        if total != release.size or digest.hexdigest() != release.sha256:
            raise ValueError("설치 파일 검증에 실패했습니다. 다시 다운로드하세요.")
        os.replace(temporary, destination)
        return destination
    finally:
        temporary.unlink(missing_ok=True)


def launch_installer(installer: Path, release: Release, directory: Path) -> subprocess.Popen:
    if not getattr(sys, "frozen", False):
        raise ValueError("자동 설치는 설치본에서만 사용할 수 있습니다.")
    bundled = Path(sys._MEIPASS) / "updater" / "install_update.ps1"
    helper = directory / "install_update.ps1"
    shutil.copyfile(bundled, helper)
    return subprocess.Popen([
        "powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
        "-File", str(helper), "-Installer", str(installer), "-AppExe", sys.executable,
        "-ParentProcessId", str(os.getpid()), "-Sha256", release.sha256,
    ], creationflags=subprocess.CREATE_NO_WINDOW)
