import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { Product } from '../types';

interface ShoppingListState {
  list: Product[];
  toggleProduct: (product: Product) => void;
  clearList: () => void;
}

export const useShoppingListStore = create<ShoppingListState>()(
  persist(
    (set, get) => ({
      list: [],
      
      // Função inteligente: Adiciona se não existir, remove se já existir!
      toggleProduct: (product) => {
        const currentList = get().list;
        // Verifica pelo EAN e pelo Nome para garantir precisão
        const exists = currentList.some((p) => p.EAN === product.EAN && p.Produto_Ouro === product.Produto_Ouro);
        
        if (exists) {
          set({ list: currentList.filter((p) => !(p.EAN === product.EAN && p.Produto_Ouro === product.Produto_Ouro)) });
        } else {
          set({ list: [...currentList, product] });
        }
      },
      clearList: () => set({ list: [] }),
    }),
    {
      name: 'minha-lista-de-compras', // Nome do "arquivo" salvo no celular
      storage: createJSONStorage(() => AsyncStorage),
    }
  )
);