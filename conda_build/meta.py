# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, print_function

import re
from functools import partial
from logging import getLogger
import os
import sys

import yaml


from auxlib.entity import (Entity, StringField, ComposableField, MutableListField as ListField,
                           IntegerField, BooleanField, Field, MapField)
from auxlib.exceptions import ValidationError
from conda.compat import PY3, text_type, string_types
from conda.resolve import MatchSpec
from jinja2 import Environment, StrictUndefined, DebugUndefined

from .config import config
from .jinja_context import load_npm, load_setuptools
from .environ import get_dict as get_environ
from conda.utils import md5_file
import conda.config as cc


log = getLogger(__name__)



#
# class Package:
#     pass
#     # self.fn = fn
#     #      filename
#     # self.name = info.get('name')
#     # self.version = info.get('version')
#     # self.build = info.get('build')
#     #      build_string
#     # self.build_number = info.get('build_number')
#     # self.channel = info.get('channel')
#
#     # location  url, path


# TODO: Not implemented
#  parse_again: run_requirements = specs_from_url(self.requirements_path)
#  validate Source

def context_processor(initial_metadata, recipe_dir):
    """
    Return a dictionary to use as context for jinja templates.

    initial_metadata: Augment the context with values from this MetaData object.
                      Used to bootstrap metadata contents via multiple parsing passes.
    """
    ctx = get_environ(initial_metadata)

    environ = dict(os.environ)
    environ.update(ctx)
    ctx.update(load_setuptools=partial(load_setuptools, recipe_dir=recipe_dir),
               load_npm=load_npm, environ=environ, **environ)
    return ctx


CONTEXT = None
def set_context(meta):
    global CONTEXT
    from conda_build.metadata import ns_cfg
    CONTEXT = dict(ns_cfg(), **context_processor(meta, meta.path))
    return CONTEXT


def template_string(string,
                    _environment=Environment(variable_start_string='@{',
                                             variable_end_string='}',
                                             )):  # undefined=StrictUndefined
    print('!!!', CONTEXT)
    return _environment.from_string(string, {}).render(CONTEXT or {})


def template_string_preprocess(recipe_dir, string):
    context = context_processor(None, recipe_dir)
    from pprint import pprint
    pprint(context)
    return Environment(undefined=StrictUndefined).from_string(string, {}).render(context)


class IntegerStringField(StringField):

    # def box(self, instance, val):
    #     return val
    #
    def unbox(self, instance, instance_type, val):
        return self.dump(val)

    def dump(self, val):
        if isinstance(val, StringField._type):
            val = template_string(val)
            # assert not set(val) & POST_VALIDATE_CHRS, val
        return int(val) if val else self.default


class ExpansionEntity(Entity):

    def __getattribute__(self, item):
        value = super(ExpansionEntity, self).__getattribute__(item)
        if not item.startswith('_') and item in type(self).fields and self._initd:
            field = self.__fields__[item]
            if isinstance(field, (StringField, IntegerStringField)):
                try:
                    value = template_string(value)
                    # assert not set(value) & POST_VALIDATE_CHRS, value
                except ValidationError:
                    pass
        return value

    def validate(self):
        # TODO: here, validate should only have to determine if the required keys are set
        try:
            for name, field in self.__fields__.items():
                if field.required:
                    getattr(self, name)
        except AttributeError as e:
            raise  # ValidationError(None, msg=e)



NAME_BAD_CHRS = set('=!#$%^&*;\\<>?/')  # for 'package/name'
VERSION_BAD_CHRS = NAME_BAD_CHRS | set('-')  # for 'package/version', 'build/string'
POST_VALIDATE_CHRS = set('@{}"\'| :')


class PackageNV(ExpansionEntity):
    name = StringField(required=False, validation=lambda s: not set(s) & NAME_BAD_CHRS,
                       # post_validation=lambda s: not set(s) & POST_VALIDATE_CHRS,
                       )
    version = StringField('', validation=lambda s: not set(s) & VERSION_BAD_CHRS,
                          # post_validation=lambda s: not set(s) & POST_VALIDATE_CHRS,
                          )


class Source(ExpansionEntity):
    fn = StringField(required=False)
    url = StringField(required=False)
    md5 = StringField('')
    sha1 = StringField(required=False)
    sha256 = StringField(required=False)
    path = StringField('')
    git_url = StringField(required=False)
    git_rev = StringField('')
    git_depth = StringField(required=False)
    hg_url = StringField(required=False)
    hg_tag = StringField(required=False)
    svn_url = StringField(required=False)
    svn_rev = StringField('')
    svn_ignore_externals = StringField(required=False)
    patches = ListField(string_types, required=False)

    def __init__(self, **kwargs):
        git_rev = kwargs.pop('git_rev', None)
        git_branch = kwargs.pop('git_branch', None)
        git_tag = kwargs.pop('git_tag', None)
        threesome = (git_branch, git_rev, git_tag)
        num = sum(bool(x) for x in threesome)
        if num > 1:
            raise ValidationError(None, msg="Use only git_rev. "
                                            "Both git_branch and git_tag are deprecated.")
        if num == 1:
            kwargs['git_rev'] = next(x for x in threesome if x)
        super(Source, self).__init__(**kwargs)


class Build(ExpansionEntity):
    number = IntegerStringField(0)
    string = StringField('', validation=lambda s: not set(s) & VERSION_BAD_CHRS,
                         # post_validation=lambda s: not set(s) & POST_VALIDATE_CHRS,
                         )
    entry_points = ListField(string_types, required=False)
    osx_is_app = BooleanField(False)
    features = ListField(string_types, required=False)
    track_features = ListField(string_types, required=False)
    preserve_egg_dir = BooleanField(False)
    no_link = BooleanField(required=False)
    binary_relocation = BooleanField(False)
    script = StringField(required=False)
    noarch_python = BooleanField(False)
    has_prefix_files = ListField(string_types, required=False)
    binary_has_prefix_files = ListField(string_types, required=False)
    script_env = ListField(string_types, required=False)
    detect_binary_files_with_prefix = BooleanField(False)
    rpaths = StringField(required=False)
    always_include_files = ListField(string_types, required=False)
    skip = BooleanField(False)
    msvc_compiler = StringField(required=False)
    pin_depends = StringField('')


class Requirements(ExpansionEntity):
    build = ListField(string_types, required=False)
    run = ListField(string_types, required=False)
    conflicts = ListField(string_types, required=False)


class App(ExpansionEntity):
    entry = StringField(required=False)
    icon = StringField(required=False)
    summary = StringField(required=False)
    type = StringField(required=False)
    cli_opts = StringField(required=False)
    own_environment = BooleanField(False)


class Test(ExpansionEntity):
    requires = ListField(string_types, required=False)
    commands = ListField(string_types, required=False)
    files = ListField(string_types, required=False)
    imports = ListField(string_types, required=False)


def validate_license_family(value):
    from conda_build.metadata import allowed_license_families
    return value in allowed_license_families


class About(ExpansionEntity):
    home = StringField(required=False)
    dev_url = StringField(required=False)
    doc_url = StringField(required=False)
    license_url = StringField(required=False)
    license = StringField(required=False)
    summary = StringField(required=False)
    description = StringField(required=False)
    license_family = StringField(required=False, validation=validate_license_family)
    license_file = StringField(required=False)
    readme = StringField(required=False)


class MetaDataMixin(object):

    # def check_fields(self):
    #     for section, submeta in iteritems(self.meta):
    #         if section == 'extra':
    #             continue
    #         if section not in FIELDS:
    #             sys.exit("Error: unknown section: %s" % section)
    #         for key in submeta:
    #             if key not in FIELDS[section]:
    #                 sys.exit("Error: in section %r: unknown key %r" %
    #                          (section, key))

    # def name(self):
    #     res = self.get_value('package/name')
    #     if not res:
    #         sys.exit('Error: package/name missing in: %r' % self.meta_path)
    #     res = text_type(res)
    #     if res != res.lower():
    #         sys.exit('Error: package/name must be lowercase, got: %r' % res)
    #     check_bad_chrs(res, 'package/name')
    #     return res

    # def version(self):
    #     res = self.get_value('package/version')
    #     if res is None:
    #         sys.exit("Error: package/version missing in: %r" % self.meta_path)
    #     check_bad_chrs(res, 'package/version')
    #     return res

    # def build_number(self):
    #     return int(self.get_value('build/number', 0))


    def ms_depends(self, typ='run'):
        from conda_build.metadata import handle_config_version
        res = []
        name_ver_list = [
            ('python', config.CONDA_PY),
            ('numpy', config.CONDA_NPY),
            ('perl', config.CONDA_PERL),
            ('lua', config.CONDA_LUA),
            ('r', config.CONDA_R),
        ]
        for spec in self.get_value('requirements/' + typ, []):
            try:
                ms = MatchSpec(spec)
            except AssertionError:
                raise RuntimeError("Invalid package specification: %r" % spec)
            if ms.name == self.name():
                raise RuntimeError("%s cannot depend on itself" % self.name())
            for name, ver in name_ver_list:
                if ms.name == name:
                    if self.get_value('build/noarch_python'):
                        continue
                    ms = handle_config_version(ms, ver)

            for c in '=!@#$%^&*:;"\'\\|<>?/':
                if c in ms.name:
                    sys.exit("Error: bad character '%s' in package name "
                             "dependency '%s'" % (c, ms.name))
                parts = spec.split()
                if len(parts) >= 2:
                    if parts[1] in {'>', '>=', '=', '==', '!=', '<', '<='}:
                        msg = ("Error: bad character '%s' in package version "
                               "dependency '%s'" % (parts[1], ms.name))
                        if len(parts) >= 3:
                            msg += "\nPerhaps you meant '%s %s%s'" % (ms.name,
                                parts[1], parts[2])
                        sys.exit(msg)
            res.append(ms)
        return res

    def build_id(self):
        ret = self.get_value('build/string')
        if ret:
            # from conda_build.metadata import check_bad_chrs
            # check_bad_chrs(ret, 'build/string')
            return ret
        res = []
        version_pat = re.compile(r'(?:==)?(\d+)\.(\d+)')
        for name, s in (('numpy', 'np'), ('python', 'py'),
                        ('perl', 'pl'), ('lua', 'lua'), ('r', 'r')):
            for ms in self.ms_depends():
                if ms.name == name:
                    try:
                        v = ms.spec.split()[1]
                    except IndexError:
                        if name not in ['numpy']:
                            res.append(s)
                        break
                    if any(i in v for i in ',|>!<'):
                        break
                    if name not in ['perl', 'r', 'lua']:
                        match = version_pat.match(v)
                        if match:
                            res.append(s + match.group(1) + match.group(2))
                    else:
                        res.append(s + v.strip('*'))
                    break

        features = self.get_value('build/features', [])
        if res:
            res.append('_')
        if features:
            res.extend(('_'.join(features), '_'))
        res.append('%d' % self.build_number())
        return ''.join(res)

    def dist(self):
        return '%s-%s-%s' % (self.name(), self.version(), self.build_id())

    def pkg_fn(self):
        return "%s.tar.bz2" % self.dist()

    def is_app(self):
        return bool(self.get_value('app/entry'))

    def app_meta(self):
        d = {'type': 'app'}
        if self.get_value('app/icon'):
            d['icon'] = '%s.png' % md5_file(os.path.join(self.path, self.get_value('app/icon')))

        for field, key in [('app/entry', 'app_entry'),
                           ('app/type', 'app_type'),
                           ('app/cli_opts', 'app_cli_opts'),
                           ('app/summary', 'summary'),
                           ('app/own_environment', 'app_own_environment')]:
            value = self.get_value(field)
            if value:
                d[key] = value
        return d

    def info_index(self):
        d = dict(
            name = self.name(),
            version = self.version(),
            build = self.build_id(),
            build_number = self.build_number(),
            platform = cc.platform,
            arch = cc.arch_name,
            subdir = cc.subdir,
            depends = sorted(' '.join(ms.spec.split())
                             for ms in self.ms_depends()),
        )
        for key in ('license', 'license_family'):
            value = self.get_value('about/' + key)
            if value:
                d[key] = value

        if self.get_value('build/features'):
            d['features'] = ' '.join(self.get_value('build/features'))
        if self.get_value('build/track_features'):
            d['track_features'] = ' '.join(self.get_value('build/track_features'))
        if self.get_value('build/noarch_python'):
            d['platform'] = d['arch'] = None
            d['subdir'] = 'noarch'
        if self.is_app():
            d.update(self.app_meta())
        return d

    def has_prefix_files(self):
        ret = self.get_value('build/has_prefix_files', [])
        if not isinstance(ret, list):
            raise RuntimeError('build/has_prefix_files should be a list of paths')
        if sys.platform == 'win32':
            if any('\\' in i for i in ret):
                raise RuntimeError("build/has_prefix_files paths must use / as the path delimiter on Windows")
        return ret

    def always_include_files(self):
        return self.get_value('build/always_include_files', [])

    def binary_has_prefix_files(self):
        ret = self.get_value('build/binary_has_prefix_files', [])
        if not isinstance(ret, (list, tuple)):
            raise RuntimeError('build/binary_has_prefix_files should be a list of paths')
        if sys.platform == 'win32':
            if any('\\' in i for i in ret):
                raise RuntimeError("build/binary_has_prefix_files paths must use / as the path delimiter on Windows")
        return ret

    def skip(self):
        return self.get_value('build/skip', False)

    def __str__(self):
        if PY3:
            return self.__unicode__()
        else:
            return self.__unicode__().encode('utf-8')



class MetaData(MetaDataMixin, ExpansionEntity):
    package = ComposableField(PackageNV, required=False)
    source = ComposableField(Source, Source())
    build = ComposableField(Build, Build())
    requirements = ComposableField(Requirements, required=False)
    app = ComposableField(App, required=False)
    test = ComposableField(Test, required=False)
    about = ComposableField(About, required=False)
    extra = MapField(required=False)

    def __init__(self, **kwargs):
        self.path = kwargs.pop('path', None)
        self.meta_path = kwargs.pop('meta_path', None)
        super(MetaData, self).__init__(**kwargs)

    @classmethod
    def from_file(cls, filepath):
        recipe_dir = os.path.dirname(filepath)
        with open(filepath, 'r') as f:
            data = f.read()
        jinja_parsed = template_string_preprocess(recipe_dir, data)
        from conda_build.metadata import select_lines, ns_cfg
        selector_parsed = select_lines(jinja_parsed, ns_cfg())
        yaml_dict = yaml.load(selector_parsed)
        instance = cls(path=recipe_dir, meta_path=filepath, **yaml_dict)
        set_context(instance)
        return instance

    @classmethod
    def fromdict(cls, metadata):
        instance = cls(**metadata)
        set_context(instance)
        return instance

    def get_section(self, section):
        section = getattr(self, section, None)
        return section.dump() if section else {}

    def get_value(self, item, default=None):
        def _get_value(obj, items):
            try:
                value = getattr(obj, items[0])
            except (IndexError, AttributeError):
                return default
            if len(items) == 1:
                return value
            else:
                return _get_value(value, items[1:])
        return _get_value(self, item.split('/'))

    def name(self):
        return self.package.name

    def version(self):
        return self.package.version

    def build_number(self):
        return self.build.number

    def __unicode__(self):
        return text_type(self.__repr__())

    def check_fields(self):
        pass

    def parse_again(self, *args, **kwargs):
        pass

    @property
    def meta(self):
        return self.dump()





if __name__ == '__main__':
    from os.path import expanduser
    # m = MetaData.from_file(expanduser('~/continuum/conda-packages/centos5/ansible/meta.yaml'))
    # print(m.name())
    # print(m.build_id())
    # print(m.path)
    # print(m.ms_depends())
    # print(m.dist())
    # print(m.pkg_fn())
    # print(m.app_meta())
    m = MetaData.from_file(expanduser('~/continuum/conda-build/tests/test-recipes/metadata/source_git_jinja2/meta.yaml'))
    # print(m.build.binary_has_prefix_files)
    print(m.get_section('package'))
    print(m.get_section('source'))
