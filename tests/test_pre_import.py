import json
import sqlite3

from tally.master_data import TallyMasterData, TallyMasterDataClient, TallyMasterRecord
from validation.pre_import import MappingRuleStore, PreImportResolver, _top_suggestions


def _master_data() -> TallyMasterData:
    return TallyMasterData(
        parties=(TallyMasterRecord(name="ACME CORPORATION", code="P100", aliases=("Acme Corp",)),),
        ledgers=(TallyMasterRecord(name="SALES LEDGER", code="L200", aliases=("Sales",)),),
        stock_items=(TallyMasterRecord(name="WIDGET-A", code="S300", aliases=("Widget A",)),),
        fetched_at_epoch=1.0,
        source="test",
    )


def test_preimport_resolves_rule_and_alias(tmp_path):
    rules = {
        "global": {
            "party": {"acme corp": "ACME CORPORATION"},
            "ledger": {},
            "stock_item": {},
        },
        "tenants": {"default": {"party": {}, "ledger": {}, "stock_item": {}}},
    }
    rules_path = tmp_path / "rules.json"
    rules_path.write_text(json.dumps(rules), encoding="utf-8")

    resolver = PreImportResolver(_master_data(), MappingRuleStore(json_path=str(rules_path)))
    report = resolver.resolve_invoice(
        {
            "buyer": "Acme Corp",
            "seller": "Sales",
            "line_items": [{"description": "Widget A", "quantity": 1, "unit_price": 1, "total_price": 1}],
        },
        tenant_id="default",
    )

    assert report.blocking is False
    assert report.invoice["buyer"] == "ACME CORPORATION"
    assert report.invoice["seller"] == "SALES LEDGER"
    assert report.invoice["line_items"][0]["description"] == "WIDGET-A"


def test_preimport_reject_contains_actionable_details(tmp_path):
    rules_path = tmp_path / "rules.json"
    rules_path.write_text(
        json.dumps({"global": {"party": {}, "ledger": {}, "stock_item": {}}, "tenants": {}}),
        encoding="utf-8",
    )

    resolver = PreImportResolver(
        _master_data(),
        MappingRuleStore(json_path=str(rules_path)),
        fallback_policy={"ledger": "reject"},
    )
    report = resolver.resolve_invoice(
        {"buyer": "Unknown Buyer", "seller": "Unknown Ledger", "line_items": []}, tenant_id="default"
    )

    reject_issues = [issue for issue in report.issues if issue.entity_type == "ledger"]
    assert report.blocking is True
    assert reject_issues
    assert reject_issues[0].code == "MASTER_MAPPING_NOT_FOUND"
    assert "Add a tenant-specific mapping rule" in " ".join(reject_issues[0].remediation)


def test_preimport_accepts_code_based_mapping_rule(tmp_path):
    rules = {
        "global": {"party": {}, "ledger": {"sales tax": "L200"}, "stock_item": {}},
        "tenants": {"default": {"party": {}, "ledger": {}, "stock_item": {}}},
    }
    rules_path = tmp_path / "rules.json"
    rules_path.write_text(json.dumps(rules), encoding="utf-8")

    resolver = PreImportResolver(_master_data(), MappingRuleStore(json_path=str(rules_path)))
    report = resolver.resolve_invoice(
        {"buyer": "ACME CORPORATION", "seller": "Sales Tax", "line_items": []}, tenant_id="default"
    )

    ledger_resolution = [resolution for resolution in report.resolutions if resolution.entity_type == "ledger"][0]
    assert ledger_resolution.source == "rule"
    assert ledger_resolution.resolved_name == "SALES LEDGER"


def test_mapping_rule_store_upsert_sqlite(tmp_path):
    rules_path = tmp_path / "rules.json"
    rules_path.write_text(json.dumps({"global": {}, "tenants": {}}), encoding="utf-8")
    db_path = tmp_path / "rules.sqlite"

    store = MappingRuleStore(json_path=str(rules_path), sqlite_path=str(db_path))
    store.upsert("tenant-a", "party", "Acme Limited", "ACME CORPORATION")

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT tally_name FROM mapping_rules WHERE tenant_id = ? AND entity_type = ? AND normalized_value = ?",
            ("tenant-a", "party", "acme limited"),
        ).fetchone()

    assert row is not None
    assert row[0] == "ACME CORPORATION"


def test_master_data_client_collection_accessors_read_cache(tmp_path):
    cache_path = tmp_path / "cache.json"
    cache_path.write_text(
        json.dumps(
            {
                "parties": [{"name": "P", "code": "1", "aliases": []}],
                "ledgers": [{"name": "L", "code": "2", "aliases": []}],
                "stock_items": [{"name": "S", "code": "3", "aliases": []}],
                "fetched_at_epoch": 9999999999,
            }
        ),
        encoding="utf-8",
    )

    client = TallyMasterDataClient(base_url="http://localhost:9000", cache_path=str(cache_path), cache_ttl_seconds=9999999999)
    assert client.get_party_masters()[0].name == "P"
    assert client.get_ledger_masters()[0].name == "L"
    assert client.get_stock_item_masters()[0].name == "S"


def test_preimport_learns_on_approval_when_enabled(tmp_path):
    rules_path = tmp_path / "rules.json"
    rules_path.write_text(
        json.dumps(
            {
                "global": {"party": {}, "ledger": {}, "stock_item": {}},
                "tenants": {"default": {"party": {}, "ledger": {}, "stock_item": {}}},
                "settings": {"global": {"learn_rule_on_approval": True}, "tenants": {}},
            }
        ),
        encoding="utf-8",
    )

    resolver = PreImportResolver(
        _master_data(),
        MappingRuleStore(json_path=str(rules_path)),
        fallback_policy={"ledger": "auto_create"},
    )
    report = resolver.resolve_invoice(
        {"buyer": "ACME CORPORATION", "seller": "Unmapped Ledger", "line_items": []},
        tenant_id="default",
        approved=True,
        approved_by="reviewer-1",
    )

    assert len(report.learned_rules) == 1
    learned = report.learned_rules[0]
    assert learned["learned"] is True
    assert learned["duplicate"] is False
    assert learned["stored_in"] == "json"

    payload = json.loads(rules_path.read_text(encoding="utf-8"))
    assert payload["tenants"]["default"]["ledger"]["unmapped ledger"]["value"] == "Unmapped Ledger"
    assert payload["tenants"]["default"]["ledger"]["unmapped ledger"]["provenance"]["approved_by"] == "reviewer-1"


def test_preimport_does_not_learn_when_disabled(tmp_path):
    rules_path = tmp_path / "rules.json"
    rules_path.write_text(
        json.dumps(
            {
                "global": {"party": {}, "ledger": {}, "stock_item": {}},
                "tenants": {"default": {"party": {}, "ledger": {}, "stock_item": {}}},
                "settings": {"global": {"learn_rule_on_approval": False}, "tenants": {}},
            }
        ),
        encoding="utf-8",
    )

    resolver = PreImportResolver(
        _master_data(),
        MappingRuleStore(json_path=str(rules_path)),
        fallback_policy={"ledger": "auto_create"},
    )
    report = resolver.resolve_invoice(
        {"buyer": "ACME CORPORATION", "seller": "Unmapped Ledger", "line_items": []},
        tenant_id="default",
        approved=True,
    )

    assert report.learned_rules == ()
    payload = json.loads(rules_path.read_text(encoding="utf-8"))
    assert payload["tenants"]["default"]["ledger"] == {}


def test_preimport_learning_is_idempotent_for_duplicate_approvals(tmp_path):
    rules_path = tmp_path / "rules.json"
    rules_path.write_text(
        json.dumps(
            {
                "global": {"party": {}, "ledger": {}, "stock_item": {}},
                "tenants": {"default": {"party": {}, "ledger": {}, "stock_item": {}}},
                "settings": {"global": {"learn_rule_on_approval": True}, "tenants": {}},
            }
        ),
        encoding="utf-8",
    )

    store = MappingRuleStore(json_path=str(rules_path))
    resolver = PreImportResolver(_master_data(), store, fallback_policy={"ledger": "auto_create"})

    first = resolver.resolve_invoice(
        {"buyer": "ACME CORPORATION", "seller": "Unmapped Ledger", "line_items": []},
        tenant_id="default",
        approved=True,
    )
    second = resolver.resolve_invoice(
        {"buyer": "ACME CORPORATION", "seller": "Unmapped Ledger", "line_items": []},
        tenant_id="default",
        approved=True,
    )

    assert first.learned_rules[0]["learned"] is True
    assert second.learned_rules[0]["learned"] is False
    assert second.learned_rules[0]["duplicate"] is True
def test_top_suggestions_improves_ocr_noisy_vendor_ranking():
    records = (
        TallyMasterRecord(name="GLOBAL SOLUTIONS LLP", code="L001", aliases=("Global Sol",)),
        TallyMasterRecord(name="GLOBAL SOURCING LLP", code="L999", aliases=()),
        TallyMasterRecord(name="GREEN SUPPLIES", code="L123", aliases=()),
    )

    ranked = _top_suggestions("GL0BAL S0LUT10NS LLP", records, limit=2)

    assert ranked[0].record.name == "GLOBAL SOLUTIONS LLP"
    assert ranked[0].breakdown["edit_ratio"] > ranked[1].breakdown["edit_ratio"]
    assert ranked[0].breakdown["ocr_boost"] > 0


def test_preimport_issue_contains_ranked_suggestion_breakdown(tmp_path):
    rules_path = tmp_path / "rules.json"
    rules_path.write_text(
        json.dumps({"global": {"party": {}, "ledger": {}, "stock_item": {}}, "tenants": {}}),
        encoding="utf-8",
    )

    master = TallyMasterData(
        parties=(TallyMasterRecord(name="ACME INDUSTRIES", code="P101", aliases=("ACME Ind",)),),
        ledgers=(
            TallyMasterRecord(name="ORBITAL VENDORS", code="L100", aliases=("Orbital",)),
            TallyMasterRecord(name="ORANGE TRADERS", code="L200", aliases=()),
        ),
        stock_items=(),
        fetched_at_epoch=1.0,
        source="test",
    )
    resolver = PreImportResolver(master, MappingRuleStore(json_path=str(rules_path)))
    report = resolver.resolve_invoice(
        {"buyer": "ACME INDUSTRIES", "seller": "0RBITAL VEND0R5", "line_items": []}, tenant_id="default"
    )

    ledger_issue = [issue for issue in report.issues if issue.entity_type == "ledger"][0]
    assert ledger_issue.suggestions[0] == "ORBITAL VENDORS"
    assert ledger_issue.suggestion_score_breakdown
    assert ledger_issue.suggestion_score_breakdown[0]["weighted_score"] >= ledger_issue.suggestion_score_breakdown[1][
        "weighted_score"
    ]
