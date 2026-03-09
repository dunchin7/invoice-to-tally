import json

from tally.master_data import TallyMasterData, TallyMasterDataClient, TallyMasterRecord
from validation.pre_import import MappingRuleStore, PreImportResolver


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
    assert "Fallback policy is 'reject'" in reject_issues[0].message


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
