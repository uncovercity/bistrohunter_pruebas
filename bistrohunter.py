# IMPORTS
import os
from typing import Optional, List
from fastapi import FastAPI, Query, HTTPException, Request
from datetime import datetime
import requests
import logging
from functools import wraps
from math import radians, cos, sin, asin, sqrt

# Desplegar fast api (no tocar)
app = FastAPI()

# Configuración del logging (nos va a decir dónde están los fallos)
logging.basicConfig(level=logging.INFO)

# Secretos. Esto son urls, claves, tokens y demás que no deben mostrarse públicamente ni subirse a ningún sitio
BASE_ID = os.getenv('BASE_ID')
AIRTABLE_PAT = os.getenv('AIRTABLE_PAT')
GOOGLE_MAPS_API_KEY = os.getenv('GOOGLE_MAPS_API_KEY')
N8N_WEBHOOK_URL = os.getenv('N8N_WEBHOOK_URL')

# Calcula la distancia haversiana entre dos puntos (filtro de zona)
def haversine(lon1, lat1, lon2, lat2):
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    c = 2 * asin(sqrt(a))
    km = 6367 * c
    return km


def calcular_bounding_box(lat, lon, radio_km=1):
    # Aproximación: 1 grado de latitud ~ 111.32 km
    km_por_grado_lat = 111.32
    delta_lat = radio_km / km_por_grado_lat

    # Para la longitud, depende de la latitud
    cos_lat = cos(radians(lat))
    km_por_grado_lon = 111.32 * cos_lat
    delta_lon = radio_km / km_por_grado_lon

    lat_min = lat - delta_lat
    lat_max = lat + delta_lat
    lon_min = lon - delta_lon
    lon_max = lon + delta_lon

    return {
        "lat_min": lat_min,
        "lat_max": lat_max,
        "lon_min": lon_min,
        "lon_max": lon_max
    }

# Función que obtiene las coordenadas de la zona que ha especificado el cliente
def obtener_coordenadas_zona(zona: str, ciudad: str, radio_km: float) -> Optional[dict]:
    try:
        url = f"https://maps.googleapis.com/maps/api/geocode/json"
        params = {
            "address": f"{zona}, {ciudad}",
            "key": GOOGLE_MAPS_API_KEY,
            "components": "country:ES"
        }
        response = requests.get(url, params=params)
        data = response.json()
        if data['status'] == 'OK':
            geometry = data['results'][0]['geometry']
            location = geometry['location']
            lat_central = location['lat']
            lon_central = location['lng']
            bounding_box = calcular_bounding_box(lat_central, lon_central, radio_km)
            return {
                "location": location,
                "bounding_box": bounding_box
            }
        else:
            logging.error(f"Error en la geocodificación: {data['status']}")
            return None
    except Exception as e:
        logging.error(f"Error al obtener coordenadas de la zona: {e}")
        return None

def airtable_request(url, headers, params, view_id: Optional[str] = None):
    if view_id:
        params["view"] = view_id
    response = requests.get(url, headers=headers, params=params)
    return response.json() if response.status_code == 200 else None

def obtener_restaurantes_por_ciudad(
    city: str,
    dia_semana: Optional[str] = None,
    price_range: Optional[str] = None,
    cocina: Optional[str] = None,
    diet: Optional[str] = None,
    dish: Optional[str] = None,
    zona: Optional[str] = None,
    coordenadas: Optional[list] = None,
    radio_km: float = 1.0,
    sort_by_proximity: bool = True
) -> (list[dict], Optional[str]):
    try:
        table_name = 'Restaurantes DB'
        url = f"https://api.airtable.com/v0/{BASE_ID}/{table_name}"
        headers = {
            "Authorization": f"Bearer {AIRTABLE_PAT}",
        }

        # 1) Construimos los filtros base (price_range, cocina, diet, dish)
        base_filters = []

        # --- price_range ---
        if price_range:
            ranges = price_range.split(',')
            if len(ranges) == 1:
                # Caso de un solo rango, p.e. '$$'
                base_filters.append(
                    f"FIND('{price_range.strip()}', ARRAYJOIN({{price_range}}, ', ')) > 0"
                )
            else:
                # Caso de varios rangos, p.e. '$, $$'
                conditions = [
                    f"FIND('{r.strip()}', ARRAYJOIN({{price_range}}, ', ')) > 0"
                    for r in ranges
                ]
                base_filters.append(f"OR({', '.join(conditions)})")

        # --- cocina ---
        if cocina:
            cocinas = cocina.split(',')
            if len(cocinas) == 1:
                base_filters.append(
                    f"SEARCH('{cocina.strip()}', {{categories_string}}) > 0"
                )
            else:
                conditions = [
                    f"SEARCH('{c.strip()}', {{categories_string}}) > 0"
                    for c in cocinas
                ]
                base_filters.append(f"OR({', '.join(conditions)})")

        # --- diet ---
        if diet:
            base_filters.append(f"SEARCH('{diet.strip()}', {{categories_string}}) > 0")

        # --- dish ---
        if dish:
            dishes = dish.split(',')
            if len(dishes) == 1:
                base_filters.append(
                    f"SEARCH('{dish.strip()}', {{google_reviews}}) > 0"
                )
            else:
                conditions = [
                    f"SEARCH('{d.strip()}', {{google_reviews}}) > 0"
                    for d in dishes
                ]
                base_filters.append(f"OR({', '.join(conditions)})")

        restaurantes_encontrados = []
        final_filter_formula = None  # para retornarla después si quieres verla

        # 2) Si hay ZONA
        if zona:
            zonas_list = (
                [z.strip() for z in zona.split(',')]
                if ',' in zona else
                [zona]
            )

            for zona_item in zonas_list:
                location_zona = obtener_coordenadas_zona(zona_item, city, radio_km)
                if not location_zona:
                    logging.error(f"Zona '{zona_item}' no encontrada.")
                    continue

                location = location_zona['location']
                bounding_box = location_zona['bounding_box']
                lat_min = bounding_box['lat_min']
                lat_max = bounding_box['lat_max']
                lon_min = bounding_box['lon_min']
                lon_max = bounding_box['lon_max']

                # Creamos una copia de los filtros base y le añadimos la parte geográfica
                zone_filters = base_filters.copy()
                zone_filters.append(f"{{location/lat}} >= {lat_min}")
                zone_filters.append(f"{{location/lat}} <= {lat_max}")
                zone_filters.append(f"{{location/lng}} >= {lon_min}")
                zone_filters.append(f"{{location/lng}} <= {lon_max}")

                # Hacemos un AND global de todas las partes
                final_filter_formula = f"AND({', '.join(zone_filters)})"
                logging.info(
                    f"Fórmula de filtro construida para zona '{zona_item}': {final_filter_formula}"
                )

                params = {
                    "filterByFormula": final_filter_formula,
                    "sort[0][field]": "NBH2",
                    "sort[0][direction]": "desc",
                    "maxRecords": 10
                }

                response_data = airtable_request(url, headers, params, view_id="viw6z7g5ZZs3mpy3S")
                if response_data and 'records' in response_data:
                    # Evitamos duplicados
                    nuevos_restaurantes = [
                        r for r in response_data['records']
                        if r not in restaurantes_encontrados
                    ]
                    restaurantes_encontrados.extend(nuevos_restaurantes)

            # Ajustamos la cantidad máximo de restaurantes
            max_total_restaurantes = len(zonas_list) * 10
            restaurantes_encontrados = restaurantes_encontrados[:max_total_restaurantes]

        # 3) Si NO hay ZONA, utilizamos coordenadas (y un radio incremental)
        else:
            if not coordenadas:
                raise HTTPException(
                    status_code=400,
                    detail="Debes especificar 'zona' o 'coordenadas'."
                )

            logging.info(f"Coordenadas recibidas: {coordenadas}")
            coords = [float(coord) for coord in coordenadas.split(",")]
            if len(coords) != 2:
                raise HTTPException(
                    status_code=400,
                    detail="Coordenadas inválidas. Deben ser [lat, lng] en texto."
                )

            lat_centro, lon_centro = coords
            logging.info(f"Coordenadas procesadas: lat={lat_centro}, lon={lon_centro}")

            # Mientras no tengamos al menos 10 resultados, agrandamos el radio
            while len(restaurantes_encontrados) < 10:
                bounding_box = calcular_bounding_box(lat_centro, lon_centro, radio_km)
                lat_min = bounding_box['lat_min']
                lat_max = bounding_box['lat_max']
                lon_min = bounding_box['lon_min']
                lon_max = bounding_box['lon_max']

                # Copiamos los filtros base y añadimos la parte geográfica
                geo_filters = base_filters.copy()
                geo_filters.extend([
                    f"{{location/lat}} >= {lat_min}",
                    f"{{location/lat}} <= {lat_max}",
                    f"{{location/lng}} >= {lon_min}",
                    f"{{location/lng}} <= {lon_max}"
                ])

                final_filter_formula = f"AND({', '.join(geo_filters)})"
                logging.info(
                    f"Fórmula de filtro construida: location=({lat_centro}, {lon_centro}), bounding_box={final_filter_formula}"
                )

                params = {
                    "filterByFormula": final_filter_formula,
                    "sort[0][field]": "NBH2",
                    "sort[0][direction]": "desc",
                    "maxRecords": 10
                }

                response_data = airtable_request(url, headers, params)
                if response_data and 'records' in response_data:
                    nuevos_restaurantes = [
                        r for r in response_data['records']
                        if r not in restaurantes_encontrados
                    ]
                    restaurantes_encontrados.extend(nuevos_restaurantes)

                if len(restaurantes_encontrados) >= 10:
                    break

                # Incrementamos el radio para volver a intentar
                radio_km += 0.5
                if radio_km > 2:  # límite de 2 km
                    break

            # 4) Orden opcional por proximidad
            if sort_by_proximity and restaurantes_encontrados:
                restaurantes_encontrados.sort(
                    key=lambda r: haversine(
                        lon_centro,
                        lat_centro,
                        float(r['fields'].get('location/lng', 0)),
                        float(r['fields'].get('location/lat', 0))
                    )
                )

            # Tomamos los primeros 10
            restaurantes_encontrados = restaurantes_encontrados[:10]

        return restaurantes_encontrados, final_filter_formula

    except Exception as e:
        logging.error(f"Error al obtener restaurantes de la ciudad: {e}")
        raise HTTPException(
            status_code=500,
            detail="Error al obtener restaurantes de la ciudad"
        )

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
        coordenadas = data.get('coordenadas')

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
            zona=zona,
            coordenadas=coordenadas
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
                "bh_message": restaurante['fields'].get('bh_message', 'Sin descripción'),
                "url": restaurante['fields'].get('url', 'No especificado')
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
