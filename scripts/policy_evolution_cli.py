#!/usr/bin/env python3
"""CLI for Phase 14 policy/contract evolution workflows."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

import yaml

from v2.core.policy_evolution import default_policy_contract_evolution_store


def _load_data_file(path: str) -> Dict[str, Any]:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if p.suffix.lower() in {".yaml", ".yml"}:
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"Expected object payload in {path}")
    return data


def _print(payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser(description="Policy/contract evolution CLI (human-governed)")
    parser.add_argument("--store-dir", default=None)
    parser.add_argument("--policy-path", default=None)
    parser.add_argument("--tool-contract-path", default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    p_list_versions = sub.add_parser("list-versions")
    p_list_versions.add_argument("--kind", required=True)

    p_list_drafts = sub.add_parser("list-drafts")
    p_list_drafts.add_argument("--kind", required=True)
    p_list_drafts.add_argument("--status", default=None)

    p_create = sub.add_parser("create-draft")
    p_create.add_argument("--kind", required=True)
    p_create.add_argument("--author", required=True)
    p_create.add_argument("--summary", required=True)
    p_create.add_argument("--payload-file", required=True)
    p_create.add_argument("--modifications-file", default=None)

    p_review = sub.add_parser("review-draft")
    p_review.add_argument("--kind", required=True)
    p_review.add_argument("--draft-id", required=True)
    p_review.add_argument("--reviewer", required=True)
    p_review.add_argument("--decision", required=True, choices=["approve", "reject"])
    p_review.add_argument("--notes", default="")

    p_sim = sub.add_parser("simulate-draft")
    p_sim.add_argument("--kind", required=True)
    p_sim.add_argument("--draft-id", required=True)
    p_sim.add_argument("--envelopes-file", required=True)

    p_diff = sub.add_parser("diff-versions")
    p_diff.add_argument("--kind", required=True)
    p_diff.add_argument("--from-version", required=True)
    p_diff.add_argument("--to-version", required=True)

    p_activate = sub.add_parser("activate-draft")
    p_activate.add_argument("--kind", required=True)
    p_activate.add_argument("--draft-id", required=True)
    p_activate.add_argument("--author", required=True)
    p_activate.add_argument("--summary", default=None)

    p_revert = sub.add_parser("revert-version")
    p_revert.add_argument("--kind", required=True)
    p_revert.add_argument("--version-id", required=True)
    p_revert.add_argument("--author", required=True)
    p_revert.add_argument("--summary", required=True)

    args = parser.parse_args()
    store = default_policy_contract_evolution_store(
        store_dir=args.store_dir,
        policy_path=args.policy_path,
        tool_contract_path=args.tool_contract_path,
    )

    if args.command == "list-versions":
        _print(store.list_versions(args.kind))
        return 0

    if args.command == "list-drafts":
        _print(store.list_drafts(args.kind, status=args.status))
        return 0

    if args.command == "create-draft":
        payload = _load_data_file(args.payload_file)
        modifications = _load_data_file(args.modifications_file) if args.modifications_file else {}
        _print(
            store.create_draft(
                kind=args.kind,
                author=args.author,
                change_summary=args.summary,
                payload=payload,
                modifications=modifications,
            )
        )
        return 0

    if args.command == "review-draft":
        _print(
            store.review_draft(
                kind=args.kind,
                draft_id=args.draft_id,
                reviewer=args.reviewer,
                decision=args.decision,
                review_notes=args.notes,
            )
        )
        return 0

    if args.command == "simulate-draft":
        envelopes = _load_data_file(args.envelopes_file).get("envelopes", [])
        if not isinstance(envelopes, list):
            raise ValueError("envelopes-file must contain an object with key 'envelopes' as a list")
        _print(store.simulate_draft(kind=args.kind, draft_id=args.draft_id, envelopes=envelopes))
        return 0

    if args.command == "diff-versions":
        _print(
            store.diff_versions(
                kind=args.kind,
                from_version_id=args.from_version,
                to_version_id=args.to_version,
            )
        )
        return 0

    if args.command == "activate-draft":
        _print(
            store.activate_approved_draft(
                kind=args.kind,
                draft_id=args.draft_id,
                author=args.author,
                change_summary=args.summary,
            )
        )
        return 0

    if args.command == "revert-version":
        _print(
            store.revert_to_version(
                kind=args.kind,
                version_id=args.version_id,
                author=args.author,
                change_summary=args.summary,
            )
        )
        return 0

    raise ValueError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
