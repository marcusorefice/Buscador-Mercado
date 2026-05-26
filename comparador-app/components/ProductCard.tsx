import React from 'react';
import { View, StyleSheet, Image } from 'react-native';
import { Card, Text, Title } from 'react-native-paper';
import { Product } from '../types';

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
  onPress?: () => void;
}

const formatPrice = (value: number) => {
  return value.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
};

export const ProductCard: React.FC<ProductCardProps> = ({ product, onPress }) => {
  const [imageError, setImageError] = React.useState(false);

  React.useEffect(() => {
    setImageError(false);
  }, [product.Imagem]);

  const titleText = product.Produto_Ouro;
  const bestOffer = product.Ofertas && product.Ofertas.length > 0 ? product.Ofertas[0] : null;

  const showPlaceholder = !product.Imagem || !product.Imagem.startsWith('http') || imageError;

  return (
    <Card style={styles.card} onPress={onPress}>
      <View style={styles.imageContainer}>
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
      </View>

      <View style={styles.contentContainer}>
        <View>
          <Title style={styles.title} numberOfLines={2}>{titleText}</Title>
          <Text style={styles.brand} numberOfLines={1}>{product.Marca}</Text>
          
          <View style={styles.priceSection}>
            <Text style={styles.priceLabel}>A partir de:</Text>
            <Text style={styles.currentPrice}>
              <Text style={styles.currencySymbol}>R$ </Text>{formatPrice(product.Menor_Preco)}
            </Text>
          </View>
        </View>

        <View style={styles.footer}>
          <Text style={styles.offerCount}>
            {product.Ofertas.length} {product.Ofertas.length === 1 ? 'mercado' : 'mercados'}
          </Text>
          {bestOffer && (
            <View style={styles.bestOfferInfo}>
              <Image source={getMarketLogo(bestOffer.Mercado)} style={styles.smallStoreLogo} resizeMode="contain" />
              <Text style={styles.bestOfferMarket} numberOfLines={1}>{bestOffer.Mercado}</Text>
            </View>
          )}
        </View>
      </View>
    </Card>
  );
};

const styles = StyleSheet.create({
  card: {
    width: '49%',
    marginVertical: 6,
    backgroundColor: '#ffffff',
    borderRadius: 12,
    overflow: 'hidden',
    elevation: 3,
  },
  imageContainer: {
    width: '100%',
    aspectRatio: 1.4,
    backgroundColor: '#f9f9f9',
  },
  image: { width: '100%', height: '100%' },
  contentContainer: {
    padding: 10,
    flex: 1,
    justifyContent: 'space-between',
  },
  title: {
    fontSize: 13,
    lineHeight: 16,
    fontWeight: '600',
    color: '#333',
    marginBottom: 2,
  },
  brand: {
    fontSize: 11,
    color: '#777',
    marginBottom: 6,
  },
  priceSection: {
    marginTop: 4,
  },
  bestOfferInfo: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 4,
  },
  smallStoreLogo: {
    width: 24,
    height: 12,
    marginRight: 4,
  },
  bestOfferMarket: {
    fontSize: 10,
    fontWeight: 'bold',
    color: '#E5293E',
  },
  priceLabel: {
    fontSize: 10,
    color: '#888',
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
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginTop: 10,
    paddingTop: 8,
    borderTopWidth: 1,
    borderTopColor: '#eee',
  },
  offerCount: {
    fontSize: 10,
    color: '#666',
    fontWeight: '500',
  },
  storeLogo: {
    width: 40,
    height: 16,
  },
});
