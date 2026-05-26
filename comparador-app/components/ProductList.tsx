import React from 'react';
import { FlatList, StyleSheet } from 'react-native';
import { ProductCard } from './ProductCard';
import { Product } from '../types';

interface ProductListProps {
  products: Product[];
  refreshing: boolean;
  onRefresh: () => void;
  ListEmptyComponent: React.ComponentType<any> | React.ReactElement | null | undefined;
  onProductPress: (product: Product) => void;
}

export const ProductList: React.FC<ProductListProps> = ({ products, refreshing, onRefresh, ListEmptyComponent, onProductPress }) => {
  return (
    <FlatList
      data={products}
      numColumns={2}
      keyExtractor={(item) => String(item.EAN)}
      columnWrapperStyle={styles.row}
      contentContainerStyle={styles.listContainer}
      renderItem={({ item }) => <ProductCard product={item} onPress={() => onProductPress(item)} />}
      showsVerticalScrollIndicator={false}
      onRefresh={onRefresh}
      refreshing={refreshing}
      ListEmptyComponent={ListEmptyComponent}
      // Otimização de performance para listas grandes
      removeClippedSubviews={true}
      maxToRenderPerBatch={10}
      windowSize={10}
      initialNumToRender={6}
    />
  );
};

const styles = StyleSheet.create({
  listContainer: {
    paddingHorizontal: 6,
    paddingTop: 8,
    paddingBottom: 32,
  },
  row: {
    justifyContent: 'space-between',
  },
});