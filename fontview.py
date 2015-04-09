# coding = utf-8
"""Font internals reporting tool.

This command-line tool is able to generate various reports about the internals
of the given TrueType or OpenType font, such as:
  - Supported unicode characters
  - Supported glyphs

Reports are generated in PDF format and contain font-specific rendering of
the glyphs supported by the font.

"""
from collections import namedtuple
import os
import sys
import subprocess
import unicodedata

from fontTools.ttLib import TTFont, TTLibError

class Glyph:
  def __init__(self, name):
    self.name = name
    self.advanceWidth = None
    self.lsb = None
    self.classDef = None

class FontFile(object):
  """Representation of font metadata.

  Provides high-level API on top of FontTools library that is used by
  report generators.
  """
  NAME_CODES = {'Copyright': 0, 'Family': 1, 'Subfamily': 2,
                'Full Name': 4, 'Version': 5, 'PostScrpt Name': 6,
                'Trademark': 7, 'Manufacturer': 8, 'Designer': 9,
                'Description': 10, 'Vendor URL': 11, 'Designer URL': 12,
                'License': 13, 'License URL': 14, 'Sample Text': 19}

  def __init__(self, filename):
    self.filename = filename
    self.ttf = TTFont(filename, fontNumber=-1, lazy=True)
    self._names = {}
    self._ParseNames()

  def _ParseNames(self):
    if 'name' in self.ttf:
      for name in self.ttf['name'].names:
        if name.isUnicode():
          text = name.string.decode('utf-16be')
        else:
          text = name.string.decode('latin1')
        if name.nameID not in self._names:
          self._names[name.nameID] = text

  def GetTables(self):
    return sorted(self.ttf.reader.keys())

  def GetTitle(self):
    title = self.GetName('Full Name')
    if not title:
      title = self.GetName('Family') + ' ' + self.GetName('Subfamily')
    return title

  def GetAuthor(self):
    author = self.GetName('Designer')
    manufacturer = self.GetName('Manufacturer')
    if author and manufacturer and author != manufacturer:
      return "%s (%s)" % (author, manufacturer)
    elif author:
      return author
    else:
      return manufacturer

  def GetUnicodeCharacters(self):
    chars = set()
    if 'cmap' in self.ttf:
      for table in self.ttf['cmap'].tables:
        if table.isUnicode():
          for code, name in table.cmap.items():
            chars.add((code, name))
    return sorted(chars)

  def GetGlyphs(self):
    """Fetch available glyph names."""
    result = []
    for name in self.ttf.getGlyphOrder():
      glyph = Glyph(name)
      if 'hmtx' in self.ttf:
        glyph.advanceWidth, glyph.lsb = self.ttf['hmtx'].metrics.get(name, [None, None])
      if 'GDEF' in self.ttf:
        glyph.classDef = self.ttf['GDEF'].table.GlyphClassDef.classDefs.get(name, 0)
      result.append(glyph)
    return result

  def GetName(self, name, default=None):
    return self._names.get(self.NAME_CODES[name], default)

  def GetNames(self):
    return ['%d: %s' % (k, v) for k,v in sorted(self._names.iteritems())]


class Report(object):
  """Base class for report generator classes."""

  def __init__(self, font):
    self.font = font

  def Report(self, xetex):
    if xetex:
      return self.Xetex()
    else:
      return self.Plaintext()

  def Plaintext(self):
    pass

  def Xetex(self):
    return self.TETEX_HEADER + self.XetexBody() + self.TETEX_FOOTER




class UnicodeCoverageReport(Report):
  TETEX_HEADER = r'''
    \begin{longtable}[l]{|r|l|p{0.6\textwidth}|}
    \hline
    \endhead
    \hline
    \endfoot
  '''
  TETEX_FOOTER = r'\end{longtable}'

  NAME = 'Unicode Coverage'

  def Plaintext(self):
    data = ''
    for code, name in self.font.GetUnicodeCharacters():
      try:
        uniname = unicodedata.name(unichr(code))
      except ValueError:
        uniname = ''
      data += "U+%04d %s %s\n" % (code, name, uniname)
    return data

  def XetexBody(self):
    data = ''
    prevcode = 0
    for code, name in self.font.GetUnicodeCharacters():
      try:
        uniname = unicodedata.name(unichr(code))
      except ValueError:
        uniname = ''
      if code - prevcode > 1:
        data += '\hline\n'
      prevcode = code
      data += '\\texttt{%04X} & {\\customfont\\symbol{%d}} & {\\small %s}\\\\\n' % (code, code, uniname)
    return data

class GlyphsReport(Report):
  NAME = 'Glyphs'

  TETEX_HEADER = r'''
    \begin{longtable}[l]{|r|l|l|r|r|r|}
    \hline
    Index & Glyph & Name & Adv. Width & lsb & Class \\
    \hline
    \endhead
    \hline
    \endfoot
  '''

  TETEX_FOOTER = r'\end{longtable}'

  def Plaintext(self):
    data = ''
    for idx, glyph in enumerate(self.font.GetGlyphs()):
      data += "%6d %s\n" % (idx, glyph.name)
    return data

  def XetexBody(self):
    data = ''
    for idx, glyph in enumerate(self.font.GetGlyphs()):
      data += "%d & {\customfont\XeTeXglyph %d} & %s & %d & %d & %d\\\\\n" % (
          idx, idx, glyph.name.replace('_', r'\_'),
          glyph.advanceWidth, glyph.lsb, glyph.classDef)
    return data


class SummaryReport(Report):
  TETEX_HEADER = r'''
    \begin{tabular}[l]{|l|r|}
    \hline
  '''

  TETEX_FOOTER = r'\hline\end{tabular}'

  NAME = 'Summary'

  def Plaintext(self):
    return '\n'.join('%20s: %d' % x for x in self._GetData())

  def XetexBody(self):
    return '\n'.join('%s & %d \\\\' % x for x in self._GetData())

  def _GetData(self):
    glyphs = self.font.GetGlyphs()
    count = {2: 0, 3: 0, 4: 0}
    for x in glyphs:
      count[x.classDef] = count.get(x.classDef, 0) + 1
    return (('Unicode characters', len(self.font.GetUnicodeCharacters())),
            ('Glyphs', len(glyphs)),
            ('Ligature glyphs', count[2]),
            ('Mark glyphs', count[3]),
            ('Component glyphs', count[4]))


class Envelope(Report):
  """Reporting entry point.

  Combines all reports into a single document.
  """
  TETEX_HEADER = r'''
    \documentclass[10pt]{article}
    \usepackage{fontspec}
    \usepackage{longtable}
    \usepackage{hyperref}
    \hypersetup{
        colorlinks,
        citecolor=black,
        filecolor=black,
        linkcolor=black,
        urlcolor=black
    }
    \begin{document}
  '''

  TETEX_FOOTER = r'\end{document}'

  FONT_TEMPLATE = r'''
    \newfontface\customfont[Path = %s/, Color = 0000AA]{%s}
  '''

  KNOWN_REPORTS = (SummaryReport, UnicodeCoverageReport, GlyphsReport)

  def Plaintext(self):
    data = ''
    for report in self.KNOWN_REPORTS:
      try:
        data += report.NAME.upper() + '\n'
      except AttributeError:
        pass
      data += report(self.font).Plaintext() + '\n\n'
    return data

  def XetexBody(self):
    data = self.FONT_TEMPLATE % os.path.split(self.font.filename)
    data += '\\title{%s}\n' % self.font.GetTitle()
    data += '\\author{%s}\n' % self.font.GetAuthor()
    data += '\\renewcommand\\today{%s}' % self.font.GetName('Version', 'Unknown version')
    data += '\\maketitle\n\\tableofcontents\n'
    for report in self.KNOWN_REPORTS:
      try:
        data += '\\section{%s}\n' % report.NAME
      except AttributeError:
        pass
      data += report(self.font).Xetex() + '\n'
    return data


def main(argv):
  if len(argv) == 3:
    infile = argv[1]
    outfile = argv[2]
  elif len(argv) == 2:
    infile = argv[1]
    outfile = None
  else:
    print "Usage: %s infile [outfile]" % argv[0]
    sys.exit(-1)

  font = FontFile(infile)
  envelope = Envelope(font)
  if outfile:
    name, ext = os.path.splitext(outfile)
    tofile = outfile
    xetex = False
    if ext in ('.pdf', '.tex'):
      xetex = True
      if ext == '.pdf':
        tofile = name + '.tex'

    with open(tofile, 'w') as f:
      f.write(envelope.Report(xetex).encode('utf-8'))
    if ext == '.pdf':
      # Call twice to let longtable package calculate
      # column width correctly
      subprocess.check_call(['xelatex', tofile])
      subprocess.check_call(['xelatex', tofile])
  else:
    print envelope.Report(xetex).encode('utf-8')


if __name__ == '__main__':
  main(sys.argv)
