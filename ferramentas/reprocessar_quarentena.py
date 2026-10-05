import os, sys
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # raiz do projeto (D:\Mercado)
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)  # caminhos como 'data/...' continuam funcionando de qualquer pasta

import json
import os

DATA_DIR = os.path.join(RAIZ, "data")
ARQUIVO_PENDENTES = os.path.join(DATA_DIR, "pendentes_ia.json")
ARQUIVO_QUARENTENA = os.path.join(DATA_DIR, "quarentena_anomalias.json")

def main():
    if not os.path.exists(ARQUIVO_QUARENTENA):
        print("❌ Arquivo quarentena_anomalias.json não encontrado.")
        return

    with open(ARQUIVO_QUARENTENA, "r", encoding="utf-8") as f:
        quarentena = json.load(f)

    if not quarentena:
        print("ℹ️ A quarentena já está vazia. Nenhum item para mover.")
        return

    pendentes = []
    if os.path.exists(ARQUIVO_PENDENTES):
        with open(ARQUIVO_PENDENTES, "r", encoding="utf-8") as f:
            pendentes = json.load(f)

    itens_movidos = 0
    nova_quarentena = []

    for item in quarentena:
        ean = str(item.get("EAN", ""))
        if ean.startswith("INT_"):
            item["EAN"] = "N/A"
            if "Fonte_EAN" in item:
                del item["Fonte_EAN"]
            pendentes.append(item)
            itens_movidos += 1
        else:
            nova_quarentena.append(item)

    with open(ARQUIVO_PENDENTES, "w", encoding="utf-8") as f:
        json.dump(pendentes, f, ensure_ascii=False, indent=4)
    with open(ARQUIVO_QUARENTENA, "w", encoding="utf-8") as f:
        json.dump(nova_quarentena, f, ensure_ascii=False, indent=4)

    print(f"✅ {itens_movidos} itens com ID 'INT_' foram resetados e movidos para a fila de pendentes!")
    print("🚀 Agora você pode rodar 'python 4_resolver_pendentes.py' para reprocessá-los com as novas regras.")

if __name__ == "__main__":
    main()