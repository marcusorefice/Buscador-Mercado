import os
import asyncio
import json
from datetime import datetime
from curl_cffi.requests import AsyncSession
from utils import (
    padronizar_categoria, 
    extrair_medidas_inteligente, 
    setup_logging, 
    read_json_file,
    MAPA_PARA_APP, CATEGORIAS_IGNORADAS,
    formatar_nome_categoria
)

logger = setup_logging()

# ==========================================
# CARREGAMENTO DAS CONFIGURAÇÕES (SPEC)
# ==========================================
SPEC_FILE = os.path.join(os.path.dirname(__file__), '..', 'specs', 'oba_spec.json')
CONFIG = read_json_file(SPEC_FILE)

# ==========================================
# CONFIGURAÇÕES DO OBA
# ==========================================
NOME_MERCADO = CONFIG.get("market_name", "Oba Hortifruti")
BASE_URL_CONFIG = CONFIG.get("base_url", "https://www.obahortifruti.com.br/").rstrip('/')
API_ENDPOINT = CONFIG.get("api_endpoint", "/api/catalog_system/pub/products/search")
API_CATALOGO = f"{BASE_URL_CONFIG}{API_ENDPOINT}"

CLUSTER_ID = CONFIG.get("regionalization", {}).get("cluster_id", "977")

PAGINATION = CONFIG.get("pagination", {})
PAGE_SIZE = PAGINATION.get("page_size", 50)
MAX_ITEMS = PAGINATION.get("max_items", 1500) # Aumentado de 600 para 1500

TECHNICAL_DEPS = CONFIG.get("technical_dependencies", {})
IMPERSONATE = TECHNICAL_DEPS.get("impersonation", "chrome120")
USER_AGENT = TECHNICAL_DEPS.get("user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
RATE_LIMIT_DELAY = TECHNICAL_DEPS.get("rate_limit_delay", 0.3)
 
BLACKLIST_RULE = next((rule for rule in CONFIG.get("special_rules", []) if isinstance(rule, dict) and rule.get("name") == "blacklist_terms"), {})
LISTA_NEGRA = BLACKLIST_RULE.get("values", [])

async def motor_extracao_oba():
    """
    Motor de Busca por Catálogo - Extrai condições dinâmicas, limpa termos 
    descritivos e aplica o fallback '1un' conforme a regra de negócio.
    """
    logger.info(f"🚀 Iniciando Varredura Completa - {NOME_MERCADO} Jundiaí...")
    lista_final = []
    agora = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
    
    passo = PAGE_SIZE - 1
    inicio = 0
    fim = passo

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }

    try:
        async with AsyncSession(impersonate=IMPERSONATE) as s:
            while inicio < MAX_ITEMS:
                params = {
                    "fq": f"productClusterIds:{CLUSTER_ID}",
                    "_from": str(inicio),
                    "_to": str(fim)
                }
                
                logger.info(f"📡 Coletando itens {inicio} até {fim}...")
                res = await s.get(API_CATALOGO, params=params, headers=headers, timeout=30)
                
                # Aceita 200 ou 206 (Partial Content padrão da VTEX para paginação)
                if res.status_code not in [200, 206]:
                    logger.error(f"❌ Falha na API: Status {res.status_code}")
                    break
                
                produtos_api = res.json()
                if not produtos_api:
                    logger.info("✅ Fim do catálogo alcançado.")
                    break

                for p in produtos_api:
                    try:
                        nome_bruto = p.get('productName', '').upper().strip()
                        if not nome_bruto: continue

                        items = p.get('items', [])
                        if not items: continue
                        sku = items[0]
                        
                        # --- LÓGICA DE EAN/GTIN ROBUSTA (do @teste.py) ---
                        # Prioriza 'gtin', depois 'ean' como fallback.
                        codigo_bruto = str(sku.get('gtin', '')).strip() or str(sku.get('ean', '')).strip()
                        
                        # Validação rigorosa: deve ser numérico e ter 12 (UPC-A) ou 13 (EAN-13) dígitos.
                        # Itens com código inválido terão EAN="N/A", mas ainda serão salvos.
                        if codigo_bruto.isdigit() and len(codigo_bruto) in [12, 13]:
                            ean = codigo_bruto
                        else:
                            ean = "N/A"

                        sellers = sku.get('sellers', [])
                        if not sellers: continue
                        
                        oferta = sellers[0].get('commertialOffer', {})
                        p_venda = float(oferta.get('Price', 0.0))
                        p_varejo = float(oferta.get('ListPrice', p_venda))

                        if p_venda <= 0: continue
                        if p_varejo < p_venda: p_varejo = p_venda

                        # --- CORREÇÃO DE UNIT MULTIPLIER (HORTIFRUTI VTEX) --- #
                        unit_multiplier = float(sku.get('unitMultiplier') or 1.0)
                        if unit_multiplier > 0 and unit_multiplier < 1.0:
                            if p_varejo > (p_venda * (1 / unit_multiplier) * 0.5): 
                                p_varejo = p_varejo * unit_multiplier
                            else:
                                p_varejo = p_varejo * unit_multiplier
                                p_venda = p_venda * unit_multiplier

                        marca = p.get('brand', 'PRÓPRIA').upper()

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
                        full_context = f"{nome_bruto} {cat_site} {subcategoria} {tipo_produto}"
                        categoria = padronizar_categoria(full_context, cat_site)

                        # --- LÓGICA DE FILTRAGEM DE CONDIÇÕES ---
                        condicoes_uteis = []
                        
                        # 1. Highlights (Etiquetas de imagem como 'PREÇO VERDE')
                        highlights = p.get('clusterHighlights', {})
                        if highlights:
                            for cname in highlights.values():
                                termo = str(cname).upper().strip()
                                if not any(lixo in termo for lixo in LISTA_NEGRA):
                                    condicoes_uteis.append(termo)
                        
                        # 2. Teasers (Promoções tipo 'Leve 2 Pague 1')
                        teasers = oferta.get('Teasers', [])
                        for t in teasers:
                            nome_promo = t.get('Name', '').upper().strip()
                            if nome_promo and not any(lixo in nome_promo for lixo in LISTA_NEGRA):
                                condicoes_uteis.append(nome_promo)
                        
                        # 3. Clusters (Categorização técnica interna)
                        clusters = p.get('productClusters', {})
                        if isinstance(clusters, dict):
                            for cname in clusters.values():
                                termo = str(cname).upper().strip()
                                if not any(lixo in termo for lixo in LISTA_NEGRA):
                                    condicoes_uteis.append(termo)

                        # --- DEFININDO A CONDIÇÃO FINAL ---
                        condicao = "1 UN"
                        
                        # Prioridade 1: "NA COMPRA DE X" ou "A PARTIR DE X"
                        encontrou_promo_qtd = False
                        for tag in condicoes_uteis:
                            if "NA COMPRA DE" in tag or "A PARTIR DE" in tag:
                                condicao = tag
                                encontrou_promo_qtd = True
                                break
                                
                        # Prioridade 2: MINHA HORA OBA (Clube de descontos com CPF)
                        if not encontrou_promo_qtd:
                            for tag in condicoes_uteis:
                                if "MINHA HORA OBA" in tag:
                                    condicao = "MINHA HORA OBA (CPF)"
                                    break

                        txt_condicao = condicao

                        # Imagem e Unidade
                        img_url = sku.get('images', [{}])[0].get('imageUrl', '')
                        
                        nome_limpo, qv, med = extrair_medidas_inteligente(nome_bruto)

                        # A unidade de venda será definida com base na medida extraída, e refinada no motor de validação.
                        unidade_venda = "KG" if med == "KG" else "UN"
                        measurement_unit = str(sku.get('measurementUnit', '')).lower()
                        
                        if measurement_unit == 'kg':
                            unidade_venda = "KG"
                            if qv == "1" and med == "UN":
                                qv, med = "1", "KG"
                                
                        if nome_bruto.endswith(" KG"):
                            unidade_venda = "KG"
                            if qv == "1" and med == "UN":
                                qv, med = "1", "KG"
                                
                        nome_limpo = re.sub(r'\s*KG$', '', nome_limpo, flags=re.IGNORECASE).strip()

                        link_pdp_rel = p.get('linkText') or p.get('link') or p.get('url') or ''
                        if link_pdp_rel:
                            if link_pdp_rel.startswith('http'):
                                link_pdp = link_pdp_rel
                            elif link_pdp_rel.startswith('/'):
                                link_pdp = f"https://www.obahortifruti.com.br{link_pdp_rel}"
                            else:
                                link_pdp = f"https://www.obahortifruti.com.br/{link_pdp_rel}/p"
                        else:
                            link_pdp = ""

                        lista_final.append({
                            "Mercado": NOME_MERCADO,
                            "EAN": ean,
                            "Categoria": categoria,
                            "subcategoria": subcategoria,
                            "tipo_produto": tipo_produto,
                            "Produto": nome_limpo,
                            "Marca": marca,
                            "Preço Varejo": f"R$ {p_varejo:.2f}".replace('.', ','),
                            "Preço Atacado": f"R$ {p_venda:.2f}".replace('.', ','),
                            "Qtd_Valor": qv,
                            "Medida": med,
                            "Unidade": unidade_venda,
                            "Condição": txt_condicao, "Data_Hora": agora,
                            "Link_Imagem": img_url,
                            "Link_PDP": link_pdp
                        })
                    except Exception:
                        continue

                # Avança os ponteiros de paginação
                inicio += passo + 1
                fim += passo + 1
                await asyncio.sleep(RATE_LIMIT_DELAY)

    except Exception as e:
        logger.error(f"❌ Erro crítico no motor Oba: {e}")

    # Remove duplicados por nome de produto
    lista_unica = list({f"{v.get('Produto','')}_{v.get('Marca','')}_{v.get('Qtd_Valor','')}_{v.get('Medida','')}": v for v in lista_final}.values())
    logger.info(f"🏆 Finalizado! {len(lista_unica)} ofertas únicas capturadas com sucesso.")
    return lista_unica

async def extrair_dados():
    """Ponto de entrada para o orquestrador síncrono"""
    return await motor_extracao_oba()