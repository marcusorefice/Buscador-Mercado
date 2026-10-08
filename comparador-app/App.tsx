import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { View, StyleSheet, ActivityIndicator, StatusBar, TouchableOpacity, ScrollView, Modal, Platform, Alert, Image, Keyboard } from 'react-native';
import { Provider as PaperProvider, DefaultTheme, Searchbar, Text, Chip, IconButton, Button, TextInput } from 'react-native-paper';
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
import * as ImagePicker from 'expo-image-picker';
import Constants from 'expo-constants';

// --- CONFIGURAÇÃO DE AMBIENTE ---
const API_URL = __DEV__ 
  ? 'https://badness-impale-suitably.ngrok-free.dev' // ngrok: Ignora o Firewall do Windows e atualiza na hora!
  : 'https://buscador-mercado.onrender.com';         // Render: App Oficial da Nuvem

// As sugestões da busca (Typesense) vêm pela API em /autocompletar: o Android bloqueia HTTP sem
// criptografia nos APKs, então o app não fala direto com o servidor do Typesense.

// Quantos produtos vêm por vez; o resto carrega conforme a pessoa rola a lista
const TAMANHO_PAGINA = 40;

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

type Ordenacao = 'relevance' | 'discount' | 'price';

// O botão de ordenação alterna entre as três, nessa ordem
const ORDENACOES: Record<Ordenacao, { titulo: string; icone: string; proxima: Ordenacao }> = {
  relevance: { titulo: 'Em Alta', icone: 'fire', proxima: 'discount' },
  discount: { titulo: 'Maiores Descontos', icone: 'percent', proxima: 'price' },
  price: { titulo: 'Menores Preços', icone: 'currency-usd', proxima: 'relevance' },
};

const TAGS_PADRAO = ['coca-cola', 'heineken', 'azeite', 'óleo', 'leite', 'café', 'papel higiênico', 'sabão em pó'];

// Chips da tela inicial: o que a pessoa mais busca, depois o que todos mais buscam, depois o padrão
const montarTags = (historico: Record<string, number>, populares: string[]): string[] => {
  const pessoais = Object.entries(historico).sort((a, b) => b[1] - a[1]).map(e => String(e[0]));
  return Array.from(new Set([...pessoais.slice(0, 4), ...populares, ...pessoais, ...TAGS_PADRAO])).slice(0, 8);
};

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
  const [isSidebarVisible, setSidebarVisible] = useState(false);
  const [isSuggestionModalVisible, setSuggestionModalVisible] = useState(false);
  const [suggestionText, setSuggestionText] = useState('');
  const [suggestionImage, setSuggestionImage] = useState<string | null>(null);
  const [suggestionImageBase64, setSuggestionImageBase64] = useState<string | null>(null);
  const [isSendingSuggestion, setIsSendingSuggestion] = useState(false);
  const [dynamicTags, setDynamicTags] = useState<string[]>(['coca-cola', 'heineken', 'azeite', 'óleo', 'leite', 'café', 'papel higiênico', 'sabão em pó']);
  const searchTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const productsRef = useRef<Product[]>([]);
  const temMaisRef = useRef(false);
  const carregandoMaisRef = useRef(false);
  const queryCarregadaRef = useRef('');
  const sugestoesCacheRef = useRef<Map<string, string[]>>(new Map());
  const autocompleteTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  
  const [isSearchFocused, setIsSearchFocused] = useState(false);
  const [textSuggestions, setTextSuggestions] = useState<string[]>([]);
  
  const [isScanning, setIsScanning] = useState(false);
  const [permission, requestPermission] = useCameraPermissions();

  // Lendo a quantidade de itens na lista usando Zustand
  const cartItemsCount = useShoppingListStore(state => state.list.length);

  // Filtros Globais
  const [sortBy, setSortBy] = useState<Ordenacao>('relevance');
  // Termos mais buscados por todos os usuários (vêm da API) para os chips da tela inicial
  const buscasPopularesRef = useRef<string[]>([]);
  const ultimoPedidoProdutosRef = useRef(0);
  const [selectedMarket, setSelectedMarket] = useState('Todos os Mercados');
  const [isMarketModalVisible, setMarketModalVisible] = useState(false);

  productsRef.current = products;

  const fetchProducts = useCallback(async (queryOverride?: string, isRefresh = false) => {
    // Enquanto a pessoa digita saem várias buscas; só a última pode mexer na tela
    const pedido = ++ultimoPedidoProdutosRef.current;
    const pedidoAtual = () => pedido === ultimoPedidoProdutosRef.current;
    if (isRefresh) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }
    setError(null);
    try {
      const currentQuery = queryOverride !== undefined ? queryOverride : searchQueryRef.current;
      const params: any = { q: currentQuery, sort_by: sortBy, limite: TAMANHO_PAGINA };
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
      
      if (!pedidoAtual()) return;

      // --- O SCANNER MÁGICO (TRADUTOR DE CÓDIGO DE BARRAS) ---
      // Se a pessoa escaneou o EAN e não achou no nosso banco (pode estar salvo como INT_)
      if (response.data.length === 0 && /^\d{8,14}$/.test(currentQuery)) {
        try {
          const offRes = await axios.get(`https://br.openfoodfacts.org/api/v0/product/${currentQuery}.json`);
          if (offRes.data && offRes.data.status === 1) {
            const translatedName = offRes.data.product.product_name;
            const translatedBrand = offRes.data.product.brands || '';
            if (translatedName) {
              const fallbackQuery = `${translatedName} ${translatedBrand}`.trim();
              const fallbackRes = await axios.get<Product[]>(`${API_URL}/produtos`, {
                params: { q: fallbackQuery, sort_by: sortBy, limite: TAMANHO_PAGINA, ...(selectedMarket !== 'Todos os Mercados' && { market: selectedMarket }) },
                headers: { 'ngrok-skip-browser-warning': 'true', 'Bypass-Tunnel-Reminder': 'true' }
              });
              if (fallbackRes.data.length > 0 && pedidoAtual()) {
                setProducts(fallbackRes.data);
                temMaisRef.current = false;
                setLoading(false);
                setRefreshing(false);
                return;
              }
            }
          }
        } catch (e) {
          // Silencia erros externos e segue para mostrar a tela de vazio
        }
      }

      setProducts(response.data);
      temMaisRef.current = response.data.length >= TAMANHO_PAGINA;
      queryCarregadaRef.current = currentQuery;

      // Otimização Extrema (Offline-first): Salva em cache se for a busca inicial padrão
      if (!currentQuery && selectedMarket === 'Todos os Mercados' && sortBy === 'relevance') {
        AsyncStorage.setItem('@cached_home_products', JSON.stringify(response.data)).catch(() => {});
      }
    } catch (err) {
      console.error(err);
      if (pedidoAtual()) setError('Não foi possível carregar os produtos.');
    } finally {
      if (pedidoAtual()) {
        setLoading(false);
        setRefreshing(false);
      }
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
        
        // Carrega o histórico de pesquisas para as tags dinâmicas
        const history = await AsyncStorage.getItem('@search_history');
        if (history) {
          const parsed = JSON.parse(history);
          setDynamicTags(montarTags(parsed, buscasPopularesRef.current));
        }

        // Mais buscados por todos os usuários
        const resposta = await axios.get<{ termos: string[] }>(`${API_URL}/buscas-populares`, {
          headers: { 'ngrok-skip-browser-warning': 'true' }, timeout: 5000,
        });
        buscasPopularesRef.current = resposta.data.termos || [];
        const historico = await AsyncStorage.getItem('@search_history');
        setDynamicTags(montarTags(historico ? JSON.parse(historico) : {}, buscasPopularesRef.current));
      } catch (e) {}
    };
    loadCache();
  }, []);

  useEffect(() => {
    fetchProducts();
  }, [fetchProducts]);

  // Cancela a busca anterior se o usuário continuar digitando e busca sozinho após uma pausa curta
  const agendarBusca = (text: string) => {
    if (searchTimeoutRef.current) {
      clearTimeout(searchTimeoutRef.current);
    }
    searchTimeoutRef.current = setTimeout(() => {
      fetchProducts(text);
    }, 300);
  };

  const carregarMais = async () => {
    if (!temMaisRef.current || carregandoMaisRef.current || loading) return;
    const pedido = ultimoPedidoProdutosRef.current;
    const consulta = queryCarregadaRef.current;
    carregandoMaisRef.current = true;
    try {
      const params: any = { q: consulta, sort_by: sortBy, limite: TAMANHO_PAGINA, offset: productsRef.current.length };
      if (selectedMarket !== 'Todos os Mercados') params.market = selectedMarket;
      const response = await axios.get<Product[]>(`${API_URL}/produtos`, {
        params,
        headers: { 'ngrok-skip-browser-warning': 'true' },
      });
      // Se começou outra busca enquanto isso, esta página não vale mais
      if (pedido !== ultimoPedidoProdutosRef.current) return;
      temMaisRef.current = response.data.length >= TAMANHO_PAGINA;
      setProducts(atuais => {
        const jaTem = new Set(atuais.map(p => p.EAN));
        return [...atuais, ...response.data.filter(p => !jaTem.has(p.EAN))];
      });
    } catch (e) {
      // Falhou: deixa tentar de novo na próxima rolagem
    } finally {
      carregandoMaisRef.current = false;
    }
  };

  const handleSearchChange = (text: string) => {
    setSearchQuery(text);
    searchQueryRef.current = text;
    setIsSearchFocused(true);
    
    if (autocompleteTimeoutRef.current) clearTimeout(autocompleteTimeoutRef.current);

    // Sugestões instantâneas (Typesense, via API)
    if (text.length > 0) {
      const chave = text.trim().toLowerCase();
      const guardadas = sugestoesCacheRef.current.get(chave);
      if (guardadas) {
        setTextSuggestions(guardadas);
        return agendarBusca(text);
      }
      autocompleteTimeoutRef.current = setTimeout(async () => {
        try {
          const response = await axios.get<{ sugestoes: string[] }>(`${API_URL}/autocompletar`, {
            params: { q: text },
            headers: { 'ngrok-skip-browser-warning': 'true' },
            timeout: 5000,
          });
          // Ignora a resposta se a pessoa já mudou o texto enquanto ela chegava
          sugestoesCacheRef.current.set(chave, response.data.sugestoes || []);
          if (searchQueryRef.current === text) {
            setTextSuggestions(response.data.sugestoes || []);
          }
        } catch (e) {
          console.error("Falha no autocomplete:", e);
        }
      }, 120); // espera a pessoa parar de digitar por 120ms
    } else {
      setTextSuggestions([]);
    }

    agendarBusca(text);
  };

  const saveSearchToHistory = async (query: string) => {
    if (!query || query.trim().length < 3) return;
    const q = query.trim().toLowerCase();
    try {
      const history = await AsyncStorage.getItem('@search_history');
      let parsed: Record<string, number> = history ? JSON.parse(history) : {};
      parsed[q] = (parsed[q] || 0) + 1;
      await AsyncStorage.setItem('@search_history', JSON.stringify(parsed));
      
      setDynamicTags(montarTags(parsed, buscasPopularesRef.current));
    } catch (e) {}
  };

  const onSearchSubmit = () => {
    if (searchTimeoutRef.current) {
      clearTimeout(searchTimeoutRef.current);
    }
    saveSearchToHistory(searchQueryRef.current);
    fetchProducts();
  };

  const handleTextSuggestionPress = (suggestion: string) => {
    setSearchQuery(suggestion);
    searchQueryRef.current = suggestion;
    setIsSearchFocused(false);
    setTextSuggestions([]);
    Keyboard.dismiss();
    if (searchTimeoutRef.current) clearTimeout(searchTimeoutRef.current);
    fetchProducts(suggestion);
    saveSearchToHistory(suggestion);
  };

  const clearSearchText = () => {
    setSearchQuery('');
    searchQueryRef.current = '';
    setTextSuggestions([]);
    setIsSearchFocused(true);
    if (searchTimeoutRef.current) clearTimeout(searchTimeoutRef.current);
  };

  const returnHome = () => {
    setSearchQuery('');
    searchQueryRef.current = '';
    setTextSuggestions([]);
    setIsSearchFocused(false);
    if (searchTimeoutRef.current) clearTimeout(searchTimeoutRef.current);
    fetchProducts('');
  };

  const handleTagPress = (tag: string) => {
    setSearchQuery(tag);
    searchQueryRef.current = tag;
    saveSearchToHistory(tag);
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

  const handlePickImage = async () => {
    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ['images'],
      quality: 0.7,
      base64: true,
    });
    if (!result.canceled) {
      setSuggestionImage(result.assets[0].uri);
      setSuggestionImageBase64(result.assets[0].base64 ?? null);
    }
  };

  const handleSendSuggestion = async () => {
    if (!suggestionText.trim()) return;
    setIsSendingSuggestion(true);
    try {
      // A sugestão vai para a nossa API, que repassa ao Discord.
      // A URL do webhook fica só no servidor (qualquer um consegue extrair o que está dentro do APK).
      const response = await fetch(`${API_URL}/sugestoes`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'ngrok-skip-browser-warning': 'true' },
        body: JSON.stringify({
          texto: suggestionText,
          imagem_base64: suggestionImage ? suggestionImageBase64 : null,
          imagem_nome: suggestionImage ? (suggestionImage.split('/').pop() || 'print.jpg') : null,
        }),
      });
      
      if (response.ok || response.status === 204) {
        Alert.alert('Sucesso!', 'Sua sugestão foi enviada. Obrigado por ajudar a melhorar o app!');
        setSuggestionModalVisible(false);
        setSuggestionText('');
        setSuggestionImage(null);
        setSuggestionImageBase64(null);
      } else {
        throw new Error('Falha no envio');
      }
    } catch (error) {
      Alert.alert('Erro', 'Não foi possível enviar a sugestão. Verifique sua conexão e tente novamente.');
    } finally {
      setIsSendingSuggestion(false);
    }
  };

  return (
    <SafeAreaProvider>
      <PaperProvider theme={theme}>
        <SafeAreaView style={styles.safeAreaWrapper} edges={['top', 'left', 'right']}>
          <StatusBar barStyle="light-content" backgroundColor="#E5293E" />
          
          <View style={styles.header}>
            <View style={styles.headerTop}>
              <View style={{ flexDirection: 'row', alignItems: 'center' }}>
                <IconButton icon="menu" iconColor="#fff" size={28} onPress={() => setSidebarVisible(true)} style={{ marginLeft: -8, marginRight: 0 }} />
                <TouchableOpacity onPress={returnHome}>
                  <Text style={styles.headerTitle}>Comparador</Text>
                </TouchableOpacity>
              </View>
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
            <View style={{ flexDirection: 'row', alignItems: 'center', zIndex: 20 }}>
              <View style={{ flex: 1, position: 'relative' }}>
                <Searchbar
                  placeholder="Ex: Cerveja Heineken, Fralda..."
                  onChangeText={handleSearchChange}
                  value={searchQuery}
                  onSubmitEditing={onSearchSubmit}
                  onIconPress={onSearchSubmit}
                  onClearIconPress={clearSearchText}
                  onFocus={() => setIsSearchFocused(true)}
                  onBlur={() => setTimeout(() => setIsSearchFocused(false), 200)}
                  style={styles.searchbar}
                  inputStyle={styles.searchInput}
                  iconColor="#E5293E"
                />
              </View>
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
              {dynamicTags.map(tag => (
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
                icon={ORDENACOES[sortBy].icone}
                onPress={() => setSortBy(prev => ORDENACOES[prev].proxima)}
                style={styles.filterChip}
              >
                {ORDENACOES[sortBy].titulo}
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
                onEndReached={carregarMais}
                onProductPress={handleProductPress}
                ListEmptyComponent={listEmptyComponent}
              />
            )}
          </View>

          {/* Overlay de Autocomplete Movido para a Raiz (Resolve o bug de rolagem no Android) */}
          {isSearchFocused && textSuggestions.length > 0 && (
            <View style={[styles.autocompleteOverlay, { top: Platform.OS === 'ios' ? 110 : 118, left: 16, right: 68 }]}>
              <ScrollView keyboardShouldPersistTaps="handled" nestedScrollEnabled={true}>
                {textSuggestions.map(s => (
                  <TouchableOpacity key={s} style={styles.autocompleteItem} onPress={() => handleTextSuggestionPress(s)}>
                    <IconButton icon="magnify" size={16} iconColor="#888" style={{ margin: 0, marginRight: 8 }} />
                    <Text style={styles.autocompleteText}>{s}</Text>
                  </TouchableOpacity>
                ))}
              </ScrollView>
            </View>
          )}

          <ProductDetailsModal
            visible={isModalVisible}
            onDismiss={() => setModalVisible(false)}
            product={selectedProduct}
            apiUrl={API_URL}
          />

          <ShoppingListModal 
            visible={isCartVisible}
            onDismiss={() => setCartVisible(false)}
            allProducts={products}
            onProductPress={handleProductPress}
            apiUrl={API_URL}
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
          
          {/* --- MENU LATERAL (SIDEBAR) --- */}
          <Modal visible={isSidebarVisible} animationType="fade" transparent={true} onRequestClose={() => setSidebarVisible(false)}>
            <View style={styles.sidebarOverlay}>
              <View style={styles.sidebarContent}>
                <View style={styles.sidebarHeader}>
                  <Text style={styles.sidebarTitle}>Comparador Jundiaí</Text>
                </View>
                <ScrollView style={{ flex: 1, paddingTop: 10 }}>
                  <TouchableOpacity 
                    style={styles.sidebarItem} 
                    onPress={() => {
                      setSidebarVisible(false);
                      setSuggestionModalVisible(true);
                    }}
                  >
                    <IconButton icon="lightbulb-on-outline" size={24} iconColor="#555" style={{ margin: 0, marginRight: 10 }} />
                    <Text style={styles.sidebarItemText}>Enviar Sugestão</Text>
                  </TouchableOpacity>
                  <TouchableOpacity style={styles.sidebarItem} onPress={() => setSidebarVisible(false)}>
                    <IconButton icon="cog-outline" size={24} iconColor="#555" style={{ margin: 0, marginRight: 10 }} />
                    <Text style={styles.sidebarItemText}>Configurações</Text>
                  </TouchableOpacity>
                </ScrollView>
                <View style={styles.sidebarFooter}>
                  <Text style={styles.versionText}>Versão {Constants.expoConfig?.version || '1.0.0'}</Text>
                </View>
              </View>
              <TouchableOpacity style={styles.sidebarCloseArea} activeOpacity={1} onPress={() => setSidebarVisible(false)} />
            </View>
          </Modal>

          {/* --- MODAL DE SUGESTÕES (IN-APP) --- */}
          <Modal visible={isSuggestionModalVisible} animationType="slide" transparent={true} onRequestClose={() => setSuggestionModalVisible(false)}>
            <View style={styles.modalOverlay}>
              <View style={styles.modalContent}>
                <View style={styles.modalHeader}>
                  <Text style={styles.modalTitle}>💡 Enviar Sugestão</Text>
                  <IconButton icon="close" onPress={() => setSuggestionModalVisible(false)} />
                </View>
                <View style={{ padding: 20 }}>
                  <Text style={{ marginBottom: 15, color: '#555', fontSize: 15, lineHeight: 22 }}>
                    Encontrou algum erro ou tem uma ideia? Envie direto por aqui!
                  </Text>
                  <TextInput
                    mode="outlined"
                    label="Sua mensagem"
                    placeholder="Descreva o problema ou a sugestão..."
                    multiline
                    numberOfLines={4}
                    value={suggestionText}
                    onChangeText={setSuggestionText}
                    style={{ backgroundColor: '#fff', marginBottom: 15 }}
                    activeOutlineColor="#E5293E"
                  />
                  
                  <View style={{ flexDirection: 'row', alignItems: 'center', marginBottom: 20 }}>
                    <Button mode="outlined" icon="camera-image" onPress={handlePickImage} textColor="#555" style={{ flex: 1, borderColor: '#ccc' }}>
                      {suggestionImage ? 'Trocar Imagem' : 'Anexar Print (Opcional)'}
                    </Button>
                    {suggestionImage && (
                      <View style={{ marginLeft: 10, position: 'relative' }}>
                        <Image source={{ uri: suggestionImage }} style={{ width: 40, height: 40, borderRadius: 8 }} />
                        <IconButton 
                          icon="close-circle" size={18} iconColor="#E5293E"
                          style={{ position: 'absolute', top: -15, right: -15, margin: 0, backgroundColor: '#fff' }}
                          onPress={() => setSuggestionImage(null)}
                        />
                      </View>
                    )}
                  </View>

                  <Button
                    mode="contained" buttonColor="#E5293E" icon="send"
                    loading={isSendingSuggestion} onPress={handleSendSuggestion}
                    disabled={suggestionText.trim().length === 0 || isSendingSuggestion}
                  >
                    Enviar Mensagem
                  </Button>
                </View>
              </View>
            </View>
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
  autocompleteOverlay: {
    position: 'absolute',
    backgroundColor: '#fff',
    borderRadius: 12,
    elevation: 6,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.3,
    shadowRadius: 5,
    zIndex: 999,
    maxHeight: 250,
  },
  autocompleteItem: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 8,
    paddingHorizontal: 8,
    borderBottomWidth: 1,
    borderBottomColor: '#f5f5f5',
  },
  autocompleteText: {
    fontSize: 15,
    color: '#333',
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
  // Estilos do Menu Lateral
  sidebarOverlay: { flex: 1, flexDirection: 'row', backgroundColor: 'rgba(0,0,0,0.5)' },
  sidebarCloseArea: { flex: 1 },
  sidebarContent: { width: '75%', maxWidth: 300, backgroundColor: '#fff', height: '100%', elevation: 16, shadowColor: '#000', shadowOffset: { width: 5, height: 0 }, shadowOpacity: 0.3, shadowRadius: 5 },
  sidebarHeader: { backgroundColor: '#E5293E', padding: 20, paddingTop: Platform.OS === 'ios' ? 50 : 20, borderBottomWidth: 1, borderBottomColor: '#eee' },
  sidebarTitle: { color: '#fff', fontSize: 20, fontWeight: 'bold' },
  sidebarItem: { flexDirection: 'row', alignItems: 'center', paddingVertical: 12, paddingHorizontal: 20 },
  sidebarItemText: { fontSize: 16, color: '#333', fontWeight: '500' },
  sidebarFooter: { padding: 20, borderTopWidth: 1, borderTopColor: '#eee', alignItems: 'center' },
  versionText: { color: '#999', fontSize: 12, fontWeight: 'bold' },
});