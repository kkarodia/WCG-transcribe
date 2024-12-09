import os
import json
import base64
import threading
import queue
import ssl
import websocket
import logging
from typing import Optional

from flask import Flask, request, jsonify
from flask_cors import CORS

# Configure logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# Global variables
transcription_queue = queue.Queue()
final_transcript = []
is_transcribing = False
websocket_connection: Optional[websocket.WebSocketApp] = None

# Watson Speech to Text configuration
REGION_MAP = {
    'us-south': 'us-south.speech-to-text.watson.cloud.ibm.com'
}

def get_watson_credentials():
    """
    Retrieve Watson Speech to Text credentials.
    In a production environment, use secure credential management.
    """
    return {
        'apikey': os.getenv('WATSON_APIKEY', 'I9meB5ym-hSrrNCps6CvSyh_aFlDMNfj1k7497B7MeHf'),
        'instance_id': os.getenv('WATSON_INSTANCE_ID', 'c68822b4-6c19-4501-8840-c51fd7cbbb36'),
        'region': os.getenv('WATSON_REGION', 'us-south')
    }

def get_url(credentials):
    """
    Generate WebSocket URL for Watson Speech to Text
    """
    host = REGION_MAP[credentials['region']]
    return (f"wss://api.{host}/instances/{credentials['instance_id']}/v1/recognize"
            "?model=en-US_BroadbandModel")

def get_auth(credentials):
    """
    Get authentication credentials
    """
    return ("apikey", credentials['apikey'])

def on_message(ws, msg):
    """
    Process incoming WebSocket messages
    """
    global final_transcript
    try:
        data = json.loads(msg)
        logger.info(f"Received WebSocket message: {data}")

        if "results" in data and data['results']:
            for result in data['results']:
                if result.get('alternatives'):
                    transcript = result['alternatives'][0]['transcript']
                    logger.info(f"Partial transcript: {transcript}")
                    transcription_queue.put(transcript)

                    # Only append final results
                    if result.get('final', False):
                        logger.info(f"Final transcript segment: {transcript}")
                        final_transcript.append(transcript)
    except Exception as e:
        logger.error(f"Error processing WebSocket message: {e}")

def on_error(ws, error):
    """
    Handle WebSocket errors
    """
    logger.error(f"WebSocket Error: {error}")
    global is_transcribing
    is_transcribing = False

def on_close(ws, close_status_code, close_msg):
    """
    Handle WebSocket closure
    """
    global is_transcribing
    is_transcribing = False
    logger.info(f"WebSocket closed. Status: {close_status_code}. Message: {close_msg}")

def on_open(ws):
    """
    Configure WebSocket when opened
    """
    global is_transcribing
    is_transcribing = True
    logger.info("WebSocket opened")
    
    # Configure transcription settings
    data = {
        "action": "start",
        "content-type": "audio/l16;rate=44100",
        "continuous": True,
        "interim_results": True,
        "max_alternatives": 3
    }
    ws.send(json.dumps(data).encode('utf8'))

def start_transcription():
    """
    Start WebSocket transcription
    """
    try:
        credentials = get_watson_credentials()
        
        # Prepare headers
        headers = {}
        userpass = ":".join(get_auth(credentials))
        headers["Authorization"] = "Basic " + base64.b64encode(userpass.encode()).decode()
        
        # Get WebSocket URL
        url = get_url(credentials)
        logger.info(f"Connecting to WebSocket: {url}")

        # Create WebSocket connection
        ws = websocket.WebSocketApp(url,
                                    header=headers,
                                    on_message=on_message,
                                    on_error=on_error,
                                    on_close=on_close)
        ws.on_open = on_open
        
        # Run WebSocket in a separate thread
        wst = threading.Thread(target=ws.run_forever, 
                               kwargs={"sslopt": {"cert_reqs": ssl.CERT_NONE}})
        wst.daemon = True
        wst.start()

        return ws
    except Exception as e:
        logger.error(f"Failed to start transcription: {e}")
        return None

@app.route('/webhook', methods=['POST'])
def webhook():
    """
    Handle webhook requests for transcription control
    """
    global is_transcribing, websocket_connection, final_transcript
    
    try:
        data = request.json
        intent = data.get('intent', {}).get('name', '')
        logger.info(f"Received intent: {intent}")

        if intent == 'Start Recording':
            # Reset transcription state
            final_transcript.clear()
            transcription_queue.queue.clear()
            
            # Start transcription websocket
            websocket_connection = start_transcription()
            
            if websocket_connection:
                return jsonify({
                    "response": {
                        "text": "Transcription started successfully."
                    }
                })
            else:
                return jsonify({
                    "response": {
                        "text": "Failed to start transcription."
                    }
                }), 500
        
        elif intent == 'Stop Recording':
            if websocket_connection:
                websocket_connection.close()
                is_transcribing = False
                
                return jsonify({
                    "response": {
                        "text": "Transcription stopped."
                    }
                })
            
            return jsonify({
                "response": {
                    "text": "No active transcription to stop."
                }
            })
        
        elif intent == 'Get Transcript':
            logger.info(f"Retrieving transcript. Current state: {final_transcript}")
            
            if final_transcript:
                full_transcript = " ".join(final_transcript)
                final_transcript.clear()  # Clear for next session
                
                return jsonify({
                    "response": {
                        "text": "Here's the transcript.",
                        "transcript": full_transcript
                    }
                })
            
            return jsonify({
                "response": {
                    "text": "No transcript available.",
                    "transcript": ""
                }
            })
        
        return jsonify({"response": {"text": "Unknown intent"}}), 400
    
    except Exception as e:
        logger.error(f"Webhook processing error: {e}")
        return jsonify({"response": {"text": "Internal server error"}}), 500

@app.route('/', methods=['GET'])
def health_check():
    """
    Simple health check endpoint
    """
    return jsonify({
        'status': 'healthy',
        'transcribing': is_transcribing,
        'transcript_length': len(final_transcript)
    })

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8080)
