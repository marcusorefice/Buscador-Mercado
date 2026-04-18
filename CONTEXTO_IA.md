# Contexto do Projeto: Monitoramento de Preços - Jundiaí

## 🎯 Objetivo

Sistema de inteligência para coleta, comparação e categorização de preços de supermercados em Jundiaí/SP. O projeto utiliza Python, Scraping avançado (API/Web) e Visão Computacional (Gemini Vision) para processar encartes.

## 🏗️ Estrutura de Pastas e Responsabilidades

- `/scrapers/`: Motores de coleta individuais. Devem herdar de `BaseScraper`.
- `/specs/`: **FONTE DA VERDADE.** Contém arquivos JSON com mapeamentos de seletores, URLs e IDs de loja de cada mercado. CONSULTE SEMPRE.
- `/data/`: Armazena banco de dados (`.db`), caches de categoria (`.json`) e logs de execução.
- `/temp_imagens/`: Pasta temporária para download de PDFs e JPEGs de encartes.
- `utils.py`: Funções globais obrigatórias para Log, limpeza de Preço e manipulação de arquivos.
- `motor_ia.py`: Orquestrador de Inteligência Artificial para OCR e Categorização.
- `main.py`: Maestro que lê a pasta `/scrapers` e executa a fila de monitoramento.

## 🛠️ Regras de Programação (Obrigatórias)

1. **Sem Prints:** É terminantemente proibido o uso de `print()`. Utilize o `logger` configurado em `utils.setup_logging()`.
2. **Tratamento de Preço:** Preços devem ser convertidos para `float` puro. Utilize `utils.clean_price_string()` para tratar vírgulas, R$ e espaços.
3. **Modularidade:** Não misture lógica de dois mercados no mesmo arquivo. Cada mercado tem seu `.py` em `/scrapers` e seu `.json` em `/specs`.
4. **Resiliência:** Utilize `try/except` e `asyncio.Semaphore` para evitar bloqueios de IP e falhas críticas durante a execução em massa.
5. **Regionalização:** O foco absoluto é **Jundiaí/SP**. IDs de loja e CEPs devem respeitar as configurações presentes nos arquivos de `/specs`.

## ⚠️ Instruções para o Gemini Code Assist

- **Não altere mais de um arquivo por vez.** Isso evita travamentos na interface do VS Code.
- Antes de sugerir mudanças em um scraper, peça para ler o arquivo correspondente em `/specs`.
- Mantenha a compatibilidade com Windows (`asyncio.WindowsSelectorEventLoopPolicy`).
- Sempre que houver erro de importação, verifique o arquivo `__init__.py` na pasta `/scrapers`.
