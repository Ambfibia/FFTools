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
}
if ($FontDir -ne "") {
    $FontDir = Resolve-Path $FontDir
}
$OutDirFull = [System.IO.Path]::GetFullPath($OutDir)
$Python = "C:\msys64\mingw32\bin\python.exe"
$FfBuildToolProject = Join-Path $RepoRoot "ffbuildtool\Cargo.toml"
$FfBuildToolSource = Join-Path $RepoRoot "ffbuildtool\src\bundle.rs"
$FfBuildToolExe = Join-Path $RepoRoot "ffbuildtool\target\debug\ffbuildtool.exe"
$PatcherProject = Join-Path $RepoRoot "tools\FfStringPatcher\FfStringPatcher.csproj"
$PatcherSource = Join-Path $RepoRoot "tools\FfStringPatcher\Program.cs"
$PatcherDll = Join-Path $RepoRoot "tools\FfStringPatcher\bin\Release\net6.0\FfStringPatcher.dll"
$FontPatchTool = Join-Path $RepoRoot "tools\ff_patch_font_refs.py"
$UnityTranslationTool = Join-Path $RepoRoot "tools\ff_text_asset_translations.py"
$LogDir = Join-Path $RepoRoot "logs\ru_patch"
$LogPath = Join-Path $LogDir ("build_beta20100104_" + (Get-Date -Format "yyyyMMdd_HHmmss") + ".log")

if (-not (Test-Path $Python)) {
    throw "Python runtime not found: $Python"
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$TempRoot = Join-Path (Join-Path $RepoRoot "work") ("main_build_" + [guid]::NewGuid().ToString("N"))
$TableTempRoot = Join-Path (Join-Path $RepoRoot "work") ("tabledata_build_" + [guid]::NewGuid().ToString("N"))

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

    Invoke-LoggedStep "Pack main.unity3d with ffbuildtool" $FfBuildToolExe @("pack-bundle", "-i", $TempRoot, "-o", (Join-Path $OutDirFull "main.unity3d"), "-l", "4")

    Invoke-LoggedStep "Validate UnityWeb contents" $FfBuildToolExe @("read-bundle", "-i", (Join-Path $OutDirFull "main.unity3d"))

    $TableDataPath = Join-Path $OutDirFull "TableData.resourceFile"
    if ($PatchTableData -and (Test-Path $TableDataPath)) {
        New-Item -ItemType Directory -Force -Path $TableTempRoot | Out-Null
        Invoke-LoggedStep "Extract TableData.resourceFile with ffbuildtool" $FfBuildToolExe @(
            "extract-bundle",
            "-i",
            $TableDataPath,
            "-o",
            $TableTempRoot
        )
        Invoke-LoggedStep "Patch TableData strings" $Python @(
            $UnityTranslationTool,
            "apply",
            $TableTempRoot,
            $PatchJson,
            "--allow-missing"
        )
        Invoke-LoggedStep "Pack TableData.resourceFile with ffbuildtool" $FfBuildToolExe @(
            "pack-bundle",
            "-i",
            $TableTempRoot,
            "-o",
            $TableDataPath,
            "-l",
            "4"
        )
        Invoke-LoggedStep "Validate TableData.resourceFile" $FfBuildToolExe @("read-bundle", "-i", $TableDataPath)
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
}
