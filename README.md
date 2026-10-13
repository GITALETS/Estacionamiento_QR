# 🚗 Sistema de Estacionamiento Inteligente con QR y Arduino

Sistema de control de acceso y estacionamiento automatizado utilizando **Arduino Uno**, control por servomotores, sensores infrarrojos (FC-51), lector de código de barras/QR USB y emisión de **tickets digitales en el celular** a través de código QR (sin necesidad de impresora térmica).

---

## 📋 Características

- **Entrada automatizada**:
  1. Sensor infrarrojo detecta la llegada de un vehículo (`CARRO_ENTRADA`).
  2. La pantalla de la laptop genera y muestra un código QR único con el ticket.
  3. El conductor escanea el QR con la cámara de su celular y el ticket se abre directamente en su navegador web.
  4. Al abrirse el ticket en el celular (o al cumplirse el tiempo de espera), la pluma de entrada sube automáticamente.
- **Salida automatizada**:
  1. El conductor muestra el ticket digital (QR) al lector QR USB en la salida.
  2. El sistema valida si el ticket está activo, lo marca como usado e invalida futuras lecturas.
  3. La pluma de salida sube automáticamente.
- **Control de aforo**:
  - Monitorea lugares disponibles en tiempo real.
  - Al llenarse el estacionamiento, muestra aviso de **LLENO** y bloquea la entrada.

---

## 🔌 Conexiones de Hardware (Arduino Uno)

| Componente | Pin Arduino | Notas |
| :--- | :--- | :--- |
| **Sensor IR Entrada** (OUT) | `D2` | FC-51 (señal digital LOW al detectar) |
| **Sensor IR Salida** (OUT) | `D3` | FC-51 (señal digital LOW al detectar) |
| **Servo Entrada** (Señal) | `D9` | Control de pluma de entrada |
| **Servo Salida** (Señal) | `D5` | Control de pluma de salida |
| **Alimentación Servos** | Fuente externa 5V | Conectar tierra (GND) común con Arduino |
| **Lector QR USB** | Puerto USB Laptop | Configurado en modo emulación teclado |
| **Arduino** | Puerto USB Laptop | Comunicación Serial a 9600 baudios |

---

## 💻 Requisitos y Dependencias

- Python 3.8+
- Dependencias de Python:
  ```bash
  pip install pyserial qrcode pillow
  ```

---

## 🚀 Puesta en Marcha

### 1. Cargar el código en el Arduino
Abre el archivo `estacionamiento_arduino/estacionamiento_arduino.ino` en el Arduino IDE y cárgalo en tu placa Arduino Uno.

### 2. Iniciar el software en la Laptop
Ejecuta el script principal de Python:
```bash
python "estacionamiento_arduino/estacionamiento laptop v2.py"
```

Abre en el navegador de la laptop para la pantalla de bienvenida:
```text
http://localhost:8000/pantalla
```
*(Puedes presionar `F11` para ponerlo en pantalla completa).*

---

## 📱 Acceso desde el Teléfono Móvil

Para que los conductores puedan escanear y abrir el ticket en su celular:

### Opción 1: Túnel Público (Recomendado - Funciona con 4G, 5G y cualquier red)
Puedes usar **Cloudflare Tunnel** o **ngrok** para exponer el puerto local `8000`:
```bash
# Con Cloudflare (gratis y sin registro):
cloudflared tunnel --url http://localhost:8000
```
Configura la URL generada en el script para que el QR sea accesible desde cualquier red móvil.

### Opción 2: Red Local Wi-Fi
- La laptop y el celular deben estar conectados a la **misma red Wi-Fi** o al **Punto de acceso móvil de la laptop**.
- Asegúrate de habilitar el puerto `8000` en el Firewall de Windows:
  ```powershell
  netsh advfirewall firewall add rule name="Estacionamiento_QR_8000" dir=in action=allow protocol=TCP localport=8000
  ```
