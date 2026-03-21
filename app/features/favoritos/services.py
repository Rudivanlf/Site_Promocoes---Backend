# favoritos/services.py

"""
Serviços para o módulo de favoritos.
Toda interação com a coleção MongoDB 'favoritos'.
"""

import datetime
from typing import Optional, Dict, Any, List

from ..mongo import db
from ..utils import serialize_mongo, get_next_id


class FavoritoService:
    """Serviço para operações de favoritos no MongoDB."""

    def __init__(self):
        self.collection = db["favoritos"]
        # Índice único: um usuário não pode favoritar o mesmo link duas vezes
        self.collection.create_index(
            [("usuario_id", 1), ("produto_link", 1)],
            unique=True,
        )

    # ------------------------------------------------------------------
    # Leitura
    # ------------------------------------------------------------------

    def listar_favoritos(self, usuario_id: int) -> List[Dict[str, Any]]:
        """Retorna todos os favoritos do usuário, mapeados para o formato do frontend."""
        cursor = self.collection.find(
            {"usuario_id": usuario_id},
            {"_id": 0, "usuario_id": 0, "usuario_email": 0},
        ).sort("data_favoritado", -1)
        return [_para_formato_frontend(doc) for doc in cursor]

    def buscar(self, usuario_id: int, produto_link: str) -> Optional[Dict[str, Any]]:
        """Busca um favorito específico do usuário pelo link do produto."""
        return self.collection.find_one(
            {"usuario_id": usuario_id, "produto_link": produto_link}
        )

    # ------------------------------------------------------------------
    # Escrita
    # ------------------------------------------------------------------

    def adicionar(self, usuario_id: int, usuario_email: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Adiciona um produto aos favoritos do usuário.

        Raises:
            ValueError: se o produto já estiver favoritado.
        """
        if self.buscar(usuario_id, data["link"]):
            raise ValueError("Produto já está nos favoritos")

        doc = {
            "id": get_next_id("favoritos"),
            "usuario_id": usuario_id,
            "usuario_email": usuario_email,
            "produto_link": data["link"],
            "produto_nome": data["name"],
            "produto_preco": float(data["price"]),
            "produto_imagem": data.get("image", ""),
            "produto_descricao": data.get("description", ""),
            "produto_vendas": int(data.get("sales", 0)),
            "produto_categoria": data.get("category", ""),
            "produto_id": data.get("id"),
            "data_favoritado": datetime.datetime.now(datetime.timezone.utc),
            "ultima_verificacao_em": None,
            "proxima_verificacao_em": None,
            "ultima_verificacao_status": "pendente",
        }

        self.collection.insert_one(doc)
        return _para_formato_frontend(doc)

    def remover(self, usuario_id: int, produto_link: str) -> bool:
        """
        Remove um favorito do usuário.

        Returns:
            True se removido, False se não encontrado.
        """
        result = self.collection.delete_one(
            {"usuario_id": usuario_id, "produto_link": produto_link}
        )
        return result.deleted_count > 0


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

def _para_formato_frontend(doc: dict) -> dict:
    """
    Mapeia os nomes internos do MongoDB para os nomes esperados pelo frontend.
    produto_link → link, produto_nome → name, etc.
    """
    data_fav = doc.get("data_favoritado")
    if isinstance(data_fav, datetime.datetime):
        data_fav = data_fav.isoformat()

    return {
        "id": doc.get("id"),
        "link": doc.get("produto_link", ""),
        "name": doc.get("produto_nome", ""),
        "price": doc.get("produto_preco", 0),
        "image": doc.get("produto_imagem", ""),
        "description": doc.get("produto_descricao", ""),
        "sales": doc.get("produto_vendas", 0),
        "category": doc.get("produto_categoria", ""),
        "data_favoritado": data_fav,
    }
