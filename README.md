# FontReport

FontReport is a tool to present features of TTF or OTF font file in a form of PDF or plain-text report.

## Requirements

FontReport uses xetex to generate PDF from .tex source. Please install TeX Live using
following installation instructions for your platform.

### Ubuntu

apt-get install python-setuptools texlive-xetex texlive-latex-recommended

### Other

See http://www.tug.org/texlive/

## Installation

    sudo python setup.py install

## Usage

### Generate a PDF report

    fontreport NotoSansMalayalam-Regular.ttf Malayalam.pdf

### Generate a plain-text report

    fontreport NotoSansMalayalam-Regular.ttf Malayalam.txt

## Report Format
Report consist of several tables:

*  Unicode coverage
*  Glyphs coverage
*  OpenType Features
*  Ligatures
*  Substitutions
