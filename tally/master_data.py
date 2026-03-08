from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import requests


@dataclass(frozen=True)
class TallyMasterRecord:
    name: str
    code: str = ""
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class TallyMasterData:
    parties: tuple[TallyMasterRecord, ...]
    ledgers: tuple[TallyMasterRecord, ...]
    stock_items: tuple[TallyMasterRecord, ...]
    fetched_at_epoch: float
    source: str


class TallyMasterDataClient:
    """Fetches and caches Tally master entities for pre-import validation."""

    def __init__(self, base_url: str, cache_path: str = "outputs/tally_master_cache.json", cache_ttl_seconds: int = 300, timeout_seconds: int = 10):
        self.base_url = base_url.rstrip("/")
        self.cache_path = Path(cache_path)
        self.cache_ttl_seconds = cache_ttl_seconds
        self.timeout_seconds = timeout_seconds

    def get_master_data(self, force_refresh: bool = False) -> TallyMasterData:
        if not force_refresh:
            cached = self._read_cache()
            if cached is not None:
                return cached

        live = self._fetch_from_tally()
        self._write_cache(live)
        return live

    def _fetch_from_tally(self) -> TallyMasterData:
        ledgers = self._fetch_collection("Ledger")
        stock_items = self._fetch_collection("Stock Item")
        parties = tuple(
            item
            for item in ledgers
            if any(token in item.name.lower() for token in ("debtor", "creditor", "customer", "vendor"))
        )

        return TallyMasterData(
            parties=parties,
            ledgers=ledgers,
            stock_items=stock_items,
            fetched_at_epoch=time.time(),
            source="live",
        )

    def _fetch_collection(self, object_type: str) -> tuple[TallyMasterRecord, ...]:
        xml_payload = f"""
<ENVELOPE>
  <HEADER>
    <TALLYREQUEST>Export Data</TALLYREQUEST>
  </HEADER>
  <BODY>
    <EXPORTDATA>
      <REQUESTDESC>
        <REPORTNAME>List of Accounts</REPORTNAME>
        <STATICVARIABLES>
          <SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
        </STATICVARIABLES>
      </REQUESTDESC>
      <REQUESTDATA>
        <TALLYMESSAGE>
          <COLLECTION NAME=\"Codex Master Pull\" ISMODIFY=\"No\">
            <TYPE>{object_type}</TYPE>
            <NATIVEMETHOD>Name</NATIVEMETHOD>
            <NATIVEMETHOD>MasterId</NATIVEMETHOD>
            <NATIVEMETHOD>Alias</NATIVEMETHOD>
          </COLLECTION>
        </TALLYMESSAGE>
      </REQUESTDATA>
    </EXPORTDATA>
  </BODY>
</ENVELOPE>
""".strip()

        response = requests.post(
            self.base_url,
            data=xml_payload.encode("utf-8"),
            headers={"Content-Type": "application/xml"},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()

        root = ET.fromstring(response.content)
        records: list[TallyMasterRecord] = []
        for obj in root.findall(".//COLLECTION/*"):
            name = (obj.findtext("NAME") or obj.findtext("Name") or "").strip()
            if not name:
                continue

            code = (obj.findtext("MASTERID") or obj.findtext("MasterId") or "").strip()
            alias_text = (obj.findtext("ALIAS") or obj.findtext("Alias") or "").strip()
            aliases = tuple(alias.strip() for alias in alias_text.split(",") if alias.strip()) if alias_text else ()
            records.append(TallyMasterRecord(name=name, code=code, aliases=aliases))

        return tuple(records)

    def _read_cache(self) -> TallyMasterData | None:
        if not self.cache_path.exists():
            return None

        payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
        age = time.time() - payload.get("fetched_at_epoch", 0)
        if age > self.cache_ttl_seconds:
            return None

        return TallyMasterData(
            parties=tuple(TallyMasterRecord(**row) for row in payload.get("parties", [])),
            ledgers=tuple(TallyMasterRecord(**row) for row in payload.get("ledgers", [])),
            stock_items=tuple(TallyMasterRecord(**row) for row in payload.get("stock_items", [])),
            fetched_at_epoch=float(payload.get("fetched_at_epoch", 0)),
            source="cache",
        )

    def _write_cache(self, data: TallyMasterData) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "parties": [asdict(item) for item in data.parties],
            "ledgers": [asdict(item) for item in data.ledgers],
            "stock_items": [asdict(item) for item in data.stock_items],
            "fetched_at_epoch": data.fetched_at_epoch,
        }
        self.cache_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_master_data_from_file(path: str) -> TallyMasterData:
    payload: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
    return TallyMasterData(
        parties=tuple(TallyMasterRecord(**row) for row in payload.get("parties", [])),
        ledgers=tuple(TallyMasterRecord(**row) for row in payload.get("ledgers", [])),
        stock_items=tuple(TallyMasterRecord(**row) for row in payload.get("stock_items", [])),
        fetched_at_epoch=float(payload.get("fetched_at_epoch", 0)),
        source=payload.get("source", "file"),
    )
