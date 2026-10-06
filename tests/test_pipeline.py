"""
Testes do pipeline. Rodar a partir da raiz do projeto:
    .venv\\Scripts\\python -m unittest discover -s tests -v
"""
import importlib
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from utils import parse_preco, normalizar_data_iso, salvar_json_atomico, ler_json_seguro, ArquivoCorrompidoError

passo4 = importlib.import_module("4_resolver_pendentes")
passo5 = importlib.import_module("5_atualizar_banco")


class TestParsePreco(unittest.TestCase):
    def test_formatos(self):
        casos = {
            "R$ 12,50": 12.5,
            "R$ 1234,56": 1234.56,
            "1.234,56": 1234.56,
            "1,234.56": 1234.56,
            "12.99": 12.99,
            "R$\xa09,90": 9.9,
            12: 12.0,
            7.5: 7.5,
            "": 0.0,
            "N/A": 0.0,
            None: 0.0,
            "abc": 0.0,
        }
        for entrada, esperado in casos.items():
            with self.subTest(entrada=entrada):
                self.assertAlmostEqual(parse_preco(entrada), esperado)


class TestDatas(unittest.TestCase):
    def test_converte_formato_dos_scrapers(self):
        self.assertEqual(normalizar_data_iso("05/10/2026 14:03:09"), "2026-10-05 14:03:09")
        self.assertEqual(normalizar_data_iso("31/05/2026"), "2026-05-31 00:00:00")

    def test_iso_passa_direto(self):
        self.assertEqual(normalizar_data_iso("2026-10-05 14:03:09"), "2026-10-05 14:03:09")

    def test_iso_ordena_como_texto(self):
        datas = [normalizar_data_iso(d) for d in ["01/10/2026 10:00:00", "31/05/2026 10:00:00"]]
        self.assertEqual(max(datas), "2026-10-01 10:00:00")


class TestJsonSeguro(unittest.TestCase):
    def test_atomico_e_leitura(self):
        with tempfile.TemporaryDirectory() as d:
            caminho = os.path.join(d, "sub", "a.json")
            salvar_json_atomico(caminho, {"x": "ç"})
            self.assertEqual(ler_json_seguro(caminho), {"x": "ç"})
            self.assertFalse(os.path.exists(caminho + ".tmp"))

    def test_arquivo_inexistente_usa_padrao(self):
        self.assertEqual(ler_json_seguro("nao_existe_123.json", []), [])

    def test_arquivo_corrompido_levanta_erro(self):
        with tempfile.TemporaryDirectory() as d:
            caminho = os.path.join(d, "ruim.json")
            with open(caminho, "w", encoding="utf-8") as f:
                f.write('[{"EAN": "123", ')
            with self.assertRaises(ArquivoCorrompidoError):
                ler_json_seguro(caminho, [])


class TestPasso5(unittest.TestCase):
    def item(self, **kw):
        base = {"EAN": "7891000100103", "Mercado": "Covabra", "Produto": "LEITE", "Preço Varejo": "R$ 5,99",
                "Preço Atacado": "R$ 4,99", "Data_Hora": "05/10/2026 10:00:00"}
        base.update(kw)
        return base

    def test_preparar_ofertas(self):
        correcoes = [{"ean_errado": "7891991015462", "nome_contem": "LATA", "ean_correto": "7891991016223"}]
        itens = [
            self.item(),
            self.item(**{"Preço Atacado": "R$ 4,50"}),                       # duplicado: o último vence
            self.item(EAN="7891991015462", Produto="STELLA LATA 350ML", Mercado="Carrefour", Scraper_Origem="FULL"),
            self.item(EAN="N/A"),                                              # sem EAN: ignorado
            self.item(EAN="7891000100110", **{"Preço Varejo": "0", "Preço Atacado": "0"}),  # sem preço: ignorado
        ]
        ofertas, eans_por_mercado, mercados_full = passo5.preparar_ofertas(itens, correcoes)

        self.assertEqual(len(ofertas), 2)
        leite = ofertas[("7891000100103", "Covabra")]
        self.assertEqual(leite[3], 5.99)
        self.assertEqual(leite[4], 4.50)
        self.assertEqual(leite[9], "2026-10-05 10:00:00")
        self.assertIn(("7891991016223", "Carrefour"), ofertas)
        self.assertEqual(mercados_full, {"Carrefour"})
        self.assertEqual(eans_por_mercado["Covabra"], {"7891000100103"})

    def test_historico_so_quando_preco_muda(self):
        ofertas, _, _ = passo5.preparar_ofertas([self.item()], [])
        chave = ("7891000100103", "Covabra")
        self.assertEqual(len(passo5.calcular_novos_historicos(ofertas, {})), 1)
        self.assertEqual(len(passo5.calcular_novos_historicos(ofertas, {chave: (5.99, 4.99)})), 0)
        self.assertEqual(len(passo5.calcular_novos_historicos(ofertas, {chave: (5.99, 4.89)})), 1)


class TestConflitoAnomalia(unittest.TestCase):
    def test_mesmo_produto_nao_e_conflito(self):
        self.assertFalse(passo4.checar_conflito_anomalia("LEITE INTEGRAL ITALAC 1L", "LEITE INTEGRAL ITALAC 1 L"))

    def test_lata_vs_garrafa(self):
        self.assertTrue(passo4.checar_conflito_anomalia("CERVEJA STELLA ARTOIS LATA 350ML", "CERVEJA STELLA ARTOIS GARRAFA 330ML"))

    def test_peso_muito_diferente(self):
        self.assertTrue(passo4.checar_conflito_anomalia("ARROZ TIO JOAO 1KG", "ARROZ TIO JOAO 5KG"))

    def test_peso_proximo_nao_e_conflito(self):
        self.assertFalse(passo4.checar_conflito_anomalia("CAFE PILAO 500G", "CAFE PILAO TRADICIONAL 0,5KG"))


class TestApiMontarProdutos(unittest.TestCase):
    def test_ordena_ofertas_e_menor_preco(self):
        api = importlib.import_module("api")
        base = {"ean": "1", "nome_comum": "Leite", "categoria": "X", "marca": "M", "imagem": "", "tags": "a, b",
                "nome_original": "", "qtd_valor": "1", "medida": "UN", "unidade": "UN", "condicao": "",
                "data_atualizacao": "", "link_pdp": ""}
        rows = [
            dict(base, mercado="Caro", preco_varejo=10, preco_atacado=0, preco_efetivo=10),
            dict(base, mercado="Barato", preco_varejo=8, preco_atacado=7, preco_efetivo=7),
        ]
        [bruto] = api._montar_produtos(rows)
        # A API devolve dicionários sem revalidar; o formato precisa continuar batendo com o modelo
        produto = api.ProdutoAgrupadoResponse(**bruto)
        self.assertEqual([o.Mercado for o in produto.Ofertas], ["Barato", "Caro"])
        self.assertEqual(produto.Menor_Preco, 7)
        self.assertEqual(produto.Tags, ["a", "b"])


if __name__ == "__main__":
    unittest.main()
