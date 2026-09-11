#!/usr/bin/env python3
"""Convert English-only monthly reports into open-elements-website EN/DE update JSON.

Output matches open-elements-website MonthlyUpdate shape:
  month, year, excerpt, categories[{title, items[{text, type, link?}]}],
  contributors {supportAndCare: [github urls], community?: [github urls]}

German text is drafted with Mittwald AI Hosting (OpenAI-compatible). Unchanged
English strings reuse prior German drafts when possible. Website PRs should still
be reviewed by someone who understands German before merge.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

import yaml

MONTH_ORDER = {
    "JANUARY": 1,
    "FEBRUARY": 2,
    "MARCH": 3,
    "APRIL": 4,
    "MAY": 5,
    "JUNE": 6,
    "JULY": 7,
    "AUGUST": 8,
    "SEPTEMBER": 9,
    "OCTOBER": 10,
    "NOVEMBER": 11,
    "DECEMBER": 12,
}

VALID_TYPES = {
    "FEATURE",
    "BUG_FIX",
    "IMPROVEMENT",
    "DOCUMENTATION",
    "SECURITY",
    "MAINTENANCE",
}

GITHUB_PROFILE_RE = re.compile(
    r"^https://github\.com/[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$"
)
ITEM_TYPE_LINE_RE = re.compile(r"^- type:\s*(\w*)\s*$")
ITEM_FIELD_LINE_RE = re.compile(r"^([ \t]+)(\w+):\s*(.*)$")
WORK_PACKAGE_HEADING_RE = re.compile(
    r"^Work Package\s+\d+\s+[—–-]\s+(.+)$",
    re.IGNORECASE,
)
CATEGORY_TITLE_ALIASES = {
    "Modernization of Core Feature": "Modernization of Core Features",
}

DEFAULT_TRANSLATION_API_URL = "https://llm.aihosting.mittwald.de/v1"
DEFAULT_TRANSLATION_MODEL = "gpt-oss-120b"
CATEGORY_TITLES_PATH = Path(__file__).with_name("category_titles_de.yaml")

TRANSLATION_SYSTEM_PROMPT = """You translate Open Elements Maven monthly update changelog text from English to German for the website /updates/maven.

Return ONLY a JSON array of German strings with the same length and order as the input array.
No markdown fences, no commentary, no numbering.

Do not translate or alter these; keep them exactly as written when they appear:
- Maven
- Apache
- Surefire
- CycloneDX
- JUnit
- ATR
- Release Drafter
- GitHub
- Getting Started
- plugin artifactIds / Maven coordinates
- version numbers (for example 3.10.0, 3.9.16)
- URLs

## German translation: match grammatical mood to communicative function

English uses the bare verb stem for both instructions ("Add support for X")
and reports of completed work ("Add support for X" in a changelog). German
does not — the two require different forms. Decide, for every sentence,
whether it is (a) an instruction, (b) a completed action, or (c) a
description of what something does, and then choose:

| Function | German form | Example |
|---|---|---|
| Instruction, UI action label, to-do | Infinitive | "Unterstützung für X hinzufügen" |
| Completed work (changelog, release notes, "what we did") | Perfekt / Partizip II | "Unterstützung für X hinzugefügt" |
| Description of what a thing does | Finite present | "Das Update fügt Unterstützung für X hinzu" |

Never emit a bare German infinitive unless the source is genuinely an
instruction. A German infinitive always reads as a command or an open task,
so a changelog translated with infinitives turns a report of finished work
into a backlog.

### Separable verbs
For separable verbs (hinzufügen, ausführen, bereitstellen, einrichten,
abrufen, umstellen), the prefix detaches in main clauses and moves to the
end of the sentence. It stays attached only in the infinitive, in the
Partizip II, and in subordinate clauses.

- ✗ "Das Update Unterstützung für X hinzufügt."
- ✓ "Das Update fügt Unterstützung für X hinzu."      (main clause)
- ✓ "…, das Unterstützung für X hinzufügt."           (subordinate clause)
- ✓ "Unterstützung für X hinzugefügt."                (Partizip II)

### Examples
- "Add dark mode" (changelog)  → "Dark Mode hinzugefügt."   NOT "Dark Mode hinzufügen."
- "Fix parser crash" (changelog) → "Absturz im Parser behoben."  NOT "Absturz im Parser beheben."
- "Add your API key" (docs step) → "API-Key hinzufügen."    (infinitive is correct here)
- "This release adds X"         → "Dieses Release fügt X hinzu."
"""


def load_category_titles_de(path: Path = CATEGORY_TITLES_PATH) -> dict[str, str]:
    if not path.is_file():
        raise FileNotFoundError(f"Missing category title map: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict) or not data:
        raise ValueError(f"{path}: expected a non-empty YAML mapping")
    return {str(k): str(v) for k, v in data.items()}


def split_frontmatter(text: str, path: Path) -> tuple[dict, str]:
    if not text.startswith("---\n"):
        raise ValueError(f"{path}: missing YAML frontmatter opener ---")
    rest = text[4:]
    end = rest.find("\n---\n")
    if end < 0:
        raise ValueError(f"{path}: missing YAML frontmatter closer ---")
    meta = yaml.safe_load(rest[:end]) or {}
    if not isinstance(meta, dict):
        raise ValueError(f"{path}: frontmatter must be a YAML mapping")
    body = rest[end + 5 :]
    return meta, body


def require_http_url(value: str, *, label: str, path: Path) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{path}: {label} must be an absolute http(s) URL, got {value!r}")
    return value


def validate_contributor(url: str, path: Path) -> str:
    cleaned = url.strip().rstrip("/")
    if not GITHUB_PROFILE_RE.match(cleaned):
        raise ValueError(
            f"{path}: contributor must be https://github.com/<username>, got {url!r}"
        )
    return cleaned


def normalize_contributors(raw: object, path: Path) -> dict:
    """Website contributors are grouped, not a flat list.

    Report frontmatter may use either:
      contributors: [url, ...]
    or
      contributors:
        supportAndCare: [url, ...]
        community: [url, ...]   # optional
    A flat list is treated as supportAndCare.
    """
    if isinstance(raw, list):
        urls = [validate_contributor(str(url), path) for url in raw]
        if not urls:
            raise ValueError(f"{path}: contributors must be a non-empty list")
        return {"supportAndCare": urls}

    if isinstance(raw, dict):
        extra = set(raw) - {"supportAndCare", "community"}
        if extra:
            raise ValueError(
                f"{path}: unsupported contributors keys {sorted(extra)}; "
                "expected supportAndCare and optional community"
            )
        support = raw.get("supportAndCare") or []
        community = raw.get("community") or []
        if not isinstance(support, list) or not support:
            raise ValueError(
                f"{path}: contributors.supportAndCare must be a non-empty list"
            )
        if not isinstance(community, list):
            raise ValueError(f"{path}: contributors.community must be a list")
        result: dict = {
            "supportAndCare": [validate_contributor(str(url), path) for url in support]
        }
        if community:
            result["community"] = [
                validate_contributor(str(url), path) for url in community
            ]
        return result

    raise ValueError(
        f"{path}: contributors must be a list of GitHub URLs, or a mapping "
        "with supportAndCare (and optional community)"
    )


def canonical_category_title(raw_title: str) -> str:
    """Map report headings (including Work Package prefixes) to website titles."""
    title = raw_title.strip()
    match = WORK_PACKAGE_HEADING_RE.match(title)
    if match:
        title = match.group(1).strip()
    return CATEGORY_TITLE_ALIASES.get(title, title)


def parse_body_categories(body: str, path: Path) -> list[dict]:
    """Line-oriented parser for ## categories and typed items (website-compatible).

    Empty work-package stubs (`- type:` / `text:` / `link:` with no values) are
    accepted in the markdown and omitted from website JSON. Categories with no
    real items are also omitted.
    """
    categories: list[dict] = []
    current_title: str | None = None
    current_items: list[dict] = []
    current_item: dict | None = None

    def flush_item() -> None:
        nonlocal current_item
        if current_item is None:
            return
        item_type = current_item.get("type")
        text = current_item.get("text")
        if not item_type and not text:
            # Placeholder stub: keep in the report, skip for website publish.
            current_item = None
            return
        if not item_type:
            raise ValueError(f"{path}: item under {current_title!r} is missing type:")
        if not text:
            raise ValueError(f"{path}: item under {current_title!r} is missing text:")
        current_items.append(current_item)
        current_item = None

    def flush_category() -> None:
        nonlocal current_title, current_items
        flush_item()
        if current_title is None:
            return
        if current_items:
            categories.append({"title": current_title, "items": current_items})
        current_title = None
        current_items = []

    for line_no, raw_line in enumerate(body.splitlines(), start=1):
        line = raw_line.rstrip()
        if not line.strip():
            continue

        if line.startswith("# ") and not line.startswith("##"):
            # Month H1 is informational for humans; ignore for website JSON.
            continue

        if line.startswith("###"):
            raise ValueError(
                f"{path}:{line_no}: only ## category headings are allowed (no ###)"
            )

        if line.startswith("## "):
            flush_category()
            current_title = canonical_category_title(line[3:].strip())
            if not current_title:
                raise ValueError(f"{path}:{line_no}: empty category heading")
            continue

        type_match = ITEM_TYPE_LINE_RE.match(line)
        if type_match:
            if current_title is None:
                raise ValueError(f"{path}:{line_no}: item found before any ## category")
            flush_item()
            raw_type = type_match.group(1)
            if not raw_type:
                current_item = {}
                continue
            item_type = raw_type.upper()
            if item_type not in VALID_TYPES:
                raise ValueError(
                    f"{path}:{line_no}: invalid item type {item_type!r}; "
                    f"expected one of {sorted(VALID_TYPES)}"
                )
            current_item = {"type": item_type}
            continue

        field_match = ITEM_FIELD_LINE_RE.match(line)
        if field_match and current_item is not None:
            _indent, key, value = field_match.groups()
            cleaned = value.strip()
            if key == "text":
                if cleaned:
                    current_item["text"] = cleaned
            elif key == "link":
                if cleaned:
                    current_item["link"] = require_http_url(
                        cleaned, label="link", path=path
                    )
            else:
                raise ValueError(
                    f"{path}:{line_no}: unsupported item field {key!r} "
                    "(website items only support text and optional link)"
                )
            continue

        raise ValueError(
            f"{path}:{line_no}: unexpected content {line!r}. "
            "Expected ## Category, '- type: TYPE', or indented text:/link: fields."
        )

    flush_category()
    if not categories:
        raise ValueError(f"{path}: no publishable categories/items found")
    return categories


def parse_report(path: Path) -> dict:
    """Parse an English-only structured monthly report into a website EN update object."""
    text = path.read_text(encoding="utf-8")
    meta, body = split_frontmatter(text, path)

    raw_month = meta.get("month")
    year = meta.get("year")
    excerpt = meta.get("excerpt")
    contributors = meta.get("contributors") or []

    if not isinstance(raw_month, str) or not raw_month.strip():
        raise ValueError(f"{path}: month must be a non-empty string")
    month = raw_month.strip().upper()
    if month not in MONTH_ORDER:
        raise ValueError(f"{path}: invalid month {month!r}")
    if not isinstance(year, int):
        raise ValueError(f"{path}: year must be an integer")
    if not isinstance(excerpt, str) or not excerpt.strip():
        raise ValueError(f"{path}: excerpt must be a non-empty English string")

    validated_contributors = normalize_contributors(contributors, path)
    categories = parse_body_categories(body, path)

    return {
        "month": month,
        "year": year,
        "excerpt": excerpt.strip(),
        "categories": categories,
        "contributors": validated_contributors,
    }


def update_key(update: dict) -> tuple[str, int]:
    return (str(update["month"]).upper(), int(update["year"]))


def build_en_to_de_cache(en_updates: list[dict], de_updates: list[dict]) -> dict[str, str]:
    """Map English strings to prior German drafts for reuse."""
    de_by_key = {update_key(u): u for u in de_updates}
    cache: dict[str, str] = {}

    for en_update in en_updates:
        de_update = de_by_key.get(update_key(en_update))
        if not de_update:
            continue

        cache[en_update["excerpt"]] = de_update["excerpt"]

        for en_cat, de_cat in zip(
            en_update.get("categories") or [],
            de_update.get("categories") or [],
        ):
            cache[en_cat["title"]] = de_cat["title"]
            for en_item, de_item in zip(
                en_cat.get("items") or [],
                de_cat.get("items") or [],
            ):
                cache[en_item["text"]] = de_item["text"]

    return cache


def collect_translation_jobs(
    en_update: dict, category_titles_de: dict[str, str]
) -> list[tuple[str, str]]:
    """Return ordered (kind, english) jobs: excerpt, unknown category titles, item texts."""
    jobs: list[tuple[str, str]] = [("excerpt", en_update["excerpt"])]
    for category in en_update["categories"]:
        title = category["title"]
        if title not in category_titles_de:
            jobs.append(("category", title))
        for item in category["items"]:
            jobs.append(("item", item["text"]))
    return jobs


def resolve_translations(
    jobs: list[tuple[str, str]],
    *,
    cache: dict[str, str],
    model: str,
) -> list[str]:
    results: list[str] = [""] * len(jobs)
    missing_indexes: list[int] = []
    missing_strings: list[str] = []

    for idx, (_kind, english) in enumerate(jobs):
        reused = cache.get(english)
        if reused:
            results[idx] = reused
        else:
            missing_indexes.append(idx)
            missing_strings.append(english)

    if missing_strings:
        print(f"Translating {len(missing_strings)}/{len(jobs)} strings with {model}...")
        translated = translate_strings_with_mittwald(missing_strings, model=model)
        for index, german in zip(missing_indexes, translated):
            results[index] = german
            cache[jobs[index][1]] = german
    else:
        print(f"Reusing cached German for all {len(jobs)} strings (no API call).")

    if any(not value for value in results):
        raise RuntimeError("Internal error: unresolved translation slots")
    return results


def _extract_message_content(body: dict) -> str:
    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(
            f"Unexpected Mittwald response shape: {json.dumps(body)[:500]}"
        ) from exc
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("Mittwald returned empty translation content")
    return content.strip()


def translate_strings_with_mittwald(strings: list[str], *, model: str) -> list[str]:
    api_key = os.environ.get("TRANSLATION_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "TRANSLATION_API_KEY is required to generate German drafts with Mittwald"
        )

    base_url = (
        os.environ.get("TRANSLATION_API_URL") or DEFAULT_TRANSLATION_API_URL
    ).rstrip("/")
    payload = {
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": TRANSLATION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Translate each string to German. Input JSON array:\n"
                    + json.dumps(strings, ensure_ascii=False)
                ),
            },
        ],
    }

    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Mittwald API error {exc.code}: {detail}") from exc

    raw = _extract_message_content(body)
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

    try:
        translated = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Mittwald did not return a JSON array: {raw[:500]}") from exc

    if not isinstance(translated, list) or len(translated) != len(strings):
        got = len(translated) if isinstance(translated, list) else type(translated).__name__
        raise RuntimeError(
            f"Mittwald translation length mismatch: expected {len(strings)}, got {got}"
        )
    if not all(isinstance(item, str) and item.strip() for item in translated):
        raise RuntimeError("Mittwald returned non-string or empty translations")

    return [item.strip() for item in translated]


def build_german_update(
    en_update: dict,
    jobs: list[tuple[str, str]],
    translated: list[str],
    category_titles_de: dict[str, str],
) -> dict:
    idx = 0
    excerpt_de = translated[idx]
    idx += 1

    de_categories: list[dict] = []
    for category in en_update["categories"]:
        en_title = category["title"]
        if en_title in category_titles_de:
            de_title = category_titles_de[en_title]
        else:
            kind, _english = jobs[idx]
            if kind != "category":
                raise RuntimeError("Category translation slot mismatch")
            de_title = translated[idx]
            idx += 1

        de_items: list[dict] = []
        for item in category["items"]:
            kind, _english = jobs[idx]
            if kind != "item":
                raise RuntimeError("Item translation slot mismatch")
            de_item = {"text": translated[idx], "type": item["type"]}
            idx += 1
            if "link" in item:
                de_item["link"] = item["link"]
            de_items.append(de_item)

        de_categories.append({"title": de_title, "items": de_items})

    if idx != len(translated):
        raise RuntimeError("Internal error applying translations")

    return {
        "month": en_update["month"],
        "year": en_update["year"],
        "excerpt": excerpt_de,
        "categories": de_categories,
        "contributors": en_update["contributors"],
    }


def sort_key(update: dict) -> tuple[int, int]:
    return (
        -int(update["year"]),
        -MONTH_ORDER[str(update["month"]).upper()],
    )


def upsert_updates(existing: list[dict], new_updates: list[dict]) -> list[dict]:
    by_key: dict[tuple[str, int], dict] = {
        update_key(u): u for u in existing
    }
    for update in new_updates:
        by_key[update_key(update)] = update
    return sorted(by_key.values(), key=sort_key)


def write_json(path: Path, data: list[dict]) -> None:
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "reports",
        nargs="+",
        type=Path,
        help="Paths to English-only structured monthly report markdown files",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate reports with the real parser only (no translation / website write)",
    )
    parser.add_argument(
        "--website-repo",
        type=Path,
        help="Path to open-elements-website checkout (required unless --check)",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("TRANSLATION_MODEL") or DEFAULT_TRANSLATION_MODEL,
        help="Mittwald model id used for German drafts",
    )
    args = parser.parse_args()

    if args.check:
        failed = False
        seen_keys: set[tuple[str, int]] = set()
        for report in args.reports:
            try:
                en_update = parse_report(report)
                key = update_key(en_update)
                if key in seen_keys:
                    raise ValueError(
                        f"Duplicate report for {key[0]} {key[1]} "
                        f"(second path: {report})"
                    )
                seen_keys.add(key)
                print(f"OK {report} -> {en_update['month']} {en_update['year']}")
            except Exception as exc:  # noqa: BLE001 - surface all validation failures
                failed = True
                print(f"FAIL {report}: {exc}", file=sys.stderr)
        return 1 if failed else 0

    if args.website_repo is None:
        parser.error("--website-repo is required unless --check is set")

    en_path = args.website_repo / "src/data/en/updates-maven.json"
    de_path = args.website_repo / "src/data/de/updates-maven.json"
    if not en_path.is_file() or not de_path.is_file():
        print(f"Website update JSON not found under {args.website_repo}", file=sys.stderr)
        return 1

    category_titles_de = load_category_titles_de()
    en_existing = json.loads(en_path.read_text(encoding="utf-8"))
    de_existing = json.loads(de_path.read_text(encoding="utf-8"))
    cache = build_en_to_de_cache(en_existing, de_existing)

    en_new: list[dict] = []
    de_new: list[dict] = []
    labels: list[str] = []
    seen_keys = set()

    for report in args.reports:
        en_update = parse_report(report)
        key = update_key(en_update)
        if key in seen_keys:
            raise ValueError(
                f"Duplicate report for {key[0]} {key[1]} in this run "
                f"(second path: {report})"
            )
        seen_keys.add(key)

        jobs = collect_translation_jobs(en_update, category_titles_de)
        print(f"Preparing {en_update['month']} {en_update['year']} ({len(jobs)} strings)...")
        translated = resolve_translations(jobs, cache=cache, model=args.model)
        de_update = build_german_update(
            en_update, jobs, translated, category_titles_de
        )

        en_new.append(en_update)
        de_new.append(de_update)
        labels.append(f"{en_update['month']} {en_update['year']}")
        print(f"Parsed {report} -> {en_update['month']} {en_update['year']}")

    write_json(en_path, upsert_updates(en_existing, en_new))
    write_json(de_path, upsert_updates(de_existing, de_new))

    print("Updated:")
    print(f"  {en_path}")
    print(f"  {de_path}")
    print("MONTHS=" + ",".join(labels))
    return 0


if __name__ == "__main__":
    sys.exit(main())
