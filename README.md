# macdeployqtfix
To bundle a Qt application on Mac OSX, there is macdeployqt. To finish the job there is macdeployqtfix!

### Here what 'Finish the job' means:

 - find dependencies and [rpathes](https://en.wikipedia.org/wiki/Rpath) of the main binary and all the plugins that are present in the bundle
 - copy into the bundle the dependencies that were **missed** by *macdeployqt*
 - fix incorrect permissions
 - fix incorrect rpathes

### Dependencies
macdeployqtfix relies on `otool` and `install_name_tool` being on the `PATH`

### Usage

:exclamation: Before using `macdeployqt` you first have to use `macdeployqtfix`!


```
$ python macdeployqtfix.py -h
usage: macdeployqtfix.py [-h] [-q] [-nl] [-v] exepath qtpath

finish the job started by macdeployqt!
 - find dependencies/rpathes with otool
 - copy missed dependencies  with cp and mkdir
 - fix missed rpathes        with install_name_tool

 exit codes:
 - 0 : success
 - 1 : error
 

positional arguments:
  exepath             path to the binary depending on Qt
  qtpath              path of Qt libraries used to build the Qt application

optional arguments:
  -h, --help          show this help message and exit
  -q, --quiet         do not create log on standard output
  -nl, --no-log-file  do not create log file './macdeployqtfix.log'
  -v, --verbose       produce more log messages(debug log)

```
#### Example usage
For the following example environment:
- if your Qt application name is `APP`
- your bundle is located at `/path/to/bundle/`
- the Qt libs used to build your app are located at `/usr/local/Cellar/qt5/5.5.0/`
- then you should run :
```
python macdeployqtfix.py /path/to/bundle/Contents/MacOS/APP /usr/local/Cellar/qt5/5.5.0/
```

