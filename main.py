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
    zonas: str = Query("", description="Lista de zonas específicas dentro de la ciudad, separadas por comas")  # Modificado para aceptar zonas como string separado por comas
):
    try:
        dia_semana = None
        if date:
            fecha = datetime.strptime(date, "%Y-%m-%d")
            dia_semana = obtener_dia_semana(fecha)

        # Convertir zonas a lista si se proporcionan como string separado por comas
        zonas_list = [zona.strip() for zona in zonas.split(",")] if zonas else []

        # Validar si la lista de zonas contiene "Madrid" como una de las zonas y eliminarla si no se desea buscar en toda la ciudad
        if "Madrid" in zonas_list:
            zonas_list.remove("Madrid")

        # Lista para almacenar los restaurantes encontrados
        restaurantes = []

        # Búsqueda en múltiples zonas si hay más de una zona, de lo contrario, una sola zona
        if zonas_list:
            for zona in zonas_list:
                if len(restaurantes) >= 10:
                    break  # Detener la búsqueda si ya tenemos 10 restaurantes
                nuevos_restaurantes, _ = obtener_restaurantes_por_ciudad(
                    city=city,
                    dia_semana=dia_semana,
                    price_range=price_range,
                    cocina=cocina,
                    diet=diet,
                    dish=dish,
                    zona=zona,
                    sort_by_proximity=True
                )
                restaurantes.extend(nuevos_restaurantes)
        else:
            # Si no hay zonas, buscar en toda la ciudad
            restaurantes, _ = obtener_restaurantes_por_ciudad(
                city=city,
                dia_semana=dia_semana,
                price_range=price_range,
                cocina=cocina,
                diet=diet,
                dish=dish,
                zona=None,
                sort_by_proximity=True
            )

        # Limitar a 10 restaurantes
        restaurantes = restaurantes[:10]

        # Capturar la URL completa y los parámetros de la solicitud
        full_url = str(request.url)
        request_method = request.method
        api_call = f'{request_method} {full_url}'

        # Verifica si se encontraron restaurantes y accede correctamente a sus campos
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

