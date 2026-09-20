/*
 * claude-status-led - Arduino firmware
 *
 * Drives one external LED to show what Claude Code is doing.
 * The Mac-side daemon sends a single byte over serial:
 *
 *   '0'  off    - no session open
 *   '1'  on     - a session is open and working
 *   '2'  blink  - a session is waiting on you
 *   'p'  ping   - heartbeat, keeps the current state alive
 *
 * Any byte resets the watchdog. If nothing arrives for WATCHDOG_MS
 * the LED drops to off by itself, so a crashed daemon or a sleeping
 * Mac can never leave the light stuck on and lying to you.
 */

const uint8_t LED_PIN     = 9;      // external LED, D9 -> 220R -> LED -> GND
const uint16_t BLINK_MS   = 250;    // half-period when blinking
const uint32_t WATCHDOG_MS = 10000; // no traffic for this long -> force off

enum State { OFF, ON, BLINK };

State state = OFF;
uint32_t lastMessage = 0;
uint32_t lastToggle = 0;
bool blinkPhase = false;

void setup() {
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);
  Serial.begin(9600);
  lastMessage = millis();
}

void loop() {
  while (Serial.available() > 0) {
    char c = Serial.read();
    switch (c) {
      case '0': state = OFF;   break;
      case '1': state = ON;    break;
      case '2': state = BLINK; break;
      case 'p': break;              // heartbeat only, state unchanged
      default:  continue;           // ignore newlines and stray bytes
    }
    lastMessage = millis();
  }

  uint32_t now = millis();

  // Watchdog: nothing heard in a while, assume the Mac is gone.
  if (now - lastMessage > WATCHDOG_MS) {
    state = OFF;
  }

  switch (state) {
    case OFF:
      digitalWrite(LED_PIN, LOW);
      break;
    case ON:
      digitalWrite(LED_PIN, HIGH);
      break;
    case BLINK:
      if (now - lastToggle >= BLINK_MS) {
        lastToggle = now;
        blinkPhase = !blinkPhase;
        digitalWrite(LED_PIN, blinkPhase ? HIGH : LOW);
      }
      break;
  }
}
