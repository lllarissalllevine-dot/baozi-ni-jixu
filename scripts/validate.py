#!/usr/bin/env python3
"""Dependency-free structural validation for the public three-Skill package."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "lllarissalllevine-dot/baozi-ni-jixu"
SKILLS = {
    "baozi-ni-jixu": {
        "display_name": "宝子你继续",
        "required_phrases": ["核心动作：把话轮还给用户", "有人味，不是加语气词"],
    },
    "wo-de-ma-ya-da-jie": {
        "display_name": "我的妈呀大姐",
        "required_phrases": ["先说中，再说狠", "毒舌不是把答案换成一串骂词"],
    },
    "plato": {
        "display_name": "柏拉图",
        "required_phrases": ["亲密要落在细节上", "柏拉图式关系"],
    },
}
PSEUDO_ROUTES = {"neutral-fallback", "clarify", "unavailable"}
STARTING_ROUTES = set(SKILLS) | {"neutral"}
INVOCATIONS = {
    "implicit",
    "explicit-language",
    "explicit-skill",
    "explicit-exit",
    "continuation",
}


def fail(message: str) -> None:
    raise ValueError(message)


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"invalid JSON: {path.relative_to(ROOT)}: {exc}")


def skill_path(skill_id: str) -> Path:
    return ROOT / "skills" / skill_id


def parse_frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(?P<frontmatter>.*?)\n---\n", text, re.S)
    if not match:
        fail(f"{path.relative_to(ROOT)} must begin with YAML frontmatter")
    fields: dict[str, str] = {}
    for line in match.group("frontmatter").splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip().strip('"').strip("'")
    return fields


def validate_required_files() -> None:
    required = [
        "README.md",
        "LICENSE",
        "THIRD_PARTY_NOTICES.md",
        "CONTRIBUTING.md",
        ".github/ISSUE_TEMPLATE/new-expression.yml",
        ".github/ISSUE_TEMPLATE/bad-reply.yml",
        ".github/workflows/validate.yml",
        "assets/three-skills.svg",
        "docs/GITHUB-REPORT.md",
        "tests/cases.json",
    ]
    for skill_id in SKILLS:
        required.extend(
            [
                f"skills/{skill_id}/SKILL.md",
                f"skills/{skill_id}/agents/openai.yaml",
                f"skills/{skill_id}/references/network-context.md",
                f"skills/{skill_id}/data/slang-starter.json",
            ]
        )
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

    if (skill_path("baozi-ni-jixu") / "references" / "styles.md").exists():
        fail("the old internal three-mode router must not remain")
    if (ROOT / "assets" / "three-modes.svg").exists():
        fail("the old three-modes asset must not remain")


def validate_local_links(skill_dir: Path, text: str) -> None:
    for target in re.findall(r"\]\(([^)]+)\)", text):
        if target.startswith(("http://", "https://", "#")):
            continue
        clean = target.split("#", 1)[0]
        if not clean:
            continue
        if ".." in Path(clean).parts:
            fail(
                f"{skill_dir.relative_to(ROOT)}/SKILL.md contains a cross-directory link: "
                f"{target}"
            )
        if not (skill_dir / clean).is_file():
            fail(
                f"{skill_dir.relative_to(ROOT)}/SKILL.md links to missing local file: "
                f"{target}"
            )


def validate_skills() -> None:
    descriptions: dict[str, str] = {}
    for skill_id, contract in SKILLS.items():
        directory = skill_path(skill_id)
        skill_file = directory / "SKILL.md"
        text = skill_file.read_text(encoding="utf-8")
        fields = parse_frontmatter(skill_file)
        if fields.get("name") != skill_id:
            fail(f"{skill_file.relative_to(ROOT)} name must be {skill_id}")
        description = fields.get("description", "")
        if len(description) < 140:
            fail(f"{skill_file.relative_to(ROOT)} description is missing or too vague")
        descriptions[skill_id] = description

        required_phrases = [
            "三个独立 Skill 互斥",
            "一条用户可见回复只能由其中一个决定表达",
            "references/network-context.md",
            "data/slang-starter.json",
            "当前可见会话",
            *contract["required_phrases"],
        ]
        missing = [phrase for phrase in required_phrases if phrase not in text]
        if missing:
            fail(
                f"{skill_file.relative_to(ROOT)} missing contract phrases: "
                + ", ".join(missing)
            )
        for forbidden in ("[TODO", "三种互斥风格", "references/styles.md"):
            if forbidden in text:
                fail(f"{skill_file.relative_to(ROOT)} contains obsolete text: {forbidden}")
        validate_local_links(directory, text)

        yaml_file = directory / "agents" / "openai.yaml"
        yaml_text = yaml_file.read_text(encoding="utf-8")
        expected_display = f'display_name: "{contract["display_name"]}"'
        if expected_display not in yaml_text:
            fail(f"{yaml_file.relative_to(ROOT)} has the wrong display_name")
        if "$" + skill_id not in yaml_text:
            fail(f"{yaml_file.relative_to(ROOT)} default_prompt must mention $" + skill_id)
        if "allow_implicit_invocation: true" not in yaml_text:
            fail(f"{yaml_file.relative_to(ROOT)} must keep implicit discovery enabled")
        short_description = re.search(
            r'^\s*short_description:\s*"([^"]+)"\s*$', yaml_text, re.M
        )
        if not short_description or not 25 <= len(short_description.group(1)) <= 64:
            fail(
                f"{yaml_file.relative_to(ROOT)} short_description must be 25-64 characters"
            )
        if "Help with " in yaml_text or "[TODO" in yaml_text:
            fail(f"{yaml_file.relative_to(ROOT)} still contains scaffold copy")

    if len(set(descriptions.values())) != len(SKILLS):
        fail("Skill descriptions must be unique and discriminating")
    if "ordinary exclamations" not in descriptions["wo-de-ma-ya-da-jie"]:
        fail("toxic routing must exclude the ordinary exclamation use of its name")
    if "philosophy questions about Plato" not in descriptions["plato"]:
        fail("plato routing must exclude philosophy questions")
    normal_description = descriptions["baozi-ni-jixu"]
    if "toxic" not in normal_description or "lover" not in normal_description:
        fail("normal routing must explicitly yield to both special styles")


def validate_slang() -> int:
    payloads = []
    references = []
    for skill_id in SKILLS:
        directory = skill_path(skill_id)
        payloads.append((directory / "data" / "slang-starter.json").read_bytes())
        references.append((directory / "references" / "network-context.md").read_bytes())
    if len(set(payloads)) != 1:
        fail("the three Skill copies of slang-starter.json have drifted")
    if len(set(references)) != 1:
        fail("the three Skill copies of network-context.md have drifted")

    data = read_json(skill_path("baozi-ni-jixu") / "data" / "slang-starter.json")
    if data.get("schema_version") != "chinese-dialogue-slang-starter-v1":
        fail("slang-starter.json has an unexpected schema_version")
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
            fail(f"frozen starter entry {entry['id']} must remain understand_only")
    return len(entries)


def validate_cases() -> int:
    data = read_json(ROOT / "tests" / "cases.json")
    if data.get("schema_version") != "baozi-three-skills-smoke-v1":
        fail("tests/cases.json has an unexpected schema_version")
    cases = data.get("cases")
    if not isinstance(cases, list) or len(cases) < 27:
        fail("tests/cases.json must retain at least the 27 public cases")
    ids = [case.get("id") for case in cases]
    if len(ids) != len(set(ids)):
        fail("test case ids must be unique")
    required_ids = {
        "ACT-01", "ACT-02", "ACT-03",
        "MIS-01", "MIS-02", "MIS-03",
        "NRM-01", "NRM-02", "NRM-03", "NRM-04", "NRM-05",
        "TOX-01", "TOX-02", "TOX-03", "TOX-04", "LOV-01", "LOV-02",
        "SWI-01", "SWI-02", "SWI-03",
        "EXIT-01", "EXIT-02",
        "NET-01", "NET-02", "FOR-01", "SAFE-01", "STATE-01",
    }
    missing_ids = required_ids - set(ids)
    if missing_ids:
        fail(f"missing public contract cases: {sorted(missing_ids)}")

    counts = Counter(case.get("category") for case in cases)
    for category in ("routing", "normal", "toxic", "lover", "switching", "exit"):
        if counts[category] == 0:
            fail(f"tests/cases.json has no {category} coverage")

    valid_expected = set(SKILLS) | PSEUDO_ROUTES
    for case in cases:
        case_id = case.get("id")
        for field in ("turns", "expect", "must_not"):
            if not isinstance(case.get(field), list) or not case[field]:
                fail(f"{case_id} requires a non-empty {field} list")
        route = case.get("route")
        if not isinstance(route, dict):
            fail(f"{case_id} requires a route object")
        installed = route.get("installed")
        if (
            not isinstance(installed, list)
            or not installed
            or len(installed) != len(set(installed))
            or not set(installed).issubset(SKILLS)
        ):
            fail(f"{case_id} has an invalid installed Skill set")
        starting = route.get("starting")
        if starting not in STARTING_ROUTES:
            fail(f"{case_id} has an invalid starting route")
        if starting in SKILLS and starting not in installed:
            fail(f"{case_id} starts from a Skill that is not installed")
        expected = route.get("expected")
        if expected not in valid_expected:
            fail(f"{case_id} has an invalid expected route")
        if expected in SKILLS and expected not in installed:
            fail(f"{case_id} expects a Skill that is not installed")
        if route.get("invocation") not in INVOCATIONS:
            fail(f"{case_id} has an invalid invocation type")

    by_id = {case["id"]: case for case in cases}
    expected_routes = {
        "SWI-01": "wo-de-ma-ya-da-jie",
        "SWI-02": "plato",
        "SWI-03": "clarify",
        "EXIT-01": "neutral-fallback",
        "EXIT-02": "neutral-fallback",
        "MIS-03": "unavailable",
    }
    for case_id, expected in expected_routes.items():
        if by_id[case_id]["route"]["expected"] != expected:
            fail(f"{case_id} must expect {expected}")
    return len(cases)


def validate_docs(release: bool) -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    required_readme_phrases = (
        "# 宝子你继续",
        "三个独立 Skill",
        "我的妈呀大姐",
        "柏拉图",
        f"npx skills add {REPOSITORY} --skill baozi-ni-jixu",
        f"npx skills add {REPOSITORY} --skill wo-de-ma-ya-da-jie",
        f"npx skills add {REPOSITORY} --skill plato",
        "skills/baozi-ni-jixu",
        "skills/wo-de-ma-ya-da-jie",
        "skills/plato",
        "docs/GITHUB-REPORT.md",
    )
    missing = [phrase for phrase in required_readme_phrases if phrase not in readme]
    if missing:
        fail("README.md missing three-Skill contract: " + ", ".join(missing))
    for link in (
        "assets/three-skills.svg",
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
    report = (ROOT / "docs" / "GITHUB-REPORT.md").read_text(encoding="utf-8")
    for phrase in ("踩坑日志", "现象", "根因", "处理"):
        if phrase not in report:
            fail(f"GitHub report missing pitfall field: {phrase}")
    issue_template = (ROOT / ".github" / "ISSUE_TEMPLATE" / "bad-reply.yml").read_text(
        encoding="utf-8"
    )
    for phrase in ("id: skill", "宝子你继续", "我的妈呀大姐", "柏拉图"):
        if phrase not in issue_template:
            fail(f"bad-reply issue template missing Skill context: {phrase}")
    asset = (ROOT / "assets" / "three-skills.svg").read_text(encoding="utf-8")
    if "互斥运行" in asset or "单轮单风格" not in asset:
        fail("three-skills.svg must describe behavioral single-style routing honestly")
    if release:
        forbidden = (
            "<owner>",
            "DRAFT",
            "[TODO",
            "AUTHOR_INTRO_PENDING",
            "简介由项目作者填写",
            "当前公开版仍是单 Skill 三模式",
        )
        leftovers = [item for item in forbidden if item in readme]
        if leftovers:
            fail(
                "release README still contains unfinished author copy: "
                + ", ".join(leftovers)
            )
        stale_report = ("简介未完成前", "尚未提交、尚未推送")
        stale_leftovers = [item for item in stale_report if item in report]
        if stale_leftovers:
            fail(
                "release report still claims the candidate is blocked: "
                + ", ".join(stale_leftovers)
            )
        if (ROOT / "skills" / "chinese-dialogue").exists():
            fail("old Skill directory still exists")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--release",
        action="store_true",
        help="also reject public-copy placeholders and draft markers",
    )
    args = parser.parse_args()
    try:
        validate_required_files()
        validate_skills()
        slang_count = validate_slang()
        case_count = validate_cases()
        validate_docs(args.release)
    except ValueError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        f"PASS: three-Skill package valid; {case_count} behavior cases; "
        f"{slang_count} synchronized understand-only expressions"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
