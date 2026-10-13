import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import AsyncStorage from '@react-native-async-storage/async-storage';

// CEP usado hoje: o de Jundiaí, onde estão os preços coletados
export const CEP_PADRAO = '13214-900';

export const formatarCep = (valor: string) => {
  const d = valor.replace(/\D/g, '').slice(0, 8);
  return d.length > 5 ? `${d.slice(0, 5)}-${d.slice(5)}` : d;
};

interface PreferenciasState {
  // Vazio = a pessoa ainda não informou o dela
  cep: string;
  setCep: (cep: string) => void;
}

export const usePreferenciasStore = create<PreferenciasState>()(
  persist(
    (set) => ({
      cep: '',
      setCep: (cep) => set({ cep }),
    }),
    {
      name: 'preferencias-storage',
      storage: createJSONStorage(() => AsyncStorage),
    }
  )
);
