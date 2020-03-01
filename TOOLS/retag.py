# retag.py
#
# Discover entity tags, produce entity tag CSV files with variants, insert
# entity tags in files where the tags have not been added for known entities
# and their known variants; operates on XML-TEI files, only in the <text />
# section.
#
# Discoverable entities:
# - persName
# - placeName
# - date

#############################################################################


import os
import sys
import shutil
import time
import json
import argparse
import configparser
import math
import re
import csv
import pickle
import sqlite3 as db

import xml.etree.ElementTree as xml_ET
from collections import namedtuple

# partialize open function to expressedly use UTF-8
from functools import partial
open_utf8 = partial(open, encoding='UTF-8')


#############################################################################

# entity types
# ENT_DATE = 'date'
ENT_GEOG = 'geogName'
ENT_PERS = 'persName'
ENT_PLACE = 'placeName'

# entity names *must* be ordered as below, because person names may contain
# place names, and place names may contain geog names
ENT_TYPES = [ENT_PERS, ENT_PLACE, ENT_GEOG]


# data file
ENT_DATAFILE = os.path.splitext(__file__)[0] + ".data"
ENT_DATAMEM = []
ENT_VARDICT = {}


# entity named tuple
Entity = namedtuple(
    'Entity', [
        'kind',
        'key',
        'ref',
        'geotype',
        'variants',
        'files',
    ])


# TEI default namespace
TEI_NS = "http://www.tei-c.org/ns/1.0"


# a dedicated exception for TEI errors
class TEIStructureError(Exception):
    def __init__(self, s):
        txt = "Invalid XML-TEI: %s" % s
        Exception.__init__(self, txt)


#############################################################################

# utilities
def _flatten_TEI_innertext(node):
    return ("".join(node.itertext())).strip()

def _normalize_TEI_tag(s):
    return s.replace('{%s}' % TEI_NS, 'tei:')

def _find_TEI_singlenode(tag, basenode):
    xmlns = { 'tei': TEI_NS, }
    li = list(basenode.findall('tei:%s' % tag, xmlns))
    n = len(li)
    if n != 1:
        raise TEIStructureError("%s '%s' sections found" % (n, tag))
    return li[0]

def _find_TEI_listnodes(tag, basenode):
    xmlns = { 'tei': TEI_NS, }
    T = lambda s: _normalize_TEI_tag(s)
    F = lambda node: _flatten_TEI_innertext(node)
    A = lambda node, a: node.attrib[a] if a in node.attrib else None
    li = []
    for node in basenode.iter():
        if T(node.tag) == "tei:%s" % tag:
            li.append(node)
    return li


def _Entity_toString(e):
    FMT = '"%s";%s;%s;%s;"%s";"%s"'
    vars = '|'.join(list(x.strip() for x in e.variants if x.strip()))
    files = '|'.join(list(x.strip() for x in e.files if x.strip()))
    return FMT % (e.key.strip(), e.kind.strip(),
                  '' if e.ref is None else e.ref.strip(),
                  '' if e.geotype is None else e.geotype.strip(),
                  vars, files)

def _Entity_fromString(s):
    try:
        for row in csv.reader([s]):
            key = row[0].strip()
            kind = row[1].strip()
            ref = row[2].strip() if row[2] else None
            geotype = row[3].strip() if row[3] else None
            vars = list(x.strip() for x in row[4].split('|'))
            files = list(x.strip() for x in row[5].split('|'))
            e = Entity(kind, key, ref, geotype, vars, files)
        return e
    except csv.Error:
        raise ValueError("invalid format for Entity string")

def _recodeXMLTags(txt, exclude=ENT_TYPES):
    # this replaces the XML tags that do not need to be reworked, and
    # returns a text where they are replaced by markers as well as a
    # dictionary that associates original tags to replacement markers
    tagre = re.compile(r"\<\/?(\w+)[^\>]*\>")
    start = 0
    idx = 0
    tags = {}
    while start < len(txt):
        mo = tagre.search(txt, start)
        # if anything is found check whether or not it has to be replaced
        if mo:
            tag = mo.group(0)
            # if anything is found and is not among reworkable tags,
            # replace it and advance index to the remaining part of
            # text, otherwise skip the reworkable tags
            if mo.group(1) not in exclude:
                idx += 1
                tag_marker = "[[TAG" + ("0000000000" + str(idx))[-10:] + "]]"
                tags[tag_marker] = tag
                txt = txt[:mo.start()] + tag_marker + txt[mo.end():]
                start += len(tag_marker)
            else:
                start = mo.end()
        else:
            # in this case no tags were found thus it is useless to go on
            break
    # now text contains no tags other than the ones to work on
    return txt, tags

def _filter_nonEmpty(iterable):
    return list(x for x in iterable if x)


#############################################################################

# discover entities of a certain type in the given text; ent_type is one of
# ENT_GEOG, ENT_PERS, ENT_PLACE; if a list of entities is provided, the new
# found ones are used to complete the provided one and the merged list is
# returned
def discover_entities(xml, merge_from=None, filename=None):
    T = lambda s: _normalize_TEI_tag(s)
    F = lambda node: _flatten_TEI_innertext(node)
    A = lambda node, a: node.attrib[a] if a in node.attrib else None
    tree = xml_ET.fromstring(xml)
    text = _find_TEI_singlenode('text', tree)
    ent_ref = {}
    ent_types = {}
    ent_geotypes = {}
    ent_variants = {}
    ent_files = {}
    ent_vardict = {}
    if merge_from:
        for x in merge_from:
            ent_types[x.key] = x.kind
            ent_ref[x.key] = x.ref
            ent_variants[x.key] = x.variants
            ent_files[x.key] = x.files
            if x.key not in ent_vardict:
                ent_vardict[x.key] = x.key
            for v in x.variants:
                if v not in ent_vardict:
                    ent_vardict[v] = x.key
    for ent_type in ENT_TYPES:
        entities = _find_TEI_listnodes(ent_type, text)
        for x in entities:
            key = A(x, 'key')
            ref = A(x, 'ref')
            geotype = A(x, 'type')
            if key:
                key = key.strip()
            if ref:
                ref = ref.strip()
            if geotype:
                geotype = geotype.strip()
            variant = F(x)
            if not key:
                if variant in ent_vardict:
                    key = ent_vardict[variant]
                else:
                    key = '[[UNKNOWN:%s]]' % variant
            if key:
                if key not in ent_types:
                    ent_types[key] = ent_type
                if key not in ent_variants:
                    ent_variants[key] = [key]
                if variant:
                    ent_variants[key].append(variant)
                if key not in ent_files:
                    if filename:
                        ent_files[key] = [filename]
                    else:
                        ent_files[key] = []
                else:
                    if filename not in ent_files[key]:
                        ent_files[key].append(filename)
                if ref:
                    if key not in ent_ref:
                        ent_ref[key] = ref
                if geotype:
                    if key not in ent_geotypes:
                        ent_geotypes[key] = geotype
                ent_vardict[variant] = key
    ret = []
    for x in ent_variants:
        if x in ent_ref:
            ref = ent_ref[x]
        else:
            ref = None
        if x in ent_geotypes:
            geotype = ent_geotypes[x]
        else:
            geotype = None
        e = Entity(
            ent_types[x], x, ref, geotype,
            list(set(ent_variants[x])),
            list(set(ent_files[x])),
            )
        ret.append(e)
    return ret


#############################################################################
# Jupyter Utilities

def JUP_gatherFromXML(fname, load_data=True):
    global ENT_DATAMEM, ENT_DATAFILE
    if not ENT_DATAMEM and load_data:
        if os.path.exists(ENT_DATAFILE):
            with open(ENT_DATAFILE, 'rb') as f:
                ENT_DATAMEM = pickle.load(f)
    with open_utf8(fname) as f:
        xml = f.read()
    ENT_DATAMEM = discover_entities(xml, ENT_DATAMEM, fname)

def JUP_gatherFromXMLDir(dname):
    global ENT_DATAMEM, ENT_DATAFILE
    files = os.listdir(dname)
    for x in files:
        if x.lower().endswith(".xml"):
            fname = os.path.join(dname, x)
            with open_utf8(fname) as f:
                xml = f.read()
                try:
                    ENT_DATAMEM = discover_entities(xml, ENT_DATAMEM, fname)
                except xml_ET.ParseError as e:
                    print("error parsing '%s': %s" % (x, e))

def JUP_readCSV(fname, merge=True):
    global ENT_DATAMEM, ENT_DATAFILE
    with open_utf8(fname) as f:
        reader = csv.DictReader(f, delimiter=';')
        li = []
        for row in reader:
            e = Entity(
                row['TYPE'].strip(),
                row['KEY'].strip(),
                row['REF'].strip() if row['REF'].strip() else None,
                row['GEOTYPE'].strip() if row['GEOTYPE'].strip() else None,
                _filter_nonEmpty(row['VARIANTS'].strip().split('|')),
                _filter_nonEmpty(row['FILES'].strip().split('|')),
            )
            li.append(e)
    if merge:
        di = {}
        for e in ENT_DATAMEM:
            di[(e.kind, e.key)] = e
        for x in li:
            if (x.kind, x.key) in di:
                v = list(set(di[x.key].variants + x.variants))
                f = list(set(di[x.key].files + x.files))
                r = di[x.key].ref
                if not r and x.ref:
                    r = x.ref
                g = di[x.key].geotype
                if not g and x.geotype:
                    g = x.geotype
                e = Entity(x.kind, x.key, r, g, v, f)
                di[x.key] = e
            else:
                di[(x.kind, x.key)] = x
        ENT_DATAMEM = []
        for e in di:
            ENT_DATAMEM.append(di[e])
    else:
        ENT_DATAMEM = li

def JUP_writeCSV(fname):
    global ENT_DATAMEM, ENT_DATAFILE
    with open_utf8(fname, 'w') as csvfile:
        csvfile.write("KEY;TYPE;REF;GEOTYPE;VARIANTS;FILES\n")
        for e in ENT_DATAMEM:
            csvfile.write("%s\n" % _Entity_toString(e))

def JUP_dumpData():
    global ENT_DATAMEM, ENT_DATAFILE
    with open(ENT_DATAFILE, 'wb') as f:
        pickle.dump(ENT_DATAMEM, f)

def JUP_loadData():
    global ENT_DATAMEM, ENT_DATAFILE
    with open(ENT_DATAFILE, 'rb') as f:
        ENT_DATAMEM = pickle.load(f)

def JUP_generateVarKeys():
    global ENT_DATAMEM, ENT_VARDICT
    ENT_VARDICT = {}
    for e in ENT_DATAMEM:
        for x in e.variants:
            ENT_VARDICT[x] = e

def JUP_replaceEntitiesXML(xml, ent_types=ENT_TYPES, remove_unknown=True):
    # NOTE: the remove_unknown parameter is actually ignored, it would
    # normally remove entities where the key is surrounded by [[UNKNOWN:...]]
    def _xmltag(e, v):
        s = '<%s key="%s"' % (e.kind, e.key)
        if e.ref:
            s += ' ref="%s"' % e.ref
        if e.geotype:
            s += ' type="%s"' % e.geotype
        s += '>%s</%s>' % (v, e.kind)
        return s
    head, tail = xml.split('<text>')
    tail, id_tags = _recodeXMLTags(tail, ent_types)
    id_no = 0
    id_subs = {}
    for t in ent_types:
        expr = re.compile(r"\<%s[^>]*>" % t)
        close = "</%s>" % t
        tail = expr.sub("", tail)
        tail = tail.replace(close, "")
    vardict = {}
    for e in ENT_DATAMEM:
        for x in e.variants:
            vardict[x] = e
    sorted_keys = sorted(vardict.keys(), key=lambda s: (-len(s), s))
    for k in sorted_keys:
        e = vardict[k]
        id_no += 1
        id_marker = "[[ID" + ("0000000000" + str(id_no))[-10:] + "]]"
        id_subs[id_marker] = _xmltag(e, k)
        subre = re.compile(r"(\W)(%s)(\W)" % re.escape(k))
        tail = subre.sub('\\1' + id_marker + '\\3', tail)
    for x in id_subs:
        tail = tail.replace(x, id_subs[x])
    for x in id_tags:
        tail = tail.replace(x, id_tags[x])
    # if remove_unknown:
    #     expr = re.compile(r'\ key\=\"\[\[UNKNOWN\:[^\]]*\]\]\"')
    #     tail = expr.sub("", tail)
    return head + "<text>" + tail

def JUP_addEntitiesXML(xml, ent_types=ENT_TYPES, remove_unknown=True):
    # NOTE: the remove_unknown parameter is actually ignored, it would
    # normally remove entities where the key is surrounded by [[UNKNOWN:...]]
    def _xmltag(e, v):
        s = '<%s key="%s"' % (e.kind, e.key)
        if e.ref:
            s += ' ref="%s"' % e.ref
        if e.geotype:
            s += ' type="%s"' % e.geotype
        s += '>%s</%s>' % (v, e.kind)
        return s
    def _we_are_inside_tag(txt, idx):
        # step back to first '<' before idx, or if '>' is found return False
        i = idx
        while i > 0 and txt[i] not in "<>":
            i -= 1
        if txt[i] == '>':
            return False
        # for now we just return True here: we're pretty sure that this will
        # be mostly the case, and in other cases better safe than sorry
        else:
            return True
        pass
    head, tail = xml.split('<text>')
    tail, id_tags = _recodeXMLTags(tail, ent_types)
    vardict = {}
    for e in ENT_DATAMEM:
        for x in e.variants:
            vardict[x] = e
    id_no = 0
    id_subs = {}
    sorted_keys = sorted(vardict.keys(), key=lambda s: (-len(s), s))
    for k in sorted_keys:
        e = vardict[k]
        id_no += 1
        id_marker = "[[ID" + ("0000000000" + str(id_no))[-10:] + "]]"
        id_subs[id_marker] = _xmltag(e, k)
        # first substitute non-keyed occurrences of entity
        s = "<%s>%s</%s>" % (e.kind, k, e.kind)
        tail = tail.replace(s, id_marker)
        # then look for occurrences not surrounded by XML tags and replace them
        start = 0
        while start < len(tail):
            i = tail.find(k, start)
            if i >= start:
                if tail[i - 1] != '>' and tail[i + len(k)] != '<' \
                   and tail[i - 2:i - 1] != '="' \
                   and not _we_are_inside_tag(tail, i):
                    tail = tail[:i] + id_marker + tail[i + len(k):]
                    start = i + len(id_marker)
                else:
                    start = i + len(k)
            else:
                break
    for x in id_subs:
        tail = tail.replace(x, id_subs[x])
    for x in id_tags:
        tail = tail.replace(x, id_tags[x])
    # if remove_unknown:
    #     expr = re.compile(r'\ key\=\"\[\[UNKNOWN\:[^\]]*\]\]\"')
    #     tail = expr.sub("", tail)
    return head + "<text>" + tail


def JUP_replaceEntitiesXMLFile(fname, destfname=None, ent_types=ENT_TYPES, remove_unknown=True):
    # NOTE: the remove_unknown parameter is actually ignored
    with open_utf8(fname) as f:
        xml = f.read()
    res = JUP_replaceEntitiesXML(xml, ent_types, remove_unknown)
    if destfname:
        with open_utf8(destfname, 'w') as f:
            f.write(res)
    else:
        return res

def JUP_addEntitiesXMLFile(fname, destfname=None, ent_types=ENT_TYPES, remove_unknown=True):
    # NOTE: the remove_unknown parameter is actually ignored
    with open_utf8(fname) as f:
        xml = f.read()
    res = JUP_addEntitiesXML(xml, ent_types, remove_unknown)
    if destfname:
        with open_utf8(destfname, 'w') as f:
            f.write(res)
    else:
        return res

def JUP_replaceEntitiesXMLDir(dname, destdir, ent_types=ENT_TYPES, remove_unknown=True):
    # NOTE: the remove_unknown parameter is actually ignored
    files = os.listdir(dname)
    if not os.path.exists(destdir):
        os.makedirs(destdir)
    for fname in files:
        if fname.lower().endswith(".xml"):
            origin = os.path.join(dname, fname)
            target = os.path.join(destdir, fname)
            JUP_replaceEntitiesXMLFile(origin, target, ent_types, remove_unknown)

def JUP_addEntitiesXMLDir(dname, destdir, ent_types=ENT_TYPES, remove_unknown=True):
    # NOTE: the remove_unknown parameter is actually ignored
    files = os.listdir(dname)
    if not os.path.exists(destdir):
        os.makedirs(destdir)
    for fname in files:
        if fname.lower().endswith(".xml"):
            origin = os.path.join(dname, fname)
            target = os.path.join(destdir, fname)
            JUP_addEntitiesXMLFile(origin, target, ent_types, remove_unknown)


#############################################################################
# Main Program

if __name__ == "__main__":
    ENT_DATAFILE = os.path.splitext(__file__)[0] + ".data"




# end.
