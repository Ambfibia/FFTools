param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot ".."))
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "ff_patch_gui_common.ps1")

Add-Type -AssemblyName Microsoft.VisualBasic

function Ask-Text {
    param(
        [string]$Prompt,
        [string]$Title,
        [string]$Default = ""
    )

    return [Microsoft.VisualBasic.Interaction]::InputBox($Prompt, $Title, $Default)
}

function Test-PythonHasPillow {
    param([string]$PythonPath)

    if ($PythonPath -eq "" -or -not (Test-Path -LiteralPath $PythonPath)) {
        return $false
    }

    & $PythonPath -c "import PIL" 2>$null
    return $LASTEXITCODE -eq 0
}

function Select-PythonWithPillow {
    param([string]$RepoRoot)

    $candidates = @()
    if ($env:TEXTURE_PYTHON -ne $null -and $env:TEXTURE_PYTHON -ne "") {
        $candidates += $env:TEXTURE_PYTHON
    }
    $candidates += (Join-Path $RepoRoot "work\texture_venv_win\Scripts\python.exe")
    if ($env:PYTHON -ne $null -and $env:PYTHON -ne "") {
        $candidates += $env:PYTHON
    }

    foreach ($candidate in $candidates) {
        if (Test-PythonHasPillow -PythonPath $candidate) {
            return [System.IO.Path]::GetFullPath($candidate)
        }
    }

    $choice = Ask-YesNo "No Python with Pillow was found automatically.`n`nSelect python.exe with Pillow installed?"
    if ($choice -ne [System.Windows.Forms.DialogResult]::Yes) {
        throw "Texture export requires Python with Pillow. Set TEXTURE_PYTHON to the correct python.exe."
    }

    while ($true) {
        $python = Select-File `
            -Title "Select python.exe with Pillow installed" `
            -Filter "Python executable (python.exe)|python.exe|All files (*.*)|*.*" `
            -InitialDirectory $RepoRoot
        if ($null -eq $python) {
            exit 2
        }
        if (Test-PythonHasPillow -PythonPath $python) {
            return [System.IO.Path]::GetFullPath($python)
        }
        Show-ErrorMessage "Selected Python does not have Pillow installed.`n`n$python"
    }
}

try {
    $RepoRoot = Normalize-FullPath $RepoRoot
    $source = Select-BuildFolder -RepoRoot $RepoRoot
    $defaultPatchDir = Get-DefaultPatchDir -SourceDir $source

    $patchDir = $defaultPatchDir
    if (Test-Path -LiteralPath $defaultPatchDir) {
        $choice = Ask-YesNoCancel "Use texture patch folder under:`n$defaultPatchDir`n`nChoose No to select another patch folder."
        if ($choice -eq [System.Windows.Forms.DialogResult]::Cancel) {
            exit 2
        }
        if ($choice -eq [System.Windows.Forms.DialogResult]::No) {
            $patchDir = $null
        }
    }

    while ($null -eq $patchDir) {
        $selectedPatchDir = Select-Folder `
            -Description "Select patch folder where textures will be exported." `
            -InitialDirectory (Split-Path -Parent $source) `
            -ShowNewFolderButton $true
        if ($null -eq $selectedPatchDir) {
            exit 2
        }
        $patchDir = [System.IO.Path]::GetFullPath($selectedPatchDir)
    }

    $textureDir = Join-Path $patchDir "textures"
    $nameRegex = Ask-Text `
        -Title "Texture export filter" `
        -Prompt "Optional texture name regex. Leave empty to export all supported textures.`nExamples: help|title|button" `
        -Default "help|title|button"
    if ($null -eq $nameRegex) {
        exit 2
    }
    $texturePython = Select-PythonWithPillow -RepoRoot $RepoRoot

    Write-Host "Source:       $source"
    Write-Host "Patch dir:    $patchDir"
    Write-Host "Texture dir:  $textureDir"
    Write-Host "Python:       $texturePython"
    if ($nameRegex -ne "") {
        Write-Host "Name regex:   $nameRegex"
    }

    $script = Join-Path $RepoRoot "tools\export_texture_patch_beta20100104.ps1"
    $arguments = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $script,
        "-ClientDir", $source,
        "-OutDir", $textureDir,
        "-TexturePython", $texturePython
    )
    if ($nameRegex -ne "") {
        $arguments += @("-NameRegex", $nameRegex)
    }

    & powershell @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Texture export failed with exit code $LASTEXITCODE"
    }

    Show-Info "Texture PNGs exported to:`n$textureDir`n`nEdit PNGs there, then run the normal patch build."
}
catch {
    Write-Error $_
    Show-ErrorMessage "Could not export texture PNGs.`n`n$($_.Exception.Message)"
    exit 1
}
