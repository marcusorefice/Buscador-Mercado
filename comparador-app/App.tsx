import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { View, StyleSheet, StatusBar, TouchableOpacity, ScrollView, Platform, Keyboard } from 'react-native';
import { Provider as PaperProvider, Searchbar, Text, Chip, IconButton, Button } from 'react-native-paper';
import { SafeAreaProvider, SafeAreaView } from 'react-native-safe-area-context';
import axios from 'axios';
import { ProductList } from './components/ProductList';
import { ProductDetailsModal } from './components/ProductDetailsModal';
import { ShoppingListModal } from './components/ShoppingListModal';
import { useShoppingListStore } from './components/useShoppingListStore';
import { Product } from './types';
import { SkeletonCard } from './components/SkeletonCard';
import { ModalOpcoes } from './components/app/ModalOpcoes';
import { ModalConfiguracoes } from './components/app/ModalConfiguracoes';
import { ModalScanner } from './components/app/ModalScanner';
import { MenuLateral } from './components/app/MenuLateral';
import { ModalSugestao } from './components/app/ModalSugestao';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { API_URL, TAMANHO_PAGINA, theme, MARKETS, Ordenacao, ORDENACOES, TAGS_PADRAO } from './config';

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
  const [dynamicTags, setDynamicTags] = useState<string[]>(TAGS_PADRAO);
  const searchTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const productsRef = useRef<Product[]>([]);
  const temMaisRef = useRef(false);
  const carregandoMaisRef = useRef(false);
  const queryCarregadaRef = useRef('');
  const sugestoesCacheRef = useRef<Map<string, string[]>>(new Map());
  const autocompleteTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  
  const [isSearchFocused, setIsSearchFocused] = useState(false);
  // Posição real da barra de busca, medida na tela. As sugestões abrem logo abaixo dela,
  // em vez de usar um "top" fixo que só batia em um tamanho de tela.
  const conteudoRef = useRef<View>(null);
  const buscaRef = useRef<View>(null);
  const [posSugestoes, setPosSugestoes] = useState<{ top: number; left: number; width: number } | null>(null);
  const medirBusca = useCallback(() => {
    const busca = buscaRef.current;
    const conteudo = conteudoRef.current;
    if (!busca || !conteudo) return;
    busca.measureLayout(
      conteudo as any,
      (x, y, width, height) => setPosSugestoes({ top: y + height + 4, left: x, width }),
      () => {}
    );
  }, []);
  const [textSuggestions, setTextSuggestions] = useState<string[]>([]);
  
  const [isScanning, setIsScanning] = useState(false);

  // Lendo a quantidade de itens na lista usando Zustand
  const cartItemsCount = useShoppingListStore(state => state.list.length);

  // Filtros Globais
  const [sortBy, setSortBy] = useState<Ordenacao>('relevance');
  // Termos mais buscados por todos os usuários (vêm da API) para os chips da tela inicial
  const buscasPopularesRef = useRef<string[]>([]);
  const ultimoPedidoProdutosRef = useRef(0);
  const [selectedMarket, setSelectedMarket] = useState('Todos os Mercados');
  const [isMarketModalVisible, setMarketModalVisible] = useState(false);
  const [isSortModalVisible, setSortModalVisible] = useState(false);
  const [isSettingsVisible, setSettingsVisible] = useState(false);
  // Busca que a pessoa pediu: só entra no histórico (e nos atalhos) se achar produtos
  const buscaPendenteRef = useRef('');
  // Quando a API corrige um erro de digitação (ex: heinekem -> heineken), guardamos os dois para avisar a pessoa
  const [buscaCorrigida, setBuscaCorrigida] = useState<{ digitada: string; corrigida: string } | null>(null);

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
      // Só buscas confirmadas (Enter, atalho, sugestão) contam para os "mais buscados"; o que sai enquanto digita não
      if (buscaPendenteRef.current && buscaPendenteRef.current === currentQuery.trim().toLowerCase()) params.registrar = true;
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

      const cabecalho = response.headers?.['x-busca-corrigida'];
      const corrigida = cabecalho ? decodeURIComponent(String(cabecalho)) : '';
      setBuscaCorrigida(corrigida ? { digitada: currentQuery.trim(), corrigida } : null);

      setProducts(response.data);
      temMaisRef.current = response.data.length >= TAMANHO_PAGINA;
      queryCarregadaRef.current = corrigida || currentQuery; // as próximas páginas usam a busca já corrigida

      if (response.data.length > 0 && buscaPendenteRef.current && buscaPendenteRef.current === currentQuery.trim().toLowerCase()) {
        const achada = buscaPendenteRef.current;
        buscaPendenteRef.current = '';
        guardarNoHistorico(corrigida || achada); // erro de digitação não vira atalho
      }

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

  const saveSearchToHistory = (query: string) => {
    if (!query || query.trim().length < 3) return;
    buscaPendenteRef.current = query.trim().toLowerCase();
  };

  const guardarNoHistorico = async (q: string) => {
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
    const termo = searchQuery.trim();
    const comFiltro = selectedMarket !== 'Todos os Mercados';
    const alternativas = dynamicTags.slice(0, 5);
    return (
      <View style={styles.vazioContainer}>
        <Text style={styles.vazioTitulo}>
          {termo ? `Nada encontrado para “${termo}”` : 'Nenhum produto encontrado'}
        </Text>
        <Text style={styles.vazioDica}>
          {comFiltro
            ? `Você está filtrando só por ${selectedMarket}. Tente ver todos os mercados.`
            : 'Confira a digitação ou tente uma palavra mais simples, como a marca ou o tipo do produto.'}
        </Text>
        {comFiltro && (
          <Button mode="contained" buttonColor="#E5293E" style={styles.vazioBotao} onPress={() => setSelectedMarket('Todos os Mercados')}>
            Ver todos os mercados
          </Button>
        )}
        {termo !== '' && (
          <Button mode="outlined" textColor="#E5293E" style={styles.vazioBotao} onPress={returnHome}>
            Limpar busca
          </Button>
        )}
        <Text style={styles.vazioSub}>Que tal buscar por:</Text>
        <View style={styles.vazioChips}>
          {alternativas.map(tag => (
            <Chip key={tag} compact onPress={() => handleTagPress(tag)} style={styles.vazioChip}>#{tag}</Chip>
          ))}
        </View>
      </View>
    );
  }, [loading, searchQuery, selectedMarket, dynamicTags, sortBy]);

  const handleProductPress = useCallback((item: Product) => {
    setSelectedProduct(item);
    setModalVisible(true);
  }, []);

  return (
    <SafeAreaProvider>
      <PaperProvider theme={theme}>
        <SafeAreaView style={styles.safeAreaWrapper} edges={['top', 'left', 'right']}>
          <StatusBar barStyle="light-content" backgroundColor="#E5293E" />
          
          <View ref={conteudoRef} style={{ flex: 1 }} collapsable={false}>
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
              <View ref={buscaRef} onLayout={medirBusca} collapsable={false} style={{ flex: 1, position: 'relative' }}>
                <Searchbar
                  placeholder="Ex: Cerveja Heineken, Fralda..."
                  onChangeText={handleSearchChange}
                  value={searchQuery}
                  onSubmitEditing={onSearchSubmit}
                  onIconPress={onSearchSubmit}
                  onClearIconPress={clearSearchText}
                  onFocus={() => { medirBusca(); setIsSearchFocused(true); }}
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
                onPress={() => setIsScanning(true)}
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
                onPress={() => setSortModalVisible(true)}
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
            {buscaCorrigida && (
              <View style={styles.correcaoBanner}>
                <Text style={styles.correcaoTexto}>
                  Mostrando resultados para <Text style={{ fontWeight: 'bold' }}>“{buscaCorrigida.corrigida}”</Text>
                  {'  '}(você digitou “{buscaCorrigida.digitada}”)
                </Text>
              </View>
            )}
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
          {isSearchFocused && textSuggestions.length > 0 && posSugestoes && (
            <View style={[styles.autocompleteOverlay, posSugestoes]}>
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
            allProducts={products}
            onProductPress={handleProductPress}
            apiUrl={API_URL}
          />

          <ModalOpcoes
            visible={isMarketModalVisible}
            titulo="Filtrar por Mercado"
            opcoes={MARKETS.map(m => ({ chave: m, titulo: m }))}
            selecionada={selectedMarket}
            onEscolher={setSelectedMarket}
            onFechar={() => setMarketModalVisible(false)}
          />

          <ModalOpcoes
            visible={isSortModalVisible}
            titulo="Ordenar por"
            opcoes={(Object.keys(ORDENACOES) as Ordenacao[]).map(chave => ({ chave, ...ORDENACOES[chave] }))}
            selecionada={sortBy}
            onEscolher={setSortBy}
            onFechar={() => setSortModalVisible(false)}
          />

          <ModalConfiguracoes visible={isSettingsVisible} onFechar={() => setSettingsVisible(false)} />

          <ModalScanner
            visible={isScanning}
            onFechar={() => setIsScanning(false)}
            onLido={codigo => {
              setSearchQuery(codigo);
              searchQueryRef.current = codigo;
              fetchProducts(codigo);
            }}
          />

          <MenuLateral
            visible={isSidebarVisible}
            onFechar={() => setSidebarVisible(false)}
            onSugestao={() => setSuggestionModalVisible(true)}
            onConfiguracoes={() => setSettingsVisible(true)}
          />

          <ModalSugestao visible={isSuggestionModalVisible} onFechar={() => setSuggestionModalVisible(false)} />

        </SafeAreaView>
      </PaperProvider>
    </SafeAreaProvider>
  );
}

const styles = StyleSheet.create({
  correcaoBanner: { backgroundColor: '#FFF4E5', paddingVertical: 8, paddingHorizontal: 14 },
  correcaoTexto: { fontSize: 13, color: '#8A5300' },
  vazioContainer: { padding: 24, alignItems: 'center' },
  vazioTitulo: { fontSize: 17, fontWeight: 'bold', color: '#333', textAlign: 'center', marginBottom: 8 },
  vazioDica: { fontSize: 14, color: '#666', textAlign: 'center', lineHeight: 20, marginBottom: 16 },
  vazioBotao: { alignSelf: 'stretch', marginBottom: 8 },
  vazioSub: { fontSize: 13, color: '#888', marginTop: 16, marginBottom: 8 },
  vazioChips: { flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'center', gap: 8 },
  vazioChip: { backgroundColor: '#fde8ea' },
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
});
