"""Search and render the embedded testing and review playbooks."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .errors import ConfigurationError

GUIDE_ROOT = Path(__file__).resolve().parent / "guides"


def guides() -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for path in sorted(GUIDE_ROOT.glob("*.md")):
        content = path.read_text(encoding="utf-8")
        title_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
        title = title_match.group(1) if title_match else path.stem.replace("-", " ").title()
        summary_match = re.search(r"^>\s+(.+)$", content, re.MULTILINE)
        result.append(
            {
                "topic": path.stem,
                "title": title,
                "summary": summary_match.group(1) if summary_match else "",
            }
        )
    return result


def read_guide(topic: str) -> str:
    normalized = topic.strip().lower().replace(" ", "-")
    direct = GUIDE_ROOT / f"{normalized}.md"
    if direct.exists():
        return direct.read_text(encoding="utf-8")
    matches = [
        item
        for item in guides()
        if normalized in item["topic"] or normalized in item["title"].lower().replace(" ", "-")
    ]
    if len(matches) == 1:
        return (GUIDE_ROOT / f"{matches[0]['topic']}.md").read_text(encoding="utf-8")
    if not matches:
        raise ConfigurationError(f"unknown guidance topic {topic!r}")
    raise ConfigurationError(
        "ambiguous guidance topic; choose one of: " + ", ".join(item["topic"] for item in matches)
    )


def search_guides(query: str) -> list[dict[str, Any]]:
    terms = [term.lower() for term in re.findall(r"[A-Za-z0-9_-]+", query)]
    scored: list[dict[str, Any]] = []
    for item in guides():
        path = GUIDE_ROOT / f"{item['topic']}.md"
        content = path.read_text(encoding="utf-8")
        lower = content.lower()
        score = sum(lower.count(term) for term in terms)
        if score:
            snippets = [
                line.strip()
                for line in content.splitlines()
                if any(term in line.lower() for term in terms)
            ][:3]
            scored.append({**item, "score": score, "snippets": snippets})
    return sorted(scored, key=lambda item: (-item["score"], item["topic"]))
