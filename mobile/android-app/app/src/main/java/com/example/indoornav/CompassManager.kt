package com.example.indoornav

import android.content.Context
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.util.Log
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow

/**
 * CompassManager.kt
 *
 * Members involved in this file
 * -----------------------------------------------------------
 * CHONG WIN NIE 22ACB05895 — Compass
 *   - Reads accelerometer and magnetometer.
 *   - Computes azimuth (0–360°) and exposes as StateFlow.
 *   - Reports sensor availability and accuracy.
 *
 */
class CompassManager(private val context: Context) : SensorEventListener {

    private val tag = "CompassManager"

    // [CHONG WIN NIE — Compass] Core sensors
    private val sensorManager: SensorManager = context.getSystemService(Context.SENSOR_SERVICE) as SensorManager
    private val accelerometer: Sensor? = sensorManager.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)
    private val magnetometer: Sensor? = sensorManager.getDefaultSensor(Sensor.TYPE_MAGNETIC_FIELD)

    // [CHONG WIN NIE — Compass] Buffers for orientation math
    private val accelerometerReading = FloatArray(3)
    private val magnetometerReading = FloatArray(3)
    private val rotationMatrix = FloatArray(9)
    private val orientationAngles = FloatArray(3)

    // Heading state (degrees)
    private val _heading = MutableStateFlow(0f)
    val heading: StateFlow<Float> = _heading

    // Availability flag
    private val _isAvailable = MutableStateFlow(false)
    val isAvailable: StateFlow<Boolean> = _isAvailable

    init {
        checkSensorAvailability()
    }

    private fun checkSensorAvailability() {
        val hasAccelerometer = accelerometer != null
        val hasMagnetometer = magnetometer != null
        val available = hasAccelerometer && hasMagnetometer

        _isAvailable.value = available

        Log.d(tag, "Compass availability: $available")
        Log.d(tag, "  - Accelerometer: $hasAccelerometer")
        Log.d(tag, "  - Magnetometer: $hasMagnetometer")
    }

    /** Start listening to sensors. */
    fun startListening() {
        if (!_isAvailable.value) {
            Log.w(tag, "Compass sensors not available")
            return
        }

        accelerometer?.let { sensor ->
            sensorManager.registerListener(this, sensor, SensorManager.SENSOR_DELAY_UI)
        }
        magnetometer?.let { sensor ->
            sensorManager.registerListener(this, sensor, SensorManager.SENSOR_DELAY_UI)
        }

        Log.d(tag, "Started compass listening")
    }

    /** Stop listening to sensors. */
    fun stopListening() {
        sensorManager.unregisterListener(this)
        Log.d(tag, "Stopped compass listening")
    }

    override fun onSensorChanged(event: SensorEvent?) {
        if (event == null) return

        when (event.sensor.type) {
            Sensor.TYPE_ACCELEROMETER -> {
                System.arraycopy(event.values, 0, accelerometerReading, 0, accelerometerReading.size)
            }
            Sensor.TYPE_MAGNETIC_FIELD -> {
                System.arraycopy(event.values, 0, magnetometerReading, 0, magnetometerReading.size)
            }
        }

        updateHeading()
    }

    private fun updateHeading() {
        // Compute rotation matrix and orientation angles
        val success = SensorManager.getRotationMatrix(
            rotationMatrix, null, accelerometerReading, magnetometerReading
        )

        if (success) {
            SensorManager.getOrientation(rotationMatrix, orientationAngles)

            // Azimuth in degrees (normalize to 0..360)
            val azimuthRad = orientationAngles[0]
            var azimuthDeg = Math.toDegrees(azimuthRad.toDouble()).toFloat()
            if (azimuthDeg < 0) azimuthDeg += 360f

            _heading.value = azimuthDeg
            Log.v(tag, "Heading updated: ${azimuthDeg.toInt()}°")
        }
    }

    override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) {
        when (accuracy) {
            SensorManager.SENSOR_STATUS_UNRELIABLE -> Log.w(tag, "Compass accuracy: UNRELIABLE")
            SensorManager.SENSOR_STATUS_ACCURACY_LOW -> Log.w(tag, "Compass accuracy: LOW")
            SensorManager.SENSOR_STATUS_ACCURACY_MEDIUM -> Log.d(tag, "Compass accuracy: MEDIUM")
            SensorManager.SENSOR_STATUS_ACCURACY_HIGH -> Log.d(tag, "Compass accuracy: HIGH")
        }
    }

    /** Returns current heading in degrees: 0=N, 90=E, 180=S, 270=W. */
    fun getCurrentHeading(): Float = _heading.value

    /** Optional helper to convert heading to cardinal direction string. */
    fun getDirectionString(heading: Float): String {
        return when (heading) {
            in 337.5f..360f, in 0f..22.5f -> "North"
            in 22.5f..67.5f -> "Northeast"
            in 67.5f..112.5f -> "East"
            in 112.5f..157.5f -> "Southeast"
            in 157.5f..202.5f -> "South"
            in 202.5f..247.5f -> "Southwest"
            in 247.5f..292.5f -> "West"
            in 292.5f..337.5f -> "Northwest"
            else -> "Unknown"
        }
    }
}
