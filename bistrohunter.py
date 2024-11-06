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
def obtener_restaurantes_por_ciudad(
    city: str, 
    dia_semana: Optional[str] = None, 
    price_range: Optional[str] = None,
    cocina: Optional[str] = None,
    diet: Optional[str] = None,
    dish: Optional[str] = None,
    zona: Optional[str] = None,
    sort_by_proximity: bool = True  # Nuevo parámetro para ordenar por proximidad
) -> (List[dict], str):
    try:
        table_name = 'Restaurantes DB'
        url = f"https://api.airtable.com/v0/{BASE_ID}/{table_name}"
        headers = {
            "Authorization": f"Bearer {AIRTABLE_PAT}",
        }

        # Inicializamos la fórmula de búsqueda
        formula_parts = []

        if dia_semana:
            formula_parts.append(f"FIND('{dia_semana}', ARRAYJOIN({{day_opened}}, ', ')) > 0")

        if price_range:
            formula_parts.append(f"FIND('{price_range}', ARRAYJOIN({{price_range}}, ', ')) > 0")

        if cocina:
            formula_parts.append(f"FIND(LOWER('{cocina}'), LOWER({{comida_[TESTING]}})) > 0")

        if diet:
            formula_parts.append(f"FIND(LOWER('{diet}'), LOWER({{comida_[TESTING]}})) > 0")
        
        if dish:
            formula_parts.append(f"FIND(LOWER('{dish}'), LOWER(ARRAYJOIN({{comida_[TESTING]}}, ', '))) > 0")

        # Lista para almacenar todos los restaurantes encontrados
        restaurantes_encontrados = []
        filter_formula = None  # Inicializamos filter_formula

        # Si se especifica zona
        if zona:
            # Verificamos si zona contiene múltiples zonas separadas por comas
            if ',' in zona:
                # Dividimos zona en una lista de zonas
                zonas_list = [z.strip() for z in zona.split(',')]
            else:
                zonas_list = [zona]

            # Iteramos sobre cada zona en la lista
            for zona_item in zonas_list:
                # Obtenemos las coordenadas de la zona
                location_zona = obtener_coordenadas(zona_item, city)
                if not location_zona:
                    logging.error(f"Zona '{zona_item}' no encontrada.")
                    continue  # Saltamos a la siguiente zona si no se encuentra

                lat_centro = location_zona['lat']
                lon_centro = location_zona['lng']

                # Realizamos la búsqueda para esta zona
                distancia_km = 1.0  # Comenzamos con un radio pequeño, 1 km
                restaurantes_encontrados_zona = []

                while len(restaurantes_encontrados_zona) < 10:
                    formula_parts_zona = formula_parts.copy()

                    limites = obtener_limites_geograficos(lat_centro, lon_centro, distancia_km)
                    formula_parts_zona.append(f"AND({{location/lat}} >= {limites['lat_min']}, {{location/lat}} <= {limites['lat_max']})")
                    formula_parts_zona.append(f"AND({{location/lng}} >= {limites['lon_min']}, {{location/lng}} <= {limites['lon_max']})")

                    filter_formula_zona = "AND(" + ", ".join(formula_parts_zona) + ")"
                    logging.info(f"Fórmula de filtro construida: {filter_formula_zona} para distancia {distancia_km} km")

                    params = {
                        "filterByFormula": filter_formula_zona,
                        "sort[0][field]": "NBH2",
                        "sort[0][direction]": "desc",
                        "maxRecords": 10
                    }

                    response_data = airtable_request(url, headers, params, view_id="viw6z7g5ZZs3mpy3S")
                    if response_data and 'records' in response_data:
                        restaurantes_filtrados = [
                            restaurante for restaurante in response_data['records']
                            if restaurante not in restaurantes_encontrados_zona  # Evitar duplicados en la misma zona
                        ]
                        restaurantes_encontrados_zona.extend(restaurantes_filtrados)

                    if len(restaurantes_encontrados_zona) >= 10:
                        break  # Si alcanzamos 10 restaurantes para esta zona, pasamos a la siguiente

                    distancia_km += 1.0  # Aumentamos el radio progresivamente

                    if distancia_km > 8:  # Limitar el rango máximo de búsqueda a 8 km
                        break

                # Ordenamos los restaurantes por proximidad si se especifica
                if sort_by_proximity and location_zona:
                    restaurantes_encontrados_zona.sort(key=lambda r: haversine(
                        lon_centro, lat_centro,
                        float(r['fields'].get('location/lng', 0)),
                        float(r['fields'].get('location/lat', 0))
                    ))

                # Agregamos los restaurantes de esta zona a la lista principal, evitando duplicados
                restaurantes_encontrados.extend([
                    restaurante for restaurante in restaurantes_encontrados_zona
                    if restaurante not in restaurantes_encontrados
                ])

            # Limitamos el total de resultados a 30 restaurantes
            restaurantes_encontrados = restaurantes_encontrados[:30]
            # Puedes ajustar filter_formula aquí si es necesario

        else:
            # Si no se especifica zona, procedemos como antes
            # Obtenemos las coordenadas de la ciudad
            location = obtener_coordenadas(city, city)
            if not location:
                raise HTTPException(status_code=404, detail="Ciudad no encontrada.")
            
            lat_centro = location['lat']
            lon_centro = location['lng']

            # Realizamos una búsqueda inicial dentro de la ciudad
            distancia_km = 1.0  # Comenzamos con un radio pequeño, 1 km
            while len(restaurantes_encontrados) < 10:
                formula_parts_city = formula_parts.copy()

                limites = obtener_limites_geograficos(lat_centro, lon_centro, distancia_km)
                formula_parts_city.append(f"AND({{location/lat}} >= {limites['lat_min']}, {{location/lat}} <= {limites['lat_max']})")
                formula_parts_city.append(f"AND({{location/lng}} >= {limites['lon_min']}, {{location/lng}} <= {limites['lon_max']})")

                filter_formula = "AND(" + ", ".join(formula_parts_city) + ")"
                logging.info(f"Fórmula de filtro construida: {filter_formula} para distancia {distancia_km} km")

                params = {
                    "filterByFormula": filter_formula,
                    "sort[0][field]": "NBH2",
                    "sort[0][direction]": "desc",
                    "maxRecords": 10
                }

                response_data = airtable_request(url, headers, params, view_id="viw6z7g5ZZs3mpy3S")
                if response_data and 'records' in response_data:
                    restaurantes_filtrados = [
                        restaurante for restaurante in response_data['records']
                        if restaurante not in restaurantes_encontrados  # Evitar duplicados
                    ]
                    restaurantes_encontrados.extend(restaurantes_filtrados)

                if len(restaurantes_encontrados) >= 10:
                    break  # Si alcanzamos 10 resultados, detenemos la búsqueda

                distancia_km += 1.0  # Aumentamos el radio

                if distancia_km > 8:  # Limitar el rango máximo de búsqueda a 8 km
                    break

            # Ordenamos los restaurantes por proximidad si se especifica
            if sort_by_proximity and location:
                restaurantes_encontrados.sort(key=lambda r: haversine(
                    lon_centro, lat_centro,
                    float(r['fields'].get('location/lng', 0)),
                    float(r['fields'].get('location/lat', 0))
                ))

            # Limitamos los resultados a 10 restaurantes
            restaurantes_encontrados = restaurantes_encontrados[:10]

        # Devolvemos los restaurantes encontrados y la fórmula de filtro usada
        return restaurantes_encontrados, filter_formula

    except Exception as e:
        logging.error(f"Error al obtener restaurantes de la ciudad: {e}")
        raise HTTPException(status_code=500, detail="Error al obtener restaurantes de la ciudad")

# ... (resto del código permanece igual)
