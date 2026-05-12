param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot ".."))
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "ff_patch_gui_common.ps1")

try {
    $RepoRoot = Normalize-FullPath $RepoRoot
    $source = Select-BuildFolder -RepoRoot $RepoRoot
    $defaultPatchDir = Get-DefaultPatchDir -SourceDir $source
    $legacyPatchDir = Get-LegacyPatchDir -SourceDir $source

    $patchDir = $null
    if ((Test-Path -LiteralPath $defaultPatchDir) -and (Test-PatchDir -PatchDir $defaultPatchDir)) {
        $choice = Ask-YesNoCancel "Found patch folder:`n$defaultPatchDir`n`nUse it?"
        if ($choice -eq [System.Windows.Forms.DialogResult]::Cancel) {
            exit 2
        }
        if ($choice -eq [System.Windows.Forms.DialogResult]::Yes) {
            $patchDir = $defaultPatchDir
        }
    }
    elseif ((Test-Path -LiteralPath $legacyPatchDir) -and (Test-PatchDir -PatchDir $legacyPatchDir)) {
        $choice = Ask-YesNoCancel "Found old patch folder:`n$legacyPatchDir`n`nUse it?"
        if ($choice -eq [System.Windows.Forms.DialogResult]::Cancel) {
            exit 2
        }
        if ($choice -eq [System.Windows.Forms.DialogResult]::Yes) {
            $patchDir = $legacyPatchDir
        }
    }

    while ($null -eq $patchDir) {
        $selectedPatchDir = Select-Folder `
            -Description "Select patch folder. It must contain ffpatch.json or translation.json." `
            -InitialDirectory (Split-Path -Parent $source) `
            -ShowNewFolderButton $false
        if ($null -eq $selectedPatchDir) {
            exit 2
        }
        if (Test-PatchDir -PatchDir $selectedPatchDir) {
            $patchDir = [System.IO.Path]::GetFullPath($selectedPatchDir)
        }
        else {
            Show-ErrorMessage "Selected folder does not contain ffpatch.json or translation.json.`n`n$selectedPatchDir"
        }
    }

    $outputDir = Get-DefaultOutputDir -SourceDir $source
    $force = $false
    if (Test-Path -LiteralPath $outputDir) {
        $overwrite = Ask-YesNo "Output folder already exists:`n$outputDir`n`nOverwrite it?"
        if ($overwrite -ne [System.Windows.Forms.DialogResult]::Yes) {
            exit 2
        }
        $force = $true
    }

    Write-Host "Source:    $source"
    Write-Host "Patch dir: $patchDir"
    Write-Host "Output:    $outputDir"

    $arguments = @(
        "build",
        "--source", $source,
        "--patch-dir", $patchDir,
        "--output", $outputDir
    )
    if ($force) {
        $arguments += "--force"
    }

    Invoke-RepoPatchTool -RepoRoot $RepoRoot -Arguments $arguments
    Show-Info "Patch applied.`n`nOutput build:`n$outputDir"
}
catch {
    Write-Error $_
    Show-ErrorMessage "Could not apply patch.`n`n$($_.Exception.Message)"
    exit 1
}
