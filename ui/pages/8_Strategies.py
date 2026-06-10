"""Strategies — 策略管理頁面（Phase B，唯讀 + is_active 切換）。"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))

import json
import shutil

import streamlit as st

from ui.components.layout import inject_css, section_header

st.set_page_config(page_title="Strategies | Sentinel", layout="wide")
inject_css()
st.title("⚙️ Strategies")
st.caption("策略啟停管理（唯讀 + is_active 切換；寫入前自動備份 .bak）")

_STRAT_PATH = pathlib.Path(__file__).parent.parent.parent / "config" / "strategies.json"

# ── 讀取 ────────────────────────────────────────────────────────────────────

def _load_raw() -> dict:
    """載入原始 JSON dict。"""
    if not _STRAT_PATH.exists():
        return {}
    try:
        return json.loads(_STRAT_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        st.error(f"讀取 strategies.json 失敗：{e}")
        return {}


def _flat_list(raw: dict) -> list[dict]:
    """把 long_strategies / short_strategies 攤平，加上 direction 鍵。"""
    result = []
    for direction in ("long", "short"):
        for s in raw.get(f"{direction}_strategies", []):
            result.append({**s, "_direction": direction})
    return result


def _save_raw(raw: dict) -> bool:
    """先備份再寫入。"""
    bak = _STRAT_PATH.with_suffix(".json.bak")
    if _STRAT_PATH.exists():
        shutil.copy2(_STRAT_PATH, bak)
    try:
        _STRAT_PATH.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception as e:
        st.error(f"寫入失敗，嘗試還原備份：{e}")
        if bak.exists():
            shutil.copy2(bak, _STRAT_PATH)
        return False

# ── 主體 ────────────────────────────────────────────────────────────────────

raw = _load_raw()
strategies = _flat_list(raw)

if not strategies:
    st.warning(f"未找到策略（路徑：`{_STRAT_PATH}`）")
    st.stop()

section_header("策略總覽", f"設定檔：`{_STRAT_PATH}` ｜ 共 {len(strategies)} 個策略")

# 彙總指標
long_cnt = sum(1 for s in strategies if s["_direction"] == "long")
short_cnt = sum(1 for s in strategies if s["_direction"] == "short")
active_cnt = sum(1 for s in strategies if s.get("is_active", True))
m1, m2, m3 = st.columns(3)
m1.metric("做多策略", long_cnt)
m2.metric("做空策略", short_cnt)
m3.metric("啟用中", active_cnt)

st.divider()

# 逐策略 is_active 切換
section_header("啟停控制")
direction_filter = st.radio("顯示方向", ["全部", "long", "short"], horizontal=True)
filtered = strategies if direction_filter == "全部" else [s for s in strategies if s["_direction"] == direction_filter]

# 記錄新的 is_active 狀態
new_states: dict[str, bool] = {}
for s in filtered:
    sid = s["strategy_id"]
    col1, col2, col3, col4 = st.columns([1, 3, 3, 1])
    new_states[sid] = col1.checkbox(
        "啟用",
        value=bool(s.get("is_active", True)),
        key=f"active_{sid}",
    )
    col2.markdown(f"**{sid}**")
    col3.caption(s.get("name") or s.get("description") or "—")
    badge_color = "#D84B4B" if s["_direction"] == "long" else "#3FA66B"
    col4.markdown(
        f'<span style="color:{badge_color};font-weight:600;font-size:0.8rem">{s["_direction"].upper()}</span>',
        unsafe_allow_html=True,
    )

# 偵測是否有變更
any_changed = any(
    new_states.get(s["strategy_id"]) != bool(s.get("is_active", True))
    for s in filtered
)

if any_changed:
    if st.button("💾 儲存變更", type="primary"):
        # 更新 raw dict
        for direction in ("long", "short"):
            key = f"{direction}_strategies"
            for item in raw.get(key, []):
                sid = item["strategy_id"]
                if sid in new_states:
                    item["is_active"] = new_states[sid]
        ok = _save_raw(raw)
        if ok:
            st.success("✅ 已儲存，備份為 .bak")
        st.rerun()
else:
    st.info("尚未變更任何設定")

st.divider()

# 策略詳細（唯讀）
section_header("策略詳細（唯讀）")
all_ids = [s["strategy_id"] for s in strategies]
if all_ids:
    sel_id = st.selectbox("選擇策略", all_ids)
    sel = next((s for s in strategies if s["strategy_id"] == sel_id), None)
    if sel:
        # 移除 _direction 輔助鍵再顯示
        display = {k: v for k, v in sel.items() if k != "_direction"}
        st.json(display)
