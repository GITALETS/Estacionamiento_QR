"""
ESTACIONAMIENTO CON QR - PROGRAMA DE LA LAPTOP (ticket en el celular)
---------------------------------------------------------------------
Sin impresora: el ticket se guarda en el celular del conductor.

ENTRADA
  1. El Arduino avisa que llegó un auto (CARRO_ENTRADA).
  2. La pantalla de la laptop muestra un QR.
  3. El conductor lo escanea con la cámara de su celular y se abre su
     ticket (otro QR) en el navegador. También puede tomarle una foto.
  4. La pluma de entrada sube cuando el celular abre el ticket,
     o a los ESPERA_ENTRADA segundos.

SALIDA
  El conductor muestra su ticket al lector QR USB. Si es válido,
  se invalida y sube la pluma de salida.

Uso:
    python estacionamiento_laptop_v2.py
    Luego abre en la laptop:  http://localhost:8000/pantalla   (pantalla completa con F11)

IMPORTANTE
  - Laptop y celulares deben estar en la misma red Wi-Fi (lo más fácil:
    activar el punto de acceso de la laptop o el de un celular).
  - El lector QR escribe en la ventana activa: deja seleccionada la
    ventana de ESTE programa (la terminal), no el navegador.
"""

import asyncio
import io
import json
import os
import re
import secrets
import socket
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import qrcode
import serial
import serial.tools.list_ports

# ======================= CONFIGURACIÓN =======================
PUERTO_ARDUINO = None     # None = detectar solo. Ej: "COM3"
BAUDIOS = 9600
PUERTO_WEB = 8000
IP_LAPTOP = None          # None = detectar sola. Ej: "192.168.137.1"
URL_PUBLICA = None        # Opcional: URL de túnel público (ej: "https://xxxx.trycloudflare.com" o ngrok)
MAX_LUGARES = 20
ESPERA_ENTRADA = 20       # segundos máximos antes de subir la pluma de entrada
ARCHIVO_TICKETS = "tickets.json"
# =============================================================

PATRON_CODIGO = re.compile(r"PK\d{10}")


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def ip_local():
    if IP_LAPTOP:
        return IP_LAPTOP
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # no envía nada; solo elige la interfaz
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


# ======================= TICKETS =======================
class BaseTickets:
    def __init__(self, archivo):
        self.archivo = archivo
        self.candado = threading.Lock()
        self.datos = {}
        if os.path.exists(archivo):
            with open(archivo, encoding="utf-8") as f:
                self.datos = json.load(f)

    def _guardar(self):
        tmp = self.archivo + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.datos, f, indent=2, ensure_ascii=False)
        os.replace(tmp, self.archivo)

    def activos(self):
        with self.candado:
            return sum(1 for t in self.datos.values() if t["estado"] == "activo")

    def obtener(self, codigo):
        with self.candado:
            t = self.datos.get(codigo)
            return dict(t) if t else None

    def nuevo(self):
        # Solo letras y números: el lector USB escribe como teclado en inglés
        with self.candado:
            while True:
                codigo = "PK" + "".join(str(secrets.randbelow(10)) for _ in range(10))
                if codigo not in self.datos:
                    break
            self.datos[codigo] = {"estado": "activo", "entrada": datetime.now().isoformat(timespec="seconds"),
                                  "en_celular": False}
            self._guardar()
            return codigo

    def marcar_en_celular(self, codigo):
        with self.candado:
            t = self.datos.get(codigo)
            if t and not t.get("en_celular"):
                t["en_celular"] = True
                self._guardar()
                return True
            return False

    def validar_y_usar(self, codigo):
        with self.candado:
            t = self.datos.get(codigo)
            if t is None:
                return False, "Ticket no registrado"
            if t["estado"] != "activo":
                return False, f"Ticket ya usado (salió a las {t.get('salida', '?')[11:19]})"
            t["estado"] = "usado"
            t["salida"] = datetime.now().isoformat(timespec="seconds")
            self._guardar()
            return True, f"Ticket válido (entró a las {t['entrada'][11:19]})"


# ======================= PANTALLA (estado compartido) =======================
class Pantalla:
    def __init__(self):
        self.candado = threading.Lock()
        self.estado = {"modo": "espera", "mensaje": "", "codigo": "", "url": "", "libres": MAX_LUGARES, "n": 0}

    def poner(self, **k):
        with self.candado:
            self.estado.update(k)
            self.estado["n"] += 1

    def leer(self):
        with self.candado:
            return dict(self.estado)


# ======================= PÁGINAS WEB =======================
CSS = """
*{box-sizing:border-box}body{margin:0;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
background:#1b2a41;color:#fff;min-height:100vh;display:flex;align-items:center;justify-content:center;text-align:center}
.card{background:#fff;color:#1b2a41;border-radius:22px;padding:28px 24px;width:min(92vw,560px);box-shadow:0 10px 40px rgba(0,0,0,.35)}
h1{margin:0 0 6px;font-size:clamp(26px,5vw,40px)}p{margin:6px 0;font-size:clamp(16px,3vw,20px);color:#4d5d72}
img{width:min(78vw,380px);height:auto;image-rendering:pixelated;margin:14px auto;display:block}
.code{font:700 clamp(22px,5vw,34px) ui-monospace,Consolas,monospace;letter-spacing:2px;color:#1b2a41}
.sign{display:inline-block;background:#f2b705;color:#1b2a41;font-weight:800;border-radius:10px;padding:6px 14px;margin-bottom:12px;border:3px solid #1b2a41}
.ok{color:#1f8a4c}.bad{color:#c62828}.big{font-size:clamp(70px,14vw,120px);font-weight:800;color:#1b2a41;line-height:1}
"""

PAGINA_PANTALLA = """<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Estacionamiento</title>
<style>""" + CSS + """</style></head><body><div class="card" id="c">Cargando…</div>
<script>
let n=-1;
async function tick(){
  try{const r=await fetch('/api/estado');const e=await r.json();
    if(e.n!==n){n=e.n;pintar(e);}}catch(err){}
  setTimeout(tick,700);
}
function pintar(e){
  const c=document.getElementById('c');
  if(e.modo==='ticket'){
    c.innerHTML='<div class="sign">🅿️ BIENVENIDO</div><h1>Escanea con tu celular</h1>'+
      '<p>Abre la cámara y apunta a este código para guardar tu ticket.</p>'+
      '<img src="/qr?d='+encodeURIComponent(e.url)+'" alt="QR del ticket">'+
      '<div class="code">'+e.codigo+'</div><p>¿Sin internet? Tómale una foto a este QR.</p>';
  }else if(e.modo==='salida_ok'){
    c.innerHTML='<div class="big ok">✓</div><h1 class="ok">¡Buen viaje!</h1><p>'+e.mensaje+'</p>';
  }else if(e.modo==='salida_mal'){
    c.innerHTML='<div class="big bad">✕</div><h1 class="bad">Ticket no válido</h1><p>'+e.mensaje+'</p>';
  }else if(e.modo==='lleno'){
    c.innerHTML='<div class="sign">🅿️ ESTACIONAMIENTO</div><h1 class="bad">LLENO</h1><p>No hay lugares disponibles.</p>';
  }else{
    c.innerHTML='<div class="sign">🅿️ ESTACIONAMIENTO</div><div class="big">'+e.libres+'</div>'+
      '<h1>lugares libres</h1><p>Acerca tu auto a la pluma para obtener tu ticket.</p>';
  }
}
tick();
</script></body></html>"""


def pagina_ticket(codigo, t):
    if t is None:
        cuerpo = '<h1 class="bad">Ticket no encontrado</h1><p>Revisa el enlace o pide ayuda.</p>'
    elif t["estado"] != "activo":
        cuerpo = (f'<div class="sign">🅿️ TICKET</div><h1>Ticket usado</h1><div class="code">{codigo}</div>'
                  f'<p>Saliste a las {t.get("salida", "?")[11:16]}. ¡Gracias!</p>')
    else:
        cuerpo = (f'<div class="sign">🅿️ TU TICKET</div><h1>Estacionamiento</h1>'
                  f'<p>Entrada: {t["entrada"][8:10]}/{t["entrada"][5:7]} a las {t["entrada"][11:16]}</p>'
                  f'<img src="/qr?d={codigo}" alt="QR de tu ticket"><div class="code">{codigo}</div>'
                  '<p><b>Al salir, muestra este QR al lector.</b></p>'
                  '<p>Sube el brillo de tu pantalla. Toma una captura por si pierdes la conexión.</p>')
    return ('<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1"><title>Mi ticket</title>'
            f'<style>{CSS}</style></head><body><div class="card">{cuerpo}</div></body></html>')


def png_qr(texto):
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=2)
    qr.add_data(texto)
    qr.make(fit=True)
    buf = io.BytesIO()
    qr.make_image(fill_color="black", back_color="white").save(buf, format="PNG")
    return buf.getvalue()


def crear_servidor(base, pantalla, avisar_celular):
    class Manejador(BaseHTTPRequestHandler):
        def _enviar(self, codigo, tipo, cuerpo):
            if isinstance(cuerpo, str):
                cuerpo = cuerpo.encode("utf-8")
            self.send_response(codigo)
            self.send_header("Content-Type", tipo)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(cuerpo)))
            self.end_headers()
            self.wfile.write(cuerpo)

        def do_GET(self):
            u = urlparse(self.path)
            if u.path in ("/", "/pantalla"):
                self._enviar(200, "text/html; charset=utf-8", PAGINA_PANTALLA)
            elif u.path == "/api/estado":
                self._enviar(200, "application/json", json.dumps(pantalla.leer()))
            elif u.path == "/qr":
                d = parse_qs(u.query).get("d", [""])[0][:200]
                self._enviar(200, "image/png", png_qr(d or "-"))
            elif u.path.startswith("/t/"):
                codigo = u.path[3:].upper()
                t = base.obtener(codigo) if PATRON_CODIGO.fullmatch(codigo) else None
                if t and t["estado"] == "activo":
                    avisar_celular(codigo)
                self._enviar(200, "text/html; charset=utf-8", pagina_ticket(codigo, t))
            else:
                self._enviar(404, "text/plain; charset=utf-8", "No encontrado")

        def log_message(self, *args):
            pass  # silencia el registro del servidor

    servidor = ThreadingHTTPServer(("0.0.0.0", PUERTO_WEB), Manejador)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    return servidor


# ======================= ARDUINO (SERIAL) =======================
def encontrar_puerto():
    if PUERTO_ARDUINO:
        return PUERTO_ARDUINO
    puertos = list(serial.tools.list_ports.comports())
    for p in puertos:
        texto = f"{p.description} {p.manufacturer or ''}".lower()
        if any(k in texto for k in ("arduino", "ch340", "ch341", "usb serial", "usb-serial", "wch")):
            return p.device
    return puertos[0].device if len(puertos) == 1 else None


class Arduino:
    def __init__(self, puerto):
        self.ser = serial.Serial(puerto, BAUDIOS, timeout=0.5)
        time.sleep(2)  # el Arduino se reinicia al abrir el puerto
        self.candado = threading.Lock()

    def enviar(self, orden):
        with self.candado:
            self.ser.write((orden + "\n").encode())
        log(f"→ Arduino: {orden}")

    def leer_en_hilo(self, cola, loop):
        def hilo():
            while True:
                try:
                    linea = self.ser.readline().decode(errors="ignore").strip()
                except serial.SerialException as e:
                    loop.call_soon_threadsafe(cola.put_nowait, ("error", str(e)))
                    return
                if linea:
                    loop.call_soon_threadsafe(cola.put_nowait, ("arduino", linea))
        threading.Thread(target=hilo, daemon=True).start()


def leer_lector_en_hilo(cola, loop):
    """El lector USB escribe el código y presiona Enter, como un teclado."""
    def hilo():
        for linea in sys.stdin:
            texto = linea.strip().upper()
            if texto:
                loop.call_soon_threadsafe(cola.put_nowait, ("lector", texto))
    threading.Thread(target=hilo, daemon=True).start()


# ======================= LÓGICA PRINCIPAL =======================
class Sistema:
    def __init__(self, arduino, base, pantalla, url_base):
        self.arduino = arduino
        self.base = base
        self.pantalla = pantalla
        self.url_base = url_base
        self.pendiente = None            # (codigo, asyncio.Event) del auto en la entrada
        self.tarea_volver = None

    def libres(self):
        return max(0, MAX_LUGARES - self.base.activos())

    def volver_a_espera(self, segundos):
        if self.tarea_volver:
            self.tarea_volver.cancel()

        async def esperar():
            await asyncio.sleep(segundos)
            self.pantalla.poner(modo="espera", libres=self.libres())
        self.tarea_volver = asyncio.create_task(esperar())

    async def atender_entrada(self):
        if self.pendiente:
            return
        if self.base.activos() >= MAX_LUGARES:
            log("Estacionamiento LLENO: no se abre la entrada.")
            self.pantalla.poner(modo="lleno")
            self.arduino.enviar("LLENO")
            self.volver_a_espera(8)
            return
        codigo = self.base.nuevo()
        url = f"{self.url_base}/t/{codigo}"
        evento = asyncio.Event()
        self.pendiente = (codigo, evento)
        if self.tarea_volver:
            self.tarea_volver.cancel()
        self.pantalla.poner(modo="ticket", codigo=codigo, url=url, libres=self.libres())
        log(f"Ticket generado: {codigo}  → {url}")
        try:
            await asyncio.wait_for(evento.wait(), timeout=ESPERA_ENTRADA)
            log(f"El celular abrió el ticket {codigo}.")
        except asyncio.TimeoutError:
            log(f"Pasaron {ESPERA_ENTRADA} s (el conductor pudo tomar foto del QR).")
        self.arduino.enviar("ABRIR_ENTRADA")
        self.pendiente = None
        self.volver_a_espera(6)

    def celular_abrio(self, codigo):
        nuevo = self.base.marcar_en_celular(codigo)
        if nuevo:
            log(f"Ticket {codigo} guardado en un celular.")
        if self.pendiente and self.pendiente[0] == codigo:
            self.pendiente[1].set()

    def atender_salida(self, texto):
        m = PATRON_CODIGO.search(texto)   # acepta el código solo o dentro del enlace
        if not m:
            log(f"Lectura no reconocida: {texto!r}")
            self.pantalla.poner(modo="salida_mal", mensaje="Ese código no es de este estacionamiento.")
            self.volver_a_espera(5)
            return
        codigo = m.group(0)
        ok, mensaje = self.base.validar_y_usar(codigo)
        if ok:
            log(f"SALIDA {codigo}: {mensaje}. Ticket invalidado.")
            self.arduino.enviar("ABRIR_SALIDA")
            self.pantalla.poner(modo="salida_ok", mensaje=mensaje, libres=self.libres())
        else:
            log(f"SALIDA {codigo}: RECHAZADO. {mensaje}.")
            self.pantalla.poner(modo="salida_mal", mensaje=mensaje)
        self.volver_a_espera(5)

    async def ejecutar(self):
        loop = asyncio.get_running_loop()
        cola = asyncio.Queue()
        self.arduino.leer_en_hilo(cola, loop)
        leer_lector_en_hilo(cola, loop)
        self.pantalla.poner(modo="espera", libres=self.libres())
        while True:
            origen, texto = await cola.get()
            if origen == "arduino":
                log(f"← Arduino: {texto}")
                if texto == "CARRO_ENTRADA":
                    asyncio.create_task(self.atender_entrada())
            elif origen == "celular":
                self.celular_abrio(texto)
            elif origen == "lector":
                self.atender_salida(texto)
            elif origen == "error":
                log(f"Se perdió la conexión con el Arduino: {texto}")
                return


async def principal():
    base = BaseTickets(ARCHIVO_TICKETS)
    pantalla = Pantalla()
    loop = asyncio.get_running_loop()
    sistema_ref = {}

    def avisar_celular(codigo):
        s = sistema_ref.get("s")
        if s:
            loop.call_soon_threadsafe(s.celular_abrio, codigo)

    crear_servidor(base, pantalla, avisar_celular)
    if URL_PUBLICA:
        url_base = URL_PUBLICA.rstrip("/")
    else:
        url_base = f"http://{ip_local()}:{PUERTO_WEB}"

    log(f"Pantalla de entrada: http://localhost:{PUERTO_WEB}/pantalla  (ábrela y presiona F11)")
    log(f"Los celulares abrirán los tickets en: {url_base}")
    if not URL_PUBLICA and (ip_local() == "127.0.0.1" or ip_local().startswith("192.168.")):
        log("AVISO: Para que el celular abra el QR, debe estar en la misma red Wi-Fi o usa un túnel (ej. Cloudflare/ngrok).")

    puerto = encontrar_puerto()
    if not puerto:
        log("No encontré el Arduino. Escribe el puerto en PUERTO_ARDUINO (ej. 'COM3').")
        return
    log(f"Conectando con el Arduino en {puerto}…")
    arduino = Arduino(puerto)
    sistema = Sistema(arduino, base, pantalla, url_base)
    sistema_ref["s"] = sistema
    log(f"Sistema listo. Lugares libres: {sistema.libres()}/{MAX_LUGARES}")
    log("Deja ESTA ventana seleccionada para que el lector QR escriba aquí.")
    await sistema.ejecutar()


if __name__ == "__main__":
    try:
        asyncio.run(principal())
    except KeyboardInterrupt:
        print("\nSistema detenido.")
