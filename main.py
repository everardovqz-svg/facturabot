"""
main.py — Punto de entrada principal

Corre simultáneamente:
  - Bot de Telegram (polling)
  - App web FastAPI (uvicorn)
  - Scheduler de recordatorios (APScheduler)

Uso:
  python main.py
"""

import asyncio
import logging
import os
import threading
import uvicorn
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ─── Recordatorios automáticos ────────────────────────────────────────────────
def enviar_recordatorios():
    """
    Corre cada hora y manda mensaje de Telegram a usuarios cuyos
    tickets vencen en menos de 72 horas.
    """
    import database as db
    from telegram import Bot
    import asyncio

    tickets = db.obtener_tickets_por_vencer(horas=72)
    if not tickets:
        return

    bot = Bot(token=os.getenv("TELEGRAM_TOKEN"))

    async def _enviar():
        for ticket in tickets:
            tu = ticket.get("telegram_usuarios")
            if not tu:
                continue
            chat_id = tu.get("chat_id")
            if not chat_id:
                continue

            from datetime import datetime, timezone
            vencimiento = ticket.get("fecha_vencimiento")
            if vencimiento:
                from dateutil import parser as dateparser
                vence_dt = dateparser.parse(vencimiento)
                horas = int((vence_dt - datetime.now(timezone.utc)).total_seconds() / 3600)
                alerta = f"⏱ Vence en *{horas}h*"
            else:
                alerta = "⏱ Próximo a vencer"

            negocio = ticket.get("negocio") or "Negocio desconocido"
            total   = ticket.get("total")   or ""

            try:
                await bot.send_message(
                    chat_id=chat_id,
                    text=(
                        f"🔔 *Recordatorio de facturación*\n\n"
                        f"🏪 {negocio}  {total}\n"
                        f"{alerta}\n\n"
                        f"Entra a la app para facturarlo antes de que venza."
                    ),
                    parse_mode="Markdown",
                )
                logger.info(f"Recordatorio enviado a chat_id {chat_id}")
            except Exception as e:
                logger.error(f"Error enviando recordatorio: {e}")

    asyncio.run(_enviar())


# ─── Servidor web ────────────────────────────────────────────────────────────
def run_web():
    uvicorn.run(
        "web:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8000)),
        log_level="warning",
        loop="asyncio",
    )


# ─── Bot de Telegram ─────────────────────────────────────────────────────────
def run_bot():
    from bot import main as bot_main
    bot_main()


# ─── Main ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logger.info("Iniciando FacturaBot...")

    # Scheduler de recordatorios — corre cada hora
    scheduler = BackgroundScheduler()
    scheduler.add_job(enviar_recordatorios, "interval", hours=1, id="recordatorios")
    scheduler.start()
    logger.info("Scheduler de recordatorios activo.")

    # Web en hilo separado
    web_thread = threading.Thread(target=run_web, daemon=True)
    web_thread.start()
    logger.info("App web iniciada en :8000")

    # Bot en el hilo principal (necesita el event loop)
    logger.info("Bot de Telegram iniciado.")
    asyncio.set_event_loop(asyncio.new_event_loop())
    run_bot()
