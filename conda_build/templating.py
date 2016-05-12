# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, print_function
from logging import getLogger

log = getLogger(__name__)









#
#
#
#
#
#
#
#
# class UndefinedNeverFail(jinja2.Undefined):
#     """
#     A class for Undefined jinja variables.
#     This is even less strict than the default jinja2.Undefined class,
#     because it permits things like {{ MY_UNDEFINED_VAR[:2] }} and {{ MY_UNDEFINED_VAR|int }}.
#     This can mask lots of errors in jinja templates, so it should only be used for a first-pass
#     parse, when you plan on running a 'strict' second pass later.
#     """
#     __add__ = __radd__ = __mul__ = \
#         __rmul__ = __div__ = __rdiv__ = \
#         __truediv__ = __rtruediv__ = __floordiv__ = \
#         __rfloordiv__ = __mod__ = __rmod__ = \
#         __pos__ = __neg__ = __call__ = \
#         __getitem__ = __lt__ = __le__ = \
#         __gt__ = __ge__ = __complex__ = \
#         __pow__ = __rpow__ = lambda *args, **kwargs: UndefinedNeverFail()
#
#     __str__ = __repr__ = lambda *args, **kwargs: u''
#
#     __int__ = lambda _: 0
#     __float__ = lambda _: 0.0
#
#     def __getattr__(self, k):
#         try:
#             return object.__getattr__(self, k)
#         except AttributeError:
#             return UndefinedNeverFail()
#
#     def __setattr__(self, k, v):
#         pass
#
#
#
#
#
# # undefined_type = jinja2.StrictUndefined
# # if permit_undefined_jinja:
# #     undefined_type = UndefinedNeverFail
#
#
#
#
#
#
#
# from conda_build.jinja_context import context_processor
#
# path, filename = os.path.split(self.meta_path)
# recipe_dir
# loaders = [# search relative to '<conda_root>/Lib/site-packages/conda_build/templates'
#            jinja2.PackageLoader('conda_build'),
#            # search relative to RECIPE_DIR
#            jinja2.FileSystemLoader(recipe_dir)
#            ]
#
# # search relative to current conda environment directory
# conda_env_path = os.environ.get('CONDA_DEFAULT_ENV')  # path to current conda environment
# if conda_env_path and os.path.isdir(conda_env_path):
#     conda_env_path = os.path.abspath(conda_env_path)
#     conda_env_path = conda_env_path.replace('\\', '/') # need unix-style path
#     env_loader = jinja2.FileSystemLoader(conda_env_path)
#     loaders.append(jinja2.PrefixLoader({'$CONDA_DEFAULT_ENV': env_loader}))
#
# undefined_type = jinja2.StrictUndefined
# if permit_undefined_jinja:
#     undefined_type = UndefinedNeverFail
#
# env = jinja2.Environment(loader=jinja2.ChoiceLoader(loaders), undefined=undefined_type)
# env.globals.update(ns_cfg())
# env.globals.update(context_processor(self, recipe_dir))
#
# try:
#     template = env.get_or_select_template(filename)
#     return template.render(environment=env)
# except jinja2.TemplateError as ex:
#     sys.exit("Error: Failed to render jinja template in {}:\n{}".format(self.meta_path, ex.message))
#
#
#
#




import datetime
import collections  # noqa
from email.utils import parseaddr
import logging
import os
import re
import urllib

from auxlib.decorators import memoize
import jinja2
from jinja2.loaders import TemplateNotFound

log = logging.getLogger(__name__)


def _filter_urllib_urlencode(url_param_dict):
    """
    Examples:
        >>> d = collections.OrderedDict([('a', 1), ('b', 2)])
        >>> _filter_urllib_urlencode(d)
        'a=1&b=2'

    """
    return urllib.urlencode(url_param_dict)


def _filter_strftime(dt, dt_format):
    return datetime.date.strftime(dt, dt_format)


def _is_re_match(s, rs):
    """Allows testing based on a regex"""
    # https://groups.google.com/forum/#!topic/pocoo-libs/3yZl8vHJ9fI
    return True if re.search(rs, s) else False


def _filter_re_sub(s, rs, repl):
    myre = re.compile(rs)
    return re.sub(myre, repl, s)


def _filter_to_email_name(s):
    name, _ = parseaddr(s)
    return name


def _filter_to_email_address(s):
    _, email = parseaddr(s)
    return email


_global_now = datetime.datetime.utcnow  # function pointer to utcnow


class _CustomEnvironment(jinja2.Environment):
    """Override join_path() to enable relative template paths."""

    def __init__(self, *args, **kwargs):
        super(_CustomEnvironment, self).__init__(*args, **kwargs)
        self.environment_locked = False

    def join_path(self, template, parent):
        return os.path.join(os.path.dirname(parent), template)

    def apply_custom_filters(self):
        if self.environment_locked:
            raise EnvironmentError('render has already been called on environment')
        # self.filters['urllib_urlencode'] = _filter_urllib_urlencode
        # self.filters['strftime'] = _filter_strftime
        # self.tests['re_match'] = _is_re_match
        # self.filters['re_sub'] = _filter_re_sub
        # self.filters['to_email_name'] = _filter_to_email_name
        # self.filters['to_email_address'] = _filter_to_email_address
        # self.globals['now'] = _global_now


@memoize
def initialize_templating():
    """Jinja2 variables injected into the global namespace must be in place before *any* template
    is rendered.  The function is memoized to ensure that it is only executed once in the python
    process.
    """
    TemplateEngine.environment = _CustomEnvironment(
        loader=jinja2.FileSystemLoader('./'),
        undefined=jinja2.StrictUndefined)
    TemplateEngine.environment.apply_custom_filters()
    log.info("templating initialized")


class TemplateEngine(object):

    environment = None

    @classmethod
    def add_global(cls, key, value):
        if cls.environment.environment_locked:
            raise EnvironmentError('render has already been called on environment')
        cls.environment.globals[key] = value

    @classmethod
    def render(cls, template_path, context=None, allow_undefined=False, **template_variables):
        """Renders a template using Jinja2 for templates with relative path

        Arguments:
            template_path (str): absolute path or relative path from /opt/ttam/emails
            context (dict, optional): a map holding variables to be applied to the template

        Keyword Arguments:
            template_variables (optional): each kwarg is added to context
        """
        cls.environment.environment_locked = True

        if context is not None:
            template_variables.update(context)
        p = os.path.normpath(template_path)
        try:
            return cls.environment.get_template(p).render(**template_variables)
        except TemplateNotFound:
            log.error("TemplateNotFound [{}]".format(template_path))
            raise
