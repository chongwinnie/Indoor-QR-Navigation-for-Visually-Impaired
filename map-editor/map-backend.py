from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import qrcode
from io import BytesIO
import base64
from PIL import Image, ImageDraw, ImageFont
import json
import math
import os
import zipfile
import tempfile

app = Flask(__name__)
CORS(app)

class QRCodeGenerator:
    def __init__(self):
        self.crc_table = self._init_crc_table()

    def _init_crc_table(self):
        """Initialize CRC16 lookup table"""
        table = []
        for i in range(256):
            crc = 0
            c = i
            for j in range(8):
                if (crc ^ c) & 1:
                    crc = (crc >> 1) ^ 0xA001
                else:
                    crc = crc >> 1
                c = c >> 1
            table.append(crc)
        return table

    def _calculate_crc16(self, data):
        """Calculate CRC16 checksum"""
        crc = 0xFFFF
        for byte in data.encode('utf-8'):
            crc = (crc >> 8) ^ self.crc_table[(crc ^ byte) & 0xFF]
        return crc ^ 0xFFFF

    def generate_corridor_nodes(self, corridor_data, scale, sampling_m=5.0):
        """Generate QR nodes every 5 meters along corridors"""
        nodes = []

        if isinstance(corridor_data, dict) and 'corridorNodes' in corridor_data and 'corridorSegments' in corridor_data:
            # New node-segment format
            nodes = self._generate_nodes_from_segments(
                corridor_data['corridorNodes'],
                corridor_data['corridorSegments'],
                scale,
                sampling_m
            )
        elif isinstance(corridor_data, list) and len(corridor_data) >= 2:
            # Legacy point format
            nodes = self._generate_nodes_from_points(corridor_data, scale, sampling_m)
        else:
            print("Warning: No valid corridor data for QR generation")

        return nodes

    def _generate_nodes_from_segments(self, corridor_nodes, corridor_segments, scale, sampling_m):
        """Generate QR nodes from corridor segments - CORNER NAMES like C001, C002, C003"""
        qr_nodes = []
        processed_segments = set()
        corner_counter = 1  # Start from 1 for C001, C002, etc.

        # Process each corridor node as a starting point
        for start_corridor_node in corridor_nodes:
            # Add QR node at this major corridor node (corner node)
            qr_nodes.append({
                'id': f'C{str(corner_counter).zfill(3)}',  # Corner format: C001, C002, C003...
                'chainageM': 0,
                'xM': start_corridor_node['x'] / scale,
                'yM': start_corridor_node['y'] / scale,
                'xPx': start_corridor_node['x'],
                'yPx': start_corridor_node['y'],
                'segment_start_node': start_corridor_node['id']
            })
            corner_counter += 1

            # Process segments that start from this node
            for segment in corridor_segments:
                if (segment['startNodeId'] == start_corridor_node['id'] and
                    segment['id'] not in processed_segments):

                    end_node = next((n for n in corridor_nodes if n['id'] == segment['endNodeId']), None)
                    if not end_node:
                        continue

                    segment_length_px = segment['length']
                    segment_length_m = segment_length_px / scale

                    # Place QR nodes every sampling_m meters along THIS segment
                    current_chainage = sampling_m  # Start at 5m, 10m, 15m...

                    while current_chainage < segment_length_m:
                        # Calculate position along this segment
                        t = current_chainage / segment_length_m if segment_length_m > 0 else 0

                        node_x = start_corridor_node['x'] + t * (end_node['x'] - start_corridor_node['x'])
                        node_y = start_corridor_node['y'] + t * (end_node['y'] - start_corridor_node['y'])

                        qr_nodes.append({
                            'id': f'C{str(corner_counter).zfill(3)}',  # Corner format: C002, C003, C004...
                            'chainageM': current_chainage,
                            'xM': node_x / scale,
                            'yM': node_y / scale,
                            'xPx': node_x,
                            'yPx': node_y,
                            'segment_start_node': start_corridor_node['id'],
                            'segment_id': segment['id']
                        })

                        corner_counter += 1
                        current_chainage += sampling_m

                    processed_segments.add(segment['id'])

        print(f"Generated {len(qr_nodes)} corner QR nodes with format (C001, C002, C003...)")
        return qr_nodes

    def _generate_nodes_from_points(self, corridor_points, scale, sampling_m):
        """Generate QR nodes from corridor points every sampling_m meters"""
        nodes = []
        corner_counter = 1  # Start from 1 for C001
        total_distance = 0

        # Always add start node
        if corridor_points:
            start_point = corridor_points[0]
            nodes.append({
                'id': f'C{str(1).zfill(3)}',  # Start with C001
                'chainageM': 0,
                'xM': start_point[0] / scale,
                'yM': start_point[1] / scale,
                'xPx': start_point[0],
                'yPx': start_point[1]
            })

        # Process each segment
        for i in range(len(corridor_points) - 1):
            p1 = corridor_points[i]
            p2 = corridor_points[i + 1]

            segment_length_px = math.sqrt((p2[0] - p1[0])**2 + (p2[1] - p1[1])**2)
            segment_length_m = segment_length_px / scale

            segment_start = total_distance
            segment_end = total_distance + segment_length_m

            next_node_position = sampling_m
            while next_node_position < segment_end:
                if next_node_position > segment_start:
                    distance_along_segment = next_node_position - segment_start
                    t = distance_along_segment / segment_length_m if segment_length_m > 0 else 0

                    node_x = p1[0] + t * (p2[0] - p1[0])
                    node_y = p1[1] + t * (p2[1] - p1[1])

                    nodes.append({
                        'id': f'C{str(corner_counter).zfill(3)}',  # Corner format: C001, C002...
                        'chainageM': next_node_position,
                        'xM': node_x / scale,
                        'yM': node_y / scale,
                        'xPx': node_x,
                        'yPx': node_y
                    })
                    corner_counter += 1

                next_node_position += sampling_m

            total_distance += segment_length_m

        return nodes

    def create_corridor_payload(self, node, building_id, version):
        """Create simple QR payload - just node ID for mobile app lookup"""
        return node['id']

    def create_destination_payload(self, destination, nearest_node, building_id, version):
        """Create simple QR payload - just room ID for mobile app lookup"""
        return destination['id']

    def generate_qr_image(self, payload, node_id):
        """Generate QR code image with 4 identical QR codes in 2x2 grid layout"""
        # Generate single QR code - larger size, smaller border for closer layout
        qr = qrcode.QRCode(version=1, box_size=10, border=1)  # Larger QR, smaller border
        qr.add_data(payload)
        qr.make(fit=True)

        single_qr = qr.make_image(fill_color="black", back_color="white")

        # Convert to RGB mode to avoid paste() compatibility issues
        if single_qr.mode != 'RGB':
            single_qr = single_qr.convert('RGB')

        qr_width, qr_height = single_qr.size

        # Create 2x2 grid layout with smaller gaps (4 identical QR codes)
        gap_reduction = 6  # Pixels to overlap for closer appearance
        grid_width = qr_width * 2 - gap_reduction
        grid_height = qr_height * 2 - gap_reduction

        # Create new image for the 2x2 grid
        grid_image = Image.new('RGB', (grid_width, grid_height), 'white')

        # Paste the same QR code in all 4 positions with slight overlap for closer appearance
        positions = [
            (0, 0),                                      # Top-left
            (qr_width - gap_reduction, 0),               # Top-right (closer)
            (0, qr_height - gap_reduction),              # Bottom-left (closer)
            (qr_width - gap_reduction, qr_height - gap_reduction) # Bottom-right (closer)
        ]

        for pos in positions:
            try:
                grid_image.paste(single_qr, pos)
            except ValueError as e:
                # Fallback: use box coordinates if position fails
                left, top = pos
                right = min(left + qr_width, grid_width)   # Ensure we don't exceed grid bounds
                bottom = min(top + qr_height, grid_height)  # Ensure we don't exceed grid bounds
                box = (left, top, right, bottom)
                grid_image.paste(single_qr, box)
                print(f"Used box coordinates for position {pos}")

        # Add subtle separator lines between QR codes (adjusted for closer positioning)
        draw = ImageDraw.Draw(grid_image)

        # Very light separator lines since QR codes are now closer and overlapping
        line_x = qr_width - gap_reduction // 2  # Position line in the middle of overlap
        line_y = qr_height - gap_reduction // 2

        # Vertical line in the middle
        draw.line([(line_x, 0), (line_x, grid_height)], fill=(240, 240, 240), width=1)
        # Horizontal line in the middle
        draw.line([(0, line_y), (grid_width, line_y)], fill=(240, 240, 240), width=1)

        # Add label at the bottom
        try:
            font = ImageFont.truetype("arial.ttf", 16)
        except:
            try:
                font = ImageFont.load_default()
            except:
                font = None

        if font:
            # Add white space at bottom for label
            labeled_image = Image.new('RGB', (grid_width, grid_height + 30), 'white')
            labeled_image.paste(grid_image, (0, 0))

            draw = ImageDraw.Draw(labeled_image)
            text = f"{node_id} - {payload}"

            # Center the text (compatible with older PIL versions)
            try:
                # Try new method first
                bbox = draw.textbbox((0, 0), text, font=font)
                text_width = bbox[2] - bbox[0]
            except (AttributeError, ValueError):
                # Fallback for older PIL versions
                text_size = draw.textsize(text, font=font)
                text_width = text_size[0]

            text_x = (grid_width - text_width) // 2

            draw.text((text_x, grid_height + 5), text, fill='black', font=font)
            grid_image = labeled_image

        print(f"Generated 4-up QR code for {node_id}: {grid_image.size[0]}x{grid_image.size[1]}px")

        buffer = BytesIO()
        grid_image.save(buffer, format='PNG')
        return buffer.getvalue()

    def generate_qr_codes(self, map_data):
        """Generate QR codes from map data - includes 5-meter corridor nodes"""
        qr_codes = []
        building_id = map_data.get('buildingId', 'BUILDING')
        version = map_data.get('version', '1.0')
        scale = map_data.get('scale', 42.7)

        # Prepare corridor data
        corridor_data = None
        if 'corridorNodes' in map_data and 'corridorSegments' in map_data:
            corridor_data = {
                'corridorNodes': map_data['corridorNodes'],
                'corridorSegments': map_data['corridorSegments']
            }
        elif 'corridorPoints' in map_data:
            corridor_data = map_data['corridorPoints']

        if not corridor_data:
            return qr_codes

        # Generate corridor nodes every 5 meters
        corridor_nodes = self.generate_corridor_nodes(corridor_data, scale, 5.0)
        print(f"Generated {len(corridor_nodes)} corridor nodes for QR codes")

        # Generate QR codes for corridor nodes (CORNERS)
        for node in corridor_nodes:
            payload = self.create_corridor_payload(node, building_id, version)
            img_data = self.generate_qr_image(payload, node['id'])

            qr_codes.append({
                'id': node['id'],
                'type': 'corner',  # Changed from 'corridor' to 'corner'
                'filename': f"{node['id']}.png",
                'payload': payload,
                'image': base64.b64encode(img_data).decode('utf-8'),
                'chainage': node['chainageM'],
                'x': node['xPx'],
                'y': node['yPx']
            })

        # Generate QR codes for destinations (ROOMS)
        for i, dest in enumerate(map_data.get('destinations', [])):
            # Force ROOM ID format - always use R### regardless of existing ID
            dest['id'] = f"R{str(i+1).zfill(3)}"  # Room format: R001, R002, R003...

            # Find nearest corridor node
            nearest_node = self.find_nearest_corridor_node(dest, corridor_nodes)
            if not nearest_node:
                continue

            payload = self.create_destination_payload(dest, nearest_node, building_id, version)
            img_data = self.generate_qr_image(payload, dest['id'])

            qr_codes.append({
                'id': dest['id'],
                'type': 'room',  # Changed from 'destination' to 'room'
                'filename': f"{dest['id']}.png",
                'payload': payload,
                'image': base64.b64encode(img_data).decode('utf-8'),
                'name': dest.get('name', ''),
                'chainage': nearest_node['chainageM']
            })

        return qr_codes

    def find_nearest_corridor_node(self, destination, corridor_nodes):
        """Find the nearest corridor node to a destination"""
        if not corridor_nodes:
            return None

        min_distance = float('inf')
        nearest_node = None

        for node in corridor_nodes:
            dx = destination['x'] - node['xPx']
            dy = destination['y'] - node['yPx']
            distance = math.sqrt(dx*dx + dy*dy)

            if distance < min_distance:
                min_distance = distance
                nearest_node = node

        return nearest_node

    def generate_placement_map(self, map_data, map_type='qr_placement'):
        """Generate annotated map with QR code or destination locations"""
        try:
            # Load base map image
            base_map_path = 'assets/map.jpg'
            if not os.path.exists(base_map_path):
                base_map_path = '../backend/static/map.jpg'

            if not os.path.exists(base_map_path):
                # Create a placeholder map if no base map exists
                img = Image.new('RGB', (1600, 1200), color='lightgray')
                draw = ImageDraw.Draw(img)
                draw.text((50, 50), "Base map not found", fill='black')
            else:
                img = Image.open(base_map_path)

            draw = ImageDraw.Draw(img)

            # Try to load a font, fall back to default if not available
            try:
                font = ImageFont.truetype("arial.ttf", 20)
                small_font = ImageFont.truetype("arial.ttf", 14)
            except:
                try:
                    font = ImageFont.load_default()
                    small_font = ImageFont.load_default()
                except:
                    font = None
                    small_font = None

            if map_type == 'qr_placement':
                # Draw corridor nodes and QR placement locations
                if 'corridorNodes' in map_data:
                    for node in map_data['corridorNodes']:
                        x, y = int(node['x']), int(node['y'])

                        # Draw node circle
                        color = self._get_node_color(node.get('type', 'straight'))
                        draw.ellipse([x-8, y-8, x+8, y+8], fill=color, outline='black', width=2)

                        # Draw node ID
                        if font:
                            draw.text((x+15, y-10), node['id'], fill='black', font=font)
                        else:
                            draw.text((x+15, y-10), node['id'], fill='black')

                # Draw corridor segments
                if 'corridorSegments' in map_data:
                    for segment in map_data['corridorSegments']:
                        start_node = next((n for n in map_data['corridorNodes'] if n['id'] == segment['startNodeId']), None)
                        end_node = next((n for n in map_data['corridorNodes'] if n['id'] == segment['endNodeId']), None)

                        if start_node and end_node:
                            draw.line([start_node['x'], start_node['y'], end_node['x'], end_node['y']],
                                     fill='blue', width=4)

            elif map_type == 'destination_placement' or map_type == 'destinations':
                # ROOM MAP: ONLY show rooms (no corridor nodes!)
                destinations = map_data.get('destinations', [])
                print(f"🎯 ROOM MAP: mapType={map_type}, Received {len(destinations)} rooms")
                print(f"🎯 Map data keys: {list(map_data.keys())}")
                print(f"🎯 Full room data: {destinations}")

                if len(destinations) == 0:
                    print("⚠️ WARNING: No rooms found in map data!")
                    print(f"⚠️ Map data keys: {list(map_data.keys())}")

                for i, dest in enumerate(destinations):
                    x, y = int(dest['x']), int(dest['y'])
                    # Ensure room ID uses R### format
                    dest_id = dest.get('id', f'R{str(i+1).zfill(3)}')
                    if not dest_id.startswith('R'):
                        dest_id = f'R{str(i+1).zfill(3)}'
                        dest['id'] = dest_id  # Update the actual data
                    dest_name = dest.get('name', dest_id)

                    print(f"🎯 Drawing room #{i+1}: {dest_id} '{dest_name}' at ({x}, {y})")

                    # Draw large, very visible red CIRCLE for room
                    draw.ellipse([x-20, y-20, x+20, y+20], fill='red', outline='darkred', width=4)

                    # Draw room ID/name in large text
                    if font:
                        draw.text((x+25, y-15), dest_name, fill='darkred', font=font)
                    else:
                        draw.text((x+25, y-15), dest_name, fill='darkred')

                    # Draw smaller ID below
                    if small_font:
                        draw.text((x+25, y+5), dest_id, fill='red', font=small_font)

                print(f"🎯 ROOM MAP: Finished drawing {len(destinations)} rooms")

            # Draw 5-meter QR code locations ONLY for QR placement map
            if map_type == 'qr_placement':
                scale = map_data.get('scale', 42.7)
                corridor_data = None
                if 'corridorNodes' in map_data and 'corridorSegments' in map_data:
                    corridor_data = {
                        'corridorNodes': map_data['corridorNodes'],
                        'corridorSegments': map_data['corridorSegments']
                    }
                elif 'corridorPoints' in map_data:
                    corridor_data = map_data['corridorPoints']

                if corridor_data:
                    qr_nodes = self.generate_corridor_nodes(corridor_data, scale, 5.0)
                    print(f"🟢 QR MAP: Drawing {len(qr_nodes)} QR locations")

                    for node in qr_nodes:
                        x, y = int(node['xPx']), int(node['yPx'])

                        # Draw QR location marker (green circle for 5-meter nodes)
                        draw.ellipse([x-6, y-6, x+6, y+6], fill='green', outline='darkgreen', width=2)

                        # Draw QR ID
                        if small_font:
                            draw.text((x+10, y-8), f"{node['id']}\n{node['chainageM']:.0f}m", fill='darkgreen', font=small_font)
                        else:
                            draw.text((x+10, y-8), f"{node['id']}", fill='darkgreen')

            # Save to buffer
            buffer = BytesIO()
            img.save(buffer, format='PNG')
            buffer.seek(0)

            return base64.b64encode(buffer.getvalue()).decode()

        except Exception as e:
            print(f"Error generating placement map: {e}")
            raise

    def _get_node_color(self, node_type):
        """Get color based on node type"""
        colors = {
            'endpoint': 'red',
            'corner': 'orange',
            'intersection': 'yellow',
            'straight': 'lightblue'
        }
        return colors.get(node_type, 'lightblue')

# Initialize QR generator
qr_generator = QRCodeGenerator()

@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({
        'status': 'healthy',
        'message': 'Enhanced backend is working',
        'features': ['qr_generation', 'map_images', 'export']
    })

@app.route('/api/generate-qr', methods=['POST'])
def generate_qr_codes():
    try:
        data = request.get_json()
        print("QR Generation request:")
        print(f"  Keys: {list(data.keys()) if data else 'None'}")
        print(f"  Nodes: {len(data.get('corridorNodes', []))} | Segments: {len(data.get('corridorSegments', []))}")

        if not data:
            return jsonify({'error': 'No data provided'}), 400

        # Validate required data
        if not data.get('corridorNodes') and not data.get('corridorPoints'):
            return jsonify({'error': 'No corridor data provided'}), 400

        if not data.get('buildingId'):
            return jsonify({'error': 'Building ID is required'}), 400

        if not data.get('scale'):
            return jsonify({'error': 'Scale is required'}), 400

        qr_codes = qr_generator.generate_qr_codes(data)

        print(f"Successfully generated {len(qr_codes)} QR codes")

        return jsonify({
            'success': True,
            'qr_codes': qr_codes,
            'count': len(qr_codes),
            'message': f'Generated {len(qr_codes)} QR codes: Corners (C001, C002...) and Rooms (R001, R002...)'
        })

    except Exception as e:
        print(f"ERROR in QR generation: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e), 'type': type(e).__name__}), 500

@app.route('/api/generate-placement-map', methods=['POST'])
def generate_placement_map():
    try:
        data = request.get_json()
        print("Placement map request data:")
        print(json.dumps({k: len(v) if isinstance(v, list) else v for k, v in data.items()}, indent=2))

        if not data:
            return jsonify({'error': 'No data provided'}), 400

        map_type = data.get('mapType', 'qr_placement')
        image_data = qr_generator.generate_placement_map(data, map_type)

        return jsonify({
            'success': True,
            'image': image_data,
            'mapType': map_type,
            'message': f'{map_type} map generated successfully'
        })

    except Exception as e:
        print(f"Error generating placement map: {e}")
        return jsonify({'error': str(e), 'message': 'Map generation failed'}), 500

@app.route('/api/download-qr-zip', methods=['POST'])
def download_qr_zip():
    try:
        data = request.get_json()

        if not data:
            return jsonify({'error': 'No data provided'}), 400

        # Check if we received already generated QR codes from frontend
        if 'qr_codes' in data:
            qr_codes = data['qr_codes']
        else:
            # Generate QR codes from map data (fallback)
            qr_codes = qr_generator.generate_qr_codes(data)

        if not qr_codes:
            return jsonify({'error': 'No QR codes provided'}), 400

        print(f"Creating ZIP with {len(qr_codes)} QR codes")

        # Create temporary file
        temp_zip = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
        temp_zip.close()

        try:
            with zipfile.ZipFile(temp_zip.name, 'w') as zipf:
                # qr_codes is a list of dictionaries
                for qr_info in qr_codes:
                    qr_id = qr_info.get('id', 'unknown')
                    filename = qr_info.get('filename', f'{qr_id}.png')

                    # Decode base64 image
                    img_data = base64.b64decode(qr_info['image'])

                    # Add to zip with proper filename
                    zipf.writestr(filename, img_data)

                    # Add metadata file
                    metadata = {
                        'id': qr_id,
                        'payload': qr_info['payload'],
                        'type': qr_info.get('type', 'unknown'),
                        'filename': filename
                    }
                    zipf.writestr(f'{qr_id}.json', json.dumps(metadata, indent=2))

            return send_file(temp_zip.name, as_attachment=True, download_name='qr_codes_4up.zip')
        finally:
            # Clean up temp file after sending
            try:
                os.unlink(temp_zip.name)
            except:
                pass

    except Exception as e:
        print(f"Error creating QR zip: {e}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    print("Starting Enhanced Indoor Navigation Map Editor Backend...")
    print("QR Code library available:", 'qrcode' in globals())
    print()
    print("📍 Available endpoints:")
    for rule in app.url_map.iter_rules():
        print(f"   {rule.methods} {rule}")
    print()
    print("🚀 Starting server on http://127.0.0.1:5501")
    print("Press Ctrl+C to stop")
    print()
    app.run(host='127.0.0.1', port=5501, debug=True)
