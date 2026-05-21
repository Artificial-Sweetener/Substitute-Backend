#!/usr/bin/env python3
#    Substitute BackEnd - backend liaison services for SugarSubstitute and ComfyUI
#    Copyright (C) 2026  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""Add or update AGPLv3 license headers in tracked source files."""

from __future__ import annotations

import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT_LINE = "Substitute BackEnd - backend liaison services for SugarSubstitute and ComfyUI"
COPYRIGHT_HOLDER = "Artificial Sweetener and contributors"
START_YEAR = 2026
SUPPORTED_SUFFIXES = frozenset((".py", ".pyi", ".js", ".mjs", ".cjs"))
HEADER_END_TEXT = "along with this program.  If not, see <https://www.gnu.org/licenses/>."
COPYRIGHT_PATTERN = re.compile(
    r"(?P<prefix>(?:#|//)\s*)Copyright \(C\)\s+"
    r"(?P<years>2026(?:\s*-\s*\d{4})?)\s+"
    r"Artificial Sweetener(?:\s+and\s+contributors)?"
)


def _copyright_years(now: datetime | None = None) -> str:
    """Return the canonical copyright year text for the run date."""

    current_year = (now or datetime.now(UTC)).year
    if current_year <= START_YEAR:
        return str(START_YEAR)
    return f"{START_YEAR} - {current_year}"


def _comment_prefix(path: Path) -> str:
    """Return the line comment prefix for a supported source file."""

    if path.suffix in {".js", ".mjs", ".cjs"}:
        return "//"
    return "#"


def _license_body(prefix: str) -> str:
    """Return the AGPLv3 notice body using the requested comment prefix."""

    return "\n".join(
        (
            f"{prefix}",
            f"{prefix}    This program is free software: you can redistribute it and/or modify",
            (
                f"{prefix}    it under the terms of the GNU Affero General Public License "
                "as published by"
            ),
            f"{prefix}    the Free Software Foundation, either version 3 of the License, or",
            f"{prefix}    (at your option) any later version.",
            f"{prefix}",
            f"{prefix}    This program is distributed in the hope that it will be useful,",
            f"{prefix}    but WITHOUT ANY WARRANTY; without even the implied warranty of",
            f"{prefix}    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the",
            f"{prefix}    GNU Affero General Public License for more details.",
            f"{prefix}",
            f"{prefix}    You should have received a copy of the GNU Affero General Public License",
            f"{prefix}    along with this program.  If not, see <https://www.gnu.org/licenses/>.",
        )
    )


def _header(path: Path, now: datetime | None = None) -> str:
    """Return the canonical license header for a source file."""

    prefix = _comment_prefix(path)
    return "\n".join(
        (
            f"{prefix}    {PROJECT_LINE}",
            f"{prefix}    Copyright (C) {_copyright_years(now)}  {COPYRIGHT_HOLDER}",
            _license_body(prefix),
        )
    )


def _tracked_source_files() -> list[Path]:
    """Return git-tracked source files that should carry the project notice."""

    try:
        result = subprocess.run(
            ["git", "ls-files"],
            capture_output=True,
            check=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        print(f"Error running git ls-files: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    return sorted(
        Path(path) for path in result.stdout.splitlines() if Path(path).suffix in SUPPORTED_SUFFIXES
    )


def _header_bounds(lines: list[str], prefix: str) -> tuple[int, int] | None:
    """Find an existing project license header block in source lines."""

    start = None
    project_marker = f"{prefix}    {PROJECT_LINE}"
    for index, line in enumerate(lines):
        if line.rstrip("\n") == project_marker:
            start = index
            break

    if start is None:
        return None

    for index in range(start, len(lines)):
        if lines[index].rstrip("\n") == f"{prefix}    {HEADER_END_TEXT}":
            return start, index

    return None


def _insertion_index(lines: list[str], prefix: str) -> int:
    """Return the safe insertion point after shebangs or encoding directives."""

    index = 0
    if lines and lines[0].startswith("#!"):
        index += 1

    if prefix == "#" and len(lines) > index:
        encoding_line = lines[index]
        if encoding_line.startswith("#") and "coding" in encoding_line:
            index += 1

    return index


def _normalize_existing_copyright(text: str) -> str:
    """Update known older project copyright variants before full header handling."""

    years = _copyright_years()

    def replace(match: re.Match[str]) -> str:
        return f"{match.group('prefix')}Copyright (C) {years}  {COPYRIGHT_HOLDER}"

    return COPYRIGHT_PATTERN.sub(replace, text)


def update_header(path: Path) -> bool:
    """Add or normalize the project license header for one source file."""

    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        print(f"Skipping {path}: unable to read as UTF-8")
        return False

    normalized_content = _normalize_existing_copyright(content)
    lines = normalized_content.splitlines(keepends=True)
    prefix = _comment_prefix(path)
    header = _header(path)
    header_lines = [line + "\n" for line in header.splitlines()]
    bounds = _header_bounds(lines, prefix)

    if bounds is not None:
        start, end = bounds
        updated_lines = lines[:start] + header_lines + lines[end + 1 :]
        updated_content = "".join(updated_lines)
        if updated_content != content:
            path.write_text(updated_content, encoding="utf-8")
            print(f"Normalized header in {path}")
            return True
        return False

    if "GNU Affero General Public License" in normalized_content[:1500]:
        print(f"Skipping {path}: unknown AGPL header already present")
        return False

    insert_at = _insertion_index(lines, prefix)
    new_lines = lines[:insert_at] + header_lines + lines[insert_at:]
    path.write_text("".join(new_lines), encoding="utf-8")
    print(f"Added header to {path}")
    return True


def main() -> None:
    """Update license headers in all tracked source files."""

    files = _tracked_source_files()
    print(f"Found {len(files)} tracked source files.")
    changed = 0
    for path in files:
        if path.exists() and update_header(path):
            changed += 1
    print(f"Updated {changed} file(s).")


if __name__ == "__main__":
    main()
