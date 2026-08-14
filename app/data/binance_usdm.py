from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

from app.core.types import Candle


ARCHIVE_BASE = "https://data.binance.vision/data/futures/um/monthly/klines"
REST_URL = "https://fapi.binance.com/fapi/v1/klines"
SYMBOL_MAP = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT"}


@dataclass(frozen=True)
class ArchiveRecord:
    symbol: str
    month: str
    url: str
    path: str
    sha256: str
    checksum_verified: bool


def archive_url(symbol: str, timeframe: str, month: str) -> str:
    return f"{ARCHIVE_BASE}/{symbol}/{timeframe}/{symbol}-{timeframe}-{month}.zip"


def verify_checksum(content: bytes, checksum_text: str) -> str:
    expected = re.search(r"\b[a-fA-F0-9]{64}\b", checksum_text)
    if expected is None:
        raise ValueError("archive checksum file does not contain a SHA-256 digest")
    actual = hashlib.sha256(content).hexdigest()
    if actual.lower() != expected.group(0).lower():
        raise ValueError("Binance archive SHA-256 mismatch")
    return actual


def download_archive(symbol: str, timeframe: str, month: str, raw_root: Path) -> ArchiveRecord:
    url = archive_url(symbol, timeframe, month)
    with urllib.request.urlopen(url, timeout=60) as response:
        content = response.read()
    with urllib.request.urlopen(f"{url}.CHECKSUM", timeout=30) as response:
        checksum_text = response.read().decode("utf-8")
    digest = verify_checksum(content, checksum_text)
    directory = raw_root / symbol
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{symbol}-{timeframe}-{month}.zip"
    path.write_bytes(content)
    return ArchiveRecord(symbol, month, url, str(path), digest, True)


def parse_archive(path: Path, local_symbol: str, timeframe: str = "15m") -> list[Candle]:
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist() if name.endswith(".csv")]
        if len(names) != 1:
            raise ValueError("Binance archive must contain exactly one CSV")
        rows = csv.reader(io.TextIOWrapper(archive.open(names[0]), encoding="utf-8"))
        candles = [_parse_row(row, local_symbol, timeframe) for row in rows if row and row[0] != "open_time"]
    return candles


def _parse_row(row: list[str], local_symbol: str, timeframe: str) -> Candle:
    if len(row) < 7:
        raise ValueError("invalid Binance kline row")
    open_time = int(row[0])
    duration = 900_000 if timeframe == "15m" else 0
    return Candle(local_symbol, timeframe, open_time, float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[5]), open_time + duration)


def fetch_klines(symbol: str, start_time: int, end_time: int) -> list[Candle]:
    query = f"?symbol={symbol}&interval=15m&startTime={start_time}&endTime={end_time}&limit=1500"
    with urllib.request.urlopen(f"{REST_URL}{query}", timeout=30) as response:
        rows = json.loads(response.read().decode("utf-8"))
    local_symbol = next(local for local, remote in SYMBOL_MAP.items() if remote == symbol)
    return [_parse_row([str(value) for value in row], local_symbol, "15m") for row in rows]
