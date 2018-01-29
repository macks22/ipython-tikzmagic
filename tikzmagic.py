# -*- coding: utf-8 -*-

# -----------------------------------------------------------------------------
#  Copyright (C) 2013 The IPython Development Team
#
#  Distributed under the terms of the BSD License.  The full license is in
#  the file COPYING, distributed as part of this software.
# -----------------------------------------------------------------------------

"""
=========
tikzmagic
=========

Magics for generating figures with TikZ.

.. note::

  ``TikZ`` and ``LaTeX`` need to be installed separately.

Usage
=====

``%%tikz``

{TIKZ_DOC}

"""

from __future__ import print_function


import os
import sys
import tempfile
import contextlib
from shutil import rmtree, copy
from subprocess import call
from xml.dom import minidom

from IPython.core.displaypub import publish_display_data
from IPython.core.magic import (Magics, magics_class, line_cell_magic, needs_local_scope)
from IPython.core.magic_arguments import (
    argument, magic_arguments, parse_argstring
)
from IPython.testing.skipdoctest import skip_doctest

try:
    import pkg_resources  # part of setuptools
    __version__ = pkg_resources.require("ipython-tikzmagic")[0].version
except ImportError:
    __version__ = 'unknown'

_MIME_TYPES = {
    'png': 'image/png',
    'svg': 'image/svg+xml',
    'jpg': 'image/jpeg',
    'jpeg': 'image/jpeg'
}


def split_csv_args(arg_string):
    return [name.strip()
            for name in arg_string.strip().split(',')
            if name.strip()]


@contextlib.contextmanager
def working_directory(path):
    """A context manager which changes the working directory to the given
    path, and then changes it back to its previous value on exit.

    """
    prev_cwd = os.getcwd()
    os.chdir(path)
    yield prev_cwd
    os.chdir(prev_cwd)


@magics_class
class TikzMagics(Magics):
    """A set of magics useful for creating figures with TikZ."""

    def __init__(self, shell):
        """
        Parameters
        ----------
        shell : IPython shell

        """
        super(TikzMagics, self).__init__(shell)
        self._plot_format = 'png'

        # Allow publish_display_data to be overridden for
        # testing purposes.
        self._publish_display_data = publish_display_data

    def _fix_gnuplot_svg_size(self, image, size=None):
        """GnuPlot SVGs do not have height/width attributes. Set
        these to be the same as the viewBox, so that the browser
        scales the image correctly.

        Parameters
        ----------
        image : str
            SVG data.
        size : tuple of int
            Image width, height.

        """
        (svg,) = minidom.parseString(image).getElementsByTagName('svg')
        viewbox = svg.getAttribute('viewBox').split(' ')

        if size is not None:
            width, height = size
        else:
            width, height = viewbox[2:]

        svg.setAttribute('width', '%dpx' % width)
        svg.setAttribute('height', '%dpx' % height)
        return svg.toxml()

    def _run_latex(self, code, encoding, dir):
        with open(dir + '/tikz.tex', 'w', encoding=encoding) as f:
            f.write(code)

        with working_directory(dir) as current_dir:
            # in case of error return LaTeX log
            if not self._convert_tikz_latex(current_dir):
                return self._read_tikz_log()

    def _convert_tikz_latex(self, current_dir):
        """Returns True if conversion is successful, else False."""
        # Set the TEXINPUTS environment variable, which allows the tikz code
        # to reference files relative to the notebook (includes, packages, ...)
        env = os.environ.copy()
        if 'TEXINPUTS' in env:
            env['TEXINPUTS'] = current_dir + os.pathsep + env['TEXINPUTS']
        else:
            env['TEXINPUTS'] = '.' + os.pathsep + current_dir + os.pathsep * 2
            # note that the trailing double pathsep will insert the standard
            # search path (otherwise we would lose access to all packages)

        try:
            retcode = call("pdflatex --shell-escape tikz.tex", shell=True, env=env)
            if retcode != 0:
                print("LaTeX terminated with signal", -retcode, file=sys.stderr)
                return False
        except OSError as e:
            print("LaTeX execution failed:", e, file=sys.stderr)
            return False

        return True

    def _read_tikz_log(self):
        """Returns log from `tikz.log` if that file exists, else None."""
        try:
            with open('tikz.log', 'r', encoding='latin-1') as f:
                return f.read()
        except IOError:
            print("No log file generated.", file=sys.stderr)
            return None

    def _convert_pdf_to_svg(self, dir):
        with working_directory(dir):
            try:
                retcode = call("pdf2svg tikz.pdf tikz.svg", shell=True)
                if retcode != 0:
                    print("pdf2svg terminated with signal", -retcode, file=sys.stderr)
            except OSError as e:
                print("pdf2svg execution failed:", e, file=sys.stderr)

    def _convert_png_to_jpg(self, dir):
        with working_directory(dir):
            try:
                retcode = call("convert tikz.png -quality 100 -background white -flatten tikz.jpg",
                               shell=True)
                if retcode != 0:
                    print("convert terminated with signal", -retcode, file=sys.stderr)
            except OSError as e:
                print("convert execution failed:", e, file=sys.stderr)

    @skip_doctest
    @magic_arguments()
    @argument(
        '-sc', '--scale', action='store', type=str, default=1,
        help='Scaling factor of plots. Default is "--scale 1".'
        )
    @argument(
        '-s', '--size', action='store', type=str, default='400,240',
        help='Pixel size of plots, "width,height". Default is "--size 400,240".'
        )
    @argument(
        '-f', '--format', action='store', type=str, default='png',
        help='Plot format (png, svg or jpg).'
        )
    @argument(
        '-e', '--encoding', action='store', type=str, default='utf-8',
        help='Text encoding, e.g., -e utf-8.'
        )
    @argument(
        '-x', '--preamble', action='store', type=str, default='',
        help='LaTeX preamble to insert before tikz figure, e.g., -x $preamble, with preamble some string variable.'
        )
    @argument(
        '-p', '--package', action='store', type=str, default='',
        help='LaTeX packages to load, separated by comma, e.g., -p pgfplots,textcomp.'
        )
    @argument(
        '-l', '--library', action='store', type=str, default='',
        help='TikZ libraries to load, separated by comma, e.g., -l matrix,arrows.'
        )
    @argument(
        '-S', '--save', action='store', type=str, default=None,
        help='Save a copy to file, e.g., -S filename. Default is None'
        )
    @argument(
        '-d', '--dry-run', action='store_true', default=False,
        help='Output the LaTeX code that will be generated.'
    )
    @needs_local_scope
    @argument(
        'code',
        nargs='*',
        )
    @line_cell_magic
    def tikz(self, line, cell=None, local_ns=None):
        """Run TikZ code in LaTeX and plot result.

            In [9]: %tikz \draw (0,0) rectangle (1,1);

        As a cell, this will run a block of TikZ code::

            In [10]: %%tikz
               ....: \draw (0,0) rectangle (1,1);

        In the notebook, plots are published as the output of the cell.

        The size and format of output plots can be specified::

            In [18]: %%tikz -s 600,800 -f svg --scale 2
                ...: \draw (0,0) rectangle (1,1);
                ...: \filldraw (0.5,0.5) circle (.1);

        TikZ packages can be loaded with -l package1,package2[,...]::

            In [20]: %%tikz -l arrows,matrix
                ...: \matrix (m) [matrix of math nodes, row sep=3em, column sep=4em] {
                ...: A & B \\
                ...: C & D \\
                ...: };
                ...: \path[-stealth, line width=.4mm]
                ...: (m-1-1) edge node [left ] {$ac$} (m-2-1)
                ...: (m-1-1) edge node [above] {$ab$} (m-1-2)
                ...: (m-1-2) edge node [right] {$bd$} (m-2-2)
                ...: (m-2-1) edge node [below] {$cd$} (m-2-2);
        """

        # read arguments
        args = parse_argstring(self.tikz, line)
        scale = args.scale
        size = args.size
        width, height = split_csv_args(size)
        plot_format = args.format
        encoding = args.encoding
        preamble = args.preamble
        tikz_libraries = split_csv_args(args.library)
        latex_package = split_csv_args(args.package)
        dry_run = args.dry_run

        # arguments 'code' in line are prepended to the cell lines
        if cell is None:
            code = ''
            return_output = True
        else:
            code = cell
            return_output = False

        code = str('').join(args.code) + code

        # if there is no local namespace then default to an empty dict
        if local_ns is None:
            local_ns = {}

        # generate plots in a temporary directory
        plot_dir = tempfile.mkdtemp().replace('\\', '/')

        add_params = ""
        if plot_format == 'png' or plot_format == 'jpg' or plot_format == 'jpeg':
            add_params += "density=300,"

        tex = ['''
\\documentclass[convert={%(add_params)ssize=%(width)sx%(height)s,outext=.png},border=0pt]{standalone}
\\usepackage{tikz}''' % locals()]

        for pkg in latex_package:
            tex.append('''
\\usepackage{%s}''' % pkg)

        tex.append('''
\\usetikzlibrary{%s}''' % ','.join(tikz_libraries))

        if preamble is not None:
            tex.append('''
%s''' % preamble.strip("'\""))  # allows users to string-escape spacing

        tex.append('''
\\begin{document}
\\begin{tikzpicture}[scale=%(scale)s]''' % locals())

        tex.append('\n'.join([
            '    %s' % line.strip()
            for line in code.split(os.linesep)
        ]))

        tex.append('''
\\end{tikzpicture}
\\end{document}
        ''')

        code = str('').join(tex)
        if dry_run:
            print(code)
            return

        latex_log = self._run_latex(code, encoding, plot_dir)

        key = 'TikZMagic.Tikz'
        display_data = []

        # If the latex error log exists, then image generation has failed.
        # Publish error log and return immediately
        if latex_log:
            self._publish_display_data(source=key, data={'text/plain': latex_log})
            return

        if plot_format == 'jpg' or plot_format == 'jpeg':
            self._convert_png_to_jpg(plot_dir)
        elif plot_format == 'svg':
            self._convert_pdf_to_svg(plot_dir)

        image_filename = "%s/tikz.%s" % (plot_dir, plot_format)

        # Publish image
        try:
            image = open(image_filename, 'rb').read()
            plot_mime_type = _MIME_TYPES.get(plot_format, 'image/%s' % (plot_format))
            width, height = [int(s) for s in size.split(',')]
            if plot_format == 'svg':
                image = self._fix_gnuplot_svg_size(image, size=(width, height))

            display_data.append((key, {plot_mime_type: image}))
        except IOError:
            print("No image generated.", file=sys.stderr)

        # Copy output file if requested
        if args.save is not None:
            copy(image_filename, args.save)

        rmtree(plot_dir)

        for tag, disp_d in display_data:
            if plot_format == 'svg':
                # isolate data in an iframe, to prevent clashing glyph declarations in SVG
                self._publish_display_data(source=tag, data=disp_d, metadata={'isolated': 'true'})
            else:
                self._publish_display_data(source=tag, data=disp_d, metadata=None)


__doc__ = __doc__.format(
    TIKZ_DOC = ' '*8 + TikzMagics.tikz.__doc__,
)


def load_ipython_extension(ip):
    """Load the extension in IPython."""
    ip.register_magics(TikzMagics)
