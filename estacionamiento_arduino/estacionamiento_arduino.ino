/*
  ESTACIONAMIENTO CON QR - ARDUINO UNO (versión con laptop y dos plumas)
  ---------------------------------------------------------------------
  El Arduino solo lee los sensores y mueve las plumas.
  La laptop genera los tickets, imprime el QR y valida la salida.

  Conexiones:
    IR entrada  OUT -> D2        IR salida  OUT -> D3
    Servo entrada (señal) -> D9  Servo salida (señal) -> D5
    Servos: rojo -> + fuente externa 5V, café -> GND común
    Cable USB -> laptop

  Mensajes Arduino -> laptop (9600 baudios, uno por línea):
    LISTO              el Arduino arrancó
    CARRO_ENTRADA      hay un auto esperando en la entrada (pide ticket)
    ABIERTA_ENTRADA / ABIERTA_SALIDA
    CERRADA_ENTRADA / CERRADA_SALIDA
    SIN_RESPUESTA      la laptop no contestó a tiempo

  Órdenes laptop -> Arduino:
    ABRIR_ENTRADA      subir pluma de entrada (después de imprimir el ticket)
    ABRIR_SALIDA       subir pluma de salida (QR válido)
    LLENO              no hay lugares: no se abre la entrada
*/

#include <Servo.h>

// ---------- Pines ----------
const uint8_t PIN_IR_ENTRADA    = 2;
const uint8_t PIN_IR_SALIDA     = 3;
const uint8_t PIN_SERVO_ENTRADA = 9;
const uint8_t PIN_SERVO_SALIDA  = 5;

// ---------- Ajustes ----------
const bool     IR_DETECTA     = LOW;    // los FC-51 dan LOW al detectar
const uint32_t T_PRESENCIA    = 1000;   // ms con el auto frente al sensor para pedir ticket
const uint32_t T_LIBRE        = 1500;   // ms sin auto antes de bajar la pluma
const uint32_t T_MAX_ABIERTA  = 30000;  // si nadie pasa, se cierra sola
const uint32_t T_ESPERA_LAPTOP = 40000; // tiempo máximo esperando a la laptop (el conductor escanea con su celular)
const uint8_t  PASO_SERVO_MS  = 8;      // velocidad: ms por grado

// Ángulos de cada pluma. Si una sube hacia el lado contrario,
// intercambia los valores de cerrado y abierto de esa pluma.
const uint8_t ENTRADA_CERRADA = 0,  ENTRADA_ABIERTA = 90;
const uint8_t SALIDA_CERRADA  = 0,  SALIDA_ABIERTA  = 90;

// ---------- Estructura de cada pluma ----------
enum Estado { CERRADA, ESPERANDO_LAPTOP, ABIERTA, PASANDO, BLOQUEADA };

struct Pluma {
  const char* nombre;     // "ENTRADA" o "SALIDA"
  uint8_t pinIR, pinServo, angCerrada, angAbierta;
  Servo servo;
  int angulo;             // ángulo actual
  int destino;            // ángulo al que se mueve
  uint32_t tPaso;         // último paso del servo
  Estado estado;
  uint32_t t0;            // inicio del estado actual
  uint32_t tPresencia;    // desde cuándo el sensor ve un auto
  uint32_t tLibre;        // desde cuándo el sensor está libre
};

Pluma entrada = {"ENTRADA", PIN_IR_ENTRADA, PIN_SERVO_ENTRADA, ENTRADA_CERRADA, ENTRADA_ABIERTA};
Pluma salida  = {"SALIDA",  PIN_IR_SALIDA,  PIN_SERVO_SALIDA,  SALIDA_CERRADA,  SALIDA_ABIERTA};

// ---------- Utilidades ----------
bool hayAuto(const Pluma& p) { return digitalRead(p.pinIR) == IR_DETECTA; }

void avisar(const char* evento, const Pluma& p) {
  Serial.print(evento); Serial.print('_'); Serial.println(p.nombre);
}

void iniciarPluma(Pluma& p) {
  pinMode(p.pinIR, INPUT);
  p.servo.attach(p.pinServo);
  p.angulo = p.destino = p.angCerrada;
  p.servo.write(p.angulo);
  p.estado = CERRADA;
  p.tPresencia = p.tLibre = 0;
}

void abrir(Pluma& p) {
  p.destino = p.angAbierta;
  p.estado = ABIERTA;
  p.t0 = millis();
  p.tLibre = 0;
  avisar("ABIERTA", p);
}

void cerrar(Pluma& p) {
  p.destino = p.angCerrada;
  p.estado = CERRADA;
  p.tPresencia = 0;
  avisar("CERRADA", p);
}

// Mueve el servo un grado a la vez sin detener el programa
void moverServo(Pluma& p) {
  if (p.angulo == p.destino || millis() - p.tPaso < PASO_SERVO_MS) return;
  p.tPaso = millis();
  p.angulo += (p.destino > p.angulo) ? 1 : -1;
  p.servo.write(p.angulo);
}

// true cuando el sensor lleva T_LIBRE ms sin ver un auto
bool libreSuficiente(Pluma& p) {
  if (hayAuto(p)) { p.tLibre = 0; return false; }
  if (p.tLibre == 0) p.tLibre = millis();
  return millis() - p.tLibre >= T_LIBRE;
}

// ---------- Lógica común después de abrir ----------
void cicloPaso(Pluma& p) {
  switch (p.estado) {
    case ABIERTA:
      if (hayAuto(p)) { p.estado = PASANDO; p.tLibre = 0; }
      else if (millis() - p.t0 > T_MAX_ABIERTA) cerrar(p);   // nadie pasó
      break;
    case PASANDO:
      // Nunca baja mientras el sensor ve el auto (seguridad)
      if (libreSuficiente(p)) cerrar(p);
      break;
    case BLOQUEADA:
      // Espera a que el auto se retire antes de volver a empezar
      if (libreSuficiente(p)) { p.estado = CERRADA; p.tPresencia = 0; }
      break;
    default: break;
  }
}

// ---------- Pluma de entrada ----------
void cicloEntrada() {
  Pluma& p = entrada;
  if (p.estado == CERRADA) {
    if (hayAuto(p)) {
      if (p.tPresencia == 0) p.tPresencia = millis();
      if (millis() - p.tPresencia >= T_PRESENCIA) {
        Serial.println(F("CARRO_ENTRADA"));   // la laptop imprime el ticket
        p.estado = ESPERANDO_LAPTOP;
        p.t0 = millis();
      }
    } else {
      p.tPresencia = 0;
    }
  } else if (p.estado == ESPERANDO_LAPTOP) {
    if (millis() - p.t0 > T_ESPERA_LAPTOP) {
      Serial.println(F("SIN_RESPUESTA"));
      p.estado = BLOQUEADA; p.tLibre = 0;
    }
  } else {
    cicloPaso(p);
  }
}

// ---------- Pluma de salida ----------
void cicloSalida() {
  cicloPaso(salida);   // se abre solo con la orden ABRIR_SALIDA
}

// ---------- Órdenes de la laptop ----------
char buf[24];
uint8_t idx = 0;

void procesarOrden(const char* orden) {
  if (strcmp(orden, "ABRIR_ENTRADA") == 0) {
    if (entrada.estado == ESPERANDO_LAPTOP || entrada.estado == CERRADA) abrir(entrada);
  } else if (strcmp(orden, "ABRIR_SALIDA") == 0) {
    if (salida.estado == CERRADA) abrir(salida);
    else Serial.println(F("OCUPADA_SALIDA"));
  } else if (strcmp(orden, "LLENO") == 0) {
    if (entrada.estado == ESPERANDO_LAPTOP) { entrada.estado = BLOQUEADA; entrada.tLibre = 0; }
  } else if (strcmp(orden, "PING") == 0) {
    Serial.println(F("LISTO"));
  }
}

void leerLaptop() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (idx > 0) { buf[idx] = '\0'; procesarOrden(buf); idx = 0; }
    } else if (idx < sizeof(buf) - 1) {
      buf[idx++] = c;
    }
  }
}

// ---------- Programa principal ----------
void setup() {
  Serial.begin(9600);
  iniciarPluma(entrada);
  iniciarPluma(salida);
  delay(300);
  Serial.println(F("LISTO"));
}

void loop() {
  leerLaptop();
  cicloEntrada();
  cicloSalida();
  moverServo(entrada);
  moverServo(salida);
}
