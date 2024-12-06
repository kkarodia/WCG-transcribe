import os
import json
import base64
import threading
import queue
import ssl
import websocket

from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

transcription_queue = queue.Queue()
final_transcript = []
is_transcribing = False

# Watson Speech to Text configuration
REGION_MAP = {
    'us-south': 'us-south.speech-to-text.watson.cloud.ibm.com'
}

def get_url():
    host = REGION_MAP["us-south"]
    return (f"wss://api.{host}/instances/57f91e09-9377-4a74-a1d2-43230edf7829/v1/recognize"
            "?model=en-US_BroadbandModel")

def get_auth():
    apikey = "Oogv4QFoAdBHL6kvvwnm-rOXAQfmSQFXvxHXWTGMUqfn"
    return ("apikey", apikey)

def on_message(ws, msg):
    global final_transcript
    data = json.loads(msg)
    if "results" in data:
        transcript = data['results'][0]['alternatives'][0]['transcript']
        transcription_queue.put(transcript)
        if data["results"][0]["final"]:
            final_transcript.append(transcript)

def on_error(ws, error):
    print(f"WebSocket Error: {error}")

def on_close(ws, close_status_code, close_msg):
    global is_transcribing
    is_transcribing = False
    print(f"WebSocket closed. Status: {close_status_code}. Message: {close_msg}")

def on_open(ws):
    global is_transcribing
    is_transcribing = True
    print("WebSocket opened")
    data = {
        "action": "start",
        "content-type": "audio/l16;rate=44100",
        "continuous": True,
        "interim_results": True,
        "max_alternatives": 3
    }
    ws.send(json.dumps(data).encode('utf8'))

def start_transcription():
    headers = {}
    userpass = ":".join(get_auth())
    headers["Authorization"] = "Basic " + base64.b64encode(userpass.encode()).decode()
    url = get_url()

    ws = websocket.WebSocketApp(url,
                                header=headers,
                                on_message=on_message,
                                on_error=on_error,
                                on_close=on_close)
    ws.on_open = on_open
    
    wst = threading.Thread(target=ws.run_forever, kwargs={"sslopt": {"cert_reqs": ssl.CERT_NONE}})
    wst.daemon = True
    wst.start()

    return ws

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    intent = data.get('intent', {}).get('name', '')

    if intent == 'Start Recording':
        # Start transcription websocket
        websocket_connection = start_transcription()
        
        # Collect transcript
        try:
            transcript = transcription_queue.get(timeout=10)
            return jsonify({
                "response": {
                    "text": f"Transcription started. First words: {transcript}"
                }
            })
        except queue.Empty:
            return jsonify({
                "response": {
                    "text": "Transcription started, but no words detected yet."
                }
            })
    
    return jsonify({"response": {"text": "Unknown intent"}})
    
@app.get('/')
def print_default():
    """ Greeting
    health check
    """
    # returning a dict equals to use jsonify()
    return {'message': 'This is the certifications API server'}
    
if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8080)
