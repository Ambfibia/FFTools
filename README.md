# FFTools

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

The Python path is currently hardcoded in the PowerShell scripts as:

```text
C:\msys64\mingw32\bin\python.exe
```

If Python is installed elsewhere, update `$Python` in:

- `tools\build_ru_beta20100104.ps1`
- `tools\export_translation_beta20100104.ps1`

TTF font patching uses Windows GDI through Python `ctypes`, so it does not require Pillow or fontTools.

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

## Export And Build Scripts

Legacy wrappers are still available:

```bat
10_export_ru_translation_beta20100104.bat
20_build_ru_beta20100104.bat -Force
```

`10_export_ru_translation_beta20100104.bat` exports by default:

- UI strings from DLL `ldstr` instructions only.
- Unity asset strings from `main.unity3d`.
- Object strings from `TableData.resourceFile`.

It does not enable full DLL string export unless `-AllDllStrings` is passed.

## Generated Files

Do not commit generated client data or local patch outputs:

- `builds\`
- `work\`
- `logs\`
- root-level `fonts\`
- `bin\`
- `obj\`

These are ignored by `.gitignore`.
