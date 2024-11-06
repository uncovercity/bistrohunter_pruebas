#IMPORTS
from fastapi import FastAPI, Query, HTTPException, Request
from typing import Optional
from bistrohunter import obtener_restaurantes_por_ciudad, obtener_dia_semana, haversine, obtener_coordenadas #Llama a las funciones que hemos definido en el otro archivo de código
import logging
from datetime import datetime

app = FastAPI()

@app.get("/") #Define el mensaje por defecto de nuestra propia API 
async def root():
    return {"message": "Bienvenido a la API de búsqueda de restaurantes"}

@app.get("/api/getRestaurantsPrueba") #Dentro de nuestra propia API nosotros podemos llamar a diferentes funciones. Aquí llama a get_restaurantes
async def get_restaurantes(
    request: Request,  
    city: str, 
    date: Optional[str] = Query(None, description="La fecha en la que se planea visitar el restaurante"), 
    price_range: Optional[str] = Query(None, description="El rango de precios deseado para el restaurante"),
    cocina: Optional[str] = Query(None, description="El tipo de cocina que prefiere el cliente"),
    diet: Optional[str] = Query(None, description="Dieta que necesita el cliente"),
    dish: Optional[str] = Query(None, description="Plato por el que puede preguntar un cliente específicamente"),
    zona: Optional[str] = Query(None, description="Zona específica dentro de la ciudad"),
):
    try:
        dia_semana = None
        if date:
            fecha = datetime.strptime(date, "%Y-%m-%d")
            dia_semana = obtener_dia_semana(fecha)

        # Llamar a la función para obtener los restaurantes y la fórmula de filtro
        restaurantes, filter_formula = obtener_restaurantes_por_ciudad(city, dia_semana, price_range, cocina, diet, dish, zona)
        
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
                    "zone": zona
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
                    "zone": zona
                },
                "api_call": api_call
            }
    except Exception as e:
        logging.error(f"Error al buscar restaurantes: {e}")
        raise HTTPException(status_code=500, detail="Error al buscar restaurantes")
        
@app.post("/procesar-variables") #Aquí llama a procesar_variables
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

        # Llamar a la función para obtener los restaurantes
        restaurantes = obtener_restaurantes_por_ciudad(
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
        api_call = f'{request_method} {full_url}'

        # Devolver los restaurantes, las variables y la llamada a la API
        if restaurantes:
            return {
                "restaurants": [
                    {
                        "cid": restaurante['fields'].get('cid'),
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
                    "zone": zona
                },
                "api_call": api_call  # Devolver la llamada a la API
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
                    "zone": zona
                },
                "api_call": api_call
            }
    except Exception as e:
        logging.error(f"Error al procesar variables: {e}")
        return {"error": "Ocurrió un error al procesar las variables"}
