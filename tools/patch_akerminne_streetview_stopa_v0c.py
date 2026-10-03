from pathlib import Path
import sys

ROOT = Path(r"C:\AkerMinne_StreetView_STOPA")
PYFILE = ROOT / "src" / "akerminne_streetview_stopa.py"
BATFILE = ROOT / "RUN_STOPA.bat"

BAT = r'''@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo  AkerMinne x Street View - STOPPUNKT A v0c
echo  Trelleborg 15+5, Skurup 10+5, blind review
echo ============================================================

echo.
python --version >nul 2>&1
if errorlevel 1 (
  echo FEL: Python hittas inte i PATH.
  pause
  exit /b 1
)

python -c "import pandas,requests,geopandas,shapely,pyarrow,dotenv" >nul 2>&1
if errorlevel 1 (
  echo Installerar saknade Python-paket...
  python -m pip install -r requirements_stopa.txt
  if errorlevel 1 goto :fail
)

set "NOAPI="
if exist .env goto :run

echo.
echo Ingen .env hittades.
echo Google-nyckel ger metadata med panorama-datum och battre ranking.
echo Tryck bara ENTER om du vill kora fallback utan API forst.
set "GKEY="
set /p "GKEY=GOOGLE_MAPS_API_KEY: "
if "%GKEY%"=="" goto :noapi
>.env echo GOOGLE_MAPS_API_KEY=%GKEY%
echo .env skapad lokalt. Nyckeln skrivs inte ut.
goto :run

:noapi
set "NOAPI=--no-api"

:run
python src\akerminne_streetview_stopa.py %NOAPI%
if errorlevel 1 goto :fail

start "" "C:\AkerSync-AkerAccess\work\akerminne_streetview_stopa\review.html"
echo.
echo KLART. Review-sidan oppnas nu.
pause
exit /b 0

:fail
echo.
echo KORNINGEN MISSLYCKADES. Kopiera hela CMD-outputen till ChatGPT.
pause
exit /b 1
'''

OLD = '''def candidate_pool(minne: pd.DataFrame, access_gdf):
    merged = minne.merge(access_gdf, on="field_id", how="inner", validate="many_to_one")
    merged = merged[merged["geometry"].notna()].copy()
'''

NEW = '''def candidate_pool(minne: pd.DataFrame, access_gdf):
    # pandas.merge preserves geometry but may return a plain DataFrame, losing CRS metadata.
    access_crs = getattr(access_gdf, "crs", None)
    merged = minne.merge(access_gdf, on="field_id", how="inner", validate="many_to_one")
    merged = merged[merged["geometry"].notna()].copy()
    if gpd is None:
        raise RuntimeError("geopandas saknas efter kandidatjoin.")
    merged = gpd.GeoDataFrame(merged, geometry="geometry", crs=access_crs)
    if merged.crs is None:
        raise ValueError("CRS tappades i ÅkerMinne×ÅkerAccess-joinen; stoppar före Street View-koordinater.")
'''

def fail(msg: str):
    print(f"FEL: {msg}")
    sys.exit(1)

if not ROOT.exists():
    fail(f"Mappen finns inte: {ROOT}")
if not PYFILE.exists():
    fail(f"Python-filen finns inte: {PYFILE}")

text = PYFILE.read_text(encoding="utf-8")
if OLD in text:
    text = text.replace(OLD, NEW, 1)
elif "access_crs = getattr(access_gdf, \"crs\", None)" in text:
    print("CRS-patch finns redan.")
else:
    fail("Känner inte igen candidate_pool() i nuvarande fil. Stoppar utan att ändra Python-koden.")

text = text.replace('"version": "v0a"', '"version": "v0c"')
text = text.replace('"version": "v0b"', '"version": "v0c"')
PYFILE.write_text(text, encoding="utf-8")
BATFILE.write_text(BAT, encoding="utf-8", newline="\r\n")

# Ensure a future git init in this folder won't pick up the key.
gitignore = ROOT / ".gitignore"
existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
if ".env" not in {line.strip() for line in existing.splitlines()}:
    with gitignore.open("a", encoding="utf-8") as f:
        if existing and not existing.endswith("\n"):
            f.write("\n")
        f.write(".env\n")

print("OK: v0c patchad pa plats.")
print(f"  Python: {PYFILE}")
print(f"  Wrapper: {BATFILE}")
print("API-nyckeln har inte lastes eller skrivits ut av patchen.")
