#IMPORTS
from fastapi import FastAPI, Query, HTTPException, Request
from typing import Optional
from bistrohunter import obtener_restaurantes_por_ciudad, obtener_dia_semana, haversine, obtener_coordenadas # Incluye la función obtener_coordenadas
import logging
from datetime import datetime

app = FastAPI()

@app.get("/") #Define el mensaje por defecto de nuestra propia API 
async def root():
    return {"message": "Bienvenido a la API de pruebas de búsqueda de restaurantes"}

@app.get("/api/getRestaurantsPrueba")
async def get_restaurantes(
    city: str, 
    date: Optional[str] = Query(None, description="La fecha en la que se planea visitar el restaurante"), 
    price_range: Optional[str] = Query(None, description="El rango de precios deseado para el restaurante"),
    cocina: Optional[str] = Query(None, description="El tipo de cocina que prefiere el cliente"),
    diet: Optional[str] = Query(None, description="Dieta que necesita el cliente"),
    dish: Optional[str] = Query(None, description="Plato por el que puede preguntar un cliente específicamente"),
    zona: Optional[str] = Query(None, description="Zona específica dentro de la ciudad"),
    conversation_id: str = Query(None)
):
    try:
        dia_semana = None
        if date:
            fecha = datetime.strptime(date, "%Y-%m-%d")
            dia_semana = obtener_dia_semana(fecha)

        # Llamar a la función para obtener los restaurantes
        restaurantes = obtener_restaurantes_por_ciudad(city, dia_semana, price_range, cocina, diet, dish, zona)
        
        if not restaurantes:
            return {"mensaje": "No se encontraron restaurantes con los filtros aplicados."}

        # Extraer las coordenadas centrales (ya sea de la ciudad o de la zona)
        if zona:
            location = obtener_coordenadas(zona, city)
        else:
            location = obtener_coordenadas(city, city)
        
        lat_centro = location['lat']
        lon_centro = location['lng']

        # Generar los resultados con las distancias calculadas
        resultados = [
            {
                "titulo": restaurante['fields'].get('title', 'Sin título'),
                "descripcion": restaurante['fields'].get('bh_message', 'Sin descripción'),
                "rango_de_precios": restaurante['fields'].get('price_range', 'No especificado'),
                "url": restaurante['fields'].get('url', 'No especificado'),
                "puntuacion_bistrohunter": restaurante['fields'].get('NBH2', 'N/A'),
                "distancia": (
                    f"{haversine(float(restaurante['fields'].get('location/lng', 0)), float(restaurante['fields'].get('location/lat', 0)), lon_centro, lat_centro):.2f} km"
                    if 'location/lng' in restaurante['fields'] and 'location/lat' in restaurante['fields'] else "No calculado"
                ),
                "opciones_alimentarias": restaurante['fields'].get('tripadvisor_dietary_restrictions') if diet else None
            }
            for restaurante in restaurantes
        ]

        return {"resultados": resultados}
        
    except Exception as e:
        logging.error(f"Error al buscar restaurantes: {e}")
        raise HTTPException(status_code=500, detail="Error al buscar restaurantes")


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

        if not city:
            raise HTTPException(status_code=400, detail="La variable 'city' es obligatoria.")

        dia_semana = None
        if date:
            try:
                fecha = datetime.strptime(date, "%Y-%m-%d")
                dia_semana = obtener_dia_semana(fecha)
            except ValueError:
                raise HTTPException(status_code=400, detail="La fecha proporcionada no tiene el formato correcto (YYYY-MM-DD).")

        restaurantes = obtener_restaurantes_por_ciudad(
            city=city,
            dia_semana=dia_semana,
            price_range=price_range,
            cocina=cocina,
            diet=diet,
            dish=dish,
            zona=zona
        )
        
        if not restaurantes:
            return {"mensaje": "No se encontraron restaurantes con los filtros aplicados."}

        # Extraer las coordenadas centrales (ya sea de la ciudad o de la zona)
        if zona:
            location = obtener_coordenadas(zona, city)
        else:
            location = obtener_coordenadas(city, city)

        lat_centro = location['lat']
        lon_centro = location['lng']

        # Generar los resultados con las distancias calculadas
        resultados = [
            {
                "titulo": restaurante['fields'].get('title', 'Sin título'),
                "descripcion": restaurante['fields'].get('bh_message', 'Sin descripción'),
                "rango_de_precios": restaurante['fields'].get('price_range', 'No especificado'),
                "url": restaurante['fields'].get('url', 'No especificado'),
                "puntuacion_bistrohunter": restaurante['fields'].get('NBH2', 'N/A'),
                "distancia": (
                    f"{haversine(float(restaurante['fields'].get('location/lng', 0)), float(restaurante['fields'].get('location/lat', 0)), lon_centro, lat_centro):.2f} km"
                    if 'location/lng' in restaurante['fields'] and 'location/lat' in restaurante['fields'] else "No calculado"
                ),
                "opciones_alimentarias": restaurante['fields'].get('tripadvisor_dietary_restrictions') if diet else None
            }
            for restaurante in restaurantes
        ]

        return {"mensaje": "Datos procesados y respuesta generada correctamente", "resultados": resultados}
    
    except Exception as e:
        logging.error(f"Error al procesar variables: {e}")
        return {"error": "Ocurrió un error al procesar las variables"}

