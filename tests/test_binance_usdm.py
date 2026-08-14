from __future__ import annotations

import hashlib
import io
import zipfile

import pytest

from app.data.binance_usdm import SYMBOL_MAP, parse_archive, verify_checksum


def test_checksum_verification_accepts_matching_digest_and_rejects_mismatch() -> None:
    payload = b"verified archive"
    assert verify_checksum(payload, f"{hashlib.sha256(payload).hexdigest()} file.zip") == hashlib.sha256(payload).hexdigest()
    with pytest.raises(ValueError, match="mismatch"):
        verify_checksum(payload, "0" * 64)


def test_binance_kline_archive_parsing_supports_header_and_symbol_mapping(tmp_path) -> None:
    archive_path = tmp_path / "BTCUSDT.zip"
    content = "open_time,open,high,low,close,volume,close_time,quote_volume,trade_count,taker_buy_base_volume,taker_buy_quote_volume,ignore\n0,10,12,9,11,4,899999,0,0,0,0,0\n"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("BTCUSDT-15m.csv", content)
    candles = parse_archive(archive_path, "BTC")
    assert SYMBOL_MAP["BTC"] == "BTCUSDT"
    assert candles[0].symbol == "BTC"
    assert candles[0].close_time == 900_000
    assert candles[0].volume == 4
