param(
 [string]$SourceDir=(Split-Path $PSScriptRoot -Parent),
 [string]$OutputRoot='D:\Codex\local-reconcile\implementation',
 [string]$PythonPath,
 [string]$DownloadsDir
)
$ErrorActionPreference='Stop'
if (-not $DownloadsDir) {$DownloadsDir=Join-Path $OutputRoot 'downloads'}
$SourceDir=[IO.Path]::GetFullPath($SourceDir);$OutputRoot=[IO.Path]::GetFullPath($OutputRoot)
if ($OutputRoot.StartsWith($SourceDir+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase) -or $OutputRoot -eq $SourceDir) {throw '构建输出必须位于源码目录之外'}
if (-not $PythonPath) {$PythonPath=Join-Path $OutputRoot 'environment\Scripts\python.exe'}
$env:PYTHONPYCACHEPREFIX=Join-Path $OutputRoot 'run-artifacts\pycache'
$env:PYTHONPATH=Join-Path $SourceDir 'src'
$env:TEMP=Join-Path $OutputRoot 'run-artifacts\tmp';$env:TMP=$env:TEMP
$env:PYINSTALLER_CONFIG_DIR=Join-Path $OutputRoot 'build\pyinstaller-cache'
$env:PIP_CACHE_DIR=Join-Path $OutputRoot 'downloads\pip-cache'
& (Join-Path $PSScriptRoot 'verify.ps1') -Stage source -PythonPath $PythonPath -OutputRoot (Join-Path $OutputRoot 'run-artifacts')
& $PythonPath -B (Join-Path $PSScriptRoot 'prepare_release.py') --source-root $SourceDir --output-root (Join-Path $OutputRoot 'build\release-materials') --downloads $DownloadsDir
if ($LASTEXITCODE -ne 0) {throw '发行材料准备失败'}
& $PythonPath -B -m PyInstaller --noconfirm --distpath (Join-Path $OutputRoot 'release') --workpath (Join-Path $OutputRoot 'build\pyinstaller') (Join-Path $SourceDir 'packaging\local_reconcile.spec')
if ($LASTEXITCODE -ne 0) {throw '程序打包失败'}
$appDirectory=Join-Path $OutputRoot 'release\LocalReconcile'
foreach ($file in @('README.md','README.en.md','LICENSE','THIRD_PARTY_NOTICES.md','CHANGELOG.md')) {Copy-Item -LiteralPath (Join-Path $SourceDir $file) -Destination $appDirectory -Force}
Copy-Item -LiteralPath (Join-Path $OutputRoot 'build\release-materials\third_party') -Destination $appDirectory -Recurse -Force
Copy-Item -LiteralPath (Join-Path $SourceDir 'third_party\SOURCE_INFO.md') -Destination (Join-Path $appDirectory 'third_party') -Force
& $PythonPath -B (Join-Path $PSScriptRoot 'audit_release.py') --app-dir $appDirectory
if ($LASTEXITCODE -ne 0) {throw '发行模块与库源码覆盖检查失败'}
& (Join-Path $PSScriptRoot 'verify.ps1') -Stage release -PythonPath $PythonPath -OutputRoot (Join-Path $OutputRoot 'run-artifacts') -ReleaseDir $appDirectory
$archive=Join-Path $OutputRoot 'release\LocalReconcile-0.5.0-Windows-x64.zip'
Compress-Archive -LiteralPath $appDirectory -DestinationPath $archive -Force
(Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLower()+'  '+[IO.Path]::GetFileName($archive) | Set-Content -LiteralPath (Join-Path $OutputRoot 'release\SHA256SUMS.txt') -Encoding ascii
Write-Output "发行包已生成：$archive"
