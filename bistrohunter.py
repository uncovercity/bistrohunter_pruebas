#IMPORTS
import os
from typing import Optional, List
from fastapi import FastAPI, Query, HTTPException, Request
from datetime import datetime
import requests
import logging
from functools import wraps
from cachetools import TTLCache
from math import radians, cos, sin, asin, sqrt

#Desplegar fast api (no tocar)
app = FastAPI()

#Configuración del logging (nos va a decir dónde están los fallos)
logging.basicConfig(level=logging.INFO)

#Secretos. Esto son urls, claves, tokens y demás que no deben mostrarse públicamente ni subirse a ningún sitio
BASE_ID = os.getenv('BASE_ID')
AIRTABLE_PAT = os.getenv('AIRTABLE_PAT')
GOOGLE_MAPS_API_KEY = os.getenv('GOOGLE_MAPS_API_KEY')
N8N_WEBHOOK_URL = os.getenv('N8N_WEBHOOK_URL')

DAYS_ES = {
    "Monday": "lunes",
    "Tuesday": "martes",
    "Wednesday": "miércoles",
    "Thursday": "jueves",
    "Friday": "viernes",
    "Saturday": "sábado",
    "Sunday": "domingo"
}

#Función que obtiene la fecha actual, obtiene el día de la semana que corresponde a esa fecha y cambia el día al español
def obtener_dia_semana(fecha: datetime) -> str:
    try:
        dia_semana_en = fecha.strftime('%A')  
        dia_semana_es = DAYS_ES.get(dia_semana_en, dia_semana_en)  
        return dia_semana_es.lower()
    except Exception as e:
        logging.error(f"Error al obtener el día de la semana: {e}")
        raise HTTPException(status_code=500, detail="Error al procesar la fecha")

#Calcula la distancia haversiana entre dos puntos (filtro de zona)
def haversine(lon1, lat1, lon2, lat2):
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
    dlon = lon2 - lon1 
    dlat = lat2 - lat1 
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a)) 
    km = 6367 * c
    return km

#Función que obtiene las coordenadas de la zona que ha especificado el cliente
def obtener_coordenadas(zona: str, ciudad: str) -> Optional[dict]:
    try:
        url = f"https://maps.googleapis.com/maps/api/geocode/json"
        params = {
            "address": f"{zona}, {ciudad}",
            "key": GOOGLE_MAPS_API_KEY
        }
        response = requests.get(url, params=params)
        data = response.json()
        if data['status'] == 'OK':
            location = data['results'][0]['geometry']['location']
            return location
        else:
            logging.error(f"Error en la geocodificación: {data['status']}")
            return None
    except Exception as e:
        logging.error(f"Error al obtener coordenadas de la zona: {e}")
        return None

#Caché (no tocar)
restaurantes_cache = TTLCache(maxsize=10000, ttl=60*30)

def cache_airtable_request(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        cache_key = f"{func.__name__}:{args}:{kwargs}"
        if cache_key in restaurantes_cache:
            return restaurantes_cache[cache_key]
        result = func(*args, **kwargs)
        restaurantes_cache[cache_key] = result
        return result
    return wrapper

@cache_airtable_request

#Función que realiza la petición a la API de Airtable
def airtable_request(url, headers, params, view_id: Optional[str] = None):
    if view_id:
        params["view"] = view_id
    response = requests.get(url, headers=headers, params=params)
    return response.json() if response.status_code == 200 else None

@cache_airtable_request

#Función que establece límites geográficos en los que se va a buscar (2 km, 4 km, 6 km, etc.)
def obtener_limites_geograficos(lat: float, lon: float, distancia_km: float = 2.0) -> dict:
    lat_delta = distancia_km / 111.0
    lon_delta = distancia_km / (111.0 * cos(radians(lat)))
    
    return {
        "lat_min": lat - lat_delta,
        "lat_max": lat + lat_delta,
        "lon_min": lon - lon_delta,
        "lon_max": lon + lon_delta
    }

@cache_airtable_request

# Función que toma las variables que le ha dado el asistente de IA para hacer la llamada a la API de Airtable con una serie de condiciones
def obtener_restaurantes_varias_zonas(
    city: str, 
    zonas: List[str],  # Lista de zonas especificadas por el cliente
    dia_semana: Optional[str] = None, 
    price_range: Optional[str] = None,
    cocina: Optional[str] = None,
    diet: Optional[str] = None,
    dish: Optional[str] = None,
    sort_by_proximity: bool = True
) -> List[dict]:
    try:
        todos_restaurantes = []
        
        for zona in zonas:
            # Realizamos la búsqueda en cada zona
            restaurantes_en_zona, _ = obtener_restaurantes_por_ciudad(
                city=city,
                dia_semana=dia_semana,
                price_range=price_range,
                cocina=cocina,
                diet=diet,
                dish=dish,
                zona=zona,
                sort_by_proximity=sort_by_proximity
            )
            todos_restaurantes.extend(restaurantes_en_zona)

        # Eliminar duplicados basándonos en algún identificador único (ej. 'cid')
        restaurantes_unicos = {r['fields']['cid']: r for r in todos_restaurantes}.values()

        # Ordenar por un criterio, por ejemplo, proximidad o puntuación
        restaurantes_ordenados = sorted(
            restaurantes_unicos,
            key=lambda r: r['fields'].get('NBH2', 0),  # Ordenar por puntuación NBH2 como ejemplo
            reverse=True
        )

        # Seleccionar los 10 mejores
        top_10_restaurantes = list(restaurantes_ordenados)[:10]

        # Seleccionar los 3 mejores para la respuesta final
        top_3_restaurantes = top_10_restaurantes[:3]

        return top_3_restaurantes

    except Exception as e:
        logging.error(f"Error al obtener restaurantes en múltiples zonas: {e}")
        raise HTTPException(status_code=500, detail="Error al obtener restaurantes en múltiples zonas")

    
@app.post("/procesar-variables")

#Esta es la función que convierte los datos que ha extraído el agente de IA en las variables que usa la función obtener_restaurantes y luego llama a esta misma función y extrae y ofrece los resultados
async def procesar_variables(request: Request):
    try:
        data = await request.json()
        logging.info(f"Datos recibidos: {data}")
        
        city = data.get('city')
        date = data.get('date')
        price_range = data.get('price_range')
        cocina = data.get('cocina')
        diet = data.get('diet')
        dish = data.get('dish')
        zona = data.get('zona')

        if not city:
            raise HTTPException(status_code=400, detail="La variable 'city' es obligatoria.")

        dia_semana = None
        if date:
            try:
                fecha = datetime.strptime(date, "%Y-%m-%d")
                dia_semana = obtener_dia_semana(fecha)
            except ValueError:
                raise HTTPException(status_code=400, detail="La fecha proporcionada no tiene el formato correcto (YYYY-MM-DD).")

        # Llama a la función obtener_restaurantes_por_ciudad y construye la filter_formula
        restaurantes, filter_formula = obtener_restaurantes_por_ciudad(
            city=city,
            dia_semana=dia_semana,
            price_range=price_range,
            cocina=cocina,
            diet=diet,
            dish=dish,
            zona=zona
        )

        # Capturar la URL completa y los parámetros de la solicitud
        full_url = str(request.url)
        request_method = request.method

        # Capturar la información del request
        http_request_info = f'{request_method} {full_url} HTTP/1.1 200 OK'
        
        # Si no se encontraron restaurantes, devolver el mensaje y el request_info
        if not restaurantes:
            return {
                "request_info": http_request_info,
                "variables": {
                    "city": city,
                    "zone": zona,
                    "cuisine_type": cocina,
                    "price_range": price_range,
                    "date": date,
                    "alimentary_restrictions": diet,
                    "specific_dishes": dish
                },
                "mensaje": "No se encontraron restaurantes con los filtros aplicados."
            }
        
        # Procesar los restaurantes
        resultados = [
            {
                "cid": restaurante['fields'].get('cid'),
                "titulo": restaurante['fields'].get('title', 'Sin título'),
                "descripcion": restaurante['fields'].get('bh_message', 'Sin descripción'),
                "rango_de_precios": restaurante['fields'].get('price_range', 'No especificado'),
                "url": restaurante['fields'].get('url', 'No especificado'),
                "puntuacion_bistrohunter": restaurante['fields'].get('NBH2', 'N/A')
            }
            for restaurante in restaurantes
        ]
        
        # Devolver los resultados junto con el log de la petición HTTP
        return {
            "request_info": http_request_info,
            "variables": {
                "city": city,
                "zone": zona,
                "cuisine_type": cocina,
                "price_range": price_range,
                "date": date,
                "alimentary_restrictions": diet,
                "specific_dishes": dish
            },
            "resultados": resultados
        }
    
    except Exception as e:
        logging.error(f"Error al procesar variables: {e}")
        return {"error": "Ocurrió un error al procesar las variables"}
