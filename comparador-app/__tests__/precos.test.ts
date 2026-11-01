import {
  descreverPeso,
  getAvisoCondicao,
  getPrecoCondicional,
  getPrecoEfetivo,
  getQtdMinimaAtacado,
  getUnidadesPack,
  melhorCombinacao,
  vendidoPorPeso,
} from '../precos';
import { Oferta } from '../types';

const oferta = (campos: Partial<Oferta> = {}): Oferta => ({
  Mercado: 'Carrefour',
  Preco_Varejo: 10,
  Preco_Atacado: 0,
  Nome_Original: '',
  Condicao: '',
  Data_Atualizacao: '',
  ...campos,
});

// Exemplos que se repetem
const pack4 = (campos: Partial<Oferta> = {}) => oferta({ Medida: 'UN', Qtd_Valor: '4', Unidade: 'UN', Preco_Varejo: 20, ...campos });
const queijo200g = (campos: Partial<Oferta> = {}) => oferta({ Unidade: 'KG', Medida: 'G', Qtd_Valor: '200', Preco_Varejo: 29.98, ...campos });

describe('getQtdMinimaAtacado', () => {
  it('lê a quantidade de "A PARTIR DE N"', () => {
    expect(getQtdMinimaAtacado(oferta({ Condicao: 'A PARTIR DE 6 UN' }))).toBe(6);
    expect(getQtdMinimaAtacado(oferta({ Condicao: 'a partir de 3' }))).toBe(3);
  });

  it('devolve null sem quantidade mínima', () => {
    expect(getQtdMinimaAtacado(oferta())).toBeNull();
    expect(getQtdMinimaAtacado(oferta({ Condicao: 'LEVE 3 PAGUE 2' }))).toBeNull();
    expect(getQtdMinimaAtacado(null)).toBeNull();
  });
});

describe('vendidoPorPeso', () => {
  it('é true só quando a unidade é KG (sem diferenciar maiúsculas)', () => {
    expect(vendidoPorPeso(oferta({ Unidade: 'KG' }))).toBe(true);
    expect(vendidoPorPeso(oferta({ Unidade: 'kg' }))).toBe(true);
    expect(vendidoPorPeso(oferta({ Unidade: 'UN' }))).toBe(false);
    expect(vendidoPorPeso(oferta())).toBe(false);
    expect(vendidoPorPeso(undefined)).toBe(false);
  });
});

describe('getUnidadesPack', () => {
  it('conta as unidades de um pack vendido com o EAN da unidade', () => {
    expect(getUnidadesPack(pack4())).toBe(4);
  });

  it('usa 1 quando a quantidade do pack não é um inteiro válido', () => {
    expect(getUnidadesPack(oferta({ Medida: 'UN', Qtd_Valor: '0' }))).toBe(1);
    expect(getUnidadesPack(oferta({ Medida: 'UN', Qtd_Valor: '2.5' }))).toBe(1);
    expect(getUnidadesPack(oferta({ Medida: 'UN', Qtd_Valor: '' }))).toBe(1);
    expect(getUnidadesPack(oferta({ Medida: 'UN' }))).toBe(1);
  });

  it('devolve o peso da peça em kg para item vendido por peso', () => {
    expect(getUnidadesPack(queijo200g())).toBeCloseTo(0.2);
    expect(getUnidadesPack(oferta({ Unidade: 'KG', Medida: 'KG', Qtd_Valor: '1.8' }))).toBeCloseTo(1.8);
  });

  it('usa 1 para peso zerado', () => {
    expect(getUnidadesPack(oferta({ Unidade: 'KG', Medida: 'G', Qtd_Valor: '0' }))).toBe(1);
  });

  it('não trata pacote de 1 kg vendido por unidade como peso', () => {
    expect(getUnidadesPack(oferta({ Unidade: 'UN', Medida: 'KG', Qtd_Valor: '1' }))).toBe(1);
  });

  it('usa 1 para oferta ausente', () => {
    expect(getUnidadesPack(null)).toBe(1);
  });
});

describe('descreverPeso', () => {
  it('mostra gramas abaixo de 1 kg e kg com vírgula acima', () => {
    expect(descreverPeso(0.2)).toBe('~200 g');
    expect(descreverPeso(0.5)).toBe('~500 g');
    expect(descreverPeso(1.8)).toBe('~1,8 kg');
    expect(descreverPeso(2)).toBe('~2 kg');
  });
});

describe('getPrecoEfetivo', () => {
  it('devolve 0 sem oferta ou sem preço', () => {
    expect(getPrecoEfetivo(null)).toBe(0);
    expect(getPrecoEfetivo(oferta({ Preco_Varejo: 0, Preco_Atacado: 0 }))).toBe(0);
  });

  it('usa o menor entre varejo e atacado sem condição', () => {
    expect(getPrecoEfetivo(oferta({ Preco_Varejo: 10 }))).toBe(10);
    expect(getPrecoEfetivo(oferta({ Preco_Varejo: 10, Preco_Atacado: 8 }))).toBe(8);
    expect(getPrecoEfetivo(oferta({ Preco_Varejo: 8, Preco_Atacado: 10 }))).toBe(8);
    expect(getPrecoEfetivo(oferta({ Preco_Varejo: 0, Preco_Atacado: 7 }))).toBe(7);
  });

  describe('atacado com quantidade mínima', () => {
    const atacado6 = oferta({ Preco_Varejo: 10, Preco_Atacado: 8, Condicao: 'A PARTIR DE 6 UN' });

    it('cobra varejo abaixo do mínimo', () => {
      expect(getPrecoEfetivo(atacado6, 1)).toBe(10);
      expect(getPrecoEfetivo(atacado6, 5)).toBe(10);
    });

    it('cobra atacado a partir do mínimo', () => {
      expect(getPrecoEfetivo(atacado6, 6)).toBe(8);
      expect(getPrecoEfetivo(atacado6, 12)).toBe(8);
    });

    it('em pack, conta o mínimo em embalagens, não em unidades', () => {
      const packAtacado = pack4({ Preco_Atacado: 16, Condicao: 'A PARTIR DE 2 UN' });
      expect(getPrecoEfetivo(packAtacado, 4)).toBe(5); // 1 pack a R$ 20
      expect(getPrecoEfetivo(packAtacado, 8)).toBe(4); // 2 packs a R$ 16
    });
  });

  it('nunca aplica atacado de CPF/clube/cartão, em qualquer quantidade', () => {
    const cpf = oferta({ Preco_Varejo: 10, Preco_Atacado: 8, Condicao: 'CPF NA NOTA' });
    expect(getPrecoEfetivo(cpf, 1)).toBe(10);
    expect(getPrecoEfetivo(cpf, 10)).toBe(10);
    expect(getPrecoEfetivo(oferta({ Preco_Varejo: 10, Preco_Atacado: 8, Condicao: 'CLUBE CARREFOUR' }))).toBe(10);
    expect(getPrecoEfetivo(oferta({ Preco_Varejo: 10, Preco_Atacado: 8, Condicao: 'Cartão Carrefour' }))).toBe(10);
  });

  it('não aplica "LEVE 3 PAGUE 2" nem levando 3 (não tem "A PARTIR DE", cai na condição especial)', () => {
    const leve3 = oferta({ Preco_Varejo: 10, Preco_Atacado: 6.67, Condicao: 'LEVE 3 PAGUE 2' });
    expect(getPrecoEfetivo(leve3, 3)).toBe(10);
  });

  describe('pack', () => {
    it('levando 1, paga o pack inteiro', () => {
      expect(getPrecoEfetivo(pack4(), 1)).toBe(20);
    });

    it('levando múltiplos do pack, sai o preço da unidade', () => {
      expect(getPrecoEfetivo(pack4(), 4)).toBe(5);
      expect(getPrecoEfetivo(pack4(), 8)).toBe(5);
    });

    it('arredonda para cima o número de packs', () => {
      expect(getPrecoEfetivo(pack4(), 5)).toBe(8); // 2 packs (R$ 40) por 5 unidades
    });
  });

  describe('venda por peso', () => {
    it('devolve o preço por kg a partir do preço da peça', () => {
      expect(getPrecoEfetivo(queijo200g(), 1)).toBeCloseTo(149.9);
    });

    it('trata quantidade abaixo de 1 como 1', () => {
      expect(getPrecoEfetivo(queijo200g(), 0.5)).toBeCloseTo(149.9);
      expect(getPrecoEfetivo(oferta({ Preco_Varejo: 10 }), 0)).toBe(10);
    });
  });
});

// O preço por unidade (ou por kg) de precos.ts tem de bater com SQL_PRECO_EFETIVO de ofertas_sql.py, que gera o
// Menor_Preco da API. Os valores esperados abaixo foram calculados à mão pela regra do SQL:
// (menor entre varejo e atacado, sem o atacado com condição especial) / unidades do pack.
// Levando exatamente uma embalagem, getPrecoEfetivo precisa dar o mesmo número.
describe('espelho de ofertas_sql.py (preço comparável)', () => {
  const casos: [string, Oferta, number][] = [
    ['só varejo', oferta({ Preco_Varejo: 10 }), 10],
    ['só atacado', oferta({ Preco_Varejo: 0, Preco_Atacado: 7 }), 7],
    ['atacado sem condição', oferta({ Preco_Varejo: 10, Preco_Atacado: 8 }), 8],
    ['atacado com mínimo', oferta({ Preco_Varejo: 10, Preco_Atacado: 8, Condicao: 'A PARTIR DE 6 UN' }), 10],
    ['atacado com CPF', oferta({ Preco_Varejo: 10, Preco_Atacado: 8, Condicao: 'com cpf' }), 10],
    ['pack de 4', pack4(), 5],
    ['pack de 4 com atacado sem condição', pack4({ Preco_Atacado: 16 }), 4],
    ['pack com quantidade "0"', oferta({ Medida: 'UN', Qtd_Valor: '0', Preco_Varejo: 10 }), 10],
    ['peça de 200 g', queijo200g(), 149.9],
    ['peça de 1.5 kg', oferta({ Unidade: 'kg', Medida: 'KG', Qtd_Valor: '1.5', Preco_Varejo: 30 }), 20],
    ['peso com vírgula não é lido', oferta({ Unidade: 'KG', Medida: 'KG', Qtd_Valor: '0,2', Preco_Varejo: 30 }), 30],
    ['peso "0" vira 1', oferta({ Unidade: 'KG', Medida: 'G', Qtd_Valor: '0', Preco_Varejo: 30 }), 30],
    ['UN com unidade KG conta como pack', oferta({ Unidade: 'KG', Medida: 'UN', Qtd_Valor: '4', Preco_Varejo: 20 }), 5],
  ];

  it.each(casos)('%s', (_nome, o, esperado) => {
    expect(getPrecoEfetivo(o, getUnidadesPack(o))).toBeCloseTo(esperado);
  });
});

// Divergências já conhecidas, documentadas como o código se comporta HOJE. A correção é uma etapa separada.
describe('divergências conhecidas (comportamento atual)', () => {
  // O ProductDetailsModal divide o preço por Qtd_Valor quando Unidade é UN e Medida é UN, PCT ou CX.
  // precos.ts (card e lista) e ofertas_sql.py (Menor_Preco) só dividem quando Medida é UN.
  // Resultado: "PCT 6" de R$ 12 aparece como R$ 2 no modal e R$ 12 no card e na lista.
  it('PCT/CX: precos.ts não divide pela quantidade', () => {
    expect(getUnidadesPack(oferta({ Unidade: 'UN', Medida: 'PCT', Qtd_Valor: '6' }))).toBe(1);
    expect(getUnidadesPack(oferta({ Unidade: 'UN', Medida: 'CX', Qtd_Valor: '12' }))).toBe(1);
    expect(getPrecoEfetivo(oferta({ Unidade: 'UN', Medida: 'PCT', Qtd_Valor: '6', Preco_Varejo: 12 }))).toBe(12);
  });

  it.todo('PCT/CX: unificar a regra entre ProductDetailsModal, precos.ts e ofertas_sql.py');

  // parseFloat("200g") é 200; a regex do SQL ('^[0-9]+([.][0-9]+)?$') não aceita o sufixo e usa 1.
  it('peso com sufixo no Qtd_Valor: precos.ts lê, o SQL não', () => {
    expect(getUnidadesPack(oferta({ Unidade: 'KG', Medida: 'G', Qtd_Valor: '200g' }))).toBeCloseTo(0.2);
  });
});

describe('getPrecoCondicional', () => {
  it('devolve o preço de CPF/clube por unidade e o texto da condição', () => {
    expect(getPrecoCondicional(oferta({ Preco_Varejo: 10, Preco_Atacado: 8, Condicao: 'CLUBE CARREFOUR' })))
      .toEqual({ preco: 8, condicao: 'com CLUBE CARREFOUR' });
  });

  it('descreve a quantidade mínima', () => {
    expect(getPrecoCondicional(oferta({ Preco_Varejo: 10, Preco_Atacado: 8, Condicao: 'A PARTIR DE 6 UN' })))
      .toEqual({ preco: 8, condicao: 'levando 6 un' });
  });

  it('divide pelo pack e pelo peso, como o preço principal', () => {
    expect(getPrecoCondicional(pack4({ Preco_Varejo: 40, Preco_Atacado: 32, Condicao: 'CPF' }))?.preco).toBe(8);
    expect(getPrecoCondicional(oferta({ Unidade: 'KG', Medida: 'G', Qtd_Valor: '500', Preco_Varejo: 20, Preco_Atacado: 15, Condicao: 'CLUBE' }))?.preco)
      .toBeCloseTo(30);
  });

  it('devolve null quando o preço menor vale para todos ou não existe', () => {
    expect(getPrecoCondicional(oferta({ Preco_Varejo: 10, Preco_Atacado: 8 }))).toBeNull();
    expect(getPrecoCondicional(oferta({ Preco_Varejo: 8, Preco_Atacado: 10, Condicao: 'CPF' }))).toBeNull();
    expect(getPrecoCondicional(oferta({ Preco_Varejo: 10, Condicao: 'CPF' }))).toBeNull();
    expect(getPrecoCondicional(null)).toBeNull();
  });
});

describe('getAvisoCondicao', () => {
  it('não mostra aviso para preço normal', () => {
    expect(getAvisoCondicao(oferta())).toBeNull();
    expect(getAvisoCondicao(null)).toBeNull();
  });

  it('explica a peça de item vendido por peso', () => {
    expect(getAvisoCondicao(queijo200g(), 1)).toBe('Vendido em peça de ~200 g (R$ 29,98 cada) · 5 peças');
  });

  it('explica o pack e quantas unidades a pessoa leva', () => {
    expect(getAvisoCondicao(pack4(), 1)).toBe('Vendido em pack c/ 4 (R$ 20,00 o pack) · você leva 4 un');
    expect(getAvisoCondicao(pack4(), 4)).toBe('Vendido em pack c/ 4 (R$ 20,00 o pack)');
  });

  it('explica o atacado com quantidade mínima', () => {
    const atacado6 = oferta({ Preco_Varejo: 10, Preco_Atacado: 8, Condicao: 'A PARTIR DE 6 UN' });
    expect(getAvisoCondicao(atacado6, 1)).toBe('Levando 6 un sai R$ 8,00 cada');
    expect(getAvisoCondicao(atacado6, 6)).toBe('Preço de atacado (a partir de 6 un)');
  });

  it('explica o preço de CPF/clube', () => {
    expect(getAvisoCondicao(oferta({ Preco_Varejo: 10, Preco_Atacado: 8, Condicao: 'CPF NA NOTA' })))
      .toBe('Com CPF NA NOTA sai R$ 8,00 cada');
  });
});

describe('melhorCombinacao', () => {
  const item = (quantity: number, ...ofertas: Oferta[]) => ({ quantity, Ofertas: ofertas });
  const em = (Mercado: string, Preco_Varejo: number, campos: Partial<Oferta> = {}) => oferta({ Mercado, Preco_Varejo, ...campos });

  it('devolve null sem nenhuma oferta', () => {
    expect(melhorCombinacao([])).toBeNull();
    expect(melhorCombinacao([item(1)])).toBeNull();
  });

  const lista = [
    item(1, em('A', 10), em('B', 12)),
    item(1, em('A', 10), em('B', 5)),
    item(1, em('C', 1)),
  ];

  it('prefere a dupla que não deixa item faltando e, entre elas, a mais barata', () => {
    const r = melhorCombinacao(lista);
    expect(r?.mercados).toEqual(['B', 'C']);
    expect(r?.faltando).toBe(0);
    expect(r?.total).toBeCloseTo(18);
    expect(r?.porMercado.B).toHaveLength(2);
  });

  it('com maxMercados = 1, escolhe o mercado com menos faltando e menor total', () => {
    const r = melhorCombinacao(lista, 1);
    expect(r?.mercados).toEqual(['B']);
    expect(r?.faltando).toBe(1);
    expect(r?.total).toBeCloseTo(17);
  });

  it('considera o atacado quando a quantidade atinge o mínimo', () => {
    const atacado = em('A', 10, { Preco_Atacado: 8, Condicao: 'A PARTIR DE 6 UN' });
    expect(melhorCombinacao([item(6, atacado, em('B', 9))], 1)?.mercados).toEqual(['A']);
    expect(melhorCombinacao([item(6, atacado, em('B', 9))], 1)?.total).toBeCloseTo(48);
    expect(melhorCombinacao([item(5, atacado, em('B', 9))], 1)?.mercados).toEqual(['B']);
  });

  it('conta como faltando o item cuja única oferta tem preço zero', () => {
    const r = melhorCombinacao([item(1, em('A', 0))]);
    expect(r).toEqual({ mercados: [], total: 0, faltando: 1, porMercado: {} });
  });
});
