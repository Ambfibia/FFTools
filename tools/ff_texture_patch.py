#!/usr/bin/env python3
"""Export and patch FusionFall Unity Texture2D images.

The tool works on directories extracted by ffbuildtool. Export writes PNG files
and a manifest. Apply reads the manifest and replaces Texture2D image data when
the corresponding PNG was edited.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
UNITYPACK_ROOT = REPO_ROOT / "UnityPackFF"
if str(UNITYPACK_ROOT) not in sys.path:
    sys.path.insert(0, str(UNITYPACK_ROOT))

from unitypack.asset import Asset  # noqa: E402
from unitypack.engine.texture import Texture2D, TextureFormat  # noqa: E402


MANIFEST_FORMAT = "fftools.texture-patch.v1"
DEFAULT_MANIFEST = "manifest.json"
PNG_FORMAT = {
    TextureFormat.Alpha8,
    TextureFormat.RGB24,
    TextureFormat.RGBA32,
    TextureFormat.ARGB32,
    TextureFormat.DXT1,
    TextureFormat.DXT3,
    TextureFormat.DXT5,
}


@dataclass
class TextureRecord:
    obj: object
    texture: Texture2D


def import_pillow():
    try:
        from PIL import Image
    except ImportError as exc:
        raise SystemExit(
            "Pillow is required for texture PNG export/patching. "
            "Install it for the Python runtime used by FFTools."
        ) from exc
    return Image


def flip_image_for_png(image):
    Image = import_pillow()
    return image.transpose(Image.Transpose.FLIP_TOP_BOTTOM)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._ -]+", "_", value).strip(" .")
    return cleaned or "texture"


def load_asset(asset_path: Path) -> Asset:
    handle = asset_path.open("rb")
    asset = Asset.from_file(handle)
    asset._fftools_handle = handle
    return asset


def close_asset(asset: Asset) -> None:
    handle = getattr(asset, "_fftools_handle", None)
    if handle is not None:
        handle.close()


def iter_textures(asset: Asset) -> list[TextureRecord]:
    records: list[TextureRecord] = []
    for obj in asset.objects.values():
        if obj.class_id != 28:
            continue
        texture = obj.contents
        if isinstance(texture, Texture2D):
            records.append(TextureRecord(obj, texture))
    return records


def relative_posix(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def should_export(texture: Texture2D, args: argparse.Namespace) -> bool:
    if texture.format not in PNG_FORMAT:
        return False
    if texture.width <= 0 or texture.height <= 0:
        return False
    if args.min_width and texture.width < args.min_width:
        return False
    if args.min_height and texture.height < args.min_height:
        return False
    if args.name_regex and not re.search(args.name_regex, texture.name, re.IGNORECASE):
        return False
    if args.path_id and str(args.path_id) != "":
        return str(texture._record_path_id) in args.path_id
    return True


def export_textures(args: argparse.Namespace) -> int:
    import_pillow()

    extracted_dir = args.extracted_dir.resolve()
    asset_path = extracted_dir / args.asset
    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        asset = load_asset(asset_path)
    except Exception as exc:
        if args.allow_invalid_asset:
            print(f"skip non-asset file {asset_path.name}: {exc}")
            return 0
        raise

    entries = []
    skipped = 0
    try:
        try:
            texture_records = iter_textures(asset)
        except Exception as exc:
            if args.allow_invalid_asset:
                print(f"skip non-asset file {asset_path.name}: {exc}")
                return 0
            raise

        for record in texture_records:
            texture = record.texture
            texture._record_path_id = record.obj.path_id
            if not should_export(texture, args):
                skipped += 1
                continue

            file_name = f"{record.obj.path_id}__{safe_name(texture.name)}.png"
            png_path = out_dir / safe_name(args.container) / safe_name(args.asset) / file_name
            png_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                image = texture.image
                if image is None:
                    skipped += 1
                    continue
                flip_image_for_png(image).save(png_path)
            except Exception as exc:
                print(f"skip {texture.name} ({record.obj.path_id}): {exc}", file=sys.stderr)
                skipped += 1
                continue

            entries.append(
                {
                    "container": args.container,
                    "asset": args.asset,
                    "path_id": record.obj.path_id,
                    "name": texture.name,
                    "width": texture.width,
                    "height": texture.height,
                    "texture_format": texture.format.name,
                    "file": relative_posix(png_path, out_dir),
                    "exported_png_sha256": sha256_file(png_path),
                }
            )
    finally:
        close_asset(asset)

    manifest_path = out_dir / args.manifest
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("format") != MANIFEST_FORMAT:
            raise SystemExit(f"Unsupported texture manifest format: {manifest.get('format')!r}")
        old_entries = manifest.get("entries", [])
        manifest["entries"] = [
            entry for entry in old_entries
            if entry.get("container") != args.container or entry.get("asset") != args.asset
        ]
        manifest["entries"].extend(entries)
    else:
        manifest = {
            "format": MANIFEST_FORMAT,
            "entries": entries,
        }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"exported {len(entries)} texture PNG(s) to {out_dir}")
    if skipped:
        print(f"skipped {skipped} texture(s)")
    print(f"manifest: {manifest_path}")
    return 0


def find_replacement(entry: dict, texture_dir: Path, replacements_dir: Path | None) -> Path | None:
    rel_file = Path(entry["file"])
    candidates = []
    if replacements_dir is not None:
        candidates.append(replacements_dir / rel_file)
        candidates.append(replacements_dir / rel_file.name)
    candidates.append(texture_dir / rel_file)

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def encode_rgba32(image_path: Path, width: int, height: int, allow_resize: bool) -> bytes:
    Image = import_pillow()
    with Image.open(image_path) as image:
        if image.size != (width, height):
            if not allow_resize:
                raise ValueError(
                    f"{image_path} is {image.size[0]}x{image.size[1]}, expected {width}x{height}"
                )
            image = image.resize((width, height), Image.LANCZOS)
        image = image.convert("RGBA")
        image = image.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
        return image.tobytes("raw", "RGBA")


def patch_texture(texture: Texture2D, png_path: Path, allow_resize: bool) -> None:
    data = encode_rgba32(png_path, texture.width, texture.height, allow_resize)
    texture._obj["m_TextureFormat"] = int(TextureFormat.RGBA32)
    texture._obj["m_CompleteImageSize"] = len(data)
    texture._obj["m_MipMap"] = False
    texture._obj["m_ImageCount"] = 1
    texture._obj["image data"] = data


def apply_textures(args: argparse.Namespace) -> int:
    extracted_dir = args.extracted_dir.resolve()
    texture_dir = args.texture_dir.resolve()
    manifest_path = texture_dir / args.manifest
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("format") != MANIFEST_FORMAT:
        raise SystemExit(f"Unsupported texture manifest format: {manifest.get('format')!r}")

    asset_name = args.asset or manifest.get("asset")
    container_name = args.container or manifest.get("container", "")
    if not asset_name:
        raise SystemExit("Specify --asset when applying a multi-asset texture manifest.")
    asset_path = extracted_dir / asset_name
    out_asset_path = (args.out_asset or asset_path).resolve()
    replacements_dir = args.replacements_dir.resolve() if args.replacements_dir else None

    asset = load_asset(asset_path)
    asset_closed = False
    patched = 0
    unchanged = 0
    missing = 0
    try:
        by_path_id = {record.obj.path_id: record for record in iter_textures(asset)}
        for entry in manifest["entries"]:
            if entry.get("asset") != asset_name:
                continue
            if container_name and entry.get("container") not in ("", container_name):
                continue
            replacement = find_replacement(entry, texture_dir, replacements_dir)
            if replacement is None:
                missing += 1
                continue
            if not args.apply_unchanged and sha256_file(replacement) == entry.get("exported_png_sha256"):
                unchanged += 1
                continue

            record = by_path_id.get(int(entry["path_id"]))
            if record is None:
                missing += 1
                continue

            patch_texture(record.texture, replacement, args.allow_resize)
            patched += 1

        if patched:
            out_asset_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = out_asset_path.with_suffix(out_asset_path.suffix + ".tmp")
            with temp_path.open("wb") as handle:
                asset.save(handle)
            close_asset(asset)
            asset_closed = True
            temp_path.replace(out_asset_path)
    finally:
        if not asset_closed:
            close_asset(asset)

    print(f"patched {patched} texture(s) in {out_asset_path}")
    if unchanged:
        print(f"unchanged PNG(s) skipped: {unchanged}")
    if missing:
        print(f"missing manifest target(s): {missing}")
    if args.status_file:
        args.status_file.parent.mkdir(parents=True, exist_ok=True)
        args.status_file.write_text(
            json.dumps(
                {
                    "asset": asset_name,
                    "container": container_name,
                    "patched": patched,
                    "unchanged": unchanged,
                    "missing": missing,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    export_parser = subparsers.add_parser("export", help="Export Texture2D objects to PNG.")
    export_parser.add_argument("extracted_dir", type=Path)
    export_parser.add_argument("out_dir", type=Path)
    export_parser.add_argument("--asset", default="sharedassets0.assets")
    export_parser.add_argument("--container", default="main.unity3d")
    export_parser.add_argument("--manifest", default=DEFAULT_MANIFEST)
    export_parser.add_argument("--name-regex", default="")
    export_parser.add_argument("--path-id", action="append", default=[])
    export_parser.add_argument("--min-width", type=int, default=0)
    export_parser.add_argument("--min-height", type=int, default=0)
    export_parser.add_argument("--allow-invalid-asset", action="store_true")
    export_parser.set_defaults(func=export_textures)

    apply_parser = subparsers.add_parser("apply", help="Patch Texture2D objects from edited PNG files.")
    apply_parser.add_argument("extracted_dir", type=Path)
    apply_parser.add_argument("texture_dir", type=Path)
    apply_parser.add_argument("--asset", default="")
    apply_parser.add_argument("--container", default="")
    apply_parser.add_argument("--manifest", default=DEFAULT_MANIFEST)
    apply_parser.add_argument("--replacements-dir", type=Path)
    apply_parser.add_argument("--out-asset", type=Path)
    apply_parser.add_argument("--status-file", type=Path)
    apply_parser.add_argument("--allow-resize", action="store_true")
    apply_parser.add_argument("--apply-unchanged", action="store_true")
    apply_parser.set_defaults(func=apply_textures)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
