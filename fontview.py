# coding = utf-8
"""Font internals reporting tool.

This command-line tool is able to generate various reports about the internals
of the given TrueType or OpenType font, such as:
  - Supported unicode characters
  - Supported glyphs

Reports are generated in PDF format and contain font-specific rendering of
the glyphs supported by the font.

"""
import os
import sys
import subprocess
import unicodedata

from fontTools.ttLib import TTFont, TTLibError

class FontFile(object):
  """Representation of font metadata.

  Provides high-level API on top of FontTools library that is used by
  report generators.
  """
  def __init__(self, filename):
    self.filename = filename
    self.ttf = TTFont(filename, fontNumber=-1, lazy=True)

  def GetTables(self):
    return sorted(self.ttf.reader.keys())

  def GetUnicodeCharacters(self):
    chars = []
    if 'cmap' in self.ttf:
      for table in self.ttf['cmap'].tables:
        for code, name in table.cmap.items():
          chars.append((code, name))
    return sorted(chars)

  def GetGlyphs(self):
    """Fetch available glyph names."""
    if 'glyf' in self.ttf:
      return self.ttf['glyf'].glyphOrder
    else:
      return []

  def GetNames(self):
    names = []
    if 'name' in self.ttf:
      for name in self.ttf['name'].names:
        if name.isUnicode():
          text = name.string.decode('utf-16be')
        else:
          text = name.string.decode('latin1')
        names.append(text)
    return names


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
    \begin{longtable}{|l|l|l|}
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
    for code, name in self.font.GetUnicodeCharacters():
      try:
        uniname = unicodedata.name(unichr(code))
      except ValueError:
        uniname = ''
      data += "{\customfont\symbol{%d}} & %s & %s\\\\\n" % (code, name, uniname)
    return data

class GlyphsReport(Report):
  NAME = 'Glyphs'

  TETEX_HEADER = r'''
    \begin{longtable}{|l|l|}
    \hline
    \endhead
    \hline
    \endfoot
  '''

  TETEX_FOOTER = r'\end{longtable}'

  def Plaintext(self):
    data = ''
    for idx, name in enumerate(self.font.GetGlyphs()):
      data += "%6d %s\n" % (idx, name)
    return data

  def XetexBody(self):
    data = ''
    for idx, name in enumerate(self.font.GetGlyphs()):
      data += "{\customfont\XeTeXglyph %d} & %s \\\\\n" % (idx, name)
    return data


class NamesReport(Report):
  NAME = 'General info'
  def Plaintext(self):
    return '\n'.join(self.font.GetNames())

  def Xetex(self):
    return '\\\\\n'.join(self.font.GetNames() + [''])

class Envelope(Report):
  """Reporting entry point.

  Combines all reports into a single document.
  """
  TETEX_HEADER = r'''
    \documentclass[10pt]{article}
    \usepackage{fontspec}
    \usepackage{longtable}
    \begin{document}
  '''

  TETEX_FOOTER = r'\end{document}'

  FONT_TEMPLATE = r'''
    \newfontface\customfont[Path = %s/, Color = 0000AA]{%s}
  '''

  KNOWN_REPORTS = (NamesReport, UnicodeCoverageReport, GlyphsReport)

  def Plaintext(self):
    data = ''
    for report in self.KNOWN_REPORTS:
      try:
        data += report.NAME + '\n'
      except AttributeError:
        pass
      data += report(self.font).Plaintext() + '\n'
    return data

  def XetexBody(self):
    data = self.FONT_TEMPLATE % os.path.split(self.font.filename)
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
      subprocess.check_call(['xelatex', tofile])
  else:
    print envelope.Report(xetex).encode('utf-8')


if __name__ == '__main__':
  main(sys.argv)
