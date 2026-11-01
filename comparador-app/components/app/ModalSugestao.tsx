import React, { useState } from 'react';
import { View, Modal, Alert, Image } from 'react-native';
import { Text, IconButton, Button, TextInput } from 'react-native-paper';
import * as ImagePicker from 'expo-image-picker';
import { API_URL } from '../../config';
import { estilosModal } from './estilosModal';

interface Props {
  visible: boolean;
  onFechar: () => void;
}

// Formulário de sugestão/erro com print opcional; a API repassa ao Discord
export const ModalSugestao = ({ visible, onFechar }: Props) => {
  const [suggestionText, setSuggestionText] = useState('');
  const [suggestionImage, setSuggestionImage] = useState<string | null>(null);
  const [suggestionImageBase64, setSuggestionImageBase64] = useState<string | null>(null);
  const [isSendingSuggestion, setIsSendingSuggestion] = useState(false);

  const handlePickImage = async () => {
    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ['images'],
      quality: 0.7,
      base64: true,
    });
    if (!result.canceled) {
      setSuggestionImage(result.assets[0].uri);
      setSuggestionImageBase64(result.assets[0].base64 ?? null);
    }
  };

  const handleSendSuggestion = async () => {
    if (!suggestionText.trim()) return;
    setIsSendingSuggestion(true);
    try {
      // A sugestão vai para a nossa API, que repassa ao Discord.
      // A URL do webhook fica só no servidor (qualquer um consegue extrair o que está dentro do APK).
      const response = await fetch(`${API_URL}/sugestoes`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'ngrok-skip-browser-warning': 'true' },
        body: JSON.stringify({
          texto: suggestionText,
          imagem_base64: suggestionImage ? suggestionImageBase64 : null,
          imagem_nome: suggestionImage ? (suggestionImage.split('/').pop() || 'print.jpg') : null,
        }),
      });

      if (response.ok || response.status === 204) {
        Alert.alert('Sucesso!', 'Sua sugestão foi enviada. Obrigado por ajudar a melhorar o app!');
        onFechar();
        setSuggestionText('');
        setSuggestionImage(null);
        setSuggestionImageBase64(null);
      } else {
        throw new Error('Falha no envio');
      }
    } catch (error) {
      Alert.alert('Erro', 'Não foi possível enviar a sugestão. Verifique sua conexão e tente novamente.');
    } finally {
      setIsSendingSuggestion(false);
    }
  };

  return (
    <Modal visible={visible} animationType="slide" transparent={true} onRequestClose={onFechar}>
      <View style={estilosModal.modalOverlay}>
        <View style={estilosModal.modalContent}>
          <View style={estilosModal.modalHeader}>
            <Text style={estilosModal.modalTitle}>💡 Enviar Sugestão</Text>
            <IconButton icon="close" onPress={onFechar} />
          </View>
          <View style={{ padding: 20 }}>
            <Text style={{ marginBottom: 15, color: '#555', fontSize: 15, lineHeight: 22 }}>
              Encontrou algum erro ou tem uma ideia? Envie direto por aqui!
            </Text>
            <TextInput
              mode="outlined"
              label="Sua mensagem"
              placeholder="Descreva o problema ou a sugestão..."
              multiline
              numberOfLines={4}
              value={suggestionText}
              onChangeText={setSuggestionText}
              style={{ backgroundColor: '#fff', marginBottom: 15 }}
              activeOutlineColor="#E5293E"
            />

            <View style={{ flexDirection: 'row', alignItems: 'center', marginBottom: 20 }}>
              <Button mode="outlined" icon="camera-image" onPress={handlePickImage} textColor="#555" style={{ flex: 1, borderColor: '#ccc' }}>
                {suggestionImage ? 'Trocar Imagem' : 'Anexar Print (Opcional)'}
              </Button>
              {suggestionImage && (
                <View style={{ marginLeft: 10, position: 'relative' }}>
                  <Image source={{ uri: suggestionImage }} style={{ width: 40, height: 40, borderRadius: 8 }} />
                  <IconButton
                    icon="close-circle" size={18} iconColor="#E5293E"
                    style={{ position: 'absolute', top: -15, right: -15, margin: 0, backgroundColor: '#fff' }}
                    onPress={() => setSuggestionImage(null)}
                  />
                </View>
              )}
            </View>

            <Button
              mode="contained" buttonColor="#E5293E" icon="send"
              loading={isSendingSuggestion} onPress={handleSendSuggestion}
              disabled={suggestionText.trim().length === 0 || isSendingSuggestion}
            >
              Enviar Mensagem
            </Button>
          </View>
        </View>
      </View>
    </Modal>
  );
};
