import sys
import platform
import keyring
from datetime import datetime

def ts(format: object = "[%H:%M:%S]") -> str:
    """Gibt aktuelle Zeit als [HH:MM:SS] String zurück für Logging."""
    return datetime.now().strftime(format)

# Plattformabhängige Imports
if platform.system() == "Windows":
    import msvcrt
else:
    import termios
    import tty

def get_input(prompt: str) -> str:
    """Plattformübergreifende Eingabe ohne Cursor-Probleme."""
    sys.stdout.write(prompt)
    sys.stdout.flush()

    if platform.system() == "Windows":
        # Windows: msvcrt
        input_buffer = []
        while True:
            char = msvcrt.getch().decode('utf-8')
            if char == '\r':  # Enter-Taste
                sys.stdout.write('\n')
                sys.stdout.flush()
                return ''.join(input_buffer)
            elif char == '\x08':  # Backspace
                if input_buffer:
                    input_buffer.pop()
                    sys.stdout.write('\b \b')
                    sys.stdout.flush()
            else:
                input_buffer.append(char)
                sys.stdout.write(char)
                sys.stdout.flush()
    else:
        # Linux/macOS: termios
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            input_buffer = []
            while True:
                char = sys.stdin.read(1)
                if char == '\r':  # Enter-Taste
                    sys.stdout.write('\n')
                    sys.stdout.flush()
                    return ''.join(input_buffer)
                elif char == '\x08':  # Backspace
                    if input_buffer:
                        input_buffer.pop()
                        sys.stdout.write('\b \b')
                        sys.stdout.flush()
                else:
                    input_buffer.append(char)
                    sys.stdout.write(char)
                    sys.stdout.flush()
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

def get_password(prompt: str) -> str:
    """Plattformübergreifende Passwort-Eingabe mit Maskierung."""
    sys.stdout.write(prompt)
    sys.stdout.flush()

    if platform.system() == "Windows":
        # Windows: msvcrt
        password_buffer = []
        while True:
            char = msvcrt.getch().decode('utf-8')
            if char == '\r':  # Enter-Taste
                sys.stdout.write('\n')
                sys.stdout.flush()
                return ''.join(password_buffer)
            elif char == '\x08':  # Backspace
                if password_buffer:
                    password_buffer.pop()
                    sys.stdout.write('\b \b')
                    sys.stdout.flush()
            else:
                password_buffer.append(char)
                sys.stdout.write('*')
                sys.stdout.flush()
    else:
        # Linux/macOS: termios
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            password_buffer = []
            while True:
                char = sys.stdin.read(1)
                if char == '\r':  # Enter-Taste
                    sys.stdout.write('\n')
                    sys.stdout.flush()
                    return ''.join(password_buffer)
                elif char == '\x08':  # Backspace
                    if password_buffer:
                        password_buffer.pop()
                        sys.stdout.write('\b \b')
                        sys.stdout.flush()
                else:
                    password_buffer.append(char)
                    sys.stdout.write('*')
                    sys.stdout.flush()
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

def get_credentials(service_name: str = "db_bahn_portal") -> tuple[str, str | None]:
    """Plattformübergreifende Abfrage von Login-Daten."""
    sys.stdout.write("\n=== Login-Daten ===\n")
    sys.stdout.flush()

    last_email = keyring.get_password(service_name, "last_email")
    if last_email:
        sys.stdout.write(f"Zuletzt verwendet: {last_email}\n")
        sys.stdout.flush()
        response = get_input("Verwenden (Enter) oder neu (n)? ")
        if response.strip().lower() == "":
            password = keyring.get_password(service_name, last_email)
            print()
            return last_email, password

    email = get_input("E-Mail: ")
    print()
    existing_password = keyring.get_password(service_name, email)
    if existing_password:
        sys.stdout.write(f"Für {email} ist bereits ein Passwort hinterlegt.\n")
        sys.stdout.flush()
        response = get_input("Vorhandenes Passwort verwenden (Enter) oder neues eingeben (n)? ")
        print()
        if response.strip().lower() == "":
            keyring.set_password(service_name, "last_email", email)
            return email, existing_password

    password = get_password("Passwort: ")
    print()
    keyring.set_password(service_name, email, password)
    keyring.set_password(service_name, "last_email", email)
    return email, password
