from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request, Header
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
import os, json, shutil, hashlib, httpx, re
from datetime import datetime
from typing import Optional, List

app = FastAPI(title="PhoenixStore")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.add_middleware(GZipMiddleware, minimum_size=1000)

ADMIN_TOKEN = os.getenv("PHOENIX_ADMIN_SECRET", "A1s2d3_4")

for d in ["apks","data","icons","screenshots"]:
    os.makedirs(d, exist_ok=True)

DB_FILE    = "data/apps.json"
STATS_FILE = "data/stats.json"
USERS_FILE = "data/users.json"

# ── Cache ──
_db_cache = None
_db_mtime = 0

def load_db():
    global _db_cache, _db_mtime
    try:
        mtime = os.path.getmtime(DB_FILE)
        if _db_cache is not None and mtime == _db_mtime:
            return _db_cache
        with open(DB_FILE,"r",encoding="utf-8") as f:
            _db_cache = json.load(f)
            _db_mtime = mtime
            return _db_cache
    except:
        return []

def save_db(d):
    global _db_cache, _db_mtime
    with open(DB_FILE,"w",encoding="utf-8") as f:
        json.dump(d,f,ensure_ascii=False,indent=2)
    _db_cache = d
    _db_mtime = os.path.getmtime(DB_FILE)

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

# ── Smart Category ──
CAT_KEYWORDS = {
    'Games': ['game','games','play','arcade','puzzle','rpg','racing','sport','chess','sudoku','ninja','angry','birds','temple','run','subway','surfer','hill','climb','jetpack','geometry','dash','cut','rope','talking','tom','pou','fruit'],
    'Browser': ['browser','chrome','firefox','opera','via','dolphin','lightning','uc','web'],
    'Video': ['video','player','vlc','mx','media','youtube','stream','movie','music','mp3','mp4'],
    'Social': ['facebook','twitter','instagram','whatsapp','telegram','chat','messenger','social','tiktok'],
    'Files': ['file','manager','explorer','amaze','root','es','storage','zip','rar'],
    'Security': ['vpn','antivirus','security','firewall','lock','privacy','openvpn'],
}

def guess_category(name, package):
    text = (name + ' ' + package).lower()
    for cat, keywords in CAT_KEYWORDS.items():
        if any(k in text for k in keywords):
            return cat
    return 'General'

def extract_apk_info(apk_path):
    info = {"name":"","icon_path":"","version":"1.0","min_sdk":"","min_android":"","package":""}
    try:
        from pyaxmlparser import APK
        ANDROID = {1:"1.0",2:"1.1",3:"1.5",4:"1.6",5:"2.0",6:"2.0.1",7:"2.1",8:"2.2",9:"2.3",10:"2.3.3",11:"3.0",12:"3.1",13:"3.2",14:"4.0",15:"4.0.3",16:"4.1",17:"4.2",18:"4.3",19:"4.4",20:"4.4W",21:"5.0",22:"5.1",23:"6.0",24:"7.0",25:"7.1",26:"8.0",27:"8.1",28:"9.0",29:"10",30:"11",31:"12",33:"13",34:"14"}
        apk = APK(apk_path)
        info["name"]    = str(apk.get_app_name() or "")
        info["version"] = str(apk.get_androidversion_name() or "1.0")
        info["package"] = str(apk.get_package() or "")
        sdk = apk.get_min_sdk_version() or ""
        info["min_sdk"] = str(sdk)
        try: info["min_android"] = ANDROID.get(int(sdk), str(sdk))
        except: pass
        try:
            if apk.icon_data:
                fname = os.path.basename(apk_path).replace(".apk",".png")
                out = f"icons/{fname}"
                open(out,"wb").write(apk.icon_data)
                info["icon_path"] = out
        except: pass
    except Exception as e:
        print(f"APK extract error: {e}")
    return info

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
def api_apps(cat:str=None,search:str=None,page:int=1,limit:int=20,sort:str="date"):
    apps = [a for a in load_db() if a.get("status","approved")=="approved"]
    # بحث
    if search:
        s=search.lower()
        apps=[a for a in apps if s in a["name"].lower() or s in a.get("desc","").lower() or s in a.get("package","").lower()]
    # فلتر
    if cat and cat not in ("All","الكل"):
        apps=[a for a in apps if a.get("cat")==cat]
    # ترتيب
    if sort=="downloads":
        apps.sort(key=lambda x:x.get("downloads",0),reverse=True)
    elif sort=="name":
        apps.sort(key=lambda x:x.get("name","").lower())
    elif sort=="size":
        apps.sort(key=lambda x:float(x.get("size","0 MB").split()[0]) if x.get("size","?")!="?" else 0,reverse=True)
    # pagination
    total = len(apps)
    start=(page-1)*limit
    return {"apps":apps[start:start+limit],"total":total,"page":page,"pages":(total+limit-1)//limit}

@app.get("/api/app-by-slug/{slug}")
def api_app_by_slug(slug:str):
    db = load_db()
    app_data = next((a for a in db if a.get("slug")==slug), None)
    if not app_data:
        app_data = next((a for a in db if a.get("file")==slug), None)
    if not app_data: raise HTTPException(404,"التطبيق غير موجود")
    similar = [a for a in db if a.get("cat")==app_data.get("cat") and a.get("slug")!=slug and a["file"]!=app_data["file"] and a.get("status","approved")=="approved"][:4]
    return {"app":app_data,"similar":similar}

@app.get("/api/stats")
def api_stats():
    stats=load_stats()
    db=load_db()
    stats["total_apps"]=len([a for a in db if a.get("status","approved")=="approved"])
    stats["total_downloads"]=sum(a.get("downloads",0) for a in db)
    return stats

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

@app.post("/api/upload")
async def upload_apk(file:UploadFile=File(...),cat:str=Form(""),desc:str=Form(""),color:str=Form("#1A1A2E"),user_token:str=Form(""),admin_token:str=Form("")):
    is_admin=verify_admin(admin_token)
    username=verify_user_token(user_token)
    if not is_admin and not username: raise HTTPException(403,"يجب تسجيل الدخول")
    if not file.filename.endswith(".apk"): raise HTTPException(400,"يجب أن يكون APK")
    safe=file.filename.replace(" ","_"); path=f"apks/{safe}"
    with open(path,"wb") as f: shutil.copyfileobj(file.file,f)
    info=extract_apk_info(path)
    name=info["name"] or safe.replace(".apk","").replace("-"," ").replace("_"," ").title()[:40]
    # تصنيف تلقائي
    auto_cat = cat if cat else guess_category(name, info.get("package",""))
    db=load_db(); existing=next((a for a in db if a["file"]==safe),None)
    uploader="admin" if is_admin else username
    status="approved" if is_admin else "pending"
    if existing:
        existing.update({"name":name,"cat":auto_cat,"desc":desc,"color":color,"ver":info["version"],"size":get_size(path),"icon_path":info["icon_path"],"min_sdk":info["min_sdk"],"min_android":info["min_android"],"package":info["package"]})
    else:
        db.append({"id":len(db)+1,"file":safe,"name":name,"icon":"📦","icon_path":info["icon_path"],"package":info["package"],"cat":auto_cat,"desc":desc,"color":color,"ver":info["version"],"min_sdk":info["min_sdk"],"min_android":info["min_android"],"size":get_size(path),"downloads":0,"date":datetime.now().strftime("%Y-%m-%d"),"uploader":uploader,"status":status,"slug":make_slug(name,safe),"ratings":[],"avg_rating":0.0,"screenshots":[]})
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

@app.post("/api/screenshots/{filename}")
async def upload_screenshots(filename:str,files:List[UploadFile]=File(...),x_admin_token:str=Header("")):
    if not verify_admin(x_admin_token): raise HTTPException(403,"فقط الأدمن")
    folder=f"screenshots/{filename}"; os.makedirs(folder,exist_ok=True)
    for old in os.listdir(folder): os.remove(f"{folder}/{old}")
    paths=[]
    for i,f in enumerate(files):
        path=f"{folder}/{i}_{f.filename}"
        with open(path,"wb") as fp: shutil.copyfileobj(f.file,fp)
        paths.append(path)
    db=load_db()
    for a in db:
        if a["file"]==filename: a["screenshots"]=paths
    save_db(db)
    return {"success":True,"screenshots":paths}

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

# ── Sitemap ──
@app.get("/sitemap.xml")
def sitemap(request:Request):
    db=load_db()
    base=str(request.base_url).rstrip('/')
    urls=[f"<url><loc>{base}/</loc></url>"]
    for a in db[:500]:
        if a.get("slug"):
            urls.append(f"<url><loc>{base}/app/{a['slug']}</loc></url>")
    xml=f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{"".join(urls)}</urlset>'
    from fastapi.responses import Response
    return Response(content=xml,media_type="application/xml")

# ── PWA ──
@app.get("/manifest.json")
def pwa_manifest():
    return JSONResponse({"name":"PhoenixStore","short_name":"Phoenix","description":"Free APK store for old Android devices","start_url":"/","display":"standalone","background_color":"#F2F2F7","theme_color":"#FF4500","icons":[{"src":"/icons/icon-192.png","sizes":"192x192","type":"image/png"},{"src":"/icons/icon-512.png","sizes":"512x512","type":"image/png"}]})

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
