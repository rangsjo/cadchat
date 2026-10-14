# cadchat + Creo launcher. Run it through creo\start.cmd (see creo\README.md).
# Installs Python and a JDK with winget if they are missing, creates .venv on first run, then hands over to tools\creolink.py.
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Rest)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Update-SessionPath {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
}

function Install-WithWinget([string]$id, [string]$what) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "$what is missing and winget is not available. Install it by hand (id: $id) and run this again."
    }
    Write-Host "Installing $what with winget ..."
    winget install -e --id $id --accept-source-agreements --accept-package-agreements
    Update-SessionPath
}

function Find-Python {
    foreach ($c in @('py', 'python', 'python3')) {
        $cmd = Get-Command $c -ErrorAction SilentlyContinue
        if (-not $cmd) { continue }
        $extra = if ($c -eq 'py') { @('-3') } else { @() }
        try { & $cmd.Source @extra -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>$null } catch { continue }
        if ($LASTEXITCODE -eq 0) { return @($cmd.Source) + $extra }     # skips the Microsoft Store stub, which exits non-zero
    }
    return $null
}

$py = Find-Python
if (-not $py) {
    Install-WithWinget 'Python.Python.3.12' 'Python 3.12'
    $py = Find-Python
    if (-not $py) { throw 'Python was installed but is not on PATH yet. Open a new terminal and run creo\start.cmd again.' }
}

$venvPython = Join-Path $root '.venv\Scripts\python.exe'
$marker = Join-Path $root '.venv\.cadchat-ready'
if (-not (Test-Path $marker)) {
    Write-Host 'First run: creating the Python environment (a few minutes, build123d is large) ...'
    $pyArgs = if ($py.Length -gt 1) { @($py[1..($py.Length - 1)]) } else { @() }
    & $py[0] @pyArgs -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'could not create .venv' }
    & $venvPython -m pip install --quiet --upgrade pip
    & $venvPython -m pip install --quiet -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'pip install failed' }
    New-Item -ItemType File -Path $marker -Force | Out-Null
}

$mode = 'start'
$passArgs = @($Rest)
if ($passArgs.Count -gt 0 -and $passArgs[0] -in @('doctor', 'start', 'run')) {
    $mode = $passArgs[0]
    $passArgs = @($passArgs | Select-Object -Skip 1)
}

& $venvPython tools\creolink.py $mode @passArgs
if ($LASTEXITCODE -eq 3 -and $mode -ne 'doctor') {          # creolink.py: no JDK found
    Install-WithWinget 'EclipseAdoptium.Temurin.17.JDK' 'a Java JDK (Temurin 17)'
    & $venvPython tools\creolink.py $mode @passArgs
}
exit $LASTEXITCODE
