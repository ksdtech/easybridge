import argparse
import csv
import datetime
import dateutil.parser
import os
import re
import sys
import zipfile
import pysftp

DAYS_PAST = 7
DAYS_UPCOMING = 7
AUTOSEND = True
LINETERM_IN = "\n"

MATH_COURSE_HEADERS = [s.strip() for s in '''
SchoolID
Course_Number
Course_Name
School_Name
'''.split('\n')[1:-1]]

STUDENT_HEADERS = [s.strip() for s in '''
Student_Number
SchoolID
EntryDate
ExitDate
First_Name
Middle_Name
Last_Name
Gender
Grade_Level
Network_ID
Mother_First
Mother
Mother_Email
Father_First
Father
Father_Email
'''.split('\n')[1:-1]]

TEST_STUDENT_HEADERS = [s.strip() for s in '''
Student_Number
First_Name
Last_Name
SchoolID
Gender
Network_ID
Sections
'''.split('\n')[1:-1]]

TEACHER_HEADERS = [s.strip() for s in '''
TeacherNumber
First_Name
Last_Name
SchoolID
Email_Addr
Status
StaffStatus
CA_SEID
'''.split('\n')[1:-1]]

COURSE_HEADERS = [s.strip() for s in '''
SchoolID
Course_Name
Course_Number
Alt_Course_Number
Code
'''.split('\n')[1:-1]]

SECTION_HEADERS = [s.strip() for s in '''
SchoolID
Course_Number
Section_Number
TermID
[13]Abbreviation
[13]FirstDay
[13]LastDay
Expression
[05]TeacherNumber
'''.split('\n')[1:-1]]

CC_HEADERS = [s.strip() for s in '''
Course_Number
Section_Number
SchoolID
TermID
DateEnrolled
DateLeft
Expression
[01]Student_Number
[01]First_Name
[01]Last_Name
[05]TeacherNumber
[05]Last_Name
'''.split('\n')[1:-1]]

# Required character encoding is UTF-8.
# Data fields must be comma delimited.
# Data must be enclosed in double quotes. Fields without data should be represented as
# an empty string.
# Dates should be represented as a string in the following format: yyyy-mm-dd. 
# For date fields requiring only a year, the format is yyyy.
# Boolean values should be represented as "true" or "false".

# Google SAML metadata file will have to be downloaded and sent to Pearson
# Turn on SAML after rollover, but before 8/22
# Return District matching spreadsheets

# Assignments file for SpEd teachers to have access
# Match teachers, if they have any custom content 
# Pearson will supply a list of logins, find out which login has the custom content

# Teachers will use new URL
# Will create link on Google page, but that one won't work
# Pearson will supply the correct link (contains link to metadata file)

# Suspend users from previous years
# Zip up files and place on SFTP
# zip-ship tool might be useful - will be on the SFTP site

# Convert dates to YYYY-MM-DD
# Calendar year is for start of year

def formatDate(s):
    m, d, y = s.split('/')
    return '-'.join((y, m, d))
    
def parseDate(s):
    dt = dateutil.parser.parse(s)
    return dt.date()

class EasyBridgeUploader(object):
    def __init__(self, source_dir=None, output_dir=None, autosend=False, effective_date=None):
        # Must change at start of year
        self.current_year = 2016
        self.year_start = '2016-08-29'
        self.year_end = '2017-06-17'
        
        self.students = { }
        self.extras = { }
        self.teachers = { }
        self.courses = { }
        self.sections = { }
        self.enrollments = { }
        self.course_names = { }
        self.included_courses = [ ]
        self.schools = [ ]
        self.source_dir = source_dir or './source'
        self.output_dir = output_dir or './output'
        try:
            os.makedirs(self.output_dir)
        except:
            pass
        self.autosend = autosend
        if effective_date is None:
          effective_date = datetime.date.today()
        self.effective_date = effective_date

    def loadData(self):
        self.loadMathCourses()
        self.loadExtraStudents()
        self.loadStudents()
        for school_name in self.schools:
            self.loadTeachers(school_name, False)
            self.loadTeachers(school_name, True)
            self.loadSections(school_name)
            self.loadEnrollments(school_name)

    def excludeFromEnrollment(self, school_course_id):
        for ex in DO_NOT_ENROLL:
            if ex == school_course_id:
                return True
            if ex[-2:1] == '.*':
                school_id, course_id = school_course_id.split('.')
                test_school = ex[0:-2]
                if school_id == test_school:
                    return True
        return False    

    def getTeacherName(self, teacher_id):
        teacher_data = self.teachers.get(teacher_id)
        if teacher_data:
            return teacher_data['Last_Name']
        return '?'

    def loadMathCourses(self):
        with open(os.path.join(self.source_dir, 'math-courses.txt')) as f:
            fieldnames = None if not self.autosend else MATH_COURSE_HEADERS
            courses = csv.DictReader(f, fieldnames=fieldnames,
                dialect='excel-tab', lineterminator=LINETERM_IN)
            for row in courses:
                school_id = row['SchoolID']
                course_number = row['Course_Number']
                course_id = '.'.join((school_id, course_number))
                self.included_courses.append(course_id)
                school_name = row['School_Name']
                if school_name not in self.schools:
                    self.schools.append(school_name)

    # This is for teachers posing as students
    def loadExtraStudents(self):
        with open(os.path.join(self.source_dir, 'extra-students.txt')) as f:
            fieldnames = None if not self.autosend else TEST_STUDENT_HEADERS
            students = csv.DictReader(f, fieldnames=fieldnames,
                dialect='excel-tab', lineterminator=LINETERM_IN)
            for row in students:
                student_id = 'S' + row['Student_Number']
                school_id = row['SchoolID']
                row.update({'Enrolled': '1'})
                self.students[student_id] = row
                
                # Add extra enrollments
                sections = row['Sections'].split(',')
                for section in sections:
                    school_section_id = '.'.join((school_id, section))
                    if school_section_id not in self.extras:
                        self.extras[school_section_id] = [ ]
                    self.extras[school_section_id].append(student_id)

    def loadStudents(self):
        with open(os.path.join(self.source_dir, 'students.txt')) as f:
            fieldnames = None if not self.autosend else STUDENT_HEADERS
            students = csv.DictReader(f, fieldnames=fieldnames, 
                dialect='excel-tab', lineterminator=LINETERM_IN)
            for row in students:
                student_id = 'S' + row['Student_Number']
                row.update({'Enrolled': '0'})
                self.students[student_id] = row

    # Create an assignments-kent.txt file that has the assigned teachers (and aides)
    # Same format as teachers-kent.txt            
    def loadTeachers(self, school_name, assignments):
        file_name = 'teachers-%s.txt' % school_name
        if assignments:
            file_name = 'assignments-%s.txt' % school_name
        with open(os.path.join(self.source_dir, file_name)) as f:
            fieldnames = None if not self.autosend else TEACHER_HEADERS
            teachers = csv.DictReader(f, fieldnames=fieldnames,
                dialect='excel-tab', lineterminator=LINETERM_IN)
            for row in teachers:
                teacher_number = row['TeacherNumber']
                teacher_id = 'T' + teacher_number
                if assignments:
                  row.update({'Assigned': '2'})
                else:
                  row.update({'Assigned': '0'})
                self.teachers[teacher_id] = row

    def loadSections(self, school_name):
        with open(os.path.join(self.source_dir, 'courses-%s.txt' % school_name)) as f:
            fieldnames = None if not self.autosend else COURSE_HEADERS
            courses = csv.DictReader(f, fieldnames=fieldnames, 
                dialect='excel-tab', lineterminator=LINETERM_IN)
            for row in courses:
                school_id = row['SchoolID']
                course_number = row['Course_Number']
                course_id = '.'.join((school_id, course_number))
                if course_id in self.included_courses:
                    self.courses[course_id] = row

        with open(os.path.join(self.source_dir, 'sections-%s.txt' % school_name)) as f:
            fieldnames = None if not self.autosend else SECTION_HEADERS
            sections = csv.DictReader(f, fieldnames=fieldnames,
                dialect='excel-tab', lineterminator=LINETERM_IN)
            for row in sections:
                school_id = row['SchoolID']
                course_number = row['Course_Number']
                section_number = row['Section_Number']
                teacher_id = 'T' + row['[05]TeacherNumber']
                course_id = '.'.join((school_id, course_number))
                if course_id in self.included_courses:
                    if teacher_id in self.teachers:
                        if self.teachers[teacher_id]['Status'] == '1':
                            if self.teachers[teacher_id]['Assigned'] == '0':
                                self.teachers[teacher_id]['Assigned'] = '1'
                            school_section_id = '.'.join((school_id, course_number, section_number))
                            self.sections[school_section_id] = row
                        else:
                            print "section %s.%s (%s): teacher %s is not active" % (course_number, section_number, school_id, teacher_id)
                    else:
                        print "section %s.%s (%s): missing teacher %s" % (course_number, section_number, school_id, teacher_id)

    def loadEnrollments(self, school_name):
        with open(os.path.join(self.source_dir, 'rosters-%s.txt' % school_name)) as f:
            fieldnames = None if not self.autosend else CC_HEADERS
            cc = csv.DictReader(f, fieldnames=fieldnames,
                dialect='excel-tab', lineterminator=LINETERM_IN)
            for row in cc:
                start_date = parseDate(row['DateEnrolled']) - datetime.timedelta(days=DAYS_UPCOMING)
                end_date   = parseDate(row['DateLeft']) + datetime.timedelta(days=DAYS_PAST)
                if self.effective_date >= start_date and self.effective_date <= end_date:
                    school_id = row['SchoolID']
                    course_number = row['Course_Number']
                    section_number = row['Section_Number']
                    course_id = '.'.join((school_id, course_number))
                    if course_id in self.included_courses:
                        student_id = 'S' + row['[01]Student_Number']
                        teacher_id = 'T' + row['[05]TeacherNumber']
                        enrollment_id = '.'.join((school_id, course_number, section_number, student_id))
                        self.enrollments[enrollment_id] = row
                        self.students[student_id]['Enrolled'] = '1'

    def dumpActiveEnrollments(self):
        f = sys.stdout
        w = csv.writer(f, dialect='excel-tab')
        w.writerow(['course_name', 'course_number', 'section_number', 'teacher_id', 'teacher_name', 'code', 'student_id'])
        for enrollment_id, enrollment_data in self.enrollments.iteritems():
            school_id, course_id, student_id, course_number, section_number, teacher_id = enrollment_id.split('.')
            course_name = self.courses[course_number]['Course_Name']
            teacher_name = self.teachers[teacher_id]['Last_Name']
            section_id = '.'.join((school_id, course_number, section_number))
            section_data = self.sections[section_id]
            term = section_data['[13]Abbreviation']
            w.writerow([course_name, course_number, section_number, teacher_id, teacher_name, course_id, student_id])        

    def writeDistrictFile(self):
        with open(os.path.join(self.output_dir, 'CODE_DISTRICT.txt'), 'w') as f:
            w = csv.writer(f, dialect='excel', quoting=csv.QUOTE_ALL)
            w.writerow(['district_code', 'district_name', 
                'address_1', 'address_2', 'city', 'state', 'zip', 'phone', 'current_school_year'])
            w.writerow(['2165334', 'Kentfield Elementary School District', 
                '750 College Ave', '', 'Kentfield', 'CA', '94904', '415-458-5130', self.current_year])

    def writeSchoolsFile(self):
        with open(os.path.join(self.output_dir, 'SCHOOL.txt'), 'w') as f:
            w = csv.writer(f, dialect='excel', quoting=csv.QUOTE_ALL)
            w.writerow(['school_code', 'school_name', 'district_code', 'grade_start', 'grade_end',
                'address_1', 'address_2', 'city', 'state', 'zip', 'phone'])
            w.writerow([104, 'Adaline E. Kent Middle School', '2165334', '5', '8',
                '800 College Ave', '', 'Kentfield', 'CA', '94904', '415-458-5970'])

    def writeSectionsFile(self):
        course_year = str(self.current_year + 1)
        with open(os.path.join(self.output_dir, 'PIF_SECTION.txt'), 'w')  as f:
            w = csv.writer(f, dialect='excel', quoting=csv.QUOTE_ALL)
            w.writerow(['native_section_code', 'school_code', # 'section_type', 'section_type_description',
                'date_start', 'date_end', 'school_year', 'course_number', 
                'course_name','section_name', 'section_number'])
            for school_section_id in self.sections:
                row = self.sections[school_section_id]
                school_id = row['SchoolID']
                course_number = row['Course_Number']
                section_number = row['Section_Number']
                course_id = '.'.join((school_id, course_number))
                if course_id in self.courses:
                    native_section_code = '.'.join((course_number, section_number))
                    course_name = self.courses[course_id]['Course_Name']
                    period = re.sub(r'^(\d+)(.+)$', r'P\1', row['Expression'])
                    date_start = formatDate(row['[13]FirstDay'])
                    date_end = formatDate(row['[13]LastDay'])

                    # TODO: Check Onboarding Guide about maximum length of the section name 
                    section_name = course_name + ' - ' + self.getTeacherName('T' + row['[05]TeacherNumber']) + ' ' + period + ' ' + course_year
                    w.writerow([native_section_code, school_id,
                        date_start, date_end,
                        self.current_year, course_number,
                        course_name, section_name, section_number])

    def writeStaffFile(self):
        with open(os.path.join(self.output_dir, 'STAFF.txt'), 'w') as f:
            w = csv.writer(f, dialect='excel', quoting=csv.QUOTE_ALL)
            w.writerow(['staff_code', 'last_name', 'first_name', 'email', 'staff_number', 'federated_id'])
            for teacher_id, teacher_data in self.teachers.iteritems():
                if teacher_data['Assigned'] != '0':
                    school_id = teacher_data['SchoolID']
                    teacher_number = teacher_data['TeacherNumber']
                    last_name = teacher_data['Last_Name']
                    first_name = teacher_data['First_Name']
                    email = teacher_data['Email_Addr']
                    w.writerow([teacher_number, last_name, first_name, email, teacher_number, email])

    def writeStudentFile(self):
        with open(os.path.join(self.output_dir, 'STUDENT.txt'), 'w') as f:
            w = csv.writer(f, dialect='excel', quoting=csv.QUOTE_ALL)
            w.writerow(['student_code', 'last_name', 'first_name', 'gender_code', 
                'email', 'student_number', 'federated_id'])
            for student_id, student_data in self.students.iteritems():
                if student_data['Enrolled'] == '1':
                    school_id = student_data['SchoolID']
                    last_name = student_data['Last_Name']
                    first_name = student_data['First_Name']
                    student_number = student_data['Student_Number']
                    gender = student_data['Gender']
                    email = student_data['Network_ID'] + '@kentfieldschools.org'
                    w.writerow([student_number, last_name, first_name, gender, 
                        email, student_number, email])

    def writeSectionStaffFile(self):
        with open(os.path.join(self.output_dir, 'PIF_SECTION_STAFF.txt'), 'w')  as f:
            w = csv.writer(f, dialect='excel', quoting=csv.QUOTE_ALL)
            w.writerow(['section_teacher_code', 'staff_code', 'native_section_code', 
                'date_start', 'date_end', 'school_year', 'teacher_of_record'])
            for school_section_id in self.sections:
                row = self.sections[school_section_id]
                school_id = row['SchoolID']
                course_number = row['Course_Number']
                section_number = row['Section_Number']
                course_id = '.'.join((school_id, course_number))
                if course_id in self.courses:
                    teacher_number = row['[05]TeacherNumber']
                    section_teacher_code = '.'.join((course_number, section_number, teacher_number))
                    native_section_code = '.'.join((course_number, section_number))

                    # Use real teacher assingment dates if possible
                    w.writerow([section_teacher_code, teacher_number, native_section_code,
                        formatDate(row['[13]FirstDay']), formatDate(row['[13]LastDay']), 
                        self.current_year, 'true'])

    def writeSectionStudentFile(self):
        with open(os.path.join(self.output_dir, 'PIF_SECTION_STUDENT.txt'), 'w')  as f:
            w = csv.writer(f, dialect='excel', quoting=csv.QUOTE_ALL)
            w.writerow(['section_student_code', 'student_code', 'native_section_code', 
                'date_start', 'date_end', 'school_year'])
            for enrollment_id, enrollment_data in self.enrollments.iteritems():
                school_id, course_number, section_number, student_id = enrollment_id.split('.')
                student_number = self.students[student_id]['Student_Number']
                section_student_code = '.'.join((course_number, section_number, student_number))
                native_section_code = '.'.join((course_number, section_number))
                date_start = formatDate(enrollment_data['DateEnrolled'])
                date_end = formatDate(enrollment_data['DateLeft'])
                w.writerow([section_student_code, student_number, native_section_code,
                    date_start, date_end, self.current_year])
            
            # Now handle special "extras" - teachers posing as students, etc.
            for school_section_id in self.extras:
                school_id, course_number, section_number = school_section_id.split('.')
                extras = self.extras[school_section_id]
                for student_id in extras:
                    student_number = self.students[student_id]['Student_Number']
                    section_student_code = '.'.join((course_number, section_number, student_number))
                    native_section_code = '.'.join((course_number, section_number))
                    date_start = formatDate(self.sections[school_section_id]['[13]FirstDay'])
                    date_end = formatDate(self.sections[school_section_id]['[13]LastDay'])
                    w.writerow([section_student_code, student_number, native_section_code,
                        date_start, date_end, self.current_year])

    def writeAssignmentFile(self):
        with open(os.path.join(self.output_dir, 'ASSIGNMENT.txt'), 'w')  as f:
            w = csv.writer(f, dialect='excel', quoting=csv.QUOTE_ALL)
            w.writerow(['native_assignment_code', 'staff_code', 'school_year', 'institution_code',
                'date_start', 'date_end', 'position_code'])
            school_id = '104'
            for teacher_id, teacher_data in self.teachers.iteritems():
                if teacher_data['Assigned'] == '2':
                    teacher_number = teacher_data['TeacherNumber']
                    native_assignment_code = '.'.join((school_id, teacher_number))
                    w.writerow([native_assignment_code, teacher_number, self.current_year, school_id, 
                        self.year_start, self.year_end, 'Teacher'])

    def zipAllFiles(self):
        with zipfile.ZipFile(os.path.join(self.output_dir, 'KENTFIELD.zip'), 'w') as myzip:
            for name in ['CODE_DISTRICT', 'SCHOOL', 'STAFF', 'STUDENT', 'PIF_SECTION', 'PIF_SECTION_STAFF', 'PIF_SECTION_STUDENT', 'ASSIGNMENT']:
                arcname = name + '.txt'
                myzip.write(os.path.join(self.output_dir, arcname), arcname)
                
    def uploadZipFile(self, host, folder, username, password):
        try:
            # cnopts = pysftp.CnOpts(knownhosts='./known_hosts.txt')
            # cnopts.hostkeys = None
            sftp = pysftp.Connection(host, username=username, password=password)
        except Exception as e:
            print "Can't connect SFTP: %s" % e
            return
        try:
            with sftp.cd(folder):
              localpath = os.path.join(self.output_dir, 'KENTFIELD.zip')
              sftp.put(localpath)
              print "zip file uploaded"
        except Exception as e:
            print "Can't put SFTP: %s" % e
        finally:
            sftp.close()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Process files for Pearson EasyBridge.')
    parser.add_argument('-a', '--autosend', action='store_true',
        help='use autosend files (no header line)')
    parser.add_argument('-t', '--effective-date')
    parser.add_argument('-n', '--dry-run', action='store_true')
    parser.add_argument('-s', '--source_dir', help='source directory')
    parser.add_argument('-o', '--output_dir', help='output directory')
    parser.add_argument('-u', '--username')
    parser.add_argument('-p', '--password')
    parser.add_argument('-d', '--dump', action='store_true', 
        help='dump courses and sections')
    args = parser.parse_args()

    eff_date = None
    if args.effective_date:
      eff_date = parseDate(args.effective_date)
    
    uploader = EasyBridgeUploader(source_dir=args.source_dir, output_dir=args.output_dir, autosend=args.autosend, effective_date=eff_date)
    uploader.loadData()
    if args.dump:
        uploader.dumpAllCourses()
        uploader.dumpActiveEnrollments()
    else:
        uploader.writeDistrictFile()
        uploader.writeSchoolsFile()
        uploader.writeSectionsFile()
        uploader.writeStaffFile()
        uploader.writeStudentFile()
        uploader.writeSectionStaffFile()
        uploader.writeSectionStudentFile()
        uploader.writeAssignmentFile()
        uploader.zipAllFiles()
        if args.dry_run:
            print "dry run, zip file created but not uploaded"
        else:
            uploader.uploadZipFile('sftp.pifdata.net', 'SIS', args.username, args.password)
