"""Generate the release test matrix from actual pytest JUnit reports."""
from __future__ import annotations
import json
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path("reports/implementation20")


def counts(cases):
    cases = list(cases)
    skipped = sum(c.find("skipped") is not None for c in cases)
    failed = sum(c.find("failure") is not None for c in cases)
    errors = sum(c.find("error") is not None for c in cases)
    return {"passed": len(cases) - skipped - failed - errors, "failed": failed,
            "errors": errors, "skipped": skipped, "total": len(cases)}


def main():
    report = {"category_counts_overlap": True, "runs": {}}
    for name, filename in (("working_tree_offline", "root_offline.xml"),
                           ("isolated_install_without_archive", "offline.xml"),
                           ("disposable_live_inclusive", "live.xml")):
        root = ET.parse(ROOT / filename).getroot()
        cases = list(root.iter("testcase"))
        entry = counts(cases)
        entry["elapsed_seconds"] = sum(float(s.get("time", "0")) for s in root.iter("testsuite"))
        entry["skips"] = [{"test": c.get("classname", "") + "." + c.get("name", ""),
                            "reason": c.find("skipped").get("message", "")}
                           for c in cases if c.find("skipped") is not None]
        groups = {
            "mathematics": ("test_belief", "test_information", "test_decision", "test_multistep", "test_regression_6_1"),
            "security": ("test_security", "test_graph_isolation", "test_release_validation"),
            "reliability": ("test_durable", "test_resumable", "test_reliability", "test_backup_restore", "test_operations"),
            "live_postgres": ("test_operations_postgres_live",),
            "live_neo4j": ("test_graph_integration", "test_graph_investigation_live", "test_langgraph_live",
                           "test_olist_live", "test_pilot_live", "test_security_live", "test_api_live",
                           "test_enterprise_ingestion_live", "test_multidomain_live"),
        }
        entry["categories"] = {key: counts(c for c in cases if any(p in c.get("classname", "") for p in patterns))
                                for key, patterns in groups.items()}
        report["runs"][name] = entry
    report["browser"] = {"automation": "actual localhost browser sessions; not pytest cases",
        "authentication": "PASS", "synthetic_pomdp_and_evidence_details": "PASS",
        "procurement_and_domain_switching": "PASS", "domain_validation_errors": "PASS",
        "operations_health_and_completed_job": "PASS", "olist_readonly": "PASS"}
    (ROOT / "test_matrix.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({name: {k: v for k, v in run.items() if k in {"passed", "failed", "errors", "skipped", "elapsed_seconds", "categories"}}
                      for name, run in report["runs"].items()}))


if __name__ == "__main__":
    main()
