package com.example.indoornav

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.speech.tts.TextToSpeech
import android.util.Log
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import java.util.*

/**
 * ClientNavigationApp.kt (+ ViewModel)
 *
 * Members involved in this file
 * -----------------------------------------------------------
 * TEO QIYANG 22ACB06185 — Integration (Owner)
 *   - ViewModel orchestration: session, destination selection,
 *     QR scan pipeline, real-time expected-direction polling.
 *   - Network calls via NavigationClient and lifecycle handling.
 *
 * CHONG WIN NIE 22ACB05895 — Compass
 *   - Supplies device heading into the QR send and expected-direction calls.
 *   - Starts/stops CompassManager listening and provides current heading.
 *
 * ONG XIANG QI 22ACB06240 — Navigation Feedback
 *   - Voice (TTS) and haptic feedback triggers based on instruction strings.
 *   - Off-path feedback scheduling/throttling (grace period + warning interval).
 *
 * WONG YEN MING 22ACB05035 — UI
 *   - Compose screens, state bindings, and permission prompt.
 *   - Display of headings, path status, and instruction cards.
 *
 * Notes
 * -----------------------------------------------------------
 * Logic unchanged. All modifications are comment/attribution only.
 */
class ClientNavigationViewModel(application: android.app.Application) : AndroidViewModel(application) {
    private val tag = "ClientNavigationViewModel"

    // [TEO QIYANG — Integration] HTTP client to Python backend
    private val navClient = NavigationClient(application)

    // [CHONG WIN NIE — Compass] Device heading source
    private val compassManager = CompassManager(application)

    // [ONG XIANG QI — Feedback] Haptic feedback for instruction cues
    private val hapticManager = HapticFeedbackManager(application)

    // [ONG XIANG QI — Feedback] Text-to-Speech for spoken directions
    private var textToSpeech: TextToSpeech? = null

    // [WONG YEN MING — UI] Screen routing
    private val _currentScreen = MutableStateFlow(ClientScreen.CONNECTING)
    val currentScreen: StateFlow<ClientScreen> = _currentScreen.asStateFlow()

    // [TEO QIYANG — Integration] Connection status
    private val _connectionStatus = MutableStateFlow("Connecting...")
    val connectionStatus: StateFlow<String> = _connectionStatus.asStateFlow()

    // [TEO QIYANG — Integration] Destination list from server
    private val _destinations = MutableStateFlow<List<NavigationClient.Destination>>(emptyList())
    val destinations: StateFlow<List<NavigationClient.Destination>> = _destinations.asStateFlow()

    // [TEO QIYANG — Integration] Currently selected destination
    private val _selectedDestination = MutableStateFlow<NavigationClient.Destination?>(null)
    val selectedDestination: StateFlow<NavigationClient.Destination?> = _selectedDestination.asStateFlow()

    // [TEO QIYANG — Integration] Location label updated after QR scan
    private val _currentLocation = MutableStateFlow("Scan QR code to locate")
    val currentLocation: StateFlow<String> = _currentLocation.asStateFlow()

    // [ONG XIANG QI — Feedback] Instruction text surfaced to UI
    private val _navigationInstruction = MutableStateFlow("Waiting for QR scan...")
    val navigationInstruction: StateFlow<String> = _navigationInstruction.asStateFlow()

    // [WONG YEN MING — UI] Busy flag for disabling inputs
    private val _isProcessing = MutableStateFlow(false)
    val isProcessing: StateFlow<Boolean> = _isProcessing.asStateFlow()

    // [CHONG WIN NIE — Compass] Device heading degrees (0–359)
    private val _currentHeading = MutableStateFlow(0f)
    val currentHeading: StateFlow<Float> = _currentHeading.asStateFlow()

    // [CHONG WIN NIE — Compass] Availability of sensors
    private val _compassAvailable = MutableStateFlow(false)
    val compassAvailable: StateFlow<Boolean> = _compassAvailable.asStateFlow()

    // [TEO QIYANG — Integration] Real-time path monitoring states
    private val _pathDeviation = MutableStateFlow(0f)
    val pathDeviation: StateFlow<Float> = _pathDeviation.asStateFlow()

    private val _onPath = MutableStateFlow(true)
    val onPath: StateFlow<Boolean> = _onPath.asStateFlow()

    private val _expectedDirection = MutableStateFlow(0f)
    val expectedDirection: StateFlow<Float> = _expectedDirection.asStateFlow()

    // [TEO QIYANG — Integration] Monitoring coroutine management
    private var isRealTimeMonitoring = false
    private var realTimeMonitoringJob: kotlinx.coroutines.Job? = null

    // [ONG XIANG QI — Feedback] Grace period after QR to allow turning
    private var lastQrScanTime = 0L
    private val qrGracePeriodMs = 8000L

    // [ONG XIANG QI — Feedback] Debounce and “same QR” prevention
    private var lastQrTime = 0L
    private val qrDebounceMs = 500L
    private var lastQrCode = ""
    private var lastQrCodeTime = 0L
    private val sameQrPreventMs = 3000L

    enum class ClientScreen {
        CONNECTING, DESTINATIONS, NAVIGATION
    }

    init {
        // [ONG XIANG QI — Feedback] TTS setup
        initializeTts()
        // [CHONG WIN NIE — Compass] Start sensor flows
        initializeCompass()
        // [TEO QIYANG — Integration] Connect to backend and create session
        connectToServer()
    }

    private fun initializeCompass() {
        // [CHONG WIN NIE — Compass] Heading updates
        viewModelScope.launch {
            compassManager.heading.collect { heading ->
                _currentHeading.value = heading
            }
        }
        // [CHONG WIN NIE — Compass] Availability + start listening
        viewModelScope.launch {
            compassManager.isAvailable.collect { available ->
                _compassAvailable.value = available
                if (available) {
                    compassManager.startListening()
                    Log.d(tag, "Compass started successfully")
                } else {
                    Log.w(tag, "Compass not available on this device")
                }
            }
        }
    }

    private fun initializeTts() {
        // [ONG XIANG QI — Feedback] TTS lifecycle
        textToSpeech = TextToSpeech(getApplication()) { status ->
            if (status == TextToSpeech.SUCCESS) {
                textToSpeech?.language = Locale.US
                Log.d(tag, "TTS initialized successfully")
            } else {
                Log.e(tag, "TTS initialization failed")
            }
        }
    }

    private fun connectToServer() {
        // [TEO QIYANG — Integration] Create backend session and fetch destinations
        viewModelScope.launch {
            try {
                _connectionStatus.value = "Connecting to server..."

                val result = navClient.createSession("Mobile User ${System.currentTimeMillis() % 1000}")

                if (result.isSuccess) {
                    _connectionStatus.value = "Connected to server"
                    speak("Connected to navigation server")
                    loadDestinations()
                } else {
                    _connectionStatus.value = "Connection failed: ${result.exceptionOrNull()?.message}"
                    speak("Connection failed")
                }

            } catch (e: Exception) {
                _connectionStatus.value = "Connection error: ${e.message}"
                Log.e(tag, "Connection error", e)
                speak("Connection error")
            }
        }
    }

    private fun loadDestinations() {
        // [TEO QIYANG — Integration] Populate destination list
        viewModelScope.launch {
            try {
                val result = navClient.getDestinations()

                if (result.isSuccess) {
                    _destinations.value = result.getOrNull() ?: emptyList()
                    _currentScreen.value = ClientScreen.DESTINATIONS
                    Log.d(tag, "Loaded ${_destinations.value.size} destinations")
                } else {
                    _connectionStatus.value = "Failed to load destinations"
                    Log.e(tag, "Failed to load destinations: ${result.exceptionOrNull()?.message}")
                }

            } catch (e: Exception) {
                _connectionStatus.value = "Error loading destinations: ${e.message}"
                Log.e(tag, "Error loading destinations", e)
            }
        }
    }

    fun selectDestination(destination: NavigationClient.Destination) {
        // [TEO QIYANG — Integration] Send chosen destination to backend
        viewModelScope.launch {
            try {
                _isProcessing.value = true

                val result = navClient.setDestination(destination.id)

                if (result.isSuccess) {
                    _selectedDestination.value = destination
                    _currentScreen.value = ClientScreen.NAVIGATION
                    _navigationInstruction.value = "Scan QR code to start navigation"

                    // [ONG XIANG QI — Feedback] Speak confirmation
                    speak("Destination set to ${destination.name}. Please scan a QR code to begin navigation.")
                    Log.d(tag, "Destination set: ${destination.name}")
                } else {
                    speak("Failed to set destination")
                    Log.e(tag, "Failed to set destination: ${result.exceptionOrNull()?.message}")
                }

            } catch (e: Exception) {
                speak("Error setting destination")
                Log.e(tag, "Error setting destination", e)
            } finally {
                _isProcessing.value = false
            }
        }
    }

    fun processQrCode(qrValue: String) {
        val currentTime = System.currentTimeMillis()

        // [ONG XIANG QI — Feedback] Global QR debounce
        if (currentTime - lastQrTime < qrDebounceMs) {
            Log.d(tag, "QR scan debounced")
            return
        }
        // [ONG XIANG QI — Feedback] Prevent rapid duplicate QR scans
        if (qrValue == lastQrCode && currentTime - lastQrCodeTime < sameQrPreventMs) {
            Log.d(tag, "Same QR code scanned within 3 seconds, ignoring")
            return
        }
        lastQrTime = currentTime
        lastQrCode = qrValue
        lastQrCodeTime = currentTime

        // [TEO QIYANG — Integration] Send QR + heading to backend
        viewModelScope.launch {
            try {
                _isProcessing.value = true
                _navigationInstruction.value = "Processing QR code..."

                // [CHONG WIN NIE — Compass] Supply current heading
                val currentHeadingValue = _currentHeading.value
                val result = navClient.processQrScan(qrValue, currentHeadingValue)

                if (result.isSuccess) {
                    val instruction = result.getOrNull()!!

                    _currentLocation.value = instruction.currentLocation
                    _navigationInstruction.value = instruction.instruction

                    // [ONG XIANG QI — Feedback] Start grace period after a scan
                    lastQrScanTime = System.currentTimeMillis()

                    // [ONG XIANG QI — Feedback] Speak and vibrate
                    speak(instruction.voiceText)
                    hapticManager.provideNavigationFeedback(instruction.instruction)

                    Log.d(tag, "Navigation: ${instruction.instruction}")

                    // [TEO QIYANG — Integration] Start real-time off-path checks
                    Log.d(tag, "QR Response - Current: '${instruction.currentLocation}', Destination: '${instruction.destination}'")
                    if (instruction.destination != null && !instruction.destination.isEmpty() && instruction.currentLocation.isNotEmpty()) {
                        startRealTimeMonitoring(instruction.currentLocation, instruction.destination)
                    } else {
                        Log.w(tag, "Cannot start real-time monitoring - missing data. Current: '${instruction.currentLocation}', Destination: '${instruction.destination}'")
                    }

                    if (!instruction.success && instruction.error != null) {
                        Log.w(tag, "Navigation warning: ${instruction.error}")
                    }

                } else {
                    val error = "Network error: ${result.exceptionOrNull()?.message}"
                    _navigationInstruction.value = error
                    speak("Network error")
                    Log.e(tag, error)
                }

            } catch (e: Exception) {
                val error = "Error processing QR: ${e.message}"
                _navigationInstruction.value = error
                speak("QR processing error")
                Log.e(tag, error, e)
            } finally {
                _isProcessing.value = false
            }
        }
    }

    fun goBack() {
        // [WONG YEN MING — UI] Back behavior between screens
        when (_currentScreen.value) {
            ClientScreen.NAVIGATION -> {
                stopRealTimeMonitoring()
                _selectedDestination.value = null
                _currentScreen.value = ClientScreen.DESTINATIONS
                _navigationInstruction.value = "Select destination"
            }
            ClientScreen.DESTINATIONS -> {
                connectToServer()
            }
            else -> { /* no-op */ }
        }
    }

    private fun speak(text: String) {
        // [ONG XIANG QI — Feedback] Voice output
        textToSpeech?.speak(text, TextToSpeech.QUEUE_FLUSH, null, "nav_instruction")
    }

    /**
     * Start real-time path monitoring (expected direction vs current heading).
     * [TEO QIYANG — Integration] owner
     */
    private fun startRealTimeMonitoring(initialLocation: String, targetDestination: String) {
        stopRealTimeMonitoring()

        isRealTimeMonitoring = true
        realTimeMonitoringJob = viewModelScope.launch {
            Log.d(tag, "🚶 Started real-time path monitoring: $initialLocation → $targetDestination")

            while (isRealTimeMonitoring) {
                try {
                    // [CHONG WIN NIE — Compass] Live heading
                    val currentHeadingValue = _currentHeading.value

                    // [TEO QIYANG — Integration] Use last QR location and selected destination
                    val currentLocationValue = _currentLocation.value
                    val selectedDest = _selectedDestination.value

                    if (selectedDest != null && !currentLocationValue.contains("Scan QR")) {
                        val currentTime = System.currentTimeMillis()
                        val timeSinceQrScan = currentTime - lastQrScanTime
                        val isInGracePeriod = timeSinceQrScan < qrGracePeriodMs

                        // [TEO QIYANG — Integration] Backend expected-direction check
                        Log.v(tag, "Real-time check - Sending: Current='$currentLocationValue', Destination='${selectedDest.id}', Heading=${currentHeadingValue.toInt()}°")
                        val result = navClient.checkExpectedDirection(currentLocationValue, selectedDest.id, currentHeadingValue)

                        if (result.isSuccess) {
                            val expectedData = result.getOrNull()!!

                            // [WONG YEN MING — UI] Update live indicators
                            _expectedDirection.value = expectedData.expectedDirection
                            _pathDeviation.value = expectedData.deviation

                            if (isInGracePeriod) {
                                // [ONG XIANG QI — Feedback] Grace window: force ON PATH
                                _onPath.value = true
                                Log.v(tag, "🕐 Grace period active (${(qrGracePeriodMs - timeSinceQrScan) / 1000}s remaining) - forcing ON PATH")
                            } else {
                                // Normal evaluation
                                _onPath.value = expectedData.onPath

                                // [ONG XIANG QI — Feedback] If off-path, provide guidance
                                if (!expectedData.onPath) {
                                    handleOffPathFeedback(expectedData)
                                }
                            }

                            Log.v(tag, "🧭 Path check - Expected: ${expectedData.expectedDirection.toInt()}°, Current: ${currentHeadingValue.toInt()}°, Deviation: ${expectedData.deviation.toInt()}°, Grace period: $isInGracePeriod, On path: ${_onPath.value}")
                        } else {
                            Log.w(tag, "Failed to check expected direction: ${result.exceptionOrNull()?.message}")
                        }
                    } else {
                        Log.v(tag, "Skipping real-time check - no valid destination or location")
                    }

                } catch (e: Exception) {
                    Log.e(tag, "Real-time monitoring error", e)
                }

                // Polling cadence
                kotlinx.coroutines.delay(2000)
            }
        }
    }

    /**
     * Stop real-time path monitoring.
     * [TEO QIYANG — Integration] owner
     */
    private fun stopRealTimeMonitoring() {
        isRealTimeMonitoring = false
        realTimeMonitoringJob?.cancel()
        realTimeMonitoringJob = null
        Log.d(tag, "🛑 Stopped real-time path monitoring")
    }

    /**
     * Off-path haptic + voice feedback with throttling.
     * [ONG XIANG QI — Navigation Feedback] owner
     */
    private var lastOffPathWarning = 0L
    private val offPathWarningInterval = 5000L

    private fun handleOffPathFeedback(expectedData: ExpectedDirectionData) {
        val currentTime = System.currentTimeMillis()

        // Throttle to avoid spamming
        if (currentTime - lastOffPathWarning < offPathWarningInterval) {
            return
        }
        lastOffPathWarning = currentTime

        // Voice guidance
        speak("You are off course. ${expectedData.expectedInstruction}")

        // Haptic cue based on suggested correction
        when {
            expectedData.expectedInstruction.contains("Turn right", ignoreCase = true) -> {
                hapticManager.provideNavigationFeedback("Turn right")
            }
            expectedData.expectedInstruction.contains("Turn left", ignoreCase = true) -> {
                hapticManager.provideNavigationFeedback("Turn left")
            }
            else -> {
                hapticManager.provideNavigationFeedback("Go straight")
            }
        }

        Log.i(tag, "🚨 Off-path warning: ${expectedData.expectedInstruction}")
    }

    override fun onCleared() {
        super.onCleared()
        // [TEO QIYANG — Integration] Cleanup
        stopRealTimeMonitoring()
        // [CHONG WIN NIE — Compass] Stop sensors
        compassManager.stopListening()
        // [ONG XIANG QI — Feedback] Stop vibrations and TTS
        hapticManager.stopVibration()
        textToSpeech?.shutdown()
        // [TEO QIYANG — Integration] Clear session cache
        navClient.clearSession()
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ClientNavigationApp() {
    // [TEO QIYANG — Integration] Provide VM
    val viewModel: ClientNavigationViewModel = viewModel()
    val currentScreen by viewModel.currentScreen.collectAsState()

    // [WONG YEN MING — UI] App scaffold and routing
    MaterialTheme {
        Scaffold(
            topBar = {
                TopAppBar(
                    title = { Text("📱 Navigation Client") },
                    actions = {
                        if (currentScreen != ClientNavigationViewModel.ClientScreen.CONNECTING) {
                            IconButton(onClick = { viewModel.goBack() }) {
                                Icon(Icons.Default.ArrowBack, "Back")
                            }
                        }
                    }
                )
            }
        ) { paddingValues ->
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(paddingValues)
            ) {
                when (currentScreen) {
                    ClientNavigationViewModel.ClientScreen.CONNECTING -> {
                        ConnectionScreen(viewModel)
                    }
                    ClientNavigationViewModel.ClientScreen.DESTINATIONS -> {
                        DestinationsScreen(viewModel)
                    }
                    ClientNavigationViewModel.ClientScreen.NAVIGATION -> {
                        NavigationScreen(viewModel)
                    }
                }
            }
        }
    }
}

@Composable
fun ConnectionScreen(viewModel: ClientNavigationViewModel) {
    // [WONG YEN MING — UI] Simple status page
    val status by viewModel.connectionStatus.collectAsState()

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(32.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        Icon(
            Icons.Default.Wifi,
            contentDescription = "Connecting",
            modifier = Modifier.size(64.dp),
            tint = MaterialTheme.colorScheme.primary
        )

        Spacer(modifier = Modifier.height(24.dp))

        Text(
            text = "Connecting to Server",
            style = MaterialTheme.typography.headlineSmall,
            fontWeight = FontWeight.Bold,
            textAlign = TextAlign.Center
        )

        Spacer(modifier = Modifier.height(16.dp))

        Text(
            text = status,
            style = MaterialTheme.typography.bodyLarge,
            textAlign = TextAlign.Center,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )

        Spacer(modifier = Modifier.height(32.dp))

        CircularProgressIndicator()
    }
}

@Composable
private fun NavigationHelpCard() {
    // [WONG YEN MING — UI] Quick help card for users
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .padding(bottom = 12.dp),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceVariant
        )
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(
                    imageVector = Icons.Default.Info,
                    contentDescription = "Info",
                    tint = MaterialTheme.colorScheme.primary
                )
                Spacer(modifier = Modifier.width(8.dp))
                Text(
                    text = "How navigation works",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold
                )
            }
            Spacer(modifier = Modifier.height(8.dp))

            Text(
                text = """
The navigation will use voice and vibration:
• 1 buzz = Go straight
• 2 buzzes = Turn right
• 3 buzzes = Turn backward
• 4 buzzes = Turn left

If you’re off-path by about 25°, the system will speak and guide you back.

Please scan the floor QR code while holding your phone naturally at ~45°.
                """.trimIndent(),
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                lineHeight = 18.sp
            )
        }
    }
}

@Composable
fun DestinationsScreen(viewModel: ClientNavigationViewModel) {
    // [WONG YEN MING — UI] Destination list
    val destinations by viewModel.destinations.collectAsState()
    val isProcessing by viewModel.isProcessing.collectAsState()

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp)
    ) {
        Text(
            text = "Select Destination",
            style = MaterialTheme.typography.headlineSmall,
            fontWeight = FontWeight.Bold,
            modifier = Modifier.padding(bottom = 16.dp)
        )

        NavigationHelpCard()

        if (destinations.isEmpty()) {
            Box(
                modifier = Modifier.fillMaxSize(),
                contentAlignment = Alignment.Center
            ) {
                CircularProgressIndicator()
            }
        } else {
            LazyColumn(
                verticalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                items(destinations) { destination ->
                    Card(
                        modifier = Modifier
                            .fillMaxWidth(),
                        onClick = {
                            if (!isProcessing) {
                                viewModel.selectDestination(destination)
                            }
                        },
                        enabled = !isProcessing
                    ) {
                        Column(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(16.dp)
                        ) {
                            Text(
                                text = destination.name,
                                style = MaterialTheme.typography.titleMedium,
                                fontWeight = FontWeight.Bold
                            )
                            Text(
                                text = "Floor: ${destination.floor}",
                                style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                    }
                }
            }
        }

        if (isProcessing) {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(16.dp),
                contentAlignment = Alignment.Center
            ) {
                CircularProgressIndicator()
            }
        }
    }
}

@Composable
fun NavigationScreen(viewModel: ClientNavigationViewModel) {
    // [WONG YEN MING — UI] Scanner + instruction container
    val context = LocalContext.current
    val selectedDestination by viewModel.selectedDestination.collectAsState()
    val currentLocation by viewModel.currentLocation.collectAsState()
    val instruction by viewModel.navigationInstruction.collectAsState()
    val isProcessing by viewModel.isProcessing.collectAsState()

    // Camera permission (UI-moderated)
    val cameraPermissionLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestPermission()
    ) { isGranted ->
        if (isGranted) {
            Log.d("NavigationScreen", "Camera permission granted")
        }
    }

    LaunchedEffect(Unit) {
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA)
            != PackageManager.PERMISSION_GRANTED) {
            cameraPermissionLauncher.launch(Manifest.permission.CAMERA)
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp)
    ) {
        // Destination card
        Card(
            modifier = Modifier
                .fillMaxWidth()
                .padding(bottom = 16.dp)
        ) {
            Column(
                modifier = Modifier.padding(16.dp)
            ) {
                Text(
                    text = "Destination",
                    style = MaterialTheme.typography.titleSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                Text(
                    text = selectedDestination?.name ?: "No destination selected",
                    style = MaterialTheme.typography.headlineSmall,
                    fontWeight = FontWeight.Bold
                )

                Spacer(modifier = Modifier.height(8.dp))

                Text(
                    text = "Current Location",
                    style = MaterialTheme.typography.titleSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                Text(
                    text = currentLocation,
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Medium
                )

                Spacer(modifier = Modifier.height(8.dp))

                // Live heading
                val heading by viewModel.currentHeading.collectAsState()
                val compassAvailable by viewModel.compassAvailable.collectAsState()

                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text(
                        text = "Device Heading",
                        style = MaterialTheme.typography.titleSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )

                    if (compassAvailable) {
                        Text(
                            text = "${heading.toInt()}°",
                            style = MaterialTheme.typography.titleMedium,
                            fontWeight = FontWeight.Bold,
                            color = MaterialTheme.colorScheme.primary
                        )
                    } else {
                        Text(
                            text = "Not Available",
                            style = MaterialTheme.typography.titleMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                }

                Spacer(modifier = Modifier.height(8.dp))

                // Real-time status
                val pathDeviation by viewModel.pathDeviation.collectAsState()
                val onPath by viewModel.onPath.collectAsState()
                val expectedDirection by viewModel.expectedDirection.collectAsState()

                Card(
                    modifier = Modifier.fillMaxWidth(),
                    colors = CardDefaults.cardColors(
                        containerColor = if (onPath) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.errorContainer
                    )
                ) {
                    Column(
                        modifier = Modifier.padding(12.dp)
                    ) {
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Text(
                                text = "Path Status",
                                style = MaterialTheme.typography.titleSmall,
                                color = if (onPath) MaterialTheme.colorScheme.onPrimaryContainer else MaterialTheme.colorScheme.onErrorContainer
                            )

                            Text(
                                text = if (onPath) "ON PATH" else "OFF PATH",
                                style = MaterialTheme.typography.labelLarge,
                                fontWeight = FontWeight.Bold,
                                color = if (onPath) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.error
                            )
                        }

                        if (expectedDirection > 0) {
                            Spacer(modifier = Modifier.height(4.dp))
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.SpaceBetween
                            ) {
                                Text(
                                    text = "Expected: ${expectedDirection.toInt()}°",
                                    style = MaterialTheme.typography.bodySmall,
                                    color = if (onPath) MaterialTheme.colorScheme.onPrimaryContainer else MaterialTheme.colorScheme.onErrorContainer
                                )
                                Text(
                                    text = "Deviation: ${pathDeviation.toInt()}°",
                                    style = MaterialTheme.typography.bodySmall,
                                    color = if (onPath) MaterialTheme.colorScheme.onPrimaryContainer else MaterialTheme.colorScheme.onErrorContainer
                                )
                            }
                        }
                    }
                }
            }
        }

        // Instruction card
        Card(
            modifier = Modifier
                .fillMaxWidth()
                .padding(bottom = 16.dp),
            colors = CardDefaults.cardColors(
                containerColor = MaterialTheme.colorScheme.primaryContainer
            )
        ) {
            Column(
                modifier = Modifier.padding(16.dp)
            ) {
                Text(
                    text = "Navigation Instructions",
                    style = MaterialTheme.typography.titleSmall,
                    color = MaterialTheme.colorScheme.onPrimaryContainer
                )
                Text(
                    text = instruction,
                    style = MaterialTheme.typography.titleLarge,
                    fontWeight = FontWeight.Bold,
                    color = MaterialTheme.colorScheme.onPrimaryContainer,
                    textAlign = TextAlign.Center,
                    modifier = Modifier.fillMaxWidth()
                )
            }
        }

        // QR Scanner area
        Card(
            modifier = Modifier.fillMaxWidth()
        ) {
            Column(
                modifier = Modifier.padding(16.dp),
                horizontalAlignment = Alignment.CenterHorizontally
            ) {
                Text(
                    text = "QR Code Scanner",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold,
                    modifier = Modifier.padding(bottom = 16.dp)
                )

                if (isProcessing) {
                    CircularProgressIndicator(
                        modifier = Modifier.padding(32.dp)
                    )
                    Text(
                        text = "Processing...",
                        style = MaterialTheme.typography.bodyLarge,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                } else {
                    // [WONG YEN MING — UI] Scanner preview; emits QR strings
                    SimpleQrScanner(
                        onQrScanned = { qrValue ->
                            viewModel.processQrCode(qrValue)
                        }
                    )
                }
            }
        }

        Spacer(modifier = Modifier.height(16.dp))

        // Manual QR input fallback
        var manualQr by remember { mutableStateOf("") }

        OutlinedTextField(
            value = manualQr,
            onValueChange = { manualQr = it },
            label = { Text("Enter QR Code") },
            modifier = Modifier
                .fillMaxWidth()
                .padding(bottom = 8.dp)
        )

        Button(
            onClick = {
                if (manualQr.isNotBlank()) {
                    viewModel.processQrCode(manualQr)
                    manualQr = ""
                }
            },
            modifier = Modifier.fillMaxWidth(),
            enabled = !isProcessing && manualQr.isNotBlank()
        ) {
            Text("Process QR Code")
        }
    }
}

@Composable
fun SimpleQrScanner(onQrScanned: (String) -> Unit) {
    // [WONG YEN MING — UI] Wrap CameraX+MLKit component
    QRScannerCompose(
        onQrScanned = onQrScanned,
        isProcessing = false
    )
}
