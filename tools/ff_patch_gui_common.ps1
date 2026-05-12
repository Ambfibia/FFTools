$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.Application]::EnableVisualStyles()

function Show-Info {
    param(
        [string]$Text,
        [string]$Caption = "FF Patch Tool"
    )
    [System.Windows.Forms.MessageBox]::Show(
        $Text,
        $Caption,
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Information
    ) | Out-Null
}

function Normalize-FullPath {
    param(
        [string]$Path
    )

    if ($null -eq $Path) {
        throw "Path is empty."
    }

    $clean = $Path.Trim().Trim('"')
    return [System.IO.Path]::GetFullPath($clean)
}

function Show-ErrorMessage {
    param(
        [string]$Text,
        [string]$Caption = "FF Patch Tool"
    )
    [System.Windows.Forms.MessageBox]::Show(
        $Text,
        $Caption,
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Error
    ) | Out-Null
}

function Ask-YesNoCancel {
    param(
        [string]$Text,
        [string]$Caption = "FF Patch Tool"
    )
    [System.Windows.Forms.MessageBox]::Show(
        $Text,
        $Caption,
        [System.Windows.Forms.MessageBoxButtons]::YesNoCancel,
        [System.Windows.Forms.MessageBoxIcon]::Question
    )
}

function Ask-YesNo {
    param(
        [string]$Text,
        [string]$Caption = "FF Patch Tool"
    )
    [System.Windows.Forms.MessageBox]::Show(
        $Text,
        $Caption,
        [System.Windows.Forms.MessageBoxButtons]::YesNo,
        [System.Windows.Forms.MessageBoxIcon]::Question
    )
}

function Select-Folder {
    param(
        [string]$Description,
        [string]$InitialDirectory = "",
        [bool]$ShowNewFolderButton = $false
    )

    $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
    $dialog.Description = $Description
    $dialog.ShowNewFolderButton = $ShowNewFolderButton
    if ($InitialDirectory -ne "" -and (Test-Path -LiteralPath $InitialDirectory)) {
        $dialog.SelectedPath = $InitialDirectory
    }

    $result = $dialog.ShowDialog()
    if ($result -ne [System.Windows.Forms.DialogResult]::OK) {
        return $null
    }

    return $dialog.SelectedPath
}

function Select-File {
    param(
        [string]$Title,
        [string]$Filter,
        [string]$InitialDirectory = ""
    )

    $dialog = New-Object System.Windows.Forms.OpenFileDialog
    $dialog.Title = $Title
    $dialog.Filter = $Filter
    $dialog.CheckFileExists = $true
    $dialog.Multiselect = $false
    if ($InitialDirectory -ne "" -and (Test-Path -LiteralPath $InitialDirectory)) {
        $dialog.InitialDirectory = $InitialDirectory
    }

    $result = $dialog.ShowDialog()
    if ($result -ne [System.Windows.Forms.DialogResult]::OK) {
        return $null
    }

    return $dialog.FileName
}

function Select-BuildFolder {
    param(
        [string]$RepoRoot
    )

    while ($true) {
        $source = Select-Folder `
            -Description "Select source FusionFall build folder, for example beta-20100104" `
            -InitialDirectory $RepoRoot `
            -ShowNewFolderButton $false

        if ($null -eq $source) {
            exit 2
        }

        if (Test-Path -LiteralPath (Join-Path $source "main.unity3d")) {
            return [System.IO.Path]::GetFullPath($source)
        }

        Show-ErrorMessage "Selected folder does not contain main.unity3d.`n`n$source"
    }
}

function Get-DefaultPatchDir {
    param(
        [string]$SourceDir
    )

    $sourceItem = Get-Item -LiteralPath $SourceDir
    if ($null -eq $sourceItem.Parent) {
        throw "Cannot create a patch directory next to root folder: $SourceDir"
    }

    return Join-Path $sourceItem.Parent.FullName ($sourceItem.Name + "-ru-patch")
}

function Get-LegacyPatchDir {
    param(
        [string]$SourceDir
    )

    $sourceItem = Get-Item -LiteralPath $SourceDir
    if ($null -eq $sourceItem.Parent) {
        throw "Cannot find a patch directory next to root folder: $SourceDir"
    }

    return Join-Path $sourceItem.Parent.FullName ($sourceItem.Name + "-patch")
}

function Get-DefaultOutputDir {
    param(
        [string]$SourceDir
    )

    $sourceItem = Get-Item -LiteralPath $SourceDir
    if ($null -eq $sourceItem.Parent) {
        throw "Cannot create an output directory next to root folder: $SourceDir"
    }

    return Join-Path $sourceItem.Parent.FullName ($sourceItem.Name + "-ru")
}

function Test-PatchDir {
    param(
        [string]$PatchDir
    )

    return (Test-Path -LiteralPath (Join-Path $PatchDir "ffpatch.json")) -or
        (Test-Path -LiteralPath (Join-Path $PatchDir "translation.json"))
}

function Invoke-RepoPatchTool {
    param(
        [string]$RepoRoot,
        [string[]]$Arguments
    )

    $tool = Join-Path $RepoRoot "30_ff_patch_tool.bat"
    if (-not (Test-Path -LiteralPath $tool)) {
        throw "Patch tool launcher was not found: $tool"
    }

    & $tool @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "FfPatchTool failed with exit code $LASTEXITCODE"
    }
}
