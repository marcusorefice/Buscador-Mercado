import { Oferta } from './types';

// Ex: Atacadão manda "A PARTIR DE 6 UN" quando o preço de atacado exige quantidade mínima
export const getQtdMinimaAtacado = (oferta?: Oferta | null): number | null => {
  const match = /A PARTIR DE\s+(\d+)/i.exec(oferta?.Condicao || '');
  return match ? parseInt(match[1], 10) : null;
};

// Preço unitário que a pessoa realmente paga levando `quantidade` unidades.
// O preço de atacado só vale se a quantidade atingir o mínimo exigido pelo mercado.
export const getPrecoEfetivo = (oferta?: Oferta | null, quantidade = 1): number => {
  if (!oferta) return 0;
  const pv = oferta.Preco_Varejo || 0;
  const pa = oferta.Preco_Atacado || 0;
  if (pa > 0 && pv > 0) {
    if (pa < pv) {
      const minimo = getQtdMinimaAtacado(oferta);
      if (minimo && quantidade < minimo) return pv;
    }
    return Math.min(pa, pv);
  }
  return Math.max(pa, pv);
};

type ItemDaLista = { quantity: number; Ofertas?: Oferta[] };

export interface Combinacao<T> {
  mercados: string[];
  total: number;
  faltando: number;
  porMercado: Record<string, { product: T; offer: Oferta }[]>;
}

// Testa cada mercado sozinho e cada par de mercados (até `maxMercados`, 1 ou 2) e devolve a
// combinação com menos itens faltando e, empatando, o menor total. Evita "rotas" de 5 mercados
// para economizar centavos.
export const melhorCombinacao = <T extends ItemDaLista>(itens: T[], maxMercados = 2): Combinacao<T> | null => {
  const mercados = Array.from(new Set(itens.flatMap(i => (i.Ofertas || []).map(o => o.Mercado))));
  if (mercados.length === 0) return null;

  const grupos: string[][] = mercados.map(m => [m]);
  if (maxMercados >= 2) {
    for (let i = 0; i < mercados.length; i++) {
      for (let j = i + 1; j < mercados.length; j++) grupos.push([mercados[i], mercados[j]]);
    }
  }

  let melhor: Combinacao<T> | null = null;
  for (const grupo of grupos) {
    let total = 0;
    let faltando = 0;
    const porMercado: Combinacao<T>['porMercado'] = {};
    for (const item of itens) {
      const qtd = item.quantity || 1;
      let escolhida: Oferta | null = null;
      let preco = Infinity;
      for (const o of item.Ofertas || []) {
        if (!grupo.includes(o.Mercado)) continue;
        const p = getPrecoEfetivo(o, qtd);
        if (p > 0 && p < preco) { preco = p; escolhida = o; }
      }
      if (!escolhida) { faltando++; continue; }
      total += preco * qtd;
      (porMercado[escolhida.Mercado] = porMercado[escolhida.Mercado] || []).push({ product: item, offer: escolhida });
    }
    const candidata = { mercados: Object.keys(porMercado), total, faltando, porMercado };
    if (!melhor || faltando < melhor.faltando || (faltando === melhor.faltando && total < melhor.total - 0.005)) {
      melhor = candidata;
    }
  }
  return melhor;
};

// Texto curto explicando a condição do preço exibido (ou null se for preço normal)
export const getAvisoCondicao = (oferta?: Oferta | null, quantidade = 1): string | null => {
  if (!oferta) return null;
  const pv = oferta.Preco_Varejo || 0;
  const pa = oferta.Preco_Atacado || 0;
  const minimo = getQtdMinimaAtacado(oferta);
  if (minimo && pa > 0 && pa < pv) {
    return quantidade >= minimo
      ? `Preço de atacado (a partir de ${minimo} un)`
      : `Levando ${minimo} un sai R$ ${pa.toFixed(2).replace('.', ',')} cada`;
  }
  const condicao = (oferta.Condicao || '').toUpperCase();
  if (pa > 0 && pa < pv && /CPF|CLUBE|CART[AÃ]O|MEU /.test(condicao)) {
    return `Preço com ${oferta.Condicao}`;
  }
  return null;
};
