# WFRP4e Character Sheet - Windows Installer/Launcher
# Run this if you don't have Python installed yet.
# Right-click → "Run with PowerShell"
# Or double-click the Install_and_Run.bat file instead.

$ErrorActionPreference = "Stop"
$AppName = "WFRP4e Character Sheet"
$AppDir  = Join-Path $env:LOCALAPPDATA "WFRP4e_Character_Sheet"

Write-Host ""
Write-Host "  =============================================="
Write-Host "   $AppName"  
Write-Host "  =============================================="
Write-Host ""

# ── Check / Install Python ──────────────────────────────────────────────────
function Find-Python {
    $candidates = @("python", "python3", "py")
    foreach ($cmd in $candidates) {
        try {
            $out = & $cmd --version 2>&1
            if ($out -match "Python 3\.(\d+)" -and [int]$Matches[1] -ge 8) {
                return (Get-Command $cmd).Source
            }
        } catch {}
    }
    # Check registry
    $paths = @(
        "HKLM:\SOFTWARE\Python\PythonCore",
        "HKCU:\SOFTWARE\Python\PythonCore",
        "HKLM:\SOFTWARE\WOW6432Node\Python\PythonCore"
    )
    foreach ($regPath in $paths) {
        if (Test-Path $regPath) {
            Get-ChildItem $regPath | ForEach-Object {
                $ver = $_.PSChildName
                if ($ver -match "^3\.(\d+)" -and [int]$Matches[1] -ge 8) {
                    $install = Join-Path $_.PSPath "InstallPath"
                    if (Test-Path $install) {
                        $dir = (Get-ItemProperty $install)."(default)"
                        $exe = Join-Path $dir "python.exe"
                        if (Test-Path $exe) { return $exe }
                    }
                }
            }
        }
    }
    return $null
}

$python = Find-Python
if (-not $python) {
    Write-Host "  Python not found. Downloading and installing Python 3.12..."
    Write-Host "  (One-time setup, ~25 MB)"
    Write-Host ""
    
    $installer = Join-Path $env:TEMP "python_installer.exe"
    $url = "https://www.python.org/ftp/python/3.12.0/python-3.12.0-amd64.exe"
    
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $url -OutFile $installer -UseBasicParsing
    } catch {
        Write-Host "  ERROR: Could not download Python."
        Write-Host "  Please install Python 3 from https://www.python.org/"
        Read-Host "  Press Enter to exit"
        exit 1
    }
    
    Write-Host "  Installing Python (this may take a minute)..."
    Start-Process -FilePath $installer -ArgumentList @(
        "/quiet", "InstallAllUsers=0", "PrependPath=1", "Include_pip=1"
    ) -Wait
    Remove-Item $installer -Force
    
    $python = Find-Python
    if (-not $python) {
        Write-Host "  ERROR: Python installation failed."
        Write-Host "  Please install Python 3 from https://www.python.org/"
        Read-Host "  Press Enter to exit"
        exit 1
    }
    Write-Host "  Python installed successfully!"
    Write-Host ""
}

Write-Host "  Python found: $python"

# ── Install pypdf ─────────────────────────────────────────────────────────
$test = & $python -c "import pypdf" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "  Installing pypdf..."
    & $python -m pip install pypdf --quiet
    Write-Host "  pypdf installed!"
    Write-Host ""
}

# ── Copy app files to AppData ─────────────────────────────────────────────
Write-Host "  Setting up application files..."
if (-not (Test-Path $AppDir)) { New-Item -ItemType Directory -Path $AppDir | Out-Null }

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Copy-Item (Join-Path $ScriptDir "wfrp_app.py") $AppDir -Force
Copy-Item (Join-Path $ScriptDir "wfrp4e_character_sheet.html") $AppDir -Force

# Copy PDF template if it exists
$pdf = Get-ChildItem $ScriptDir -Filter "*Fillable*Character*Sheet*.pdf" | Select-Object -First 1
if ($pdf) { Copy-Item $pdf.FullName $AppDir -Force }

# Create a desktop shortcut
$WshShell = New-Object -comObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("$env:USERPROFILE\Desktop\WFRP Character Sheet.lnk")
$Shortcut.TargetPath = $python
$Shortcut.Arguments  = "`"$(Join-Path $AppDir 'wfrp_app.py')`""
$Shortcut.WorkingDirectory = $AppDir
$Shortcut.Description = "WFRP4e Character Sheet"
$Shortcut.Save()

Write-Host "  Shortcut created on your Desktop!"
Write-Host ""

# ── Launch ────────────────────────────────────────────────────────────────
Write-Host "  Launching WFRP4e Character Sheet..."
Write-Host "  (The app will open in your browser)"
Write-Host ""
Write-Host "  Keep this window open while using the app."
Write-Host "  Press Ctrl+C to stop."
Write-Host ""

& $python (Join-Path $AppDir "wfrp_app.py")
