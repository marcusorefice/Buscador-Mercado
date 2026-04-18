from google import genai
import json
import os
import re
import unicodedata
from dotenv import load_dotenv
from utils import setup_logging, read_json_file, write_json_file

load_dotenv()
api_key = os.getenv("GEMINI_API_KEYS", "").split(',')[0].strip().strip('"').strip("'")
if api_key:
    client = genai.Client(api_key=api_key)

logger = setup_logging()

# Arquivo agora se chama biblioteca para refletir que guarda Categoria + Imagem
CACHE_FILE = "biblioteca_produtos.json"

def carregar_biblioteca():
    return read_json_file(CACHE_FILE, default_value={})

def salvar_biblioteca(nova_biblioteca):
    write_json_file(CACHE_FILE, nova_biblioteca)

def normalizar_para_cache(nome):
    if not nome: return ""
    nfkd = unicodedata.normalize('NFKD', str(nome).lower())
    texto = "".join([c for c in nfkd if not unicodedata.combining(c)])
    texto = re.sub(r'\d+(?:[.,]\d+)?\s*(KG|G|ML|L|UN|M|ROLOS|FLS|CAPS|UNIDADES|MT|POTS|GR)', '', texto, flags=re.IGNORECASE)
    texto = re.sub(r'[^a-z0-9\s]', '', texto)
    return " ".join(texto.split())

def resolver_geral_com_ia(lista_produtos):
    """
    Classifica itens novos e alimenta a biblioteca com a categoria.
    """
    if not lista_produtos: return {}

    biblioteca = carregar_biblioteca()
    resultado_final = {}
    sobras_reais = {}

    for p in lista_produtos:
        chave = normalizar_para_cache(p)
        # Verifica se o produto já existe na biblioteca e se possui uma categoria válida
        if chave in biblioteca and "categoria" in biblioteca[chave]:
            resultado_final[p] = biblioteca[chave]['categoria']
        else:
            sobras_reais[p] = chave

    if not sobras_reais: return resultado_final

    print(f"🧠 IA classificando {len(sobras_reais)} itens novos...")
    prompt = f"""
    Classifique estes produtos nestas categorias: BEBIDAS, MERCEARIA, LIMPEZA, HIGIENE E BELEZA, FRIOS E LATICÍNIOS, PADARIA, CONGELADOS, PET SHOP, AÇOUGUE, HORTIFRUTI, BAZAR.
    Produtos: {", ".join(sobras_reais.keys())}
    Retorne apenas JSON puro: {{"NOME": "CATEGORIA"}}
    """

    try:
        if not api_key:
            logger.error("Chave da API Gemini não configurada no .env. Pulando classificação de IA.")
            return resultado_final
            
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )
        txt = response.text.strip()
        
        # Limpa formatação markdown caso a IA responda com blocos de código
        if "```json" in txt: 
            txt = txt.split("```json")[-1].split("```")[0].strip()
        elif "```" in txt:
            txt = txt.replace("```", "").strip()
            
        novas_cats = json.loads(txt)

        for prod_ia, cat in novas_cats.items():
            cat_upper = cat.upper()
            chave = normalizar_para_cache(prod_ia)
            
            # Se for um produto inédito, cria a estrutura com imagem vazia para ser preenchida depois
            if chave not in biblioteca:
                biblioteca[chave] = {"categoria": cat_upper, "imagem": "SEM IMAGEM"}
            else:
                biblioteca[chave]["categoria"] = cat_upper
            
            # Associa a resposta da IA com o nome original do produto
            for prod_orig, chave_orig in sobras_reais.items():
                if chave == chave_orig or prod_ia.upper() in prod_orig.upper():
                    resultado_final[prod_orig] = cat_upper
                    break

        salvar_biblioteca(biblioteca)
        return resultado_final
        
    except Exception as e:
        logger.error(f"⚠️ Erro IA: {e}")
        return resultado_final