from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
import os
import threading
import anthropic
import requests
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from supabase import create_client
# --- Clientes ---
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
SYSTEM_PROMPT_BASE = (
    "Eres Zoa, una IA amorosa, calida y comprensiva. Acompanas a las personas "
    "en cualquier situacion. Escuchas, validas emociones, ofreces esperanza y "
    "soluciones concretas. Jamas juzgas ni abandonas a la persona sin un camino claro. "
    "Tenes memoria persistente: guardas el nombre del usuario y el historial de la "
    "conversacion entre sesiones, asi que si te preguntan si vas a recordar, respondes "
    "con confianza que si. "
    "Respondes siempre en 2 a 4 oraciones como maximo, en un solo parrafo fluido, como "
    "un mensaje de WhatsApp entre amigos cercanos. Nunca uses listas con guiones ni "
    "numeraciones, nunca uses asteriscos ni cursiva ni negrita, y nunca separes tu "
    "respuesta en varias lineas cortas — todo va en un unico bloque de texto corrido. "
    "Elegi una sola idea central por mensaje, no repitas el mismo punto de varias "
    "formas distintas, y nunca digas dos veces algo parecido dentro de la misma "
    "respuesta, ni con las mismas palabras ni parafraseado. Usa como mucho un emoji "
    "por mensaje, no varios. No termines siempre con una pregunta: a veces alcanza "
    "con acompanar y validar, sin abrir otra pregunta nueva. "
    "Muy importante sobre el idioma: respondes siempre en el mismo idioma en el que "
    "te escribe el usuario, sin importar cual sea (ingles, portugues, frances, "
    "italiano, etc.), detectandolo vos misma a partir de su ultimo mensaje. Si el "
    "usuario cambia de idioma durante la charla, vos tambien cambias a partir de ese "
    "momento. Si un mensaje mezcla idiomas o no queda claro cual predomina, respondes "
    "en el idioma que uso en su mensaje mas reciente. Todas las reglas de esta "
    "instruccion (tono, longitud, formato, como hablar del precio) aplican igual sin "
    "importar el idioma en el que respondas. "
    "Sobre el precio: los primeros 30 dias son gratis y despues cuesta USD 3.80 por "
    "mes, siempre en dolares. Solo hables de esto si te preguntan directamente por "
    "el precio, o si quedan 48 horas o menos para que se termine el periodo gratis. "
    "Cuando te pregunten cuanto cuesta, respondes con seguridad y calidez que son "
    "USD 3.80 por mes despues de los 30 dias gratis, explicando amablemente que si "
    "no cobrara no podrias seguir existiendo ni ayudar a mas personas. No termines "
    "esa explicacion con ninguna comparacion dirigida al usuario (nada de 'como vos', "
    "'como a vos', 'personas como tu' ni similares) — terminala en 'ayudar a mas "
    "personas' y ahi cortas. Ese es el "
    "precio real y no cambia, asi que nunca digas que no tenes esa informacion, que "
    "depende del plan, ni derives la pregunta a la plataforma o a un equipo — vos "
    "misma das siempre esa respuesta completa y segura, sin ninguna aclaracion "
    "adicional despues. Nunca menciones el precio por tu cuenta en otro momento de "
    "la charla."
)
HISTORIAL_MENSAJES = 20  # cuantos mensajes previos mandarle a Claude como contexto
# --- Herramienta para que Claude guarde el nombre cuando el usuario se presenta ---
TOOLS = [
    {
        "name": "guardar_nombre",
        "description": "Guarda el nombre del usuario cuando se presenta o lo menciona por primera vez.",
        "input_schema": {
            "type": "object",
            "properties": {
                "nombre": {"type": "string", "description": "El nombre de la persona"}
            },
            "required": ["nombre"],
        },
    }
]
# --- Funciones de Supabase ---
def obtener_usuario(chat_id: int):
    res = supabase.table("usuarios").select("*").eq("chat_id", chat_id).execute()
    return res.data[0] if res.data else None
def crear_usuario_si_no_existe(chat_id: int, canal_referido: str | None = None):
    if not obtener_usuario(chat_id):
        datos = {"chat_id": chat_id}
        if canal_referido:
            datos["canal_referido"] = canal_referido
        supabase.table("usuarios").insert(datos).execute()
def guardar_nombre(chat_id: int, nombre: str):
    supabase.table("usuarios").update(
        {"nombre": nombre, "updated_at": "now()"}
    ).eq("chat_id", chat_id).execute()
def obtener_historial(chat_id: int, limite: int = HISTORIAL_MENSAJES):
    res = (
        supabase.table("conversaciones")
        .select("role, content")
        .eq("chat_id", chat_id)
        .order("created_at", desc=True)
        .limit(limite)
        .execute()
    )
    return list(reversed(res.data))  # orden cronologico
def guardar_mensaje(chat_id: int, role: str, content: str):
    supabase.table("conversaciones").insert(
        {"chat_id": chat_id, "role": role, "content": content}
    ).execute()
import difflib
import re
def limpiar_formato(texto: str) -> str:
    # Quita asteriscos de negrita/cursiva por si el modelo los usa igual
    return texto.replace("*", "")
def quitar_comparaciones(texto: str) -> str:
    # Elimina frases de comparacion tipo "como vos", "como a vos", "como tu", etc.
    patrones = [
        r",?\s*como a vos\.?",
        r",?\s*como vos\.?",
        r",?\s*como a ti\.?",
        r",?\s*como tu\.?",
        r",?\s*como tú\.?",
        r",?\s*personas como vos\.?",
        r",?\s*personas como tu\.?",
    ]
    for patron in patrones:
        texto = re.sub(patron, ".", texto, flags=re.IGNORECASE)
    texto = re.sub(r"\.{2,}", ".", texto)  # colapsa puntos duplicados que puedan quedar
    return texto.strip()
def quitar_repeticiones(texto: str) -> str:
    # Corta oraciones que repiten (parafraseado incluido) una idea ya dicha antes.
    # Umbral alto (0.75) a proposito: solo debe descartar oraciones PRACTICAMENTE
    # identicas, no oraciones que simplemente comparten tono o algunas palabras
    # (con un umbral bajo se terminaba comiendo el final de respuestas validas).
    partes = [p.strip() for p in texto.replace("\n", " ").split(". ") if p.strip()]
    resultado = []
    for parte in partes:
        es_repetida = any(
            difflib.SequenceMatcher(None, parte.lower(), previa.lower()).ratio() > 0.75
            for previa in resultado
        )
        if not es_repetida:
