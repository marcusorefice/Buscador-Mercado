export interface Oferta {
  Mercado: string;
  Preco_Varejo: number;
  Preco_Atacado: number;
  Nome_Original: string;
  Condicao: string;
  Data_Atualizacao: string;
  Link_PDP?: string;
  Qtd_Valor?: string;
  Medida?: string;
  Unidade?: string;
}
export interface Product {
  EAN: string;
  Produto_Ouro: string;
  Categoria_Ouro: string;
  Marca: string;
  Imagem: string;
  Tags: string[];
  Menor_Preco: number;
  Ofertas: Oferta[];
  weight?: string;
  volume?: string;
  unidade_medida?: string;
  Categoria?: string; // para não quebrar filtro antigo
}
