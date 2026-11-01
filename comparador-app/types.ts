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
  Preco_Unitario?: number; // preço por kg ou litro, quando a API consegue saber
  Unidade_Ref?: string; // 'kg' ou 'L'
}
export interface Product {
  EAN: string;
  Produto_Ouro: string;
  Categoria_Ouro: string;
  Marca: string;
  Imagem: string;
  Tags: string[];
  Menor_Preco: number;
  Preco_Unitario?: number;
  Unidade_Ref?: string;
  Qtd_Mercados?: number; // em quantos mercados existe (com filtro de mercado, Ofertas traz só o filtrado)
  Ofertas: Oferta[];
  weight?: string;
  volume?: string;
  unidade_medida?: string;
  Categoria?: string; // para não quebrar filtro antigo
}

// Um ponto de GET /produtos/{ean}/historico. preco = menor entre varejo e atacado da embalagem;
// preco_varejo e preco_atacado vêm da API nova (o app trata a ausência deles).
export interface PontoHistoricoApi {
  mercado: string;
  preco: number;
  preco_varejo?: number;
  preco_atacado?: number;
  data_hora: string;
}
