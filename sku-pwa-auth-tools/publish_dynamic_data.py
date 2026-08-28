from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from advanced_modules import data_quality_audit, next_task, purchase_reverse, route_decision
import build_dynamic_pwa_data as builder
from sheet_contracts import (
    load_master_rows_google,
    load_master_rows_xlsx,
    validate_master_rows,
    validate_snapshot_rows,
)

PAYLOAD_SCHEMA = "SKU-DYNAMIC-AUTOMATION-V4"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: Any, *, pretty: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2 if pretty else None, separators=None if pretty else (",", ":")),
        encoding="utf-8",
    )


def read_manifest(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def dataset_digest(records: list[dict[str, Any]]) -> str:
    stable = [{key: value for key, value in record.items() if key != "rowHash"} for record in records]
    return hashlib.sha256(builder.canonical(stable).encode()).hexdigest()


def enrich_advanced(records: list[dict], params: dict) -> dict:
    audits = []
    for record in records:
        audit = data_quality_audit(record)
        record["qualityAudit"] = audit
        record["routeDecision"] = route_decision(record)
        record["purchaseReverse"] = purchase_reverse(record.get("price"), record.get("weight"), params)
        record["nextTask"] = next_task(record)
        if audit["issueCount"]:
            audits.append({"skuKey": record.get("skuKey"), "sku": record.get("sku"), "audit": audit})
    return {
        "audited": len(records),
        "issueSkus": len(audits),
        "highRiskSkus": sum(item["audit"]["highRiskCount"] > 0 for item in audits),
        "issues": audits,
    }


def _finish_records(
    rows: list[dict],
    master: list[str],
    params: dict,
    master_rows: list[dict],
) -> tuple[list[dict], dict, dict, dict]:
    builder.base.validate_master_coverage(master, rows)
    contracts = {
        "master": validate_master_rows(master_rows),
        "snapshot": validate_snapshot_rows(rows),
    }
    records = builder.base.build_dataset(rows)
    for record in records:
        auto = builder.enrich_automation(record.get("source") or {}, params)
        record["automation"] = auto
        record["gapCount"] = auto["gaps"]["gapCount"]
        record["completion"] = auto["gaps"]["completion"]
        record["primaryBlocker"] = auto["gaps"]["primaryBlocker"]
        record["queueLevel"] = auto["queue"]["level"]
        record["queueScore"] = auto["queue"]["score"]
        record["structuralStop"] = auto["profitGate"].get("structuralStop")
        record["supplierCount"] = auto["sourcing"]["supplierCount"]
        builder.legacy_compat(record)
    audit = enrich_advanced(records, params)
    for record in records:
        record["rowHash"] = hashlib.sha256(
            builder.canonical(
                {
                    "source": record.get("source"),
                    "automation": record.get("automation"),
                    "audit": record.get("qualityAudit"),
                    "route": record.get("routeDecision"),
                    "reverse": record.get("purchaseReverse"),
                    "next": record.get("nextTask"),
                    "params": params,
                }
            ).encode()
        ).hexdigest()
    return records, params, audit, contracts


def build_records_xlsx(path: Path) -> tuple[list[dict], dict, dict, dict]:
    rows = builder.base.load_from_xlsx(path, builder.base.DEFAULT_WORKSHEET)
    master = builder.base.load_master_names_from_xlsx(path, builder.base.DEFAULT_MASTER_WORKSHEET)
    master_rows = load_master_rows_xlsx(path)
    params = builder.load_params_xlsx(path)
    return _finish_records(rows, master, params, master_rows)


def build_records_google(spreadsheet_id: str) -> tuple[list[dict], dict, dict, dict]:
    rows = builder.base.load_from_google(spreadsheet_id, builder.base.DEFAULT_WORKSHEET)
    master = builder.base.load_master_names_from_google(spreadsheet_id, builder.base.DEFAULT_MASTER_WORKSHEET)
    master_rows = load_master_rows_google(spreadsheet_id, builder.base._google_credentials())
    params = builder.load_params_google(spreadsheet_id)
    return _finish_records(rows, master, params, master_rows)


def previous_hashes(path: Path | None) -> dict[str, str]:
    if not path or not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {
        record["skuKey"]: record["rowHash"]
        for record in data
        if isinstance(record, dict) and record.get("skuKey") and record.get("rowHash")
    }


def contract_high_risk_count(contracts: dict[str, dict]) -> int:
    return sum(int(report.get("highRiskCount", 0)) for report in contracts.values())


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Deterministically build, audit and encrypt the SKU dataset; skip encryption when source data is unchanged."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--xlsx", type=Path)
    source.add_argument("--spreadsheet-id")
    parser.add_argument("--keyring", type=Path, required=True)
    parser.add_argument("--encrypt-tool", type=Path, default=HERE / "encrypt_pwa_public.py")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--previous-json", type=Path)
    parser.add_argument("--previous-manifest", type=Path)
    parser.add_argument("--status-file", type=Path)
    parser.add_argument("--skip-unchanged", action="store_true")
    parser.add_argument("--fail-high-risk", action="store_true", help="Also block on analytical model drift/outliers.")
    parser.add_argument("--fail-contract-risk", action="store_true", help="Block on duplicate IDs, invalid dates or shifted columns.")
    args = parser.parse_args()
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    status_file = args.status_file or output / "pipeline-status.json"

    if args.xlsx:
        records, params, audit, contracts = build_records_xlsx(args.xlsx)
    else:
        records, params, audit, contracts = build_records_google(args.spreadsheet_id)

    previous = previous_hashes(args.previous_json)
    current = {record["skuKey"]: record["rowHash"] for record in records}
    added = sorted(set(current) - set(previous))
    removed = sorted(set(previous) - set(current))
    changed = sorted(key for key in current.keys() & previous.keys() if current[key] != previous[key])
    dataset_sha = dataset_digest(records)
    prior_manifest = read_manifest(args.previous_manifest)
    contract_risks = contract_high_risk_count(contracts)

    private_audit = {"contracts": contracts, "analytics": audit}
    write_json(output / "quality-audit.private.json", private_audit)

    if args.fail_contract_risk and contract_risks:
        status = {
            "state": "BLOCKED_CONTRACT",
            "shouldPublish": False,
            "records": len(records),
            "datasetSha256": dataset_sha,
            "contractHighRiskCount": contract_risks,
        }
        write_json(status_file, status)
        raise SystemExit(f"high-risk sheet contract issues: {contract_risks}")
    if args.fail_high_risk and audit["highRiskSkus"]:
        status = {
            "state": "BLOCKED_ANALYTICS",
            "shouldPublish": False,
            "records": len(records),
            "datasetSha256": dataset_sha,
            "analyticsHighRiskSkus": audit["highRiskSkus"],
        }
        write_json(status_file, status)
        raise SystemExit(f"high-risk analytical data issues: {audit['highRiskSkus']}")

    unchanged = (
        bool(prior_manifest.get("datasetSha256"))
        and prior_manifest.get("datasetSha256") == dataset_sha
        and prior_manifest.get("records") == len(records)
    )
    if args.skip_unchanged and unchanged:
        status = {
            "state": "NO_CHANGE",
            "shouldPublish": False,
            "records": len(records),
            "version": dataset_sha[:16],
            "datasetSha256": dataset_sha,
            "contractHighRiskCount": contract_risks,
            "analyticsHighRiskSkus": audit["highRiskSkus"],
        }
        write_json(status_file, status)
        print(json.dumps(status, ensure_ascii=False, separators=(",", ":")))
        return

    plain = output / "new-pwa-data.json"
    write_json(plain, records, pretty=False)
    envelope = output / "sku-data.enc.json"
    process = subprocess.run(
        [
            sys.executable,
            str(args.encrypt_tool),
            "--input",
            str(plain),
            "--keyring",
            str(args.keyring),
            "--output",
            str(envelope),
        ],
        text=True,
        capture_output=True,
    )
    if process.returncode != 0:
        raise SystemExit(process.stderr or process.stdout)
    encrypted = json.loads(envelope.read_text(encoding="utf-8"))
    if encrypted.get("records") != len(records):
        raise SystemExit("encrypted envelope record mismatch")
    encrypted["payloadSchema"] = PAYLOAD_SCHEMA
    write_json(envelope, encrypted, pretty=False)
    envelope_sha = sha256_file(envelope)

    manifest = {
        "schema": "SKU-PWA-EXTERNAL-DATA-V4",
        "payloadSchema": PAYLOAD_SCHEMA,
        "version": dataset_sha[:16],
        "records": len(records),
        "datasetSha256": dataset_sha,
        "envelopeSha256": envelope_sha,
        "delta": {"added": len(added), "changed": len(changed), "removed": len(removed)},
        "stats": {
            "stop": sum(record.get("stage") == "STOP" for record in records),
            "profitKnown": sum(bool(record.get("profitKnown")) for record in records),
            "orPass": sum(bool(record.get("decisionOrPass")) for record in records),
            "modelRankEligible": sum(bool(record.get("profitRankEligible")) for record in records),
            "p1": sum(record.get("queueLevel") == "P1" for record in records),
            "structuralStop": sum(record.get("structuralStop") is True for record in records),
            "qualityIssueSkus": audit["issueSkus"],
            "qualityHighRiskSkus": audit["highRiskSkus"],
            "contractHighRiskCount": contract_risks,
        },
        "params": params,
    }
    write_json(output / "pwa-data-version.json", manifest)
    write_json(output / "delta.private.json", {"added": added, "changed": changed, "removed": removed})
    status = {
        "state": "CHANGED",
        "shouldPublish": True,
        "records": len(records),
        "version": manifest["version"],
        "payloadSchema": PAYLOAD_SCHEMA,
        "datasetSha256": dataset_sha,
        "envelopeSha256": envelope_sha,
        "delta": manifest["delta"],
        "stats": manifest["stats"],
    }
    write_json(status_file, status)
    print(json.dumps(status, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
