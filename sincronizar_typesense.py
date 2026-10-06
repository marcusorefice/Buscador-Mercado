import typesense
import json
import os
import time
from dotenv import load_dotenv

load_dotenv()

NOME_ALIAS = 'produtos'  # nome que o app usa na busca (collections/produtos/...)

def _criar_cliente():
    api_key = os.getenv("TYPESENSE_ADMIN_KEY")
    if not api_key:
        raise RuntimeError("TYPESENSE_ADMIN_KEY não definida no .env")
    return typesense.Client({
        'nodes': [{
            'host': os.getenv("TYPESENSE_HOST", "34.16.54.234"),
            'port': os.getenv("TYPESENSE_PORT", "8108"),
            'protocol': os.getenv("TYPESENSE_PROTOCOL", "http")
        }],
        'api_key': api_key,
        'connection_timeout_seconds': 30
    })

def _alias_atual(client):
    try:
        return client.aliases[NOME_ALIAS].retrieve().get('collection_name')
    except typesense.exceptions.ObjectNotFound:
        return None

def _eans_com_oferta():
    """EANs que têm oferta no banco agora. None se não der para consultar (aí indexa a biblioteca toda)."""
    url = os.getenv("DATABASE_URL")
    if not url:
        return None
    try:
        import psycopg2
        with psycopg2.connect(url) as conn, conn.cursor() as cur:
            cur.execute("SELECT DISTINCT ean FROM ofertas_atuais")
            return {r[0] for r in cur.fetchall()}
    except Exception as e:
        print(f"⚠️ Não foi possível ler as ofertas do banco ({e}); indexando a biblioteca inteira.")
        return None

def sincronizar_com_typesense():
    print("Iniciando sincronização com o motor de buscas Typesense...")
    # 1. Conecta ao servidor Typesense usando a chave Admin
    client = _criar_cliente()

    # 2. Cria uma coleção NOVA com nome versionado. A antiga continua respondendo
    #    as buscas do app até a troca do alias no final (sem tempo fora do ar).
    nova_colecao = f"{NOME_ALIAS}_{int(time.time())}"
    schema = {
        'name': nova_colecao,
        'fields': [
            {'name': 'nome_comum', 'type': 'string'},
            {'name': 'marca', 'type': 'string', 'facet': True},
            {'name': 'tags', 'type': 'string[]', 'facet': True, 'optional': True}
        ]
    }
    client.collections.create(schema)

    try:
        # 3. Lê o seu JSON Ouro e prepara os dados
        caminho = os.path.join(os.path.dirname(__file__), "data", "biblioteca_produtos.json")
        with open(caminho, 'r', encoding='utf-8') as f:
            biblioteca = json.load(f)

        # Só produtos que aparecem no app (têm oferta): senão o autocomplete sugere algo que a busca não acha
        com_oferta = _eans_com_oferta()
        documentos = []
        for ean, item in biblioteca.items():
            if com_oferta is not None and ean not in com_oferta:
                continue
            documentos.append({
                'id': ean, # EAN atua como ID único
                'nome_comum': item['nome_comum'],
                'marca': item.get('marca', 'OUTROS'),
                'tags': item.get('tags', [])
            })

        # 4. Envia tudo para a coleção nova
        resultados = client.collections[nova_colecao].documents.import_(documentos, {'action': 'upsert'})
        falhas = [r for r in resultados if not r.get('success')]
        if documentos and len(falhas) > len(documentos) * 0.05:
            raise RuntimeError(f"{len(falhas)} de {len(documentos)} documentos falharam. Exemplo: {falhas[0]}")
    except Exception:
        # Algo deu errado: descarta a coleção nova e mantém a antiga no ar
        client.collections[nova_colecao].delete()
        raise

    # 5. Aponta o alias para a coleção nova
    antiga = _alias_atual(client)
    if antiga is None:
        # Primeira execução com alias: existia uma coleção "de verdade" chamada 'produtos'.
        # Ela precisa sair para o alias poder usar esse nome (busca fica fora do ar só por um instante).
        try:
            client.collections[NOME_ALIAS].delete()
        except typesense.exceptions.ObjectNotFound:
            pass
    client.aliases.upsert(NOME_ALIAS, {'collection_name': nova_colecao})

    # 6. Apaga a coleção antiga
    if antiga and antiga != nova_colecao:
        try:
            client.collections[antiga].delete()
        except typesense.exceptions.ObjectNotFound:
            pass

    print(f"✅ {len(documentos) - len(falhas)} produtos sincronizados com o Typesense com sucesso! ({len(falhas)} falhas)")

if __name__ == "__main__":
    sincronizar_com_typesense()
