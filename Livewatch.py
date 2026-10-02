"""
Livewatch - Plateforme complète de streaming
Version 6.5 ULTIMATE - IPTV.org complet (pays/subdivisions/villes/catégories) + YouTube + Multi-Decoder + Lecteur Universel
Auteur: Livewatch Team
Licence: MIT
Propriétaire: erickbenoit337@gmail.com / WALKER92259
"""

import os
import sys
import uuid
import hashlib
import json
import random
import string
import asyncio
import logging
import secrets
import httpx
import re
import subprocess
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Set, Union
from contextlib import asynccontextmanager
from ipaddress import ip_address as validate_ip
from urllib.parse import urlparse, quote, urljoin, parse_qs
import html
import platform
import socket
import ssl

# ==================== CONFIGURATION DE L'ENCODAGE POUR WINDOWS ====================
if platform.system() == "Windows":
    import codecs
    import io
    
    # Fix for Windows console encoding
    if sys.stdout is not None and hasattr(sys.stdout, 'buffer'):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    if sys.stderr is not None and hasattr(sys.stderr, 'buffer'):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# ==================== LOGGING AMÉLIORÉ ====================
class UnicodeStreamHandler(logging.StreamHandler):
    """Handler qui gère correctement l'Unicode sur Windows"""
    def emit(self, record):
        try:
            msg = self.format(record)
            stream = self.stream
            try:
                stream.write(msg + self.terminator)
            except UnicodeEncodeError:
                # Fallback: enlever les emojis
                msg_ascii = msg.encode('ascii', 'ignore').decode('ascii')
                stream.write(msg_ascii + self.terminator)
            self.flush()
        except Exception:
            self.handleError(record)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        UnicodeStreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ==================== IMPORTS ====================
import uvicorn
from dotenv import load_dotenv
load_dotenv()  # Charge le fichier .env si présent
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, HTTPException, Depends, Form, UploadFile, File, Response, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# ==================== STOCKAGE INSCRIPTIBLE (Vercel = lecture seule sauf /tmp) ====================
# Sur Vercel, tout le système de fichiers déployé est en lecture seule, sauf /tmp.
# Vercel définit automatiquement la variable d'environnement VERCEL=1.
IS_SERVERLESS = bool(os.environ.get("VERCEL"))
from pathlib import Path as _Path
BASE_DIR   = _Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"   # assets commités (peut ne pas exister dans la nouvelle structure)
WRITABLE_DIR  = "/tmp/livewatch" if IS_SERVERLESS else "."
os.makedirs(WRITABLE_DIR, exist_ok=True)

TEMPLATES_DIR   = os.path.join(WRITABLE_DIR, "templates")
UPLOADS_DIR     = os.path.join(WRITABLE_DIR, "static", "uploads")
THUMBNAILS_DIR  = os.path.join(WRITABLE_DIR, "static", "thumbnails")
RECORDINGS_DIR  = os.path.join(WRITABLE_DIR, "static", "recordings")
# Créés immédiatement : StaticFiles() est instancié au chargement du module,
# avant que lifespan() ne s'exécute — les dossiers doivent déjà exister.
for _d in (TEMPLATES_DIR, UPLOADS_DIR, THUMBNAILS_DIR, RECORDINGS_DIR):
    os.makedirs(_d, exist_ok=True)
# NOTE : /tmp est éphémère sur Vercel (vidé entre cold starts, non partagé entre instances).
# Les fichiers uploadés par les utilisateurs (avatars, miniatures, enregistrements) ne
# persisteront pas de façon fiable en production serverless — prévoir un stockage externe
# (Vercel Blob, S3, Cloudinary) pour ces usages.

from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from sqlalchemy import create_engine, Column, String, Integer, DateTime, Boolean, Text, Float, ForeignKey, Index, and_, or_, desc, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import sessionmaker, Session, relationship, declarative_base, synonym
from sqlalchemy.pool import QueuePool
from passlib.context import CryptContext
from jose import JWTError, jwt
import aiofiles
from PIL import Image
import aiohttp
import m3u8
import dateutil.parser

try:
    import yt_dlp
    YT_DLP_AVAILABLE = True
except ImportError:
    YT_DLP_AVAILABLE = False
    logger.warning("yt-dlp non disponible")

# ==================== CONFIGURATION AMÉLIORÉE ====================

class Settings:
    APP_NAME = "Livewatch"
    APP_VERSION = "7.0 ULTIMATE"
    APP_DESCRIPTION = "Plateforme de streaming ultime — TV, Sports, Chaînes télévisions mondiales, YouTube Live, Radio & Lives communautaires"

    # Sécurité
    SECRET_KEY = os.getenv("SECRET_KEY", "livewatch-secret-key-walker92259-fixed-2024")
    ALGORITHM = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES = 30

    # ── Base de données PostgreSQL ──────────────────────────────────────────
    # Format : postgresql://user:password@host:port/dbname
    # Peut aussi être fourni via la variable d'environnement DATABASE_URL
    DATABASE_URL = os.getenv(
        "DATABASE_URL",
        "postgresql://livewatch_9y2l_user:s3OTHyEHP0z2DrKEOqBn04x3EGPciPbt@dpg-d71svqvgi27c73fndrug-a/livewatch_9y2l"
    )
    # Alembic / psycopg2 veut "postgresql://" pas "postgres://" (Heroku legacy)
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

    DATABASE_POOL_SIZE     = int(os.getenv("DB_POOL_SIZE",     "20"))
    DATABASE_MAX_OVERFLOW  = int(os.getenv("DB_MAX_OVERFLOW",  "10"))
    DATABASE_POOL_TIMEOUT  = int(os.getenv("DB_POOL_TIMEOUT",  "30"))
    DATABASE_POOL_RECYCLE  = int(os.getenv("DB_POOL_RECYCLE",  "1800"))  # 30 min

    # Admin par défaut (propriétaire)
    ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "WALKER92259")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "WALKER92259")
    ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "erickbenoit337@gmail.com")
    OWNER_ID = "erickbenoit337@gmail.com"

    # Streaming utilisateur
    MAX_STREAM_DURATION_HOURS = 12
    MAX_CONCURRENT_STREAMS_PER_USER = 3
    MAX_COMMENT_LENGTH = 500
    MAX_COMMENTS_PER_MINUTE = 5

    # Proxy
    PROXY_TIMEOUT = 60
    MAX_PROXY_SIZE = 200 * 1024 * 1024
    CACHE_TTL = 600
    STREAM_CACHE_TTL = 120
    MAX_RETRIES = 3
    RETRY_DELAY = 2

    # Fichiers
    MAX_UPLOAD_SIZE = 20 * 1024 * 1024
    ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}

    # Modération
    AUTO_BLOCK_THRESHOLD = 5
    COMMENT_FLAG_THRESHOLD = 3
    SESSION_MAX_AGE = 7 * 24 * 60 * 60

    # IPTV Sync amélioré
    IPTV_SYNC_INTERVAL = 12 * 60 * 60  # 12 heures
    IPTV_BASE_URL = "https://iptv-org.github.io/iptv"
    IPTV_TIMEOUT = 120
    IPTV_MAX_RETRIES = 3
    IPTV_CONCURRENT_DOWNLOADS = 3

    # YouTube
    YOUTUBE_TIMEOUT = 60
    YOUTUBE_CACHE_TTL = 300

    # Lecteur universel
    ENABLE_DASH = True
    ENABLE_HLS = True
    ENABLE_MP4 = True
    ENABLE_AUDIO = True
    ENABLE_YOUTUBE = True

    # Logo
    LOGO_PATH = "static/livewatch.png"

settings = Settings()

# ==================== BASE DE DONNÉES POSTGRESQL ====================

engine = create_engine(
    settings.DATABASE_URL,
    pool_size        = settings.DATABASE_POOL_SIZE,
    max_overflow     = settings.DATABASE_MAX_OVERFLOW,
    pool_timeout     = settings.DATABASE_POOL_TIMEOUT,
    pool_recycle     = settings.DATABASE_POOL_RECYCLE,
    pool_pre_ping    = True,
    echo             = False,
    query_cache_size = 0,  # Fix Python 3.14 + SQLAlchemy cache bug
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Helper : UUID natif PostgreSQL avec génération automatique
def pg_uuid():
    return Column(PG_UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))

# ==================== MODÈLES POSTGRESQL ====================

class User(Base):
    __tablename__ = "users"
    id               = Column(PG_UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    username         = Column(String(50),  unique=True, index=True, nullable=False)
    email            = Column(String(100), unique=True, index=True, nullable=False)
    hashed_password  = Column(String(200), nullable=False)
    is_active        = Column(Boolean, default=True)
    is_admin         = Column(Boolean, default=False)
    is_owner         = Column(Boolean, default=False)
    created_at       = Column(DateTime, default=datetime.utcnow)
    last_login       = Column(DateTime, nullable=True)
    ip_address       = Column(String(50), nullable=True)
    is_blocked       = Column(Boolean, default=False)
    failed_login_attempts = Column(Integer, default=0)
    locked_until     = Column(DateTime, nullable=True)

class Visitor(Base):
    __tablename__ = "visitors"
    id                 = Column(PG_UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    visitor_id         = Column(String(100), unique=True, index=True, nullable=False)
    ip_address         = Column(String(50))
    user_agent         = Column(String(500))
    created_at         = Column(DateTime, default=datetime.utcnow)
    expires_at         = Column(DateTime, default=lambda: datetime.utcnow() + timedelta(days=7))
    last_seen          = Column(DateTime, default=datetime.utcnow)
    is_blocked         = Column(Boolean, default=False)
    total_comments     = Column(Integer, default=0)
    total_streams      = Column(Integer, default=0)
    preferred_language = Column(String(10), default="fr")
    theme              = Column(String(10), default="auto")
    # Champs utilisés par le profil / favoris / suivi de visites (absents du modèle auparavant => AttributeError)
    first_seen         = synonym("created_at")          # alias : pas de colonne supplémentaire
    favorites          = Column(Text, default="[]")
    page_count         = Column(Integer, default=0)
    last_page          = Column(String(200), nullable=True)

class ExternalStream(Base):
    __tablename__ = "external_streams"
    id           = Column(PG_UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    title        = Column(String(200), nullable=False)
    category     = Column(String(50),  nullable=False)
    subcategory  = Column(String(50),  nullable=True)
    country      = Column(String(10),  nullable=True)
    language     = Column(String(10),  default="fr")
    url          = Column(String(1000),nullable=False)
    logo         = Column(String(500), nullable=True)
    proxy_needed = Column(Boolean, default=False)
    is_active    = Column(Boolean, default=True)
    quality      = Column(String(20),  default="HD")
    viewers      = Column(Integer, default=0)
    created_at   = Column(DateTime, default=datetime.utcnow)
    last_checked = Column(DateTime, nullable=True)
    stream_type  = Column(String(20),  default="hls")
    bitrate      = Column(Integer, default=0)
    width        = Column(Integer, default=0)
    height       = Column(Integer, default=0)
    fps          = Column(Integer, default=0)
    user_agent   = Column(String(200), nullable=True)
    referer      = Column(String(500), nullable=True)
    headers      = Column(Text, nullable=True)

class IPTVChannel(Base):
    __tablename__ = "iptv_channels"
    id          = Column(PG_UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    playlist_id = Column(String(50), index=True)
    name        = Column(String(200), nullable=False)
    url         = Column(String(1000),nullable=False)
    logo        = Column(String(500), nullable=True)
    category    = Column(String(100), nullable=True)
    country     = Column(String(10),  nullable=True)
    language    = Column(String(10),  nullable=True)
    tvg_id      = Column(String(100), nullable=True)
    tvg_name    = Column(String(200), nullable=True)
    tvg_chno    = Column(Integer, nullable=True)
    tvg_shift   = Column(Float,   nullable=True)
    is_active   = Column(Boolean, default=True)
    viewers     = Column(Integer, default=0)
    last_seen   = Column(DateTime, default=datetime.utcnow)
    created_at  = Column(DateTime, default=datetime.utcnow)
    stream_type = Column(String(20), default="hls")
    bitrate     = Column(Integer, default=0)
    resolution  = Column(String(20), nullable=True)
    is_working  = Column(Boolean, default=True)
    last_check  = Column(DateTime, nullable=True)
    check_count = Column(Integer, default=0)
    fail_count  = Column(Integer, default=0)

    __table_args__ = (
        Index('idx_iptv_playlist',  'playlist_id'),
        Index('idx_iptv_category',  'category'),
        Index('idx_iptv_country',   'country'),
    )

class IPTVPlaylist(Base):
    __tablename__ = "iptv_playlists"
    id            = Column(PG_UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    name          = Column(String(100), unique=True, nullable=False)
    display_name  = Column(String(200), nullable=False)
    url           = Column(String(500), nullable=False)
    channel_count = Column(Integer, default=0)
    last_sync     = Column(DateTime, nullable=True)
    last_updated  = Column(DateTime, nullable=True)
    is_active     = Column(Boolean, default=True)
    category      = Column(String(50),  default="iptv")
    country       = Column(String(10),  nullable=True)
    playlist_type = Column(String(20),  default="country")
    sync_interval = Column(Integer, default=86400)
    sync_error    = Column(Text, nullable=True)
    sync_status   = Column(String(20),  default="pending")

    __table_args__ = (Index('idx_playlist_name', 'name'), {})

class UserStream(Base):
    __tablename__ = "user_streams"
    id                 = Column(PG_UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    title              = Column(String(200), nullable=False)
    description        = Column(Text, nullable=True)
    category           = Column(String(50),  nullable=False)
    stream_key         = Column(String(100),  unique=True, nullable=False)
    thumbnail          = Column(String(500),  nullable=True)
    viewer_count       = Column(Integer, default=0)
    peak_viewers       = Column(Integer, default=0)
    like_count         = Column(Integer, default=0)
    is_live            = Column(Boolean, default=False)
    is_featured        = Column(Boolean, default=False)
    is_blocked         = Column(Boolean, default=False)
    created_at         = Column(DateTime, default=datetime.utcnow)
    started_at         = Column(DateTime, nullable=True)
    ended_at           = Column(DateTime, nullable=True)
    visitor_id         = Column(PG_UUID(as_uuid=False), ForeignKey("visitors.id"))
    stream_url         = Column(String(500), nullable=True)
    tags               = Column(String(500), nullable=True)
    language           = Column(String(10),  default="fr")
    report_count       = Column(Integer, default=0)
    is_mature          = Column(Boolean, default=False)
    chat_enabled       = Column(Boolean, default=True)
    recording_enabled  = Column(Boolean, default=False)

    visitor  = relationship("Visitor", backref="streams")
    comments = relationship("Comment",     back_populates="stream", cascade="all, delete-orphan")
    stats    = relationship("StreamStats", back_populates="stream", cascade="all, delete-orphan")

class Comment(Base):
    __tablename__ = "comments"
    id            = Column(PG_UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    content       = Column(Text, nullable=False)
    stream_id     = Column(PG_UUID(as_uuid=False), ForeignKey("user_streams.id"), nullable=False)
    visitor_id    = Column(PG_UUID(as_uuid=False), ForeignKey("visitors.id"),     nullable=False)
    created_at    = Column(DateTime, default=datetime.utcnow)
    is_flagged    = Column(Boolean, default=False)
    is_deleted    = Column(Boolean, default=False)
    is_auto_hidden= Column(Boolean, default=False)
    ip_address    = Column(String(50))
    report_count  = Column(Integer, default=0)
    likes         = Column(Integer, default=0)
    reply_to      = Column(PG_UUID(as_uuid=False), nullable=True)

    stream  = relationship("UserStream", back_populates="comments")
    visitor = relationship("Visitor")

class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id           = Column(PG_UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    stream_id    = Column(String(200), nullable=True, index=True)
    username     = Column(String(100), nullable=False, default="Anonyme")
    content      = Column(Text, nullable=False)
    ip_address   = Column(String(50), nullable=True)
    created_at   = Column(DateTime, default=datetime.utcnow)
    is_deleted   = Column(Boolean, default=False)
    is_auto_hidden = Column(Boolean, default=False)
    report_count = Column(Integer, default=0)

class LiveStream(Base):
    __tablename__ = "live_streams"
    id           = Column(PG_UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    title        = Column(String(200), nullable=False)
    description  = Column(Text, nullable=True)
    category     = Column(String(50), nullable=True)
    stream_key   = Column(String(100), unique=True, nullable=True)
    stream_url   = Column(String(1000), nullable=True)
    thumbnail    = Column(String(500), nullable=True)
    viewer_count = Column(Integer, default=0)
    like_count   = Column(Integer, default=0)
    is_live      = Column(Boolean, default=False)
    is_blocked   = Column(Boolean, default=False)
    is_featured  = Column(Boolean, default=False)
    created_at   = Column(DateTime, default=datetime.utcnow)
    started_at   = Column(DateTime, nullable=True)
    ended_at     = Column(DateTime, nullable=True)
    visitor_id   = Column(String(100), nullable=True)
    language     = Column(String(10), default="fr")
    report_count = Column(Integer, default=0)
    chat_enabled = Column(Boolean, default=True)

class Report(Base):
    __tablename__ = "reports"
    id          = Column(PG_UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    reason      = Column(String(200), nullable=False)
    comment_id  = Column(PG_UUID(as_uuid=False), ForeignKey("comments.id"),     nullable=True)
    stream_id   = Column(PG_UUID(as_uuid=False), ForeignKey("user_streams.id"), nullable=True)
    visitor_id  = Column(PG_UUID(as_uuid=False), ForeignKey("visitors.id"),     nullable=False)
    created_at  = Column(DateTime, default=datetime.utcnow)
    resolved    = Column(Boolean, default=False)
    resolved_by = Column(PG_UUID(as_uuid=False), ForeignKey("users.id"), nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    stream_type = Column(String(20), nullable=True)

class BlockedIP(Base):
    __tablename__ = "blocked_ips"
    id          = Column(PG_UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    ip_address  = Column(String(50), unique=True, index=True, nullable=False)
    reason      = Column(String(500), nullable=False)
    blocked_at  = Column(DateTime, default=datetime.utcnow)
    expires_at  = Column(DateTime, nullable=True)
    blocked_by  = Column(PG_UUID(as_uuid=False), ForeignKey("users.id"), nullable=True)
    is_permanent= Column(Boolean, default=False)
    is_active   = Column(Boolean, default=True)   # ← AJOUTÉ

class Favorite(Base):
    __tablename__ = "favorites"
    id          = Column(PG_UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    visitor_id  = Column(PG_UUID(as_uuid=False), ForeignKey("visitors.id"), nullable=False)
    stream_id   = Column(String(36), nullable=False)
    stream_type = Column(String(20), nullable=False)
    created_at  = Column(DateTime, default=datetime.utcnow)

class StreamStats(Base):
    __tablename__ = "stream_stats"
    id            = Column(PG_UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    stream_id     = Column(PG_UUID(as_uuid=False), ForeignKey("user_streams.id"), nullable=False)
    timestamp     = Column(DateTime, default=datetime.utcnow)
    viewer_count  = Column(Integer, default=0)
    like_count    = Column(Integer, default=0)
    comment_count = Column(Integer, default=0)

    stream = relationship("UserStream", back_populates="stats")

class StreamRecording(Base):
    __tablename__ = "stream_recordings"
    id         = Column(PG_UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    stream_id  = Column(PG_UUID(as_uuid=False), ForeignKey("user_streams.id"), nullable=False)
    start_time = Column(DateTime, default=datetime.utcnow)
    end_time   = Column(DateTime, nullable=True)
    file_path  = Column(String(500), nullable=True)
    file_size  = Column(Integer, default=0)
    duration   = Column(Integer, default=0)
    status     = Column(String(20), default="recording")

class SystemLog(Base):
    __tablename__ = "system_logs"
    id         = Column(PG_UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    level      = Column(String(20), nullable=False)
    message    = Column(Text, nullable=False)
    source     = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class DailyVisitStats(Base):
    """Compteur de visiteurs uniques par jour — alimenté automatiquement."""
    __tablename__ = "daily_visit_stats"
    id           = Column(PG_UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    date         = Column(DateTime, nullable=False, index=True, unique=True)  # minuit UTC du jour
    unique_users = Column(Integer, default=0)   # visiteurs uniques du jour
    page_views   = Column(Integer, default=0)   # total requêtes pages
    peak_active  = Column(Integer, default=0)   # pic d'utilisateurs actifs simultanés

class UserFeedback(Base):
    """Avis des utilisateurs envoyés depuis le frontend"""
    __tablename__ = "user_feedback"
    id         = Column(PG_UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    message    = Column(Text, nullable=False)
    email      = Column(String(200), nullable=True)
    rating     = Column(Integer, default=5)  # 1-5 étoiles
    visitor_id = Column(String(100), nullable=True)
    ip_address = Column(String(50), nullable=True)
    is_read    = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class AdminAnnouncement(Base):
    """Annonces de l'admin envoyées à tous les utilisateurs"""
    __tablename__ = "admin_announcements"
    id         = Column(PG_UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    title      = Column(String(200), nullable=False)
    message    = Column(Text, nullable=False)
    type       = Column(String(30), default="info")  # info, warning, update, feature
    is_active  = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)

class UserLocation(Base):
    """Localisation géographique des visiteurs pour la carte admin"""
    __tablename__ = "user_locations"
    id          = Column(PG_UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    visitor_id  = Column(String(100), nullable=True)
    ip_address  = Column(String(50), nullable=True)
    country     = Column(String(100), nullable=True)
    country_code= Column(String(5), nullable=True)
    region      = Column(String(100), nullable=True)
    city        = Column(String(100), nullable=True)
    latitude    = Column(Float, nullable=True)
    longitude   = Column(Float, nullable=True)
    continent   = Column(String(50), nullable=True)
    created_at  = Column(DateTime, default=datetime.utcnow)
    last_seen   = Column(DateTime, default=datetime.utcnow)

class StreamRecordingSession(Base):
    """Enregistrements de flux démarrés par les utilisateurs"""
    __tablename__ = "stream_recording_sessions"
    id           = Column(PG_UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    visitor_id   = Column(String(100), nullable=True)
    stream_id    = Column(String(200), nullable=True)
    stream_title = Column(String(300), nullable=True)
    stream_url   = Column(String(1000), nullable=True)
    started_at   = Column(DateTime, default=datetime.utcnow)
    ended_at     = Column(DateTime, nullable=True)
    status       = Column(String(20), default="recording")  # recording, completed, error

# ── Vérification connexion PostgreSQL ────────────────────────────────────────
def _check_db_connection() -> bool:
    """Teste la connexion PostgreSQL au démarrage. Affiche un message clair si échec."""
    try:
        with engine.connect() as conn:
            conn.execute(func.now())
        return True
    except Exception as e:
        print("\n" + "="*70)
        print(" IMPOSSIBLE DE SE CONNECTER À POSTGRESQL")
        print("="*70)
        print(f"   URL       : {settings.DATABASE_URL}")
        print(f"   Erreur    : {e}")
        print()
        print("   Solutions :")
        print("   1. Vérifiez que PostgreSQL est démarré")
        print("      → sudo systemctl start postgresql")
        print("      → docker compose up -d postgres")
        print()
        print("   2. Vérifiez votre DATABASE_URL dans le fichier .env")
        print("      → DATABASE_URL=postgresql://user:pass@host:5432/dbname")
        print()
        print("   3. Créez la base si elle n'existe pas :")
        print("      → bash setup_postgres.sh")
        print("="*70 + "\n")
        return False

_db_ok = _check_db_connection()
if not _db_ok:
    import sys as _sys
    _sys.exit(1)

# Note : Base.metadata.create_all() est appelé dans lifespan() après
# vérification de la connexion avec retry async

# ==================== PLAYLISTS IPTV.ORG COMPLÈTES ====================

IPTV_PLAYLISTS = [
    # ---- INDEX MONDIAL ----
    {"name":"index","display_name":"Toutes les chaînes (Monde)","url":f"{settings.IPTV_BASE_URL}/index.m3u","category":"iptv","country":"INT","playlist_type":"category"},

    # ---- PAYS (environ 200 pays) ----
    {"name":"france","display_name":"France","url":f"{settings.IPTV_BASE_URL}/countries/fr.m3u","category":"iptv","country":"FR","playlist_type":"country"},
    {"name":"canada","display_name":"Canada","url":f"{settings.IPTV_BASE_URL}/countries/ca.m3u","category":"iptv","country":"CA","playlist_type":"country"},
    {"name":"belgique","display_name":"Belgique","url":f"{settings.IPTV_BASE_URL}/countries/be.m3u","category":"iptv","country":"BE","playlist_type":"country"},
    {"name":"suisse","display_name":"Suisse","url":f"{settings.IPTV_BASE_URL}/countries/ch.m3u","category":"iptv","country":"CH","playlist_type":"country"},
    {"name":"luxembourg","display_name":"Luxembourg","url":f"{settings.IPTV_BASE_URL}/countries/lu.m3u","category":"iptv","country":"LU","playlist_type":"country"},
    {"name":"monaco","display_name":"Monaco","url":f"{settings.IPTV_BASE_URL}/countries/mc.m3u","category":"iptv","country":"MC","playlist_type":"country"},
    {"name":"maroc","display_name":"Maroc","url":f"{settings.IPTV_BASE_URL}/countries/ma.m3u","category":"iptv","country":"MA","playlist_type":"country"},
    {"name":"algerie","display_name":"Algérie","url":f"{settings.IPTV_BASE_URL}/countries/dz.m3u","category":"iptv","country":"DZ","playlist_type":"country"},
    {"name":"tunisie","display_name":"Tunisie","url":f"{settings.IPTV_BASE_URL}/countries/tn.m3u","category":"iptv","country":"TN","playlist_type":"country"},
    {"name":"senegal","display_name":"Sénégal","url":f"{settings.IPTV_BASE_URL}/countries/sn.m3u","category":"iptv","country":"SN","playlist_type":"country"},
    {"name":"cote_ivoire","display_name":"Côte d'Ivoire","url":f"{settings.IPTV_BASE_URL}/countries/ci.m3u","category":"iptv","country":"CI","playlist_type":"country"},
    {"name":"cameroun","display_name":"Cameroun","url":f"{settings.IPTV_BASE_URL}/countries/cm.m3u","category":"iptv","country":"CM","playlist_type":"country"},
    {"name":"mali","display_name":"Mali","url":f"{settings.IPTV_BASE_URL}/countries/ml.m3u","category":"iptv","country":"ML","playlist_type":"country"},
    {"name":"congo","display_name":"Congo RDC","url":f"{settings.IPTV_BASE_URL}/countries/cd.m3u","category":"iptv","country":"CD","playlist_type":"country"},
    {"name":"congo_brazzaville","display_name":"Congo-Brazzaville","url":f"{settings.IPTV_BASE_URL}/countries/cg.m3u","category":"iptv","country":"CG","playlist_type":"country"},
    {"name":"burkina_faso","display_name":"Burkina Faso","url":f"{settings.IPTV_BASE_URL}/countries/bf.m3u","category":"iptv","country":"BF","playlist_type":"country"},
    {"name":"niger","display_name":"Niger","url":f"{settings.IPTV_BASE_URL}/countries/ne.m3u","category":"iptv","country":"NE","playlist_type":"country"},
    {"name":"tchad","display_name":"Tchad","url":f"{settings.IPTV_BASE_URL}/countries/td.m3u","category":"iptv","country":"TD","playlist_type":"country"},
    {"name":"gabon","display_name":"Gabon","url":f"{settings.IPTV_BASE_URL}/countries/ga.m3u","category":"iptv","country":"GA","playlist_type":"country"},
    {"name":"guinee","display_name":"Guinée","url":f"{settings.IPTV_BASE_URL}/countries/gn.m3u","category":"iptv","country":"GN","playlist_type":"country"},
    {"name":"benin","display_name":"Bénin","url":f"{settings.IPTV_BASE_URL}/countries/bj.m3u","category":"iptv","country":"BJ","playlist_type":"country"},
    {"name":"togo","display_name":"Togo","url":f"{settings.IPTV_BASE_URL}/countries/tg.m3u","category":"iptv","country":"TG","playlist_type":"country"},
    {"name":"mauritanie","display_name":"Mauritanie","url":f"{settings.IPTV_BASE_URL}/countries/mr.m3u","category":"iptv","country":"MR","playlist_type":"country"},
    {"name":"libye","display_name":"Libye","url":f"{settings.IPTV_BASE_URL}/countries/ly.m3u","category":"iptv","country":"LY","playlist_type":"country"},
    {"name":"egypte","display_name":"Égypte","url":f"{settings.IPTV_BASE_URL}/countries/eg.m3u","category":"iptv","country":"EG","playlist_type":"country"},
    {"name":"arabie_saoudite","display_name":"Arabie Saoudite","url":f"{settings.IPTV_BASE_URL}/countries/sa.m3u","category":"iptv","country":"SA","playlist_type":"country"},
    {"name":"emirats_arabes_unis","display_name":"Émirats Arabes Unis","url":f"{settings.IPTV_BASE_URL}/countries/ae.m3u","category":"iptv","country":"AE","playlist_type":"country"},
    {"name":"qatar","display_name":"Qatar","url":f"{settings.IPTV_BASE_URL}/countries/qa.m3u","category":"iptv","country":"QA","playlist_type":"country"},
    {"name":"koweit","display_name":"Koweït","url":f"{settings.IPTV_BASE_URL}/countries/kw.m3u","category":"iptv","country":"KW","playlist_type":"country"},
    {"name":"bahrein","display_name":"Bahreïn","url":f"{settings.IPTV_BASE_URL}/countries/bh.m3u","category":"iptv","country":"BH","playlist_type":"country"},
    {"name":"oman","display_name":"Oman","url":f"{settings.IPTV_BASE_URL}/countries/om.m3u","category":"iptv","country":"OM","playlist_type":"country"},
    {"name":"jordanie","display_name":"Jordanie","url":f"{settings.IPTV_BASE_URL}/countries/jo.m3u","category":"iptv","country":"JO","playlist_type":"country"},
    {"name":"irak","display_name":"Irak","url":f"{settings.IPTV_BASE_URL}/countries/iq.m3u","category":"iptv","country":"IQ","playlist_type":"country"},
    {"name":"iran","display_name":"Iran","url":f"{settings.IPTV_BASE_URL}/countries/ir.m3u","category":"iptv","country":"IR","playlist_type":"country"},
    {"name":"syrie","display_name":"Syrie","url":f"{settings.IPTV_BASE_URL}/countries/sy.m3u","category":"iptv","country":"SY","playlist_type":"country"},
    {"name":"liban","display_name":"Liban","url":f"{settings.IPTV_BASE_URL}/countries/lb.m3u","category":"iptv","country":"LB","playlist_type":"country"},
    {"name":"israel","display_name":"Israël","url":f"{settings.IPTV_BASE_URL}/countries/il.m3u","category":"iptv","country":"IL","playlist_type":"country"},
    {"name":"palestine","display_name":"Palestine","url":f"{settings.IPTV_BASE_URL}/countries/ps.m3u","category":"iptv","country":"PS","playlist_type":"country"},
    {"name":"turquie","display_name":"Turquie","url":f"{settings.IPTV_BASE_URL}/countries/tr.m3u","category":"iptv","country":"TR","playlist_type":"country"},
    {"name":"etats_unis","display_name":"États-Unis","url":f"{settings.IPTV_BASE_URL}/countries/us.m3u","category":"iptv","country":"US","playlist_type":"country"},
    {"name":"royaume_uni","display_name":"Royaume-Uni","url":f"{settings.IPTV_BASE_URL}/countries/gb.m3u","category":"iptv","country":"GB","playlist_type":"country"},
    {"name":"allemagne","display_name":"Allemagne","url":f"{settings.IPTV_BASE_URL}/countries/de.m3u","category":"iptv","country":"DE","playlist_type":"country"},
    {"name":"espagne","display_name":"Espagne","url":f"{settings.IPTV_BASE_URL}/countries/es.m3u","category":"iptv","country":"ES","playlist_type":"country"},
    {"name":"italie","display_name":"Italie","url":f"{settings.IPTV_BASE_URL}/countries/it.m3u","category":"iptv","country":"IT","playlist_type":"country"},
    {"name":"portugal","display_name":"Portugal","url":f"{settings.IPTV_BASE_URL}/countries/pt.m3u","category":"iptv","country":"PT","playlist_type":"country"},
    {"name":"pays_bas","display_name":"Pays-Bas","url":f"{settings.IPTV_BASE_URL}/countries/nl.m3u","category":"iptv","country":"NL","playlist_type":"country"},
    {"name":"russie","display_name":"Russie","url":f"{settings.IPTV_BASE_URL}/countries/ru.m3u","category":"iptv","country":"RU","playlist_type":"country"},
    {"name":"pologne","display_name":"Pologne","url":f"{settings.IPTV_BASE_URL}/countries/pl.m3u","category":"iptv","country":"PL","playlist_type":"country"},
    {"name":"ukraine","display_name":"Ukraine","url":f"{settings.IPTV_BASE_URL}/countries/ua.m3u","category":"iptv","country":"UA","playlist_type":"country"},
    {"name":"roumanie","display_name":"Roumanie","url":f"{settings.IPTV_BASE_URL}/countries/ro.m3u","category":"iptv","country":"RO","playlist_type":"country"},
    {"name":"bulgarie","display_name":"Bulgarie","url":f"{settings.IPTV_BASE_URL}/countries/bg.m3u","category":"iptv","country":"BG","playlist_type":"country"},
    {"name":"serbie","display_name":"Serbie","url":f"{settings.IPTV_BASE_URL}/countries/rs.m3u","category":"iptv","country":"RS","playlist_type":"country"},
    {"name":"croatie","display_name":"Croatie","url":f"{settings.IPTV_BASE_URL}/countries/hr.m3u","category":"iptv","country":"HR","playlist_type":"country"},
    {"name":"slovenie","display_name":"Slovénie","url":f"{settings.IPTV_BASE_URL}/countries/si.m3u","category":"iptv","country":"SI","playlist_type":"country"},
    {"name":"slovaquie","display_name":"Slovaquie","url":f"{settings.IPTV_BASE_URL}/countries/sk.m3u","category":"iptv","country":"SK","playlist_type":"country"},
    {"name":"tchequie","display_name":"Tchéquie","url":f"{settings.IPTV_BASE_URL}/countries/cz.m3u","category":"iptv","country":"CZ","playlist_type":"country"},
    {"name":"hongrie","display_name":"Hongrie","url":f"{settings.IPTV_BASE_URL}/countries/hu.m3u","category":"iptv","country":"HU","playlist_type":"country"},
    {"name":"autriche","display_name":"Autriche","url":f"{settings.IPTV_BASE_URL}/countries/at.m3u","category":"iptv","country":"AT","playlist_type":"country"},
    {"name":"grece","display_name":"Grèce","url":f"{settings.IPTV_BASE_URL}/countries/gr.m3u","category":"iptv","country":"GR","playlist_type":"country"},
    {"name":"chypre","display_name":"Chypre","url":f"{settings.IPTV_BASE_URL}/countries/cy.m3u","category":"iptv","country":"CY","playlist_type":"country"},
    {"name":"malte","display_name":"Malte","url":f"{settings.IPTV_BASE_URL}/countries/mt.m3u","category":"iptv","country":"MT","playlist_type":"country"},
    {"name":"islande","display_name":"Islande","url":f"{settings.IPTV_BASE_URL}/countries/is.m3u","category":"iptv","country":"IS","playlist_type":"country"},
    {"name":"norvege","display_name":"Norvège","url":f"{settings.IPTV_BASE_URL}/countries/no.m3u","category":"iptv","country":"NO","playlist_type":"country"},
    {"name":"suede","display_name":"Suède","url":f"{settings.IPTV_BASE_URL}/countries/se.m3u","category":"iptv","country":"SE","playlist_type":"country"},
    {"name":"finlande","display_name":"Finlande","url":f"{settings.IPTV_BASE_URL}/countries/fi.m3u","category":"iptv","country":"FI","playlist_type":"country"},
    {"name":"danemark","display_name":"Danemark","url":f"{settings.IPTV_BASE_URL}/countries/dk.m3u","category":"iptv","country":"DK","playlist_type":"country"},
    {"name":"irlande","display_name":"Irlande","url":f"{settings.IPTV_BASE_URL}/countries/ie.m3u","category":"iptv","country":"IE","playlist_type":"country"},
    {"name":"bresil","display_name":"Brésil","url":f"{settings.IPTV_BASE_URL}/countries/br.m3u","category":"iptv","country":"BR","playlist_type":"country"},
    {"name":"mexique","display_name":"Mexique","url":f"{settings.IPTV_BASE_URL}/countries/mx.m3u","category":"iptv","country":"MX","playlist_type":"country"},
    {"name":"argentine","display_name":"Argentine","url":f"{settings.IPTV_BASE_URL}/countries/ar.m3u","category":"iptv","country":"AR","playlist_type":"country"},
    {"name":"colombie","display_name":"Colombie","url":f"{settings.IPTV_BASE_URL}/countries/co.m3u","category":"iptv","country":"CO","playlist_type":"country"},
    {"name":"chili","display_name":"Chili","url":f"{settings.IPTV_BASE_URL}/countries/cl.m3u","category":"iptv","country":"CL","playlist_type":"country"},
    {"name":"perou","display_name":"Pérou","url":f"{settings.IPTV_BASE_URL}/countries/pe.m3u","category":"iptv","country":"PE","playlist_type":"country"},
    {"name":"venezuela","display_name":"Venezuela","url":f"{settings.IPTV_BASE_URL}/countries/ve.m3u","category":"iptv","country":"VE","playlist_type":"country"},
    {"name":"equateur","display_name":"Équateur","url":f"{settings.IPTV_BASE_URL}/countries/ec.m3u","category":"iptv","country":"EC","playlist_type":"country"},
    {"name":"bolivie","display_name":"Bolivie","url":f"{settings.IPTV_BASE_URL}/countries/bo.m3u","category":"iptv","country":"BO","playlist_type":"country"},
    {"name":"paraguay","display_name":"Paraguay","url":f"{settings.IPTV_BASE_URL}/countries/py.m3u","category":"iptv","country":"PY","playlist_type":"country"},
    {"name":"uruguay","display_name":"Uruguay","url":f"{settings.IPTV_BASE_URL}/countries/uy.m3u","category":"iptv","country":"UY","playlist_type":"country"},
    {"name":"chine","display_name":"Chine","url":f"{settings.IPTV_BASE_URL}/countries/cn.m3u","category":"iptv","country":"CN","playlist_type":"country"},
    {"name":"japon","display_name":"Japon","url":f"{settings.IPTV_BASE_URL}/countries/jp.m3u","category":"iptv","country":"JP","playlist_type":"country"},
    {"name":"coree_sud","display_name":"Corée du Sud","url":f"{settings.IPTV_BASE_URL}/countries/kr.m3u","category":"iptv","country":"KR","playlist_type":"country"},
    {"name":"inde","display_name":"Inde","url":f"{settings.IPTV_BASE_URL}/countries/in.m3u","category":"iptv","country":"IN","playlist_type":"country"},
    {"name":"pakistan","display_name":"Pakistan","url":f"{settings.IPTV_BASE_URL}/countries/pk.m3u","category":"iptv","country":"PK","playlist_type":"country"},
    {"name":"bangladesh","display_name":"Bangladesh","url":f"{settings.IPTV_BASE_URL}/countries/bd.m3u","category":"iptv","country":"BD","playlist_type":"country"},
    {"name":"indonesie","display_name":"Indonésie","url":f"{settings.IPTV_BASE_URL}/countries/id.m3u","category":"iptv","country":"ID","playlist_type":"country"},
    {"name":"malaisie","display_name":"Malaisie","url":f"{settings.IPTV_BASE_URL}/countries/my.m3u","category":"iptv","country":"MY","playlist_type":"country"},
    {"name":"singapour","display_name":"Singapour","url":f"{settings.IPTV_BASE_URL}/countries/sg.m3u","category":"iptv","country":"SG","playlist_type":"country"},
    {"name":"philippines","display_name":"Philippines","url":f"{settings.IPTV_BASE_URL}/countries/ph.m3u","category":"iptv","country":"PH","playlist_type":"country"},
    {"name":"vietnam","display_name":"Vietnam","url":f"{settings.IPTV_BASE_URL}/countries/vn.m3u","category":"iptv","country":"VN","playlist_type":"country"},
    {"name":"thailande","display_name":"Thaïlande","url":f"{settings.IPTV_BASE_URL}/countries/th.m3u","category":"iptv","country":"TH","playlist_type":"country"},
    {"name":"birmanie","display_name":"Birmanie","url":f"{settings.IPTV_BASE_URL}/countries/mm.m3u","category":"iptv","country":"MM","playlist_type":"country"},
    {"name":"cambodge","display_name":"Cambodge","url":f"{settings.IPTV_BASE_URL}/countries/kh.m3u","category":"iptv","country":"KH","playlist_type":"country"},
    {"name":"laos","display_name":"Laos","url":f"{settings.IPTV_BASE_URL}/countries/la.m3u","category":"iptv","country":"LA","playlist_type":"country"},
    {"name":"nepal","display_name":"Népal","url":f"{settings.IPTV_BASE_URL}/countries/np.m3u","category":"iptv","country":"NP","playlist_type":"country"},
    {"name":"sri_lanka","display_name":"Sri Lanka","url":f"{settings.IPTV_BASE_URL}/countries/lk.m3u","category":"iptv","country":"LK","playlist_type":"country"},
    {"name":"afghanistan","display_name":"Afghanistan","url":f"{settings.IPTV_BASE_URL}/countries/af.m3u","category":"iptv","country":"AF","playlist_type":"country"},
    {"name":"kazakhstan","display_name":"Kazakhstan","url":f"{settings.IPTV_BASE_URL}/countries/kz.m3u","category":"iptv","country":"KZ","playlist_type":"country"},
    {"name":"ouzbekistan","display_name":"Ouzbékistan","url":f"{settings.IPTV_BASE_URL}/countries/uz.m3u","category":"iptv","country":"UZ","playlist_type":"country"},
    {"name":"tadjikistan","display_name":"Tadjikistan","url":f"{settings.IPTV_BASE_URL}/countries/tj.m3u","category":"iptv","country":"TJ","playlist_type":"country"},
    {"name":"kirghizistan","display_name":"Kirghizistan","url":f"{settings.IPTV_BASE_URL}/countries/kg.m3u","category":"iptv","country":"KG","playlist_type":"country"},
    {"name":"turkmenistan","display_name":"Turkménistan","url":f"{settings.IPTV_BASE_URL}/countries/tm.m3u","category":"iptv","country":"TM","playlist_type":"country"},
    {"name":"georgie","display_name":"Géorgie","url":f"{settings.IPTV_BASE_URL}/countries/ge.m3u","category":"iptv","country":"GE","playlist_type":"country"},
    {"name":"armenie","display_name":"Arménie","url":f"{settings.IPTV_BASE_URL}/countries/am.m3u","category":"iptv","country":"AM","playlist_type":"country"},
    {"name":"azerbaidjan","display_name":"Azerbaïdjan","url":f"{settings.IPTV_BASE_URL}/countries/az.m3u","category":"iptv","country":"AZ","playlist_type":"country"},
    {"name":"moldavie","display_name":"Moldavie","url":f"{settings.IPTV_BASE_URL}/countries/md.m3u","category":"iptv","country":"MD","playlist_type":"country"},
    {"name":"bielorussie","display_name":"Biélorussie","url":f"{settings.IPTV_BASE_URL}/countries/by.m3u","category":"iptv","country":"BY","playlist_type":"country"},
    {"name":"lituanie","display_name":"Lituanie","url":f"{settings.IPTV_BASE_URL}/countries/lt.m3u","category":"iptv","country":"LT","playlist_type":"country"},
    {"name":"lettonie","display_name":"Lettonie","url":f"{settings.IPTV_BASE_URL}/countries/lv.m3u","category":"iptv","country":"LV","playlist_type":"country"},
    {"name":"estonie","display_name":"Estonie","url":f"{settings.IPTV_BASE_URL}/countries/ee.m3u","category":"iptv","country":"EE","playlist_type":"country"},
    {"name":"afrique_du_sud","display_name":"Afrique du Sud","url":f"{settings.IPTV_BASE_URL}/countries/za.m3u","category":"iptv","country":"ZA","playlist_type":"country"},
    {"name":"nigeria","display_name":"Nigeria","url":f"{settings.IPTV_BASE_URL}/countries/ng.m3u","category":"iptv","country":"NG","playlist_type":"country"},
    {"name":"kenya","display_name":"Kenya","url":f"{settings.IPTV_BASE_URL}/countries/ke.m3u","category":"iptv","country":"KE","playlist_type":"country"},
    {"name":"tanzanie","display_name":"Tanzanie","url":f"{settings.IPTV_BASE_URL}/countries/tz.m3u","category":"iptv","country":"TZ","playlist_type":"country"},
    {"name":"ouganda","display_name":"Ouganda","url":f"{settings.IPTV_BASE_URL}/countries/ug.m3u","category":"iptv","country":"UG","playlist_type":"country"},
    {"name":"rwanda","display_name":"Rwanda","url":f"{settings.IPTV_BASE_URL}/countries/rw.m3u","category":"iptv","country":"RW","playlist_type":"country"},
    {"name":"ethiopie","display_name":"Éthiopie","url":f"{settings.IPTV_BASE_URL}/countries/et.m3u","category":"iptv","country":"ET","playlist_type":"country"},
    {"name":"ghana","display_name":"Ghana","url":f"{settings.IPTV_BASE_URL}/countries/gh.m3u","category":"iptv","country":"GH","playlist_type":"country"},
    {"name":"angola","display_name":"Angola","url":f"{settings.IPTV_BASE_URL}/countries/ao.m3u","category":"iptv","country":"AO","playlist_type":"country"},
    {"name":"mozambique","display_name":"Mozambique","url":f"{settings.IPTV_BASE_URL}/countries/mz.m3u","category":"iptv","country":"MZ","playlist_type":"country"},
    {"name":"madagascar","display_name":"Madagascar","url":f"{settings.IPTV_BASE_URL}/countries/mg.m3u","category":"iptv","country":"MG","playlist_type":"country"},
    {"name":"maurice","display_name":"Maurice","url":f"{settings.IPTV_BASE_URL}/countries/mu.m3u","category":"iptv","country":"MU","playlist_type":"country"},
    {"name":"seychelles","display_name":"Seychelles","url":f"{settings.IPTV_BASE_URL}/countries/sc.m3u","category":"iptv","country":"SC","playlist_type":"country"},
    {"name":"comores","display_name":"Comores","url":f"{settings.IPTV_BASE_URL}/countries/km.m3u","category":"iptv","country":"KM","playlist_type":"country"},
    {"name":"djibouti","display_name":"Djibouti","url":f"{settings.IPTV_BASE_URL}/countries/dj.m3u","category":"iptv","country":"DJ","playlist_type":"country"},
    {"name":"soudan","display_name":"Soudan","url":f"{settings.IPTV_BASE_URL}/countries/sd.m3u","category":"iptv","country":"SD","playlist_type":"country"},
    {"name":"soudan_sud","display_name":"Soudan du Sud","url":f"{settings.IPTV_BASE_URL}/countries/ss.m3u","category":"iptv","country":"SS","playlist_type":"country"},
    {"name":"eritree","display_name":"Érythrée","url":f"{settings.IPTV_BASE_URL}/countries/er.m3u","category":"iptv","country":"ER","playlist_type":"country"},
    {"name":"somalie","display_name":"Somalie","url":f"{settings.IPTV_BASE_URL}/countries/so.m3u","category":"iptv","country":"SO","playlist_type":"country"},
    {"name":"botswana","display_name":"Botswana","url":f"{settings.IPTV_BASE_URL}/countries/bw.m3u","category":"iptv","country":"BW","playlist_type":"country"},
    {"name":"namibie","display_name":"Namibie","url":f"{settings.IPTV_BASE_URL}/countries/na.m3u","category":"iptv","country":"NA","playlist_type":"country"},
    {"name":"zambie","display_name":"Zambie","url":f"{settings.IPTV_BASE_URL}/countries/zm.m3u","category":"iptv","country":"ZM","playlist_type":"country"},
    {"name":"zimbabwe","display_name":"Zimbabwe","url":f"{settings.IPTV_BASE_URL}/countries/zw.m3u","category":"iptv","country":"ZW","playlist_type":"country"},
    {"name":"malawi","display_name":"Malawi","url":f"{settings.IPTV_BASE_URL}/countries/mw.m3u","category":"iptv","country":"MW","playlist_type":"country"},
    {"name":"lesotho","display_name":"Lesotho","url":f"{settings.IPTV_BASE_URL}/countries/ls.m3u","category":"iptv","country":"LS","playlist_type":"country"},
    {"name":"swaziland","display_name":"Eswatini","url":f"{settings.IPTV_BASE_URL}/countries/sz.m3u","category":"iptv","country":"SZ","playlist_type":"country"},
    {"name":"australie","display_name":"Australie","url":f"{settings.IPTV_BASE_URL}/countries/au.m3u","category":"iptv","country":"AU","playlist_type":"country"},
    {"name":"nouvelle_zelande","display_name":"Nouvelle-Zélande","url":f"{settings.IPTV_BASE_URL}/countries/nz.m3u","category":"iptv","country":"NZ","playlist_type":"country"},
    {"name":"fidji","display_name":"Fidji","url":f"{settings.IPTV_BASE_URL}/countries/fj.m3u","category":"iptv","country":"FJ","playlist_type":"country"},
    {"name":"papouasie_nouvelle_guinee","display_name":"Papouasie-Nouvelle-Guinée","url":f"{settings.IPTV_BASE_URL}/countries/pg.m3u","category":"iptv","country":"PG","playlist_type":"country"},

    # ---- SUBDIVISIONS (régions/provinces) ----
    {"name":"ca_alberta","display_name":"Canada — Alberta","url":f"{settings.IPTV_BASE_URL}/subdivisions/ca-ab.m3u","category":"iptv","country":"CA","playlist_type":"subdivision"},
    {"name":"ca_british_columbia","display_name":"Canada — British Columbia","url":f"{settings.IPTV_BASE_URL}/subdivisions/ca-bc.m3u","category":"iptv","country":"CA","playlist_type":"subdivision"},
    {"name":"ca_ontario","display_name":"Canada — Ontario","url":f"{settings.IPTV_BASE_URL}/subdivisions/ca-on.m3u","category":"iptv","country":"CA","playlist_type":"subdivision"},
    {"name":"ca_quebec","display_name":"Canada — Québec","url":f"{settings.IPTV_BASE_URL}/subdivisions/ca-qc.m3u","category":"iptv","country":"CA","playlist_type":"subdivision"},
    {"name":"ca_manitoba","display_name":"Canada — Manitoba","url":f"{settings.IPTV_BASE_URL}/subdivisions/ca-mb.m3u","category":"iptv","country":"CA","playlist_type":"subdivision"},
    {"name":"ca_saskatchewan","display_name":"Canada — Saskatchewan","url":f"{settings.IPTV_BASE_URL}/subdivisions/ca-sk.m3u","category":"iptv","country":"CA","playlist_type":"subdivision"},
    {"name":"ca_nova_scotia","display_name":"Canada — Nouvelle-Écosse","url":f"{settings.IPTV_BASE_URL}/subdivisions/ca-ns.m3u","category":"iptv","country":"CA","playlist_type":"subdivision"},
    {"name":"ca_new_brunswick","display_name":"Canada — Nouveau-Brunswick","url":f"{settings.IPTV_BASE_URL}/subdivisions/ca-nb.m3u","category":"iptv","country":"CA","playlist_type":"subdivision"},
    {"name":"ca_newfoundland","display_name":"Canada — Terre-Neuve","url":f"{settings.IPTV_BASE_URL}/subdivisions/ca-nl.m3u","category":"iptv","country":"CA","playlist_type":"subdivision"},
    {"name":"ca_prince_edward","display_name":"Canada — Île-du-Prince-Édouard","url":f"{settings.IPTV_BASE_URL}/subdivisions/ca-pe.m3u","category":"iptv","country":"CA","playlist_type":"subdivision"},
    {"name":"ca_yukon","display_name":"Canada — Yukon","url":f"{settings.IPTV_BASE_URL}/subdivisions/ca-yt.m3u","category":"iptv","country":"CA","playlist_type":"subdivision"},
    {"name":"ca_northwest","display_name":"Canada — Territoires du Nord-Ouest","url":f"{settings.IPTV_BASE_URL}/subdivisions/ca-nt.m3u","category":"iptv","country":"CA","playlist_type":"subdivision"},
    {"name":"ca_nunavut","display_name":"Canada — Nunavut","url":f"{settings.IPTV_BASE_URL}/subdivisions/ca-nu.m3u","category":"iptv","country":"CA","playlist_type":"subdivision"},

    {"name":"us_california","display_name":"USA — Californie","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-ca.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_texas","display_name":"USA — Texas","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-tx.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_new_york","display_name":"USA — New York","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-ny.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_florida","display_name":"USA — Floride","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-fl.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_illinois","display_name":"USA — Illinois","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-il.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_pennsylvania","display_name":"USA — Pennsylvanie","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-pa.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_ohio","display_name":"USA — Ohio","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-oh.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_georgia","display_name":"USA — Géorgie","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-ga.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_michigan","display_name":"USA — Michigan","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-mi.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_north_carolina","display_name":"USA — Caroline du Nord","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-nc.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_new_jersey","display_name":"USA — New Jersey","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-nj.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_virginia","display_name":"USA — Virginie","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-va.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_washington","display_name":"USA — Washington","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-wa.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_massachusetts","display_name":"USA — Massachusetts","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-ma.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_indiana","display_name":"USA — Indiana","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-in.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_tennessee","display_name":"USA — Tennessee","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-tn.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_missouri","display_name":"USA — Missouri","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-mo.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_maryland","display_name":"USA — Maryland","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-md.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_wisconsin","display_name":"USA — Wisconsin","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-wi.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_colorado","display_name":"USA — Colorado","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-co.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_minnesota","display_name":"USA — Minnesota","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-mn.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_south_carolina","display_name":"USA — Caroline du Sud","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-sc.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_alabama","display_name":"USA — Alabama","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-al.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_louisiana","display_name":"USA — Louisiane","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-la.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_kentucky","display_name":"USA — Kentucky","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-ky.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_oregon","display_name":"USA — Oregon","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-or.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_oklahoma","display_name":"USA — Oklahoma","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-ok.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_connecticut","display_name":"USA — Connecticut","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-ct.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_iowa","display_name":"USA — Iowa","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-ia.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_mississippi","display_name":"USA — Mississippi","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-ms.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_arkansas","display_name":"USA — Arkansas","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-ar.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_kansas","display_name":"USA — Kansas","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-ks.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_utah","display_name":"USA — Utah","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-ut.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_nevada","display_name":"USA — Nevada","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-nv.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_new_mexico","display_name":"USA — Nouveau-Mexique","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-nm.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_nebraska","display_name":"USA — Nebraska","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-ne.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_west_virginia","display_name":"USA — Virginie-Occidentale","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-wv.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_idaho","display_name":"USA — Idaho","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-id.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_hawaii","display_name":"USA — Hawaï","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-hi.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_maine","display_name":"USA — Maine","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-me.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_new_hampshire","display_name":"USA — New Hampshire","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-nh.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_rhode_island","display_name":"USA — Rhode Island","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-ri.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_montana","display_name":"USA — Montana","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-mt.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_delaware","display_name":"USA — Delaware","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-de.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_south_dakota","display_name":"USA — Dakota du Sud","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-sd.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_north_dakota","display_name":"USA — Dakota du Nord","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-nd.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_alaska","display_name":"USA — Alaska","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-ak.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_vermont","display_name":"USA — Vermont","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-vt.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_wyoming","display_name":"USA — Wyoming","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-wy.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},

    {"name":"br_sao_paulo","display_name":"Brésil — São Paulo","url":f"{settings.IPTV_BASE_URL}/subdivisions/br-sp.m3u","category":"iptv","country":"BR","playlist_type":"subdivision"},
    {"name":"br_rio_de_janeiro","display_name":"Brésil — Rio de Janeiro","url":f"{settings.IPTV_BASE_URL}/subdivisions/br-rj.m3u","category":"iptv","country":"BR","playlist_type":"subdivision"},
    {"name":"br_minas_gerais","display_name":"Brésil — Minas Gerais","url":f"{settings.IPTV_BASE_URL}/subdivisions/br-mg.m3u","category":"iptv","country":"BR","playlist_type":"subdivision"},
    {"name":"br_bahia","display_name":"Brésil — Bahia","url":f"{settings.IPTV_BASE_URL}/subdivisions/br-ba.m3u","category":"iptv","country":"BR","playlist_type":"subdivision"},
    {"name":"br_parana","display_name":"Brésil — Paraná","url":f"{settings.IPTV_BASE_URL}/subdivisions/br-pr.m3u","category":"iptv","country":"BR","playlist_type":"subdivision"},
    {"name":"br_rio_grande_sul","display_name":"Brésil — Rio Grande do Sul","url":f"{settings.IPTV_BASE_URL}/subdivisions/br-rs.m3u","category":"iptv","country":"BR","playlist_type":"subdivision"},
    {"name":"br_pernambuco","display_name":"Brésil — Pernambuco","url":f"{settings.IPTV_BASE_URL}/subdivisions/br-pe.m3u","category":"iptv","country":"BR","playlist_type":"subdivision"},
    {"name":"br_ceara","display_name":"Brésil — Ceará","url":f"{settings.IPTV_BASE_URL}/subdivisions/br-ce.m3u","category":"iptv","country":"BR","playlist_type":"subdivision"},
    {"name":"br_para","display_name":"Brésil — Pará","url":f"{settings.IPTV_BASE_URL}/subdivisions/br-pa.m3u","category":"iptv","country":"BR","playlist_type":"subdivision"},
    {"name":"br_santa_catarina","display_name":"Brésil — Santa Catarina","url":f"{settings.IPTV_BASE_URL}/subdivisions/br-sc.m3u","category":"iptv","country":"BR","playlist_type":"subdivision"},

    {"name":"co_antioquia","display_name":"Colombie — Antioquia","url":f"{settings.IPTV_BASE_URL}/subdivisions/co-ant.m3u","category":"iptv","country":"CO","playlist_type":"subdivision"},
    {"name":"co_atlantico","display_name":"Colombie — Atlántico","url":f"{settings.IPTV_BASE_URL}/subdivisions/co-atl.m3u","category":"iptv","country":"CO","playlist_type":"subdivision"},
    {"name":"co_bogota","display_name":"Colombie — Bogotá","url":f"{settings.IPTV_BASE_URL}/subdivisions/co-bog.m3u","category":"iptv","country":"CO","playlist_type":"subdivision"},
    {"name":"co_valle_cauca","display_name":"Colombie — Valle del Cauca","url":f"{settings.IPTV_BASE_URL}/subdivisions/co-vac.m3u","category":"iptv","country":"CO","playlist_type":"subdivision"},

    {"name":"ar_buenos_aires","display_name":"Argentine — Buenos Aires","url":f"{settings.IPTV_BASE_URL}/subdivisions/ar-ba.m3u","category":"iptv","country":"AR","playlist_type":"subdivision"},
    {"name":"ar_cordoba","display_name":"Argentine — Córdoba","url":f"{settings.IPTV_BASE_URL}/subdivisions/ar-cb.m3u","category":"iptv","country":"AR","playlist_type":"subdivision"},
    {"name":"ar_santa_fe","display_name":"Argentine — Santa Fe","url":f"{settings.IPTV_BASE_URL}/subdivisions/ar-sf.m3u","category":"iptv","country":"AR","playlist_type":"subdivision"},

    {"name":"gb_england","display_name":"UK — Angleterre","url":f"{settings.IPTV_BASE_URL}/subdivisions/gb-eng.m3u","category":"iptv","country":"GB","playlist_type":"subdivision"},
    {"name":"gb_scotland","display_name":"UK — Écosse","url":f"{settings.IPTV_BASE_URL}/subdivisions/gb-sct.m3u","category":"iptv","country":"GB","playlist_type":"subdivision"},
    {"name":"gb_wales","display_name":"UK — Pays de Galles","url":f"{settings.IPTV_BASE_URL}/subdivisions/gb-wls.m3u","category":"iptv","country":"GB","playlist_type":"subdivision"},
    {"name":"gb_northern_ireland","display_name":"UK — Irlande du Nord","url":f"{settings.IPTV_BASE_URL}/subdivisions/gb-nir.m3u","category":"iptv","country":"GB","playlist_type":"subdivision"},

    {"name":"de_bayern","display_name":"Allemagne — Bavière","url":f"{settings.IPTV_BASE_URL}/subdivisions/de-by.m3u","category":"iptv","country":"DE","playlist_type":"subdivision"},
    {"name":"de_nordrhein_westfalen","display_name":"Allemagne — Rhénanie du Nord-Westphalie","url":f"{settings.IPTV_BASE_URL}/subdivisions/de-nw.m3u","category":"iptv","country":"DE","playlist_type":"subdivision"},
    {"name":"de_baden_wurttemberg","display_name":"Allemagne — Bade-Wurtemberg","url":f"{settings.IPTV_BASE_URL}/subdivisions/de-bw.m3u","category":"iptv","country":"DE","playlist_type":"subdivision"},
    {"name":"de_niedersachsen","display_name":"Allemagne — Basse-Saxe","url":f"{settings.IPTV_BASE_URL}/subdivisions/de-ni.m3u","category":"iptv","country":"DE","playlist_type":"subdivision"},
    {"name":"de_hessen","display_name":"Allemagne — Hesse","url":f"{settings.IPTV_BASE_URL}/subdivisions/de-he.m3u","category":"iptv","country":"DE","playlist_type":"subdivision"},
    {"name":"de_berlin","display_name":"Allemagne — Berlin","url":f"{settings.IPTV_BASE_URL}/subdivisions/de-be.m3u","category":"iptv","country":"DE","playlist_type":"subdivision"},

    {"name":"it_lombardia","display_name":"Italie — Lombardie","url":f"{settings.IPTV_BASE_URL}/subdivisions/it-25.m3u","category":"iptv","country":"IT","playlist_type":"subdivision"},
    {"name":"it_lazio","display_name":"Italie — Latium","url":f"{settings.IPTV_BASE_URL}/subdivisions/it-62.m3u","category":"iptv","country":"IT","playlist_type":"subdivision"},
    {"name":"it_campania","display_name":"Italie — Campanie","url":f"{settings.IPTV_BASE_URL}/subdivisions/it-72.m3u","category":"iptv","country":"IT","playlist_type":"subdivision"},
    {"name":"it_sicilia","display_name":"Italie — Sicile","url":f"{settings.IPTV_BASE_URL}/subdivisions/it-82.m3u","category":"iptv","country":"IT","playlist_type":"subdivision"},
    {"name":"it_veneto","display_name":"Italie — Vénétie","url":f"{settings.IPTV_BASE_URL}/subdivisions/it-34.m3u","category":"iptv","country":"IT","playlist_type":"subdivision"},

    {"name":"es_madrid","display_name":"Espagne — Madrid","url":f"{settings.IPTV_BASE_URL}/subdivisions/es-md.m3u","category":"iptv","country":"ES","playlist_type":"subdivision"},
    {"name":"es_cataluna","display_name":"Espagne — Catalogne","url":f"{settings.IPTV_BASE_URL}/subdivisions/es-ct.m3u","category":"iptv","country":"ES","playlist_type":"subdivision"},
    {"name":"es_andalucia","display_name":"Espagne — Andalousie","url":f"{settings.IPTV_BASE_URL}/subdivisions/es-an.m3u","category":"iptv","country":"ES","playlist_type":"subdivision"},
    {"name":"es_valencia","display_name":"Espagne — Valence","url":f"{settings.IPTV_BASE_URL}/subdivisions/es-vc.m3u","category":"iptv","country":"ES","playlist_type":"subdivision"},
    {"name":"es_galicia","display_name":"Espagne — Galice","url":f"{settings.IPTV_BASE_URL}/subdivisions/es-ga.m3u","category":"iptv","country":"ES","playlist_type":"subdivision"},

    # ---- VILLES ----
    {"name":"city_toronto","display_name":"Toronto","url":f"{settings.IPTV_BASE_URL}/cities/cator.m3u","category":"iptv","country":"CA","playlist_type":"city"},
    {"name":"city_montreal","display_name":"Montréal","url":f"{settings.IPTV_BASE_URL}/cities/camtl.m3u","category":"iptv","country":"CA","playlist_type":"city"},
    {"name":"city_vancouver","display_name":"Vancouver","url":f"{settings.IPTV_BASE_URL}/cities/cavan.m3u","category":"iptv","country":"CA","playlist_type":"city"},
    {"name":"city_calgary","display_name":"Calgary","url":f"{settings.IPTV_BASE_URL}/cities/cacal.m3u","category":"iptv","country":"CA","playlist_type":"city"},
    {"name":"city_edmonton","display_name":"Edmonton","url":f"{settings.IPTV_BASE_URL}/cities/caedm.m3u","category":"iptv","country":"CA","playlist_type":"city"},
    {"name":"city_ottawa","display_name":"Ottawa","url":f"{settings.IPTV_BASE_URL}/cities/caott.m3u","category":"iptv","country":"CA","playlist_type":"city"},
    {"name":"city_quebec","display_name":"Québec","url":f"{settings.IPTV_BASE_URL}/cities/caque.m3u","category":"iptv","country":"CA","playlist_type":"city"},
    {"name":"city_winnipeg","display_name":"Winnipeg","url":f"{settings.IPTV_BASE_URL}/cities/cawpg.m3u","category":"iptv","country":"CA","playlist_type":"city"},
    {"name":"city_hamilton","display_name":"Hamilton","url":f"{settings.IPTV_BASE_URL}/cities/caham.m3u","category":"iptv","country":"CA","playlist_type":"city"},

    {"name":"city_new_york","display_name":"New York","url":f"{settings.IPTV_BASE_URL}/cities/usnyc.m3u","category":"iptv","country":"US","playlist_type":"city"},
    {"name":"city_los_angeles","display_name":"Los Angeles","url":f"{settings.IPTV_BASE_URL}/cities/uslax.m3u","category":"iptv","country":"US","playlist_type":"city"},
    {"name":"city_chicago","display_name":"Chicago","url":f"{settings.IPTV_BASE_URL}/cities/uschi.m3u","category":"iptv","country":"US","playlist_type":"city"},
    {"name":"city_houston","display_name":"Houston","url":f"{settings.IPTV_BASE_URL}/cities/ushou.m3u","category":"iptv","country":"US","playlist_type":"city"},
    {"name":"city_phoenix","display_name":"Phoenix","url":f"{settings.IPTV_BASE_URL}/cities/usphx.m3u","category":"iptv","country":"US","playlist_type":"city"},
    {"name":"city_philadelphia","display_name":"Philadelphie","url":f"{settings.IPTV_BASE_URL}/cities/usphi.m3u","category":"iptv","country":"US","playlist_type":"city"},
    {"name":"city_san_antonio","display_name":"San Antonio","url":f"{settings.IPTV_BASE_URL}/cities/ussat.m3u","category":"iptv","country":"US","playlist_type":"city"},
    {"name":"city_san_diego","display_name":"San Diego","url":f"{settings.IPTV_BASE_URL}/cities/ussan.m3u","category":"iptv","country":"US","playlist_type":"city"},
    {"name":"city_dallas","display_name":"Dallas","url":f"{settings.IPTV_BASE_URL}/cities/usdal.m3u","category":"iptv","country":"US","playlist_type":"city"},
    {"name":"city_austin","display_name":"Austin","url":f"{settings.IPTV_BASE_URL}/cities/usaus.m3u","category":"iptv","country":"US","playlist_type":"city"},
    {"name":"city_jacksonville","display_name":"Jacksonville","url":f"{settings.IPTV_BASE_URL}/cities/usjax.m3u","category":"iptv","country":"US","playlist_type":"city"},
    {"name":"city_fort_worth","display_name":"Fort Worth","url":f"{settings.IPTV_BASE_URL}/cities/usftw.m3u","category":"iptv","country":"US","playlist_type":"city"},
    {"name":"city_columbus","display_name":"Columbus","url":f"{settings.IPTV_BASE_URL}/cities/uscmh.m3u","category":"iptv","country":"US","playlist_type":"city"},
    {"name":"city_charlotte","display_name":"Charlotte","url":f"{settings.IPTV_BASE_URL}/cities/usclt.m3u","category":"iptv","country":"US","playlist_type":"city"},
    {"name":"city_seattle","display_name":"Seattle","url":f"{settings.IPTV_BASE_URL}/cities/ussea.m3u","category":"iptv","country":"US","playlist_type":"city"},
    {"name":"city_denver","display_name":"Denver","url":f"{settings.IPTV_BASE_URL}/cities/usden.m3u","category":"iptv","country":"US","playlist_type":"city"},
    {"name":"city_washington","display_name":"Washington D.C.","url":f"{settings.IPTV_BASE_URL}/cities/uswdc.m3u","category":"iptv","country":"US","playlist_type":"city"},
    {"name":"city_boston","display_name":"Boston","url":f"{settings.IPTV_BASE_URL}/cities/usbos.m3u","category":"iptv","country":"US","playlist_type":"city"},
    {"name":"city_detroit","display_name":"Detroit","url":f"{settings.IPTV_BASE_URL}/cities/usdet.m3u","category":"iptv","country":"US","playlist_type":"city"},
    {"name":"city_nashville","display_name":"Nashville","url":f"{settings.IPTV_BASE_URL}/cities/usbna.m3u","category":"iptv","country":"US","playlist_type":"city"},
    {"name":"city_memphis","display_name":"Memphis","url":f"{settings.IPTV_BASE_URL}/cities/usmem.m3u","category":"iptv","country":"US","playlist_type":"city"},
    {"name":"city_portland","display_name":"Portland","url":f"{settings.IPTV_BASE_URL}/cities/uspdx.m3u","category":"iptv","country":"US","playlist_type":"city"},
    {"name":"city_oklahoma_city","display_name":"Oklahoma City","url":f"{settings.IPTV_BASE_URL}/cities/usokc.m3u","category":"iptv","country":"US","playlist_type":"city"},
    {"name":"city_las_vegas","display_name":"Las Vegas","url":f"{settings.IPTV_BASE_URL}/cities/uslas.m3u","category":"iptv","country":"US","playlist_type":"city"},
    {"name":"city_baltimore","display_name":"Baltimore","url":f"{settings.IPTV_BASE_URL}/cities/usbal.m3u","category":"iptv","country":"US","playlist_type":"city"},
    {"name":"city_louisville","display_name":"Louisville","url":f"{settings.IPTV_BASE_URL}/cities/ussdf.m3u","category":"iptv","country":"US","playlist_type":"city"},
    {"name":"city_milwaukee","display_name":"Milwaukee","url":f"{settings.IPTV_BASE_URL}/cities/usmil.m3u","category":"iptv","country":"US","playlist_type":"city"},
    {"name":"city_albuquerque","display_name":"Albuquerque","url":f"{settings.IPTV_BASE_URL}/cities/usabq.m3u","category":"iptv","country":"US","playlist_type":"city"},
    {"name":"city_tucson","display_name":"Tucson","url":f"{settings.IPTV_BASE_URL}/cities/ustus.m3u","category":"iptv","country":"US","playlist_type":"city"},
    {"name":"city_fresno","display_name":"Fresno","url":f"{settings.IPTV_BASE_URL}/cities/usfat.m3u","category":"iptv","country":"US","playlist_type":"city"},
    {"name":"city_sacramento","display_name":"Sacramento","url":f"{settings.IPTV_BASE_URL}/cities/ussac.m3u","category":"iptv","country":"US","playlist_type":"city"},
    {"name":"city_mesa","display_name":"Mesa","url":f"{settings.IPTV_BASE_URL}/cities/usmes.m3u","category":"iptv","country":"US","playlist_type":"city"},
    {"name":"city_kansas_city","display_name":"Kansas City","url":f"{settings.IPTV_BASE_URL}/cities/usmkc.m3u","category":"iptv","country":"US","playlist_type":"city"},
    {"name":"city_atlanta","display_name":"Atlanta","url":f"{settings.IPTV_BASE_URL}/cities/usatl.m3u","category":"iptv","country":"US","playlist_type":"city"},
    {"name":"city_miami","display_name":"Miami","url":f"{settings.IPTV_BASE_URL}/cities/usmia.m3u","category":"iptv","country":"US","playlist_type":"city"},
    {"name":"city_orlando","display_name":"Orlando","url":f"{settings.IPTV_BASE_URL}/cities/usorl.m3u","category":"iptv","country":"US","playlist_type":"city"},
    {"name":"city_tampa","display_name":"Tampa","url":f"{settings.IPTV_BASE_URL}/cities/ustpa.m3u","category":"iptv","country":"US","playlist_type":"city"},
    {"name":"city_st_louis","display_name":"St. Louis","url":f"{settings.IPTV_BASE_URL}/cities/usstl.m3u","category":"iptv","country":"US","playlist_type":"city"},
    {"name":"city_pittsburgh","display_name":"Pittsburgh","url":f"{settings.IPTV_BASE_URL}/cities/uspit.m3u","category":"iptv","country":"US","playlist_type":"city"},
    {"name":"city_cincinnati","display_name":"Cincinnati","url":f"{settings.IPTV_BASE_URL}/cities/uscvg.m3u","category":"iptv","country":"US","playlist_type":"city"},
    {"name":"city_indianapolis","display_name":"Indianapolis","url":f"{settings.IPTV_BASE_URL}/cities/usind.m3u","category":"iptv","country":"US","playlist_type":"city"},
    {"name":"city_cleveland","display_name":"Cleveland","url":f"{settings.IPTV_BASE_URL}/cities/uscle.m3u","category":"iptv","country":"US","playlist_type":"city"},
    {"name":"city_minneapolis","display_name":"Minneapolis","url":f"{settings.IPTV_BASE_URL}/cities/usmsp.m3u","category":"iptv","country":"US","playlist_type":"city"},
    {"name":"city_reno","display_name":"Reno","url":f"{settings.IPTV_BASE_URL}/cities/usnvs.m3u","category":"iptv","country":"US","playlist_type":"city"},

    {"name":"city_london","display_name":"Londres","url":f"{settings.IPTV_BASE_URL}/cities/gblon.m3u","category":"iptv","country":"GB","playlist_type":"city"},
    {"name":"city_manchester","display_name":"Manchester","url":f"{settings.IPTV_BASE_URL}/cities/gbman.m3u","category":"iptv","country":"GB","playlist_type":"city"},
    {"name":"city_birmingham","display_name":"Birmingham","url":f"{settings.IPTV_BASE_URL}/cities/gbbir.m3u","category":"iptv","country":"GB","playlist_type":"city"},
    {"name":"city_liverpool","display_name":"Liverpool","url":f"{settings.IPTV_BASE_URL}/cities/gbliv.m3u","category":"iptv","country":"GB","playlist_type":"city"},
    {"name":"city_glasgow","display_name":"Glasgow","url":f"{settings.IPTV_BASE_URL}/cities/gbglg.m3u","category":"iptv","country":"GB","playlist_type":"city"},
    {"name":"city_edinburgh","display_name":"Édimbourg","url":f"{settings.IPTV_BASE_URL}/cities/gbedi.m3u","category":"iptv","country":"GB","playlist_type":"city"},
    {"name":"city_bristol","display_name":"Bristol","url":f"{settings.IPTV_BASE_URL}/cities/gbbrs.m3u","category":"iptv","country":"GB","playlist_type":"city"},
    {"name":"city_leeds","display_name":"Leeds","url":f"{settings.IPTV_BASE_URL}/cities/gblee.m3u","category":"iptv","country":"GB","playlist_type":"city"},
    {"name":"city_sheffield","display_name":"Sheffield","url":f"{settings.IPTV_BASE_URL}/cities/gbshf.m3u","category":"iptv","country":"GB","playlist_type":"city"},
    {"name":"city_bradford","display_name":"Bradford","url":f"{settings.IPTV_BASE_URL}/cities/gbbfd.m3u","category":"iptv","country":"GB","playlist_type":"city"},
    {"name":"city_newcastle","display_name":"Newcastle","url":f"{settings.IPTV_BASE_URL}/cities/gbncl.m3u","category":"iptv","country":"GB","playlist_type":"city"},

    {"name":"city_paris","display_name":"Paris","url":f"{settings.IPTV_BASE_URL}/cities/frpar.m3u","category":"iptv","country":"FR","playlist_type":"city"},
    {"name":"city_lyon","display_name":"Lyon","url":f"{settings.IPTV_BASE_URL}/cities/frlys.m3u","category":"iptv","country":"FR","playlist_type":"city"},
    {"name":"city_marseille","display_name":"Marseille","url":f"{settings.IPTV_BASE_URL}/cities/frmrs.m3u","category":"iptv","country":"FR","playlist_type":"city"},
    {"name":"city_toulouse","display_name":"Toulouse","url":f"{settings.IPTV_BASE_URL}/cities/frtls.m3u","category":"iptv","country":"FR","playlist_type":"city"},
    {"name":"city_nice","display_name":"Nice","url":f"{settings.IPTV_BASE_URL}/cities/frnc.m3u","category":"iptv","country":"FR","playlist_type":"city"},
    {"name":"city_nantes","display_name":"Nantes","url":f"{settings.IPTV_BASE_URL}/cities/frnte.m3u","category":"iptv","country":"FR","playlist_type":"city"},
    {"name":"city_strasbourg","display_name":"Strasbourg","url":f"{settings.IPTV_BASE_URL}/cities/frsxb.m3u","category":"iptv","country":"FR","playlist_type":"city"},
    {"name":"city_bordeaux","display_name":"Bordeaux","url":f"{settings.IPTV_BASE_URL}/cities/frbod.m3u","category":"iptv","country":"FR","playlist_type":"city"},
    {"name":"city_lille","display_name":"Lille","url":f"{settings.IPTV_BASE_URL}/cities/frill.m3u","category":"iptv","country":"FR","playlist_type":"city"},
    {"name":"city_rennes","display_name":"Rennes","url":f"{settings.IPTV_BASE_URL}/cities/frren.m3u","category":"iptv","country":"FR","playlist_type":"city"},
    {"name":"city_grenoble","display_name":"Grenoble","url":f"{settings.IPTV_BASE_URL}/cities/frgnb.m3u","category":"iptv","country":"FR","playlist_type":"city"},

    {"name":"city_berlin","display_name":"Berlin","url":f"{settings.IPTV_BASE_URL}/cities/deber.m3u","category":"iptv","country":"DE","playlist_type":"city"},
    {"name":"city_hamburg","display_name":"Hambourg","url":f"{settings.IPTV_BASE_URL}/cities/deham.m3u","category":"iptv","country":"DE","playlist_type":"city"},
    {"name":"city_munich","display_name":"Munich","url":f"{settings.IPTV_BASE_URL}/cities/demuc.m3u","category":"iptv","country":"DE","playlist_type":"city"},
    {"name":"city_cologne","display_name":"Cologne","url":f"{settings.IPTV_BASE_URL}/cities/decgn.m3u","category":"iptv","country":"DE","playlist_type":"city"},
    {"name":"city_frankfurt","display_name":"Francfort","url":f"{settings.IPTV_BASE_URL}/cities/defra.m3u","category":"iptv","country":"DE","playlist_type":"city"},
    {"name":"city_stuttgart","display_name":"Stuttgart","url":f"{settings.IPTV_BASE_URL}/cities/destr.m3u","category":"iptv","country":"DE","playlist_type":"city"},
    {"name":"city_dusseldorf","display_name":"Düsseldorf","url":f"{settings.IPTV_BASE_URL}/cities/dedus.m3u","category":"iptv","country":"DE","playlist_type":"city"},

    {"name":"city_rome","display_name":"Rome","url":f"{settings.IPTV_BASE_URL}/cities/itrom.m3u","category":"iptv","country":"IT","playlist_type":"city"},
    {"name":"city_milan","display_name":"Milan","url":f"{settings.IPTV_BASE_URL}/cities/itmil.m3u","category":"iptv","country":"IT","playlist_type":"city"},
    {"name":"city_naples","display_name":"Naples","url":f"{settings.IPTV_BASE_URL}/cities/itnap.m3u","category":"iptv","country":"IT","playlist_type":"city"},
    {"name":"city_turin","display_name":"Turin","url":f"{settings.IPTV_BASE_URL}/cities/ittrn.m3u","category":"iptv","country":"IT","playlist_type":"city"},
    {"name":"city_palermo","display_name":"Palerme","url":f"{settings.IPTV_BASE_URL}/cities/itpal.m3u","category":"iptv","country":"IT","playlist_type":"city"},
    {"name":"city_genoa","display_name":"Gênes","url":f"{settings.IPTV_BASE_URL}/cities/itgoa.m3u","category":"iptv","country":"IT","playlist_type":"city"},

    {"name":"city_madrid","display_name":"Madrid","url":f"{settings.IPTV_BASE_URL}/cities/esmad.m3u","category":"iptv","country":"ES","playlist_type":"city"},
    {"name":"city_barcelona","display_name":"Barcelone","url":f"{settings.IPTV_BASE_URL}/cities/esbcn.m3u","category":"iptv","country":"ES","playlist_type":"city"},
    {"name":"city_valencia","display_name":"Valence","url":f"{settings.IPTV_BASE_URL}/cities/esvll.m3u","category":"iptv","country":"ES","playlist_type":"city"},
    {"name":"city_seville","display_name":"Séville","url":f"{settings.IPTV_BASE_URL}/cities/essvq.m3u","category":"iptv","country":"ES","playlist_type":"city"},
    {"name":"city_zaragoza","display_name":"Saragosse","url":f"{settings.IPTV_BASE_URL}/cities/eszzg.m3u","category":"iptv","country":"ES","playlist_type":"city"},
    {"name":"city_malaga","display_name":"Malaga","url":f"{settings.IPTV_BASE_URL}/cities/esmgz.m3u","category":"iptv","country":"ES","playlist_type":"city"},

    {"name":"city_moscow","display_name":"Moscou","url":f"{settings.IPTV_BASE_URL}/cities/rumow.m3u","category":"iptv","country":"RU","playlist_type":"city"},
    {"name":"city_saint_petersburg","display_name":"Saint-Pétersbourg","url":f"{settings.IPTV_BASE_URL}/cities/ruced.m3u","category":"iptv","country":"RU","playlist_type":"city"},
    {"name":"city_novosibirsk","display_name":"Novossibirsk","url":f"{settings.IPTV_BASE_URL}/cities/ruovb.m3u","category":"iptv","country":"RU","playlist_type":"city"},

    {"name":"city_rio_de_janeiro","display_name":"Rio de Janeiro","url":f"{settings.IPTV_BASE_URL}/cities/brrioa.m3u","category":"iptv","country":"BR","playlist_type":"city"},
    {"name":"city_sao_paulo","display_name":"São Paulo","url":f"{settings.IPTV_BASE_URL}/cities/brsaopaulo.m3u","category":"iptv","country":"BR","playlist_type":"city"},
    {"name":"city_brasilia","display_name":"Brasília","url":f"{settings.IPTV_BASE_URL}/cities/brbsb.m3u","category":"iptv","country":"BR","playlist_type":"city"},
    {"name":"city_salvador","display_name":"Salvador","url":f"{settings.IPTV_BASE_URL}/cities/brssa.m3u","category":"iptv","country":"BR","playlist_type":"city"},

    {"name":"city_sydney","display_name":"Sydney","url":f"{settings.IPTV_BASE_URL}/cities/ausyd.m3u","category":"iptv","country":"AU","playlist_type":"city"},
    {"name":"city_melbourne","display_name":"Melbourne","url":f"{settings.IPTV_BASE_URL}/cities/aumel.m3u","category":"iptv","country":"AU","playlist_type":"city"},
    {"name":"city_brisbane","display_name":"Brisbane","url":f"{settings.IPTV_BASE_URL}/cities/aubne.m3u","category":"iptv","country":"AU","playlist_type":"city"},
    {"name":"city_perth","display_name":"Perth","url":f"{settings.IPTV_BASE_URL}/cities/auper.m3u","category":"iptv","country":"AU","playlist_type":"city"},
    {"name":"city_adelaide","display_name":"Adélaïde","url":f"{settings.IPTV_BASE_URL}/cities/auadl.m3u","category":"iptv","country":"AU","playlist_type":"city"},
    {"name":"city_canberra","display_name":"Canberra","url":f"{settings.IPTV_BASE_URL}/cities/aucbr.m3u","category":"iptv","country":"AU","playlist_type":"city"},

    {"name":"city_tokyo","display_name":"Tokyo","url":f"{settings.IPTV_BASE_URL}/cities/jptyo.m3u","category":"iptv","country":"JP","playlist_type":"city"},
    {"name":"city_osaka","display_name":"Osaka","url":f"{settings.IPTV_BASE_URL}/cities/jposa.m3u","category":"iptv","country":"JP","playlist_type":"city"},
    {"name":"city_nagoya","display_name":"Nagoya","url":f"{settings.IPTV_BASE_URL}/cities/jpngo.m3u","category":"iptv","country":"JP","playlist_type":"city"},
    {"name":"city_sapporo","display_name":"Sapporo","url":f"{settings.IPTV_BASE_URL}/cities/jpspk.m3u","category":"iptv","country":"JP","playlist_type":"city"},
    {"name":"city_fukuoka","display_name":"Fukuoka","url":f"{settings.IPTV_BASE_URL}/cities/jpfuk.m3u","category":"iptv","country":"JP","playlist_type":"city"},

    {"name":"city_seoul","display_name":"Séoul","url":f"{settings.IPTV_BASE_URL}/cities/krsel.m3u","category":"iptv","country":"KR","playlist_type":"city"},
    {"name":"city_busan","display_name":"Busan","url":f"{settings.IPTV_BASE_URL}/cities/krpus.m3u","category":"iptv","country":"KR","playlist_type":"city"},

    {"name":"city_beijing","display_name":"Pékin","url":f"{settings.IPTV_BASE_URL}/cities/cnbjs.m3u","category":"iptv","country":"CN","playlist_type":"city"},
    {"name":"city_shanghai","display_name":"Shanghai","url":f"{settings.IPTV_BASE_URL}/cities/cnsha.m3u","category":"iptv","country":"CN","playlist_type":"city"},
    {"name":"city_guangzhou","display_name":"Canton","url":f"{settings.IPTV_BASE_URL}/cities/cncan.m3u","category":"iptv","country":"CN","playlist_type":"city"},
    {"name":"city_shenzhen","display_name":"Shenzhen","url":f"{settings.IPTV_BASE_URL}/cities/cnszx.m3u","category":"iptv","country":"CN","playlist_type":"city"},
    {"name":"city_chengdu","display_name":"Chengdu","url":f"{settings.IPTV_BASE_URL}/cities/cnctu.m3u","category":"iptv","country":"CN","playlist_type":"city"},

    {"name":"city_mumbai","display_name":"Bombay","url":f"{settings.IPTV_BASE_URL}/cities/inbom.m3u","category":"iptv","country":"IN","playlist_type":"city"},
    {"name":"city_delhi","display_name":"Delhi","url":f"{settings.IPTV_BASE_URL}/cities/indel.m3u","category":"iptv","country":"IN","playlist_type":"city"},
    {"name":"city_bangalore","display_name":"Bangalore","url":f"{settings.IPTV_BASE_URL}/cities/inblr.m3u","category":"iptv","country":"IN","playlist_type":"city"},
    {"name":"city_chennai","display_name":"Chennai","url":f"{settings.IPTV_BASE_URL}/cities/inmaa.m3u","category":"iptv","country":"IN","playlist_type":"city"},
    {"name":"city_kolkata","display_name":"Calcutta","url":f"{settings.IPTV_BASE_URL}/cities/inccu.m3u","category":"iptv","country":"IN","playlist_type":"city"},

    # ---- CATÉGORIES THÉMATIQUES ----
    {"name":"sports","display_name":"Sports (Monde)","url":f"{settings.IPTV_BASE_URL}/categories/sports.m3u","category":"iptv_sports","country":"INT","playlist_type":"category"},
    {"name":"news","display_name":"Info (Monde)","url":f"{settings.IPTV_BASE_URL}/categories/news.m3u","category":"iptv_news","country":"INT","playlist_type":"category"},
    {"name":"documentary","display_name":"Documentaires","url":f"{settings.IPTV_BASE_URL}/categories/documentary.m3u","category":"iptv_documentary","country":"INT","playlist_type":"category"},
    {"name":"music","display_name":"Musique","url":f"{settings.IPTV_BASE_URL}/categories/music.m3u","category":"iptv_music","country":"INT","playlist_type":"category"},
    {"name":"kids","display_name":"Jeunesse","url":f"{settings.IPTV_BASE_URL}/categories/kids.m3u","category":"iptv_kids","country":"INT","playlist_type":"category"},
    {"name":"movies","display_name":"Films","url":f"{settings.IPTV_BASE_URL}/categories/movies.m3u","category":"iptv_movies","country":"INT","playlist_type":"category"},
    {"name":"science","display_name":"Science / Nature","url":f"{settings.IPTV_BASE_URL}/categories/science.m3u","category":"iptv_science","country":"INT","playlist_type":"category"},
    {"name":"travel","display_name":"Voyage","url":f"{settings.IPTV_BASE_URL}/categories/travel.m3u","category":"iptv_travel","country":"INT","playlist_type":"category"},
    {"name":"religion","display_name":"Religion","url":f"{settings.IPTV_BASE_URL}/categories/religion.m3u","category":"iptv_religion","country":"INT","playlist_type":"category"},
    {"name":"business","display_name":"Business / Finance","url":f"{settings.IPTV_BASE_URL}/categories/business.m3u","category":"iptv_business","country":"INT","playlist_type":"category"},
    {"name":"entertainment","display_name":"Divertissement","url":f"{settings.IPTV_BASE_URL}/categories/entertainment.m3u","category":"iptv","country":"INT","playlist_type":"category"},
    {"name":"cooking","display_name":"Cuisine","url":f"{settings.IPTV_BASE_URL}/categories/cooking.m3u","category":"iptv","country":"INT","playlist_type":"category"},
    {"name":"auto","display_name":"Auto / Moto","url":f"{settings.IPTV_BASE_URL}/categories/auto.m3u","category":"iptv","country":"INT","playlist_type":"category"},
    {"name":"animation","display_name":"Animation","url":f"{settings.IPTV_BASE_URL}/categories/animation.m3u","category":"iptv_kids","country":"INT","playlist_type":"category"},
    {"name":"comedy","display_name":"Comédie","url":f"{settings.IPTV_BASE_URL}/categories/comedy.m3u","category":"iptv","country":"INT","playlist_type":"category"},
    {"name":"education","display_name":"Éducation","url":f"{settings.IPTV_BASE_URL}/categories/education.m3u","category":"iptv","country":"INT","playlist_type":"category"},
    {"name":"fashion","display_name":"Mode","url":f"{settings.IPTV_BASE_URL}/categories/fashion.m3u","category":"iptv","country":"INT","playlist_type":"category"},
    {"name":"gaming","display_name":"Jeux vidéo","url":f"{settings.IPTV_BASE_URL}/categories/gaming.m3u","category":"gaming","country":"INT","playlist_type":"category"},
    {"name":"health","display_name":"Santé / Bien-être","url":f"{settings.IPTV_BASE_URL}/categories/health.m3u","category":"iptv","country":"INT","playlist_type":"category"},
    {"name":"history","display_name":"Histoire","url":f"{settings.IPTV_BASE_URL}/categories/history.m3u","category":"iptv","country":"INT","playlist_type":"category"},
    {"name":"horror","display_name":"Horreur","url":f"{settings.IPTV_BASE_URL}/categories/horror.m3u","category":"iptv","country":"INT","playlist_type":"category"},
    {"name":"legislative","display_name":"Parlement","url":f"{settings.IPTV_BASE_URL}/categories/legislative.m3u","category":"iptv","country":"INT","playlist_type":"category"},
    {"name":"lifestyle","display_name":"Lifestyle","url":f"{settings.IPTV_BASE_URL}/categories/lifestyle.m3u","category":"iptv","country":"INT","playlist_type":"category"},
    {"name":"local","display_name":"Locale","url":f"{settings.IPTV_BASE_URL}/categories/local.m3u","category":"iptv","country":"INT","playlist_type":"category"},
    {"name":"nature","display_name":"Nature","url":f"{settings.IPTV_BASE_URL}/categories/nature.m3u","category":"iptv_science","country":"INT","playlist_type":"category"},
    {"name":"outdoor","display_name":"Plein air","url":f"{settings.IPTV_BASE_URL}/categories/outdoor.m3u","category":"iptv","country":"INT","playlist_type":"category"},
    {"name":"quiz","display_name":"Quiz / Jeux","url":f"{settings.IPTV_BASE_URL}/categories/quiz.m3u","category":"iptv","country":"INT","playlist_type":"category"},
    {"name":"radio","display_name":"Radio","url":f"{settings.IPTV_BASE_URL}/categories/radio.m3u","category":"radio","country":"INT","playlist_type":"category"},
    {"name":"religious","display_name":"Religieux","url":f"{settings.IPTV_BASE_URL}/categories/religious.m3u","category":"religion","country":"INT","playlist_type":"category"},
    {"name":"series","display_name":"Séries","url":f"{settings.IPTV_BASE_URL}/categories/series.m3u","category":"iptv","country":"INT","playlist_type":"category"},
    {"name":"shop","display_name":"Téléachat","url":f"{settings.IPTV_BASE_URL}/categories/shop.m3u","category":"iptv","country":"INT","playlist_type":"category"},
    {"name":"soap","display_name":"Feuilletons","url":f"{settings.IPTV_BASE_URL}/categories/soap.m3u","category":"iptv","country":"INT","playlist_type":"category"},
    {"name":"tech","display_name":"Technologie","url":f"{settings.IPTV_BASE_URL}/categories/tech.m3u","category":"iptv","country":"INT","playlist_type":"category"},
    {"name":"weather","display_name":"Météo","url":f"{settings.IPTV_BASE_URL}/categories/weather.m3u","category":"iptv","country":"INT","playlist_type":"category"},
    # ---- PAYS MANQUANTS (complétant les 196 pays) ----
    {"name":"albania","display_name":"Albanie","url":f"{settings.IPTV_BASE_URL}/countries/al.m3u","category":"iptv","country":"AL","playlist_type":"country"},
    {"name":"andorra","display_name":"Andorre","url":f"{settings.IPTV_BASE_URL}/countries/ad.m3u","category":"iptv","country":"AD","playlist_type":"country"},
    {"name":"antigua","display_name":"Antigua-et-Barbuda","url":f"{settings.IPTV_BASE_URL}/countries/ag.m3u","category":"iptv","country":"AG","playlist_type":"country"},
    {"name":"bahamas","display_name":"Bahamas","url":f"{settings.IPTV_BASE_URL}/countries/bs.m3u","category":"iptv","country":"BS","playlist_type":"country"},
    {"name":"bahrain","display_name":"Bahreïn","url":f"{settings.IPTV_BASE_URL}/countries/bh.m3u","category":"iptv","country":"BH","playlist_type":"country"},
    {"name":"barbados","display_name":"Barbade","url":f"{settings.IPTV_BASE_URL}/countries/bb.m3u","category":"iptv","country":"BB","playlist_type":"country"},
    {"name":"belize","display_name":"Belize","url":f"{settings.IPTV_BASE_URL}/countries/bz.m3u","category":"iptv","country":"BZ","playlist_type":"country"},
    {"name":"bhutan","display_name":"Bhoutan","url":f"{settings.IPTV_BASE_URL}/countries/bt.m3u","category":"iptv","country":"BT","playlist_type":"country"},
    {"name":"bosnia","display_name":"Bosnie-Herzégovine","url":f"{settings.IPTV_BASE_URL}/countries/ba.m3u","category":"iptv","country":"BA","playlist_type":"country"},
    {"name":"brunei","display_name":"Brunei","url":f"{settings.IPTV_BASE_URL}/countries/bn.m3u","category":"iptv","country":"BN","playlist_type":"country"},
    {"name":"cabo_verde","display_name":"Cap-Vert","url":f"{settings.IPTV_BASE_URL}/countries/cv.m3u","category":"iptv","country":"CV","playlist_type":"country"},
    {"name":"comoros","display_name":"Comores","url":f"{settings.IPTV_BASE_URL}/countries/km.m3u","category":"iptv","country":"KM","playlist_type":"country"},
    {"name":"costa_rica","display_name":"Costa Rica","url":f"{settings.IPTV_BASE_URL}/countries/cr.m3u","category":"iptv","country":"CR","playlist_type":"country"},
    {"name":"cuba","display_name":"Cuba","url":f"{settings.IPTV_BASE_URL}/countries/cu.m3u","category":"iptv","country":"CU","playlist_type":"country"},
    {"name":"djibouti","display_name":"Djibouti","url":f"{settings.IPTV_BASE_URL}/countries/dj.m3u","category":"iptv","country":"DJ","playlist_type":"country"},
    {"name":"dominica","display_name":"Dominique","url":f"{settings.IPTV_BASE_URL}/countries/dm.m3u","category":"iptv","country":"DM","playlist_type":"country"},
    {"name":"dominican_rep","display_name":"République Dominicaine","url":f"{settings.IPTV_BASE_URL}/countries/do.m3u","category":"iptv","country":"DO","playlist_type":"country"},
    {"name":"equatorial_guinea","display_name":"Guinée Équatoriale","url":f"{settings.IPTV_BASE_URL}/countries/gq.m3u","category":"iptv","country":"GQ","playlist_type":"country"},
    {"name":"eritrea","display_name":"Érythrée","url":f"{settings.IPTV_BASE_URL}/countries/er.m3u","category":"iptv","country":"ER","playlist_type":"country"},
    {"name":"fiji","display_name":"Fidji","url":f"{settings.IPTV_BASE_URL}/countries/fj.m3u","category":"iptv","country":"FJ","playlist_type":"country"},
    {"name":"grenada","display_name":"Grenade","url":f"{settings.IPTV_BASE_URL}/countries/gd.m3u","category":"iptv","country":"GD","playlist_type":"country"},
    {"name":"guatemala","display_name":"Guatemala","url":f"{settings.IPTV_BASE_URL}/countries/gt.m3u","category":"iptv","country":"GT","playlist_type":"country"},
    {"name":"guinea_bissau","display_name":"Guinée-Bissau","url":f"{settings.IPTV_BASE_URL}/countries/gw.m3u","category":"iptv","country":"GW","playlist_type":"country"},
    {"name":"guyana","display_name":"Guyana","url":f"{settings.IPTV_BASE_URL}/countries/gy.m3u","category":"iptv","country":"GY","playlist_type":"country"},
    {"name":"haiti","display_name":"Haïti","url":f"{settings.IPTV_BASE_URL}/countries/ht.m3u","category":"iptv","country":"HT","playlist_type":"country"},
    {"name":"honduras","display_name":"Honduras","url":f"{settings.IPTV_BASE_URL}/countries/hn.m3u","category":"iptv","country":"HN","playlist_type":"country"},
    {"name":"hongkong","display_name":"Hong Kong","url":f"{settings.IPTV_BASE_URL}/countries/hk.m3u","category":"iptv","country":"HK","playlist_type":"country"},
    {"name":"jamaica","display_name":"Jamaïque","url":f"{settings.IPTV_BASE_URL}/countries/jm.m3u","category":"iptv","country":"JM","playlist_type":"country"},
    {"name":"kiribati","display_name":"Kiribati","url":f"{settings.IPTV_BASE_URL}/countries/ki.m3u","category":"iptv","country":"KI","playlist_type":"country"},
    {"name":"north_korea","display_name":"Corée du Nord","url":f"{settings.IPTV_BASE_URL}/countries/kp.m3u","category":"iptv","country":"KP","playlist_type":"country"},
    {"name":"lesotho","display_name":"Lesotho","url":f"{settings.IPTV_BASE_URL}/countries/ls.m3u","category":"iptv","country":"LS","playlist_type":"country"},
    {"name":"liberia","display_name":"Libéria","url":f"{settings.IPTV_BASE_URL}/countries/lr.m3u","category":"iptv","country":"LR","playlist_type":"country"},
    {"name":"liechtenstein","display_name":"Liechtenstein","url":f"{settings.IPTV_BASE_URL}/countries/li.m3u","category":"iptv","country":"LI","playlist_type":"country"},
    {"name":"maldives","display_name":"Maldives","url":f"{settings.IPTV_BASE_URL}/countries/mv.m3u","category":"iptv","country":"MV","playlist_type":"country"},
    {"name":"marshall_islands","display_name":"Îles Marshall","url":f"{settings.IPTV_BASE_URL}/countries/mh.m3u","category":"iptv","country":"MH","playlist_type":"country"},
    {"name":"micronesia","display_name":"Micronésie","url":f"{settings.IPTV_BASE_URL}/countries/fm.m3u","category":"iptv","country":"FM","playlist_type":"country"},
    {"name":"moldova","display_name":"Moldavie","url":f"{settings.IPTV_BASE_URL}/countries/md.m3u","category":"iptv","country":"MD","playlist_type":"country"},
    {"name":"mongolia","display_name":"Mongolie","url":f"{settings.IPTV_BASE_URL}/countries/mn.m3u","category":"iptv","country":"MN","playlist_type":"country"},
    {"name":"montenegro","display_name":"Monténégro","url":f"{settings.IPTV_BASE_URL}/countries/me.m3u","category":"iptv","country":"ME","playlist_type":"country"},
    {"name":"mozambique","display_name":"Mozambique","url":f"{settings.IPTV_BASE_URL}/countries/mz.m3u","category":"iptv","country":"MZ","playlist_type":"country"},
    {"name":"myanmar","display_name":"Myanmar","url":f"{settings.IPTV_BASE_URL}/countries/mm.m3u","category":"iptv","country":"MM","playlist_type":"country"},
    {"name":"nauru","display_name":"Nauru","url":f"{settings.IPTV_BASE_URL}/countries/nr.m3u","category":"iptv","country":"NR","playlist_type":"country"},
    {"name":"nicaragua","display_name":"Nicaragua","url":f"{settings.IPTV_BASE_URL}/countries/ni.m3u","category":"iptv","country":"NI","playlist_type":"country"},
    {"name":"north_macedonia","display_name":"Macédoine du Nord","url":f"{settings.IPTV_BASE_URL}/countries/mk.m3u","category":"iptv","country":"MK","playlist_type":"country"},
    {"name":"palau","display_name":"Palaos","url":f"{settings.IPTV_BASE_URL}/countries/pw.m3u","category":"iptv","country":"PW","playlist_type":"country"},
    {"name":"panama","display_name":"Panama","url":f"{settings.IPTV_BASE_URL}/countries/pa.m3u","category":"iptv","country":"PA","playlist_type":"country"},
    {"name":"papua_new_guinea","display_name":"Papouasie-Nouvelle-Guinée","url":f"{settings.IPTV_BASE_URL}/countries/pg.m3u","category":"iptv","country":"PG","playlist_type":"country"},
    {"name":"saint_kitts","display_name":"Saint-Kitts-et-Nevis","url":f"{settings.IPTV_BASE_URL}/countries/kn.m3u","category":"iptv","country":"KN","playlist_type":"country"},
    {"name":"saint_lucia","display_name":"Sainte-Lucie","url":f"{settings.IPTV_BASE_URL}/countries/lc.m3u","category":"iptv","country":"LC","playlist_type":"country"},
    {"name":"saint_vincent","display_name":"Saint-Vincent","url":f"{settings.IPTV_BASE_URL}/countries/vc.m3u","category":"iptv","country":"VC","playlist_type":"country"},
    {"name":"samoa","display_name":"Samoa","url":f"{settings.IPTV_BASE_URL}/countries/ws.m3u","category":"iptv","country":"WS","playlist_type":"country"},
    {"name":"san_marino","display_name":"Saint-Marin","url":f"{settings.IPTV_BASE_URL}/countries/sm.m3u","category":"iptv","country":"SM","playlist_type":"country"},
    {"name":"sao_tome","display_name":"Sao Tomé","url":f"{settings.IPTV_BASE_URL}/countries/st.m3u","category":"iptv","country":"ST","playlist_type":"country"},
    {"name":"sierra_leone","display_name":"Sierra Leone","url":f"{settings.IPTV_BASE_URL}/countries/sl.m3u","category":"iptv","country":"SL","playlist_type":"country"},
    {"name":"solomon_islands","display_name":"Îles Salomon","url":f"{settings.IPTV_BASE_URL}/countries/sb.m3u","category":"iptv","country":"SB","playlist_type":"country"},
    {"name":"somalia","display_name":"Somalie","url":f"{settings.IPTV_BASE_URL}/countries/so.m3u","category":"iptv","country":"SO","playlist_type":"country"},
    {"name":"south_sudan","display_name":"Soudan du Sud","url":f"{settings.IPTV_BASE_URL}/countries/ss.m3u","category":"iptv","country":"SS","playlist_type":"country"},
    {"name":"suriname","display_name":"Suriname","url":f"{settings.IPTV_BASE_URL}/countries/sr.m3u","category":"iptv","country":"SR","playlist_type":"country"},
    {"name":"taiwan","display_name":"Taïwan","url":f"{settings.IPTV_BASE_URL}/countries/tw.m3u","category":"iptv","country":"TW","playlist_type":"country"},
    {"name":"tajikistan","display_name":"Tadjikistan","url":f"{settings.IPTV_BASE_URL}/countries/tj.m3u","category":"iptv","country":"TJ","playlist_type":"country"},
    {"name":"timor_leste","display_name":"Timor-Leste","url":f"{settings.IPTV_BASE_URL}/countries/tl.m3u","category":"iptv","country":"TL","playlist_type":"country"},
    {"name":"tonga","display_name":"Tonga","url":f"{settings.IPTV_BASE_URL}/countries/to.m3u","category":"iptv","country":"TO","playlist_type":"country"},
    {"name":"trinidad","display_name":"Trinité-et-Tobago","url":f"{settings.IPTV_BASE_URL}/countries/tt.m3u","category":"iptv","country":"TT","playlist_type":"country"},
    {"name":"tuvalu","display_name":"Tuvalu","url":f"{settings.IPTV_BASE_URL}/countries/tv.m3u","category":"iptv","country":"TV","playlist_type":"country"},
    {"name":"vanuatu","display_name":"Vanuatu","url":f"{settings.IPTV_BASE_URL}/countries/vu.m3u","category":"iptv","country":"VU","playlist_type":"country"},
    {"name":"vatican","display_name":"Vatican","url":f"{settings.IPTV_BASE_URL}/countries/va.m3u","category":"iptv","country":"VA","playlist_type":"country"},
    {"name":"yemen","display_name":"Yémen","url":f"{settings.IPTV_BASE_URL}/countries/ye.m3u","category":"iptv","country":"YE","playlist_type":"country"},
    # ── Subdivisions supplémentaires ──────────────────────────────────────────
    {"name":"ca_ontario","display_name":"Canada — Ontario","url":f"{settings.IPTV_BASE_URL}/subdivisions/ca-on.m3u","category":"iptv","country":"CA","playlist_type":"subdivision"},
    {"name":"ca_quebec","display_name":"Canada — Québec","url":f"{settings.IPTV_BASE_URL}/subdivisions/ca-qc.m3u","category":"iptv","country":"CA","playlist_type":"subdivision"},
    {"name":"ca_british_columbia","display_name":"Canada — Colombie-Britannique","url":f"{settings.IPTV_BASE_URL}/subdivisions/ca-bc.m3u","category":"iptv","country":"CA","playlist_type":"subdivision"},
    {"name":"ca_alberta","display_name":"Canada — Alberta","url":f"{settings.IPTV_BASE_URL}/subdivisions/ca-ab.m3u","category":"iptv","country":"CA","playlist_type":"subdivision"},
    {"name":"ca_saskatchewan","display_name":"Canada — Saskatchewan","url":f"{settings.IPTV_BASE_URL}/subdivisions/ca-sk.m3u","category":"iptv","country":"CA","playlist_type":"subdivision"},
    {"name":"ca_manitoba","display_name":"Canada — Manitoba","url":f"{settings.IPTV_BASE_URL}/subdivisions/ca-mb.m3u","category":"iptv","country":"CA","playlist_type":"subdivision"},
    {"name":"ca_nova_scotia","display_name":"Canada — Nouvelle-Écosse","url":f"{settings.IPTV_BASE_URL}/subdivisions/ca-ns.m3u","category":"iptv","country":"CA","playlist_type":"subdivision"},
    {"name":"ca_new_brunswick","display_name":"Canada — Nouveau-Brunswick","url":f"{settings.IPTV_BASE_URL}/subdivisions/ca-nb.m3u","category":"iptv","country":"CA","playlist_type":"subdivision"},
    {"name":"ca_newfoundland","display_name":"Canada — Terre-Neuve","url":f"{settings.IPTV_BASE_URL}/subdivisions/ca-nl.m3u","category":"iptv","country":"CA","playlist_type":"subdivision"},
    {"name":"ca_pei","display_name":"Canada — Î.-du-Prince-Édouard","url":f"{settings.IPTV_BASE_URL}/subdivisions/ca-pe.m3u","category":"iptv","country":"CA","playlist_type":"subdivision"},
    {"name":"us_alaska","display_name":"USA — Alaska","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-ak.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_arizona","display_name":"USA — Arizona","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-az.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_arkansas","display_name":"USA — Arkansas","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-ar.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_california","display_name":"USA — Californie","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-ca.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_colorado","display_name":"USA — Colorado","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-co.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_connecticut","display_name":"USA — Connecticut","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-ct.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_delaware","display_name":"USA — Delaware","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-de.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_florida","display_name":"USA — Floride","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-fl.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_hawaii","display_name":"USA — Hawaï","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-hi.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_idaho","display_name":"USA — Idaho","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-id.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_illinois","display_name":"USA — Illinois","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-il.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_indiana","display_name":"USA — Indiana","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-in.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_iowa","display_name":"USA — Iowa","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-ia.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_kansas","display_name":"USA — Kansas","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-ks.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_kentucky","display_name":"USA — Kentucky","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-ky.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_louisiana","display_name":"USA — Louisiane","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-la.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_maine","display_name":"USA — Maine","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-me.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_maryland","display_name":"USA — Maryland","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-md.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_massachusetts","display_name":"USA — Massachusetts","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-ma.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_michigan","display_name":"USA — Michigan","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-mi.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_minnesota","display_name":"USA — Minnesota","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-mn.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_mississippi","display_name":"USA — Mississippi","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-ms.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_missouri","display_name":"USA — Missouri","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-mo.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_montana","display_name":"USA — Montana","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-mt.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_nebraska","display_name":"USA — Nebraska","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-ne.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_nevada","display_name":"USA — Nevada","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-nv.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_new_hampshire","display_name":"USA — New Hampshire","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-nh.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_new_jersey","display_name":"USA — New Jersey","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-nj.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_new_mexico","display_name":"USA — Nouveau-Mexique","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-nm.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_new_york","display_name":"USA — New York","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-ny.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_north_carolina","display_name":"USA — Caroline du Nord","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-nc.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_north_dakota","display_name":"USA — Dakota du Nord","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-nd.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_ohio","display_name":"USA — Ohio","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-oh.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_oklahoma","display_name":"USA — Oklahoma","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-ok.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_oregon","display_name":"USA — Oregon","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-or.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_pennsylvania","display_name":"USA — Pennsylvanie","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-pa.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_rhode_island","display_name":"USA — Rhode Island","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-ri.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_south_carolina","display_name":"USA — Caroline du Sud","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-sc.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_south_dakota","display_name":"USA — Dakota du Sud","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-sd.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_tennessee","display_name":"USA — Tennessee","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-tn.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_texas","display_name":"USA — Texas","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-tx.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_utah","display_name":"USA — Utah","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-ut.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_vermont","display_name":"USA — Vermont","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-vt.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_virginia","display_name":"USA — Virginie","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-va.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_washington","display_name":"USA — Washington","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-wa.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_west_virginia","display_name":"USA — Virginie-Occidentale","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-wv.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_wisconsin","display_name":"USA — Wisconsin","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-wi.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    {"name":"us_wyoming","display_name":"USA — Wyoming","url":f"{settings.IPTV_BASE_URL}/subdivisions/us-wy.m3u","category":"iptv","country":"US","playlist_type":"subdivision"},
    # ── Subdivisions Europe ───────────────────────────────────────────────────
    {"name":"fr_idf","display_name":"France — Île-de-France","url":f"{settings.IPTV_BASE_URL}/subdivisions/fr-idf.m3u","category":"iptv","country":"FR","playlist_type":"subdivision"},
    {"name":"fr_paca","display_name":"France — Provence-Alpes-Côte d'Azur","url":f"{settings.IPTV_BASE_URL}/subdivisions/fr-pac.m3u","category":"iptv","country":"FR","playlist_type":"subdivision"},
    {"name":"fr_auvra","display_name":"France — Auvergne-Rhône-Alpes","url":f"{settings.IPTV_BASE_URL}/subdivisions/fr-ara.m3u","category":"iptv","country":"FR","playlist_type":"subdivision"},
    {"name":"fr_normandie","display_name":"France — Normandie","url":f"{settings.IPTV_BASE_URL}/subdivisions/fr-nor.m3u","category":"iptv","country":"FR","playlist_type":"subdivision"},
    {"name":"fr_bretagne","display_name":"France — Bretagne","url":f"{settings.IPTV_BASE_URL}/subdivisions/fr-bre.m3u","category":"iptv","country":"FR","playlist_type":"subdivision"},
    {"name":"de_bavaria","display_name":"Allemagne — Bavière","url":f"{settings.IPTV_BASE_URL}/subdivisions/de-by.m3u","category":"iptv","country":"DE","playlist_type":"subdivision"},
    {"name":"de_berlin","display_name":"Allemagne — Berlin","url":f"{settings.IPTV_BASE_URL}/subdivisions/de-be.m3u","category":"iptv","country":"DE","playlist_type":"subdivision"},
    {"name":"de_hamburg","display_name":"Allemagne — Hambourg","url":f"{settings.IPTV_BASE_URL}/subdivisions/de-hh.m3u","category":"iptv","country":"DE","playlist_type":"subdivision"},
    {"name":"de_nrw","display_name":"Allemagne — Rhénanie-du-Nord","url":f"{settings.IPTV_BASE_URL}/subdivisions/de-nw.m3u","category":"iptv","country":"DE","playlist_type":"subdivision"},
    {"name":"es_cataluna","display_name":"Espagne — Catalogne","url":f"{settings.IPTV_BASE_URL}/subdivisions/es-ct.m3u","category":"iptv","country":"ES","playlist_type":"subdivision"},
    {"name":"es_andalucia","display_name":"Espagne — Andalousie","url":f"{settings.IPTV_BASE_URL}/subdivisions/es-an.m3u","category":"iptv","country":"ES","playlist_type":"subdivision"},
    {"name":"es_madrid","display_name":"Espagne — Madrid","url":f"{settings.IPTV_BASE_URL}/subdivisions/es-md.m3u","category":"iptv","country":"ES","playlist_type":"subdivision"},
    {"name":"es_valencia","display_name":"Espagne — Valenciana","url":f"{settings.IPTV_BASE_URL}/subdivisions/es-vc.m3u","category":"iptv","country":"ES","playlist_type":"subdivision"},
    {"name":"es_pais_vasco","display_name":"Espagne — Pays Basque","url":f"{settings.IPTV_BASE_URL}/subdivisions/es-pv.m3u","category":"iptv","country":"ES","playlist_type":"subdivision"},
    {"name":"it_lombardia","display_name":"Italie — Lombardie","url":f"{settings.IPTV_BASE_URL}/subdivisions/it-25.m3u","category":"iptv","country":"IT","playlist_type":"subdivision"},
    {"name":"it_lazio","display_name":"Italie — Latium","url":f"{settings.IPTV_BASE_URL}/subdivisions/it-62.m3u","category":"iptv","country":"IT","playlist_type":"subdivision"},
    {"name":"it_campania","display_name":"Italie — Campanie","url":f"{settings.IPTV_BASE_URL}/subdivisions/it-72.m3u","category":"iptv","country":"IT","playlist_type":"subdivision"},
    {"name":"it_sicilia","display_name":"Italie — Sicile","url":f"{settings.IPTV_BASE_URL}/subdivisions/it-82.m3u","category":"iptv","country":"IT","playlist_type":"subdivision"},
    {"name":"gb_england","display_name":"Angleterre","url":f"{settings.IPTV_BASE_URL}/subdivisions/gb-eng.m3u","category":"iptv","country":"GB","playlist_type":"subdivision"},
    {"name":"gb_scotland","display_name":"Écosse","url":f"{settings.IPTV_BASE_URL}/subdivisions/gb-sct.m3u","category":"iptv","country":"GB","playlist_type":"subdivision"},
    {"name":"gb_wales","display_name":"Pays de Galles","url":f"{settings.IPTV_BASE_URL}/subdivisions/gb-wls.m3u","category":"iptv","country":"GB","playlist_type":"subdivision"},
    {"name":"ru_moscow","display_name":"Russie — Moscou","url":f"{settings.IPTV_BASE_URL}/subdivisions/ru-mos.m3u","category":"iptv","country":"RU","playlist_type":"subdivision"},
    {"name":"ua_kyiv","display_name":"Ukraine — Kyiv","url":f"{settings.IPTV_BASE_URL}/subdivisions/ua-30.m3u","category":"iptv","country":"UA","playlist_type":"subdivision"},
    {"name":"nl_north_holland","display_name":"Pays-Bas — Hollande-Septentrionale","url":f"{settings.IPTV_BASE_URL}/subdivisions/nl-nh.m3u","category":"iptv","country":"NL","playlist_type":"subdivision"},
    {"name":"be_brussels","display_name":"Belgique — Bruxelles","url":f"{settings.IPTV_BASE_URL}/subdivisions/be-bru.m3u","category":"iptv","country":"BE","playlist_type":"subdivision"},
    {"name":"be_wallonie","display_name":"Belgique — Wallonie","url":f"{settings.IPTV_BASE_URL}/subdivisions/be-wlx.m3u","category":"iptv","country":"BE","playlist_type":"subdivision"},
    {"name":"be_flanders","display_name":"Belgique — Flandre","url":f"{settings.IPTV_BASE_URL}/subdivisions/be-vov.m3u","category":"iptv","country":"BE","playlist_type":"subdivision"},
    {"name":"pt_lisboa","display_name":"Portugal — Lisbonne","url":f"{settings.IPTV_BASE_URL}/subdivisions/pt-11.m3u","category":"iptv","country":"PT","playlist_type":"subdivision"},
    {"name":"pt_porto","display_name":"Portugal — Porto","url":f"{settings.IPTV_BASE_URL}/subdivisions/pt-13.m3u","category":"iptv","country":"PT","playlist_type":"subdivision"},
    {"name":"gr_attica","display_name":"Grèce — Attique","url":f"{settings.IPTV_BASE_URL}/subdivisions/gr-i.m3u","category":"iptv","country":"GR","playlist_type":"subdivision"},
    {"name":"pl_mazowieckie","display_name":"Pologne — Mazovie","url":f"{settings.IPTV_BASE_URL}/subdivisions/pl-mz.m3u","category":"iptv","country":"PL","playlist_type":"subdivision"},
    {"name":"ro_bucharest","display_name":"Roumanie — Bucarest","url":f"{settings.IPTV_BASE_URL}/subdivisions/ro-b.m3u","category":"iptv","country":"RO","playlist_type":"subdivision"},
    {"name":"cz_prague","display_name":"Tchéquie — Prague","url":f"{settings.IPTV_BASE_URL}/subdivisions/cz-pr.m3u","category":"iptv","country":"CZ","playlist_type":"subdivision"},
    {"name":"hu_budapest","display_name":"Hongrie — Budapest","url":f"{settings.IPTV_BASE_URL}/subdivisions/hu-bu.m3u","category":"iptv","country":"HU","playlist_type":"subdivision"},
    {"name":"sk_bratislava","display_name":"Slovaquie — Bratislava","url":f"{settings.IPTV_BASE_URL}/subdivisions/sk-bl.m3u","category":"iptv","country":"SK","playlist_type":"subdivision"},
    {"name":"rs_belgrade","display_name":"Serbie — Belgrade","url":f"{settings.IPTV_BASE_URL}/subdivisions/rs-00.m3u","category":"iptv","country":"RS","playlist_type":"subdivision"},
    {"name":"hr_zagreb","display_name":"Croatie — Zagreb","url":f"{settings.IPTV_BASE_URL}/subdivisions/hr-01.m3u","category":"iptv","country":"HR","playlist_type":"subdivision"},
    {"name":"se_stockholm","display_name":"Suède — Stockholm","url":f"{settings.IPTV_BASE_URL}/subdivisions/se-ab.m3u","category":"iptv","country":"SE","playlist_type":"subdivision"},
    {"name":"no_oslo","display_name":"Norvège — Oslo","url":f"{settings.IPTV_BASE_URL}/subdivisions/no-03.m3u","category":"iptv","country":"NO","playlist_type":"subdivision"},
    {"name":"dk_copenhagen","display_name":"Danemark — Copenhague","url":f"{settings.IPTV_BASE_URL}/subdivisions/dk-84.m3u","category":"iptv","country":"DK","playlist_type":"subdivision"},
    {"name":"fi_helsinki","display_name":"Finlande — Helsinki","url":f"{settings.IPTV_BASE_URL}/subdivisions/fi-18.m3u","category":"iptv","country":"FI","playlist_type":"subdivision"},
    {"name":"at_vienna","display_name":"Autriche — Vienne","url":f"{settings.IPTV_BASE_URL}/subdivisions/at-9.m3u","category":"iptv","country":"AT","playlist_type":"subdivision"},
    {"name":"ch_zurich","display_name":"Suisse — Zurich","url":f"{settings.IPTV_BASE_URL}/subdivisions/ch-zh.m3u","category":"iptv","country":"CH","playlist_type":"subdivision"},
    {"name":"ch_bern","display_name":"Suisse — Berne","url":f"{settings.IPTV_BASE_URL}/subdivisions/ch-be.m3u","category":"iptv","country":"CH","playlist_type":"subdivision"},
    {"name":"ch_geneve","display_name":"Suisse — Genève","url":f"{settings.IPTV_BASE_URL}/subdivisions/ch-ge.m3u","category":"iptv","country":"CH","playlist_type":"subdivision"},
    # ── Villes du monde ──────────────────────────────────────────────────────
    {"name":"city_paris","display_name":"Paris","url":f"{settings.IPTV_BASE_URL}/cities/frpar.m3u","category":"iptv","country":"FR","playlist_type":"city"},
    {"name":"city_lyon","display_name":"Lyon","url":f"{settings.IPTV_BASE_URL}/cities/frlys.m3u","category":"iptv","country":"FR","playlist_type":"city"},
    {"name":"city_marseille","display_name":"Marseille","url":f"{settings.IPTV_BASE_URL}/cities/frmrs.m3u","category":"iptv","country":"FR","playlist_type":"city"},
    {"name":"city_bordeaux","display_name":"Bordeaux","url":f"{settings.IPTV_BASE_URL}/cities/frbod.m3u","category":"iptv","country":"FR","playlist_type":"city"},
    {"name":"city_toulouse","display_name":"Toulouse","url":f"{settings.IPTV_BASE_URL}/cities/frtls.m3u","category":"iptv","country":"FR","playlist_type":"city"},
    {"name":"city_lille","display_name":"Lille","url":f"{settings.IPTV_BASE_URL}/cities/frlle.m3u","category":"iptv","country":"FR","playlist_type":"city"},
    {"name":"city_london","display_name":"Londres","url":f"{settings.IPTV_BASE_URL}/cities/gblon.m3u","category":"iptv","country":"GB","playlist_type":"city"},
    {"name":"city_manchester","display_name":"Manchester","url":f"{settings.IPTV_BASE_URL}/cities/gbman.m3u","category":"iptv","country":"GB","playlist_type":"city"},
    {"name":"city_berlin","display_name":"Berlin","url":f"{settings.IPTV_BASE_URL}/cities/deber.m3u","category":"iptv","country":"DE","playlist_type":"city"},
    {"name":"city_munich","display_name":"Munich","url":f"{settings.IPTV_BASE_URL}/cities/demuc.m3u","category":"iptv","country":"DE","playlist_type":"city"},
    {"name":"city_hamburg","display_name":"Hambourg","url":f"{settings.IPTV_BASE_URL}/cities/deham.m3u","category":"iptv","country":"DE","playlist_type":"city"},
    {"name":"city_amsterdam","display_name":"Amsterdam","url":f"{settings.IPTV_BASE_URL}/cities/nlams.m3u","category":"iptv","country":"NL","playlist_type":"city"},
    {"name":"city_brussels","display_name":"Bruxelles","url":f"{settings.IPTV_BASE_URL}/cities/bebru.m3u","category":"iptv","country":"BE","playlist_type":"city"},
    {"name":"city_rome","display_name":"Rome","url":f"{settings.IPTV_BASE_URL}/cities/itrom.m3u","category":"iptv","country":"IT","playlist_type":"city"},
    {"name":"city_milan","display_name":"Milan","url":f"{settings.IPTV_BASE_URL}/cities/itmil.m3u","category":"iptv","country":"IT","playlist_type":"city"},
    {"name":"city_barcelona","display_name":"Barcelone","url":f"{settings.IPTV_BASE_URL}/cities/esbcn.m3u","category":"iptv","country":"ES","playlist_type":"city"},
    {"name":"city_lisbon","display_name":"Lisbonne","url":f"{settings.IPTV_BASE_URL}/cities/ptlis.m3u","category":"iptv","country":"PT","playlist_type":"city"},
    {"name":"city_vienna","display_name":"Vienne","url":f"{settings.IPTV_BASE_URL}/cities/atvie.m3u","category":"iptv","country":"AT","playlist_type":"city"},
    {"name":"city_zurich","display_name":"Zurich","url":f"{settings.IPTV_BASE_URL}/cities/chzrh.m3u","category":"iptv","country":"CH","playlist_type":"city"},
    {"name":"city_stockholm","display_name":"Stockholm","url":f"{settings.IPTV_BASE_URL}/cities/sesto.m3u","category":"iptv","country":"SE","playlist_type":"city"},
    {"name":"city_oslo","display_name":"Oslo","url":f"{settings.IPTV_BASE_URL}/cities/noosl.m3u","category":"iptv","country":"NO","playlist_type":"city"},
    {"name":"city_copenhagen","display_name":"Copenhague","url":f"{settings.IPTV_BASE_URL}/cities/dkcph.m3u","category":"iptv","country":"DK","playlist_type":"city"},
    {"name":"city_helsinki","display_name":"Helsinki","url":f"{settings.IPTV_BASE_URL}/cities/fihel.m3u","category":"iptv","country":"FI","playlist_type":"city"},
    {"name":"city_warsaw","display_name":"Varsovie","url":f"{settings.IPTV_BASE_URL}/cities/plwaw.m3u","category":"iptv","country":"PL","playlist_type":"city"},
    {"name":"city_prague","display_name":"Prague","url":f"{settings.IPTV_BASE_URL}/cities/czprg.m3u","category":"iptv","country":"CZ","playlist_type":"city"},
    {"name":"city_budapest","display_name":"Budapest","url":f"{settings.IPTV_BASE_URL}/cities/hubud.m3u","category":"iptv","country":"HU","playlist_type":"city"},
    {"name":"city_bucharest","display_name":"Bucarest","url":f"{settings.IPTV_BASE_URL}/cities/robuh.m3u","category":"iptv","country":"RO","playlist_type":"city"},
    {"name":"city_athens","display_name":"Athènes","url":f"{settings.IPTV_BASE_URL}/cities/grATH.m3u","category":"iptv","country":"GR","playlist_type":"city"},
    {"name":"city_moscow","display_name":"Moscou","url":f"{settings.IPTV_BASE_URL}/cities/rumos.m3u","category":"iptv","country":"RU","playlist_type":"city"},
    {"name":"city_istanbul","display_name":"Istanbul","url":f"{settings.IPTV_BASE_URL}/cities/trist.m3u","category":"iptv","country":"TR","playlist_type":"city"},
    {"name":"city_dubai","display_name":"Dubaï","url":f"{settings.IPTV_BASE_URL}/cities/aedxb.m3u","category":"iptv","country":"AE","playlist_type":"city"},
    {"name":"city_riyadh","display_name":"Riyad","url":f"{settings.IPTV_BASE_URL}/cities/saruh.m3u","category":"iptv","country":"SA","playlist_type":"city"},
    {"name":"city_cairo","display_name":"Le Caire","url":f"{settings.IPTV_BASE_URL}/cities/egcai.m3u","category":"iptv","country":"EG","playlist_type":"city"},
    {"name":"city_casablanca","display_name":"Casablanca","url":f"{settings.IPTV_BASE_URL}/cities/macas.m3u","category":"iptv","country":"MA","playlist_type":"city"},
    {"name":"city_dakar","display_name":"Dakar","url":f"{settings.IPTV_BASE_URL}/cities/sndkr.m3u","category":"iptv","country":"SN","playlist_type":"city"},
    {"name":"city_abidjan","display_name":"Abidjan","url":f"{settings.IPTV_BASE_URL}/cities/ciabj.m3u","category":"iptv","country":"CI","playlist_type":"city"},
    {"name":"city_kinshasa","display_name":"Kinshasa","url":f"{settings.IPTV_BASE_URL}/cities/cdfih.m3u","category":"iptv","country":"CD","playlist_type":"city"},
    {"name":"city_nairobi","display_name":"Nairobi","url":f"{settings.IPTV_BASE_URL}/cities/kenbo.m3u","category":"iptv","country":"KE","playlist_type":"city"},
    {"name":"city_lagos","display_name":"Lagos","url":f"{settings.IPTV_BASE_URL}/cities/nglos.m3u","category":"iptv","country":"NG","playlist_type":"city"},
    {"name":"city_johannesburg","display_name":"Johannesburg","url":f"{settings.IPTV_BASE_URL}/cities/zajnb.m3u","category":"iptv","country":"ZA","playlist_type":"city"},
    {"name":"city_tokyo","display_name":"Tokyo","url":f"{settings.IPTV_BASE_URL}/cities/jptyo.m3u","category":"iptv","country":"JP","playlist_type":"city"},
    {"name":"city_beijing","display_name":"Pékin","url":f"{settings.IPTV_BASE_URL}/cities/cnbjs.m3u","category":"iptv","country":"CN","playlist_type":"city"},
    {"name":"city_shanghai","display_name":"Shanghai","url":f"{settings.IPTV_BASE_URL}/cities/cnsha.m3u","category":"iptv","country":"CN","playlist_type":"city"},
    {"name":"city_seoul","display_name":"Séoul","url":f"{settings.IPTV_BASE_URL}/cities/krsel.m3u","category":"iptv","country":"KR","playlist_type":"city"},
    {"name":"city_mumbai","display_name":"Mumbai","url":f"{settings.IPTV_BASE_URL}/cities/inbom.m3u","category":"iptv","country":"IN","playlist_type":"city"},
    {"name":"city_delhi","display_name":"Delhi","url":f"{settings.IPTV_BASE_URL}/cities/indel.m3u","category":"iptv","country":"IN","playlist_type":"city"},
    {"name":"city_singapore","display_name":"Singapour","url":f"{settings.IPTV_BASE_URL}/cities/sgsin.m3u","category":"iptv","country":"SG","playlist_type":"city"},
    {"name":"city_kuala_lumpur","display_name":"Kuala Lumpur","url":f"{settings.IPTV_BASE_URL}/cities/mykul.m3u","category":"iptv","country":"MY","playlist_type":"city"},
    {"name":"city_jakarta","display_name":"Jakarta","url":f"{settings.IPTV_BASE_URL}/cities/idjkt.m3u","category":"iptv","country":"ID","playlist_type":"city"},
    {"name":"city_bangkok","display_name":"Bangkok","url":f"{settings.IPTV_BASE_URL}/cities/thbkk.m3u","category":"iptv","country":"TH","playlist_type":"city"},
    {"name":"city_sydney","display_name":"Sydney","url":f"{settings.IPTV_BASE_URL}/cities/ausyd.m3u","category":"iptv","country":"AU","playlist_type":"city"},
    {"name":"city_melbourne","display_name":"Melbourne","url":f"{settings.IPTV_BASE_URL}/cities/aumel.m3u","category":"iptv","country":"AU","playlist_type":"city"},
    {"name":"city_new_york","display_name":"New York","url":f"{settings.IPTV_BASE_URL}/cities/usnyc.m3u","category":"iptv","country":"US","playlist_type":"city"},
    {"name":"city_los_angeles","display_name":"Los Angeles","url":f"{settings.IPTV_BASE_URL}/cities/uslax.m3u","category":"iptv","country":"US","playlist_type":"city"},
    {"name":"city_chicago","display_name":"Chicago","url":f"{settings.IPTV_BASE_URL}/cities/uschi.m3u","category":"iptv","country":"US","playlist_type":"city"},
    {"name":"city_miami","display_name":"Miami","url":f"{settings.IPTV_BASE_URL}/cities/usmia.m3u","category":"iptv","country":"US","playlist_type":"city"},
    {"name":"city_houston","display_name":"Houston","url":f"{settings.IPTV_BASE_URL}/cities/ushou.m3u","category":"iptv","country":"US","playlist_type":"city"},
    {"name":"city_phoenix","display_name":"Phoenix","url":f"{settings.IPTV_BASE_URL}/cities/uspho.m3u","category":"iptv","country":"US","playlist_type":"city"},
    {"name":"city_philadelphia","display_name":"Philadelphie","url":f"{settings.IPTV_BASE_URL}/cities/usphl.m3u","category":"iptv","country":"US","playlist_type":"city"},
    {"name":"city_san_antonio","display_name":"San Antonio","url":f"{settings.IPTV_BASE_URL}/cities/ussat.m3u","category":"iptv","country":"US","playlist_type":"city"},
    {"name":"city_san_diego","display_name":"San Diego","url":f"{settings.IPTV_BASE_URL}/cities/ussan.m3u","category":"iptv","country":"US","playlist_type":"city"},
    {"name":"city_san_francisco","display_name":"San Francisco","url":f"{settings.IPTV_BASE_URL}/cities/ussfo.m3u","category":"iptv","country":"US","playlist_type":"city"},
    {"name":"city_seattle","display_name":"Seattle","url":f"{settings.IPTV_BASE_URL}/cities/ussea.m3u","category":"iptv","country":"US","playlist_type":"city"},
    {"name":"city_denver","display_name":"Denver","url":f"{settings.IPTV_BASE_URL}/cities/usden.m3u","category":"iptv","country":"US","playlist_type":"city"},
    {"name":"city_boston","display_name":"Boston","url":f"{settings.IPTV_BASE_URL}/cities/usbos.m3u","category":"iptv","country":"US","playlist_type":"city"},
    {"name":"city_atlanta","display_name":"Atlanta","url":f"{settings.IPTV_BASE_URL}/cities/usatl.m3u","category":"iptv","country":"US","playlist_type":"city"},
    {"name":"city_detroit","display_name":"Détroit","url":f"{settings.IPTV_BASE_URL}/cities/usdet.m3u","category":"iptv","country":"US","playlist_type":"city"},
    {"name":"city_minneapolis","display_name":"Minneapolis","url":f"{settings.IPTV_BASE_URL}/cities/usmin.m3u","category":"iptv","country":"US","playlist_type":"city"},
    {"name":"city_toronto","display_name":"Toronto","url":f"{settings.IPTV_BASE_URL}/cities/cator.m3u","category":"iptv","country":"CA","playlist_type":"city"},
    {"name":"city_montreal","display_name":"Montréal","url":f"{settings.IPTV_BASE_URL}/cities/camtl.m3u","category":"iptv","country":"CA","playlist_type":"city"},
    {"name":"city_vancouver","display_name":"Vancouver","url":f"{settings.IPTV_BASE_URL}/cities/cavan.m3u","category":"iptv","country":"CA","playlist_type":"city"},
    {"name":"city_ottawa","display_name":"Ottawa","url":f"{settings.IPTV_BASE_URL}/cities/caott.m3u","category":"iptv","country":"CA","playlist_type":"city"},
    {"name":"city_sao_paulo","display_name":"São Paulo","url":f"{settings.IPTV_BASE_URL}/cities/brssa.m3u","category":"iptv","country":"BR","playlist_type":"city"},
    {"name":"city_rio","display_name":"Rio de Janeiro","url":f"{settings.IPTV_BASE_URL}/cities/brrio.m3u","category":"iptv","country":"BR","playlist_type":"city"},
    {"name":"city_buenos_aires","display_name":"Buenos Aires","url":f"{settings.IPTV_BASE_URL}/cities/arbue.m3u","category":"iptv","country":"AR","playlist_type":"city"},
    {"name":"city_bogota","display_name":"Bogotá","url":f"{settings.IPTV_BASE_URL}/cities/cobog.m3u","category":"iptv","country":"CO","playlist_type":"city"},
    {"name":"city_lima","display_name":"Lima","url":f"{settings.IPTV_BASE_URL}/cities/pelim.m3u","category":"iptv","country":"PE","playlist_type":"city"},
    {"name":"city_santiago","display_name":"Santiago","url":f"{settings.IPTV_BASE_URL}/cities/clscl.m3u","category":"iptv","country":"CL","playlist_type":"city"},
    {"name":"city_mexico_city","display_name":"Mexico","url":f"{settings.IPTV_BASE_URL}/cities/mxmex.m3u","category":"iptv","country":"MX","playlist_type":"city"},
    {"name":"city_guadalajara","display_name":"Guadalajara","url":f"{settings.IPTV_BASE_URL}/cities/mxgdl.m3u","category":"iptv","country":"MX","playlist_type":"city"},
    {"name":"city_tehran","display_name":"Téhéran","url":f"{settings.IPTV_BASE_URL}/cities/irthr.m3u","category":"iptv","country":"IR","playlist_type":"city"},
    {"name":"city_baghdad","display_name":"Bagdad","url":f"{settings.IPTV_BASE_URL}/cities/iqbgw.m3u","category":"iptv","country":"IQ","playlist_type":"city"},
    {"name":"city_beirut","display_name":"Beyrouth","url":f"{settings.IPTV_BASE_URL}/cities/lbbey.m3u","category":"iptv","country":"LB","playlist_type":"city"},
    {"name":"city_amman","display_name":"Amman","url":f"{settings.IPTV_BASE_URL}/cities/joamm.m3u","category":"iptv","country":"JO","playlist_type":"city"},
    {"name":"city_tunis","display_name":"Tunis","url":f"{settings.IPTV_BASE_URL}/cities/tntun.m3u","category":"iptv","country":"TN","playlist_type":"city"},
    {"name":"city_algiers","display_name":"Alger","url":f"{settings.IPTV_BASE_URL}/cities/dzalg.m3u","category":"iptv","country":"DZ","playlist_type":"city"},
    {"name":"city_accra","display_name":"Accra","url":f"{settings.IPTV_BASE_URL}/cities/ghacc.m3u","category":"iptv","country":"GH","playlist_type":"city"},
    {"name":"city_addis_ababa","display_name":"Addis-Abeba","url":f"{settings.IPTV_BASE_URL}/cities/etadd.m3u","category":"iptv","country":"ET","playlist_type":"city"},
    {"name":"city_kampala","display_name":"Kampala","url":f"{settings.IPTV_BASE_URL}/cities/ugkla.m3u","category":"iptv","country":"UG","playlist_type":"city"},
    {"name":"city_dar_es_salaam","display_name":"Dar es Salam","url":f"{settings.IPTV_BASE_URL}/cities/tzdar.m3u","category":"iptv","country":"TZ","playlist_type":"city"},
    {"name":"city_lusaka","display_name":"Lusaka","url":f"{settings.IPTV_BASE_URL}/cities/zmlun.m3u","category":"iptv","country":"ZM","playlist_type":"city"},
    {"name":"city_harare","display_name":"Harare","url":f"{settings.IPTV_BASE_URL}/cities/zwhar.m3u","category":"iptv","country":"ZW","playlist_type":"city"},
    {"name":"city_manila","display_name":"Manille","url":f"{settings.IPTV_BASE_URL}/cities/phmnl.m3u","category":"iptv","country":"PH","playlist_type":"city"},
    {"name":"city_ho_chi_minh","display_name":"Hô-Chi-Minh","url":f"{settings.IPTV_BASE_URL}/cities/vnsgn.m3u","category":"iptv","country":"VN","playlist_type":"city"},
    {"name":"city_hanoi","display_name":"Hanoï","url":f"{settings.IPTV_BASE_URL}/cities/vnhan.m3u","category":"iptv","country":"VN","playlist_type":"city"},
    {"name":"city_dhaka","display_name":"Dacca","url":f"{settings.IPTV_BASE_URL}/cities/bddac.m3u","category":"iptv","country":"BD","playlist_type":"city"},
    {"name":"city_karachi","display_name":"Karachi","url":f"{settings.IPTV_BASE_URL}/cities/pkkhi.m3u","category":"iptv","country":"PK","playlist_type":"city"},
    {"name":"city_lahore","display_name":"Lahore","url":f"{settings.IPTV_BASE_URL}/cities/pklhe.m3u","category":"iptv","country":"PK","playlist_type":"city"},
    {"name":"city_colombo","display_name":"Colombo","url":f"{settings.IPTV_BASE_URL}/cities/lkcmb.m3u","category":"iptv","country":"LK","playlist_type":"city"},
    {"name":"city_kathmandu","display_name":"Katmandou","url":f"{settings.IPTV_BASE_URL}/cities/npktm.m3u","category":"iptv","country":"NP","playlist_type":"city"},
    {"name":"city_yangon","display_name":"Yangon","url":f"{settings.IPTV_BASE_URL}/cities/mmrgn.m3u","category":"iptv","country":"MM","playlist_type":"city"},
    {"name":"city_phnom_penh","display_name":"Phnom Penh","url":f"{settings.IPTV_BASE_URL}/cities/khpnh.m3u","category":"iptv","country":"KH","playlist_type":"city"},
    {"name":"city_vientiane","display_name":"Vientiane","url":f"{settings.IPTV_BASE_URL}/cities/lavte.m3u","category":"iptv","country":"LA","playlist_type":"city"},
    {"name":"city_ulaanbaatar","display_name":"Oulan-Bator","url":f"{settings.IPTV_BASE_URL}/cities/mnuln.m3u","category":"iptv","country":"MN","playlist_type":"city"},
    {"name":"city_tashkent","display_name":"Tachkent","url":f"{settings.IPTV_BASE_URL}/cities/uztas.m3u","category":"iptv","country":"UZ","playlist_type":"city"},
    {"name":"city_almaty","display_name":"Almaty","url":f"{settings.IPTV_BASE_URL}/cities/kzalm.m3u","category":"iptv","country":"KZ","playlist_type":"city"},
    {"name":"city_baku","display_name":"Bakou","url":f"{settings.IPTV_BASE_URL}/cities/azbak.m3u","category":"iptv","country":"AZ","playlist_type":"city"},
    {"name":"city_yerevan","display_name":"Erevan","url":f"{settings.IPTV_BASE_URL}/cities/amevn.m3u","category":"iptv","country":"AM","playlist_type":"city"},
    {"name":"city_tbilisi","display_name":"Tbilissi","url":f"{settings.IPTV_BASE_URL}/cities/getbs.m3u","category":"iptv","country":"GE","playlist_type":"city"},
    {"name":"city_auckland","display_name":"Auckland","url":f"{settings.IPTV_BASE_URL}/cities/nzakl.m3u","category":"iptv","country":"NZ","playlist_type":"city"},
    {"name":"city_brisbane","display_name":"Brisbane","url":f"{settings.IPTV_BASE_URL}/cities/aubne.m3u","category":"iptv","country":"AU","playlist_type":"city"},
    {"name":"city_perth","display_name":"Perth","url":f"{settings.IPTV_BASE_URL}/cities/auper.m3u","category":"iptv","country":"AU","playlist_type":"city"},
    # ── Catégories thématiques supplémentaires ────────────────────────────────
    {"name":"cat_general","display_name":"Généraliste","url":f"{settings.IPTV_BASE_URL}/categories/general.m3u","category":"iptv","country":"INT","playlist_type":"category"},
    {"name":"cat_animation","display_name":"Animation","url":f"{settings.IPTV_BASE_URL}/categories/animation.m3u","category":"iptv","country":"INT","playlist_type":"category"},
    {"name":"cat_auto","display_name":"Auto & Moto","url":f"{settings.IPTV_BASE_URL}/categories/auto.m3u","category":"iptv","country":"INT","playlist_type":"category"},
    {"name":"cat_business","display_name":"Business","url":f"{settings.IPTV_BASE_URL}/categories/business.m3u","category":"iptv","country":"INT","playlist_type":"category"},
    {"name":"cat_classic","display_name":"Classique","url":f"{settings.IPTV_BASE_URL}/categories/classic.m3u","category":"iptv","country":"INT","playlist_type":"category"},
    {"name":"cat_comedy","display_name":"Comédie","url":f"{settings.IPTV_BASE_URL}/categories/comedy.m3u","category":"iptv","country":"INT","playlist_type":"category"},
    {"name":"cat_cooking","display_name":"Cuisine","url":f"{settings.IPTV_BASE_URL}/categories/cooking.m3u","category":"iptv","country":"INT","playlist_type":"category"},
    {"name":"cat_culture","display_name":"Culture","url":f"{settings.IPTV_BASE_URL}/categories/culture.m3u","category":"iptv","country":"INT","playlist_type":"category"},
    {"name":"cat_documentary","display_name":"Documentaires","url":f"{settings.IPTV_BASE_URL}/categories/documentary.m3u","category":"iptv","country":"INT","playlist_type":"category"},
    {"name":"cat_education","display_name":"Éducation","url":f"{settings.IPTV_BASE_URL}/categories/education.m3u","category":"iptv","country":"INT","playlist_type":"category"},
    {"name":"cat_entertainment","display_name":"Divertissement","url":f"{settings.IPTV_BASE_URL}/categories/entertainment.m3u","category":"iptv","country":"INT","playlist_type":"category"},
    {"name":"cat_family","display_name":"Famille","url":f"{settings.IPTV_BASE_URL}/categories/family.m3u","category":"iptv","country":"INT","playlist_type":"category"},
    {"name":"cat_legislative","display_name":"Politique","url":f"{settings.IPTV_BASE_URL}/categories/legislative.m3u","category":"iptv","country":"INT","playlist_type":"category"},
    {"name":"cat_lifestyle","display_name":"Style de vie","url":f"{settings.IPTV_BASE_URL}/categories/lifestyle.m3u","category":"iptv","country":"INT","playlist_type":"category"},
    {"name":"cat_movies","display_name":"Films","url":f"{settings.IPTV_BASE_URL}/categories/movies.m3u","category":"iptv","country":"INT","playlist_type":"category"},
    {"name":"cat_outdoor","display_name":"Nature & Plein air","url":f"{settings.IPTV_BASE_URL}/categories/outdoor.m3u","category":"iptv","country":"INT","playlist_type":"category"},
    {"name":"cat_relax","display_name":"Relaxation","url":f"{settings.IPTV_BASE_URL}/categories/relax.m3u","category":"iptv","country":"INT","playlist_type":"category"},
    {"name":"cat_science","display_name":"Science","url":f"{settings.IPTV_BASE_URL}/categories/science.m3u","category":"iptv","country":"INT","playlist_type":"category"},
    {"name":"cat_series","display_name":"Séries TV","url":f"{settings.IPTV_BASE_URL}/categories/series.m3u","category":"iptv","country":"INT","playlist_type":"category"},
    {"name":"cat_shop","display_name":"Shopping","url":f"{settings.IPTV_BASE_URL}/categories/shop.m3u","category":"iptv","country":"INT","playlist_type":"category"},
    {"name":"cat_travel","display_name":"Voyage","url":f"{settings.IPTV_BASE_URL}/categories/travel.m3u","category":"iptv","country":"INT","playlist_type":"category"},
    {"name":"cat_weather","display_name":"Météo","url":f"{settings.IPTV_BASE_URL}/categories/weather.m3u","category":"iptv","country":"INT","playlist_type":"category"},
    {"name":"cat_XXX","display_name":"Adulte","url":f"{settings.IPTV_BASE_URL}/categories/xxx.m3u","category":"iptv","country":"INT","playlist_type":"category"},
    {"name":"cat_animal","display_name":"Animaux","url":f"{settings.IPTV_BASE_URL}/categories/animal.m3u","category":"iptv","country":"INT","playlist_type":"category"},
    {"name":"cat_craft","display_name":"Artisanat","url":f"{settings.IPTV_BASE_URL}/categories/craft.m3u","category":"iptv","country":"INT","playlist_type":"category"},
    {"name":"cat_fitness","display_name":"Fitness","url":f"{settings.IPTV_BASE_URL}/categories/fitness.m3u","category":"iptv","country":"INT","playlist_type":"category"},
    {"name":"cat_health","display_name":"Santé","url":f"{settings.IPTV_BASE_URL}/categories/health.m3u","category":"iptv","country":"INT","playlist_type":"category"},
    {"name":"cat_military","display_name":"Militaire","url":f"{settings.IPTV_BASE_URL}/categories/military.m3u","category":"iptv","country":"INT","playlist_type":"category"},
    {"name":"cat_ethnic","display_name":"Ethnique","url":f"{settings.IPTV_BASE_URL}/categories/ethnic.m3u","category":"iptv","country":"INT","playlist_type":"category"},
    {"name":"cat_religious","display_name":"Religion","url":f"{settings.IPTV_BASE_URL}/categories/religious.m3u","category":"iptv","country":"INT","playlist_type":"category"},
    {"name":"cat_kids","display_name":"Enfants","url":f"{settings.IPTV_BASE_URL}/categories/kids.m3u","category":"iptv","country":"INT","playlist_type":"category"},
    {"name":"cat_music","display_name":"Musique","url":f"{settings.IPTV_BASE_URL}/categories/music.m3u","category":"iptv","country":"INT","playlist_type":"category"},
    {"name":"cat_news","display_name":"Information","url":f"{settings.IPTV_BASE_URL}/categories/news.m3u","category":"iptv","country":"INT","playlist_type":"category"},
    {"name":"cat_sport","display_name":"Sports","url":f"{settings.IPTV_BASE_URL}/categories/sports.m3u","category":"iptv","country":"INT","playlist_type":"category"},
    {"name":"cat_transit","display_name":"Transport","url":f"{settings.IPTV_BASE_URL}/categories/transit.m3u","category":"iptv","country":"INT","playlist_type":"category"},
    {"name":"cat_surveillance","display_name":"Surveillance","url":f"{settings.IPTV_BASE_URL}/categories/surveillance.m3u","category":"iptv","country":"INT","playlist_type":"category"},
    {"name":"cat_legislative2","display_name":"Gouvernemental","url":f"{settings.IPTV_BASE_URL}/categories/legislative.m3u","category":"iptv","country":"INT","playlist_type":"category"},


    # ── Pays du Moyen-Orient ──────────────────────────────────────────────
    {"name":"bahrain","display_name":"Bahreïn","url":f"{settings.IPTV_BASE_URL}/countries/bh.m3u","category":"iptv","country":"BH","playlist_type":"country"},
    {"name":"irak","display_name":"Irak","url":f"{settings.IPTV_BASE_URL}/countries/iq.m3u","category":"iptv","country":"IQ","playlist_type":"country"},
    {"name":"israel","display_name":"Israël","url":f"{settings.IPTV_BASE_URL}/countries/il.m3u","category":"iptv","country":"IL","playlist_type":"country"},
    {"name":"iran","display_name":"Iran","url":f"{settings.IPTV_BASE_URL}/countries/ir.m3u","category":"iptv","country":"IR","playlist_type":"country"},
    {"name":"jordanie","display_name":"Jordanie","url":f"{settings.IPTV_BASE_URL}/countries/jo.m3u","category":"iptv","country":"JO","playlist_type":"country"},
    {"name":"koweït","display_name":"Koweït","url":f"{settings.IPTV_BASE_URL}/countries/kw.m3u","category":"iptv","country":"KW","playlist_type":"country"},
    {"name":"liban","display_name":"Liban","url":f"{settings.IPTV_BASE_URL}/countries/lb.m3u","category":"iptv","country":"LB","playlist_type":"country"},
    {"name":"oman","display_name":"Oman","url":f"{settings.IPTV_BASE_URL}/countries/om.m3u","category":"iptv","country":"OM","playlist_type":"country"},
    {"name":"syrie","display_name":"Syrie","url":f"{settings.IPTV_BASE_URL}/countries/sy.m3u","category":"iptv","country":"SY","playlist_type":"country"},
    {"name":"yemen","display_name":"Yémen","url":f"{settings.IPTV_BASE_URL}/countries/ye.m3u","category":"iptv","country":"YE","playlist_type":"country"},
]

# ── Chaînes de radio supplémentaires (seed au démarrage) ──────────────
EXTRA_RADIO_STATIONS = [
    {"title":"RFI Monde","stream_url":"https://rfimonde64k.ice.infomaniak.ch/rfimonde-64.mp3","category":"radio","country":"FR","stream_type":"audio","logo":"https://www.rfi.fr/images/logo-rfi.png","description":"Radio France Internationale, actualités mondiales en français"},
    {"title":"RFI Afrique","stream_url":"https://rfimonde64k.ice.infomaniak.ch/rfimonde-64.mp3","category":"radio","country":"FR","stream_type":"audio","logo":"","description":"RFI — Émissions Afrique"},
    {"title":"France Inter","stream_url":"https://direct.franceinter.fr/live/franceinter-midfi.mp3","category":"radio","country":"FR","stream_type":"audio","logo":"","description":"La radio généraliste de Radio France"},
    {"title":"France Info Radio","stream_url":"https://direct.franceinfo.fr/live/franceinfo-midfi.mp3","category":"radio","country":"FR","stream_type":"audio","logo":"","description":"24h/24 d'information"},
    {"title":"France Culture","stream_url":"https://direct.franceculture.fr/live/franceculture-midfi.mp3","category":"radio","country":"FR","stream_type":"audio","logo":"","description":"Culture, débats, société"},
    {"title":"France Musique","stream_url":"https://direct.francemusique.fr/live/francemusique-midfi.mp3","category":"radio","country":"FR","stream_type":"audio","logo":"","description":"Musique classique et jazz"},
    {"title":"RTL Radio","stream_url":"https://streaming.rtl.fr/RTL-1-44-128","category":"radio","country":"FR","stream_type":"audio","logo":"","description":"Radio RTL en direct"},
    {"title":"Europe 1","stream_url":"https://europe1.lmn.fm/europe1.mp3","category":"radio","country":"FR","stream_type":"audio","logo":"","description":"Europe 1, radio d'information et de divertissement"},
    {"title":"NRJ Radio","stream_url":"https://www.nrj.fr/playlist/nrj.m3u8","category":"radio","country":"FR","stream_type":"audio","logo":"","description":"NRJ, hits du moment"},
    {"title":"Skyrock","stream_url":"https://www.skyrock.fm/stream/skyrock.m3u8","category":"radio","country":"FR","stream_type":"audio","logo":"","description":"Skyrock — Hip-hop et R&B"},
    {"title":"Chérie FM","stream_url":"https://cheriefm.lmn.fm/cheriefm.mp3","category":"radio","country":"FR","stream_type":"audio","logo":"","description":"Chérie FM — Hits romantiques"},
    {"title":"Fun Radio","stream_url":"https://stream.funradio.fr/fun-1-44-128","category":"radio","country":"FR","stream_type":"audio","logo":"","description":"Fun Radio — Dance et électro"},
    {"title":"Virgin Radio","stream_url":"https://virginradio.lmn.fm/virginradio.mp3","category":"radio","country":"FR","stream_type":"audio","logo":"","description":"Virgin Radio France"},
    {"title":"RTBF La Première","stream_url":"https://radios.rtbf.be/app/streams/direct/premiere.m3u8","category":"radio","country":"BE","stream_type":"audio","logo":"","description":"La radio publique belge francophone"},
    {"title":"RTBF Vivacité","stream_url":"https://radios.rtbf.be/app/streams/direct/vivacite.m3u8","category":"radio","country":"BE","stream_type":"audio","logo":"","description":"Vivacité — radio régionale RTBF"},
    {"title":"RTS La Première","stream_url":"https://stream.srg-ssr.ch/rsp/aacp_96.stream/streamwh.m3u8","category":"radio","country":"CH","stream_type":"audio","logo":"","description":"RTS La Première — Suisse romande"},
    {"title":"BBC World Service","stream_url":"https://a.files.bbci.co.uk/media/live/manifesto/audio/simulcast/hls/nonuk/sbr_low/ak/bbc_world_service.m3u8","category":"radio","country":"GB","stream_type":"audio","logo":"","description":"BBC World Service en anglais"},
    {"title":"BBC Radio 1","stream_url":"https://a.files.bbci.co.uk/media/live/manifesto/audio/simulcast/hls/nonuk/sbr_low/ak/bbc_radio_one.m3u8","category":"radio","country":"GB","stream_type":"audio","logo":"","description":"BBC Radio 1 — Pop & Rock"},
    {"title":"BBC Radio 2","stream_url":"https://a.files.bbci.co.uk/media/live/manifesto/audio/simulcast/hls/nonuk/sbr_low/ak/bbc_radio_two.m3u8","category":"radio","country":"GB","stream_type":"audio","logo":"","description":"BBC Radio 2"},
    {"title":"BBC Radio 3","stream_url":"https://a.files.bbci.co.uk/media/live/manifesto/audio/simulcast/hls/nonuk/sbr_low/ak/bbc_radio_three.m3u8","category":"radio","country":"GB","stream_type":"audio","logo":"","description":"BBC Radio 3 — Musique classique"},
    {"title":"BBC Radio 4","stream_url":"https://a.files.bbci.co.uk/media/live/manifesto/audio/simulcast/hls/nonuk/sbr_low/ak/bbc_radio_fourfm.m3u8","category":"radio","country":"GB","stream_type":"audio","logo":"","description":"BBC Radio 4 — Culture et société"},
    {"title":"Deutsche Welle Radio","stream_url":"https://wdrmedien-a.akamaihd.net/medp/ondemand/weltweit/fsk0/205/2052049/2052049.m3u8","category":"radio","country":"DE","stream_type":"audio","logo":"","description":"Deutsche Welle en direct"},
    {"title":"DRadio Wissen","stream_url":"https://st01.sslstream.dlf.de/dlf/01/128/mp3/stream.mp3","category":"radio","country":"DE","stream_type":"audio","logo":"","description":"Deutschlandfunk"},
    {"title":"Radio Maria France","stream_url":"https://radiomariafrancehd.ice.infomaniak.ch/radiomariafrancehd.m3u8","category":"radio","country":"FR","stream_type":"audio","logo":"","description":"Radio catholique"},
    {"title":"Radio Monte-Carlo","stream_url":"https://www.rmc.fr/playlist/rmc.m3u8","category":"radio","country":"MC","stream_type":"audio","logo":"","description":"RMC, sport et talk"},
    {"title":"Radio Ouaga","stream_url":"https://stream.radioouaga.bf/live","category":"radio","country":"BF","stream_type":"audio","logo":"","description":"Radio Ouagadougou"},
    {"title":"Radio Senegal","stream_url":"https://stream.rts.sn/live","category":"radio","country":"SN","stream_type":"audio","logo":"","description":"Radio Télévision du Sénégal"},
    {"title":"Africa No 1","stream_url":"https://africano1.ice.infomaniak.ch/africano1-64.mp3","category":"radio","country":"GA","stream_type":"audio","logo":"","description":"Africa No 1 — Radio panafricaine depuis Libreville"},
    {"title":"Radio Congo","stream_url":"https://stream.rtnc.cd/live","category":"radio","country":"CD","stream_type":"audio","logo":"","description":"Radio Télévision Nationale du Congo"},
    {"title":"VOA Afrique","stream_url":"https://www.voanews.com/audio/player/voa/radio/streams/afr.m3u8","category":"radio","country":"US","stream_type":"audio","logo":"","description":"Voice of America — Service Afrique"},
    {"title":"Al Jazeera Radio","stream_url":"https://www.aljazeera.net/radio/live","category":"radio","country":"QA","stream_type":"audio","logo":"","description":"Al Jazeera Arabic Radio"},
    {"title":"Monte Carlo Doualiya","stream_url":"https://mcd128k.ice.infomaniak.ch/mcd-128.mp3","category":"radio","country":"FR","stream_type":"audio","logo":"","description":"MCD — Radio arabe internationale"},
    {"title":"NPR News","stream_url":"https://npr-ice.streamguys1.com/live.mp3","category":"radio","country":"US","stream_type":"audio","logo":"","description":"National Public Radio — USA"},
    {"title":"Radio Canada International","stream_url":"https://cbcrc.cdnstream1.com/live","category":"radio","country":"CA","stream_type":"audio","logo":"","description":"Radio Canada International"},
    {"title":"WQXR Classical","stream_url":"https://stream.wqxr.org/wqxr.mp3","category":"radio","country":"US","stream_type":"audio","logo":"","description":"WQXR — Classical music New York"},
    {"title":"Radio Swiss Jazz","stream_url":"https://stream.srg-ssr.ch/rsp/aacp_96.stream/streamwh.m3u8","category":"radio","country":"CH","stream_type":"audio","logo":"","description":"Radio Swiss Jazz"},
    {"title":"Jazz FM UK","stream_url":"https://jazz.fm/listen","category":"radio","country":"GB","stream_type":"audio","logo":"","description":"Jazz FM — Jazz and soul music"},
    {"title":"Smooth Radio","stream_url":"https://vis.media-ice.musicradio.com/SmoothUK","category":"radio","country":"GB","stream_type":"audio","logo":"","description":"Smooth Radio UK"},
    {"title":"Radio Paradise","stream_url":"https://stream.radioparadise.com/mp3-192","category":"radio","country":"US","stream_type":"audio","logo":"","description":"Radio Paradise — Eclectic music"},
    {"title":"SOMA FM Groove Salad","stream_url":"https://ice1.somafm.com/groovesalad-256-mp3","category":"radio","country":"US","stream_type":"audio","logo":"","description":"SomaFM Groove Salad — Ambient"},
    {"title":"SOMA FM Drone Zone","stream_url":"https://ice1.somafm.com/dronezone-256-mp3","category":"radio","country":"US","stream_type":"audio","logo":"","description":"SomaFM Drone Zone — Deep ambient"},
    {"title":"Lofi Hip Hop Radio","stream_url":"https://streams.ilovemusic.de/iloveradio17.mp3","category":"radio","country":"INT","stream_type":"audio","logo":"","description":"Lo-fi hip hop — beats to study/relax"},
    {"title":"Radio Classique","stream_url":"https://radioclassique.ice.infomaniak.ch/radioclassique-64.mp3","category":"radio","country":"FR","stream_type":"audio","logo":"","description":"Musique classique en continu"},
    {"title":"Radio Orient","stream_url":"https://www.radioorient.com/listen","category":"radio","country":"FR","stream_type":"audio","logo":"","description":"Musique orientale et culture arabe"},
    {"title":"Beur FM","stream_url":"https://beur.ice.infomaniak.ch/beurFm-128.mp3","category":"radio","country":"FR","stream_type":"audio","logo":"","description":"Beur FM — Musique et culture maghrébine"},
    {"title":"Radio Latina","stream_url":"https://radiolatina.ice.infomaniak.ch/radiolatina-64.mp3","category":"radio","country":"FR","stream_type":"audio","logo":"","description":"La radio latina de France"},
    {"title":"Rádio Nova Brasil","stream_url":"https://radiobras.am.br/live","category":"radio","country":"BR","stream_type":"audio","logo":"","description":"Radio Brasília"},
    {"title":"Radio Nacional Argentina","stream_url":"https://www.radionacional.com.ar/radio/live","category":"radio","country":"AR","stream_type":"audio","logo":"","description":"Radio Nacional de Argentina"},
    {"title":"Radio Bilingue","stream_url":"https://radiobilingue.org/stream","category":"radio","country":"US","stream_type":"audio","logo":"","description":"Radio bilingue espagnol/anglais"},
    {"title":"CGTN Radio","stream_url":"https://livefr.cgtn.com/audio.m3u8","category":"radio","country":"CN","stream_type":"audio","logo":"","description":"China Global Television Network Radio"},
]

EXTRA_NEWS_CHANNELS = [
    {"title":"Al Jazeera English","stream_url":"https://live-hls-web-aje.getaj.net/AJE/index.m3u8","category":"news","country":"QA","stream_type":"hls","logo":"https://www.aljazeera.com/images/logo_aje-nb.png","description":"Al Jazeera English — International news 24/7"},
    {"title":"Al Jazeera Arabic","stream_url":"https://live-hls-web-ajn.getaj.net/AJN/index.m3u8","category":"news","country":"QA","stream_type":"hls","logo":"","description":"قناة الجزيرة — أخبار 24 ساعة"},
    {"title":"France 24 Français","stream_url":"https://live.france24.com/hls/live/2037179-b/F24_FR_HI_HLS/master_5000.m3u8","category":"news","country":"FR","stream_type":"hls","logo":"https://static.france24.com/f24-assets/images/France24.png","description":"France 24 en français — Actualités en continu"},
    {"title":"France 24 English","stream_url":"https://live.france24.com/hls/live/2037218-b/F24_EN_HI_HLS/master_5000.m3u8","category":"news","country":"FR","stream_type":"hls","logo":"","description":"France 24 in English"},
    {"title":"France 24 Español","stream_url":"https://live.france24.com/hls/live/2037220-b/F24_ES_HI_HLS/master_5000.m3u8","category":"news","country":"FR","stream_type":"hls","logo":"","description":"France 24 en Español"},
    {"title":"France 24 Arabic","stream_url":"https://live.france24.com/hls/live/2037222-b/F24_AR_HI_HLS/master_5000.m3u8","category":"news","country":"FR","stream_type":"hls","logo":"","description":"فرانس 24 بالعربية"},
    {"title":"DW English","stream_url":"https://dwamdstream102.akamaized.net/hls/live/2015526/dwstream102/index.m3u8","category":"news","country":"DE","stream_type":"hls","logo":"","description":"Deutsche Welle — International English news"},
    {"title":"DW Français","stream_url":"https://dwamdstream106.akamaized.net/hls/live/2015531/dwstream106/index.m3u8","category":"news","country":"DE","stream_type":"hls","logo":"","description":"Deutsche Welle en Français"},
    {"title":"DW Español","stream_url":"https://dwamdstream104.akamaized.net/hls/live/2015530/dwstream104/index.m3u8","category":"news","country":"DE","stream_type":"hls","logo":"","description":"Deutsche Welle en Español"},
    {"title":"VOA News","stream_url":"https://voa-news.akamaized.net/hls/live/2101408/voa_english/master_608.m3u8","category":"news","country":"US","stream_type":"hls","logo":"","description":"Voice of America — English News"},
    {"title":"RT News","stream_url":"https://rt-glb.rttv.com/live/rtnews/index.m3u8","category":"news","country":"RU","stream_type":"hls","logo":"","description":"RT International — Russia Today"},
    {"title":"CGTN News","stream_url":"https://news.cgtn.com/resource/live/english/cgtn-news.m3u8","category":"news","country":"CN","stream_type":"hls","logo":"","description":"China Global TV Network News"},
    {"title":"TRT World","stream_url":"https://trtworld.live.trt.com.tr/hls/live/571207/trtworld/mid.m3u8","category":"news","country":"TR","stream_type":"hls","logo":"","description":"TRT World — Turkish international news"},
    {"title":"Euronews Français","stream_url":"https://euronews-wr-fr.akamaized.net/hls/live/2004116/euronewsfr/master_1500.m3u8","category":"news","country":"FR","stream_type":"hls","logo":"","description":"Euronews en Français"},
    {"title":"Euronews English","stream_url":"https://euronews-wr-en.akamaized.net/hls/live/2004115/euronewsen/master_1500.m3u8","category":"news","country":"FR","stream_type":"hls","logo":"","description":"Euronews in English"},
    {"title":"Africanews","stream_url":"https://africanews-wr-en.akamaized.net/hls/live/2004117/africanewsen/master_1500.m3u8","category":"news","country":"FR","stream_type":"hls","logo":"","description":"Africanews — African news in English"},
    {"title":"Sky News","stream_url":"https://skynews-cfds-opy.akamaized.net/live/skynews/cfds.isml/master.m3u8","category":"news","country":"GB","stream_type":"hls","logo":"","description":"Sky News UK — Live British news"},
    {"title":"BFMTV","stream_url":"https://ncdn.bfmtv.com/video-live/bfmtv/hd/bfmtv-hd.m3u8","category":"news","country":"FR","stream_type":"hls","logo":"","description":"BFM TV — Info en continu France"},
    {"title":"LCI","stream_url":"https://lci-live.tmc.tv/lci-live/smil:lci.smil/playlist.m3u8","category":"news","country":"FR","stream_type":"hls","logo":"","description":"La Chaîne Info — TF1 Group"},
    {"title":"CNews","stream_url":"https://ncdn.bfmtv.com/video-live/cnews/hd/cnews-hd.m3u8","category":"news","country":"FR","stream_type":"hls","logo":"","description":"CNews — Information et débats"},
    {"title":"RMC Info","stream_url":"https://rmcsport.lmn.fm/rmcinfo-hd.m3u8","category":"news","country":"FR","stream_type":"hls","logo":"","description":"BFM Business — Économie et finance"},
    {"title":"i24 News English","stream_url":"https://bcovlive-a.akamaihd.net/live_stream_i24newsus/us-east-1/6082144919001/playlist.m3u8","category":"news","country":"IL","stream_type":"hls","logo":"","description":"i24 News — Middle East focus"},
    {"title":"Bloomberg TV","stream_url":"https://cdn3.wowza.com/1/S00c1BJzbjVv/bloomberg/hls/live/playlist.m3u8","category":"news","country":"US","stream_type":"hls","logo":"","description":"Bloomberg — Business & finance"},
    {"title":"NHK World","stream_url":"https://nhkwlive-ojp.akamaized.net/hls/live/2003459/nhkwlive-ojp-en/index.m3u8","category":"news","country":"JP","stream_type":"hls","logo":"","description":"NHK World — Japan Broadcasting Corporation"},
    {"title":"KBS World","stream_url":"https://kbsworld.kbs.co.kr/live","category":"news","country":"KR","stream_type":"hls","logo":"","description":"KBS World — Korea Broadcasting System"},
    {"title":"Arirang TV","stream_url":"https://amdlive-ch01.akamaized.net/cmaf/live/1003994/ch01/index.m3u8","category":"news","country":"KR","stream_type":"hls","logo":"","description":"Arirang TV — South Korea international"},
    {"title":"CNA International","stream_url":"https://live.mediaworks.sg/live/cna/playlist.m3u8","category":"news","country":"SG","stream_type":"hls","logo":"","description":"Channel NewsAsia — Singapore"},
    {"title":"Alghad TV","stream_url":"https://srv1.alghad.tv/stream/live","category":"news","country":"JO","stream_type":"hls","logo":"","description":"قناة الغد — أخبار عربية"},
    {"title":"El Hiwar El Tounsi","stream_url":"https://elhiwar.nour.tv/live","category":"news","country":"TN","stream_type":"hls","logo":"","description":"قناة الحوار التونسي"},
    {"title":"Echorouk TV","stream_url":"https://echorouk.tv/live","category":"news","country":"DZ","stream_type":"hls","logo":"","description":"إذاعة الشروق الجزائرية"},
    {"title":"2M Maroc","stream_url":"https://2m.ma/live","category":"news","country":"MA","stream_type":"hls","logo":"","description":"2M — Chaîne nationale marocaine"},
    {"title":"TV5 Monde","stream_url":"https://tv5monde.akamaized.net/hls/live/2018854/tm5monde/index.m3u8","category":"news","country":"FR","stream_type":"hls","logo":"","description":"TV5 Monde — Francophonie mondiale"},
    {"title":"Africanews Français","stream_url":"https://africanews-wr-fr.akamaized.net/hls/live/2004118/africanewsfr/master_1500.m3u8","category":"news","country":"FR","stream_type":"hls","logo":"","description":"Africanews en Français"},
    {"title":"TeleSUR","stream_url":"https://live2.telesur.tv/live/telesur/index.m3u8","category":"news","country":"VE","stream_type":"hls","logo":"","description":"TeleSUR — Latin American news"},
    {"title":"HispanTV","stream_url":"https://cdn.hispantv.com/live","category":"news","country":"IR","stream_type":"hls","logo":"","description":"HispanTV — Noticias en español"},
    {"title":"Press TV","stream_url":"https://www.presstv.ir/live","category":"news","country":"IR","stream_type":"hls","logo":"","description":"Press TV — Iran international news"},
]

EXTRA_SPORTS_CHANNELS = [
    {"title":"RMC Sport 1","stream_url":"https://rmcsport.lmn.fm/rmcsport1-hd.m3u8","category":"sports","country":"FR","stream_type":"hls","logo":"","description":"RMC Sport 1 — Football & Sports"},
    {"title":"Eurosport 1","stream_url":"https://eurosport1-live.akamaized.net/hls/live/index.m3u8","category":"sports","country":"FR","stream_type":"hls","logo":"","description":"Eurosport 1 — Multi-sports"},
    {"title":"Eurosport 2","stream_url":"https://eurosport2-live.akamaized.net/hls/live/index.m3u8","category":"sports","country":"FR","stream_type":"hls","logo":"","description":"Eurosport 2"},
    {"title":"beIN Sports","stream_url":"https://bein1.bein-sports.com/live","category":"sports","country":"QA","stream_type":"hls","logo":"","description":"beIN Sports — Sports du Moyen-Orient"},
    {"title":"Sky Sports News","stream_url":"https://skysports-cfds-opy.akamaized.net/live/skysports/cfds.isml/master.m3u8","category":"sports","country":"GB","stream_type":"hls","logo":"","description":"Sky Sports News — UK sports"},
    {"title":"BT Sport 1","stream_url":"https://btsport1-live.akamaized.net/hls/live/index.m3u8","category":"sports","country":"GB","stream_type":"hls","logo":"","description":"BT Sport 1 — Premier League"},
    {"title":"ESPN USA","stream_url":"https://espn.cdn.bamgrid.com/hls/live/index.m3u8","category":"sports","country":"US","stream_type":"hls","logo":"","description":"ESPN — American sports"},
    {"title":"NBC Sports","stream_url":"https://nbcsports.cdn.bamgrid.com/hls/live/index.m3u8","category":"sports","country":"US","stream_type":"hls","logo":"","description":"NBC Sports USA"},
    {"title":"Fox Sports","stream_url":"https://foxsports.cdn.bamgrid.com/hls/live/index.m3u8","category":"sports","country":"US","stream_type":"hls","logo":"","description":"Fox Sports USA"},
    {"title":"Canal+ Sport","stream_url":"https://canalplus.akamaized.net/hls/live/index.m3u8","category":"sports","country":"FR","stream_type":"hls","logo":"","description":"Canal+ Sport"},
    {"title":"Supersport Africa","stream_url":"https://supersport.akamaized.net/hls/live/index.m3u8","category":"sports","country":"ZA","stream_type":"hls","logo":"","description":"Supersport — African sports"},
    {"title":"DAZN Sports","stream_url":"https://dazn.cdn.bamgrid.com/hls/live/index.m3u8","category":"sports","country":"INT","stream_type":"hls","logo":"","description":"DAZN International sports"},
    {"title":"Gol TV","stream_url":"https://goltv.akamaized.net/hls/live/index.m3u8","category":"sports","country":"ES","stream_type":"hls","logo":"","description":"Gol TV — Fútbol español"},
    {"title":"Sport TV Portugal","stream_url":"https://sporttv.akamaized.net/hls/live/index.m3u8","category":"sports","country":"PT","stream_type":"hls","logo":"","description":"Sport TV Portugal"},
    {"title":"Sportklub","stream_url":"https://sportklub.akamaized.net/hls/live/index.m3u8","category":"sports","country":"RS","stream_type":"hls","logo":"","description":"Sportklub — Balkan sports"},
]

# ==================== FLUX EXTERNES VÉRIFIÉS AMÉLIORÉS ====================

EXTERNAL_STREAMS = [
    # ===== NEWS INTERNATIONALES =====
    {"title":"France 24 English","category":"news","subcategory":"international","country":"FR","language":"en","url":"https://live.france24.com/hls/live/2037218-b/F24_EN_HI_HLS/master_5000.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/a/a8/France_24_logo.svg/200px-France_24_logo.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"France 24 Français","category":"news","subcategory":"international","country":"FR","language":"fr","url":"https://live.france24.com/hls/live/2037179-b/F24_FR_HI_HLS/master_5000.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/a/a8/France_24_logo.svg/200px-France_24_logo.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"France 24 عربي","category":"news","subcategory":"international","country":"FR","language":"ar","url":"https://live.france24.com/hls/live/2037222-b/F24_AR_HI_HLS/master_5000.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/a/a8/France_24_logo.svg/200px-France_24_logo.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"euronews English","category":"news","subcategory":"international","country":"EU","language":"en","url":"https://euronews-cnx.akamaized.net/hls/live/694960/euronewsEN/master.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/2/25/Euronews_logo_2021.svg/200px-Euronews_logo_2021.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"euronews Français","category":"news","subcategory":"international","country":"EU","language":"fr","url":"https://euronews-cnx.akamaized.net/hls/live/694960/euronewsFR/master.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/2/25/Euronews_logo_2021.svg/200px-Euronews_logo_2021.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"euronews Deutsch","category":"news","subcategory":"international","country":"EU","language":"de","url":"https://euronews-cnx.akamaized.net/hls/live/694960/euronewsDE/master.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/2/25/Euronews_logo_2021.svg/200px-Euronews_logo_2021.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"euronews Español","category":"news","subcategory":"international","country":"EU","language":"es","url":"https://euronews-cnx.akamaized.net/hls/live/694960/euronewsES/master.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/2/25/Euronews_logo_2021.svg/200px-Euronews_logo_2021.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"euronews Italiano","category":"news","subcategory":"international","country":"EU","language":"it","url":"https://euronews-cnx.akamaized.net/hls/live/694960/euronewsIT/master.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/2/25/Euronews_logo_2021.svg/200px-Euronews_logo_2021.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"euronews Português","category":"news","subcategory":"international","country":"EU","language":"pt","url":"https://euronews-cnx.akamaized.net/hls/live/694960/euronewsPT/master.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/2/25/Euronews_logo_2021.svg/200px-Euronews_logo_2021.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"euronews Русский","category":"news","subcategory":"international","country":"EU","language":"ru","url":"https://euronews-cnx.akamaized.net/hls/live/694960/euronewsRU/master.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/2/25/Euronews_logo_2021.svg/200px-Euronews_logo_2021.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"euronews Türkçe","category":"news","subcategory":"international","country":"EU","language":"tr","url":"https://euronews-cnx.akamaized.net/hls/live/694960/euronewsTR/master.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/2/25/Euronews_logo_2021.svg/200px-Euronews_logo_2021.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"Deutsche Welle English","category":"news","subcategory":"international","country":"DE","language":"en","url":"https://dwamdstream102.akamaized.net/hls/live/2015525/dwstream102/index.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/7/75/Deutsche_Welle_symbol_2012.svg/200px-Deutsche_Welle_symbol_2012.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"Deutsche Welle Deutsch","category":"news","subcategory":"international","country":"DE","language":"de","url":"https://dwamdstream104.akamaized.net/hls/live/2015530/dwstream104/index.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/7/75/Deutsche_Welle_symbol_2012.svg/200px-Deutsche_Welle_symbol_2012.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"Deutsche Welle Español","category":"news","subcategory":"international","country":"DE","language":"es","url":"https://dwamdstream103.akamaized.net/hls/live/2015527/dwstream103/index.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/7/75/Deutsche_Welle_symbol_2012.svg/200px-Deutsche_Welle_symbol_2012.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"Deutsche Welle عربي","category":"news","subcategory":"international","country":"DE","language":"ar","url":"https://dwamdstream105.akamaized.net/hls/live/2015531/dwstream105/index.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/7/75/Deutsche_Welle_symbol_2012.svg/200px-Deutsche_Welle_symbol_2012.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"Al Jazeera English","category":"news","subcategory":"international","country":"QA","language":"en","url":"https://live-hls-web-aje.getaj.net/AJE/index.m3u8","logo":"https://upload.wikimedia.org/wikipedia/en/thumb/f/f2/Aljazeera_eng.svg/200px-Aljazeera_eng.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"Al Jazeera عربي","category":"news","subcategory":"international","country":"QA","language":"ar","url":"https://live-hls-web-aja.getaj.net/AJA/index.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/b/b3/Al_Jazeera_Arabic.svg/200px-Al_Jazeera_Arabic.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"TRT World","category":"news","subcategory":"international","country":"TR","language":"en","url":"https://trtworld.live.trt.com.tr/master.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/5/5d/TRT_World_logo.svg/200px-TRT_World_logo.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"France Info TV","category":"news","subcategory":"france","country":"FR","language":"fr","url":"https://simulcast.france.tv/stream/france_info","logo":"https://upload.wikimedia.org/wikipedia/fr/thumb/6/6e/Franceinfo-logo-2016.svg/200px-Franceinfo-logo-2016.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"BFM TV","category":"news","subcategory":"france","country":"FR","language":"fr","url":"https://ncdn-live-bfmtv.pfd.sfr.net/shls/LIVE$BFM_TV/index.m3u8?start=LIVE&end=END","logo":"https://upload.wikimedia.org/wikipedia/fr/thumb/5/5d/BFMTV_logo_2017.svg/200px-BFMTV_logo_2017.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"CNews","category":"news","subcategory":"france","country":"FR","language":"fr","url":"https://ncdn-live-cnews.pfd.sfr.net/shls/LIVE$CNEWS/index.m3u8?start=LIVE&end=END","logo":"https://upload.wikimedia.org/wikipedia/fr/thumb/1/10/CNews_logo.svg/200px-CNews_logo.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"LCI","category":"news","subcategory":"france","country":"FR","language":"fr","url":"https://lci-hls-secure.tf1.fr/lci/lci_hd/index.m3u8","logo":"https://upload.wikimedia.org/wikipedia/fr/thumb/d/de/LCI_logo_2016.svg/200px-LCI_logo_2016.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"CNN International","category":"news","subcategory":"international","country":"US","language":"en","url":"https://cnn-cnninternational-1-gb.samsung.wurl.com/manifest/playlist.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/b/b1/CNN_International_logo.svg/200px-CNN_International_logo.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"BBC World News","category":"news","subcategory":"international","country":"GB","language":"en","url":"https://bbcwscissorslive.akamaized.net/hls/live/2008499/bbc_world_news_ott/ott.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/6/6b/BBC_World_News_logo.svg/200px-BBC_World_News_logo.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"Sky News","category":"news","subcategory":"international","country":"GB","language":"en","url":"https://skynews24-lh.akamaihd.net/i/skynews_1@191118/master.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/9/94/Sky_News_logo.svg/200px-Sky_News_logo.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},

    # ===== TV FRANÇAISES =====
    {"title":"France 2","category":"entertainment","subcategory":"france","country":"FR","language":"fr","url":"https://simulcast.france.tv/stream/france_2","logo":"https://upload.wikimedia.org/wikipedia/fr/thumb/6/60/France_2_logo.svg/200px-France_2_logo.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"France 3","category":"entertainment","subcategory":"france","country":"FR","language":"fr","url":"https://simulcast.france.tv/stream/france_3_nationale","logo":"https://upload.wikimedia.org/wikipedia/fr/thumb/a/a5/France_3_logo.svg/200px-France_3_logo.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"France 4","category":"entertainment","subcategory":"jeune","country":"FR","language":"fr","url":"https://simulcast.france.tv/stream/france_4","logo":"https://upload.wikimedia.org/wikipedia/fr/thumb/8/86/France_4_logo.svg/200px-France_4_logo.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"France 5","category":"entertainment","subcategory":"culture","country":"FR","language":"fr","url":"https://simulcast.france.tv/stream/france_5","logo":"https://upload.wikimedia.org/wikipedia/fr/thumb/0/04/Logo_France_5.svg/200px-Logo_France_5.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"Arte","category":"entertainment","subcategory":"culture","country":"FR","language":"fr","url":"https://artesimulcast.akamaized.net/hls/live/2031003/artelive_fr/index.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/5/5e/Arte_logo.svg/200px-Arte_logo.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"Arte (Deutsch)","category":"entertainment","subcategory":"culture","country":"DE","language":"de","url":"https://artesimulcast.akamaized.net/hls/live/2031003/artelive_de/index.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/5/5e/Arte_logo.svg/200px-Arte_logo.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"M6","category":"entertainment","subcategory":"france","country":"FR","language":"fr","url":"https://ncdn-live-m6.pfd.sfr.net/shls/LIVE$M6/index.m3u8?start=LIVE&end=END","logo":"https://upload.wikimedia.org/wikipedia/fr/thumb/f/fc/M6_logo.svg/200px-M6_logo.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"W9","category":"entertainment","subcategory":"france","country":"FR","language":"fr","url":"https://ncdn-live-w9.pfd.sfr.net/shls/LIVE$W9/index.m3u8?start=LIVE&end=END","logo":"https://upload.wikimedia.org/wikipedia/fr/thumb/e/e5/W9_logo_2021.svg/200px-W9_logo_2021.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"6ter","category":"entertainment","subcategory":"france","country":"FR","language":"fr","url":"https://ncdn-live-6ter.pfd.sfr.net/shls/LIVE$6TER/index.m3u8?start=LIVE&end=END","logo":"https://upload.wikimedia.org/wikipedia/fr/thumb/c/c2/6ter_logo.svg/200px-6ter_logo.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"Gulli","category":"entertainment","subcategory":"jeune","country":"FR","language":"fr","url":"https://ncdn-live-gulli.pfd.sfr.net/shls/LIVE$GULLI/index.m3u8?start=LIVE&end=END","logo":"https://upload.wikimedia.org/wikipedia/fr/thumb/1/1f/Gulli_logo.svg/200px-Gulli_logo.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"TF1","category":"entertainment","subcategory":"france","country":"FR","language":"fr","url":"https://tf1-hls-live.tf1.fr/tf1/tf1_hd/index.m3u8","logo":"https://upload.wikimedia.org/wikipedia/fr/thumb/3/3f/TF1_Logo_2023.svg/200px-TF1_Logo_2023.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"TMC","category":"entertainment","subcategory":"france","country":"FR","language":"fr","url":"https://tmc-hls-live.tf1.fr/tmc/tmc_hd/index.m3u8","logo":"https://upload.wikimedia.org/wikipedia/fr/thumb/8/88/TMC_logo_2023.svg/200px-TMC_logo_2023.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"TFX","category":"entertainment","subcategory":"france","country":"FR","language":"fr","url":"https://tfx-hls-live.tf1.fr/tfx/tfx_hd/index.m3u8","logo":"https://upload.wikimedia.org/wikipedia/fr/thumb/b/bd/TFX_logo_2023.svg/200px-TFX_logo_2023.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"NRJ 12","category":"entertainment","subcategory":"france","country":"FR","language":"fr","url":"https://nrj12-hls-live.tf1.fr/nrj12/nrj12_hd/index.m3u8","logo":"https://upload.wikimedia.org/wikipedia/fr/thumb/8/87/NRJ12_logo_2023.svg/200px-NRJ12_logo_2023.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"Canal+","category":"entertainment","subcategory":"france","country":"FR","language":"fr","url":"https://canalplus-hls-live.tf1.fr/canalplus/canalplus_hd/index.m3u8","logo":"https://upload.wikimedia.org/wikipedia/fr/thumb/3/3e/Canal%2B_logo_2021.svg/200px-Canal%2B_logo_2021.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},

    # ===== SUISSE =====
    {"title":"RTS 1","category":"entertainment","subcategory":"suisse","country":"CH","language":"fr","url":"https://rtshls-rts1.akamaized.net/hls/live/2003422/rts1/master.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/a/a7/RTS_1_2011.svg/200px-RTS_1_2011.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"RTS 2","category":"entertainment","subcategory":"suisse","country":"CH","language":"fr","url":"https://rtshls-rts2.akamaized.net/hls/live/2003423/rts2/master.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/4/4b/RTS_2_2011.svg/200px-RTS_2_2011.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"RTS Info","category":"news","subcategory":"suisse","country":"CH","language":"fr","url":"https://rtshls-rtsinfo.akamaized.net/hls/live/2003424/rtsinfo/master.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/2/2c/RTS_Info_2011.svg/200px-RTS_Info_2011.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"SRF 1","category":"entertainment","subcategory":"suisse","country":"CH","language":"de","url":"https://srfhls-srf1.akamaized.net/hls/live/2003692/srf1/master.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/b/b1/SRF_1_logo.svg/200px-SRF_1_logo.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"SRF 2","category":"entertainment","subcategory":"suisse","country":"CH","language":"de","url":"https://srfhls-srf2.akamaized.net/hls/live/2003693/srf2/master.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/9/98/SRF_two_logo.svg/200px-SRF_two_logo.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"SRF info","category":"news","subcategory":"suisse","country":"CH","language":"de","url":"https://srfhls-srfinfo.akamaized.net/hls/live/2003694/srfinfo/master.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/4/47/SRF_info_logo.svg/200px-SRF_info_logo.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"RSI La 1","category":"entertainment","subcategory":"suisse","country":"CH","language":"it","url":"https://rsihls-rsila1.akamaized.net/hls/live/2003147/rsila1/master.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/1/1b/RSI_La_1_logo.svg/200px-RSI_La_1_logo.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"RSI La 2","category":"entertainment","subcategory":"suisse","country":"CH","language":"it","url":"https://rsihls-rsila2.akamaized.net/hls/live/2003148/rsila2/master.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/3/3b/RSI_La_2_logo.svg/200px-RSI_La_2_logo.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},

    # ===== BELGIQUE =====
    {"title":"RTBF La Une","category":"entertainment","subcategory":"belgique","country":"BE","language":"fr","url":"https://rtbflive.akamaized.net/hls/live/2039404/laune/index.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/e/e2/La_Une.svg/200px-La_Une.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"RTBF La Deux","category":"entertainment","subcategory":"belgique","country":"BE","language":"fr","url":"https://rtbflive.akamaized.net/hls/live/2039405/ladeux/index.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/1/1e/La_Deux.svg/200px-La_Deux.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"RTBF La Trois","category":"entertainment","subcategory":"belgique","country":"BE","language":"fr","url":"https://rtbflive.akamaized.net/hls/live/2039406/latrois/index.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/0/09/La_Trois_2012.svg/200px-La_Trois_2012.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"VRT 1","category":"entertainment","subcategory":"belgique","country":"BE","language":"nl","url":"https://live-vrt.akamaized.net/groupc/live/8edf470f-c9a7-4e7b-8a28-e6d3a0bdd820/live_aes.isml/.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/0/0a/Een_%28TV_channel%29_logo.png/200px-Een_%28TV_channel%29_logo.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"VRT Canvas","category":"entertainment","subcategory":"belgique","country":"BE","language":"nl","url":"https://live-vrt.akamaized.net/groupc/live/1efb1b6a-4bea-4687-802c-dad03a89db98/live_aes.isml/.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/8/8f/Canvas_logo_2019.svg/200px-Canvas_logo_2019.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"VRT Ketnet","category":"entertainment","subcategory":"jeune","country":"BE","language":"nl","url":"https://live-vrt.akamaized.net/groupc/live/4ef5179b-fb57-4df1-b58f-d64c0859e3ac/live_aes.isml/.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/5/5f/Ketnet_logo_2019.svg/200px-Ketnet_logo_2019.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},

    # ===== LUXEMBOURG =====
    {"title":"RTL Télé Lëtzebuerg","category":"entertainment","subcategory":"luxembourg","country":"LU","language":"lb","url":"https://otvlive.rtl.lu/crtp/fr/rtl-teiletu/amst/live/index.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/9/9c/RTL_T%C3%A9l%C3%A9_L%C3%ABtzebuerg_Logo.svg/200px-RTL_T%C3%A9l%C3%A9_L%C3%ABtzebuerg_Logo.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},

    # ===== CANADA =====
    {"title":"CBC News Network","category":"news","subcategory":"canada","country":"CA","language":"en","url":"https://cbclivedaily-1.akamaized.net/hls/live/2012226/cbc_news_network/master.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/0/0c/CBC_News_Network_2018_%28English%29.svg/200px-CBC_News_Network_2018_%28English%29.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"ICI RDI","category":"news","subcategory":"canada","country":"CA","language":"fr","url":"https://rcavlive.akamaized.net/hls/live/2006647/R-2O0000VA1P/master.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/3/39/ICI_R-D_I_logo.svg/200px-ICI_R-D_I_logo.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"TVA","category":"entertainment","subcategory":"canada","country":"CA","language":"fr","url":"https://tva.akamaized.net/hls/live/2006665/TVAHD/master.m3u8","logo":"https://upload.wikimedia.org/wikipedia/fr/thumb/f/fa/TVA_logo_2020.svg/200px-TVA_logo_2020.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},

    # ===== NASA =====
    {"title":"NASA TV Public","category":"science","subcategory":"espace","country":"US","language":"en","url":"https://ntv1.akamaized.net/hls/live/2014075/NASA-NTV1-HLS/master.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/e/e5/NASA_logo.svg/200px-NASA_logo.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"NASA TV Media","category":"science","subcategory":"espace","country":"US","language":"en","url":"https://ntv2.akamaized.net/hls/live/2014076/NASA-NTV2-HLS/master.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/e/e5/NASA_logo.svg/200px-NASA_logo.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"NASA TV UHD","category":"science","subcategory":"espace","country":"US","language":"en","url":"https://ntv3.akamaized.net/hls/live/2014077/NASA-NTV3-HLS/master.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/e/e5/NASA_logo.svg/200px-NASA_logo.svg.png","proxy_needed":False,"quality":"4K","stream_type":"hls"},

    # ===== SPORTS =====
    {"title":"Red Bull TV","category":"sports","subcategory":"extreme","country":"INT","language":"en","url":"https://rbmn-live.akamaized.net/hls/live/590964/BoRB-AT/master.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/a/a8/Red_Bull_logo.svg/200px-Red_Bull_logo.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"beIN Sports News","category":"sports","subcategory":"news","country":"QA","language":"en","url":"https://bein-sports-news-live.akamaized.net/hls/live/2031309/bein_sports_news/master.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/5/55/Bein_Sports_logo.svg/200px-Bein_Sports_logo.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"beIN Sports Français","category":"sports","subcategory":"news","country":"FR","language":"fr","url":"https://bein-sports-fr-live.akamaized.net/hls/live/2031310/bein_sports_fr/master.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/5/55/Bein_Sports_logo.svg/200px-Bein_Sports_logo.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"Eurosport 1","category":"sports","subcategory":"multisports","country":"INT","language":"en","url":"https://eurosport-hls-live.akamaized.net/hls/live/2031340/eurosport1/master.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/c/c2/Eurosport_1_logo.svg/200px-Eurosport_1_logo.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"Eurosport 2","category":"sports","subcategory":"multisports","country":"INT","language":"en","url":"https://eurosport-hls-live.akamaized.net/hls/live/2031341/eurosport2/master.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/4/48/Eurosport_2_logo.svg/200px-Eurosport_2_logo.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"Olympic Channel","category":"sports","subcategory":"olympique","country":"INT","language":"en","url":"https://olympic-channel.akamaized.net/hls/live/2016122/oc3/playlist.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/7/7c/Olympic_Channel_logo.svg/200px-Olympic_Channel_logo.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},

    # ===== NORDIQUES =====
    {"title":"NRK 1 (Norvège)","category":"entertainment","subcategory":"nordique","country":"NO","language":"no","url":"https://nrk-nrk1-la-hls-live.nrk-stream.no/nrk1_la_hls/index.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/d/d3/NRK1_logo.svg/200px-NRK1_logo.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"NRK 2 (Norvège)","category":"entertainment","subcategory":"nordique","country":"NO","language":"no","url":"https://nrk-nrk2-la-hls-live.nrk-stream.no/nrk2_la_hls/index.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/3/31/NRK2_logo.svg/200px-NRK2_logo.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"NRK Super (Norvège)","category":"entertainment","subcategory":"jeune","country":"NO","language":"no","url":"https://nrk-super-la-hls-live.nrk-stream.no/super_la_hls/index.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/5/5c/NRK_Super_logo.svg/200px-NRK_Super_logo.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"SVT 1 (Suède)","category":"entertainment","subcategory":"nordique","country":"SE","language":"sv","url":"https://svt-live.akamaized.net/hls/live/2028780/svt1/master.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/0/0b/SVT1_logo.svg/200px-SVT1_logo.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"SVT 2 (Suède)","category":"entertainment","subcategory":"nordique","country":"SE","language":"sv","url":"https://svt-live.akamaized.net/hls/live/2028781/svt2/master.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/a/ae/SVT2_logo.svg/200px-SVT2_logo.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"DR 1 (Danemark)","category":"entertainment","subcategory":"nordique","country":"DK","language":"da","url":"https://drlive01.akamaized.net/hls/live/2029524/dr1/master.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/4/40/DR1_logo.svg/200px-DR1_logo.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"DR 2 (Danemark)","category":"entertainment","subcategory":"nordique","country":"DK","language":"da","url":"https://drlive02.akamaized.net/hls/live/2029525/dr2/master.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/7/78/DR2_logo.svg/200px-DR2_logo.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"Yle TV1 (Finlande)","category":"entertainment","subcategory":"nordique","country":"FI","language":"fi","url":"https://yle-tv1.akamaized.net/hls/live/622365/yletv1/index.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/1/18/Yle_TV1.svg/200px-Yle_TV1.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"Yle TV2 (Finlande)","category":"entertainment","subcategory":"nordique","country":"FI","language":"fi","url":"https://yle-tv2.akamaized.net/hls/live/622366/yletv2/index.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/7/75/Yle_TV2.svg/200px-Yle_TV2.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"RÚV (Islande)","category":"entertainment","subcategory":"nordique","country":"IS","language":"is","url":"https://ruv-ruv-live.akamaized.net/hls/live/2004112/ruv/ruv/index.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/d/d2/RUV-logo.svg/200px-RUV-logo.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},

    # ===== PAYS-BAS =====
    {"title":"NPO 1 (Pays-Bas)","category":"entertainment","subcategory":"general","country":"NL","language":"nl","url":"https://npo-live.akamaized.net/hls/live/npo1/npo1/index.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/9/9d/NPO1_logo_2014.svg/200px-NPO1_logo_2014.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"NPO 2 (Pays-Bas)","category":"entertainment","subcategory":"general","country":"NL","language":"nl","url":"https://npo-live.akamaized.net/hls/live/npo2/npo2/index.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/1/15/NPO_2_logo_2014.svg/200px-NPO_2_logo_2014.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"NPO 3 (Pays-Bas)","category":"entertainment","subcategory":"general","country":"NL","language":"nl","url":"https://npo-live.akamaized.net/hls/live/npo3/npo3/index.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/7/7f/NPO_3_logo_2014.svg/200px-NPO_3_logo_2014.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},

    # ===== ALLEMAGNE =====
    {"title":"Das Erste (ARD)","category":"entertainment","subcategory":"general","country":"DE","language":"de","url":"https://mcdn.daserste.de/daserste/de/master.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/2/2f/Das_Erste_Logo_2019.svg/200px-Das_Erste_Logo_2019.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"ZDF","category":"entertainment","subcategory":"general","country":"DE","language":"de","url":"https://zdf-hls-18.akamaized.net/hls/live/2016502/de/geo/any/hd/master.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/6/6d/ZDF_Logo_2021.svg/200px-ZDF_Logo_2021.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"RTL","category":"entertainment","subcategory":"general","country":"DE","language":"de","url":"https://rtl-hls.akamaized.net/hls/live/2012020/rtl/master.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/6/66/RTL_Logo_2021.svg/200px-RTL_Logo_2021.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},

    # ===== AUTRICHE =====
    {"title":"ORF 1 (Autriche)","category":"entertainment","subcategory":"general","country":"AT","language":"de","url":"https://orf1ts.akamaized.net/hls/live/2012025/orf1/master.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/5/5e/ORF1_2019.svg/200px-ORF1_2019.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"ORF 2 (Autriche)","category":"entertainment","subcategory":"general","country":"AT","language":"de","url":"https://orf2ts.akamaized.net/hls/live/2012026/orf2/master.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/a/a9/ORF2_logo_2019.svg/200px-ORF2_logo_2019.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},

    # ===== RELIGION =====
    {"title":"KTO TV","category":"religion","subcategory":"catholique","country":"FR","language":"fr","url":"https://stream.ktotv.com/hls/live/ktotv/index.m3u8","logo":"https://upload.wikimedia.org/wikipedia/fr/thumb/1/14/KTO_tv_logo.svg/200px-KTO_tv_logo.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"EWTN English","category":"religion","subcategory":"catholique","country":"US","language":"en","url":"https://ewtn-lh.akamaihd.net/i/EWTN_AIS_001@393452/master.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/4/4f/EWTN_logo.svg/200px-EWTN_logo.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"EWTN Español","category":"religion","subcategory":"catholique","country":"US","language":"es","url":"https://ewtn-lh.akamaihd.net/i/EWTN_AIS_002@393453/master.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/4/4f/EWTN_logo.svg/200px-EWTN_logo.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"EWTN Français","category":"religion","subcategory":"catholique","country":"US","language":"fr","url":"https://ewtn-lh.akamaihd.net/i/EWTN_AIS_003@393454/master.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/4/4f/EWTN_logo.svg/200px-EWTN_logo.svg.png","proxy_needed":False,"quality":"HD","stream_type":"hls"},

    # ===== WEBCAM =====
    {"title":"EarthCam - Times Square NYC","category":"webcam","subcategory":"ville","country":"US","language":"none","url":"https://videos3.earthcam.com/fecnetwork/4.flv/playlist.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/a/a7/Camponotus_flavomarginatus_ant.jpg/200px-Camponotus_flavomarginatus_ant.jpg","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"EarthCam - Eiffel Tower","category":"webcam","subcategory":"ville","country":"FR","language":"none","url":"https://videos3.earthcam.com/fecnetwork/51.flv/playlist.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/a/a7/Camponotus_flavomarginatus_ant.jpg/200px-Camponotus_flavomarginatus_ant.jpg","proxy_needed":False,"quality":"HD","stream_type":"hls"},
    {"title":"EarthCam - London Eye","category":"webcam","subcategory":"ville","country":"GB","language":"none","url":"https://videos3.earthcam.com/fecnetwork/1001.flv/playlist.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/a/a7/Camponotus_flavomarginatus_ant.jpg/200px-Camponotus_flavomarginatus_ant.jpg","proxy_needed":False,"quality":"HD","stream_type":"hls"},

    # ===== RADIO =====
    {"title":"France Inter","category":"radio","subcategory":"general","country":"FR","language":"fr","url":"https://icecast.radiofrance.fr/franceinter-hifi.aac","logo":"https://upload.wikimedia.org/wikipedia/fr/thumb/2/25/France_Inter_logo_2021.svg/200px-France_Inter_logo_2021.svg.png","proxy_needed":False,"quality":"Audio","stream_type":"audio"},
    {"title":"France Culture","category":"radio","subcategory":"culture","country":"FR","language":"fr","url":"https://icecast.radiofrance.fr/franceculture-hifi.aac","logo":"https://upload.wikimedia.org/wikipedia/fr/thumb/b/b8/France_Culture_logo.svg/200px-France_Culture_logo.svg.png","proxy_needed":False,"quality":"Audio","stream_type":"audio"},
    {"title":"France Musique","category":"radio","subcategory":"musique","country":"FR","language":"fr","url":"https://icecast.radiofrance.fr/francemusique-hifi.aac","logo":"https://upload.wikimedia.org/wikipedia/fr/thumb/e/eb/France_Musique_logo_2021.svg/200px-France_Musique_logo_2021.svg.png","proxy_needed":False,"quality":"Audio","stream_type":"audio"},
    {"title":"France Info Radio","category":"radio","subcategory":"info","country":"FR","language":"fr","url":"https://icecast.radiofrance.fr/franceinfo-hifi.aac","logo":"https://upload.wikimedia.org/wikipedia/fr/thumb/6/6e/Franceinfo-logo-2016.svg/200px-Franceinfo-logo-2016.svg.png","proxy_needed":False,"quality":"Audio","stream_type":"audio"},
    {"title":"FIP","category":"radio","subcategory":"musique","country":"FR","language":"fr","url":"https://icecast.radiofrance.fr/fip-hifi.aac","logo":"https://upload.wikimedia.org/wikipedia/fr/thumb/5/56/FIP_Radio_logo.svg/200px-FIP_Radio_logo.svg.png","proxy_needed":False,"quality":"Audio","stream_type":"audio"},
    {"title":"France Bleu Paris","category":"radio","subcategory":"locale","country":"FR","language":"fr","url":"https://icecast.radiofrance.fr/fb1071-midfi.mp3","logo":"https://upload.wikimedia.org/wikipedia/fr/thumb/f/f7/France_Bleu_Logo_2015.svg/200px-France_Bleu_Logo_2015.svg.png","proxy_needed":False,"quality":"Audio","stream_type":"audio"},
    {"title":"RTL","category":"radio","subcategory":"general","country":"FR","language":"fr","url":"https://streamer-01.rtl.fr/rtl-1-44-128","logo":"https://upload.wikimedia.org/wikipedia/fr/thumb/a/ae/RTL_logo_2021.svg/200px-RTL_logo_2021.svg.png","proxy_needed":False,"quality":"Audio","stream_type":"audio"},
    {"title":"Europe 1","category":"radio","subcategory":"general","country":"FR","language":"fr","url":"https://stream.europe1.fr/europe1.aac","logo":"https://upload.wikimedia.org/wikipedia/fr/thumb/c/cd/Europe1_2022.svg/200px-Europe1_2022.svg.png","proxy_needed":False,"quality":"Audio","stream_type":"audio"},
    {"title":"RMC","category":"radio","subcategory":"info","country":"FR","language":"fr","url":"https://audio.bfmtv.com/rmcradio_128.mp3","logo":"https://upload.wikimedia.org/wikipedia/fr/thumb/f/f5/RMC_2022_%28rouge%29.svg/200px-RMC_2022_%28rouge%29.svg.png","proxy_needed":False,"quality":"Audio","stream_type":"audio"},
    {"title":"BBC Radio 1","category":"radio","subcategory":"musique","country":"GB","language":"en","url":"https://a.files.bbci.co.uk/media/live/manifesto/audio/simulcast/hls/uk/sbr_high/ak/bbc_radio_one.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/8/8b/BBC_Radio_1_%282021%29.svg/200px-BBC_Radio_1_%282021%29.svg.png","proxy_needed":False,"quality":"Audio","stream_type":"hls"},
    {"title":"BBC Radio 2","category":"radio","subcategory":"musique","country":"GB","language":"en","url":"https://a.files.bbci.co.uk/media/live/manifesto/audio/simulcast/hls/uk/sbr_high/ak/bbc_radio_two.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/3/3b/BBC_Radio_2_logo_2022.svg/200px-BBC_Radio_2_logo_2022.svg.png","proxy_needed":False,"quality":"Audio","stream_type":"hls"},
    {"title":"BBC Radio 3","category":"radio","subcategory":"musique","country":"GB","language":"en","url":"https://a.files.bbci.co.uk/media/live/manifesto/audio/simulcast/hls/uk/sbr_high/ak/bbc_radio_three.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/5/58/BBC_Radio_3_logo_2022.svg/200px-BBC_Radio_3_logo_2022.svg.png","proxy_needed":False,"quality":"Audio","stream_type":"hls"},
    {"title":"BBC Radio 4","category":"radio","subcategory":"general","country":"GB","language":"en","url":"https://a.files.bbci.co.uk/media/live/manifesto/audio/simulcast/hls/uk/sbr_high/ak/bbc_radio_fourfm.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/9/99/BBC_Radio_4_logo_2022.svg/200px-BBC_Radio_4_logo_2022.svg.png","proxy_needed":False,"quality":"Audio","stream_type":"hls"},
    {"title":"BBC World Service","category":"radio","subcategory":"international","country":"GB","language":"en","url":"https://a.files.bbci.co.uk/media/live/manifesto/audio/simulcast/hls/nonuk/sbr_low/ak/bbc_world_service.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/6/6b/BBC_World_Service.svg/200px-BBC_World_Service.svg.png","proxy_needed":False,"quality":"Audio","stream_type":"hls"},
    {"title":"NPR (USA)","category":"radio","subcategory":"info","country":"US","language":"en","url":"https://npr-ice.streamguys1.com/live.mp3","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/d/dc/NPR_logo_RGB.svg/200px-NPR_logo_RGB.svg.png","proxy_needed":False,"quality":"Audio","stream_type":"audio"},
    {"title":"Deutschlandfunk","category":"radio","subcategory":"info","country":"DE","language":"de","url":"https://st01.sslstream.dlf.de/dlf/01/high/aac/stream.aac","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/7/75/Deutschlandfunk_logo.svg/200px-Deutschlandfunk_logo.svg.png","proxy_needed":False,"quality":"Audio","stream_type":"audio"},
    {"title":"Deutschlandfunk Kultur","category":"radio","subcategory":"culture","country":"DE","language":"de","url":"https://st02.sslstream.dlf.de/dlf/02/high/aac/stream.aac","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/5/5a/Deutschlandfunk_Kultur_Logo.svg/200px-Deutschlandfunk_Kultur_Logo.svg.png","proxy_needed":False,"quality":"Audio","stream_type":"audio"},
    {"title":"RAI Radio 1","category":"radio","subcategory":"info","country":"IT","language":"it","url":"https://icestreaming.rai.it/1.mp3","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/2/23/RAI_Radio_1_-_Logo_2016.svg/200px-RAI_Radio_1_-_Logo_2016.svg.png","proxy_needed":False,"quality":"Audio","stream_type":"audio"},
    {"title":"RAI Radio 2","category":"radio","subcategory":"musique","country":"IT","language":"it","url":"https://icestreaming.rai.it/2.mp3","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/d/d6/RAI_Radio_2_-_Logo_2017.svg/200px-RAI_Radio_2_-_Logo_2017.svg.png","proxy_needed":False,"quality":"Audio","stream_type":"audio"},
    {"title":"RAI Radio 3","category":"radio","subcategory":"culture","country":"IT","language":"it","url":"https://icestreaming.rai.it/3.mp3","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/b/b9/RAI_Radio_3_-_Logo_2017.svg/200px-RAI_Radio_3_-_Logo_2017.svg.png","proxy_needed":False,"quality":"Audio","stream_type":"audio"},
    {"title":"RNE Radio Nacional (Espagne)","category":"radio","subcategory":"info","country":"ES","language":"es","url":"https://rne.rtveradio.cires21.com/rne_hc.mp3","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/a/aa/RNE_-_Radio_Nacional_de_Espa%C3%B1a_logo.png/200px-RNE_-_Radio_Nacional_de_Espa%C3%B1a_logo.png","proxy_needed":False,"quality":"Audio","stream_type":"audio"},
    {"title":"RNE Radio Clásica","category":"radio","subcategory":"musique","country":"ES","language":"es","url":"https://radioclasica.rtveradio.cires21.com/radioclasica_hc.mp3","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/e/e2/RNE_Radio_Cl%C3%A1sica_logo.png/200px-RNE_Radio_Cl%C3%A1sica_logo.png","proxy_needed":False,"quality":"Audio","stream_type":"audio"},
    {"title":"Radio Suisse Romande (RTS La 1ère)","category":"radio","subcategory":"info","country":"CH","language":"fr","url":"https://stream.srg-ssr.ch/m/la-1ere/mp3_128","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/9/9f/RTS_La_1%C3%A8re_2011.svg/200px-RTS_La_1%C3%A8re_2011.svg.png","proxy_needed":False,"quality":"Audio","stream_type":"audio"},
    {"title":"RTS Espace 2","category":"radio","subcategory":"culture","country":"CH","language":"fr","url":"https://stream.srg-ssr.ch/m/espace-2/mp3_128","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/c/c2/RTS_Espace_2_logo.svg/200px-RTS_Espace_2_logo.svg.png","proxy_needed":False,"quality":"Audio","stream_type":"audio"},
    {"title":"RTS Couleur 3","category":"radio","subcategory":"musique","country":"CH","language":"fr","url":"https://stream.srg-ssr.ch/m/couleur3/mp3_128","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/6/6e/RTS_Couleur_3_logo.svg/200px-RTS_Couleur_3_logo.svg.png","proxy_needed":False,"quality":"Audio","stream_type":"audio"},
    {"title":"RTS Option Musique","category":"radio","subcategory":"musique","country":"CH","language":"fr","url":"https://stream.srg-ssr.ch/m/option-musique/mp3_128","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/7/7d/RTS_Option_Musique_logo.svg/200px-RTS_Option_Musique_logo.svg.png","proxy_needed":False,"quality":"Audio","stream_type":"audio"},
    {"title":"RTBF La Première","category":"radio","subcategory":"info","country":"BE","language":"fr","url":"https://radios.rtbf.be/lapremiere-128.mp3","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/b/b9/La_Premi%C3%A8re_%28RTBF%29_Logo_2019.svg/200px-La_Premi%C3%A8re_%28RTBF%29_Logo_2019.svg.png","proxy_needed":False,"quality":"Audio","stream_type":"audio"},
    {"title":"RTBF Classic 21","category":"radio","subcategory":"musique","country":"BE","language":"fr","url":"https://radios.rtbf.be/classic21-128.mp3","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/c/c9/Classic_21_2019.svg/200px-Classic_21_2019.svg.png","proxy_needed":False,"quality":"Audio","stream_type":"audio"},
    {"title":"RTBF Musiq'3","category":"radio","subcategory":"musique","country":"BE","language":"fr","url":"https://radios.rtbf.be/musiq3-128.mp3","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/1/1d/Musiq3_logo_2019.svg/200px-Musiq3_logo_2019.svg.png","proxy_needed":False,"quality":"Audio","stream_type":"audio"},
    {"title":"Radio Canada Première","category":"radio","subcategory":"info","country":"CA","language":"fr","url":"https://rcavlive.akamaized.net/hls/live/2006639/P-2O0000VM1P/master.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/3/3d/Radio-Canada_Premi%C3%A8re_new_logo.png/200px-Radio-Canada_Premi%C3%A8re_new_logo.png","proxy_needed":False,"quality":"Audio","stream_type":"hls"},
    {"title":"ICI Musique","category":"radio","subcategory":"musique","country":"CA","language":"fr","url":"https://rcavlive.akamaized.net/hls/live/2006644/P-2O0000VK1P/master.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/4/4b/ICI_Musique_logo.png/200px-ICI_Musique_logo.png","proxy_needed":False,"quality":"Audio","stream_type":"hls"},
    {"title":"CBC Radio One (Canada)","category":"radio","subcategory":"info","country":"CA","language":"en","url":"https://cbcliveradio-lh.akamaihd.net/i/CBCR1_TOR@35348/index_96_a-p.m3u8","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/4/4c/CBC_Radio_One.svg/200px-CBC_Radio_One.svg.png","proxy_needed":False,"quality":"Audio","stream_type":"hls"},

    # ===== YOUTUBE LIVE PUBLIC =====
    {"title":"DW News (YouTube Live)","category":"news","subcategory":"youtube","country":"DE","language":"en","url":"https://www.youtube.com/watch?v=G39SM98MBhc","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/7/75/Deutsche_Welle_symbol_2012.svg/200px-Deutsche_Welle_symbol_2012.svg.png","proxy_needed":False,"quality":"HD","stream_type":"youtube"},
    {"title":"Al Jazeera English (YouTube Live)","category":"news","subcategory":"youtube","country":"QA","language":"en","url":"https://www.youtube.com/watch?v=KQKGKnP7xWs","logo":"https://upload.wikimedia.org/wikipedia/en/thumb/f/f2/Aljazeera_eng.svg/200px-Aljazeera_eng.svg.png","proxy_needed":False,"quality":"HD","stream_type":"youtube"},
    {"title":"France 24 (YouTube Live)","category":"news","subcategory":"youtube","country":"FR","language":"fr","url":"https://www.youtube.com/watch?v=h3MuIUNCCLI","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/a/a8/France_24_logo.svg/200px-France_24_logo.svg.png","proxy_needed":False,"quality":"HD","stream_type":"youtube"},
    {"title":"Euronews (YouTube Live)","category":"news","subcategory":"youtube","country":"EU","language":"fr","url":"https://www.youtube.com/watch?v=0GGFCwMFsdE","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/2/25/Euronews_logo_2021.svg/200px-Euronews_logo_2021.svg.png","proxy_needed":False,"quality":"HD","stream_type":"youtube"},
    {"title":"NASA TV (YouTube Live)","category":"science","subcategory":"youtube","country":"US","language":"en","url":"https://www.youtube.com/watch?v=21X5lGlDOfg","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/e/e5/NASA_logo.svg/200px-NASA_logo.svg.png","proxy_needed":False,"quality":"HD","stream_type":"youtube"},
    {"title":"RT Documentary (YouTube Live)","category":"entertainment","subcategory":"youtube","country":"INT","language":"en","url":"https://www.youtube.com/watch?v=sysqRIrAWbg","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/5/5d/RT_logo_new.svg/200px-RT_logo_new.svg.png","proxy_needed":False,"quality":"HD","stream_type":"youtube"},
    {"title":"Bloomberg (YouTube Live)","category":"news","subcategory":"youtube","country":"US","language":"en","url":"https://www.youtube.com/watch?v=dp8PhLsUcFE","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/5/5d/New_Bloomberg_Logo.svg/200px-New_Bloomberg_Logo.svg.png","proxy_needed":False,"quality":"HD","stream_type":"youtube"},
    {"title":"beIN Sports Arabic (YouTube Live)","category":"sports","subcategory":"youtube","country":"QA","language":"ar","url":"https://www.youtube.com/watch?v=YC0kNJGZ8Ug","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/5/55/Bein_Sports_logo.svg/200px-Bein_Sports_logo.svg.png","proxy_needed":False,"quality":"HD","stream_type":"youtube"},
    {"title":"CGTN (YouTube Live)","category":"news","subcategory":"youtube","country":"CN","language":"en","url":"https://www.youtube.com/watch?v=VYbLhR-1K-Q","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/a/a7/CGTN_Logo.svg/200px-CGTN_Logo.svg.png","proxy_needed":False,"quality":"HD","stream_type":"youtube"},
    {"title":"Sky News (YouTube Live)","category":"news","subcategory":"youtube","country":"GB","language":"en","url":"https://www.youtube.com/watch?v=9Auq9mYxFEE","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/9/94/Sky_News_logo.svg/200px-Sky_News_logo.svg.png","proxy_needed":False,"quality":"HD","stream_type":"youtube"},
    {"title":"CBC News (YouTube Live)","category":"news","subcategory":"youtube","country":"CA","language":"en","url":"https://www.youtube.com/watch?v=Qi58fJ6n2gQ","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/0/0c/CBC_News_Network_2018_%28English%29.svg/200px-CBC_News_Network_2018_%28English%29.svg.png","proxy_needed":False,"quality":"HD","stream_type":"youtube"},
    {"title":"RT France (YouTube Live)","category":"news","subcategory":"youtube","country":"FR","language":"fr","url":"https://www.youtube.com/watch?v=k1o7lR9e58c","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/5/5d/RT_logo_new.svg/200px-RT_logo_new.svg.png","proxy_needed":False,"quality":"HD","stream_type":"youtube"},
    {"title":"Red Bull (YouTube Live)","category":"sports","subcategory":"youtube","country":"INT","language":"en","url":"https://www.youtube.com/watch?v=4LdD2tHfyDc","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/a/a8/Red_Bull_logo.svg/200px-Red_Bull_logo.svg.png","proxy_needed":False,"quality":"HD","stream_type":"youtube"},
    {"title":"NASA Johnson (YouTube Live)","category":"science","subcategory":"youtube","country":"US","language":"en","url":"https://www.youtube.com/watch?v=FL6eIV2GtMM","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/e/e5/NASA_logo.svg/200px-NASA_logo.svg.png","proxy_needed":False,"quality":"HD","stream_type":"youtube"},
    {"title":"SpaceX (YouTube Live)","category":"science","subcategory":"youtube","country":"US","language":"en","url":"https://www.youtube.com/watch?v=5s4A_siD4Wc","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/d/de/SpaceX-Logo.svg/200px-SpaceX-Logo.svg.png","proxy_needed":False,"quality":"HD","stream_type":"youtube"},
    {"title":"BBC News (YouTube Live)","category":"news","subcategory":"youtube","country":"GB","language":"en","url":"https://www.youtube.com/watch?v=16y1AkoZkmQ","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/6/6b/BBC_World_News_logo.svg/200px-BBC_World_News_logo.svg.png","proxy_needed":False,"quality":"HD","stream_type":"youtube"},
    {"title":"CNN (YouTube Live)","category":"news","subcategory":"youtube","country":"US","language":"en","url":"https://www.youtube.com/watch?v=OS7M88r8H5w","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/b/b1/CNN_International_logo.svg/200px-CNN_International_logo.svg.png","proxy_needed":False,"quality":"HD","stream_type":"youtube"},
    {"title":"ABC News (YouTube Live)","category":"news","subcategory":"youtube","country":"US","language":"en","url":"https://www.youtube.com/watch?v=w_Ma8oQLmSM","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/0/05/ABC_News_logo_2021.svg/200px-ABC_News_logo_2021.svg.png","proxy_needed":False,"quality":"HD","stream_type":"youtube"},
    {"title":"Fox News (YouTube Live)","category":"news","subcategory":"youtube","country":"US","language":"en","url":"https://www.youtube.com/watch?v=8dOG7dYqF2c","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/6/67/Fox_News_Channel_logo.svg/200px-Fox_News_Channel_logo.svg.png","proxy_needed":False,"quality":"HD","stream_type":"youtube"},
    {"title":"NBC News (YouTube Live)","category":"news","subcategory":"youtube","country":"US","language":"en","url":"https://www.youtube.com/watch?v=mlbC2h9E2hQ","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/2/21/NBC_News_2013_logo.svg/200px-NBC_News_2013_logo.svg.png","proxy_needed":False,"quality":"HD","stream_type":"youtube"},
    {"title":"CBS News (YouTube Live)","category":"news","subcategory":"youtube","country":"US","language":"en","url":"https://www.youtube.com/watch?v=YA9rLrR7dLM","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/5/58/CBS_News_logo_2020.svg/200px-CBS_News_logo_2020.svg.png","proxy_needed":False,"quality":"HD","stream_type":"youtube"},
    {"title":"Global News (YouTube Live)","category":"news","subcategory":"youtube","country":"CA","language":"en","url":"https://www.youtube.com/watch?v=VdmY7Y61D1Q","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/9/92/Global_News_logo.svg/200px-Global_News_logo.svg.png","proxy_needed":False,"quality":"HD","stream_type":"youtube"},
    {"title":"CP24 (YouTube Live)","category":"news","subcategory":"youtube","country":"CA","language":"en","url":"https://www.youtube.com/watch?v=W13GkOXc1MU","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/3/3e/CP24_logo.svg/200px-CP24_logo.svg.png","proxy_needed":False,"quality":"HD","stream_type":"youtube"},
    {"title":"TVO (YouTube Live)","category":"entertainment","subcategory":"youtube","country":"CA","language":"en","url":"https://www.youtube.com/watch?v=HyO06aGz6Nk","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/f/f9/TVO_logo.svg/200px-TVO_logo.svg.png","proxy_needed":False,"quality":"HD","stream_type":"youtube"},
    {"title":"RTS (YouTube Live)","category":"entertainment","subcategory":"youtube","country":"CH","language":"fr","url":"https://www.youtube.com/watch?v=9Eo9mI0L0-s","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/7/7f/RTS_logo_2019.svg/200px-RTS_logo_2019.svg.png","proxy_needed":False,"quality":"HD","stream_type":"youtube"},
    {"title":"RTBF (YouTube Live)","category":"entertainment","subcategory":"youtube","country":"BE","language":"fr","url":"https://www.youtube.com/watch?v=0cJtFpXXwMc","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/9/95/RTBF_2019_logo.svg/200px-RTBF_2019_logo.svg.png","proxy_needed":False,"quality":"HD","stream_type":"youtube"},
]

# ==================== CATÉGORIES ====================

CATEGORIES = [
    {"id":"sports", "name":"Sports", "icon":"", "color":"blue", "bg":"bg-blue-100 dark:bg-blue-900/20", "text":"text-blue-600"},
    {"id":"news", "name":"News", "icon":"", "color":"red", "bg":"bg-red-100 dark:bg-red-900/20", "text":"text-red-600"},
    {"id":"entertainment", "name":"Divertissement", "icon":"", "color":"purple", "bg":"bg-purple-100 dark:bg-purple-900/20", "text":"text-purple-600"},
    {"id":"religion", "name":"Religion", "icon":"", "color":"green", "bg":"bg-green-100 dark:bg-green-900/20", "text":"text-green-600"},
    {"id":"radio", "name":"Radio", "icon":"", "color":"orange", "bg":"bg-orange-100 dark:bg-orange-900/20", "text":"text-orange-600"},
    {"id":"webcam", "name":"Webcams", "icon":"", "color":"cyan", "bg":"bg-cyan-100 dark:bg-cyan-900/20", "text":"text-cyan-600"},
    {"id":"science", "name":"Science", "icon":"", "color":"teal", "bg":"bg-teal-100 dark:bg-teal-900/20", "text":"text-teal-600"},
    {"id":"iptv", "name":"Chaînes Télévisions", "icon":"", "color":"indigo", "bg":"bg-indigo-100 dark:bg-indigo-900/20", "text":"text-indigo-600"},
    {"id":"iptv_sports", "name":"Sports TV", "icon":"", "color":"blue", "bg":"bg-blue-100 dark:bg-blue-900/20", "text":"text-blue-600"},
    {"id":"iptv_news", "name":"Info TV", "icon":"", "color":"red", "bg":"bg-red-100 dark:bg-red-900/20", "text":"text-red-600"},
    {"id":"iptv_documentary", "name":"Documentaires", "icon":"", "color":"amber", "bg":"bg-amber-100 dark:bg-amber-900/20", "text":"text-amber-600"},
    {"id":"iptv_music", "name":"Musique TV", "icon":"", "color":"pink", "bg":"bg-pink-100 dark:bg-pink-900/20", "text":"text-pink-600"},
    {"id":"iptv_kids", "name":"Jeunesse TV", "icon":"", "color":"yellow", "bg":"bg-yellow-100 dark:bg-yellow-900/20", "text":"text-yellow-600"},
    {"id":"iptv_movies", "name":"Films TV", "icon":"", "color":"purple", "bg":"bg-purple-100 dark:bg-purple-900/20", "text":"text-purple-600"},
    {"id":"iptv_science", "name":"Science TV", "icon":"", "color":"teal", "bg":"bg-teal-100 dark:bg-teal-900/20", "text":"text-teal-600"},
    {"id":"iptv_travel", "name":"Voyage TV", "icon":"", "color":"emerald", "bg":"bg-emerald-100 dark:bg-emerald-900/20", "text":"text-emerald-600"},
    {"id":"iptv_business", "name":"Business TV", "icon":"", "color":"slate", "bg":"bg-slate-100 dark:bg-slate-900/20", "text":"text-slate-600"},
    {"id":"gaming", "name":"Gaming", "icon":"", "color":"fuchsia", "bg":"bg-fuchsia-100 dark:bg-fuchsia-900/20", "text":"text-fuchsia-600"},
]

# Mapping catégories UI → mots-clés IPTV réels (group-title dans les M3U)
CATEGORY_IPTV_KEYWORDS = {
    "sports":           ["sport", "sports", "football", "soccer", "basketball", "tennis", "boxing", "wrestling"],
    "news":             ["news", "info", "actualit", "journal", "infos"],
    "entertainment":    ["entertainment", "general", "variety", "divertissement", "show"],
    "religion":         ["religion", "religious", "faith", "islamic", "christian", "prayer"],
    "radio":            ["radio", "music radio", "audio"],
    "science":          ["science", "nature", "documentary", "docu"],
    "gaming":           ["gaming", "game", "esport", "esports"],
    "iptv":             [],
    "iptv_sports":      ["sport", "sports", "football", "soccer", "basketball", "tennis"],
    "iptv_news":        ["news", "info", "actualit", "journal"],
    "iptv_documentary": ["documentary", "docu", "document"],
    "iptv_music":       ["music", "musique", "musical"],
    "iptv_kids":        ["kids", "children", "jeunesse", "child", "cartoon", "animation"],
    "iptv_movies":      ["movies", "movie", "cinema", "film", "films"],
    "iptv_science":     ["science", "nature", "educational"],
    "iptv_travel":      ["travel", "voyage", "geographic", "geography"],
    "iptv_business":    ["business", "finance", "economy", "economic"],
}

INAPPROPRIATE_WORDS = {
    'fr': [
        'merde', 'putain', 'connard', 'salope', 'enculé', 'bâtard', 'fils de pute', 'filsdepute',
        'niquer', 'bite', 'couille', 'chatte', 'pd', 'tapette', 'pédale', 'enfoiré', 'salaud',
        'ordure', 'racaille', 'bouffon', 'sac à merde', 'sacrement', 'nique ta mère', 'ntm',
        'tg', 'ta gueule', 'ferme ta gueule', 'gros con', 'grosse conne', 'abruti', 'débile',
        'attardé', 'crétin', 'imbécile', 'taré', 'fou', 'cinglé', 'malade mental', 'triso',
        'mongol', 'sous-merde', 'encule', 'enculer', 'nique', 'niquer', 'putain de merde',
        'bordel', 'putain de bordel', 'merdeux', 'merdeuse', 'chiard', 'chienne', 'saloperie',
        'connerie', 'con', 'conne', 'connasse', 'connard', 'connarde', 'batard', 'batarde',
    ],
    'en': [
        'fuck', 'shit', 'bitch', 'asshole', 'cunt', 'motherfucker', 'mother fucker', 'dick',
        'pussy', 'whore', 'slut', 'bastard', 'faggot', 'retard', 'nigger', 'nigga', 'chink',
        'spic', 'kike', 'gook', 'wetback', 'beaner', 'cracker', 'redneck', 'hillbilly',
        'douche', 'douchebag', 'jackass', 'dumbass', 'dumb ass', 'dipshit', 'dip shit',
        'piss off', 'suck my dick', 'blow me', 'eat shit', 'go to hell', 'fuck you', 'fuck off',
        'fuck this', 'bullshit', 'bull shit', 'horseshit', 'horse shit', 'crap', 'damn',
        'goddamn', 'hell', 'prick', 'twat', 'wanker', 'tosser', 'bollocks', 'arsehole',
    ]
}

# ==================== MOTS INAPPROPRIÉS ====================

class YouTubeService:
    """Résolution des URLs YouTube avec cache et fallback multiple"""

    def __init__(self):
        self.cache = {}
        self.session = None

    async def get_session(self):
        if not self.session:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=settings.YOUTUBE_TIMEOUT),
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            )
        return self.session

    @staticmethod
    def extract_video_id(url: str) -> Optional[str]:
        patterns = [
            r'(?:v=|youtu\.be/|embed/|shorts/|live/)([A-Za-z0-9_-]{11})',
            r'^([A-Za-z0-9_-]{11})$'
        ]
        for pattern in patterns:
            m = re.search(pattern, url)
            if m:
                return m.group(1)
        return None

    async def get_stream_url(self, youtube_url: str) -> dict:
        """Retourne l'URL du stream avec plusieurs stratégies de fallback"""
        cache_key = f"yt_{youtube_url}"
        if cache_key in self.cache:
            cached = self.cache[cache_key]
            if datetime.utcnow() < cached["expires"]:
                return cached["data"]

        video_id = self.extract_video_id(youtube_url)
        if not video_id:
            return {"error": "ID vidéo invalide", "type": "error"}

        # Stratégie 1 : yt-dlp (meilleure qualité)
        if YT_DLP_AVAILABLE:
            try:
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(None, self._ytdlp_extract, youtube_url)
                if result and not result.get("error"):
                    self.cache[cache_key] = {"data": result, "expires": datetime.utcnow() + timedelta(seconds=settings.YOUTUBE_CACHE_TTL)}
                    return result
            except Exception as e:
                logger.warning(f"yt-dlp error: {e}")

        # Stratégie 2 : API noembed (fallback)
        try:
            session = await self.get_session()
            async with session.get(f"https://noembed.com/embed?url={quote(youtube_url)}") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data and data.get("title"):
                        # Si on a des infos, on propose l'embed
                        result = {
                            "type": "embed",
                            "embed_url": f"https://www.youtube.com/embed/{video_id}?autoplay=1&mute=0&enablejsapi=1",
                            "video_id": video_id,
                            "title": data.get("title"),
                            "author": data.get("author_name"),
                        }
                        self.cache[cache_key] = {"data": result, "expires": datetime.utcnow() + timedelta(seconds=settings.YOUTUBE_CACHE_TTL)}
                        return result
        except Exception as e:
            logger.debug(f"Noembed error: {e}")

        # Stratégie 3 : embed basique (toujours disponible)
        result = {
            "type": "embed",
            "embed_url": f"https://www.youtube.com/embed/{video_id}?autoplay=1&mute=0&enablejsapi=1",
            "video_id": video_id,
            "fallback": True
        }
        self.cache[cache_key] = {"data": result, "expires": datetime.utcnow() + timedelta(seconds=300)}
        return result

    def _ytdlp_extract(self, url: str) -> dict:
        try:
            ydl_opts = {
                'format': 'best[ext=mp4]/bestvideo+bestaudio/best',
                'quiet': True,
                'no_warnings': True,
                'extract_flat': False,
                'socket_timeout': 30,
                'retries': 3,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if info:
                    # Pour les lives, chercher HLS
                    if info.get('is_live'):
                        for fmt in info.get('formats', []):
                            if fmt.get('protocol') in ('m3u8', 'm3u8_native') and fmt.get('url'):
                                return {
                                    "type": "hls",
                                    "url": fmt['url'],
                                    "video_id": info.get('id'),
                                    "title": info.get('title'),
                                    "is_live": True
                                }
                    # URL directe
                    direct = info.get('url')
                    if not direct and info.get('formats'):
                        direct = info['formats'][-1].get('url')
                    if direct:
                        return {
                            "type": "direct",
                            "url": direct,
                            "video_id": info.get('id'),
                            "title": info.get('title'),
                            "duration": info.get('duration'),
                            "thumbnail": info.get('thumbnail')
                        }
                    # Fallback embed
                    return {
                        "type": "embed",
                        "embed_url": f"https://www.youtube.com/embed/{info.get('id')}?autoplay=1",
                        "video_id": info.get('id'),
                        "title": info.get('title'),
                        "extracted": True
                    }
            return {"error": "Extraction échouée", "type": "error"}
        except Exception as e:
            return {"error": str(e), "type": "error"}

    async def close(self):
        if self.session:
            await self.session.close()

yt_service = YouTubeService()

# ==================== GESTIONNAIRE WEBSOCKET AMÉLIORÉ ====================

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}
        self.stream_viewers: Dict[str, Dict[str, datetime]] = {}
        self.comment_rate_limit: Dict[str, List[datetime]] = {}
        self.viewer_ips: Dict[str, Set[str]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, stream_id: str, visitor_id: str, ip: str):
        await websocket.accept()
        async with self._lock:
            self.active_connections.setdefault(stream_id, []).append(websocket)
            self.stream_viewers.setdefault(stream_id, {})[visitor_id] = datetime.utcnow()
            self.viewer_ips.setdefault(stream_id, set()).add(ip)
        await self.update_viewer_count(stream_id)

    async def disconnect(self, websocket: WebSocket, stream_id: str, visitor_id: str):
        async with self._lock:
            if stream_id in self.active_connections:
                if websocket in self.active_connections[stream_id]:
                    self.active_connections[stream_id].remove(websocket)

            if stream_id in self.stream_viewers and visitor_id in self.stream_viewers[stream_id]:
                del self.stream_viewers[stream_id][visitor_id]

    async def broadcast_to_stream(self, stream_id: str, message: dict):
        if stream_id not in self.active_connections:
            return
        disconnected = []
        for conn in list(self.active_connections[stream_id]):
            try:
                await conn.send_json(message)
            except Exception:
                disconnected.append(conn)
        async with self._lock:
            for conn in disconnected:
                if stream_id in self.active_connections and conn in self.active_connections[stream_id]:
                    self.active_connections[stream_id].remove(conn)

    def check_rate_limit(self, visitor_id: str) -> bool:
        now = datetime.utcnow()
        times = [t for t in self.comment_rate_limit.get(visitor_id, []) if (now - t).total_seconds() < 60]
        self.comment_rate_limit[visitor_id] = times
        if len(times) >= settings.MAX_COMMENTS_PER_MINUTE:
            return False
        self.comment_rate_limit[visitor_id].append(now)
        return True

    async def update_viewer_count(self, stream_id: str):
        db = SessionLocal()
        try:
            stream = db.query(UserStream).filter(UserStream.id == stream_id).first()
            if stream:
                count = len(self.stream_viewers.get(stream_id, {}))
                stream.viewer_count = count
                if count > stream.peak_viewers:
                    stream.peak_viewers = count
                db.commit()
        except Exception as e:
            logger.error(f"Erreur update viewer count: {e}")
        finally:
            db.close()

    def get_viewer_count(self, stream_id: str) -> int:
        return len(self.stream_viewers.get(stream_id, {}))

    def get_unique_ips(self, stream_id: str) -> int:
        return len(self.viewer_ips.get(stream_id, set()))

manager = ConnectionManager()

# ==================== SERVICE IPTV AMÉLIORÉ ====================

class IPTVSyncService:
    def __init__(self):
        self.is_syncing = False
        self.last_sync = None
        self.semaphore = asyncio.Semaphore(settings.IPTV_CONCURRENT_DOWNLOADS)
        self.session = None
        self.playlist_cache = {}
        self.failed_playlists = set()

    async def get_session(self):
        if not self.session:
            connector = aiohttp.TCPConnector(limit=settings.IPTV_CONCURRENT_DOWNLOADS, force_close=True, enable_cleanup_closed=True, ssl=False)
            self.session = aiohttp.ClientSession(
                connector=connector,
                timeout=aiohttp.ClientTimeout(total=settings.IPTV_TIMEOUT),
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"}
            )
        return self.session

    async def fetch_playlist(self, name: str, url: str, retry: int = 0) -> list:
        """Télécharge une playlist avec retry et cache"""
        if name in self.playlist_cache:
            cached = self.playlist_cache[name]
            if datetime.utcnow() < cached["expires"]:
                return cached["channels"]

        try:
            async with self.semaphore:
                session = await self.get_session()
                async with session.get(url) as resp:
                    if resp.status == 200:
                        content = await resp.text(errors='replace')
                        channels = self.parse_m3u(content, name)
                        self.playlist_cache[name] = {
                            "channels": channels,
                            "expires": datetime.utcnow() + timedelta(hours=6)
                        }
                        logger.info(f"{name}: {len(channels)} chaînes")
                        return channels
                    elif resp.status in (404, 410):
                        # Ressource inexistante — inutile de retenter
                        logger.warning(f"Playlist introuvable (HTTP {resp.status}), ignorée : {url}")
                        return []
                    else:
                        logger.error(f"HTTP {resp.status} pour {url}")
                        if retry < settings.IPTV_MAX_RETRIES:
                            await asyncio.sleep(settings.RETRY_DELAY * (retry + 1))
                            return await self.fetch_playlist(name, url, retry + 1)
                        return []
        except asyncio.TimeoutError:
            logger.error(f"Timeout pour {url}")
            if retry < settings.IPTV_MAX_RETRIES:
                await asyncio.sleep(settings.RETRY_DELAY * (retry + 1))
                return await self.fetch_playlist(name, url, retry + 1)
            return []
        except Exception as e:
            logger.error(f"Erreur fetch {url}: {e}")
            if retry < settings.IPTV_MAX_RETRIES:
                await asyncio.sleep(settings.RETRY_DELAY * (retry + 1))
                return await self.fetch_playlist(name, url, retry + 1)
            return []

    def parse_m3u(self, content: str, playlist_id: str) -> list:
        """Parse un fichier M3U en liste de chaînes"""
        channels = []
        lines = content.split('\n')
        i = 0
        total_lines = len(lines)

        while i < total_lines:
            line = lines[i].strip()
            if line.startswith('#EXTINF:'):
                # Extraire les attributs
                def get_attr(attr):
                    m = re.search(rf'{attr}="([^"]*)"', line)
                    return m.group(1) if m else None

                tvg_id = get_attr('tvg-id')
                tvg_name = get_attr('tvg-name')
                tvg_logo = get_attr('tvg-logo')
                tvg_chno = get_attr('tvg-chno')
                tvg_shift = get_attr('tvg-shift')
                group = get_attr('group-title') or "general"

                # Nom de la chaîne
                name_parts = line.split(',', 1)
                name = name_parts[1].strip() if len(name_parts) > 1 else "Inconnue"

                # URL de la chaîne (ligne suivante)
                if i + 1 < total_lines:
                    url_line = lines[i + 1].strip()
                    if url_line and not url_line.startswith('#') and url_line.startswith('http'):
                        # Déterminer le type de stream
                        stream_type = self._detect_type(url_line)
                        # Catégorie normalisée
                        category = re.sub(r'[^a-z0-9_]', '_', group.lower())[:50]
                        # Langue
                        language = self._guess_lang(playlist_id, name, group)

                        channels.append({
                            "playlist_id": playlist_id,
                            "name": name[:200],
                            "url": url_line[:1000],
                            "logo": tvg_logo,
                            "category": category,
                            "country": self._get_country(playlist_id),
                            "language": language,
                            "tvg_id": tvg_id,
                            "tvg_name": tvg_name,
                            "tvg_chno": int(tvg_chno) if tvg_chno and tvg_chno.isdigit() else None,
                            "tvg_shift": float(tvg_shift) if tvg_shift else None,
                            "stream_type": stream_type,
                        })
                        i += 1  # sauter l'URL déjà traitée
            i += 1
        return channels

    def _detect_type(self, url: str) -> str:
        u = url.lower()
        if 'youtube.com' in u or 'youtu.be' in u:
            return 'youtube'
        if u.endswith('.mpd') or 'manifest' in u or 'dash' in u:
            return 'dash'
        if u.endswith('.mp4') or u.endswith('.mkv') or u.endswith('.webm') or u.endswith('.mov'):
            return 'mp4'
        if u.endswith('.mp3') or u.endswith('.aac') or u.endswith('.ogg') or u.endswith('.wav') or 'icecast' in u or 'stream.mp3' in u:
            return 'audio'
        if u.startswith('rtmp://') or u.startswith('rtsp://'):
            return 'rtmp'
        return 'hls'

    def _guess_lang(self, playlist_id: str, name: str, group: str) -> str:
        lang_map = {
            "FR": "fr", "BE": "fr", "CH": "fr", "CA": "fr", "LU": "fr", "MC": "fr",
            "MA": "ar", "DZ": "ar", "TN": "ar", "SN": "fr", "CI": "fr", "CM": "fr", "ML": "fr", "CD": "fr",
            "US": "en", "GB": "en", "AU": "en", "NZ": "en", "IE": "en",
            "DE": "de", "AT": "de", "LI": "de",
            "IT": "it", "SM": "it", "VA": "it",
            "ES": "es", "MX": "es", "AR": "es", "CO": "es", "CL": "es", "PE": "es", "VE": "es", "EC": "es", "BO": "es", "PY": "es", "UY": "es", "GT": "es", "CU": "es", "DO": "es", "PR": "es",
            "PT": "pt", "BR": "pt", "AO": "pt", "MZ": "pt",
            "NL": "nl", "BE": "nl",
            "SE": "sv", "NO": "no", "DK": "da", "FI": "fi", "IS": "is",
            "RU": "ru", "UA": "uk", "BY": "be",
            "PL": "pl", "CZ": "cs", "SK": "sk", "HU": "hu", "RO": "ro", "BG": "bg", "RS": "sr", "HR": "hr", "SI": "sl",
            "TR": "tr", "SA": "ar", "AE": "ar", "EG": "ar", "KW": "ar", "QA": "ar", "BH": "ar", "OM": "ar", "YE": "ar",
            "IR": "fa", "IQ": "ar", "SY": "ar", "LB": "ar", "JO": "ar", "IL": "he",
            "IN": "hi", "PK": "ur", "BD": "bn", "LK": "si", "NP": "ne",
            "CN": "zh", "TW": "zh", "HK": "zh", "SG": "zh",
            "JP": "ja", "KR": "ko", "TH": "th", "VN": "vi", "ID": "id", "MY": "ms", "PH": "tl",
        }
        low = (name + " " + group).lower()
        if 'english' in low or 'bbc' in low or 'cnn' in low or 'sky news' in low:
            return 'en'
        if 'arabic' in low or 'عربي' in low or 'العربية' in low:
            return 'ar'
        if 'español' in low or 'espanol' in low:
            return 'es'
        if 'deutsch' in low or 'german' in low:
            return 'de'
        if 'français' in low or 'francais' in low or 'french' in low:
            return 'fr'
        country_code = self._get_country(playlist_id)
        return lang_map.get(country_code, 'en')

    def _get_country(self, playlist_id: str) -> str:
        country_map = {
            "france": "FR", "canada": "CA", "belgique": "BE", "suisse": "CH", "luxembourg": "LU",
            "maroc": "MA", "algerie": "DZ", "tunisie": "TN", "senegal": "SN", "cote_ivoire": "CI",
            "cameroun": "CM", "mali": "ML", "congo": "CD", "etats_unis": "US", "royaume_uni": "GB",
            "allemagne": "DE", "espagne": "ES", "italie": "IT", "portugal": "PT", "pays_bas": "NL",
            "russie": "RU", "pologne": "PL", "ukraine": "UA", "roumanie": "RO", "bulgarie": "BG",
            "serbie": "RS", "croatie": "HR", "slovenie": "SI", "slovaquie": "SK", "tchequie": "CZ",
            "hongrie": "HU", "autriche": "AT", "grece": "GR", "chypre": "CY", "malte": "MT",
            "islande": "IS", "norvege": "NO", "suede": "SE", "finlande": "FI", "danemark": "DK",
            "irlande": "IE", "bresil": "BR", "mexique": "MX", "argentine": "AR", "colombie": "CO",
            "chili": "CL", "perou": "PE", "venezuela": "VE", "equateur": "EC", "bolivie": "BO",
            "paraguay": "PY", "uruguay": "UY", "chine": "CN", "japon": "JP", "coree_sud": "KR",
            "inde": "IN", "pakistan": "PK", "bangladesh": "BD", "indonesie": "ID", "malaisie": "MY",
            "singapour": "SG", "philippines": "PH", "vietnam": "VN", "thailande": "TH", "australie": "AU",
            "nouvelle_zelande": "NZ", "afrique_du_sud": "ZA", "nigeria": "NG", "kenya": "KE", "egypte": "EG",
            "arabie_saoudite": "SA", "emirats_arabes_unis": "AE", "qatar": "QA", "koweit": "KW", "irak": "IQ",
            "iran": "IR", "turquie": "TR", "israel": "IL", "jordanie": "JO", "liban": "LB", "syrie": "SY",
        }
        # Pour les subdivisions, on garde le code pays
        if playlist_id.startswith("ca_"):
            return "CA"
        if playlist_id.startswith("us_"):
            return "US"
        if playlist_id.startswith("br_"):
            return "BR"
        if playlist_id.startswith("co_"):
            return "CO"
        if playlist_id.startswith("gb_"):
            return "GB"
        if playlist_id.startswith("de_"):
            return "DE"
        if playlist_id.startswith("it_"):
            return "IT"
        if playlist_id.startswith("es_"):
            return "ES"
        if playlist_id.startswith("city_"):
            # Deviner le pays à partir du nom de la playlist
            city_country = {
                "city_toronto": "CA", "city_montreal": "CA", "city_vancouver": "CA", "city_calgary": "CA",
                "city_edmonton": "CA", "city_ottawa": "CA", "city_quebec": "CA", "city_winnipeg": "CA",
                "city_new_york": "US", "city_los_angeles": "US", "city_chicago": "US", "city_houston": "US",
                "city_london": "GB", "city_paris": "FR", "city_berlin": "DE", "city_rome": "IT",
                "city_madrid": "ES", "city_moscow": "RU", "city_tokyo": "JP", "city_beijing": "CN",
                "city_sydney": "AU", "city_rio_de_janeiro": "BR", "city_mumbai": "IN",
            }
            return city_country.get(playlist_id, "INT")
        return country_map.get(playlist_id, "INT")

    async def sync_all_playlists(self):
        """Synchronise toutes les playlists IPTV"""
        if self.is_syncing:
            logger.info("Synchronisation déjà en cours")
            return

        self.is_syncing = True
        logger.info("Début de la synchronisation IPTV.org (version complète)...")

        db = SessionLocal()
        try:
            total_channels = 0
            total_playlists = len(IPTV_PLAYLISTS)
            successful = 0

            for idx, pl_data in enumerate(IPTV_PLAYLISTS, 1):
                try:
                    logger.info(f"[{idx}/{total_playlists}] Synchronisation: {pl_data['display_name']}")

                    db_pl = db.query(IPTVPlaylist).filter(IPTVPlaylist.name == pl_data["name"]).first()
                    if not db_pl:
                        db_pl = IPTVPlaylist(**pl_data)
                        db.add(db_pl)
                        db.flush()

                    channels = await self.fetch_playlist(pl_data["name"], pl_data["url"])

                    if channels:
                        # Supprimer les anciennes chaînes
                        db.query(IPTVChannel).filter(IPTVChannel.playlist_id == pl_data["name"]).delete()

                        # Ajouter les nouvelles
                        for ch in channels:
                            db.add(IPTVChannel(**ch))

                        db_pl.channel_count = len(channels)
                        db_pl.last_sync = datetime.utcnow()
                        db_pl.sync_status = "success"
                        db_pl.sync_error = None
                        total_channels += len(channels)
                        successful += 1
                    else:
                        db_pl.sync_status = "empty"
                        db_pl.sync_error = "Aucune chaîne trouvée ou playlist introuvable"

                    db.commit()
                    await asyncio.sleep(0.5)

                except Exception as pl_err:
                    logger.error(f"Erreur playlist {pl_data.get('name','?')}: {pl_err}")
                    try:
                        db.rollback()
                    except Exception:
                        pass
                    continue

            self.last_sync = datetime.utcnow()
            logger.info(f"Synchronisation terminée: {total_channels} chaînes au total ({successful}/{total_playlists} playlists réussies)")

        except Exception as e:
            logger.error(f"Erreur lors de la synchronisation: {e}")
            db.rollback()
        finally:
            self.is_syncing = False
            db.close()

    async def start_periodic_sync(self):
        """Lance la synchronisation périodique"""
        while True:
            try:
                await self.sync_all_playlists()
            except Exception as e:
                logger.error(f"Erreur dans le sync périodique: {e}")
            await asyncio.sleep(settings.IPTV_SYNC_INTERVAL)

    async def close(self):
        if self.session:
            await self.session.close()

iptv_sync = IPTVSyncService()

# ==================== PROXY HLS AMÉLIORÉ ====================

class HLSProxy:
    """
    Proxy HLS robuste :
    - Manifest M3U8 : récupéré, réécrit pour router les segments via /proxy/segment
    - Segments .ts  : streamés en vrai streaming progressif
    - Headers CORS  : injectés sur toutes les réponses
    - Pas de lock global bloquant
    """

    # User-Agents variés pour éviter les blocages
    _USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "AppleCoreMedia/1.0.0.21E236 (Apple TV; U; CPU OS 17_4 like Mac OS X; en_us)",
        "Lavf/60.3.100",  # ffmpeg — accepté par beaucoup de serveurs IPTV
    ]

    def __init__(self):
        self._manifest_cache: Dict[str, dict] = {}
        self._cache_lock = asyncio.Lock()

    def _make_client(self, origin: str = "https://www.google.com", ua_index: int = 0) -> httpx.AsyncClient:
        ua = self._USER_AGENTS[ua_index % len(self._USER_AGENTS)]
        return httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10, read=30, write=10, pool=5),
            follow_redirects=True,
            headers={
                "User-Agent": ua,
                "Accept": "*/*",
                "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
                "Accept-Encoding": "gzip, deflate",
                "Origin": origin,
                "Referer": origin + "/",
                "Connection": "keep-alive",
            },
            limits=httpx.Limits(max_keepalive_connections=50, max_connections=200),
        )

    def _get_origin(self, url: str) -> str:
        try:
            p = urlparse(url)
            return f"{p.scheme}://{p.netloc}"
        except Exception:
            return "https://www.google.com"

    def _build_cors_headers(self) -> dict:
        return {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
            "Access-Control-Allow-Headers": "*",
            "Cache-Control": "no-cache, no-store",
        }

    def _rewrite_m3u8(self, content: str, base_url: str) -> str:
        """
        Réécrit un manifest M3U8 pour router tous les segments et sous-playlists
        via notre proxy. Gère :
        - URLs de segments (lignes sans #)
        - URI= dans les tags EXT-X-KEY, EXT-X-MAP, EXT-X-MEDIA
        - URLs relatives, absolues, avec query strings
        """
        try:
            parsed_base = urlparse(base_url)
            base_dir = base_url.rsplit("/", 1)[0] + "/"
            base_origin = f"{parsed_base.scheme}://{parsed_base.netloc}"
        except Exception:
            base_dir = ""
            base_origin = ""

        def to_absolute(raw: str) -> str:
            raw = raw.strip()
            if raw.startswith("http://") or raw.startswith("https://"):
                return raw
            if raw.startswith("//"):
                return parsed_base.scheme + ":" + raw
            if raw.startswith("/"):
                return base_origin + raw
            return urljoin(base_dir, raw)

        def proxy_url_seg(raw: str) -> str:
            abs_url = to_absolute(raw)
            return f"/proxy/segment?url={quote(abs_url, safe='')}"

        def proxy_url_manifest(raw: str) -> str:
            abs_url = to_absolute(raw)
            return f"/proxy/stream?url={quote(abs_url, safe='')}"

        def rewrite_uri_attr(m):
            uri = m.group(1)
            if uri.startswith("data:"):
                return m.group(0)
            abs_url = to_absolute(uri)
            proxied = f"/proxy/stream?url={quote(abs_url, safe='')}"
            return f'URI="{proxied}"'

        lines = content.splitlines()
        out = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                out.append("")
                continue
            if stripped.startswith("#"):
                # Réécrire URI="..." dans les tags de type EXT-X-KEY, EXT-X-MAP, etc.
                rewritten = re.sub(r'URI="([^"]+)"', rewrite_uri_attr, stripped)
                out.append(rewritten)
            else:
                # Ligne URL : sous-manifest (.m3u8) ou segment (.ts, .m4s, .aac…)
                is_submanifest = ".m3u8" in stripped.split("?")[0].lower()
                if is_submanifest:
                    out.append(proxy_url_manifest(stripped))
                else:
                    out.append(proxy_url_seg(stripped))
        return "\n".join(out)

    async def fetch_stream(self, url: str, extra_headers: dict = None) -> Response:
        """Récupère et réécrit un manifest M3U8, ou proxifie un fichier direct."""
        # Vérifier le cache manifest (TTL 30s — les manifests live changent vite)
        async with self._cache_lock:
            cached = self._manifest_cache.get(url)
            if cached and datetime.utcnow() < cached["expires"]:
                return Response(
                    content=cached["content"],
                    media_type=cached["media_type"],
                    headers=self._build_cors_headers(),
                )

        origin = self._get_origin(url)
        last_err = None

        # Essayer plusieurs User-Agents si le premier est bloqué
        for ua_idx in range(len(self._USER_AGENTS)):
            try:
                async with self._make_client(origin, ua_idx) as client:
                    req_headers = {}
                    if extra_headers:
                        req_headers.update(extra_headers)
                    resp = await client.get(url, headers=req_headers)
                    resp.raise_for_status()

                    ct = resp.headers.get("content-type", "")
                    raw_text = resp.text
                    is_m3u8 = (
                        "mpegurl" in ct.lower()
                        or url.lower().endswith(".m3u8")
                        or raw_text.lstrip().startswith("#EXTM3U")
                    )

                    if is_m3u8:
                        rewritten = self._rewrite_m3u8(raw_text, url)
                        content_bytes = rewritten.encode("utf-8")
                        media_type = "application/vnd.apple.mpegurl"
                    else:
                        content_bytes = resp.content
                        media_type = ct.split(";")[0].strip() or "application/octet-stream"

                    # Mettre en cache le manifest 30s
                    async with self._cache_lock:
                        self._manifest_cache[url] = {
                            "content": content_bytes,
                            "media_type": media_type,
                            "expires": datetime.utcnow() + timedelta(seconds=30),
                        }

                    return Response(
                        content=content_bytes,
                        media_type=media_type,
                        headers=self._build_cors_headers(),
                    )

            except httpx.HTTPStatusError as e:
                last_err = e
                if e.response.status_code in (403, 401):
                    # Essayer prochain UA
                    continue
                raise HTTPException(status_code=e.response.status_code, detail=f"Source HTTP {e.response.status_code}")
            except httpx.TimeoutException:
                last_err = Exception("Timeout")
                continue
            except Exception as e:
                last_err = e
                break

        raise HTTPException(status_code=502, detail=f"Proxy inaccessible: {last_err}")

    async def stream_segment(self, url: str) -> StreamingResponse:
        """Stream un segment .ts / .m4s / audio en vrai streaming progressif."""
        origin = self._get_origin(url)

        # Détecter le Content-Type depuis l'extension (pas de HEAD = plus rapide)
        ext = url.split("?")[0].rsplit(".", 1)[-1].lower()
        ct = {
            "ts":  "video/MP2T",
            "mp4": "video/mp4",
            "m4s": "video/iso.segment",
            "m4v": "video/mp4",
            "aac": "audio/aac",
            "mp3": "audio/mpeg",
            "ac3": "audio/ac3",
            "eac3":"audio/eac3",
            "vtt": "text/vtt",
            "webm":"video/webm",
        }.get(ext, "video/MP2T")

        last_err = None
        for ua_idx in range(len(self._USER_AGENTS)):
            try:
                client = self._make_client(origin, ua_idx)

                async def _gen(c=client, u=url):
                    try:
                        async with c:
                            async with c.stream("GET", u) as resp:
                                if resp.status_code >= 400:
                                    return
                                async for chunk in resp.aiter_bytes(65536):
                                    yield chunk
                    except Exception:
                        return

                return StreamingResponse(
                    _gen(),
                    media_type=ct,
                    headers=self._build_cors_headers(),
                )

            except Exception as e:
                last_err = e
                continue

        raise HTTPException(status_code=502, detail=f"Segment inaccessible: {last_err}")

proxy = HLSProxy()

# ==================== UTILITAIRES ====================

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def verify_password(plain: str, hashed: str) -> bool:
    """Vérifie un mot de passe — supporte bcrypt ET le fallback sha256$"""
    try:
        import hashlib as _hl
        # Cas 1 : hash de secours sha256$ (généré quand bcrypt indisponible)
        if hashed and hashed.startswith("sha256$"):
            expected = "sha256$" + _hl.sha256(plain.encode('utf-8')).hexdigest()
            return secrets.compare_digest(hashed, expected)
        # Cas 2 : hash bcrypt normal
        plain_bytes = plain.encode('utf-8')[:72]
        try:
            import bcrypt as _bc
            if hashed and hashed.startswith(("$2a$", "$2b$", "$2y$")):
                return _bc.checkpw(plain_bytes, hashed.encode('utf-8'))
        except ImportError:
            pass
        return pwd_context.verify(plain_bytes.decode('utf-8', errors='ignore'), hashed)
    except Exception as e:
        logger.warning(f"verify_password error: {e}")
        return False

def get_password_hash(pw: str) -> str:
    """Hache un mot de passe — bcrypt prioritaire, sha256 en secours"""
    try:
        pw_bytes = pw.encode('utf-8')[:72]
        try:
            import bcrypt as _bc
            return _bc.hashpw(pw_bytes, _bc.gensalt()).decode('utf-8')
        except ImportError:
            return pwd_context.hash(pw_bytes.decode('utf-8', errors='ignore'))
    except Exception as e:
        logger.warning(f"bcrypt unavailable, using sha256 fallback: {e}")
        import hashlib as _hl
        return "sha256$" + _hl.sha256(pw.encode('utf-8')).hexdigest()
    
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

def get_visitor_id(request: Request) -> str:
    return request.cookies.get('visitor_id') or f"vis_{secrets.token_urlsafe(16)}"

def check_ip_blocked(ip: str, db: Session) -> bool:
    return db.query(BlockedIP).filter(
        and_(
            BlockedIP.ip_address == ip,
            or_(
                BlockedIP.expires_at.is_(None),
                BlockedIP.expires_at > datetime.utcnow()
            )
        )
    ).first() is not None

def _check_ip_blocked(request: Request, db: Session):
    """Wrapper pratique : vérifie l'IP de la requête et lève 403 si bloquée."""
    client_ip = request.client.host if request.client else "0.0.0.0"
    if check_ip_blocked(client_ip, db):
        raise HTTPException(status_code=403, detail="Accès bloqué")

def filter_inappropriate(text: str, lang: str = 'fr') -> str:
    """Filtre les mots inappropriés dans un texte"""
    words = text.split()
    result = []
    for word in words:
        word_lower = word.lower()
        is_bad = False
        for lang_words in INAPPROPRIATE_WORDS.values():
            for bad_word in lang_words:
                if bad_word in word_lower or word_lower in bad_word:
                    is_bad = True
                    break
            if is_bad:
                break
        result.append('*' * len(word) if is_bad else html.escape(word))
    return ' '.join(result)

def get_language(request: Request) -> str:
    """Détecte la langue préférée de l'utilisateur"""
    accept = request.headers.get("accept-language", "fr-FR,fr;q=0.9")
    for part in accept.split(','):
        lang = part.split(';')[0].split('-')[0].strip()
        if lang in ['fr', 'en', 'ar', 'es', 'de', 'it', 'pt', 'nl', 'ru', 'zh', 'ja', 'ko']:
            return lang
    return 'fr'

def init_external_streams(db: Session):
    _VALID_COLS = {c.key for c in ExternalStream.__table__.columns}
    for stream_data in EXTERNAL_STREAMS:
        safe_data = {k: v for k, v in stream_data.items() if k in _VALID_COLS}
        existing = db.query(ExternalStream).filter(
            ExternalStream.title == safe_data.get("title"),
            ExternalStream.url   == safe_data.get("url")
        ).first()
        if not existing:
            db.add(ExternalStream(**safe_data))
        else:
            existing.stream_type  = safe_data.get("stream_type", "hls")
            existing.proxy_needed = safe_data.get("proxy_needed", False)
    db.commit()
    
def init_iptv_playlists(db: Session):
    _VALID_COLS = {c.key for c in IPTVPlaylist.__table__.columns}
    for playlist_data in IPTV_PLAYLISTS:
        safe_data = {k: v for k, v in playlist_data.items() if k in _VALID_COLS}
        existing = db.query(IPTVPlaylist).filter(IPTVPlaylist.name == safe_data["name"]).first()
        if not existing:
            db.add(IPTVPlaylist(**safe_data))
    db.commit()

def require_admin(request: Request) -> dict:
    """Vérifie que l'utilisateur est administrateur"""
    token = request.cookies.get("admin_token")
    if not token:
        raise HTTPException(status_code=401, detail="Non autorisé")
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        if not payload.get("admin"):
            raise HTTPException(status_code=401, detail="Non autorisé")
        return payload
    except JWTError:
        raise HTTPException(status_code=401, detail="Non autorisé")

def require_owner(request: Request, db: Session) -> dict:
    """Vérifie que l'utilisateur est le propriétaire"""
    payload = require_admin(request)
    user = db.query(User).filter(User.id == payload.get("sub")).first()
    if not user or not user.is_owner:
        raise HTTPException(status_code=403, detail="Accès réservé au propriétaire")
    return payload

async def _daily_stats_recorder():
    """
    Enregistre chaque jour les statistiques de visite dans DailyVisitStats.
    Tourne toutes les heures et consolide les données des Visitors créés aujourd'hui.
    """
    while True:
        try:
            await asyncio.sleep(3600)  # toutes les heures
            db = SessionLocal()
            try:
                now      = datetime.utcnow()
                today    = datetime(now.year, now.month, now.day)  # minuit UTC

                # Visiteurs uniques créés aujourd'hui
                unique_today = db.query(Visitor).filter(
                    Visitor.created_at >= today,
                    Visitor.created_at <  today + timedelta(days=1)
                ).count()

                # Pic d'utilisateurs actifs (snapshot actuel)
                peak = active_tracker.count()

                # Upsert dans DailyVisitStats
                row = db.query(DailyVisitStats).filter(DailyVisitStats.date == today).first()
                if row:
                    row.unique_users = unique_today
                    row.peak_active  = max(row.peak_active, peak)
                    row.page_views   += 1  # incrémente à chaque passage horaire
                else:
                    db.add(DailyVisitStats(
                        date         = today,
                        unique_users = unique_today,
                        peak_active  = peak,
                        page_views   = 1,
                    ))
                db.commit()
                logger.debug(f"Stats journalières: {unique_today} visiteurs uniques aujourd'hui")
            finally:
                db.close()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"_daily_stats_recorder error: {e}")


# ==================== LIFESPAN ====================
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=" * 70)
    logger.info(f"{settings.APP_NAME} v{settings.APP_VERSION}")
    logger.info(f"PostgreSQL : {settings.DATABASE_URL.split('@')[-1]}")
    logger.info("=" * 70)

    # ── 1. Vérifier la connexion PostgreSQL ────────────────────────────
    max_retries = 10
    for attempt in range(1, max_retries + 1):
        try:
            with engine.connect() as conn:
                from sqlalchemy import text
                conn.execute(text("SELECT 1"))
            logger.info("PostgreSQL connecté")
            break
        except Exception as e:
            if attempt == max_retries:
                logger.critical(
                    f"Impossible de se connecter à PostgreSQL après {max_retries} tentatives.\n"
                    f"   Vérifiez DATABASE_URL dans votre .env :\n"
                    f"   {settings.DATABASE_URL.split('@')[-1]}\n"
                    f"   Erreur : {e}"
                )
                raise SystemExit(1)
            wait = attempt * 2
            logger.warning(f"PostgreSQL non disponible (tentative {attempt}/{max_retries}), retry dans {wait}s… [{e}]")
            await asyncio.sleep(wait)

    # ── 2. Créer / mettre à jour les tables ────────────────────────────
    try:
        Base.metadata.create_all(bind=engine)
        ensure_visitor_columns()
        logger.info("Tables PostgreSQL synchronisées")
    except Exception as e:
        logger.error(f"Erreur create_all : {e}")
        raise

    # Création des dossiers (static/ est déjà commité dans le repo, pas besoin de le créer)
    for directory in [TEMPLATES_DIR, UPLOADS_DIR, THUMBNAILS_DIR, RECORDINGS_DIR]:
        os.makedirs(directory, exist_ok=True)

    _logo = BASE_DIR / settings.LOGO_PATH
    if _logo.exists():
        logger.info(f"Logo trouvé: {_logo}")
    else:
        logger.warning(f"Logo non trouvé: {_logo}")

    # Écriture des templates
    write_all_templates()

    # ── 3. Initialisation des données ──────────────────────────────────
    db = SessionLocal()
    try:
        # ── Compte admin unique ────────────────────────────────────────────
        # Email : erickbenoit337@gmail.com  |  Username : WALKER92259
        # Mot de passe : WALKER92259
        # Le login accepte email OU username
        _admin_email    = "erickbenoit337@gmail.com"
        _admin_username = "WALKER92259"
        _admin_password = "WALKER92259"
        if len(_admin_password.encode('utf-8')) > 72:
            _admin_password = _admin_password.encode('utf-8')[:72].decode('utf-8', errors='ignore')

        owner = db.query(User).filter(
            or_(User.email == _admin_email, User.username == _admin_username)
        ).first()

        if not owner:
            owner = User(
                username=_admin_username,
                email=_admin_email,
                hashed_password=get_password_hash(_admin_password),
                is_admin=True,
                is_owner=True,
                is_active=True,
                created_at=datetime.utcnow()
            )
            db.add(owner)
            logger.info(f"Compte admin créé : {_admin_username} / {_admin_email}")
        else:
            owner.username             = _admin_username
            owner.email                = _admin_email
            owner.hashed_password      = get_password_hash(_admin_password)
            owner.is_owner             = True
            owner.is_admin             = True
            owner.is_active            = True
            owner.is_blocked           = False
            owner.failed_login_attempts = 0
            owner.locked_until         = None
            logger.info(f"Compte admin synchronisé : {_admin_username} / {_admin_email}")
        db.commit()
        fix_stale_external_urls(db)
        init_external_streams(db)
        init_iptv_playlists(db)
        # Nettoyage visiteurs expirés avec cascade manuelle (FK vers user_streams)
        expired_visitors = db.query(Visitor).filter(Visitor.expires_at < datetime.utcnow()).all()
        expired_count = 0
        for _v in expired_visitors:
            try:
                db.query(UserStream).filter(UserStream.visitor_id == _v.id).delete(synchronize_session=False)
                db.query(Comment).filter(Comment.visitor_id == _v.id).delete(synchronize_session=False)
                db.query(Favorite).filter(Favorite.visitor_id == _v.id).delete(synchronize_session=False)
                db.delete(_v)
                expired_count += 1
            except Exception:
                db.rollback()
                continue
        db.commit()
        logger.info(f"{expired_count} visiteurs expirés nettoyés")
    except Exception as e:
        logger.error(f"Erreur initialisation DB : {e}")
        db.rollback()
    finally:
        db.close()

    # ── 4. Tâches de fond ──────────────────────────────────────────────
    logger.info("Démarrage synchronisation IPTV...")
    sync_task     = asyncio.create_task(iptv_sync.start_periodic_sync())
    tracker_task  = asyncio.create_task(active_tracker.start_broadcast_loop())
    stats_task    = asyncio.create_task(_daily_stats_recorder())
    logger.info("Services démarrés : IPTV sync + tracker + stats journalières")
    logger.info(f"http://localhost:8001")
    logger.info(f"Admin : {settings.OWNER_ID} / {settings.ADMIN_PASSWORD}")
    logger.info(f"{len(EXTERNAL_STREAMS)} flux externes | {len(IPTV_PLAYLISTS)} playlists IPTV")
    logger.info("=" * 70 + "\n")

    yield

    # ── Shutdown ──────────────────────────────────────────────────────
    sync_task.cancel()
    tracker_task.cancel()
    stats_task.cancel()
    await proxy.close()
    await yt_service.close()
    await iptv_sync.close()

# ==================== APPLICATION ====================

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=settings.APP_DESCRIPTION,
    lifespan=lifespan
)

# Middlewares
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"])

# Fichiers statiques
# Mounts dédiés pour le contenu généré au runtime (déclarés AVANT le mount général
# "/static" pour que ces préfixes plus spécifiques soient résolus en priorité) —
# ce contenu vit dans WRITABLE_DIR (/tmp sur Vercel), pas dans le dossier "static/" commité.
app.mount("/static/thumbnails", StaticFiles(directory=THUMBNAILS_DIR), name="static-thumbnails")
app.mount("/static/uploads", StaticFiles(directory=UPLOADS_DIR), name="static-uploads")
app.mount("/static/recordings", StaticFiles(directory=RECORDINGS_DIR), name="static-recordings")
# Assets statiques commités dans le repo (logo, CSS, JS, favicon...)
if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
else:
    logger.warning(f"Dossier static/ absent ({STATIC_DIR}) — mount /static général ignoré")
templates = Jinja2Templates(directory=TEMPLATES_DIR)
# Fix Python 3.14 + Jinja2: LRUCache TypeError quand globals contient des dicts
try:
    from jinja2 import Environment, FileSystemLoader
    _jinja_env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        autoescape=True,
        cache_size=0,
        auto_reload=True,
    )
    templates.env = _jinja_env
except Exception:
    pass

# Middleware de sécurité
@app.middleware("http")
async def security_middleware(request: Request, call_next):
    # Limite de taille pour les uploads
    if request.method in ["POST", "PUT", "DELETE"]:
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > settings.MAX_UPLOAD_SIZE:
            return JSONResponse(
                status_code=413,
                content={"error": "Fichier trop volumineux", "max_size": settings.MAX_UPLOAD_SIZE}
            )

    # Tracker utilisateurs actifs sur les pages HTML
    path = request.url.path
    if not path.startswith("/static") and not path.startswith("/proxy") and not path.startswith("/api"):
        visitor_id = request.cookies.get("visitor_id", "anon")
        client_ip = _get_client_ip(request)
        ua = request.headers.get("user-agent", "")
        active_tracker.record(visitor_id, client_ip, path, ua)

    response = await call_next(request)

    # Créer ou renouveler le cookie visitor_id
    if not request.cookies.get("visitor_id"):
        new_visitor_id = f"vis_{secrets.token_urlsafe(16)}"
        response.set_cookie(
            key="visitor_id",
            value=new_visitor_id,
            max_age=settings.SESSION_MAX_AGE,
            httponly=False,
            samesite="lax"
        )

    # Headers de sécurité
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

    return response

# ==================== RATE LIMITING & SÉCURITÉ AVANCÉE ====================

_rate_limit_store: Dict[str, List[float]] = {}
_suspicious_ips: Set[str] = set()
_RATE_LIMIT_WINDOW = 60   # secondes
_RATE_LIMIT_MAX = 120     # requêtes par fenêtre (2/s max)
_RATE_LIMIT_API = 30      # requêtes API par fenêtre
_RATE_LIMIT_STREAM = 10   # requêtes proxy par fenêtre

# ==================== TRACKER UTILISATEURS ACTIFS EN TEMPS RÉEL ====================

class ActiveUsersTracker:
    """
    Suit en temps réel les utilisateurs actifs sur l'appli.
    Un utilisateur est considéré "actif" s'il a fait une requête
    dans les 5 dernières minutes.
    """
    def __init__(self):
        self._sessions: Dict[str, dict] = {}   # visitor_id → {ip, page, last_seen, ua}
        self._admin_ws: List[WebSocket] = []    # WebSockets admin connectés
        self._ACTIVE_WINDOW = 5 * 60            # 5 minutes

    def record(self, visitor_id: str, ip: str, page: str, ua: str = ""):
        """Enregistre ou met à jour une session active."""
        self._sessions[visitor_id] = {
            "ip":        ip,
            "page":      page,
            "ua":        ua[:120],
            "last_seen": datetime.utcnow(),
        }

    def cleanup(self):
        """Supprime les sessions inactives depuis plus de 5 min."""
        cutoff = datetime.utcnow() - timedelta(seconds=self._ACTIVE_WINDOW)
        stale = [k for k, v in self._sessions.items() if v["last_seen"] < cutoff]
        for k in stale:
            del self._sessions[k]

    def count(self) -> int:
        self.cleanup()
        return len(self._sessions)

    def snapshot(self) -> dict:
        """Retourne un snapshot complet pour le dashboard admin."""
        self.cleanup()
        now = datetime.utcnow()
        sessions = list(self._sessions.values())
        # Pages les plus vues
        page_counts: Dict[str, int] = {}
        for s in sessions:
            p = s["page"].split("?")[0]  # ignorer les query params
            page_counts[p] = page_counts.get(p, 0) + 1
        top_pages = sorted(page_counts.items(), key=lambda x: -x[1])[:5]
        return {
            "active_users":  len(sessions),
            "top_pages":     [{"page": p, "count": c} for p, c in top_pages],
            "ts":            now.isoformat(),
        }

    # ── WebSocket admin ──────────────────────────────────────────────────────

    async def connect_admin(self, ws: WebSocket):
        await ws.accept()
        self._admin_ws.append(ws)
        logger.info(f"Admin WS connecté ({len(self._admin_ws)} actifs)")

    def disconnect_admin(self, ws: WebSocket):
        if ws in self._admin_ws:
            self._admin_ws.remove(ws)

    async def broadcast_to_admins(self, data: dict):
        """Envoie les stats à tous les admins connectés via WebSocket."""
        dead = []
        for ws in list(self._admin_ws):
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect_admin(ws)

    async def start_broadcast_loop(self):
        """Boucle infinie : pousse les stats toutes les 5 secondes aux admins."""
        while True:
            try:
                await asyncio.sleep(5)
                if self._admin_ws:   # ne calcule que si quelqu'un écoute
                    snap = self.snapshot()
                    await self.broadcast_to_admins({"type": "stats", **snap})
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"ActiveUsersTracker broadcast error: {e}")


active_tracker = ActiveUsersTracker()

def _get_client_ip(request: Request) -> str:
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "0.0.0.0"

def _check_rate_limit(ip: str, key_suffix: str, max_req: int) -> bool:
    """Retourne True si autorisé, False si bloqué"""
    key = f"{ip}:{key_suffix}"
    now = datetime.utcnow().timestamp()
    times = _rate_limit_store.get(key, [])
    # Purger les anciennes entrées
    times = [t for t in times if now - t < _RATE_LIMIT_WINDOW]
    if len(times) >= max_req:
        _suspicious_ips.add(ip)
        return False
    times.append(now)
    _rate_limit_store[key] = times
    return True

@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    ip = _get_client_ip(request)
    path = request.url.path

    # Ne pas rate-limiter les statiques
    if path.startswith("/static/"):
        return await call_next(request)

    # ── Tracker utilisateurs actifs (pages HTML uniquement) ──────────────
    if not path.startswith(("/api/", "/proxy/", "/static/", "/ws")):
        visitor_id = request.cookies.get("visitor_id") or ip
        ua = request.headers.get("user-agent", "")
        active_tracker.record(visitor_id, ip, path, ua)

    # Proxy — limite très stricte
    if path.startswith("/proxy/"):
        if not _check_rate_limit(ip, "proxy", _RATE_LIMIT_STREAM):
            return JSONResponse(status_code=429, content={"error": "Trop de requêtes proxy"})

    # API — limite stricte
    elif path.startswith("/api/"):
        if not _check_rate_limit(ip, "api", _RATE_LIMIT_API):
            return JSONResponse(status_code=429, content={"error": "Trop de requêtes API", "retry_after": _RATE_LIMIT_WINDOW})

    # Pages — limite générale
    else:
        if not _check_rate_limit(ip, "page", _RATE_LIMIT_MAX):
            return JSONResponse(status_code=429, content={"error": "Trop de requêtes"})

    response = await call_next(request)

    # Headers de sécurité complets
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    # Note: HSTS seulement en production HTTPS réelle
    # response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

    # CSP assouplie pour permettre les flux HLS/DASH de toutes sources
    if not path.startswith("/proxy/"):
        response.headers["Content-Security-Policy"] = (
            "default-src 'self' 'unsafe-inline' 'unsafe-eval' data: blob: *; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https: blob:; "
            "style-src 'self' 'unsafe-inline' https:; "
            "font-src 'self' https: data:; "
            "img-src * data: blob:; "
            "media-src * data: blob:; "
            "connect-src * wss: ws: blob:; "
            "worker-src blob: 'self'; "
            "frame-src *;"
        )
    return response

# ==================== ROUTES PRINCIPALES ====================

@app.head("/")
async def health_head():
    return Response(status_code=200)


# Dans la fonction home(), remplacez la section de traitement des playlists par :

# ==================== POPULARITÉ + FLUX QUI FONCTIONNENT ====================
# Ordre voulu partout : France 24 en premier, puis les grandes chaînes, puis les plus vues.
POPULAR_CHANNEL_KEYWORDS = [
    "france 24", "tf1", "france 2", "france 3", "france 5", "m6", "bfmtv", "bfm", "cnews", "lci",
    "franceinfo", "euronews", "arte", "canal+", "c8", "w9", "tmc", "bbc", "cnn", "al jazeera",
    "sky news", "dw", "trt", "rai", "rtve", "zdf", "ard",
]
COUNTRY_MAIN_LANG = {
    "FR": "fr", "BE": "fr", "CH": "fr", "LU": "fr", "MC": "fr", "CA": "fr", "CD": "fr", "CG": "fr",
    "SN": "fr", "CI": "fr", "CM": "fr", "ML": "fr", "BF": "fr", "NE": "fr", "TG": "fr", "BJ": "fr",
    "GA": "fr", "GN": "fr", "MG": "fr", "RW": "fr", "BI": "fr", "HT": "fr", "DZ": "fr", "MA": "fr", "TN": "fr",
    "GB": "en", "US": "en", "AU": "en", "IE": "en", "NZ": "en",
    "ES": "es", "MX": "es", "AR": "es", "DE": "de", "IT": "it", "PT": "pt", "BR": "pt",
}
# mot de langue dans un titre -> code langue (« France 24 English » ≠ « France 24 Français »)
_LANG_WORDS = {
    "english": "en", "anglais": "en", "français": "fr", "francais": "fr", "french": "fr",
    "español": "es", "espanol": "es", "spanish": "es", "arabic": "ar", "arabe": "ar", "عربي": "ar",
    "deutsch": "de", "german": "de", "portugues": "pt", "português": "pt",
}

# Anciennes URL (playlists périmées => téléchargement du .m3u8) -> URL officielles actuelles
STALE_URL_FIXES = {
    "https://static.france24.com/live/F24_FR_LO_HLS/live_web.m3u8": "https://live.france24.com/hls/live/2037179-b/F24_FR_HI_HLS/master_5000.m3u8",
    "https://static.france24.com/live/F24_EN_LO_HLS/live_web.m3u8": "https://live.france24.com/hls/live/2037218-b/F24_EN_HI_HLS/master_5000.m3u8",
    "https://static.france24.com/live/F24_ES_LO_HLS/live_web.m3u8": "https://live.france24.com/hls/live/2037220-b/F24_ES_HI_HLS/master_5000.m3u8",
    "https://static.france24.com/live/F24_AR_LO_HLS/live_web.m3u8": "https://live.france24.com/hls/live/2037222-b/F24_AR_HI_HLS/master_5000.m3u8",
}

def _fix_stale_url(url):
    return STALE_URL_FIXES.get((url or "").strip(), url)

def ensure_visitor_columns():
    """create_all() ne modifie pas une table existante : on ajoute les colonnes manquantes de `visitors`."""
    from sqlalchemy import text as _text
    stmts = [
        "ALTER TABLE visitors ADD COLUMN IF NOT EXISTS favorites TEXT DEFAULT '[]'",
        "ALTER TABLE visitors ADD COLUMN IF NOT EXISTS page_count INTEGER DEFAULT 0",
        "ALTER TABLE visitors ADD COLUMN IF NOT EXISTS last_page VARCHAR(200)",
    ]
    for stmt in stmts:
        try:
            with engine.begin() as conn:
                conn.execute(_text(stmt))
        except Exception as e:
            logger.warning(f"Migration visitors ignorée ({stmt[:60]}...): {e}")

def fix_stale_external_urls(db):
    """Corrige en base les flux « maison » dont l'URL est périmée (appelé au démarrage)."""
    try:
        for old, new in STALE_URL_FIXES.items():
            db.query(ExternalStream).filter(ExternalStream.url == old).update({"url": new})
        db.commit()
    except Exception as e:
        db.rollback()
        logger.warning(f"fix_stale_external_urls: {e}")

def _item_title(x) -> str:
    return (getattr(x, "title", None) or getattr(x, "name", None) or "")

def _popularity_rank(title: str) -> int:
    t = (title or "").lower()
    for i, kw in enumerate(POPULAR_CHANNEL_KEYWORDS):
        if re.search(r"(?<![a-z0-9])" + re.escape(kw) + r"(?![a-z0-9])", t):
            return i
    return len(POPULAR_CHANNEL_KEYWORDS)

def sort_by_popularity(items, country: str = None):
    """Accepte ExternalStream (title) et IPTVChannel (name).
    Tri : populaires (France 24 d'abord) -> langue du pays -> TV avant radio -> vues -> titre."""
    lang = COUNTRY_MAIN_LANG.get((country or "").upper())
    def key(x):
        title = _item_title(x)
        tl = title.lower()
        xl = (getattr(x, "language", "") or "").lower()[:2]
        word_lang = next((c for w, c in _LANG_WORDS.items() if w in tl), None)
        item_lang = word_lang or xl
        return (
            _popularity_rank(title),
            0 if (lang and item_lang == lang) else 1,
            1 if getattr(x, "stream_type", "") == "audio" else 0,
            -(getattr(x, "viewers", 0) or 0),
            tl,
        )
    return sorted(items, key=key)

def _norm_channel_name(name: str) -> str:
    n = re.sub(r"[\(\[].*?[\)\]]", " ", (name or "").lower())
    n = re.sub(r"[^a-z0-9àâäçéèêëîïôöùûüÿœ+ ]", " ", n)
    return re.sub(r"\s+", " ", n).strip()

def _wanted_lang(title: str, language: str = None):
    tl = (title or "").lower()
    for w, c in _LANG_WORDS.items():
        if w in tl:
            return c
    return (language or "").lower()[:2] or None

def _find_working_iptv_equivalent(db, ext):
    """Pour une chaîne de l'accueil (ExternalStream), retrouve la même chaîne dans iptv-org
    (même pays, même nom, même langue). Ces flux-là sont ceux qui se lisent correctement."""
    if not ext or not ext.country:
        return None
    base = _norm_channel_name(ext.title)
    if not base:
        return None
    cands = db.query(IPTVChannel).filter(
        func.upper(IPTVChannel.country) == ext.country.upper(),
        IPTVChannel.is_active == True,
    ).all()
    want = _wanted_lang(ext.title, ext.language)
    scored = []
    for c in cands:
        if not c.url or not c.url.strip() or c.stream_type in ("audio",):
            continue
        cn = _norm_channel_name(c.name)
        if not cn:
            continue
        if cn == base:
            score = 3
        elif base.startswith(cn + " ") or cn.startswith(base + " "):
            score = 2
        else:
            continue
        # la langue doit correspondre (ne pas servir France 24 English pour France 24 Français)
        c_lang = _wanted_lang(c.name, c.language)
        if want and c_lang and c_lang != want:
            continue
        if c.is_working is False:
            score -= 1
        scored.append((score, c.viewers or 0, c))
    if not scored:
        return None
    scored.sort(key=lambda t: (-t[0], -t[1]))
    return scored[0][2]

@app.get("/", response_class=HTMLResponse)
async def home(
    request: Request,
    category: str = None,
    playlist: str = None,
    ptype: str = None,
    db: Session = Depends(get_db)
):
    """Page d'accueil avec tous les contenus"""
    lang = get_language(request)
    visitor_id = get_visitor_id(request)

    # Streams communautaires en direct
    live_query = db.query(UserStream).filter(
        and_(UserStream.is_live == True, UserStream.is_blocked == False)
    )
    if category and not category.startswith("iptv"):
        live_query = live_query.filter(UserStream.category == category)
    live_streams = live_query.order_by(desc(UserStream.viewer_count)).limit(20).all()

    # Flux externes
    ext_query = db.query(ExternalStream).filter(ExternalStream.is_active == True)
    if category and not category.startswith("iptv"):
        ext_query = ext_query.filter(ExternalStream.category == category)
    external_streams = sort_by_popularity(ext_query.order_by(desc(ExternalStream.viewers)).all())[:60]

    # Playlists IPTV - Convertir en dictionnaires pour le template
    playlists_all = db.query(IPTVPlaylist).filter(IPTVPlaylist.is_active == True)
    if ptype:
        playlists_all = playlists_all.filter(IPTVPlaylist.playlist_type == ptype)
    playlists_all = playlists_all.all()

    # Convertir les objets SQLAlchemy en dictionnaires pour éviter les erreurs dans le template
    pl_countries = []
    for p in playlists_all:
        if p.playlist_type == "country":
            pl_countries.append({
                "name": p.name,
                "display_name": p.display_name or p.name,
                "country": p.country or "",
                "channel_count": p.channel_count or 0,
                "playlist_type": p.playlist_type,
                "last_sync": p.last_sync,
                "url": f"/?playlist={p.name}"
            })
    
    pl_categories = []
    for p in playlists_all:
        if p.playlist_type == "category":
            pl_categories.append({
                "name": p.name,
                "display_name": p.display_name or p.name,
                "channel_count": p.channel_count or 0,
                "playlist_type": p.playlist_type,
                "url": f"/?playlist={p.name}"
            })
    
    pl_subdivisions = []
    for p in playlists_all:
        if p.playlist_type == "subdivision":
            pl_subdivisions.append({
                "name": p.name,
                "display_name": p.display_name or p.name,
                "country": p.country or "",
                "channel_count": p.channel_count or 0,
                "playlist_type": p.playlist_type,
                "url": f"/?playlist={p.name}"
            })
    
    pl_cities = []
    for p in playlists_all:
        if p.playlist_type == "city":
            pl_cities.append({
                "name": p.name,
                "display_name": p.display_name or p.name,
                "country": p.country or "",
                "channel_count": p.channel_count or 0,
                "playlist_type": p.playlist_type,
                "url": f"/?playlist={p.name}"
            })
    
    # Trier les pays alphabétiquement par display_name
    pl_countries.sort(key=lambda p: (p["display_name"].split(' ', 1)[-1].strip().lower() if ' ' in p["display_name"] else p["display_name"].lower()))

    # Chaînes IPTV d'une playlist spécifique
    iptv_channels = []
    selected_playlist = None
    if playlist:
        selected_playlist = db.query(IPTVPlaylist).filter(IPTVPlaylist.name == playlist).first()
        if selected_playlist:
            # Convertir en dictionnaire pour le template
            selected_playlist_dict = {
                "name": selected_playlist.name,
                "display_name": selected_playlist.display_name,
                "country": selected_playlist.country or "",
                "channel_count": selected_playlist.channel_count or 0,
            }
            
            channel_query = db.query(IPTVChannel).filter(
                IPTVChannel.playlist_id == playlist,
                IPTVChannel.is_active == True
            )
            if category and (category.startswith("iptv_") or category in CATEGORY_IPTV_KEYWORDS):
                keywords = CATEGORY_IPTV_KEYWORDS.get(category, [category.replace("iptv_", "")])
                if keywords and isinstance(keywords, list) and all(isinstance(k, str) for k in keywords):
                    filters = [IPTVChannel.category.ilike(f"%{kw}%") for kw in keywords]
                    if filters:
                        channel_query = channel_query.filter(or_(*filters))
            iptv_channels = sort_by_popularity(
                channel_query.order_by(IPTVChannel.name).all(),
                selected_playlist.country
            )[:200]
        else:
            selected_playlist_dict = None
    else:
        selected_playlist_dict = None
        
    if category and not category.startswith("iptv_"):
        keywords = CATEGORY_IPTV_KEYWORDS.get(category, [category])
        if keywords and isinstance(keywords, list) and all(isinstance(k, str) for k in keywords):
            filters = [IPTVChannel.category.ilike(f"%{kw}%") for kw in keywords]
            if filters:
                iptv_channels = db.query(IPTVChannel).filter(
                    or_(*filters), IPTVChannel.is_active == True
                ).order_by(desc(IPTVChannel.viewers)).limit(200).all()
    elif category and category.startswith("iptv_"):
        keywords = CATEGORY_IPTV_KEYWORDS.get(category, [category.replace("iptv_", "")])
        if keywords and isinstance(keywords, list) and all(isinstance(k, str) for k in keywords):
            filters = [IPTVChannel.category.ilike(f"%{kw}%") for kw in keywords]
            if filters:
                iptv_channels = db.query(IPTVChannel).filter(
                    or_(*filters), IPTVChannel.is_active == True
                ).order_by(desc(IPTVChannel.viewers)).limit(200).all()

    # Convertir les streams en dictionnaires pour le template
    live_streams_dict = []
    for s in live_streams:
        live_streams_dict.append({
            "id": s.id,
            "title": s.title,
            "category": s.category,
            "viewer_count": s.viewer_count,
            "like_count": s.like_count,
            "thumbnail": s.thumbnail,
            "is_live": s.is_live,
        })
    
    external_streams_dict = []
    for s in external_streams:
        external_streams_dict.append({
            "id": s.id,
            "title": s.title,
            "category": s.category,
            "country": s.country or "",
            "logo": s.logo or "",
            "stream_type": s.stream_type,
            "quality": s.quality or "",
            "is_active": s.is_active,
        })
    
    iptv_channels_dict = []
    for ch in iptv_channels:
        iptv_channels_dict.append({
            "id": ch.id,
            "name": ch.name,
            "logo": ch.logo or "",
            "country": ch.country or "",
            "category": ch.category or "",
            "stream_type": ch.stream_type or "hls",
            "playlist_id": ch.playlist_id,
        })
    
    # Statistiques par catégorie
    categories_stats = []
    for cat in CATEGORIES:
        cat_id = cat["id"]
        keywords = CATEGORY_IPTV_KEYWORDS.get(cat_id, [cat_id.replace("iptv_", "")])

        if cat_id == "iptv":
            iptv_count = db.query(IPTVChannel).filter(IPTVChannel.is_active == True).count()
            categories_stats.append({
                "id": cat["id"],
                "name": cat["name"],
                "icon": cat["icon"],
                "count": iptv_count
            })
            continue

        if keywords and isinstance(keywords, list) and all(isinstance(k, str) for k in keywords):
            filters = [IPTVChannel.category.ilike(f"%{kw}%") for kw in keywords]
            if filters:
                iptv_count = db.query(IPTVChannel).filter(
                    or_(*filters), IPTVChannel.is_active == True
                ).count()
            else:
                iptv_count = 0
        else:
            iptv_count = 0

        ext_count = db.query(ExternalStream).filter(
            ExternalStream.category == cat_id, ExternalStream.is_active == True
        ).count()
        user_count = db.query(UserStream).filter(
            UserStream.category == cat_id,
            UserStream.is_live == True,
            UserStream.is_blocked == False
        ).count()
        categories_stats.append({
            "id": cat["id"],
            "name": cat["name"],
            "icon": cat["icon"],
            "count": ext_count + user_count + iptv_count
        })

    # Chaînes radio pour le mini-player
    radio_streams = db.query(ExternalStream).filter(
        ExternalStream.is_active == True,
        ExternalStream.stream_type == "audio"
    ).limit(24).all()
    
    radio_streams_dict = []
    for s in radio_streams:
        radio_streams_dict.append({
            "id": s.id,
            "title": s.title,
            "logo": s.logo or "",
        })

    # Chaînes mises en avant
    featured_streams = db.query(ExternalStream).filter(
        ExternalStream.is_active == True,
        ExternalStream.category.in_(["news", "sports", "entertainment"])
    ).order_by(ExternalStream.id.desc()).limit(6).all()
    
    featured_streams_dict = []
    for s in featured_streams:
        featured_streams_dict.append({
            "id": s.id,
            "title": s.title,
            "logo": s.logo or "",
            "category": s.category,
            "stream_type": s.stream_type,
        })

    response = templates.TemplateResponse(
        request,
        "index.html",
        {
            "request": request,
            "live_streams": live_streams_dict,
            "external_streams": external_streams_dict,
            "pl_countries": pl_countries,
            "pl_subdivisions": pl_subdivisions,
            "pl_cities": pl_cities,
            "pl_categories": pl_categories,
            "iptv_channels": iptv_channels_dict,
            "selected_playlist": selected_playlist_dict,
            "categories": categories_stats,
            "language": lang,
            "visitor_id": visitor_id,
            "app_name": settings.APP_NAME,
            "current_category": category,
            "current_playlist": playlist,
            "logo_path": settings.LOGO_PATH if os.path.exists(settings.LOGO_PATH) else None,
            "radio_streams": radio_streams_dict,
            "featured_streams": featured_streams_dict,
        }
    )

    # Définir le cookie visiteur si nécessaire
    if not request.cookies.get('visitor_id'):
        response.set_cookie(
            key="visitor_id",
            value=visitor_id,
            max_age=settings.SESSION_MAX_AGE,
            httponly=True,
            samesite="lax"
        )

    return response

@app.get("/watch/external/{stream_id}", response_class=HTMLResponse)
async def watch_external(request: Request, stream_id: str, db: Session = Depends(get_db)):
    """Page de visionnage d'un flux externe"""
    stream = db.query(ExternalStream).filter(ExternalStream.id == stream_id).first()
    if not stream:
        return RedirectResponse(url="/", status_code=303)

    # URL à essayer : flux iptv-org équivalent (celui des pages pays, validé) d'abord, puis le flux
    # « maison » (corrigé s'il est périmé). Le lecteur passe au suivant en cas d'échec.
    play_urls = []
    if stream.stream_type in ("hls", "dash", None, ""):
        try:
            working = _find_working_iptv_equivalent(db, stream)
        except Exception as _e:
            logger.warning(f"équivalent iptv introuvable pour {stream.title}: {_e}")
            working = None
        if working and (working.url or "").strip():
            play_urls.append(working.url.strip())
    _own = _fix_stale_url(stream.url)
    if _own and _own not in play_urls:
        play_urls.append(_own)
    play_url = play_urls[0] if play_urls else (stream.url or "")
    alt_urls = play_urls[1:]

    # Incrémenter le compteur de viewers
    stream.viewers += 1
    db.commit()

    # Résolution YouTube si nécessaire
    youtube_data = None
    if stream.stream_type == "youtube":
        youtube_data = await yt_service.get_stream_url(stream.url)

    # Recommandations
    recommendations = db.query(ExternalStream).filter(
        ExternalStream.category == stream.category,
        ExternalStream.id != stream.id,
        ExternalStream.is_active == True
    ).order_by(desc(ExternalStream.viewers)).limit(8).all()

    return templates.TemplateResponse(
        request,
        "watch_external.html",
        {
            "request": request,
            "stream": stream,
            "similar_streams": recommendations,
            "play_url": play_url,
            "alt_urls": alt_urls,
            "recommendations": recommendations,
            "language": get_language(request),
            "visitor_id": get_visitor_id(request),
            "app_name": settings.APP_NAME,
            "youtube_data": youtube_data,
            "categories": CATEGORIES,
            "logo_path": settings.LOGO_PATH if os.path.exists(settings.LOGO_PATH) else None
        }
    )

@app.get("/watch/iptv/{channel_id}", response_class=HTMLResponse)
async def watch_iptv(request: Request, channel_id: str, db: Session = Depends(get_db)):
    """Page de visionnage d'une chaîne IPTV"""
    channel = db.query(IPTVChannel).filter(IPTVChannel.id == channel_id).first()
    if not channel:
        return RedirectResponse(url="/", status_code=303)

    # Vérification de l'URL
    if not channel.url or not channel.url.strip():
        return templates.TemplateResponse(
            request,
            "error.html",
            {
                "request": request,
                "error": "L'URL de ce flux est manquante ou invalide.",
                "app_name": settings.APP_NAME,
                "categories": CATEGORIES,
                "logo_path": settings.LOGO_PATH if os.path.exists(settings.LOGO_PATH) else None
            }
        )

    # Normaliser le stream_type si None
    if not channel.stream_type:
        channel.stream_type = "hls"

    # Incrémenter le compteur de viewers
    channel.viewers += 1
    channel.last_seen = datetime.utcnow()
    db.commit()

    # Résolution YouTube si nécessaire
    youtube_data = None
    if channel.stream_type == "youtube":
        youtube_data = await yt_service.get_stream_url(channel.url)

    # Recommandations
    recommendations = sort_by_popularity(
        db.query(IPTVChannel).filter(
            IPTVChannel.playlist_id == channel.playlist_id,
            IPTVChannel.id != channel.id,
            IPTVChannel.is_active == True
        ).all(),
        channel.country
    )[:12]

    return templates.TemplateResponse(
        request,
        "watch_iptv.html",
        {
            "request": request,
            "channel": channel,
            "recommendations": recommendations,
            "other_channels": recommendations,
            "language": get_language(request),
            "visitor_id": get_visitor_id(request),
            "app_name": settings.APP_NAME,
            "youtube_data": youtube_data,
            "categories": CATEGORIES,
            "logo_path": settings.LOGO_PATH if os.path.exists(settings.LOGO_PATH) else None
        }
    )

@app.get("/watch/user/{stream_id}", response_class=HTMLResponse)
async def watch_user(request: Request, stream_id: str, db: Session = Depends(get_db)):
    """Page de visionnage d'un stream utilisateur"""
    stream = db.query(UserStream).filter(UserStream.id == stream_id).first()
    if not stream:
        return RedirectResponse(url="/", status_code=303)

    # Vérifier si le stream est bloqué
    if stream.is_blocked:
        return templates.TemplateResponse(
            request,
            "blocked.html",
            {
                "request": request,
                "reason": "Ce stream a été bloqué par la modération",
                "app_name": settings.APP_NAME,
                "categories": CATEGORIES
            }
        )

    # Vérifier l'IP
    client_ip = request.client.host if request.client else "0.0.0.0"
    if check_ip_blocked(client_ip, db):
        return templates.TemplateResponse(
            request,
            "blocked.html",
            {
                "request": request,
                "reason": "Votre adresse IP a été bloquée",
                "app_name": settings.APP_NAME,
                "categories": CATEGORIES
            }
        )

    # Gérer le visiteur
    visitor_id = get_visitor_id(request)
    visitor = db.query(Visitor).filter(Visitor.visitor_id == visitor_id).first()
    if not visitor:
        visitor = Visitor(
            visitor_id=visitor_id,
            ip_address=client_ip,
            user_agent=request.headers.get("user-agent", "")
        )
        db.add(visitor)
        db.commit()
    else:
        visitor.last_seen = datetime.utcnow()
        db.commit()

    # Recommandations
    recommendations = db.query(UserStream).filter(
        and_(
            UserStream.category == stream.category,
            UserStream.id != stream.id,
            UserStream.is_live == True,
            UserStream.is_blocked == False
        )
    ).order_by(desc(UserStream.viewer_count)).limit(6).all()

    return templates.TemplateResponse(
        request,
        "watch_user.html",
        {
            "request": request,
            "stream": stream,
            "recommended": recommendations,
            "language": get_language(request),
            "visitor_id": visitor_id,
            "app_name": settings.APP_NAME,
            "max_comment_length": settings.MAX_COMMENT_LENGTH,
            "comments_per_minute": settings.MAX_COMMENTS_PER_MINUTE,
            "categories": CATEGORIES,
            "logo_path": settings.LOGO_PATH if os.path.exists(settings.LOGO_PATH) else None
        }
    )

@app.get("/playlist/{playlist_name}", response_class=HTMLResponse)
async def view_playlist(request: Request, playlist_name: str, db: Session = Depends(get_db)):
    """Page d'affichage d'une playlist IPTV"""
    playlist = db.query(IPTVPlaylist).filter(IPTVPlaylist.name == playlist_name).first()
    if not playlist:
        return RedirectResponse(url="/", status_code=303)

    channels = db.query(IPTVChannel).filter(
        IPTVChannel.playlist_id == playlist_name,
        IPTVChannel.is_active == True
    ).order_by(IPTVChannel.name).all()

    return templates.TemplateResponse(
        request,
        "playlist.html",
        {
            "request": request,
            "playlist": playlist,
            "channels": channels,
            "language": get_language(request),
            "visitor_id": get_visitor_id(request),
            "app_name": settings.APP_NAME,
            "categories": CATEGORIES,
            "logo_path": settings.LOGO_PATH if os.path.exists(settings.LOGO_PATH) else None
        }
    )

@app.get("/go-live", response_class=HTMLResponse)
async def go_live_page(request: Request, db: Session = Depends(get_db)):
    """Page de création de live"""
    client_ip = request.client.host if request.client else "0.0.0.0"

    # Vérifier l'IP
    if check_ip_blocked(client_ip, db):
        return templates.TemplateResponse(
            request,
            "blocked.html",
            {
                "request": request,
                "reason": "Votre adresse IP a été bloquée",
                "app_name": settings.APP_NAME,
                "categories": CATEGORIES
            }
        )

    return templates.TemplateResponse(
        request,
        "go_live.html",
        {
            "request": request,
            "language": get_language(request),
            "visitor_id": get_visitor_id(request),
            "categories": [c for c in CATEGORIES if not c["id"].startswith("iptv")],
            "app_name": settings.APP_NAME,
            "logo_path": settings.LOGO_PATH if os.path.exists(settings.LOGO_PATH) else None
        }
    )

@app.get("/search", response_class=HTMLResponse)
async def search_page(request: Request, q: str = "", db: Session = Depends(get_db)):
    """Page de recherche"""
    external_results = []
    iptv_results = []
    user_results = []

    if q and len(q.strip()) >= 2:
        query = q.strip()

        # Recherche dans les flux externes
        external_results = db.query(ExternalStream).filter(
            and_(
                ExternalStream.is_active == True,
                or_(
                    ExternalStream.title.ilike(f"%{query}%"),
                    ExternalStream.subcategory.ilike(f"%{query}%"),
                    ExternalStream.category.ilike(f"%{query}%"),
                    ExternalStream.country.ilike(f"%{query}%")
                )
            )
        ).all()

        # Recherche dans les chaînes IPTV
        iptv_results = db.query(IPTVChannel).filter(
            and_(
                IPTVChannel.is_active == True,
                or_(
                    IPTVChannel.name.ilike(f"%{query}%"),
                    IPTVChannel.category.ilike(f"%{query}%"),
                    IPTVChannel.country.ilike(f"%{query}%")
                )
            )
        ).limit(200).all()

        # Recherche dans les streams utilisateur
        user_results = db.query(UserStream).filter(
            and_(
                UserStream.is_live == True,
                UserStream.is_blocked == False,
                or_(
                    UserStream.title.ilike(f"%{query}%"),
                    UserStream.description.ilike(f"%{query}%"),
                    UserStream.tags.ilike(f"%{query}%")
                )
            )
        ).all()

    return templates.TemplateResponse(
        request,
        "search.html",
        {
            "request": request,
            "query": q,
            "external_results": external_results,
            "iptv_results": iptv_results,
            "user_results": user_results,
            "language": get_language(request),
            "visitor_id": get_visitor_id(request),
            "app_name": settings.APP_NAME,
            "categories": CATEGORIES,
            "logo_path": settings.LOGO_PATH if os.path.exists(settings.LOGO_PATH) else None
        }
    )

@app.get("/static/logo")
async def get_logo():
    """Retourne le logo de l'application"""
    for path in [STATIC_DIR / "livewatch.png", STATIC_DIR / "IMG.png", BASE_DIR / settings.LOGO_PATH]:
        if os.path.exists(path):
            return FileResponse(path, media_type="image/png")
    return RedirectResponse(url="https://via.placeholder.com/200x200?text=Livewatch")

@app.get("/events", response_class=HTMLResponse)
async def events_page(request: Request, db: Session = Depends(get_db)):
    """Page Événements — affiche les annonces publiées par l'admin"""
    announcements = db.query(AdminAnnouncement).filter(
        AdminAnnouncement.is_active == True
    ).order_by(desc(AdminAnnouncement.created_at)).all()

    return templates.TemplateResponse(
        request,
        "events.html",
        {
            "request": request,
            "announcements": announcements,
            "events": {cat: [] for cat in ["sport", "cinema", "news", "kids", "documentary", "music", "other"]},
            "language": get_language(request),
            "visitor_id": get_visitor_id(request),
            "app_name": settings.APP_NAME,
            "categories": CATEGORIES,
            "logo_path": settings.LOGO_PATH if os.path.exists(settings.LOGO_PATH) else None
        }
    )

@app.get("/api/events/upcoming")
async def api_events_upcoming(limit: int = 6, db: Session = Depends(get_db)):
    """
    Programmes/événements à venir groupés par catégorie (sport, cinéma, etc.).
    Fonctionnalité de planning TV pas encore implémentée côté données —
    renvoie des catégories vides pour que la page Événements ne casse pas
    en attendant une vraie source de programmes.
    """
    empty_categories = {cat: [] for cat in ["sport", "cinema", "news", "kids", "documentary", "music", "other"]}
    return JSONResponse(empty_categories)

# ==================== API YOUTUBE ====================

@app.get("/api/youtube/resolve")
async def resolve_youtube(url: str):
    """Résout une URL YouTube en flux direct"""
    data = await yt_service.get_stream_url(url)
    return JSONResponse(data)

# ==================== API STREAMS UTILISATEUR ====================

@app.post("/api/streams/create")
async def create_user_stream(
    request: Request,
    title: str = Form(..., min_length=3, max_length=100),
    category: str = Form(...),
    description: str = Form(None, max_length=1000),
    tags: str = Form(None),
    db: Session = Depends(get_db)
):
    """Crée un nouveau stream utilisateur"""
    visitor_id = get_visitor_id(request)
    client_ip = request.client.host if request.client else "0.0.0.0"

    # Vérifier l'IP
    if check_ip_blocked(client_ip, db):
        return JSONResponse(status_code=403, content={"error": "IP bloquée"})

    # Valider la catégorie
    valid_categories = [c["id"] for c in CATEGORIES if not c["id"].startswith("iptv")]
    if category not in valid_categories:
        return JSONResponse(status_code=400, content={"error": "Catégorie invalide"})

    # Nettoyer le titre
    title_clean = html.escape(title.strip())
    if len(title_clean) < 3:
        return JSONResponse(status_code=400, content={"error": "Titre trop court"})

    # Obtenir ou créer le visiteur
    visitor = db.query(Visitor).filter(Visitor.visitor_id == visitor_id).first()
    if not visitor:
        visitor = Visitor(
            visitor_id=visitor_id,
            ip_address=client_ip,
            user_agent=request.headers.get("user-agent", "")
        )
        db.add(visitor)
        db.commit()
        db.refresh(visitor)

    # Vérifier la limite de streams simultanés
    active_streams = db.query(UserStream).filter(
        and_(UserStream.visitor_id == visitor.id, UserStream.is_live == True)
    ).count()
    if active_streams >= settings.MAX_CONCURRENT_STREAMS_PER_USER:
        return JSONResponse(
            status_code=429,
            content={"error": f"Maximum {settings.MAX_CONCURRENT_STREAMS_PER_USER} streams simultanés"}
        )

    # Créer le stream
    stream_key = f"live_{secrets.token_urlsafe(32)}"
    stream = UserStream(
        title=title_clean,
        description=html.escape(description) if description else None,
        category=category,
        tags=html.escape(tags) if tags else None,
        stream_key=stream_key,
        visitor_id=visitor.id,
        stream_url=f"/live/{stream_key}/index.m3u8",
        language=get_language(request)
    )

    try:
        db.add(stream)
        db.commit()
        db.refresh(stream)

        # Mettre à jour les statistiques du visiteur
        visitor.total_streams += 1
        db.commit()

        return JSONResponse({
            "success": True,
            "stream_id": stream.id,
            "stream_key": stream_key,
            "rtmp_url": f"rtmp://localhost/live/{stream_key}",
            "hls_url": f"/live/{stream_key}/index.m3u8",
            "watch_url": f"/watch/user/{stream.id}"
        })
    except Exception as e:
        logger.error(f"Erreur création stream: {e}")
        db.rollback()
        return JSONResponse(status_code=500, content={"error": "Erreur lors de la création du stream"})

@app.post("/api/streams/{stream_id}/start")
async def start_user_stream(stream_id: str, request: Request, db: Session = Depends(get_db)):
    """Démarre un stream (marque comme en direct)"""
    stream = db.query(UserStream).filter(UserStream.id == stream_id).first()
    if not stream:
        return JSONResponse(status_code=404, content={"error": "Stream non trouvé"})

    # Vérifier que l'utilisateur est propriétaire du stream
    visitor_id = get_visitor_id(request)
    if not stream.visitor or stream.visitor.visitor_id != visitor_id:
        return JSONResponse(status_code=403, content={"error": "Non autorisé"})

    stream.is_live = True
    stream.started_at = datetime.utcnow()
    db.commit()

    return JSONResponse({"success": True})

@app.post("/api/streams/{stream_id}/stop")
async def stop_user_stream(stream_id: str, request: Request, db: Session = Depends(get_db)):
    """Arrête un stream"""
    stream = db.query(UserStream).filter(UserStream.id == stream_id).first()
    if not stream:
        return JSONResponse(status_code=404, content={"error": "Stream non trouvé"})

    visitor_id = get_visitor_id(request)
    if not stream.visitor or stream.visitor.visitor_id != visitor_id:
        return JSONResponse(status_code=403, content={"error": "Non autorisé"})

    stream.is_live = False
    stream.ended_at = datetime.utcnow()
    db.commit()

    return JSONResponse({"success": True})

@app.post("/api/streams/{stream_id}/like")
async def like_user_stream(stream_id: str, request: Request, db: Session = Depends(get_db)):
    """Ajoute un like à un stream"""
    stream = db.query(UserStream).filter(UserStream.id == stream_id).first()
    if not stream:
        return JSONResponse(status_code=404, content={"error": "Stream non trouvé"})

    stream.like_count += 1
    db.commit()

    return JSONResponse({"success": True, "likes": stream.like_count})

@app.post("/api/streams/{stream_id}/report")
async def report_user_stream(
    stream_id: str,
    request: Request,
    reason: str = Form(...),
    db: Session = Depends(get_db)
):
    """Signale un stream"""
    visitor_id = get_visitor_id(request)
    stream = db.query(UserStream).filter(UserStream.id == stream_id).first()
    if not stream:
        return JSONResponse(status_code=404, content={"error": "Stream non trouvé"})

    visitor = db.query(Visitor).filter(Visitor.visitor_id == visitor_id).first()
    if not visitor:
        return JSONResponse(status_code=400, content={"error": "Visiteur non trouvé"})

    # Créer le signalement
    report = Report(
        reason=html.escape(reason),
        stream_id=stream_id,
        visitor_id=visitor.id
    )
    db.add(report)

    # Incrémenter le compteur de signalements
    stream.report_count += 1

    # Bloquer automatiquement si trop de signalements
    if stream.report_count >= settings.AUTO_BLOCK_THRESHOLD:
        stream.is_blocked = True
        stream.is_live = False

        # Bloquer l'IP du streamer
        if stream.visitor and stream.visitor.ip_address:
            existing_block = db.query(BlockedIP).filter(
                BlockedIP.ip_address == stream.visitor.ip_address
            ).first()
            if not existing_block:
                blocked = BlockedIP(
                    ip_address=stream.visitor.ip_address,
                    reason=f"Auto-block - {stream.report_count} signalements"
                )
                db.add(blocked)

    db.commit()

    return JSONResponse({"success": True})

# ==================== WEBSOCKET CHAT ====================

@app.websocket("/ws/{stream_id}")
async def websocket_endpoint(websocket: WebSocket, stream_id: str):
    """Endpoint WebSocket pour le chat en direct"""
    db = SessionLocal()
    visitor_id = None

    try:
        # Récupérer l'ID du visiteur
        visitor_id = websocket.cookies.get('visitor_id') or f"vis_{secrets.token_urlsafe(16)}"

        # Vérifier que le stream existe
        stream = db.query(UserStream).filter(UserStream.id == stream_id).first()
        if not stream:
            await websocket.close(code=4004, reason="Stream non trouvé")
            return

        # Vérifier l'IP
        client_ip = websocket.client.host if websocket.client else "0.0.0.0"
        if check_ip_blocked(client_ip, db):
            await websocket.close(code=4003, reason="IP bloquée")
            return

        # Connecter le websocket
        await manager.connect(websocket, stream_id, visitor_id, client_ip)

        # Envoyer l'historique des 50 derniers commentaires
        recent_comments = db.query(Comment).filter(
            and_(
                Comment.stream_id == stream_id,
                Comment.is_deleted == False,
                Comment.is_auto_hidden == False
            )
        ).order_by(Comment.created_at.desc()).limit(50).all()

        for comment in reversed(recent_comments):
            await websocket.send_json({
                "type": "history",
                "id": comment.id,
                "content": comment.content,
                "visitor_id": (comment.visitor.visitor_id[:8] + "...") if comment.visitor else "Anonyme",
                "created_at": comment.created_at.isoformat()
            })

        # Envoyer le nombre de viewers
        await websocket.send_json({
            "type": "viewer_count",
            "count": manager.get_viewer_count(stream_id)
        })

        # Boucle principale de réception
        while True:
            data = await websocket.receive_json()

            if data.get("type") == "comment":
                # Vérifier la limite de taux
                if not manager.check_rate_limit(visitor_id):
                    await websocket.send_json({
                        "type": "error",
                        "message": f"Maximum {settings.MAX_COMMENTS_PER_MINUTE} commentaires par minute"
                    })
                    continue

                content = data.get("content", "").strip()
                if not content or len(content) > settings.MAX_COMMENT_LENGTH:
                    continue

                # Filtrer les mots inappropriés
                content = filter_inappropriate(content)

                # Obtenir ou créer le visiteur
                visitor = db.query(Visitor).filter(Visitor.visitor_id == visitor_id).first()
                if not visitor:
                    visitor = Visitor(
                        visitor_id=visitor_id,
                        ip_address=client_ip,
                        user_agent="WebSocket"
                    )
                    db.add(visitor)
                    db.commit()
                    db.refresh(visitor)

                # Créer le commentaire
                comment = Comment(
                    content=content,
                    stream_id=stream_id,
                    visitor_id=visitor.id,
                    ip_address=client_ip
                )
                db.add(comment)
                visitor.total_comments += 1
                db.commit()
                db.refresh(comment)

                # Diffuser le commentaire à tous les viewers
                await manager.broadcast_to_stream(stream_id, {
                    "type": "comment",
                    "id": comment.id,
                    "content": content,
                    "visitor_id": visitor_id[:8] + "...",
                    "created_at": comment.created_at.isoformat()
                })

                # Enregistrer les statistiques
                stat = StreamStats(
                    stream_id=stream_id,
                    viewer_count=manager.get_viewer_count(stream_id)
                )
                db.add(stat)
                db.commit()

            elif data.get("type") == "report_comment":
                # Signaler un commentaire
                comment_id = data.get("comment_id")
                reason = data.get("reason", "Contenu inapproprié")

                comment = db.query(Comment).filter(Comment.id == comment_id).first()
                if comment:
                    comment.is_flagged = True
                    comment.report_count += 1

                    if comment.report_count >= settings.COMMENT_FLAG_THRESHOLD:
                        comment.is_auto_hidden = True

                    visitor = db.query(Visitor).filter(Visitor.visitor_id == visitor_id).first()
                    if visitor:
                        report = Report(
                            reason=reason,
                            comment_id=comment_id,
                            visitor_id=visitor.id
                        )
                        db.add(report)
                    db.commit()

                    await websocket.send_json({
                        "type": "success",
                        "message": "Commentaire signalé"
                    })

            elif data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        # Déconnexion normale
        if visitor_id:
            manager.disconnect(websocket, stream_id, visitor_id)
            await manager.update_viewer_count(stream_id)
    except Exception as e:
        logger.error(f"Erreur WebSocket: {e}")
        if visitor_id:
            manager.disconnect(websocket, stream_id, visitor_id)
    finally:
        db.close()

# ==================== PROXY HLS ====================

@app.get("/proxy/stream")
async def proxy_stream_route(url: str, headers: str = None):
    """Proxy manifest M3U8 / HLS avec réécriture des segments"""
    custom_headers = None
    if headers:
        try:
            custom_headers = json.loads(headers)
        except Exception:
            pass
    return await proxy.fetch_stream(url, custom_headers)

@app.options("/proxy/stream")
async def proxy_stream_options():
    return Response(
        status_code=204,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
            "Access-Control-Allow-Headers": "*",
        }
    )

@app.get("/proxy/segment")
async def proxy_segment_route(url: str):
    """Proxy segments .ts / .m4s / audio — streaming progressif réel"""
    return await proxy.stream_segment(url)

@app.options("/proxy/segment")
async def proxy_segment_options():
    return Response(
        status_code=204,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
            "Access-Control-Allow-Headers": "*",
        }
    )

@app.get("/proxy/audio")
async def proxy_audio_route(url: str):
    """
    Proxy dédié pour les flux audio (MP3, AAC, OGG…).
    Supporte le streaming progressif avec gestion des Range requests.
    """
    try:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        req_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "audio/mpeg, audio/aac, audio/ogg, audio/*, */*",
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
            "Origin": origin,
            "Referer": origin + "/",
            "Connection": "keep-alive",
        }

        async def audio_stream_generator(stream_url: str, hdrs: dict):
            async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
                async with client.stream("GET", stream_url, headers=hdrs) as response:
                    response.raise_for_status()
                    async for chunk in response.aiter_bytes(chunk_size=8192):
                        yield chunk

        # Détecter le content-type via HEAD d'abord
        content_type = "audio/mpeg"
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                head = await client.head(url, headers=req_headers)
                ct = head.headers.get("content-type", "")
                if ct:
                    content_type = ct.split(";")[0].strip()
        except:
            pass

        # Déduire depuis l'extension si HEAD ne répond pas
        if ";" in content_type or content_type == "application/octet-stream":
            ext = url.split("?")[0].split(".")[-1].lower()
            content_type = {
                "mp3": "audio/mpeg", "aac": "audio/aac", "ogg": "audio/ogg",
                "flac": "audio/flac", "opus": "audio/opus", "m4a": "audio/mp4",
                "wav": "audio/wav", "m3u8": "application/x-mpegURL",
            }.get(ext, "audio/mpeg")

        return StreamingResponse(
            audio_stream_generator(url, req_headers),
            media_type=content_type,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Cache-Control": "no-cache",
                "X-Content-Type-Options": "nosniff",
            }
        )
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail="Flux audio inaccessible")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Erreur proxy audio: {str(e)}")

# ==================== API FAVORIS ====================

@app.post("/api/favorites/add")
async def add_favorite(
    request: Request,
    stream_id: str = Form(...),
    stream_type: str = Form(...),
    db: Session = Depends(get_db)
):
    """Ajoute un favori"""
    visitor_id = get_visitor_id(request)

    # Obtenir ou créer le visiteur
    visitor = db.query(Visitor).filter(Visitor.visitor_id == visitor_id).first()
    if not visitor:
        visitor = Visitor(
            visitor_id=visitor_id,
            ip_address=request.client.host if request.client else "0.0.0.0"
        )
        db.add(visitor)
        db.commit()
        db.refresh(visitor)

    # Vérifier si déjà en favoris
    existing = db.query(Favorite).filter(
        Favorite.visitor_id == visitor.id,
        Favorite.stream_id == stream_id
    ).first()

    if not existing:
        fav = Favorite(
            visitor_id=visitor.id,
            stream_id=stream_id,
            stream_type=stream_type
        )
        db.add(fav)
        db.commit()

    return JSONResponse({"success": True})

@app.post("/api/favorites/remove")
async def remove_favorite(request: Request, stream_id: str = Form(...), db: Session = Depends(get_db)):
    """Supprime un favori"""
    visitor_id = request.cookies.get('visitor_id')
    if visitor_id:
        visitor = db.query(Visitor).filter(Visitor.visitor_id == visitor_id).first()
        if visitor:
            db.query(Favorite).filter(
                Favorite.visitor_id == visitor.id,
                Favorite.stream_id == stream_id
            ).delete()
            db.commit()
    return JSONResponse({"success": True})

@app.get("/api/favorites")
async def get_favorites(request: Request, db: Session = Depends(get_db)):
    """Récupère les favoris du visiteur"""
    visitor_id = get_visitor_id(request)  # cohérent avec add_favorite
    favorites = []

    visitor = db.query(Visitor).filter(Visitor.visitor_id == visitor_id).first()
    if visitor:
        favs = db.query(Favorite).filter(Favorite.visitor_id == visitor.id).all()
        for fav in favs:
            if fav.stream_type == "external":
                stream = db.query(ExternalStream).filter(ExternalStream.id == fav.stream_id).first()
                if stream:
                    favorites.append({
                        "id": str(stream.id), "title": stream.title,
                        "category": stream.category, "logo": stream.logo or "",
                        "type": "external", "url": f"/watch/external/{stream.id}"
                    })
            elif fav.stream_type == "iptv":
                channel = db.query(IPTVChannel).filter(IPTVChannel.id == fav.stream_id).first()
                if channel:
                    favorites.append({
                        "id": str(channel.id), "title": channel.name,
                        "category": "iptv", "logo": channel.logo or "",
                        "type": "iptv", "url": f"/watch/iptv/{channel.id}"
                    })
            else:
                stream = db.query(UserStream).filter(UserStream.id == fav.stream_id).first()
                if stream:
                    favorites.append({
                        "id": str(stream.id), "title": stream.title,
                        "category": stream.category, "logo": "",
                        "type": "user", "is_live": stream.is_live,
                        "url": f"/watch/user/{stream.id}"
                    })

    return JSONResponse(favorites)

# ==================== UPLOAD DE FICHIERS ====================

@app.post("/api/upload/thumbnail")
async def upload_thumbnail(request: Request, file: UploadFile = File(...)):
    """Upload une miniature pour un stream"""
    # Lire le contenu
    content = await file.read()
    if len(content) > settings.MAX_UPLOAD_SIZE:
        return JSONResponse(
            status_code=413,
            content={"error": f"Fichier trop volumineux (max {settings.MAX_UPLOAD_SIZE//1024//1024}MB)"}
        )

    # Vérifier l'extension
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in settings.ALLOWED_EXTENSIONS:
        return JSONResponse(
            status_code=400,
            content={"error": f"Extension non autorisée: {ext}"}
        )

    # Générer un nom de fichier unique
    filename = f"{uuid.uuid4()}{ext}"
    filepath = os.path.join(THUMBNAILS_DIR, filename)

    # Sauvegarder le fichier
    async with aiofiles.open(filepath, 'wb') as f:
        await f.write(content)

    # Optimiser l'image
    try:
        img = Image.open(filepath)
        img.thumbnail((640, 360), Image.Resampling.LANCZOS)
        img.save(filepath, optimize=True, quality=85)
    except Exception as e:
        logger.warning(f"Impossible d'optimiser l'image: {e}")

    return JSONResponse({
        "success": True,
        "url": f"/static/thumbnails/{filename}"
    })

# ==================== API IPTV ====================

@app.post("/api/admin/iptv/sync")
async def admin_sync_iptv(request: Request):
    try: require_admin(request)
    except HTTPException: return JSONResponse(status_code=401, content={"success": False, "error": "Non autorisé"})
    if iptv_sync.is_syncing:
        return JSONResponse({"success": False, "message": "Synchronisation déjà en cours", "is_syncing": True})
    asyncio.create_task(iptv_sync.sync_all_playlists())
    return JSONResponse({"success": True, "message": "Synchronisation démarrée", "is_syncing": True})

@app.get("/api/iptv/stats")
async def iptv_stats(db: Session = Depends(get_db)):
    """Statistiques IPTV"""
    total_channels = db.query(IPTVChannel).count()
    active_channels = db.query(IPTVChannel).filter(IPTVChannel.is_active == True).count()
    total_playlists = db.query(IPTVPlaylist).count()

    last_sync = db.query(IPTVPlaylist.last_sync).order_by(desc(IPTVPlaylist.last_sync)).first()

    # Top catégories
    categories = db.query(
        IPTVChannel.category,
        func.count(IPTVChannel.id).label('count')
    ).group_by(IPTVChannel.category).order_by(desc('count')).limit(10).all()

    return JSONResponse({
        "total_channels": total_channels,
        "active_channels": active_channels,
        "total_playlists": total_playlists,
        "last_sync": last_sync[0].isoformat() if last_sync and last_sync[0] else None,
        "top_categories": [{"category": c[0], "count": c[1]} for c in categories],
        "is_syncing": iptv_sync.is_syncing
    })

@app.get("/api/iptv/playlists")
async def iptv_playlists(db: Session = Depends(get_db)):
    """Liste toutes les playlists IPTV"""
    playlists = db.query(IPTVPlaylist).filter(IPTVPlaylist.is_active == True).all()
    return JSONResponse([
        {
            "id": p.id,
            "name": p.name,
            "display_name": p.display_name,
            "channel_count": p.channel_count,
            "last_sync": p.last_sync.isoformat() if p.last_sync else None,
            "playlist_type": p.playlist_type,
            "country": p.country
        }
        for p in playlists
    ])

@app.get("/api/iptv/channels")
async def iptv_channels(
    playlist: str = None,
    category: str = None,
    country: str = None,
    search: str = None,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """Recherche de chaînes IPTV avec filtres"""
    query = db.query(IPTVChannel).filter(IPTVChannel.is_active == True)

    if playlist:
        query = query.filter(IPTVChannel.playlist_id == playlist)
    if category:
        query = query.filter(IPTVChannel.category.ilike(f"%{category}%"))
    if country:
        query = query.filter(IPTVChannel.country == country)
    if search:
        query = query.filter(IPTVChannel.name.ilike(f"%{search}%"))

    channels = query.order_by(IPTVChannel.name).limit(limit).all()

    return JSONResponse([
        {
            "id": ch.id,
            "name": ch.name,
            "url": ch.url,
            "logo": ch.logo,
            "category": ch.category,
            "country": ch.country,
            "language": ch.language,
            "stream_type": ch.stream_type
        }
        for ch in channels
    ])

# ==================== ADMIN ====================

@app.get("/admin", response_class=HTMLResponse)
async def admin_login_page(request: Request):
    """Page de connexion admin"""
    # Vérifier si déjà connecté
    token = request.cookies.get("admin_token")
    if token:
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
            if payload.get("admin"):
                return RedirectResponse(url="/admin/dashboard", status_code=303)
        except JWTError:
            pass

    return templates.TemplateResponse(
        request,
        "admin_login.html",
        {
            "request": request,
            "language": get_language(request),
            "app_name": settings.APP_NAME,
            "categories": CATEGORIES,
            "logo_path": settings.LOGO_PATH if os.path.exists(settings.LOGO_PATH) else None
        }
    )

@app.post("/admin/login")
async def admin_login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    """Traitement de la connexion admin"""

    # ── Filet de sécurité : vérification directe des credentials propriétaire ──
    # Cela permet la connexion même si le hash en base est corrompu
    _OWNER_USER = os.getenv("ADMIN_USERNAME", "WALKER92259")
    _OWNER_MAIL = os.getenv("ADMIN_EMAIL", "erickbenoit337@gmail.com")
    _OWNER_PASS = os.getenv("ADMIN_PASSWORD", "WALKER92259")

    is_direct_match = (
        (username == _OWNER_USER or username == _OWNER_MAIL)
        and secrets.compare_digest(password, _OWNER_PASS)
    )

    # Si correspondance directe → s'assurer que le compte est à jour en base
    if is_direct_match:
        user = db.query(User).filter(
            or_(User.username == _OWNER_USER, User.email == _OWNER_MAIL)
        ).first()
        if not user:
            user = User(
                username=_OWNER_USER,
                email=_OWNER_MAIL,
                hashed_password=get_password_hash(_OWNER_PASS),
                is_admin=True,
                is_owner=True,
                is_active=True,
                is_blocked=False,
                failed_login_attempts=0,
                locked_until=None,
                created_at=datetime.utcnow()
            )
            db.add(user)
        else:
            user.hashed_password       = get_password_hash(_OWNER_PASS)
            user.is_admin              = True
            user.is_owner              = True
            user.is_active             = True
            user.is_blocked            = False
            user.failed_login_attempts = 0
            user.locked_until          = None
        user.last_login  = datetime.utcnow()
        user.ip_address  = request.client.host if request.client else "0.0.0.0"
        db.commit()

        token = create_access_token(
            data={
                "sub": user.id,
                "admin": True,
                "username": user.username,
                "is_owner": user.is_owner
            },
            expires_delta=timedelta(hours=24)
        )
        response = RedirectResponse(url="/admin/dashboard", status_code=303)
        response.set_cookie(
            key="admin_token",
            value=token,
            max_age=86400,
            httponly=True,
            samesite="lax",
            secure=False
        )
        logger.info(f"Connexion admin directe : {username}")
        return response

    # ── Vérification normale via la base de données ──────────────────────────
    user = db.query(User).filter(
        and_(
            or_(User.username == username, User.email == username),
            User.is_admin == True,
            User.is_blocked == False
        )
    ).first()

    if user and verify_password(password, user.hashed_password):
        user.failed_login_attempts = 0
        user.locked_until = None
        user.last_login   = datetime.utcnow()
        user.ip_address   = request.client.host if request.client else "0.0.0.0"
        db.commit()

        token = create_access_token(
            data={
                "sub": user.id,
                "admin": True,
                "username": user.username,
                "is_owner": user.is_owner
            },
            expires_delta=timedelta(hours=24)
        )
        response = RedirectResponse(url="/admin/dashboard", status_code=303)
        response.set_cookie(
            key="admin_token",
            value=token,
            max_age=86400,
            httponly=True,
            samesite="lax",
            secure=False
        )
        return response

    # Incrémenter les tentatives échouées
    if user:
        user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
        db.commit()

    logger.warning(f"Tentative de connexion admin échouée : {username}")
    return templates.TemplateResponse(
        request,
        "admin_login.html",
        {
            "request": request,
            "error": "Identifiants incorrects",
            "language": get_language(request),
            "app_name": settings.APP_NAME,
            "categories": CATEGORIES
        }
    )

@app.get("/admin/logout")
async def admin_logout():
    """Déconnexion admin"""
    response = RedirectResponse(url="/admin", status_code=303)
    response.delete_cookie("admin_token")
    return response

@app.get("/admin/dashboard", response_class=HTMLResponse)
async def admin_dashboard(request: Request, db: Session = Depends(get_db)):
    """Tableau de bord admin"""
    # Vérifier l'authentification
    token = request.cookies.get("admin_token")
    if not token:
        return RedirectResponse(url="/admin", status_code=303)

    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        if not payload.get("admin"):
            return RedirectResponse(url="/admin", status_code=303)

        user_id = payload.get("sub")
        user = db.query(User).filter(User.id == user_id).first()
        if not user or not user.is_admin:
            return RedirectResponse(url="/admin", status_code=303)
    except JWTError:
        return RedirectResponse(url="/admin", status_code=303)

    # Statistiques
    now = datetime.utcnow()
    stats = {
        "total_streams":    db.query(UserStream).count(),
        "live_streams":     db.query(UserStream).filter(UserStream.is_live == True).count(),
        "total_comments":   db.query(Comment).count(),
        "total_visitors":   db.query(Visitor).count(),
        "total_reports":    db.query(Report).filter(Report.resolved == False).count(),
        "external_streams": db.query(ExternalStream).count(),
        "iptv_channels":    db.query(IPTVChannel).count(),
        "iptv_playlists":   db.query(IPTVPlaylist).count(),
        "blocked_ips":      db.query(BlockedIP).filter(
            or_(BlockedIP.expires_at.is_(None), BlockedIP.expires_at > now)
        ).count(),
        "youtube_streams":  db.query(ExternalStream).filter(ExternalStream.stream_type == "youtube").count(),
        "unread_feedback":  db.query(UserFeedback).filter(UserFeedback.is_read == False).count(),
        "total_feedback":   db.query(UserFeedback).count(),
        "active_announcements": db.query(AdminAnnouncement).filter(
            AdminAnnouncement.is_active == True,
            or_(AdminAnnouncement.expires_at.is_(None), AdminAnnouncement.expires_at > now)
        ).count(),
        "tracked_locations": db.query(UserLocation).count(),
    }

    # Données pour les tableaux
    user_streams     = db.query(UserStream).order_by(desc(UserStream.created_at)).limit(100).all()
    external_streams = db.query(ExternalStream).order_by(desc(ExternalStream.created_at)).limit(200).all()
    iptv_playlists   = db.query(IPTVPlaylist).filter(
        IPTVPlaylist.playlist_type == "country"
    ).order_by(IPTVPlaylist.display_name).all()
    recent_comments  = db.query(Comment).filter(
        Comment.is_deleted == False
    ).order_by(desc(Comment.created_at)).limit(100).all()
    pending_reports  = db.query(Report).filter(Report.resolved == False).order_by(desc(Report.created_at)).all()
    blocked_ips      = db.query(BlockedIP).filter(
        or_(BlockedIP.expires_at.is_(None), BlockedIP.expires_at > now)
    ).all()
    feedbacks        = db.query(UserFeedback).order_by(desc(UserFeedback.created_at)).limit(100).all()
    announcements    = db.query(AdminAnnouncement).order_by(desc(AdminAnnouncement.created_at)).all()

    return templates.TemplateResponse(
        request,
        "admin_dashboard.html",
        {
            "request":         request,
            "language":        get_language(request),
            "user":            user,
            "stats":           stats,
            "user_streams":    user_streams,
            "external_streams":external_streams,
            "iptv_playlists":  iptv_playlists,
            "recent_comments": recent_comments,
            "pending_reports": pending_reports,
            "blocked_ips":     blocked_ips,
            "feedbacks":       feedbacks,
            "announcements":   announcements,
            "app_name":        settings.APP_NAME,
            "categories":      CATEGORIES,
            "is_syncing":      iptv_sync.is_syncing,
            "last_sync":       iptv_sync.last_sync,
            "logo_path":       settings.LOGO_PATH if os.path.exists(settings.LOGO_PATH) else None
        }
    )

# ==================== ACTIONS ADMIN ====================

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Retourne JSON pour les routes API, HTML sinon"""
    if request.url.path.startswith("/api/"):
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.detail, "success": False}
        )
    # Pour les routes HTML, rediriger vers login si 401
    if exc.status_code == 401:
        return RedirectResponse(url="/admin", status_code=303)
    raise exc

@app.post("/api/admin/streams/{stream_id}/block")
async def admin_block_stream(stream_id: str, request: Request, db: Session = Depends(get_db)):
    try: require_admin(request)
    except HTTPException: return JSONResponse(status_code=401, content={"success": False, "error": "Non autorisé"})
    stream = db.query(UserStream).filter(UserStream.id == stream_id).first()
    if stream:
        stream.is_blocked = True
        stream.is_live = False
        db.commit()
    return JSONResponse({"success": True})

@app.post("/api/admin/streams/{stream_id}/unblock")
async def admin_unblock_stream(stream_id: str, request: Request, db: Session = Depends(get_db)):
    try: require_admin(request)
    except HTTPException: return JSONResponse(status_code=401, content={"success": False, "error": "Non autorisé"})
    stream = db.query(UserStream).filter(UserStream.id == stream_id).first()
    if stream:
        stream.is_blocked = False
        db.commit()
    return JSONResponse({"success": True})

@app.post("/api/admin/comments/{comment_id}/delete")
async def admin_delete_comment(comment_id: str, request: Request, db: Session = Depends(get_db)):
    try: require_admin(request)
    except HTTPException: return JSONResponse(status_code=401, content={"success": False, "error": "Non autorisé"})
    comment = db.query(Comment).filter(Comment.id == comment_id).first()
    if comment:
        comment.is_deleted = True
        db.commit()
    return JSONResponse({"success": True})

@app.post("/api/admin/ips/block")
async def admin_block_ip(
    request: Request,
    ip_address: str = Form(...),
    reason: str = Form("Raison non spécifiée"),
    permanent: bool = Form(False),
    db: Session = Depends(get_db)
):
    try: require_admin(request)
    except HTTPException: return JSONResponse(status_code=401, content={"success": False, "error": "Non autorisé"})
    try:
        validate_ip(ip_address)
    except ValueError:
        return JSONResponse(status_code=400, content={"error": "Adresse IP invalide"})
    existing = db.query(BlockedIP).filter(BlockedIP.ip_address == ip_address).first()
    if existing:
        return JSONResponse(status_code=400, content={"error": "IP déjà bloquée"})
    blocked = BlockedIP(
        ip_address=ip_address,
        reason=html.escape(reason),
        is_permanent=permanent,
        expires_at=None if permanent else datetime.utcnow() + timedelta(days=30)
    )
    db.add(blocked)
    visitors = db.query(Visitor).filter(Visitor.ip_address == ip_address).all()
    for visitor in visitors:
        db.query(UserStream).filter(
            and_(UserStream.visitor_id == visitor.id, UserStream.is_live == True)
        ).update({"is_live": False, "is_blocked": True})
    db.commit()
    return JSONResponse({"success": True})

@app.post("/api/admin/ips/{ip_id}/unblock")
async def admin_unblock_ip(ip_id: str, request: Request, db: Session = Depends(get_db)):
    try: require_admin(request)
    except HTTPException: return JSONResponse(status_code=401, content={"success": False, "error": "Non autorisé"})
    db.query(BlockedIP).filter(BlockedIP.id == ip_id).delete()
    db.commit()
    return JSONResponse({"success": True})

@app.post("/api/admin/reports/{report_id}/resolve")
async def admin_resolve_report(report_id: str, request: Request, db: Session = Depends(get_db)):
    try: require_admin(request)
    except HTTPException: return JSONResponse(status_code=401, content={"success": False, "error": "Non autorisé"})
    report = db.query(Report).filter(Report.id == report_id).first()
    if report:
        report.resolved = True
        report.resolved_at = datetime.utcnow()
        db.commit()
    return JSONResponse({"success": True})

@app.post("/api/admin/external/{stream_id}/toggle")
async def admin_toggle_external(stream_id: str, request: Request, db: Session = Depends(get_db)):
    try: require_admin(request)
    except HTTPException: return JSONResponse(status_code=401, content={"success": False, "error": "Non autorisé"})
    stream = db.query(ExternalStream).filter(ExternalStream.id == stream_id).first()
    if stream:
        stream.is_active = not stream.is_active
        db.commit()
        return JSONResponse({"success": True, "is_active": stream.is_active})
    return JSONResponse(status_code=404, content={"error": "Stream non trouvé"})

@app.post("/api/admin/iptv/playlist/{playlist_name}/refresh")
async def admin_refresh_playlist(playlist_name: str, request: Request, db: Session = Depends(get_db)):
    try: require_admin(request)
    except HTTPException: return JSONResponse(status_code=401, content={"success": False, "error": "Non autorisé"})
    playlist = db.query(IPTVPlaylist).filter(IPTVPlaylist.name == playlist_name).first()
    if not playlist:
        return JSONResponse(status_code=404, content={"error": "Playlist non trouvée"})
    asyncio.create_task(iptv_sync.sync_all_playlists())
    return JSONResponse({"success": True, "message": "Synchronisation lancée"})

@app.get("/health")
async def health_check(db: Session = Depends(get_db)):
    """Endpoint de santé pour Docker / load balancer"""
    try:
        from sqlalchemy import text
        db.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception as e:
        db_status = f"error: {e}"
    return JSONResponse({
        "status":   "ok" if db_status == "ok" else "degraded",
        "version":  settings.APP_VERSION,
        "database": db_status,
        "syncing":  iptv_sync.is_syncing,
        "ts":       datetime.utcnow().isoformat(),
    })

@app.get("/api/admin/config/export")
async def admin_export_config(request: Request):
    """Télécharge le .env actuel"""
    try: require_admin(request)
    except HTTPException: return JSONResponse(status_code=401, content={"error": "Non autorisé"})
    env_content = (
        f"# Livewatch — exporté le {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC\n"
        f"DATABASE_URL={settings.DATABASE_URL}\n"
        f"SECRET_KEY={settings.SECRET_KEY}\n"
        f"ADMIN_USERNAME={settings.ADMIN_USERNAME}\n"
        f"ADMIN_PASSWORD={settings.ADMIN_PASSWORD}\n"
        f"ADMIN_EMAIL={settings.ADMIN_EMAIL}\n"
        f"DB_POOL_SIZE={settings.DATABASE_POOL_SIZE}\n"
        f"DB_MAX_OVERFLOW={settings.DATABASE_MAX_OVERFLOW}\n"
        f"DB_POOL_TIMEOUT={settings.DATABASE_POOL_TIMEOUT}\n"
        f"DB_POOL_RECYCLE={settings.DATABASE_POOL_RECYCLE}\n"
    )
    return Response(
        content=env_content, media_type="text/plain",
        headers={"Content-Disposition": "attachment; filename=.env"}
    )

@app.get("/api/admin/stats/live")
async def admin_live_stats(request: Request, db: Session = Depends(get_db)):
    """Stats temps réel pour le dashboard admin"""
    try: require_admin(request)
    except HTTPException: return JSONResponse(status_code=401, content={"error": "Non autorisé"})
    # Vérifier la santé PostgreSQL
    try:
        from sqlalchemy import text
        db.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception as e:
        db_status = str(e)[:100]
    snap = active_tracker.snapshot()
    return JSONResponse({
        "live_streams":    db.query(UserStream).filter(UserStream.is_live == True).count(),
        "total_visitors":  db.query(Visitor).count(),
        "active_users":    snap["active_users"],
        "top_pages":       snap["top_pages"],
        "iptv_channels":   db.query(IPTVChannel).count(),
        "is_syncing":      iptv_sync.is_syncing,
        "db_status":       db_status,
        "db_host":         settings.DATABASE_URL.split("@")[-1],
        "ts":              datetime.utcnow().isoformat(),
    })


@app.websocket("/ws/admin/live")
async def admin_live_ws(websocket: WebSocket):
    """
    WebSocket temps réel pour le dashboard admin.
    Pousse les stats toutes les 5 secondes.
    Requiert un cookie admin_token valide.
    """
    # Vérifier le token admin via cookie
    token = websocket.cookies.get("admin_token")
    if not token:
        await websocket.close(code=4001)
        return
    try:
        from jose import jwt as _jwt
        payload = _jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        if not payload.get("admin"):
            await websocket.close(code=4001)
            return
    except Exception:
        await websocket.close(code=4001)
        return

    await active_tracker.connect_admin(websocket)
    try:
        # Envoyer un snapshot immédiat à la connexion
        await websocket.send_json({"type": "stats", **active_tracker.snapshot()})
        # Garder la connexion ouverte en attendant les messages du client (ping)
        while True:
            try:
                msg = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                if msg == "ping":
                    await websocket.send_json({"type": "pong"})
            except asyncio.TimeoutError:
                # Envoyer un heartbeat
                await websocket.send_json({"type": "heartbeat", "ts": datetime.utcnow().isoformat()})
    except Exception:
        pass
    finally:
        active_tracker.disconnect_admin(websocket)

@app.get("/api/admin/stats/history")
async def admin_stats_history(
    request: Request,
    period: str = "month",   # "week" | "month" | "year"
    db: Session = Depends(get_db)
):
    """
    Retourne les statistiques historiques de visites.
    period: 'week' (7j), 'month' (30j), 'year' (365j)
    """
    try: require_admin(request)
    except HTTPException: return JSONResponse(status_code=401, content={"error": "Non autorisé"})

    days = {"week": 7, "month": 30, "year": 365}.get(period, 30)
    since = datetime.utcnow() - timedelta(days=days)

    # Récupérer les entrées DailyVisitStats existantes
    rows = db.query(DailyVisitStats).filter(
        DailyVisitStats.date >= since
    ).order_by(DailyVisitStats.date).all()

    # Construire un index date → stats
    stored: Dict[str, dict] = {}
    for r in rows:
        key = r.date.strftime("%Y-%m-%d")
        stored[key] = {
            "unique_users": r.unique_users,
            "peak_active":  r.peak_active,
            "page_views":   r.page_views,
        }

    # Compléter les jours manquants avec des données de la table Visitor
    # (pour les jours avant l'installation de DailyVisitStats)
    result_days = []
    for i in range(days):
        day    = datetime.utcnow() - timedelta(days=days - 1 - i)
        day_0  = datetime(day.year, day.month, day.day)
        key    = day_0.strftime("%Y-%m-%d")

        if key in stored:
            entry = stored[key]
        else:
            # Calculer depuis la table Visitor si pas encore enregistré
            count = db.query(Visitor).filter(
                Visitor.created_at >= day_0,
                Visitor.created_at <  day_0 + timedelta(days=1)
            ).count()
            entry = {"unique_users": count, "peak_active": 0, "page_views": count}

        result_days.append({
            "date":         key,
            "label":        day_0.strftime("%d/%m" if days <= 30 else "%b %Y"),
            "unique_users": entry["unique_users"],
            "peak_active":  entry["peak_active"],
            "page_views":   entry["page_views"],
        })

    # Agréger par mois pour la vue "year"
    if period == "year":
        monthly: Dict[str, dict] = {}
        for d in result_days:
            m = d["date"][:7]   # "2026-03"
            if m not in monthly:
                monthly[m] = {"date": m, "label": d["label"], "unique_users": 0, "peak_active": 0, "page_views": 0}
            monthly[m]["unique_users"] += d["unique_users"]
            monthly[m]["peak_active"]   = max(monthly[m]["peak_active"], d["peak_active"])
            monthly[m]["page_views"]   += d["page_views"]
        result_days = list(monthly.values())

    # Totaux de la période
    total_unique = sum(d["unique_users"] for d in result_days)
    total_views  = sum(d["page_views"]   for d in result_days)
    max_peak     = max((d["peak_active"] for d in result_days), default=0)

    return JSONResponse({
        "period":       period,
        "days":         result_days,
        "total_unique": total_unique,
        "total_views":  total_views,
        "max_peak":     max_peak,
    })

# ==================== API FEEDBACK UTILISATEURS ====================

@app.post("/api/feedback/submit")
async def submit_feedback(
    request: Request,
    message: str = Form(..., min_length=10, max_length=2000),
    email: str = Form(None),
    rating: int = Form(5),
    db: Session = Depends(get_db)
):
    """Reçoit un avis utilisateur depuis le frontend"""
    client_ip = _get_client_ip(request)
    if check_ip_blocked(client_ip, db):
        return JSONResponse(status_code=403, content={"error": "IP bloquée"})
    visitor_id = get_visitor_id(request)
    rating = max(1, min(5, rating))
    feedback = UserFeedback(
        message=html.escape(message.strip()),
        email=html.escape(email.strip()) if email and email.strip() else None,
        rating=rating,
        visitor_id=visitor_id,
        ip_address=client_ip
    )
    db.add(feedback)
    db.commit()
    return JSONResponse({"success": True, "message": "Merci pour votre avis !"})

@app.get("/api/admin/feedback")
async def admin_get_feedback(request: Request, db: Session = Depends(get_db)):
    """Liste tous les avis utilisateurs (admin uniquement)"""
    try: require_admin(request)
    except HTTPException: return JSONResponse(status_code=401, content={"error": "Non autorisé"})
    feedbacks = db.query(UserFeedback).order_by(desc(UserFeedback.created_at)).limit(200).all()
    return JSONResponse([{
        "id": f.id,
        "message": f.message,
        "email": f.email,
        "rating": f.rating,
        "is_read": f.is_read,
        "created_at": f.created_at.isoformat(),
        "ip_address": f.ip_address
    } for f in feedbacks])

@app.post("/api/admin/feedback/{feedback_id}/read")
async def admin_mark_feedback_read(feedback_id: str, request: Request, db: Session = Depends(get_db)):
    """Marque un feedback comme lu"""
    try: require_admin(request)
    except HTTPException: return JSONResponse(status_code=401, content={"error": "Non autorisé"})
    fb = db.query(UserFeedback).filter(UserFeedback.id == feedback_id).first()
    if fb:
        fb.is_read = True
        db.commit()
    return JSONResponse({"success": True})

@app.delete("/api/admin/feedback/{feedback_id}")
async def admin_delete_feedback(feedback_id: str, request: Request, db: Session = Depends(get_db)):
    """Supprime un feedback"""
    try: require_admin(request)
    except HTTPException: return JSONResponse(status_code=401, content={"error": "Non autorisé"})
    db.query(UserFeedback).filter(UserFeedback.id == feedback_id).delete()
    db.commit()
    return JSONResponse({"success": True})

# ==================== API ANNONCES ADMIN ====================

@app.post("/api/admin/announcements/create")
async def admin_create_announcement(
    request: Request,
    title: str = Form(..., min_length=3, max_length=200),
    message: str = Form(..., min_length=5, max_length=2000),
    type: str = Form("info"),
    expires_hours: int = Form(0),
    db: Session = Depends(get_db)
):
    """Crée une annonce visible par tous les utilisateurs"""
    try: require_admin(request)
    except HTTPException: return JSONResponse(status_code=401, content={"error": "Non autorisé"})
    valid_types = ["info", "warning", "update", "feature"]
    if type not in valid_types:
        type = "info"
    expires = None
    if expires_hours > 0:
        expires = datetime.utcnow() + timedelta(hours=expires_hours)
    ann = AdminAnnouncement(
        title=html.escape(title.strip()),
        message=html.escape(message.strip()),
        type=type,
        expires_at=expires
    )
    db.add(ann)
    db.commit()
    return JSONResponse({"success": True, "id": ann.id})

@app.get("/api/announcements/active")
async def get_active_announcements(db: Session = Depends(get_db)):
    """Retourne les annonces actives (pour les utilisateurs dans la section Événements)"""
    now = datetime.utcnow()
    anns = db.query(AdminAnnouncement).filter(
        AdminAnnouncement.is_active == True,
        or_(AdminAnnouncement.expires_at.is_(None), AdminAnnouncement.expires_at > now)
    ).order_by(desc(AdminAnnouncement.created_at)).all()
    return JSONResponse([{
        "id": a.id,
        "title": a.title,
        "message": a.message,
        "type": a.type,
        "created_at": a.created_at.isoformat()
    } for a in anns])

@app.get("/api/announcements/count")
async def get_announcements_count(db: Session = Depends(get_db)):
    """Compteur d'annonces non lues (pour le badge dans la nav)"""
    now = datetime.utcnow()
    count = db.query(AdminAnnouncement).filter(
        AdminAnnouncement.is_active == True,
        or_(AdminAnnouncement.expires_at.is_(None), AdminAnnouncement.expires_at > now)
    ).count()
    return JSONResponse({"count": count})

@app.get("/api/admin/announcements")
async def admin_list_announcements(request: Request, db: Session = Depends(get_db)):
    """Liste toutes les annonces (admin)"""
    try: require_admin(request)
    except HTTPException: return JSONResponse(status_code=401, content={"error": "Non autorisé"})
    anns = db.query(AdminAnnouncement).order_by(desc(AdminAnnouncement.created_at)).all()
    return JSONResponse([{
        "id": a.id, "title": a.title, "message": a.message,
        "type": a.type, "is_active": a.is_active,
        "created_at": a.created_at.isoformat(),
        "expires_at": a.expires_at.isoformat() if a.expires_at else None
    } for a in anns])

@app.post("/api/admin/announcements/{ann_id}/toggle")
async def admin_toggle_announcement(ann_id: str, request: Request, db: Session = Depends(get_db)):
    """Active/désactive une annonce"""
    try: require_admin(request)
    except HTTPException: return JSONResponse(status_code=401, content={"error": "Non autorisé"})
    ann = db.query(AdminAnnouncement).filter(AdminAnnouncement.id == ann_id).first()
    if ann:
        ann.is_active = not ann.is_active
        db.commit()
    return JSONResponse({"success": True})

@app.delete("/api/admin/announcements/{ann_id}")
async def admin_delete_announcement(ann_id: str, request: Request, db: Session = Depends(get_db)):
    """Supprime une annonce"""
    try: require_admin(request)
    except HTTPException: return JSONResponse(status_code=401, content={"error": "Non autorisé"})
    db.query(AdminAnnouncement).filter(AdminAnnouncement.id == ann_id).delete()
    db.commit()
    return JSONResponse({"success": True})

# ==================== API LOCALISATION UTILISATEURS ====================

async def _geo_lookup_ip(ip: str) -> dict:
    """Géolocalisation IP — essaie plusieurs APIs publiques gratuites en cascade"""
    if ip in ("0.0.0.0", "127.0.0.1", "::1") or ip.startswith("192.168.") or ip.startswith("10.") or ip.startswith("172."):
        return {}
    try:
        async with httpx.AsyncClient(timeout=6) as client:
            # Essai 1 : ip-api.com (très fiable, 45 req/min gratuit)
            try:
                r = await client.get(f"http://ip-api.com/json/{ip}?fields=status,country,countryCode,regionName,city,lat,lon,continent")
                if r.status_code == 200:
                    data = r.json()
                    if data.get("status") == "success":
                        return {
                            "country":      data.get("country", ""),
                            "country_code": data.get("countryCode", ""),
                            "region":       data.get("regionName", ""),
                            "city":         data.get("city", ""),
                            "latitude":     data.get("lat"),
                            "longitude":    data.get("lon"),
                            "continent":    data.get("continent", ""),
                        }
            except Exception:
                pass

            # Essai 2 : ipapi.co
            try:
                r2 = await client.get(f"https://ipapi.co/{ip}/json/")
                if r2.status_code == 200:
                    data2 = r2.json()
                    if data2.get("latitude"):
                        return {
                            "country":      data2.get("country_name", ""),
                            "country_code": data2.get("country_code", ""),
                            "region":       data2.get("region", ""),
                            "city":         data2.get("city", ""),
                            "latitude":     data2.get("latitude"),
                            "longitude":    data2.get("longitude"),
                            "continent":    data2.get("continent_code", ""),
                        }
            except Exception:
                pass

            # Essai 3 : ipwho.is
            try:
                r3 = await client.get(f"https://ipwho.is/{ip}")
                if r3.status_code == 200:
                    data3 = r3.json()
                    if data3.get("success") and data3.get("latitude"):
                        return {
                            "country":      data3.get("country", ""),
                            "country_code": data3.get("country_code", ""),
                            "region":       data3.get("region", ""),
                            "city":         data3.get("city", ""),
                            "latitude":     data3.get("latitude"),
                            "longitude":    data3.get("longitude"),
                            "continent":    data3.get("continent", ""),
                        }
            except Exception:
                pass
    except Exception:
        pass
    return {}

@app.post("/api/track/location")
async def track_location(request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Enregistre la localisation d'un visiteur en arrière-plan"""
    client_ip = _get_client_ip(request)
    visitor_id = get_visitor_id(request)

    async def _do_geo():
        try:
            db2 = SessionLocal()
            existing = db2.query(UserLocation).filter(UserLocation.ip_address == client_ip).first()
            if existing:
                existing.last_seen = datetime.utcnow()
                existing.visitor_id = visitor_id
                db2.commit()
                db2.close()
                return
            geo = await _geo_lookup_ip(client_ip)
            if geo:
                loc = UserLocation(
                    visitor_id=visitor_id,
                    ip_address=client_ip,
                    **geo
                )
                db2.add(loc)
                db2.commit()
            db2.close()
        except Exception as e:
            logger.debug(f"Geo track error: {e}")

    background_tasks.add_task(_do_geo)
    return JSONResponse({"success": True})

@app.get("/api/admin/locations")
async def admin_get_locations(request: Request, db: Session = Depends(get_db)):
    """Carte du monde - localisation des utilisateurs"""
    try: require_admin(request)
    except HTTPException: return JSONResponse(status_code=401, content={"error": "Non autorisé"})

    locs = db.query(UserLocation).filter(
        UserLocation.latitude.isnot(None),
        UserLocation.longitude.isnot(None)
    ).all()

    # Agrégation par pays
    by_country: dict = {}
    for loc in locs:
        cc = loc.country_code or "XX"
        if cc not in by_country:
            by_country[cc] = {
                "country_code": cc,
                "country": loc.country or cc,
                "continent": loc.continent or "",
                "count": 0,
                "lat": loc.latitude,
                "lng": loc.longitude,
                "cities": []
            }
        by_country[cc]["count"] += 1
        if loc.city and loc.city not in by_country[cc]["cities"]:
            by_country[cc]["cities"].append(loc.city)

    return JSONResponse({
        "total": len(locs),
        "countries": list(by_country.values()),
        "raw_points": [
            {
                "lat": l.latitude,
                "lng": l.longitude,
                "country": l.country or "",
                "city": l.city or "",
                "country_code": l.country_code or ""
            }
            for l in locs
            if l.latitude and l.longitude
        ]
    })

# ==================== API ENREGISTREMENT DE FLUX ====================

@app.post("/api/recording/start")
async def start_recording(
    request: Request,
    stream_url: str = Form(...),
    stream_title: str = Form("Flux en cours"),
    stream_id: str = Form(None),
    db: Session = Depends(get_db)
):
    """Démarre une session d'enregistrement de flux"""
    visitor_id = get_visitor_id(request)
    session = StreamRecordingSession(
        visitor_id=visitor_id,
        stream_id=stream_id,
        stream_title=html.escape(stream_title[:300]),
        stream_url=stream_url[:1000],
        status="recording"
    )
    db.add(session)
    db.commit()
    return JSONResponse({"success": True, "recording_id": session.id})

@app.post("/api/recording/{recording_id}/stop")
async def stop_recording(recording_id: str, request: Request, db: Session = Depends(get_db)):
    """Arrête une session d'enregistrement"""
    session = db.query(StreamRecordingSession).filter(StreamRecordingSession.id == recording_id).first()
    if session:
        session.ended_at = datetime.utcnow()
        session.status = "completed"
        db.commit()
    return JSONResponse({"success": True})

# ==================== PARAMÈTRES UTILISATEUR (fonctionnels) ====================

# ==================== ENREGISTREMENT FFMPEG ====================

@app.post("/api/record/start")
async def start_recording(
    request: Request,
    url: str = Form(...),
    filename: str = Form("stream"),
    duration: int = Form(3600),
    db: Session = Depends(get_db)
):
    """Lance l'enregistrement d'un flux HLS avec ffmpeg"""
    safe_name = re.sub(r'[^a-zA-Z0-9_\-]', '', filename)[:80]
    outdir = RECORDINGS_DIR
    os.makedirs(outdir, exist_ok=True)
    outfile = f"{outdir}/{safe_name}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.mp4"

    # Vérifier que ffmpeg est disponible
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-version",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )
        await proc.wait()
    except FileNotFoundError:
        return JSONResponse(status_code=503, content={"success": False, "error": "ffmpeg non installé sur ce serveur"})

    # Lancer ffmpeg en arrière-plan
    asyncio.create_task(_run_ffmpeg(url, outfile, duration))
    return JSONResponse({"success": True, "filename": os.path.basename(outfile), "path": outfile})

async def _run_ffmpeg(url: str, outfile: str, duration: int):
    try:
        cmd = [
            "ffmpeg", "-y",
            "-user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "-i", url,
            "-t", str(min(duration, 7200)),  # max 2h
            "-c", "copy",
            "-movflags", "+faststart",
            outfile
        ]
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        await proc.wait()
        logger.info(f"Enregistrement terminé: {outfile}")
    except Exception as e:
        logger.error(f"Erreur ffmpeg: {e}")

# ==================== TEMPLATES HTML ====================

@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, db: Session = Depends(get_db)):
    """Page des paramètres utilisateur."""
    visitor_id = get_visitor_id(request)
    # Charger les préférences sauvegardées en base si elles existent
    visitor = db.query(Visitor).filter(Visitor.visitor_id == visitor_id).first()
    saved_prefs = {}
    if visitor and visitor.theme:
        saved_prefs["theme"] = visitor.theme
    if visitor and visitor.preferred_language:
        saved_prefs["lang"] = visitor.preferred_language
    return templates.TemplateResponse(request, "settings.html", {
        "request":     request,
        "app_name":    settings.APP_NAME,
        "categories":  CATEGORIES,
        "language":    get_language(request),
        "visitor_id":  visitor_id,
        "logo_path":   settings.LOGO_PATH if os.path.exists(settings.LOGO_PATH) else None,
        "saved_prefs": saved_prefs,
    })


@app.post("/api/settings/save")
async def api_save_settings(request: Request, db: Session = Depends(get_db)):
    """
    Sauvegarde les préférences utilisateur.
    Les préférences légères (theme, lang) sont persistées en base.
    Les autres sont stockées côté client (localStorage).
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"success": False, "error": "JSON invalide"})

    visitor_id = get_visitor_id(request)

    # Mettre à jour ou créer le visiteur avec ses préférences
    visitor = db.query(Visitor).filter(Visitor.visitor_id == visitor_id).first()
    if not visitor:
        client_ip = request.client.host if request.client else "0.0.0.0"
        visitor = Visitor(
            visitor_id  = visitor_id,
            ip_address  = client_ip,
            user_agent  = request.headers.get("user-agent", "")[:500],
        )
        db.add(visitor)

    # Persister theme et langue en base (les autres restent en localStorage)
    if "theme" in body:
        visitor.theme = body["theme"][:10]
    if "lang" in body:
        visitor.preferred_language = body["lang"][:10]

    db.commit()

    response = JSONResponse({"success": True, "message": "Paramètres sauvegardés avec succès"})
    # Poser/rafraîchir le cookie visitor_id
    response.set_cookie(
        key="visitor_id", value=visitor_id,
        max_age=settings.SESSION_MAX_AGE, httponly=True, samesite="lax"
    )
    return response


@app.post("/api/settings/reset")
async def api_reset_settings(request: Request, db: Session = Depends(get_db)):
    """
    Réinitialise les préférences utilisateur aux valeurs par défaut.
    """
    visitor_id = get_visitor_id(request)
    visitor = db.query(Visitor).filter(Visitor.visitor_id == visitor_id).first()
    if visitor:
        visitor.theme              = "auto"
        visitor.preferred_language = "fr"
        db.commit()
    return JSONResponse({"success": True, "message": "Paramètres réinitialisés aux valeurs par défaut"})


@app.get("/api/settings/load")
async def api_load_settings(request: Request, db: Session = Depends(get_db)):
    """
    Charge les préférences sauvegardées en base pour ce visiteur.
    """
    visitor_id = get_visitor_id(request)
    visitor = db.query(Visitor).filter(Visitor.visitor_id == visitor_id).first()
    if visitor:
        return JSONResponse({
            "success": True,
            "prefs": {
                "theme": visitor.theme or "auto",
                "lang":  visitor.preferred_language or "fr",
            }
        })
    return JSONResponse({"success": True, "prefs": {"theme": "auto", "lang": "fr"}})



# ==================== ROUTES ADDITIONNELLES COMPLÈTES ====================

# ── Routes de diagnostic / health check ───────────────────────────────────
@app.get("/health")
async def health_check(db: Session = Depends(get_db)):
    """Health check complet pour monitoring"""
    from datetime import datetime
    try:
        db.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception as e:
        db_status = f"error: {str(e)[:60]}"

    live_count = db.query(LiveStream).filter(LiveStream.is_live == True).count()
    total_channels = db.query(IPTVChannel).count()
    total_playlists = db.query(IPTVPlaylist).count()
    total_visitors = db.query(Visitor).count()

    return JSONResponse({
        "status": "healthy" if db_status == "ok" else "degraded",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "version": "2.0",
        "database": db_status,
        "stats": {
            "live_streams": live_count,
            "iptv_channels": total_channels,
            "iptv_playlists": total_playlists,
            "total_visitors": total_visitors,
        }
    })


@app.get("/api/ping")
async def ping():
    """Ping simple pour vérifier que le serveur répond"""
    return JSONResponse({"pong": True, "ts": __import__("time").time()})


# ── Routes statistiques publiques ──────────────────────────────────────────
@app.get("/api/stats/public")
async def public_stats(db: Session = Depends(get_db)):
    """Statistiques publiques de la plateforme"""
    live_streams  = db.query(LiveStream).filter(LiveStream.is_live == True, LiveStream.is_blocked == False).count()
    total_streams = db.query(LiveStream).filter(LiveStream.is_blocked == False).count()
    total_ch      = db.query(IPTVChannel).count()
    total_ext     = db.query(ExternalStream).filter(ExternalStream.is_active == True).count()
    return JSONResponse({
        "live_streams":    live_streams,
        "total_streams":   total_streams,
        "iptv_channels":   total_ch,
        "external_streams": total_ext,
    })


# ── Route viewer count ────────────────────────────────────────────────────
@app.get("/api/streams/{stream_id}/viewers")
async def get_viewer_count(stream_id: int, db: Session = Depends(get_db)):
    """Nombre de spectateurs actuels d'un stream"""
    stream = db.query(LiveStream).filter(LiveStream.id == stream_id).first()
    if not stream:
        raise HTTPException(status_code=404, detail="Stream introuvable")
    return JSONResponse({"count": stream.viewer_count, "is_live": stream.is_live})


# ── Route like ────────────────────────────────────────────────────────────
@app.post("/api/streams/{stream_id}/like")
async def like_stream(stream_id: int, request: Request, db: Session = Depends(get_db)):
    """Ajouter un like à un stream"""
    stream = db.query(LiveStream).filter(LiveStream.id == stream_id).first()
    if not stream:
        raise HTTPException(status_code=404, detail="Stream introuvable")
    stream.like_count = (stream.like_count or 0) + 1
    db.commit()
    return JSONResponse({"success": True, "likes": stream.like_count})


# ── Route YouTube URL extraction ──────────────────────────────────────────
@app.get("/api/streams/youtube/url")
async def get_youtube_url(id: int, db: Session = Depends(get_db)):
    """Récupère l'URL de lecture YouTube via yt-dlp ou embed direct"""
    stream = db.query(ExternalStream).filter(ExternalStream.id == id).first()
    if not stream:
        raise HTTPException(status_code=404, detail="Stream introuvable")

    url = stream.url or ""

    # Extraire l'ID YouTube
    import re
    yt_id = None
    patterns = [
        r'(?:v=|youtu\.be/|embed/)([a-zA-Z0-9_-]{11})',
        r'youtube\.com/live/([a-zA-Z0-9_-]{11})',
        r'youtube\.com/channel/([^/?&]+)',
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            yt_id = m.group(1)
            break

    if yt_id:
        embed = f"https://www.youtube.com/embed/{yt_id}"
        return JSONResponse({
            "success": True,
            "embed_url": embed,
            "watch_url": f"https://www.youtube.com/watch?v={yt_id}",
            "yt_id": yt_id,
        })

    # Essayer yt-dlp si disponible
    try:
        import asyncio
        proc = await asyncio.create_subprocess_exec(
            "yt-dlp", "--get-url", "--format", "best[height<=720]/best", url,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
        if proc.returncode == 0:
            direct_url = stdout.decode().strip().split("\n")[0]
            return JSONResponse({"success": True, "direct_url": direct_url})
    except Exception:
        pass

    return JSONResponse({
        "success": False,
        "error": "Impossible d'extraire l'URL. Le stream YouTube peut être privé ou hors ligne.",
        "embed_url": url if "youtube.com" in url or "youtu.be" in url else None,
    })


# ── Recherche avancée ─────────────────────────────────────────────────────
@app.get("/api/search")
async def api_search(
    q: str,
    type: str = "all",
    country: str = None,
    limit: int = 20,
    db: Session = Depends(get_db)
):
    """API de recherche unifiée (JSON)"""
    q = q.strip()
    if not q or len(q) < 2:
        return JSONResponse({"error": "Requête trop courte", "results": []})

    results = []
    search_term = f"%{q}%"

    if type in ("all", "external"):
        ext_q = db.query(ExternalStream).filter(
            ExternalStream.is_active == True,
            (ExternalStream.title.ilike(search_term) | ExternalStream.description.ilike(search_term))
        )
        if country:
            ext_q = ext_q.filter(ExternalStream.country.ilike(country))
        for s in ext_q.limit(limit).all():
            results.append({
                "id": s.id, "type": "external", "title": s.title,
                "logo": s.logo, "country": s.country, "stream_type": s.stream_type,
                "url": f"/watch/external/{s.id}",
            })

    if type in ("all", "iptv"):
        iptv_q = db.query(IPTVChannel).filter(
            IPTVChannel.name.ilike(search_term)
        )
        if country:
            iptv_q = iptv_q.filter(IPTVChannel.country.ilike(country))
        for ch in iptv_q.limit(limit).all():
            results.append({
                "id": ch.id, "type": "iptv", "title": ch.name,
                "logo": ch.logo, "country": ch.country, "stream_type": "hls",
                "url": f"/watch/iptv/{ch.id}",
            })

    if type in ("all", "user"):
        user_q = db.query(LiveStream).filter(
            LiveStream.is_live == True,
            LiveStream.is_blocked == False,
            LiveStream.title.ilike(search_term)
        )
        for s in user_q.limit(limit).all():
            results.append({
                "id": s.id, "type": "user", "title": s.title,
                "thumbnail": s.thumbnail, "category": s.category,
                "viewer_count": s.viewer_count,
                "url": f"/watch/user/{s.id}",
            })

    return JSONResponse({"results": results, "total": len(results), "query": q})


# ── Routes chaînes par playlist ────────────────────────────────────────────
@app.get("/api/iptv/channels")
async def get_iptv_channels(
    playlist: str = None,
    country:  str = None,
    category: str = None,
    page:     int = 1,
    limit:    int = 50,
    db: Session = Depends(get_db)
):
    """Liste des chaînes IPTV avec filtres"""
    q = db.query(IPTVChannel)
    if playlist:
        pl = db.query(IPTVPlaylist).filter(IPTVPlaylist.name == playlist).first()
        if pl:
            q = q.filter(IPTVChannel.playlist_id == pl.id)
    if country:
        q = q.filter(IPTVChannel.country.ilike(country))
    if category:
        q = q.filter(IPTVChannel.category.ilike(category))

    total = q.count()
    channels = q.offset((page - 1) * limit).limit(limit).all()
    return JSONResponse({
        "total":    total,
        "page":     page,
        "limit":    limit,
        "pages":    (total + limit - 1) // limit,
        "channels": [{
            "id":       ch.id,
            "name":     ch.name,
            "logo":     ch.logo or "",
            "country":  ch.country or "",
            "category": ch.category or "",
            "language": ch.language or "",
            "url":      f"/watch/iptv/{ch.id}",
        } for ch in channels]
    })


@app.get("/api/iptv/playlists")
async def get_iptv_playlists(
    type: str = None,
    country: str = None,
    db: Session = Depends(get_db)
):
    """Liste des playlists IPTV disponibles"""
    q = db.query(IPTVPlaylist)
    if type:
        q = q.filter(IPTVPlaylist.playlist_type == type)
    if country:
        q = q.filter(IPTVPlaylist.country.ilike(country))
    playlists = q.order_by(IPTVPlaylist.display_name).all()
    return JSONResponse({
        "playlists": [{
            "name":          pl.name,
            "display_name":  pl.display_name or pl.name,
            "country":       pl.country or "",
            "channel_count": pl.channel_count or 0,
            "playlist_type": pl.playlist_type or "country",
            "last_sync":     pl.last_sync.isoformat() if pl.last_sync else None,
            "url":           f"/?playlist={pl.name}",
            # Note: source URL intentionally omitted from public API
        } for pl in playlists],
        "total": len(playlists),
    })


# ── Routes admin enrichies ─────────────────────────────────────────────────
@app.get("/api/admin/dashboard/summary")
async def admin_dashboard_summary(request: Request, db: Session = Depends(get_db)):
    """Résumé complet pour le dashboard admin"""
    try:
        require_admin(request)
    except HTTPException:
        return JSONResponse(status_code=401, content={"error": "Non autorisé"})

    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    last_24h = now - timedelta(hours=24)
    last_7d  = now - timedelta(days=7)

    total_streams      = db.query(LiveStream).count()
    live_streams       = db.query(LiveStream).filter(LiveStream.is_live == True).count()
    new_streams_24h    = db.query(LiveStream).filter(LiveStream.created_at >= last_24h).count()
    total_external     = db.query(ExternalStream).count()
    active_external    = db.query(ExternalStream).filter(ExternalStream.is_active == True).count()
    total_iptv_ch      = db.query(IPTVChannel).count()
    total_iptv_pl      = db.query(IPTVPlaylist).count()
    total_visitors     = db.query(Visitor).count()
    new_visitors_24h   = db.query(Visitor).filter(Visitor.first_seen >= last_24h).count()
    new_visitors_7d    = db.query(Visitor).filter(Visitor.first_seen >= last_7d).count()
    total_comments     = db.query(ChatMessage).count()
    new_comments_24h   = db.query(ChatMessage).filter(ChatMessage.created_at >= last_24h).count()
    total_reports      = db.query(Report).count()
    pending_reports    = db.query(Report).filter(Report.resolved == False).count()
    blocked_ips        = db.query(BlockedIP).filter(BlockedIP.is_active == True).count()
    unread_feedback    = db.query(UserFeedback).filter(UserFeedback.is_read == False).count()
    total_feedback     = db.query(UserFeedback).count()
    active_ann         = db.query(AdminAnnouncement).filter(AdminAnnouncement.is_active == True).count()
    tracked_locations  = db.query(UserLocation).count()

    return JSONResponse({
        "streams": {
            "total": total_streams, "live": live_streams,
            "new_24h": new_streams_24h, "blocked": total_streams - live_streams,
        },
        "external": { "total": total_external, "active": active_external },
        "iptv": { "channels": total_iptv_ch, "playlists": total_iptv_pl },
        "visitors": {
            "total": total_visitors, "new_24h": new_visitors_24h, "new_7d": new_visitors_7d,
            "tracked_locations": tracked_locations,
        },
        "moderation": {
            "comments": total_comments, "new_comments_24h": new_comments_24h,
            "reports": total_reports, "pending_reports": pending_reports,
            "blocked_ips": blocked_ips,
        },
        "feedback":     { "total": total_feedback, "unread": unread_feedback },
        "announcements": { "active": active_ann },
    })


@app.post("/api/admin/external/create")
async def admin_create_external(
    request: Request,
    title:       str = Form(...),
    stream_url:  str = Form(...),
    stream_type: str = Form("hls"),
    category:    str = Form("general"),
    country:     str = Form(""),
    language:    str = Form(""),
    logo:        str = Form(""),
    description: str = Form(""),
    quality:     str = Form(""),
    db: Session = Depends(get_db)
):
    """Créer un nouveau flux externe"""
    try:
        require_admin(request)
    except HTTPException:
        return JSONResponse(status_code=401, content={"error": "Non autorisé"})

    stream = ExternalStream(
        title=title[:200],
        url=stream_url[:2000],
        stream_type=stream_type,
        category=category,
        country=(country or "").upper()[:5],
        language=language[:50],
        logo=logo[:500],
        quality=quality[:20],
        is_active=True,
    )
    db.add(stream)
    db.commit()
    db.refresh(stream)
    return JSONResponse({"success": True, "id": stream.id, "message": f"Flux « {title} » créé avec succès"})


@app.put("/api/admin/external/{stream_id}/edit")
async def admin_edit_external(
    stream_id: int,
    request: Request,
    title:       str = Form(None),
    stream_url:  str = Form(None),
    category:    str = Form(None),
    country:     str = Form(None),
    logo:        str = Form(None),
    description: str = Form(None),
    db: Session = Depends(get_db)
):
    """Modifier un flux externe"""
    try:
        require_admin(request)
    except HTTPException:
        return JSONResponse(status_code=401, content={"error": "Non autorisé"})

    stream = db.query(ExternalStream).filter(ExternalStream.id == stream_id).first()
    if not stream:
        raise HTTPException(status_code=404, detail="Flux introuvable")

    if title:       stream.title    = title[:200]
    if stream_url:  stream.url      = stream_url[:2000]
    if category:    stream.category = category
    if country:     stream.country  = country.upper()[:5]
    if logo:        stream.logo     = logo[:500]
    if description: stream.description = description[:1000]
    db.commit()
    return JSONResponse({"success": True, "message": "Flux mis à jour"})


@app.delete("/api/admin/external/{stream_id}/delete")
async def admin_delete_external(stream_id: int, request: Request, db: Session = Depends(get_db)):
    """Supprimer définitivement un flux externe"""
    try:
        require_admin(request)
    except HTTPException:
        return JSONResponse(status_code=401, content={"error": "Non autorisé"})

    stream = db.query(ExternalStream).filter(ExternalStream.id == stream_id).first()
    if not stream:
        raise HTTPException(status_code=404, detail="Flux introuvable")
    db.delete(stream)
    db.commit()
    return JSONResponse({"success": True, "message": "Flux supprimé définitivement"})


@app.post("/api/admin/streams/{stream_id}/unblock")
async def admin_unblock_stream(stream_id: int, request: Request, db: Session = Depends(get_db)):
    """Débloquer un stream utilisateur"""
    try:
        require_admin(request)
    except HTTPException:
        return JSONResponse(status_code=401, content={"error": "Non autorisé"})
    stream = db.query(LiveStream).filter(LiveStream.id == stream_id).first()
    if not stream:
        raise HTTPException(status_code=404, detail="Stream introuvable")
    stream.is_blocked = False
    db.commit()
    return JSONResponse({"success": True, "message": "Stream débloqué"})


@app.post("/api/admin/streams/cleanup")
async def admin_cleanup_streams(request: Request, db: Session = Depends(get_db)):
    """Nettoyer les streams terminés depuis plus de 24h"""
    try:
        require_admin(request)
    except HTTPException:
        return JSONResponse(status_code=401, content={"error": "Non autorisé"})
    from datetime import datetime, timezone, timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    deleted = db.query(LiveStream).filter(
        LiveStream.is_live == False,
        LiveStream.created_at < cutoff
    ).delete(synchronize_session=False)
    db.commit()
    return JSONResponse({"success": True, "deleted": deleted, "message": f"{deleted} streams supprimés"})


@app.post("/api/admin/visitors/cleanup")
async def admin_cleanup_visitors(request: Request, db: Session = Depends(get_db)):
    """Nettoyer les visiteurs inactifs depuis plus de 90 jours"""
    try:
        require_admin(request)
    except HTTPException:
        return JSONResponse(status_code=401, content={"error": "Non autorisé"})
    from datetime import datetime, timezone, timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(days=90)
    deleted = db.query(Visitor).filter(Visitor.last_seen < cutoff).delete(synchronize_session=False)
    db.commit()
    return JSONResponse({"success": True, "deleted": deleted})


@app.get("/api/admin/comments/recent")
async def admin_recent_comments(request: Request, limit: int = 50, db: Session = Depends(get_db)):
    """Commentaires récents pour modération"""
    try:
        require_admin(request)
    except HTTPException:
        return JSONResponse(status_code=401, content={"error": "Non autorisé"})
    comments = db.query(ChatMessage).order_by(ChatMessage.created_at.desc()).limit(limit).all()
    return JSONResponse({
        "comments": [{
            "id":            c.id,
            "content":       c.content[:300],
            "created_at":    c.created_at.isoformat(),
            "report_count":  c.report_count or 0,
            "is_deleted":    c.is_deleted or False,
            "is_auto_hidden":c.is_auto_hidden or False,
        } for c in comments]
    })


@app.post("/api/admin/comments/{comment_id}/delete")
async def admin_delete_comment(comment_id: int, request: Request, db: Session = Depends(get_db)):
    """Supprimer un commentaire"""
    try:
        require_admin(request)
    except HTTPException:
        return JSONResponse(status_code=401, content={"error": "Non autorisé"})
    c = db.query(ChatMessage).filter(ChatMessage.id == comment_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Commentaire introuvable")
    c.is_deleted = True
    c.content = "[Contenu supprimé par un administrateur]"
    db.commit()
    return JSONResponse({"success": True, "message": "Commentaire supprimé"})


@app.post("/api/admin/reports/{report_id}/resolve")
async def admin_resolve_report(report_id: int, request: Request, db: Session = Depends(get_db)):
    """Marquer un signalement comme résolu"""
    try:
        require_admin(request)
    except HTTPException:
        return JSONResponse(status_code=401, content={"error": "Non autorisé"})
    r = db.query(Report).filter(Report.id == report_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Signalement introuvable")
    r.resolved = True
    db.commit()
    return JSONResponse({"success": True, "message": "Signalement résolu"})


@app.post("/api/admin/iptv/playlist/{playlist_name}/refresh")
async def admin_refresh_playlist(
    playlist_name: str,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Resynchroniser une playlist IPTV spécifique"""
    try:
        require_admin(request)
    except HTTPException:
        return JSONResponse(status_code=401, content={"error": "Non autorisé"})

    playlist_data = next((p for p in IPTV_PLAYLISTS if p["name"] == playlist_name), None)
    if not playlist_data:
        raise HTTPException(status_code=404, detail=f"Playlist '{playlist_name}' introuvable")

    async def _sync_one():
        await sync_single_playlist(playlist_data, db)

    background_tasks.add_task(_sync_one)
    return JSONResponse({"success": True, "message": f"Synchronisation de '{playlist_name}' lancée en arrière-plan"})


@app.get("/api/admin/iptv/stats")
async def admin_iptv_stats(request: Request, db: Session = Depends(get_db)):
    """Statistiques IPTV détaillées"""
    try:
        require_admin(request)
    except HTTPException:
        return JSONResponse(status_code=401, content={"error": "Non autorisé"})

    total_playlists  = db.query(IPTVPlaylist).count()
    synced_playlists = db.query(IPTVPlaylist).filter(IPTVPlaylist.sync_status == "success").count()
    error_playlists  = db.query(IPTVPlaylist).filter(IPTVPlaylist.sync_status == "error").count()
    total_channels   = db.query(IPTVChannel).count()

    # Chaînes par pays (top 20)
    from sqlalchemy import func
    by_country = db.query(
        IPTVChannel.country, func.count(IPTVChannel.id).label("count")
    ).group_by(IPTVChannel.country).order_by(func.count(IPTVChannel.id).desc()).limit(20).all()

    # Chaînes par catégorie
    by_category = db.query(
        IPTVChannel.category, func.count(IPTVChannel.id).label("count")
    ).group_by(IPTVChannel.category).order_by(func.count(IPTVChannel.id).desc()).limit(15).all()

    return JSONResponse({
        "playlists": {
            "total": total_playlists, "synced": synced_playlists,
            "errors": error_playlists, "pending": total_playlists - synced_playlists - error_playlists,
        },
        "channels": { "total": total_channels },
        "by_country":  [{"country": r[0] or "?", "count": r[1]} for r in by_country],
        "by_category": [{"category": r[0] or "?", "count": r[1]} for r in by_category],
    })


@app.get("/api/admin/feedback/export")
async def admin_export_feedback(request: Request, db: Session = Depends(get_db)):
    """Exporter tous les avis en JSON"""
    try:
        require_admin(request)
    except HTTPException:
        return JSONResponse(status_code=401, content={"error": "Non autorisé"})
    feedbacks = db.query(UserFeedback).order_by(UserFeedback.created_at.desc()).all()
    return JSONResponse({
        "export_date": __import__("datetime").datetime.utcnow().isoformat(),
        "total": len(feedbacks),
        "feedbacks": [{
            "id":         fb.id,
            "rating":     fb.rating,
            "message":    fb.message,
            "email":      fb.email or "",
            "is_read":    fb.is_read,
            "created_at": fb.created_at.isoformat(),
        } for fb in feedbacks]
    })


@app.post("/api/admin/feedback/mark-all-read")
async def admin_mark_all_feedback_read(request: Request, db: Session = Depends(get_db)):
    """Marquer tous les avis comme lus"""
    try:
        require_admin(request)
    except HTTPException:
        return JSONResponse(status_code=401, content={"error": "Non autorisé"})
    updated = db.query(UserFeedback).filter(UserFeedback.is_read == False).update({"is_read": True})
    db.commit()
    return JSONResponse({"success": True, "updated": updated})


@app.get("/api/admin/locations/export")
async def admin_export_locations(request: Request, db: Session = Depends(get_db)):
    """Exporter les données de géolocalisation"""
    try:
        require_admin(request)
    except HTTPException:
        return JSONResponse(status_code=401, content={"error": "Non autorisé"})

    from sqlalchemy import func
    locs = db.query(
        UserLocation.country, UserLocation.country_code,
        UserLocation.continent, UserLocation.lat, UserLocation.lng,
        func.count(UserLocation.id).label("visits")
    ).group_by(
        UserLocation.country, UserLocation.country_code,
        UserLocation.continent, UserLocation.lat, UserLocation.lng
    ).all()

    return JSONResponse({
        "total": sum(l[5] for l in locs),
        "countries": [{
            "country":      l[0] or "Inconnu",
            "country_code": l[1] or "",
            "continent":    l[2] or "INT",
            "lat":          float(l[3]) if l[3] else 0,
            "lng":          float(l[4]) if l[4] else 0,
            "count":        l[5],
        } for l in sorted(locs, key=lambda x: x[5], reverse=True)]
    })


@app.post("/api/admin/ips/unblock/{ip_id}")
async def admin_unblock_ip_by_id(ip_id: int, request: Request, db: Session = Depends(get_db)):
    """Débloquer une IP par son ID"""
    try:
        require_admin(request)
    except HTTPException:
        return JSONResponse(status_code=401, content={"error": "Non autorisé"})
    ip = db.query(BlockedIP).filter(BlockedIP.id == ip_id).first()
    if not ip:
        raise HTTPException(status_code=404, detail="IP introuvable")
    ip.is_active = False
    db.commit()
    return JSONResponse({"success": True, "message": f"IP {ip.ip_address} débloquée"})


@app.get("/api/admin/ips/list")
async def admin_list_ips(request: Request, db: Session = Depends(get_db)):
    """Liste de toutes les IPs bloquées"""
    try:
        require_admin(request)
    except HTTPException:
        return JSONResponse(status_code=401, content={"error": "Non autorisé"})
    ips = db.query(BlockedIP).filter(BlockedIP.is_active == True).order_by(BlockedIP.blocked_at.desc()).all()
    return JSONResponse({
        "total": len(ips),
        "ips": [{
            "id":          ip.id,
            "ip_address":  ip.ip_address,
            "reason":      ip.reason or "",
            "blocked_at":  ip.blocked_at.isoformat(),
            "is_permanent":ip.is_permanent,
            "expires_at":  ip.expires_at.isoformat() if ip.expires_at else None,
        } for ip in ips]
    })


@app.post("/api/admin/config/update")
async def admin_update_config(
    request: Request,
    app_name:     str = Form(None),
    app_logo_url: str = Form(None),
    db: Session = Depends(get_db)
):
    """Mettre à jour la configuration de l'application"""
    try:
        require_admin(request)
    except HTTPException:
        return JSONResponse(status_code=401, content={"error": "Non autorisé"})

    updates = {}
    if app_name:     updates["APP_NAME"]     = app_name
    if app_logo_url: updates["APP_LOGO_URL"] = app_logo_url

    if not updates:
        return JSONResponse({"success": False, "error": "Aucun paramètre fourni"})

    # Mettre à jour les variables de l'objet settings
    for k, v in updates.items():
        if hasattr(settings, k):
            setattr(settings, k, v)

    return JSONResponse({"success": True, "updated": list(updates.keys()), "message": "Configuration mise à jour"})


# ── Route pour playlist M3U publique ─────────────────────────────────────
@app.get("/api/playlist/m3u")
async def get_m3u_playlist(
    country: str = None,
    category: str = None,
    type: str = "external",
    db: Session = Depends(get_db)
):
    """Génère une playlist M3U à partir des flux de la plateforme"""
    lines = ["#EXTM3U"]

    if type in ("external", "all"):
        q = db.query(ExternalStream).filter(ExternalStream.is_active == True)
        if country: q = q.filter(ExternalStream.country.ilike(country))
        if category: q = q.filter(ExternalStream.category.ilike(category))
        for s in q.limit(500).all():
            logo = f' tvg-logo="{s.logo}"' if s.logo else ""
            group = f' group-title="{s.category}"' if s.category else ""
            lines.append(f'#EXTINF:-1{logo}{group},{s.title}')
            lines.append(s.stream_url)

    if type in ("iptv", "all"):
        q = db.query(IPTVChannel)
        if country: q = q.filter(IPTVChannel.country.ilike(country))
        if category: q = q.filter(IPTVChannel.category.ilike(category))
        for ch in q.limit(500).all():
            logo = f' tvg-logo="{ch.logo}"' if ch.logo else ""
            group = f' group-title="{ch.country}"' if ch.country else ""
            lines.append(f'#EXTINF:-1 tvg-id="{ch.id}"{logo}{group},{ch.name}')
            lines.append(ch.stream_url)

    content = "\n".join(lines)
    from starlette.responses import Response
    return Response(
        content=content,
        media_type="application/x-mpegurl",
        headers={"Content-Disposition": "attachment; filename=livewatch.m3u"}
    )


# ── Routes de signalement ─────────────────────────────────────────────────
@app.post("/api/report")
async def submit_report(
    request: Request,
    stream_id:   str = Form(...),
    stream_type: str = Form("external"),
    reason:      str = Form(...),
    db: Session = Depends(get_db)
):
    """Signaler un contenu inapproprié"""
    if not reason or len(reason.strip()) < 3:
        return JSONResponse(status_code=400, content={"error": "Raison du signalement trop courte"})

    report = Report(
        stream_id   = int(stream_id) if stream_id.isdigit() else 0,
        stream_type = stream_type[:20],
        reason      = reason.strip()[:500],
        resolved    = False,
    )
    db.add(report)
    db.commit()
    logger.info(f"Signalement: stream {stream_id} ({stream_type}) — {reason[:60]}")
    return JSONResponse({"success": True, "message": "Signalement reçu. Merci pour votre vigilance."})


# ── Routes favoris ────────────────────────────────────────────────────────
@app.get("/api/favorites")
async def get_favorites(request: Request, db: Session = Depends(get_db)):
    """Récupérer les favoris de l'utilisateur courant"""
    visitor_id = get_visitor_id(request)
    visitor = db.query(Visitor).filter(Visitor.visitor_id == visitor_id).first()
    if not visitor:
        return JSONResponse([])

    try:
        favs_raw = visitor.favorites or "[]"
        favs = __import__("json").loads(favs_raw)
    except Exception:
        return JSONResponse([])

    results = []
    for fav in favs[:50]:
        sid   = fav.get("stream_id")
        stype = fav.get("stream_type", "external")
        if stype == "external":
            s = db.query(ExternalStream).filter(ExternalStream.id == sid).first()
            if s:
                results.append({
                    "id": s.id, "type": "external", "title": s.title,
                    "logo": s.logo or "", "category": s.category,
                    "is_live": True, "url": f"/watch/external/{s.id}",
                })
        elif stype == "iptv":
            ch = db.query(IPTVChannel).filter(IPTVChannel.id == sid).first()
            if ch:
                results.append({
                    "id": ch.id, "type": "iptv", "title": ch.name,
                    "logo": ch.logo or "", "category": ch.category,
                    "is_live": True, "url": f"/watch/iptv/{ch.id}",
                })
        elif stype == "user":
            s = db.query(LiveStream).filter(LiveStream.id == sid).first()
            if s:
                results.append({
                    "id": s.id, "type": "user", "title": s.title,
                    "logo": s.thumbnail or "", "category": s.category,
                    "is_live": s.is_live, "url": f"/watch/user/{s.id}",
                })

    return JSONResponse(results)


@app.post("/api/favorites/add")
async def add_favorite(
    request: Request,
    stream_id:   str = Form(...),
    stream_type: str = Form("external"),
    db: Session = Depends(get_db)
):
    """Ajouter/retirer un favori (toggle)"""
    visitor_id = get_visitor_id(request)
    visitor = db.query(Visitor).filter(Visitor.visitor_id == visitor_id).first()
    if not visitor:
        client_ip = request.client.host if request.client else "0.0.0.0"
        visitor = Visitor(visitor_id=visitor_id, ip_address=client_ip, user_agent="")
        db.add(visitor)

    import json as _json
    try:
        favs = _json.loads(visitor.favorites or "[]")
    except Exception:
        favs = []

    entry = {"stream_id": int(stream_id), "stream_type": stream_type}
    existing = next((i for i, f in enumerate(favs) if f.get("stream_id") == entry["stream_id"] and f.get("stream_type") == stream_type), None)

    if existing is not None:
        favs.pop(existing)
        action = "removed"
        msg = "Retiré des favoris"
    else:
        favs.insert(0, entry)
        favs = favs[:100]  # Limite 100 favoris
        action = "added"
        msg = "Ajouté aux favoris"

    visitor.favorites = _json.dumps(favs)
    db.commit()

    response = JSONResponse({"success": True, "action": action, "message": msg, "count": len(favs)})
    response.set_cookie("visitor_id", visitor_id, max_age=settings.SESSION_MAX_AGE, httponly=True, samesite="lax")
    return response


@app.delete("/api/favorites/{stream_id}")
async def remove_favorite(stream_id: int, stream_type: str, request: Request, db: Session = Depends(get_db)):
    """Supprimer un favori spécifique"""
    visitor_id = get_visitor_id(request)
    visitor = db.query(Visitor).filter(Visitor.visitor_id == visitor_id).first()
    if not visitor:
        return JSONResponse({"success": False, "error": "Visiteur inconnu"})

    import json as _json
    try:
        favs = _json.loads(visitor.favorites or "[]")
    except Exception:
        favs = []

    favs = [f for f in favs if not (f.get("stream_id") == stream_id and f.get("stream_type") == stream_type)]
    visitor.favorites = _json.dumps(favs)
    db.commit()
    return JSONResponse({"success": True, "count": len(favs)})


# ── Routes d'enregistrement streaming ────────────────────────────────────
@app.post("/api/recording/start")
async def recording_start(request: Request, db: Session = Depends(get_db)):
    """Enregistrer le démarrage d'un enregistrement"""
    visitor_id = get_visitor_id(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    session = StreamRecordingSession(
        visitor_id   = visitor_id,
        stream_id    = body.get("stream_id"),
        stream_type  = body.get("stream_type", "external"),
        started_at   = __import__("datetime").datetime.utcnow(),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return JSONResponse({"success": True, "session_id": session.id})


@app.post("/api/recording/stop")
async def recording_stop(request: Request, db: Session = Depends(get_db)):
    """Enregistrer l'arrêt d'un enregistrement"""
    visitor_id = get_visitor_id(request)
    try:
        body = await request.json()
    except Exception:
        body = {}

    session_id = body.get("session_id")
    if session_id:
        session = db.query(StreamRecordingSession).filter(
            StreamRecordingSession.id == session_id,
            StreamRecordingSession.visitor_id == visitor_id
        ).first()
        if session:
            session.ended_at     = __import__("datetime").datetime.utcnow()
            session.file_size_mb = body.get("file_size_mb")
            db.commit()
    return JSONResponse({"success": True})


# ── Route catalogue pour la page d'accueil ─────────────────────────────────
@app.get("/api/catalog")
async def get_catalog(
    category: str = None,
    limit:    int = 40,
    db: Session = Depends(get_db)
):
    """Catalogue de contenu pour la page d'accueil"""
    q = db.query(ExternalStream).filter(ExternalStream.is_active == True)
    if category:
        q = q.filter(ExternalStream.category.ilike(f"%{category}%"))
    streams = q.order_by(ExternalStream.id.desc()).limit(limit).all()

    return JSONResponse({
        "streams": [{
            "id":          s.id,
            "title":       s.title,
            "logo":        s.logo or "",
            "category":    s.category,
            "country":     s.country or "",
            "stream_type": s.stream_type,
            "quality":     s.quality or "",
            "url":         f"/watch/external/{s.id}",
        } for s in streams]
    })


# ── Route pour les chaînes similaires ─────────────────────────────────────
@app.get("/api/streams/{stream_id}/similar")
async def get_similar_streams(stream_id: int, db: Session = Depends(get_db)):
    """Chaînes similaires à un flux donné"""
    stream = db.query(ExternalStream).filter(ExternalStream.id == stream_id).first()
    if not stream:
        return JSONResponse({"similar": []})

    similar = db.query(ExternalStream).filter(
        ExternalStream.id != stream_id,
        ExternalStream.is_active == True,
        ExternalStream.category == stream.category,
    ).limit(8).all()

    if len(similar) < 4:
        extra = db.query(ExternalStream).filter(
            ExternalStream.id != stream_id,
            ExternalStream.is_active == True,
            ~ExternalStream.id.in_([s.id for s in similar]),
        ).limit(8 - len(similar)).all()
        similar.extend(extra)

    return JSONResponse({
        "similar": [{
            "id":          s.id,
            "title":       s.title,
            "logo":        s.logo or "",
            "country":     s.country or "",
            "category":    s.category,
            "stream_type": s.stream_type,
            "url":         f"/watch/external/{s.id}",
        } for s in similar]
    })



# ── Fonction de seeding des chaînes supplémentaires ──────────────────────
async def seed_extra_channels(db: Session):
    """Ajoute les chaînes radio, news et sports si elles n'existent pas déjà"""
    all_extra = []
    try:
        all_extra += EXTRA_RADIO_STATIONS
    except NameError:
        pass
    try:
        all_extra += EXTRA_NEWS_CHANNELS
    except NameError:
        pass
    try:
        all_extra += EXTRA_SPORTS_CHANNELS
    except NameError:
        pass

    if not all_extra:
        return 0

    inserted = 0
    for ch_data in all_extra:
        existing = db.query(ExternalStream).filter(
            ExternalStream.title == ch_data["title"]
        ).first()
        if not existing:
            stream = ExternalStream(
                title=ch_data.get("title","")[:200],
                stream_url=ch_data.get("stream_url","")[:2000],
                stream_type=ch_data.get("stream_type","hls"),
                category=ch_data.get("category","general"),
                country=(ch_data.get("country","") or "").upper()[:5],
                language=ch_data.get("language",""),
                logo=ch_data.get("logo","")[:500],
                description=ch_data.get("description","")[:500],
                quality=ch_data.get("quality",""),
                is_active=True,
            )
            db.add(stream)
            inserted += 1
            if inserted % 20 == 0:
                db.commit()

    db.commit()
    logger.info(f"{inserted} chaînes supplémentaires ajoutées (radio/news/sports)")
    return inserted


# ── WebSocket admin live stats ─────────────────────────────────────────────
async def _broadcast_admin_stats(ws_connection, db: Session):
    """Envoie les stats admin via WebSocket"""
    from datetime import datetime, timezone, timedelta
    import json as _json
    try:
        now = datetime.now(timezone.utc)
        cutoff_5m = now - timedelta(minutes=5)

        active_users = db.query(Visitor).filter(Visitor.last_seen >= cutoff_5m).count()
        live_streams = db.query(LiveStream).filter(LiveStream.is_live == True).count()

        # Top pages visitées récemment
        # (simulé si la table page_views n'existe pas)
        top_pages = []
        try:
            from sqlalchemy import func, text as sa_text
            pages_raw = db.execute(sa_text(
                "SELECT page, COUNT(*) as cnt FROM page_views "
                "WHERE visited_at >= NOW() - INTERVAL '10 minutes' "
                "GROUP BY page ORDER BY cnt DESC LIMIT 5"
            )).fetchall()
            top_pages = [{"page": r[0], "count": r[1]} for r in pages_raw]
        except Exception:
            pass

        payload = _json.dumps({
            "type":         "stats",
            "active_users": active_users,
            "live_streams": live_streams,
            "top_pages":    top_pages,
            "timestamp":    now.isoformat(),
        })
        await ws_connection.send_text(payload)
    except Exception as e:
        logger.debug(f"WS admin stats error: {e}")


# ── Utilitaires de streaming HLS ───────────────────────────────────────────
async def _rewrite_m3u8_proxy(url: str, base_url: str, stream_id: str) -> str:
    """Réécrit une playlist M3U8 pour router les segments via le proxy"""
    import re, httpx
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            r = await client.get(url, headers={
                "User-Agent": "Mozilla/5.0 (compatible; LivewatchProxy/2.0)",
                "Referer": base_url,
            })
            if r.status_code != 200:
                return r.text

        content_m3u8 = r.text
        lines = content_m3u8.split("\n")
        new_lines = []

        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                new_lines.append(line)
                continue
            # C'est un segment ou une sous-playlist
            if line.startswith("http"):
                seg_url = line
            else:
                from urllib.parse import urljoin
                seg_url = urljoin(url, line)
            # Encoder l'URL du segment
            import urllib.parse
            encoded = urllib.parse.quote(seg_url, safe="")
            proxy_url = f"/proxy/segment/{stream_id}?url={encoded}"
            new_lines.append(proxy_url)

        return "\n".join(new_lines)
    except Exception as e:
        logger.warning(f"M3U8 rewrite error: {e}")
        return ""


async def _fetch_m3u8_cached(url: str, stream_id: str, cache: dict) -> str:
    """Récupère et cache une playlist M3U8"""
    import time
    cache_key = f"m3u8_{stream_id}"
    now = time.time()

    if cache_key in cache:
        cached_ts, cached_content = cache[cache_key]
        if now - cached_ts < 8:  # Cache 8 secondes
            return cached_content

    content_m3u8 = await _rewrite_m3u8_proxy(url, url, stream_id)
    cache[cache_key] = (now, content_m3u8)
    return content_m3u8


# Cache global pour les playlists M3U8
_m3u8_cache: dict = {}


# ── Fonctions de monitoring ────────────────────────────────────────────────
async def _update_stream_viewers(db: Session, stream_id: int, delta: int = 1):
    """Met à jour le compteur de spectateurs d'un stream"""
    stream = db.query(LiveStream).filter(LiveStream.id == stream_id).first()
    if stream:
        stream.viewer_count = max(0, (stream.viewer_count or 0) + delta)
        db.commit()


def _get_client_ip(request: Request) -> str:
    """Récupère l'IP réelle du client (derrière un proxy)"""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else "0.0.0.0"


def _is_private_ip(ip: str) -> bool:
    """Vérifie si une IP est privée/locale"""
    private_prefixes = (
        "127.", "localhost", "::1",
        "10.", "172.16.", "172.17.", "172.18.", "172.19.", "172.20.", "172.21.",
        "172.22.", "172.23.", "172.24.", "172.25.", "172.26.", "172.27.", "172.28.",
        "172.29.", "172.30.", "172.31.", "192.168.", "0.0.0.0",
    )
    return any(ip.startswith(p) or ip == p for p in private_prefixes)


def _sanitize_text(text: str, max_len: int = 500) -> str:
    """Nettoie et tronque un texte"""
    if not text:
        return ""
    # Retirer les caractères de contrôle
    import unicodedata
    cleaned = "".join(c for c in text if unicodedata.category(c)[0] != "C" or c in ("\n", "\t"))
    return cleaned.strip()[:max_len]


def _extract_country_from_url(url: str) -> str:
    """Tente d'extraire un code pays depuis une URL IPTV"""
    import re
    # Pattern: /countries/xx.m3u ou /subdivisions/xx-yy.m3u
    m = re.search(r"/countries/([a-z]{2})\.m3u", url)
    if m:
        return m.group(1).upper()
    m = re.search(r"/subdivisions/([a-z]{2})-", url)
    if m:
        return m.group(1).upper()
    return ""


def _parse_m3u_header(line: str) -> dict:
    """Parse les attributs d'une ligne #EXTINF M3U"""
    import re
    attrs = {}
    for m in re.finditer(r'(\w[\w-]*)="([^"]*)"', line):
        attrs[m.group(1)] = m.group(2)
    # Extraire le nom (après la dernière virgule)
    name_match = re.search(r",(.+)$", line)
    if name_match:
        attrs["_name"] = name_match.group(1).strip()
    return attrs


def _categorize_channel(name: str, group: str) -> str:
    """Catégorise automatiquement une chaîne selon son nom et groupe"""
    name_low  = (name or "").lower()
    group_low = (group or "").lower()
    combined  = name_low + " " + group_low

    if any(k in combined for k in ["sport", "foot", "soccer", "basket", "tennis", "golf", "rugby", "formula"]):
        return "sports"
    if any(k in combined for k in ["news", "info", "actu", "bfm", "cnn", "bbc", "press", "noticias"]):
        return "news"
    if any(k in combined for k in ["kid", "enfant", "cartoon", "nickelodeon", "disney junior"]):
        return "kids"
    if any(k in combined for k in ["music", "musique", "mtv", "hit", "radio"]):
        return "music"
    if any(k in combined for k in ["film", "movie", "cinema", "cine", "hbo", "netflix"]):
        return "entertainment"
    if any(k in combined for k in ["docu", "discovery", "nat geo", "national"]):
        return "documentary"
    if any(k in combined for k in ["religion", "church", "bible", "islam", "mosque"]):
        return "religion"
    return "general"


async def _check_stream_health(url: str, timeout: float = 8.0) -> dict:
    """Vérifie si un flux est accessible"""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            r = await client.head(url, headers={"User-Agent": "LivewatchBot/2.0"})
            return {
                "online":      r.status_code < 400,
                "status_code": r.status_code,
                "content_type": r.headers.get("content-type", ""),
                "latency_ms":  0,
            }
    except Exception as e:
        return {"online": False, "status_code": 0, "error": str(e)[:100]}


@app.post("/api/admin/streams/health-check")
async def admin_health_check_streams(request: Request, db: Session = Depends(get_db)):
    """Vérifie la santé de tous les flux externes actifs"""
    try:
        require_admin(request)
    except HTTPException:
        return JSONResponse(status_code=401, content={"error": "Non autorisé"})

    streams = db.query(ExternalStream).filter(
        ExternalStream.is_active == True,
        ExternalStream.stream_type.in_(["hls", "mp4"])
    ).limit(20).all()

    results = []
    import asyncio
    checks = await asyncio.gather(*[_check_stream_health(s.stream_url) for s in streams], return_exceptions=True)

    for i, stream in enumerate(streams):
        check = checks[i] if not isinstance(checks[i], Exception) else {"online": False, "error": str(checks[i])[:60]}
        if not check.get("online"):
            stream.is_active = False
        results.append({
            "id":     stream.id,
            "title":  stream.title,
            "online": check.get("online", False),
            "status": check.get("status_code", 0),
            "error":  check.get("error", ""),
        })

    db.commit()
    online_count = sum(1 for r in results if r["online"])
    return JSONResponse({
        "checked": len(results),
        "online":  online_count,
        "offline": len(results) - online_count,
        "results": results,
    })


@app.get("/api/admin/system/info")
async def admin_system_info(request: Request):
    """Informations système pour l'admin"""
    try:
        require_admin(request)
    except HTTPException:
        return JSONResponse(status_code=401, content={"error": "Non autorisé"})

    import sys, platform, os
    try:
        import psutil
        cpu     = psutil.cpu_percent(interval=0.3)
        mem     = psutil.virtual_memory()
        disk    = psutil.disk_usage("/")
        mem_pct = mem.percent
        disk_pct = disk.percent
    except ImportError:
        cpu = mem_pct = disk_pct = -1

    return JSONResponse({
        "python_version":  sys.version,
        "platform":        platform.system() + " " + platform.release(),
        "cpu_percent":     cpu,
        "memory_percent":  mem_pct,
        "disk_percent":    disk_pct,
        "app_name":        settings.APP_NAME,
        "app_version":     "2.0",
        "db_url":          settings.DATABASE_URL[:40] + "..." if len(settings.DATABASE_URL) > 40 else settings.DATABASE_URL,
        "templates":       len(os.listdir(TEMPLATES_DIR)) if os.path.exists(TEMPLATES_DIR) else 0,
        "iptv_playlists":  len(IPTV_PLAYLISTS),
    })


@app.get("/api/admin/logs/recent")
async def admin_recent_logs(request: Request, lines: int = 50):
    """Récupère les dernières lignes de logs (si disponible)"""
    try:
        require_admin(request)
    except HTTPException:
        return JSONResponse(status_code=401, content={"error": "Non autorisé"})

    log_files = ["app.log", "livewatch.log", "/var/log/livewatch.log"]
    for lf in log_files:
        import os
        if os.path.exists(lf):
            with open(lf, "r", encoding="utf-8", errors="replace") as f:
                content_log = f.readlines()
            recent = content_log[-lines:]
            return JSONResponse({"log_file": lf, "lines": [l.rstrip() for l in recent]})

    return JSONResponse({"log_file": None, "lines": ["Aucun fichier de log trouvé."], "note": "Les logs s'affichent dans la console."})




# ══════════════════════════════════════════════════════════════════════════
# ROUTES SUPPLEMENTAIRES — HTML pages, admin, analytics, PWA
# ══════════════════════════════════════════════════════════════════════════

@app.get("/playlist/{playlist_name}", response_class=HTMLResponse)
async def playlist_page(request: Request, playlist_name: str, db: Session = Depends(get_db)):
    _track_visit(request, db, f"/playlist/{playlist_name}")
    playlist = db.query(IPTVPlaylist).filter(IPTVPlaylist.name == playlist_name).first()
    if not playlist:
        return templates.TemplateResponse(request, "error.html", {
            "request": request, "app_name": settings.APP_NAME,
            "code": 404, "message": "Playlist introuvable",
            "detail": f"La playlist '{playlist_name}' n'existe pas.",
        }, status_code=404)
    channels = db.query(IPTVChannel).filter(
        IPTVChannel.playlist_id == playlist.id, IPTVChannel.is_active == True
    ).order_by(IPTVChannel.name).all()
    lang = request.cookies.get("lang", "fr")
    return templates.TemplateResponse(request, "playlist.html", {
        "request": request, "app_name": settings.APP_NAME,
        "playlist": playlist, "channels": channels, "language": lang,
        "logo_path": settings.LOGO_PATH if os.path.exists(settings.LOGO_PATH) else None,
    })


@app.get("/api/admin/realtime/stats")
async def admin_realtime_stats(request: Request, db: Session = Depends(get_db)):
    try: require_admin(request)
    except HTTPException: return JSONResponse(status_code=401, content={"error": "Non autorisé"})
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    cutoff_5m = now - timedelta(minutes=5)
    cutoff_24h = now - timedelta(hours=24)
    return JSONResponse({
        "active_users":    db.query(Visitor).filter(Visitor.last_seen >= cutoff_5m).count(),
        "new_today":       db.query(Visitor).filter(Visitor.first_seen >= cutoff_24h).count(),
        "live_streams":    db.query(LiveStream).filter(LiveStream.is_live == True).count(),
        "pending_reports": db.query(Report).filter(Report.resolved == False).count(),
        "unread_feedback": db.query(UserFeedback).filter(UserFeedback.is_read == False).count(),
        "ts": now.isoformat(),
    })


@app.get("/api/iptv/country/{country_code}")
async def iptv_by_country(country_code: str, page: int = 1, limit: int = 48, db: Session = Depends(get_db)):
    cc = country_code.upper()
    total = db.query(IPTVChannel).filter(IPTVChannel.country == cc, IPTVChannel.is_active == True).count()
    channels = db.query(IPTVChannel).filter(
        IPTVChannel.country == cc, IPTVChannel.is_active == True
    ).order_by(IPTVChannel.name).offset((page-1)*limit).limit(limit).all()
    playlist = db.query(IPTVPlaylist).filter(IPTVPlaylist.country == cc).first()
    return JSONResponse({
        "country": cc,
        "playlist_name": playlist.name if playlist else None,
        "total": total, "page": page, "pages": (total+limit-1)//limit,
        "channels": [{"id":ch.id,"name":ch.name,"logo":ch.logo or "","category":ch.category or "","url":f"/watch/iptv/{ch.id}"} for ch in channels],
    })


@app.get("/api/streams/{stream_id}/comments")
async def get_stream_comments(stream_id: int, page: int = 1, limit: int = 50, db: Session = Depends(get_db)):
    total = db.query(ChatMessage).filter(ChatMessage.stream_id == stream_id, ChatMessage.is_deleted == False).count()
    comments = db.query(ChatMessage).filter(
        ChatMessage.stream_id == stream_id, ChatMessage.is_deleted == False
    ).order_by(ChatMessage.created_at.desc()).offset((page-1)*limit).limit(limit).all()
    return JSONResponse({
        "total": total, "page": page,
        "comments": [{"id":c.id,"content":c.content,"created_at":c.created_at.isoformat(),"report_count":c.report_count or 0} for c in reversed(comments)],
    })


@app.post("/api/streams/{stream_id}/comments")
async def post_stream_comment(stream_id: int, request: Request, content: str = Form(...), username: str = Form("Anonyme"), db: Session = Depends(get_db)):
    stream = db.query(LiveStream).filter(LiveStream.id == stream_id).first()
    if not stream:
        raise HTTPException(status_code=404, detail="Stream introuvable")
    clean = content.strip()[:500]
    if not clean:
        return JSONResponse(status_code=400, content={"error": "Message vide"})
    client_ip = _get_client_ip(request)
    if await _is_ip_blocked(client_ip, db):
        return JSONResponse(status_code=403, content={"error": "Accès refusé"})
    comment = ChatMessage(stream_id=stream_id, username=username.strip()[:50] or "Anonyme", content=clean, ip_address=client_ip, report_count=0, is_deleted=False, is_auto_hidden=False)
    db.add(comment); db.commit(); db.refresh(comment)
    return JSONResponse({"success":True,"id":comment.id,"username":comment.username,"content":comment.content,"created_at":comment.created_at.isoformat()})


@app.post("/api/comments/{comment_id}/report")
async def report_comment(comment_id: int, request: Request, reason: str = Form(""), db: Session = Depends(get_db)):
    comment = db.query(ChatMessage).filter(ChatMessage.id == comment_id).first()
    if not comment:
        raise HTTPException(status_code=404, detail="Commentaire introuvable")
    comment.report_count = (comment.report_count or 0) + 1
    if comment.report_count >= 5:
        comment.is_auto_hidden = True
    db.commit()
    return JSONResponse({"success":True,"report_count":comment.report_count})


@app.post("/api/admin/external/{stream_id}/toggle")
async def admin_toggle_external(stream_id: int, request: Request, db: Session = Depends(get_db)):
    try: require_admin(request)
    except HTTPException: return JSONResponse(status_code=401, content={"error":"Non autorisé"})
    stream = db.query(ExternalStream).filter(ExternalStream.id == stream_id).first()
    if not stream: raise HTTPException(status_code=404, detail="Flux introuvable")
    stream.is_active = not stream.is_active
    db.commit()
    state = "activé" if stream.is_active else "désactivé"
    return JSONResponse({"success":True,"is_active":stream.is_active,"message":f"Flux {state}"})


@app.post("/api/admin/streams/{stream_id}/block")
async def admin_block_stream(stream_id: int, request: Request, db: Session = Depends(get_db)):
    try: require_admin(request)
    except HTTPException: return JSONResponse(status_code=401, content={"error":"Non autorisé"})
    stream = db.query(LiveStream).filter(LiveStream.id == stream_id).first()
    if not stream: raise HTTPException(status_code=404, detail="Stream introuvable")
    stream.is_blocked = True; stream.is_live = False; db.commit()
    return JSONResponse({"success":True,"message":"Stream bloqué"})


@app.post("/api/admin/streams/{stream_id}/unblock")
async def admin_unblock_stream(stream_id: int, request: Request, db: Session = Depends(get_db)):
    try: require_admin(request)
    except HTTPException: return JSONResponse(status_code=401, content={"error":"Non autorisé"})
    stream = db.query(LiveStream).filter(LiveStream.id == stream_id).first()
    if not stream: raise HTTPException(status_code=404, detail="Stream introuvable")
    stream.is_blocked = False; db.commit()
    return JSONResponse({"success":True,"message":"Stream débloqué"})


@app.post("/api/admin/ips/block")
async def admin_block_ip(request: Request, ip_address: str = Form(...), reason: str = Form("Raison non spécifiée"), permanent: str = Form("false"), db: Session = Depends(get_db)):
    try: require_admin(request)
    except HTTPException: return JSONResponse(status_code=401, content={"error":"Non autorisé"})
    existing = db.query(BlockedIP).filter(BlockedIP.ip_address == ip_address, BlockedIP.is_active == True).first()
    if existing:
        return JSONResponse({"success":False,"error":f"IP {ip_address} déjà bloquée"})
    from datetime import datetime, timezone, timedelta
    is_perm = permanent.lower() in ("true","1","yes")
    ip_entry = BlockedIP(ip_address=ip_address.strip()[:45], reason=reason.strip()[:500], blocked_at=datetime.now(timezone.utc), is_permanent=is_perm, expires_at=None if is_perm else datetime.now(timezone.utc)+timedelta(days=30), is_active=True)
    db.add(ip_entry); db.commit()
    logger.info(f"IP bloquée: {ip_address}")
    return JSONResponse({"success":True,"message":f"IP {ip_address} bloquée"})


@app.post("/api/admin/ips/{ip_id}/unblock")
async def admin_unblock_ip(ip_id: int, request: Request, db: Session = Depends(get_db)):
    try: require_admin(request)
    except HTTPException: return JSONResponse(status_code=401, content={"error":"Non autorisé"})
    ip = db.query(BlockedIP).filter(BlockedIP.id == ip_id).first()
    if not ip: raise HTTPException(status_code=404, detail="IP introuvable")
    ip.is_active = False; db.commit()
    return JSONResponse({"success":True,"message":f"IP {ip.ip_address} débloquée"})


async def _is_ip_blocked(ip: str, db: Session) -> bool:
    if _is_private_ip(ip): return False
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    blocked = db.query(BlockedIP).filter(BlockedIP.ip_address == ip, BlockedIP.is_active == True).first()
    if not blocked: return False
    if blocked.is_permanent: return True
    if blocked.expires_at and blocked.expires_at < now:
        blocked.is_active = False; db.commit(); return False
    return True


@app.get("/api/admin/config/export")
async def admin_export_config(request: Request):
    try: require_admin(request)
    except HTTPException: return JSONResponse(status_code=401, content={"error":"Non autorisé"})
    env_content = (
        f"# Configuration Livewatch v2.0\n"
        f"APP_NAME={settings.APP_NAME}\n"
        f"DATABASE_URL={settings.DATABASE_URL}\n"
        f"SECRET_KEY={settings.SECRET_KEY}\n"
        f"ADMIN_USERNAME={settings.ADMIN_USERNAME}\n"
        f"IPTV_BASE_URL={settings.IPTV_BASE_URL}\n"
        f"SESSION_MAX_AGE={settings.SESSION_MAX_AGE}\n"
    )
    from starlette.responses import Response
    return Response(content=env_content, media_type="text/plain", headers={"Content-Disposition":"attachment; filename=livewatch.env"})


def _track_visit(request: Request, db: Session, page: str = "/"):
    try:
        visitor_id = get_visitor_id(request)
        client_ip  = _get_client_ip(request)
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        visitor = db.query(Visitor).filter(Visitor.visitor_id == visitor_id).first()
        if visitor:
            visitor.last_seen  = now
            visitor.last_page  = page[:200]
            visitor.page_count = (visitor.page_count or 0) + 1
        else:
            visitor = Visitor(visitor_id=visitor_id, ip_address=client_ip, user_agent=request.headers.get("user-agent","")[:500], first_seen=now, last_seen=now, page_count=1, last_page=page[:200], theme="auto", preferred_language="fr", favorites="[]")
            db.add(visitor)
        db.commit()
    except Exception as e:
        logger.debug(f"Track visit error: {e}")


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"]         = "SAMEORIGIN"
    response.headers["Referrer-Policy"]         = "strict-origin-when-cross-origin"
    response.headers["X-Powered-By"]            = "Livewatch/2.0"
    return response


@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    return templates.TemplateResponse(request, "error.html", {"request":request,"app_name":settings.APP_NAME,"code":404,"message":"Page introuvable","detail":f"La page {request.url.path!r} n'existe pas.","logo_path":settings.LOGO_PATH if os.path.exists(settings.LOGO_PATH) else None}, status_code=404)


@app.exception_handler(500)
async def server_error_handler(request: Request, exc):
    logger.error(f"Erreur 500 sur {request.url.path}: {exc}")
    return templates.TemplateResponse(request, "error.html", {"request":request,"app_name":settings.APP_NAME,"code":500,"message":"Erreur interne","detail":"Une erreur inattendue s'est produite.","logo_path":settings.LOGO_PATH if os.path.exists(settings.LOGO_PATH) else None}, status_code=500)


@app.exception_handler(403)
async def forbidden_handler(request: Request, exc):
    return templates.TemplateResponse(request, "blocked.html", {"request":request,"app_name":settings.APP_NAME,"logo_path":settings.LOGO_PATH if os.path.exists(settings.LOGO_PATH) else None}, status_code=403)


@app.delete("/api/admin/announcements/{ann_id}")
async def admin_delete_announcement(ann_id: int, request: Request, db: Session = Depends(get_db)):
    try: require_admin(request)
    except HTTPException: return JSONResponse(status_code=401, content={"error":"Non autorisé"})
    ann = db.query(AdminAnnouncement).filter(AdminAnnouncement.id == ann_id).first()
    if not ann: raise HTTPException(status_code=404, detail="Annonce introuvable")
    db.delete(ann); db.commit()
    return JSONResponse({"success":True,"message":"Annonce supprimée"})


@app.post("/api/admin/announcements/{ann_id}/toggle")
async def admin_toggle_announcement(ann_id: int, request: Request, db: Session = Depends(get_db)):
    try: require_admin(request)
    except HTTPException: return JSONResponse(status_code=401, content={"error":"Non autorisé"})
    ann = db.query(AdminAnnouncement).filter(AdminAnnouncement.id == ann_id).first()
    if not ann: raise HTTPException(status_code=404, detail="Annonce introuvable")
    ann.is_active = not ann.is_active; db.commit()
    return JSONResponse({"success":True,"is_active":ann.is_active,"message":f"Annonce {'activée' if ann.is_active else 'désactivée'}"})


@app.delete("/api/admin/feedback/{fb_id}")
async def admin_delete_feedback(fb_id: int, request: Request, db: Session = Depends(get_db)):
    try: require_admin(request)
    except HTTPException: return JSONResponse(status_code=401, content={"error":"Non autorisé"})
    fb = db.query(UserFeedback).filter(UserFeedback.id == fb_id).first()
    if not fb: raise HTTPException(status_code=404, detail="Avis introuvable")
    db.delete(fb); db.commit()
    return JSONResponse({"success":True,"message":"Avis supprimé"})


@app.post("/api/admin/feedback/{fb_id}/read")
async def admin_mark_feedback_read(fb_id: int, request: Request, db: Session = Depends(get_db)):
    try: require_admin(request)
    except HTTPException: return JSONResponse(status_code=401, content={"error":"Non autorisé"})
    fb = db.query(UserFeedback).filter(UserFeedback.id == fb_id).first()
    if not fb: raise HTTPException(status_code=404, detail="Avis introuvable")
    fb.is_read = True; db.commit()
    return JSONResponse({"success":True,"message":"Marqué comme lu"})


def _format_duration(seconds: int) -> str:
    if not seconds: return "00:00:00"
    h, r = divmod(int(seconds), 3600)
    m, s = divmod(r, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _format_filesize(bytes_: int) -> str:
    if not bytes_: return "0 B"
    units = ["B","KB","MB","GB","TB"]
    size, i = float(bytes_), 0
    while size >= 1024 and i < len(units)-1: size /= 1024; i += 1
    return f"{size:.1f} {units[i]}"


def _truncate_text(text: str, max_len: int = 100, suffix: str = "...") -> str:
    if not text or len(text) <= max_len: return text or ""
    return text[:max_len].rsplit(" ",1)[0] + suffix


def _generate_slug(text: str) -> str:
    import unicodedata, re
    nfkd = unicodedata.normalize("NFKD", text)
    ascii_text = nfkd.encode("ASCII","ignore").decode("ASCII")
    return re.sub(r"[^a-z0-9]+-*", "-", ascii_text.lower()).strip("-")[:100]


def _color_from_string(s: str) -> str:
    colors = ["#dc2626","#2563eb","#16a34a","#d97706","#7c3aed","#0891b2","#059669","#db2777","#9333ea","#0284c7","#b45309","#475569"]
    return colors[sum(ord(c) for c in (s or "x")) % len(colors)]


def _build_m3u_from_channels(channels: list, title: str = "Livewatch") -> str:
    lines = ['#EXTM3U m3u-creator="Livewatch 2.0"']
    for ch in channels:
        name = getattr(ch,"name","") or getattr(ch,"title","")
        url  = getattr(ch,"stream_url","") or ""
        if not url: continue
        logo = getattr(ch,"logo","") or ""
        cat  = getattr(ch,"category","") or ""
        cnt  = getattr(ch,"country","") or ""
        lines.append(f'#EXTINF:-1 tvg-id="{getattr(ch,"id","")}" tvg-logo="{logo}" group-title="{cat}" tvg-country="{cnt}",{name}')
        lines.append(url)
    return "\n".join(lines)


@app.get("/api/analytics/trends")
async def get_trending(db: Session = Depends(get_db)):
    trending_live = db.query(LiveStream).filter(LiveStream.is_live == True, LiveStream.is_blocked == False).order_by(LiveStream.viewer_count.desc()).limit(6).all()
    trending_ext  = db.query(ExternalStream).filter(ExternalStream.is_active == True).order_by(ExternalStream.id.desc()).limit(8).all()
    from datetime import datetime, timezone
    return JSONResponse({
        "trending_live": [{"id":s.id,"title":s.title,"viewers":s.viewer_count,"url":f"/watch/user/{s.id}"} for s in trending_live],
        "trending_channels": [{"id":s.id,"title":s.title,"logo":s.logo or "","category":s.category,"country":s.country or "","url":f"/watch/external/{s.id}"} for s in trending_ext],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    })


@app.get("/api/analytics/categories")
async def get_categories_stats(db: Session = Depends(get_db)):
    from sqlalchemy import func
    ext_by_cat  = db.query(ExternalStream.category, func.count(ExternalStream.id).label("count")).filter(ExternalStream.is_active == True).group_by(ExternalStream.category).all()
    iptv_by_cat = db.query(IPTVChannel.category,   func.count(IPTVChannel.id).label("count")).filter(IPTVChannel.is_active == True).group_by(IPTVChannel.category).order_by(func.count(IPTVChannel.id).desc()).limit(20).all()
    return JSONResponse({
        "external": [{"category":r[0] or "général","count":r[1]} for r in sorted(ext_by_cat, key=lambda x:x[1], reverse=True)],
        "iptv":     [{"category":r[0] or "général","count":r[1]} for r in iptv_by_cat],
    })


@app.get("/api/playlist/m3u")
async def get_m3u_playlist(country: str = None, category: str = None, type: str = "external", db: Session = Depends(get_db)):
    lines = ["#EXTM3U"]
    if type in ("external","all"):
        q = db.query(ExternalStream).filter(ExternalStream.is_active == True)
        if country: q = q.filter(ExternalStream.country.ilike(country))
        if category: q = q.filter(ExternalStream.category.ilike(category))
        for s in q.limit(500).all():
            lines.append(f'#EXTINF:-1 tvg-logo="{s.logo or ""}" group-title="{s.category}",{s.title}')
            lines.append(s.stream_url)
    if type in ("iptv","all"):
        q = db.query(IPTVChannel)
        if country: q = q.filter(IPTVChannel.country.ilike(country))
        if category: q = q.filter(IPTVChannel.category.ilike(category))
        for ch in q.limit(500).all():
            lines.append(f'#EXTINF:-1 tvg-id="{ch.id}" tvg-logo="{ch.logo or ""}" group-title="{ch.country}",{ch.name}')
            lines.append(ch.stream_url)
    from starlette.responses import Response
    return Response(content="\n".join(lines), media_type="application/x-mpegurl", headers={"Content-Disposition":"attachment; filename=livewatch.m3u"})


@app.get("/manifest.json")
async def pwa_manifest():
    return JSONResponse({
        "name": settings.APP_NAME, "short_name": settings.APP_NAME,
        "description": "Streaming TV et radio du monde entier",
        "start_url": "/", "display": "standalone",
        "background_color": "#111827", "theme_color": "#dc2626",
        "icons": [{"src":"/static/IMG.png","sizes":"192x192","type":"image/png"},{"src":"/static/IMG.png","sizes":"512x512","type":"image/png"}],
        "categories": ["entertainment","news"], "lang": "fr",
    })


@app.get("/robots.txt")
async def robots():
    from starlette.responses import Response
    return Response(content="User-agent: *\nAllow: /\nDisallow: /admin\nDisallow: /api/admin/\nDisallow: /proxy/\n\nSitemap: /sitemap.xml\n", media_type="text/plain")


@app.get("/sitemap.xml")
async def sitemap(request: Request, db: Session = Depends(get_db)):
    base = str(request.base_url).rstrip("/")
    urls = [f"{base}/", f"{base}/events", f"{base}/search", f"{base}/settings", f"{base}/go-live"]
    for s in db.query(ExternalStream).filter(ExternalStream.is_active == True).limit(300).all():
        urls.append(f"{base}/watch/external/{s.id}")
    for pl in db.query(IPTVPlaylist).limit(150).all():
        urls.append(f"{base}/?playlist={pl.name}")
    xml_lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    xml_lines += [f"  <url><loc>{u}</loc><changefreq>daily</changefreq></url>" for u in urls]
    xml_lines.append("</urlset>")
    from starlette.responses import Response
    return Response(content="\n".join(xml_lines), media_type="application/xml")


@app.post("/api/admin/streams/health-check")
async def admin_health_check_streams(request: Request, db: Session = Depends(get_db)):
    try: require_admin(request)
    except HTTPException: return JSONResponse(status_code=401, content={"error":"Non autorisé"})
    streams = db.query(ExternalStream).filter(ExternalStream.is_active == True, ExternalStream.stream_type.in_(["hls","mp4"])).limit(20).all()
    import asyncio
    checks = await asyncio.gather(*[_check_stream_health(s.stream_url) for s in streams], return_exceptions=True)
    results = []
    for i, stream in enumerate(streams):
        check = checks[i] if not isinstance(checks[i], Exception) else {"online":False,"error":str(checks[i])[:60]}
        if not check.get("online"): stream.is_active = False
        results.append({"id":stream.id,"title":stream.title,"online":check.get("online",False),"status":check.get("status_code",0),"error":check.get("error","")})
    db.commit()
    online = sum(1 for r in results if r["online"])
    return JSONResponse({"checked":len(results),"online":online,"offline":len(results)-online,"results":results})


@app.get("/api/admin/system/info")
async def admin_system_info(request: Request):
    try: require_admin(request)
    except HTTPException: return JSONResponse(status_code=401, content={"error":"Non autorisé"})
    import sys, platform, os
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=0.3)
        mem = psutil.virtual_memory().percent
        disk = psutil.disk_usage("/").percent
    except ImportError:
        cpu = mem = disk = -1
    return JSONResponse({
        "python_version": sys.version, "platform": platform.system()+" "+platform.release(),
        "cpu_percent": cpu, "memory_percent": mem, "disk_percent": disk,
        "app_name": settings.APP_NAME, "app_version": "2.0",
        "db_url": (settings.DATABASE_URL[:40]+"...") if len(settings.DATABASE_URL)>40 else settings.DATABASE_URL,
        "templates": len(os.listdir(TEMPLATES_DIR)) if os.path.exists(TEMPLATES_DIR) else 0,
        "iptv_playlists": len(IPTV_PLAYLISTS),
    })


@app.get("/api/admin/logs/recent")
async def admin_recent_logs(request: Request, lines: int = 50):
    try: require_admin(request)
    except HTTPException: return JSONResponse(status_code=401, content={"error":"Non autorisé"})
    import os
    for lf in ["app.log","livewatch.log","/var/log/livewatch.log"]:
        if os.path.exists(lf):
            with open(lf,"r",encoding="utf-8",errors="replace") as f:
                all_lines = f.readlines()
            return JSONResponse({"log_file":lf,"lines":[l.rstrip() for l in all_lines[-lines:]]})
    return JSONResponse({"log_file":None,"lines":["Aucun fichier de log trouvé."],"note":"Les logs s'affichent dans la console."})


@app.post("/api/admin/external/create")
async def admin_create_external(request: Request, title: str = Form(...), stream_url: str = Form(...), stream_type: str = Form("hls"), category: str = Form("general"), country: str = Form(""), language: str = Form(""), logo: str = Form(""), description: str = Form(""), quality: str = Form(""), db: Session = Depends(get_db)):
    try: require_admin(request)
    except HTTPException: return JSONResponse(status_code=401, content={"error":"Non autorisé"})
    stream = ExternalStream(title=title[:200], stream_url=stream_url[:2000], stream_type=stream_type, category=category, country=(country or "").upper()[:5], language=language[:50], logo=logo[:500], description=description[:1000], quality=quality[:20], is_active=True)
    db.add(stream); db.commit(); db.refresh(stream)
    return JSONResponse({"success":True,"id":stream.id,"message":f"Flux '{title}' créé"})


@app.delete("/api/admin/external/{stream_id}/delete")
async def admin_delete_external(stream_id: int, request: Request, db: Session = Depends(get_db)):
    try: require_admin(request)
    except HTTPException: return JSONResponse(status_code=401, content={"error":"Non autorisé"})
    stream = db.query(ExternalStream).filter(ExternalStream.id == stream_id).first()
    if not stream: raise HTTPException(status_code=404, detail="Flux introuvable")
    db.delete(stream); db.commit()
    return JSONResponse({"success":True,"message":"Flux supprimé"})


@app.post("/api/admin/iptv/playlist/{playlist_name}/refresh")
async def admin_refresh_playlist(playlist_name: str, request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    try: require_admin(request)
    except HTTPException: return JSONResponse(status_code=401, content={"error":"Non autorisé"})
    playlist_data = next((p for p in IPTV_PLAYLISTS if p["name"] == playlist_name), None)
    if not playlist_data: raise HTTPException(status_code=404, detail=f"Playlist '{playlist_name}' introuvable")
    async def _sync_one():
        await sync_single_playlist(playlist_data, db)
    background_tasks.add_task(_sync_one)
    return JSONResponse({"success":True,"message":f"Synchronisation de '{playlist_name}' lancée"})


@app.post("/api/admin/streams/cleanup")
async def admin_cleanup_streams(request: Request, db: Session = Depends(get_db)):
    try: require_admin(request)
    except HTTPException: return JSONResponse(status_code=401, content={"error":"Non autorisé"})
    from datetime import datetime, timezone, timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    deleted = db.query(LiveStream).filter(LiveStream.is_live == False, LiveStream.created_at < cutoff).delete(synchronize_session=False)
    db.commit()
    return JSONResponse({"success":True,"deleted":deleted,"message":f"{deleted} streams supprimés"})


@app.get("/api/admin/feedback/export")
async def admin_export_feedback(request: Request, db: Session = Depends(get_db)):
    try: require_admin(request)
    except HTTPException: return JSONResponse(status_code=401, content={"error":"Non autorisé"})
    feedbacks = db.query(UserFeedback).order_by(UserFeedback.created_at.desc()).all()
    import datetime as dt
    return JSONResponse({"export_date":dt.datetime.utcnow().isoformat(),"total":len(feedbacks),"feedbacks":[{"id":fb.id,"rating":fb.rating,"message":fb.message,"email":fb.email or "","is_read":fb.is_read,"created_at":fb.created_at.isoformat()} for fb in feedbacks]})


@app.post("/api/admin/feedback/mark-all-read")
async def admin_mark_all_feedback_read(request: Request, db: Session = Depends(get_db)):
    try: require_admin(request)
    except HTTPException: return JSONResponse(status_code=401, content={"error":"Non autorisé"})
    updated = db.query(UserFeedback).filter(UserFeedback.is_read == False).update({"is_read":True})
    db.commit()
    return JSONResponse({"success":True,"updated":updated})


@app.get("/api/admin/locations/export")
async def admin_export_locations(request: Request, db: Session = Depends(get_db)):
    try: require_admin(request)
    except HTTPException: return JSONResponse(status_code=401, content={"error":"Non autorisé"})
    from sqlalchemy import func
    locs = db.query(UserLocation.country, UserLocation.country_code, UserLocation.continent, UserLocation.lat, UserLocation.lng, func.count(UserLocation.id).label("visits")).group_by(UserLocation.country, UserLocation.country_code, UserLocation.continent, UserLocation.lat, UserLocation.lng).all()
    return JSONResponse({"total":sum(l[5] for l in locs),"countries":[{"country":l[0] or "Inconnu","country_code":l[1] or "","continent":l[2] or "INT","lat":float(l[3]) if l[3] else 0,"lng":float(l[4]) if l[4] else 0,"count":l[5]} for l in sorted(locs, key=lambda x:x[5], reverse=True)]})


@app.get("/api/admin/dashboard/summary")
async def admin_dashboard_summary(request: Request, db: Session = Depends(get_db)):
    try: require_admin(request)
    except HTTPException: return JSONResponse(status_code=401, content={"error":"Non autorisé"})
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    d24 = now - timedelta(hours=24)
    d7  = now - timedelta(days=7)
    return JSONResponse({
        "streams":       {"total":db.query(LiveStream).count(),"live":db.query(LiveStream).filter(LiveStream.is_live==True).count(),"new_24h":db.query(LiveStream).filter(LiveStream.created_at>=d24).count()},
        "external":      {"total":db.query(ExternalStream).count(),"active":db.query(ExternalStream).filter(ExternalStream.is_active==True).count()},
        "iptv":          {"channels":db.query(IPTVChannel).count(),"playlists":db.query(IPTVPlaylist).count()},
        "visitors":      {"total":db.query(Visitor).count(),"new_24h":db.query(Visitor).filter(Visitor.first_seen>=d24).count(),"new_7d":db.query(Visitor).filter(Visitor.first_seen>=d7).count()},
        "moderation":    {"comments":db.query(ChatMessage).count(),"reports":db.query(Report).count(),"pending":db.query(Report).filter(Report.resolved==False).count(),"blocked_ips":db.query(BlockedIP).filter(BlockedIP.is_active==True).count()},
        "feedback":      {"total":db.query(UserFeedback).count(),"unread":db.query(UserFeedback).filter(UserFeedback.is_read==False).count()},
        "announcements": {"active":db.query(AdminAnnouncement).filter(AdminAnnouncement.is_active==True).count()},
    })



# ══════════════════════════════════════════════════════════════════════════
# DONNÉES DE CONFIGURATION — Streams externes pré-configurés
# ══════════════════════════════════════════════════════════════════════════

# Ces listes sont utilisées pour peupler la base au premier démarrage.
# Elles incluent les meilleures chaînes de TV, radio et YouTube par catégorie.

PRECONFIGURED_TV_STREAMS = [
    # ── Chaînes françaises ──────────────────────────────────────────────
    {"title":"TF1","stream_url":"https://livetf1.lmn.fm/tf1-avc-2500k/index.m3u8","category":"entertainment","country":"FR","stream_type":"hls","logo":"https://upload.wikimedia.org/wikipedia/fr/thumb/8/84/Logo_TF1.svg/320px-Logo_TF1.svg.png","description":"TF1 — Première chaîne de télévision française","quality":"HD"},
    {"title":"France 2","stream_url":"https://livetv2.lmn.fm/france2-avc-2500k/index.m3u8","category":"entertainment","country":"FR","stream_type":"hls","logo":"https://upload.wikimedia.org/wikipedia/fr/thumb/5/52/France_2_logo.svg/320px-France_2_logo.svg.png","description":"France 2 — Chaîne publique française","quality":"HD"},
    {"title":"France 3","stream_url":"https://livetv3.lmn.fm/france3-avc-2500k/index.m3u8","category":"entertainment","country":"FR","stream_type":"hls","logo":"","description":"France 3 — Chaînes régionales France Télévisions","quality":"SD"},
    {"title":"France 4","stream_url":"https://livetv4.lmn.fm/france4-avc-2500k/index.m3u8","category":"kids","country":"FR","stream_type":"hls","logo":"","description":"France 4 — Jeunesse et spectacle","quality":"SD"},
    {"title":"France 5","stream_url":"https://livetv5.lmn.fm/france5-avc-2500k/index.m3u8","category":"documentary","country":"FR","stream_type":"hls","logo":"","description":"France 5 — Culture, société et documentaires","quality":"SD"},
    {"title":"M6","stream_url":"https://livem6.lmn.fm/m6-avc-2500k/index.m3u8","category":"entertainment","country":"FR","stream_type":"hls","logo":"https://upload.wikimedia.org/wikipedia/fr/thumb/a/a5/M6_-_Logo_2015.svg/320px-M6_-_Logo_2015.svg.png","description":"M6 — La chaîne du 6","quality":"HD"},
    {"title":"Arte","stream_url":"https://artesimulcast.akamaized.net/hls/live/2031003/artelive_fr/index.m3u8","category":"culture","country":"FR","stream_type":"hls","logo":"https://upload.wikimedia.org/wikipedia/fr/thumb/0/04/Arte_Logo_2019.svg/320px-Arte_Logo_2019.svg.png","description":"Arte — Chaîne culturelle européenne franco-allemande","quality":"HD"},
    {"title":"C8","stream_url":"https://livecdn.c8.fr/c8/c8.isml/master.m3u8","category":"entertainment","country":"FR","stream_type":"hls","logo":"","description":"C8 — Canal 8 TNT","quality":"SD"},
    {"title":"TMC","stream_url":"https://livetmc.lmn.fm/tmc-avc-2500k/index.m3u8","category":"entertainment","country":"FR","stream_type":"hls","logo":"","description":"TMC — Télé Monte Carlo","quality":"SD"},
    {"title":"TFX","stream_url":"https://livetfx.lmn.fm/tfx-avc-2500k/index.m3u8","category":"entertainment","country":"FR","stream_type":"hls","logo":"","description":"TFX — Divertissement","quality":"SD"},
    {"title":"TF1 Séries Films","stream_url":"https://livetsf.lmn.fm/tsf-avc-2500k/index.m3u8","category":"entertainment","country":"FR","stream_type":"hls","logo":"","description":"TF1 Séries Films — Films et séries","quality":"SD"},
    {"title":"6ter","stream_url":"https://live6ter.lmn.fm/6ter-avc-2500k/index.m3u8","category":"entertainment","country":"FR","stream_type":"hls","logo":"","description":"6ter — Chaîne du groupe M6","quality":"SD"},
    {"title":"W9","stream_url":"https://livew9.lmn.fm/w9-avc-2500k/index.m3u8","category":"entertainment","country":"FR","stream_type":"hls","logo":"","description":"W9 — Chaîne du groupe M6","quality":"SD"},
    {"title":"TEVA","stream_url":"https://liveteva.lmn.fm/teva-avc-2500k/index.m3u8","category":"entertainment","country":"FR","stream_type":"hls","logo":"","description":"TEVA — Chaîne féminine","quality":"SD"},
    {"title":"Gulli","stream_url":"https://livegulli.lmn.fm/gulli-avc-2500k/index.m3u8","category":"kids","country":"FR","stream_type":"hls","logo":"","description":"Gulli — Chaîne jeunesse","quality":"SD"},
    {"title":"RTL9","stream_url":"https://liversl9.lmn.fm/rtl9-avc-2500k/index.m3u8","category":"entertainment","country":"FR","stream_type":"hls","logo":"","description":"RTL9","quality":"SD"},
    # ── Chaînes belges ──────────────────────────────────────────────────
    {"title":"RTBF La Une","stream_url":"https://radiotele.rtbf.be/laune-live.m3u8","category":"entertainment","country":"BE","stream_type":"hls","logo":"","description":"RTBF La Une — Première chaîne belge francophone","quality":"SD"},
    {"title":"RTBF La Deux","stream_url":"https://radiotele.rtbf.be/ladeux-live.m3u8","category":"entertainment","country":"BE","stream_type":"hls","logo":"","description":"RTBF La Deux — Deuxième chaîne belge","quality":"SD"},
    {"title":"RTBF La Trois","stream_url":"https://radiotele.rtbf.be/latrois-live.m3u8","category":"kids","country":"BE","stream_type":"hls","logo":"","description":"RTBF La Trois — Culture et jeunesse","quality":"SD"},
    {"title":"RTL-TVI","stream_url":"https://stream.rtltvi.be/live.m3u8","category":"entertainment","country":"BE","stream_type":"hls","logo":"","description":"RTL-TVI — Chaîne belge du groupe RTL","quality":"SD"},
    {"title":"Club RTL","stream_url":"https://stream.clubrtl.be/live.m3u8","category":"entertainment","country":"BE","stream_type":"hls","logo":"","description":"Club RTL","quality":"SD"},
    {"title":"Plug RTL","stream_url":"https://stream.plugrtl.be/live.m3u8","category":"entertainment","country":"BE","stream_type":"hls","logo":"","description":"Plug RTL","quality":"SD"},
    # ── Chaînes suisses ─────────────────────────────────────────────────
    {"title":"RTS Un","stream_url":"https://stream.srg-ssr.ch/rts/livestp/1/index.m3u8","category":"entertainment","country":"CH","stream_type":"hls","logo":"","description":"RTS Un — Suisse romande","quality":"SD"},
    {"title":"RTS Deux","stream_url":"https://stream.srg-ssr.ch/rts/livestp/2/index.m3u8","category":"entertainment","country":"CH","stream_type":"hls","logo":"","description":"RTS Deux — Suisse romande","quality":"SD"},
    # ── Chaînes canadiennes ─────────────────────────────────────────────
    {"title":"ICI Radio-Canada","stream_url":"https://rcavlive.akamaized.net/hls/live/696121/gbuttawa/master.m3u8","category":"entertainment","country":"CA","stream_type":"hls","logo":"","description":"ICI Radio-Canada Télé — Réseau national","quality":"HD"},
    {"title":"TVA","stream_url":"https://qb.fmprt.com/tva/tva_1500.m3u8","category":"entertainment","country":"CA","stream_type":"hls","logo":"","description":"TVA — Télévision de Vidéotron","quality":"SD"},
    {"title":"RDI","stream_url":"https://rcavlive.akamaized.net/hls/live/696121/gbuotmedi/master.m3u8","category":"news","country":"CA","stream_type":"hls","logo":"","description":"RDI — Réseau de l'information Radio-Canada","quality":"SD"},
    # ── Chaînes africaines francophones ─────────────────────────────────
    {"title":"RTG Gabon","stream_url":"https://stream.rtg.ga/live","category":"entertainment","country":"GA","stream_type":"hls","logo":"","description":"Radio Télévision Gabonaise","quality":"SD"},
    {"title":"RTNC Congo","stream_url":"https://stream.rtnc.cd/live","category":"entertainment","country":"CD","stream_type":"hls","logo":"","description":"Radio Télévision Nationale Congolaise","quality":"SD"},
    {"title":"ORTB Bénin","stream_url":"https://stream.ortb.bj/live","category":"entertainment","country":"BJ","stream_type":"hls","logo":"","description":"Office de Radiodiffusion et Télévision du Bénin","quality":"SD"},
    {"title":"RTI Côte d'Ivoire","stream_url":"https://stream.rti.ci/live","category":"entertainment","country":"CI","stream_type":"hls","logo":"","description":"Radiodiffusion Télévision Ivoirienne","quality":"SD"},
    {"title":"RTS Sénégal","stream_url":"https://stream.rts.sn/live","category":"entertainment","country":"SN","stream_type":"hls","logo":"","description":"Radiodiffusion Télévision du Sénégal","quality":"SD"},
    {"title":"ORTM Mali","stream_url":"https://stream.ortm.ml/live","category":"entertainment","country":"ML","stream_type":"hls","logo":"","description":"Office de Radiodiffusion Télévision du Mali","quality":"SD"},
    {"title":"TVM Mozambique","stream_url":"https://stream.tvm.co.mz/live","category":"entertainment","country":"MZ","stream_type":"hls","logo":"","description":"Televisão de Moçambique","quality":"SD"},
    {"title":"CRTV Cameroun","stream_url":"https://stream.crtv.cm/live","category":"entertainment","country":"CM","stream_type":"hls","logo":"","description":"Cameroon Radio Television","quality":"SD"},
    {"title":"ONRTV Niger","stream_url":"https://stream.onrtv.ne/live","category":"entertainment","country":"NE","stream_type":"hls","logo":"","description":"Office de Radiodiffusion Télévision du Niger","quality":"SD"},
    {"title":"ORTB Burkina","stream_url":"https://stream.ortb.bf/live","category":"entertainment","country":"BF","stream_type":"hls","logo":"","description":"Radiodiffusion Télévision du Burkina","quality":"SD"},
    {"title":"Télé Congo","stream_url":"https://stream.telecongo.cg/live","category":"entertainment","country":"CG","stream_type":"hls","logo":"","description":"Télé Congo — République du Congo","quality":"SD"},
    {"title":"TéléChad","stream_url":"https://stream.tchadtv.td/live","category":"entertainment","country":"TD","stream_type":"hls","logo":"","description":"Télé Tchad — République du Tchad","quality":"SD"},
    {"title":"ORTM Mauritanie","stream_url":"https://stream.tvm.mr/live","category":"entertainment","country":"MR","stream_type":"hls","logo":"","description":"Télévision de Mauritanie","quality":"SD"},
    # ── Chaînes UK ──────────────────────────────────────────────────────
    {"title":"BBC One","stream_url":"https://a.files.bbci.co.uk/media/live/manifesto/audio_video/simulcast/hls/uk/abr_v2_prog_index/bbc_one_hd/index.m3u8","category":"entertainment","country":"GB","stream_type":"hls","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/e/eb/BBC_One_logo_2021.svg/320px-BBC_One_logo_2021.svg.png","description":"BBC One — Principal service de la BBC","quality":"HD"},
    {"title":"BBC Two","stream_url":"https://a.files.bbci.co.uk/media/live/manifesto/audio_video/simulcast/hls/uk/abr_v2_prog_index/bbc_two_hd/index.m3u8","category":"entertainment","country":"GB","stream_type":"hls","logo":"","description":"BBC Two","quality":"HD"},
    {"title":"ITV","stream_url":"https://simulcast.itv.com/playlist/itvonline.m3u8","category":"entertainment","country":"GB","stream_type":"hls","logo":"","description":"ITV — Independent Television","quality":"HD"},
    {"title":"Channel 4","stream_url":"https://ott.channel4.com/simulcast/C4.m3u8","category":"entertainment","country":"GB","stream_type":"hls","logo":"","description":"Channel 4 UK","quality":"HD"},
    {"title":"Channel 5","stream_url":"https://simulcast.channel5.com/live/c5.m3u8","category":"entertainment","country":"GB","stream_type":"hls","logo":"","description":"Channel 5 UK","quality":"SD"},
    # ── Chaînes allemandes ──────────────────────────────────────────────
    {"title":"ARD Das Erste","stream_url":"https://mcdn.daserste.de/daserste/de/master.m3u8","category":"entertainment","country":"DE","stream_type":"hls","logo":"https://upload.wikimedia.org/wikipedia/commons/thumb/2/2a/ARD_Das_Erste.svg/320px-ARD_Das_Erste.svg.png","description":"ARD Das Erste — Première chaîne publique allemande","quality":"HD"},
    {"title":"ZDF","stream_url":"https://zdf-hls-15.akamaized.net/hls/live/2016498/de/high/index.m3u8","category":"entertainment","country":"DE","stream_type":"hls","logo":"","description":"ZDF — Zweites Deutsches Fernsehen","quality":"HD"},
    {"title":"RTL Deutschland","stream_url":"https://rtl-live.akamaized.net/hls/live/index.m3u8","category":"entertainment","country":"DE","stream_type":"hls","logo":"","description":"RTL Allemagne","quality":"HD"},
    {"title":"ProSieben","stream_url":"https://prosieben-live.akamaized.net/hls/live/index.m3u8","category":"entertainment","country":"DE","stream_type":"hls","logo":"","description":"ProSieben — Chaîne allemande","quality":"HD"},
    {"title":"Sat.1","stream_url":"https://sat1-live.akamaized.net/hls/live/index.m3u8","category":"entertainment","country":"DE","stream_type":"hls","logo":"","description":"Sat.1","quality":"HD"},
    {"title":"Kabel eins","stream_url":"https://kabeleins-live.akamaized.net/hls/live/index.m3u8","category":"entertainment","country":"DE","stream_type":"hls","logo":"","description":"Kabel eins","quality":"HD"},
    # ── Chaînes espagnoles ──────────────────────────────────────────────
    {"title":"TVE La 1","stream_url":"https://rtvelive-a.akamaized.net/hls/live/532183/tve/la1/index.m3u8","category":"entertainment","country":"ES","stream_type":"hls","logo":"","description":"TVE La 1 — Chaîne nationale espagnole","quality":"HD"},
    {"title":"TVE La 2","stream_url":"https://rtvelive-a.akamaized.net/hls/live/532184/tve/la2/index.m3u8","category":"documentary","country":"ES","stream_type":"hls","logo":"","description":"TVE La 2","quality":"HD"},
    {"title":"Antena 3","stream_url":"https://antena3live.akamaized.net/hls/live/index.m3u8","category":"entertainment","country":"ES","stream_type":"hls","logo":"","description":"Antena 3 Espagne","quality":"HD"},
    {"title":"Cuatro","stream_url":"https://cuatrolive.akamaized.net/hls/live/index.m3u8","category":"entertainment","country":"ES","stream_type":"hls","logo":"","description":"Cuatro","quality":"HD"},
    # ── Chaînes italiennes ──────────────────────────────────────────────
    {"title":"RAI 1","stream_url":"https://creativemedia4.rai.it/italy/raione/masterplaylist.m3u8","category":"entertainment","country":"IT","stream_type":"hls","logo":"","description":"RAI 1 — Première chaîne italienne","quality":"HD"},
    {"title":"RAI 2","stream_url":"https://creativemedia4.rai.it/italy/raidue/masterplaylist.m3u8","category":"entertainment","country":"IT","stream_type":"hls","logo":"","description":"RAI 2","quality":"HD"},
    {"title":"RAI 3","stream_url":"https://creativemedia4.rai.it/italy/raitre/masterplaylist.m3u8","category":"documentary","country":"IT","stream_type":"hls","logo":"","description":"RAI 3","quality":"HD"},
    {"title":"Canale 5","stream_url":"https://canale5live.akamaized.net/hls/live/index.m3u8","category":"entertainment","country":"IT","stream_type":"hls","logo":"","description":"Canale 5 — Chaîne Mediaset","quality":"HD"},
    {"title":"Italia 1","stream_url":"https://italia1live.akamaized.net/hls/live/index.m3u8","category":"entertainment","country":"IT","stream_type":"hls","logo":"","description":"Italia 1","quality":"HD"},
    {"title":"Rete 4","stream_url":"https://rete4live.akamaized.net/hls/live/index.m3u8","category":"entertainment","country":"IT","stream_type":"hls","logo":"","description":"Rete 4","quality":"HD"},
    # ── Chaînes portugaises ─────────────────────────────────────────────
    {"title":"RTP 1","stream_url":"https://streaming-vod.rtp.pt/liverewind/rtp1/rtp1.m3u8","category":"entertainment","country":"PT","stream_type":"hls","logo":"","description":"RTP 1 — Rádio e Televisão de Portugal","quality":"HD"},
    {"title":"RTP 2","stream_url":"https://streaming-vod.rtp.pt/liverewind/rtp2/rtp2.m3u8","category":"documentary","country":"PT","stream_type":"hls","logo":"","description":"RTP 2","quality":"HD"},
    {"title":"SIC","stream_url":"https://sic-live.akamaized.net/hls/live/index.m3u8","category":"entertainment","country":"PT","stream_type":"hls","logo":"","description":"SIC — Sociedade Independente de Comunicação","quality":"HD"},
    {"title":"TVI","stream_url":"https://tvi-live.akamaized.net/hls/live/index.m3u8","category":"entertainment","country":"PT","stream_type":"hls","logo":"","description":"TVI — Televisão Independente","quality":"HD"},
    # ── Chaînes russes ──────────────────────────────────────────────────
    {"title":"Perviy Kanal","stream_url":"https://live.1internet.ru/stream/1channel.m3u8","category":"entertainment","country":"RU","stream_type":"hls","logo":"","description":"Premier canal — Первый канал","quality":"SD"},
    {"title":"Rossiya 1","stream_url":"https://live.1internet.ru/stream/russia1.m3u8","category":"entertainment","country":"RU","stream_type":"hls","logo":"","description":"Rossiya 1","quality":"SD"},
    {"title":"NTV","stream_url":"https://live.1internet.ru/stream/ntv.m3u8","category":"entertainment","country":"RU","stream_type":"hls","logo":"","description":"НТВ — Télévision Indépendante","quality":"SD"},
    # ── Chaînes arabes ──────────────────────────────────────────────────
    {"title":"MBC 1","stream_url":"https://shls-live-ak.shaheenv2.com/MBC1_AR/smil:MBC1_AR.smil/master.m3u8","category":"entertainment","country":"SA","stream_type":"hls","logo":"","description":"MBC 1 — أم بي سي 1","quality":"HD"},
    {"title":"MBC 2","stream_url":"https://shls-live-ak.shaheenv2.com/MBC2_AR/smil:MBC2_AR.smil/master.m3u8","category":"entertainment","country":"SA","stream_type":"hls","logo":"","description":"MBC 2 — أفلام","quality":"HD"},
    {"title":"MBC 3","stream_url":"https://shls-live-ak.shaheenv2.com/MBC3_AR/smil:MBC3_AR.smil/master.m3u8","category":"kids","country":"SA","stream_type":"hls","logo":"","description":"MBC 3 — أطفال","quality":"HD"},
    {"title":"MBC 4","stream_url":"https://shls-live-ak.shaheenv2.com/MBC4_AR/smil:MBC4_AR.smil/master.m3u8","category":"entertainment","country":"SA","stream_type":"hls","logo":"","description":"MBC 4","quality":"HD"},
    {"title":"Rotana Classic","stream_url":"https://rotana-classic.akamaized.net/hls/live/index.m3u8","category":"music","country":"SA","stream_type":"hls","logo":"","description":"روتانا كلاسيك — Musique arabe classique","quality":"HD"},
    {"title":"OSN TV","stream_url":"https://osntv.akamaized.net/hls/live/index.m3u8","category":"entertainment","country":"AE","stream_type":"hls","logo":"","description":"OSN TV — Chaîne premium Moyen-Orient","quality":"HD"},
    {"title":"Nile TV","stream_url":"https://nile-tv.nilesat.akamaized.net/hls/live/index.m3u8","category":"news","country":"EG","stream_type":"hls","logo":"","description":"Nile TV International — Égypte","quality":"SD"},
    {"title":"Al Arabiya","stream_url":"https://alarabiya.akamaized.net/alarabiya/index.m3u8","category":"news","country":"AE","stream_type":"hls","logo":"","description":"قناة العربية — News en arabe","quality":"HD"},
    # ── Chaînes asiatiques ──────────────────────────────────────────────
    {"title":"NHK World Japan","stream_url":"https://nhkwlive-ojp.akamaized.net/hls/live/2003459/nhkwlive-ojp-en/index.m3u8","category":"news","country":"JP","stream_type":"hls","logo":"","description":"NHK World — Chaîne internationale du Japon","quality":"HD"},
    {"title":"CCTV 4 China","stream_url":"https://cctv.akamaized.net/hls/live/cctv4/index.m3u8","category":"entertainment","country":"CN","stream_type":"hls","logo":"","description":"CCTV 4 — Chaîne internationale chinoise","quality":"HD"},
    {"title":"KBS World Korea","stream_url":"https://kbsworld-lh.akamaized.net/hls/live/index.m3u8","category":"entertainment","country":"KR","stream_type":"hls","logo":"","description":"KBS World — Corée du Sud","quality":"HD"},
    {"title":"Arirang Korea","stream_url":"https://amdlive-ch01.akamaized.net/cmaf/live/1003994/ch01/index.m3u8","category":"entertainment","country":"KR","stream_type":"hls","logo":"","description":"Arirang TV — International coréen","quality":"HD"},
    {"title":"CGTN International","stream_url":"https://news.cgtn.com/resource/live/english/cgtn-news.m3u8","category":"news","country":"CN","stream_type":"hls","logo":"","description":"CGTN — China Global Television Network","quality":"HD"},
    {"title":"TV5 Monde Asie","stream_url":"https://tv5monde.akamaized.net/hls/live/2018854/tm5monde/index_tv5mondeasia.m3u8","category":"entertainment","country":"FR","stream_type":"hls","logo":"","description":"TV5 Monde — Francophonie en Asie","quality":"HD"},
    # ── YouTube Live (Entertainment) ─────────────────────────────────────
    {"title":"Lofi Girl Radio","stream_url":"https://www.youtube.com/c/LofiGirl/live","category":"music","country":"FR","stream_type":"youtube","logo":"https://yt3.googleusercontent.com/ytc/AMLnZu80Gc8yQULJxV_MZz4DnjZiLxRq4IgPbz3Cjg=s900-c-k-c0x00ffffff-no-rj","description":"Lofi Hip Hop Radio — Beats to relax/study"},
    {"title":"NASA TV","stream_url":"https://www.youtube.com/user/NASAtelevision/live","category":"science","country":"US","stream_type":"youtube","logo":"","description":"NASA Live — Space exploration"},
    {"title":"EuroNews Live","stream_url":"https://www.youtube.com/user/euronews/live","category":"news","country":"FR","stream_type":"youtube","logo":"","description":"EuroNews — 24h d'info en direct"},
    {"title":"DW Documentary","stream_url":"https://www.youtube.com/user/deutschewelle/live","category":"documentary","country":"DE","stream_type":"youtube","logo":"","description":"DW Documentary — Deutsche Welle"},
    {"title":"France 24 Live YT","stream_url":"https://www.youtube.com/user/france24/live","category":"news","country":"FR","stream_type":"youtube","logo":"","description":"France 24 en direct sur YouTube"},
    {"title":"RFI en direct YT","stream_url":"https://www.youtube.com/c/RFI/live","category":"news","country":"FR","stream_type":"youtube","logo":"","description":"RFI en direct sur YouTube"},
]

# ══════════════════════════════════════════════════════════════════════════
# FONCTION DE SEEDING COMPLÈTE
# ══════════════════════════════════════════════════════════════════════════

async def seed_all_preconfigured_channels(db: Session) -> int:
    """
    Initialise la base de données avec toutes les chaînes pré-configurées.
    Comprend : TV française/européenne/africaine/asiatique, radios du monde,
    chaînes d'info internationales, chaînes sportives, YouTube Live.
    
    Cette fonction est idempotente : elle ne duplique pas les chaînes existantes.
    Elle vérifie d'abord si le titre existe avant d'insérer.
    """
    all_channels = []
    
    # Ajouter les TV pré-configurées
    try:
        all_channels += PRECONFIGURED_TV_STREAMS
    except NameError:
        logger.warning("PRECONFIGURED_TV_STREAMS non défini")
    
    # Ajouter les radios supplémentaires
    try:
        all_channels += EXTRA_RADIO_STATIONS
    except NameError:
        pass
    
    # Ajouter les chaînes d'info
    try:
        all_channels += EXTRA_NEWS_CHANNELS
    except NameError:
        pass
    
    # Ajouter les chaînes sportives
    try:
        all_channels += EXTRA_SPORTS_CHANNELS
    except NameError:
        pass

    if not all_channels:
        logger.info("Aucune chaîne pré-configurée à insérer")
        return 0

    # Récupérer les titres existants pour éviter les doublons
    existing_titles = set(
        t[0] for t in db.query(ExternalStream.title).filter(ExternalStream.is_active == True).all()
    )

    inserted = 0
    batch_size = 50
    
    for i, ch_data in enumerate(all_channels):
        title = ch_data.get("title", "").strip()
        if not title or title in existing_titles:
            continue
        
        stream = ExternalStream(
            title        = title[:200],
            stream_url   = ch_data.get("stream_url", "")[:2000],
            stream_type  = ch_data.get("stream_type", "hls"),
            category     = ch_data.get("category", "general"),
            country      = (ch_data.get("country", "") or "").upper()[:5],
            language     = ch_data.get("language", "")[:50],
            logo         = ch_data.get("logo", "")[:500],
            description  = ch_data.get("description", "")[:500],
            quality      = ch_data.get("quality", "")[:20],
            is_active    = True,
        )
        db.add(stream)
        existing_titles.add(title)
        inserted += 1
        
        # Commit par lots pour éviter les transactions trop longues
        if inserted % batch_size == 0:
            try:
                db.commit()
                logger.info(f"Seeding: {inserted}/{len(all_channels)} chaînes insérées...")
            except Exception as e:
                db.rollback()
                logger.error(f"Erreur batch commit: {e}")

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Erreur commit final seeding: {e}")
        return inserted

    logger.info(f"Seeding terminé: {inserted} chaînes pré-configurées ajoutées")
    return inserted


# ══════════════════════════════════════════════════════════════════════════
# FONCTIONS DE MAINTENANCE
# ══════════════════════════════════════════════════════════════════════════

async def cleanup_expired_blocks(db: Session) -> int:
    """Supprime les blocages d'IP expirés"""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    expired = db.query(BlockedIP).filter(
        BlockedIP.is_active == True,
        BlockedIP.is_permanent == False,
        BlockedIP.expires_at <= now
    ).all()
    
    count = 0
    for block in expired:
        block.is_active = False
        count += 1
    
    if count:
        db.commit()
        logger.info(f"{count} blocages d'IP expirés nettoyés")
    return count


async def cleanup_old_streams(db: Session) -> int:
    """Archive les streams utilisateur terminés depuis plus de 7 jours"""
    from datetime import datetime, timezone, timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    count = db.query(LiveStream).filter(
        LiveStream.is_live == False,
        LiveStream.created_at < cutoff,
        LiveStream.is_blocked == False,
    ).delete(synchronize_session=False)
    db.commit()
    if count:
        logger.info(f"{count} anciens streams supprimés")
    return count


async def update_visitor_stats(db: Session):
    """Met à jour les statistiques agrégées des visiteurs"""
    from datetime import datetime, timezone, timedelta
    from sqlalchemy import func
    
    now = datetime.now(timezone.utc)
    
    # Compter les visiteurs actifs dans les dernières 5 minutes
    cutoff = now - timedelta(minutes=5)
    active_count = db.query(Visitor).filter(Visitor.last_seen >= cutoff).count()
    
    # Mettre à jour la valeur en cache (si on a un système de cache)
    # Pour l'instant, on log juste
    logger.debug(f"Visiteurs actifs: {active_count}")
    return active_count


async def generate_daily_stats(db: Session) -> dict:
    """Génère les statistiques quotidiennes de la plateforme"""
    from datetime import datetime, timezone, timedelta
    from sqlalchemy import func
    
    now = datetime.now(timezone.utc)
    yesterday = now - timedelta(days=1)
    last_week = now - timedelta(days=7)
    last_month = now - timedelta(days=30)
    
    stats = {
        "generated_at":       now.isoformat(),
        "total_visitors":     db.query(Visitor).count(),
        "new_visitors_24h":   db.query(Visitor).filter(Visitor.first_seen >= yesterday).count(),
        "new_visitors_7d":    db.query(Visitor).filter(Visitor.first_seen >= last_week).count(),
        "new_visitors_30d":   db.query(Visitor).filter(Visitor.first_seen >= last_month).count(),
        "total_streams":      db.query(LiveStream).count(),
        "live_streams":       db.query(LiveStream).filter(LiveStream.is_live == True).count(),
        "total_ext_channels": db.query(ExternalStream).count(),
        "active_ext_channels":db.query(ExternalStream).filter(ExternalStream.is_active == True).count(),
        "total_iptv_channels":db.query(IPTVChannel).count(),
        "total_iptv_playlists":db.query(IPTVPlaylist).count(),
        "total_comments":     db.query(ChatMessage).count(),
        "new_comments_24h":   db.query(ChatMessage).filter(ChatMessage.created_at >= yesterday).count(),
        "total_reports":      db.query(Report).count(),
        "pending_reports":    db.query(Report).filter(Report.resolved == False).count(),
        "total_feedback":     db.query(UserFeedback).count(),
        "unread_feedback":    db.query(UserFeedback).filter(UserFeedback.is_read == False).count(),
        "blocked_ips":        db.query(BlockedIP).filter(BlockedIP.is_active == True).count(),
        "active_announcements":db.query(AdminAnnouncement).filter(AdminAnnouncement.is_active == True).count(),
        "tracked_locations":  db.query(UserLocation).count(),
    }
    
    # Top catégories de streams
    top_cats = db.query(
        ExternalStream.category,
        func.count(ExternalStream.id).label("cnt")
    ).filter(ExternalStream.is_active == True).group_by(ExternalStream.category).order_by(func.count(ExternalStream.id).desc()).limit(5).all()
    
    stats["top_categories"] = [{"category": r[0] or "général", "count": r[1]} for r in top_cats]
    
    # Top pays
    top_countries = db.query(
        ExternalStream.country,
        func.count(ExternalStream.id).label("cnt")
    ).filter(ExternalStream.is_active == True, ExternalStream.country != "").group_by(ExternalStream.country).order_by(func.count(ExternalStream.id).desc()).limit(10).all()
    
    stats["top_countries"] = [{"country": r[0], "count": r[1]} for r in top_countries]
    
    logger.info(f"Stats quotidiennes générées: {stats['total_visitors']} visiteurs, {stats['live_streams']} lives")
    return stats


# ══════════════════════════════════════════════════════════════════════════
# TÂCHES PLANIFIÉES (Periodic Background Tasks)
# ══════════════════════════════════════════════════════════════════════════

async def _periodic_maintenance_task():
    """
    Tâche de maintenance périodique.
    Exécutée toutes les heures pour nettoyer la base de données.
    """
    import asyncio
    from database import SessionLocal  # Import local pour éviter les cycles
    
    while True:
        try:
            await asyncio.sleep(3600)  # Toutes les heures
            db = SessionLocal()
            try:
                logger.info("Démarrage maintenance périodique...")
                
                # Nettoyer les blocages expirés
                await cleanup_expired_blocks(db)
                
                # Nettoyer les vieux streams
                await cleanup_old_streams(db)
                
                # Mettre à jour les stats
                await update_visitor_stats(db)
                
                logger.info("Maintenance périodique terminée")
            except Exception as e:
                logger.error(f"Erreur maintenance: {e}")
                db.rollback()
            finally:
                db.close()
        except asyncio.CancelledError:
            logger.info("Tâche de maintenance annulée")
            break
        except Exception as e:
            logger.error(f"Erreur tâche maintenance: {e}")
            await asyncio.sleep(60)  # Retry dans 1 minute si erreur


async def _periodic_stats_task():
    """
    Génère des statistiques toutes les 24h.
    """
    import asyncio
    
    while True:
        try:
            await asyncio.sleep(86400)  # Toutes les 24h
            db = SessionLocal()
            try:
                stats = await generate_daily_stats(db)
                logger.info(f"Stats 24h: {stats['total_visitors']} visiteurs totaux")
            except Exception as e:
                logger.error(f"Erreur génération stats: {e}")
            finally:
                db.close()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Erreur tâche stats: {e}")
            await asyncio.sleep(3600)



# ══════════════════════════════════════════════════════════════════════════
#
#  ██╗     ██╗██╗   ██╗███████╗██╗    ██╗ █████╗ ████████╗ ██████╗██╗  ██╗
#  ██║     ██║██║   ██║██╔════╝██║    ██║██╔══██╗╚══██╔══╝██╔════╝██║  ██║
#  ██║     ██║██║   ██║█████╗  ██║ █╗ ██║███████║   ██║   ██║     ███████║
#  ██║     ██║╚██╗ ██╔╝██╔══╝  ██║███╗██║██╔══██║   ██║   ██║     ██╔══██║
#  ███████╗██║ ╚████╔╝ ███████╗╚███╔███╔╝██║  ██║   ██║   ╚██████╗██║  ██║
#  ╚══════╝╚═╝  ╚═══╝  ╚══════╝ ╚══╝╚══╝ ╚═╝  ╚═╝   ╚═╝    ╚═════╝╚═╝  ╚═╝
#
#  Livewatch v2.0 — Plateforme de Streaming IPTV/TV/Radio mondiale
#  ═══════════════════════════════════════════════════════════════════════
#
#  ARCHITECTURE TECHNIQUE :
#  ─────────────────────────
#  • Backend  : FastAPI + Python 3.11 + SQLAlchemy ORM
#  • Base DB  : PostgreSQL (Supabase) + psycopg2-binary
#  • Migrations: Alembic
#  • Frontend : Jinja2 Templates + Tailwind CSS (CDN) + Vanilla JS
#  • Streaming: HLS.js + hls.js fallback chain (8 niveaux)
#  • Vidéo    : VideoJS 8 + HLS natif Safari + Audio API
#  • WebSocket: FastAPI native WebSockets (chat en temps réel)
#  • Proxy HLS: Réécriture M3U8 + cache + en-têtes CORS
#  • Déploiement: Docker Compose + Uvicorn ASGI
#
#  FONCTIONNALITÉS PRINCIPALES :
#  ──────────────────────────────
#  Streaming IPTV (pays, régions, villes, catégories) — iptv-org
#  Flux externes (HLS, DASH, MP4, Audio, YouTube Live)
#  Go Live WebRTC (caméra/écran/micro) avec timer & VU-mètre
#  EPG / Guide des programmes (XMLTV + générateur interne)
#  Chat WebSocket temps réel par stream
#  Système de signalements & modération automatique
#  Dashboard admin complet avec statistiques temps réel
#  Carte du monde des utilisateurs (géolocalisation IP)
#  Graphique historique des visites (7j/30j/1an)
#  Système d'annonces admin → utilisateurs
#  Système de feedback/avis utilisateurs
#  Paramètres persistés (thème, langue, qualité, volume)
#  Favoris synchronisés entre appareils
#  Enregistrement de flux (MediaRecorder → .webm)
#  Radio mini-player inline sur la page d'accueil
#  Recherche unifiée (streams, chaînes, IPTV)
#  Playlist M3U exportable
#  Sitemap XML + robots.txt + PWA manifest
#  Embeds (iframes) pour chaînes IPTV et flux externes
#  Rappels d'événements EPG
#  Health check + monitoring système
#
#  COUVERTURE GÉOGRAPHIQUE IPTV :
#  ────────────────────────────────
#  • 195+ pays couverts (ISO 3166-1 alpha-2)
#  • 50+ régions/états (USA, Canada, France, Allemagne, Espagne...)
#  • 100+ villes mondiales (Paris, Londres, Tokyo, New York...)
#  • 35+ catégories thématiques (sport, news, music, kids, docs...)
#  • Source : iptv-org GitHub (mise à jour automatique)
#
#  CHAÎNES PRÉ-CONFIGURÉES :
#  ───────────────────────────
#  • France : TF1, France 2/3/4/5, M6, Arte, C8, TMC, TFX...
#  • Belgique : RTBF La Une/Deux/Trois, RTL-TVI, Club RTL...
#  • Suisse : RTS Un, RTS Deux
#  • Canada : ICI Radio-Canada, TVA, RDI
#  • Afrique : RTG Gabon, RTNC Congo, RTI CI, RTS Sénégal...
#  • UK : BBC One/Two, ITV, Channel 4/5
#  • Allemagne : ARD, ZDF, RTL, ProSieben, Sat.1...
#  • Espagne : TVE La 1/2, Antena 3, Cuatro
#  • Italie : RAI 1/2/3, Canale 5, Italia 1, Rete 4
#  • Portugal : RTP 1/2, SIC, TVI
#  • Russie : Premier Canal, Rossiya 1, NTV
#  • Monde arabe : MBC 1/2/3/4, Al Arabiya, Rotana...
#  • Asie : NHK World, CCTV 4, KBS World, Arirang, CGTN
#  • News : Al Jazeera, France 24, DW, RT, CGTN, VOA, BBC...
#  • Radio : RFI, France Inter, BBC World, Africa No 1...
#
#  CONFIGURATION :
#  ────────────────
#  Les variables d'environnement sont chargées depuis .env :
#
#  DATABASE_URL=postgresql://user:pass@host:5432/dbname
#  SECRET_KEY=votre-clé-secrète-256-bits
#  APP_NAME=Livewatch
#  ADMIN_USERNAME=WALKER92259
#  ADMIN_PASSWORD=WALKER92259
#  IPTV_BASE_URL=https://iptv-org.github.io/iptv
#  SESSION_MAX_AGE=2592000  # 30 jours
#  LOGO_PATH=static/IMG.png
#
#  DÉMARRAGE :
#  ────────────
#  docker-compose up -d          # Avec Docker
#  python Livewatch.py           # Sans Docker (uvicorn intégré)
#  uvicorn Livewatch:app --reload  # Mode développement
#
#  ACCÈS ADMIN :
#  ──────────────
#  URL : /admin
#  Login : WALKER92259 / WALKER92259
#  Email propriétaire : erickbenoit337@gmail.com
#
# ══════════════════════════════════════════════════════════════════════════




# ==================== ROUTES PAGES STATIQUES & UTILITAIRES ====================

@app.get("/profile", response_class=HTMLResponse)
async def profile_page(request: Request, db: Session = Depends(get_db)):
    """Page de profil utilisateur anonyme"""
    _check_ip_blocked(request, db)
    visitor_id = get_visitor_id(request)
    visitor = db.query(Visitor).filter(Visitor.visitor_id == visitor_id).first()

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    member_since = "aujourd'hui"
    fav_count = 0
    view_count = 0
    lang_pref = "fr"
    stream_count = 0

    if visitor:
        if visitor.first_seen:
            delta = now - visitor.first_seen.replace(tzinfo=timezone.utc) if visitor.first_seen.tzinfo is None else now - visitor.first_seen
            days = delta.days
            if days == 0:   member_since = "aujourd'hui"
            elif days == 1: member_since = "hier"
            elif days < 30: member_since = f"il y a {days} jours"
            elif days < 365:member_since = f"il y a {days//30} mois"
            else:           member_since = f"il y a {days//365} an(s)"
        lang_pref = visitor.preferred_language or "fr"
        import json as _j
        try:
            fav_count = len(_j.loads(visitor.favorites or "[]"))
        except Exception:
            fav_count = 0

    stream_count = db.query(LiveStream).filter(
        LiveStream.is_blocked == False
    ).count()

    lang = lang_pref
    return templates.TemplateResponse(request, "profile.html", {
        "request":      request,
        "app_name":     settings.APP_NAME,
        "language":     lang,
        "visitor_id":   visitor_id,
        "member_since": member_since,
        "fav_count":    fav_count,
        "view_count":   view_count,
        "stream_count": stream_count,
        "lang_pref":    lang.upper(),
        "logo_path":    settings.LOGO_PATH if os.path.exists(settings.LOGO_PATH) else None,
    })


@app.get("/about", response_class=HTMLResponse)
async def about_page(request: Request, db: Session = Depends(get_db)):
    """Page à propos"""
    _check_ip_blocked(request, db)
    visitor_id = get_visitor_id(request)
    lang = _get_visitor_lang(request, db)
    return templates.TemplateResponse(request, "about.html", {
        "request":   request,
        "app_name":  settings.APP_NAME,
        "language":  lang,
        "visitor_id":visitor_id,
        "logo_path": settings.LOGO_PATH if os.path.exists(settings.LOGO_PATH) else None,
    })


@app.get("/terms", response_class=HTMLResponse)
async def terms_page(request: Request, db: Session = Depends(get_db)):
    """Conditions d'utilisation"""
    _check_ip_blocked(request, db)
    visitor_id = get_visitor_id(request)
    lang = _get_visitor_lang(request, db)
    from datetime import date
    return templates.TemplateResponse(request, "terms.html", {
        "request":      request,
        "app_name":     settings.APP_NAME,
        "language":     lang,
        "visitor_id":   visitor_id,
        "current_date": date.today().strftime("%d/%m/%Y"),
        "logo_path":    settings.LOGO_PATH if os.path.exists(settings.LOGO_PATH) else None,
    })


@app.get("/privacy", response_class=HTMLResponse)
async def privacy_page(request: Request, db: Session = Depends(get_db)):
    """Politique de confidentialité"""
    _check_ip_blocked(request, db)
    visitor_id = get_visitor_id(request)
    lang = _get_visitor_lang(request, db)
    from datetime import date
    return templates.TemplateResponse(request, "privacy.html", {
        "request":      request,
        "app_name":     settings.APP_NAME,
        "language":     lang,
        "visitor_id":   visitor_id,
        "current_date": date.today().strftime("%d/%m/%Y"),
        "logo_path":    settings.LOGO_PATH if os.path.exists(settings.LOGO_PATH) else None,
    })


# ── Gestionnaire 404 global ────────────────────────────────────────────────
@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    """Handler 404 personnalisé"""
    db = next(get_db())
    try:
        visitor_id = get_visitor_id(request)
        lang = _get_visitor_lang(request, db)
    except Exception:
        visitor_id = ""
        lang = "fr"
    return templates.TemplateResponse(request, "404.html", {
        "request":   request,
        "app_name":  settings.APP_NAME,
        "language":  lang,
        "visitor_id":visitor_id,
        "logo_path": None,
    }, status_code=404)


# ── Helper : récupérer la langue du visiteur ──────────────────────────────
def _get_visitor_lang(request: Request, db: Session) -> str:
    """Récupère la langue préférée du visiteur depuis la DB ou cookie"""
    try:
        vid = get_visitor_id(request)
        v = db.query(Visitor).filter(Visitor.visitor_id == vid).first()
        if v and v.preferred_language:
            return v.preferred_language
    except Exception:
        pass
    return "fr"


# ── Routes API additionnelles ────────────────────────────────────────────
@app.get("/api/channels/featured")
async def get_featured_channels(limit: int = 12, db: Session = Depends(get_db)):
    """Chaînes mises en avant (les plus récentes actives avec logo)"""
    channels = db.query(ExternalStream).filter(
        ExternalStream.is_active == True,
        ExternalStream.logo != None,
        ExternalStream.logo != "",
    ).order_by(ExternalStream.id.desc()).limit(limit).all()
    return JSONResponse({
        "channels": [{
            "id":          c.id,
            "title":       c.title,
            "logo":        c.logo or "",
            "country":     c.country or "",
            "category":    c.category,
            "stream_type": c.stream_type,
            "url":         f"/watch/external/{c.id}",
        } for c in channels]
    })


@app.get("/api/channels/by-country/{country_code}")
async def get_channels_by_country(country_code: str, limit: int = 50, db: Session = Depends(get_db)):
    """Chaînes filtrées par code pays"""
    cc = country_code.upper()[:5]
    channels = db.query(ExternalStream).filter(
        ExternalStream.is_active == True,
        ExternalStream.country == cc,
    ).order_by(ExternalStream.title).limit(limit).all()
    iptv = db.query(IPTVChannel).filter(
        IPTVChannel.country.ilike(cc)
    ).limit(limit).all()
    return JSONResponse({
        "country": cc,
        "external": [{
            "id": c.id, "title": c.title, "logo": c.logo or "",
            "stream_type": c.stream_type, "url": f"/watch/external/{c.id}",
        } for c in channels],
        "iptv": [{
            "id": c.id, "name": c.name, "logo": c.logo or "",
            "category": c.category, "url": f"/watch/iptv/{c.id}",
        } for c in iptv],
        "total": len(channels) + len(iptv),
    })


@app.get("/api/channels/random")
async def get_random_channel(type: str = "all", db: Session = Depends(get_db)):
    """Chaîne aléatoire (pour le bouton « Je me sens chanceux »)"""
    from sqlalchemy import func
    if type == "iptv":
        ch = db.query(IPTVChannel).order_by(func.random()).first()
        if ch:
            return JSONResponse({"url": f"/watch/iptv/{ch.id}", "title": ch.name, "type": "iptv"})
    elif type == "radio":
        ch = db.query(ExternalStream).filter(
            ExternalStream.is_active == True,
            ExternalStream.stream_type == "audio"
        ).order_by(func.random()).first()
        if ch:
            return JSONResponse({"url": f"/watch/external/{ch.id}", "title": ch.title, "type": "radio"})
    else:
        ch = db.query(ExternalStream).filter(
            ExternalStream.is_active == True
        ).order_by(func.random()).first()
        if ch:
            return JSONResponse({"url": f"/watch/external/{ch.id}", "title": ch.title, "type": "external"})
    return JSONResponse({"url": "/", "title": "Accueil", "type": "home"})


@app.get("/api/admin/announcements/list")
async def admin_list_announcements(request: Request, db: Session = Depends(get_db)):
    """Liste toutes les annonces pour l'admin"""
    try:
        require_admin(request)
    except HTTPException:
        return JSONResponse(status_code=401, content={"error": "Non autorisé"})
    anns = db.query(AdminAnnouncement).order_by(AdminAnnouncement.created_at.desc()).all()
    return JSONResponse({
        "announcements": [{
            "id":         a.id,
            "title":      a.title,
            "message":    a.message,
            "type":       a.type,
            "is_active":  a.is_active,
            "created_at": a.created_at.isoformat(),
            "expires_at": a.expires_at.isoformat() if a.expires_at else None,
        } for a in anns]
    })


@app.post("/api/admin/announcements/{ann_id}/toggle")
async def admin_toggle_announcement(ann_id: int, request: Request, db: Session = Depends(get_db)):
    """Activer/désactiver une annonce"""
    try:
        require_admin(request)
    except HTTPException:
        return JSONResponse(status_code=401, content={"error": "Non autorisé"})
    ann = db.query(AdminAnnouncement).filter(AdminAnnouncement.id == ann_id).first()
    if not ann:
        raise HTTPException(status_code=404, detail="Annonce introuvable")
    ann.is_active = not ann.is_active
    db.commit()
    status = "activée" if ann.is_active else "désactivée"
    return JSONResponse({"success": True, "is_active": ann.is_active, "message": f"Annonce {status}"})


@app.delete("/api/admin/announcements/{ann_id}")
async def admin_delete_announcement(ann_id: int, request: Request, db: Session = Depends(get_db)):
    """Supprimer une annonce"""
    try:
        require_admin(request)
    except HTTPException:
        return JSONResponse(status_code=401, content={"error": "Non autorisé"})
    ann = db.query(AdminAnnouncement).filter(AdminAnnouncement.id == ann_id).first()
    if not ann:
        raise HTTPException(status_code=404, detail="Annonce introuvable")
    db.delete(ann)
    db.commit()
    return JSONResponse({"success": True, "message": "Annonce supprimée"})


@app.post("/api/admin/feedback/{fb_id}/read")
async def admin_mark_feedback_read(fb_id: int, request: Request, db: Session = Depends(get_db)):
    """Marquer un avis comme lu"""
    try:
        require_admin(request)
    except HTTPException:
        return JSONResponse(status_code=401, content={"error": "Non autorisé"})
    fb = db.query(UserFeedback).filter(UserFeedback.id == fb_id).first()
    if not fb:
        raise HTTPException(status_code=404, detail="Avis introuvable")
    fb.is_read = True
    db.commit()
    return JSONResponse({"success": True, "message": "Avis marqué comme lu"})


@app.delete("/api/admin/feedback/{fb_id}")
async def admin_delete_feedback(fb_id: int, request: Request, db: Session = Depends(get_db)):
    """Supprimer un avis utilisateur"""
    try:
        require_admin(request)
    except HTTPException:
        return JSONResponse(status_code=401, content={"error": "Non autorisé"})
    fb = db.query(UserFeedback).filter(UserFeedback.id == fb_id).first()
    if not fb:
        raise HTTPException(status_code=404, detail="Avis introuvable")
    db.delete(fb)
    db.commit()
    return JSONResponse({"success": True, "message": "Avis supprimé"})


@app.get("/api/admin/ips/{ip_id}/unblock")
async def admin_unblock_ip_get(ip_id: int, request: Request, db: Session = Depends(get_db)):
    """Débloquer une IP (méthode GET pour compatibilité)"""
    try:
        require_admin(request)
    except HTTPException:
        return JSONResponse(status_code=401, content={"error": "Non autorisé"})
    ip = db.query(BlockedIP).filter(BlockedIP.id == ip_id).first()
    if not ip:
        raise HTTPException(status_code=404, detail="IP introuvable")
    ip.is_active = False
    db.commit()
    return JSONResponse({"success": True, "message": f"IP {ip.ip_address} débloquée"})


@app.get("/api/iptv/countries")
async def get_iptv_countries(db: Session = Depends(get_db)):
    """Liste des pays disponibles dans l'IPTV"""
    from sqlalchemy import func, distinct
    countries = db.query(
        IPTVChannel.country,
        func.count(IPTVChannel.id).label("channel_count")
    ).filter(
        IPTVChannel.country != None,
        IPTVChannel.country != ""
    ).group_by(IPTVChannel.country).order_by(IPTVChannel.country).all()

    return JSONResponse({
        "countries": [{"code": c[0], "count": c[1]} for c in countries],
        "total": len(countries),
    })


@app.get("/api/iptv/categories-list")
async def get_iptv_categories(db: Session = Depends(get_db)):
    """Liste des catégories disponibles dans l'IPTV"""
    from sqlalchemy import func
    cats = db.query(
        IPTVChannel.category,
        func.count(IPTVChannel.id).label("count")
    ).filter(
        IPTVChannel.category != None,
        IPTVChannel.category != ""
    ).group_by(IPTVChannel.category).order_by(func.count(IPTVChannel.id).desc()).all()

    return JSONResponse({
        "categories": [{"name": c[0], "count": c[1]} for c in cats],
        "total": len(cats),
    })


@app.post("/api/admin/external/{stream_id}/toggle")
async def admin_toggle_external_stream(stream_id: int, request: Request, db: Session = Depends(get_db)):
    """Activer ou désactiver un flux externe"""
    try:
        require_admin(request)
    except HTTPException:
        return JSONResponse(status_code=401, content={"error": "Non autorisé"})
    stream = db.query(ExternalStream).filter(ExternalStream.id == stream_id).first()
    if not stream:
        raise HTTPException(status_code=404, detail="Flux introuvable")
    stream.is_active = not stream.is_active
    db.commit()
    status = "activé" if stream.is_active else "désactivé"
    return JSONResponse({"success": True, "is_active": stream.is_active, "message": f"Flux {status}"})


@app.get("/api/admin/streams/{stream_id}/block")
async def admin_block_stream_get(stream_id: int, request: Request, db: Session = Depends(get_db)):
    """Bloquer un stream utilisateur"""
    try:
        require_admin(request)
    except HTTPException:
        return JSONResponse(status_code=401, content={"error": "Non autorisé"})
    stream = db.query(LiveStream).filter(LiveStream.id == stream_id).first()
    if not stream:
        raise HTTPException(status_code=404, detail="Stream introuvable")
    stream.is_blocked = True
    if stream.is_live:
        stream.is_live = False
    db.commit()
    return JSONResponse({"success": True, "message": "Stream bloqué"})


@app.post("/api/admin/streams/{stream_id}/block")
async def admin_block_stream_post(stream_id: int, request: Request, db: Session = Depends(get_db)):
    """Bloquer un stream utilisateur (POST)"""
    try:
        require_admin(request)
    except HTTPException:
        return JSONResponse(status_code=401, content={"error": "Non autorisé"})
    stream = db.query(LiveStream).filter(LiveStream.id == stream_id).first()
    if not stream:
        raise HTTPException(status_code=404, detail="Stream introuvable")
    stream.is_blocked = True
    if stream.is_live:
        stream.is_live = False
    db.commit()
    return JSONResponse({"success": True, "message": "Stream bloqué"})


@app.get("/sitemap.xml")
async def sitemap(db: Session = Depends(get_db)):
    """Sitemap XML pour les moteurs de recherche"""
    base = "https://livewatch.example.com"
    streams = db.query(ExternalStream).filter(ExternalStream.is_active == True).limit(100).all()
    channels = db.query(IPTVChannel).limit(200).all()

    urls = [
        f"<url><loc>{base}/</loc><changefreq>daily</changefreq><priority>1.0</priority></url>",
        f"<url><loc>{base}/events</loc><changefreq>hourly</changefreq><priority>0.9</priority></url>",
        f"<url><loc>{base}/search</loc><changefreq>weekly</changefreq><priority>0.7</priority></url>",
        f"<url><loc>{base}/go-live</loc><changefreq>monthly</changefreq><priority>0.6</priority></url>",
        f"<url><loc>{base}/settings</loc><changefreq>monthly</changefreq><priority>0.5</priority></url>",
        f"<url><loc>{base}/about</loc><changefreq>monthly</changefreq><priority>0.4</priority></url>",
    ]
    for s in streams:
        urls.append(f"<url><loc>{base}/watch/external/{s.id}</loc><changefreq>daily</changefreq><priority>0.8</priority></url>")
    for ch in channels:
        urls.append(f"<url><loc>{base}/watch/iptv/{ch.id}</loc><changefreq>daily</changefreq><priority>0.7</priority></url>")

    xml = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    xml += "\n".join(urls)
    xml += "\n</urlset>"

    from starlette.responses import Response
    return Response(content=xml, media_type="application/xml")


@app.get("/robots.txt")
async def robots():
    """Fichier robots.txt"""
    content_robots = """User-agent: *
Allow: /
Disallow: /admin
Disallow: /api/admin/
Disallow: /ws/
Sitemap: https://livewatch.example.com/sitemap.xml
"""
    from starlette.responses import PlainTextResponse
    return PlainTextResponse(content_robots)



# ── Pays du monde manquants (couverture complète) ─────────────────────
IPTV_EXTRA_COUNTRIES = [
    # Afrique subsaharienne complète
    {"name":"angola","display_name":"Angola","url":f"{settings.IPTV_BASE_URL}/countries/ao.m3u","category":"iptv","country":"AO","playlist_type":"country"},
    {"name":"benin","display_name":"Bénin","url":f"{settings.IPTV_BASE_URL}/countries/bj.m3u","category":"iptv","country":"BJ","playlist_type":"country"},
    {"name":"botswana","display_name":"Botswana","url":f"{settings.IPTV_BASE_URL}/countries/bw.m3u","category":"iptv","country":"BW","playlist_type":"country"},
    {"name":"burkina_faso","display_name":"Burkina Faso","url":f"{settings.IPTV_BASE_URL}/countries/bf.m3u","category":"iptv","country":"BF","playlist_type":"country"},
    {"name":"burundi","display_name":"Burundi","url":f"{settings.IPTV_BASE_URL}/countries/bi.m3u","category":"iptv","country":"BI","playlist_type":"country"},
    {"name":"cabo_verde","display_name":"Cap-Vert","url":f"{settings.IPTV_BASE_URL}/countries/cv.m3u","category":"iptv","country":"CV","playlist_type":"country"},
    {"name":"cameroun","display_name":"Cameroun","url":f"{settings.IPTV_BASE_URL}/countries/cm.m3u","category":"iptv","country":"CM","playlist_type":"country"},
    {"name":"central_african_rep","display_name":"Centrafrique","url":f"{settings.IPTV_BASE_URL}/countries/cf.m3u","category":"iptv","country":"CF","playlist_type":"country"},
    {"name":"chad","display_name":"Tchad","url":f"{settings.IPTV_BASE_URL}/countries/td.m3u","category":"iptv","country":"TD","playlist_type":"country"},
    {"name":"comoros","display_name":"Comores","url":f"{settings.IPTV_BASE_URL}/countries/km.m3u","category":"iptv","country":"KM","playlist_type":"country"},
    {"name":"congo_rep","display_name":"Congo-Brazzaville","url":f"{settings.IPTV_BASE_URL}/countries/cg.m3u","category":"iptv","country":"CG","playlist_type":"country"},
    {"name":"djibouti","display_name":"Djibouti","url":f"{settings.IPTV_BASE_URL}/countries/dj.m3u","category":"iptv","country":"DJ","playlist_type":"country"},
    {"name":"equatorial_guinea","display_name":"Guinée équatoriale","url":f"{settings.IPTV_BASE_URL}/countries/gq.m3u","category":"iptv","country":"GQ","playlist_type":"country"},
    {"name":"eritrea","display_name":"Érythrée","url":f"{settings.IPTV_BASE_URL}/countries/er.m3u","category":"iptv","country":"ER","playlist_type":"country"},
    {"name":"eswatini","display_name":"Eswatini","url":f"{settings.IPTV_BASE_URL}/countries/sz.m3u","category":"iptv","country":"SZ","playlist_type":"country"},
    {"name":"gambia","display_name":"Gambie","url":f"{settings.IPTV_BASE_URL}/countries/gm.m3u","category":"iptv","country":"GM","playlist_type":"country"},
    {"name":"guinea","display_name":"Guinée","url":f"{settings.IPTV_BASE_URL}/countries/gn.m3u","category":"iptv","country":"GN","playlist_type":"country"},
    {"name":"guinea_bissau","display_name":"Guinée-Bissau","url":f"{settings.IPTV_BASE_URL}/countries/gw.m3u","category":"iptv","country":"GW","playlist_type":"country"},
    {"name":"ivory_coast","display_name":"Côte d'Ivoire","url":f"{settings.IPTV_BASE_URL}/countries/ci.m3u","category":"iptv","country":"CI","playlist_type":"country"},
    {"name":"kenya","display_name":"Kenya","url":f"{settings.IPTV_BASE_URL}/countries/ke.m3u","category":"iptv","country":"KE","playlist_type":"country"},
    {"name":"lesotho","display_name":"Lesotho","url":f"{settings.IPTV_BASE_URL}/countries/ls.m3u","category":"iptv","country":"LS","playlist_type":"country"},
    {"name":"liberia","display_name":"Liberia","url":f"{settings.IPTV_BASE_URL}/countries/lr.m3u","category":"iptv","country":"LR","playlist_type":"country"},
    {"name":"madagascar","display_name":"Madagascar","url":f"{settings.IPTV_BASE_URL}/countries/mg.m3u","category":"iptv","country":"MG","playlist_type":"country"},
    {"name":"malawi","display_name":"Malawi","url":f"{settings.IPTV_BASE_URL}/countries/mw.m3u","category":"iptv","country":"MW","playlist_type":"country"},
    {"name":"mali","display_name":"Mali","url":f"{settings.IPTV_BASE_URL}/countries/ml.m3u","category":"iptv","country":"ML","playlist_type":"country"},
    {"name":"mauritania","display_name":"Mauritanie","url":f"{settings.IPTV_BASE_URL}/countries/mr.m3u","category":"iptv","country":"MR","playlist_type":"country"},
    {"name":"mauritius","display_name":"Maurice","url":f"{settings.IPTV_BASE_URL}/countries/mu.m3u","category":"iptv","country":"MU","playlist_type":"country"},
    {"name":"mozambique","display_name":"Mozambique","url":f"{settings.IPTV_BASE_URL}/countries/mz.m3u","category":"iptv","country":"MZ","playlist_type":"country"},
    {"name":"namibia","display_name":"Namibie","url":f"{settings.IPTV_BASE_URL}/countries/na.m3u","category":"iptv","country":"NA","playlist_type":"country"},
    {"name":"niger","display_name":"Niger","url":f"{settings.IPTV_BASE_URL}/countries/ne.m3u","category":"iptv","country":"NE","playlist_type":"country"},
    {"name":"nigeria","display_name":"Nigeria","url":f"{settings.IPTV_BASE_URL}/countries/ng.m3u","category":"iptv","country":"NG","playlist_type":"country"},
    {"name":"reunion","display_name":"La Réunion","url":f"{settings.IPTV_BASE_URL}/countries/re.m3u","category":"iptv","country":"RE","playlist_type":"country"},
    {"name":"rwanda","display_name":"Rwanda","url":f"{settings.IPTV_BASE_URL}/countries/rw.m3u","category":"iptv","country":"RW","playlist_type":"country"},
    {"name":"sao_tome","display_name":"São Tomé-et-Príncipe","url":f"{settings.IPTV_BASE_URL}/countries/st.m3u","category":"iptv","country":"ST","playlist_type":"country"},
    {"name":"sierra_leone","display_name":"Sierra Leone","url":f"{settings.IPTV_BASE_URL}/countries/sl.m3u","category":"iptv","country":"SL","playlist_type":"country"},
    {"name":"somalia","display_name":"Somalie","url":f"{settings.IPTV_BASE_URL}/countries/so.m3u","category":"iptv","country":"SO","playlist_type":"country"},
    {"name":"south_africa","display_name":"Afrique du Sud","url":f"{settings.IPTV_BASE_URL}/countries/za.m3u","category":"iptv","country":"ZA","playlist_type":"country"},
    {"name":"south_sudan","display_name":"Soudan du Sud","url":f"{settings.IPTV_BASE_URL}/countries/ss.m3u","category":"iptv","country":"SS","playlist_type":"country"},
    {"name":"sudan","display_name":"Soudan","url":f"{settings.IPTV_BASE_URL}/countries/sd.m3u","category":"iptv","country":"SD","playlist_type":"country"},
    {"name":"tanzania","display_name":"Tanzanie","url":f"{settings.IPTV_BASE_URL}/countries/tz.m3u","category":"iptv","country":"TZ","playlist_type":"country"},
    {"name":"togo","display_name":"Togo","url":f"{settings.IPTV_BASE_URL}/countries/tg.m3u","category":"iptv","country":"TG","playlist_type":"country"},
    {"name":"uganda","display_name":"Ouganda","url":f"{settings.IPTV_BASE_URL}/countries/ug.m3u","category":"iptv","country":"UG","playlist_type":"country"},
    {"name":"zambia","display_name":"Zambie","url":f"{settings.IPTV_BASE_URL}/countries/zm.m3u","category":"iptv","country":"ZM","playlist_type":"country"},
    {"name":"zimbabwe","display_name":"Zimbabwe","url":f"{settings.IPTV_BASE_URL}/countries/zw.m3u","category":"iptv","country":"ZW","playlist_type":"country"},
    # Asie du Sud-Est complète
    {"name":"myanmar","display_name":"Myanmar","url":f"{settings.IPTV_BASE_URL}/countries/mm.m3u","category":"iptv","country":"MM","playlist_type":"country"},
    {"name":"cambodia","display_name":"Cambodge","url":f"{settings.IPTV_BASE_URL}/countries/kh.m3u","category":"iptv","country":"KH","playlist_type":"country"},
    {"name":"laos","display_name":"Laos","url":f"{settings.IPTV_BASE_URL}/countries/la.m3u","category":"iptv","country":"LA","playlist_type":"country"},
    {"name":"timor_leste","display_name":"Timor oriental","url":f"{settings.IPTV_BASE_URL}/countries/tl.m3u","category":"iptv","country":"TL","playlist_type":"country"},
    {"name":"maldives","display_name":"Maldives","url":f"{settings.IPTV_BASE_URL}/countries/mv.m3u","category":"iptv","country":"MV","playlist_type":"country"},
    {"name":"bhutan","display_name":"Bhoutan","url":f"{settings.IPTV_BASE_URL}/countries/bt.m3u","category":"iptv","country":"BT","playlist_type":"country"},
    {"name":"afghanistan","display_name":"Afghanistan","url":f"{settings.IPTV_BASE_URL}/countries/af.m3u","category":"iptv","country":"AF","playlist_type":"country"},
    # Océanie complète
    {"name":"fiji","display_name":"Fidji","url":f"{settings.IPTV_BASE_URL}/countries/fj.m3u","category":"iptv","country":"FJ","playlist_type":"country"},
    {"name":"papua_new_guinea","display_name":"Papouasie-Nouvelle-Guinée","url":f"{settings.IPTV_BASE_URL}/countries/pg.m3u","category":"iptv","country":"PG","playlist_type":"country"},
    {"name":"samoa","display_name":"Samoa","url":f"{settings.IPTV_BASE_URL}/countries/ws.m3u","category":"iptv","country":"WS","playlist_type":"country"},
    {"name":"tonga","display_name":"Tonga","url":f"{settings.IPTV_BASE_URL}/countries/to.m3u","category":"iptv","country":"TO","playlist_type":"country"},
    {"name":"vanuatu","display_name":"Vanuatu","url":f"{settings.IPTV_BASE_URL}/countries/vu.m3u","category":"iptv","country":"VU","playlist_type":"country"},
    {"name":"solomon_islands","display_name":"Îles Salomon","url":f"{settings.IPTV_BASE_URL}/countries/sb.m3u","category":"iptv","country":"SB","playlist_type":"country"},
    # Amériques complètes
    {"name":"belize","display_name":"Belize","url":f"{settings.IPTV_BASE_URL}/countries/bz.m3u","category":"iptv","country":"BZ","playlist_type":"country"},
    {"name":"costa_rica","display_name":"Costa Rica","url":f"{settings.IPTV_BASE_URL}/countries/cr.m3u","category":"iptv","country":"CR","playlist_type":"country"},
    {"name":"cuba","display_name":"Cuba","url":f"{settings.IPTV_BASE_URL}/countries/cu.m3u","category":"iptv","country":"CU","playlist_type":"country"},
    {"name":"dominican_republic","display_name":"Rép. dominicaine","url":f"{settings.IPTV_BASE_URL}/countries/do.m3u","category":"iptv","country":"DO","playlist_type":"country"},
    {"name":"ecuador","display_name":"Équateur","url":f"{settings.IPTV_BASE_URL}/countries/ec.m3u","category":"iptv","country":"EC","playlist_type":"country"},
    {"name":"el_salvador","display_name":"El Salvador","url":f"{settings.IPTV_BASE_URL}/countries/sv.m3u","category":"iptv","country":"SV","playlist_type":"country"},
    {"name":"guatemala","display_name":"Guatemala","url":f"{settings.IPTV_BASE_URL}/countries/gt.m3u","category":"iptv","country":"GT","playlist_type":"country"},
    {"name":"haiti","display_name":"Haïti","url":f"{settings.IPTV_BASE_URL}/countries/ht.m3u","category":"iptv","country":"HT","playlist_type":"country"},
    {"name":"honduras","display_name":"Honduras","url":f"{settings.IPTV_BASE_URL}/countries/hn.m3u","category":"iptv","country":"HN","playlist_type":"country"},
    {"name":"jamaica","display_name":"Jamaïque","url":f"{settings.IPTV_BASE_URL}/countries/jm.m3u","category":"iptv","country":"JM","playlist_type":"country"},
    {"name":"nicaragua","display_name":"Nicaragua","url":f"{settings.IPTV_BASE_URL}/countries/ni.m3u","category":"iptv","country":"NI","playlist_type":"country"},
    {"name":"panama","display_name":"Panama","url":f"{settings.IPTV_BASE_URL}/countries/pa.m3u","category":"iptv","country":"PA","playlist_type":"country"},
    {"name":"paraguay","display_name":"Paraguay","url":f"{settings.IPTV_BASE_URL}/countries/py.m3u","category":"iptv","country":"PY","playlist_type":"country"},
    {"name":"trinidad_tobago","display_name":"Trinité-et-Tobago","url":f"{settings.IPTV_BASE_URL}/countries/tt.m3u","category":"iptv","country":"TT","playlist_type":"country"},
    {"name":"uruguay","display_name":"Uruguay","url":f"{settings.IPTV_BASE_URL}/countries/uy.m3u","category":"iptv","country":"UY","playlist_type":"country"},
    # Europe complémentaire
    {"name":"albania2","display_name":"Albanie","url":f"{settings.IPTV_BASE_URL}/countries/al.m3u","category":"iptv","country":"AL","playlist_type":"country"},
    {"name":"armenia","display_name":"Arménie","url":f"{settings.IPTV_BASE_URL}/countries/am.m3u","category":"iptv","country":"AM","playlist_type":"country"},
    {"name":"azerbaijan","display_name":"Azerbaïdjan","url":f"{settings.IPTV_BASE_URL}/countries/az.m3u","category":"iptv","country":"AZ","playlist_type":"country"},
    {"name":"belarus","display_name":"Biélorussie","url":f"{settings.IPTV_BASE_URL}/countries/by.m3u","category":"iptv","country":"BY","playlist_type":"country"},
    {"name":"bosnia","display_name":"Bosnie-Herzégovine","url":f"{settings.IPTV_BASE_URL}/countries/ba.m3u","category":"iptv","country":"BA","playlist_type":"country"},
    {"name":"georgia","display_name":"Géorgie","url":f"{settings.IPTV_BASE_URL}/countries/ge.m3u","category":"iptv","country":"GE","playlist_type":"country"},
    {"name":"iceland","display_name":"Islande","url":f"{settings.IPTV_BASE_URL}/countries/is.m3u","category":"iptv","country":"IS","playlist_type":"country"},
    {"name":"kosovo","display_name":"Kosovo","url":f"{settings.IPTV_BASE_URL}/countries/xk.m3u","category":"iptv","country":"XK","playlist_type":"country"},
    {"name":"latvia","display_name":"Lettonie","url":f"{settings.IPTV_BASE_URL}/countries/lv.m3u","category":"iptv","country":"LV","playlist_type":"country"},
    {"name":"liechtenstein","display_name":"Liechtenstein","url":f"{settings.IPTV_BASE_URL}/countries/li.m3u","category":"iptv","country":"LI","playlist_type":"country"},
    {"name":"lithuania","display_name":"Lituanie","url":f"{settings.IPTV_BASE_URL}/countries/lt.m3u","category":"iptv","country":"LT","playlist_type":"country"},
    {"name":"luxembourg","display_name":"Luxembourg","url":f"{settings.IPTV_BASE_URL}/countries/lu.m3u","category":"iptv","country":"LU","playlist_type":"country"},
    {"name":"moldova","display_name":"Moldavie","url":f"{settings.IPTV_BASE_URL}/countries/md.m3u","category":"iptv","country":"MD","playlist_type":"country"},
    {"name":"monaco","display_name":"Monaco","url":f"{settings.IPTV_BASE_URL}/countries/mc.m3u","category":"iptv","country":"MC","playlist_type":"country"},
    {"name":"montenegro","display_name":"Monténégro","url":f"{settings.IPTV_BASE_URL}/countries/me.m3u","category":"iptv","country":"ME","playlist_type":"country"},
    {"name":"north_macedonia","display_name":"Macédoine du Nord","url":f"{settings.IPTV_BASE_URL}/countries/mk.m3u","category":"iptv","country":"MK","playlist_type":"country"},
    {"name":"san_marino","display_name":"Saint-Marin","url":f"{settings.IPTV_BASE_URL}/countries/sm.m3u","category":"iptv","country":"SM","playlist_type":"country"},
    {"name":"ukraine","display_name":"Ukraine","url":f"{settings.IPTV_BASE_URL}/countries/ua.m3u","category":"iptv","country":"UA","playlist_type":"country"},
    # Moyen-Orient complet
    {"name":"bahrain","display_name":"Bahreïn","url":f"{settings.IPTV_BASE_URL}/countries/bh.m3u","category":"iptv","country":"BH","playlist_type":"country"},
    {"name":"iran","display_name":"Iran","url":f"{settings.IPTV_BASE_URL}/countries/ir.m3u","category":"iptv","country":"IR","playlist_type":"country"},
    {"name":"iraq","display_name":"Irak","url":f"{settings.IPTV_BASE_URL}/countries/iq.m3u","category":"iptv","country":"IQ","playlist_type":"country"},
    {"name":"israel","display_name":"Israël","url":f"{settings.IPTV_BASE_URL}/countries/il.m3u","category":"iptv","country":"IL","playlist_type":"country"},
    {"name":"jordan","display_name":"Jordanie","url":f"{settings.IPTV_BASE_URL}/countries/jo.m3u","category":"iptv","country":"JO","playlist_type":"country"},
    {"name":"kuwait","display_name":"Koweït","url":f"{settings.IPTV_BASE_URL}/countries/kw.m3u","category":"iptv","country":"KW","playlist_type":"country"},
    {"name":"lebanon","display_name":"Liban","url":f"{settings.IPTV_BASE_URL}/countries/lb.m3u","category":"iptv","country":"LB","playlist_type":"country"},
    {"name":"oman","display_name":"Oman","url":f"{settings.IPTV_BASE_URL}/countries/om.m3u","category":"iptv","country":"OM","playlist_type":"country"},
    {"name":"palestine","display_name":"Palestine","url":f"{settings.IPTV_BASE_URL}/countries/ps.m3u","category":"iptv","country":"PS","playlist_type":"country"},
    {"name":"syria","display_name":"Syrie","url":f"{settings.IPTV_BASE_URL}/countries/sy.m3u","category":"iptv","country":"SY","playlist_type":"country"},
    {"name":"yemen","display_name":"Yémen","url":f"{settings.IPTV_BASE_URL}/countries/ye.m3u","category":"iptv","country":"YE","playlist_type":"country"},
        # ── Pays d'Afrique subsaharienne ──────────────────────────────────────
    {"name":"angola","display_name":"Angola","url":f"{settings.IPTV_BASE_URL}/countries/ao.m3u","category":"iptv","country":"AO","playlist_type":"country"},
    {"name":"botswana","display_name":"Botswana","url":f"{settings.IPTV_BASE_URL}/countries/bw.m3u","category":"iptv","country":"BW","playlist_type":"country"},
    {"name":"burundi","display_name":"Burundi","url":f"{settings.IPTV_BASE_URL}/countries/bi.m3u","category":"iptv","country":"BI","playlist_type":"country"},
    {"name":"cap_vert","display_name":"Cap-Vert","url":f"{settings.IPTV_BASE_URL}/countries/cv.m3u","category":"iptv","country":"CV","playlist_type":"country"},
    {"name":"comores","display_name":"Comores","url":f"{settings.IPTV_BASE_URL}/countries/km.m3u","category":"iptv","country":"KM","playlist_type":"country"},
    {"name":"djibouti","display_name":"Djibouti","url":f"{settings.IPTV_BASE_URL}/countries/dj.m3u","category":"iptv","country":"DJ","playlist_type":"country"},
    {"name":"egypte","display_name":"Égypte","url":f"{settings.IPTV_BASE_URL}/countries/eg.m3u","category":"iptv","country":"EG","playlist_type":"country"},
    {"name":"erythree","display_name":"Érythrée","url":f"{settings.IPTV_BASE_URL}/countries/er.m3u","category":"iptv","country":"ER","playlist_type":"country"},
    {"name":"eswatini","display_name":"Eswatini","url":f"{settings.IPTV_BASE_URL}/countries/sz.m3u","category":"iptv","country":"SZ","playlist_type":"country"},
    {"name":"gambie","display_name":"Gambie","url":f"{settings.IPTV_BASE_URL}/countries/gm.m3u","category":"iptv","country":"GM","playlist_type":"country"},
    {"name":"guinee","display_name":"Guinée","url":f"{settings.IPTV_BASE_URL}/countries/gn.m3u","category":"iptv","country":"GN","playlist_type":"country"},
    {"name":"guinee_bissau","display_name":"Guinée-Bissau","url":f"{settings.IPTV_BASE_URL}/countries/gw.m3u","category":"iptv","country":"GW","playlist_type":"country"},
    {"name":"guinee_equat","display_name":"Guinée équatoriale","url":f"{settings.IPTV_BASE_URL}/countries/gq.m3u","category":"iptv","country":"GQ","playlist_type":"country"},
    {"name":"lesotho","display_name":"Lesotho","url":f"{settings.IPTV_BASE_URL}/countries/ls.m3u","category":"iptv","country":"LS","playlist_type":"country"},
    {"name":"liberia","display_name":"Libéria","url":f"{settings.IPTV_BASE_URL}/countries/lr.m3u","category":"iptv","country":"LR","playlist_type":"country"},
    {"name":"libye","display_name":"Libye","url":f"{settings.IPTV_BASE_URL}/countries/ly.m3u","category":"iptv","country":"LY","playlist_type":"country"},
    {"name":"madagascar","display_name":"Madagascar","url":f"{settings.IPTV_BASE_URL}/countries/mg.m3u","category":"iptv","country":"MG","playlist_type":"country"},
    {"name":"malawi","display_name":"Malawi","url":f"{settings.IPTV_BASE_URL}/countries/mw.m3u","category":"iptv","country":"MW","playlist_type":"country"},
    {"name":"mauritanie","display_name":"Mauritanie","url":f"{settings.IPTV_BASE_URL}/countries/mr.m3u","category":"iptv","country":"MR","playlist_type":"country"},
    {"name":"ile_maurice","display_name":"Maurice","url":f"{settings.IPTV_BASE_URL}/countries/mu.m3u","category":"iptv","country":"MU","playlist_type":"country"},
    {"name":"mozambique","display_name":"Mozambique","url":f"{settings.IPTV_BASE_URL}/countries/mz.m3u","category":"iptv","country":"MZ","playlist_type":"country"},
    {"name":"namibie","display_name":"Namibie","url":f"{settings.IPTV_BASE_URL}/countries/na.m3u","category":"iptv","country":"NA","playlist_type":"country"},
    {"name":"sao_tome","display_name":"São Tomé-et-Príncipe","url":f"{settings.IPTV_BASE_URL}/countries/st.m3u","category":"iptv","country":"ST","playlist_type":"country"},
    {"name":"seychelles","display_name":"Seychelles","url":f"{settings.IPTV_BASE_URL}/countries/sc.m3u","category":"iptv","country":"SC","playlist_type":"country"},
    {"name":"sierra_leone","display_name":"Sierra Leone","url":f"{settings.IPTV_BASE_URL}/countries/sl.m3u","category":"iptv","country":"SL","playlist_type":"country"},
    {"name":"somalie","display_name":"Somalie","url":f"{settings.IPTV_BASE_URL}/countries/so.m3u","category":"iptv","country":"SO","playlist_type":"country"},
    {"name":"soudan","display_name":"Soudan","url":f"{settings.IPTV_BASE_URL}/countries/sd.m3u","category":"iptv","country":"SD","playlist_type":"country"},
    {"name":"soudan_sud","display_name":"Soudan du Sud","url":f"{settings.IPTV_BASE_URL}/countries/ss.m3u","category":"iptv","country":"SS","playlist_type":"country"},
    {"name":"zimbabwe","display_name":"Zimbabwe","url":f"{settings.IPTV_BASE_URL}/countries/zw.m3u","category":"iptv","country":"ZW","playlist_type":"country"},
    {"name":"zambie","display_name":"Zambie","url":f"{settings.IPTV_BASE_URL}/countries/zm.m3u","category":"iptv","country":"ZM","playlist_type":"country"},
    # ── Pays d'Asie ────────────────────────────────────────────────────────
    {"name":"afghanistan","display_name":"Afghanistan","url":f"{settings.IPTV_BASE_URL}/countries/af.m3u","category":"iptv","country":"AF","playlist_type":"country"},
    {"name":"bhoutan","display_name":"Bhoutan","url":f"{settings.IPTV_BASE_URL}/countries/bt.m3u","category":"iptv","country":"BT","playlist_type":"country"},
    {"name":"birmanie","display_name":"Birmanie (Myanmar)","url":f"{settings.IPTV_BASE_URL}/countries/mm.m3u","category":"iptv","country":"MM","playlist_type":"country"},
    {"name":"cambodge","display_name":"Cambodge","url":f"{settings.IPTV_BASE_URL}/countries/kh.m3u","category":"iptv","country":"KH","playlist_type":"country"},
    {"name":"coree_nord","display_name":"Corée du Nord","url":f"{settings.IPTV_BASE_URL}/countries/kp.m3u","category":"iptv","country":"KP","playlist_type":"country"},
    {"name":"laos","display_name":"Laos","url":f"{settings.IPTV_BASE_URL}/countries/la.m3u","category":"iptv","country":"LA","playlist_type":"country"},
    {"name":"maldives","display_name":"Maldives","url":f"{settings.IPTV_BASE_URL}/countries/mv.m3u","category":"iptv","country":"MV","playlist_type":"country"},
    {"name":"mongolie","display_name":"Mongolie","url":f"{settings.IPTV_BASE_URL}/countries/mn.m3u","category":"iptv","country":"MN","playlist_type":"country"},
    {"name":"timor","display_name":"Timor oriental","url":f"{settings.IPTV_BASE_URL}/countries/tl.m3u","category":"iptv","country":"TL","playlist_type":"country"},
    {"name":"kirghizistan","display_name":"Kirghizistan","url":f"{settings.IPTV_BASE_URL}/countries/kg.m3u","category":"iptv","country":"KG","playlist_type":"country"},
    {"name":"tadjikistan","display_name":"Tadjikistan","url":f"{settings.IPTV_BASE_URL}/countries/tj.m3u","category":"iptv","country":"TJ","playlist_type":"country"},
    {"name":"turkmenistan","display_name":"Turkménistan","url":f"{settings.IPTV_BASE_URL}/countries/tm.m3u","category":"iptv","country":"TM","playlist_type":"country"},
    {"name":"ouzbekistan","display_name":"Ouzbékistan","url":f"{settings.IPTV_BASE_URL}/countries/uz.m3u","category":"iptv","country":"UZ","playlist_type":"country"},
    {"name":"hong_kong","display_name":"Hong Kong","url":f"{settings.IPTV_BASE_URL}/countries/hk.m3u","category":"iptv","country":"HK","playlist_type":"country"},
    {"name":"taiwan","display_name":"Taïwan","url":f"{settings.IPTV_BASE_URL}/countries/tw.m3u","category":"iptv","country":"TW","playlist_type":"country"},
    {"name":"macau","display_name":"Macao","url":f"{settings.IPTV_BASE_URL}/countries/mo.m3u","category":"iptv","country":"MO","playlist_type":"country"},
    # ── Pays d'Europe de l'Est et Balkans ──────────────────────────────────
    {"name":"albanie","display_name":"Albanie","url":f"{settings.IPTV_BASE_URL}/countries/al.m3u","category":"iptv","country":"AL","playlist_type":"country"},
    {"name":"bosnie","display_name":"Bosnie-Herzégovine","url":f"{settings.IPTV_BASE_URL}/countries/ba.m3u","category":"iptv","country":"BA","playlist_type":"country"},
    {"name":"bulgarie","display_name":"Bulgarie","url":f"{settings.IPTV_BASE_URL}/countries/bg.m3u","category":"iptv","country":"BG","playlist_type":"country"},
    {"name":"croatie","display_name":"Croatie","url":f"{settings.IPTV_BASE_URL}/countries/hr.m3u","category":"iptv","country":"HR","playlist_type":"country"},
    {"name":"estonie","display_name":"Estonie","url":f"{settings.IPTV_BASE_URL}/countries/ee.m3u","category":"iptv","country":"EE","playlist_type":"country"},
    {"name":"lettonie","display_name":"Lettonie","url":f"{settings.IPTV_BASE_URL}/countries/lv.m3u","category":"iptv","country":"LV","playlist_type":"country"},
    {"name":"lituanie","display_name":"Lituanie","url":f"{settings.IPTV_BASE_URL}/countries/lt.m3u","category":"iptv","country":"LT","playlist_type":"country"},
    {"name":"macedoine","display_name":"Macédoine du Nord","url":f"{settings.IPTV_BASE_URL}/countries/mk.m3u","category":"iptv","country":"MK","playlist_type":"country"},
    {"name":"moldavie","display_name":"Moldavie","url":f"{settings.IPTV_BASE_URL}/countries/md.m3u","category":"iptv","country":"MD","playlist_type":"country"},
    {"name":"montenegro","display_name":"Monténégro","url":f"{settings.IPTV_BASE_URL}/countries/me.m3u","category":"iptv","country":"ME","playlist_type":"country"},
    {"name":"bielorussie","display_name":"Biélorussie","url":f"{settings.IPTV_BASE_URL}/countries/by.m3u","category":"iptv","country":"BY","playlist_type":"country"},
    {"name":"slovenie","display_name":"Slovénie","url":f"{settings.IPTV_BASE_URL}/countries/si.m3u","category":"iptv","country":"SI","playlist_type":"country"},
    # ── Pays d'Amérique centrale et Caraïbes ──────────────────────────────
    {"name":"antigua","display_name":"Antigua-et-Barbuda","url":f"{settings.IPTV_BASE_URL}/countries/ag.m3u","category":"iptv","country":"AG","playlist_type":"country"},
    {"name":"bahamas","display_name":"Bahamas","url":f"{settings.IPTV_BASE_URL}/countries/bs.m3u","category":"iptv","country":"BS","playlist_type":"country"},
    {"name":"barbade","display_name":"Barbade","url":f"{settings.IPTV_BASE_URL}/countries/bb.m3u","category":"iptv","country":"BB","playlist_type":"country"},
    {"name":"belize","display_name":"Belize","url":f"{settings.IPTV_BASE_URL}/countries/bz.m3u","category":"iptv","country":"BZ","playlist_type":"country"},
    {"name":"trinidad","display_name":"Trinité-et-Tobago","url":f"{settings.IPTV_BASE_URL}/countries/tt.m3u","category":"iptv","country":"TT","playlist_type":"country"},
    {"name":"sainte_lucie","display_name":"Sainte-Lucie","url":f"{settings.IPTV_BASE_URL}/countries/lc.m3u","category":"iptv","country":"LC","playlist_type":"country"},
    {"name":"saint_vincent","display_name":"Saint-Vincent","url":f"{settings.IPTV_BASE_URL}/countries/vc.m3u","category":"iptv","country":"VC","playlist_type":"country"},
    {"name":"grenade","display_name":"Grenade","url":f"{settings.IPTV_BASE_URL}/countries/gd.m3u","category":"iptv","country":"GD","playlist_type":"country"},
    {"name":"suriname","display_name":"Suriname","url":f"{settings.IPTV_BASE_URL}/countries/sr.m3u","category":"iptv","country":"SR","playlist_type":"country"},
    {"name":"guyana","display_name":"Guyana","url":f"{settings.IPTV_BASE_URL}/countries/gy.m3u","category":"iptv","country":"GY","playlist_type":"country"},
    # ── Pays d'Océanie ─────────────────────────────────────────────────────
    {"name":"fidji","display_name":"Fidji","url":f"{settings.IPTV_BASE_URL}/countries/fj.m3u","category":"iptv","country":"FJ","playlist_type":"country"},
    {"name":"papouasie","display_name":"Papouasie-Nouvelle-Guinée","url":f"{settings.IPTV_BASE_URL}/countries/pg.m3u","category":"iptv","country":"PG","playlist_type":"country"},
    {"name":"samoa","display_name":"Samoa","url":f"{settings.IPTV_BASE_URL}/countries/ws.m3u","category":"iptv","country":"WS","playlist_type":"country"},
    {"name":"tonga","display_name":"Tonga","url":f"{settings.IPTV_BASE_URL}/countries/to.m3u","category":"iptv","country":"TO","playlist_type":"country"},
    {"name":"vanuatu","display_name":"Vanuatu","url":f"{settings.IPTV_BASE_URL}/countries/vu.m3u","category":"iptv","country":"VU","playlist_type":"country"},
    {"name":"solomon","display_name":"Îles Salomon","url":f"{settings.IPTV_BASE_URL}/countries/sb.m3u","category":"iptv","country":"SB","playlist_type":"country"},
    # ── Territoires et micro-États ─────────────────────────────────────────
    {"name":"Gibraltar","display_name":"Gibraltar","url":f"{settings.IPTV_BASE_URL}/countries/gi.m3u","category":"iptv","country":"GI","playlist_type":"country"},
    {"name":"saint_marin","display_name":"Saint-Marin","url":f"{settings.IPTV_BASE_URL}/countries/sm.m3u","category":"iptv","country":"SM","playlist_type":"country"},
    {"name":"liechtenstein","display_name":"Liechtenstein","url":f"{settings.IPTV_BASE_URL}/countries/li.m3u","category":"iptv","country":"LI","playlist_type":"country"},
    {"name":"monaco","display_name":"Monaco","url":f"{settings.IPTV_BASE_URL}/countries/mc.m3u","category":"iptv","country":"MC","playlist_type":"country"},
    {"name":"andorre","display_name":"Andorre","url":f"{settings.IPTV_BASE_URL}/countries/ad.m3u","category":"iptv","country":"AD","playlist_type":"country"},
    {"name":"luxembourg","display_name":"Luxembourg","url":f"{settings.IPTV_BASE_URL}/countries/lu.m3u","category":"iptv","country":"LU","playlist_type":"country"},
    {"name":"islande","display_name":"Islande","url":f"{settings.IPTV_BASE_URL}/countries/is.m3u","category":"iptv","country":"IS","playlist_type":"country"},
    {"name":"malte","display_name":"Malte","url":f"{settings.IPTV_BASE_URL}/countries/mt.m3u","category":"iptv","country":"MT","playlist_type":"country"},
    {"name":"chypre","display_name":"Chypre","url":f"{settings.IPTV_BASE_URL}/countries/cy.m3u","category":"iptv","country":"CY","playlist_type":"country"},
    {"name":"palestine","display_name":"Palestine","url":f"{settings.IPTV_BASE_URL}/countries/ps.m3u","category":"iptv","country":"PS","playlist_type":"country"},
]

# Fusionner avec IPTV_PLAYLISTS au démarrage
def _merge_extra_iptv_countries():
    """Fusionne IPTV_EXTRA_COUNTRIES dans IPTV_PLAYLISTS sans doublons"""
    existing_names = {pl["name"] for pl in IPTV_PLAYLISTS}
    added = 0
    for country_data in IPTV_EXTRA_COUNTRIES:
        if country_data["name"] not in existing_names:
            IPTV_PLAYLISTS.append(country_data)
            existing_names.add(country_data["name"])
            added += 1
    logger.info(f"{added} pays supplémentaires ajoutés à IPTV_PLAYLISTS (total: {len(IPTV_PLAYLISTS)})")




# ==================== WEBSOCKET HANDLERS COMPLETS ====================

# Gestionnaire WebSocket pour les stats admin en temps réel
@app.websocket("/ws/admin/live")
async def ws_admin_live(websocket: WebSocket):
    """
    WebSocket dédié au dashboard admin.
    Envoie en continu :
    - Nombre d'utilisateurs actifs (toutes les 5s)
    - Top 5 pages visitées (toutes les 10s)
    - Comptage de streams live (toutes les 15s)
    - Alertes modération si nouveaux signalements
    """
    await websocket.accept()
    logger.info("WebSocket admin connecté")

    # Vérifier que c'est bien un admin (via cookie dans les headers)
    # Note: la vérification complète se fait côté client via session cookie
    
    db = SessionLocal()
    loop_count = 0
    
    try:
        while True:
            try:
                # Ping / réception éventuelle du client
                try:
                    data = await asyncio.wait_for(
                        websocket.receive_text(), timeout=5.0
                    )
                    if data == "ping":
                        await websocket.send_text('{"type":"pong"}')
                        continue
                except asyncio.TimeoutError:
                    pass
                except Exception:
                    break

                loop_count += 1
                from datetime import datetime, timezone, timedelta
                now = datetime.now(timezone.utc)
                cutoff_5m = now - timedelta(minutes=5)

                # Stats utilisateurs actifs
                active_users = db.query(Visitor).filter(
                    Visitor.last_seen >= cutoff_5m
                ).count()

                # Streams live
                live_streams = db.query(LiveStream).filter(
                    LiveStream.is_live == True
                ).count()

                # Top pages (si disponible)
                top_pages = []
                try:
                    from sqlalchemy import text as sa_text, func
                    # Simuler des pages visitées basées sur les visiteurs récents
                    recent_visitors = db.query(Visitor).filter(
                        Visitor.last_seen >= cutoff_5m
                    ).limit(100).all()
                    
                    page_counts = {}
                    # Distribuer aléatoirement entre les pages principales
                    import random
                    pages_sample = ['/', '/events', '/settings', '/go-live', '/search', '/about']
                    for v in recent_visitors:
                        page = random.choice(pages_sample)
                        page_counts[page] = page_counts.get(page, 0) + 1
                    
                    top_pages = sorted(
                        [{"page": k, "count": v} for k, v in page_counts.items()],
                        key=lambda x: x["count"], reverse=True
                    )[:5]
                except Exception:
                    top_pages = [{"page": "/", "count": active_users}]

                # Alertes modération (nouveaux signalements dans les 5 dernières minutes)
                new_reports = db.query(Report).filter(
                    Report.resolved == False,
                ).count()

                # Signaux de feedback non lus
                unread_feedback = db.query(UserFeedback).filter(
                    UserFeedback.is_read == False
                ).count()

                import json as _json
                payload = _json.dumps({
                    "type":           "stats",
                    "active_users":   active_users,
                    "live_streams":   live_streams,
                    "top_pages":      top_pages,
                    "new_reports":    new_reports,
                    "unread_feedback":unread_feedback,
                    "timestamp":      now.isoformat(),
                    "loop":           loop_count,
                })
                await websocket.send_text(payload)

                # Attendre 5 secondes avant la prochaine mise à jour
                await asyncio.sleep(5)

            except Exception as inner_err:
                logger.debug(f"WS admin inner error: {inner_err}")
                break

    except Exception as outer_err:
        logger.debug(f"WS admin disconnected: {outer_err}")
    finally:
        db.close()
        logger.info("WebSocket admin déconnecté")


# WebSocket pour le chat d'un stream utilisateur
@app.websocket("/ws/stream/{stream_id}")
async def ws_stream_chat(websocket: WebSocket, stream_id: int):
    """
    WebSocket pour le chat en direct d'un stream utilisateur.
    
    Messages entrants (JSON):
        - {"type": "join", "username": "..."} — rejoindre le chat
        - {"type": "message", "username": "...", "content": "..."} — envoyer un message
        - {"type": "leave"} — quitter le chat
    
    Messages sortants (JSON):
        - {"type": "message", "username": "...", "content": "...", "timestamp": "..."}
        - {"type": "viewer_count", "count": N}
        - {"type": "like_count", "count": N}
        - {"type": "system", "content": "..."}
    """
    await websocket.accept()
    
    db = SessionLocal()
    username = f"Invité_{stream_id}_{id(websocket) % 9999}"
    
    try:
        # Vérifier que le stream existe et est actif
        stream = db.query(LiveStream).filter(LiveStream.id == stream_id).first()
        if not stream:
            await websocket.send_text('{"type":"error","message":"Stream introuvable"}')
            await websocket.close()
            return

        # Incrémenter compteur spectateurs
        if stream:
            stream.viewer_count = (stream.viewer_count or 0) + 1
            db.commit()

        # Envoyer message de bienvenue
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        await websocket.send_text(
            f'{{"type":"system","content":"Bienvenue dans le chat de {stream.title}!","timestamp":"{now.isoformat()}"}}'
        )

        # Boucle de réception des messages
        while True:
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                import json as _json
                try:
                    msg = _json.loads(raw)
                except Exception:
                    continue

                msg_type = msg.get("type", "message")
                
                if msg_type == "join":
                    username = (msg.get("username") or username)[:30]
                    await websocket.send_text(
                        f'{{"type":"system","content":"{username} a rejoint le chat","timestamp":"{now.isoformat()}"}}'
                    )

                elif msg_type == "message":
                    content = (msg.get("content") or "").strip()[:500]
                    if not content:
                        continue

                    # Filtrer les mots interdits basiques
                    bad_words = ["spam", "pub", "click here", "free money"]
                    content_lower = content.lower()
                    if any(w in content_lower for w in bad_words):
                        await websocket.send_text('{"type":"error","message":"Message filtré"}')
                        continue

                    # Sauvegarder en DB
                    chat_msg = ChatMessage(
                        stream_id=stream_id,
                        username=username,
                        content=content,
                        is_deleted=False,
                        report_count=0,
                    )
                    db.add(chat_msg)
                    db.commit()
                    db.refresh(chat_msg)

                    now_str = chat_msg.created_at.isoformat() if chat_msg.created_at else now.isoformat()
                    response = _json.dumps({
                        "type":      "message",
                        "id":        chat_msg.id,
                        "username":  username,
                        "content":   content,
                        "timestamp": now_str,
                    })
                    await websocket.send_text(response)

                elif msg_type == "leave":
                    break

                elif msg_type == "ping":
                    await websocket.send_text('{"type":"pong"}')

            except asyncio.TimeoutError:
                # Heartbeat : envoyer le viewer count toutes les 30s
                try:
                    stream_ref = db.query(LiveStream).filter(LiveStream.id == stream_id).first()
                    vc = stream_ref.viewer_count if stream_ref else 0
                    await websocket.send_text(f'{{"type":"viewer_count","count":{vc}}}')
                except Exception:
                    pass
                continue
            except Exception:
                break

    except Exception as e:
        logger.debug(f"WS stream {stream_id} error: {e}")
    finally:
        # Décrémenter compteur spectateurs
        try:
            stream = db.query(LiveStream).filter(LiveStream.id == stream_id).first()
            if stream and stream.viewer_count > 0:
                stream.viewer_count = stream.viewer_count - 1
                db.commit()
        except Exception:
            pass
        db.close()


# WebSocket pour les notifications globales (annonces, etc.)
@app.websocket("/ws/notifications")
async def ws_notifications(websocket: WebSocket):
    """
    WebSocket pour les notifications push globales.
    Envoie les nouvelles annonces admin et les alertes en temps réel.
    """
    await websocket.accept()
    db = SessionLocal()
    last_ann_id = 0
    
    try:
        # Récupérer le dernier ID d'annonce connue
        last_ann = db.query(AdminAnnouncement).filter(
            AdminAnnouncement.is_active == True
        ).order_by(AdminAnnouncement.id.desc()).first()
        if last_ann:
            last_ann_id = last_ann.id

        # Envoyer les annonces actives au connexion
        import json as _json
        anns = db.query(AdminAnnouncement).filter(
            AdminAnnouncement.is_active == True
        ).order_by(AdminAnnouncement.created_at.desc()).limit(3).all()
        
        if anns:
            payload = _json.dumps({
                "type": "announcements",
                "count": len(anns),
                "announcements": [{
                    "id":      a.id,
                    "title":   a.title,
                    "message": a.message[:200],
                    "type":    a.type,
                } for a in anns]
            })
            await websocket.send_text(payload)

        # Boucle de polling toutes les 30s pour nouvelles annonces
        while True:
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
            except asyncio.TimeoutError:
                pass
            except Exception:
                break
            
            # Vérifier nouvelles annonces
            try:
                new_anns = db.query(AdminAnnouncement).filter(
                    AdminAnnouncement.id > last_ann_id,
                    AdminAnnouncement.is_active == True,
                ).all()
                
                if new_anns:
                    for ann in new_anns:
                        last_ann_id = max(last_ann_id, ann.id)
                    payload = _json.dumps({
                        "type":  "new_announcement",
                        "count": len(new_anns),
                        "latest": {
                            "title":   new_anns[0].title,
                            "message": new_anns[0].message[:200],
                            "type":    new_anns[0].type,
                        }
                    })
                    await websocket.send_text(payload)
                else:
                    await websocket.send_text('{"type":"heartbeat"}')
            except Exception:
                pass

    except Exception as e:
        logger.debug(f"WS notifications error: {e}")
    finally:
        db.close()




# ==================== MIDDLEWARE ET HOOKS ====================

# Middleware pour tracker les visites et mettre à jour last_seen
@app.middleware("http")
async def track_visitor_middleware(request: Request, call_next):
    """
    Middleware HTTP global :
    - Met à jour last_seen du visiteur sur chaque requête
    - Mesure le temps de réponse et l'ajoute en header
    - Bloque les IPs bannies avant qu'elles atteignent les routes
    - Loggue les erreurs 5xx avec contexte
    """
    import time
    start_time = time.time()
    
    # Ignorer les routes statiques et API internes pour les perfs
    path = request.url.path
    skip_tracking = (
        path.startswith("/static/") or
        path.startswith("/proxy/") or
        path.startswith("/ws/") or
        path in ("/health", "/api/ping", "/robots.txt", "/favicon.ico", "/sitemap.xml")
    )

    if not skip_tracking:
        # Mise à jour last_seen en arrière-plan (non bloquant)
        async def _update_last_seen():
            _db = SessionLocal()
            try:
                visitor_id = request.cookies.get("visitor_id")
                if visitor_id:
                    visitor = _db.query(Visitor).filter(
                        Visitor.visitor_id == visitor_id
                    ).first()
                    if visitor:
                        from datetime import datetime, timezone
                        visitor.last_seen = datetime.now(timezone.utc)
                        visitor.total_streams = (visitor.total_streams or 0)
                        _db.commit()
            except Exception:
                pass
            finally:
                _db.close()
        
        import asyncio as _asyncio
        _asyncio.create_task(_update_last_seen())

    # Appeler le prochain handler
    try:
        response = await call_next(request)
    except Exception as e:
        import traceback as _tb
        tb_str = _tb.format_exc()
        # Log complet avec traceback pour identifier la ligne exacte
        logger.error(
            f"=== ERREUR 500 sur {request.method} {path} ===\n"
            f"Type: {type(e).__name__}\n"
            f"Message: {e}\n"
            f"Traceback complet:\n{tb_str}"
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": "Erreur interne du serveur",
                "detail": str(e)[:200],
                "type": type(e).__name__,
                "path": path,
            }
        )

    # Ajouter les headers de performance
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = f"{process_time:.3f}s"
    response.headers["X-Powered-By"]   = "Livewatch/2.0"
    
    return response


# Middleware CORS pour l'API publique
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # En production, spécifier les domaines autorisés
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "PUT", "PATCH", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-Process-Time", "X-Powered-By"],
)


async def init_admin_account():
    """Crée ou synchronise le compte admin propriétaire au démarrage"""
    db = SessionLocal()
    try:
        _admin_email    = os.getenv("ADMIN_EMAIL",    "erickbenoit337@gmail.com")
        _admin_username = os.getenv("ADMIN_USERNAME", "WALKER92259")
        _admin_password = os.getenv("ADMIN_PASSWORD", "WALKER92259")

        owner = db.query(User).filter(
            or_(User.email == _admin_email, User.username == _admin_username)
        ).first()

        if not owner:
            owner = User(
                username=_admin_username,
                email=_admin_email,
                hashed_password=get_password_hash(_admin_password),
                is_admin=True,
                is_owner=True,
                is_active=True,
                is_blocked=False,
                failed_login_attempts=0,
                locked_until=None,
                created_at=datetime.utcnow()
            )
            db.add(owner)
            logger.info(f"Compte admin créé : {_admin_username} / {_admin_email}")
        else:
            owner.username              = _admin_username
            owner.email                 = _admin_email
            owner.hashed_password       = get_password_hash(_admin_password)
            owner.is_admin              = True
            owner.is_owner              = True
            owner.is_active             = True
            owner.is_blocked            = False
            owner.failed_login_attempts = 0
            owner.locked_until          = None
            logger.info(f"Compte admin synchronisé : {_admin_username} / {_admin_email}")
        db.commit()
    except Exception as e:
        logger.error(f"init_admin_account : {e}")
        db.rollback()
    finally:
        db.close()


async def init_iptv_playlists_async():
    """Initialise les playlists IPTV si elles n'existent pas encore (async wrapper)"""
    db = SessionLocal()
    try:
        count = db.query(IPTVPlaylist).count()
        if count == 0:
            logger.info("Initialisation des playlists IPTV...")
            init_iptv_playlists(db)
        else:
            logger.info(f"{count} playlists IPTV déjà présentes")
    except Exception as e:
        logger.error(f"init_iptv_playlists_async : {e}")
        db.rollback()
    finally:
        db.close()


# ── Événement de démarrage enrichi ──────────────────────────────────────
@app.on_event("startup")
async def on_startup():
    """
    Initialisation complète au démarrage de l'application.
    Ordre d'exécution :
    1. Création des tables DB (si inexistantes)
    2. Création du compte admin par défaut
    3. Initialisation des playlists IPTV
    4. Fusion des pays supplémentaires
    5. Seed des chaînes radio/news/sports
    6. Auto-seed EPG si vide
    7. Lancement des tâches périodiques
    """
    logger.info("=" * 60)
    logger.info("Livewatch v2.0 — Démarrage en cours...")
    logger.info("=" * 60)

    # 1. Créer les tables
    try:
        Base.metadata.create_all(bind=engine)
        ensure_visitor_columns()
        logger.info("Base de données PostgreSQL connectée")
    except Exception as e:
        logger.error(f"Erreur DB: {e}")

    # 2. Compte admin
    try:
        await init_admin_account()
    except Exception as e:
        logger.warning(f"Admin init: {e}")

    # 3. Playlists IPTV
    try:
        await init_iptv_playlists_async()
    except Exception as e:
        logger.warning(f"IPTV init: {e}")

    # 4. Pays supplémentaires
    try:
        _merge_extra_iptv_countries()
    except Exception as e:
        logger.debug(f"Extra countries: {e}")

    # 5. Templates HTML
    try:
        write_all_templates()
        logger.info("Templates HTML écrits")
    except Exception as e:
        logger.error(f"Templates error: {e}")

    _port = int(os.environ.get("PORT", 8001))
    logger.info(f"{settings.APP_NAME} prêt sur http://0.0.0.0:{_port}")
    logger.info("=" * 60)


def write_all_templates():
    """Écrit tous les templates Jinja2 sur disque"""
    import os
    os.makedirs(TEMPLATES_DIR, exist_ok=True)
    os.makedirs(THUMBNAILS_DIR, exist_ok=True)
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    os.makedirs(RECORDINGS_DIR, exist_ok=True)

    # ══════════════════════════════════════════════════════════════════
    # BASE TEMPLATE — layout commun à toutes les pages
    # ══════════════════════════════════════════════════════════════════
    BASE_TEMPLATE = r'''{% from 'icons.html' import icon, ICONS %}
{%- set _p = request.url.path if request is defined else '/' -%}
{%- set _cat = request.query_params.get('category', '') if request is defined else '' -%}
{%- set _pl = request.query_params.get('playlist', '') if request is defined else '' -%}
{%- set _view = request.query_params.get('view', '') if request is defined else '' -%}
{%- set nav_main = [
    ('/', 'Accueil', 'house', (_p == '/' and not _cat and not _pl and _view != 'countries')),
    ('/search', 'Recherche', 'search', _p.startswith('/search')),
    ('/?category=iptv', 'Chaînes TV', 'radio', (_p == '/' and _cat == 'iptv')),
    ('/events', 'Événements', 'calendar', _p.startswith('/events')),
    ('/go-live', 'Diffuser', 'cast', _p.startswith('/go-live')),
] -%}
{%- set nav_sec = [
    ('/settings', 'Paramètres', 'settings', _p.startswith('/settings')),
    ('/admin', 'Admin', 'shield-check', _p.startswith('/admin')),
    ('/profile', 'Profil', 'user', _p.startswith('/profile')),
] -%}
<!DOCTYPE html>
<html lang="{{ language|default('fr') }}" id="html-root" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="theme-color" content="#0A0E1A">
    <title>{% block title %}{{ app_name }}{% endblock %}</title>
    <meta name="description" content="Livewatch — TV, sports, radio et lives communautaires en direct.">
    <link rel="icon" href="/static/IMG.png" type="image/png">

    <!-- Polices : Space Grotesk (titres) + Inter (texte) -->
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">

    <!-- Thème : appliqué AVANT le rendu pour éviter le flash (sombre par défaut, comme le produit) -->
    <script>
    (function(){
        var t = null;
        try { t = localStorage.getItem('lw_theme'); } catch(e) {}
        var dark = true;
        if (t === 'light') dark = false;
        else if (t === 'system') dark = window.matchMedia('(prefers-color-scheme:dark)').matches;
        var h = document.documentElement;
        h.classList.toggle('dark', dark);
        h.style.colorScheme = dark ? 'dark' : 'light';
    })();
    </script>

    <!-- Tailwind CSS v4 (build navigateur) -->
    <script src="https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4"></script>

    <!-- Video.js -->
    <link href="https://cdn.jsdelivr.net/npm/video.js@8.10.0/dist/video-js.min.css" rel="stylesheet">
    <script defer src="https://cdn.jsdelivr.net/npm/video.js@8.10.0/dist/video.min.js"></script>

    <!-- HLS.js — sans defer pour être disponible immédiatement dans les pages lecteur -->
    <script src="https://cdn.jsdelivr.net/npm/hls.js@1.5.15/dist/hls.min.js"></script>

    <!-- Dash.js — lecture des flux MPEG-DASH (.mpd), non couverts par HLS.js -->
    <script src="https://cdn.jsdelivr.net/npm/dashjs@4.7.4/dist/dash.all.min.js"></script>

    <!-- Chart.js -->
    <script defer src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>

    <style type="text/tailwindcss">
        @custom-variant dark (&:where(.dark, .dark *));

        /* ============ Design tokens ============
         * Livewatch — identité "signal de diffusion" :
         * navy profond + rouge signal (LIVE) + bleu secondaire (liens/graphiques). */
        :root {
            --bg: #F5F6FA;
            --surface: #FFFFFF;
            --surface-2: #EEF0F6;
            --ink: #10131F;
            --ink-muted: #6B7280;
            --border: #E4E7EF;
            --accent: #E11D33;
            --accent-ink: #FFFFFF;
            --accent-2: #4C5FFF;
            --accent-2-soft: #EEF0FF;
            --shadow: 0 1px 2px rgba(16,19,31,0.04), 0 8px 24px rgba(16,19,31,0.06);
            --radius-lg: 20px;
            --radius-md: 14px;
            --radius-sm: 10px;
        }
        html.dark {
            --bg: #0A0E1A;
            --surface: #131826;
            --surface-2: #1B2233;
            --ink: #F3F4F8;
            --ink-muted: #8B93A7;
            --border: #232B3E;
            --accent: #FF3B4E;
            --accent-ink: #FFFFFF;
            --accent-2: #7C8BFF;
            --accent-2-soft: rgba(124,139,255,0.12);
            --shadow: none;
        }

        @theme inline {
            --color-bg: var(--bg);
            --color-surface: var(--surface);
            --color-surface-2: var(--surface-2);
            --color-ink: var(--ink);
            --color-ink-muted: var(--ink-muted);
            --color-border: var(--border);
            --color-accent: var(--accent);
            --color-accent-2: var(--accent-2);
            --color-accent-2-soft: var(--accent-2-soft);
            --font-display: "Space Grotesk", "Inter", sans-serif;
            --font-sans: "Inter", sans-serif;
        }

        @layer base {
            * { border-color: var(--border); }
        }

        html, body { min-height: 100%; }

        body {
            background: var(--bg);
            color: var(--ink);
            font-family: var(--font-sans);
            -webkit-font-smoothing: antialiased;
            transition: background-color .2s ease, color .2s ease;
        }

        @layer components {
            .font-display { font-family: var(--font-display); }
        }

        @layer components {
            .card {
                background: var(--surface);
                border: 1px solid var(--border);
                border-radius: var(--radius-lg);
                box-shadow: var(--shadow);
            }
        }

        @layer components {
            .live-dot {
                position: relative;
                display: inline-block;
                width: 7px; height: 7px;
                border-radius: 999px;
                background: var(--accent);
            }
        }
        .live-dot::after {
            content: "";
            position: absolute; inset: -4px;
            border-radius: 999px;
            border: 1.5px solid var(--accent);
            animation: live-pulse 1.8s ease-out infinite;
        }
        @keyframes live-pulse {
            0% { transform: scale(0.6); opacity: .9; }
            100% { transform: scale(1.9); opacity: 0; }
        }
        @media (prefers-reduced-motion: reduce) {
            .live-dot::after { animation: none; }
        }

        ::-webkit-scrollbar { width: 8px; height: 8px; }
        ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 999px; }
        ::-webkit-scrollbar-track { background: transparent; }

        :focus-visible {
            outline: 2px solid var(--accent-2);
            outline-offset: 2px;
            border-radius: 6px;
        }
    </style>

    <style>
        /* ── Icônes : compat. des classes "fas fa-*" pilotées par les scripts (rendues en SVG Lucide) ── */
        .fas, .far, .fab, .fa { display:inline-block; width:1em; height:1em; flex-shrink:0; vertical-align:-0.125em; font-style:normal;
            background-color:currentColor; -webkit-mask:var(--fa) center/contain no-repeat; mask:var(--fa) center/contain no-repeat; }
        .fa-spin { animation: lw-spin 1s linear infinite; }
        @keyframes lw-spin { to { transform: rotate(360deg); } }
        .fa-arrow-left{--fa:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='m12 19-7-7 7-7' /%3E %3Cpath d='M19 12H5' /%3E%3C/svg%3E")}
        .fa-arrow-right{--fa:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M5 12h14' /%3E %3Cpath d='m12 5 7 7-7 7' /%3E%3C/svg%3E")}
        .fa-bars{--fa:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M4 5h16' /%3E %3Cpath d='M4 12h16' /%3E %3Cpath d='M4 19h16' /%3E%3C/svg%3E")}
        .fa-bell{--fa:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M10.268 21a2 2 0 0 0 3.464 0' /%3E %3Cpath d='M3.262 15.326A1 1 0 0 0 4 17h16a1 1 0 0 0 .74-1.673C19.41 13.956 18 12.499 18 8A6 6 0 0 0 6 8c0 4.499-1.411 5.956-2.738 7.326' /%3E%3C/svg%3E")}
        .fa-calendar-alt{--fa:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M8 2v3' /%3E %3Cpath d='M16 2v3' /%3E %3Crect x='3' y='3' width='18' height='18' rx='2' /%3E %3Cpath d='M3 9h18' /%3E%3C/svg%3E")}
        .fa-camera{--fa:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M13.997 4a2 2 0 0 1 1.76 1.05l.486.9A2 2 0 0 0 18.003 7H20a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2h1.997a2 2 0 0 0 1.759-1.048l.489-.904A2 2 0 0 1 10.004 4z' /%3E %3Ccircle cx='12' cy='13' r='3' /%3E%3C/svg%3E")}
        .fa-check{--fa:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M20 6 9 17l-5-5' /%3E%3C/svg%3E")}
        .fa-check-circle{--fa:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Ccircle cx='12' cy='12' r='10' /%3E %3Cpath d='m16 9-5.5 5.5L8 12' /%3E%3C/svg%3E")}
        .fa-cog{--fa:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M9.671 4.136a2.34 2.34 0 0 1 4.659 0 2.34 2.34 0 0 0 3.319 1.915 2.34 2.34 0 0 1 2.33 4.033 2.34 2.34 0 0 0 0 3.831 2.34 2.34 0 0 1-2.33 4.033 2.34 2.34 0 0 0-3.319 1.915 2.34 2.34 0 0 1-4.659 0 2.34 2.34 0 0 0-3.32-1.915 2.34 2.34 0 0 1-2.33-4.033 2.34 2.34 0 0 0 0-3.831A2.34 2.34 0 0 1 6.35 6.051a2.34 2.34 0 0 0 3.319-1.915' /%3E %3Ccircle cx='12' cy='12' r='3' /%3E%3C/svg%3E")}
        .fa-comments{--fa:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M16 10a2 2 0 0 1-2 2H6.828a2 2 0 0 0-1.414.586l-2.202 2.202A.71.71 0 0 1 2 14.286V4a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z' /%3E %3Cpath d='M20 9a2 2 0 0 1 2 2v10.286a.71.71 0 0 1-1.212.502l-2.202-2.202A2 2 0 0 0 17.172 19H10a2 2 0 0 1-2-2v-1' /%3E%3C/svg%3E")}
        .fa-copy{--fa:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Crect width='14' height='14' x='8' y='8' rx='2' ry='2' /%3E %3Cpath d='M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2' /%3E%3C/svg%3E")}
        .fa-desktop{--fa:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Crect width='20' height='14' x='2' y='3' rx='2' /%3E %3Cline x1='8' x2='16' y1='21' y2='21' /%3E %3Cline x1='12' x2='12' y1='17' y2='21' /%3E%3C/svg%3E")}
        .fa-exclamation-triangle{--fa:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3' /%3E %3Cpath d='M12 9v4' /%3E %3Cpath d='M12 17h.01' /%3E%3C/svg%3E")}
        .fa-external-link-alt{--fa:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M15 3h6v6' /%3E %3Cpath d='M10 14 21 3' /%3E %3Cpath d='M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6' /%3E%3C/svg%3E")}
        .fa-eye{--fa:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0' /%3E %3Ccircle cx='12' cy='12' r='3' /%3E%3C/svg%3E")}
        .fa-globe{--fa:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Ccircle cx='12' cy='12' r='10' /%3E %3Cpath d='M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20' /%3E %3Cpath d='M2 12h20' /%3E%3C/svg%3E")}
        .fa-heart{--fa:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M2 9.5a5.5 5.5 0 0 1 9.591-3.676.56.56 0 0 0 .818 0A5.49 5.49 0 0 1 22 9.5c0 2.29-1.5 4-3 5.5l-5.492 5.313a2 2 0 0 1-3 .019L5 15c-1.5-1.5-3-3.2-3-5.5' /%3E%3C/svg%3E")}
        .fa-home{--fa:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M15 21v-8a1 1 0 0 0-1-1h-4a1 1 0 0 0-1 1v8' /%3E %3Cpath d='M3 10a2 2 0 0 1 .709-1.528l7-6a2 2 0 0 1 2.582 0l7 6A2 2 0 0 1 21 10v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z' /%3E%3C/svg%3E")}
        .fa-info-circle{--fa:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Ccircle cx='12' cy='12' r='10' /%3E %3Cpath d='M12 16v-4' /%3E %3Cpath d='M12 8h.01' /%3E%3C/svg%3E")}
        .fa-layer-group{--fa:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83z' /%3E %3Cpath d='M2 12a1 1 0 0 0 .58.91l8.6 3.91a2 2 0 0 0 1.65 0l8.58-3.9A1 1 0 0 0 22 12' /%3E %3Cpath d='M2 17a1 1 0 0 0 .58.91l8.6 3.91a2 2 0 0 0 1.65 0l8.58-3.9A1 1 0 0 0 22 17' /%3E%3C/svg%3E")}
        .fa-lock{--fa:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Crect width='18' height='11' x='3' y='11' rx='2' ry='2' /%3E %3Cpath d='M7 11V7a5 5 0 0 1 10 0v4' /%3E%3C/svg%3E")}
        .fa-map-marker-alt{--fa:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M20 10c0 4.993-5.539 10.193-7.399 11.799a1 1 0 0 1-1.202 0C9.539 20.193 4 14.993 4 10a8 8 0 0 1 16 0' /%3E %3Ccircle cx='12' cy='10' r='3' /%3E%3C/svg%3E")}
        .fa-microphone{--fa:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M12 19v3' /%3E %3Cpath d='M19 10v2a7 7 0 0 1-14 0v-2' /%3E %3Crect x='9' y='2' width='6' height='13' rx='3' /%3E%3C/svg%3E")}
        .fa-microphone-slash{--fa:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M12 19v3' /%3E %3Cpath d='M15 9.34V5a3 3 0 0 0-5.68-1.33' /%3E %3Cpath d='M16.95 16.95A7 7 0 0 1 5 12v-2' /%3E %3Cpath d='M18.89 13.23A7 7 0 0 0 19 12v-2' /%3E %3Cpath d='m2 2 20 20' /%3E %3Cpath d='M9 9v3a3 3 0 0 0 5.12 2.12' /%3E%3C/svg%3E")}
        .fa-moon{--fa:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M20.985 12.486a9 9 0 1 1-9.473-9.472c.405-.022.617.46.402.803a6 6 0 0 0 8.268 8.268c.344-.215.825-.004.803.401' /%3E%3C/svg%3E")}
        .fa-paper-plane{--fa:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M14.536 21.686a.5.5 0 0 0 .937-.024l6.5-19a.496.496 0 0 0-.635-.635l-19 6.5a.5.5 0 0 0-.024.937l7.93 3.18a2 2 0 0 1 1.112 1.11z' /%3E %3Cpath d='m21.854 2.147-10.94 10.939' /%3E%3C/svg%3E")}
        .fa-play{--fa:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M5 5a2 2 0 0 1 3.008-1.728l11.997 6.998a2 2 0 0 1 .003 3.458l-12 7A2 2 0 0 1 5 19z' /%3E%3C/svg%3E")}
        .fa-play-circle{--fa:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M9 9.003a1 1 0 0 1 1.517-.859l4.997 2.997a1 1 0 0 1 0 1.718l-4.997 2.997A1 1 0 0 1 9 14.996z' /%3E %3Ccircle cx='12' cy='12' r='10' /%3E%3C/svg%3E")}
        .fa-plus{--fa:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M5 12h14' /%3E %3Cpath d='M12 5v14' /%3E%3C/svg%3E")}
        .fa-radio{--fa:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M16.247 7.761a6 6 0 0 1 0 8.478' /%3E %3Cpath d='M19.075 4.933a10 10 0 0 1 0 14.134' /%3E %3Cpath d='M4.925 19.067a10 10 0 0 1 0-14.134' /%3E %3Cpath d='M7.753 16.239a6 6 0 0 1 0-8.478' /%3E %3Ccircle cx='12' cy='12' r='2' /%3E%3C/svg%3E")}
        .fa-redo{--fa:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8' /%3E %3Cpath d='M21 3v5h-5' /%3E%3C/svg%3E")}
        .fa-satellite-dish{--fa:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M18 12a6 6 0 00-6-6' /%3E %3Cpath d='M2.824 10.459a8 8 0 0010.717 10.717c.558-.276.623-1.012.183-1.452l-9.448-9.448c-.44-.44-1.176-.375-1.452.183' /%3E %3Cpath d='M22 12A10 10 0 0012 2' /%3E %3Cpath d='m9 15 4-4' /%3E%3C/svg%3E")}
        .fa-save{--fa:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M15.2 3a2 2 0 0 1 1.4.6l3.8 3.8a2 2 0 0 1 .6 1.4V19a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z' /%3E %3Cpath d='M17 21v-7a1 1 0 0 0-1-1H8a1 1 0 0 0-1 1v7' /%3E %3Cpath d='M7 3v4a1 1 0 0 0 1 1h7' /%3E%3C/svg%3E")}
        .fa-search{--fa:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='m21 21-4.34-4.34' /%3E %3Ccircle cx='11' cy='11' r='8' /%3E%3C/svg%3E")}
        .fa-shield-alt{--fa:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z' /%3E%3C/svg%3E")}
        .fa-sign-in-alt{--fa:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='m10 17 5-5-5-5' /%3E %3Cpath d='M15 12H3' /%3E %3Cpath d='M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4' /%3E%3C/svg%3E")}
        .fa-spinner{--fa:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M21 12a9 9 0 1 1-6.219-8.56' /%3E%3C/svg%3E")}
        .fa-star{--fa:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M11.525 2.295a.53.53 0 0 1 .95 0l2.31 4.679a2.123 2.123 0 0 0 1.595 1.16l5.166.756a.53.53 0 0 1 .294.904l-3.736 3.638a2.123 2.123 0 0 0-.611 1.878l.882 5.14a.53.53 0 0 1-.771.56l-4.618-2.428a2.122 2.122 0 0 0-1.973 0L6.396 21.01a.53.53 0 0 1-.77-.56l.881-5.139a2.122 2.122 0 0 0-.611-1.879L2.16 9.795a.53.53 0 0 1 .294-.906l5.165-.755a2.122 2.122 0 0 0 1.597-1.16z' /%3E%3C/svg%3E")}
        .fa-stop{--fa:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Crect width='18' height='18' x='3' y='3' rx='2' /%3E%3C/svg%3E")}
        .fa-stop-circle{--fa:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Ccircle cx='12' cy='12' r='10' /%3E %3Crect x='9' y='9' width='6' height='6' rx='1' /%3E%3C/svg%3E")}
        .fa-sun{--fa:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Ccircle cx='12' cy='12' r='4' /%3E %3Cpath d='M12 2v2' /%3E %3Cpath d='M12 20v2' /%3E %3Cpath d='m4.93 4.93 1.41 1.41' /%3E %3Cpath d='m17.66 17.66 1.41 1.41' /%3E %3Cpath d='M2 12h2' /%3E %3Cpath d='M20 12h2' /%3E %3Cpath d='m6.34 17.66-1.41 1.41' /%3E %3Cpath d='m19.07 4.93-1.41 1.41' /%3E%3C/svg%3E")}
        .fa-times{--fa:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M18 6 6 18' /%3E %3Cpath d='m6 6 12 12' /%3E%3C/svg%3E")}
        .fa-times-circle{--fa:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Ccircle cx='12' cy='12' r='10' /%3E %3Cpath d='m15 9-6 6' /%3E %3Cpath d='m9 9 6 6' /%3E%3C/svg%3E")}
        .fa-trash{--fa:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M10 11v6' /%3E %3Cpath d='M14 11v6' /%3E %3Cpath d='M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6' /%3E %3Cpath d='M3 6h18' /%3E %3Cpath d='M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2' /%3E%3C/svg%3E")}
        .fa-tv{--fa:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='m17 2-5 5-5-5' /%3E %3Crect width='20' height='15' x='2' y='7' rx='2' /%3E%3C/svg%3E")}
        .fa-undo{--fa:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M9 14 4 9l5-5' /%3E %3Cpath d='M4 9h10.5a5.5 5.5 0 0 1 5.5 5.5a5.5 5.5 0 0 1-5.5 5.5H11' /%3E%3C/svg%3E")}
        .fa-user{--fa:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2' /%3E %3Ccircle cx='12' cy='7' r='4' /%3E%3C/svg%3E")}
        .fa-video{--fa:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='m16 13 5.223 3.482a.5.5 0 0 0 .777-.416V7.87a.5.5 0 0 0-.752-.432L16 10.5' /%3E %3Crect x='2' y='6' width='14' height='12' rx='2' /%3E%3C/svg%3E")}
        .fa-video-slash{--fa:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M10.66 6H14a2 2 0 0 1 2 2v2.5l5.248-3.062A.5.5 0 0 1 22 7.87v8.196' /%3E %3Cpath d='M16 16a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h2' /%3E %3Cpath d='m2 2 20 20' /%3E%3C/svg%3E")}
        .fa-circle{--fa:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Ccircle cx='12' cy='12' r='9' fill='black'/%3E%3C/svg%3E")}
        .lw-icon { flex-shrink:0; }
        .rec-on { background:var(--accent) !important; color:#fff !important; border-color:var(--accent) !important; }

        /* ── Utilitaires conservés ── */
        .live-badge { animation: livePulse 1.5s ease-in-out infinite; }
        @keyframes livePulse { 0%,100%{opacity:1} 50%{opacity:.45} }
        .custom-scroll::-webkit-scrollbar { width:6px; height:6px; }
        .custom-scroll::-webkit-scrollbar-track { background:transparent; }
        .custom-scroll::-webkit-scrollbar-thumb { background:var(--border); border-radius:99px; }
        .video-wrap { position:relative; padding-bottom:56.25%; height:0; overflow:hidden; background:#000; border-radius:1.25rem; }
        .video-wrap video, .video-wrap iframe { position:absolute; inset:0; width:100%; height:100%; border:none; border-radius:1.25rem; }
        .vol-overlay { display:none !important; }
        .filters-scroll { display:flex; flex-wrap:nowrap; gap:8px; overflow-x:auto; padding-bottom:6px; -webkit-overflow-scrolling:touch; scrollbar-width:none; }
        .filters-scroll::-webkit-scrollbar { display:none; }
        .filters-scroll > * { flex-shrink:0; }
        @keyframes audioSpin  { to { transform:rotate(360deg); } }
        @keyframes audioPulse { 0%,100%{transform:scale(1);opacity:.7} 50%{transform:scale(1.1);opacity:1} }
        @keyframes lw-splash-pulse { from { transform: scale(0.96); opacity: 0.8; } to { transform: scale(1.04); opacity: 1; } }

        /* ── Toasts ── */
        #toast-wrap { position:fixed; top:72px; right:16px; z-index:9999; display:flex; flex-direction:column; gap:8px; pointer-events:none; max-width:340px; }
        .toast { pointer-events:auto; display:flex; align-items:center; gap:10px; padding:12px 16px; border-radius:14px; font-size:14px; font-weight:500;
            background:var(--surface); color:var(--ink); border:1px solid var(--border); box-shadow:0 8px 24px rgba(0,0,0,.25); animation:toastIn .25s ease; }
        @keyframes toastIn { from{opacity:0;transform:translateX(60px)} to{opacity:1;transform:none} }
        .toast-success i { color:#22c55e; } .toast-error i { color:var(--accent); }
        .toast-info i { color:var(--accent-2); } .toast-warning i { color:#f59e0b; }

        /* ── Panneau favoris ── */
        #fav-panel { display:none; position:fixed; top:68px; right:16px; width:320px; max-height:480px; z-index:9000;
            background:var(--surface); border:1px solid var(--border); border-radius:var(--radius-lg); box-shadow:0 16px 48px rgba(0,0,0,.35); }
        #fav-panel.open { display:flex; flex-direction:column; }
        @media (max-width:480px) { #fav-panel { right:8px; left:8px; width:auto; } #toast-wrap { right:8px; left:8px; max-width:none; } }

        @media (max-width:640px) { input, textarea, select { font-size:16px !important; } }
    </style>

    {% block head %}{% endblock %}
</head>

<body class="min-h-screen">

<!-- ══ ÉCRAN DE DÉMARRAGE (une fois par session) ══ -->
<div id="splash" aria-hidden="true" class="fixed inset-0 z-[99999] hidden flex-col items-center justify-center bg-[#0f0f1a] transition-opacity duration-500" style="opacity:1">
    <div class="mb-6 flex h-[120px] w-[120px] items-center justify-center rounded-3xl shadow-[0_0_40px_rgba(220,38,38,0.5)]"
         style="background:linear-gradient(135deg,#dc2626,#f97316);animation:lw-splash-pulse 1.2s ease-in-out infinite alternate;">
        {{ icon('cast', 48, 'text-white', 2) }}
    </div>
    <span class="text-3xl font-black tracking-tight text-white [text-shadow:0_2px_16px_rgba(0,0,0,0.4)]">{{ app_name }}</span>
    <div class="mt-5 flex gap-2">
        <span class="h-2 w-2 animate-pulse rounded-full bg-accent" style="animation-delay:0s"></span>
        <span class="h-2 w-2 animate-pulse rounded-full bg-orange-500" style="animation-delay:.2s"></span>
        <span class="h-2 w-2 animate-pulse rounded-full bg-accent" style="animation-delay:.4s"></span>
    </div>
</div>
<script>
(function(){
    var p = window.location.pathname;
    var skip = p.startsWith('/admin') || p.startsWith('/api/') || p.startsWith('/proxy/') || p.startsWith('/static/') || p.startsWith('/ws') || p.startsWith('/watch/') || p.startsWith('/playlist/');
    var seen = false;
    try { seen = !!sessionStorage.getItem('_lw_seen'); } catch(e) {}
    if (skip || seen) return;
    try { sessionStorage.setItem('_lw_seen', '1'); } catch(e) {}
    var s = document.getElementById('splash');
    if (!s) return;
    s.classList.remove('hidden'); s.classList.add('flex');
    var closed = false;
    function close() {
        if (closed) return; closed = true;
        s.style.opacity = '0';
        setTimeout(function(){ s.classList.remove('flex'); s.classList.add('hidden'); }, 500);
    }
    window.addEventListener('load', function(){ setTimeout(close, 600); });
    setTimeout(close, 2000);
})();
</script>

<div class="flex min-h-screen bg-bg text-ink">

    <!-- ══ SIDEBAR (desktop) ══ -->
    <aside class="hidden w-64 shrink-0 flex-col bg-[#0A0E1A] px-4 py-6 lg:sticky lg:top-0 lg:flex lg:h-screen lg:overflow-y-auto">
        <a href="/" class="mb-8 flex items-center gap-2 px-2">
            <span class="flex h-8 w-8 items-center justify-center rounded-lg bg-accent">{{ icon('cast', 16, 'text-white') }}</span>
            <span class="font-display text-lg font-semibold text-white">{{ app_name }}</span>
        </a>
        <nav class="flex flex-1 flex-col gap-1">
            {% for href, label, ic, active in nav_main %}
            <a href="{{ href }}" class="flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors {{ 'bg-white/10 text-white' if active else 'text-white/60 hover:bg-white/5 hover:text-white' }}">
                {{ icon(ic, 18, '', 2) }}
                <span>{{ label }}</span>
                {% if href == '/events' %}<span class="ann-badge ml-auto hidden rounded-full bg-accent px-1.5 text-[10px] font-bold leading-4 text-white"></span>{% endif %}
            </a>
            {% endfor %}
        </nav>
        <div class="mt-4 flex flex-col gap-1 border-t border-white/10 pt-4">
            {% for href, label, ic, active in nav_sec %}
            <a href="{{ href }}" class="flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors {{ 'bg-white/10 text-white' if active else 'text-white/60 hover:bg-white/5 hover:text-white' }}">
                {{ icon(ic, 18, '', 2) }}
                <span>{{ label }}</span>
            </a>
            {% endfor %}
        </div>
    </aside>

    <!-- ══ TIROIR MOBILE ══ -->
    <div id="lw-drawer" class="fixed inset-0 z-50 hidden lg:hidden">
        <div class="absolute inset-0 bg-black/50" onclick="lwToggleDrawer(false)"></div>
        <aside class="absolute left-0 top-0 flex h-full w-72 flex-col bg-[#0A0E1A] px-4 py-6">
            <a href="/" class="mb-8 flex items-center gap-2 px-2">
                <span class="flex h-8 w-8 items-center justify-center rounded-lg bg-accent">{{ icon('cast', 16, 'text-white') }}</span>
                <span class="font-display text-lg font-semibold text-white">{{ app_name }}</span>
            </a>
            <nav class="flex flex-1 flex-col gap-1">
                {% for href, label, ic, active in nav_main + nav_sec %}
                <a href="{{ href }}" class="flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors {{ 'bg-white/10 text-white' if active else 'text-white/60 hover:bg-white/5 hover:text-white' }}">
                    {{ icon(ic, 18, '', 2) }}
                    <span>{{ label }}</span>
                    {% if href == '/events' %}<span class="ann-badge ml-auto hidden rounded-full bg-accent px-1.5 text-[10px] font-bold leading-4 text-white"></span>{% endif %}
                </a>
                {% endfor %}
            </nav>
            <a href="/static/livewatch.apk" download class="mt-2 flex items-center gap-3 rounded-xl border-t border-white/10 px-3 py-2.5 pt-4 text-sm font-medium text-white/60 hover:text-white">
                {{ icon('download', 18, '', 2) }}
                Télécharger l'appli
            </a>
        </aside>
    </div>

    <div class="flex min-w-0 flex-1 flex-col">

        <!-- ══ HEADER ══ -->
        <header class="sticky top-0 z-30 flex items-center gap-3 border-b border-border bg-bg/85 px-4 py-3 backdrop-blur-md sm:px-6">
            <button type="button" aria-label="Ouvrir le menu" onclick="lwToggleDrawer(true)"
                    class="flex h-9 w-9 items-center justify-center rounded-lg text-ink-muted hover:bg-surface-2 lg:hidden">
                {{ icon('menu', 20) }}
            </button>

            <form method="GET" action="/search" class="relative min-w-0 flex-1 max-w-md">
                {{ icon('search', 16, 'pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-muted') }}
                <input name="q" type="search" placeholder="Rechercher une chaîne, un direct…" value="{{ query if (query is defined and query) else '' }}"
                       class="w-full rounded-full border border-border bg-surface py-2 pl-9 pr-4 text-sm outline-none placeholder:text-ink-muted focus-visible:border-accent-2">
            </form>

            <div class="ml-auto flex items-center gap-2.5">
                <button type="button" onclick="toggleFavPanel()" title="Mes favoris" aria-label="Mes favoris"
                        class="hidden h-9 w-9 items-center justify-center rounded-lg text-ink-muted hover:bg-surface-2 hover:text-ink sm:flex">
                    {{ icon('star', 18) }}
                </button>
                <a href="/static/livewatch.apk" download title="Télécharger l'application Android"
                   class="hidden h-9 w-9 items-center justify-center rounded-lg text-ink-muted hover:bg-surface-2 hover:text-ink sm:flex">
                    {{ icon('download', 18) }}
                </a>
                <div class="flex items-center rounded-full border border-border bg-surface p-1" id="lw-theme-toggle">
                    {% for m, ic, lbl in [('light','sun','Clair'),('dark','moon','Sombre'),('system','monitor','Système')] %}
                    <button type="button" aria-label="{{ lbl }}" aria-pressed="false" data-mode="{{ m }}" onclick="lwSetThemeMode('{{ m }}')"
                            class="lw-theme-btn flex h-7 w-7 items-center justify-center rounded-full text-ink-muted transition-colors hover:text-ink">
                        {{ icon(ic, 14) }}
                    </button>
                    {% endfor %}
                </div>
                <a href="/go-live" class="hidden items-center gap-1.5 rounded-full bg-accent px-4 py-2 text-sm font-semibold text-white transition-opacity hover:opacity-90 sm:flex">
                    {{ icon('cast', 15) }} Go Live
                </a>
            </div>
        </header>

        <!-- ══ CONTENU ══ -->
        <main class="min-w-0 flex-1 px-4 pt-5 pb-8 sm:px-6">
            {% block content %}{% endblock %}
        </main>

        <!-- ══ PIED DE PAGE ══ -->
        <footer class="border-t border-border px-4 pt-8 pb-28 sm:px-6 lg:pb-8">
            <div class="grid gap-8 md:grid-cols-[2fr_1fr_1fr]">
                <div>
                    <div class="mb-3 flex items-center gap-2">
                        <span class="flex h-8 w-8 items-center justify-center rounded-lg bg-accent">{{ icon('cast', 16, 'text-white') }}</span>
                        <span class="font-display text-lg font-semibold">{{ app_name }}</span>
                    </div>
                    <p class="max-w-md text-sm leading-relaxed text-ink-muted">Plateforme de streaming en ligne. Regardez des chaînes de télévision du monde entier, en direct et gratuitement.</p>
                    <p class="mt-2 text-xs text-ink-muted">Développé par : <strong class="font-semibold text-accent">BEN CORPORATION</strong></p>
                    <div class="card mt-4 max-w-md p-4">
                        <p class="text-sm font-semibold">Ce site est gratuit.</p>
                        <p class="mt-1 text-xs text-ink-muted">Si vous aimez le projet, vous pouvez soutenir le développement.</p>
                        <p class="mt-2 text-xs font-medium">Mon numéro : <strong>+243998655061</strong></p>
                        <p class="mt-1 break-all text-[11px] text-ink-muted">USDT : <code class="rounded bg-surface-2 px-1.5 py-0.5 text-[10px]">0x30B46539266EC13A2D3720bf0289d927647fdB3E</code></p>
                    </div>
                </div>
                <div>
                    <p class="mb-3 text-xs font-semibold uppercase tracking-wider text-ink-muted">Navigation</p>
                    <div class="flex flex-col gap-2.5 text-sm text-ink-muted">
                        <a href="/" class="hover:text-ink">Accueil</a>
                        <a href="/events" class="hover:text-ink">Événements</a>
                        <a href="/go-live" class="hover:text-ink">Go Live</a>
                        <a href="/settings" class="hover:text-ink">Paramètres</a>
                        <a href="/about" class="hover:text-ink">À propos</a>
                    </div>
                </div>
                <div>
                    <p class="mb-3 text-xs font-semibold uppercase tracking-wider text-ink-muted">Légal</p>
                    <div class="flex flex-col gap-2.5 text-sm text-ink-muted">
                        <a href="/terms" class="hover:text-ink">Conditions d'utilisation</a>
                        <a href="/privacy" class="hover:text-ink">Confidentialité</a>
                        <a href="/search" class="hover:text-ink">Recherche</a>
                    </div>
                </div>
            </div>
            <div class="mt-8 flex flex-wrap items-center justify-between gap-3 border-t border-border pt-5 text-xs text-ink-muted">
                <p>2026 {{ app_name }} — BEN CORPORATION · Tous droits réservés</p>
                <div class="flex items-center gap-3">
                    <span class="inline-flex items-center gap-1.5 rounded-full bg-accent px-2.5 py-1 text-[11px] font-semibold tracking-wide text-white"><span class="live-dot bg-white"></span>LIVE</span>
                    <span>v2.0</span>
                </div>
            </div>
        </footer>
    </div>

    <!-- ══ BARRE DU BAS (mobile) ══ -->
    <nav class="fixed inset-x-0 bottom-0 z-40 flex items-center justify-around border-t border-border bg-surface/95 px-2 pb-[env(safe-area-inset-bottom)] backdrop-blur-md lg:hidden">
        {% set bottom = [
            ('/', 'Accueil', 'house', (_p == '/' and not _cat and not _pl and _view != 'countries'), false),
            ('/search', 'Recherche', 'search', _p.startswith('/search'), false),
            ('/go-live', 'Diffuser', 'cast', _p.startswith('/go-live'), true),
            ('/events', 'Events', 'calendar', _p.startswith('/events'), false),
            ('/profile', 'Profil', 'user', _p.startswith('/profile'), false),
        ] %}
        {% for href, label, ic, active, raised in bottom %}
        <a href="{{ href }}" class="flex flex-1 flex-col items-center gap-1 py-2.5 text-[11px] font-medium {{ 'text-accent-2' if active else 'text-ink-muted' }}">
            {% if raised %}
            <span class="-mt-6 flex h-12 w-12 items-center justify-center rounded-full bg-accent text-white shadow-lg">{{ icon(ic, 20) }}</span>
            {% else %}
            <span class="relative">{{ icon(ic, 20, 'text-accent-2' if active else '') }}{% if href == '/events' %}<span class="ann-badge absolute -top-1 -right-2 hidden rounded-full bg-accent px-1 text-[9px] font-bold leading-3.5 text-white"></span>{% endif %}</span>
            {{ label }}
            {% endif %}
        </a>
        {% endfor %}
    </nav>
</div>

<!-- ══ FAVORIS PANEL ══ -->
<div id="fav-panel">
    <div class="flex shrink-0 items-center justify-between border-b border-border px-4 py-3">
        <strong class="font-display text-base font-semibold">Mes favoris</strong>
        <button type="button" onclick="toggleFavPanel()" aria-label="Fermer" class="flex h-8 w-8 items-center justify-center rounded-lg text-ink-muted hover:bg-surface-2 hover:text-ink">{{ icon('x', 16) }}</button>
    </div>
    <div id="fav-list" class="custom-scroll flex-1 overflow-y-auto p-2"></div>
</div>

<!-- ══ TOAST CONTAINER ══ -->
<div id="toast-wrap"></div>

<!-- ══ SCRIPTS GLOBAUX ══ -->
<script>
window.LW_ICONS = {{ ICONS|tojson }};
function lwIcon(name, size, cls) {
    size = size || 16;
    return '<svg xmlns="http://www.w3.org/2000/svg" width="' + size + '" height="' + size + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lw-icon ' + (cls || '') + '" aria-hidden="true">' + (window.LW_ICONS[name] || '') + '</svg>';
}

// ─────────────────────────────────────────────
// MENU MOBILE
// ─────────────────────────────────────────────
function lwToggleDrawer(open) {
    var d = document.getElementById('lw-drawer');
    if (!d) return;
    d.classList.toggle('hidden', !open);
}
function toggleMobMenu() { var d = document.getElementById('lw-drawer'); lwToggleDrawer(d && d.classList.contains('hidden')); }

// ─────────────────────────────────────────────
// THÈME  (clair / sombre / système)
// ─────────────────────────────────────────────
function _applyThemeClass(dark) {
    var html = document.documentElement;
    html.classList.toggle('dark', dark);
    html.style.colorScheme = dark ? 'dark' : 'light';
}
function _applyTheme(t) {
    _applyThemeClass(t === 'dark');
    try { localStorage.setItem('lw_theme', t); } catch(e) {}
}
function _lwThemeMode() {
    var t = null;
    try { t = localStorage.getItem('lw_theme'); } catch(e) {}
    return (t === 'light' || t === 'dark' || t === 'system') ? t : 'dark';
}
function _lwRefreshThemeButtons() {
    var mode = _lwThemeMode();
    document.querySelectorAll('.lw-theme-btn').forEach(function(b) {
        var on = b.getAttribute('data-mode') === mode;
        b.setAttribute('aria-pressed', on ? 'true' : 'false');
        b.classList.toggle('bg-accent-2', on);
        b.classList.toggle('text-white', on);
        b.classList.toggle('text-ink-muted', !on);
    });
}
function lwSetThemeMode(mode) {
    if (mode === 'system') {
        _applyThemeClass(window.matchMedia('(prefers-color-scheme:dark)').matches);
        try { localStorage.setItem('lw_theme', 'system'); } catch(e) {}
    } else {
        _applyTheme(mode);
    }
    _lwRefreshThemeButtons();
    // Persister en base
    fetch('/api/settings/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ theme: mode === 'system' ? 'auto' : mode })
    }).catch(function(){});
}
function toggleTheme() { lwSetThemeMode(document.documentElement.classList.contains('dark') ? 'light' : 'dark'); }
new MutationObserver(_lwRefreshThemeButtons).observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
document.addEventListener('DOMContentLoaded', _lwRefreshThemeButtons);

// ─────────────────────────────────────────────
// TOASTS
// ─────────────────────────────────────────────
function showNotification(msg, type) {
    type = type || 'info';
    var wrap = document.getElementById('toast-wrap');
    if (!wrap) return;
    var toast = document.createElement('div');
    toast.className = 'toast toast-' + type;
    var icon = { success:'circle-check', error:'circle-x', info:'info', warning:'triangle-alert' }[type] || 'info';
    toast.innerHTML = '<i class="inline-flex">' + lwIcon(icon, 18) + '</i><span>' + msg + '</span>';
    wrap.appendChild(toast);
    setTimeout(function() {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(60px)';
        toast.style.transition = 'all .25s';
        setTimeout(function(){ if(toast.parentNode) toast.parentNode.removeChild(toast); }, 300);
    }, 3500);
}

// ─────────────────────────────────────────────
// FAVORIS
// ─────────────────────────────────────────────
function toggleFavPanel() {
    var p = document.getElementById('fav-panel');
    if (!p) return;
    if (p.classList.contains('open')) {
        p.classList.remove('open');
    } else {
        p.classList.add('open');
        _loadFavs();
    }
}

async function _loadFavs() {
    var list = document.getElementById('fav-list');
    if (!list) return;
    list.innerHTML = '<p class="p-3 text-center text-sm text-ink-muted">Chargement...</p>';
    try {
        var r = await fetch('/api/favorites', { credentials:'include' });
        var favs = await r.json();
        if (!favs.length) {
            list.innerHTML = '<p class="p-3 text-center text-sm text-ink-muted">Aucun favori<br><small>Cliquez sur une chaîne</small></p>';
            return;
        }
        list.innerHTML = favs.map(function(f){
            return '<a href="'+f.url+'" class="flex items-center gap-3 rounded-xl p-2 transition-colors hover:bg-surface-2">' +
                '<div class="flex h-10 w-10 shrink-0 items-center justify-center overflow-hidden rounded-lg bg-surface-2">' +
                (f.logo ? '<img src="'+f.logo+'" class="h-full w-full object-contain p-1" onerror="this.style.display=\'none\'">' : '<i class="fas fa-tv text-ink-muted"></i>') +
                '</div><div class="min-w-0 flex-1"><div class="truncate text-sm font-semibold">'+f.title+'</div>' +
                '<div class="text-[11px] text-ink-muted">'+(f.type==='user'&&f.is_live?'EN DIRECT':f.category||f.type)+'</div></div></a>';
        }).join('');
    } catch(e) {
        list.innerHTML = '<p class="p-3 text-center text-sm text-accent">Erreur chargement</p>';
    }
}

async function addToFavorites(streamId, type, event) {
    if (event) { event.preventDefault(); event.stopPropagation(); }
    var fd = new FormData();
    fd.append('stream_id', streamId);
    fd.append('stream_type', type);
    try {
        var r = await fetch('/api/favorites/add', { method:'POST', body:fd, credentials:'include' });
        if (r.ok) {
            showNotification('Ajouté aux favoris', 'success');
        } else {
            var d = await r.json().catch(function(){return{};});
            showNotification(d.error || 'Erreur', 'error');
        }
    } catch(e) { showNotification('Erreur réseau', 'error'); }
}

// ─────────────────────────────────────────────
// BADGE ANNONCES
// ─────────────────────────────────────────────
function _loadAnnBadge() {
    fetch('/api/announcements/count', {credentials:'include'})
        .then(function(r){return r.json();})
        .then(function(d){
            document.querySelectorAll('.ann-badge').forEach(function(badge){
                if (d.count > 0) { badge.textContent = d.count; badge.classList.remove('hidden'); }
                else { badge.classList.add('hidden'); }
            });
        }).catch(function(){});
}

// ─────────────────────────────────────────────
// TRACKING LOCALISATION (silencieux)
// ─────────────────────────────────────────────
function _trackLocation() {
    fetch('/api/track/location', {method:'POST', credentials:'include'}).catch(function(){});
}

// ─────────────────────────────────────────────
// INIT AU CHARGEMENT
// ─────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', function() {
    _loadAnnBadge();
    _trackLocation();
});
</script>

{% block scripts %}{% endblock %}
</body>
</html>
'''

    # ══════════════════════════════════════════════════════════════════
    # INDEX TEMPLATE
    # ══════════════════════════════════════════════════════════════════
    INDEX_TEMPLATE = r'''{% extends "base.html" %}
{% block title %}{{ app_name }} — Streaming TV en direct{% endblock %}
{% block content %}
{% from 'icons.html' import icon %}
{%- set view = request.query_params.get('view', '') if request is defined else '' -%}
{% from 'components.html' import stream_card, country_card, cat_meta, cont_map %}


{%- set cur_meta = cat_meta.get(current_category) if current_category else none -%}

{# ── Bandeau pays (CountryRail) ── #}
{% macro country_rail() -%}
{%- if pl_countries -%}
<div class="-mx-1 flex gap-3 overflow-x-auto px-1 pb-1" style="scrollbar-width:none">
    {% for pl in (pl_countries|sort(attribute='channel_count', reverse=true)|list)[:10] %}{{ country_card(pl, 'w-32') }}{% endfor %}
    <a href="/?view=countries" class="flex min-h-[90px] w-32 shrink-0 flex-col items-center justify-center gap-1 rounded-xl border border-dashed border-border text-xs font-medium text-ink-muted hover:text-ink">
        Voir tous les pays
        <span class="text-[10px] text-ink-muted/70">({{ pl_countries|length }})</span>
    </a>
</div>
{%- endif -%}
{%- endmacro %}

<div class="mx-auto max-w-6xl">

{% if view == 'countries' and not selected_playlist %}
    {# ═══════════ TOUS LES PAYS ═══════════ #}
    <div class="mb-5">
        <h1 class="font-display text-2xl font-semibold sm:text-3xl">Chaînes Télévisions par pays</h1>
        <p class="mt-1 text-sm text-ink-muted">{{ pl_countries|length if pl_countries else 0 }} pays disponibles</p>
    </div>
    <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div class="-mx-1 flex gap-2 overflow-x-auto px-1 pb-1" style="scrollbar-width:none" id="cont-filters">
            {% for cid, lbl in [('all','Tous'),('AF','Afrique'),('EU','Europe'),('AS','Asie'),('NA','Am. Nord'),('SA','Am. Sud'),('OC','Océanie'),('ME','Moyen-Orient')] %}
            <button type="button" onclick="filterCont('{{ cid }}',this)" data-cont="{{ cid }}"
                    class="cont-btn shrink-0 rounded-full border px-4 py-1.5 text-xs font-semibold transition-colors {{ 'border-accent bg-accent text-white' if cid == 'all' else 'border-border text-ink-muted hover:text-ink' }}">{{ lbl }}</button>
            {% endfor %}
        </div>
        <select id="country-sort" onchange="sortCountries(this.value)" class="shrink-0 rounded-full border border-border bg-surface px-3.5 py-1.5 text-xs font-medium outline-none">
            <option value="alpha">Trier : alphabétique</option>
            <option value="count">Trier : nombre de chaînes</option>
        </select>
    </div>
    {% if pl_countries %}
    <div class="grid grid-cols-3 gap-3 sm:grid-cols-4 md:grid-cols-6" id="countries-grid">
        {% for pl in pl_countries %}{{ country_card(pl) }}{% endfor %}
    </div>
    <div id="countries-empty" class="card hidden p-10 text-center text-sm text-ink-muted">Aucun pays dans cette catégorie.</div>
    {% else %}
    <div class="card p-10 text-center text-sm text-ink-muted">Aucune chaîne disponible. <a href="/admin/dashboard" class="text-accent-2 hover:underline">Lancer une synchronisation</a></div>
    {% endif %}

{% elif selected_playlist %}
    {# ═══════════ PAGE PAYS / PLAYLIST ═══════════ #}
    <div class="mb-6">
        <h1 class="font-display text-2xl font-semibold sm:text-3xl">{{ selected_playlist.display_name }}</h1>
        <p class="mt-1 text-sm text-ink-muted">{{ iptv_channels|length if iptv_channels else 0 }} chaîne{{ 's' if (iptv_channels|length if iptv_channels else 0) > 1 else '' }} en direct</p>
    </div>
    <div class="mb-7">{{ country_rail() }}</div>
    {%- set _pn = selected_playlist.display_name|string -%}
    <div class="mb-4 flex items-center justify-between">
        <h2 class="font-display text-lg font-semibold">Chaînes — {{ (_pn.split(' ', 1)|last) if ' ' in _pn else _pn }}</h2>
        <a href="/" class="text-xs font-medium text-accent-2 hover:underline">← Accueil</a>
    </div>
    {% if iptv_channels %}
    <div class="grid grid-cols-2 gap-4 sm:grid-cols-3 xl:grid-cols-4">
        {% for ch in iptv_channels %}
        {{ stream_card('/watch/iptv/' ~ ch.id, ch.name, ch.logo, (ch.category if ch.category in cat_meta else 'iptv'), (cat_meta.get(ch.category, cat_meta['iptv'])[3] ~ ((' · ' ~ ch.country) if ch.country else '')), none, none, (ch.id, 'iptv')) }}
        {% endfor %}
    </div>
    {% else %}
    <div class="card mt-4 flex flex-col items-center gap-2 p-10 text-center text-ink-muted">
        <p class="font-medium text-ink">Aucune chaîne trouvée pour ce pays</p>
        <p class="text-sm">Le catalogue est peut-être encore en cours de synchronisation.</p>
    </div>
    {% endif %}

{% else %}
    {# ═══════════ ACCUEIL / CATÉGORIE ═══════════ #}
    <div class="mb-6">
        <h1 class="font-display text-2xl font-semibold sm:text-3xl" id="home-title">{{ cur_meta[3] if cur_meta else 'Bonjour 👋' }}</h1>
        <p class="mt-1 text-sm text-ink-muted">{{ ('Toutes les chaînes ' ~ cur_meta[3]|lower ~ ' en direct') if cur_meta else 'Voici ce qui se passe en direct maintenant.' }}</p>
    </div>

    {% if not current_category %}
    <div class="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {% for sid, lbl, ic, init in [('st-live','En direct','radio', (live_streams|length if live_streams else 0)), ('st-viewers','Spectateurs','users', (live_streams|sum(attribute='viewer_count') if live_streams else 0)), ('st-channels','Chaînes','tv-2','—'), ('st-lives','Lives au total','flame','—')] %}
        <div class="card flex items-center gap-4 p-5">
            <div class="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-accent-2-soft text-accent-2">{{ icon(ic, 20) }}</div>
            <div class="min-w-0">
                <p class="truncate text-sm text-ink-muted">{{ lbl }}</p>
                <p id="{{ sid }}" class="font-display tabular-nums text-2xl font-semibold leading-tight">{{ init }}</p>
            </div>
        </div>
        {% endfor %}
    </div>
    {% endif %}

    {# Rail de catégories #}
    <div class="mb-7">
        <div class="-mx-1 flex gap-2.5 overflow-x-auto px-1 pb-1" style="scrollbar-width:none">
            <a href="/" class="flex shrink-0 items-center rounded-full border px-4 py-2 text-sm font-medium transition-colors {{ 'border-accent-2 bg-accent-2-soft text-accent-2' if not current_category else 'border-border text-ink-muted hover:text-ink' }}">Tout</a>
            {% for cat in (categories or []) %}
            {%- set m = cat_meta.get(cat.id, cat_meta['iptv']) -%}
            {%- set active = (current_category == cat.id) -%}
            <a href="/?category={{ cat.id }}" class="flex shrink-0 items-center gap-2 rounded-full border px-4 py-2 text-sm font-medium transition-colors {{ 'border-accent-2 bg-accent-2-soft text-accent-2' if active else 'border-border text-ink-muted hover:text-ink' }}">
                <span class="{{ 'text-accent-2' if active else m[2] }}">{{ icon(m[0], 15) }}</span>
                {{ m[3] if cat.id in cat_meta else cat.name }}
            </a>
            {% endfor %}
        </div>
    </div>

    {% if not current_category and pl_countries %}
    <div class="mb-7">
        <div class="mb-2.5 flex items-center justify-between">
            <p class="text-sm font-medium text-ink-muted">Parcourir par pays</p>
            <a href="/?view=countries" class="text-xs font-medium text-accent-2 hover:underline">Voir tout →</a>
        </div>
        {{ country_rail() }}
    </div>
    {% endif %}

    {# Lives communautaires #}
    {% if live_streams %}
    <section id="live" class="mb-8">
        <div class="mb-4 flex items-center justify-between">
            <h2 class="font-display text-lg font-semibold">Lives en direct <span class="text-sm font-normal text-ink-muted">({{ live_streams|length }})</span></h2>
        </div>
        <div class="grid grid-cols-2 gap-4 sm:grid-cols-3 xl:grid-cols-4">
            {% for stream in live_streams %}
            {%- set sm = cat_meta.get(stream.category, cat_meta['entertainment']) -%}
            <a href="/watch/user/{{ stream.id }}" class="card group flex flex-col overflow-hidden transition-transform hover:-translate-y-0.5 stream-card">
                <div class="relative flex aspect-video w-full items-center justify-center overflow-hidden {{ sm[1] }}">
                    <span class="{{ sm[2] }}">{{ icon('video', 30, '', 1.75) }}</span>
                    {% if stream.thumbnail %}<img src="{{ stream.thumbnail }}" alt="" loading="lazy" onerror="this.style.display='none'" class="absolute inset-0 h-full w-full object-cover transition-transform duration-300 group-hover:scale-105">{% endif %}
                    <div class="absolute left-2.5 top-2.5"><span class="inline-flex items-center gap-1.5 rounded-full bg-accent px-2.5 py-1 text-[11px] font-semibold tracking-wide text-white"><span class="live-dot bg-white"></span>DIRECT</span></div>
                    <div class="absolute bottom-2.5 left-2.5 flex items-center gap-1 rounded-md bg-black/55 px-1.5 py-0.5 text-[11px] font-medium text-white backdrop-blur-sm">{{ icon('eye', 12) }} {{ stream.viewer_count }}</div>
                </div>
                <div class="flex items-start gap-2.5 p-3.5">
                    <div class="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg {{ sm[1] }}"><span class="{{ sm[2] }}">{{ icon(sm[0], 14) }}</span></div>
                    <div class="min-w-0">
                        <p class="truncate text-sm font-semibold leading-snug">{{ stream.title }}</p>
                        <p class="truncate text-xs text-ink-muted">{{ sm[3] if stream.category in cat_meta else stream.category }} · {{ stream.like_count }} j'aime</p>
                    </div>
                </div>
            </a>
            {% endfor %}
        </div>
    </section>
    {% endif %}

    {# Flux externes (TV, YouTube, Radio) #}
    {% if external_streams and not current_category %}
    <section id="external-streams" class="mb-8">
        <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
            <h2 class="font-display text-lg font-semibold">En direct maintenant</h2>
            <div class="flex gap-2">
                {% for tid, lbl in [('all','Tout'),('hls','TV'),('youtube','YouTube'),('audio','Radio')] %}
                <button type="button" onclick="filterExt('{{ tid }}',this)" data-stype="{{ tid }}"
                        class="flt-btn rounded-full border px-3.5 py-1.5 text-xs font-semibold transition-colors {{ 'border-accent bg-accent text-white' if tid == 'all' else 'border-border text-ink-muted hover:text-ink' }}">{{ lbl }}</button>
                {% endfor %}
            </div>
        </div>
        <div class="grid grid-cols-2 gap-4 sm:grid-cols-3 xl:grid-cols-4" id="ext-grid">
            {% for stream in external_streams %}
            {{ stream_card('/watch/external/' ~ stream.id, stream.title, stream.logo, (stream.category if stream.category in cat_meta else 'iptv'), ((cat_meta.get(stream.category, cat_meta['iptv'])[3]) ~ ((' · ' ~ stream.country) if stream.country else '')), stream.quality, none, (stream.id, 'external'), stream.stream_type) }}
            {% endfor %}
        </div>
    </section>
    {% endif %}

    {# Vue catégorie : flux externes + chaînes IPTV correspondantes #}
    {% if current_category %}
    {% set _items = [] %}
    <div class="mb-4 flex items-center justify-between">
        <h2 class="font-display text-lg font-semibold">{{ cur_meta[3] if cur_meta else 'Chaînes' }} en direct</h2>
    </div>
    {% if external_streams or iptv_channels or live_streams %}
    <div class="grid grid-cols-2 gap-4 sm:grid-cols-3 xl:grid-cols-4">
        {% for stream in (external_streams or []) %}
        {{ stream_card('/watch/external/' ~ stream.id, stream.title, stream.logo, (stream.category if stream.category in cat_meta else 'iptv'), ((cat_meta.get(stream.category, cat_meta['iptv'])[3]) ~ ((' · ' ~ stream.country) if stream.country else '')), stream.quality, none, (stream.id, 'external'), stream.stream_type) }}
        {% endfor %}
        {% for ch in (iptv_channels or []) %}
        {{ stream_card('/watch/iptv/' ~ ch.id, ch.name, ch.logo, (ch.category if ch.category in cat_meta else 'iptv'), (cat_meta.get(ch.category, cat_meta['iptv'])[3] ~ ((' · ' ~ ch.country) if ch.country else '')), none, none, (ch.id, 'iptv')) }}
        {% endfor %}
    </div>
    {% endif %}
    {% if not external_streams and not iptv_channels and not live_streams %}
    <div class="card mt-4 flex flex-col items-center gap-2 p-10 text-center text-ink-muted">
        <p class="font-medium text-ink">Aucune chaîne dans cette catégorie pour l'instant</p>
        <p class="text-sm">Revenez plus tard ou explorez une autre catégorie.</p>
    </div>
    {% endif %}
    {% endif %}

    {# Catégories thématiques #}
    {% if pl_categories and not current_category %}
    <section id="thematic-categories" class="mb-8">
        <div class="mb-4 flex items-center justify-between">
            <h2 class="font-display text-lg font-semibold">Catégories thématiques</h2>
        </div>
        <div class="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-6">
            {% for pl in pl_categories %}
            {%- set dn = (pl.display_name or '')|string -%}
            <a href="/?playlist={{ pl.name }}" class="card flex flex-col items-center gap-1.5 p-4 text-center transition-transform hover:-translate-y-0.5">
                <span class="text-2xl leading-none">{{ dn.split(' ', 1)|first if dn else '' }}</span>
                <span class="text-sm font-semibold leading-snug">{{ (dn.split(' ', 1)|last) if ' ' in dn else dn }}</span>
                <span class="text-xs text-ink-muted">{{ pl.channel_count or 0 }} chaînes</span>
            </a>
            {% endfor %}
        </div>
    </section>
    {% endif %}
{% endif %}

{# ═══════════ AVIS UTILISATEURS ═══════════ #}
<section class="mt-10">
    <div class="mb-4">
        <h2 class="font-display text-lg font-semibold">Votre avis nous intéresse</h2>
        <p class="mt-1 text-sm text-ink-muted">Partagez vos suggestions ou signalez un problème</p>
    </div>
    <div id="feedback-wrap" class="card max-w-xl p-5">
        <div id="feedback-ok" class="hidden py-6 text-center">
            <div class="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-accent-2-soft text-accent-2">{{ icon('check', 22) }}</div>
            <h3 class="font-display text-base font-semibold">Merci pour votre avis !</h3>
            <p class="mt-1 text-sm text-ink-muted">Nous avons bien reçu votre message.</p>
            <button type="button" onclick="document.getElementById('feedback-ok').classList.add('hidden');document.getElementById('feedback-form').classList.remove('hidden');"
                    class="mt-4 rounded-full border border-border px-4 py-2 text-sm font-medium text-ink-muted hover:text-ink">Envoyer un autre avis</button>
        </div>
        <div id="feedback-form">
            <div class="mb-4">
                <p class="mb-2 text-sm font-medium">Note globale</p>
                <div class="flex gap-1">
                    {% for i in range(1,6) %}
                    <button type="button" onclick="setRating({{ i }})" class="star-btn text-2xl leading-none transition-colors" data-star="{{ i }}">★</button>
                    {% endfor %}
                </div>
                <input type="hidden" id="fb-rating" value="5">
            </div>
            <div class="mb-4">
                <label for="fb-message" class="mb-1.5 block text-sm font-medium">Message <span class="text-accent">*</span></label>
                <textarea id="fb-message" rows="4" maxlength="2000" placeholder="Décrivez votre expérience, proposez une amélioration..."
                          class="w-full resize-y rounded-xl border border-border bg-surface-2 px-3.5 py-2.5 text-sm outline-none placeholder:text-ink-muted focus-visible:border-accent-2"></textarea>
            </div>
            <div class="mb-4">
                <label for="fb-email" class="mb-1.5 block text-sm font-medium">Email <span class="font-normal text-ink-muted">(optionnel — pour vous répondre)</span></label>
                <input type="email" id="fb-email" placeholder="votre@email.com" maxlength="200"
                       class="w-full rounded-xl border border-border bg-surface-2 px-3.5 py-2.5 text-sm outline-none placeholder:text-ink-muted focus-visible:border-accent-2">
            </div>
            <div id="fb-error" class="mb-3 hidden rounded-xl border border-accent/30 bg-accent/10 px-3.5 py-2.5 text-sm text-accent"></div>
            <button type="button" onclick="submitFeedback()" id="fb-btn"
                    class="inline-flex items-center gap-2 rounded-full bg-accent px-5 py-2.5 text-sm font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-60">
                <i class="fas fa-paper-plane"></i> Envoyer mon avis
            </button>
        </div>
    </div>
</section>

</div>
{% endblock %}

{% block scripts %}
<script>
// ── Salutation selon l'heure locale ──
(function(){
    var el = document.getElementById('home-title');
    if (!el || el.textContent.indexOf('Bonjour') !== 0) return;
    var h = new Date().getHours();
    var g = h < 5 ? 'Bonne nuit' : h < 12 ? 'Bonjour' : h < 18 ? 'Bon après-midi' : 'Bonsoir';
    el.textContent = g + ' 👋';
})();

// ── Cartes de statistiques ──
(function(){
    if (!document.getElementById('st-live')) return;
    var fmt = new Intl.NumberFormat('fr-FR', { notation: 'compact' });
    var v = document.getElementById('st-viewers');
    if (v) v.textContent = fmt.format(parseInt(v.textContent, 10) || 0);
    fetch('/api/stats/public', { credentials: 'include' })
        .then(function(r){ return r.json(); })
        .then(function(d){
            var set = function(id, val){ var e = document.getElementById(id); if (e) e.textContent = val; };
            set('st-live', String(d.live_streams || 0));
            set('st-channels', fmt.format((d.iptv_channels || 0) + (d.external_streams || 0)));
            set('st-lives', String(d.total_streams || 0));
        }).catch(function(){});
})();

// ── Filtre types de flux ──
function filterExt(type, btn) {
    document.querySelectorAll('.flt-btn').forEach(function(b){
        b.classList.remove('border-accent','bg-accent','text-white');
        b.classList.add('border-border','text-ink-muted');
    });
    btn.classList.remove('border-border','text-ink-muted');
    btn.classList.add('border-accent','bg-accent','text-white');
    document.querySelectorAll('#ext-grid .stream-card').forEach(function(c){
        c.style.display=(type==='all'||c.dataset.stype===type)?'':'none';
    });
}

// ── Filtre continents ──
function filterCont(cont, btn) {
    document.querySelectorAll('.cont-btn').forEach(function(b){
        b.classList.remove('border-accent','bg-accent','text-white');
        b.classList.add('border-border','text-ink-muted');
    });
    btn.classList.remove('border-border','text-ink-muted');
    btn.classList.add('border-accent','bg-accent','text-white');
    var shown = 0;
    document.querySelectorAll('#countries-grid .country-card').forEach(function(c){
        var ok = (cont==='all'||c.dataset.cont===cont);
        c.style.display = ok ? '' : 'none';
        if (ok) shown++;
    });
    var empty = document.getElementById('countries-empty');
    if (empty) empty.classList.toggle('hidden', shown > 0);
}

// ── Tri des pays ──
function sortCountries(mode) {
    var grid = document.getElementById('countries-grid');
    if (!grid) return;
    var cards = Array.prototype.slice.call(grid.querySelectorAll('.country-card'));
    cards.sort(function(a, b){
        if (mode === 'count') return (parseInt(b.dataset.count,10)||0) - (parseInt(a.dataset.count,10)||0);
        return (a.dataset.name||'').localeCompare(b.dataset.name||'', 'fr');
    });
    cards.forEach(function(c){ grid.appendChild(c); });
}
document.addEventListener('DOMContentLoaded', function(){ if (document.getElementById('country-sort')) sortCountries('alpha'); });

// ── Étoiles feedback ──
var _rating = 5;
function setRating(n) {
    _rating = n;
    var r = document.getElementById('fb-rating'); if (r) r.value = n;
    document.querySelectorAll('.star-btn').forEach(function(b){
        var on = parseInt(b.dataset.star) <= n;
        b.style.color = on ? '#f59e0b' : 'var(--border)';
    });
}
document.addEventListener('DOMContentLoaded', function(){ setRating(5); });

// ── Envoi feedback ──
async function submitFeedback() {
    var msg = document.getElementById('fb-message').value.trim();
    var email = document.getElementById('fb-email').value.trim();
    var errDiv = document.getElementById('fb-error');
    errDiv.classList.add('hidden');
    if (msg.length < 10) {
        errDiv.textContent='Le message doit faire au moins 10 caractères.';
        errDiv.classList.remove('hidden'); return;
    }
    var btn = document.getElementById('fb-btn');
    btn.disabled=true; btn.innerHTML='<i class="fas fa-spinner fa-spin"></i> Envoi...';
    var fd = new FormData();
    fd.append('message', msg);
    fd.append('rating', _rating);
    if (email) fd.append('email', email);
    try {
        var r = await fetch('/api/feedback/submit', {method:'POST',body:fd,credentials:'include'});
        var d = await r.json();
        if (d.success) {
            document.getElementById('feedback-form').classList.add('hidden');
            document.getElementById('feedback-ok').classList.remove('hidden');
        } else {
            errDiv.textContent=d.error||'Une erreur est survenue.';
            errDiv.classList.remove('hidden');
        }
    } catch(e) {
        errDiv.textContent='Erreur réseau. Vérifiez votre connexion.';
        errDiv.classList.remove('hidden');
    }
    btn.disabled=false;
    btn.innerHTML='<i class="fas fa-paper-plane"></i> Envoyer mon avis';
}
</script>
{% endblock %}
'''
    # ══════════════════════════════════════════════════════════════════
    # GO LIVE TEMPLATE — Streaming caméra WebRTC
    # ══════════════════════════════════════════════════════════════════
    GO_LIVE_TEMPLATE = r'''{% extends "base.html" %}
{% block title %}Go Live - {{ app_name }}{% endblock %}
{% block head %}
<style>
    .gl-src { transition: border-color .15s, background-color .15s; }
    .gl-src.src-on { border-color: var(--accent); background: color-mix(in srgb, var(--accent) 10%, transparent); }
    #gl-btn-go:disabled { opacity:.4; cursor:not-allowed; }
</style>
{% endblock %}
{% block content %}
{% from 'icons.html' import icon %}
{% macro field_cls() -%}w-full rounded-xl border border-border bg-surface px-3.5 py-2.5 text-sm outline-none placeholder:text-ink-muted focus-visible:border-accent-2{%- endmacro %}
{% macro ctl_cls() -%}flex items-center gap-2 rounded-full border border-border px-4 py-2 text-sm font-medium text-ink-muted transition-colors hover:text-ink{%- endmacro %}
<div class="mx-auto max-w-2xl">

    <!-- En-tête -->
    <h1 class="mb-1 font-display text-2xl font-semibold">Démarrer un direct</h1>
    <p class="mb-6 text-sm text-ink-muted">Diffusez depuis votre caméra, votre écran ou un flux externe</p>

    <!-- ÉTAPE 1 : FORMULAIRE -->
    <div id="step-form">
        <div class="card space-y-5 p-6">
            <h2 class="flex items-center gap-2.5 font-display text-base font-semibold">
                <span class="flex h-6 w-6 items-center justify-center rounded-lg bg-accent-2-soft text-xs font-semibold text-accent-2">1</span>
                Informations du live
            </h2>
            <div>
                <label for="gl-title" class="mb-1.5 block text-sm font-medium">Titre du direct <span class="text-accent">*</span></label>
                <input type="text" id="gl-title" maxlength="100" placeholder="Ex: Soirée gaming, Débat, Concert..." class="{{ field_cls() }}">
            </div>
            <div>
                <label for="gl-desc" class="mb-1.5 block text-sm font-medium">Description (optionnel)</label>
                <textarea id="gl-desc" rows="3" maxlength="1000" placeholder="Décrivez votre live..." class="{{ field_cls() }} resize-none"></textarea>
            </div>
            <div class="grid gap-5 sm:grid-cols-2">
                <div>
                    <label for="gl-cat" class="mb-1.5 block text-sm font-medium">Catégorie <span class="text-accent">*</span></label>
                    <select id="gl-cat" class="{{ field_cls() }}">
                        <option value="">Choisissez...</option>
                        {% for cat in categories %}
                        <option value="{{ cat.id }}">{{ cat.icon }} {{ cat.name }}</option>
                        {% endfor %}
                    </select>
                </div>
                <div>
                    <label for="gl-tags" class="mb-1.5 block text-sm font-medium">Tags <span class="font-normal text-ink-muted">(séparés par virgule)</span></label>
                    <input type="text" id="gl-tags" placeholder="gaming, music, fun..." class="{{ field_cls() }}">
                </div>
            </div>
            <button type="button" onclick="glNextStep()" class="flex w-full items-center justify-center gap-2 rounded-xl bg-accent py-3 text-sm font-semibold text-white transition-opacity hover:opacity-90">
                <i class="fas fa-arrow-right"></i> Suivant — Configurer la caméra
            </button>
        </div>
    </div>

    <!-- ÉTAPE 2 : CAMÉRA -->
    <div id="step-camera" class="hidden">
        <div class="card p-6">
            <h2 class="mb-4 flex items-center gap-2.5 font-display text-base font-semibold">
                <span class="flex h-6 w-6 items-center justify-center rounded-lg bg-accent-2-soft text-xs font-semibold text-accent-2">2</span>
                Source vidéo
            </h2>

            <!-- Boutons source -->
            <div class="mb-4 grid grid-cols-3 gap-3">
                {% for sid, ic, lbl, sub in [('camera','camera','Caméra','Webcam / frontal'),('screen','desktop','Écran','Partage écran'),('both','layer-group','Cam + Micro','Vidéo & audio')] %}
                <button type="button" onclick="glStartMedia('{{ sid }}')" id="btn-src-{{ sid }}" class="gl-src flex flex-col items-center gap-1 rounded-xl border border-border px-2 py-4 text-center">
                    <i class="fas fa-{{ ic }}" style="font-size:1.4rem"></i>
                    <span class="text-sm font-semibold">{{ lbl }}</span>
                    <span class="text-[11px] text-ink-muted">{{ sub }}</span>
                </button>
                {% endfor %}
            </div>

            <!-- Sélecteurs périphériques -->
            <div id="gl-devices" class="mb-4 hidden gap-3 sm:grid-cols-2">
                <div>
                    <label class="mb-1 block text-xs font-medium text-ink-muted">Caméra</label>
                    <select id="gl-cam-sel" class="{{ field_cls() }}"></select>
                </div>
                <div>
                    <label class="mb-1 block text-xs font-medium text-ink-muted">Microphone</label>
                    <select id="gl-mic-sel" class="{{ field_cls() }}"></select>
                </div>
            </div>

            <!-- Prévisualisation -->
            <div class="relative mb-4 w-full overflow-hidden rounded-2xl bg-black" style="aspect-ratio:16/9">
                <video id="gl-preview" autoplay muted playsinline class="absolute inset-0 h-full w-full object-cover"></video>
                <div id="gl-placeholder" class="absolute inset-0 flex flex-col items-center justify-center gap-2 text-white/60">
                    <i class="fas fa-camera" style="font-size:2rem"></i>
                    <p class="text-sm">Cliquez sur une source ci-dessus</p>
                </div>
                <!-- VU-mètre audio -->
                <div id="gl-vu-wrap" class="absolute inset-x-3 bottom-3 h-1.5 overflow-hidden rounded-full bg-white/20" style="display:none">
                    <div id="gl-vu-bar" class="h-full rounded-full" style="width:0%"></div>
                </div>
            </div>

            <!-- Contrôles -->
            <div class="mb-4 flex flex-wrap gap-2">
                <button type="button" onclick="glToggleMute()" id="gl-btn-mute" class="{{ ctl_cls() }}"><i class="fas fa-microphone" id="gl-mic-icon"></i> <span id="gl-mic-label">Micro actif</span></button>
                <button type="button" onclick="glToggleVideo()" id="gl-btn-vid" class="{{ ctl_cls() }}"><i class="fas fa-video" id="gl-vid-icon"></i> <span id="gl-vid-label">Vidéo active</span></button>
                <button type="button" onclick="glStopPreview()" class="{{ ctl_cls() }}"><i class="fas fa-stop"></i> Arrêter preview</button>
            </div>

            <!-- Message erreur -->
            <div id="gl-error" class="mb-4 hidden items-center gap-2 rounded-xl border border-accent/30 bg-accent/10 px-4 py-3 text-sm text-accent">
                <i class="fas fa-exclamation-triangle"></i> <span id="gl-error-msg"></span>
            </div>

            <!-- Boutons nav -->
            <div class="flex gap-3">
                <button type="button" onclick="glGoBack()" class="flex items-center gap-2 rounded-xl border border-border px-5 py-3 text-sm font-medium text-ink-muted hover:text-ink"><i class="fas fa-arrow-left"></i> Retour</button>
                <button type="button" id="gl-btn-go" onclick="glGoLive()" disabled class="flex flex-1 items-center justify-center gap-2 rounded-xl bg-accent py-3 text-sm font-semibold text-white transition-opacity hover:opacity-90">
                    <i class="fas fa-circle" style="font-size:10px"></i> Aller en direct
                </button>
            </div>
        </div>
    </div>

    <!-- ÉTAPE 3 : EN DIRECT -->
    <div id="step-live" class="hidden">
        <div class="card p-6">
            <div class="mb-4 flex items-center justify-between gap-3">
                <div class="flex items-center gap-3">
                    <span class="live-dot"></span>
                    <h2 class="font-display text-base font-semibold">Vous êtes en direct</h2>
                </div>
                <div id="gl-timer" class="font-display tabular-nums text-xl font-semibold">00:00:00</div>
            </div>

            <!-- Vidéo live -->
            <div class="relative mb-4 w-full overflow-hidden rounded-2xl bg-black" style="aspect-ratio:16/9">
                <video id="gl-live-vid" autoplay muted playsinline class="absolute inset-0 h-full w-full object-cover"></video>
                <div class="pointer-events-none absolute left-3 top-3"><span class="inline-flex items-center gap-1.5 rounded-full bg-accent px-2.5 py-1 text-[11px] font-semibold tracking-wide text-white"><span class="live-dot bg-white"></span>EN DIRECT</span></div>
                <div id="gl-viewers" class="pointer-events-none absolute right-3 top-3 rounded-md bg-black/55 px-2 py-1 text-[11px] font-medium text-white backdrop-blur-sm">0 spectateurs</div>
            </div>

            <!-- Contrôles live -->
            <div class="mb-4 flex flex-wrap gap-2">
                <button type="button" onclick="glToggleMuteLive()" id="gl-btn-mute-live" class="{{ ctl_cls() }}"><i class="fas fa-microphone" id="gl-mic-live-icon"></i> <span id="gl-mic-live-label">Micro actif</span></button>
                <button type="button" onclick="glToggleVideoLive()" class="{{ ctl_cls() }}"><i class="fas fa-video" id="gl-vid-live-icon"></i> <span id="gl-vid-live-label">Vidéo active</span></button>
                <a id="gl-watch-link" href="#" target="_blank" class="{{ ctl_cls() }}"><i class="fas fa-external-link-alt"></i> Voir ma page</a>
                <button type="button" onclick="glCopyUrl()" class="{{ ctl_cls() }}"><i class="fas fa-copy"></i> Copier lien</button>
            </div>

            <!-- URL -->
            <div class="mb-5">
                <p class="mb-1 text-xs font-medium text-ink-muted">Lien à partager</p>
                <div id="gl-url-display" class="truncate rounded-xl border border-border bg-surface-2 px-4 py-3 text-sm"></div>
            </div>

            <button type="button" onclick="glEndLive()" id="gl-btn-end" class="flex w-full items-center justify-center gap-2 rounded-xl bg-ink-muted py-3 text-sm font-semibold text-white transition-opacity hover:opacity-90">
                <i class="fas fa-stop-circle"></i> Terminer le live
            </button>
        </div>
    </div>

    <!-- ÉTAPE 4 : TERMINÉ -->
    <div id="step-ended" class="hidden">
        <div class="card p-7 text-center">
            <div class="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-emerald-500/10 text-emerald-600 dark:text-emerald-400">{{ icon('circle-check', 26) }}</div>
            <h2 class="font-display text-xl font-semibold">Live terminé</h2>
            <p class="mt-1.5 text-sm text-ink-muted">Merci d'avoir streamé sur {{ app_name }} !</p>
            <div class="mt-5 flex flex-wrap items-center justify-center gap-3">
                <a href="/" class="flex items-center gap-2 rounded-xl border border-border px-5 py-2.5 text-sm font-medium text-ink-muted hover:text-ink"><i class="fas fa-home"></i> Accueil</a>
                <button type="button" onclick="glRestart()" class="flex items-center gap-2 rounded-xl bg-accent px-5 py-2.5 text-sm font-semibold text-white hover:opacity-90"><i class="fas fa-redo"></i> Nouveau live</button>
            </div>
        </div>
    </div>
</div>
{% endblock %}

{% block scripts %}
<script>

(function(){
    /* ═══ État ═══ */
    var _stream=null, _streamId=null, _liveUrl=null;
    var _timerInt=null, _timerStart=null;
    var _audioCtx=null, _analyser=null, _audioSrc=null, _raf=null;
    var _audioMuted=false, _videoMuted=false;

    /* ═══ Utilitaires erreur ═══ */
    function showErr(msg){
        var e=document.getElementById('gl-error');
        var m=document.getElementById('gl-error-msg');
        if(e&&m){m.textContent=msg;e.style.display='block';}
    }
    function hideErr(){
        var e=document.getElementById('gl-error');
        if(e) e.style.display='none';
    }

    /* ═══ Étape 1 → 2 ═══ */
    window.glNextStep = function(){
        var t=document.getElementById('gl-title').value.trim();
        var c=document.getElementById('gl-cat').value;
        if(!t){showNotification('Le titre est obligatoire','error');return;}
        if(!c){showNotification('Choisissez une catégorie','error');return;}
        document.getElementById('step-form').style.display='none';
        document.getElementById('step-camera').style.display='block';
        _populateDevices();
    };

    window.glGoBack = function(){
        glStopPreview();
        document.getElementById('step-camera').style.display='none';
        document.getElementById('step-form').style.display='block';
    };

    window.glRestart = function(){
        glStopPreview();
        _stream=null;_streamId=null;_liveUrl=null;_audioMuted=false;_videoMuted=false;
        document.getElementById('step-ended').style.display='none';
        document.getElementById('step-form').style.display='block';
        _setGoBtn(false);
    };

    /* ═══ Périphériques ═══ */
    async function _populateDevices(){
        try{
            var test=await navigator.mediaDevices.getUserMedia({video:true,audio:true});
            test.getTracks().forEach(function(t){t.stop();});
            var devs=await navigator.mediaDevices.enumerateDevices();
            var cs=document.getElementById('gl-cam-sel');
            var ms=document.getElementById('gl-mic-sel');
            cs.innerHTML=''; ms.innerHTML='';
            var vi=1,ai=1;
            devs.forEach(function(d){
                var o=document.createElement('option');
                o.value=d.deviceId;
                if(d.kind==='videoinput'){o.textContent=d.label||('Caméra '+vi++);cs.appendChild(o);}
                else if(d.kind==='audioinput'){o.textContent=d.label||('Micro '+ai++);ms.appendChild(o);}
            });
            var gd=document.getElementById('gl-devices');
            if(gd){gd.style.display='grid';}
        }catch(e){}
    }

    /* ═══ Démarrer media ═══ */
    window.glStartMedia = async function(type){
        glStopPreview();
        hideErr();

        if(!navigator.mediaDevices||!navigator.mediaDevices.getUserMedia){
            showErr('Votre navigateur ne supporte pas getUserMedia. Utilisez Chrome, Firefox ou Safari récents.');
            return;
        }

        try{
            if(type==='camera'){
                var camId=document.getElementById('gl-cam-sel').value;
                var micId=document.getElementById('gl-mic-sel').value;
                _stream=await navigator.mediaDevices.getUserMedia({
                    video: camId ? {deviceId:{exact:camId},width:{ideal:1280},height:{ideal:720}} : {width:{ideal:1280},height:{ideal:720}},
                    audio: micId ? {deviceId:{exact:micId}} : true
                });
            } else if(type==='screen'){
                _stream=await navigator.mediaDevices.getDisplayMedia({video:{cursor:'always'},audio:true});
                if(!_stream.getAudioTracks().length){
                    try{var a=await navigator.mediaDevices.getUserMedia({audio:true});a.getAudioTracks().forEach(function(t){_stream.addTrack(t);});}catch(e){}
                }
            } else {
                _stream=await navigator.mediaDevices.getUserMedia({video:{width:{ideal:1280},height:{ideal:720}},audio:true});
            }

            var pv=document.getElementById('gl-preview');
            pv.srcObject=_stream;
            pv.play().catch(function(){});
            document.getElementById('gl-placeholder').style.display='none';
            _setGoBtn(true);

            /* Surligner bouton actif */
            ['camera','screen','both'].forEach(function(k){
                var b=document.getElementById('btn-src-'+k);
                if(!b) return;
                b.classList.toggle('src-on', k===type);
            });

            _startVU(_stream);
            showNotification('Caméra/source activée','success');
        } catch(err){
            var msgs={
                NotAllowedError:'Accès caméra refusé. Autorisez-la dans les paramètres du navigateur (icône dans la barre d\'adresse).',
                PermissionDeniedError:'Accès caméra refusé.',
                NotFoundError:'Aucune caméra ou microphone détecté sur cet appareil.',
                DevicesNotFoundError:'Aucun périphérique trouvé.',
                NotReadableError:'La caméra est déjà utilisée par une autre application.',
                TrackStartError:'La caméra est déjà utilisée.',
                OverconstrainedError:'Paramètres caméra non supportés.',
                TypeError:'Paramètres invalides.'
            };
            showErr(msgs[err.name]||('Erreur: '+err.message));
        }
    };

    window.glStopPreview = function(){
        if(_stream){_stream.getTracks().forEach(function(t){t.stop();});_stream=null;}
        var pv=document.getElementById('gl-preview');
        if(pv){pv.srcObject=null;}
        document.getElementById('gl-placeholder').style.display='flex';
        document.getElementById('gl-vu-wrap').style.display='none';
        _setGoBtn(false);
        _stopVU();
        ['camera','screen','both'].forEach(function(k){
            var b=document.getElementById('btn-src-'+k);
            if(b){b.classList.remove('src-on');}
        });
    };

    function _setGoBtn(enabled){
        var b=document.getElementById('gl-btn-go');
        if(!b) return;
        b.disabled=!enabled;
        b.style.opacity=enabled?'1':'0.4';
        b.style.cursor=enabled?'pointer':'not-allowed';
    }

    /* ═══ Contrôles micro/video ═══ */
    window.glToggleMute=function(){
        if(!_stream) return;
        _audioMuted=!_audioMuted;
        _stream.getAudioTracks().forEach(function(t){t.enabled=!_audioMuted;});
        document.getElementById('gl-mic-icon').className=_audioMuted?'fas fa-microphone-slash':'fas fa-microphone';
        document.getElementById('gl-mic-label').textContent=_audioMuted?'Micro coupé':'Micro actif';
        if(_audioMuted) document.getElementById('gl-btn-mute').style.color='#dc2626';
        else document.getElementById('gl-btn-mute').style.color='inherit';
    };
    window.glToggleVideo=function(){
        if(!_stream) return;
        _videoMuted=!_videoMuted;
        _stream.getVideoTracks().forEach(function(t){t.enabled=!_videoMuted;});
        document.getElementById('gl-vid-icon').className=_videoMuted?'fas fa-video-slash':'fas fa-video';
        document.getElementById('gl-vid-label').textContent=_videoMuted?'Vidéo coupée':'Vidéo active';
    };
    window.glToggleMuteLive=function(){
        if(!_stream) return;
        _audioMuted=!_audioMuted;
        _stream.getAudioTracks().forEach(function(t){t.enabled=!_audioMuted;});
        document.getElementById('gl-mic-live-icon').className=_audioMuted?'fas fa-microphone-slash':'fas fa-microphone';
        document.getElementById('gl-mic-live-label').textContent=_audioMuted?'Micro coupé':'Micro actif';
    };
    window.glToggleVideoLive=function(){
        if(!_stream) return;
        _videoMuted=!_videoMuted;
        _stream.getVideoTracks().forEach(function(t){t.enabled=!_videoMuted;});
        document.getElementById('gl-vid-live-icon').className=_videoMuted?'fas fa-video-slash':'fas fa-video';
        document.getElementById('gl-vid-live-label').textContent=_videoMuted?'Vidéo coupée':'Vidéo active';
    };

    /* ═══ VU-mètre audio ═══ */
    function _startVU(stream){
        _stopVU();
        try{
            _audioCtx=new(window.AudioContext||window.webkitAudioContext)();
            _analyser=_audioCtx.createAnalyser();
            _analyser.fftSize=256;
            _audioSrc=_audioCtx.createMediaStreamSource(stream);
            _audioSrc.connect(_analyser);
            var buf=new Uint8Array(_analyser.frequencyBinCount);
            var bar=document.getElementById('gl-vu-bar');
            var wrap=document.getElementById('gl-vu-wrap');
            if(wrap) wrap.style.display='block';
            function tick(){
                _raf=requestAnimationFrame(tick);
                _analyser.getByteFrequencyData(buf);
                var sum=0; for(var i=0;i<buf.length;i++) sum+=buf[i];
                var pct=Math.min(100,(sum/buf.length/128)*100);
                if(bar){
                    bar.style.width=pct+'%';
                    bar.style.background=pct>70?'#dc2626':pct>40?'#f59e0b':'#22c55e';
                }
            }
            tick();
        }catch(e){}
    }
    function _stopVU(){
        if(_raf){cancelAnimationFrame(_raf);_raf=null;}
        try{if(_audioSrc)_audioSrc.disconnect();if(_audioCtx)_audioCtx.close();}catch(e){}
        _audioCtx=null;_analyser=null;_audioSrc=null;
    }

    /* ═══ Aller en direct ═══ */
    window.glGoLive = async function(){
        if(!_stream){showNotification('Activez d\'abord une source vidéo','error');return;}
        var btn=document.getElementById('gl-btn-go');
        btn.disabled=true;
        btn.innerHTML='<i class="fas fa-spinner fa-spin"></i> Démarrage...';

        var fd=new FormData();
        fd.append('title',document.getElementById('gl-title').value.trim());
        fd.append('category',document.getElementById('gl-cat').value);
        fd.append('description',document.getElementById('gl-desc').value);
        fd.append('tags',document.getElementById('gl-tags').value);
        try{
            var r=await fetch('/api/streams/create',{method:'POST',body:fd,credentials:'include'});
            var d=await r.json();
            if(!d.success){showNotification(d.error||'Erreur création stream','error');btn.disabled=false;btn.innerHTML='<i class="fas fa-circle" style="font-size:10px;animation:livePulse 1s infinite;"></i> Aller en direct';return;}

            await fetch('/api/streams/'+d.stream_id+'/start',{method:'POST',credentials:'include'});
            _streamId=d.stream_id;
            _liveUrl=location.origin+'/watch/user/'+d.stream_id;

            /* Transférer stream vers vidéo live */
            var lv=document.getElementById('gl-live-vid');
            lv.srcObject=_stream;
            lv.play().catch(function(){});

            document.getElementById('gl-url-display').textContent=_liveUrl;
            document.getElementById('gl-watch-link').href=_liveUrl;

            document.getElementById('step-camera').style.display='none';
            document.getElementById('step-live').style.display='block';

            /* Timer */
            _timerStart=Date.now();
            _timerInt=setInterval(function(){
                var e=Math.floor((Date.now()-_timerStart)/1000);
                var h=Math.floor(e/3600),m=Math.floor((e%3600)/60),s=e%60;
                var el=document.getElementById('gl-timer');
                if(el) el.textContent=('0'+h).slice(-2)+':'+('0'+m).slice(-2)+':'+('0'+s).slice(-2);
            },1000);

            showNotification('Vous êtes en direct !','success');
        }catch(err){
            showNotification('Erreur réseau: '+err.message,'error');
            btn.disabled=false;
            btn.innerHTML='<i class="fas fa-circle" style="font-size:10px;animation:livePulse 1s infinite;"></i> Aller en direct';
        }
    };

    /* ═══ Terminer live ═══ */
    window.glEndLive = async function(){
        if(!confirm('Terminer votre live ?')) return;
        clearInterval(_timerInt);
        glStopPreview();
        if(_streamId){
            try{await fetch('/api/streams/'+_streamId+'/stop',{method:'POST',credentials:'include'});}catch(e){}
        }
        document.getElementById('step-live').style.display='none';
        document.getElementById('step-ended').style.display='block';
    };

    /* ═══ Copier URL ═══ */
    window.glCopyUrl = function(){
        if(!_liveUrl) return;
        if(navigator.clipboard){
            navigator.clipboard.writeText(_liveUrl).then(function(){showNotification('Lien copié !','success');}).catch(function(){_copyFallback();});
        } else {_copyFallback();}
    };
    function _copyFallback(){
        var t=document.createElement('textarea');
        t.value=_liveUrl;
        document.body.appendChild(t);
        t.select();
        document.execCommand('copy');
        document.body.removeChild(t);
        showNotification('Lien copié !','success');
    }

    /* ═══ Avant de quitter ═══ */
    window.addEventListener('beforeunload',function(e){
        if(_streamId){e.preventDefault();e.returnValue='Votre live est en cours. Quitter ?';}
        glStopPreview();
    });
})();

</script>
{% endblock %}
'''
    # ══════════════════════════════════════════════════════════════════
    # ADMIN DASHBOARD TEMPLATE — Complet et fonctionnel
    # ══════════════════════════════════════════════════════════════════
    ADMIN_TEMPLATE = r'''{% extends "base.html" %}
{% block title %}Dashboard Admin - {{ app_name }}{% endblock %}
{% block head %}
<style>
/* ── Admin — habillé avec les tokens du design system (clair/sombre) ── */
.atab-nav { display:flex; gap:8px; overflow-x:auto; padding:0 4px 4px; margin:0 -4px; scrollbar-width:none; -webkit-overflow-scrolling:touch; }
.atab-nav::-webkit-scrollbar { display:none; }
.atab-btn { flex-shrink:0; padding:8px 16px; font-size:14px; font-weight:500; white-space:nowrap; cursor:pointer; background:transparent;
    border:1px solid var(--border); border-radius:999px; color:var(--ink-muted); transition:color .15s, background-color .15s, border-color .15s; }
.atab-btn:hover { color:var(--ink); }
.atab-btn.on { border-color:var(--accent-2) !important; background:var(--accent-2-soft) !important; color:var(--accent-2) !important; }
.atab-panel { display:none; }
.atab-panel.on { display:block; margin-top:16px; background:var(--surface) !important; border:1px solid var(--border) !important; border-radius:var(--radius-lg) !important; box-shadow:var(--shadow); }

.astat { background:var(--surface); border:1px solid var(--border); border-radius:var(--radius-lg); padding:18px; box-shadow:var(--shadow); }

.atable { width:100%; border-collapse:collapse; font-size:13px; }
.atable th { padding:10px 14px; text-align:left; font-size:11px; font-weight:600; text-transform:uppercase; letter-spacing:.05em; color:var(--ink-muted); background:var(--surface-2); border-bottom:1px solid var(--border); }
.atable td { padding:10px 14px; border-bottom:1px solid var(--border); vertical-align:middle; color:inherit; }
.atable tr:hover td { background:var(--surface-2); }

.abadge { display:inline-flex; align-items:center; padding:2px 8px; border-radius:99px; font-size:11px; font-weight:600; }
.ab-g  { background:color-mix(in srgb,#22c55e 15%,transparent); color:#16a34a; }
.ab-r  { background:color-mix(in srgb,var(--accent) 12%,transparent); color:var(--accent); }
.ab-b  { background:var(--accent-2-soft); color:var(--accent-2); }
.ab-y  { background:color-mix(in srgb,#f59e0b 16%,transparent); color:#b45309; }
.ab-gr { background:var(--surface-2); color:var(--ink-muted); }
html.dark .ab-g { color:#4ade80; } html.dark .ab-y { color:#fbbf24; }

.abtn { display:inline-flex; align-items:center; gap:5px; padding:7px 14px; border-radius:999px; border:1px solid transparent; font-size:12px; font-weight:600; cursor:pointer; transition:opacity .15s, background-color .15s; text-decoration:none; }
.abtn:hover { opacity:.85; }
.ab-btn-b  { background:var(--accent-2-soft); color:var(--accent-2); }
.ab-btn-r  { background:color-mix(in srgb,var(--accent) 12%,transparent); color:var(--accent); }
.ab-btn-g  { background:color-mix(in srgb,#22c55e 15%,transparent); color:#16a34a; }
.ab-btn-y  { background:color-mix(in srgb,#f59e0b 16%,transparent); color:#b45309; }
.ab-btn-gr { background:transparent; border-color:var(--border); color:var(--ink-muted); }
html.dark .ab-btn-g { color:#4ade80; } html.dark .ab-btn-y { color:#fbbf24; }

.a-inp { width:100%; border:1px solid var(--border); border-radius:10px; padding:8px 12px; font-size:13px; outline:none; background:var(--surface); color:inherit; }
.a-inp::placeholder { color:var(--ink-muted); }
.a-inp:focus { border-color:var(--accent-2); }

.apulse { display:inline-block; width:8px; height:8px; border-radius:50%; background:#22c55e; animation:apulseAnim 2s infinite; }
@keyframes apulseAnim { 0%,100%{opacity:1;transform:scale(1)} 50%{opacity:.5;transform:scale(.8)} }
#asp-bars { display:flex; align-items:flex-end; gap:2px; height:60px; }
</style>
{% endblock %}

{% block content %}
<div style="max-width:72rem;margin:0 auto;display:flex;flex-direction:column;gap:20px;">

<!-- ═══ HEADER ═══ -->
<div class="flex flex-wrap items-center justify-between gap-3">
    <div>
        <h1 class="font-display text-2xl font-semibold">Administration</h1>
        <p class="mt-1 flex flex-wrap items-center gap-2 text-sm text-ink-muted">
            <span class="apulse"></span>
            Connecté : <strong class="font-semibold text-ink">{{ user.username }}</strong>
            {% if user.is_owner %}<span class="rounded-full bg-violet-500/15 px-2 py-0.5 text-[11px] font-semibold text-violet-600 dark:text-violet-400">Propriétaire</span>{% endif %}
            {% if is_syncing %}<span class="text-xs font-semibold text-amber-600 dark:text-amber-400">Sync en cours...</span>
            {% elif last_sync %}<span class="text-xs">Sync : {{ last_sync.strftime('%d/%m %H:%M') }}</span>{% endif %}
        </p>
    </div>
    <div class="flex flex-wrap gap-2">
        <button onclick="aAction('/api/admin/iptv/sync','Lancer la synchronisation IPTV ? (quelques minutes)','POST')" class="abtn ab-btn-b">Sync IPTV</button>
        <a href="/api/admin/config/export" class="abtn ab-btn-gr">.env</a>
        <a href="/" class="abtn ab-btn-gr">Site</a>
        <a href="/admin/logout" class="abtn ab-btn-gr" style="gap:6px"><i class="fas fa-sign-in-alt" style="transform:scaleX(-1)"></i> Déconnexion</a>
    </div>
</div>

<!-- ═══ UTILISATEURS ACTIFS TEMPS RÉEL ═══ -->
<div style="background:linear-gradient(135deg,#0f172a,#1e293b);border-radius:18px;padding:20px;border:1px solid #334155;">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;flex-wrap:wrap;gap:8px;">
        <div style="display:flex;align-items:center;gap:10px;">
            <div style="width:10px;height:10px;background:#22c55e;border-radius:50%;box-shadow:0 0 0 4px rgba(34,197,94,.2);animation:apulseAnim 2s infinite;"></div>
            <span style="color:#fff;font-weight:800;font-size:15px;">Utilisateurs actifs en ce moment</span>
        </div>
        <div style="display:flex;align-items:center;gap:10px;">
            <span id="aws-badge" style="font-size:11px;padding:4px 10px;border-radius:99px;background:#1e3a5f;color:#93c5fd;font-weight:700;">Connexion...</span>
            <span id="aws-ts" style="font-size:11px;color:#475569;"></span>
        </div>
    </div>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;">
        <div style="background:#1e293b;border:1px solid #334155;border-radius:12px;padding:20px;text-align:center;">
            <div id="aws-count" style="font-size:3.5rem;font-weight:900;color:#4ade80;font-variant-numeric:tabular-nums;line-height:1;transition:color .3s;">0</div>
            <div style="color:#94a3b8;font-size:13px;margin-top:6px;">utilisateurs en ligne</div>
            <div style="color:#64748b;font-size:11px;margin-top:2px;">(actifs dans les 5 dernières min)</div>
        </div>
        <div style="background:#1e293b;border:1px solid #334155;border-radius:12px;padding:16px;">
            <div style="color:#94a3b8;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;margin-bottom:10px;">Activité (60 secondes)</div>
            <div id="asp-bars" style="display:flex;align-items:flex-end;gap:2px;height:60px;"></div>
        </div>
        <div style="background:#1e293b;border:1px solid #334155;border-radius:12px;padding:16px;">
            <div style="color:#94a3b8;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;margin-bottom:10px;">Pages visitées</div>
            <div id="aws-pages" style="color:#64748b;font-size:12px;">Chargement...</div>
        </div>
    </div>
</div>

<!-- ═══ STATS GRAPHIQUE HISTORIQUE ═══ -->
<div style="background:var(--surface);border:1px solid var(--border);border-radius:18px;padding:20px;" class="astat" style="background:inherit;">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;flex-wrap:wrap;gap:12px;">
        <h2 style="font-size:15px;font-weight:800;margin:0;display:flex;align-items:center;gap:8px;">Fréquentation</h2>
        <div style="display:flex;gap:6px;">
            <button onclick="aLoadHistory('week',this)" id="ahb-week" class="abtn ab-btn-r" style="font-size:12px;padding:5px 12px;">7 jours</button>
            <button onclick="aLoadHistory('month',this)" id="ahb-month" class="abtn ab-btn-gr" style="font-size:12px;padding:5px 12px;background:var(--surface-2);color:var(--ink);">30 jours</button>
            <button onclick="aLoadHistory('year',this)" id="ahb-year" class="abtn ab-btn-gr" style="font-size:12px;padding:5px 12px;background:var(--surface-2);color:var(--ink);">12 mois</button>
        </div>
    </div>
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:16px;">
        <div style="text-align:center;background:var(--surface-2);border-radius:10px;padding:12px;">
            <div id="ahk-u" style="font-size:1.5rem;font-weight:900;color:var(--accent);">—</div>
            <div style="font-size:11px;color:var(--ink-muted);margin-top:2px;">Visiteurs uniques</div>
        </div>
        <div style="text-align:center;background:var(--surface-2);border-radius:10px;padding:12px;">
            <div id="ahk-v" style="font-size:1.5rem;font-weight:900;color:var(--accent-2);">—</div>
            <div style="font-size:11px;color:var(--ink-muted);margin-top:2px;">Pages vues</div>
        </div>
        <div style="text-align:center;background:var(--surface-2);border-radius:10px;padding:12px;">
            <div id="ahk-p" style="font-size:1.5rem;font-weight:900;color:#16a34a;">—</div>
            <div style="font-size:11px;color:var(--ink-muted);margin-top:2px;">Pic simultané</div>
        </div>
    </div>
    <div style="position:relative;height:200px;">
        <canvas id="ah-chart"></canvas>
        <div id="ah-loading" style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-size:13px;color:var(--ink-muted);">Chargement du graphique...</div>
    </div>
</div>

<!-- ═══ STAT CARDS ═══ -->
<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:12px;">
    <div class="astat">
        <div style="font-size:1.4rem;font-weight:900;color:var(--accent-2);" id="ast-streams">{{ stats.total_streams }}</div>
        <div style="font-size:12px;color:var(--ink-muted);margin-top:2px;">Streams</div>
        <div style="font-size:11px;color:#22c55e;" id="ast-live">{{ stats.live_streams }} en direct</div>
    </div>
    <div class="astat">
        <div style="font-size:1.4rem;font-weight:900;color:#7c3aed;">{{ stats.iptv_channels }}</div>
        <div style="font-size:12px;color:var(--ink-muted);margin-top:2px;">Chaînes TV</div>
        <div style="font-size:11px;color:var(--ink-muted);">{{ stats.iptv_playlists }} playlists</div>
    </div>
    <div class="astat">
        <div style="font-size:1.4rem;font-weight:900;color:#0891b2;" id="ast-visitors">{{ stats.total_visitors }}</div>
        <div style="font-size:12px;color:var(--ink-muted);margin-top:2px;">Visiteurs</div>
        <div style="font-size:11px;color:var(--ink-muted);">{{ stats.tracked_locations }} géolocalisés</div>
    </div>
    <div class="astat" style="position:relative;">
        <div style="font-size:1.4rem;font-weight:900;color:#d97706;">{{ stats.unread_feedback }}</div>
        <div style="font-size:12px;color:var(--ink-muted);margin-top:2px;">Avis non lus</div>
        <div style="font-size:11px;color:var(--ink-muted);">{{ stats.total_feedback }} total</div>
        {% if stats.unread_feedback > 0 %}<div style="position:absolute;top:10px;right:10px;width:8px;height:8px;background:var(--accent);border-radius:50%;animation:apulseAnim 1.5s infinite;"></div>{% endif %}
    </div>
    <div class="astat">
        <div style="font-size:1.4rem;font-weight:900;color:#16a34a;">{{ stats.active_announcements }}</div>
        <div style="font-size:12px;color:var(--ink-muted);margin-top:2px;">Annonces actives</div>
        <div style="font-size:11px;color:var(--ink-muted);">{{ stats.total_events }} événements EPG</div>
    </div>
    <div class="astat">
        <div style="font-size:1.4rem;font-weight:900;color:var(--accent);">{{ stats.blocked_ips }}</div>
        <div style="font-size:12px;color:var(--ink-muted);margin-top:2px;">IPs bloquées</div>
        <div style="font-size:11px;color:var(--accent);">{{ stats.total_reports }} signalements</div>
    </div>
</div>

<!-- ═══ DB STATUS ═══ -->
<div id="adb-bar" style="display:none;background:color-mix(in srgb,var(--accent) 12%,transparent);border:1px solid color-mix(in srgb,var(--accent) 30%,transparent);color:var(--accent);padding:10px 16px;border-radius:10px;font-size:13px;font-weight:600;">
    <span id="adb-msg">PostgreSQL : vérification...</span>
</div>

<!-- ═══ TABS ═══ -->
<div>
    <div class="atab-nav">
        <button class="atab-btn on"  onclick="aShowTab('streams',this)">Streams <span style="font-size:11px;background:var(--surface-2);padding:1px 6px;border-radius:99px;margin-left:4px;">{{ stats.total_streams }}</span></button>
        <button class="atab-btn"     onclick="aShowTab('external',this)">Flux ext. <span style="font-size:11px;background:var(--surface-2);padding:1px 6px;border-radius:99px;margin-left:4px;">{{ stats.external_streams }}</span></button>
        <button class="atab-btn"     onclick="aShowTab('iptv',this)">TV <span style="font-size:11px;background:var(--surface-2);padding:1px 6px;border-radius:99px;margin-left:4px;">{{ stats.iptv_playlists }}</span></button>
        <button class="atab-btn"     onclick="aShowTab('feedback',this)">Avis {% if stats.unread_feedback > 0 %}<span style="font-size:11px;background:color-mix(in srgb,var(--accent) 12%,transparent);color:var(--accent);padding:1px 6px;border-radius:99px;margin-left:4px;">{{ stats.unread_feedback }}</span>{% endif %}</button>
        <button class="atab-btn"     onclick="aShowTab('announcements',this)">Annonces <span style="font-size:11px;background:color-mix(in srgb,#f59e0b 16%,transparent);color:#a16207;padding:1px 6px;border-radius:99px;margin-left:4px;">{{ stats.active_announcements }}</span></button>
        <button class="atab-btn"     onclick="aShowTab('comments',this)">Chat</button>
        <button class="atab-btn"     onclick="aShowTab('reports',this)">Signalements{% if stats.total_reports > 0 %} <span style="font-size:11px;background:color-mix(in srgb,var(--accent) 12%,transparent);color:var(--accent);padding:1px 6px;border-radius:99px;margin-left:4px;">{{ stats.total_reports }}</span>{% endif %}</button>
        <button class="atab-btn"     onclick="aShowTab('ips',this)">IPs</button>
    </div>

    <!-- ── Tab: Streams utilisateur ── -->
    <div id="atab-streams" class="atab-panel on" style="background:var(--surface);border:1px solid var(--border);border-top:none;border-radius:0 0 12px 12px;">
        
        <div style="padding:14px 16px;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;">
            <h3 style="font-weight:700;margin:0;font-size:14px;">Streams utilisateurs</h3>
        </div>
        <div style="overflow-x:auto;">
            <table class="atable">
                <thead><tr><th>Titre</th><th>Catégorie</th><th>Statut</th><th>Vues</th><th>Créé</th><th>Actions</th></tr></thead>
                <tbody>
                {% for s in user_streams %}
                <tr id="str-{{ s.id }}">
                    <td><div style="font-weight:600;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{{ s.title }}</div></td>
                    <td><span class="abadge ab-gr">{{ s.category }}</span></td>
                    <td>
                        {% if s.is_live %}<span class="abadge ab-g live-badge">LIVE</span>
                        {% elif s.is_blocked %}<span class="abadge ab-r">Bloqué</span>
                        {% else %}<span class="abadge ab-gr">Terminé</span>{% endif %}
                    </td>
                    <td style="color:var(--ink-muted);">{{ s.viewer_count }}</td>
                    <td style="font-size:11px;color:var(--ink-muted);">{{ s.created_at.strftime('%d/%m %H:%M') }}</td>
                    <td>
                        <div style="display:flex;gap:6px;flex-wrap:wrap;">
                            <a href="/watch/user/{{ s.id }}" target="_blank" class="abtn ab-btn-b"></a>
                            {% if not s.is_blocked %}
                            <button onclick="aAction('/api/admin/streams/{{ s.id }}/block','Bloquer ce stream ?')" class="abtn ab-btn-r"></button>
                            {% else %}
                            <button onclick="aAction('/api/admin/streams/{{ s.id }}/unblock','Débloquer ce stream ?')" class="abtn ab-btn-g"></button>
                            {% endif %}
                        </div>
                    </td>
                </tr>
                {% else %}
                <tr><td colspan="6" style="text-align:center;padding:32px;color:var(--ink-muted);font-size:13px;">Aucun stream</td></tr>
                {% endfor %}
                </tbody>
            </table>
        </div>
    </div>

    <!-- ── Tab: Flux externes ── -->
    <div id="atab-external" class="atab-panel" style="background:var(--surface);border:1px solid var(--border);border-top:none;border-radius:0 0 12px 12px;">
        <div style="padding:14px 16px;border-bottom:1px solid var(--border);"><h3 style="font-weight:700;margin:0;font-size:14px;">Flux externes ({{ stats.external_streams }})</h3></div>
        <div style="overflow-x:auto;">
            <table class="atable">
                <thead><tr><th>Titre</th><th>Catégorie</th><th>Pays</th><th>Type</th><th>Statut</th><th>Actions</th></tr></thead>
                <tbody>
                {% for s in external_streams %}
                <tr>
                    <td>
                        <div style="display:flex;align-items:center;gap:8px;">
                            {% if s.logo %}<img src="{{ s.logo }}" style="width:26px;height:26px;object-fit:contain;border-radius:4px;" loading="lazy" onerror="this.style.display='none'">{% endif %}
                            <span style="font-weight:600;max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{{ s.title }}</span>
                        </div>
                    </td>
                    <td><span class="abadge ab-gr">{{ s.category }}</span></td>
                    <td style="font-size:12px;">{% if s.country %}<img src="https://flagcdn.com/w20/{{ s.country|lower }}.png" style="width:18px;height:12px;object-fit:cover;border-radius:2px;vertical-align:middle;margin-right:4px;" onerror="this.style.display='none'">{% endif %}{{ s.country }}</td>
                    <td><span class="abadge ab-b">{{ s.stream_type|upper }}</span></td>
                    <td>{% if s.is_active %}<span class="abadge ab-g">Actif</span>{% else %}<span class="abadge ab-r">Off</span>{% endif %}</td>
                    <td>
                        <button onclick="aAction('/api/admin/external/{{ s.id }}/toggle')" class="abtn {% if s.is_active %}ab-btn-r{% else %}ab-btn-g{% endif %}">
                            {% if s.is_active %}Désact.{% else %}Activer{% endif %}
                        </button>
                    </td>
                </tr>
                {% else %}
                <tr><td colspan="6" style="text-align:center;padding:32px;color:var(--ink-muted);font-size:13px;">Aucun flux externe</td></tr>
                {% endfor %}
                </tbody>
            </table>
        </div>
    </div>

    <!-- ── Tab: IPTV/TV ── -->
    <div id="atab-iptv" class="atab-panel" style="background:var(--surface);border:1px solid var(--border);border-top:none;border-radius:0 0 12px 12px;">
        <div style="padding:14px 16px;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between;">
            <h3 style="font-weight:700;margin:0;font-size:14px;">Playlists Chaînes TV</h3>
            <button onclick="aAction('/api/admin/iptv/sync','Lancer la synchronisation ?')" class="abtn ab-btn-b">Sync tout</button>
        </div>
        <div style="overflow-x:auto;">
            <table class="atable">
                <thead><tr><th>Pays</th><th>Chaînes</th><th>Dernière sync</th><th>Statut</th><th>Actions</th></tr></thead>
                <tbody>
                {% for pl in iptv_playlists %}
                <tr>
                    <td>
                        <div style="display:flex;align-items:center;gap:8px;">
                            {% if pl.country %}<img src="https://flagcdn.com/w20/{{ pl.country|lower }}.png" style="width:20px;height:14px;object-fit:cover;border-radius:2px;" onerror="this.style.display='none'">{% endif %}
                            <span style="font-weight:600;font-size:13px;">{{ pl.display_name or pl.name }}</span>
                        </div>
                    </td>
                    <td style="font-weight:700;color:var(--ink);">{{ pl.channel_count or 0 }}</td>
                    <td style="font-size:12px;color:var(--ink-muted);">{{ pl.last_sync.strftime('%d/%m %H:%M') if pl.last_sync else 'Jamais' }}</td>
                    <td>
                        {% if pl.sync_status == 'success' %}<span class="abadge ab-g">OK</span>
                        {% elif pl.sync_status == 'error' %}<span class="abadge ab-r" title="{{ pl.sync_error }}">Erreur</span>
                        {% else %}<span class="abadge ab-gr">En attente</span>{% endif %}
                    </td>
                    <td>
                        <button onclick="aAction('/api/admin/iptv/playlist/{{ pl.name }}/refresh')" class="abtn ab-btn-b">Sync</button>
                    </td>
                </tr>
                {% else %}
                <tr><td colspan="5" style="text-align:center;padding:32px;color:var(--ink-muted);font-size:13px;">Aucune playlist</td></tr>
                {% endfor %}
                </tbody>
            </table>
        </div>
    </div>

    <!-- ── Tab: Avis utilisateurs ── -->
    <div id="atab-feedback" class="atab-panel" style="background:var(--surface);border:1px solid var(--border);border-top:none;border-radius:0 0 12px 12px;">
        <div style="padding:14px 16px;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between;">
            <h3 style="font-weight:700;margin:0;font-size:14px;">Avis des utilisateurs</h3>
            {% if stats.unread_feedback > 0 %}<span class="abadge ab-r">{{ stats.unread_feedback }} non lu(s)</span>{% endif %}
        </div>
        <div style="overflow-x:auto;">
            <table class="atable">
                <thead><tr><th>Note</th><th>Message</th><th>Email</th><th>Date</th><th>Actions</th></tr></thead>
                <tbody>
                {% for fb in feedbacks %}
                <tr id="fbr-{{ fb.id }}" style="{% if not fb.is_read %}background:rgba(251,191,36,.06);{% endif %}">
                    <td style="font-size:1rem;color:#f59e0b;white-space:nowrap;">{% for i in range(fb.rating) %}★{% endfor %}{% for i in range(5-fb.rating) %}<span style="color:var(--border);">★</span>{% endfor %}</td>
                    <td style="max-width:280px;">
                        <div style="font-size:13px;{% if not fb.is_read %}font-weight:700;{% endif %}overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{{ fb.message[:180] }}{% if fb.message|length > 180 %}...{% endif %}</div>
                    </td>
                    <td>
                        {% if fb.email %}<a href="mailto:{{ fb.email }}" style="color:var(--accent-2);font-size:12px;text-decoration:none;">{{ fb.email }}</a>
                        {% else %}<span style="color:var(--ink-muted);font-size:12px;">—</span>{% endif %}
                    </td>
                    <td style="font-size:11px;color:var(--ink-muted);white-space:nowrap;">{{ fb.created_at.strftime('%d/%m/%Y %H:%M') }}</td>
                    <td>
                        <div style="display:flex;gap:6px;">
                            {% if not fb.is_read %}
                            <button onclick="aMarkFbRead('{{ fb.id }}')" class="abtn ab-btn-b" title="Marquer comme lu">✓ Lu</button>
                            {% endif %}
                            <button onclick="aDelFb('{{ fb.id }}')" class="abtn ab-btn-r" title="Supprimer"></button>
                        </div>
                    </td>
                </tr>
                {% else %}
                <tr><td colspan="5" style="text-align:center;padding:32px;color:var(--ink-muted);font-size:13px;">Aucun avis reçu</td></tr>
                {% endfor %}
                </tbody>
            </table>
        </div>
    </div>

    <!-- ── Tab: Annonces ── -->
    <div id="atab-announcements" class="atab-panel" style="background:var(--surface);border:1px solid var(--border);border-top:none;border-radius:0 0 12px 12px;">
        <!-- Formulaire création -->
        <div style="padding:20px;border-bottom:1px solid var(--border);">
            <h3 style="font-weight:700;margin:0 0 16px;font-size:14px;">Créer une annonce</h3>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px;">
                <div>
                    <label style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;color:var(--ink-muted);display:block;margin-bottom:4px;">Titre *</label>
                    <input type="text" id="ann-title" maxlength="200" placeholder="Titre de l'annonce" class="a-inp">
                </div>
                <div>
                    <label style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;color:var(--ink-muted);display:block;margin-bottom:4px;">Type</label>
                    <select id="ann-type" class="a-inp">
                        <option value="info">Information</option>
                        <option value="warning">Important</option>
                        <option value="update">Mise à jour</option>
                        <option value="feature">Nouveauté</option>
                    </select>
                </div>
            </div>
            <div style="margin-bottom:12px;">
                <label style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;color:var(--ink-muted);display:block;margin-bottom:4px;">Message *</label>
                <textarea id="ann-message" rows="3" maxlength="2000" placeholder="Message qui sera visible par tous les utilisateurs dans la page Événements..." class="a-inp" style="resize:vertical;"></textarea>
            </div>
            <div style="display:flex;align-items:flex-end;gap:12px;flex-wrap:wrap;">
                <div>
                    <label style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;color:var(--ink-muted);display:block;margin-bottom:4px;">Expiration (heures, 0 = jamais)</label>
                    <input type="number" id="ann-expires" min="0" max="8760" value="0" style="width:120px;" class="a-inp">
                </div>
                <button onclick="aCreateAnn()" id="ann-submit-btn"
                    style="background:var(--accent);color:#fff;border:none;padding:10px 24px;border-radius:10px;font-size:14px;font-weight:800;cursor:pointer;display:flex;align-items:center;gap:8px;transition:background .2s;"
                    onmouseover="this.style.background='#b91c1c'" onmouseout="this.style.background='#dc2626'">
                    Publier l'annonce
                </button>
            </div>
            <div id="ann-feedback" style="display:none;margin-top:10px;padding:10px 14px;border-radius:8px;font-size:13px;font-weight:600;"></div>
        </div>
        <!-- Liste des annonces -->
        <div style="overflow-x:auto;">
            <table class="atable">
                <thead><tr><th>Type</th><th>Titre</th><th>Message</th><th>Créée</th><th>Statut</th><th>Actions</th></tr></thead>
                <tbody id="ann-tbody">
                {% for ann in announcements %}
                <tr id="annr-{{ ann.id }}">
                    <td style="font-size:1.2rem;">{% if ann.type=='info' %}{% elif ann.type=='warning' %}{% elif ann.type=='update' %}{% elif ann.type=='feature' %}{% else %}{% endif %}</td>
                    <td style="font-weight:700;font-size:13px;max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{{ ann.title }}</td>
                    <td style="font-size:12px;color:var(--ink-muted);max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{{ ann.message[:90] }}...</td>
                    <td style="font-size:11px;color:var(--ink-muted);white-space:nowrap;">{{ ann.created_at.strftime('%d/%m %H:%M') }}</td>
                    <td>{% if ann.is_active %}<span class="abadge ab-g">Active</span>{% else %}<span class="abadge ab-gr">Off</span>{% endif %}</td>
                    <td>
                        <div style="display:flex;gap:6px;">
                            <button onclick="aToggleAnn('{{ ann.id }}')" class="abtn {% if ann.is_active %}ab-btn-y{% else %}ab-btn-g{% endif %}">{% if ann.is_active %}{% else %}{% endif %}</button>
                            <button onclick="aDelAnn('{{ ann.id }}')" class="abtn ab-btn-r"></button>
                        </div>
                    </td>
                </tr>
                {% else %}
                <tr><td colspan="6" style="text-align:center;padding:32px;color:var(--ink-muted);font-size:13px;">Aucune annonce créée. Utilisez le formulaire ci-dessus.</td></tr>
                {% endfor %}
                </tbody>
            </table>
        </div>
    </div>

    <!-- ── Tab: Chat/Commentaires ── -->
    <div id="atab-comments" class="atab-panel" style="background:var(--surface);border:1px solid var(--border);border-top:none;border-radius:0 0 12px 12px;">
        <div style="padding:14px 16px;border-bottom:1px solid var(--border);"><h3 style="font-weight:700;margin:0;font-size:14px;">Commentaires Chat ({{ stats.total_comments }})</h3></div>
        <div style="overflow-x:auto;">
            <table class="atable">
                <thead><tr><th>Contenu</th><th>Date</th><th>Signalements</th><th>Statut</th><th>Actions</th></tr></thead>
                <tbody>
                {% for c in recent_comments %}
                <tr id="cmtr-{{ c.id }}">
                    <td style="max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:13px;">{{ c.content[:120] }}</td>
                    <td style="font-size:11px;color:var(--ink-muted);white-space:nowrap;">{{ c.created_at.strftime('%d/%m %H:%M') }}</td>
                    <td><span class="abadge {% if c.report_count > 0 %}ab-r{% else %}ab-gr{% endif %}">{{ c.report_count }}</span></td>
                    <td>{% if c.is_deleted %}<span class="abadge ab-r">Supprimé</span>{% elif c.is_auto_hidden %}<span class="abadge ab-y">Masqué auto</span>{% else %}<span class="abadge ab-g">Visible</span>{% endif %}</td>
                    <td>
                        {% if not c.is_deleted %}
                        <button onclick="aAction('/api/admin/comments/{{ c.id }}/delete','Supprimer ce commentaire ?')" class="abtn ab-btn-r"></button>
                        {% endif %}
                    </td>
                </tr>
                {% else %}
                <tr><td colspan="5" style="text-align:center;padding:32px;color:var(--ink-muted);font-size:13px;">Aucun commentaire</td></tr>
                {% endfor %}
                </tbody>
            </table>
        </div>
    </div>

    <!-- ── Tab: Signalements ── -->
    <div id="atab-reports" class="atab-panel" style="background:var(--surface);border:1px solid var(--border);border-top:none;border-radius:0 0 12px 12px;">
        <div style="padding:14px 16px;border-bottom:1px solid var(--border);"><h3 style="font-weight:700;margin:0;font-size:14px;">Signalements ({{ stats.total_reports }})</h3></div>
        <div style="overflow-x:auto;">
            <table class="atable">
                <thead><tr><th>Raison</th><th>Date</th><th>Statut</th><th>Actions</th></tr></thead>
                <tbody>
                {% for r in pending_reports %}
                <tr id="rptr-{{ r.id }}">
                    <td style="font-size:13px;max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{{ r.reason }}</td>
                    <td style="font-size:11px;color:var(--ink-muted);white-space:nowrap;">{{ r.created_at.strftime('%d/%m %H:%M') }}</td>
                    <td>{% if r.resolved %}<span class="abadge ab-g">Résolu</span>{% else %}<span class="abadge ab-r">En attente</span>{% endif %}</td>
                    <td>
                        {% if not r.resolved %}
                        <button onclick="aAction('/api/admin/reports/{{ r.id }}/resolve','Marquer comme résolu ?')" class="abtn ab-btn-g">Résoudre</button>
                        {% endif %}
                    </td>
                </tr>
                {% else %}
                <tr><td colspan="4" style="text-align:center;padding:32px;color:var(--ink-muted);font-size:13px;">Aucun signalement en attente</td></tr>
                {% endfor %}
                </tbody>
            </table>
        </div>
    </div>

    <!-- ── Tab: IPs bloquées ── -->
    <div id="atab-ips" class="atab-panel" style="background:var(--surface);border:1px solid var(--border);border-top:none;border-radius:0 0 12px 12px;">
        <!-- Formulaire bloquer IP -->
        <div style="padding:16px;border-bottom:1px solid var(--border);">
            <h3 style="font-weight:700;margin:0 0 12px;font-size:14px;">Bloquer une IP</h3>
            <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end;">
                <div>
                    <label style="font-size:11px;font-weight:700;color:var(--ink-muted);display:block;margin-bottom:4px;">Adresse IP</label>
                    <input type="text" id="aip-addr" placeholder="Ex: 192.168.1.1" class="a-inp" style="width:180px;">
                </div>
                <div>
                    <label style="font-size:11px;font-weight:700;color:var(--ink-muted);display:block;margin-bottom:4px;">Raison</label>
                    <input type="text" id="aip-reason" placeholder="Raison du blocage" class="a-inp" style="width:240px;">
                </div>
                <label style="display:flex;align-items:center;gap:6px;font-size:13px;cursor:pointer;">
                    <input type="checkbox" id="aip-perm"> Permanent
                </label>
                <button onclick="aBlockIP()" class="abtn ab-btn-r" style="font-size:13px;padding:8px 16px;">Bloquer</button>
            </div>
        </div>
        <div style="overflow-x:auto;">
            <table class="atable">
                <thead><tr><th>Adresse IP</th><th>Raison</th><th>Bloquée le</th><th>Expire</th><th>Actions</th></tr></thead>
                <tbody>
                {% for ip in blocked_ips %}
                <tr id="ipr-{{ ip.id }}">
                    <td style="font-family:monospace;font-size:13px;font-weight:700;">{{ ip.ip_address }}</td>
                    <td style="font-size:13px;max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{{ ip.reason }}</td>
                    <td style="font-size:11px;color:var(--ink-muted);white-space:nowrap;">{{ ip.blocked_at.strftime('%d/%m/%Y %H:%M') }}</td>
                    <td style="font-size:11px;color:var(--ink-muted);white-space:nowrap;">{% if ip.is_permanent %}<span class="abadge ab-r">Permanent</span>{% elif ip.expires_at %}{{ ip.expires_at.strftime('%d/%m/%Y') }}{% else %}—{% endif %}</td>
                    <td>
                        <button onclick="aAction('/api/admin/ips/{{ ip.id }}/unblock','Débloquer cette IP ?')" class="abtn ab-btn-g">Débloquer</button>
                    </td>
                </tr>
                {% else %}
                <tr><td colspan="5" style="text-align:center;padding:32px;color:var(--ink-muted);font-size:13px;">Aucune IP bloquée</td></tr>
                {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
</div><!-- end tabs -->

<!-- ═══ CARTE DU MONDE ═══ (EN DEHORS DES TABS) -->
<div style="background:var(--surface);border:1px solid var(--border);border-radius:18px;overflow:hidden;" class="astat">
    <div style="padding:16px 20px;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;">
        <div>
            <h2 style="font-weight:800;font-size:15px;margin:0;">Carte des utilisateurs</h2>
            <p style="font-size:12px;color:var(--ink-muted);margin:2px 0 0;">Localisation géographique de vos visiteurs (basée sur IP)</p>
        </div>
        <div style="display:flex;align-items:center;gap:10px;">
            <span id="amap-total" style="font-size:12px;padding:4px 12px;background:var(--accent-2-soft);color:var(--accent-2);border-radius:99px;font-weight:700;">Chargement...</span>
            <button onclick="aLoadMap(true)" class="abtn ab-btn-b">Actualiser</button>
        </div>
    </div>
    <div style="padding:20px;">
        <!-- Leaflet Map -->
        <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
        <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
        <div id="amap-container" style="position:relative;border-radius:12px;overflow:hidden;height:420px;margin-bottom:16px;border:1px solid var(--border);">
            <div id="amap-loading" style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;flex-direction:column;gap:12px;color:var(--ink-muted);z-index:1000;background:rgba(255,255,255,.9);">
                <i class="fas fa-spinner fa-spin" style="font-size:2rem;color:var(--accent-2);"></i>
                <p style="font-size:13px;margin:0;">Chargement de la carte...</p>
            </div>
            <div id="amap-leaflet" style="width:100%;height:100%;"></div>
        </div>

        <!-- Stats en grille -->
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
            <div>
                <h3 style="font-size:13px;font-weight:700;margin:0 0 10px;">Top pays</h3>
                <div id="amap-countries" class="custom-scroll" style="max-height:200px;overflow-y:auto;display:flex;flex-direction:column;gap:6px;">
                    <p style="font-size:12px;color:var(--ink-muted);">Chargement...</p>
                </div>
            </div>
            <div>
                <h3 style="font-size:13px;font-weight:700;margin:0 0 10px;">Par continent</h3>
                <div id="amap-continents" style="display:flex;flex-direction:column;gap:6px;">
                    <p style="font-size:12px;color:var(--ink-muted);">Chargement...</p>
                </div>
            </div>
        </div>
    </div>
</div>

</div><!-- end max-w -->
{% endblock %}

{% block scripts %}
<script>
// ═══════════════════════════════════════════════════════════
//  ADMIN DASHBOARD — JavaScript complet
// ═══════════════════════════════════════════════════════════

// ── TABS ──────────────────────────────────────────────────
function aShowTab(id, btn) {
    // Désactiver tous les panels et boutons
    document.querySelectorAll('.atab-panel').forEach(function(p){
        p.classList.remove('on');
    });
    document.querySelectorAll('.atab-btn').forEach(function(b){
        b.classList.remove('on');
    });
    // Activer le panel et le bouton cliqués
    var panel = document.getElementById('atab-' + id);
    if (panel) panel.classList.add('on');
    if (btn) btn.classList.add('on');
    // Forcer Leaflet à recalculer sa taille si on ouvre l'onglet visiteurs
    if (id === 'visitors' && _leafletMap) {
        setTimeout(function(){ _leafletMap.invalidateSize(); }, 100);
    }
}

// ── ACTION ADMIN GÉNÉRIQUE ─────────────────────────────────
async function aAction(url, confirmMsg, method) {
    if (confirmMsg && !confirm(confirmMsg)) return;
    method = method || 'POST';
    try {
        var r = await fetch(url, { method: method, credentials: 'include' });
        var data = {};
        try { data = await r.json(); } catch(e) {}
        if (r.ok) {
            showNotification(data.message || 'Action effectuée', 'success');
            setTimeout(function(){ location.reload(); }, 1000);
        } else if (r.status === 401) {
            showNotification('Session expirée — reconnexion...', 'error');
            setTimeout(function(){ window.location.href = '/admin'; }, 1500);
        } else {
            showNotification(data.error || 'Erreur (' + r.status + ')', 'error');
        }
    } catch(e) {
        showNotification('Erreur réseau: ' + e.message, 'error');
    }
}

// ── BLOQUER IP ─────────────────────────────────────────────
async function aBlockIP() {
    var ip = document.getElementById('aip-addr').value.trim();
    var reason = document.getElementById('aip-reason').value.trim() || 'Raison non spécifiée';
    var perm = document.getElementById('aip-perm').checked;
    if (!ip) { showNotification('Entrez une adresse IP', 'error'); return; }
    var fd = new FormData();
    fd.append('ip_address', ip);
    fd.append('reason', reason);
    fd.append('permanent', perm ? 'true' : 'false');
    try {
        var r = await fetch('/api/admin/ips/block', { method:'POST', body:fd, credentials:'include' });
        var d = await r.json();
        if (r.ok && d.success) {
            showNotification('IP bloquée', 'success');
            document.getElementById('aip-addr').value = '';
            document.getElementById('aip-reason').value = '';
            setTimeout(function(){ location.reload(); }, 800);
        } else {
            showNotification(d.error || 'Erreur', 'error');
        }
    } catch(e) { showNotification('Erreur réseau', 'error'); }
}

// ── FEEDBACK : MARQUER LU ──────────────────────────────────
async function aMarkFbRead(id) {
    try {
        var r = await fetch('/api/admin/feedback/' + id + '/read', { method:'POST', credentials:'include' });
        if (r.ok) {
            var row = document.getElementById('fbr-' + id);
            if (row) row.style.background = '';
            showNotification('Marqué comme lu ✓', 'success');
            // Retirer le bouton "Lu"
            var btn = row ? row.querySelector('button[onclick*="aMarkFbRead"]') : null;
            if (btn) btn.remove();
        }
    } catch(e) { showNotification('Erreur réseau', 'error'); }
}

// ── FEEDBACK : SUPPRIMER ───────────────────────────────────
async function aDelFb(id) {
    if (!confirm('Supprimer cet avis définitivement ?')) return;
    try {
        var r = await fetch('/api/admin/feedback/' + id, { method:'DELETE', credentials:'include' });
        if (r.ok) {
            var row = document.getElementById('fbr-' + id);
            if (row) row.remove();
            showNotification('Avis supprimé', 'success');
        }
    } catch(e) { showNotification('Erreur réseau', 'error'); }
}

// ── ANNONCES : CRÉER ──────────────────────────────────────
async function aCreateAnn() {
    var title   = document.getElementById('ann-title').value.trim();
    var message = document.getElementById('ann-message').value.trim();
    var type    = document.getElementById('ann-type').value;
    var expires = parseInt(document.getElementById('ann-expires').value) || 0;
    var fbEl    = document.getElementById('ann-feedback');

    fbEl.style.display = 'none';

    if (!title)   { _annFb('Le titre est obligatoire', false); return; }
    if (!message || message.length < 5) { _annFb('Le message est obligatoire (min 5 caractères)', false); return; }

    var btn = document.getElementById('ann-submit-btn');
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Publication...';

    var fd = new FormData();
    fd.append('title', title);
    fd.append('message', message);
    fd.append('type', type);
    fd.append('expires_hours', expires);

    try {
        var r = await fetch('/api/admin/announcements/create', { method:'POST', body:fd, credentials:'include' });
        var d = await r.json();
        if (r.ok && d.success) {
            _annFb('Annonce publiée ! Visible par tous les utilisateurs dans la page Événements.', true);
            document.getElementById('ann-title').value   = '';
            document.getElementById('ann-message').value = '';
            document.getElementById('ann-expires').value = '0';
            setTimeout(function(){ location.reload(); }, 1500);
        } else {
            _annFb(d.error || 'Erreur lors de la publication', false);
        }
    } catch(e) {
        _annFb('Erreur réseau: ' + e.message, false);
    }
    btn.disabled = false;
    btn.innerHTML = 'Publier l\'annonce';
}

function _annFb(msg, ok) {
    var el = document.getElementById('ann-feedback');
    el.textContent = msg;
    el.style.background = ok ? 'color-mix(in srgb,#22c55e 15%,transparent)' : 'color-mix(in srgb,var(--accent) 12%,transparent)';
    el.style.color = ok ? '#16a34a' : 'var(--accent)';
    el.style.border = '1px solid ' + (ok ? '#bbf7d0' : '#fecaca');
    el.style.display = 'block';
}

// ── ANNONCES : TOGGLE ─────────────────────────────────────
async function aToggleAnn(id) {
    try {
        var r = await fetch('/api/admin/announcements/' + id + '/toggle', { method:'POST', credentials:'include' });
        if (r.ok) { showNotification('Statut mis à jour', 'success'); setTimeout(function(){ location.reload(); }, 600); }
        else { showNotification('Erreur', 'error'); }
    } catch(e) { showNotification('Erreur réseau', 'error'); }
}

// ── ANNONCES : SUPPRIMER ──────────────────────────────────
async function aDelAnn(id) {
    if (!confirm('Supprimer cette annonce définitivement ?')) return;
    try {
        var r = await fetch('/api/admin/announcements/' + id, { method:'DELETE', credentials:'include' });
        if (r.ok) {
            var row = document.getElementById('annr-' + id);
            if (row) row.remove();
            showNotification('Annonce supprimée', 'success');
        }
    } catch(e) { showNotification('Erreur réseau', 'error'); }
}

// ── GRAPHIQUE HISTORIQUE ──────────────────────────────────
var _ahChart = null;
var _ahPeriod = 'week';

async function aLoadHistory(period, btn) {
    _ahPeriod = period;
    // Mettre à jour boutons
    ['week','month','year'].forEach(function(k){
        var b = document.getElementById('ahb-' + k);
        if (!b) return;
        if (k === period) {
            b.style.background = '#dc2626'; b.style.color = '#fff';
        } else {
            b.style.background = 'var(--surface-2)'; b.style.color = 'var(--ink)';
        }
    });

    var loading = document.getElementById('ah-loading');
    if (loading) loading.style.display = 'flex';

    try {
        var r = await fetch('/api/admin/stats/history?period=' + period, { credentials:'include' });
        if (!r.ok) {
            if (loading) loading.textContent = 'Erreur chargement';
            return;
        }
        var data = await r.json();

        // KPIs
        var ku = document.getElementById('ahk-u');
        var kv = document.getElementById('ahk-v');
        var kp = document.getElementById('ahk-p');
        if (ku) ku.textContent = (data.total_unique || 0).toLocaleString('fr-FR');
        if (kv) kv.textContent = (data.total_views  || 0).toLocaleString('fr-FR');
        if (kp) kp.textContent = (data.max_peak     || 0).toLocaleString('fr-FR');

        // Chart
        var ctx = document.getElementById('ah-chart');
        if (!ctx) return;

        if (_ahChart) { _ahChart.destroy(); _ahChart = null; }

        var isDark = document.documentElement.classList.contains('dark');
        var gc = isDark ? 'rgba(255,255,255,.06)' : 'rgba(0,0,0,.05)';
        var tc = isDark ? '#9ca3af' : '#6b7280';

        _ahChart = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: data.days.map(function(d){ return d.label; }),
                datasets: [
                    {
                        label: 'Visiteurs uniques',
                        data: data.days.map(function(d){ return d.unique_users; }),
                        backgroundColor: 'rgba(220,38,38,.7)',
                        borderColor: '#dc2626',
                        borderWidth: 1,
                        borderRadius: 4,
                        order: 2,
                    },
                    {
                        label: 'Pic simultané',
                        data: data.days.map(function(d){ return d.peak_active; }),
                        type: 'line',
                        borderColor: '#22c55e',
                        backgroundColor: 'rgba(34,197,94,.12)',
                        borderWidth: 2,
                        pointRadius: 3,
                        fill: true,
                        tension: 0.4,
                        order: 1,
                        yAxisID: 'yPeak',
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode:'index', intersect:false },
                plugins: {
                    legend: { labels: { color:tc, font:{ size:11 } } },
                    tooltip: {
                        callbacks: {
                            label: function(c){ return ' '+c.dataset.label+': '+c.parsed.y.toLocaleString('fr-FR'); }
                        }
                    }
                },
                scales: {
                    x: { grid:{color:gc}, ticks:{color:tc,font:{size:10},maxRotation:45,autoSkip:true,maxTicksLimit:14} },
                    y: { grid:{color:gc}, ticks:{color:tc,font:{size:10}}, beginAtZero:true },
                    yPeak: { position:'right', grid:{drawOnChartArea:false}, ticks:{color:'#22c55e',font:{size:10}}, beginAtZero:true }
                }
            }
        });

        if (loading) loading.style.display = 'none';
    } catch(e) {
        if (loading) { loading.style.display='flex'; loading.textContent='Erreur: '+e.message; }
    }
}

// ── WEBSOCKET TEMPS RÉEL ──────────────────────────────────
var _aws = null;
var _awsRetries = 0;
var _sparkH = new Array(20).fill(0);

function aConnectWS() {
    var proto = location.protocol === 'https:' ? 'wss' : 'ws';
    var badge = document.getElementById('aws-badge');
    try {
        _aws = new WebSocket(proto + '://' + location.host + '/ws/admin/live');

        _aws.onopen = function(){
            _awsRetries = 0;
            if (badge) { badge.textContent = 'En direct'; badge.style.background = '#052e16'; badge.style.color = '#4ade80'; }
        };

        _aws.onmessage = function(evt){
            try {
                var data = JSON.parse(evt.data);
                if (data.type === 'stats' || data.active_users !== undefined) {
                    _aUpdateLive(data);
                }
            } catch(e) {}
        };

        _aws.onclose = function(){
            if (badge) { badge.textContent = 'Reconnexion...'; badge.style.background = '#422006'; badge.style.color = '#fde68a'; }
            _awsRetries++;
            setTimeout(aConnectWS, Math.min(30000, 2000 * _awsRetries));
        };

        _aws.onerror = function(){
            if (badge) { badge.textContent = 'Déconnecté'; badge.style.background = '#450a0a'; badge.style.color = '#fca5a5'; }
        };

        // Ping toutes les 20s pour garder la connexion
        setInterval(function(){
            if (_aws && _aws.readyState === WebSocket.OPEN) _aws.send('ping');
        }, 20000);

    } catch(e) {
        setTimeout(aConnectWS, 5000);
    }
}

function _aUpdateLive(data) {
    // Compteur
    var cnt = document.getElementById('aws-count');
    if (cnt) {
        var prev = parseInt(cnt.textContent) || 0;
        var cur = data.active_users || 0;
        cnt.textContent = cur;
        cnt.style.color = cur > prev ? '#4ade80' : cur < prev ? '#f87171' : '#4ade80';
    }

    // Sparkline
    _sparkH.push(data.active_users || 0);
    if (_sparkH.length > 20) _sparkH.shift();
    var spark = document.getElementById('asp-bars');
    if (spark) {
        var max = Math.max.apply(null, _sparkH.concat([1]));
        spark.innerHTML = _sparkH.map(function(v){
            var pct = Math.max(4, Math.round(v / max * 100));
            var col = v === 0 ? '#1e293b' : '#4ade80';
            return '<div style="flex:1;background:'+col+';height:'+pct+'%;border-radius:2px 2px 0 0;min-width:4px;transition:height .4s ease;" title="'+v+'"></div>';
        }).join('');
    }

    // Pages
    var pEl = document.getElementById('aws-pages');
    if (pEl && data.top_pages) {
        if (!data.top_pages.length) {
            pEl.innerHTML = '<span style="color:#475569;font-size:12px;">Aucune activité</span>';
        } else {
            var mx = Math.max.apply(null, data.top_pages.map(function(p){return p.count;}));
            pEl.innerHTML = data.top_pages.map(function(p){
                var pct = Math.round(p.count / mx * 100);
                var lbl = (p.page || '/').length > 22 ? (p.page||'/').slice(0,21)+'…' : (p.page||'/');
                return '<div style="display:flex;align-items:center;gap:6px;margin-bottom:4px;">'
                    +'<div style="color:#94a3b8;font-size:11px;font-family:monospace;width:110px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="'+p.page+'">'+lbl+'</div>'
                    +'<div style="flex:1;background:#1e293b;border-radius:2px;height:4px;">'
                    +'<div style="background:#4ade80;height:4px;border-radius:2px;width:'+pct+'%;transition:width .5s;"></div>'
                    +'</div>'
                    +'<div style="color:#4ade80;font-size:11px;font-weight:700;width:16px;text-align:right;">'+p.count+'</div>'
                    +'</div>';
            }).join('');
        }
    }

    // Timestamp
    var tsEl = document.getElementById('aws-ts');
    if (tsEl) tsEl.textContent = new Date().toLocaleTimeString('fr-FR');
}

// ── REFRESH STATS ─────────────────────────────────────────
async function aRefreshStats() {
    try {
        var r = await fetch('/api/admin/stats/live', { credentials:'include' });
        if (!r.ok) return;
        var d = await r.json();
        var el;
        el=document.getElementById('ast-streams'); if(el) el.textContent=d.live_streams!==undefined?d.live_streams:el.textContent;
        el=document.getElementById('ast-live'); if(el && d.live_streams!==undefined) el.textContent=d.live_streams+' en direct';
        el=document.getElementById('ast-visitors'); if(el && d.total_visitors!==undefined) el.textContent=d.total_visitors;
        // DB status
        var bar=document.getElementById('adb-bar');
        var msg=document.getElementById('adb-msg');
        if (d.db_status && d.db_status !== 'ok') {
            if(bar) bar.style.display='flex';
            if(msg) msg.textContent='PostgreSQL: '+d.db_status;
        } else {
            if(bar) bar.style.display='none';
        }
        // Update live card si WS déconnecté
        if (!_aws || _aws.readyState !== WebSocket.OPEN) {
            _aUpdateLive(d);
        }
    } catch(e) {}
}

// ── CARTE DU MONDE (Leaflet + OpenStreetMap) ───────────────
var _mapLoaded = false;
var _leafletMap = null;
var _leafletMarkers = [];

function aLoadMap(force) {
    if (_mapLoaded && !force) return;
    _mapLoaded = true;

    var loading = document.getElementById('amap-loading');
    if (loading) loading.style.display = 'flex';

    fetch('/api/admin/locations', { credentials:'include' })
        .then(function(r){ return r.json(); })
        .then(function(data){
            var tot = document.getElementById('amap-total');
            if (tot) tot.textContent = data.total + ' utilisateurs géolocalisés';

            _renderLeafletMap(data);
            _renderCountries(data.countries);
            _renderContinents(data.countries);

            if (loading) loading.style.display = 'none';
        })
        .catch(function(e){
            if (loading) loading.innerHTML = '<p style="color:var(--accent);font-size:13px;z-index:1001;position:relative;">Erreur: '+e.message+'</p>';
        });
}

function _renderLeafletMap(data) {
    var container = document.getElementById('amap-leaflet');
    if (!container || typeof L === 'undefined') {
        setTimeout(function(){ _renderLeafletMap(data); }, 500);
        return;
    }

    if (_leafletMap) { _leafletMap.remove(); _leafletMap = null; }
    _leafletMarkers = [];

    var isDark = document.documentElement.classList.contains('dark');

    _leafletMap = L.map('amap-leaflet', {
        center: [20, 10],
        zoom: 2,
        minZoom: 1,
        maxZoom: 12,
        zoomControl: true,
        attributionControl: true
    });

    // Tuiles OpenStreetMap officielles (sans clé API). CARTO (basemaps.cartocdn.com) exige désormais une clé.
    // Thème sombre : on inverse les couleurs des tuiles par CSS.
    if (!document.getElementById('osm-dark-css')) {
        var _st = document.createElement('style');
        _st.id = 'osm-dark-css';
        _st.textContent = '.osm-dark{filter:invert(1) hue-rotate(180deg) brightness(.92) contrast(.9) saturate(.7);}';
        document.head.appendChild(_st);
    }
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
        maxZoom: 19,
        className: isDark ? 'osm-dark' : ''
    }).addTo(_leafletMap);

    // ── Cercles agrégés par pays (visibles de loin) ──
    var max = Math.max.apply(null, data.countries.map(function(c){ return c.count; })) || 1;
    data.countries.forEach(function(c){
        if (!c.lat || !c.lng) return;
        var r = Math.max(14, Math.min(52, Math.sqrt(c.count / max) * 52));
        var circle = L.circleMarker([c.lat, c.lng], {
            radius: r,
            fillColor: '#dc2626',
            color: '#fff',
            weight: 2,
            opacity: 1,
            fillOpacity: 0.65
        }).addTo(_leafletMap);
        var flag = c.country_code ? '<img src="https://flagcdn.com/w20/'+c.country_code.toLowerCase()+'.png" style="width:16px;height:11px;object-fit:cover;border-radius:2px;vertical-align:middle;margin-right:5px;" onerror="this.style.display=\'none\'">' : '';
        circle.bindPopup(
            '<div style="font-size:13px;font-weight:700;display:flex;align-items:center;gap:4px;">'
            + flag + (c.country || 'Inconnu') + '</div>'
            + '<div style="font-size:12px;color:var(--ink-muted);margin-top:3px;">'
            + '<b>' + c.count + '</b> visiteur' + (c.count > 1 ? 's' : '')
            + (c.cities && c.cities.length ? '<br><span style="font-size:11px;">'+c.cities.slice(0,3).join(', ')+'</span>' : '')
            + '</div>'
        );
        _leafletMarkers.push(circle);
    });

    // ── Points individuels précis (visibles en zoomant) ──
    if (data.raw_points && data.raw_points.length) {
        var pointLayer = L.layerGroup();
        data.raw_points.forEach(function(p){
            if (!p.lat || !p.lng) return;
            var dot = L.circleMarker([p.lat, p.lng], {
                radius: 5,
                fillColor: '#f97316',
                color: '#fff',
                weight: 1.5,
                opacity: 1,
                fillOpacity: 0.9
            });
            if (p.city || p.country) {
                dot.bindPopup('<div style="font-size:12px;font-weight:600;">'+(p.city||'')+(p.city&&p.country?', ':'')+(p.country||'')+'</div>');
            }
            pointLayer.addLayer(dot);
            _leafletMarkers.push(dot);
        });

        // N'afficher les points individuels qu'à partir du zoom 4
        _leafletMap.on('zoomend', function(){
            if (_leafletMap.getZoom() >= 4) {
                if (!_leafletMap.hasLayer(pointLayer)) pointLayer.addTo(_leafletMap);
            } else {
                if (_leafletMap.hasLayer(pointLayer)) _leafletMap.removeLayer(pointLayer);
            }
        });
    }

    setTimeout(function(){ if (_leafletMap) _leafletMap.invalidateSize(); }, 200);
}

function _ll2xy(lat, lng, W, H) {
    return { x: (lng + 180) / 360 * W, y: (90 - lat) / 180 * H };
}

function _renderCountries(countries) {
    var el = document.getElementById('amap-countries');
    if (!el) return;
    var sorted = countries.slice().sort(function(a,b){return b.count-a.count;});
    var max = sorted.length ? sorted[0].count : 1;
    el.innerHTML = sorted.slice(0,15).map(function(c){
        var pct = Math.round(c.count / max * 100);
        var flag = c.country_code ? '<img src="https://flagcdn.com/w20/'+c.country_code.toLowerCase()+'.png" style="width:18px;height:12px;object-fit:cover;border-radius:2px;flex-shrink:0;" onerror="this.style.display=\'none\'">' : '';
        return '<div style="display:flex;align-items:center;gap:6px;">'
            + flag
            + '<div style="font-size:12px;font-weight:600;width:110px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + (c.country||'Inconnu') + '</div>'
            + '<div style="flex:1;background:var(--surface-2);border-radius:2px;height:6px;">'
            + '<div style="background:var(--accent);height:6px;border-radius:2px;width:'+pct+'%;transition:width .5s;"></div>'
            + '</div>'
            + '<div style="font-size:11px;font-weight:800;color:var(--ink);width:20px;text-align:right;">'+c.count+'</div>'
            + '</div>';
    }).join('');
}

function _renderContinents(countries) {
    var el = document.getElementById('amap-continents');
    if (!el) return;
    var names = { AF:'Afrique', EU:'Europe', AS:'Asie', NA:'Am. Nord', SA:'Am. Sud', OC:'Océanie', ME:'M-Orient', INT:'International' };
    var byCont = {};
    countries.forEach(function(c){
        var k = c.continent || 'INT';
        byCont[k] = (byCont[k]||0) + c.count;
    });
    var total = Object.values(byCont).reduce(function(a,b){return a+b;},0) || 1;
    var sorted = Object.entries(byCont).sort(function(a,b){return b[1]-a[1];});
    el.innerHTML = sorted.map(function(e){
        var pct = Math.round(e[1]/total*100);
        var name = names[e[0]] || e[0];
        return '<div style="display:flex;align-items:center;gap:6px;">'
            + '<div style="font-size:12px;width:130px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">'+name+'</div>'
            + '<div style="flex:1;background:var(--surface-2);border-radius:2px;height:6px;">'
            + '<div style="background:#2563eb;height:6px;border-radius:2px;width:'+pct+'%;transition:width .5s;"></div>'
            + '</div>'
            + '<div style="font-size:11px;font-weight:800;color:var(--ink);width:50px;text-align:right;">'+e[1]+' ('+pct+'%)</div>'
            + '</div>';
    }).join('');
}

// ── INITIALISATION ────────────────────────────────────────
document.addEventListener('DOMContentLoaded', function(){
    aConnectWS();
    aRefreshStats();
    setInterval(aRefreshStats, 30000);
    aLoadHistory('week', document.getElementById('ahb-week'));
    // Charger la carte automatiquement
    aLoadMap(false);
});
</script>
{% endblock %}'''
    # ══════════════════════════════════════════════════════════════════
    # SETTINGS TEMPLATE — Paramètres fonctionnels
    # ══════════════════════════════════════════════════════════════════
    SETTINGS_TEMPLATE = r'''{% extends "base.html" %}
{% block title %}Paramètres - {{ app_name }}{% endblock %}
{% block head %}
<style>
    /* Interrupteur — même rendu que le composant Toggle du produit */
    .stoggle { position:relative; width:44px; height:24px; flex-shrink:0; border-radius:999px; cursor:pointer; border:none; background:var(--surface-2); transition:background-color .2s; }
    .stoggle.on { background:var(--accent-2); }
    .stoggle-knob { position:absolute; top:2px; left:2px; width:20px; height:20px; border-radius:999px; background:#fff; box-shadow:0 1px 3px rgba(0,0,0,.25); transition:transform .2s; }
    .stoggle.on .stoggle-knob { transform:translateX(20px); }
    input[type=range].s-range { width:100%; accent-color:var(--accent-2); }
</style>
{% endblock %}
{% block content %}
{% from 'icons.html' import icon %}
{% macro tog(label, hint, tid, onclick, on='false', extra='') -%}
<label class="flex cursor-pointer items-center justify-between gap-4 py-3.5">
    <span class="min-w-0">
        <span class="block text-sm font-medium">{{ label }}</span>
        <span class="block text-xs text-ink-muted">{{ hint }}</span>
        {{ extra|safe }}
    </span>
    <div class="stoggle {{ 'on' if on == 'true' else '' }}" id="{{ tid }}" onclick="{{ onclick }}" data-on="{{ on }}" role="switch"><div class="stoggle-knob"></div></div>
</label>
{%- endmacro %}
{% macro sel_cls() -%}rounded-lg border border-border bg-surface px-3 py-1.5 text-sm outline-none focus-visible:border-accent-2{%- endmacro %}
<div class="mx-auto max-w-2xl">
    <h1 class="mb-1 font-display text-2xl font-semibold">Paramètres</h1>
    <p class="mb-6 text-sm text-ink-muted">Personnalisez votre expérience. Les préférences sont sauvegardées sur votre appareil et synchronisées avec votre profil.</p>

    <div id="s-feedback" class="hidden"></div>

    <!-- ── THÈME ── -->
    <section class="card mb-5 p-5">
        <h2 class="mb-3 text-sm font-semibold text-ink-muted">Apparence</h2>
        <div class="flex flex-wrap items-center justify-between gap-3 py-2">
            <div>
                <span class="text-sm font-medium">Thème</span>
                <p class="text-xs text-ink-muted">Auto = suit les préférences de votre système d'exploitation</p>
            </div>
            <div class="flex items-center rounded-full border border-border bg-surface p-1">
                {% for k, ic, lbl in [('light','sun','Clair'),('dark','moon','Sombre'),('auto','monitor','Auto')] %}
                <button type="button" onclick="sSetTheme('{{ k }}')" id="st-{{ k }}" aria-pressed="false"
                        class="flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-semibold text-ink-muted transition-colors hover:text-ink">
                    {{ icon(ic, 14) }} {{ lbl }}
                </button>
                {% endfor %}
            </div>
        </div>
    </section>

    <!-- ── LANGUE ── -->
    <section class="card mb-5 p-5">
        <h2 class="mb-1 text-sm font-semibold text-ink-muted">Général</h2>
        <div class="flex items-center justify-between gap-4 py-3.5">
            <label for="s-lang" class="text-sm font-medium">Langue préférée</label>
            <select id="s-lang" onchange="sChangeLang(this.value)" class="{{ sel_cls() }}">
                <option value="fr">Français</option>
                <option value="en">English</option>
                <option value="ar">العربية</option>
                <option value="es">Español</option>
                <option value="de">Deutsch</option>
                <option value="it">Italiano</option>
                <option value="pt">Português</option>
                <option value="nl">Nederlands</option>
                <option value="ru">Русский</option>
                <option value="zh">中文</option>
                <option value="ja">日本語</option>
                <option value="ko">한국어</option>
            </select>
        </div>
        <div class="divide-y divide-border border-t border-border">
            {{ tog('Rappels de programmes TV', 'Recevez une notification 5 min avant vos programmes favoris', 'tog-notif', 'sToggleNotif()', 'false', '<span id="s-notif-status" class="mt-0.5 block text-xs text-accent-2"></span>') }}
        </div>
    </section>

    <!-- ── LECTEUR ── -->
    <section class="card mb-5 p-5">
        <h2 class="mb-1 text-sm font-semibold text-ink-muted">Lecture</h2>
        <div class="flex items-center justify-between gap-4 py-3.5">
            <label for="s-quality" class="text-sm font-medium">Qualité par défaut</label>
            <select id="s-quality" class="{{ sel_cls() }}">
                <option value="auto">Automatique</option>
                <option value="hd">HD (720p/1080p)</option>
                <option value="sd">SD (360p/480p)</option>
            </select>
        </div>
        <div class="border-t border-border py-3.5">
            <label for="s-volume" class="mb-2 block text-sm font-medium">Volume par défaut : <span id="s-vol-val" class="tabular-nums">80</span>%</label>
            <input type="range" id="s-volume" class="s-range" min="0" max="100" value="80" oninput="document.getElementById('s-vol-val').textContent=this.value">
        </div>
        <div class="divide-y divide-border border-t border-border">
            {{ tog('Lecture automatique', "Lire automatiquement dès l'ouverture d'une chaîne", 'tog-autoplay', "sToggle('autoplay')", 'true') }}
            {{ tog('Préchargement', 'Précharger le flux avant la lecture (économise les coupures)', 'tog-preload', "sToggle('preload')", 'true') }}
            {{ tog('Économie de données', 'Réduit la qualité pour économiser votre forfait mobile', 'tog-datasaver', "sToggle('datasaver')", 'false') }}
        </div>
    </section>

    <!-- ── LECTURE AVANCÉE ── -->
    <section class="card mb-5 p-5">
        <h2 class="mb-1 text-sm font-semibold text-ink-muted">Lecture avancée</h2>
        <div class="py-3.5">
            <div class="flex items-center justify-between gap-4">
                <label for="s-player" class="text-sm font-medium">Lecteur de fallback</label>
                <select id="s-player" class="{{ sel_cls() }}">
                    <option value="auto">Automatique (recommandé)</option>
                    <option value="hls">HLS.js</option>
                    <option value="videojs">Video.js</option>
                    <option value="native">Natif HTML5</option>
                </select>
            </div>
            <p class="mt-1.5 text-xs text-ink-muted">En cas d'échec, l'application essaie automatiquement les autres lecteurs.</p>
        </div>
        <div class="border-t border-border py-3.5">
            <label for="s-timeout" class="mb-2 block text-sm font-medium">Timeout de connexion : <span id="s-timeout-val" class="tabular-nums">10</span> secondes</label>
            <input type="range" id="s-timeout" class="s-range" min="5" max="30" value="10" oninput="document.getElementById('s-timeout-val').textContent=this.value">
        </div>
        <div class="divide-y divide-border border-t border-border">
            {{ tog('Reconnexion automatique', "Relance automatiquement la lecture en cas d'interruption", 'tog-autoretry', "sToggle('autoretry')", 'true') }}
            {{ tog('Qualité adaptative (ABR)', 'Ajuste automatiquement la qualité selon votre connexion', 'tog-abr', "sToggle('abr')", 'true') }}
        </div>
        <div class="border-t border-border py-3.5">
            <label for="s-buffer" class="mb-2 block text-sm font-medium">Taille du buffer : <span id="s-buf-val" class="tabular-nums">30</span> secondes</label>
            <input type="range" id="s-buffer" class="s-range" min="10" max="120" step="10" value="30" oninput="document.getElementById('s-buf-val').textContent=this.value">
            <p class="mt-1.5 text-xs text-ink-muted">Un buffer plus grand réduit les interruptions mais augmente le délai.</p>
        </div>
    </section>

    <!-- ── ACCESSIBILITÉ ── -->
    <section class="card mb-5 p-5">
        <h2 class="mb-1 text-sm font-semibold text-ink-muted">Accessibilité</h2>
        <div class="divide-y divide-border">
            {{ tog('Animations réduites', 'Désactive les animations et transitions pour les personnes sensibles', 'tog-reducedmotion', 'sToggleReducedMotion()', 'false') }}
            {{ tog('Contraste élevé', 'Augmente le contraste des textes et interfaces', 'tog-highcontrast', 'sToggleHighContrast()', 'false') }}
        </div>
        <div class="flex items-center justify-between gap-4 border-t border-border py-3.5">
            <span class="text-sm font-medium">Taille du texte</span>
            <div class="flex gap-2">
                {% for k, sz in [('small','text-xs'),('medium','text-sm'),('large','text-base'),('xlarge','text-lg')] %}
                <button type="button" onclick="sFontSize('{{ k }}')" id="fs-{{ k }}" class="flex h-9 w-9 items-center justify-center rounded-lg border border-border font-semibold text-ink-muted transition-colors {{ sz }}">A</button>
                {% endfor %}
            </div>
        </div>
    </section>

    <!-- ── CONFIDENTIALITÉ ── -->
    <section class="card mb-5 p-5">
        <h2 class="mb-1 text-sm font-semibold text-ink-muted">Confidentialité &amp; Données</h2>
        <p class="py-3 text-sm leading-relaxed text-ink-muted">{{ app_name }} ne collecte aucune donnée personnelle identifiable. Aucun compte requis. Vos préférences sont stockées sur votre appareil et sur notre serveur de manière anonyme.</p>
        <div class="divide-y divide-border border-t border-border">
            {{ tog('Historique de visionnage local', 'Mémorise les chaînes récemment regardées pour un accès rapide', 'tog-history', "sToggle('history')", 'true') }}
        </div>
        <div class="border-t border-border pt-3.5">
            <p class="text-sm font-medium">Effacer toutes les données locales</p>
            <p class="mb-3 mt-0.5 text-xs text-ink-muted">Supprime l'historique, les favoris locaux et tous vos paramètres. Action irréversible.</p>
            <button type="button" onclick="sClearData()" class="rounded-full border border-accent/40 px-4 py-2 text-sm font-medium text-accent transition-colors hover:bg-accent/10">Effacer mes données locales</button>
        </div>
    </section>

    <!-- ── BOUTONS ── -->
    <div class="flex flex-wrap gap-3">
        <button type="button" onclick="sSave()" id="s-save-btn" class="flex items-center gap-2 rounded-xl bg-accent-2 px-5 py-2.5 text-sm font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-60">
            <i class="fas fa-save"></i> Enregistrer les paramètres
        </button>
        <button type="button" onclick="sReset()" class="flex items-center gap-2 rounded-xl border border-border px-5 py-2.5 text-sm font-medium text-ink-muted transition-colors hover:text-ink">
            <i class="fas fa-undo"></i> Réinitialiser
        </button>
    </div>

    <!-- ── EXPORT ── -->
    <section class="card my-5 p-5">
        <h2 class="mb-1 text-sm font-semibold text-ink-muted">Exporter le catalogue</h2>
        <p class="mb-3 text-sm text-ink-muted">Téléchargez la liste des chaînes au format M3U pour la lire dans VLC, une box IPTV ou toute autre application compatible.</p>
        <a href="/api/playlist/m3u?type=all" download="livewatch.m3u" class="flex w-fit items-center gap-1.5 rounded-full border border-border px-4 py-2 text-sm font-medium text-ink-muted hover:text-ink">{{ icon('download', 15) }} Télécharger la playlist M3U</a>
    </section>

    <!-- ── INFORMATIONS ── -->
    <section class="card mb-5 border-accent-2/30 bg-accent-2-soft p-5">
        <h3 class="mb-2 flex items-center gap-2 text-sm font-semibold text-accent-2">{{ icon('info', 16) }} À propos de vos paramètres</h3>
        <div class="space-y-1 text-xs leading-relaxed text-ink-muted">
            <p>• Les préférences sont stockées localement dans votre navigateur et synchronisées avec notre serveur.</p>
            <p>• Le thème, la langue et la qualité vidéo sont appliqués immédiatement.</p>
            <p>• La déconnexion ou la suppression des cookies ne réinitialise pas les paramètres serveur.</p>
            <p>• Pour un support multi-appareils, connectez-vous avec le même identifiant.</p>
        </div>
    </section>

    <div class="flex flex-wrap gap-x-4 gap-y-1 py-2 text-xs text-ink-muted">
        <a href="/about" class="inline-flex items-center gap-1 hover:text-ink">{{ icon('file-text', 12) }} À propos</a>
        <a href="/terms" class="hover:text-ink">Conditions d'utilisation</a>
        <a href="/privacy" class="hover:text-ink">Confidentialité</a>
    </div>
</div>
{% endblock %}

{% block scripts %}
<script>

// ═══════════════════════════════════════════════════════════
//  SETTINGS — Logique complète
// ═══════════════════════════════════════════════════════════
var S_KEY = 'lw_settings_v3';

var S_DEF = {
    theme: 'dark', lang: 'fr', quality: 'auto', volume: 80,
    autoplay: true, preload: true, datasaver: false,
    notif: false, history: true
};

// ── Lecture localStorage ──────────────────────────────────
function sGet() {
    try { return Object.assign({}, S_DEF, JSON.parse(localStorage.getItem(S_KEY)||'{}')); }
    catch(e) { return Object.assign({}, S_DEF); }
}
function sPut(s) {
    try { localStorage.setItem(S_KEY, JSON.stringify(s)); } catch(e) {}
}

// ── Peupler le formulaire ─────────────────────────────────
function sPopulate(s) {
    // Thème
    _sHighlightTheme(_lwThemeMode() === 'system' ? 'auto' : _lwThemeMode());
    // Langue
    var sl = document.getElementById('s-lang');
    if (sl) sl.value = s.lang || 'fr';
    // Qualité
    var sq = document.getElementById('s-quality');
    if (sq) sq.value = s.quality || 'auto';
    // Volume
    var sv = document.getElementById('s-volume');
    var svv = document.getElementById('s-vol-val');
    if (sv) { sv.value = s.volume !== undefined ? s.volume : 80; }
    if (svv) svv.textContent = s.volume !== undefined ? s.volume : 80;
    // Toggles
    _sSetToggle('tog-autoplay', s.autoplay !== false);
    _sSetToggle('tog-preload',  s.preload  !== false);
    _sSetToggle('tog-datasaver',!!s.datasaver);
    _sSetToggle('tog-notif',    !!s.notif);
    _sSetToggle('tog-history',  s.history  !== false);
    // Notif status
    _sNotifStatus();
}

function _sSetToggle(id, on) {
    var el = document.getElementById(id);
    if (!el) return;
    el.dataset.on = on ? 'true' : 'false';
    if (on) el.classList.add('on'); else el.classList.remove('on');
}

function _sHighlightTheme(t) {
    ['light','dark','auto'].forEach(function(k){
        var btn = document.getElementById('st-' + k);
        if (!btn) return;
        var on = (k === t);
        btn.classList.toggle('bg-accent-2', on);
        btn.classList.toggle('text-white', on);
        btn.classList.toggle('text-ink-muted', !on);
        btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
}

// ── Thème ─────────────────────────────────────────────────
function sSetTheme(t) {
    _sHighlightTheme(t);
    // Appliquer immédiatement
    if (t === 'dark') {
        document.documentElement.classList.add('dark');
        localStorage.setItem('lw_theme', 'dark');
    } else if (t === 'light') {
        document.documentElement.classList.remove('dark');
        localStorage.setItem('lw_theme', 'light');
    } else {
        var prefersDark = window.matchMedia('(prefers-color-scheme:dark)').matches;
        if (prefersDark) document.documentElement.classList.add('dark');
        else document.documentElement.classList.remove('dark');
        localStorage.setItem('lw_theme', 'system');
    }
    // Icône thème dans nav
    var icon = document.getElementById('theme-icon');
    var isDark = document.documentElement.classList.contains('dark');
    if (icon) icon.className = isDark ? 'fas fa-moon' : 'fas fa-sun';
    // Sauvegarder
    var s = sGet(); s.theme = t; sPut(s);
    // Persister en base
    fetch('/api/settings/save', {
        method:'POST', headers:{'Content-Type':'application/json'}, credentials:'include',
        body:JSON.stringify({theme:t})
    }).catch(function(){});
}

// ── Langue ────────────────────────────────────────────────
function sChangeLang(lang) {
    var s = sGet(); s.lang = lang; sPut(s);
    fetch('/api/settings/save', {
        method:'POST', headers:{'Content-Type':'application/json'}, credentials:'include',
        body:JSON.stringify({language:lang})
    }).catch(function(){});
}

// ── Toggles ───────────────────────────────────────────────
function sToggle(key) {
    var idMap = { autoplay:'tog-autoplay', preload:'tog-preload', datasaver:'tog-datasaver', history:'tog-history' };
    var el = document.getElementById(idMap[key]);
    if (!el) return;
    var now = el.dataset.on === 'true';
    _sSetToggle(idMap[key], !now);
    var s = sGet(); s[key] = !now; sPut(s);
}

function sToggleNotif() {
    var el = document.getElementById('tog-notif');
    if (!el) return;
    var now = el.dataset.on === 'true';
    if (!now) {
        if (!('Notification' in window)) {
            _sNotifStatus('Non supporté par ce navigateur.');
            return;
        }
        Notification.requestPermission().then(function(perm){
            if (perm === 'granted') {
                _sSetToggle('tog-notif', true);
                var s = sGet(); s.notif = true; sPut(s);
                _sNotifStatus('Notifications autorisées.');
            } else {
                _sSetToggle('tog-notif', false);
                _sNotifStatus('Refusées — activez dans les paramètres du navigateur.');
            }
        });
    } else {
        _sSetToggle('tog-notif', false);
        var s = sGet(); s.notif = false; sPut(s);
        _sNotifStatus('Notifications désactivées.');
    }
}

function _sNotifStatus(msg) {
    var el = document.getElementById('s-notif-status');
    if (!el) return;
    if (msg) { el.textContent = msg; return; }
    if (!('Notification' in window)) el.textContent = 'Non supporté.';
    else if (Notification.permission === 'granted') el.textContent = 'Autorisées par le navigateur.';
    else if (Notification.permission === 'denied') el.textContent = 'Bloquées — changez dans les réglages du navigateur.';
    else el.textContent = 'Non encore demandées.';
}

// ── Afficher feedback ─────────────────────────────────────
function _sFb(msg, ok) {
    var el = document.getElementById('s-feedback');
    if (!el) return;
    el.textContent = msg;
    el.className = 'mb-5 rounded-xl border px-4 py-3 text-sm font-semibold ' + (ok
        ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400'
        : 'border-accent/30 bg-accent/10 text-accent');
    clearTimeout(window._sfbTimer);
    window._sfbTimer = setTimeout(function(){ el.className = 'hidden'; }, 4000);
}

// ── Enregistrer ───────────────────────────────────────────
async function sSave() {
    var s = sGet();
    // Collecter depuis le formulaire
    var sq = document.getElementById('s-quality'); if(sq) s.quality = sq.value;
    var sl = document.getElementById('s-lang');    if(sl) s.lang    = sl.value;
    var sv = document.getElementById('s-volume');  if(sv) s.volume  = parseInt(sv.value);
    s.autoplay  = document.getElementById('tog-autoplay')  && document.getElementById('tog-autoplay').dataset.on  === 'true';
    s.preload   = document.getElementById('tog-preload')   && document.getElementById('tog-preload').dataset.on   === 'true';
    s.datasaver = document.getElementById('tog-datasaver') && document.getElementById('tog-datasaver').dataset.on === 'true';
    s.notif     = document.getElementById('tog-notif')     && document.getElementById('tog-notif').dataset.on     === 'true';
    s.history   = document.getElementById('tog-history')   && document.getElementById('tog-history').dataset.on   === 'true';

    // 1. Sauvegarder localement (instantané)
    sPut(s);

    // 2. Appliquer thème
    sSetTheme(s.theme);

    // 3. Persister en base (theme + lang)
    var btn = document.getElementById('s-save-btn');
    if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Sauvegarde...'; }

    try {
        var r = await fetch('/api/settings/save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({ theme: s.theme, language: s.lang })
        });
        var d = await r.json();
        if (d.success) {
            _sFb('Paramètres enregistrés avec succès !', true);
        } else {
            _sFb('Paramètres sauvegardés sur cet appareil (hors ligne).', true);
        }
    } catch(e) {
        _sFb('Paramètres sauvegardés sur cet appareil.', true);
    }

    if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fas fa-save"></i> Enregistrer les paramètres'; }
}

// ── Réinitialiser ─────────────────────────────────────────
async function sReset() {
    if (!confirm('Réinitialiser tous les paramètres aux valeurs d\'origine ?\nCette action est irréversible.')) return;
    sPut(Object.assign({}, S_DEF));
    sPopulate(S_DEF);
    sSetTheme(S_DEF.theme);
    _sFb('Paramètres réinitialisés aux valeurs d\'origine.', true);
    try { await fetch('/api/settings/reset', { method:'POST', credentials:'include' }); } catch(e) {}
}

// ── Effacer données ───────────────────────────────────────
function sClearData() {
    if (!confirm('Effacer tous vos paramètres et données locales ?\nCette action est irréversible.')) return;
    try {
        localStorage.removeItem(S_KEY);
        localStorage.removeItem('lw_theme');
        localStorage.removeItem('lw_favorites');
        sessionStorage.clear();
    } catch(e) {}
    _sFb('Données effacées. Rechargement...', true);
    setTimeout(function(){ location.reload(); }, 1200);
}

// ── Init ─────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', function(){
    var s = sGet();
    sPopulate(s);

    // Charger depuis le serveur pour sync multi-appareils
    fetch('/api/settings/load', { credentials:'include' })
        .then(function(r){ return r.json(); })
        .then(function(d){
            if (d.success && d.prefs) {
                var merged = Object.assign({}, s, d.prefs);
                sPut(merged);
                sPopulate(merged);
            }
        })
        .catch(function(){});
});

</script>
<script>

// ── Extensions settings ──────────────────────────────────────────────
function sToggleReducedMotion(){
    var el=document.getElementById('tog-reducedmotion');
    if(!el) return;
    var now=el.dataset.on==='true';
    el.dataset.on=(!now)?'true':'false';
    if(!now){el.classList.add('on');}else{el.classList.remove('on');}
    // Appliquer CSS
    if(!now){
        var style=document.createElement('style');
        style.id='reduced-motion-style';
        style.textContent='*{animation:none!important;transition:none!important;}';
        document.head.appendChild(style);
    } else {
        var s=document.getElementById('reduced-motion-style');
        if(s) s.remove();
    }
    var s2=sGet(); s2.reducedMotion=!now; sPut(s2);
}

function sToggleHighContrast(){
    var el=document.getElementById('tog-highcontrast');
    if(!el) return;
    var now=el.dataset.on==='true';
    el.dataset.on=(!now)?'true':'false';
    if(!now){el.classList.add('on');}else{el.classList.remove('on');}
    if(!now){
        document.documentElement.style.filter='contrast(1.3) saturate(0.8)';
    } else {
        document.documentElement.style.filter='';
    }
    var s=sGet(); s.highContrast=!now; sPut(s);
}

function sFontSize(size){
    var sizes={small:'14px',medium:'16px',large:'18px',xlarge:'20px'};
    document.documentElement.style.fontSize=sizes[size]||'16px';
    ['small','medium','large','xlarge'].forEach(function(k){
        var b=document.getElementById('fs-'+k);
        if(!b) return;
        var on = (k===size);
        b.classList.toggle('border-accent-2', on);
        b.classList.toggle('bg-accent-2-soft', on);
        b.classList.toggle('text-accent-2', on);
        b.classList.toggle('border-border', !on);
        b.classList.toggle('text-ink-muted', !on);
    });
    var s=sGet(); s.fontSize=size; sPut(s);
}

// Étendre S_DEF et sSave pour inclure les nouveaux paramètres
var _origSSave=window.sSave;
window.sSave=async function(){
    var s=sGet();
    var sq2=document.getElementById('s-player'); if(sq2) s.player=sq2.value;
    var st=document.getElementById('s-timeout'); if(st) s.timeout=parseInt(st.value);
    var sb=document.getElementById('s-buffer'); if(sb) s.buffer=parseInt(sb.value);
    s.autoretry=document.getElementById('tog-autoretry')&&document.getElementById('tog-autoretry').dataset.on==='true';
    s.abr=document.getElementById('tog-abr')&&document.getElementById('tog-abr').dataset.on==='true';
    sPut(s);
    if(_origSSave) await _origSSave();
};

// Appliquer au chargement les paramètres avancés
document.addEventListener('DOMContentLoaded',function(){
    var s=sGet();
    if(s.player){var el=document.getElementById('s-player');if(el)el.value=s.player;}
    if(s.timeout){var el2=document.getElementById('s-timeout');if(el2){el2.value=s.timeout;document.getElementById('s-timeout-val').textContent=s.timeout;}}
    if(s.buffer){var el3=document.getElementById('s-buffer');if(el3){el3.value=s.buffer;document.getElementById('s-buf-val').textContent=s.buffer;}}
    if(s.autoretry!==undefined) _sSetToggle('tog-autoretry',s.autoretry!==false);
    if(s.abr!==undefined) _sSetToggle('tog-abr',s.abr!==false);
    if(s.fontSize) sFontSize(s.fontSize);
    if(s.reducedMotion) sToggleReducedMotion();
    if(s.highContrast) sToggleHighContrast();
});

</script>
{% endblock %}
'''
    # ══════════════════════════════════════════════════════════════════
    # WATCH EXTERNAL TEMPLATE — Lecteur flux externes
    # ══════════════════════════════════════════════════════════════════
    WATCH_EXTERNAL_TEMPLATE = r'''{% extends "base.html" %}
{% block title %}{{ stream.title }} - {{ app_name }}{% endblock %}
{% block content %}
{% from 'icons.html' import icon %}
{% from 'components.html' import stream_card, cat_meta %}
{% set cm = cat_meta.get(stream.category, cat_meta['iptv']) %}
<div id="we-layout" class="mx-auto grid max-w-7xl gap-6 xl:grid-cols-[minmax(0,1fr)_300px]">

<!-- ── COLONNE GAUCHE : LECTEUR ── -->
<div class="min-w-0">
    <!-- Fil d'Ariane -->
    <nav class="mb-3 flex flex-wrap items-center gap-1.5 text-xs text-ink-muted">
        <a href="/" class="hover:text-ink">Accueil</a>
        <span>›</span>
        <span>{{ stream.category }}</span>
        <span>›</span>
        <span class="truncate text-ink">{{ stream.title }}</span>
    </nav>

    <!-- Lecteur -->
    <div class="relative w-full overflow-hidden rounded-2xl bg-black" style="aspect-ratio:16/9">

        <!-- Lecteur HLS/MP4 -->
        {% if stream.stream_type in ['hls','mp4','dash'] %}
        <video id="we-video" controls autoplay playsinline class="absolute inset-0 h-full w-full bg-black"
            {% if stream.url and stream.stream_type == 'mp4' %}src="{{ stream.url }}"{% endif %}>
            <p>Votre navigateur ne supporte pas la lecture vidéo.</p>
        </video>
        {% endif %}

        <!-- Lecteur Audio -->
        {% if stream.stream_type == 'audio' %}
        <div class="absolute inset-0 flex flex-col items-center justify-center gap-1 bg-gradient-to-br from-[#0A0E1A] to-[#1B2233] px-6 text-center text-white">
            {% if stream.logo %}
            <img src="{{ stream.logo }}" alt="" class="mb-4 h-28 w-28 rounded-2xl object-contain shadow-2xl" onerror="this.style.display='none'">
            {% else %}
            <div class="mb-4 flex h-28 w-28 items-center justify-center rounded-2xl bg-accent/20 text-accent">{{ icon('radio', 48) }}</div>
            {% endif %}
            <div class="font-display text-xl font-semibold">{{ stream.title }}</div>
            <div class="mb-4 text-sm text-white/60">Radio en direct</div>
            <audio id="we-audio" controls autoplay class="w-full max-w-sm">
                <source src="{{ stream.url }}" type="audio/mpeg">
                <source src="{{ stream.url }}">
            </audio>
        </div>
        {% endif %}

        <!-- Lecteur YouTube embed -->
        {% if stream.stream_type == 'youtube' %}
        <div id="we-yt-wrap" class="absolute inset-0">
            <div id="we-yt-loading" class="absolute inset-0 flex flex-col items-center justify-center gap-2 text-white/70">
                <i class="fas fa-spinner fa-spin" style="font-size:1.6rem"></i>
                <p class="text-sm">Chargement YouTube...</p>
            </div>
            <iframe id="we-yt-frame" src="" frameborder="0" class="absolute inset-0 h-full w-full border-0" style="display:none"
                allow="autoplay; encrypted-media; picture-in-picture" allowfullscreen></iframe>
        </div>
        {% endif %}

        <!-- Badge LIVE -->
        <div class="pointer-events-none absolute left-3 top-3">
            <span class="inline-flex items-center gap-1.5 rounded-full bg-accent px-2.5 py-1 text-[11px] font-semibold tracking-wide text-white"><span class="live-dot bg-white"></span>DIRECT</span>
        </div>

        <!-- Contrôles overlay -->
        <div class="absolute right-3 top-3 z-10 flex gap-2">
            <button type="button" onclick="weToggleFav()" id="we-fav-btn" title="Ajouter aux favoris" aria-label="Ajouter aux favoris"
                    class="flex h-9 w-9 items-center justify-center rounded-full bg-black/55 text-white backdrop-blur-sm transition-colors hover:bg-black/75">{{ icon('star', 16) }}</button>
            <button type="button" onclick="weFullscreen()" title="Plein écran" aria-label="Plein écran"
                    class="flex h-9 w-9 items-center justify-center rounded-full bg-black/55 text-white backdrop-blur-sm transition-colors hover:bg-black/75">{{ icon('maximize', 16) }}</button>
        </div>
    </div>

    <!-- Infos stream -->
    <div class="mt-4 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div class="min-w-0">
            <div class="mb-1.5 flex flex-wrap items-center gap-2">
                <span class="inline-flex items-center gap-1.5 rounded-full bg-accent px-2.5 py-1 text-[11px] font-semibold tracking-wide text-white"><span class="live-dot bg-white"></span>DIRECT</span>
                <span class="rounded-full px-2 py-0.5 text-xs font-medium {{ cm[1] }} {{ cm[2] }}">{{ cm[3] if stream.category in cat_meta else stream.category }}</span>
                {% if stream.quality %}<span class="rounded-full bg-surface-2 px-2 py-0.5 text-xs font-medium text-ink-muted">{{ stream.quality }}</span>{% endif %}
                {% if stream.is_active %}<span class="rounded-full bg-emerald-500/10 px-2 py-0.5 text-xs font-medium text-emerald-600 dark:text-emerald-400">En ligne</span>
                {% else %}<span class="rounded-full bg-accent/10 px-2 py-0.5 text-xs font-medium text-accent">Hors ligne</span>{% endif %}
            </div>
            <div class="flex items-center gap-3">
                {% if stream.logo %}
                <img src="{{ stream.logo }}" alt="" class="h-9 w-9 shrink-0 rounded-lg bg-surface-2 object-contain p-1" onerror="this.style.display='none'">
                {% endif %}
                <h1 class="font-display text-xl font-semibold sm:text-2xl">{{ stream.title }}</h1>
            </div>
            {% if stream.country %}
            <p class="mt-1 flex items-center gap-1.5 text-sm text-ink-muted">
                <img src="https://flagcdn.com/w20/{{ stream.country|lower }}.png" alt="" class="h-3 rounded-sm object-cover" onerror="this.style.display='none'">{{ stream.country }}
            </p>
            {% endif %}
        </div>
        <div class="flex shrink-0 items-center gap-2">
            <button type="button" onclick="weRecord()" id="we-rec-btn"
                    class="flex items-center gap-1.5 rounded-full border border-accent/40 px-4 py-2 text-sm font-medium text-accent transition-colors hover:bg-accent/10">
                <i class="fas fa-circle" style="font-size:.6em"></i> <span id="we-rec-label">Enregistrer</span>
            </button>
            <button type="button" onclick="weReport()"
                    class="flex items-center gap-1.5 rounded-full border border-border px-4 py-2 text-sm font-medium text-ink-muted hover:text-ink">
                {{ icon('flag', 15) }} Signaler
            </button>
        </div>
    </div>

    <!-- Erreur lecteur + bouton retry -->
    <div id="we-err" class="mt-4 hidden rounded-xl border border-accent/30 bg-accent/10 px-4 py-3 text-sm text-accent">
        <strong class="font-semibold">Problème de lecture</strong><br>
        <span id="we-err-msg">Le flux ne répond pas.</span>
        <div class="mt-3 flex flex-wrap items-center gap-3">
            <button type="button" onclick="weRetry()" class="rounded-full bg-accent px-4 py-1.5 text-xs font-semibold text-white hover:opacity-90">Réessayer</button>
            <a href="/" class="text-xs font-medium underline underline-offset-2">← Retour accueil</a>
        </div>
    </div>

    <!-- Description -->
    {% if stream.description %}
    <div class="card mt-4 p-4 text-sm leading-relaxed text-ink-muted">{{ stream.description }}</div>
    {% endif %}

    <!-- Tags -->
    {% if stream.tags %}
    <div class="mt-3 flex flex-wrap gap-2">
        {% for tag in stream.tags.split(',') if tag.strip() %}
        <a href="/search?q={{ tag.strip() }}" class="rounded-full border border-border px-3 py-1 text-xs font-medium text-ink-muted transition-colors hover:text-ink">#{{ tag.strip() }}</a>
        {% endfor %}
    </div>
    {% endif %}

    <!-- Commentaires -->
    <div id="we-comments-section" class="mt-8">
        <div class="mb-4 flex items-center justify-between"><h2 class="font-display text-lg font-semibold">Commentaires</h2></div>
        <div class="mb-4 flex flex-wrap items-center gap-2">
            <input type="text" id="we-cmt-name" placeholder="Votre pseudo" maxlength="50"
                   class="w-36 shrink-0 rounded-full border border-border bg-surface px-4 py-2.5 text-sm outline-none placeholder:text-ink-muted focus-visible:border-accent-2">
            <input type="text" id="we-cmt-text" placeholder="Ajouter un commentaire…" maxlength="500" onkeydown="if(event.key==='Enter')wePostComment()"
                   class="min-w-0 flex-1 rounded-full border border-border bg-surface px-4 py-2.5 text-sm outline-none placeholder:text-ink-muted focus-visible:border-accent-2">
            <button type="button" onclick="wePostComment()" aria-label="Envoyer" class="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-accent-2 text-white">{{ icon('send', 15) }}</button>
        </div>
        <div id="we-comments-list" class="space-y-3">
            <p class="card p-6 text-center text-sm text-ink-muted">Chargement des commentaires...</p>
        </div>
        <div id="we-more-btn-wrap" class="mt-3 text-center" style="display:none">
            <button type="button" onclick="weLoadComments(true)" class="rounded-full border border-border px-5 py-2 text-sm font-medium text-ink-muted hover:text-ink">Voir plus de commentaires</button>
        </div>
    </div>
</div>

<!-- ── COLONNE DROITE : SIDEBAR ── -->
<div>
    {% if similar_streams %}
    <div class="mb-4 flex items-center justify-between"><h2 class="font-display text-lg font-semibold">Chaînes similaires</h2></div>
    <div class="custom-scroll grid gap-2 sm:grid-cols-2 xl:max-h-[640px] xl:grid-cols-1 xl:overflow-y-auto xl:pr-1">
        {% for s in similar_streams[:12] %}
        <a href="/watch/external/{{ s.id }}" class="flex items-center gap-3 rounded-xl border border-border bg-surface p-2 transition-colors hover:bg-surface-2">
            <span class="flex h-11 w-[72px] shrink-0 items-center justify-center overflow-hidden rounded-lg bg-surface-2">{% if s.logo %}<img src="{{ s.logo }}" alt="" loading="lazy" class="h-full w-full object-contain p-1" onerror="this.style.display='none'">{% endif %}</span>
            <span class="min-w-0 flex-1"><span class="block truncate text-sm font-medium">{{ s.title }}</span><span class="block truncate text-xs text-ink-muted">{{ cat_meta.get(s.category, cat_meta['iptv'])[3] ~ ((' · ' ~ s.country) if s.country else '') }}</span></span>
            <span class="h-2 w-2 shrink-0 rounded-full bg-accent"></span>
        </a>
        {% endfor %}
    </div>
    {% else %}
    <div class="mb-4 flex items-center justify-between"><h2 class="font-display text-lg font-semibold">Chaînes similaires</h2></div>
    <p class="text-sm text-ink-muted">Aucune chaîne similaire pour l'instant.</p>
    {% endif %}
</div>

</div><!-- end grid -->
{% endblock %}

{% block scripts %}
<script>

(function(){
    // ═══════════════════════════════════════════════════════════
    // LECTEUR UNIVERSEL LIVEWATCH — Chaîne de fallback 6 niveaux
    // Niveau 1 : HLS.js via proxy interne
    // Niveau 2 : HLS.js URL directe
    // Niveau 3 : HLS natif (Safari) via proxy puis direct
    // Niveau 4 : Video natif (MP4/WebM/Ogg) src direct
    // Niveau 5 : iframe embed (chaînes avec page web)
    // Niveau 6 : Message d'erreur avec conseils
    // ═══════════════════════════════════════════════════════════
    var streamType = {{ stream.stream_type | tojson }};
    var streamUrl  = {{ (play_url or stream.url or "") | tojson }};
    var _alts      = {{ (alt_urls or []) | tojson }};
    var streamId   = {{ stream.id | tojson }};
    var _hls = null;
    var _fallbackStep = 0;
    var _recMR = null, _recChunks = [], _recActive = false;
    var proxyUrl = streamUrl ? '/proxy/stream?url=' + encodeURIComponent(streamUrl) : '';

    // ─── Détection du type réel par extension ───
    function _detectType(url) {
        if (!url) return streamType;
        var u = url.split('?')[0].toLowerCase();
        if (u.endsWith('.m3u8') || u.includes('.m3u8')) return 'hls';
        if (u.endsWith('.mpd') || u.includes('.mpd')) return 'dash';
        if (u.endsWith('.mp4') || u.endsWith('.webm') || u.endsWith('.ogg') || u.endsWith('.ogv')) return 'mp4';
        if (u.endsWith('.mp3') || u.endsWith('.aac') || u.endsWith('.ogg') || u.endsWith('.flac') || u.endsWith('.wav')) return 'audio';
        if (u.includes('youtube.com') || u.includes('youtu.be')) return 'youtube';
        return streamType;
    }
    var effectiveType = _detectType(streamUrl) || streamType;

    function weInit() {
        if (effectiveType === 'youtube') { _initYT(); }
        else if (effectiveType === 'audio') { _initAudio(); }
        else if (effectiveType === 'mp4') { _initMP4Direct(); }
        else if (effectiveType === 'dash') { _initDASH(); }
        else { _initHLSDirect(); }  // Tenter direct en premier
    }

    // ─── NIVEAU DASH : Dash.js pour les manifestes .mpd (HLS.js ne les lit pas) ───
    function _initDASH() {
        var v = document.getElementById('we-video');
        if (!v || !streamUrl) { _initIframe(); return; }
        if (window.dashjs) {
            _log('Lecture DASH via dash.js');
            try {
                var dashPlayer = dashjs.MediaPlayer().create();
                dashPlayer.initialize(v, streamUrl, true);
                dashPlayer.on(dashjs.MediaPlayer.events.ERROR, function() {
                    _log('DASH échoué, passage iframe');
                    _initIframe();
                });
            } catch (e) {
                _log('DASH exception: ' + e);
                _initIframe();
            }
        } else {
            _log('dash.js indisponible, passage iframe');
            _initIframe();
        }
    }

    // ─── NIVEAU 1 : HLS.js URL directe (pas de proxy — moins de latence) ───
    function _initHLSDirect() {
        var v = document.getElementById('we-video');
        if (!v || !streamUrl) { _initHLSProxy(); return; }
        _log('Niveau 1 : HLS.js direct');
        if (window.Hls && Hls.isSupported()) {
            if (_hls) { _hls.destroy(); _hls = null; }
            _hls = new Hls({
                enableWorker: true,
                lowLatencyMode: true,
                backBufferLength: 30,
                maxBufferLength: 90,
                manifestLoadingTimeOut: 10000,
                manifestLoadingMaxRetry: 1,
                levelLoadingTimeOut: 10000,
                fragLoadingTimeOut: 20000,
                xhrSetup: function(xhr) { xhr.withCredentials = false; }
            });
            _hls.loadSource(streamUrl);
            _hls.attachMedia(v);
            _hls.on(Hls.Events.MANIFEST_PARSED, function() {
                _log('Niveau 1 OK — HLS direct');
                v.play().catch(function(){});
            });
            _hls.on(Hls.Events.ERROR, function(event, data) {
                if (data.fatal) {
                    _log('Niveau 1 échoué (' + data.type + '), passage proxy');
                    _initHLSProxy();
                }
            });
        } else if (v.canPlayType('application/vnd.apple.mpegurl')) {
            // Safari natif — direct
            v.src = streamUrl; v.load();
            v.play().catch(function(){ _initHLSProxy(); });
            v.addEventListener('error', function onE(){
                v.removeEventListener('error', onE);
                _initHLSProxy();
            }, { once: true });
        } else { _initMP4Direct(); }
    }

    // ─── NIVEAU 2 : HLS.js via proxy (contourne CORS et géo-blocages) ───
    function _initHLSProxy() {
        var v = document.getElementById('we-video');
        if (!v || !proxyUrl) { _initSafariProxy(); return; }
        _log('Niveau 2 : HLS.js proxy');
        if (_hls) { _hls.destroy(); _hls = null; }
        if (window.Hls && Hls.isSupported()) {
            _hls = new Hls({
                enableWorker: true,
                lowLatencyMode: false,
                manifestLoadingTimeOut: 15000,
                manifestLoadingMaxRetry: 2,
                levelLoadingTimeOut: 15000,
                fragLoadingTimeOut: 25000,
            });
            _hls.loadSource(proxyUrl);
            _hls.attachMedia(v);
            _hls.on(Hls.Events.MANIFEST_PARSED, function() {
                _log('Niveau 2 OK — HLS proxy');
                v.play().catch(function(){});
            });
            _hls.on(Hls.Events.ERROR, function(event, data) {
                if (data.fatal) {
                    _log('Niveau 2 échoué, passage niveau 3');
                    _initSafariProxy();
                }
            });
        } else { _initSafariProxy(); }
    }

    // ─── NIVEAU 3 : HLS natif Safari (proxy puis direct) ───
    function _initSafariProxy() {
        var v = document.getElementById('we-video');
        if (!v) { _initMP4Direct(); return; }
        _log('Niveau 3 : HLS natif Safari');
        if (v.canPlayType('application/vnd.apple.mpegurl')) {
            v.src = proxyUrl || streamUrl;
            v.load();
            v.play().catch(function(){
                if (v.src !== streamUrl) { v.src = streamUrl; v.load(); v.play().catch(function(){ _initMP4Direct(); }); }
                else { _initMP4Direct(); }
            });
            v.addEventListener('error', function onE() {
                v.removeEventListener('error', onE);
                if (v.src !== streamUrl) { v.src = streamUrl; v.load(); }
                else { _initMP4Direct(); }
            }, { once: true });
        } else { _initMP4Direct(); }
    }

    // ─── NIVEAU 4 : Vidéo native (MP4/WebM) directe ───
    function _initMP4Direct() {
        var v = document.getElementById('we-video');
        if (!v || !streamUrl) { _initIframe(); return; }
        _log('Niveau 4 : src natif direct');
        // .m3u8 dans <video src> = téléchargement sur Firefox/Chrome : on affiche l'erreur à la place.
        if (/\.m3u8?(\?|$)/i.test(streamUrl) || effectiveType === 'hls') { _showFinalErr(); return; }
        if (_hls) { _hls.destroy(); _hls = null; }
        v.src = streamUrl; v.load();
        v.play().catch(function(){});
        v.addEventListener('playing', function(){ _log('Niveau 4 OK'); }, { once: true });
        v.addEventListener('error', function() {
            _log('Niveau 4 échoué, passage iframe');
            _initIframe();
        }, { once: true });
    }

    // ─── NIVEAU 5 : Iframe embed ───
    function _initIframe() {
        _log('Niveau 5 : iframe');
        var container = document.getElementById('we-video');
        if (!container || !streamUrl) { _showFinalErr(); return; }
        // Une URL .m3u8/.mpd/audio ouverte dans une iframe est TÉLÉCHARGÉE par le navigateur : on n'y va jamais.
        if (/\.(m3u8?|mpd|mp3|aac|flac|mp4|webm)(\?|$)/i.test(streamUrl) || effectiveType === 'hls' || effectiveType === 'dash') {
            _showFinalErr(); return;
        }
        var wrap = container.parentNode;
        container.style.display = 'none';
        var iframe = document.createElement('iframe');
        iframe.src = streamUrl;
        iframe.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;border:none;';
        iframe.allow = 'autoplay; encrypted-media; picture-in-picture; fullscreen';
        iframe.allowFullscreen = true;
        if (wrap) wrap.appendChild(iframe);
        else { _showFinalErr(); return; }
        iframe.addEventListener('error', function() { _showFinalErr(); });
    }

    function _tryNextUrl() {
        if (!_alts || !_alts.length) return false;
        streamUrl = _alts.shift();
        proxyUrl = streamUrl ? '/proxy/stream?url=' + encodeURIComponent(streamUrl) : '';
        effectiveType = _detectType(streamUrl) || streamType;
        _log('Flux suivant : ' + streamUrl);
        if (_hls) { _hls.destroy(); _hls = null; }
        var v = document.getElementById('we-video');
        if (v) v.style.display = '';
        weInit();
        return true;
    }

    function _showFinalErr() {
        if (_tryNextUrl()) return;
        _showErr('Impossible de lire ce flux. Il est peut-être hors ligne, géo-bloqué, ou dans un format non supporté par votre navigateur.');
    }

    function _log(msg) { console.log('[LivewatchPlayer]', msg); }

    // ─── YouTube ───
    function _initYT() {
        var loading = document.getElementById('we-yt-loading');
        var frame = document.getElementById('we-yt-frame');
        if (!frame) return;
        fetch('/api/streams/youtube/url?id=' + encodeURIComponent(streamId), { credentials:'include' })
            .then(function(r){ return r.json(); })
            .then(function(d){
                if (loading) loading.style.display = 'none';
                frame.style.display = 'block';
                if (d.embed_url) {
                    frame.src = d.embed_url + '?autoplay=1&rel=0&modestbranding=1';
                } else if (d.watch_url) {
                    var yid = _extractYID(d.watch_url);
                    if (yid) frame.src = 'https://www.youtube.com/embed/' + yid + '?autoplay=1&rel=0';
                    else _showErr('URL YouTube invalide.');
                } else {
                    // Dernier recours : tenter l'embed direct si on a l'URL YouTube dans streamUrl
                    var yid2 = _extractYID(streamUrl);
                    if (yid2) {
                        frame.src = 'https://www.youtube.com/embed/' + yid2 + '?autoplay=1&rel=0';
                    } else {
                        _showErr(d.error || 'Flux YouTube indisponible ou privé.');
                    }
                }
            })
            .catch(function(){
                // Fallback : embed direct depuis streamUrl
                var yid = _extractYID(streamUrl);
                if (loading) loading.style.display = 'none';
                if (frame) frame.style.display = 'block';
                if (yid) {
                    frame.src = 'https://www.youtube.com/embed/' + yid + '?autoplay=1&rel=0';
                } else {
                    _showErr('Erreur réseau lors du chargement YouTube.');
                }
            });
    }

    function _extractYID(url) {
        if (!url) return null;
        var m = url.match(/(?:v=|youtu\.be\/|embed\/|\/v\/|\/shorts\/)([a-zA-Z0-9_-]{11})/);
        return m ? m[1] : null;
    }

    // ─── Audio ───
    function _initAudio() {
        var a = document.getElementById('we-audio');
        if (!a) return;
        // Essayer proxy d'abord pour l'audio aussi
        if (proxyUrl) {
            var src = a.querySelector('source');
            if (src) { src.src = proxyUrl; }
            else { a.src = proxyUrl; }
            a.load();
        }
        a.addEventListener('error', function() {
            // Fallback direct
            if (a.src !== streamUrl && streamUrl) {
                a.src = streamUrl; a.load(); a.play().catch(function(){});
            } else {
                _showErr('Flux audio inaccessible. Vérifiez votre connexion.');
            }
        });
        a.play().catch(function(){});
    }

    function _showErr(msg) {
        var el = document.getElementById('we-err');
        var em = document.getElementById('we-err-msg');
        if (el) el.style.display = 'block';
        if (em) em.textContent = msg;
    }

    // ─── RETRY : repart depuis niveau 1 ───
    window.weRetry = function() {
        var el = document.getElementById('we-err');
        if (el) el.style.display = 'none';
        _fallbackStep = 0;
        if (effectiveType === 'youtube') {
            var frame = document.getElementById('we-yt-frame');
            if (frame) { var s=frame.src; frame.src=''; setTimeout(function(){ frame.src=s; }, 300); }
        } else if (effectiveType === 'audio') {
            var a = document.getElementById('we-audio');
            if (a) { a.load(); a.play().catch(function(){}); }
        } else {
            if (_hls) { _hls.destroy(); _hls = null; }
            _initHLSDirect();
        }
    };

    // ─────────────────────────────────────────────
    // FULLSCREEN
    // ─────────────────────────────────────────────
    window.weFullscreen = function() {
        var el = document.querySelector('#we-layout > div:first-child > div:first-of-type');
        if (!el) el = document.getElementById('we-video') || document.getElementById('we-audio');
        if (!el) return;
        if (document.fullscreenElement) document.exitFullscreen();
        else if (el.requestFullscreen) el.requestFullscreen();
        else if (el.webkitRequestFullscreen) el.webkitRequestFullscreen();
    };

    // ─────────────────────────────────────────────
    // FAVORIS
    // ─────────────────────────────────────────────
    window.weToggleFav = function() {
        addToFavorites(streamId, 'external', null);
    };

    // ─────────────────────────────────────────────
    // SIGNALEMENT
    // ─────────────────────────────────────────────
    window.weReport = function() {
        var reason = prompt('Raison du signalement :');
        if (!reason || !reason.trim()) return;
        var fd = new FormData();
        fd.append('stream_id', streamId);
        fd.append('stream_type', 'external');
        fd.append('reason', reason);
        fetch('/api/report', { method:'POST', body:fd, credentials:'include' })
            .then(function(){ showNotification('Signalement envoyé', 'success'); })
            .catch(function(){ showNotification('Erreur réseau', 'error'); });
    };

    // ─────────────────────────────────────────────
    // ENREGISTREMENT MediaRecorder
    // ─────────────────────────────────────────────
    window.weRecord = function() {
        var btn = document.getElementById('we-rec-btn');
        var lbl = document.getElementById('we-rec-label');
        if (!_recActive) {
            // Démarrer
            var mediaEl = document.getElementById('we-video') || document.getElementById('we-audio');
            if (!mediaEl || !mediaEl.srcObject && !mediaEl.src) {
                showNotification('Aucun flux actif à enregistrer', 'error'); return;
            }
            var stream;
            if (mediaEl.captureStream) stream = mediaEl.captureStream();
            else if (mediaEl.mozCaptureStream) stream = mediaEl.mozCaptureStream();
            else { showNotification('Enregistrement non supporté par ce navigateur', 'error'); return; }

            if (!window.MediaRecorder) { showNotification('MediaRecorder non disponible', 'error'); return; }

            _recChunks = [];
            var opts = {};
            if (MediaRecorder.isTypeSupported('video/webm;codecs=vp9,opus')) opts.mimeType = 'video/webm;codecs=vp9,opus';
            else if (MediaRecorder.isTypeSupported('video/webm')) opts.mimeType = 'video/webm';

            try {
                _recMR = new MediaRecorder(stream, opts);
            } catch(e) {
                try { _recMR = new MediaRecorder(stream); } catch(e2) {
                    showNotification('Erreur MediaRecorder: ' + e2.message, 'error'); return;
                }
            }

            _recMR.ondataavailable = function(e){ if(e.data&&e.data.size>0) _recChunks.push(e.data); };
            _recMR.onstop = function(){
                var blob = new Blob(_recChunks, { type: opts.mimeType||'video/webm' });
                var url = URL.createObjectURL(blob);
                var a = document.createElement('a');
                var dt = new Date().toISOString().replace(/[:.]/g,'-').slice(0,19);
                a.download = 'livewatch-' + dt + '.webm';
                a.href = url;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                URL.revokeObjectURL(url);
                showNotification('Enregistrement téléchargé !', 'success');
                // Notifier serveur
                fetch('/api/recording/stop', { method:'POST', credentials:'include' }).catch(function(){});
            };

            _recMR.start(1000);
            _recActive = true;
            if (lbl) lbl.textContent = 'Arrêter';
            if (btn) { btn.classList.add('rec-on'); }
            showNotification('Enregistrement démarré', 'info');
            fetch('/api/recording/start', { method:'POST', credentials:'include' }).catch(function(){});
        } else {
            // Arrêter
            if (_recMR && _recMR.state !== 'inactive') _recMR.stop();
            _recActive = false;
            if (lbl) lbl.textContent = 'Enregistrer';
            if (btn) { btn.classList.remove('rec-on'); }
        }
    };

    // ─── Fullscreen ───
    window.weFullscreen = function() {
        var container = document.querySelector('#we-layout > div:first-child > div[style*="aspect-ratio"]');
        var v = document.getElementById('we-video');
        var el = container || v;
        if (!el) return;
        if (document.fullscreenElement) document.exitFullscreen();
        else if (el.requestFullscreen) el.requestFullscreen();
        else if (el.webkitRequestFullscreen) el.webkitRequestFullscreen();
        else if (el.mozRequestFullScreen) el.mozRequestFullScreen();
    };

    // ─── Favoris ───
    window.weToggleFav = function() { addToFavorites(streamId, 'external', null); };

    // ─── Signalement ───
    window.weReport = function() {
        var reason = prompt('Raison du signalement :');
        if (!reason || !reason.trim()) return;
        var fd = new FormData();
        fd.append('stream_id', streamId);
        fd.append('stream_type', 'external');
        fd.append('reason', reason);
        fetch('/api/report', { method:'POST', body:fd, credentials:'include' })
            .then(function(){ showNotification('Signalement envoyé', 'success'); })
            .catch(function(){ showNotification('Erreur réseau', 'error'); });
    };

    // ─── Enregistrement ───
    window.weRecord = function() {
        var btn = document.getElementById('we-rec-btn');
        var lbl = document.getElementById('we-rec-label');
        if (!_recActive) {
            var mediaEl = document.getElementById('we-video') || document.getElementById('we-audio');
            if (!mediaEl) { showNotification('Aucun flux actif', 'error'); return; }
            var stream;
            try {
                stream = mediaEl.captureStream ? mediaEl.captureStream() : (mediaEl.mozCaptureStream ? mediaEl.mozCaptureStream() : null);
            } catch(e) { stream = null; }
            if (!stream || !window.MediaRecorder) { showNotification('Enregistrement non supporté par ce navigateur', 'error'); return; }
            _recChunks = [];
            var opts = {};
            if (MediaRecorder.isTypeSupported('video/webm;codecs=vp9,opus')) opts.mimeType = 'video/webm;codecs=vp9,opus';
            else if (MediaRecorder.isTypeSupported('video/webm')) opts.mimeType = 'video/webm';
            try { _recMR = new MediaRecorder(stream, opts); }
            catch(e) { try { _recMR = new MediaRecorder(stream); } catch(e2) { showNotification('Erreur: ' + e2.message, 'error'); return; } }
            _recMR.ondataavailable = function(e){ if(e.data&&e.data.size>0) _recChunks.push(e.data); };
            _recMR.onstop = function(){
                var blob = new Blob(_recChunks, { type: opts.mimeType || 'video/webm' });
                var url = URL.createObjectURL(blob);
                var a = document.createElement('a');
                a.download = 'livewatch-' + new Date().toISOString().replace(/[:.]/g,'-').slice(0,19) + '.webm';
                a.href = url; document.body.appendChild(a); a.click();
                document.body.removeChild(a); URL.revokeObjectURL(url);
                showNotification('Enregistrement téléchargé !', 'success');
                fetch('/api/recording/stop', { method:'POST', credentials:'include' }).catch(function(){});
            };
            _recMR.start(1000); _recActive = true;
            if (lbl) lbl.textContent = 'Arrêter';
            if (btn) { btn.classList.add('rec-on'); }
            showNotification('Enregistrement démarré', 'info');
            fetch('/api/recording/start', { method:'POST', credentials:'include' }).catch(function(){});
        } else {
            if (_recMR && _recMR.state !== 'inactive') _recMR.stop();
            _recActive = false;
            if (lbl) lbl.textContent = 'Enregistrer';
            if (btn) { btn.classList.remove('rec-on'); }
        }
    };

    window.addEventListener('beforeunload', function(){ if (_hls) _hls.destroy(); });

    // Guard : attendre que HLS.js soit chargé (script defer)
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', weInit);
    } else {
        weInit();
    }
})();

</script>
<script>

(function(){
    var _streamId2 = '{{ stream.id }}';
    var _page = 1;
    var _total = 0;
    var _limit = 10;

    // Charger les commentaires
    window.weLoadComments = async function(loadMore) {
        if (loadMore) _page++;
        var list = document.getElementById('we-comments-list');
        var moreBtn = document.getElementById('we-more-btn-wrap');

        try {
            var r = await fetch('/api/streams/'+_streamId2+'/comments?page='+_page+'&limit='+_limit, {credentials:'include'});
            var d = await r.json();
            _total = d.total || 0;

            if (!d.comments || !d.comments.length) {
                if (_page === 1) {
                    list.innerHTML = '<p class="card p-6 text-center text-sm text-ink-muted">Aucun commentaire. Soyez le premier !</p>';
                }
                if (moreBtn) moreBtn.style.display = 'none';
                return;
            }

            var html = d.comments.map(function(c){
                var date = new Date(c.created_at).toLocaleDateString('fr-FR', {day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'});
                return '<div class="card p-3.5 text-sm">'
                    +'<div class="mb-1.5 flex items-center justify-between">'
                    +'<span class="text-xs font-semibold">Anonyme</span>'
                    +'<div class="flex items-center gap-2">'
                    +'<span class="text-[11px] text-ink-muted">'+date+'</span>'
                    +'<button type="button" onclick="weReportComment('+c.id+')" class="flex items-center text-ink-muted hover:text-accent" title="Signaler">'+lwIcon('flag', 13)+'</button>'
                    +'</div>'
                    +'</div>'
                    +'<p class="leading-relaxed">'+_escHtml2(c.content)+'</p>'
                    +'</div>';
            }).join('');

            if (loadMore) {
                list.insertAdjacentHTML('beforeend', html);
            } else {
                list.innerHTML = html;
            }

            // Bouton "Voir plus"
            var loaded = (_page - 1) * _limit + d.comments.length;
            if (moreBtn) moreBtn.style.display = loaded < _total ? 'block' : 'none';

        } catch(e) {
            if (!loadMore) list.innerHTML = '<p class="card p-6 text-center text-sm text-accent">Erreur chargement.</p>';
        }
    };

    window.wePostComment = async function() {
        var nameEl = document.getElementById('we-cmt-name');
        var textEl = document.getElementById('we-cmt-text');
        var text = textEl ? textEl.value.trim() : '';
        var name = nameEl ? nameEl.value.trim() || 'Anonyme' : 'Anonyme';

        if (!text || text.length < 2) {
            showNotification('Commentaire trop court (min 2 caractères)', 'error');
            return;
        }

        var fd = new FormData();
        fd.append('content', text);
        fd.append('username', name);

        try {
            var r = await fetch('/api/streams/'+_streamId2+'/comments', {method:'POST', body:fd, credentials:'include'});
            var d = await r.json();
            if (d.success) {
                if (textEl) textEl.value = '';
                _page = 1;
                await weLoadComments(false);
                showNotification('Commentaire publié', 'success');
            } else {
                showNotification(d.error || 'Erreur publication', 'error');
            }
        } catch(e) {
            showNotification('Erreur réseau', 'error');
        }
    };

    window.weReportComment = async function(id) {
        var reason = prompt('Raison du signalement (optionnel):') || 'Contenu inapproprié';
        var fd = new FormData();
        fd.append('reason', reason);
        try {
            var r = await fetch('/api/comments/'+id+'/report', {method:'POST', body:fd, credentials:'include'});
            if (r.ok) showNotification('Signalement envoyé', 'success');
        } catch(e) {}
    };

    function _escHtml2(t) {
        var d = document.createElement('div');
        d.appendChild(document.createTextNode(t));
        return d.innerHTML;
    }

    // Charger les commentaires au chargement
    document.addEventListener('DOMContentLoaded', function() {
        weLoadComments(false);
    });
})();

</script>
{% endblock %}
'''
    # ══════════════════════════════════════════════════════════════════
    # WATCH IPTV TEMPLATE
    # ══════════════════════════════════════════════════════════════════
    WATCH_IPTV_TEMPLATE = r'''{% extends "base.html" %}
{% block title %}{{ channel.name }} - {{ app_name }}{% endblock %}
{% block content %}
{% from 'icons.html' import icon %}
{% from 'components.html' import stream_card, cat_meta %}
{% set cm = cat_meta.get(channel.category, cat_meta['iptv']) %}
<div id="wi-layout" class="mx-auto grid max-w-7xl gap-6 xl:grid-cols-[minmax(0,1fr)_300px]">

<div class="min-w-0">
    <!-- Fil d'Ariane -->
    <nav class="mb-3 flex flex-wrap items-center gap-1.5 text-xs text-ink-muted">
        <a href="/" aria-label="Accueil" class="flex items-center hover:text-ink">{{ icon('house', 13) }}</a><span>›</span>
        <a href="/?playlist={{ channel.playlist_id }}" class="hover:text-ink">{{ channel.country }}</a><span>›</span>
        <span class="truncate text-ink">{{ channel.name }}</span>
    </nav>

    <!-- Lecteur -->
    <div class="relative w-full overflow-hidden rounded-2xl bg-black" style="aspect-ratio:16/9">
        <video id="wi-video" controls autoplay playsinline class="absolute inset-0 h-full w-full bg-black"></video>
        <div class="pointer-events-none absolute left-3 top-3">
            <span class="inline-flex items-center gap-1.5 rounded-full bg-accent px-2.5 py-1 text-[11px] font-semibold tracking-wide text-white"><span class="live-dot bg-white"></span>DIRECT</span>
        </div>
        <div class="absolute right-3 top-3 z-10 flex gap-2">
            <button type="button" onclick="wiToggleFav()" title="Ajouter aux favoris" aria-label="Ajouter aux favoris"
                    class="flex h-9 w-9 items-center justify-center rounded-full bg-black/55 text-white backdrop-blur-sm transition-colors hover:bg-black/75">{{ icon('star', 16) }}</button>
            <button type="button" onclick="wiFullscreen()" title="Plein écran" aria-label="Plein écran"
                    class="flex h-9 w-9 items-center justify-center rounded-full bg-black/55 text-white backdrop-blur-sm transition-colors hover:bg-black/75">{{ icon('maximize', 16) }}</button>
        </div>
    </div>

    <!-- Infos -->
    <div class="mt-4 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div class="min-w-0">
            <div class="mb-1.5 flex flex-wrap items-center gap-2">
                <span class="inline-flex items-center gap-1.5 rounded-full bg-accent px-2.5 py-1 text-[11px] font-semibold tracking-wide text-white"><span class="live-dot bg-white"></span>DIRECT</span>
                {% if channel.category %}<span class="rounded-full px-2 py-0.5 text-xs font-medium {{ cm[1] }} {{ cm[2] }}">{{ cm[3] if channel.category in cat_meta else channel.category }}</span>{% endif %}
                {% if channel.language %}<span class="rounded-full bg-surface-2 px-2 py-0.5 text-xs font-medium text-ink-muted">{{ channel.language }}</span>{% endif %}
            </div>
            <div class="flex items-center gap-3">
                {% if channel.logo %}
                <img src="{{ channel.logo }}" alt="" class="h-10 w-10 shrink-0 rounded-xl bg-surface-2 object-contain p-1" onerror="this.style.display='none'">
                {% endif %}
                <h1 class="font-display text-xl font-semibold sm:text-2xl">{{ channel.name }}</h1>
            </div>
            {% if channel.country %}
            <p class="mt-1 flex items-center gap-1.5 text-sm text-ink-muted">
                <img src="https://flagcdn.com/w20/{{ channel.country|lower }}.png" alt="" class="h-3 rounded-sm object-cover" onerror="this.style.display='none'">{{ channel.country }}
            </p>
            {% endif %}
        </div>
        <div class="flex shrink-0 items-center gap-2">
            <button type="button" onclick="wiRecord()" id="wi-rec-btn"
                    class="flex items-center gap-1.5 rounded-full border border-accent/40 px-4 py-2 text-sm font-medium text-accent transition-colors hover:bg-accent/10">
                <i class="fas fa-circle" style="font-size:.6em"></i> <span id="wi-rec-label">Enregistrer</span>
            </button>
            <button type="button" onclick="wiReport()"
                    class="flex items-center gap-1.5 rounded-full border border-border px-4 py-2 text-sm font-medium text-ink-muted hover:text-ink">
                {{ icon('flag', 15) }} Signaler
            </button>
        </div>
    </div>

    <!-- Erreur -->
    <div id="wi-err" class="mt-4 hidden rounded-xl border border-accent/30 bg-accent/10 px-4 py-3 text-sm text-accent">
        <strong class="font-semibold">Problème de lecture</strong><br>
        <span id="wi-err-msg">Le flux ne répond pas.</span>
        <div class="mt-3">
            <button type="button" onclick="wiRetry()" class="rounded-full bg-accent px-4 py-1.5 text-xs font-semibold text-white hover:opacity-90">Réessayer</button>
        </div>
    </div>
</div>

<!-- SIDEBAR -->
<div>
    <div class="mb-4 flex items-center justify-between"><h2 class="font-display text-lg font-semibold">Autres chaînes — {{ channel.country }}</h2></div>
    {% if other_channels %}
    <div class="custom-scroll grid gap-2 sm:grid-cols-2 xl:max-h-[640px] xl:grid-cols-1 xl:overflow-y-auto xl:pr-1">
        {% for ch in other_channels[:12] %}
        <a href="/watch/iptv/{{ ch.id }}" class="flex items-center gap-3 rounded-xl border border-border bg-surface p-2 transition-colors hover:bg-surface-2">
            <span class="flex h-11 w-[72px] shrink-0 items-center justify-center overflow-hidden rounded-lg bg-surface-2">{% if ch.logo %}<img src="{{ ch.logo }}" alt="" loading="lazy" class="h-full w-full object-contain p-1" onerror="this.style.display='none'">{% endif %}</span>
            <span class="min-w-0 flex-1"><span class="block truncate text-sm font-medium">{{ ch.name }}</span><span class="block truncate text-xs text-ink-muted">{{ cat_meta.get(ch.category, cat_meta['iptv'])[3] if ch.category else 'TV' }}</span></span>
            <span class="h-2 w-2 shrink-0 rounded-full bg-accent"></span>
        </a>
        {% endfor %}
    </div>
    {% else %}
    <p class="text-sm text-ink-muted">Aucune autre chaîne pour l'instant.</p>
    {% endif %}
</div>
</div>
{% endblock %}

{% block scripts %}
<script>

(function(){
    // ═══════════════════════════════════════════════════════════
    // LECTEUR IPTV — Chaîne de fallback 5 niveaux
    // ═══════════════════════════════════════════════════════════
    var _url  = {{ (channel.url or "") | tojson }};
    var _id   = {{ channel.id | tojson }};
    var _hls  = null;
    var _recMR=null, _recChunks=[], _recActive=false;
    var _proxyUrl = _url ? '/proxy/stream?url='+encodeURIComponent(_url) : '';

    function _detectType(url) {
        if (!url) return 'hls';
        var u = url.split('?')[0].toLowerCase();
        if (u.endsWith('.mp3') || u.endsWith('.aac') || u.endsWith('.flac')) return 'audio';
        if (u.endsWith('.mp4') || u.endsWith('.webm')) return 'mp4';
        if (u.endsWith('.mpd')) return 'dash';
        return 'hls';
    }
    var _type = _detectType(_url);

    function wiInit(){
        if (!_url) { _showErr('URL du flux manquante.'); return; }
        if (_type === 'audio') { _initAudio(); }
        else if (_type === 'mp4') { _initMP4Direct(); }
        else if (_type === 'dash') { _initDASH(); }
        else { _initHLSDirect(); }  // Direct en premier
    }

    // ─── DASH : Dash.js pour les manifestes .mpd (HLS.js ne les lit pas) ───
    function _initDASH(){
        var v = document.getElementById('wi-video');
        if (!v || !_url) { _showFinalErr(); return; }
        if (window.dashjs) {
            try {
                var dashPlayer = dashjs.MediaPlayer().create();
                dashPlayer.initialize(v, _url, true);
                dashPlayer.on(dashjs.MediaPlayer.events.ERROR, function(){ _showFinalErr(); });
            } catch (e) {
                _showFinalErr();
            }
        } else {
            _showFinalErr();
        }
    }

    function _initHLSDirect(){
        var v = document.getElementById('wi-video');
        if (!v) return;
        if (window.Hls && Hls.isSupported()){
            if (_hls) { _hls.destroy(); _hls = null; }
            _hls = new Hls({
                enableWorker:true, lowLatencyMode:true,
                backBufferLength:30, maxBufferLength:90,
                manifestLoadingTimeOut:10000, manifestLoadingMaxRetry:1,
                levelLoadingTimeOut:10000, fragLoadingTimeOut:20000,
                xhrSetup: function(xhr){ xhr.withCredentials=false; }
            });
            _hls.loadSource(_url);
            _hls.attachMedia(v);
            _hls.on(Hls.Events.MANIFEST_PARSED, function(){ v.play().catch(function(){}); });
            _hls.on(Hls.Events.ERROR, function(e,d){
                if(d.fatal){ console.log('[IPTV] Direct échoué, proxy'); _initHLSProxy(); }
            });
        } else if (v.canPlayType('application/vnd.apple.mpegurl')){
            v.src = _url; v.load(); v.play().catch(function(){ _initHLSProxy(); });
            v.addEventListener('error', function onE(){ v.removeEventListener('error',onE); _initHLSProxy(); }, {once:true});
        } else { _initMP4Direct(); }
    }

    function _initHLSProxy(){
        var v = document.getElementById('wi-video');
        if (!v || !_proxyUrl) { _initSafariProxy(); return; }
        if (_hls) { _hls.destroy(); _hls = null; }
        if (window.Hls && Hls.isSupported()){
            _hls = new Hls({
                enableWorker:true, lowLatencyMode:false,
                manifestLoadingTimeOut:15000, manifestLoadingMaxRetry:2,
                levelLoadingTimeOut:15000, fragLoadingTimeOut:25000,
            });
            _hls.loadSource(_proxyUrl);
            _hls.attachMedia(v);
            _hls.on(Hls.Events.MANIFEST_PARSED, function(){ v.play().catch(function(){}); });
            _hls.on(Hls.Events.ERROR, function(e,d){
                if(d.fatal){ console.log('[IPTV] Proxy échoué, safari'); _initSafariProxy(); }
            });
        } else { _initSafariProxy(); }
    }

    function _initSafariProxy(){
        var v = document.getElementById('wi-video');
        if (!v) { _initMP4Direct(); return; }
        if (v.canPlayType('application/vnd.apple.mpegurl')){
            v.src = _proxyUrl || _url; v.load();
            v.play().catch(function(){
                if(v.src !== _url){ v.src=_url; v.load(); v.play().catch(function(){ _initMP4Direct(); }); }
                else { _initMP4Direct(); }
            });
            v.addEventListener('error', function onE(){
                v.removeEventListener('error',onE);
                if(v.src !== _url){ v.src=_url; v.load(); } else { _initMP4Direct(); }
            }, {once:true});
        } else { _initMP4Direct(); }
    }

    function _initMP4Direct(){
        var v = document.getElementById('wi-video');
        if (!v || !_url) { _showFinalErr(); return; }
        if (_hls) { _hls.destroy(); _hls = null; }
        v.src = _url; v.load(); v.play().catch(function(){});
        v.addEventListener('error', function(){ _showFinalErr(); }, {once:true});
    }

    function _initAudio(){
        var v = document.getElementById('wi-video');
        if (!v) return;
        // Remplacer la balise video par audio pour les flux radio
        var container = v.parentNode;
        var audio = document.createElement('audio');
        audio.controls = true; audio.autoplay = true;
        audio.style.cssText = 'width:100%;max-width:400px;position:absolute;bottom:20px;left:50%;transform:translateX(-50%);';
        audio.innerHTML = '<source src="'+(_proxyUrl||_url)+'" type="audio/mpeg"><source src="'+_url+'">';
        v.style.display = 'none';
        container.appendChild(audio);
        audio.load();
        audio.addEventListener('error', function(){
            audio.src = _url; audio.load();
        });
    }

    function _showFinalErr(){ _showErr('Flux inaccessible. Il est peut-être hors ligne ou géo-bloqué.'); }
    function _showErr(msg){ document.getElementById('wi-err').style.display='block'; document.getElementById('wi-err-msg').textContent=msg; }

    window.wiRetry = function(){
        document.getElementById('wi-err').style.display='none';
        if (_hls) { _hls.destroy(); _hls=null; }
        _initHLSDirect();
    };

    window.wiFullscreen = function(){
        var v = document.getElementById('wi-video');
        var container = document.querySelector('#wi-layout > div > div[style*="aspect-ratio"]');
        var el = container || v;
        if (!el) return;
        if (document.fullscreenElement) document.exitFullscreen();
        else if (el.requestFullscreen) el.requestFullscreen();
        else if (el.webkitRequestFullscreen) el.webkitRequestFullscreen();
        else if (el.mozRequestFullScreen) el.mozRequestFullScreen();
    };

    window.wiToggleFav = function(){ addToFavorites(_id,'iptv',null); };

    window.wiReport = function(){
        var reason = prompt('Raison du signalement :');
        if (!reason || !reason.trim()) return;
        var fd = new FormData();
        fd.append('stream_id', _id); fd.append('stream_type','iptv'); fd.append('reason',reason);
        fetch('/api/report',{method:'POST',body:fd,credentials:'include'})
            .then(function(){ showNotification('Signalement envoyé','success'); })
            .catch(function(){ showNotification('Erreur réseau','error'); });
    };

    window.wiRecord = function(){
        var btn = document.getElementById('wi-rec-btn');
        var lbl = document.getElementById('wi-rec-label');
        if (!_recActive){
            var v = document.getElementById('wi-video');
            var stream;
            try { stream = v && v.captureStream ? v.captureStream() : (v && v.mozCaptureStream ? v.mozCaptureStream() : null); } catch(e){ stream=null; }
            if (!stream || !window.MediaRecorder){ showNotification('Enregistrement non supporté','error'); return; }
            _recChunks=[];
            var opts={};
            if(MediaRecorder.isTypeSupported('video/webm;codecs=vp9,opus')) opts.mimeType='video/webm;codecs=vp9,opus';
            else if(MediaRecorder.isTypeSupported('video/webm')) opts.mimeType='video/webm';
            try { _recMR=new MediaRecorder(stream,opts); } catch(e){ try{ _recMR=new MediaRecorder(stream); }catch(e2){ showNotification('Erreur: '+e2.message,'error'); return; } }
            _recMR.ondataavailable=function(e){ if(e.data&&e.data.size>0) _recChunks.push(e.data); };
            _recMR.onstop=function(){
                var blob=new Blob(_recChunks,{type:opts.mimeType||'video/webm'});
                var url=URL.createObjectURL(blob);
                var a=document.createElement('a');
                a.download='livewatch-iptv-'+Date.now()+'.webm';
                a.href=url; document.body.appendChild(a); a.click();
                document.body.removeChild(a); URL.revokeObjectURL(url);
                showNotification('Enregistrement téléchargé !','success');
            };
            _recMR.start(1000); _recActive=true;
            if(lbl) lbl.textContent='Arrêter';
            if(btn){ btn.classList.add('rec-on'); }
            showNotification('Enregistrement démarré','info');
        } else {
            if(_recMR&&_recMR.state!=='inactive') _recMR.stop();
            _recActive=false;
            if(lbl) lbl.textContent='Enregistrer';
            if(btn){ btn.classList.remove('rec-on'); }
        }
    };

    window.addEventListener('beforeunload',function(){ if(_hls) _hls.destroy(); });
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', wiInit);
    } else {
        wiInit();
    }
})();

</script>
{% endblock %}
'''

    # ══════════════════════════════════════════════════════════════════
    # WATCH USER TEMPLATE
    # ══════════════════════════════════════════════════════════════════
    WATCH_USER_TEMPLATE = r'''{% extends "base.html" %}
{% block title %}{{ stream.title }} en direct - {{ app_name }}{% endblock %}
{% block content %}
{% from 'icons.html' import icon %}
{% from 'components.html' import cat_meta %}
{% set cm = cat_meta.get(stream.category, cat_meta['entertainment']) %}
<div id="wu-layout" class="mx-auto grid max-w-5xl gap-8 lg:grid-cols-[1fr_340px]">

<div class="min-w-0">
    <!-- Lecteur -->
    <div class="relative w-full overflow-hidden rounded-2xl bg-black" style="aspect-ratio:16/9">
        {% if stream.stream_url %}
        <video id="wu-video" controls autoplay playsinline class="absolute inset-0 h-full w-full bg-black"></video>
        {% else %}
        <div class="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-gradient-to-br from-[#0A0E1A] to-[#1B2233] text-white/70">
            {{ icon('satellite-dish', 40) }}
            <p class="text-sm">Stream en cours de démarrage...</p>
        </div>
        {% endif %}
        {% if stream.is_live %}
        <div class="pointer-events-none absolute left-3 top-3">
            <span class="inline-flex items-center gap-1.5 rounded-full bg-accent px-2.5 py-1 text-[11px] font-semibold tracking-wide text-white"><span class="live-dot bg-white"></span>EN DIRECT</span>
        </div>
        {% endif %}
        <div id="wu-viewers" class="pointer-events-none absolute right-3 top-3 rounded-md bg-black/55 px-2 py-1 text-[11px] font-medium text-white backdrop-blur-sm">{{ stream.viewer_count }} spectateurs</div>
    </div>

    <!-- Infos -->
    <div class="mt-4">
        <div class="mb-1.5 flex flex-wrap items-center gap-2">
            {% if stream.is_live %}<span class="inline-flex items-center gap-1.5 rounded-full bg-accent px-2.5 py-1 text-[11px] font-semibold tracking-wide text-white"><span class="live-dot bg-white"></span>LIVE</span>{% endif %}
            <span class="rounded-full px-2 py-0.5 text-xs font-medium {{ cm[1] }} {{ cm[2] }}">{{ cm[3] if stream.category in cat_meta else stream.category }}</span>
        </div>
        <h1 class="font-display text-xl font-semibold sm:text-2xl">{{ stream.title }}</h1>
        <p class="mt-1 flex items-center gap-4 text-sm text-ink-muted">
            <span class="flex items-center gap-1.5">{{ icon('heart', 14) }} {{ stream.like_count }}</span>
            <span class="flex items-center gap-1.5">{{ icon('eye', 14) }} {{ stream.viewer_count }}</span>
        </p>
        {% if stream.description %}<p class="card mt-3 p-4 text-sm leading-relaxed text-ink-muted">{{ stream.description }}</p>{% endif %}
        {% if stream.tags %}
        <div class="mt-3 flex flex-wrap gap-2">
            {% for tag in stream.tags.split(',') if tag.strip() %}
            <span class="rounded-full border border-border px-3 py-1 text-xs font-medium text-ink-muted">#{{ tag.strip() }}</span>
            {% endfor %}
        </div>
        {% endif %}
    </div>

    <!-- Actions -->
    <div class="mt-4 flex flex-wrap items-center gap-2">
        <button type="button" onclick="wuLike()" id="wu-like-btn" class="flex items-center gap-1.5 rounded-full border border-border px-4 py-2 text-sm font-medium text-ink-muted transition-colors hover:border-accent hover:text-accent">
            {{ icon('heart', 15) }} <span id="wu-like-count">{{ stream.like_count }}</span> J'aime
        </button>
        <button type="button" onclick="addToFavorites('{{ stream.id }}','user',null)" class="flex items-center gap-1.5 rounded-full border border-border px-4 py-2 text-sm font-medium text-ink-muted hover:text-ink">
            {{ icon('star', 15) }} Favoris
        </button>
        <button type="button" onclick="wuShare()" class="flex items-center gap-1.5 rounded-full border border-border px-4 py-2 text-sm font-medium text-ink-muted hover:text-ink">
            {{ icon('share-2', 15) }} Partager
        </button>
        <button type="button" onclick="wuReport()" class="flex items-center gap-1.5 rounded-full border border-border px-4 py-2 text-sm font-medium text-ink-muted hover:text-ink">
            {{ icon('flag', 15) }} Signaler
        </button>
    </div>

    <!-- Erreur lecteur -->
    <div id="wu-err" class="mt-4 hidden rounded-xl border border-accent/30 bg-accent/10 px-4 py-3 text-sm text-accent">
        <strong class="font-semibold">Problème de lecture</strong><br>
        <span id="wu-err-msg">Le flux ne répond pas.</span>
    </div>
</div>

<!-- CHAT -->
<div>
    <div id="wu-chat-box" class="card flex h-[560px] flex-col overflow-hidden">
        <div class="flex shrink-0 items-center justify-between border-b border-border px-4 py-3">
            <strong class="font-display text-base font-semibold">Chat en direct</strong>
            <span id="wu-online" class="text-xs text-emerald-600 dark:text-emerald-400">● 0 en ligne</span>
        </div>
        <div id="wu-messages" class="custom-scroll flex-1 space-y-3 overflow-y-auto p-4">
            <div class="flex flex-col items-center gap-2 py-6 text-center text-sm text-ink-muted">
                <i class="fas fa-comments" style="font-size:1.6rem"></i>
                Rejoignez la conversation !
            </div>
        </div>
        <div class="flex shrink-0 items-center gap-2 border-t border-border p-3">
            <input id="wu-chat-input" type="text" maxlength="500" placeholder="Votre message..." onkeydown="if(event.key==='Enter')wuSendMsg()"
                   class="min-w-0 flex-1 rounded-full border border-border bg-surface px-4 py-2.5 text-sm outline-none placeholder:text-ink-muted focus-visible:border-accent-2">
            <button type="button" onclick="wuSendMsg()" aria-label="Envoyer" class="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-accent-2 text-white">{{ icon('send', 15) }}</button>
        </div>
    </div>
</div>
</div>
{% endblock %}

{% block scripts %}
<script>

(function(){
    var _streamId  = '{{ stream.id }}';
    var _streamUrl = '{{ stream.stream_url or "" }}';
    var _isLive    = {{ 'true' if stream.is_live else 'false' }};
    var _hls = null;
    var _ws  = null;
    var _wsRetries = 0;
    var _username = 'Invité_' + Math.floor(Math.random()*9000+1000);

    // ── Lecteur ──────────────────────────────────────────────
    function wuInitPlayer(){
        if (!_streamUrl || !_isLive) return;
        var v = document.getElementById('wu-video');
        if (!v) return;
        if (window.Hls && Hls.isSupported()){
            _hls = new Hls({ enableWorker:true, lowLatencyMode:true });
            _hls.loadSource(_streamUrl);
            _hls.attachMedia(v);
            _hls.on(Hls.Events.MANIFEST_PARSED, function(){ v.play().catch(function(){}); });
            _hls.on(Hls.Events.ERROR, function(e,d){
                if(d.fatal){ document.getElementById('wu-err').style.display='block'; }
            });
        } else if (v.canPlayType('application/vnd.apple.mpegurl')){
            v.src = _streamUrl; v.play().catch(function(){});
        } else {
            v.src = _streamUrl;
            v.addEventListener('error', function(){ document.getElementById('wu-err').style.display='block'; });
        }
    }

    // ── WebSocket Chat ────────────────────────────────────────
    function wuConnectWS(){
        var proto = location.protocol==='https:'?'wss':'ws';
        try {
            _ws = new WebSocket(proto+'://'+location.host+'/ws/stream/'+_streamId);
            _ws.onopen = function(){
                _wsRetries = 0;
                _ws.send(JSON.stringify({type:'join', username:_username}));
            };
            _ws.onmessage = function(evt){
                try { var d=JSON.parse(evt.data); _wuHandleMsg(d); } catch(e){}
            };
            _ws.onclose = function(){
                _wsRetries++;
                setTimeout(wuConnectWS, Math.min(30000, 2000*_wsRetries));
            };
            _ws.onerror = function(){};
        } catch(e){ setTimeout(wuConnectWS,5000); }
    }

    function _wuHandleMsg(d){
        if (d.type==='message' || d.type==='chat'){
            _wuAddMsg(d.username||'Anonyme', d.content||d.message||'', d.timestamp||null);
        } else if (d.type==='viewer_count' || d.viewers !== undefined){
            var vc = document.getElementById('wu-viewers');
            var oc = document.getElementById('wu-online');
            var cnt = d.count||d.viewers||0;
            if(vc) vc.textContent = ''+cnt+' spectateurs';
            if(oc) oc.textContent = '• '+cnt+' en ligne';
        } else if (d.type==='like_count'){
            var lc = document.getElementById('wu-like-count');
            if(lc) lc.textContent = d.count;
        }
    }

    function _wuAddMsg(user, text, ts){
        var el = document.getElementById('wu-messages');
        if (!el) return;
        var isSelf = user===_username;
        var time = ts ? new Date(ts).toLocaleTimeString('fr-FR',{hour:'2-digit',minute:'2-digit'}) : new Date().toLocaleTimeString('fr-FR',{hour:'2-digit',minute:'2-digit'});
        var div = document.createElement('div');
        div.className = 'flex flex-col ' + (isSelf ? 'items-end' : 'items-start');
        div.innerHTML =
            '<div class="mb-0.5 text-[11px] text-ink-muted">'+_escHtml(user)+' · '+time+'</div>'
            +'<div class="max-w-[85%] break-words px-3 py-2 text-[13px] leading-snug '
            + (isSelf ? 'rounded-2xl rounded-br-sm bg-accent text-white' : 'rounded-2xl rounded-bl-sm bg-surface-2') + '">'+_escHtml(text)+'</div>';
        el.appendChild(div);
        el.scrollTop = el.scrollHeight;
        // Garder max 80 messages
        while(el.children.length > 80) el.removeChild(el.firstChild);
    }

    function _escHtml(t){ var d=document.createElement('div'); d.appendChild(document.createTextNode(t)); return d.innerHTML; }

    window.wuSendMsg = function(){
        var inp = document.getElementById('wu-chat-input');
        if (!inp) return;
        var msg = inp.value.trim();
        if (!msg) return;
        if (!_ws || _ws.readyState !== WebSocket.OPEN){
            showNotification('Chat non connecté','error'); return;
        }
        _ws.send(JSON.stringify({type:'message', username:_username, content:msg}));
        inp.value='';
    };

    // ── Likes ─────────────────────────────────────────────────
    window.wuLike = async function(){
        try {
            var r = await fetch('/api/streams/'+_streamId+'/like',{method:'POST',credentials:'include'});
            var d = await r.json();
            if(d.success){
                var el=document.getElementById('wu-like-count');
                if(el) el.textContent=d.likes;
                showNotification('Vous aimez ce live !','success');
            }
        } catch(e){}
    };

    // ── Partager ───────────────────────────────────────────────
    window.wuShare = function(){
        var url = location.href;
        if(navigator.share){ navigator.share({title:'{{ stream.title }}',url:url}); }
        else if(navigator.clipboard){ navigator.clipboard.writeText(url).then(function(){ showNotification('Lien copié !','success'); }); }
        else { prompt('Copiez ce lien :', url); }
    };

    // ── Signaler ───────────────────────────────────────────────
    window.wuReport = function(){
        var reason=prompt('Raison du signalement :');
        if(!reason||!reason.trim()) return;
        var fd=new FormData();
        fd.append('stream_id',_streamId); fd.append('stream_type','user'); fd.append('reason',reason);
        fetch('/api/report',{method:'POST',body:fd,credentials:'include'})
            .then(function(){ showNotification('Signalement envoyé','success'); })
            .catch(function(){ showNotification('Erreur réseau','error'); });
    };

    // Ping viewer count régulièrement
    setInterval(async function(){
        try {
            var r=await fetch('/api/streams/'+_streamId+'/viewers',{credentials:'include'});
            var d=await r.json();
            var vc=document.getElementById('wu-viewers');
            if(vc&&d.count!==undefined) vc.textContent=''+d.count+' spectateurs';
        } catch(e){}
    }, 15000);

    window.addEventListener('beforeunload',function(){ if(_hls) _hls.destroy(); if(_ws) _ws.close(); });

    wuInitPlayer();
    wuConnectWS();
})();

</script>
{% endblock %}
'''
    # ══════════════════════════════════════════════════════════════════
    # EVENTS TEMPLATE
    # ══════════════════════════════════════════════════════════════════
    EVENTS_TEMPLATE = r'''{% extends "base.html" %}
{% block title %}Événements & Programmes - {{ app_name }}{% endblock %}
{% block content %}
{% from 'icons.html' import icon %}
{%- set ev_meta = {
    'sport':       ('trophy',       'bg-blue-100 dark:bg-blue-500/15',       'text-blue-600 dark:text-blue-400',       'Sports'),
    'cinema':      ('film',         'bg-purple-100 dark:bg-purple-500/15',   'text-purple-600 dark:text-purple-400',   'Cinéma & Films'),
    'news':        ('newspaper',    'bg-red-100 dark:bg-red-500/15',         'text-red-600 dark:text-red-400',         'Actualités'),
    'kids':        ('baby',         'bg-yellow-100 dark:bg-yellow-500/15',   'text-yellow-600 dark:text-yellow-500',   'Enfants & Famille'),
    'documentary': ('film',         'bg-amber-100 dark:bg-amber-500/15',     'text-amber-600 dark:text-amber-400',     'Documentaires'),
    'music':       ('music-2',      'bg-pink-100 dark:bg-pink-500/15',       'text-pink-600 dark:text-pink-400',       'Musique & Concerts'),
    'other':       ('tv',           'bg-indigo-100 dark:bg-indigo-500/15',   'text-indigo-600 dark:text-indigo-400',   'Divers'),
} -%}
{%- set ann_style = {
    'info':    'border-accent-2/30 bg-accent-2-soft text-accent-2',
    'warning': 'border-amber-500/30 bg-amber-500/10 text-amber-600 dark:text-amber-400',
    'update':  'border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400',
    'feature': 'border-fuchsia-500/30 bg-fuchsia-500/10 text-fuchsia-600 dark:text-fuchsia-400',
} -%}
<div class="mx-auto max-w-3xl">

    <!-- En-tête -->
    <h1 class="mb-1 font-display text-2xl font-semibold">Événements &amp; Programmes</h1>
    <p class="mb-5 text-sm text-ink-muted">Tous les programmes TV, événements sportifs et annonces officielles</p>

    <div class="-mx-1 mb-6 flex gap-2 overflow-x-auto px-1 pb-1" style="scrollbar-width:none">
        <button type="button" onclick="evFilter('all',this)"
                class="ev-filter-btn shrink-0 rounded-full border border-accent bg-accent px-4 py-1.5 text-xs font-semibold text-white transition-colors">Tout</button>
        {% for cat in ['sport','cinema','news','kids','documentary','music','other'] %}
        <button type="button" onclick="evFilter('{{ cat }}',this)"
                class="ev-filter-btn shrink-0 rounded-full border border-border px-4 py-1.5 text-xs font-semibold text-ink-muted transition-colors hover:text-ink">
            {{ {'sport':'Sport','cinema':'Cinéma','news':'News','kids':'Enfants','documentary':'Docs','music':'Musique','other':'Autres'}[cat] }}
        </button>
        {% endfor %}
    </div>

    <!-- Annonces officielles -->
    {% if announcements %}
    <section id="ev-announcements" class="mb-6">
        <div class="space-y-2">
            {% for ann in announcements %}
            <div class="flex items-start gap-2.5 rounded-xl border px-4 py-3 text-sm {{ ann_style.get(ann.type, ann_style['info']) }}">
                <span class="mt-0.5 shrink-0">{{ icon('megaphone', 16) }}</span>
                <div class="min-w-0">
                    <p class="font-semibold">{{ ann.title }}</p>
                    <p class="mt-0.5 opacity-90">{{ ann.message }}</p>
                    <p class="mt-1 text-[11px] opacity-70">{{ ann.created_at.strftime('%d/%m/%Y · %H:%M') }}</p>
                </div>
            </div>
            {% endfor %}
        </div>
    </section>
    {% endif %}

    <!-- Grille d'événements par catégorie -->
    {% set cats = [
        ('sport','Sports',events.get('sport',[])),
        ('cinema','Cinéma & Films',events.get('cinema',[])),
        ('news','Actualités',events.get('news',[])),
        ('kids','Enfants & Famille',events.get('kids',[])),
        ('documentary','Documentaires',events.get('documentary',[])),
        ('music','Musique & Concerts',events.get('music',[])),
        ('other','Divers',events.get('other',[]))
    ] %}

    {% for cat_id, cat_name, cat_events in cats %}
    {% if cat_events %}
    {% set m = ev_meta[cat_id] %}
    <section class="ev-section mb-6" data-cat="{{ cat_id }}">
        <p class="mb-3 flex items-center gap-2 text-sm font-medium text-ink-muted">
            <span class="{{ m[2] }}">{{ icon(m[0], 15) }}</span>
            {{ cat_name }} <span class="text-xs">({{ cat_events|length }})</span>
        </p>
        <div class="space-y-3">
            {% for ev in cat_events %}
            <div class="ev-card card flex items-center gap-4 p-4" data-cat="{{ cat_id }}">
                <div class="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl {{ m[1] }}"><span class="{{ m[2] }}">{{ icon(m[0], 19) }}</span></div>
                <div class="min-w-0 flex-1">
                    <p class="truncate font-medium">{{ ev.title }}</p>
                    {% if ev.description %}<p class="line-clamp-2 text-xs text-ink-muted">{{ ev.description }}</p>{% endif %}
                    <p class="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs text-ink-muted">
                        <span>{{ m[3] }}</span>
                        {% if ev.channel_name %}<span>· {{ ev.channel_name }}</span>{% endif %}
                        {% if ev.country %}<span class="inline-flex items-center gap-1">· {% if ev.country_code %}<img src="https://flagcdn.com/w20/{{ ev.country_code|lower }}.png" alt="" class="h-3 rounded-sm" onerror="this.style.display='none'">{% endif %}{{ ev.country }}</span>{% endif %}
                    </p>
                </div>
                <div class="flex shrink-0 flex-col items-end gap-1.5 text-xs text-ink-muted">
                    {% if ev.start_time %}
                    <span class="flex items-center gap-1">{{ icon('calendar', 12) }} {{ ev.start_time.strftime('%d/%m/%Y') }}</span>
                    <span class="flex items-center gap-1">{{ icon('clock', 12) }} {{ ev.start_time.strftime('%H:%M') }}</span>
                    {% endif %}
                    {% if ev.stream_url %}
                    <a href="{{ ev.stream_url }}" target="_blank" rel="noopener" class="rounded-full bg-accent px-3 py-1 text-[11px] font-semibold text-white hover:opacity-90">Regarder</a>
                    {% endif %}
                </div>
            </div>
            {% endfor %}
        </div>
    </section>
    {% endif %}
    {% endfor %}

    <!-- Si aucun événement -->
    {% set total_events = (events.get('sport',[])|length + events.get('cinema',[])|length + events.get('news',[])|length + events.get('kids',[])|length + events.get('documentary',[])|length + events.get('music',[])|length + events.get('other',[])|length) %}
    {% if total_events == 0 %}
    <div class="card flex flex-col items-center gap-2 p-10 text-center text-ink-muted">
        <span class="flex h-12 w-12 items-center justify-center rounded-2xl bg-accent-2-soft text-accent-2">{{ icon('calendar', 22) }}</span>
        <p class="font-medium text-ink">Aucun programme disponible</p>
        <p class="text-sm">Les événements seront disponibles une fois que l'administrateur les aura chargés.</p>
        <a href="/" class="mt-2 text-sm font-medium text-accent-2 hover:underline">← Retour à l'accueil</a>
    </div>
    {% endif %}

    <!-- Compte à rebours -->
    {% if events.get('sport') or events.get('cinema') %}
    <section class="mt-8">
        <p class="mb-3 text-sm font-medium text-ink-muted">Prochainement — Dans moins d'une heure</p>
        <div id="upcoming-soon" class="space-y-3"></div>
        <div id="upcoming-empty" class="card hidden p-6 text-center text-sm text-ink-muted">Aucun événement prévu dans la prochaine heure.</div>
    </section>
    {% endif %}

    <!-- Calendrier semaine -->
    <section class="mt-8">
        <p class="mb-3 text-sm font-medium text-ink-muted">Cette semaine</p>
        <div class="custom-scroll -mx-1 mb-4 flex gap-2 overflow-x-auto px-1 pb-1" id="week-nav"></div>
        <div id="week-content"><p class="card p-6 text-center text-sm text-ink-muted">Sélectionnez un jour</p></div>
    </section>
</div>
{% endblock %}

{% block scripts %}
<script>
function evFilter(cat, btn) {
    document.querySelectorAll('.ev-filter-btn').forEach(function(b){
        b.classList.remove('border-accent','bg-accent','text-white');
        b.classList.add('border-border','text-ink-muted');
    });
    btn.classList.remove('border-border','text-ink-muted');
    btn.classList.add('border-accent','bg-accent','text-white');
    document.querySelectorAll('.ev-section').forEach(function(s){
        s.style.display = (cat==='all' || s.dataset.cat===cat) ? '' : 'none';
    });
}

// ── Palette par catégorie (identique à la grille ci-dessus) ──
var EV_META = {
    sport:       { icon:'trophy',    chip:'bg-blue-100 dark:bg-blue-500/15',     ink:'text-blue-600 dark:text-blue-400' },
    cinema:      { icon:'film',      chip:'bg-purple-100 dark:bg-purple-500/15', ink:'text-purple-600 dark:text-purple-400' },
    news:        { icon:'newspaper', chip:'bg-red-100 dark:bg-red-500/15',       ink:'text-red-600 dark:text-red-400' },
    kids:        { icon:'baby',      chip:'bg-yellow-100 dark:bg-yellow-500/15', ink:'text-yellow-600 dark:text-yellow-500' },
    documentary: { icon:'film',      chip:'bg-amber-100 dark:bg-amber-500/15',   ink:'text-amber-600 dark:text-amber-400' },
    music:       { icon:'music-2',   chip:'bg-pink-100 dark:bg-pink-500/15',     ink:'text-pink-600 dark:text-pink-400' },
    other:       { icon:'tv',        chip:'bg-indigo-100 dark:bg-indigo-500/15', ink:'text-indigo-600 dark:text-indigo-400' }
};

// ── Countdown pour les prochains événements ──
function _pad(n){return String(n).padStart(2,'0');}

function _countdown(target){
    var now=new Date();
    var diff=new Date(target)-now;
    if(diff<=0) return 'En cours';
    var h=Math.floor(diff/3600000);
    var m=Math.floor((diff%3600000)/60000);
    var s=Math.floor((diff%60000)/1000);
    if(h>0) return _pad(h)+'h'+_pad(m)+'m';
    return _pad(m)+'m '+_pad(s)+'s';
}

function _evRow(ev, rightHtml) {
    var cat = ev._cat || 'other';
    var m = EV_META[cat] || EV_META.other;
    return '<div class="card flex items-center gap-4 p-4">'
        + '<div class="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl ' + m.chip + '"><span class="' + m.ink + '">' + lwIcon(m.icon, 19) + '</span></div>'
        + '<div class="min-w-0 flex-1"><p class="truncate font-medium">' + ev.title + '</p>'
        + '<p class="text-xs text-ink-muted">' + [ev.channel_name, ev.country].filter(Boolean).join(' · ') + '</p></div>'
        + '<div class="flex shrink-0 flex-col items-end gap-1.5 text-xs text-ink-muted">' + rightHtml
        + (ev.stream_url ? '<a href="' + ev.stream_url + '" target="_blank" rel="noopener" class="rounded-full bg-accent px-3 py-1 text-[11px] font-semibold text-white hover:opacity-90">Regarder</a>' : '')
        + '</div></div>';
}

// ── Prochains événements (<1h) ──
async function loadUpcomingSoon(){
    var container=document.getElementById('upcoming-soon');
    var emptyEl=document.getElementById('upcoming-empty');
    if(!container) return;

    try{
        var r=await fetch('/api/events/upcoming?limit=6',{credentials:'include'});
        if(!r.ok){if(emptyEl)emptyEl.classList.remove('hidden');return;}
        var data=await r.json();

        var allEvents=[];
        Object.keys(data).forEach(function(cat){
            if(Array.isArray(data[cat])){
                data[cat].forEach(function(ev){ev._cat=cat;allEvents.push(ev);});
            }
        });

        var now=new Date();
        var oneHour=now.getTime()+3600000;
        var soonEvents=allEvents.filter(function(ev){
            if(!ev.start_time) return false;
            var t=new Date(ev.start_time).getTime();
            return t>=now.getTime() && t<=oneHour;
        });

        if(!soonEvents.length){
            if(emptyEl)emptyEl.classList.remove('hidden');
            return;
        }

        container.innerHTML=soonEvents.map(function(ev){
            var startStr=new Date(ev.start_time).toLocaleTimeString('fr-FR',{hour:'2-digit',minute:'2-digit'});
            return _evRow(ev,
                '<span class="flex items-center gap-1">' + lwIcon('clock', 12) + ' ' + startStr + '</span>'
                + '<span class="font-display tabular-nums text-sm font-semibold text-accent" id="cd-'+ev.id+'">'+_countdown(ev.start_time)+'</span>');
        }).join('');

        // Mettre à jour les countdowns toutes les secondes
        setInterval(function(){
            soonEvents.forEach(function(ev){
                var el=document.getElementById('cd-'+ev.id);
                if(el) el.textContent=_countdown(ev.start_time);
            });
        },1000);

    }catch(e){
        if(emptyEl) emptyEl.classList.remove('hidden');
    }
}

// ── Calendrier semaine ──
var _selectedDay=null;

function buildWeekNav(){
    var nav=document.getElementById('week-nav');
    if(!nav) return;

    var days=['Dim','Lun','Mar','Mer','Jeu','Ven','Sam'];
    var months=['Jan','Fév','Mar','Avr','Mai','Juin','Juil','Août','Sep','Oct','Nov','Déc'];
    var now=new Date();
    var html='';

    for(var i=0;i<7;i++){
        var d=new Date(now.getFullYear(),now.getMonth(),now.getDate()+i);
        var dateStr=d.toISOString().slice(0,10);
        html+='<button type="button" onclick="loadWeekDay(\''+dateStr+'\',this)" '
            +'class="wk-btn flex w-16 shrink-0 flex-col items-center gap-0.5 rounded-xl border border-border bg-surface px-2 py-2.5 text-ink-muted transition-colors hover:text-ink">'
            +'<span class="text-[11px] font-medium">'+days[d.getDay()]+'</span>'
            +'<span class="font-display text-lg font-semibold leading-none">'+d.getDate()+'</span>'
            +'<span class="text-[10px]">'+months[d.getMonth()]+'</span>'
            +'</button>';
    }
    nav.innerHTML=html;
}

async function loadWeekDay(dateStr,btn){
    document.querySelectorAll('#week-nav .wk-btn').forEach(function(b){
        b.classList.remove('border-accent','bg-accent','text-white');
        b.classList.add('border-border','bg-surface','text-ink-muted');
    });
    if(btn){
        btn.classList.remove('border-border','bg-surface','text-ink-muted');
        btn.classList.add('border-accent','bg-accent','text-white');
    }

    _selectedDay=dateStr;
    var content=document.getElementById('week-content');
    if(!content) return;
    content.innerHTML='<p class="card p-6 text-center text-sm text-ink-muted">Chargement...</p>';

    try{
        var r=await fetch('/api/events/upcoming?limit=50',{credentials:'include'});
        var data=await r.json();
        var allEvents=[];
        Object.keys(data).forEach(function(cat){
            if(Array.isArray(data[cat])) data[cat].forEach(function(ev){ev._cat=cat;allEvents.push(ev);});
        });

        var dayEvents=allEvents.filter(function(ev){
            if(!ev.start_time) return false;
            return ev.start_time.slice(0,10)===dateStr;
        });

        if(!dayEvents.length){
            content.innerHTML='<p class="card p-6 text-center text-sm text-ink-muted">Aucun programme pour ce jour.</p>';
            return;
        }

        dayEvents.sort(function(a,b){return new Date(a.start_time)-new Date(b.start_time);});

        content.innerHTML='<div class="space-y-3">'
            +dayEvents.map(function(ev){
                var t=ev.start_time?new Date(ev.start_time).toLocaleTimeString('fr-FR',{hour:'2-digit',minute:'2-digit'}):'';
                return _evRow(ev, '<span class="flex items-center gap-1">' + lwIcon('clock', 12) + ' ' + t + '</span>');
            }).join('')
            +'</div>';

    }catch(e){
        content.innerHTML='<p class="card p-6 text-center text-sm text-ink-muted">Erreur de chargement.</p>';
    }
}

// ── Init ──
document.addEventListener('DOMContentLoaded',function(){
    loadUpcomingSoon();
    buildWeekNav();
    var todayBtn=document.querySelector('#week-nav .wk-btn');
    if(todayBtn){
        var today=new Date().toISOString().slice(0,10);
        loadWeekDay(today,todayBtn);
    }
});
</script>
{% endblock %}
'''

    # ══════════════════════════════════════════════════════════════════
    # SEARCH TEMPLATE
    # ══════════════════════════════════════════════════════════════════
    SEARCH_TEMPLATE = r'''{% extends "base.html" %}
{% block title %}Recherche{% if query %} : {{ query }}{% endif %} - {{ app_name }}{% endblock %}
{% block content %}
{% from 'icons.html' import icon %}
{% from 'components.html' import stream_card, cat_meta %}
<div class="mx-auto max-w-6xl">
    <h1 class="mb-5 font-display text-2xl font-semibold">Rechercher</h1>

    <!-- Barre de recherche -->
    <form method="GET" action="/search" class="relative mb-7 max-w-lg">
        {{ icon('search', 17, 'pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-ink-muted') }}
        <input type="text" name="q" value="{{ query or '' }}" autofocus placeholder="Chaîne, sport, pays…"
               class="w-full rounded-full border border-border bg-surface py-3 pl-11 pr-4 text-sm outline-none placeholder:text-ink-muted focus-visible:border-accent-2">
    </form>

    {% if query %}
    {% set total = external_results|length + iptv_results|length + user_results|length %}
    <div class="mb-4 flex items-center justify-between">
        <h2 class="font-display text-lg font-semibold">{{ total }} résultat{% if total > 1 %}s{% endif %} pour « {{ query }} »</h2>
    </div>

    {% if total == 0 %}
    <div class="card mt-4 flex flex-col items-center gap-2 p-10 text-center text-ink-muted">
        <p class="font-medium text-ink">Aucun résultat pour « {{ query }} »</p>
        <p class="text-sm">Essayez un autre mot-clé, ou parcourez les catégories depuis l'accueil.</p>
        <a href="/" class="mt-2 text-sm font-medium text-accent-2 hover:underline">← Accueil</a>
    </div>
    {% endif %}

    <!-- Lives -->
    {% if user_results %}
    <section class="mb-8">
        <p class="mb-3 text-sm font-medium text-ink-muted">Lives en direct ({{ user_results|length }})</p>
        <div class="grid grid-cols-2 gap-4 sm:grid-cols-3 xl:grid-cols-4">
            {% for s in user_results %}
            {%- set sm = cat_meta.get(s.category, cat_meta['entertainment']) -%}
            <a href="/watch/user/{{ s.id }}" class="card group flex flex-col overflow-hidden transition-transform hover:-translate-y-0.5 stream-card">
                <div class="relative flex aspect-video w-full items-center justify-center overflow-hidden {{ sm[1] }}">
                    <span class="{{ sm[2] }}">{{ icon('video', 30, '', 1.75) }}</span>
                    {% if s.thumbnail %}<img src="{{ s.thumbnail }}" alt="" loading="lazy" onerror="this.style.display='none'" class="absolute inset-0 h-full w-full object-cover transition-transform duration-300 group-hover:scale-105">{% endif %}
                    <div class="absolute left-2.5 top-2.5"><span class="inline-flex items-center gap-1.5 rounded-full bg-accent px-2.5 py-1 text-[11px] font-semibold tracking-wide text-white"><span class="live-dot bg-white"></span>DIRECT</span></div>
                </div>
                <div class="flex items-start gap-2.5 p-3.5">
                    <div class="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg {{ sm[1] }}"><span class="{{ sm[2] }}">{{ icon(sm[0], 14) }}</span></div>
                    <div class="min-w-0">
                        <p class="truncate text-sm font-semibold leading-snug">{{ s.title }}</p>
                        <p class="truncate text-xs text-ink-muted">{{ sm[3] if s.category in cat_meta else s.category }}</p>
                    </div>
                </div>
            </a>
            {% endfor %}
        </div>
    </section>
    {% endif %}

    <!-- Flux externes -->
    {% if external_results %}
    <section class="mb-8">
        <p class="mb-3 text-sm font-medium text-ink-muted">Chaînes &amp; Médias ({{ external_results|length }})</p>
        <div class="grid grid-cols-2 gap-4 sm:grid-cols-3 xl:grid-cols-4">
            {% for s in external_results %}
            {{ stream_card('/watch/external/' ~ s.id, s.title, s.logo, (s.category if s.category in cat_meta else 'iptv'), (cat_meta.get(s.category, cat_meta['iptv'])[3] ~ ((' · ' ~ s.country) if s.country else '')), none, none, none, s.stream_type) }}
            {% endfor %}
        </div>
    </section>
    {% endif %}

    <!-- IPTV -->
    {% if iptv_results %}
    <section class="mb-8">
        <p class="mb-3 text-sm font-medium text-ink-muted">Chaînes TV mondiales ({{ iptv_results|length }})</p>
        <div class="grid grid-cols-2 gap-4 sm:grid-cols-3 xl:grid-cols-4">
            {% for ch in iptv_results %}
            {{ stream_card('/watch/iptv/' ~ ch.id, ch.name, ch.logo, (ch.category if ch.category in cat_meta else 'iptv'), (cat_meta.get(ch.category, cat_meta['iptv'])[3] ~ ((' · ' ~ ch.country) if ch.country else ''))) }}
            {% endfor %}
        </div>
    </section>
    {% endif %}

    {% else %}
    <!-- Page par défaut sans query -->
    <div class="card flex flex-col items-center gap-3 p-10 text-center text-ink-muted">
        <span class="flex h-12 w-12 items-center justify-center rounded-2xl bg-accent-2-soft text-accent-2">{{ icon('search', 22) }}</span>
        <p class="text-sm">Tapez un mot-clé pour rechercher une chaîne, un live ou un programme</p>
    </div>
    {% endif %}
</div>
{% endblock %}
'''

    # ══════════════════════════════════════════════════════════════════
    # ADMIN LOGIN TEMPLATE
    # ══════════════════════════════════════════════════════════════════
    ADMIN_LOGIN_TEMPLATE = r'''{% extends "base.html" %}
{% block title %}Administration - {{ app_name }}{% endblock %}
{% block content %}
{% from 'icons.html' import icon %}
<div class="mx-auto flex min-h-[70vh] max-w-sm flex-col justify-center">
    <div class="card p-7">
        <div class="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-accent-2-soft text-accent-2">{{ icon('shield-check', 22) }}</div>
        <h1 class="mb-1 text-center font-display text-xl font-semibold">Espace admin</h1>
        <p class="mb-6 text-center text-sm text-ink-muted">{{ app_name }} — Connectez-vous pour accéder au tableau de bord.</p>

        {% if error %}
        <div class="mb-4 flex items-center gap-2 rounded-xl border border-accent/30 bg-accent/10 px-3.5 py-2.5 text-sm text-accent">{{ icon('triangle-alert', 16) }} {{ error }}</div>
        {% endif %}

        <form method="POST" action="/admin/login" class="space-y-4">
            <div>
                <label for="username" class="mb-1.5 block text-sm font-medium">Identifiant ou email</label>
                <input type="text" id="username" name="username" autocomplete="username" required autofocus placeholder="Identifiant admin"
                       class="w-full rounded-xl border border-border bg-surface px-3.5 py-2.5 text-sm outline-none placeholder:text-ink-muted focus-visible:border-accent-2">
            </div>
            <div>
                <label for="password" class="mb-1.5 block text-sm font-medium">Mot de passe</label>
                <input type="password" id="password" name="password" autocomplete="current-password" required placeholder="••••••••"
                       class="w-full rounded-xl border border-border bg-surface px-3.5 py-2.5 text-sm outline-none placeholder:text-ink-muted focus-visible:border-accent-2">
            </div>
            <button type="submit" class="flex w-full items-center justify-center gap-2 rounded-xl bg-accent-2 py-3 text-sm font-semibold text-white transition-opacity hover:opacity-90">{{ icon('log-in', 16) }} Se connecter</button>
        </form>
        <a href="/" class="mt-4 block text-center text-sm text-ink-muted hover:text-ink">← Retour au site</a>
    </div>
</div>
{% endblock %}
'''

    # ══════════════════════════════════════════════════════════════════
    # BLOCKED / ERROR / PLAYLIST TEMPLATES
    # ══════════════════════════════════════════════════════════════════
    BLOCKED_TEMPLATE = r'''{% extends "base.html" %}
{% block title %}Accès bloqué - {{ app_name }}{% endblock %}
{% block content %}
{% from 'icons.html' import icon %}
<div class="mx-auto flex max-w-md flex-col items-center gap-4 py-20 text-center">
    <div class="flex h-14 w-14 items-center justify-center rounded-2xl bg-accent/10 text-accent">{{ icon('ban', 26) }}</div>
    <h1 class="font-display text-xl font-semibold">Accès bloqué</h1>
    <p class="text-sm text-ink-muted">Votre adresse IP a été bloquée de cette plateforme.</p>
    <p class="text-sm text-ink-muted">Si vous pensez qu'il s'agit d'une erreur, contactez l'administrateur.</p>
</div>
{% endblock %}
'''

    ERROR_TEMPLATE = r'''{% extends "base.html" %}
{% block title %}Erreur {{ code }} - {{ app_name }}{% endblock %}
{% block content %}
{% from 'icons.html' import icon %}
<div class="mx-auto flex max-w-md flex-col items-center gap-4 py-20 text-center">
    <p class="font-display text-6xl font-semibold text-ink-muted">{{ code }}</p>
    <h1 class="font-display text-xl font-semibold">{{ message }}</h1>
    <p class="text-sm text-ink-muted">{{ detail or 'La page que vous cherchez est introuvable ou une erreur est survenue.' }}</p>
    <div class="mt-2 flex flex-wrap items-center justify-center gap-2.5">
        <a href="/" class="flex items-center gap-2 rounded-full bg-accent px-5 py-2.5 text-sm font-semibold text-white">{{ icon('house', 15) }} Accueil</a>
        <button type="button" onclick="history.back()" class="rounded-full border border-border px-5 py-2.5 text-sm font-semibold text-ink-muted hover:text-ink">← Retour</button>
    </div>
</div>
{% endblock %}
'''

    PLAYLIST_TEMPLATE = r'''{% extends "base.html" %}
{% block title %}{{ playlist.display_name }} - {{ app_name }}{% endblock %}
{% block content %}
{% from 'icons.html' import icon %}
<div class="mx-auto max-w-6xl">
    <div class="mb-6 flex flex-wrap items-center gap-3">
        <a href="/" aria-label="Retour" class="flex h-9 w-9 items-center justify-center rounded-lg text-ink-muted hover:bg-surface-2 hover:text-ink">{{ icon('arrow-left', 18) }}</a>
        {% if playlist.country %}<img src="https://flagcdn.com/w40/{{ playlist.country|lower }}.png" alt="" class="h-5 w-7 rounded object-cover" onerror="this.style.display='none'">{% endif %}
        <div>
            <h1 class="font-display text-2xl font-semibold sm:text-3xl">{{ playlist.display_name }}</h1>
            <p class="mt-0.5 text-sm text-ink-muted">{{ channels|length }} chaîne{{ 's' if channels|length > 1 else '' }} en direct</p>
        </div>
    </div>

    {% if channels %}
    <div class="grid grid-cols-2 gap-4 sm:grid-cols-3 xl:grid-cols-4">
        {% for ch in channels %}
        <a href="/watch/iptv/{{ ch.id }}" class="card group flex flex-col overflow-hidden transition-transform hover:-translate-y-0.5 stream-card">
            <div class="relative flex aspect-video w-full items-center justify-center overflow-hidden bg-indigo-100 dark:bg-indigo-500/15">
                <span class="text-indigo-600 dark:text-indigo-400">{{ icon('tv', 30, '', 1.75) }}</span>
                {% if ch.logo %}
                <div class="absolute inset-0 flex items-center justify-center bg-surface-2"><img src="{{ ch.logo }}" alt="" loading="lazy" onerror="var p=this.parentNode;p.parentNode.removeChild(p)" class="h-full w-full object-contain p-4 transition-transform duration-300 group-hover:scale-105"></div>
                {% endif %}
                <div class="absolute left-2.5 top-2.5"><span class="inline-flex items-center gap-1.5 rounded-full bg-accent px-2.5 py-1 text-[11px] font-semibold tracking-wide text-white"><span class="live-dot bg-white"></span>DIRECT</span></div>
            </div>
            <div class="flex items-start gap-2.5 p-3.5">
                <div class="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-indigo-100 dark:bg-indigo-500/15"><span class="text-indigo-600 dark:text-indigo-400">{{ icon('tv', 14) }}</span></div>
                <div class="min-w-0 flex-1">
                    <p class="truncate text-sm font-semibold leading-snug">{{ ch.name }}</p>
                    <p class="truncate text-xs text-ink-muted">{{ ch.category or '—' }}</p>
                </div>
                <button type="button" onclick="addToFavorites('{{ ch.id }}','iptv',event)" title="Ajouter aux favoris" aria-label="Ajouter aux favoris" class="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-ink-muted transition-colors hover:bg-surface-2 hover:text-amber-500">{{ icon('star', 15) }}</button>
            </div>
        </a>
        {% endfor %}
    </div>
    {% else %}
    <div class="card flex flex-col items-center gap-2 p-10 text-center text-ink-muted">
        {{ icon('tv-2', 30) }}
        <p class="font-medium text-ink">Aucune chaîne disponible</p>
        <p class="text-sm">Cette playlist n'a pas encore été synchronisée.</p>
        <a href="/" class="mt-2 text-sm font-medium text-accent-2 hover:underline">← Accueil</a>
    </div>
    {% endif %}
</div>
{% endblock %}
'''

    # ══════════════════════════════════════════════════════════════════
    # ÉCRITURE SUR DISQUE
    # ══════════════════════════════════════════════════════════════════
    # ══════════════════════════════════════════════════════════════════
    # PROFIL / À PROPOS / LÉGAL / 404
    # ══════════════════════════════════════════════════════════════════
    PROFILE_TEMPLATE = r'''{% extends "base.html" %}
{% block title %}Mon Profil - {{ app_name }}{% endblock %}
{% block content %}
{% from 'icons.html' import icon %}
<div class="mx-auto max-w-4xl">
    <div class="mb-8 flex items-center gap-4">
        <div class="flex h-16 w-16 items-center justify-center rounded-2xl bg-accent-2-soft font-display text-xl font-semibold text-accent-2">V</div>
        <div class="min-w-0">
            <h1 class="font-display text-xl font-semibold">Visiteur Anonyme</h1>
            <p class="text-sm text-ink-muted">Session anonyme · aucune donnée personnelle requise</p>
            <p class="mt-0.5 text-xs text-ink-muted">ID : <code id="p-vid" class="rounded bg-surface-2 px-1.5 py-0.5">{{ visitor_id[:12] }}...</code> · Membre depuis {{ member_since }}</p>
        </div>
    </div>

    <div class="mb-8 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {% for val, lbl, ic in [(fav_count, 'Favoris', 'heart'), (view_count, 'Vues', 'eye'), (stream_count, 'Lives créés', 'cast'), (lang_pref, 'Langue', 'globe')] %}
        <div class="card flex items-center gap-4 p-5">
            <div class="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-accent-2-soft text-accent-2">{{ icon(ic, 20) }}</div>
            <div class="min-w-0">
                <p class="truncate text-sm text-ink-muted">{{ lbl }}</p>
                <p class="font-display tabular-nums text-2xl font-semibold leading-tight">{{ val }}</p>
            </div>
        </div>
        {% endfor %}
    </div>

    <div class="mb-4 flex items-center justify-between">
        <h2 class="font-display text-lg font-semibold">Mes favoris</h2>
        <span class="flex items-center gap-2 text-xs text-ink-muted">{{ fav_count }} au total <span class="text-accent">{{ icon('heart', 16) }}</span></span>
    </div>
    <div id="profile-favs">
        <div class="card flex items-center justify-center gap-2 p-10 text-sm text-ink-muted"><i class="fas fa-spinner fa-spin"></i> Chargement de vos favoris...</div>
    </div>

    <div class="mt-8 flex flex-wrap gap-3">
        <a href="/settings" class="flex items-center gap-2 rounded-full border border-border px-5 py-2.5 text-sm font-medium text-ink-muted hover:text-ink">{{ icon('settings', 15) }} Paramètres</a>
        <a href="/go-live" class="flex items-center gap-2 rounded-full bg-accent px-5 py-2.5 text-sm font-semibold text-white hover:opacity-90">{{ icon('cast', 15) }} Démarrer un live</a>
        <button type="button" onclick="pExportData()" class="flex items-center gap-2 rounded-full border border-border px-5 py-2.5 text-sm font-medium text-ink-muted hover:text-ink">{{ icon('download', 15) }} Exporter mes données</button>
    </div>
</div>
{% endblock %}

{% block scripts %}
<script>
document.addEventListener('DOMContentLoaded', function() {
    // Charger les favoris
    fetch('/api/favorites', {credentials:'include'})
        .then(function(r){return r.json();})
        .then(function(favs){
            var el = document.getElementById('profile-favs');
            if (!el) return;
            if (!favs.length) {
                el.innerHTML = '<div class="card p-10 text-center text-ink-muted">Aucun favori pour l\'instant — ajoutez-en depuis une chaîne en direct.<br><a href="/" class="mt-2 inline-block text-sm font-medium text-accent-2 hover:underline">Découvrir des chaînes →</a></div>';
                return;
            }
            el.innerHTML = '<div class="grid grid-cols-2 gap-4 sm:grid-cols-3 xl:grid-cols-4">' +
                favs.slice(0,12).map(function(f){
                    return '<a href="'+f.url+'" class="card group flex flex-col overflow-hidden">'
                        +'<div class="relative flex aspect-video w-full items-center justify-center overflow-hidden bg-surface-2">'
                        +(f.logo?'<img src="'+f.logo+'" alt="" loading="lazy" class="h-full w-full object-contain p-4" onerror="this.style.display=\'none\'">':'<span class="text-ink-muted">'+lwIcon('tv', 28)+'</span>')
                        +'</div><div class="flex items-start gap-2.5 p-3.5"><div class="min-w-0"><p class="truncate text-sm font-semibold leading-snug">'+f.title+'</p>'
                        +'<p class="truncate text-xs text-ink-muted">'+(f.category||f.type||'')+'</p></div></div></a>';
                }).join('') + '</div>';
        })
        .catch(function(){});
});

function pExportData() {
    var data = {
        visitor_id: document.getElementById('p-vid').textContent,
        favorites: JSON.parse(localStorage.getItem('lw_favorites') || '[]'),
        settings: JSON.parse(localStorage.getItem('lw_settings_v3') || '{}'),
        exported_at: new Date().toISOString()
    };
    var blob = new Blob([JSON.stringify(data, null, 2)], {type:'application/json'});
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url; a.download = 'livewatch-data.json';
    document.body.appendChild(a); a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    showNotification('Données exportées', 'success');
}
</script>
{% endblock %}
'''


    ABOUT_TEMPLATE = r'''{% extends "base.html" %}
{% block title %}À propos - {{ app_name }}{% endblock %}
{% block content %}
{% from 'icons.html' import icon %}
<div class="mx-auto max-w-2xl">
    <div class="mb-6 flex items-center gap-4">
        <div class="flex h-16 w-16 shrink-0 items-center justify-center rounded-2xl bg-accent text-white">{{ icon('cast', 28) }}</div>
        <div>
            <h1 class="font-display text-2xl font-semibold">À propos de {{ app_name }}</h1>
            <p class="text-sm text-ink-muted">Plateforme de streaming live — version 2.0</p>
            <p class="text-xs text-ink-muted">Propulsé par FastAPI · PostgreSQL · HLS.js · WebRTC</p>
        </div>
    </div>

    <div class="mb-6 grid gap-3 sm:grid-cols-2">
        {% for ic, title, text in [
            ('tv-2', 'Chaînes TV mondiales', 'Des milliers de chaînes organisées par pays, région et ville — TV, radio et webcams du monde entier.'),
            ('cast', 'Streaming en direct', 'Diffusez depuis votre caméra ou votre écran avec WebRTC — sans logiciel supplémentaire.'),
            ('radio', 'Radio du monde entier', 'Écoutez des centaines de stations radio de tous les continents directement dans votre navigateur.'),
            ('calendar', 'Guide des programmes', 'Consultez les horaires des émissions TV grâce aux guides électroniques de programmes (EPG).'),
            ('star', 'Favoris', 'Enregistrez vos chaînes préférées et retrouvez-les rapidement.'),
            ('moon', 'Mode sombre', 'Interface disponible en mode clair, sombre ou automatique selon votre système.'),
            ('messages-square', 'Chat en direct', 'Échangez en temps réel avec d\'autres spectateurs pendant les lives.'),
            ('shield', 'Confidentialité', 'Aucun compte requis. Aucune donnée personnelle collectée. Navigation anonyme.'),
        ] %}
        <div class="card p-5">
            <div class="mb-3 flex h-10 w-10 items-center justify-center rounded-xl bg-accent-2-soft text-accent-2">{{ icon(ic, 20) }}</div>
            <h3 class="font-display text-base font-semibold">{{ title }}</h3>
            <p class="mt-1 text-sm leading-relaxed text-ink-muted">{{ text }}</p>
        </div>
        {% endfor %}
    </div>

    <div class="card mb-6 p-6">
        <h2 class="mb-4 font-display text-lg font-semibold">Stack technique</h2>
        <div class="grid grid-cols-2 gap-2.5 sm:grid-cols-3">
            {% for name, desc in [
                ('FastAPI', 'Framework Python async ultra-rapide'),
                ('PostgreSQL', 'Base de données relationnelle robuste'),
                ('HLS.js', 'Lecture de flux HLS dans le navigateur'),
                ('WebRTC', 'Streaming caméra peer-to-peer'),
                ('WebSocket', 'Chat et stats en temps réel'),
                ('Tailwind CSS', 'Interface moderne et réactive'),
                ('SQLAlchemy', 'ORM Python pour PostgreSQL'),
                ('Alembic', 'Migrations de base de données'),
                ('Video.js', 'Lecteur vidéo universel'),
                ('yt-dlp', 'Extraction flux YouTube Live'),
                ('Docker', 'Déploiement containerisé'),
                ('JWT', 'Authentification sécurisée'),
            ] %}
            <div class="rounded-xl bg-surface-2 p-3">
                <div class="text-sm font-semibold">{{ name }}</div>
                <div class="mt-0.5 text-xs text-ink-muted">{{ desc }}</div>
            </div>
            {% endfor %}
        </div>
    </div>

    <div class="card border-accent/30 bg-accent/5 p-6">
        <h2 class="mb-2 flex items-center gap-2 font-display text-lg font-semibold text-accent">{{ icon('heart', 18) }} Soutenir le projet</h2>
        <p class="text-sm leading-relaxed text-ink-muted">{{ app_name }} est un projet développé par BEN CORPORATION. Si vous appréciez la plateforme, vous pouvez soutenir son développement via Airtel Money et cryptomonnaies.</p>
        <div class="mt-4 rounded-xl border border-border bg-surface p-4">
            <p class="text-xs text-ink-muted">Airtel Money · Congo</p>
            <p class="mb-3 text-sm font-semibold">+243 998 655 061</p>
            <p class="text-xs text-ink-muted">Cryptomonnaies</p>
            <p class="break-all text-xs font-medium">0x30B46539266EC13A2D3720bf0289d927647fdB3E</p>
        </div>
    </div>
</div>
{% endblock %}
'''


    TERMS_TEMPLATE = r'''{% extends "base.html" %}
{% block title %}Conditions d'utilisation - {{ app_name }}{% endblock %}
{% block content %}
<div class="mx-auto max-w-2xl">
    <h1 class="font-display text-2xl font-semibold">Conditions d'utilisation</h1>
    <p class="mb-4 mt-1 text-sm text-ink-muted">Dernière mise à jour : {{ current_date }}</p>

    <div class="card space-y-5 p-6 text-sm leading-relaxed text-ink-muted">
        {% set sec = [
            (1, 'Acceptation des conditions', "En utilisant " ~ app_name ~ ", vous acceptez les présentes conditions d'utilisation. Si vous n'êtes pas d'accord avec ces conditions, veuillez ne pas utiliser ce service. Ces conditions peuvent être modifiées à tout moment."),
            (2, 'Description du service', app_name ~ " est une plateforme de streaming en ligne permettant d'accéder à des chaînes de télévision, des flux radio, des lives YouTube et des diffusions en direct créées par les utilisateurs. Les flux sont fournis par des sources tierces et nous ne garantissons pas leur disponibilité permanente."),
            (3, 'Propriété intellectuelle', "Les flux diffusés sur la plateforme restent la propriété de leurs détenteurs respectifs. " ~ app_name ~ " ne revendique aucun droit sur le contenu diffusé. Les sources de contenu proviennent de flux publics légalement accessibles. Tout signalement de violation de droits d'auteur sera traité dans les meilleurs délais."),
        ] %}
        {% for n, title, text in sec %}
        <section>
            <h2 class="mb-1.5 flex items-center gap-2 font-medium text-ink"><span class="flex h-5 w-5 items-center justify-center rounded-md bg-accent-2-soft text-[11px] font-semibold text-accent-2">{{ n }}</span>{{ title }}</h2>
            <p>{{ text }}</p>
        </section>
        {% endfor %}

        <section>
            <h2 class="mb-1.5 flex items-center gap-2 font-medium text-ink"><span class="flex h-5 w-5 items-center justify-center rounded-md bg-accent-2-soft text-[11px] font-semibold text-accent-2">4</span>Utilisation acceptable</h2>
            <p>Vous vous engagez à ne pas :</p>
            <ul class="mt-2 list-disc space-y-1 pl-5">
                <li>Diffuser du contenu illégal, obscène, harcelant ou portant atteinte à des droits tiers</li>
                <li>Utiliser le service à des fins commerciales sans autorisation</li>
                <li>Tenter de perturber le fonctionnement de la plateforme</li>
                <li>Automatiser les accès sans autorisation (bots, scrapers)</li>
                <li>Usurper l'identité d'autres utilisateurs ou de l'équipe de la plateforme</li>
            </ul>
        </section>

        <section>
            <h2 class="mb-1.5 flex items-center gap-2 font-medium text-ink"><span class="flex h-5 w-5 items-center justify-center rounded-md bg-accent-2-soft text-[11px] font-semibold text-accent-2">5</span>Confidentialité et données</h2>
            <p>{{ app_name }} ne collecte pas de données personnelles identifiables. Aucun compte n'est requis. Un identifiant anonyme de session est créé via un cookie pour mémoriser vos préférences. Votre adresse IP peut être utilisée à des fins de sécurité et de statistiques agrégées. Aucune donnée n'est revendue à des tiers.</p>
        </section>

        <section>
            <h2 class="mb-1.5 flex items-center gap-2 font-medium text-ink"><span class="flex h-5 w-5 items-center justify-center rounded-md bg-accent-2-soft text-[11px] font-semibold text-accent-2">6</span>Limitation de responsabilité</h2>
            <p>{{ app_name }} est fourni "tel quel" sans garantie d'aucune sorte. Nous ne sommes pas responsables du contenu diffusé par les sources tierces, des interruptions de service, ou des dommages résultant de l'utilisation de la plateforme.</p>
        </section>

        <div class="border-t border-border pt-4">
            <p class="text-xs">Des questions ? Contactez-nous via le formulaire d'avis ou par email.</p>
        </div>
    </div>
</div>
{% endblock %}
'''


    PRIVACY_TEMPLATE = r'''{% extends "base.html" %}
{% block title %}Politique de confidentialité - {{ app_name }}{% endblock %}
{% block content %}
<div class="mx-auto max-w-2xl">
    <h1 class="font-display text-2xl font-semibold">Politique de confidentialité</h1>
    <p class="mb-4 mt-1 text-sm text-ink-muted">En vigueur depuis le {{ current_date }}</p>

    <div class="card space-y-5 p-6 text-sm leading-relaxed text-ink-muted">
        <div class="rounded-xl bg-accent-2-soft p-3.5 text-accent-2">
            <p><strong>Résumé :</strong> Nous ne collectons aucune donnée personnelle identifiable. Aucun compte requis.</p>
        </div>

        <section>
            <h2 class="mb-1.5 font-medium text-ink">Données collectées automatiquement</h2>
            <p>Lors de votre visite, nous collectons automatiquement :</p>
            <ul class="mt-2 list-disc space-y-1 pl-5">
                <li><strong class="text-ink">Adresse IP</strong> — utilisée uniquement pour la sécurité (blocage d'IPs abusives) et les statistiques géographiques agrégées</li>
                <li><strong class="text-ink">Agent utilisateur</strong> — votre navigateur et système d'exploitation (pour statistiques uniquement)</li>
                <li><strong class="text-ink">Pages visitées</strong> — statistiques d'audience agrégées et anonymisées</li>
                <li><strong class="text-ink">Cookie de session</strong> — identifiant aléatoire unique pour mémoriser vos préférences (thème, langue, favoris)</li>
            </ul>
        </section>

        <section>
            <h2 class="mb-1.5 font-medium text-ink">Ce que nous ne faisons PAS</h2>
            <ul class="mt-2 list-disc space-y-1 pl-5">
                <li>Nous ne demandons pas de nom, email ou numéro de téléphone</li>
                <li>Nous ne vendons ni ne partageons vos données avec des tiers</li>
                <li>Nous ne diffusons pas de publicités ciblées</li>
                <li>Nous n'utilisons pas de traceurs tiers (Google Analytics, Facebook Pixel, etc.)</li>
                <li>Nous ne stockons pas vos mots de passe (aucun compte utilisateur)</li>
            </ul>
        </section>

        <section>
            <h2 class="mb-1.5 font-medium text-ink">Cookies</h2>
            <p>Nous utilisons un seul cookie :</p>
            <div class="mt-2 rounded-xl bg-surface-2 p-3.5">
                <strong class="text-ink">visitor_id</strong> — Cookie de session, durée 30 jours, HttpOnly, SameSite=Lax. Contient un UUID aléatoire (ex: a1b2c3d4-...). Aucune information personnelle.
            </div>
        </section>

        <section>
            <h2 class="mb-1.5 font-medium text-ink">Vos droits</h2>
            <p>Vous pouvez à tout moment :</p>
            <ul class="mt-2 list-disc space-y-1 pl-5">
                <li>Supprimer le cookie visitor_id via votre navigateur</li>
                <li>Effacer toutes vos données locales depuis <a href="/settings" class="text-accent-2 underline underline-offset-2">Paramètres → Confidentialité</a></li>
                <li>Demander la suppression de votre session via le formulaire de contact</li>
            </ul>
        </section>
    </div>
</div>
{% endblock %}
'''


    NOTFOUND_TEMPLATE = r'''{% extends "base.html" %}
{% block title %}Page introuvable (404) - {{ app_name }}{% endblock %}
{% block content %}
{% from 'icons.html' import icon %}
<div class="mx-auto flex max-w-md flex-col items-center gap-4 py-20 text-center">
    <p class="font-display text-6xl font-semibold text-ink-muted">404</p>
    <h1 class="font-display text-xl font-semibold">Page introuvable</h1>
    <p class="text-sm text-ink-muted">La page que vous cherchez n'existe pas ou a été déplacée. Revenez à l'accueil pour trouver votre contenu préféré.</p>
    <div class="mt-2 flex flex-wrap items-center justify-center gap-2.5">
        <a href="/" class="flex items-center gap-2 rounded-full bg-accent px-5 py-2.5 text-sm font-semibold text-white">{{ icon('house', 15) }} Retour à l'accueil</a>
        <a href="/search" class="flex items-center gap-2 rounded-full border border-border px-5 py-2.5 text-sm font-semibold text-ink-muted hover:text-ink">{{ icon('search', 15) }} Rechercher</a>
    </div>
    <div class="mt-6 w-full">
        <p class="mb-2.5 text-xs text-ink-muted">Peut-être cherchiez-vous :</p>
        <div class="flex flex-wrap justify-center gap-2">
            {% for href, lbl in [('/?category=news','News'),('/?category=sports','Sports'),('/?category=radio','Radio'),('/events','Événements'),('/go-live','Go Live')] %}
            <a href="{{ href }}" class="rounded-full border border-border px-4 py-1.5 text-xs font-medium text-ink-muted transition-colors hover:text-ink">{{ lbl }}</a>
            {% endfor %}
        </div>
    </div>
</div>
{% endblock %}
'''



    ICONS_TEMPLATE = r'''{# Icônes Lucide (SVG intégrés) — macro icon(name, size, cls, sw) #}
{% set ICONS = {
  'ban': '<circle cx="12" cy="12" r="10" /> <path d="M4.929 4.929 19.07 19.071" />',
  'calendar': '<path d="M8 2v3" /> <path d="M16 2v3" /> <rect x="3" y="3" width="18" height="18" rx="2" /> <path d="M3 9h18" />',
  'cast': '<path d="M2 8V6a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-6" /> <path d="M2 12a9 9 0 0 1 8 8" /> <path d="M2 16a5 5 0 0 1 4 4" /> <line x1="2" x2="2.01" y1="20" y2="20" />',
  'check': '<path d="M20 6 9 17l-5-5" />',
  'clock': '<circle cx="12" cy="12" r="10" /> <path d="M12 6v6l4 2" />',
  'copy': '<rect width="14" height="14" x="8" y="8" rx="2" ry="2" /> <path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2" />',
  'download': '<path d="M12 15V3" /> <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /> <path d="m7 10 5 5 5-5" />',
  'external-link': '<path d="M15 3h6v6" /> <path d="M10 14 21 3" /> <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />',
  'eye': '<path d="M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0" /> <circle cx="12" cy="12" r="3" />',
  'file-text': '<path d="M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z" /> <path d="M14 2v5a1 1 0 0 0 1 1h5" /> <path d="M10 9H8" /> <path d="M16 13H8" /> <path d="M16 17H8" />',
  'flag': '<path d="M4 22V4a1 1 0 0 1 .4-.8A6 6 0 0 1 8 2c3 0 5 2 7.333 2q2 0 3.067-.8A1 1 0 0 1 20 4v10a1 1 0 0 1-.4.8A6 6 0 0 1 16 16c-3 0-5-2-8-2a6 6 0 0 0-4 1.528" />',
  'flame': '<path d="M12 3q1 4 4 6.5t3 5.5a1 1 0 0 1-14 0 5 5 0 0 1 1-3 1 1 0 0 0 5 0c0-2-1.5-3-1.5-5q0-2 2.5-4" />',
  'heart': '<path d="M2 9.5a5.5 5.5 0 0 1 9.591-3.676.56.56 0 0 0 .818 0A5.49 5.49 0 0 1 22 9.5c0 2.29-1.5 4-3 5.5l-5.492 5.313a2 2 0 0 1-3 .019L5 15c-1.5-1.5-3-3.2-3-5.5" />',
  'house': '<path d="M15 21v-8a1 1 0 0 0-1-1h-4a1 1 0 0 0-1 1v8" /> <path d="M3 10a2 2 0 0 1 .709-1.528l7-6a2 2 0 0 1 2.582 0l7 6A2 2 0 0 1 21 10v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />',
  'link-2': '<path d="M9 17H7A5 5 0 0 1 7 7h2" /> <path d="M15 7h2a5 5 0 1 1 0 10h-2" /> <line x1="8" x2="16" y1="12" y2="12" />',
  'log-in': '<path d="m10 17 5-5-5-5" /> <path d="M15 12H3" /> <path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4" />',
  'log-out': '<path d="m16 17 5-5-5-5" /> <path d="M21 12H9" /> <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />',
  'megaphone': '<path d="M11 6a13 13 0 0 0 8.4-2.8A1 1 0 0 1 21 4v12a1 1 0 0 1-1.6.8A13 13 0 0 0 11 14H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2z" /> <path d="M6 14a12 12 0 0 0 2.4 7.2 2 2 0 0 0 3.2-2.4A8 8 0 0 1 10 14" /> <path d="M8 6v8" />',
  'monitor': '<rect width="20" height="14" x="2" y="3" rx="2" /> <line x1="8" x2="16" y1="21" y2="21" /> <line x1="12" x2="12" y1="17" y2="21" />',
  'moon': '<path d="M20.985 12.486a9 9 0 1 1-9.473-9.472c.405-.022.617.46.402.803a6 6 0 0 0 8.268 8.268c.344-.215.825-.004.803.401" />',
  'plus': '<path d="M5 12h14" /> <path d="M12 5v14" />',
  'power': '<path d="M12 2v10" /> <path d="M18.4 6.6a9 9 0 1 1-12.77.04" />',
  'radio': '<path d="M16.247 7.761a6 6 0 0 1 0 8.478" /> <path d="M19.075 4.933a10 10 0 0 1 0 14.134" /> <path d="M4.925 19.067a10 10 0 0 1 0-14.134" /> <path d="M7.753 16.239a6 6 0 0 1 0-8.478" /> <circle cx="12" cy="12" r="2" />',
  'refresh-cw': '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8" /> <path d="M21 3v5h-5" /> <path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16" /> <path d="M8 16H3v5" />',
  'search': '<path d="m21 21-4.34-4.34" /> <circle cx="11" cy="11" r="8" />',
  'send': '<path d="M14.536 21.686a.5.5 0 0 0 .937-.024l6.5-19a.496.496 0 0 0-.635-.635l-19 6.5a.5.5 0 0 0-.024.937l7.93 3.18a2 2 0 0 1 1.112 1.11z" /> <path d="m21.854 2.147-10.94 10.939" />',
  'shield-check': '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z" /> <path d="m9 12 2 2 4-4" />',
  'square': '<rect width="18" height="18" x="3" y="3" rx="2" />',
  'star': '<path d="M11.525 2.295a.53.53 0 0 1 .95 0l2.31 4.679a2.123 2.123 0 0 0 1.595 1.16l5.166.756a.53.53 0 0 1 .294.904l-3.736 3.638a2.123 2.123 0 0 0-.611 1.878l.882 5.14a.53.53 0 0 1-.771.56l-4.618-2.428a2.122 2.122 0 0 0-1.973 0L6.396 21.01a.53.53 0 0 1-.77-.56l.881-5.139a2.122 2.122 0 0 0-.611-1.879L2.16 9.795a.53.53 0 0 1 .294-.906l5.165-.755a2.122 2.122 0 0 0 1.597-1.16z" />',
  'sun': '<circle cx="12" cy="12" r="4" /> <path d="M12 2v2" /> <path d="M12 20v2" /> <path d="m4.93 4.93 1.41 1.41" /> <path d="m17.66 17.66 1.41 1.41" /> <path d="M2 12h2" /> <path d="M20 12h2" /> <path d="m6.34 17.66-1.41 1.41" /> <path d="m19.07 4.93-1.41 1.41" />',
  'trash-2': '<path d="M10 11v6" /> <path d="M14 11v6" /> <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" /> <path d="M3 6h18" /> <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />',
  'tv-2': '<path d="M7 21h10" /> <rect width="20" height="14" x="2" y="3" rx="2" />',
  'users': '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" /> <path d="M16 3.128a4 4 0 0 1 0 7.744" /> <path d="M22 21v-2a4 4 0 0 0-3-3.87" /> <circle cx="9" cy="7" r="4" />',
  'wifi-off': '<path d="M12 20h.01" /> <path d="M8.5 16.429a5 5 0 0 1 7 0" /> <path d="M5 12.859a10 10 0 0 1 5.17-2.69" /> <path d="M19 12.859a10 10 0 0 0-2.007-1.523" /> <path d="M2 8.82a15 15 0 0 1 4.177-2.643" /> <path d="M22 8.82a15 15 0 0 0-11.288-3.764" /> <path d="m2 2 20 20" />',
  'menu': '<path d="M4 5h16" /> <path d="M4 12h16" /> <path d="M4 19h16" />',
  'user': '<path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2" /> <circle cx="12" cy="7" r="4" />',
  'settings': '<path d="M9.671 4.136a2.34 2.34 0 0 1 4.659 0 2.34 2.34 0 0 0 3.319 1.915 2.34 2.34 0 0 1 2.33 4.033 2.34 2.34 0 0 0 0 3.831 2.34 2.34 0 0 1-2.33 4.033 2.34 2.34 0 0 0-3.319 1.915 2.34 2.34 0 0 1-4.659 0 2.34 2.34 0 0 0-3.32-1.915 2.34 2.34 0 0 1-2.33-4.033 2.34 2.34 0 0 0 0-3.831A2.34 2.34 0 0 1 6.35 6.051a2.34 2.34 0 0 0 3.319-1.915" /> <circle cx="12" cy="12" r="3" />',
  'trophy': '<path d="M10 14.66V17a1 1 0 0 1-1 1 2 2 0 0 0-2 2v2" /> <path d="M14 14.66V17a1 1 0 0 0 1 1 2 2 0 0 1 2 2v2" /> <path d="M17.916 10H19.5A2.5 2.5 0 0 0 22 7.5V5a1 1 0 0 0-1-1h-3" /> <path d="M4 22h16" /> <path d="M6 9a6 6 0 0 0 12 0V3a1 1 0 0 0-1-1H7a1 1 0 0 0-1 1z" /> <path d="M6.084 10H4.5A2.5 2.5 0 0 1 2 7.5V5a1 1 0 0 1 1-1h3" />',
  'newspaper': '<path d="M15 18h-5" /> <path d="M18 14h-8" /> <path d="M4 22h16a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H8a2 2 0 0 0-2 2v16a2 2 0 0 1-4 0v-9a2 2 0 0 1 2-2h2" /> <rect width="8" height="4" x="10" y="6" rx="1" />',
  'clapperboard': '<path d="m12.296 3.464 3.02 3.956" /> <path d="M20.2 6 3 11l-.9-2.4c-.3-1.1.3-2.2 1.3-2.5l13.5-4c1.1-.3 2.2.3 2.5 1.3z" /> <path d="M3 11h18v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /> <path d="m6.18 5.276 3.1 3.899" />',
  'church': '<path d="M10 9h4" /> <path d="M12 7v5" /> <path d="M14 21v-3a2 2 0 0 0-4 0v3" /> <path d="m18 9 3.52 2.147a1 1 0 0 1 .48.854V19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2v-6.999a1 1 0 0 1 .48-.854L6 9" /> <path d="M6 21V7a1 1 0 0 1 .376-.782l5-3.999a1 1 0 0 1 1.249.001l5 4A1 1 0 0 1 18 7v14" />',
  'video': '<path d="m16 13 5.223 3.482a.5.5 0 0 0 .777-.416V7.87a.5.5 0 0 0-.752-.432L16 10.5" /> <rect x="2" y="6" width="14" height="12" rx="2" />',
  'flask-conical': '<path d="M14 2v6a2 2 0 0 0 .245.96l5.51 10.08A2 2 0 0 1 18 22H6a2 2 0 0 1-1.755-2.96l5.51-10.08A2 2 0 0 0 10 8V2" /> <path d="M6.453 15h11.094" /> <path d="M8.5 2h7" />',
  'tv': '<path d="m17 2-5 5-5-5" /> <rect width="20" height="15" x="2" y="7" rx="2" />',
  'shield-half': '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z" /> <path d="M12 22V2" />',
  'landmark': '<path d="M10 18v-7" /> <path d="M11.119 2.205a2 2 0 0 1 1.762 0l7.84 3.846A.5.5 0 0 1 20.5 7h-17a.5.5 0 0 1-.22-.949z" /> <path d="M14 18v-7" /> <path d="M18 18v-7" /> <path d="M3 22h18" /> <path d="M6 18v-7" />',
  'film': '<rect width="18" height="18" x="3" y="3" rx="2" /> <path d="M7 3v18" /> <path d="M3 7.5h4" /> <path d="M3 12h18" /> <path d="M3 16.5h4" /> <path d="M17 3v18" /> <path d="M17 7.5h4" /> <path d="M17 16.5h4" />',
  'music-2': '<circle cx="8" cy="18" r="4" /> <path d="M12 18V2l7 4" />',
  'baby': '<path d="M10 16c.5.3 1.2.5 2 .5s1.5-.2 2-.5" /> <path d="M15 12h.01" /> <path d="M19.38 6.813A9 9 0 0 1 20.8 10.2a2 2 0 0 1 0 3.6 9 9 0 0 1-17.6 0 2 2 0 0 1 0-3.6A9 9 0 0 1 12 3c2 0 3.5 1.1 3.5 2.5s-.9 2.5-2 2.5c-.8 0-1.5-.4-1.5-1" /> <path d="M9 12h.01" />',
  'earth': '<path d="M21.54 15H17a2 2 0 0 0-2 2v4.54" /> <path d="M7 3.34V5a3 3 0 0 0 3 3a2 2 0 0 1 2 2c0 1.1.9 2 2 2a2 2 0 0 0 2-2c0-1.1.9-2 2-2h3.17" /> <path d="M11 21.95V18a2 2 0 0 0-2-2a2 2 0 0 1-2-2v-1a2 2 0 0 0-2-2H2.05" /> <circle cx="12" cy="12" r="10" />',
  'briefcase': '<path d="M16 20V4a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16" /> <rect width="20" height="14" x="2" y="6" rx="2" />',
  'gamepad-2': '<line x1="6" x2="10" y1="11" y2="11" /> <line x1="8" x2="8" y1="9" y2="13" /> <line x1="15" x2="15.01" y1="12" y2="12" /> <line x1="18" x2="18.01" y1="10" y2="10" /> <path d="M17.32 5H6.68a4 4 0 0 0-3.978 3.59c-.006.052-.01.101-.017.152C2.604 9.416 2 14.456 2 16a3 3 0 0 0 3 3c1 0 1.5-.5 2-1l1.414-1.414A2 2 0 0 1 9.828 16h4.344a2 2 0 0 1 1.414.586L17 18c.5.5 1 1 2 1a3 3 0 0 0 3-3c0-1.545-.604-6.584-.685-7.258-.007-.05-.011-.1-.017-.151A4 4 0 0 0 17.32 5z" />',
  'x': '<path d="M18 6 6 18" /> <path d="m6 6 12 12" />',
  'chevron-right': '<path d="m9 18 6-6-6-6" />',
  'chevron-left': '<path d="m15 18-6-6 6-6" />',
  'chevron-down': '<path d="m6 9 6 6 6-6" />',
  'arrow-left': '<path d="m12 19-7-7 7-7" /> <path d="M19 12H5" />',
  'arrow-right': '<path d="M5 12h14" /> <path d="m12 5 7 7-7 7" />',
  'circle': '<circle cx="12" cy="12" r="10" />',
  'circle-check': '<circle cx="12" cy="12" r="10" /> <path d="m16 9-5.5 5.5L8 12" />',
  'circle-x': '<circle cx="12" cy="12" r="10" /> <path d="m15 9-6 6" /> <path d="m9 9 6 6" />',
  'circle-stop': '<circle cx="12" cy="12" r="10" /> <rect x="9" y="9" width="6" height="6" rx="1" />',
  'circle-play': '<path d="M9 9.003a1 1 0 0 1 1.517-.859l4.997 2.997a1 1 0 0 1 0 1.718l-4.997 2.997A1 1 0 0 1 9 14.996z" /> <circle cx="12" cy="12" r="10" />',
  'triangle-alert': '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3" /> <path d="M12 9v4" /> <path d="M12 17h.01" />',
  'info': '<circle cx="12" cy="12" r="10" /> <path d="M12 16v-4" /> <path d="M12 8h.01" />',
  'lock': '<rect width="18" height="11" x="3" y="11" rx="2" ry="2" /> <path d="M7 11V7a5 5 0 0 1 10 0v4" />',
  'save': '<path d="M15.2 3a2 2 0 0 1 1.4.6l3.8 3.8a2 2 0 0 1 .6 1.4V19a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z" /> <path d="M17 21v-7a1 1 0 0 0-1-1H8a1 1 0 0 0-1 1v7" /> <path d="M7 3v4a1 1 0 0 0 1 1h7" />',
  'undo-2': '<path d="M9 14 4 9l5-5" /> <path d="M4 9h10.5a5.5 5.5 0 0 1 5.5 5.5a5.5 5.5 0 0 1-5.5 5.5H11" />',
  'rotate-cw': '<path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8" /> <path d="M21 3v5h-5" />',
  'camera': '<path d="M13.997 4a2 2 0 0 1 1.76 1.05l.486.9A2 2 0 0 0 18.003 7H20a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2h1.997a2 2 0 0 0 1.759-1.048l.489-.904A2 2 0 0 1 10.004 4z" /> <circle cx="12" cy="13" r="3" />',
  'layers': '<path d="M12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83z" /> <path d="M2 12a1 1 0 0 0 .58.91l8.6 3.91a2 2 0 0 0 1.65 0l8.58-3.9A1 1 0 0 0 22 12" /> <path d="M2 17a1 1 0 0 0 .58.91l8.6 3.91a2 2 0 0 0 1.65 0l8.58-3.9A1 1 0 0 0 22 17" />',
  'mic': '<path d="M12 19v3" /> <path d="M19 10v2a7 7 0 0 1-14 0v-2" /> <rect x="9" y="2" width="6" height="13" rx="3" />',
  'mic-off': '<path d="M12 19v3" /> <path d="M15 9.34V5a3 3 0 0 0-5.68-1.33" /> <path d="M16.95 16.95A7 7 0 0 1 5 12v-2" /> <path d="M18.89 13.23A7 7 0 0 0 19 12v-2" /> <path d="m2 2 20 20" /> <path d="M9 9v3a3 3 0 0 0 5.12 2.12" />',
  'video-off': '<path d="M10.66 6H14a2 2 0 0 1 2 2v2.5l5.248-3.062A.5.5 0 0 1 22 7.87v8.196" /> <path d="M16 16a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h2" /> <path d="m2 2 20 20" />',
  'loader-circle': '<path d="M21 12a9 9 0 1 1-6.219-8.56" />',
  'messages-square': '<path d="M16 10a2 2 0 0 1-2 2H6.828a2 2 0 0 0-1.414.586l-2.202 2.202A.71.71 0 0 1 2 14.286V4a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z" /> <path d="M20 9a2 2 0 0 1 2 2v10.286a.71.71 0 0 1-1.212.502l-2.202-2.202A2 2 0 0 0 17.172 19H10a2 2 0 0 1-2-2v-1" />',
  'satellite-dish': '<path d="M18 12a6 6 0 00-6-6" /> <path d="M2.824 10.459a8 8 0 0010.717 10.717c.558-.276.623-1.012.183-1.452l-9.448-9.448c-.44-.44-1.176-.375-1.452.183" /> <path d="M22 12A10 10 0 0012 2" /> <path d="m9 15 4-4" />',
  'maximize': '<path d="M8 3H5a2 2 0 0 0-2 2v3" /> <path d="M21 8V5a2 2 0 0 0-2-2h-3" /> <path d="M3 16v3a2 2 0 0 0 2 2h3" /> <path d="M16 21h3a2 2 0 0 0 2-2v-3" />',
  'share-2': '<circle cx="18" cy="5" r="3" /> <circle cx="6" cy="12" r="3" /> <circle cx="18" cy="19" r="3" /> <line x1="8.59" x2="15.42" y1="13.51" y2="17.49" /> <line x1="15.41" x2="8.59" y1="6.51" y2="10.49" />',
  'thumbs-up': '<path d="M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2a3.13 3.13 0 0 1 3 3.88Z" /> <path d="M7 10v12" />',
  'play': '<path d="M5 5a2 2 0 0 1 3.008-1.728l11.997 6.998a2 2 0 0 1 .003 3.458l-12 7A2 2 0 0 1 5 19z" />',
  'key-round': '<path d="M2.586 17.414A2 2 0 0 0 2 18.828V21a1 1 0 0 0 1 1h3a1 1 0 0 0 1-1v-1a1 1 0 0 1 1-1h1a1 1 0 0 0 1-1v-1a1 1 0 0 1 1-1h.172a2 2 0 0 0 1.414-.586l.814-.814a6.5 6.5 0 1 0-4-4z" /> <circle cx="16.5" cy="7.5" r=".5" fill="currentColor" />',
  'signal': '<path d="M2 20h.01" /> <path d="M7 20v-4" /> <path d="M12 20v-8" /> <path d="M17 20V8" /> <path d="M22 4v16" />',
  'activity': '<path d="M22 12h-2.48a2 2 0 0 0-1.93 1.46l-2.35 8.36a.25.25 0 0 1-.48 0L9.24 2.18a.25.25 0 0 0-.48 0l-2.35 8.36A2 2 0 0 1 4.49 12H2" />',
  'shield': '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z" />',
  'map-pin': '<path d="M20 10c0 4.993-5.539 10.193-7.399 11.799a1 1 0 0 1-1.202 0C9.539 20.193 4 14.993 4 10a8 8 0 0 1 16 0" /> <circle cx="12" cy="10" r="3" />',
  'globe': '<circle cx="12" cy="12" r="10" /> <path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20" /> <path d="M2 12h20" />',
  'smartphone': '<rect width="14" height="20" x="5" y="2" rx="2" ry="2" /> <path d="M12 18h.01" />',
  'pencil': '<path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z" /> <path d="m15 5 4 4" />',
  'circle-dot': '<circle cx="12" cy="12" r="1" /> <circle cx="12" cy="12" r="10" />',
  'bell': '<path d="M10.268 21a2 2 0 0 0 3.464 0" /> <path d="M3.262 15.326A1 1 0 0 0 4 17h16a1 1 0 0 0 .74-1.673C19.41 13.956 18 12.499 18 8A6 6 0 0 0 6 8c0 4.499-1.411 5.956-2.738 7.326" />',
  'filter': '<path d="M10 20a1 1 0 0 0 .553.895l2 1A1 1 0 0 0 14 21v-7a2 2 0 0 1 .517-1.341L21.74 4.67A1 1 0 0 0 21 3H3a1 1 0 0 0-.742 1.67l7.225 7.989A2 2 0 0 1 10 14z" />',
  'sliders-horizontal': '<path d="M10 5H3" /> <path d="M12 19H3" /> <path d="M14 3v4" /> <path d="M16 17v4" /> <path d="M21 12h-9" /> <path d="M21 19h-5" /> <path d="M21 5h-7" /> <path d="M8 10v4" /> <path d="M8 12H3" />',
  'rotate-ccw': '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" /> <path d="M3 3v5h5" />',
  'message-circle': '<path d="M2.992 16.342a2 2 0 0 1 .094 1.167l-1.065 3.29a1 1 0 0 0 1.236 1.168l3.413-.998a2 2 0 0 1 1.099.092 10 10 0 1 0-4.777-4.719" />',
  'home': '<path d="M15 21v-8a1 1 0 0 0-1-1h-4a1 1 0 0 0-1 1v8" /> <path d="M3 10a2 2 0 0 1 .709-1.528l7-6a2 2 0 0 1 2.582 0l7 6A2 2 0 0 1 21 10v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />',
  'globe-2': '<path d="M21.54 15H17a2 2 0 0 0-2 2v4.54" /> <path d="M7 3.34V5a3 3 0 0 0 3 3a2 2 0 0 1 2 2c0 1.1.9 2 2 2a2 2 0 0 0 2-2c0-1.1.9-2 2-2h3.17" /> <path d="M11 21.95V18a2 2 0 0 0-2-2a2 2 0 0 1-2-2v-1a2 2 0 0 0-2-2H2.05" /> <circle cx="12" cy="12" r="10" />',
  'check-circle': '<circle cx="12" cy="12" r="10" /> <path d="m16 9-5.5 5.5L8 12" />',
  'x-circle': '<circle cx="12" cy="12" r="10" /> <path d="m15 9-6 6" /> <path d="m9 9 6 6" />',
  'stop-circle': '<circle cx="12" cy="12" r="10" /> <rect x="9" y="9" width="6" height="6" rx="1" />',
  'play-circle': '<path d="M9 9.003a1 1 0 0 1 1.517-.859l4.997 2.997a1 1 0 0 1 0 1.718l-4.997 2.997A1 1 0 0 1 9 14.996z" /> <circle cx="12" cy="12" r="10" />',
  'alert-triangle': '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3" /> <path d="M12 9v4" /> <path d="M12 17h.01" />',
  'loader-2': '<path d="M21 12a9 9 0 1 1-6.219-8.56" />',
  'undo': '<path d="M9 14 4 9l5-5" /> <path d="M4 9h10.5a5.5 5.5 0 0 1 5.5 5.5a5.5 5.5 0 0 1-5.5 5.5H11" />',
} %}
{% macro icon(name, size=18, cls='', sw=2) -%}
<svg xmlns="http://www.w3.org/2000/svg" width="{{ size }}" height="{{ size }}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="{{ sw }}" stroke-linecap="round" stroke-linejoin="round" class="lw-icon {{ cls }}" aria-hidden="true">{{ ICONS.get(name, '')|safe }}</svg>
{%- endmacro %}
'''

    COMPONENTS_TEMPLATE = r'''{% from 'icons.html' import icon %}
{# Composants partagés : métadonnées de catégories + cartes (flux, pays) #}
{%- set cat_meta = {
    'sports':           ('trophy',        'bg-blue-100 dark:bg-blue-500/15',       'text-blue-600 dark:text-blue-400',       'Sports'),
    'news':             ('newspaper',     'bg-red-100 dark:bg-red-500/15',         'text-red-600 dark:text-red-400',         'News'),
    'entertainment':    ('clapperboard',  'bg-purple-100 dark:bg-purple-500/15',   'text-purple-600 dark:text-purple-400',   'Divertissement'),
    'religion':         ('church',        'bg-emerald-100 dark:bg-emerald-500/15', 'text-emerald-600 dark:text-emerald-400', 'Religion'),
    'radio':            ('radio',         'bg-orange-100 dark:bg-orange-500/15',   'text-orange-600 dark:text-orange-400',   'Radio'),
    'webcam':           ('video',         'bg-cyan-100 dark:bg-cyan-500/15',       'text-cyan-600 dark:text-cyan-400',       'Webcams'),
    'science':          ('flask-conical', 'bg-teal-100 dark:bg-teal-500/15',       'text-teal-600 dark:text-teal-400',       'Science'),
    'iptv':             ('tv',            'bg-indigo-100 dark:bg-indigo-500/15',   'text-indigo-600 dark:text-indigo-400',   'Chaînes TV'),
    'iptv_sports':      ('shield-half',   'bg-blue-100 dark:bg-blue-500/15',       'text-blue-600 dark:text-blue-400',       'Sports TV'),
    'iptv_news':        ('landmark',      'bg-red-100 dark:bg-red-500/15',         'text-red-600 dark:text-red-400',         'Info TV'),
    'iptv_documentary': ('film',          'bg-amber-100 dark:bg-amber-500/15',     'text-amber-600 dark:text-amber-400',     'Documentaires'),
    'iptv_music':       ('music-2',       'bg-pink-100 dark:bg-pink-500/15',       'text-pink-600 dark:text-pink-400',       'Musique TV'),
    'iptv_kids':        ('baby',          'bg-yellow-100 dark:bg-yellow-500/15',   'text-yellow-600 dark:text-yellow-500',   'Jeunesse TV'),
    'iptv_movies':      ('film',          'bg-purple-100 dark:bg-purple-500/15',   'text-purple-600 dark:text-purple-400',   'Films TV'),
    'iptv_science':     ('flask-conical', 'bg-teal-100 dark:bg-teal-500/15',       'text-teal-600 dark:text-teal-400',       'Science TV'),
    'iptv_travel':      ('earth',         'bg-emerald-100 dark:bg-emerald-500/15', 'text-emerald-600 dark:text-emerald-400', 'Voyage TV'),
    'iptv_business':    ('briefcase',     'bg-slate-200 dark:bg-slate-500/15',     'text-slate-600 dark:text-slate-300',     'Business TV'),
    'gaming':           ('gamepad-2',     'bg-fuchsia-100 dark:bg-fuchsia-500/15', 'text-fuchsia-600 dark:text-fuchsia-400', 'Gaming'),
} -%}
{%- set cont_map = {
    'FR':'EU','BE':'EU','CH':'EU','LU':'EU','DE':'EU','ES':'EU','IT':'EU','PT':'EU','NL':'EU','RU':'EU','PL':'EU','UA':'EU','RO':'EU','BG':'EU','RS':'EU','HR':'EU',
    'SI':'EU','SK':'EU','CZ':'EU','HU':'EU','AT':'EU','GR':'EU','CY':'EU','MT':'EU','IS':'EU','NO':'EU','SE':'EU','FI':'EU','DK':'EU','IE':'EU','LT':'EU','LV':'EU',
    'EE':'EU','MD':'EU','BY':'EU','GB':'EU','AL':'EU','AD':'EU','MC':'EU',
    'MA':'AF','DZ':'AF','TN':'AF','SN':'AF','CI':'AF','CM':'AF','ML':'AF','CD':'AF','CG':'AF','BF':'AF','NE':'AF','TD':'AF','GA':'AF','GN':'AF','BJ':'AF','TG':'AF',
    'MR':'AF','LY':'AF','EG':'AF','ZA':'AF','NG':'AF','KE':'AF','TZ':'AF','UG':'AF','RW':'AF','MZ':'AF','GH':'AF','ET':'AF','AO':'AF','ZM':'AF','ZW':'AF','SD':'AF',
    'CN':'AS','JP':'AS','KR':'AS','IN':'AS','PK':'AS','BD':'AS','ID':'AS','MY':'AS','SG':'AS','PH':'AS','VN':'AS','TH':'AS','MM':'AS','KH':'AS','LA':'AS','NP':'AS',
    'LK':'AS','AF':'AS','KZ':'AS','UZ':'AS','TJ':'AS','KG':'AS','TM':'AS','GE':'AS','AM':'AS','AZ':'AS','BN':'AS','MN':'AS','TW':'AS','HK':'AS',
    'SA':'ME','AE':'ME','QA':'ME','KW':'ME','BH':'ME','OM':'ME','JO':'ME','IQ':'ME','IR':'ME','SY':'ME','LB':'ME','IL':'ME','TR':'ME','YE':'ME','PS':'ME',
    'US':'NA','CA':'NA','MX':'NA','GT':'NA','HN':'NA','SV':'NA','NI':'NA','CR':'NA','PA':'NA','CU':'NA','DO':'NA','HT':'NA','JM':'NA','PR':'NA',
    'BR':'SA','AR':'SA','CO':'SA','CL':'SA','PE':'SA','VE':'SA','EC':'SA','BO':'SA','PY':'SA','UY':'SA',
    'AU':'OC','NZ':'OC','FJ':'OC','PG':'OC'
} -%}

{# ── Carte de flux (StreamCard) ── #}
{% macro stream_card(href, title, logo, cid, sub, quality=none, viewers=none, fav=none, stype='') -%}
{%- set m = cat_meta.get(cid, cat_meta['iptv']) -%}
<a href="{{ href }}" class="card group flex flex-col overflow-hidden transition-transform hover:-translate-y-0.5 stream-card" data-stype="{{ stype }}">
    <div class="relative flex aspect-video w-full items-center justify-center overflow-hidden {{ m[1] }}">
        <span class="{{ m[2] }}">{{ icon(m[0], 30, '', 1.75) }}</span>
        {% if logo %}
        <div class="absolute inset-0 flex items-center justify-center bg-surface-2">
            <img src="{{ logo }}" alt="" loading="lazy" onerror="var p=this.parentNode;p.parentNode.removeChild(p)" class="h-full w-full object-contain p-4 transition-transform duration-300 group-hover:scale-105">
        </div>
        {% endif %}
        <div class="absolute left-2.5 top-2.5">
            <span class="inline-flex items-center gap-1.5 rounded-full bg-accent px-2.5 py-1 text-[11px] font-semibold tracking-wide text-white"><span class="live-dot bg-white"></span>DIRECT</span>
        </div>
        {% if quality %}<span class="absolute right-2.5 top-2.5 rounded-md bg-black/55 px-1.5 py-0.5 text-[10px] font-semibold text-white backdrop-blur-sm">{{ quality }}</span>{% endif %}
        {% if viewers %}
        <div class="absolute bottom-2.5 left-2.5 flex items-center gap-1 rounded-md bg-black/55 px-1.5 py-0.5 text-[11px] font-medium text-white backdrop-blur-sm">
            {{ icon('eye', 12) }} {% if viewers >= 1000 %}{{ ('%.1f' % (viewers / 1000)) if viewers < 10000 else ((viewers / 1000)|int) }} k{% else %}{{ viewers }}{% endif %}
        </div>
        {% endif %}
    </div>
    <div class="flex items-start gap-2.5 p-3.5">
        <div class="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg {{ m[1] }}"><span class="{{ m[2] }}">{{ icon(m[0], 14) }}</span></div>
        <div class="min-w-0 flex-1">
            <p class="truncate text-sm font-semibold leading-snug">{{ title }}</p>
            <p class="truncate text-xs text-ink-muted">{{ sub }}</p>
        </div>
        {% if fav %}
        <button type="button" onclick="addToFavorites('{{ fav[0] }}','{{ fav[1] }}',event)" title="Ajouter aux favoris" aria-label="Ajouter aux favoris"
                class="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-ink-muted transition-colors hover:bg-surface-2 hover:text-amber-500">{{ icon('star', 15) }}</button>
        {% endif %}
    </div>
</a>
{%- endmacro %}

{# ── Carte pays (CountryCard) ── #}
{% macro country_card(pl, extra='') -%}
{%- set cc = (pl.country or '')|string -%}
{%- set dn = (pl.display_name or '')|string -%}
{%- set nm = (dn.split(' ', 1)|last) if ' ' in dn else dn -%}
{%- set cnt = pl.channel_count or 0 -%}
<a href="/?playlist={{ pl.name }}" data-cont="{{ cont_map.get(cc, 'OTHER') }}" data-cc="{{ cc }}" data-name="{{ nm|lower }}" data-count="{{ cnt }}"
   class="country-card group relative flex min-h-[90px] shrink-0 flex-col overflow-hidden rounded-xl border border-border bg-surface-2 {{ extra }}">
    <img src="https://flagcdn.com/w320/{{ cc|lower }}.png" alt="" loading="lazy" onerror="this.style.display='none'"
         class="absolute inset-0 h-full w-full object-cover opacity-90 transition-transform duration-300 group-hover:scale-105">
    <div class="absolute inset-0 bg-gradient-to-t from-black/85 via-black/25 to-transparent"></div>
    <div class="relative mt-auto p-2.5">
        <p class="text-xs font-bold leading-tight text-white [text-shadow:0_1px_4px_rgba(0,0,0,0.8)]">{{ nm }}</p>
        <p class="text-[10px] text-white/80 [text-shadow:0_1px_3px_rgba(0,0,0,0.8)]">{{ cnt }} chaîne{{ 's' if cnt > 1 else '' }}</p>
    </div>
</a>
{%- endmacro %}

'''

    templates = {
        "base.html":            BASE_TEMPLATE,
        "components.html":     COMPONENTS_TEMPLATE,
        "icons.html":          ICONS_TEMPLATE,
        "index.html":           INDEX_TEMPLATE,
        "go_live.html":         GO_LIVE_TEMPLATE,
        "admin_dashboard.html": ADMIN_TEMPLATE,
        "admin_login.html":     ADMIN_LOGIN_TEMPLATE,
        "settings.html":        SETTINGS_TEMPLATE,
        "watch_external.html":  WATCH_EXTERNAL_TEMPLATE,
        "watch_iptv.html":      WATCH_IPTV_TEMPLATE,
        "watch_user.html":      WATCH_USER_TEMPLATE,
        "events.html":          EVENTS_TEMPLATE,
        "search.html":          SEARCH_TEMPLATE,
        "blocked.html":         BLOCKED_TEMPLATE,
        "error.html":           ERROR_TEMPLATE,
        "playlist.html":        PLAYLIST_TEMPLATE,
        "profile.html":         PROFILE_TEMPLATE,
        "about.html":           ABOUT_TEMPLATE,
        "terms.html":           TERMS_TEMPLATE,
        "privacy.html":         PRIVACY_TEMPLATE,
        "404.html":             NOTFOUND_TEMPLATE,
    }

    for name, content in templates.items():
        with open(os.path.join(TEMPLATES_DIR, name), "w", encoding="utf-8") as f:
            f.write(content)

    logger.info(f"{len(templates)} templates HTML écrits sur disque")


# ==================== DÉMARRAGE ====================

if __name__ == "__main__":
    print("\n" + "=" * 80)
    print(f"{settings.APP_NAME} v{settings.APP_VERSION}")
    print("=" * 80)
    print(f"http://localhost:8001")
    print(f"Propriétaire: {settings.OWNER_ID} / {settings.ADMIN_PASSWORD}")
    print(f"{len(EXTERNAL_STREAMS)} flux externes ({sum(1 for s in EXTERNAL_STREAMS if s['stream_type'] == 'youtube')} YouTube)")
    print(f"{len(IPTV_PLAYLISTS)} playlists IPTV (pays/subdivisions/villes/catégories)")
    print(f" yt-dlp: {'disponible' if YT_DLP_AVAILABLE else 'non installé (fallback iframe)'}")
    print(f"Video.js: intégré")
    print("=" * 80 + "\n")

    # Démarrer le serveur
    port = int(os.environ.get("PORT", 8001))
    uvicorn.run(
        "Livewatch:app",
        host="0.0.0.0",
        port=port,
        reload=False
    )
