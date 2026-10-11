@echo off
chcp 65001 >nul
title Easy Visualise
color 0B

echo.
echo  ========================================
echo     Easy Visualise - Iniciando...
echo  ========================================
echo.

:: -------------------------------------------------
:: 1. Detecta o Python (tenta 'python' e depois 'py')
:: -------------------------------------------------
set "PYTHON_CMD="

python --version >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_CMD=python"
    goto :python_found
)

py --version >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_CMD=py"
    goto :python_found
)

echo  [ERRO] Python nao encontrado!
echo.
echo  Instale o Python em: https://www.python.org/downloads/
echo  IMPORTANTE: marque a opcao "Add Python to PATH" na instalacao.
echo.
pause
exit /b 1

:python_found
echo  [OK] Python detectado: %PYTHON_CMD%
%PYTHON_CMD% --version
echo.

:: -------------------------------------------------
:: 2. Verifica se o customtkinter esta instalado
:: -------------------------------------------------
echo  [INFO] Verificando dependencias...
%PYTHON_CMD% -c "import customtkinter" >nul 2>&1
if not errorlevel 1 (
    echo  [OK] Dependencias ja instaladas.
    echo.
    goto :run_app
)

:: -------------------------------------------------
:: 3. Instala as dependencias automaticamente
:: -------------------------------------------------
echo  [INFO] Instalando dependencias (primeira vez)...
echo.

%PYTHON_CMD% -m pip install --upgrade pip >nul 2>&1
%PYTHON_CMD% -m pip install -r requirements.txt

if errorlevel 1 (
    echo.
    echo  [ERRO] Falha ao instalar depesndencias.
    echo  Tentando com --user...
    echo.
    %PYTHON_CMD% -m