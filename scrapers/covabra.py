import os
from datetime import datetime
from curl_cffi import requests
from utils import padronizar_categoria, extrair_medidas_inteligente, setup_logging, read_json_file, MAPA_PARA_APP, CATEGORIAS_IGNORADAS, formatar_nome_categoria

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

def obter_precos_simulados(session, skus, cep="13211745", qtd=3):
    """Simula um carrinho com `qtd` unidades para descobrir descontos (Clube ou Leve + Pague -)."""
    if not skus:
        return {}

    url_simulacao = "https://www.covabra.com.br/api/checkout/pub/orderForms/simulation?sc=1"
    
    payload = {
        "items": [{"id": str(sku), "quantity": qtd, "seller": "1"} for sku in skus],
        "country": "BRA",
        "postalCode": cep
    }

    try:
        res = session.post(url_simulacao, json=payload, timeout=30)
        if res.status_code == 200:
            dados = res.json()
            resultado = {}
            for item in dados.get('items', []):
                sku_id = str(item.get('id'))
                tags = item.get('priceTags', [])
                tag_name = tags[0].get('name', 'DESCONTO PROGRESSIVO') if tags else 'PROMOÇÃO ATIVA'
                
                resultado[sku_id] = {
                    'price': float(item.get('price', 0)) / 100,
                    'listPrice': float(item.get('listPrice', 0)) / 100,
                    'tag_name': tag_name
                }
            return resultado
    except Exception as e:
        logger.error(f"⚠️ Falha na simulação em lote: {e}")
    
    return {}

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
            logger.info(f"🎯 Rastreador {NOME_MERCADO} focado no Cluster: {cluster}")
            pagina = 0
            while True:
                try:
                    _from = pagina * PAGE_SIZE
                    _to = _from + PAGE_SIZE - 1
                    url_final = f"{URL_BASE}?fq=productClusterIds:{cluster}&_from={_from}&_to={_to}"
                    response = s.get(url_final, headers=headers, timeout=30)
                    
                    if response.status_code not in [200, 206]:
                        break

                    produtos_raw = response.json()
                    if not produtos_raw:
                        break

                    # --- SIMULAÇÃO DE CARRINHO (PULO DO GATO) ---
                    skus_pagina = []
                    for p in produtos_raw:
                        try:
                            sku = p.get('items', [{}])[0].get('itemId')
                            if sku: skus_pagina.append(str(sku))
                        except: pass
                    
                    dados_simulacao = obter_precos_simulados(s, skus_pagina, qtd=3)

                    for p in produtos_raw:
                        try:
                            nome_original = str(p.get('productName', '')).upper().strip()
                            if not nome_original: continue

                            # --- NOVA LÓGICA DE TAXONOMIA ---
                            categorias_vtex = p.get('categories', [])
                            cat_site = ""
                            subcategoria = "N/A"
                            tipo_produto = "N/A"

                            if categorias_vtex and isinstance(categorias_vtex, list) and categorias_vtex[0]:
                                partes_cat = categorias_vtex[0].strip('/').split('/')
                                if len(partes_cat) > 0: cat_site = partes_cat[0].upper()
                                if len(partes_cat) > 1: subcategoria = formatar_nome_categoria(partes_cat[1])
                                if len(partes_cat) > 2: tipo_produto = formatar_nome_categoria(partes_cat[2])
                            
                            if cat_site in CATEGORIAS_IGNORADAS:
                                continue

                            # Usa o contexto completo para uma categorização mais precisa, evitando erros da API de origem.
                            full_context = f"{nome_original} {cat_site} {subcategoria} {tipo_produto}"
                            categoria = padronizar_categoria(full_context, cat_site)
                            
                            nome_limpo, qv, med = extrair_medidas_inteligente(nome_original)

                            # Dados de Preço e Oferta
                            item = p.get('items', [{}])[0]
                            sku_id = str(item.get('itemId'))
                            seller = item.get('sellers', [{}])[0]
                            offer = seller.get('commertialOffer', {})
                            
                            p_venda = float(offer.get('Price', 0.0))
                            p_varejo = float(offer.get('ListPrice', p_venda))
                            
                            if p_venda <= 0: continue

                            p_atacado = p_venda
                            condicao = "OFERTA" if p_venda < p_varejo else "1 UN"

                            # Verifica desconto usando a simulação
                            sim_data = dados_simulacao.get(sku_id)
                            if sim_data:
                                p_sim_3 = sim_data['price']
                                p_lista = sim_data['listPrice']
                                tag_name = sim_data['tag_name']
                                
                                if p_sim_3 > 0 and p_sim_3 < p_lista:
                                    p_atacado = p_sim_3
                                    # Usa o nome da tag, ou fallback se for uma promoção
                                    if "PROGRESSIVO" in tag_name.upper():
                                        condicao = "A PARTIR DE 3 UN"
                                    elif "CLUBE" in tag_name.upper():
                                        condicao = "CLUBE"
                                    else:
                                        condicao = "A PARTIR DE 3 UN" # Padrão baseado no script do usuário

                            # Marca e Imagem
                            marca = str(p.get('brand', 'OUTROS')).upper()
                            img_url = item.get('images', [{}])[0].get('imageUrl', '')
                            
                            lista_final.append({
                                "Mercado": NOME_MERCADO,
                                "Categoria": categoria,
                                "subcategoria": subcategoria,
                                "tipo_produto": tipo_produto,
                                "Produto": nome_limpo,
                                "Marca": marca,
                                "Preço Varejo": f"R$ {p_varejo:.2f}".replace('.', ','),
                                "Preço Atacado": f"R$ {p_atacado:.2f}".replace('.', ','),
                                "Qtd_Valor": qv,
                                "Medida": med,
                                "Unidade": "UN",
                                "Condição": condicao,
                                "Validade": "VER NO SITE",
                                "Data_Hora": agora,
                                "Link_Imagem": img_url
                            })
                        except:
                            continue
                    
                    # Avança para a próxima página
                    pagina += 1
                except Exception as e:
                    logger.error(f"⚠️ Erro ao processar cluster {cluster} página {pagina} no {NOME_MERCADO}: {e}")
                    break

    lista_deduplicada = list({v['Produto']: v for v in lista_final}.values())
    
    logger.info(f"✅ {len(lista_deduplicada)} produtos capturados no {NOME_MERCADO}.")
    return lista_deduplicada