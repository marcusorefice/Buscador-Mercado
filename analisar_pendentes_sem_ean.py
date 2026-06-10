import json
import os
from collections import defaultdict

ARQUIVO_PENDENTES = os.path.join(os.path.dirname(__file__), "data", "pendentes_ia.json")

def ean_eh_valido(ean_str):
    ean_str = str(ean_str).strip()
    if not ean_str.isdigit(): return False
    if len(ean_str) not in (8, 12, 13, 14): return False
    if len(set(ean_str)) == 1: return False
    if ean_str.startswith('0000000'): return False
    
    padded = ean_str.zfill(14)
    total = sum(int(padded[i]) * (3 if i % 2 == 0 else 1) for i in range(13))
    return str((10 - (total % 10)) % 10) == padded[13]

def main():
    if not os.path.exists(ARQUIVO_PENDENTES):
        print(f"❌ Arquivo não encontrado: {ARQUIVO_PENDENTES}")
        return

    try:
        with open(ARQUIVO_PENDENTES, "r", encoding="utf-8") as f:
            pendentes = json.load(f)
    except Exception as e:
        print(f"❌ Erro ao ler {ARQUIVO_PENDENTES}: {e}")
        return

    sem_ean_por_mercado = defaultdict(int)
    total_sem_ean = 0
    total_itens = len(pendentes)

    for item in pendentes:
        ean = str(item.get("EAN", item.get("ean", "N/A"))).strip()
        mercado = item.get("Mercado", "Desconhecido")
        
        # Considera "sem EAN" se for N/A, vazio, None, nan, ou se não for válido matematicamente.
        # O script 4_resolver_pendentes só tenta buscar na internet itens sem EAN,
        # ou seja, aqueles que ean_eh_valido retorna False e não começam com INT_.
        if ean in ("N/A", "", "None", "nan") or (not ean.startswith('INT_') and not ean_eh_valido(ean)):
            sem_ean_por_mercado[mercado] += 1
            total_sem_ean += 1
            
    print(f"\n[ANALISE] EANs Ausentes em {ARQUIVO_PENDENTES}\n")
    print(f"Total de itens pendentes: {total_itens}")
    print(f"Total de itens SEM EAN (que precisam de busca web): {total_sem_ean}\n")
    
    print("Detalhes por Mercado:")
    print("-" * 30)
    
    # Ordenar por quantidade decrescente
    mercados_ordenados = sorted(sem_ean_por_mercado.items(), key=lambda x: x[1], reverse=True)
    
    for mercado, qtd in mercados_ordenados:
        print(f"{mercado:<15}: {qtd} itens")
        
    print("-" * 30)

if __name__ == "__main__":
    main()
