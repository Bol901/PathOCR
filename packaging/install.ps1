$ErrorActionPreference = 'Stop'
$sourceDir = $PSScriptRoot
$targetDir = Join-Path $env:LOCALAPPDATA 'Programs\PathOCR'
New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
Get-ChildItem -LiteralPath $sourceDir | Where-Object { $_.Name -ne 'Install.cmd' -and $_.Name -ne 'install.ps1' } | Copy-Item -Destination $targetDir -Recurse -Force
$taskShell = New-Object -ComObject WScript.Shell
$shortcutPath = Join-Path ([Environment]::GetFolderPath('Desktop')) 'PathOCR.lnk'
$shortcut = $taskShell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = Join-Path $targetDir 'PathOCR.exe'
$shortcut.WorkingDirectory = $targetDir
$shortcut.Save()
Write-Host 'PathOCR installed. Use the desktop shortcut to start.'
Start-Process -FilePath (Join-Path $targetDir 'PathOCR.exe') -WindowStyle Hidden
