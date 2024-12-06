import argparse
import base64
import configparser
import json
import threading
import time
import os
import sys

import sounddevice as sd
import numpy as np
import websocket
from websocket._abnf import ABNF
from flask import Flask, render_template, Response, jsonify, send_from_directory
import queue
import ssl

app = Flask(__name__, static_folder='static')

CHUNK = 1024
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
    global is_transcribing
    
    def audio_callback(indata, frames, time, status):
        if status:
            print(status)
        ws.send(indata.tobytes(), ABNF.OPCODE_BINARY)

    try:
        with sd.InputStream(callback=audio_callback, 
                            channels=CHANNELS, 
                            samplerate=RATE, 
                            dtype='int16'):
            while is_transcribing:
                sd.sleep(100)
    except Exception as e:
        print(f"Audio input error: {e}")
        is_transcribing = False

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
        with open("transcript.txt", "a") as f:
            f.write(" ".join(final_transcript) + "\n")
        print("Transcript appended to transcript.txt")
        final_transcript = []
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
    apikey = "Oogv4QFoAdBHL6kvvwnm-rOXAQfmSQFXvxHXWTGMUqfn"
    return ("apikey", apikey)

# Rest of the Flask routes remain the same as in the original script

if __name__ == "__main__":
    app.run(debug=True, port=8080)
