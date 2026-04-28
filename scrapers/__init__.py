import sys
import os

# Adiciona o diretório raiz do projeto ao sys.path para permitir importações de módulos como 'utils'.
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from scrapers.base_scraper import BaseScraper
from scrapers.boa import extrair_dados as BoaScraper
from scrapers.atacadao import extrair_dados as AtacadaoScraper
from scrapers.carrefour import extrair_dados as CarrefourScraper
from scrapers.covabra import extrair_dados as CovabraScraper
from scrapers.oba import extrair_dados as ObaScraper
from scrapers.paodeacucar import extrair_dados as PaoDeAcucarScraper
from scrapers.roldao import extrair_dados as RoldaoScraper
from scrapers.tauste import extrair_dados as TausteScraper
from scrapers.tenda import extrair_dados as TendaScraper
from scrapers.assai import extrair_dados as AssaiScraper
from scrapers.svicente import extrair_dados as SVicenteScraper
from scrapers.fort import extrair_dados as FortScraper

__all__ = [
    'BaseScraper', 'BoaScraper', 'AtacadaoScraper', 'CarrefourScraper', 
    'CovabraScraper', 'ObaScraper', 'PaoDeAcucarScraper', 'RoldaoScraper', 
    'TausteScraper', 'TendaScraper', 'AssaiScraper', 'SVicenteScraper', 'FortScraper'
]