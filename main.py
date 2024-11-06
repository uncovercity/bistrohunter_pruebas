from fastapi import FastAPI, Query, HTTPException, Request
from typing import Optional, List
from bistrohunter import obtener_restaurantes_por_ciudad
import logging
from datetime import datetime

app = FastAPI()

@app.get("/")
async def root():
    return {"message": "Bienvenido a la API de búsqueda de restaurantes"}

@app.get("/api/getRestaurantsPrueba")
async def get_restaurantes(
    request: Request,  
    city: str, 
    date: Optional[str] = Query(None, description="La fecha en la que se planea visitar el restaurante"), 
    price_range: Optional[str] = Query(None, description="El rango de precios deseado para el restaurante"),
    cocina: Optional[str] = Query(None, description="El tipo de cocina que prefiere el cliente"),
    diet: Optional[str] = Query(None, description="Dieta que necesita el cliente"),
    dish: Optional[str] = Query(None, description="Plato por el que puede preguntar un cliente específicamente"),
    zonas: str = Query("", description="Lista de zonas específicas dentro de la ciudad, separadas por comas")
):
    try:
        dia_semana = None
        if date:
            fecha = datetime.strptime(date, "%Y-%m-%d")
            dia_semana = obtener_dia_semana(fecha)

        zonas_list = [zona.strip() for zona in zonas.split(",")] if zonas else []

        restaurantes = []
        if zonas_list:
            for zona in zonas_list:
                if len(restaurantes) >= 10:
                    break
                nuevos_restaurantes = obtener_restaurantes_por_ciudad(city, dia_semana, price_range, cocina, diet, dish, zona)
                restaurantes.extend(nuevos_restaurantes)
        else:
            restaurantes = obtener_restaurantes_por_ciudad(city, dia_semana, price_range, cocina, diet, dish)

        restaurantes = restaurantes[:10]

        full_url = str(request.url)
        request_method = request.method
        api_call = f'{request_method} {full_url}'

        if restaurantes:
            return {
                "restaurants": [
                    {
                        "cid": r['fields'].get('cid'),
                        "title": r['fields'].get('title', 'Sin título'),
                        "description": r['fields'].get('bh_message', 'Sin descripción'),
                        "price_range": r['fields'].get('price_range', 'No especificado'),
                        "score": r['fields'].get('NBH2', 'N/A'),
                        "url": r['fields'].get('url', 'No especificado')
                    } for r in restaurantes
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
