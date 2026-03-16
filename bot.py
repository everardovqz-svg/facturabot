"""
bot.py — Bot de Telegram para recibir fotos de tickets

Vinculación automática por número de teléfono:
  1. Usuario escribe /start
  2. Bot pide su número de teléfono (el que registró en la web)
  3. Bot busca en Supabase la empresa con ese teléfono
  4. Guarda chat_id ↔ empresa — vinculado para siempre
  5. A partir de ahí solo manda fotos, sin más pasos

Comandos:
  /start  → inicia vinculación o confirma cuenta activa
  /estado → tickets pendientes de la empresa
  /ayuda  → instrucciones
"""

import os
import logging
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, KeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    filters,
    ContextTypes,
)
from dotenv import load_dotenv

import database as db
import storage
import claude_ocr

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Estado de la conversación de vinculación
ESPERANDO_TELEFONO = 1


# ─── /start ──────────────────────────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    usuario = db.obtener_usuario_telegram(chat_id)

    if usuario:
        empresa = usuario["empresas"]["nombre"]
        await update.message.reply_text(
            f"✅ Ya estás conectado a *{empresa}*.\n\n"
            "Mándame una foto de cualquier ticket y lo proceso automáticamente. 🧾",
            parse_mode="Markdown",
        )
        return ConversationHandler.END

    # Usuario nuevo — pedir teléfono
    await update.message.reply_text(
        "👋 Bienvenido a *FacturaBot*.\n\n"
        "Para vincular tu cuenta, escribe el número de teléfono con el que te registraste en la app web.\n\n"
        "_Ejemplo: 5512345678_\n\n"
        "Si aún no tienes cuenta, regístrate primero en la app web.",
        parse_mode="Markdown",
    )
    return ESPERANDO_TELEFONO


# ─── Recibir teléfono y vincular ─────────────────────────────────────────────
async def recibir_telefono(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    texto = update.message.text.strip().replace(" ", "").replace("-", "")

    # Validación básica — debe ser numérico y tener entre 10 y 13 dígitos
    if not texto.isdigit() or not (10 <= len(texto) <= 13):
        await update.message.reply_text(
            "⚠️ Eso no parece un número de teléfono válido.\n"
            "Escríbelo sin espacios ni guiones, ejemplo: `5512345678`",
            parse_mode="Markdown",
        )
        return ESPERANDO_TELEFONO

    # Buscar empresa con ese teléfono
    from supabase import create_client
    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

    # Intentar con y sin lada 52
    numeros_a_probar = [texto]
    if texto.startswith("52") and len(texto) == 12:
        numeros_a_probar.append(texto[2:])   # sin lada
    elif len(texto) == 10:
        numeros_a_probar.append(f"52{texto}")  # con lada

    empresa = None
    for num in numeros_a_probar:
        res = sb.table("empresas").select("*").eq("telefono", num).execute()
        if res.data:
            empresa = res.data[0]
            break

    if not empresa:
        await update.message.reply_text(
            "❌ No encontré una cuenta con ese número.\n\n"
            "Verifica que:\n"
            "• Sea el mismo número que pusiste al registrarte\n"
            "• Hayas agregado tu teléfono en el registro (es opcional)\n\n"
            "Si no agregaste teléfono, entra a la app web y actualiza tu perfil.",
        )
        return ESPERANDO_TELEFONO

    # Vincular chat_id con la empresa
    nombre_usuario = update.effective_user.full_name or "Usuario"
    db.registrar_usuario_telegram(chat_id, empresa["id"], nombre_usuario)

    await update.message.reply_text(
        f"✅ ¡Listo! Vinculado a *{empresa['nombre']}*.\n\n"
        "Ahora mándame fotos de tus tickets y los proceso automáticamente.\n\n"
        "_Tip: entre mejor la foto, mejor la lectura. Buena luz y encuadre derecho._",
        parse_mode="Markdown",
    )
    return ConversationHandler.END


async def cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelado. Escribe /start cuando quieras vincular tu cuenta.")
    return ConversationHandler.END


# ─── /estado ─────────────────────────────────────────────────────────────────
async def cmd_estado(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    usuario = db.obtener_usuario_telegram(chat_id)

    if not usuario:
        await update.message.reply_text("Primero vincula tu cuenta con /start 👆")
        return

    tickets = db.obtener_tickets_empresa(usuario["empresa_id"], estado="pendiente")
    total = len(tickets)

    if total == 0:
        await update.message.reply_text("🎉 No tienes tickets pendientes de facturar.")
    else:
        # Armar lista de los primeros 5 tickets pendientes
        lista = ""
        for t in tickets[:5]:
            negocio = t.get("negocio") or "Desconocido"
            total_t = t.get("total") or "—"
            lista += f"• {negocio}  {total_t}\n"
        if total > 5:
            lista += f"_...y {total - 5} más_\n"

        await update.message.reply_text(
            f"📋 *{total} ticket(s) pendientes:*\n\n{lista}\n"
            "Entra a la app web para facturarlos.",
            parse_mode="Markdown",
        )


# ─── /ayuda ──────────────────────────────────────────────────────────────────
async def cmd_ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🧾 *FacturaBot — Ayuda*\n\n"
        "*¿Cómo funciona?*\n"
        "1. Toma foto de tu ticket\n"
        "2. Mándamela aquí\n"
        "3. Te confirmo los datos detectados\n"
        "4. Entra a la app web para facturar con un clic\n\n"
        "*Comandos:*\n"
        "/start — Vincular tu cuenta\n"
        "/estado — Ver tickets pendientes\n"
        "/ayuda — Este mensaje\n\n"
        "_Tip: entre mejor la foto, mejor la lectura._",
        parse_mode="Markdown",
    )


# ─── Procesar foto ────────────────────────────────────────────────────────────
async def recibir_foto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    usuario = db.obtener_usuario_telegram(chat_id)

    if not usuario:
        await update.message.reply_text(
            "Primero vincula tu cuenta con /start 👆"
        )
        return

    empresa = usuario["empresas"]
    msg = await update.message.reply_text("⏳ Procesando tu ticket...")

    try:
        # Descargar foto en mejor resolución
        foto = update.message.photo[-1]
        archivo = await context.bot.get_file(foto.file_id)
        imagen_bytes = bytes(await archivo.download_as_bytearray())

        # Subir a R2
        imagen_url = storage.subir_imagen(imagen_bytes, empresa_id=empresa["id"], extension="jpg")

        # OCR con Claude
        resultado = await claude_ocr.procesar_ticket(imagen_bytes, "image/jpeg")

        if resultado.get("error"):
            await msg.edit_text(f"❌ Error al procesar: {resultado['error']}")
            return

        # Guardar en Supabase
        ticket = db.guardar_ticket({
            "empresa_id":           empresa["id"],
            "telegram_usuario_id":  usuario["id"],
            "negocio":              resultado.get("negocio", ""),
            "fecha_ticket":         resultado.get("fecha_ticket", ""),
            "total":                resultado.get("total", ""),
            "iva":                  resultado.get("iva", ""),
            "subtotal":             resultado.get("subtotal", ""),
            "ieps":                 resultado.get("ieps", ""),
            "forma_pago":           resultado.get("forma_pago", ""),
            "folio":                resultado.get("folio", ""),
            "rfc_negocio":          resultado.get("rfc_negocio", ""),
            "direccion":            resultado.get("direccion", ""),
            "tc":                   resultado.get("tc", ""),
            "tr":                   resultado.get("tr", ""),
            "tda":                  resultado.get("tda", ""),
            "op":                   resultado.get("op", ""),
            "web_id":               resultado.get("web_id", ""),
            "aprobacion":           resultado.get("aprobacion", ""),
            "cp":                   resultado.get("cp", ""),
            "texto_completo":       resultado.get("texto_completo", ""),
            "imagen_url":           imagen_url,
            "portal_facturacion":   resultado.get("portal_url"),
            "estado":               "pendiente",
            "fecha_vencimiento":    resultado["fecha_vencimiento"].isoformat()
                                    if resultado.get("fecha_vencimiento") else None,
        })

        # Alerta de vencimiento urgente
        alerta = ""
        if resultado["fecha_vencimiento"]:
            from datetime import datetime, timezone
            horas = (resultado["fecha_vencimiento"] - datetime.now(timezone.utc)).total_seconds() / 3600
            if horas < 72:
                alerta = f"\n\n⚠️ *¡Vence en {int(horas)}h!* Factura pronto."

        negocio = resultado["negocio"] or "Negocio no identificado"
        total   = resultado["total"]   or "No detectado"
        fecha   = resultado["fecha_ticket"] or "No detectada"
        portal  = resultado["portal_nombre"] or "No encontrado"

        await msg.edit_text(
            f"✅ *Ticket guardado*\n\n"
            f"🏪 *Negocio:* {negocio}\n"
            f"💰 *Total:* {total}\n"
            f"📅 *Fecha:* {fecha}\n"
            f"🧾 *Portal:* {portal}"
            f"{alerta}\n\n"
            "_Entra a la app web para facturarlo._",
            parse_mode="Markdown",
        )

    except Exception as e:
        logger.error(f"Error procesando foto: {e}", exc_info=True)
        await msg.edit_text(
            f"❌ Error al procesar.\n\n"
            f"{str(e)[:200]}\n\n"
            f"Intenta de nuevo.",
            parse_mode="Markdown"
        )


# ─── Foto enviada como documento ─────────────────────────────────────────────
async def recibir_documento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not (doc and doc.mime_type and doc.mime_type.startswith("image/")):
        await update.message.reply_text("Solo proceso imágenes de tickets 📷")
        return

    chat_id = update.effective_chat.id
    usuario = db.obtener_usuario_telegram(chat_id)
    if not usuario:
        await update.message.reply_text("Primero vincula tu cuenta con /start 👆")
        return

    empresa = usuario["empresas"]
    msg = await update.message.reply_text("⏳ Procesando tu ticket...")

    try:
        archivo = await context.bot.get_file(doc.file_id)
        imagen_bytes = bytes(await archivo.download_as_bytearray())
        ext = doc.mime_type.split("/")[-1]

        imagen_url = storage.subir_imagen(imagen_bytes, empresa_id=empresa["id"], extension=ext)
        resultado = await claude_ocr.procesar_ticket(imagen_bytes, doc.mime_type)

        if resultado.get("error"):
            await msg.edit_text(f"❌ Error: {resultado['error']}")
            return

        db.guardar_ticket({
            "empresa_id":           empresa["id"],
            "telegram_usuario_id":  usuario["id"],
            "negocio":              resultado.get("negocio", ""),
            "fecha_ticket":         resultado.get("fecha_ticket", ""),
            "total":                resultado.get("total", ""),
            "iva":                  resultado.get("iva", ""),
            "subtotal":             resultado.get("subtotal", ""),
            "ieps":                 resultado.get("ieps", ""),
            "forma_pago":           resultado.get("forma_pago", ""),
            "folio":                resultado.get("folio", ""),
            "rfc_negocio":          resultado.get("rfc_negocio", ""),
            "direccion":            resultado.get("direccion", ""),
            "tc":                   resultado.get("tc", ""),
            "tr":                   resultado.get("tr", ""),
            "tda":                  resultado.get("tda", ""),
            "op":                   resultado.get("op", ""),
            "web_id":               resultado.get("web_id", ""),
            "aprobacion":           resultado.get("aprobacion", ""),
            "cp":                   resultado.get("cp", ""),
            "texto_completo":       resultado.get("texto_completo", ""),
            "imagen_url":           imagen_url,
            "portal_facturacion":   resultado.get("portal_url"),
            "estado":               "pendiente",
            "fecha_vencimiento":    resultado["fecha_vencimiento"].isoformat()
                                    if resultado.get("fecha_vencimiento") else None,
        })

        negocio = resultado["negocio"] or "Negocio no identificado"
        total   = resultado["total"]   or "No detectado"

        await msg.edit_text(
            f"✅ *Ticket guardado*\n\n"
            f"🏪 *Negocio:* {negocio}\n"
            f"💰 *Total:* {total}\n\n"
            "_Entra a la app web para facturarlo._",
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.error(f"Error con documento: {e}", exc_info=True)
        await msg.edit_text(
            f"❌ Error al procesar.\n\n"
            f"{str(e)[:200]}\n\n"
            f"Intenta de nuevo.",
            parse_mode="Markdown"
        )


# ─── Arrancar ─────────────────────────────────────────────────────────────────
def main():
    token = os.getenv("TELEGRAM_TOKEN")
    app = Application.builder().token(token).build()

    # ConversationHandler para el flujo de vinculación
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", cmd_start)],
        states={
            ESPERANDO_TELEFONO: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_telefono)
            ],
        },
        fallbacks=[CommandHandler("cancelar", cancelar)],
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("estado", cmd_estado))
    app.add_handler(CommandHandler("ayuda",  cmd_ayuda))
    app.add_handler(MessageHandler(filters.PHOTO,        recibir_foto))
    app.add_handler(MessageHandler(filters.Document.ALL, recibir_documento))

    logger.info("Bot iniciado...")
    app.run_polling()


if __name__ == "__main__":
    main()
