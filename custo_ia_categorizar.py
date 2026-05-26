import os
import json
import asyncio
from google import genai
from dotenv import load_dotenv

load_dotenv()

# Configuração do Cliente (Usando sua lógica de chaves)
API_KEY = os.getenv("GEMINI_API_KEYS", "").split(',')[0].strip().strip('"')
client = genai.Client(api_key=API_KEY)

# Lista de 10 produtos (Misturando itens fáceis e os que falharam na API gratuita)
produtos_teste = [
    "NUTELLA CREME DE AVELA 350G",
    "BOMBOM GAROTO SORTIDO 250G",
    "MACARRÃO COM OVOS BULNEZ ESPAGUETE 500G",
    "LEITE CONDENSADO MILK + SEMIDESNATADO 395G",
    "MOLHO DE TOMATE QUERO TRADICIONAL SACHE 300G",
    "ARROZ EXTREMO SUL AGULHINHA TIPO 1 5KG",
    "PESSEGO EM CALDA LA FAMIGLIA 400G",
    "SHAMPOO PANTENE RESTAURACAO 400ML",
    "DETERGENTE YPE CLEAR 500ML",
    "CERVEJA HEINEKEN LATA 350ML"
]

# Seu padrão de Prompt
PROMPT_SISTEMA = """Você é um assistente especialista em supermercados. Classifique os produtos abaixo.
Retorne APENAS um JSON onde as chaves são os nomes dos produtos.
Categorias válidas: Açougue e Peixaria, Bebidas, Bebidas Alcoólicas, Congelados e Pratos Prontos, Frios e Laticínios, Higiene e Cuidado Pessoal, Hortifrúti, Limpeza, Mercearia e Despensa, Padaria e Confeitaria, Pet Shop, Bebê e Infantil."""

async def testar_custo_gemini():
    print(f"🚀 Enviando {len(produtos_teste)} produtos para o Gemini...")
    
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=f"{PROMPT_SISTEMA}\n\nProdutos: {json.dumps(produtos_teste)}"
        )

        # 1. Analisando o Custo (Tokens)
        uso = response.usage_metadata
        print("\n" + "="*30)
        print("📊 RELATÓRIO DE CONSUMO")
        print("="*30)
        print(f"Tokens de Entrada: {uso.prompt_token_count}")
        print(f"Tokens de Saída: {uso.candidates_token_count}")
        print(f"Total de Tokens: {uso.total_token_count}")
        # Estimativa de custo aproximada para 2.0 Flash
        custo_est = (uso.total_token_count / 1_000_000) * 0.10 
        print(f"Custo Estimado (USD): ${custo_est:.6f}")
        print("="*30)

        # 2. Exibindo a Formatação
        print("\n📦 DADOS FORMATADOS (PADRÃO GRABIT):")
        dados_json = json.loads(response.text.replace('```json', '').replace('```', ''))
        print(json.dumps(dados_json, indent=4, ensure_ascii=False))

    except Exception as e:
        print(f"❌ Erro na chamada: {e}")

if __name__ == "__main__":
    asyncio.run(testar_custo_gemini())