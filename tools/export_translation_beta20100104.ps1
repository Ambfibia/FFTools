param(
    [string]$ClientDir = "",
    [string]$OutFile = "",
    [string]$MergeJson = "",
    [switch]$AllAssemblies,
    [switch]$AllDllStrings,
    [switch]$IncludeUnityAssets,
    [switch]$IncludeTableData,
    [switch]$NoUnityAssets,
    [switch]$NoTableData,
    [switch]$NoExistingMerge,
    [switch]$NoBackup
)

$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
if ($ClientDir -eq "") {
    $ClientDir = Join-Path $RepoRoot "beta-20100104"
}
if ($OutFile -eq "") {
    $OutFile = Join-Path $RepoRoot "patches\ru_translation_beta20100104.json"
}
if ($MergeJson -eq "") {
    $MergeJson = Join-Path $RepoRoot "patches\ru_strings_beta20100104.json"
}

$ClientDir = Resolve-Path $ClientDir
$OutFileFull = [System.IO.Path]::GetFullPath($OutFile)
$MergeJsonFull = [System.IO.Path]::GetFullPath($MergeJson)
$Python = "C:\msys64\mingw32\bin\python.exe"
$FfBuildToolProject = Join-Path $RepoRoot "ffbuildtool\Cargo.toml"
$FfBuildToolSource = Join-Path $RepoRoot "ffbuildtool\src\bundle.rs"
$FfBuildToolExe = Join-Path $RepoRoot "ffbuildtool\target\debug\ffbuildtool.exe"
$PatcherProject = Join-Path $RepoRoot "tools\FfStringPatcher\FfStringPatcher.csproj"
$PatcherSource = Join-Path $RepoRoot "tools\FfStringPatcher\Program.cs"
$PatcherDll = Join-Path $RepoRoot "tools\FfStringPatcher\bin\Release\net6.0\FfStringPatcher.dll"
$UnityTranslationTool = Join-Path $RepoRoot "tools\ff_text_asset_translations.py"
$LogDir = Join-Path $RepoRoot "logs\translation_export"
$LogPath = Join-Path $LogDir ("export_beta20100104_" + (Get-Date -Format "yyyyMMdd_HHmmss") + ".log")
$TempRoot = Join-Path (Join-Path $RepoRoot "work") ("main_export_" + [guid]::NewGuid().ToString("N"))
$TableTempRoot = Join-Path (Join-Path $RepoRoot "work") ("tabledata_export_" + [guid]::NewGuid().ToString("N"))

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

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

Set-Content -Path $LogPath -Value ("Translation export started " + (Get-Date -Format "s")) -Encoding UTF8
try {
    Write-LogLine "ClientDir: $ClientDir"
    Write-LogLine "OutFile:   $OutFileFull"
    Write-LogLine "MergeJson: $MergeJsonFull"

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
    if (-not (Test-Path $Python)) {
        throw "Python runtime not found: $Python"
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

    New-Item -ItemType Directory -Force -Path $TempRoot | Out-Null
    Invoke-LoggedStep "Extract main.unity3d with ffbuildtool" $FfBuildToolExe @(
        "extract-bundle",
        "-i",
        (Join-Path $ClientDir "main.unity3d"),
        "-o",
        $TempRoot
    )

    $ExportArgs = @($PatcherDll, "export", $TempRoot, $OutFileFull)
    if ($AllAssemblies) {
        $ExportArgs += "--all-assemblies"
    }
    else {
        $ExportArgs += @(
            "--assembly",
            "Assembly - CSharp.dll",
            "Assembly - CSharp - first pass.dll",
            "Assembly - UnityScript - first pass.dll"
        )
    }
    if (-not $AllDllStrings) {
        $ExportArgs += "--ui-only"
    }

    $ExistingTranslationBackup = ""
    if (-not $NoExistingMerge -and (Test-Path $OutFileFull)) {
        if (-not $NoBackup) {
            $ExistingTranslationBackup = $OutFileFull + ".bak"
            Copy-Item -LiteralPath $OutFileFull -Destination $ExistingTranslationBackup -Force
        }
        $ExportArgs += @("--merge", $OutFileFull)
    }
    if (Test-Path $MergeJsonFull) {
        $ExportArgs += @("--merge", $MergeJsonFull)
    }

    Invoke-LoggedStep "Export translation JSON" "dotnet" $ExportArgs

    $UnityMergeArgs = @()
    if ($ExistingTranslationBackup -ne "" -and (Test-Path $ExistingTranslationBackup)) {
        $UnityMergeArgs += @("--merge", $ExistingTranslationBackup)
    }
    if (Test-Path $MergeJsonFull) {
        $UnityMergeArgs += @("--merge", $MergeJsonFull)
    }

    if (-not $NoUnityAssets) {
        $MainUnityExportArgs = @(
            $UnityTranslationTool,
            "export",
            $TempRoot,
            $OutFileFull,
            "--asset",
            "sharedassets0.assets",
            "--container",
            "main.unity3d"
        ) + $UnityMergeArgs
        Invoke-LoggedStep "Export main Unity asset strings" $Python $MainUnityExportArgs
    }

    if (-not $NoTableData) {
        New-Item -ItemType Directory -Force -Path $TableTempRoot | Out-Null
        Invoke-LoggedStep "Extract TableData.resourceFile with ffbuildtool" $FfBuildToolExe @(
            "extract-bundle",
            "-i",
            (Join-Path $ClientDir "TableData.resourceFile"),
            "-o",
            $TableTempRoot
        )
        $TableAssetFile = Get-ChildItem -LiteralPath $TableTempRoot -File |
            Where-Object { -not $_.Name.StartsWith(".") } |
            Select-Object -First 1
        if ($null -eq $TableAssetFile) {
            throw "TableData.resourceFile extraction produced no asset file."
        }
        $TableDataExportArgs = @(
            $UnityTranslationTool,
            "export",
            $TableTempRoot,
            $OutFileFull,
            "--asset",
            $TableAssetFile.Name,
            "--container",
            "TableData.resourceFile",
            "--object-strings"
        ) + $UnityMergeArgs
        Invoke-LoggedStep "Export TableData strings" $Python $TableDataExportArgs
    }

    Write-LogLine "Translation JSON written to $OutFileFull"
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
