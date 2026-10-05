# Pacote dos scrapers.
# Não importe os scrapers aqui: o Python executa este arquivo a cada "import scrapers.X",
# e importar todos (inclusive os que usam Selenium/Playwright) deixava cada import lento
# e fazia um scraper quebrado derrubar todos os outros.
# Use sempre o import direto: "import scrapers.covabra_full as covabra_full".
