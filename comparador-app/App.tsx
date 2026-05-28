import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { View, StyleSheet, ActivityIndicator, StatusBar, TouchableOpacity, ScrollView, Modal, Platform } from 'react-native';
import { Provider as PaperProvider, DefaultTheme, Searchbar, Text, Chip, IconButton, Button } from 'react-native-paper';
import { SafeAreaProvider, SafeAreaView } from 'react-native-safe-area-context';
import axios from 'axios';
import { ProductList } from './components/ProductList';
import { ProductDetailsModal } from './components/ProductDetailsModal';
import { ShoppingListModal } from './components/ShoppingListModal';
import { useShoppingListStore } from './components/useShoppingListStore';
import { Product } from './types';
import { SkeletonCard } from './components/SkeletonCard';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { CameraView, useCameraPermissions } from 'expo-camera';

// --- CONFIGURAÇÃO DE AMBIENTE ---
const API_URL = __DEV__ 
  ? 'https://badness-impale-suitably.ngrok-free.dev' // ngrok: Ignora o Firewall do Windows e atualiza na hora!
  : 'https://buscador-mercado.onrender.com';         // Render: App Oficial da Nuvem

const theme = {
  ...DefaultTheme,
  colors: {
    ...DefaultTheme.colors,
    primary: '#E5293E', // Vermelho vibrante estilo app comercial
    accent: '#ff4d5a',
  },
};

const MARKETS = [
  'Todos os Mercados',
  'Assaí Atacadista',
  'Atacadão',
  'Boa Supermercados',
  'Carrefour',
  'Covabra',
  'Dom Olívio',
  'Fort Atacadista',
  'Oba Hortifruti',
  'Pão de Açúcar',
  'Roldão Atacadista',
  'São Vicente',
  'Tauste Supermercado',
  'Tenda Atacado'
];

export default function App() {
  const [searchQuery, setSearchQuery] = useState('');
  const searchQueryRef = useRef('');
  
  const [products, setProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  const [selectedProduct, setSelectedProduct] = useState<Product | null>(null);
  const [isModalVisible, setModalVisible] = useState(false);
  const [isCartVisible, setCartVisible] = useState(false);
  
  const [isScanning, setIsScanning] = useState(false);
  const [permission, requestPermission] = useCameraPermissions();

  // Lendo a quantidade de itens na lista usando Zustand
  const cartItemsCount = useShoppingListStore(state => state.list.length);

  // Filtros Globais
  const [sortBy, setSortBy] = useState<'discount' | 'price'>('discount');
  const [selectedMarket, setSelectedMarket] = useState('Todos os Mercados');
  const [isMarketModalVisible, setMarketModalVisible] = useState(false);

  const fetchProducts = useCallback(async (queryOverride?: string, isRefresh = false) => {
    if (isRefresh) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }
    setError(null);
    try {
      const currentQuery = queryOverride !== undefined ? queryOverride : searchQueryRef.current;
      const params: any = { q: currentQuery, sort_by: sortBy };
      if (selectedMarket !== 'Todos os Mercados') {
        params.market = selectedMarket;
      }
      
      const response = await axios.get<Product[]>(`${API_URL}/produtos`, {
        params,
        headers: { 
          'ngrok-skip-browser-warning': 'true',
          'Bypass-Tunnel-Reminder': 'true'
        }
      });
      setProducts(response.data);

      // Otimização Extrema (Offline-first): Salva em cache se for a busca inicial padrão
      if (!currentQuery && selectedMarket === 'Todos os Mercados' && sortBy === 'discount') {
        AsyncStorage.setItem('@cached_home_products', JSON.stringify(response.data)).catch(() => {});
      }
    } catch (err) {
      console.error(err);
      setError('Não foi possível carregar os produtos.');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [sortBy, selectedMarket]);

  useEffect(() => {
    // Tenta carregar o cache primeiro para mostrar os produtos instantaneamente
    const loadCache = async () => {
      try {
        const cached = await AsyncStorage.getItem('@cached_home_products');
        if (cached) {
          setProducts(JSON.parse(cached));
        }
      } catch (e) {}
    };
    loadCache();
  }, []);

  useEffect(() => {
    fetchProducts();
  }, [fetchProducts]);

  const handleSearchChange = (text: string) => {
    setSearchQuery(text);
    searchQueryRef.current = text;
  };

  const onSearchSubmit = () => {
    fetchProducts();
  };

  const clearSearch = () => {
    setSearchQuery('');
    searchQueryRef.current = '';
    fetchProducts('');
  };

  const handleTagPress = (tag: string) => {
    setSearchQuery(tag);
    searchQueryRef.current = tag;
    fetchProducts(tag);
  };

  const handleRefresh = useCallback(() => {
    fetchProducts(undefined, true);
  }, [fetchProducts]);

  const listEmptyComponent = useMemo(() => {
    if (loading) return null;
    return (
      <View style={styles.centerContainer}>
        <Text style={{ color: '#666' }}>Nenhum produto encontrado para a busca atual.</Text>
      </View>
    );
  }, [loading]);

  const handleProductPress = useCallback((item: Product) => {
    setSelectedProduct(item);
    setModalVisible(true);
  }, []);

  return (
    <SafeAreaProvider>
      <PaperProvider theme={theme}>
        <SafeAreaView style={styles.safeAreaWrapper} edges={['top', 'left', 'right']}>
          <StatusBar barStyle="light-content" backgroundColor="#E5293E" />
          
          <View style={styles.header}>
            <View style={styles.headerTop}>
              <TouchableOpacity onPress={clearSearch}>
                <Text style={styles.headerTitle}>Comparador Jundiaí</Text>
              </TouchableOpacity>
              <View>
                <IconButton
                  icon="cart-outline"
                  iconColor="#fff"
                  size={26}
                  onPress={() => setCartVisible(true)}
                />
                {cartItemsCount > 0 && (
                  <View style={styles.badge}>
                    <Text style={styles.badgeText}>{cartItemsCount}</Text>
                  </View>
                )}
              </View>
            </View>
            <View style={{ flexDirection: 'row', alignItems: 'center' }}>
              <Searchbar
                placeholder="Ex: Cerveja Heineken, Fralda..."
                onChangeText={handleSearchChange}
                value={searchQuery}
                onSubmitEditing={onSearchSubmit}
                onIconPress={onSearchSubmit}
                onClearIconPress={clearSearch}
                style={[styles.searchbar, { flex: 1 }]}
                inputStyle={styles.searchInput}
                iconColor="#E5293E"
              />
              <IconButton
                icon="barcode-scan"
                iconColor="#fff"
                size={28}
                onPress={() => {
                  if (!permission?.granted) requestPermission();
                  setIsScanning(true);
                }}
                style={{ marginLeft: 8, marginRight: 0 }}
              />
            </View>

            <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.tagsContainer} contentContainerStyle={{ paddingRight: 20 }}>
              {['cerveja', 'café', 'fralda', 'sabão em pó', 'arroz', 'leite'].map(tag => (
                <Chip 
                  key={tag} 
                  style={styles.tagChip} 
                  textStyle={styles.tagText}
                  onPress={() => handleTagPress(tag)}
                  compact
                >
                  #{tag}
                </Chip>
              ))}
            </ScrollView>

            <View style={styles.filtersRow}>
              <Chip 
                icon={sortBy === 'discount' ? "percent" : "currency-usd"} 
                onPress={() => setSortBy(prev => prev === 'discount' ? 'price' : 'discount')}
                style={styles.filterChip}
              >
                {sortBy === 'discount' ? 'Maiores Descontos' : 'Menores Preços'}
              </Chip>
              <Chip 
                icon="store" 
                onPress={() => setMarketModalVisible(true)}
                style={styles.filterChip}
              >
                {selectedMarket === 'Todos os Mercados' ? 'Mercados' : selectedMarket}
              </Chip>
            </View>
          </View>

          <View style={styles.mainContent}>
            {loading && products.length === 0 ? (
              <ScrollView contentContainerStyle={styles.skeletonContainer} showsVerticalScrollIndicator={false}>
                {[1, 2, 3, 4, 5, 6].map((key) => (
                  <SkeletonCard key={key} />
                ))}
              </ScrollView>
            ) : error ? (
              <View style={styles.centerContainer}>
                <Text style={styles.errorText}>{error}</Text>
              </View>
            ) : (
              <ProductList
                products={products}
                refreshing={refreshing}
                onRefresh={handleRefresh}
                onProductPress={handleProductPress}
                ListEmptyComponent={listEmptyComponent}
              />
            )}
          </View>

          <ProductDetailsModal
            visible={isModalVisible}
            onDismiss={() => setModalVisible(false)}
            product={selectedProduct}
            apiUrl={API_URL}
          />

          <ShoppingListModal 
            visible={isCartVisible}
            onDismiss={() => setCartVisible(false)}
          />

          <Modal visible={isMarketModalVisible} animationType="slide" transparent={true}>
            <View style={styles.modalOverlay}>
              <View style={styles.modalContent}>
                <View style={styles.modalHeader}>
                  <Text style={styles.modalTitle}>Filtrar por Mercado</Text>
                  <IconButton icon="close" onPress={() => setMarketModalVisible(false)} />
                </View>
                <ScrollView>
                  {MARKETS.map(market => (
                    <TouchableOpacity 
                      key={market} 
                      style={[styles.marketOption, selectedMarket === market && styles.marketOptionSelected]}
                      onPress={() => {
                        setSelectedMarket(market);
                        setMarketModalVisible(false);
                      }}
                    >
                      <Text style={[styles.marketOptionText, selectedMarket === market && styles.marketOptionTextSelected]}>
                        {market}
                      </Text>
                    </TouchableOpacity>
                  ))}
                </ScrollView>
              </View>
            </View>
          </Modal>

          {/* --- MODAL DA CÂMERA DE LEITURA DE EAN --- */}
          <Modal visible={isScanning} animationType="slide" transparent={false} onRequestClose={() => setIsScanning(false)}>
            <SafeAreaView style={{ flex: 1, backgroundColor: 'black' }} edges={['top', 'bottom']}>
              <View style={styles.scannerHeader}>
                <Text style={styles.scannerTitle}>Escanear Código de Barras</Text>
                <IconButton icon="close" iconColor="white" size={24} onPress={() => setIsScanning(false)} />
              </View>
              {permission?.granted ? (
                <View style={styles.scannerContainer}>
                  <CameraView
                    style={StyleSheet.absoluteFillObject}
                    facing="back"
                    barcodeScannerSettings={{ barcodeTypes: ["ean13", "ean8", "upc_a", "upc_e"] }}
                    onBarcodeScanned={({ data }) => {
                      setIsScanning(false);
                      setSearchQuery(data);
                      searchQueryRef.current = data;
                      fetchProducts(data);
                    }}
                  />
                  <View style={styles.scannerOverlay}>
                    <View style={styles.scannerTarget} />
                  </View>
                </View>
              ) : (
                <View style={styles.centerContainer}>
                  <Text style={{ color: 'white', marginBottom: 20 }}>Precisamos de acesso à câmera.</Text>
                  <Button mode="contained" onPress={requestPermission} buttonColor="#E5293E">Conceder Permissão</Button>
                </View>
              )}
            </SafeAreaView>
          </Modal>

        </SafeAreaView>
      </PaperProvider>
    </SafeAreaProvider>
  );
}

const styles = StyleSheet.create({
  safeAreaWrapper: {
    flex: 1,
    backgroundColor: '#E5293E',
  },
  mainContent: {
    flex: 1,
    backgroundColor: '#f5f5f5',
  },
  header: {
    backgroundColor: '#E5293E',
    paddingHorizontal: 16,
    paddingTop: Platform.OS === 'ios' ? 4 : 12,
    paddingBottom: 16,
    borderBottomLeftRadius: 16,
    borderBottomRightRadius: 16,
    elevation: 4,
    zIndex: 10,
  },
  headerTop: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
  },
  headerTitle: {
    color: '#fff',
    fontSize: 22,
    fontWeight: 'bold',
  },
  badge: {
    position: 'absolute',
    top: 4,
    right: 4,
    backgroundColor: '#FFD700', // Amarelo destaque
    borderRadius: 10,
    width: 20,
    height: 20,
    justifyContent: 'center',
    alignItems: 'center',
    borderWidth: 2,
    borderColor: '#E5293E',
  },
  badgeText: {
    color: '#E5293E',
    fontSize: 10,
    fontWeight: 'bold',
  },
  searchbar: {
    elevation: 0,
    borderRadius: 12,
    backgroundColor: '#fff',
    height: 48,
  },
  searchInput: {
    fontSize: 15,
  },
  tagsContainer: {
    marginTop: 12,
    flexDirection: 'row',
  },
  tagChip: {
    marginRight: 8,
    backgroundColor: 'rgba(255,255,255,0.2)',
    height: 32,
  },
  tagText: {
    color: '#fff',
    fontWeight: 'bold',
    fontSize: 12,
  },
  filtersRow: {
    flexDirection: 'row',
    marginTop: 12,
  },
  filterChip: {
    marginRight: 8,
    backgroundColor: '#fff',
  },
  centerContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: 20,
  },
  loadingText: {
    marginTop: 16, 
    color: '#666',
    fontWeight: '500',
  },
  errorText: {
    color: '#d32f2f',
    textAlign: 'center',
    fontSize: 16,
  },
  skeletonContainer: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    justifyContent: 'space-between',
    padding: 6,
  },
  modalOverlay: {
    flex: 1,
    justifyContent: 'flex-end',
    backgroundColor: 'rgba(0,0,0,0.5)'
  },
  modalContent: {
    backgroundColor: '#fff',
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
    maxHeight: '70%',
    paddingBottom: 20,
  },
  modalHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 20,
    paddingTop: 10,
    borderBottomWidth: 1,
    borderBottomColor: '#eee',
  },
  modalTitle: {
    fontSize: 18,
    fontWeight: 'bold',
  },
  marketOption: {
    paddingVertical: 16,
    paddingHorizontal: 20,
    borderBottomWidth: 1,
    borderBottomColor: '#f5f5f5',
  },
  marketOptionSelected: {
    backgroundColor: '#fff0f2',
  },
  marketOptionText: {
    fontSize: 16,
    color: '#444',
  },
  marketOptionTextSelected: {
    color: '#E5293E',
    fontWeight: 'bold',
  },
  // Estilos do Scanner
  scannerHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingHorizontal: 16, paddingVertical: 8, backgroundColor: 'black' },
  scannerTitle: { color: 'white', fontSize: 18, fontWeight: 'bold' },
  scannerContainer: { flex: 1, position: 'relative' },
  scannerOverlay: { flex: 1, justifyContent: 'center', alignItems: 'center', backgroundColor: 'rgba(0,0,0,0.5)' },
  scannerTarget: { width: 250, height: 150, borderWidth: 2, borderColor: '#E5293E', borderRadius: 12, backgroundColor: 'transparent' },
});