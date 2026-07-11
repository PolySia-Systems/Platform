[CmdletBinding()]
param(
    [string]$OutputDirectory
)

$ErrorActionPreference = 'Stop'
$repository = [IO.Path]::GetFullPath((Split-Path $PSScriptRoot -Parent))
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path (Split-Path $repository -Parent) 'PolySia-source-exports'
}
$output = [IO.Path]::GetFullPath($OutputDirectory)

$repositoryPrefix = $repository.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
if (
    $output.Equals($repository, [StringComparison]::OrdinalIgnoreCase) -or
    $output.StartsWith($repositoryPrefix, [StringComparison]::OrdinalIgnoreCase)
) {
    throw 'Source exports must be written outside the repository.'
}

New-Item -ItemType Directory -Path $output -Force | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$archive = Join-Path $output "PolySia-source-$stamp.tar.gz"

$arguments = @(
    '-czf', $archive,
    '-C', $repository,
    '--exclude=.git',
    '--exclude=.env',
    '--exclude=.env.*',
    '--exclude=Polymarket Python SDK',
    '--exclude=release-artifacts',
    '--exclude=artifacts',
    '--exclude=__pycache__',
    '--exclude=.pytest_cache',
    '--exclude=.mypy_cache',
    '--exclude=.ruff_cache',
    '--exclude=*.pyc',
    '--exclude=*.sqlite',
    '--exclude=*.sqlite3',
    '--exclude=*.db',
    '--exclude=secrets',
    '.'
)

& tar.exe @arguments
if ($LASTEXITCODE -ne 0) {
    throw "Source export failed with exit code $LASTEXITCODE."
}

$hash = Get-FileHash -LiteralPath $archive -Algorithm SHA256
[pscustomobject]@{
    Archive = $archive
    Bytes = (Get-Item -LiteralPath $archive).Length
    SHA256 = $hash.Hash
}
