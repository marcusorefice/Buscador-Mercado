import React from 'react';
import { View, StyleSheet, Modal, FlatList, Image, TouchableOpacity } from 'react-native';
import { Text, IconButton, Divider } from 'react-native-paper';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useShoppingListStore } from './useShoppingListStore';
import { Product } from '../types';

interface ShoppingListModalProps {
  visible: boolean;
  onDismiss: () => void;
}

const formatPrice = (value: number) => {
  return value.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
};

export const ShoppingListModal: React.FC<ShoppingListModalProps> = ({ visible, onDismiss }) => {
  const list = useShoppingListStore(state => state.list);
  const toggleProduct = useShoppingListStore(state => state.toggleProduct);
  const clearList = useShoppingListStore(state => state.clearList);

  // Soma o menor preço de todos os itens da lista
  const total = list.reduce((sum, item) => sum + (item.Menor_Preco || 0), 0);

  const renderItem = ({ item }: { item: Product }) => (
    <View style={styles.itemRow}>
      <Image source={item.Imagem && item.Imagem.startsWith('http') ? { uri: item.Imagem } : require('../assets/placeholder.png')} style={styles.itemImage} resizeMode="contain" />
      <View style={styles.itemInfo}>
        <Text style={styles.itemName} numberOfLines={2}>{item.Produto_Ouro}</Text>
        <Text style={styles.itemPrice}>R$ {formatPrice(item.Menor_Preco || 0)}</Text>
      </View>
      <IconButton
        icon="trash-can-outline"
        iconColor="#E5293E"
        size={22}
        onPress={() => toggleProduct(item)}
      />
    </View>
  );

  return (
    <Modal visible={visible} animationType="slide" presentationStyle="pageSheet" onRequestClose={onDismiss}>
      <SafeAreaView style={styles.container} edges={['bottom', 'left', 'right']}>
        <View style={styles.header}>
          <TouchableOpacity onPress={onDismiss} style={styles.closeButton} hitSlop={{ top: 20, bottom: 20, left: 20, right: 20 }}>
            <Text style={styles.closeButtonText}>✕</Text>
          </TouchableOpacity>
          <Text style={styles.headerTitle}>Minha Lista</Text>
          {/* Botão de limpar a lista inteira */}
          <IconButton icon="broom" size={24} onPress={clearList} iconColor="#666" />
        </View>

        {list.length === 0 ? (
          <View style={styles.emptyContainer}>
            <IconButton icon="cart-outline" size={64} iconColor="#ccc" />
            <Text style={styles.emptyText}>Sua lista está vazia!</Text>
          </View>
        ) : (
          <>
            <FlatList
              data={list}
              keyExtractor={(item, index) => `${item.EAN}_${index}`}
              renderItem={renderItem}
              contentContainerStyle={styles.listContent}
              ItemSeparatorComponent={() => <Divider />}
            />
            <View style={styles.footer}>
              <Text style={styles.totalLabel}>Total Estimado:</Text>
              <Text style={styles.totalValue}>R$ {formatPrice(total)}</Text>
            </View>
          </>
        )}
      </SafeAreaView>
    </Modal>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#fff' },
  header: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingHorizontal: 8, paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: '#f0f0f0' },
  closeButton: { width: 48, height: 48, justifyContent: 'center', alignItems: 'center' },
  closeButtonText: { fontSize: 22, fontWeight: 'bold', color: '#444' },
  headerTitle: { fontSize: 18, fontWeight: 'bold', color: '#333' },
  emptyContainer: { flex: 1, justifyContent: 'center', alignItems: 'center' },
  emptyText: { fontSize: 16, color: '#999', marginTop: 8 },
  listContent: { paddingBottom: 20 },
  itemRow: { flexDirection: 'row', alignItems: 'center', padding: 12 },
  itemImage: { width: 50, height: 50, marginRight: 12 },
  itemInfo: { flex: 1, justifyContent: 'center' },
  itemName: { fontSize: 14, color: '#333', marginBottom: 4 },
  itemPrice: { fontSize: 16, fontWeight: 'bold', color: '#E5293E' },
  footer: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', padding: 20, borderTopWidth: 1, borderTopColor: '#eee', backgroundColor: '#fdfdfd' },
  totalLabel: { fontSize: 16, color: '#666', fontWeight: '500' },
  totalValue: { fontSize: 24, fontWeight: 'bold', color: '#E5293E' }
});