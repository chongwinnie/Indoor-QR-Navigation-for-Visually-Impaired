package com.example.indoornav

import android.content.Context
import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken
import java.io.IOException

/**
 * NavigationClient.kt
 *
 * Members involved in this file
 * -----------------------------------------------------------
 * TEO QIYANG 22ACB06185 — Integration
 *   - Android ↔ Python backend networking.
 *   - API calls: session, destinations, set destination, scan QR, expected-direction.
 *
 */
class NavigationClient(private val context: Context) {
    private val tag = "NavigationClient"
    private val baseUrl = "http://192.168.0.127:5000/api"  // Your computer's IP address
    private val client = OkHttpClient()
    private val gson = Gson()

    // Session info
    var sessionId: String? = null
    var userName: String = "Mobile User"

    data class ApiResponse(
        val success: Boolean? = null,
        val error: String? = null,
        val message: String? = null,
        val session_id: String? = null,
        val user_name: String? = null,
        val current_location: String? = null,
        val destination: String? = null,
        val path: List<String>? = null,
        val instruction: String? = null,
        val voice_text: String? = null,
        val turn_direction: String? = null,
        val distance_remaining: Int? = null,
        val destination_name: String? = null
    )

    data class Destination(
        val id: String,
        val name: String,
        val floor: String
    )

    /** Create new session with backend server. */
    suspend fun createSession(userName: String = "Mobile User"): Result<String> = withContext(Dispatchers.IO) {
        try {
            this@NavigationClient.userName = userName

            val requestBody = gson.toJson(mapOf("user_name" to userName))
                .toRequestBody("application/json".toMediaType())

            val request = Request.Builder()
                .url("$baseUrl/session/create")
                .post(requestBody)
                .build()

            val response = client.newCall(request).execute()
            val responseBody = response.body?.string()

            if (response.isSuccessful && responseBody != null) {
                val apiResponse = gson.fromJson(responseBody, ApiResponse::class.java)
                sessionId = apiResponse.session_id

                Log.d(tag, "✅ Session created: $sessionId for user: $userName")
                Result.success(sessionId!!)
            } else {
                val error = "Failed to create session: ${response.code}"
                Log.e(tag, error)
                Result.failure(Exception(error))
            }
        } catch (e: Exception) {
            Log.e(tag, "Error creating session: ${e.message}")
            Result.failure(e)
        }
    }

    /** Get available destinations from server. */
    suspend fun getDestinations(): Result<List<Destination>> = withContext(Dispatchers.IO) {
        try {
            val request = Request.Builder()
                .url("$baseUrl/destinations")
                .get()
                .build()

            val response = client.newCall(request).execute()
            val responseBody = response.body?.string()

            if (response.isSuccessful && responseBody != null) {
                val type = object : TypeToken<List<Destination>>() {}.type
                val destinations = gson.fromJson<List<Destination>>(responseBody, type)

                Log.d(tag, "✅ Got ${destinations.size} destinations")
                Result.success(destinations)
            } else {
                val error = "Failed to get destinations: ${response.code}"
                Log.e(tag, error)
                Result.failure(Exception(error))
            }
        } catch (e: Exception) {
            Log.e(tag, "Error getting destinations: ${e.message}")
            Result.failure(e)
        }
    }

    /** Set destination for navigation. */
    suspend fun setDestination(destinationId: String): Result<String> = withContext(Dispatchers.IO) {
        try {
            val currentSessionId = sessionId ?: return@withContext Result.failure(Exception("No active session"))

            val requestBody = gson.toJson(mapOf(
                "session_id" to currentSessionId,
                "destination_id" to destinationId
            )).toRequestBody("application/json".toMediaType())

            val request = Request.Builder()
                .url("$baseUrl/destination/set")
                .post(requestBody)
                .build()

            val response = client.newCall(request).execute()
            val responseBody = response.body?.string()

            if (response.isSuccessful && responseBody != null) {
                val apiResponse = gson.fromJson(responseBody, ApiResponse::class.java)

                if (apiResponse.success == true) {
                    Log.d(tag, "✅ Destination set: ${apiResponse.destination_name}")
                    Result.success(apiResponse.message ?: "Destination set successfully")
                } else {
                    val error = apiResponse.error ?: "Unknown error setting destination"
                    Log.e(tag, error)
                    Result.failure(Exception(error))
                }
            } else {
                val error = "Failed to set destination: ${response.code}"
                Log.e(tag, error)
                Result.failure(Exception(error))
            }
        } catch (e: Exception) {
            Log.e(tag, "Error setting destination: ${e.message}")
            Result.failure(e)
        }
    }

    /** Process QR code scan and get navigation instruction from server. */
    suspend fun processQrScan(qrValue: String, deviceHeading: Float = 0f): Result<NavigationInstruction> = withContext(Dispatchers.IO) {
        try {
            val currentSessionId = sessionId ?: return@withContext Result.failure(Exception("No active session"))

            val requestBody = gson.toJson(mapOf(
                "session_id" to currentSessionId,
                "qr_value" to qrValue,
                "device_heading" to deviceHeading
            )).toRequestBody("application/json".toMediaType())

            val request = Request.Builder()
                .url("$baseUrl/qr/scan")
                .post(requestBody)
                .build()

            Log.d(tag, "📤 Sending QR scan: $qrValue with heading: ${deviceHeading.toInt()}°")

            val response = client.newCall(request).execute()
            val responseBody = response.body?.string()

            if (response.isSuccessful && responseBody != null) {
                val apiResponse = gson.fromJson(responseBody, ApiResponse::class.java)

                if (apiResponse.success == true) {
                    val instruction = NavigationInstruction(
                        success = true,
                        currentLocation = apiResponse.current_location ?: "Unknown",
                        destination = apiResponse.destination,
                        instruction = apiResponse.instruction ?: "Continue",
                        voiceText = apiResponse.voice_text ?: apiResponse.instruction ?: "Continue",
                        turnDirection = apiResponse.turn_direction,
                        distanceRemaining = apiResponse.distance_remaining ?: 0,
                        path = apiResponse.path ?: emptyList()
                    )

                    Log.d(tag, "✅ Navigation instruction: ${instruction.instruction}")
                    Result.success(instruction)
                } else {
                    val error = apiResponse.error ?: apiResponse.message ?: "Unknown error"
                    Log.e(tag, "❌ QR scan error: $error")

                    val errorInstruction = NavigationInstruction(
                        success = false,
                        error = error,
                        currentLocation = apiResponse.current_location ?: "Unknown",
                        instruction = error,
                        voiceText = error
                    )
                    Result.success(errorInstruction)
                }
            } else {
                val error = "Server error: ${response.code}"
                Log.e(tag, error)
                Result.failure(Exception(error))
            }
        } catch (e: Exception) {
            Log.e(tag, "Network error processing QR: ${e.message}")
            Result.failure(e)
        }
    }

    /** Returns whether a session is currently cached. */
    fun hasActiveSession(): Boolean = sessionId != null

    /** Clears the cached session id. */
    fun clearSession() {
        sessionId = null
        Log.d(tag, "Session cleared")
    }

    /** Get expected direction for real-time path deviation detection. */
    suspend fun checkExpectedDirection(
        currentLocation: String,
        destination: String,
        deviceHeading: Float
    ): Result<ExpectedDirectionData> = withContext(Dispatchers.IO) {
        try {
            val requestBody = gson.toJson(mapOf(
                "current_location" to currentLocation,
                "destination" to destination,
                "device_heading" to deviceHeading
            )).toRequestBody("application/json".toMediaType())

            val request = Request.Builder()
                .url("$baseUrl/expected-direction")
                .post(requestBody)
                .build()

            Log.v(tag, "🧭 Checking expected direction: $currentLocation → $destination, heading=${deviceHeading.toInt()}°")

            val response = client.newCall(request).execute()
            val responseBody = response.body?.string()

            if (response.isSuccessful && responseBody != null) {
                val apiResponse = gson.fromJson(responseBody, ExpectedDirectionResponse::class.java)

                val expectedData = ExpectedDirectionData(
                    expectedDirection = apiResponse.expected_direction ?: 0f,
                    expectedInstruction = apiResponse.expected_instruction ?: "Continue",
                    deviation = apiResponse.deviation ?: 0f,
                    onPath = apiResponse.on_path ?: true,
                    nextWaypoint = apiResponse.next_waypoint,
                    nextWaypointName = apiResponse.next_waypoint_name
                )

                Log.v(tag, "✅ Expected direction: ${expectedData.expectedDirection.toInt()}°, deviation: ${expectedData.deviation.toInt()}°, on_path: ${expectedData.onPath}")
                Result.success(expectedData)
            } else {
                val error = "Failed to get expected direction: ${response.code}"
                Log.e(tag, error)
                Result.failure(Exception(error))
            }
        } catch (e: Exception) {
            Log.e(tag, "Error checking expected direction: ${e.message}")
            Result.failure(e)
        }
    }
}

data class NavigationInstruction(
    val success: Boolean = true,
    val error: String? = null,
    val currentLocation: String,
    val destination: String? = null,
    val instruction: String,
    val voiceText: String,
    val turnDirection: String? = null,
    val distanceRemaining: Int = 0,
    val path: List<String> = emptyList()
)

data class ExpectedDirectionResponse(
    val expected_direction: Float? = null,
    val expected_instruction: String? = null,
    val deviation: Float? = null,
    val on_path: Boolean? = null,
    val next_waypoint: String? = null,
    val next_waypoint_name: String? = null,
    val error: String? = null
)

data class ExpectedDirectionData(
    val expectedDirection: Float,
    val expectedInstruction: String,
    val deviation: Float,
    val onPath: Boolean,
    val nextWaypoint: String? = null,
    val nextWaypointName: String? = null
)
