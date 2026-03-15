# features/utils.py

"""
Utilitários compartilhados entre os módulos de features.
"""

import json
import jwt as pyjwt
from django.conf import settings
from django.http import JsonResponse
from bson import ObjectId
from .mongo import db


def serialize_mongo(document: dict) -> dict:
    """
    Converte um documento do MongoDB em dicionário serializável em JSON.
    Transforma ObjectId em string e remove o campo interno '_id'.
    """
    if document is None:
        return {}

    result = {}
    for key, value in document.items():
        if key == "_id":
            continue  # nunca expõe o _id interno do MongoDB
        if isinstance(value, ObjectId):
            result[key] = str(value)
        elif isinstance(value, dict):
            result[key] = serialize_mongo(value)
        elif isinstance(value, list):
            result[key] = [
                serialize_mongo(item) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            result[key] = value

    return result


def get_next_id(collection_name: str) -> int:
    """
    Gera um ID sequencial para a coleção informada usando um contador atômico.
    Utiliza a coleção '_counters' do MongoDB para garantir unicidade.
    """
    counters = db["_counters"]
    result = counters.find_one_and_update(
        {"_id": collection_name},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=True,
    )
    return result["seq"]


def parse_request_body(request) -> tuple[dict, str | None]:
    """
    Faz o parse do corpo da requisição como JSON.

    Returns:
        Tupla (data, error): data é o dict parseado, error é a mensagem de erro
        ou None se tudo ocorreu bem.
    """
    try:
        body = request.body
        if not body:
            return {}, "Corpo da requisição está vazio"
        data = json.loads(body)
        if not isinstance(data, dict):
            return {}, "O corpo da requisição deve ser um objeto JSON"
        return data, None
    except json.JSONDecodeError:
        return {}, "JSON inválido no corpo da requisição"


def autenticar_jwt(request) -> tuple[dict | None, JsonResponse | None]:
    """
    Valida o token JWT do header Authorization: Bearer {token}.

    Returns:
        (payload, None) se válido.
        (None, JsonResponse 401) se inválido ou ausente.
    """
    auth_header = request.META.get("HTTP_AUTHORIZATION", "")
    if not auth_header.startswith("Bearer "):
        return None, JsonResponse(
            {"error": "Token inválido ou ausente"}, status=401
        )

    token = auth_header.split(" ", 1)[1].strip()
    try:
        payload = pyjwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        return payload, None
    except pyjwt.ExpiredSignatureError:
        return None, JsonResponse({"error": "Token expirado"}, status=401)
    except pyjwt.InvalidTokenError:
        return None, JsonResponse({"error": "Token inválido"}, status=401)
