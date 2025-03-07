# IMPORTS (NO TOCAR)
import os
from typing import Optional, List, Tuple
from fastapi import FastAPI, Query, HTTPException, Request
from datetime import datetime
import requests
import logging
from math import radians, cos, sin, asin, sqrt

# Desplegar fast api (no tocar)
app = FastAPI()

# Configuración del logging
logging.basicConfig(level=logging.INFO)

# Secretos para render
BASE_ID = os.getenv('BASE_ID')
AIRTABLE_PAT = os.getenv('AIRTABLE_PAT')
GOOGLE_MAPS_API_KEY = os.getenv('GOOGLE_MAPS_API_KEY')
N8N_WEBHOOK_URL = os.getenv('N8N_WEBHOOK_URL')

# Calcula la distancia haversiana entre dos puntos (lo uso para el filtro de zona)
def haversine(lon1, lat1, lon2, lat2):
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    c = 2 * asin(sqrt(a))
    km = 6367 * c
    return km
    
# Calculamos la bounding_box dependiendo del punto central de búsqueda (coordenadas del centro de la ciudad o del "centro" de la zona que pide el cliente)
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

# Petición a Airtable en la vista de BistroHunter
def airtable_request(url, headers, params, view_id: Optional[str] = None):
    if view_id:
        params["view"] = view_id
    response = requests.get(url, headers=headers, params=params)
    return response.json() if response.status_code == 200 else None

# Buscamos los restaurantes que tenemos en ddbb en función de las variables que nos pidió el cliente
def obtener_restaurantes_por_ciudad(
    city: str,
    dia_semana: Optional[str] = None,
    price_range: Optional[str] = None,
    cocina: Optional[str] = None,
    diet: Optional[str] = None,
    dish: Optional[str] = None,
    zona: Optional[str] = None,
    coordenadas: Optional[str] = None, 
    radio_km: float = 1.0,
    sort_by_proximity: bool = True
) -> Tuple[list, Optional[str], Optional[float], Optional[float]]:
    
    try:
        table_name = 'Restaurantes DB'
        url = f"https://api.airtable.com/v0/{BASE_ID}/{table_name}"
        headers = {
            "Authorization": f"Bearer {AIRTABLE_PAT}",
        }

        # Latitud y longitud del punto central de búsqueda (tiene que estar en el output para el fit de cercanía)
        lat_centro_busqueda = None  
        lon_centro_busqueda = None  

        # 1) Construimos los filtros base (price_range, cocina, diet, dish)
        base_filters = []

        # --- price_range ---
        if price_range:
            ranges = price_range.split(',')
            if len(ranges) == 1:
                # Caso de un solo rango
                base_filters.append(
                    f"FIND('{price_range.strip()}', ARRAYJOIN({{price_range}}, ', ')) > 0"
                )
            else:
                # Caso de varios rangos
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
        final_filter_formula = None  

        # 2) SI hay ZONA
        if zona:
            zonas_list = (
                [z.strip() for z in zona.split(',')]
                if ',' in zona else
                [zona]
            )

            for index, zona_item in enumerate(zonas_list):
                location_zona = obtener_coordenadas_zona(zona_item, city, radio_km)
                if not location_zona:
                    logging.error(f"Zona '{zona_item}' no encontrada.")
                    continue

                
                lat_centro_busqueda = location_zona['location']['lat']
                lon_centro_busqueda = location_zona['location']['lng']

                bounding_box = location_zona['bounding_box']
                lat_min = bounding_box['lat_min']
                lat_max = bounding_box['lat_max']
                lon_min = bounding_box['lon_min']
                lon_max = bounding_box['lon_max']

                
                zone_filters = base_filters.copy()
                zone_filters.append(f"{{location/lat}} >= {lat_min}")
                zone_filters.append(f"{{location/lat}} <= {lat_max}")
                zone_filters.append(f"{{location/lng}} >= {lon_min}")
                zone_filters.append(f"{{location/lng}} <= {lon_max}")

                
                final_filter_formula = f"AND({', '.join(zone_filters)}, {{description}} != '', {{discard_reason}} != 'Cerrado permanentemente', {{type}} = 'Restaurante', {{price_range_string}} != 'No disponible')"

                logging.info(
                    f"Fórmula de filtro construida para zona '{zona_item}': {final_filter_formula}"
                )

                params = {
                    "filterByFormula": final_filter_formula,
                    "sort[0][field]": "NBH2",
                    "sort[0][direction]": "desc",
                    "maxRecords": 80
                }

                response_data = airtable_request(url, headers, params, view_id="viw6z7g5ZZs3mpy3S")
                if response_data and 'records' in response_data:
                    
                    nuevos_restaurantes = [
                        r for r in response_data['records']
                        if r not in restaurantes_encontrados
                    ]
                    restaurantes_encontrados.extend(nuevos_restaurantes)

            # CANTIDAD MÁXIMA DE RESTAURANTES QUE SE DEVUELVEN (AJUSTAR A VOLUNTAD)
            max_total_restaurantes = len(zonas_list) * 80
            restaurantes_encontrados = restaurantes_encontrados[:max_total_restaurantes]

        # 3) SI NO hay ZONA, utilizamos coordenadas (y un radio incremental)
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
            
            lat_centro_busqueda = lat_centro
            lon_centro_busqueda = lon_centro

            logging.info(f"Coordenadas procesadas: lat={lat_centro}, lon={lon_centro}")

            # Agrandamos el radio de búsqueda hasta que tengamos 80 restaurantes (esto se puede cambiar según los que queramos)
            while len(restaurantes_encontrados) < 80:
                bounding_box = calcular_bounding_box(lat_centro, lon_centro, radio_km)
                lat_min = bounding_box['lat_min']
                lat_max = bounding_box['lat_max']
                lon_min = bounding_box['lon_min']
                lon_max = bounding_box['lon_max']

                
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
                    "maxRecords": 80
                }

                response_data = airtable_request(url, headers, params)
                if response_data and 'records' in response_data:
                    nuevos_restaurantes = [
                        r for r in response_data['records']
                        if r not in restaurantes_encontrados
                    ]
                    restaurantes_encontrados.extend(nuevos_restaurantes)

                if len(restaurantes_encontrados) >= 80:
                    break

                radio_km += 1
                # Buscamos en un radio de HASTA 20 km. Esto se puede ajustar también (hablar con JaviB).
                if radio_km > 20:
                    break

            # 4) Ordenar por proximidad
            if sort_by_proximity and restaurantes_encontrados:
                restaurantes_encontrados.sort(
                    key=lambda r: haversine(
                        lon_centro,
                        lat_centro,
                        float(r['fields'].get('location/lng', 0)),
                        float(r['fields'].get('location/lat', 0))
                    )
                )

            # Tomamos los primeros 80
            restaurantes_encontrados = restaurantes_encontrados[:80]

        
        return (
            restaurantes_encontrados,
            final_filter_formula,
            lat_centro_busqueda,
            lon_centro_busqueda
        )

    except Exception as e:
        logging.error(f"Error al obtener restaurantes de la ciudad: {e}")
        raise HTTPException(
            status_code=500,
            detail="Error al obtener restaurantes de la ciudad"
        )
#Procesa las variables que nos ha dado el cliente (creo que actualmente no se usa, se usaba cuando había que transformar la fecha?)
@app.post("/procesar-variables")
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
                raise HTTPException(
                    status_code=400, 
                    detail="La fecha proporcionada no tiene el formato correcto (YYYY-MM-DD)."
                )
        
        restaurantes, filter_formula, lat_centro_busqueda, lon_centro_busqueda = obtener_restaurantes_por_ciudad(
            city=city,
            dia_semana=dia_semana,
            price_range=price_range,
            cocina=cocina,
            diet=diet,
            dish=dish,
            zona=zona,
            coordenadas=coordenadas
        )

        
        full_url = str(request.url)
        request_method = request.method

        
        http_request_info = f'{request_method} {full_url} HTTP/1.1 200 OK'
        
        # Si no se encontraron restaurantes:
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
        
        
        resultados = []
        for restaurante in restaurantes:
            fields = restaurante.get('fields', {})
            resultados.append({
                "bh_message": fields.get('bh_message', 'Sin descripción'),
                "url": fields.get('url', 'No especificado'),
                "lat_restaurante": fields.get('location/lat', None), 
                "lon_restaurante": fields.get('location/lng', None),
                "categories_string": fields.get('categories_string', None)
            })
        
    
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
            "search_center_lat": lat_centro_busqueda,  
            "search_center_lng": lon_centro_busqueda,  
            "resultados": resultados
        }
    
    except Exception as e:
        logging.error(f"Error al procesar variables: {e}")
        return {"error": "Ocurrió un error al procesar las variables"}
