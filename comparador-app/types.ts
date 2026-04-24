export interface Product {
  id: number;
  Mercado: string | null;
  Categoria: string | null;
  Produto: string | null;
  Marca: string | null;
  Preco_Varejo: string | null;
  Preco_Atacado: string | null;
  Qtd_Valor: string | null;
  Medida: string | null;
  Unidade: string | null;
  Condicao: string | null;
  Validade: string | null;
  Data_Hora: string | null;
  Link_Imagem: string | null;
  subcategoria?: string | null;
  tipo_produto?: string | null;
}