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
import shutil
import tempfile
import contextlib
import subprocess
from xml.dom import minidom

from IPython.core.displaypub import publish_display_data
from IPython.core.magic import Magics, magics_class, line_cell_magic, needs_local_scope
from IPython.core.magic_arguments import argument, magic_arguments, parse_argstring
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


def get_mime_type(img_format):
    return _MIME_TYPES.get(img_format, 'image/%s' % img_format)


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
    try:
        yield prev_cwd
    finally:
        os.chdir(prev_cwd)


@contextlib.contextmanager
def make_tempdir():
    """This sort of thing exists in Py3 as `tempfile.TemporaryDirectory`,
    but we roll our own here for Py2 compatibility.
    """
    tempdir_path = tempfile.mkdtemp().replace('\\', '/')
    try:
        yield tempdir_path
    finally:
        shutil.rmtree(tempdir_path)


def run_latex(code, dirpath, encoding='utf-8'):
    with open(dirpath + '/tikz.tex', 'w', encoding=encoding) as f:
        f.write(code)

    with working_directory(dirpath) as current_dir:
        # in case of error return LaTeX log
        if not _convert_tikz_latex(current_dir):
            return _read_tikz_log()


def _convert_tikz_latex(current_dir):
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
        retcode = subprocess.call(
            "pdflatex --shell-escape tikz.tex", shell=True, env=env)

        if retcode != 0:
            print("LaTeX terminated with signal", -retcode, file=sys.stderr)
            return False
    except OSError as e:
        print("LaTeX execution failed:", e, file=sys.stderr)
        return False

    return True


def _read_tikz_log(log_path='tikz.log', encoding='latin-1'):
    """Returns log from `tikz.log` if that file exists, else None."""
    try:
        with open(log_path, 'r', encoding=encoding) as f:
            return f.read()
    except IOError:
        print("No log file generated.", file=sys.stderr)
        return None


def _convert_img_format(plot_dir, plot_format):
    if plot_format == 'jpg' or plot_format == 'jpeg':
        _convert_png_to_jpg(plot_dir)
    elif plot_format == 'svg':
        _convert_pdf_to_svg(plot_dir)


def _convert_pdf_to_svg(dirpath):
    with working_directory(dirpath):
        try:
            retcode = subprocess.call("pdf2svg tikz.pdf tikz.svg", shell=True)
            if retcode != 0:
                print("pdf2svg terminated with signal", -retcode, file=sys.stderr)
        except OSError as e:
            print("pdf2svg execution failed:", e, file=sys.stderr)


def _convert_png_to_jpg(dirpath):
    with working_directory(dirpath):
        try:
            retcode = subprocess.call(
                "convert tikz.png -quality 100 -background white -flatten tikz.jpg",
                shell=True)

            if retcode != 0:
                print("convert terminated with signal", -retcode, file=sys.stderr)
        except OSError as e:
            print("convert execution failed:", e, file=sys.stderr)


def _fix_gnuplot_svg_size(image, size=None):
    """GnuPlot SVGs do not have height/width attributes. Set
    these to be the same as the viewBox, so that the browser
    scales the image correctly.

    Parameters
    ----------
    image : str|bytes
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

    @skip_doctest
    @magic_arguments()
    @argument(
        '-sc', '--scale', action='store', type=str, default=1,
        help='Scaling factor of plots. Default is "--scale 1".')
    @argument(
        '-s', '--size', action='store', type=str, default='400,240',
        help='Pixel size of plots, "width,height". Default is "--size 400,240".')
    @argument(
        '-f', '--format', action='store', type=str, default='png',
        help='Plot format (png, svg or jpg).')
    @argument(
        '-e', '--encoding', action='store', type=str, default='utf-8',
        help='Text encoding, e.g., -e utf-8.')
    @argument(
        '-x', '--preamble', action='store', type=str, default='',
        help='LaTeX preamble to insert before tikz figure, e.g., '
             '-x $preamble, with preamble some string variable.')
    @argument(
        '-p', '--package', action='store', type=str, default='',
        help='LaTeX packages to load, separated by comma, e.g., -p pgfplots,textcomp.')
    @argument(
        '-l', '--library', action='store', type=str, default='',
        help='TikZ libraries to load, separated by comma, e.g., -l matrix,arrows.')
    @argument(
        '-S', '--save', action='store', type=str, default=None,
        help='Save a copy to file, e.g., -S filename. Default is None')
    @argument(
        '-d', '--dry-run', action='store_true', default=False,
        help='Output the LaTeX code that will be generated.')
    @needs_local_scope
    @argument('code', nargs='*')
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
        args = parse_argstring(self.tikz, line)

        # If code blocks are passed in args, prepend to the block in the cell.
        code_from_args = str('\n').join(
            section.strip("'\"")
            for section in args.code
        ).strip()

        if cell is None:
            code = code_from_args
        else:
            code = code_from_args + cell

        runner = TikzRunner(
            code, args.package, args.library, args.preamble, args.size, args.scale,
            plot_format=args.format, encoding=args.encoding,
            img_save_path=args.save, dry_run=args.dry_run)
        runner.run()


class TikzRunner(object):
    """Run Tikz code to compile images."""

    def __init__(self, code, latex_packages, tikz_libraries, preamble, size, scale,
                 plot_format='svg', encoding='utf-8', img_save_path='', dry_run=False):
        self.code = code
        self.tikz_libraries = split_csv_args(tikz_libraries)
        self.latex_packages = split_csv_args(latex_packages)
        self.preamble = preamble
        self.width, self.height = map(int, split_csv_args(size))
        self.scale = scale

        self.plot_format = plot_format
        self.encoding = encoding
        self.img_save_path = img_save_path
        self.dry_run = dry_run

        self._key = 'TikZMagic.Tikz'

    def run(self):
        compiled_code = self.compile_tikz_template()
        if self.dry_run:
            print(compiled_code)
        else:
            self._run_and_display(compiled_code)

    def _run_and_display(self, compiled_code):
        display_data = self.generate_plots(compiled_code)
        for tag, disp_d in display_data:
            if self.plot_format == 'svg':
                # isolate data in an iframe, to prevent clashing glyph declarations in SVG
                publish_display_data(source=tag, data=disp_d, metadata={'isolated': 'true'})
            else:
                publish_display_data(source=tag, data=disp_d, metadata=None)

    def compile_tikz_template(self):
        add_params = ""
        if self.plot_format in {'png', 'jpg', 'jpeg'}:
            add_params += "density=300,"

        kwargs = {
            'add_params': add_params,
            'width': self.width,
            'height': self.height,
            'scale': self.scale,
        }

        convert_args = '%(add_params)ssize=%(width)sx%(height)s,outext=.png' % kwargs
        tex = ['\\documentclass[convert={%s},border=0pt]{standalone}' % convert_args,
               '\\usepackage{tikz}']

        for pkg in self.latex_packages:
            tex.append('\\usepackage{%s}' % pkg)

        tex.append('\\usetikzlibrary{%s}' % ','.join(self.tikz_libraries))

        if self.preamble is not None:
            # the strip allows users to string-escape spacing
            tex.append('%s' % self.preamble.strip("'\""))

        tex.append('\\begin{document}\n'
                   '\\begin{tikzpicture}[scale=%(scale)s]' % kwargs)

        tex.append('\n'.join([
            '    %s' % line.strip()
            for line in self.code.split(os.linesep)
        ]))

        tex.append('\\end{tikzpicture}\n'
                   '\\end{document}')

        return str('\n').join(tex)

    def generate_plots(self, compiled_code):
        display_data = []
        with make_tempdir() as plot_dir:
            latex_log = run_latex(compiled_code, plot_dir, self.encoding)

            # If the latex error log exists, then image generation has failed.
            # Publish error log and return immediately
            if latex_log:
                publish_display_data(
                    source=self._key,
                    data={'text/plain': latex_log})
            else:
                _convert_img_format(plot_dir, self.plot_format)

                image_filename = "%s/tikz.%s" % (plot_dir, self.plot_format)
                img = self._publish_image(image_filename)
                if img is not None:
                    display_data.append((self._key, img))

                self._save_if_requested(image_filename)

        return display_data

    def _publish_image(self, image_filename):
        try:
            with open(image_filename, 'rb') as f:
                image = f.read()

            plot_mime_type = get_mime_type(self.plot_format)
            if self.plot_format == 'svg':
                image = _fix_gnuplot_svg_size(image, size=(self.width, self.height))

            return {plot_mime_type: image}
        except IOError:
            print("No image generated.", file=sys.stderr)
            return None

    def _save_if_requested(self, image_filename):
        """Copy output file if requested."""
        if self.img_save_path is not None:
            shutil.copy(image_filename, self.img_save_path)


__doc__ = __doc__.format(
    TIKZ_DOC=' ' * 8 + TikzMagics.tikz.__doc__,
)


def load_ipython_extension(ip):
    """Load the extension in IPython."""
    ip.register_magics(TikzMagics)
