#!/usr/bin/env python3
# Tools for ELA using CLTK/NLTK

# what it does:
# 1. Indexes of Words, Lemmas, Types, Words LC and J->I, also without stops
# 2. Frequencies of Lemmas, Types
# 3. Concordances
# 4. TTR
# 5. Collocations
# 6. N-grams
# 7. Min, Max and Mean lengths of Types
# 16. POS Tagging
#
# what it does not:
# 8. Frequencies by starting letter or suffix
# 9. Clusters
# 10. Number of Words per Sentence (maybe it already works)
# 11. Variance and StdDev / Zscore (define)
# 12. Burrow's Delta
# 13. Markov Chain Analysis
# 14. Sentiment Analysis
# 15. Topic Modeling
#
# Take into account this for points 11 and 12:
# https://programminghistorian.org/en/lessons/introduction-to-stylometry-with-python


import os
import sys
import shutil
import time
import re
import math
import copy
import json
import argparse
import configparser
import sqlite3 as db

from cltk.tokenize.line import LineTokenizer
from cltk.tokenize.word import WordTokenizer
from cltk.lemmatize.latin.backoff import BackoffLatinLemmatizer
from cltk.corpus.utils.formatter import phi5_plaintext_cleanup
from cltk.utils import philology
from cltk.tag.pos import POSTag
# from cltk.stop.latin import STOPS_LIST

import nltk
from nltk.util import ngrams as nltk_ngrams

# TEI handling
# from tei_reader import TeiReader
import xml.etree.ElementTree as xml_ET

# partialize open function to expressedly use UTF-8
from functools import partial
open_utf8 = partial(open, encoding='UTF-8')


# TEI default namespace
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"

# TEI attributes (listed)
TEI_ATTRS = [
    'author',
    'author-viaf',
    'title',
    'date',
    'form',
    'source',
    'genre',
    'place',
    'language',
    'oclc-reference',
    'sinica-2.0',
    'cct-database',
    'digitized',
    'availability',
    'publisher',
    'first-tei-pubdate',
    'changes',
    'editorialdecl',
    'projectdesc',
]


PLEIADES_URL_BASE = "https://pleiades.stoa.org/places/"
GEONAMES_URL_BASE = "https://www.geonames.org/"


# alternate list of stopwords:
# comment the above import line and uncomment this statement
STOPS_LIST = """
a ab ac ad adhic aliqui aliquis an ante apud at atque aut autem cum cur de
deinde dum e ego enim ergo es est et etiam etsi ex fio haec haud hic hoc
iam idem igitur ille in infra inter interim ipse is ita magis modo mox nam
ne nec necque neque nisi non nos o ob per possum post pro quae quam quare
qui quia quicumque quid quidem quilibet quis quisnam quisquam quisque
quisquis quo quod quoniam sed si sic siue sive sub sui sum super suus tam
tamen trans tu tum ubi uel uero unus ut vel vero
""".strip().split()


# configuration
config = configparser.ConfigParser()
config['Paths'] = {
    'base': '.',
    'cltk_base': '~/cltk_data',
    'origin_subdir': 'ELA_TXT',
    'result_subdir': 'ELA_RESULT',
    'logfile': 'error.log',
    'database': 'tools_ela.db',
}


# constants
TEMP_BASENAME = 'TEMP'


# configuration
cfg_paths = {}


# database
DB = None


# read configuration file and set global variables
def reconfigure(s=None):
    if s is not None:
        config.read_string(s)
    cfg_paths['CLTK'] = config['Paths']['cltk_base']
    cfg_paths['BASE'] = config['Paths']['base']
    cfg_paths['SRCORIGIN'] = os.path.join(cfg_paths['BASE'],
                                          config['Paths']['origin_subdir'])
    cfg_paths['RESDEST'] = os.path.join(cfg_paths['BASE'],
                                        config['Paths']['result_subdir'])
    cfg_paths['CLTKORIGIN'] = os.path.join(cfg_paths['CLTK'], 'user_data')
    cfg_paths['LOGFILE'] = config['Paths']['logfile']
    cfg_paths['DATABASE'] = config['Paths']['database']
    for key in cfg_paths:
        if cfg_paths[key].startswith('~'):
            cfg_paths[key] = os.path.expanduser(cfg_paths[key])
        cfg_paths[key] = os.path.normpath(cfg_paths[key])


# unclutter file name construction
def fname_origin(s, ext=".xml"):
    return os.path.join(cfg_paths['SRCORIGIN'], s + ext)


def fname_result(s, ext=".json"):
    return os.path.join(cfg_paths['RESDEST'], s + ext)


# list files in origin directory
def list_origin_files(ext=".xml"):
    filenames = list(
        map(lambda x: os.path.splitext(os.path.basename(x))[0],
            (x for x in os.listdir(cfg_paths['SRCORIGIN']) if x.endswith('.xml'))
        )
    )
    return filenames


# returns a row from a table, matching a query 'field=value' as a dictionary
def seek_db(table, query):
    if DB:
        sql = "select * from %s where %s" % (table, query)
        cur = DB.cursor()
        cur.execute(sql)
        try:
            row = cur.fetchone()
            res = {}
            for k in row.keys():
                res[k] = row[k]
            return res
        except Exception as e:
            return None
    else:
        return None


# retrieve latitude and longitude from DB
def db_geoCoords(s):
    try:
        if s.startswith(PLEIADES_URL_BASE):
            pid = int(s.replace(PLEIADES_URL_BASE, "").split('/', 1)[0])
            tab = "PLEIADES_PLACES"
        elif s.startswith(GEONAMES_URL_BASE):
            pid = int(s.replace(GEONAMES_URL_BASE, "").split('/', 1)[0])
            tab = "GEONAMES_PLACES"
        else:
            return None
    except Exception as e:
        return None
    try:
        row = seek_db(tab, "id=%s" % pid)
        if row:
            if row['lat'] and row['lon']:
                return (float(row['lat']), float(row['lon']))
            else:
                return None
        else:
            return None
    except Exception as e:
        return None

# a dedicated exception for TEI errors
class TEIStructureError(Exception):
    def __init__(self, s):
        txt = "Invalid XML-TEI: %s" % s
        Exception.__init__(self, txt)

# TEI parsing and traversing engine
class TeiParser_ELA(object):
    def __init__(self, text=None):
        self._xmlns = {
            'tei': TEI_NS,
            'xml': XML_NS,
            }
        if text:
            self._xmlroot = xml_ET.fromstring(text)
        else:
            self._xmlroot = None
        self._attributes = {}
        self._names = []
        self._dates = []
        self._text_body = []
        self._text_front = []
        self._text_head = []
        self._default_language = 'lat'

    # properties
    text_body = property(lambda s: s._text_body if s._xmlroot else None)
    text_front = property(lambda s: s._text_front if s._xmlroot else None)
    text_head = property(lambda s: s._text_head if s._xmlroot else None)
    names = property(lambda s: s._names if s._xmlroot else None)
    dates = property(lambda s: s._dates if s._xmlroot else None)
    attributes = property(lambda s: s._attributes if s._xmlroot else None)

    # debug the tree
    def dbg_getRoot(self):
        return self._xmlroot

    # internals
    def _find(self, tag, fromnode=None, mandatory=False):
        if not self._xmlroot:
            return []
        else:
            if not fromnode:
                node = self._xmlroot
            else:
                node = fromnode
            li = list(node.findall('tei:%s' % tag, self._xmlns))
            n = len(li)
            if n != 1:
                if not mandatory and n == 0:
                    return []
                raise TEIStructureError("%s '%s' sections found" % (n, tag))
            else:
                return li[0]

    def _finds(self, tag, fromnode=None):
        if not self._xmlroot:
            return []
        else:
            if not fromnode:
                node = self._xmlroot
            else:
                node = fromnode
            li = list(node.findall('tei:%s' % tag, self._xmlns))
            return li

    def _tag(self, s):
        if TEI_NS in s:
            return s.replace('{%s}' % TEI_NS, 'tei:')
        elif XML_NS in s:
            return s.replace('{%s}' % XML_NS, 'xml:')
        else:
            return s

    def _attr(self, node, attr):
        if attr in node.attrib:
            return node.attrib[attr]
        else:
            for x in self._xmlns:
                if attr.startswith("%s:" % x):
                    a = "{%s}" % self._xmlns[x] + attr.split(':')[1]
                    if a in node.attrib:
                        return node.attrib[a]
            return None

    def _flatten_text(self, n):
        return ("".join(n.itertext()))

    def _zero_dash(self, s):
        return "-" if not s else s

    def _suppress_pb_tags(self, s):
        return re.sub(r"\<pb[^>]*\/\>", "", s)

    # parse text, traditionally in a recursive fashion; returns nothing, but
    # results in alteration of the _text_* internal structures: the side
    # effect is that in the end the three parts will contain lists of pairs
    # structured as follows:
    #   ('ST', 'lng', "text as found in file, including punctuation")
    # where 'ST' is a special tag (see below) and 'lng' is the language code;
    # in the resulting text list not all special tags will be found, because
    # some of them are used by the parser to generate a consistent list, and
    # most of the remaining ones will actually indicate a paragraph change
    #
    # Notes:
    # 1. all text renditions/formats are stripped (bold, italic, etc)
    # 2. names, places, dates kept in text while added to appropriate lists
    # 3. if a portion of text is traversed by a text delimitation tag (such as
    #    div, p, foreign) that might hold a language connotation, the text is
    #    split in different parts: left, center, and right wrt the tag; this
    #    is usually important just for the foreign tag, however it may affect
    #    the other tags too
    # 4. opening div and p tags will imply a paragraph marker in the text
    # 5. pb tags will be just removed: when in the middle of a word the word
    #    itself will be merged; to achieve this the text following the pb
    #    tag is added using a special ltag that indicate
    # 6. the choice/abbr/expan structure converted to the expanded part
    #
    # Special Tags:
    # JL: join preceeding text
    # JR: join following text
    # PP: add paragraph marker

    # parse inner text
    #   textnode: a text node (initially one of the three top ones)
    #   tl: one of the three lists (_text_body, _text_front, _text_head)
    def _parse_inner(self, textnode, tl, current_language='*'):
        T = lambda s: self._tag(s)
        F = lambda node: self._flatten_text(node)
        A = lambda node, a: self._attr(node, a)
        PARA_TAGS = ['tei:div', 'tei:p', 'tei:lg', 'tei:lb', ]
        NAME_TAGS = ['tei:persName', 'tei:placeName', 'tei:geogName', ]

        for node in textnode:
            tag = T(node.tag)
            text = node.text
            tail = node.tail
            lang = A(node, 'xml:lang')
            if not lang:
                lang = current_language
            if tag in PARA_TAGS:
                if text:
                    tl.append(('PP:%s' % lang, text))
                self._parse_inner(node, tl, lang)
                if tail:
                    tl.append(('PP:%s' % current_language, tail))
            elif tag in NAME_TAGS:
                # NOTE: cannot go recursive
                key = A(node, 'key')
                ref = A(node, 'ref')
                typ = A(node, 'type')
                self._names.append((tag, key, ref, typ, text))
                if text:
                    tl.append(('*:*', text))
                if tail:
                    tl.append(('*:*', tail))
            elif tag == 'tei:date':
                when = A(node, 'when')
                if text:
                    self._dates.append((when, text))
                    tl.append(('*:*', text))
                if tail:
                    tl.append(('*:*', tail))
            # NOTE: pb tags are suppressed at feed time
            # elif tag == 'tei:pb':
            #     # NOTE: cannot go recursive
            #     if tail:
            #         tl.append(('JL:*', tail))
            elif tag == 'tei:foreign':
                if text:
                    tl.append(('*:%s' % lang, text))
                self._parse_inner(node, tl, lang)
                if tail:
                    tl.append(('*:%s' % current_language, tail))
            elif tag == 'tei:hi':
                if text:
                    tl.append(('*:*', text))
                    self._parse_inner(node, tl, lang)
                    if tail:
                        tl.append(('JL:*', tail))
                else:
                    self._parse_inner(node, tl, lang)
                    if tail:
                        tl.append(('*:*', tail))
            elif tag == 'tei:choice':
                # NOTE: cannot go recursive
                expan = self._find('expan', node)
                abbr = self._find('abbr', node)
                expan_text = expan.text
                abbr_text = abbr.text
                if expan_text:
                    tl.append(('*:*', expan_text))
                elif abbr_text:
                    tl.append(('*:*', abbr_text))
                elif text:
                    tl.append(('*:*', text))
                if tail:
                    tl.append(('*:*', tail))
            else:
                if text:
                    tl.append(('*:%s' % lang, text))
                self._parse_inner(node, tl, lang)
                if tail:
                    tl.append(('*:%s' % current_language, tail))

    def _parse_text(self, textnode, reinitialize=False):
        if reinitialize:
            self._text_body = []
            self._text_front = []
            self._text_head = []
            self._names = []
            self._dates = []

        default_language = self._default_language

        # some shorteners
        T = lambda s: self._tag(s)
        F = lambda node: self._flatten_text(node)

        # we receive a node, that at most contains three tag types: front,
        # head, body; other tags are in turn contained within; we handle
        # each part separately in order to fill related variables
        li = []
        current_language = default_language
        try:
            node = self._find('head', textnode)
            self._parse_inner(node, li, current_language)
            if li:
                t, lang = li[0][0].split(':')
                s = li[0][1]
                for x in li[1:]:
                    if x[0] == '*:*':
                        s += ' ' + x[1]
                    elif x[0] == 'JL:*':
                        s += x[1]
                    else:
                        s = ' '.join(s.split())
                        if s or t != 'PP':
                            self._text_head.append((t, lang, s))
                        t, lang = x[0].split(':')
                        s = ' '.join(x[1].split())
                s = ' '.join(s.split())
                if s or t != 'PP':
                    self._text_head.append((t, lang, s))
        except TEIStructureError as e:
            pass

        li = []
        current_language = default_language
        try:
            node = self._find('front', textnode)
            self._parse_inner(node, li, current_language)
            if li:
                t, lang = li[0][0].split(':')
                s = li[0][1]
                for x in li[1:]:
                    if x[0] == '*:*':
                        s += ' ' + x[1]
                    elif x[0] == 'JL:*':
                        s += x[1]
                    else:
                        s = ' '.join(s.split())
                        if s or t != 'PP':
                            self._text_front.append((t, lang, s))
                        t, lang = x[0].split(':')
                        s = ' '.join(x[1].split())
                s = ' '.join(s.split())
                if s or t != 'PP':
                    self._text_front.append((t, lang, s))
        except TEIStructureError as e:
            pass

        li = []
        current_language = default_language
        node = self._find('body', textnode)
        self._parse_inner(node, li, current_language)
        if li:
            t, lang = li[0][0].split(':')
            s = li[0][1]
            for x in li[1:]:
                if x[0] == '*:*':
                    s += ' ' + x[1]
                elif x[0] == 'JL:*':
                    s += x[1]
                else:
                    s = ' '.join(s.split())
                    if s or t != 'PP':
                        self._text_body.append((t, lang, s))
                    t, lang = x[0].split(':')
                    s = ' '.join(x[1].split())
            s = ' '.join(s.split())
            if s or t != 'PP':
                self._text_body.append((t, lang, s))

    def _parse(self):
        if not self._xmlroot:
            self._attributes = {}
            self._names = {}
            self._text_body = []
            self._text_front = []
            self._text_head = []
        else:
            # fill all useful attributes with a dash '-' as per specification
            for x in TEI_ATTRS:
                self._attributes[x] = '-'

            # split document in sections
            text = self._find('text')
            header = self._find('teiHeader')

            fileDesc = self._find('fileDesc', header)
            encodingDesc = self._find('encodingDesc', header)
            profileDesc = self._find('profileDesc', header)
            revisionDesc = self._find('revisionDesc', header)

            # some shorteners
            T = lambda s: self._tag(s)
            F = lambda node: self._zero_dash(self._flatten_text(node))

            # all of the following are ELA SPECIFIC
            if fileDesc:
                nodes = self._find('titleStmt', fileDesc)
                for node in nodes:
                    tag = T(node.tag)
                    if tag == 'tei:author':
                        self._attributes['author'] = node.text
                        if 'ref' in node.attrib:
                            self._attributes['author-viaf'] = node.attrib['ref']
                    elif tag == 'tei:title':
                        self._attributes['title'] = F(node)
                publicationStmt = self._find('publicationStmt', fileDesc)
                for node in publicationStmt:
                    tag = T(node.tag)
                    if tag == 'tei:publisher':
                        child = self._find('ref', node)
                        target = child.attrib['target'] if 'target' in child.attrib else '-'
                        self._attributes['publisher'] = {
                            'ref': target,
                            'value': F(child),
                        }
                    elif tag == 'tei:date':
                        # if 'when' in node.attrib:
                        #     date_iso = node.attrib['when']
                        # else:
                        #     date_iso = '-'
                        self._attributes['first-tei-pubdate'] = {
                            # 'iso': date_iso,
                            'value': F(node),
                        }
                    elif tag == 'tei:availability':
                        k = {}
                        license = self._find('licence', node)
                        k['value'] = F(license)
                        if 'target' in license.attrib:
                            k['target'] = license.attrib['target']
                        self._attributes['availability'] = k
                sourceDesc = self._find('sourceDesc', fileDesc)
                bibl = self._find('bibl', sourceDesc)
                # WARNING: ElementTree evaluates to False if no sub-elements found
                if bibl:
                    source = self._find('title', bibl)
                    # WARNING: see above, in this case no sub-elements is valid
                    if source is not None:
                        if 'ref' in source.attrib:
                            self._attributes['oclc-reference'] = source.attrib['ref']
                            self._attributes['source'] = F(source)
                    idno_nodes = self._finds('idno', bibl)
                    for ino in idno_nodes:
                        if 'type' in ino.attrib:
                            ino_type = ino.attrib['type'].lower()
                            if ino_type == 'sinica':
                                self._attributes['sinica-2.0'] = F(ino)
                            elif ino_type == 'cct':
                                self._attributes['cct-database'] = F(ino)
                            elif ino_type == 'dl':
                                self._attributes['digitized'] = F(ino)

            if profileDesc:
                nodes = self._find('langUsage', profileDesc)
                languages = []
                for node in nodes:
                    tag = T(node.tag)
                    if tag == 'tei:language':
                        languages.append({
                            # 'iso': node.attrib['ident'],
                            'value': F(node),
                        })
                self._attributes['language'] = languages
                nodes = self._find('creation', profileDesc)
                for node in nodes:
                    tag = T(node.tag)
                    if tag == 'tei:date':
                        # if 'when-iso' in node.attrib:
                        #     date_iso = node.attrib['when-iso']
                        # else:
                        #     date_iso = '-'
                        self._attributes['date'] = {
                            # 'iso': date_iso,
                            'value': F(node),
                        }
                places = []
                forms = []
                nodes = self._find('textClass', profileDesc)
                for node in nodes:
                    tag = T(node.tag)
                    if tag == 'tei:keywords':
                        for child in node:
                            ctag = T(child.tag)
                            if ctag == 'tei:term':
                                if 'type' in child.attrib:
                                    ctype = child.attrib['type']
                                    if ctype == 'form':
                                        forms.append(F(child))
                                    # elif ctype == 'source':
                                    #     self._attributes['source-bibl'] = F(child)
                                    elif ctype == 'genre':
                                        self._attributes['genre'] = F(child)
                                    elif ctype == 'place':
                                        places.append(F(child))
                if places:
                    self._attributes['place'] = places
                if forms:
                    self._attributes['form'] = forms

            if encodingDesc:
                projectDesc = self._find('projectDesc', encodingDesc)
                if projectDesc:
                    li = []
                    for node in projectDesc:
                        li.append(F(node))
                    s = '\n'.join(li).strip()
                    if s:
                        self._attributes['projectdesc'] = s
                editorialDecl = self._find('editorialDecl', encodingDesc)
                if editorialDecl:
                    li = []
                    for node in editorialDecl:
                        li.append(F(node))
                    s = '\n'.join(li).strip()
                    if s:
                        self._attributes['editorialdecl'] = s

            if revisionDesc:
                changes = self._finds('change', revisionDesc)
                clist = []
                for node in changes:
                    when = node.attrib['when'] if 'when' in node.attrib else '-'
                    who = node.attrib['who'] if 'who' in node.attrib else '-'
                    change = F(node)
                    clist.append({
                        'when': when,
                        'who': who,
                        'change': change,
                    })
                self._attributes['changes'] = clist

            # parse the text part
            self._parse_text(text)

    # interface
    def feed(self, text):
        cleantext = self._suppress_pb_tags(text)
        self._xmlroot = xml_ET.fromstring(cleantext)
        self._parse()

    def read(self, filename):
        with open_utf8(filename) as f:
            self.feed(f.read())
        self._parse()

    def json_places(self, place_coords=True):
        result = { 'list': [] }
        freqs = {}
        for x in self._names:
            v = None
            if x[0] == 'tei:placeName':
                v = {
                    'tag': 'placeName',
                    'value':  x[4],
                }
            elif x[0] == 'tei:geogName':
                v = {
                    'tag': 'geogName',
                    'value':  x[4],
                }
            if v:
                if x[1]:
                    v['key'] = x[1]
                    if x[1] not in freqs:
                        freqs[x[1]] = 0
                    freqs[x[1]] += 1
                # else:
                #     if x[4] not in freqs:
                #         freqs[x[4]] = 0
                #     freqs[x[4]] += 1
                if x[2]:
                    ref = x[2]
                    v['ref'] = ref
                    if place_coords:
                        if ref.startswith(PLEIADES_URL_BASE) \
                           or ref.startswith(GEONAMES_URL_BASE):
                            coords = db_geoCoords(ref)
                            if coords:
                                v['lat'] = coords[0]
                                v['lon'] = coords[1]
                if x[3]:
                    v['type'] = x[3]
                result['list'].append(v)
        result['frequencies'] = freqs
        return result

    def json_persons(self):
        result = { 'list': [] }
        freqs = {}
        for x in self._names:
            if x[0] == 'tei:persName':
                v = {
                    'tag': 'persName',
                    'value':  x[4],
                }
                if x[1]:
                    v['key'] = x[1]
                    if x[1] not in freqs:
                        freqs[x[1]] = 0
                    freqs[x[1]] += 1
                # else:
                #     if x[4] not in freqs:
                #         freqs[x[4]] = 0
                #     freqs[x[4]] += 1
                if x[2]:
                    v['ref'] = x[2]
                result['list'].append(v)
        result['frequencies'] = freqs
        return result

    def json_dates(self):
        result = []
        for x in self._dates:
            v = {
                'iso': x[0],
                'value':  x[1],
            }
            result.append(v)
        return result


# class encompassing most of the possible base text processing: it scans a
# complete text, and extract several lists:
# a.  words: word sequence (no punctuation) as-is
# a2. words_lower: same as above, but all-lowercase and j replaced by i
# b.  lemmas: unique processed lemmas
# c.  words_lemmas: pairs (word, lemma) in the order as words appear in text
# d.  types: unique words not in sequence
class LatinProcessor(object):

    def __init__(self, text=None):
        self.__lemmatizer = BackoffLatinLemmatizer()
        self.__text = None
        if text is not None:
            self.__text = text.strip()
            self.__text_fixed = self.__fix_spaces(
                self.__fix_punctuation(self.__text))
            li = [self.__remove_nonalpha(x)
                  for x in self.__text_fixed.split()]
            self.__word_tokens = list(x for x in li if bool(x))
            self.__word_tokens_lc = list(
                x.lower().replace('j', 'i') for x in self.__word_tokens)
            self.__lemmas_pairs = list(
                (x[0], x[1].lower())
                for x in self.__lemmatizer.lemmatize(self.__word_tokens))
            self.__lemmas = list(set([x[1] for x in self.__lemmas_pairs]))
        else:
            self.__text_fixed = None
            self.__word_tokens = []
            self.__word_tokens_lc = []
            self.__lemmas_pairs = []
            self.__lemmas = []

    # to reuse the class
    def set_text(self, text):
        self.__text = text
        self.__text_fixed = self.__fix_punctuation(text)
        li = [self.__remove_nonalpha(x) for x in self.__text_fixed.split()]
        self.__word_tokens = list(x for x in li if bool(x))
        self.__word_tokens_lc = list(x.lower().replace('j', 'i')
                                     for x in self.__word_tokens)
        self.__lemmas_pairs = list(
            (x[0], x[1].lower())
            for x in self.__lemmatizer.lemmatize(self.__word_tokens))
        self.__lemmas = list(set(x[1] for x in self.__lemmas_pairs))

    # helpers
    @staticmethod
    def __remove_nonalpha(s):
        res = ""
        for x in s:
            if x.isalpha():
                res += x
        return res

    @staticmethod
    def __fix_punctuation(s):
        res = ""
        last_alnum = True
        for l in s:
            is_alnum = l.isalnum()
            if not last_alnum and is_alnum:
                res += " "
            res += l
            last_alnum = is_alnum or l.isspace()
        return res

    @staticmethod
    def __fix_spaces(s):
        text = s
        text = text.replace('\n', '[[__NEWLINE__]] ')
        text = text.replace('\r', '[[__NEWLINE__]] ')
        text = text.replace('\t', '[[__TAB__]] ')
        text = " ".join(text.split())
        text = text.replace('[[__TAB__]]', '\t')
        text = text.replace('[[__NEWLINE__]]', '\n')
        text = text.replace('\t ', '\t')
        text = text.replace(' \t', '\t')
        text = text.replace('\n ', '\n')
        text = text.replace(' \n', '\n')
        return text

    @staticmethod
    def __count_frequency(word_list):
        res = {}
        for w in word_list:
            if w not in res:
                res[w] = 0
            res[w] += 1
        return res

    @staticmethod
    def __average_word_length(word_list):
        if word_list:
            return sum(len(x) for x in word_list) / len(word_list)
        else:
            return 0

    @staticmethod
    def __max_word_length(word_list):
        if word_list:
            return max(len(x) for x in word_list)
        else:
            return 0

    @staticmethod
    def __min_word_length(word_list):
        if word_list:
            return min(len(x) for x in word_list)
        else:
            return 0

    @staticmethod
    def __skip_stopwords(word_list, check_lower=True):
        if check_lower:
            return list(x for x in word_list if x.lower() not in STOPS_LIST)
        else:
            return list(x for x in word_list if x not in STOPS_LIST)

    # properties
    text = property(lambda s: s.__text_fixed)
    words = property(lambda s: s.__word_tokens.copy())
    words_lower = property(lambda s: s.__word_tokens_lc.copy())
    words_nostops = property(lambda s: s.__skip_stopwords(s.__word_tokens_lc))
    words_lemmas = property(lambda s: s.__lemmas_pairs.copy())
    lemmas = property(lambda s: s.__lemmas.copy())
    lemmas_list = property(lambda s: list(x[1] for x in s.__lemmas_pairs))
    lemmas_nostops = property(lambda s: s.__skip_stopwords(s.__lemmas))
    types = property(lambda s: list(set(s.__word_tokens_lc)))
    types_max_len = property(lambda s: s.__max_word_length(s.types))
    types_min_len = property(lambda s: s.__min_word_length(s.types))
    types_average_len = property(lambda s: s.__average_word_length(s.types))

    # calls
    def get_word_frequencies(self, case_sensitive=False):
        if self.__text is not None:
            if case_sensitive:
                return self.__count_frequency(self.__word_tokens)
            else:
                return self.__count_frequency(self.__word_tokens_lc)
        else:
            return None

    def get_lemma_frequencies(self):
        if self.__text is not None:
            llist = list(x[1] for x in self.__lemmas_pairs)
            return self.__count_frequency(llist)
        else:
            return None


# simpler text processing class, language agnostic
class GenericProcessor(object):

    def __init__(self, text=None):
        self.__text = None
        if text is not None:
            self.__text = text.strip()
            self.__text_fixed = self.__fix_spaces(
                self.__fix_punctuation(self.__text))
            li = [self.__remove_nonalpha(x)
                  for x in self.__text_fixed.split()]
            self.__word_tokens = list(x for x in li if bool(x))
            self.__word_tokens_lc = list(x.lower() for x in self.__word_tokens)
        else:
            self.__text_fixed = None
            self.__word_tokens = []
            self.__word_tokens_lc = []

    # to reuse the class
    def set_text(self, text):
        self.__text = text
        self.__text_fixed = self.__fix_punctuation(text)
        li = [self.__remove_nonalpha(x) for x in self.__text_fixed.split()]
        self.__word_tokens = list(x for x in li if bool(x))
        self.__word_tokens_lc = list(x.lower() for x in self.__word_tokens)

    # helpers
    @staticmethod
    def __remove_nonalpha(s):
        res = ""
        for x in s:
            if x.isalpha():
                res += x
        return res

    @staticmethod
    def __fix_punctuation(s):
        res = ""
        last_alnum = True
        for l in s:
            is_alnum = l.isalnum()
            if not last_alnum and is_alnum:
                res += " "
            res += l
            last_alnum = is_alnum or l.isspace()
        return res

    @staticmethod
    def __fix_spaces(s):
        text = s
        text = text.replace('\n', '[[__NEWLINE__]] ')
        text = text.replace('\r', '[[__NEWLINE__]] ')
        text = text.replace('\t', '[[__TAB__]] ')
        text = " ".join(text.split())
        text = text.replace('[[__TAB__]]', '\t')
        text = text.replace('[[__NEWLINE__]]', '\n')
        text = text.replace('\t ', '\t')
        text = text.replace(' \t', '\t')
        text = text.replace('\n ', '\n')
        text = text.replace(' \n', '\n')
        return text

    @staticmethod
    def __count_frequency(word_list):
        res = {}
        for w in word_list:
            if w not in res:
                res[w] = 0
            res[w] += 1
        return res

    @staticmethod
    def __average_word_length(word_list):
        if word_list:
            return sum(len(x) for x in word_list) / len(word_list)
        else:
            return 0

    @staticmethod
    def __max_word_length(word_list):
        if word_list:
            return max(len(x) for x in word_list)
        else:
            return 0

    @staticmethod
    def __min_word_length(word_list):
        if word_list:
            return min(len(x) for x in word_list)
        else:
            return 0

    # properties
    text = property(lambda s: s.__text_fixed)
    words = property(lambda s: s.__word_tokens.copy())
    words_lower = property(lambda s: s.__word_tokens_lc.copy())
    types = property(lambda s: list(set(s.__word_tokens_lc)))
    types_max_len = property(lambda s: s.__max_word_length(s.types))
    types_min_len = property(lambda s: s.__min_word_length(s.types))
    types_average_len = property(lambda s: s.__average_word_length(s.types))

    # calls
    def get_word_frequencies(self, case_sensitive=False):
        if self.__text is not None:
            if case_sensitive:
                return self.__count_frequency(self.__word_tokens)
            else:
                return self.__count_frequency(self.__word_tokens_lc)
        else:
            return None


# take a LatinProcessor and return a dictionary with all extracted data
def lproc_to_dict(lp):
    words_number = len(lp.words)
    words_number_nostops = len(lp.words_nostops)
    lemmas_number = len(lp.lemmas)
    lemmas_number_nostops = len(lp.lemmas_nostops)
    types_number = len(lp.types)
    word_frequencies = lp.get_word_frequencies()
    stop_frequencies = {}   # TODO: should be a dict comprehension
    word_frequencies_nostops = {}
    for x in word_frequencies:
        if x in STOPS_LIST:
            stop_frequencies[x] = word_frequencies[x]
        else:
            word_frequencies_nostops[x] = word_frequencies[x]

    try:
        ttr = types_number / words_number
    except ZeroDivisionError as e:
        ttr = 0
    return {
        'text': lp.text,
        'word_list': lp.words,
        'word_list_lowercase': lp.words_lower,
        'word_list_nostops': lp.words_nostops,
        'words_number': words_number,
        'words_number_nostops': words_number_nostops,
        'lemma_list': lp.lemmas,
        'lemmas_number': lemmas_number,
        'type_list': lp.types,
        'types_number': types_number,
        'types_min_length': lp.types_min_len,
        'types_max_length': lp.types_max_len,
        'types_mean_length': lp.types_average_len,
        'word_lemma_list': lp.words_lemmas,
        'word_frequencies': word_frequencies,
        'stop_frequencies': stop_frequencies,
        'word_frequencies_nostops': word_frequencies_nostops,
        'lemma_frequencies': lp.get_lemma_frequencies(),
        'ttr': ttr,
    }


# take a GenericProcessor and return a dictionary with all extracted data
def gproc_to_dict(lp):
    words_number = len(lp.words)
    types_number = len(lp.types)

    try:
        ttr = types_number / words_number
    except ZeroDivisionError as e:
        ttr = 0
    return {
        'text': lp.text,
        'word_list': lp.words,
        'word_list_lowercase': lp.words_lower,
        'words_number': words_number,
        'type_list': lp.types,
        'types_number': types_number,
        'types_min_length': lp.types_min_len,
        'types_max_length': lp.types_max_len,
        'types_mean_length': lp.types_average_len,
        'word_frequencies': lp.get_word_frequencies(),
        'word_frequencies_casesensitive': lp.get_word_frequencies(True),
        'ttr': ttr,
    }


# a simple class that converts a full text into a list of paragraphs
class LatinParagraphizer(object):

    def __init__(self, text):
        self.__tokenizer = LineTokenizer('latin')
        self.__text_fixed = self.__fix_spaces(self.__fix_punctuation(text))
        self.__paragraphs = self.__tokenizer.tokenize(self.__text_fixed)

    # helpers
    @staticmethod
    def __fix_punctuation(s):
        res = ""
        last_alnum = True
        for l in s:
            is_alnum = l.isalnum()
            if not last_alnum and is_alnum:
                res += " "
            res += l
            last_alnum = is_alnum or l.isspace()
        return res

    @staticmethod
    def __fix_spaces(s):
        text = s
        text = text.replace('\n', '[[__NEWLINE__]] ')
        text = text.replace('\r', '[[__NEWLINE__]] ')
        text = text.replace('\t', '[[__TAB__]] ')
        text = " ".join(text.split())
        text = text.replace('[[__TAB__]]', '\t')
        text = text.replace('[[__NEWLINE__]]', '\n')
        text = text.replace('\t ', '\t')
        text = text.replace(' \t', '\t')
        text = text.replace('\n ', '\n')
        text = text.replace(' \n', '\n')
        return text

    # properties
    text = property(lambda s: s.__text_fixed)
    paragraphs = property(lambda s: s.__paragraphs)


# POS taggers
# backoff 123 bayesian POS tagger
def bayesian_POStagger(text):
    lp = LatinParagraphizer(text)
    tagger = POSTag('latin')
    paragraphs = lp.paragraphs
    sentences = []
    for p in paragraphs:
        _sentences = list(x.strip() for x in p.split('.'))
        sentences += _sentences
    res = []
    for x in sentences:
        if len(x) > 0:
            _tags = [x for x in tagger.tag_ngram_123_backoff(x)
                     if len(x[0]) > 1 or x[0].isalnum()]
            tags = []
            for y in _tags:
                if not y[1]:
                    tags.append((y[0], "Unk"))
                else:
                    tags.append(y)
            res.append((x, tags))
    return res


# hidden Markov model (HMM) based POS tagger
def hmm_POStagger(text):
    lp = LatinParagraphizer(text)
    tagger = POSTag('latin')
    paragraphs = lp.paragraphs
    sentences = []
    for p in paragraphs:
        _sentences = list(x.strip() for x in p.split('.'))
        sentences += _sentences
    res = []
    for x in sentences:
        if len(x) > 0:
            tags = list(x for x in tagger.tag_tnt(x)
                        if len(x[0]) > 1 or x[0].isalnum())
            res.append((x, tags))
    return res


# functions operating directly on the file system

# writes concordances to a file
def write_concordances(text, dest_filename):
    text_clean = phi5_plaintext_cleanup(text).lower()
    concordances = philology.build_concordance(text_clean)
    with open_utf8(dest_filename, 'w') as f:
        for wlist in concordances:
            f.write("%s\n" % ' '.join(wlist))


# write collocations to a file
def write_collocations(filebase, processor, dest_filename,
                       window=2, lemmas=False):
    result_data = {
        'file_basename': filebase,
    }
    bigram_measures = nltk.collocations.BigramAssocMeasures()
    for wsize in range(2, window + 1):
        if lemmas:
            li = processor.lemmas_list
        else:
            li = processor.words_lower
        finder = nltk.collocations.BigramCollocationFinder.from_words(
            li, window_size=wsize)
        finder.apply_freq_filter(2)
        scored = finder.score_ngrams(bigram_measures.raw_freq)
        li = list((' '.join(list(x[0])), x[1]) for x in scored)
        entryname = 'collocations_windowsize%s' % wsize
        result_data[entryname] = li.copy()
    with open_utf8(dest_filename, 'w') as f:
        f.write(json.dumps(result_data, indent=4))


# write ngrams to a file
def write_ngrams(filebase, processor, dest_filename,
                 size=2, lemmas=False):
    result_data = {
        'file_basename': filebase,
    }
    for nsize in range(2, size + 1):
        if lemmas:
            li = processor.lemmas_list
        else:
            li = processor.words_lower
        lister = nltk_ngrams(li, nsize)
        result_data['ngrams%s' % nsize] = list(x for x in lister)
    with open_utf8(dest_filename, 'w') as f:
        f.write(json.dumps(result_data, indent=4))


# write POS tags to a file: bayesian
def write_bayesian_pos_tags(filebase, text, dest_filename):
    result_data = {
        'file_basename': filebase,
    }
    data = bayesian_POStagger(text)
    result_data['tagged_sentences'] = data
    with open_utf8(dest_filename, 'w') as f:
        f.write(json.dumps(result_data, indent=4))


# write POS tags to a file: HMM based
def write_hmm_pos_tags(filebase, text, dest_filename):
    result_data = {
        'file_basename': filebase,
    }
    data = hmm_POStagger(text)
    result_data['tagged_sentences'] = data
    with open_utf8(dest_filename, 'w') as f:
        f.write(json.dumps(result_data, indent=4))


# writers for XML TEI data
def write_xmltei_attributes(filebase, teiparser, dest_filename):
    result_data = {
        'file_basename': filebase,
    }
    result_data['xmltei_attributes'] = teiparser.attributes
    with open_utf8(dest_filename, 'w') as f:
        f.write(json.dumps(result_data, indent=4))

def write_xmltei_lists(filebase, teiparser, dest_filename):
    result_data = {
        'file_basename': filebase,
    }
    result_data['xmltei_places'] = teiparser.json_places()
    result_data['xmltei_persons'] = teiparser.json_persons()
    result_data['xmltei_dates'] = teiparser.json_dates()
    with open_utf8(dest_filename, 'w') as f:
        f.write(json.dumps(result_data, indent=4))


# generic utilities
def oerr(text):
    sys.stderr.write("%s: %s\n" % (sys.argv[0], text))


def exiterror(text, exitcode=2):
    oerr(text)
    sys.exit(exitcode)


def omsg(text):
    sys.stdout.write("[%s] %s\n" % (time.asctime(), text))


# utility to completely process a file:
# takes a file name and output several files in the output folder: see
# the result_... variables below to determine files and type of data
def process_file(filebase,
                 paragraphize=False, verbose=False, logfile=None,
                 actions={}, assume_text=False):
    if verbose:
        t0 = time.time()
    tei_parser = TeiParser_ELA()
    lat_processor = LatinProcessor()
    lat_processor_t = LatinProcessor()
    gen_processor = GenericProcessor()
    gen_processor_t = GenericProcessor()

    result_statistics = fname_result(filebase, "_statistics.json")
    result_ftstatistics = fname_result(filebase, "_fulltext_statistics.json")
    result_concordances = fname_result(filebase, "_concordances.txt")
    result_collocations = fname_result(filebase, "_collocations.json")
    result_lcollocations = fname_result(filebase, "_lemma_collocations.json")
    result_bayesian_pos = fname_result(filebase, "_bayesian_pos.json")
    result_hmm_pos = fname_result(filebase, "_hmm_pos.json")
    result_ngrams = fname_result(filebase, "_ngrams.json")

    file_ext = '.txt'
    if not assume_text:
        file_ext = '.xml'
        result_teiheader = fname_result(filebase, "_tei_attrs.json")
        result_teilists = fname_result(filebase, "_tei_lists.json")

    production = []

    if assume_text:
        origin = fname_origin(filebase, ".txt")
    else:
        origin = fname_origin(filebase, ".xml")
    error_status = False
    try:
        try:
            with open_utf8(origin) as f:
                original_text = f.read()
            if not assume_text:
                full_text = ""
                latin_text = ""
                tei_parser.feed(original_text)
                for elem in tei_parser.text_head:
                    if full_text:
                        full_text += '\n' if elem[0] == 'PP' else ' '
                    full_text += elem[2]
                    if elem[1] == 'lat':
                        if latin_text:
                            latin_text += '\n' if elem[0] == 'PP' else ' '
                        latin_text += elem[2]
                for elem in tei_parser.text_front:
                    if full_text:
                        full_text += '\n' if elem[0] == 'PP' else ' '
                    full_text += elem[2]
                    if elem[1] == 'lat':
                        if latin_text:
                            latin_text += '\n' if elem[0] == 'PP' else ' '
                        latin_text += elem[2]
                for elem in tei_parser.text_body:
                    if full_text:
                        full_text += '\n' if elem[0] == 'PP' else ' '
                    full_text += elem[2]
                    if elem[1] == 'lat':
                        if latin_text:
                            latin_text += '\n' if elem[0] == 'PP' else ' '
                        latin_text += elem[2]
            else:
                full_text = original_text
                latin_text = original_text
        except Exception as e:
            oerr("could not read '%s' (%s)" % (filebase, str(e)))
            if logfile:
                logfile.write('READ ERROR: %s / CAUSE: %s\n' % (
                              filebase, str(e)))
            return False

        # setup processors
        lat_processor.set_text(latin_text)
        gen_processor.set_text(full_text)

        if not assume_text:
            # actions that rely on XML-TEI file assumption
            try:
                if 'tei_attrs' in actions:
                    write_xmltei_attributes(
                        filebase, tei_parser, result_teiheader)
            except Exception as e:
                oerr("could not write XML-TEI attributes for '%s' (%s)" % (
                     filebase, str(e)))
                if logfile:
                    logfile.write('XML_TEI_ATTRS SKIPPED: %s / CAUSE: %s\n' % (
                                  filebase, str(e)))
            try:
                if 'tei_lists' in actions:
                    write_xmltei_lists(filebase, tei_parser, result_teilists)
            except Exception as e:
                oerr("could not write XML-TEI lists for '%s' (%s)" % (
                     filebase, str(e)))
                if logfile:
                    logfile.write('XML_TEI_LISTS SKIPPED: %s/ CAUSE: %s\n' % (
                                  filebase, str(e)))

        # processor based result data which rely on LATIN text
        try:
            if 'stats' in actions:
                result_data = lproc_to_dict(lat_processor)
                result_data['file_basename'] = filebase
                if paragraphize:
                    paragraphizer = LatinParagraphizer(latin_text)
                    paragraphs_data = []
                    for x in paragraphizer.paragraphs:
                        lat_processor_t.set_text(x)
                        data = lproc_to_dict(lat_processor_t)
                        paragraphs_data.append(data)
                    result_data['paragraphs'] = paragraphs_data
                res = json.dumps(result_data, indent=4)
                with open_utf8(result_statistics, 'w') as w:
                    w.write(res)
                production.append('stats-latin')
        except Exception as e:
            oerr("could not write statistics for '%s' (%s)" % (
                 filebase, str(e)))
            if logfile:
                logfile.write('STATS SKIPPED: %s/ CAUSE: %s\n' % (
                              filebase, str(e)))
        try:
            if 'lemma_collocations' in actions:
                write_collocations(
                    filebase, lat_processor, result_lcollocations,
                    actions['lemma_collocations'], True)
                production.append('lemma_collocations')
        except Exception as e:
            oerr("could not write lemma collocations for '%s' (%s)" % (
                 filebase, str(e)))
            if logfile:
                logfile.write('LEMMA_COLLOCATIONS SKIPPED: %s/ CAUSE: %s\n' % (
                              filebase, str(e)))
        try:
            if 'ngrams' in actions:
                write_ngrams(filebase, lat_processor, result_ngrams,
                             actions['ngrams'], True)
                production.append('ngrams')
        except Exception as e:
            oerr("could not write ngrams for '%s' (%s)" % (
                 filebase, str(e)))
            if logfile:
                logfile.write('NGRAMS SKIPPED: %s/ CAUSE: %s\n' % (
                              filebase, str(e)))

        # processor based result data which rely on FULL text
        try:
            if 'stats' in actions:
                result_data = gproc_to_dict(gen_processor)
                result_data['file_basename'] = filebase
                res = json.dumps(result_data, indent=4)
                with open_utf8(result_ftstatistics, 'w') as w:
                    w.write(res)
                production.append('stats-fulltext')
        except Exception as e:
            oerr("could not write full-text statistics for '%s' (%s)" % (
                 filebase, str(e)))
            if logfile:
                logfile.write('FULL-TEXT STATS SKIPPED: %s/ CAUSE: %s\n' % (
                              filebase, str(e)))
        try:
            if 'collocations' in actions:
                processor.set_text(full_text)
                write_collocations(
                    filebase, gen_processor, result_collocations,
                    actions['collocations'])
                production.append('collocations')
        except Exception as e:
            oerr("could not write collocations for '%s' (%s)" % (
                 filebase, str(e)))
            if logfile:
                logfile.write('COLLOCATIONS SKIPPED: %s/ CAUSE: %s\n' % (
                              filebase, str(e)))
        # other result data that do not use a processor relying on LATIN text
        try:
            if 'hmm_pos' in actions:
                write_hmm_pos_tags(filebase, latin_text, result_hmm_pos)
                production.append('hmm_pos')
        except Exception as e:
            oerr("could not write HMM POS tags for '%s' (%s)" % (
                 filebase, str(e)))
            if logfile:
                logfile.write('HMM_POS SKIPPED: %s/ CAUSE: %s\n' % (
                              filebase, str(e)))
        try:
            if 'bayesian_pos' in actions:
                write_bayesian_pos_tags(filebase, latin_text,
                                        result_bayesian_pos)
                production.append('bayesian_pos')
        except Exception as e:
            oerr("could not write bayesian POS tags for '%s' (%s)" % (
                 filebase, str(e)))
            if logfile:
                logfile.write('BAYESIAN_POS SKIPPED: %s/ CAUSE: %s\n' % (
                              filebase, str(e)))
        # other result data that do not use a processor relying on FULL text
        try:
            if 'concordances' in actions:
                write_concordances(full_text, result_concordances)
                production.append('concordances')
        except Exception as e:
            oerr("could not write concordances for '%s' (%s)" % (
                 filebase, str(e)))
            if logfile:
                logfile.write('CONCORDANCES SKIPPED: %s/ CAUSE: %s\n' % (
                              filebase, str(e)))
        if verbose:
            t1 = time.time()
            msg = "processed: '%s' (elapsed: %.3f sec, produced: %s)" % (
                  filebase, t1 - t0, ", ".join(production))
            omsg(msg)
        return True
    except Exception as e:
        if verbose:
            msg = "could not process '%s' (%s)" % (filebase, str(e))
            omsg(msg)
        if logfile:
            logfile.write('PROCESS ERROR: %s/ CAUSE: %s\n' % (
                          filebase, str(e)))
        return False


# module command line: use as a standalone application
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
        description="Preprocess latin text file(s) for ELA")
    parser.add_argument(
        '-a', '--all', action='store_true',
        help="process all files in the source directory")
    parser.add_argument(
        '-C', '--collocations', action='store',
        type=int, default=0, metavar='N',
        help="generate collocations file with window up to N [N=2..5]")
    parser.add_argument(
        '-L', '--lemma-collocations', action='store',
        dest='lemma_collocations', type=int, default=0, metavar='N',
        help="generate lemma collocations file with window up to N [N=2..5]")
    parser.add_argument(
        '-N', '--ngrams', action='store',
        type=int, default=0, metavar='N',
        help="generate ngrams file of sizes up to N [N=2..5]")
    parser.add_argument(
        '-O', '--concordances', action='store_true',
        help="generate concordances file")
    parser.add_argument(
        '-B', '--bayesian-pos', action='store_true', dest='bayesian_pos',
        help="generate bayesian POS tag file")
    parser.add_argument(
        '-M', '--hmm-pos', action='store_true', dest='hmm_pos',
        help="generate HMM base POS tag file")
    parser.add_argument(
        '-T', '--assume-text', action='store_true', dest='assume_text',
        help="assume simple text files instead of XML-TEI")
    parser.add_argument(
        '-A', '--tei-attrs', action='store_true', dest='tei_attrs',
        help="generate XML-TEI header attributes file")
    parser.add_argument(
        '-S', '--tei-lists', action='store_true', dest='tei_lists',
        help="generate XML-TEI lists file")
    parser.add_argument(
        '-v', '--verbose', action='store_true',
        help="produce verbose output and timings")
    parser.add_argument(
        '-p', '--para', action='store_true',
        help="include split paragraph data in statistics file")
    parser.add_argument(
        '--full-monty', action='store_true', dest='full_monty',
        help="generate MOST files for specified texts")
    parser.add_argument(
        'basename', metavar="BASE_FILENAME", type=str,
        default=None, nargs='?',
        help="base of filename to process (no directory/extension)")

    args = parser.parse_args()
    cfg_fname = os.path.splitext(sys.argv[0])[0] + '.cfg'
    if os.path.exists(cfg_fname):
        if args.verbose:
            omsg("reading configuration from '%s'" % cfg_fname)
        try:
            with open_utf8(cfg_fname) as f:
                s = f.read()
            reconfigure(s)
        except Exception as e:
            exiterror("FATAL: could not read configuration file '%s' (%s)" % (
                      cfg_fname, e))
    else:
        reconfigure()

    try:
        processor = LatinProcessor()
    except Exception as e:
        oerr("initialization failed, some components may be missing")
        oerr("make sure GIT and 'latin_models_cltk' have been installed")
        exiterror("FATAL: could not initialize CLTK")

    if args.basename and args.all:
        exiterror("please either specify a file basename or --all", 1)

    if args.basename:
        basenames = [args.basename]
    elif args.all:
        if args.assume_text:
            basenames = list_origin_files(".txt")
        else:
            basenames = list_origin_files(".xml")
    else:
        exiterror("please specify a file basename, or --all for all files", 1)

    # define what we have to do
    actions = {
        'stats': True,
    }

    if args.collocations:
        if args.full_monty:
            exiterror("either specify some services or all services", 1)
        if args.collocations < 2:
            oerr("collocation window too low, defaulting to 2")
            actions['collocations'] = 2
        elif args.collocations > 5:
            oerr("collocation window too high, defaulting to 5")
            actions['collocations'] = 5
        else:
            actions['collocations'] = args.collocations

    if args.lemma_collocations:
        if args.full_monty:
            exiterror("either specify some services or all services", 1)
        if args.collocations < 2:
            oerr("collocation window too low, defaulting to 2")
            actions['lemma_collocations'] = 2
        elif args.collocations > 5:
            oerr("collocation window too high, defaulting to 5")
            actions['lemma_collocations'] = 5
        else:
            actions['lemma_collocations'] = args.collocations

    if args.ngrams:
        if args.full_monty:
            exiterror("either specify some services or all services", 1)
        if args.collocations < 2:
            oerr("ngram size too low, defaulting to 2")
            actions['ngrams'] = 2
        elif args.collocations > 5:
            oerr("ngram size too high, defaulting to 5")
            actions['ngrams'] = 5
        else:
            actions['ngrams'] = args.collocations

    if args.concordances:
        if args.full_monty:
            exiterror("either specify some services or all services", 1)
        actions['concordances'] = True

    if args.bayesian_pos:
        # if args.full_monty:
        #     exiterror("either specify some services or all services", 1)
        actions['bayesian_pos'] = True

    if args.hmm_pos:
        # if args.full_monty:
        #     exiterror("either specify some services or all services", 1)
        actions['hmm_pos'] = True

    if args.assume_text:
        if args.tei_attrs or args.tei_lists:
            exiterror("XML-TEI specific feature disabled for raw text", 1)
    else:
        if args.verbose:
            omsg("notice: assuming input files are in XML-TEI specific format")

    if args.tei_attrs:
        if args.full_monty:
            exiterror("either specify some services or all services", 1)
        actions['tei_attrs'] = True

    if args.tei_lists:
        if args.full_monty:
            exiterror("either specify some services or all services", 1)
        actions['tei_lists'] = True

    if args.full_monty:
        actions['concordances'] = True
        actions['ngrams'] = 5
        actions['lemma_collocations'] = 5
        actions['collocations'] = 5
        # actions['bayesian_pos'] = True
        # actions['hmm_pos'] = True
        if not args.assume_text:
            actions['tei_attrs'] = True
            actions['tei_lists'] = True

    if args.verbose:
        if 'stats' in actions:
            omsg("extracting: statistics")
        if 'collocations' in actions:
            omsg("extracting: collocations (window max size: %s)" % (
                 actions['collocations'],))
        if 'lemma_collocations' in actions:
            omsg("extracting: lemma_collocations (window max size: %s)" % (
                 actions['lemma_collocations'],))
        if 'ngrams' in actions:
            omsg("extracting: ngrams (ngram max size: %s)" % (
                 actions['ngrams'],))
        if 'concordances' in actions:
            omsg("extracting: concordances")
        if 'bayesian_pos' in actions:
            omsg("extracting: bayesian POS (Parts Of Speech) tags")
        if 'hmm_pos' in actions:
            omsg("extracting: HMM based POS (Parts Of Speech) tags")
        if 'tei_attrs' in actions:
            omsg("extracting: XML-TEI header attributes")
        if 'tei_lists' in actions:
            omsg("extracting: XML-TEI element lists")

    num_processed = 0
    num_skipped = 0
    if args.verbose:
        omsg("starting process for %s" % (
             "all files" if args.all else "file '%s'" % args.basename,))
        omsg("environment:\nsource: '%s'\ndestination: '%s'" % (
             cfg_paths['SRCORIGIN'], cfg_paths['RESDEST']))

    logfile = None
    if cfg_paths['LOGFILE']:
        try:
            logfile = open_utf8(cfg_paths['LOGFILE'], 'w')
        except Exception as e:
            exiterror("FATAL: could not open '%s' for logging" %
                      cfg_paths['LOGFILE'])

        logfile.write("session starting: %s\n" % time.asctime())
        if args.verbose:
            omsg("logging errors to: '%s'" % cfg_paths['LOGFILE'])

    if cfg_paths['DATABASE']:
        try:
            DB = db.connect(cfg_paths['DATABASE'])
            DB.row_factory = db.Row
        except Exception as e:
            DB = None
            if args.verbose:
                omsg("cannot open DB: '%s'" % cfg_paths['DATABASE'])
                omsg("WARNING: database based data will not be provided")
            logfile.write("database cannot be opened\n")

    if args.verbose:
        omsg('--- BEGIN ---')

    t0 = time.time()
    for x in basenames:
        if process_file(x, verbose=args.verbose,
                        paragraphize=args.para, logfile=logfile,
                        actions=actions, assume_text=args.assume_text):
            num_processed += 1
        else:
            num_skipped += 1
    t1 = time.time()

    if args.verbose:
        omsg('--- END ---')
        omsg("process ended: %s files processed, %s skipped (%.3f sec)" % (
             num_processed, num_skipped, t1 - t0))


# end.
