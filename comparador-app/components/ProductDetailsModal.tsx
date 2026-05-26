import React from 'react';
import { View, StyleSheet, Modal, Image, ScrollView } from 'react-native';
import { Text, Title, IconButton, Divider } from 'react-native-paper';
import { Product } from '../types';
import { getMarketLogo } from './ProductCard';
import { SafeAreaView } from 'react-native-safe-area-context';

interface ProductDetailsModalProps {
  visible: boolean;
  onDismiss: () => void;
  product: Product | null;
}

const formatPrice = (value: number) => {
  return value.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
};

export const ProductDetailsModal: React.FC<ProductDetailsModalProps> = ({ visible, onDismiss, product }) => {
  const [imageError, setImageError] = React.useState(false);

  React.useEffect(() => {
    setImageError(false);
  }, [product?.Imagem]);

  if (!product) return null;

  const showPlaceholder = !product.Imagem || !product.Imagem.startsWith('http') || imageError;

  return (
    <Modal visible={visible} animationType="slide" transparent={false} onRequestClose={onDismiss}>
      <SafeAreaView style={styles.container}>
        <View style={styles.header}>
          <IconButton icon="close" size={24} onPress={onDismiss} iconColor="#333" />
          <Text style={styles.headerTitle}>Comparar Preços</Text>
          <View style={{ width: 48 }} />
        </View>

        <ScrollView contentContainerStyle={styles.scrollContent} showsVerticalScrollIndicator={false}>
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

          <View style={styles.infoContainer}>
            <Title style={styles.title}>{product.Produto_Ouro}</Title>
            <Text style={styles.brand}>{product.Marca}</Text>
            <Text style={styles.category}>{product.Categoria_Ouro}</Text>
            
            <Divider style={styles.divider} />
            <Text style={styles.offersHeader}>Disponível em {product.Ofertas.length} mercados:</Text>
            
            {product.Ofertas.map((oferta, index) => (
              <View key={index} style={styles.offerRow}>
                <View style={styles.marketInfo}>
                  <Image source={getMarketLogo(oferta.Mercado)} style={styles.marketLogo} resizeMode="contain" />
                  <View>
                    <Text style={styles.marketName}>{oferta.Mercado}</Text>
                    {oferta.Condicao ? (
                      <Text style={styles.conditionText}>{oferta.Condicao}</Text>
                    ) : null}
                  </View>
                </View>
                <View style={styles.priceInfo}>
                  {oferta.Preco_Atacado > 0 && oferta.Preco_Atacado < (oferta.Preco_Varejo || 999999) ? (
                    <>
                      <Text style={styles.priceText}>
                        <Text style={styles.currencySymbol}>R$ </Text>{formatPrice(oferta.Preco_Atacado)}
                      </Text>
                      {oferta.Preco_Varejo > 0 && (
                        <Text style={styles.retailText}>R$ {formatPrice(oferta.Preco_Varejo)}</Text>
                      )}
                    </>
                  ) : (
                    <Text style={styles.priceText}>
                      <Text style={styles.currencySymbol}>R$ </Text>{formatPrice(oferta.Preco_Varejo)}
                    </Text>
                  )}
                </View>
              </View>
            ))}
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
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 8,
    paddingVertical: 8,
    borderBottomWidth: 1,
    borderBottomColor: '#f0f0f0',
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
    backgroundColor: '#f9f9f9',
  },
  image: { width: '100%', height: '100%' },
  infoContainer: {
    padding: 20,
  },
  title: {
    fontSize: 22,
    lineHeight: 28,
    fontWeight: 'bold',
    color: '#222',
  },
  brand: {
    fontSize: 16,
    color: '#666',
    marginTop: 4,
  },
  category: {
    fontSize: 14,
    color: '#999',
    marginTop: 8,
  },
  divider: {
    marginVertical: 20,
    backgroundColor: '#eee',
    height: 1,
  },
  offersHeader: {
    fontSize: 16,
    fontWeight: 'bold',
    color: '#444',
    marginBottom: 16,
  },
  offerRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#f5f5f5',
  },
  marketInfo: {
    flexDirection: 'row',
    alignItems: 'center',
    flex: 1,
  },
  marketLogo: {
    width: 40,
    height: 40,
    marginRight: 12,
  },
  marketName: {
    fontSize: 16,
    fontWeight: '600',
    color: '#333',
  },
  conditionText: {
    fontSize: 12,
    color: '#e67e22',
    marginTop: 2,
    maxWidth: 160,
  },
  priceInfo: {
    alignItems: 'flex-end',
  },
  priceText: {
    fontSize: 20,
    fontWeight: 'bold',
    color: '#E5293E',
  },
  currencySymbol: {
    fontSize: 14,
    fontWeight: 'normal',
  },
  wholesaleText: {
    fontSize: 12,
    color: '#27ae60',
    fontWeight: '600',
    marginTop: 2,
  },
  wholesaleTextLabel: {
    fontSize: 10,
    color: '#E5293E',
    fontWeight: 'bold',
    marginBottom: 2,
    textTransform: 'uppercase',
  },
  retailTextLabel: {
    fontSize: 10,
    color: '#E5293E',
    fontWeight: 'bold',
    marginBottom: 2,
    textTransform: 'uppercase',
  },
  retailText: {
    fontSize: 12,
    color: '#666',
    textDecorationLine: 'line-through',
    marginTop: 2,
  },
});
