import React, { useState, useEffect } from 'react';
import { View, StyleSheet, ActivityIndicator, StatusBar, TouchableOpacity, ScrollView, Modal } from 'react-native';
import { Provider as PaperProvider, DefaultTheme, Searchbar, Text, Chip, IconButton } from 'react-native-paper';
import { SafeAreaProvider, SafeAreaView } from 'react-native-safe-area-context';
import axios from 'axios';
import { ProductList } from './components/ProductList';
import { ProductDetailsModal } from './components/ProductDetailsModal';
import { Product } from './types';

// --- CONFIGURAÇÃO DE AMBIENTE ---
const API_URL = ' https://badness-impale-suitably.ngrok-free.dev';

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
  
  const [products, setProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  const [selectedProduct, setSelectedProduct] = useState<Product | null>(null);
  const [isModalVisible, setModalVisible] = useState(false);

  // Filtros Globais
  const [sortBy, setSortBy] = useState<'discount' | 'price'>('discount');
  const [selectedMarket, setSelectedMarket] = useState('Todos os Mercados');
  const [isMarketModalVisible, setMarketModalVisible] = useState(false);

  const fetchProducts = async (queryOverride?: string) => {
    setLoading(true);
    setError(null);
    try {
      const currentQuery = queryOverride !== undefined ? queryOverride : searchQuery;
      const params: any = { q: currentQuery, sort_by: sortBy };
      if (selectedMarket !== 'Todos os Mercados') {
        params.market = selectedMarket;
      }
      
      const response = await axios.get<Product[]>(`${API_URL}/produtos`, {
        params,
        headers: { 'ngrok-skip-browser-warning': 'true' }
      });
      setProducts(response.data);
    } catch (err) {
      console.error(err);
      setError('Não foi possível carregar os produtos.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchProducts();
  }, [sortBy, selectedMarket]);

  const onSearchSubmit = () => {
    fetchProducts();
  };

  const clearSearch = () => {
    setSearchQuery('');
    fetchProducts('');
  };

  const handleTagPress = (tag: string) => {
    setSearchQuery(tag);
    fetchProducts(tag);
  };

  return (
    <SafeAreaProvider>
      <PaperProvider theme={theme}>
        <SafeAreaView style={styles.container} edges={['top', 'left', 'right']}>
          <StatusBar barStyle="light-content" backgroundColor="#E5293E" />
          
          <View style={styles.header}>
            <View style={styles.headerTop}>
              <TouchableOpacity onPress={clearSearch}>
                <Text style={styles.headerTitle}>Comparador Jundiaí</Text>
              </TouchableOpacity>
            </View>
            <Searchbar
              placeholder="Ex: Cerveja Heineken, Fralda..."
              onChangeText={setSearchQuery}
              value={searchQuery}
              onSubmitEditing={onSearchSubmit}
              onIconPress={onSearchSubmit}
              onClearIconPress={clearSearch}
              style={styles.searchbar}
              inputStyle={styles.searchInput}
              iconColor="#E5293E"
            />

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

          {loading && products.length === 0 ? (
            <View style={styles.centerContainer}>
              <ActivityIndicator size="large" color="#E5293E" />
              <Text style={styles.loadingText}>Buscando produtos...</Text>
            </View>
          ) : error ? (
            <View style={styles.centerContainer}>
              <Text style={styles.errorText}>{error}</Text>
            </View>
          ) : (
            <ProductList
              products={products}
              refreshing={loading}
              onRefresh={() => fetchProducts()}
              onProductPress={(item) => { setSelectedProduct(item); setModalVisible(true); }}
              ListEmptyComponent={
                !loading ? (
                  <View style={styles.centerContainer}>
                    <Text style={{ color: '#666' }}>Nenhum produto encontrado para a busca atual.</Text>
                  </View>
                ) : null
              }
            />
          )}

          <ProductDetailsModal
            visible={isModalVisible}
            onDismiss={() => setModalVisible(false)}
            product={selectedProduct}
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

        </SafeAreaView>
      </PaperProvider>
    </SafeAreaProvider>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#f5f5f5',
  },
  header: {
    backgroundColor: '#E5293E',
    paddingHorizontal: 16,
    paddingTop: 12,
    paddingBottom: 12,
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
  }
});