import React, { useState, useEffect } from 'react';
import { View, StyleSheet, Modal } from 'react-native';
import { Text, IconButton, Button, TextInput } from 'react-native-paper';
import { usePreferenciasStore, formatarCep, CEP_PADRAO } from '../usePreferenciasStore';
import { estilosModal } from './estilosModal';

interface Props {
  visible: boolean;
  onFechar: () => void;
}

export const ModalConfiguracoes = ({ visible, onFechar }: Props) => {
  const cepSalvo = usePreferenciasStore(state => state.cep);
  const setCepSalvo = usePreferenciasStore(state => state.setCep);
  const [cepDigitado, setCepDigitado] = useState('');

  // Ao abrir, o campo começa com o CEP já salvo
  useEffect(() => {
    if (visible) setCepDigitado(cepSalvo);
  }, [visible]);

  return (
    <Modal visible={visible} animationType="slide" transparent={true} onRequestClose={onFechar}>
      <View style={estilosModal.modalOverlay}>
        <View style={estilosModal.modalContent}>
          <View style={estilosModal.modalHeader}>
            <Text style={estilosModal.modalTitle}>⚙️ Configurações</Text>
            <IconButton icon="close" onPress={onFechar} />
          </View>
          <View style={{ padding: 20 }}>
            <Text style={styles.configRotulo}>Seu CEP</Text>
            <Text style={styles.configAjuda}>
              Alguns mercados (como o Atacadão) mostram preços diferentes conforme o CEP. Informe o seu para copiá-lo e colar no site do mercado.
            </Text>
            <TextInput
              mode="outlined"
              label="CEP"
              placeholder={CEP_PADRAO}
              value={cepDigitado}
              onChangeText={t => setCepDigitado(formatarCep(t))}
              keyboardType="number-pad"
              maxLength={9}
              style={{ backgroundColor: '#fff', marginBottom: 15 }}
              activeOutlineColor="#E5293E"
            />
            <Button
              mode="contained"
              buttonColor="#E5293E"
              disabled={cepDigitado !== '' && cepDigitado.length !== 9}
              onPress={() => { setCepSalvo(cepDigitado); onFechar(); }}
            >
              Salvar
            </Button>
            {cepSalvo !== '' && (
              <Button textColor="#888" style={{ marginTop: 8 }} onPress={() => { setCepSalvo(''); setCepDigitado(''); }}>
                Voltar ao CEP padrão ({CEP_PADRAO})
              </Button>
            )}
          </View>
        </View>
      </View>
    </Modal>
  );
};

const styles = StyleSheet.create({
  configRotulo: { fontSize: 16, fontWeight: 'bold', color: '#333', marginBottom: 4 },
  configAjuda: { fontSize: 13, color: '#666', lineHeight: 19, marginBottom: 14 },
});
