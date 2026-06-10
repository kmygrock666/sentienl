"""UI 測試 conftest：確保 ui 套件路徑在測試中可用。"""

from __future__ import annotations

import sys
from pathlib import Path

# 專案根目錄（tests/ui/ 的上兩層）
_root = Path(__file__).parent.parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))
