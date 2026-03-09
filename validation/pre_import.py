from __future__ import annotations

import json
import math
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from tally.master_data import TallyMasterData, TallyMasterRecord


FallbackPolicy = Literal["auto_create", "reject", "manual_review"]
MasterType = Literal["party", "ledger", "stock_item"]


@dataclass(frozen=True)
class MappingIssue:
    code: str
    field: str
    entity_type: MasterType
    extracted_value: str
    message: str
    suggestions: tuple[str, ...] = ()
    suggestion_codes: tuple[str, ...] = ()
    suggestion_score_breakdown: tuple[dict[str, float | str], ...] = ()
    remediation: tuple[str, ...] = ()
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
    learned_rules: tuple[dict, ...] = ()

    @property
    def blocking(self) -> bool:
        return any(issue.action == "reject" for issue in self.issues)


@dataclass(frozen=True)
class SuggestionScore:
    record: TallyMasterRecord
    score: float
    breakdown: dict[str, float | str]


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
            mapped_value = self._mapping_value(mapped)
            if mapped_value:
                return mapped_value
        return None

    def should_learn_rule_on_approval(self, tenant_id: str) -> bool:
        payload = self._load_json()
        tenant_setting = payload.get("settings", {}).get("tenants", {}).get(tenant_id, {}).get("learn_rule_on_approval")
        if tenant_setting is not None:
            return bool(tenant_setting)
        global_setting = payload.get("settings", {}).get("global", {}).get("learn_rule_on_approval")
        if global_setting is not None:
            return bool(global_setting)
        return False

    def upsert(self, tenant_id: str, entity_type: MasterType, extracted_value: str, tally_name_or_code: str) -> None:
        """Persist a tenant-specific rule in SQLite when configured."""
        if not self.sqlite_path:
            return

        db_file = Path(self.sqlite_path)
        db_file.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(db_file) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS mapping_rules (
                    tenant_id TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    normalized_value TEXT NOT NULL,
                    tally_name TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, entity_type, normalized_value)
                )
                """
            )
            conn.execute(
                """
                INSERT INTO mapping_rules (tenant_id, entity_type, normalized_value, tally_name)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(tenant_id, entity_type, normalized_value)
                DO UPDATE SET tally_name = excluded.tally_name
                """,
                (tenant_id, entity_type, _key(extracted_value), tally_name_or_code.strip()),
            )
            conn.commit()

    def learn_rule_on_approval(
        self,
        tenant_id: str,
        entity_type: MasterType,
        extracted_value: str,
        tally_name_or_code: str,
        provenance: dict,
    ) -> dict:
        normalized_value = _key(extracted_value)
        mapped_value = tally_name_or_code.strip()
        existing = self.lookup(tenant_id, entity_type, extracted_value)
        if existing and _key(existing) == _key(mapped_value):
            return {
                "entity_type": entity_type,
                "extracted_value": extracted_value,
                "mapped_value": mapped_value,
                "learned": False,
                "duplicate": True,
                "stored_in": "none",
            }

        if self.sqlite_path:
            self._upsert_sqlite_with_provenance(tenant_id, entity_type, normalized_value, mapped_value, provenance)
            return {
                "entity_type": entity_type,
                "extracted_value": extracted_value,
                "mapped_value": mapped_value,
                "learned": True,
                "duplicate": False,
                "stored_in": "sqlite",
            }

        self._upsert_json_with_provenance(tenant_id, entity_type, normalized_value, mapped_value, provenance)
        return {
            "entity_type": entity_type,
            "extracted_value": extracted_value,
            "mapped_value": mapped_value,
            "learned": True,
            "duplicate": False,
            "stored_in": "json",
        }

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

    @staticmethod
    def _mapping_value(raw_mapping: object) -> str | None:
        if isinstance(raw_mapping, dict):
            value = raw_mapping.get("value")
            if value:
                return str(value).strip()
            return None
        if raw_mapping:
            return str(raw_mapping).strip()
        return None

    def _upsert_sqlite_with_provenance(
        self,
        tenant_id: str,
        entity_type: MasterType,
        normalized_value: str,
        mapped_value: str,
        provenance: dict,
    ) -> None:
        db_file = Path(self.sqlite_path or "")
        db_file.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(db_file) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS mapping_rules (
                    tenant_id TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    normalized_value TEXT NOT NULL,
                    tally_name TEXT NOT NULL,
                    provenance_json TEXT,
                    learned_at TEXT,
                    PRIMARY KEY (tenant_id, entity_type, normalized_value)
                )
                """
            )
            table_info = conn.execute("PRAGMA table_info(mapping_rules)").fetchall()
            columns = {row[1] for row in table_info}
            if "provenance_json" not in columns:
                conn.execute("ALTER TABLE mapping_rules ADD COLUMN provenance_json TEXT")
            if "learned_at" not in columns:
                conn.execute("ALTER TABLE mapping_rules ADD COLUMN learned_at TEXT")

            conn.execute(
                """
                INSERT INTO mapping_rules (tenant_id, entity_type, normalized_value, tally_name, provenance_json, learned_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id, entity_type, normalized_value)
                DO UPDATE SET
                    tally_name = excluded.tally_name,
                    provenance_json = excluded.provenance_json,
                    learned_at = excluded.learned_at
                """,
                (
                    tenant_id,
                    entity_type,
                    normalized_value,
                    mapped_value,
                    json.dumps(provenance),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            conn.commit()

    def _upsert_json_with_provenance(
        self,
        tenant_id: str,
        entity_type: MasterType,
        normalized_value: str,
        mapped_value: str,
        provenance: dict,
    ) -> None:
        payload = self._load_json()
        tenants = payload.setdefault("tenants", {})
        tenant_rules = tenants.setdefault(tenant_id, {})
        entity_rules = tenant_rules.setdefault(entity_type, {})
        entity_rules[normalized_value] = {
            "value": mapped_value,
            "provenance": provenance,
            "learned_at": datetime.now(timezone.utc).isoformat(),
        }
        self.json_path.parent.mkdir(parents=True, exist_ok=True)
        self.json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


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

    def resolve_invoice(self, invoice: dict, tenant_id: str, approved: bool = False, approved_by: str = "system") -> ResolutionReport:
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
        learned_rules: list[dict] = []
        if approved and self.rule_store.should_learn_rule_on_approval(tenant_id):
            for resolution in resolutions:
                if resolution.source != "created" or not resolution.resolved_name:
                    continue
                learned_rules.append(
                    self.rule_store.learn_rule_on_approval(
                        tenant_id=tenant_id,
                        entity_type=resolution.entity_type,
                        extracted_value=resolution.extracted_value,
                        tally_name_or_code=resolution.resolved_name,
                        provenance={
                            "source": "approval",
                            "approved_by": approved_by,
                            "tenant_id": tenant_id,
                        },
                    )
                )

        return ResolutionReport(
            invoice=working,
            resolutions=tuple(resolutions),
            issues=tuple(issues),
            learned_rules=tuple(learned_rules),
        )

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
                code="MISSING_EXTRACTED_VALUE",
                field=field,
                entity_type=entity_type,
                extracted_value=extracted_value,
                message="No extracted value available for mapping.",
                remediation=(
                    "Improve OCR/LLM extraction quality for this field.",
                    "If this is optional, add a tenant rule to map an empty value to a safe default.",
                ),
                action=self.fallback_policy[entity_type],
            )
            return EntityResolution(entity_type, extracted_value, None, None, "unresolved"), issue

        rule_match = self.rule_store.lookup(tenant_id, entity_type, extracted_value)
        if rule_match:
            matched = _find_record(rule_match, master_records) or _find_record_by_code(rule_match, master_records)
            if matched:
                return EntityResolution(entity_type, extracted_value, matched.name, matched.code, "rule"), None

        exact = _find_record(extracted_value, master_records) or _find_record_by_code(extracted_value, master_records)
        if exact:
            return EntityResolution(entity_type, extracted_value, exact.name, exact.code, "exact"), None

        alias = _find_alias(extracted_value, master_records)
        if alias:
            return EntityResolution(entity_type, extracted_value, alias.name, alias.code, "alias"), None

        suggestions = _top_suggestions(extracted_value, master_records)
        policy = self.fallback_policy[entity_type]
        issue = MappingIssue(
            code="MASTER_MAPPING_NOT_FOUND",
            field=field,
            entity_type=entity_type,
            extracted_value=extracted_value,
            message=(
                f"Could not resolve {entity_type} '{extracted_value}' against Tally master data. "
                f"Fallback policy is '{policy}'. Add or update mapping rules for tenant '{tenant_id}', "
                "fix OCR extraction, or route this invoice to manual review."
            ),
            suggestions=tuple(candidate.record.name for candidate in suggestions),
            suggestion_codes=tuple(candidate.record.code for candidate in suggestions),
            suggestion_score_breakdown=tuple(candidate.breakdown for candidate in suggestions),
            remediation=(
                "Use one of the suggested master names/codes.",
                "Add a tenant-specific mapping rule in JSON/SQLite.",
                "Switch fallback policy to 'auto_create' only if governance allows it.",
            ),
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


def _find_record_by_code(code: str, records: tuple[TallyMasterRecord, ...]) -> TallyMasterRecord | None:
    key = _key(code)
    return next((record for record in records if record.code and _key(record.code) == key), None)


def _top_suggestions(value: str, records: tuple[TallyMasterRecord, ...], limit: int = 3) -> tuple[SuggestionScore, ...]:
    target = _key(value)
    fuzzy_available = _rapidfuzz_available()
    ranked: list[SuggestionScore] = []

    for record in records:
        best_score = -math.inf
        best_breakdown: dict[str, float | str] | None = None
        for candidate_value, source in _candidate_names(record):
            score, breakdown = _weighted_similarity(target, _key(candidate_value), source=source, fuzzy_available=fuzzy_available)
            if score > best_score:
                best_score = score
                best_breakdown = breakdown

        if best_breakdown is None:
            continue

        ranked.append(SuggestionScore(record=record, score=best_score, breakdown=best_breakdown))

    ranked.sort(key=lambda row: (-row.score, row.record.name))
    return tuple(ranked[:limit])


def _candidate_names(record: TallyMasterRecord) -> tuple[tuple[str, str], ...]:
    values: list[tuple[str, str]] = [(record.name, "name")]
    values.extend((alias, "alias") for alias in record.aliases)
    return tuple(values)


def _weighted_similarity(left: str, right: str, source: str, fuzzy_available: bool) -> tuple[float, dict[str, float | str]]:
    normalized_left = _normalize_ocr_confusions(left)
    normalized_right = _normalize_ocr_confusions(right)

    edit_ratio = _normalized_levenshtein(normalized_left, normalized_right)
    token_ratio = _token_sort_ratio(normalized_left, normalized_right)
    token_overlap = _token_overlap(normalized_left, normalized_right)
    alias_boost = 0.1 if source == "alias" else 0.0
    ocr_boost = 0.05 if left != normalized_left or right != normalized_right else 0.0

    score = (0.4 * edit_ratio) + (0.35 * token_ratio) + (0.15 * token_overlap) + alias_boost + ocr_boost

    return score, {
        "matched_on": source,
        "weighted_score": round(score, 6),
        "edit_ratio": round(edit_ratio, 6),
        "token_sort_ratio": round(token_ratio, 6),
        "token_overlap": round(token_overlap, 6),
        "alias_boost": round(alias_boost, 6),
        "ocr_boost": round(ocr_boost, 6),
        "fuzzy_backend": "rapidfuzz" if fuzzy_available else "builtin",
    }


def _rapidfuzz_available() -> bool:
    try:
        import rapidfuzz  # noqa: F401
    except ImportError:
        return False
    return True


def _normalized_levenshtein(left: str, right: str) -> float:
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0

    previous = list(range(len(right) + 1))
    for i, l_char in enumerate(left, start=1):
        current = [i]
        for j, r_char in enumerate(right, start=1):
            insertions = previous[j] + 1
            deletions = current[j - 1] + 1
            substitutions = previous[j - 1] + (0 if l_char == r_char else 1)
            current.append(min(insertions, deletions, substitutions))
        previous = current

    distance = previous[-1]
    denominator = max(len(left), len(right))
    return 1.0 - (distance / denominator)


def _token_sort_ratio(left: str, right: str) -> float:
    left_sorted = " ".join(sorted(left.split()))
    right_sorted = " ".join(sorted(right.split()))
    return _normalized_levenshtein(left_sorted, right_sorted)


def _token_overlap(left: str, right: str) -> float:
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    if not left_tokens and not right_tokens:
        return 1.0
    union = left_tokens | right_tokens
    if not union:
        return 0.0
    return len(left_tokens & right_tokens) / len(union)


def _normalize_ocr_confusions(value: str) -> str:
    table = str.maketrans({
        "0": "o",
        "1": "l",
        "5": "s",
        "8": "b",
    })
    return value.translate(table)
