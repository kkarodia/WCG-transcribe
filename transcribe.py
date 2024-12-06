import argparse
import base64
import configparser
import json
import threading
import time
import os
import sys

import pyaudio
import websocket
from websocket._abnf import ABNF
from flask import Flask, render_template, Response, jsonify, send_from_directory
import queue
import ssl

app = Flask(__name__, static_folder='static')

CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 44100
FINALS = []
LAST = None

REGION_MAP = {
    'us-east': 'us-east.speech-to-text.watson.cloud.ibm.com',
    'us-south': 'us-south.speech-to-text.watson.cloud.ibm.com',
    'eu-gb': 'eu-gb.speech-to-text.watson.cloud.ibm.com',
    'eu-de': 'eu-de.speech-to-text.watson.cloud.ibm.com',
    'au-syd': 'au-syd.speech-to-text.watson.cloud.ibm.com',
    'jp-tok': 'jp-tok.speech-to-text.watson.cloud.ibm.com',
}

transcription_queue = queue.Queue()
final_transcript = []
is_transcribing = False

def read_audio(ws):
    global RATE, is_transcribing
    p = pyaudio.PyAudio()
    RATE = int(p.get_default_input_device_info()['defaultSampleRate'])
    stream = p.open(format=FORMAT,
                    channels=CHANNELS,
                    rate=RATE,
                    input=True,
                    frames_per_buffer=CHUNK)

    print("* recording")
    while is_transcribing:
        try:
            data = stream.read(CHUNK)
            ws.send(data, ABNF.OPCODE_BINARY)
        except websocket.WebSocketConnectionClosedException:
            print("WebSocket connection closed unexpectedly")
            break
        except ssl.SSLError as e:
            print(f"SSL Error occurred: {e}")
            break
        except Exception as e:
            print(f"An error occurred while sending audio data: {e}")
            break

    stream.stop_stream()
    stream.close()
    print("* done recording")

    try:
        data = {"action": "stop"}
        ws.send(json.dumps(data).encode('utf8'))
    except:
        print("Failed to send stop action")

    time.sleep(1)
    try:
        ws.close()
    except:
        print("Failed to close WebSocket")
    p.terminate()

def on_message(ws, msg):
    global final_transcript
    data = json.loads(msg)
    if "results" in data:
        transcript = data['results'][0]['alternatives'][0]['transcript']
        print(transcript)
        transcription_queue.put(transcript)
        if data["results"][0]["final"]:
            final_transcript.append(transcript)

def on_error(ws, error):
    print(f"Error occurred: {error}")

def on_close(ws, close_status_code, close_msg):
    global is_transcribing
    is_transcribing = False
    print(f"WebSocket closed. Status code: {close_status_code}. Close message: {close_msg}")
    save_transcript()

def save_transcript():
    global final_transcript
    if final_transcript:
        with open("transcript.txt", "a") as f:  # 'a' for append mode
            f.write(" ".join(final_transcript) + "\n")
        print("Transcript appended to transcript.txt")
        final_transcript = []  # Clear after saving
    else:
        print("No new transcript to save.")

def on_open(ws):
    global is_transcribing
    is_transcribing = True
    print("WebSocket opened")
    data = {
        "action": "start",
        "content-type": f"audio/l16;rate={RATE}",
        "continuous": True,
        "interim_results": True,
        "word_confidence": True,
        "timestamps": True,
        "max_alternatives": 3
    }
    ws.send(json.dumps(data).encode('utf8'))
    threading.Thread(target=read_audio, args=(ws,)).start()

def get_url():
    host = REGION_MAP["us-south"]
    return (f"wss://api.{host}/instances/57f91e09-9377-4a74-a1d2-43230edf7829/v1/recognize"
            "?model=en-US_BroadbandModel")

def get_auth():
    apikey = "RKqhmwIfHlPmg1ISs1Je8VZWMsDH8qheVjEwIn8b9mRt"
    return ("apikey", apikey)

@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/start_transcription')
def start_transcription():
    global is_transcribing, final_transcript
    is_transcribing = True
    final_transcript = []  # Reset final transcript

    def generate():
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

        while is_transcribing:
            try:
                transcript = transcription_queue.get(timeout=1)
                yield f"data: {transcript}\n\n"
            except queue.Empty:
                pass

    return Response(generate(), mimetype='text/event-stream')

@app.route('/stop_transcription')
def stop_transcription():
    global is_transcribing
    is_transcribing = False
    save_transcript()
    return jsonify({"status": "Transcription stopped and saved"})

@app.route('/get_final_transcript')
def get_final_transcript():
    save_transcript()  # Save any remaining transcript
    if os.path.exists("transcript.txt"):
        with open("transcript.txt", "r") as f:
            transcript = f.read()
        return jsonify({"transcript": transcript})
    else:
        return jsonify({"transcript": "No transcript available."})

@app.route('/clear_transcript')
def clear_transcript():
    global final_transcript
    final_transcript = []
    if os.path.exists("transcript.txt"):
        os.remove("transcript.txt")
    return jsonify({"status": "Transcript cleared"})

# default "homepage", also needed for health check by Code Engine
@app.get('/')
def print_default():
    """ Greeting
    health check
    """
    # returning a dict equals to use jsonify()
    return {'message': 'This is the certifications API server'}


# Start the actual app
# Get the PORT from environment or use the default
port = os.getenv('PORT', '5000')
if __name__ == "__main__":
    app.run(host='0.0.0.0',port=int(port))