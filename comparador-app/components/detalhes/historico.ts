import { Oferta, PontoHistoricoApi } from '../../types';
import { getPrecoCondicional, getUnidadesPack, vendidoPorPeso } from '../../precos';

// Limpa o histórico cru da API e resume por mercado, na mesma base de preço do topo do modal
// (por unidade do pack ou por kg, sem o preço de CPF/clube/compra mínima).

// Ponto fora de 2,5x o preço atual do mercado é tratado como erro (pack ou EAN trocado).
// Mesmo limiar de ofertas_sql.py, que descarta ofertas fora de 2,5x a mediana.
const FATOR_FORA_DA_CURVA = 2.5;
const MESMO_PRECO = 0.005;

export interface PontoHistorico {
  data: string; // AAAA-MM-DD
  preco: number;
  promocao: boolean;
}

export interface HistoricoMercado {
  mercado: string;
  atual: number;
  emPromocao: boolean;
  desde: string | null; // desde quando o preço atual aparece no histórico
  anterior: PontoHistorico | null;
  variacao: number | null; // fração: 0.15 = subiu 15%
  pontos: PontoHistorico[]; // um por mudança de preço, mais recente primeiro
  conferidoEm: string | null; // última vez que o preço foi lido no site (AAAA-MM-DD)
}

export interface ResumoHistorico {
  comMudanca: HistoricoMercado[];
  semMudanca: { mercados: string[]; desde: string | null };
  minimo: { preco: number; mercado: string; data: string } | null;
  melhorAtual: number | null;
  ocultos: number;
}

// "2026-10-05 17:59:39" ou "05/10/2026 17:59:39" -> "2026-10-05" (null se não reconhecer)
export const normalizarData = (dataStr?: string): string | null => {
  const parte = String(dataStr || '').trim().split(/[ T]/)[0];
  let m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(parte);
  if (m) return `${m[1]}-${m[2]}-${m[3]}`;
  m = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(parte);
  if (m) return `${m[3]}-${m[2]}-${m[1]}`;
  return null;
};

// "2026-10-05" -> "05/10"
export const formatarDiaMes = (data: string | null): string => {
  if (!data) return '';
  const [, mes, dia] = data.split('-');
  return `${dia}/${mes}`;
};

// Chave para ordenar por data e hora; o texto ISO ordena certo
const chaveTempo = (dataStr: string): string => {
  const data = normalizarData(dataStr) || '';
  const hora = String(dataStr).trim().split(/[ T]/)[1] || '00:00:00';
  return `${data} ${hora}`;
};

// Preço de uma embalagem num ponto do histórico, sem o preço condicional quando a oferta atual tem um.
// Sem preco_varejo/preco_atacado (API antiga), usa o preco já calculado pela API.
const precoDoPonto = (p: PontoHistoricoApi, condicional: boolean): { preco: number; promocao: boolean } => {
  const pv = Number(p.preco_varejo) || 0;
  const pa = Number(p.preco_atacado) || 0;
  if (pv <= 0 && pa <= 0) return { preco: Number(p.preco) || 0, promocao: false };
  if (pa > 0 && pv > 0 && pa < pv) {
    return condicional ? { preco: pv, promocao: false } : { preco: pa, promocao: true };
  }
  return { preco: pv > 0 ? pv : pa, promocao: false };
};

const resumirMercado = (oferta: Oferta, brutos: PontoHistoricoApi[]): { resumo: HistoricoMercado; ocultos: number } => {
  const condicional = !!getPrecoCondicional(oferta);
  const unidades = getUnidadesPack(oferta);
  const pv = oferta.Preco_Varejo || 0;
  const pa = oferta.Preco_Atacado || 0;
  const emPromocao = !condicional && pa > 0 && pv > 0 && pa < pv;
  const atual = (emPromocao ? pa : condicional ? pv : Math.max(pa, pv)) / unidades;

  let ocultos = 0;
  const ordenados = [...brutos].sort((a, b) => chaveTempo(a.data_hora).localeCompare(chaveTempo(b.data_hora)));
  const trechos: PontoHistorico[] = []; // do mais antigo ao mais recente, um por mudança
  for (const bruto of ordenados) {
    const data = normalizarData(bruto.data_hora);
    const { preco: porEmbalagem, promocao } = precoDoPonto(bruto, condicional);
    const preco = porEmbalagem / unidades;
    if (!data || !(preco > 0)) continue;
    if (atual > 0 && (preco > atual * FATOR_FORA_DA_CURVA || preco < atual / FATOR_FORA_DA_CURVA)) {
      ocultos++;
      continue;
    }
    const ultimo = trechos[trechos.length - 1];
    if (ultimo && Math.abs(ultimo.preco - preco) < MESMO_PRECO) continue; // fica a data mais antiga do trecho
    trechos.push({ data, preco, promocao });
  }

  const ultimo = trechos[trechos.length - 1];
  const ultimoEhAtual = !!ultimo && Math.abs(ultimo.preco - atual) < MESMO_PRECO;
  const anterior = ultimoEhAtual ? trechos[trechos.length - 2] || null : ultimo || null;
  return {
    ocultos,
    resumo: {
      mercado: oferta.Mercado,
      atual,
      emPromocao,
      desde: ultimoEhAtual ? ultimo.data : null,
      anterior,
      variacao: anterior && anterior.preco > 0 ? (atual - anterior.preco) / anterior.preco : null,
      pontos: [...trechos].reverse(),
      conferidoEm: normalizarData(oferta.Data_Atualizacao),
    },
  };
};

// Resume o histórico por mercado, na ordem das ofertas. Mercado sem oferta atual fica de fora:
// não há com o que comparar e esses pontos costumam ser de EAN já corrigido.
export const resumirHistorico = (historico: PontoHistoricoApi[], ofertas: Oferta[]): ResumoHistorico => {
  const porMercado = new Map<string, PontoHistoricoApi[]>();
  for (const p of historico || []) {
    if (!p || !p.mercado) continue;
    (porMercado.get(p.mercado) || porMercado.set(p.mercado, []).get(p.mercado)!).push(p);
  }

  const comMudanca: HistoricoMercado[] = [];
  const semMudanca: string[] = [];
  let desdeSemMudanca: string | null = null;
  let ocultos = 0;
  let minimo: ResumoHistorico['minimo'] = null;
  let melhorAtual: number | null = null;
  // Só compara mercados na mesma unidade da melhor oferta (kg com kg, unidade com unidade)
  const porPeso = vendidoPorPeso(ofertas?.[0]);
  const vistos = new Set<string>();

  for (const oferta of ofertas || []) {
    if (vistos.has(oferta.Mercado)) continue;
    vistos.add(oferta.Mercado);
    const r = resumirMercado(oferta, porMercado.get(oferta.Mercado) || []);
    ocultos += r.ocultos;
    const m = r.resumo;
    if (m.anterior) {
      comMudanca.push(m);
    } else {
      semMudanca.push(m.mercado);
      if (m.desde && (!desdeSemMudanca || m.desde > desdeSemMudanca)) desdeSemMudanca = m.desde;
    }
    if (vendidoPorPeso(oferta) !== porPeso || !(m.atual > 0)) continue;
    if (melhorAtual === null || m.atual < melhorAtual) melhorAtual = m.atual;
    for (const p of m.pontos) {
      if (!minimo || p.preco < minimo.preco - MESMO_PRECO || (Math.abs(p.preco - minimo.preco) < MESMO_PRECO && p.data > minimo.data)) {
        minimo = { preco: p.preco, mercado: m.mercado, data: p.data };
      }
    }
  }

  return { comMudanca, semMudanca: { mercados: semMudanca, desde: desdeSemMudanca }, minimo, melhorAtual, ocultos };
};
