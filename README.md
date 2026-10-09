# 🛒 Comparador de Preços de Supermercados – Jundiaí/SP

Sistema completo, da coleta ao app, que compara preços de **8 redes de supermercados de Jundiaí/SP**.

| | |
|---|---|
| **Produtos cadastrados** | ~58 mil |
| **Preços ativos** | ~74 mil |
| **Produtos comparáveis em 2+ mercados** | ~14 mil |
| **Mercados** | Atacadão, Carrefour, Boa Supermercados, Pão de Açúcar, Covabra, Oba Hortifruti, Dom Olívio e São Vicente |

> Números da base em outubro/2026.

---

## O problema

Cada supermercado tem seu próprio site, sua própria forma de escrever o nome do produto, e nem todos informam o código de barras (EAN). Para comparar "Leite Integral Italac 1L" entre 8 mercados, é preciso:

1. **coletar** catálogos inteiros de sites com tecnologias diferentes;
2. **entender** que `LEITE UHT INTEG. ITALAC 1LT` e `Leite Italac Integral 1 Litro` são o mesmo produto;
3. **entregar** isso rápido no celular, com busca, histórico e lista de compras.

## Arquitetura

```
 Sites dos mercados
        │  scrapers/ (Python assíncrono: Playwright, curl_cffi, BeautifulSoup)
        ▼
 main_full.py ─► coleta o catálogo completo (main.py: só promoções, diário)
        │
        ▼
 4_resolver_pendentes.py ─► agrupa por EAN e casa os produtos sem EAN
        │                   (casamento_produtos.py + classificador_ia.py / Gemini)
        ▼
 5_atualizar_banco.py ─► PostgreSQL (Supabase) + SQLite local + índice Typesense
        │
        ▼
 api.py (FastAPI) ─► comparador-app/ (React Native + Expo)
```

## Destaques técnicos

- **Coleta resiliente**: um scraper por mercado, com seletores, IDs de loja e CEPs isolados em `specs/*.json`. Usa execução assíncrona com `asyncio.Semaphore`, retry e checkpoint, para que uma coleta interrompida retome de onde parou.
- **Casamento de produtos sem EAN** (`casamento_produtos.py`): o nome vira uma *assinatura* (marca, medida normalizada, embalagem e palavras-chave), que é comparada com a biblioteca de produtos.
  - Confiança alta: o produto é casado automaticamente.
  - Caso duvidoso: vai para uma planilha de revisão manual, e as decisões ficam salvas.
  - Sem candidato: forma um grupo interno com produtos equivalentes de outros mercados.
- **Normalização de preços e medidas**: trata packs, venda por kg, preço de atacado com quantidade mínima, combos e preços fora da curva (uma quarentena de anomalias evita distorções).
- **Categorização com IA**: a API do Gemini classifica os produtos novos em categoria e subcategoria, com rodízio de chaves e retry.
- **Banco e busca**: PostgreSQL no Supabase com tabela de ofertas atuais e histórico de preços. O autocomplete usa o Typesense, consultado pela própria API para não expor chaves no app.
- **App mobile** (React Native, Expo, TypeScript, Zustand):
  - busca com autocomplete e paginação ao rolar;
  - leitor de código de barras (EAN-13, EAN-8 e UPC);
  - histórico de preço de cada produto;
  - lista de compras que calcula a **melhor combinação de até 2 mercados**, respeitando o preço de atacado.
- **Testes**: 47 testes unitários do casamento de produtos e do pipeline (`python -m unittest discover -s tests`).

## Stack

**Back-end e dados:** Python, asyncio, Playwright, curl_cffi, BeautifulSoup, FastAPI, PostgreSQL (Supabase), SQLite, Typesense e Google Gemini API.
**Mobile:** React Native, Expo, TypeScript, React Native Paper e Zustand.

## Estrutura

```
scrapers/            um coletor por mercado (X.py = promoções, X_full.py = catálogo)
specs/               configuração de cada mercado (seletores, URLs, IDs de loja)
casamento_produtos.py   algoritmo de casamento por assinatura de nome
classificador_ia.py     categorização com Gemini
api.py               API FastAPI consumida pelo app
comparador-app/      app React Native/Expo
ferramentas/         scripts de manutenção e auditoria da base
tests/               testes unitários
```

## Como rodar

```bash
# 1. Dependências
python -m venv .venv && .venv\Scripts\activate   # Windows
pip install -r requirements.txt
playwright install chromium

# 2. Variáveis de ambiente (.env, não versionado)
#    DATABASE_URL, GEMINI_API_KEYS, TYPESENSE_HOST, TYPESENSE_SEARCH_KEY ...

# 3. Pipeline
python main_full.py            # coleta
python 4_resolver_pendentes.py # casamento/categorização
python 5_atualizar_banco.py    # grava no banco e sincroniza a busca

# 4. API e app
python api.py
cd comparador-app && npm install && npx expo start
```

## Autor

**Marcus Orefice**: [LinkedIn](https://www.linkedin.com/in/marcus-orefice/)
