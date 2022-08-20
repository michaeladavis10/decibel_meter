import os, errno
import pyaudio
import spl_lib as spl
from scipy.signal import lfilter
import numpy as np
import datetime
from gpiozero import LED
import time
import csv
import sys

sys.path.insert(1, '../pixel_ring')
from pixel_ring import pixel_ring


''' The following is similar to a basic CD quality
   When CHUNK size is 4096 it routinely throws an IOError.
   When it is set to 8192 it doesn't.
   IOError happens due to the small CHUNK size

   What is CHUNK? Let's say CHUNK = 4096
   math.pow(2, 12) => RATE / CHUNK = 100ms = 0.1 sec
'''

CHUNK = 1024
RESPEAKER_RATE = 16000
RESPEAKER_CHANNELS = 4
RESPEAKER_WIDTH = 2

RESPEAKER_INDEX = 2

FORMAT = pyaudio.paInt16    # 16 bit
CHANNEL = 2    # 1 means mono. If stereo, put 2

NUMERATOR, DENOMINATOR = spl.A_weighting(RESPEAKER_RATE)

def get_path(base, tail, head=''):
    return os.path.join(base, tail) if head == '' else get_path(head, get_path(base, tail)[1:])

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

'''
Listen to mic
'''
pa = pyaudio.PyAudio()

stream = pa.open(
	format = FORMAT,
    channels = RESPEAKER_CHANNELS,
    rate = RESPEAKER_RATE,
    input = True,
    frames_per_buffer = CHUNK
)
    
def control_led(decibel, warnings, infractions, serious_range = 75, annoying_range = 65):

    if decibel > serious_range:
        pixel_ring.set_brightness(100)
        pixel_ring.set_color(r = 255)
        infractions += 1
        print(f'  Infraction #{infractions}')
    elif decibel > annoying_range:
        pixel_ring.set_brightness(5)
        pixel_ring.set_color(g = 255)
        warnings += 1
        print(f'  Warning #{warnings}')
    else:
        pixel_ring.off()
    
    return warnings, infractions


def listen(old=0, error_count=0):

    start_day = datetime.datetime.now().date()
    filename = os.path.join(BASE_DIR, 'data', start_day.strftime('%Y'), start_day.strftime('%Y%m%d') + '.csv')
    warnings = 0
    infractions = 0
    
    # Open the file for writing to
    with open(filename, 'a') as csv_file:
        writer = csv.writer(csv_file)
        # Don't write the header row because if a file restarts then it'll have extra headers
        # writer.writerow(['timestamp', 'decibel_measurement']) 
            
        print("Listening")
        while datetime.datetime.now().date() == start_day:

            try:
                ## read() returns string. You need to decode it into an array later.
                block = stream.read(CHUNK)
            except KeyboardInterrupt:
                break
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

                ## Store the value
                writer.writerow([datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f'), new])

                ## Flash the lights
                if abs(old - new) > 3:
                    old = new
                    print('A-weighted: {:+.2f} dB'.format(new))
                    warnings, infractions = control_led(decibel = new, warnings = warnings, infractions = infractions)

        # Done for day
        # stream.stop()
        stream.close()
        pa.terminate()
        pixel_ring.think()
        csv_file.close()

    return warnings, infractions

if __name__ == '__main__':
    power = LED(5)
    power.on()
    warnings, infractions = listen()
    power.off()
	
