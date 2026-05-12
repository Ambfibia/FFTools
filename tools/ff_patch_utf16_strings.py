#!/usr/bin/env python3
"""Apply fixed-width UTF-16 string replacements to extracted .NET DLLs.

This is intentionally conservative. It only replaces strings with the same
number of UTF-16 code units, so the CLR metadata heaps keep the same layout.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


def patch_file(path: Path, replacements: list[dict[str, str]], backup: bool) -> int:
    data = path.read_bytes()
    patched = data
    total = 0

    for replacement in replacements:
        old = replacement["old"]
        new = replacement["new"]
        if len(old) != len(new):
            raise ValueError(
                f"{path}: replacement must keep UTF-16 width: {old!r} ({len(old)}) "
                f"-> {new!r} ({len(new)})"
            )

        old_bytes = old.encode("utf-16le")
        new_bytes = new.encode("utf-16le")
        count = patched.count(old_bytes)
        expected = replacement.get("count")
        if expected is not None and count != int(expected):
            raise ValueError(f"{path}: {old!r} matched {count} times, expected {expected}")
        if count == 0:
            raise ValueError(f"{path}: {old!r} was not found")

        patched = patched.replace(old_bytes, new_bytes)
        total += count
        print(f"{path.name}: {old!r} -> {new!r} ({count})")

    if patched != data:
        if backup:
            backup_path = path.with_suffix(path.suffix + ".bak")
            if not backup_path.exists():
                shutil.copy2(path, backup_path)
        path.write_bytes(patched)
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="Directory containing extracted UnityWeb files")
    parser.add_argument("patch_json", type=Path)
    parser.add_argument("--backup", action="store_true")
    args = parser.parse_args()

    spec = json.loads(args.patch_json.read_text(encoding="utf-8"))
    total = 0
    for file_spec in spec["files"]:
        path = args.root / file_spec["path"]
        total += patch_file(path, file_spec["replacements"], args.backup)
    print(f"Applied {total} UTF-16 replacements")


if __name__ == "__main__":
    main()
