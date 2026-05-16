#!/usr/bin/env python3
"""Patch FusionFall GUI bitmap fonts from replacement TTF files."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import platform
import re
import sys
import struct
from pathlib import Path
from typing import Any, NamedTuple
from ctypes import wintypes


ROOT = Path(__file__).resolve().parents[1]
UNITYPACK = ROOT / "UnityPackFF"
if str(UNITYPACK) not in sys.path:
    sys.path.insert(0, str(UNITYPACK))

from unitypack.asset import Asset  # noqa: E402
from unitypack.object import FFOrderedDict, ObjectPointer  # noqa: E402


RUSSIAN_CODES = (
    list(range(0x410, 0x430))
    + [0x401]
    + list(range(0x430, 0x450))
    + [0x451]
)
ASCII_CODES = list(range(0x20, 0x7F))
CP1251_RUSSIAN_ALIASES = {
    **{0xC0 + index: 0x410 + index for index in range(0x20)},
    **{0xE0 + index: 0x430 + index for index in range(0x20)},
    0xA8: 0x401,
    0xB8: 0x451,
}
DEFAULT_TTF_PATCH_CODES = ASCII_CODES + RUSSIAN_CODES + sorted(CP1251_RUSSIAN_ALIASES)


MANUAL_FONT_FALLBACKS = {
    "ChaletBook-Regular Small 1": "ChaletBook-Regular Small",
    "JEFFE___72": "JEFFE___40",
}

FONT_VERTICAL_OFFSETS = {
    "JEFFE": 2.0,
}


def normalize_font_family(name: str) -> str:
    normalized = name.strip()
    normalized = re.sub(r"\s+Small(?:\s+\d+)?$", "", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"[_\-\s]*\d+$", "", normalized)
    normalized = re.sub(r"[_\-\s]+$", "", normalized)
    if normalized.upper().startswith("JEFFE"):
        return "JEFFE"
    return normalized or name.strip()


def build_ttf_font_map(font_dir: Path | None) -> dict[str, Path]:
    if font_dir is None:
        return {}
    if not font_dir.exists():
        raise FileNotFoundError(f"TTF font directory was not found: {font_dir}")

    result: dict[str, Path] = {}
    for path in sorted(font_dir.glob("*.ttf")):
        result[normalize_font_family(path.stem)] = path
    return result


class GlyphBitmap(NamedTuple):
    code: int
    render_code: int
    width: int
    height: int
    origin_x: int
    origin_y: int
    advance: int
    alpha_rows: list[bytes]


class GdiFixed(ctypes.Structure):
    _fields_ = [("fract", wintypes.WORD), ("value", wintypes.SHORT)]


class GdiMat2(ctypes.Structure):
    _fields_ = [
        ("eM11", GdiFixed),
        ("eM12", GdiFixed),
        ("eM21", GdiFixed),
        ("eM22", GdiFixed),
    ]


class GdiGlyphMetrics(ctypes.Structure):
    _fields_ = [
        ("gmBlackBoxX", wintypes.UINT),
        ("gmBlackBoxY", wintypes.UINT),
        ("gmptGlyphOrigin", wintypes.POINT),
        ("gmCellIncX", ctypes.c_short),
        ("gmCellIncY", ctypes.c_short),
    ]


def next_power_of_two(value: int) -> int:
    result = 1
    while result < value:
        result <<= 1
    return result


def extract_ttf_family_name(ttf_path: Path) -> str:
    data = ttf_path.read_bytes()
    if len(data) < 12:
        raise ValueError(f"TTF file is too small: {ttf_path}")

    table_count = struct.unpack_from(">H", data, 4)[0]
    name_table: tuple[int, int] | None = None
    offset = 12
    for _ in range(table_count):
        tag, _checksum, table_offset, length = struct.unpack_from(">4sIII", data, offset)
        offset += 16
        if tag == b"name":
            name_table = (table_offset, length)
            break

    if name_table is None:
        raise ValueError(f"TTF name table was not found: {ttf_path}")

    table_offset, table_length = name_table
    if table_offset + table_length > len(data):
        raise ValueError(f"TTF name table is truncated: {ttf_path}")

    _format, record_count, strings_offset = struct.unpack_from(">HHH", data, table_offset)
    candidates: list[tuple[int, str]] = []
    for index in range(record_count):
        rec_offset = table_offset + 6 + index * 12
        platform_id, encoding_id, language_id, name_id, length, value_offset = struct.unpack_from(
            ">HHHHHH", data, rec_offset
        )
        if name_id not in (1, 4):
            continue

        start = table_offset + strings_offset + value_offset
        raw = data[start:start + length]
        try:
            if platform_id == 3:
                value = raw.decode("utf-16-be").strip("\0 ")
            elif platform_id == 1:
                value = raw.decode("macroman").strip("\0 ")
            else:
                continue
        except UnicodeDecodeError:
            continue

        if not value:
            continue

        score = 0
        if name_id == 1:
            score += 100
        if platform_id == 3:
            score += 50
        if language_id in (0x409, 0):
            score += 10
        if encoding_id in (1, 10):
            score += 5
        candidates.append((score, value))

    if not candidates:
        raise ValueError(f"TTF family name was not found: {ttf_path}")

    return max(candidates, key=lambda item: item[0])[1]


class GdiFontRenderer:
    FR_PRIVATE = 0x10
    DEFAULT_CHARSET = 1
    OUT_TT_ONLY_PRECIS = 7
    CLIP_DEFAULT_PRECIS = 0
    ANTIALIASED_QUALITY = 4
    DEFAULT_PITCH = 0
    FW_NORMAL = 400
    GGO_GRAY8_BITMAP = 6
    GDI_ERROR = 0xFFFFFFFF

    def __init__(self, ttf_path: Path, face_name: str, pixel_height: int) -> None:
        if platform.system() != "Windows":
            raise RuntimeError("TTF bitmap font patching currently requires Windows GDI.")

        self.ttf_path = str(ttf_path)
        self.face_name = face_name
        self.pixel_height = max(1, int(pixel_height))
        self.gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._configure_api()
        self.added_font = False
        self.hdc = None
        self.font = None
        self.old_font = None
        self.mat2 = GdiMat2(
            GdiFixed(0, 1),
            GdiFixed(0, 0),
            GdiFixed(0, 0),
            GdiFixed(0, 1),
        )

    def _configure_api(self) -> None:
        self.gdi32.AddFontResourceExW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p]
        self.gdi32.AddFontResourceExW.restype = ctypes.c_int
        self.gdi32.RemoveFontResourceExW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p]
        self.gdi32.RemoveFontResourceExW.restype = wintypes.BOOL
        self.gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
        self.gdi32.CreateCompatibleDC.restype = wintypes.HDC
        self.gdi32.DeleteDC.argtypes = [wintypes.HDC]
        self.gdi32.DeleteDC.restype = wintypes.BOOL
        self.gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
        self.gdi32.DeleteObject.restype = wintypes.BOOL
        self.gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
        self.gdi32.SelectObject.restype = wintypes.HGDIOBJ
        self.gdi32.CreateFontW.restype = wintypes.HFONT
        self.gdi32.GetGlyphOutlineW.argtypes = [
            wintypes.HDC,
            wintypes.UINT,
            wintypes.UINT,
            ctypes.POINTER(GdiGlyphMetrics),
            wintypes.DWORD,
            wintypes.LPVOID,
            ctypes.POINTER(GdiMat2),
        ]
        self.gdi32.GetGlyphOutlineW.restype = wintypes.DWORD

    def __enter__(self) -> "GdiFontRenderer":
        if self.gdi32.AddFontResourceExW(self.ttf_path, self.FR_PRIVATE, None) <= 0:
            raise RuntimeError(f"Windows could not load TTF font: {self.ttf_path}")
        self.added_font = True

        self.hdc = self.gdi32.CreateCompatibleDC(None)
        if not self.hdc:
            raise RuntimeError("Windows could not create a GDI device context.")

        self.font = self.gdi32.CreateFontW(
            -self.pixel_height,
            0,
            0,
            0,
            self.FW_NORMAL,
            0,
            0,
            0,
            self.DEFAULT_CHARSET,
            self.OUT_TT_ONLY_PRECIS,
            self.CLIP_DEFAULT_PRECIS,
            self.ANTIALIASED_QUALITY,
            self.DEFAULT_PITCH,
            self.face_name,
        )
        if not self.font:
            raise RuntimeError(f"Windows could not create font face {self.face_name!r}.")

        self.old_font = self.gdi32.SelectObject(self.hdc, self.font)
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        if self.hdc and self.old_font:
            self.gdi32.SelectObject(self.hdc, self.old_font)
        if self.font:
            self.gdi32.DeleteObject(self.font)
        if self.hdc:
            self.gdi32.DeleteDC(self.hdc)
        if self.added_font:
            self.gdi32.RemoveFontResourceExW(self.ttf_path, self.FR_PRIVATE, None)

    def render_glyph(self, code: int) -> GlyphBitmap | None:
        metrics = GdiGlyphMetrics()
        size = self.gdi32.GetGlyphOutlineW(
            self.hdc,
            code,
            self.GGO_GRAY8_BITMAP,
            ctypes.byref(metrics),
            0,
            None,
            ctypes.byref(self.mat2),
        )
        if size == self.GDI_ERROR:
            return None

        width = int(metrics.gmBlackBoxX)
        height = int(metrics.gmBlackBoxY)
        advance = max(0, int(metrics.gmCellIncX))
        if width == 0 or height == 0:
            return GlyphBitmap(code, code, 0, 0, 0, 0, advance, [])

        buffer = (ctypes.c_ubyte * size)()
        rendered = self.gdi32.GetGlyphOutlineW(
            self.hdc,
            code,
            self.GGO_GRAY8_BITMAP,
            ctypes.byref(metrics),
            size,
            buffer,
            ctypes.byref(self.mat2),
        )
        if rendered == self.GDI_ERROR:
            return None

        stride = (width + 3) & ~3
        available = int(rendered)
        rows: list[bytes] = []
        for y in range(height):
            row = bytes(
                min(255, int(buffer[y * stride + x]) * 4) if y * stride + x < available else 0
                for x in range(width)
            )
            rows.append(row)

        return GlyphBitmap(
            code,
            code,
            width,
            height,
            int(metrics.gmptGlyphOrigin.x),
            int(metrics.gmptGlyphOrigin.y),
            advance,
            rows,
        )

    def render_glyph_alias(self, code: int, render_code: int) -> GlyphBitmap | None:
        glyph = self.render_glyph(render_code)
        if glyph is None:
            return None
        return GlyphBitmap(code, render_code, glyph.width, glyph.height, glyph.origin_x, glyph.origin_y, glyph.advance, glyph.alpha_rows)


def font_has_cyrillic(font: dict[str, Any]) -> bool:
    chars = {item["index"] for item in font.get("m_CharacterRects", [])}
    return all(code in chars for code in RUSSIAN_CODES)


def texture_to_logical_alpha(texture: dict[str, Any]) -> bytearray:
    width = int(texture["m_Width"])
    height = int(texture["m_Height"])
    data = texture.get("image data", b"")
    if texture.get("m_TextureFormat") != 1:
        raise ValueError("Only Alpha8 font textures can be patched from TTF.")
    if len(data) != width * height:
        raise ValueError(
            f"Unexpected Alpha8 texture data length {len(data)} for {width}x{height} texture."
        )

    logical = bytearray(width * height)
    for y in range(height):
        source = (height - 1 - y) * width
        target = y * width
        logical[target:target + width] = data[source:source + width]
    return logical


def logical_alpha_to_texture_data(logical: bytearray, width: int, height: int) -> bytes:
    raw = bytearray(width * height)
    for y in range(height):
        source = y * width
        target = (height - 1 - y) * width
        raw[target:target + width] = logical[source:source + width]
    return bytes(raw)


def rect_pixels(rect: dict[str, Any], texture_width: int, texture_height: int) -> tuple[int, int, int, int]:
    uv = rect["uv"]
    x = int(round(float(uv["x"]) * texture_width))
    w = int(round(float(uv["width"]) * texture_width))
    h = int(round(float(uv["height"]) * texture_height))
    y = int(round(texture_height - (float(uv["y"]) + float(uv["height"])) * texture_height))
    y = max(0, min(texture_height, y))
    return x, y, w, h


def set_rect_uv(rect: dict[str, Any], x: int, y: int, width: int, height: int, atlas_width: int, atlas_height: int) -> None:
    rect["uv"]["x"] = float(x) / float(atlas_width)
    rect["uv"]["y"] = float(atlas_height - y - height) / float(atlas_height)
    rect["uv"]["width"] = float(width) / float(atlas_width)
    rect["uv"]["height"] = float(height) / float(atlas_height)


def make_character_rect(
    code: int,
    glyph: GlyphBitmap,
    x: int,
    y: int,
    atlas_width: int,
    atlas_height: int,
    line_spacing: float,
    vertical_offset: float = 0.0,
) -> FFOrderedDict:
    rect = FFOrderedDict()
    rect["index"] = code
    rect["uv"] = FFOrderedDict()
    rect["vert"] = FFOrderedDict()
    set_rect_uv(rect, x, y, glyph.width, glyph.height, atlas_width, atlas_height)
    vert_x = max(0, int(glyph.origin_x))
    ink_right = vert_x + int(glyph.width)
    advance = max(int(glyph.advance), ink_right)
    rect["vert"]["x"] = float(vert_x)
    rect["vert"]["y"] = -max(0.0, float(line_spacing) - float(glyph.origin_y)) + float(vertical_offset)
    rect["vert"]["width"] = float(glyph.width)
    rect["vert"]["height"] = -float(glyph.height)
    rect["width"] = float(advance)
    return rect


def try_pack_glyphs(
    glyphs: list[GlyphBitmap],
    start_y: int,
    atlas_width: int,
    atlas_height: int,
    padding: int,
) -> dict[int, tuple[int, int]] | None:
    positions: dict[int, tuple[int, int]] = {}
    x = padding
    y = start_y
    row_height = 0

    for glyph in glyphs:
        if glyph.width == 0 or glyph.height == 0:
            positions[glyph.code] = (x, y)
            continue

        if glyph.width + padding * 2 > atlas_width:
            return None

        if x + glyph.width + padding > atlas_width:
            x = padding
            y += row_height + padding
            row_height = 0

        if y + glyph.height + padding > atlas_height:
            return None

        positions[glyph.code] = (x, y)
        x += glyph.width + padding
        row_height = max(row_height, glyph.height)

    return positions


def patch_font_with_ttf(
    asset: Asset,
    font_path_id: int,
    ttf_path: Path,
    face_name: str,
    size_scale: float,
    padding: int,
    max_texture_size: int,
    replace_ascii: bool,
) -> dict[str, Any]:
    font = asset.objects[font_path_id].contents._obj
    texture_pointer = font.get("m_Texture")
    if not texture_pointer:
        raise ValueError("Font has no m_Texture pointer.")
    texture_obj = texture_pointer.object
    texture = texture_obj.contents._obj
    old_width = int(texture["m_Width"])
    old_height = int(texture["m_Height"])
    logical = texture_to_logical_alpha(texture)

    existing_rects = font.get("m_CharacterRects", [])
    patch_codes = DEFAULT_TTF_PATCH_CODES if replace_ascii else RUSSIAN_CODES + sorted(CP1251_RUSSIAN_ALIASES)
    patch_code_set = set(patch_codes)
    existing_rect_by_code = {int(rect["index"]): rect for rect in existing_rects}
    existing_codes = set(existing_rect_by_code)

    line_spacing = float(font.get("m_LineSpacing") or 16.0)
    font_family = normalize_font_family(font.get("m_Name", ""))
    vertical_offset = FONT_VERTICAL_OFFSETS.get(font_family, 0.0)
    pixel_height = max(1, int(round(line_spacing * size_scale)))
    with GdiFontRenderer(ttf_path, face_name, pixel_height) as renderer:
        glyphs = []
        for code in patch_codes:
            render_code = CP1251_RUSSIAN_ALIASES.get(code, code)
            glyph = renderer.render_glyph_alias(code, render_code) if render_code != code else renderer.render_glyph(code)
            if glyph is not None:
                glyphs.append(glyph)

    if not glyphs:
        raise ValueError("No glyphs could be rendered from the supplied TTF.")

    existing_positions_by_code = {
        int(rect["index"]): rect_pixels(rect, old_width, old_height)
        for rect in existing_rects
    }
    kept_rects = [
        rect
        for rect in existing_rects
        if int(rect["index"]) not in patch_code_set
    ]
    kept_positions = [
        existing_positions_by_code[int(rect["index"])]
        for rect in kept_rects
    ]

    reused_positions: dict[int, tuple[int, int]] = {}
    glyphs_to_pack: list[GlyphBitmap] = []
    for glyph in glyphs:
        old_rect = existing_rect_by_code.get(glyph.code)
        if old_rect is None:
            glyphs_to_pack.append(glyph)
            continue

        old_x, old_y, old_w, old_h = existing_positions_by_code[glyph.code]
        if glyph.width <= old_w and glyph.height <= old_h:
            reused_positions[glyph.code] = (old_x, old_y)
        else:
            glyphs_to_pack.append(glyph)

    occupied_positions = list(existing_positions_by_code.values())
    start_y = padding
    if occupied_positions:
        start_y = max(y + h + padding for _x, y, _w, h in occupied_positions)

    atlas_width = next_power_of_two(max(old_width, 64))
    atlas_height = next_power_of_two(max(old_height, start_y + padding + 1))
    packed: dict[int, tuple[int, int]] | None = None
    while atlas_width <= max_texture_size and atlas_height <= max_texture_size:
        packed = try_pack_glyphs(glyphs_to_pack, start_y, atlas_width, atlas_height, padding)
        if packed is not None:
            break
        if atlas_height <= atlas_width:
            atlas_height <<= 1
        else:
            atlas_width <<= 1

    if packed is None:
        raise ValueError(
            f"Could not pack {len(glyphs_to_pack)} glyphs into a {max_texture_size}x{max_texture_size} texture."
        )

    new_logical = bytearray(atlas_width * atlas_height)
    for y in range(old_height):
        source = y * old_width
        target = y * atlas_width
        new_logical[target:target + old_width] = logical[source:source + old_width]

    for rect, (x, y, width, height) in zip(kept_rects, kept_positions):
        set_rect_uv(rect, x, y, width, height, atlas_width, atlas_height)

    patched_rects = []
    for glyph in glyphs:
        if glyph.code in reused_positions:
            x, y = reused_positions[glyph.code]
        else:
            x, y = packed[glyph.code]
        old_position = existing_positions_by_code.get(glyph.code)
        if old_position is not None:
            old_x, old_y, old_w, old_h = old_position
            for clear_y in range(old_y, min(old_y + old_h, atlas_height)):
                target = clear_y * atlas_width + old_x
                clear_width = min(old_w, atlas_width - old_x)
                new_logical[target:target + clear_width] = b"\0" * clear_width
        for row_index, row in enumerate(glyph.alpha_rows):
            target = (y + row_index) * atlas_width + x
            new_logical[target:target + glyph.width] = row
        patched_rects.append(
            make_character_rect(
                glyph.code,
                glyph,
                x,
                y,
                atlas_width,
                atlas_height,
                line_spacing,
                vertical_offset,
            )
        )

    font["m_CharacterRects"] = sorted(
        kept_rects + patched_rects,
        key=lambda rect: int(rect["index"]),
    )
    texture["m_Width"] = atlas_width
    texture["m_Height"] = atlas_height
    texture["m_TextureFormat"] = 1
    texture["m_MipMap"] = False
    texture["m_ImageCount"] = 1
    texture["m_CompleteImageSize"] = len(new_logical)
    texture["image data"] = logical_alpha_to_texture_data(new_logical, atlas_width, atlas_height)

    return {
        "font_path_id": font_path_id,
        "font_name": font.get("m_Name", ""),
        "texture_path_id": texture_pointer.path_id,
        "old_texture_size": [old_width, old_height],
        "new_texture_size": [atlas_width, atlas_height],
        "line_spacing": line_spacing,
        "vertical_offset": vertical_offset,
        "pixel_height": pixel_height,
        "patched_codes": [glyph.code for glyph in glyphs],
        "patched_chars": "".join(chr(glyph.code) for glyph in glyphs),
        "cp1251_alias_codes": [glyph.code for glyph in glyphs if glyph.render_code != glyph.code],
        "added_codes": [glyph.code for glyph in glyphs if glyph.code not in existing_codes],
        "replaced_codes": [glyph.code for glyph in glyphs if glyph.code in existing_codes],
        "reused_slots": len(reused_positions),
        "packed_slots": len(glyphs_to_pack),
    }


def patch_fonts_with_ttf(
    asset: Asset,
    fallback_ttf_path: Path | None,
    ttf_font_dir: Path | None,
    face_name: str | None,
    size_scale: float,
    padding: int,
    max_texture_size: int,
    replace_ascii: bool,
) -> list[dict[str, Any]]:
    ttf_by_family = build_ttf_font_map(ttf_font_dir)
    fallback_face = face_name or (extract_ttf_family_name(fallback_ttf_path) if fallback_ttf_path else None)
    reports: list[dict[str, Any]] = []
    for path_id, obj in sorted(asset.objects.items()):
        if obj.type_id != 128:
            continue

        font = obj.read()._obj
        font_name = font.get("m_Name", "")
        font_family = normalize_font_family(font_name)
        ttf_path = ttf_by_family.get(font_family) or fallback_ttf_path
        report_base = {
            "font_path_id": path_id,
            "font_name": font_name,
            "font_family": font_family,
            "ttf_path": str(ttf_path) if ttf_path else None,
        }
        try:
            if ttf_path is None:
                report_base["skipped"] = "no_ttf_configured"
                reports.append(report_base)
                continue
            resolved_face = fallback_face if ttf_path == fallback_ttf_path and fallback_face else extract_ttf_family_name(ttf_path)
            report_base["ttf_face"] = resolved_face
            report = patch_font_with_ttf(
                asset,
                path_id,
                ttf_path,
                resolved_face,
                size_scale,
                padding,
                max_texture_size,
                replace_ascii,
            )
            report.update(report_base)
            reports.append(report)
        except Exception as exc:
            report_base["error"] = str(exc)
            reports.append(report_base)

    return reports


def walk_pointers(value: Any, path: str = ""):
    if isinstance(value, ObjectPointer):
        yield path, value
    elif isinstance(value, dict):
        for key, item in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            yield from walk_pointers(item, child_path)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from walk_pointers(item, f"{path}[{index}]")
    elif isinstance(value, tuple):
        for index, item in enumerate(value):
            yield from walk_pointers(item, f"{path}({index})")


def build_font_map(asset: Asset) -> tuple[dict[int, int], dict[int, dict[str, Any]]]:
    font_info: dict[int, dict[str, Any]] = {}
    cyrillic_by_name: dict[str, list[tuple[int, dict[str, Any]]]] = {}

    for path_id, obj in asset.objects.items():
        if obj.type_id != 128:
            continue

        font = obj.read()._obj
        info = {
            "name": font.get("m_Name", ""),
            "has_cyrillic": font_has_cyrillic(font),
            "char_count": len(font.get("m_CharacterRects", [])),
            "line_spacing": font.get("m_LineSpacing", 0.0),
        }
        font_info[path_id] = info
        if info["has_cyrillic"]:
            cyrillic_by_name.setdefault(info["name"], []).append((path_id, info))

    result: dict[int, int] = {}
    for path_id, info in font_info.items():
        if info["has_cyrillic"]:
            continue

        target_name = info["name"]
        candidates = cyrillic_by_name.get(target_name, [])
        if not candidates and target_name in MANUAL_FONT_FALLBACKS:
            candidates = cyrillic_by_name.get(MANUAL_FONT_FALLBACKS[target_name], [])
        if not candidates:
            continue

        source_spacing = float(info.get("line_spacing") or 0.0)
        target_id, _ = min(
            candidates,
            key=lambda item: abs(float(item[1].get("line_spacing") or 0.0) - source_spacing),
        )
        result[path_id] = target_id

    return result, font_info


def patch_asset(asset: Asset, font_map: dict[int, int]) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for object_path_id, obj in asset.objects.items():
        try:
            data = obj.contents
        except Exception:
            continue

        for field_path, pointer in walk_pointers(data):
            if pointer.file_id != 0 or pointer.path_id not in font_map:
                continue

            old_path_id = pointer.path_id
            new_path_id = font_map[old_path_id]
            pointer.path_id = new_path_id
            changes.append(
                {
                    "object_path_id": object_path_id,
                    "object_type_id": obj.type_id,
                    "object_class_id": obj.class_id,
                    "field": field_path,
                    "old_font_path_id": old_path_id,
                    "new_font_path_id": new_path_id,
                }
            )

    return changes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_asset", type=Path)
    parser.add_argument("output_asset", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--ttf-font", type=Path, help="TTF to rasterize into bitmap fonts that lack Cyrillic glyphs.")
    parser.add_argument("--ttf-font-dir", type=Path, help="Directory with per-family TTF files, e.g. JEFFE.ttf.")
    parser.add_argument("--font-face", help="Windows font face name. Defaults to the family name read from the TTF.")
    parser.add_argument("--font-size-scale", type=float, default=1.0)
    parser.add_argument("--glyph-padding", type=int, default=2)
    parser.add_argument("--max-texture-size", type=int, default=4096)
    parser.add_argument("--preserve-ascii-glyphs", action="store_true", help="Only add Cyrillic and CP1251 aliases; leave existing ASCII glyphs unchanged.")
    parser.add_argument("--no-reference-redirect", action="store_true")
    args = parser.parse_args()

    with args.input_asset.open("rb") as handle:
        asset = Asset.from_file(handle)
        asset.load()
        ttf_reports: list[dict[str, Any]] = []
        if args.ttf_font or args.ttf_font_dir:
            ttf_reports = patch_fonts_with_ttf(
                asset,
                args.ttf_font,
                args.ttf_font_dir,
                args.font_face,
                args.font_size_scale,
                args.glyph_padding,
                args.max_texture_size,
                not args.preserve_ascii_glyphs,
            )

        font_map, font_info = build_font_map(asset)
        changes = [] if args.no_reference_redirect else patch_asset(asset, font_map)

        temp_path = args.output_asset.with_suffix(args.output_asset.suffix + ".tmp")
        args.output_asset.parent.mkdir(parents=True, exist_ok=True)
        with temp_path.open("wb") as out_handle:
            asset.save(out_handle)

    os.replace(temp_path, args.output_asset)

    report = {
        "input_asset": str(args.input_asset),
        "output_asset": str(args.output_asset),
        "ttf_font": str(args.ttf_font) if args.ttf_font else None,
        "ttf_font_dir": str(args.ttf_font_dir) if args.ttf_font_dir else None,
        "replace_ascii_glyphs": not args.preserve_ascii_glyphs,
        "ttf_patch": ttf_reports,
        "font_map": {
            str(old): {
                "old_name": font_info[old]["name"],
                "new_path_id": new,
                "new_name": font_info[new]["name"],
            }
            for old, new in sorted(font_map.items())
        },
        "change_count": len(changes),
        "changes": changes,
    }

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Font map entries: {len(font_map)}")
    if args.ttf_font or args.ttf_font_dir:
        patched = sum(1 for item in ttf_reports if "error" not in item and item.get("patched_codes"))
        failed = sum(1 for item in ttf_reports if "error" in item)
        families = sorted({item.get("font_family") for item in ttf_reports if item.get("font_family")})
        print(f"TTF font families considered: {len(families)}")
        print(f"TTF bitmap fonts patched: {patched}")
        print(f"TTF bitmap font patch failures: {failed}")
    print(f"Font references patched: {len(changes)}")
    for old, new in sorted(font_map.items()):
        print(f"  {old} {font_info[old]['name']} -> {new} {font_info[new]['name']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
