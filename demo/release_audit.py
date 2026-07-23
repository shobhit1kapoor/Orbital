from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {
    "",
    ".css",
    ".env",
    ".example",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".jsx",
    ".lock",
    ".md",
    ".mjs",
    ".py",
    ".rego",
    ".sh",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".vtt",
    ".yaml",
    ".yml",
}
SECRET_PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "Azure storage connection": re.compile(
        r"DefaultEndpointsProtocol=https?;AccountName=[^;\s]+;AccountKey="
    ),
}
LOCAL_PATHS = {
    "Windows user path": re.compile(r"\b[A-Za-z]:\\Users\\"),
    "Linux home path": re.compile(r"/home/[A-Za-z0-9._-]+/"),
}
MARKDOWN_LINK = re.compile(r"!?\[[^\]]*]\(([^)]+)\)")


def repository_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [
        ROOT / item.decode("utf-8")
        for item in result.stdout.split(b"\0")
        if item
    ]


def text_files(paths: list[Path]) -> list[tuple[Path, str]]:
    values: list[tuple[Path, str]] = []
    for path in paths:
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            values.append((path, path.read_text(encoding="utf-8")))
        except UnicodeDecodeError:
            continue
    return values


def validate_links(path: Path, body: str) -> list[str]:
    errors: list[str] = []
    for target in MARKDOWN_LINK.findall(body):
        target = target.strip().split("#", 1)[0]
        if (
            not target
            or target.startswith(("http://", "https://", "mailto:", "#"))
            or "://" in target
        ):
            continue
        resolved = (path.parent / target).resolve()
        if not resolved.exists():
            errors.append(
                f"{path.relative_to(ROOT)}: missing local link target {target}"
            )
    return errors


def main() -> None:
    paths = repository_files()
    text = text_files(paths)
    failures: list[str] = []
    for path, body in text:
        relative = path.relative_to(ROOT)
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(body):
                failures.append(f"{relative}: possible {label}")
        if relative.parts and relative.parts[0] in {"README.md", "docs"}:
            for label, pattern in LOCAL_PATHS.items():
                if pattern.search(body):
                    failures.append(f"{relative}: contains {label}")
        if path.suffix.lower() == ".md":
            failures.extend(validate_links(path, body))

    public_keys = [
        path.relative_to(ROOT).as_posix()
        for path in paths
        if path.is_file() and path.suffix.lower() in {".pub", ".pem", ".key"}
    ]
    expected_public_key = "packages/certificate-schema/public-keys/development.pub"
    if public_keys != [expected_public_key]:
        failures.append(
            "unexpected committed key material: "
            + (", ".join(public_keys) if public_keys else "none")
        )
    if failures:
        raise SystemExit("Release audit failed:\n- " + "\n- ".join(failures))
    print(
        "Release audit PASS: no secret signatures or public local paths; "
        f"{len(paths)} repository files checked; development public key only; "
        "Markdown local links resolve."
    )


if __name__ == "__main__":
    main()
