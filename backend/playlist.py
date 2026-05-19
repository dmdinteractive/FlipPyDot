"""
playlist.py — Professional playlist with three playback modes.
sequential / shuffle / weighted
"""
import threading, random, time, uuid, logging
log = logging.getLogger(__name__)

class PlaylistItem:
    def __init__(self, content_type="clear", content=None,
                 label="", duration=5.0, weight=1.0):
        self.id=str(uuid.uuid4())[:8]; self.content_type=content_type
        self.content=content or {}; self.label=label
        self.duration=float(duration); self.weight=max(0.1,float(weight))
        self.play_count=0
    def to_dict(self):
        return {"id":self.id,"content_type":self.content_type,"content":self.content,
                "label":self.label,"duration":self.duration,"weight":self.weight,
                "play_count":self.play_count}
    @classmethod
    def from_dict(cls,d):
        item=cls(d.get("content_type","clear"),d.get("content",{}),
                 d.get("label",""),float(d.get("duration",5)),float(d.get("weight",1)))
        item.id=d.get("id",item.id); item.play_count=d.get("play_count",0); return item

class Playlist:
    SEQUENTIAL="sequential"; SHUFFLE="shuffle"; WEIGHTED="weighted"
    def __init__(self,execute_fn):
        self._execute=execute_fn; self.items=[]; self.mode=self.SEQUENTIAL
        self.running=False; self.current_idx=-1; self.current_item=None
        self._thread=None; self._stop=threading.Event(); self._last_idx=-1
    def add(self,item): self.items.append(item); return item
    def remove(self,item_id): self.items=[i for i in self.items if i.id!=item_id]
    def update(self,item_id,data):
        for item in self.items:
            if item.id==item_id:
                for k,v in data.items():
                    if hasattr(item,k): setattr(item,k,v)
                return item
    def move(self,item_id,direction):
        for i,item in enumerate(self.items):
            if item.id==item_id:
                j=i-1 if direction=="up" else i+1
                if 0<=j<len(self.items): self.items[i],self.items[j]=self.items[j],self.items[i]; return True
    def start(self,mode=None):
        if mode: self.mode=mode
        if self.running or not self.items: return
        self.running=True; self._stop.clear()
        self._thread=threading.Thread(target=self._loop,daemon=True); self._thread.start()
    def stop(self): self.running=False; self._stop.set(); self.current_item=None
    def skip(self):
        self._stop.set(); time.sleep(0.05)
        if self.running: self._stop.clear()
    def _loop(self):
        while self.running:
            item=self._pick()
            if not item: break
            self.current_item=item; item.play_count+=1
            try: self._execute(item)
            except Exception as e: log.error(f"Playlist: {e}")
            start=time.time()
            while time.time()-start<item.duration:
                if self._stop.is_set(): break
                time.sleep(0.05)
            if self._stop.is_set() and not self.running: break
            self._stop.clear()
        self.running=False
    def _pick(self):
        if not self.items: return None
        if self.mode==self.SEQUENTIAL:
            self.current_idx=(self.current_idx+1)%len(self.items)
            return self.items[self.current_idx]
        elif self.mode==self.SHUFFLE:
            cands=[i for i in range(len(self.items)) if i!=self._last_idx]
            if not cands: cands=list(range(len(self.items)))
            self.current_idx=random.choice(cands); self._last_idx=self.current_idx
            return self.items[self.current_idx]
        elif self.mode==self.WEIGHTED:
            total=sum(i.weight for i in self.items); r,run=random.uniform(0,total),0
            for i,item in enumerate(self.items):
                run+=item.weight
                if r<=run: self.current_idx=i; return item
            return self.items[-1]
    def get_status(self):
        return {"running":self.running,"mode":self.mode,"item_count":len(self.items),
                "current_idx":self.current_idx,
                "current_item":self.current_item.to_dict() if self.current_item else None,
                "items":[i.to_dict() for i in self.items]}
    def to_list(self): return [i.to_dict() for i in self.items]
    def from_list(self,data): self.items=[PlaylistItem.from_dict(d) for d in data]
