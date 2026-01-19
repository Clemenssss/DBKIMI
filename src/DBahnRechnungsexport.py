#push changed files
import os
import time
import datetime
import traceback
from operator import truediv

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


def collect_all_trips(page):
    detailpages = []
    print(f"{ts()} 🔍 DEBUG-MODUS gestartet...")

    try:
        # 1. WICHTIG: Warte, bis die Seite wirklich Daten zeigt
        # Wir warten auf den Container oder die Buttons
        print(f"{ts()} ⏳ Warte auf Bahn-Inhalte (max 10s)...")
        try:
            # Warte bis entweder Reisen da sind ODER der "Weitere"-Button erscheint
            page.wait_for_selector("a.test-reisedetails-button-mobile, button:has-text('Weitere Reisen laden')",
                                   timeout=10000)
        except:
            print(f"{ts()} ⚠️ Timeout: Seite scheint auch nach 10s leer zu sein.")
            page.screenshot(path="debug_timeout_empty.png")
            return []

        # 2. Kurze Verschnaufpause für das Rendering
        page.wait_for_timeout(1000)

        # --- Ab hier dein Klick-Loop ---
        klick_count = 0
        while True:
            # Wir suchen den Button jetzt spezifischer
            btn = page.get_by_role("button", name="Weitere Reisen laden")
            if btn.is_visible():
                btn.scroll_into_view_if_needed()
                btn.click()
                klick_count += 1
                print(f"{ts()}   [{klick_count}] Klick 'Weitere Reisen'...")
                page.wait_for_timeout(2000)  # Zeit zum Nachladen geben
            else:
                break

        # 3. Jetzt erst sammeln
        links = page.locator("a.test-reisedetails-button-mobile").all()
        for link in links:
            href = link.get_attribute("href")
            if href:
                detailpages.append(f"https://www.bahn.de{href}" if href.startswith("/") else href)

        detailpages = list(dict.fromkeys(detailpages))
        print(f"{ts()} ✅ {len(detailpages)} Reisen erfolgreich im Speicher.")

    except Exception as e:
        print(f"{ts()} 🔥 Fehler: {e}")
    finally:
        print(f"{ts()} 🔒 Cleanup: Schließe Browser-Kontext...")
        page.context.close()

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
        # 1. Navigation und Daten auslesen
        try:
            page.goto(url, wait_until="networkidle", timeout=10000)
        except:
            # Falls die Seite gar nicht lädt (Internet/Server-Fehler)
            print(f"{ts()}    ⚠️ Verbindung hakt, versuche Reload...")
            page.wait_for_timeout(2000)
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
#        page.wait_for_selector(".test-auftragsnummer", timeout=30000)
        # Erst sicherstellen, dass das Element nicht nur da ist, sondern auch Text enthält
        page.locator(".test-auftragsnummer").wait_for(state="visible", timeout=60000)

        # Falls das Element leer ist, kurz warten (asynchrones Nachladen)
        if not page.locator(".test-auftragsnummer").inner_text().strip():
            page.wait_for_timeout(2000)
        auftrag = page.locator(".test-auftragsnummer").inner_text().strip()
        datum_raw = page.locator(".test-anlagedatum").inner_text().strip()
        kundenname = page.locator(".test-kundenname").inner_text().strip()

        # Dateinamen erstellen
        lfd_nummer = str(index + 1).zfill(stellen)
        filename = get_download_filename(datum_raw, auftrag, kundenname).replace("RG", f"RG_{lfd_nummer}", 1)
        filepath = os.path.join(DOWNLOAD_DIR, filename)
        print(f"{ts()} 📍 {index + 1}/{total}: Download steht an: {filename}")

        if os.path.exists(filepath):
            print(f"{ts()} ⏭️  {index + 1}/{total}: Bereits vorhanden: {filename}")
            stats["vorhanden"] += 1
            return True

        # 2. Seite verifizieren
        page.locator(".test-breadcrumb-item-text-only", has_text="Reisedetails").wait_for(state="visible", timeout=15000)

        # 3. Locatoren definieren (Role-basiert ist am sichersten!)
        create_btn = page.locator("button.rechnung-abruf__create-rechnung-button").first
        download_btn = page.get_by_role("button", name="Rechnung als PDF herunterladen")

        # 4. Scrollen
        try:
            if download_btn.is_visible():
                download_btn.scroll_into_view_if_needed(timeout=2000)
            else:
                create_btn.scroll_into_view_if_needed(timeout=2000)
        except:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")

        # 5. Rechnung erstellen falls nötig
        if create_btn.is_visible(timeout=3000):
            print(f"{ts()}    ⚙️  Rechnung wird erstellt (Server-Request)...")
            create_btn.click()
            try:
                download_btn.wait_for(state="visible", timeout=30000)
                print(f"{ts()}    ✅ Rechnung wird generiert.")
            except:
                print(f"{ts()}    ⚠️ Rechnung wurde nicht rechtzeitig generiert.")
                return False

        # 6. Der eigentliche Download (jetzt mit Force-Click und JS-Backup)
        try:
            download_btn.wait_for(state="visible", timeout=15000)
            page.wait_for_load_state("networkidle")

            with page.expect_download(timeout=30000) as download_info:
                # Force=True hilft gegen Overlays, die den Klick blockieren
                download_btn.click(force=True, timeout=15000)

            download = download_info.value
            download.save_as(filepath)
            print(f"{ts()}    ✓ Erfolg.")
            stats["neu"] += 1
            return True

        except Exception as e:
            print(f"{ts()}    ⚠️ Normaler Klick fehlgeschlagen, versuche JS-Klick...")
            try:
                with page.expect_download(timeout=20000) as download_info:
                    # Wir klicken den Button direkt via JavaScript
                    page.evaluate("() => { const b = Array.from(document.querySelectorAll('button')).find(el => el.textContent.includes('Rechnung als PDF')); if(b) b.click(); }")
                download = download_info.value
                download.save_as(filepath)
                print(f"{ts()}    ✓ Erfolg (via JS-Klick).")
                stats["neu"] += 1
                return True
            except:
                raise e # Reicht den Fehler an den äußeren Block weiter

    except Exception as e:
        print(f"{ts()}    ✗ Fehler bei Reise {index + 1}: {e}")
        print(f"{ts()}    → URL für manuelle Nacharbeit: {url}")
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

        for i, url in enumerate(detail_urls):
            success = process_single_trip(page, url, i, count, stellen, stats)

            # # Rate Limiting: Pause nach jedem 3. Download
            # if (i + 1) % 3 == 0 and (i + 1) < count:
            #     print(f"{ts()}   ⏸️  Pause (Server-Schonung)...")
            #     page.wait_for_timeout(5000)

            # Bei Fehler: Optional zur Übersicht zurück und neu sammeln
            if not success:
                print(f"{ts()}   ⚠️  Versuche Neustart...")
                page.goto(BASE_URL)
                page.wait_for_timeout(300)  # Extra Pause nach Fehler

        print(f"{ts()}\n--- BERICHT: Neu: {stats['neu']} | Vorhanden: {stats['vorhanden']} | Fehler: {stats['fehler']} ---")
        browser.close()


if __name__ == "__main__":
    run_download()