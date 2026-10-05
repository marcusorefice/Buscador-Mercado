# Contexto do Projeto: Monitoramento de Preços - Jundiaí

## 🎯 Objetivo

Sistema de inteligência para coleta, comparação e categorização de preços de supermercados em Jundiaí/SP. O projeto utiliza Python, Scraping avançado (API/Web) e Visão Computacional (Gemini Vision) para processar encartes.

## 🏗️ Estrutura de Pastas e Responsabilidades

- `/scrapers/`: Motores de coleta individuais. `X.py` coleta só as promoções (diário, `main.py`); `X_full.py` coleta o catálogo inteiro (base, `main_full.py`).
- `/specs/`: **FONTE DA VERDADE.** Contém arquivos JSON com mapeamentos de seletores, URLs e IDs de loja de cada mercado. CONSULTE SEMPRE.
- `/data/`: Armazena banco de dados (`.db`), caches de categoria (`.json`) e logs de execução.
- `/temp_imagens/`: Pasta temporária para download de PDFs e JPEGs de encartes.
- `utils.py`: Funções globais obrigatórias para Log, limpeza de Preço e leitura/gravação segura de JSON.
- `motor_ia.py`: Orquestrador de Inteligência Artificial para OCR e Categorização.
- `main.py` / `main_full.py`: Executam os scrapers e acrescentam os itens em `data/pendentes_ia.json`.
- `4_resolver_pendentes.py`: Agrupa por EAN, casa nomes sem EAN com a biblioteca (`casamento_produtos.py`) e gera `data/itens_prontos_para_comparar.json`.
- `revisar_casamentos.py`: Importa as decisões S/N da planilha `data/revisao_casamentos.xlsx` para `data/casamentos.json`.
- `5_atualizar_banco.py`: Grava produtos, ofertas e histórico no Supabase e no SQLite local; sincroniza o Typesense.
- `api.py`: API FastAPI usada pelo app (`/comparador-app`).
- `/ferramentas/`: Scripts de manutenção e consulta (rodam de qualquer pasta).
- `/tests/`: Testes (`python -m unittest discover -s tests`).

## 🛠️ Regras de Programação (Obrigatórias)

1. **Sem Prints:** É terminantemente proibido o uso de `print()`. Utilize o `logger` configurado em `utils.setup_logging()`.
2. **Arquivos JSON:** Grave com `utils.salvar_json_atomico()` e leia com `utils.ler_json_seguro()` (nunca trate arquivo corrompido como vazio).
3. **Tratamento de Preço:** Preços devem ser convertidos para `float` puro. Utilize `utils.parse_preco()` para tratar vírgulas, R$ e espaços. Os scrapers já gravam o preço como número.
4. **Modularidade:** Não misture lógica de dois mercados no mesmo arquivo. Cada mercado tem seu `.py` em `/scrapers` e seu `.json` em `/specs`.
5. **Resiliência:** Utilize `try/except` e `asyncio.Semaphore` para evitar bloqueios de IP e falhas críticas durante a execução em massa.
6. **Regionalização:** O foco absoluto é **Jundiaí/SP**. IDs de loja e CEPs devem respeitar as configurações presentes nos arquivos de `/specs`.

## ⚠️ Instruções para o Gemini Code Assist

- **Não altere mais de um arquivo por vez.** Isso evita travamentos na interface do VS Code.
- Antes de sugerir mudanças em um scraper, peça para ler o arquivo correspondente em `/specs`.
- Mantenha a compatibilidade com Windows (`asyncio.WindowsSelectorEventLoopPolicy`).
- Sempre que houver erro de importação, verifique o arquivo `__init__.py` na pasta `/scrapers`.
