from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request, Header
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import os, json, shutil, hashlib, httpx, re
from datetime import datetime
from typing import Optional, List

app = FastAPI(title="PhoenixStore")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

ADMIN_TOKEN = os.getenv("PHOENIX_ADMIN_SECRET", "A1s2d3_4")

for d in ["apks","data","icons","screenshots"]:
    os.makedirs(d, exist_ok=True)

DB_FILE    = "data/apps.json"
STATS_FILE = "data/stats.json"
USERS_FILE = "data/users.json"

ANDROID_VERSIONS = {
    1:"1.0",2:"1.1",3:"1.5",4:"1.6",5:"2.0",6:"2.0.1",7:"2.1",
    8:"2.2",9:"2.3",10:"2.3.3",11:"3.0",12:"3.1",13:"3.2",
    14:"4.0",15:"4.0.3",16:"4.1",17:"4.2",18:"4.3",19:"4.4",
    20:"4.4W",21:"5.0",22:"5.1",23:"6.0",24:"7.0",25:"7.1",
    26:"8.0",27:"8.1",28:"9.0",29:"10",30:"11",31:"12",32:"12L",33:"13",34:"14"
}

def sdk_to_android(sdk):
    try: return ANDROID_VERSIONS.get(int(sdk), str(sdk))
    except: return str(sdk)

def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE,"r",encoding="utf-8") as f: return json.load(f)
    return []

def save_db(d):
    with open(DB_FILE,"w",encoding="utf-8") as f: json.dump(d,f,ensure_ascii=False,indent=2)

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

def md5(text): return hashlib.md5(text.encode()).hexdigest()
def verify_admin(t): return t == ADMIN_TOKEN

def make_slug(name, file):
    clean = re.sub(r'[^a-z0-9-]','',name.lower().replace(' ','-'))[:25].strip('-')
    uid = md5(file)[:6]
    return f"{clean}-{uid}"

def verify_user_token(token):
    for u,d in load_users().items():
        if d.get("token")==token: return u
    return None

def extract_apk_info(apk_path):
    info = {"name":"","icon_path":"","version":"1.0","min_sdk":"","min_android":"","package":""}
    try:
        from androguard.core.apk import APK
        apk = APK(apk_path)
        info["name"]    = apk.get_app_name() or ""
        info["version"] = apk.get_androidversion_name() or "1.0"
        info["package"] = apk.get_package() or ""
        min_sdk = apk.get_min_sdk_version()
        if min_sdk:
            info["min_sdk"]     = str(min_sdk)
            info["min_android"] = sdk_to_android(min_sdk)
        icon_name = apk.get_app_icon()
        icon_data = None
        if icon_name and icon_name.endswith('.xml'):
            base = icon_name.split('/')[-1].replace('.xml','')
            possible = [f for f in apk.get_files() if base in f and f.endswith('.png')]
            if possible: icon_data = apk.get_file(sorted(possible)[-1])
        elif icon_name:
            icon_data = apk.get_file(icon_name)
        if not icon_data:
            possible = [f for f in apk.get_files() if ('ic_launcher.png' in f.lower() or 'icon.png' in f.lower()) and 'res/' in f.lower()]
            if possible: icon_data = apk.get_file(sorted(possible)[-1])
        if not icon_data:
            best_size = 0
            for fname in apk.get_files():
                if not fname.endswith('.png'): continue
                try:
                    d = apk.get_file(fname)
                    if d and len(d)>best_size and len(d)>5000: best_size=len(d); icon_data=d
                except: pass
        if icon_data:
            icon_file = os.path.basename(apk_path).replace(".apk",".png")
            icon_path = f"icons/{icon_file}"
            open(icon_path,"wb").write(icon_data)
            info["icon_path"] = icon_path
    except Exception as e:
        print(f"APK extract error: {e}")
    return info

def sync_apks():
    db = load_db()
    existing = {a["file"] for a in db}
    changed = False
    for f in os.listdir("apks"):
        if not f.endswith(".apk") or f in existing: continue
        path = f"apks/{f}"
        info = extract_apk_info(path)
        name = info["name"] or f.replace(".apk","").replace("-"," ").replace("_"," ").title()[:40]
        db.append({"id":len(db)+1,"file":f,"name":name,"icon":"📦",
            "icon_path":info["icon_path"],"package":info["package"],
            "cat":"General","desc":"","color":"#1A1A2E",
            "ver":info["version"],"min_sdk":info["min_sdk"],
            "min_android":info["min_android"],"size":get_size(path),
            "downloads":0,"date":datetime.now().strftime("%Y-%m-%d"),
            "uploader":"admin","status":"approved",
            "slug":make_slug(name,f),"ratings":[],"avg_rating":0.0,"screenshots":[]})
        changed = True
    if changed: save_db(db)
    return db

# ── Auth ──
@app.post("/api/register")
async def register(username:str=Form(...),email:str=Form(...),password:str=Form(...)):
    users = load_users()
    if username in users: raise HTTPException(400,"اسم المستخدم موجود")
    for u,d in users.items():
        if d.get("email")==email: raise HTTPException(400,"البريد مستخدم")
    if len(username)<3: raise HTTPException(400,"اسم قصير")
    if len(password)<6: raise HTTPException(400,"كلمة مرور قصيرة")
    token = md5(username+password+str(datetime.now()))
    users[username] = {"password":md5(password),"email":email,"token":token,"joined":datetime.now().strftime("%Y-%m-%d"),"uploads":0}
    save_users(users)
    return {"success":True,"token":token,"username":username}

@app.post("/api/login")
async def login(email:str=Form(...),password:str=Form(...)):
    users = load_users()
    found = None
    for u,d in users.items():
        if d.get("email")==email: found=(u,d); break
    if not found: raise HTTPException(401,"البريد غير موجود")
    u,d = found
    if d["password"]!=md5(password): raise HTTPException(401,"كلمة مرور خاطئة")
    return {"success":True,"token":d["token"],"username":u}

# ── Apps ──
@app.get("/api/apps")
def api_apps(cat:str=None,search:str=None,page:int=1,limit:int=20):
    apps = [a for a in sync_apks() if a.get("status","approved")=="approved"]
    if cat and cat not in ("All","الكل"): apps=[a for a in apps if a.get("cat")==cat]
    if search:
        s=search.lower(); apps=[a for a in apps if s in a["name"].lower() or s in a.get("desc","").lower()]
    start=(page-1)*limit
    return apps[start:start+limit]

@app.get("/api/app-by-slug/{slug}")
def api_app_by_slug(slug:str):
    db = load_db()
    # البحث بالـ slug أولاً ثم الـ file
    app_data = next((a for a in db if a.get("slug")==slug), None)
    if not app_data:
        app_data = next((a for a in db if a.get("file")==slug), None)
    if not app_data: raise HTTPException(404,"التطبيق غير موجود")
    similar = [a for a in db if a.get("cat")==app_data.get("cat") and a.get("slug")!=slug and a["file"]!=app_data["file"] and a.get("status","approved")=="approved"][:4]
    return {"app":app_data,"similar":similar}

@app.get("/api/pending")
def api_pending(x_admin_token:str=Header("")):
    if not verify_admin(x_admin_token): raise HTTPException(403,"غير مصرح")
    return [a for a in load_db() if a.get("status","approved")=="pending"]

@app.post("/api/approve/{filename}")
def approve_app(filename:str,x_admin_token:str=Header("")):
    if not verify_admin(x_admin_token): raise HTTPException(403,"غير مصرح")
    db=load_db()
    for a in db:
        if a["file"]==filename: a["status"]="approved"
    save_db(db); return {"success":True}

@app.get("/api/stats")
def api_stats():
    stats=load_stats(); apps=sync_apks()
    stats["total_apps"]=len([a for a in apps if a.get("status")=="approved"])
    stats["total_downloads"]=sum(a.get("downloads",0) for a in apps)
    return stats

@app.post("/api/upload")
async def upload_apk(file:UploadFile=File(...),cat:str=Form("General"),desc:str=Form(""),color:str=Form("#1A1A2E"),user_token:str=Form(""),admin_token:str=Form("")):
    is_admin=verify_admin(admin_token)
    username=verify_user_token(user_token)
    if not is_admin and not username: raise HTTPException(403,"يجب تسجيل الدخول")
    if not file.filename.endswith(".apk"): raise HTTPException(400,"يجب أن يكون APK")
    safe=file.filename.replace(" ","_"); path=f"apks/{safe}"
    with open(path,"wb") as f: shutil.copyfileobj(file.file,f)
    info=extract_apk_info(path)
    name=info["name"] or safe.replace(".apk","").replace("-"," ").replace("_"," ").title()[:40]
    db=load_db(); existing=next((a for a in db if a["file"]==safe),None)
    uploader="admin" if is_admin else username
    status="approved" if is_admin else "pending"
    if existing:
        existing.update({"name":name,"cat":cat,"desc":desc,"color":color,"ver":info["version"],"size":get_size(path),"icon_path":info["icon_path"],"min_sdk":info["min_sdk"],"min_android":info["min_android"],"package":info["package"]})
    else:
        db.append({"id":len(db)+1,"file":safe,"name":name,"icon":"📦","icon_path":info["icon_path"],"package":info["package"],"cat":cat,"desc":desc,"color":color,"ver":info["version"],"min_sdk":info["min_sdk"],"min_android":info["min_android"],"size":get_size(path),"downloads":0,"date":datetime.now().strftime("%Y-%m-%d"),"uploader":uploader,"status":status,"slug":make_slug(name,safe),"ratings":[],"avg_rating":0.0,"screenshots":[]})
    save_db(db)
    if username:
        users=load_users()
        if username in users: users[username]["uploads"]=users[username].get("uploads",0)+1; save_users(users)
    return {"success":True,"message":f"تم رفع {safe}" if is_admin else "في انتظار الموافقة ⏳","name":name,"version":info["version"],"min_android":info["min_android"]}

@app.delete("/api/delete/{filename}")
def delete_apk(filename:str,x_admin_token:str=Header("")):
    if not verify_admin(x_admin_token): raise HTTPException(403,"غير مصرح")
    for p in [f"apks/{filename}",f"icons/{filename.replace('.apk','.png')}"]:
        if os.path.exists(p): os.remove(p)
    save_db([a for a in load_db() if a["file"]!=filename])
    return {"success":True}

@app.post("/api/download/{filename}")
def count_download(filename:str):
    db=load_db()
    for a in db:
        if a["file"]==filename: a["downloads"]=a.get("downloads",0)+1
    save_db(db); stats=load_stats()
    stats["total_downloads"]=stats.get("total_downloads",0)+1; save_stats(stats)
    return {"success":True}

# ── Screenshots (Admin only) ──
@app.post("/api/screenshots/{filename}")
async def upload_screenshots(filename:str, files:List[UploadFile]=File(...), x_admin_token:str=Header("")):
    if not verify_admin(x_admin_token): raise HTTPException(403,"فقط الأدمن")
    folder = f"screenshots/{filename}"
    os.makedirs(folder, exist_ok=True)
    # حذف القديمة
    for old in os.listdir(folder): os.remove(f"{folder}/{old}")
    paths = []
    for i,f in enumerate(files):
        path = f"{folder}/{i}_{f.filename}"
        with open(path,"wb") as fp: shutil.copyfileobj(f.file,fp)
        paths.append(path)
    db=load_db()
    for a in db:
        if a["file"]==filename: a["screenshots"]=paths
    save_db(db)
    return {"success":True,"screenshots":paths}

# ── Ratings ──
@app.post("/api/rate/{filename}")
async def rate_app(filename:str,stars:int=Form(...),comment:str=Form(""),username:str=Form("مجهول")):
    if not 1<=stars<=5: raise HTTPException(400,"تقييم غير صالح")
    db=load_db()
    for a in db:
        if a["file"]==filename:
            if "ratings" not in a: a["ratings"]=[]
            a["ratings"].append({"user":username,"stars":stars,"comment":comment,"date":datetime.now().strftime("%Y-%m-%d")})
            a["avg_rating"]=round(sum(r["stars"] for r in a["ratings"])/len(a["ratings"]),1)
    save_db(db); return {"success":True}

@app.get("/api/ratings/{filename}")
def get_ratings(filename:str):
    db=load_db()
    a=next((x for x in db if x["file"]==filename),None)
    if not a: raise HTTPException(404,"غير موجود")
    return {"ratings":a.get("ratings",[]),"avg":a.get("avg_rating",0.0)}

# ── Proxy ──
@app.get("/api/proxy-download")
async def proxy_download(url:str):
    if not url.startswith("http"): raise HTTPException(400,"رابط غير صالح")
    try:
        async with httpx.AsyncClient(follow_redirects=True,timeout=60) as client:
            async with client.stream("GET",url) as response:
                filename=url.split("/")[-1] or "download.apk"
                headers={"Content-Disposition":f'attachment; filename="{filename}"',"Content-Type":"application/vnd.android.package-archive"}
                return StreamingResponse(response.aiter_bytes(),headers=headers,media_type="application/vnd.android.package-archive")
    except Exception as e: raise HTTPException(500,f"فشل: {str(e)}")

app.mount("/apks",StaticFiles(directory="apks"),name="apks")
app.mount("/icons",StaticFiles(directory="icons"),name="icons")
app.mount("/screenshots",StaticFiles(directory="screenshots"),name="screenshots")

@app.get("/app/{slug}",response_class=HTMLResponse)
async def app_page_route(slug:str,request:Request):
    if os.path.exists("app_page.html"):
        with open("app_page.html","r",encoding="utf-8") as f: return f.read()
    return "<script>window.location='/'</script>"

@app.get("/",response_class=HTMLResponse)
async def root(request:Request):
    stats=load_stats(); stats["total_visits"]=stats.get("total_visits",0)+1; save_stats(stats)
    if os.path.exists("store.html"):
        with open("store.html","r",encoding="utf-8") as f: return f.read()
    return "<h1>PhoenixStore</h1>"
