import { formatarDiaMes, normalizarData, resumirHistorico } from '../components/detalhes/historico';
import { Oferta, PontoHistoricoApi } from '../types';

const oferta = (campos: Partial<Oferta> = {}): Oferta => ({
  Mercado: 'Carrefour',
  Preco_Varejo: 10,
  Preco_Atacado: 0,
  Nome_Original: '',
  Condicao: '',
  Data_Atualizacao: '2026-10-31 10:00:00',
  ...campos,
});

const ponto = (data_hora: string, preco_varejo: number, preco_atacado = 0, mercado = 'Carrefour'): PontoHistoricoApi => ({
  mercado,
  preco: preco_atacado > 0 && preco_atacado < preco_varejo ? preco_atacado : preco_varejo,
  preco_varejo,
  preco_atacado,
  data_hora,
});

describe('normalizarData e formatarDiaMes', () => {
  it('aceita ISO e dd/mm/aaaa', () => {
    expect(normalizarData('2026-10-05 17:59:39')).toBe('2026-10-05');
    expect(normalizarData('05/10/2026 17:59:39')).toBe('2026-10-05');
    expect(normalizarData('ontem')).toBeNull();
    expect(normalizarData(undefined)).toBeNull();
  });
  it('mostra dia/mês', () => {
    expect(formatarDiaMes('2026-10-05')).toBe('05/10');
    expect(formatarDiaMes(null)).toBe('');
  });
});

describe('resumirHistorico', () => {
  it('mercado com um preço só entra em "sem mudança"', () => {
    const r = resumirHistorico([ponto('2026-10-05 10:00:00', 10)], [oferta()]);
    expect(r.comMudanca).toHaveLength(0);
    expect(r.semMudanca).toEqual({ mercados: ['Carrefour'], desde: '2026-10-05' });
  });

  it('calcula anterior, variação e desde', () => {
    const r = resumirHistorico(
      [ponto('2026-10-30 10:00:00', 11.5), ponto('2026-10-05 10:00:00', 10)],
      [oferta({ Preco_Varejo: 11.5 })],
    );
    const m = r.comMudanca[0];
    expect(m.atual).toBeCloseTo(11.5);
    expect(m.anterior).toEqual({ data: '2026-10-05', preco: 10, promocao: false });
    expect(m.variacao).toBeCloseTo(0.15);
    expect(m.desde).toBe('2026-10-30');
    expect(m.pontos.map(p => p.data)).toEqual(['2026-10-30', '2026-10-05']);
  });

  it('junta pontos seguidos com o mesmo preço efetivo e fica com a data mais antiga', () => {
    // mudou o varejo, mas o menor preço (atacado) continuou 8
    const r = resumirHistorico(
      [ponto('2026-10-03 10:00:00', 10, 8), ponto('2026-10-12 10:00:00', 12, 8), ponto('2026-10-30 10:00:00', 12, 8)],
      [oferta({ Preco_Varejo: 12, Preco_Atacado: 8 })],
    );
    expect(r.comMudanca).toHaveLength(0);
    expect(r.semMudanca.desde).toBe('2026-10-03');
  });

  it('divide pelo pack, como o topo do modal', () => {
    const pack4 = { Medida: 'UN', Qtd_Valor: '4', Unidade: 'UN' };
    const r = resumirHistorico(
      [ponto('2026-10-05 10:00:00', 20), ponto('2026-10-30 10:00:00', 24)],
      [oferta({ ...pack4, Preco_Varejo: 24 })],
    );
    expect(r.comMudanca[0].atual).toBeCloseTo(6);
    expect(r.comMudanca[0].anterior?.preco).toBeCloseTo(5);
  });

  it('divide pelo peso da peça em item vendido por kg', () => {
    const queijo = { Unidade: 'KG', Medida: 'G', Qtd_Valor: '200' };
    const r = resumirHistorico(
      [ponto('2026-10-05 10:00:00', 20), ponto('2026-10-30 10:00:00', 30)],
      [oferta({ ...queijo, Preco_Varejo: 30 })],
    );
    expect(r.comMudanca[0].atual).toBeCloseTo(150);
    expect(r.comMudanca[0].anterior?.preco).toBeCloseTo(100);
  });

  it('não usa preço de CPF/clube quando a oferta atual tem condição especial', () => {
    const r = resumirHistorico(
      [ponto('2026-10-05 10:00:00', 10, 7), ponto('2026-10-30 10:00:00', 10, 6)],
      [oferta({ Preco_Varejo: 10, Preco_Atacado: 6, Condicao: 'COM CPF' })],
    );
    expect(r.comMudanca).toHaveLength(0);
    expect(r.semMudanca.mercados).toEqual(['Carrefour']);
    expect(r.minimo?.preco).toBe(10);
  });

  it('marca promoção e mostra o vai e volta como mudanças', () => {
    const r = resumirHistorico(
      [ponto('2026-10-03 10:00:00', 149.9), ponto('2026-10-06 10:00:00', 149.9, 115.9), ponto('2026-10-12 10:00:00', 149.9)],
      [oferta({ Preco_Varejo: 149.9 })],
    );
    const m = r.comMudanca[0];
    expect(m.emPromocao).toBe(false);
    expect(m.anterior).toEqual({ data: '2026-10-06', preco: 115.9, promocao: true });
    expect(m.pontos).toHaveLength(3);
  });

  it('oculta ponto fora de 2,5x o preço atual e conta quantos', () => {
    const r = resumirHistorico(
      [ponto('2026-10-03 10:00:00', 142.73), ponto('2026-10-05 10:00:00', 3.79), ponto('2026-10-06 10:00:00', 0.01)],
      [oferta({ Preco_Varejo: 3.79 })],
    );
    expect(r.ocultos).toBe(2);
    expect(r.comMudanca).toHaveLength(0);
    expect(r.semMudanca.desde).toBe('2026-10-05');
  });

  it('ignora mercado sem oferta atual e segue a ordem das ofertas', () => {
    const r = resumirHistorico(
      [
        ponto('2026-10-05 10:00:00', 5, 0, 'Boa'),
        ponto('2026-10-30 10:00:00', 4, 0, 'Boa'),
        ponto('2026-10-05 10:00:00', 6, 0, 'Covabra'),
        ponto('2026-10-30 10:00:00', 5, 0, 'Covabra'),
        ponto('2026-10-05 10:00:00', 1, 0, 'Tenda'),
      ],
      [oferta({ Mercado: 'Boa', Preco_Varejo: 4 }), oferta({ Mercado: 'Covabra', Preco_Varejo: 5 })],
    );
    expect(r.comMudanca.map(m => m.mercado)).toEqual(['Boa', 'Covabra']);
    expect(r.minimo).toEqual({ preco: 4, mercado: 'Boa', data: '2026-10-30' });
    expect(r.melhorAtual).toBe(4);
  });

  it('não compara o mínimo entre kg e unidade', () => {
    const r = resumirHistorico(
      [ponto('2026-10-05 10:00:00', 3, 0, 'Covabra'), ponto('2026-10-05 10:00:00', 9, 0, 'Oba')],
      [oferta({ Mercado: 'Oba', Unidade: 'KG', Medida: 'KG', Qtd_Valor: '1', Preco_Varejo: 9 }), oferta({ Mercado: 'Covabra', Preco_Varejo: 3 })],
    );
    expect(r.minimo).toEqual({ preco: 9, mercado: 'Oba', data: '2026-10-05' });
  });

  it('funciona com a API antiga (só preco) e com histórico vazio', () => {
    const antigo: PontoHistoricoApi[] = [
      { mercado: 'Carrefour', preco: 9, data_hora: '05/10/2026 10:00:00' },
      { mercado: 'Carrefour', preco: 10, data_hora: '30/10/2026 10:00:00' },
    ];
    expect(resumirHistorico(antigo, [oferta()]).comMudanca[0].anterior?.preco).toBe(9);
    const vazio = resumirHistorico([], [oferta()]);
    expect(vazio.comMudanca).toHaveLength(0);
    expect(vazio.semMudanca).toEqual({ mercados: ['Carrefour'], desde: null });
    expect(vazio.minimo).toBeNull();
  });

  it('histórico atrasado em relação à oferta: o último ponto vira o anterior', () => {
    const r = resumirHistorico([ponto('2026-10-05 10:00:00', 9)], [oferta({ Preco_Varejo: 10 })]);
    expect(r.comMudanca[0].desde).toBeNull();
    expect(r.comMudanca[0].anterior?.preco).toBe(9);
  });
});
