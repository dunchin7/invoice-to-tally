from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from tally.master_data import TallyMasterData, TallyMasterRecord


FallbackPolicy = Literal["auto_create", "reject", "manual_review"]
MasterType = Literal["party", "ledger", "stock_item"]


@dataclass(frozen=True)
class MappingIssue:
    field: str
    entity_type: MasterType
    extracted_value: str
    message: str
    suggestions: tuple[str, ...] = ()
    suggestion_codes: tuple[str, ...] = ()
    action: Literal["auto_create", "reject", "manual_review"] = "manual_review"


@dataclass(frozen=True)
class EntityResolution:
    entity_type: MasterType
    extracted_value: str
    resolved_name: str | None
    resolved_code: str | None
    source: Literal["exact", "alias", "rule", "created", "unresolved"]


@dataclass(frozen=True)
class ResolutionReport:
    invoice: dict
    resolutions: tuple[EntityResolution, ...]
    issues: tuple[MappingIssue, ...]

    @property
    def blocking(self) -> bool:
        return any(issue.action == "reject" for issue in self.issues)


class MappingRuleStore:
    """Tenant-aware rule store using configurable JSON file + optional SQLite DB."""

    def __init__(self, json_path: str = "validation/config/mapping_rules.json", sqlite_path: str | None = None):
        self.json_path = Path(json_path)
        self.sqlite_path = sqlite_path

    def lookup(self, tenant_id: str, entity_type: MasterType, extracted_value: str) -> str | None:
        key = _key(extracted_value)

        db_value = self._lookup_sqlite(tenant_id, entity_type, key)
        if db_value:
            return db_value

        payload = self._load_json()
        tenant_section = payload.get("tenants", {}).get(tenant_id, {})
        for scope in (tenant_section, payload.get("global", {})):
            mapped = scope.get(entity_type, {}).get(key)
            if mapped:
                return str(mapped).strip()
        return None

    def _load_json(self) -> dict:
        if not self.json_path.exists():
            return {"global": {}, "tenants": {}}
        return json.loads(self.json_path.read_text(encoding="utf-8"))

    def _lookup_sqlite(self, tenant_id: str, entity_type: MasterType, normalized_value: str) -> str | None:
        if not self.sqlite_path:
            return None

        db_file = Path(self.sqlite_path)
        if not db_file.exists():
            return None

        with sqlite3.connect(db_file) as conn:
            row = conn.execute(
                """
                SELECT tally_name
                FROM mapping_rules
                WHERE tenant_id = ? AND entity_type = ? AND normalized_value = ?
                LIMIT 1
                """,
                (tenant_id, entity_type, normalized_value),
            ).fetchone()

        if row and row[0]:
            return str(row[0]).strip()
        return None


class PreImportResolver:
    def __init__(
        self,
        master_data: TallyMasterData,
        rule_store: MappingRuleStore,
        fallback_policy: dict[MasterType, FallbackPolicy] | None = None,
    ):
        self.master_data = master_data
        self.rule_store = rule_store
        self.fallback_policy = {
            "party": "manual_review",
            "ledger": "reject",
            "stock_item": "manual_review",
        }
        if fallback_policy:
            self.fallback_policy.update(fallback_policy)

    def resolve_invoice(self, invoice: dict, tenant_id: str) -> ResolutionReport:
        working = dict(invoice)
        resolutions: list[EntityResolution] = []
        issues: list[MappingIssue] = []

        buyer_name = _extract_name(invoice.get("buyer"))
        party_resolution, party_issue = self._resolve_entity(
            tenant_id=tenant_id,
            entity_type="party",
            field="buyer",
            extracted_value=buyer_name,
            master_records=self.master_data.parties or self.master_data.ledgers,
        )
        resolutions.append(party_resolution)
        if party_resolution.resolved_name:
            working["buyer"] = _replace_name(invoice.get("buyer"), party_resolution.resolved_name)
        if party_issue:
            issues.append(party_issue)

        seller_name = _extract_name(invoice.get("seller"))
        ledger_resolution, ledger_issue = self._resolve_entity(
            tenant_id=tenant_id,
            entity_type="ledger",
            field="seller",
            extracted_value=seller_name,
            master_records=self.master_data.ledgers,
        )
        resolutions.append(ledger_resolution)
        if ledger_resolution.resolved_name:
            working["seller"] = _replace_name(invoice.get("seller"), ledger_resolution.resolved_name)
        if ledger_issue:
            issues.append(ledger_issue)

        resolved_items = []
        for idx, item in enumerate(invoice.get("line_items", []), start=1):
            description = str(item.get("description", "")).strip()
            stock_resolution, stock_issue = self._resolve_entity(
                tenant_id=tenant_id,
                entity_type="stock_item",
                field=f"line_items[{idx}].description",
                extracted_value=description,
                master_records=self.master_data.stock_items,
            )
            resolutions.append(stock_resolution)

            next_item = dict(item)
            if stock_resolution.resolved_name:
                next_item["description"] = stock_resolution.resolved_name
            resolved_items.append(next_item)

            if stock_issue:
                issues.append(stock_issue)

        working["line_items"] = resolved_items
        return ResolutionReport(invoice=working, resolutions=tuple(resolutions), issues=tuple(issues))

    def _resolve_entity(
        self,
        tenant_id: str,
        entity_type: MasterType,
        field: str,
        extracted_value: str,
        master_records: tuple[TallyMasterRecord, ...],
    ) -> tuple[EntityResolution, MappingIssue | None]:
        if not extracted_value:
            issue = MappingIssue(
                field=field,
                entity_type=entity_type,
                extracted_value=extracted_value,
                message="No extracted value available for mapping.",
                action=self.fallback_policy[entity_type],
            )
            return EntityResolution(entity_type, extracted_value, None, None, "unresolved"), issue

        rule_match = self.rule_store.lookup(tenant_id, entity_type, extracted_value)
        if rule_match:
            matched = _find_record(rule_match, master_records)
            if matched:
                return EntityResolution(entity_type, extracted_value, matched.name, matched.code, "rule"), None

        exact = _find_record(extracted_value, master_records)
        if exact:
            return EntityResolution(entity_type, extracted_value, exact.name, exact.code, "exact"), None

        alias = _find_alias(extracted_value, master_records)
        if alias:
            return EntityResolution(entity_type, extracted_value, alias.name, alias.code, "alias"), None

        suggestions = _top_suggestions(extracted_value, master_records)
        policy = self.fallback_policy[entity_type]
        issue = MappingIssue(
            field=field,
            entity_type=entity_type,
            extracted_value=extracted_value,
            message=(
                f"Could not resolve {entity_type} '{extracted_value}' against Tally master data. "
                f"Fallback policy is '{policy}'. Add or update mapping rules for tenant '{tenant_id}', "
                "fix OCR extraction, or route this invoice to manual review."
            ),
            suggestions=tuple(candidate.name for candidate in suggestions),
            suggestion_codes=tuple(candidate.code for candidate in suggestions),
            action=policy,
        )

        if policy == "auto_create":
            return EntityResolution(entity_type, extracted_value, extracted_value, None, "created"), issue

        return EntityResolution(entity_type, extracted_value, None, None, "unresolved"), issue


def _key(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _extract_name(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return str(value.get("name", "")).strip()
    return ""


def _replace_name(value: object, resolved_name: str) -> object:
    if isinstance(value, dict):
        next_value = dict(value)
        next_value["name"] = resolved_name
        return next_value
    return resolved_name


def _find_record(name: str, records: tuple[TallyMasterRecord, ...]) -> TallyMasterRecord | None:
    key = _key(name)
    return next((record for record in records if _key(record.name) == key), None)


def _find_alias(name: str, records: tuple[TallyMasterRecord, ...]) -> TallyMasterRecord | None:
    key = _key(name)
    for record in records:
        if any(_key(alias) == key for alias in record.aliases):
            return record
    return None


def _top_suggestions(value: str, records: tuple[TallyMasterRecord, ...], limit: int = 3) -> tuple[TallyMasterRecord, ...]:
    target = _key(value)
    scored: list[tuple[int, TallyMasterRecord]] = []
    for record in records:
        name_key = _key(record.name)
        overlap = len(set(target.split()) & set(name_key.split()))
        if overlap > 0:
            scored.append((overlap, record))

    ranked = [record for _, record in sorted(scored, key=lambda row: (-row[0], row[1].name))[:limit]]
    return tuple(ranked)
