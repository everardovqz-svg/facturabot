"""
database.py — Operaciones con Supabase

ANTES DE USAR: ejecuta este SQL en Supabase → SQL Editor:

--------------------------------------------------------------
-- EMPRESAS: cada cliente que se registra en la app web
create table empresas (
  id uuid primary key default gen_random_uuid(),
  nombre text not null,
  email text unique not null,
  password_hash text not null,
  telefono text unique,           -- OPCIONAL: solo para vincular bot de Telegram
  created_at timestamptz default now()
);

-- USUARIOS DE TELEGRAM: empleados que mandan fotos por el bot
create table telegram_usuarios (
  id uuid primary key default gen_random_uuid(),
  empresa_id uuid references empresas(id) on delete cascade,
  chat_id bigint unique not null,  -- ID que da Telegram
  nombre text,
  activo boolean default true,
  created_at timestamptz default now()
);

-- TICKETS: cada recibo procesado
create table tickets (
  id uuid primary key default gen_random_uuid(),
  empresa_id uuid references empresas(id) on delete cascade,
  telegram_usuario_id uuid references telegram_usuarios(id),
  negocio text,
  fecha_ticket text,
  total text,
  iva text,
  subtotal text,
  forma_pago text,
  numero_ticket text,
  numero_caja text,
  numero_transaccion text,
  folio text,
  rfc_negocio text,
  direccion text,
  texto_completo text,            -- texto raw extraído por Claude
  imagen_url text,                -- URL en Cloudflare R2
  portal_facturacion text,        -- URL del portal detectado
  estado text default 'pendiente', -- pendiente | facturado | ignorado
  fecha_vencimiento timestamptz,  -- cuándo vence la facturación
  created_at timestamptz default now()
);

-- PORTALES: para recordatorios de vencimiento
-- (ya están hardcodeados en claude.py pero esta tabla permite actualizarlos)
create table portales (
  id uuid primary key default gen_random_uuid(),
  nombre text not null,
  url text not null,
  dias_vencimiento integer default 30,
  horas_minimas integer default 0,  -- mínimo de horas antes de poder facturar
  notas text
);

-- Índices para queries frecuentes
create index on tickets(empresa_id, estado);
create index on tickets(empresa_id, created_at desc);
create index on telegram_usuarios(chat_id);
--------------------------------------------------------------
"""

import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

# ─── Cliente de Supabase ──────────────────────────────────────────────────────
def get_client() -> Client:
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    return create_client(url, key)


# ─── Empresas ────────────────────────────────────────────────────────────────
def obtener_empresa_por_telefono(telefono: str) -> dict | None:
    """Busca una empresa por número de teléfono (login de la web)."""
    sb = get_client()
    res = sb.table("empresas").select("*").eq("telefono", telefono).execute()
    return res.data[0] if res.data else None


def crear_empresa(nombre: str, email: str, telefono: str) -> dict:
    """Registra una empresa nueva."""
    sb = get_client()
    res = sb.table("empresas").insert({
        "nombre": nombre,
        "email": email,
        "telefono": telefono,
    }).execute()
    return res.data[0]


# ─── Usuarios de Telegram ────────────────────────────────────────────────────
def obtener_usuario_telegram(chat_id: int) -> dict | None:
    """Busca un usuario por su chat_id de Telegram."""
    sb = get_client()
    res = (sb.table("telegram_usuarios")
             .select("*, empresas(*)")
             .eq("chat_id", chat_id)
             .eq("activo", True)
             .execute())
    return res.data[0] if res.data else None


def registrar_usuario_telegram(chat_id: int, empresa_id: str, nombre: str) -> dict:
    """Vincula un chat_id de Telegram con una empresa."""
    sb = get_client()
    res = sb.table("telegram_usuarios").upsert({
        "chat_id": chat_id,
        "empresa_id": empresa_id,
        "nombre": nombre,
        "activo": True,
    }).execute()
    return res.data[0]


# ─── Tickets ─────────────────────────────────────────────────────────────────
def guardar_ticket(datos: dict) -> dict:
    """
    Guarda un ticket procesado.
    datos debe incluir: empresa_id, negocio, total, texto_completo, etc.
    """
    sb = get_client()
    try:
        res = sb.table("tickets").insert(datos).execute()
        return res.data[0]
    except Exception as e:
        msg = str(e)
        # Detectar errores de columna inexistente (Supabase/PostgREST)
        import re
        match = re.search(r'column ["\']?(\w+)["\']? of relation', msg)
        if not match:
            match = re.search(r'Unknown column[:\s]+["\']?(\w+)["\']?', msg, re.IGNORECASE)
        if match:
            columna = match.group(1)
            raise RuntimeError(
                f"Falta ejecutar SQL en Supabase — columna: {columna}"
            ) from e
        raise


def obtener_tickets_empresa(empresa_id: str, estado: str = None) -> list:
    """Lista tickets de una empresa. Opcionalmente filtra por estado."""
    sb = get_client()
    query = (sb.table("tickets")
               .select("*")
               .eq("empresa_id", empresa_id)
               .order("created_at", desc=True))
    if estado:
        query = query.eq("estado", estado)
    return query.execute().data


def actualizar_estado_ticket(ticket_id: str, estado: str) -> dict:
    """Cambia el estado de un ticket: pendiente | facturado | ignorado."""
    sb = get_client()
    res = (sb.table("tickets")
             .update({"estado": estado})
             .eq("id", ticket_id)
             .execute())
    return res.data[0]


def obtener_tickets_por_vencer(horas: int = 72) -> list:
    """
    Devuelve tickets pendientes cuya fecha de vencimiento
    es en menos de `horas` horas. Usado por el scheduler de recordatorios.
    """
    from datetime import datetime, timedelta, timezone
    sb = get_client()
    ahora = datetime.now(timezone.utc)
    limite = ahora + timedelta(hours=horas)
    res = (sb.table("tickets")
             .select("*, empresas(*), telegram_usuarios(*)")
             .eq("estado", "pendiente")
             .lte("fecha_vencimiento", limite.isoformat())
             .gte("fecha_vencimiento", ahora.isoformat())
             .execute())
    return res.data
