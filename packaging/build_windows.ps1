param(
    [string]$Version = "1.0.0",
    [string]$LibreOfficeVersion = "26.2.5",
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot

if ($env:OS -ne "Windows_NT") {
    throw "GuideComparisonSetup.exe must be built on Windows."
}

& $Python -m pip install --disable-pip-version-check -r requirements-build.txt
if ($LASTEXITCODE -ne 0) { throw "Unable to install build dependencies." }

& $Python -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw "Tests failed; the installer was not built." }

& $Python -m PyInstaller --noconfirm --clean packaging\GuideComparison.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed." }

$DownloadDir = Join-Path $RepoRoot "build\downloads"
New-Item -ItemType Directory -Force -Path $DownloadDir | Out-Null
$LibreOfficeFile = "LibreOffice_${LibreOfficeVersion}_Win_x86-64.msi"
$LibreOfficeMsi = Join-Path $DownloadDir $LibreOfficeFile
$LibreOfficeUrl = "https://download.documentfoundation.org/libreoffice/stable/$LibreOfficeVersion/win/x86_64/$LibreOfficeFile"

if (-not (Test-Path $LibreOfficeMsi)) {
    Write-Host "Downloading LibreOffice $LibreOfficeVersion from The Document Foundation..."
    Invoke-WebRequest -Uri $LibreOfficeUrl -OutFile $LibreOfficeMsi
}

if ((Get-Item $LibreOfficeMsi).Length -lt 100MB) {
    throw "The LibreOffice MSI is unexpectedly small: $LibreOfficeMsi"
}
$Signature = Get-AuthenticodeSignature $LibreOfficeMsi
if ($Signature.Status -ne "Valid") {
    throw "The LibreOffice MSI does not have a valid Authenticode signature: $($Signature.Status)"
}

$IsccCandidates = @(
    "$env:ProgramFiles\Inno Setup 7\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 7\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
)
$Iscc = $IsccCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Iscc) {
    throw "Inno Setup 6 or 7 is required. Install it and rerun this script."
}

& $Iscc "/DAppVersion=$Version" "/DLibreOfficeMsi=$LibreOfficeMsi" "packaging\GuideComparison.iss"
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed." }

$Installer = Join-Path $RepoRoot "dist\installer\GuideComparisonSetup.exe"
if (-not (Test-Path $Installer)) { throw "Installer output was not created: $Installer" }
Write-Host "Created: $Installer"
