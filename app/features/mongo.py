# features/mongo.py

"""
Conexão centralizada com o MongoDB.
Carrega as credenciais do arquivo .env via python-dotenv.
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from pymongo import MongoClient, errors

# Carrega o .env da raiz do projeto
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

_client: MongoClient | None = None


def get_client() -> MongoClient:
    """Retorna (ou cria) o cliente MongoDB singleton."""
    global _client
    if _client is None:
        mongo_uri = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
        print(f"Connecting to MongoDB at: {mongo_uri}")
        _client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
    return _client


def get_db():
    """Retorna a instância do banco de dados configurado."""
    db_name = os.environ.get("MONGO_DB_NAME") or "site_promocoes_db"
    client = get_client()
    try:
        # Check connection status
        client.admin.command('ping')
    except errors.ServerSelectionTimeoutError as e:
        print(f"CRITICAL ERROR: Failed to connect to MongoDB ({e}).")
        print("Please ensure your MongoDB instance is running locally or configured correctly in .env via MONGO_URI.")
        # If we are in a script or management command, we might want to exit
        # For a running server, it's better to let individual calls handle the failure
        # For now, we print a clear warning.
    return client[db_name]


# Atalho utilizado pelos módulos de features
db = get_db()

