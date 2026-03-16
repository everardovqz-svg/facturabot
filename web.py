"""
web.py — App web con FastAPI

Autenticación: email + contraseña
Teléfono: opcional, solo para vincular bot de Telegram automáticamente

Rutas:
  GET  /              → login (email + contraseña)
  POST /login         → autentica y guarda sesión
  GET  /registro      → formulario de registro
  POST /registro      → crea empresa nueva
  GET  /dashboard     → lista de tickets pendientes
  GET  /ticket/{id}   → detalle de un ticket
  POST /ticket/{id}/estado → cambia estado
  GET  /logout        → cierra sesión
"""

import os
import secrets
import hashlib
from fastapi import FastAPI, Request, Form, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv
from supabase import create_client

import database as db

load_dotenv()

app = FastAPI(title="FacturaBot Web")
templates = Jinja2Templates(directory="templates")

# Sesiones en memoria (MVP — migrar a Supabase sessions en Fase 2)
sesiones: dict[str, str] = {}  # token → empresa_id


def get_supabase():
    return create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))


def hash_password(password: str) -> str:
    """Hash simple con SHA-256 + salt fijo de la SECRET_KEY."""
    salt = os.getenv("SECRET_KEY", "fallback-salt")
    return hashlib.sha256(f"{salt}{password}".encode()).hexdigest()


def get_empresa_id(request: Request) -> str | None:
    token = request.cookies.get("session")
    return sesiones.get(token)


def crear_sesion(empresa_id: str) -> str:
    token = secrets.token_hex(32)
    sesiones[token] = empresa_id
    return token


# ─── Login ────────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def login_page(request: Request):
    if get_empresa_id(request):
        return RedirectResponse(url="/dashboard")
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login")
async def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
):
    sb = get_supabase()
    res = (sb.table("empresas")
             .select("*")
             .eq("email", email.strip().lower())
             .execute())
    empresa = res.data[0] if res.data else None

    if not empresa or empresa.get("password_hash") != hash_password(password):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Email o contraseña incorrectos."},
        )

    token = crear_sesion(empresa["id"])
    response = RedirectResponse(url="/dashboard", status_code=302)
    response.set_cookie("session", token, httponly=True, max_age=86400 * 7)
    return response


@app.get("/logout")
async def logout(request: Request):
    token = request.cookies.get("session")
    if token:
        sesiones.pop(token, None)
    response = RedirectResponse(url="/", status_code=302)
    response.delete_cookie("session")
    return response


# ─── Registro ────────────────────────────────────────────────────────────────
@app.get("/registro", response_class=HTMLResponse)
async def registro_page(request: Request):
    return templates.TemplateResponse("registro.html", {"request": request})


@app.post("/registro")
async def registro(
    request: Request,
    nombre: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    telefono: str = Form(""),   # opcional — solo para vincular Telegram
):
    if len(password) < 6:
        return templates.TemplateResponse(
            "registro.html",
            {"request": request, "error": "La contraseña debe tener al menos 6 caracteres."},
        )

    try:
        sb = get_supabase()
        datos = {
            "nombre":        nombre.strip(),
            "email":         email.strip().lower(),
            "password_hash": hash_password(password),
        }
        # Solo guardar teléfono si lo proporcionó
        tel = telefono.strip().replace(" ", "").replace("-", "")
        if tel:
            datos["telefono"] = tel

        res = sb.table("empresas").insert(datos).execute()
        empresa = res.data[0]

        token = crear_sesion(empresa["id"])
        response = RedirectResponse(url="/dashboard", status_code=302)
        response.set_cookie("session", token, httponly=True, max_age=86400 * 7)
        return response

    except Exception as e:
        return templates.TemplateResponse(
            "registro.html",
            {"request": request, "error": "Ese email ya está registrado."},
        )


# ─── Dashboard ────────────────────────────────────────────────────────────────
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, filtro: str = "pendiente"):
    empresa_id = get_empresa_id(request)
    if not empresa_id:
        return RedirectResponse(url="/")

    sb = get_supabase()
    res = (sb.table("empresas")
               .select("*")
               .eq("id", empresa_id)
               .execute())
    empresa = res.data[0] if res.data else None

    estado_filtro = filtro if filtro in ("pendiente", "facturado", "ignorado") else "pendiente"
    tickets = db.obtener_tickets_empresa(empresa_id, estado=estado_filtro)

    todos = db.obtener_tickets_empresa(empresa_id)
    conteos = {"pendiente": 0, "facturado": 0, "ignorado": 0}
    for t in todos:
        conteos[t["estado"]] = conteos.get(t["estado"], 0) + 1

    return templates.TemplateResponse("dashboard.html", {
        "request":    request,
        "empresa":    empresa,
        "tickets":    tickets,
        "filtro":     estado_filtro,
        "conteos":    conteos,
        "empresa_id": empresa_id,
        "tiene_telegram": bool(empresa.get("telefono")),
    })


# ─── Detalle de ticket ───────────────────────────────────────────────────────
@app.get("/ticket/{ticket_id}", response_class=HTMLResponse)
async def detalle_ticket(ticket_id: str, request: Request):
    empresa_id = get_empresa_id(request)
    if not empresa_id:
        return RedirectResponse(url="/")

    sb = get_supabase()
    res = (sb.table("tickets")
               .select("*")
               .eq("id", ticket_id)
               .execute())
    ticket = res.data[0] if res.data else None

    if not ticket or ticket["empresa_id"] != empresa_id:
        raise HTTPException(status_code=404, detail="Ticket no encontrado")

    from claude_ocr import buscar_portal
    portal_info = buscar_portal(ticket.get("negocio", ""))

    # Campos display: prefijo visual para mostrar, valor limpio para copiar
    def _display(prefijo, valor):
        return f"{prefijo}# {valor.strip()}" if valor else ""

    ticket["tc_display"]  = _display("TC",  ticket.get("tc", ""))
    ticket["tr_display"]  = _display("TR",  ticket.get("tr", ""))
    ticket["tda_display"] = _display("TDA", ticket.get("tda", ""))
    ticket["op_display"]  = _display("OP",  ticket.get("op", ""))

    return templates.TemplateResponse("ticket.html", {
        "request":     request,
        "ticket":      ticket,
        "portal_info": portal_info,
    })


# ─── Cambiar estado ──────────────────────────────────────────────────────────
@app.post("/ticket/{ticket_id}/estado")
async def cambiar_estado(
    ticket_id: str,
    request: Request,
    estado: str = Form(...),
):
    empresa_id = get_empresa_id(request)
    if not empresa_id:
        return RedirectResponse(url="/")

    if estado not in ("pendiente", "facturado", "ignorado"):
        raise HTTPException(status_code=400, detail="Estado inválido")

    db.actualizar_estado_ticket(ticket_id, estado)
    return RedirectResponse(url="/dashboard", status_code=302)


# ─── Upload desde web (Ctrl+V) ──────────────────────────────────────────────
@app.post("/upload")
async def upload_desde_web(request: Request, file: UploadFile = File(...)):
    empresa_id = get_empresa_id(request)
    if not empresa_id:
        return {"ok": False, "error": "No autenticado"}

    import claude_ocr, storage

    try:
        imagen_bytes = await file.read()
        mime = file.content_type or "image/jpeg"
        ext = mime.split("/")[-1]

        imagen_url = storage.subir_imagen(imagen_bytes, empresa_id=empresa_id, extension=ext)
        resultado = await claude_ocr.procesar_ticket(imagen_bytes, mime)

        if resultado.get("error"):
            return {"ok": False, "error": resultado["error"]}

        db.guardar_ticket({
            "empresa_id":         empresa_id,
            "negocio":            resultado.get("negocio", ""),
            "fecha_ticket":       resultado.get("fecha_ticket", ""),
            "total":              resultado.get("total", ""),
            "iva":                resultado.get("iva", ""),
            "subtotal":           resultado.get("subtotal", ""),
            "forma_pago":         resultado.get("forma_pago", ""),
            "folio":              resultado.get("folio", ""),
            "rfc_negocio":        resultado.get("rfc_negocio", ""),
            "direccion":          resultado.get("direccion", ""),
            "tc":                 resultado.get("tc", ""),
            "tr":                 resultado.get("tr", ""),
            "ieps":               resultado.get("ieps", ""),
            "tda":                resultado.get("tda", ""),
            "op":                 resultado.get("op", ""),
            "web_id":             resultado.get("web_id", ""),
            "aprobacion":         resultado.get("aprobacion", ""),
            "cp":                 resultado.get("cp", ""),
            "texto_completo":     resultado.get("texto_completo", ""),
            "imagen_url":         imagen_url,
            "portal_facturacion": resultado["portal_url"],
            "estado":             "pendiente",
            "fecha_vencimiento":  resultado["fecha_vencimiento"].isoformat()
                                  if resultado["fecha_vencimiento"] else None,
        })
        return {
            "ok":          True,
            "negocio":     resultado["negocio"],
            "total":       resultado["total"],
            "fecha_ticket": resultado["fecha_ticket"],
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ─── Arrancar ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("web:app", host="0.0.0.0", port=8000, reload=True)
