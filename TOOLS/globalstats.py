# globalstats.py
#
# retrieve values from result files and perform global statistics:
#
# + Numero tot. parole
# + Numero tot. parole latine [per testi multilingua]
# + Numero tot. lemmi
# + Numero tot. latin types
# + Min/max/average lenghts of Latin types
# + Type token ratio
# + Lista di parole e frequenza
# + Lista di parole latine e frequenza
# + Lista stop words e frequenza
# + Lista lemmi, frequenza, varianti
# * Lista e frequenza di persone individuate
# * Lista e frequenza di luoghi individuati
#
# Results will be placed in a single HTML file with no formatting, to be
# enriched by an appropriate CSS file.


import os
import sys
import time
import json
import math
import re
import csv


# network analysis
import networkx as nx


#############################################################################
# text templates

TEXT_TEMPLATE = """\
Statistiche Complessive
=======================

Numero Totale di Parole: {num_words}
Numero Totale di Parole Latine: {num_lat_words}
Numero Totale di Type Latini: {num_lat_types}
Numero Totale di Lemmi Latini: {num_lat_lemmas}
Type / Token Ratio: {lat_ttr}

Minima Lunghezza Type: {min_len_types}
Massima Lunghezza Type: {max_len_types}
Media Lunghezza Type: {average_len_types}

Frequenze Parole Latine:
------------------------
{lat_freqs_lines}

Frequenze Lemmi Latini e Occorrenze:
------------------------------------
{lat_lemmafreqsoccurrences_lines}

Frequenze Parole Latine non-Stopword:
-------------------------------------
{lat_nostopfreqs_lines}

Frequenze Stopword Latine:
--------------------------
{lat_stopfreqs_lines}

Frequenze Persone:
------------------
{personfreqs_lines}

Frequenze Luoghi:
-----------------
{placefreqs_lines}

"""



# partialize open function to expressedly use UTF-8
from functools import partial
open_utf8 = partial(open, encoding='UTF-8')


#############################################################################

FOCUS_EXTENSION = "_fulltext_statistics.json"   # use this to focus on file

def retrieve_data(fromdir):
    def _retrieve_data_fromfile(fromdir, basename):
        with open_utf8(os.path.join(fromdir, basename + "_statistics.json")) as f:
            data_latstats = json.load(f)
        with open_utf8(os.path.join(fromdir,
                       basename + "_fulltext_statistics.json")) as f:
            data_ftstats = json.load(f)
        with open_utf8(os.path.join(fromdir,
                       basename + "_tei_lists.json")) as f:
            data_teilists = json.load(f)
        with open_utf8(os.path.join(fromdir,
                       basename + "_tei_attrs.json")) as f:
            data_teiattrs = json.load(f)
        res = {
            'text': data_ftstats['text'],
            'lat_words': data_latstats['word_list_lowercase'],
            'ft_words': data_ftstats['word_list_lowercase'],
            'lat_types': data_latstats['type_list'],
            'ft_freqs': data_ftstats['word_frequencies'],
            'lat_freqs': data_latstats['word_frequencies'],
            'lat_nostopfreqs': data_latstats['word_frequencies_nostops'],
            'lat_stopfreqs': data_latstats['stop_frequencies'],
            'lat_lemmafreqs': data_latstats['lemma_frequencies'],
            'lat_lemmas': data_latstats['word_lemma_list'],
            'place_freqs': data_teilists['xmltei_places']['frequencies'],
            'person_freqs': data_teilists['xmltei_persons']['frequencies'],
        }
        return res
    basefiles = os.listdir(fromdir)
    res = {}
    for x in basefiles:
        if x.endswith(FOCUS_EXTENSION):
            basename = x[:-len(FOCUS_EXTENSION)]
            res[basename] = _retrieve_data_fromfile(fromdir, basename)
    return res


def retrieve_teidata_fromfile(fromdir, basename):
    with open_utf8(os.path.join(fromdir,
                   basename + "_tei_lists.json")) as f:
        data_teilists = json.load(f)
    with open_utf8(os.path.join(fromdir,
                   basename + "_tei_attrs.json")) as f:
        data_teiattrs = json.load(f)
    return (data_teiattrs, data_teilists)

def retrieve_teidata(fromdir):
    basefiles = os.listdir(fromdir)
    res = {}
    for x in basefiles:
        if x.endswith(FOCUS_EXTENSION):
            basename = x[:-len(FOCUS_EXTENSION)]
            res[basename] = retrieve_teidata_fromfile(fromdir, basename)
    return res


# write text files retrieved from the stats records
def do_writetexts(data, destdir):
    for x in data:
        with open_utf8(os.path.join(destdir, "%s.txt" % x), 'w') as f:
            f.write(data[x]['text'])


# given a dict made out of the above records, perform data extraction
def do_stats(data):
    def _l_strip(l, filterempty=True):
        if filterempty:
            return list(x.strip() for x in l if x.strip())
        else:
            return list(x.strip() for x in l)
    def _d_strip(d, filterempty=True):
        if filterempty:
            return dict({k.strip():e for (k, e) in d.items() if k.strip()})
        else:
            return dict({k.strip():e for (k, e) in d.items()})
    all_words = []
    all_lat_words = []
    all_lat_types = set()
    all_lat_lemmas = {}
    all_freqs = {}
    all_lat_freqs = {}
    all_lat_lemmafreqs ={}
    all_lat_stopfreqs ={}
    all_lat_nostopfreqs ={}
    all_lat_lemmas_occurrences = {}
    all_place_freqs = {}
    all_person_freqs = {}
    for x in data:
        rec = data[x]
        all_words += _l_strip(rec['ft_words'])
        all_lat_words += _l_strip(rec['lat_words'])
        all_lat_types = all_lat_types.union(_l_strip(rec['lat_types']))
        for k in rec['ft_freqs']:
            ks = k.strip()
            if ks in all_freqs:
                all_freqs[ks] += rec['ft_freqs'][k]
            else:
                all_freqs[ks] = rec['ft_freqs'][k]
        for k in rec['lat_freqs']:
            ks = k.strip()
            if ks in all_lat_freqs:
                all_lat_freqs[ks] += rec['lat_freqs'][k]
            else:
                all_lat_freqs[ks] = rec['lat_freqs'][k]
        for k in rec['lat_lemmafreqs']:
            ks = k.strip()
            if ks in all_lat_lemmafreqs:
                all_lat_lemmafreqs[ks] += rec['lat_lemmafreqs'][k]
            else:
                all_lat_lemmafreqs[ks] = rec['lat_lemmafreqs'][k]
        for k in rec['lat_nostopfreqs']:
            ks = k.strip()
            if ks in all_lat_nostopfreqs:
                all_lat_nostopfreqs[ks] += rec['lat_nostopfreqs'][k]
            else:
                all_lat_nostopfreqs[ks] = rec['lat_nostopfreqs'][k]
        for k in rec['lat_stopfreqs']:
            ks = k.strip()
            if ks in all_lat_stopfreqs:
                all_lat_stopfreqs[ks] += rec['lat_stopfreqs'][k]
            else:
                all_lat_stopfreqs[ks] = rec['lat_stopfreqs'][k]
        for k in rec['place_freqs']:
            ks = k.strip()
            if ks in all_place_freqs:
                all_place_freqs[ks] += rec['place_freqs'][k]
            else:
                all_place_freqs[ks] = rec['place_freqs'][k]
        for k in rec['person_freqs']:
            ks = k.strip()
            if ks in all_place_freqs:
                all_person_freqs[ks] += rec['person_freqs'][k]
            else:
                all_person_freqs[ks] = rec['person_freqs'][k]
        for e in rec['lat_lemmas']:
            word, lemma = e
            if lemma in all_lat_lemmas_occurrences:
                all_lat_lemmas_occurrences[lemma].add(word.lower())
            else:
                all_lat_lemmas_occurrences[lemma] = set([word.lower()])
    all_lat_types = list(all_lat_types)
    num_words = len(all_words)
    num_lat_words = len(all_lat_words)
    num_lat_types = len(all_lat_types)
    num_lat_lemmas = len(all_lat_lemmafreqs)
    num_persons = len(all_person_freqs)
    num_places = len(all_place_freqs)
    lat_ttr = num_lat_types / num_lat_words
    min_len_types = None
    max_len_types = 0
    ltsum = 0
    for x in all_lat_types:
        l = len(x)
        if min_len_types is None or l < min_len_types:
            min_len_types = l
        if l > max_len_types:
            max_len_types = l
        ltsum += l
    average_len_types = ltsum / num_lat_types
    res = {
        'words': all_words,
        'lat_words': all_lat_words,
        'lat_types': all_lat_types,
        'num_words': num_words,
        'num_lat_words': num_lat_words,
        'num_lat_types': num_lat_types,
        'num_lat_lemmas': num_lat_lemmas,
        'num_persons': num_persons,
        'num_places': num_places,
        'lat_ttr': lat_ttr,
        'min_len_types': min_len_types,
        'max_len_types': max_len_types,
        'average_len_types': average_len_types,
        'lat_lemmas': all_lat_lemmas,
        'freqs': all_freqs,
        'lat_freqs': all_lat_freqs,
        'lat_lemmafreqs': all_lat_lemmafreqs,
        'lat_nostopfreqs': all_lat_nostopfreqs,
        'lat_stopfreqs': all_lat_stopfreqs,
        'personfreqs': all_person_freqs,
        'placefreqs': all_place_freqs,
        'lat_lemmas_occurrences': all_lat_lemmas_occurrences,
        'freqs_lines': '\n'.join(
            ["%s: %s" % (x, all_freqs[x])
             for x in sorted(list(all_freqs.keys()))]),
        'lat_freqs_lines': '\n'.join(
            ["%s: %s" % (x, all_lat_freqs[x])
             for x in sorted(list(all_lat_freqs.keys()))]),
        'lat_lemmafreqsoccurrences_lines': '\n'.join(
            ["%s: %s; %s" % (x, all_lat_lemmafreqs[x],
                             ' '.join(sorted(all_lat_lemmas_occurrences[x])))
             for x in sorted(list(all_lat_lemmafreqs.keys()))]),
        'lat_nostopfreqs_lines': '\n'.join(
            ["%s: %s" % (x, all_lat_nostopfreqs[x])
             for x in sorted(list(all_lat_nostopfreqs.keys()))]),
        'lat_stopfreqs_lines': '\n'.join(
            ["%s: %s" % (x, all_lat_stopfreqs[x])
             for x in sorted(list(all_lat_stopfreqs.keys()))]),
        'personfreqs_lines': '\n'.join(
            ["%s: %s" % (x, all_person_freqs[x])
             for x in sorted(list(all_person_freqs.keys()))]),
        'placefreqs_lines': '\n'.join(
            ["%s: %s" % (x, all_place_freqs[x])
             for x in sorted(list(all_place_freqs.keys()))]),
    }
    return res


#############################################################################

# classes to handle TEI data and perform aggregations; the first is a class
# that encompasses all data from a single document, and the second provides
# a way to handle a list of such structured data by allowing filtering and
# subset extraction; built on results of the retrieve_data* utilities

class TEIData(object):
    def __init__(self, data):
        self.__docbase = data[0]['file_basename']
        self.__teiattrs = data[0]
        self.__teilists = data[1]

    # get an attribute, given an attribute specification: the attribute
    # specification is a string of dot-separated JSON indexes that only
    # returns leaf attributes: if a path does not exist or is not a leaf
    # then an IndexError is raised; if an attribute exists but is empty
    # or a single dash, then None is returned
    def get_attribute(self, attrspec):
        attrpath = attrspec.split('.')
        base = self.__teiattrs
        try:
            for i in attrpath:
                base = base[i]
        except IndexError as e:
            raise IndexError(
                "index '%s' not found for entry '%s'" % (
                attrspec, self.__docbase))
        if type(base) not in [str, int, float]:
            raise IndexError(
                "incomplete index '%s' for entry '%s'" % (
                attrspec, self.__docbase))
        if not base or base == '-':
            return None
        else:
            return base

    def get_list(self, listspec):
        listpath = listspec.split('.')
        llp = len(listpath)
        if llp < 1 or llp > 3:
            raise IndexError(
                "incorrect index '%s' for entry '%s'" % (
                listspec, self.__docbase))
        try:
            # first case is xmltei_dates, second is everything else
            if llp == 1:
                base = self.__teilists[listpath[0]]
            else:
                base = self.__teilists[listpath[0]][listpath[1]]
        except (IndexError, KeyError) as e:
            raise IndexError(
                "index '%s' not found for entry '%s'" % (
                listspec, self.__docbase))
        # if we get a dict it is frequency entries, otherwise it is a list
        if type(base) == dict:
            if llp != 2:
                raise IndexError(
                    "incorrect index '%s' for entry '%s'" % (
                    listspec, self.__docbase))
            else:
                return base.copy()
        elif type(base) == list:
            if llp not in (2, 3):
                raise IndexError(
                    "incorrect index '%s' for entry '%s'" % (
                    listspec, self.__docbase))
            else:
                idx = listpath[llp - 1]
                for x in base:
                    if idx in x:
                        res = x[idx]
                        if type(res) not in [str, int, float]:
                            raise IndexError(
                                "invalid index/data '%s' for entry '%s'" % (
                                attrspec, self.__docbase))
                        else:
                            yield res
        else:
            raise IndexError(
                "incorrect index '%s' for entry '%s'" % (
                listspec, self.__docbase))

    def list_has(self, listspec, value):
        listpath = listspec.split('.')
        llp = len(listpath)
        if llp < 1 or llp > 3:
            raise IndexError(
                "incorrect index '%s' for entry '%s'" % (
                listspec, self.__docbase))
        try:
            # first case is xmltei_dates, second is everything else
            if llp == 1:
                base = self.__teilists[listpath[0]]
            else:
                base = self.__teilists[listpath[0]][listpath[1]]
        except (IndexError, KeyError) as e:
            raise IndexError(
                "index '%s' not found for entry '%s'" % (
                listspec, self.__docbase))
        # if we get a dict it is frequency entries, otherwise it is a list
        if type(base) == list:
            if llp not in (2, 3):
                raise IndexError(
                    "incorrect index '%s' for entry '%s'" % (
                    listspec, self.__docbase))
            else:
                idx = listpath[llp - 1]
                for x in base:
                    if idx in x and x[idx] == value:
                        return True
                return False
        else:
            raise IndexError(
                "incorrect index '%s' for entry '%s'" % (
                listspec, self.__docbase))

class TEIDataList(object):
    def __init__(self, docs):
        self.__docs = {}
        for x in docs:
            self.__docs[x] = TEIData(docs[x])
        self.__keys = list(self.__docs.keys())
        self.__keys.sort()

    def keys(self):
        return self.__keys.copy()

    def get_item(self, idx):
        if type(idx) == int:
            idx = self.__keys[idx]
        return self.__docs[idx]

    # iterators
    def filter_by_attribute(self, attrspec, value):
        for x in self.__docs:
            try:
                if self.__docs[x].get_attribute(attrspec) == value:
                    yield self.__docs[x]
            except IndexError:
                continue

    def filter_by_list_containing(self, listspec, value):
        for x in self.__docs:
            try:
                if self.__docs[x].list_has(listspec, value):
                    yield self.__docs[x]
            except IndexError:
                continue


#############################################################################

def JUP_getStats(fromdir):
    data = retrieve_data(fromdir)
    return do_stats(data)

def JUP_getRawTEIData(fromdir):
    return retrieve_teidata(fromdir)

def JUP_renderText(fromdir):
    data = retrieve_data(fromdir)
    gstats = do_stats(data)
    return TEXT_TEMPLATE.format_map(gstats)

def JUP_renderTextFiles(fromdir, destdir, statsfname, texts=True):
    data = retrieve_data(fromdir)
    gstats = do_stats(data)
    s = TEXT_TEMPLATE.format_map(gstats)
    with open_utf8(os.path.join(destdir, statsfname), 'w') as f:
        f.write(s)
    if texts:
        do_writetexts(data, destdir)


# end.
