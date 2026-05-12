#!/usr/bin/env python3
"""Audit Unity 2.x bitmap Font objects for Russian character coverage."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UNITYPACK = ROOT / "UnityPackFF"
if str(UNITYPACK) not in sys.path:
    sys.path.insert(0, str(UNITYPACK))

from unitypack.asset import Asset  # noqa: E402


RUSSIAN_CODES = (
    list(range(0x410, 0x430))
    + [0x401]
    + list(range(0x430, 0x450))
    + [0x451]
)
RUSSIAN = "".join(chr(code) for code in RUSSIAN_CODES)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("asset", type=Path)
    args = parser.parse_args()

    with args.asset.open("rb") as asset_file:
        asset = Asset.from_file(asset_file)
        asset.load()

        for path_id, obj in asset.objects.items():
            if obj.type_id != 128:
                continue

            font = obj.read()._obj
            chars = {item["index"] for item in font.get("m_CharacterRects", [])}
            missing = "".join(ch for ch in RUSSIAN if ord(ch) not in chars)
            status = "OK" if not missing else f"missing: {missing}"
            print(
                f"{path_id:>5}  {font.get('m_Name', ''):<28} "
                f"chars={len(chars):>5}  cyr={sum(0x400 <= c <= 0x4ff for c in chars):>3}  {status}"
            )


if __name__ == "__main__":
    main()
