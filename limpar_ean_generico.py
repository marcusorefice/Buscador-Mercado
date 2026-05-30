import json
import os

bib_path = os.path.join('data', 'biblioteca_produtos.json')

try:
    if not os.path.exists(bib_path):
        print(f"Erro: Arquivo não encontrado em {bib_path}")
    else:
        with open(bib_path, 'r', encoding='utf-8') as f:
            bib = json.load(f)
            
        bib_limpa = {k: v for k, v in bib.items() if not str(k).startswith('INT_')}
        
        with open(bib_path, 'w', encoding='utf-8') as f:
            json.dump(bib_limpa, f, indent=4, ensure_ascii=False)
            
        print(f"✅ Limpeza concluída! {len(bib) - len(bib_limpa)} produtos 'INT_' foram apagados da base Ouro.")
        print("👉 Agora rode sua esteira ou o '4_resolver_pendentes.py' novamente para ele buscar o EAN real deles!")
except Exception as e:
    print(f"Erro: {e}")