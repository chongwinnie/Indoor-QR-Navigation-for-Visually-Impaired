/**
 *
 * Team Contribution:
 * ----------------------------------
 * TEO QIYANG 22ACB06185 — Map Editing (Graph/UI):
 *   constructor/setup, canvas rendering, nodes & connections modeling,
 *   drag/select tools, grid snap, labels, compass, validation+export.
 *
 * CHONG WIN NIE 22ACB05895 — QR & Integration (Backend):
 *   startBackend() helper, generateQRCodes() flow,
 *   conversions to backend payload, QR dialog + ZIP download.
 *   
 *  ONG XIANG QI 22ACB06240 — UI (index.html)
 *   Page layout, header/toolbar/status bar, buttons, selects, canvas container
 *   Wires UI controls to editor.* methods; styling and accessibility of controls
 */

class SimpleGraphEditor {
    constructor() {
        // [TEO QIYANG 22ACB06185] Canvas & DOM references
        this.canvas = document.getElementById('mapCanvas');
        this.ctx = this.canvas.getContext('2d');
        this.canvasWrapper = document.getElementById('canvasWrapper');
        this.canvasContent = document.getElementById('canvasContent');

        // [TEO QIYANG 22ACB06185] In-memory graph model (same structure used by export)
        // nodes: { id: { position:[x,y], name, floor } }
        // connections: [[nodeIdA, nodeIdB], ...]
        this.nodes = {};
        this.connections = [];
        this.connection_mode = false;
        this.deletion_mode = false;
        this.corner_mode = true;     // auto L-corner on connect
        this.add_corner_mode = false;

        // [TEO QIYANG 22ACB06185] Display options/state
        this.label_mode = 'Hover';   // None / Name / ID / ID+Name / Hover
        this.font_px = 16;
        this.hover_node_id = null;

        // [TEO QIYANG 22ACB06185] Drag/selection state
        this.dragging_node_id = null;
        this.first_node_id = null;   // first endpoint in connection mode

        // [TEO QIYANG 22ACB06185] Grid snap
        this.grid_size = 20;
        this.snap_enabled = true;

        // [TEO QIYANG 22ACB06185] (reserved) zoom/pan
        this.zoomLevel = 1.0;
        this.panX = 0;
        this.panY = 0;

        // [TEO QIYANG 22ACB06185] Map metadata
        this.backgroundImage = null;
        this.buildingId = 'HOSPITAL_A';
        this.version = '2025.01.15-01';
        this.scale = 42.7; // pixels/meter (used only for exports/integration)

        // [TEO QIYANG 22ACB06185] Compass UI (for north reference overlay only)
        this.compass_mode = false;
        this.north_direction = 0;    // degrees; 0 = up
        this.compass_center = null;  // where to draw the compass

        // [TEO QIYANG 22ACB06185] Boot sequence
        this.setupEventListeners();
        this.loadMapImage();
        this.loadData();
        this.updateDisplay();
    }

    // [TEO QIYANG 22ACB06185] Register mouse + keyboard handlers
    setupEventListeners() {
        // Canvas events
        this.canvas.addEventListener('mousedown', (e) => this.onMouseDown(e));
        this.canvas.addEventListener('mousemove', (e) => this.onMouseMove(e));
        this.canvas.addEventListener('mouseup', (e) => this.onMouseUp(e));

        // Keyboard shortcuts (mirrors editor.py behavior)
        document.addEventListener('keydown', (e) => {
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

            switch(e.key.toLowerCase()) {
                case 'c': this.toggleConnectionMode(); break;  // connect nodes
                case 'd': this.toggleDeletionMode(); break;    // delete node
                case 's': this.toggleSnap(); break;            // grid snap
                case 'm': this.toggleCornerMode(); break;      // auto L corner on connect
                case 'k': this.toggleAddCornerMode(); break;   // place corner manually
                case 'n': this.toggleCompassMode(); break;     // set compass center
                case 'v': this.validateAndExport(); break;     // export JSON
                case 'g': this.generateQRCodes(); break;       // [CHONG WIN NIE 22ACB05895] backend QR
            }
        });
    }

    // [TEO QIYANG 22ACB06185] Load map background image (no logic change)
    loadMapImage() {
        const img = new Image();
        img.onload = () => {
            this.backgroundImage = img;
            this.canvas.width = img.width;
            this.canvas.height = img.height;
            this.updateDisplay();
        };
        img.src = '../backend/static/map.jpg'; // Updated path to backend/static/map.jpg
    }

    // ===== Data I/O (localStorage) — TEO QIYANG 22ACB06185 =====
    loadData() {
        try {
            const saved = localStorage.getItem('graph_map_data');
            if (saved) {
                const data = JSON.parse(saved);
                this.nodes = data.nodes || {};
                this.connections = data.connections || [];
            }
        } catch (e) {
            console.warn('Could not load saved data:', e);
        }
    }

    saveData() {
        try {
            const data = {
                nodes: this.nodes,
                connections: this.connections
            };
            localStorage.setItem('graph_map_data', JSON.stringify(data, null, 2));
        } catch (e) {
            console.warn('Could not save data:', e);
        }
    }

    // ===== Coordinates & snapping — TEO QIYANG 22ACB06185 =====
    getCanvasCoords(event) {
        const rect = this.canvas.getBoundingClientRect();
        const x = (event.clientX - rect.left) * (this.canvas.width / rect.width);
        const y = (event.clientY - rect.top) * (this.canvas.height / rect.height);
        return this.snap_enabled ? this.snapToGrid(x, y) : [x, y];
    }

    snapToGrid(x, y) {
        const gs = this.grid_size;
        return [Math.round(x / gs) * gs, Math.round(y / gs) * gs];
    }

    // ===== Node/edge helpers — TEO QIYANG 22ACB06185 =====
    getNextRoomId() {
        let i = 1;
        while (true) {
            const id = `R${String(i).padStart(3, '0')}`;
            if (!this.nodes[id]) return id;
            i++;
        }
    }

    getNextCornerId() {
        let i = 1;
        while (true) {
            const id = `C${String(i).padStart(3, '0')}`;
            if (!this.nodes[id]) return id;
            i++;
        }
    }

    getNodeAt(x, y, threshold = 10) {
        for (const [nodeId, node] of Object.entries(this.nodes)) {
            const [nx, ny] = node.position;
            if (Math.hypot(x - nx, y - ny) < threshold) {
                return nodeId;
            }
        }
        return null;
    }

    createCornerNode(x, y) {
        const nodeId = this.getNextCornerId();
        const i = parseInt(nodeId.substring(1));
        this.nodes[nodeId] = {
            position: [x, y],
            name: `Corner ${i}`,
            floor: this.inferFloor()
        };
        this.saveData();
        return nodeId;
    }

    inferFloor() {
        // If any node already has a floor, reuse that; else default to "Ground"
        for (const node of Object.values(this.nodes)) {
            if (node.floor) return node.floor;
        }
        return 'Ground';
    }

    addConnection(a, b) {
        if (a === b) return; // ignore self loops
        // Prevent duplicate undirected edges
        const exists = this.connections.some(conn =>
            (conn[0] === a && conn[1] === b) || (conn[0] === b && conn[1] === a)
        );
        if (!exists) {
            this.connections.push([a, b]);
            this.saveData();
        }
    }

    // ===== Mouse handlers — TEO QIYANG 22ACB06185 =====
    onMouseDown(event) {
        const [x, y] = this.getCanvasCoords(event);

        // Set compass center when compass mode is on
        if (this.compass_mode) {
            this.compass_center = [x, y];
            this.compass_mode = false;
            this.updateStatus('Compass position set successfully');
            this.updateDisplay();
            return;
        }

        if (this.deletion_mode) {
            this.handleDeletion(x, y);
            return;
        }

        if (this.connection_mode) {
            this.handleConnection(x, y);
            return;
        }

        if (this.add_corner_mode) {
            this.createCornerNode(x, y);
            this.updateStatus(`Corner added. Mode: Add Corner`);
            this.updateDisplay();
            return;
        }

        // Drag existing node or create a room node
        const nodeId = this.getNodeAt(x, y);
        if (nodeId) {
            this.dragging_node_id = nodeId;
        } else {
            this.openAddRoomDialog(x, y);
        }
    }

    onMouseMove(event) {
        const [x, y] = this.getCanvasCoords(event);

        // Hover label (ID+Name) in Hover mode
        this.hover_node_id = this.getNodeAt(x, y, 12);

        // Dragging node live update
        if (this.dragging_node_id) {
            this.nodes[this.dragging_node_id].position = [x, y];
            this.updateDisplay();
        } else if (this.label_mode === 'Hover') {
            this.updateDisplay();
        }
    }

    onMouseUp(event) {
        if (this.dragging_node_id) {
            this.saveData();
            this.dragging_node_id = null;
        }
    }

    // ===== Connect / Delete flows — TEO QIYANG 22ACB06185 =====
    handleConnection(x, y) {
        const nodeId = this.getNodeAt(x, y);
        if (!nodeId) return;

        if (!this.first_node_id) {
            this.first_node_id = nodeId;
            this.updateStatus(`Selected ${nodeId}. Click another node to connect.`);
        } else {
            const a = this.first_node_id;
            const b = nodeId;
            this.first_node_id = null;
            this.connection_mode = false;

            if (!this.corner_mode) {
                this.addConnection(a, b);
            } else {
                // Auto “L” corner if not horizontally/vertically aligned
                const [ax, ay] = this.nodes[a].position;
                const [bx, by] = this.nodes[b].position;

                if (ax === bx || ay === by) {
                    // Straight edge
                    this.addConnection(a, b);
                } else {
                    // Create or reuse an L-corner at (ax,by) or (bx,ay)
                    const cornerOptions = [[ax, by], [bx, ay]];
                    for (const [cx, cy] of cornerOptions) {
                        const existing = this.getNodeAt(cx, cy, 8);
                        const cornerId = existing || this.createCornerNode(cx, cy);
                        this.addConnection(a, cornerId);
                        this.addConnection(cornerId, b);
                        break;
                    }
                }
            }

            this.updateStatus('Connection added. Mode: Normal');
            this.updateDisplay();
        }
    }

    handleDeletion(x, y) {
        const nodeId = this.getNodeAt(x, y);
        if (!nodeId) return;

        if (confirm(`Delete node '${nodeId}' and its connections?`)) {
            delete this.nodes[nodeId];
            this.connections = this.connections.filter(([a, b]) => a !== nodeId && b !== nodeId);
            this.saveData();
            this.deletion_mode = false;
            this.updateStatus('Node deleted. Mode: Normal');
            this.updateDisplay();
        }
    }

    openAddRoomDialog(x, y) {
        const name = prompt('Room name/number:');
        if (!name) return;

        const floor = prompt('Floor:', 'Ground') || 'Ground';

        const nodeId = this.getNextRoomId();
        this.nodes[nodeId] = {
            position: [x, y],
            name: name.trim(),
            floor: floor.trim()
        };

        this.saveData();
        this.updateStatus(`Added ${nodeId} (${name}, ${floor}). Mode: Normal`);
        this.updateDisplay();
    }

    // ===== Mode toggles — TEO QIYANG 22ACB06185 =====
    toggleConnectionMode() {
        this.connection_mode = !this.connection_mode;
        this.deletion_mode = false;
        this.add_corner_mode = false;
        this.first_node_id = null;
        this.updateStatus(`Mode: ${this.connection_mode ? 'Connection' : 'Normal'}`);
        this.updateDisplay();
    }

    toggleDeletionMode() {
        this.deletion_mode = !this.deletion_mode;
        this.connection_mode = false;
        this.add_corner_mode = false;
        this.updateStatus(`Mode: ${this.deletion_mode ? 'Delete' : 'Normal'}`);
        this.updateDisplay();
    }

    toggleCornerMode() {
        this.corner_mode = !this.corner_mode;
        this.updateStatus(`Corner Mode: ${this.corner_mode ? 'ON' : 'OFF'}. Mode: Normal`);
    }

    toggleAddCornerMode() {
        this.add_corner_mode = !this.add_corner_mode;
        this.connection_mode = false;
        this.deletion_mode = false;
        this.updateStatus(`Add Corner Mode: ${this.add_corner_mode ? 'ON' : 'OFF'}. Click to place corner.`);
    }

    toggleSnap() {
        this.snap_enabled = !this.snap_enabled;
        this.updateStatus(`Grid Snap: ${this.snap_enabled ? 'ON' : 'OFF'}. Mode: Normal`);
        this.updateDisplay();
    }

    // ===== Rendering — TEO QIYANG 22ACB06185 =====
    updateDisplay() {
        const ctx = this.ctx;
        ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);

        // Background
        if (this.backgroundImage) {
            ctx.drawImage(this.backgroundImage, 0, 0);
        }

        // Grid overlay (visible when snap is on)
        if (this.snap_enabled && this.grid_size > 4) {
            ctx.strokeStyle = '#e0e0e0';
            ctx.lineWidth = 1;
            for (let x = 0; x < this.canvas.width; x += this.grid_size) {
                ctx.beginPath();
                ctx.moveTo(x, 0);
                ctx.lineTo(x, this.canvas.height);
                ctx.stroke();
            }
            for (let y = 0; y < this.canvas.height; y += this.grid_size) {
                ctx.beginPath();
                ctx.moveTo(0, y);
                ctx.lineTo(this.canvas.width, y);
                ctx.stroke();
            }
        }

        // Edges
        ctx.strokeStyle = '#00c800';
        ctx.lineWidth = 2;
        for (const [a, b] of this.connections) {
            if (this.nodes[a] && this.nodes[b]) {
                const [ax, ay] = this.nodes[a].position;
                const [bx, by] = this.nodes[b].position;
                ctx.beginPath();
                ctx.moveTo(ax, ay);
                ctx.lineTo(bx, by);
                ctx.stroke();
            }
        }

        // Nodes + labels
        for (const [nodeId, node] of Object.entries(this.nodes)) {
            const [x, y] = node.position;

            // Mark first chosen node during connection mode
            if (this.connection_mode && nodeId === this.first_node_id) {
                ctx.fillStyle = '#00ffff';
                ctx.beginPath();
                ctx.arc(x, y, 7, 0, 2 * Math.PI);
                ctx.fill();
            }

            // Node marker
            ctx.fillStyle = '#0000ff';
            ctx.beginPath();
            ctx.arc(x, y, 5, 0, 2 * Math.PI);
            ctx.fill();

            // Label depending on label_mode
            if (this.shouldShowLabel(nodeId)) {
                const text = this.getLabelText(nodeId, node);
                this.drawLabel(ctx, x, y, text);
            }
        }

        // Compass overlay (optional)
        this.drawCompass(ctx);
    }

    shouldShowLabel(nodeId) {
        switch (this.label_mode) {
            case 'None': return false;
            case 'Hover': return nodeId === this.hover_node_id;
            default: return true;
        }
    }

    getLabelText(nodeId, node) {
        switch (this.label_mode) {
            case 'Name': return node.name;
            case 'ID': return nodeId;
            case 'ID+Name': return `${nodeId}: ${node.name}`;
            case 'Hover': return `${nodeId}: ${node.name}`;
            default: return nodeId;
        }
    }

    drawLabel(ctx, x, y, text) {
        ctx.font = `${this.font_px}px Arial`;
        ctx.fillStyle = 'rgba(255, 255, 255, 0.8)';
        const metrics = ctx.measureText(text);
        const width = metrics.width + 8;
        const height = this.font_px + 4;

        ctx.fillRect(x + 10, y - height, width, height);
        ctx.fillStyle = '#000';
        ctx.fillText(text, x + 14, y - 4);
    }

    // [TEO QIYANG 22ACB06185] Status text helper (UI only)
    updateStatus(message) {
        const statusEl = document.getElementById('statusMessage');
        if (statusEl) {
            statusEl.textContent = message;
        }
        console.log(message);
    }

    // ===== Backend helper (instructions only) — CHONG WIN NIE 22ACB05895 =====
    startBackend() {
        const instructions = `
To generate QR codes, you need to start the backend server:

1. Open terminal/command prompt
2. Navigate to: indoor-navigation-system/map-editor/
3. Run: python enhanced_backend.py
4. Wait for "Starting server on http://127.0.0.1:5501"
5. Then click "Generate QR" button

The backend generates 4-up QR codes:
• Corner nodes: C001, C002, C003...
• Room nodes: R001, R002, R003...
• Each QR image contains 4 identical codes in 2x2 grid
        `;
        alert(instructions);
    }

    // ===== Validate & Export JSON (map_compiled.json shape) — TEO QIYANG 22ACB06185 =====
    validateAndExport() {
        const errors = [];
        const cleaned = [];
        const seen = new Set();

        // Normalize edges: drop self-loops/dupes/missing refs
        for (const [s, e] of this.connections) {
            if (s === e) {
                errors.push(`Self-loop at ${s}`);
                continue;
            }
            if (!this.nodes[s] || !this.nodes[e]) {
                errors.push(`Edge references missing node: ${s}-${e}`);
                continue;
            }
            const key = [s, e].sort().join('-');
            if (seen.has(key)) continue;
            seen.add(key);
            cleaned.push([s, e]);
        }

        // Degree check: flag nodes with no edges
        const degrees = {};
        for (const nodeId of Object.keys(this.nodes)) {
            degrees[nodeId] = 0;
        }
        for (const [s, e] of cleaned) {
            degrees[s]++;
            degrees[e]++;
        }
        const dangling = Object.entries(degrees).filter(([id, deg]) => deg === 0).map(([id]) => id);
        if (dangling.length > 0) {
            errors.push(`Dangling nodes: ${dangling.join(', ')}`);
        }

        // Export payload used by server/editor stack
        const exportData = {
            buildingId: this.buildingId,
            version: this.version,
            scale: this.scale,
            nodes: this.nodes,
            connections: cleaned,
            compass: {
                north_direction: this.north_direction,
                compass_center: this.compass_center
            }
        };

        // Show the JSON + warnings (no state change)
        this.showExportDialog(exportData, errors);
        return exportData;
    }

    // [TEO QIYANG 22ACB06185] Export dialog UI only
    showExportDialog(data, errors) {
        const json = JSON.stringify(data, null, 2);

        // Create or update export dialog
        let dialog = document.getElementById('exportDialog');
        if (!dialog) {
            dialog = document.createElement('div');
            dialog.id = 'exportDialog';
            dialog.style.cssText = `
                position: fixed; top: 0; left: 0; width: 100%; height: 100%;
                background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center;
                z-index: 1000;
            `;

            const content = document.createElement('div');
            content.style.cssText = `
                background: white; padding: 20px; border-radius: 8px; max-width: 80%; max-height: 80%;
                overflow: hidden; display: flex; flex-direction: column;
            `;

            content.innerHTML = `
                <h3>Export Map Data</h3>
                <div id="exportErrors" style="color: red; margin-bottom: 10px;"></div>
                <textarea id="exportJson" style="flex: 1; min-height: 400px; font-family: monospace; font-size: 12px;"></textarea>
                <div style="margin-top: 10px; text-align: right;">
                    <button id="copyExport">Copy to Clipboard</button>
                    <button id="downloadExport">Download JSON</button>
                    <button id="closeExport">Close</button>
                </div>
            `;

            dialog.appendChild(content);
            document.body.appendChild(dialog);

            // Buttons
            document.getElementById('copyExport').onclick = () => {
                document.getElementById('exportJson').select();
                document.execCommand('copy');
                alert('Copied to clipboard!');
            };

            document.getElementById('downloadExport').onclick = () => {
                const blob = new Blob([json], { type: 'application/json' });
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = 'map_compiled.json';
                a.click();
                URL.revokeObjectURL(url);
            };

            document.getElementById('closeExport').onclick = () => {
                dialog.style.display = 'none';
            };
        }

        // Fill UI
        document.getElementById('exportJson').value = json;
        document.getElementById('exportErrors').innerHTML = errors.length > 0
            ? `<strong>Warnings:</strong><br>${errors.join('<br>')}<br><br>`
            : '<strong>✅ Validation OK</strong><br><br>';

        dialog.style.display = 'flex';
    }

    // ===== Backend integration — CHONG WIN NIE 22ACB05895 =====
    async generateQRCodes() {
        if (Object.keys(this.nodes).length === 0) {
            alert('Please add some nodes first');
            return;
        }

        try {
            this.updateStatus('Generating QR codes...');

            // Prepare data for backend (keeps original shape)
            const exportData = this.validateAndExport();
            const backendData = {
                buildingId: this.buildingId,
                version: this.version,
                scale: this.scale,
                nodes: exportData.nodes,
                connections: exportData.connections,

                // Convert to format expected by map-backend.py (no logic change)
                corridorNodes: this.convertNodesToCorridorNodes(),
                corridorSegments: this.convertConnectionsToSegments(),
                destinations: this.convertDestinationNodes()
            };

            console.log('Calling backend for QR generation:', backendData);

            const response = await fetch('http://127.0.0.1:5501/api/generate-qr', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(backendData)
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const result = await response.json();
            console.log('QR Generation Result:', result);

            if (result.success) {
                this.showQRCodesDialog(result.qr_codes);
                this.updateStatus(`Generated ${result.count} QR codes with 4-up format`);
            } else {
                throw new Error(result.error || 'QR generation failed');
            }

        } catch (error) {
            console.error('QR generation error:', error);
            this.updateStatus('QR generation failed');

            if (error.message.includes('Failed to fetch')) {
                alert('Cannot connect to backend server.\nPlease run: python map-backend.py');
            } else {
                alert(`QR generation failed: ${error.message}`);
            }
        }
    }

    // [CHONG WIN NIE 22ACB05895] Editor → backend adapters (names/shape unchanged)
    convertNodesToCorridorNodes() {
        const corridorNodes = [];
        let nodeId = 1;

        for (const [id, node] of Object.entries(this.nodes)) {
            // include corners (C###) and rooms (R###)
            if (id.startsWith('C') || id.startsWith('R')) {
                corridorNodes.push({
                    id: id,
                    x: node.position[0],
                    y: node.position[1],
                    type: id.startsWith('C') ? 'corner' : 'room'
                });
            }
        }

        return corridorNodes;
    }

    // [CHONG WIN NIE 22ACB05895] connections → segments (pixel length)
    convertConnectionsToSegments() {
        const segments = [];
        let segmentId = 1;

        for (const [nodeA, nodeB] of this.connections) {
            const posA = this.nodes[nodeA]?.position;
            const posB = this.nodes[nodeB]?.position;

            if (posA && posB) {
                const length = Math.sqrt(
                    Math.pow(posB[0] - posA[0], 2) + Math.pow(posB[1] - posA[1], 2)
                );

                segments.push({
                    id: `seg_${segmentId++}`,
                    startNodeId: nodeA,
                    endNodeId: nodeB,
                    length: length
                });
            }
        }

        return segments;
    }

    // [CHONG WIN NIE 22ACB05895] room nodes → destinations list
    convertDestinationNodes() {
        const destinations = [];
        let destId = 1;

        for (const [id, node] of Object.entries(this.nodes)) {
            if (id.startsWith('R')) {
                destinations.push({
                    id: id, // keep R001, R002...
                    name: node.name,
                    x: node.position[0],
                    y: node.position[1]
                });
            }
        }

        return destinations;
    }

    // ===== QR dialog + ZIP download — CHONG WIN NIE 22ACB05895 =====
    showQRCodesDialog(qrCodes) {
        // Create or update QR dialog
        let dialog = document.getElementById('qrDialog');
        if (!dialog) {
            dialog = document.createElement('div');
            dialog.id = 'qrDialog';
            dialog.style.cssText = `
                position: fixed; top: 0; left: 0; width: 100%; height: 100%;
                background: rgba(0,0,0,0.8); display: flex; align-items: center; justify-content: center;
                z-index: 1000; overflow: auto;
            `;

            const content = document.createElement('div');
            content.style.cssText = `
                background: white; padding: 20px; border-radius: 8px; max-width: 90%; max-height: 90%;
                overflow: auto; display: flex; flex-direction: column;
            `;

            content.innerHTML = `
                <h3>Generated QR Codes (4-up format)</h3>
                <div id="qrGrid" style="display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; margin: 20px 0;"></div>
                <div style="margin-top: 10px; text-align: right;">
                    <button id="downloadQRZip">📦 Download ZIP</button>
                    <button id="closeQRDialog">Close</button>
                </div>
            `;

            dialog.appendChild(content);
            document.body.appendChild(dialog);

            // Events
            document.getElementById('downloadQRZip').onclick = () => {
                this.downloadQRZip(qrCodes);
            };

            document.getElementById('closeQRDialog').onclick = () => {
                dialog.style.display = 'none';
            };
        }

        // Populate grid
        const qrGrid = document.getElementById('qrGrid');
        qrGrid.innerHTML = '';

        for (const qr of qrCodes) {
            const qrItem = document.createElement('div');
            qrItem.style.cssText = `
                border: 1px solid #ccc; padding: 10px; border-radius: 4px; text-align: center;
            `;

            qrItem.innerHTML = `
                <h4>${qr.id} - ${qr.type}</h4>
                <img src="data:image/png;base64,${qr.image}" style="max-width: 100%; height: auto;" />
                <p><strong>Payload:</strong> ${qr.payload}</p>
                ${qr.name ? `<p><strong>Name:</strong> ${qr.name}</p>` : ''}
                ${qr.chainage !== undefined ? `<p><strong>Chainage:</strong> ${qr.chainage}m</p>` : ''}
            `;

            qrGrid.appendChild(qrItem);
        }

        dialog.style.display = 'flex';
        this.updateStatus(`Showing ${qrCodes.length} QR codes (4-up format)`);
    }

    async downloadQRZip(qrCodes) {
        try {
            const response = await fetch('http://127.0.0.1:5501/api/download-qr-zip', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ qr_codes: qrCodes })
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const blob = await response.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'qr_codes_4up.zip';
            a.click();
            URL.revokeObjectURL(url);

            this.updateStatus('QR codes ZIP downloaded');

        } catch (error) {
            console.error('Download error:', error);
            alert(`Download failed: ${error.message}`);
        }
    }

    // ===== Compass overlay UI — TEO QIYANG 22ACB06185 =====
    toggleCompassMode() {
        this.compass_mode = !this.compass_mode;
        if (this.compass_mode) {
            this.updateStatus('Compass Mode: Click center of map to set compass position');
            // disable other modes while selecting compass center
            this.connection_mode = false;
            this.deletion_mode = false;
            this.add_corner_mode = false;
        } else {
            this.updateStatus('Compass mode disabled');
        }
        this.updateDisplay();
    }

    setNorthDirection(value) {
        const customAngle = document.getElementById('customAngle');
        if (value === 'custom') {
            customAngle.style.display = 'inline-block';
        } else {
            customAngle.style.display = 'none';
            this.north_direction = parseInt(value);
            this.updateDisplay();
        }
    }

    setCustomNorthDirection(value) {
        const angle = parseInt(value);
        if (!isNaN(angle) && angle >= 0 && angle <= 359) {
            this.north_direction = angle;
            this.updateDisplay();
        }
    }

    drawCompass(ctx) {
        if (!this.compass_center) return;

        const [cx, cy] = this.compass_center;
        const radius = 50;

        // Rim
        ctx.strokeStyle = '#000';
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(cx, cy, radius, 0, 2 * Math.PI);
        ctx.stroke();

        // Fill
        ctx.fillStyle = 'rgba(255, 255, 255, 0.8)';
        ctx.fill();

        // North arrow (0° up)
        const northAngleRad = (this.north_direction - 90) * Math.PI / 180;
        const arrowLength = radius * 0.8;
        const arrowX = cx + Math.cos(northAngleRad) * arrowLength;
        const arrowY = cy + Math.sin(northAngleRad) * arrowLength;

        ctx.strokeStyle = '#ff0000';
        ctx.lineWidth = 3;
        ctx.beginPath();
        ctx.moveTo(cx, cy);
        ctx.lineTo(arrowX, arrowY);
        ctx.stroke();

        // Arrowhead
        const headLength = 10;
        const headAngle = Math.PI / 6;
        ctx.beginPath();
        ctx.moveTo(arrowX, arrowY);
        ctx.lineTo(
            arrowX - headLength * Math.cos(northAngleRad - headAngle),
            arrowY - headLength * Math.sin(northAngleRad - headAngle)
        );
        ctx.moveTo(arrowX, arrowY);
        ctx.lineTo(
            arrowX - headLength * Math.cos(northAngleRad + headAngle),
            arrowY - headLength * Math.sin(northAngleRad + headAngle)
        );
        ctx.stroke();

        // “N” label
        ctx.fillStyle = '#ff0000';
        ctx.font = 'bold 14px Arial';
        ctx.textAlign = 'center';
        ctx.fillText('N', arrowX, arrowY - 5);

        // E/S/W labels (derived from N)
        ctx.fillStyle = '#000';
        ctx.font = 'bold 12px Arial';
        ctx.textAlign = 'center';

        const eastAngle = northAngleRad + Math.PI / 2;
        const southAngle = northAngleRad + Math.PI;
        const westAngle = northAngleRad - Math.PI / 2;

        const labelRadius = radius * 0.7;

        ctx.fillText('E', cx + Math.cos(eastAngle) * labelRadius,  cy + Math.sin(eastAngle) * labelRadius + 4);
        ctx.fillText('S', cx + Math.cos(southAngle) * labelRadius, cy + Math.sin(southAngle) * labelRadius + 4);
        ctx.fillText('W', cx + Math.cos(westAngle) * labelRadius,  cy + Math.sin(westAngle) * labelRadius + 4);

        // Angle text
        ctx.fillStyle = '#666';
        ctx.font = '10px Arial';
        ctx.fillText(`${this.north_direction}°`, cx, cy + radius + 15);
    }
}

// Initialize when DOM is ready (no logic change)
document.addEventListener('DOMContentLoaded', () => {
    window.editor = new SimpleGraphEditor();
});
