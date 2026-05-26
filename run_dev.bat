@echo off
title Orquestrador de Desenvolvimento - Comparador de Precos

echo.
echo =================================================================
echo    INICIANDO AMBIENTE DE DESENVOLVIMENTO COMPLETO
echo =================================================================
echo.
echo Este script vai abrir 3 janelas de terminal:
echo   1. A API Python (backend)
echo   2. O servico ngrok (para expor a API)
echo   3. O Metro Bundler do Expo (frontend)
echo.

echo [1/3] Iniciando a API Python (FastAPI) na porta 8000...
start "API Backend" cmd /k "cd /d "%~dp0" && python api.py"

echo [2/3] Iniciando o ngrok para expor a porta 8000...
start "ngrok" cmd /k "ngrok http 8000"

echo [3/3] Iniciando o Expo Metro Bundler...
start "Expo Metro" cmd /k "cd /d "%~dp0\comparador-app" && npx expo start -c"

echo.
echo =================================================================
echo    TUDO PRONTO!
echo =================================================================
echo.
echo   INSTRUCOES:
echo   1. Na janela do 'ngrok', copie a URL 'Forwarding' (ex: https://xxxx.ngrok-free.dev).
echo   2. Cole essa URL no arquivo 'comparador-app/App.tsx', na constante 'API_URL'.
echo   3. Salve o arquivo e use o QR Code da janela 'Expo Metro' para abrir o app no seu celular.
echo.
