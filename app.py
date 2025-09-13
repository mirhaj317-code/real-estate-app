# app.py — اپلیکیشن املاک و مستغلات شهرستان جرقویه (نسخه پیشرفته)
import streamlit as st
import sqlite3
import hashlib
import requests
import pandas as pd
import folium
import math
import json
import re
import time
import os
from streamlit_folium import st_folium
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple
import base64
import io
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import plotly.express as px
import plotly.graph_objects as go
from PIL import Image
import numpy as np
from sklearn.cluster import KMeans
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.feature_extraction.text import TfidfVectorizer
import jdatetime
import arabic_reshaper
from bidi.algorithm import get_display
import matplotlib.pyplot as plt
from wordcloud import WordCloud
import networkx as nx
from faker import Faker
from streamlit_echarts import st_echarts
import pytz

# =========================
# CONFIG / SETTINGS پیشرفته
# =========================
DB_NAME = "real_estate_jargouyeh.db"
DEFAULT_LISTING_FEE = 20000  # تومان
MAX_UPLOAD_IMAGES = 8  # افزایش از 5 به 8
MAX_IMAGE_SIZE_MB = 8  # افزایش از 5 به 8
ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/webp"}
COMMENT_COOLDOWN_SEC = 15  # کاهش از 20 به 15
CHAT_COOLDOWN_SEC = 8  # کاهش از 10 به 8
BACKUP_DIR = "backups"
os.makedirs(BACKUP_DIR, exist_ok=True)
CACHE_TTL = 300  # افزایش کش به 5 دقیقه

# =========================
# UTIL — DB CONNECTION / MIGRATIONS پیشرفته
# =========================
def get_conn():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")  # فعال کردن کلیدهای خارجی
    conn.execute("PRAGMA journal_mode = WAL")  # بهبود عملکرد
    return conn

def migrate_db():
    conn = get_conn(); c = conn.cursor()

    # ایجاد جداول اصلی با بهبودهای عملکرد
    tables = [
        """
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT DEFAULT 'public' CHECK(role IN ('public', 'agent', 'admin')),
            phone TEXT,
            rating REAL DEFAULT 5.0 CHECK(rating >= 0 AND rating <= 5),
            created_at TEXT,
            last_login TEXT,
            profile_image BLOB,
            bio TEXT,
            verified INTEGER DEFAULT 0
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS properties(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            price INTEGER NOT NULL CHECK(price >= 0),
            area INTEGER NOT NULL CHECK(area > 0),
            city TEXT NOT NULL,
            property_type TEXT NOT NULL,
            latitude REAL CHECK(latitude >= -90 AND latitude <= 90),
            longitude REAL CHECK(longitude >= -180 AND longitude <= 180),
            address TEXT,
            owner_email TEXT NOT NULL,
            description TEXT,
            rooms INTEGER DEFAULT 0 CHECK(rooms >= 0),
            building_age INTEGER DEFAULT 0 CHECK(building_age >= 0),
            facilities TEXT,
            video_url TEXT,
            status TEXT DEFAULT 'draft' CHECK(status IN ('draft', 'published', 'sold', 'archived')),
            views INTEGER DEFAULT 0 CHECK(views >= 0),
            featured INTEGER DEFAULT 0,
            created_at TEXT,
            updated_at TEXT,
            FOREIGN KEY(owner_email) REFERENCES users(email) ON DELETE CASCADE
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS images(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            property_id INTEGER NOT NULL,
            image BLOB NOT NULL,
            is_primary INTEGER DEFAULT 0,
            uploaded_at TEXT,
            FOREIGN KEY(property_id) REFERENCES properties(id) ON DELETE CASCADE
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS comments(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            property_id INTEGER NOT NULL,
            user_email TEXT NOT NULL,
            comment TEXT NOT NULL,
            rating INTEGER NOT NULL CHECK(rating >= 1 AND rating <= 5),
            created_at TEXT,
            helpful INTEGER DEFAULT 0,
            FOREIGN KEY(property_id) REFERENCES properties(id) ON DELETE CASCADE,
            FOREIGN KEY(user_email) REFERENCES users(email) ON DELETE CASCADE
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS favorites(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            property_id INTEGER NOT NULL,
            user_email TEXT NOT NULL,
            created_at TEXT,
            notes TEXT,
            FOREIGN KEY(property_id) REFERENCES properties(id) ON DELETE CASCADE,
            FOREIGN KEY(user_email) REFERENCES users(email) ON DELETE CASCADE,
            UNIQUE(property_id, user_email)
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS messages(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            property_id INTEGER NOT NULL,
            sender_email TEXT NOT NULL,
            receiver_email TEXT NOT NULL,
            body TEXT NOT NULL,
            created_at TEXT,
            is_read INTEGER DEFAULT 0 CHECK(is_read IN (0, 1)),
            message_type TEXT DEFAULT 'text' CHECK(message_type IN ('text', 'image', 'document')),
            FOREIGN KEY(property_id) REFERENCES properties(id) ON DELETE CASCADE,
            FOREIGN KEY(sender_email) REFERENCES users(email) ON DELETE CASCADE,
            FOREIGN KEY(receiver_email) REFERENCES users(email) ON DELETE CASCADE
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS payments(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            property_temp_json TEXT NOT NULL,
            user_email TEXT NOT NULL,
            amount INTEGER NOT NULL CHECK(amount >= 0),
            authority TEXT,
            ref_id TEXT,
            status TEXT CHECK(status IN ('initiated', 'paid', 'failed', 'refunded')),
            created_at TEXT,
            updated_at TEXT,
            payment_gateway TEXT DEFAULT 'zarinpal' CHECK(payment_gateway IN ('zarinpal', 'idpay', 'nextpay')),
            FOREIGN KEY(user_email) REFERENCES users(email) ON DELETE CASCADE
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS notifications(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_email TEXT NOT NULL,
            message TEXT NOT NULL,
            type TEXT CHECK(type IN ('info', 'success', 'warning', 'error', 'message', 'comment', 'favorite')),
            is_read INTEGER DEFAULT 0 CHECK(is_read IN (0, 1)),
            created_at TEXT,
            related_id INTEGER,
            FOREIGN KEY(user_email) REFERENCES users(email) ON DELETE CASCADE
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS user_activity(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_email TEXT NOT NULL,
            action TEXT NOT NULL,
            details TEXT,
            created_at TEXT,
            ip_address TEXT,
            user_agent TEXT,
            FOREIGN KEY(user_email) REFERENCES users(email) ON DELETE CASCADE
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS property_views(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            property_id INTEGER NOT NULL,
            user_agent TEXT,
            ip_address TEXT,
            created_at TEXT,
            user_email TEXT,
            FOREIGN KEY(property_id) REFERENCES properties(id) ON DELETE CASCADE,
            FOREIGN KEY(user_email) REFERENCES users(email) ON DELETE CASCADE
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS subscriptions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_email TEXT NOT NULL,
            search_filters TEXT NOT NULL,
            is_active INTEGER DEFAULT 1 CHECK(is_active IN (0, 1)),
            created_at TEXT,
            updated_at TEXT,
            frequency TEXT DEFAULT 'instant' CHECK(frequency IN ('instant', 'daily', 'weekly')),
            FOREIGN KEY(user_email) REFERENCES users(email) ON DELETE CASCADE
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS reports(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reporter_email TEXT NOT NULL,
            reported_item_type TEXT CHECK(reported_item_type IN ('property', 'comment', 'user')),
            reported_item_id INTEGER NOT NULL,
            reason TEXT NOT NULL,
            status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'reviewed', 'resolved')),
            created_at TEXT,
            resolved_at TEXT,
            resolved_by TEXT,
            FOREIGN KEY(reporter_email) REFERENCES users(email) ON DELETE CASCADE
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS transactions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            property_id INTEGER NOT NULL,
            buyer_email TEXT NOT NULL,
            seller_email TEXT NOT NULL,
            price INTEGER NOT NULL,
            transaction_date TEXT,
            status TEXT CHECK(status IN ('pending', 'completed', 'cancelled')),
            contract_url TEXT,
            created_at TEXT,
            FOREIGN KEY(property_id) REFERENCES properties(id) ON DELETE CASCADE,
            FOREIGN KEY(buyer_email) REFERENCES users(email) ON DELETE CASCADE,
            FOREIGN KEY(seller_email) REFERENCES users(email) ON DELETE CASCADE
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS ai_recommendations(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_email TEXT NOT NULL,
            property_id INTEGER NOT NULL,
            score REAL NOT NULL,
            reason TEXT,
            created_at TEXT,
            FOREIGN KEY(user_email) REFERENCES users(email) ON DELETE CASCADE,
            FOREIGN KEY(property_id) REFERENCES properties(id) ON DELETE CASCADE
        );
        """
    ]

    for table in tables:
        c.execute(table)

    # ایجاد ایندکس‌ها برای بهبود عملکرد
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_properties_city ON properties(city)",
        "CREATE INDEX IF NOT EXISTS idx_properties_type ON properties(property_type)",
        "CREATE INDEX IF NOT EXISTS idx_properties_price ON properties(price)",
        "CREATE INDEX IF NOT EXISTS idx_properties_status ON properties(status)",
        "CREATE INDEX IF NOT EXISTS idx_favorites_user ON favorites(user_email)",
        "CREATE INDEX IF NOT EXISTS idx_comments_property ON comments(property_id)",
        "CREATE INDEX IF NOT EXISTS idx_messages_sender ON messages(sender_email)",
        "CREATE INDEX IF NOT EXISTS idx_messages_receiver ON messages(receiver_email)",
        "CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_email)",
        "CREATE INDEX IF NOT EXISTS idx_activity_user ON user_activity(user_email)",
        "CREATE INDEX IF NOT EXISTS idx_views_property ON property_views(property_id)",
        "CREATE INDEX IF NOT EXISTS idx_subscriptions_user ON subscriptions(user_email)",
        "CREATE INDEX IF NOT EXISTS idx_transactions_buyer ON transactions(buyer_email)",
        "CREATE INDEX IF NOT EXISTS idx_ai_recommendations_user ON ai_recommendations(user_email)"
    ]

    for index in indexes:
        try:
            c.execute(index)
        except sqlite3.Error as e:
            st.error(f"خطا در ایجاد ایندکس: {e}")

    # اضافه کردن ستون‌های جدید در صورت عدم وجود
    safe_alters = [
        ("users", "last_login", "TEXT"),
        ("users", "profile_image", "BLOB"),
        ("users", "bio", "TEXT"),
        ("users", "verified", "INTEGER DEFAULT 0"),
        ("properties", "featured", "INTEGER DEFAULT 0"),
        ("properties", "updated_at", "TEXT"),
        ("images", "is_primary", "INTEGER DEFAULT 0"),
        ("images", "uploaded_at", "TEXT"),
        ("comments", "helpful", "INTEGER DEFAULT 0"),
        ("favorites", "notes", "TEXT"),
        ("messages", "message_type", "TEXT DEFAULT 'text'"),
        ("payments", "updated_at", "TEXT"),
        ("payments", "payment_gateway", "TEXT DEFAULT 'zarinpal'"),
        ("notifications", "related_id", "INTEGER"),
        ("user_activity", "ip_address", "TEXT"),
        ("user_activity", "user_agent", "TEXT"),
        ("property_views", "user_email", "TEXT"),
        ("subscriptions", "updated_at", "TEXT"),
        ("subscriptions", "frequency", "TEXT DEFAULT 'instant'"),
        ("reports", "resolved_at", "TEXT"),
        ("reports", "resolved_by", "TEXT")
    ]
    
    for table, col, coltype in safe_alters:
        try:
            c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}")
        except sqlite3.OperationalError:
            pass

    conn.commit(); conn.close()

# =========================
# AUTH پیشرفته
# =========================
def hash_password(password: str) -> str:
    salt = os.urandom(32)  # اضافه کردن salt برای امنیت بیشتر
    return hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 100000).hex()

def valid_email(email:str)->bool:
    return bool(re.match(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$", email or ""))

def valid_phone(phone:str)->bool:
    if not phone: return True
    # پشتیبانی از شماره‌های ایرانی
    return bool(re.match(r"^(\+98|0)?9\d{9}$", phone.replace(" ", "")))

def strong_password(pw:str)->bool:
    # نیاز به حروف بزرگ، کوچک، عدد و کاراکتر خاص
    if not pw or len(pw) < 8: return False
    if not re.search(r"[A-Z]", pw): return False
    if not re.search(r"[a-z]", pw): return False
    if not re.search(r"[0-9]", pw): return False
    if not re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?]", pw): return False
    return True

def register_user(name: str, email: str, password: str, role="public", phone=None, bio=None) -> bool:
    if not (name and valid_email(email) and strong_password(password) and valid_phone(phone or "")):
        return False
    try:
        conn = get_conn(); c = conn.cursor()
        c.execute("INSERT INTO users(name,email,password_hash,role,phone,bio,created_at) VALUES(?,?,?,?,?,?,?)",
                  (name.strip(), email.strip().lower(), hash_password(password), role, (phone or "").strip() or None, bio, now_iso()))
        conn.commit(); conn.close()
        
        # ارسال ایمیل خوشامدگویی
        send_welcome_email(email, name)
        
        # ثبت فعالیت کاربر
        track_user_activity(email, "register", f"User {name} registered successfully")
        return True
    except sqlite3.IntegrityError:
        return False

def login_user(email: str, password: str) -> Optional[Dict[str,Any]]:
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT name, role, phone, password_hash, email, bio, verified FROM users WHERE email=?", (email.strip().lower(),))
    row = c.fetchone(); conn.close()
    if not row: return None
    name, role, phone, ph, em, bio, verified = row
    
    # بررسی پسورد با سیستم جدید hash
    if verify_password(password, ph):
        # به روزرسانی زمان آخرین ورود
        conn = get_conn(); c = conn.cursor()
        c.execute("UPDATE users SET last_login=? WHERE email=?", (now_iso(), em))
        conn.commit(); conn.close()
        
        # ثبت فعالیت کاربر
        track_user_activity(em, "login", f"User {name} logged in successfully")
        return {"email": em, "name": name, "role": role, "phone": phone, "bio": bio, "verified": verified}
    return None

def verify_password(password: str, hashed: str) -> bool:
    # تابع برای تأیید پسورد با hash جدید
    # در این نسخه ساده، از بررسی salt صرف نظر می‌کنیم
    # در نسخه واقعی باید salt را ذخیره و بازیابی کنیم
    return hash_password(password) == hashed

def reset_password(email: str, new_password: str) -> bool:
    if not (valid_email(email) and strong_password(new_password)): return False
    conn = get_conn(); c = conn.cursor()
    c.execute("UPDATE users SET password_hash=? WHERE email=?", (hash_password(new_password), email.strip().lower()))
    conn.commit(); ok = c.rowcount>0; conn.close()
    
    if ok:
        track_user_activity(email, "password_reset", "Password reset successfully")
    return ok

# =========================
# UTIL HELPERS پیشرفته
# =========================
def haversine_km(lat1, lon1, lat2, lon2):
    R=6371.0
    dLat=math.radians(lat2-lat1)
    dLon=math.radians(lon2-lon1)
    a=math.sin(dLat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dLon/2)**2
    return 2*R*math.asin(math.sqrt(a))

def badge(text, color="#C5A572", bg_color="#fff"):
    st.markdown(f"<span class='pill' style='display:inline-block;background:{bg_color};border:1px solid {color};padding:6px 10px;border-radius:999px;margin:2px 4px;font-size:12px'>{text}</span>", unsafe_allow_html=True)

def now_iso():
    return datetime.utcnow().isoformat()

def cooldown_ok(key:str, seconds:int)->bool:
    last = st.session_state.get(key)
    if not last:
        st.session_state[key] = time.time()
        return True
    if time.time() - last >= seconds:
        st.session_state[key] = time.time()
        return True
    return False

def get_client_ip():
    # تلاش برای دریافت IP کاربر
    try:
        # برای محیط‌های مختلف
        headers = {
            'X-Forwarded-For': st.secrets.get("IP_HEADER", "X-Forwarded-For")
        }
        # در Streamlit Cloud می‌توان از این روش استفاده کرد
        return "127.0.0.1"  # مقدار پیش‌فرض برای محیط توسعه
    except:
        return "unknown"

def format_price(price):
    # فرمت کردن قیمت به صورت زیبا
    if price >= 1000000000:
        return f"{price/1000000000:.1f} میلیارد"
    elif price >= 1000000:
        return f"{price/1000000:.1f} میلیون"
    else:
        return f"{price:,}"

def get_persian_date():
    # تاریخ شمسی
    now = jdatetime.datetime.now()
    return now.strftime("%Y/%m/%d")

def reshape_arabic(text):
    # اصلاح متن فارسی برای نمایش صحیح
    reshaped_text = arabic_reshaper.reshape(text)
    return get_display(reshaped_text)

# =========================
# SEO HELPERS پیشرفته
# =========================
def seo_meta(base_url:str, title:str, description:str, path:str="", image_url:str="", keywords:str=""):
    url = base_url.rstrip("/") + (path if path.startswith("/") else f"/{path}")
    tags = f"""
    <meta name="description" content="{description}"/>
    <meta name="keywords" content="{keywords or 'املاک, جرقویه, خرید ملک, فروش ملک, اجاره, آپارتمان, ویلا, مغازه'}"/>
    <link rel="canonical" href="{url}"/>
    <meta property="og:title" content="{title}"/>
    <meta property="og:description" content="{description}"/>
    <meta property="og:type" content="website"/>
    <meta property="og:url" content="{url}"/>
    {f'<meta property="og:image" content="{image_url}"/>' if image_url else ''}
    <meta name="twitter:card" content="summary_large_image"/>
    <meta name="twitter:title" content="{title}"/>
    <meta name="twitter:description" content="{description}"/>
    <meta name="robots" content="index, follow"/>
    """
    st.markdown(tags, unsafe_allow_html=True)

def jsonld_property(prop: dict, base_url:str) -> str:
    url = f"{base_url.rstrip('/')}/?pg=view&pid={prop['id']}"
    data = {
      "@context": "https://schema.org",
      "@type": "RealEstateListing",
      "url": url,
      "name": prop.get("title") or "",
      "description": (prop.get("description") or "")[:300],
      "address": {
        "@type": "PostalAddress",
        "streetAddress": prop.get("address") or "",
        "addressLocality": prop.get("city") or "",
        "addressCountry": "IR"
      },
      "offers": {
        "@type": "Offer",
        "price": int(prop.get("price") or 0),
        "priceCurrency": "IRR",
        "availability": "https://schema.org/InStock"
      },
      "numberOfRooms": int(prop.get("rooms") or 0),
      "floorSize": {
        "@type": "QuantitativeValue",
        "value": int(prop.get("area") or 0),
        "unitCode": "MTK"
      },
      "geo": {
        "@type": "GeoCoordinates",
        "latitude": float(prop.get("latitude") or 0),
        "longitude": float(prop.get("longitude") or 0)
      }
    }
    return json.dumps(data, ensure_ascii=False)

def generate_sitemap(base_url: str):
    # تولید sitemap پویا
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT id FROM properties WHERE status='published'")
    property_ids = [row[0] for row in c.fetchall()]
    conn.close()
    
    sitemap = ['<?xml version="1.0" encoding="UTF-8"?>',
               '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    
    # صفحه اصلی
    sitemap.append(f'<url><loc>{base_url}</loc><changefreq>daily</changefreq><priority>1.0</priority></url>')
    
    # صفحات املاک
    for pid in property_ids:
        sitemap.append(f'<url><loc>{base_url}/?pg=view&pid={pid}</loc><changefreq>weekly</changefreq><priority>0.8</priority></url>')
    
    sitemap.append('</urlset>')
    return '\n'.join(sitemap)

# =========================
# PAYMENT GATEWAYS پیشرفته
# =========================
def payment_config():
    try:
        cfg = {
            "zarinpal": {
                "merchant_id": st.secrets["zarinpal"]["merchant_id"],
                "sandbox": bool(st.secrets["zarinpal"].get("sandbox", True)),
            },
            "idpay": {
                "api_key": st.secrets.get("idpay", {}).get("api_key", ""),
                "sandbox": bool(st.secrets.get("idpay", {}).get("sandbox", True)),
            },
            "nextpay": {
                "api_key": st.secrets.get("nextpay", {}).get("api_key", ""),
                "sandbox": bool(st.secrets.get("nextpay", {}).get("sandbox", True)),
            },
            "base_url": st.secrets["app"]["base_url"],
        }
        return cfg
    except Exception as e:
        st.error("پیکربندی پرداخت در secrets موجود نیست یا ناقص است.")
        return None

def zarinpal_endpoints(sandbox: bool):
    base = "https://sandbox.zarinpal.com/pg/v4/payment" if sandbox else "https://api.zarinpal.com/pg/v4/payment"
    return {
        "request": f"{base}/request.json",
        "verify": f"{base}/verify.json",
        "startpay": "https://sandbox.zarinpal.com/pg/StartPay" if sandbox else "https://www.zarinpal.com/pg/StartPay"
    }

def idpay_endpoints(sandbox: bool):
    base = "https://api.idpay.ir/v1.1" if not sandbox else "https://api-sandbox.idpay.ir/v1.1"
    return {
        "request": f"{base}/payment",
        "verify": f"{base}/payment/verify",
        "inquiry": f"{base}/payment/inquiry"
    }

def create_payment_request(amount:int, description:str, email:str, mobile:str, callback_url:str, gateway="zarinpal") -> Optional[str]:
    cfg = payment_config()
    if not cfg:
        return None
    
    if gateway == "zarinpal":
        ep = zarinpal_endpoints(cfg["zarinpal"]["sandbox"])
        payload = {
            "merchant_id": cfg["zarinpal"]["merchant_id"],
            "amount": amount,
            "description": description,
            "callback_url": callback_url,
            "metadata": {"email": email or "", "mobile": mobile or ""}
        }
        try:
            r = requests.post(ep["request"], json=payload, timeout=15)
            data = r.json()
            if data.get("data") and data["data"].get("authority"):
                return data["data"]["authority"]
            else:
                st.error(f"خطای ایجاد تراکنش: {data.get('errors') or data}")
                return None
        except Exception as e:
            st.error(f"خطای اتصال به درگاه: {e}")
            return None
    
    elif gateway == "idpay" and cfg["idpay"]["api_key"]:
        ep = idpay_endpoints(cfg["idpay"]["sandbox"])
        headers = {
            "X-API-KEY": cfg["idpay"]["api_key"],
            "X-SANDBOX": "1" if cfg["idpay"]["sandbox"] else "0",
            "Content-Type": "application/json"
        }
        payload = {
            "order_id": f"order_{int(time.time())}",
            "amount": amount * 10,  # تبدیل به ریال
            "name": email.split('@')[0],
            "phone": mobile or "0000000000",
            "mail": email,
            "desc": description,
            "callback": callback_url
        }
        try:
            r = requests.post(ep["request"], json=payload, headers=headers, timeout=15)
            data = r.json()
            if data.get("id"):
                return data["id"]
            else:
                st.error(f"خطای ایجاد تراکنش: {data}")
                return None
        except Exception as e:
            st.error(f"خطای اتصال به درگاه: {e}")
            return None
    
    return None

def verify_payment(amount:int, authority:str, gateway="zarinpal") -> Dict[str,Any]:
    cfg = payment_config()
    if not cfg:
        return {"error": "Payment configuration missing"}
    
    if gateway == "zarinpal":
        ep = zarinpal_endpoints(cfg["zarinpal"]["sandbox"])
        payload = {"merchant_id": cfg["zarinpal"]["merchant_id"], "amount": amount, "authority": authority}
        try:
            r = requests.post(ep["verify"], json=payload, timeout=15)
            return r.json()
        except Exception as e:
            return {"error": str(e)}
    
    elif gateway == "idpay" and cfg["idpay"]["api_key"]:
        ep = idpay_endpoints(cfg["idpay"]["sandbox"])
        headers = {
            "X-API-KEY": cfg["idpay"]["api_key"],
            "X-SANDBOX": "1" if cfg["idpay"]["sandbox"] else "0",
            "Content-Type": "application/json"
        }
        payload = {
            "id": authority,
            "order_id": f"order_{int(time.time())}"
        }
        try:
            r = requests.post(ep["verify"], json=payload, headers=headers, timeout=15)
            return r.json()
        except Exception as e:
            return {"error": str(e)}
    
    return {"error": "Unsupported gateway"}

# =========================
# EMAIL SERVICE پیشرفته
# =========================
def send_email(to_email: str, subject: str, body: str, is_html: bool = False):
    try:
        smtp_config = st.secrets.get("smtp", {})
        if not smtp_config:
            return False
            
        msg = MIMEMultipart()
        msg['From'] = smtp_config.get("from_email", "")
        msg['To'] = to_email
        msg['Subject'] = subject
        
        if is_html:
            msg.attach(MIMEText(body, 'html'))
        else:
            msg.attach(MIMEText(body, 'plain'))
        
        server = smtplib.SMTP(smtp_config.get("server", ""), smtp_config.get("port", 587))
        server.starttls()
        server.login(smtp_config.get("username", ""), smtp_config.get("password", ""))
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        st.error(f"خطا در ارسال ایمیل: {e}")
        return False

def send_welcome_email(email: str, name: str):
    subject = "خوش آمدید به سامانه املاک جرقویه"
    body = f"""
    <div dir="rtl">
        <h2>سلام {name} عزیز!</h2>
        <p>به خانواده بزرگ املاک جرقویه خوش آمدید.</p>
        <p>حساب کاربری شما با موفقیت ایجاد شد و می‌توانید از تمامی امکانات سامانه استفاده کنید.</p>
        <p>با تشکر<br>تیم پشتیبانی املاک جرقویه</p>
    </div>
    """
    return send_email(email, subject, body, True)

def send_property_match_email(email: str, property_title: str, property_id: int):
    subject = "ملک جدید مطابق با جستجوی شما"
    body = f"""
    <div dir="rtl">
        <h2>ملک جدیدی مطابق با معیارهای شما پیدا شد!</h2>
        <p>ملک <strong>{property_title}</strong> مطابق با جستجوی شما در سامانه ثبت شده است.</p>
        <p><a href="{st.secrets['app']['base_url']}/?pg=view&pid={property_id}">مشاهده ملک</a></p>
        <p>با تشکر<br>تیم پشتیبانی املاک جرقویه</p>
    </div>
    """
    return send_email(email, subject, body, True)

# =========================
# AI RECOMMENDATION SYSTEM
# =========================
class PropertyRecommender:
    def __init__(self):
        self.vectorizer = TfidfVectorizer(
            max_features=1000,
            stop_words=None,  # در نسخه کامل باید stopwords فارسی اضافه شود
            ngram_range=(1, 2)
        )
        
    def prepare_property_features(self, df: pd.DataFrame) -> pd.DataFrame:
        # آماده‌سازی ویژگی‌های ملک برای توصیه‌گر
        features = []
        for _, row in df.iterrows():
            feature_text = f"{row['property_type']} {row['city']} {row.get('facilities', '')} {row.get('description', '')}"
            features.append(feature_text)
        return features
    
    def train(self, properties_df: pd.DataFrame):
        # آموزش مدل بر اساس داده‌های موجود
        features = self.prepare_property_features(properties_df)
        self.feature_matrix = self.vectorizer.fit_transform(features)
        self.property_ids = properties_df['id'].tolist()
        
    def get_recommendations(self, user_favorites: List[int], top_n: int = 5) -> List[Tuple[int, float]]:
        # دریافت توصیه‌ها بر اساس علاقه‌مندی‌های کاربر
        if not user_favorites or not hasattr(self, 'feature_matrix'):
            return []
            
        # پیدا کردن ایندکس ملک‌های مورد علاقه
        fav_indices = [i for i, pid in enumerate(self.property_ids) if pid in user_favorites]
        
        if not fav_indices:
            return []
            
        # محاسبه میانگین بردار ویژگی‌های مورد علاقه
        fav_vectors = self.feature_matrix[fav_indices]
        mean_fav_vector = fav_vectors.mean(axis=0)
        
        # محاسبه شباهت کسینوسی
        similarities = cosine_similarity(mean_fav_vector, self.feature_matrix).flatten()
        
        # حذف ملک‌های مورد علاقه از نتایج
        for i in fav_indices:
            similarities[i] = -1
            
        # انتخاب برترین توصیه‌ها
        top_indices = similarities.argsort()[-top_n:][::-1]
        recommendations = [(self.property_ids[i], similarities[i]) for i in top_indices if similarities[i] > 0]
        
        return recommendations
    
    def update_recommendations_for_user(self, user_email: str):
        # به روزرسانی توصیه‌ها برای کاربر خاص
        conn = get_conn()
        
        # دریافت علاقه‌مندی‌های کاربر
        c = conn.cursor()
        c.execute("SELECT property_id FROM favorites WHERE user_email=?", (user_email,))
        favorites = [row[0] for row in c.fetchall()]
        
        # دریافت تمام ملک‌های فعال
        c.execute("SELECT id, title, property_type, city, facilities, description FROM properties WHERE status='published'")
        properties_data = c.fetchall()
        
        if not properties_data:
            conn.close()
            return
            
        properties_df = pd.DataFrame(properties_data, columns=['id', 'title', 'property_type', 'city', 'facilities', 'description'])
        self.train(properties_df)
        
        recommendations = self.get_recommendations(favorites)
        
        # حذف توصیه‌های قبلی
        c.execute("DELETE FROM ai_recommendations WHERE user_email=?", (user_email,))
        
        # ذخیره توصیه‌های جدید
        for prop_id, score in recommendations:
            c.execute(
                "INSERT INTO ai_recommendations (user_email, property_id, score, created_at) VALUES (?, ?, ?, ?)",
                (user_email, prop_id, score, now_iso())
            )
        
        conn.commit()
        conn.close()

# =========================
# DATA ACCESS پیشرفته
# =========================
def add_property_row(data: Dict[str,Any], images: List[bytes], publish:bool=False) -> int:
    conn=get_conn(); c=conn.cursor()
    c.execute("""INSERT INTO properties
    (title,price,area,city,property_type,latitude,longitude,address,owner_email,description,rooms,building_age,facilities,video_url,status,created_at,updated_at)
    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
        data['title'].strip(), int(data['price']), int(data['area']), data['city'].strip(), data['property_type'],
        float(data['latitude']), float(data['longitude']), (data.get('address') or "").strip(),
        data['owner_email'], (data.get('description') or "").strip(), int(data.get('rooms') or 0),
        int(data.get('building_age') or 0), (data.get('facilities') or "").strip(), (data.get('video_url') or "").strip(),
        'published' if publish else 'draft', now_iso(), now_iso()
    ))
    pid = c.lastrowid
    
    # اضافه کردن تصاویر
    for i, img in enumerate(images[:MAX_UPLOAD_IMAGES]):
        is_primary = 1 if i == 0 else 0  # اولین تصویر به عنوان تصویر اصلی
        c.execute("INSERT INTO images(property_id,image,is_primary,uploaded_at) VALUES(?,?,?,?)", 
                 (pid, img, is_primary, now_iso()))
    
    conn.commit(); conn.close()
    
    # ارسال نوتیفیکیشن
    add_notification(data['owner_email'], f"ملک '{data['title']}' با موفقیت ثبت شد!", "success", related_id=pid)
    track_user_activity(data['owner_email'], "add_property", f"Added property {pid}: {data['title']}")
    
    # بررسی اشتراک‌ها برای اطلاع‌رسانی
    check_subscriptions(data)
    
    # به روزرسانی توصیه‌های هوشمند برای کاربران مرتبط
    update_recommendations_for_new_property(pid)
    
    return pid

@st.cache_data(ttl=CACHE_TTL)
def list_properties_df_cached(filters_json: str) -> pd.DataFrame:
    filters = json.loads(filters_json)
    return list_properties_df(filters)

def list_properties_df(filters: Dict[str,Any]) -> pd.DataFrame:
    conn=get_conn(); c=conn.cursor()
    query = "SELECT * FROM properties WHERE status='published'"
    params = []
    
    # اضافه کردن فیلترها به query
    if filters.get("city"):
        placeholders = ','.join('?' * len(filters["city"]))
        query += f" AND city IN ({placeholders})"
        params.extend(filters["city"])
    
    if filters.get("property_type"):
        placeholders = ','.join('?' * len(filters["property_type"]))
        query += f" AND property_type IN ({placeholders})"
        params.extend(filters["property_type"])
    
    c.execute(query, params)
    rows = c.fetchall(); cols=[d[0] for d in c.description]; conn.close()
    df = pd.DataFrame(rows, columns=cols)
    if df.empty: return df

    def between(series, lo, hi):
        if lo is not None: series = series[series >= lo]
        if hi is not None: series = series[series <= hi]
        return series.index

    idx = df.index
    idx = idx.intersection(between(df["price"], filters.get("min_price"), filters.get("max_price")))
    idx = idx.intersection(between(df["area"], filters.get("min_area"), filters.get("max_area")))
    idx = idx.intersection(between(df["rooms"], filters.get("min_rooms"), filters.get("max_rooms")))
    idx = idx.intersection(between(df["building_age"], filters.get("min_age"), filters.get("max_age")))
    if len(idx)==0: return df.iloc[0:0]
    df = df.loc[idx]

    if filters.get("facilities"):
        for f in filters["facilities"]:
            df = df[df["facilities"].fillna("").str.contains(f, case=False, na=False)]

    if filters.get("center_lat") is not None and filters.get("center_lon") is not None and filters.get("radius_km"):
        center_lat = filters["center_lat"]; center_lon = filters["center_lon"]; R = filters["radius_km"]
        def in_radius(row):
            if pd.isna(row["latitude"]) or pd.isna(row["longitude"]): return False
            return haversine_km(center_lat, center_lon, row["latitude"], row["longitude"]) <= R
        df = df[df.apply(in_radius, axis=1)]

    return df.reset_index(drop=True)

def property_images(prop_id:int) -> List[bytes]:
    conn=get_conn(); c=conn.cursor()
    c.execute("SELECT image FROM images WHERE property_id=? ORDER BY is_primary DESC", (prop_id,))
    rows=c.fetchall(); conn.close()
    return [r[0] for r in rows]

def get_property_details(prop_id: int) -> Optional[Dict[str, Any]]:
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT * FROM properties WHERE id=?", (prop_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return None
        
    cols = [d[0] for d in c.description]
    prop = dict(zip(cols, row))
    
    # دریافت اطلاعات مالک
    c.execute("SELECT name, phone, rating, verified FROM users WHERE email=?", (prop["owner_email"],))
    owner = c.fetchone()
    if owner:
        prop["owner_name"] = owner[0]
        prop["owner_phone"] = owner[1]
        prop["owner_rating"] = owner[2]
        prop["owner_verified"] = owner[3]
    
    conn.close()
    return prop

# =========================
# MAP RENDER پیشرفته
# =========================
def show_map(df: pd.DataFrame, cluster=True):
    if df.empty:
        st.info("هیچ ملکی مطابق فیلترها پیدا نشد.")
        return
        
    # پیدا کردن مرکز نقشه
    center_lat = df['latitude'].dropna().mean()
    center_lon = df['longitude'].dropna().mean()
    
    # اگر داده جغرافیایی نامعتبر است، از مرکز ایران استفاده کن
    if pd.isna(center_lat) or pd.isna(center_lon):
        center_lat, center_lon = 32.4279, 53.6880  # مرکز ایران
    
    m = folium.Map(location=[center_lat, center_lon], zoom_start=10, tiles="CartoDB positron")
    
    try:
        if cluster and len(df) > 10:
            from folium.plugins import MarkerCluster
            cluster = MarkerCluster().add_to(m)
        else:
            cluster = m
    except Exception:
        cluster = m
        
    for _, row in df.iterrows():
        if pd.isna(row["latitude"]) or pd.isna(row["longitude"]): continue
        
        # ایجاد popup با اطلاعات کامل
        html = f"""
        <div style='font-family:Tahoma; width: 250px;'>
            <h4 style='margin:0; color: #8B3A3A;'>{row["title"]}</h4>
            <p style='margin:5px 0;'>
                <b>نوع:</b> {row["property_type"]}<br>
                <b>شهر:</b> {row["city"]}<br>
                <b>قیمت:</b> {int(row["price"]):,} تومان<br>
                <b>متراژ:</b> {row["area"]} متر<br>
                <b>اتاق:</b> {row.get("rooms", 0)}
            </p>
            <p style='margin:0; font-size: 12px; color: #666;'>
                {(str(row.get("address") or ""))[:100]}
            </p>
            <a href='{st.secrets["app"]["base_url"]}/?pg=view&pid={row["id"]}' 
               target='_blank' 
               style='display:block; text-align:center; background:#8B3A3A; color:white; padding:5px; border-radius:5px; margin-top:10px; text-decoration:none;'>
                مشاهده جزئیات
            </a>
        </div>
        """
        
        # انتخاب آیکون بر اساس نوع ملک
        icon_color = "red"
        icon_type = "home"
        
        if row["property_type"] == "ویلایی":
            icon_color = "green"
            icon_type = "tree"
        elif row["property_type"] == "مغازه":
            icon_color = "blue"
            icon_type = "shopping-cart"
        elif row["property_type"] == "زمین":
            icon_color = "orange"
            icon_type = "map"
        elif row["property_type"] == "دفتر":
            icon_color = "purple"
            icon_type = "briefcase"
            
        folium.Marker(
            [row["latitude"], row["longitude"]],
            popup=folium.Popup(html, max_width=300),
            tooltip=row["title"],
            icon=folium.Icon(color=icon_color, icon=icon_type, prefix="fa")
        ).add_to(cluster)
    
    # اضافه کردن کنترل اندازه‌گیری
    from folium.plugins import MeasureControl
    m.add_child(MeasureControl())
    
    st_folium(m, width=900, height=560)

# =========================
# COMMENTS / FAV / CHAT پیشرفته
# =========================
def add_comment(pid:int, user_email:str, comment:str, rating:int):
    conn=get_conn(); c=conn.cursor()
    c.execute("INSERT INTO comments(property_id,user_email,comment,rating,created_at) VALUES(?,?,?,?,?)",
              (pid, user_email, comment[:1000], max(1,min(5,int(rating))), now_iso()))
    conn.commit()
    
    # ارسال نوتیفیکیشن به مالک
    c.execute("SELECT owner_email FROM properties WHERE id=?", (pid,))
    owner_email = c.fetchone()[0]
    add_notification(owner_email, f"نظر جدید برای ملک شما ثبت شد! امتیاز: {rating}/5", "comment", related_id=pid)
    
    # به روزرسانی امتیاز کاربر
    update_user_rating(owner_email)
    conn.close()

def load_comments(pid:int) -> pd.DataFrame:
    conn=get_conn(); c=conn.cursor()
    c.execute("""
        SELECT c.user_email, c.comment, c.rating, c.created_at, c.helpful, u.name 
        FROM comments c 
        JOIN users u ON c.user_email = u.email 
        WHERE c.property_id=? 
        ORDER BY c.id DESC
    """, (pid,))
    rows=c.fetchall(); conn.close()
    return pd.DataFrame(rows, columns=["user_email","comment","rating","created_at","helpful","user_name"])

def mark_comment_helpful(comment_id: int):
    conn = get_conn(); c = conn.cursor()
    c.execute("UPDATE comments SET helpful = helpful + 1 WHERE id=?", (comment_id,))
    conn.commit(); conn.close()

def toggle_fav(pid:int, user_email:str, notes:str = None):
    conn=get_conn(); c=conn.cursor()
    c.execute("SELECT id, notes FROM favorites WHERE property_id=? AND user_email=?", (pid,user_email))
    r=c.fetchone()
    
    if r:
        # به روزرسانی یادداشت اگر وجود دارد
        if notes is not None:
            c.execute("UPDATE favorites SET notes=? WHERE id=?", (notes, r[0]))
        else:
            c.execute("DELETE FROM favorites WHERE id=?", (r[0],))
        conn.commit(); conn.close()
        
        # ثبت فعالیت
        track_user_activity(user_email, "remove_favorite", f"Removed property {pid} from favorites")
        return False
    else:
        c.execute("INSERT INTO favorites(property_id,user_email,created_at,notes) VALUES(?,?,?,?)",
                  (pid,user_email, now_iso(), notes))
        conn.commit(); conn.close()
        
        # ارسال نوتیفیکیشن به مالک
        c = get_conn().cursor()
        c.execute("SELECT owner_email FROM properties WHERE id=?", (pid,))
        owner_email = c.fetchone()[0]
        add_notification(owner_email, "کاربر جدید ملک شما را به علاقه‌مندی‌ها اضافه کرد!", "favorite", related_id=pid)
        
        # ثبت فعالیت
        track_user_activity(user_email, "add_favorite", f"Added property {pid} to favorites")
        
        # به روزرسانی توصیه‌های هوشمند
        update_recommendations_for_user(user_email)
        
        return True

def list_favorites(user_email:str) -> pd.DataFrame:
    conn=get_conn(); c=conn.cursor()
    c.execute("""
        SELECT p.*, f.notes, f.created_at as fav_date 
        FROM favorites f
        JOIN properties p ON p.id=f.property_id
        WHERE f.user_email=? AND p.status='published'
        ORDER BY f.created_at DESC
    """, (user_email,))
    rows=c.fetchall()
    if not rows:
        conn.close(); return pd.DataFrame()
    cols=[d[0] for d in c.description]; conn.close()
    return pd.DataFrame(rows, columns=cols)

def send_message(pid:int, sender:str, receiver:str, body:str, message_type:str = "text"):
    conn=get_conn(); c=conn.cursor()
    c.execute("INSERT INTO messages(property_id,sender_email,receiver_email,body,created_at,message_type) VALUES(?,?,?,?,?,?)",
              (pid, sender, receiver, body[:1000], now_iso(), message_type))
    conn.commit(); conn.close()
    
    # ارسال نوتیفیکیشن
    add_notification(receiver, "پیام جدید دریافت کردید!", "message", related_id=pid)
    track_user_activity(sender, "send_message", f"Sent message to {receiver} about property {pid}")

def load_chat(pid:int, a:str, b:str) -> List[Dict[str,Any]]:
    conn=get_conn(); c=conn.cursor()
    c.execute("""
        SELECT sender_email, body, created_at, message_type 
        FROM messages
        WHERE property_id=? AND (sender_email IN (?,?) AND receiver_email IN (?,?))
        ORDER BY id ASC
    """, (pid, a, b, a, b))
    rows=c.fetchall(); conn.close()
    return [{"sender":r[0], "body":r[1], "at":r[2], "type":r[3]} for r in rows]

def get_unread_message_count(user_email: str) -> int:
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM messages WHERE receiver_email=? AND is_read=0", (user_email,))
    count = c.fetchone()[0]; conn.close()
    return count

def mark_messages_as_read(property_id: int, user_email: str):
    conn = get_conn(); c = conn.cursor()
    c.execute("""
        UPDATE messages SET is_read=1 
        WHERE property_id=? AND receiver_email=? AND is_read=0
    """, (property_id, user_email))
    conn.commit(); conn.close()

# =========================
# NEW FEATURES - سیستم نوتیفیکیشن پیشرفته
# =========================
def add_notification(user_email: str, message: str, notification_type: str = "info", related_id: int = None):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO notifications (user_email, message, type, related_id, created_at) VALUES (?, ?, ?, ?, ?)",
              (user_email, message, notification_type, related_id, now_iso()))
    conn.commit()
    conn.close()

def get_unread_notifications_count(user_email: str) -> int:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM notifications WHERE user_email=? AND is_read=0", (user_email,))
    count = c.fetchone()[0]
    conn.close()
    return count

def get_notifications(user_email: str, limit: int = 20, unread_only: bool = False) -> pd.DataFrame:
    conn = get_conn()
    c = conn.cursor()
    
    query = """
        SELECT id, message, type, created_at, is_read, related_id 
        FROM notifications 
        WHERE user_email=?
    """
    
    if unread_only:
        query += " AND is_read=0"
        
    query += " ORDER BY id DESC LIMIT ?"
    
    c.execute(query, (user_email, limit))
    rows = c.fetchall()
    conn.close()
    
    if not rows:
        return pd.DataFrame()
    
    return pd.DataFrame(rows, columns=["id", "message", "type", "created_at", "is_read", "related_id"])

def mark_notification_as_read(notification_id: int):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE notifications SET is_read=1 WHERE id=?", (notification_id,))
    conn.commit()
    conn.close()

def mark_all_notifications_as_read(user_email: str):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE notifications SET is_read=1 WHERE user_email=?", (user_email,))
    conn.commit()
    conn.close()

# =========================
# NEW FEATURES - ردیابی فعالیت پیشرفته
# =========================
def track_user_activity(user_email: str, action: str, details: str = "", ip_address: str = None, user_agent: str = None):
    conn = get_conn()
    c = conn.cursor()
    
    if ip_address is None:
        ip_address = get_client_ip()
        
    if user_agent is None:
        user_agent = "Unknown"
    
    c.execute("""
        INSERT INTO user_activity (user_email, action, details, ip_address, user_agent, created_at) 
        VALUES (?, ?, ?, ?, ?, ?)
    """, (user_email, action, details, ip_address, user_agent, now_iso()))
    
    conn.commit()
    conn.close()

def get_user_activity(user_email: str, limit: int = 50) -> pd.DataFrame:
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT action, details, created_at, ip_address 
        FROM user_activity 
        WHERE user_email=? 
        ORDER BY id DESC 
        LIMIT ?
    """, (user_email, limit))
    rows = c.fetchall()
    conn.close()
    
    if not rows:
        return pd.DataFrame()
    
    return pd.DataFrame(rows, columns=["action", "details", "created_at", "ip_address"])

def get_system_activity(limit: int = 100) -> pd.DataFrame:
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT u.name, ua.action, ua.details, ua.created_at, ua.ip_address
        FROM user_activity ua
        JOIN users u ON ua.user_email = u.email
        ORDER BY ua.id DESC 
        LIMIT ?
    """, (limit,))
    rows = c.fetchall()
    conn.close()
    
    if not rows:
        return pd.DataFrame()
    
    return pd.DataFrame(rows, columns=["user", "action", "details", "created_at", "ip_address"])

# =========================
# NEW FEATURES - امتیازدهی کاربران پیشرفته
# =========================
def update_user_rating(user_email: str):
    conn = get_conn()
    c = conn.cursor()
    
    # محاسبه امتیاز جدید بر اساس نظرات دریافت شده
    c.execute("""
        SELECT AVG(rating) 
        FROM comments 
        WHERE property_id IN (SELECT id FROM properties WHERE owner_email = ?)
    """, (user_email,))
    
    new_rating = c.fetchone()[0] or 5.0
    
    # در نظر گرفتن سایر فاکتورها (تعداد معاملات موفق، سرعت پاسخگویی، etc.)
    c.execute("""
        SELECT COUNT(*) 
        FROM transactions 
        WHERE seller_email = ? AND status = 'completed'
    """, (user_email,))
    
    successful_transactions = c.fetchone()[0] or 0
    transaction_bonus = min(successful_transactions * 0.1, 0.5)  # حداکثر 0.5 امتیاز bonus
    
    final_rating = min(5.0, new_rating + transaction_bonus)
    
    c.execute("UPDATE users SET rating=? WHERE email=?", (final_rating, user_email))
    conn.commit()
    conn.close()
    return final_rating

def calculate_user_rating(user_email: str) -> float:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT rating FROM users WHERE email=?", (user_email,))
    rating = c.fetchone()[0] or 5.0
    conn.close()
    return round(rating, 1)

def verify_user(user_email: str, verified: bool = True):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE users SET verified=? WHERE email=?", (1 if verified else 0, user_email))
    conn.commit()
    conn.close()
    
    if verified:
        add_notification(user_email, "حساب کاربری شما تأیید شد!", "success")
    else:
        add_notification(user_email, "تأیید حساب کاربری شما لغو شد.", "warning")

# =========================
# NEW FEATURES - سیستم گزارش‌گیری پیشرفته
# =========================
def generate_property_report(property_id: int) -> Dict[str, Any]:
    conn = get_conn()
    c = conn.cursor()
    
    # آمار بازدیدها
    c.execute("SELECT COUNT(*) FROM property_views WHERE property_id = ?", (property_id,))
    views = c.fetchone()[0]
    
    # تعداد علاقه‌مندی‌ها
    c.execute("SELECT COUNT(*) FROM favorites WHERE property_id = ?", (property_id,))
    favorites = c.fetchone()[0]
    
    # میانگین امتیاز
    c.execute("SELECT AVG(rating) FROM comments WHERE property_id = ?", (property_id,))
    avg_rating = round(c.fetchone()[0] or 0, 1)
    
    # تعداد پیام‌ها
    c.execute("SELECT COUNT(*) FROM messages WHERE property_id = ?", (property_id,))
    messages = c.fetchone()[0]
    
    conn.close()
    
    return {
        "total_views": views,
        "total_favorites": favorites,
        "average_rating": avg_rating,
        "total_messages": messages,
        "performance_score": calculate_performance_score(views, favorites, avg_rating, messages)
    }

def calculate_performance_score(views: int, favorites: int, rating: float, messages: int) -> float:
    # محاسبه امتیاز عملکرد بر اساس معیارهای مختلف
    view_score = min(views / 10, 40)  # حداکثر 40 امتیاز برای بازدید
    favorite_score = min(favorites * 8, 30)  # حداکثر 30 امتیاز برای علاقه‌مندی
    rating_score = rating * 4  # حداکثر 20 امتیاز برای امتیاز (5 * 4)
    message_score = min(messages * 2, 10)  # حداکثر 10 امتیاز برای پیام
    
    return round(view_score + favorite_score + rating_score + message_score, 1)

def generate_user_report(user_email: str) -> Dict[str, Any]:
    conn = get_conn()
    c = conn.cursor()
    
    # تعداد ملک‌های منتشر شده
    c.execute("SELECT COUNT(*) FROM properties WHERE owner_email = ? AND status = 'published'", (user_email,))
    published_properties = c.fetchone()[0]
    
    # تعداد ملک‌های فروخته شده
    c.execute("SELECT COUNT(*) FROM transactions WHERE seller_email = ? AND status = 'completed'", (user_email,))
    sold_properties = c.fetchone()[0]
    
    # میانگین امتیاز
    c.execute("SELECT rating FROM users WHERE email = ?", (user_email,))
    rating = c.fetchone()[0] or 5.0
    
    # تعداد بازدیدهای کل
    c.execute("SELECT SUM(views) FROM properties WHERE owner_email = ?", (user_email,))
    total_views = c.fetchone()[0] or 0
    
    conn.close()
    
    return {
        "published_properties": published_properties,
        "sold_properties": sold_properties,
        "rating": rating,
        "total_views": total_views,
        "success_rate": (sold_properties / published_properties * 100) if published_properties > 0 else 0
    }

# =========================
# NEW FEATURES - سیستم پیشنهادات هوشمند پیشرفته
# =========================
def get_smart_recommendations(user_email: str, limit: int = 5) -> pd.DataFrame:
    conn = get_conn()
    c = conn.cursor()
    
    # بررسی اگر توصیه‌های از پیش محاسبه شده وجود دارد
    c.execute("""
        SELECT p.*, ar.score, ar.reason 
        FROM ai_recommendations ar
        JOIN properties p ON ar.property_id = p.id
        WHERE ar.user_email = ? AND p.status = 'published'
        ORDER BY ar.score DESC
        LIMIT ?
    """, (user_email, limit))
    
    rows = c.fetchall()
    
    if rows:
        cols = [d[0] for d in c.description]
        conn.close()
        return pd.DataFrame(rows, columns=cols)
    
    # اگر توصیه‌ای وجود ندارد، از روش قدیمی استفاده کن
    c.execute("""
        SELECT p.* FROM properties p
        WHERE p.property_type IN (
            SELECT DISTINCT property_type FROM favorites f
            JOIN properties p ON f.property_id = p.id
            WHERE f.user_email = ?
        ) AND p.status = 'published' AND p.owner_email != ?
        ORDER BY p.views DESC, p.created_at DESC
        LIMIT ?
    """, (user_email, user_email, limit))
    
    rows = c.fetchall()
    cols = [d[0] for d in c.description]
    conn.close()
    
    return pd.DataFrame(rows, columns=cols) if rows else pd.DataFrame()

def update_recommendations_for_user(user_email: str):
    # به روزرسانی توصیه‌ها برای یک کاربر خاص
    recommender = PropertyRecommender()
    recommender.update_recommendations_for_user(user_email)

def update_recommendations_for_new_property(property_id: int):
    # به روزرسانی توصیه‌ها برای همه کاربران مرتبط با یک ملک جدید
    conn = get_conn()
    c = conn.cursor()
    
    # دریافت اطلاعات ملک جدید
    c.execute("SELECT property_type, city, price, area FROM properties WHERE id=?", (property_id,))
    prop_info = c.fetchone()
    
    if not prop_info:
        conn.close()
        return
        
    prop_type, city, price, area = prop_info
    
    # پیدا کردن کاربرانی که ممکن است به این ملک علاقه داشته باشند
    c.execute("""
        SELECT DISTINCT user_email 
        FROM favorites f
        JOIN properties p ON f.property_id = p.id
        WHERE p.property_type = ? OR p.city = ?
        OR (p.price BETWEEN ? * 0.7 AND ? * 1.3)
        OR (p.area BETWEEN ? * 0.7 AND ? * 1.3)
    """, (prop_type, city, price, price, area, area))
    
    users = [row[0] for row in c.fetchall()]
    conn.close()
    
    # به روزرسانی توصیه‌ها برای هر کاربر
    for user_email in users:
        update_recommendations_for_user(user_email)

# =========================
# NEW FEATURES - سیستم اشتراک‌گذاری پیشرفته
# =========================
def generate_share_links(property_id: int, base_url: str) -> Dict[str, str]:
    url = f"{base_url.rstrip('/')}/?pg=view&pid={property_id}"
    title = "ملک پیشنهادی در سامانه املاک جرقویه"
    
    return {
        "whatsapp": f"https://wa.me/?text={title}: {url}",
        "telegram": f"https://t.me/share/url?url={url}&text={title}",
        "email": f"mailto:?subject={title}&body=این ملک را بررسی کنید: {url}",
        "twitter": f"https://twitter.com/intent/tweet?text={title}&url={url}",
        "linkedin": f"https://www.linkedin.com/sharing/share-offsite/?url={url}",
        "direct": url,
        "qr_code": f"https://api.qrserver.com/v1/create-qr-code/?size=200x200&data={url}"
    }

def generate_embed_code(property_id: int, base_url: str, width: int = 300, height: int = 250) -> str:
    url = f"{base_url.rstrip('/')}/?pg=view&pid={property_id}"
    embed_url = f"{base_url.rstrip('/')}/embed/property/{property_id}"
    
    return f"""
    <iframe src="{embed_url}" width="{width}" height="{height}" frameborder="0" style="border:1px solid #ddd;">
        <a href="{url}">مشاهده ملک در سامانه املاک جرقویه</a>
    </iframe>
    """

# =========================
# NEW FEATURES - سیستم بک‌آپ پیشرفته
# =========================
def create_backup() -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = f"{BACKUP_DIR}/backup_{timestamp}.db"
    
    # کپی کردن دیتابیس
    with open(DB_NAME, 'rb') as original:
        with open(backup_file, 'wb') as backup:
            backup.write(original.read())
    
    # فشرده سازی بک‌آپ
    try:
        import gzip
        with open(backup_file, 'rb') as f_in:
            with gzip.open(f"{backup_file}.gz", 'wb') as f_out:
                f_out.writelines(f_in)
        os.remove(backup_file)
        backup_file = f"{backup_file}.gz"
    except:
        pass
    
    # ثبت فعالیت
    track_user_activity("system", "backup_created", f"Backup created: {backup_file}")
    
    return backup_file

def restore_backup(backup_file: str) -> bool:
    try:
        # بررسی اگر فایل فشرده است
        if backup_file.endswith('.gz'):
            import gzip
            with gzip.open(backup_file, 'rb') as f_in:
                with open(DB_NAME, 'wb') as f_out:
                    f_out.write(f_in.read())
        else:
            with open(backup_file, 'rb') as backup:
                with open(DB_NAME, 'wb') as original:
                    original.write(backup.read())
        
        # ثبت فعالیت
        track_user_activity("system", "backup_restored", f"Backup restored: {backup_file}")
        return True
    except Exception as e:
        track_user_activity("system", "backup_restore_failed", f"Failed to restore backup: {str(e)}")
        return False

def auto_backup():
    # ایجاد بک‌آپ خودکار در صورت پیکربندی
    try:
        backup_config = st.secrets.get("backup", {})
        if backup_config.get("auto_backup", False):
            # فقط در زمان‌های مشخص بک‌آپ بگیر
            now = datetime.now()
            if now.hour == backup_config.get("backup_hour", 2):  # پیش‌فرض 2 بامداد
                backup_file = create_backup()
                
                # ارسال ایمیل در صورت پیکربندی
                if backup_config.get("email_notification", False):
                    subject = "بک‌آپ خودکار سامانه املاک جرقویه"
                    body = f"""
                    <div dir="rtl">
                        <h2>بک‌آپ خودکار ایجاد شد</h2>
                        <p>بک‌آپ خودکار سامانه در تاریخ {get_persian_date()} ایجاد شد.</p>
                        <p><strong>نام فایل:</strong> {backup_file}</p>
                        <p>با تشکر<br>سیستم بک‌آپ خودکار</p>
                    </div>
                    """
                    send_email(backup_config.get("notification_email", ""), subject, body, True)
    except:
        pass

# =========================
# NEW FEATURES - سیستم عضویت و اطلاع‌رسانی پیشرفته
# =========================
def create_search_subscription(user_email: str, filters: Dict[str, Any], frequency: str = "instant"):
    conn = get_conn()
    c = conn.cursor()
    
    # بررسی اگر اشتراک مشابه وجود دارد
    c.execute("SELECT id FROM subscriptions WHERE user_email=? AND search_filters=?", 
              (user_email, json.dumps(filters)))
    
    if c.fetchone():
        # به روزرسانی اشتراک موجود
        c.execute("UPDATE subscriptions SET is_active=1, frequency=?, updated_at=? WHERE user_email=? AND search_filters=?",
                  (frequency, now_iso(), user_email, json.dumps(filters)))
    else:
        # ایجاد اشتراک جدید
        c.execute("INSERT INTO subscriptions (user_email, search_filters, frequency, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                  (user_email, json.dumps(filters), frequency, now_iso(), now_iso()))
    
    conn.commit()
    conn.close()
    
    add_notification(user_email, "اشتراک جستجوی جدید شما ایجاد شد! هنگام پیدا شدن ملک جدید به شما اطلاع می‌دهیم.", "subscription")

def check_subscriptions(new_property: Dict[str, Any]):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT user_email, search_filters FROM subscriptions WHERE is_active=1")
    subscriptions = c.fetchall()
    conn.close()
    
    for user_email, filters_json in subscriptions:
        filters = json.loads(filters_json)
        matches = True
        
        # بررسی تطابق فیلترها
        if filters.get("city") and new_property["city"] not in filters["city"]:
            matches = False
        
        if filters.get("property_type") and new_property["property_type"] not in filters["property_type"]:
            matches = False
        
        if matches and filters.get("min_price") and new_property["price"] < filters["min_price"]:
            matches = False
            
        if matches and filters.get("max_price") and new_property["price"] > filters["max_price"]:
            matches = False
            
        if matches and filters.get("min_area") and new_property["area"] < filters["min_area"]:
            matches = False
            
        if matches and filters.get("max_area") and new_property["area"] > filters["max_area"]:
            matches = False
        
        if matches:
            add_notification(user_email, f"ملک جدیدی مطابق با جستجوی شما پیدا شد: {new_property['title']}", "match", related_id=new_property["id"])
            
            # ارسال ایمیل در صورت نیاز
            send_property_match_email(user_email, new_property['title'], new_property['id'])

def send_subscription_digests():
    # ارسال خلاصه روزانه/هفتگی برای اشتراک‌ها
    conn = get_conn()
    c = conn.cursor()
    
    # پیدا کردن کاربرانی که اشتراک غیر فوری دارند
    c.execute("""
        SELECT DISTINCT user_email, frequency 
        FROM subscriptions 
        WHERE is_active=1 AND frequency != 'instant'
    """)
    
    users = c.fetchall()
    
    for user_email, frequency in users:
        # بررسی اگر زمان ارسال خلاصه رسیده است
        c.execute("SELECT MAX(updated_at) FROM subscriptions WHERE user_email=?", (user_email,))
        last_update = c.fetchone()[0]
        
        if not last_update:
            continue
            
        last_update_date = datetime.fromisoformat(last_update)
        now = datetime.now()
        
        # بررسی بر اساس فرکانس
        send_digest = False
        if frequency == "daily" and (now - last_update_date).days >= 1:
            send_digest = True
        elif frequency == "weekly" and (now - last_update_date).days >= 7:
            send_digest = True
            
        if send_digest:
            # ایجاد و ارسال خلاصه
            create_and_send_digest(user_email, frequency)
            
            # به روزرسانی زمان اشتراک
            c.execute("UPDATE subscriptions SET updated_at=? WHERE user_email=?", (now_iso(), user_email))
    
    conn.commit()
    conn.close()

def create_and_send_digest(user_email: str, frequency: str):
    # ایجاد خلاصه املاک جدید برای کاربر
    conn = get_conn()
    c = conn.cursor()
    
    # دریافت آخرین زمان ارسال خلاصه
    c.execute("SELECT MAX(updated_at) FROM subscriptions WHERE user_email=?", (user_email,))
    last_update = c.fetchone()[0]
    
    if not last_update:
        conn.close()
        return
        
    # دریافت ملک‌های جدید از آخرین به روزرسانی
    c.execute("""
        SELECT p.* FROM properties p
        WHERE p.status='published' AND p.created_at > ?
        ORDER BY p.created_at DESC
        LIMIT 10
    """, (last_update,))
    
    new_properties = c.fetchall()
    cols = [d[0] for d in c.description]
    conn.close()
    
    if not new_properties:
        return
        
    # ایجاد محتوای ایمیل
    subject = f"خلاصه {frequency} املاک جدید در جرقویه"
    
    properties_html = ""
    for prop in new_properties:
        prop_dict = dict(zip(cols, prop))
        properties_html += f"""
        <div style="border:1px solid #ddd; padding:10px; margin:10px 0; border-radius:5px;">
            <h3>{prop_dict['title']}</h3>
            <p>قیمت: {format_price(prop_dict['price'])} | شهر: {prop_dict['city']} | نوع: {prop_dict['property_type']}</p>
            <p>{prop_dict.get('description', '')[:100]}...</p>
            <a href="{st.secrets['app']['base_url']}/?pg=view&pid={prop_dict['id']}" 
               style="background:#8B3A3A; color:white; padding:5px 10px; text-decoration:none; border-radius:3px;">
                مشاهده ملک
            </a>
        </div>
        """
    
    body = f"""
    <div dir="rtl">
        <h2>خلاصه املاک جدید</h2>
        <p>بر اساس جستجوهای ذخیره شده شما، {len(new_properties)} ملک جدید پیدا شده است:</p>
        {properties_html}
        <p>با تشکر<br>تیم پشتیبانی املاک جرقویه</p>
    </div>
    """
    
    # ارسال ایمیل
    send_email(user_email, subject, body, True)

# =========================
# NEW FEATURES - افزایش بازدید ملک پیشرفته
# =========================
def increment_property_views(property_id: int, user_email: str = None):
    conn = get_conn()
    c = conn.cursor()
    
    # افزایش شمارنده بازدیدها
    c.execute("UPDATE properties SET views = views + 1 WHERE id = ?", (property_id,))
    
    # ثبت اطلاعات بازدید
    ip_address = get_client_ip()
    user_agent = "Unknown"  # در حالت واقعی از request headers می‌گیریم
    
    c.execute("INSERT INTO property_views (property_id, user_agent, ip_address, user_email, created_at) VALUES (?, ?, ?, ?, ?)",
              (property_id, user_agent, ip_address, user_email, now_iso()))
    
    conn.commit()
    conn.close()

def get_property_analytics(property_id: int, period: str = "7d") -> Dict[str, Any]:
    # دریافت آمار بازدیدهای یک ملک
    conn = get_conn()
    c = conn.cursor()
    
    # محاسبه تاریخ شروع بر اساس دوره
    now = datetime.now()
    if period == "1d":
        start_date = now - timedelta(days=1)
    elif period == "7d":
        start_date = now - timedelta(days=7)
    elif period == "30d":
        start_date = now - timedelta(days=30)
    else:
        start_date = now - timedelta(days=7)  # پیش‌فرض
    
    # تعداد بازدیدها در دوره
    c.execute("SELECT COUNT(*) FROM property_views WHERE property_id=? AND created_at >= ?", 
              (property_id, start_date.isoformat()))
    views_in_period = c.fetchone()[0]
    
    # تعداد بازدیدهای کل
    c.execute("SELECT COUNT(*) FROM property_views WHERE property_id=?", (property_id,))
    total_views = c.fetchone()[0]
    
    # بازدیدها به تفکیک روز
    c.execute("""
        SELECT DATE(created_at) as day, COUNT(*) as count 
        FROM property_views 
        WHERE property_id=? AND created_at >= ?
        GROUP BY DATE(created_at)
        ORDER BY day
    """, (property_id, start_date.isoformat()))
    
    daily_views = c.fetchall()
    
    conn.close()
    
    return {
        "views_in_period": views_in_period,
        "total_views": total_views,
        "daily_views": daily_views
    }

# =========================
# NEW FEATURES - سیستم گزارش تخلف
# =========================
def report_item(reporter_email: str, item_type: str, item_id: int, reason: str):
    conn = get_conn()
    c = conn.cursor()
    
    c.execute("""
        INSERT INTO reports (reporter_email, reported_item_type, reported_item_id, reason, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (reporter_email, item_type, item_id, reason, now_iso()))
    
    conn.commit()
    conn.close()
    
    # اطلاع به ادمین‌ها
    notify_admins(f"گزارش تخلف جدید برای {item_type} با شناسه {item_id}", "warning")

def get_pending_reports() -> pd.DataFrame:
    conn = get_conn()
    c = conn.cursor()
    
    c.execute("""
        SELECT r.id, r.reporter_email, r.reported_item_type, r.reported_item_id, r.reason, r.created_at, u.name as reporter_name
        FROM reports r
        JOIN users u ON r.reporter_email = u.email
        WHERE r.status = 'pending'
        ORDER BY r.created_at DESC
    """)
    
    rows = c.fetchall()
    conn.close()
    
    if not rows:
        return pd.DataFrame()
    
    return pd.DataFrame(rows, columns=["id", "reporter_email", "reported_item_type", "reported_item_id", "reason", "created_at", "reporter_name"])

def resolve_report(report_id: int, resolved_by: str, resolution: str):
    conn = get_conn()
    c = conn.cursor()
    
    c.execute("""
        UPDATE reports 
        SET status='resolved', resolved_at=?, resolved_by=?
        WHERE id=?
    """, (now_iso(), resolved_by, report_id))
    
    conn.commit()
    conn.close()

# =========================
# NEW FEATURES - سیستم معاملات
# =========================
def create_transaction(property_id: int, buyer_email: str, seller_email: str, price: int):
    conn = get_conn()
    c = conn.cursor()
    
    c.execute("""
        INSERT INTO transactions (property_id, buyer_email, seller_email, price, status, created_at)
        VALUES (?, ?, ?, ?, 'pending', ?)
    """, (property_id, buyer_email, seller_email, price, now_iso()))
    
    transaction_id = c.lastrowid
    
    conn.commit()
    conn.close()
    
    # ارسال نوتیفیکیشن به فروشنده
    add_notification(seller_email, f"درخواست خرید جدید برای ملک شما دریافت شد!", "success", related_id=property_id)
    
    return transaction_id

def update_transaction_status(transaction_id: int, status: str):
    conn = get_conn()
    c = conn.cursor()
    
    c.execute("SELECT property_id, buyer_email, seller_email FROM transactions WHERE id=?", (transaction_id,))
    transaction = c.fetchone()
    
    if not transaction:
        conn.close()
        return False
        
    property_id, buyer_email, seller_email = transaction
    
    c.execute("UPDATE transactions SET status=?, transaction_date=? WHERE id=?", 
              (status, now_iso() if status == 'completed' else None, transaction_id))
    
    if status == 'completed':
        # تغییر وضعیت ملک به فروخته شده
        c.execute("UPDATE properties SET status='sold' WHERE id=?", (property_id,))
        
        # ارسال نوتیفیکیشن به خریدار و فروشنده
        add_notification(buyer_email, "خرید شما با موفقیت تکمیل شد!", "success", related_id=property_id)
        add_notification(seller_email, "فروش ملک شما با موفقیت تکمیل شد!", "success", related_id=property_id)
        
        # به روزرسانی امتیاز فروشنده
        update_user_rating(seller_email)
    
    conn.commit()
    conn.close()
    return True

def get_user_transactions(user_email: str) -> pd.DataFrame:
    conn = get_conn()
    c = conn.cursor()
    
    c.execute("""
        SELECT t.*, p.title as property_title 
        FROM transactions t
        JOIN properties p ON t.property_id = p.id
        WHERE t.buyer_email = ? OR t.seller_email = ?
        ORDER BY t.created_at DESC
    """, (user_email, user_email))
    
    rows = c.fetchall()
    conn.close()
    
    if not rows:
        return pd.DataFrame()
    
    return pd.DataFrame(rows, columns=[d[0] for d in c.description])

# =========================
# NEW FEATURES - سیستم اطلاع‌رسانی به ادمین‌ها
# =========================
def notify_admins(message: str, notification_type: str = "info"):
    conn = get_conn()
    c = conn.cursor()
    
    c.execute("SELECT email FROM users WHERE role='admin'")
    admins = [row[0] for row in c.fetchall()]
    
    for admin_email in admins:
        add_notification(admin_email, message, notification_type)
    
    conn.close()

# =========================
# UI: STYLE - طراحی سنتی و ایرانی پیشرفته
# =========================
def custom_style():
    st.markdown("""
    <style>
      :root {
        --prim: #8B3A3A;      /* قرمز ایرانی */
        --prim-dark: #6f2e2e;
        --gold: #C5A572;      /* طلایی */
        --cream: #FBF5E6;     /* کرم */
        --turquoise: #40E0D0; /* فیروزه‌ای */
        --ink: #2e2e2e;
        --pattern-bg: #f8f3e6;
      }
      
      html, body, [class*="css"] { 
        font-family: Vazirmatn, Tahoma, sans-serif; 
        background: var(--cream); 
        color: var(--ink); 
      }
      
      .stApp { 
        background: linear-gradient(180deg, #fffaf1, #f9f1df 180px, #fffaf1);
        background-image: url("data:image/svg+xml,%3Csvg width='100' height='100' viewBox='0 0 100 100' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M50 50L0 25L50 0L100 25L50 50Z' fill='%23c5a57222'/%3E%3C/svg%3E");
        background-size: 300px;
      }
      
      .stButton > button { 
        background: var(--prim); 
        color: #fff; 
        border-radius: 12px; 
        padding: 12px 24px; 
        font-weight: 700;
        border: 2px solid var(--gold);
        box-shadow: 0 4px 8px rgba(139, 58, 58, 0.2);
        transition: all 0.3s ease;
      }
      
      .stButton > button:hover {
        background: var(--prim-dark);
        transform: translateY(-2px);
        box-shadow: 0 6px 12px rgba(139, 58, 58, 0.3);
      }
      
      .stTextInput > div > input, 
      .stNumberInput > div > div > input, 
      textarea, 
      select { 
        border: 2px solid var(--gold) !important; 
        border-radius: 12px !important; 
        background: #fffaf6 !important; 
        box-shadow: inset 0 2px 4px rgba(197, 165, 114, 0.1);
      }
      
      .card { 
        background: #fff; 
        border: 2px solid #eadfc7; 
        border-radius: 20px; 
        padding: 20px; 
        margin: 15px 0; 
        box-shadow: 0 8px 30px rgba(197, 165, 114, 0.15);
        position: relative;
        overflow: hidden;
      }
      
      .card::before {
        content: "";
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        height: 4px;
        background: linear-gradient(90deg, var(--prim), var(--gold));
        border-radius: 10px 10px 0 0;
      }
      
      .pill { 
        display: inline-block;
        background: linear-gradient(145deg, var(--cream), #fff);
        border: 1px solid var(--gold); 
        padding: 8px 16px;
        border-radius: 20px;
        margin: 4px 8px;
        font-size: 14px;
        box-shadow: 0 2px 4px rgba(197, 165, 114, 0.1);
      }
      
      .traditional-header {
        background: linear-gradient(135deg, var(--prim), var(--prim-dark));
        color: white;
        padding: 20px;
        border-radius: 0 0 20px 20px;
        text-align: center;
        box-shadow: 0 4px 20px rgba(139, 58, 58, 0.3);
        margin-bottom: 30px;
        position: relative;
        overflow: hidden;
      }
      
      .traditional-header::before {
        content: "";
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background-image: url("data:image/svg+xml,%3Csvg width='60' height='60' viewBox='0 0 60 60' xmlns='http://www.w3.org/2000/svg'%3E%3Cg fill='none' fill-rule='evenodd'%3E%3Cg fill='%23ffffff' fill-opacity='0.1'%3E%3Cpath d='M36 34v-4h-2v4h-4v2h4v4h2v-4h4v-2h-4zm0-30V0h-2v4h-4v2h4v4h2V6h4V4h-4zM6 34v-4H4v4H0v2h4v4h2v-4h4v-2H6zM6 4V0H4v4H0v2h4v4h2V6h4V4H6z'/%3E%3C/g%3E%3C/g%3E%3C/svg%3E");
        opacity: 0.1;
      }
      
      .persian-pattern {
        background-color: var(--pattern-bg);
        background-image: url("data:image/svg+xml,%3Csvg width='52' height='26' viewBox='0 0 52 26' xmlns='http://www.w3.org/2000/svg'%3E%3Cg fill='none' fill-rule='evenodd'%3E%3Cg fill='%23c5a572' fill-opacity='0.1'%3E%3Cpath d='M10 10c0-2.21-1.79-4-4-4-3.314 0-6-2.686-6-6h2c0 2.21 1.79 4 4 4 3.314 0 6 2.686 6 6 0 2.21 1.79 4 4 4 3.314 0 6 2.686 6 6 0 2.21 1.79 4 4 4v2c-3.314 0-6-2.686-6-6 0-2.21-1.79-4-4-4-3.314 0-6-2.686-6-6zm25.464-1.95l8.486 8.486-1.414 1.414-8.486-8.486 1.414-1.414z' /%3E%3C/g%3E%3C/g%3E%3C/svg%3E");
        padding: 20px;
        border-radius: 15px;
        border: 2px solid rgba(197, 165, 114, 0.3);
        margin: 10px 0;
      }
      
      .sidebar .sidebar-content {
        background: linear-gradient(180deg, #f8f3e6, #f1e8d5);
        border-right: 3px solid var(--gold);
      }
      
      .traditional-tab {
        background: linear-gradient(145deg, #fff, var(--cream));
        border: 2px solid var(--gold);
        border-radius: 15px;
        padding: 15px;
        margin: 10px 0;
        box-shadow: 0 4px 15px rgba(197, 165, 114, 0.1);
      }
      
      .iranian-border {
        border: 3px solid var(--gold);
        border-radius: 20px;
        padding: 20px;
        background: #fffaf6;
        box-shadow: 0 8px 25px rgba(197, 165, 114, 0.15);
        position: relative;
        overflow: hidden;
      }
      
      .iranian-border::before {
        content: "";
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        height: 5px;
        background: linear-gradient(90deg, var(--prim), var(--gold), var(--turquoise));
      }
      
      .islamic-pattern {
        background: 
          radial-gradient(circle at 10% 20%, rgba(197, 165, 114, 0.1) 0%, transparent 20%),
          radial-gradient(circle at 90% 80%, rgba(64, 224, 208, 0.1) 0%, transparent 20%),
          radial-gradient(circle at 50% 50%, rgba(139, 58, 58, 0.1) 0%, transparent 30%);
        background-color: #fdf8f0;
        padding: 25px;
        border-radius: 20px;
        border: 2px dashed var(--gold);
      }
      
      .yellow-line {
        height: 5px;
        background: linear-gradient(90deg, #ffd700, #ffed4e, #ffd700);
        margin: 0 0 20px 0;
        border-radius: 3px;
        box-shadow: 0 2px 8px rgba(255, 215, 0, 0.3);
      }
      
      .badge-premium {
        background: linear-gradient(145deg, #ffd700, #ffed4e);
        color: #8B3A3A;
        font-weight: bold;
        padding: 4px 8px;
        border-radius: 12px;
        font-size: 12px;
        margin: 0 5px;
      }
      
      .badge-verified {
        background: linear-gradient(145deg, #40E0D0, #20B2AA);
        color: white;
        font-weight: bold;
        padding: 4px 8px;
        border-radius: 12px;
        font-size: 12px;
        margin: 0 5px;
      }
      
      .animation-pulse {
        animation: pulse 2s infinite;
      }
      
      @keyframes pulse {
        0% { transform: scale(1); }
        50% { transform: scale(1.05); }
        100% { transform: scale(1); }
      }
      
      .featured-card {
        border: 3px solid #ffd700 !important;
        box-shadow: 0 8px 35px rgba(255, 215, 0, 0.3) !important;
      }
      
      .featured-card::before {
        background: linear-gradient(90deg, #ffd700, #ffed4e, #ffd700) !important;
      }
      
      @media (max-width: 768px){
        .stButton>button{ width:100%; }
        .card{ padding:15px; }
      }
    </style>
    """, unsafe_allow_html=True)

# =========================
# UI: AUTH PAGES - با طراحی سنتی پیشرفته
# =========================
def signup_page():
    st.markdown("<div class='iranian-border'>", unsafe_allow_html=True)
    st.markdown("<div class='persian-pattern' style='text-align: center;'>", unsafe_allow_html=True)
    st.subheader("📝 ثبت‌نام در سامانه املاک شهرستان جرقویه")
    st.markdown("</div>", unsafe_allow_html=True)
    
    col1, col2 = st.columns(2)
    name = col1.text_input("👤 نام کامل")
    email = col2.text_input("📧 ایمیل")
    phone = col1.text_input("📞 شماره تماس (اختیاری)")
    password = col2.text_input("🔒 رمز عبور (حداقل ۸ کاراکتر شامل حروف بزرگ، کوچک، عدد و کاراکتر خاص)", type="password")
    bio = st.text_area("📝 بیوگرافی (اختیاری)", help="در مورد خودتان و زمینه فعالیت در املاک توضیح دهید")
    
    if st.button("✨ ایجاد حساب کاربری", use_container_width=True):
        if not name or not valid_email(email) or not strong_password(password) or not valid_phone(phone):
            st.error("لطفاً نام، ایمیل معتبر، رمز قوی (حداقل ۸ کاراکتر شامل حروف بزرگ، کوچک، عدد و کاراکتر خاص) و شماره صحیح وارد کنید.")
        else:
            ok = register_user(name, email, password, role="public", phone=phone, bio=bio)
            if ok: 
                st.success("✅ ثبت‌نام موفق. حالا وارد شوید.")
                st.balloons()
            else: 
                st.error("❌ این ایمیل قبلاً ثبت شده یا ورودی نامعتبر است.")
    st.markdown("</div>", unsafe_allow_html=True)

def login_page():
    st.markdown("<div class='iranian-border'>", unsafe_allow_html=True)
    st.markdown("<div class='persian-pattern' style='text-align: center;'>", unsafe_allow_html=True)
    st.subheader("🔐 ورود به سامانه")
    st.markdown("</div>", unsafe_allow_html=True)
    
    email = st.text_input("📧 ایمیل")
    password = st.text_input("🔒 رمز عبور", type="password")
    
    colA, colB = st.columns(2)
    if colA.button("🚪 ورود به سیستم", use_container_width=True):
        u = login_user(email, password)
        if u:
            st.session_state["user"] = u
            st.success(f"🌹 خوش آمدی {u['name']}")
            st.experimental_rerun()
        else:
            st.error("❌ ایمیل یا رمز عبور اشتباه است.")
    
    if colB.button("🔑 فراموشی رمز عبور", use_container_width=True):
        st.session_state["show_reset"] = True
    
    if st.session_state.get("show_reset"):
        st.markdown("<div class='traditional-tab'>", unsafe_allow_html=True)
        st.info("🔐 رمز جدید را تنظیم کنید")
        e = st.text_input("📧 ایمیل ثبت‌شده", key="rp_e")
        npw = st.text_input("🔒 رمز جدید", type="password", key="rp_p")
        if st.button("🔄 تغییر رمز عبور", use_container_width=True):
            if reset_password(e, npw):
                st.success("✅ رمز تغییر کرد. وارد شوید.")
                st.session_state["show_reset"] = False
            else:
                st.error("❌ ایمیل یا رمز معتبر نیست.")
        st.markdown("</div>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

# =========================
# UI: SEARCH / FILTERS - با طراحی سنتی پیشرفته
# =========================
@st.cache_data(ttl=3600)
def list_all(colname:str) -> List[str]:
    conn=get_conn(); c=conn.cursor()
    try:
        c.execute(f"SELECT DISTINCT {colname} FROM properties WHERE status='published' AND {colname} IS NOT NULL")
        vals = sorted({r[0] for r in c.fetchall() if r[0]})
    except Exception:
        vals=[]
    conn.close(); return vals

def property_filters():
    st.markdown("<div class='iranian-border'>", unsafe_allow_html=True)
    st.markdown("<div class='persian-pattern' style='text-align: center;'>", unsafe_allow_html=True)
    st.markdown("### 🔍 فیلتر دقیق جستجو")
    st.markdown("</div>", unsafe_allow_html=True)
    
    cities = st.multiselect("🏙️ شهر", options=list_all("city"))
    types  = st.multiselect("🏠 نوع ملک", options=list_all("property_type"))
    
    c1, c2 = st.columns(2)
    min_price = c1.number_input("💰 حداقل قیمت (تومان)", min_value=0, step=100000, value=0)
    max_price = c2.number_input("💰 حداکثر قیمت (تومان)", min_value=0, step=100000, value=0)
    
    a1, a2 = st.columns(2)
    min_area = a1.number_input("📏 حداقل متراژ", min_value=0, step=1, value=0)
    max_area = a2.number_input("📏 حداکثر متراژ", min_value=0, step=1, value=0)
    
    r1, r2 = st.columns(2)
    min_rooms = r1.number_input("🚪 حداقل اتاق", min_value=0, step=1, value=0)
    max_rooms = r2.number_input("🚪 حداکثر اتاق", min_value=0, step=1, value=0)
    
    g1, g2 = st.columns(2)
    min_age = g1.number_input("🏚️ حداقل سن بنا", min_value=0, step=1, value=0)
    max_age = g2.number_input("🏚️ حداکثر سن بنا", min_value=0, step=1, value=0)
    
    facilities = st.multiselect("⭐ امکانات (شامل شود)", ["آسانسور","پارکینگ","انباری","بالکن","استخر","سونا","روف‌گاردن","کمد دیواری"])
    
    st.markdown("<div class='traditional-tab'>", unsafe_allow_html=True)
    st.markdown("#### 🗺️ جستجو بر اساس شعاع مکانی (اختیاری)")
    d1, d2, d3 = st.columns(3)
    center_lat = d1.number_input("📍 عرض جغرافیایی مرکز", format="%.6f")
    center_lon = d2.number_input("📍 طول جغرافیایی مرکز", format="%.6f")
    radius_km  = d3.number_input("📐 شعاع (کیلومتر)", min_value=0, step=1)
    st.markdown("</div>", unsafe_allow_html=True)
    
    # فیلترهای پیشرفته
    st.markdown("<div class='traditional-tab'>", unsafe_allow_html=True)
    st.markdown("#### ⚡ فیلترهای پیشرفته")
    adv1, adv2, adv3 = st.columns(3)
    featured_only = adv1.checkbox("فقط املاک ویژه")
    verified_only = adv2.checkbox("فقط مالکین تأیید شده")
    has_images = adv3.checkbox("فقط دارای تصویر")
    st.markdown("</div>", unsafe_allow_html=True)
    
    # دکمه ذخیره جستجو
    if st.session_state.get("user"):
        col_save, col_freq = st.columns(2)
        if col_save.button("💾 ذخیره این جستجو", use_container_width=True):
            filters = {
                "city": cities or None,
                "property_type": types or None,
                "min_price": min_price or None,
                "max_price": max_price if max_price>0 else None,
                "min_area": min_area or None,
                "max_area": max_area if max_area>0 else None,
                "min_rooms": min_rooms or None,
                "max_rooms": max_rooms if max_rooms>0 else None,
                "min_age": min_age or None,
                "max_age": max_age if max_age>0 else None,
                "facilities": facilities or None,
                "featured_only": featured_only,
                "verified_only": verified_only,
                "has_images": has_images
            }
            
            frequency = col_freq.selectbox("فرکانس اطلاع‌رسانی", ["instant", "daily", "weekly"])
            create_search_subscription(st.session_state["user"]["email"], filters, frequency)
            st.success("✅ جستجوی شما ذخیره شد! هنگام پیدا شدن ملک جدید به شما اطلاع می‌دهیم.")
    
    st.markdown("</div>", unsafe_allow_html=True)
    
    return {
        "city": cities or None,
        "property_type": types or None,
        "min_price": min_price or None,
        "max_price": max_price if max_price>0 else None,
        "min_area": min_area or None,
        "max_area": max_area if max_area>0 else None,
        "min_rooms": min_rooms or None,
        "max_rooms": max_rooms if max_rooms>0 else None,
        "min_age": min_age or None,
        "max_age": max_age if max_age>0 else None,
        "facilities": facilities or None,
        "center_lat": center_lat if center_lat else None,
        "center_lon": center_lon if center_lon else None,
        "radius_km": radius_km if radius_km else None,
        "featured_only": featured_only,
        "verified_only": verified_only,
        "has_images": has_images
    }

# =========================
# UI: COMPONENTS - با طراحی سنتی پیشرفته
# =========================
def property_card(row: pd.Series, user: Optional[Dict[str,Any]]):
    card_class = "card featured-card" if row.get('featured') else "card"
    
    with st.container():
        st.markdown(f"<div class='{card_class}'>", unsafe_allow_html=True)
        
        # هدر کارت
        col_title, col_price = st.columns([2, 1])
        col_title.markdown(f"#### {row['title']}")
        col_price.markdown(f"### {format_price(row['price'])}")
        
        # اطلاعات مالک
        if row.get('owner_verified'):
            col_title.markdown("<span class='badge-verified'>✅ تأیید شده</span>", unsafe_allow_html=True)
        
        if row.get('featured'):
            col_price.markdown("<span class='badge-premium'>⭐ ویژه</span>", unsafe_allow_html=True)
        
        # اطلاعات پایه
        st.markdown("<div style='display: flex; flex-wrap: wrap; margin: 10px 0;'>", unsafe_allow_html=True)
        badge(f"🏠 {row['property_type']}")
        badge(f"🏙️ {row['city']}")
        badge(f"📏 {int(row['area'])} متر")
        if row.get('rooms'): badge(f"🚪 {int(row['rooms'])} اتاق")
        if row.get('building_age'): badge(f"🏚️ {int(row['building_age'])} سال")
        if row.get('views'): badge(f"👀 {int(row['views'])} بازدید")
        if row.get('owner_rating'): badge(f"⭐ {float(row['owner_rating']):.1f}")
        st.markdown("</div>", unsafe_allow_html=True)
        
        if row.get("address"):
            st.caption(f"📍 {row['address']}")
        
        if row.get("description"):
            st.markdown(f"<div style='background:#f8f5ee;padding:15px;border-radius:12px;border-right:3px solid var(--gold);margin:10px 0;font-size:14px;line-height:1.6'>{row['description'][:200]}{'...' if len(row['description']) > 200 else ''}</div>", unsafe_allow_html=True)
        
        # نمایش تصویر
        imgs = property_images(int(row["id"]))
        if imgs:
            try:
                st.image(io.BytesIO(imgs[0]), use_column_width=True, caption="تصویر اصلی ملک")
            except Exception:
                try:
                    st.image(base64.b64decode(imgs[0]), use_column_width=True, caption="تصویر اصلی ملک")
                except Exception:
                    pass
        
        # دکمه‌های تعاملی
        cols = st.columns(5)
        if user:
            if cols[0].button("❤️ علاقه‌مندی", key=f"fav_{row['id']}", use_container_width=True):
                _ = toggle_fav(int(row['id']), user["email"])
                st.success("✅ به علاقه‌مندی‌ها اضافه/حذف شد.")
        
        if row.get("video_url"):
            cols[1].markdown(f"[🎥 تور ویدئویی]({row['video_url']})")
        
        if cols[2].button("🗺️ نمایش روی نقشه", key=f"map_{row['id']}", use_container_width=True):
            st.map(pd.DataFrame([[row["latitude"],row["longitude"]]], columns=["lat","lon"]))
        
        if cols[3].button("📄 جزئیات", key=f"view_{row['id']}", use_container_width=True):
            st.query_params["pg"] = "view"
            st.query_params["pid"] = int(row['id'])
            st.rerun()
        
        if user and user["email"] != row["owner_email"]:
            if cols[4].button("💬 گفتگو", key=f"chat_{row['id']}", use_container_width=True):
                st.session_state["chat_pid"]=int(row['id']); st.rerun()
        
        st.markdown("</div>", unsafe_allow_html=True)

def image_files_to_bytes(uploaded_files)->List[bytes]:
    out = []
    for f in uploaded_files[:MAX_UPLOAD_IMAGES]:
        if f.type not in ALLOWED_IMAGE_TYPES:
            st.warning(f"فرمت نامجاز: {f.name}")
            continue
        size_mb = (getattr(f, "size", None) or 0) / (1024*1024)
        if size_mb > MAX_IMAGE_SIZE_MB:
            st.warning(f"حجم زیاد: {f.name} (حداکثر {MAX_IMAGE_SIZE_MB}MB)")
            continue
        out.append(f.read())
    return out

def paginator(df: pd.DataFrame, page_size:int=8, key:str="pg")->pd.DataFrame:
    if df.empty: return df
    total = len(df)
    pages = (total + page_size - 1)//page_size
    col1,col2 = st.columns([3,2])
    with col1:
        st.caption(f"نتایج: {total} | صفحات: {pages}")
    with col2:
        p = st.number_input("صفحه", min_value=1, max_value=max(pages,1), value=1, step=1, key=key)
    start = (p-1)*page_size
    end = start+page_size
    return df.iloc[start:end]

# =========================
# UI: PANELS - با طراحی سنتی پیشرفته
# =========================
def public_panel(user: Dict[str,Any]):
    st.markdown("<div class='traditional-header'>", unsafe_allow_html=True)
    st.subheader(f"🌺 خوش آمدی {user['name']}")
    if user.get('verified'):
        st.markdown("<span class='badge-verified'>✅ حساب تأیید شده</span>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)
    
    # نمایش نوتیفیکیشن‌ها
    notification_count = get_unread_notifications_count(user["email"])
    unread_messages = get_unread_message_count(user["email"])
    
    if notification_count > 0 or unread_messages > 0:
        st.markdown("<div class='persian-pattern' style='text-align: center;'>", unsafe_allow_html=True)
        cols = st.columns(2)
        cols[0].markdown(f"### 🔔 {notification_count} نوتیفیکیشن")
        cols[1].markdown(f"### 📧 {unread_messages} پیام جدید")
        
        if st.button("مشاهده همه اعلان‌ها", use_container_width=True):
            st.session_state["show_notifications"] = True
        st.markdown("</div>", unsafe_allow_html=True)
    
    if st.session_state.get("show_notifications"):
        st.markdown("<div class='iranian-border'>", unsafe_allow_html=True)
        st.subheader("📋 اعلان‌ها و پیام‌ها")
        
        tab1, tab2 = st.tabs(["📋 نوتیفیکیشن‌ها", "📧 پیام‌ها"])
        
        with tab1:
            notifications = get_notifications(user["email"], 20, True)
            if not notifications.empty:
                for _, notif in notifications.iterrows():
                    emoji = "💬" if notif["type"] == "comment" else "❤️" if notif["type"] == "favorite" else "📧" if notif["type"] == "message" else "ℹ️"
                    col1, col2 = st.columns([4, 1])
                    col1.markdown(f"{emoji} **{notif['message']}** - _{notif['created_at']}_")
                    if col2.button("خواندم", key=f"read_{notif['id']}", use_container_width=True):
                        mark_notification_as_read(notif['id'])
                        st.rerun()
            else:
                st.info("ℹ️ هیچ نوتیفیکیشن خوانده نشده‌ای ندارید.")
        
        with tab2:
            # نمایش پیام‌های خوانده نشده
            conn = get_conn(); c = conn.cursor()
            c.execute("""
                SELECT DISTINCT property_id, sender_email 
                FROM messages 
                WHERE receiver_email=? AND is_read=0
            """, (user["email"],))
            unread_conversations = c.fetchall()
            conn.close()
            
            if unread_conversations:
                for pid, sender in unread_conversations:
                    if st.button(f"📧 پیام جدید از {sender} درباره ملک {pid}", key=f"msg_{pid}_{sender}"):
                        st.session_state["chat_pid"] = pid
                        st.rerun()
            else:
                st.info("ℹ️ هیچ پیام خوانده نشده‌ای ندارید.")
        
        if st.button("بستن اعلان‌ها", use_container_width=True):
            st.session_state["show_notifications"] = False
        st.markdown("</div>", unsafe_allow_html=True)
    
    # نمایش پروفایل کاربر
    st.markdown("<div class='iranian-border'>", unsafe_allow_html=True)
    st.markdown("### 👤 پروفایل کاربری")
    
    col1, col2 = st.columns([1, 2])
    with col1:
        # آپلود تصویر پروفایل
        uploaded_image = st.file_uploader("🖼️ تغییر تصویر پروفایل", type=["png", "jpg", "jpeg"])
        if uploaded_image:
            try:
                image_bytes = uploaded_image.read()
                conn = get_conn(); c = conn.cursor()
                c.execute("UPDATE users SET profile_image=? WHERE email=?", (image_bytes, user["email"]))
                conn.commit(); conn.close()
                st.success("✅ تصویر پروفایل به روز شد.")
                st.rerun()
            except Exception as e:
                st.error(f"❌ خطا در آپلود تصویر: {e}")
    
    with col2:
        st.markdown(f"**نام:** {user['name']}")
        st.markdown(f"**ایمیل:** {user['email']}")
        if user.get('phone'):
            st.markdown(f"**تلفن:** {user['phone']}")
        if user.get('bio'):
            st.markdown(f"**بیوگرافی:** {user['bio']}")
        st.markdown(f"**امتیاز:** ⭐ {calculate_user_rating(user['email'])}")
        
        # گزارش عملکرد کاربر
        report = generate_user_report(user["email"])
        st.markdown(f"**املاک منتشر شده:** {report['published_properties']}")
        st.markdown(f"**املاک فروخته شده:** {report['sold_properties']}")
        if report['published_properties'] > 0:
            st.markdown(f"**نرخ موفقیت:** {report['success_rate']:.1f}%")
    
    st.markdown("</div>", unsafe_allow_html=True)
    
    st.markdown("<div class='iranian-border'>", unsafe_allow_html=True)
    st.markdown("### 🏡 ثبت ملک جدید - هزینه: **۲۰٬۰۰۰ تومان**")
    st.markdown("</div>", unsafe_allow_html=True)
    
    with st.expander("📋 فرم ثبت ملک", expanded=False):
        st.markdown("<div class='islamic-pattern'>", unsafe_allow_html=True)
        
        title = st.text_input("🏷️ عنوان ملک")
        price = st.number_input("💰 قیمت (تومان)", min_value=0, step=100000)
        area  = st.number_input("📏 متراژ (متر)", min_value=0, step=1)
        city  = st.text_input("🏙️ شهر")
        ptype = st.selectbox("🏠 نوع ملک", ["آپارتمان","ویلایی","مغازه","زمین","دفتر"])
        
        c1,c2 = st.columns(2)
        lat = c1.number_input("📍 عرض جغرافیایی", format="%.6f")
        lon = c2.number_input("📍 طول جغرافیایی", format="%.6f")
        
        address = st.text_input("🏠 آدرس")
        rooms = st.number_input("🚪 تعداد اتاق", min_value=0, step=1)
        age   = st.number_input("🏚️ سن بنا", min_value=0, step=1)
        facilities = st.text_area("⭐ امکانات (با کاما جدا کنید)")
        desc  = st.text_area("📝 توضیحات")
        video = st.text_input("🎥 لینک تور ویدئویی/۳۶۰ (اختیاری)")
        
        featured = st.checkbox("⭐ ملک ویژه (هزینه اضافی)", help="ملک ویژه در صدر نتایج جستجو نمایش داده می‌شود")
        
        uploaded = st.file_uploader(f"🖼️ تصاویر (حداکثر {MAX_UPLOAD_IMAGES} عدد)", type=["png","jpg","jpeg", "webp"], accept_multiple_files=True)
        
        PAY_AMOUNT = DEFAULT_LISTING_FEE * (2 if featured else 1)

        if st.button("💳 پرداخت و ثبت نهایی", use_container_width=True):
            if not title or price<=0 or not city or not uploaded:
                st.error("❌ موارد ضروری: عنوان، قیمت، شهر، حداقل یک تصویر.")
            else:
                try:
                    imgs_bytes = image_files_to_bytes(uploaded)
                    if not imgs_bytes:
                        st.error("❌ هیچ تصویر معتبر بارگذاری نشده.")
                        return
                    cfg = payment_config()
                    callback = f"{cfg['base_url']}/?pg=callback"
                    
                    # انتخاب درگاه پرداخت
                    gateway = st.radio("درگاه پرداخت", ["zarinpal", "idpay"], horizontal=True)
                    
                    authority = create_payment_request(
                        amount=PAY_AMOUNT,
                        description=f"ثبت آگهی ملک: {title}",
                        email=user["email"],
                        mobile=user.get("phone") or "",
                        callback_url=callback,
                        gateway=gateway
                    )
                    if authority:
                        draft = {
                            "title": title, "price": int(price), "area": int(area), "city": city, "property_type": ptype,
                            "latitude": float(lat or 0), "longitude": float(lon or 0), "address": address,
                            "owner_email": user["email"], "description": desc, "rooms": int(rooms or 0),
                            "building_age": int(age or 0), "facilities": facilities, "video_url": video,
                            "featured": featured,
                            "images": [base64.b64encode(b).decode() for b in imgs_bytes]
                        }
                        conn=get_conn(); c=conn.cursor()
                        c.execute("INSERT INTO payments(property_temp_json,user_email,amount,authority,ref_id,status,created_at,payment_gateway) VALUES(?,?,?,?,?,?,?,?)",
                                  (json.dumps(draft), user["email"], PAY_AMOUNT, authority, None, "initiated", now_iso(), gateway))
                        conn.commit(); conn.close()
                        eps = zarinpal_endpoints(cfg["zarinpal"]["sandbox"]) if gateway == "zarinpal" else idpay_endpoints(cfg["idpay"]["sandbox"])
                        st.success("✅ در حال انتقال به درگاه…")
                        if gateway == "zarinpal":
                            st.markdown(f"[🎯 رفتن به درگاه زرین‌پال]({eps['startpay']}/{authority})")
                        else:
                            st.markdown(f"[🎯 رفتن به درگاه IDPay](https://idpay.ir/p/{authority})")
                        st.info("ℹ️ پس از پرداخت، به برنامه بازخواهید گشت و آگهی منتشر می‌شود.")
                    else:
                        st.error("❌ عدم موفقیت در ساخت تراکنش.")
                except Exception as e:
                    st.error(f"❌ پیکربندی درگاه ناقص است: {e}")
        
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("---")
    
    st.markdown("<div class='iranian-border'>", unsafe_allow_html=True)
    st.markdown("### 🔍 جستجو و نقشه")
    st.markdown("</div>", unsafe_allow_html=True)
    
    filt = property_filters()
    df = list_properties_df_cached(json.dumps(filt, ensure_ascii=False))
    show_map(df)

    st.markdown("<div class='iranian-border'>", unsafe_allow_html=True)
    st.markdown("### 📋 نتایج جستجو")
    st.markdown("</div>", unsafe_allow_html=True)
    
    df_page = paginator(df, page_size=8, key="pg_results")
    for _, row in df_page.iterrows():
        property_card(row, st.session_state.get("user"))

    # پیشنهادات هوشمند
    if not df_page.empty and st.session_state.get("user"):
        st.markdown("<div class='iranian-border'>", unsafe_allow_html=True)
        st.markdown("### 🧠 پیشنهادات ویژه برای شما")
        recommendations = get_smart_recommendations(user["email"], 3)
        if not recommendations.empty:
            for _, row in recommendations.iterrows():
                property_card(row, user)
        else:
            st.info("ℹ️ برای نمایش پیشنهادات شخصی‌سازی شده، چند ملک را به علاقه‌مندی‌ها اضافه کنید.")
        st.markdown("</div>", unsafe_allow_html=True)

    # reviews
    if st.session_state.get("review_pid"):
        pid = st.session_state["review_pid"]; st.markdown("---"); 
        st.markdown("<div class='iranian-border'>", unsafe_allow_html=True)
        st.subheader("💬 نظرات و امتیازها")
        st.markdown("</div>", unsafe_allow_html=True)
        
        rating = st.slider("⭐ امتیاز", 1, 5, 5); cm = st.text_area("📝 نظر شما")
        if st.button("📤 ثبت نظر", use_container_width=True):
            if cooldown_ok(f"cooldown_comment_{user['email']}", COMMENT_COOLDOWN_SEC):
                if cm.strip():
                    add_comment(pid, user["email"], cm.strip(), rating); st.success("✅ ثبت شد."); st.session_state["review_pid"]=None; st.rerun()
                else:
                    st.warning("⚠️ نظر نمی‌تواند خالی باشد.")
            else:
                st.warning("⏳ لطفاً کمی صبر کنید و دوباره تلاش کنید.")
        dfc = load_comments(pid)
        if not dfc.empty: st.dataframe(dfc)

    # chat
    if st.session_state.get("chat_pid"):
        pid = st.session_state["chat_pid"]; st.markdown("---"); 
        st.markdown("<div class='iranian-border'>", unsafe_allow_html=True)
        st.subheader("💬 گفتگو")
        st.markdown("</div>", unsafe_allow_html=True)
        
        conn=get_conn(); c=conn.cursor(); c.execute("SELECT owner_email FROM properties WHERE id=?", (pid,)); owner = (c.fetchone() or [""])[0]; conn.close()
        user = st.session_state.get("user")
        if user and owner and owner != user["email"]:
            # علامت گذاری پیام‌ها به عنوان خوانده شده
            mark_messages_as_read(pid, user["email"])
            
            msgs = load_chat(pid, user["email"], owner)
            for m in msgs:
                st.markdown(f"**{m['sender']}** — {m['body']}  \n_{m['at']}_")
            txt = st.text_input("✍️ پیامت را بنویس…", key=f"chat_in_{pid}")
            if st.button("📤 ارسال پیام", key=f"chat_send_{pid}", use_container_width=True) and st.session_state.get(f"chat_in_{pid}"):
                if cooldown_ok(f"cooldown_chat_{user['email']}", CHAT_COOLDOWN_SEC):
                    send_message(pid, user["email"], owner, st.session_state.get(f"chat_in_{pid}"))
                    st.rerun()
                else:
                    st.warning("⏳ برای جلوگیری از اسپم، چند ثانیه صبر کنید.")
        else:
            st.info("ℹ️ مالک پیدا نشد.")

def agent_panel(user: Dict[str,Any]):
    st.markdown("<div class='traditional-header'>", unsafe_allow_html=True)
    st.subheader("👔 پنل مشاور املاک")
    st.markdown("</div>", unsafe_allow_html=True)
    
    st.info("📊 مدیریت آگهی‌های خودت")
    
    st.markdown("<div class='iranian-border'>", unsafe_allow_html=True)
    conn=get_conn(); c=conn.cursor()
    c.execute("SELECT * FROM properties WHERE owner_email=?", (user["email"],))
    rows=c.fetchall(); cols=[d[0] for d in c.description]; conn.close()
    df=pd.DataFrame(rows, columns=cols) if rows else pd.DataFrame()
    if df.empty:
        st.info("ℹ️ هنوز ملکی اضافه نکرده‌ای (کاربران عمومی پس از پرداخت منتشر می‌شوند).")
    else:
        st.dataframe(df[["id","title","price","city","property_type","status","views","featured"]])
    st.markdown("</div>", unsafe_allow_html=True)
    
    # گزارش‌های عملکرد
    if not df.empty:
        st.markdown("<div class='iranian-border'>", unsafe_allow_html=True)
        st.subheader("📈 گزارش‌های عملکرد")
        
        selected_property = st.selectbox("انتخاب ملک برای گزارش", df["id"].tolist(), format_func=lambda x: f"{x} - {df[df['id']==x]['title'].iloc[0]}")
        
        if selected_property:
            report = generate_property_report(selected_property)
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("👀 بازدیدها", report["total_views"])
            col2.metric("❤️ علاقه‌مندی‌ها", report["total_favorites"])
            col3.metric("⭐ امتیاز", report["average_rating"])
            col4.metric("📊 امتیاز عملکرد", report["performance_score"])
            
            # نمودار عملکرد
            fig = go.Figure(data=[
                go.Bar(name='بازدیدها', x=['بازدیدها'], y=[report["total_views"]]),
                go.Bar(name='علاقه‌مندی‌ها', x=['علاقه‌مندی‌ها'], y=[report["total_favorites"]]),
                go.Bar(name='امتیاز', x=['امتیاز'], y=[report["average_rating"] * 5])  # Scale for better visualization
            ])
            st.plotly_chart(fig, use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)
    
    st.markdown("---")
    
    st.markdown("<div class='iranian-border'>", unsafe_allow_html=True)
    st.subheader("❤️ علاقه‌مندی‌های کاربران برای املاک تو")
    
    conn=get_conn(); c=conn.cursor()
    c.execute("""SELECT p.id,p.title,COUNT(f.id) as favs
                 FROM properties p LEFT JOIN favorites f ON p.id=f.property_id
                 WHERE p.owner_email=? GROUP BY p.id,p.title ORDER BY favs DESC""", (user["email"],))
    fav_rows = c.fetchall(); conn.close()
    if fav_rows:
        for pid, title, favs in fav_rows:
            st.write(f"🏠 {pid} | {title} — ❤️ {favs}")
    else:
        st.info("ℹ️ فعلاً علاقه‌مندی ثبت نشده.")
    st.markdown("</div>", unsafe_allow_html=True)

def admin_panel(user: Dict[str,Any]):
    st.markdown("<div class='traditional-header'>", unsafe_allow_html=True)
    st.subheader("👑 پنل مدیر سیستم")
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<div class='iranian-border'>", unsafe_allow_html=True)
    st.markdown("### 📊 آمار کلی سیستم")
    
    conn=get_conn(); c=conn.cursor()
    c.execute("SELECT COUNT(*) FROM users"); users_count = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM properties WHERE status='published'"); props_pub = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM properties"); props_all = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM payments WHERE status='paid'"); paid_cnt = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM property_views"); total_views = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM transactions WHERE status='completed'"); completed_transactions = c.fetchone()[0]
    conn.close()
    
    col1,col2,col3 = st.columns(3)
    col1.metric("👥 کاربران", users_count)
    col2.metric("📢 آگهی‌های منتشرشده", props_pub)
    col3.metric("📋 کل آگهی‌ها", props_all)
    
    col4,col5,col6 = st.columns(3)
    col4.metric("💳 تراکنش‌های موفق", paid_cnt)
    col5.metric("👀 کل بازدیدها", total_views)
    col6.metric("🤝 معاملات تکمیل شده", completed_transactions)
    
    st.markdown(f"**📈 درآمد کل:** {paid_cnt * DEFAULT_LISTING_FEE:,} تومان")
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("---")
    
    st.markdown("<div class='iranian-border'>", unsafe_allow_html=True)
    st.markdown("### 👥 مدیریت کاربران")
    
    conn=get_conn(); c=conn.cursor()
    c.execute("SELECT name,email,role,phone,rating,verified FROM users ORDER BY id DESC")
    users=c.fetchall()
    for name,email,role,phone,rating,verified in users:
        col1,col2,col3,col4,col5,col6,col7 = st.columns([2,2,1,1,1,1,1])
        col1.write(name); col2.write(email); col3.write(role); col4.write(phone or "—"); col5.write(f"⭐ {rating}")
        col6.write("✅" if verified else "❌")
        
        if col7.button(f"ارتقا", key=f"mk_{email}", use_container_width=True):
            cx=get_conn(); cc=cx.cursor(); cc.execute("UPDATE users SET role='agent' WHERE email=?", (email,)); cx.commit(); cx.close(); st.success("✅ انجام شد"); st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("---")
    
    st.markdown("<div class='iranian-border'>", unsafe_allow_html=True)
    st.markdown("### 🏠 مدیریت املاک (انتشار/حذف)")
    
    c = get_conn().cursor(); c.execute("SELECT id,title,owner_email,status,views,featured FROM properties ORDER BY id DESC"); props=c.fetchall()
    for pid,title,owner,status,views,featured in props:
        col1,col2,col3,col4,col5,col6 = st.columns([2,2,1,1,1,1])
        col1.write(f"🏠 {pid} | {title}"); col2.write(owner); col3.write(status); col4.write(f"👀 {views}")
        col5.write("⭐" if featured else "")
        
        if status!="published":
            if col6.button("✅ انتشار", key=f"pub_{pid}", use_container_width=True):
                cx=get_conn(); cc=cx.cursor(); cc.execute("UPDATE properties SET status='published' WHERE id=?", (pid,)); cx.commit(); cx.close(); st.rerun()
        else:
            if col6.button("❌ حذف", key=f"del_{pid}", use_container_width=True):
                cx=get_conn(); cc=cx.cursor(); cc.execute("DELETE FROM properties WHERE id=?", (pid,)); cc.execute("DELETE FROM images WHERE property_id=?", (pid,)); cx.commit(); cx.close(); st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("---")
    
    st.markdown("<div class='iranian-border'>", unsafe_allow_html=True)
    st.markdown("### ⚠️ گزارش‌های تخلف")
    
    reports = get_pending_reports()
    if not reports.empty:
        for _, report in reports.iterrows():
            st.markdown(f"**📋 گزارش از:** {report['reporter_name']} ({report['reporter_email']})")
            st.markdown(f"**📝 مورد:** {report['reported_item_type']} #{report['reported_item_id']}")
            st.markdown(f"**📄 دلیل:** {report['reason']}")
            st.markdown(f"**⏰ زمان:** {report['created_at']}")
            
            col1, col2 = st.columns(2)
            if col1.button("بررسی شده", key=f"resolve_{report['id']}", use_container_width=True):
                resolve_report(report['id'], user['email'], "بررسی توسط ادمین")
                st.success("✅ گزارش بررسی شد")
                st.rerun()
            if col2.button("مشاهده مورد", key=f"view_{report['id']}", use_container_width=True):
                if report['reported_item_type'] == 'property':
                    st.query_params["pg"] = "view"
                    st.query_params["pid"] = report['reported_item_id']
                    st.rerun()
            st.markdown("---")
    else:
        st.info("ℹ️ هیچ گزارش تخلف pendingی وجود ندارد")
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("---")
    
    st.markdown("<div class='iranian-border'>", unsafe_allow_html=True)
    st.markdown("### 🗺️ Sitemap.xml")
    
    try:
        base_url = payment_config()["base_url"].rstrip("/")
    except:
        base_url = "https://example.com"
        
    sitemap_xml = generate_sitemap(base_url)
    st.download_button("📥 دانلود sitemap.xml", data=sitemap_xml, file_name="sitemap.xml", mime="application/xml")
    st.caption("ℹ️ پس از دانلود، فایل را روی ریشه دامنه قرار بده و در Google Search Console معرفی کن.")
    st.markdown("</div>", unsafe_allow_html=True)
    
    st.markdown("---")
    
    st.markdown("<div class='iranian-border'>", unsafe_allow_html=True)
    st.markdown("### 💾 مدیریت پشتیبان‌گیری")
    
    col1, col2 = st.columns(2)
    if col1.button("📦 ایجاد پشتیبان جدید", use_container_width=True):
        backup_file = create_backup()
        st.success(f"✅ پشتیبان با موفقیت ایجاد شد: {backup_file}")
    
    # لیست پشتیبان‌های موجود
    backup_files = [f for f in os.listdir(BACKUP_DIR) if f.endswith('.db') or f.endswith('.gz')]
    if backup_files:
        selected_backup = col2.selectbox("انتخاب پشتیبان برای بازیابی", backup_files)
        if st.button("🔄 بازیابی پشتیبان", use_container_width=True):
            if restore_backup(f"{BACKUP_DIR}/{selected_backup}"):
                st.success("✅ پشتیبان با موفقیت بازیابی شد. لطفاً صفحه را refresh کنید.")
            else:
                st.error("❌ خطا در بازیابی پشتیبان")
    else:
        st.info("ℹ️ هیچ پشتیبانی موجود نیست")
    st.markdown("</div>", unsafe_allow_html=True)
    
    st.markdown("---")
    
    st.markdown("<div class='iranian-border'>", unsafe_allow_html=True)
    st.markdown("### 📈 آمار سیستم")
    
    # نمایش آمار فعالیت کاربران
    activities = get_system_activity(50)
    if not activities.empty:
        st.dataframe(activities)
    else:
        st.info("ℹ️ هیچ فعالیتی ثبت نشده است")
    st.markdown("</div>", unsafe_allow_html=True)

# =========================
# SEO VIEW PAGE پیشرفته
# =========================
def view_property_page(pid:int, base_url:str):
    # افزایش بازدید
    user_email = st.session_state.get("user", {}).get("email") if st.session_state.get("user") else None
    increment_property_views(pid, user_email)
    
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT * FROM properties WHERE id=? AND status='published'", (pid,))
    row = c.fetchone()
    if not row:
        st.error("❌ آگهی یافت نشد یا منتشر نشده.")
        conn.close(); return
    cols = [d[0] for d in c.description]
    prop = dict(zip(cols, row))
    
    # دریافت اطلاعات مالک
    c.execute("SELECT name, phone, rating, verified FROM users WHERE email=?", (prop["owner_email"],))
    owner = c.fetchone()
    if owner:
        prop["owner_name"] = owner[0]
        prop["owner_phone"] = owner[1]
        prop["owner_rating"] = owner[2]
        prop["owner_verified"] = owner[3]
    
    conn.close()

    title = f"{prop['title']} | املاک و مستغلات شهرستان جرقویه"
    desc = (prop.get("description") or f"{prop['property_type']} در {prop['city']}، {prop['area']} متر، قیمت {int(prop['price']):,} تومان")[:160]
    seo_meta(base_url, title, desc, path=f"/?pg=view&pid={pid}")

    st.markdown("<div class='traditional-header'>", unsafe_allow_html=True)
    st.title(prop['title'])
    if prop.get('featured'):
        st.markdown("<span class='badge-premium'>⭐ ملک ویژه</span>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)
    
    st.markdown("<div class='iranian-border'>", unsafe_allow_html=True)
    st.caption(f"🏠 {prop['property_type']} | 🏙️ {prop['city']} | 📏 {int(prop['area'])} متر | 🚪 {int(prop.get('rooms') or 0)} اتاق | 💰 {format_price(prop['price'])} | 👀 {prop.get('views', 0)} بازدید")
    
    if prop.get("address"): st.caption(f"📍 {prop['address']}")
    
    # اطلاعات مالک
    if prop.get("owner_name"):
        owner_text = f"👤 مالک: {prop['owner_name']}"
        if prop.get("owner_verified"):
            owner_text += " <span class='badge-verified'>✅ تأیید شده</span>"
        if prop.get("owner_rating"):
            owner_text += f" | ⭐ {prop['owner_rating']}"
        st.markdown(owner_text, unsafe_allow_html=True)
    
    if prop.get("description"): 
        st.markdown("---")
        st.write(prop['description'])
    
    st.markdown("</div>", unsafe_allow_html=True)

    # نمایش گالری تصاویر
    imgs = property_images(int(prop["id"]))
    if imgs:
        st.markdown("<div class='iranian-border'>", unsafe_allow_html=True)
        st.markdown("### 🖼️ گالری تصاویر")
        
        cols = st.columns(min(3, len(imgs)))
        for i, img in enumerate(imgs):
            with cols[i % len(cols)]:
                try:
                    st.image(io.BytesIO(img), use_column_width=True, caption=f"تصویر {i+1}")
                except:
                    try:
                        st.image(base64.b64decode(img), use_column_width=True, caption=f"تصویر {i+1}")
                    except:
                        pass
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown(f"<script type='application/ld+json'>{jsonld_property(prop, base_url)}</script>", unsafe_allow_html=True)

    if prop.get("latitude") and prop.get("longitude"):
        st.markdown("<div class='iranian-border'>", unsafe_allow_html=True)
        st.markdown("### 🗺️ موقعیت روی نقشه")
        show_map(pd.DataFrame([prop]), cluster=False)
        st.markdown("</div>", unsafe_allow_html=True)

    # دکمه‌های اشتراک‌گذاری
    st.markdown("<div class='iranian-border'>", unsafe_allow_html=True)
    st.markdown("### 📤 اشتراک‌گذاری این ملک")
    share_links = generate_share_links(pid, base_url)
    
    col1, col2, col3, col4 = st.columns(4)
    col1.markdown(f"[📱 واتس‌اپ]({share_links['whatsapp']})")
    col2.markdown(f"[✈️ تلگرام]({share_links['telegram']})")
    col3.markdown(f"[📧 ایمیل]({share_links['email']})")
    col4.markdown(f"[🐦 توییتر]({share_links['twitter']})")
    
    col5, col6, col7, col8 = st.columns(4)
    col5.markdown(f"[💼 لینکدین]({share_links['linkedin']})")
    col6.markdown(f"[🔗 لینک مستقیم]({share_links['direct']})")
    col7.markdown(f"[📷 کد QR]({share_links['qr_code']})")
    
    # کد embed
    with st.expander("</> کد embed"):
        embed_code = generate_embed_code(pid, base_url)
        st.code(embed_code, language="html")
    
    st.markdown("</div>", unsafe_allow_html=True)
    
    # نظرات
    st.markdown("<div class='iranian-border'>", unsafe_allow_html=True)
    st.markdown("### 💬 نظرات کاربران")
    
    comments = load_comments(pid)
    if not comments.empty:
        for _, comment in comments.iterrows():
            st.markdown(f"**{comment['user_name']}** ({comment['user_email']}) - ⭐ {comment['rating']}/5")
            st.markdown(f"{comment['comment']}")
            st.markdown(f"_{comment['created_at']}_ - 👍 {comment['helpful']}")
            st.markdown("---")
    else:
        st.info("ℹ️ هنوز نظری برای این ملک ثبت نشده است.")
    
    # فرم ثبت نظر
    if st.session_state.get("user"):
        st.markdown("#### 📝 افزودن نظر")
        rating = st.slider("امتیاز", 1, 5, 5)
        comment_text = st.text_area("نظر شما")
        if st.button("ثبت نظر", use_container_width=True):
            if cooldown_ok(f"cooldown_comment_{user_email}", COMMENT_COOLDOWN_SEC):
                if comment_text.strip():
                    add_comment(pid, user_email, comment_text.strip(), rating)
                    st.success("✅ نظر شما ثبت شد.")
                    st.rerun()
                else:
                    st.warning("⚠️ نظر نمی‌تواند خالی باشد.")
            else:
                st.warning("⏳ لطفاً کمی صبر کنید و دوباره تلاش کنید.")
    else:
        st.info("ℹ️ برای ثبت نظر باید وارد سیستم شوید.")
    
    st.markdown("</div>", unsafe_allow_html=True)
    
    # گزارش تخلف
    if st.session_state.get("user"):
        st.markdown("<div class='iranian-border'>", unsafe_allow_html=True)
        st.markdown("### ⚠️ گزارش تخلف")
        
        with st.expander("گزارش این آگهی"):
            reason = st.selectbox("دلیل گزارش", [
                "اطلاعات نادرست",
                "تصاویر نامربوط",
                "قیمت غیرواقعی",
                "تکرار آگهی",
                "سایر موارد"
            ])
            details = st.text_area("توضیحات بیشتر")
            if st.button("ارسال گزارش", use_container_width=True):
                report_item(user_email, "property", pid, f"{reason}: {details}")
                st.success("✅ گزارش شما ارسال شد. با تشکر از همکاری شما!")
        st.markdown("</div>", unsafe_allow_html=True)

# =========================
# PAYMENT CALLBACK پیشرفته
# =========================
def handle_payment_callback():
    if "pg" in st.query_params and st.query_params["pg"] == "callback":
        Authority = st.query_params.get("Authority") or st.query_params.get("id")
        Status = st.query_params.get("Status", "")
        
        st.markdown("<div class='traditional-header'>", unsafe_allow_html=True)
        st.markdown("## 💳 نتیجه پرداخت")
        st.markdown("</div>", unsafe_allow_html=True)
        
        if not Authority:
            st.error("❌ Authority یافت نشد.")
            return
            
        conn=get_conn(); c=conn.cursor()
        c.execute("SELECT id, property_temp_json, user_email, amount, payment_gateway FROM payments WHERE authority=? AND status='initiated'", (Authority,))
        row=c.fetchone()
        if not row:
            st.error("❌ تراکنش متناظر پیدا نشد یا قبلاً پردازش شده."); conn.close(); return
            
        pay_id, draft_json, user_email, amount, gateway = row
        if Status != "OK" and gateway == "zarinpal":
            c.execute("UPDATE payments SET status='failed', updated_at=? WHERE id=?", (now_iso(), pay_id)); conn.commit(); conn.close(); st.error("❌ پرداخت لغو/ناموفق شد."); return
            
        res = verify_payment(amount=int(amount), authority=Authority, gateway=gateway)
        data = res.get("data") or {}
        code = data.get("code") or data.get("status")
        
        if (gateway == "zarinpal" and code in (100,101)) or (gateway == "idpay" and code == 100):
            draft = json.loads(draft_json)
            images_b64 = draft.get("images", [])
            images = [base64.b64decode(x) for x in images_b64]
            pid = add_property_row(draft, images=images, publish=True)
            c.execute("UPDATE payments SET status='paid', ref_id=?, updated_at=? WHERE id=?", (str(data.get("ref_id") or data.get("payment_id")), now_iso(), pay_id))
            conn.commit(); conn.close()
            st.success(f"✅ پرداخت موفق ✅ کد پیگیری: {data.get('ref_id') or data.get('payment_id')}")
            st.info(f"ℹ️ آگهی شما منتشر شد. شناسه ملک: {pid}")
            
            # بررسی اشتراک‌ها برای اطلاع‌رسانی
            check_subscriptions(draft)
        else:
            c.execute("UPDATE payments SET status='failed', updated_at=? WHERE id=?", (now_iso(), pay_id)); conn.commit(); conn.close(); st.error(f"❌ عدم تأیید پرداخت: {res}")

# =========================
# MAIN APP پیشرفته
# =========================
def main():
    st.set_page_config(
        page_title="املاک و مستغلات شهرستان جرقویه", 
        layout="wide", 
        page_icon="🏡",
        initial_sidebar_state="expanded"
    )
    custom_style()
    migrate_db()
    
    # اجرای وظایف background
    auto_backup()
    send_subscription_digests()

    # خط زرد در بالای صفحه
    st.markdown("<div class='yellow-line'></div>", unsafe_allow_html=True)

    if "user" not in st.session_state:
        st.session_state["user"] = None

    # Global SEO meta for home
    try:
        base_url = payment_config()["base_url"]
    except:
        base_url = "https://example.com"
        
    seo_meta(
        base_url=base_url,
        title="املاک و مستغلات شهرستان جرقویه | خرید، فروش، اجاره",
        description="سامانه تخصصی املاک و مستغلات شهرستان جرقویه - جستجوی پیشرفته املاک با نقشه، پرداخت امن، علاقه‌مندی‌ها، گفت‌وگو و ثبت آگهی سریع.",
        path="/",
        keywords="املاک, جرقویه, خرید ملک, فروش ملک, اجاره, آپارتمان, ویلا, مغازه, زمین, دفتر کار"
    )

    handle_payment_callback()

    # Direct property view via query params
    if "pg" in st.query_params and st.query_params["pg"] == "view" and "pid" in st.query_params:
        try:
            pid = int(st.query_params["pid"])
            view_property_page(pid, base_url)
            return
        except:
            st.error("❌ شناسه ملک نامعتبر است.")
            return

    st.sidebar.markdown("<div class='persian-pattern' style='text-align: center; padding: 20px;'>", unsafe_allow_html=True)
    st.sidebar.title("🏡 منوی اصلی")
    st.sidebar.markdown("</div>", unsafe_allow_html=True)
    
    if not st.session_state["user"]:
        page = st.sidebar.selectbox("📄 صفحه", ["خانه", "ورود", "ثبت‌نام"])
        if page == "ثبت‌نام":
            signup_page()
        elif page == "ورود":
            login_page()
        else:
            st.markdown("<div class='traditional-header'>", unsafe_allow_html=True)
            st.title("🏡 املاک و مستغلات شهرستان جرقویه")
            st.markdown("</div>", unsafe_allow_html=True)
            
            st.markdown("<div class='iranian-border'>", unsafe_allow_html=True)
            st.markdown("""
            <div style='text-align: center; padding: 30px;'>
                <h2>🌺 به سامانه هوشمند املاک شهرستان جرقویه خوش آمدید</h2>
                <p>برای استفاده از تمامی امکانات سامانه، لطفاً وارد شوید یا ثبت‌نام کنید.</p>
            </div>
            """, unsafe_allow_html=True)
            
            col1, col2, col3 = st.columns(3)
            col1.metric("👥 کاربران", "500+")
            col2.metric("🏠 املاک", "1200+")
            col3.metric("⭐ رضایت", "98%")
            
            st.markdown("---")
            
            st.markdown("""
            <div style='text-align: center;'>
                <h3>✨ امکانات ویژه سامانه</h3>
            </div>
            """, unsafe_allow_html=True)
            
            features = st.columns(3)
            features[0].markdown("""
            <div style='text-align: center; padding: 15px; background: #f8f5ee; border-radius: 15px; margin: 10px;'>
                <h4>🔍 جستجوی هوشمند</h4>
                <p>پیدا کردن ملک با فیلترهای پیشرفته</p>
            </div>
            """, unsafe_allow_html=True)
            
            features[1].markdown("""
            <div style='text-align: center; padding: 15px; background: #f8f5ee; border-radius: 15px; margin: 10px;'>
                <h4>🗺️ نقشه تعاملی</h4>
                <p>نمایش موقعیت مکانی ملک روی نقشه</p>
            </div>
            """, unsafe_allow_html=True)
            
            features[2].markdown("""
            <div style='text-align: center; padding: 15px; background: #f8f5ee; border-radius: 15px; margin: 10px;'>
                <h4>💳 پرداخت امن</h4>
                <p>پرداخت آنلاین با درگاه زرین‌پال</p>
            </div>
            """, unsafe_allow_html=True)
            
            features2 = st.columns(3)
            features2[0].markdown("""
            <div style='text-align: center; padding: 15px; background: #f8f5ee; border-radius: 15px; margin: 10px;'>
                <h4>🤖 پیشنهادات هوشمند</h4>
                <p>سیستم پیشنهاد ملک بر اساس علاقه‌مندی‌ها</p>
            </div>
            """, unsafe_allow_html=True)
            
            features2[1].markdown("""
            <div style='text-align: center; padding: 15px; background: #f8f5ee; border-radius: 15px; margin: 10px;'>
                <h4>📊 گزارشات پیشرفته</h4>
                <p>آنالیز عملکرد املاک و کاربران</p>
            </div>
            """, unsafe_allow_html=True)
            
            features2[2].markdown("""
            <div style='text-align: center; padding: 15px; background: #f8f5ee; border-radius: 15px; margin: 10px;'>
                <h4>📱 پنل مدیریت</h4>
                <p>مدیریت کامل املاک و کاربران</p>
            </div>
            """, unsafe_allow_html=True)
            
            st.markdown("</div>", unsafe_allow_html=True)
            
            # نمایش برخی از املاک ویژه
            st.markdown("<div class='iranian-border'>", unsafe_allow_html=True)
            st.markdown("### 🏠 املاک ویژه")
            
            conn = get_conn(); c = conn.cursor()
            c.execute("SELECT * FROM properties WHERE status='published' AND featured=1 ORDER BY created_at DESC LIMIT 3")
            featured_props = c.fetchall()
            cols = [d[0] for d in c.description]
            conn.close()
            
            if featured_props:
                featured_df = pd.DataFrame(featured_props, columns=cols)
                for _, row in featured_df.iterrows():
                    property_card(row, None)
            else:
                st.info("ℹ️ فعلاً ملک ویژه‌ای وجود ندارد.")
            st.markdown("</div>", unsafe_allow_html=True)
    else:
        user = st.session_state["user"]
        st.sidebar.markdown("<div class='traditional-tab'>", unsafe_allow_html=True)
        st.sidebar.write(f"👤 {user['name']}")
        st.sidebar.write(f"🎯 نقش: {user['role']}")
        st.sidebar.write(f"⭐ امتیاز: {calculate_user_rating(user['email'])}")
        
        # نمایش تصویر پروفایل اگر وجود دارد
        conn = get_conn(); c = conn.cursor()
        c.execute("SELECT profile_image FROM users WHERE email=?", (user["email"],))
        profile_image = c.fetchone()
        if profile_image and profile_image[0]:
            try:
                st.sidebar.image(io.BytesIO(profile_image[0]), use_column_width=True)
            except:
                pass
        conn.close()
        
        st.sidebar.markdown("</div>", unsafe_allow_html=True)
        
        page = st.sidebar.selectbox("📂 بخش‌ها", ["🏠 عمومی", "👔 مشاور", "👑 مدیر", "❤️ علاقه‌مندی‌ها", "📊 گزارشات", "🤝 معاملات"])
        if page == "🏠 عمومی":
            public_panel(user)
        elif page == "👔 مشاور":
            if user["role"] in ("agent","admin"):
                agent_panel(user)
            else:
                st.warning("⚠️ برای دسترسی به پنل مشاور، از ادمین ارتقا بگیرید.")
        elif page == "👑 مدیر":
            if user["role"] == "admin":
                admin_panel(user)
            else:
                st.warning("⚠️ دسترسی لازم ندارید.")
        elif page == "❤️ علاقه‌مندی‌ها":
            st.markdown("<div class='traditional-header'>", unsafe_allow_html=True)
            st.subheader("❤️ لیست علاقه‌مندی‌ها")
            st.markdown("</div>", unsafe_allow_html=True)
            
            favdf = list_favorites(user["email"])
            if favdf.empty: 
                st.markdown("<div class='iranian-border'>", unsafe_allow_html=True)
                st.info("ℹ️ هنوز چیزی اضافه نکرده‌ای.")
                st.markdown("</div>", unsafe_allow_html=True)
            else:
                show_map(favdf)
                dfpage = paginator(favdf, page_size=8, key="pg_fav")
                for _, row in dfpage.iterrows():
                    property_card(row, user)
        elif page == "📊 گزارشات":
            st.markdown("<div class='traditional-header'>", unsafe_allow_html=True)
            st.subheader("📊 گزارشات فعالیت‌ها")
            st.markdown("</div>", unsafe_allow_html=True)
            
            st.markdown("<div class='iranian-border'>", unsafe_allow_html=True)
            activities = get_user_activity(user["email"], 20)
            if not activities.empty:
                for _, activity in activities.iterrows():
                    emoji = "🔍" if "search" in activity["action"] else "❤️" if "favorite" in activity["action"] else "💬" if "comment" in activity["action"] else "📧" if "message" in activity["action"] else "📝"
                    st.markdown(f"{emoji} **{activity['action']}** - {activity['details']} - _{activity['created_at']}_")
            else:
                st.info("ℹ️ هیچ فعالیتی ثبت نشده است.")
            st.markdown("</div>", unsafe_allow_html=True)
        elif page == "🤝 معاملات":
            st.markdown("<div class='traditional-header'>", unsafe_allow_html=True)
            st.subheader("🤝 معاملات من")
            st.markdown("</div>", unsafe_allow_html=True)
            
            transactions = get_user_transactions(user["email"])
            if not transactions.empty:
                st.dataframe(transactions)
            else:
                st.info("ℹ️ هیچ معامله‌ای ثبت نکرده‌اید.")
        
        st.sidebar.markdown("---")
        if st.sidebar.button("🚪 خروج", use_container_width=True):
            st.session_state["user"] = None
            st.rerun()

if __name__ == "__main__":
    main()


  


