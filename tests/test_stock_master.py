from __future__ import annotations

import requests

from sentinel.config import Settings
from sentinel.datasources.stock_master import (
    TpexStockMasterProvider,
    TwseStockMasterProvider,
    build_stock_master_provider_registry,
    fetch_stock_master,
    fetch_stock_master_with_diagnostics,
    load_stock_master,
    save_stock_master_diagnostics,
    upsert_stock_master,
)


def test_load_stock_master_normalizes_market_and_status(tmp_path) -> None:
    dataset_path = tmp_path / "stocks.csv"
    dataset_path.write_text(
        "\n".join(
            [
                "symbol,name,market,industry,list_status,source",
                "2330,TSMC,twse,Semiconductor,ACTIVE,fixture",
            ]
        ),
        encoding="utf-8",
    )

    loaded = load_stock_master(dataset_path)

    assert loaded.iloc[0]["symbol"] == "2330"
    assert loaded.iloc[0]["market"] == "TWSE"
    assert loaded.iloc[0]["list_status"] == "active"


def test_upsert_stock_master_keeps_latest_symbol_row() -> None:
    existing = load_stock_master_from_rows(
        [
            {
                "symbol": "2330",
                "name": "TSMC",
                "market": "TWSE",
                "industry": "Semiconductor",
                "list_status": "active",
                "source": "old",
            }
        ]
    )
    incoming = load_stock_master_from_rows(
        [
            {
                "symbol": "2330",
                "name": "台積電",
                "market": "TWSE",
                "industry": "Semiconductor",
                "list_status": "active",
                "source": "fixture",
            }
        ]
    )

    merged = upsert_stock_master(existing, incoming)

    assert len(merged.index) == 1
    assert merged.iloc[0]["name"] == "台積電"
    assert merged.iloc[0]["source"] == "fixture"


def test_upsert_stock_master_keeps_same_symbol_across_markets() -> None:
    existing = load_stock_master_from_rows(
        [
            {
                "symbol": "6805",
                "name": "富世達",
                "market": "TWSE",
                "industry": "電子零組件業",
                "list_status": "active",
                "source": "old",
            }
        ]
    )
    incoming = load_stock_master_from_rows(
        [
            {
                "symbol": "6805",
                "name": "峰源-KY",
                "market": "TPEX",
                "industry": "其他業",
                "list_status": "active",
                "source": "fixture",
            }
        ]
    )

    merged = upsert_stock_master(existing, incoming)

    assert len(merged.index) == 2
    assert set(zip(merged["market"], merged["symbol"])) == {("TWSE", "6805"), ("TPEX", "6805")}


def test_fetch_stock_master_fixture_mode_reads_market_fixture(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    fixture_dir = data_dir / "raw" / "fixtures" / "stocks"
    fixture_dir.mkdir(parents=True, exist_ok=True)
    fixture_path = fixture_dir / "twse_stocks.csv"
    fixture_path.write_text(
        "\n".join(
            [
                "symbol,name,market,industry,list_status,source",
                "2330,台積電,TWSE,Semiconductor,active,fixture",
                "2317,鴻海,TWSE,Electronics,active,fixture",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("TS_DATA_DIR", str(data_dir))

    frame = fetch_stock_master(markets=["TWSE"], settings=Settings(), source_mode="fixture")

    assert list(frame["symbol"]) == ["2330", "2317"]
    assert set(frame["market"]) == {"TWSE"}


def test_fetch_stock_master_fixture_mode_decodes_cp950_html_fixture(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    fixture_dir = data_dir / "raw" / "fixtures" / "stocks"
    fixture_dir.mkdir(parents=True, exist_ok=True)
    fixture_path = fixture_dir / "twse_stocks.csv"
    payload = """
    <table>
      <tr><td colspan="7"><b> 股票 </b></td></tr>
      <tr><td>2330　台積電</td><td>TW0002330008</td><td>1994/09/05</td><td>上市</td><td>半導體業</td><td>ESVUFR</td><td></td></tr>
    </table>
    """
    fixture_path.write_bytes(payload.encode("cp950"))
    monkeypatch.setenv("TS_DATA_DIR", str(data_dir))

    frame = fetch_stock_master(markets=["TWSE"], settings=Settings(), source_mode="fixture")

    assert list(frame["symbol"]) == ["2330"]
    assert list(frame["name"]) == ["台積電"]


def test_build_stock_master_provider_registry_includes_twse_and_tpex() -> None:
    registry = build_stock_master_provider_registry(
        providers=[TwseStockMasterProvider(), TpexStockMasterProvider()]
    )

    assert set(registry.keys()) == {"TWSE", "TPEX"}


def test_twse_stock_master_provider_parses_official_style_columns() -> None:
    payload = "\n".join(
        [
            "證券代號,證券名稱,產業別,上市別",
            "2330,台積電,半導體業,上市",
            "2317,鴻海,其他電子業,上市",
        ]
    )

    frame = TwseStockMasterProvider().parse_payload(payload)

    assert list(frame["symbol"]) == ["2330", "2317"]
    assert list(frame["industry"]) == ["半導體業", "其他電子業"]
    assert set(frame["list_status"]) == {"active"}


def test_tpex_stock_master_provider_parses_official_style_columns() -> None:
    payload = "\n".join(
        [
            "代號,名稱,產業類別,上櫃別",
            "8069,元太,光電業,上櫃",
            "5274,信驊,半導體業,上櫃",
        ]
    )

    frame = TpexStockMasterProvider().parse_payload(payload)

    assert list(frame["symbol"]) == ["8069", "5274"]
    assert list(frame["industry"]) == ["光電業", "半導體業"]
    assert set(frame["list_status"]) == {"active"}


def test_twse_stock_master_provider_parses_isin_html_stock_section() -> None:
    payload = """
    <table>
      <tr><td>有價證券代號及名稱</td><td>ISIN Code</td><td>上市日</td><td>市場別</td><td>產業別</td><td>CFICode</td><td>備註</td></tr>
      <tr><td colspan="7"><b> 股票 </b></td></tr>
      <tr><td>2330　台積電</td><td>TW0002330008</td><td>1994/09/05</td><td>上市</td><td>半導體業</td><td>ESVUFR</td><td></td></tr>
      <tr><td>2317　鴻海</td><td>TW0002317005</td><td>1991/06/18</td><td>上市</td><td>其他電子業</td><td>ESVUFR</td><td></td></tr>
      <tr><td colspan="7"><b> ETF </b></td></tr>
      <tr><td>0050　元大台灣50</td><td>TW0000050004</td><td>2003/06/30</td><td>上市</td><td></td><td>CEOGEU</td><td></td></tr>
    </table>
    """

    frame = TwseStockMasterProvider().parse_payload(payload)

    assert list(frame["symbol"]) == ["2330", "2317"]
    assert list(frame["name"]) == ["台積電", "鴻海"]
    assert list(frame["industry"]) == ["半導體業", "其他電子業"]


def test_tpex_stock_master_provider_parses_isin_html_stock_section() -> None:
    payload = """
    <table>
      <tr><td>有價證券代號及名稱</td><td>ISIN Code</td><td>上櫃日</td><td>市場別</td><td>產業別</td><td>CFICode</td><td>備註</td></tr>
      <tr><td colspan="7"><b> 上櫃認購(售)權證 </b></td></tr>
      <tr><td>700001　範例權證</td><td>TW25Z7000016</td><td>2025/10/01</td><td>上櫃</td><td></td><td>RWSCCA</td><td></td></tr>
      <tr><td colspan="7"><b> 股票 </b></td></tr>
      <tr><td>8069　元太</td><td>TW0008069006</td><td>2004/01/02</td><td>上櫃</td><td>光電業</td><td>ESVUFR</td><td></td></tr>
      <tr><td>5274　信驊</td><td>TW0005274005</td><td>2013/03/12</td><td>上櫃</td><td>半導體業</td><td>ESVUFR</td><td></td></tr>
    </table>
    """

    frame = TpexStockMasterProvider().parse_payload(payload)

    assert list(frame["symbol"]) == ["8069", "5274"]
    assert list(frame["name"]) == ["元太", "信驊"]
    assert list(frame["industry"]) == ["光電業", "半導體業"]


def test_twse_stock_master_provider_network_decodes_cp950_html(monkeypatch) -> None:
    payload = """
    <table>
      <tr><td colspan="7"><b> 股票 </b></td></tr>
      <tr><td>2330　台積電</td><td>TW0002330008</td><td>1994/09/05</td><td>上市</td><td>半導體業</td><td>ESVUFR</td><td></td></tr>
    </table>
    """.encode(
        "cp950"
    )

    class FakeResponse:
        content = payload

        @staticmethod
        def raise_for_status() -> None:
            return None

    def fake_get(*args, **kwargs):
        return FakeResponse()

    monkeypatch.setattr("sentinel.datasources.stock_master.requests.get", fake_get)

    settings = Settings(
        twse_stock_master_url="https://example.com/twse",
        tpex_stock_master_url="https://example.com/tpex",
    )
    frame = TwseStockMasterProvider().fetch(settings=settings, source_mode="network")

    assert list(frame["symbol"]) == ["2330"]
    assert list(frame["name"]) == ["台積電"]


def test_fetch_stock_master_with_diagnostics_classifies_dns_failure(monkeypatch) -> None:
    def fake_get(*args, **kwargs):
        raise requests.ConnectionError(
            "HTTPSConnection(host='isin.twse.com.tw', port=443): Failed to resolve 'isin.twse.com.tw'"
        )

    monkeypatch.setattr("sentinel.datasources.stock_master.requests.get", fake_get)

    _, diagnostics = fetch_stock_master_with_diagnostics(
        markets=["TWSE"],
        settings=Settings(twse_stock_master_url="https://example.com/twse"),
        source_mode="network",
    )

    assert diagnostics[0]["final_status"] == "failed"
    assert diagnostics[0]["attempts"][0]["error_category"] == "dns"


def test_fetch_stock_master_with_diagnostics_classifies_timeout_failure(monkeypatch) -> None:
    def fake_get(*args, **kwargs):
        raise requests.ReadTimeout("read timed out")

    monkeypatch.setattr("sentinel.datasources.stock_master.requests.get", fake_get)

    _, diagnostics = fetch_stock_master_with_diagnostics(
        markets=["TWSE"],
        settings=Settings(twse_stock_master_url="https://example.com/twse"),
        source_mode="network",
    )

    assert diagnostics[0]["final_status"] == "failed"
    assert diagnostics[0]["attempts"][0]["error_category"] == "timeout"


def test_fetch_stock_master_with_diagnostics_classifies_http_status_failure(monkeypatch) -> None:
    class FakeResponse:
        status_code = 503

    class FailingResponse:
        @staticmethod
        def raise_for_status() -> None:
            raise requests.HTTPError("503 Server Error", response=FakeResponse())

    def fake_get(*args, **kwargs):
        return FailingResponse()

    monkeypatch.setattr("sentinel.datasources.stock_master.requests.get", fake_get)

    _, diagnostics = fetch_stock_master_with_diagnostics(
        markets=["TWSE"],
        settings=Settings(twse_stock_master_url="https://example.com/twse"),
        source_mode="network",
    )

    assert diagnostics[0]["final_status"] == "failed"
    assert diagnostics[0]["attempts"][0]["error_category"] == "http_status"
    assert diagnostics[0]["attempts"][0]["http_status_code"] == 503


def test_save_stock_master_diagnostics_writes_json(tmp_path) -> None:
    diagnostics_path = tmp_path / "outputs" / "stock_master" / "sync_diagnostics.json"

    save_stock_master_diagnostics(
        diagnostics=[
            {
                "market": "TWSE",
                "source_mode": "network",
                "final_status": "failed",
                "rows_fetched": 0,
                "attempts": [
                    {
                        "transport": "network",
                        "status": "failed",
                        "rows_fetched": 0,
                        "error_category": "dns",
                        "error_type": "ConnectionError",
                        "error_message": "failed to resolve",
                        "http_status_code": None,
                        "url": "https://example.com/twse",
                        "fixture_path": None,
                    }
                ],
            }
        ],
        path=diagnostics_path,
    )

    payload = diagnostics_path.read_text(encoding="utf-8")

    assert diagnostics_path.exists()
    assert '"market": "TWSE"' in payload
    assert '"error_category": "dns"' in payload


def load_stock_master_from_rows(rows):
    import pandas as pd

    return pd.DataFrame(rows)
