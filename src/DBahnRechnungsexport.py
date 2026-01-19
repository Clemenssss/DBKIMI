#push changed files
import os
import time
# import datetime
# import traceback
# from operator import truediv

from playwright.sync_api import sync_playwright, TimeoutError
from reusables import get_credentials, ts

# --- 1. KONFIGURATION ---
SERVICE_NAME = "db_bahn_portal"
DOWNLOAD_DIR = "rechnungen"
BASE_URL = "https://www.bahn.de/buchung/reiseuebersicht/vergangene"


# --- 2. HILFSFUNKTIONEN ---

def handle_cookies(page):
    """Versucht Cookie-Popup zu schließen - mehrere Varianten"""
    closed = False

    # Variante 1: Englischer Button (kommt auf dem Screenshot vor!)
    try:
        cookie_btn = page.get_by_role("button", name="Allow all cookies")
        if cookie_btn.is_visible(timeout=1000):
            cookie_btn.click(force=True)
            page.wait_for_timeout(500)
            print(f"{ts()} ✅ Cookie-Popup geschlossen (EN)")
            return True
    except:
        pass

    # Variante 2: Deutscher Button
    try:
        cookie_btn = page.get_by_role("button", name="Alle Cookies zulassen")
        if cookie_btn.is_visible(timeout=1000):
            cookie_btn.click(force=True)
            page.wait_for_timeout(500)
            print(f"{ts()} ✅ Cookie-Popup geschlossen (DE)")
            return True
    except:
        pass

    # Variante 3: JavaScript Fallback
    try:
        js_result = page.evaluate("""
            () => {
                const buttons = Array.from(document.querySelectorAll('button'));
                const cookieBtn = buttons.find(b => {
                    const text = b.textContent.toLowerCase();
                    return (text.includes('allow all') || 
                            text.includes('alle cookies'));
                });
                if (cookieBtn) {
                    cookieBtn.click();
                    return true;
                }
                return false;
            }
        """)
        if js_result:
            page.wait_for_timeout(500)
            print(f"{ts()} ✅ Cookie-Popup geschlossen (JS)")
            return True
    except:
        pass

    return False  # Kein Popup gefunden - aber auch kein Error ausgeben


def load_all_reisen(page):
    print(f"{ts()} 🔄 Starte Nachladen der Liste...")
    klick_limit = 15
    klicks = 0

    while klicks < klick_limit:
        # 1. Ans Ende der Seite scrollen, damit der Button geladen wird
        page.keyboard.press("End")
        page.wait_for_timeout(1500)  # Zeit für die Bahn-Seite zu reagieren

        # 2. Den Button suchen
        # Wir versuchen es mit einer Kombination aus Text und Rolle
        loader_btn = page.get_by_role("button").filter(has_text="Weitere Reisen laden")

        # 3. Prüfen, ob er da ist (wir warten hier kurz explizit)
        if loader_btn.count() > 0 and loader_btn.is_visible():
            print(f"{ts()}   🔘 Klick {klicks + 1}: Lade mehr...")
            loader_btn.scroll_into_view_if_needed()
            loader_btn.click(force=True)

            # Warten, bis der Lade-Indicator (aus deinem Screenshot) weg ist
            page.wait_for_timeout(1000)
            klicks += 1
        else:
            # Sicherheits-Check: Nochmal scrollen, falls er erst jetzt erscheint
            page.keyboard.press("End")
            page.wait_for_timeout(1000)
            if loader_btn.count() == 0:
                print(f"{ts()} ✅ Keine weiteren 'Laden'-Buttons gefunden.")
                break
            klicks += 1  # Falls er doch noch da ist, nächster Durchlauf

def collect_all_trips(page):
    #gemnini 20260119
    detailpages = []
    print(f"{ts()} 🔍 Starte Extraktion (Hypothese: Attribut-Selektor ist stabiler)...")

    try:
        # Kurze Pause, falls Vue.js noch mit dem DOM-Tree beschäftigt ist
        page.wait_for_timeout(2000)
        load_all_reisen(page)
        # Wir suchen nach dem Muster, das wir in deinem Screenshot identifiziert haben
        selector = "a[href*='auftragsnummer=']"

        # Wir warten darauf, dass dieser spezifische Link-Typ erscheint
        print(f"{ts()} ⏳ Suche nach Links mit 'auftragsnummer='...")
        page.wait_for_selector(selector, timeout=12000)

        links_locator = page.locator(selector)
        count = links_locator.count()

        if count == 0:
            print(f"{ts()} ⚠️ Trotz Wartezeit wurden 0 Links mit diesem Muster gefunden.")
            page.screenshot(path="debug_keine_auftragsnummer.png")
        else:
            print(f"{ts()} 📊 {count} potenzielle Reise-Links identifiziert.")

        for i in range(count):
            href = links_locator.nth(i).get_attribute("href")
            if href:
                full_url = f"https://www.bahn.de{href}" if href.startswith("/") else href
                detailpages.append(full_url)

        detailpages = list(dict.fromkeys(detailpages))

    except Exception as e:
        print(f"{ts()} 🔥 Fehler bei der Extraktion: {e}")
        page.screenshot(path="debug_exception.png")

    finally:
        # Der Cleanup-Block, der (wie wir gelernt haben) auch beim Return greift
        # print(f"{ts()} 🔒 Cleanup: Schließe Browser-Kontext...")
        # page.context.close()
        pass

    return detailpages

def get_download_filename(datum_text, auftrag_text,kundenname):
    monate = {
        "Jan": "01", "Feb": "02", "Mär": "03", "Mrz": "03",
        "Apr": "04", "Mai": "05", "Jun": "06", "Jul": "07",
        "Aug": "08", "Sep": "09", "Okt": "10", "Nov": "11", "Dez": "12"
    }
    try:
        # 1. Auftragsnummer säubern
        auftrag_clean = auftrag_text.replace("Auftragsnummer", "").strip()

        # 2. Text in Teile zerlegen
        # Wir entfernen bekannte Füllwörter, damit nur Tag, Monat, Jahr und Name übrig bleiben
        clean_text = datum_text.replace("gebucht am", "").replace("bestellt am", "").replace(".", "").strip()
        teile = [t for t in clean_text.split() if t]
        #breakpoint()
        # 3. Datumsteile extrahieren
        # Wir suchen das Jahr (die erste 4-stellige Zahl von links)
        jahr_index = -1
        for i, teil in enumerate(teile):
            if len(teil) == 4 and teil.isdigit():
                jahr_index = i
                break

        if jahr_index == -1:
            raise ValueError("Kein Jahr im Text gefunden")

        tag = teile[jahr_index - 2].zfill(2)
        monat_str = teile[jahr_index - 1][:3]
        jahr = teile[jahr_index]
        monat_num = monate.get(monat_str, "00")

        # 4. Namen extrahieren (alles nach dem Jahr)
        # Wir nehmen alle Teile nach dem Jahr-Index und fügen sie ohne Leerzeichen zusammen

        name_clean = kundenname.replace(' ','').strip()

        # Ergebnis: RG_2024-706855677982_2024-10-31[Name].pdf
        # Hinweis: Die Endung .pdf wird in 'process_single_trip' für die lfd Nummer ersetzt
        return f"RG_{jahr}-{auftrag_clean}_{jahr}-{monat_num}-{tag}{name_clean}.pdf"

    except Exception as e:
        zeitstempel = time.strftime("%Y%m%d-%H%M%S")
        print(f"{ts()} ⚠️ Namens-Fehler bei '{datum_text}' / '{auftrag_text}': {e}")
        return f"RG_FEHLER_{zeitstempel}.pdf"


def login_to_bahn(page, email, password):
    print(f"{ts()} → Öffne {BASE_URL}...")
    page.goto(BASE_URL)
    handle_cookies(page)
    try:
        page.wait_for_selector("input#username", timeout=15000)
        page.locator("input#username").fill(email)
        page.keyboard.press("Enter")
        page.wait_for_timeout(500)
        handle_cookies(page)
        page.wait_for_selector("input#password", timeout=10000)
        page.locator("input#password").fill(password)
        page.keyboard.press("Enter")
        page.wait_for_timeout(500)
        handle_cookies(page)
        if page.locator("text=Es ist ein Fehler aufgetreten").first.is_visible(timeout=2000):
            page.goto(BASE_URL)
            handle_cookies(page)
        page.wait_for_url("**/vergangene**", timeout=20000)
        print(f"{ts()} ✅ Login erfolgreich.")
        return True
    except Exception as e:
        print(f"{ts()} ❌ Login-Fehler: {e}")
        return False


def process_single_trip(page, url, index, total, stellen, stats):
    try:
        print(f"{ts()} 📍 {index + 1}/{total}: Details")

        # 1. Schnelleres Laden: "domcontentloaded" reicht meistens aus
        try:
            # Wir warten nicht mehr auf 'networkidle', das dauert bei der Bahn zu lange
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
        except Exception:
            print(f"{ts()}    ⚠️ Timeout beim Laden, versuche direkten Zugriff...")
            page.goto(url, wait_until="commit", timeout=30000)

        # 2. Warten auf Kerndaten
        auftrag_locator = page.locator(".test-auftragsnummer")
        auftrag_locator.wait_for(state="attached", timeout=90000)

        # Schneller Check ob Text da ist, sonst Mini-Pause
        if not auftrag_locator.inner_text().strip():
            page.wait_for_timeout(1000)

        auftrag = auftrag_locator.inner_text().strip()
        datum_raw = page.locator(".test-anlagedatum").inner_text().strip()
        kundenname = page.locator(".test-kundenname").inner_text().strip()

        # Dateiname und Existenz-Check
        lfd_nummer = str(index + 1).zfill(stellen)
        filename = get_download_filename(datum_raw, auftrag, kundenname).replace("RG", f"RG_{lfd_nummer}", 1)
        filepath = os.path.join(DOWNLOAD_DIR, filename)

        if os.path.exists(filepath):
            print(f"{ts()} ⏭️  {index + 1}/{total}: Bereits vorhanden: {filename}")
            stats["vorhanden"] += 1
            return True

        print(f"{ts()} 📍 {index + 1}/{total}: Download {filename} vorbereiten...")

        # 3. Download-Logik mit priorisiertem JS-Klick
        # Wir definieren eine Funktion für den Klick, um Code-Duplikate zu vermeiden
        def trigger_download():
            page.evaluate("""() => {
                // Wir nutzen Array.find, um den Button am Text zu erkennen
                const buttons = Array.from(document.querySelectorAll('button'));
                const btn = buttons.find(b => 
                    b.innerText.includes('Rechnung') || 
                    b.classList.contains('rechnung-abruf__create-rechnung-button')
                );
                if (btn) {
                    btn.click();
                    return true;
                }
                return false;
            }""")

        # 4. Falls Button "Rechnung erstellen" da ist
        create_btn = page.locator("button.rechnung-abruf__create-rechnung-button")
        if create_btn.is_visible(timeout=2000):
            print(f"{ts()}    ⚙️  Rechnung wird angefordert...")
            trigger_download()
            page.wait_for_timeout(3000)  # Zeit für Generierung

        # 5. Der eigentliche Download-Klick
        try:
            with page.expect_download(timeout=20000) as download_info:
                # Wir versuchen erst den "sauberen" Klick, falls das Element bereit ist
                download_btn = page.get_by_role("button", name="Rechnung als PDF herunterladen")
                if download_btn.is_visible():
                    print(f"{ts()} 📍 download_btn.is_visible...")
                    download_btn.click(force=True, timeout=5000)
                else:
                    # Sofortiger JS-Backup-Klick
                    print(f"{ts()} 📍 trigger_download()")
                    trigger_download()

            download = download_info.value
            download.save_as(filepath)
            # Prüfung, ob die Datei erfolgreich geschrieben wurde
            if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                print(f"{ts()}    ✓ Erfolg: Datei gespeichert unter '{filepath}'.")
                stats["neu"] += 1
            else:
                print(f"{ts()}    ✗ Fehler: Datei konnte nicht gespeichert werden.")
            return True

        except Exception as e:
            # Letzter Rettungsversuch: Nochmal JS-Klick falls Timeout
            print(f"{ts()}    ⚠️ Timeout beim Download-Event, starte JS-Retry...")
            with page.expect_download(timeout=10000) as download_info:
                trigger_download()
            download = download_info.value
            download.save_as(filepath)
            stats["neu"] += 1
            return True

    except Exception as e:
        print(f"{ts()}    ✗ Fehler bei Reise {index + 1}: {e}")
        stats["fehler"] += 1
        return False
def run_download():
    email, password = get_credentials(SERVICE_NAME)
    stats = {"neu": 0, "vorhanden": 0, "fehler": 0}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=500)
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0")
        page = context.new_page()

        if not login_to_bahn(page, email, password):
            browser.close()
            return

        # Hauptlogik
        # # page again?
        # print(f"{ts()} Reload {BASE_URL}")
        # page.goto(BASE_URL)
        detail_urls = collect_all_trips(page)
        count = len(detail_urls)
        print(f"{ts()} 📊 {count} Reisen gefunden.")

        os.makedirs(DOWNLOAD_DIR, exist_ok=True)

        stellen = len(str(count))  # Gibt 2 bei 52 Reisen, 3 bei 100+
        toDoUrls = detail_urls
        trys = 0.
        maxtrys = 5.
        while len(toDoUrls) > 0 and trys < maxtrys:
            process_urls(count, toDoUrls, page, stats, stellen)
            trys+=1

        print(f"{ts()}\n--- BERICHT: Neu: {stats['neu']} | Vorhanden: {stats['vorhanden']} | Fehler: {stats['fehler']} ---")
        browser.close()


def process_urls(count: int, detail_urls: list, page, stats: dict[str, int], stellen: int):
    unprocessed = []
    print(f"{ts()} Download {len(detail_urls)} Reisen")
    for i, url in enumerate(detail_urls):
        success = process_single_trip(page, url, i, count, stellen, stats)
        if not success:
            unprocessed.append(url)
            print(f"{ts()}   ⚠️  Verarbeite {len(unprocessed)} später {url}...")
    return unprocessed

if __name__ == "__main__":
    run_download()