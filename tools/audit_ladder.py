#!/usr/bin/env python3
"""Deterministic ladder audit for PHASE promotion checklist documents.

This script scans docs/PHASE*_PROMOTION_CHECKLIST.md and produces a
deterministic markdown report with PASS/FAIL results per phase.

Implementation constraints:
- stdlib only
- regex + lightweight markdown heading detection
- fail-closed: missing required signals are reported as FAIL with NOT_FOUND
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


PHASE_FILE_RE = re.compile(r"^PHASE(\d+)_PROMOTION_CHECKLIST\.md$")


@dataclass(frozen=True)
class Heading:
    level: int
    title: str
    line: int
    start_idx: int
    end_idx: int


@dataclass
class Finding:
    check: str
    passed: bool
    reason: str
    anchor: str


@dataclass
class PhaseAudit:
    phase: int
    path: Path
    level_name: str
    contracts: List[str]
    upstream_refs: List[int]
    linked_ids: List[str]
    uniqueness_signals: List[str]
    rejection_codes: List[str]
    priority_ordering_required: bool
    priority_ordering_present: bool
    priority_ordering_codes: List[str]
    has_hard_invariants: bool
    has_negative_guarantees: bool
    has_preservation_clause: bool
    mentions_runtime_change: bool
    findings: List[Finding] = field(default_factory=list)

    @property
    def status(self) -> str:
        return "PASS" if all(f.passed for f in self.findings) else "FAIL"


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Audit docs/PHASE*_PROMOTION_CHECKLIST.md for deterministic governance "
            "signals and emit a markdown report."
        )
    )
    parser.add_argument(
        "--docs-dir",
        default="docs",
        help="Directory containing PHASE promotion checklists (default: docs).",
    )
    parser.add_argument(
        "--out",
        default="docs/LADDER_AUDIT_REPORT.md",
        help="Output markdown report path (default: docs/LADDER_AUDIT_REPORT.md).",
    )
    return parser.parse_args(argv)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def discover_phase_files(docs_dir: Path) -> List[Tuple[int, Path]]:
    out: List[Tuple[int, Path]] = []
    for child in sorted(docs_dir.iterdir(), key=lambda p: p.name):
        if not child.is_file():
            continue
        m = PHASE_FILE_RE.match(child.name)
        if not m:
            continue
        out.append((int(m.group(1)), child))
    out.sort(key=lambda x: x[0])
    return out


def build_headings(text: str) -> Tuple[List[str], List[Heading]]:
    lines = text.splitlines()
    raw: List[Tuple[int, str, int, int]] = []
    for idx, line in enumerate(lines):
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if not m:
            continue
        raw.append((len(m.group(1)), m.group(2).strip(), idx + 1, idx))
    headings: List[Heading] = []
    for i, (level, title, line_no, start_idx) in enumerate(raw):
        end_idx = len(lines)
        for j in range(i + 1, len(raw)):
            nxt_level, _, _, nxt_start = raw[j]
            if nxt_level <= level:
                end_idx = nxt_start
                break
        headings.append(
            Heading(
                level=level,
                title=title,
                line=line_no,
                start_idx=start_idx,
                end_idx=end_idx,
            )
        )
    return lines, headings


def find_heading(headings: Sequence[Heading], pattern: str) -> Optional[Heading]:
    rx = re.compile(pattern, re.IGNORECASE)
    for h in headings:
        if rx.search(h.title):
            return h
    return None


def section_text(lines: Sequence[str], heading: Optional[Heading]) -> str:
    if heading is None:
        return ""
    return "\n".join(lines[heading.start_idx : heading.end_idx])


def anchor(path: Path, heading: Optional[Heading]) -> str:
    if heading is None:
        return f"{path.as_posix()}:1 (NOT_FOUND)"
    return f'{path.as_posix()}:{heading.line} ("## {heading.title}")'


def extract_level_name(text: str) -> str:
    m = re.search(r"Level\s+\d+\s+\(`([^`]+)`\)", text)
    if m:
        return m.group(1).strip()
    m = re.search(r"^#\s*Phase\s+\d+\s+Promotion Checklist(?:\s*\(([^)]+)\))?", text, re.M)
    if m and m.group(1):
        return m.group(1).strip()
    return "NOT_FOUND"


def extract_contract_blocks(text: str) -> List[str]:
    blocks: List[str] = []
    for m in re.finditer(r"```yaml\s*\n(.*?)\n```", text, re.S):
        block = m.group(1)
        if re.search(r"^\s*contract:\s*", block, re.M):
            blocks.append(block)
    return blocks


def extract_contract_names(blocks: Sequence[str], text: str) -> List[str]:
    names: List[str] = []
    for block in blocks:
        for m in re.finditer(r"^\s*contract:\s*([A-Za-z0-9_.-]+)\s*$", block, re.M):
            names.append(m.group(1).strip())
    if names:
        return sorted(dict.fromkeys(names))
    fallback = re.findall(r"`([a-z][a-z0-9_]*\.v[0-9]+)`", text, re.I)
    return sorted(dict.fromkeys(fallback))


def extract_required_keys(yaml_text: str) -> List[str]:
    lines = yaml_text.splitlines()
    keys: List[str] = []
    in_required = False
    required_indent = -1
    for line in lines:
        if not in_required and re.match(r"^\s*required:\s*$", line):
            in_required = True
            required_indent = len(line) - len(line.lstrip(" "))
            continue
        if not in_required:
            continue
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent <= required_indent:
            break
        m = re.match(r"^\s*-\s*([A-Za-z0-9_]+)\s*$", line)
        if m:
            keys.append(m.group(1))
    return keys


def extract_linked_ids(yaml_text: str) -> List[str]:
    ids = re.findall(r"\blinked_[a-z0-9_]+_id\b", yaml_text)
    return sorted(dict.fromkeys(ids))


def find_key_block(lines: Sequence[str], key: str) -> Tuple[Optional[List[str]], Optional[int]]:
    pattern = re.compile(rf"^\s*{re.escape(key)}:\s*$")
    for i, line in enumerate(lines):
        if not pattern.match(line):
            continue
        base_indent = len(line) - len(line.lstrip(" "))
        block: List[str] = []
        j = i + 1
        while j < len(lines):
            nxt = lines[j]
            if not nxt.strip():
                block.append(nxt)
                j += 1
                continue
            indent = len(nxt) - len(nxt.lstrip(" "))
            if indent <= base_indent:
                break
            block.append(nxt)
            j += 1
        return block, i + 1
    return None, None


def const_value_for_key(lines: Sequence[str], key: str) -> Optional[str]:
    # inline forms first
    inline_pat = re.compile(rf"^\s*{re.escape(key)}:\s*(?:const:\s*)?(true|false)\s*$")
    for line in lines:
        m = inline_pat.match(line)
        if m:
            return m.group(1)
    block, _ = find_key_block(lines, key)
    if block is None:
        return None
    for line in block:
        m = re.search(r"\bconst:\s*(true|false)\b", line)
        if m:
            return m.group(1)
    return None


def list_codes_from_section(text: str) -> List[str]:
    codes: List[str] = []
    for m in re.finditer(r"`([A-Z0-9_]{3,})`", text):
        codes.append(m.group(1))
    return list(dict.fromkeys(codes))


def list_codes_from_priority_block(yaml_text: str) -> List[str]:
    lines = yaml_text.splitlines()
    in_block = False
    base_indent = -1
    out: List[str] = []
    for line in lines:
        if not in_block and re.match(r"^\s*rejection_code_priority_order:\s*$", line):
            in_block = True
            base_indent = len(line) - len(line.lstrip(" "))
            continue
        if not in_block:
            continue
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent <= base_indent:
            break
        m = re.match(r"^\s*-\s*([A-Z0-9_]+)\s*$", line)
        if m:
            out.append(m.group(1))
    return out


def find_uniqueness_signals(text: str) -> List[str]:
    out: List[str] = []
    for line in text.splitlines():
        cleaned = line.strip()
        if not cleaned:
            continue
        if re.search(r"\bExactly one\b", cleaned, re.I):
            out.append(cleaned)
            continue
        if re.search(r"\bone\b.*\bper\b", cleaned, re.I):
            out.append(cleaned)
    return list(dict.fromkeys(out))


def extract_upstream_phase_refs(section: str) -> List[int]:
    nums = [int(x) for x in re.findall(r"Phase\s+(\d+)", section)]
    return sorted(dict.fromkeys(nums))


def extract_state_enum_map(yaml_text: str) -> Dict[str, Tuple[str, ...]]:
    """Extract enum sets for fields with state/outcome-like names."""
    lines = yaml_text.splitlines()
    out: Dict[str, Tuple[str, ...]] = {}
    i = 0
    while i < len(lines):
        m = re.match(r"^\s*([a-z0-9_]+):\s*$", lines[i], re.I)
        if not m:
            i += 1
            continue
        key = m.group(1)
        key_l = key.lower()
        interesting = ("state" in key_l) or ("outcome" in key_l)
        indent = len(lines[i]) - len(lines[i].lstrip(" "))
        j = i + 1
        block: List[str] = []
        while j < len(lines):
            if not lines[j].strip():
                block.append(lines[j])
                j += 1
                continue
            ind = len(lines[j]) - len(lines[j].lstrip(" "))
            if ind <= indent:
                break
            block.append(lines[j])
            j += 1
        if interesting:
            enum_match = None
            for b in block:
                enum_match = re.search(r"enum:\s*\[([^\]]*)\]", b)
                if enum_match:
                    break
            if enum_match:
                vals = tuple(
                    x.strip().strip("'\"")
                    for x in enum_match.group(1).split(",")
                    if x.strip()
                )
                out[key] = vals
        i = j
    return out


EXPECTED_LINK_KEY: Dict[int, str] = {
    58: "linked_planning_session_id",
    59: "linked_plan_acceptance_id",
    60: "linked_plan_approval_id",
    61: "linked_plan_authorization_id",
    62: "linked_execution_scope_binding_id",
    63: "linked_execution_preconditions_id",
    64: "linked_execution_readiness_id",
    65: "linked_readiness_attestation_id",
    66: "linked_execution_arming_authorization_id",
    67: "linked_execution_arming_state_id",
}


LINKED_KEY_TO_PHASE: Dict[str, int] = {
    "linked_human_replanning_intent_id": 54,
    "linked_planning_context_id": 55,
    "linked_planning_output_id": 56,
    "linked_planning_session_id": 57,
    "linked_plan_acceptance_id": 58,
    "linked_plan_approval_id": 59,
    "linked_plan_authorization_id": 60,
    "linked_execution_scope_binding_id": 61,
    "linked_execution_preconditions_id": 62,
    "linked_execution_readiness_id": 63,
    "linked_readiness_attestation_id": 64,
    "linked_execution_arming_authorization_id": 65,
    "linked_execution_arming_state_id": 66,
}


def audit_phase(phase: int, path: Path) -> PhaseAudit:
    text = read_text(path)
    lines, headings = build_headings(text)
    level_name = extract_level_name(text)

    contract_heading = find_heading(headings, r"contract v1")
    hard_heading = find_heading(headings, r"Hard Invariants")
    neg_heading = find_heading(headings, r"Deterministic Negative Guarantees")
    upstream_heading = find_heading(headings, r"Required Upstream Artifacts|Upstream Preconditions")
    reject_heading = find_heading(headings, r"Deterministic Rejection Codes")
    preserve_heading = find_heading(headings, r"Explicit Preservation of Phases")
    phase_status_heading = find_heading(headings, r"Phase\s+\d+\s+Status")

    contract_blocks = extract_contract_blocks(text)
    contract_names = extract_contract_names(contract_blocks, text)
    primary_yaml = contract_blocks[0] if contract_blocks else ""
    yaml_lines = primary_yaml.splitlines()

    upstream_text = section_text(lines, upstream_heading) or text
    upstream_refs = extract_upstream_phase_refs(upstream_text)
    linked_ids = extract_linked_ids(primary_yaml)
    uniqueness_signals = find_uniqueness_signals(text)

    reject_text = section_text(lines, reject_heading)
    rejection_codes = list_codes_from_section(reject_text)

    priority_required = bool(re.search(r"priority ordering|with priority", text, re.I))
    priority_codes = list_codes_from_priority_block(primary_yaml)
    priority_present = bool(priority_codes)

    has_hard_invariants = hard_heading is not None and bool(
        re.search(r"^\s*-\s*\[[xX ]\]", section_text(lines, hard_heading), re.M)
    )
    has_negative_guarantees = neg_heading is not None and bool(
        re.search(r"^\s*-\s*\[[xX ]\]", section_text(lines, neg_heading), re.M)
    )
    has_preservation_clause = preserve_heading is not None

    mentions_runtime_change = False
    runtime_status = "NOT_FOUND"
    if phase_status_heading:
        status_text = section_text(lines, phase_status_heading)
        m = re.search(r"Runtime delta:\s*([^\n]+)", status_text, re.I)
        if m:
            runtime_status = m.group(1).strip().lower()
            mentions_runtime_change = runtime_status not in {"none", "`none`"}

    audit = PhaseAudit(
        phase=phase,
        path=path,
        level_name=level_name,
        contracts=contract_names,
        upstream_refs=upstream_refs,
        linked_ids=linked_ids,
        uniqueness_signals=uniqueness_signals,
        rejection_codes=rejection_codes,
        priority_ordering_required=priority_required,
        priority_ordering_present=priority_present,
        priority_ordering_codes=priority_codes,
        has_hard_invariants=has_hard_invariants,
        has_negative_guarantees=has_negative_guarantees,
        has_preservation_clause=has_preservation_clause,
        mentions_runtime_change=mentions_runtime_change,
    )

    def add(check: str, passed: bool, reason: str, where: Optional[Heading]) -> None:
        audit.findings.append(Finding(check=check, passed=passed, reason=reason, anchor=anchor(path, where)))

    # Presence checks
    add(
        "level_name_found",
        level_name != "NOT_FOUND",
        "PASS" if level_name != "NOT_FOUND" else "NOT_FOUND: could not parse level name",
        phase_status_heading or find_heading(headings, r"Purpose"),
    )
    add(
        "contract_found",
        bool(contract_names),
        "PASS" if contract_names else "NOT_FOUND: contract name not found",
        contract_heading,
    )
    add(
        "hard_invariants_present",
        has_hard_invariants,
        "PASS" if has_hard_invariants else "NOT_FOUND: hard invariants checklist signals missing",
        hard_heading,
    )
    add(
        "negative_guarantees_present",
        has_negative_guarantees,
        "PASS" if has_negative_guarantees else "NOT_FOUND: deterministic negative guarantees missing",
        neg_heading,
    )

    # Authority checks
    if primary_yaml:
        exec_const = const_value_for_key(yaml_lines, "execution_enabled")
        add(
            "execution_enabled_false",
            exec_const == "false",
            "PASS" if exec_const == "false" else f"NOT_FOUND/INVALID: execution_enabled const false not found (value={exec_const})",
            contract_heading,
        )
        auth_block, _ = find_key_block(yaml_lines, "authority_guarantees")
        if auth_block is None:
            add(
                "authority_guarantees_all_false",
                False,
                "NOT_FOUND: authority_guarantees block missing",
                contract_heading,
            )
        else:
            block_text = "\n".join(auth_block)
            has_false = bool(re.search(r"\bconst:\s*false\b", block_text))
            has_true = bool(re.search(r"\bconst:\s*true\b", block_text))
            has_bool = bool(re.search(r"\btype:\s*boolean\b", block_text))
            passed = has_false and (not has_true) and (not has_bool)
            if passed:
                reason = "PASS"
            else:
                reasons: List[str] = []
                if not has_false:
                    reasons.append("NOT_FOUND: no const false in authority_guarantees")
                if has_true:
                    reasons.append("INVALID: const true found in authority_guarantees")
                if has_bool:
                    reasons.append("INVALID: non-constant boolean found in authority_guarantees")
                reason = "; ".join(reasons)
            add("authority_guarantees_all_false", passed, reason, contract_heading)
    else:
        add(
            "execution_enabled_false",
            False,
            "NOT_FOUND: contract yaml block missing",
            contract_heading,
        )
        add(
            "authority_guarantees_all_false",
            False,
            "NOT_FOUND: contract yaml block missing",
            contract_heading,
        )

    # Immutability checks
    if primary_yaml:
        imm_block, _ = find_key_block(yaml_lines, "immutability_guarantees")
        if imm_block is None:
            add("immutability_flags", False, "NOT_FOUND: immutability_guarantees block missing", contract_heading)
        else:
            imm_lines = list(imm_block)
            checks = {
                "append_only": "true",
                "mutable_after_write": "false",
                "overwrite_allowed": "false",
                "delete_allowed": "false",
            }
            missing: List[str] = []
            wrong: List[str] = []
            for key, expected in checks.items():
                value = const_value_for_key(imm_lines, key)
                if value is None:
                    missing.append(key)
                elif value != expected:
                    wrong.append(f"{key}={value} (expected {expected})")
            passed = not missing and not wrong
            if passed:
                reason = "PASS"
            else:
                parts: List[str] = []
                if missing:
                    parts.append("NOT_FOUND: " + ", ".join(missing))
                if wrong:
                    parts.append("INVALID: " + ", ".join(wrong))
                reason = "; ".join(parts)
            add("immutability_flags", passed, reason, contract_heading)
    else:
        add("immutability_flags", False, "NOT_FOUND: contract yaml block missing", contract_heading)

    # Rejection codes and priority ordering
    add(
        "rejection_codes_present",
        bool(rejection_codes),
        "PASS" if rejection_codes else "NOT_FOUND: rejection code list section missing or empty",
        reject_heading,
    )
    if priority_required:
        add(
            "priority_ordering_present",
            priority_present,
            "PASS" if priority_present else "NOT_FOUND: rejection_code_priority_order missing where priority ordering is required",
            contract_heading,
        )

    # Uniqueness signal check
    need_uniqueness = phase >= 54
    if need_uniqueness:
        add(
            "uniqueness_signal_present",
            bool(uniqueness_signals),
            "PASS" if uniqueness_signals else "NOT_FOUND: one-per-* uniqueness statement not detected",
            hard_heading or find_heading(headings, r"Validation Order"),
        )

    # Expiry semantics
    has_expiry_field = bool(re.search(r"\b[a-z_]*expires_at\b", primary_yaml))
    if has_expiry_field:
        has_time_code = bool(re.search(r"\bTIME_WINDOW_INVALID\b", text))
        has_comparison = bool(re.search(r"\b[a-z_]+_at\b\s*(?:<=|<)\s*\b[a-z_]+_at\b", text))
        passed = has_time_code and has_comparison
        reason = "PASS" if passed else "NOT_FOUND: expiry/time-window checks incomplete"
        add("expiry_semantics", passed, reason, find_heading(headings, r"Validation Order|Expiry"))

    # Linkage correctness checks
    if phase in EXPECTED_LINK_KEY:
        expected_link = EXPECTED_LINK_KEY[phase]
        req_keys = extract_required_keys(primary_yaml) if primary_yaml else []
        count = req_keys.count(expected_link)
        add(
            "expected_linkage_present_once",
            count == 1,
            "PASS" if count == 1 else f"NOT_FOUND/INVALID: expected required key `{expected_link}` count={count}",
            contract_heading,
        )

    # Future linkage drift
    if linked_ids:
        future_links: List[str] = []
        for lk in linked_ids:
            p = LINKED_KEY_TO_PHASE.get(lk)
            if p is None:
                continue
            if p > phase - 1:
                future_links.append(f"{lk}->Phase{p}")
        add(
            "future_linkage_drift",
            not future_links,
            "PASS" if not future_links else ("INVALID: future linkage detected: " + ", ".join(sorted(future_links))),
            contract_heading,
        )
    elif phase >= 55:
        add(
            "future_linkage_drift",
            False,
            "NOT_FOUND: linked_*_id fields missing for late phase",
            contract_heading,
        )

    # Preservation clause check for late phases
    requires_preservation = phase >= 54
    if requires_preservation:
        add(
            "preservation_clause_present",
            has_preservation_clause,
            "PASS" if has_preservation_clause else "NOT_FOUND: explicit preservation clause missing",
            preserve_heading,
        )

    # Runtime delta check
    add(
        "runtime_delta_none",
        not mentions_runtime_change,
        "PASS" if not mentions_runtime_change else f"INVALID: runtime delta is not none ({runtime_status})",
        phase_status_heading,
    )

    return audit


def input_digest(phases: Sequence[Tuple[int, Path]]) -> str:
    h = hashlib.sha256()
    for num, path in phases:
        text = read_text(path)
        h.update(f"{num}:{path.name}\n".encode("utf-8"))
        h.update(text.encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def generate_cross_phase_drift(
    audited: Sequence[PhaseAudit],
    yaml_by_phase: Dict[int, str],
) -> Tuple[List[str], List[str], List[str], List[str]]:
    # naming drift for state/outcome-like fields
    enum_map: Dict[str, Dict[Tuple[str, ...], List[int]]] = {}
    for phase, yaml_text in sorted(yaml_by_phase.items()):
        for key, enum_vals in extract_state_enum_map(yaml_text).items():
            enum_map.setdefault(key, {}).setdefault(enum_vals, []).append(phase)

    drift_lines: List[str] = []
    for key in sorted(enum_map):
        variants = enum_map[key]
        if len(variants) <= 1:
            continue
        parts: List[str] = []
        for enum_vals, phases in sorted(variants.items(), key=lambda x: (x[0], x[1])):
            vals = ", ".join(enum_vals)
            phase_list = ", ".join(str(p) for p in sorted(phases))
            parts.append(f"[{vals}] @ phases {phase_list}")
        drift_lines.append(f"- `{key}` enum drift: " + " | ".join(parts))

    missing_priority: List[str] = []
    missing_preserve: List[str] = []
    authority_fail: List[str] = []
    for pa in audited:
        if pa.priority_ordering_required and not pa.priority_ordering_present:
            missing_priority.append(
                f"- Phase {pa.phase}: missing rejection priority ordering ({pa.path.as_posix()})"
            )
        if pa.phase >= 54 and not pa.has_preservation_clause:
            missing_preserve.append(
                f"- Phase {pa.phase}: preservation clause missing ({pa.path.as_posix()})"
            )
        auth_find = next((f for f in pa.findings if f.check == "authority_guarantees_all_false"), None)
        if auth_find and not auth_find.passed:
            authority_fail.append(
                f"- Phase {pa.phase}: authority false guarantee failed ({auth_find.anchor}) -> {auth_find.reason}"
            )

    return drift_lines, missing_priority, missing_preserve, authority_fail


def render_report(
    docs_dir: Path,
    phases: Sequence[Tuple[int, Path]],
    audited: Sequence[PhaseAudit],
    digest: str,
    yaml_by_phase: Dict[int, str],
) -> str:
    pass_count = sum(1 for p in audited if p.status == "PASS")
    fail_count = len(audited) - pass_count

    drift_lines, missing_priority, missing_preserve, authority_fail = generate_cross_phase_drift(
        audited, yaml_by_phase
    )

    out: List[str] = []
    out.append("# Full Ladder Audit Report")
    out.append("")
    out.append("Deterministic audit output for maturity protocol promotion checklists.")
    out.append("")
    out.append(f"- Docs directory: `{docs_dir.as_posix()}`")
    if phases:
        out.append(f"- Phase range scanned: `{phases[0][0]}` to `{phases[-1][0]}`")
    else:
        out.append("- Phase range scanned: `NOT_FOUND`")
    out.append(f"- Phase files scanned: `{len(phases)}`")
    out.append(f"- Input digest (sha256): `{digest}`")
    out.append(f"- PASS phases: `{pass_count}`")
    out.append(f"- FAIL phases: `{fail_count}`")
    out.append("")

    out.append("## Phase Index")
    out.append("")
    out.append("| Phase | Level Name | Contract(s) | Status |")
    out.append("|---:|---|---|---|")
    for pa in audited:
        contracts = ", ".join(pa.contracts) if pa.contracts else "NOT_FOUND"
        out.append(f"| {pa.phase} | {pa.level_name} | {contracts} | **{pa.status}** |")
    out.append("")

    out.append("## Per-Phase Results")
    out.append("")
    for pa in audited:
        out.append(f"### Phase {pa.phase} — {pa.level_name} ({pa.status})")
        out.append("")
        out.append(f"- File: `{pa.path.as_posix()}`")
        out.append(
            "- Contracts: "
            + ("`" + "`, `".join(pa.contracts) + "`" if pa.contracts else "`NOT_FOUND`")
        )
        out.append(
            "- Upstream phase refs (declared): "
            + (", ".join(str(x) for x in pa.upstream_refs) if pa.upstream_refs else "NOT_FOUND")
        )
        out.append(
            "- Linked IDs detected: "
            + (", ".join(f"`{x}`" for x in pa.linked_ids) if pa.linked_ids else "NOT_FOUND")
        )
        out.append(
            "- Uniqueness signals: "
            + (str(len(pa.uniqueness_signals)) if pa.uniqueness_signals else "NOT_FOUND")
        )
        out.append(
            "- Rejection codes in section: "
            + (str(len(pa.rejection_codes)) if pa.rejection_codes else "NOT_FOUND")
        )
        if pa.priority_ordering_required:
            out.append(
                "- Priority ordering required: yes; present: "
                + ("yes" if pa.priority_ordering_present else "no")
            )
        else:
            out.append("- Priority ordering required: no")
        out.append("- Findings:")
        for f in sorted(pa.findings, key=lambda x: x.check):
            status = "PASS" if f.passed else "FAIL"
            out.append(f"  - [{status}] `{f.check}`: {f.reason} [{f.anchor}]")
        out.append("")

    out.append("## Cross-Phase Inconsistencies and Naming Drift")
    out.append("")
    if drift_lines:
        out.extend(drift_lines)
    else:
        out.append("- None detected by enum-name drift heuristic.")
    out.append("")

    out.append("## Missing Priority Ordering Where Expected")
    out.append("")
    if missing_priority:
        out.extend(sorted(missing_priority))
    else:
        out.append("- None.")
    out.append("")

    out.append("## Missing Preservation Clauses")
    out.append("")
    if missing_preserve:
        out.extend(sorted(missing_preserve))
    else:
        out.append("- None detected for phases requiring preservation checks.")
    out.append("")

    out.append("## Authority False Guarantee Failures")
    out.append("")
    if authority_fail:
        out.extend(sorted(authority_fail))
    else:
        out.append("- None.")
    out.append("")

    out.append("## Runtime Change Mentions")
    out.append("")
    runtime_mentions = [
        pa for pa in audited if any(f.check == "runtime_delta_none" and not f.passed for f in pa.findings)
    ]
    if runtime_mentions:
        for pa in runtime_mentions:
            f = next(f for f in pa.findings if f.check == "runtime_delta_none")
            out.append(f"- Phase {pa.phase}: {f.reason} [{f.anchor}]")
    else:
        out.append("- None (all detected runtime delta markers are `none` or absent).")
    out.append("")

    out.append("## Summary")
    out.append("")
    out.append(f"- PASS: `{pass_count}`")
    out.append(f"- FAIL: `{fail_count}`")
    out.append("")
    out.append("_Deterministic ordering rules: phases sorted numerically; findings sorted by check key;")
    out.append("cross-phase lists sorted lexicographically._")
    out.append("")
    return "\n".join(out)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    docs_dir = Path(args.docs_dir)
    out_path = Path(args.out)

    if not docs_dir.exists() or not docs_dir.is_dir():
        print(f"ERROR: docs directory not found: {docs_dir}", file=sys.stderr)
        return 2

    phases = discover_phase_files(docs_dir)
    if not phases:
        print(f"ERROR: no PHASE*_PROMOTION_CHECKLIST.md files found in {docs_dir}", file=sys.stderr)
        return 2

    audited: List[PhaseAudit] = []
    yaml_by_phase: Dict[int, str] = {}
    for phase, path in phases:
        pa = audit_phase(phase, path)
        audited.append(pa)
        blocks = extract_contract_blocks(read_text(path))
        yaml_by_phase[phase] = blocks[0] if blocks else ""

    digest = input_digest(phases)
    report = render_report(docs_dir, phases, audited, digest, yaml_by_phase)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")

    pass_count = sum(1 for p in audited if p.status == "PASS")
    fail_count = len(audited) - pass_count
    print(f"Wrote report: {out_path}")
    print(f"PASS={pass_count} FAIL={fail_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
