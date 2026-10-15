param(
 [ValidateSet('source','release')][string]$Stage='source',
 [string]$PythonPath,
 [string]$OutputRoot='D:\Codex\local-reconcile\implementation\run-artifacts',
 [string]$ReleaseDir
)
$ErrorActionPreference='Stop'
$sourceRoot=Split-Path $PSScriptRoot -Parent
if (-not $PythonPath) {$PythonPath=Join-Path (Split-Path $sourceRoot -Parent) 'environment\Scripts\python.exe'}
if (-not (Test-Path -LiteralPath $PythonPath)) {throw '请通过 -PythonPath 指定已安装依赖的 Python 3.12'}
$OutputRoot=[IO.Path]::GetFullPath($OutputRoot)
if ($OutputRoot.StartsWith([IO.Path]::GetFullPath($sourceRoot)+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) {throw '测试产物目录必须位于源码目录之外'}
New-Item -ItemType Directory -Path $OutputRoot -Force | Out-Null
$env:PYTHONPATH=Join-Path $sourceRoot 'src'
$env:PYTHONPYCACHEPREFIX=Join-Path $OutputRoot 'pycache'
$env:QT_QPA_PLATFORM='offscreen'
$env:PYTHONIOENCODING='utf-8'
$env:TEMP=Join-Path $OutputRoot 'tmp'
$env:TMP=$env:TEMP
New-Item -ItemType Directory -Path $env:TEMP -Force | Out-Null
$pytestArgs=@('-B','-m','pytest','-q','-o',"cache_dir=$OutputRoot\pytest-cache",'--basetemp',"$OutputRoot\tmp\verify-$Stage",'--junitxml',"$OutputRoot\verify-$Stage.xml")
if ($Stage -eq 'source') {$pytestArgs+=@('tests','--ignore=tests/test_release.py')}
else {
 if (-not $ReleaseDir -or -not (Test-Path -LiteralPath $ReleaseDir)) {throw '发行检查需要实际 -ReleaseDir'}
 $env:LOCAL_RECONCILE_RELEASE_DIR=[IO.Path]::GetFullPath($ReleaseDir)
 $pytestArgs+='tests/test_release.py'
}
Push-Location -LiteralPath $sourceRoot
try {
 & $PythonPath @pytestArgs
 if ($LASTEXITCODE -ne 0) {throw "检查失败，退出码 $LASTEXITCODE"}
} finally {Pop-Location}
