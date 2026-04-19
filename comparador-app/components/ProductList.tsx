import React from 'react';
import { FlatList, StyleSheet, View } from 'react-native';
import { ProductCard } from './ProductCard';
import { Product } from '../types';

interface ProductListProps {
  products: Product[];
  ListEmptyComponent?: React.ComponentType<any> | React.ReactElement | null;
  refreshing?: boolean;
  onRefresh?: () => void;
}

export const ProductList: React.FC<ProductListProps> = ({
  products,
  ListEmptyComponent,
  refreshing,
  onRefresh
}) => {
  return (
    <FlatList
      data={products}
      numColumns={2} 
      keyExtractor={(item) => String(item.id)}
      // O segredo do alinhamento está nestas duas linhas abaixo:
      columnWrapperStyle={styles.row}
      contentContainerStyle={styles.listContainer}
      renderItem={({ item }) => (
        <ProductCard product={item} />
      )}
      showsVerticalScrollIndicator={false}
      ListEmptyComponent={ListEmptyComponent}
      refreshing={refreshing}
      onRefresh={onRefresh}
      // Otimização de performance para listas grandes
      removeClippedSubviews={true}
      maxToRenderPerBatch={10}
      windowSize={10}
    />
  );
};

const styles = StyleSheet.create({
  listContainer: {
    paddingHorizontal: 8,
    paddingTop: 8,
    paddingBottom: 32,
    backgroundColor: '#f5f5f5', // Cor de fundo leve para destacar os cards brancos
  },
  row: {
    justifyContent: 'space-between',
    // IMPORTANTE: Faz com que todos os itens da mesma linha tenham a mesma altura
    alignItems: 'stretch', 
    marginBottom: 8, // Espaçamento entre as linhas
  },
});