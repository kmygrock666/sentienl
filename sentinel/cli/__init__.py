"""CLI 介面層：只負責參數解析與結果呈現，業務邏輯委派給 sentinel.services。"""

from sentinel.cli.main import build_parser, main

__all__ = ["build_parser", "main"]
