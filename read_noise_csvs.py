import os
import datetime
import csv
import json 


# Directory & files stuff
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(BASE_DIR, 'settings.json'), 'r') as f:
    config = json.load(f)
    

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

def read_one_day(csv_date, infrac_value = config['infraction_level'], infrac_grace_period = config['infrac_grace_period']):

    filename = get_filename(csv_date)

    # Initialize counters
    infrac_count = 0
    last_infrac = None

    # Go line by line until decibel over infrac_value
    with open(filename, 'r') as read_obj:
        csv_reader = csv.reader(x.replace('\0','') for x in read_obj)
        for row in csv_reader:
            try:
                if float(row[1]) >= infrac_value:
                    if row[0][-1] == 'Z':
                        infrac_time = datetime.datetime.fromisoformat(row[0][:-1]) # there's a z for sending to JS
                    else:
                        infrac_time = datetime.datetime.fromisoformat(row[0])
                    if (last_infrac is None) or (infrac_time > last_infrac + datetime.timedelta(seconds = infrac_grace_period)):
                        infrac_count += 1
                        last_infrac = infrac_time
            except Exception as e:
                continue
                # sometimes there's a nul bite on power failure



    
    # Make pretty export (dictionary)
    infrac_dict = dict()
    infrac_dict['filedate'] = csv_date.date()
    infrac_dict['filename'] = filename
    infrac_dict['infrac_count'] = infrac_count
    infrac_dict['last_infrac'] = last_infrac

    return infrac_dict


def get_past_x_days(csv_date, n_days):

    # This is really just going to Javascript charts, so they take in 
    # x: [], y = []
    # And we want it in chronological order
    results = {'x':[], 'y':[]}
    for n in range(-n_days + 1, 1, 1):
        this_date = csv_date + datetime.timedelta(days = n)
        this_infrac_dict = read_one_day(this_date)
        results['x'].append(this_infrac_dict['filedate'].isoformat())
        results['y'].append(this_infrac_dict['infrac_count'])

    return results

if __name__ == "__main__":
    # infrac_dict = read_one_day(datetime.datetime.now())
    # print(infrac_dict)
    p7d = get_past_x_days(datetime.datetime.now(), n_days = 7)
    print(p7d)