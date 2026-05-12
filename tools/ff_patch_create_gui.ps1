param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot ".."))
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "ff_patch_gui_common.ps1")

try {
    $RepoRoot = Normalize-FullPath $RepoRoot
    $source = Select-BuildFolder -RepoRoot $RepoRoot
    $patchDir = Get-DefaultPatchDir -SourceDir $source

    $fontPath = $null
    $fontChoice = Ask-YesNoCancel "Select one fallback TTF font for Cyrillic and save it as font.ttf?`n`nFor per-family fonts choose No, then add TTF files later to:`n$patchDir\fonts`nExample: JEFFE.ttf"
    if ($fontChoice -eq [System.Windows.Forms.DialogResult]::Cancel) {
        exit 2
    }
    if ($fontChoice -eq [System.Windows.Forms.DialogResult]::Yes) {
        $fontPath = Select-File `
            -Title "Select TTF font with Cyrillic glyphs" `
            -Filter "TrueType fonts (*.ttf)|*.ttf|All files (*.*)|*.*" `
            -InitialDirectory (Join-Path $env:WINDIR "Fonts")
        if ($null -eq $fontPath) {
            exit 2
        }
    }

    Write-Host "Source:    $source"
    Write-Host "Patch dir: $patchDir"
    if ($fontPath) {
        Write-Host "Font:      $fontPath"
    }

    $arguments = @("init", "--source", $source, "--patch-dir", $patchDir)
    if ($fontPath) {
        $arguments += @("--font-ttf", $fontPath, "--force")
    }

    Invoke-RepoPatchTool -RepoRoot $RepoRoot -Arguments $arguments
    Show-Info "Patch folder created:`n$patchDir"
}
catch {
    Write-Error $_
    Show-ErrorMessage "Could not create patch folder.`n`n$($_.Exception.Message)"
    exit 1
}
