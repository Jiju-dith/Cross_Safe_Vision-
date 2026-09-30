#include <Preferences.h>

Preferences prefs;

// =====================================================
// PINS
// =====================================================

const int PIR_PIN       = 13;

const int TRIG_PIN      = 26;
const int ECHO_PIN      = 27;

const int LDR_PIN       = 34;

const int FLOODLIGHT_PIN = 18;   // WHITE LIGHT
const int BEACON_PIN     = 21;   // RED LIGHT


// =====================================================
// LDR SETTINGS
// =====================================================

const int LDR_THRESHOLD = 2000;

// Your wiring:
// 3.3V -> LDR -> GPIO34 -> 10k resistor -> GND
//
// Therefore:
// LOW ADC value = DARK
// HIGH ADC value = BRIGHT


// =====================================================
// ULTRASONIC SETTINGS
// =====================================================

// Short distance for your hand-testing prototype
const float VEHICLE_DISTANCE = 10.0;

// Valid ultrasonic measurement range
const float MIN_DISTANCE = 2.0;
const float MAX_DISTANCE = 400.0;


// =====================================================
// WHITE LIGHT
// =====================================================

const unsigned long WHITE_LIGHT_TIME = 5000;

unsigned long whiteLightStart = 0;
bool whiteLightActive = false;


// =====================================================
// RED BEACON
// =====================================================

const unsigned long SLOW_FLASH_INTERVAL = 500;
const unsigned long FAST_FLASH_INTERVAL = 100;

unsigned long lastFlashTime = 0;

bool redState = false;


// =====================================================
// VEHICLE SPEED
// =====================================================

// Speed is measured in cm/s for the prototype

float previousDistance = -1;
float previousSpeed = 0;

unsigned long previousDistanceTime = 0;

float currentSpeed = 0;


// Speed above this is considered approaching quickly
const float NOT_SLOWING_SPEED = 20.0;

// Difference used to decide whether speed is decreasing
const float SLOWING_DIFFERENCE = 5.0;


// =====================================================
// SENSOR STATES
// =====================================================

bool pedestrianPresent = false;
bool previousPedestrianState = false;

bool vehicleDetected = false;
bool previousVehicleDetected = false;

bool vehicleSlowing = false;


// =====================================================
// COUNTERS
// =====================================================

int pedestrianCount = 0;
int vehicleCount = 0;


// =====================================================
// SETUP
// =====================================================

void setup()
{
    Serial.begin(115200);

    pinMode(PIR_PIN, INPUT);

    pinMode(TRIG_PIN, OUTPUT);
    pinMode(ECHO_PIN, INPUT);

    pinMode(FLOODLIGHT_PIN, OUTPUT);
    pinMode(BEACON_PIN, OUTPUT);

    digitalWrite(FLOODLIGHT_PIN, LOW);
    digitalWrite(BEACON_PIN, LOW);

    // -------------------------------------------------
    // Preferences
    // -------------------------------------------------

    prefs.begin("crossing", false);

    pedestrianCount = prefs.getInt("ped", 0);
    vehicleCount = prefs.getInt("veh", 0);

    Serial.println();
    Serial.println("======================================");
    Serial.println(" SMART PEDESTRIAN CROSSING");
    Serial.println("======================================");

    Serial.print("Pedestrian count: ");
    Serial.println(pedestrianCount);

    Serial.print("Vehicle count: ");
    Serial.println(vehicleCount);

    Serial.println("System ready.");
    Serial.println();
}


// =====================================================
// READ ULTRASONIC DISTANCE
// =====================================================

float readDistance()
{
    digitalWrite(TRIG_PIN, LOW);
    delayMicroseconds(2);

    digitalWrite(TRIG_PIN, HIGH);
    delayMicroseconds(10);

    digitalWrite(TRIG_PIN, LOW);

    long duration = pulseIn(ECHO_PIN, HIGH, 30000);

    // No echo
    if (duration == 0)
    {
        return -1;
    }

    float distance = duration * 0.0343 / 2.0;

    if (distance < MIN_DISTANCE || distance > MAX_DISTANCE)
    {
        return -1;
    }

    return distance;
}


// =====================================================
// CALCULATE VEHICLE SPEED
// =====================================================

void calculateVehicleSpeed(float distance)
{
    unsigned long currentTime = millis();

    // First valid reading
    if (previousDistance < 0)
    {
        previousDistance = distance;
        previousDistanceTime = currentTime;
        currentSpeed = 0;

        return;
    }

    unsigned long timeDifference =
        currentTime - previousDistanceTime;

    if (timeDifference < 50)
    {
        return;
    }

    // Positive value means object is getting closer
    float distanceChange =
        previousDistance - distance;

    float newSpeed =
        (distanceChange / timeDifference) * 1000.0;

    // Ignore movement away from sensor
    if (newSpeed < 0)
    {
        newSpeed = 0;
    }

    // Ignore unrealistic hand/sensor spikes
    if (newSpeed > 500)
    {
        newSpeed = 500;
    }

    currentSpeed = newSpeed;

    // -------------------------------------------------
    // Determine whether vehicle is slowing
    // -------------------------------------------------

    if (currentSpeed < previousSpeed - SLOWING_DIFFERENCE)
    {
        vehicleSlowing = true;
    }
    else
    {
        vehicleSlowing = false;
    }

    previousSpeed = currentSpeed;
    previousDistance = distance;
    previousDistanceTime = currentTime;
}


// =====================================================
// RESET VEHICLE SPEED DATA
// =====================================================

void resetVehicleSpeed()
{
    previousDistance = -1;
    previousSpeed = 0;
    currentSpeed = 0;
    previousDistanceTime = 0;
    vehicleSlowing = false;
}


// =====================================================
// WHITE LIGHT CONTROL
// =====================================================

void controlWhiteLight()
{
    if (whiteLightActive)
    {
        if (millis() - whiteLightStart < WHITE_LIGHT_TIME)
        {
            digitalWrite(FLOODLIGHT_PIN, HIGH);
        }
        else
        {
            whiteLightActive = false;

            digitalWrite(FLOODLIGHT_PIN, LOW);

            Serial.println("💡 White light OFF");
        }
    }
    else
    {
        digitalWrite(FLOODLIGHT_PIN, LOW);
    }
}


// =====================================================
// RED BEACON CONTROL
// =====================================================

void controlRedBeacon()
{
    // Red beacon works ONLY when:
    // pedestrian + vehicle are both detected

    if (pedestrianPresent && vehicleDetected)
    {
        unsigned long flashInterval;

        // ---------------------------------------------
        // Vehicle slowing -> SLOW BLINK
        // ---------------------------------------------

        if (vehicleSlowing)
        {
            flashInterval = SLOW_FLASH_INTERVAL;

            if (millis() - lastFlashTime >= flashInterval)
            {
                lastFlashTime = millis();

                redState = !redState;

                digitalWrite(BEACON_PIN, redState);
            }
        }

        // ---------------------------------------------
        // Vehicle NOT slowing -> FAST BLINK
        // ---------------------------------------------

        else
        {
            flashInterval = FAST_FLASH_INTERVAL;

            if (millis() - lastFlashTime >= flashInterval)
            {
                lastFlashTime = millis();

                redState = !redState;

                digitalWrite(BEACON_PIN, redState);
            }
        }
    }

    // ---------------------------------------------
    // No pedestrian or no vehicle
    // ---------------------------------------------

    else
    {
        redState = false;

        digitalWrite(BEACON_PIN, LOW);

        lastFlashTime = millis();
    }
}


// =====================================================
// MAIN LOOP
// =====================================================

void loop()
{
    // =================================================
    // 1. READ LDR
    // =================================================

    int lightLevel = analogRead(LDR_PIN);

    bool isNight = (lightLevel < LDR_THRESHOLD);


    // =================================================
    // 2. DAYTIME
    // =================================================

    if (!isNight)
    {
        pedestrianPresent = false;
        vehicleDetected = false;

        whiteLightActive = false;

        digitalWrite(FLOODLIGHT_PIN, LOW);
        digitalWrite(BEACON_PIN, LOW);

        redState = false;

        resetVehicleSpeed();

        previousPedestrianState = false;
        previousVehicleDetected = false;

        Serial.print("☀️ DAY | LDR: ");
        Serial.println(lightLevel);

        delay(200);

        return;
    }


    // =================================================
    // 3. NIGHT
    // =================================================

    // -------------------------------------------------
    // PIR
    // -------------------------------------------------

    pedestrianPresent = digitalRead(PIR_PIN);


    // =================================================
    // 4. NEW PEDESTRIAN DETECTION
    // =================================================

    if (pedestrianPresent && !previousPedestrianState)
    {
        pedestrianCount++;

        prefs.putInt("ped", pedestrianCount);

        // Start the 5-second white-light timer
        whiteLightStart = millis();

        whiteLightActive = true;

        Serial.println();
        Serial.println("======================================");
        Serial.println("🚶 PEDESTRIAN DETECTED");
        Serial.println("💡 WHITE LIGHT ON FOR 5 SECONDS");
        Serial.print("Pedestrian count: ");
        Serial.println(pedestrianCount);
        Serial.println("======================================");
    }


    // Save PIR state
    previousPedestrianState = pedestrianPresent;


    // =================================================
    // 5. ULTRASONIC
    // =================================================

    float distance = readDistance();


    if (distance > 0)
    {
        // Vehicle is inside detection zone
        if (distance <= VEHICLE_DISTANCE)
        {
            vehicleDetected = true;

            // Calculate speed
            calculateVehicleSpeed(distance);
        }
        else
        {
            vehicleDetected = false;

            resetVehicleSpeed();
        }
    }
    else
    {
        vehicleDetected = false;

        resetVehicleSpeed();
    }


    // =================================================
    // 6. NEW VEHICLE DETECTION
    // =================================================

    if (vehicleDetected && !previousVehicleDetected)
    {
        vehicleCount++;

        prefs.putInt("veh", vehicleCount);

        Serial.println();
        Serial.println("🚗 VEHICLE DETECTED");

        Serial.print("Vehicle count: ");
        Serial.println(vehicleCount);
    }


    previousVehicleDetected = vehicleDetected;


    // =================================================
    // 7. WHITE LIGHT
    // =================================================

    controlWhiteLight();


    // =================================================
    // 8. RED BEACON
    // =================================================

    controlRedBeacon();


    // =================================================
    // 9. SERIAL MONITOR
    // =================================================

    Serial.print("🌙 NIGHT");
    Serial.print(" | LDR: ");
    Serial.print(lightLevel);

    Serial.print(" | PIR: ");
    Serial.print(pedestrianPresent ? "YES" : "NO");

    Serial.print(" | Distance: ");

    if (distance > 0)
    {
        Serial.print(distance);
        Serial.print(" cm");
    }
    else
    {
        Serial.print("NO ECHO");
    }

    Serial.print(" | Vehicle: ");
    Serial.print(vehicleDetected ? "YES" : "NO");

    Serial.print(" | Speed: ");
    Serial.print(currentSpeed);
    Serial.print(" cm/s");

    Serial.print(" | ");

    if (pedestrianPresent && vehicleDetected)
    {
        if (vehicleSlowing)
        {
            Serial.println("🐢 SLOWING -> WHITE ON + RED SLOW BLINK");
        }
        else
        {
            Serial.println("⚠️ NOT SLOWING -> WHITE ON + RED FAST BLINK");
        }
    }
    else if (pedestrianPresent)
    {
        Serial.println("🚶 PEDESTRIAN ONLY -> WHITE ON");
    }
    else if (vehicleDetected)
    {
        Serial.println("🚗 VEHICLE ONLY -> NO LIGHT");
    }
    else
    {
        Serial.println("NO DETECTION -> LIGHTS OFF");
    }


    delay(100);
}