package com.example.indoornav

import android.content.Context
import android.os.Build
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import android.util.Log

/**
 * HapticFeedbackManager.kt
 *
 * Members involved in this file
 * -----------------------------------------------------------
 * ONG XIANG QI 22ACB06240 — Navigation Feedback
 *   - Maps instruction words to vibration patterns.
 *   - Exposes a single call: provideNavigationFeedback(instruction).
 *   - Handles platform differences and stop control.
 *
 */
class HapticFeedbackManager(private val context: Context) {

    private val tag = "HapticFeedbackManager"

    // Vibrator handle (API 31+ uses VibratorManager)
    private val vibrator: Vibrator = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
        val vibratorManager = context.getSystemService(Context.VIBRATOR_MANAGER_SERVICE) as VibratorManager
        vibratorManager.defaultVibrator
    } else {
        @Suppress("DEPRECATION")
        context.getSystemService(Context.VIBRATOR_SERVICE) as Vibrator
    }

    /**
     * Choose pattern based on the instruction string.
     * Categories: left, right, straight/continue, backward/turn around, bear left/right.
     */
    fun provideNavigationFeedback(instruction: String) {
        if (!vibrator.hasVibrator()) {
            Log.w(tag, "Device does not have vibrator")
            return
        }

        val pattern = when {
            instruction.contains("left", ignoreCase = true) -> getLeftTurnPattern()
            instruction.contains("right", ignoreCase = true) -> getRightTurnPattern()
            instruction.contains("straight", ignoreCase = true) || instruction.contains("continue", ignoreCase = true) -> getStraightPattern()
            instruction.contains("backward", ignoreCase = true) || instruction.contains("turn around", ignoreCase = true) -> getBackwardPattern()
            instruction.contains("bear left", ignoreCase = true) -> getSlightLeftPattern()
            instruction.contains("bear right", ignoreCase = true) -> getSlightRightPattern()
            else -> getStraightPattern() // default
        }

        vibrate(pattern)
        Log.d(tag, "Haptic feedback for: $instruction")
    }

    // Patterns (unchanged)
    private fun getLeftTurnPattern(): VibrationPattern {
        return VibrationPattern(
            timings = longArrayOf(0, 500, 200, 500, 200, 500, 200, 500),
            amplitudes = intArrayOf(0, 200, 0, 200, 0, 200, 0, 200),
            description = "Left Turn - 4 vibrations"
        )
    }

    private fun getRightTurnPattern(): VibrationPattern {
        return VibrationPattern(
            timings = longArrayOf(0, 500, 200, 500),
            amplitudes = intArrayOf(0, 200, 0, 200),
            description = "Right Turn - 2 vibrations"
        )
    }

    private fun getStraightPattern(): VibrationPattern {
        return VibrationPattern(
            timings = longArrayOf(0, 500),
            amplitudes = intArrayOf(0, 200),
            description = "Go Straight - 1 vibration"
        )
    }

    private fun getBackwardPattern(): VibrationPattern {
        return VibrationPattern(
            timings = longArrayOf(0, 500, 200, 500, 200, 500),
            amplitudes = intArrayOf(0, 200, 0, 200, 0, 200),
            description = "Turn Around - 3 vibrations"
        )
    }

    private fun getSlightLeftPattern(): VibrationPattern {
        return VibrationPattern(
            timings = longArrayOf(0, 500, 200, 500, 200, 500, 200, 500),
            amplitudes = intArrayOf(0, 200, 0, 200, 0, 200, 0, 200),
            description = "Bear Left - 4 vibrations"
        )
    }

    private fun getSlightRightPattern(): VibrationPattern {
        return VibrationPattern(
            timings = longArrayOf(0, 500, 200, 500),
            amplitudes = intArrayOf(0, 200, 0, 200),
            description = "Bear Right - 2 vibrations"
        )
    }

    private fun vibrate(pattern: VibrationPattern) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val effect = VibrationEffect.createWaveform(pattern.timings, pattern.amplitudes, -1)
            vibrator.vibrate(effect)
            Log.d(tag, "Vibrating with pattern: ${pattern.description}")
        } else {
            @Suppress("DEPRECATION")
            vibrator.vibrate(pattern.timings, -1)
            Log.d(tag, "Legacy vibration: ${pattern.description}")
        }
    }

    /** Stop any ongoing vibration. */
    fun stopVibration() {
        vibrator.cancel()
        Log.d(tag, "Vibration stopped")
    }

    private data class VibrationPattern(
        val timings: LongArray,
        val amplitudes: IntArray,
        val description: String
    )
}
