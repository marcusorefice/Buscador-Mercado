import unittest
from utils import normalizar_taxonomia_grabit

class TestTaxonomiaLimpeza(unittest.TestCase):
    def setUp(self):
        # Simulando uma biblioteca de produtos vazia para forçar o motor a usar as regras lógicas
        self.biblioteca_mock = {}

    def _testar_taxonomia(self, nome_produto, cat_esperada, sub_esperada, tipo_esperado):
        # Chama a função de taxonomia ignorando a taxonomia do mercado (tudo vazio/N/A)
        cat, sub, tipo = normalizar_taxonomia_grabit(
            nome_produto=nome_produto,
            marca="",
            categoria_mercado="",
            subcategoria_mercado="",
            tipo_produto_mercado="",
            ean="N/A",
            biblioteca=self.biblioteca_mock
        )
        
        self.assertEqual(cat, cat_esperada, f"❌ Falha na Categoria para: '{nome_produto}'. Esperado: {cat_esperada}, Obtido: {cat}")
        self.assertEqual(sub, sub_esperada, f"❌ Falha na Subcategoria para: '{nome_produto}'. Esperado: {sub_esperada}, Obtido: {sub}")
        if tipo_esperado:
            self.assertEqual(tipo, tipo_esperado, f"❌ Falha no Tipo para: '{nome_produto}'. Esperado: {tipo_esperado}, Obtido: {tipo}")

    def test_limpeza_de_roupas(self):
        # Estes caem na Trava de Alta Prioridade (Regra OMO / Sabão)
        self._testar_taxonomia("SABÃO EM PÓ OMO LAVAGEM PERFEITA", "Limpeza", "Cuidado com as Roupas", "Sabão em Pó")
        self._testar_taxonomia("LAVA ROUPAS TIXAN YPÊ", "Limpeza", "Cuidado com as Roupas", "Sabão em Pó")
        
        # AMACIANTE cai na Trava de Limpeza ("Limpeza", "Geral", "Limpeza")
        self._testar_taxonomia("AMACIANTE DOWNY 2L", "Limpeza", "Geral", "Limpeza")
        
        # Cai na ANCHOR_RULES e o mapa renomeia para "Cuidado com as Roupas"
        self._testar_taxonomia("ALVEJANTE SEM CLORO", "Limpeza", "Cuidado com as Roupas", "Geral")
        self._testar_taxonomia("TIRA-MANCHAS VANISH", "Limpeza", "Cuidado com as Roupas", "Geral")

    def test_limpeza_de_cozinha(self):
        # DETERGENTE cai na Trava de Limpeza ("Limpeza", "Geral", "Limpeza")
        self._testar_taxonomia("DETERGENTE LÍQUIDO YPÊ", "Limpeza", "Geral", "Limpeza")
        
        # Estes caem na ANCHOR_RULES e o mapa renomeia para "Cozinha e Utensílios"
        self._testar_taxonomia("ESPONJA DE AÇO ASSOLAN", "Limpeza", "Cozinha e Utensílios", "Geral")
        self._testar_taxonomia("DESENGORDURANTE CIF", "Limpeza", "Cozinha e Utensílios", "Geral")

    def test_limpeza_geral_e_banheiro(self):
        # DESINFETANTE cai na Trava de Limpeza ("Limpeza", "Geral", "Limpeza")
        self._testar_taxonomia("DESINFETANTE PINHO SOL", "Limpeza", "Geral", "Limpeza")
        
        # Caem na ANCHOR_RULES em "Limpeza Geral e Banheiro"
        self._testar_taxonomia("LIMPADOR MULTIUSO VEJA", "Limpeza", "Limpeza Geral e Banheiro", "Geral")
        self._testar_taxonomia("ÁLCOOL LÍQUIDO 70%", "Limpeza", "Limpeza Geral e Banheiro", "Geral")
        self._testar_taxonomia("ÁGUA SANITÁRIA CANDURA", "Limpeza", "Limpeza Geral e Banheiro", "Geral")

    def test_papeis_e_descartaveis(self):
        self._testar_taxonomia("PAPEL HIGIÊNICO NEVE", "Limpeza", "Papéis e Descartáveis", "Geral")
        self._testar_taxonomia("SACO DE LIXO 50L", "Limpeza", "Papéis e Descartáveis", "Geral")

    def test_inseticidas_e_repelentes(self):
        self._testar_taxonomia("INSETICIDA SBP AEROSOL", "Limpeza", "Inseticidas e Repelentes", "Geral")

if __name__ == "__main__":
    unittest.main(verbosity=2)