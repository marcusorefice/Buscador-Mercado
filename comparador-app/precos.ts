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
