from scrapers.base_scraper import BaseScraper
from scrapers.boa import extrair_dados as BoaScraper
from scrapers.atacadao import extrair_dados as AtacadaoScraper
from scrapers.carrefour import extrair_dados as CarrefourScraper
from scrapers.covabra import extrair_dados as CovabraScraper
from scrapers.oba import extrair_dados as ObaScraper
from scrapers.paodeacucar import extrair_dados as PaoDeAcucarScraper
from scrapers.roldao import baixar_encartes as RoldaoScraper
from scrapers.tauste import baixar_encartes as TausteScraper
from scrapers.tenda import baixar_encartes as TendaScraper
from scrapers.assai import baixar_encartes as AssaiScraper
from scrapers.svicente import extrair_dados as SVicenteScraper
from scrapers.fort import baixar_encartes as FortScraper

__all__ = [
    'BaseScraper', 'BoaScraper', 'AtacadaoScraper', 'CarrefourScraper', 
    'CovabraScraper', 'ObaScraper', 'PaoDeAcucarScraper', 'RoldaoScraper', 
    'TausteScraper', 'TendaScraper', 'AssaiScraper', 'SVicenteScraper', 'FortScraper'
]