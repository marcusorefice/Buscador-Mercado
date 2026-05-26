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

echo [2/3] Iniciando o localtunnel para expor a API na porta 8000...
start "localtunnel" cmd /k "npx -y localtunnel --port 8000 --subdomain comp-jundiai-api-99"

echo [3/3] Iniciando o Expo Metro Bundler...
:: Mata processos fantasmas do ngrok e usa aspas no Token para evitar espacos em branco no Windows
start "Expo Metro" cmd /k "taskkill /f /im ngrok.exe >nul 2>&1 & cd /d "%~dp0\comparador-app" && set "EXPO_NGROK_AUTHTOKEN=***REMOVIDO***" && npx expo start -c --tunnel"

echo.
echo =================================================================
echo    TUDO PRONTO!
echo =================================================================
echo.
echo   INSTRUCOES:
echo   1. A URL da sua API agora e fixa: https://comp-jundiai-api-99.loca.lt
echo   2. Cole essa URL no arquivo 'comparador-app/App.tsx' (voce so precisa fazer isso uma vez!).
echo   3. Salve o arquivo e use o QR Code da janela 'Expo Metro' para abrir o app no seu celular.
echo.
