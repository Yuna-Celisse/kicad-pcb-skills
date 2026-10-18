# Mount this repository's skill directories as junctions into a target skills folder.
# Preview by default; pass -Apply to create links.

[CmdletBinding()]
param(
    [string]$Target = (Join-Path $HOME '.dsh\skills'),
    [switch]$Apply
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$names = @(
    'pcb-flow',
    'pcb-schematic',
    'pcb-components',
    'pcb-layout',
    'pcb-routing',
    'pcb-verification',
    'pcb-manufacturing',
    'pcb-toolkit'
)

Write-Host "suite : $root"
Write-Host "target: $Target"
if (-not $Apply) {
    Write-Host "DRY RUN (no links created; pass -Apply to execute)"
}

if ($Apply -and -not (Test-Path $Target)) {
    New-Item -ItemType Directory -Path $Target | Out-Null
    Write-Host "mkdir $Target"
}

foreach ($name in $names) {
    $src = Join-Path $root $name
    if (-not (Test-Path $src)) {
        throw "missing skill dir: $src"
    }
    $dst = Join-Path $Target $name

    if (Test-Path $dst) {
        $item = Get-Item $dst -Force
        $linked = $false
        if ($item.LinkType -eq 'Junction' -and $item.Target) {
            $linked = ([string]$item.Target).TrimEnd('\') -ieq $src.TrimEnd('\')
        }
        if ($linked) {
            Write-Host "skip  $name (already points here)"
            continue
        }
        throw "refusing to overwrite existing: $dst"
    }

    if ($Apply) {
        New-Item -ItemType Junction -Path $dst -Target $src | Out-Null
        Write-Host "link  $name -> $src"
    }
    else {
        Write-Host "plan  $name -> $src"
    }
}

if (-not $Apply) {
    Write-Host "preview complete; run with -Apply to create links"
}
