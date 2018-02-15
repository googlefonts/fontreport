#!/usr/bin/python
#
# Copyright 2015 Google Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Font reporting tool.

This command-line tool is able to generate various reports about the internals
of the given TrueType or OpenType font, such as:
  - Supported unicode characters
  - Supported glyphs

Reports are generated in PDF format and contain font-specific rendering of
the glyphs supported by the font.

"""
import os
import random
import re
import subprocess
import sys
import unicodedata

import ngram

from fontTools.ttLib import TTFont
import version


class Glyph(object):
  """Representation of a single glyph.

  Contains glyph properties collected from different tables of a font and
  queried by report classes.
  """

  def __init__(self, name):
    self.name = name
    self.advance_idth = None
    self.lsb = None
    self.class_def = 0
    self.sequences = None
    self.alternates = None
    self.chars = []
    self.index = -1


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
    self.ttf = TTFont(filename, fontNumber=-1, lazy=False)
    self._names = {}
    self.chars = {}
    self._glyphsmap = {}
    self.glyphs = []
    self.features = {}
    self.caret_list = {}
    self.substitutes = set()
    self.caret_list = {}
    self._ParseNames()
    self._ParseCmap()
    self._ParseGSUB()
    self._ParseGlyphs()

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
      return '%s (%s)' % (author, manufacturer)
    elif author:
      return author
    elif manufacturer:
      return manufacturer
    else:
      return 'Author is not set'

  def GetFeaturesByTable(self):
    mapping = {}
    for key, scripts in self.features.iteritems():
      feature, tables = key
      for table in tables:
        if table not in mapping:
          mapping[table] = set()
        mapping[table].add((feature, tuple(sorted(scripts))))
    return mapping

  def _ParseCmap(self):
    if 'cmap' in self.ttf:
      for table in self.ttf['cmap'].tables:
        if table.isUnicode():
          for code, name in table.cmap.items():
            self.chars[code] = name

  def _ParseGSUB(self):
    if 'GSUB' not in self.ttf:
      return

    scripts = [set() for unused_x
               in xrange(self.ttf['GSUB'].table.FeatureList.FeatureCount)]
    # Find scripts defined in a font
    for script in self.ttf['GSUB'].table.ScriptList.ScriptRecord:
      if script.Script.DefaultLangSys:
        for idx in script.Script.DefaultLangSys.FeatureIndex:
          scripts[idx].add(script.ScriptTag)
      for lang in script.Script.LangSysRecord:
        for idx in lang.LangSys.FeatureIndex:
          scripts[idx].add(script.ScriptTag + '-' + lang.LangSysTag)

    # Find all featrures defined in a font
    for idx, feature in enumerate(
        self.ttf['GSUB'].table.FeatureList.FeatureRecord):
      key = (feature.FeatureTag, tuple(feature.Feature.LookupListIndex))
      if key not in self.features:
        self.features[key] = set()
      self.features[key].update(scripts[idx])

    for idx, lookup in enumerate(self.ttf['GSUB'].table.LookupList.Lookup):
      for sub in lookup.SubTable:
        if sub.LookupType == 1:
          for k, v in sub.mapping.iteritems():
            self.substitutes.add(((k,), ((v,),), idx, 1))
        elif sub.LookupType == 2:
          for k, v in sub.mapping.iteritems():
            self.substitutes.add(((k,), (tuple(v),), idx, 2))
        elif sub.LookupType == 3:
          for k, v in sub.alternates.iteritems():
            self.substitutes.add(((k,), tuple((x,) for x in v), idx, 3))
        elif sub.LookupType == 4:
          for key, value in sub.ligatures.iteritems():
            for component in value:
              sequence = tuple([key] + component.Component)
              glyph = component.LigGlyph
              self.substitutes.add((sequence, ((glyph,),), idx, 4))
        else:
          print 'Lookup table %d: type %s not yet supported.' % (
              idx, sub.LookupType)

  def _ParseGlyphs(self):
    """Fetch available glyphs."""
    class_defs = {}
    class_names = {2: 'ligature', 3: 'mark', 4: 'component'}
    metrics = {}
    if 'GDEF' in self.ttf:
      class_defs = self.ttf['GDEF'].table.GlyphClassDef.classDefs
      caret_list = self.ttf['GDEF'].table.LigCaretList
      if caret_list:
        carets = [tuple(str(x.Coordinate) for x in y.CaretValue)
                  for y in caret_list.LigGlyph]
        self.caret_list = dict(zip(caret_list.Coverage.glyphs, carets))

    if 'hmtx' in self.ttf:
      metrics = self.ttf['hmtx'].metrics

    for idx, name in enumerate(self.ttf.getGlyphOrder()):
      glyph = Glyph(name)
      glyph.index = idx
      glyph.advance_width, glyph.lsb = metrics.get(name, [None, None])
      glyph.class_def = class_defs.get(name, 0)
      glyph.class_name = class_names.get(glyph.class_def, None)
      self.glyphs.append(glyph)
      self._glyphsmap[name] = glyph
    for k, v in self.chars.iteritems():
      try:
        self._glyphsmap[v].chars.append(k)
      except KeyError:
        print '%s is mapped to non-existent glyph %s' % (k, v)

  def GetName(self, name, default=None):
    return self._names.get(self.NAME_CODES[name], default)

  def GetNames(self):
    return ['%d: %s' % (k, v) for k, v in sorted(self._names.iteritems())]

  def GetGlyph(self, name, default=None):
    return self._glyphsmap.get(name, default)


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
    body = self.XetexBody()
    if body:
      body = self.TETEX_HEADER + body + self.TETEX_FOOTER
    return body


class UnicodeCoverageReport(Report):
  """Report font unicode coverage."""

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
      data += '  U+%04X %-30s %s\n' % (code, name, uniname)
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
        gaps = len([x for x in  xrange(prevcode + 1, code)
                    if unicodedata.category(unichr(x))[0] != 'C'])
        if gaps:
          data += ('\\rowcolor{missing}\\multicolumn{3}{|c|}'
                   '{\\small %d visible characters not mapped to glyphs} \\\\\n') % (gaps)
      prevcode = code
      data += ('\\texttt{%04X} & {\\customfont\\symbol{%d}} &'
               '{\\small %s}\\\\\n') % (code, code, uniname)
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
    for glyph in self.font.glyphs:
      data += '%6d %-30s %6d %6d %3d\n' % (
          glyph.index, glyph.name, glyph.advance_width,
          glyph.lsb, glyph.class_def)
    return data

  def XetexBody(self):
    data = ''
    uni = {}
    for code, name in self.font.chars.iteritems():
      if name not in uni:
        uni[name] = []
      uni[name].append(code)
    for glyph in self.font.glyphs:
      if glyph.class_name:
        data += '\\rowcolor{%s}\n' % glyph.class_name
      if glyph.name in uni:
        chars = ', '.join('u%04X' % x for x in glyph.chars)
      else:
        chars = ''
      data += '%d & %s & %s & %d & %d & %d & %s\\\\\n' % (
          glyph.index, TexGlyph(glyph), TexEscape(glyph.name),
          glyph.advance_width, glyph.lsb, glyph.class_def, chars)
    return data


class LigaturesReport(Report):
  """Report ligatures."""
  TETEX_HEADER = r'''
    \begin{longtable}[l]{|l|l|l|p{.5\textwidth}|}
    \hline
    \rowcolor{header}
    Glyph & Caret Positions & Sequences \\
    \hline
    \endhead
    \hline
    \endfoot
  '''
  TETEX_FOOTER = r'\end{longtable}'

  NAME = 'Ligatures with Carets'

  def Plaintext(self):
    data = ''
    for glyph, caret_list in sorted(self.font.caret_list.iteritems()):
      data += '%-10s\t%s\t%s\n' % (
          glyph, ', '.join(caret_list), '-')
    return data

  def XetexBody(self):
    data = ''
    for glyph, caret_list in sorted(self.font.caret_list.iteritems()):
      coords = ', '.join(str(x) for x in caret_list)
      data += '%s(%s) & %s & %s \\\\\n' % (
          TexGlyph(self.font.GetGlyph(glyph)), TexEscape(glyph),
          coords, '-')
    return data


class ChartReport(Report):
  """Report glyphs in a format of Unicode charts."""
  ROWS = 16
  COLUMNS = 16
  TETEX_HEADER = r'''
    \newcommand\cell[2]{\begin{tabular}[c]{@{}c@{}}
      \customfont{\symbol{#1}}\\ \tiny{#2}\end{tabular}}
  '''
  CHART_HEADER = r'''
    \subsection{%%s}
    \begin{tabular}{r|%s|}
  ''' % '|'.join(('c',) * COLUMNS)
  CHART_FOOTER = r'\end{tabular}\pagebreak'
  TETEX_FOOTER = ''

  NAME = 'Block'

  def Plaintext(self):
    data = ''
    return data

  def GenerateBlocks(self, rows, cols):
    def NewBlock():
      return [False for x in xrange(rows * cols)]
    current_block = -1
    block = None
    span = rows * cols
    for code in sorted(self.font.chars):
      blockno = code / span
      offset = code % span
      if current_block != blockno:
        if block:
          yield current_block * span, block
        block = NewBlock()
        current_block = blockno
      block[offset] = True
    if block:
      yield current_block * span, block

  def XetexBody(self):
    data = ''
    for idx, block in self.GenerateBlocks(self.ROWS, self.COLUMNS):
      subtitle = '%04X - %04X' % (idx,
                                  idx + self.ROWS * self.COLUMNS - 1)
      data += self.CHART_HEADER % subtitle
      data += '&' + ' & '.join('\\multicolumn{1}{c%s}{%03X}' % (
          '|' if x == self.COLUMNS -1 else '',
          idx / self.COLUMNS + x, ) for x in range(self.COLUMNS))
      data += '\\\\\n\\cline{2-17}\n'
      for row_idx in range(self.ROWS):
        row = ['\small{%X}' % row_idx]
        for col_idx in range(self.COLUMNS):
          offset = col_idx * self.ROWS + row_idx
          code = idx + offset
          if block[offset]:
            cell = '\\cell{%d}{%04X}' % (code, code)
          else:
            cell = '\\cellcolor{red}{\\cell{0}{%04X}}' % (code)
          row.append(cell)
        data += ' & '.join(row) + '\\\\\n\\cline{2-17}\n'
      data += self.CHART_FOOTER
    return data


class GridReport(Report):
  """Report glyphs in a grid."""
  TETEX_HEADER = r'''
    \newcommand\gl[1]{\tiny{#1}}
    \newcommand\glyph[3]{\Large\customfont{\textcolor{gray}{#1}}{\textcolor{blue}{#2}}{\textcolor{gray}{{#3}}}}
    \begin{longtable}[l]{|c|c|c|c|c|c|c|c|}
    \hline
    \endhead
    \hline
    \endfoot
  '''
  TETEX_FOOTER = r'\end{longtable}'
  VARIANT_COLOR = 'yellow'
  ROW_LENGTH = 8

  NAME = 'Characters'

  def Plaintext(self):
    data = ''
    return data

  def GetVariantsMap(self):
    features_mapping = self.font.GetFeaturesByTable()
    alt_map = {}
    prefixes = []
    suffixes = []
    for src, dest, table, kind in self.font.substitutes:
      if kind == 1 or kind == 3:
        glyph = self.font.GetGlyph(src[0])
        if glyph.chars:
          key = glyph.chars[0]
          if not key in alt_map:
            alt_map[key] = []
          if table in features_mapping:
            label = (x[0] for x in features_mapping[table]).next()
          else:
            label = 'var'
          for g in dest[0]:
            alt_map[key].append((g, label))
            if label in ('medi', 'fina'):
              prefixes.append(g)
            if label in ('medi', 'init'):
              suffixes.append(g)
    return (alt_map, prefixes, suffixes)

  def XetexBody(self):
    def Cell(text, color=None):
      return '\cellcolor{%s!10}{%s}' % (color, text) if color else text

    alt_map, prefixes, suffixes = self.GetVariantsMap()
    mapped = set()
    scripts = {}
    unimap = {}
    grid_data = []
    for code, glyph in sorted(self.font.chars.iteritems()):
      char = unichr(code)
      name = unicodedata.name(char, '').lower()
      category = unicodedata.category(char)
      prefix, suffix = None, None
      if category[0] == 'L':
        # Python unicodedata package does not contain script
        # data for characters. Use a hack for a proof-of-concept now.
        # TODO: Use unicode script data if script-based candidates
        # selection is proven to be useful.
        script = name.split()[0]
        if script not in scripts:
          scripts[script] = []
        scripts[script].append(code)
        unimap[code] = (script, category)
      if unicodedata.bidirectional(char) == 'AL':
        m = re.search(r'(isol|fina|medi|init)[a-z]* form', name)
        label = m.group(1) if m else 'isol'
      else:
        label = None
      grid_data.append(('u%04X' % code, code, glyph, label))
      mapped.add(glyph)
      for item in sorted(alt_map.get(code, ()), key=lambda x:x[1]):
        glyph, label = item
        if glyph not in mapped:
          mapped.add(glyph)
          grid_data.append(('u%04X, %s' % (code, TexEscape(label)), code, glyph, label))
    for glyph in self.font.glyphs:
      if glyph.name not in mapped:
        grid_data.append((TexEscape(glyph.name[:10]), None, glyph.name, None))

    ngrams = []
    for item in ngram.NGRAMS:
      if all(ord(x) in unimap for x in item):
        ngrams.append(item)
    col = 0
    data = ''
    labels, glyphs = [], []
    for label, code, glyph, other in grid_data:
      suffix, prefix = None, None
      if code and code in unimap:
        script, category = unimap[code]
        # TODO: get rid of ad hoc arabic handling
        if script != 'arabic':
          match = sorted((x for x in ngrams if x[0] == unichr(code)),
                         key=lambda k: tuple(x.isalpha() for x in k),
                         reverse=True)
          if match:
            prefix = self.font.chars[ord(match[0][1])]
            suffix = self.font.chars[ord(match[0][2])]
          else:
            candidates = scripts[script]
            prefix = self.font.chars[random.choice(scripts[script])]
            suffix = self.font.chars[random.choice(scripts[script])]
      color = self.VARIANT_COLOR if ',' in label else None
      labels.append(Cell('\\gl{%s}' % label, color))
      if not prefix and other not in ('fina', 'isol') and prefixes:
        prefix = random.choice(prefixes)
      if not suffix and other not in ('init', 'isol') and suffixes:
        suffix = random.choice(suffixes)
      if code and not other:
        content = r'\symbol{%s}' % code
      else:
        content = r'{\XeTeXglyph %d}' % self.font.GetGlyph(glyph).index
      formatted = '{\\glyph{%s}{%s}{%s}}' % (
          (r'{\XeTeXglyph %d}' % self.font.GetGlyph(prefix).index) if prefix else '',
          content,
          (r'{\XeTeXglyph %d}' % self.font.GetGlyph(suffix).index) if suffix else ''
      )
      glyphs.append(Cell(formatted, color))
      col = (col + 1) % self.ROW_LENGTH
      if not col:
        data += ' & '.join(glyphs) + '\\\\\n'
        data += ' & '.join(labels) + '\\\\\n\\hline\n'
        labels, glyphs = [], []
    return data


class SubstitutionsReport(Report):
  """Report GSUB substitutions."""
  TETEX_HEADER = r'''
    \begin{longtable}[l]{|c|c|p{.7\textwidth}|}
    \hline
    \rowcolor{header}
    Table & Feature & Substitution  \\
    \hline
    \endhead
    \hline
    \endfoot
  '''
  TETEX_FOOTER = r'\end{longtable}'

  NAME = 'GSUB Substitutions'

  def Plaintext(self):
    data = ''
    for table, features, src, dest in self.GetTableItems():
      data += '%4d\t%-20s\t%s\n' % (
          table,
          ', '.join(features),
          ' '.join(src) + ' -> ' +
          ', '.join(' '.join(y) for y in dest))
    return data

  def XetexBody(self):
    features_mapping = self.font.GetFeaturesByTable()
    data = ''
    for table, features, src, dest in self.GetTableItems():
      sequence = ' '.join('%s(%s)' % (
          TexGlyph(self.font.GetGlyph(x)),
          TexEscape(x)) for x in src)
      alternates = ', '.join(' '.join('%s(%s)' % (
          TexGlyph(self.font.GetGlyph(x)),
          TexEscape(x)) for x in y) for y in dest)
      data += '%d & %s & %s$\\rightarrow$%s \\\\\n' % (
          table, ', '.join(features), sequence, alternates)
    return data

  def GetTableItems(self):
    features_mapping = self.font.GetFeaturesByTable()
    for src, dest, table, unused_kind in sorted(
        self.font.substitutes, key=lambda x: (x[2], x[0])):
      if table in features_mapping:
        features = sorted(set(k for k, v in features_mapping[table]))
      else:
        features = ()
      yield (table, features, src, dest)


class FeaturesReport(Report):
  """Report OpenType features."""
  TETEX_HEADER = r'''
    \begin{longtable}[l]{|l|p{.2\textwidth}|p{.4\textwidth}|l|}
    \hline
    \rowcolor{header}
    Feature & Description & Scripts & Lookup Tables \\
    \hline
    \endhead
    \hline
    \endfoot
  '''
  TETEX_FOOTER = r'\end{longtable}'

  NAME = 'OpenType Features'

  KNOWN_FEATURES = {
      'aalt': 'All Alternates',
      'case': 'Case-Sensitive Forms',
      'ccmp': 'Glyph Composition/Decomposition',
      'c2sc': 'Small Capitals From Capitals',
      'dlig': 'Discretionary Ligatures',
      'fina': 'Terminal Forms',
      'frac': 'Fractions',
      'fwid': 'Full Width',
      'hlig': 'Historical Ligatures',
      'hwid': 'Half Width',
      'init': 'Initial Forms',
      'isol': 'Isolated Forms',
      'liga': 'Standard Ligatures',
      'lnum': 'Lining Figures',
      'locl': 'Localized Forms',
      'medi': 'Medial Forms',
      'onum': 'Oldstyle Figures',
      'pnum': 'Proportional Figures',
      'pwid': 'Proportional Width',
      'rtla': 'Right-to-left alternates',
      'rlig': 'Required Ligatures',
      'rtlm': 'Right-toleft mirrored forms',
      'salt': 'Stylistic Alternates',
      'sinf': 'Scientific Inferiors',
      'smcp': 'Small Capitals',
      'ss01': 'Stylistic Set 1',
      'ss02': 'Stylistic Set 2',
      'ss03': 'Stylistic Set 3',
      'subs': 'Subscript',
      'sups': 'Superscript',
      'tnum': 'Tabular Figures',
      'vert': 'Vertical Writing',
      'vrt2': 'Vertical Alternates and Rotation',
      'zero': 'Slashed Zero',
  }

  def Plaintext(self):
    data = ''
    for key, scripts in sorted(self.font.features.iteritems()):
      feature, tables = key
      scriptlist = ', '.join(x for x in scripts if x)
      data += '%4s\t%s\t%s\t%s\n' % (
          feature, self.KNOWN_FEATURES.get(feature, 'N/A'),
          scriptlist, ', '.join(str(x) for x in tables))
    return data

  def XetexBody(self):
    data = ''
    for key, scripts in sorted(self.font.features.iteritems()):
      feature, tables = key
      scriptlist = ', '.join(x.strip() for x in sorted(scripts) if x)
      data += '%s & %s & %s & %s  \\\\\n' % (
          feature, self.KNOWN_FEATURES.get(feature, 'N/A'),
          scriptlist, ', '.join(str(x) for x in tables))
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
    data = '\n'.join('%s & %d \\\\' % x for x in self._GetData())
    return data

  def _GetData(self):
    glyphs = self.font.glyphs
    count = {2: 0, 3: 0, 4: 0}
    for x in glyphs:
      count[x.class_def] = count.get(x.class_def, 0) + 1
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
    \usepackage[top=.25in, bottom=.25in, left=.5in, right=.5in]{geometry}
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
    \newfontface\customfont[Path = %s/]{%s}
  '''
  #  \newfontface\customfont[Path = %s/, Color = 0000AA]{%s}

  KNOWN_REPORTS = (SummaryReport, ChartReport, UnicodeCoverageReport,
                   GlyphsReport, FeaturesReport,
                   LigaturesReport, SubstitutionsReport)

  def Plaintext(self):
    data = ''
    for report in self.KNOWN_REPORTS:
      try:
        content = report(self.font).Plaintext()
        if content:
          data += report.NAME.upper() + '\n' + content + '\n\n'
      except AttributeError as e:
        pass
    return data

  def XetexBody(self):
    data = self.FONT_TEMPLATE % os.path.split(self.font.filename)
    data += '\\title{%s}\n' % TexEscape(self.font.GetTitle())
    data += '\\author{%s}\n' % TexEscape(self.font.GetAuthor())
    data += '\\renewcommand\\today{%s}' % TexEscape(
        self.font.GetName('Version', 'Unknown version'))
    data += '\\maketitle\n\\tableofcontents\n'
    for report in self.KNOWN_REPORTS:
      try:
        content = report(self.font).Xetex()
        if content:
          data += '\\section{%s}\n%s\n' % (report.NAME, content)
      except ValueError as e:
        print e
        pass
    return data


def TexGlyph(glyph):
  return '{\\customfont\\XeTeXglyph %d}' % glyph.index


def TexEscape(name):
  return re.sub(r'([_#&{}\[\]])', r'\\\1', name)


def main():
  argv = sys.argv
  if len(argv) == 3:
    infile = argv[1]
    outfile = argv[2]
  elif len(argv) == 2:
    infile = argv[1]
    if infile in ('--version', '-v'):
      print('FontReport version %s' % version.__version__)
      sys.exit(0)
    outfile = None
  else:
    print 'Usage: %s infile [outfile]' % argv[0]
    sys.exit(-1)

  font = FontFile(os.path.abspath(infile))
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
    print envelope.Report(False).encode('utf-8')


if __name__ == '__main__':
  main()
