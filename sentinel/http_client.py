from __future__ import annotations

import math
import subprocess
from typing import Mapping, Optional
from urllib.parse import urlencode

import requests


def fetch_text(
    url: str,
    *,
    params: Optional[Mapping[str, object]] = None,
    headers: Optional[Mapping[str, str]] = None,
    timeout_seconds: float = 20.0,
) -> str:
    try:
        response = requests.get(
            url,
            params=params,
            headers=dict(headers or {}),
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        return _decode_payload(response.content)
    except requests.RequestException:
        return _fetch_text_with_curl(
            url=url,
            params=params,
            headers=headers,
            timeout_seconds=timeout_seconds,
        )


def _fetch_text_with_curl(
    *,
    url: str,
    params: Optional[Mapping[str, object]],
    headers: Optional[Mapping[str, str]],
    timeout_seconds: float,
) -> str:
    full_url = url
    if params:
        query = urlencode([(key, value) for key, value in params.items()])
        separator = "&" if "?" in url else "?"
        full_url = "{0}{1}{2}".format(url, separator, query)

    command = [
        "curl",
        "-L",
        "-sS",
        "--max-time",
        str(max(1, int(math.ceil(timeout_seconds)))),
        "--tlsv1.2",
    ]

    user_agent = (headers or {}).get("User-Agent")
    if user_agent:
        command.extend(["-A", user_agent])
    
    # Add common browser-like headers to reduce likelihood of being blocked
    command.extend([
        "-H", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "-H", "Accept-Language: zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "-H", "Cache-Control: no-cache",
        "-H", "Pragma: no-cache",
        "-H", "Sec-Fetch-Dest: document",
        "-H", "Sec-Fetch-Mode: navigate",
        "-H", "Sec-Fetch-Site: none",
        "-H", "Sec-Fetch-User: ?1",
        "-H", "Upgrade-Insecure-Requests: 1",
    ])
    
    # Add Referer if it's TPEX to look more like a browser navigation
    if "tpex.org.tw" in url:
        command.extend(["-H", "Referer: https://www.tpex.org.tw/web/stock/aftertrading/daily_close_quotes/stk_quote.php?l=zh-tw"])

    command.append(full_url)

    completed = subprocess.run(
        command,
        check=True,
        capture_output=True,
    )
    return _decode_payload(completed.stdout)


def _decode_payload(payload: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig", "cp950", "big5", "big5hkscs"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    return payload.decode("utf-8", errors="replace")
