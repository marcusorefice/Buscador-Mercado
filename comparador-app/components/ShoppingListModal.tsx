import React, { useMemo, useState } from 'react';
import { View, StyleSheet, ScrollView, Modal, Image, TouchableOpacity } from 'react-native';
import { Text, IconButton, Divider, Button } from 'react-native-paper';
import { useShoppingListStore } from './useShoppingListStore';
import { Product } from '../types';

interface Props {
  visible: boolean;
  onDismiss: () => void;
}

export const ShoppingListModal = ({ visible, onDismiss }: Props) => {
  const { list, toggleProduct, clearList, updateQuantity } = useShoppingListStore();
  const [expandedMarkets, setExpandedMarkets] = useState<Record<string, boolean>>({});

  const toggleExpandedMarket = (marketName: string) => {
    setExpandedMarkets(prev => ({ ...prev, [marketName]: !prev[marketName] }));
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

              {list.map(item => (
                <View key={`${item.EAN}_${item.Produto_Ouro}`} style={styles.listItem}>
                  <Image 
                    source={item.Imagem && item.Imagem.startsWith('http') ? { uri: item.Imagem } : require('../assets/placeholder.png')} 
                    style={styles.listImage} 
                    resizeMode="contain" 
                  />
                  <View style={styles.listInfo}>
                    <Text style={styles.listProductName} numberOfLines={2}>{item.Produto_Ouro}</Text>
                    <Text style={styles.listBrand}>{item.Marca}</Text>
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
              ))}
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
  marketHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 },
  marketNameRow: { flexDirection: 'row', alignItems: 'center', flex: 1 },
  expandIcon: { margin: 0, padding: 0, width: 24, height: 24, marginLeft: 4 },
  marketName: { fontSize: 16, fontWeight: 'bold', color: '#555' },
  bestMarketName: { color: '#E5293E', fontSize: 18 },
  marketTotal: { fontSize: 16, fontWeight: 'bold', color: '#333' },
  bestMarketTotal: { color: '#E5293E', fontSize: 18 },
  marketDetails: { fontSize: 12, color: '#777' },
  expandedContent: { marginTop: 12 },
  expandedDivider: { marginBottom: 12, backgroundColor: '#ddd' },
  expandedSectionTitle: { fontSize: 13, fontWeight: 'bold', color: '#4CAF50', marginBottom: 6 },
  expandedItemRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 },
  expandedItemName: { fontSize: 13, color: '#444', flex: 1, paddingRight: 10 },
  expandedItemPrice: { fontSize: 13, fontWeight: '600', color: '#333', width: 90, textAlign: 'right' },
  expandedMissingContainer: { marginBottom: 2 },
  missingAlternativeText: { fontSize: 12, color: '#0066cc', marginLeft: 12, marginTop: -4, fontStyle: 'italic' },
  listItem: { flexDirection: 'row', alignItems: 'center', paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: '#f0f0f0' },
  listImage: { width: 50, height: 50, borderRadius: 8, backgroundColor: '#fff' },
  listInfo: { flex: 1, marginLeft: 15 },
  listProductName: { fontSize: 14, fontWeight: '600', color: '#333' },
  listBrand: { fontSize: 12, color: '#888', marginTop: 2 },
  quantityControls: { flexDirection: 'row', alignItems: 'center' },
  quantityText: { fontSize: 16, fontWeight: 'bold', marginHorizontal: 4, minWidth: 20, textAlign: 'center' },
});