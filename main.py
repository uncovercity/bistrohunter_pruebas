# IMPORTS
from fastapi import FastAPI, Query, HTTPException, Request
from typing import Optional
import logging
from datetime import datetime
from bistrohunter import (
    obtener_restaurantes_por_ciudad,
    calcular_bounding_box,  
    obtener_coordenadas_zona,
    haversine,
)

app = FastAPI()

@app.get("/")
async def root():
    return {"message": "Bienvenido a la API de búsqueda de restaurantes"}

@app.get("/api/getRestaurantsPrueba")
async def get_restaurantes(
    request: Request,
    city: str = Query(..., description="Ciudad donde buscar restaurantes"),
    coordenadas: Optional[str] = Query(None, description="Coordenadas en formato 'lat,lng'"),
    price_range: Optional[str] = Query(None, description="Rango de precios"),
    cocina: Optional[str] = Query(None, description="Tipo de cocina preferida"),
    diet: Optional[str] = Query(None, description="Restricciones dietéticas"),
    dish: Optional[str] = Query(None, description="Plato específico"),
    zona: Optional[str] = Query(None, description="Zona específica dentro de la ciudad")
):
    try:
        restaurantes, filter_formula, lat_centro_busqueda, lon_centro_busqueda = obtener_restaurantes_por_ciudad(
    city=city,
    price_range=price_range,
    cocina=cocina,
    diet=diet,
    dish=dish,
    zona=zona,
    coordenadas=coordenadas,
    sort_by_proximity=True
)
        
        # Capturar la URL completa y los parámetros de la solicitud
        full_url = str(request.url)
        request_method = request.method
        api_call = f"{request_method} {full_url}"

        # Revisar si hay restaurantes
        if not restaurantes:
            return {
                "mensaje": "No se encontraron restaurantes con los filtros aplicados.",
                "variables": {
                    "city": city,
                    "price_range": price_range,
                    "cuisine_type": cocina,
                    "diet": diet,
                    "dish": dish,
                    "zone": zona,
                    "coordenadas": coordenadas
                },
                "api_call": api_call,
                "filter_formula": filter_formula  # opcional, para debug
            }

        # Si sí hay restaurantes
        resultados = [
            {
                "cid": r["fields"].get("cid"),
                "title": r["fields"].get("title", "Sin título"),
                "description": r["fields"].get("bh_message", "Sin descripción"),
                "price_range": r["fields"].get("price_range", "No especificado"),
                "score": r["fields"].get("NBH2", "N/A"),
                "url": r["fields"].get("url", "No especificado")
            }
            for r in restaurantes
        ]

        return {
            "restaurants": resultados,
            "variables": {
                "city": city,
                "price_range": price_range,
                "cuisine_type": cocina,
                "diet": diet,
                "dish": dish,
                "zone": zona,
                "coordenadas": coordenadas
            },
            "api_call": api_call,
            "filter_formula": filter_formula
        }

    except Exception as e:
        logging.error(f"Error al buscar restaurantes en /api/getRestaurantsPrueba: {e}")
        raise HTTPException(status_code=500, detail="Error interno del servidor")

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

        # Llamar a la función para obtener los restaurantes y la fórmula de filtro
        logging.info(f"Coordenadas recibidas: {coordenadas}")
        restaurantes, filter_formula = obtener_restaurantes_por_ciudad(
            city=city,
            price_range=price_range,
            cocina=cocina,
            diet=diet,
            dish=dish,
            zona=zona,
            coordenadas=coordenadas
        )

        full_url = str(request.url)
        request_method = request.method
        api_call = f'{request_method} {full_url}'

        # Devolver los restaurantes, las variables y la llamada a la API
        if restaurantes:
            return {
                "restaurants": [
                    {
                        "bh_message": r['fields'].get('bh_message', 'Sin descripción'),
                        "url": r['fields'].get('url', 'No especificado'),
                        "lat_restaurante": r['fields'].get('location/lat', 'No especificado'),
                        "lon_restaurante": r['fields'].get('location/lng', 'No especificado')
                    }
                    for r in restaurantes
                ],
                "variables": {
                    "city": city,
                    "price_range": price_range,
                    "cuisine_type": cocina,
                    "diet": diet,
                    "dish": dish,
                    "zone": zona,
                    "coordenadas": coordenadas
                },
                "api_call": api_call
            }
        else:
            return {
                "mensaje": "No se encontraron restaurantes con los filtros aplicados.",
                "variables": {
                    "city": city,
                    "price_range": price_range,
                    "cuisine_type": cocina,
                    "diet": diet,
                    "dish": dish,
                    "zone": zona,
                    "coordenadas": coordenadas
                },
                "api_call": api_call
            }
    except Exception as e:
        logging.error(f"Error al procesar variables: {e}")
        raise HTTPException(status_code=500, detail="Error al procesar variables")
