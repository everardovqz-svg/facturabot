# FacturaBot MVP

Bot de Telegram + App web para capturar tickets y facilitar la facturación electrónica en México.

---

## Estructura del proyecto

```
facturabot/
├── main.py          → punto de entrada (bot + web + scheduler)
├── bot.py           → bot de Telegram
├── web.py           → app web con FastAPI
├── claude_ocr.py    → OCR de tickets con Claude
├── database.py      → operaciones con Supabase (incluye SQL)
├── storage.py       → subir imágenes a Cloudflare R2
├── requirements.txt
├── Procfile         → para Railway
├── .env.example     → variables de entorno necesarias
└── templates/
    ├── base.html
    ├── login.html
    ├── registro.html
    ├── dashboard.html
    └── ticket.html
```

---

## Paso 1 — Clonar e instalar

```bash
git clone <tu-repo>
cd facturabot
python -m venv venv
source venv/bin/activate        # Mac/Linux
venv\Scripts\activate           # Windows
pip install -r requirements.txt
cp .env.example .env
```

---

## Paso 2 — Crear el bot de Telegram

1. Abre Telegram y busca **@BotFather**
2. Escribe `/newbot`
3. Ponle nombre: `FacturaBot` (o el que quieras)
4. Ponle usuario: `facturabot_tunombre_bot`
5. Copia el token que te da y ponlo en `.env` como `TELEGRAM_TOKEN`

---

## Paso 3 — Crear proyecto en Supabase

1. Ve a [supabase.com](https://supabase.com) → New project
2. Ve a **SQL Editor** y ejecuta TODO el bloque SQL que está en `database.py` (líneas 8-60 aprox.)
3. Ve a **Settings → API** y copia:
   - `Project URL` → `SUPABASE_URL`
   - `anon public key` → `SUPABASE_KEY`

---

## Paso 4 — Crear bucket en Cloudflare R2

1. Ve a [dash.cloudflare.com](https://dash.cloudflare.com) → R2
2. Crea un bucket llamado `recibos-facturacion`
3. En el bucket → **Settings → Public access** → activa acceso público
4. Ve a **Manage R2 API Tokens** → Create API Token con permisos de lectura/escritura
5. Copia los datos en `.env`

---

## Paso 5 — Obtener API key de Anthropic

1. Ve a [console.anthropic.com](https://console.anthropic.com)
2. API Keys → Create Key
3. Copia en `.env` como `ANTHROPIC_API_KEY`

---

## Paso 6 — Correr localmente

```bash
python main.py
```

- App web: http://localhost:8000
- Bot de Telegram: activo en polling

Para probar: regístrate en http://localhost:8000/registro y sigue las instrucciones para vincular Telegram.

---

## Paso 7 — Deploy en Railway

```bash
# Instala Railway CLI
npm install -g @railway/cli

# Login
railway login

# Nuevo proyecto
railway init

# Agrega las variables de entorno
railway variables set TELEGRAM_TOKEN=xxx
railway variables set ANTHROPIC_API_KEY=xxx
railway variables set SUPABASE_URL=xxx
railway variables set SUPABASE_KEY=xxx
railway variables set R2_ACCOUNT_ID=xxx
railway variables set R2_ACCESS_KEY_ID=xxx
railway variables set R2_SECRET_ACCESS_KEY=xxx
railway variables set R2_BUCKET_NAME=recibos-facturacion
railway variables set R2_PUBLIC_URL=https://tu-bucket.r2.dev
railway variables set SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")

# Deploy
railway up
```

Railway te dará una URL pública tipo `https://facturabot-production.up.railway.app`

---

## Flujo completo del usuario

1. Usuario entra a la app web → se registra con nombre, email y teléfono
2. Ve su **código de empresa** en el dashboard (primeros 8 caracteres del ID)
3. Busca el bot en Telegram → escribe `CODIGO XXXXXXXX`
4. Bot confirma la vinculación
5. Usuario manda fotos de tickets → bot responde con datos detectados
6. En la app web aparecen los tickets con campos listos para copiar
7. Usuario abre el portal de facturación, pega los datos, factura

---

## Notas para Fase 2 (después de validar)

- [ ] Recordatorios automáticos (scheduler ya está listo en main.py)
- [ ] Exportar tickets a Excel
- [ ] Multi-usuario por empresa (ya soportado en BD)
- [ ] Códigos de empresa amigables (ej: TACOS-01)
- [ ] Panel del contador con vista de todos los empleados
- [ ] WhatsApp como add-on (+$100 MXN/mes)
