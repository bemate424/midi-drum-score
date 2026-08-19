"""Step 4 - hand the MusicXML off to MuseScore 4 for PDF/PNG rendering."""

import os
import shutil
import subprocess

_DEFAULT_PATHS = [
    # Windows
    r"C:\Program Files\MuseScore 4\bin\MuseScore4.exe",
    r"C:\Program Files\MuseScore 3\bin\MuseScore3.exe",
    # macOS
    "/Applications/MuseScore 4.app/Contents/MacOS/mscore",
    "/Applications/MuseScore 3.app/Contents/MacOS/mscore",
    # Linux (native package / manual install)
    "/usr/bin/musescore4",
    "/usr/bin/mscore4",
    "/usr/bin/musescore3",
    "/usr/bin/mscore3",
    "/usr/bin/musescore",
    "/usr/bin/mscore",
    "/usr/local/bin/musescore4",
    "/usr/local/bin/mscore",
    # Linux (Snap / Flatpak)
    "/snap/bin/musescore",
    "/var/lib/flatpak/exports/bin/org.musescore.MuseScore",
]


def find_musescore_executable() -> str:
    env_path = os.environ.get("MUSESCORE_PATH")
    if env_path and os.path.isfile(env_path):
        return env_path

    for path in _DEFAULT_PATHS:
        if os.path.isfile(path):
            return path

    for name in ("MuseScore4.exe", "mscore.exe", "musescore4", "musescore3", "musescore", "mscore"):
        found = shutil.which(name)
        if found:
            return found

    raise FileNotFoundError(
        "MuseScore 실행 파일을 찾을 수 없습니다. MUSESCORE_PATH 환경 변수로 경로를 지정하세요."
    )


def render_musicxml(musicxml_path: str, output_path: str, musescore_exe: str | None = None) -> str:
    """Renders a .musicxml file to .pdf or .png via MuseScore's CLI mode."""
    exe = musescore_exe or find_musescore_executable()
    result = subprocess.run(
        [exe, "-o", output_path, musicxml_path],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0 or not os.path.isfile(output_path):
        raise RuntimeError(
            f"MuseScore 렌더링 실패 (exit {result.returncode})\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return output_path
