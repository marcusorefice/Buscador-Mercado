import React from 'react';
import { View, StyleSheet, Modal, Image, ScrollView, TouchableOpacity } from 'react-native';
import { Text, Title, IconButton } from 'react-native-paper';
import { Product } from '../types';
import { getMarketLogo } from './ProductCard';
import { SafeAreaView } from 'react-native-safe-area-context';

interface ProductDetailsModalProps {
  visible: boolean;
  onDismiss: () => void;
  product: Product | null;
  allProducts?: Product[];
  onSelectComparison?: (p: Product) => void;
}

const capitalize = (str: string | null): string => {
  if (!str) return '';
  return str.toLowerCase().replace(/(?:^|\s)\S/g, (a) => a.toUpperCase());
};

const normalize = (str?: string | null): string => {
  if (!str) return '';
  return str
    .trim()
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '');
};

const parsePrice = (priceStr: string): number => {
  const cleanStr = priceStr.replace(/\./g, '').replace(',', '.');
  const val = parseFloat(cleanStr);
  return isNaN(val) ? 0 : val;
};

export const ProductDetailsModal: React.FC<ProductDetailsModalProps> = ({ visible, onDismiss, product, allProducts = [], onSelectComparison }) => {
  if (!product) return null;

  const titleText = `${capitalize(product.Produto)}${product.Marca ? ` ${capitalize(product.Marca)}` : ''}`;
  const varejoStr = product.Preco_Varejo ? product.Preco_Varejo.replace(/[R$\s]/gi, '') : '';
  const atacadoStr = product.Preco_Atacado ? product.Preco_Atacado.replace(/[R$\s]/gi, '') : '';
  const varejoVal = parsePrice(varejoStr);
  const atacadoVal = parsePrice(atacadoStr);

  let currentPriceStr = varejoStr || atacadoStr || '0,00';
  let previousPriceStr = '';
  let discountPercent = 0;

  if (varejoVal > 0 && atacadoVal > 0 && atacadoVal < varejoVal) {
    currentPriceStr = atacadoStr;
    previousPriceStr = varejoStr;
    discountPercent = Math.round((1 - atacadoVal / varejoVal) * 100);
  }

  const condition = product.Condicao?.trim().toUpperCase();
  const hasCondition = condition && !['1 UN', 'NAN', 'NONE', ''].includes(condition);

  // Filter similar products from other markets
  const getComparisons = () => {
    if (!product || !allProducts) return [];
    
    const prodName = normalize(product.Produto);
    const prodBrand = normalize(product.Marca);
    
    // Extrai palavras-chave principais do produto, ignorando palavras curtas e conectivos
    const ignoreWords = ['de', 'com', 'em', 'sem', 'ao', 'para', 'e'];
    const keywords = prodName.split(' ').filter(w => w.length > 2 && !ignoreWords.includes(w));
    const coreKeywords = keywords.slice(0, 3); // Usa as 3 primeiras palavras mais fortes
    
    const matches = allProducts
      .filter((p) => {
        if (p.id === product.id || p.Mercado === product.Mercado) return false;
        
        const pName = normalize(p.Produto);
        const pBrand = normalize(p.Marca);
        
        // 1. Marca: Se ambos tem marca, precisam ser iguais. Se um não tiver explícito, relaxa a busca
        const isGeneric = (b: string) => !b || b === 'n/a' || b === 'propria' || b === 'própria';
        const brandA = isGeneric(prodBrand) ? null : prodBrand;
        const brandB = isGeneric(pBrand) ? null : pBrand;
        
        if (brandA && brandB && brandA !== brandB) return false;

        // 2. Nome exato
        if (pName === prodName) return true;

        // 3. Nome parecido (Fuzzy Match pelas palavras-chave)
        if (coreKeywords.length > 0) {
           const matchCount = coreKeywords.filter(kw => pName.includes(kw)).length;
           // Se o produto rival contiver todas as 2 ou 3 palavras-chave principais
           if (matchCount === coreKeywords.length) return true;
        }

        return false;
      })
      .sort((a, b) => {
         const pA = parsePrice(a.Preco_Atacado || a.Preco_Varejo || '0');
         const pB = parsePrice(b.Preco_Atacado || b.Preco_Varejo || '0');
         return pA - pB;
      });
      
      // Filtra para pegar apenas o mais barato de cada mercado rival
      const uniqueMarkets: Record<string, boolean> = {};
      return matches.filter((p) => {
        if (!p.Mercado || uniqueMarkets[p.Mercado]) return false;
        uniqueMarkets[p.Mercado] = true;
        return true;
      }).slice(0, 4); // Limita a 4 resultados para não poluir a tela
  };

  const comparisons = getComparisons();

  return (
    <Modal visible={visible} animationType="slide" transparent={false} onRequestClose={onDismiss}>
      <SafeAreaView style={styles.container}>
        <View style={styles.header}>
          <IconButton icon="close" size={24} onPress={onDismiss} iconColor="#333" />
          <Text style={styles.headerTitle}>Detalhes do Produto</Text>
          <View style={{ width: 48 }} />
        </View>

        <ScrollView contentContainerStyle={styles.scrollContent} showsVerticalScrollIndicator={false}>
          <View style={styles.imageContainer}>
            {product.Link_Imagem ? (
              <Image source={{ uri: product.Link_Imagem }} style={styles.image} resizeMode="contain" />
            ) : (
              <View style={styles.placeholderImage}><Text style={styles.placeholderText}>Sem Imagem</Text></View>
            )}
            {discountPercent > 0 && (
              <View style={styles.discountBadge}>
                <Text style={styles.discountText}>-{discountPercent}%</Text>
              </View>
            )}
          </View>

          <View style={styles.infoContainer}>
            <View style={styles.marketRow}>
              <Image source={getMarketLogo(product.Mercado || 'Default')} style={styles.marketLogo} resizeMode="contain" />
              <Text style={styles.marketName}>{product.Mercado || 'Mercado'}</Text>
            </View>

            <Title style={styles.title}>{titleText}</Title>
            <Text style={styles.category}>{capitalize(product.Categoria)} {product.subcategoria && product.subcategoria !== 'N/A' ? `• ${capitalize(product.subcategoria)}` : ''}</Text>

            <View style={styles.priceSection}>
              {previousPriceStr ? (
                <Text style={styles.previousPrice}>De: R$ {previousPriceStr}</Text>
              ) : null}
              <Text style={styles.currentPrice}>
                <Text style={styles.currencySymbol}>R$ </Text>{currentPriceStr}
                {!hasCondition ? <Text style={styles.unitText}> / un</Text> : null}
              </Text>
            </View>

            {hasCondition && (
              <View style={styles.conditionBox}>
                <Text style={styles.conditionTitle}>✨ Oferta Especial</Text>
                <Text style={styles.conditionText}>
                  Preço de <Text style={{fontWeight: 'bold'}}>R$ {atacadoStr}</Text> exclusivo para <Text style={{fontWeight: 'bold'}}>{condition}</Text>.
                  {previousPriceStr ? ` Preço normal: R$ ${varejoStr}.` : ''}
                </Text>
              </View>
            )}

            <View style={styles.detailsBox}>
              <Text style={styles.detailsLabel}>Marca: <Text style={styles.detailsValue}>{product.Marca || 'N/A'}</Text></Text>
              {product.Qtd_Valor ? (
                <Text style={styles.detailsLabel}>Quantidade: <Text style={styles.detailsValue}>{product.Qtd_Valor} {product.Medida}</Text></Text>
              ) : null}
              {product.Validade && product.Validade !== 'VER NO SITE' ? (
                <Text style={styles.detailsLabel}>Validade: <Text style={styles.detailsValue}>{product.Validade}</Text></Text>
              ) : null}
              <Text style={styles.detailsLabel}>Atualizado em: <Text style={styles.detailsValue}>{product.Data_Hora || 'N/A'}</Text></Text>
            </View>
            
            <View style={styles.comparisonBox}>
              <Text style={styles.comparisonTitle}>🛒 Onde mais tem?</Text>
              {comparisons.length > 0 ? (
                comparisons.map((comp) => {
                  const compPrice = comp.Preco_Atacado || comp.Preco_Varejo || '0,00';
                  return (
                    <TouchableOpacity 
                      key={comp.id} 
                      style={styles.comparisonRow}
                      onPress={() => onSelectComparison?.(comp)}
                      activeOpacity={0.7}
                    >
                      <View style={styles.comparisonMarket}>
                        <Image source={getMarketLogo(comp.Mercado || 'Default')} style={styles.compLogo} resizeMode="contain" />
                        <Text style={styles.compMarketName} numberOfLines={1}>{comp.Mercado}</Text>
                      </View>
                      <View style={{ flexDirection: 'row', alignItems: 'center' }}>
                        <Text style={styles.compPrice}>R$ {compPrice}</Text>
                        <IconButton icon="chevron-right" size={20} iconColor="#E5293E" style={{ margin: 0, padding: 0 }} />
                      </View>
                    </TouchableOpacity>
                  );
                })
              ) : (
                <Text style={{ fontSize: 14, color: '#888', fontStyle: 'italic' }}>
                  Não encontramos esse exato produto em outros mercados hoje.
                </Text>
              )}
            </View>

          </View>
        </ScrollView>
      </SafeAreaView>
    </Modal>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#fff',
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    borderBottomWidth: 1,
    borderBottomColor: '#eee',
    paddingHorizontal: 8,
  },
  headerTitle: {
    fontSize: 18,
    fontWeight: 'bold',
    color: '#333',
  },
  scrollContent: {
    paddingBottom: 40,
  },
  imageContainer: {
    width: '100%',
    aspectRatio: 1.2,
    backgroundColor: '#fff',
    position: 'relative',
    padding: 20,
    borderBottomWidth: 1,
    borderBottomColor: '#f0f0f0',
  },
  image: {
    width: '100%',
    height: '100%',
  },
  placeholderImage: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  placeholderText: {
    fontSize: 14,
    color: '#ccc',
  },
  discountBadge: {
    position: 'absolute',
    top: 16,
    left: 16,
    backgroundColor: '#17c671',
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 8,
    elevation: 2,
  },
  discountText: {
    color: '#fff',
    fontSize: 16,
    fontWeight: 'bold',
  },
  infoContainer: {
    padding: 20,
  },
  marketRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 16,
    backgroundColor: '#f9f9f9',
    padding: 8,
    borderRadius: 12,
    alignSelf: 'flex-start',
  },
  marketLogo: {
    width: 24,
    height: 24,
    borderRadius: 6,
    marginRight: 8,
  },
  marketName: {
    fontSize: 14,
    color: '#555',
    fontWeight: '700',
  },
  title: {
    fontSize: 24,
    lineHeight: 30,
    fontWeight: 'bold',
    color: '#222',
    marginBottom: 4,
  },
  category: {
    fontSize: 14,
    color: '#888',
    marginBottom: 20,
  },
  priceSection: {
    marginBottom: 24,
  },
  previousPrice: {
    fontSize: 16,
    color: '#999',
    textDecorationLine: 'line-through',
    marginBottom: 4,
  },
  currentPrice: {
    fontSize: 36,
    fontWeight: '900',
    color: '#E5293E',
  },
  currencySymbol: {
    fontSize: 20,
    fontWeight: 'bold',
  },
  unitText: {
    fontSize: 16,
    fontWeight: 'normal',
    color: '#666',
  },
  conditionBox: {
    backgroundColor: '#fff4f4',
    borderWidth: 1,
    borderColor: '#ffd1d1',
    borderRadius: 12,
    padding: 16,
    marginBottom: 24,
  },
  conditionTitle: {
    fontSize: 16,
    fontWeight: 'bold',
    color: '#E5293E',
    marginBottom: 8,
  },
  conditionText: {
    fontSize: 15,
    color: '#444',
    lineHeight: 22,
  },
  detailsBox: {
    backgroundColor: '#f9f9f9',
    borderRadius: 12,
    padding: 16,
    borderWidth: 1,
    borderColor: '#eee',
  },
  detailsLabel: {
    fontSize: 14,
    color: '#666',
    marginBottom: 8,
  },
  detailsValue: {
    fontWeight: 'bold',
    color: '#333',
  },
  comparisonBox: {
    marginTop: 24,
    backgroundColor: '#fff',
    borderRadius: 12,
    padding: 16,
    borderWidth: 1,
    borderColor: '#e0e0e0',
  },
  comparisonTitle: {
    fontSize: 16,
    fontWeight: 'bold',
    color: '#333',
    marginBottom: 12,
  },
  comparisonRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: 8,
    borderBottomWidth: 1,
    borderBottomColor: '#f5f5f5',
  },
  comparisonMarket: {
    flexDirection: 'row',
    alignItems: 'center',
    flex: 1,
  },
  compLogo: {
    width: 24,
    height: 24,
    borderRadius: 4,
    marginRight: 8,
  },
  compMarketName: {
    fontSize: 14,
    color: '#555',
    flex: 1,
  },
  compPrice: {
    fontSize: 16,
    fontWeight: 'bold',
    color: '#E5293E',
  },
});
