package com.example.indoornav

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.ui.Modifier

/**
 * MainActivity.kt
 *
 * Members involved in this file
 * -----------------------------------------------------------
 * WONG YEN MING 22ACB05035 — UI
 *   - Composable app shell and theming container.
 *
 * TEO QIYANG 22ACB06185 — Integration
 *   - Wires the app entry point to the composable navigation app.
 *
 */
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            // [WONG YEN MING — UI]
            MaterialTheme {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = MaterialTheme.colorScheme.background
                ) {
                    // [TEO QIYANG — Integration] Hook main composable
                    ClientNavigationApp()
                }
            }
        }
    }
}
