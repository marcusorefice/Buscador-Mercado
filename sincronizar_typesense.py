import typesense
import json
import os

def sincronizar_com_typesense():
    print("Iniciando sincronização com o motor de buscas Typesense...")
    # 1. Conecta ao servidor Typesense usando a chave Admin
    client = typesense.Client({
        'nodes': [{
            'host': '34.16.54.234',
            'port': '8108',
            'protocol': 'http'
        }],
        'api_key': '***CHAVE_REMOVIDA***', 
        'connection_timeout_seconds': 30
    })

    # 2. Cria a "Tabela" (Coleção) para busca
    schema = {
        'name': 'produtos',
        'fields': [
            {'name': 'nome_comum', 'type': 'string'},
            {'name': 'marca', 'type': 'string', 'facet': True},
            {'name': 'tags', 'type': 'string[]', 'facet': True, 'optional': True}
        ]
    }

    try: client.collections['produtos'].delete()
    except: pass
    client.collections.create(schema)

    # 3. Lê o seu JSON Ouro e prepara os dados
    caminho = os.path.join(os.path.dirname(__file__), "data", "biblioteca_produtos.json")
    with open(caminho, 'r', encoding='utf-8') as f:
        biblioteca = json.load(f)

    documentos = []
    for ean, item in biblioteca.items():
        documentos.append({
            'id': ean, # EAN atua como ID único
            'nome_comum': item['nome_comum'],
            'marca': item.get('marca', 'OUTROS'),
            'tags': item.get('tags', [])
        })

    # 4. Envia tudo para a memória ultrarrápida do Typesense
    client.collections['produtos'].documents.import_(documentos, {'action': 'upsert'})
    print(f"✅ {len(documentos)} produtos sincronizados com o Typesense com sucesso!")

if __name__ == "__main__":
    sincronizar_com_typesense()