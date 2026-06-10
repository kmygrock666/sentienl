from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)


class MISFetcher:
    """
    Fetcher for Taiwan Stock Exchange MIS API (mis.twse.com.tw).
    Handles session maintenance and batch requests.
    """

    HOME_URL = "https://mis.twse.com.tw/stock/index.jsp"
    API_URL = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"

    def __init__(self, timeout: int = 10):
        self.session = requests.Session()
        self.timeout = timeout
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
        )
        self._initialized = False

    def _ensure_session(self):
        """Visit home page to get required cookies."""
        if not self._initialized:
            try:
                self.session.get(self.HOME_URL, timeout=self.timeout)
                self._initialized = True
                logger.info("MIS session initialized.")
            except Exception as e:
                logger.error(f"Failed to initialize MIS session: {e}")
                raise

    def fetch_batch(
        self, symbols: List[str], markets: List[str], max_retries: int = 3
    ) -> List[Dict[str, Any]]:
        """
        Fetch real-time data for a list of symbols with retry logic.
        """
        self._ensure_session()

        # Build query string: tse_2330.tw|otc_6547.tw
        ex_ch_list = []
        for symbol, market in zip(symbols, markets):
            prefix = "tse" if market == "TWSE" else "otc"
            ex_ch_list.append(f"{prefix}_{symbol}.tw")

        ex_ch = "|".join(ex_ch_list)
        params = {"ex_ch": ex_ch, "json": 1, "delay": 0, "_": int(time.time() * 1000)}

        for attempt in range(max_retries):
            try:
                response = self.session.get(self.API_URL, params=params, timeout=self.timeout)
                response.raise_for_status()

                # Check if it's actually JSON before parsing
                # Note: TWSE MIS sometimes returns 'text/html;charset=UTF-8' even for valid JSON.
                content_type = response.headers.get("Content-Type", "")
                is_json = "application/json" in content_type or "text/javascript" in content_type
                is_html = "text/html" in content_type

                if not (is_json or is_html):
                    raise ValueError(f"Unexpected Content-Type: {content_type}")

                try:
                    data = response.json()
                except ValueError:
                    if is_html:
                        logger.error(
                            f"MIS API returned real HTML instead of JSON. Body snippet: {response.text[:200]}"
                        )
                    raise

                if "msgArray" in data:
                    return data["msgArray"]
                else:
                    logger.warning(
                        f"MIS API returned no data (Attempt {attempt+1}): {ex_ch[:50]}..."
                    )
                    if attempt < max_retries - 1:
                        time.sleep(2)
                        continue
                    return []
            except Exception as e:
                logger.error(f"Error fetching MIS data (Attempt {attempt+1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 * (attempt + 1))  # Exponential backoff
                    continue
                return []
        return []

    def fetch_all(
        self, symbols: List[str], markets: List[str], batch_size: int = 50
    ) -> List[Dict[str, Any]]:
        """Fetch all symbols in batches of batch_size."""
        all_results = []
        for i in range(0, len(symbols), batch_size):
            batch_syms = symbols[i : i + batch_size]
            batch_mkts = markets[i : i + batch_size]

            logger.info(f"Fetching MIS batch {i//batch_size + 1} ({len(batch_syms)} stocks)...")
            results = self.fetch_batch(batch_syms, batch_mkts)
            all_results.extend(results)

            if i + batch_size < len(symbols):
                time.sleep(2)  # Increased from 1s to be more conservative

        return all_results


def parse_mis_data(msg: Dict[str, Any]) -> Dict[str, Any]:
    """Parse raw MIS message into a cleaner dictionary."""

    def to_float(val: Any) -> float:
        try:
            return float(val) if val and val != "-" else 0.0
        except ValueError:
            return 0.0

    def to_int(val: Any) -> int:
        try:
            return int(val) if val and val != "-" else 0
        except ValueError:
            return 0

    raw_close = msg.get("z", "-")
    prev_close = to_float(msg.get("y"))

    # Price Fallback Logic:
    # If last trade price (z) is missing ('-'), try to use:
    # 1. Best bid price (b)
    # 2. Opening price (o)
    # 3. Previous close (y)
    close = to_float(raw_close)
    if close == 0.0:
        bid_price = to_float(msg.get("b", "").split("_")[0])
        if bid_price > 0:
            close = bid_price
        else:
            open_price = to_float(msg.get("o"))
            close = open_price if open_price > 0 else prev_close

    return {
        "symbol": msg.get("c"),
        "name": msg.get("n"),
        "market": "TWSE" if msg.get("ex") == "tse" else "TPEX",
        "open": to_float(msg.get("o")),
        "high": to_float(msg.get("h")),
        "low": to_float(msg.get("l")),
        "close": close,
        "prev_close": prev_close,
        "volume": to_int(msg.get("v")) * 1000,  # MIS uses lots (1000 shares), DB uses shares
        "last_trade_volume": to_int(msg.get("tv")),
        "limit_up": to_float(msg.get("u")),
        "limit_down": to_float(msg.get("w")),
        # Best bid volumes is 'g', prices is 'b' (comma separated)
        "best_bid_price": msg.get("b", "").split("_")[0] if msg.get("b") else "-",
        "best_bid_volume": msg.get("g", "").split("_")[0] if msg.get("g") else "-",
        "timestamp": msg.get("t"),
    }
