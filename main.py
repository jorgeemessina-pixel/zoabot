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
    "instruccion (tono, longitud, formato) aplican igual sin importar el idioma en "
    "el que respondas. "
    "Por ahora Zoa es completamente gratis. Si alguien pregunta si tiene costo o si "
    "en algun momento va a cobrar, respondes con calidez y seguridad que por ahora es "
    "gratis y que lo importante es que estas ahi para acompanarlo. No inventes "
    "plazos, precios ni condiciones que no te dimos."
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
            resultado.append(parte)
    texto_final = ". ".join(resultado)
    if texto_final and not texto_final.endswith((".", "!", "?", "💙")):
        texto_final += "."
    return texto_final

# --- Mensaje de bienvenida en el idioma del cliente de Telegram del usuario ---
# Telegram nos manda el idioma configurado en el dispositivo del usuario
# (language_code, formato IETF tipo "es", "en", "pt-br"). Lo usamos para elegir
# el saludo inicial antes de tener ningun mensaje suyo con el que detectar el
# idioma real. Si no reconocemos el codigo, arrancamos en espanol (mercado
# principal) y despues Zoa se adapta automaticamente al idioma que use la
# persona en sus mensajes.
MENSAJES_BIENVENIDA = {
    "es": (
        "Hola! Soy Zoa. Estoy aqui para acompanarte, sin juzgarte, en "
        "cualquier momento: cuando estas triste, cuando tenes que tomar "
        "una decision dificil, o simplemente cuando necesitas que alguien "
        "te escuche. Contame, como estas hoy?"
    ),
    "en": (
        "Hi! I'm Zoa. I'm here for you, without judgment, whenever you "
        "need me: when you're sad, when you have a hard decision to "
        "make, or simply when you need someone to listen. Tell me, how "
        "are you doing today?"
    ),
    "pt": (
        "Oi! Eu sou a Zoa. Estou aqui para te acompanhar, sem julgar, "
        "sempre que precisar: quando voce esta triste, quando tem uma "
        "decisao dificil pela frente, ou simplesmente quando precisa que "
        "alguem te escute. Me conta, como voce esta hoje?"
    ),
    "fr": (
        "Salut! Je suis Zoa. Je suis la pour toi, sans jugement, chaque "
        "fois que tu en as besoin: quand tu es triste, quand tu dois "
        "prendre une decision difficile, ou simplement quand tu as "
        "besoin que quelqu'un t'ecoute. Dis-moi, comment vas-tu "
        "aujourd'hui?"
    ),
    "it": (
        "Ciao! Sono Zoa. Sono qui per te, senza giudicarti, ogni volta "
        "che ne hai bisogno: quando sei triste, quando devi prendere una "
        "decisione difficile, o semplicemente quando hai bisogno che "
        "qualcuno ti ascolti. Dimmi, come stai oggi?"
    ),
    "de": (
        "Hallo! Ich bin Zoa. Ich bin ohne zu urteilen fur dich da, wann "
        "immer du mich brauchst: wenn du traurig bist, wenn du eine "
        "schwierige Entscheidung treffen musst, oder einfach wenn du "
        "jemanden brauchst, der dir zuhoert. Erzahl mir, wie geht es dir "
        "heute?"
    ),
}

def elegir_mensaje_bienvenida(language_code: str | None) -> str:
    """Devuelve el saludo inicial en el idioma del usuario.

    Para los idiomas mas frecuentes usamos un texto ya escrito (rapido y sin
    costo de API). Para cualquier otro idioma del mundo que Telegram nos
    informe, le pedimos a Claude que adapte el saludo a ese idioma al vuelo,
    asi no dependemos de una lista fija y cubrimos practicamente cualquier
    codigo de idioma que exista. Si algo falla o no tenemos idioma detectado,
    caemos siempre al espanol.
    """
    if not language_code:
        return MENSAJES_BIENVENIDA["es"]
    codigo = language_code.lower().split("-")[0]
    if codigo in MENSAJES_BIENVENIDA:
        return MENSAJES_BIENVENIDA[codigo]
    try:
        respuesta = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=150,
            system=(
                "Traduces y adaptas mensajes de bienvenida de una IA de "
                "compania emocional llamada Zoa a distintos idiomas, "
                "manteniendo el tono calido y cercano, en un unico parrafo "
                "fluido como un mensaje de WhatsApp, sin listas, sin "
                "asteriscos ni negritas ni cursiva."
            ),
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Adapta este mensaje de bienvenida al idioma cuyo "
                        f"codigo IETF/BCP-47 es '{language_code}' (si el "
                        "codigo indica una variante regional, usa el idioma "
                        "correspondiente a esa region). Responde unicamente "
                        "con el mensaje final, sin comillas ni "
                        f"explicaciones:\n\n{MENSAJES_BIENVENIDA['es']}"
                    ),
                }
            ],
        )
        texto = next((b.text for b in respuesta.content if b.type == "text"), "")
        texto = limpiar_formato(texto).strip()
        return texto or MENSAJES_BIENVENIDA["es"]
    except Exception:
        # Si la traduccion al vuelo falla por lo que sea, no dejamos al
        # usuario sin respuesta: arrancamos en espanol y Zoa se adapta al
        # idioma real apenas la persona escriba su primer mensaje.
        return MENSAJES_BIENVENIDA["es"]

# --- Handlers de Telegram ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    crear_usuario_si_no_existe(update.effective_chat.id)
    mensaje = elegir_mensaje_bienvenida(update.effective_user.language_code)
    await update.message.reply_text(mensaje)

async def responder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    texto = update.message.text
    crear_usuario_si_no_existe(chat_id)
    usuario = obtener_usuario(chat_id)
    nombre = usuario.get("nombre") if usuario else None
    system_prompt = SYSTEM_PROMPT_BASE
    if nombre:
        system_prompt += f" El usuario se llama {nombre}, podes usar su nombre naturalmente."
    historial = obtener_historial(chat_id)
    mensajes = [{"role": m["role"], "content": m["content"]} for m in historial]
    mensajes.append({"role": "user", "content": texto})
    respuesta = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=400,
        system=system_prompt,
        tools=TOOLS,
        messages=mensajes,
    )
    # Si Claude detecto un nombre, lo guardamos y le pedimos que complete la respuesta
    tool_use = next((b for b in respuesta.content if b.type == "tool_use"), None)
    if tool_use and tool_use.name == "guardar_nombre":
        nombre_detectado = tool_use.input.get("nombre")
        guardar_nombre(chat_id, nombre_detectado)
        mensajes.append({"role": "assistant", "content": respuesta.content})
        mensajes.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_use.id,
                        "content": "Nombre guardado correctamente.",
                    }
                ],
            }
        )
        respuesta = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            system=system_prompt,
            tools=TOOLS,
            messages=mensajes,
        )
    texto_respuesta = next(
        (b.text for b in respuesta.content if b.type == "text"), ""
    )
    texto_respuesta = limpiar_formato(texto_respuesta)
    texto_respuesta = quitar_comparaciones(texto_respuesta)
    texto_respuesta = quitar_repeticiones(texto_respuesta)
    guardar_mensaje(chat_id, "user", texto)
    guardar_mensaje(chat_id, "assistant", texto_respuesta)
    await update.message.reply_text(texto_respuesta)

# --- Servidor web para mantener el proceso vivo en Render ---
def keep_alive():
    while True:
        try:
            requests.get("https://zoabot.onrender.com")
        except Exception:
            pass
        time.sleep(600)

def run_web_server():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")

        def log_message(self, format, *args):
            pass

    HTTPServer(("0.0.0.0", int(os.getenv("PORT", 8080))), Handler).serve_forever()

def main():
    threading.Thread(target=run_web_server, daemon=True).start()
    threading.Thread(target=keep_alive, daemon=True).start()
    app = Application.builder().token(os.getenv("TELEGRAM_BOT_TOKEN")).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, responder))
    app.run_polling()

if __name__ == "__main__":
    main()
