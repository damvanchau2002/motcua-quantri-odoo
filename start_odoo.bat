@echo off
REM Fix charmap/cp1252 error on Windows
REM PYTHONUTF8=1 forces Python to use UTF-8 for all I/O (equivalent to -X utf8)

SET PYTHONUTF8=1
SET PYTHONIOENCODING=utf-8

REM Set Windows console to UTF-8
chcp 65001 >nul 2>&1

echo Starting Odoo with UTF-8 encoding...
python odoo-bin -c odoo.cfg %*
