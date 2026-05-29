import json
from curl_cffi import requests

def mapear_categorias_boa():
    base_url = "https://www.boasupermercados.com.br"
    # O número "3" no final da URL define a profundidade da busca (Departamentos > Categorias > Subcategorias)
    api_url = f"{base_url}/api/catalog_system/pub/category/tree/3"
    
    headers = {
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    }

    print("🔍 Consultando a árvore de categorias do Boa Supermercados...")
    
    try:
        # O impersonate ajuda a passar direto por eventuais bloqueios de firewall (WAF)
        resposta = requests.get(api_url, headers=headers, impersonate="chrome124", timeout=20)
        
        if resposta.status_code != 200:
            print(f"❌ Erro ao acessar a API: Status HTTP {resposta.status_code}")
            return

        dados = resposta.json()
        
        print("\n✅ Estrutura de Categorias Encontrada:\n" + "="*50)
        
        for depto in dados:
            nome_depto = depto.get("name", "")
            # Limpa o domínio principal para deixar só o caminho útil
            slug_depto = depto.get("url", "").replace(base_url, "").strip("/")
            print(f"\n📂 {nome_depto.upper()} (/{slug_depto})")
            
            for sub in depto.get("children", []):
                nome_sub = sub.get("name", "")
                slug_sub = sub.get("url", "").replace(base_url, "").strip("/")
                print(f"   ├── {nome_sub} -> /{slug_sub}")
                
    except Exception as e:
        print(f"❌ Falha na requisição: {e}")

if __name__ == "__main__":
    mapear_categorias_boa()