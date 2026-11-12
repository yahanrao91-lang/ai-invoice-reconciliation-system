@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo 正在创建虚拟环境...
    python -m venv .venv
    .venv\Scripts\python.exe -m pip install --upgrade pip
    .venv\Scripts\python.exe -m pip install -r requirements.txt
)
echo 正在启动 AI 智能票据审核与采购对账系统...
.venv\Scripts\python.exe -m streamlit run app.py
pause
