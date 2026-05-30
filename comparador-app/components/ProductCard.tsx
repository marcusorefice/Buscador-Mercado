import React from 'react';
import { View, StyleSheet, Image } from 'react-native';
import { Card, Text, Title, IconButton } from 'react-native-paper';
import { Product } from '../types';
import { useShoppingListStore } from './useShoppingListStore';

type MarketName = 
  | 'Assaí Atacadista'
  | 'Atacadão'
  | 'Boa Supermercados'
  | 'Carrefour'
  | 'Covabra'
  | 'Dom Olívio'
  | 'Fort Atacadista'
  | 'Oba Hortifruti'
  | 'Pão de Açúcar'
  | 'Roldão Atacadista'
  | 'São Vicente'
  | 'Tauste Supermercado'
  | 'Tenda Atacado'
  | 'Default';

const marketLogos: Record<MarketName, any> = {
  'Assaí Atacadista': require('../assets/logos/assai.png'),
  'Atacadão': require('../assets/logos/atacadao.png'),
  'Boa Supermercados': require('../assets/logos/boa.png'),
  'Carrefour': require('../assets/logos/carrefour.png'),
  'Covabra': require('../assets/logos/covabra.png'),
  'Dom Olívio': require('../assets/logos/dom_olivio.png'),
  'Fort Atacadista': require('../assets/logos/fort.png'),
  'Oba Hortifruti': require('../assets/logos/oba.png'),
  'Pão de Açúcar': require('../assets/logos/pao_de_acucar.png'),
  'Roldão Atacadista': require('../assets/logos/roldao.png'),
  'São Vicente': require('../assets/logos/sao_vicente.png'),
  'Tauste Supermercado': require('../assets/logos/tauste.png'),
  'Tenda Atacado': require('../assets/logos/tenda.png'),
  'Default': require('../assets/logos/default.png'),
};

export const getMarketLogo = (marketName: string) => {
  return marketLogos[marketName as MarketName] || marketLogos.Default;
};

interface ProductCardProps {
  product: Product;
  onPress?: (product: Product) => void;
}

const formatPrice = (value: number) => {
  return value.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
};

export const ProductCard = React.memo(({ product, onPress }: ProductCardProps) => {
  const [imageError, setImageError] = React.useState(false);

  React.useEffect(() => {
    setImageError(false);
  }, [product.Imagem]);

  const titleText = product.Produto_Ouro;
  const bestOffer = product.Ofertas && product.Ofertas.length > 0 ? product.Ofertas[0] : null;

  const showPlaceholder = !product.Imagem || !product.Imagem.startsWith('http') || imageError;

  const weightInfo = product.weight || product.volume || product.unidade_medida;
  const showWeight = weightInfo && !titleText.toLowerCase().includes(weightInfo.toLowerCase());

  // Lógica de cálculo de desconto: buscando o maior preço entre as ofertas para comparação
  const maxOfferPrice = React.useMemo(() => {
    return product.Ofertas?.reduce((max, oferta) => {
      return Math.max(max, oferta.Preco_Varejo || 0, oferta.Preco_Atacado || 0);
    }, 0) || 0;
  }, [product.Ofertas]);

  const originalPrice = (product as any).Maior_Preco || maxOfferPrice;
  const currentPrice = product.Menor_Preco || 0;
  const hasDiscount = originalPrice > currentPrice;
  const discountPercent = React.useMemo(() => hasDiscount ? Math.round(((originalPrice - currentPrice) / originalPrice) * 100) : 0, [hasDiscount, originalPrice, currentPrice]);

  // Conectando com o Zustand para saber se este produto específico está na lista
  const cartItem = useShoppingListStore(state => state.list.find(p => p.EAN === product.EAN && p.Produto_Ouro === product.Produto_Ouro));
  const isInList = !!cartItem;
  const quantity = (cartItem as any)?.quantity || 1;
  const toggleProduct = useShoppingListStore(state => state.toggleProduct);
  const updateQuantity = useShoppingListStore(state => (state as any).updateQuantity);

  return (
    <Card style={styles.card} onPress={() => onPress?.(product)}>
      <View style={styles.innerCard}>
        <View style={[styles.imageContainer, showPlaceholder && { padding: 0 }]}>
          {showPlaceholder ? (
            <Image source={require('../assets/placeholder.png')} style={styles.image} resizeMode="cover" />
          ) : (
            <Image 
              source={{ uri: product.Imagem }} 
              style={styles.image} 
              resizeMode="contain" 
              onError={() => setImageError(true)}
            />
          )}
          {!isInList ? (
            <IconButton
              icon="cart-plus"
              size={20}
              iconColor="#E5293E"
              containerColor="rgba(255, 255, 255, 0.9)"
              style={styles.addToListBtn}
              onPress={() => toggleProduct(product)}
            />
          ) : (
            <View style={styles.quantityContainer}>
              <IconButton
                icon="minus"
                size={16}
                iconColor="#E5293E"
                style={styles.quantityBtn}
                onPress={() => {
                  if (quantity > 1 && updateQuantity) updateQuantity(product, quantity - 1);
                  else toggleProduct(product); // Remove se chegar a zero
                }}
              />
              <Text style={styles.quantityText}>{quantity}</Text>
              <IconButton
                icon="plus"
                size={16}
                iconColor="#E5293E"
                style={styles.quantityBtn}
                onPress={() => updateQuantity && updateQuantity(product, quantity + 1)}
              />
            </View>
          )}
        </View>

        <View style={styles.contentContainer}>
          <View>
            <Title style={styles.title} numberOfLines={2}>{titleText}</Title>
            
            {showWeight && (
              <View style={styles.weightBadge}>
                <Text style={styles.weightText}>{weightInfo}</Text>
              </View>
            )}

            <View style={styles.brandRow}>
              <Text style={styles.brand} numberOfLines={1}>{product.Marca}</Text>
            </View>
            
            <View style={styles.priceSection}>
              <Text style={styles.priceLabel}>A partir de:</Text>
              {hasDiscount && (
                <View style={styles.originalPriceRow}>
                  <Text style={styles.originalPrice}>R$ {formatPrice(originalPrice)}</Text>
                  <View style={styles.discountTag}>
                    <Text style={styles.discountTagText}>-{discountPercent}%</Text>
                  </View>
                </View>
              )}
              <Text style={styles.currentPrice}>
                <Text style={styles.currencySymbol}>R$ </Text>{formatPrice(product.Menor_Preco)}
              </Text>
            </View>
          </View>

          <View style={styles.footer}>
            <Text style={styles.offerCount}>
              {product.Ofertas?.length === 1 ? 'Disponível em 1 mercado:' : `Disponíveis em ${product.Ofertas?.length || 0} mercados:`}
            </Text>
            {bestOffer && (
              <View style={styles.bestOfferInfo}>
                <Text style={styles.bestOfferMarket} numberOfLines={1}>{bestOffer.Mercado}</Text>
                <Image source={getMarketLogo(bestOffer.Mercado)} style={styles.smallStoreLogo} resizeMode="contain" />
              </View>
            )}
            {product.EAN && product.EAN.startsWith('INT_') && (
              <View style={styles.internalEanBadge}>
                <Text style={styles.internalEanText}>⚠️ Sem Cód. Barras</Text>
              </View>
            )}
          </View>
        </View>
      </View>
    </Card>
  );
}, (prevProps, nextProps) => {
  // Otimização extrema: O card não sofre re-renderização se o código e o preço continuam os mesmos
  return prevProps.product.EAN === nextProps.product.EAN && prevProps.product.Menor_Preco === nextProps.product.Menor_Preco;
});

const styles = StyleSheet.create({
  card: {
    width: '49%',
    marginVertical: 6,
    backgroundColor: '#ffffff',
    borderRadius: 12,
    elevation: 3,
  },
  innerCard: {
    overflow: 'hidden',
    borderRadius: 12,
  },
  imageContainer: {
    width: '100%',
    aspectRatio: 1, // Container agora é um quadrado perfeito
    backgroundColor: '#f9f9f9',
    padding: 16, // Respiro padrão para a imagem não colar nas bordas
  },
  addToListBtn: {
    position: 'absolute',
    top: 4,
    right: 4,
    margin: 0,
    elevation: 2,
  },
  quantityContainer: {
    position: 'absolute',
    top: 4,
    right: 4,
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: 'rgba(255, 255, 255, 0.9)',
    borderRadius: 20,
    elevation: 2,
    paddingHorizontal: 2,
  },
  quantityBtn: {
    margin: 0,
    width: 24,
    height: 24,
  },
  quantityText: {
    fontSize: 14,
    fontWeight: 'bold',
    color: '#333',
    minWidth: 16,
    textAlign: 'center',
  },
  image: { width: '100%', height: '100%' },
  contentContainer: {
    paddingHorizontal: 10,
    paddingTop: 10,
    paddingBottom: 4, // Diminui o respiro no final do card
    flex: 1,
    justifyContent: 'space-between',
  },
  title: {
    fontSize: 13,
    lineHeight: 18,
    height: 36,
    fontWeight: '600',
    color: '#333',
    marginBottom: 4,
  },
  brandRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 4,
  },
  brand: {
    fontSize: 11,
    color: '#777',
    flex: 1,
    marginRight: 4,
  },
  weightBadge: {
    alignSelf: 'flex-start',
    backgroundColor: '#F0F0F0',
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
    marginBottom: 4,
  },
  weightText: {
    fontSize: 10,
    color: '#666',
    fontWeight: '600',
  },
  priceSection: {
    marginTop: 4,
  },
  bestOfferInfo: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 4,
  },
  smallStoreLogo: {
    width: 44,
    height: 32,
  },
  bestOfferMarket: {
    fontSize: 10,
    fontWeight: 'bold',
    color: '#E5293E',
    flexShrink: 1,
  },
  priceLabel: {
    fontSize: 10,
    color: '#888',
  },
  originalPriceRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 2,
  },
  originalPrice: {
    fontSize: 12,
    color: '#666666',
    textDecorationLine: 'line-through',
    marginRight: 6,
  },
  discountTag: {
    backgroundColor: '#4CAF50',
    paddingHorizontal: 4,
    paddingVertical: 2,
    borderRadius: 4,
  },
  discountTagText: {
    color: '#fff',
    fontSize: 9,
    fontWeight: 'bold',
  },
  currentPrice: {
    fontSize: 18,
    fontWeight: 'bold',
    color: '#E5293E',
  },
  currencySymbol: {
    fontSize: 12,
    fontWeight: 'normal',
  },
  footer: {
    flexDirection: 'column',
    alignItems: 'stretch',
    marginTop: 8,
    paddingTop: 6,
    paddingBottom: 0, // Remove o excesso de espaço sobrando embaixo do mercado
    borderTopWidth: 1,
    borderTopColor: '#eee',
  },
  offerCount: {
    fontSize: 10,
    color: '#666',
    fontWeight: '500',
    marginBottom: 4,
  },
  storeLogo: {
    width: 40,
    height: 16,
  },
  internalEanBadge: {
    backgroundColor: '#fff3cd',
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
    alignSelf: 'flex-start',
    marginTop: 4,
  },
  internalEanText: {
    fontSize: 9,
    color: '#856404',
    fontWeight: 'bold',
  },
});
