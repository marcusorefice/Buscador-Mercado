import unittest
from utils import normalizar_taxonomia_grabit

class TestTaxonomiaErros(unittest.TestCase):
    def setUp(self):
        self.biblioteca_mock = {}

    def _testar(self, nome_produto, cat_esperada):
        cat, sub, tipo = normalizar_taxonomia_grabit(
            nome_produto=nome_produto,
            marca="",
            categoria_mercado="",
            subcategoria_mercado="",
            tipo_produto_mercado="",
            ean="N/A",
            biblioteca=self.biblioteca_mock
        )
        self.assertEqual(cat, cat_esperada, f"❌ Categoria falhou: '{nome_produto}'. Esp: {cat_esperada}, Obt: {cat}")

    def test_erros_recentes(self):
        self._testar("SACHÊ DOG CHOW CARNE", "Pet Shop")
        self._testar("PRATO DESCARTÁVEL BIO TRIK", "Bazar e Utilidades")
        self._testar("PRATO RASO FESTA FÁCIL", "Bazar e Utilidades")
        self._testar("VINAGRE DE ÁLCOOL PEIXE", "Mercearia e Despensa")
        self._testar("TOALHA DE PAPEL COQUETEL", "Limpeza")
        self._testar("LIMPADOR COALA CHÁ BRANCO", "Limpeza")
        self._testar("PROTEÍNA DE SOJA CAMIL", "Mercearia e Despensa")
        self._testar("PAPEL SULFITE REPORT A4", "Bazar e Utilidades")
        self._testar("BEBIDA ALCOÓLICA BEATS", "Bebidas Alcoólicas")
        self._testar("SMIRNOFF ICE LIMÃO", "Bebidas Alcoólicas")
        self._testar("CHÁ ICE TEA LEÃO PÊSSEGO", "Bebidas")
        self._testar("SABÃO EM PASTA ASSOLAN", "Limpeza")
        self._testar("ÁGUA TÔNICA SCHWEPPES", "Bebidas")

if __name__ == "__main__":
    unittest.main(verbosity=2)