# solveabbr.py
#
# simple utility functions to solve abbreviations, intended for use in a
# Jupyter notebook and not as a command or module.

import sys
import os


# partialize open function to expressedly use UTF-8
from functools import partial
open_utf8 = partial(open, encoding='UTF-8')


#############################################################################


ABBR = {
    'Fr.': {
        'us': 'Frater',
        'um': 'Fratrem',
        'o': 'Fratri',
        # 'i': 'Fratri',
        'os': 'Fratres',
        'ibus': 'Fratribus',
    },

    'Rev.': {
        'us': 'Reverendus',
        'um': 'Reverendum',
        'o': 'Reverendo',
        # 'i': 'Reverendi',
        'os': 'Reverendos',
        'ibus': 'Reverendis',
    },

    # ...
}


PATTERN = ''.join("""
<choice>
    <abbr>%s</abbr>
    <expan>%s</expan>
</choice>
""".split())


COMMENT = '\n<!-- WARNING: abbreviation "%s" automatically replaced %s times -->\n'


# maximum number of characters that the main function explores forward to
# find the required <persName/> tag
MAX_LOOK_FORWARD = 80


#############################################################################


def _solve_abbr(abbr, txt):
    cnt = 0
    if abbr not in ABBR:
        raise ValueError("abbreviation '%s' is unknown" % abbr)
    res = ""
    head, tail = '', txt
    while tail:
        res += head
        if head and head[-1].isalnum():
            head = tail[0]
            tail = tail[1:]
        elif tail.startswith(abbr) and not head.endswith('<abbr>'):
            d = ABBR[abbr]
            j = 0
            tester = None
            while j < MAX_LOOK_FORWARD and j < len(tail):
                if tail[j:].startswith("<persName"):
                    tester = tail.split('>', 1)[1].split(maxsplit=1)[0]
                    break
                else:
                    j += 1
            if tester:
                try:
                    repl = None
                    for suffix in d:
                        if tester.endswith(suffix):
                            repl = PATTERN % (abbr, d[suffix])
                            break
                    if repl:
                        head = repl
                        tail = tail[len(abbr):]
                        cnt += 1
                    else:
                        head = tail[0]
                        tail = tail[1:]
                except IndexError as e:
                    print("SKIPPED: %s" % e)
                    head = tail[0]
                    tail = tail[1:]
            else:
                head = tail[0]
                tail = tail[1:]
        else:
            head = tail[0]
            tail = tail[1:]
    return cnt, res


#############################################################################


def solve_abbr_text(abbr, tei_text):
    header, text = tei_text.split("<text>", 1)
    cnt, res = _solve_abbr(abbr, text)
    # return header + '<text>' + res
    return header + '<text>' + res + COMMENT % (abbr, cnt)

def solve_abbr_file(abbr, tei_file, res_file=None):
    if not res_file:
        res_file = os.path.splitext(tei_file)[0] + "_solve.xml"
    with open_utf8(tei_file) as f:
        text = f.read()
    res = solve_abbr_text(abbr, text)
    with open_utf8(res_file, 'w') as f:
        f.write(res)

def solve_abbrs_file(tei_file, res_file=None):
    if not res_file:
        res_file = os.path.splitext(tei_file)[0] + "_solve.xml"
    with open_utf8(tei_file) as f:
        text = f.read()
    res = text
    for abbr in ABBR:
        res = solve_abbr_text(abbr, res)
    with open_utf8(res_file, 'w') as f:
        f.write(res)


# end.
