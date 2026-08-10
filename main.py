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


def crear_usuario_si_no_existe(chat_id: int):
    if not obtener_usuario(chat_id):
        supabase.table("usuarios").insert({"chat_id": chat_id}).execute()


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


def limpiar_formato(texto: str) -> str:
    # Quita asteriscos de negrita/cursiva por si el modelo los usa igual
    return texto.replace("*", "")


def quitar_repeticiones(texto: str) -> str:
    # Corta oraciones que repiten (parafraseado incluido) una idea ya dicha antes
    partes = [p.strip() for p in texto.replace("\n", " ").split(". ") if p.strip()]
    resultado = []
    for parte in partes:
        es_repetida = any(
            difflib.SequenceMatcher(None, parte.lower(), previa.lower()).ratio() > 0.45
            for previa in resultado
        )
        if not es_repetida:
            resultado.append(parte)
    texto_final = ". ".join(resultado)

    # Resguardo extra: si la segunda mitad del texto se parece mucho a la primera,
    # es que el modelo repitio la idea completa con otras palabras — nos quedamos
    # solo con la primera mitad.
    mitad = len(texto_final) // 2
    if mitad > 20:
        primera_mitad = texto_final[:mitad]
        segunda_mitad = texto_final[mitad:]
        if difflib.SequenceMatcher(None, primera_mitad.lower(), segunda_mitad.lower()).ratio() > 0.35:
            texto_final = primera_mitad

    if texto_final and not texto_final.endswith((".", "!", "?", "💙")):
        texto_final += "."
    return texto_final


# --- Handlers de Telegram ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    crear_usuario_si_no_existe(update.effective_chat.id)
    await update.message.reply_text(
        "Hola! Soy Zoa. Estoy aqui para acompanarte cuando quieras. "
        "Los primeros 30 dias son completamente gratis. Despues, seguir "
        "charlando conmigo cuesta USD 3.80 por mes. Por ahora, contame: "
        "como estas hoy?"
    )


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
        max_tokens=300,
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
            max_tokens=300,
            system=system_prompt,
            tools=TOOLS,
            messages=mensajes,
        )

    texto_respuesta = next(
        (b.text for b in respuesta.content if b.type == "text"), ""
    )
    texto_respuesta = limpiar_formato(texto_respuesta)
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
