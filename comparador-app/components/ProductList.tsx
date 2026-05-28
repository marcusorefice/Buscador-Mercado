import React, { useCallback, memo } from 'react';
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

export const ProductList = memo(({ products, refreshing, onRefresh, ListEmptyComponent, onProductPress }: ProductListProps) => {
  const renderItem = useCallback(({ item }: { item: Product }) => (
    <ProductCard product={item} onPress={onProductPress} />
  ), [onProductPress]);

  return (
    <FlatList
      data={products}
      numColumns={2}
      keyExtractor={(item, index) => `${item.EAN}_${index}`}
      columnWrapperStyle={styles.row}
      contentContainerStyle={styles.listContainer}
      renderItem={renderItem}
      showsVerticalScrollIndicator={false}
      onRefresh={onRefresh}
      refreshing={refreshing}
      ListEmptyComponent={ListEmptyComponent}
      // Otimização de performance para listas grandes
      removeClippedSubviews={true}
      maxToRenderPerBatch={12}
      updateCellsBatchingPeriod={30}
      windowSize={11}
      initialNumToRender={10}
    />
  );
});

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