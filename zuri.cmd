@echo off
setlocal
"%~dp0.venv\Scripts\python.exe" -m app.cli %*
