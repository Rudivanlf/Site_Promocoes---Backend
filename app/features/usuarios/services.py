# usuarios/services.py

"""
Serviços e lógica de negócio para o módulo de usuários.
Responsável por toda interação com o MongoDB e regras de autenticação.
"""

from typing import Optional, Dict, Any, List

from django.contrib.auth.hashers import make_password, check_password

from ..mongo import db
from ..utils import serialize_mongo, get_next_id


class UsuarioService:
    """Serviço para operações com usuários no MongoDB."""

    def __init__(self):
        self.collection = db["usuarios"]
        # Garante índice único no campo email para evitar duplicatas
        self.collection.create_index("email", unique=True, sparse=True)

    # ------------------------------------------------------------------
    # Leitura
    # ------------------------------------------------------------------

    def listar_usuarios(self, skip: int = 0, limit: int = 50) -> tuple[List[Dict], int]:
        """Lista usuários com paginação. Nunca retorna o campo senha_hash."""
        projection = {"senha_hash": 0}
        cursor = self.collection.find({}, projection).skip(skip).limit(limit)
        usuarios = [serialize_mongo(u) for u in cursor]
        total = self.collection.count_documents({})
        return usuarios, total

    def buscar_por_id(self, usuario_id: int) -> Optional[Dict[str, Any]]:
        """Busca um usuário pelo ID. Nunca retorna o campo senha_hash."""
        usuario = self.collection.find_one({"id": usuario_id}, {"senha_hash": 0})
        return serialize_mongo(usuario) if usuario else None

    def buscar_por_email(self, email: str) -> Optional[Dict[str, Any]]:
        """
        Busca um usuário pelo email (inclui senha_hash para validação interna).
        Uso exclusivo de autenticação — nunca exponha o resultado direto na API.
        """
        return self.collection.find_one({"email": email.strip().lower()})

    def email_ja_cadastrado(self, email: str) -> bool:
        """Verifica se um email já está em uso."""
        return self.collection.find_one({"email": email.strip().lower()}) is not None

    # ------------------------------------------------------------------
    # Escrita
    # ------------------------------------------------------------------

    def criar_usuario(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Cria um novo usuário com a senha hasheada.
        Garante que o email seja único antes de inserir.

        Raises:
            ValueError: se o email já estiver cadastrado.
        """
        email = data["email"].strip().lower()

        if self.email_ja_cadastrado(email):
            raise ValueError("Este email já está cadastrado")

        usuario = {
            "id": get_next_id("usuarios"),
            "email": email,
            "senha_hash": make_password(data["senha"]),  # hash seguro via Django
        }

        result = self.collection.insert_one(usuario)
        usuario["_id"] = result.inserted_id

        # Remove dados sensíveis antes de retornar
        doc = serialize_mongo(usuario)
        doc.pop("senha_hash", None)
        return doc

    def autenticar_usuario(self, email: str, senha: str) -> Optional[Dict[str, Any]]:
        """
        Verifica email e senha. Retorna o documento do usuário (sem senha_hash)
        se as credenciais forem válidas, ou None caso contrário.
        """
        usuario = self.buscar_por_email(email)
        if not usuario:
            return None

        if not check_password(senha, usuario.get("senha_hash", "")):
            return None

        # Retorna o documento sem o hash da senha
        doc = serialize_mongo(usuario)
        doc.pop("senha_hash", None)
        return doc

    def atualizar_usuario(self, usuario_id: int, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Atualiza campos permitidos de um usuário existente."""
        update_data: Dict[str, Any] = {}

        if "nome" in data:
            update_data["nome"] = data["nome"].strip()
        if "email" in data:
            novo_email = data["email"].strip().lower()
            if self.email_ja_cadastrado(novo_email):
                raise ValueError("Este email já está em uso por outro usuário")
            update_data["email"] = novo_email
        if "idade" in data:
            update_data["idade"] = int(data["idade"])
        if "telefone" in data:
            update_data["telefone"] = data["telefone"].strip()
        # Não permitimos atualização de senha por aqui (endpoint próprio)

        if not update_data:
            return self.buscar_por_id(usuario_id)

        result = self.collection.update_one(
            {"id": usuario_id},
            {"$set": update_data}
        )

        if result.matched_count == 0:
            return None

        return self.buscar_por_id(usuario_id)

    def deletar_usuario(self, usuario_id: int) -> bool:
        """Remove um usuário pelo ID."""
        result = self.collection.delete_one({"id": usuario_id})
        return result.deleted_count > 0

    def criar_ou_buscar_usuario_google(self, google_info: Dict[str, Any]) -> Dict[str, Any]:
        """
        Encontra ou cria um usuário a partir das informações validadas do Google.
        `google_info` deve conter: email, name (opcional), picture (opcional), sub (Google user ID).
        Nunca exige senha — contas Google não têm senha_hash.
        """
        email = google_info["email"].strip().lower()

        usuario = self.collection.find_one({"email": email})

        if usuario:
            # Atualiza campos do Google se ainda não existirem
            updates: Dict[str, Any] = {}
            if "google_id" not in usuario and google_info.get("sub"):
                updates["google_id"] = google_info["sub"]
            if "foto" not in usuario and google_info.get("picture"):
                updates["foto"] = google_info["picture"]
            if updates:
                self.collection.update_one({"email": email}, {"$set": updates})
        else:
            usuario = {
                "id": get_next_id("usuarios"),
                "email": email,
                "nome": google_info.get("name", ""),
                "foto": google_info.get("picture", ""),
                "google_id": google_info.get("sub", ""),
                # sem senha_hash — login exclusivamente via Google
            }
            result = self.collection.insert_one(usuario)
            usuario["_id"] = result.inserted_id

        doc = serialize_mongo(usuario)
        doc.pop("senha_hash", None)
        return doc
