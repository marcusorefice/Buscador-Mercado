import json
import sys
import os

# Adiciona o diretorio atual para poder importar utils
sys.path.append(os.getcwd())
from utils import is_valid_check_digit, normalizar_para_cache

def clean_lib(filepath):
    if not os.path.exists(filepath):
        return
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    new_data = {}
    removidos = 0
    modificados = 0

    for k, v in list(data.items()):
        ean = v.get('ean', 'N/A')
        if ean != 'N/A' and not is_valid_check_digit(ean):
            print(f"Removendo/Ajustando EAN Invalido: {ean} - {v.get('nome_comum')}")
            v['ean'] = 'N/A'
            novo_id = normalizar_para_cache(v.get('nome_comum', ''))
            v['id'] = novo_id
            if novo_id and novo_id not in new_data:
                new_data[novo_id] = v
            modificados += 1
        else:
            new_data[k] = v

    print(f'Total modificados no {filepath}: {modificados}')
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(new_data, f, indent=4, ensure_ascii=False)

clean_lib('data/biblioteca_produtos.json')
clean_lib('data/biblioteca_unificada.json')
