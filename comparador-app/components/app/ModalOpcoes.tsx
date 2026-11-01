import React from 'react';
import { View, StyleSheet, TouchableOpacity, ScrollView, Modal } from 'react-native';
import { Text, IconButton } from 'react-native-paper';
import { estilosModal } from './estilosModal';

export interface Opcao<T extends string> {
  chave: T;
  titulo: string;
  descricao?: string;
}

interface Props<T extends string> {
  visible: boolean;
  titulo: string;
  opcoes: Opcao<T>[];
  selecionada: T;
  onEscolher: (chave: T) => void;
  onFechar: () => void;
}

// Lista de opções com uma marcada: usada no filtro de mercado e na ordenação
export function ModalOpcoes<T extends string>({ visible, titulo, opcoes, selecionada, onEscolher, onFechar }: Props<T>) {
  return (
    <Modal visible={visible} animationType="slide" transparent={true} onRequestClose={onFechar}>
      <View style={estilosModal.modalOverlay}>
        <View style={estilosModal.modalContent}>
          <View style={estilosModal.modalHeader}>
            <Text style={estilosModal.modalTitle}>{titulo}</Text>
            <IconButton icon="close" onPress={onFechar} />
          </View>
          <ScrollView>
            {opcoes.map(opcao => (
              <TouchableOpacity
                key={opcao.chave}
                style={[styles.opcao, selecionada === opcao.chave && styles.opcaoSelecionada]}
                onPress={() => { onEscolher(opcao.chave); onFechar(); }}
              >
                <Text style={[styles.opcaoTexto, selecionada === opcao.chave && styles.opcaoTextoSelecionado]}>
                  {opcao.titulo}
                </Text>
                {opcao.descricao ? <Text style={styles.descricao}>{opcao.descricao}</Text> : null}
              </TouchableOpacity>
            ))}
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  opcao: {
    paddingVertical: 16,
    paddingHorizontal: 20,
    borderBottomWidth: 1,
    borderBottomColor: '#f5f5f5',
  },
  opcaoSelecionada: {
    backgroundColor: '#fff0f2',
  },
  opcaoTexto: {
    fontSize: 16,
    color: '#444',
  },
  opcaoTextoSelecionado: {
    color: '#E5293E',
    fontWeight: 'bold',
  },
  descricao: { fontSize: 12, color: '#888', marginTop: 2 },
});
