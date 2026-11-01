import React, { useEffect } from 'react';
import { View, StyleSheet, Modal } from 'react-native';
import { Text, IconButton, Button } from 'react-native-paper';
import { SafeAreaView } from 'react-native-safe-area-context';
import { CameraView, useCameraPermissions } from 'expo-camera';

interface Props {
  visible: boolean;
  onFechar: () => void;
  onLido: (codigo: string) => void;
}

// Câmera para ler o código de barras (EAN) de um produto
export const ModalScanner = ({ visible, onFechar, onLido }: Props) => {
  const [permission, requestPermission] = useCameraPermissions();

  // Pede a permissão da câmera assim que o scanner abre
  useEffect(() => {
    if (visible && !permission?.granted) requestPermission();
  }, [visible]);

  return (
    <Modal visible={visible} animationType="slide" transparent={false} onRequestClose={onFechar}>
      <SafeAreaView style={{ flex: 1, backgroundColor: 'black' }} edges={['top', 'bottom']}>
        <View style={styles.scannerHeader}>
          <Text style={styles.scannerTitle}>Escanear Código de Barras</Text>
          <IconButton icon="close" iconColor="white" size={24} onPress={onFechar} />
        </View>
        {permission?.granted ? (
          <View style={styles.scannerContainer}>
            <CameraView
              style={StyleSheet.absoluteFillObject}
              facing="back"
              barcodeScannerSettings={{ barcodeTypes: ["ean13", "ean8", "upc_a", "upc_e"] }}
              onBarcodeScanned={({ data }) => {
                onFechar();
                onLido(data);
              }}
            />
            <View style={styles.scannerOverlay}>
              <View style={styles.scannerTarget} />
            </View>
          </View>
        ) : (
          <View style={styles.centerContainer}>
            <Text style={{ color: 'white', marginBottom: 20 }}>Precisamos de acesso à câmera.</Text>
            <Button mode="contained" onPress={requestPermission} buttonColor="#E5293E">Conceder Permissão</Button>
          </View>
        )}
      </SafeAreaView>
    </Modal>
  );
};

const styles = StyleSheet.create({
  scannerHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingHorizontal: 16, paddingVertical: 8, backgroundColor: 'black' },
  scannerTitle: { color: 'white', fontSize: 18, fontWeight: 'bold' },
  scannerContainer: { flex: 1, position: 'relative' },
  scannerOverlay: { flex: 1, justifyContent: 'center', alignItems: 'center', backgroundColor: 'rgba(0,0,0,0.5)' },
  scannerTarget: { width: 250, height: 150, borderWidth: 2, borderColor: '#E5293E', borderRadius: 12, backgroundColor: 'transparent' },
  centerContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: 20,
  },
});
