/*
  ================================================================
          SISTEM KONTROL AEROPONIK BERBASIS ESP32
          POMPA SPRAY TERJADWAL + FIREBASE IOT
  ================================================================
*/

#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <WiFi.h>
#include <Firebase_ESP_Client.h>

// Token Helper & RTDB Helper Firebase
#include "addons/TokenHelper.h"
#include "addons/RTDBHelper.h"

// ================================================================
// KREDENSIAL WIFI & FIREBASE
// ================================================================
#define WIFI_SSID "NAMA_WIFI_KAMU"        // Ganti dengan SSID WiFi/Tethering
#define WIFI_PASSWORD "PASSWORD_WIFI_KAMU" // Ganti dengan Password WiFi

#define API_KEY "AIzaSyBmBj2VzJzGYE9gobVU3-oRu6Y4ki_Amrw"
#define DATABASE_URL "https://aeroponic-2712d-default-rtdb.firebaseio.com"

FirebaseData fbdo;
FirebaseAuth auth;
FirebaseConfig config;

// ================================================================
// LCD
// ================================================================
LiquidCrystal_I2C lcd(0x27, 20, 4);

// ================================================================
// PIN ULTRASONIK ATAS - DETEKSI HAMA (Pin Disesuaikan)
// ================================================================
#define TRIG_HAMA 27
#define ECHO_HAMA 14

// ================================================================
// PIN ULTRASONIK BAWAH - LEVEL AIR (Pin Disesuaikan)
// ================================================================
#define TRIG_LEVEL 25
#define ECHO_LEVEL 26

// ================================================================
// SENSOR ANALOG
// ================================================================
#define PIN_PH 34
#define PIN_PPM 35

// ================================================================
// OUTPUT
// ================================================================
#define BUZZER 18

#define RELAY_POMPA_ISI 19
#define RELAY_POMPA_SPRAY 23
#define RELAY_POMPA_NUTRISI 32
#define RELAY_POMPA_UTAMA 33

// ================================================================
// LED INDIKATOR
// ================================================================
#define LED_POMPA_ISI 4
#define LED_POMPA_SPRAY 5

// ================================================================
// BATAS DETEKSI HAMA
// ================================================================
const float JARAK_HAMA = 50.0;

// ================================================================
// BATAS LEVEL AIR
// ================================================================
const float LEVEL_MAKSIMUM = 5.0;
const float LEVEL_MINIMUM = 17.0;

// ================================================================
// BATAS PPM & pH
// ================================================================
const float PPM_MINIMUM = 800.0;
const float PPM_MAKSIMUM = 1200.0;
const float PH_MINIMUM = 5.5;
const float PH_MAKSIMUM = 6.5;

// ================================================================
// JADWAL POMPA SPRAY
// ================================================================
const unsigned long SPRAY_ON_TIME = 5000;  // 5 detik
const unsigned long SPRAY_OFF_TIME = 30000; // 30 detik

// Timer pompa spray
unsigned long waktuSpray = 0;

// Status pompa & sistem
bool pompaIsiStatus = false;
bool pompaSprayStatus = false;
bool autoSprayStatus = false;

// Status hama & buzzer
bool hamaTerdeteksi = false;
bool statusBuzzerAktif = false; // Mencegah error LEDC spam

// Status Override dari Firebase Dashboard
bool fbPompaAir = false;
bool fbPompaMisting = false;
bool fbPompaNutrisi = false;
bool fbPompaUtama = false;

// Timer Multitasking Non-Blocking
unsigned long waktuBacaSensor = 0;
unsigned long waktuKirimFB = 0;
unsigned long waktuBacaFB = 0;


// ================================================================
// FUNGSI MEMBACA ULTRASONIK
// ================================================================
float bacaUltrasonik(int trigPin, int echoPin)
{
  digitalWrite(trigPin, LOW);
  delayMicroseconds(2);

  digitalWrite(trigPin, HIGH);
  delayMicroseconds(10);

  digitalWrite(trigPin, LOW);

  // Timeout 40ms untuk mendeteksi pantulan
  long durasi = pulseIn(echoPin, HIGH, 40000);

  if (durasi == 0)
  {
    return -1;
  }

  float jarak = durasi * 0.0343 / 2.0;

  // Filter Out of Range (> 4 meter atau invalid)
  if (jarak > 400.0 || jarak <= 0.0)
  {
    return -1;
  }

  return jarak;
}


// ================================================================
// FUNGSI MEMBACA SENSOR pH
// ================================================================
float bacaPH()
{
  int nilaiADC = analogRead(PIN_PH);
  float ph = 6.0 + (nilaiADC / 4095.0) * 2.0;
  return ph;
}


// ================================================================
// FUNGSI MEMBACA SENSOR PPM
// ================================================================
float bacaPPM()
{
  int nilaiADC = analogRead(PIN_PPM);
  float ppm = map(nilaiADC, 0, 4095, 0, 1500);
  return ppm;
}


// ================================================================
// FUNGSI KOMUNIKASI FIREBASE
// ================================================================
void kirimDataFirebase(float ph, float ppm, float jarakAir) {
  if (Firebase.ready()) {
    Firebase.RTDB.setFloat(&fbdo, "sensor/ph", ph);
    Firebase.RTDB.setFloat(&fbdo, "sensor/tds", ppm);
    
    // Estimasi konversi volume air (0 - 50 L)
    float volumeAir = map((long)jarakAir, (long)LEVEL_MINIMUM, (long)LEVEL_MAKSIMUM, 0, 50); 
    if (volumeAir < 0) volumeAir = 0;
    if (volumeAir > 50) volumeAir = 50;
    
    Firebase.RTDB.setFloat(&fbdo, "sensor/volume", volumeAir);
  }
}

void bacaDataFirebase() {
  if (Firebase.ready()) {
    if (Firebase.RTDB.getBool(&fbdo, "kontrol/pompaAir")) fbPompaAir = fbdo.boolData();
    if (Firebase.RTDB.getBool(&fbdo, "kontrol/pompaMisting")) fbPompaMisting = fbdo.boolData();
    if (Firebase.RTDB.getBool(&fbdo, "kontrol/pompaNutrisiA")) fbPompaNutrisi = fbdo.boolData();
    if (Firebase.RTDB.getBool(&fbdo, "kontrol/pompaUtama")) fbPompaUtama = fbdo.boolData();
  }
}


// ================================================================
// KONTROL HAMA
// ================================================================
void kontrolHama(float jarakHama)
{
  if (jarakHama < 0 || jarakHama > JARAK_HAMA)
  {
    hamaTerdeteksi = false;
    if (statusBuzzerAktif) {
      noTone(BUZZER);
      statusBuzzerAktif = false;
    }
    return;
  }

  if (jarakHama > 0 && jarakHama <= JARAK_HAMA)
  {
    hamaTerdeteksi = true;

    if (!statusBuzzerAktif) {
      tone(BUZZER, 4000);
      statusBuzzerAktif = true;

      Serial.println("!!! PERINGATAN !!!");
      Serial.println("OBJEK / HAMA TERDETEKSI");
    }
  }
}


// ================================================================
// KONTROL LEVEL AIR
// ================================================================
void kontrolLevelAir(float jarakAir)
{
  bool autoIsi = pompaIsiStatus;

  if (jarakAir > 0 && jarakAir >= LEVEL_MINIMUM)
  {
    autoIsi = true;
  }
  else if (jarakAir > 0 && jarakAir <= LEVEL_MAKSIMUM)
  {
    autoIsi = false;
  }

  // Override Firebase / Auto Logic
  pompaIsiStatus = fbPompaAir || autoIsi;

  if (pompaIsiStatus)
  {
    digitalWrite(RELAY_POMPA_ISI, LOW);
    digitalWrite(LED_POMPA_ISI, HIGH);
  }
  else
  {
    digitalWrite(RELAY_POMPA_ISI, HIGH);
    digitalWrite(LED_POMPA_ISI, LOW);
  }
}


// ================================================================
// KONTROL POMPA SPRAY TERJADWAL
// ================================================================
void kontrolSprayTerjadwal()
{
  unsigned long waktuSekarang = millis();

  if (autoSprayStatus == true)
  {
    if (waktuSekarang - waktuSpray >= SPRAY_ON_TIME)
    {
      autoSprayStatus = false;
      waktuSpray = waktuSekarang;
    }
  }
  else
  {
    if (waktuSekarang - waktuSpray >= SPRAY_OFF_TIME)
    {
      autoSprayStatus = true;
      waktuSpray = waktuSekarang;
    }
  }

  // Override Firebase / Auto Logic
  pompaSprayStatus = fbPompaMisting || autoSprayStatus;

  if (pompaSprayStatus)
  {
    digitalWrite(RELAY_POMPA_SPRAY, LOW);
    digitalWrite(LED_POMPA_SPRAY, HIGH);
  }
  else
  {
    digitalWrite(RELAY_POMPA_SPRAY, HIGH);
    digitalWrite(LED_POMPA_SPRAY, LOW);
  }
}


// ================================================================
// KONTROL POMPA EKSTRA (WEB DASHBOARD)
// ================================================================
void kontrolPompaEkstra()
{
  if (fbPompaNutrisi) digitalWrite(RELAY_POMPA_NUTRISI, LOW);
  else digitalWrite(RELAY_POMPA_NUTRISI, HIGH);

  if (fbPompaUtama) digitalWrite(RELAY_POMPA_UTAMA, LOW);
  else digitalWrite(RELAY_POMPA_UTAMA, HIGH);
}


// ================================================================
// TAMPILKAN DATA KE LCD
// ================================================================
void tampilkanLCD(
  float jarakHama,
  float jarakAir,
  float ph,
  float ppm
)
{
  // BARIS 1 - pH DAN PPM
  lcd.setCursor(0, 0);
  lcd.print("pH:");
  lcd.print(ph, 2);
  lcd.print(" PPM:");
  lcd.print(ppm, 0);
  lcd.print("   ");

  // BARIS 2 - LEVEL AIR
  lcd.setCursor(0, 1);
  lcd.print("Air:");

  if (jarakAir < 0)
  {
    lcd.print("ERROR ");
  }
  else
  {
    lcd.print(jarakAir, 1);
    lcd.print("cm ");
  }

  if (jarakAir >= LEVEL_MINIMUM && jarakAir > 0)
  {
    lcd.print("MIN");
  }
  else if (jarakAir <= LEVEL_MAKSIMUM && jarakAir > 0)
  {
    lcd.print("MAX");
  }
  else if (jarakAir > 0)
  {
    lcd.print("OK ");
  }
  lcd.print("  ");

  // BARIS 3 - STATUS POMPA
  lcd.setCursor(0, 2);
  lcd.print("Isi:");

  if (pompaIsiStatus)
  {
    lcd.print("ON ");
  }
  else
  {
    lcd.print("OFF");
  }

  lcd.print(" Spray:");

  if (pompaSprayStatus)
  {
    lcd.print("ON ");
  }
  else
  {
    lcd.print("OFF");
  }
  lcd.print(" ");

  // BARIS 4 - STATUS HAMA
  lcd.setCursor(0, 3);

  if (hamaTerdeteksi)
  {
    lcd.print("HAMA: TERDETEKSI ");
  }
  else
  {
    lcd.print("HAMA: AMAN       ");
  }
}


// ================================================================
// TAMPILKAN DATA KE SERIAL MONITOR
// ================================================================
void tampilkanSerial(
  float jarakHama,
  float jarakAir,
  float ph,
  float ppm
)
{
  Serial.println("\n================================");
  Serial.println("     MONITORING AEROPONIK");
  Serial.println("================================");

  Serial.print("Jarak Objek : ");
  if (jarakHama > 0)
  {
    Serial.print(jarakHama, 1);
    Serial.println(" cm");
  }
  else
  {
    Serial.println("Tidak terbaca");
  }

  Serial.print("Level Air   : ");
  if (jarakAir > 0)
  {
    Serial.print(jarakAir, 1);
    Serial.println(" cm");
  }
  else
  {
    Serial.println("Tidak terbaca");
  }

  Serial.print("pH Air      : ");
  Serial.println(ph, 2);

  Serial.print("PPM Nutrisi : ");
  Serial.println(ppm, 0);

  Serial.print("Pompa Isi   : ");
  Serial.println(pompaIsiStatus ? "ON" : "OFF");

  Serial.print("Pompa Spray : ");
  Serial.println(pompaSprayStatus ? "ON" : "OFF");

  Serial.print("Hama        : ");
  Serial.println(hamaTerdeteksi ? "TERDETEKSI" : "AMAN");

  Serial.println("================================");
}


// ================================================================
// SETUP
// ================================================================
void setup()
{
  Serial.begin(115200);

  pinMode(TRIG_HAMA, OUTPUT);
  pinMode(ECHO_HAMA, INPUT);

  pinMode(TRIG_LEVEL, OUTPUT);
  pinMode(ECHO_LEVEL, INPUT);

  pinMode(BUZZER, OUTPUT);

  pinMode(RELAY_POMPA_ISI, OUTPUT);
  pinMode(RELAY_POMPA_SPRAY, OUTPUT);
  pinMode(RELAY_POMPA_NUTRISI, OUTPUT);
  pinMode(RELAY_POMPA_UTAMA, OUTPUT);

  pinMode(LED_POMPA_ISI, OUTPUT);
  pinMode(LED_POMPA_SPRAY, OUTPUT);

  digitalWrite(TRIG_HAMA, LOW);
  digitalWrite(TRIG_LEVEL, LOW);

  noTone(BUZZER);

  digitalWrite(RELAY_POMPA_ISI, HIGH);
  digitalWrite(RELAY_POMPA_SPRAY, HIGH);
  digitalWrite(RELAY_POMPA_NUTRISI, HIGH);
  digitalWrite(RELAY_POMPA_UTAMA, HIGH);

  digitalWrite(LED_POMPA_ISI, LOW);
  digitalWrite(LED_POMPA_SPRAY, LOW);

  Wire.begin(21, 22);
  lcd.init();
  lcd.backlight();

  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print(" SISTEM AEROPONIK");
  lcd.setCursor(0, 1);
  lcd.print(" Menghubungkan...");

  // Koneksi WiFi
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi Terhubung.");
  lcd.setCursor(0, 2);
  lcd.print(" WiFi Connected! ");

  // Konfigurasi Firebase
  config.api_key = API_KEY;
  config.database_url = DATABASE_URL;
  if (Firebase.signUp(&config, &auth, "", "")) {
    Serial.println("Firebase Auth Sukses");
  }
  config.token_status_callback = tokenStatusCallback;
  Firebase.begin(&config, &auth);
  Firebase.reconnectWiFi(true);

  delay(2000);
  lcd.clear();

  waktuSpray = millis();
}


// ================================================================
// LOOP UTAMA (MILLIS NON-BLOCKING)
// ================================================================
void loop()
{
  unsigned long waktuSekarang = millis();

  // 1. BACA SENSOR & UPDATE LAYAR SETIAP 1 DETIK
  if (waktuSekarang - waktuBacaSensor >= 1000)
  {
    waktuBacaSensor = waktuSekarang;

    float jarakHama = bacaUltrasonik(TRIG_HAMA, ECHO_HAMA);
    float jarakAir = bacaUltrasonik(TRIG_LEVEL, ECHO_LEVEL);
    float ph = bacaPH();
    float ppm = bacaPPM();

    // Kontrol Logika
    kontrolHama(jarakHama);
    kontrolLevelAir(jarakAir);
    kontrolSprayTerjadwal();
    kontrolPompaEkstra();

    // Tampilan
    tampilkanLCD(jarakHama, jarakAir, ph, ppm);
    tampilkanSerial(jarakHama, jarakAir, ph, ppm);
  }

  // 2. KIRIM DATA KE FIREBASE SETIAP 5 DETIK
  if (waktuSekarang - waktuKirimFB >= 5000)
  {
    waktuKirimFB = waktuSekarang;
    
    // Baca nilai sensor untuk dikirim
    float jAir = bacaUltrasonik(TRIG_LEVEL, ECHO_LEVEL);
    float nilPH = bacaPH();
    float nilPPM = bacaPPM();

    kirimDataFirebase(nilPH, nilPPM, jAir);
  }

  // 3. BACA PERINTAH DARI FIREBASE SETIAP 2 DETIK
  if (waktuSekarang - waktuBacaFB >= 2000)
  {
    waktuBacaFB = waktuSekarang;
    bacaDataFirebase();
  }
}
