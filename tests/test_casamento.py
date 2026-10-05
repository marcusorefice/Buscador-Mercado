import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import casamento_produtos as cp
from casamento_produtos import Assinatura, CasadorProdutos, compativel, montar_equivalencias


def biblioteca_exemplo():
    return {
        "7894900011517": {"nome_comum": "Refrigerante Coca-Cola Garrafa 2l", "marca": "Coca-Cola"},
        "7894900700015": {"nome_comum": "Refrigerante Coca-Cola Sem Açúcar Garrafa 2l", "marca": "Coca-Cola"},
        "7891000100103": {"nome_comum": "Leite Integral Italac 1l", "marca": "Italac"},
        "7891000100110": {"nome_comum": "Leite Desnatado Italac 1l", "marca": "Italac"},
        "7896004000001": {"nome_comum": "Suco Del Valle Kapo Morango 200ml", "marca": "Del Valle"},
        "7896004000002": {"nome_comum": "Suco Del Valle Kapo Uva 200ml", "marca": "Del Valle"},
        "7891991000001": {"nome_comum": "Cerveja Heineken Lata 350ml", "marca": "Heineken"},
        "7891991000002": {"nome_comum": "Cerveja Heineken Lata 350ml", "marca": "Heineken"},  # mesmo produto, outro EAN
        "7891991000003": {"nome_comum": "Cerveja Heineken Lata 350ml com 12 Unidades", "marca": "Heineken"},
        "7896000000009": {"nome_comum": "Sabão em Pó Omo Lavagem Perfeita 800g", "marca": "Omo"},
    }


class TestAssinatura(unittest.TestCase):
    def test_medidas_equivalentes(self):
        self.assertEqual(Assinatura("AGUA CRYSTAL 1,5L", "CRYSTAL").medida, Assinatura("Água Crystal 1500ml", "Crystal").medida)
        self.assertEqual(Assinatura("CAFE PILAO 0,5KG", "PILAO").medida, ("g", 500.0))

    def test_pack(self):
        self.assertEqual(Assinatura("CERVEJA SKOL LATA 350ML C/ 12 UNIDADES", "SKOL").pack, 12)
        self.assertEqual(Assinatura("CERVEJA SKOL 12X350ML", "SKOL").pack, 12)
        self.assertIsNone(Assinatura("CERVEJA SKOL LATA 350ML", "SKOL").pack)

    def test_promocao_nao_vira_pack(self):
        self.assertIsNone(Assinatura("ESPONJA TININDO LEVE 4 PAGUE 3 UN", "TININDO").pack)

    def test_mesmo_nome_escrito_diferente_tem_mesma_chave(self):
        a = Assinatura("TOMATE ITALIANO BDJ 500G", "HORTIFRUTI")
        b = Assinatura("Tomate Italiano Bandeja 500 g", "")
        self.assertEqual(a.chave, b.chave)


class TestCompativel(unittest.TestCase):
    def test_zero_x_normal(self):
        ok, _ = compativel(Assinatura("COCA COLA ZERO 2L", "COCA-COLA"), Assinatura("COCA COLA 2L", "COCA-COLA"))
        self.assertFalse(ok)

    def test_sem_pimenta_x_com_pimenta(self):
        ok, _ = compativel(Assinatura("TEMPERO COMPLETO SEM PIMENTA AMI 300G", "AMI"), Assinatura("Tempero Completo com Pimenta Ami 300g", "Ami"))
        self.assertFalse(ok)

    def test_lata_x_garrafa(self):
        ok, _ = compativel(Assinatura("CERVEJA STELLA LATA 350ML", "STELLA"), Assinatura("CERVEJA STELLA GARRAFA 350ML", "STELLA"))
        self.assertFalse(ok)

    def test_medida_diferente(self):
        ok, _ = compativel(Assinatura("ARROZ TIO JOAO 1KG", "TIO JOAO"), Assinatura("ARROZ TIO JOAO 5KG", "TIO JOAO"))
        self.assertFalse(ok)

    def test_marca_x_fabricante(self):
        ok, _ = compativel(Assinatura("LAVA-ROUPAS EM PÓ OMO LAVAGEM PERFEITA 800G", "UNILEVER"), Assinatura("Sabão em Pó Omo Lavagem Perfeita 800g", "Omo"))
        self.assertTrue(ok)

    def test_marcas_diferentes(self):
        ok, _ = compativel(Assinatura("CERVEJA SKOL 350ML", "SKOL"), Assinatura("CERVEJA BRAHMA 350ML", "BRAHMA"))
        self.assertFalse(ok)


class TestCasador(unittest.TestCase):
    def setUp(self):
        self.casador = CasadorProdutos(biblioteca_exemplo())

    def test_casa_automatico(self):
        r = self.casador.casar("REFRIGERANTE COCA-COLA SEM AÇÚCAR GARRAFA 2L", "COCA-COLA")
        self.assertEqual((r["ean"], r["tipo"]), ("7894900700015", "auto"))

    def test_nao_confunde_integral_com_desnatado(self):
        r = self.casador.casar("LEITE ITALAC DESNATADO 1 LITRO", "ITALAC")
        self.assertEqual(r["ean"], "7891000100110")

    def test_nao_confunde_sabor(self):
        r = self.casador.casar("SUCO KAPO DEL VALLE UVA 200ML", "DEL VALLE")
        self.assertEqual(r["ean"], "7896004000002")

    def test_unidade_nao_casa_com_pack(self):
        r = self.casador.casar("CERVEJA HEINEKEN LATA 350ML", "HEINEKEN")
        self.assertIn(r["ean"], {"7891991000001", "7891991000002"})

    def test_sem_candidato(self):
        self.assertIsNone(self.casador.casar("PILHA ALCALINA DURACELL AAA 4UN", "DURACELL"))

    def test_confirmado_por_humano_tem_prioridade(self):
        chave = Assinatura("SUCO KAPO UVA 200ML", "DEL VALLE").chave
        casador = CasadorProdutos(biblioteca_exemplo(), {"confirmados": {chave: "7896004000001"}})
        self.assertEqual(casador.casar("SUCO KAPO UVA 200ML", "DEL VALLE")["tipo"], "confirmado")

    def test_rejeitado_por_humano_nao_volta(self):
        chave = Assinatura("REFRIGERANTE COCA-COLA SEM AÇÚCAR GARRAFA 2L", "COCA-COLA").chave
        casador = CasadorProdutos(biblioteca_exemplo(), {"rejeitados": {chave: ["7894900700015"]}})
        r = casador.casar("REFRIGERANTE COCA-COLA SEM AÇÚCAR GARRAFA 2L", "COCA-COLA")
        self.assertTrue(r is None or r["ean"] != "7894900700015")

    def test_grupo_interno_junta_mercados(self):
        a = self.casador.agrupar_interno("TOMATE ITALIANO BDJ 500G", "HORTIFRUTI")
        b = self.casador.agrupar_interno("Tomate Italiano Bandeja 500 g", "")
        c = self.casador.agrupar_interno("CEBOLA ROXA", "HORTIFRUTI")
        self.assertTrue(a.startswith("INT_"))
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)

    def test_id_interno_estavel_entre_rodadas(self):
        a = CasadorProdutos({}).agrupar_interno("TOMATE ITALIANO BDJ 500G", "HORTIFRUTI")
        b = CasadorProdutos({}).agrupar_interno("TOMATE ITALIANO BDJ 500G", "HORTIFRUTI")
        self.assertEqual(a, b)


class TestEquivalencias(unittest.TestCase):
    def test_duplicata_exata_vira_equivalente(self):
        casador = CasadorProdutos(biblioteca_exemplo())
        eq = montar_equivalencias(casador, {})
        self.assertEqual(eq, {"7891991000002": "7891991000001"})

    def test_humano_pode_bloquear_e_criar(self):
        casador = CasadorProdutos(biblioteca_exemplo())
        eq = montar_equivalencias(casador, {
            "nao_equivalentes": [["7891991000001", "7891991000002"]],
            "equivalentes": {"7896004000002": "7896004000001", "7896004000001": "7891000100103"},
        })
        self.assertNotIn("7891991000002", eq)
        self.assertEqual(eq["7896004000002"], "7891000100103")  # cadeia resolvida


class TestRevisao(unittest.TestCase):
    def test_exportar_e_importar_decisoes(self):
        import revisar_casamentos as rc
        import pandas as pd
        with tempfile.TemporaryDirectory() as d:
            rc.ARQUIVO_CASAMENTOS = os.path.join(d, "casamentos.json")
            rc.ARQUIVO_REVISAO = os.path.join(d, "revisao.xlsx")
            rc.ARQUIVO_DUPLICATAS = os.path.join(d, "dup.xlsx")
            rc.exportar_sugestoes([
                {"Mercado": "Oba", "Nome no mercado": "SUCO X", "Marca": "X", "EAN sugerido": "111", "Nome na biblioteca": "Suco X", "Pontuação": 0.7, "chave": "k1"},
                {"Mercado": "Oba", "Nome no mercado": "SUCO Y", "Marca": "Y", "EAN sugerido": "222", "Nome na biblioteca": "Suco Z", "Pontuação": 0.6, "chave": "k2"},
                {"Mercado": "Oba", "Nome no mercado": "SUCO W", "Marca": "W", "EAN sugerido": "333", "Nome na biblioteca": "Suco W", "Pontuação": 0.6, "chave": "k3"},
            ])
            df = pd.read_excel(rc.ARQUIVO_REVISAO, dtype=str).fillna("")
            df.loc[df["chave (não alterar)"] == "k1", rc.COLUNA_DECISAO] = "s"
            df.loc[df["chave (não alterar)"] == "k2", rc.COLUNA_DECISAO] = "N"
            df.to_excel(rc.ARQUIVO_REVISAO, index=False)

            self.assertEqual(rc.importar_decisoes(), 2)
            c = rc.carregar_casamentos()
            self.assertEqual(c["confirmados"], {"k1": "111"})
            self.assertEqual(c["rejeitados"], {"k2": ["222"]})
            restante = pd.read_excel(rc.ARQUIVO_REVISAO, dtype=str)
            self.assertEqual(list(restante["chave (não alterar)"]), ["k3"])


if __name__ == "__main__":
    unittest.main()
