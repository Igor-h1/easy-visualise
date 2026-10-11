@echo off
title Easy Visualise

echo ========================================
echo   Easy Visualise - Iniciando...
echo ========================================
echo.

:: Verifica se Python esta instalado
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERRO] Python nao encontrado!
    echo Por favor, instale o Python em: https://www.python.org/downloads/
    echo.
    pause
    exit /b
)

:: Verifica se customtkinter esta instalado
python -c "import customtkinter" >nul 2>&1
if errorlevel 1 (
    echo [INFO] Instalando dependencias...
    pip install -r requirements.txt
    echo.
)

:: Roda o aplicativo
echo [INFO] Abrindo Easy Visualise...
echo.
python src\main.py

:: Se o app fechar com erro, mostra a mensagem
if errorlevel 1 (
    echo.
    echo [ERRO] O aplicativo fechou com erro.
    pause
)