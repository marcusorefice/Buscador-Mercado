import { Platform } from 'react-native';
import { DefaultTheme } from 'react-native-paper';

// Configurações e constantes do app (antes no topo do App.tsx)

// --- CONFIGURAÇÃO DE AMBIENTE ---
// EXPO_PUBLIC_API_URL (arquivo .env do app) sobrescreve tudo, ex.: API local ou outro túnel
export const API_URL = process.env.EXPO_PUBLIC_API_URL || (__DEV__ && Platform.OS !== 'web' // na web (navegador) usa sempre o Render
  ? 'https://badness-impale-suitably.ngrok-free.dev' // ngrok: Ignora o Firewall do Windows e atualiza na hora!
  : 'https://buscador-mercado.onrender.com');        // Render: App Oficial da Nuvem

// As sugestões da busca (Typesense) vêm pela API em /autocompletar: o Android bloqueia HTTP sem
// criptografia nos APKs, então o app não fala direto com o servidor do Typesense.

// Quantos produtos vêm por vez; o resto carrega conforme a pessoa rola a lista
export const TAMANHO_PAGINA = 40;

export const theme = {
  ...DefaultTheme,
  colors: {
    ...DefaultTheme.colors,
    primary: '#E5293E', // Vermelho vibrante estilo app comercial
    accent: '#ff4d5a',
  },
};

// Só os mercados coletados hoje. Assaí, Fort, Roldão, Tauste e Tenda estão pausados (exigem OCR de encarte):
// quando voltarem, é só reincluí-los aqui.
export const MARKETS = [
  'Todos os Mercados',
  'Atacadão',
  'Boa Supermercados',
  'Carrefour',
  'Covabra',
  'Dom Olivio', // sem acento: é o nome que a API grava, e o filtro compara o texto exato
  'Oba Hortifruti',
  'Pão de Açúcar',
  'São Vicente'
];

export type Ordenacao = 'relevance' | 'discount' | 'price';

// O botão de ordenação abre um menu com todas as opções
export const ORDENACOES: Record<Ordenacao, { titulo: string; icone: string; descricao: string }> = {
  relevance: { titulo: 'Em Alta', icone: 'fire', descricao: 'Os produtos mais procurados primeiro' },
  discount: { titulo: 'Maiores Descontos', icone: 'percent', descricao: 'Maior queda de preço primeiro' },
  price: { titulo: 'Menores Preços', icone: 'currency-usd', descricao: 'Do mais barato para o mais caro' },
};

export const TAGS_PADRAO = ['coca-cola', 'heineken', 'azeite', 'óleo', 'leite', 'café', 'papel higiênico', 'sabão em pó'];
