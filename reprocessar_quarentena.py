import json
import os

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
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

    for item in quarentena:
        item["EAN"] = "N/A"
        if "Fonte_EAN" in item:
            del item["Fonte_EAN"]
        pendentes.append(item)

    with open(ARQUIVO_PENDENTES, "w", encoding="utf-8") as f:
        json.dump(pendentes, f, ensure_ascii=False, indent=4)
    with open(ARQUIVO_QUARENTENA, "w", encoding="utf-8") as f:
        json.dump([], f, ensure_ascii=False, indent=4)

    print(f"✅ {len(quarentena)} itens movidos da quarentena para os pendentes!")
    print("🚀 Agora você pode rodar 'python 4_resolver_pendentes.py' novamente.")

if __name__ == "__main__":
    main()