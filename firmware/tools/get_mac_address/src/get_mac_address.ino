/*
  Flash this onto the RECEIVER dongle (not the gloves) to print its
  MAC address over Serial. Copy that address into each glove's
  config.h as RECEIVER_MAC before flashing the glove firmware.
*/

#include <WiFi.h>

void setup() {
  Serial.begin(115200);
  delay(500);
  WiFi.mode(WIFI_STA);
  Serial.print("MAC Address: ");
  Serial.println(WiFi.macAddress());
}

void loop() {
  // Nothing to do — the address only needs to be read once.
}
