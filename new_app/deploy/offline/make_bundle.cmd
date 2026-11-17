@echo off
rem 在 cmd / PowerShell 中运行（或双击）：用 Git Bash 执行 make_bundle.sh。
rem 不能直接敲 bash —— 那会调用 WSL 的 bash。用法: make_bundle.cmd [web^|app^|all]
chcp 65001 >nul
setlocal
for /f "delims=" %%G in ('where git 2^>nul') do (
  if exist "%%~dpG..\bin\bash.exe" set "GB=%%~dpG..\bin\bash.exe"
  if exist "%%~dpG..\..\bin\bash.exe" set "GB=%%~dpG..\..\bin\bash.exe"
)
if not defined GB (
  echo 找不到 Git Bash，请先安装 Git for Windows
  exit /b 1
)
"%GB%" "%~dp0make_bundle.sh" %*
if "%~1"=="" pause
