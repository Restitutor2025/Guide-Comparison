param(
    [string]$Version = "1.0.0",
    [string]$LibreOfficeVersion = "26.2.5",
    [string]$Python = "",
    [string]$SigningThumbprint = $env:WINDOWS_SIGNING_CERT_THUMBPRINT,
    [ValidateSet("CurrentUser", "LocalMachine")]
    [string]$SigningStoreLocation = "CurrentUser",
    [string]$TimestampUrl = "http://timestamp.digicert.com",
    [switch]$RequireCodeSigning
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot

if (-not $Python) {
    $ProjectPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    $Python = if (Test-Path -LiteralPath $ProjectPython) { $ProjectPython } else { "python" }
}
Write-Host "Using Python: $Python"

if ($env:OS -ne "Windows_NT") {
    throw "GuideComparisonSetup.exe must be built on Windows."
}

function Find-SignTool {
    $Command = Get-Command signtool.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($Command) { return $Command.Source }

    $WindowsKitsBin = "${env:ProgramFiles(x86)}\Windows Kits\10\bin"
    if (Test-Path -LiteralPath $WindowsKitsBin) {
        $Candidate = Get-ChildItem -LiteralPath $WindowsKitsBin -Filter signtool.exe -Recurse -File |
            Where-Object { $_.DirectoryName -match '\\x64$' } |
            Sort-Object FullName -Descending |
            Select-Object -First 1
        if ($Candidate) { return $Candidate.FullName }
    }
    return $null
}

function Assert-ValidSignature([string]$Path) {
    $Signature = Get-AuthenticodeSignature -LiteralPath $Path
    if ($Signature.Status -ne "Valid") {
        throw "Authenticode verification failed for '$Path': $($Signature.Status)"
    }
}

$SigningThumbprint = if ($SigningThumbprint) { $SigningThumbprint.Replace(" ", "").ToUpperInvariant() } else { "" }
$CodeSigningEnabled = -not [string]::IsNullOrWhiteSpace($SigningThumbprint)
$SignTool = $null
if ($CodeSigningEnabled) {
    $StorePath = "Cert:\$SigningStoreLocation\My\$SigningThumbprint"
    $Certificate = Get-Item -LiteralPath $StorePath -ErrorAction SilentlyContinue
    if (-not $Certificate -or -not $Certificate.HasPrivateKey) {
        throw "A code-signing certificate with a private key was not found at '$StorePath'."
    }
    if ($Certificate.NotAfter -le (Get-Date)) {
        throw "The code-signing certificate expired on $($Certificate.NotAfter)."
    }
    if (-not ($Certificate.EnhancedKeyUsageList.ObjectId.Value -contains "1.3.6.1.5.5.7.3.3")) {
        throw "Certificate '$SigningThumbprint' is not valid for code signing."
    }
    $SignTool = Find-SignTool
    if (-not $SignTool) {
        throw "signtool.exe was not found. Install the Windows SDK signing tools."
    }
    Write-Host "Authenticode signing enabled: $($Certificate.Subject)"
} elseif ($RequireCodeSigning) {
    throw "A signed build was required, but -SigningThumbprint (or WINDOWS_SIGNING_CERT_THUMBPRINT) was not provided."
} else {
    Write-Warning "Building unsigned output. Do not distribute it publicly; pass -SigningThumbprint and -RequireCodeSigning for a release build."
}

& $Python -m pip install --disable-pip-version-check -r requirements-build.txt
if ($LASTEXITCODE -ne 0) { throw "Unable to install build dependencies." }

$PreviousQtPlatform = $env:QT_QPA_PLATFORM
$env:QT_QPA_PLATFORM = "offscreen"
& $Python -m unittest discover -s tests -v
$TestExitCode = $LASTEXITCODE
$env:QT_QPA_PLATFORM = $PreviousQtPlatform
if ($TestExitCode -ne 0) { throw "Tests failed; the installer was not built." }

& $Python -m PyInstaller --noconfirm --clean packaging\GuideComparison.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed." }

$ApplicationExe = Join-Path $RepoRoot "dist\GuideComparison\GuideComparison.exe"
if (-not (Test-Path -LiteralPath $ApplicationExe)) {
    throw "Frozen application output was not created: $ApplicationExe"
}
if ($CodeSigningEnabled) {
    $StoreArguments = if ($SigningStoreLocation -eq "LocalMachine") { @("/sm", "/s", "My") } else { @("/s", "My") }
    & $SignTool sign @StoreArguments /sha1 $SigningThumbprint /fd SHA256 /td SHA256 /tr $TimestampUrl /d "Guide Comparison" $ApplicationExe
    if ($LASTEXITCODE -ne 0) { throw "Unable to sign $ApplicationExe" }
    Assert-ValidSignature $ApplicationExe
}

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
    "$env:LOCALAPPDATA\Programs\Inno Setup 7\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 7\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 7\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
)
$Iscc = $IsccCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Iscc) {
    throw "Inno Setup 6 or 7 is required. Install it and rerun this script."
}

$IsccArguments = @(
    "/DAppVersion=$Version",
    "/DLibreOfficeMsi=$LibreOfficeMsi"
)
if ($CodeSigningEnabled) {
    $StoreSwitch = if ($SigningStoreLocation -eq "LocalMachine") { "/sm /s My" } else { "/s My" }
    $InnoSignCommand = "`"$SignTool`" sign $StoreSwitch /sha1 $SigningThumbprint /fd SHA256 /td SHA256 /tr $TimestampUrl /d `$qGuide Comparison`$q `$f"
    $IsccArguments += "/DEnableCodeSigning=1"
    $IsccArguments += "/Sguidecomparisonsigntool=$InnoSignCommand"
}
$IsccArguments += "packaging\GuideComparison.iss"

& $Iscc @IsccArguments
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed." }

$Installer = Join-Path $RepoRoot "dist\installer\GuideComparisonSetup.exe"
if (-not (Test-Path $Installer)) { throw "Installer output was not created: $Installer" }
if ($CodeSigningEnabled) {
    Assert-ValidSignature $Installer
}
Write-Host "Created: $Installer"
