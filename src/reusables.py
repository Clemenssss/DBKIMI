#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Solarpotenzialanalyse Hamburger Hafen - mit Debugging und Timestamps
"""

import os
import glob
import zipfile
import tempfile
import webbrowser
from datetime import datetime
import geopandas as gpd
import folium

# ============================================================
# LOGGING MIT TIMESTAMP
# ============================================================
def ts(format_str: str = "[%H:%M:%S]") -> str:
    return datetime.now().strftime(format_str)

def log(msg, level="INFO"):
    print(f"{ts()} {level:5} {msg}")

# ============================================================
# HILFSFUNKTIONEN
# ============================================================
def finde_solar_zip(verzeichnis="."):
    """Sucht automatisch nach der Solar-ZIP (case-insensitiv)."""
    pattern = "*solar*.zip"
    treffer = glob.glob(os.path.join(verzeichnis, pattern))
    if treffer:
        return treffer[0]
    # Fallback: alle ZIPs auflisten
    alle_zips = glob.glob(os.path.join(verzeichnis, "*.zip"))
    log(f"Keine Solar-ZIP gefunden. Verfügbare ZIPs: {alle_zips}", "WARN")
    return None

def lade_hafengebiet(pfad_zip="hafengebietsgrenzen_json.zip",
                     datei_in_zip="app_hafengebietsgrenzen_EPSG_25832.json"):
    voller_pfad = f"zip://{pfad_zip}!{datei_in_zip}"
    hafen = gpd.read_file(voller_pfad)
    hafen = hafen.set_crs(25832, allow_override=True)
    log(f"Hafengebiet geladen: {len(hafen)} Polygon(e)")
    return hafen

def lade_solar_daten(zip_pfad):
    """Entpackt ZIP und lädt Gebäude & Dachseiten (25832 und 4326)."""
    ergebnis = {}
    with tempfile.TemporaryDirectory() as tmpdir:
        with zipfile.ZipFile(zip_pfad, 'r') as zf:
            zf.extractall(tmpdir)
            log(f"{zip_pfad} enthält {len(zf.namelist())} Dateien")

        # Alle JSON-Dateien finden
        json_files = []
        for root, dirs, files in os.walk(tmpdir):
            for f in files:
                if f.endswith('.json'):
                    json_files.append(os.path.join(root, f))

        gdf_geb = gdf_geb_wgs = gdf_dach = gdf_dach_wgs = None
        for pfad in json_files:
            name = os.path.basename(pfad)
            if 'gebaeude' in name.lower():
                if '25832' in pfad:
                    gdf_geb = gpd.read_file(pfad)
                    log(f"Gebäude (25832): {len(gdf_geb):,} Objekte")
                elif '4326' in pfad:
                    gdf_geb_wgs = gpd.read_file(pfad)
                    log(f"Gebäude (4326): {len(gdf_geb_wgs):,} Objekte")
            elif 'dachseiten' in name.lower():
                if '25832' in pfad:
                    gdf_dach = gpd.read_file(pfad)
                    log(f"Dachseiten (25832): {len(gdf_dach):,} Objekte")
                elif '4326' in pfad:
                    gdf_dach_wgs = gpd.read_file(pfad)
                    log(f"Dachseiten (4326): {len(gdf_dach_wgs):,} Objekte")

        # Notfalls konvertieren
        if gdf_geb is not None and gdf_geb_wgs is None:
            gdf_geb_wgs = gdf_geb.to_crs(4326)
            log("Gebäude nach WGS84 konvertiert")
        if gdf_dach is not None and gdf_dach_wgs is None:
            gdf_dach_wgs = gdf_dach.to_crs(4326)
            log("Dachseiten nach WGS84 konvertiert")

        ergebnis['gebaeude'] = gdf_geb
        ergebnis['gebaeude_wgs'] = gdf_geb_wgs
        ergebnis['dachseiten'] = gdf_dach
        ergebnis['dachseiten_wgs'] = gdf_dach_wgs
    return ergebnis

# ============================================================
# DEBUG: RÄUMLICHE ÜBERLAPPUNG PRÜFEN
# ============================================================
def debug_ueberlappung(hafen, solar_gdf, name):
    """Prüft BBoxen, führt sjoin durch und gibt Anzahl Schnitte aus."""
    if solar_gdf is None or len(solar_gdf) == 0:
        log(f"{name}: Keine Daten", "WARN")
        return

    # CRS angleichen
    if solar_gdf.crs != hafen.crs:
        solar_gdf = solar_gdf.to_crs(hafen.crs)
        log(f"{name}: CRS an Hafengebiet angepasst")

    # Bounding Boxes
    hafen_bbox = hafen.total_bounds
    solar_bbox = solar_gdf.total_bounds
    log(f"Hafen   BBox: [{hafen_bbox[0]:.1f}, {hafen_bbox[1]:.1f}, {hafen_bbox[2]:.1f}, {hafen_bbox[3]:.1f}]")
    log(f"{name} BBox: [{solar_bbox[0]:.1f}, {solar_bbox[1]:.1f}, {solar_bbox[2]:.1f}, {solar_bbox[3]:.1f}]")

    # Überlappung der BBoxen?
    ueberlappt = not (hafen_bbox[2] < solar_bbox[0] or hafen_bbox[0] > solar_bbox[2] or
                      hafen_bbox[3] < solar_bbox[1] or hafen_bbox[1] > solar_bbox[3])
    log(f"Bounding Boxen überlappen: {ueberlappt}")

    if ueberlappt:
        # Räumlicher Join mit intersects
        join = gpd.sjoin(solar_gdf, hafen, predicate='intersects')
        log(f"Anzahl {name} mit intersects: {len(join)}")
        if len(join) == 0:
            # Test mit 10m Puffer
            hafen_puff = hafen.copy()
            hafen_puff.geometry = hafen_puff.geometry.buffer(10)
            join_puff = gpd.sjoin(solar_gdf, hafen_puff, predicate='intersects')
            log(f"Mit 10m Puffer: {len(join_puff)} Schnitte")
    else:
        log(f"Keine Überlappung der BBoxen – möglicherweise falsches CRS oder Daten außerhalb", "WARN")

def testkarte_mit_rohdaten(hafen_wgs, solar_wgs, name="Solarflächen"):
    """Erstellt eine Karte mit Hafengrenze und einer Stichprobe der Solardaten."""
    zentrum = [hafen_wgs.geometry.centroid.y.mean(), hafen_wgs.geometry.centroid.x.mean()]
    m = folium.Map(location=zentrum, zoom_start=12, tiles='CartoDB positron')
    folium.GeoJson(hafen_wgs, name="Hafengebiet", style_function=lambda x: {"color": "blue", "fillOpacity": 0.1}).add_to(m)
    if solar_wgs is not None and len(solar_wgs) > 0:
        sample = solar_wgs.head(1000)
        folium.GeoJson(sample, name=name, style_function=lambda x: {"color": "red", "weight": 1, "fillOpacity": 0.3}).add_to(m)
    folium.LayerControl().add_to(m)
    out = "test_overlap.html"
    m.save(out)
    webbrowser.open(out)
    log(f"Testkarte mit Rohdaten gespeichert: {out}")

# ============================================================
# VERSCHNEIDUNG (OVERLAY)
# ============================================================
def verschneide_mit_hafen(gdf, hafen_gdf, name="Objekte"):
    if gdf is None or len(gdf) == 0:
        return None
    if gdf.crs != hafen_gdf.crs:
        gdf = gdf.to_crs(hafen_gdf.crs)
    overlay = gpd.overlay(gdf, hafen_gdf, how='intersection')
    log(f"Overlay {name}: {len(overlay)} Objekte im Hafen")
    return overlay

# ============================================================
# HAUPTABLAUF
# ============================================================
def main():
    log("Start Solarpotenzialanalyse Hafen", "INFO")

    # 1. Hafen laden
    hafen = lade_hafengebiet()
    hafen_wgs = hafen.to_crs(4326)

    # 2. Solar-ZIP finden
    zip_pfad = finde_solar_zip()
    if not zip_pfad:
        log("Keine Solar-ZIP gefunden. Abbruch.", "ERROR")
        return
    log(f"Solar-ZIP: {zip_pfad}")

    # 3. Solardaten laden
    solar = lade_solar_daten(zip_pfad)
    if solar.get('gebaeude') is None:
        log("Keine Gebäudedaten in ZIP.", "ERROR")
        return

    # 4. Debug: Räumliche Überprüfung
    log("\n--- Räumliche Überprüfung (Gebäude) ---")
    debug_ueberlappung(hafen, solar['gebaeude'], "Gebäude")
    if solar.get('dachseiten') is not None:
        log("\n--- Räumliche Überprüfung (Dachseiten) ---")
        debug_ueberlappung(hafen, solar['dachseiten'], "Dachseiten")

    # 5. Testkarte mit Rohdaten (nur Hafengrenze + Stichprobe Solar)
    log("\n--- Erstelle Testkarte für visuelle Prüfung ---")
    testkarte_mit_rohdaten(hafen_wgs, solar['gebaeude_wgs'], "Gebäude (erste 1000)")

    # 6. Eigentliche Verschneidung (overlay)
    geb_im_hafen = verschneide_mit_hafen(solar['gebaeude'], hafen, "Gebäude")
    dach_im_hafen = None
    if solar.get('dachseiten') is not None:
        dach_im_hafen = verschneide_mit_hafen(solar['dachseiten'], hafen, "Dachseiten")

    # 7. Abschluss
    if geb_im_hafen is not None and len(geb_im_hafen) > 0:
        log(f"Erfolg: {len(geb_im_hafen)} Gebäude im Hafen gefunden.")
    else:
        log("Verschneidung ergab 0. Bitte Testkarte prüfen!", "WARN")
        log("Tipp: Nutzen Sie ggf. einen Puffer auf die Hafengrenze (z.B. buffer(10)).")

    log("Analyse beendet.")

if __name__ == "__main__":
    main()