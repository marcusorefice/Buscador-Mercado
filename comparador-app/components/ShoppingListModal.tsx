import React, { useMemo, useState, useCallback, useEffect } from 'react';
import { View, StyleSheet, ScrollView, Modal, Image, TouchableOpacity } from 'react-native';
import { Text, IconButton, Divider, Button, Chip, Checkbox } from 'react-native-paper';
import { useShoppingListStore } from './useShoppingListStore';
import { Product } from '../types';
import { getPrecoEfetivo, getAvisoCondicao, melhorCombinacao, vendidoPorPeso } from '../precos';

// "2x" para unidades, "2 kg" para itens vendidos por peso
const rotuloQuantidade = (quantidade: number, oferta: any) => (vendidoPorPeso(oferta) ? `${quantidade} kg` : `${quantidade}x`);

interface Props {
  visible: boolean;
  onDismiss: () => void;
  allProducts?: Product[];
  onProductPress?: (product: Product) => void;
  apiUrl?: string;
}

export const ShoppingListModal = ({ visible, onDismiss, allProducts = [], onProductPress, apiUrl }: Props) => {
  const { list, toggleProduct, clearList, updateQuantity, setPinnedMarket, toggleItemCheck, refreshOffers } = useShoppingListStore();

  // A lista fica salva no celular; ao abrir, atualiza os preços com os dados mais recentes da API
  useEffect(() => {
    if (!visible || !apiUrl) return;
    const eans = useShoppingListStore.getState().list.map(p => p.EAN);
    if (eans.length === 0) return;
    let cancelado = false;
    fetch(`${apiUrl}/produtos/lote?eans=${encodeURIComponent(eans.join(','))}`, {
      headers: { 'ngrok-skip-browser-warning': 'true' },
    })
      .then(res => (res.ok ? res.json() : Promise.reject(res.status)))
      .then((atualizados: Product[]) => { if (!cancelado) refreshOffers(atualizados); })
      .catch(() => { /* sem conexão: mantém os preços salvos */ });
    return () => { cancelado = true; };
  }, [visible, apiUrl, refreshOffers]);
  const [expandedMarkets, setExpandedMarkets] = useState<Record<string, boolean>>({});
  const [expandedItems, setExpandedItems] = useState<Record<string, boolean>>({});
  const [shoppingMode, setShoppingMode] = useState<{ type: 'cheapest' | 'custom' | 'single' | 'dupla', market?: string, title: string } | null>(null);

  const toggleExpandedMarket = (marketName: string) => {
    setExpandedMarkets(prev => ({ ...prev, [marketName]: !prev[marketName] }));
  };

  const toggleExpandItem = (key: string) => {
    setExpandedItems(prev => ({ ...prev, [key]: !prev[key] }));
  };

  // Preço unitário real considerando a quantidade (atacado só vale a partir da qtd mínima)
  const getBestPrice = (oferta: any, quantidade = 1) => getPrecoEfetivo(oferta, quantidade);

  const getBestAlternative = (product: Product, quantidade = 1) => {
    if (!product.Ofertas || product.Ofertas.length === 0) return null;
    let bestOffer = product.Ofertas[0];
    let bestPrice = getBestPrice(bestOffer, quantidade);
    for (let i = 1; i < product.Ofertas.length; i++) {
      const price = getBestPrice(product.Ofertas[i], quantidade);
      if (price < bestPrice) {
        bestPrice = price;
        bestOffer = product.Ofertas[i];
      }
    }
    return { market: bestOffer.Mercado, price: bestPrice };
  };

  // --- INTELIGÊNCIA: Busca um substituto direto no MESMO mercado ---
  const getSubstitute = useCallback((missingProduct: typeof list[0], market: string): Product | null => {
    if (!allProducts || allProducts.length === 0) return null;
    
    // Pega todos os produtos que não são esse e que têm oferta neste mercado
    const availableInMarket = allProducts.filter(p => 
      p.EAN !== missingProduct.EAN && 
      p.Ofertas?.some(o => o.Mercado === market)
    );

    let bestSub: Product | null = null;
    let maxScore = -1;
    const mainTag = missingProduct.Tags && missingProduct.Tags.length > 0 ? missingProduct.Tags[0] : '';

    availableInMarket.forEach(p => {
      let score = 0;
      if (p.Categoria_Ouro === missingProduct.Categoria_Ouro) score += 10;
      
      const missingTags = missingProduct.Tags || [];
      const pTags = p.Tags || [];
      const overlap = missingTags.filter(t => pTags.includes(t)).length;
      score += overlap * 3;

      // Bônus para mesma marca (ex: trocando fralda tamanho M pra tamanho G da mesma marca)
      if (p.Marca === missingProduct.Marca && p.Marca !== 'OUTROS' && p.Marca !== 'PRÓPRIA') score += 5;
      if (mainTag && pTags.includes(mainTag)) score += 8;

      if (score > maxScore && score >= 15) { // Nota de corte aumentada para evitar sugestões zumbis
        maxScore = score;
        bestSub = p;
      }
    });
    return bestSub;
  }, [allProducts]);

  const handleSwap = (missingProd: typeof list[0], newProd: Product) => {
    const qty = missingProd.quantity || 1;
    toggleProduct(missingProd); // Remove o que não tem
    const exists = list.find(p => p.EAN === newProd.EAN);
    if (!exists) {
      toggleProduct(newProd); // Adiciona a sugestão
      setTimeout(() => updateQuantity(newProd, qty), 50); // Garante a mesma quantidade
    }
  };

  // Carrinho Absoluto Mais Barato (Ignora customizações, sempre o menor preço)
  const cheapestCart = useMemo(() => {
    let total = 0;
    const markets: Record<string, { product: typeof list[0], offer: any }[]> = {};
    let missingCount = 0;

    list.forEach(item => {
      if (!item.Ofertas || item.Ofertas.length === 0) {
        missingCount++;
        return;
      }
      const bestOffer = item.Ofertas.reduce((best, curr) => getBestPrice(curr, item.quantity) < getBestPrice(best, item.quantity) ? curr : best);
      
      total += getBestPrice(bestOffer, item.quantity) * item.quantity;
      if (!markets[bestOffer.Mercado]) markets[bestOffer.Mercado] = [];
      markets[bestOffer.Mercado].push({ product: item, offer: bestOffer });
    });

    return { total, markets, missingCount };
  }, [list]);

  // Carrinho Personalizado (Respeita as escolhas manuais / Pins do usuário)
  const customCart = useMemo(() => {
    let total = 0;
    const markets: Record<string, { product: typeof list[0], offer: any }[]> = {};
    let missingCount = 0;
    let hasCustomPins = false;

    list.forEach(item => {
      if (!item.Ofertas || item.Ofertas.length === 0) {
        missingCount++;
        return;
      }
      
      let chosenOffer = null;
      if (item.pinnedMarket) {
        hasCustomPins = true;
        chosenOffer = item.Ofertas.find(o => o.Mercado === item.pinnedMarket);
      }
      if (!chosenOffer) {
        chosenOffer = item.Ofertas.reduce((best, curr) => getBestPrice(curr, item.quantity) < getBestPrice(best, item.quantity) ? curr : best);
      }

      if (chosenOffer) {
        total += getBestPrice(chosenOffer, item.quantity) * item.quantity;
        if (!markets[chosenOffer.Mercado]) markets[chosenOffer.Mercado] = [];
        markets[chosenOffer.Mercado].push({ product: item, offer: chosenOffer });
      } else {
        missingCount++;
      }
    });

    return { total, markets, missingCount, hasCustomPins };
  }, [list]);

  // Melhor rota usando no máximo 2 mercados (só vale mostrar se o "mais barato" exigir 3 ou mais)
  const duplaCart = useMemo(() => melhorCombinacao(list, 2), [list]);
  const mostrarDupla = !!duplaCart && Object.keys(cheapestCart.markets).length > 2 && duplaCart.mercados.length > 0;

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
          let bestPrice = getBestPrice(bestOffer, item.quantity || 1);
          for (let i = 1; i < marketOffers.length; i++) {
            const price = getBestPrice(marketOffers[i], item.quantity || 1);
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

  // Componente que desenha o item no "Modo Compras"
  const renderShoppingItem = (item: typeof list[0], offer: any) => {
    const itemKey = `${item.EAN}_${item.Produto_Ouro}_${offer.Mercado}`;
    const isChecked = !!item.checked;
    return (
      <View key={itemKey} style={[styles.listItemContainer, isChecked && { opacity: 0.5 }]}>
        <View style={styles.listItemTopRow}>
          <Checkbox
            status={isChecked ? 'checked' : 'unchecked'}
            onPress={() => toggleItemCheck(item)}
            color="#4CAF50"
          />
        <TouchableOpacity 
          style={{ flexDirection: 'row', flex: 1, alignItems: 'center' }}
          onPress={() => onProductPress && onProductPress(item)}
          activeOpacity={0.7}
        >
          <Image 
            source={item.Imagem && item.Imagem.startsWith('http') ? { uri: item.Imagem } : require('../assets/placeholder.png')} 
            style={[styles.listImage, { marginLeft: 4 }]} 
            resizeMode="contain" 
          />
          <View style={styles.listInfo}>
            <Text style={[styles.listProductName, isChecked && { textDecorationLine: 'line-through', color: '#888' }]} numberOfLines={2}>{item.Produto_Ouro}</Text>
            <Text style={styles.listBrand}>{item.Marca}</Text>
            <Text style={{ fontSize: 14, fontWeight: 'bold', color: '#E5293E', marginTop: 4 }}>
              {rotuloQuantidade(item.quantity, offer)} R$ {getBestPrice(offer, item.quantity).toFixed(2).replace('.', ',')}{vendidoPorPeso(offer) ? '/kg' : ''} 
              <Text style={{ fontSize: 12, color: '#666', fontWeight: 'normal' }}> (Total: R$ {(getBestPrice(offer, item.quantity) * item.quantity).toFixed(2).replace('.', ',')})</Text>
            </Text>
            {getAvisoCondicao(offer, item.quantity) && (
              <Text style={{ fontSize: 11, color: '#b26a00', marginTop: 2 }}>{getAvisoCondicao(offer, item.quantity)}</Text>
            )}
          </View>
        </TouchableOpacity>
        </View>
      </View>
    );
  };

  return (
    <Modal visible={visible} animationType="slide" transparent={true} onRequestClose={onDismiss}>
      <View style={styles.overlay}>
        <View style={styles.container}>
          <View style={styles.header}>
            <View style={{ flexDirection: 'row', alignItems: 'center', flex: 1 }}>
              {shoppingMode && (
                <IconButton icon="arrow-left" size={24} onPress={() => setShoppingMode(null)} style={{ margin: 0, marginRight: 4, marginLeft: -8 }} />
              )}
              <Text style={styles.title} numberOfLines={1} ellipsizeMode="tail">
                {shoppingMode ? shoppingMode.title : 'Minha Lista de Compras'}
              </Text>
            </View>
            <IconButton icon="close" size={24} onPress={onDismiss} />
          </View>

          {list.length === 0 ? (
            <View style={styles.emptyContainer}>
              <IconButton icon="cart-outline" size={60} iconColor="#ccc" />
              <Text style={styles.emptyText}>Sua lista está vazia!</Text>
              <Text style={styles.emptySub}>Adicione produtos para descobrir onde é mais barato comprar tudo junto.</Text>
            </View>
          ) : shoppingMode ? (
            <ScrollView showsVerticalScrollIndicator={false} contentContainerStyle={{ paddingBottom: 20 }}>
              {(shoppingMode.type === 'cheapest' || shoppingMode.type === 'custom' || shoppingMode.type === 'dupla') && (
                Object.entries(
                  shoppingMode.type === 'cheapest' ? cheapestCart.markets
                    : shoppingMode.type === 'dupla' ? (duplaCart?.porMercado || {})
                    : customCart.markets
                ).map(([mkt, items]) => (
                  <View key={mkt} style={{ marginBottom: 20 }}>
                    <View style={{ backgroundColor: '#f0f0f0', padding: 8, borderRadius: 8, marginBottom: 8 }}>
                      <Text style={{ fontSize: 16, fontWeight: 'bold', color: '#555' }}>🛒 {mkt}</Text>
                    </View>
                    {items.map(i => renderShoppingItem(i.product, i.offer))}
                  </View>
                ))
              )}
              {shoppingMode.type === 'single' && shoppingMode.market && (
                <View>
                  {marketRanking.find(r => r.market === shoppingMode.market)?.foundItems.map(i => renderShoppingItem(i.product, i.offer))}
                  {marketRanking.find(r => r.market === shoppingMode.market)?.missingItems && marketRanking.find(r => r.market === shoppingMode.market)!.missingItems.length > 0 && (
                     <View style={{ marginTop: 20 }}>
                       <Text style={[styles.sectionTitle, { color: '#d32f2f' }]}>❌ Itens Indisponíveis</Text>
                       {marketRanking.find(r => r.market === shoppingMode.market)?.missingItems.map((prod, idx) => {
                          const substitute = getSubstitute(prod, shoppingMode.market!);
                          return (
                          <View key={`missing-${idx}`} style={[styles.listItemContainer, { opacity: substitute ? 1 : 0.5 }]}>
                            <View style={styles.listItemTopRow}>
                          <TouchableOpacity 
                            style={{ flexDirection: 'row', flex: 1, alignItems: 'center', marginLeft: 36 }}
                            onPress={() => onProductPress && onProductPress(prod)}
                            activeOpacity={0.7}
                          >
                            <Image source={prod.Imagem && prod.Imagem.startsWith('http') ? { uri: prod.Imagem } : require('../assets/placeholder.png')} style={styles.listImage} resizeMode="contain" />
                            <View style={styles.listInfo}>
                              <Text style={styles.listProductName} numberOfLines={2}>{prod.Produto_Ouro}</Text>
                              <Text style={{ color: '#d32f2f', fontSize: 12, marginTop: 4 }}>Não encontrado neste mercado</Text>
                            </View>
                          </TouchableOpacity>
                            </View>
                            
                            {substitute && (
                              <View style={styles.substituteContainer}>
                                <Text style={styles.substituteTitle}>🔄 Sugestão de Troca neste mercado:</Text>
                                <TouchableOpacity style={styles.substituteCard} onPress={() => onProductPress && substitute && onProductPress(substitute)}>
                                  <Image source={substitute?.Imagem && substitute?.Imagem.startsWith('http') ? { uri: substitute?.Imagem } : require('../assets/placeholder.png')} style={styles.substituteImage} resizeMode="contain" />
                                  <View style={{ flex: 1, marginLeft: 8 }}>
                                    <Text style={styles.substituteName} numberOfLines={1}>{substitute?.Produto_Ouro}</Text>
                                    <Text style={styles.substitutePrice}>R$ {getBestPrice(substitute?.Ofertas?.find(o => o.Mercado === shoppingMode?.market), prod.quantity).toFixed(2).replace('.', ',')}</Text>
                                  </View>
                                  <Button mode="contained-tonal" buttonColor="#e3f2fd" textColor="#0066cc" compact onPress={() => substitute && handleSwap(prod, substitute)}>
                                    Trocar
                                  </Button>
                                </TouchableOpacity>
                              </View>
                            )}
                          </View>
                       )})}
                     </View>
                  )}
                </View>
              )}
            </ScrollView>
          ) : (
            <ScrollView showsVerticalScrollIndicator={false} contentContainerStyle={{ paddingBottom: 20 }}>
              
              <Text style={styles.sectionTitle}>🏆 Onde comprar mais barato?</Text>
              
              {Object.keys(cheapestCart.markets).length > 0 && (
                <View style={[styles.marketCard, styles.optimizedCard]}>
                  <TouchableOpacity onPress={() => toggleExpandedMarket('cheapest')} activeOpacity={0.7}>
                    <View style={styles.marketHeader}>
                      <View style={styles.marketNameRow}>
                        <Text style={styles.optimizedName}>⚡ Mais Barato (Vários Mercados)</Text>
                        <IconButton icon={expandedMarkets['cheapest'] ? "chevron-up" : "chevron-down"} size={18} style={styles.expandIcon} iconColor="#b8860b" />
                      </View>
                      <Text style={styles.optimizedTotal}>R$ {cheapestCart.total.toFixed(2).replace('.', ',')}</Text>
                    </View>
                    <Text style={styles.marketDetails}>
                      Comprando em {Object.keys(cheapestCart.markets).length} mercado(s) diferentes
                      {cheapestCart.missingCount > 0 && ` (Faltam ${cheapestCart.missingCount})`}
                    </Text>
                  </TouchableOpacity>
                  {expandedMarkets['cheapest'] && (
                    <View style={styles.expandedContent}>
                      <Divider style={styles.expandedDivider} />
                      <Button 
                        mode="contained" 
                        buttonColor="#b8860b" 
                        icon="cart-outline" 
                        style={{ marginBottom: 16 }} 
                        onPress={() => setShoppingMode({ type: 'cheapest', title: 'Mais Barato Geral' })}
                      >
                        Iniciar Compras
                      </Button>
                      {Object.entries(cheapestCart.markets).map(([mkt, items]) => (
                        <View key={mkt} style={{ marginBottom: 12 }}>
                          <Text style={styles.optimizedMarketTitle}>🛒 {mkt}</Text>
                          {items.map((item, idx) => (
                              <TouchableOpacity key={`cheap-${mkt}-${idx}`} onPress={() => onProductPress && onProductPress(item.product)} activeOpacity={0.7}>
                                <View style={styles.expandedItemRow}>
                                  <Text style={styles.expandedItemName} numberOfLines={1}>• {rotuloQuantidade(item.product.quantity, item.offer)} {item.product.Produto_Ouro}</Text>
                                  <Text style={styles.expandedItemPrice}>R$ {(getBestPrice(item.offer, item.product.quantity) * item.product.quantity).toFixed(2).replace('.', ',')}</Text>
                                </View>
                              </TouchableOpacity>
                          ))}
                        </View>
                      ))}
                    </View>
                  )}
                </View>
              )}

              {mostrarDupla && duplaCart && (
                <View style={[styles.marketCard, styles.duplaCard]}>
                  <TouchableOpacity onPress={() => toggleExpandedMarket('dupla')} activeOpacity={0.7}>
                    <View style={styles.marketHeader}>
                      <View style={styles.marketNameRow}>
                        <Text style={styles.duplaName}>🚗 Melhor em até 2 mercados</Text>
                        <IconButton icon={expandedMarkets['dupla'] ? "chevron-up" : "chevron-down"} size={18} style={styles.expandIcon} iconColor="#2e7d32" />
                      </View>
                      <Text style={styles.duplaTotal}>R$ {duplaCart.total.toFixed(2).replace('.', ',')}</Text>
                    </View>
                    <Text style={styles.marketDetails}>
                      {duplaCart.mercados.join(' + ')}
                      {duplaCart.total > cheapestCart.total + 0.005
                        ? ` · só R$ ${(duplaCart.total - cheapestCart.total).toFixed(2).replace('.', ',')} a mais que ir em ${Object.keys(cheapestCart.markets).length} mercados`
                        : ''}
                      {duplaCart.faltando > 0 && ` (Faltam ${duplaCart.faltando})`}
                    </Text>
                  </TouchableOpacity>
                  {expandedMarkets['dupla'] && (
                    <View style={styles.expandedContent}>
                      <Divider style={styles.expandedDivider} />
                      <Button
                        mode="contained"
                        buttonColor="#2e7d32"
                        icon="cart-outline"
                        style={{ marginBottom: 16 }}
                        onPress={() => setShoppingMode({ type: 'dupla', title: 'Até 2 Mercados' })}
                      >
                        Iniciar Compras
                      </Button>
                      {Object.entries(duplaCart.porMercado).map(([mkt, items]) => (
                        <View key={mkt} style={{ marginBottom: 12 }}>
                          <Text style={[styles.optimizedMarketTitle, { color: '#2e7d32', backgroundColor: '#e8f5e9' }]}>🛒 {mkt}</Text>
                          {items.map((item, idx) => (
                              <TouchableOpacity key={`dupla-${mkt}-${idx}`} onPress={() => onProductPress && onProductPress(item.product)} activeOpacity={0.7}>
                                <View style={styles.expandedItemRow}>
                                  <Text style={styles.expandedItemName} numberOfLines={1}>• {rotuloQuantidade(item.product.quantity, item.offer)} {item.product.Produto_Ouro}</Text>
                                  <Text style={styles.expandedItemPrice}>R$ {(getBestPrice(item.offer, item.product.quantity) * item.product.quantity).toFixed(2).replace('.', ',')}</Text>
                                </View>
                              </TouchableOpacity>
                          ))}
                        </View>
                      ))}
                    </View>
                  )}
                </View>
              )}

              {customCart.hasCustomPins && Object.keys(customCart.markets).length > 0 && (
                <View style={[styles.marketCard, styles.customCard]}>
                  <TouchableOpacity onPress={() => toggleExpandedMarket('custom')} activeOpacity={0.7}>
                    <View style={styles.marketHeader}>
                      <View style={styles.marketNameRow}>
                        <Text style={styles.customName}>🛠️ Rota Personalizada</Text>
                        <IconButton icon={expandedMarkets['custom'] ? "chevron-up" : "chevron-down"} size={18} style={styles.expandIcon} iconColor="#0066cc" />
                      </View>
                      <Text style={styles.customTotal}>R$ {customCart.total.toFixed(2).replace('.', ',')}</Text>
                    </View>
                    <Text style={styles.marketDetails}>
                      Sua seleção manual de mercados
                      {customCart.missingCount > 0 && ` (Faltam ${customCart.missingCount})`}
                    </Text>
                  </TouchableOpacity>
                  {expandedMarkets['custom'] && (
                    <View style={styles.expandedContent}>
                      <Divider style={styles.expandedDivider} />
                      <Button 
                        mode="contained" 
                        buttonColor="#0066cc" 
                        icon="cart-outline" 
                        style={{ marginBottom: 16 }} 
                        onPress={() => setShoppingMode({ type: 'custom', title: 'Rota Personalizada' })}
                      >
                        Iniciar Compras
                      </Button>
                      {Object.entries(customCart.markets).map(([mkt, items]) => (
                        <View key={mkt} style={{ marginBottom: 12 }}>
                          <Text style={[styles.optimizedMarketTitle, { color: '#0066cc', backgroundColor: '#e3f2fd' }]}>🛒 {mkt}</Text>
                          {items.map((item, idx) => (
                              <TouchableOpacity key={`cust-${mkt}-${idx}`} onPress={() => onProductPress && onProductPress(item.product)} activeOpacity={0.7}>
                                <View style={styles.expandedItemRow}>
                                  <Text style={styles.expandedItemName} numberOfLines={1}>• {rotuloQuantidade(item.product.quantity, item.offer)} {item.product.Produto_Ouro}</Text>
                                  <Text style={styles.expandedItemPrice}>R$ {(getBestPrice(item.offer, item.product.quantity) * item.product.quantity).toFixed(2).replace('.', ',')}</Text>
                                </View>
                              </TouchableOpacity>
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
                        
                        <Button 
                          mode="contained" 
                          buttonColor="#E5293E" 
                          icon="cart-outline" 
                          style={{ marginBottom: 16 }} 
                          onPress={() => setShoppingMode({ type: 'single', market: rank.market, title: rank.market })}
                        >
                          Ir para este Mercado
                        </Button>
                        
                        {rank.foundItems.length > 0 && (
                          <>
                            <Text style={styles.expandedSectionTitle}>✅ Encontrados:</Text>
                            {rank.foundItems.map((item, idx) => (
                              <TouchableOpacity key={`found-${idx}`} onPress={() => onProductPress && onProductPress(item.product)} activeOpacity={0.7}>
                                <View style={styles.expandedItemRow}>
                                  <Text style={styles.expandedItemName} numberOfLines={1}>• {rotuloQuantidade(item.product.quantity, item.offer)} {item.product.Produto_Ouro}</Text>
                                  <Text style={styles.expandedItemPrice}>R$ {(getBestPrice(item.offer, item.product.quantity) * item.product.quantity).toFixed(2).replace('.', ',')}</Text>
                                </View>
                              </TouchableOpacity>
                            ))}
                          </>
                        )}

                        {rank.missingItems.length > 0 && (
                          <>
                            <Text style={[styles.expandedSectionTitle, { color: '#d32f2f', marginTop: 10 }]}>❌ Faltando:</Text>
                            {rank.missingItems.map((prod, idx) => {
                              const alt = getBestAlternative(prod, prod.quantity);
                              const substitute = getSubstitute(prod, rank.market);
                              return (
                                <View key={`missing-${idx}`} style={styles.expandedMissingContainer}>
                              <TouchableOpacity onPress={() => onProductPress && onProductPress(prod)} activeOpacity={0.7}>
                                <View style={styles.expandedItemRow}>
                                  <Text style={[styles.expandedItemName, { color: '#888' }]} numberOfLines={1}>• {prod.Produto_Ouro}</Text>
                                  {!alt && <Text style={[styles.expandedItemPrice, { color: '#888' }]}>Indisponível</Text>}
                                </View>
                              </TouchableOpacity>
                                  {alt && (
                                    <Text style={styles.missingAlternativeText}>💡 Tem no {alt.market} por R$ {alt.price.toFixed(2).replace('.', ',')}</Text>
                                  )}
                                  {substitute && (
                                    <View style={styles.substituteContainer}>
                                      <Text style={styles.substituteTitle}>🔄 Sugestão de Troca:</Text>
                                      <TouchableOpacity style={styles.substituteCard} onPress={() => onProductPress && substitute && onProductPress(substitute)}>
                                        <Image source={substitute?.Imagem && substitute?.Imagem.startsWith('http') ? { uri: substitute?.Imagem } : require('../assets/placeholder.png')} style={styles.substituteImage} resizeMode="contain" />
                                        <View style={{ flex: 1, marginLeft: 8 }}>
                                          <Text style={styles.substituteName} numberOfLines={1}>{substitute?.Produto_Ouro}</Text>
                                          <Text style={styles.substitutePrice}>R$ {getBestPrice(substitute?.Ofertas?.find(o => o.Mercado === rank.market), prod.quantity).toFixed(2).replace('.', ',')}</Text>
                                        </View>
                                        <Button mode="contained-tonal" buttonColor="#e3f2fd" textColor="#0066cc" compact onPress={() => substitute && handleSwap(prod, substitute)}>
                                          Trocar
                                        </Button>
                                      </TouchableOpacity>
                                    </View>
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
                const isChecked = !!item.checked;
                return (
                  <View key={itemKey} style={[styles.listItemContainer, isChecked && { opacity: 0.5 }]}>
                    <View style={styles.listItemTopRow}>
                      <Checkbox
                        status={isChecked ? 'checked' : 'unchecked'}
                        onPress={() => toggleItemCheck(item)}
                        color="#4CAF50"
                      />
                  <TouchableOpacity onPress={() => onProductPress && onProductPress(item)} activeOpacity={0.7}>
                    <Image 
                      source={item.Imagem && item.Imagem.startsWith('http') ? { uri: item.Imagem } : require('../assets/placeholder.png')} 
                      style={[styles.listImage, { marginLeft: 4 }]} 
                      resizeMode="contain" 
                    />
                  </TouchableOpacity>
                      <View style={styles.listInfo}>
                    <TouchableOpacity onPress={() => onProductPress && onProductPress(item)} activeOpacity={0.7}>
                      <Text style={[styles.listProductName, isChecked && { textDecorationLine: 'line-through', color: '#888' }]} numberOfLines={2}>{item.Produto_Ouro}</Text>
                      <Text style={styles.listBrand}>{item.Marca}</Text>
                    </TouchableOpacity>
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
                              {o.Mercado} (R$ {getBestPrice(o, item.quantity).toFixed(2).replace('.', ',')})
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
  container: { backgroundColor: '#fff', flex: 1, marginTop: 40, borderTopLeftRadius: 20, borderTopRightRadius: 20, paddingHorizontal: 20 },
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
  customCard: { backgroundColor: '#f0f8ff', borderColor: '#0066cc', borderWidth: 2 },
  duplaCard: { backgroundColor: '#f1f8e9', borderColor: '#2e7d32', borderWidth: 2 },
  marketHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 },
  marketNameRow: { flexDirection: 'row', alignItems: 'center', flex: 1 },
  expandIcon: { margin: 0, padding: 0, width: 24, height: 24, marginLeft: 4 },
  marketName: { fontSize: 16, fontWeight: 'bold', color: '#555' },
  bestMarketName: { color: '#E5293E', fontSize: 18 },
  optimizedName: { color: '#b8860b', fontSize: 16, fontWeight: 'bold' },
  customName: { color: '#0066cc', fontSize: 16, fontWeight: 'bold' },
  duplaName: { color: '#2e7d32', fontSize: 16, fontWeight: 'bold' },
  marketTotal: { fontSize: 16, fontWeight: 'bold', color: '#333' },
  bestMarketTotal: { color: '#E5293E', fontSize: 18 },
  optimizedTotal: { color: '#b8860b', fontSize: 18, fontWeight: 'bold' },
  customTotal: { color: '#0066cc', fontSize: 18, fontWeight: 'bold' },
  duplaTotal: { color: '#2e7d32', fontSize: 18, fontWeight: 'bold' },
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
  substituteContainer: { marginTop: 8, marginBottom: 4, paddingLeft: 12, borderLeftWidth: 3, borderLeftColor: '#0066cc', marginLeft: 36 },
  substituteTitle: { fontSize: 11, color: '#0066cc', fontWeight: 'bold', marginBottom: 6 },
  substituteCard: { flexDirection: 'row', alignItems: 'center', backgroundColor: '#f0f8ff', padding: 8, borderRadius: 8, borderWidth: 1, borderColor: '#e3f2fd' },
  substituteImage: { width: 36, height: 36, borderRadius: 4, backgroundColor: '#fff' },
  substituteName: { fontSize: 12, color: '#333', fontWeight: '600' },
  substitutePrice: { fontSize: 13, color: '#E5293E', fontWeight: 'bold' },
});