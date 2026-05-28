import asyncio
import json
import os
from playwright.async_api import async_playwright

async def rastrear_apis():
    print("\n" + "="*60)
    print("🕵️ INICIANDO O RADAR DE APIS - MODO ESPIONAGEM")
    print("="*60)
    print("⚠️ Um navegador vai abrir agora.")
    print("👉 Interaja com o site (ex: clique no menu de 'Departamentos' ou mude de página).")
    print("📡 As APIs capturadas aparecerão em tempo real aqui no terminal!\n")
    
    async with async_playwright() as p:
        # Abre o Chrome com interface gráfica para você poder clicar e interagir
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        async def capturar_respostas(response):
            # Filtra apenas chamadas de dados (APIs)
            if response.request.resource_type in ["fetch", "xhr"]:
                url = response.url
                
                # Filtra lixos de telemetria, Google Analytics, etc. para limpar o terminal
                if any(lixo in url for lixo in ['google', 'facebook', 'analytics', 'clarity', 'ping', 'vtex.js', 'gtm']): 
                    return
                
                try:
                    json_data = await response.json()
                    json_str = json.dumps(json_data).lower()
                    
                    # Heurística: Se o JSON trouxer palavras-chave do nosso interesse
                    if "category" in json_str or "department" in json_str or "products" in json_str or "categories" in json_str:
                        print("\n" + "🎯 ENCONTREI UMA API ÚTIL " + "-"*35)
                        print(f"🔗 URL: {url}")
                        print(f"⚙️ Método: {response.request.method} | Status: {response.status}")
                        
                        # Mostra as primeiras 300 letras da resposta para confirmar o que é
                        preview = json.dumps(json_data, indent=2, ensure_ascii=False)[:300]
                        print(f"📦 Preview dos Dados:\n{preview}...\n")
                except Exception:
                    pass # Ignora respostas que não sejam JSON

        # Escuta silenciosamente todas as respostas de rede da página
        page.on("response", capturar_respostas)
        
        # Abre o site alvo
        await page.goto("https://mercado.carrefour.com.br/")
        print("⏳ Escutando a rede pelos próximos 60 segundos...")
        
        # Mantém o script rodando para você ter tempo de clicar no menu de departamentos
        await asyncio.sleep(60)
        await browser.close()

if __name__ == "__main__":
    asyncio.run(rastrear_apis())
