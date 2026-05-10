from __future__ import annotations

import io
import re
import zipfile
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import pandas as pd
from bs4 import BeautifulSoup

from src.discover.base import SourceAdapter, SourceMetadata
from src.normalize.schema import canonicalize
from src.utils.checkpoints import CheckpointStore
from src.utils.config import PATHS
from src.utils.dates import parse_cdsl_archive_input
from src.utils.io_utils import raw_path, write_bytes, write_text


class NSECurrentAdapter(SourceAdapter):
    source_name = "nse_current"
    combined_url = "https://www.nseindia.com/api/fiidiiTradeReact"
    nse_only_url = "https://www.nseindia.com/api/fiidiiTradeNse"

    def discover(self) -> SourceMetadata:
        return SourceMetadata(
            source_name=self.source_name,
            trust_tier="official",
            history_coverage="latest day only",
            granularity="daily",
            fields_available=["date", "category", "buyValue", "sellValue", "netValue"],
            participant_coverage=["FII/FPI", "DII"],
            sector_data="none",
            implementation_difficulty="low",
            fragility_risk="low",
            limitations=[
                "Official NSE endpoint exposes only latest day.",
                "NSE page states FII/FPI values are provisional.",
            ],
            urls=[
                "https://www.nseindia.com/reports/fii-dii",
                self.combined_url,
                self.nse_only_url,
            ],
        )

    def fetch(self, start_date: date | None = None, end_date: date | None = None) -> list[dict[str, Any]]:
        outputs = []
        for label, url in [("combined", self.combined_url), ("nse_only", self.nse_only_url)]:
            response = self.http.get(url, headers={"Accept": "application/json,text/plain,*/*"})
            write_text(raw_path(self.source_name, f"{label}/latest.json"), response.text)
            outputs.append({"url": url, "label": label, "payload": response.json()})
        return outputs

    def parse(self, raw_item: dict[str, Any]) -> pd.DataFrame:
        frame = pd.DataFrame(raw_item["payload"])
        frame = frame.rename(
            columns={
                "category": "participant_type",
                "buyValue": "buy_value",
                "sellValue": "sell_value",
                "netValue": "net_value",
            }
        )
        frame["market_segment"] = "capital_market"
        frame["sector"] = pd.NA
        frame["instrument"] = "equity"
        frame["series_kind"] = "direct"
        frame["source_name"] = self.source_name
        frame["source_url"] = raw_item["url"]
        frame["source_type"] = "json_api"
        frame["extraction_method"] = "requests_json"
        frame["is_official"] = True
        frame["is_provisional"] = raw_item["label"] == "combined"
        frame["is_final"] = raw_item["label"] == "nse_only"
        frame["confidence_score"] = 0.92 if raw_item["label"] == "combined" else 0.9
        frame["currency"] = "INR crore"
        frame["notes"] = (
            "Combined across NSE/BSE/MSEI and provisional"
            if raw_item["label"] == "combined"
            else "NSE-only values"
        )
        return canonicalize(frame)


class NSDLAdapter(SourceAdapter):
    source_name = "nsdl_latest"
    latest_url = "https://pilot.fpi.nsdl.co.in/Reports/Latest.aspx"

    def discover(self) -> SourceMetadata:
        return SourceMetadata(
            source_name=self.source_name,
            trust_tier="official",
            history_coverage="latest daily page verified; older history not discovered via simple URL pattern",
            granularity="daily",
            fields_available=["date", "gross_purchase", "gross_sales", "net_investment"],
            participant_coverage=["FII/FPI"],
            sector_data="none",
            implementation_difficulty="medium",
            fragility_risk="medium",
            limitations=[
                "ASP.NET page requires HTML parsing.",
                "Historical archive path is not obvious from the public latest page.",
            ],
            urls=[self.latest_url],
        )

    def fetch(self, start_date: date | None = None, end_date: date | None = None) -> list[dict[str, Any]]:
        response = self.http.get(self.latest_url)
        write_text(raw_path(self.source_name, "latest.html"), response.text)
        return [{"url": self.latest_url, "payload": response.text}]

    def parse(self, raw_item: dict[str, Any]) -> pd.DataFrame:
        tables = pd.read_html(io.StringIO(raw_item["payload"]))
        frame = next(table for table in tables if table.shape[1] >= 6 and table.shape[0] >= 3)
        working = frame.copy()
        working.iloc[:, 1] = working.iloc[:, 1].ffill()
        working.iloc[:, 2] = working.iloc[:, 2].ffill()
        subtotal_rows = working[
            working.iloc[:, 1].astype(str).str.contains("equity", case=False, na=False)
            & working.iloc[:, 2].astype(str).str.contains("sub-total", case=False, na=False)
        ]
        if subtotal_rows.empty:
            raise ValueError("Could not locate NSDL equity subtotal row")
        row = subtotal_rows.iloc[0]
        trade_date = pd.to_datetime(row.iloc[0]).date()
        normalized = pd.DataFrame(
            [
                {
                    "date": trade_date,
                    "participant_type": "FII/FPI",
                    "buy_value": pd.to_numeric(row.iloc[3], errors="coerce"),
                    "sell_value": pd.to_numeric(row.iloc[4], errors="coerce"),
                    "net_value": _coerce_parenthesized_number(row.iloc[5]),
                    "market_segment": "capital_market",
                    "sector": pd.NA,
                    "instrument": "equity",
                    "series_kind": "direct",
                    "source_name": self.source_name,
                    "source_url": raw_item["url"],
                    "source_type": "html_table",
                    "extraction_method": "pandas_read_html",
                    "is_official": True,
                    "is_provisional": False,
                    "is_final": True,
                    "confidence_score": 0.98,
                    "currency": "INR crore",
                    "notes": "NSDL latest final FPI/FII daily trend",
                }
            ]
        )
        return canonicalize(normalized)


class CDSLAdapter(SourceAdapter):
    source_name = "cdsl"
    landing_url = "https://www.cdslindia.com/Publications/ForeignPortInvestor.html"
    latest_archive_url = "https://www.cdslindia.com/Publications/FIITrends.aspx"
    equity_zip_url = "https://www.cdslindia.com/Publications/EquityDataFII.html"
    calendar_url = "https://www.cdslindia.com/eservices/Publications/FIICalendar"
    sector_page = "https://www.cdslindia.com/publications/FII/FortnightlySecWisePages/March%2031%2C%202026.html"

    def __init__(self, *args: Any, checkpoint_store: CheckpointStore | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.checkpoints = checkpoint_store or CheckpointStore()

    def discover(self) -> SourceMetadata:
        return SourceMetadata(
            source_name=self.source_name,
            trust_tier="official",
            history_coverage="daily archive links and monthly equity trade ZIPs from 2003 onward; sector-wise fortnightly pages available",
            granularity="daily and fortnightly",
            fields_available=[
                "daily FPI/FII buy/sell/net",
                "monthly security-level trade data",
                "fortnightly sector-wise investment",
            ],
            participant_coverage=["FII/FPI"],
            sector_data="direct fortnightly sector-wise investment; daily sector proxy feasible",
            implementation_difficulty="medium",
            fragility_risk="medium",
            limitations=[
                "No DII series.",
                "Archive page is ASP.NET and requires form POSTs for arbitrary dates.",
                "Monthly trade ZIP files are large.",
            ],
            urls=[
                self.landing_url,
                self.latest_archive_url,
                self.equity_zip_url,
                self.calendar_url,
                self.sector_page,
            ],
        )

    def fetch_latest(self) -> list[dict[str, Any]]:
        response = self.http.get(self.landing_url)
        write_text(raw_path(self.source_name, "landing.html"), response.text)
        soup = BeautifulSoup(response.text, "lxml")
        links = []
        for anchor in soup.select('a[href*="downloads/Publications/Latest/latest_"], a[href*="downloads/Publications/Latest/Latest_"]'):
            href = urljoin(self.landing_url, anchor.get("href", ""))
            links.append(href)
        if not links:
            return []
        latest_link = max(set(links), key=_extract_date_from_latest_url)
        payload = self.http.get(latest_link).content
        ext = ".xls" if latest_link.lower().endswith(".xls") else ".bin"
        write_bytes(raw_path(self.source_name, f"latest/latest{ext}"), payload)
        return [{"url": latest_link, "payload": payload}]

    def fetch_archive_date(self, trade_date: date) -> dict[str, Any]:
        response = self.http.get(self.latest_archive_url)
        write_text(raw_path(self.source_name, f"archive_form/{trade_date.isoformat()}.html"), response.text)
        soup = BeautifulSoup(response.text, "lxml")
        form_data = {}
        for name in ["__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION"]:
            element = soup.find("input", {"name": name})
            if element and element.get("value"):
                form_data[name] = element["value"]
        form_data.update(
            {
                "selectedDate": parse_cdsl_archive_input(trade_date),
                "ctl30": "Go",
                "grpArchive": "rdbAfter",
            }
        )
        posted = self.http.post(self.latest_archive_url, data=form_data)
        write_text(raw_path(self.source_name, f"archive_response/{trade_date.isoformat()}.html"), posted.text)
        return {"url": self.latest_archive_url, "payload": posted.text, "trade_date": trade_date}

    def fetch_equity_month_zip(self, year: int, month_label: str, zip_href: str) -> dict[str, Any]:
        zip_url = urljoin(self.equity_zip_url, zip_href)
        payload = self.http.get(zip_url).content
        write_bytes(raw_path(self.source_name, f"equity_trade_zips/{year}/{Path(zip_href).name}"), payload)
        return {"url": zip_url, "payload": payload, "year": year, "month_label": month_label}

    def fetch_sector_page(self, url: str) -> dict[str, Any]:
        response = self.http.get(url)
        write_text(raw_path(self.source_name, f"sector_pages/{Path(url).name or 'sector.html'}"), response.text)
        return {"url": url, "payload": response.text}

    def discover_sector_page_urls(self) -> list[str]:
        cache_path = raw_path(self.source_name, "landing.html")
        try:
            response = self.http.get(self.landing_url)
            write_text(cache_path, response.text)
            html = response.text
        except Exception:
            if not cache_path.exists():
                raise
            html = cache_path.read_text(encoding="utf-8")

        soup = BeautifulSoup(html, "lxml")
        urls: list[str] = []
        seen: set[str] = set()
        for anchor in soup.select('a[href*="FortnightlySecWisePages"]'):
            href = anchor.get("href", "").strip()
            if not href:
                continue
            url = urljoin(self.landing_url, href)
            if url in seen:
                continue
            seen.add(url)
            urls.append(url)
        return urls

    def fetch(self, start_date: date | None = None, end_date: date | None = None) -> list[dict[str, Any]]:
        return self.fetch_latest()

    def parse(self, raw_item: dict[str, Any]) -> pd.DataFrame:
        content = raw_item["payload"]
        tables = _read_excel_like_tables(content)
        frame = max(tables, key=len).copy()
        frame.columns = [str(col).strip() for col in frame.columns]
        row, trade_date = _extract_cdsl_equity_subtotal(frame)
        normalized = pd.DataFrame(
            [
                {
                    "date": trade_date,
                    "participant_type": "FII/FPI",
                    "buy_value": row["buy_value"],
                    "sell_value": row["sell_value"],
                    "net_value": row["net_value"],
                    "market_segment": "capital_market",
                    "sector": pd.NA,
                    "instrument": "equity",
                    "series_kind": "direct",
                    "source_name": self.source_name,
                    "source_url": raw_item["url"],
                    "source_type": "xls_or_html_excel",
                    "extraction_method": "pandas_excel_or_html_fallback",
                    "is_official": True,
                    "is_provisional": False,
                    "is_final": True,
                    "confidence_score": 0.99,
                    "currency": "INR crore",
                    "notes": "CDSL final FPI/FII daily flow",
                }
            ]
        )
        return canonicalize(normalized)

    def parse_archive_html(self, raw_item: dict[str, Any]) -> pd.DataFrame:
        soup = BeautifulSoup(raw_item["payload"], "lxml")
        link = soup.find("a", href=re.compile(r"Latest_\d{8}\.xls", re.I))
        if link and link.get("href"):
            xls_url = urljoin(self.latest_archive_url, link["href"])
            payload = self.http.get(xls_url).content
            write_bytes(raw_path(self.source_name, f"archive_files/{raw_item['trade_date'].isoformat()}.xls"), payload)
            return self.parse({"url": xls_url, "payload": payload})
        raise ValueError(f"No downloadable file found for {raw_item['trade_date']}")

    def discover_equity_trade_archives(self) -> list[dict[str, Any]]:
        cache_path = raw_path(self.source_name, "equity_data_page.html")
        try:
            response = self.http.get(self.equity_zip_url)
            write_text(cache_path, response.text)
            html = response.text
        except Exception:
            if not cache_path.exists():
                raise
            html = cache_path.read_text(encoding="utf-8")
        soup = BeautifulSoup(html, "lxml")
        records: list[dict[str, Any]] = []
        current_year: int | None = None
        for element in soup.find_all(["a", "div"]):
            text = element.get_text(" ", strip=True)
            year_match = re.search(r"\((20\d{2}|201\d|200\d)\)", text)
            if year_match:
                current_year = int(year_match.group(1))
            if element.name == "a" and element.get("href", "").lower().endswith(".zip"):
                records.append(
                    {
                        "year": current_year,
                        "month_label": text,
                        "href": element["href"],
                    }
                )
        return records

    def parse_equity_trade_zip(self, raw_item: dict[str, Any]) -> pd.DataFrame:
        with zipfile.ZipFile(io.BytesIO(raw_item["payload"])) as zf:
            workbook_name = zf.namelist()[0]
            workbook_payload = zf.read(workbook_name)
        workbook_path = raw_path(
            self.source_name,
            f"equity_trade_unpacked/{raw_item['year']}/{workbook_name}",
        )
        write_bytes(workbook_path, workbook_payload)
        frame = pd.read_excel(io.BytesIO(workbook_payload))
        frame.columns = [str(col).strip() for col in frame.columns]
        return frame

    def parse_sector_page(self, raw_item: dict[str, Any]) -> pd.DataFrame:
        tables = pd.read_html(io.StringIO(raw_item["payload"]))
        frame = max(tables, key=lambda table: table.shape[1]).copy()
        if frame.shape[0] < 5:
            raise ValueError("Unexpected sector table shape")
        header_rows = frame.iloc[:4].fillna("")
        columns = []
        for col_idx in range(frame.shape[1]):
            parts = [str(header_rows.iat[row_idx, col_idx]).strip() for row_idx in range(4)]
            columns.append(" | ".join(part for part in parts if part))
        body = frame.iloc[4:].copy()
        body.columns = columns
        body = body.dropna(how="all")
        date_match = re.search(r"([A-Za-z]+\s+\d{1,2},\s+\d{4})", raw_item["url"])
        anchor_date = pd.to_datetime(date_match.group(1)).date() if date_match else date.today()
        sector_column = next((col for col in body.columns if "sectors" in col.lower()), body.columns[1])
        value_column = next(
            (
                col
                for col in body.columns
                if "net investment" in col.lower()
                and "total" in col.lower()
                and anchor_date.strftime("%d") in col
            ),
            None,
        )
        if value_column is None:
            value_column = next(
                (col for col in body.columns if "net investment" in col.lower() and "total" in col.lower()),
                body.columns[-1],
            )
        normalized = pd.DataFrame(
            {
                "date": anchor_date,
                "participant_type": "FII/FPI",
                "buy_value": pd.NA,
                "sell_value": pd.NA,
                "net_value": body[value_column].apply(_coerce_parenthesized_number),
                "market_segment": "capital_market",
                "sector": body[sector_column].astype(str).str.strip(),
                "instrument": "equity",
                "series_kind": "direct_sector_fortnightly",
                "source_name": self.source_name,
                "source_url": raw_item["url"],
                "source_type": "html_table",
                "extraction_method": "pandas_read_html",
                "is_official": True,
                "is_provisional": False,
                "is_final": True,
                "confidence_score": 0.97,
                "currency": "INR crore",
                "notes": "CDSL fortnightly sector-wise FPI investment",
            }
        )
        normalized = normalized[normalized["sector"].ne("nan") & normalized["sector"].ne("")]
        return canonicalize(normalized)


class FYERSAdapter(SourceAdapter):
    source_name = "fyers"

    def discover(self) -> SourceMetadata:
        return SourceMetadata(
            source_name=self.source_name,
            trust_tier="semi_official",
            history_coverage="not confirmed for historical institutional-flow API",
            granularity="unknown",
            fields_available=[],
            participant_coverage=["unknown"],
            sector_data="unknown",
            implementation_difficulty="high",
            fragility_risk="high",
            limitations=[
                "No documented FYERS institutional-flow API was confirmed during discovery.",
                "Web/UI presence should not be assumed to imply stable machine access.",
            ],
            urls=["https://myapi.fyers.in/"],
        )

    def fetch(self, start_date: date | None = None, end_date: date | None = None) -> list[dict[str, Any]]:
        return []

    def parse(self, raw_item: dict[str, Any]) -> pd.DataFrame:
        return canonicalize(pd.DataFrame())


class FallbackThirdPartyAdapter(SourceAdapter):
    source_name = "fallback_third_party"

    def __init__(self, csv_path: str | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.csv_path = csv_path

    def discover(self) -> SourceMetadata:
        return SourceMetadata(
            source_name=self.source_name,
            trust_tier="third_party",
            history_coverage="user-supplied",
            granularity="user-supplied",
            fields_available=["user-supplied schema"],
            participant_coverage=["user-supplied"],
            sector_data="user-supplied",
            implementation_difficulty="low",
            fragility_risk="high",
            limitations=[
                "Disabled by default.",
                "All rows must be tagged as third-party provenance.",
            ],
            urls=[self.csv_path] if self.csv_path else [],
        )

    def fetch(self, start_date: date | None = None, end_date: date | None = None) -> list[dict[str, Any]]:
        if not self.csv_path:
            return []
        path = Path(self.csv_path)
        return [{"url": str(path), "payload": pd.read_csv(path)}]

    def parse(self, raw_item: dict[str, Any]) -> pd.DataFrame:
        frame = raw_item["payload"].copy()
        frame["source_name"] = self.source_name
        frame["source_url"] = raw_item["url"]
        frame["source_type"] = "user_supplied_csv"
        frame["extraction_method"] = "pandas_read_csv"
        frame["is_official"] = False
        frame["is_provisional"] = False
        frame["is_final"] = pd.NA
        frame["confidence_score"] = 0.4
        return canonicalize(frame)


def _coerce_number_from_mapping(value_map: dict[str, Any], candidates: list[str]) -> float | None:
    for candidate in candidates:
        for key, value in value_map.items():
            if candidate.lower() in key:
                return pd.to_numeric(str(value).replace(",", ""), errors="coerce")
    return None


def _coerce_parenthesized_number(value: Any) -> float | None:
    text = str(value).strip().replace(",", "")
    if text.startswith("(") and text.endswith(")"):
        text = f"-{text[1:-1]}"
    return pd.to_numeric(text, errors="coerce")


def _series_lookup(row: pd.Series, candidates: list[str]) -> float | None:
    lowered = {str(key).strip().lower(): value for key, value in row.items()}
    for candidate in candidates:
        value = lowered.get(candidate.strip().lower())
        if value is not None:
            return pd.to_numeric(str(value).replace(",", ""), errors="coerce")
    return None


def _read_excel_like_tables(payload: bytes) -> list[pd.DataFrame]:
    for reader in (
        lambda: [pd.read_excel(io.BytesIO(payload), engine="openpyxl")],
        lambda: [pd.read_excel(io.BytesIO(payload), engine="xlrd")],
        lambda: pd.read_html(io.BytesIO(payload)),
    ):
        try:
            tables = reader()
            if tables:
                return tables
        except Exception:
            continue
    raise ValueError("Unable to parse payload as excel/html table")


def _extract_date_from_latest_url(url: str) -> datetime:
    match = re.search(r"latest_(\d{8})\.xls|Latest_(\d{8})\.xls", url, flags=re.I)
    if not match:
        return datetime.min
    raw = next(group for group in match.groups() if group)
    return datetime.strptime(raw, "%d%m%Y")


def _extract_cdsl_equity_subtotal(frame: pd.DataFrame) -> tuple[dict[str, float | None], date]:
    working = frame.copy()
    if working.shape[1] < 6:
        raise ValueError("Unexpected CDSL table shape")

    working.iloc[:, 1] = working.iloc[:, 1].ffill()
    working.iloc[:, 2] = working.iloc[:, 2].ffill()
    equity_rows = working[
        working.iloc[:, 1].astype(str).str.contains("equity", case=False, na=False)
        & working.iloc[:, 2].astype(str).str.contains("sub-total", case=False, na=False)
    ]
    if not equity_rows.empty:
        row = equity_rows.iloc[0]
        buy_value = pd.to_numeric(row.iloc[3], errors="coerce")
        sell_value = pd.to_numeric(row.iloc[4], errors="coerce")
        net_value = pd.to_numeric(row.iloc[5], errors="coerce")
        trade_date = _extract_cdsl_trade_date(frame)
        return (
            {
                "buy_value": buy_value,
                "sell_value": sell_value,
                "net_value": net_value,
            },
            trade_date,
        )
    raise ValueError("Could not locate CDSL equity subtotal row")


def _extract_cdsl_trade_date(frame: pd.DataFrame) -> date:
    header_text = " ".join(str(value) for value in frame.iloc[0].tolist())
    match = re.search(r"on (\d{2}-[A-Za-z]{3}-\d{4})", header_text)
    if match:
        return datetime.strptime(match.group(1), "%d-%b-%Y").date()
    for value in frame.iloc[:, 0].tolist():
        parsed = pd.to_datetime(value, errors="coerce")
        if pd.notna(parsed):
            return parsed.date()
    return date.today()
