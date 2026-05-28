import React, { useMemo, useState } from 'react';
import { View, StyleSheet, ScrollView, Modal, Image, TouchableOpacity } from 'react-native';
import { Text, IconButton, Divider, Button, Chip } from 'react-native-paper';
import { useShoppingListStore } from './useShoppingListStore';
import { Product } from '../types';

interface Props {
  visible: boolean;
  onDismiss: () => void;
}

export const ShoppingListModal = ({ visible, onDismiss }: Props) => {
  const { list, toggleProduct, clearList, updateQuantity, setPinnedMarket } = useShoppingListStore();
  const [expandedMarkets, setExpandedMarkets] = useState<Record<string, boolean>>({});
  const [expandedItems, setExpandedItems] = useState<Record<string, boolean>>({});

  const toggleExpandedMarket = (marketName: string) => {
    setExpandedMarkets(prev => ({ ...prev, [marketName]: !prev[marketName] }));
  };

  const toggleExpandItem = (key: string) => {
    setExpandedItems(prev => ({ ...prev, [key]: !prev[key] }));
  };

  // Função interna para pegar o melhor preço da oferta
  const getBestPrice = (oferta: any) => {
    const pv = oferta.Preco_Varejo || 0;
    const pa = oferta.Preco_Atacado || 0;
    if (pa > 0 && pv > 0) return Math.min(pa, pv);
    return Math.max(pa, pv);
  };

  const getBestAlternative = (product: Product) => {
    if (!product.Ofertas || product.Ofertas.length === 0) return null;
    let bestOffer = product.Ofertas[0];
    let bestPrice = getBestPrice(bestOffer);
    for (let i = 1; i < product.Ofertas.length; i++) {
      const price = getBestPrice(product.Ofertas[i]);
      if (price < bestPrice) {
        bestPrice = price;
        bestOffer = product.Ofertas[i];
      }
    }
    return { market: bestOffer.Mercado, price: bestPrice };
  };

  // Carrinho Otimizado (Multi-Mercados + Customizações do Usuário)
  const optimizedCart = useMemo(() => {
    let total = 0;
    const markets: Record<string, { product: typeof list[0], offer: any }[]> = {};
    let missingCount = 0;

    list.forEach(item => {
      if (!item.Ofertas || item.Ofertas.length === 0) {
        missingCount++;
        return;
      }

      let chosenOffer = null;
      if (item.pinnedMarket) {
        chosenOffer = item.Ofertas.find(o => o.Mercado === item.pinnedMarket);
      }
      if (!chosenOffer) {
        chosenOffer = item.Ofertas.reduce((best, curr) => getBestPrice(curr) < getBestPrice(best) ? curr : best);
      }

      if (chosenOffer) {
        total += getBestPrice(chosenOffer) * item.quantity;
        if (!markets[chosenOffer.Mercado]) markets[chosenOffer.Mercado] = [];
        markets[chosenOffer.Mercado].push({ product: item, offer: chosenOffer });
      } else {
        missingCount++;
      }
    });

    return { total, markets, missingCount };
  }, [list]);

  // MÁGICA: Cálculo do carrinho e Ranking por mercado
  const marketRanking = useMemo(() => {
    if (list.length === 0) return [];

    const allMarkets = new Set<string>();
    list.forEach(item => {
      item.Ofertas?.forEach(oferta => allMarkets.add(oferta.Mercado));
    });

    const marketStats: Record<string, { total: number; found: {product: typeof list[0], offer: any}[]; missing: typeof list[0][] }> = {};

    allMarkets.forEach(m => {
      marketStats[m] = { total: 0, found: [], missing: [] };
    });

    list.forEach(item => {
      allMarkets.forEach(marketName => {
        const marketOffers = item.Ofertas?.filter(o => o.Mercado === marketName) || [];
        if (marketOffers.length > 0) {
          // Pega a melhor oferta se houver mais de uma no mesmo mercado
          let bestOffer = marketOffers[0];
          let bestPrice = getBestPrice(bestOffer);
          for (let i = 1; i < marketOffers.length; i++) {
            const price = getBestPrice(marketOffers[i]);
            if (price < bestPrice) {
              bestPrice = price;
              bestOffer = marketOffers[i];
            }
          }
          marketStats[marketName].total += bestPrice * (item.quantity || 1);
          marketStats[marketName].found.push({ product: item, offer: bestOffer });
        } else {
          marketStats[marketName].missing.push(item);
        }
      });
    });

    // Converte os dados calculados numa lista ordenada
    return Object.entries(marketStats)
      .map(([market, stats]) => ({
        market,
        total: stats.total,
        foundItems: stats.found,
        missingItems: stats.missing
      }))
      .sort((a, b) => {
        // 1º Critério: Quem tem mais itens da lista disponíveis (menos itens faltando)
        if (a.missingItems.length !== b.missingItems.length) {
          return a.missingItems.length - b.missingItems.length;
        }
        // 2º Critério: Desempate pelo Menor preço total
        return a.total - b.total;
      });
  }, [list]);

  return (
    <Modal visible={visible} animationType="slide" transparent={true} onRequestClose={onDismiss}>
      <View style={styles.overlay}>
        <View style={styles.container}>
          <View style={styles.header}>
            <Text style={styles.title}>Minha Lista de Compras</Text>
            <IconButton icon="close" size={24} onPress={onDismiss} />
          </View>

          {list.length === 0 ? (
            <View style={styles.emptyContainer}>
              <IconButton icon="cart-outline" size={60} iconColor="#ccc" />
              <Text style={styles.emptyText}>Sua lista está vazia!</Text>
              <Text style={styles.emptySub}>Adicione produtos para descobrir onde é mais barato comprar tudo junto.</Text>
            </View>
          ) : (
            <ScrollView showsVerticalScrollIndicator={false} contentContainerStyle={{ paddingBottom: 20 }}>
              
              <Text style={styles.sectionTitle}>🏆 Onde comprar mais barato?</Text>
              
              {Object.keys(optimizedCart.markets).length > 0 && (
                <View style={[styles.marketCard, styles.optimizedCard]}>
                  <TouchableOpacity onPress={() => toggleExpandedMarket('optimized')} activeOpacity={0.7}>
                    <View style={styles.marketHeader}>
                      <View style={styles.marketNameRow}>
                        <Text style={styles.optimizedName}>⚡ Multi-Mercados (Otimizado)</Text>
                        <IconButton icon={expandedMarkets['optimized'] ? "chevron-up" : "chevron-down"} size={18} style={styles.expandIcon} iconColor="#b8860b" />
                      </View>
                      <Text style={styles.optimizedTotal}>R$ {optimizedCart.total.toFixed(2).replace('.', ',')}</Text>
                    </View>
                    <Text style={styles.marketDetails}>
                      Comprando em {Object.keys(optimizedCart.markets).length} mercado(s) diferentes
                      {optimizedCart.missingCount > 0 && ` (Faltam ${optimizedCart.missingCount})`}
                    </Text>
                  </TouchableOpacity>
                  {expandedMarkets['optimized'] && (
                    <View style={styles.expandedContent}>
                      <Divider style={styles.expandedDivider} />
                      {Object.entries(optimizedCart.markets).map(([mkt, items]) => (
                        <View key={mkt} style={{ marginBottom: 12 }}>
                          <Text style={styles.optimizedMarketTitle}>🛒 {mkt}</Text>
                          {items.map((item, idx) => (
                            <View key={`opt-${mkt}-${idx}`} style={styles.expandedItemRow}>
                              <Text style={styles.expandedItemName} numberOfLines={1}>• {item.product.quantity}x {item.product.Produto_Ouro}</Text>
                              <Text style={styles.expandedItemPrice}>R$ {(getBestPrice(item.offer) * item.product.quantity).toFixed(2).replace('.', ',')}</Text>
                            </View>
                          ))}
                        </View>
                      ))}
                    </View>
                  )}
                </View>
              )}

              {marketRanking.map((rank, index) => {
                const isExpanded = !!expandedMarkets[rank.market];
                
                return (
                  <View key={rank.market} style={[styles.marketCard, index === 0 && styles.bestMarketCard]}>
                    <TouchableOpacity 
                      onPress={() => toggleExpandedMarket(rank.market)}
                      activeOpacity={0.7}
                    >
                      <View style={styles.marketHeader}>
                        <View style={styles.marketNameRow}>
                          <Text style={[styles.marketName, index === 0 && styles.bestMarketName]}>
                            {index === 0 ? '🥇 ' : ''}{rank.market}
                          </Text>
                          <IconButton 
                            icon={isExpanded ? "chevron-up" : "chevron-down"} 
                            size={18} 
                            style={styles.expandIcon} 
                            iconColor="#888"
                          />
                        </View>
                        <Text style={[styles.marketTotal, index === 0 && styles.bestMarketTotal]}>
                          R$ {rank.total.toFixed(2).replace('.', ',')}
                        </Text>
                      </View>
                      <Text style={styles.marketDetails}>
                        {rank.foundItems.length} de {list.length} itens da lista disponíveis
                        {rank.missingItems.length > 0 ? ` (Faltam ${rank.missingItems.length})` : ' ✨ Lista Completa!'}
                      </Text>
                    </TouchableOpacity>

                    {isExpanded && (
                      <View style={styles.expandedContent}>
                        <Divider style={styles.expandedDivider} />
                        
                        {rank.foundItems.length > 0 && (
                          <>
                            <Text style={styles.expandedSectionTitle}>✅ Encontrados:</Text>
                            {rank.foundItems.map((item, idx) => (
                              <View key={`found-${idx}`} style={styles.expandedItemRow}>
                                <Text style={styles.expandedItemName} numberOfLines={1}>• {item.product.quantity}x {item.product.Produto_Ouro}</Text>
                                <Text style={styles.expandedItemPrice}>R$ {(getBestPrice(item.offer) * item.product.quantity).toFixed(2).replace('.', ',')}</Text>
                              </View>
                            ))}
                          </>
                        )}

                        {rank.missingItems.length > 0 && (
                          <>
                            <Text style={[styles.expandedSectionTitle, { color: '#d32f2f', marginTop: 10 }]}>❌ Faltando:</Text>
                            {rank.missingItems.map((prod, idx) => {
                              const alt = getBestAlternative(prod);
                              return (
                                <View key={`missing-${idx}`} style={styles.expandedMissingContainer}>
                                  <View style={styles.expandedItemRow}>
                                    <Text style={[styles.expandedItemName, { color: '#888' }]} numberOfLines={1}>• {prod.Produto_Ouro}</Text>
                                    {!alt && <Text style={[styles.expandedItemPrice, { color: '#888' }]}>Indisponível</Text>}
                                  </View>
                                  {alt && (
                                    <Text style={styles.missingAlternativeText}>💡 Tem no {alt.market} por R$ {alt.price.toFixed(2).replace('.', ',')}</Text>
                                  )}
                                </View>
                              );
                            })}
                          </>
                        )}
                      </View>
                    )}
                  </View>
                );
              })}

              <Divider style={{ marginVertical: 20 }} />

              <View style={styles.listHeaderRow}>
                 <Text style={styles.sectionTitle}>📝 Itens Adicionados ({list.length})</Text>
                 <Button mode="text" textColor="#d32f2f" onPress={clearList} compact>Limpar Tudo</Button>
              </View>

              {list.map(item => {
                const itemKey = `${item.EAN}_${item.Produto_Ouro}`;
                return (
                  <View key={itemKey} style={styles.listItemContainer}>
                    <View style={styles.listItemTopRow}>
                      <Image 
                        source={item.Imagem && item.Imagem.startsWith('http') ? { uri: item.Imagem } : require('../assets/placeholder.png')} 
                        style={styles.listImage} 
                        resizeMode="contain" 
                      />
                      <View style={styles.listInfo}>
                        <Text style={styles.listProductName} numberOfLines={2}>{item.Produto_Ouro}</Text>
                        <Text style={styles.listBrand}>{item.Marca}</Text>
                        <TouchableOpacity onPress={() => toggleExpandItem(itemKey)} style={styles.pinnedMarketRow} activeOpacity={0.6}>
                          <Text style={styles.pinnedMarketText}>
                            📍 {item.pinnedMarket ? `Fixo: ${item.pinnedMarket}` : 'Melhor Preço Automático'}
                          </Text>
                          <IconButton icon="chevron-down" size={14} style={styles.editIcon} iconColor="#0066cc" />
                        </TouchableOpacity>
                      </View>
                      <View style={styles.quantityControls}>
                        <IconButton
                          icon="minus-circle-outline"
                          iconColor="#E5293E"
                          size={24}
                          style={{ margin: 0 }}
                          onPress={() => {
                            if (item.quantity > 1) updateQuantity(item, item.quantity - 1);
                            else toggleProduct(item);
                          }}
                        />
                        <Text style={styles.quantityText}>{item.quantity}</Text>
                        <IconButton
                          icon="plus-circle-outline"
                          iconColor="#E5293E"
                          size={24}
                          style={{ margin: 0 }}
                          onPress={() => updateQuantity(item, item.quantity + 1)}
                        />
                      </View>
                    </View>
                    {expandedItems[itemKey] && (
                      <View style={styles.marketOptionsContainer}>
                        <ScrollView horizontal showsHorizontalScrollIndicator={false}>
                          <Chip 
                            selected={!item.pinnedMarket} 
                            onPress={() => setPinnedMarket(item, undefined)}
                            style={styles.marketChip}
                            textStyle={styles.marketChipText}
                            compact
                          >
                            ✨ Automático
                          </Chip>
                          {item.Ofertas?.map(o => (
                            <Chip 
                              key={o.Mercado}
                              selected={item.pinnedMarket === o.Mercado} 
                              onPress={() => setPinnedMarket(item, o.Mercado)}
                              style={styles.marketChip}
                              textStyle={styles.marketChipText}
                              compact
                            >
                              {o.Mercado} (R$ {getBestPrice(o).toFixed(2).replace('.', ',')})
                            </Chip>
                          ))}
                        </ScrollView>
                      </View>
                    )}
                  </View>
                );
              })}
            </ScrollView>
          )}
        </View>
      </View>
    </Modal>
  );
};

const styles = StyleSheet.create({
  overlay: { flex: 1, backgroundColor: 'rgba(0,0,0,0.5)', justifyContent: 'flex-end' },
  container: { backgroundColor: '#fff', height: '85%', borderTopLeftRadius: 20, borderTopRightRadius: 20, paddingHorizontal: 20 },
  header: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: '#eee', marginBottom: 10 },
  title: { fontSize: 20, fontWeight: 'bold', color: '#333' },
  emptyContainer: { flex: 1, justifyContent: 'center', alignItems: 'center', padding: 20 },
  emptyText: { fontSize: 18, fontWeight: 'bold', color: '#666', marginTop: 10 },
  emptySub: { fontSize: 14, color: '#999', textAlign: 'center', marginTop: 10 },
  sectionTitle: { fontSize: 16, fontWeight: 'bold', color: '#444', marginBottom: 12, marginTop: 10 },
  listHeaderRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  marketCard: { backgroundColor: '#f9f9f9', padding: 15, borderRadius: 12, marginBottom: 10, borderWidth: 1, borderColor: '#eee' },
  bestMarketCard: { backgroundColor: '#fff0f2', borderColor: '#E5293E', borderWidth: 2 },
  optimizedCard: { backgroundColor: '#fffdf5', borderColor: '#ffd700', borderWidth: 2 },
  marketHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 },
  marketNameRow: { flexDirection: 'row', alignItems: 'center', flex: 1 },
  expandIcon: { margin: 0, padding: 0, width: 24, height: 24, marginLeft: 4 },
  marketName: { fontSize: 16, fontWeight: 'bold', color: '#555' },
  bestMarketName: { color: '#E5293E', fontSize: 18 },
  optimizedName: { color: '#b8860b', fontSize: 16, fontWeight: 'bold' },
  marketTotal: { fontSize: 16, fontWeight: 'bold', color: '#333' },
  bestMarketTotal: { color: '#E5293E', fontSize: 18 },
  optimizedTotal: { color: '#b8860b', fontSize: 18, fontWeight: 'bold' },
  marketDetails: { fontSize: 12, color: '#777' },
  expandedContent: { marginTop: 12 },
  expandedDivider: { marginBottom: 12, backgroundColor: '#ddd' },
  expandedSectionTitle: { fontSize: 13, fontWeight: 'bold', color: '#4CAF50', marginBottom: 6 },
  optimizedMarketTitle: { fontSize: 12, fontWeight: 'bold', color: '#555', marginBottom: 6, backgroundColor: '#f0f0f0', paddingHorizontal: 8, paddingVertical: 4, borderRadius: 6, alignSelf: 'flex-start' },
  expandedItemRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 },
  expandedItemName: { fontSize: 13, color: '#444', flex: 1, paddingRight: 10 },
  expandedItemPrice: { fontSize: 13, fontWeight: '600', color: '#333', width: 90, textAlign: 'right' },
  expandedMissingContainer: { marginBottom: 2 },
  missingAlternativeText: { fontSize: 12, color: '#0066cc', marginLeft: 12, marginTop: -4, fontStyle: 'italic' },
  listItemContainer: { paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: '#f0f0f0' },
  listItemTopRow: { flexDirection: 'row', alignItems: 'center' },
  listImage: { width: 50, height: 50, borderRadius: 8, backgroundColor: '#fff' },
  listInfo: { flex: 1, marginLeft: 15 },
  listProductName: { fontSize: 14, fontWeight: '600', color: '#333' },
  listBrand: { fontSize: 12, color: '#888', marginTop: 2 },
  pinnedMarketRow: { flexDirection: 'row', alignItems: 'center', marginTop: 4 },
  pinnedMarketText: { fontSize: 11, color: '#0066cc', fontWeight: '500' },
  editIcon: { margin: 0, width: 20, height: 20, marginLeft: -4 },
  marketOptionsContainer: { marginTop: 12, paddingLeft: 65 },
  marketChip: { marginRight: 8, backgroundColor: '#f5f5f5', borderColor: '#ddd', borderWidth: 1 },
  marketChipText: { fontSize: 11, color: '#444' },
  quantityControls: { flexDirection: 'row', alignItems: 'center' },
  quantityText: { fontSize: 16, fontWeight: 'bold', marginHorizontal: 4, minWidth: 20, textAlign: 'center' },
});