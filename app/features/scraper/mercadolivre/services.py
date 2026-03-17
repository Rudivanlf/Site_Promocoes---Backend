import requests

ML_API_SEARCH_URL = "https://api.mercadolibre.com/sites/MLB/search"

def buscar_produtos_basic(query: str, pagina: int = 1) -> list[dict]:
    # O Mercado Livre traz 50 por padrão, mas mantivemos 48 para bater com o seu layout original
    limit = 48
    offset = (pagina - 1) * limit
    
    params = {
        "q": query,
        "limit": limit,
        "offset": offset
    }
    
    try:
        # A API oficial do ML não bloqueia IPs da Vercel/AWS e não exige CAPTCHA
        response = requests.get(ML_API_SEARCH_URL, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        raise ConnectionError(f"Erro ao acessar a API do Mercado Livre: {exc}") from exc
        
    produtos = []
    for item in data.get("results", []):
        preco_num = item.get("price")
        preco_original_num = item.get("original_price")
        
        # O seu frontend espera o formato string "123.45", então nós convertemos os números aqui
        preco_str = f"{preco_num:.2f}" if preco_num is not None else None
        preco_orig_str = f"{preco_original_num:.2f}" if preco_original_num is not None else None
        
        # Calcula o desconto automaticamente se houver preço original
        desconto_str = None
        if preco_num and preco_original_num and preco_num < preco_original_num:
            desconto_pct = round((1 - (preco_num / preco_original_num)) * 100)
            desconto_str = f"{desconto_pct}% OFF"
            
        # Pega a imagem e troca para qualidade alta (substituindo o sufixo -I por -O)
        imagem = item.get("thumbnail", "")
        if imagem:
            imagem = imagem.replace("-I.jpg", "-O.jpg").replace("-I.webp", "-O.webp")
            
        produto = {
            "titulo": item.get("title"),
            "preco": preco_str,
            "preco_original": preco_orig_str,
            "desconto": desconto_str,
            "imagem": imagem,
            "link": item.get("permalink"),
            "nota": None,  # A API de busca genérica não traz nota, usamos None para não quebrar o frontend
            "quantidade_avaliacoes": None,
        }
        produtos.append(produto)
        
    return produtos


def buscar_produtos(query: str, pagina: int = 1, detalhes: bool = False) -> list[dict]:
    """
    Na API oficial, o preço já vem exato nos centavos desde a primeira busca.
    Portanto, não precisamos mais varrer produto por produto abrindo as páginas.
    Isso economiza dezenas de requisições e evita punições por excesso de tráfego.
    """
    return buscar_produtos_basic(query, pagina)
