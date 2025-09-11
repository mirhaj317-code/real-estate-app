# app.py — Super Real-Estate Streamlit App (All-in-One, Upgraded + SEO)
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
from streamlit_folium import st_folium
from datetime import datetime
from typing import Optional, Dict, Any, List
import base64
import io

# =========================
# CONFIG / SETTINGS
# =========================
DB_NAME = "real_estate.db"
DEFAULT_LISTING_FEE = 20000  # تومان
MAX_UPLOAD_IMAGES = 5
MAX_IMAGE_SIZE_MB = 5
ALLOWED_IMAGE_TYPES = {"image/png","image/jpeg","image/jpg"}
COMMENT_COOLDOWN_SEC = 20
CHAT_COOLDOWN_SEC = 10

# =========================
# UTIL — DB CONNECTION / MIGRATIONS
# =========================
def get_conn():
    return sqlite3.connect(DB_NAME, check_same_thread=False)

def migrate_db():
    conn = get_conn(); c = conn.cursor()

    c.execute("""
      CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        email TEXT UNIQUE,
        password_hash TEXT,
        role TEXT DEFAULT 'public',
        phone TEXT
      );
    """)
    c.execute("""
      CREATE TABLE IF NOT EXISTS properties(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        price INTEGER,
        area INTEGER,
        city TEXT,
        property_type TEXT,
        latitude REAL,
        longitude REAL,
        address TEXT,
        owner_email TEXT,
        description TEXT,
        rooms INTEGER,
        building_age INTEGER,
        facilities TEXT,
        video_url TEXT,
        status TEXT DEFAULT 'draft'
      );
    """)
    c.execute("""
      CREATE TABLE IF NOT EXISTS images(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        property_id INTEGER,
        image BLOB,
        FOREIGN KEY(property_id) REFERENCES properties(id)
      );
    """)
    c.execute("""
      CREATE TABLE IF NOT EXISTS comments(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        property_id INTEGER,
        user_email TEXT,
        comment TEXT,
        rating INTEGER,
        created_at TEXT,
        FOREIGN KEY(property_id) REFERENCES properties(id)
      );
    """)
    c.execute("""
      CREATE TABLE IF NOT EXISTS favorites(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        property_id INTEGER,
        user_email TEXT,
        created_at TEXT
      );
    """)
    c.execute("""
      CREATE TABLE IF NOT EXISTS messages(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        property_id INTEGER,
        sender_email TEXT,
        receiver_email TEXT,
        body TEXT,
        created_at TEXT
      );
    """)
    c.execute("""
      CREATE TABLE IF NOT EXISTS payments(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        property_temp_json TEXT,
        user_email TEXT,
        amount INTEGER,
        authority TEXT,
        ref_id TEXT,
        status TEXT,
        created_at TEXT
      );
    """)

    safe_alters = [
        ("properties", "address", "TEXT"),
        ("properties", "video_url", "TEXT"),
        ("properties", "status", "TEXT"),
        ("users", "phone", "TEXT"),
    ]
    for table, col, coltype in safe_alters:
        try:
            c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}")
        except sqlite3.OperationalError:
            pass

    conn.commit(); conn.close()

# =========================
# AUTH
# =========================
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def valid_email(email:str)->bool:
    return bool(re.match(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$", email or ""))

def valid_phone(phone:str)->bool:
    if not phone: return True
    return bool(re.match(r"^[0-9+()\-\s]{7,20}$", phone))

def strong_password(pw:str)->bool:
    return bool(pw and len(pw) >= 8)

def register_user(name: str, email: str, password: str, role="public", phone=None) -> bool:
    if not (name and valid_email(email) and strong_password(password) and valid_phone(phone or "")):
        return False
    try:
        conn = get_conn(); c = conn.cursor()
        c.execute("INSERT INTO users(name,email,password_hash,role,phone) VALUES(?,?,?,?,?)",
                  (name.strip(), email.strip().lower(), hash_password(password), role, (phone or "").strip() or None))
        conn.commit(); conn.close()
        return True
    except sqlite3.IntegrityError:
        return False

def login_user(email: str, password: str) -> Optional[Dict[str,Any]]:
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT name, role, phone, password_hash, email FROM users WHERE email=?", (email.strip().lower(),))
    row = c.fetchone(); conn.close()
    if not row: return None
    name, role, phone, ph, em = row
    if ph == hash_password(password):
        return {"email": em, "name": name, "role": role, "phone": phone}
    return None

def reset_password(email: str, new_password: str) -> bool:
    if not (valid_email(email) and strong_password(new_password)): return False
    conn = get_conn(); c = conn.cursor()
    c.execute("UPDATE users SET password_hash=? WHERE email=?", (hash_password(new_password), email.strip().lower()))
    conn.commit(); ok = c.rowcount>0; conn.close()
    return ok

# =========================
# UTIL HELPERS
# =========================
def haversine_km(lat1, lon1, lat2, lon2):
    R=6371.0
    dLat=math.radians(lat2-lat1)
    dLon=math.radians(lon2-lon1)
    a=math.sin(dLat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dLon/2)**2
    return 2*R*math.asin(math.sqrt(a))

def badge(text):
    st.markdown(f"<span class='pill' style='display:inline-block;background:#fff;border:1px solid #C5A572;padding:6px 10px;border-radius:999px;margin:2px 4px;font-size:12px'>{text}</span>", unsafe_allow_html=True)

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

# =========================
# SEO HELPERS
# =========================
def seo_meta(base_url:str, title:str, description:str, path:str="", image_url:str=""):
    url = base_url.rstrip("/") + (path if path.startswith("/") else f"/{path}")
    tags = f"""
    <meta name="description" content="{description}"/>
    <link rel="canonical" href="{url}"/>
    <meta property="og:title" content="{title}"/>
    <meta property="og:description" content="{description}"/>
    <meta property="og:type" content="website"/>
    <meta property="og:url" content="{url}"/>
    {f'<meta property="og:image" content="{image_url}"/>' if image_url else ''}
    <meta name="twitter:card" content="summary_large_image"/>
    <meta name="twitter:title" content="{title}"/>
    <meta name="twitter:description" content="{description}"/>
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
        "addressLocality": prop.get("city") or ""
      },
      "offers": {
        "@type": "Offer",
        "price": int(prop.get("price") or 0),
        "priceCurrency": "IRR",
        "availability": "https://schema.org/InStock"
      },
      "numberOfRoomsTotal": int(prop.get("rooms") or 0),
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

# =========================
# ZARINPAL PAYMENT HELPERS
# =========================
def zp_config():
    try:
        cfg = {
            "merchant_id": st.secrets["zarinpal"]["merchant_id"],
            "sandbox": bool(st.secrets["zarinpal"].get("sandbox", True)),
            "base_url": st.secrets["app"]["base_url"],
        }
        return cfg
    except Exception as e:
        st.error("پیکربندی زرین‌پال در secrets موجود نیست یا ناقص است. لطفاً .streamlit/secrets.toml را تنظیم کنید.")
        raise

def zp_endpoints(sandbox: bool):
    base = "https://sandbox.zarinpal.com/pg/v4/payment" if sandbox else "https://api.zarinpal.com/pg/v4/payment"
    return {
        "request": f"{base}/request.json",
        "verify": f"{base}/verify.json",
        "startpay": "https://sandbox.zarinpal.com/pg/StartPay" if sandbox else "https://www.zarinpal.com/pg/StartPay"
    }

def create_payment_request(amount:int, description:str, email:str, mobile:str, callback_url:str) -> Optional[str]:
    cfg = zp_config(); ep = zp_endpoints(cfg["sandbox"])
    payload = {
        "merchant_id": cfg["merchant_id"],
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

def verify_payment(amount:int, authority:str) -> Dict[str,Any]:
    cfg = zp_config(); ep = zp_endpoints(cfg["sandbox"])
    payload = {"merchant_id": cfg["merchant_id"], "amount": amount, "authority": authority}
    try:
        r = requests.post(ep["verify"], json=payload, timeout=15)
        return r.json()
    except Exception as e:
        return {"error": str(e)}

# =========================
# DATA ACCESS
# =========================
def add_property_row(data: Dict[str,Any], images: List[bytes], publish:bool=False) -> int:
    conn=get_conn(); c=conn.cursor()
    c.execute("""INSERT INTO properties
    (title,price,area,city,property_type,latitude,longitude,address,owner_email,description,rooms,building_age,facilities,video_url,status)
    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
        data['title'].strip(), int(data['price']), int(data['area']), data['city'].strip(), data['property_type'],
        float(data['latitude']), float(data['longitude']), (data.get('address') or "").strip(),
        data['owner_email'], (data.get('description') or "").strip(), int(data.get('rooms') or 0),
        int(data.get('building_age') or 0), (data.get('facilities') or "").strip(), (data.get('video_url') or "").strip(),
        'published' if publish else 'draft'
    ))
    pid = c.lastrowid
    for img in images[:MAX_UPLOAD_IMAGES]:
        c.execute("INSERT INTO images(property_id,image) VALUES(?,?)", (pid, img))
    conn.commit(); conn.close()
    return pid

@st.cache_data(ttl=120)
def list_properties_df_cached(filters_json: str) -> pd.DataFrame:
    filters = json.loads(filters_json)
    return list_properties_df(filters)

def list_properties_df(filters: Dict[str,Any]) -> pd.DataFrame:
    conn=get_conn(); c=conn.cursor()
    c.execute("SELECT * FROM properties WHERE status='published'")
    rows = c.fetchall(); cols=[d[0] for d in c.description]; conn.close()
    df = pd.DataFrame(rows, columns=cols)
    if df.empty: return df

    if filters.get("city"): df = df[df["city"].isin(filters["city"])]
    if filters.get("property_type"): df = df[df["property_type"].isin(filters["property_type"])]

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
    c.execute("SELECT image FROM images WHERE property_id=?", (prop_id,))
    rows=c.fetchall(); conn.close()
    return [r[0] for r in rows]

# =========================
# MAP RENDER
# =========================
def show_map(df: pd.DataFrame):
    if df.empty:
        st.info("هیچ ملکی مطابق فیلترها پیدا نشد.")
        return
    m = folium.Map(location=[df['latitude'].dropna().mean(), df['longitude'].dropna().mean()], zoom_start=12, tiles="CartoDB positron")
    try:
        from folium.plugins import MarkerCluster
        cluster = MarkerCluster().add_to(m)
    except Exception:
        cluster = m
    for _, row in df.iterrows():
        if pd.isna(row["latitude"]) or pd.isna(row["longitude"]): continue
        html = f"""
        <div style='font-family:Tahoma;'>
          <b>{row["title"]}</b><br>
          نوع: {row["property_type"]} | شهر: {row["city"]}<br>
          قیمت: {int(row["price"]):,} تومان | متراژ: {row["area"]} متر<br>
          <small>{(str(row.get("address") or ""))[:80]}</small>
        </div>
        """
        folium.Marker(
            [row["latitude"], row["longitude"]],
            popup=folium.Popup(html, max_width=300),
            tooltip=row["title"],
            icon=folium.Icon(color="red", icon="home")
        ).add_to(cluster)
    st_folium(m, width=900, height=560)

# =========================
# COMMENTS / FAV / CHAT
# =========================
def add_comment(pid:int, user_email:str, comment:str, rating:int):
    conn=get_conn(); c=conn.cursor()
    c.execute("INSERT INTO comments(property_id,user_email,comment,rating,created_at) VALUES(?,?,?,?,?)",
              (pid, user_email, comment[:1000], max(1,min(5,int(rating))), now_iso()))
    conn.commit(); conn.close()

def load_comments(pid:int) -> pd.DataFrame:
    conn=get_conn(); c=conn.cursor()
    c.execute("SELECT user_email, comment, rating, created_at FROM comments WHERE property_id=? ORDER BY id DESC", (pid,))
    rows=c.fetchall(); conn.close()
    return pd.DataFrame(rows, columns=["user_email","comment","rating","created_at"])

def toggle_fav(pid:int, user_email:str):
    conn=get_conn(); c=conn.cursor()
    c.execute("SELECT id FROM favorites WHERE property_id=? AND user_email=?", (pid,user_email))
    r=c.fetchone()
    if r:
        c.execute("DELETE FROM favorites WHERE id=?", (r[0],))
        conn.commit(); conn.close(); return False
    else:
        c.execute("INSERT INTO favorites(property_id,user_email,created_at) VALUES(?,?,?)",
                  (pid,user_email, now_iso()))
        conn.commit(); conn.close(); return True

def list_favorites(user_email:str) -> pd.DataFrame:
    conn=get_conn(); c=conn.cursor()
    c.execute("""SELECT p.* FROM favorites f
                 JOIN properties p ON p.id=f.property_id
                 WHERE f.user_email=? AND p.status='published'""", (user_email,))
    rows=c.fetchall()
    if not rows:
        conn.close(); return pd.DataFrame()
    cols=[d[0] for d in c.description]; conn.close()
    return pd.DataFrame(rows, columns=cols)

def send_message(pid:int, sender:str, receiver:str, body:str):
    conn=get_conn(); c=conn.cursor()
    c.execute("INSERT INTO messages(property_id,sender_email,receiver_email,body,created_at) VALUES(?,?,?,?,?)",
              (pid, sender, receiver, body[:1000], now_iso()))
    conn.commit(); conn.close()

def load_chat(pid:int, a:str, b:str) -> List[Dict[str,Any]]:
    conn=get_conn(); c=conn.cursor()
    c.execute("""SELECT sender_email, body, created_at FROM messages
                 WHERE property_id=? AND (sender_email IN (?,?) AND receiver_email IN (?,?))
                 ORDER BY id ASC""", (pid, a,b,a,b))
    rows=c.fetchall(); conn.close()
    return [{"sender":r[0], "body":r[1], "at":r[2]} for r in rows]

# =========================
# UI: STYLE
# =========================
def custom_style():
    st.markdown("""
    <style>
      :root{--prim:#8B3A3A;--prim-dark:#6f2e2e;--gold:#C5A572;--cream:#FBF5E6;--ink:#2e2e2e;}
      html, body, [class*="css"] { font-family: Vazirmatn, Tahoma, sans-serif; background: var(--cream); color: var(--ink); }
      .stApp { background: linear-gradient(180deg, #fffaf1, #f9f1df 180px, #fffaf1); }
      .stButton>button{ background: var(--prim); color: #fff; border-radius:14px; padding:10px 18px; font-weight:700;}
      .stTextInput>div>input, .stNumberInput>div>div>input, textarea, select{ border:2px solid var(--gold)!important; border-radius:12px!important; background:#fffaf6!important; }
      .card{ background:#fff; border:1px solid #eadfc7; border-radius:18px; padding:16px; margin:10px 0; box-shadow: 0 6px 26px rgba(197,165,114,.12); }
      .pill{ display:inline-block;background:#fff;border:1px solid var(--gold); padding:6px 10px;border-radius:999px;margin:2px 4px;font-size:12px }
      @media (max-width: 768px){
        .stButton>button{ width:100%; }
        .card{ padding:12px; }
      }
    </style>
    """, unsafe_allow_html=True)

# =========================
# UI: AUTH PAGES
# =========================
def signup_page():
    st.subheader("ثبت‌نام")
    name = st.text_input("نام کامل")
    email = st.text_input("ایمیل")
    phone = st.text_input("شماره تماس (اختیاری)")
    password = st.text_input("رمز عبور (حداقل ۸ کاراکتر)", type="password")
    if st.button("ایجاد حساب"):
        if not name or not valid_email(email) or not strong_password(password) or not valid_phone(phone):
            st.error("لطفاً نام، ایمیل معتبر، رمز قوی (حداقل ۸ کاراکتر) و شماره صحیح وارد کنید.")
        else:
            ok = register_user(name, email, password, role="public", phone=phone or None)
            if ok: st.success("ثبت‌نام موفق. حالا وارد شوید.")
            else: st.error("این ایمیل قبلاً ثبت شده یا ورودی نامعتبر است.")

def login_page():
    st.subheader("ورود")
    email = st.text_input("ایمیل")
    password = st.text_input("رمز عبور", type="password")
    colA, colB = st.columns(2)
    if colA.button("ورود"):
        u = login_user(email, password)
        if u:
            st.session_state["user"] = u
            st.success(f"خوش آمدی {u['name']} 🌹")
            st.experimental_rerun()
        else:
            st.error("ایمیل یا رمز عبور اشتباه است.")
    if colB.button("فراموشی رمز عبور"):
        st.session_state["show_reset"] = True
    if st.session_state.get("show_reset"):
        st.info("رمز جدید را تنظیم کنید (فعلاً بدون ایمیل تایید).")
        e = st.text_input("ایمیل ثبت‌شده", key="rp_e")
        npw = st.text_input("رمز جدید", type="password", key="rp_p")
        if st.button("تغییر رمز"):
            if reset_password(e, npw):
                st.success("رمز تغییر کرد. وارد شوید.")
                st.session_state["show_reset"] = False
            else:
                st.error("ایمیل یا رمز معتبر نیست.")

# =========================
# UI: SEARCH / FILTERS
# =========================
@st.cache_data(ttl=180)
def list_all(colname:str) -> List[str]:
    conn=get_conn(); c=conn.cursor()
    try:
        c.execute(f"SELECT DISTINCT {colname} FROM properties WHERE status='published' AND {colname} IS NOT NULL")
        vals = sorted({r[0] for r in c.fetchall() if r[0]})
    except Exception:
        vals=[]
    conn.close(); return vals

def property_filters():
    st.markdown("### فیلتر دقیق جستجو")
    cities = st.multiselect("شهر", options=list_all("city"))
    types  = st.multiselect("نوع ملک", options=list_all("property_type"))
    c1, c2 = st.columns(2)
    min_price = c1.number_input("حداقل قیمت (تومان)", min_value=0, step=100000, value=0)
    max_price = c2.number_input("حداکثر قیمت (تومان)", min_value=0, step=100000, value=0)
    a1, a2 = st.columns(2)
    min_area = a1.number_input("حداقل متراژ", min_value=0, step=1, value=0)
    max_area = a2.number_input("حداکثر متراژ", min_value=0, step=1, value=0)
    r1, r2 = st.columns(2)
    min_rooms = r1.number_input("حداقل اتاق", min_value=0, step=1, value=0)
    max_rooms = r2.number_input("حداکثر اتاق", min_value=0, step=1, value=0)
    g1, g2 = st.columns(2)
    min_age = g1.number_input("حداقل سن بنا", min_value=0, step=1, value=0)
    max_age = g2.number_input("حداکثر سن بنا", min_value=0, step=1, value=0)
    facilities = st.multiselect("امکانات (شامل شود)", ["آسانسور","پارکینگ","انباری","بالکن","استخر","سونا","روف‌گاردن","کمد دیواری"])
    st.markdown("#### جستجو بر اساس شعاع مکانی (اختیاری)")
    d1, d2, d3 = st.columns(3)
    center_lat = d1.number_input("عرض جغرافیایی مرکز", format="%.6f")
    center_lon = d2.number_input("طول جغرافیایی مرکز", format="%.6f")
    radius_km  = d3.number_input("شعاع (کیلومتر)", min_value=0, step=1)
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
        "radius_km": radius_km if radius_km else None
    }

# =========================
# UI: COMPONENTS
# =========================
def property_card(row: pd.Series, user: Optional[Dict[str,Any]]):
    with st.container():
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        st.markdown(f"#### {row['title']}")
        badge(row["property_type"]); badge(row["city"])
        st.write(f"**قیمت:** {int(row['price']):,} تومان | **متراژ:** {int(row['area'])} متر | **اتاق:** {int(row['rooms'] or 0)}")
        if row.get("address"):
            st.caption(f"📍 {row['address']}")
        if row.get("description"):
            st.write((row['description'] or "")[:280])
        imgs = property_images(int(row["id"]))
        if imgs:
            try:
                st.image(io.BytesIO(imgs[0]), use_column_width=True)
            except Exception:
                try:
                    st.image(base64.b64decode(imgs[0]), use_column_width=True)
                except Exception:
                    pass
        cols = st.columns(5)
        if user:
            if cols[0].button("علاقه‌مندی ❤️", key=f"fav_{row['id']}"):
                _ = toggle_fav(int(row['id']), user["email"])
                st.success("به علاقه‌مندی‌ها اضافه/حذف شد.")
        if row.get("video_url"):
            cols[1].markdown(f"[🎥 تور ویدئویی]({row['video_url']})")
        if cols[2].button("نمایش روی نقشه 🗺️", key=f"map_{row['id']}"):
            st.map(pd.DataFrame([[row["latitude"],row["longitude"]]], columns=["lat","lon"]))
        if cols[3].button("جزئیات 📄", key=f"view_{row['id']}"):
            st.experimental_set_query_params(pg="view", pid=int(row['id']))
            st.experimental_rerun()
        if user and user["email"] != row["owner_email"]:
            if cols[4].button("گفتگو 💬", key=f"chat_{row['id']}"):
                st.session_state["chat_pid"]=int(row['id']); st.experimental_rerun()
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
# UI: PANELS
# =========================
def public_panel(user: Dict[str,Any]):
    st.subheader(f"خوش آمدی {user['name']} 🌿")
    st.markdown("### ثبت ملک (برای عموم) – هزینه: **۲۰٬۰۰۰ تومان** از طریق زرین‌پال")
    with st.expander("فرم ثبت ملک", expanded=False):
        title = st.text_input("عنوان")
        price = st.number_input("قیمت (تومان)", min_value=0, step=100000)
        area  = st.number_input("متراژ (متر)", min_value=0, step=1)
        city  = st.text_input("شهر")
        ptype = st.selectbox("نوع ملک", ["آپارتمان","ویلایی","مغازه","زمین","دفتر"])
        c1,c2 = st.columns(2)
        lat = c1.number_input("عرض جغرافیایی", format="%.6f")
        lon = c2.number_input("طول جغرافیایی", format="%.6f")
        address = st.text_input("آدرس")
        rooms = st.number_input("تعداد اتاق", min_value=0, step=1)
        age   = st.number_input("سن بنا", min_value=0, step=1)
        facilities = st.text_area("امکانات (با کاما جدا کن)")
        desc  = st.text_area("توضیحات")
        video = st.text_input("لینک تور ویدئویی/۳۶۰ (اختیاری)")
        uploaded = st.file_uploader(f"تصاویر (حداکثر {MAX_UPLOAD_IMAGES} عدد)", type=["png","jpg","jpeg"], accept_multiple_files=True)
        PAY_AMOUNT = DEFAULT_LISTING_FEE

        if st.button("پرداخت و ثبت نهایی"):
            if not title or price<=0 or not city or not uploaded:
                st.error("موارد ضروری: عنوان، قیمت، شهر، حداقل یک تصویر.")
            else:
                try:
                    imgs_bytes = image_files_to_bytes(uploaded)
                    if not imgs_bytes:
                        st.error("هیچ تصویر معتبر بارگذاری نشده.")
                        return
                    cfg = zp_config()
                    callback = f"{cfg['base_url']}/?pg=callback"
                    authority = create_payment_request(
                        amount=PAY_AMOUNT,
                        description=f"ثبت آگهی ملک: {title}",
                        email=user["email"],
                        mobile=user.get("phone") or "",
                        callback_url=callback
                    )
                    if authority:
                        draft = {
                            "title": title, "price": int(price), "area": int(area), "city": city, "property_type": ptype,
                            "latitude": float(lat or 0), "longitude": float(lon or 0), "address": address,
                            "owner_email": user["email"], "description": desc, "rooms": int(rooms or 0),
                            "building_age": int(age or 0), "facilities": facilities, "video_url": video,
                            "images": [base64.b64encode(b).decode() for b in imgs_bytes]
                        }
                        conn=get_conn(); c=conn.cursor()
                        c.execute("INSERT INTO payments(property_temp_json,user_email,amount,authority,ref_id,status,created_at) VALUES(?,?,?,?,?,?,?)",
                                  (json.dumps(draft), user["email"], PAY_AMOUNT, authority, None, "initiated", now_iso()))
                        conn.commit(); conn.close()
                        eps = zp_endpoints(cfg["sandbox"])
                        st.success("در حال انتقال به درگاه…")
                        st.markdown(f"[رفتن به درگاه زرین‌پال]({eps['startpay']}/{authority})")
                        st.info("پس از پرداخت، به برنامه بازخواهید گشت و آگهی منتشر می‌شود.")
                    else:
                        st.error("عدم موفقیت در ساخت تراکنش.")
                except Exception as e:
                    st.error(f"پیکربندی درگاه ناقص است: {e}")

    st.markdown("---")
    st.markdown("### جستجو و نقشه")
    filt = property_filters()
    df = list_properties_df_cached(json.dumps(filt, ensure_ascii=False))
    show_map(df)

    st.markdown("### نتایج")
    df_page = paginator(df, page_size=8, key="pg_results")
    for _, row in df_page.iterrows():
        property_card(row, st.session_state.get("user"))

    # reviews
    if st.session_state.get("review_pid"):
        pid = st.session_state["review_pid"]; st.markdown("---"); st.subheader("نظرات و امتیازها")
        rating = st.slider("امتیاز", 1, 5, 5); cm = st.text_area("نظر شما")
        if st.button("ثبت نظر"):
            if cooldown_ok(f"cooldown_comment_{user['email']}", COMMENT_COOLDOWN_SEC):
                if cm.strip():
                    add_comment(pid, user["email"], cm.strip(), rating); st.success("ثبت شد."); st.session_state["review_pid"]=None; st.experimental_rerun()
                else:
                    st.warning("نظر نمی‌تواند خالی باشد.")
            else:
                st.warning("لطفاً کمی صبر کنید و دوباره تلاش کنید.")
        dfc = load_comments(pid)
        if not dfc.empty: st.dataframe(dfc)

    # chat
    if st.session_state.get("chat_pid"):
        pid = st.session_state["chat_pid"]; st.markdown("---"); st.subheader("گفتگو")
        conn=get_conn(); c=conn.cursor(); c.execute("SELECT owner_email FROM properties WHERE id=?", (pid,)); owner = (c.fetchone() or [""])[0]; conn.close()
        user = st.session_state.get("user")
        if user and owner and owner != user["email"]:
            msgs = load_chat(pid, user["email"], owner)
            for m in msgs:
                st.markdown(f"**{m['sender']}** — {m['body']}  \n_{m['at']}_")
            txt = st.text_input("پیامت را بنویس…", key=f"chat_in_{pid}")
            if st.button("ارسال پیام", key=f"chat_send_{pid}") and st.session_state.get(f"chat_in_{pid}"):
                if cooldown_ok(f"cooldown_chat_{user['email']}", CHAT_COOLDOWN_SEC):
                    send_message(pid, user["email"], owner, st.session_state.get(f"chat_in_{pid}"))
                    st.experimental_rerun()
                else:
                    st.warning("برای جلوگیری از اسپم، چند ثانیه صبر کنید.")
        else:
            st.info("مالک پیدا نشد.")

def agent_panel(user: Dict[str,Any]):
    st.subheader("پنل مشاور")
    st.info("مدیریت آگهی‌های خودت")
    conn=get_conn(); c=conn.cursor()
    c.execute("SELECT * FROM properties WHERE owner_email=?", (user["email"],))
    rows=c.fetchall(); cols=[d[0] for d in c.description]; conn.close()
    df=pd.DataFrame(rows, columns=cols) if rows else pd.DataFrame()
    if df.empty:
        st.info("هنوز ملکی اضافه نکرده‌ای (کاربران عمومی پس از پرداخت منتشر می‌شوند).")
    else:
        st.dataframe(df[["id","title","price","city","property_type","status"]])
    st.markdown("---")
    st.subheader("علاقه‌مندی‌های کاربران برای املاک تو")
    conn=get_conn(); c=conn.cursor()
    c.execute("""SELECT p.id,p.title,COUNT(f.id) as favs
                 FROM properties p LEFT JOIN favorites f ON p.id=f.property_id
                 WHERE p.owner_email=? GROUP BY p.id,p.title ORDER BY favs DESC""", (user["email"],))
    fav_rows = c.fetchall(); conn.close()
    if fav_rows:
        for pid, title, favs in fav_rows:
            st.write(f"{pid} | {title} — ❤️ {favs}")
    else:
        st.info("فعلاً علاقه‌مندی ثبت نشده.")

def admin_panel(user: Dict[str,Any]):
    st.subheader("پنل مدیر")

    st.markdown("### آمار کلی")
    conn=get_conn(); c=conn.cursor()
    c.execute("SELECT COUNT(*) FROM users"); users_count = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM properties WHERE status='published'"); props_pub = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM properties"); props_all = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM payments WHERE status='paid'"); paid_cnt = c.fetchone()[0]
    conn.close()
    col1,col2,col3,col4 = st.columns(4)
    col1.metric("کاربران", users_count)
    col2.metric("آگهی‌های منتشرشده", props_pub)
    col3.metric("کل آگهی‌ها", props_all)
    col4.metric("تراکنش‌های موفق", paid_cnt)

    st.markdown("---")
    st.markdown("### مدیریت کاربران")
    conn=get_conn(); c=conn.cursor()
    c.execute("SELECT name,email,role,phone FROM users ORDER BY id DESC")
    users=c.fetchall()
    for name,email,role,phone in users:
        col1,col2,col3,col4,col5 = st.columns([3,3,2,3,2])
        col1.write(name); col2.write(email); col3.write(role); col4.write(phone or "—")
        if col5.button(f"ارتقا به مشاور", key=f"mk_{email}"):
            cx=get_conn(); cc=cx.cursor(); cc.execute("UPDATE users SET role='agent' WHERE email=?", (email,)); cx.commit(); cx.close(); st.success("انجام شد"); st.experimental_rerun()

    st.markdown("---")
    st.markdown("### مدیریت املاک (انتشار/حذف)")
    c = get_conn().cursor(); c.execute("SELECT id,title,owner_email,status FROM properties ORDER BY id DESC"); props=c.fetchall()
    for pid,title,owner,status in props:
        col1,col2,col3,col4 = st.columns([3,3,2,3])
        col1.write(f"{pid} | {title}"); col2.write(owner); col3.write(status)
        if status!="published":
            if col4.button("انتشار", key=f"pub_{pid}"):
                cx=get_conn(); cc=cx.cursor(); cc.execute("UPDATE properties SET status='published' WHERE id=?", (pid,)); cx.commit(); cx.close(); st.experimental_rerun()
        else:
            if col4.button("حذف", key=f"del_{pid}"):
                cx=get_conn(); cc=cx.cursor(); cc.execute("DELETE FROM properties WHERE id=?", (pid,)); cc.execute("DELETE FROM images WHERE property_id=?", (pid,)); cx.commit(); cx.close(); st.experimental_rerun()

    st.markdown("---")
    st.markdown("### Sitemap.xml")
    try:
        base_url = zp_config()["base_url"].rstrip("/")
    except:
        base_url = "https://example.com"
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT id FROM properties WHERE status='published' ORDER BY id DESC")
    ids = [r[0] for r in c.fetchall()]
    conn.close()
    urls = [f"{base_url}/?pg=view&pid={pid}" for pid in ids]
    sitemap = ["<?xml version='1.0' encoding='UTF-8'?>",
               "<urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>"]
    for u in urls:
        sitemap.append(f"<url><loc>{u}</loc><changefreq>daily</changefreq><priority>0.8</priority></url>")
    sitemap.append("</urlset>")
    sitemap_xml = "\n".join(sitemap)
    st.download_button("دانلود sitemap.xml", data=sitemap_xml, file_name="sitemap.xml", mime="application/xml")
    st.caption("پس از دانلود، فایل را روی ریشه دامنه قرار بده و در Google Search Console معرفی کن.")

# =========================
# SEO VIEW PAGE
# =========================
def view_property_page(pid:int, base_url:str):
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT * FROM properties WHERE id=? AND status='published'", (pid,))
    row = c.fetchone()
    if not row:
        st.error("آگهی یافت نشد یا منتشر نشده.")
        conn.close(); return
    cols = [d[0] for d in c.description]
    prop = dict(zip(cols, row))
    conn.close()

    title = f"{prop['title']} | آگهی املاک"
    desc = (prop.get("description") or f"{prop['property_type']} در {prop['city']}، {prop['area']} متر، قیمت {int(prop['price']):,} تومان")[:160]
    seo_meta(base_url, title, desc, path=f"/?pg=view&pid={pid}")

    st.title(prop['title'])
    st.caption(f"{prop['property_type']} | {prop['city']} | {int(prop['area'])} متر | {int(prop.get('rooms') or 0)} اتاق | {int(prop['price']):,} تومان")
    if prop.get("address"): st.caption(f"📍 {prop['address']}")
    if prop.get("description"): st.write(prop['description'])

    imgs = property_images(int(prop["id"]))
    if imgs:
        cols = st.columns(min(3, len(imgs)))
        for i, img in enumerate(imgs[:3]):
            with cols[i % len(cols)]:
                try:
                    st.image(io.BytesIO(img), use_column_width=True)
                except:
                    try:
                        st.image(base64.b64decode(img), use_column_width=True)
                    except:
                        pass

    st.markdown(f"<script type='application/ld+json'>{jsonld_property(prop, base_url)}</script>", unsafe_allow_html=True)

    if prop.get("latitude") and prop.get("longitude"):
        st.markdown("### موقعیت روی نقشه")
        show_map(pd.DataFrame([prop]))

    share_url = f"{base_url.rstrip('/')}/?pg=view&pid={pid}"
    st.code(share_url, language="text")

# =========================
# PAYMENT CALLBACK
# =========================
def handle_payment_callback():
    q = st.experimental_get_query_params()
    pg = q.get("pg", [None])[0]
    if pg != "callback": return
    Authority = q.get("Authority", [None])[0]
    Status = q.get("Status", [None])[0]
    st.markdown("## نتیجه پرداخت")
    if not Authority:
        st.error("Authority یافت نشد.")
        return
    conn=get_conn(); c=conn.cursor()
    c.execute("SELECT id, property_temp_json, user_email, amount FROM payments WHERE authority=? AND status='initiated'", (Authority,))
    row=c.fetchone()
    if not row:
        st.error("تراکنش متناظر پیدا نشد یا قبلاً پردازش شده."); conn.close(); return
    pay_id, draft_json, user_email, amount = row
    if Status != "OK":
        c.execute("UPDATE payments SET status='failed' WHERE id=?", (pay_id,)); conn.commit(); conn.close(); st.error("پرداخت لغو/ناموفق شد."); return
    res = verify_payment(amount=int(amount), authority=Authority)
    data = res.get("data") or {}
    code = data.get("code")
    ref_id = data.get("ref_id")
    if code in (100,101):
        draft = json.loads(draft_json)
        images_b64 = draft.get("images", [])
        images = [base64.b64decode(x) for x in images_b64]
        pid = add_property_row(draft, images=images, publish=True)
        c.execute("UPDATE payments SET status='paid', ref_id=? WHERE id=?", (str(ref_id), pay_id))
        conn.commit(); conn.close()
        st.success(f"پرداخت موفق ✅ کد پیگیری: {ref_id}")
        st.info(f"آگهی شما منتشر شد. شناسه ملک: {pid}")
    else:
        c.execute("UPDATE payments SET status='failed' WHERE id=?", (pay_id,)); conn.commit(); conn.close(); st.error(f"عدم تأیید پرداخت: {res}")

# =========================
# MAIN APP
# =========================
def main():
    st.set_page_config(page_title="سوپر اپ املاک", layout="wide")
    custom_style()
    migrate_db()

    if "user" not in st.session_state:
        st.session_state["user"] = None

    # Global SEO meta for home
    try:
        base_url = zp_config()["base_url"]
    except:
        base_url = "https://example.com"
    seo_meta(
        base_url=base_url,
        title="سوپر اپ املاک | خرید، فروش، اجاره",
        description="جستجوی پیشرفته املاک با نقشه، پرداخت امن، علاقه‌مندی‌ها، گفت‌وگو و ثبت آگهی سریع.",
        path="/"
    )

    handle_payment_callback()

    # Direct property view via query
    q = st.experimental_get_query_params()
    if q.get("pg", [None])[0] == "view" and q.get("pid", [None])[0]:
        try:
            base_url = zp_config()["base_url"]
        except:
            base_url = "https://example.com"
        pid = int(q["pid"][0])
        view_property_page(pid, base_url)
        return

    st.sidebar.title("منوی اصلی")
    if not st.session_state["user"]:
        page = st.sidebar.selectbox("صفحه", ["ورود","ثبت‌نام","خانه"])
        if page == "ثبت‌نام":
            signup_page()
        elif page == "ورود":
            login_page()
        else:
            st.title("🏡 سوپر اپ املاک")
            st.write("به سامانه خوش آمدید — ابتدا وارد شوید یا ثبت‌نام کنید.")
    else:
        user = st.session_state["user"]
        st.sidebar.write(f"👤 {user['name']} | نقش: {user['role']}")
        page = st.sidebar.selectbox("بخش‌ها", ["عمومی","مشاور","مدیر","علاقه‌مندی‌ها"])
        if page == "عمومی":
            public_panel(user)
        elif page == "مشاور":
            if user["role"] in ("agent","admin"):
                agent_panel(user)
            else:
                st.warning("برای دسترسی به پنل مشاور، از ادمین ارتقا بگیرید.")
        elif page == "مدیر":
            if user["role"] == "admin":
                admin_panel(user)
            else:
                st.warning("دسترسی لازم ندارید.")
        elif page == "علاقه‌مندی‌ها":
            st.subheader("لیست علاقه‌مندی‌ها")
            favdf = list_favorites(user["email"])
            if favdf.empty: st.info("هنوز چیزی اضافه نکرده‌ای.")
            else:
                show_map(favdf)
                dfpage = paginator(favdf, page_size=8, key="pg_fav")
                for _, row in dfpage.iterrows():
                    property_card(row, user)
        if st.sidebar.button("خروج"):
            st.session_state["user"] = None
            st.experimental_rerun()

if __name__ == "__main__":
    main()


  


