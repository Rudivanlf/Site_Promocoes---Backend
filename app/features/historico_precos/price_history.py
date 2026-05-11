from datetime import datetime, timedelta, timezone
from pymongo import ASCENDING
from urllib.parse import parse_qs, unquote, urlparse, urlunparse
import hashlib
import os
import random
import re

from app.features.mongo import db

_FAKE_SOURCE = "fake"
_FAKE_VERSION = 3
_MIN_POINTS = 6
_INDEXES_READY = False

def _get_int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default

def _get_float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default

FAKE_POINTS = max(_MIN_POINTS, _get_int_env("FAKE_HISTORY_POINTS", 16))
FAKE_DAYS = max(7, _get_int_env("FAKE_HISTORY_DAYS", 30))
FAKE_MIN_FACTOR = _get_float_env("FAKE_HISTORY_MIN_FACTOR", 0.85)
FAKE_MAX_FACTOR = _get_float_env("FAKE_HISTORY_MAX_FACTOR", 1.15)
FAKE_STEP_NOISE = _get_float_env("FAKE_HISTORY_STEP_NOISE", 0.015)

if FAKE_MIN_FACTOR <= 0:
    FAKE_MIN_FACTOR = 0.85
if FAKE_MAX_FACTOR <= FAKE_MIN_FACTOR:
    FAKE_MAX_FACTOR = FAKE_MIN_FACTOR + 0.2
if FAKE_STEP_NOISE <= 0:
    FAKE_STEP_NOISE = 0.015

def _get_collection():
    global _INDEXES_READY
    col = db["price_history"]
    if not _INDEXES_READY:
        col.create_index([("link", ASCENDING), ("recorded_at", ASCENDING)])
        col.create_index([("link", ASCENDING), ("source", ASCENDING), ("version", ASCENDING)])
        _INDEXES_READY = True
    return col

def _clean_link(link: str, depth: int = 0) -> str:
    """Normaliza o link para facilitar o match entre favoritos e historico."""
    if not link:
        return ""
    raw = link.strip()
    if depth > 2:
        return raw
    try:
        parsed = urlparse(raw)
        if not parsed.netloc and "://" not in raw:
            parsed = urlparse(f"https://{raw}")

        netloc_lower = parsed.netloc.lower()
        path_lower = parsed.path.lower()
        if "mercadolivre" in netloc_lower and (
            "click" in netloc_lower or "/mclics/" in path_lower or "/clicks" in path_lower
        ):
            embedded = _extract_embedded_url(parsed)
            if embedded and embedded != raw:
                return _clean_link(embedded, depth + 1)
            if parsed.fragment:
                return urlunparse(parsed._replace(fragment=""))
            return raw

        scheme = parsed.scheme.lower() if parsed.scheme else "https"
        netloc = parsed.netloc.lower().replace("www.", "")
        path = parsed.path.rstrip("/")
        cleaned = urlunparse((scheme, netloc, path, "", ""))
        return cleaned or raw
    except Exception:
        return raw

def _extract_embedded_url(parsed) -> str:
    if not parsed.query:
        return ""
    qs = parse_qs(parsed.query)
    for key in ("url", "u", "redirect", "redir", "target"):
        value = qs.get(key)
        if not value:
            continue
        candidate = unquote(value[0])
        if candidate.startswith("http://") or candidate.startswith("https://"):
            return candidate
    return ""

def _extract_ml_item_id(link: str) -> str | None:
    match = re.search(r"(MLB-\d+)", link, re.IGNORECASE)
    if match:
        return match.group(1)
    return None
def _safe_price(value) -> float | None:
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    if price <= 0:
        return None
    return price

def _seed_for_link(link: str, price: float) -> int:
    seed_input = f"{link}|{price:.2f}".encode("utf-8")
    return int(hashlib.md5(seed_input).hexdigest()[:8], 16)

def _has_valid_fake_history(col, link: str) -> bool:
    count = col.count_documents({
        "link": link,
        "source": _FAKE_SOURCE,
        "version": _FAKE_VERSION,
    })
    return count >= _MIN_POINTS

def _build_fake_history(
    link: str,
    name: str,
    image: str,
    base_price: float,
    points: int,
    days: int,
):
    rng = random.Random(_seed_for_link(link, base_price))

    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    total_seconds = max(1, int((now - start).total_seconds()))

    min_price = base_price * FAKE_MIN_FACTOR
    max_price = base_price * FAKE_MAX_FACTOR

    records = []
    steps = max(1, points - 1)
    anchor_count = max(3, min(6, steps // 3))
    anchor_positions = {0, steps}
    if steps > 2 and anchor_count > 2:
        extra = min(anchor_count - 2, max(0, steps - 1))
        anchor_positions.update(rng.sample(range(1, steps), extra))
    anchor_positions = sorted(anchor_positions)

    drift = base_price * rng.uniform(-0.05, 0.05)
    anchor_prices = []
    for pos in anchor_positions:
        progress = pos / max(1, steps)
        baseline = base_price + drift * (progress - 0.5)
        jitter = base_price * rng.uniform(-0.03, 0.03)
        price = max(min_price, min(max_price, baseline + jitter))
        anchor_prices.append(price)

    promo_map = {}
    if steps >= 6 and rng.random() < 0.45:
        promo_length = rng.randint(1, min(3, steps - 2))
        promo_start = rng.randint(1, steps - promo_length - 1)
        promo_depth = rng.uniform(0.04, 0.12)
        mid = (promo_length - 1) / 2.0
        for j in range(promo_length):
            if promo_length == 1:
                intensity = 1.0
            else:
                intensity = 1.0 - (abs(j - mid) / (mid + 1))
            promo_map[promo_start + j] = promo_depth * intensity

    anchor_idx = 0
    for i in range(steps):
        while anchor_idx < len(anchor_positions) - 2 and i > anchor_positions[anchor_idx + 1]:
            anchor_idx += 1

        left_pos = anchor_positions[anchor_idx]
        right_pos = anchor_positions[anchor_idx + 1]
        left_price = anchor_prices[anchor_idx]
        right_price = anchor_prices[anchor_idx + 1]

        if right_pos == left_pos:
            base = left_price
        else:
            t = (i - left_pos) / (right_pos - left_pos)
            base = left_price + (right_price - left_price) * t

        noise = rng.uniform(-FAKE_STEP_NOISE, FAKE_STEP_NOISE) * base_price
        current = max(min_price, min(max_price, base + noise))

        promo = promo_map.get(i)
        if promo:
            current = max(min_price, current * (1.0 - promo))

        progress = i / max(1, steps)
        recorded_at = start + timedelta(seconds=int(total_seconds * progress))
        records.append({
            "link": link,
            "name": name,
            "image": image,
            "price": float(round(current, 2)),
            "recorded_at": recorded_at,
            "source": _FAKE_SOURCE,
            "version": _FAKE_VERSION,
        })

    records.append({
        "link": link,
        "name": name,
        "image": image,
        "price": float(round(base_price, 2)),
        "recorded_at": now,
        "source": _FAKE_SOURCE,
        "version": _FAKE_VERSION,
    })
    return records

def ensure_fake_history_for_link(
    link: str,
    name: str,
    image: str,
    price: float,
    points: int | None = None,
    days: int | None = None,
):
    link = _clean_link(link)
    if not link:
        return

    base_price = _safe_price(price)
    if base_price is None:
        return

    col = _get_collection()
    if _has_valid_fake_history(col, link):
        return

    col.delete_many({"link": link})

    final_points = max(_MIN_POINTS, points or FAKE_POINTS)
    final_days = max(7, days or FAKE_DAYS)
    records = _build_fake_history(
        link=link,
        name=name,
        image=image,
        base_price=base_price,
        points=final_points,
        days=final_days,
    )
    if records:
        col.insert_many(records)

def _get_favorites_for_links(links: list) -> dict:
    col = db["favoritos"]
    candidates = []
    for link in links:
        if not link:
            continue
        candidates.append(link)
        cleaned = _clean_link(link)
        if cleaned and cleaned != link:
            candidates.append(cleaned)

    if not candidates:
        return {}

    cursor = col.find(
        {"produto_link": {"$in": list(set(candidates))}},
        {
            "_id": 0,
            "produto_link": 1,
            "produto_nome": 1,
            "produto_imagem": 1,
            "produto_preco": 1,
            "produto_preco_alvo": 1,
        },
    )

    result = {}
    for doc in cursor:
        clean = _clean_link(doc.get("produto_link", ""))
        if clean and clean not in result:
            result[clean] = doc

    missing = [c for c in {_clean_link(l) for l in links if _clean_link(l)} if c and c not in result]
    if missing:
        for clean_link in missing:
            item_id = _extract_ml_item_id(clean_link)
            if not item_id:
                continue
            regex = re.compile(re.escape(item_id), re.IGNORECASE)
            cursor = col.find(
                {"produto_link": {"$regex": regex}},
                {
                    "_id": 0,
                    "produto_link": 1,
                    "produto_nome": 1,
                    "produto_imagem": 1,
                    "produto_preco": 1,
                    "produto_preco_alvo": 1,
                },
            )
            for doc in cursor:
                clean = _clean_link(doc.get("produto_link", ""))
                if clean and clean not in result:
                    result[clean] = doc
    return result

def get_history_for_links(links: list) -> dict:
    """Retorna { link_original: [{ price, recorded_at }] } usando historico fake."""
    clean_map = {_clean_link(l): l for l in links if _clean_link(l)}
    clean_links = list(clean_map.keys())

    result = {l: [] for l in links}
    if not clean_links:
        return result

    fav_map = _get_favorites_for_links(links)
    for clean_link in clean_links:
        fav = fav_map.get(clean_link)
        if not fav:
            continue
        base_price = _safe_price(fav.get("produto_preco"))
        if base_price is None:
            base_price = _safe_price(fav.get("produto_preco_alvo"))
        ensure_fake_history_for_link(
            link=clean_link,
            name=fav.get("produto_nome", ""),
            image=fav.get("produto_imagem", ""),
            price=base_price or 0,
        )

    col = _get_collection()
    cursor = col.find(
        {
            "link": {"$in": clean_links},
            "source": _FAKE_SOURCE,
            "version": _FAKE_VERSION,
        },
        {"_id": 0, "link": 1, "price": 1, "recorded_at": 1},
    ).sort("recorded_at", ASCENDING)

    for doc in cursor:
        original_link = clean_map.get(doc.get("link"))
        if not original_link:
            continue
        recorded_at = doc.get("recorded_at")
        if isinstance(recorded_at, datetime):
            recorded_at = recorded_at.isoformat()
        result[original_link].append({
            "price": doc.get("price"),
            "recorded_at": recorded_at,
        })

    return result