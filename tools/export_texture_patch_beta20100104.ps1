param(
    [string]$ClientDir = "",
    [string]$OutDir = "",
    [string]$TexturePython = "",
    [string]$NameRegex = "",
    [int]$MinWidth = 0,
    [int]$MinHeight = 0
)

$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
if ($ClientDir -eq "") {
    $ClientDir = Join-Path $RepoRoot "beta-20100104"
}
if ($OutDir -eq "") {
    $PatchDir = Join-Path ([System.IO.DirectoryInfo](Resolve-Path $ClientDir)).Parent.FullName ((Split-Path $ClientDir -Leaf) + "-ru-patch")
    $OutDir = Join-Path $PatchDir "textures"
}

$ClientDir = Resolve-Path $ClientDir
$OutDirFull = [System.IO.Path]::GetFullPath($OutDir)
$FfBuildToolProject = Join-Path $RepoRoot "ffbuildtool\Cargo.toml"
$FfBuildToolSource = Join-Path $RepoRoot "ffbuildtool\src\bundle.rs"
$FfBuildToolExe = Join-Path $RepoRoot "ffbuildtool\target\debug\ffbuildtool.exe"
$TexturePatchTool = Join-Path $RepoRoot "tools\ff_texture_patch.py"
$TempRoot = Join-Path (Join-Path $RepoRoot "work") ("texture_export_" + [guid]::NewGuid().ToString("N"))

function Test-PythonHasPillow {
    param([string]$PythonPath)

    if ($PythonPath -eq "" -or -not (Test-Path -LiteralPath $PythonPath)) {
        return $false
    }

    & $PythonPath -c "import PIL" 2>$null
    return $LASTEXITCODE -eq 0
}

function Resolve-TexturePython {
    param([string]$ExplicitPython)

    $candidates = @()
    if ($ExplicitPython -ne "") {
        $candidates += $ExplicitPython
    }
    if ($env:TEXTURE_PYTHON -ne $null -and $env:TEXTURE_PYTHON -ne "") {
        $candidates += $env:TEXTURE_PYTHON
    }
    $candidates += (Join-Path $RepoRoot "work\texture_venv_win\Scripts\python.exe")
    if ($env:PYTHON -ne $null -and $env:PYTHON -ne "") {
        $candidates += $env:PYTHON
    }
    $candidates += "C:\msys64\mingw32\bin\python.exe"

    foreach ($candidate in $candidates) {
        if (Test-PythonHasPillow -PythonPath $candidate) {
            return [System.IO.Path]::GetFullPath($candidate)
        }
    }

    throw "No Python with Pillow was found for texture PNG export. Set TEXTURE_PYTHON to python.exe with Pillow installed."
}

$Python = Resolve-TexturePython -ExplicitPython $TexturePython

function Invoke-Step {
    param(
        [string]$Name,
        [string]$File,
        [string[]]$Arguments
    )

    Write-Host "== $Name =="
    & $File @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Name failed with exit code $LASTEXITCODE"
    }
}

try {
    $NeedsFfBuildToolBuild = -not (Test-Path $FfBuildToolExe)
    if (-not $NeedsFfBuildToolBuild -and (Test-Path $FfBuildToolSource)) {
        $NeedsFfBuildToolBuild = (Get-Item $FfBuildToolSource).LastWriteTimeUtc -gt (Get-Item $FfBuildToolExe).LastWriteTimeUtc
    }
    if ($NeedsFfBuildToolBuild) {
        Invoke-Step "Build ffbuildtool" "cargo" @("build", "--manifest-path", $FfBuildToolProject)
    }
    if (-not (Test-Path $FfBuildToolExe)) {
        throw "ffbuildtool executable was not found: $FfBuildToolExe"
    }

    New-Item -ItemType Directory -Force -Path $TempRoot | Out-Null
    New-Item -ItemType Directory -Force -Path $OutDirFull | Out-Null
    $ManifestPath = Join-Path $OutDirFull "manifest.json"
    if (Test-Path $ManifestPath) {
        Remove-Item -LiteralPath $ManifestPath -Force
    }

    $Containers = Get-ChildItem -LiteralPath $ClientDir -File |
        Where-Object {
            ($_.Name.EndsWith(".unity3d", [System.StringComparison]::OrdinalIgnoreCase) -or
             $_.Name.EndsWith(".resourceFile", [System.StringComparison]::OrdinalIgnoreCase)) -and
            ($_.Name -notlike "*.bak*")
        } |
        Sort-Object Name

    foreach ($Container in $Containers) {
        $ContainerExtractDir = Join-Path $TempRoot ([System.IO.Path]::GetFileName($Container.Name))
        New-Item -ItemType Directory -Force -Path $ContainerExtractDir | Out-Null
        Invoke-Step "Extract $($Container.Name) with ffbuildtool" $FfBuildToolExe @(
            "extract-bundle",
            "-i",
            $Container.FullName,
            "-o",
            $ContainerExtractDir
        )

        $AssetFiles = Get-ChildItem -LiteralPath $ContainerExtractDir -File |
            Where-Object {
                $_.Extension -ne ".dll" -and
                $_.Name -ne "mainData" -and
                $_.Name -ne "manifest.json"
            } |
            Sort-Object Name

        foreach ($AssetFile in $AssetFiles) {
            $ExportArgs = @(
                $TexturePatchTool,
                "export",
                $ContainerExtractDir,
                $OutDirFull,
                "--asset",
                $AssetFile.Name,
                "--container",
                $Container.Name,
                "--allow-invalid-asset"
            )
            if ($NameRegex -ne "") {
                $ExportArgs += @("--name-regex", $NameRegex)
            }
            if ($MinWidth -gt 0) {
                $ExportArgs += @("--min-width", $MinWidth.ToString())
            }
            if ($MinHeight -gt 0) {
                $ExportArgs += @("--min-height", $MinHeight.ToString())
            }

            Invoke-Step "Export texture PNGs from $($Container.Name)\$($AssetFile.Name)" $Python $ExportArgs
        }
    }

    Write-Host "Texture patch folder: $OutDirFull"
}
finally {
    if (Test-Path $TempRoot) {
        Remove-Item -LiteralPath $TempRoot -Recurse -Force
    }
}
