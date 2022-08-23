import os
import sys
import datetime
import csv
import numpy as np
import pyaudio
import spl_lib as spl
from scipy.signal import lfilter
from gpiozero import LED
import time
import json

with open('settings.json', 'r') as f:
    config = json.load(f)

import read_noise_csvs as rnc

sys.path.insert(1, "../pixel_ring")
from pixel_ring import pixel_ring

sys.path.insert(1, "../rasp_pi_web_server")
from app import socketio

""" The following is similar to a basic CD quality
   When CHUNK size is 4096 it routinely throws an IOError.
   When it is set to 8192 it doesn't.
   IOError happens due to the small CHUNK size

   What is CHUNK? Let's say CHUNK = 4096
   math.pow(2, 12) => RATE / CHUNK = 100ms = 0.1 sec
"""

# Respeaker stuff
CHUNK = 1024
RESPEAKER_RATE = 16000
RESPEAKER_CHANNELS = 4
RESPEAKER_WIDTH = 2
RESPEAKER_INDEX = 2
FORMAT = pyaudio.paInt16  # 16 bit
CHANNEL = 2  # 1 means mono. If stereo, put 2
NUMERATOR, DENOMINATOR = spl.A_weighting(RESPEAKER_RATE)


def control_led(decibel_value, serious_range=config['infraction_level'], annoying_range=config['warning_level']):
    if decibel_value > serious_range:
        pixel_ring.set_brightness(100)
        pixel_ring.set_color(r=255)
    elif decibel_value > annoying_range:
        pixel_ring.set_brightness(5)
        pixel_ring.set_color(r=255, g=255)
    else:
        pixel_ring.set_color(g = 0)
    return None


def listen_once(stream, error_count):
    try:
        ## read() returns string. You need to decode it into an array later.
        block = stream.read(CHUNK, exception_on_overflow=False)
    except IOError as e:
        error_count += 1
        print(" (%d) Error recording: %s" % (error_count, e))
    else:
        ## Int16 is a np data type which is Integer (-32768 to 32767)
        ## If you put Int8 or Int32, the result numbers will be ridiculous
        decoded_block = np.fromstring(block, np.int16)
        ## This is where you apply A-weighted filter
        y = lfilter(NUMERATOR, DENOMINATOR, decoded_block)
        new = 20 * np.log10(spl.rms_flat(y))
    return new, error_count
   

def listen_all_the_time(stream, 
                            print_delta=config['print_delta'], 
                            infrac_value = config['infraction_level'], 
                            infrac_grace_period = config['infrac_grace_period'], 
                            send_threshold = config['send_threshold']):
    error_count = 0
    old = 0
    now_time = datetime.datetime.now()
    
    # Read previous history
    infrac_dict = rnc.read_one_day(csv_date = now_time, infrac_value = infrac_value, infrac_grace_period = infrac_grace_period)
    now_date = infrac_dict['filedate']
    last_infrac = infrac_dict['last_infrac_time']
    infrac_count = infrac_dict['infrac_count']


    with open(infrac_dict['filename'], "a") as csv_file:
        writer = csv.writer(csv_file)

        # Using a try/except here for keyboard interrupt if necessary (happens!)
        try:
            while now_time.date() == now_date:
                # Get new value
                new, error_count = listen_once(stream, error_count)
                # Write to file for storage later
                writer.writerow([now_time.isoformat(), new])
                # Send to redis queue
                if new >= send_threshold:
                    socketio.emit("decibel data", {'time':now_time.isoformat(),'data':int(new)}, namespace = '/test')
                
                # Calculate infractions
                # Current rule is more than 60 seconds
                if (new > infrac_value):
                    if (last_infrac is None) or (now_time > last_infrac + datetime.timedelta(seconds = infrac_grace_period)):
                        infrac_count += 1
                        last_infrac = now_time
                        socketio.emit("decibel infraction", {'last_infrac':now_time.isoformat(), 'infrac_count':int(infrac_count)}, namespace = '/test')

                # Flash the lights
                control_led(decibel_value=int(new))

                # Print out some info for debugging and just to show it's doing something
                # if abs(old - new) > print_delta:
                #     old = new
                #     print("A-weighted: {:+.2f} dB".format(new))

                # Get new time
                now_time = datetime.datetime.now()
        except KeyboardInterrupt as e:
            print(e)

    return None


if __name__ == "__main__":

    # Turn on LEDs
    power = LED(5)
    power.on()
    pixel_ring.wakeup()
    time.sleep(2)
    pixel_ring.off()

    """
    Listen to mic
    """
    pa = pyaudio.PyAudio()

    audio_stream = pa.open(
        format=FORMAT,
        channels=RESPEAKER_CHANNELS,
        rate=RESPEAKER_RATE,
        input=True,
        frames_per_buffer=CHUNK,
    )

    listen_all_the_time(stream=audio_stream)

    # Done for day
    audio_stream.stop_stream()
    audio_stream.close()
    pa.terminate()
    pixel_ring.think()
    time.sleep(2)
    pixel_ring.off()
    power.off()
