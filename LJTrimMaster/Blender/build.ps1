# Builds lj_trim_master into an installable Blender extension zip.
#
#   .\build.ps1
#   .\build.ps1 -Blender "C:\Program Files\Blender Foundation\Blender 4.5\blender.exe"
#   .\build.ps1 -Output .\dist
#
# Prefers `blender --command extension build`, which is the official packer and
# validates blender_manifest.toml on the way through - a malformed manifest is
# caught here rather than by the user at install time. Falls back to a plain zip
# when no Blender is found, which produces the same layout but checks nothing.
#
# blender.exe is not on PATH on the dev machine, hence the search list.

[CmdletBinding()]
param(
    [string] $Blender = "",
    [string] $Output = "$PSScriptRoot\dist"
)

$ErrorActionPreference = 'Stop'

$source = Join-Path $PSScriptRoot 'lj_trim_master'
$manifest = Join-Path $source 'blender_manifest.toml'
if (-not (Test-Path $manifest)) {
    throw "No blender_manifest.toml in $source - is this the right folder?"
}

# The zip must not carry __pycache__: Blender refuses an extension containing
# compiled files it did not produce, and they are per-Python-version anyway.
Get-ChildItem -Path $source -Recurse -Directory -Filter '__pycache__' |
    Remove-Item -Recurse -Force

# The build command writes its temp file into the output folder and will not
# create it, so it has to exist first.
New-Item -ItemType Directory -Force -Path $Output | Out-Null

function Find-Blender {
    if ($Blender) {
        if (Test-Path $Blender) { return $Blender }
        throw "No Blender at '$Blender'"
    }
    $candidates = @(
        (Get-Command blender -ErrorAction SilentlyContinue).Source
        "C:\Program Files\Blender Foundation\Blender 5.1\blender.exe"
        "C:\Program Files\Blender Foundation\Blender 4.5\blender.exe"
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path $candidate)) { return $candidate }
    }
    return $null
}

$exe = Find-Blender

if ($exe) {
    Write-Host "Building with $exe"
    # --factory-startup so third-party add-ons are not loaded. Two reasons: they
    # are irrelevant to packing, and a broken one (this machine has two) spews
    # tracebacks to stderr that look like build failures but are not.
    & $exe --factory-startup --command extension build --source-dir $source --output-dir $Output
    if ($LASTEXITCODE -ne 0) {
        throw "blender --command extension build failed with exit code $LASTEXITCODE"
    }
}
else {
    # No Blender to validate with. Still produce something installable, but say
    # plainly that the manifest was not checked.
    Write-Warning "No Blender found - zipping without validating the manifest."
    $version = (Select-String -Path $manifest -Pattern '^\s*version\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
    $zip = Join-Path $Output "lj_trim_master-$version.zip"
    if (Test-Path $zip) { Remove-Item $zip -Force }
    Compress-Archive -Path $source -DestinationPath $zip
    Write-Host "Wrote $zip"
}

Get-ChildItem $Output -Filter '*.zip' | ForEach-Object {
    Write-Host ("  {0}  ({1:N0} KB)" -f $_.Name, ($_.Length / 1KB))
}
