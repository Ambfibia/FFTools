#!/usr/bin/env python3
"""Pack and unpack FusionFall Unity Web Player containers.

The beta client uses old UnityWeb/streamed files: a small big-endian header
followed by one LZMA-alone block. The decompressed block is a file table plus
the actual file payloads.
"""

from __future__ import annotations

import argparse
import json
import lzma
import struct
from dataclasses import dataclass
from pathlib import Path


LZMA_FILTER = {
    "id": lzma.FILTER_LZMA1,
    "dict_size": 0x800000,
    "lc": 3,
    "lp": 0,
    "pb": 2,
}
LZMA_ALONE_PROPS = b"\x5d\x00\x00\x80\x00"


@dataclass
class UnityWebHeader:
    signature: str
    format_version: int
    unity_version: str
    generator_version: str


def read_cstring(data: bytes, offset: int) -> tuple[str, int]:
    end = data.index(b"\0", offset)
    return data[offset:end].decode("utf-8"), end + 1


def write_cstring(value: str) -> bytes:
    return value.encode("utf-8") + b"\0"


def parse_container(data: bytes) -> tuple[UnityWebHeader, bytes]:
    offset = 0
    signature, offset = read_cstring(data, offset)
    if signature not in ("UnityWeb", "streamed"):
        raise ValueError(f"Unsupported signature: {signature!r}")

    format_version = struct.unpack_from(">i", data, offset)[0]
    offset += 4
    unity_version, offset = read_cstring(data, offset)
    generator_version, offset = read_cstring(data, offset)

    file_size, header_size, file_count, bundle_count = struct.unpack_from(">IIII", data, offset)
    offset += 16
    if file_size != len(data):
        raise ValueError(f"Header file size {file_size} does not match actual {len(data)}")
    if file_count != 1 or bundle_count != 1:
        raise ValueError(f"Unexpected UnityWeb bundle counts: {file_count}, {bundle_count}")

    bundle_size, uncompressed_size, last_offset = struct.unpack_from(">III", data, offset)
    offset += 12
    dummy = data[offset]
    offset += 1
    if dummy != 0:
        raise ValueError(f"Unexpected UnityWeb dummy byte: {dummy}")
    if last_offset != file_size:
        raise ValueError(f"Header last offset {last_offset} does not match file size {file_size}")
    padding = data[offset:header_size]
    if any(padding):
        raise ValueError(f"Unexpected non-zero UnityWeb header padding: {padding!r}")

    compressed = data[header_size:header_size + bundle_size]
    decompressed = lzma.decompress(compressed, format=lzma.FORMAT_AUTO)
    if len(decompressed) != uncompressed_size:
        raise ValueError(
            f"Decompressed size {len(decompressed)} does not match stored {uncompressed_size}"
        )

    return UnityWebHeader(signature, format_version, unity_version, generator_version), decompressed


def parse_file_table(block: bytes) -> list[tuple[str, bytes]]:
    offset = 0
    file_count = struct.unpack_from(">I", block, offset)[0]
    offset += 4

    entries: list[tuple[str, int, int]] = []
    for _ in range(file_count):
        name, offset = read_cstring(block, offset)
        file_offset, size = struct.unpack_from(">II", block, offset)
        offset += 8
        entries.append((name, file_offset, size))

    files: list[tuple[str, bytes]] = []
    for name, file_offset, size in entries:
        files.append((name, block[file_offset:file_offset + size]))
    return files


def build_file_table(files: list[tuple[str, bytes]]) -> bytes:
    table_size = 4
    for name, _ in files:
        table_size += len(write_cstring(name)) + 8

    chunks = [struct.pack(">I", len(files))]
    payload = bytearray()
    offset = table_size
    for name, contents in files:
        chunks.append(write_cstring(name))
        chunks.append(struct.pack(">II", offset, len(contents)))
        payload += contents
        offset += len(contents)

    return b"".join(chunks) + bytes(payload)


def compress_lzma_alone(block: bytes) -> bytes:
    raw = lzma.compress(block, format=lzma.FORMAT_RAW, filters=[LZMA_FILTER])
    return LZMA_ALONE_PROPS + struct.pack("<Q", len(block)) + raw


def build_container(header: UnityWebHeader, block: bytes) -> bytes:
    compressed = compress_lzma_alone(block)
    header_without_sizes = b"".join(
        [
            write_cstring(header.signature),
            struct.pack(">i", header.format_version),
            write_cstring(header.unity_version),
            write_cstring(header.generator_version),
        ]
    )
    header_size = len(header_without_sizes) + 30
    file_size = header_size + len(compressed)
    packed_header = b"".join(
        [
            header_without_sizes,
            struct.pack(">IIII", file_size, header_size, 1, 1),
            struct.pack(">III", len(compressed), len(block), file_size),
            b"\0\0",
        ]
    )
    if len(packed_header) != header_size:
        raise AssertionError("UnityWeb header size calculation mismatch")
    return packed_header + compressed


def unpack(container_path: Path, out_dir: Path) -> None:
    header, block = parse_container(container_path.read_bytes())
    files = parse_file_table(block)
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "signature": header.signature,
        "format_version": header.format_version,
        "unity_version": header.unity_version,
        "generator_version": header.generator_version,
        "files": [name for name, _ in files],
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    for name, contents in files:
        target = out_dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(contents)


def pack(in_dir: Path, out_path: Path) -> None:
    manifest = json.loads((in_dir / "manifest.json").read_text(encoding="utf-8"))
    header = UnityWebHeader(
        manifest["signature"],
        int(manifest["format_version"]),
        manifest["unity_version"],
        manifest["generator_version"],
    )
    files = []
    for name in manifest["files"]:
        files.append((name, (in_dir / name).read_bytes()))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(build_container(header, build_file_table(files)))


def list_files(container_path: Path) -> None:
    header, block = parse_container(container_path.read_bytes())
    print(
        f"{container_path}: {header.signature} {header.format_version} "
        f"{header.unity_version} {header.generator_version}"
    )
    for name, contents in parse_file_table(block):
        print(f"{len(contents):>10}  {name}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list")
    list_parser.add_argument("container", type=Path)

    unpack_parser = subparsers.add_parser("unpack")
    unpack_parser.add_argument("container", type=Path)
    unpack_parser.add_argument("out_dir", type=Path)

    pack_parser = subparsers.add_parser("pack")
    pack_parser.add_argument("in_dir", type=Path)
    pack_parser.add_argument("out_container", type=Path)

    args = parser.parse_args()
    if args.command == "list":
        list_files(args.container)
    elif args.command == "unpack":
        unpack(args.container, args.out_dir)
    elif args.command == "pack":
        pack(args.in_dir, args.out_container)


if __name__ == "__main__":
    main()
