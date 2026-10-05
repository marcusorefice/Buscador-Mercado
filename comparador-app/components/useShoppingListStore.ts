import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { Product } from '../types';

interface ShoppingListItem extends Product {
  quantity: number;
  pinnedMarket?: string;
  checked?: boolean;
}

interface ShoppingListState {
  list: ShoppingListItem[];
  toggleProduct: (product: Product) => void;
  updateQuantity: (product: Product, quantity: number) => void;
  setPinnedMarket: (product: Product, marketName?: string) => void;
  toggleItemCheck: (product: Product) => void;
  clearList: () => void;
  refreshOffers: (atualizados: Product[]) => void;
}

export const useShoppingListStore = create<ShoppingListState>()(
  persist(
    (set) => ({
      list: [],
      toggleProduct: (product) => set((state) => {
        const exists = state.list.find(p => p.EAN === product.EAN && p.Produto_Ouro === product.Produto_Ouro);
        if (exists) {
          return { list: state.list.filter(p => p.EAN !== product.EAN || p.Produto_Ouro !== product.Produto_Ouro) };
        }
        return { list: [...state.list, { ...product, quantity: 1 }] };
      }),
      updateQuantity: (product, quantity) => set((state) => ({
        list: state.list.map(p =>
          (p.EAN === product.EAN && p.Produto_Ouro === product.Produto_Ouro) ? { ...p, quantity } : p
        )
      })),
      setPinnedMarket: (product, marketName) => set((state) => ({
        list: state.list.map(p =>
          (p.EAN === product.EAN && p.Produto_Ouro === product.Produto_Ouro) ? { ...p, pinnedMarket: marketName } : p
        )
      })),
      toggleItemCheck: (product) => set((state) => ({
        list: state.list.map(p =>
          (p.EAN === product.EAN && p.Produto_Ouro === product.Produto_Ouro) ? { ...p, checked: !p.checked } : p
        )
      })),
      clearList: () => set({ list: [] }),
      // Troca os preços salvos (que podem ser de dias atrás) pelos atuais da API,
      // mantendo quantidade, mercado fixado e check de cada item.
      // Produto que não voltou da API não tem mais oferta: fica na lista como "em falta".
      refreshOffers: (atualizados) => set((state) => {
        const porEan = new Map(atualizados.map(p => [p.EAN, p]));
        return {
          list: state.list.map(item => {
            const novo = porEan.get(item.EAN);
            if (!novo) return { ...item, Ofertas: [] };
            return { ...item, ...novo, quantity: item.quantity, pinnedMarket: item.pinnedMarket, checked: item.checked };
          })
        };
      }),
    }),
    {
      name: '@shopping_list',
      version: 1,
      storage: createJSONStorage(() => AsyncStorage),
      partialize: (state) => ({ list: state.list }),
    }
  )
);
