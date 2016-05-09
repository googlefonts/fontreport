# FontReport

FontReport is a tool that allows the user to generate a report about a given
font (TTF or OTF) listing its features in the plain-text (default) or PDF
format. It is useful in quickly identifying such things as the Unicode coverage
of the font, what glyphs are in it, what Open Type features it supports,
available ligatures, and glyph substitutions.

## Requirements

Install TeX Live following installation instructions for your platform. (Text
Live is needed because FontReport uses xetex to generate PDF from .tex source.)
Also, make sure python setuptools are installed.

### Ubuntu

apt-get install python-setuptools texlive-xetex texlive-latex-recommended

### Mac OS X
Setuptools are pre-installed for MacOS-X. To set up TeX Live, download and run
MacTeX installation package at http://tug.org/cgi-bin/mactex-download/MacTeX.pkg

### Other platforms

See http://www.tug.org/texlive/

## Installation

    sudo python setup.py install

## Usage samples

### Generate a PDF report

    fontreport NotoSansMalayalam-Regular.ttf Malayalam.pdf

### Generate a plain-text report

    fontreport NotoSansMalayalam-Regular.ttf Malayalam.txt

### Generate a plain-text report

    fontreport NotoSansMalayalam-Regular.ttf Malayalam.txt

### Find out if a given Unicode character is included in what fonts in a
directory

    for file in *.ttf; do fontreport "$file" | grep U+XXXX > temp.txt && echo
$file && cat temp.txt; done > summary.txt

### Find language-specific substitutions defined in a font
fontreport NotoKufiArabic-Regular.ttf | grep locl
locl  Localized Forms arab-URD  1
   1  locl                  uni0667 -> uni06F7.urdu
   1  locl                  uni06F4 -> uni06F4.urdu
   1  locl                  uni06F6 -> uni0666


## Report Content
Currently a report consists of several tables:

*  Unicode coverage
*  Glyphs coverage
*  OpenType Features
*  Ligatures
*  Substitutions

