# usuarios/models.py

"""
Modelos e schemas para o módulo de usuários.
Define a estrutura dos documentos de usuários no MongoDB.
"""

from typing import TypedDict
import re


class UsuarioSchema(TypedDict):
    """Schema do documento Usuario no MongoDB."""
    id: int
    email: str
    senha_hash: str  # nunca armazenamos a senha em texto puro


def validate_usuario_data(data: dict) -> tuple[bool, list[str]]:
    """
    Valida os dados de criação de um usuário.

    Returns:
        Tupla (is_valid, errors).
    """
    errors = []

    # Email
    if not data.get("email"):
        errors.append("Email é obrigatório")
    elif not isinstance(data["email"], str):
        errors.append("Email deve ser uma string")
    else:
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, data["email"]):
            errors.append("Email inválido")

    # Senha
    if not data.get("senha"):
        errors.append("Senha é obrigatória")
    elif not isinstance(data["senha"], str):
        errors.append("Senha deve ser uma string")
    elif len(data["senha"]) < 8:
        errors.append("Senha deve ter pelo menos 8 caracteres")

    return (len(errors) == 0, errors)


def validate_login_data(data: dict) -> tuple[bool, list[str]]:
    """
    Valida os dados de login (email + senha).

    Returns:
        Tupla (is_valid, errors).
    """
    errors = []

    if not data.get("email"):
        errors.append("Email é obrigatório")
    else:
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, data["email"]):
            errors.append("Email inválido")

    if not data.get("senha"):
        errors.append("Senha é obrigatória")

    return (len(errors) == 0, errors)
