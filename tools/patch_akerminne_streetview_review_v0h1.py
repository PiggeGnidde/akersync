from pathlib import Path
import json
import pandas as pd

OUT = Path(r"C:\AkerSync-AkerAccess\work\akerminne_streetview_historical_hunter_v0h")
CSV = OUT / "selected_truth.csv"
HTML = OUT / "review.html"
BACKUP = OUT / "review_v0h_original.html"

if not CSV.exists():
    raise SystemExit(f"FEL: Hittar inte {CSV}")

df = pd.read_csv(CSV)
need = {"case_id","municipality","year","crop","meta_date","streetview_url"}
missing = need - set(df.columns)
if missing:
    raise SystemExit(f"FEL: selected_truth.csv saknar kolumner: {sorted(missing)}")

if HTML.exists() and not BACKUP.exists():
    BACKUP.write_text(HTML.read_text(encoding="utf-8"), encoding="utf-8")

rows = []
for _, r in df.iterrows():
    year = int(r["year"])
    meta_date = "" if pd.isna(r["meta_date"]) else str(r["meta_date"])
    field_url = ""
    if "field_url" in df.columns and not pd.isna(r.get("field_url")):
        field_url = str(r.get("field_url"))
    rows.append({
        "case_id": str(r["case_id"]),
        "municipality": str(r["municipality"]).title(),
        "year": year,
        "crop": str(r["crop"]),
        "meta_date": meta_date,
        "streetview_url": str(r["streetview_url"]),
        "field_url": field_url,
        "direct": meta_date == f"{year}-05",
    })

data = json.dumps(rows, ensure_ascii=False).replace("</", "<\\/")

template = r"""<!doctype html>
<html lang="sv">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ÅkerMinne × Street View — v0h1</title>
<style>
body{font-family:Arial,Helvetica,sans-serif;margin:0;background:#fafafa;color:#171717}
main{max-width:1080px;margin:24px auto;padding:0 14px}
h1{margin:0 0 4px;font-size:30px}.sub{color:#555;margin-bottom:18px}
.info,.card,#score{background:white;border:1px solid #ddd;border-radius:12px;padding:14px;margin:12px 0}
.top{display:flex;justify-content:space-between;gap:12px;font-weight:700}.meta{margin:6px 0;color:#555}
.warn{background:#fff2cc;border:1px solid #e4c456;border-radius:8px;padding:9px;margin:9px 0}
.ok{background:#eaf7ea;border:1px solid #85bd85;border-radius:8px;padding:9px;margin:9px 0}
.links a{margin-right:12px}button{padding:8px 12px;margin:8px 4px 0 0;border:1px solid #aaa;border-radius:8px;background:#fff;cursor:pointer}
button:disabled{opacity:.35;cursor:not-allowed}button.sel{outline:3px solid #222}.confirm{background:#fff8e6}
.truth{display:none;background:#f0f1f2;border-radius:7px;padding:9px;margin-top:10px}.small{font-size:13px;color:#555}
</style>
</head>
<body><main>
<h1>ÅkerMinne × Street View</h1>
<div class="sub">STOPPUNKT H1 — historisk majvalidering med målårs-spärr</div>
<div class="info">
<b>Viktigt:</b> <i>Nuvarande API-pano</i> är bara den bild Google returnerar idag.
Om årtalet skiljer sig från målåret är bilden <b>inte ground truth</b> för ÅkerMinne.<br>
Öppna Street View → <i>Se fler datum</i> → välj <b>maj under målåret</b>.
Bekräfta sedan detta i kortet. Först då går RAPS / INTE RAPS / OSÄKER att välja.
Finns ingen majbild under målåret: välj <b>INGEN MAJ</b>.<br><br>
<b>RAPS:</b> sammanhängande gul blomning över odlad yta.
<b>Maskrosor:</b> grönt vall/gräs med spridda gula prickar = <b>INTE RAPS</b>.
</div>
<div id="progress" class="info"></div><div id="cards"></div>
<div id="score"><button onclick="reveal()">Avslöja ÅkerMinne och scorea</button>
<button onclick="resetAll()">Nollställ v0h1-svar</button><div id="scoreText" style="margin-top:10px"></div></div>
<script>
const DATA=__DATA__;
const STORE="akerminne_streetview_historical_hunter_v0h1_answers";
let state=JSON.parse(localStorage.getItem(STORE)||"{}");
function save(){localStorage.setItem(STORE,JSON.stringify(state));}
function st(id){if(!state[id]) state[id]={confirmed:false,answer:null}; return state[id];}
function setConfirm(id,v){st(id).confirmed=v;save();render();}
function answer(id,a){
  const row=DATA.find(function(x){return x.case_id===id;});
  if(a!=="INGEN MAJ" && !(row.direct||st(id).confirmed)) return;
  st(id).answer=a;save();render();
}
function esc(s){return String(s==null?"":s).replace(/[&<>"']/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c];});}
function buttonHtml(r,x,a,label,always){
  const verified=r.direct||x.confirmed;
  const dis=(!always&&!verified)?" disabled":"";
  const sel=x.answer===a?" sel":"";
  return '<button'+dis+' class="'+sel+'" onclick="answer(\''+r.case_id+'\',\''+a+'\')">'+label+'</button>';
}
function render(){
  let done=0,usable=0,h="";
  DATA.forEach(function(r){
    const x=st(r.case_id); if(x.answer) done++;
    if(["RAPS","INTE RAPS","OSÄKER"].indexOf(x.answer)>=0) usable++;
    let status="";
    let conf="";
    if(r.direct){
      status='<div class="ok"><b>DIRECT MATCH:</b> aktuellt API-pano är '+esc(r.meta_date)+' = maj målår. Klassificering är giltig direkt.</div>';
    } else {
      status='<div class="warn"><b>OBS:</b> aktuellt API-pano är <b>'+esc(r.meta_date||"okänt")+'</b>, men målåret är <b>'+r.year+'</b>. Bedöm inte detta pano mot ÅkerMinne '+r.year+'.</div>';
      conf='<button class="confirm '+(x.confirmed?'sel':'')+'" onclick="setConfirm(\''+r.case_id+'\','+(!x.confirmed)+')">'+(x.confirmed?'✓ Maj '+r.year+' bekräftad':'Jag har valt MAJ '+r.year+' via Se fler datum')+'</button>';
    }
    const fld=r.field_url?'<a href="'+esc(r.field_url)+'" target="_blank">Visa fältläge ↗</a>':"";
    h+='<div class="card"><div class="top"><span>'+esc(r.case_id)+'</span><span>'+esc(r.municipality)+' · målår '+r.year+'</span></div>'+
       '<div class="meta">Nuvarande API-pano: <b>'+esc(r.meta_date||"okänt")+'</b></div>'+
       '<div class="links"><a href="'+esc(r.streetview_url)+'" target="_blank">Öppna Street View ↗</a>'+fld+'</div>'+
       status+conf+'<br>'+
       buttonHtml(r,x,"RAPS","RAPS",false)+buttonHtml(r,x,"INTE RAPS","INTE RAPS",false)+buttonHtml(r,x,"OSÄKER","OSÄKER",false)+buttonHtml(r,x,"INGEN MAJ","INGEN MAJ",true)+
       '<div class="truth" id="truth_'+r.case_id+'"></div></div>';
  });
  document.getElementById("cards").innerHTML=h;
  document.getElementById("progress").innerHTML='Bedömda <b>'+done+' / '+DATA.length+'</b> · verifierade målårs-majfall: <b>'+usable+'</b>';
}
function reveal(){
  let tp=0,fn=0,unc=0,nomay=0,valid=0;
  DATA.forEach(function(r){
    const x=st(r.case_id), verified=r.direct||x.confirmed;
    const el=document.getElementById("truth_"+r.case_id); el.style.display="block";
    let verdict="INTE VERIFIERAD";
    if(x.answer==="RAPS"&&verified){tp++;valid++;verdict="TRÄFF";}
    else if(x.answer==="INTE RAPS"&&verified){fn++;valid++;verdict="MISS";}
    else if(x.answer==="OSÄKER"&&verified){unc++;verdict="OSÄKER";}
    else if(x.answer==="INGEN MAJ"){nomay++;verdict="EJ BEDÖMBAR";}
    el.innerHTML='ÅkerMinne <b>målår '+r.year+'</b>: <b>'+esc(r.crop)+'</b> — POSITIV höstraps. Ditt svar: <b>'+esc(x.answer||"—")+'</b>. '+verdict+'.';
  });
  const pct=valid?100*tp/valid:0;
  document.getElementById("scoreText").innerHTML='<b>Verifierade binära målårs-majfall: '+valid+'</b> · träff '+tp+' · miss '+fn+' · träffandel '+pct.toFixed(1)+'%<br>Osäkra='+unc+', ingen maj='+nomay+'.<br><span class="small">Endast explicit bekräftade målårs-majbilder scoreas.</span>';
}
function resetAll(){if(confirm("Nollställ alla v0h1-svar?")){state={};save();render();document.getElementById("scoreText").innerHTML="";}}
render();
</script></main></body></html>"""
page = template.replace("__DATA__", data)
HTML.write_text(page, encoding="utf-8")
print("OK: review.html ersatt med v0h1 målårs-spärr.")
print(f"Backup: {BACKUP}")
print(f"Ny sida: {HTML}")
print("Gamla v0h-svar ligger kvar separat och påverkar inte v0h1.")
