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

  // Informar a altura estimada do Card (~310px) poupa o React Native de calcular dinamicamente item por item
  const getItemLayout = useCallback((data: any, index: number) => ({
    length: 310,
    // Como temos 2 colunas, pulamos a altura a cada linha (index / 2)
    offset: 310 * Math.floor(index / 2),
    index,
  }), []);

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
      getItemLayout={getItemLayout}
      // Otimização de performance para listas grandes
      removeClippedSubviews={true}
      maxToRenderPerBatch={6}
      updateCellsBatchingPeriod={50}
      windowSize={5}
      initialNumToRender={6}
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