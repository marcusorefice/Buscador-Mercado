import { create } from 'zustand';
import { Product } from '../types';

interface ShoppingListItem extends Product {
  quantity: number;
}

interface ShoppingListState {
  list: ShoppingListItem[];
  toggleProduct: (product: Product) => void;
  updateQuantity: (product: Product, quantity: number) => void;
  clearList: () => void;
}

export const useShoppingListStore = create<ShoppingListState>((set) => ({
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
  clearList: () => set({ list: [] }),
}));