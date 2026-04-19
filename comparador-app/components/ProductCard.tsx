import React from 'react';
import { View, StyleSheet, Image } from 'react-native';
import { Card, Text, Title } from 'react-native-paper';
import { Product } from '../types';

interface ProductCardProps {
  product: Product;
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

const marketLogos: { [key: string]: string } = {
  'OBA HORTIFRUTI': 'https://www.plataformaneo.com.br/wp-content/uploads/2023/07/logo-oba-hortifruti-g-1.png',
  'SÃO VICENTE': 'https://www.svicente.com.br/arquivos/logo-sao-vicente-horizontal.png',
  'PÃO DE AÇÚCAR': 'https://logodownload.org/wp-content/uploads/2014/07/pao-de-acucar-logo-1.png',
  'CARREFOUR': 'https://logodownload.org/wp-content/uploads/2014/11/carrefour-logo-1.png',
  'ATACADÃO': 'https://logodownload.org/wp-content/uploads/2019/11/atacadao-logo-1.png',
  'ASSAÍ ATACADISTA': 'https://logodownload.org/wp-content/uploads/2020/09/assai-atacadista-logo-1.png',
  'TAUSTE SUPERMERCADO': 'https://www.tauste.com.br/static/media/logo-tauste.43a69d75.svg',
};

const MarketLogoDisplay = ({ marketName }: { marketName: string | null }) => {
  const normalizedMarketName = marketName?.toUpperCase().trim() || '';
  const logoUri = marketLogos[normalizedMarketName];
  if (logoUri) return <Image source={{ uri: logoUri }} style={styles.storeLogo} resizeMode="contain" />;
  return (
    <View style={styles.storeIconFallback}>
      <Text style={styles.storeIconText}>{marketName ? marketName.charAt(0).toUpperCase() : 'M'}</Text>
    </View>
  );
};

export const ProductCard: React.FC<ProductCardProps> = ({ product }) => {
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
    <Card style={styles.card}>
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
            <MarketLogoDisplay marketName={product.Mercado} />
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
    height: 35,
  },
  storeInfo: { flexDirection: 'row', alignItems: 'center', flex: 1 },
  storeLogo: { width: 18, height: 18, borderRadius: 9, marginRight: 6 },
  storeIconFallback: { width: 18, height: 18, borderRadius: 9, backgroundColor: '#eee', justifyContent: 'center', alignItems: 'center', marginRight: 6 },
  storeIconText: { fontSize: 9, fontWeight: 'bold' },
  storeName: { fontSize: 11, color: '#888', flex: 1 },
});