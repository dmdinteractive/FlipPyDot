"""
assets.py — Asset library. Stores text presets, processed images, animation configs.
Assets live in assets/ dir as individual JSON files.
"""
import os, json, uuid, logging
from datetime import datetime
log = logging.getLogger(__name__)
ASSETS_DIR = os.path.join(os.path.dirname(__file__),"..","assets")

def _dir(): os.makedirs(ASSETS_DIR,exist_ok=True); return ASSETS_DIR
def _path(aid): return os.path.join(_dir(),f"{aid}.json")

def create(name, asset_type, data, tags=None):
    asset = {"id":str(uuid.uuid4())[:8],"name":name,"type":asset_type,
             "data":data,"tags":tags or [],"created":datetime.now().isoformat(),
             "modified":datetime.now().isoformat()}
    with open(_path(asset["id"]),"w") as f: json.dump(asset,f,indent=2)
    log.info(f"Asset created: {name} [{asset_type}]")
    return asset

def get(asset_id):
    p=_path(asset_id)
    if not os.path.isfile(p): return None
    with open(p) as f: return json.load(f)

def update(asset_id, data):
    asset=get(asset_id)
    if not asset: return None
    asset.update(data); asset["modified"]=datetime.now().isoformat()
    with open(_path(asset_id),"w") as f: json.dump(asset,f,indent=2)
    return asset

def delete(asset_id):
    p=_path(asset_id)
    if os.path.isfile(p): os.remove(p); return True
    return False

def list_all(asset_type=None, tag=None):
    assets=[]
    for fname in sorted(os.listdir(_dir())):
        if not fname.endswith(".json"): continue
        try:
            with open(os.path.join(_dir(),fname)) as f: a=json.load(f)
            if asset_type and a.get("type")!=asset_type: continue
            if tag and tag not in a.get("tags",[]): continue
            # Don't include large image data in list
            summary = {k:v for k,v in a.items() if k!="data"}
            summary["has_data"] = bool(a.get("data"))
            assets.append(summary)
        except: pass
    return assets

def search(query):
    q=query.lower()
    return [a for a in list_all() if q in a.get("name","").lower() or
            any(q in t.lower() for t in a.get("tags",[]))]
