"""
WSGI config for proj project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/1.11/howto/deployment/wsgi/
"""

import os
import sys
import site

from os import environ


rundir = os.path.dirname(os.path.abspath(__file__))
basedir = "%s/.."%(rundir)
# Activate the virtual env
activate_env="%s/env/bin/activate_this.py"%(basedir)
execfile(activate_env, dict(__file__=activate_env))
os.system("which python")

#Add the site-packages of the virtualenv
site.addsitedir("%s/env/lib/python2.7/site-packages/"%(basedir))
site.addsitedir("/usr/local/lib/python2.7/dist-packages")

# Add the directory for the project
sys.path.append(basedir)
sys.path.append(rundir)
sys.path.append("/usr/local/lib/python2.7/dist-packages")

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "proj.settings")

if 'LD_LIBRARY_PATH' in os.environ:
    os.environ['LD_LIBRARY_PATH'] = os.environ['LD_LIBRARY_PATH'] + ":" + "/usr/local/lib"
else:
    os.environ['LD_LIBRARY_PATH'] = "/usr/local/lib"

os.environ['KERAS_BACKEND'] = 'theano'
os.environ['THEANO_FLAGS'] = 'base_compiledir=/tmp/.theano/'

from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
