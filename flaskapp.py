# Python 3.5

import logging
from logging.handlers import RotatingFileHandler
import re
import shutil

from flask import Flask, request, session, render_template, make_response, redirect, url_for
from pyexcel import get_array
from pyexcel_io import save_data
import werkzeug.exceptions
from werkzeug.utils import secure_filename


# Initialize an app instance
app = Flask(__name__)

# Get app settings
import app_config
app.config.from_object(app_config.Config)

@app.route('/edit', methods=['GET','POST'])
def edit():
    # shutil.copyfile(app.config['EXTRA_STUDENTS_SOURCE_PATH'], app.config['EXTRA_STUDENTS_WORKING_PATH'])
    records = get_array(file_name=app.config['EXTRA_STUDENTS_WORKING_PATH'])
    if request.method == 'POST':
        changed = False
        removes = []
        for key in request.form.keys():
            m = re.match('remove_(\d+)', key)
            if m:
                removes.append(int(m.group(1)))
                changed = True

        records = [r for r in records if not (r[0] in removes)]
        if request.form['student_number'] and request.form['first_name'] and \
            request.form['last_name'] and request.form['email']:
            records.append([
                request.form['student_number'],
                request.form['first_name'],
                request.form['last_name'],
                '104',
                request.form['gender'],
                request.form['email'],
                '9919.1'
            ])
            changed = True
        if changed:
            save_data(app.config['EXTRA_STUDENTS_WORKING_PATH'], records, lineterminator='\n')

    return render_template('students.html', page_title='Edit Students', records=records)



## MAIN

if __name__ == '__main__':
    handler = RotatingFileHandler('rcweb.log', maxBytes=10000, backupCount=1)
    if app.config['DEBUG']:
        handler.setLevel(logging.INFO)
    else:
        handler.setLevel(logging.ERROR)
    app.logger.addHandler(handler)
    app.run()
