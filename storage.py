"""
storage.py — Sube imágenes a Cloudflare R2

R2 es compatible con la API de S3, por eso usamos boto3.
"""

import os
import uuid
import boto3
from dotenv import load_dotenv

load_dotenv()


def get_r2_client():
    return boto3.client(
        "s3",
        endpoint_url=f"https://{os.getenv('R2_ACCOUNT_ID')}.r2.cloudflarestorage.com",
        aws_access_key_id=os.getenv("R2_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY"),
        region_name="auto",
    )


def subir_imagen(imagen_bytes: bytes, empresa_id: str, extension: str = "jpg") -> str:
    """
    Sube una imagen a R2 y devuelve la URL pública.

    Args:
        imagen_bytes: bytes de la imagen
        empresa_id: ID de la empresa (para organizar carpetas)
        extension: jpg, png, webp

    Returns:
        URL pública de la imagen en R2
    """
    nombre_archivo = f"{empresa_id}/{uuid.uuid4()}.{extension}"
    bucket = os.getenv("R2_BUCKET_NAME")

    r2 = get_r2_client()
    r2.put_object(
        Bucket=bucket,
        Key=nombre_archivo,
        Body=imagen_bytes,
        ContentType=f"image/{extension}",
    )

    url_publica = f"{os.getenv('R2_PUBLIC_URL')}/{nombre_archivo}"
    return url_publica
