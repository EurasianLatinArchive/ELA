# dbload.py
# refresh tools_ela.db using data stored in ./DATA
# NOTE: to be updated

import os
import sys
import time
import csv
import sqlite3 as db
import pgeocode

# partialize open function to expressedly use UTF-8
from functools import partial
open_utf8 = partial(open, encoding='UTF-8')


# simple progress bar
from jnbkutility import log_progress


# Notes on tabular files:
# 1. Pleiades CSV can be downloaded here: https://pleiades.stoa.org/downloads
# 2. Geonames is different, as it is an Oracle generated tab-delimited file
#    which can be found at: https://download.geonames.org/export/dump/ (namely
#    the allCountries.zip file)
# From Geonames README:
#
# The main 'geoname' table has the following fields :
# ---------------------------------------------------
# geonameid         : integer id of record in geonames database
# name              : name of geographical point (utf8) varchar(200)
# asciiname         : name of geographical point in plain ascii characters, varchar(200)
# alternatenames    : alternatenames, comma separated, ascii names automatically transliterated, convenience attribute from alternatename table, varchar(10000)
# latitude          : latitude in decimal degrees (wgs84)
# longitude         : longitude in decimal degrees (wgs84)
# feature class     : see http://www.geonames.org/export/codes.html, char(1)
# feature code      : see http://www.geonames.org/export/codes.html, varchar(10)
# country code      : ISO-3166 2-letter country code, 2 characters
# cc2               : alternate country codes, comma separated, ISO-3166 2-letter country code, 200 characters
# admin1 code       : fipscode (subject to change to iso code), see exceptions below, see file admin1Codes.txt for display names of this code; varchar(20)
# admin2 code       : code for the second administrative division, a county in the US, see file admin2Codes.txt; varchar(80)
# admin3 code       : code for third level administrative division, varchar(20)
# admin4 code       : code for fourth level administrative division, varchar(20)
# population        : bigint (8 byte int)
# elevation         : in meters, integer
# dem               : digital elevation model, srtm3 or gtopo30, average elevation of 3''x3'' (ca 90mx90m) or 30''x30'' (ca 900mx900m) area in meters, integer. srtm processed by cgiar/ciat.
# timezone          : the iana timezone id (see file timeZone.txt) varchar(40)
# modification date : date of last modification in yyyy-MM-dd format
#
# Thus extraction is performed using numerical indexes, as:
# 0: geonameid -> id
# 1: name -> title
# 4: latitude -> lat
# 5: longitude -> lon


DATA_DIR = os.path.join('.', 'SOURCE', 'external')
DATABASE = os.path.join('.', 'tools_ela.db')

def _count_lines(fname):
    i = 0
    with open(fname) as f:
        for line in f:
            i += 1
    return i

COMMIT_EVERY = 5000


def JUP_loadPleiades(csv_name, verbose=True):
    conn = db.connect(DATABASE)
    SQL = """
        drop table if exists PLEIADES_PLACES
        """
    conn.execute(SQL)
    SQL = """
        create table PLEIADES_PLACES
        (id integer, title text, lat real, lon real)
        """
    conn.execute(SQL)
    line_counter = 0
    if verbose:
        num_lines = _count_lines(csv_name)
        print("reading file: '%s' (%s entries)" % (csv_name, num_lines))
        start = time.time()
    with open_utf8(csv_name) as csvfile:
        reader = csv.DictReader(csvfile)
        if verbose:
            reader = log_progress(reader, size=num_lines, name="Entries")
        for row in reader:
            line_counter += 1
            sql = "insert into PLEIADES_PLACES values (?, ?, ?, ?)"
            conn.execute(sql, (row['id'], row['title'],
                               row['reprLat'], row['reprLong']))
            if not line_counter % COMMIT_EVERY:
                conn.commit()
        conn.commit()
    if verbose:
        print("\nDone in %s sec." % (time.time() - start))


def JUP_loadGeonames(csv_name, verbose=True):
    conn = db.connect(DATABASE)
    SQL = """
        drop table if exists GEONAMES_PLACES
        """
    conn.execute(SQL)
    SQL = """
        create table GEONAMES_PLACES
        (id integer, title text, lat real, lon real)
        """
    conn.execute(SQL)
    line_counter = 0
    if verbose:
        num_lines = _count_lines(csv_name)
        print("reading file: '%s' (%s lines)" % (csv_name, num_lines))
        start = time.time()
    with open_utf8(csv_name) as csvfile:
        reader = csv.reader(csvfile, delimiter='\t')
        if verbose:
            reader = log_progress(reader, size=num_lines, name="Entries")
        for row in reader:
            line_counter += 1
            sql = "insert into GEONAMES_PLACES values (?, ?, ?, ?)"
            conn.execute(sql, (row[0], row[1], row[4], row[5]))
            if not line_counter % COMMIT_EVERY:
                conn.commit()
        conn.commit()
    if verbose:
        print("\nDone in %s sec." % (time.time() - start))


if __name__ == '__main__':
    pass


# end.
