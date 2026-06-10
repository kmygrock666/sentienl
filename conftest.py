"""根目錄 conftest：確保 ui 套件可在測試中被引入。"""
from __future__ import annotations

import sys
from pathlib import Path

# 讓 ui.* 在測試中可被引入（與 sentinel.* 同層）
sys.path.insert(0, str(Path(__file__).parent))
