import React from 'react';
import { View, StyleSheet, TouchableOpacity, ScrollView, Modal, Platform } from 'react-native';
import { Text, IconButton } from 'react-native-paper';
import Constants from 'expo-constants';

interface Props {
  visible: boolean;
  onFechar: () => void;
  onSugestao: () => void;
  onConfiguracoes: () => void;
}

export const MenuLateral = ({ visible, onFechar, onSugestao, onConfiguracoes }: Props) => (
  <Modal visible={visible} animationType="fade" transparent={true} onRequestClose={onFechar}>
    <View style={styles.sidebarOverlay}>
      <View style={styles.sidebarContent}>
        <View style={styles.sidebarHeader}>
          <Text style={styles.sidebarTitle}>Comparador Jundiaí</Text>
        </View>
        <ScrollView style={{ flex: 1, paddingTop: 10 }}>
          <TouchableOpacity style={styles.sidebarItem} onPress={() => { onFechar(); onSugestao(); }}>
            <IconButton icon="lightbulb-on-outline" size={24} iconColor="#555" style={{ margin: 0, marginRight: 10 }} />
            <Text style={styles.sidebarItemText}>Enviar Sugestão</Text>
          </TouchableOpacity>
          <TouchableOpacity style={styles.sidebarItem} onPress={() => { onFechar(); onConfiguracoes(); }}>
            <IconButton icon="cog-outline" size={24} iconColor="#555" style={{ margin: 0, marginRight: 10 }} />
            <Text style={styles.sidebarItemText}>Configurações</Text>
          </TouchableOpacity>
        </ScrollView>
        <View style={styles.sidebarFooter}>
          <Text style={styles.versionText}>Versão {Constants.expoConfig?.version || '1.0.0'}</Text>
        </View>
      </View>
      <TouchableOpacity style={styles.sidebarCloseArea} activeOpacity={1} onPress={onFechar} />
    </View>
  </Modal>
);

const styles = StyleSheet.create({
  sidebarOverlay: { flex: 1, flexDirection: 'row', backgroundColor: 'rgba(0,0,0,0.5)' },
  sidebarCloseArea: { flex: 1 },
  sidebarContent: { width: '75%', maxWidth: 300, backgroundColor: '#fff', height: '100%', elevation: 16, shadowColor: '#000', shadowOffset: { width: 5, height: 0 }, shadowOpacity: 0.3, shadowRadius: 5 },
  sidebarHeader: { backgroundColor: '#E5293E', padding: 20, paddingTop: Platform.OS === 'ios' ? 50 : 20, borderBottomWidth: 1, borderBottomColor: '#eee' },
  sidebarTitle: { color: '#fff', fontSize: 20, fontWeight: 'bold' },
  sidebarItem: { flexDirection: 'row', alignItems: 'center', paddingVertical: 12, paddingHorizontal: 20 },
  sidebarItemText: { fontSize: 16, color: '#333', fontWeight: '500' },
  sidebarFooter: { padding: 20, borderTopWidth: 1, borderTopColor: '#eee', alignItems: 'center' },
  versionText: { color: '#999', fontSize: 12, fontWeight: 'bold' },
});
