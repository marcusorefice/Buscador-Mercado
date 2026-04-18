import requests
import urllib.parse
import re
import time

def buscar_imagem_na_web(nome_produto):
    """
    Buscador robusto de imagens: Tenta o Yahoo primeiro (mais estável) e depois o Bing.
    Inclui feedback visual no terminal.
    """
    print(f"   🌐 Buscando: {nome_produto[:45]}...")
    termo = f"{nome_produto} png"
    query = urllib.parse.quote(termo)
    
    # Cabeçalhos para simular um navegador real
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
    }
    
    # --- TENTATIVA 1: YAHOO IMAGENS ---
    try:
        url_yahoo = f"https://images.search.yahoo.com/search/images?p={query}"
        res = requests.get(url_yahoo, headers=headers, timeout=5)
        
        # O Yahoo guarda links limpos e leves
        links = re.findall(r'src=["\'](https://tse\d\.mm\.bing\.net/th\?id=[^"\']+)["\']', res.text)
        
        if links:
            print("      ✅ Foto encontrada (Yahoo)!")
            return links[0]
    except Exception:
        pass

    # --- TENTATIVA 2: BING IMAGENS (Corrigido) ---
    try:
        url_bing = f"https://www.bing.com/images/search?q={query}"
        res = requests.get(url_bing, headers=headers, timeout=5)
        
        # O Bing pode esconder os links com código HTML (&quot;)
        links = re.findall(r'murl&quot;:&quot;(https?://[^&]+)&quot;', res.text)
        if not links:
            links = re.findall(r'"murl":"(https?://[^"]+)"', res.text)
            
        if links:
            print("      ✅ Foto encontrada (Bing)!")
            return links[0]
    except Exception:
        pass

    # --- FALHA ---
    print("      ❌ Nenhuma imagem disponível na web.")
    time.sleep(0.5)
    return "SEM IMAGEM"