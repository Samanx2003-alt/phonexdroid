from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request, Header
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import os, json, shutil, hashlib, httpx
from datetime import datetime, date
from typing import Optional

app = FastAPI(title="PhoenixStore")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

ADMIN_TOKEN = os.getenv("PHOENIX_ADMIN_SECRET", "A1s2d3_4")
API_SECRET  = os.getenv("PHOENIX_API_SECRET",   "phoenix2026")

os.makedirs("apks", exist_ok=True)
os.makedirs("data", exist_ok=True)

DB_FILE    = "data/apps.json"
STATS_FILE = "data/stats.json"
USERS_FILE = "data/users.json"

def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE,"r",encoding="utf-8") as f: return json.load(f)
    return []

def save_db(data):
    with open(DB_FILE,"w",encoding="utf-8") as f: json.dump(data,f,ensure_ascii=False,indent=2)

def load_stats():
    if os.path.exists(STATS_FILE):
        with open(STATS_FILE,"r") as f: return json.load(f)
    return {"total_downloads":0,"total_visits":0}

def save_stats(s):
    with open(STATS_FILE,"w") as f: json.dump(s,f)

def load_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE,"r",encoding="utf-8") as f: return json.load(f)
    return {}

def save_users(u):
    with open(USERS_FILE,"w",encoding="utf-8") as f: json.dump(u,f,ensure_ascii=False,indent=2)

def get_size(path):
    if os.path.exists(path):
        s = os.path.getsize(path)
        return f"{s/1024/1024:.1f} MB" if s>1024*1024 else f"{s/1024:.0f} KB"
    return "0 KB"

def md5_sign(text):
    return hashlib.md5(text.encode()).hexdigest()

def verify_admin(token):
    return token == ADMIN_TOKEN

def verify_user_token(token):
    users = load_users()
    for username, data in users.items():
        if data.get("token") == token:
            return username
    return None

def sync_apks():
    db = load_db()
    existing = {a["file"] for a in db}
    defaults = {
        "via.apk":     {"name":"Via Browser","icon":"🌐","cat":"Browser","desc":"Lightest browser under 500KB","color":"#0A1628"},
        "newpipe.apk": {"name":"NewPipe","icon":"📺","cat":"Video","desc":"YouTube without Google or ads","color":"#1A0505"},
        "vlc.apk":     {"name":"VLC Player","icon":"🎬","cat":"Video","desc":"Full video player all formats","color":"#1A0E00"},
        "amaze.apk":   {"name":"Amaze Files","icon":"📁","cat":"Files","desc":"Lightweight file manager","color":"#1A0A1A"},
        "openvpn.apk": {"name":"OpenVPN","icon":"🔒","cat":"Security","desc":"Free secure VPN","color":"#0A1A0A"},
    }
    changed = False
    for f in os.listdir("apks"):
        if f.endswith(".apk") and f not in existing:
            info = defaults.get(f,{"name":f.replace(".apk","").replace("-"," ").title(),"icon":"📦","cat":"General","desc":"Android App","color":"#1A1A2E"})
            db.append({"id":len(db)+1,"file":f,"name":info["name"],"icon":info["icon"],"cat":info["cat"],"desc":info["desc"],"color":info["color"],"ver":"1.0","size":get_size(f"apks/{f}"),"downloads":0,"date":datetime.now().strftime("%Y-%m-%d"),"uploader":"admin"})
            changed = True
    if changed: save_db(db)
    return db

# ── Auth ──
@app.post("/api/register")
async def register(username:str=Form(...),password:str=Form(...),email:str=Form("")):
    users = load_users()
    if username in users: raise HTTPException(400,"اسم المستخدم موجود")
    if len(username)<3: raise HTTPException(400,"اسم المستخدم قصير جداً")
    if len(password)<6: raise HTTPException(400,"كلمة المرور قصيرة جداً")
    token = md5_sign(username+password+str(datetime.now()))
    users[username] = {"password":md5_sign(password),"email":email,"token":token,"joined":datetime.now().strftime("%Y-%m-%d"),"uploads":0}
    save_users(users)
    return {"success":True,"token":token,"username":username}

@app.post("/api/login")
async def login(username:str=Form(...),password:str=Form(...)):
    users = load_users()
    if username not in users: raise HTTPException(401,"اسم المستخدم غير موجود")
    if users[username]["password"] != md5_sign(password): raise HTTPException(401,"كلمة المرور خاطئة")
    return {"success":True,"token":users[username]["token"],"username":username}

# ── Apps ──
@app.get("/api/apps")
def api_apps(cat:str=None,search:str=None):
    apps = sync_apks()
    if cat and cat not in ("All","الكل"): apps=[a for a in apps if a.get("cat")==cat]
    if search:
        s=search.lower(); apps=[a for a in apps if s in a["name"].lower() or s in a.get("desc","").lower()]
    return apps

@app.get("/api/stats")
def api_stats():
    stats=load_stats(); apps=sync_apks()
    stats["total_apps"]=len(apps)
    stats["total_downloads"]=sum(a.get("downloads",0) for a in apps)
    return stats

@app.post("/api/upload")
async def upload_apk(file:UploadFile=File(...),name:str=Form(""),cat:str=Form("General"),desc:str=Form(""),ver:str=Form("1.0"),icon:str=Form("📦"),color:str=Form("#1A1A2E"),user_token:str=Form(""),admin_token:str=Form("")):
    is_admin=verify_admin(admin_token)
    username=verify_user_token(user_token)
    if not is_admin and not username: raise HTTPException(403,"يجب تسجيل الدخول للرفع")
    if not file.filename.endswith(".apk"): raise HTTPException(400,"يجب أن يكون الملف APK")
    safe=file.filename.replace(" ","_"); path=f"apks/{safe}"
    with open(path,"wb") as f: shutil.copyfileobj(file.file,f)
    db=load_db(); existing=next((a for a in db if a["file"]==safe),None)
    app_name=name or safe.replace(".apk","").replace("-"," ").replace("_"," ").title()
    uploader="admin" if is_admin else username
    if existing: existing.update({"name":app_name,"cat":cat,"desc":desc,"ver":ver,"icon":icon,"color":color,"size":get_size(path)})
    else: db.append({"id":len(db)+1,"file":safe,"name":app_name,"icon":icon,"cat":cat,"desc":desc,"color":color,"ver":ver,"size":get_size(path),"downloads":0,"date":datetime.now().strftime("%Y-%m-%d"),"uploader":uploader})
    save_db(db)
    if username:
        users=load_users()
        if username in users: users[username]["uploads"]=users[username].get("uploads",0)+1; save_users(users)
    return {"success":True,"message":f"تم رفع {safe}"}

@app.delete("/api/delete/{filename}")
def delete_apk(filename:str,x_admin_token:str=Header("")):
    if not verify_admin(x_admin_token): raise HTTPException(403,"غير مصرح — فقط الأدمن")
    path=f"apks/{filename}"
    if os.path.exists(path): os.remove(path)
    db=[a for a in load_db() if a["file"]!=filename]; save_db(db)
    return {"success":True}

@app.post("/api/download/{filename}")
def count_download(filename:str):
    db=load_db()
    for a in db:
        if a["file"]==filename: a["downloads"]=a.get("downloads",0)+1
    save_db(db)
    stats=load_stats(); stats["total_downloads"]=stats.get("total_downloads",0)+1; save_stats(stats)
    return {"success":True}

@app.get("/api/proxy-download")
async def proxy_download(url:str):
    if not url.startswith("http"): raise HTTPException(400,"رابط غير صالح")
    try:
        async with httpx.AsyncClient(follow_redirects=True,timeout=60) as client:
            async with client.stream("GET",url) as response:
                filename=url.split("/")[-1] or "download.apk"
                headers={"Content-Disposition":f'attachment; filename="{filename}"',"Content-Type":"application/vnd.android.package-archive"}
                return StreamingResponse(response.aiter_bytes(),headers=headers,media_type="application/vnd.android.package-archive")
    except Exception as e:
        raise HTTPException(500,f"فشل التحميل: {str(e)}")

app.mount("/apks",StaticFiles(directory="apks"),name="apks")

@app.get("/",response_class=HTMLResponse)
async def root(request:Request):
    stats=load_stats(); stats["total_visits"]=stats.get("total_visits",0)+1; save_stats(stats)
    if os.path.exists("store.html"):
        with open("store.html","r",encoding="utf-8") as f: return f.read()
    return "<h1>PhoenixStore</h1>"
