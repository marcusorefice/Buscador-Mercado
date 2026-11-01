import React from 'react';
import { View, StyleSheet, Image, TouchableOpacity, ActivityIndicator } from 'react-native';
import { Text } from 'react-native-paper';
import { Oferta, PontoHistoricoApi } from '../../types';
import { getMarketLogo } from '../ProductCard';
import { formatPrice } from '../../formatar';
import { vendidoPorPeso } from '../../precos';
import { formatarDiaMes, HistoricoMercado, resumirHistorico } from './historico';

interface HistoricoPrecosProps {
  historico: PontoHistoricoApi[];
  ofertas: Oferta[];
  carregando: boolean;
  erro: boolean;
}

// Abaixo de 1% de diferença o preço conta como estável
const ESTAVEL = 0.01;

const Variacao: React.FC<{ variacao: number | null }> = ({ variacao }) => {
  if (variacao === null) return null;
  if (Math.abs(variacao) < ESTAVEL) return <Text style={styles.estavel}>estável</Text>;
  const subiu = variacao > 0;
  return (
    <Text style={subiu ? styles.subiu : styles.caiu}>
      {subiu ? '↑' : '↓'} {Math.round(Math.abs(variacao) * 100)}%
    </Text>
  );
};

// "antes R$ 4,79 · promoção acabou em 30/10" / "antes R$ 5,49 · desde 27/10"
const textoAnterior = (m: HistoricoMercado): string => {
  if (!m.anterior) return '';
  const antes = `antes R$ ${formatPrice(m.anterior.preco)}`;
  if (m.anterior.promocao && !m.emPromocao) return `${antes} · promoção acabou${m.desde ? ` em ${formatarDiaMes(m.desde)}` : ''}`;
  return m.desde ? `${antes} · desde ${formatarDiaMes(m.desde)}` : antes;
};

export const HistoricoPrecos: React.FC<HistoricoPrecosProps> = ({ historico, ofertas, carregando, erro }) => {
  const [abertos, setAbertos] = React.useState<string[]>([]);
  const resumo = React.useMemo(() => resumirHistorico(historico, ofertas), [historico, ofertas]);
  const sufixo = (mercado: string) => (vendidoPorPeso(ofertas.find(o => o.Mercado === mercado)) ? ' / kg' : '');
  const alternar = (mercado: string) =>
    setAbertos(atual => (atual.includes(mercado) ? atual.filter(m => m !== mercado) : [...atual, mercado]));

  const { comMudanca, semMudanca, minimo, melhorAtual, ocultos } = resumo;
  const semHistorico = historico.length === 0;

  return (
    <View>
      <View style={styles.cabecalho}>
        <Text style={styles.titulo}>📉 Histórico de Preços</Text>
        {carregando && <ActivityIndicator size="small" color="#E5293E" />}
      </View>

      {carregando ? null : erro ? (
        <Text style={styles.vazio}>Não foi possível carregar o histórico.</Text>
      ) : semHistorico ? (
        <Text style={styles.vazio}>Nenhum histórico registrado para este produto.</Text>
      ) : (
        <View style={styles.caixa}>
          {comMudanca.length > 0 && minimo && melhorAtual !== null && (
            <View style={styles.resumo}>
              <Text style={styles.resumoTexto}>
                Menor preço visto pelo app: <Text style={styles.negrito}>R$ {formatPrice(minimo.preco)}{sufixo(minimo.mercado)}</Text> no {minimo.mercado} ({formatarDiaMes(minimo.data)})
              </Text>
              <Text style={styles.resumoDetalhe}>
                {melhorAtual - minimo.preco < 0.005
                  ? 'Hoje o melhor preço é o menor já visto'
                  : `Hoje o melhor preço está ${Math.round(((melhorAtual - minimo.preco) / minimo.preco) * 100)}% acima desse mínimo`}
              </Text>
            </View>
          )}

          {comMudanca.length === 0 && (
            <Text style={styles.semMudanca}>
              Preços sem mudança{semMudanca.desde ? ` desde ${formatarDiaMes(semMudanca.desde)}` : ''} em todos os mercados.
            </Text>
          )}

          {comMudanca.map(m => {
            const aberto = abertos.includes(m.mercado);
            return (
              <View key={m.mercado} style={styles.mercado}>
                <TouchableOpacity style={styles.linha} onPress={() => alternar(m.mercado)} activeOpacity={0.7}>
                  <Image source={getMarketLogo(m.mercado)} style={styles.logo} resizeMode="contain" />
                  <View style={styles.meio}>
                    <Text style={styles.nomeMercado}>{m.mercado}</Text>
                    <Text style={styles.detalhe}>{textoAnterior(m)}</Text>
                  </View>
                  <View style={styles.direita}>
                    <Text style={styles.preco}>R$ {formatPrice(m.atual)}<Text style={styles.sufixo}>{sufixo(m.mercado)}</Text></Text>
                    <View style={styles.linhaVariacao}>
                      {m.emPromocao && <Text style={styles.promo}>PROMO</Text>}
                      <Variacao variacao={m.variacao} />
                    </View>
                  </View>
                  <Text style={styles.seta}>{aberto ? '▾' : '▸'}</Text>
                </TouchableOpacity>

                {aberto && (
                  <View style={styles.expandido}>
                    {m.pontos.map((p, i) => (
                      <View key={`${p.data}-${i}`} style={styles.ponto}>
                        <Text style={styles.pontoData}>{formatarDiaMes(p.data)}</Text>
                        <Text style={styles.pontoPreco}>R$ {formatPrice(p.preco)}</Text>
                        <Text style={styles.pontoNota}>
                          {p.promocao ? 'promoção' : i === m.pontos.length - 1 ? 'primeiro registro' : ''}
                        </Text>
                      </View>
                    ))}
                    {m.conferidoEm && <Text style={styles.conferido}>preço conferido no site em {formatarDiaMes(m.conferidoEm)}</Text>}
                  </View>
                )}
              </View>
            );
          })}

          {comMudanca.length > 0 && semMudanca.mercados.length > 0 && (
            <Text style={styles.semMudanca}>
              Sem mudança{semMudanca.desde ? ` desde ${formatarDiaMes(semMudanca.desde)}` : ''}: {semMudanca.mercados.join(', ')}
            </Text>
          )}

          {ocultos > 0 && (
            <Text style={styles.ocultos}>
              {ocultos === 1 ? '1 preço fora do normal foi ocultado' : `${ocultos} preços fora do normal foram ocultados`}
            </Text>
          )}
        </View>
      )}
    </View>
  );
};

const styles = StyleSheet.create({
  cabecalho: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 },
  titulo: { fontSize: 16, fontWeight: 'bold', color: '#444' },
  vazio: { color: '#888', fontStyle: 'italic', textAlign: 'center', marginTop: 10 },
  caixa: { backgroundColor: '#f9f9f9', borderRadius: 12, padding: 12, borderWidth: 1, borderColor: '#eee' },
  resumo: { paddingBottom: 10, marginBottom: 4, borderBottomWidth: 1, borderBottomColor: '#eee' },
  resumoTexto: { fontSize: 13, color: '#444' },
  resumoDetalhe: { fontSize: 12, color: '#888', marginTop: 2 },
  negrito: { fontWeight: 'bold', color: '#222' },
  mercado: { borderBottomWidth: 1, borderBottomColor: '#eee' },
  linha: { flexDirection: 'row', alignItems: 'center', paddingVertical: 10 },
  logo: { width: 32, height: 24, marginRight: 12 },
  meio: { flex: 1 },
  nomeMercado: { fontSize: 14, fontWeight: '600', color: '#444' },
  detalhe: { fontSize: 12, color: '#888' },
  direita: { alignItems: 'flex-end', marginLeft: 8 },
  preco: { fontSize: 16, fontWeight: 'bold', color: '#E5293E' },
  sufixo: { fontSize: 11, color: '#888', fontWeight: 'normal' },
  linhaVariacao: { flexDirection: 'row', alignItems: 'center', marginTop: 2 },
  promo: { fontSize: 10, fontWeight: 'bold', color: '#fff', backgroundColor: '#e67e22', borderRadius: 4, paddingHorizontal: 4, marginRight: 6, overflow: 'hidden' },
  subiu: { fontSize: 12, fontWeight: 'bold', color: '#c0392b' },
  caiu: { fontSize: 12, fontWeight: 'bold', color: '#27ae60' },
  estavel: { fontSize: 12, color: '#888' },
  seta: { fontSize: 14, color: '#999', marginLeft: 8, width: 12 },
  expandido: { paddingLeft: 44, paddingBottom: 10 },
  ponto: { flexDirection: 'row', alignItems: 'center', paddingVertical: 3 },
  pontoData: { fontSize: 12, color: '#666', width: 48 },
  pontoPreco: { fontSize: 13, fontWeight: '600', color: '#444', width: 80 },
  pontoNota: { fontSize: 11, color: '#e67e22' },
  conferido: { fontSize: 11, color: '#999', marginTop: 4 },
  semMudanca: { fontSize: 12, color: '#666', paddingTop: 10 },
  ocultos: { fontSize: 11, color: '#999', fontStyle: 'italic', paddingTop: 6 },
});
