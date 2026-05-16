param(
    [string]$ClientDir = "",
    [string]$OutDir = "",
    [string]$PatchJson = "",
    [string]$AssetUrl = "http://127.0.0.1:8000",
    [string]$FontTtf = "",
    [string]$FontDir = "",
    [string]$FontFace = "",
    [switch]$PatchUnityAssets,
    [switch]$PatchTableData,
    [switch]$NoFontPatch,
    [switch]$NoFontReferenceRedirect,
    [switch]$AllowTextureResize,
    [switch]$SkipManifest,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
if ($ClientDir -eq "") {
    $ClientDir = Join-Path $RepoRoot "beta-20100104"
}
if ($OutDir -eq "") {
    $OutDir = Join-Path $RepoRoot "work\beta-20100104-ru-ffbuildtool"
}
if ($PatchJson -eq "") {
    $TranslationJson = Join-Path $RepoRoot "patches\ru_translation_beta20100104.json"
    if (Test-Path $TranslationJson) {
        $PatchJson = $TranslationJson
    }
    else {
        $PatchJson = Join-Path $RepoRoot "patches\ru_strings_beta20100104.json"
    }
}

$ClientDir = Resolve-Path $ClientDir
$PatchJson = Resolve-Path $PatchJson
if ($FontTtf -ne "") {
    $FontTtf = Resolve-Path $FontTtf
}
if ($FontDir -eq "") {
    $DefaultFontDir = Join-Path ([System.IO.Path]::GetDirectoryName($PatchJson)) "fonts"
    if (Test-Path $DefaultFontDir) {
        $FontDir = $DefaultFontDir
    }
    else {
        $RepoFontDir = Join-Path $RepoRoot "fonts"
        if (Test-Path $RepoFontDir) {
            $FontDir = $RepoFontDir
        }
    }
}
if ($FontDir -ne "") {
    $FontDir = Resolve-Path $FontDir
}
$PatchDir = [System.IO.Path]::GetDirectoryName($PatchJson)
$TexturePatchDir = Join-Path $PatchDir "textures"
$OutDirFull = [System.IO.Path]::GetFullPath($OutDir)
$Python = if ($env:PYTHON -ne $null -and $env:PYTHON -ne "") { $env:PYTHON } else { "C:\msys64\mingw32\bin\python.exe" }
$FfBuildToolProject = Join-Path $RepoRoot "ffbuildtool\Cargo.toml"
$FfBuildToolSource = Join-Path $RepoRoot "ffbuildtool\src\bundle.rs"
$FfBuildToolExe = Join-Path $RepoRoot "ffbuildtool\target\debug\ffbuildtool.exe"
$PatcherProject = Join-Path $RepoRoot "tools\FfStringPatcher\FfStringPatcher.csproj"
$PatcherSource = Join-Path $RepoRoot "tools\FfStringPatcher\Program.cs"
$PatcherDll = Join-Path $RepoRoot "tools\FfStringPatcher\bin\Release\net6.0\FfStringPatcher.dll"
$FontPatchTool = Join-Path $RepoRoot "tools\ff_patch_font_refs.py"
$UnityTranslationTool = Join-Path $RepoRoot "tools\ff_text_asset_translations.py"
$TexturePatchTool = Join-Path $RepoRoot "tools\ff_texture_patch.py"
$LogDir = Join-Path $RepoRoot "logs\ru_patch"
$LogPath = Join-Path $LogDir ("build_beta20100104_" + (Get-Date -Format "yyyyMMdd_HHmmss") + ".log")

if (-not (Test-Path $Python)) {
    throw "Python runtime not found: $Python"
}

function Test-PythonHasPillow {
    param([string]$PythonPath)

    if ($PythonPath -eq "" -or -not (Test-Path -LiteralPath $PythonPath)) {
        return $false
    }

    & $PythonPath -c "import PIL" 2>$null
    return $LASTEXITCODE -eq 0
}

function Resolve-TexturePython {
    $candidates = @()
    if ($env:TEXTURE_PYTHON -ne $null -and $env:TEXTURE_PYTHON -ne "") {
        $candidates += $env:TEXTURE_PYTHON
    }
    $candidates += (Join-Path $RepoRoot "work\texture_venv_win\Scripts\python.exe")
    if ($env:PYTHON -ne $null -and $env:PYTHON -ne "") {
        $candidates += $env:PYTHON
    }
    $candidates += $Python

    foreach ($candidate in $candidates) {
        if (Test-PythonHasPillow -PythonPath $candidate) {
            return [System.IO.Path]::GetFullPath($candidate)
        }
    }

    throw "No Python with Pillow was found for texture PNG patching. Set TEXTURE_PYTHON to python.exe with Pillow installed."
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$TempRoot = Join-Path (Join-Path $RepoRoot "work") ("main_build_" + [guid]::NewGuid().ToString("N"))
$TableTempRoot = Join-Path (Join-Path $RepoRoot "work") ("tabledata_build_" + [guid]::NewGuid().ToString("N"))
$BundleTempRoot = Join-Path (Join-Path $RepoRoot "work") ("bundle_build_" + [guid]::NewGuid().ToString("N"))
$TextureTempRoot = Join-Path (Join-Path $RepoRoot "work") ("texture_build_" + [guid]::NewGuid().ToString("N"))

function Write-LogLine {
    param([string]$Message)
    Write-Host $Message
    Add-Content -Path $LogPath -Value $Message -Encoding UTF8
}

function Invoke-LoggedStep {
    param(
        [string]$Name,
        [string]$File,
        [string[]]$Arguments
    )

    Write-LogLine "== $Name =="
    $PreviousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $File @Arguments 2>&1 | ForEach-Object {
            $line = $_.ToString()
            Write-Host $line
            Add-Content -Path $LogPath -Value $line -Encoding UTF8
        }
        $ExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $PreviousErrorActionPreference
    }
    if ($ExitCode -ne 0) {
        throw "$Name failed with exit code $ExitCode"
    }
}

Set-Content -Path $LogPath -Value ("RU patch build started " + (Get-Date -Format "s")) -Encoding UTF8
try {
    Write-LogLine "ClientDir: $ClientDir"
    Write-LogLine "OutDir:    $OutDirFull"
    Write-LogLine "PatchJson: $PatchJson"
    if ($FontTtf -ne "") {
        Write-LogLine "FontTtf:   $FontTtf"
    }
    if ($FontDir -ne "") {
        Write-LogLine "FontDir:   $FontDir"
    }
    if ($FontFace -ne "") {
        Write-LogLine "FontFace:  $FontFace"
    }
    if ($AllowTextureResize) {
        Write-LogLine "Texture resize: enabled"
    }
    Write-LogLine "AssetUrl:  $AssetUrl"

    $NeedsFfBuildToolBuild = -not (Test-Path $FfBuildToolExe)
    if (-not $NeedsFfBuildToolBuild -and (Test-Path $FfBuildToolSource)) {
        $NeedsFfBuildToolBuild = (Get-Item $FfBuildToolSource).LastWriteTimeUtc -gt (Get-Item $FfBuildToolExe).LastWriteTimeUtc
    }
    if ($NeedsFfBuildToolBuild) {
        Invoke-LoggedStep "Build ffbuildtool" "cargo" @("build", "--manifest-path", $FfBuildToolProject)
    }
    if (-not (Test-Path $FfBuildToolExe)) {
        throw "ffbuildtool executable was not found: $FfBuildToolExe"
    }

    $NeedsPatcherBuild = -not (Test-Path $PatcherDll)
    if (-not $NeedsPatcherBuild -and (Test-Path $PatcherProject)) {
        $NeedsPatcherBuild = (Get-Item $PatcherProject).LastWriteTimeUtc -gt (Get-Item $PatcherDll).LastWriteTimeUtc
    }
    if (-not $NeedsPatcherBuild -and (Test-Path $PatcherSource)) {
        $NeedsPatcherBuild = (Get-Item $PatcherSource).LastWriteTimeUtc -gt (Get-Item $PatcherDll).LastWriteTimeUtc
    }
    if ($NeedsPatcherBuild) {
        Invoke-LoggedStep "Build string patcher" "dotnet" @("build", $PatcherProject, "-c", "Release")
    }
    if (-not (Test-Path $PatcherDll)) {
        throw "String patcher build output was not found: $PatcherDll"
    }

    if (Test-Path $OutDirFull) {
        if (-not $Force) {
            throw "Output directory already exists: $OutDirFull. Re-run with -Force to replace it."
        }
        Remove-Item -LiteralPath $OutDirFull -Recurse -Force
    }

    New-Item -ItemType Directory -Force -Path $TempRoot | Out-Null
    Copy-Item -Path $ClientDir -Destination $OutDirFull -Recurse

    Invoke-LoggedStep "Extract main.unity3d with ffbuildtool" $FfBuildToolExe @("extract-bundle", "-i", (Join-Path $OutDirFull "main.unity3d"), "-o", $TempRoot)

    Invoke-LoggedStep "Patch managed strings" "dotnet" @($PatcherDll, "apply", $TempRoot, $PatchJson)

    if ($PatchUnityAssets) {
        Invoke-LoggedStep "Patch main Unity asset strings" $Python @(
            $UnityTranslationTool,
            "apply",
            $TempRoot,
            $PatchJson,
            "--container",
            "main.unity3d",
            "--allow-missing"
        )
    }

    if (-not $NoFontPatch) {
        $FontPatchReport = Join-Path $OutDirFull "font_patch_report.json"
        $FontPatchArgs = @(
            $FontPatchTool,
            (Join-Path $TempRoot "sharedassets0.assets"),
            (Join-Path $TempRoot "sharedassets0.assets"),
            "--report",
            $FontPatchReport
        )
        if ($FontTtf -ne "") {
            $FontPatchArgs += @("--ttf-font", $FontTtf)
        }
        if ($FontDir -ne "") {
            $FontPatchArgs += @("--ttf-font-dir", $FontDir)
        }
        if ($FontFace -ne "") {
            $FontPatchArgs += @("--font-face", $FontFace)
        }
        if ($NoFontReferenceRedirect) {
            $FontPatchArgs += "--no-reference-redirect"
        }
        Invoke-LoggedStep "Patch GUI fonts" $Python $FontPatchArgs
    }

    $TextureManifest = Join-Path $TexturePatchDir "manifest.json"
    if (Test-Path $TextureManifest) {
        $TexturePython = Resolve-TexturePython
        Write-LogLine "TexturePython: $TexturePython"
        $TexturePatchManifest = Get-Content -LiteralPath $TextureManifest -Raw | ConvertFrom-Json
        $MainTextureAssets = @($TexturePatchManifest.entries |
            Where-Object { $_.container -eq "main.unity3d" } |
            Select-Object -ExpandProperty asset -Unique)
        foreach ($TextureAsset in $MainTextureAssets) {
            $TextureArgs = @(
                $TexturePatchTool,
                "apply",
                $TempRoot,
                $TexturePatchDir,
                "--asset",
                $TextureAsset,
                "--container",
                "main.unity3d"
            )
            if ($AllowTextureResize) {
                $TextureArgs += "--allow-resize"
            }
            Invoke-LoggedStep "Patch texture PNGs in main.unity3d\$TextureAsset" $TexturePython $TextureArgs
        }
    }

    Invoke-LoggedStep "Pack main.unity3d with ffbuildtool" $FfBuildToolExe @("pack-bundle", "-i", $TempRoot, "-o", (Join-Path $OutDirFull "main.unity3d"), "-l", "4")

    Invoke-LoggedStep "Validate UnityWeb contents" $FfBuildToolExe @("read-bundle", "-i", (Join-Path $OutDirFull "main.unity3d"))

    if ($PatchUnityAssets -or $PatchTableData) {
        New-Item -ItemType Directory -Force -Path $BundleTempRoot | Out-Null
        $Containers = Get-ChildItem -LiteralPath $OutDirFull -File |
            Where-Object {
                ($_.Name.EndsWith(".unity3d", [System.StringComparison]::OrdinalIgnoreCase) -or
                 $_.Name.EndsWith(".resourceFile", [System.StringComparison]::OrdinalIgnoreCase)) -and
                ($_.Name -notlike "*.bak*") -and
                (-not [string]::Equals($_.Name, "main.unity3d", [System.StringComparison]::OrdinalIgnoreCase))
            } |
            Sort-Object Name

        foreach ($Container in $Containers) {
            $IsTableData = [string]::Equals($Container.Name, "TableData.resourceFile", [System.StringComparison]::OrdinalIgnoreCase)
            if ($IsTableData) {
                if (-not $PatchTableData) {
                    continue
                }
            }
            elseif (-not $PatchUnityAssets) {
                continue
            }

            $ContainerTempRoot = Join-Path $BundleTempRoot ([guid]::NewGuid().ToString("N"))
            New-Item -ItemType Directory -Force -Path $ContainerTempRoot | Out-Null
            Invoke-LoggedStep "Extract $($Container.Name) with ffbuildtool" $FfBuildToolExe @(
                "extract-bundle",
                "-i",
                $Container.FullName,
                "-o",
                $ContainerTempRoot
            )
            $StringStatusPath = Join-Path $BundleTempRoot ("string_status_" + [guid]::NewGuid().ToString("N") + ".json")
            Invoke-LoggedStep "Patch Unity asset strings in $($Container.Name)" $Python @(
                $UnityTranslationTool,
                "apply",
                $ContainerTempRoot,
                $PatchJson,
                "--container",
                $Container.Name,
                "--allow-missing",
                "--status-file",
                $StringStatusPath
            )
            $StringsPatched = $true
            if (Test-Path -LiteralPath $StringStatusPath) {
                $StringStatus = Get-Content -LiteralPath $StringStatusPath -Raw | ConvertFrom-Json
                $StringsPatched = $StringStatus.applied -gt 0
            }

            if ($StringsPatched) {
                Invoke-LoggedStep "Pack $($Container.Name) after string patching" $FfBuildToolExe @(
                    "pack-bundle",
                    "-i",
                    $ContainerTempRoot,
                    "-o",
                    $Container.FullName,
                    "-l",
                    "4"
                )
                Invoke-LoggedStep "Validate $($Container.Name) after string patching" $FfBuildToolExe @("read-bundle", "-i", $Container.FullName)
            }
            else {
                Write-LogLine "String patch skipped unchanged container: $($Container.Name)"
            }
        }
    }

    if (Test-Path $TextureManifest) {
        if ($null -eq $TexturePatchManifest) {
            $TexturePatchManifest = Get-Content -LiteralPath $TextureManifest -Raw | ConvertFrom-Json
        }
        $OtherTextureContainers = @($TexturePatchManifest.entries |
            Where-Object { $_.container -ne "main.unity3d" } |
            Select-Object -ExpandProperty container -Unique)

        foreach ($TextureContainer in $OtherTextureContainers) {
            $ContainerPath = Join-Path $OutDirFull $TextureContainer
            if (-not (Test-Path -LiteralPath $ContainerPath)) {
                Write-LogLine "Texture patch skipped missing container: $ContainerPath"
                continue
            }

            $ContainerTempRoot = Join-Path $TextureTempRoot ([guid]::NewGuid().ToString("N"))
            New-Item -ItemType Directory -Force -Path $ContainerTempRoot | Out-Null
            Invoke-LoggedStep "Extract $TextureContainer for texture patching" $FfBuildToolExe @(
                "extract-bundle",
                "-i",
                $ContainerPath,
                "-o",
                $ContainerTempRoot
            )

            $TextureAssets = @($TexturePatchManifest.entries |
                Where-Object { $_.container -eq $TextureContainer } |
                Select-Object -ExpandProperty asset -Unique)
            $ContainerPatched = $false
            foreach ($TextureAsset in $TextureAssets) {
                $TextureStatusPath = Join-Path $TextureTempRoot ("texture_status_" + [guid]::NewGuid().ToString("N") + ".json")
                $TextureArgs = @(
                    $TexturePatchTool,
                    "apply",
                    $ContainerTempRoot,
                    $TexturePatchDir,
                    "--asset",
                    $TextureAsset,
                    "--container",
                    $TextureContainer,
                    "--status-file",
                    $TextureStatusPath
                )
                if ($AllowTextureResize) {
                    $TextureArgs += "--allow-resize"
                }
                Invoke-LoggedStep "Patch texture PNGs in $TextureContainer\$TextureAsset" $TexturePython $TextureArgs
                if (Test-Path -LiteralPath $TextureStatusPath) {
                    $TextureStatus = Get-Content -LiteralPath $TextureStatusPath -Raw | ConvertFrom-Json
                    if ($TextureStatus.patched -gt 0) {
                        $ContainerPatched = $true
                    }
                }
            }

            if ($ContainerPatched) {
                Invoke-LoggedStep "Pack $TextureContainer after texture patching" $FfBuildToolExe @(
                    "pack-bundle",
                    "-i",
                    $ContainerTempRoot,
                    "-o",
                    $ContainerPath,
                    "-l",
                    "4"
                )
                Invoke-LoggedStep "Validate $TextureContainer after texture patching" $FfBuildToolExe @("read-bundle", "-i", $ContainerPath)
            }
            else {
                Write-LogLine "Texture patch skipped unchanged container: $TextureContainer"
            }
        }
    }

    if (-not $SkipManifest) {
        $BuildName = Split-Path $OutDirFull -Leaf
        $ManifestPath = Join-Path $OutDirFull "manifest_ru.json"
        Invoke-LoggedStep "Generate RU manifest" $FfBuildToolExe @(
            "gen-manifest",
            "-b", $OutDirFull,
            "-u", $AssetUrl,
            "-n", $BuildName,
            "-d", "RU patched beta-20100104 packed with ffbuildtool",
            "-o", $ManifestPath
        )
        Invoke-LoggedStep "Validate RU manifest" $FfBuildToolExe @(
            "validate-build",
            "-m", $ManifestPath,
            "-p", $OutDirFull
        )
    }

    Write-LogLine "RU client written to $OutDirFull"
    Write-LogLine "Log written to $LogPath"
}
finally {
    if (Test-Path $TempRoot) {
        Remove-Item -LiteralPath $TempRoot -Recurse -Force
    }
    if (Test-Path $TableTempRoot) {
        Remove-Item -LiteralPath $TableTempRoot -Recurse -Force
    }
    if (Test-Path $BundleTempRoot) {
        Remove-Item -LiteralPath $BundleTempRoot -Recurse -Force
    }
    if (Test-Path $TextureTempRoot) {
        Remove-Item -LiteralPath $TextureTempRoot -Recurse -Force
    }
}
