from fastapi import FastAPI, Query, HTTPException, Request
from typing import Optional, List
from bistrohunter import obtener_restaurantes_varias_zonas, obtener_restaurantes_por_ciudad, obtener_dia_semana
import logging
from datetime import datetime

app = FastAPI()

@app.get("/") # Define el mensaje por defecto de nuestra propia API 
async def root():
    return {"message": "Bienvenido a la API de búsqueda de restaurantes"}

@app.get("/api/getRestaurantsPrueba") # Endpoint para obtener restaurantes
async def get_restaurantes(
    request: Request,  
    city: str, 
    date: Optional[str] = Query(None, description="La fecha en la que se planea visitar el restaurante"), 
    price_range: Optional[str] = Query(None, description="El rango de precios deseado para el restaurante"),
    cocina: Optional[str] = Query(None, description="El tipo de cocina que prefiere el cliente"),
    diet: Optional[str] = Query(None, description="Dieta que necesita el cliente"),
    dish: Optional[str] = Query(None, description="Plato por el que puede preguntar un cliente específicamente"),
    zonas: str = Query("", description="Lista de zonas específicas dentro de la ciudad, separadas por comas")  # Cambio para aceptar zonas como string separado por comas
):
    try:
        dia_semana = None
        if date:
            fecha = datetime.strptime(date, "%Y-%m-%d")
            dia_semana = obtener_dia_semana(fecha)

        # Convertir zonas a lista si se proporcionan como string separado por comas
        zonas_list = [zona.strip() for zona in zonas.split(",")] if zonas else []

        # Manejar la lógica de búsqueda dependiendo de si hay una o múltiples zonas
        if len(zonas_list) > 1:
            # Búsqueda en múltiples zonas
            restaurantes = obtener_restaurantes_varias_zonas(
                city=city,
                zonas=zonas_list,
                dia_semana=dia_semana,
                price_range=price_range,
                cocina=cocina,
                diet=diet,
                dish=dish
            )
        else:
            # Búsqueda en una sola zona
            zona = zonas_list[0] if zonas_list else None
            restaurantes, filter_formula = obtener_restaurantes_por_ciudad(
                city=city,
                dia_semana=dia_semana,
                price_range=price_range,
                cocina=cocina,
                diet=diet,
                dish=dish,
                zona=zona,
                sort_by_proximity=True
            )

        # Capturar la URL completa y los parámetros de la solicitud
        full_url = str(request.url)
        request_method = request.method
        api_call = f'{request_method} {full_url}'

        # Verifica si se encontraron restaurantes y accede correctamente a sus campos
        if restaurantes:
            # Seleccionar los 3 mejores de los 10 mejores (si es aplicable)
            top_10 = restaurantes[:10]
            top_3 = top_10[:3]

            return {
                "top_3_restaurants": [
                    {
                        "cid": r['fields'].get('cid'),
                        "title": r['fields'].get('title', 'Sin título'),
                        "description": r['fields'].get('bh_message', 'Sin descripción'),
                        "price_range": r['fields'].get('price_range', 'No especificado'),
                        "score": r['fields'].get('NBH2', 'N/A'),
                        "url": r['fields'].get('url', 'No especificado')
                    } for r in top_3
                ],
                "all_restaurants": [
                    {
                        "cid": r['fields'].get('cid'),
                        "title": r['fields'].get('title', 'Sin título'),
                        "description": r['fields'].get('bh_message', 'Sin descripción'),
                        "price_range": r['fields'].get('price_range', 'No especificado'),
                        "score": r['fields'].get('NBH2', 'N/A'),
                        "url": r['fields'].get('url', 'No especificado')
                    } for r in top_10
                ],
                "variables": {
                    "city": city,
                    "price_range": price_range,
                    "cuisine_type": cocina,
                    "diet": diet,
                    "dish": dish,
                    "zones": zonas_list
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
                    "zones": zonas_list
                },
                "api_call": api_call
            }
    except Exception as e:
        logging.error(f"Error al buscar restaurantes: {e}")
        raise HTTPException(status_code=500, detail="Error al buscar restaurantes")

