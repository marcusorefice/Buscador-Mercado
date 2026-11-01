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

from utils import ean_e_valido, ean_unico_no_html, parse_preco, normalizar_data_iso, salvar_json_atomico, ler_json_seguro, ArquivoCorrompidoError, normalizar_categoria, CATEGORIAS_MASTER

passo4 = importlib.import_module("4_resolver_pendentes")
passo5 = importlib.import_module("5_atualizar_banco")
from casamento_produtos import CasadorProdutos, equivalencias_automaticas, apoio_por_ean


class TestEanEValido(unittest.TestCase):
    def test_gtins_reais(self):
        for ean in ["7891000100103", "80051220", "0000078946033", "0000042360407"]:
            with self.subTest(ean=ean):
                self.assertTrue(ean_e_valido(ean))

    def test_codigo_interno_com_zeros_nao_e_ean(self):
        # Códigos internos do Pão de Açúcar e do São Vicente: o mesmo número é um produto diferente em cada loja
        for ean in ["0000000081641", "0000000037839", "0000002510606"]:
            with self.subTest(ean=ean):
                self.assertFalse(ean_e_valido(ean))


class TestEanUnicoNoHtml(unittest.TestCase):
    def test_um_ean_so(self):
        self.assertEqual(ean_unico_no_html('<img src="/fotos/7891000100103.jpg"> "ean":"7891000100103"'), "7891000100103")

    def test_varios_eans_nao_escolhe_nenhum(self):
        # Página de kit ou com vitrine: o primeiro EAN pode ser de outro produto
        html = 'Kit Melitta <a>7891021006125</a> vitrine <a>7891000100103</a>'
        self.assertIsNone(ean_unico_no_html(html))

    def test_ignora_numero_invalido_e_pedaco_de_numero_maior(self):
        self.assertIsNone(ean_unico_no_html("id 7891000100104 e 178910001001039"))
        self.assertIsNone(ean_unico_no_html(""))


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

    def test_peca_com_peso_vira_preco_por_kg(self):
        self.assertEqual(passo5.peso_da_peca("INT_COVABRA_BATATA", "BATATA PIRULITO 1 UN 35G", "1", "UN", "UN"), ("35", "G", "KG"))
        self.assertEqual(passo5.peso_da_peca("INT_COVABRA_LINGUICA", "LINGUIÇA TOSCANA 1 PORÇÃO 824G", "1", "UN", "UN"), ("824", "G", "KG"))
        # Com EAN continua por unidade (é comparado com outros mercados); sem peso no nome também
        self.assertEqual(passo5.peso_da_peca("7891000100103", "NUTELLA 1 UN 375G", "1", "UN", "UN"), ("1", "UN", "UN"))
        self.assertEqual(passo5.peso_da_peca("INT_X", "ALFACE CRESPA 1 UN", "1", "UN", "UN"), ("1", "UN", "UN"))
        ofertas, _, _ = passo5.preparar_ofertas([self.item(EAN="INT_COVABRA_BATATA", Produto="BATATA PIRULITO 1 UN 35G")], [])
        self.assertEqual(ofertas[("INT_COVABRA_BATATA", "Covabra")][5:8], ("35", "G", "KG"))

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



class TestNormalizarCategoria(unittest.TestCase):
    def test_categorias_brutas_dos_mercados(self):
        casos = {
            "HORTIFRUTI": "Hortifrúti",
            "HORTIFRÚTI": "Hortifrúti",
            "HIGIENE-E-PERFUMARIA": "Higiene e Cuidado Pessoal",
            "FRIOS & EMBUTIDOS": "Frios e Laticínios",
            "ACOUGUE-E-PEIXARIA": "Açougue e Peixaria",
            "BEBIDAS ALCOÓLICAS": "Bebidas Alcoólicas",
            "CERVEJAS": "Bebidas Alcoólicas",
            "DESCARTÁVEIS": "Bazar e Utilidades",
            "PETSHOP": "Pet Shop",
        }
        for bruta, esperado in casos.items():
            with self.subTest(bruta=bruta):
                self.assertEqual(normalizar_categoria(bruta), esperado)

    def test_categoria_generica_usa_o_nome(self):
        # "NESTLE" é a marca, não a categoria: o produto pode ser qualquer coisa
        self.assertEqual(normalizar_categoria("NESTLE", "Rivaroxabana 10mg com 30 Comprimidos"), "Saúde e Suplementos")
        self.assertEqual(normalizar_categoria("NESTLE", "Ração Úmida para Cães Adultos Sabor Carne"), "Pet Shop")
        self.assertEqual(normalizar_categoria("NESTLE", "Queijo Provolone Tirolez 160g"), "Frios e Laticínios")
        self.assertEqual(normalizar_categoria("ALIMENTOS", "Bacalhau Morhua Desfiado 300g"), "Açougue e Peixaria")

    def test_sem_pista_vira_outros(self):
        self.assertEqual(normalizar_categoria("GERAL", "Difusor de Aromas 4house Vanilla 100ml"), "Outros")
        self.assertEqual(normalizar_categoria(None, None), "Outros")

    def test_categoria_master_nao_muda(self):
        for categoria in CATEGORIAS_MASTER:
            with self.subTest(categoria=categoria):
                self.assertEqual(normalizar_categoria(categoria), categoria)



class TestCondicaoEspecialEspelhada(unittest.TestCase):
    def test_sql_e_app_usam_a_mesma_regra(self):
        # A regra do preço com CPF/clube/compra mínima existe no SQL e no app: as duas precisam ser iguais
        import re
        from ofertas_sql import RE_CONDICAO_ESPECIAL
        caminho = os.path.join(os.path.dirname(__file__), '..', 'comparador-app', 'precos.ts')
        with open(caminho, encoding='utf-8') as f:
            regra_app = re.search(r"const CONDICAO_ESPECIAL = /(.+)/i;", f.read()).group(1)
        self.assertEqual(regra_app, RE_CONDICAO_ESPECIAL)



class TestApiProtecoes(unittest.TestCase):
    def test_limite_de_pedidos_por_janela(self):
        api = importlib.import_module("api")
        limite = api._LimiteDePedidos(maximo=2, janela_segundos=10)
        self.assertEqual([limite.permitir("a", 0), limite.permitir("a", 1), limite.permitir("a", 2)], [True, True, False])
        self.assertTrue(limite.permitir("b", 2))    # outra chave tem a própria conta
        self.assertTrue(limite.permitir("a", 11))   # passada a janela, volta a valer

    def test_debug_fica_escondido_sem_a_senha(self):
        from starlette.testclient import TestClient
        api = importlib.import_module("api")
        cliente = TestClient(api.app)
        senha_original, api.DEBUG_TOKEN = api.DEBUG_TOKEN, "senha-de-teste"
        try:
            self.assertEqual(cliente.get("/debug").status_code, 404)
            self.assertEqual(cliente.get("/debug", headers={"X-Debug-Token": "errada"}).status_code, 404)
        finally:
            api.DEBUG_TOKEN = senha_original

    def test_cors_nao_libera_sites_por_padrao(self):
        from starlette.testclient import TestClient
        api = importlib.import_module("api")
        resposta = TestClient(api.app).get("/", headers={"Origin": "https://site-qualquer.com"})
        self.assertNotIn("access-control-allow-origin", resposta.headers)



class TestMontarProdutos(unittest.TestCase):
    def test_quantidade_de_mercados_vem_do_ranking_mesmo_com_filtro(self):
        api = importlib.import_module("api")
        linha = {"ean": "789", "nome_comum": "Leite", "categoria": "Frios e Laticínios", "marca": "X", "imagem": "", "tags": "",
                 "mercado": "Carrefour", "nome_original": "LEITE", "preco_varejo": 5.0, "preco_atacado": 5.0, "qtd_valor": "1",
                 "medida": "UN", "unidade": "UN", "condicao": "1 UN", "data_atualizacao": "", "link_pdp": "",
                 "preco_efetivo": 5.0, "qtd_mercados": 6}
        produto = api._montar_produtos([linha])[0]
        self.assertEqual(produto["Qtd_Mercados"], 6)
        self.assertEqual(len(produto["Ofertas"]), 1)
        sem_ranking = {k: v for k, v in linha.items() if k != "qtd_mercados"}  # /produtos/lote não traz a coluna
        self.assertIsNone(api._montar_produtos([sem_ranking])[0]["Qtd_Mercados"])


if __name__ == "__main__":
    unittest.main()


class TestEquivalenciasPrincipal(unittest.TestCase):
    """O principal de dois EANs com nome idêntico é o que mais mercados confirmam, não o menor número."""
    BIBLIOTECA = {
        "7891095911851": {"nome_comum": "Shampoo Dove Reconstrução + Aminoácido 370ml", "marca": "Dove"},
        "7891150102637": {"nome_comum": "Shampoo Dove Reconstrução + Aminoácido 370ml", "marca": "Dove"},
    }

    def test_sem_apoio_vale_o_menor(self):
        mapa = equivalencias_automaticas(CasadorProdutos(self.BIBLIOTECA))
        self.assertEqual(mapa, {"7891150102637": "7891095911851"})

    def test_com_apoio_vale_o_confirmado(self):
        apoio = {"7891150102637": 1}
        mapa = equivalencias_automaticas(CasadorProdutos(self.BIBLIOTECA), apoio=apoio)
        self.assertEqual(mapa, {"7891095911851": "7891150102637"})

    def test_apoio_conta_mercados_distintos(self):
        itens = [
            {"EAN": "7891150102637", "Mercado": "Atacadão"},
            {"EAN": "7891150102637", "Mercado": "Atacadão"},
            {"EAN": "7891150102637", "Mercado": "Carrefour"},
            {"EAN": "N/A", "Mercado": "Covabra"},
            {"EAN": "INT_ABC", "Mercado": "Covabra"},
        ]
        self.assertEqual(apoio_por_ean(itens), {"7891150102637": 2})


class TestConflitosBiblioteca(unittest.TestCase):
    def test_classificacao(self):
        self.assertEqual(passo4.classificar_conflito({"Atacadão", "Carrefour"}, set()), "PROVAVEL_BIBLIOTECA_ERRADA")
        self.assertEqual(passo4.classificar_conflito({"Atacadão"}, {"Oba", "Covabra"}), "PROVAVEL_ITEM_DO_MERCADO_ERRADO")
        self.assertEqual(passo4.classificar_conflito({"Atacadão"}, set()), "REVISAR")

    def test_relatorios_sao_gravados(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = os.path.join(pasta, "conflitos.csv")
            n = passo4.gravar_conflitos_biblioteca(
                [("789", "Lâmpada Ledvance", "SABONETE CLOY 80G", "Carrefour"), ("789", "Lâmpada Ledvance", "SABONETE CLOY 80G", "Covabra")],
                {}, caminho)
            self.assertEqual(n, 1)
            with open(caminho, encoding="utf-8-sig") as f:
                self.assertIn("PROVAVEL_BIBLIOTECA_ERRADA", f.read())
            log = os.path.join(pasta, "eq.csv")
            passo4.gravar_log_equivalencias({"2": "1"}, {"1": {"nome_comum": "A"}, "2": {"nome_comum": "A"}}, {"2": 1}, log)
            with open(log, encoding="utf-8-sig") as f:
                self.assertEqual(len(f.read().strip().splitlines()), 2)


class TestTravaLimpeza(unittest.TestCase):
    def test_limites(self):
        self.assertTrue(passo5.limpeza_segura(100, 5))
        self.assertFalse(passo5.limpeza_segura(100, 6))
        self.assertTrue(passo5.limpeza_segura(0, 0))
        self.assertFalse(passo5.limpeza_segura(6532, 3200))

    def test_scrapers_carrefour_nao_usam_biblioteca(self):
        base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scrapers")
        for nome in ("carrefour.py", "carrefour_full.py"):
            with open(os.path.join(base, nome), encoding="utf-8") as f:
                self.assertNotIn("indice_reverso", f.read(), nome)
