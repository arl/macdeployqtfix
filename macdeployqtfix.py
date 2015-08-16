from subprocess import Popen, PIPE
from string import Template
import os, sys
import logging
import argparse
import re

QTLIB_NAME_REGEX = r'^(?:@executable_path)?/.*/(Qt[a-zA-Z]*).framework/(?:Versions/\d/)?\1$'
QTPLUGIN_NAME_REGEX = r'^(?:@executable_path)?/.*/[pP]lug[iI]ns/(.*)/(.*).dylib$'
QTLIB_NORMALIZED = r'$prefix/Frameworks/$qtlib.framework/Versions/$qtversion/$qtlib'
QTPLUGIN_NORMALIZED = r'$prefix/PlugIns/$plugintype/$pluginname.dylib'

def run_and_get_output(popen_args):
    """
    exec process and get all output
    """
    try:
        logger.debug('run_and_get_output({0})'.format(repr(popen_args)))

        p = Popen(popen_args, stdin=PIPE, stdout=PIPE, stderr=PIPE)
        stdout, stderr = p.communicate(b'')

        logger.debug('\tretcode {0}'.format(p.returncode))
        logger.debug('\tstdout: {0}'.format(stdout))
        logger.debug('\tstderr: {0}'.format(stderr))
        return stdout, stderr, p.returncode
    except Exception as e:
        logger.error('\texception: {0}'.format(e))
        return '', e.message, -1

def get_dependencies(filename):
    """
    input: filename fullpath
    should call otool on mac and returns the list of dependencies,
        unsorted, unmodified, just the raw list
    so then we could eventually re-use in other more specialized functions
    """
    logger.debug('get_dependencies({0})'.format(filename))
    popen_args = ['otool', '-L', filename]

    stdout, stderr, retcode = run_and_get_output(popen_args)
    deps = []
    if retcode == 0:
        deps = map(lambda s: s.strip().split(' ')[0],
                        stdout.split('\n')[1:])
        # prevent infinite recursion when a binary depends on itself (seen with QtWidgets)...
        deps = filter(lambda s: os.path.basename(filename) not in s, deps)
        # filter out empty lines
        deps = filter(None, deps)
    return deps

def is_qt_plugin(filename):
    """
    check if a given file is a qt plugin
    accept absolute path as well as path containing @executable_path
    """
    qtlib_name_rgx = re.compile(QTPLUGIN_NAME_REGEX)
    rgxret = qtlib_name_rgx.match(filename)
    if rgxret is not None:
        logger.debug('rgxret is not None for {0}: {1}'.format(filename, rgxret.groups()))
    return rgxret is not None

def is_qt_lib(filename):
    """
    check if a given file is a qt library
    accept absolute path as well as path containing @executable_path
    """
    qtlib_name_rgx = re.compile(QTLIB_NAME_REGEX)
    rgxret = qtlib_name_rgx.match(filename)
    return rgxret is not None

def normalize_qtplugin_name(filename):
    """
    input: a path to a qt plugin, as returned by otool, that can have this form :
            - an absolute path /../plugins/PLUGINTYPE/PLUGINNAME.dylib
            - @executable_path/../plugins/PLUGINTYPE/PLUGINNAME.dylib
    output:
        a tuple (qtlib, abspath, rpath) where:
            - qtname is the name of the plugin (libqcocoa.dylib, etc.)
            - abspath is the absolute path of the qt lib inside the app bundle of exepath
            - relpath is the correct rpath to a qt lib inside the app bundle
    """

    logger.debug('normalize_plugin_name({0})'.format(filename))

    qtplugin_name_rgx = re.compile(QTPLUGIN_NAME_REGEX)
    rgxret = qtplugin_name_rgx.match(filename)
    if not rgxret:
        msg = 'couldn\'t normalize a non-qt plugin filename: {0}'.format(filename)
        logger.critical(msg)
        raise Exception(msg)

    # qtplugin normalization settings
    qtplugintype = rgxret.groups()[0]
    qtpluginname = rgxret.groups()[1]

    templ = Template(QTPLUGIN_NORMALIZED)
    # from qtlib, forge 2 path :
    #  - absolute path of qt lib in bundle,
    abspath = os.path.normpath(templ.safe_substitute(
                prefix=os.path.dirname(exepath) + '/..',
                plugintype=qtplugintype,
                pluginname=qtpluginname))
    #  - and rpath containing @executable_path, relative to exepath
    rpath = templ.safe_substitute(
                prefix='@executable_path/..',
                plugintype=qtplugintype,
                pluginname=qtpluginname)

    logger.debug('\treturns({0})'.format((qtpluginname, abspath, rpath)))
    return qtpluginname, abspath, rpath


def normalize_qtlib_name(filename):
    """
    input: a path to a qt library, as returned by otool, that can have this form :
            - an absolute path /lib/XXX/YYY
            - @executable_path/../Frameworks/QtSerialPort.framework/Versions/5/QtSerialPort
    output:
        a tuple (qtlib, abspath, rpath) where:
            - qtlib is the name of the qtlib (QtCore, QtWidgets, etc.)
            - abspath is the absolute path of the qt lib inside the app bundle of exepath
            - relpath is the correct rpath to a qt lib inside the app bundle
    """

    logger.debug('normalize_qtlib_name({0})'.format(filename))

    qtlib_name_rgx = re.compile(QTLIB_NAME_REGEX)
    rgxret = qtlib_name_rgx.match(filename)
    if not rgxret:
        msg = 'couldn\'t normalize a non-qt lib filename: {0}'.format(filename)
        logger.critical(msg)
        raise Exception(msg)

    # qtlib normalization settings
    qtlib = rgxret.groups()[0]
    qtversion = 5

    templ = Template(QTLIB_NORMALIZED)
    # from qtlib, forge 2 path :
    #  - absolute path of qt lib in bundle,
    abspath = os.path.normpath(templ.safe_substitute(
                prefix=os.path.dirname(exepath) + '/..',
                qtlib=qtlib,
                qtversion=qtversion))
    #  - and rpath containing @executable_path, relative to exepath
    rpath = templ.safe_substitute(
                prefix='@executable_path/..',
                qtlib=qtlib, 
                qtversion=qtversion)

    logger.debug('\treturns({0})'.format((qtlib, abspath, rpath)))
    return qtlib, abspath, rpath

def fix_dependency(binary, dep):
    """
    fix 'dep' dependency of 'binary'. 'dep' is a qt library
    """
    if is_qt_lib(dep):
        qtname, dep_abspath, dep_rpath = normalize_qtlib_name(dep)
    elif is_qt_plugin(dep):
        qtname, dep_abspath, dep_rpath = normalize_qtplugin_name(dep)
    else:
        return True

    # check that rpath of 'dep' inside binary has been correctly set
    # (ie: relative to exepath using '@executable_path' syntax)
    if dep != dep_rpath:
        # dep rpath is not ok
        logger.info('changing rpath \'{0}\' in binary {1}'.format(dep, binary))

        # call install_name_tool -change on binary
        popen_args = ['install_name_tool', '-change', dep, dep_rpath, binary]
        stdout, stderr, retcode = run_and_get_output(popen_args)
        if retcode != 0:
            logger.error(stderr)
            return False
        # call install_name_tool -id on binary
        popen_args = ['install_name_tool', '-id', dep_rpath, binary]
        stdout, stderr, retcode = run_and_get_output(popen_args)
        if retcode != 0:
            logger.error(stderr)
            return False
    else:
        logger.debug('rpath OK for {0} in {1}'.format(dep, binary))

    # now ensure that 'dep' exists at the specified path, relative to bundle
    if not os.path.exists(dep_abspath):

        # ensure destination directory exists
        logger.info('ensuring directory \'{0}\' exists: {0}'.format(os.path.dirname(dep_abspath)))    
        popen_args = ['mkdir', '-p', os.path.dirname(dep_abspath)]
        stdout, stderr, retcode = run_and_get_output(popen_args)
        if retcode != 0:
            logger.info(stderr)
            return False

        # copy missing dependency into bundle
        qtnamesrc = os.path.join(qtpath, 'lib', '{0}.framework'.format(qtname), qtname)
        logger.info('copying missing dependency in bundle: {0}'.format(qtname))    
        popen_args = ['cp', qtnamesrc, dep_abspath]
        stdout, stderr, retcode = run_and_get_output(popen_args)
        if retcode != 0:
            logger.info(stderr)
            return False

        # ensure permissions are correct if we ever have to change its rpath
        logger.info('ensuring 755 perm to {0}'.format(dep_abspath))    
        popen_args = ['chmod', '755', dep_abspath]
        stdout, stderr, retcode = run_and_get_output(popen_args)
        if retcode != 0:
            logger.info(stderr)
            return False
        
    else:
        logger.debug('{0} exist at expected location inside bundle'.format(qtname))    
    fix_binary(dep_abspath)
    return True

def fix_binary(binary):
    """
        input:
          binary: relative or absolute path (no @executable_path syntax)
        process:
        - first fix the rpath for the qt libs on which 'binary' depend
        - copy into the bundle of exepath the eventual libraries that are missing 
        - (create the soft links) needed ?
        - do the same for all qt dependencies of binary (recursive)
    """
    logger.debug('fix_binary({0})'.format(binary))    
       
    # loop on 'binary' dependencies
    for dep in get_dependencies(binary):
        if not fix_dependency(binary, dep):
            logger.error('quitting early: couldn\'t fix dependency {0} of {1}'.format(dep, binary))
            return False
    return True

def fix_main_binaries():
    """
        list the main binaries of the app bundle and fix them
    """
    # deduce bundle path
    global bundlepath
    bundlepath = os.path.sep.join(exepath.split(os.path.sep)[0:-3])

    # fix main binary
    logger.info('fixing main binary: {0}'.format(exepath))
    if fix_binary(exepath):
        logger.info('fixing all plugins')
        for root, dirs, files in os.walk(bundlepath):
            for name in filter(lambda f: os.path.splitext(f)[1] == '.dylib', files):
                logger.info('fixing plugin {0}'.format(name))
                if not fix_binary(os.path.join(root, name)):
                    return False
    return True 

logger = None

def main():

    descr = """finish the job started by macdeployqt!
 - find dependencies/rpathes with otool
 - copy missed dependencies  with cp and mkdir
 - fix missed rpathes        with install_name_tool

 exit codes:
 - 0 : success
 - 1 : error
 """

    parser = argparse.ArgumentParser(description=descr, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument('exepath', help='path to the binary depending on Qt')
    parser.add_argument('qtpath', help='path of Qt libraries used to build the Qt application')
    parser.add_argument('-q', '--quiet', action='store_true', default=False,
                                           help='do not create log on standard output')
    parser.add_argument('-nl', '--no-log-file', action='store_true', default=False,
                                           help='do not create log file \'./macdeployqtfix.log\'')
    parser.add_argument('-v', '--verbose', action='store_true', default=False,
                                           help='produce more log messages(debug log)')
    args = parser.parse_args() 

    # globals
    global qtpath
    qtpath = os.path.normpath(args.qtpath)
    global exepath
    exepath = args.exepath

    # configure logging
    ###################

    global logger
    logger = logging.getLogger()

    # create formatter
    formatter = logging.Formatter('%(levelname)s | %(message)s')
    # create console logger
    if not args.quiet:
        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(formatter)
        logger.addHandler(ch)

    # create file logger
    if not args.no_log_file:
        fh = logging.FileHandler('./macdeployqtfix.log', mode='w')
        fh.setFormatter(formatter)
        logger.addHandler(fh)

    if args.no_log_file and args.quiet:
        logger.addHandler(logging.NullHandler())
    else:
        if args.verbose:
            logger.setLevel(logging.DEBUG)
        else:
            logger.setLevel(logging.INFO)
 
    if fix_main_binaries():
        logger.info('process terminated with success')
        sys.exit(0)
    else:
        logger.error('process terminated with error')
        sys.exit(1)

if __name__ == "__main__":

    main()

