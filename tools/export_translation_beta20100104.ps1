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
$Python = if ($env:PYTHON -ne $null -and $env:PYTHON -ne "") { $env:PYTHON } else { "C:\msys64\mingw32\bin\python.exe" }
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
$BundleTempRoot = Join-Path (Join-Path $RepoRoot "work") ("bundle_export_" + [guid]::NewGuid().ToString("N"))

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

function Get-UnityAssetFiles {
    param([string]$ExtractDir)

    return @(Get-ChildItem -LiteralPath $ExtractDir -File |
        Where-Object {
            $_.Extension -ne ".dll" -and
            $_.Name -ne "mainData" -and
            $_.Name -ne "manifest.json"
        } |
        Sort-Object Name)
}

function Export-UnityAssetStrings {
    param(
        [string]$ExtractDir,
        [string]$ContainerName,
        [string[]]$MergeArgs
    )

    $AssetFiles = Get-UnityAssetFiles -ExtractDir $ExtractDir
    if ($AssetFiles.Count -eq 0) {
        Write-LogLine "No Unity asset files found in $ContainerName"
        return
    }

    $ExportArgs = @(
        $UnityTranslationTool,
        "export",
        $ExtractDir,
        $OutFileFull,
        "--container",
        $ContainerName,
        "--object-strings",
        "--allow-invalid-asset"
    ) + $MergeArgs

    foreach ($AssetFile in $AssetFiles) {
        $ExportArgs += @("--asset", $AssetFile.Name)
    }

    Invoke-LoggedStep "Export Unity asset strings from $ContainerName" $Python $ExportArgs
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
        Export-UnityAssetStrings -ExtractDir $TempRoot -ContainerName "main.unity3d" -MergeArgs $UnityMergeArgs
    }

    New-Item -ItemType Directory -Force -Path $BundleTempRoot | Out-Null
    $Containers = Get-ChildItem -LiteralPath $ClientDir -File |
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
            if ($NoTableData) {
                Write-LogLine "Skipping TableData.resourceFile because -NoTableData was set"
                continue
            }
        }
        elseif ($NoUnityAssets) {
            continue
        }

        $ContainerExtractDir = Join-Path $BundleTempRoot ([guid]::NewGuid().ToString("N"))
        New-Item -ItemType Directory -Force -Path $ContainerExtractDir | Out-Null
        Invoke-LoggedStep "Extract $($Container.Name) with ffbuildtool" $FfBuildToolExe @(
            "extract-bundle",
            "-i",
            $Container.FullName,
            "-o",
            $ContainerExtractDir
        )
        Export-UnityAssetStrings -ExtractDir $ContainerExtractDir -ContainerName $Container.Name -MergeArgs $UnityMergeArgs
    }

    Write-LogLine "Translation JSON written to $OutFileFull"
    Write-LogLine "Log written to $LogPath"
}
finally {
    if (Test-Path $TempRoot) {
        Remove-Item -LiteralPath $TempRoot -Recurse -Force
    }
    if (Test-Path $BundleTempRoot) {
        Remove-Item -LiteralPath $BundleTempRoot -Recurse -Force
    }
}
