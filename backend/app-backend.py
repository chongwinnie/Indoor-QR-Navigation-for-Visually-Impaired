"""
Indoor Navigation Server

Team Contributions
------------------
WONG YEN MING 22ACB05035 (Path Calculation & Navigation)
  • A* pathfinding + distance math
  • Functions: heuristic(), find_shortest_path(), calculate_path_distance()
  • Turn logic from movement geometry: get_turn_direction()

CHONG WIN NIE 22ACB05895 (Compass & Off-Path Handling)
  • Compass model + calibration and on/off-path detection
  • Data & config: MAP_COMPASS, compass section in load_map_data()
  • First-scan heading guidance: get_direction_from_device_heading()
  • Live deviation + turn hints and tolerance: /api/expected-direction

ONG XIANG QI 22ACB06240 (Navigation Feedback & Dashboard)
  • User-facing guidance text/voice and arrival messaging
  • Functions: get_navigation_instruction(), get_expected_direction() API
  • Dashboard rendering (DASHBOARD_HTML) and live session overlay

TEO QIYANG 22ACB06185 (Integration)
  • Flask app wiring, routes, and session state
  • Functions/APIs: load_map_data(), create_session(), set_destination(), scan_qr(),
                    get_users(), get_session()
  • Flow: QR scans → A* path → guidance → dashboard
"""

from flask import Flask, request, jsonify, render_template_string, send_from_directory
import json
import uuid
import time
import os
import heapq
import math
from datetime import datetime
from typing import Dict, List

app = Flask(__name__)

# =============================================================================
# GLOBAL STATE & MAP LOADING
# =============================================================================
# [TEO QIYANG 22ACB06185: Integration]
# [CHONG WIN NIE 22ACB05895: Compass & Off-Path] Central compass model used by
# heading math and deviation checks. 'compass_calibration' is applied to device readings.
MAP_COMPASS = {
    "north_direction": 0,     # Degrees (0 = map north pointing up) [CHONG WIN NIE]
    "compass_center": None,   # Optional visual anchor for UI compass [CHONG WIN NIE]
    "compass_calibration": 0  # Degrees added to device heading to correct bias [CHONG WIN NIE]
}

# [TEO QIYANG 22ACB06185: Integration]
# Load map_compiled.json (nodes, edges, optional compass info) into the in-memory graph.
def load_map_data():
    try:
        with open('map_compiled.json', 'r') as f:
            map_data = json.load(f)

        # Convert JSON to internal graph format
        nodes = {}
        for node_id, node_info in map_data['nodes'].items():
            nodes[node_id] = {
                "name": node_info['name'],
                "pos": node_info['position'],   # [x, y] pixel coords
                "connections": []               # neighbors populated below
            }

        # Undirected edges: add both ways
        for connection in map_data['connections']:
            node1, node2 = connection[0], connection[1]
            if node1 in nodes and node2 in nodes:
                nodes[node1]['connections'].append(node2)
                nodes[node2]['connections'].append(node1)

        # [CHONG WIN NIE 22ACB05895: Compass & Off-Path]
        # Load compass config if present; unified reference for heading math.
        if 'compass' in map_data:
            compass_info = map_data['compass']
            MAP_COMPASS['north_direction'] = compass_info.get('north_direction', 0)
            MAP_COMPASS['compass_center'] = compass_info.get('compass_center')
            MAP_COMPASS['compass_calibration'] = compass_info.get('compass_calibration', 0)
            print(f"Loaded map compass: North = {MAP_COMPASS['north_direction']}°, Calibration = +{MAP_COMPASS['compass_calibration']}°")

        print(f"Map loaded: {len(nodes)} nodes, {len([n for n in nodes.keys() if n.startswith('R')])} rooms")
        return nodes

    except Exception as e:
        # Safe fallback if the JSON is missing/invalid
        print(f"Error loading map data: {e}")
        return {
            "R001": {"name": "Room A", "pos": [100, 100], "connections": ["C001"]},
            "R002": {"name": "Room B", "pos": [300, 100], "connections": ["C002"]},
            "R003": {"name": "Room C", "pos": [500, 100], "connections": ["C003"]},
        }

# [TEO QIYANG 22ACB06185: Integration]
MAP_NODES = load_map_data()

# [TEO QIYANG 22ACB06185: Integration]
# In-memory session store for users (mobile clients)
users = {}

# [TEO QIYANG 22ACB06185: Integration]
# Short movement history per session (helps infer left/right/straight)
user_movement_history = {}

# [TEO QIYANG 22ACB06185: Integration]
# Build the list of valid destinations (rooms only) for clients to choose
destinations = []
for node_id, node_info in MAP_NODES.items():
    if node_id.startswith('R'):
        destinations.append({
            "id": node_id,
            "name": node_info['name'],
            "floor": "Ground"
        })

print(f"Destinations loaded: {len(destinations)} rooms available")

# =============================================================================
# STATIC FILES (map background image)
# =============================================================================
# [TEO QIYANG 22ACB06185: Integration]
@app.route('/static/<filename>')
def static_files(filename):
    """Serve static files like the map image."""
    return send_from_directory('static', filename)

# =============================================================================
# PATHFINDING & NAVIGATION CORE
# =============================================================================

# [WONG YEN MING 22ACB05035: Path&Nav]
def heuristic(node1, node2):
    """Straight-line (Euclidean) distance between two nodes (used by A*)."""
    pos1 = MAP_NODES.get(node1, {}).get("pos", [0, 0])
    pos2 = MAP_NODES.get(node2, {}).get("pos", [0, 0])
    return math.sqrt((pos1[0] - pos2[0]) ** 2 + (pos1[1] - pos2[1]) ** 2)

# [WONG YEN MING 22ACB05035: Path&Nav]
def find_shortest_path(start, end):
    """
    A* pathfinding using node coordinates for both cost and heuristic.
    Returns a list of node IDs from start to end. Falls back to [start, end]
    when no path can be found or endpoints are invalid.
    """
    if start not in MAP_NODES or end not in MAP_NODES:
        return [start, end]
    if start == end:
        return [start]

    open_set = []
    heapq.heappush(open_set, (0, start))  # (f_score, node)

    came_from = {}                # backpointers: child -> parent
    g_score = {start: 0}          # actual cost from start
    f_score = {start: heuristic(start, end)}  # best known total cost (g + h)

    while open_set:
        _, current = heapq.heappop(open_set)

        if current == end:
            # Reconstruct path by walking parents back to start
            path = [current]
            while current in came_from:
                current = came_from[current]
                path.append(current)
            return path[::-1]

        for neighbor in MAP_NODES[current].get("connections", []):
            # Use straight-line distance between connected nodes as edge cost
            tentative_g = g_score[current] + heuristic(current, neighbor)
            if tentative_g < g_score.get(neighbor, float("inf")):
                came_from[neighbor] = current
                g_score[neighbor] = tentative_g
                f_score[neighbor] = tentative_g + heuristic(neighbor, end)
                # Push if not already in heap (cheap membership check)
                if neighbor not in [n for _, n in open_set]:
                    heapq.heappush(open_set, (f_score[neighbor], neighbor))

    # No path
    return [start, end]

# [WONG YEN MING 22ACB05035: Path&Nav]
def calculate_path_distance(path):
    """Sum Euclidean distances over consecutive nodes (for dashboard display)."""
    if len(path) < 2:
        return 0
    total_distance = 0
    for i in range(len(path) - 1):
        node1 = MAP_NODES.get(path[i], {})
        node2 = MAP_NODES.get(path[i + 1], {})
        if node1.get("pos") and node2.get("pos"):
            x1, y1 = node1["pos"]
            x2, y2 = node2["pos"]
            total_distance += math.sqrt((x1 - x2) ** 2 + (y1 - y2) ** 2)
    return round(total_distance, 1)

# [WONG YEN MING 22ACB05035: Path&Nav]
def get_turn_direction(current_node, next_node, previous_node=None):
    """
    Infer turn instruction ('Go straight', 'Turn left', 'Turn right', 'Turn backward')
    from the approach direction (prev -> current) and outbound direction (current -> next).
    """
    if not current_node or not next_node:
        return "Continue"
    if not previous_node:
        return "Scan next QR code to establish direction"

    # Safety: must be connected
    current_connections = MAP_NODES.get(current_node, {}).get('connections', [])
    if next_node not in current_connections:
        print(f"WARNING: {next_node} not directly connected to {current_node}!")
        return "Continue"

    # Special handle U-turn
    if next_node == previous_node:
        return "Turn backward"

    available_directions = {}
    current_pos = MAP_NODES.get(current_node, {}).get('pos', [0, 0])

    # Pre-compute angles to each neighbor
    for connected_node in current_connections:
        if connected_node in MAP_NODES:
            cx, cy = MAP_NODES[connected_node].get('pos', [0, 0])
            dx = cx - current_pos[0]
            dy = cy - current_pos[1]
            available_directions[connected_node] = math.degrees(math.atan2(dy, dx))

    # Approach (prev -> current)
    px, py = MAP_NODES.get(previous_node, {}).get('pos', [0, 0])
    approach_dx = current_pos[0] - px
    approach_dy = current_pos[1] - py
    approach_angle = math.degrees(math.atan2(approach_dy, approach_dx))

    # Outbound (current -> next)
    next_angle = available_directions.get(next_node, 0)

    # Normalize to [-180, 180] to get smallest turn
    turn_angle = (next_angle - approach_angle) % 360
    if turn_angle > 180:
        turn_angle -= 360

    # Bucket into instructions (tolerances tuned for indoor use)
    if abs(turn_angle) < 25:
        return "Go straight"
    elif abs(turn_angle) > 135:
        return "Turn backward"
    elif turn_angle > 45:
        return "Turn right"
    elif turn_angle < -45:
        return "Turn left"
    elif turn_angle > 25:
        return "Turn right"
    elif turn_angle < -25:
        return "Turn left"
    else:
        return "Go straight"

# [CHONG WIN NIE 22ACB05895: Compass & Off-Path]
def get_direction_from_device_heading(current_node, next_node, device_heading=0.0):
    """
    First-scan guidance: compare phone heading to the required direction
    (current -> next). Applies global north offset and device calibration.
    """
    if not current_node or not next_node or current_node == next_node:
        return "Continue"

    current_pos = MAP_NODES.get(current_node, {}).get('pos', [0, 0])
    next_pos = MAP_NODES.get(next_node, {}).get('pos', [0, 0])

    # Angle on the map to next node
    dx = next_pos[0] - current_pos[0]
    dy = next_pos[1] - current_pos[1]
    map_angle = math.degrees(math.atan2(dy, dx))

    # Align both map and device to the same north reference [CHONG WIN NIE]
    map_north_offset = MAP_COMPASS.get('north_direction', 0)
    adjusted_map_angle = (map_angle - map_north_offset) % 360

    # Apply device calibration (bias correction) [CHONG WIN NIE]
    compass_calibration_offset = MAP_COMPASS.get('compass_calibration', 0)
    calibrated_device_heading = (device_heading + compass_calibration_offset) % 360

    # Convert device heading to map frame and compare [CHONG WIN NIE]
    adjusted_device_heading = (calibrated_device_heading - map_north_offset) % 360
    relative_angle = (adjusted_map_angle - adjusted_device_heading) % 360
    if relative_angle > 180:
        relative_angle -= 360

    # Tolerance bands (phone compasses can be noisy) [CHONG WIN NIE]
    if abs(relative_angle) < 25:
        return "Go straight"
    elif abs(relative_angle) > 135:
        return "Turn backward"
    elif relative_angle > 45:
        return "Turn right"
    elif relative_angle < -45:
        return "Turn left"
    elif relative_angle > 25:
        return "Turn right"
    elif relative_angle < -25:
        return "Turn left"
    else:
        return "Go straight"

# =============================================================================
# INSTRUCTION BUILDER
# =============================================================================

# [ONG XIANG QI 22ACB06240: Feedback]
def get_navigation_instruction(current, destination, path, user_id,
                               is_first_scan=False, previous_node=None, device_heading=0.0):
    """
    Central place to phrase the guidance text + voice output:
      - Arrival / near-arrival
      - First-scan (uses device heading)  [uses CHONG WIN NIE’s compass math]
      - Subsequent scans (uses turn inference from movement history)
    """
    current_name = MAP_NODES.get(current, {}).get('name', current)
    destination_name = MAP_NODES.get(destination, {}).get('name', destination)

    # Arrival / near arrival
    if len(path) <= 1:
        if current == destination:
            return {'text': f'You have arrived at {destination_name}',
                    'voice': f'You have arrived at {destination_name}'}
        else:
            return {'text': f'You are near {destination_name}',
                    'voice': f'You are near {destination_name}'}

    next_node = path[1]
    next_name = MAP_NODES.get(next_node, {}).get('name', next_node)
    remaining = len(path) - 1

    # First scan: use device heading (CHONG WIN NIE) when prior movement is unknown
    if is_first_scan or not previous_node:
        direction = get_direction_from_device_heading(current, next_node, device_heading)
        return {
            'text': f'{direction} to {next_name}',
            'voice': f'You are now at {current_name}. {direction} to {next_name}.'
        }

    # Subsequent scans: infer turn based on prev->current->next geometry (YEN MING)
    direction = get_turn_direction(current, next_node, previous_node)
    action = direction.split(' to ')[0]

    if remaining == 1:
        return {
            'text': f'{direction} to {destination_name}',
            'voice': f'You are now at {current_name}, {action} to {destination_name}'
        }
    else:
        return {
            'text': f'{direction} ({remaining} steps remaining)',
            'voice': f'You are now at {current_name}, {action} to {next_name}'
        }

# =============================================================================
# DASHBOARD (HTML)
# =============================================================================
# [ONG XIANG QI 22ACB06240: Dashboard UI & overlay]
DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Indoor Navigation - Simple Dashboard</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; background: #f0f0f0; }
        .container { max-width: 800px; margin: 0 auto; }
        .card { background: white; padding: 20px; margin: 10px 0; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .header { text-align: center; color: #333; }
        .status { color: #28a745; font-weight: bold; }
        .user-list { max-height: 400px; overflow-y: auto; }
        .user-item { border: 1px solid #ddd; padding: 10px; margin: 5px 0; border-radius: 4px; }
    </style>
    <script>
        // mapNodes is injected by Flask; front-end uses it only for drawing overlays
        const mapNodes = {{ map_nodes | tojson }};

        function drawMap(users = []) {
            const canvas = document.getElementById('mapCanvas');
            if (!canvas) return;
            const ctx = canvas.getContext('2d');

            // Draw the raw map image at its natural resolution
            const mapImage = new Image();
            mapImage.onload = function() {
                canvas.width  = mapImage.naturalWidth;
                canvas.height = mapImage.naturalHeight;
                ctx.clearRect(0, 0, canvas.width, canvas.height);
                ctx.drawImage(mapImage, 0, 0);
                drawMapOverlay(ctx, users, canvas.width, canvas.height);
            };
            mapImage.src = '/static/map.jpg';
        }

        function drawMapOverlay(ctx, users, canvasWidth, canvasHeight) {
            // Edges
            ctx.strokeStyle = '#00FF00';
            ctx.lineWidth = 3;
            for (const [nodeId, node] of Object.entries(mapNodes)) {
                const [x1, y1] = node.pos;
                for (const connectedId of node.connections) {
                    const connectedNode = mapNodes[connectedId];
                    if (connectedNode) {
                        const [x2, y2] = connectedNode.pos;
                        ctx.beginPath();
                        ctx.moveTo(x1, y1);
                        ctx.lineTo(x2, y2);
                        ctx.stroke();
                    }
                }
            }

            // User paths
            users.forEach((user, index) => {
                if (user.path && user.path.length > 1) {
                    const colors = ['#FF0000', '#FF6600', '#FFCC00', '#00CC00', '#0066FF'];
                    const color = colors[index % colors.length];
                    ctx.strokeStyle = color;
                    ctx.lineWidth = 4;
                    ctx.beginPath();
                    for (let i = 0; i < user.path.length - 1; i++) {
                        const n1 = mapNodes[user.path[i]];
                        const n2 = mapNodes[user.path[i + 1]];
                        if (n1 && n2) {
                            const [x1, y1] = n1.pos;
                            const [x2, y2] = n2.pos;
                            if (i === 0) ctx.moveTo(x1, y1);
                            ctx.lineTo(x2, y2);
                        }
                    }
                    ctx.stroke();
                }
            });

            // Nodes
            for (const [nodeId, node] of Object.entries(mapNodes)) {
                const [x, y] = node.pos;
                const isRoom = nodeId.startsWith('R');

                ctx.strokeStyle = '#FFFFFF';
                ctx.lineWidth = 2;
                ctx.fillStyle = isRoom ? '#FF0000' : '#0066FF';
                ctx.beginPath();
                ctx.arc(x, y, isRoom ? 12 : 8, 0, 2 * Math.PI);
                ctx.fill();
                ctx.stroke();

                // Node ID label
                const nodeText = nodeId;
                ctx.font = 'bold 10px Arial';
                ctx.textAlign = 'center';
                const textWidth = ctx.measureText(nodeText).width;
                ctx.fillStyle = 'rgba(0,0,0,0.8)';
                ctx.fillRect(x - textWidth/2 - 4, y - 25, textWidth + 8, 14);
                ctx.fillStyle = '#FFFFFF';
                ctx.fillText(nodeText, x, y - 15);

                // Room name label
                if (isRoom) {
                    ctx.font = 'bold 9px Arial';
                    const nameText = node.name;
                    const nameWidth = ctx.measureText(nameText).width;
                    ctx.fillStyle = 'rgba(0,0,0,0.8)';
                    ctx.fillRect(x - nameWidth/2 - 4, y + 15, nameWidth + 8, 12);
                    ctx.fillStyle = '#FFFFFF';
                    ctx.fillText(nameText, x, y + 24);
                }
            }

            // User markers
            users.forEach((user, index) => {
                if (user.current_location && mapNodes[user.current_location]) {
                    const colors = ['#FF0000', '#FF6600', '#FFCC00', '#00CC00', '#0066FF'];
                    const color = colors[index % colors.length];
                    const [x, y] = mapNodes[user.current_location].pos;

                    // Dot + border
                    ctx.fillStyle = color;
                    ctx.strokeStyle = '#FFFFFF';
                    ctx.lineWidth = 2;
                    ctx.beginPath();
                    ctx.arc(x, y, 10, 0, 2 * Math.PI);
                    ctx.fill();
                    ctx.stroke();

                    // "U" label
                    ctx.fillStyle = '#FFFFFF';
                    ctx.font = 'bold 12px Arial';
                    ctx.textAlign = 'center';
                    ctx.fillText('U', x, y + 3);

                    // Username tag
                    const userName = user.user_name.split(' ')[0];
                    ctx.font = 'bold 10px Arial';
                    const nameWidth = ctx.measureText(userName).width;
                    ctx.fillStyle = 'rgba(0,0,0,0.8)';
                    ctx.fillRect(x - nameWidth/2 - 3, y - 28, nameWidth + 6, 12);
                    ctx.fillStyle = color;
                    ctx.fillText(userName, x, y - 20);
                }
            });
        }

        // Poll the backend for live sessions
        function refreshData() {
            fetch('/api/users')
                .then(response => response.json())
                .then(data => {
                    drawMap(data);  // redraw with latest user positions/paths
                    const userList = document.getElementById('users');
                    userList.innerHTML = '';
                    data.forEach(user => {
                        const pathInfo = user.path && user.path.length > 1
                            ? `<br><strong>Shortest Path:</strong> ${user.path.join(' → ')}<br><strong>Distance:</strong> ${user.distance || 'N/A'} units`
                            : '<br><em>No active path</em>';

                        const div = document.createElement('div');
                        div.className = 'user-item';
                        div.innerHTML = `
                            <strong>${user.user_name}</strong><br>
                            Location: ${user.current_location || 'Unknown'}<br>
                            Destination: ${user.destination || 'None'}<br>
                            Last seen: ${new Date(user.last_seen).toLocaleTimeString()}
                            ${pathInfo}
                        `;
                        userList.appendChild(div);
                    });
                    document.getElementById('userCount').textContent = data.length;
                })
                .catch(err => console.error('Error:', err));
        }

        setInterval(refreshData, 3000);  // refresh every 3 seconds
        window.onload = function() {
            refreshData();
            drawMap([]);
        };
    </script>
</head>
<body>
    <div class="container">
        <div class="card">
            <h1 class="header">Indoor Navigation Dashboard</h1>
            <p class="status">Server Running - Simplified Version</p>
        </div>

        <div class="card">
            <h3>Statistics</h3>
            <p>Active Users: <span id="userCount">0</span></p>
            <p>Available Destinations: {{ destinations|length }}</p>
        </div>

        <div class="card">
            <h3>Live Map View</h3>
            <div style="position: relative; width: 100%; height: auto; background: #f8f9fa; border: 2px solid #ddd; border-radius: 8px; overflow: auto;">
                <canvas id="mapCanvas" style="display: block; max-width: 100%; height: auto;"></canvas>
            </div>
        </div>

        <div class="card">
            <h3>Active Users & Shortest Paths</h3>
            <div id="users" class="user-list">
                <p>Loading users...</p>
            </div>
        </div>

        <div class="card">
            <h3>API Endpoints</h3>
            <ul>
                <li><strong>GET</strong> /api/destinations - Get available destinations</li>
                <li><strong>POST</strong> /api/session/create - Create user session</li>
                <li><strong>POST</strong> /api/destination/set - Set destination</li>
                <li><strong>POST</strong> /api/qr/scan - Process QR scan</li>
            </ul>
        </div>
    </div>
</body>
</html>
"""

# =============================================================================
# ROUTES: DASHBOARD + PUBLIC API
# =============================================================================

# [TEO QIYANG 22ACB06185: Integration]
@app.route('/')
def dashboard():
    """Renders the monitoring dashboard and injects MAP_NODES and destinations."""
    return render_template_string(DASHBOARD_HTML, destinations=destinations, map_nodes=MAP_NODES)

# [TEO QIYANG 22ACB06185: Integration]
@app.route('/api/session/create', methods=['POST'])
def create_session():
    """
    Create a new user session. Mobile app should call this once and
    keep the returned session_id for all subsequent requests.
    """
    data = request.get_json() or {}
    user_name = data.get('user_name', 'Anonymous')
    session_id = str(uuid.uuid4())

    users[session_id] = {
        'session_id': session_id,
        'user_name': user_name,
        'created_at': datetime.now().isoformat(),
        'last_seen': datetime.now().isoformat(),
        'current_location': None,
        'destination': None,
        'path': [],
        'is_active': True
    }

    print(f"Created session {session_id} for {user_name}")
    return jsonify({'session_id': session_id, 'user_name': user_name})

# [TEO QIYANG 22ACB06185: Integration]
@app.route('/api/destinations', methods=['GET'])
def get_destinations():
    """Return list of valid room destinations for client pickers."""
    return jsonify(destinations)

# [ONG XIANG QI 22ACB06240: Feedback] [CHONG WIN NIE 22ACB05895: Off-Path]
@app.route('/api/expected-direction', methods=['POST'])
def get_expected_direction():
    """
    Given current_location, destination, and device_heading,
    compute the next-leg expected direction and how far the user deviates.
    Used for live orientation feedback between QR scans.

    CHONG WIN NIE:
      • Applies MAP_COMPASS north + calibration to device heading
      • Computes deviation and on/off-path using a 30° tolerance
      • Generates left/right/straight hints from angle difference
    """
    try:
        data = request.json
        current_location = data.get('current_location')
        destination = data.get('destination')
        device_heading = float(data.get('device_heading', 0))

        print(f"Expected Direction Request - Current: '{current_location}', Destination: '{destination}', Heading: {device_heading}")

        if not current_location or not destination:
            print(f"ERROR: Missing data - Current: '{current_location}', Destination: '{destination}'")
            return jsonify({'error': 'Missing current_location or destination'}), 400

        # A* path to know the next waypoint (YEN MING)
        try:
            path = find_shortest_path(current_location, destination)
            print(f"  Pathfinding successful: {path}")
        except Exception as e:
            print(f"  Pathfinding FAILED: {str(e)}")
            return jsonify({'error': f'Pathfinding failed: {str(e)}'}), 400

        # Arrival / near-arrival branch
        if not path or len(path) < 2:
            dest_name = MAP_NODES.get(destination, {}).get('name', destination)
            instruction = f'You have arrived at {dest_name}' if current_location == destination else f'You are near {dest_name}'
            return jsonify({
                'expected_direction': 0,
                'expected_instruction': instruction,
                'deviation': 0,
                'on_path': True
            })

        # Locate current index within the path to identify next waypoint
        current_index = None
        for i, node in enumerate(path):
            if node == current_location:
                current_index = i
                break

        print(f"  Current index in path: {current_index}")

        if current_index is None or current_index >= len(path) - 1:
            # Not found or already at the end
            dest_name = MAP_NODES.get(destination, {}).get('name', destination)
            instruction = f'You have arrived at {dest_name}' if current_location == destination else f'You are near {dest_name}'
            return jsonify({
                'expected_direction': 0,
                'expected_instruction': instruction,
                'deviation': 0,
                'on_path': True
            })

        # Compute expected heading to next waypoint
        next_node = path[current_index + 1]
        current_pos = MAP_NODES.get(current_location, {}).get('pos', [0, 0])
        next_pos = MAP_NODES.get(next_node, {}).get('pos', [0, 0])

        dx = next_pos[0] - current_pos[0]
        dy = next_pos[1] - current_pos[1]
        map_angle = math.degrees(math.atan2(dy, dx))

        # CHONG WIN NIE: bring map and device into same frame and calibrate
        map_north_offset = MAP_COMPASS.get('north_direction', 0)
        expected_direction = (map_angle - map_north_offset) % 360

        compass_calibration_offset = MAP_COMPASS.get('compass_calibration', 0)
        calibrated_device_heading = (device_heading + compass_calibration_offset) % 360

        # Absolute angular deviation (<= 180) [CHONG WIN NIE]
        deviation = abs(expected_direction - calibrated_device_heading)
        if deviation > 180:
            deviation = 360 - deviation

        # Tolerance: within 30° is considered facing the correct way [CHONG WIN NIE]
        on_path = deviation < 30

        # Phrase a short instruction for the UI/speaker [CHONG WIN NIE]
        if on_path:
            expected_instruction = f"Continue toward {MAP_NODES.get(next_node, {}).get('name', next_node)}"
        else:
            angle_diff = (expected_direction - calibrated_device_heading) % 360
            if angle_diff > 180:
                angle_diff -= 360
            if angle_diff > 15:
                expected_instruction = f"Turn right toward {MAP_NODES.get(next_node, {}).get('name', next_node)}"
            elif angle_diff < -15:
                expected_instruction = f"Turn left toward {MAP_NODES.get(next_node, {}).get('name', next_node)}"
            else:
                expected_instruction = f"Continue straight toward {MAP_NODES.get(next_node, {}).get('name', next_node)}"

        print(f"Expected Direction Check:")
        print(f"  Current: {current_location} → Next: {next_node}")
        print(f"  Expected direction: {expected_direction:.1f}°")
        print(f"  Device heading: {calibrated_device_heading:.1f}°")
        print(f"  Deviation: {deviation:.1f}°")
        print(f"  On path: {on_path}")

        return jsonify({
            'expected_direction': expected_direction,
            'expected_instruction': expected_instruction,
            'deviation': deviation,
            'on_path': on_path,
            'next_waypoint': next_node,
            'next_waypoint_name': MAP_NODES.get(next_node, {}).get('name', next_node)
        })

    except Exception as e:
        print(f"Expected direction error: {e}")
        return jsonify({'error': str(e)}), 500

# [TEO QIYANG 22ACB06185: Integration]
@app.route('/api/destination/set', methods=['POST'])
def set_destination():
    """
    Attach a destination to a session. After this, every QR scan will compute
    and return an updated path + step instruction.
    """
    data = request.get_json()
    session_id = data.get('session_id')
    destination_id = data.get('destination_id')

    if not session_id or not destination_id:
        return jsonify({'error': 'Missing session_id or destination_id'}), 400
    if session_id not in users:
        return jsonify({'error': 'Invalid session'}), 404

    dest_name = next((d['name'] for d in destinations if d['id'] == destination_id), destination_id)
    users[session_id]['destination'] = destination_id
    users[session_id]['last_seen'] = datetime.now().isoformat()

    print(f"Set destination {destination_id} ({dest_name}) for session {session_id}")
    return jsonify({
        'success': True,
        'destination': destination_id,
        'destination_name': dest_name,
        'message': f'Destination set to {dest_name}'
    })

# [TEO QIYANG 22ACB06185: Integration] (+ uses Path&Nav + Feedback internally)
@app.route('/api/qr/scan', methods=['POST'])
def scan_qr():
    """
    Main navigation step:
      1) Client scans a QR (node id) and sends device_heading.
      2) Server sets current location.
      3) If destination is set → compute A* path.
      4) Build instruction via get_navigation_instruction()
      5) Return guidance + path for rendering.
    """
    data = request.get_json()
    session_id = data.get('session_id')
    qr_value = data.get('qr_value')
    device_heading = data.get('device_heading', 0.0)

    if not session_id or not qr_value:
        return jsonify({'error': 'Missing session_id or qr_value'}), 400
    if session_id not in users:
        return jsonify({'error': 'Invalid session'}), 404

    user = users[session_id]
    node_id = qr_value.upper()
    user['current_location'] = node_id
    user['last_seen'] = datetime.now().isoformat()

    # If no destination yet, tell the client to choose one
    if not user['destination']:
        return jsonify({
            'success': True,
            'current_location': node_id,
            'instruction': f'You are at {node_id}. Please set a destination.',
            'voice_text': f'You are at {node_id}. Please select a destination to start navigation.'
        })

    # Compute A* shortest path and distance for the dashboard (YEN MING)
    path = find_shortest_path(node_id, user['destination'])
    user['path'] = path
    user['distance'] = calculate_path_distance(path)

    # Movement history (for turn inference on subsequent scans)
    if session_id not in user_movement_history:
        user_movement_history[session_id] = []
    is_first_scan = len(user_movement_history[session_id]) == 0
    previous_node = user_movement_history[session_id][-1] if user_movement_history[session_id] else None

    print(f"Scan History: {user_movement_history[session_id]} + [{node_id}]")
    print(f"Previous: {previous_node}, Current: {node_id}, First: {is_first_scan}")

    # Record the current scan
    user_movement_history[session_id].append(node_id)
    if len(user_movement_history[session_id]) > 3:
        user_movement_history[session_id] = user_movement_history[session_id][-3:]

    # Build phrased navigation instruction (Feedback + Compass for first scan)
    instruction = get_navigation_instruction(
        node_id, user['destination'], path, session_id,
        is_first_scan, previous_node, device_heading
    )

    # Persist current location
    user['current_location'] = node_id

    print(f"QR scan: {qr_value} -> {node_id}, destination: {user['destination']}, heading: {float(device_heading):.1f}°")

    return jsonify({
        'success': True,
        'current_location': node_id,
        'destination': user['destination'],
        'path': path,
        'instruction': instruction['text'],
        'voice_text': instruction['voice'],
        'distance_remaining': len(path) - 1,
        'total_distance': user.get('distance', 0),
        'next_node': path[1] if len(path) > 1 else None
    })

# [TEO QIYANG 22ACB06185: Integration]
@app.route('/api/users', methods=['GET'])
def get_users():
    """Dashboard consumption: list active sessions and their latest path/state."""
    active_users = [user for user in users.values() if user['is_active']]
    return jsonify(active_users)

# [TEO QIYANG 22ACB06185: Integration]
@app.route('/api/session/<session_id>', methods=['GET'])
def get_session(session_id):
    """Retrieve a single session object (useful for debugging)."""
    if session_id not in users:
        return jsonify({'error': 'Session not found'}), 404
    return jsonify(users[session_id])

# [TEO QIYANG 22ACB06185: Integration]
if __name__ == '__main__':
    print("Starting Simplified Indoor Navigation Server...")
    print("Mobile API: http://localhost:5000/api/")
    print("Web Dashboard: http://localhost:5000/")
    print("No complex dependencies required!")
    print("=" * 50)
    try:
        app.run(host='0.0.0.0', port=5000, debug=True)
    except Exception as e:
        print(f"Server error: {e}")
        print("Make sure port 5000 is available")
