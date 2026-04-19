import React, { useState, useEffect } from 'react';
import { View, StyleSheet, ActivityIndicator, StatusBar, TouchableOpacity, FlatList } from 'react-native';
import { Provider as PaperProvider, DefaultTheme, Searchbar, Text } from 'react-native-paper';
import { SafeAreaProvider, SafeAreaView } from 'react-native-safe-area-context';
import axios from 'axios';
import { ProductList } from './components/ProductList';
import { Product } from './types';

// --- CONFIGURAÇÃO DE AMBIENTE ---
// Para usar localmente na mesma rede Wi-Fi:
// const API_URL = 'http://192.168.18.77:8000'; 

// --- PARA USAR FORA DA REDE (NGROK) ---
// 1. Rode o ngrok no seu PC (ngrok http 8000)
// 2. Copie o endereço https que ele gerar e COLE AQUI ABAIXO:
const API_URL = 'https://badness-impale-suitably.ngrok-free.dev';

const theme = {
  ...DefaultTheme,
  colors: {
    ...DefaultTheme.colors,
    primary: '#E5293E', // Vermelho vibrante estilo app comercial
    accent: '#ff4d5a',
  },
};

export default function App() {
  const [searchQuery, setSearchQuery] = useState('');
  const [products, setProducts] = useState<Product[]>([]);
  const [allProducts, setAllProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const categories = ['Todos', 'Higiene e Perfumaria', 'Limpeza', 'Bebidas', 'Laticínios, Ovos e Frios', 'Açougue e Peixaria', 'Mercearia', 'Congelados e Pratos Prontos', 'Bazar e Utilidades'];
  const [selectedCategory, setSelectedCategory] = useState('Todos');

  const filterProducts = (data: Product[], category: string) => {
    if (category === 'Todos') {
      setProducts(data);
    } else {
      setProducts(data.filter(p => p.Categoria && p.Categoria.toLowerCase().includes(category.toLowerCase())));
    }
  };

  const fetchProducts = async (query = '') => {
    setLoading(true);
    setError(null);
    try {
      const response = await axios.get<Product[]>(`${API_URL}/produtos`, {
        params: query ? { q: query } : {}
      });
      setAllProducts(response.data);
      filterProducts(response.data, selectedCategory);
    } catch (err) {
      console.error(err);
      setError('Não foi possível carregar os produtos.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchProducts();
  }, []);

  const onChangeSearch = (query: string) => setSearchQuery(query);

  const onSearchSubmit = () => {
    fetchProducts(searchQuery);
  };

  const onCategoryPress = (category: string) => {
    setSelectedCategory(category);
    filterProducts(allProducts, category);
  };

  return (
    <SafeAreaProvider>
      <PaperProvider theme={theme}>
        <SafeAreaView style={styles.container} edges={['top', 'left', 'right']}>
          <StatusBar barStyle="light-content" backgroundColor="#E5293E" />
          
          {/* Header Premium Customizado */}
          <View style={styles.header}>
            <View style={styles.headerTop}>
              <Text style={styles.headerTitle}>Ofertas de Hoje</Text>
            </View>
            <Searchbar
              placeholder="Buscar no supermercado..."
              onChangeText={onChangeSearch}
              value={searchQuery}
              onSubmitEditing={onSearchSubmit}
              onIconPress={onSearchSubmit}
              style={styles.searchbar}
              inputStyle={styles.searchInput}
              iconColor="#E5293E"
              traileringIcon="barcode-scan"
              traileringIconColor="#999"
              onTraileringIconPress={() => {}}
            />
          </View>

          {/* Barra de Categorias Horizontal */}
          <View style={styles.categoryContainer}>
            <FlatList
              horizontal
              showsHorizontalScrollIndicator={false}
              data={categories}
              keyExtractor={(item) => item}
              renderItem={({ item }) => (
                <TouchableOpacity
                  style={[
                    styles.categoryButton,
                    selectedCategory === item && styles.categoryButtonSelected
                  ]}
                  onPress={() => onCategoryPress(item)}
                >
                  <Text
                    style={[
                      styles.categoryText,
                      selectedCategory === item && styles.categoryTextSelected
                    ]}
                  >
                    {item}
                  </Text>
                </TouchableOpacity>
              )}
              contentContainerStyle={styles.categoryList}
            />
          </View>

          {loading && products.length === 0 ? (
            <View style={styles.centerContainer}>
              <ActivityIndicator size="large" color="#E5293E" />
              <Text style={styles.loadingText}>Buscando os melhores preços...</Text>
            </View>
          ) : error ? (
            <View style={styles.centerContainer}>
              <Text style={styles.errorText}>{error}</Text>
            </View>
          ) : (
            <ProductList
              products={products}
              refreshing={loading}
              onRefresh={() => fetchProducts(searchQuery)}
              ListEmptyComponent={
                !loading ? (
                  <View style={styles.centerContainer}>
                    <Text style={{ color: '#666' }}>Nenhum produto encontrado.</Text>
                  </View>
                ) : null
              }
            />
          )}
        </SafeAreaView>
      </PaperProvider>
    </SafeAreaProvider>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#f5f5f5', // Fundo cinza claro
  },
  header: {
    backgroundColor: '#E5293E', // Vermelho Premium
    paddingHorizontal: 16,
    paddingTop: 12,
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
  searchbar: {
    elevation: 0,
    borderRadius: 12,
    backgroundColor: '#fff',
    height: 48,
  },
  searchInput: {
    fontSize: 15,
  },
  categoryContainer: {
    backgroundColor: '#f5f5f5',
    paddingVertical: 10,
  },
  categoryList: {
    paddingHorizontal: 12,
  },
  categoryButton: {
    paddingHorizontal: 18,
    paddingVertical: 8,
    borderRadius: 20,
    backgroundColor: '#e0e0e0',
    marginHorizontal: 4,
    elevation: 1,
  },
  categoryButtonSelected: {
    backgroundColor: '#E5293E',
  },
  categoryText: {
    fontSize: 14,
    color: '#555',
    fontWeight: '600',
  },
  categoryTextSelected: {
    color: '#fff',
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
});
