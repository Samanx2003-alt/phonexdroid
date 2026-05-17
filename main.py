from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import os, json, shutil
from datetime import datetime

app = FastAPI(title="PhoenixStore API")

# ── CORS للسماح بكل الأجهزة ──
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── مجلدات ──
os.makedirs("apks", exist_ok=True)
os.makedirs("data", exist_ok=True)

DB_FILE = "data/apps.json"
STATS_FILE = "data/stats.json"

# ── قاعدة البيانات ──
def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_db(data):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_stats():
    if os.path.exists(STATS_FILE):
        with open(STATS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"total_downloads": 0, "total_visits": 0}

def save_stats(stats):
    with open(STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(stats, f)

# ── معلومات افتراضية ──
DEFAULT_INFO = {
    "via.apk":      {"name":"Via Browser",   "icon":"🌐","cat":"متصفح",   "desc":"أخف متصفح في العالم - أقل من 500KB","color":"#1A3A5C"},
    "newpipe.apk":  {"name":"NewPipe",        "icon":"📺","cat":"فيديو",    "desc":"يوتيوب بدون Google وبدون إعلانات","color":"#1A0A0A"},
    "vlc.apk":      {"name":"VLC Player",     "icon":"🎬","cat":"فيديو",    "desc":"مشغل فيديو كامل يدعم كل الصيغ","color":"#1A0E00"},
    "amaze.apk":    {"name":"Amaze Files",    "icon":"📁","cat":"ملفات",    "desc":"مدير ملفات خفيف ومفتوح المصدر","color":"#1A0A1A"},
    "openvpn.apk":  {"name":"OpenVPN",        "icon":"🔒","cat":"أمان",     "desc":"VPN مجاني وآمن بدون قيود","color":"#0A1A0A"},
    "frost.apk":    {"name":"Frost",          "icon":"💙","cat":"سوشيال",   "desc":"فيسبوك خفيف وسريع بدون إعلانات","color":"#0A1A3A"},
    "quran.apk":    {"name":"Quran Android",  "icon":"📖","cat":"إسلاميات", "desc":"القرآن الكريم كاملاً بدون إنترنت","color":"#0A1A0F"},
    "skytube.apk":  {"name":"SkyTube",        "icon":"🎥","cat":"فيديو",    "desc":"يوتيوب خفيف بدون حساب Google","color":"#1A0A0A"},
}

def get_size(path):
    if os.path.exists(path):
        s = os.path.getsize(path)
        return f"{s/1024/1024:.1f} MB" if s > 1024*1024 else f"{s/1024:.0f} KB"
    return "0 KB"

def sync_apks():
    db = load_db()
    existing = {a["file"] for a in db}
    changed = False
    for f in os.listdir("apks"):
        if f.endswith(".apk") and f not in existing:
            info = DEFAULT_INFO.get(f, {
                "name": f.replace(".apk","").replace("-"," ").replace("_"," ").title(),
                "icon":"📦","cat":"عام","desc":"تطبيق أندرويد","color":"#1A1A2E"
            })
            db.append({
                "id": len(db)+1,
                "file": f,
                "name": info["name"],
                "icon": info["icon"],
                "cat": info["cat"],
                "desc": info["desc"],
                "color": info.get("color","#1A1A2E"),
                "ver": "1.0",
                "size": get_size(f"apks/{f}"),
                "downloads": 0,
                "date": datetime.now().strftime("%Y-%m-%d"),
                "featured": False
            })
            changed = True
    if changed:
        save_db(db)
    return db

# ── API Routes ──
@app.get("/api/apps")
def api_apps(cat: str = None, search: str = None):
    apps = sync_apks()
    if cat and cat != "الكل":
        apps = [a for a in apps if a.get("cat") == cat]
    if search:
        s = search.lower()
        apps = [a for a in apps if s in a["name"].lower() or s in a.get("desc","").lower()]
    return apps

@app.get("/api/stats")
def api_stats():
    stats = load_stats()
    apps = sync_apks()
    stats["total_apps"] = len(apps)
    stats["total_downloads"] = sum(a.get("downloads",0) for a in apps)
    return stats

@app.post("/api/upload")
async def upload_apk(
    file: UploadFile = File(...),
    name: str = Form(""),
    cat: str = Form("عام"),
    desc: str = Form(""),
    ver: str = Form("1.0"),
    icon: str = Form("📦"),
    color: str = Form("#1A1A2E")
):
    if not file.filename.endswith(".apk"):
        raise HTTPException(400, "يجب أن يكون الملف APK")
    
    safe_name = file.filename.replace(" ", "_")
    path = f"apks/{safe_name}"
    
    with open(path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    
    db = load_db()
    existing = next((a for a in db if a["file"] == safe_name), None)
    app_name = name or safe_name.replace(".apk","").replace("-"," ").replace("_"," ").title()
    
    if existing:
        existing.update({
            "name": app_name, "cat": cat, "desc": desc,
            "ver": ver, "icon": icon, "color": color,
            "size": get_size(path)
        })
    else:
        db.append({
            "id": len(db)+1, "file": safe_name, "name": app_name,
            "icon": icon, "cat": cat, "desc": desc, "color": color,
            "ver": ver, "size": get_size(path), "downloads": 0,
            "date": datetime.now().strftime("%Y-%m-%d"), "featured": False
        })
    save_db(db)
    return {"success": True, "message": f"تم رفع {safe_name} بنجاح"}

@app.delete("/api/delete/{filename}")
def delete_apk(filename: str):
    path = f"apks/{filename}"
    if os.path.exists(path):
        os.remove(path)
    db = [a for a in load_db() if a["file"] != filename]
    save_db(db)
    return {"success": True}

@app.post("/api/download/{filename}")
def count_download(filename: str):
    db = load_db()
    for a in db:
        if a["file"] == filename:
            a["downloads"] = a.get("downloads", 0) + 1
    save_db(db)
    stats = load_stats()
    stats["total_downloads"] = stats.get("total_downloads", 0) + 1
    save_stats(stats)
    return {"success": True}

@app.put("/api/update/{filename}")
async def update_app(
    filename: str,
    name: str = Form(""),
    cat: str = Form(""),
    desc: str = Form(""),
    ver: str = Form(""),
    icon: str = Form(""),
    featured: bool = Form(False)
):
    db = load_db()
    for a in db:
        if a["file"] == filename:
            if name: a["name"] = name
            if cat: a["cat"] = cat
            if desc: a["desc"] = desc
            if ver: a["ver"] = ver
            if icon: a["icon"] = icon
            a["featured"] = featured
    save_db(db)
    return {"success": True}

# ── تخديم الملفات ──
app.mount("/apks", StaticFiles(directory="apks"), name="apks")

# ── الصفحة الرئيسية ──
@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    stats = load_stats()
    stats["total_visits"] = stats.get("total_visits", 0) + 1
    save_stats(stats)
    if os.path.exists("store.html"):
        with open("store.html", "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>PhoenixStore</h1>"
