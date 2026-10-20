"""Google Places (New) — interface pronta, inativa sem GOOGLE_MAPS_API_KEY (variável de ambiente, só no servidor).

NÃO TESTADO contra a API real: não há chave/faturamento neste ambiente.
ToS Google: resultados não são persistidos nem misturados às bases próprias (pois_osm.gpkg); só place_id pode ser guardado.
Exibição em mapa Google exige atribuição do Google; sobre mapa OSM, não exiba estes pontos.
"""
import os

import httpx

URL = "https://places.googleapis.com/v1/places:searchNearby"
CAMPOS = "places.id,places.displayName,places.location,places.primaryType"


def configurado() -> bool:
    return bool(os.environ.get("GOOGLE_MAPS_API_KEY"))


def buscar_proximos(lat: float, lon: float, raio_m: float, tipos: list[str]) -> list[dict]:
    """Nearby Search; `tipos` = tipos Google (ex.: ["pharmacy"]). Retorna lista só para uso na sessão."""
    if not configurado():
        raise RuntimeError("GOOGLE_MAPS_API_KEY ausente: integração Google Places aguardando credenciais")
    body = {"includedTypes": tipos, "maxResultCount": 20,
            "locationRestriction": {"circle": {"center": {"latitude": lat, "longitude": lon}, "radius": raio_m}}}
    r = httpx.post(URL, json=body, timeout=30,
                   headers={"X-Goog-Api-Key": os.environ["GOOGLE_MAPS_API_KEY"], "X-Goog-FieldMask": CAMPOS})
    r.raise_for_status()
    return r.json().get("places", [])
