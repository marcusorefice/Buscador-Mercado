import { create } from 'zustand';
import { Product } from '../types';

interface ShoppingListState {
  list: Product[];
  toggleProduct: (product: Product) => void;
  clearList: () => void;
}

export const useShoppingListStore = create<ShoppingListState>((set) => ({
  list: [],
  toggleProduct: (product) => set((state) => {
    const exists = state.list.some(p => p.EAN === product.EAN);
    if (exists) {
      return { list: state.list.filter(p => p.EAN !== product.EAN) };
    } else {
      return { list: [...state.list, product] };
    }
  }),
  clearList: () => set({ list: [] }),
}));