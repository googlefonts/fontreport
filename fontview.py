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
    self.classDef = 0
    self.caretList = None

  def isLigature(self):
    return self.caretList or self.classDef == 2


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
    self.chars = {}
    self.glyphs = []
    self._ParseNames()
    self._ParseGlyphs()
    self._ParseCmap()

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

  def _ParseCmap(self):
    if 'cmap' in self.ttf:
      for table in self.ttf['cmap'].tables:
        if table.isUnicode():
          for code, name in table.cmap.items():
            self.chars[code] = name

  def _ParseGlyphs(self):
    """Fetch available glyphs."""
    classDefs = {}
    classNames = {2:'ligature', 3:'mark', 4: 'component' }
    caretList = {}
    metrics = {}
    if 'GDEF' in self.ttf:
      classDefs = self.ttf['GDEF'].table.GlyphClassDef.classDefs
      fontCaretList = self.ttf['GDEF'].table.LigCaretList
      if fontCaretList:
        carets = [tuple(x.Coordinate for x in y.CaretValue) for y in fontCaretList.LigGlyph]
        caretList = dict(zip(fontCaretList.Coverage.glyphs, carets))

    if 'hmtx' in self.ttf:
      metrics = self.ttf['hmtx'].metrics

    for name in self.ttf.getGlyphOrder():
      glyph = Glyph(name)
      glyph.advanceWidth, glyph.lsb = metrics.get(name, [None, None])
      glyph.classDef = classDefs.get(name, 0)
      glyph.className = classNames.get(glyph.classDef, None)
      glyph.caretList = caretList.get(name, ())
      self.glyphs.append(glyph)

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
    \definecolor{missing}{gray}{.95}
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
    for code, name in sorted(self.font.chars.iteritems()):
      try:
        uniname = unicodedata.name(unichr(code))
      except ValueError:
        uniname = ''
      data += "U+%04d %s %s\n" % (code, name, uniname)
    return data

  def XetexBody(self):
    data = ''
    prevcode = 0
    for code in sorted(self.font.chars):
      try:
        uniname = unicodedata.name(unichr(code))
      except ValueError:
        uniname = ''
      if code - prevcode > 1:
        data += '\\rowcolor{missing}\\multicolumn{3}{|c|}{\\small %d codepoints missing} \\\\\n' % (code - prevcode + 1)
      prevcode = code
      data += '\\texttt{%04X} & {\\customfont\\symbol{%d}} & {\\small %s}\\\\\n' % (code, code, uniname)
    return data

class GlyphsReport(Report):
  NAME = 'Glyphs'

  TETEX_HEADER = r'''
    \definecolor{ligature}{RGB}{255, 255, 200}
    \definecolor{mark}{RGB}{255, 200, 255}
    \definecolor{component}{RGB}{200, 255, 255}
    \begin{longtable}[l]{|r|l|l|r|r|r|p{.2\textwidth}|}
    \hline
    \rowcolor{header}
    Index & Glyph & Name & Adv. Width & lsb & Class & Chars\\
    \hline
    \endhead
    \hline
    \endfoot
  '''

  TETEX_FOOTER = r'\end{longtable}'

  def Plaintext(self):
    data = ''
    for idx, glyph in enumerate(self.font.glyphs):
      data += "%6d %-30s %6d %6d %3d\n" % (idx, glyph.name, glyph.advanceWidth, glyph.lsb, glyph.classDef)
    return data

  def XetexBody(self):
    data = ''
    uni = {}
    for code, name in self.font.chars.iteritems():
      if name not in uni:
        uni[name] = []
      uni[name].append(code)
    for idx, glyph in enumerate(self.font.glyphs):
      if glyph.className:
        data += '\\rowcolor{%s}\n' % glyph.className
      if glyph.name in uni:
        chars = ', '.join('u%04X' % x for x in uni[glyph.name])
      else:
        chars = ''
      data += "%d & {\customfont\XeTeXglyph %d} & %s & %d & %d & %d & %s\\\\\n" % (
          idx, idx, TexEscape(glyph.name),
          glyph.advanceWidth, glyph.lsb, glyph.classDef, chars)
    return data

class LigaturesReport(Report):
  TETEX_HEADER = r'''
    \begin{longtable}[l]{|l|l|l|}
    \hline
    \rowcolor{header}
    Glyph & Name & Caret Positions \\
    \hline
    \endhead
    \hline
    \endfoot
  '''
  TETEX_FOOTER = r'\end{longtable}'

  NAME = 'Ligatures'

  def Plaintext(self):
    data = ''
    for glyph in self.font.glyphs:
      if glyph.isLigature():
        data += "%-30s\t%s\n" % (glyph.name, glyph.caretList)
    return data

  def XetexBody(self):
    data = ''
    for idx, glyph in enumerate(self.font.glyphs):
      if glyph.isLigature():
        coords = ', '.join(str(x) for x in glyph.caretList) if glyph.caretList else ''
        data += '{\customfont\XeTeXglyph %d} & %s & %s\\\\\n' % (idx, TexEscape(glyph.name), coords)
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
    glyphs = self.font.glyphs
    count = {2: 0, 3: 0, 4: 0}
    for x in glyphs:
      count[x.classDef] = count.get(x.classDef, 0) + 1
    return (('Unicode characters', len(self.font.chars)),
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
    \usepackage[table]{xcolor}
    \definecolor{header}{gray}{.9}
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

  KNOWN_REPORTS = (SummaryReport, UnicodeCoverageReport, GlyphsReport, LigaturesReport)

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


def TexEscape(name):
  return name.replace('_', r'\_').replace('#', r'\#')


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
