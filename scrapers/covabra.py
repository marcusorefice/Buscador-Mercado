import os
from datetime import datetime
from curl_cffi import requests
from utils import padronizar_categoria, extrair_medidas_inteligente, setup_logging, read_json_file

logger = setup_logging()

# ==========================================
# CARREGAMENTO DAS CONFIGURAÇÕES (SPEC)
# ==========================================
SPEC_FILE = os.path.join(os.path.dirname(__file__), '..', 'specs', 'covabra_spec.json')
CONFIG = read_json_file(SPEC_FILE)

# ==========================================
# CONFIGURAÇÕES DO COVABRA
# ==========================================
NOME_MERCADO = CONFIG.get("market_name", "Covabra")
BASE_URL_CONFIG = CONFIG.get("base_url", "https://www.covabra.com.br/").rstrip('/')
API_ENDPOINT = CONFIG.get("api_endpoint", "/api/catalog_system/pub/products/search")
URL_BASE = f"{BASE_URL_CONFIG}{API_ENDPOINT}"

CLUSTERS_ALVO = CONFIG.get("regionalization", {}).get("clusters_alvo", [])
PAGE_SIZE = CONFIG.get("pagination", {}).get("page_size", 50)

TECHNICAL_DEPS = CONFIG.get("technical_dependencies", {})
IMPERSONATE = TECHNICAL_DEPS.get("impersonation", "chrome110")
USER_AGENT = TECHNICAL_DEPS.get("user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")

def extrair_dados():
    """Motor de extração para o Covabra."""
    logger.info(f"🚀 Iniciando extração para {NOME_MERCADO} Jundiaí...")
    lista_final = []
    agora = datetime.now().strftime('%d/%m/%Y %H:%M:%S')

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json"
    }

    with requests.Session(impersonate=IMPERSONATE) as s:
        for cluster in CLUSTERS_ALVO:
            try:
                logger.info(f"🎯 Rastreador {NOME_MERCADO} focado no Cluster: {cluster}")
                url_final = f"{URL_BASE}?fq=productClusterIds:{cluster}&_from=0&_to={PAGE_SIZE - 1}"
                response = s.get(url_final, headers=headers, timeout=30)
                
                if response.status_code not in [200, 206]:
                    continue

                produtos_raw = response.json()
                if not produtos_raw:
                    continue

                for p in produtos_raw:
                    try:
                        nome_original = str(p.get('productName', '')).upper().strip()
                        if not nome_original: continue

                        categorias_vtex = p.get('categories', [])
                        cat_site = categorias_vtex[0].split('/')[-2] if categorias_vtex else ""
                        
                        categoria_final = padronizar_categoria(nome_original, cat_site)
                        nome_limpo, qv, med = extrair_medidas_inteligente(nome_original)

                        # Dados de Preço e Oferta
                        item = p.get('items', [{}])[0]
                        seller = item.get('sellers', [{}])[0]
                        offer = seller.get('commertialOffer', {})
                        
                        p_venda = float(offer.get('Price', 0.0))
                        p_varejo = float(offer.get('ListPrice', p_venda))
                        
                        if p_venda <= 0: continue

                        # Marca e Imagem
                        marca = str(p.get('brand', 'OUTROS')).upper()
                        img_url = item.get('images', [{}])[0].get('imageUrl', '')

                        lista_final.append({
                            "Mercado": NOME_MERCADO,
                            "Categoria": categoria_final,
                            "Produto": nome_limpo,
                            "Marca": marca,
                            "Preço Varejo": f"R$ {p_varejo:.2f}".replace('.', ','),
                            "Preço Atacado": f"R$ {p_venda:.2f}".replace('.', ','),
                            "Qtd_Valor": qv,
                            "Medida": med,
                            "Unidade": "UN",
                            "Condição": "OFERTA",
                            "Validade": "VER NO SITE",
                            "Data_Hora": agora,
                            "Link_Imagem": img_url
                        })
                    except:
                        continue
            except Exception as e:
                logger.error(f"⚠️ Erro ao processar cluster {cluster} no {NOME_MERCADO}: {e}")
                continue

    lista_deduplicada = list({v['Produto']: v for v in lista_final}.values())
    
    logger.info(f"✅ {len(lista_deduplicada)} produtos capturados no {NOME_MERCADO}.")
    return lista_deduplicada