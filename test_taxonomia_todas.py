import unittest
from utils import normalizar_taxonomia_grabit

class TestTaxonomiaTodas(unittest.TestCase):
    def setUp(self):
        # Simulando uma biblioteca vazia para focar apenas no Motor de Regras (GrabIt)
        self.biblioteca_mock = {}
        self.failures = []

    def tearDown(self):
        if self.failures:
            # Junta todas as mensagens de falha e falha o teste com a mensagem combinada
            # Isso garante que todos os erros dentro de um método de teste sejam exibidos de uma vez.
            self.fail("\n\n" + "\n\n".join(self.failures))

    def _testar(self, nome_produto, cat_esperada, sub_esperada, tipo_esperado):
        cat, sub, tipo = normalizar_taxonomia_grabit(
            nome_produto=nome_produto,
            marca="",
            categoria_mercado="",
            subcategoria_mercado="",
            tipo_produto_mercado="",
            ean="N/A",
            biblioteca=self.biblioteca_mock
        )
        errors = []
        if cat != cat_esperada:
            errors.append(f"  - Categoria: Esperado '{cat_esperada}', Obtido '{cat}'")
        if sub != sub_esperada:
            errors.append(f"  - Subcategoria: Esperado '{sub_esperada}', Obtido '{sub}'")
        if tipo_esperado and tipo != tipo_esperado:
            errors.append(f"  - Tipo: Esperado '{tipo_esperado}', Obtido '{tipo}'")

        if errors:
            # Formata a mensagem de erro para este produto específico
            failure_message = f"❌ Falha no produto: '{nome_produto}'\n" + "\n".join(errors)
            self.failures.append(failure_message)

    # --- MERCEARIA E DESPENSA ---
    def test_mercearia_basicos(self):
        self._testar("ARROZ AGULHINHA TIPO 1 5KG", "Mercearia e Despensa", "Arroz e Grãos", "Arroz")
        self._testar("FEIJÃO PRETO KICALDO 1KG", "Mercearia e Despensa", "Arroz e Grãos", "Feijão")
        self._testar("AÇÚCAR REFINADO UNIÃO 1KG", "Mercearia e Despensa", "Açúcar e Adoçantes", "Açúcar")
        self._testar("CAFÉ EM PÓ MELITTA 500G", "Mercearia e Despensa", "Cafés, Chás e Achocolatados", "Café")

    def test_mercearia_massas_e_molhos(self):
        self._testar("MACARRÃO INSTANTÂNEO NISSIN LÁMEN", "Mercearia e Despensa", "Massas e Molhos", "Macarrão")

    def test_mercearia_oleos_e_temperos(self):
        self._testar("AZEITE DE OLIVA ANDORINHA", "Mercearia e Despensa", "Óleos e Azeites", "Óleo")
        self._testar("VINAGRE DE MAÇÃ CASTELO", "Mercearia e Despensa", "Óleos e Azeites", "Óleo")
        self._testar("MAIONESE HELLMANN'S 500G", "Mercearia e Despensa", "Temperos e Condimentos", "Maionese")

    def test_mercearia_doces_e_biscoitos(self):
        self._testar("BOMBOM SONHO DE VALSA PACOTE", "Mercearia e Despensa", "Chocolates e Doces", "Chocolate")
        self._testar("GELATINA EM PÓ ROYAL", "Mercearia e Despensa", "Chocolates e Doces", "Gelatina")
        self._testar("BISCOITO WAFER BAUDUCCO", "Mercearia e Despensa", "Biscoitos e Bolachas", "Biscoitos")
        self._testar("SALGADINHO DE MILHO CHEETOS", "Mercearia e Despensa", "Biscoitos e Bolachas", "Salgadinhos")

    # --- BEBIDAS ---
    def test_bebidas_nao_alcoolicas(self):
        self._testar("REFRIGERANTE GUARANÁ ANTARCTICA 2L", "Bebidas", "Refrigerantes", "Refrigerantes")
        self._testar("SUCO DE LARANJA PRATS", "Bebidas", "Sucos e Refrescos", "Suco")
        self._testar("ÁGUA MINERAL SEM GÁS Minalba 1L", "Bebidas", "Águas", "Águas")
        self._testar("ENERGÉTICO MONSTER 473ML", "Bebidas", "Energéticos e Isotônicos", "Energético")

    def test_bebidas_alcoolicas(self):
        self._testar("CERVEJA SKOL PURO MALTE 350ML", "Bebidas Alcoólicas", "Geral", "Alcoólicos")
        self._testar("VODKA SMIRNOFF 998ML", "Bebidas Alcoólicas", "Geral", "Alcoólicos")
        
    # --- FRIOS E LATICÍNIOS ---
    def test_frios_laticinios(self):
        self._testar("REQUEIJÃO CREMOSO VIGOR", "Frios e Laticínios", "Queijos", "Queijo")
        self._testar("LEITE UHT INTEGRAL ITALAC 1L", "Frios e Laticínios", "Leites", "Leite")
        self._testar("IOGURTE GREGO MORANGO", "Frios e Laticínios", "Iogurtes e Lácteos", "Iogurte")
        self._testar("MORTADELA BOLOGNA OURO PERDIGÃO", "Frios e Laticínios", "Frios e Embutidos", "Frios")
        self._testar("LINGUIÇA CALABRESA DEFUMADA SEARA", "Frios e Laticínios", "Frios e Embutidos", "Linguiça Defumada")

    # --- AÇOUGUE E PEIXARIA ---
    def test_acougue_peixaria(self):
        self._testar("BIFE DE ALCATRA", "Açougue e Peixaria", "Carne Bovina", "Carne Bovina")
        self._testar("COXINHA DA ASA DE FRANGO", "Açougue e Peixaria", "Aves", "Aves")
        self._testar("BISTECA SUÍNA SADIA", "Açougue e Peixaria", "Suínos", "Suínos")
        self._testar("FILÉ DE SALMÃO FRESCO", "Açougue e Peixaria", "Peixes e Frutos do Mar", "Peixes")

    # --- CONGELADOS ---
    def test_congelados(self):
        self._testar("PÃO DE QUEIJO CONGELADO FORNO DE MINAS", "Congelados e Pratos Prontos", "Pratos Prontos Congelados", "Pratos Prontos Congelados")
        self._testar("PIZZA CONGELADA SADIA CALABRESA", "Congelados e Pratos Prontos", "Pratos Prontos Congelados", "Pratos Prontos Congelados")
        self._testar("SORVETE KIBON CREMOSÍSSIMO", "Congelados e Pratos Prontos", "Sorvetes e Sobremesas Congeladas", "Sorvete")

    # --- HORTIFRUTI ---
    def test_hortifruti(self):
        self._testar("BATATA LAVADA KG", "Hortifrúti", "Legumes e Raízes", "Batata")
        self._testar("COUVE-FLOR UNIDADE", "Hortifrúti", "Verduras e Folhas", "Couve-flor")
        self._testar("OVOS BRANCOS DÚZIA", "Hortifrúti", "Ovos", "Ovos")
        self._testar("MAÇÃ GALA KG", "Hortifrúti", "Frutas", "Maçã")

    # --- PADARIA ---
    def test_padaria(self):
        self._testar("PÃO FRANCÊS", "Padaria e Confeitaria", "Pães e Bolos", "Padaria")
        self._testar("BOLO DE CHOCOLATE", "Padaria e Confeitaria", "Pães e Bolos", "Bolo")

    # --- LIMPEZA ---
    def test_limpeza(self):
        self._testar("DETERGENTE LÍQUIDO YPÊ 500ML", "Limpeza", "Limpadores e Detergentes", "Detergente Líquido")
        self._testar("SABÃO EM PÓ OMO LAVAGEM PERFEITA", "Limpeza", "Cuidado com as Roupas", "Sabão em Pó")
        self._testar("ÁGUA SANITÁRIA CANDURA 2L", "Limpeza", "Limpeza Geral e Banheiro", "Geral")
        self._testar("PAPEL HIGIÊNICO NEVE FOLHA DUPLA", "Limpeza", "Papéis e Descartáveis", "Geral")

    # --- HIGIENE E CUIDADO PESSOAL ---
    def test_higiene(self):
        self._testar("SHAMPOO PANTENE RESTAURAÇÃO", "Higiene e Cuidado Pessoal", "Cabelos", "Tratamento Capilar")
        self._testar("CREME DENTAL COLGATE TOTAL 12", "Higiene e Cuidado Pessoal", "Higiene Oral", "Creme Dental")
        self._testar("ABSORVENTE SEM ABAS SEMPRE LIVRE", "Higiene e Cuidado Pessoal", "Higiene Íntima", "Absorvente")

    # --- BEBÊ E INFANTIL ---
    def test_bebe_infantil(self):
        self._testar("FRALDA DESCARTÁVEL HUGGIES M", "Bebê e Infantil", "Fraldas e Higiene", "Fraldas Descartáveis")
        self._testar("LENÇO UMEDECIDO JOHNSON'S BABY", "Bebê e Infantil", "Fraldas e Higiene", "Lenços Umedecidos")

    # --- PET SHOP ---
    def test_pet_shop(self):
        self._testar("RAÇÃO PARA CÃES PEDIGREE ADULTO 1KG", "Pet Shop", "Alimentos para Cães", "Ração Seca")
        self._testar("AREIA HIGIÊNICA PARA GATO PIPICAT", "Pet Shop", "Higiene e Cuidados Pet", "Areia para Gato")

    # --- BAZAR E UTILIDADES ---
    def test_bazar(self):
        self._testar("LÂMPADA LED 9W BRANCA", "Bazar e Utilidades", "Eletro e Eletrônicos", "Eletro")
        self._testar("PILHA ALCALINA DURACELL AA", "Bazar e Utilidades", "Eletro e Eletrônicos", "Eletro")
        self._testar("SACO DE LIXO 100L", "Limpeza", "Papéis e Descartáveis", "Geral")

    # --- NOVOS TESTES (EANs da biblioteca) ---
    def test_casos_adicionados_pelo_usuario(self):
        # EAN: 7896098900277
        self._testar("Detergente Ypê Clear Care", "Limpeza", "Limpadores e Detergentes", "Detergente Líquido")
        # EAN: 7891035524271
        self._testar("Harpic Pedra Sanitária Aroma Plus Pinho 40% de Desconto", "Limpeza", "Limpeza Sanitária", "Geral")
        # EAN: 7891035524349
        self._testar("Desodorizador Sanitário Pato Gel Adesivo Marine Refil", "Limpeza", "Limpeza Sanitária", "Desodorizador Sanitário")
        # EAN: 7891103213946 - Corrigido para refletir que sabão de bebê é para roupas, não higiene de bebê.
        self._testar("Sabão Líquido Lava-roupas Carrefour Baby", "Limpeza", "Cuidado com as Roupas", "Lava Roupas Líquido")
        # Correção: Detergente Carrefour
        self._testar("Detergente Líquido Carrefour Neutro", "Limpeza", "Limpadores e Detergentes", "Detergente Líquido")
        # Correção: Mini Bolo Kim
        self._testar("Mini Bolo Kim de Chocolate com Recheio de Baunilha 80g", "Padaria e Confeitaria", "Pães e Bolos", "Mini Bolo")
        # Correção: Leite Condensado Moça
        self._testar("Leite Condensado Moça Tradicional", "Frios e Laticínios", "Leites", "Leite Condensado")
        # Correção: Açúcar Caravelas
        self._testar("Açúcar Refinado Caravelas 1kg", "Mercearia e Despensa", "Açúcar e Adoçantes", "Açúcar")
        # Correção: Nescau Protein
        self._testar("Bebida Láctea Uht Chocolate Zero Lactose Nescau Protein", "Frios e Laticínios", "Iogurtes e Lácteos", "Bebida Láctea")
        # Correção: Hambúrguer VPJ
        self._testar("Hambúrguer Quadrado Angus Vpj", "Congelados e Pratos Prontos", "Pratos Prontos Congelados", "Hambúrguer de Carne Bovina")
        # Correção: Hidratante Monange
        self._testar("Hidratante Monange Firmador Q10 Vitamina C + e Pele Extra-seca com Ação Desodorante", "Higiene e Cuidado Pessoal", "Corpo e Banho", "Hidratante Corporal")
        # Correção: Almôndega Fazenda Futuro
        self._testar("Almondega Fazenda Futuro 275g", "Congelados e Pratos Prontos", "Pratos Prontos Congelados", "Almôndega Vegetal")
        # Correção: Amaciante Downy (Padronização de subcategoria)
        self._testar("Amaciante Downy Concentrado Brisa de Verão 500ml", "Limpeza", "Cuidado com as Roupas", "Amaciante")
        self._testar("Gatos Adultos Sabor Peixe Branco Ao Molho Friskies Sachê", "Pet Shop", "Alimentos para Gatos", "Ração Úmida")
        self._testar("Gatos Adultos Sabor Atum Ao Molho Friskies Sachê", "Pet Shop", "Alimentos para Gatos", "Ração Úmida")
        self._testar("Iscas Mata Ratos Mortein Raticida", "Limpeza", "Inseticidas e Repelentes", "Geral")
        self._testar("Sabão em Barra Ypê Neutro", "Limpeza", "Limpadores e Detergentes", "Geral")
        self._testar("Harpic Pedra Sanitária Aroma Plus Pinho 40% de Desconto", "Limpeza", "Limpeza Sanitária", "Geral")
        self._testar("Harpic Pedra Perfumada Floral Delicado", "Limpeza", "Limpeza Sanitária", "Geral")
        self._testar("Esponja Multiuso Tinindo 4 Unidades - Embalagem Promocional", "Limpeza", "Acessórios de Limpeza", "Esponja Multiuso")
        self._testar("Limpador para Limpeza Pesada Original, Veja,", "Limpeza", "Limpeza Geral e Banheiro", "Geral")
        self._testar("Papel Manteiga Wyda 29cm x 7,5m", "Bazar e Utilidades", "Papéis e Filmes Culinários", "Papel Manteiga")
        self._testar("Suco Néctar Maratá Pêssego", "Bebidas", "Sucos e Refrescos", "Suco")
        self._testar("Macarrão Instantâneo Cup Noodles Yakissoba", "Mercearia e Despensa", "Massas e Molhos", "Macarrão")
        self._testar("Detergente em Pó Urca Coco", "Limpeza", "Limpadores e Detergentes", "Detergente em Pó")
        self._testar("Tempero Baiano", "Mercearia e Despensa", "Temperos e Condimentos", "Tempero")
        self._testar("Pó para Refresco Sabor Limão Maratá", "Bebidas", "Sucos e Refrescos", "Suco")
        self._testar("Pão de Forma Integral Visconti", "Padaria e Confeitaria", "Pães e Bolos", "Padaria")
        self._testar("Torrada Visconti Tradicional", "Padaria e Confeitaria", "Pães e Bolos", "Padaria")
        self._testar("Chá Branco Pitaya e Amora", "Mercearia e Despensa", "Cafés, Chás e Achocolatados", "Cafés, Chás")
        self._testar("Limpa Alumínio Luar", "Limpeza", "Limpeza de Metais", "Limpa Alumínio")
        self._testar("Desodorizador Aerossol Bom Ar Flor de Algodão", "Limpeza", "Aromatizantes e Desinfetantes", "Desodorizador de Ambiente Aerossol")
        self._testar("Creme Dental Sorriso Tripla Limpeza Completa", "Higiene e Cuidado Pessoal", "Higiene Oral", "Creme Dental")
        self._testar("Pão de Forma Tradicional Bauducco", "Padaria e Confeitaria", "Pães e Bolos", "Padaria")
        self._testar("Refrigerante Schweppes Citrus", "Bebidas", "Refrigerantes", "Refrigerantes")
        self._testar("Gatos Adultos Sabor Atum Ao Molho Friskies Sachê", "Pet Shop", "Alimentos para Gatos", "Ração Úmida")
        self._testar("Gatos Adultos Sabor Peixe Branco Ao Molho Friskies Sachê", "Pet Shop", "Alimentos para Gatos", "Ração Úmida")

if __name__ == "__main__":
    unittest.main(verbosity=2)