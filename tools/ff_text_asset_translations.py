#!/usr/bin/env python3
"""Export and apply Unity asset translations in the shared translation JSON."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
UNITYPACK = ROOT / "UnityPackFF"
if str(UNITYPACK) not in sys.path:
    sys.path.insert(0, str(UNITYPACK))

from unitypack.asset import Asset  # noqa: E402


TEXT_ASSET_TYPE_ID = 49
TEXT_ASSET_KIND = "unity.textAsset"
OBJECT_STRING_KIND = "unity.objectString"

LOCALIZABLE_PATH_HINTS = (
    "MissionStringData",
    "NpcStringData",
    "NpcBarkerData",
    "ItemStringData",
    "NanoStringData",
    "NanoTuneStringData",
    "ShinyStringData",
    "SkillStringData",
    "ChatStringData",
    "MessageData",
    "HelpPageString",
    "FirstUseString",
    "RulesString",
    "GuideStringData",
    "WarpNameData",
    "WorldNameData",
    "ClassString",
    "SkillBookString",
    "SceneData",
    "BlackFilterData",
    "WhiteFilterData",
)

SKIP_SOURCE_VALUES = {"", "0", "-1", "null", "none"}


def load_spec(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "format": "fftools.translation.v1",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "entries": [],
        }
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save_spec(path: Path, spec: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def sha1_text(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()


def text_asset_entry_id(file_name: str, path_id: int, source: str) -> str:
    digest = sha1_text(f"{file_name}|{path_id}|{source}")[:16]
    return f"{TEXT_ASSET_KIND}:{file_name}:{path_id}:{digest}"


def object_string_entry_id(file_name: str, path_id: int, field_path: str, source: str) -> str:
    digest = sha1_text(f"{file_name}|{path_id}|{field_path}|{source}")[:16]
    return f"{OBJECT_STRING_KIND}:{file_name}:{path_id}:{digest}"


def has_text(value: Any) -> bool:
    return isinstance(value, str) and value != ""


def normalize_asset_name(name: str) -> str:
    return name.replace("\\", "/")


class Merge:
    def __init__(self) -> None:
        self.by_id: dict[str, str] = {}
        self.by_file_path_source: dict[tuple[str, int, str], str] = {}
        self.by_file_field_source: dict[tuple[str, int, str, str], str] = {}
        self.by_file_name_source: dict[tuple[str, str, str], str] = {}
        self.by_source: dict[str, str | None] = {}

    def add_spec(self, spec: dict[str, Any]) -> None:
        for entry in spec.get("entries", []):
            translation = entry.get("translation")
            if not has_text(translation):
                continue
            source = entry.get("source")
            if not isinstance(source, str):
                continue

            entry_id_value = entry.get("id")
            if isinstance(entry_id_value, str):
                self.by_id[entry_id_value] = translation

            file_name = entry.get("file")
            path_id = entry.get("pathId")
            field_path = entry.get("fieldPath")
            name = entry.get("name") or entry.get("objectName")
            if isinstance(file_name, str) and isinstance(path_id, int):
                self.by_file_path_source[(file_name, path_id, source)] = translation
                if isinstance(field_path, str):
                    self.by_file_field_source[(file_name, path_id, field_path, source)] = translation
            if isinstance(file_name, str) and isinstance(name, str):
                self.by_file_name_source[(file_name, name, source)] = translation

            if source not in self.by_source:
                self.by_source[source] = translation
            elif self.by_source[source] != translation:
                self.by_source[source] = None

    def find(self, entry: dict[str, Any]) -> str:
        entry_id_value = entry["id"]
        file_name = entry["file"]
        path_id = entry["pathId"]
        source = entry["source"]

        if entry_id_value in self.by_id:
            return self.by_id[entry_id_value]

        field_path = entry.get("fieldPath")
        if isinstance(field_path, str):
            key_field = (file_name, path_id, field_path, source)
            if key_field in self.by_file_field_source:
                return self.by_file_field_source[key_field]

        key_path = (file_name, path_id, source)
        if key_path in self.by_file_path_source:
            return self.by_file_path_source[key_path]

        name = entry.get("name") or entry.get("objectName")
        if isinstance(name, str):
            key_name = (file_name, name, source)
            if key_name in self.by_file_name_source:
                return self.by_file_name_source[key_name]

        by_source = self.by_source.get(source)
        return by_source or ""


def load_merge(paths: list[Path]) -> Merge:
    merge = Merge()
    for path in paths:
        if path.exists():
            merge.add_spec(load_spec(path))
    return merge


def read_asset(asset_path: Path) -> Asset:
    handle = asset_path.open("rb")
    asset = Asset.from_file(handle)
    asset.load()
    asset._fftools_handle = handle  # type: ignore[attr-defined]
    return asset


def close_asset(asset: Asset) -> None:
    handle = getattr(asset, "_fftools_handle", None)
    if handle is not None:
        handle.close()


def text_asset_entries(root: Path, asset_names: list[str], merge: Merge, container: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for asset_name in asset_names:
        asset_path = root / asset_name
        if not asset_path.exists():
            continue

        asset = read_asset(asset_path)
        try:
            for path_id, obj in sorted(asset.objects.items()):
                if obj.type_id != TEXT_ASSET_TYPE_ID:
                    continue
                data = obj.read()
                source = data.script
                if not isinstance(source, str) or source.strip() == "":
                    continue

                entry = {
                    "id": text_asset_entry_id(asset_name, int(path_id), source),
                    "kind": TEXT_ASSET_KIND,
                    "container": container,
                    "file": asset_name,
                    "pathId": int(path_id),
                    "name": data.name,
                    "source": source,
                    "sourceSha1": sha1_text(source),
                    "translation": "",
                }
                entry["translation"] = merge.find(entry)
                entries.append(entry)
        finally:
            close_asset(asset)
    return entries


def path_to_string(parts: list[str | int]) -> str:
    result = ""
    for part in parts:
        if isinstance(part, int):
            result += f"[{part}]"
        else:
            result = f"{result}.{part}" if result else part
    return result


def walk_strings(value: Any, parts: list[str | int] | None = None):
    if parts is None:
        parts = []

    if isinstance(value, str):
        yield parts, value
    elif hasattr(value, "_obj"):
        yield from walk_strings(value._obj, parts)
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from walk_strings(item, [*parts, str(key)])
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            yield from walk_strings(item, [*parts, index])


def get_by_parts(value: Any, parts: list[str | int]) -> Any:
    current = value._obj if hasattr(value, "_obj") else value
    for part in parts:
        if hasattr(current, "_obj"):
            current = current._obj
        current = current[part]
    return current


def set_by_parts(value: Any, parts: list[str | int], replacement: str) -> None:
    current = value._obj if hasattr(value, "_obj") else value
    for part in parts[:-1]:
        if hasattr(current, "_obj"):
            current = current._obj
        current = current[part]
    if hasattr(current, "_obj"):
        current = current._obj
    current[parts[-1]] = replacement


def is_localizable_object_string(field_path: str, source: str, include_all: bool) -> bool:
    stripped = source.strip()
    if stripped.lower() in SKIP_SOURCE_VALUES:
        return False
    if include_all:
        return True
    return any(hint in field_path for hint in LOCALIZABLE_PATH_HINTS)


def object_string_entries(
    root: Path,
    asset_names: list[str],
    merge: Merge,
    container: str,
    include_all: bool,
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for asset_name in asset_names:
        asset_path = root / asset_name
        if not asset_path.exists():
            continue

        asset = read_asset(asset_path)
        try:
            for path_id, obj in sorted(asset.objects.items()):
                if obj.class_id != 114 or obj.type_id >= 0:
                    continue
                data = obj.read()
                object_name = data.get("m_Name", "") if isinstance(data, dict) else ""
                for parts, source in walk_strings(data):
                    field_path = path_to_string(parts)
                    if field_path == "m_Name":
                        continue
                    if not is_localizable_object_string(field_path, source, include_all):
                        continue

                    entry = {
                        "id": object_string_entry_id(asset_name, int(path_id), field_path, source),
                        "kind": OBJECT_STRING_KIND,
                        "container": container,
                        "file": asset_name,
                        "pathId": int(path_id),
                        "objectName": object_name,
                        "objectTypeId": int(obj.type_id),
                        "fieldPath": field_path,
                        "path": parts,
                        "source": source,
                        "sourceSha1": sha1_text(source),
                        "translation": "",
                    }
                    entry["translation"] = merge.find(entry)
                    entries.append(entry)
        finally:
            close_asset(asset)
    return entries


def export_assets(args: argparse.Namespace) -> int:
    spec = load_spec(args.translation_json)
    merge = load_merge([args.translation_json, *args.merge])
    asset_names = [normalize_asset_name(name) for name in args.asset]
    kinds = {TEXT_ASSET_KIND}
    if args.object_strings:
        kinds.add(OBJECT_STRING_KIND)

    kept_entries = [
        entry
        for entry in spec.get("entries", [])
        if not (entry.get("kind") in kinds and entry.get("file") in asset_names)
    ]

    new_entries = text_asset_entries(args.root, asset_names, merge, args.container)
    if args.object_strings:
        new_entries.extend(
            object_string_entries(args.root, asset_names, merge, args.container, args.all_object_strings)
        )

    spec["entries"] = kept_entries + new_entries
    spec.setdefault("format", "fftools.translation.v1")
    spec["generatedAt"] = datetime.now(timezone.utc).isoformat()

    save_spec(args.translation_json, spec)
    translated = sum(1 for entry in new_entries if has_text(entry.get("translation")))
    print(f"Exported {len(new_entries)} Unity asset entries to {args.translation_json}")
    print(f"Prefilled Unity asset translations: {translated}")
    return 0


def apply_text_asset_entries(asset: Asset, file_name: str, entries: list[dict[str, Any]], allow_missing: bool) -> int:
    total = 0
    for entry in entries:
        path_id = int(entry["pathId"])
        if path_id not in asset.objects:
            if allow_missing:
                continue
            raise KeyError(f"{file_name}: pathId {path_id} was not found")

        obj = asset.objects[path_id]
        data = obj.contents
        if data.script != entry["source"]:
            if allow_missing:
                continue
            raise ValueError(f"{file_name}: {entry['name']} source text does not match")

        data.script = entry["translation"]
        total += 1
        print(f"{file_name}: {entry['name']} -> translated")
    return total


def apply_object_string_entries(asset: Asset, file_name: str, entries: list[dict[str, Any]], allow_missing: bool) -> int:
    total = 0
    for entry in entries:
        path_id = int(entry["pathId"])
        if path_id not in asset.objects:
            if allow_missing:
                continue
            raise KeyError(f"{file_name}: pathId {path_id} was not found")

        obj = asset.objects[path_id]
        data = obj.contents
        path = entry["path"]
        if get_by_parts(data, path) != entry["source"]:
            if allow_missing:
                continue
            raise ValueError(f"{file_name}: {entry['fieldPath']} source text does not match")

        set_by_parts(data, path, entry["translation"])
        total += 1
        print(f"{file_name}: {entry['fieldPath']} -> translated")
    return total


def apply_assets(args: argparse.Namespace) -> int:
    spec = load_spec(args.translation_json)
    entries = [
        entry
        for entry in spec.get("entries", [])
        if entry.get("kind") in {TEXT_ASSET_KIND, OBJECT_STRING_KIND} and has_text(entry.get("translation"))
    ]
    if not entries:
        print("No filled Unity asset translations to apply.")
        return 0

    total = 0
    by_file: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        by_file.setdefault(entry["file"], []).append(entry)

    for file_name, file_entries in sorted(by_file.items()):
        asset_path = args.root / file_name
        if not asset_path.exists():
            if args.allow_missing:
                continue
            raise FileNotFoundError(asset_path)

        asset = read_asset(asset_path)
        try:
            total += apply_text_asset_entries(
                asset,
                file_name,
                [entry for entry in file_entries if entry.get("kind") == TEXT_ASSET_KIND],
                args.allow_missing,
            )
            total += apply_object_string_entries(
                asset,
                file_name,
                [entry for entry in file_entries if entry.get("kind") == OBJECT_STRING_KIND],
                args.allow_missing,
            )

            temp_path = asset_path.with_suffix(asset_path.suffix + ".tmp")
            with temp_path.open("wb") as output:
                asset.save(output)
        finally:
            close_asset(asset)

        os.replace(temp_path, asset_path)

    print(f"Applied {total} Unity asset translations.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    export_parser = subparsers.add_parser("export")
    export_parser.add_argument("root", type=Path)
    export_parser.add_argument("translation_json", type=Path)
    export_parser.add_argument("--asset", action="append", required=True)
    export_parser.add_argument("--container", default="")
    export_parser.add_argument("--merge", action="append", type=Path, default=[])
    export_parser.add_argument("--object-strings", action="store_true")
    export_parser.add_argument("--all-object-strings", action="store_true")
    export_parser.set_defaults(func=export_assets)

    apply_parser = subparsers.add_parser("apply")
    apply_parser.add_argument("root", type=Path)
    apply_parser.add_argument("translation_json", type=Path)
    apply_parser.add_argument("--allow-missing", action="store_true")
    apply_parser.set_defaults(func=apply_assets)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
