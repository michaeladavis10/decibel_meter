import os
import sys
import datetime
import csv
import numpy as np
import pyaudio
import spl_lib as spl
from scipy.signal import lfilter
from gpiozero import LED

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

# My init
serious_value = 75  # decibels
annoying_value = 60  # decibels
print_delta = 20 # decibels
baseline_value = 34 # decibels
infrac_grace_period = 60 # seconds

# Respeaker stuff
CHUNK = 1024
RESPEAKER_RATE = 16000
RESPEAKER_CHANNELS = 4
RESPEAKER_WIDTH = 2
RESPEAKER_INDEX = 2
FORMAT = pyaudio.paInt16  # 16 bit
CHANNEL = 2  # 1 means mono. If stereo, put 2
NUMERATOR, DENOMINATOR = spl.A_weighting(RESPEAKER_RATE)

# Directory & files stuff
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def get_filename(this_date):
    filename = os.path.join(
        BASE_DIR,
        "data",
        this_date.strftime("%Y"),
        this_date.strftime("%Y%m%d") + ".csv",
    )

    if os.path.exists(filename):
        pass
    else:
        f = open(filename, "x")
    return filename


def read_one_day(csv_date, infrac_value = serious_value, infrac_grace_period = infrac_grace_period):

    filename = get_filename(csv_date)

    # Initialize counters
    infrac_count = 0
    last_infrac = None

    # Open file
    # Go line by line until decibel over infrac_value
    with open(filename, 'r') as read_obj:
        csv_reader = csv.reader(read_obj)
        for row in csv_reader:
            if float(row[1]) >= infrac_value:
                if row[0][-1] == 'Z':
                    infrac_time = datetime.datetime.fromisoformat(row[0][:-1]) # there's a z for sending to JS
                else:
                    infrac_time = datetime.datetime.fromisoformat(row[0])
                if (last_infrac is None) or (infrac_time > last_infrac + datetime.timedelta(seconds = infrac_grace_period)):
                    infrac_count += 1
                    last_infrac = infrac_time
    
    # Make pretty export (dictionary)
    infrac_dict = dict()
    infrac_dict['filedate'] = csv_date.date()
    infrac_dict['filename'] = filename
    infrac_dict['infrac_count'] = infrac_count
    infrac_dict['last_infrac_time'] = last_infrac

    return infrac_dict

def control_led(decibel_value, serious_range=serious_value, annoying_range=annoying_value):
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
   

def listen_all_the_time(stream, print_delta=print_delta, infrac_value = serious_value, infrac_grace_period = infrac_grace_period, send_threshold = annoying_value):
    error_count = 0
    old = 0
    now_time = datetime.datetime.now()
    
    # Read previous history
    infrac_dict = read_one_day(now_time)
    print(infrac_dict)
    infrac_count = infrac_dict['infrac_count'] 
    last_infrac = infrac_dict['last_infrac_time']
    now_date = infrac_dict['filedate']

    # Send this to the server immediately to update the chart
    socketio.emit("decibel infraction", {'last_infrac':now_time.isoformat() + 'Z', 'infrac_count':int(infrac_count)}, namespace = '/test')
    
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
                    socketio.emit("decibel data", {'time':now_time.isoformat() + 'Z','data':int(new)}, namespace = '/test')
                
                # Calculate infractions
                # Current rule is more than 60 seconds
                if (new > infrac_value) and (now_time > last_infrac + datetime.timedelta(seconds = infrac_grace_period)):
                    infrac_count += 1
                    last_infrac = now_time
                    socketio.emit("decibel infraction", {'last_infrac':now_time.isoformat() + 'Z', 'infrac_count':int(infrac_count)}, namespace = '/test')

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
    power.off()
