#!/usr/bin/env python3
"""Dependency-free structural validation for the public v0.1 package."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "chinese-dialogue"


def fail(message: str) -> None:
    raise ValueError(message)


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"invalid JSON: {path.relative_to(ROOT)}: {exc}")


def validate_required_files() -> None:
    required = [
        "README.md",
        "LICENSE",
        "THIRD_PARTY_NOTICES.md",
        "CONTRIBUTING.md",
        ".github/ISSUE_TEMPLATE/new-expression.yml",
        ".github/ISSUE_TEMPLATE/bad-reply.yml",
        ".github/workflows/validate.yml",
        "assets/three-modes.svg",
        "skills/chinese-dialogue/SKILL.md",
        "skills/chinese-dialogue/agents/openai.yaml",
        "skills/chinese-dialogue/references/styles.md",
        "skills/chinese-dialogue/references/network-context.md",
        "skills/chinese-dialogue/data/slang-starter.json",
        "tests/cases.json",
    ]
    missing = [item for item in required if not (ROOT / item).is_file()]
    if missing:
        fail("missing required files: " + ", ".join(missing))

    oversized = [
        str(path.relative_to(ROOT))
        for path in ROOT.rglob("*")
        if path.is_file() and path.stat().st_size > 500_000
    ]
    if oversized:
        fail("public package contains files over 500 KB: " + ", ".join(oversized))

    bundled_chime = [
        str(path.relative_to(ROOT))
        for path in ROOT.rglob("*")
        if path.is_file() and re.search(r"chime_(full|mcq)\.json$", path.name, re.I)
    ]
    if bundled_chime:
        fail("CHIME data must not be bundled: " + ", ".join(bundled_chime))


def validate_skill() -> None:
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    match = re.match(r"^---\n(?P<frontmatter>.*?)\n---\n", text, re.S)
    if not match:
        fail("SKILL.md must begin with YAML frontmatter")
    frontmatter = match.group("frontmatter")
    name = re.search(r"^name:\s*(.+)$", frontmatter, re.M)
    description = re.search(r"^description:\s*(.+)$", frontmatter, re.M)
    if not name or name.group(1).strip() != "chinese-dialogue":
        fail("SKILL.md name must be chinese-dialogue")
    if not description or len(description.group(1).strip()) < 80:
        fail("SKILL.md description is missing or too vague")

    required_phrases = [
        "三种互斥风格",
        "references/styles.md",
        "references/network-context.md",
        "data/slang-starter.json",
        "不能说“以后都记住了”",
    ]
    missing = [phrase for phrase in required_phrases if phrase not in text]
    if missing:
        fail("SKILL.md missing contract phrases: " + ", ".join(missing))

    yaml_text = (SKILL / "agents" / "openai.yaml").read_text(encoding="utf-8")
    for phrase in ('display_name: "', 'short_description: "', 'default_prompt: "'):
        if phrase not in yaml_text:
            fail(f"openai.yaml missing quoted field: {phrase[:-2]}")
    if "$chinese-dialogue" not in yaml_text:
        fail("openai.yaml default_prompt must mention $chinese-dialogue")


def validate_slang() -> int:
    data = read_json(SKILL / "data" / "slang-starter.json")
    entries = data.get("entries")
    if not isinstance(entries, list) or len(entries) < 7:
        fail("slang-starter.json must retain at least the 7 frozen starter entries")
    required_terms = {
        "雷霆",
        "阴的没边了",
        "这波贪了",
        "贴脸开大",
        "绷不住了",
        "破绷了",
        "假如说我绷住了呢？",
    }
    terms = {entry.get("term") for entry in entries}
    if not required_terms.issubset(terms):
        fail("starter data is missing one or more frozen expressions")
    ids = [entry.get("id") for entry in entries]
    if len(ids) != len(set(ids)):
        fail("starter entry ids must be unique")
    required_fields = {
        "id",
        "term",
        "aliases",
        "type",
        "meaning",
        "signals",
        "good_when",
        "avoid_when",
        "active_use",
        "confidence",
        "examples",
    }
    for entry in entries:
        missing = required_fields - set(entry)
        if missing:
            fail(f"starter entry {entry.get('id')} missing fields: {sorted(missing)}")
        if entry["active_use"] not in {
            "understand_only",
            "echo_allowed",
            "proactive_allowed",
        }:
            fail(f"starter entry {entry['id']} has an invalid active_use value")
        if entry["term"] in required_terms and entry["active_use"] != "understand_only":
            fail(f"frozen starter entry {entry['id']} must remain understand_only in v0.1")
    return len(entries)


def validate_cases() -> int:
    data = read_json(ROOT / "tests" / "cases.json")
    cases = data.get("cases")
    if not isinstance(cases, list) or len(cases) < 16:
        fail("tests/cases.json must retain at least the 16 v0.1 cases")
    ids = [case.get("id") for case in cases]
    if len(ids) != len(set(ids)):
        fail("test case ids must be unique")
    expected_counts = {"natural": 4, "style": 6, "network": 4, "formal": 2}
    counts = Counter(case.get("category") for case in cases)
    missing_coverage = {
        category: minimum
        for category, minimum in expected_counts.items()
        if counts[category] < minimum
    }
    if missing_coverage:
        fail(f"insufficient category coverage: {missing_coverage}")
    for case in cases:
        if case.get("style") not in {"normal", "lover", "toxic"}:
            fail(f"invalid style in {case.get('id')}")
        for field in ("turns", "expect", "must_not"):
            if not isinstance(case.get(field), list) or not case[field]:
                fail(f"{case.get('id')} requires a non-empty {field} list")
    return len(cases)


def validate_docs(release: bool) -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for link in (
        "assets/three-modes.svg",
        "THIRD_PARTY_NOTICES.md",
        "CONTRIBUTING.md",
        "LICENSE",
    ):
        if link not in readme:
            fail(f"README.md does not link to {link}")
    if "MIT License" not in (ROOT / "LICENSE").read_text(encoding="utf-8"):
        fail("LICENSE is not MIT")
    if "does not bundle or redistribute" not in (
        ROOT / "THIRD_PARTY_NOTICES.md"
    ).read_text(encoding="utf-8"):
        fail("CHIME non-bundling notice is missing")
    if release and ("<owner>" in readme or "DRAFT" in readme):
        fail("release README still contains an owner placeholder or draft marker")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--release",
        action="store_true",
        help="also reject repository placeholders and draft markers",
    )
    args = parser.parse_args()
    try:
        validate_required_files()
        validate_skill()
        slang_count = validate_slang()
        case_count = validate_cases()
        validate_docs(args.release)
    except ValueError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        f"PASS: public package valid; {case_count} behavior cases; "
        f"{slang_count} understand-only starter expressions"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
