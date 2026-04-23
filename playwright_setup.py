"""Streamlit Cloud 같은 무상태 환경에서 앱 첫 실행 시 Chromium을 설치한다.

로컬에서는 `python -m playwright install chromium`을 미리 쳤다면 스킵된다.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_SENTINEL = Path.home() / ".cache" / "playwright_chromium_ready"


def ensure_chromium_installed() -> None:
    if _SENTINEL.exists():
        return
    try:
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            check=False,
            timeout=300,
            env={**os.environ, "PLAYWRIGHT_BROWSERS_PATH": str(Path.home() / ".cache" / "ms-playwright")},
        )
        _SENTINEL.parent.mkdir(parents=True, exist_ok=True)
        _SENTINEL.touch()
    except Exception:
        pass
