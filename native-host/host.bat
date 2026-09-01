@echo off
rem Chrome can only launch a .bat or .exe as a native messaging host, not a .py
rem file directly. %~dp0 is this file's own folder, so the project can be moved
rem without editing anything here.
"%~dp0..\.venv\Scripts\python.exe" -u "%~dp0host.py"
