"""
claude_ocr.py — Procesa imágenes de tickets con Claude

Este módulo:
1. Manda la imagen a Claude con un prompt específico
2. Extrae texto completo + datos estructurados
3. Detecta el portal de facturación correcto
4. Calcula la fecha de vencimiento
"""

import os
import base64
import json
from datetime import datetime, timedelta, timezone
import anthropic
from dotenv import load_dotenv

load_dotenv()

# ─── Base de datos de portales de facturación ────────────────────────────────
# dias_vencimiento: días que tienes para facturar desde la compra
# horas_minimas: tiempo mínimo que debes esperar antes de poder facturar
PORTALES = {
    "oxxo":                  {"url": "https://www4.oxxo.com/facturacionElectronica-web/views/layout/nuevoUsuario.do", "nombre": "OXXO",                   "dias_vencimiento": 60,  "horas_minimas": 24},
    "oxxo gas":              {"url": "https://facturacion.oxxogas.com/",                                              "nombre": "OXXO Gas",                "dias_vencimiento": 30,  "horas_minimas": 0},
    "walmart":               {"url": "https://facturacion.walmartmexico.com.mx/",                                     "nombre": "Walmart",                 "dias_vencimiento": 30,  "horas_minimas": 0},
    "bodega aurrera":        {"url": "https://facturacion.walmartmexico.com.mx/",                                     "nombre": "Bodega Aurrerá",          "dias_vencimiento": 30,  "horas_minimas": 0},
    "sam's":                 {"url": "https://facturacion.walmartmexico.com.mx/",                                     "nombre": "Sam's Club",              "dias_vencimiento": 30,  "horas_minimas": 0},
    "chedraui":              {"url": "https://portal-financiero.chedraui.com.mx/",                                    "nombre": "Chedraui",                "dias_vencimiento": 30,  "horas_minimas": 0},
    "soriana":               {"url": "https://www.soriana.com/facturacion-login",                                     "nombre": "Soriana",                 "dias_vencimiento": 90,  "horas_minimas": 0},
    "la comer":              {"url": "https://www.lacomer.com.mx/emision-cfdiwebangular/",                            "nombre": "La Comer",                "dias_vencimiento": 30,  "horas_minimas": 0},
    "costco":                {"url": "https://www.costco.com.mx/facturacion",                                         "nombre": "Costco",                  "dias_vencimiento": 30,  "horas_minimas": 0},
    "heb":                   {"url": "https://www.heb.com.mx/facturacion",                                            "nombre": "HEB",                     "dias_vencimiento": 30,  "horas_minimas": 0},
    "farmacias guadalajara": {"url": "https://www.farmaciasguadalajara.com/facturacion",                              "nombre": "Farmacias Guadalajara",   "dias_vencimiento": 0,   "horas_minimas": 0,  "horas_vencimiento": 72},
    "benavides":             {"url": "https://www.benavides.com.mx/facturacion",                                      "nombre": "Benavides",               "dias_vencimiento": 0,   "horas_minimas": 2,  "horas_vencimiento": 48},
    "farmacia del ahorro":   {"url": "https://www.fahorro.com/facturacion",                                           "nombre": "Farmacia del Ahorro",     "dias_vencimiento": 30,  "horas_minimas": 0},
    "pemex":                 {"url": "https://facturacion.gasbienestar.pemex.com/",                                   "nombre": "Gas Bienestar / Pemex",   "dias_vencimiento": 30,  "horas_minimas": 0},
    "gas bienestar":         {"url": "https://facturacion.gasbienestar.pemex.com/",                                   "nombre": "Gas Bienestar",           "dias_vencimiento": 30,  "horas_minimas": 0},
    "bp":                    {"url": "https://www.bpmexico.com.mx/facturacion",                                       "nombre": "BP",                      "dias_vencimiento": 30,  "horas_minimas": 0},
    "shell":                 {"url": "https://www.shell.com.mx/facturacion",                                          "nombre": "Shell",                   "dias_vencimiento": 30,  "horas_minimas": 0},
    "home depot":            {"url": "https://facturacion.homedepot.com.mx",                                          "nombre": "The Home Depot",          "dias_vencimiento": 30,  "horas_minimas": 0},
    "office depot":          {"url": "https://www.officedepot.com.mx/facturacion",                                    "nombre": "Office Depot",            "dias_vencimiento": 30,  "horas_minimas": 0},
    "liverpool":             {"url": "https://www.liverpool.com.mx/facturacion",                                      "nombre": "Liverpool",               "dias_vencimiento": 30,  "horas_minimas": 0},
    "starbucks":             {"url": "https://factura.starbucks.com.mx",                                              "nombre": "Starbucks",               "dias_vencimiento": 30,  "horas_minimas": 0},
    "mcdonald's":            {"url": "https://www.mcdonalds.com.mx/facturacion",                                      "nombre": "McDonald's",              "dias_vencimiento": 30,  "horas_minimas": 0},
    "burger king":           {"url": "https://www.burgerking.com.mx/facturacion",                                     "nombre": "Burger King",             "dias_vencimiento": 30,  "horas_minimas": 0},
    "vips":                  {"url": "https://www.vips.com.mx/facturacion",                                           "nombre": "VIPS",                    "dias_vencimiento": 30,  "horas_minimas": 0},
    "cinepolis":             {"url": "https://www.cinepolis.com/facturacion",                                         "nombre": "Cinépolis",               "dias_vencimiento": 30,  "horas_minimas": 0},
    "uber":                  {"url": "https://help.uber.com/riders/article/factura-de-uber",                          "nombre": "Uber",                    "dias_vencimiento": 30,  "horas_minimas": 0},
    "telcel":                {"url": "https://www.telcel.com/facturacion",                                            "nombre": "Telcel",                  "dias_vencimiento": 30,  "horas_minimas": 0},
    "volaris":               {"url": "https://www.volaris.com/facturacion",                                           "nombre": "Volaris",                 "dias_vencimiento": 30,  "horas_minimas": 0},
    "aeromexico":            {"url": "https://www.aeromexico.com/facturacion",                                        "nombre": "Aeroméxico",              "dias_vencimiento": 30,  "horas_minimas": 0},
}


def buscar_portal(nombre_negocio: str) -> dict | None:
    """Busca el portal de facturación por nombre del negocio."""
    if not nombre_negocio:
        return None
    lw = nombre_negocio.lower().strip()
    for key, val in PORTALES.items():
        if key in lw or lw in key:
            return val
    return None


def calcular_vencimiento(portal: dict, fecha_ticket_str: str) -> datetime | None:
    """
    Calcula la fecha exacta en que vence la facturación.
    Si no puede parsear la fecha del ticket, usa la fecha actual.
    """
    try:
        # Intenta parsear la fecha del ticket (varios formatos comunes)
        for fmt in ["%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y"]:
            try:
                base = datetime.strptime(fecha_ticket_str, fmt)
                base = base.replace(tzinfo=timezone.utc)
                break
            except ValueError:
                continue
        else:
            base = datetime.now(timezone.utc)
    except Exception:
        base = datetime.now(timezone.utc)

    # Farmacias Guadalajara y Benavides vencen en horas, no días
    if "horas_vencimiento" in portal:
        return base + timedelta(hours=portal["horas_vencimiento"])

    return base + timedelta(days=portal["dias_vencimiento"])


async def procesar_ticket(imagen_bytes: bytes, mime_type: str = "image/jpeg") -> dict:

    try:
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        imagen_b64 = base64.standard_b64encode(imagen_bytes).decode("utf-8")

        # ─── PASO 1: Leer el ticket libremente, igual que haría un humano ────────
        respuesta_lectura = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1500,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": mime_type,
                            "data": imagen_b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": "Transcribe todo el texto que ves en este ticket o recibo exactamente como aparece, de arriba a abajo, sin omitir nada. Solo el texto, sin comentarios ni explicaciones.\n\nPresta especial atención a los números — transcríbelos con máxima precisión. Si tienes duda entre un 9 y un 5, o entre un 6 y un 8, descríbelo tal como aparece en el ticket sin interpretar. Es mejor transcribir exacto que interpretar mal."
                    }
                ],
            }]
        )

        texto_completo = respuesta_lectura.content[0].text.strip()

        # ─── PASO 2: Estructurar los datos a partir del texto ya extraído ────────
        respuesta_datos = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=800,
            messages=[{
                "role": "user",
                "content": f"""Del siguiente texto de un ticket mexicano, extrae los datos para facturación.

TEXTO DEL TICKET:
{texto_completo}

Responde SOLO con el JSON, sin texto adicional, sin markdown:
{{"negocio":"","rfc_negocio":"","fecha":"","total":"","iva":"","ieps":"","subtotal":"","forma_pago":"","direccion":"","cp":"","folio":"","web_id":"","tc":"","tr":"","tda":"","op":"","aprobacion":"","url_facturacion_ticket":"","plazo_facturacion":""}}

Reglas:
- tc: si el valor empieza con "TCH" seguido de números, extrae solo los dígitos (ejemplo: "TCH736846830891970637422" → "736846830891970637422"). El campo tc solo debe contener los dígitos, sin prefijo TC#, TCH ni similar
- fecha en formato DD/MM/YYYY
- total es el monto final, no el subtotal
- tc son solo dígitos, no confundir con CSH o ID CASHI
- folio es el número principal del comprobante, no el número de estación; copia el número exactamente como aparece en la transcripción, sin modificar ningún dígito
- si un dato no aparece déjalo vacío
- si un número es ambiguo escribe las dos posibilidades separadas por /"""
            }]
        )

        import json, re
        json_text = respuesta_datos.content[0].text.strip()
        json_text = re.sub(r"```json|```", "", json_text).strip()

        try:
            datos = json.loads(json_text)
        except json.JSONDecodeError:
            datos = {}

        # Limpiar TC# — la impresora térmica a veces imprime # como H
        tc = datos.get("tc", "")
        if tc.upper().startswith("TCH"):
            tc = tc[3:]  # quitar "TCH"
        elif tc.upper().startswith("TC#"):
            tc = tc[3:]  # quitar "TC#"
        elif tc.upper().startswith("TC"):
            tc = tc[2:]  # quitar "TC"
        datos["tc"] = tc.strip()

        # Formato visual con prefijo para mostrar en pantalla
        def formatear_campo_ticket(prefijo: str, valor: str) -> str:
            """Agrega prefijo con # y espacio para mostrar en pantalla."""
            if not valor:
                return ""
            return f"{prefijo}# {valor.strip()}"

        datos["tc_display"]  = formatear_campo_ticket("TC",  datos.get("tc", ""))
        datos["tr_display"]  = formatear_campo_ticket("TR",  datos.get("tr", ""))
        datos["tda_display"] = formatear_campo_ticket("TDA", datos.get("tda", ""))
        datos["op_display"]  = formatear_campo_ticket("OP",  datos.get("op", ""))

        portal = buscar_portal(datos.get("negocio", ""))
        fecha_vencimiento = None
        if portal:
            fecha_vencimiento = calcular_vencimiento(portal, datos.get("fecha", ""))

        return {
            "texto_completo":       texto_completo,
            "negocio":              datos.get("negocio", ""),
            "rfc_negocio":          datos.get("rfc_negocio", ""),
            "fecha_ticket":         datos.get("fecha", ""),
            "total":                datos.get("total", ""),
            "iva":                  datos.get("iva", ""),
            "ieps":                 datos.get("ieps", ""),
            "subtotal":             datos.get("subtotal", ""),
            "forma_pago":           datos.get("forma_pago", ""),
            "direccion":            datos.get("direccion", ""),
            "cp":                   datos.get("cp", ""),
            "folio":                datos.get("folio", ""),
            "web_id":               datos.get("web_id", ""),
            "tc":                   datos.get("tc", ""),
            "tr":                   datos.get("tr", ""),
            "tda":                  datos.get("tda", ""),
            "op":                   datos.get("op", ""),
            "tc_display":           datos.get("tc_display", ""),
            "tr_display":           datos.get("tr_display", ""),
            "tda_display":          datos.get("tda_display", ""),
            "op_display":           datos.get("op_display", ""),
            "aprobacion":           datos.get("aprobacion", ""),
            "url_facturacion_ticket": datos.get("url_facturacion_ticket", ""),
            "plazo_facturacion":    datos.get("plazo_facturacion", ""),
            "portal_url":           portal["url"] if portal else None,
            "portal_nombre":        portal["nombre"] if portal else None,
            "fecha_vencimiento":    fecha_vencimiento,
            "error":                None,
        }

    except Exception as e:
        return {
            "texto_completo":         "",
            "negocio":                "",
            "rfc_negocio":            "",
            "fecha_ticket":           "",
            "total":                  "",
            "iva":                    "",
            "ieps":                   "",
            "subtotal":               "",
            "forma_pago":             "",
            "direccion":              "",
            "cp":                     "",
            "folio":                  "",
            "web_id":                 "",
            "tc":                     "",
            "tr":                     "",
            "tda":                    "",
            "op":                     "",
            "aprobacion":             "",
            "url_facturacion_ticket": "",
            "plazo_facturacion":      "",
            "portal_url":             None,
            "portal_nombre":          None,
            "fecha_vencimiento":      None,
            "error":                  str(e),
        }
