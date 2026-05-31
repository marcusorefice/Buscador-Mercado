import React from 'react';
import { View, StyleSheet, Modal, Image, ScrollView, ActivityIndicator, TouchableOpacity, ToastAndroid, Linking, Alert } from 'react-native';
import { Text, Title, IconButton, Divider, Chip, Button } from 'react-native-paper';
import { Product } from '../types';
import { getMarketLogo } from './ProductCard';
import { SafeAreaView } from 'react-native-safe-area-context';
import axios from 'axios';
import { useShoppingListStore } from './useShoppingListStore';
import * as Clipboard from 'expo-clipboard';

interface ProductDetailsModalProps {
  visible: boolean;
  onDismiss: () => void;
  product: Product | null;
  apiUrl: string;
}

const formatPrice = (value: number) => {
  return value.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
};

export const ProductDetailsModal: React.FC<ProductDetailsModalProps> = ({ visible, onDismiss, product, apiUrl }) => {
  const [imageError, setImageError] = React.useState(false);
  const [detailedProduct, setDetailedProduct] = React.useState<Product | null>(null);
  const [isLoading, setIsLoading] = React.useState(false);
  const [selectedOfferIndex, setSelectedOfferIndex] = React.useState<number>(0);

  React.useEffect(() => {
    setImageError(false);
    // Quando o modal abre com um produto novo, busca os detalhes completos
    if (visible && product) {
      // Começa com o produto parcial para a UI não piscar
      setDetailedProduct(product); 
      setIsLoading(true);
      setSelectedOfferIndex(0); // Reseta a seleção para a melhor oferta ao abrir

      // Atrasar a busca levemente para não engasgar a animação de "Slide" do Modal
      const timer = setTimeout(() => {
        const fetchDetails = async () => {
          try {
            const response = await axios.get<Product[]>(`${apiUrl}/produtos`, {
              params: { q: product.EAN },
              headers: { 'ngrok-skip-browser-warning': 'true', 'Bypass-Tunnel-Reminder': 'true' }
            });
            if (response.data && response.data.length > 0) {
              setDetailedProduct(response.data[0]);
            }
          } catch (error) {
            console.error("Falha ao buscar detalhes completos do produto:", error);
            setDetailedProduct(product);
          } finally {
            setIsLoading(false);
          }
        };
        fetchDetails();
      }, 100);

      return () => clearTimeout(timer);
    }
  }, [visible, product, apiUrl]);

  const productToRender = detailedProduct || product;

  // Conectando com o Zustand (Regra do React: Hooks DEVEM ficar antes de qualquer 'return')
  const isInList = useShoppingListStore(state => productToRender ? state.list.some(p => p.EAN === productToRender.EAN && p.Produto_Ouro === productToRender.Produto_Ouro) : false);
  const toggleProduct = useShoppingListStore(state => state.toggleProduct);

  if (!productToRender) return null;

  // Oferta Ativa para o Card Superior (Atualizada ao clicar na lista de baixo)
  const activeOffer = productToRender.Ofertas && productToRender.Ofertas.length > 0 
    ? productToRender.Ofertas[selectedOfferIndex] || productToRender.Ofertas[0] 
    : null;
    
  // Lógica de Desconto Dinâmica baseada na oferta selecionada
  const originalPrice = activeOffer?.Preco_Varejo || 0;
  const currentPrice = activeOffer && activeOffer.Preco_Atacado > 0 && activeOffer.Preco_Atacado < originalPrice 
    ? activeOffer.Preco_Atacado 
    : originalPrice;

  const displayCurrentPrice = currentPrice > 0 ? currentPrice : (productToRender.Menor_Preco || 0);
  const displayOriginalPrice = originalPrice > 0 ? originalPrice : displayCurrentPrice;

  const hasDiscount = displayOriginalPrice > displayCurrentPrice && displayOriginalPrice > 0 && displayCurrentPrice > 0;
  const discountPercent = hasDiscount ? Math.round(((displayOriginalPrice - displayCurrentPrice) / displayOriginalPrice) * 100) : 0;
  
  const showPlaceholder = !productToRender.Imagem || !productToRender.Imagem.startsWith('http') || imageError;

  // Transforma o EAN em texto de forma segura
  const eanStr = String(productToRender?.EAN || '').trim();
  // Validação: Tem pelo menos 8 dígitos, não começa com '0' e possui apenas números
  const isValidEAN = eanStr.length >= 8 && !eanStr.startsWith('0') && /^\d+$/.test(eanStr);

  // Função que copia para a área de transferência
  const copyToClipboard = async () => {
    await Clipboard.setStringAsync(eanStr);
    ToastAndroid.show('EAN copiado!', ToastAndroid.SHORT);
  };

  const abrirLinkDoProduto = (link?: string) => {
    if (link && link !== "") {
      Linking.openURL(link).catch(() => {
        Alert.alert("Erro", "Não foi possível abrir o link do mercado.");
      });
    }
  };

  return (
    <Modal visible={visible} animationType="slide" presentationStyle="pageSheet" onRequestClose={onDismiss}>
      <SafeAreaView style={styles.container} edges={['bottom', 'left', 'right']}>
        <View style={styles.header}>
          <TouchableOpacity onPress={onDismiss} style={styles.closeButton} hitSlop={{ top: 20, bottom: 20, left: 20, right: 20 }}>
            <Text style={styles.closeButtonText}>✕</Text>
          </TouchableOpacity>
          <Text style={styles.headerTitle}>Comparar Preços</Text>
          <View style={{ width: 48 }} />
        </View>

        <ScrollView contentContainerStyle={styles.scrollContent} showsVerticalScrollIndicator={false}>
          <View style={[styles.imageContainer, showPlaceholder && { padding: 0 }]}>
            {showPlaceholder ? (
              <Image source={require('../assets/placeholder.png')} style={styles.image} resizeMode="cover" />
            ) : (
              <Image 
                source={{ uri: productToRender.Imagem }} 
                style={styles.image} 
                resizeMode="contain" 
                onError={() => setImageError(true)}
              />
            )}
          </View>

          <View style={styles.infoContainer}>
            <Title style={styles.title}>{productToRender.Produto_Ouro}</Title>
            <Text style={styles.brand}>{productToRender.Marca}</Text>
            <Text style={styles.category}>{productToRender.Categoria_Ouro}</Text>

            {isValidEAN && (
              <TouchableOpacity 
                style={styles.eanContainer} 
                onPress={copyToClipboard} 
                activeOpacity={0.6}
              >
                <Text style={styles.eanText}>EAN: {eanStr}</Text>
                <IconButton 
                  icon="content-copy" 
                  size={12} 
                  iconColor="#999" 
                  style={styles.copyIcon} 
                />
              </TouchableOpacity>
            )}
            
            <View style={styles.mainOfferContainer}>
              <Text style={styles.mainOfferLabel}>
                {selectedOfferIndex === 0 ? 'Melhor oferta encontrada:' : 'Oferta selecionada:'}
              </Text>
              <View style={styles.mainOfferRow}>
                <Text style={styles.mainPriceText}>
                  <Text style={styles.mainCurrencySymbol}>R$ </Text>{formatPrice(displayCurrentPrice)}
                  {activeOffer?.Unidade && activeOffer.Unidade !== 'UN' ? (
                    <Text style={{ fontSize: 16, color: '#888', fontWeight: 'normal' }}> / {activeOffer.Unidade.toLowerCase()}</Text>
                  ) : activeOffer?.Medida === 'KG' && activeOffer?.Qtd_Valor === '1' ? (
                    <Text style={{ fontSize: 16, color: '#888', fontWeight: 'normal' }}> / kg</Text>
                  ) : (
                    <Text style={{ fontSize: 16, color: '#888', fontWeight: 'normal' }}> un</Text>
                  )}
                </Text>
                {activeOffer && (
                  <View style={styles.bestOfferBadgeContainer}>
                    <TouchableOpacity 
                      style={styles.topMarketBadge}
                      onPress={() => abrirLinkDoProduto(activeOffer.Link_PDP)}
                      activeOpacity={activeOffer.Link_PDP ? 0.7 : 1}
                    >
                      <Text style={[styles.topMarketText, activeOffer.Link_PDP ? styles.marketNameLink : null]}>
                        {activeOffer.Mercado} {activeOffer.Link_PDP ? '🔗' : ''}
                      </Text>
                      <Image source={getMarketLogo(activeOffer.Mercado)} style={styles.topMarketLogo} resizeMode="contain" />
                    </TouchableOpacity>
                    {activeOffer.Condicao && (
                      <Text style={[styles.bestOfferCondition, activeOffer.Condicao === '1 UN' && { color: '#888' }]}>
                        {activeOffer.Condicao}
                      </Text>
                    )}
                  </View>
                )}
              </View>
              
              {hasDiscount && (
                <View style={styles.discountInfoContainer}>
                  <Text style={styles.originalPrice}>De R$ {formatPrice(displayOriginalPrice)}</Text>
                  <Chip icon="arrow-down" style={styles.discountChip} textStyle={styles.discountChipText} compact>
                    {`-${discountPercent}%`}
                  </Chip>
                </View>
              )}

              <Button 
                mode="contained" 
                icon={isInList ? "cart-check" : "cart-plus"} 
                style={[styles.addToListButtonModal, isInList && { backgroundColor: '#4CAF50' }]}
                onPress={() => toggleProduct(productToRender)}
              >
                {isInList ? 'Adicionado à Lista' : 'Adicionar à Lista'}
              </Button>
            </View>

            <Divider style={styles.divider} />

            <View style={styles.offersHeaderRow}>
              <Text style={styles.offersHeader}>
                {productToRender.Ofertas.length === 1 
                  ? 'Disponível em 1 mercado:' 
                  : `Disponíveis em ${productToRender.Ofertas.length} mercados:`}
              </Text>
              {isLoading && <ActivityIndicator size="small" color="#E5293E" />}
            </View>

            {productToRender.Ofertas.map((oferta, index) => {
              const isSelected = index === selectedOfferIndex;
              const content = (
                <View style={[styles.offerRow, isSelected && styles.offerRowSelected]}>
                  <View style={styles.marketInfo}>
                    <Image source={getMarketLogo(oferta.Mercado)} style={styles.marketLogo} resizeMode="contain" />
                    <View>
                      <Text style={styles.marketName}>
                        {oferta.Mercado}
                      </Text>
                      {oferta.Condicao && (
                        <Text style={[styles.conditionText, oferta.Condicao === '1 UN' && { color: '#888' }]}>{oferta.Condicao}</Text>
                      )}
                    </View>
                  </View>
                  <View style={styles.priceInfo}>
                    {oferta.Preco_Atacado > 0 && oferta.Preco_Atacado < (oferta.Preco_Varejo || 999999) ? (
                      <>
                        <Text style={styles.priceText}>
                          <Text style={styles.currencySymbol}>R$ </Text>{formatPrice(oferta.Preco_Atacado)}
                          {oferta.Unidade && oferta.Unidade !== 'UN' ? (
                            <Text style={{ fontSize: 12, color: '#888', fontWeight: 'normal' }}> / {oferta.Unidade.toLowerCase()}</Text>
                          ) : oferta.Medida === 'KG' && oferta.Qtd_Valor === '1' ? (
                            <Text style={{ fontSize: 12, color: '#888', fontWeight: 'normal' }}> / kg</Text>
                          ) : (
                            <Text style={{ fontSize: 12, color: '#888', fontWeight: 'normal' }}> un</Text>
                          )}
                        </Text>
                        {oferta.Preco_Varejo > 0 && (
                          <Text style={styles.retailText}>R$ {formatPrice(oferta.Preco_Varejo)}</Text>
                        )}
                      </>
                    ) : (
                      <Text style={styles.priceText}>
                        <Text style={styles.currencySymbol}>R$ </Text>{formatPrice(oferta.Preco_Varejo)}
                        {oferta.Unidade && oferta.Unidade !== 'UN' ? (
                          <Text style={{ fontSize: 12, color: '#888', fontWeight: 'normal' }}> / {oferta.Unidade.toLowerCase()}</Text>
                        ) : oferta.Medida === 'KG' && oferta.Qtd_Valor === '1' ? (
                          <Text style={{ fontSize: 12, color: '#888', fontWeight: 'normal' }}> / kg</Text>
                        ) : (
                          <Text style={{ fontSize: 12, color: '#888', fontWeight: 'normal' }}> un</Text>
                        )}
                      </Text>
                    )}
                  </View>
                </View>
              );

              return (
                <TouchableOpacity 
                  key={index} 
                  onPress={() => setSelectedOfferIndex(index)}
                  activeOpacity={0.7}
                >
                  {content}
                </TouchableOpacity>
              );
            })}
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
    backgroundColor: '#fff',
    zIndex: 10,
  },
  closeButton: {
    width: 48,
    height: 48,
    justifyContent: 'center',
    alignItems: 'center',
  },
  closeButtonText: {
    fontSize: 22,
    fontWeight: 'bold',
    color: '#444',
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
    aspectRatio: 1, // Container quadrado acompanhando o padrão do app
    backgroundColor: '#f9f9f9',
    padding: 24, // Respiro maior para o modal
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
  eanContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: 2,
  },
  eanText: {
    fontSize: 11,
    color: '#999', // Cinza claro e discreto
  },
  copyIcon: {
    margin: 0,
    marginLeft: -4, // Aproxima o ícone do texto
    width: 24,
    height: 24,
  },
  mainOfferContainer: {
    marginTop: 16,
    backgroundColor: '#fdfdfd',
    padding: 16,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#eee',
  },
  mainOfferLabel: {
    fontSize: 12,
    color: '#666',
    marginBottom: 8,
    textTransform: 'uppercase',
    fontWeight: 'bold',
  },
  mainOfferRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  mainPriceText: {
    fontSize: 32,
    fontWeight: 'bold',
    color: '#E5293E',
  },
  mainCurrencySymbol: {
    fontSize: 18,
    fontWeight: 'normal',
  },
  bestOfferBadgeContainer: {
    alignItems: 'flex-end',
  },
  topMarketBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#fff',
    paddingHorizontal: 8,
    paddingVertical: 6,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#e0e0e0',
  },
  topMarketText: {
    fontSize: 11,
    color: '#555',
    marginRight: 6,
  },
  topMarketLogo: {
    width: 48,
    height: 24,
  },
  bestOfferCondition: {
    fontSize: 10,
    color: '#e67e22',
    fontWeight: 'bold',
    marginTop: 4,
    textAlign: 'right',
  },
  addToListButtonModal: {
    marginTop: 16,
    borderRadius: 8,
    backgroundColor: '#E5293E',
  },
  divider: {
    marginVertical: 20,
    backgroundColor: '#eee',
    height: 1,
  },
  offersHeaderRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 16,
  },
  offersHeader: {
    fontSize: 16,
    fontWeight: 'bold',
    color: '#444',
  },
  discountInfoContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: 12,
    backgroundColor: '#fff8f9',
    padding: 8,
    borderRadius: 8,
  },
  originalPrice: {
    fontSize: 16,
    color: '#777',
    textDecorationLine: 'line-through',
  },
  discountChip: {
    marginLeft: 12,
    backgroundColor: '#4CAF50',
  },
  discountChipText: {
    color: '#fff',
    fontWeight: 'bold',
  },
  offerRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: 12,
    paddingHorizontal: 8,
    borderBottomWidth: 1,
    borderBottomColor: '#f5f5f5',
  },
  offerRowSelected: {
    backgroundColor: '#fff0f2',
    borderRadius: 8,
    borderBottomColor: 'transparent',
  },
  marketInfo: {
    flexDirection: 'row',
    alignItems: 'center',
    flex: 1,
  },
  marketLogo: {
    width: 48,
    height: 48,
    marginRight: 16,
  },
  marketName: {
    fontSize: 16,
    fontWeight: '600',
    color: '#333',
  },
  marketNameLink: {
    color: '#0066cc',
    textDecorationLine: 'underline',
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
