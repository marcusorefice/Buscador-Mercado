import React from 'react';
import { View, StyleSheet, Image } from 'react-native';
import { Card, Text, Title } from 'react-native-paper';
import { Product } from '../types';

// --- INÍCIO DA LÓGICA DE LOGOS ---
// A lógica foi movida para este arquivo para resolver um erro de importação persistente.

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
  'Default': require('../assets/logos/default.png'), // Um logo padrão
};

export const getMarketLogo = (marketName: string) => {
  return marketLogos[marketName as MarketName] || marketLogos.Default;
};
// --- FIM DA LÓGICA DE LOGOS ---
interface ProductCardProps {
  product: Product;
  onPress?: () => void;
}

const capitalize = (str: string | null): string => {
  if (!str) return '';
  return str.toLowerCase().replace(/(?:^|\s)\S/g, (a) => a.toUpperCase());
};

const parsePrice = (priceStr: string): number => {
  const cleanStr = priceStr.replace(/\./g, '').replace(',', '.');
  const val = parseFloat(cleanStr);
  return isNaN(val) ? 0 : val;
};

export const ProductCard: React.FC<ProductCardProps> = ({ product, onPress }) => {
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

  return (
    <Card style={styles.card} onPress={onPress}>
      <View style={styles.imageContainer}>
        {product.Link_Imagem ? (
          <Image source={{ uri: product.Link_Imagem }} style={styles.image} resizeMode="contain" />
        ) : (
          <View style={styles.placeholderImage}><Text style={styles.placeholderText}>Sem Imagem</Text></View>
        )}
        {discountPercent > 0 && (
          <View style={styles.discountBadge}><Text style={styles.discountText}>-{discountPercent}%</Text></View>
        )}
      </View>

      <View style={styles.contentContainer}>
        <View>
          <Title style={styles.title} numberOfLines={2}>{titleText}</Title>
          
          <View style={styles.priceSection}>
            {previousPriceStr ? (
              <Text style={styles.previousPrice}>De: R$ {previousPriceStr}</Text>
            ) : (
              <View style={{ height: 16 }} /> // Placeholder para manter altura
            )}
            <Text style={styles.currentPrice}>
              <Text style={styles.currencySymbol}>Por: R$ </Text>{currentPriceStr}
            </Text>
          </View>

          <View style={styles.conditionWrapper}>
            {hasCondition ? (
              <Text style={styles.wholesalePrice} numberOfLines={1}>{product.Condicao}</Text>
            ) : null}
          </View>
        </View>

        <View style={styles.footer}>
          <View style={styles.storeInfo}>
            <Image source={getMarketLogo(product.Mercado || 'Default')} style={styles.storeLogo} resizeMode="contain" />
            <Text style={styles.storeName} numberOfLines={1}>{product.Mercado || 'Mercado'}</Text>
          </View>
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
  placeholderImage: { flex: 1, justifyContent: 'center', alignItems: 'center' },
  placeholderText: { fontSize: 10, color: '#ccc' },
  discountBadge: {
    position: 'absolute',
    top: 0,
    left: 0,
    backgroundColor: '#17c671',
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderBottomRightRadius: 8,
  },
  discountText: { color: '#fff', fontSize: 14, fontWeight: 'bold' },
  contentContainer: {
    padding: 10,
    flex: 1,
    justifyContent: 'space-between', // EMPURRA O FOOTER PARA BAIXO
    minHeight: 160, // Força uma altura mínima no conteúdo
  },
  title: {
    fontSize: 13,
    lineHeight: 17,
    fontWeight: 'bold',
    color: '#333',
    height: 36, // ALTURA FIXA PARA 2 LINHAS
    marginBottom: 4,
  },
  priceSection: {
    marginTop: 4,
    minHeight: 45,
  },
  previousPrice: {
    fontSize: 12,
    color: '#999',
    textDecorationLine: 'line-through',
  },
  currentPrice: {
    fontSize: 22,
    fontWeight: '900',
    color: '#E5293E',
    marginTop: -2,
  },
  currencySymbol: { fontSize: 12 },
  conditionWrapper: {
    height: 18, // ESPAÇO RESERVADO PARA "CLUBE" OU "ATACADO"
    justifyContent: 'center',
    marginTop: 2,
  },
  wholesalePrice: {
    fontSize: 11,
    color: '#607d8b',
    fontWeight: '600',
  },
  footer: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    borderTopWidth: 1,
    borderTopColor: '#f0f0f0',
    paddingTop: 8,
    marginTop: 10,
    height: 48,
  },
  storeInfo: { flexDirection: 'row', alignItems: 'center', flex: 1 },
  storeLogo: { width: 65, height: 65, borderRadius: 20, marginRight: 8 },
  storeName: { fontSize: 13, color: '#888', flex: 1 },
});