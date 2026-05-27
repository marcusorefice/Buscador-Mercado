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

echo [2/3] Iniciando o ngrok para expor a API (URL FIXA)...
start "ngrok API" cmd /k "npx @ngrok/ngrok http 8000 --domain=badness-impale-suitably.ngrok-free.dev"

echo [3/3] Iniciando o Expo Metro Bundler...
:: Inicia o Expo em modo LAN (mais estável). Use o QR Code no seu celular na mesma rede Wi-Fi.
start "Expo Metro" cmd /k "cd /d "%~dp0\comparador-app" && npx expo start -c"

echo.
echo =================================================================
echo    TUDO PRONTO!
echo =================================================================
echo.
echo   INSTRUCOES:
echo   1. A API esta rodando com o dominio estatico do ngrok!
echo   2. Certifique-se de que substituiu o dominio no 'App.tsx' antes de gerar o APK final.
echo   3. Para desenvolver, conecte seu celular na mesma rede Wi-Fi e escaneie o QR Code do Expo.
echo.
