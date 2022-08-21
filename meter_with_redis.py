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

""" The following is similar to a basic CD quality
   When CHUNK size is 4096 it routinely throws an IOError.
   When it is set to 8192 it doesn't.
   IOError happens due to the small CHUNK size

   What is CHUNK? Let's say CHUNK = 4096
   math.pow(2, 12) => RATE / CHUNK = 100ms = 0.1 sec
"""

# My init
serious_value = 75  # decibels
annoying_value = 65  # decibels
print_delta = 10 # decibels

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


def control_led(decibel_value, serious_range=serious_value, annoying_range=annoying_value):
    if decibel_value > serious_range:
        pixel_ring.set_brightness(100)
        pixel_ring.set_color(r=255)
    elif decibel_value > annoying_range:
        pixel_ring.set_brightness(5)
        pixel_ring.set_color(g=255)
    else:
        pixel_ring.off()
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


def send_to_redis_queue(decibel_value):
    # socketio.emit("decibel data", {"data": decibel_value})
    return None


def listen_all_the_time(stream, print_delta=print_delta):
    error_count = 0
    old = 0
    now_time = datetime.datetime.now()
    now_date = now_time.date()
    filename = get_filename(this_date=now_date)

    with open(filename, "a") as csv_file:
        writer = csv.writer(csv_file)

        # Using a try/except here for keyboard interrupt if necessary (happens!)
        try:
            while now_time.date() == now_date:
                # Get new value
                new, error_count = listen_once(stream, error_count)
                # Flash the lights
                control_led(decibel_value=new)
                # Send to redis queue
                send_to_redis_queue(decibel_value=new)
                # Write to file for storage later
                writer.writerow([now_time.strftime("%Y-%m-%d %H:%M:%S.%f"), new])
                # Print out some info for debugging
                if abs(old - new) > print_delta:
                    old = new
                    print("A-weighted: {:+.2f} dB".format(new))
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
    pixel_ring.think()
    power.off()
