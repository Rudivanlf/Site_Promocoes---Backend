from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

# --- SEGURANÇA E AMBIENTE ---
SECRET_KEY = "django-insecure-)s@fwddpff6@ew6qso8i!_tkz_=ud10z8tb2!1brr4_r8myb#e"
DEBUG = os.environ.get("DEBUG", "False").lower() in ("true", "1", "t")
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "*").split(",")

# --- CONFIGURAÇÕES DE HTTPS PARA VERCEL ---
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
USE_X_FORWARDED_HOST = True
USE_X_FORWARDED_PORT = True

# --- CORS & CSRF ---
CORS_ALLOW_ALL_ORIGINS = False 
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOWED_ORIGINS = os.environ.get("CORS_ALLOWED_ORIGINS", "").split(",")
CSRF_TRUSTED_ORIGINS = os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",")

# Application definition
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "app",
    "app.features.usuarios",
    "app.features.produtos",
    "app.features.alertas",
    "app.features.busca_inteligente",
    "app.features.historico_precos",
    "app.features.email",
    "rest_framework",
    "corsheaders",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware", # Sempre aqui no topo
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "app.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# Database - Lógica de troca de banco
if os.environ.get("USE_MONGO", "1") == "1":
    DATABASES = {
        "default": {
            "ENGINE": "django_mongodb", # NÃO use 'djongo' aqui!
            "NAME": os.environ.get("MONGO_DB_NAME", "site_promocoes_db"),
            "ENFORCE_SCHEMA": False,
            "CLIENT": {
                "host": os.environ.get("MONGO_URI"),
            },
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

# Resto das configurações padrões...
LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
MEDIA_URL = "media/"
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
}

# Configurações Extras (Google/JWT)
GOOGLE_CLIENT_SECRET_JSON = os.environ.get('GOOGLE_CLIENT_SECRET_JSON')
GOOGLE_TOKEN_JSON = os.environ.get('GOOGLE_TOKEN_JSON')
EMAIL_USER = os.environ.get('EMAIL_USER', 'seu-email@gmail.com')
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:5173")
GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID')
JWT_SECRET = os.environ.get("JWT_SECRET", SECRET_KEY)
JWT_ALGORITHM = "HS256"
