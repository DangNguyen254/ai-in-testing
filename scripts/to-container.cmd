@echo off
rem Copy this project's last commit into a container: to-container.cmd <container> [--target ...]
python "%~dp0to_container.py" %*
