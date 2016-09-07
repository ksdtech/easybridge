# easybridge

Upload nightly files to Pearson EasyBridge Auto/Plus.

Uses PowerSchool AutoSend files.  

There are now three additional files you must put in the "source" folder:

math-courses.txt - Records in this file indicate which of the exported PowerSchool 
courses are to be included in the Pearson setup (and also the "school" names used as 
suffixes for the AutosSend "teachers", "courses", "sections", and "rosters" files.

extra-students.txt - Records in this file are for "special" students that are not
in PowerSchool. The "Sections" column in the record is a comma-delimited list of
"course\_number"."section\_number" entries for the given school that the student
will be enrolled in.

assignment-"school".txt - Records in this file contain only those lines from the 
teachers file for Easybridge "assigned" users (who can see all classes).


