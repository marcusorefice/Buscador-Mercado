import os
import json
import re
import asyncio
from datetime import datetime
from PIL import Image, UnidentifiedImageError
from google import genai
from utils import setup_logging, clean_price_string, padronizar_categoria, extrair_medidas_inteligente

logger = setup_logging()

# Prompt ultra reduzido para economizar tokens de entrada e saída
PROMPT_OTIMIZADO = """Extraia 100% das ofertas desta imagem. 
Responda APENAS um array JSON compacto.
Chaves: p (produto), m (marca), pv (preço varejo), pa (preço atacado), cd (condição para o preço 'pa'), v (validade).
Não use markdown ou explicações.
Ex: [{"p":"ARROZ 5KG","m":"TIO JOAO","pv":29.90,"pa":27.50,"cd":"CLUBE","v":"20/04"}]"""

# --- NOVO: Diretório para cachear as respostas JSON da IA ---
JSON_CACHE_DIR = "temp_json_cache"
os.makedirs(JSON_CACHE_DIR, exist_ok=True)

class MotorIA:
    def __init__(self, lista_chaves):
        if not lista_chaves:
            logger.critical("Lista de chaves vazia.")
            raise ValueError("Chaves da API não fornecidas.")
        
        self.lista_chaves = lista_chaves
        self.indice_chave_atual = 0
        self.client = genai.Client(api_key=self.lista_chaves[self.indice_chave_atual])
        self._key_lock = asyncio.Lock()
        logger.info(f"Motor de IA inicializado com {len(self.lista_chaves)} chaves.")

    async def _trocar_chave(self):
        """Rotaciona a chave da API. Uma vez que chega nas chaves pagas (2 últimas), não volta para as gratuitas."""
        async with self._key_lock:
            num_chaves = len(self.lista_chaves)
            if num_chaves <= 2: # Se só tem chaves pagas ou menos, faz o ciclo normal
                self.indice_chave_atual = (self.indice_chave_atual + 1) % num_chaves
            else:
                num_chaves_pagas = 2
                primeiro_indice_pago = num_chaves - num_chaves_pagas

                # Se a chave atual já é uma das pagas
                if self.indice_chave_atual >= primeiro_indice_pago:
                    # Calcula o próximo índice dentro do bloco de chaves pagas
                    indice_relativo = (self.indice_chave_atual - primeiro_indice_pago + 1) % num_chaves_pagas
                    self.indice_chave_atual = primeiro_indice_pago + indice_relativo
                    logger.warning("Permanecendo em chaves pagas para garantir a operação.")
                else:
                    # Avança normalmente pelas chaves gratuitas até chegar nas pagas
                    self.indice_chave_atual += 1
                    if self.indice_chave_atual >= primeiro_indice_pago:
                        logger.warning("Chaves gratuitas esgotadas. Escalando para chaves pagas.")

            nova_chave = self.lista_chaves[self.indice_chave_atual]
            self.client = genai.Client(api_key=nova_chave)
            logger.info(f"🔄 Alternando para a chave API de índice {self.indice_chave_atual}")

    async def _processar_imagem_async(self, caminho_imagem, nome_mercado):
        """Worker que processa a imagem com escala de cinza e redimensionamento."""
        nome_arq = os.path.basename(caminho_imagem)
        caminho_cache_json = None

        # --- LÓGICA DE CACHE DE JSON (LEITURA) ---
        try:
            tamanho_arquivo = os.path.getsize(caminho_imagem)
            nome_cache_json = f"{os.path.splitext(nome_arq)[0]}_{tamanho_arquivo}.json"
            caminho_cache_json = os.path.join(JSON_CACHE_DIR, nome_cache_json)

            if os.path.exists(caminho_cache_json):
                logger.info(f"   CACHE JSON HIT: Usando resposta da IA de '{os.path.basename(caminho_cache_json)}'")
                with open(caminho_cache_json, 'r', encoding='utf-8') as f:
                    return self._estruturar_resposta(json.load(f), nome_mercado)
        except Exception as e:
            logger.warning(f"Não foi possível usar o cache JSON para {nome_arq}: {e}")

        logger.info(f"   CACHE JSON MISS: {nome_arq} será processado pela IA.")

        try:
            # OTMIZAÇÃO: Abre e converte para Escala de Cinza (Preto e Branco)
            with Image.open(caminho_imagem) as raw_img:
                img = raw_img.convert('L')
                # Otimização de tamanho (Aumentado para 3000px para melhorar OCR de folhetos densos)
                max_size = 3000
                if max(img.size) > max_size:
                    img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
        except Exception as e:
            logger.error(f"Erro ao preparar imagem {nome_arq}: {e}")
            return []

        # Tenta processar usando as chaves disponíveis
        for tentativa in range(len(self.lista_chaves)):
            try:
                response = self.client.models.generate_content(
                    model='models/gemini-2.5-flash-image',
                    contents=[PROMPT_OTIMIZADO, img]
                )

                if not response.text:
                    raise ValueError("Resposta vazia da IA.")

                texto = response.text.strip()
                texto = re.sub(r'```json\s*|```', '', texto)
                
                dados_json = json.loads(texto) # Valida se o JSON é válido

                # --- LÓGICA DE CACHE DE JSON (ESCRITA) ---
                if caminho_cache_json:
                    try:
                        with open(caminho_cache_json, 'w', encoding='utf-8') as f:
                            json.dump(dados_json, f, ensure_ascii=False, indent=2)
                        logger.debug(f"   CACHE JSON WRITE: Resposta da IA salva em '{os.path.basename(caminho_cache_json)}'")
                    except Exception as e:
                        logger.warning(f"Não foi possível salvar a resposta da IA no cache JSON: {e}")
                
                return self._estruturar_resposta(dados_json, nome_mercado)

            except Exception as e:
                erro_msg = str(e).upper()
                if any(err in erro_msg for err in ["429", "QUOTA", "EXHAUSTED", "503", "UNAVAILABLE"]):
                    logger.warning(f"Cota/Disponibilidade esgotada na chave {self.indice_chave_atual}. Tentando próxima...")
                    await self._trocar_chave()
                else:
                    logger.error(f"Erro inesperado na IA ({nome_arq}): {e}")
                    await self._trocar_chave()
        
        logger.error(f"FALHA GERAL: Nenhuma chave da API conseguiu processar a imagem {nome_arq} após {len(self.lista_chaves)} tentativas.")
        return []

    def _estruturar_resposta(self, dados_json, nome_mercado):
        """Transforma o JSON enxuto no formato completo da planilha."""
        lista_formatada = []
        agora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

        if not isinstance(dados_json, list):
            dados_json = [dados_json]

        for item in dados_json:
            try:
                # Mapeamento das chaves curtas (p, m, pv, pa, cd, v)
                p_bruto = str(item.get("p", "")).upper().strip()
                marca = str(item.get("m", "")).upper().strip()
                if marca in ["", "NONE", "N/A", "NAN"]: marca = "PRÓPRIA"

                # Categorização LOCAL (Economiza Tokens da IA)
                # Usa a junção de nome e marca para uma categoria mais precisa
                nome_para_categoria = f"{p_bruto} {marca}".strip()
                categoria = padronizar_categoria(nome_para_categoria)
                
                # Limpa o nome do produto (p_bruto) para extrair medidas, sem a marca.
                nome_limpo, qv, med = extrair_medidas_inteligente(p_bruto)

                # Preços: lógica aprimorada para não mascarar dados ausentes
                p_varejo = clean_price_string(item.get("pv", 0)) # Passa 0 se 'pv' não existir
                p_atacado = clean_price_string(item.get("pa", 0)) # Passa 0 se 'pa' não existir

                # Se o preço de atacado não existir, preenche com o preço de varejo
                if p_atacado == 0:
                    p_atacado = p_varejo

                # Se o preço de atacado foi encontrado mas o de varejo não, o varejo é no mínimo igual ao atacado.
                if p_atacado > 0 and p_varejo == 0:
                    p_varejo = p_atacado
                
                # Garante que o preço de atacado (promocional) seja sempre menor ou igual ao de varejo.
                if p_atacado > p_varejo and p_varejo > 0:
                    p_varejo, p_atacado = p_atacado, p_varejo # Inverte se a IA se confundiu

                # Tratamento especial para a condição do cartão Vuon
                condicao = str(item.get("cd", "1 UN")).upper()
                if "VUON" in condicao:
                    condicao = "VUON CARD"

                lista_formatada.append({
                    "Mercado": nome_mercado,
                    "Categoria": categoria,
                    "subcategoria": "N/A",
                    "tipo_produto": "N/A",
                    "Produto": nome_limpo, # Agora sem a marca
                    "Marca": marca,
                    "Preço Varejo": f"R$ {p_varejo:.2f}".replace('.', ','),
                    "Preço Atacado": f"R$ {p_atacado:.2f}".replace('.', ','),
                    "Qtd_Valor": qv,
                    "Medida": med,
                    "Unidade": "UN",
                    "Condição": condicao,
                    "Validade": str(item.get("v", "VER ENCARTE")).upper(),
                    "Data_Hora": item.get("data_hora", agora), # Mantém consistência se vier do cache
                    "Link_Imagem": "SEM IMAGEM"
                })
            except Exception as e:
                logger.error(f"Erro ao estruturar item: {e}")
                continue
                
        return lista_formatada

    async def processar_imagens_em_lote_async(self, lista_imagens, nome_mercado, concorrencia=3):
        """Processa o lote de imagens de forma assíncrona, integrando-se a um loop de eventos existente."""
        # Semáforo para não estourar o limite de requisições por segundo (RPM)
        semaforo = asyncio.Semaphore(concorrencia)
        
        async def worker(caminho):
            async with semaforo:
                return await self._processar_imagem_async(caminho, nome_mercado)

        tarefas = [worker(img) for img in lista_imagens]
        resultados = await asyncio.gather(*tarefas)
        
        # Achata a lista
        return [p for sublist in resultados for p in sublist]

    def processar_imagens_em_lote(self, lista_imagens, nome_mercado, concorrencia=3):
        """Wrapper síncrono para manter a compatibilidade. Inicia e fecha um novo loop de eventos."""
        async def main():
            return await self.processar_imagens_em_lote_async(lista_imagens, nome_mercado, concorrencia)

        # Configuração para Windows
        if os.name == 'nt':
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        
        return asyncio.run(main())