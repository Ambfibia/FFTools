# FFTools

[Русская версия README](README.ru.md)

FFTools is a Windows toolchain for creating and applying Russian localization patches for the FusionFall beta client.

The normal workflow is:

1. Select the original client folder, for example `beta-20100104`.
2. Generate a patch folder named `beta-20100104-ru-patch`.
3. Edit `translation.json` and optionally add replacement fonts.
4. Apply the patch and build `beta-20100104-ru`.

## Repository Setup

Clone with submodules:

```bat
git clone --recurse-submodules <repo-url> FFTools
cd FFTools
```

If the repo was cloned without submodules:

```bat
git submodule update --init --recursive
```

Required submodules:

- `UnityPackFF` from `https://github.com/dongresource/UnityPackFF`
- `ffbuildtool` from `https://github.com/OpenFusionProject/ffbuildtool`

## Requirements

Install these tools on Windows:

- Windows 10 or 11.
- .NET SDK 6.0 or newer. The included C# tools target `net6.0`; newer SDKs such as .NET 8/10 can build them.
- Rust stable toolchain with `cargo`, from `https://rustup.rs`.
- MSYS2 with MinGW 32-bit Python at `C:\msys64\mingw32\bin\python.exe`.
- Git for Windows.

The PowerShell scripts use this Python by default:

```text
C:\msys64\mingw32\bin\python.exe
```

If Python is installed elsewhere, set the `PYTHON` environment variable before running the scripts.
For texture PNG export/patching, set `TEXTURE_PYTHON` to a Python that has Pillow installed.

TTF font patching uses Windows GDI through Python `ctypes`, so it does not require Pillow or fontTools.
Texture PNG export/patching does require Pillow for the selected Python.

## Build Tools

Run these once after cloning:

```bat
dotnet build tools\FfPatchTool\FfPatchTool.csproj -c Release
dotnet build tools\FfStringPatcher\FfStringPatcher.csproj -c Release
cargo build --manifest-path ffbuildtool\Cargo.toml
```

`30_ff_patch_tool.bat` will build `FfPatchTool` automatically if it is missing, but building everything once makes failures easier to diagnose.

## Folder Layout

Recommended local layout:

```text
FFTools\
  builds\
    beta-20100104\
    beta-20100104-ru-patch\
    beta-20100104-ru\
```

`builds`, `work`, `logs`, and root-level `fonts` are ignored by git.

The source client folder must contain `main.unity3d`. `TableData.resourceFile` is used when TableData export/patching is enabled.

## GUI Workflow

Create a patch folder:

```bat
31_create_patch_dir_gui.bat
```

This opens a folder picker. Select the source client folder, for example:

```text
builds\beta-20100104
```

The tool creates:

```text
builds\beta-20100104-ru-patch
```

The patch folder contains:

- `ffpatch.json`
- `translation.json`
- optional `font.ttf`
- optional `fonts\*.ttf`

Apply the patch:

```bat
32_apply_patch_gui.bat
```

Select the same source client folder. The tool looks for:

```text
builds\beta-20100104-ru-patch
```

The output build is:

```text
builds\beta-20100104-ru
```

## Font Replacement

There are two font modes.

When replacement TTFs are configured, the patcher rasterizes the primary printable ASCII range
(letters, digits, punctuation) and Russian glyphs from the replacement font into matching Unity
bitmap font atlases. It also adds CP1251 byte-code aliases for Russian input fields used by the
old Unity GUI. Other existing glyphs are preserved.

A single fallback TTF can be stored as:

```text
beta-20100104-ru-patch\font.ttf
```

Per-family fonts can be stored as:

```text
beta-20100104-ru-patch\fonts\JEFFE.ttf
beta-20100104-ru-patch\fonts\ChaletBook-Regular.ttf
```

Font file names are matched by normalized family name:

- `JEFFE.ttf` is used for `JEFFE___14`, `JEFFE___20`, `JEFFE___40`, `JEFFE___72`, and similar size variants.
- `ChaletBook-Regular.ttf` is used for `ChaletBook-Regular`, `ChaletBook-Regular Small`, and `ChaletBook-Regular Small 1`.

If a per-family TTF is missing, the tool falls back to `font.ttf` when present.

## Texture Replacement

Some UI art has baked-in English text. Export candidate Texture2D images to PNG:

```bat
35_export_texture_pngs_gui.bat
```

The GUI asks for the source build folder, patch folder, and an optional texture name regex.
It uses `TEXTURE_PYTHON` when set, otherwise it tries `work\texture_venv_win\Scripts\python.exe` before asking you to select `python.exe`.
The CLI wrapper is also available:

```bat
35_export_texture_pngs.bat -ClientDir builds\beta-20100104 -NameRegex "help|title|button"
```

By default this scans all `.unity3d` and `.resourceFile` containers in the selected client folder and writes to:

```text
builds\beta-20100104-ru-patch\textures
```

PNG files are grouped by source container and asset file, for example:

```text
textures\main.unity3d\sharedassets0.assets\73__HelpTitle.png
textures\Tutorial.resourceFile\CustomAssetBundle-...\123__SomeTexture.png
```

Edit the exported PNG files in place. During `30_ff_patch_tool.bat build`, the build script automatically applies edited
PNGs when `textures\manifest.json` exists in the patch folder. Unchanged PNGs are skipped by hash.

The lower-level tool is also available:

```bat
C:\msys64\mingw32\bin\python.exe tools\ff_texture_patch.py export work\extracted-main builds\beta-20100104-ru-patch\textures
C:\msys64\mingw32\bin\python.exe tools\ff_texture_patch.py apply  work\extracted-main builds\beta-20100104-ru-patch\textures
```

## CLI Workflow

Create or update a patch folder:

```bat
30_ff_patch_tool.bat init --source builds\beta-20100104
```

Apply a patch:

```bat
30_ff_patch_tool.bat build --source builds\beta-20100104 --force
```

One-step create-and-build:

```bat
30_ff_patch_tool.bat make-ru --source builds\beta-20100104 --force
```

Defaults:

- source: `beta-20100104`
- patch folder: `beta-20100104-ru-patch`
- output folder: `beta-20100104-ru`

Useful options:

```bat
30_ff_patch_tool.bat init --source builds\beta-20100104 --font-ttf C:\Windows\Fonts\arial.ttf
30_ff_patch_tool.bat build --source builds\beta-20100104 --patch-dir builds\beta-20100104-ru-patch --output builds\beta-20100104-ru --force
30_ff_patch_tool.bat build --source builds\beta-20100104 --no-unity-assets --no-table-data --force
```

## Translator JSON

To give a translator a compact file with only the original text and translation fields:

```bat
33_export_translator_json.bat
```

This reads `builds\retro-010920-ru-patch\translation.json` and writes:

```text
builds\retro-010920-ru-patch\translation.translator.json
```

After editing `translation.translator.json`, merge the translations back into the full patch JSON:

```bat
34_import_translator_json.bat
```

Both wrappers also accept explicit paths:

```bat
33_export_translator_json.bat builds\my-patch\translation.json builds\my-patch\translation.translator.json
34_import_translator_json.bat builds\my-patch\translation.json builds\my-patch\translation.translator.json
```

The compact file intentionally contains only `source` and `translation`.
Keep the `entries` order unchanged; the import step validates each `source` row before writing translations back.
