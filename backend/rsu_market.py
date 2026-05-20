"""
RSU market data: S&P 500 closing prices (yfinance) + USD/INR (Tavily).
Tranche value = price_usd * usd_to_inr_rate * no_shares  (= price_inr * no_shares).
"""

from __future__ import annotations

import json
import os
import re
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import pandas as pd
import requests
import yfinance as yf

DATA_DIR = Path(__file__).resolve().parent / "data"
PARQUET_FILE = DATA_DIR / "rsu_market_data.parquet"
LAST_UPDATE_FILE = DATA_DIR / "rsu_last_update.json"
REFRESH_INTERVAL_DAYS = 1

# yfinance uses hyphen for class B shares
YFINANCE_TICKER_ALIASES = {"BRK.B": "BRK-B", "BF.B": "BF-B"}


def _normalize_ticker(ticker: str) -> str:
    return (ticker or "").strip().upper()


def _yfinance_symbol(ticker: str) -> str:
    t = _normalize_ticker(ticker)
    return YFINANCE_TICKER_ALIASES.get(t, t)


def _save_last_update(iso_date: str) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LAST_UPDATE_FILE.write_text(
        json.dumps({"last_update": iso_date}), encoding="utf-8"
    )


def _load_last_update_date() -> Optional[str]:
    if not LAST_UPDATE_FILE.exists():
        return None
    try:
        return json.loads(LAST_UPDATE_FILE.read_text(encoding="utf-8")).get(
            "last_update"
        )
    except (json.JSONDecodeError, OSError):
        return None


def needs_refresh() -> bool:
    last = _load_last_update_date()
    if not last or not PARQUET_FILE.exists():
        return True
    try:
        last_d = datetime.fromisoformat(last.strip()).date()
        return (date.today() - last_d).days >= REFRESH_INTERVAL_DAYS
    except ValueError:
        return True


USD_INR_MIN = 60.0
USD_INR_MAX = 150.0

# Explicit FX phrases (avoid grabbing day-of-month like "May 19")
_FX_PATTERNS = [
    re.compile(
        r"1\s*(?:USD|US\s*\$|U\.?S\.?\s*Dollar)\s*[=:]\s*([\d]{2,3}(?:\.\d{1,4})?)\s*(?:INR|₹|Rs\.?|Rupees?)",
        re.I,
    ),
    re.compile(
        r"([\d]{2,3}(?:\.\d{1,4})?)\s*(?:INR|₹|Rs\.?|Rupees?)\s*(?:per|for|to)\s*(?:1\s*)?(?:USD|US\s*\$)",
        re.I,
    ),
    re.compile(
        r"(?:USD|US\s*\$)\s*(?:to|/|-)\s*(?:INR|₹)\s*[=:]\s*([\d]{2,3}(?:\.\d{1,4})?)",
        re.I,
    ),
    re.compile(
        r"(?:exchange\s+rate|conversion\s+rate|rate)\s*(?:is|of|:)?\s*([\d]{2,3}(?:\.\d{1,4})?)",
        re.I,
    ),
]


def _rate_in_range(value: float) -> bool:
    return USD_INR_MIN <= value <= USD_INR_MAX


def _cached_usd_to_inr_rate() -> Optional[float]:
    """Last USD/INR from parquet (used when Tavily parsing fails)."""
    if not PARQUET_FILE.exists():
        return None
    try:
        df = load_market_data()
        if df.empty or "usd_to_inr_rate" not in df.columns:
            return None
        rate = float(df["usd_to_inr_rate"].iloc[0])
        return rate if _rate_in_range(rate) else None
    except Exception:
        return None


def _parse_usd_to_inr_from_text(text: str) -> Optional[float]:
    """Extract USD/INR from search snippets; never use arbitrary first number."""
    for pattern in _FX_PATTERNS:
        for match in pattern.finditer(text):
            try:
                rate = float(match.group(1))
            except (ValueError, IndexError):
                continue
            if _rate_in_range(rate):
                return rate

    in_range: list[float] = []
    for raw in re.findall(r"\b(\d{2,3}(?:\.\d{1,4})?)\b", text):
        try:
            rate = float(raw)
        except ValueError:
            continue
        if _rate_in_range(rate):
            in_range.append(rate)

    if not in_range:
        return None

    # Prefer the most frequently cited rate in snippets
    rounded = [round(r, 2) for r in in_range]
    return float(max(set(rounded), key=rounded.count))


def scrape_usd_to_inr_rate(*, allow_cached_fallback: bool = True) -> float:
    api_key = os.getenv("TAVILY_API_KEY", "").strip()
    if not api_key:
        cached = _cached_usd_to_inr_rate()
        if cached is not None:
            return cached
        raise RuntimeError("TAVILY_API_KEY is not configured")

    query = f"USD INR exchange rate 1 dollar equals rupees {date.today().isoformat()}"
    resp = requests.post(
        "https://api.tavily.com/search",
        json={
            "api_key": api_key,
            "query": query,
            "max_results": 5,
            "search_depth": "basic",
        },
        timeout=60,
    )
    resp.raise_for_status()
    body = resp.json()
    chunks = [
        r.get("content", "") or ""
        for r in body.get("results", [])
    ]
    text = " ".join(chunks)
    rate = _parse_usd_to_inr_from_text(text)
    if rate is not None:
        return rate

    if allow_cached_fallback:
        cached = _cached_usd_to_inr_rate()
        if cached is not None:
            return cached

    raise RuntimeError(
        "Could not parse USD/INR from Tavily results (avoided mis-reading dates). "
        "Ensure parquet exists or check TAVILY_API_KEY."
    )


def _to_scalar_price(value) -> Optional[float]:
    """Coerce yfinance/pandas values to a single float (never use Series in if)."""
    if value is None:
        return None
    if isinstance(value, pd.Series):
        cleaned = value.dropna()
        if cleaned.empty:
            return None
        return float(cleaned.iloc[-1])
    if isinstance(value, pd.DataFrame):
        return None
    try:
        f = float(value)
        if pd.isna(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _column_to_symbol(col) -> str:
    """Map yfinance column label (incl. MultiIndex) to ticker symbol string."""
    if isinstance(col, tuple):
        for part in reversed(col):
            if part and str(part).lower() not in ("close", "adj close", "price"):
                return str(part).upper()
        return str(col[-1]).upper()
    return str(col).upper()


def fetch_closing_prices(tickers: list[str]) -> pd.DataFrame:
    symbols = [_yfinance_symbol(t) for t in tickers]
    unique_symbols = list(dict.fromkeys(symbols))
    if not unique_symbols:
        return pd.DataFrame(columns=["ticker", "price_usd"])

    raw = yf.download(
        tickers=unique_symbols,
        period="5d",
        interval="1d",
        auto_adjust=True,
        progress=False,
        threads=True,
        group_by="column",
    )
    if raw is None or (hasattr(raw, "empty") and raw.empty):
        raise RuntimeError("yfinance returned no data")

    close_df = raw["Close"] if "Close" in raw.columns or isinstance(raw.columns, pd.MultiIndex) else raw
    sym_to_canonical: dict[str, str] = {}
    for t in tickers:
        sym = _yfinance_symbol(t)
        sym_to_canonical[sym] = _normalize_ticker(t)

    # yfinance symbol -> last close (USD)
    yf_prices: dict[str, float] = {}

    if isinstance(close_df, pd.Series):
        # One ticker: index is dates, not symbol
        price = _to_scalar_price(close_df.ffill().iloc[-1])
        if price is not None and unique_symbols:
            yf_prices[unique_symbols[0]] = price
    elif isinstance(close_df, pd.DataFrame):
        last_row = close_df.ffill().iloc[-1]
        for col in last_row.index:
            sym_key = _column_to_symbol(col)
            price = _to_scalar_price(last_row[col])
            if price is not None:
                yf_prices[sym_key] = price
    else:
        raise RuntimeError(f"Unexpected Close data type: {type(close_df)}")

    records = []
    seen: set[str] = set()
    for sym, canon in sym_to_canonical.items():
        if canon in seen:
            continue
        price = yf_prices.get(sym)
        if price is None:
            # MultiIndex column may use hyphen symbol (BRK-B vs BRK.B)
            alt = sym.replace(".", "-")
            price = yf_prices.get(alt) or yf_prices.get(sym.replace("-", "."))
        if price is not None:
            records.append({"ticker": canon, "price_usd": round(price, 4)})
            seen.add(canon)
    return pd.DataFrame(records)


def build_market_data(tickers: Optional[list[str]] = None) -> pd.DataFrame:
    usd_to_inr = scrape_usd_to_inr_rate()
    scrape_date = date.today().isoformat()

    if tickers:
        tickers = [_normalize_ticker(t) for t in tickers if t]
        price_df = fetch_closing_prices(tickers)
    else:
        existing = load_market_data()
        tickers = existing["ticker"].tolist()
        price_df = fetch_closing_prices(tickers)

    if price_df.empty:
        raise RuntimeError("No stock prices retrieved")

    price_df["price_inr"] = (price_df["price_usd"] * usd_to_inr).round(2)
    price_df["usd_to_inr_rate"] = usd_to_inr
    price_df["scrape_date"] = scrape_date
    return price_df


def _verify_parquet_storage(expected_rows: Optional[int] = None) -> dict:
    """Confirm parquet was written and is readable."""
    info: dict = {
        "parquet_path": str(PARQUET_FILE.resolve()),
        "parquet_exists": PARQUET_FILE.exists(),
        "parquet_row_count": 0,
        "parquet_ok": False,
    }
    if not PARQUET_FILE.exists():
        return info
    try:
        on_disk = pd.read_parquet(PARQUET_FILE, engine="pyarrow")
        info["parquet_row_count"] = len(on_disk)
        required = {"ticker", "price_usd", "price_inr", "usd_to_inr_rate", "scrape_date"}
        info["parquet_ok"] = required.issubset(on_disk.columns) and len(on_disk) > 0
        if expected_rows is not None:
            info["parquet_ok"] = info["parquet_ok"] and len(on_disk) == expected_rows
    except Exception as exc:
        info["parquet_error"] = str(exc)
    return info


def save_market_data(df: pd.DataFrame) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    expected_cols = ["ticker", "price_usd", "price_inr", "usd_to_inr_rate", "scrape_date"]
    missing = [c for c in expected_cols if c not in df.columns]
    if missing:
        raise RuntimeError(f"Cannot save market data: missing columns {missing}")
    df.to_parquet(PARQUET_FILE, index=False, engine="pyarrow")
    verify = _verify_parquet_storage(expected_rows=len(df))
    if not verify.get("parquet_ok"):
        raise RuntimeError(
            f"Parquet write verification failed: {verify}"
        )
    scrape_date = str(df["scrape_date"].iloc[0])
    _save_last_update(scrape_date)


def load_market_data() -> pd.DataFrame:
    if not PARQUET_FILE.exists():
        raise FileNotFoundError(
            f"RSU market data not found at {PARQUET_FILE}. Run refresh first."
        )
    return pd.read_parquet(PARQUET_FILE, engine="pyarrow")


def merge_and_save(new_rows: pd.DataFrame) -> pd.DataFrame:
    """Merge new ticker rows into existing parquet; refresh FX on all cached tickers."""
    usd_to_inr = float(new_rows["usd_to_inr_rate"].iloc[0])
    scrape_date = str(new_rows["scrape_date"].iloc[0])
    if PARQUET_FILE.exists():
        existing = load_market_data()
        existing = existing[~existing["ticker"].isin(new_rows["ticker"])]
        existing["usd_to_inr_rate"] = usd_to_inr
        existing["scrape_date"] = scrape_date
        existing["price_inr"] = (existing["price_usd"] * usd_to_inr).round(2)
        combined = pd.concat([existing, new_rows], ignore_index=True)
    else:
        combined = new_rows
    save_market_data(combined)
    return combined


def refresh_market_data(
    tickers: Optional[list[str]] = None,
    force: bool = False,
) -> dict:
    if not force and not needs_refresh() and PARQUET_FILE.exists():
        df = load_market_data()
        return _meta_from_df(df, skipped=True)

    if tickers:
        tickers = [_normalize_ticker(t) for t in tickers if t]
        new_df = build_market_data(tickers)
        df = merge_and_save(new_df)
    else:
        df = build_market_data()
        save_market_data(df)

    return _meta_from_df(df, skipped=False)


def _meta_from_df(df: pd.DataFrame, skipped: bool = False) -> dict:
    storage = _verify_parquet_storage()
    if df.empty:
        return {
            "skipped": skipped,
            "last_update": _load_last_update_date(),
            "scrape_date": None,
            "usd_to_inr_rate": None,
            "ticker_count": 0,
            **storage,
        }
    return {
        "skipped": skipped,
        "last_update": _load_last_update_date(),
        "scrape_date": str(df["scrape_date"].iloc[0]),
        "usd_to_inr_rate": float(df["usd_to_inr_rate"].iloc[0]),
        "ticker_count": len(df),
        **storage,
    }


def get_rsu_market_payload() -> dict:
    """Full cached market data (parquet) in the shape the dashboard expects."""
    if not PARQUET_FILE.exists():
        raise FileNotFoundError(
            f"RSU market data not found at {PARQUET_FILE}. Run refresh first."
        )
    df = load_market_data()
    usd_to_inr = float(df.iloc[0]["usd_to_inr_rate"]) if not df.empty else None
    scrape_date = str(df.iloc[0]["scrape_date"]) if not df.empty else None
    tickers = {
        str(row["ticker"]): {
            "price_usd": float(row["price_usd"]),
            "price_inr": float(row["price_inr"]),
            "usd_to_inr_rate": float(row["usd_to_inr_rate"]),
            "scrape_date": str(row["scrape_date"]),
        }
        for _, row in df.iterrows()
    }
    return {
        "usd_to_inr_rate": usd_to_inr,
        "last_updated": _load_last_update_date(),
        "scrape_date": scrape_date,
        "tickers": tickers,
        **_verify_parquet_storage(),
    }


def refresh_rsu_market_payload(tickers: Optional[list[str]] = None) -> dict:
    """Force refresh then return full parquet payload."""
    refresh_market_data(
        tickers=[_normalize_ticker(t) for t in tickers if t] if tickers else None,
        force=True,
    )
    payload = get_rsu_market_payload()
    return {"status": "ok", **payload}


def get_prices_for_tickers(tickers: list[str]) -> dict:
    tickers = [_normalize_ticker(t) for t in tickers if t]
    if not tickers:
        return {"meta": _meta_from_df(pd.DataFrame()), "prices": {}}

    if not PARQUET_FILE.exists():
        return {
            "meta": {
                "last_update": None,
                "scrape_date": None,
                "usd_to_inr_rate": None,
                "ticker_count": 0,
                **_verify_parquet_storage(),
            },
            "prices": {},
        }

    df = load_market_data()
    meta = _meta_from_df(df)
    subset = df[df["ticker"].isin(tickers)]
    prices = {
        row["ticker"]: {
            "price_usd": float(row["price_usd"]),
            "price_inr": float(row["price_inr"]),
            "usd_to_inr_rate": float(row["usd_to_inr_rate"]),
            "scrape_date": str(row["scrape_date"]),
        }
        for _, row in subset.iterrows()
    }
    return {"meta": meta, "prices": prices}


def tranche_value_inr(
    price_usd: float,
    usd_to_inr_rate: float,
    no_shares: float,
) -> float:
    return round(price_usd * usd_to_inr_rate * no_shares, 2)
