# features/mongo.py

"""
Conexão centralizada com o MongoDB.
Carrega as credenciais do arquivo .env via python-dotenv.
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from pymongo import MongoClient

# Carrega o .env da raiz do projeto
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

_client: MongoClient | None = None


def get_client() -> MongoClient:
    """Retorna (ou cria) o cliente MongoDB singleton."""
    global _client
    if _client is None:
        mongo_uri = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
        _client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
    return _client


def get_db():
    """Retorna a instância do banco de dados configurado."""
    db_name = os.environ.get("MONGO_DB_NAME") or "site_promocoes_db"
    return get_client()[db_name]


# Atalho utilizado pelos módulos de features
db = get_db()

