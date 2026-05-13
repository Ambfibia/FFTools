#!/usr/bin/env python3
"""Create and merge translator-friendly views of FFTools translation JSON files."""

from __future__ import annotations

import argparse
import json
import shutil
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def has_text(value: Any) -> bool:
    return isinstance(value, str) and value != ""


def source_key(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def create_backup(path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = path.with_name(f"{path.name}.bak-{stamp}")
    shutil.copy2(path, backup)
    return backup


def export_view(args: argparse.Namespace) -> int:
    source_json = args.translation_json
    output_json = args.output_json
    spec = load_json(source_json)
    entries = spec.get("entries")
    if not isinstance(entries, list):
        raise ValueError(f"{source_json} does not contain an entries array")

    exported: list[dict[str, str]] = []
    duplicate_rows = 0
    seen_sources: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        source = source_key(entry.get("source"))
        if source is None:
            continue
        if args.skip_empty_source and source == "":
            continue
        if args.unique_source:
            if source in seen_sources:
                duplicate_rows += 1
                continue
            seen_sources.add(source)
        exported.append(
            {
                "source": source,
                "translation": entry.get("translation") if has_text(entry.get("translation")) else "",
            }
        )

    save_json(
        output_json,
        {
            "format": "fftools.translation.editor.v1",
            "sourceFile": str(source_json),
            "entries": exported,
        },
    )
    print(f"Exported {len(exported)} translator entries to {output_json}")
    if duplicate_rows:
        print(f"Skipped {duplicate_rows} duplicate source rows")
    return 0


def import_view(args: argparse.Namespace) -> int:
    full_json = args.translation_json
    editor_json = args.editor_json
    spec = load_json(full_json)
    editor = load_json(editor_json)

    full_entries = spec.get("entries")
    editor_entries = editor.get("entries")
    if not isinstance(full_entries, list):
        raise ValueError(f"{full_json} does not contain an entries array")
    if not isinstance(editor_entries, list):
        raise ValueError(f"{editor_json} does not contain an entries array")

    if args.by_source:
        return import_view_by_source(args, spec, editor)

    full_translatable = [
        entry
        for entry in full_entries
        if isinstance(entry, dict) and source_key(entry.get("source")) is not None
    ]
    editor_translatable = [row for row in editor_entries if isinstance(row, dict)]
    if len(full_translatable) != len(editor_translatable):
        print(
            "Entry count mismatch: "
            f"full JSON has {len(full_translatable)} source rows, "
            f"editor JSON has {len(editor_translatable)} rows"
        )
        print("Use an editor JSON exported from the same full translation.json.")
        return 2

    mismatches: list[tuple[int, str, str]] = []
    for index, (entry, row) in enumerate(zip(full_translatable, editor_translatable), start=1):
        full_source = source_key(entry.get("source"))
        editor_source = source_key(row.get("source"))
        if full_source != editor_source:
            mismatches.append((index, full_source or "", editor_source or ""))
            if len(mismatches) >= 20:
                break

    if mismatches:
        print("Source order mismatch between full JSON and editor JSON:")
        for index, full_source, editor_source in mismatches:
            full_printable = full_source.replace("\r", "\\r").replace("\n", "\\n")
            editor_printable = editor_source.replace("\r", "\\r").replace("\n", "\\n")
            print(f"- row {index}: full={full_printable!r}, editor={editor_printable!r}")
        return 2

    changed = 0
    filled = 0
    ignored_rows = 0
    for entry, row in zip(full_translatable, editor_translatable):
        translation = row.get("translation")
        if not isinstance(translation, str):
            ignored_rows += 1
            continue
        if entry.get("translation") != translation:
            entry["translation"] = translation
            changed += 1
        if translation != "":
            filled += 1

    if args.backup:
        backup = create_backup(full_json)
        print(f"Backup written to {backup}")

    save_json(full_json, spec)

    print(f"Matched {len(full_translatable)} full translation entries by row order")
    print(f"Changed {changed} translations in {full_json}")
    print(f"Non-empty matched translations: {filled}")
    if ignored_rows:
        print(f"Ignored {ignored_rows} editor rows with non-string translation values")
    return 0


def import_view_by_source(args: argparse.Namespace, spec: dict[str, Any], editor: dict[str, Any]) -> int:
    full_json = args.translation_json
    editor_json = args.editor_json
    full_entries = spec["entries"]
    editor_entries = editor["entries"]
    source_counts = Counter()
    translations: dict[str, str] = {}
    conflicts: dict[str, set[str]] = {}
    ignored_rows = 0
    for row in editor_entries:
        if not isinstance(row, dict):
            ignored_rows += 1
            continue
        source = source_key(row.get("source"))
        translation = row.get("translation")
        if source is None or not isinstance(translation, str):
            ignored_rows += 1
            continue
        source_counts[source] += 1
        if source in translations and translations[source] != translation:
            conflicts.setdefault(source, {translations[source]}).add(translation)
            continue
        translations[source] = translation

    if conflicts and not args.allow_conflicts:
        print("Conflicting translations for the same source were found:")
        for index, (source, values) in enumerate(conflicts.items()):
            if index >= 20:
                print(f"... and {len(conflicts) - index} more")
                break
            printable = source.replace("\r", "\\r").replace("\n", "\\n")
            print(f"- {printable!r}: {len(values)} different translations")
        print("Fix the duplicate source rows or rerun with --allow-conflicts to keep the first value.")
        return 2

    changed = 0
    matched = 0
    filled = 0
    for entry in full_entries:
        if not isinstance(entry, dict):
            continue
        source = source_key(entry.get("source"))
        if source is None or source not in translations:
            continue
        matched += 1
        new_translation = translations[source]
        if entry.get("translation") != new_translation:
            entry["translation"] = new_translation
            changed += 1
        if new_translation != "":
            filled += 1

    if args.backup:
        backup = create_backup(full_json)
        print(f"Backup written to {backup}")

    save_json(full_json, spec)

    duplicate_sources = sum(1 for count in source_counts.values() if count > 1)
    print(f"Matched {matched} full translation entries")
    print(f"Changed {changed} translations in {full_json}")
    print(f"Non-empty matched translations: {filled}")
    if duplicate_sources:
        print(f"Editor file contains {duplicate_sources} duplicate source values")
    if ignored_rows:
        print(f"Ignored {ignored_rows} malformed editor rows")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    export_parser = subparsers.add_parser("export", help="write a source/translation-only JSON")
    export_parser.add_argument("translation_json", type=Path)
    export_parser.add_argument("output_json", type=Path)
    export_parser.add_argument("--unique-source", action="store_true")
    export_parser.add_argument("--keep-empty-source", dest="skip_empty_source", action="store_false")
    export_parser.set_defaults(skip_empty_source=True, func=export_view)

    import_parser = subparsers.add_parser("import", help="merge a source/translation-only JSON back")
    import_parser.add_argument("translation_json", type=Path)
    import_parser.add_argument("editor_json", type=Path)
    import_parser.add_argument("--no-backup", dest="backup", action="store_false")
    import_parser.add_argument("--by-source", action="store_true")
    import_parser.add_argument("--allow-conflicts", action="store_true")
    import_parser.set_defaults(backup=True, func=import_view)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
