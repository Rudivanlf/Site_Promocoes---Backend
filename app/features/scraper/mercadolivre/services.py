import requests

ML_API_SEARCH_URL = "https://api.mercadolibre.com/sites/MLB/search"

# O disfarce perfeito para passar pelo Firewall (Erro 403)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json"
}

def buscar_produtos_basic(query: str, pagina: int = 1) -> list[dict]:
    limit = 48
    offset = (pagina - 1) * limit
    
    params = {
        "q": query,
        "limit": limit,
        "offset": offset
    }
    
    try:
        # Passamos o disfarce (headers) aqui na requisição!
        response = requests.get(ML_API_SEARCH_URL, params=params, headers=HEADERS, timeout=15)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        raise ConnectionError(f"Erro ao acessar a API do Mercado Livre: {exc}") from exc
        
    produtos = []
    for item in data.get("results", []):
        preco_num = item.get("price")
        preco_original_num = item.get("original_price")
        
        preco_str = f"{preco_num:.2f}" if preco_num is not None else None
        preco_orig_str = f"{preco_original_num:.2f}" if preco_original_num is not None else None
        
        desconto_str = None
        if preco_num and preco_original_num and preco_num < preco_original_num:
            desconto_pct = round((1 - (preco_num / preco_original_num)) * 100)
            desconto_str = f"{desconto_pct}% OFF"
            
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
            "nota": None,
            "quantidade_avaliacoes": None,
        }
        produtos.append(produto)
        
    return produtos

def buscar_produtos(query: str, pagina: int = 1, detalhes: bool = False) -> list[dict]:
    return buscar_produtos_basic(query, pagina)
