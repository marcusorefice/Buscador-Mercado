import asyncio
import os
from abc import ABC, abstractmethod
from datetime import datetime
from utils import setup_logging

logger = setup_logging()

class BaseScraper(ABC):
    """
    Classe base abstrata para todos os scrapers de supermercado.
    Define uma interface comum e fornece funcionalidades básicas.
    """
    def __init__(self, nome_mercado: str):
        if not nome_mercado:
            raise ValueError("O nome do mercado não pode ser vazio.")
        self.nome_mercado = nome_mercado
        self.agora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        logger.info(f"Scraper para '{self.nome_mercado}' inicializado.")

    @abstractmethod
    async def _executar(self) -> list:
        """
        Método de extração principal e abstrato.
        Cada scraper filho DEVE implementar sua própria lógica de coleta de dados
        aqui e retornar uma lista de produtos.
        """
        pass

    def extrair_dados(self) -> list:
        """
        Ponto de entrada síncrono para o orquestrador (main.py).
        Configura o loop de eventos e executa o motor assíncrono.
        """
        logger.info(f"🚀 Iniciando extração para {self.nome_mercado}...")
        print(f"\n🚀 Iniciando extração para {self.nome_mercado}...")
        
        if os.name == 'nt':
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        
        try:
            resultados = asyncio.run(self._executar())
            
            if not resultados:
                logger.warning(f"⚠️ Nenhuma oferta encontrada para {self.nome_mercado}.")
                print(f"   ⚠️ Nenhuma oferta encontrada para {self.nome_mercado}.")
                return []

            return resultados
        except Exception as e:
            logger.error(f"❌ Erro crítico durante a extração de {self.nome_mercado}: {e}", exc_info=True)
            print(f"   ❌ Erro crítico durante a extração de {self.nome_mercado}: {e}")
            return []