"""Conservative repository scan for common committed credential shapes."""
from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {".git", ".venv", ".pytest_cache", "__pycache__", "reports"}
TEXT_SUFFIXES = {
    ".py", ".toml", ".yaml", ".yml", ".md", ".json", ".csv", ".txt",
    ".html", ".css", ".js", ".example", "",
}
PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bgsk_[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)


def main() -> int:
    findings: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in EXCLUDED for part in path.parts):
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if any(pattern.search(content) for pattern in PATTERNS):
            findings.append(str(path.relative_to(ROOT)))
    if findings:
        print("Potential credential material found in: " + ", ".join(sorted(findings)))
        return 1
    print("Secret-shaped credential scan passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
