from datetime import datetime, timezone
from pymongo import MongoClient, ASCENDING
from urllib.parse import urlparse, urlunparse
import os

_client = None

def _get_collection():
    global _client
    if _client is None:
        uri = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
        _client = MongoClient(uri)
    db = _client[os.environ.get("MONGO_DB_NAME", "projectpromo")]
    return db["price_history"]

def ensure_indexes():
    col = _get_collection()
    col.create_index([("link", ASCENDING), ("recorded_at", ASCENDING)])

def _clean_link(link: str) -> str:
    """Remove parâmetros de tracking e hash do link do ML."""
    if not link:
        return ""
    if "click1.mercadolivre" in link or "/mclics/" in link:
        return ""
    try:
        parsed = urlparse(link)
        return urlunparse(parsed._replace(query="", fragment=""))
    except Exception:
        return link

def record_price(link: str, name: str, image: str, price: float):
    """Grava preço no histórico. Só insere se o preço mudou."""
    link = _clean_link(link)
    if not link or price is None:
        return

    col = _get_collection()
    last = col.find_one({"link": link}, sort=[("recorded_at", -1)])

    if last and float(last["price"]) == float(price):
        return  # preço não mudou, não duplica

    col.insert_one({
        "link": link,
        "name": name,
        "image": image,
        "price": float(price),
        "recorded_at": datetime.now(timezone.utc),
    })

def get_history_for_links(links: list) -> dict:
    """Retorna { link_limpo: [{ price, recorded_at }] }"""
    clean_map = {_clean_link(l): l for l in links if _clean_link(l)}
    clean_links = list(clean_map.keys())

    col = _get_collection()
    cursor = col.find(
        {"link": {"$in": clean_links}},
        {"_id": 0, "link": 1, "price": 1, "recorded_at": 1}
    ).sort("recorded_at", ASCENDING)

    result = {l: [] for l in links}
    for doc in cursor:
        original_link = clean_map.get(doc["link"])
        if original_link:
            result[original_link].append({
                "price": doc["price"],
                "recorded_at": doc["recorded_at"].isoformat(),
            })
    return result